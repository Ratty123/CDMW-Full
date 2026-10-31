"""Read-only Archive Browser inspector for reflection-serialized game objects.

Several formats are the same reflection container the prefab and effect readers
use (type table, string pool, data header, pointer-addressed blob). The blob
grammar :mod:`cdmw.core.effect_binary` documents for `.pae`/`.paem` also walks
these to the last byte in game build 1.0.0.3446:

- `.parg` emitter render presets (PARC-wrapped): 783 of 783
- `.pasg` emitter simulation presets (PARC-wrapped): 42 of 42
- `.uianiminit` UI animation start states (4 zero bytes, then the container): 489 of 489
- `.save` save presets (bare, or after 4 zero bytes): 396 of 397; the last is an
  empty container that declares no types
- `.pcg` convex collision geometry (bare): 320 of 320; the 56 at schema revision
  14 write collection counts without a presence byte, which the reader handles

So this module decodes with that reader and renders the object graph as text.
A decoded `.pcg` also becomes a 3D preview: face ``f`` of a hull is the polygon
``_indices[_firstFaceVertexIndices[f] : + _faceNumIndices[f]]`` over
``_vertices``. Over the 72,035 faces of all 5,788 hulls, the median face is
exactly planar with every other hull vertex behind it, and 99% are within 0.3% of
the hull's extent on both counts, which a wrong reading would not produce.
Values come straight from the declared member types; nothing here assigns
gameplay meaning beyond the member names the files carry.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional, Sequence

from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle
from cdmw.core.model_preview import _build_vertex_normals, _normalize_model_meshes
from cdmw.core.effect_binary import (
    KIND_ARRAY,
    KIND_STRING,
    KIND_STRING_LIST,
    EffectBinaryError,
    EffectDocument,
    ReflectNode,
    ReflectValue,
    decode_effect_binary,
)
from cdmw.models import ModelPreviewData, ModelPreviewMesh

REFLECT_OBJECT_EXTENSIONS = frozenset({".parg", ".pasg", ".pcg", ".save", ".uianiminit"})
TREE_LINE_LIMIT = 600
_ARRAY_PREVIEW_ITEMS = 8
_STRING_PREVIEW = 160
_ZERO_PREFIX = b"\0\0\0\0"
_REFLECT_MAGIC = b"\xff\xff"
_RESOURCE_SUFFIXES = (
    ".dds", ".pam", ".pac", ".pamlod", ".pab", ".paa", ".pae", ".paem", ".effect", ".parg", ".pasg",
    ".pcg", ".hkx", ".prefab", ".wem", ".bnk", ".xml", ".material", ".pat",
)

_TITLES = {
    ".parg": ("Emitter render preset", "Render Preset"),
    ".pasg": ("Emitter simulation preset", "Simulation Preset"),
    ".pcg": ("Convex collision geometry", "Convex Geometry"),
    ".save": ("Save preset", "Save Preset"),
    ".uianiminit": ("UI animation start state", "UI Animation State"),
    ".pae": ("Effect", "Effect"),
    ".paem": ("Emitter", "Emitter"),
}


@dataclass(frozen=True)
class ReflectObjectPreview:
    bundle: _StructuredBinaryPreviewBundle
    #: Resource-looking strings the graph names, for related-file resolution.
    reference_names: tuple[str, ...]
    #: A 3D preview when the object is geometry (`.pcg` convex hulls).
    model: Optional[ModelPreviewData] = None


def decode_reflect_object(data: bytes) -> tuple[EffectDocument, int]:
    """Decode a reflection object; returns the document and the bytes skipped before it.

    A PARC wrapper is handled by the effect reader itself. `.uianiminit` and the two
    input-pad `.save` presets put four zero bytes before the container instead.
    """

    payload = bytes(data or b"")
    skipped = 0
    if payload[:4] == _ZERO_PREFIX and payload[4:6] == _REFLECT_MAGIC:
        payload, skipped = payload[4:], 4
    return decode_effect_binary(payload), skipped


def _empty_container_size(data: bytes) -> Optional[int]:
    """The byte length of a version-4 container that declares no types, else None.

    `miscellaneous/inputpresetb.save` is one: 36 bytes, a zero type count and
    no object data. The header reader rightly refuses a zero count as damage,
    so it is recognised here instead.
    """

    payload = bytes(data or b"")
    if payload[:4] == _ZERO_PREFIX:
        payload = payload[4:]
    if len(payload) < 20 or payload[:2] != _REFLECT_MAGIC or payload[2:4] != b"\x04\x00":
        return None
    return len(data) if struct.unpack_from("<H", payload, 18)[0] == 0 else None


def _format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, tuple):
        return "(" + ", ".join(_format_scalar(item) for item in value) + ")"
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value[:32]).hex(" ")
        return f"<{len(value)} bytes: {text}{' ...' if len(value) > 32 else ''}>"
    return str(value)


def _format_typed_bytes(type_name: str, raw: bytes) -> Optional[str]:
    """Game value types the generic decoder leaves as bytes (keys, hashes, transforms)."""

    size = len(raw)
    if type_name == "Transform" and size == 40:
        # The serialized Transform: scale, quaternion xyzw, position (section 8.1 of the research notes).
        values = struct.unpack("<10f", raw)
        scale, rotation, position = values[:3], values[3:7], values[7:]
        return (
            f"scale {_format_scalar(scale)}, rotation {_format_scalar(rotation)}, "
            f"position {_format_scalar(position)}"
        )
    if type_name == "uint4" and size == 16:
        return raw.hex()
    if size in (1, 2, 4, 8):
        number = int.from_bytes(raw, "little")
        if "hash" in type_name.lower():
            return f"0x{number:0{size * 2}x}"
        return str(number)
    return None


def _array_items(value: ReflectValue) -> Optional[list[str]]:
    raw, count = value.raw, max(1, value.count)
    if not raw or len(raw) % count:
        return None
    size = len(raw) // count
    formats = {
        ("float", 4): "<f", ("float2", 8): "<2f", ("float3", 12): "<3f", ("float4", 16): "<4f",
        ("uint", 4): "<I", ("uint32", 4): "<I", ("int", 4): "<i", ("int32", 4): "<i",
        ("uint16", 2): "<H", ("int16", 2): "<h", ("uint8", 1): "<B", ("uint64", 8): "<Q",
    }
    layout = formats.get((value.type_name, size))
    items = []
    for index in range(min(count, _ARRAY_PREVIEW_ITEMS)):
        if layout is not None:
            unpacked = struct.unpack_from(layout, raw, index * size)
            items.append(_format_scalar(unpacked[0] if len(unpacked) == 1 else unpacked))
            continue
        typed = _format_typed_bytes(value.type_name, raw[index * size : (index + 1) * size])
        if typed is None:
            return None
        items.append(typed)
    return items


def format_reflect_value(value: ReflectValue) -> str:
    if value.kind == KIND_STRING:
        text = str(value.value)
        if len(text) > _STRING_PREVIEW:
            text = text[: _STRING_PREVIEW - 3] + "..."
        return f'"{text}"'
    if value.kind == KIND_STRING_LIST:
        items = list(value.value)  # type: ignore[arg-type]
        shown = ", ".join(f'"{item}"' for item in items[:_ARRAY_PREVIEW_ITEMS])
        more = f", ... {len(items) - _ARRAY_PREVIEW_ITEMS} more" if len(items) > _ARRAY_PREVIEW_ITEMS else ""
        return f"[{shown}{more}]"
    if value.kind == KIND_ARRAY:
        if not value.raw:
            return f"{value.type_name}[0] []"
        items = _array_items(value)
        if items is None:
            return f"{value.type_name}[{value.count}] {_format_scalar(value.raw)}"
        more = f", ... {value.count - len(items)} more" if value.count > len(items) else ""
        return f"{value.type_name}[{value.count}] [{', '.join(items)}{more}]"
    decoded = value.value
    if isinstance(decoded, (bytes, bytearray)):
        typed = _format_typed_bytes(value.type_name, bytes(decoded))
        if typed is not None:
            return typed
    return _format_scalar(decoded)


class _TreeWriter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.lines: list[str] = []
        self.dropped = 0

    def add(self, depth: int, text: str) -> None:
        if len(self.lines) >= self.limit:
            self.dropped += 1
            return
        self.lines.append("  " * depth + text)

    def node(self, node: ReflectNode, depth: int, label: str = "") -> None:
        heading = f"{label}: " if label else ""
        name = f' "{node.name}"' if node.name else ""
        override = " (override)" if node.override else ""
        self.add(depth, f"{heading}{node.type_name}{name}{override}")
        for value in node.values:
            self.add(depth + 1, f"{value.name} = {format_reflect_value(value)}")
        for member, child in node.children:
            if child is None:
                self.add(depth + 1, f"{member}: none")
            elif isinstance(child, tuple):
                self.add(depth + 1, f"{member} [{len(child)}]")
                for index, item in enumerate(child):
                    self.node(item, depth + 2, f"[{index}]")
            else:
                self.node(child, depth + 1, member)


def format_reflect_tree(root: ReflectNode, *, limit: int = TREE_LINE_LIMIT) -> list[str]:
    writer = _TreeWriter(limit)
    writer.node(root, 0)
    if writer.dropped:
        writer.lines.append(f"... {writer.dropped:,} more lines; extract the file to read the whole graph")
    return writer.lines


def reflect_resource_names(document: EffectDocument) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for text in document.strings():
        cleaned = str(text).strip()
        if "/" in cleaned and cleaned.lower().endswith(_RESOURCE_SUFFIXES):
            seen.setdefault(cleaned, None)
    return tuple(seen)


def describe_reflect_document(document: EffectDocument, *, skipped: int = 0) -> list[str]:
    """Summary lines shared by every reflection format (no title)."""

    if document.container_offset:
        wrapper = "PARC wrapper, reflection container"
    elif skipped:
        wrapper = f"{skipped} zero bytes, then the reflection container"
    else:
        wrapper = "bare reflection container"
    walk = (
        "complete (every blob byte accounted for)"
        if document.walk_complete
        else f"stopped early: {document.walk_note}"
    )
    lines = [
        f"- Root object: {document.root_type or 'unknown'}",
        f"- Layout: {wrapper}",
        f"- Declared types: {len(document.types):,}",
        f"- String pool: {len(document.string_pool):,}",
        f"- Object data: {document.blob_length:,} bytes",
        f"- Decode: {walk}",
    ]
    nodes = sum(1 for _node in document.root.walk())
    values = sum(len(node.values) for node in document.root.walk())
    if nodes > 1 or values:
        lines.append(f"- Objects decoded: {nodes:,}, values: {values:,}")
    return lines


def describe_declared_types(document: EffectDocument, *, limit: int = 40) -> list[str]:
    if not document.types:
        return []
    lines = ["", f"Declared types ({len(document.types):,}):"]
    for kind in document.types[:limit]:
        members = ", ".join(member.name for member in kind.members[:12])
        more = f", +{len(kind.members) - 12}" if len(kind.members) > 12 else ""
        lines.append(f"  {kind.type_name} ({len(kind.members)}): {members}{more}")
    if len(document.types) > limit:
        lines.append(f"  ... {len(document.types) - limit:,} more")
    return lines


_HULL_COLOURS = (
    (0.86, 0.55, 0.24), (0.33, 0.62, 0.86), (0.45, 0.76, 0.42), (0.80, 0.42, 0.62),
    (0.70, 0.70, 0.35), (0.48, 0.48, 0.82),
)


def _typed_items(value: Optional[ReflectValue], layout: str) -> list[tuple]:
    if value is None or value.kind != KIND_ARRAY or not value.count:
        return []
    size = struct.calcsize(layout)
    if len(value.raw) != size * value.count:
        return []
    return [struct.unpack_from(layout, value.raw, index * size) for index in range(value.count)]


def build_convex_geometry_model(document: EffectDocument, virtual_path: str) -> Optional[ModelPreviewData]:
    """One preview mesh per `ConvexHull`, each face fanned into triangles.

    A hull whose face table does not index its own vertices is left out rather
    than drawn wrongly; no model is returned when none remains.
    """

    hulls = document.root.child("_convexHullList") if document.root.type_name == "ConvexGeometry" else None
    if not isinstance(hulls, tuple):
        return None
    meshes: list[ModelPreviewMesh] = []
    skipped = 0
    for index, hull in enumerate(hulls):
        vertices = [tuple(item) for item in _typed_items(hull.value("_vertices"), "<3f")]
        first = [item[0] for item in _typed_items(hull.value("_firstFaceVertexIndices"), "<H")]
        counts = [item[0] for item in _typed_items(hull.value("_faceNumIndices"), "<H")]
        indices = list(hull.value("_indices").raw) if hull.value("_indices") is not None else []
        triangles: list[int] = []
        valid = bool(vertices) and len(first) == len(counts) and sum(counts) == len(indices)
        if valid:
            for start, count in zip(first, counts):
                polygon = indices[start : start + count]
                if len(polygon) < 3 or any(vertex >= len(vertices) for vertex in polygon):
                    valid = False
                    break
                for corner in range(1, len(polygon) - 1):
                    triangles.extend((polygon[0], polygon[corner], polygon[corner + 1]))
        if not valid or not triangles:
            skipped += 1
            continue
        meshes.append(
            ModelPreviewMesh(
                material_name=f"hull_{index:03d}",
                preview_color=_HULL_COLOURS[index % len(_HULL_COLOURS)],
                positions=vertices,
                indices=triangles,
                source_submesh_index=index,
                preview_double_sided=True,
                preview_role=f"Convex hull {index + 1}",
            )
        )
    if not meshes:
        return None
    center, scale = _normalize_model_meshes(meshes)
    for mesh in meshes:
        mesh.normals = _build_vertex_normals(mesh.positions, mesh.indices)
    vertex_count = sum(len(mesh.positions) for mesh in meshes)
    face_count = sum(len(mesh.indices) // 3 for mesh in meshes)
    skipped_text = f"\n{skipped} hull(s) with an unreadable face table left out" if skipped else ""
    return ModelPreviewData(
        path=virtual_path,
        format="pcg",
        summary=(
            f"{virtual_path}\nConvex collision geometry\n{len(meshes):,} hulls\n"
            f"{vertex_count:,} vertices\n{face_count:,} triangles{skipped_text}"
        ),
        mesh_count=len(meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        normalization_center=center,
        normalization_scale=scale,
        meshes=meshes,
    )


def build_reflect_object_preview(data: bytes, virtual_path: str, *, extension: str) -> ReflectObjectPreview:
    """Decode and render one reflection object.

    Raises `EffectBinaryError` when the type table or data header does not parse,
    so the caller can keep its strings fallback.
    """

    normalized = str(extension or "").lower()
    title, label = _TITLES.get(normalized, ("Reflection object", "Reflection Object"))
    empty = _empty_container_size(data)
    if empty is not None:
        return ReflectObjectPreview(
            bundle=_StructuredBinaryPreviewBundle(
                preview_text="\n".join(
                    [
                        f"{title} inspector for {virtual_path}",
                        "",
                        "Summary:",
                        "- Root object: none; the container declares no types",
                        f"- Size: {empty:,} bytes",
                    ]
                ),
                detail_lines=("This file is an empty reflection container.", "This inspector is read-only."),
                metadata_label=f"{label} (empty)",
            ),
            reference_names=(),
        )
    document, skipped = decode_reflect_object(data)
    references = reflect_resource_names(document)
    lines = [f"{title} inspector for {virtual_path}", "", "Summary:"]
    lines.extend(describe_reflect_document(document, skipped=skipped))
    if references:
        lines.append(f"- Resource paths named: {len(references):,}")
    if references:
        lines.extend(["", "Resource paths:"])
        lines.extend(f"  {reference}" for reference in references[:40])
        if len(references) > 40:
            lines.append(f"  ... {len(references) - 40:,} more")
    if document.walk_complete or document.root.values or document.root.children:
        lines.extend(["", "Object graph:"])
        lines.extend(format_reflect_tree(document.root))
    lines.extend(describe_declared_types(document))
    detail = [
        "Decoded with the reflection grammar the effect reader uses; values follow their declared member types.",
    ]
    if not document.walk_complete:
        detail.append(f"The object data was not read to the end ({document.walk_note}); the declared types are still listed.")
    model = build_convex_geometry_model(document, virtual_path) if normalized == ".pcg" and document.walk_complete else None
    if model is not None:
        detail.append(f"The 3D view draws {model.mesh_count:,} convex hulls, one colour each.")
    detail.append("This inspector is read-only.")
    return ReflectObjectPreview(
        bundle=_StructuredBinaryPreviewBundle(
            preview_text="\n".join(lines),
            detail_lines=tuple(detail),
            metadata_label=label,
        ),
        reference_names=references,
        model=model,
    )


def build_effect_tree_section(data: bytes, *, extension: str) -> list[str]:
    """The exact decoded graph of a `.pae`/`.paem`, for the effect inspector to lead with.

    Returns no lines when the payload does not decode, so the caller keeps its
    existing output unchanged.
    """

    try:
        document = decode_effect_binary(data)
    except EffectBinaryError:
        return []
    lines = ["Decoded object graph:"]
    lines.extend(describe_reflect_document(document))
    emitters = document.emitter_names()
    if emitters:
        lines.append(f"- Emitters named: {', '.join(emitters[:8])}" + (f" (+{len(emitters) - 8} more)" if len(emitters) > 8 else ""))
    lines.append("")
    lines.extend(format_reflect_tree(document.root))
    return lines


__all__ = [
    "REFLECT_OBJECT_EXTENSIONS",
    "ReflectObjectPreview",
    "build_convex_geometry_model",
    "build_effect_tree_section",
    "build_reflect_object_preview",
    "decode_reflect_object",
    "describe_reflect_document",
    "format_reflect_tree",
    "format_reflect_value",
    "reflect_resource_names",
]
