"""Read-only Archive Browser inspector for the shipped D3D12 shader cache.

`shadercache__/d3d12` holds two kinds of entry. A `.padxil` is a 36-byte `PASC`
wrapper around a standard DXBC container carrying DXIL; every one in game build
1.0.0.3446 is PASC version 8 with the chunks SFI0, ISG1, OSG1, PSV0, STAT, HASH
and DXIL (shader model 6.6). A `.pars` is a bare DXBC container with a single
`RTS0` chunk, i.e. a serialized D3D12 root signature (all version 1.1).

Everything below the PASC header is Microsoft's documented container layout
(DirectXShaderCompiler's DxilContainer.h and DxilPipelineStateValidation.h, and
d3d12.h for root signatures), so the decode is exact. The PASC header's own
fields beyond size, payload offset and digest are not identified and are shown
as raw values. Shader bytecode itself is not disassembled here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle

SHADER_CACHE_EXTENSIONS = frozenset({".padxil", ".pars"})
PASC_MAGIC = b"PASC"
DXBC_MAGIC = b"DXBC"
_DXBC_HEADER_SIZE = 32
_MAX_CHUNKS = 64
_ROW_LIMIT = 64

_DXIL_SHADER_KINDS = {
    0: "Pixel", 1: "Vertex", 2: "Geometry", 3: "Hull", 4: "Domain", 5: "Compute", 6: "Library",
    7: "Ray generation", 8: "Intersection", 9: "Any hit", 10: "Closest hit", 11: "Miss",
    12: "Callable", 13: "Mesh", 14: "Amplification", 15: "Node",
}
_PSV_SHADER_KINDS = {
    0: "Pixel", 1: "Vertex", 2: "Geometry", 3: "Hull", 4: "Domain", 5: "Compute", 6: "Library",
    7: "Mesh", 8: "Amplification",
}
_PSV_RESOURCE_TYPES = {
    1: ("Sampler", "s"), 2: ("CBV", "b"), 3: ("SRV", "t"), 4: ("SRV", "t"), 5: ("SRV", "t"),
    6: ("UAV", "u"), 7: ("UAV", "u"), 8: ("UAV", "u"), 9: ("UAV", "u"),
}
_PSV_FALLBACK_SHAPES = {3: "typed", 4: "raw", 5: "structured", 6: "typed", 7: "raw", 8: "structured", 9: "structured"}
# AMD GPU Services binds its shader-intrinsics UAV at u0 in this space
# (AmdExtD3DShaderIntrinsicsSpaceId in ags_shader_intrinsics_dx12.hlsl).
_AMD_INTRINSICS_SPACE = 2147420894
_DXIL_RESOURCE_KINDS = {
    1: "Texture1D", 2: "Texture2D", 3: "Texture2DMS", 4: "Texture3D", 5: "TextureCube",
    6: "Texture1DArray", 7: "Texture2DArray", 8: "Texture2DMSArray", 9: "TextureCubeArray",
    10: "TypedBuffer", 11: "RawBuffer", 12: "StructuredBuffer", 13: "CBuffer", 14: "Sampler",
    15: "TBuffer", 16: "RTAccelerationStructure", 17: "FeedbackTexture2D",
    18: "FeedbackTexture2DArray",
}
_SIGNATURE_COMPONENT_TYPES = {
    1: "uint", 2: "int", 3: "float", 4: "uint16", 5: "int16", 6: "half", 7: "uint64",
    8: "int64", 9: "double",
}
# RDAT (library runtime data): part types and the record fields read here.
_RDAT_VERSION = 0x10
_RDAT_STRING_BUFFER = 1
_RDAT_RESOURCE_TABLE = 3
_RDAT_FUNCTION_TABLE = 4
_RDAT_RESOURCE_CLASSES = {0: ("SRV", "t"), 1: ("UAV", "u"), 2: ("CBV", "b"), 3: ("Sampler", "s")}
_MIN_PRECISION = {1: "min16float", 2: "min10float", 4: "min16int", 5: "min16uint"}
# D3D_SHADER_FEATURE_* bits as stored in SFI0.
_SHADER_FEATURES = (
    (0x1, "doubles"),
    (0x2, "raw/structured buffers via SM4.x"),
    (0x4, "UAVs at every stage"),
    (0x8, "64 UAVs"),
    (0x10, "minimum precision"),
    (0x20, "11.1 double extensions"),
    (0x40, "11.1 shader extensions"),
    (0x80, "level 9 comparison filtering"),
    (0x100, "tiled resources"),
    (0x200, "stencil ref"),
    (0x400, "inner coverage"),
    (0x800, "typed UAV load formats"),
    (0x1000, "rasterizer ordered views"),
    (0x2000, "viewport/RT array index from any stage"),
    (0x4000, "wave ops"),
    (0x8000, "int64 ops"),
    (0x10000, "view ID"),
    (0x20000, "barycentrics"),
    (0x40000, "native 16-bit ops"),
    (0x80000, "shading rate"),
    (0x100000, "raytracing tier 1.1"),
    (0x200000, "sampler feedback"),
    (0x400000, "int64 atomics on typed resources"),
    (0x800000, "int64 atomics on group shared"),
    (0x1000000, "derivatives in mesh/amplification"),
    (0x2000000, "resource descriptor heap indexing"),
    (0x4000000, "sampler descriptor heap indexing"),
    (0x8000000, "wave MMA"),
    (0x10000000, "int64 atomics on heap resources"),
    (0x20000000, "advanced texture ops"),
    (0x40000000, "writeable MSAA textures"),
)

_ROOT_PARAMETER_TYPES = {0: "Descriptor table", 1: "32-bit constants", 2: "CBV", 3: "SRV", 4: "UAV"}
_SHADER_VISIBILITY = {
    0: "all", 1: "vertex", 2: "hull", 3: "domain", 4: "geometry", 5: "pixel", 6: "amplification", 7: "mesh",
}
_RANGE_TYPES = {0: ("SRV", "t"), 1: ("UAV", "u"), 2: ("CBV", "b"), 3: ("Sampler", "s")}
_ROOT_PARAMETER_REGISTERS = {2: "b", 3: "t", 4: "u"}
_ROOT_SIGNATURE_FLAGS = (
    (0x1, "allow input assembler layout"),
    (0x2, "deny vertex root access"),
    (0x4, "deny hull root access"),
    (0x8, "deny domain root access"),
    (0x10, "deny geometry root access"),
    (0x20, "deny pixel root access"),
    (0x40, "allow stream output"),
    (0x80, "local root signature"),
    (0x100, "deny amplification root access"),
    (0x200, "deny mesh root access"),
    (0x400, "CBV/SRV/UAV heap directly indexed"),
    (0x800, "sampler heap directly indexed"),
)
_ROOT_SIGNATURE_VERSIONS = {1: "1.0", 2: "1.1", 3: "1.2"}
_ADDRESS_MODES = {1: "wrap", 2: "mirror", 3: "clamp", 4: "border", 5: "mirror once"}
_COMPARISON = {
    0: "none", 1: "never", 2: "less", 3: "equal", 4: "less-equal", 5: "greater", 6: "not-equal",
    7: "greater-equal", 8: "always",
}
_BORDER_COLORS = {
    0: "transparent black", 1: "opaque black", 2: "opaque white", 3: "opaque black (uint)",
    4: "opaque white (uint)",
}
_UNBOUNDED = 0xFFFFFFFF


class ShaderContainerError(ValueError):
    """The bytes are not a shader container this inspector can read."""


@dataclass(frozen=True)
class DxbcChunk:
    fourcc: str
    offset: int  # of the chunk data, relative to the container start
    data: bytes


@dataclass(frozen=True)
class PascHeader:
    version: int
    declared_size: int
    unknown_u32: int
    payload_offset: int
    digest: bytes


@dataclass
class ShaderSummary:
    stage: str = ""
    shader_model: str = ""
    dxil_version: str = ""
    entry_point: str = ""
    threads: tuple[int, int, int] = (0, 0, 0)
    features: tuple[str, ...] = ()
    unknown_feature_bits: int = 0
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    shader_hash: str = ""
    bitcode_bytes: int = 0
    reflection_bytes: int = 0


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ShaderContainerError(f"read past end at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def read_pasc_header(data: bytes) -> PascHeader:
    if len(data) < 36 or data[:4] != PASC_MAGIC:
        raise ShaderContainerError("not a PASC shader cache entry")
    version, declared_size, unknown_u32, payload_offset = struct.unpack_from("<IIII", data, 4)
    if version != 8:
        raise ShaderContainerError(f"PASC version {version} is not supported (version 8 is)")
    if declared_size != len(data) or payload_offset != 36:
        raise ShaderContainerError("PASC header size or payload offset does not match the entry")
    return PascHeader(version, declared_size, unknown_u32, payload_offset, bytes(data[20:36]))


def read_dxbc_chunks(container: bytes) -> tuple[DxbcChunk, ...]:
    """Split a DXBC container into its chunks, validating every span."""

    if len(container) < _DXBC_HEADER_SIZE or container[:4] != DXBC_MAGIC:
        raise ShaderContainerError("no DXBC container")
    total_size, count = struct.unpack_from("<II", container, 24)
    if total_size != len(container):
        raise ShaderContainerError(f"DXBC declares {total_size:,} bytes but {len(container):,} are present")
    if count > _MAX_CHUNKS or _DXBC_HEADER_SIZE + 4 * count > total_size:
        raise ShaderContainerError(f"implausible DXBC chunk count {count}")
    chunks = []
    for index in range(count):
        offset = _u32(container, _DXBC_HEADER_SIZE + 4 * index)
        if offset < _DXBC_HEADER_SIZE + 4 * count or offset + 8 > total_size:
            raise ShaderContainerError(f"chunk {index} starts outside the container")
        size = _u32(container, offset + 4)
        if offset + 8 + size > total_size:
            raise ShaderContainerError(f"chunk {index} runs past the container")
        fourcc = container[offset : offset + 4].decode("latin-1")
        chunks.append(DxbcChunk(fourcc, offset + 8, bytes(container[offset + 8 : offset + 8 + size])))
    return tuple(chunks)


def _space_text(space: int) -> str:
    if space == _AMD_INTRINSICS_SPACE:
        return f"space {space} (AMD shader-intrinsics extension slot)"
    return f"space {space}"


def _mask_text(mask: int) -> str:
    return "".join(letter for bit, letter in zip((1, 2, 4, 8), "xyzw") if mask & bit) or "-"


def _c_string(data: bytes, offset: int) -> str:
    if offset <= 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    return data[offset : end if end >= 0 else len(data)].decode("utf-8", errors="replace")


def _signature_rows(chunk: DxbcChunk) -> list[str]:
    """ISG1/OSG1/PSG1 (32-byte elements) or ISGN/OSGN (24-byte elements)."""

    data = chunk.data
    count, first = struct.unpack_from("<II", data, 0) if len(data) >= 8 else (0, 8)
    element_size = 32 if chunk.fourcc.endswith("1") else 24
    rows = []
    for index in range(count):
        base = first + index * element_size
        if base + element_size > len(data):
            break
        if element_size == 32:
            _stream, name_offset, semantic_index, _system_value, component, register = struct.unpack_from("<6I", data, base)
            mask = data[base + 24]
            precision = _MIN_PRECISION.get(_u32(data, base + 28), "")
        else:
            name_offset, semantic_index, _system_value, component, register = struct.unpack_from("<5I", data, base)
            mask = data[base + 20]
            precision = ""
        name = _c_string(data, name_offset) or "?"
        component_text = precision or _SIGNATURE_COMPONENT_TYPES.get(component, f"type {component}")
        register_text = f"v{register}" if register != _UNBOUNDED else "system value"
        rows.append(f"{name}{semantic_index if semantic_index else ''}  {component_text}.{_mask_text(mask)}  ({register_text})")
    return rows


def _apply_psv0(chunk: DxbcChunk, summary: ShaderSummary) -> None:
    data = chunk.data
    info_size = _u32(data, 0)
    info = 4
    if info_size >= 36:
        stage = data[info + 24]
        summary.stage = summary.stage or _PSV_SHADER_KINDS.get(stage, f"kind {stage}")
    if info_size >= 48:
        threads = struct.unpack_from("<III", data, info + 36)
        if any(threads):
            summary.threads = threads
    entry_offset = _u32(data, info + 48) if info_size >= 52 else 0
    cursor = info + info_size
    resource_count = _u32(data, cursor)
    cursor += 4
    if resource_count:
        bind_size = _u32(data, cursor)
        cursor += 4
        if bind_size < 16:
            raise ShaderContainerError(f"PSV0 resource record of {bind_size} bytes")
        for index in range(resource_count):
            base = cursor + index * bind_size
            res_type, space, lower, upper = struct.unpack_from("<4I", data, base)
            kind = _DXIL_RESOURCE_KINDS.get(_u32(data, base + 16), "") if bind_size >= 24 else ""
            label, letter = _PSV_RESOURCE_TYPES.get(res_type, (f"type {res_type}", "?"))
            shape = "" if kind in ("CBuffer", "Sampler") else (kind or _PSV_FALLBACK_SHAPES.get(res_type, ""))
            if res_type == 9:
                shape += " with counter"
            if upper == _UNBOUNDED:
                registers = f"{letter}{lower}+ (unbounded)"
            elif upper > lower:
                registers = f"{letter}{lower}-{letter}{upper}"
            else:
                registers = f"{letter}{lower}"
            summary.resources.append(f"{label}{f' {shape}' if shape else ''}  {registers}, {_space_text(space)}")
        cursor += resource_count * bind_size
    if info_size >= 36 and cursor + 4 <= len(data):
        table_size = _u32(data, cursor)
        table = data[cursor + 4 : cursor + 4 + table_size]
        if entry_offset < len(table):
            summary.entry_point = _c_string(b"\0" + table, entry_offset + 1)


def _apply_program_header(chunk: DxbcChunk, summary: ShaderSummary) -> None:
    data = chunk.data
    if len(data) < 24:
        return
    program_version, _dwords, magic, dxil_version, _bitcode_offset, bitcode_size = struct.unpack_from("<IIIIII", data, 0)
    if chunk.fourcc == "STAT":
        summary.reflection_bytes = bitcode_size
        return
    kind = program_version >> 16
    summary.stage = _DXIL_SHADER_KINDS.get(kind, f"kind {kind}")
    summary.shader_model = f"{(program_version >> 4) & 0xF}.{program_version & 0xF}"
    if magic == 0x4C495844:  # "DXIL"
        summary.dxil_version = f"{dxil_version >> 8}.{dxil_version & 0xFF}"
    summary.bitcode_bytes = bitcode_size


def _apply_rdat(chunk: DxbcChunk, summary: ShaderSummary) -> None:
    """Library runtime data: the functions a library exports and its named resources."""

    data = chunk.data
    version, part_count = struct.unpack_from("<II", data, 0)
    if version != _RDAT_VERSION or part_count > 32:
        return
    strings = b""
    tables: dict[int, tuple[int, int, bytes]] = {}
    for offset in struct.unpack_from(f"<{part_count}I", data, 8):
        part_type, size = struct.unpack_from("<II", data, offset)
        body = data[offset + 8 : offset + 8 + size]
        if part_type == _RDAT_STRING_BUFFER:
            strings = body
        elif part_type in (_RDAT_RESOURCE_TABLE, _RDAT_FUNCTION_TABLE) and len(body) >= 8:
            count, stride = struct.unpack_from("<II", body, 0)
            tables[part_type] = (count, stride, body[8:])

    def text(offset: int) -> str:
        return _c_string(b"\0" + strings, offset + 1) if offset < len(strings) else ""

    count, stride, records = tables.get(_RDAT_FUNCTION_TABLE, (0, 0, b""))
    for index in range(count if stride >= 20 else 0):
        name, unmangled, _resources, _dependencies, kind = struct.unpack_from("<5I", records, index * stride)
        label = text(unmangled) or text(name) or f"function {index}"
        summary.functions.append(f"{label}  ({_DXIL_SHADER_KINDS.get(kind, f'kind {kind}')})")
    count, stride, records = tables.get(_RDAT_RESOURCE_TABLE, (0, 0, b""))
    if summary.resources or stride < 28:
        return
    for index in range(count):
        resource_class, kind, _id, space, lower, upper, name = struct.unpack_from("<7I", records, index * stride)
        label, letter = _RDAT_RESOURCE_CLASSES.get(resource_class, (f"class {resource_class}", "?"))
        shape = _DXIL_RESOURCE_KINDS.get(kind, "")
        shape = "" if shape in ("CBuffer", "Sampler") else shape
        if upper == _UNBOUNDED:
            registers = f"{letter}{lower}+ (unbounded)"
        elif upper > lower:
            registers = f"{letter}{lower}-{letter}{upper}"
        else:
            registers = f"{letter}{lower}"
        named = text(name)
        summary.resources.append(
            f"{label}{f' {shape}' if shape else ''}  {registers}, {_space_text(space)}{f'  {named}' if named else ''}"
        )


def summarize_shader_chunks(chunks: tuple[DxbcChunk, ...]) -> ShaderSummary:
    summary = ShaderSummary()
    for chunk in chunks:
        try:
            if chunk.fourcc in ("DXIL", "STAT"):
                _apply_program_header(chunk, summary)
            elif chunk.fourcc == "PSV0":
                _apply_psv0(chunk, summary)
            elif chunk.fourcc == "SFI0" and len(chunk.data) >= 8:
                flags = struct.unpack_from("<Q", chunk.data, 0)[0]
                summary.features = tuple(name for bit, name in _SHADER_FEATURES if flags & bit)
                summary.unknown_feature_bits = flags & ~sum(bit for bit, _name in _SHADER_FEATURES)
            elif chunk.fourcc in ("ISG1", "ISGN"):
                summary.inputs = _signature_rows(chunk)
            elif chunk.fourcc in ("OSG1", "OSGN", "OSG5"):
                summary.outputs = _signature_rows(chunk)
            elif chunk.fourcc == "HASH" and len(chunk.data) >= 20:
                summary.shader_hash = chunk.data[4:20].hex()
            elif chunk.fourcc == "RDAT":
                _apply_rdat(chunk, summary)
        except (ShaderContainerError, struct.error, IndexError):
            # One malformed optional chunk must not hide what the rest says.
            continue
    return summary


def _flag_names(flags: int, table) -> str:
    names = [name for bit, name in table if flags & bit]
    rest = flags & ~sum(bit for bit, _name in table)
    if rest:
        names.append(f"0x{rest:x}")
    return ", ".join(names) or "none"


def _register_span(letter: str, base: int, count: int) -> str:
    if count == _UNBOUNDED:
        return f"{letter}{base}+ (unbounded)"
    if count > 1:
        return f"{letter}{base}-{letter}{base + count - 1}"
    return f"{letter}{base}"


def _filter_text(value: int) -> str:
    reduction = ("", "comparison ", "minimum ", "maximum ")[(value >> 7) & 3]
    if value & 0x40:
        return f"{reduction}anisotropic"
    parts = []
    for label, shift in (("min", 4), ("mag", 2), ("mip", 0)):
        parts.append(f"{label} {'linear' if (value >> shift) & 1 else 'point'}")
    return reduction + ", ".join(parts)


def describe_root_signature(data: bytes) -> list[str]:
    """A serialized D3D12 root signature (the `RTS0` chunk data), as text lines."""

    version, parameter_count, parameter_offset, sampler_count, sampler_offset, flags = struct.unpack_from("<6I", data, 0)
    if version not in _ROOT_SIGNATURE_VERSIONS:
        raise ShaderContainerError(f"unknown root signature version {version}")
    if parameter_count > 256 or sampler_count > 2048:
        raise ShaderContainerError("implausible root signature counts")
    lines = [
        f"- Version: {_ROOT_SIGNATURE_VERSIONS[version]}",
        f"- Flags: {_flag_names(flags, _ROOT_SIGNATURE_FLAGS)}",
        f"- Root parameters: {parameter_count}",
        f"- Static samplers: {sampler_count}",
        "",
        "Root parameters:",
    ]
    range_size = 20 if version == 1 else 24
    for index in range(parameter_count):
        kind, visibility, payload = struct.unpack_from("<III", data, parameter_offset + 12 * index)
        title = _ROOT_PARAMETER_TYPES.get(kind, f"type {kind}")
        where = _SHADER_VISIBILITY.get(visibility, f"visibility {visibility}")
        if kind == 0:
            range_count, range_offset = struct.unpack_from("<II", data, payload)
            lines.append(f"  [{index}] {title} ({where}), {range_count} range{'s' if range_count != 1 else ''}")
            for range_index in range(min(range_count, _ROW_LIMIT)):
                base = range_offset + range_size * range_index
                range_type, count, register, space = struct.unpack_from("<4I", data, base)
                label, letter = _RANGE_TYPES.get(range_type, (f"type {range_type}", "?"))
                lines.append(f"      {label} {_register_span(letter, register, count)}, {_space_text(space)}")
        elif kind == 1:
            register, space, values = struct.unpack_from("<III", data, payload)
            lines.append(f"  [{index}] {title} ({where}): b{register}, {_space_text(space)}, {values} values")
        else:
            register, space = struct.unpack_from("<II", data, payload)
            letter = _ROOT_PARAMETER_REGISTERS.get(kind, "?")
            lines.append(f"  [{index}] Root {title} ({where}): {letter}{register}, {_space_text(space)}")
    if sampler_count:
        sampler_size = 56 if version == 3 else 52
        lines.extend(["", "Static samplers:"])
        for index in range(min(sampler_count, _ROW_LIMIT)):
            base = sampler_offset + sampler_size * index
            (filter_value, address_u, address_v, address_w) = struct.unpack_from("<4I", data, base)
            mip_bias = struct.unpack_from("<f", data, base + 16)[0]
            anisotropy, comparison, border = struct.unpack_from("<3I", data, base + 20)
            min_lod, max_lod = struct.unpack_from("<2f", data, base + 32)
            register, space, visibility = struct.unpack_from("<3I", data, base + 40)
            addressing = "/".join(_ADDRESS_MODES.get(mode, str(mode)) for mode in (address_u, address_v, address_w))
            extras = []
            if filter_value & 0x40:
                extras.append(f"max anisotropy {anisotropy}")
            if (filter_value >> 7) & 3 == 1:
                extras.append(f"compare {_COMPARISON.get(comparison, comparison)}")
            if 4 in (address_u, address_v, address_w):
                extras.append(f"border {_BORDER_COLORS.get(border, border)}")
            if mip_bias:
                extras.append(f"mip bias {mip_bias:g}")
            if min_lod or max_lod < 3.4e38:
                extras.append(f"LOD {min_lod:g}-{max_lod:g}")
            suffix = f"; {', '.join(extras)}" if extras else ""
            lines.append(
                f"  s{register}, space {space} ({_SHADER_VISIBILITY.get(visibility, visibility)}): "
                f"{_filter_text(filter_value)}; {addressing}{suffix}"
            )
        if sampler_count > _ROW_LIMIT:
            lines.append(f"  ... {sampler_count - _ROW_LIMIT:,} more")
    return lines


def _limited(title: str, rows: list[str]) -> list[str]:
    if not rows:
        return []
    shown = rows[:_ROW_LIMIT]
    lines = ["", f"{title} ({len(rows):,}):"]
    lines.extend(f"  {row}" for row in shown)
    if len(rows) > len(shown):
        lines.append(f"  ... {len(rows) - len(shown):,} more")
    return lines


def build_shader_cache_preview(data: bytes, virtual_path: str, *, extension: str) -> _StructuredBinaryPreviewBundle:
    """Describe a `.padxil` shader or `.pars` root signature.

    Raises `ShaderContainerError` when the bytes do not hold a readable container,
    so the caller can keep its strings fallback.
    """

    normalized = str(extension or "").lower()
    pasc: Optional[PascHeader] = None
    container = data
    if data[:4] == PASC_MAGIC:
        pasc = read_pasc_header(data)
        container = data[pasc.payload_offset :]
    chunks = read_dxbc_chunks(container)
    names = [chunk.fourcc for chunk in chunks]
    root_signature = next((chunk for chunk in chunks if chunk.fourcc == "RTS0"), None)
    if normalized == ".pars" or (root_signature is not None and len(chunks) == 1):
        if root_signature is None:
            raise ShaderContainerError("root signature container has no RTS0 chunk")
        try:
            body = describe_root_signature(root_signature.data)
        except struct.error as exc:
            raise ShaderContainerError(f"root signature runs past its chunk: {exc}") from exc
        lines = [f"D3D12 root signature for {virtual_path}", "", "Summary:", f"- Container: DXBC, {len(container):,} bytes, chunk RTS0"]
        lines.extend(body)
        return _StructuredBinaryPreviewBundle(
            preview_text="\n".join(lines),
            detail_lines=(
                "Decoded the serialized D3D12 root signature (DXBC RTS0 chunk).",
                "Which pipelines use this root signature is not recorded in the file.",
                "This inspector is read-only.",
            ),
            metadata_label="Root Signature",
        )

    summary = summarize_shader_chunks(chunks)
    lines = [f"D3D12 shader cache entry for {virtual_path}", "", "Summary:"]
    if summary.stage:
        lines.append(f"- Stage: {summary.stage} shader")
    if summary.shader_model:
        lines.append(f"- Shader model: {summary.shader_model}" + (f" (DXIL {summary.dxil_version})" if summary.dxil_version else ""))
    if summary.entry_point:
        lines.append(f"- Entry point: {summary.entry_point}")
    if any(summary.threads):
        x, y, z = summary.threads
        lines.append(f"- Thread group: {x} x {y} x {z}")
    if summary.bitcode_bytes:
        lines.append(f"- DXIL bitcode: {summary.bitcode_bytes:,} bytes")
    if summary.reflection_bytes:
        lines.append(f"- Reflection bitcode (STAT): {summary.reflection_bytes:,} bytes")
    lines.append(f"- Container: DXBC, {len(container):,} bytes, chunks {', '.join(names)}")
    if summary.shader_hash:
        lines.append(f"- Shader hash: {summary.shader_hash}")
    if pasc is not None:
        lines.append(f"- PASC wrapper: version {pasc.version}, digest {pasc.digest.hex()}, unidentified field {pasc.unknown_u32}")
    if summary.features or summary.unknown_feature_bits:
        features = list(summary.features)
        if summary.unknown_feature_bits:
            features.append(f"0x{summary.unknown_feature_bits:x}")
        lines.append(f"- Required features: {', '.join(features)}")
    elif any(chunk.fourcc == "SFI0" for chunk in chunks):
        lines.append("- Required features: none")
    lines.extend(_limited("Exported functions", summary.functions))
    lines.extend(_limited("Resource bindings", summary.resources))
    lines.extend(_limited("Inputs", summary.inputs))
    lines.extend(_limited("Outputs", summary.outputs))
    if root_signature is not None:
        try:
            lines.extend(["", "Embedded root signature:"])
            lines.extend(describe_root_signature(root_signature.data))
        except (ShaderContainerError, struct.error):
            lines.append("- present but not readable")
    detail = [
        "Decoded the DXBC container: stage, shader model, signatures and resource bindings come from its "
        "DXIL, PSV0 and signature chunks.",
        "Resource names and the shader's instructions live in LLVM bitcode, which this preview does not "
        "disassemble.",
        "This inspector is read-only.",
    ]
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail),
        metadata_label=f"{summary.stage} Shader" if summary.stage else "Shader",
    )


__all__ = [
    "SHADER_CACHE_EXTENSIONS",
    "ShaderContainerError",
    "build_shader_cache_preview",
    "describe_root_signature",
    "read_dxbc_chunks",
    "read_pasc_header",
    "summarize_shader_chunks",
]
