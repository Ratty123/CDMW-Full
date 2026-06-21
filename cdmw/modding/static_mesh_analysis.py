"""Static mesh replacement analysis and diagnostics."""

from __future__ import annotations

from .mesh_parser import ParsedMesh
from .static_mesh_geometry import (
    _GRIP_MARKER_NAMES,
    _TIP_MARKER_NAMES,
    _append_alignment_summary,
    _axis_length,
    _axis_vector,
    _bbox,
    _dims,
    _dominant_axis,
    _find_marker_anchor_any,
    _format_vec,
    _infer_grip_anchor,
    _infer_tip_anchor,
    _is_marker_submesh,
)
from .static_mesh_mapping import (
    _append_special_runtime_slot_mapping_findings,
    _confidence_label,
    suggest_static_submesh_mappings,
)
from .static_mesh_output_plan import _dense_export_mode, plan_static_output_draw_sections
from .static_mesh_runtime_builder import _replacement_mesh_with_original_part_copies
from .static_mesh_source_parts import _independent_source_indices, _source_part_adjustments_by_index
from .static_mesh_types import (
    StaticMeshReplacementOptions,
    StaticMeshReplacementReport,
    StaticSubmeshMapping,
)


def _replacement_mesh_from_options(
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions,
) -> ParsedMesh:
    edited = getattr(options, "edited_source_mesh", None)
    if isinstance(edited, ParsedMesh):
        return edited
    return replacement_mesh


def analyze_static_replacement(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions | None = None,
) -> StaticMeshReplacementReport:
    """Analyze a replacement OBJ against an original parsed mesh."""
    normalized_options = options or StaticMeshReplacementOptions()
    replacement_mesh = _replacement_mesh_from_options(replacement_mesh, normalized_options)
    effective_replacement_mesh, _preserve_source_indices = _replacement_mesh_with_original_part_copies(
        original_mesh,
        replacement_mesh,
        normalized_options.original_part_copies,
    )
    mappings = normalized_options.submesh_mappings or suggest_static_submesh_mappings(
        original_mesh,
        effective_replacement_mesh,
    )
    report = _base_report(original_mesh, effective_replacement_mesh)
    _append_mapping_summary(report, original_mesh, effective_replacement_mesh, mappings)
    _append_static_warnings(report, original_mesh, effective_replacement_mesh, mappings, normalized_options)
    _append_mapping_errors(report, original_mesh, effective_replacement_mesh, mappings, normalized_options)
    output_sections, dense_warnings, dense_errors = plan_static_output_draw_sections(
        original_mesh,
        effective_replacement_mesh,
        mappings,
        normalized_options,
    )
    report.output_draw_sections = output_sections
    report.dense_summary.extend(dense_warnings)
    report.warnings.extend(dense_warnings)
    if dense_errors:
        report.dense_summary.extend(dense_errors)
        report.errors.extend(dense_errors)
    if any(section.is_cloned_section for section in output_sections) and original_mesh.format.lower() != "pac":
        report.errors.append(
            "Dense preserve-split output needs cloned draw sections, but this asset is not a PAC. "
            "Reduce the source mesh or map fewer source parts into each target draw slot."
        )
    _append_alignment_summary(report, original_mesh, effective_replacement_mesh, normalized_options.transform)
    return report


def describe_static_placement_context(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
) -> list[str]:
    """Return user-facing placement values for manual static alignment."""
    original_axis = _dominant_axis(original_mesh) or "unknown"
    replacement_axis = _dominant_axis(replacement_mesh) or "unknown"
    original_anchor = _infer_grip_anchor(original_mesh)
    replacement_anchor = _find_marker_anchor_any(replacement_mesh, _GRIP_MARKER_NAMES) or _infer_grip_anchor(replacement_mesh)
    original_tip = _infer_tip_anchor(original_mesh)
    replacement_tip = _find_marker_anchor_any(replacement_mesh, _TIP_MARKER_NAMES) or _infer_tip_anchor(replacement_mesh)
    original_vertices = [vertex for submesh in original_mesh.submeshes for vertex in submesh.vertices]
    replacement_vertices = [
        vertex
        for submesh in replacement_mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]
    original_min, original_max = _bbox(original_vertices)
    replacement_min, replacement_max = _bbox(replacement_vertices)
    original_axis_vec = _axis_vector(original_axis)
    replacement_axis_vec = _axis_vector(replacement_axis)
    original_length = _axis_length(original_mesh, original_axis_vec)
    replacement_length = _axis_length(replacement_mesh, replacement_axis_vec)
    fit_scale = original_length / replacement_length if replacement_length > 1e-8 and original_length > 1e-8 else 1.0
    return [
        f"Original bbox: min {_format_vec(original_min)} max {_format_vec(original_max)} dims {_format_vec(_dims(original_min, original_max))}",
        f"Replacement bbox: min {_format_vec(replacement_min)} max {_format_vec(replacement_max)} dims {_format_vec(_dims(replacement_min, replacement_max))}",
        f"Original axis/length: {original_axis.upper()} / {original_length:.5g}",
        f"Replacement axis/length: {replacement_axis.upper()} / {replacement_length:.5g}",
        f"Original inferred anchor: {_format_vec(original_anchor)}",
        f"Replacement inferred anchor: {_format_vec(replacement_anchor)}",
        f"Original inferred far end: {_format_vec(original_tip)}",
        f"Replacement inferred far end: {_format_vec(replacement_tip)}",
        f"Auto length scale: {fit_scale:.6g}",
    ]


def effective_static_replacement_source_mesh(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions | None = None,
) -> ParsedMesh:
    """Return the replacement source mesh after appending copied original parts."""
    normalized_options = options or StaticMeshReplacementOptions()
    replacement_mesh = _replacement_mesh_from_options(replacement_mesh, normalized_options)
    effective_mesh, _preserve_source_indices = _replacement_mesh_with_original_part_copies(
        original_mesh,
        replacement_mesh,
        normalized_options.original_part_copies,
    )
    return effective_mesh


def _base_report(original_mesh: ParsedMesh, replacement_mesh: ParsedMesh) -> StaticMeshReplacementReport:
    return StaticMeshReplacementReport(
        original_submesh_count=len(original_mesh.submeshes),
        replacement_submesh_count=len(replacement_mesh.submeshes),
        original_vertex_count=sum(len(sm.vertices) for sm in original_mesh.submeshes),
        replacement_vertex_count=sum(len(sm.vertices) for sm in replacement_mesh.submeshes),
        original_face_count=sum(len(sm.faces) for sm in original_mesh.submeshes),
        replacement_face_count=sum(len(sm.faces) for sm in replacement_mesh.submeshes),
    )


def _append_mapping_summary(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
) -> None:
    for mapping in mappings:
        if mapping.target_submesh_index >= len(original_mesh.submeshes):
            continue
        target = original_mesh.submeshes[mapping.target_submesh_index]
        source_labels = []
        for source_index in mapping.source_submesh_indices:
            if source_index >= len(replacement_mesh.submeshes):
                continue
            source = replacement_mesh.submeshes[source_index]
            source_labels.append(source.material or source.name or f"source {source_index}")
        if not source_labels:
            source_labels.append("(no replacement source)")
        confidence = str(mapping.confidence_label or "").strip()
        suffix = f" [{confidence} confidence]" if confidence and source_labels != ["(no replacement source)"] else ""
        report.mapping_summary.append(
            f"{' + '.join(source_labels)} -> {target.material or target.name or mapping.target_submesh_name}{suffix}"
        )


def _append_static_warnings(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions,
) -> None:
    if len(original_mesh.submeshes) != len(replacement_mesh.submeshes):
        report.warnings.append(
            "Replacement submesh count differs from the original; source objects will be mapped/merged into original draw sections."
        )
    original_materials = {sm.material or sm.name for sm in original_mesh.submeshes if sm.material or sm.name}
    replacement_materials = {sm.material or sm.name for sm in replacement_mesh.submeshes if sm.material or sm.name}
    if len(replacement_materials) > len(original_materials):
        report.warnings.append(
            "Replacement uses more material names than the original; static replacement reuses original material slots."
        )
    if any(len(mapping.source_submesh_indices) > 1 for mapping in mappings):
        if _dense_export_mode(options) == "preserve_split":
            report.warnings.append(
                "Multiple replacement submeshes map to at least one original draw section; dense groups will be split before export when needed."
            )
        else:
            report.warnings.append("Multiple replacement submeshes will be merged into at least one original draw section.")
    low_confidence_mappings = [
        mapping
        for mapping in mappings
        if mapping.source_submesh_indices and _confidence_label(mapping.confidence_score) == "low"
    ]
    if low_confidence_mappings:
        examples = ", ".join(
            f"target {mapping.target_submesh_index} ({mapping.target_submesh_name})"
            for mapping in low_confidence_mappings[:4]
        )
        report.warnings.append(
            "Low-confidence static submesh mapping detected. Review the source index mapping before building; "
            f"examples: {examples}."
        )
    empty_targets = [mapping.target_submesh_index for mapping in mappings if not mapping.source_submesh_indices]
    if empty_targets:
        if options.allow_empty_target_submeshes:
            report.warnings.append(
                "Original draw section(s) with no replacement source will be emitted empty: "
                f"{empty_targets}."
            )
        else:
            report.warnings.append(
                "Original draw section(s) have no replacement source and empty output is disabled: "
                f"{empty_targets}."
            )
    if original_mesh.has_bones:
        report.warnings.append(
            "Original mesh has bone/weight data. Static replacement will clone compatible original vertex records; new skinning is not authored from OBJ."
        )
    _append_special_runtime_slot_mapping_findings(report, original_mesh, replacement_mesh, mappings, options)

    original_axis = _dominant_axis(original_mesh)
    replacement_axis = _dominant_axis(replacement_mesh)
    if original_axis and replacement_axis and original_axis != replacement_axis:
        report.warnings.append(
            f"Replacement appears oriented along {replacement_axis.upper()}, while original appears oriented along {original_axis.upper()}."
        )
    if options.transform.fit_to_original_bbox:
        report.warnings.append("Replacement vertices will be fit to the original bounding box before serialization.")


def _append_mapping_errors(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions,
) -> None:
    if not original_mesh.submeshes:
        report.errors.append("Original mesh has no parsed submeshes to replace.")
    if not replacement_mesh.submeshes:
        report.errors.append("Replacement OBJ has no parsed submeshes.")
    seen_targets: set[int] = set()
    seen_sources: set[int] = set()
    disabled_sources = {
        source_index
        for source_index, adjustment in _source_part_adjustments_by_index(options.source_part_adjustments).items()
        if not adjustment.enabled
    }
    for mapping in mappings:
        if mapping.target_submesh_index < 0 or mapping.target_submesh_index >= len(original_mesh.submeshes):
            report.errors.append(f"Mapping references invalid target submesh index {mapping.target_submesh_index}.")
            continue
        if mapping.target_submesh_index in seen_targets:
            report.errors.append(f"Target submesh {mapping.target_submesh_index} is mapped more than once.")
        seen_targets.add(mapping.target_submesh_index)
        if not mapping.source_submesh_indices and not options.allow_empty_target_submeshes:
            report.errors.append(f"Target submesh {mapping.target_submesh_index} has no replacement source submesh.")
        if len(mapping.source_submesh_indices) > 1 and not options.allow_merge_source_submeshes:
            report.errors.append(
                f"Target submesh {mapping.target_submesh_index} requires merging, but merging is disabled."
            )
        for source_index in mapping.source_submesh_indices:
            if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
                report.errors.append(f"Mapping references invalid source submesh index {source_index}.")
            elif _is_marker_submesh(replacement_mesh.submeshes[source_index]):
                report.errors.append(f"Mapping references marker source submesh index {source_index}; marker objects are not render geometry.")
            elif source_index not in disabled_sources:
                seen_sources.add(source_index)
    missing_targets = set(range(len(original_mesh.submeshes))) - seen_targets
    if missing_targets:
        report.errors.append(f"Missing target mapping for original submesh index(es): {sorted(missing_targets)}.")
    render_source_indices = {
        index
        for index, source_submesh in enumerate(replacement_mesh.submeshes)
        if not _is_marker_submesh(source_submesh) and index not in disabled_sources
    }
    render_source_indices -= _independent_source_indices(
        options,
        replacement_mesh,
        include_preview_only=True,
    )
    missing_sources = render_source_indices - seen_sources
    if missing_sources:
        report.warnings.append(f"Replacement source submesh index(es) not used by mapping: {sorted(missing_sources)}.")


def _format_static_report_failure(report: StaticMeshReplacementReport) -> str:
    lines = [
        "Static mesh replacement failed.",
        "",
        "Original:",
        f"  submeshes: {report.original_submesh_count}",
        f"  vertices: {report.original_vertex_count}",
        f"  faces: {report.original_face_count}",
        "",
        "Replacement:",
        f"  submeshes: {report.replacement_submesh_count}",
        f"  vertices: {report.replacement_vertex_count}",
        f"  faces: {report.replacement_face_count}",
    ]
    if report.mapping_summary:
        lines.extend(["", "Mapping:"])
        lines.extend(f"  {line}" for line in report.mapping_summary)
    if report.output_draw_sections:
        lines.extend(["", "Output draw sections:"])
        for section in report.output_draw_sections[:12]:
            suffix = " cloned" if section.is_cloned_section else ""
            sources = ", ".join(str(index) for index in section.source_submesh_indices) or "empty"
            lines.append(
                f"  {section.output_index}: target {section.target_submesh_index}{suffix}, "
                f"sources [{sources}], vertices {section.vertex_count:,}"
            )
        if len(report.output_draw_sections) > 12:
            lines.append(f"  ... {len(report.output_draw_sections) - 12} more")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"  {line}" for line in report.warnings)
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend(f"  {line}" for line in report.errors)
    return "\n".join(lines)
