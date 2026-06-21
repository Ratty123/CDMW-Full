"""High-level material replacement payload orchestration."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence


def analyze_replacement_textures(
    obj_mesh: ParsedMesh,
    texture_files: Sequence[Path],
    original_sidecar_texts: Sequence[str] = (),
    original_texture_refs: Sequence[object] = (),
) -> TextureReplacementReport:
    from .material_replacer import TextureReplacementReport
    from .material_texture_routing import group_replacement_texture_sets

    """Group replacement texture files and report likely material slots."""
    del original_sidecar_texts, original_texture_refs
    texture_sets = group_replacement_texture_sets(texture_files, obj_mesh=obj_mesh)
    report = TextureReplacementReport(texture_sets=list(texture_sets.values()))
    if not texture_sets and texture_files:
        report.warnings.append("No replacement texture files matched known material suffix patterns.")
    return report


def _with_source_material_reference_textures(
    texture_files: Sequence[Path],
    obj_mesh: ParsedMesh,
) -> tuple[Path, ...]:
    """Include texture paths carried by imported material metadata."""

    from .material_texture_payloads import _SOURCE_TEXTURE_IMAGE_EXTENSIONS

    paths: list[Path] = []
    seen: set[str] = set()

    def add_path(value: object) -> None:
        text = str(value or "").strip()
        if not text:
            return
        path = Path(text).expanduser()
        try:
            path = path.resolve()
        except Exception:
            pass
        if path.suffix.lower() not in _SOURCE_TEXTURE_IMAGE_EXTENSIONS or not path.is_file():
            return
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    for texture_file in tuple(texture_files or ()):
        add_path(texture_file)
    for submesh in tuple(getattr(obj_mesh, "submeshes", ()) or ()):
        add_path(getattr(submesh, "texture", ""))
        for _slot_kind, slot_path in tuple(getattr(submesh, "texture_slots", ()) or ()):
            add_path(slot_path)
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            add_path(getattr(texture_input, "preview_texture_path", ""))
            add_path(getattr(texture_input, "source_texture_path", ""))
    return tuple(paths)


def build_texture_replacement_payloads(
    *,
    obj_mesh: ParsedMesh,
    rebuilt_mesh: Optional[ParsedMesh] = None,
    texture_files: Sequence[Path],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    on_log: Optional[Callable[[str], None]] = None,
    enable_missing_base_color_parameters: bool = False,
    texture_slot_overrides: Sequence[object] = (),
    source_material_texture_overrides: Sequence[object] = (),
    source_part_adjustments: Sequence[object] = (),
    donor_material_plans: Sequence[object] = (),
    texture_output_size_mode: str = "source",
    pac_driven_sidecar: bool = False,
    neutralize_inherited_material_layers: bool = False,
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
) -> tuple[list[TextureReplacementPayload], TextureReplacementReport]:
    from .material_profiles import (
        apply_true_source_basic_controls_to_profile,
        complete_swap_material_probe_variants,
        get_complete_swap_material_profile,
        normalize_basic_control_percent,
        normalize_edge_relief_source,
        normalize_global_gloss_reduction,
        _profile_gloss_reduction_mode,
        _profile_is_runtime_xml,
        _profile_mask_binding_mode,
    )
    from .material_replacer import (
        SidecarPatchPlan,
        SidecarTextureParameterInjection,
        TextureReplacementPayload,
        TextureSlotMapping,
        _references_by_target_path,
        patch_material_sidecar_text,
    )
    from .material_rebuilt_payloads import _build_rebuilt_pac_driven_payloads
    from .material_sidecar_payloads import (
        _build_donor_material_sidecar_payloads,
        _build_donor_material_texture_payloads,
        _build_patched_sidecar_payloads,
        _build_removed_target_prune_sidecar_payloads,
        _overlay_original_sidecars_with_payloads,
        _replace_sidecar_payloads,
        _sidecar_keep_rules_from_slot_mappings,
    )
    from .material_sidecar_patching import _normalize_texture_path
    from .material_texture_payloads import (
        _append_texture_contract_warnings,
        _append_unused_texture_warnings,
        _apply_source_material_texture_overrides,
        _build_manual_texture_slot_override_payloads,
        _build_missing_base_color_parameter_payloads,
        _build_texture_payload,
        _infer_slot_kind,
        _manual_target_texture_slot_overrides,
        _needs_missing_base_color_parameter_payloads,
        _reference_belongs_to_active_static_target,
        _should_replace_original_texture_reference,
        _slot_for_target,
        _warn_once,
    )
    from .material_texture_routing import (
        _apply_source_part_role_overrides,
        _attach_source_face_counts,
        _augment_source_materials_from_rebuilt_mesh,
        _best_source_material_for_target,
        _choose_source_materials_for_output_draw_sections,
        _choose_source_materials_for_targets,
        _reference_target_path,
        _replacement_output_texture_path,
    )

    """Build generated DDS and patched sidecar payloads for a static replacement."""
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
    effective_texture_files = tuple(texture_files or ())
    if complete_external_material_reset:
        effective_texture_files = _with_source_material_reference_textures(
            effective_texture_files,
            obj_mesh,
        )
    report = analyze_replacement_textures(obj_mesh, effective_texture_files)
    if complete_external_material_reset:
        report.material_profile_name = material_profile.name
        report.material_probe_variants = list(complete_swap_material_probe_variants())
        _warn_once(
            report,
            f"Complete swap material profile: {material_profile.name} ({material_profile.label}).",
        )
        if gloss_reduction != 0.0:
            gloss_strength = abs(gloss_reduction)
            gloss_mode = _profile_gloss_reduction_mode(material_profile)
            if gloss_reduction < 0.0:
                if gloss_mode == "source_roughness_high":
                    gloss_summary = (
                        f"Global gloss boost applied: {gloss_strength:.0f}%; generated source roughness is lowered "
                        "and compatible shine/scalar response is increased for source-owned wrappers."
                    )
                    gloss_channels = (
                        "Global gloss boost channels: generated material-mask/detail roughness is driven lower, "
                        "source metalness is preserved, and XML _scratchRoughness/_sheen plus compatible shine/scalar slots are patched when present."
                    )
                elif gloss_mode == "cd_smoothness_low_preserve_metal":
                    gloss_summary = (
                        f"Global gloss boost applied: {gloss_strength:.0f}%; CD smoothness/gloss response is raised "
                        "while source metalness is preserved for source-owned wrappers."
                    )
                    gloss_channels = (
                        "Global gloss boost channels: _colorBlendingMaskTexture G is driven smoothness-high, "
                        "B source metalness is preserved, and XML _scratchRoughness/_sheen plus compatible gloss/smoothness scalars are patched when present."
                    )
                else:
                    gloss_summary = (
                        f"Global gloss boost applied: {gloss_strength:.0f}%; CD gloss/smoothness mask response "
                        "and compatible shine scalars are increased for source-owned wrappers."
                    )
                    gloss_channels = (
                        "Global gloss boost channels: _colorBlendingMaskTexture G is driven gloss/high for CD gloss response, "
                        "B/A metallic-spec response is preserved, and XML _scratchRoughness/_scratchMetallic/_sheen "
                        "plus compatible gloss/smoothness/spec scalars are patched when present."
                    )
            elif gloss_mode == "source_roughness_high":
                gloss_summary = (
                    f"Global gloss reduction applied: {gloss_reduction:.0f}%; source roughness floor raised "
                    "while source metalness is preserved for source-owned wrappers."
                )
                gloss_channels = (
                    "Global gloss reduction channels: _colorBlendingMaskTexture G is driven rough/high for source PBR response, "
                    "B source metalness is preserved, and XML _scratchRoughness/_sheen plus compatible gloss/smoothness/spec scalars are patched when present."
                )
            elif gloss_mode == "cd_smoothness_low_preserve_metal":
                gloss_summary = (
                    f"Global gloss reduction applied: {gloss_reduction:.0f}%; CD smoothness/gloss response reduced "
                    "while source metalness is preserved for source-owned wrappers."
                )
                gloss_channels = (
                    "Global gloss reduction channels: _colorBlendingMaskTexture G is driven smoothness-low, "
                    "B source metalness is preserved, and XML _scratchRoughness/_sheen plus compatible gloss/smoothness scalars are patched when present."
                )
            else:
                gloss_summary = (
                    f"Global gloss reduction applied: {gloss_reduction:.0f}%; CD gloss/smoothness mask response, "
                    "metallic/spec, and shine scalars reduced for source-owned wrappers."
                )
                gloss_channels = (
                    "Global gloss reduction channels: _colorBlendingMaskTexture G is driven matte/low for CD gloss response, "
                    "B/A metallic-spec response is reduced where generated, and XML _scratchRoughness/_scratchMetallic/_sheen "
                    "plus compatible gloss/smoothness/spec scalars are patched when present."
                )
            _warn_once(
                report,
                gloss_summary,
            )
            _warn_once(
                report,
                gloss_channels,
            )
            if _profile_is_runtime_xml(material_profile) or _profile_mask_binding_mode(material_profile) == "disabled":
                _warn_once(
                    report,
                    "Global gloss/matte bias had limited effect for some wrappers because Runtime XML preserves stock material layers unless compatible scalar slots are patched.",
                )
        if normalize_basic_control_percent(complete_swap_edge_relief_strength) > 0.0:
            _warn_once(
                report,
                "Edge relief control applied: "
                f"{normalize_basic_control_percent(complete_swap_edge_relief_strength):.0f}% "
                f"({normalize_edge_relief_source(complete_swap_edge_relief_source).replace('_', ' ')}); "
                "height/detail support slots may be preserved or generated when compatible.",
            )
        if normalize_basic_control_percent(complete_swap_dark_detail_lift) > 0.0:
            _warn_once(
                report,
                "Source brightness control applied: "
                f"{normalize_basic_control_percent(complete_swap_dark_detail_lift):.0f}%; "
                "source base DDS shadows and midtones will be lifted before export.",
            )
        if normalize_basic_control_percent(complete_swap_auto_brightness_balance) > 0.0:
            _warn_once(
                report,
                "Auto brightness balance applied: "
                f"{normalize_basic_control_percent(complete_swap_auto_brightness_balance):.0f}%; "
                "source base DDS exposure will be nudged toward a stable midrange before export.",
            )
    texture_sets = {texture_set.material_name.lower(): texture_set for texture_set in report.texture_sets}
    _apply_source_material_texture_overrides(
        texture_sets,
        obj_mesh=obj_mesh,
        texture_slot_overrides=texture_slot_overrides,
        source_material_texture_overrides=source_material_texture_overrides,
        report=report,
    )
    if texture_sets:
        report.warnings[:] = [
            warning
            for warning in report.warnings
            if warning != "No replacement texture files matched known material suffix patterns."
        ]
    report.texture_sets = list(texture_sets.values())
    active_donor_material_plans = tuple(
        plan for plan in tuple(donor_material_plans or ()) if bool(getattr(plan, "enabled", True))
    )
    removed_target_material_names = tuple(
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    )
    prune_removed_target_texture_parameters = bool(prune_removed_target_texture_parameters and removed_target_material_names)
    prune_unmapped_original_texture_parameters = bool(prune_unmapped_original_texture_parameters)
    if (
        not texture_sets
        and not active_donor_material_plans
        and not prune_removed_target_texture_parameters
        and not prune_unmapped_original_texture_parameters
    ):
        return [], report

    if texture_sets:
        _attach_source_face_counts(texture_sets, obj_mesh)
        _apply_source_part_role_overrides(texture_sets, obj_mesh, source_part_adjustments)
        if complete_external_material_reset and output_draw_sections:
            target_to_source_material = _choose_source_materials_for_output_draw_sections(
                obj_mesh,
                texture_sets,
                output_draw_sections,
                report,
            )
        else:
            target_to_source_material = _choose_source_materials_for_targets(obj_mesh, texture_sets, submesh_mappings, report)
        if rebuilt_mesh is not None:
            _augment_source_materials_from_rebuilt_mesh(target_to_source_material, rebuilt_mesh, texture_sets)
    else:
        target_to_source_material = {}

    if pac_driven_sidecar and rebuilt_mesh is not None:
        generated_payloads: list[TextureReplacementPayload] = []
        if texture_sets:
            generated_payloads = _build_rebuilt_pac_driven_payloads(
                obj_mesh=obj_mesh,
                rebuilt_mesh=rebuilt_mesh,
                texture_sets=texture_sets,
                original_texture_refs=original_texture_refs,
                original_sidecars=original_sidecars,
                submesh_mappings=submesh_mappings,
                target_to_source_material=target_to_source_material,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                enable_missing_base_color_parameters=enable_missing_base_color_parameters,
                texture_slot_overrides=_manual_target_texture_slot_overrides(texture_slot_overrides),
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
                output_draw_sections=output_draw_sections,
                pac_xml_corpus_root=pac_xml_corpus_root,
                pac_xml_profile_cache_path=pac_xml_profile_cache_path,
            )
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        if donor_sidecar_payloads:
            generated_payloads = _replace_sidecar_payloads(generated_payloads, donor_sidecar_payloads)
            generated_payloads.extend(
                _build_donor_material_texture_payloads(
                    active_donor_material_plans,
                    existing_payloads=generated_payloads,
                    report=report,
                )
            )
        if (prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters) and not texture_sets:
            keep_rules = _sidecar_keep_rules_from_slot_mappings(
                report.slot_mappings,
                _references_by_target_path(original_texture_refs),
            )
            if prune_unmapped_original_texture_parameters:
                pruned_payloads = _build_patched_sidecar_payloads(
                    original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
                    sidecar_replacements_by_path={},
                    sidecar_parameter_injections=(),
                    texture_parameter_keep_rules=keep_rules,
                    prune_unmapped_texture_parameters=True,
                    prune_material_names=(),
                    report=report,
                )
            else:
                pruned_payloads = _build_removed_target_prune_sidecar_payloads(
                    original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
                    removed_target_material_names=removed_target_material_names,
                    keep_rules=keep_rules,
                    report=report,
                )
            if pruned_payloads:
                generated_payloads = _replace_sidecar_payloads(generated_payloads, pruned_payloads)
        report.generated_payloads = generated_payloads
        _append_unused_texture_warnings(texture_sets, report)
        return list(report.generated_payloads), report

    if active_donor_material_plans and not texture_sets:
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=original_sidecars,
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        report.generated_payloads = donor_sidecar_payloads + _build_donor_material_texture_payloads(
            active_donor_material_plans,
            existing_payloads=donor_sidecar_payloads,
            report=report,
        )
        return list(report.generated_payloads), report

    texture_payloads: list[TextureReplacementPayload] = []
    sidecar_replacements_by_path: dict[str, str] = {}
    sidecar_parameter_injections: list[SidecarTextureParameterInjection] = []
    reference_by_target_path = _references_by_target_path(original_texture_refs)
    emitted_target_paths: set[str] = set()
    target_texture_slot_overrides = _manual_target_texture_slot_overrides(texture_slot_overrides)
    if target_texture_slot_overrides:
        override_payloads, override_replacements = _build_manual_texture_slot_override_payloads(
            texture_slot_overrides=target_texture_slot_overrides,
            reference_by_target_path=reference_by_target_path,
            texture_sets=texture_sets,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        texture_payloads.extend(override_payloads)
        sidecar_replacements_by_path.update(override_replacements)
        emitted_target_paths.update(_normalize_texture_path(payload.target_path) for payload in override_payloads)

    skipped_inactive_target_count = 0
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path:
            continue
        if _normalize_texture_path(target_path) in emitted_target_paths:
            continue
        if not _should_replace_original_texture_reference(reference, target_path):
            continue
        if not _reference_belongs_to_active_static_target(reference, target_path, target_to_source_material):
            skipped_inactive_target_count += 1
            continue
        target_material = str(getattr(reference, "material_name", "") or "").strip()
        source_material = _best_source_material_for_target(target_material, target_to_source_material)
        if not source_material:
            source_material = _best_source_material_for_target(
                PurePosixPath(str(target_path or "").replace("\\", "/")).stem,
                target_to_source_material,
            )
        texture_set = texture_sets.get(source_material.lower()) if source_material else None
        if texture_set is None:
            continue

        slot_kind = _infer_slot_kind(
            str(getattr(reference, "sidecar_parameter_name", "") or ""),
            target_path,
        )
        source_slot = _slot_for_target(texture_set, slot_kind)
        if source_slot is None:
            continue
        if slot_kind == "material" and source_slot.slot_kind != "material":
            report.warnings.append(
                f"{target_path} expects a packed material/mask texture; using {source_slot.slot_kind} source "
                f"{source_slot.source_path.name}. Bake or pack metallic/roughness/AO into the game's expected mask layout for best results."
            )

        target_entry = getattr(reference, "resolved_entry", None)
        if target_entry is None:
            report.warnings.append(f"Texture target could not be resolved in archive: {target_path}")
            continue
        output_texture_path = _replacement_output_texture_path(source_slot, target_path)

        try:
            payload = _build_texture_payload(
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

        texture_payloads.append(
            TextureReplacementPayload(
                target_path=output_texture_path,
                payload_data=payload,
                kind="texture_generated",
                source_path=source_slot.source_path,
                note=f"{source_slot.material_name} {source_slot.slot_kind} -> {output_texture_path}",
            )
        )
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name=target_material,
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

    if skipped_inactive_target_count:
        report.warnings.append(
            f"Skipped {skipped_inactive_target_count:,} original texture binding(s) for draw/material slots with no replacement geometry."
        )

    if enable_missing_base_color_parameters:
        injected_payloads, injected_parameters = _build_missing_base_color_parameter_payloads(
            obj_mesh=obj_mesh,
            texture_sets=texture_sets,
            original_texture_refs=original_texture_refs,
            target_to_source_material=target_to_source_material,
            existing_slot_mappings=report.slot_mappings,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        texture_payloads.extend(injected_payloads)
        sidecar_parameter_injections.extend(injected_parameters)
    elif _needs_missing_base_color_parameter_payloads(
        texture_sets=texture_sets,
        target_to_source_material=target_to_source_material,
        existing_slot_mappings=report.slot_mappings,
        original_sidecars=original_sidecars,
    ):
        report.warnings.append(
            "A replacement base-color texture has no safe existing material slot. "
            "The app did not inject a new .pac_xml material parameter because this can make some shaders render untextured."
        )

    sidecar_payloads: list[TextureReplacementPayload] = []
    if texture_payloads and (sidecar_replacements_by_path or sidecar_parameter_injections):
        for sidecar_entry, sidecar_text in original_sidecars:
            sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
            patched_text, sidecar_report = patch_material_sidecar_text(
                sidecar_text,
                SidecarPatchPlan(
                    sidecar_path=sidecar_path,
                    texture_path_replacements=sidecar_replacements_by_path,
                    texture_parameter_injections=sidecar_parameter_injections,
                ),
            )
            report.sidecar_reports.append(sidecar_report)
            if sidecar_report.replaced_count <= 0 and (sidecar_replacements_by_path or sidecar_parameter_injections):
                report.warnings.append(
                    f"Patched sidecar {PurePosixPath(sidecar_path).name} did not apply any texture path or parameter changes."
                )
                continue
            sidecar_payloads.append(
                TextureReplacementPayload(
                    target_path=sidecar_path,
                    payload_data=patched_text.encode("utf-8"),
                    kind="sidecar_generated",
                    source_path=Path(PurePosixPath(sidecar_path).name),
                    note="Patched material sidecar cloned from original archive entry.",
                )
            )

    if active_donor_material_plans:
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        if donor_sidecar_payloads:
            sidecar_payloads = _replace_sidecar_payloads(sidecar_payloads, donor_sidecar_payloads)
            texture_payloads.extend(
                _build_donor_material_texture_payloads(
                    active_donor_material_plans,
                    existing_payloads=tuple(texture_payloads) + tuple(sidecar_payloads),
                    report=report,
                )
            )

    _append_texture_contract_warnings(
        texture_payloads=texture_payloads,
        sidecar_payloads=sidecar_payloads,
        report=report,
    )
    report.generated_payloads = texture_payloads + sidecar_payloads
    _append_unused_texture_warnings(texture_sets, report)
    return list(report.generated_payloads), report
