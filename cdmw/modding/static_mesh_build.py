"""Static mesh replacement build and preview orchestration."""

from __future__ import annotations

import copy

from .logging import get_logger
from .mesh_parser import ParsedMesh, inspect_mesh_binary_layout
from .static_mesh_analysis import (
    _format_static_report_failure,
    _replacement_mesh_from_options,
    analyze_static_replacement,
)
from .static_mesh_mapping import suggest_static_submesh_mappings
from .static_mesh_runtime_builder import (
    _build_mapped_replacement_mesh,
    _replacement_mesh_with_original_part_copies,
)
from .static_mesh_source_parts import _independent_parts_for_options
from .static_mesh_types import (
    StaticMeshReplacementOptions,
    StaticMeshReplacementReport,
    StaticSubmeshMapping,
)

logger = get_logger("core.static_mesh_replacer")


def build_static_mesh_replacement(
    original_data: bytes,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions | None = None,
) -> tuple[bytes, StaticMeshReplacementReport]:
    """Build a static replacement PAC/PAM payload from an arbitrary OBJ mesh."""
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
    normalized_options = copy.copy(normalized_options)
    normalized_options.submesh_mappings = mappings

    report = analyze_static_replacement(original_mesh, replacement_mesh, normalized_options)
    layout = inspect_mesh_binary_layout(original_data, original_mesh.path)
    report.warnings.extend(layout.warnings)

    if original_mesh.format.lower() == "pamlod":
        report.errors.append("Static replacement currently supports one selected PAC/PAM mesh payload, not PAMLOD.")
    independent_output_parts = _independent_parts_for_options(
        normalized_options,
        effective_replacement_mesh,
        include_preview_only=False,
    )
    if independent_output_parts:
        labels = ", ".join(
            str(part.label or f"source {part.source_submesh_index}")
            for part in independent_output_parts[:4]
        )
        if len(independent_output_parts) > 4:
            labels += f", +{len(independent_output_parts) - 4} more"
        report.errors.append(
            "Independent added mesh parts cannot be written into this PAC/PAM layout yet because the current "
            "serializer preserves the original draw-section descriptor set. Attach the part to an existing target "
            f"draw slot, or export after native draw-section cloning is available. Independent part(s): {labels}."
        )
    if normalized_options.replace_lods:
        report.warnings.append("LOD replacement was requested, but this first version only replaces the selected mesh/LOD.")
    fmt = original_mesh.format.lower()
    cloned_draw_sections = [
        section
        for section in report.output_draw_sections
        if bool(getattr(section, "is_cloned_section", False))
    ]
    if cloned_draw_sections and fmt != "pac":
        report.errors.append(
            "Dense preserve-split output requires PAC draw-section cloning. "
            "PAM/PAMLOD cloning is not enabled; reduce the source mesh or map fewer source parts into each target."
        )
    if report.errors:
        raise ValueError(_format_static_report_failure(report))

    working_mesh = _build_mapped_replacement_mesh(
        original_mesh,
        replacement_mesh,
        mappings,
        normalized_options,
        output_draw_sections=report.output_draw_sections,
    )

    if fmt == "pac":
        from .mesh_importer import _build_pac_full_rebuild

        complete_external_swap = bool(getattr(normalized_options, "complete_external_swap", False))
        rebuilt = _build_pac_full_rebuild(
            original_mesh,
            working_mesh,
            original_data,
            clone_descriptor_sources=[] if complete_external_swap else [
                int(section.clone_source_target_index)
                for section in cloned_draw_sections
            ],
            clone_descriptor_names=[] if complete_external_swap else [
                str(section.target_submesh_name or "").strip()
                for section in cloned_draw_sections
            ],
            preserve_runtime_abi=complete_external_swap,
        )
    elif fmt == "pam":
        from .mesh_importer import build_pam

        rebuilt = build_pam(working_mesh, original_data)
    else:
        report.errors.append(f"Unsupported static replacement mesh format: {original_mesh.format or 'unknown'}")
        raise ValueError(_format_static_report_failure(report))

    logger.info(
        "Built static mesh replacement for %s: %d -> %d submesh source(s), %d bytes",
        original_mesh.path,
        len(effective_replacement_mesh.submeshes),
        len(working_mesh.submeshes),
        len(rebuilt),
    )
    return rebuilt, report


def build_static_replacement_preview_mesh(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions | None = None,
    *,
    max_source_faces_per_submesh: int | None = None,
) -> ParsedMesh:
    """Build the mapped/transformed preview mesh without serializing a PAC/PAM payload."""
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
    mappings_by_target = {mapping.target_submesh_index: mapping for mapping in mappings}
    complete_mappings: list[StaticSubmeshMapping] = []
    for target_index, target in enumerate(original_mesh.submeshes):
        mapping = mappings_by_target.get(target_index)
        if mapping is not None:
            complete_mappings.append(mapping)
            continue
        complete_mappings.append(
            StaticSubmeshMapping(
                target_submesh_index=target_index,
                target_submesh_name=target.material or target.name or f"target {target_index}",
                source_submesh_indices=[],
                target_material_slot_index=target_index,
                merge_sources=True,
            )
        )
    normalized_options = copy.copy(normalized_options)
    normalized_options.submesh_mappings = complete_mappings
    return _build_mapped_replacement_mesh(
        original_mesh,
        replacement_mesh,
        complete_mappings,
        normalized_options,
        enforce_vertex_limit=False,
        max_source_faces_per_submesh=max_source_faces_per_submesh,
    )
