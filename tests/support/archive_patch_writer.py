"""The direct game-archive writers, kept for tests only (decision 39).

CDMW never writes into the game's archives. These are the writers an older
CDMW used to patch PAMT/PAZ files in place; tests use them on owned copies in
a temporary folder, to make the state Restore Backup and the overlay
migration undo. Nothing under cdmw/ imports this module, and
tests/test_no_game_archive_writes.py fails if anything there starts to.

Helpers that stay in cdmw.core.archive_patching (backups, payload encoding,
the checksum) are reached through that module at call time, so patching them
there still reaches this code.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core import archive_patching as _core
from cdmw.domain.archives.mutation import ArchivePatchRequest, ArchivePatchResult
from cdmw.models import ArchiveEntry


def __getattr__(name):
    # Everything else of the old module, read from core at call time.
    return getattr(_core, name)


#: Every shipped PAMT stores its per-PAZ record as (paz index, checksum of the
#: PAZ bytes, PAZ size). Measured on the installed build: 0020/0.pamt holds
#: (0, 0x09B7964E, 7427056) for a 7,427,056-byte 0.paz whose pa-checksum is
#: 0x09B7964E, and 0009/0.pamt runs 0, 1, 2 ... in the first field.
_PAZ_RECORD_INDEX_OFFSET = 0


_PAZ_RECORD_CHECKSUM_OFFSET = 4


_PAZ_RECORD_SIZE_OFFSET = 8


@dataclass(slots=True)
class _MutablePazRecord:
    index: int
    entry_offset: int
    checksum: int
    size: int
    #: The index the record itself states; equals `index` in every shipped table.
    stored_index: int = 0


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
        stored_index, checksum, size = struct.unpack_from("<III", data, record_offset)
        paz_records[paz_index] = _MutablePazRecord(
            index=paz_index,
            entry_offset=record_offset,
            checksum=checksum,
            size=size,
            stored_index=stored_index,
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
    if file_table_offset + file_table_size != len(data):
        raise ValueError("Compact or extended PAMT indexes are read-only; archive patching is not supported for this layout.")
    file_table = memoryview(data)[file_table_offset : file_table_offset + file_table_size]

    resolver = _core._VfsPathResolver(file_names)
    dir_resolver = _core._VfsPathResolver(directory_data, max_cache_entries=50_000)
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
        normalized_path = _core._normalize_virtual_path(full_path)
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
            _core._validate_archive_patch_compression_type(request.entry.compression_type)
            normalized_path = _core._normalize_virtual_path(request.entry.path)
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


def _write_paz_record(raw: bytearray, record_offset: int, *, checksum: int, size: int) -> None:
    """Rewrite a PAZ record's checksum and size, leaving its index field alone."""

    struct.pack_into("<I", raw, record_offset + _PAZ_RECORD_CHECKSUM_OFFSET, int(checksum) & 0xFFFFFFFF)
    struct.pack_into("<I", raw, record_offset + _PAZ_RECORD_SIZE_OFFSET, int(size) & 0xFFFFFFFF)


def _write_paz_payload(entry: ArchiveEntry, payload: bytes) -> int:
    return _append_paz_payload(entry.paz_file, payload)


def _append_paz_payload(paz_path: Path, payload: bytes) -> int:
    padded_payload = _pad_to_16(payload)

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
    computed_papgt_crc = _core._calculate_pa_checksum(papgt_data[12:])
    if stored_papgt_crc != computed_papgt_crc:
        raise ValueError(
            f"PAPGT checksum verification failed: stored=0x{stored_papgt_crc:08X} computed=0x{computed_papgt_crc:08X}"
        )

    for pamt_path in touched_pamt_paths:
        pamt_data = pamt_path.read_bytes()
        stored_pamt_crc = struct.unpack_from("<I", pamt_data, 0)[0]
        computed_pamt_crc = _core._calculate_pa_checksum(pamt_data[12:])
        if stored_pamt_crc != computed_pamt_crc:
            raise ValueError(
                f"PAMT checksum verification failed for {pamt_path.name}: "
                f"stored=0x{stored_pamt_crc:08X} computed=0x{computed_pamt_crc:08X}"
            )


def paz_checksums(paths: Sequence[Path], *, on_log: Optional[Callable[[str], None]] = None) -> Dict[Path, Tuple[int, int]]:
    """`{path: (checksum, size)}` for whole archive payload files.

    The native accelerator hashes them out of process at about 1 GB/s; without it the
    same files go through the Python hash at about 6 MiB/s, which is where an install
    used to spend most of its minutes.
    """

    wanted = [Path(path) for path in paths]
    if not wanted:
        return {}
    try:
        from cdmw.core.archive_accelerator import checksum_files_native

        native = checksum_files_native(wanted)
    except Exception:  # noqa: BLE001 - a missing or unhappy helper is not an error
        native = None
    if native is not None:
        _core._safe_log(on_log, f"Checksums for {len(wanted)} archive file(s) read by the native accelerator.")
        return dict(native)
    out: Dict[Path, Tuple[int, int]] = {}
    for path in wanted:
        _core._safe_log(on_log, f"Recalculating checksum for {path.name} ({_core._format_progress_size(path.stat().st_size)})...")
        data = path.read_bytes()
        out[path] = (_core._calculate_pa_checksum(data), len(data))
    return out


def _refresh_changed_entries(pamt_paths: Iterable[Path], changed_paths: Iterable[str]) -> Dict[str, ArchiveEntry]:
    from cdmw.core.archive_format import parse_archive_pamt

    changed_lookup = {_core._normalize_virtual_path(path) for path in changed_paths}
    refreshed: Dict[str, ArchiveEntry] = {}
    for pamt_path in pamt_paths:
        for entry in parse_archive_pamt(pamt_path, paz_dir=pamt_path.parent):
            normalized = _core._normalize_virtual_path(entry.path)
            if normalized in changed_lookup:
                refreshed[normalized] = entry
    return refreshed


def _run_archive_mutation(
    *,
    papgt_path: Path,
    ordered_pamts: Sequence[Path],
    backup_targets: Iterable[Path],
    description: str,
    changed_paths: Sequence[str],
    added_paths: Sequence[str],
    apply_group: Callable[[Path], int],
    on_log: Optional[Callable[[str], None]] = None,
    meta_writes: Optional[Mapping[str, Tuple[Path, bytes]]] = None,
) -> ArchivePatchResult:
    """Back up, apply one package group at a time, rechain the PAPGT, verify, or restore.

    `apply_group` writes one group's PAMT and returns its new crc. Everything
    around it (backup set, PAPGT slot, chain verification, restore on failure,
    entry refresh) is shared by in-place patching and by the rebuild that adds
    entries, so it lives here once. `meta_writes` (relative path -> (file, bytes))
    are whole loose files beside the archives (`meta/0.pathc`) written after the
    chain verifies, inside the same backup, so a failure anywhere restores them too.
    """

    total = len(changed_paths)
    metas = dict(meta_writes or {})
    _core._safe_log(on_log, f"Creating archive patch backup for {total} entrie(s)...")
    backup_dir = _core._create_backup(sorted(set(backup_targets) | {target for target, _payload in metas.values()}), description=description, on_log=on_log)
    _core._safe_log(on_log, f"Backup created: {backup_dir}")
    warnings: List[str] = []
    touched_pamt_paths: List[Path] = []

    try:
        papgt_raw = bytearray(papgt_path.read_bytes())
        for pamt_path in ordered_pamts:
            pamt_crc = apply_group(pamt_path)
            touched_pamt_paths.append(pamt_path)
            struct.pack_into("<I", papgt_raw, _papgt_crc_offset(papgt_path, pamt_path.parent.name), pamt_crc)

        _core._safe_log(on_log, f"Writing updated {papgt_path.name}...")
        struct.pack_into("<I", papgt_raw, 4, _core._calculate_pa_checksum(bytes(papgt_raw[12:])))
        _write_bytes_preserve_timestamps(papgt_path, bytes(papgt_raw))

        _core._safe_log(on_log, "Verifying archive checksum chain...")
        _verify_crc_chain(papgt_path, touched_pamt_paths)
        for relative, (meta_path, payload) in metas.items():
            _core._safe_log(on_log, f"Writing {relative} ({_core._format_progress_size(len(payload))})...")
            _write_bytes_preserve_timestamps(meta_path, bytes(payload))
    except Exception:
        _core._safe_log(on_log, f"Patch failed. Restoring files from backup: {backup_dir}")
        _core._restore_backup(backup_dir, on_log=on_log)
        raise

    _core._safe_log(on_log, "Refreshing changed archive entries...")
    refreshed_entries = _refresh_changed_entries(touched_pamt_paths, changed_paths)
    _core._safe_log(on_log, f"Patch complete. Backup available at {backup_dir}")
    return ArchivePatchResult(
        backup_dir=backup_dir,
        changed_entries=refreshed_entries,
        changed_paths=list(changed_paths),
        warnings=warnings,
        added_paths=list(added_paths),
        meta_paths=list(metas),
    )


def _apply_in_place_patches(
    pamt_path: Path,
    mutable: _MutablePamt,
    group_requests: Sequence[ArchivePatchRequest],
    *,
    on_log: Optional[Callable[[str], None]],
) -> int:
    """Rewrite existing file records in place; returns the new PAMT crc."""

    touched_paz_indices: set[int] = set()
    group_name = pamt_path.parent.name
    _core._safe_log(on_log, f"Updating {group_name}/{pamt_path.name} ({len(group_requests)} entrie(s))...")

    for request in group_requests:
        normalized_path = _core._normalize_virtual_path(request.entry.path)
        mutable_record = mutable.file_records.get(normalized_path)
        if mutable_record is None:
            raise ValueError(f"Could not locate {request.entry.path} inside {pamt_path.name}.")

        _core._safe_log(on_log, f"Preparing payload for {request.entry.path}...")
        processed_payload = _core._compress_archive_payload(request.payload_data, request.entry.compression_type)
        if request.entry.encrypted:
            processed_payload = _core._crypt_archive_payload(processed_payload, request.entry.basename)

        _core._safe_log(
            on_log,
            f"Writing {request.entry.basename} to {request.entry.paz_file.name} at a safe append-only offset...",
        )
        new_offset = _write_paz_payload(request.entry, processed_payload)
        struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 4, new_offset)
        struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 8, len(processed_payload))
        struct.pack_into("<I", mutable.raw, mutable_record.record_offset + 12, len(request.payload_data))
        touched_paz_indices.add(int(mutable_record.paz_index))

    ordered = sorted(touched_paz_indices)
    paz_paths: List[Path] = []
    for paz_index in ordered:
        if mutable.paz_records.get(paz_index) is None:
            raise ValueError(f"PAMT {pamt_path.name} is missing PAZ table entry {paz_index}.")
        paz_path = pamt_path.parent / f"{paz_index}.paz"
        if not paz_path.is_file():
            raise FileNotFoundError(f"Could not find archive payload file {paz_path}.")
        paz_paths.append(paz_path)
    sums = paz_checksums(paz_paths, on_log=on_log)
    for paz_index, paz_path in zip(ordered, paz_paths):
        checksum, size = sums[paz_path]
        _write_paz_record(mutable.raw, mutable.paz_records[paz_index].entry_offset, checksum=checksum, size=size)

    _core._safe_log(on_log, f"Writing updated {pamt_path.name}...")
    pamt_crc = _core._calculate_pa_checksum(bytes(mutable.raw[12:]))
    struct.pack_into("<I", mutable.raw, 0, pamt_crc)
    _write_bytes_preserve_timestamps(pamt_path, bytes(mutable.raw))
    return pamt_crc


def patch_archive_entries(
    requests: Sequence[ArchivePatchRequest],
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchivePatchResult:
    """Replace existing entries in place. To add entries as well, see
    :func:`cdmw.core.archive_entry_addition.apply_archive_mutations`."""

    if not requests:
        raise ValueError("No archive modifications were provided.")

    package_roots = {_core._package_root_from_entry(request.entry).resolve() for request in requests}
    if len(package_roots) != 1:
        raise ValueError("Archive patching currently requires all modified entries to come from the same package root.")
    papgt_path = _core._resolve_papgt_path(requests[0].entry)

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

    return _run_archive_mutation(
        papgt_path=papgt_path,
        ordered_pamts=list(grouped_requests),
        backup_targets=backup_targets,
        description=f"Patch {len(requests)} archive entrie(s)",
        changed_paths=[request.entry.path for request in requests],
        added_paths=(),
        apply_group=lambda pamt_path: _apply_in_place_patches(
            pamt_path, mutable_by_pamt[pamt_path], grouped_requests[pamt_path], on_log=on_log
        ),
        on_log=on_log,
    )
