"""Static mesh replacement option and report dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field

from .mesh_parser import ParsedMesh

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
    material_role: str = ""
    emissive_color_rgb: tuple[int, int, int] = ()


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
class StaticMaterialAtlasRect:
    source_material_name: str
    source_submesh_indices: tuple[int, ...] = ()
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0


@dataclass
class StaticOutputDrawSection:
    output_index: int
    target_submesh_index: int
    target_submesh_name: str
    source_submesh_indices: list[int] = field(default_factory=list)
    target_material_slot_index: int = 0
    clone_source_target_index: int = -1
    donor_material_name: str = ""
    vertex_count: int = 0
    is_cloned_section: bool = False
    runtime_slot_name: str = ""
    runtime_material_name: str = ""
    source_material_name: str = ""
    lod_strategy: str = ""
    section0_preserved: bool = False
    companion_paths: tuple[str, ...] = ()
    atlas_source_material_names: tuple[str, ...] = ()
    atlas_rects: tuple[StaticMaterialAtlasRect, ...] = ()
    atlas_padding: int = 8
    atlas_size: tuple[int, int] = (0, 0)
    atlas_material_name: str = ""


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
    full_import_model_replacement: bool = False
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
    source_owned_target_names: list[str] = field(default_factory=list)
    dense_export_mode: str = "preserve_split"
    complete_swap_atlas_mode: str = "auto_when_needed"
    complete_swap_material_profile: str = "source_graph_strict"
    global_gloss_reduction: float = 0.0
    edge_relief_strength: float = 0.0
    edge_relief_source: str = "hybrid"
    accent_glow_strength: float = 0.0
    auto_brightness_balance: float = 50.0
    dark_detail_lift: float = 0.0
    tone_contrast: float = 0.0
    allow_unsafe_material_preflight_export: bool = False
    removed_target_submesh_indices: list[int] = field(default_factory=list)
    prune_removed_target_texture_parameters: bool = False
    prune_unmapped_original_texture_parameters: bool = False
    pac_xml_corpus_root: str = ""
    pac_xml_profile_cache_path: str = ""


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
