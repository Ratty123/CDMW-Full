from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

from cdmw.constants import (
    DDS_MAGIC,
    DDPF_ALPHA,
    DDPF_ALPHAPIXELS,
    DDPF_LUMINANCE,
    DDPF_RGB,
)
from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled
from cdmw.core.archive_format import try_decrypt_archive_entry_data
from cdmw.core.dds_resource_limits import (
    DDS_MAX_DIMENSION,
    DDS_MAX_PAYLOAD_BYTES,
    checked_allocation_size,
    checked_dds_surface_byte_count,
    validate_dds_dimensions,
)
from cdmw.models import ArchiveEntry, RunCancelled


def get_archive_partial_dds_header(entry: ArchiveEntry) -> bytes:
    from cdmw.core.archive_preview_support import get_archive_partial_dds_header as owner

    return owner(entry)


def _dds_bytes_per_block(dxgi_format: int, four_cc: bytes) -> Optional[int]:
    block_8_formats = {71, 72, 80, 81}
    block_16_formats = {74, 75, 77, 78, 83, 84, 94, 95, 96, 98, 99}
    if dxgi_format in block_8_formats:
        return 8
    if dxgi_format in block_16_formats:
        return 16
    four_cc_upper = four_cc.upper()
    if four_cc_upper in {b"DXT1", b"BC4U", b"BC4S", b"ATI1"}:
        return 8
    if four_cc_upper in {b"DXT3", b"DXT5", b"BC5U", b"BC5S", b"ATI2", b"RXGB"}:
        return 16
    return None


def _dds_uncompressed_surface_size(
    width: int,
    height: int,
    pf_flags: int,
    rgb_bit_count: int,
    *,
    pitch_or_linear_size: int = 0,
    mip_level: int = 0,
) -> Optional[int]:
    if width <= 0 or height <= 0:
        return None
    if pf_flags & (DDPF_LUMINANCE | DDPF_RGB | DDPF_ALPHAPIXELS | DDPF_ALPHA):
        if rgb_bit_count > 0 and rgb_bit_count % 8 == 0:
            return checked_dds_surface_byte_count(
                width,
                height,
                max(1, rgb_bit_count // 8),
                label="DDS surface",
            )
    if pitch_or_linear_size > 0:
        row_pitch = max(1, pitch_or_linear_size >> max(0, mip_level))
        return checked_allocation_size(
            row_pitch,
            max(1, height),
            label="DDS surface",
        )
    return None


def _dds_surface_size(
    width: int,
    height: int,
    dxgi_format: int,
    four_cc: bytes,
    *,
    pf_flags: int = 0,
    rgb_bit_count: int = 0,
    pitch_or_linear_size: int = 0,
    mip_level: int = 0,
) -> int:
    bytes_per_block = _dds_bytes_per_block(dxgi_format, four_cc)
    if bytes_per_block is not None:
        return checked_dds_surface_byte_count(
            width,
            height,
            bytes_per_block,
            block_width=4,
            block_height=4,
            label="DDS surface",
        )
    raw_surface_size = _dds_uncompressed_surface_size(
        width,
        height,
        pf_flags,
        rgb_bit_count,
        pitch_or_linear_size=pitch_or_linear_size,
        mip_level=mip_level,
    )
    if raw_surface_size is not None:
        return raw_surface_size
    raise ValueError(
        f"Unsupported DDS partial compression format: DXGI={dxgi_format} FOURCC={four_cc!r}"
    )


def reconstruct_partial_dds(entry: ArchiveEntry, data: bytes) -> bytes:
    header = get_archive_partial_dds_header(entry)
    if len(header) < 0x80 or header[:4] != DDS_MAGIC:
        raise ValueError("Partial DDS header is missing or invalid.")
    if struct.unpack_from("<I", header, 4)[0] != 124:
        raise ValueError("Partial DDS header size is invalid.")
    payload_header = bytes(data[: len(header)])
    (
        _header_size,
        _flags,
        height,
        width,
        _pitch_or_linear_size,
        depth,
        mip_map_count,
        *reserved1_and_rest,
    ) = struct.unpack_from("<IIIIIII11I", header, 4)
    reserved1 = reserved1_and_rest[:11]
    pf_flags = struct.unpack_from("<I", header, 80)[0]
    ddspf_four_cc = header[84:88]
    rgb_bit_count = struct.unpack_from("<I", header, 88)[0]
    caps2 = struct.unpack_from("<I", header, 112)[0]
    is_dx10 = ddspf_four_cc == b"DX10"
    header_size = 0x94 if is_dx10 else 0x80
    if len(header) < header_size:
        raise ValueError("Partial DDS DX10 header is truncated.")
    width, height, mip_map_count = validate_dds_dimensions(width, height, mip_map_count or 1)
    if depth > DDS_MAX_DIMENSION:
        raise ValueError(f"DDS depth {depth} exceeds the {DDS_MAX_DIMENSION}px resource limit.")
    dxgi_format = struct.unpack_from("<I", header, 0x80)[0] if is_dx10 and len(header) >= 0x94 else 0
    dx10_array_size = struct.unpack_from("<I", header, 0x8C)[0] if is_dx10 and len(header) >= 0x94 else 1

    multi_chunk_supported_0 = dx10_array_size < 2 if is_dx10 else True
    multi_chunk_supported_1 = mip_map_count > 5 and (caps2 == 0 and depth < 2)
    use_single_chunk = not multi_chunk_supported_0 or not multi_chunk_supported_1

    if use_single_chunk:
        compressed_block_sizes = [reserved1[0]]
        decompressed_block_sizes = [reserved1[1]]
    else:
        compressed_block_sizes = list(reserved1[:4])
        decompressed_block_sizes: List[int] = []
        current_width = max(1, width)
        current_height = max(1, height)
        for _ in range(min(4, max(1, mip_map_count))):
            decompressed_block_sizes.append(
                _dds_surface_size(
                    current_width,
                    current_height,
                    dxgi_format,
                    ddspf_four_cc,
                    pf_flags=pf_flags,
                    rgb_bit_count=rgb_bit_count,
                    pitch_or_linear_size=_pitch_or_linear_size,
                    mip_level=len(decompressed_block_sizes),
                )
            )
            current_width = max(1, current_width >> 1)
            current_height = max(1, current_height >> 1)

    if len(payload_header) >= header_size and payload_header[:4] == DDS_MAGIC:
        payload_reserved = list(struct.unpack_from("<11I", payload_header, 32))
        if use_single_chunk:
            payload_compressed = [payload_reserved[0]]
            payload_decompressed = [payload_reserved[1]]
        else:
            payload_compressed = list(payload_reserved[: len(compressed_block_sizes)])
            payload_decompressed = decompressed_block_sizes
        payload_bytes_needed = sum(int(value) for value in payload_compressed if int(value) > 0)
        payload_decompressed_needed = sum(int(value) for value in payload_decompressed if int(value) > 0)
        current_bytes_needed = sum(int(value) for value in compressed_block_sizes if int(value) > 0)
        payload_chunk_table_is_plausible = (
            payload_bytes_needed > 0
            and header_size + payload_bytes_needed <= len(data)
            and payload_decompressed_needed > 0
            and payload_bytes_needed <= payload_decompressed_needed
            and (
                current_bytes_needed <= 0
                or header_size + current_bytes_needed > len(data)
                or payload_bytes_needed < current_bytes_needed
            )
        )
        if payload_chunk_table_is_plausible:
            compressed_block_sizes = payload_compressed
            if use_single_chunk:
                decompressed_block_sizes = payload_decompressed

    compressed_total = 0
    decompressed_total = 0
    for compressed_size, decompressed_size in zip(compressed_block_sizes, decompressed_block_sizes):
        if compressed_size <= 0 or decompressed_size <= 0:
            continue
        if compressed_size > len(data) - header_size - compressed_total:
            raise ValueError("Partial DDS block is truncated.")
        if decompressed_size > DDS_MAX_PAYLOAD_BYTES - header_size - decompressed_total:
            raise ValueError(
                f"Partial DDS output exceeds the {DDS_MAX_PAYLOAD_BYTES:,}-byte resource limit."
            )
        compressed_total += compressed_size
        decompressed_total += decompressed_size
    trailing_size = len(data) - header_size - compressed_total
    if trailing_size < 0:
        raise ValueError("Partial DDS block is truncated.")
    if header_size + decompressed_total + trailing_size > DDS_MAX_PAYLOAD_BYTES:
        raise ValueError(f"Partial DDS output exceeds the {DDS_MAX_PAYLOAD_BYTES:,}-byte resource limit.")

    current_data_offset = header_size
    output_data = bytearray(header[:header_size])
    for compressed_size, decompressed_size in zip(compressed_block_sizes, decompressed_block_sizes):
        if compressed_size <= 0 or decompressed_size <= 0:
            continue
        if compressed_size == decompressed_size:
            block = data[current_data_offset : current_data_offset + decompressed_size]
            if len(block) != decompressed_size:
                raise ValueError("Partial DDS block is truncated.")
            output_data.extend(block)
            current_data_offset += decompressed_size
            continue
        if lz4_block is None:
            raise ValueError("This entry uses Partial DDS reconstruction, but the lz4 Python package is not installed.")
        compressed_data = data[current_data_offset : current_data_offset + compressed_size]
        if len(compressed_data) != compressed_size:
            raise ValueError("Partial DDS block is truncated.")
        block = lz4_block.decompress(compressed_data, uncompressed_size=decompressed_size)
        if len(block) != decompressed_size:
            raise ValueError("Partial DDS block decompressed to an unexpected size.")
        output_data.extend(block)
        current_data_offset += compressed_size
    if current_data_offset < len(data):
        output_data.extend(data[current_data_offset:])
    return bytes(output_data)


def sanitize_archive_entry_output_path(entry: ArchiveEntry, output_root: Path) -> Path:
    pure_path = PurePosixPath(entry.path.replace("\\", "/"))
    safe_parts = [part for part in pure_path.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        raise ValueError(f"Archive entry has an invalid path: {entry.path}")
    package_root = entry.pamt_path.parent.name.strip() or "package"
    return output_root.joinpath(package_root, *safe_parts)


def find_available_output_path(target_path: Path, reserved_paths: Optional[set[str]] = None) -> Path:
    reserved = reserved_paths or set()
    if str(target_path).lower() not in reserved and not target_path.exists():
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        lowered = str(candidate).lower()
        if lowered not in reserved and not candidate.exists():
            return candidate
        counter += 1


def _read_archive_entry_raw_data_from_handle(
    handle: BinaryIO,
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    raise_if_cancelled(stop_event)
    read_size = entry.comp_size if entry.compressed else entry.orig_size
    handle.seek(entry.offset)
    data = handle.read(read_size)
    raise_if_cancelled(stop_event)
    return data


def read_archive_entry_raw_data(
    entry: ArchiveEntry,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    raise_if_cancelled(stop_event)
    if not entry.paz_file.exists():
        raise ValueError(f"Missing PAZ file: {entry.paz_file}")

    with entry.paz_file.open("rb") as handle:
        return _read_archive_entry_raw_data_from_handle(handle, entry, stop_event=stop_event)


def maybe_reconstruct_sparse_dds(entry: ArchiveEntry, data: bytes) -> Optional[Tuple[bytes, str]]:
    if entry.extension != ".dds":
        return None
    if not data.startswith(DDS_MAGIC):
        return None
    if len(data) >= entry.orig_size:
        return None
    if len(data) < 128:
        raise ValueError("Sparse DDS header is truncated.")
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mip_count = struct.unpack_from("<I", data, 28)[0] or 1
    validate_dds_dimensions(width, height, mip_count)
    if entry.orig_size > DDS_MAX_PAYLOAD_BYTES:
        raise ValueError(f"Sparse DDS output exceeds the {DDS_MAX_PAYLOAD_BYTES:,}-byte resource limit.")
    padded = data + (b"\x00" * (entry.orig_size - len(data)))
    return padded, "SparseDDS"


def _maybe_decompress_partial_par_container(
    entry: ArchiveEntry,
    data: bytes,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Tuple[bytes, str]]:
    if lz4_block is None:
        return None
    if entry.compression_type != 1 or len(data) < 0x50 or not data.startswith(b"PAR "):
        return None

    slots: List[Tuple[int, int, int]] = []
    file_offset = 0x50
    rebuilt_size = 0x50
    saw_compressed_section = False

    for slot in range(8):
        raise_if_cancelled(stop_event)
        slot_offset = 0x10 + slot * 8
        comp_size = struct.unpack_from("<I", data, slot_offset)[0]
        decomp_size = struct.unpack_from("<I", data, slot_offset + 4)[0]
        if decomp_size <= 0:
            continue

        chunk_size = comp_size if comp_size > 0 else decomp_size
        if chunk_size <= 0:
            return None
        if decomp_size > entry.orig_size or rebuilt_size + decomp_size > entry.orig_size:
            return None
        if file_offset + chunk_size > len(data):
            return None

        slots.append((comp_size, decomp_size, file_offset))
        file_offset += chunk_size
        rebuilt_size += decomp_size
        if comp_size > 0:
            saw_compressed_section = True

    if not saw_compressed_section:
        return None
    if file_offset != len(data) or rebuilt_size != entry.orig_size:
        return None

    rebuilt = bytearray(data[:0x50])
    for comp_size, decomp_size, chunk_offset in slots:
        raise_if_cancelled(stop_event)
        chunk_size = comp_size if comp_size > 0 else decomp_size
        chunk = data[chunk_offset : chunk_offset + chunk_size]
        if comp_size > 0:
            try:
                chunk = lz4_block.decompress(chunk, uncompressed_size=decomp_size)
            except Exception:
                return None
            if len(chunk) != decomp_size:
                return None
        rebuilt.extend(chunk)

    if len(rebuilt) != entry.orig_size:
        return None

    # Preserve section sizes but clear the stored compressed lengths so the
    # rebuilt payload behaves like a normal decompressed PAR for downstream parsers.
    for slot in range(8):
        struct.pack_into("<I", rebuilt, 0x10 + slot * 8, 0)

    return bytes(rebuilt), "PartialPAR"


def _decode_archive_entry_data(
    entry: ArchiveEntry,
    data: bytes,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    decompressed = False
    note = ""
    if entry.encrypted:
        raise_if_cancelled(stop_event)
        data, decrypt_note = try_decrypt_archive_entry_data(entry, data)
        if decrypt_note:
            note = decrypt_note
        raise_if_cancelled(stop_event)
    if entry.compressed:
        if entry.compression_type == 1:
            partial_par = _maybe_decompress_partial_par_container(
                entry,
                data,
                stop_event=stop_event,
            )
            if partial_par is not None:
                data, partial_note = partial_par
                decompressed = True
                note = ",".join(part for part in [note, partial_note] if part)
            elif entry.extension == ".dds":
                raise_if_cancelled(stop_event)
                data = reconstruct_partial_dds(entry, data)
                decompressed = True
                note = ",".join(part for part in [note, "PartialDDS"] if part)
            else:
                note = ",".join(
                    part
                    for part in [note, "PartialRaw"]
                    if part
                )
        elif entry.compression_type == 2:
            if lz4_block is None:
                raise ValueError("This entry uses LZ4 compression, but the lz4 Python package is not installed.")
            if entry.extension == ".dds" and (entry.orig_size <= 0 or entry.orig_size > DDS_MAX_PAYLOAD_BYTES):
                raise ValueError(
                    f"DDS output size {entry.orig_size:,} exceeds the "
                    f"{DDS_MAX_PAYLOAD_BYTES:,}-byte resource limit."
                )
            raise_if_cancelled(stop_event)
            data = lz4_block.decompress(data, uncompressed_size=entry.orig_size)
            if entry.extension == ".dds" and len(data) != entry.orig_size:
                raise ValueError("DDS block decompressed to an unexpected size.")
            decompressed = True
            note = ",".join(part for part in [note, "LZ4"] if part)
        else:
            reconstructed = maybe_reconstruct_sparse_dds(entry, data)
            if reconstructed is not None:
                data, sparse_note = reconstructed
                note = ",".join(part for part in [note, sparse_note] if part)
            else:
                raise ValueError(f"Unsupported archive compression type {entry.compression_type} for {entry.path}")
        raise_if_cancelled(stop_event)

    return data, decompressed, note


def read_archive_entry_data(
    entry: ArchiveEntry,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    prepared_path = getattr(entry, "prepared_path", None)
    if prepared_path is not None:
        path = Path(prepared_path)
        raise_if_cancelled(stop_event)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError(
                f"Prepared archive source is unavailable for {entry.path}: {path}"
            ) from exc
        expected_size = max(0, int(entry.orig_size or 0))
        if expected_size and size != expected_size:
            raise ValueError(
                f"Prepared archive source size changed for {entry.path}: "
                f"expected {expected_size:,} bytes, found {size:,}."
            )
        with path.open("rb") as stream:
            data = stream.read()
        raise_if_cancelled(stop_event)
        if len(data) != size:
            raise ValueError(f"Prepared archive source changed while reading {entry.path}.")
        expected_sha256 = (
            str(getattr(entry, "prepared_sha256", "") or "").strip().casefold()
        )
        if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ValueError(f"Prepared archive source checksum changed for {entry.path}.")
        note = ",".join(
            part
            for part in (
                str(getattr(entry, "prepared_note", "") or "").strip(),
                "standalone archive worker prepared source",
            )
            if part
        )
        return data, bool(entry.compressed), note
    try:
        from cdmw.core.archive_accelerator import read_archive_entry_data_native

        native_result = read_archive_entry_data_native(entry, stop_event=stop_event)
        if native_result is not None:
            return native_result
    except RunCancelled:
        raise
    except Exception:
        pass
    data = read_archive_entry_raw_data(entry, stop_event=stop_event)
    return _decode_archive_entry_data(entry, data, stop_event=stop_event)


def _read_archive_entry_data_from_handle(
    handle: BinaryIO,
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    data = _read_archive_entry_raw_data_from_handle(handle, entry, stop_event=stop_event)
    return _decode_archive_entry_data(entry, data, stop_event=stop_event)


def extract_archive_entry(
    entry: ArchiveEntry,
    output_root: Path,
) -> Tuple[Path, bool, str]:
    data, decompressed, note = read_archive_entry_data(entry)
    out_path = output_root
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path, decompressed, note


def extract_archive_entries(
    entries: Sequence[ArchiveEntry],
    output_root: Path,
    *,
    collision_mode: str = "overwrite",
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, int]:
    output_root.mkdir(parents=True, exist_ok=True)
    total = len(entries)
    extracted = 0
    decompressed = 0
    failed = 0
    duplicate_targets: Dict[str, int] = defaultdict(int)
    renamed = 0
    used_targets: set[str] = set()
    last_progress_emit_at = 0.0
    progress_interval = max(total // 200, 1) if total > 0 else 1

    def emit_progress(current: int, detail: str, *, force: bool = False) -> None:
        nonlocal last_progress_emit_at
        if on_progress is None:
            return
        current = min(max(int(current), 0), total)
        now = time.monotonic()
        if (
            force
            or current == 0
            or current >= total
            or current % progress_interval == 0
            or now - last_progress_emit_at >= 0.25
        ):
            last_progress_emit_at = now
            on_progress(current, total, detail)

    emit_progress(0, f"Preparing to extract {total:,} archive file(s)...", force=True)
    for entry in entries:
        try:
            target_path = sanitize_archive_entry_output_path(entry, output_root)
            duplicate_targets[str(target_path).lower()] += 1
        except Exception:
            continue

    duplicate_count = sum(1 for count in duplicate_targets.values() if count > 1)
    if duplicate_count and on_log:
        on_log(
            f"Warning: {duplicate_count} extracted path(s) are duplicated across selected archive entries. "
            "Later entries will overwrite earlier extracted files."
        )
    if total:
        emit_progress(0, f"Extracting 0 / {total:,} archive file(s)...", force=True)

    for index, entry in enumerate(entries, start=1):
        raise_if_cancelled(stop_event)
        try:
            target_path = sanitize_archive_entry_output_path(entry, output_root)
            if collision_mode == "rename":
                resolved_path = find_available_output_path(target_path, used_targets)
                if resolved_path != target_path:
                    renamed += 1
            else:
                resolved_path = target_path
            used_targets.add(str(resolved_path).lower())
            out_path, was_decompressed, note = extract_archive_entry(entry, resolved_path)
            extracted += 1
            if was_decompressed:
                decompressed += 1
            if on_log:
                flags = []
                if note and note not in flags:
                    flags.append(note)
                elif was_decompressed:
                    flags.append("Decompressed")
                if collision_mode == "rename" and out_path != target_path:
                    flags.append("Renamed")
                extra = f" [{' '.join(flags)}]" if flags else ""
                on_log(f"[{index}/{total}] EXTRACT {entry.path}{extra} -> {out_path}")
            emit_progress(index, f"Extracted {index:,} / {total:,}: {entry.path}")
        except Exception as exc:
            failed += 1
            if on_log:
                on_log(f"[{index}/{total}] FAIL {entry.path} -> {exc}")
            emit_progress(index, f"Extracted {index:,} / {total:,} with {failed:,} failure(s): {entry.path}")

    emit_progress(total, f"Archive extraction complete: {extracted:,} extracted, {failed:,} failed.", force=True)
    return {
        "total": total,
        "extracted": extracted,
        "decompressed": decompressed,
        "renamed": renamed,
        "failed": failed,
    }


def directory_has_contents(path: Path) -> bool:
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def _background_delete_directory(path: Path) -> None:
    if not path.exists():
        return
    if os.name == "nt":
        subprocess.Popen(
            ["cmd.exe", "/d", "/c", "rmdir", "/s", "/q", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_subprocess_kwargs(),
        )
        return
    shutil.rmtree(path, ignore_errors=True)


def clear_directory_contents(path: Path) -> None:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError(f"Refusing to clear root directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    children = list(resolved.iterdir())
    if not children:
        return

    trash_root = Path(
        tempfile.mkdtemp(
            prefix=f"__ctf_pending_delete_{resolved.name}_",
            dir=str(resolved.parent),
        )
    )

    try:
        for child in children:
            target = trash_root / child.name
            suffix = 1
            while target.exists():
                target = trash_root / f"{child.name}.{suffix}"
                suffix += 1
            try:
                child.replace(target)
            except OSError:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        _background_delete_directory(trash_root)
    except Exception:
        shutil.rmtree(trash_root, ignore_errors=True)
        raise


def count_existing_archive_targets(entries: Sequence[ArchiveEntry], output_root: Path) -> int:
    return sum(1 for entry in entries if sanitize_archive_entry_output_path(entry, output_root).exists())


def format_byte_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{size} B"


def sanitize_cache_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", name).strip(" .")
    return sanitized or "preview.bin"


def build_archive_entry_metadata_summary(entry: ArchiveEntry) -> str:
    flags: List[str] = []
    if entry.compressed:
        flags.append(entry.compression_label)
    if entry.encrypted:
        flags.append("Encrypted")
    flags_text = f" | {' | '.join(flags)}" if flags else ""
    return (
        f"{entry.extension or 'no extension'} | {format_byte_size(entry.orig_size)}"
        f" | Stored {format_byte_size(entry.comp_size)}{flags_text}"
    )


def build_archive_entry_detail_text(entry: ArchiveEntry, extra_detail: str = "") -> str:
    lines = [
        f"Path: {entry.path}",
        f"Package: {entry.package_label}",
        f"PAMT: {entry.pamt_path}",
        f"PAZ: {entry.paz_file}",
        f"Offset: {entry.offset:,}",
        f"Original size: {entry.orig_size:,} bytes ({format_byte_size(entry.orig_size)})",
        f"Stored size: {entry.comp_size:,} bytes ({format_byte_size(entry.comp_size)})",
        f"Compression: {entry.compression_label}",
        f"Encrypted: {'Yes' if entry.encrypted else 'No'}",
    ]
    if extra_detail.strip():
        lines.extend(["", extra_detail.strip()])
    return "\n".join(lines)
