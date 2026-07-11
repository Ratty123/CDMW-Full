from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, List, Sequence

if TYPE_CHECKING:
    from cdmw.core.archive_hkx import HkxPreviewResult


_ASSET_EXTENSIONS = (".hkx", ".motionblending", ".pab", ".pac", ".pam", ".pamlod", ".xml", ".pami", ".dds")
_STRUCTURED_MARKERS = (
    "hkRootLevelContainer",
    "hkaAnimation",
    "hkaSkeleton",
    "hkaAnimationBinding",
    "hkpPhysicsData",
    "hknpPhysicsSystem",
    "hknpCompoundShape",
    "hknpShapeInstance",
)


def _hkx_preview_asset_references(printable: Sequence[str]) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    for text in printable:
        normalized = str(text or "").strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        if any(lowered.endswith(extension) for extension in _ASSET_EXTENSIONS):
            seen.add(lowered)
            references.append(normalized)
    return references


def _hkx_preview_markers(class_names: Sequence[str], printable: Sequence[str]) -> List[str]:
    return [
        marker
        for marker in _STRUCTURED_MARKERS
        if marker in class_names or any(marker in item for item in printable)
    ]


def _append_hkx_format_summary(hkx, data, summary, class_names, tag_sections, declared_size, lines, detail_lines) -> None:
    if summary.tag0_offset < 0 and not summary.sdk_version and not tag_sections:
        return
    lines.append("Format summary:")
    if declared_size is not None and summary.size_matches:
        lines.append(f"- Declared size: {declared_size:,} bytes")
        detail_lines.append(f"Declared HKX size matches payload size ({declared_size:,} bytes).")
    elif summary.declared_size is not None:
        lines.append(f"- Declared size: {summary.declared_size:,} bytes (payload: {len(data):,} bytes)")
    if summary.tag0_offset >= 0:
        lines.append(f"- TAG0 header offset: {summary.tag0_offset}")
    if summary.sdk_version:
        lines.append(f"- Havok SDK version: {summary.sdk_version} ({hkx._hkx_sdk_version_label(summary.sdk_version)})")
        detail_lines.append(f"Detected Havok SDK version {summary.sdk_version}.")
    if tag_sections:
        lines.append("- Detected tag sections: " + ", ".join(tag_sections))
    type_families = hkx._summarize_hkx_type_families(class_names)
    if type_families:
        lines.append("- Type families: " + "; ".join(type_families[:6]))
        if any(name.startswith("hknp") for name in class_names):
            detail_lines.append("Detected modern Havok Physics (hknp) type markers.")
    if summary.declared_type_name_count is not None:
        lines.append(f"- TNA1 declared type names: {summary.declared_type_name_count:,}")
    if summary.item_records:
        lines.append(f"- Inferred ITEM records: {len(summary.item_records):,}")
        detail_lines.append(f"Decoded {len(summary.item_records):,} inferred Havok ITEM table record(s).")
    lines.append("")


def _append_hkx_tag_items(data: bytes, summary, lines: List[str]) -> None:
    if not summary.tag_items:
        return
    lines.append("Tag item map:")
    for item in summary.tag_items[:24]:
        if item.declared_length is None:
            lines.append(f"- {item.name}: offset {item.offset:,}")
            continue
        flags_text = f", flags=0x{item.length_flags:08X}" if item.length_flags else ""
        end_text = ""
        if item.word_end_offset is not None and item.word_end_offset <= len(data):
            end_text = f", data-end {item.word_end_offset:,}"
        elif item.marker_end_offset is not None and item.marker_end_offset <= len(data):
            end_text = f", marker-end {item.marker_end_offset:,}"
        lines.append(f"- {item.name}: offset {item.offset:,}, length {item.declared_length:,}{flags_text}{end_text}")
    if len(summary.tag_items) > 24:
        lines.append(f"... {len(summary.tag_items) - 24} more tag item(s)")
    lines.append("")


def _hkx_collision_hint_parts(hint) -> List[str]:
    parts: List[str] = []
    if hint.shape_type:
        parts.append(hint.shape_type)
    if hint.shape_record_index is not None:
        parts.append(f"shape-record={hint.shape_record_index}")
    if hint.radius is not None:
        parts.append(f"radius={hint.radius:.6g}")
    if hint.capsule_length is not None:
        parts.append(f"capsule length={hint.capsule_length:.6g}")
    for value, label in (
        (hint.vertex_count, "vertices"),
        (hint.plane_count, "planes"),
        (hint.face_count, "faces"),
        (hint.face_index_count, "face-index bytes"),
        (hint.edge_pair_count, "edge pairs"),
        (hint.mesh_section_count, "mesh sections"),
        (hint.mesh_primitive_count, "mesh primitives"),
        (hint.mesh_aabb_node_count, "aabb nodes"),
        (hint.mesh_shape_tag_count, "shape tags"),
        (hint.mesh_data_byte_count, "mesh data bytes"),
    ):
        if value:
            parts.append(f"{label}={value:,}")
    return parts


def _hkx_collision_detail_bits(hint) -> List[str]:
    bits: List[str] = []
    if hint.radius is not None:
        bits.append(f"radius={hint.radius:.6g}")
    if hint.capsule_length is not None:
        bits.append(f"capsule length={hint.capsule_length:.6g}")
    if hint.vertex_count:
        bits.append(f"vertices={hint.vertex_count:,}")
    if hint.plane_count:
        bits.append(f"planes={hint.plane_count:,}")
    if hint.mesh_primitive_count:
        bits.append(f"mesh primitives={hint.mesh_primitive_count:,}")
    if hint.mesh_section_count:
        bits.append(f"mesh sections={hint.mesh_section_count:,}")
    return bits


def _append_hkx_collision_hints(hkx, summary, lines: List[str], detail_lines: List[str]) -> None:
    hints = summary.collision_geometry_hints
    if not hints:
        return
    lines.extend(["", "Collision geometry hints:"])
    editable_count = sum(1 for hint in hints if hint.shape_type != "hknpMeshShape")
    if editable_count:
        lines.append(
            f"Editable JSON geometry patch: {editable_count:,} shape(s) support fixed-size numeric edits "
            "(vertices/planes or sphere center/radius)."
        )
        detail_lines.append(f"Editable HKX geometry patch data can be exported for {editable_count:,} shape(s).")
    for hint in hints[:8]:
        lines.append("- " + "; ".join(_hkx_collision_hint_parts(hint)))
        if hint.bounds_min is not None and hint.bounds_max is not None:
            lines.append(
                f"  bounds: min={hkx._format_hkx_vector(hint.bounds_min)}, "
                f"max={hkx._format_hkx_vector(hint.bounds_max)}"
            )
        if hint.center is not None and hint.extent is not None:
            lines.append(
                f"  approx center={hkx._format_hkx_vector(hint.center)}, "
                f"extent={hkx._format_hkx_vector(hint.extent)}"
            )
        if hint.face_vertex_indices:
            lines.append(
                "  face vertex loops: "
                + "; ".join(
                    "[" + ", ".join(str(vertex_index) for vertex_index in face) + "]"
                    for face in hint.face_vertex_indices[:8]
                )
            )
        detail_bits = _hkx_collision_detail_bits(hint)
        if detail_bits:
            detail_lines.append("Inferred collision geometry hints: " + ", ".join(detail_bits) + ".")
    if len(hints) > 8:
        lines.append(f"... {len(hints) - 8} more collision geometry hint(s)")


def _append_hkx_item_records(summary, lines: List[str]) -> None:
    if not summary.item_records:
        return
    type_counts = Counter(record.type_name or f"type[{record.type_index}]" for record in summary.item_records)
    lines.extend(["", "Inferred ITEM table:"])
    lines.append("Record type counts:")
    for type_name, count in type_counts.most_common(16):
        lines.append(f"- {type_name}: {count:,}")
    if summary.item_payload_summaries:
        lines.extend(["", "DATA payload summaries:"])
        for payload_summary in summary.item_payload_summaries[:24]:
            stride_text = f", stride={payload_summary.inferred_stride:.3g}" if payload_summary.inferred_stride is not None else ""
            lines.append(
                f"[{payload_summary.record_index:02d}] {payload_summary.type_name}: "
                f"{payload_summary.byte_length:,} byte(s){stride_text}"
            )
            for payload_line in payload_summary.lines[:3]:
                lines.append(f"     - {payload_line}")
        if len(summary.item_payload_summaries) > 24:
            lines.append(f"... {len(summary.item_payload_summaries) - 24} more payload summary row(s)")
    lines.append("")
    lines.append("Records:")
    for record in summary.item_records[:40]:
        type_text = record.type_name or f"type[{record.type_index}]"
        absolute_text = f", absolute=0x{record.absolute_data_offset:X}" if record.absolute_data_offset is not None else ""
        lines.append(
            f"[{record.index:02d}] {type_text} "
            f"type={record.type_index} flags=0x{record.flags:08X} "
            f"data=0x{record.data_offset:X}{absolute_text} count={record.count:,}"
        )
    if len(summary.item_records) > 40:
        lines.append(f"... {len(summary.item_records) - 40} more record(s)")


def build_hkx_preview(data: bytes, virtual_path: str) -> HkxPreviewResult:
    from cdmw.core import archive_hkx as hkx

    summary = hkx.parse_hkx_tagfile_summary(data)
    printable = hkx._extract_hkx_printable_strings(data)
    class_names = summary.type_names or hkx._extract_hkx_type_names(printable)
    tag_sections = hkx._detect_hkx_tag_sections(data)
    declared_size = summary.declared_size if summary.size_matches else hkx._detect_hkx_declared_size(data)
    asset_references = _hkx_preview_asset_references(printable)
    markers = _hkx_preview_markers(class_names, printable)
    lines = [f"HKX tagfile preview for {virtual_path}", ""]
    detail_lines = ["Structured Havok tagfile or binary animation metadata detected."]
    _append_hkx_format_summary(hkx, data, summary, class_names, tag_sections, declared_size, lines, detail_lines)
    _append_hkx_tag_items(data, summary, lines)
    if class_names:
        detail_lines.append(f"Detected {len(class_names):,} Havok class/type marker(s).")
        lines.append("Detected classes/types:")
        lines.extend(class_names[:64])
    _append_hkx_collision_hints(hkx, summary, lines, detail_lines)
    _append_hkx_item_records(summary, lines)
    if markers:
        detail_lines.append(f"Detected structured marker(s): {', '.join(markers[:6])}.")
        lines.extend(["", "Detected markers:"])
        lines.extend(markers[:12])
    if asset_references:
        detail_lines.append(f"Detected {len(asset_references):,} related asset reference(s).")
        lines.extend(["", "Detected asset references:"])
        lines.extend(asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"... {len(asset_references) - 24} more")
    elif printable:
        lines.append("Readable strings:")
        lines.extend(printable[:64])
    else:
        lines.append("No readable Havok strings were recovered from the preview sample.")
    if len(printable) >= hkx._HKX_PRINTABLE_STRING_LIMIT:
        lines.extend(("", "String scan truncated to keep the preview responsive."))
    if summary.warnings:
        detail_lines.extend(summary.warnings)
        lines.extend(["", "Parser warnings:"])
        lines.extend(f"- {warning}" for warning in summary.warnings)
    return hkx.HkxPreviewResult(preview_text="\n".join(lines), detail_lines=detail_lines)
