"""Texture and material-sidecar planning for static mesh replacement."""

from __future__ import annotations

import re
import shutil
import tempfile
import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from cdmw.domain.textures.material_authority import (
    material_profile_authority_contract,
    material_profile_is_runtime_xml,
    material_profile_mask_binding_mode,
    material_profile_support_policy,
)
from .asset_replacement import classify_texture_binding, infer_cd_texture_role_from_path
from .mesh_parser import ParsedMesh
from .pac_xml_profiles import (
    PacXmlCorpusIndex,
    PacXmlProfileReport,
    PacXmlTemplateMatch,
    PacXmlWrapperProfile,
    build_pac_xml_profile_match_report,
    load_or_build_pac_xml_corpus_index,
    pac_xml_parameter_for_slot,
    parse_pac_xml_profile,
    select_best_pac_xml_template,
)
from .static_mesh_replacer import StaticOutputDrawSection, StaticSubmeshMapping, _semantic_tokens


from .material_profiles import (
    MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_NAME,
    _MANUAL_COMPLETE_SWAP_MATERIAL_PROFILE_PREFIX,
    CDMaterialRuntimeProfile,
    _MANUAL_PROFILE_FIELD_NAMES,
    _material_authority_clean_source_profile,
    _material_authority_runtime_xml_profile,
    _material_authority_true_source_profile,
    _material_authority_pbr_source_test_profile,
    _material_authority_detail_mask_profile,
    _material_authority_placeholder_safe_test_profile,
    _material_authority_manual_default_profile,
    _manual_profile_payload,
    serialize_complete_swap_manual_material_profile,
    _coerce_optional_float,
    _coerce_optional_byte,
    _manual_material_profile_from_payload,
    CDMaterialProbeVariant,
    CDMaterialProbePackageResult,
    SourceMaterialRoutingResult,
    TextureAssignmentGuidance,
    _HELPER_MATERIAL_SUFFIXES,
    complete_swap_material_runtime_profiles,
    get_complete_swap_material_profile,
    normalize_global_gloss_reduction,
    normalize_basic_control_percent,
    normalize_signed_basic_control_percent,
    normalize_tone_contrast,
    normalize_edge_relief_source,
    _profile_uses_cd_smoothness_mask_response,
    _profile_global_gloss_reduction,
    _profile_accent_glow_strength,
    _profile_accent_glow_intensity,
    _profile_requires_accent_glow_for_source_emissive,
    _profile_source_emissive_enabled,
    _profile_source_emissive_parameter_intensity,
    _profile_gloss_reduction_mode,
    _blend_byte_value,
    _blend_float_value,
    apply_global_gloss_reduction_to_profile,
    apply_true_source_basic_controls_to_profile,
    complete_swap_material_profile_to_dict,
    write_complete_swap_calibrated_material_profile,
    read_complete_swap_calibrated_material_profile,
    complete_swap_material_probe_variants,
    complete_swap_material_probe_manifest,
    write_complete_swap_material_probe_manifests,
    _hash_bytes,
    _hash_file,
    _probe_payload_items,
    write_complete_swap_material_probe_packages,
    _profile_base_binding_mode,
    _profile_mask_binding_mode,
    _profile_support_policy,
    _profile_is_source_only,
    _profile_is_material_authority_bruteforce,
    _profile_authority_contract,
    complete_swap_material_authority_contract,
    complete_swap_material_allows_inherited_layer_color_bindings,
    complete_swap_material_requires_true_source_authority,
    _profile_is_runtime_xml,
    _profile_allows_factor_only_authority,
    _profile_bruteforce_texture_scope,
    _profile_forces_neutral_layer_support,
    _profile_uses_factor_only_material_mask,
    _profile_preserves_target_layer_response,
    _profile_applies_source_pbr_scalars_with_preserved_layers,
    _profile_uses_detail_mask_material_contract,
    _profile_routes_source_color_to_layer_slots,
    _profile_neutral_color_rgb,
    _profile_base_color_lift,
    _profile_base_color_gamma,
    _profile_base_color_saturation,
    _profile_optional_byte,
    _profile_optional_scale,
    _profile_displacement_scale_multiplier,
    _profile_displacement_scale_max,
    _profile_roughness_inverted,
    _profile_metallic_inverted,
    _profile_ma_rgb_roles,
    _format_profile_color_hex,
)
_SOURCE_TEXTURE_IMAGE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(slots=True)
class ReplacementTextureSlot:
    material_name: str
    slot_kind: str
    source_path: Path
    normal_space: str = ""
    semantic_subtype: str = ""
    packed_channels: tuple[str, ...] = ()
    source_authority: str = ""
    base_color_factor: tuple[float, float, float] = ()
    base_alpha_factor: Optional[float] = None
    base_color_scale: float = 1.0
    base_color_lift: int = 0
    base_color_gamma: float = 1.0
    base_color_saturation: float = 1.0
    base_color_value_max: int = 255
    base_color_auto_balance: int = 0
    base_color_shadow_lift: int = 0
    base_color_tone_contrast: float = 0.0


@dataclass(slots=True)
class ReplacementTextureSet:
    material_name: str
    slots: dict[str, ReplacementTextureSlot] = field(default_factory=dict)
    source_face_count: int = 0
    roughness_factor: Optional[float] = None
    metallic_factor: Optional[float] = None
    specular_factor: Optional[float] = None
    glossiness_factor: Optional[float] = None
    occlusion_strength: Optional[float] = None
    base_color_factor: Optional[tuple[float, float, float]] = None
    source_role_tags: tuple[str, ...] = ()
    accent_glow_color_rgb: tuple[float, float, float] = ()
    emissive_strength: Optional[float] = None


_SPECULAR_GLOSSINESS_SUBTYPES = {"specular_glossiness", "specularglossiness", "specular_gloss", "specgloss"}
_METALLIC_ROUGHNESS_SUBTYPES = {"metallic_roughness", "metallicroughness"}


def replacement_texture_slot_preview_semantics(
    source_slot: Optional[ReplacementTextureSlot],
    *,
    source_path: Optional[Path] = None,
) -> tuple[str, str, tuple[str, ...], str]:
    """Return native-preview semantics declared by source material metadata or filename."""

    subtype = _sanitize_texture_component(str(getattr(source_slot, "semantic_subtype", "") or ""))
    channels = tuple(
        _sanitize_texture_component(channel)
        for channel in tuple(getattr(source_slot, "packed_channels", ()) or ())
        if _sanitize_texture_component(channel)
    )
    channel_set = set(channels)
    path = source_path if source_path is not None else getattr(source_slot, "source_path", None)
    normalized_stem = ""
    if isinstance(path, Path):
        normalized_stem = re.sub(r"[^a-z0-9]+", "", str(path.stem or "").lower())
    if (
        subtype in _SPECULAR_GLOSSINESS_SUBTYPES
        or {"specular", "glossiness"} <= channel_set
        or any(token in normalized_stem for token in ("specularglossiness", "specgloss"))
    ):
        return "specular", "specular_glossiness", ("specular", "glossiness"), "_specularGlossinessTexture"
    if (
        subtype in _METALLIC_ROUGHNESS_SUBTYPES
        or {"roughness", "metallic"} <= channel_set
        or any(
            token in normalized_stem
            for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic")
        )
    ):
        return "material", "metallic_roughness", ("roughness", "metallic"), "_metallicRoughnessTexture"
    return "", "", (), ""


@dataclass(slots=True)
class TextureSlotMapping:
    target_material_name: str
    target_texture_path: str
    slot_kind: str
    source_material_name: str
    source_path: Path
    output_texture_path: str
    normal_space: str = ""


@dataclass(slots=True)
class SidecarTextureParameterInjection:
    target_material_name: str
    parameter_name: str
    texture_path: str
    anchor_texture_paths: tuple[str, ...] = ()


@dataclass(slots=True)
class SidecarTextureParameterRename:
    target_material_name: str
    texture_path: str
    old_parameter_name: str
    new_parameter_name: str


@dataclass(slots=True)
class SidecarMaterialWrapperClone:
    target_material_name: str
    donor_material_name: str


@dataclass(slots=True)
class SidecarPatchPlan:
    sidecar_path: str
    texture_path_replacements: dict[str, str] = field(default_factory=dict)
    texture_parameter_injections: list[SidecarTextureParameterInjection] = field(default_factory=list)
    texture_parameter_renames: list[SidecarTextureParameterRename] = field(default_factory=list)
    material_wrapper_clones: list[SidecarMaterialWrapperClone] = field(default_factory=list)
    texture_parameter_keep_rules: list[tuple[str, str]] = field(default_factory=list)
    prune_unmapped_texture_parameters: bool = False
    prune_material_names: list[str] = field(default_factory=list)
    neutralize_inherited_material_layers: bool = False
    complete_external_material_reset: bool = False
    neutralize_material_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SidecarPatchReport:
    sidecar_path: str = ""
    replaced_count: int = 0
    unchanged_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureReplacementPayload:
    target_path: str
    payload_data: bytes
    kind: str
    source_path: Path
    note: str = ""


@dataclass(slots=True)
class TextureReplacementReport:
    texture_sets: list[ReplacementTextureSet] = field(default_factory=list)
    material_routes: list["SourceMaterialRoutingResult"] = field(default_factory=list)
    slot_mappings: list[TextureSlotMapping] = field(default_factory=list)
    sidecar_reports: list[SidecarPatchReport] = field(default_factory=list)
    generated_payloads: list[TextureReplacementPayload] = field(default_factory=list)
    material_profile_name: str = ""
    material_probe_variants: list["CDMaterialProbeVariant"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_static_replacement_helper_material_name(material_name: str) -> bool:
    """Return true for technical material wrappers that should stay manual.

    Helmet sidecars often contain helper wrappers such as ``*_black`` and
    ``*_inside`` for interior/occlusion shader behavior.  They should not
    receive broad source texture routing just because the replacement only has
    one material set.
    """

    normalized = _sanitize_texture_component(material_name)
    if not normalized:
        return False
    if not normalized.startswith(("cd_", "pew_", "pe_", "npc_", "monster_", "vehicle_")):
        return False
    parts = tuple(part for part in normalized.split("_") if part)
    if not parts:
        return False
    if parts[-1] in _HELPER_MATERIAL_SUFFIXES:
        return True
    return "inside" in parts





def patch_material_sidecar_text(
    original_text: str,
    sidecar_patch_plan: SidecarPatchPlan,
) -> tuple[str, SidecarPatchReport]:
    """Clone-patch sidecar text by replacing paths and optional compatible texture parameters."""
    patched = str(original_text or "")
    report = SidecarPatchReport(sidecar_path=sidecar_patch_plan.sidecar_path)
    patched = _apply_sidecar_material_wrapper_clones(
        patched,
        sidecar_patch_plan.material_wrapper_clones,
        report,
    )
    for old_path, new_path in sidecar_patch_plan.texture_path_replacements.items():
        old_value = str(old_path or "").strip()
        new_value = str(new_path or "").strip()
        if not old_value or not new_value:
            continue
        if old_value == new_value:
            if old_value in patched:
                report.unchanged_count += 1
            continue
        replacement_variants = []
        slashless_old = old_value.replace("\\", "/").lstrip("/")
        if slashless_old:
            leading_slash_old = "/" + slashless_old
            if leading_slash_old not in replacement_variants:
                replacement_variants.append(leading_slash_old)
        replacement_variants.append(old_value)
        if slashless_old and slashless_old != old_value and slashless_old not in replacement_variants:
            replacement_variants.append(slashless_old)
        replaced_any = False
        for candidate_old in replacement_variants:
            occurrences = patched.count(candidate_old)
            if occurrences <= 0:
                continue
            patched = patched.replace(candidate_old, new_value)
            report.replaced_count += occurrences
            replaced_any = True
        if not replaced_any:
            report.warnings.append(f"Sidecar did not contain texture path: {old_value}")
            continue
    for injection in sidecar_patch_plan.texture_parameter_injections:
        patched, injected = _inject_sidecar_texture_parameter(patched, injection, report)
        if injected:
            report.replaced_count += 1
    for rename in sidecar_patch_plan.texture_parameter_renames:
        patched, renamed = _rename_sidecar_texture_parameter(patched, rename, report)
        if renamed:
            report.replaced_count += 1
    if sidecar_patch_plan.prune_unmapped_texture_parameters:
        if sidecar_patch_plan.prune_material_names:
            patched, removed_count = _prune_unmapped_sidecar_texture_parameters_for_materials(
                patched,
                material_names=sidecar_patch_plan.prune_material_names,
                keep_rules=sidecar_patch_plan.texture_parameter_keep_rules,
            )
        else:
            patched, removed_count = _prune_unmapped_sidecar_texture_parameters(
                patched,
                sidecar_patch_plan.texture_parameter_keep_rules,
            )
        if removed_count:
            report.replaced_count += removed_count
            report.warnings.append(
                f"Removed {removed_count:,} unmapped original texture parameter(s) from rebuilt material sidecar."
            )
    if sidecar_patch_plan.neutralize_inherited_material_layers:
        patched, neutralized_wrappers, neutralized_parameters = _neutralize_inherited_material_layers(
            patched,
            material_names=sidecar_patch_plan.neutralize_material_names,
            keep_rules=sidecar_patch_plan.texture_parameter_keep_rules,
            complete_external_reset=bool(sidecar_patch_plan.complete_external_material_reset),
        )
        if neutralized_parameters:
            report.replaced_count += neutralized_parameters
            report.warnings.append(
                "Neutralized inherited material layers for "
                f"{neutralized_wrappers:,} material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
            )
    return patched, report








_TARGET_SAFE_PRESERVE_LAYER_TOKENS = (
    "skinnedmeshcloth",
    "clothcategory",
    "clothmaskbit",
    "grimediffusetexture",
    "grimenormaltexture",
    "grimematerialtexture",
    "grimeblendingparameter",
    "detaildiffusemask",
    "detailnormalmask",
    "detailheightmask",
    "detailmaterialmask",
)


def _material_authority_wrapper_needs_target_safe_preserve(wrapper_text: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", str(wrapper_text or "").lower())
    if not compact:
        return False
    return any(token in compact for token in _TARGET_SAFE_PRESERVE_LAYER_TOKENS)



def _references_by_target_path(original_texture_refs: Sequence[object]) -> dict[str, object]:
    references: dict[str, object] = {}
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path:
            continue
        references.setdefault(_normalize_texture_path(target_path), reference)
        reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        if reference_name:
            references.setdefault(_normalize_texture_path(reference_name), reference)
    return references




from .material_replacement_pipeline import (
    analyze_replacement_textures,
    _with_source_material_reference_textures,
    build_texture_replacement_payloads,
)

from .material_rebuilt_payloads import (
    _build_rebuilt_pac_driven_payloads,
    _active_rebuilt_material_names,
    _references_by_material,
    _references_for_active_material,
    _color_blending_mask_reference,
    _atlas_sections_by_target_name,
    _atlas_section_for_target,
    _build_complete_swap_atlas_material_payloads,
    _bake_complete_swap_material_atlas_png,
    _slot_for_complete_swap_atlas_role,
    _neutral_atlas_role_color,
    _source_driven_atlas_texture_output_path,
)

from .material_texture_payloads import (
    _manual_target_texture_slot_overrides,
    _apply_source_material_texture_overrides,
    _parse_source_material_texture_override,
    _override_enabled,
    _override_target_texture_path,
    _normalize_source_material_override_slot,
    _canonical_source_material_name,
    _normal_space_for_source_path,
    _build_manual_texture_slot_override_payloads,
    _source_slot_from_manual_path,
    _manual_source_material_name,
    _should_replace_original_texture_reference,
    _reference_belongs_to_active_static_target,
    _important_material_tokens,
    _active_target_tokens_conflict_path,
    _active_target_tokens_match_path,
    _is_direct_base_color_mapping,
    _needs_missing_base_color_parameter_payloads,
    _infer_slot_kind,
    _slot_for_target,
    _build_missing_base_color_parameter_payloads,
    _base_color_template_reference,
    _reference_target_parent,
    _infer_base_color_path_for_material,
    _preferred_base_color_suffix,
    _base_color_suffix_from_path,
    _infer_base_color_path_from_support_texture,
    _append_unused_texture_warnings,
    _warn_once,
    _looks_like_normal_texture_path,
    _sidecar_texture_parameter_rows,
    _append_texture_contract_warnings,
    _append_crimson_dds_validation_warnings,
    _build_texture_payload,
    _source_slot_needs_base_color_factor,
    _source_slot_needs_base_alpha_factor,
    _source_slot_needs_base_color_adjustment,
    _source_slot_png_with_base_color_factor_path,
    material_authority_preview_texture_slots,
    _dds_format_is_bc1,
    _force_png_alpha_opaque,
    _copy_png_with_inverted_green,
)

from .material_sidecar_patching import (
    _SOURCE_MATERIAL_OVERRIDE_SLOT_ALIASES,
    _normalize_texture_path,
    _inject_sidecar_texture_parameter,
    _find_sidecar_material_wrapper_by_texture_paths,
    _rename_sidecar_texture_parameter,
    _rename_sidecar_texture_parameter_by_path,
    _prune_unmapped_sidecar_texture_parameters,
    _prune_unmapped_sidecar_texture_parameters_for_materials,
    _material_wrapper_block_pattern,
    _material_wrapper_name,
    _prune_source_owned_sidecar_material_wrappers,
    _reorder_source_owned_sidecar_material_wrappers,
    _sync_submesh_resources_vector_idbase,
    _apply_source_pbr_scalar_parameters,
    _apply_source_emissive_parameters,
    _neutralize_inherited_material_layers,
    _neutralize_flat_material_instance_parameters,
    _renumber_sidecar_parameter_indexes,
    _rename_sidecar_parameter_name,
    _sidecar_texture_injection_position,
    _sidecar_parameter_name,
    _sidecar_parameter_index,
    _shift_sidecar_parameter_indexes,
    _find_sidecar_material_wrapper,
    _find_sidecar_material_wrapper_exact,
    _sidecar_material_names_match,
    _sidecar_material_match_score,
    _normalize_sidecar_material_name,
    _sidecar_texture_parameter_template,
    _next_material_parameter_index,
    _retarget_texture_parameter_template,
    _escape_xml_attr,
    _set_source_driven_wrapper_shader_name,
    _source_driven_parameter_item_id,
)

from .material_sidecar_payloads import (
    _VISIBLE_GEM_SENSITIVE_WRAPPER_TOKENS,
    _visible_gem_sensitive_wrappers_touched,
    _build_base_color_injection_for_target,
    _sidecar_keep_rules_from_slot_mappings,
    _should_keep_rebuilt_sidecar_texture_parameter,
    _build_patched_sidecar_payloads,
    _build_removed_target_prune_sidecar_payloads,
    _overlay_original_sidecars_with_payloads,
    _replace_sidecar_payloads,
    _build_donor_material_texture_payloads,
    _sidecar_kind_from_path,
    _donor_plan_texture_bindings,
    _donor_plan_anchor_texture_paths,
    _donor_binding_is_emissive,
    _donor_parameter_candidates,
    _patch_donor_texture_bindings_into_wrapper,
    _texture_parameter_paths_by_name,
    _restore_texture_parameter_paths,
    _donor_texture_patch_covers_selected_bindings,
    _wrapper_open_close,
    _retarget_wrapper_submesh_attrs,
    _material_wrapper_clones_for_output_draw_sections,
    _source_owned_keep_material_names_for_output_draw_sections,
    _source_owned_material_name_for_output_section,
    _profile_suppresses_runtime_placeholder_material_bindings,
    _source_owned_active_material_names_for_output_draw_sections,
    _apply_sidecar_material_wrapper_clones,
    _next_sidecar_material_wrapper_item_id,
    _retarget_wrapper_item_id,
    _insert_sidecar_material_wrapper_clone_after_donor,
    _graft_donor_wrapper_payload,
    _target_wrapper_for_donor_plan,
    _donor_wrapper_for_plan,
    _apply_donor_material_plan_to_sidecar,
    _build_donor_material_sidecar_payloads,
)


def _bind_lazy_material_exports(module_name: str, namespace: Mapping[str, object]) -> None:
    for export_name, current in tuple(globals().items()):
        marker = getattr(current, "_cdmw_lazy_material_export", None)
        if marker != (module_name, export_name) or export_name not in namespace:
            continue
        globals()[export_name] = namespace[export_name]


try:
    from .material_source_driven import (
        _source_driven_slots,
        _complete_swap_material_divergence_reasons,
        _source_slot_is_real_texture,
        _source_slot_is_synthetic_factor_authority,
        _texture_set_has_real_source_texture,
        _texture_set_has_source_authority_data,
        _texture_set_has_explicit_source_pbr,
        _complete_swap_neutral_support_slot,
        _complete_swap_runtime_material_mask_slot,
        _complete_swap_factor_only_material_mask_slot,
        _is_complete_swap_runtime_material_mask_path,
        _material_mask_rgba_from_roles,
        _source_slot_is_explicit_pbr,
        _source_slot_is_specular_glossiness,
        _source_slot_is_real_diffuse_base,
        _source_slot_channel_index,
        _complete_swap_runtime_material_mask_png_path,
        _blend_grayscale_channel_toward,
        _apply_profile_channel_adjustments,
        _optional_factor,
        _multiply_grayscale_channel,
        _apply_occlusion_strength,
        _factor_byte,
        _first_readable_image_size,
        _load_grayscale_channel,
        _load_rgb_luminance_channel,
        _complete_swap_neutral_support_png_path,
        _complete_swap_edge_relief_support_png_path,
        _source_driven_parameter_name,
        _byte4_uniform_rgb,
        _profile_scalar_byte4,
        _profile_scalar_values,
        _mean_image_channel,
        _mean_image_rgb_luminance,
        _looks_like_gltf_metallic_roughness,
        _source_pbr_scalar_values,
        _normalized_accent_glow_rgb,
        _complete_swap_accent_emissive_slot,
        _complete_swap_accent_glow_skip_reason,
        _specular_glossiness_runtime_base_slot,
        _specular_glossiness_should_drive_runtime_base,
        _specular_glossiness_runtime_base_png_path,
        _texture_set_is_accent_glow_candidate,
        _texture_set_has_explicit_glow_authority,
        _texture_set_is_saturated_factor_shell_accent,
        _texture_set_accent_glow_color_hex,
        _texture_role_for_parameter_and_path,
        _source_driven_template_reference,
        _source_driven_texture_parent,
        _source_driven_texture_prefix,
        _source_driven_texture_output_path,
        _source_driven_texture_output_name_parts,
        _source_driven_prefixed_stem,
        _strip_source_role_suffix,
        _sanitize_texture_component,
        _source_driven_texture_keep_rules,
        _build_source_driven_pac_material_payloads,
        _apply_detail_mask_material_contract_to_wrapper,
        _patch_source_driven_wrapper_texture_slots,
        _route_source_base_to_visible_color_texture_parameters,
        _bruteforce_source_authority_texture_parameters,
        _replace_source_driven_texture_parameter,
        _insert_source_driven_texture_parameter,
        _source_driven_wrapper_name,
        _source_driven_bindings_for_wrapper,
        _source_driven_parameter_body,
        _is_direct_pac_driven_parameter,
        _build_source_driven_sidecar_text,
    )

except ImportError as exc:
    if "partially initialized module" not in str(exc):
        raise

    def _lazy_material_source_driven(name: str):
        def _lazy(*args, **kwargs):
            from . import material_source_driven as module

            return getattr(module, name)(*args, **kwargs)

        _lazy._cdmw_lazy_material_export = ("cdmw.modding.material_source_driven", name)
        return _lazy

    _source_driven_slots = _lazy_material_source_driven('_source_driven_slots')
    _complete_swap_material_divergence_reasons = _lazy_material_source_driven('_complete_swap_material_divergence_reasons')
    _source_slot_is_real_texture = _lazy_material_source_driven('_source_slot_is_real_texture')
    _source_slot_is_synthetic_factor_authority = _lazy_material_source_driven('_source_slot_is_synthetic_factor_authority')
    _texture_set_has_real_source_texture = _lazy_material_source_driven('_texture_set_has_real_source_texture')
    _texture_set_has_source_authority_data = _lazy_material_source_driven('_texture_set_has_source_authority_data')
    _texture_set_has_explicit_source_pbr = _lazy_material_source_driven('_texture_set_has_explicit_source_pbr')
    _complete_swap_neutral_support_slot = _lazy_material_source_driven('_complete_swap_neutral_support_slot')
    _complete_swap_runtime_material_mask_slot = _lazy_material_source_driven('_complete_swap_runtime_material_mask_slot')
    _complete_swap_factor_only_material_mask_slot = _lazy_material_source_driven('_complete_swap_factor_only_material_mask_slot')
    _is_complete_swap_runtime_material_mask_path = _lazy_material_source_driven('_is_complete_swap_runtime_material_mask_path')
    _material_mask_rgba_from_roles = _lazy_material_source_driven('_material_mask_rgba_from_roles')
    _source_slot_is_explicit_pbr = _lazy_material_source_driven('_source_slot_is_explicit_pbr')
    _source_slot_is_specular_glossiness = _lazy_material_source_driven('_source_slot_is_specular_glossiness')
    _source_slot_is_real_diffuse_base = _lazy_material_source_driven('_source_slot_is_real_diffuse_base')
    _source_slot_channel_index = _lazy_material_source_driven('_source_slot_channel_index')
    _complete_swap_runtime_material_mask_png_path = _lazy_material_source_driven('_complete_swap_runtime_material_mask_png_path')
    _blend_grayscale_channel_toward = _lazy_material_source_driven('_blend_grayscale_channel_toward')
    _apply_profile_channel_adjustments = _lazy_material_source_driven('_apply_profile_channel_adjustments')
    _optional_factor = _lazy_material_source_driven('_optional_factor')
    _multiply_grayscale_channel = _lazy_material_source_driven('_multiply_grayscale_channel')
    _apply_occlusion_strength = _lazy_material_source_driven('_apply_occlusion_strength')
    _factor_byte = _lazy_material_source_driven('_factor_byte')
    _first_readable_image_size = _lazy_material_source_driven('_first_readable_image_size')
    _load_grayscale_channel = _lazy_material_source_driven('_load_grayscale_channel')
    _load_rgb_luminance_channel = _lazy_material_source_driven('_load_rgb_luminance_channel')
    _complete_swap_neutral_support_png_path = _lazy_material_source_driven('_complete_swap_neutral_support_png_path')
    _complete_swap_edge_relief_support_png_path = _lazy_material_source_driven('_complete_swap_edge_relief_support_png_path')
    _source_driven_parameter_name = _lazy_material_source_driven('_source_driven_parameter_name')
    _byte4_uniform_rgb = _lazy_material_source_driven('_byte4_uniform_rgb')
    _profile_scalar_byte4 = _lazy_material_source_driven('_profile_scalar_byte4')
    _profile_scalar_values = _lazy_material_source_driven('_profile_scalar_values')
    _mean_image_channel = _lazy_material_source_driven('_mean_image_channel')
    _mean_image_rgb_luminance = _lazy_material_source_driven('_mean_image_rgb_luminance')
    _looks_like_gltf_metallic_roughness = _lazy_material_source_driven('_looks_like_gltf_metallic_roughness')
    _source_pbr_scalar_values = _lazy_material_source_driven('_source_pbr_scalar_values')
    _normalized_accent_glow_rgb = _lazy_material_source_driven('_normalized_accent_glow_rgb')
    _complete_swap_accent_emissive_slot = _lazy_material_source_driven('_complete_swap_accent_emissive_slot')
    _complete_swap_accent_glow_skip_reason = _lazy_material_source_driven('_complete_swap_accent_glow_skip_reason')
    _specular_glossiness_runtime_base_slot = _lazy_material_source_driven('_specular_glossiness_runtime_base_slot')
    _specular_glossiness_should_drive_runtime_base = _lazy_material_source_driven('_specular_glossiness_should_drive_runtime_base')
    _specular_glossiness_runtime_base_png_path = _lazy_material_source_driven('_specular_glossiness_runtime_base_png_path')
    _texture_set_is_accent_glow_candidate = _lazy_material_source_driven('_texture_set_is_accent_glow_candidate')
    _texture_set_has_explicit_glow_authority = _lazy_material_source_driven('_texture_set_has_explicit_glow_authority')
    _texture_set_is_saturated_factor_shell_accent = _lazy_material_source_driven('_texture_set_is_saturated_factor_shell_accent')
    _texture_set_accent_glow_color_hex = _lazy_material_source_driven('_texture_set_accent_glow_color_hex')
    _texture_role_for_parameter_and_path = _lazy_material_source_driven('_texture_role_for_parameter_and_path')
    _source_driven_template_reference = _lazy_material_source_driven('_source_driven_template_reference')
    _source_driven_texture_parent = _lazy_material_source_driven('_source_driven_texture_parent')
    _source_driven_texture_prefix = _lazy_material_source_driven('_source_driven_texture_prefix')
    _source_driven_texture_output_path = _lazy_material_source_driven('_source_driven_texture_output_path')
    _source_driven_texture_output_name_parts = _lazy_material_source_driven('_source_driven_texture_output_name_parts')
    _source_driven_prefixed_stem = _lazy_material_source_driven('_source_driven_prefixed_stem')
    _strip_source_role_suffix = _lazy_material_source_driven('_strip_source_role_suffix')
    _sanitize_texture_component = _lazy_material_source_driven('_sanitize_texture_component')
    _source_driven_texture_keep_rules = _lazy_material_source_driven('_source_driven_texture_keep_rules')
    _build_source_driven_pac_material_payloads = _lazy_material_source_driven('_build_source_driven_pac_material_payloads')
    _apply_detail_mask_material_contract_to_wrapper = _lazy_material_source_driven('_apply_detail_mask_material_contract_to_wrapper')
    _patch_source_driven_wrapper_texture_slots = _lazy_material_source_driven('_patch_source_driven_wrapper_texture_slots')
    _route_source_base_to_visible_color_texture_parameters = _lazy_material_source_driven('_route_source_base_to_visible_color_texture_parameters')
    _bruteforce_source_authority_texture_parameters = _lazy_material_source_driven('_bruteforce_source_authority_texture_parameters')
    _replace_source_driven_texture_parameter = _lazy_material_source_driven('_replace_source_driven_texture_parameter')
    _insert_source_driven_texture_parameter = _lazy_material_source_driven('_insert_source_driven_texture_parameter')
    _source_driven_wrapper_name = _lazy_material_source_driven('_source_driven_wrapper_name')
    _source_driven_bindings_for_wrapper = _lazy_material_source_driven('_source_driven_bindings_for_wrapper')
    _source_driven_parameter_body = _lazy_material_source_driven('_source_driven_parameter_body')
    _is_direct_pac_driven_parameter = _lazy_material_source_driven('_is_direct_pac_driven_parameter')
    _build_source_driven_sidecar_text = _lazy_material_source_driven('_build_source_driven_sidecar_text')

try:
    from .material_texture_routing import (
        _TEXTURE_SUFFIXES,
        group_replacement_texture_sets,
        _parse_replacement_texture_filename,
        _replacement_texture_suffix_match,
        _attach_source_texture_reference_base_slots,
        _attach_source_material_factor_slots,
        _merge_source_role_tags,
        _source_material_role_tags,
        _source_material_numeric_parameter,
        _source_material_color_luminance_parameter,
        _source_material_specular_factor,
        _source_preview_rgb,
        _source_preview_alpha,
        _source_material_parameters,
        _source_emissive_rgb,
        _solid_material_factor_png_path,
        _normalize_source_texture_slot_kind,
        _source_texture_reference_is_visible_base,
        _texture_path_already_grouped,
        _paths_match,
        _texture_path_already_grouped_for_other_slot,
        _source_authority_priority,
        _default_texture_material_name,
        _match_known_material_prefix,
        _texture_slot_priority,
        _texture_slot_semantic_priority,
        _attach_source_face_counts,
        _normalized_source_part_material_role,
        _apply_source_part_role_overrides,
        _choose_source_materials_for_targets,
        _choose_source_materials_for_output_draw_sections,
        _augment_source_materials_from_rebuilt_mesh,
        _append_source_material_route_match_warnings,
        build_source_material_routing_plan,
        _texture_set_for_source_submesh,
        _source_submesh_display_name,
        _texture_set_detected_roles,
        _texture_reference_keys,
        _texture_set_for_source_texture_reference,
        _best_texture_set_for_source_mapping,
        _texture_source_candidate_score,
        _best_source_material_for_target,
        _material_tokens,
        _reference_target_path,
        _replacement_output_texture_path,
        _is_shared_material_layer_texture,
        is_shared_material_layer_texture,
        classify_texture_assignment_guidance,
    )
except ImportError as exc:
    if "partially initialized module" not in str(exc):
        raise

    def _lazy_material_texture_routing(name: str):
        def _lazy(*args, **kwargs):
            from . import material_texture_routing as module

            return getattr(module, name)(*args, **kwargs)

        _lazy._cdmw_lazy_material_export = ("cdmw.modding.material_texture_routing", name)
        return _lazy

    group_replacement_texture_sets = _lazy_material_texture_routing('group_replacement_texture_sets')
    _parse_replacement_texture_filename = _lazy_material_texture_routing('_parse_replacement_texture_filename')
    _replacement_texture_suffix_match = _lazy_material_texture_routing('_replacement_texture_suffix_match')
    _attach_source_texture_reference_base_slots = _lazy_material_texture_routing('_attach_source_texture_reference_base_slots')
    _attach_source_material_factor_slots = _lazy_material_texture_routing('_attach_source_material_factor_slots')
    _merge_source_role_tags = _lazy_material_texture_routing('_merge_source_role_tags')
    _source_material_role_tags = _lazy_material_texture_routing('_source_material_role_tags')
    _source_material_numeric_parameter = _lazy_material_texture_routing('_source_material_numeric_parameter')
    _source_material_color_luminance_parameter = _lazy_material_texture_routing('_source_material_color_luminance_parameter')
    _source_material_specular_factor = _lazy_material_texture_routing('_source_material_specular_factor')
    _source_preview_rgb = _lazy_material_texture_routing('_source_preview_rgb')
    _source_preview_alpha = _lazy_material_texture_routing('_source_preview_alpha')
    _source_material_parameters = _lazy_material_texture_routing('_source_material_parameters')
    _source_emissive_rgb = _lazy_material_texture_routing('_source_emissive_rgb')
    _solid_material_factor_png_path = _lazy_material_texture_routing('_solid_material_factor_png_path')
    _normalize_source_texture_slot_kind = _lazy_material_texture_routing('_normalize_source_texture_slot_kind')
    _source_texture_reference_is_visible_base = _lazy_material_texture_routing('_source_texture_reference_is_visible_base')
    _texture_path_already_grouped = _lazy_material_texture_routing('_texture_path_already_grouped')
    _paths_match = _lazy_material_texture_routing('_paths_match')
    _texture_path_already_grouped_for_other_slot = _lazy_material_texture_routing('_texture_path_already_grouped_for_other_slot')
    _source_authority_priority = _lazy_material_texture_routing('_source_authority_priority')
    _default_texture_material_name = _lazy_material_texture_routing('_default_texture_material_name')
    _match_known_material_prefix = _lazy_material_texture_routing('_match_known_material_prefix')
    _texture_slot_priority = _lazy_material_texture_routing('_texture_slot_priority')
    _texture_slot_semantic_priority = _lazy_material_texture_routing('_texture_slot_semantic_priority')
    _attach_source_face_counts = _lazy_material_texture_routing('_attach_source_face_counts')
    _normalized_source_part_material_role = _lazy_material_texture_routing('_normalized_source_part_material_role')
    _apply_source_part_role_overrides = _lazy_material_texture_routing('_apply_source_part_role_overrides')
    _choose_source_materials_for_targets = _lazy_material_texture_routing('_choose_source_materials_for_targets')
    _choose_source_materials_for_output_draw_sections = _lazy_material_texture_routing('_choose_source_materials_for_output_draw_sections')
    _augment_source_materials_from_rebuilt_mesh = _lazy_material_texture_routing('_augment_source_materials_from_rebuilt_mesh')
    _append_source_material_route_match_warnings = _lazy_material_texture_routing('_append_source_material_route_match_warnings')
    build_source_material_routing_plan = _lazy_material_texture_routing('build_source_material_routing_plan')
    _texture_set_for_source_submesh = _lazy_material_texture_routing('_texture_set_for_source_submesh')
    _source_submesh_display_name = _lazy_material_texture_routing('_source_submesh_display_name')
    _texture_set_detected_roles = _lazy_material_texture_routing('_texture_set_detected_roles')
    _texture_reference_keys = _lazy_material_texture_routing('_texture_reference_keys')
    _texture_set_for_source_texture_reference = _lazy_material_texture_routing('_texture_set_for_source_texture_reference')
    _best_texture_set_for_source_mapping = _lazy_material_texture_routing('_best_texture_set_for_source_mapping')
    _texture_source_candidate_score = _lazy_material_texture_routing('_texture_source_candidate_score')
    _best_source_material_for_target = _lazy_material_texture_routing('_best_source_material_for_target')
    _material_tokens = _lazy_material_texture_routing('_material_tokens')
    _reference_target_path = _lazy_material_texture_routing('_reference_target_path')
    _replacement_output_texture_path = _lazy_material_texture_routing('_replacement_output_texture_path')
    _is_shared_material_layer_texture = _lazy_material_texture_routing('_is_shared_material_layer_texture')
    is_shared_material_layer_texture = _lazy_material_texture_routing('is_shared_material_layer_texture')
    classify_texture_assignment_guidance = _lazy_material_texture_routing('classify_texture_assignment_guidance')


def __getattr__(name: str) -> object:
    if name == "_TEXTURE_SUFFIXES":
        from .material_texture_routing import _TEXTURE_SUFFIXES as value

        globals()[name] = value
        return value
    raise AttributeError(name)
