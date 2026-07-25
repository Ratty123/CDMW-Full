from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

try:
    import lz4.block as lz4_block
except Exception:  # pragma: no cover - optional dependency
    lz4_block = None  # type: ignore[assignment]

from cdmw.constants import APP_NAME, DDS_MAGIC
from cdmw.core.archive_format import VfsPathResolver
from cdmw.domain.archives.mutation import ArchivePatchRequest, ArchivePatchResult
from cdmw.models import ArchiveEntry

ARCHIVE_PATCH_BACKUP_ROOT = Path(tempfile.gettempdir()) / APP_NAME / "archive_patch_backups"


# The archive read path resolves VFS names with this exact resolver. Patch
# writes must agree with it entry-for-entry, so it is imported rather than
# re-implemented here.
_VfsPathResolver = VfsPathResolver


@dataclass(slots=True)
class _MutablePazRecord:
    index: int
    entry_offset: int
    checksum: int
    size: int


@dataclass(slots=True)
class _MutableFileRecord:
    path: str
    paz_index: int
    flags: int
    record_offset: int
    offset: int
    comp_size: int
    orig_size: int


@dataclass(slots=True)
class _MutablePamt:
    path: Path
    raw: bytearray
    paz_records: Dict[int, _MutablePazRecord]
    file_records: Dict[str, _MutableFileRecord]


def _normalize_virtual_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()

def _safe_log(log: Optional[Callable[[str], None]], message: str) -> None:
    if log is not None:
        log(message)

def _parse_mutable_pamt(pamt_path: Path) -> _MutablePamt:
    data = bytearray(pamt_path.read_bytes())
    if len(data) < 12:
        raise ValueError(f"{pamt_path} is too small to be a valid PAMT file.")

    off = 0
    _header_crc, paz_count, _unknown = struct.unpack_from("<III", data, off)
    off += 12

    paz_records: Dict[int, _MutablePazRecord] = {}
    for paz_index in range(paz_count):
        record_offset = off + (paz_index * 12)
        checksum, size, _reserved = struct.unpack_from("<III", data, record_offset)
        paz_records[paz_index] = _MutablePazRecord(
            index=paz_index,
            entry_offset=record_offset,
            checksum=checksum,
            size=size,
        )
    off += paz_count * 12

    if off + 4 > len(data):
        raise ValueError(f"{pamt_path.name} directory block length is truncated.")
    dir_block_size = struct.unpack_from("<I", data, off)[0]
    off += 4
    directory_data = bytes(data[off : off + dir_block_size])
    off += dir_block_size

    if off + 4 > len(data):
        raise ValueError(f"{pamt_path.name} file-name block length is truncated.")
    file_name_block_size = struct.unpack_from("<I", data, off)[0]
    off += 4
    file_names = bytes(data[off : off + file_name_block_size])
    off += file_name_block_size

    if off + 4 > len(data):
        raise ValueError(f"{pamt_path.name} folder table length is truncated.")
    folder_count = struct.unpack_from("<I", data, off)[0]
    off += 4
    folder_table_size = folder_count * 16
    if off + folder_table_size > len(data):
        raise ValueError(f"{pamt_path.name} folder table is truncated.")
    folder_table = memoryview(data)[off : off + folder_table_size]
    off += folder_table_size

    if off + 4 > len(data):
        raise ValueError(f"{pamt_path.name} file table length is truncated.")
    file_count = struct.unpack_from("<I", data, off)[0]
    off += 4
    file_table_offset = off
    file_table_size = file_count * struct.calcsize("<IIIIHH")
    if file_table_offset + file_table_size > len(data):
        raise ValueError(f"{pamt_path.name} file table is truncated.")
    file_table = memoryview(data)[file_table_offset : file_table_offset + file_table_size]

    resolver = _VfsPathResolver(file_names)
    dir_resolver = _VfsPathResolver(directory_data, max_cache_entries=50_000)
    folder_ranges = sorted(
        (
            file_start_index,
            file_start_index + folder_file_count,
            dir_resolver.get_full_path(name_offset).replace("\\", "/").strip("/"),
        )
        for _folder_hash, name_offset, file_start_index, folder_file_count in struct.iter_unpack("<IIII", folder_table)
        if folder_file_count > 0
    )

    file_records: Dict[str, _MutableFileRecord] = {}
    folder_cursor = 0
    record_stride = struct.calcsize("<IIIIHH")
    for entry_index, (name_offset, paz_offset, comp_size, orig_size, paz_index, flags) in enumerate(struct.iter_unpack("<IIIIHH", file_table)):
        relative_path = resolver.get_full_path(name_offset).replace("\\", "/").strip("/")
        guessed_dir = ""
        while folder_cursor < len(folder_ranges) and entry_index >= folder_ranges[folder_cursor][1]:
            folder_cursor += 1
        if folder_cursor < len(folder_ranges):
            start, end, candidate_dir = folder_ranges[folder_cursor]
            if start <= entry_index < end:
                guessed_dir = candidate_dir
        full_path = f"{guessed_dir}/{relative_path}".strip("/") if guessed_dir else relative_path
        normalized_path = _normalize_virtual_path(full_path)
        file_records[normalized_path] = _MutableFileRecord(
            path=full_path,
            paz_index=int(paz_index),
            flags=int(flags),
            record_offset=file_table_offset + (entry_index * record_stride),
            offset=int(paz_offset),
            comp_size=int(comp_size),
            orig_size=int(orig_size),
        )

    return _MutablePamt(path=pamt_path, raw=data, paz_records=paz_records, file_records=file_records)


def _calculate_pa_checksum(value: bytes) -> int:
    from cdmw.core.archive_format import calculate_pa_checksum

    return int(calculate_pa_checksum(value))


def _crypt_archive_payload(data: bytes, basename: str) -> bytes:
    from cdmw.core.archive_format import crypt_chacha20_filename

    return crypt_chacha20_filename(data, basename)


def _compress_archive_payload(data: bytes, compression_type: int) -> bytes:
    _validate_archive_patch_compression_type(compression_type)
    if compression_type in {0, 1}:
        return data
    if compression_type == 2:
        if lz4_block is None:
            raise ValueError("LZ4 support is not available in this build.")
        return lz4_block.compress(data, store_size=False)
    raise ValueError(f"Archive patching does not support compression type {compression_type} yet.")


def _validate_archive_patch_compression_type(compression_type: int) -> None:
    if int(compression_type) not in {0, 1, 2}:
        raise ValueError(f"Archive patching does not support compression type {compression_type} yet.")


def _preflight_archive_patch_requests(
    papgt_path: Path,
    grouped_requests: Mapping[Path, Sequence[ArchivePatchRequest]],
) -> Dict[Path, _MutablePamt]:
    for pamt_path in grouped_requests:
        if not pamt_path.is_file():
            raise FileNotFoundError(f"Could not find archive metadata file {pamt_path}.")
    _verify_crc_chain(papgt_path, grouped_requests.keys())

    mutable_by_pamt: Dict[Path, _MutablePamt] = {}
    for pamt_path, group_requests in grouped_requests.items():
        mutable = _parse_mutable_pamt(pamt_path)
        mutable_by_pamt[pamt_path] = mutable

        for request in group_requests:
            _validate_archive_patch_compression_type(request.entry.compression_type)
            normalized_path = _normalize_virtual_path(request.entry.path)
            mutable_record = mutable.file_records.get(normalized_path)
            if mutable_record is None:
                raise ValueError(f"Could not locate {request.entry.path} inside {pamt_path.name}.")
            if int(mutable_record.paz_index) != int(request.entry.paz_index):
                raise ValueError(
                    f"Archive entry {request.entry.path} no longer points at PAZ index {request.entry.paz_index}; "
                    f"current PAMT record points at PAZ index {mutable_record.paz_index}."
                )
            if mutable_record.paz_index not in mutable.paz_records:
                raise ValueError(f"PAMT {pamt_path.name} is missing PAZ table entry {mutable_record.paz_index}.")

            expected_paz_path = (pamt_path.parent / f"{mutable_record.paz_index}.paz").resolve()
            entry_paz_path = request.entry.paz_file.resolve()
            if entry_paz_path != expected_paz_path:
                raise ValueError(
                    f"Archive entry {request.entry.path} points at {entry_paz_path.name}, "
                    f"but the current PAMT record expects {expected_paz_path.name}."
                )
            if not expected_paz_path.is_file():
                raise FileNotFoundError(f"Could not find archive payload file {expected_paz_path}.")

    return mutable_by_pamt


def _write_bytes_preserve_timestamps(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp_path.open("wb") as handle:
        handle.write(data)
    os.replace(temp_path, path)


def _pad_to_16(data: bytes) -> bytes:
    padding = (-len(data)) % 16
    if padding <= 0:
        return data
    return data + (b"\x00" * padding)


def _format_progress_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024.0 * 1024.0):.1f} MB"
    return f"{size_bytes / (1024.0 * 1024.0 * 1024.0):.2f} GB"


def _copy_file_with_progress(
    source: Path,
    target: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    label: str = "",
) -> None:
    total_size = max(0, int(source.stat().st_size))
    copied = 0
    last_logged_percent = -10
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src_handle, target.open("wb") as dst_handle:
        while True:
            chunk = src_handle.read(16 * 1024 * 1024)
            if not chunk:
                break
            dst_handle.write(chunk)
            copied += len(chunk)
            if on_log is None or total_size <= 0:
                continue
            percent = min(100, int((copied * 100) / total_size))
            if percent >= 100 or percent - last_logged_percent >= 10:
                last_logged_percent = percent
                prefix = f"{label}: " if label else ""
                _safe_log(
                    on_log,
                    f"{prefix}{percent}% ({_format_progress_size(copied)} / {_format_progress_size(total_size)})",
                )
    shutil.copystat(source, target)


def _write_paz_payload(entry: ArchiveEntry, payload: bytes) -> int:
    padded_payload = _pad_to_16(payload)
    paz_path = entry.paz_file

    # Always append a new payload instead of overwriting or clearing the old slot.
    # This keeps the previous archive bytes intact until the updated PAMT has been
    # written successfully, which makes forced-close failures recoverable.
    with paz_path.open("r+b") as handle:
        handle.seek(0, os.SEEK_END)
        paz_size = handle.tell()
        new_offset = (paz_size + 15) & ~15
        if new_offset > paz_size:
            handle.write(b"\x00" * (new_offset - paz_size))
        handle.write(padded_payload)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    return new_offset


def _package_root_from_entry(entry: ArchiveEntry) -> Path:
    return entry.pamt_path.parent.parent


def _resolve_papgt_path(entry: ArchiveEntry) -> Path:
    root = _package_root_from_entry(entry)
    papgt_path = root / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise FileNotFoundError(f"Could not find PAPGT root index at {papgt_path}.")
    return papgt_path


def _read_printable_build_text(path: Path, *, limit: int = 4096) -> str:
    try:
        raw = path.read_bytes()[:limit]
    except OSError:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    text = "".join(ch if ch.isprintable() or ch in "\r\n\t" else " " for ch in text)
    return " ".join(text.split())[:240]


def _detect_archive_game_metadata(entry: ArchiveEntry) -> Dict[str, object]:
    metadata: Dict[str, object] = {
        "primary_package_group": str(getattr(entry.pamt_path.parent, "name", "") or ""),
    }
    root = _package_root_from_entry(entry)
    paver_path = root / "meta" / "0.paver"
    paver_text = _read_printable_build_text(paver_path)
    if paver_text:
        metadata["game_build"] = paver_text
    try:
        papgt_path = _resolve_papgt_path(entry)
        papgt_data = papgt_path.read_bytes()
        payload = papgt_data[12:] if len(papgt_data) >= 12 else papgt_data
        metadata["papgt_crc"] = f"0x{_calculate_pa_checksum(payload):08X}"
        metadata["papgt_size"] = len(papgt_data)
        metadata["papgt_sha256"] = hashlib.sha256(papgt_data).hexdigest()
    except Exception:
        pass
    try:
        pamt_data = entry.pamt_path.read_bytes()
        payload = pamt_data[12:] if len(pamt_data) >= 12 else pamt_data
        metadata["pamt_crc"] = f"0x{_calculate_pa_checksum(payload):08X}"
        metadata["pamt_size"] = len(pamt_data)
        metadata["pamt_sha256"] = hashlib.sha256(pamt_data).hexdigest()
    except Exception:
        pass
    if "game_build" not in metadata and "papgt_crc" in metadata:
        metadata["game_build"] = f"0.papgt {metadata['papgt_crc']}"
    return metadata


def _package_group_sort_order(package_root: Path) -> List[str]:
    groups: List[str] = []
    for child in sorted(package_root.iterdir()):
        if child.is_dir() and (child / "0.pamt").is_file():
            groups.append(child.name)
    return groups


def _papgt_crc_offset(papgt_path: Path, package_group: str) -> int:
    package_root = papgt_path.parent.parent
    groups = _package_group_sort_order(package_root)
    if package_group not in groups:
        raise ValueError(f"Package group {package_group} is not present under {package_root}.")
    index = groups.index(package_group)
    return 12 + (index * 12) + 8


def _verify_crc_chain(papgt_path: Path, touched_pamt_paths: Iterable[Path]) -> None:
    papgt_data = papgt_path.read_bytes()
    stored_papgt_crc = struct.unpack_from("<I", papgt_data, 4)[0]
    computed_papgt_crc = _calculate_pa_checksum(papgt_data[12:])
    if stored_papgt_crc != computed_papgt_crc:
        raise ValueError(
            f"PAPGT checksum verification failed: stored=0x{stored_papgt_crc:08X} computed=0x{computed_papgt_crc:08X}"
        )

    for pamt_path in touched_pamt_paths:
        pamt_data = pamt_path.read_bytes()
        stored_pamt_crc = struct.unpack_from("<I", pamt_data, 0)[0]
        computed_pamt_crc = _calculate_pa_checksum(pamt_data[12:])
        if stored_pamt_crc != computed_pamt_crc:
            raise ValueError(
                f"PAMT checksum verification failed for {pamt_path.name}: "
                f"stored=0x{stored_pamt_crc:08X} computed=0x{computed_pamt_crc:08X}"
            )


def _create_backup(
    files: Sequence[Path],
    *,
    description: str,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    backup_root = ARCHIVE_PATCH_BACKUP_ROOT
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp
    counter = 1
    while backup_dir.exists():
        backup_dir = backup_root / f"{timestamp}_{counter:02d}"
        counter += 1
    backup_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, str]] = []
    for path in files:
        if not path.exists():
            continue
        target_name = f"{path.parent.name}_{path.name}"
        target_path = backup_dir / target_name
        _safe_log(
            on_log,
            f"Backing up {path.name} to {backup_dir.name} ({_format_progress_size(path.stat().st_size)})...",
        )
        _copy_file_with_progress(path, target_path, on_log=on_log, label=f"Backup {path.name}")
        manifest.append(
            {
                "original_path": str(path),
                "backup_path": str(target_path),
            }
        )
    manifest_path = backup_dir / "backup_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "description": description,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "files": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return backup_dir


def _restore_backup(backup_dir: Path, *, on_log: Optional[Callable[[str], None]] = None) -> None:
    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Backup manifest was not found under {backup_dir}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for file_info in manifest.get("files", []):
        source = Path(str(file_info.get("backup_path", "")))
        target = Path(str(file_info.get("original_path", "")))
        if source.is_file():
            _safe_log(
                on_log,
                f"Restoring {target.name} from backup ({_format_progress_size(source.stat().st_size)})...",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target.with_name(f".{target.name}.{os.getpid()}.restore.tmp")
            try:
                _copy_file_with_progress(source, temp_target, on_log=on_log, label=f"Restore {target.name}")
                os.replace(temp_target, target)
            finally:
                if temp_target.exists():
                    try:
                        temp_target.unlink()
                    except OSError:
                        pass


def list_archive_patch_backups(*, limit: Optional[int] = None) -> List[Path]:
    if not ARCHIVE_PATCH_BACKUP_ROOT.is_dir():
        return []
    backups = [
        path
        for path in ARCHIVE_PATCH_BACKUP_ROOT.iterdir()
        if path.is_dir() and (path / "backup_manifest.json").is_file()
    ]
    backups.sort(key=lambda path: path.name, reverse=True)
    if limit is not None:
        return backups[: max(0, int(limit))]
    return backups


def restore_archive_patch_backup(
    backup_dir: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    resolved = backup_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Archive patch backup directory was not found: {resolved}")
    _restore_backup(resolved, on_log=on_log)
    return resolved

def _refresh_changed_entries(pamt_paths: Iterable[Path], changed_paths: Iterable[str]) -> Dict[str, ArchiveEntry]:
    from cdmw.core.archive_format import parse_archive_pamt

    changed_lookup = {_normalize_virtual_path(path) for path in changed_paths}
    refreshed: Dict[str, ArchiveEntry] = {}
    for pamt_path in pamt_paths:
        for entry in parse_archive_pamt(pamt_path, paz_dir=pamt_path.parent):
            normalized = _normalize_virtual_path(entry.path)
            if normalized in changed_lookup:
                refreshed[normalized] = entry
    return refreshed


def patch_archive_entries(
    requests: Sequence[ArchivePatchRequest],
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchivePatchResult:
    if not requests:
        raise ValueError("No archive modifications were provided.")

    package_roots = {_package_root_from_entry(request.entry).resolve() for request in requests}
    if len(package_roots) != 1:
        raise ValueError("Archive patching currently requires all modified entries to come from the same package root.")
    package_root = next(iter(package_roots))
    papgt_path = _resolve_papgt_path(requests[0].entry)

    grouped_requests: Dict[Path, List[ArchivePatchRequest]] = {}
    for request in requests:
        grouped_requests.setdefault(request.entry.pamt_path.resolve(), []).append(request)

    mutable_by_pamt = _preflight_archive_patch_requests(
        papgt_path=papgt_path,
        grouped_requests=grouped_requests,
    )

    backup_targets: List[Path] = [papgt_path]
    for pamt_path, group_requests in grouped_requests.items():
        backup_targets.append(pamt_path)
        backup_targets.extend({request.entry.paz_file.resolve() for request in group_requests})
    _safe_log(on_log, f"Creating archive patch backup for {len(requests)} entrie(s)...")
    backup_dir = _create_backup(
        sorted(set(backup_targets)),
        description=f"Patch {len(requests)} archive entrie(s)",
        on_log=on_log,
    )
    _safe_log(on_log, f"Backup created: {backup_dir}")
    warnings: List[str] = []
    touched_pamt_paths: List[Path] = []
    changed_paths = [request.entry.path for request in requests]

    try:
        papgt_raw = bytearray(papgt_path.read_bytes())

        for pamt_path, group_requests in grouped_requests.items():
            mutable = mutable_by_pamt[pamt_path]
            touched_paz_indices: set[int] = set()
            group_name = pamt_path.parent.name
            _safe_log(on_log, f"Updating {group_name}/{pamt_path.name} ({len(group_requests)} entrie(s))...")

            for request in group_requests:
                normalized_path = _normalize_virtual_path(request.entry.path)
                mutable_record = mutable.file_records.get(normalized_path)
                if mutable_record is None:
                    raise ValueError(f"Could not locate {request.entry.path} inside {pamt_path.name}.")

                _safe_log(on_log, f"Preparing payload for {request.entry.path}...")
                processed_payload = _compress_archive_payload(request.payload_data, request.entry.compression_type)
                if request.entry.encrypted:
                    processed_payload = _crypt_archive_payload(processed_payload, request.entry.basename)

                _safe_log(
                    on_log,
                    f"Writing {request.entry.basename} to {request.entry.paz_file.name} at a safe append-only offset...",
                )
                new_offset = _write_paz_payload(request.entry, processed_payload)
                struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 4, new_offset)
                struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 8, len(processed_payload))
                struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 12, len(request.payload_data))
                touched_paz_indices.add(int(mutable_record.paz_index))

            for paz_index in sorted(touched_paz_indices):
                paz_record = mutable.paz_records.get(paz_index)
                if paz_record is None:
                    raise ValueError(f"PAMT {pamt_path.name} is missing PAZ table entry {paz_index}.")
                paz_path = pamt_path.parent / f"{paz_index}.paz"
                if not paz_path.is_file():
                    raise FileNotFoundError(f"Could not find archive payload file {paz_path}.")
                _safe_log(on_log, f"Recalculating checksum for {paz_path.name}...")
                paz_data = paz_path.read_bytes()
                struct.pack_into("<I", mutable.raw, paz_record.entry_offset, _calculate_pa_checksum(paz_data))
                struct.pack_into("<I", mutable.raw, paz_record.entry_offset + 4, len(paz_data))

            _safe_log(on_log, f"Writing updated {pamt_path.name}...")
            pamt_crc = _calculate_pa_checksum(bytes(mutable.raw[12:]))
            struct.pack_into("<I", mutable.raw, 0, pamt_crc)
            _write_bytes_preserve_timestamps(pamt_path, bytes(mutable.raw))
            touched_pamt_paths.append(pamt_path)

            crc_offset = _papgt_crc_offset(papgt_path, group_name)
            struct.pack_into("<I", papgt_raw, crc_offset, pamt_crc)

        _safe_log(on_log, f"Writing updated {papgt_path.name}...")
        papgt_crc = _calculate_pa_checksum(bytes(papgt_raw[12:]))
        struct.pack_into("<I", papgt_raw, 4, papgt_crc)
        _write_bytes_preserve_timestamps(papgt_path, bytes(papgt_raw))

        _safe_log(on_log, "Verifying archive checksum chain...")
        _verify_crc_chain(papgt_path, touched_pamt_paths)
    except Exception:
        _safe_log(on_log, f"Patch failed. Restoring files from backup: {backup_dir}")
        _restore_backup(backup_dir, on_log=on_log)
        raise

    _safe_log(on_log, "Refreshing changed archive entries...")
    refreshed_entries = _refresh_changed_entries(touched_pamt_paths, changed_paths)
    _safe_log(on_log, f"Patch complete. Backup available at {backup_dir}")
    return ArchivePatchResult(
        backup_dir=backup_dir,
        changed_entries=refreshed_entries,
        changed_paths=changed_paths,
        warnings=warnings,
    )


def get_archive_texture_patch_blocker(entry: ArchiveEntry) -> str:
    if entry.extension != ".dds":
        return f"{entry.path} is not a DDS archive entry."
    if entry.compression_type == 1:
        return (
            "Direct archive patching for Partial DDS entries is not supported yet. "
            "Write a mod-ready loose replacement instead."
        )
    return ""

def build_archive_texture_payload_from_dds(
    entry: ArchiveEntry,
    replacement_dds_path: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> bytes:
    from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds, parse_dds

    if entry.extension != ".dds":
        raise ValueError(f"{entry.path} is not a DDS archive entry.")

    resolved_path = replacement_dds_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Replacement DDS was not found: {resolved_path}")

    pathc_last4: Optional[int] = None
    try:
        from cdmw.core.archive_preview_support import load_pathc_collection, resolve_archive_pathc_path

        pathc_path = resolve_archive_pathc_path(entry)
        if pathc_path.is_file():
            pathc_header = load_pathc_collection(pathc_path).get_file_header(entry.path)
            if len(pathc_header) >= 128 and pathc_header[:4] == DDS_MAGIC:
                pathc_last4 = struct.unpack_from("<I", pathc_header, 124)[0] or None
    except Exception:
        pathc_last4 = None

    crimson_info = inspect_crimson_dds(resolved_path, vpath=entry.path, pathc_last4=pathc_last4)
    fatal_messages = [finding.message for finding in crimson_info.findings if finding.severity == "fatal"]
    if fatal_messages:
        raise ValueError("; ".join(fatal_messages))
    for finding in crimson_info.findings:
        if finding.severity == "warning":
            _safe_log(on_log, f"Crimson DDS warning for {entry.path}: {finding.message}")
        elif finding.severity == "info" and finding.code == "requires_pathc":
            _safe_log(on_log, f"Crimson DDS note for {entry.path}: {finding.message}")

    parse_dds(resolved_path)
    return resolved_path.read_bytes()

def build_archive_texture_payload_from_png(
    entry: ArchiveEntry,
    replacement_png_path: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> bytes:
    from cdmw.core.archive_media_preview import ensure_archive_preview_source
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.domain.textures.output import max_mips_for_size

    if entry.extension != ".dds":
        raise ValueError(f"{entry.path} is not a DDS archive entry.")

    resolved_png = replacement_png_path.expanduser().resolve()
    if not resolved_png.is_file():
        raise FileNotFoundError(f"Replacement PNG was not found: {resolved_png}")

    original_dds_path, _note = ensure_archive_preview_source(entry)
    original_info = parse_dds(original_dds_path)

    target_stem = PurePosixPath(entry.path.replace("\\", "/")).stem or "replacement"
    with tempfile.TemporaryDirectory(prefix="ctf_archive_texture_rebuild_") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        normalized_png_path = temp_dir / f"{target_stem}.png"
        shutil.copy2(resolved_png, normalized_png_path)
        output_dir = temp_dir / "rebuilt"
        output_dir.mkdir(parents=True, exist_ok=True)
        mip_count = max(
            1,
            min(
                max_mips_for_size(original_info.width, original_info.height),
                int(original_info.mip_count or 1),
            ),
        )
        native_output_path = output_dir / f"{target_stem}.dds"
        try:
            from cdmw.core.texture_native import encode_dds_with_directxtex

            native_report = encode_dds_with_directxtex(
                normalized_png_path,
                native_output_path,
                dds_format=original_info.dds_format,
                width=original_info.width,
                height=original_info.height,
                mip_count=mip_count,
                timeout_seconds=120.0,
            )
        except Exception as exc:
            native_report = None
            _safe_log(on_log, f"DirectXTex native DDS rebuild unavailable for {entry.path}: {exc}")
        if native_report and native_output_path.is_file():
            _safe_log(
                on_log,
                (
                    f"Rebuilt DDS for {entry.path} from {resolved_png.name} "
                    f"with DirectXTex native backend using {original_info.dds_format} "
                    f"at {original_info.width}x{original_info.height}."
                ),
            )
            return native_output_path.read_bytes()

        raise RuntimeError(f"Native DDS rebuild failed for {entry.path}.")
