from __future__ import annotations

import math
import struct
from pathlib import Path, PurePosixPath
from typing import Dict, List, Literal, Optional, Tuple

from cdmw.constants import (
    DDS_MAGIC,
    DDPF_ALPHA,
    DDPF_ALPHAPIXELS,
    DDPF_FOURCC,
    DDPF_LUMINANCE,
    DDPF_RGB,
    DXGI_TO_TEXCONV,
    LEGACY_FOURCC_TO_TEXCONV,
    LEGACY_NUMERIC_FOURCC_TO_TEXCONV,
    PNG_MAGIC,
)
from cdmw.core.common import read_u32_le
from cdmw.domain.textures.plan import _dds_colorspace_intent_from_format
from cdmw.models import CrimsonDdsFinding, CrimsonDdsInfo, DdsInfo

_DDS_ALPHA_CAPABLE_FORMATS = {
    "R8G8B8A8_UNORM",
    "R8G8B8A8_UNORM_SRGB",
    "B8G8R8A8_UNORM",
    "B8G8R8A8_UNORM_SRGB",
    "BC1_UNORM",
    "BC1_UNORM_SRGB",
    "BC2_UNORM",
    "BC2_UNORM_SRGB",
    "BC3_UNORM",
    "BC3_UNORM_SRGB",
    "BC7_UNORM",
    "BC7_UNORM_SRGB",
    "R16G16B16A16_FLOAT",
    "R16G16B16A16_SNORM",
    "R32G32B32A32_FLOAT",
}
def _legacy_luminance_texconv_format(
    rgb_bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
) -> Optional[str]:
    mask_tuple = (r_mask, g_mask, b_mask, a_mask)
    if rgb_bit_count == 8 and mask_tuple == (
        0x000000FF,
        0x00000000,
        0x00000000,
        0x00000000,
    ):
        return "R8_UNORM"
    if rgb_bit_count == 16 and mask_tuple == (
        0x0000FFFF,
        0x00000000,
        0x00000000,
        0x00000000,
    ):
        return "R16_UNORM"
    if rgb_bit_count == 16 and mask_tuple in {
        (
            0x000000FF,
            0x00000000,
            0x00000000,
            0x0000FF00,
        ),
        (
            0x0000FF00,
            0x00000000,
            0x00000000,
            0x000000FF,
        ),
    }:
        return "R8G8_UNORM"
    return None


def _legacy_alpha_texconv_format(
    rgb_bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
) -> Optional[str]:
    mask_tuple = (r_mask, g_mask, b_mask, a_mask)
    if rgb_bit_count == 8 and mask_tuple in {
        (0x00000000, 0x00000000, 0x00000000, 0x000000FF),
        (0x000000FF, 0x00000000, 0x00000000, 0x00000000),
        (0x00000000, 0x00000000, 0x00000000, 0x00000000),
    }:
        return "A8_UNORM"
    if rgb_bit_count == 16 and mask_tuple in {
        (0x00000000, 0x00000000, 0x00000000, 0x0000FFFF),
        (0x0000FFFF, 0x00000000, 0x00000000, 0x00000000),
    }:
        return "R16_UNORM"
    return None

def parse_dds(dds_path: Path) -> DdsInfo:
    with dds_path.open("rb") as handle:
        blob = handle.read(148)

    if len(blob) < 128:
        raise ValueError("File is too small to be a valid DDS.")

    if blob[:4] != DDS_MAGIC:
        raise ValueError("Missing DDS magic.")

    header = blob[4:128]
    header_size = read_u32_le(header, 0)
    if header_size != 124:
        raise ValueError(f"Unexpected DDS header size: {header_size}")

    height = read_u32_le(header, 8)
    width = read_u32_le(header, 12)
    mip_count = read_u32_le(header, 24) or 1

    pf_size = read_u32_le(header, 72)
    if pf_size != 32:
        raise ValueError(f"Unexpected DDS pixel format size: {pf_size}")

    pf_flags = read_u32_le(header, 76)
    fourcc = header[80:84]
    rgb_bit_count = read_u32_le(header, 84)
    r_mask = read_u32_le(header, 88)
    g_mask = read_u32_le(header, 92)
    b_mask = read_u32_le(header, 96)
    a_mask = read_u32_le(header, 100)

    texconv_format: Optional[str] = None

    has_alpha = bool(pf_flags & (DDPF_ALPHAPIXELS | DDPF_ALPHA))

    if pf_flags & DDPF_FOURCC:
        if fourcc == b"DX10":
            if len(blob) < 148:
                raise ValueError("DDS declares DX10 header, but file is too small.")
            dx10 = blob[128:148]
            dxgi_format = read_u32_le(dx10, 0)
            texconv_format = DXGI_TO_TEXCONV.get(dxgi_format)
            if not texconv_format:
                raise ValueError(f"Unsupported DXGI format: {dxgi_format}")
        else:
            texconv_format = LEGACY_FOURCC_TO_TEXCONV.get(fourcc)
            if not texconv_format:
                numeric_fourcc = read_u32_le(fourcc, 0)
                texconv_format = LEGACY_NUMERIC_FOURCC_TO_TEXCONV.get(numeric_fourcc)
            if not texconv_format:
                pretty_fourcc = fourcc.decode("ascii", errors="replace")
                raise ValueError(
                    f"Unsupported legacy FOURCC format: {pretty_fourcc!r} (numeric={read_u32_le(fourcc, 0)})"
                )
    elif pf_flags & DDPF_RGB:
        if rgb_bit_count == 32:
            if (r_mask, g_mask, b_mask, a_mask) == (
                0x000000FF,
                0x0000FF00,
                0x00FF0000,
                0xFF000000,
            ):
                texconv_format = "R8G8B8A8_UNORM"
            elif (r_mask, g_mask, b_mask, a_mask) == (
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0xFF000000,
            ):
                texconv_format = "B8G8R8A8_UNORM"
            elif (r_mask, g_mask, b_mask, a_mask) == (
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0x00000000,
            ):
                texconv_format = "B8G8R8X8_UNORM"
            else:
                raise ValueError(
                    "Unsupported 32-bit RGB mask combination: "
                    f"R={r_mask:#010x} G={g_mask:#010x} B={b_mask:#010x} A={a_mask:#010x}"
                )
        else:
            raise ValueError(f"Unsupported uncompressed RGB bit depth: {rgb_bit_count}")
    elif pf_flags & DDPF_LUMINANCE:
        texconv_format = _legacy_luminance_texconv_format(rgb_bit_count, r_mask, g_mask, b_mask, a_mask)
        if not texconv_format:
            raise ValueError(
                "Unsupported luminance mask combination: "
                f"bits={rgb_bit_count} R={r_mask:#010x} G={g_mask:#010x} B={b_mask:#010x} A={a_mask:#010x}"
            )
    elif pf_flags & DDPF_ALPHA:
        texconv_format = _legacy_alpha_texconv_format(rgb_bit_count, r_mask, g_mask, b_mask, a_mask)
        if not texconv_format:
            raise ValueError(
                "Unsupported alpha-only mask combination: "
                f"bits={rgb_bit_count} R={r_mask:#010x} G={g_mask:#010x} B={b_mask:#010x} A={a_mask:#010x}"
            )
    else:
        raise ValueError(f"Unsupported DDS pixel format flags: {pf_flags:#x}")

    if texconv_format in _DDS_ALPHA_CAPABLE_FORMATS:
        has_alpha = True

    return DdsInfo(
        width=width,
        height=height,
        mip_count=max(1, mip_count),
        texconv_format=texconv_format,
        source_path=dds_path,
        has_alpha=has_alpha,
        colorspace_intent=_dds_colorspace_intent_from_format(texconv_format),
        precision_sensitive=("FLOAT" in texconv_format.upper() or "SNORM" in texconv_format.upper()),
    )


_CRIMSON_DDS_BLOCK_BYTES_BY_DXGI: Dict[int, int] = {
    71: 8,
    72: 8,
    74: 16,
    75: 16,
    77: 16,
    78: 16,
    80: 8,
    81: 8,
    83: 16,
    84: 16,
    95: 16,
    96: 16,
    98: 16,
    99: 16,
}
_CRIMSON_DDS_BLOCK_BYTES_BY_FOURCC: Dict[bytes, int] = {
    b"DXT1": 8,
    b"BC4U": 8,
    b"BC4S": 8,
    b"ATI1": 8,
    b"DXT3": 16,
    b"DXT5": 16,
    b"BC5U": 16,
    b"BC5S": 16,
    b"ATI2": 16,
    b"RXGB": 16,
}
_CRIMSON_DDS_LAST4_BC1_DXGI = frozenset({71, 72})
_CRIMSON_DDS_LAST4_BC2_BC3_BC7_DXGI = frozenset({74, 75, 77, 78, 98, 99})
_CRIMSON_DDS_LAST4_BC4_BC5_BC6_DXGI = frozenset({80, 81, 83, 84, 95, 96})
_CRIMSON_DDS_PATHC_REQUIRED_DXGI = frozenset({95, 96, 98, 99})


def _crimson_dds_finding(
    findings: List[CrimsonDdsFinding],
    severity: Literal["fatal", "warning", "info"],
    code: str,
    message: str,
) -> None:
    findings.append(CrimsonDdsFinding(severity=severity, code=code, message=message))


def _crimson_dds_format_block_bytes(dxgi_format: int, fourcc: bytes) -> Optional[int]:
    if dxgi_format in _CRIMSON_DDS_BLOCK_BYTES_BY_DXGI:
        return _CRIMSON_DDS_BLOCK_BYTES_BY_DXGI[dxgi_format]
    return _CRIMSON_DDS_BLOCK_BYTES_BY_FOURCC.get(bytes(fourcc or b"").upper())


def _crimson_dds_expected_payload_size(
    *,
    width: int,
    height: int,
    mip_count: int,
    block_bytes: Optional[int],
    rgb_bit_count: int = 0,
) -> int:
    levels = max(1, int(mip_count or 1))
    total = 0
    current_width = max(1, int(width or 0))
    current_height = max(1, int(height or 0))
    for _level in range(levels):
        if block_bytes:
            total += max(1, (current_width + 3) // 4) * max(1, (current_height + 3) // 4) * int(block_bytes)
        elif rgb_bit_count:
            bytes_per_pixel = max(1, (int(rgb_bit_count) + 7) // 8)
            total += current_width * current_height * bytes_per_pixel
        else:
            return 0
        current_width = max(1, current_width // 2)
        current_height = max(1, current_height // 2)
    return total


def validate_dds_payload_size(
    source: bytes | bytearray | memoryview | Path,
) -> Tuple[bool, str, int, int]:
    if isinstance(source, (bytes, bytearray, memoryview)):
        blob = bytes(source)
    else:
        blob = Path(source).read_bytes()
    if len(blob) < 128 or blob[:4] != DDS_MAGIC:
        return False, "DDS header is missing or too short.", len(blob), 128
    header = blob[4:128]
    header_flags = read_u32_le(header, 4)
    required_header_flags = 0x1 | 0x2 | 0x4 | 0x1000
    if (header_flags & required_header_flags) != required_header_flags:
        return True, "DDS payload size could not be proven because required header flags are missing.", len(blob), len(blob)
    pf_flags = read_u32_le(header, 76)
    fourcc = header[80:84]
    rgb_bit_count = read_u32_le(header, 84)
    width = read_u32_le(header, 12)
    height = read_u32_le(header, 8)
    mip_count = max(1, read_u32_le(header, 24) or 1)
    is_dx10 = bool((pf_flags & DDPF_FOURCC) and fourcc == b"DX10")
    if is_dx10 and len(blob) < 148:
        return False, "DDS declares DX10 metadata, but the DX10 header is missing.", len(blob), 148
    dxgi_format = read_u32_le(blob, 128) if is_dx10 else 0
    block_bytes = _crimson_dds_format_block_bytes(dxgi_format, fourcc)
    payload_size = _crimson_dds_expected_payload_size(
        width=width,
        height=height,
        mip_count=mip_count,
        block_bytes=block_bytes,
        rgb_bit_count=rgb_bit_count if not block_bytes else 0,
    )
    if payload_size <= 0:
        return True, "DDS payload size could not be proven for this format.", len(blob), len(blob)
    header_size = 148 if is_dx10 else 128
    expected_total = header_size + payload_size
    if len(blob) < expected_total:
        return (
            False,
            f"DDS payload is truncated: {len(blob):,} byte(s), expected at least {expected_total:,}.",
            len(blob),
            expected_total,
        )
    return True, "DDS payload size is valid.", len(blob), expected_total


def _crimson_dds_expected_mips(width: int, height: int, depth: int = 0) -> int:
    largest = max(1, int(width or 0), int(height or 0), int(depth or 1))
    return max(1, int(math.floor(math.log2(largest))) + 1)


def _crimson_dds_is_power_of_two(value: int) -> bool:
    numeric = int(value or 0)
    return numeric > 0 and (numeric & (numeric - 1)) == 0


def classify_crimson_dds_vpath_last4(vpath: str) -> Optional[int]:
    normalized = str(vpath or "").replace("\\", "/").strip()
    if not normalized:
        return None
    normalized = "/" + normalized.lstrip("/")
    lowered = normalized.lower()
    name = PurePosixPath(lowered).name
    if lowered.startswith("/ui/"):
        return 0x1580
    if lowered.startswith("/character/texture/") and name.endswith("_n.dds"):
        return 0x0480
    if lowered.startswith("/character/texture/") and "tattoo" in name:
        return 0x1380
    if lowered.startswith("/character/texture/"):
        return 0x1280
    return None


def crimson_dds_format_last4(
    *,
    dxgi_format: int = 0,
    fourcc: bytes | str = b"",
    texconv_format: str = "",
) -> Optional[int]:
    fourcc_bytes = (
        str(fourcc or "").encode("ascii", errors="ignore")
        if isinstance(fourcc, str)
        else bytes(fourcc or b"")
    ).upper()
    normalized_format = str(texconv_format or "").strip().upper()
    if int(dxgi_format or 0) in _CRIMSON_DDS_LAST4_BC1_DXGI or fourcc_bytes == b"DXT1" or normalized_format.startswith("BC1_"):
        return 12
    if (
        int(dxgi_format or 0) in _CRIMSON_DDS_LAST4_BC2_BC3_BC7_DXGI
        or fourcc_bytes in {b"DXT3", b"DXT5"}
        or normalized_format.startswith(("BC2_", "BC3_", "BC7_"))
    ):
        return 15
    if (
        int(dxgi_format or 0) in _CRIMSON_DDS_LAST4_BC4_BC5_BC6_DXGI
        or fourcc_bytes in {b"ATI1", b"ATI2", b"BC4U", b"BC4S", b"BC5U", b"BC5S"}
        or normalized_format.startswith(("BC4_", "BC5_", "BC6H_"))
    ):
        return 4
    return None


def _crimson_dds_texconv_format(
    *,
    pf_flags: int,
    fourcc: bytes,
    rgb_bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
    dxgi_format: int,
    findings: List[CrimsonDdsFinding],
) -> str:
    if pf_flags & DDPF_FOURCC:
        if fourcc == b"DX10":
            texconv_format = DXGI_TO_TEXCONV.get(dxgi_format, "")
            if not texconv_format:
                _crimson_dds_finding(
                    findings,
                    "warning",
                    "unknown_dxgi_format",
                    f"DDS uses an unknown DXGI format id: {dxgi_format}.",
                )
            return texconv_format
        texconv_format = LEGACY_FOURCC_TO_TEXCONV.get(fourcc, "")
        if not texconv_format:
            numeric_fourcc = read_u32_le(fourcc, 0) if len(fourcc) >= 4 else 0
            texconv_format = LEGACY_NUMERIC_FOURCC_TO_TEXCONV.get(numeric_fourcc, "")
        if not texconv_format:
            pretty_fourcc = fourcc.decode("ascii", errors="replace")
            _crimson_dds_finding(
                findings,
                "warning",
                "unknown_fourcc",
                f"DDS uses an unknown legacy FOURCC: {pretty_fourcc!r}.",
            )
        return texconv_format
    if pf_flags & DDPF_RGB:
        if rgb_bit_count == 32:
            if (r_mask, g_mask, b_mask, a_mask) == (
                0x000000FF,
                0x0000FF00,
                0x00FF0000,
                0xFF000000,
            ):
                return "R8G8B8A8_UNORM"
            if (r_mask, g_mask, b_mask, a_mask) == (
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0xFF000000,
            ):
                return "B8G8R8A8_UNORM"
            if (r_mask, g_mask, b_mask, a_mask) == (
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0x00000000,
            ):
                return "B8G8R8X8_UNORM"
        _crimson_dds_finding(
            findings,
            "warning",
            "unknown_rgb_layout",
            f"DDS uses an unsupported RGB layout: bits={rgb_bit_count}.",
        )
        return ""
    if pf_flags & DDPF_LUMINANCE:
        texconv_format = _legacy_luminance_texconv_format(rgb_bit_count, r_mask, g_mask, b_mask, a_mask) or ""
        if not texconv_format:
            _crimson_dds_finding(
                findings,
                "warning",
                "unknown_luminance_layout",
                f"DDS uses an unsupported luminance layout: bits={rgb_bit_count}.",
            )
        return texconv_format
    if pf_flags & DDPF_ALPHA:
        texconv_format = _legacy_alpha_texconv_format(rgb_bit_count, r_mask, g_mask, b_mask, a_mask) or ""
        if not texconv_format:
            _crimson_dds_finding(
                findings,
                "warning",
                "unknown_alpha_layout",
                f"DDS uses an unsupported alpha-only layout: bits={rgb_bit_count}.",
            )
        return texconv_format
    _crimson_dds_finding(
        findings,
        "warning",
        "unknown_pixel_format_flags",
        f"DDS uses unsupported pixel format flags: 0x{pf_flags:08X}.",
    )
    return ""


def inspect_crimson_dds(
    source: bytes | bytearray | memoryview | Path,
    *,
    vpath: str = "",
    pathc_last4: Optional[int] = None,
) -> CrimsonDdsInfo:
    source_path: Optional[Path] = None
    if isinstance(source, (bytes, bytearray, memoryview)):
        blob = bytes(source)
    else:
        source_path = Path(source)
        blob = source_path.read_bytes()

    findings: List[CrimsonDdsFinding] = []
    normalized_vpath = str(vpath or "").replace("\\", "/").strip()
    if len(blob) < 128:
        _crimson_dds_finding(
            findings,
            "fatal",
            "header_too_short",
            f"DDS header is too short: {len(blob):,} bytes.",
        )
        return CrimsonDdsInfo(
            source_path=source_path,
            vpath=normalized_vpath,
            findings=tuple(findings),
        )
    if blob[:4] != DDS_MAGIC:
        _crimson_dds_finding(findings, "fatal", "bad_magic", "DDS magic is missing.")
        return CrimsonDdsInfo(
            source_path=source_path,
            vpath=normalized_vpath,
            findings=tuple(findings),
        )

    header = blob[4:128]
    header_size = read_u32_le(header, 0)
    if header_size != 124:
        _crimson_dds_finding(
            findings,
            "fatal",
            "bad_header_size",
            f"DDS header size is {header_size}, expected 124.",
        )
    height = read_u32_le(header, 8)
    width = read_u32_le(header, 12)
    depth = read_u32_le(header, 20)
    raw_mip_count = read_u32_le(header, 24)
    mip_count = max(1, int(raw_mip_count or 1))
    reserved1 = tuple(struct.unpack_from("<11I", header, 28))
    pf_size = read_u32_le(header, 72)
    if pf_size != 32:
        _crimson_dds_finding(
            findings,
            "fatal",
            "bad_pixel_format_size",
            f"DDS pixel format size is {pf_size}, expected 32.",
        )
    pf_flags = read_u32_le(header, 76)
    fourcc = header[80:84]
    rgb_bit_count = read_u32_le(header, 84)
    r_mask = read_u32_le(header, 88)
    g_mask = read_u32_le(header, 92)
    b_mask = read_u32_le(header, 96)
    a_mask = read_u32_le(header, 100)
    crimson_last4_header = read_u32_le(header, 120)
    is_dx10 = bool((pf_flags & DDPF_FOURCC) and fourcc == b"DX10")
    dxgi_format = 0
    if is_dx10:
        if len(blob) < 148:
            _crimson_dds_finding(
                findings,
                "fatal",
                "dx10_header_too_short",
                "DDS declares a DX10 header, but the 20-byte DX10 payload is missing.",
            )
        else:
            dxgi_format = read_u32_le(blob, 128)

    texconv_format = _crimson_dds_texconv_format(
        pf_flags=pf_flags,
        fourcc=fourcc,
        rgb_bit_count=rgb_bit_count,
        r_mask=r_mask,
        g_mask=g_mask,
        b_mask=b_mask,
        a_mask=a_mask,
        dxgi_format=dxgi_format,
        findings=findings,
    )
    block_bytes = _crimson_dds_format_block_bytes(dxgi_format, fourcc)
    path_class_last4 = classify_crimson_dds_vpath_last4(normalized_vpath)
    format_last4 = crimson_dds_format_last4(
        dxgi_format=dxgi_format,
        fourcc=fourcc,
        texconv_format=texconv_format,
    )
    resolved_pathc_last4 = int(pathc_last4) if pathc_last4 is not None else None
    effective_last4 = (
        resolved_pathc_last4
        if resolved_pathc_last4 is not None
        else path_class_last4
        if path_class_last4 is not None
        else format_last4
    )
    requires_pathc = bool(is_dx10 and dxgi_format in _CRIMSON_DDS_PATHC_REQUIRED_DXGI)

    if depth <= 0:
        _crimson_dds_finding(
            findings,
            "warning",
            "depth_zero",
            "DDS depth field is 0; preserve the target template/PATHC context for Crimson replacements.",
        )
    if raw_mip_count <= 0:
        _crimson_dds_finding(findings, "warning", "mip_count_zero", "DDS mip count field is 0; treating it as 1.")
    if width <= 0 or height <= 0:
        _crimson_dds_finding(
            findings,
            "fatal",
            "bad_dimensions",
            f"DDS dimensions are invalid: {width}x{height}.",
        )
    elif not (_crimson_dds_is_power_of_two(width) and _crimson_dds_is_power_of_two(height)):
        _crimson_dds_finding(
            findings,
            "warning",
            "non_power_of_two_dims",
            f"DDS dimensions are not powers of two: {width}x{height}.",
        )
    expected_mips = _crimson_dds_expected_mips(width, height, depth)
    if width > 1 and height > 1 and raw_mip_count > 0 and mip_count < expected_mips:
        _crimson_dds_finding(
            findings,
            "warning",
            "missing_mips",
            f"DDS mip chain has {mip_count} level(s); {expected_mips} would be a full chain for {width}x{height}.",
        )
    if requires_pathc:
        _crimson_dds_finding(
            findings,
            "info",
            "requires_pathc",
            f"DDS format {texconv_format or dxgi_format} uses DX10 metadata and should be registered through PATHC/manifest metadata.",
        )
    if effective_last4 is not None:
        _crimson_dds_finding(
            findings,
            "info",
            "effective_last4",
            f"Effective Crimson last4 class is 0x{effective_last4:04X}.",
        )
    payload_ok, payload_message, payload_actual, payload_expected = validate_dds_payload_size(blob)
    if not payload_ok:
        _crimson_dds_finding(
            findings,
            "fatal",
            "payload_truncated",
            payload_message,
        )
    elif payload_message == "DDS payload size is valid.":
        _crimson_dds_finding(
            findings,
            "info",
            "payload_size_valid",
            payload_message,
        )
    if crimson_last4_header and effective_last4 is not None:
        if crimson_last4_header == effective_last4:
            _crimson_dds_finding(
                findings,
                "info",
                "overlay_patched",
                f"DDS header last4 already matches 0x{effective_last4:04X}.",
            )
        else:
            _crimson_dds_finding(
                findings,
                "warning",
                "last4_mismatch",
                f"DDS header last4 is 0x{crimson_last4_header:04X}; expected 0x{effective_last4:04X} for this path/format.",
            )

    return CrimsonDdsInfo(
        source_path=source_path,
        vpath=normalized_vpath,
        width=width,
        height=height,
        mip_count=mip_count,
        raw_mip_count=raw_mip_count,
        depth=depth,
        texconv_format=texconv_format,
        is_dx10=is_dx10,
        dxgi_format=dxgi_format,
        fourcc=fourcc.decode("ascii", errors="replace"),
        block_bytes=block_bytes,
        crimson_last4_header=crimson_last4_header or None,
        last4_pathc=resolved_pathc_last4,
        last4_path_class=path_class_last4,
        last4_format_derived=format_last4,
        effective_last4=effective_last4,
        requires_pathc=requires_pathc,
        reserved1=reserved1,
        findings=tuple(findings),
    )


def validate_crimson_dds(
    source: bytes | bytearray | memoryview | Path,
    *,
    vpath: str = "",
    pathc_last4: Optional[int] = None,
) -> Tuple[CrimsonDdsFinding, ...]:
    return inspect_crimson_dds(source, vpath=vpath, pathc_last4=pathc_last4).findings


def read_png_dimensions(png_path: Path) -> Tuple[int, int]:
    with png_path.open("rb") as handle:
        signature = handle.read(8)
        if signature != PNG_MAGIC:
            raise ValueError("Not a PNG file or PNG signature is invalid.")
        ihdr_len = struct.unpack(">I", handle.read(4))[0]
        chunk_type = handle.read(4)
        if chunk_type != b"IHDR" or ihdr_len != 13:
            raise ValueError("PNG IHDR chunk is missing or invalid.")
        width, height = struct.unpack(">II", handle.read(8))
        return width, height


def read_png_header_info(png_path: Path) -> Tuple[int, int, int, int]:
    with png_path.open("rb") as handle:
        signature = handle.read(8)
        if signature != PNG_MAGIC:
            raise ValueError("Not a PNG file or PNG signature is invalid.")
        ihdr_len = struct.unpack(">I", handle.read(4))[0]
        chunk_type = handle.read(4)
        if chunk_type != b"IHDR" or ihdr_len != 13:
            raise ValueError("PNG IHDR chunk is missing or invalid.")
        width, height = struct.unpack(">II", handle.read(8))
        bit_depth = handle.read(1)
        color_type = handle.read(1)
        if len(bit_depth) != 1 or len(color_type) != 1:
            raise ValueError("PNG IHDR bit depth or color type is missing.")
        return width, height, bit_depth[0], color_type[0]


def describe_png_color_type(color_type: int) -> str:
    return {
        0: "grayscale",
        2: "rgb",
        3: "indexed",
        4: "grayscale_alpha",
        6: "rgba",
    }.get(int(color_type), f"unknown({color_type})")


def png_has_alpha_channel(png_path: Path) -> bool:
    _width, _height, _bit_depth, color_type = read_png_header_info(png_path)
    return color_type in {4, 6}
