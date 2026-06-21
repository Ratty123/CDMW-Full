"""Rebuilt PAC-driven and atlas material payload planning."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from .material_profiles import (
    CDMaterialRuntimeProfile,
    apply_true_source_basic_controls_to_profile,
    get_complete_swap_material_profile,
    normalize_global_gloss_reduction,
    _profile_is_source_only,
    _profile_ma_rgb_roles,
)
from .material_sidecar_patching import (
    _normalize_sidecar_material_name,
    _normalize_texture_path,
    _sidecar_material_match_score,
    _sidecar_material_names_match,
)
from .material_sidecar_payloads import (
    _build_base_color_injection_for_target,
    _build_patched_sidecar_payloads,
    _material_wrapper_clones_for_output_draw_sections,
    _profile_suppresses_runtime_placeholder_material_bindings,
    _sidecar_keep_rules_from_slot_mappings,
    _source_owned_active_material_names_for_output_draw_sections,
    _source_owned_keep_material_names_for_output_draw_sections,
)
from .material_texture_payloads import (
    _active_target_tokens_match_path,
    _append_texture_contract_warnings,
    _build_manual_texture_slot_override_payloads,
    _build_texture_payload,
    _infer_slot_kind,
    _slot_for_target,
    _source_slot_png_with_base_color_factor_path,
    _warn_once,
)

def _build_rebuilt_pac_driven_payloads(
    *,
    obj_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    target_to_source_material: Mapping[str, str],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    enable_missing_base_color_parameters: bool,
    texture_slot_overrides: Sequence[object],
    texture_output_size_mode: str,
    neutralize_inherited_material_layers: bool,
    complete_external_material_reset: bool = False,
    complete_swap_material_profile: str = "arm_standard",
    complete_swap_global_gloss_reduction: float = 0.0,
    complete_swap_edge_relief_strength: float = 0.0,
    complete_swap_edge_relief_source: str = "hybrid",
    complete_swap_accent_glow_strength: float = 0.0,
    complete_swap_auto_brightness_balance: float = 0.0,
    complete_swap_dark_detail_lift: float = 0.0,
    complete_swap_tone_contrast: float = 0.0,
    removed_target_material_names: Sequence[str] = (),
    prune_removed_target_texture_parameters: bool = False,
    prune_unmapped_original_texture_parameters: bool = False,
    output_draw_sections: Sequence[StaticOutputDrawSection] = (),
    pac_xml_corpus_root: str | Path | None = None,
    pac_xml_profile_cache_path: str | Path | None = None,
) -> list[TextureReplacementPayload]:
    from .material_replacer import (
        SidecarTextureParameterInjection,
        SidecarTextureParameterRename,
        TextureReplacementPayload,
        TextureSlotMapping,
        _references_by_target_path,
        is_static_replacement_helper_material_name,
    )
    from .material_source_driven import _build_source_driven_pac_material_payloads, _is_direct_pac_driven_parameter
    from .material_texture_routing import _best_source_material_for_target, _reference_target_path, _replacement_output_texture_path

    """Build texture and sidecar payloads from final rebuilt PAC/PAM draw sections.

    Only rebuilt submeshes with geometry drive generated texture payloads. The
    sidecar patch still preserves unrelated shader parameters because many
    game material wrappers rely on layer/detail/PBD data that is not part of
    the visible replacement texture set.
    """
    del obj_mesh
    gloss_reduction = normalize_global_gloss_reduction(complete_swap_global_gloss_reduction)
    material_profile = apply_true_source_basic_controls_to_profile(
        get_complete_swap_material_profile(complete_swap_material_profile),
        gloss_reduction=gloss_reduction,
        edge_relief_strength=complete_swap_edge_relief_strength,
        edge_relief_source=complete_swap_edge_relief_source,
        accent_glow_strength=complete_swap_accent_glow_strength,
        auto_brightness_balance=complete_swap_auto_brightness_balance,
        dark_detail_lift=complete_swap_dark_detail_lift,
        tone_contrast=complete_swap_tone_contrast,
    )
    references_by_material = _references_by_material(original_texture_refs)
    references_by_target_path = _references_by_target_path(original_texture_refs)
    if complete_external_material_reset and output_draw_sections:
        keep_names = _source_owned_keep_material_names_for_output_draw_sections(output_draw_sections)
        active_target_names = list(
            _source_owned_active_material_names_for_output_draw_sections(
                output_draw_sections,
                material_profile=material_profile,
            )
        )
        skipped_placeholder_count = len(tuple(keep_names)) - len(active_target_names)
        if skipped_placeholder_count > 0 and _profile_suppresses_runtime_placeholder_material_bindings(material_profile):
            _warn_once(
                report,
                "Material Authority Placeholder Safe Test: kept "
                f"{skipped_placeholder_count:,} runtime placeholder material wrapper(s) unpatched to avoid source glow flicker.",
            )
    else:
        active_target_names = _active_rebuilt_material_names(rebuilt_mesh, submesh_mappings)
    if not active_target_names:
        report.warnings.append("PAC-driven material sidecar had no rebuilt draw sections with geometry to bind.")
        return []

    if not texture_slot_overrides:
        source_driven_payloads = _build_source_driven_pac_material_payloads(
            texture_sets=texture_sets,
            original_texture_refs=original_texture_refs,
            original_sidecars=original_sidecars,
            active_target_names=active_target_names,
            target_to_source_material=target_to_source_material,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
            neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
            complete_external_material_reset=bool(complete_external_material_reset),
            complete_swap_material_profile=complete_swap_material_profile,
            complete_swap_global_gloss_reduction=gloss_reduction,
            complete_swap_edge_relief_strength=complete_swap_edge_relief_strength,
            complete_swap_edge_relief_source=complete_swap_edge_relief_source,
            complete_swap_accent_glow_strength=complete_swap_accent_glow_strength,
            complete_swap_auto_brightness_balance=complete_swap_auto_brightness_balance,
            complete_swap_dark_detail_lift=complete_swap_dark_detail_lift,
            complete_swap_tone_contrast=complete_swap_tone_contrast,
            removed_target_material_names=removed_target_material_names,
            prune_removed_target_texture_parameters=prune_removed_target_texture_parameters,
            prune_unmapped_original_texture_parameters=prune_unmapped_original_texture_parameters,
            material_wrapper_clones=_material_wrapper_clones_for_output_draw_sections(output_draw_sections),
            source_owned_keep_material_names=_source_owned_keep_material_names_for_output_draw_sections(output_draw_sections),
            output_draw_sections=output_draw_sections,
            pac_xml_corpus_root=pac_xml_corpus_root,
            pac_xml_profile_cache_path=pac_xml_profile_cache_path,
        )
        if source_driven_payloads:
            return source_driven_payloads
        if complete_external_material_reset and _profile_is_source_only(material_profile):
            return []

    payloads: list[TextureReplacementPayload] = []
    sidecar_replacements_by_path: dict[str, str] = {}
    sidecar_parameter_injections: list[SidecarTextureParameterInjection] = []
    sidecar_parameter_renames: list[SidecarTextureParameterRename] = []
    emitted_texture_paths: set[str] = set()
    manual_targets: set[str] = set()
    material_source_overrides: dict[str, str] = {}

    if texture_slot_overrides:
        override_payloads, override_replacements = _build_manual_texture_slot_override_payloads(
            texture_slot_overrides=texture_slot_overrides,
            reference_by_target_path=references_by_target_path,
            texture_sets=texture_sets,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        payloads.extend(override_payloads)
        sidecar_replacements_by_path.update(override_replacements)
        for mapping in report.slot_mappings:
            normalized_target = _normalize_texture_path(mapping.output_texture_path or mapping.target_texture_path)
            if normalized_target:
                manual_targets.add(normalized_target)
            if mapping.target_material_name and mapping.source_material_name:
                material_source_overrides.setdefault(
                    _normalize_sidecar_material_name(mapping.target_material_name),
                    mapping.source_material_name,
                )
        emitted_texture_paths.update(_normalize_texture_path(payload.target_path) for payload in override_payloads)

    for target_name in active_target_names:
        target_key = _normalize_sidecar_material_name(target_name)
        if is_static_replacement_helper_material_name(target_name) and target_key not in material_source_overrides:
            _warn_once(
                report,
                f"Preserved helper material wrapper {target_name}; automatic texture routing does not patch _black/_inside-style parts.",
            )
            continue
        source_material = material_source_overrides.get(target_key) or _best_source_material_for_target(
            target_name,
            target_to_source_material,
        )
        texture_set = texture_sets.get(str(source_material or "").strip().lower()) if source_material else None
        if texture_set is None:
            report.warnings.append(f"No replacement texture set was selected for rebuilt draw section {target_name}.")
            continue

        material_refs = _references_for_active_material(target_name, references_by_material)
        direct_refs = [
            reference
            for reference in material_refs
            if _is_direct_pac_driven_parameter(reference, _reference_target_path(reference))
        ]
        if not direct_refs:
            report.warnings.append(
                f"Rebuilt draw section {target_name} has no direct texture parameters in the original sidecar; "
                "base/normal/material slots may need manual sidecar authoring."
            )

        mapped_kinds: set[str] = set()
        direct_base_reference_exists = any(
            _infer_slot_kind(str(getattr(reference, "sidecar_parameter_name", "") or ""), _reference_target_path(reference)) == "base"
            for reference in direct_refs
        )
        repurposed_base_reference = (
            None
            if direct_base_reference_exists or texture_set.slots.get("base") is None
            else _color_blending_mask_reference(direct_refs)
        )
        for reference in direct_refs:
            target_path = _reference_target_path(reference)
            normalized_target = _normalize_texture_path(target_path)
            if not target_path or normalized_target in emitted_texture_paths:
                continue
            if normalized_target in manual_targets:
                continue
            target_entry = getattr(reference, "resolved_entry", None)
            if target_entry is None:
                report.warnings.append(f"Texture target could not be resolved in archive: {target_path}")
                continue
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "")
            if reference is repurposed_base_reference:
                slot_kind = "base"
                source_slot = texture_set.slots.get("base")
            else:
                slot_kind = _infer_slot_kind(parameter_name, target_path)
                source_slot = _slot_for_target(texture_set, slot_kind)
            if source_slot is None:
                continue
            if slot_kind in {"material", "material_mask", "detail_mask"} and source_slot.slot_kind != slot_kind:
                report.warnings.append(
                    f"{target_path} expects a packed material/mask texture; using {source_slot.slot_kind} source "
                    f"{source_slot.source_path.name}. Bake or pack metallic/roughness/AO into the game's expected mask layout for best results."
                )
            try:
                payload_data = _build_texture_payload(
                    source_slot,
                    target_entry=target_entry,
                    texconv_path=texconv_path,
                    read_original_texture_bytes=read_original_texture_bytes,
                    original_texture_source_path=original_texture_source_path,
                    report=report,
                    on_log=on_log,
                    texture_output_size_mode=texture_output_size_mode,
                )
            except Exception as exc:
                report.errors.append(f"Failed to build replacement texture for {target_path}: {exc}")
                continue
            output_texture_path = _replacement_output_texture_path(source_slot, target_path)
            payloads.append(
                TextureReplacementPayload(
                    target_path=output_texture_path,
                    payload_data=payload_data,
                    kind="texture_generated",
                    source_path=source_slot.source_path,
                    note=(
                        f"PAC-driven {target_name} base via existing color-blend slot: {source_slot.source_path.name}"
                        if reference is repurposed_base_reference
                        else f"PAC-driven {target_name} {slot_kind}: {source_slot.source_path.name}"
                    ),
                )
            )
            report.slot_mappings.append(
                TextureSlotMapping(
                    target_material_name=target_name,
                    target_texture_path=target_path,
                    slot_kind=slot_kind,
                    source_material_name=source_slot.material_name,
                    source_path=source_slot.source_path,
                    output_texture_path=output_texture_path,
                    normal_space=source_slot.normal_space,
                )
            )
            original_reference_name = str(getattr(reference, "reference_name", "") or "").strip()
            if original_reference_name and original_reference_name != output_texture_path:
                sidecar_replacements_by_path[original_reference_name] = output_texture_path
            if target_path != output_texture_path:
                sidecar_replacements_by_path[target_path] = output_texture_path
            if reference is repurposed_base_reference:
                sidecar_parameter_renames.append(
                    SidecarTextureParameterRename(
                        target_material_name=target_name,
                        texture_path=output_texture_path,
                        old_parameter_name="_colorBlendingMaskTexture",
                        new_parameter_name="_overlayColorTexture",
                    )
                )
                report.warnings.append(
                    f"PAC XML rebuild: repurposed _colorBlendingMaskTexture as _overlayColorTexture for {target_name}."
                )
            emitted_texture_paths.add(normalized_target)
            mapped_kinds.add(slot_kind)

        if "base" not in mapped_kinds and texture_set.slots.get("base") is not None:
            injected_payloads, injected_parameters = _build_base_color_injection_for_target(
                target_name=target_name,
                texture_set=texture_set,
                original_texture_refs=original_texture_refs,
                material_refs=material_refs,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
            payloads.extend(injected_payloads)
            sidecar_parameter_injections.extend(injected_parameters)
            if not injected_payloads and not enable_missing_base_color_parameters:
                report.warnings.append(
                    f"{target_name}: base color source {texture_set.slots['base'].source_path.name} is available, "
                    "but no compatible template was found for automatic PAC XML base-color injection."
                )

    sidecar_payloads = _build_patched_sidecar_payloads(
        original_sidecars=original_sidecars,
        sidecar_replacements_by_path=sidecar_replacements_by_path,
        sidecar_parameter_injections=sidecar_parameter_injections,
        sidecar_parameter_renames=sidecar_parameter_renames,
        texture_parameter_keep_rules=_sidecar_keep_rules_from_slot_mappings(
            report.slot_mappings,
            references_by_target_path,
        ),
        prune_unmapped_texture_parameters=bool(
            prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters
        ),
        prune_material_names=[] if prune_unmapped_original_texture_parameters else list(removed_target_material_names),
        neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
        complete_external_material_reset=bool(complete_external_material_reset),
        neutralize_material_names=list(active_target_names),
        report=report,
        include_unchanged_clone=bool(
            payloads
            and (
                sidecar_replacements_by_path
                or sidecar_parameter_injections
                or sidecar_parameter_renames
            )
        ),
    )
    _append_texture_contract_warnings(
        texture_payloads=payloads,
        sidecar_payloads=sidecar_payloads,
        report=report,
    )
    if payloads and not sidecar_payloads and original_sidecars:
        report.warnings.append(
            "PAC-driven texture payloads were built, but no .pac_xml sidecar changes were applied. "
            "This is expected only when texture paths are overwritten in-place."
        )
    elif sidecar_payloads:
        if neutralize_inherited_material_layers:
            report.warnings.append(
                "PAC-driven material sidecar rebuild used source-color faithful mode: inherited tint/grime/detail/color-blend layers were neutralized on active rebuilt draw sections."
            )
        else:
            report.warnings.append(
                "PAC-driven material sidecar rebuild preserved unmodified material parameters and patched only resolved texture bindings."
            )
    return payloads + sidecar_payloads


def _active_rebuilt_material_names(
    rebuilt_mesh: ParsedMesh,
    submesh_mappings: Sequence[StaticSubmeshMapping],
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    mapping_names_by_index = {
        int(mapping.target_submesh_index): str(mapping.target_submesh_name or "").strip()
        for mapping in submesh_mappings
    }
    for index, submesh in enumerate(rebuilt_mesh.submeshes):
        if not getattr(submesh, "vertices", None) or not getattr(submesh, "faces", None):
            continue
        name = (
            str(getattr(submesh, "material", "") or "").strip()
            or str(getattr(submesh, "name", "") or "").strip()
            or mapping_names_by_index.get(index, "")
            or f"target {index}"
        )
        key = _normalize_sidecar_material_name(name)
        if key and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def _references_by_material(original_texture_refs: Sequence[object]) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for reference in original_texture_refs:
        if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
            continue
        material_name = str(getattr(reference, "material_name", "") or "").strip()
        if not material_name:
            continue
        result.setdefault(_normalize_sidecar_material_name(material_name), []).append(reference)
    return result


def _references_for_active_material(
    target_name: str,
    references_by_material: Mapping[str, Sequence[object]],
) -> list[object]:
    from .material_texture_routing import _reference_target_path

    target_key = _normalize_sidecar_material_name(target_name)
    if target_key in references_by_material:
        return list(references_by_material[target_key])
    scored: list[tuple[float, object]] = []
    for material_key, references in references_by_material.items():
        if not material_key:
            continue
        representative = str(getattr(references[0], "material_name", "") or material_key)
        score = _sidecar_material_match_score(target_name, representative)
        if _sidecar_material_names_match(target_name, representative):
            score += 8.0
        for reference in references:
            path_text = _reference_target_path(reference)
            if _active_target_tokens_match_path(target_name, path_text):
                score += 4.0
        if score > 0:
            for reference in references:
                scored.append((score, reference))
    best_score = max((score for score, _reference in scored), default=0.0)
    if best_score < 6.0:
        return []
    return [reference for score, reference in scored if score == best_score]


def _color_blending_mask_reference(references: Sequence[object]) -> Optional[object]:
    from .material_texture_routing import _reference_target_path

    for reference in references:
        parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
        target_path = _reference_target_path(reference)
        if parameter == "_colorblendingmasktexture" and target_path.lower().endswith(".dds"):
            return reference
    return None




def _atlas_sections_by_target_name(
    output_draw_sections: Sequence[StaticOutputDrawSection],
) -> dict[str, StaticOutputDrawSection]:
    sections: dict[str, StaticOutputDrawSection] = {}
    for section in tuple(output_draw_sections or ()):
        if not tuple(getattr(section, "atlas_rects", ()) or ()):
            continue
        for value in (
            getattr(section, "target_submesh_name", ""),
            getattr(section, "runtime_material_name", ""),
            getattr(section, "runtime_slot_name", ""),
        ):
            key = _normalize_sidecar_material_name(str(value or ""))
            if key:
                sections.setdefault(key, section)
    return sections


def _atlas_section_for_target(
    target_name: str,
    atlas_sections_by_target: Mapping[str, StaticOutputDrawSection],
) -> Optional[StaticOutputDrawSection]:
    for key in {
        _normalize_sidecar_material_name(target_name),
        str(target_name or "").strip().lower(),
    }:
        if key and key in atlas_sections_by_target:
            return atlas_sections_by_target[key]
    return None


def _build_complete_swap_atlas_material_payloads(
    *,
    target_name: str,
    section: StaticOutputDrawSection,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    texture_parent: str,
    texture_prefix: str,
    emitted_paths: set[str],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
    material_profile: CDMaterialRuntimeProfile,
) -> tuple[list[tuple[str, str, str]], list[TextureReplacementPayload]]:
    from .material_replacer import ReplacementTextureSet, ReplacementTextureSlot, TextureReplacementPayload, TextureSlotMapping
    from .material_source_driven import (
        _complete_swap_material_divergence_reasons,
        _source_driven_parameter_name,
        _source_driven_template_reference,
    )

    rects = tuple(getattr(section, "atlas_rects", ()) or ())
    if not rects:
        return [], []
    material_names = [
        str(getattr(rect, "source_material_name", "") or "").strip()
        for rect in rects
        if str(getattr(rect, "source_material_name", "") or "").strip()
    ]
    if not material_names:
        report.errors.append(f"Cannot atlas/bake {target_name}: no source material names were recorded.")
        return [], []
    for material_name in tuple(dict.fromkeys(material_names)):
        texture_set = texture_sets.get(material_name.lower())
        if texture_set is None:
            continue
        for reason in _complete_swap_material_divergence_reasons(texture_set, material_profile):
            _warn_once(
                report,
                f"CD Runtime Approx divergence for atlas {target_name}/{texture_set.material_name}: {reason}.",
            )
    has_emissive = material_profile.emissive_mode == "intensity" and any(
        _slot_for_complete_swap_atlas_role(
            texture_sets.get(material_name.lower(), ReplacementTextureSet(material_name)),
            "emissive",
            material_profile=material_profile,
        )
        is not None
        for material_name in material_names
    )
    roles = ["base", "normal", "height", "material_mask", "detail_mask"]
    if has_emissive:
        roles.append("emissive")
    bindings: list[tuple[str, str, str]] = []
    payloads: list[TextureReplacementPayload] = []
    for role in roles:
        parameter_name = _source_driven_parameter_name(role, material_profile=material_profile)
        if not parameter_name:
            continue
        template_reference = _source_driven_template_reference(original_texture_refs, role)
        target_entry = getattr(template_reference, "resolved_entry", None) if template_reference is not None else None
        if target_entry is None:
            report.errors.append(f"Cannot atlas/bake {target_name}: no original DDS template exists for {role}.")
            continue
        atlas_png = _bake_complete_swap_material_atlas_png(
            target_name=target_name,
            rects=rects,
            texture_sets=texture_sets,
            slot_kind=role,
            padding=int(getattr(section, "atlas_padding", 8) or 8),
            report=report,
            material_profile=material_profile,
        )
        if atlas_png is None:
            continue
        atlas_slot = ReplacementTextureSlot(
            material_name=target_name,
            slot_kind=role,
            source_path=atlas_png,
            normal_space="directx" if role == "normal" else "",
        )
        output_texture_path = _source_driven_atlas_texture_output_path(
            texture_parent,
            texture_prefix,
            target_name,
            role,
            emitted_paths,
        )
        try:
            payload_data = _build_texture_payload(
                atlas_slot,
                target_entry=target_entry,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
        except Exception as exc:
            report.errors.append(f"Failed to build baked atlas texture for {target_name} {role}: {exc}")
            continue
        payloads.append(
            TextureReplacementPayload(
                target_path=output_texture_path,
                payload_data=payload_data,
                kind="texture_generated",
                source_path=atlas_png,
                note=(
                    f"Complete-swap baked atlas {role}: "
                    f"{', '.join(material_names)} -> {output_texture_path}"
                ),
            )
        )
        bindings.append((parameter_name, output_texture_path, role))
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name=target_name,
                target_texture_path=f"(complete-swap baked atlas {parameter_name})",
                slot_kind=role,
                source_material_name=" + ".join(material_names),
                source_path=atlas_png,
                output_texture_path=output_texture_path,
                normal_space=atlas_slot.normal_space,
            )
        )
    if bindings:
        report.warnings.append(
            "Complete source-owned swap baked material atlas for "
            f"{target_name}: {', '.join(material_names)}."
        )
    return bindings, payloads


def _bake_complete_swap_material_atlas_png(
    *,
    target_name: str,
    rects: Sequence[object],
    texture_sets: Mapping[str, ReplacementTextureSet],
    slot_kind: str,
    padding: int,
    report: TextureReplacementReport,
    material_profile: CDMaterialRuntimeProfile,
) -> Optional[Path]:
    from .material_source_driven import _sanitize_texture_component
    from PIL import Image

    material_images: list[tuple[object, str, Image.Image]] = []
    for rect in tuple(rects or ()):
        material_name = str(getattr(rect, "source_material_name", "") or "").strip()
        texture_set = texture_sets.get(material_name.lower())
        if texture_set is None:
            report.errors.append(f"Cannot atlas/bake {target_name}: missing source texture set {material_name}.")
            continue
        source_slot = _slot_for_complete_swap_atlas_role(texture_set, slot_kind, material_profile=material_profile)
        if source_slot is None:
            if str(slot_kind or "").strip().lower() == "emissive":
                material_images.append(
                    (
                        rect,
                        material_name,
                        Image.new("RGBA", (16, 16), _neutral_atlas_role_color("emissive", material_profile=material_profile)),
                    )
                )
                continue
            report.errors.append(f"Cannot atlas/bake {target_name}: missing source slot {slot_kind} for {material_name}.")
            continue
        try:
            image = Image.open(_source_slot_png_with_base_color_factor_path(source_slot)).convert("RGBA")
        except Exception as exc:
            report.errors.append(
                f"Cannot atlas/bake {target_name}: source {slot_kind} texture for {material_name} is unreadable: {source_slot.source_path} ({exc})."
            )
            continue
        material_images.append((rect, material_name, image))
    if len(material_images) != len(tuple(rects or ())):
        for _rect, _material_name, image in material_images:
            image.close()
        return None

    columns = max(1, round(1.0 / max(1e-6, min(float(getattr(rect, "width", 1.0) or 1.0) for rect in rects))))
    rows = max(1, round(1.0 / max(1e-6, min(float(getattr(rect, "height", 1.0) or 1.0) for rect in rects))))
    max_width = max((image.width for _rect, _material_name, image in material_images), default=16)
    max_height = max((image.height for _rect, _material_name, image in material_images), default=16)
    cell_width = min(4096 // columns, max(16, max_width + padding * 2))
    cell_height = min(4096 // rows, max(16, max_height + padding * 2))
    if cell_width <= padding * 2 or cell_height <= padding * 2:
        report.errors.append(f"Cannot atlas/bake {target_name}: atlas padding leaves no drawable area.")
        for _rect, _material_name, image in material_images:
            image.close()
        return None
    atlas_width = columns * cell_width
    atlas_height = rows * cell_height
    if atlas_width > 4096 or atlas_height > 4096:
        report.errors.append(f"Cannot atlas/bake {target_name}: atlas size {atlas_width}x{atlas_height} exceeds 4096.")
        for _rect, _material_name, image in material_images:
            image.close()
        return None

    atlas = Image.new("RGBA", (atlas_width, atlas_height), _neutral_atlas_role_color(slot_kind, material_profile=material_profile))
    for rect, _material_name, image in material_images:
        column = max(0, min(columns - 1, int(round(float(getattr(rect, "x", 0.0) or 0.0) * columns))))
        row = max(0, min(rows - 1, int(round(float(getattr(rect, "y", 0.0) or 0.0) * rows))))
        target_size = (max(1, cell_width), max(1, cell_height))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        resized = image.resize(target_size, resampling)
        atlas.paste(resized, (column * cell_width, row * cell_height))
        image.close()

    digest = hashlib.sha1(
        f"{target_name}|{slot_kind}|{atlas_width}x{atlas_height}|"
        f"{'|'.join(str(getattr(rect, 'source_material_name', '')) for rect in rects)}".encode("utf-8", errors="ignore")
    ).hexdigest()[:12]
    safe_target = _sanitize_texture_component(target_name) or "runtime_slot"
    safe_role = _sanitize_texture_component(slot_kind) or "role"
    root = Path(tempfile.gettempdir()) / "cdmw_baked_material_atlases"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_target}_{safe_role}_atlas_{digest}.png"
    atlas.save(path)
    return path


def _slot_for_complete_swap_atlas_role(
    texture_set: ReplacementTextureSet,
    slot_kind: str,
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> Optional[ReplacementTextureSlot]:
    from .material_replacer import ReplacementTextureSlot
    from .material_source_driven import (
        _complete_swap_accent_emissive_slot,
        _complete_swap_neutral_support_slot,
        _complete_swap_runtime_material_mask_slot,
        _specular_glossiness_runtime_base_slot,
    )
    from .material_texture_routing import _solid_material_factor_png_path

    profile = material_profile or get_complete_swap_material_profile()
    normalized = str(slot_kind or "").strip().lower()
    if normalized == "base":
        spec_gloss_base = _specular_glossiness_runtime_base_slot(texture_set)
        return (
            spec_gloss_base
            or texture_set.slots.get("base")
            or texture_set.slots.get("emissive")
            or ReplacementTextureSlot(
                material_name=texture_set.material_name,
                slot_kind="base",
                source_path=_solid_material_factor_png_path(texture_set.material_name, "base", (0.5, 0.5, 0.5)),
                source_authority="synthetic",
            )
        )
    source_slot = texture_set.slots.get(normalized)
    if source_slot is not None:
        return source_slot
    if normalized == "emissive":
        return _complete_swap_accent_emissive_slot(texture_set, texture_set.material_name, profile)
    if normalized == "material_mask":
        return _complete_swap_runtime_material_mask_slot(texture_set, profile)
    if normalized in {"normal", "height", "material_mask", "detail_mask"}:
        return _complete_swap_neutral_support_slot(texture_set, normalized, material_profile=profile)
    return None


def _neutral_atlas_role_color(
    slot_kind: str,
    *,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
) -> tuple[int, int, int, int]:
    profile = material_profile or get_complete_swap_material_profile()
    normalized = str(slot_kind or "").strip().lower()
    if normalized == "normal":
        return (128, 128, 255, 255)
    if normalized == "material_mask":
        defaults = {
            "ao": int(profile.ao_default),
            "roughness": int(profile.roughness_default),
            "metallic": int(profile.metallic_default),
        }
        return tuple(defaults.get(role, 0) for role in _profile_ma_rgb_roles(profile)) + (int(profile.alpha_default),)
    if normalized == "detail_mask":
        return (0, 0, 0, 0)
    if normalized == "emissive":
        return (0, 0, 0, 255)
    return (128, 128, 128, 255)


def _source_driven_atlas_texture_output_path(
    texture_parent: str,
    texture_prefix: str,
    target_name: str,
    slot_kind: str,
    emitted_paths: set[str],
) -> str:
    from .material_source_driven import _sanitize_texture_component

    parent = str(texture_parent or "character/texture").replace("\\", "/").strip("/")
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    target = _sanitize_texture_component(target_name) or "runtime_slot"
    role = _sanitize_texture_component(slot_kind) or "role"
    role_suffix = {
        "normal": "_n",
        "height": "_disp",
        "material_mask": "_ma",
        "detail_mask": "_mg",
        "emissive": "_emi",
    }.get(role, "")
    stem = f"{prefix}_{target}_baked_{role}"
    base_name = f"{stem}{role_suffix}.dds"
    candidate = f"{parent}/{base_name}" if parent else base_name
    normalized = _normalize_texture_path(candidate)
    if normalized not in emitted_paths:
        emitted_paths.add(normalized)
        return candidate
    index = 2
    while True:
        base_name = f"{stem}_{index}{role_suffix}.dds"
        candidate = f"{parent}/{base_name}" if parent else base_name
        normalized = _normalize_texture_path(candidate)
        if normalized not in emitted_paths:
            emitted_paths.add(normalized)
            return candidate
        index += 1
