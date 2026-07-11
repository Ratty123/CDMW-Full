from __future__ import annotations

import hashlib
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
    DDPF_ALPHA,
    DDPF_ALPHAPIXELS,
    DDPF_FOURCC,
    DDPF_LUMINANCE,
    DDPF_RGB,
    DDS_MAGIC,
)
from cdmw.models import ArchiveEntry, DdsInfo
from cdmw.core.atomic_file import atomic_publish_directory
from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled
from cdmw.core.archive_extraction import (
    _dds_bytes_per_block,
    _dds_surface_size,
    format_byte_size,
    read_archive_entry_data,
    sanitize_cache_filename,
)
from cdmw.core.archive_format import extract_binary_strings
from cdmw.core.archive_preview_support import resolve_archive_pathc_path
from cdmw.core.temp_cache import (
    app_temp_cache_build,
    app_temp_cache_path,
    app_temp_cache_use,
    mark_app_temp_cache_recent,
    request_app_temp_cache_prune,
)
from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds, parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.upscale_profiles import classify_texture_type, infer_texture_semantics

def _decode_dds_fourcc(fourcc: bytes) -> str:
    if not fourcc:
        return "-"
    try:
        text = fourcc.decode("ascii", errors="strict")
    except Exception:
        text = ""
    if text and all(32 <= ord(ch) <= 126 for ch in text):
        return text
    return "0x" + fourcc.hex().upper()


def _decode_dds_resource_dimension(value: int) -> str:
    return {
        0: "Unknown",
        1: "Buffer",
        2: "Texture1D",
        3: "Texture2D",
        4: "Texture3D",
    }.get(int(value), f"Unknown ({value})")


def _decode_dds_alpha_mode(value: int) -> str:
    return {
        0: "Unknown",
        1: "Straight",
        2: "Premultiplied",
        3: "Opaque",
        4: "Custom",
    }.get(int(value), f"Unknown ({value})")


def _decode_flag_names(value: int, mapping: Sequence[Tuple[int, str]]) -> str:
    names = [label for mask, label in mapping if value & mask]
    return ", ".join(names) if names else "-"


def _format_u32_list(values: Sequence[int]) -> str:
    if not values:
        return "-"
    return ", ".join(f"0x{int(value):08X}" for value in values)


def _format_hex_dump(data: bytes) -> str:
    if not data:
        return "-"
    lines: List[str] = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in chunk)
        lines.append(f"  {offset:04X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _dds_resource_type_from_caps(caps2: int) -> str:
    if caps2 & 0x00000200:
        return "Cubemap"
    if caps2 & 0x00200000:
        return "Texture3D"
    return "Texture2D"


def build_dds_header_detail_text(
    dds_path: Path,
    dds_info: Optional[DdsInfo] = None,
    *,
    logical_path: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    resolved_info = dds_info if dds_info is not None else parse_dds(dds_path)
    with dds_path.open("rb") as handle:
        blob = handle.read(148)
    if len(blob) < 128 or blob[:4] != DDS_MAGIC:
        raise ValueError("Missing DDS header.")

    header_magic = blob[:4]
    header = blob[4:128]
    header_size = struct.unpack_from("<I", header, 0)[0]
    header_flags = struct.unpack_from("<I", header, 4)[0]
    pitch_or_linear_size = struct.unpack_from("<I", header, 16)[0]
    depth = struct.unpack_from("<I", header, 20)[0]
    reserved1 = list(struct.unpack_from("<11I", header, 28))
    pf_flags = struct.unpack_from("<I", header, 76)[0]
    fourcc = header[80:84]
    rgb_bit_count = struct.unpack_from("<I", header, 84)[0]
    r_mask = struct.unpack_from("<I", header, 88)[0]
    g_mask = struct.unpack_from("<I", header, 92)[0]
    b_mask = struct.unpack_from("<I", header, 96)[0]
    a_mask = struct.unpack_from("<I", header, 100)[0]
    caps = struct.unpack_from("<I", header, 104)[0]
    caps2 = struct.unpack_from("<I", header, 108)[0]
    caps3 = struct.unpack_from("<I", header, 112)[0]
    caps4 = struct.unpack_from("<I", header, 116)[0]
    semantic_path_value = str(logical_path or dds_path).strip() or str(dds_path)
    semantic = infer_texture_semantics(
        semantic_path_value,
        sidecar_texts=sidecar_texts,
        original_texconv_format=resolved_info.texconv_format,
        has_alpha=resolved_info.has_alpha,
    )
    texture_type_hint = str(getattr(semantic, "texture_type", "") or "").strip().lower() or classify_texture_type(semantic_path_value)
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower()
    semantic_confidence = int(getattr(semantic, "confidence", 0) or 0)
    semantic_evidence = list(getattr(semantic, "evidence", ()) or [])
    is_dx10 = fourcc == b"DX10" and len(blob) >= 148
    dxgi_format = struct.unpack_from("<I", blob, 128)[0] if is_dx10 else 0
    resource_dimension = struct.unpack_from("<I", blob, 132)[0] if is_dx10 else 0
    misc_flag = struct.unpack_from("<I", blob, 136)[0] if is_dx10 else 0
    array_size = struct.unpack_from("<I", blob, 140)[0] if is_dx10 else 1
    misc_flags2 = struct.unpack_from("<I", blob, 144)[0] if is_dx10 else 0
    resource_type = _decode_dds_resource_dimension(resource_dimension) if is_dx10 else _dds_resource_type_from_caps(caps2)
    expected_mips = max(1, int(math.floor(math.log2(max(1, resolved_info.width, resolved_info.height, depth or 1)))) + 1)
    block_bytes = _dds_bytes_per_block(dxgi_format, fourcc)
    cube_face_count = 1
    if is_dx10 and (misc_flag & 0x4):
        cube_face_count = 6
    elif caps2 & 0x00000200:
        cube_face_count = sum(
            1
            for mask in (0x00000400, 0x00000800, 0x00001000, 0x00002000, 0x00004000, 0x00008000)
            if caps2 & mask
        ) or 6
    surface_instance_count = max(1, array_size) * max(1, cube_face_count)
    top_level_surface_bytes_text = "-"
    total_surface_bytes_text = "-"
    try:
        cur_w = max(1, resolved_info.width)
        cur_h = max(1, resolved_info.height)
        top_level_surface_bytes = _dds_surface_size(
            cur_w,
            cur_h,
            dxgi_format,
            fourcc,
            pf_flags=pf_flags,
            rgb_bit_count=rgb_bit_count,
            pitch_or_linear_size=pitch_or_linear_size,
            mip_level=0,
        )
        total_surface_bytes = 0
        for mip_index in range(max(1, resolved_info.mip_count)):
            total_surface_bytes += _dds_surface_size(
                cur_w,
                cur_h,
                dxgi_format,
                fourcc,
                pf_flags=pf_flags,
                rgb_bit_count=rgb_bit_count,
                pitch_or_linear_size=pitch_or_linear_size,
                mip_level=mip_index,
            )
            cur_w = max(1, cur_w >> 1)
            cur_h = max(1, cur_h >> 1)
        top_level_surface_bytes *= surface_instance_count
        total_surface_bytes *= surface_instance_count
        top_level_surface_bytes_text = f"{top_level_surface_bytes:,}"
        total_surface_bytes_text = f"{total_surface_bytes:,}"
    except Exception:
        pass
    file_sha256 = _sha256_path(dds_path)
    header_bytes = blob[:148] if is_dx10 else blob[:128]
    ddsd_flags = _decode_flag_names(
        header_flags,
        (
            (0x00000001, "CAPS"),
            (0x00000002, "HEIGHT"),
            (0x00000004, "WIDTH"),
            (0x00000008, "PITCH"),
            (0x00001000, "PIXELFORMAT"),
            (0x00020000, "MIPMAPCOUNT"),
            (0x00080000, "LINEARSIZE"),
            (0x00800000, "DEPTH"),
        ),
    )
    pixel_flag_names = _decode_flag_names(
        pf_flags,
        (
            (DDPF_ALPHAPIXELS, "ALPHAPIXELS"),
            (DDPF_ALPHA, "ALPHA"),
            (DDPF_FOURCC, "FOURCC"),
            (DDPF_RGB, "RGB"),
            (DDPF_LUMINANCE, "LUMINANCE"),
        ),
    )
    caps_names = _decode_flag_names(
        caps,
        (
            (0x00000008, "COMPLEX"),
            (0x00001000, "TEXTURE"),
            (0x00400000, "MIPMAP"),
        ),
    )
    caps2_names = _decode_flag_names(
        caps2,
        (
            (0x00000200, "CUBEMAP"),
            (0x00000400, "CUBEMAP_POSITIVEX"),
            (0x00000800, "CUBEMAP_NEGATIVEX"),
            (0x00001000, "CUBEMAP_POSITIVEY"),
            (0x00002000, "CUBEMAP_NEGATIVEY"),
            (0x00004000, "CUBEMAP_POSITIVEZ"),
            (0x00008000, "CUBEMAP_NEGATIVEZ"),
            (0x00200000, "VOLUME"),
        ),
    )
    crimson_info = inspect_crimson_dds(dds_path, vpath=logical_path)
    crimson_findings = [
        f"  - {finding.severity.upper()} {finding.code}: {finding.message}"
        for finding in crimson_info.findings
        if finding.code not in {"effective_last4"}
    ]
    crimson_last4_text = f"0x{crimson_info.effective_last4:04X}" if crimson_info.effective_last4 is not None else "-"
    crimson_last4_header_text = (
        f"0x{crimson_info.crimson_last4_header:04X}" if crimson_info.crimson_last4_header is not None else "-"
    )
    crimson_path_class_text = (
        f"0x{crimson_info.last4_path_class:04X}" if crimson_info.last4_path_class is not None else "-"
    )
    crimson_format_class_text = (
        f"0x{crimson_info.last4_format_derived:04X}" if crimson_info.last4_format_derived is not None else "-"
    )

    lines = [
        "DDS metadata:",
        f"- Format: {resolved_info.texconv_format}",
        f"- Dimensions: {resolved_info.width}x{resolved_info.height}",
        f"- Mip levels: {resolved_info.mip_count}",
        f"- Mip chain complete: {'Yes' if resolved_info.mip_count >= expected_mips else 'No'} ({resolved_info.mip_count}/{expected_mips} expected)",
        f"- Alpha: {'Yes' if resolved_info.has_alpha else 'No'}",
        f"- Colorspace intent: {resolved_info.colorspace_intent}",
        f"- Precision-sensitive: {'Yes' if resolved_info.precision_sensitive else 'No'}",
        f"- Texture type hint: {texture_type_hint}",
        f"- Semantic subtype: {semantic_subtype or '-'}",
        f"- Semantic confidence: {semantic_confidence}",
        f"- Semantic evidence: {semantic_evidence[0] if semantic_evidence else '-'}",
        f"- Resource type: {resource_type}",
        f"- DX10 header present: {'Yes' if is_dx10 else 'No'}",
        f"- DDS magic: {header_magic.decode('ascii', errors='replace')!r}",
        f"- Header size field: {header_size}",
        f"- Header flags: 0x{header_flags:08X}",
        f"- Header flag names: {ddsd_flags}",
        f"- Pitch / linear size: {pitch_or_linear_size:,}",
        f"- Depth: {depth or 1}",
        f"- Pixel format flags: 0x{pf_flags:08X}",
        f"- Pixel format names: {pixel_flag_names}",
        f"- FOURCC: {_decode_dds_fourcc(fourcc)}",
        f"- RGB bit count: {rgb_bit_count}",
        f"- Channel masks: R=0x{r_mask:08X} G=0x{g_mask:08X} B=0x{b_mask:08X} A=0x{a_mask:08X}",
        f"- Caps: 0x{caps:08X}",
        f"- Caps names: {caps_names}",
        f"- Caps2: 0x{caps2:08X}",
        f"- Caps2 names: {caps2_names}",
        f"- Caps3: 0x{caps3:08X}",
        f"- Caps4: 0x{caps4:08X}",
        f"- Block compression: {f'{block_bytes} bytes per 4x4 block' if block_bytes is not None else 'Uncompressed / direct pixel layout'}",
        f"- Surface instances: {surface_instance_count}",
        f"- Estimated top-level surface bytes: {top_level_surface_bytes_text}",
        f"- Estimated total surface bytes across listed mips: {total_surface_bytes_text}",
        f"- Resolved DDS file size: {dds_path.stat().st_size:,} bytes",
        f"- SHA-256: {file_sha256}",
        f"- Reserved1 values: {_format_u32_list(reserved1)}",
        "- Crimson DDS:",
        f"  - Effective last4: {crimson_last4_text}",
        f"  - Header last4: {crimson_last4_header_text}",
        f"  - Path-class last4: {crimson_path_class_text}",
        f"  - Format-derived last4: {crimson_format_class_text}",
        f"  - Requires PATHC/manifest registration: {'Yes' if crimson_info.requires_pathc else 'No'}",
        f"  - Findings: {len(crimson_findings):,}",
    ]
    if crimson_findings:
        lines.extend(crimson_findings)

    if is_dx10:
        lines.extend(
            [
                "- DX10 header:",
                f"  - DXGI format id: {dxgi_format}",
                f"  - Resource dimension: {_decode_dds_resource_dimension(resource_dimension)}",
                f"  - Array size: {array_size}",
                f"  - Misc flag: 0x{misc_flag:08X}",
                f"  - Misc flags2: 0x{misc_flags2:08X}",
                f"  - Alpha mode: {_decode_dds_alpha_mode(misc_flags2 & 0x7)}",
                f"  - Texture cube flag: {'Yes' if (misc_flag & 0x4) else 'No'}",
            ]
        )
    lines.extend(
        [
            "- Header hex dump:",
            _format_hex_dump(header_bytes),
        ]
    )
    return "\n".join(lines)


def ensure_archive_preview_source(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Path, str]:
    try:
        pamt_stat = entry.pamt_path.stat()
        pamt_stamp = f"{pamt_stat.st_size}:{pamt_stat.st_mtime_ns}"
    except OSError:
        pamt_stamp = "missing"
    try:
        paz_stat = entry.paz_file.stat()
        paz_stamp = f"{paz_stat.st_size}:{paz_stat.st_mtime_ns}"
    except OSError:
        paz_stamp = "missing"
    pathc_stamp = ""
    if entry.extension == ".dds" and entry.compression_type == 1:
        try:
            pathc_path = resolve_archive_pathc_path(entry)
            pathc_stat = pathc_path.stat()
            pathc_stamp = f"|{pathc_path.resolve()}|{pathc_stat.st_size}:{pathc_stat.st_mtime_ns}"
        except OSError:
            pathc_stamp = "|missing_pathc"

    cache_key = hashlib.sha256(
        (
            f"{entry.path}|{entry.pamt_path.resolve()}|{pamt_stamp}|{entry.paz_file.resolve()}|{paz_stamp}|"
            f"{entry.offset}|{entry.comp_size}|{entry.orig_size}|{entry.flags}{pathc_stamp}"
        ).encode("utf-8")
    ).hexdigest()
    suffix = Path(entry.path).suffix or ".bin"
    filename = sanitize_cache_filename(f"{Path(entry.path).stem}{suffix}")
    cache_dir = app_temp_cache_path("archive_preview_cache", cache_key)
    target_path = cache_dir / filename
    with app_temp_cache_build(cache_dir):
        try:
            if target_path.is_file() and target_path.stat().st_size > 0:
                note_path = cache_dir / ".note"
                note = note_path.read_text(encoding="utf-8") if note_path.is_file() else ""
                mark_app_temp_cache_recent(cache_dir)
                return target_path, note
        except (OSError, UnicodeError):
            pass

        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{cache_key}.",
                suffix=".staging",
                dir=cache_dir.parent,
            )
        )
        try:
            with app_temp_cache_use(staging_dir):
                data, _decompressed, note = read_archive_entry_data(entry, stop_event=stop_event)
                raise_if_cancelled(stop_event, "Archive preview extraction cancelled.")
                (staging_dir / filename).write_bytes(data)
                if note:
                    (staging_dir / ".note").write_text(note, encoding="utf-8")
                if cache_dir.is_symlink() or cache_dir.is_file():
                    cache_dir.unlink()
                elif cache_dir.is_dir():
                    shutil.rmtree(cache_dir)
                atomic_publish_directory(staging_dir, cache_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        mark_app_temp_cache_recent(cache_dir)
        request_app_temp_cache_prune()
        return target_path, note






def iter_archive_loose_file_candidates(
    entry: ArchiveEntry,
    search_roots: Sequence[Path],
) -> Sequence[Path]:
    pure_path = PurePosixPath(entry.path.replace("\\", "/"))
    safe_parts = [part for part in pure_path.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        return []

    package_root = entry.pamt_path.parent.name.strip()
    candidates: List[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        if not resolved_root.exists() or not resolved_root.is_dir():
            continue
        root_candidates = [resolved_root.joinpath(*safe_parts)]
        if package_root:
            root_candidates.append(resolved_root.joinpath(package_root, *safe_parts))
        for candidate in root_candidates:
            lowered = str(candidate).lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            if candidate.exists() and candidate.is_file():
                candidates.append(candidate)
    return candidates


def build_loose_archive_preview_assets(
    texconv_path: Optional[Path],
    loose_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, str, str]:
    resolved_path = loose_path.expanduser().resolve()
    suffix = resolved_path.suffix.lower()
    detail = f"Loose file preview from: {resolved_path}"
    raise_if_cancelled(stop_event)

    if suffix == ".dds":
        dds_info = None
        parse_error: Optional[Exception] = None
        try:
            dds_info = parse_dds(resolved_path)
            metadata_summary = (
                f"Loose DDS | Format: {dds_info.texconv_format} | "
                f"Size: {dds_info.width}x{dds_info.height} | Mips: {dds_info.mip_count}"
            )
        except Exception as exc:
            parse_error = exc
            metadata_summary = f"Loose DDS | {resolved_path.name}"
        preview_png = ensure_dds_display_preview_png(
            texconv_path.resolve() if texconv_path is not None and texconv_path.is_file() else None,
            resolved_path,
            dds_info=dds_info,
            stop_event=stop_event,
        )
        if parse_error is not None:
            detail += f"\nDDS metadata unavailable: {parse_error}"
        return str(preview_png), metadata_summary, detail

    if suffix in ARCHIVE_IMAGE_EXTENSIONS:
        return str(resolved_path), f"Loose image | {resolved_path.name}", detail

    return "", f"Loose file | {resolved_path.name}", detail + "\nThis loose file type cannot be previewed as an image."


def _format_media_duration_millis(duration_ms: int) -> str:
    total_seconds = max(0, int(duration_ms // 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _runtime_search_roots() -> List[Path]:
    roots: List[Path] = []
    seen: set[str] = set()

    def add_root(candidate: Optional[Path]) -> None:
        if candidate is None:
            return
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate.expanduser()
        lowered = str(resolved).lower()
        if not lowered or lowered in seen:
            return
        seen.add(lowered)
        roots.append(resolved)

    if getattr(sys, "frozen", False):
        add_root(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            add_root(Path(str(meipass)))
    add_root(Path(__file__).resolve().parents[2])
    return roots


def _resolve_vgmstream_cli_path() -> Optional[Path]:
    candidate_names = ("vgmstream-cli.exe", "test.exe")
    for root in _runtime_search_roots():
        for relative_dir in ("vgmstream", ".tools/vgmstream"):
            base_dir = root / relative_dir
            for candidate_name in candidate_names:
                candidate_path = base_dir / candidate_name
                if candidate_path.is_file():
                    return candidate_path
    return None


def _decode_wem_with_vgmstream(
    source_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Optional[Path], str]:
    cli_path = _resolve_vgmstream_cli_path()
    if cli_path is None:
        return None, "Bundled vgmstream decoder is not available in this build."

    output_path = source_path.with_name(f"{sanitize_cache_filename(source_path.stem)}.vgmstream.wav")
    if output_path.exists():
        try:
            if output_path.stat().st_size > 44 and output_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns:
                return output_path, "Decoded for playback with bundled vgmstream-cli."
        except OSError:
            pass

    command = [str(cli_path), "-o", str(output_path), str(source_path)]
    popen_kwargs: Dict[str, object] = {
        "cwd": str(cli_path.parent),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    popen_kwargs.update(hidden_subprocess_kwargs())
    process = subprocess.Popen(
        command,
        **popen_kwargs,
    )
    try:
        while True:
            try:
                return_code = process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                raise_if_cancelled(stop_event)
        stderr_text = ""
        if process.stderr is not None:
            try:
                stderr_text = process.stderr.read().strip()
            except Exception:
                stderr_text = ""
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        raise
    finally:
        if process.stderr is not None:
            try:
                process.stderr.close()
            except Exception:
                pass

    if return_code != 0 or not output_path.exists():
        return None, stderr_text or "vgmstream-cli could not decode this Wwise stream."
    return output_path, "Decoded for playback with bundled vgmstream-cli."


def _ensure_media_preview_source_path(
    source_path: Path,
    declared_extension: str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Path, str]:
    resolved_source = source_path.expanduser().resolve()
    normalized_extension = str(declared_extension or resolved_source.suffix).strip().lower()
    if normalized_extension != ".wem":
        return resolved_source, ""

    decoded_wav_path, decode_note = _decode_wem_with_vgmstream(
        resolved_source,
        stop_event=stop_event,
    )
    if decoded_wav_path is not None:
        return decoded_wav_path, decode_note

    raise_if_cancelled(stop_event)
    try:
        with resolved_source.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return resolved_source, decode_note
    if len(header) < 12 or not header.startswith(b"RIFF") or header[8:12] != b"WAVE":
        return resolved_source, decode_note

    alias_path = resolved_source.with_suffix(".wav")
    if alias_path == resolved_source:
        return resolved_source, decode_note
    if alias_path.exists() and alias_path.stat().st_size == resolved_source.stat().st_size:
        return alias_path, decode_note

    shutil.copy2(resolved_source, alias_path)
    return alias_path, decode_note


def _iter_riff_chunks(
    data: bytes,
    *,
    max_chunks: int = 32,
) -> List[Tuple[str, int, int]]:
    chunks: List[Tuple[str, int, int]] = []
    if len(data) < 12 or not data.startswith(b"RIFF"):
        return chunks
    offset = 12
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_name = chunk_id.decode("ascii", errors="replace")
        data_offset = offset + 8
        if data_offset > len(data):
            break
        chunks.append((chunk_name, chunk_size, data_offset))
        next_offset = data_offset + chunk_size
        if next_offset <= offset:
            break
        offset = next_offset + (chunk_size % 2)
    return chunks


def _build_wem_media_preview_detail_text(
    source_path: Path,
    data: bytes,
    *,
    loose: bool,
    playback_source_path: Optional[Path] = None,
    playback_note: str = "",
) -> Tuple[str, str]:
    resolved_source = source_path.expanduser().resolve()
    metadata_summary = f"{'Loose' if loose else 'Archive'} Wwise audio | {resolved_source.name}"
    detail_lines = [f"{'Loose file' if loose else 'Archive preview source'}: {resolved_source}"]
    if playback_source_path is not None:
        resolved_playback = playback_source_path.expanduser().resolve()
        if resolved_playback != resolved_source:
            detail_lines.append(f"Playback source: {resolved_playback}")
    if playback_note:
        detail_lines.append(playback_note)
    if len(data) < 12 or not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        detail_lines.append("Container sniffing did not confirm a RIFF/WAVE-style Wwise stream. Playback support may depend on the local multimedia backend.")
        return metadata_summary, "\n".join(detail_lines)

    detail_lines.append("Detected RIFF/WAVE-style Wwise audio container.")
    fmt_channels = None
    fmt_sample_rate = None
    fmt_bits_per_sample = None
    chunk_names: List[str] = []
    for chunk_name, chunk_size, chunk_offset in _iter_riff_chunks(data):
        chunk_names.append(f"{chunk_name} ({chunk_size:,} B)")
        if chunk_name == "fmt " and chunk_size >= 16 and chunk_offset + 16 <= len(data):
            try:
                _audio_format, fmt_channels, fmt_sample_rate, _byte_rate, _block_align, fmt_bits_per_sample = struct.unpack_from(
                    "<HHIIHH",
                    data,
                    chunk_offset,
                )
            except struct.error:
                fmt_channels = None
                fmt_sample_rate = None
                fmt_bits_per_sample = None
    if fmt_channels is not None and fmt_sample_rate is not None:
        metadata_summary = (
            f"{metadata_summary} | {fmt_channels} ch | {fmt_sample_rate:,} Hz"
            + (f" | {fmt_bits_per_sample}-bit" if fmt_bits_per_sample is not None else "")
        )
    if chunk_names:
        detail_lines.append("RIFF chunks: " + ", ".join(chunk_names[:12]))
    detail_lines.append(
        "Playback is best-effort through Qt Multimedia. Some Wwise `.wem` variants may still fail if the local backend cannot decode them."
    )
    return metadata_summary, "\n".join(detail_lines)


def _build_mp4_media_preview_detail_text(
    source_path: Path,
    *,
    loose: bool,
) -> Tuple[str, str]:
    resolved_source = source_path.expanduser().resolve()
    metadata_summary = f"{'Loose' if loose else 'Archive'} video | {resolved_source.name}"
    detail_lines = [
        f"{'Loose file' if loose else 'Archive preview source'}: {resolved_source}",
        "Embedded playback uses Qt Multimedia.",
    ]
    return metadata_summary, "\n".join(detail_lines)


def build_loose_archive_media_preview_assets(
    loose_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, str, str, str]:
    resolved_path = loose_path.expanduser().resolve()
    suffix = resolved_path.suffix.lower()
    raise_if_cancelled(stop_event)

    if suffix in ARCHIVE_VIDEO_EXTENSIONS:
        metadata_summary, detail_text = _build_mp4_media_preview_detail_text(resolved_path, loose=True)
        return str(resolved_path), "video", metadata_summary, detail_text

    if suffix in ARCHIVE_AUDIO_EXTENSIONS:
        media_source, playback_note = _ensure_media_preview_source_path(
            resolved_path,
            suffix,
            stop_event=stop_event,
        )
        try:
            with resolved_path.open("rb") as handle:
                sample = handle.read(131072)
        except OSError:
            sample = b""
        metadata_summary, detail_text = _build_wem_media_preview_detail_text(
            resolved_path,
            sample,
            loose=True,
            playback_source_path=media_source,
            playback_note=playback_note,
        )
        return str(media_source), "audio", metadata_summary, detail_text

    return "", "", f"Loose file | {resolved_path.name}", f"Loose file preview from: {resolved_path}"


def _iter_bnk_chunks(
    data: bytes,
    *,
    max_chunks: int = 32,
) -> List[Tuple[str, int, int]]:
    chunks: List[Tuple[str, int, int]] = []
    offset = 0
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        chunk_name = data[offset : offset + 4].decode("ascii", errors="replace")
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        data_offset = offset + 8
        if data_offset + chunk_size > len(data):
            break
        chunks.append((chunk_name, chunk_size, data_offset))
        next_offset = data_offset + chunk_size
        aligned_offset = (next_offset + 3) & ~3
        if aligned_offset <= offset:
            break
        offset = aligned_offset
    return chunks


def build_bnk_soundbank_preview(data: bytes) -> Tuple[str, str]:
    if len(data) < 8 or data[:4] != b"BKHD":
        return "", ""

    chunk_rows = _iter_bnk_chunks(data)
    if not chunk_rows:
        return "Detected Wwise soundbank container.", "Wwise soundbank preview is limited because the bank does not expose readable chunk boundaries."

    detail_lines = ["Detected Wwise soundbank container."]
    preview_lines = ["Wwise soundbank summary:"]
    chunk_descriptions: List[str] = []
    embedded_media_count = 0
    embedded_media_examples: List[str] = []
    hirc_object_count = None
    bank_version = None
    bank_id = None

    for chunk_name, chunk_size, chunk_offset in chunk_rows:
        chunk_descriptions.append(f"{chunk_name} ({chunk_size:,} B)")
        if chunk_name == "BKHD" and chunk_size >= 8:
            try:
                bank_version, bank_id = struct.unpack_from("<II", data, chunk_offset)
            except struct.error:
                bank_version = None
                bank_id = None
        elif chunk_name == "DIDX" and chunk_size >= 12:
            embedded_media_count = chunk_size // 12
            preview_lines.append(f"- Embedded media entries: {embedded_media_count:,}")
            for media_index in range(min(8, embedded_media_count)):
                media_id, media_offset, media_size = struct.unpack_from("<III", data, chunk_offset + media_index * 12)
                embedded_media_examples.append(
                    f"{media_id} @ {media_offset:,} ({format_byte_size(media_size)})"
                )
        elif chunk_name == "HIRC" and chunk_size >= 4:
            try:
                hirc_object_count = struct.unpack_from("<I", data, chunk_offset)[0]
            except struct.error:
                hirc_object_count = None

    if bank_version is not None:
        preview_lines.append(f"- Bank version: {bank_version}")
    if bank_id is not None:
        preview_lines.append(f"- Bank id: {bank_id}")
    preview_lines.append(f"- Top-level chunks: {', '.join(chunk_name for chunk_name, _chunk_size, _chunk_offset in chunk_rows)}")
    if hirc_object_count is not None:
        preview_lines.append(f"- HIRC objects: {hirc_object_count:,}")
    if embedded_media_examples:
        preview_lines.append("- First embedded media ids:")
        preview_lines.extend(f"  {example}" for example in embedded_media_examples)

    readable_strings = extract_binary_strings(data, sample_limit=262144, max_strings=24)
    if readable_strings:
        preview_lines.append("- Readable strings:")
        preview_lines.extend(f"  {text}" for text in readable_strings[:16])

    detail_lines.append("Top-level chunks: " + ", ".join(chunk_descriptions[:16]))
    if embedded_media_count:
        detail_lines.append(
            f"Embedded media index contains {embedded_media_count:,} item(s). These can be inspected, but direct bank playback is not exposed yet."
        )
    else:
        detail_lines.append("No embedded media index entries were detected in the top-level DIDX chunk.")

    return "\n".join(preview_lines), "\n".join(detail_lines)
