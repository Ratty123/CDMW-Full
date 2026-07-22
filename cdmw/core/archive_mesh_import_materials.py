from __future__ import annotations

from collections.abc import Mapping

from cdmw.core.archive_mesh_import_build_state import MeshImportBuildState
from cdmw.core.common import raise_if_cancelled
from cdmw.modding.scene_importer import SCENE_TEXTURE_SOURCE_EXTENSIONS


def _public_api():
    from cdmw.core import archive_mesh_import_preview as public

    return public


def _clamped_option(options: object, name: str, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(getattr(options, name, 0.0) or 0.0)))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def configure_mesh_import_materials(state: MeshImportBuildState) -> None:
    options = state.static_replacement_options
    complete_reset = bool(getattr(options, "complete_external_material_reset", False))
    profile = str(
        getattr(
            options,
            "complete_swap_material_profile",
            "source_graph_strict" if complete_reset else "arm_standard",
        )
        or ("source_graph_strict" if complete_reset else "arm_standard")
    )
    values = {
        "global_gloss_reduction": _clamped_option(options, "global_gloss_reduction", -100.0, 100.0),
        "edge_relief_strength": _clamped_option(options, "edge_relief_strength", 0.0, 100.0),
        "edge_relief_source": str(getattr(options, "edge_relief_source", "hybrid") or "hybrid"),
        "accent_glow_strength": _clamped_option(options, "accent_glow_strength", 0.0, 100.0),
        "auto_brightness_balance": _clamped_option(options, "auto_brightness_balance", 0.0, 100.0),
        "dark_detail_lift": _clamped_option(options, "dark_detail_lift", -100.0, 100.0),
        "tone_contrast": _clamped_option(options, "tone_contrast", -100.0, 100.0),
    }
    state.material_options = {
        "texture_slot_overrides": tuple(getattr(options, "texture_slot_overrides", ()) or ()),
        "source_material_texture_overrides": tuple(
            getattr(options, "source_material_texture_overrides", ()) or ()
        ),
        "donor_material_plans": tuple(getattr(options, "donor_material_plans", ()) or ()),
        "prune_removed_target_texture_parameters": bool(
            getattr(options, "prune_removed_target_texture_parameters", False)
        ),
        "prune_unmapped_original_texture_parameters": bool(
            getattr(options, "prune_unmapped_original_texture_parameters", False)
        ),
        "complete_external_material_reset": complete_reset,
        "complete_swap_material_profile": profile,
        "material_authority_fingerprint": str(
            getattr(options, "material_authority_fingerprint", "") or ""
        ),
        "material_authority_revision": max(
            0, int(getattr(options, "material_authority_revision", 0) or 0)
        ),
        "material_authority_resolved_bindings": tuple(
            dict(binding)
            for binding in tuple(getattr(options, "material_authority_resolved_bindings", ()) or ())
            if isinstance(binding, Mapping)
        ),
        "material_authority_residual_parameter_groups": tuple(
            dict(group)
            for group in tuple(getattr(options, "material_authority_residual_parameter_groups", ()) or ())
            if isinstance(group, Mapping)
        ),
        **values,
    }
    state.material_authority_settings = {
        "enabled": complete_reset,
        "requested_profile": profile,
        "resolved_profile": "",
        "fingerprint": state.material_options["material_authority_fingerprint"],
        "revision": state.material_options["material_authority_revision"],
        **values,
    }
    append_mesh_import_material_summary(state)


def append_mesh_import_material_summary(state: MeshImportBuildState) -> None:
    options = state.static_replacement_options
    values = state.material_options
    if state.normalized_import_mode == "static_replacement" and bool(
        getattr(options, "neutralize_inherited_material_layers", False)
    ):
        state.summary_lines.append(
            "Source-color faithful material mode: enabled; generated material sidecars will neutralize inherited tint/grime/detail/color-blend layers on rebuilt draw sections."
        )
    if state.normalized_import_mode != "static_replacement" or not values["complete_external_material_reset"]:
        return
    state.summary_lines.extend(
        (
            "Complete external swap material reset: enabled; generated material sidecars will reset inherited target shader response on rebuilt draw sections.",
            f"Complete swap material profile: {values['complete_swap_material_profile']}; source PBR maps/factors will be translated into CD runtime support masks.",
        )
    )
    gloss = values["global_gloss_reduction"]
    if gloss < 0:
        state.summary_lines.append(
            f"Global gloss boost requested: {abs(gloss):.0f}%; generated source roughness will be lowered and compatible shine/scalar response increased."
        )
    elif gloss > 0:
        state.summary_lines.append(
            f"Global gloss reduction requested: {gloss:.0f}%; CD gloss/smoothness, metallic/spec, and shine response will be reduced."
        )
    if values["edge_relief_strength"] > 0:
        state.summary_lines.append(
            f"Edge relief requested: {values['edge_relief_strength']:.0f}% via {values['edge_relief_source'].replace('_', ' ')} support."
        )
    if values["accent_glow_strength"] > 0:
        state.summary_lines.append(
            f"Accent glow requested: {values['accent_glow_strength']:.0f}%; accent/emissive source parts will receive emissive shader parameters."
        )
    lift = values["dark_detail_lift"]
    if lift:
        action = "shadows and midtones will be lifted" if lift > 0 else "color will be dimmed before export"
        state.summary_lines.append(f"Source brightness requested: {lift:.0f}%; source base DDS {action}.")
    if values["auto_brightness_balance"] > 0:
        state.summary_lines.append(
            f"Auto brightness balance requested: {values['auto_brightness_balance']:.0f}%; source base DDS exposure will be nudged toward a stable midrange."
        )
    if abs(values["tone_contrast"]) > 0:
        state.summary_lines.append(
            f"Tone contrast requested: {values['tone_contrast']:+.0f}%; generated source base DDS tone curve will be adjusted."
        )


def _should_generate_static_textures(state: MeshImportBuildState) -> bool:
    values = state.material_options
    return state.normalized_import_mode == "static_replacement" and bool(
        state.resolved_supplemental_files
        or values["texture_slot_overrides"]
        or values["source_material_texture_overrides"]
        or values["donor_material_plans"]
        or values["prune_removed_target_texture_parameters"]
        or values["prune_unmapped_original_texture_parameters"]
    )


def _removed_target_material_names(state: MeshImportBuildState) -> tuple[str, ...]:
    return tuple(
        str(
            getattr(state.original_mesh.submeshes[int(index)], "material", "")
            or getattr(state.original_mesh.submeshes[int(index)], "name", "")
            or f"target {int(index)}"
        )
        for index in tuple(
            getattr(state.static_replacement_options, "removed_target_submesh_indices", ()) or ()
        )
        if str(index).strip().lstrip("-").isdigit()
        and 0 <= int(index) < len(getattr(state.original_mesh, "submeshes", ()) or ())
    )


def build_static_texture_payloads(state: MeshImportBuildState, original_sidecars: tuple):
    api = _public_api()
    values = state.material_options
    texture_files = tuple(
        path
        for path in state.resolved_supplemental_files
        if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
    )
    if not any(
        (
            texture_files,
            values["texture_slot_overrides"],
            values["source_material_texture_overrides"],
            values["donor_material_plans"],
            values["prune_removed_target_texture_parameters"],
            values["prune_unmapped_original_texture_parameters"],
        )
    ):
        return [], None
    payloads, report = api.build_texture_replacement_payloads(
        obj_mesh=state.effective_static_source_mesh,
        rebuilt_mesh=state.parsed_mesh,
        texture_files=texture_files,
        original_texture_refs=state.texture_references,
        original_sidecars=original_sidecars,
        submesh_mappings=state.static_mappings,
        read_original_texture_bytes=api._mesh_texture_original_bytes,
        original_texture_source_path=api._mesh_texture_original_source_path,
        enable_missing_base_color_parameters=state.enable_missing_base_color_parameters,
        texture_slot_overrides=values["texture_slot_overrides"],
        source_material_texture_overrides=values["source_material_texture_overrides"],
        source_part_adjustments=tuple(
            getattr(state.static_replacement_options, "source_part_adjustments", ()) or ()
        ),
        donor_material_plans=values["donor_material_plans"],
        texture_output_size_mode=str(
            getattr(state.static_replacement_options, "texture_output_size_mode", "source") or "source"
        ),
        pac_driven_sidecar=bool(
            getattr(state.static_replacement_options, "rebuild_material_sidecar", True)
        ),
        neutralize_inherited_material_layers=bool(
            getattr(state.static_replacement_options, "neutralize_inherited_material_layers", False)
        ),
        complete_external_material_reset=values["complete_external_material_reset"],
        complete_swap_material_profile=values["complete_swap_material_profile"],
        complete_swap_global_gloss_reduction=values["global_gloss_reduction"],
        complete_swap_edge_relief_strength=values["edge_relief_strength"],
        complete_swap_edge_relief_source=values["edge_relief_source"],
        complete_swap_accent_glow_strength=values["accent_glow_strength"],
        complete_swap_auto_brightness_balance=values["auto_brightness_balance"],
        complete_swap_dark_detail_lift=values["dark_detail_lift"],
        complete_swap_tone_contrast=values["tone_contrast"],
        removed_target_material_names=_removed_target_material_names(state),
        prune_removed_target_texture_parameters=values["prune_removed_target_texture_parameters"],
        prune_unmapped_original_texture_parameters=values["prune_unmapped_original_texture_parameters"],
        output_draw_sections=tuple(getattr(state.static_report, "output_draw_sections", ()) or ()),
        pac_xml_corpus_root=str(
            getattr(state.static_replacement_options, "pac_xml_corpus_root", "") or ""
        ),
        pac_xml_profile_cache_path=str(
            getattr(state.static_replacement_options, "pac_xml_profile_cache_path", "") or ""
        ),
    )
    fingerprint = str(values.get("material_authority_fingerprint", "") or "")
    bindings = tuple(values.get("material_authority_resolved_bindings", ()) or ())
    if fingerprint or bindings:
        from cdmw.services.material_authority_build_artifacts import (
            synchronize_material_authority_build_payloads,
        )

        if not fingerprint or not bindings:
            raise ValueError("Material Authority exact build state is incomplete.")
        exact_artifacts = synchronize_material_authority_build_payloads(
            payloads,
            report,
            bindings,
            fingerprint=fingerprint,
            parameter_groups=tuple(
                values.get("material_authority_residual_parameter_groups", ()) or ()
            ),
        )
        state.material_authority_settings.update(
            {
                "status": "exact",
                "exact_artifacts": exact_artifacts,
                "residual_parameter_groups": tuple(
                    values.get("material_authority_residual_parameter_groups", ()) or ()
                ),
            }
        )
    return payloads, report


def append_texture_replacement_report(state: MeshImportBuildState, report: object) -> None:
    profile = str(getattr(report, "material_profile_name", "") or "").strip()
    variants = tuple(getattr(report, "material_probe_variants", ()) or ())
    if profile:
        state.material_authority_settings["resolved_profile"] = profile
        state.summary_lines.append(f"Complete swap material profile active: {profile}")
        if variants:
            state.summary_lines.append(
                "Complete swap calibration profiles available: "
                + ", ".join(str(getattr(item, "material_profile_name", "") or "") for item in variants[:5])
            )
    routes = tuple(getattr(report, "material_routes", ()) or ())
    if routes:
        state.summary_lines.append("Static source material routing:")
        for route in routes[:16]:
            roles = ", ".join(tuple(getattr(route, "detected_roles", ()) or ())) or "-"
            source = str(getattr(route, "source_material_name", "") or "-")
            state.summary_lines.append(
                f"  {getattr(route, 'target_material_name', '')} <- {source} "
                f"[{getattr(route, 'status', 'Unknown')}; {roles}]"
            )
        if len(routes) > 16:
            state.summary_lines.append(f"  ... {len(routes) - 16:,} more routing row(s)")
    mappings = tuple(getattr(report, "slot_mappings", ()) or ())
    if mappings:
        state.summary_lines.append("Static texture replacement mapping:")
        state.summary_lines.extend(
            f"  {item.source_material_name} {item.slot_kind} ({item.source_path.name}) -> {item.output_texture_path}"
            for item in mappings[:16]
        )
        if len(mappings) > 16:
            state.summary_lines.append(f"  ... {len(mappings) - 16:,} more texture mapping(s)")
    if report.warnings:
        state.summary_lines.append("Static texture replacement warnings:")
        state.summary_lines.extend(f"  {warning}" for warning in report.warnings)
    if report.errors:
        state.summary_lines.append("Static texture replacement errors:")
        state.summary_lines.extend(f"  {error}" for error in report.errors)
    if not mappings and not report.warnings and not report.errors:
        state.summary_lines.append(
            "Static texture replacement found no matching original texture bindings for the selected PNG/DDS files."
        )


def publish_generated_texture_payloads(
    state: MeshImportBuildState,
    payloads: list,
    report: object,
    original_sidecars: tuple,
) -> None:
    if not payloads:
        return
    api = _public_api()
    count = api._apply_generated_static_texture_previews(
        state.preview_model,
        generated_payloads=payloads,
        texture_replacement_report=report,
    )
    if count:
        state.summary_lines.append(
            f"Applied {count:,} generated static texture preview slot(s) from PNG/DDS replacements."
        )
    elif not count:
        state.summary_lines.append(
            "Generated static texture payloads were not shown in preview because the DirectXTex/native preview backend did not produce usable previews."
        )
    specs = api._texture_replacement_payloads_to_specs(
        payloads,
        archive_entries_by_normalized_path=state.archive_entries_by_normalized_path,
    )
    state.supplemental_file_specs += specs
    texture_count = sum(1 for payload in payloads if payload.kind == "texture_generated")
    sidecar_count = sum(1 for payload in payloads if payload.kind == "sidecar_generated")
    if bool(getattr(state.static_replacement_options, "full_import_model_replacement", False)) and not sidecar_count:
        raise ValueError("Full Import Model Replacement could not generate a patched target material sidecar.")
    state.summary_lines.append(
        f"Generated static replacement payloads: {texture_count:,} texture(s), {sidecar_count:,} sidecar(s)."
    )
    if not original_sidecars:
        state.summary_lines.append(
            "Generated replacement texture payloads without a patched material sidecar because no original sidecar text was available."
        )


def generate_mesh_import_material_payloads(state: MeshImportBuildState) -> None:
    if _should_generate_static_textures(state):
        api = _public_api()
        original_sidecars = state.original_sidecars_for_static or api._collect_original_mesh_sidecar_texts(
            state.entry,
            state.texture_entries_by_basename,
            stop_event=state.stop_event,
        )
        raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
        try:
            payloads, report = build_static_texture_payloads(state, original_sidecars)
            raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
        except Exception as exc:
            raise_if_cancelled(state.stop_event, "Mesh import preview cancelled.")
            if str(state.material_options.get("material_authority_fingerprint", "") or ""):
                raise ValueError(f"Material Authority exact build failed closed: {exc}") from exc
            payloads, report = [], None
            state.summary_lines.append(f"Static texture replacement failed: {exc}")
        if report is not None:
            append_texture_replacement_report(state, report)
        publish_generated_texture_payloads(state, payloads, report, original_sidecars)
    if (
        state.normalized_import_mode == "static_replacement"
        and bool(getattr(state.static_replacement_options, "full_import_model_replacement", False))
        and not any(str(getattr(spec, "kind", "") or "") == "sidecar_generated" for spec in state.supplemental_file_specs)
    ):
        raise ValueError("Full Import Model Replacement requires generated target material sidecar output.")
    if state.supplemental_file_specs:
        mapped = sum(1 for spec in state.supplemental_file_specs if spec.target_path)
        unmapped = len(state.supplemental_file_specs) - mapped
        state.summary_lines.append(f"Supplemental files mapped to package/archive targets: {mapped:,}")
        if unmapped:
            state.summary_lines.append(
                f"{unmapped:,} supplemental file(s) could not be mapped to a known game-relative target automatically."
            )
