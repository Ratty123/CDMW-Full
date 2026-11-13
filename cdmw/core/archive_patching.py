from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

try:
    import lz4.block as lz4_block
except Exception:  # pragma: no cover - optional dependency
    lz4_block = None  # type: ignore[assignment]

from cdmw.constants import APP_NAME, DDS_MAGIC
from cdmw.core.archive_format import VfsPathResolver
# Re-exported: other modules import the request types from here.
from cdmw.domain.archives.mutation import ArchivePatchRequest, ArchivePatchResult  # noqa: F401
from cdmw.models import ArchiveEntry

ARCHIVE_PATCH_BACKUP_ROOT = Path(tempfile.gettempdir()) / APP_NAME / "archive_patch_backups"


# The archive read path resolves VFS names with this exact resolver. Patch
# writes must agree with it entry-for-entry, so it is imported rather than
# re-implemented here.
_VfsPathResolver = VfsPathResolver


def _normalize_virtual_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()

def _safe_log(log: Optional[Callable[[str], None]], message: str) -> None:
    if log is not None:
        log(message)


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


def _package_root_from_entry(entry: ArchiveEntry) -> Path:
    return entry.pamt_path.parent.parent


def _resolve_papgt_path(entry: ArchiveEntry) -> Path:
    root = _package_root_from_entry(entry)
    papgt_path = root / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise FileNotFoundError(f"Could not find PAPGT root index at {papgt_path}.")
    return papgt_path


def _read_printable_build_text(path: Path, *, limit: int = 4096) -> str:
    from cdmw.core.mod_compatibility import decode_paver_build

    try:
        raw = path.read_bytes()[:limit]
    except OSError:
        return ""
    return decode_paver_build(raw)


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
    for number, path in enumerate(files, start=1):
        if not path.exists():
            continue
        # A running number keeps two files with the same folder and file name apart
        # (generations/g1/packages/a.cditem and generations/g2/packages/a.cditem);
        # the manifest records which copy goes where.
        target_name = f"{number:05d}_{path.parent.name}_{path.name}"
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


def _restore_backup(
    backup_dir: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    pairs: Optional[Sequence[Tuple[Path, Path]]] = None,
) -> None:
    """Copy every backed-up file back. ``pairs`` is the (copy, target) list a caller already checked."""

    if pairs is None:
        manifest_path = backup_dir / "backup_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Backup manifest was not found under {backup_dir}.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pairs = [(Path(str(file_info.get("backup_path", ""))), Path(str(file_info.get("original_path", ""))))
                 for file_info in manifest.get("files", [])]
    for source, target in pairs:
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
    pairs: Optional[Sequence[Tuple[Path, Path]]] = None,
) -> Path:
    resolved = backup_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Archive patch backup directory was not found: {resolved}")
    _restore_backup(resolved, on_log=on_log, pairs=pairs)
    return resolved


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
