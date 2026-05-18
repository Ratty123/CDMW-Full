"""Static OBJ replacement path for PAC/PAM mesh payloads.

This module is intentionally separate from mesh_importer.py.  The importer
remains the strict round-trip edit path; this module maps arbitrary static OBJ
submeshes onto the original game draw sections and asks the binary builders to
serialize new vertex/index buffers.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .logging import get_logger
from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals, inspect_mesh_binary_layout

logger = get_logger("core.static_mesh_replacer")

_STATIC_REPLACEMENT_VERTEX_LIMIT = 65535


@dataclass
class StaticSubmeshMapping:
    target_submesh_index: int
    target_submesh_name: str
    source_submesh_indices: list[int]
    target_material_slot_index: int
    merge_sources: bool = True
    confidence_score: float = 0.0
    confidence_label: str = ""


@dataclass
class StaticReplacementTransform:
    rotate_xyz_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: float = 1.0
    scale_xyz: tuple[float, float, float] | None = None
    offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fit_to_original_bbox: bool = False
    preserve_aspect_ratio: bool = True
    scale_to_original_length: bool = True
    alignment_mode: str = "grid_flat"
    source_anchor: tuple[float, float, float] | None = None
    target_anchor: tuple[float, float, float] | None = None
    source_axis: tuple[float, float, float] | None = None
    target_axis: tuple[float, float, float] | None = None
    flip_source_axis: bool = False
    flip_target_axis: bool = False
    manual_adjustment: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class StaticSourcePartAdjustment:
    source_submesh_index: int
    enabled: bool = True
    offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate_xyz_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0)
    uniform_scale: float = 1.0
    pivot_mode: str = "part_center"


@dataclass
class StaticOriginalPartCopy:
    original_submesh_index: int
    label: str = ""
    keep_original_placement: bool = True


@dataclass
class StaticTextureSlotOverride:
    target_texture_path: str
    source_path: str = ""
    slot_kind: str = ""
    target_material_name: str = ""
    enabled: bool = True
    source_material_name: str = ""


@dataclass
class StaticSourceMaterialTextureOverride:
    source_material_name: str
    slot_kind: str
    source_path: str
    enabled: bool = True


@dataclass
class StaticDonorMaterialTextureBinding:
    parameter_name: str = ""
    texture_path: str = ""
    slot_kind: str = ""
    semantic_subtype: str = ""
    source_path: str = ""


@dataclass
class StaticDonorMaterialPlan:
    target_material_name: str
    donor_sidecar_path: str = ""
    donor_sidecar_text: str = ""
    donor_sidecar_kind: str = ""
    donor_material_name: str = ""
    donor_submesh_name: str = ""
    donor_shader_family: str = ""
    patch_mode: str = "material_behavior"
    texture_bindings: list[StaticDonorMaterialTextureBinding] = field(default_factory=list)
    target_anchor_texture_paths: list[str] = field(default_factory=list)
    donor_anchor_texture_paths: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class StaticTextureUvTransform:
    source_material_name: str
    rotate_degrees: int = 0
    flip_u: bool = False
    flip_v: bool = False
    offset_uv: tuple[float, float] = (0.0, 0.0)
    scale_uv: tuple[float, float] = (1.0, 1.0)
    pivot_uv: tuple[float, float] = (0.5, 0.5)


@dataclass
class StaticIndependentPart:
    source_submesh_index: int
    label: str = ""
    material_name: str = ""
    enabled: bool = True
    preview_only: bool = False
    clone_target_submesh_index: int = -1


@dataclass
class StaticOutputDrawSection:
    output_index: int
    target_submesh_index: int
    target_submesh_name: str
    source_submesh_indices: list[int] = field(default_factory=list)
    target_material_slot_index: int = 0
    clone_source_target_index: int = -1
    vertex_count: int = 0
    is_cloned_section: bool = False


@dataclass
class StaticMeshReplacementOptions:
    transform: StaticReplacementTransform = field(default_factory=StaticReplacementTransform)
    submesh_mappings: list[StaticSubmeshMapping] = field(default_factory=list)
    edited_source_mesh: ParsedMesh | None = None
    material_mapping_mode: str = "source_driven_materials"
    allow_merge_source_submeshes: bool = True
    allow_empty_target_submeshes: bool = True
    rebuild_material_sidecar: bool = False
    complete_external_swap: bool = False
    neutralize_inherited_material_layers: bool = False
    complete_external_material_reset: bool = False
    enable_missing_base_color_parameters: bool = False
    texture_slot_overrides: list[StaticTextureSlotOverride] = field(default_factory=list)
    texture_output_size_mode: str = "source"
    texture_uv_transforms: list[StaticTextureUvTransform] = field(default_factory=list)
    source_part_adjustments: list[StaticSourcePartAdjustment] = field(default_factory=list)
    original_part_copies: list[StaticOriginalPartCopy] = field(default_factory=list)
    global_transform_exempt_source_indices: list[int] = field(default_factory=list)
    independent_output_parts: list[StaticIndependentPart] = field(default_factory=list)
    additional_supplemental_files: list[object] = field(default_factory=list)
    custom_item_icon_override: object | None = None
    replace_lods: bool = False
    strict_static_only: bool = True
    source_material_texture_overrides: list[StaticSourceMaterialTextureOverride] = field(default_factory=list)
    donor_material_plans: list[StaticDonorMaterialPlan] = field(default_factory=list)
    dense_export_mode: str = "preserve_split"
    removed_target_submesh_indices: list[int] = field(default_factory=list)
    prune_removed_target_texture_parameters: bool = False
    prune_unmapped_original_texture_parameters: bool = False


@dataclass
class StaticMeshReplacementReport:
    original_submesh_count: int = 0
    replacement_submesh_count: int = 0
    original_vertex_count: int = 0
    replacement_vertex_count: int = 0
    original_face_count: int = 0
    replacement_face_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mapping_summary: list[str] = field(default_factory=list)
    alignment_summary: list[str] = field(default_factory=list)
    output_draw_sections: list[StaticOutputDrawSection] = field(default_factory=list)
    dense_summary: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


_PART_HINTS: dict[str, tuple[str, ...]] = {
    "acc": ("acc", "accessory", "accent", "ornament", "spike", "trim", "detail", "circular", "circulares"),
    "accessory": ("acc", "accessory", "accent", "ornament", "spike", "trim", "detail", "circular", "circulares"),
    "armor": ("armor", "armour", "plate", "mail", "body", "chest", "torso"),
    "blade": ("blade", "edge", "body", "sword", "spike", "tip", "main", "cuchilla", "hoja"),
    "body": ("body", "main", "base", "core", "shell", "torso", "mesh"),
    "cape": ("cape", "cloth", "fabric", "cloak", "mantle"),
    "cloth": ("cloth", "fabric", "cape", "cloak", "skirt", "sleeve"),
    "edge": ("blade", "edge", "rim", "border", "trim", "borde"),
    "guard": ("guard", "crossguard", "handguard", "protector", "soporte"),
    "handle": ("handle", "hilt", "grip", "pommel", "shaft", "mango", "empunadura"),
    "helmet": ("helmet", "helm", "head", "mask", "face"),
    "hilt": ("handle", "hilt", "grip", "pommel"),
    "metal": ("metal", "steel", "iron", "armor", "plate", "trim"),
    "plate": ("plate", "armor", "armour", "metal", "shell"),
    "trim": ("trim", "edge", "accent", "acc", "border", "ornament"),
}

_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "borde": ("edge", "trim"),
    "bordecuadrado": ("edge", "trim"),
    "circular": ("acc", "detail"),
    "circulares": ("acc", "detail"),
    "cuchilla": ("blade",),
    "dtcirculares": ("acc", "detail"),
    "empunadura": ("handle", "hilt", "grip"),
    "hoja": ("blade",),
    "mango": ("handle", "hilt", "grip"),
    "punta": ("tip", "edge"),
    "soporte": ("guard", "support"),
    "soporteespada": ("guard", "support"),
}

_TOKEN_STOP_WORDS = {
    "cd",
    "phm",
    "pc",
    "sword",
    "weapon",
    "onehandweapon",
    "twohandweapon",
    "low",
    "high",
    "mesh",
    "mat",
    "material",
    "object",
    "cube",
    "default",
}

_GRIP_MARKER_NAMES = ("cdmw_anchor", "cdmw_grip_anchor", "cft_anchor", "cft_grip_anchor")
_TIP_MARKER_NAMES = ("cdmw_tip_anchor", "cft_tip_anchor")
_MARKER_NAMES = {*_GRIP_MARKER_NAMES, *_TIP_MARKER_NAMES}


def _clone_submesh_fast(submesh: SubMesh) -> SubMesh:
    cloned = SubMesh(
        name=str(submesh.name or ""),
        material=str(submesh.material or ""),
        texture=str(submesh.texture or ""),
        vertices=list(submesh.vertices or []),
        uvs=list(submesh.uvs or []),
        normals=list(submesh.normals or []),
        faces=list(submesh.faces or []),
        bone_indices=list(submesh.bone_indices or []),
        bone_weights=list(submesh.bone_weights or []),
        source_vertex_map=list(submesh.source_vertex_map or []),
        vertex_count=int(submesh.vertex_count or 0),
        face_count=int(submesh.face_count or 0),
        source_vertex_offsets=list(submesh.source_vertex_offsets or []),
        source_index_offset=int(submesh.source_index_offset or -1),
        source_index_count=int(submesh.source_index_count or 0),
        source_vertex_stride=int(submesh.source_vertex_stride or 0),
        source_descriptor_offset=int(submesh.source_descriptor_offset or -1),
        source_bbox_min=tuple(submesh.source_bbox_min or (0.0, 0.0, 0.0)),
        source_bbox_extent=tuple(submesh.source_bbox_extent or (0.0, 0.0, 0.0)),
        source_lod_count=int(submesh.source_lod_count or 0),
    )
    for attr_name in (
        "texture_slots",
        "preview_color",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_sidecar_shader_family",
    ):
        if hasattr(submesh, attr_name):
            setattr(cloned, attr_name, getattr(submesh, attr_name))
    return cloned


def _clone_parsed_mesh_fast(mesh: ParsedMesh) -> ParsedMesh:
    return ParsedMesh(
        path=str(mesh.path or ""),
        format=str(mesh.format or ""),
        bbox_min=tuple(mesh.bbox_min or (0.0, 0.0, 0.0)),
        bbox_max=tuple(mesh.bbox_max or (0.0, 0.0, 0.0)),
        submeshes=[_clone_submesh_fast(submesh) for submesh in mesh.submeshes],
        lod_levels=[
            [_clone_submesh_fast(submesh) for submesh in lod_level]
            for lod_level in (mesh.lod_levels or [])
        ],
        total_vertices=int(mesh.total_vertices or 0),
        total_faces=int(mesh.total_faces or 0),
        has_uvs=bool(mesh.has_uvs),
        has_bones=bool(mesh.has_bones),
    )


def _replacement_mesh_from_options(
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions,
) -> ParsedMesh:
    edited = getattr(options, "edited_source_mesh", None)
    if isinstance(edited, ParsedMesh):
        return edited
    return replacement_mesh


def _independent_parts_for_options(
    options: StaticMeshReplacementOptions,
    replacement_mesh: ParsedMesh,
    *,
    include_preview_only: bool,
) -> list[StaticIndependentPart]:
    parts: list[StaticIndependentPart] = []
    seen: set[int] = set()
    for raw_part in getattr(options, "independent_output_parts", []) or []:
        if not bool(getattr(raw_part, "enabled", True)):
            continue
        if bool(getattr(raw_part, "preview_only", False)) and not include_preview_only:
            continue
        try:
            source_index = int(getattr(raw_part, "source_submesh_index"))
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
            continue
        if source_index in seen:
            continue
        submesh = replacement_mesh.submeshes[source_index]
        if _is_marker_submesh(submesh):
            continue
        seen.add(source_index)
        parts.append(
            StaticIndependentPart(
                source_submesh_index=source_index,
                label=str(getattr(raw_part, "label", "") or ""),
                material_name=str(getattr(raw_part, "material_name", "") or ""),
                enabled=True,
                preview_only=bool(getattr(raw_part, "preview_only", False)),
                clone_target_submesh_index=int(getattr(raw_part, "clone_target_submesh_index", -1) or -1),
            )
        )
    return parts


def _independent_source_indices(
    options: StaticMeshReplacementOptions,
    replacement_mesh: ParsedMesh,
    *,
    include_preview_only: bool,
) -> set[int]:
    return {
        int(part.source_submesh_index)
        for part in _independent_parts_for_options(
            options,
            replacement_mesh,
            include_preview_only=include_preview_only,
        )
    }


def _dense_export_mode(options: StaticMeshReplacementOptions) -> str:
    mode = str(getattr(options, "dense_export_mode", "preserve_split") or "preserve_split").strip().lower()
    return mode if mode in {"preserve_split", "legacy_merge"} else "preserve_split"


def _source_vertex_count(
    replacement_mesh: ParsedMesh,
    source_index: int,
    options: StaticMeshReplacementOptions,
) -> int:
    if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
        return 0
    source = replacement_mesh.submeshes[source_index]
    if _is_marker_submesh(source):
        return 0
    adjustment = _source_part_adjustments_by_index(options.source_part_adjustments).get(
        source_index,
        StaticSourcePartAdjustment(source_index),
    )
    if not bool(adjustment.enabled):
        return 0
    return len(getattr(source, "vertices", ()) or ())


def _partition_source_indices_for_vertex_limit(
    replacement_mesh: ParsedMesh,
    source_indices: Iterable[int],
    options: StaticMeshReplacementOptions,
) -> tuple[list[list[int]], list[str]]:
    groups: list[list[int]] = []
    errors: list[str] = []
    current_group: list[int] = []
    current_vertices = 0
    for raw_source_index in source_indices:
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        vertex_count = _source_vertex_count(replacement_mesh, source_index, options)
        if vertex_count <= 0:
            continue
        if vertex_count > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            errors.append(
                f"Replacement source {source_index} has {vertex_count:,} vertices; "
                f"16-bit PAC/PAM draw sections support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,}."
            )
            continue
        if current_group and current_vertices + vertex_count > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            groups.append(current_group)
            current_group = []
            current_vertices = 0
        current_group.append(source_index)
        current_vertices += vertex_count
    if current_group:
        groups.append(current_group)
    if not groups:
        groups.append([])
    return groups, errors


def plan_static_output_draw_sections(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions | None = None,
) -> tuple[list[StaticOutputDrawSection], list[str], list[str]]:
    """Plan export draw sections, preserving dense source parts when possible."""
    normalized_options = options or StaticMeshReplacementOptions()
    mode = _dense_export_mode(normalized_options)
    mappings_by_target = {mapping.target_submesh_index: mapping for mapping in mappings}
    original_sections: list[StaticOutputDrawSection] = []
    cloned_sections: list[StaticOutputDrawSection] = []
    warnings: list[str] = []
    errors: list[str] = []

    for target_index, target in enumerate(original_mesh.submeshes):
        mapping = mappings_by_target.get(target_index)
        source_indices = list(mapping.source_submesh_indices if mapping is not None else [])
        target_name = (
            str(getattr(mapping, "target_submesh_name", "") or "").strip()
            if mapping is not None
            else ""
        ) or target.material or target.name or f"target {target_index}"
        material_slot_index = (
            int(getattr(mapping, "target_material_slot_index", target_index) or target_index)
            if mapping is not None
            else target_index
        )

        if mode == "legacy_merge":
            groups = [source_indices]
            oversized_groups = [
                sum(_source_vertex_count(replacement_mesh, source_index, normalized_options) for source_index in source_indices)
            ]
            if oversized_groups[0] > _STATIC_REPLACEMENT_VERTEX_LIMIT:
                errors.append(
                    f"{target_name} receives {oversized_groups[0]:,} vertices; "
                    f"legacy merge mode exceeds the {_STATIC_REPLACEMENT_VERTEX_LIMIT:,}-vertex draw-section limit."
                )
        else:
            groups, group_errors = _partition_source_indices_for_vertex_limit(
                replacement_mesh,
                source_indices,
                normalized_options,
            )
            errors.extend(group_errors)

        first_group = groups[0] if groups else []
        original_sections.append(
            StaticOutputDrawSection(
                output_index=0,
                target_submesh_index=target_index,
                target_submesh_name=target_name,
                source_submesh_indices=list(first_group),
                target_material_slot_index=material_slot_index,
                clone_source_target_index=-1,
                vertex_count=sum(
                    _source_vertex_count(replacement_mesh, source_index, normalized_options)
                    for source_index in first_group
                ),
                is_cloned_section=False,
            )
        )
        for group in groups[1:]:
            cloned_sections.append(
                StaticOutputDrawSection(
                    output_index=0,
                    target_submesh_index=target_index,
                    target_submesh_name=target_name,
                    source_submesh_indices=list(group),
                    target_material_slot_index=material_slot_index,
                    clone_source_target_index=target_index,
                    vertex_count=sum(
                        _source_vertex_count(replacement_mesh, source_index, normalized_options)
                        for source_index in group
                    ),
                    is_cloned_section=True,
                )
            )

    planned = original_sections + cloned_sections
    for output_index, section in enumerate(planned):
        section.output_index = output_index
    if cloned_sections:
        warnings.append(
            "Dense replacement will preserve source parts by cloning PAC draw section(s): "
            f"{len(cloned_sections)} cloned section(s)."
        )
    return planned, warnings, errors


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

        rebuilt = _build_pac_full_rebuild(
            original_mesh,
            working_mesh,
            original_data,
            clone_descriptor_sources=[
                int(section.clone_source_target_index)
                for section in cloned_draw_sections
            ],
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


def suggest_static_submesh_mappings(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
) -> list[StaticSubmeshMapping]:
    """Suggest source-to-target draw-section mappings using metadata and geometry.

    The first pass is intentionally generic: exact names/materials, token overlap,
    broad part aliases, relative position, and size similarity. Weapon-specific
    words are only one hint family among armor, cloth, trim, accessory, body, etc.
    """
    render_source_indices = [
        index
        for index, submesh in enumerate(replacement_mesh.submeshes)
        if not _is_marker_submesh(submesh)
    ]
    if not original_mesh.submeshes or not render_source_indices:
        return []
    if len(original_mesh.submeshes) == 1:
        return [
            StaticSubmeshMapping(
                target_submesh_index=0,
                target_submesh_name=original_mesh.submeshes[0].material or original_mesh.submeshes[0].name,
                source_submesh_indices=render_source_indices,
                target_material_slot_index=0,
                merge_sources=True,
            )
        ]

    spatial_cache = _StaticMappingSpatialCache()
    assignments: dict[int, list[int]] = {index: [] for index in range(len(original_mesh.submeshes))}
    for source_index in render_source_indices:
        source = replacement_mesh.submeshes[source_index]
        best_target, best_score = _best_target_match_for_source(
            source,
            original_mesh.submeshes,
            source_mesh=replacement_mesh,
            target_mesh=original_mesh,
            spatial_cache=spatial_cache,
        )
        assignments.setdefault(best_target, []).append(source_index)
    confidence_by_target_source: dict[tuple[int, int], float] = {}
    for target_index, source_indices in assignments.items():
        if target_index < 0 or target_index >= len(original_mesh.submeshes):
            continue
        target = original_mesh.submeshes[target_index]
        for source_index in source_indices:
            if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
                continue
            confidence_by_target_source[(target_index, source_index)] = _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )

    for target_index, target in enumerate(original_mesh.submeshes):
        if assignments.get(target_index):
            continue
        donor_index = max(assignments, key=lambda index: len(assignments.get(index, ())))
        donor_sources = assignments.get(donor_index, [])
        if len(donor_sources) <= 1:
            continue
        stolen_source = max(
            donor_sources,
            key=lambda source_index: _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            ),
        )
        donor_sources.remove(stolen_source)
        assignments[target_index] = [stolen_source]
        confidence_by_target_source[(target_index, stolen_source)] = _token_score(
            _name_text(replacement_mesh.submeshes[stolen_source]),
            _name_text(target),
            source_submesh=replacement_mesh.submeshes[stolen_source],
            target_submesh=target,
            source_mesh=replacement_mesh,
            target_mesh=original_mesh,
            spatial_cache=spatial_cache,
        )

    _rebalance_duplicate_material_assignments(
        assignments,
        confidence_by_target_source,
        original_mesh,
        replacement_mesh,
        spatial_cache=spatial_cache,
    )

    mappings: list[StaticSubmeshMapping] = []
    used_sources: set[int] = set()
    for target_index, target in enumerate(original_mesh.submeshes):
        source_indices = assignments.get(target_index, [])
        used_sources.update(source_indices)
        mappings.append(
            StaticSubmeshMapping(
                target_submesh_index=target_index,
                target_submesh_name=target.material or target.name,
                source_submesh_indices=source_indices,
                target_material_slot_index=target_index,
                merge_sources=True,
                confidence_score=_mapping_confidence_score(target_index, source_indices, confidence_by_target_source),
                confidence_label=_confidence_label(
                    _mapping_confidence_score(target_index, source_indices, confidence_by_target_source)
                ),
            )
        )

    unassigned = [
        index
        for index in render_source_indices
        if index not in used_sources
    ]
    if unassigned:
        largest_target = max(
            range(len(original_mesh.submeshes)),
            key=lambda index: len(original_mesh.submeshes[index].faces),
        )
        mappings[largest_target].source_submesh_indices.extend(unassigned)
        scores = [
            _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(original_mesh.submeshes[largest_target]),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=original_mesh.submeshes[largest_target],
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )
            for source_index in unassigned
        ]
        if scores:
            mappings[largest_target].confidence_score = min(mappings[largest_target].confidence_score or scores[0], *scores)
            mappings[largest_target].confidence_label = _confidence_label(mappings[largest_target].confidence_score)
    return mappings


def _rebalance_duplicate_material_assignments(
    assignments: dict[int, list[int]],
    confidence_by_target_source: dict[tuple[int, int], float],
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    *,
    spatial_cache: "_StaticMappingSpatialCache | None" = None,
) -> None:
    targets_by_material: dict[str, list[int]] = {}
    for target_index, target in enumerate(original_mesh.submeshes):
        key = re.sub(r"[^a-z0-9]+", "", str(target.material or target.name or "").lower())
        if not key:
            continue
        targets_by_material.setdefault(key, []).append(target_index)

    for target_indices in targets_by_material.values():
        if len(target_indices) < 2:
            continue
        source_indices: list[int] = []
        seen_sources: set[int] = set()
        for target_index in target_indices:
            for source_index in assignments.get(target_index, []):
                if source_index not in seen_sources:
                    seen_sources.add(source_index)
                    source_indices.append(source_index)
        if len(source_indices) < 2:
            continue

        representative_target = original_mesh.submeshes[target_indices[0]]
        source_indices.sort(
            key=lambda source_index: _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(representative_target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=representative_target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            ),
            reverse=True,
        )

        for target_index in target_indices:
            assignments[target_index] = []
        for ordinal, source_index in enumerate(source_indices):
            target_index = target_indices[min(ordinal, len(target_indices) - 1)]
            assignments.setdefault(target_index, []).append(source_index)
            target = original_mesh.submeshes[target_index]
            confidence_by_target_source[(target_index, source_index)] = _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )


def _base_report(original_mesh: ParsedMesh, replacement_mesh: ParsedMesh) -> StaticMeshReplacementReport:
    return StaticMeshReplacementReport(
        original_submesh_count=len(original_mesh.submeshes),
        replacement_submesh_count=len(replacement_mesh.submeshes),
        original_vertex_count=sum(len(sm.vertices) for sm in original_mesh.submeshes),
        replacement_vertex_count=sum(len(sm.vertices) for sm in replacement_mesh.submeshes),
        original_face_count=sum(len(sm.faces) for sm in original_mesh.submeshes),
        replacement_face_count=sum(len(sm.faces) for sm in replacement_mesh.submeshes),
    )


def _replacement_mesh_with_original_part_copies(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    original_part_copies: list[StaticOriginalPartCopy] | None,
) -> tuple[ParsedMesh, set[int]]:
    copies = list(original_part_copies or [])
    if not copies:
        return replacement_mesh, set()

    effective_mesh = _clone_parsed_mesh_fast(replacement_mesh)
    preserve_source_indices: set[int] = set()
    for copy_request in copies:
        try:
            original_index = int(copy_request.original_submesh_index)
        except (TypeError, ValueError):
            continue
        if original_index < 0 or original_index >= len(original_mesh.submeshes):
            continue
        copied_submesh = _clone_submesh_fast(original_mesh.submeshes[original_index])
        original_label = copied_submesh.material or copied_submesh.name or f"original {original_index}"
        copy_label = str(copy_request.label or "").strip() or f"{original_label} (original copy)"
        copied_submesh.name = copy_label
        if not copied_submesh.material:
            copied_submesh.material = original_label
        effective_mesh.submeshes.append(copied_submesh)
        copied_source_index = len(effective_mesh.submeshes) - 1
        if copy_request.keep_original_placement:
            preserve_source_indices.add(copied_source_index)

    all_vertices = [vertex for submesh in effective_mesh.submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(all_vertices)
    effective_mesh.bbox_min = bbox_min
    effective_mesh.bbox_max = bbox_max
    effective_mesh.total_vertices = sum(len(submesh.vertices) for submesh in effective_mesh.submeshes)
    effective_mesh.total_faces = sum(len(submesh.faces) for submesh in effective_mesh.submeshes)
    effective_mesh.has_uvs = any(bool(submesh.uvs) for submesh in effective_mesh.submeshes)
    return effective_mesh, preserve_source_indices


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


def _build_mapped_replacement_mesh(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions,
    *,
    enforce_vertex_limit: bool = True,
    max_source_faces_per_submesh: int | None = None,
    output_draw_sections: list[StaticOutputDrawSection] | None = None,
) -> ParsedMesh:
    effective_replacement_mesh, preserve_source_indices = _replacement_mesh_with_original_part_copies(
        original_mesh,
        replacement_mesh,
        options.original_part_copies,
    )
    preserve_source_indices = set(preserve_source_indices)
    for index in getattr(options, "global_transform_exempt_source_indices", []) or []:
        try:
            source_index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(effective_replacement_mesh.submeshes):
            preserve_source_indices.add(source_index)
    adjustments_by_index = _source_part_adjustments_by_index(options.source_part_adjustments)
    mapped_enabled_source_indices: set[int] = set()
    for mapping in mappings:
        for source_index in mapping.source_submesh_indices:
            if (
                0 <= source_index < len(effective_replacement_mesh.submeshes)
                and not _is_marker_submesh(effective_replacement_mesh.submeshes[source_index])
                and adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index)).enabled
            ):
                mapped_enabled_source_indices.add(source_index)
    independent_parts = _independent_parts_for_options(
        options,
        effective_replacement_mesh,
        include_preview_only=not enforce_vertex_limit,
    )
    independent_source_indices = {int(part.source_submesh_index) for part in independent_parts}
    transformed_sources = _transformed_replacement_sources(
        original_mesh,
        effective_replacement_mesh,
        options.transform,
        options.source_part_adjustments,
        options.texture_uv_transforms,
        global_transform_exempt_indices=preserve_source_indices | independent_source_indices,
        global_transform_source_indices=mapped_enabled_source_indices,
        max_source_faces_per_submesh=max_source_faces_per_submesh,
        output_source_indices=mapped_enabled_source_indices | independent_source_indices,
    )
    mapped_submeshes: list[SubMesh] = []
    sections = list(output_draw_sections or [])
    if not sections:
        if enforce_vertex_limit:
            sections, _dense_warnings, dense_errors = plan_static_output_draw_sections(
                original_mesh,
                effective_replacement_mesh,
                mappings,
                options,
            )
            if dense_errors:
                raise ValueError("; ".join(dense_errors))
        else:
            mappings_by_target = {mapping.target_submesh_index: mapping for mapping in mappings}
            sections = [
                StaticOutputDrawSection(
                    output_index=target_index,
                    target_submesh_index=target_index,
                    target_submesh_name=target.material or target.name or f"target {target_index}",
                    source_submesh_indices=list(
                        mappings_by_target.get(
                            target_index,
                            StaticSubmeshMapping(target_index, target.material or target.name or "", [], target_index),
                        ).source_submesh_indices
                    ),
                    target_material_slot_index=target_index,
                )
                for target_index, target in enumerate(original_mesh.submeshes)
            ]
    for section in sections:
        target_index = int(section.target_submesh_index)
        if target_index < 0 or target_index >= len(original_mesh.submeshes):
            if enforce_vertex_limit:
                raise ValueError(f"Output draw section references invalid target submesh index {target_index}.")
            continue
        target = original_mesh.submeshes[target_index]
        source_parts = [
            _clone_submesh_fast(transformed_sources[source_index])
            for source_index in section.source_submesh_indices
            if (
                0 <= source_index < len(transformed_sources)
                and not _is_marker_submesh(transformed_sources[source_index])
                and adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index)).enabled
            )
        ]
        merged = _merge_source_submeshes(source_parts, target)
        section_label = str(section.target_submesh_name or "").strip()
        if section_label:
            merged.name = section_label
            if not merged.material:
                merged.material = section_label
        if enforce_vertex_limit and len(merged.vertices) > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            raise ValueError(
                f"Static replacement target {target_index} has {len(merged.vertices):,} vertices; "
                f"current serializers use 16-bit indices and support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,} vertices per draw section."
            )
        mapped_submeshes.append(merged)

    for independent_part in independent_parts:
        source_index = int(independent_part.source_submesh_index)
        if source_index < 0 or source_index >= len(transformed_sources):
            continue
        source_submesh = transformed_sources[source_index]
        if _is_marker_submesh(source_submesh):
            continue
        adjustment = adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index))
        if not bool(adjustment.enabled):
            continue
        independent_submesh = _clone_submesh_fast(source_submesh)
        label = str(independent_part.label or "").strip()
        material_name = str(independent_part.material_name or "").strip()
        if label:
            independent_submesh.name = label
        if material_name:
            independent_submesh.material = material_name
        elif not str(independent_submesh.material or "").strip():
            independent_submesh.material = independent_submesh.name or f"independent_{source_index}"
        if enforce_vertex_limit and len(independent_submesh.vertices) > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            raise ValueError(
                f"Independent replacement part {source_index} has {len(independent_submesh.vertices):,} vertices; "
                f"current serializers use 16-bit indices and support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,} vertices per draw section."
            )
        if not independent_submesh.normals or len(independent_submesh.normals) != len(independent_submesh.vertices):
            independent_submesh.normals = _compute_smooth_normals(independent_submesh.vertices, independent_submesh.faces)
        independent_submesh.vertex_count = len(independent_submesh.vertices)
        independent_submesh.face_count = len(independent_submesh.faces)
        mapped_submeshes.append(independent_submesh)

    all_vertices = [vertex for submesh in mapped_submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(all_vertices)
    return ParsedMesh(
        path=original_mesh.path,
        format=original_mesh.format,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=mapped_submeshes,
        total_vertices=sum(len(sm.vertices) for sm in mapped_submeshes),
        total_faces=sum(len(sm.faces) for sm in mapped_submeshes),
        has_uvs=any(sm.uvs for sm in mapped_submeshes),
        has_bones=False,
    )


def _transformed_replacement_sources(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    texture_uv_transforms: list[StaticTextureUvTransform] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    *,
    max_source_faces_per_submesh: int | None = None,
    output_source_indices: set[int] | None = None,
) -> list[SubMesh]:
    bound_indices = None if global_transform_source_indices is None else {int(index) for index in global_transform_source_indices}
    requested_output_indices = None if output_source_indices is None else {int(index) for index in output_source_indices}
    if requested_output_indices is None:
        indices_to_copy = set(range(len(replacement_mesh.submeshes)))
    else:
        indices_to_copy = set(requested_output_indices)
        if bound_indices is not None:
            indices_to_copy.update(bound_indices)
    sources: list[SubMesh] = []
    for source_index, submesh in enumerate(replacement_mesh.submeshes):
        if source_index in indices_to_copy:
            sources.append(_clone_submesh_fast(submesh))
            continue
        sources.append(
            SubMesh(
                name=str(getattr(submesh, "name", "") or ""),
                material=str(getattr(submesh, "material", "") or ""),
                texture=str(getattr(submesh, "texture", "") or ""),
            )
        )
    if not sources:
        return sources
    adjustments_by_index = _source_part_adjustments_by_index(source_part_adjustments or [])
    exempt_indices = set(global_transform_exempt_indices or set())

    # Manual source-part edits are fine-tuning controls. They should not change
    # the auto-alignment basis, and preview decimation should not change their
    # rotation/scale pivot. Compute both from the full source mesh before any
    # preview-only face sampling.
    alignment_bound_sources = [
        submesh
        for source_index, submesh in enumerate(sources)
        if source_index not in exempt_indices and (bound_indices is None or source_index in bound_indices)
    ] or sources
    alignment_replacement_mesh = copy.copy(replacement_mesh)
    alignment_replacement_mesh.submeshes = list(alignment_bound_sources)

    all_vertices = [vertex for submesh in alignment_bound_sources for vertex in submesh.vertices]
    src_min, src_max = _bbox(all_vertices)
    dst_min, dst_max = _bbox([vertex for submesh in original_mesh.submeshes for vertex in submesh.vertices])
    alignment = _compute_anchor_alignment(original_mesh, alignment_replacement_mesh, transform)
    adjustment_pivots = {
        source_index: _center(*_bbox(submesh.vertices))
        for source_index, submesh in enumerate(sources)
        if (
            source_index in adjustments_by_index
            and adjustments_by_index[source_index].enabled
            and not _is_marker_submesh(submesh)
            and bool(submesh.vertices)
        )
    }

    fit_scale_xyz = (1.0, 1.0, 1.0)
    fit_offset = (0.0, 0.0, 0.0)
    if transform.fit_to_original_bbox:
        src_dims = _dims(src_min, src_max)
        dst_dims = _dims(dst_min, dst_max)
        if transform.preserve_aspect_ratio:
            ratios = [
                dst_dims[index] / src_dims[index]
                for index in range(3)
                if src_dims[index] > 1e-8
            ]
            uniform = min(ratios) if ratios else 1.0
            fit_scale_xyz = (uniform, uniform, uniform)
        else:
            fit_scale_xyz = tuple(
                dst_dims[index] / src_dims[index] if src_dims[index] > 1e-8 else 1.0
                for index in range(3)
            )
        src_center = _center(src_min, src_max)
        dst_center = _center(dst_min, dst_max)
        fit_offset = tuple(dst_center[index] - src_center[index] * fit_scale_xyz[index] for index in range(3))

    max_preview_faces = _normalized_preview_face_limit(max_source_faces_per_submesh)
    if max_preview_faces > 0:
        sources = [_decimate_submesh_for_preview(submesh, max_preview_faces) for submesh in sources]

    uv_transforms_by_key = _texture_uv_transforms_by_key(texture_uv_transforms or [])
    if uv_transforms_by_key:
        for submesh in sources:
            uv_transform = _texture_uv_transform_for_submesh(submesh, uv_transforms_by_key)
            if uv_transform is not None:
                _apply_texture_uv_transform(submesh, uv_transform)

    for source_index, submesh in enumerate(sources):
        adjustment = adjustments_by_index.get(source_index)
        if adjustment is None or not adjustment.enabled or _is_marker_submesh(submesh):
            continue
        _apply_source_part_adjustment(submesh, adjustment, pivot=adjustment_pivots.get(source_index))

    for source_index, submesh in enumerate(sources):
        if source_index in exempt_indices:
            continue
        submesh.vertices = [
            _apply_transform(vertex, transform, fit_scale_xyz, fit_offset, alignment)
            for vertex in submesh.vertices
        ]
        if submesh.normals and len(submesh.normals) == len(submesh.vertices):
            submesh.normals = [
                _normalize(
                    _rotate_xyz(
                        _apply_alignment_roll(
                            _rotate_between(normal, alignment["source_axis"], alignment["target_axis"]),
                            alignment,
                        ),
                        transform.rotate_xyz_degrees,
                    )
                )
                for normal in submesh.normals
            ]
    return sources


def _texture_uv_transforms_by_key(
    transforms: list[StaticTextureUvTransform],
) -> dict[str, StaticTextureUvTransform]:
    by_key: dict[str, StaticTextureUvTransform] = {}
    for transform in transforms or []:
        material_name = str(getattr(transform, "source_material_name", "") or "").strip()
        if not material_name:
            continue
        by_key[material_name.lower()] = transform
    return by_key


def _texture_uv_transform_for_submesh(
    submesh: SubMesh,
    transforms_by_key: dict[str, StaticTextureUvTransform],
) -> StaticTextureUvTransform | None:
    for value in (submesh.material, submesh.name):
        key = str(value or "").strip().lower()
        if key and key in transforms_by_key:
            return transforms_by_key[key]
    return None


def _apply_texture_uv_transform(submesh: SubMesh, transform: StaticTextureUvTransform) -> None:
    if not submesh.uvs or len(submesh.uvs) != len(submesh.vertices):
        return
    pivot_u, pivot_v = _uv_pair(transform.pivot_uv, (0.5, 0.5))
    offset_u, offset_v = _uv_pair(transform.offset_uv, (0.0, 0.0))
    scale_u, scale_v = _uv_pair(transform.scale_uv, (1.0, 1.0))
    scale_u = scale_u if abs(scale_u) > 1e-8 else 1.0
    scale_v = scale_v if abs(scale_v) > 1e-8 else 1.0
    rotate_steps = int(round(float(getattr(transform, "rotate_degrees", 0) or 0) / 90.0)) % 4

    transformed: list[tuple[float, float]] = []
    for raw_u, raw_v in submesh.uvs:
        u = (float(raw_u) - pivot_u) * scale_u
        v = (float(raw_v) - pivot_v) * scale_v
        if bool(transform.flip_u):
            u = -u
        if bool(transform.flip_v):
            v = -v
        for _step in range(rotate_steps):
            u, v = -v, u
        transformed.append((u + pivot_u + offset_u, v + pivot_v + offset_v))
    submesh.uvs = transformed


def _uv_pair(value: tuple[float, float] | None, fallback: tuple[float, float]) -> tuple[float, float]:
    try:
        if value is None:
            return fallback
        return (float(value[0]), float(value[1]))
    except Exception:
        return fallback


def _source_part_adjustments_by_index(
    adjustments: list[StaticSourcePartAdjustment] | None,
) -> dict[int, StaticSourcePartAdjustment]:
    by_index: dict[int, StaticSourcePartAdjustment] = {}
    for adjustment in adjustments or []:
        try:
            source_index = int(adjustment.source_submesh_index)
        except Exception:
            continue
        if source_index >= 0:
            by_index[source_index] = adjustment
    return by_index


def _apply_source_part_adjustment(
    submesh: SubMesh,
    adjustment: StaticSourcePartAdjustment,
    *,
    pivot: tuple[float, float, float] | None = None,
) -> None:
    if not submesh.vertices:
        return
    pivot = pivot if pivot is not None else _center(*_bbox(submesh.vertices))
    sx, sy, sz = adjustment.scale_xyz or (1.0, 1.0, 1.0)
    uniform = float(adjustment.uniform_scale or 1.0)
    scale_xyz = (float(sx) * uniform, float(sy) * uniform, float(sz) * uniform)
    offset = tuple(float(value) for value in adjustment.offset_xyz)
    rotation = tuple(float(value) for value in adjustment.rotate_xyz_degrees)
    adjusted_vertices: list[tuple[float, float, float]] = []
    for vertex in submesh.vertices:
        local = (
            (float(vertex[0]) - pivot[0]) * scale_xyz[0],
            (float(vertex[1]) - pivot[1]) * scale_xyz[1],
            (float(vertex[2]) - pivot[2]) * scale_xyz[2],
        )
        rotated = _rotate_xyz(local, rotation)
        adjusted_vertices.append(
            (
                rotated[0] + pivot[0] + offset[0],
                rotated[1] + pivot[1] + offset[1],
                rotated[2] + pivot[2] + offset[2],
            )
        )
    submesh.vertices = adjusted_vertices
    if submesh.normals and len(submesh.normals) == len(submesh.vertices):
        submesh.normals = [_normalize(_rotate_xyz(normal, rotation)) for normal in submesh.normals]


def _merge_source_submeshes(submeshes: list[SubMesh], target: SubMesh) -> SubMesh:
    merged = SubMesh(
        name=target.name,
        material=target.material,
        texture=target.texture,
    )
    wants_uvs = any(len(submesh.uvs) == len(submesh.vertices) for submesh in submeshes)
    wants_normals = any(len(submesh.normals) == len(submesh.vertices) for submesh in submeshes)
    for submesh in submeshes:
        base = len(merged.vertices)
        merged.vertices.extend(list(submesh.vertices or []))
        if wants_uvs:
            merged.uvs.extend(
                list(submesh.uvs or [])
                if len(submesh.uvs) == len(submesh.vertices)
                else [(0.0, 0.0)] * len(submesh.vertices)
            )
        if wants_normals:
            merged.normals.extend(
                list(submesh.normals or [])
                if len(submesh.normals) == len(submesh.vertices)
                else [(0.0, 1.0, 0.0)] * len(submesh.vertices)
            )
        for face in submesh.faces:
            if len(face) == 3:
                merged.faces.append((face[0] + base, face[1] + base, face[2] + base))
    if not merged.normals or len(merged.normals) != len(merged.vertices):
        merged.normals = _compute_smooth_normals(merged.vertices, merged.faces)
    merged.vertex_count = len(merged.vertices)
    merged.face_count = len(merged.faces)
    return merged


def _normalized_preview_face_limit(value: int | None) -> int:
    try:
        limit = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, limit)


def _decimate_submesh_for_preview(submesh: SubMesh, max_faces: int) -> SubMesh:
    faces = list(submesh.faces or [])
    if max_faces <= 0 or len(faces) <= max_faces:
        return submesh
    if not submesh.vertices:
        return submesh

    step = max(1, math.ceil(len(faces) / float(max_faces)))
    sampled_faces = faces[::step][:max_faces]
    source_to_preview: dict[int, int] = {}
    preview_vertices: list[tuple[float, float, float]] = []
    preview_faces: list[tuple[int, int, int]] = []

    for face in sampled_faces:
        remapped_face: list[int] = []
        for raw_index in face[:3]:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError):
                remapped_face = []
                break
            if source_index < 0 or source_index >= len(submesh.vertices):
                remapped_face = []
                break
            preview_index = source_to_preview.get(source_index)
            if preview_index is None:
                preview_index = len(preview_vertices)
                source_to_preview[source_index] = preview_index
                preview_vertices.append(submesh.vertices[source_index])
            remapped_face.append(preview_index)
        if len(remapped_face) == 3:
            preview_faces.append((remapped_face[0], remapped_face[1], remapped_face[2]))

    if not preview_faces:
        return submesh

    ordered_source_indices = [
        source_index
        for source_index, _preview_index in sorted(source_to_preview.items(), key=lambda item: item[1])
    ]
    preview = _clone_submesh_fast(submesh)
    preview.vertices = preview_vertices
    preview.faces = preview_faces
    preview.uvs = (
        [submesh.uvs[source_index] for source_index in ordered_source_indices]
        if len(submesh.uvs) == len(submesh.vertices)
        else []
    )
    preview.normals = (
        [submesh.normals[source_index] for source_index in ordered_source_indices]
        if len(submesh.normals) == len(submesh.vertices)
        else []
    )
    preview.bone_indices = (
        [submesh.bone_indices[source_index] for source_index in ordered_source_indices]
        if len(submesh.bone_indices) == len(submesh.vertices)
        else []
    )
    preview.bone_weights = (
        [submesh.bone_weights[source_index] for source_index in ordered_source_indices]
        if len(submesh.bone_weights) == len(submesh.vertices)
        else []
    )
    preview.source_vertex_map = (
        [submesh.source_vertex_map[source_index] for source_index in ordered_source_indices]
        if len(submesh.source_vertex_map) == len(submesh.vertices)
        else []
    )
    preview.vertex_count = len(preview.vertices)
    preview.face_count = len(preview.faces)
    preview.source_vertex_offsets = []
    preview.source_index_offset = -1
    preview.source_index_count = len(preview.faces) * 3
    return preview


def _best_target_index_for_source(
    source: SubMesh,
    targets: list[SubMesh],
    *,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: "_StaticMappingSpatialCache | None" = None,
) -> int:
    best_index, _best_score = _best_target_match_for_source(
        source,
        targets,
        source_mesh=source_mesh,
        target_mesh=target_mesh,
        spatial_cache=spatial_cache,
    )
    return best_index


@dataclass
class _StaticMappingSpatialCache:
    mesh_bounds_by_id: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=dict)
    submesh_center_by_id: dict[tuple[int, int], tuple[float, float, float] | None] = field(default_factory=dict)


def _best_target_match_for_source(
    source: SubMesh,
    targets: list[SubMesh],
    *,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> tuple[int, float]:
    source_text = _name_text(source)
    best_index = 0
    best_score = float("-inf")
    for target_index, target in enumerate(targets):
        target_text = _name_text(target)
        score = _token_score(
            source_text,
            target_text,
            source_submesh=source,
            target_submesh=target,
            source_mesh=source_mesh,
            target_mesh=target_mesh,
            spatial_cache=spatial_cache,
        )
        if score > best_score:
            best_score = score
            best_index = target_index
    return best_index, best_score


def _mapping_confidence_score(
    target_index: int,
    source_indices: list[int],
    confidence_by_target_source: dict[tuple[int, int], float],
) -> float:
    scores = [
        confidence_by_target_source.get((target_index, source_index), 0.0)
        for source_index in source_indices
    ]
    return min(scores) if scores else 0.0


def _confidence_label(score: float) -> str:
    if score >= 18.0:
        return "high"
    if score >= 10.0:
        return "medium"
    return "low"


def _name_text(submesh: SubMesh) -> str:
    return f"{submesh.name} {submesh.material} {submesh.texture}".replace("_", " ").replace(".", " ").lower()


def _token_score(
    source_text: str,
    target_text: str,
    *,
    source_submesh: SubMesh | None = None,
    target_submesh: SubMesh | None = None,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> float:
    source_tokens = _semantic_tokens(source_text)
    target_tokens = _semantic_tokens(target_text)
    score = 0.0
    if source_text.strip() and target_text.strip() and source_text.strip() == target_text.strip():
        score += 80.0
    if source_submesh is not None and target_submesh is not None:
        if _normalized_label(source_submesh.name) and _normalized_label(source_submesh.name) == _normalized_label(target_submesh.name):
            score += 60.0
        if _normalized_label(source_submesh.material) and _normalized_label(source_submesh.material) == _normalized_label(target_submesh.material):
            score += 70.0
    overlap = source_tokens & target_tokens
    score += float(len(overlap) * 8)
    if overlap:
        score += min(10.0, sum(len(token) for token in overlap) * 0.5)
    for target_token in target_tokens:
        hints = _PART_HINTS.get(target_token, ())
        if hints and any(hint in source_tokens or hint in source_text for hint in hints):
            score += 9.0
    for source_token in source_tokens:
        hints = _PART_HINTS.get(source_token, ())
        if hints and any(hint in target_tokens or hint in target_text for hint in hints):
            score += 5.0
    if source_submesh is not None and target_submesh is not None:
        score += _submesh_size_similarity_score(source_submesh, target_submesh)
    if source_submesh is not None and target_submesh is not None and source_mesh is not None and target_mesh is not None:
        score += _submesh_spatial_similarity_score(
            source_submesh,
            source_mesh,
            target_submesh,
            target_mesh,
            spatial_cache=spatial_cache,
        )
    return score


def _normalized_label(value: str) -> str:
    return " ".join(_semantic_tokens(value))


def infer_static_replacement_part_role(text: str) -> str:
    """Return a compact, human-facing role hint for replacement routing tables."""
    tokens = _semantic_tokens(text)

    def has_any(*needles: str) -> bool:
        return any(needle in tokens for needle in needles)

    if has_any("hand", "glove", "gauntlet", "forearm", "arm"):
        return "hand/arm"
    if has_any("head", "face", "eye", "eyes", "mouth", "jaw"):
        return "head/face"
    if has_any("hair", "beard", "moustache", "mustache"):
        return "hair"
    if has_any("foot", "feet", "boot", "boots", "shoe", "shoes", "leg"):
        return "foot/leg"
    if has_any("nude", "body", "torso", "chest", "upperbody", "lowerbody", "upper", "lower", "ub", "lb"):
        return "body"
    if has_any("helmet", "helm", "mask"):
        return "helmet"
    if has_any("cloth", "cape", "fabric", "cloak", "mantle", "skirt", "sleeve"):
        return "cloth"
    if has_any("armor", "armour", "plate", "mail"):
        return "armor/body"
    if has_any("blade", "edge", "tip", "sword", "cuchilla", "hoja"):
        return "blade"
    if has_any("handle", "hilt", "grip", "pommel", "shaft", "mango", "empunadura"):
        return "handle"
    if has_any("guard", "crossguard", "handguard", "protector", "soporte"):
        return "guard"
    if has_any("acc", "accessory", "detail", "trim", "spike", "ornament", "accent", "horn"):
        return "accessory/detail"
    return "unknown"


def _semantic_tokens(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())
    tokens: set[str] = set()
    for raw_token in normalized.split():
        token = raw_token.strip()
        if not token or token in _TOKEN_STOP_WORDS or token.isdigit():
            continue
        token = re.sub(r"\d+$", "", token)
        if len(token) <= 1 or token in _TOKEN_STOP_WORDS:
            continue
        tokens.add(token)
        for alias, expanded_tokens in _TOKEN_ALIASES.items():
            if alias in token:
                tokens.update(expanded_tokens)
    return tokens


def _submesh_size_similarity_score(source: SubMesh, target: SubMesh) -> float:
    source_faces = max(1, len(source.faces) or source.face_count)
    target_faces = max(1, len(target.faces) or target.face_count)
    face_ratio = min(source_faces, target_faces) / max(source_faces, target_faces)
    source_vertices = max(1, len(source.vertices) or source.vertex_count)
    target_vertices = max(1, len(target.vertices) or target.vertex_count)
    vertex_ratio = min(source_vertices, target_vertices) / max(source_vertices, target_vertices)
    return (face_ratio * 3.0) + (vertex_ratio * 2.0)


def _submesh_spatial_similarity_score(
    source: SubMesh,
    source_mesh: ParsedMesh,
    target: SubMesh,
    target_mesh: ParsedMesh,
    *,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> float:
    source_center = _normalized_submesh_center(source, source_mesh, spatial_cache=spatial_cache)
    target_center = _normalized_submesh_center(target, target_mesh, spatial_cache=spatial_cache)
    if source_center is None or target_center is None:
        return 0.0
    distance = math.sqrt(sum((source_center[index] - target_center[index]) ** 2 for index in range(3)))
    return max(0.0, 8.0 - distance * 10.0)


def _normalized_submesh_center(
    submesh: SubMesh,
    mesh: ParsedMesh,
    *,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> tuple[float, float, float] | None:
    if not submesh.vertices:
        return None
    cache_key = (id(mesh), id(submesh))
    if spatial_cache is not None and cache_key in spatial_cache.submesh_center_by_id:
        return spatial_cache.submesh_center_by_id[cache_key]
    mesh_bounds_key = id(mesh)
    if spatial_cache is not None and mesh_bounds_key in spatial_cache.mesh_bounds_by_id:
        mesh_min, mesh_max = spatial_cache.mesh_bounds_by_id[mesh_bounds_key]
    else:
        mesh_vertices = [
            vertex
            for candidate in mesh.submeshes
            if not _is_marker_submesh(candidate)
            for vertex in candidate.vertices
        ]
        if not mesh_vertices:
            if spatial_cache is not None:
                spatial_cache.submesh_center_by_id[cache_key] = None
            return None
        mesh_min, mesh_max = _bbox(mesh_vertices)
        if spatial_cache is not None:
            spatial_cache.mesh_bounds_by_id[mesh_bounds_key] = (mesh_min, mesh_max)
    mesh_dims = _dims(mesh_min, mesh_max)
    submesh_min, submesh_max = _bbox(submesh.vertices)
    center = _center(submesh_min, submesh_max)
    normalized_center = tuple(
        0.5 if mesh_dims[index] <= 1e-8 else (center[index] - mesh_min[index]) / mesh_dims[index]
        for index in range(3)
    )
    if spatial_cache is not None:
        spatial_cache.submesh_center_by_id[cache_key] = normalized_center
    return normalized_center


def _dominant_axis(mesh: ParsedMesh) -> str:
    vertices = [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]
    if not vertices:
        return ""
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    axis_index = max(range(3), key=lambda index: dims[index])
    if dims[axis_index] <= 1e-8:
        return ""
    return ("x", "y", "z")[axis_index]


def _bbox(
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _dims(
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(max(0.0, bmax[index] - bmin[index]) for index in range(3))


def _center(
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple((bmin[index] + bmax[index]) * 0.5 for index in range(3))


def _apply_transform(
    vertex: tuple[float, float, float],
    transform: StaticReplacementTransform,
    fit_scale_xyz: tuple[float, float, float],
    fit_offset: tuple[float, float, float],
    alignment: dict[str, tuple[float, float, float] | float],
) -> tuple[float, float, float]:
    source_anchor = alignment["source_anchor"]
    target_anchor = alignment["target_anchor"]
    source_axis = alignment["source_axis"]
    target_axis = alignment["target_axis"]
    align_scale = float(alignment["scale"])
    centered = (
        vertex[0] - source_anchor[0],
        vertex[1] - source_anchor[1],
        vertex[2] - source_anchor[2],
    )
    x, y, z = _apply_alignment_roll(_rotate_between(centered, source_axis, target_axis), alignment)
    manual_scale = transform.scale_xyz or (transform.scale, transform.scale, transform.scale)
    x *= manual_scale[0] * align_scale * fit_scale_xyz[0]
    y *= manual_scale[1] * align_scale * fit_scale_xyz[1]
    z *= manual_scale[2] * align_scale * fit_scale_xyz[2]
    x, y, z = _rotate_xyz((x, y, z), transform.rotate_xyz_degrees)
    return (
        x + target_anchor[0] + fit_offset[0] + transform.offset_xyz[0] + transform.manual_adjustment[0],
        y + target_anchor[1] + fit_offset[1] + transform.offset_xyz[1] + transform.manual_adjustment[1],
        z + target_anchor[2] + fit_offset[2] + transform.offset_xyz[2] + transform.manual_adjustment[2],
    )


def _apply_alignment_roll(
    value: tuple[float, float, float],
    alignment: dict[str, tuple[float, float, float] | float],
) -> tuple[float, float, float]:
    roll_angle = float(alignment.get("roll_angle", 0.0) or 0.0)
    if abs(roll_angle) <= 1e-8:
        return value
    return _rotate_around_axis(value, alignment["target_axis"], roll_angle)


def _rotate_xyz(
    value: tuple[float, float, float],
    degrees: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = value
    rx, ry, rz = (math.radians(deg) for deg in degrees)
    if abs(rx) > 1e-8:
        cy, sy = math.cos(rx), math.sin(rx)
        y, z = y * cy - z * sy, y * sy + z * cy
    if abs(ry) > 1e-8:
        cx, sx = math.cos(ry), math.sin(ry)
        x, z = x * cx + z * sx, -x * sx + z * cx
    if abs(rz) > 1e-8:
        cz, sz = math.cos(rz), math.sin(rz)
        x, y = x * cz - y * sz, x * sz + y * cz
    return x, y, z


def _normalize(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _is_marker_submesh(submesh: SubMesh) -> bool:
    text = _name_text(submesh).replace(" ", "_")
    return any(marker in text for marker in _MARKER_NAMES)


def _find_marker_anchor(mesh: ParsedMesh, marker_name: str) -> tuple[float, float, float] | None:
    normalized_marker = marker_name.lower()
    for submesh in mesh.submeshes:
        text = _name_text(submesh).replace(" ", "_")
        if normalized_marker not in text or not submesh.vertices:
            continue
        return _centroid(submesh.vertices)
    return None


def _find_marker_anchor_any(mesh: ParsedMesh, marker_names: Iterable[str]) -> tuple[float, float, float] | None:
    for marker_name in marker_names:
        anchor = _find_marker_anchor(mesh, marker_name)
        if anchor is not None:
            return anchor
    return None


def _append_alignment_summary(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
) -> None:
    alignment = _compute_anchor_alignment(original_mesh, replacement_mesh, transform)
    report.alignment_summary.extend(
        [
            f"mode={transform.alignment_mode or 'manual'}",
            f"source_anchor={_format_vec(alignment['source_anchor'])}",
            f"target_anchor={_format_vec(alignment['target_anchor'])}",
            f"source_axis={_format_vec(alignment['source_axis'])}",
            f"target_axis={_format_vec(alignment['target_axis'])}",
            f"scale={float(alignment['scale']):.6g}",
            f"scale_to_original_length={transform.scale_to_original_length}",
            f"auto_roll_degrees={math.degrees(float(alignment.get('roll_angle', 0.0) or 0.0)):.5g}",
        ]
    )
    if transform.flip_source_axis or transform.flip_target_axis:
        report.alignment_summary.append(
            "axis_flip="
            + ", ".join(
                label
                for enabled, label in (
                    (transform.flip_source_axis, "source"),
                    (transform.flip_target_axis, "target"),
                )
                if enabled
            )
        )


def _compute_anchor_alignment(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
) -> dict[str, tuple[float, float, float] | float]:
    alignment_mode = str(transform.alignment_mode or "").strip().lower()
    if alignment_mode in {"manual", "none", "off"}:
        source_axis = transform.source_axis or (0.0, 0.0, 1.0)
        target_axis = transform.target_axis or source_axis
        return {
            "source_anchor": transform.source_anchor or (0.0, 0.0, 0.0),
            "target_anchor": transform.target_anchor or (0.0, 0.0, 0.0),
            "source_axis": _normalize(source_axis),
            "target_axis": _normalize(target_axis),
            "scale": 1.0,
            "roll_angle": 0.0,
        }
    if alignment_mode in {"auto_fit", "auto_fit_original", "preserve_original", "bbox_center", "center", "auto_flat_original", "flat_original", "grid_flat"}:
        source_anchor = transform.source_anchor or _mesh_center_anchor(replacement_mesh)
        target_anchor = transform.target_anchor or _mesh_center_anchor(original_mesh)
        source_axis = transform.source_axis or _axis_vector(_dominant_axis(replacement_mesh))
        target_axis = transform.target_axis or _axis_vector(_dominant_axis(original_mesh))
        if transform.flip_source_axis:
            source_axis = (-source_axis[0], -source_axis[1], -source_axis[2])
        if transform.flip_target_axis:
            target_axis = (-target_axis[0], -target_axis[1], -target_axis[2])
        source_length = _axis_length(replacement_mesh, source_axis)
        target_length = _axis_length(original_mesh, target_axis)
        scale = (
            target_length / source_length
            if transform.scale_to_original_length and source_length > 1e-8 and target_length > 1e-8
            else 1.0
        )
        source_axis_normalized = _normalize(source_axis)
        target_axis_normalized = _normalize(target_axis)
        return {
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "source_axis": source_axis_normalized,
            "target_axis": target_axis_normalized,
            "scale": scale,
            "roll_angle": _auto_roll_angle(
                replacement_mesh,
                original_mesh,
                source_axis_normalized,
                target_axis_normalized,
                prefer_flat_normal=alignment_mode in {"auto_flat_original", "flat_original", "grid_flat"},
                fallback_to_grid=alignment_mode in {"auto_flat_original", "grid_flat"},
                force_grid_flat=alignment_mode == "grid_flat",
            ),
        }

    source_anchor = transform.source_anchor or _find_marker_anchor_any(replacement_mesh, _GRIP_MARKER_NAMES) or _infer_grip_anchor(replacement_mesh)
    source_tip = _find_marker_anchor_any(replacement_mesh, _TIP_MARKER_NAMES)
    target_anchor = transform.target_anchor or _infer_grip_anchor(original_mesh)
    target_tip = _infer_tip_anchor(original_mesh)

    source_axis = transform.source_axis or (
        _normalize(_sub(source_tip, source_anchor)) if source_tip is not None else _axis_vector(_dominant_axis(replacement_mesh))
    )
    target_axis = transform.target_axis or (
        _normalize(_sub(target_tip, target_anchor)) if target_tip is not None else _axis_vector(_dominant_axis(original_mesh))
    )
    source_length = _axis_length(replacement_mesh, source_axis)
    target_length = _axis_length(original_mesh, target_axis)
    scale = (
        target_length / source_length
        if transform.scale_to_original_length and source_length > 1e-8 and target_length > 1e-8
        else 1.0
    )
    if transform.flip_source_axis:
        source_axis = (-source_axis[0], -source_axis[1], -source_axis[2])
    if transform.flip_target_axis:
        target_axis = (-target_axis[0], -target_axis[1], -target_axis[2])
    source_axis_normalized = _normalize(source_axis)
    target_axis_normalized = _normalize(target_axis)
    return {
        "source_anchor": source_anchor,
        "target_anchor": target_anchor,
        "source_axis": source_axis_normalized,
        "target_axis": target_axis_normalized,
        "scale": scale,
        "roll_angle": _auto_roll_angle(replacement_mesh, original_mesh, source_axis_normalized, target_axis_normalized),
    }


def _auto_roll_angle(
    replacement_mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    source_axis: tuple[float, float, float],
    target_axis: tuple[float, float, float],
    *,
    prefer_flat_normal: bool = False,
    fallback_to_grid: bool = False,
    force_grid_flat: bool = False,
) -> float:
    if prefer_flat_normal:
        source_flat_normal = _axis_aligned_flat_normal_vector(replacement_mesh, source_axis)
        if source_flat_normal is None:
            source_flat_normal = _flat_normal_axis_vector(replacement_mesh, source_axis)
        target_flat_normal = None if force_grid_flat else _flat_normal_axis_vector(original_mesh, target_axis)
        if target_flat_normal is None and (fallback_to_grid or force_grid_flat):
            target_flat_normal = _grid_flat_normal_for_axis(target_axis)
        if source_flat_normal is not None and target_flat_normal is not None:
            rotated_source_flat_normal = _rotate_between(source_flat_normal, source_axis, target_axis)
            return _signed_angle_around_axis(rotated_source_flat_normal, target_flat_normal, target_axis)
    source_secondary = _secondary_axis_vector(replacement_mesh, source_axis)
    target_secondary = _secondary_axis_vector(original_mesh, target_axis)
    rotated_source_secondary = _rotate_between(source_secondary, source_axis, target_axis)
    return _signed_angle_around_axis(rotated_source_secondary, target_secondary, target_axis)


def _renderable_mesh_vertices(mesh: ParsedMesh) -> list[tuple[float, float, float]]:
    return [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]


def _axis_aligned_secondary_axis_vector(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    if not vertices:
        return (0.0, 1.0, 0.0)
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    primary_index = max(range(3), key=lambda index: abs(primary_axis[index]))
    candidates = [index for index in range(3) if index != primary_index]
    secondary_index = max(candidates, key=lambda index: dims[index]) if candidates else 1
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[secondary_index]


def _canonical_axis_sign(axis: tuple[float, float, float]) -> tuple[float, float, float]:
    dominant_index = max(range(3), key=lambda index: abs(axis[index]))
    if axis[dominant_index] < 0.0:
        return (-axis[0], -axis[1], -axis[2])
    return axis


def _projected_principal_plane_axes(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if len(vertices) < 3:
        return None
    primary = _normalize(primary_axis)
    if _dot(primary, primary) <= 1e-12:
        return None
    reference = (0.0, 0.0, 1.0) if abs(primary[2]) < 0.82 else (1.0, 0.0, 0.0)
    u = _normalize(_cross(primary, reference))
    if _dot(u, u) <= 1e-12:
        return None
    v = _normalize(_cross(primary, u))
    center = _centroid(vertices)
    covariance_uu = 0.0
    covariance_uv = 0.0
    covariance_vv = 0.0
    for vertex in vertices:
        centered = _sub(vertex, center)
        projected_u = _dot(centered, u)
        projected_v = _dot(centered, v)
        covariance_uu += projected_u * projected_u
        covariance_uv += projected_u * projected_v
        covariance_vv += projected_v * projected_v
    count = float(max(1, len(vertices)))
    covariance_uu /= count
    covariance_uv /= count
    covariance_vv /= count
    trace = covariance_uu + covariance_vv
    if trace <= 1e-12:
        return None
    delta = math.sqrt(((covariance_uu - covariance_vv) * 0.5) ** 2 + covariance_uv * covariance_uv)
    major = (trace * 0.5) + delta
    minor = max(0.0, (trace * 0.5) - delta)
    if major <= 1e-12 or (major - minor) / major < 0.08:
        return None
    angle = 0.5 * math.atan2(2.0 * covariance_uv, covariance_uu - covariance_vv)
    secondary = _normalize(
        (
            (u[0] * math.cos(angle)) + (v[0] * math.sin(angle)),
            (u[1] * math.cos(angle)) + (v[1] * math.sin(angle)),
            (u[2] * math.cos(angle)) + (v[2] * math.sin(angle)),
        )
    )
    if _dot(secondary, secondary) <= 1e-12:
        return None
    flat_normal = _normalize(_cross(primary, secondary))
    if _dot(flat_normal, flat_normal) <= 1e-12:
        return None
    return _canonical_axis_sign(secondary), _canonical_axis_sign(flat_normal)


def _projected_principal_secondary_axis(
    vertices: list[tuple[float, float, float]],
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    axes = _projected_principal_plane_axes(vertices, primary_axis)
    return axes[0] if axes is not None else None


def _flat_normal_axis_vector(
    mesh: ParsedMesh,
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return None
    axes = _projected_principal_plane_axes(vertices, primary_axis)
    return axes[1] if axes is not None else None


def _axis_aligned_flat_normal_vector(
    mesh: ParsedMesh,
    primary_axis: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return None
    bmin, bmax = _bbox(vertices)
    dims = _dims(bmin, bmax)
    primary_index = max(range(3), key=lambda index: abs(primary_axis[index]))
    candidates = [index for index in range(3) if index != primary_index]
    if not candidates:
        return None
    thin_index = min(candidates, key=lambda index: dims[index])
    wide_index = max(candidates, key=lambda index: dims[index])
    if dims[wide_index] <= 1e-8:
        return None
    if dims[thin_index] > dims[wide_index] * 0.9:
        return None
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[thin_index]


def _grid_flat_normal_for_axis(primary_axis: tuple[float, float, float]) -> tuple[float, float, float]:
    primary = _normalize(primary_axis)
    grid_normal = (0.0, 1.0, 0.0)
    if abs(_dot(primary, grid_normal)) < 0.85:
        return grid_normal
    return (0.0, 0.0, 1.0)


def _secondary_axis_vector(mesh: ParsedMesh, primary_axis: tuple[float, float, float]) -> tuple[float, float, float]:
    vertices = _renderable_mesh_vertices(mesh)
    if not vertices:
        return (0.0, 1.0, 0.0)
    projected_secondary = _projected_principal_secondary_axis(vertices, primary_axis)
    if projected_secondary is not None:
        return projected_secondary
    return _axis_aligned_secondary_axis_vector(vertices, primary_axis)


def _signed_angle_around_axis(
    source: tuple[float, float, float],
    target: tuple[float, float, float],
    axis: tuple[float, float, float],
) -> float:
    normalized_axis = _normalize(axis)
    source_projected = _normalize(_sub(source, _mul(normalized_axis, _dot(source, normalized_axis))))
    target_projected = _normalize(_sub(target, _mul(normalized_axis, _dot(target, normalized_axis))))
    cross = _cross(source_projected, target_projected)
    sin_theta = _dot(normalized_axis, cross)
    cos_theta = max(-1.0, min(1.0, _dot(source_projected, target_projected)))
    return math.atan2(sin_theta, cos_theta)


def _mesh_center_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [
        vertex
        for submesh in mesh.submeshes
        if not _is_marker_submesh(submesh)
        for vertex in submesh.vertices
    ]
    if not vertices:
        return (0.0, 0.0, 0.0)
    return _center(*_bbox(vertices))


def _infer_grip_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    handle = _find_named_part(mesh, ("handle", "hilt", "grip"))
    submeshes = [handle] if handle is not None else [sm for sm in mesh.submeshes if not _is_marker_submesh(sm)]
    vertices = [vertex for submesh in submeshes for vertex in submesh.vertices]
    if not vertices:
        return (0.0, 0.0, 0.0)
    axis = _axis_vector(_dominant_axis(_mesh_from_submeshes(mesh, submeshes)))
    return _axis_extreme_point(vertices, axis, minimum=True)


def _infer_tip_anchor(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [vertex for submesh in mesh.submeshes if not _is_marker_submesh(submesh) for vertex in submesh.vertices]
    if not vertices:
        return (0.0, 0.0, 1.0)
    axis = _axis_vector(_dominant_axis(mesh))
    return _axis_extreme_point(vertices, axis, minimum=False)


def _find_named_part(mesh: ParsedMesh, tokens: tuple[str, ...]) -> SubMesh | None:
    for submesh in mesh.submeshes:
        text = _name_text(submesh)
        if any(token in text for token in tokens):
            return submesh
    return None


def _mesh_from_submeshes(source: ParsedMesh, submeshes: list[SubMesh]) -> ParsedMesh:
    clone = ParsedMesh(path=source.path, format=source.format, submeshes=submeshes)
    return clone


def _axis_vector(axis_name: str) -> tuple[float, float, float]:
    return {
        "x": (1.0, 0.0, 0.0),
        "y": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, 1.0),
    }.get(str(axis_name or "").lower(), (0.0, 0.0, 1.0))


def _axis_extreme_point(
    vertices: list[tuple[float, float, float]],
    axis: tuple[float, float, float],
    *,
    minimum: bool,
) -> tuple[float, float, float]:
    normalized_axis = _normalize(axis)
    return min(vertices, key=lambda vertex: _dot(vertex, normalized_axis)) if minimum else max(vertices, key=lambda vertex: _dot(vertex, normalized_axis))


def _axis_length(mesh: ParsedMesh, axis: tuple[float, float, float]) -> float:
    vertices = [vertex for submesh in mesh.submeshes if not _is_marker_submesh(submesh) for vertex in submesh.vertices]
    if not vertices:
        return 1.0
    normalized_axis = _normalize(axis)
    values = [_dot(vertex, normalized_axis) for vertex in vertices]
    return max(values) - min(values)


def _rotate_between(
    value: tuple[float, float, float],
    source_axis: tuple[float, float, float],
    target_axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    a = _normalize(source_axis)
    b = _normalize(target_axis)
    cos_theta = max(-1.0, min(1.0, _dot(a, b)))
    if cos_theta > 0.999999:
        return value
    if cos_theta < -0.999999:
        fallback = _normalize((1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0))
        axis = _normalize(_cross(a, fallback))
    else:
        axis = _normalize(_cross(a, b))
    angle = math.acos(cos_theta)
    return _rotate_around_axis(value, axis, angle)


def _rotate_around_axis(
    value: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float]:
    ux, uy, uz = _normalize(axis)
    x, y, z = value
    c = math.cos(angle)
    s = math.sin(angle)
    dot = ux * x + uy * y + uz * z
    return (
        x * c + (uy * z - uz * y) * s + ux * dot * (1.0 - c),
        y * c + (uz * x - ux * z) * s + uy * dot * (1.0 - c),
        z * c + (ux * y - uy * x) * s + uz * dot * (1.0 - c),
    )


def _centroid(vertices: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not vertices:
        return (0.0, 0.0, 0.0)
    return (
        sum(vertex[0] for vertex in vertices) / len(vertices),
        sum(vertex[1] for vertex in vertices) / len(vertices),
        sum(vertex[2] for vertex in vertices) / len(vertices),
    )


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: tuple[float, float, float], scalar: float) -> tuple[float, float, float]:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _format_vec(value: tuple[float, float, float]) -> str:
    return f"({value[0]:.5g}, {value[1]:.5g}, {value[2]:.5g})"


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
