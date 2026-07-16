from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence


MATERIAL_AUTHORITY_REPORT_FILENAME = "cdmw_material_authority_report.json"
MATERIAL_AUTHORITY_REPORT_CHECK_SCHEMA = "cdmw_material_authority_report_check_v1"

DEFAULT_BLOCKING_RISK_FLAGS = (
    "preflight_blockers",
    "missing_final_dds",
    "invalid_dds_payload",
    "truncated_dds_payload",
    "normal_format_mismatch",
    "visible_color_format_mismatch",
    "technical_slot_srgb_format",
    "base_texture_used_as_emissive",
    "visible_technical_role_conflict",
    "source_missing_base_color",
    "source_alpha_missing_opacity",
    "source_spec_gloss_base_conflict",
)

REVIEW_RISK_FLAGS = (
    "missing_dds_mips",
    "dds_requires_pathc",
    "missing_source_path",
    "missing_package_root",
    "missing_target_sections",
    "missing_texture_outputs",
    "texture_output_unhashed",
    "missing_texture_payload_provenance",
    "missing_material_routing",
    "incomplete_material_routing",
    "routing_output_missing",
    "missing_pac_xml_sidecar_report",
    "path_mismatch_basename_only",
    "stock_shared_texture_override",
    "inherited_target_influence",
    "unknown_material_response",
    "missing_material_sidecar",
    "orphan_dds",
    "preview_draw_order_fallback",
    "preview_export_mismatch",
    "normal_slot_suspicious",
    "normal_y_policy_unconfirmed",
    "ambiguous_texture_role_binding",
    "source_missing_roughness_metalness",
    "source_emissive_scalar_no_texture",
    "missing_sidecar_output",
    "sidecar_output_unhashed",
    "missing_pac_xml_edit_summary",
    "missing_pac_xml_structural_compare",
    "pac_xml_wrapper_order_changed",
    "pac_xml_submesh_binding_changed",
    "pac_xml_item_id_changed",
    "pac_xml_parameter_abi_changed",
    "missing_neutralization_actions",
    "neutralization_action_mismatch",
    "neutralization_action_incomplete",
    "neutralization_action_not_required",
    "neutralization_abi_unproven",
    "missing_channel_visualization",
    "channel_order_visualization_mismatch",
    "missing_texture_conversion_policy",
    "missing_texture_conversion_note",
    "texture_conversion_role_mismatch",
    "missing_normal_conversion_policy",
    "missing_packed_mask_conversion_policy",
    "packed_mask_semantics_mismatch",
    "missing_spec_gloss_conversion_policy",
    "missing_visible_color_conversion_policy",
    "missing_source_channel_diagnostics",
    "missing_source_texture_facts",
    "source_texture_missing_format",
    "source_texture_missing_color_space",
    "source_texture_missing_resolution",
    "source_texture_missing_channel_stats",
    "missing_source_alpha_diagnostics",
    "missing_source_emissive_diagnostics",
    "missing_source_roughness_metalness_diagnostics",
    "missing_preview_settings",
    "missing_source_preview_evidence",
    "missing_final_preview_evidence",
    "missing_normal_y_policy",
    "missing_submesh_bindings",
    "submesh_binding_mismatch",
    "missing_dds_dimensions",
    "missing_dds_format",
    "missing_source_material_classification",
    "missing_source_material_sections",
    "source_material_section_missing_geometry",
    "dark_visible_color_output",
)

ROLE_DIAGNOSTIC_RISK_FLAGS = {
    "base_texture_used_as_emissive": "base_texture_used_as_emissive",
    "texture_bound_to_visible_and_technical_roles": "visible_technical_role_conflict",
    "normal_format_not_bc5": "normal_format_mismatch",
    "normal_srgb_format": "normal_format_mismatch",
    "normal_y_policy_unconfirmed": "normal_y_policy_unconfirmed",
    "multi_role_texture_binding": "ambiguous_texture_role_binding",
    "visible_color_technical_format": "visible_color_format_mismatch",
    "technical_slot_srgb_format": "technical_slot_srgb_format",
}

SOURCE_DIAGNOSTIC_RISK_FLAGS = {
    "source_missing_base_color": "source_missing_base_color",
    "source_alpha_without_opacity_texture": "source_alpha_missing_opacity",
    "source_spec_gloss_texture_as_base_color": "source_spec_gloss_base_conflict",
    "source_spec_gloss_texture_bound_as_base": "source_spec_gloss_base_conflict",
    "source_base_texture_bound_as_emissive": "base_texture_used_as_emissive",
    "source_material_response_texture_bound_as_base": "visible_technical_role_conflict",
    "source_base_texture_bound_as_normal": "normal_slot_suspicious",
    "source_emissive_scalar_no_texture": "source_emissive_scalar_no_texture",
}


def resolve_material_authority_report_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        return candidate / MATERIAL_AUTHORITY_REPORT_FILENAME
    return candidate


def load_material_authority_report(path: str | Path) -> Mapping[str, object]:
    report_path = resolve_material_authority_report_path(path)
    with report_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"Material authority report is not a JSON object: {report_path}")
    return data


def check_material_authority_report(
    report: Mapping[str, object],
    *,
    fail_on_risk_flags: Sequence[str] = DEFAULT_BLOCKING_RISK_FLAGS,
) -> dict[str, object]:
    risk_flags = tuple(str(flag) for flag in tuple(report.get("risk_flags", ()) or ()) if str(flag).strip())
    derived_risk_flags: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    schema = str(report.get("schema", "") or "")
    if schema != "cdmw_material_authority_report_v1":
        errors.append(f"Unsupported material authority report schema: {schema or '<missing>'}.")
    if tuple(report.get("preflight_errors", ()) or ()):
        derived_risk_flags.append("preflight_blockers")

    source_path = str(report.get("source_path", "") or "").strip()
    package_root = str(report.get("package_root", "") or "").strip()
    preview_settings = report.get("preview_settings")
    material_authority_export = (
        preview_settings.get("material_authority_export", {})
        if isinstance(preview_settings, Mapping)
        else {}
    )
    if not isinstance(material_authority_export, Mapping):
        material_authority_export = {}
    if not source_path:
        derived_risk_flags.append("missing_source_path")
        warnings.append("Report is missing source path evidence.")
    if not package_root:
        derived_risk_flags.append("missing_package_root")
        warnings.append("Report is missing package root evidence.")

    target_sections = tuple(item for item in tuple(report.get("target_sections", ()) or ()) if isinstance(item, Mapping))
    texture_outputs = tuple(item for item in tuple(report.get("texture_outputs", ()) or ()) if isinstance(item, Mapping))
    routing = tuple(item for item in tuple(report.get("routing", ()) or ()) if isinstance(item, Mapping))
    sidecar_reports = tuple(item for item in tuple(report.get("sidecar_reports", ()) or ()) if isinstance(item, Mapping))
    sidecar_outputs = tuple(item for item in tuple(report.get("sidecar_outputs", ()) or ()) if isinstance(item, Mapping))
    source_materials = tuple(item for item in tuple(report.get("source_materials", ()) or ()) if isinstance(item, Mapping))
    if not target_sections:
        derived_risk_flags.append("missing_target_sections")
        warnings.append("Report has no target section rows.")
    if not texture_outputs:
        derived_risk_flags.append("missing_texture_outputs")
        warnings.append("Report has no texture output rows.")
    if not routing:
        derived_risk_flags.append("missing_material_routing")
        warnings.append("Report has no material routing rows.")
    if not sidecar_reports:
        derived_risk_flags.append("missing_pac_xml_sidecar_report")
        warnings.append("Report has no PAC/XML sidecar authority rows.")
    if sidecar_reports and not sidecar_outputs:
        derived_risk_flags.append("missing_sidecar_output")
        warnings.append("Report has PAC/XML authority rows but no sidecar output artifact rows.")

    texture_status_counts: Counter[str] = Counter()
    role_diagnostic_counts: Counter[str] = Counter()
    channel_visualization_counts: Counter[str] = Counter()
    texture_conversion_source_counts: Counter[str] = Counter()
    texture_conversion_role_counts: Counter[str] = Counter()
    texture_conversion_source_route_diagnostic_counts: Counter[str] = Counter()
    source_diagnostic_counts: Counter[str] = Counter()
    source_material_class_counts: Counter[str] = Counter()
    routing_status_counts: Counter[str] = Counter()
    routing_binding_source_counts: Counter[str] = Counter()
    routing_confidence_counts: Counter[str] = Counter()
    pac_xml_wrapper_order_rows = 0
    pac_xml_submesh_binding_rows = 0
    pac_xml_scalar_range_rows = 0
    pac_xml_color_parameter_rows = 0
    pac_xml_alpha_control_rows = 0
    pac_xml_inherited_influence_rows = 0
    pac_xml_unknown_material_response_rows = 0
    pac_xml_neutralization_action_rows = 0
    pac_xml_neutralization_required_rows = 0
    pac_xml_neutralization_missing_rows = 0
    pac_xml_neutralization_incomplete_rows = 0
    pac_xml_neutralization_not_required_rows = 0
    pac_xml_neutralization_abi_unproven_rows = 0
    pac_xml_edit_summaries = 0
    pac_xml_texture_ref_change_rows = 0
    pac_xml_structural_compare_rows = 0
    pac_xml_structural_compare_missing = 0
    pac_xml_wrapper_order_changed = 0
    pac_xml_submesh_binding_changed = 0
    pac_xml_item_id_changed = 0
    pac_xml_parameter_abi_changed = 0
    channel_order_visualization_mismatches = 0
    packed_mask_semantics_mismatches = 0
    spec_gloss_conversion_policy_rows = 0
    spec_gloss_conversion_policy_missing = 0
    texture_conversion_source_route_diagnostic_rows = 0
    source_vertex_color_materials = 0
    source_vertex_alpha_materials = 0
    source_material_class_rows = 0
    source_material_section_rows = 0
    source_materials_missing_section_evidence = 0
    source_material_sections_missing_geometry = 0
    source_section_vertex_count = 0
    source_section_face_count = 0
    source_sections_missing_uvs = 0
    source_sections_missing_normals = 0
    source_skinned_sections = 0
    source_channel_profile_rows = 0
    source_texture_fact_rows = 0
    source_materials_missing_texture_facts = 0
    source_textures_missing_format = 0
    source_textures_missing_color_space = 0
    source_textures_missing_resolution = 0
    source_textures_missing_channel_stats = 0
    source_materials_missing_channel_diagnostics = 0
    source_materials_missing_alpha_diagnostics = 0
    source_materials_missing_emissive_diagnostics = 0
    source_materials_missing_roughness_metalness_diagnostics = 0
    source_detected_channel_counts: Counter[str] = Counter()
    source_missing_channel_counts: Counter[str] = Counter()
    source_preview_mesh_parts = 0
    final_preview_mesh_parts = 0
    source_preview_visible_texture_sets = 0
    final_preview_visible_texture_sets = 0
    texture_output_unhashed_rows = 0
    texture_payload_provenance_missing_rows = 0
    stock_shared_texture_output_rows = 0
    dark_visible_color_output_rows = 0
    routing_output_missing_rows = 0
    routing_incomplete_rows = 0
    texture_output_paths = {
        _normalized_report_texture_path(texture.get("target_path", ""))
        for texture in texture_outputs
        if _normalized_report_texture_path(texture.get("target_path", ""))
    }
    for route in routing:
        material_name = str(route.get("material_name", "") or route.get("part_name", "") or "<unknown>")
        status_value = str(route.get("status", "") or "").strip()
        binding_source_value = str(route.get("binding_source", "") or "").strip()
        confidence_value = str(route.get("confidence", "") or "").strip()
        status = status_value or "missing"
        binding_source = binding_source_value or "missing"
        confidence = confidence_value or "unknown"
        role = str(route.get("role", "") or "").strip()
        parameter_name = str(route.get("parameter_name", "") or "").strip()
        requested_path = str(route.get("requested_texture_path", "") or "")
        resolved_path = str(route.get("resolved_texture_path", "") or "")
        route_output_path = _normalized_report_texture_path(resolved_path or requested_path)
        routing_status_counts[status] += 1
        routing_binding_source_counts[binding_source] += 1
        routing_confidence_counts[confidence] += 1
        missing_route_fields = [
            field_name
            for field_name, value in (
                ("material_name", material_name if material_name != "<unknown>" else ""),
                ("role", role),
                ("parameter_name", parameter_name),
                ("status", status_value),
                ("binding_source", binding_source_value),
                ("confidence", confidence_value),
            )
            if not str(value or "").strip()
        ]
        if missing_route_fields or (status == "ready" and not route_output_path):
            routing_incomplete_rows += 1
            derived_risk_flags.append("incomplete_material_routing")
            warnings.append(
                "Material routing row is incomplete for "
                f"{material_name}: {', '.join(missing_route_fields) if missing_route_fields else 'missing output path'}."
            )
        if status == "missing_dds":
            derived_risk_flags.append("missing_final_dds")
            warnings.append(f"Final DDS missing for routed material binding: {material_name}.")
        if status == "ready" and binding_source == "generated" and not route_output_path:
            routing_output_missing_rows += 1
            derived_risk_flags.append("routing_output_missing")
            warnings.append(f"Ready generated route has no requested/resolved output path: {material_name}.")
        if status == "ready" and binding_source == "generated" and route_output_path and route_output_path not in texture_output_paths:
            routing_output_missing_rows += 1
            derived_risk_flags.append("missing_final_dds")
            derived_risk_flags.append("routing_output_missing")
            warnings.append(f"Ready generated route has no matching texture output row: {material_name} -> {route_output_path}.")
        if binding_source == "basename_diagnostic" or confidence == "basename":
            derived_risk_flags.append("path_mismatch_basename_only")
            warnings.append(f"Texture route used basename-only diagnostic matching: {material_name}.")
        if _is_stock_or_shared_texture_path(requested_path) or _is_stock_or_shared_texture_path(resolved_path):
            derived_risk_flags.append("stock_shared_texture_override")
            warnings.append(f"Texture route references stock/shared runtime texture path: {material_name}.")
    for sidecar in sidecar_reports:
        wrapper_rows = tuple(row for row in tuple(sidecar.get("wrapper_order", ()) or ()) if isinstance(row, Mapping))
        binding_rows = tuple(row for row in tuple(sidecar.get("submesh_bindings", ()) or ()) if isinstance(row, Mapping))
        pac_xml_wrapper_order_rows += len(wrapper_rows)
        pac_xml_submesh_binding_rows += len(binding_rows)
        pac_xml_scalar_range_rows += len(tuple(sidecar.get("scalar_ranges", ()) or ()))
        pac_xml_color_parameter_rows += len(tuple(sidecar.get("color_parameters", ()) or ()))
        pac_xml_alpha_control_rows += len(tuple(sidecar.get("alpha_controls", ()) or ()))
        inherited_rows = tuple(
            row for row in tuple(sidecar.get("inherited_influence_parameters", ()) or ()) if isinstance(row, Mapping)
        )
        neutralization_rows = tuple(row for row in tuple(sidecar.get("neutralization_actions", ()) or ()) if isinstance(row, Mapping))
        pac_xml_inherited_influence_rows += len(inherited_rows)
        pac_xml_unknown_material_response_rows += len(tuple(sidecar.get("unknown_material_response_parameters", ()) or ()))
        pac_xml_neutralization_action_rows += len(neutralization_rows)
        pac_xml_neutralization_required_rows += sum(1 for row in neutralization_rows if bool(row.get("required")))
        contract = str(sidecar.get("authority_contract", "") or report.get("authority_contract", "") or "true_source_authority")
        if inherited_rows and not neutralization_rows:
            derived_risk_flags.append("missing_neutralization_actions")
            sidecar_path = str(sidecar.get("path", "") or sidecar.get("target_path", "") or "<unknown>")
            warnings.append(f"PAC/XML inherited target influence lacks neutralization action rows: {sidecar_path}.")
        elif inherited_rows:
            inherited_identities = {_material_parameter_identity(row) for row in inherited_rows}
            action_identities = {_material_parameter_identity(row) for row in neutralization_rows}
            missing_identities = inherited_identities - action_identities
            if missing_identities:
                pac_xml_neutralization_missing_rows += len(missing_identities)
                derived_risk_flags.append("neutralization_action_mismatch")
                sidecar_path = str(sidecar.get("path", "") or sidecar.get("target_path", "") or "<unknown>")
                warnings.append(
                    f"PAC/XML inherited target influence has {len(missing_identities):,} unmatched neutralization action row(s): {sidecar_path}."
                )
            incomplete_rows = [
                row
                for row in neutralization_rows
                if not str(row.get("action", "") or "").strip() or not str(row.get("action_status", "") or "").strip()
            ]
            if incomplete_rows:
                pac_xml_neutralization_incomplete_rows += len(incomplete_rows)
                derived_risk_flags.append("neutralization_action_incomplete")
            abi_unproven_rows = [row for row in neutralization_rows if not bool(row.get("preserve_runtime_abi"))]
            if abi_unproven_rows:
                pac_xml_neutralization_abi_unproven_rows += len(abi_unproven_rows)
                derived_risk_flags.append("neutralization_abi_unproven")
            if contract != "runtime_xml_preserve":
                not_required_rows = [row for row in neutralization_rows if not bool(row.get("required"))]
                if not_required_rows:
                    pac_xml_neutralization_not_required_rows += len(not_required_rows)
                    derived_risk_flags.append("neutralization_action_not_required")
        wrapper_names = tuple(str(row.get("wrapper_name", "") or "").strip() for row in wrapper_rows)
        binding_names = tuple(str(row.get("wrapper_name", "") or "").strip() for row in binding_rows)
        if wrapper_names and binding_names and wrapper_names != binding_names:
            derived_risk_flags.append("submesh_binding_mismatch")
            sidecar_path = str(sidecar.get("path", "") or sidecar.get("target_path", "") or "<unknown>")
            warnings.append(f"PAC/XML wrapper order does not match _subMeshResources binding order: {sidecar_path}.")
    if pac_xml_wrapper_order_rows and not pac_xml_submesh_binding_rows:
        derived_risk_flags.append("missing_submesh_bindings")
        warnings.append("PAC/XML wrapper order rows exist but no _subMeshResources binding evidence was recorded.")
    if pac_xml_inherited_influence_rows:
        derived_risk_flags.append("inherited_target_influence")
    if pac_xml_unknown_material_response_rows:
        derived_risk_flags.append("unknown_material_response")
    for sidecar in sidecar_outputs:
        target_path = str(sidecar.get("target_path", "") or "<unknown>")
        edit_summary = sidecar.get("pac_xml_edit_summary")
        if isinstance(edit_summary, Mapping):
            pac_xml_edit_summaries += 1
            pac_xml_texture_ref_change_rows += len(tuple(edit_summary.get("texture_ref_changes", ()) or ()))
            structural_status = str(edit_summary.get("structural_compare_status", "") or "").strip()
            has_structural_keys = any(
                key in edit_summary
                for key in (
                    "wrapper_order_preserved",
                    "wrapper_item_ids_preserved",
                    "submesh_bindings_preserved",
                    "submesh_item_ids_preserved",
                    "parameter_abi_preserved",
                )
            )
            if structural_status == "source_compared" and has_structural_keys:
                pac_xml_structural_compare_rows += 1
            else:
                pac_xml_structural_compare_missing += 1
                derived_risk_flags.append("missing_pac_xml_structural_compare")
                warnings.append(f"PAC/XML sidecar structural comparison is missing or unavailable: {target_path}.")
            if has_structural_keys:
                if not bool(edit_summary.get("wrapper_order_preserved")):
                    pac_xml_wrapper_order_changed += 1
                    derived_risk_flags.append("pac_xml_wrapper_order_changed")
                    warnings.append(f"PAC/XML wrapper order/count changed from source: {target_path}.")
                if not bool(edit_summary.get("submesh_bindings_preserved")):
                    pac_xml_submesh_binding_changed += 1
                    derived_risk_flags.append("pac_xml_submesh_binding_changed")
                    warnings.append(f"PAC/XML submesh binding order/count changed from source: {target_path}.")
                if not bool(edit_summary.get("wrapper_item_ids_preserved")) or not bool(
                    edit_summary.get("submesh_item_ids_preserved")
                ):
                    pac_xml_item_id_changed += 1
                    derived_risk_flags.append("pac_xml_item_id_changed")
                    warnings.append(f"PAC/XML wrapper/submesh ItemID or IdBase changed from source: {target_path}.")
                if not bool(edit_summary.get("parameter_abi_preserved")):
                    pac_xml_parameter_abi_changed += 1
                    derived_risk_flags.append("pac_xml_parameter_abi_changed")
                    warnings.append(f"PAC/XML parameter ABI names, types, ItemIDs, or indexes changed: {target_path}.")
        else:
            pac_xml_structural_compare_missing += 1
            derived_risk_flags.append("missing_pac_xml_edit_summary")
            warnings.append(f"PAC/XML sidecar output is missing edit-summary evidence: {target_path}.")
        try:
            payload_size = int(sidecar.get("bytes", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            payload_size = 0
        sha256 = str(sidecar.get("sha256", "") or "").strip()
        if payload_size <= 0 or not sha256:
            derived_risk_flags.append("sidecar_output_unhashed")
            warnings.append(f"PAC/XML sidecar output is missing bytes or sha256 evidence: {target_path}.")
    for texture in texture_outputs:
        target_path = str(texture.get("target_path", "") or "<unknown>")
        texture_kind = str(texture.get("kind", "") or "").strip().lower()
        if bool(texture.get("stock_or_shared")) or _is_stock_or_shared_texture_path(target_path):
            stock_shared_texture_output_rows += 1
            derived_risk_flags.append("stock_shared_texture_override")
            warnings.append(f"Texture output targets stock/shared runtime texture path: {target_path}.")
        try:
            texture_bytes = int(texture.get("bytes", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            texture_bytes = 0
        texture_sha256 = str(texture.get("sha256", "") or texture.get("output_sha256", "") or "").strip()
        if texture_kind in {"texture", "texture_generated"} and (texture_bytes <= 0 or not texture_sha256):
            texture_output_unhashed_rows += 1
            derived_risk_flags.append("texture_output_unhashed")
            warnings.append(f"Texture output is missing bytes or sha256 evidence: {target_path}.")
        payload_source = str(texture.get("payload_source", "") or "").strip()
        if texture_kind in {"texture", "texture_generated"}:
            source_sha256 = str(texture.get("source_sha256", "") or "").strip()
            source_bytes = _report_int(texture.get("source_bytes"), 0)
            if payload_source not in {"inline_payload", "source_file"} or (
                payload_source == "source_file" and (source_bytes <= 0 or not source_sha256)
            ):
                texture_payload_provenance_missing_rows += 1
                derived_risk_flags.append("missing_texture_payload_provenance")
                warnings.append(f"Texture output is missing payload/source provenance evidence: {target_path}.")
        conversion_policy = texture.get("conversion_policy")
        expected_role_classes = _texture_expected_role_classes(texture)
        if isinstance(conversion_policy, Mapping) and conversion_policy:
            source_extension = str(conversion_policy.get("source_extension", "") or "<unknown>")
            texture_conversion_source_counts[source_extension] += 1
            policy_role_classes = {
                str(role_class or "").strip()
                for role_class in tuple(conversion_policy.get("bound_role_classes", ()) or ())
                if str(role_class or "").strip()
            }
            for role_class in tuple(conversion_policy.get("bound_role_classes", ()) or ()):
                role_text = str(role_class or "").strip()
                if role_text:
                    texture_conversion_role_counts[role_text] += 1
            for diagnostic in tuple(conversion_policy.get("source_route_diagnostics", ()) or ()):
                if not isinstance(diagnostic, Mapping):
                    continue
                code = str(diagnostic.get("code", "") or "").strip()
                if not code:
                    continue
                severity = str(diagnostic.get("severity", "") or "")
                texture_conversion_source_route_diagnostic_rows += 1
                texture_conversion_source_route_diagnostic_counts[code] += 1
                risk_flag = SOURCE_DIAGNOSTIC_RISK_FLAGS.get(code)
                if risk_flag:
                    derived_risk_flags.append(risk_flag)
                if severity == "warning":
                    warnings.append(f"Texture conversion source-route diagnostic warning for {target_path}: {code}.")
            missing_policy_roles = expected_role_classes - policy_role_classes
            if missing_policy_roles:
                derived_risk_flags.append("texture_conversion_role_mismatch")
                warnings.append(
                    f"Texture conversion policy role mismatch for {target_path}: "
                    + ", ".join(sorted(missing_policy_roles))
                    + "."
                )
            if "normal" in expected_role_classes and not bool(conversion_policy.get("normal_y_policy_required")):
                derived_risk_flags.append("missing_normal_conversion_policy")
                warnings.append(f"Normal DDS conversion policy is missing normal-Y requirement: {target_path}.")
            if "material" in expected_role_classes and not _conversion_policy_has_packed_semantics(conversion_policy):
                derived_risk_flags.append("missing_packed_mask_conversion_policy")
                warnings.append(f"Material/mask DDS conversion policy is missing packed channel semantics: {target_path}.")
            source_workflows = {
                str(value or "").strip().lower()
                for value in tuple(conversion_policy.get("source_workflows", ()) or ())
                if str(value or "").strip()
            }
            if "material" in expected_role_classes and "specular_glossiness" in source_workflows:
                if bool(conversion_policy.get("spec_gloss_conversion")) and _conversion_policy_derived_channels_include(
                    conversion_policy,
                    ("roughness", "metalness"),
                ):
                    spec_gloss_conversion_policy_rows += 1
                else:
                    spec_gloss_conversion_policy_missing += 1
                    derived_risk_flags.append("missing_spec_gloss_conversion_policy")
                    warnings.append(f"Specular-glossiness material output lacks conversion provenance: {target_path}.")
            if expected_role_classes.intersection({"base_color", "emissive"}) and not str(
                conversion_policy.get("channel_order", "") or ""
            ).strip():
                derived_risk_flags.append("missing_visible_color_conversion_policy")
                warnings.append(f"Visible color DDS conversion policy is missing channel order: {target_path}.")
        elif texture_kind in {"texture", "texture_generated"}:
            derived_risk_flags.append("missing_texture_conversion_policy")
            warnings.append(f"Texture output is missing conversion policy evidence: {target_path}.")
        if texture_kind == "texture_generated" and not str(texture.get("note", "") or "").strip():
            derived_risk_flags.append("missing_texture_conversion_note")
            warnings.append(f"Generated DDS output is missing source conversion note: {target_path}.")
        validation = texture.get("dds_validation")
        if isinstance(validation, Mapping):
            status = str(validation.get("status", "") or "")
            texture_status_counts[status or "missing"] += 1
            finding_codes = _finding_codes(validation.get("findings", ()))
            dds_format = str(validation.get("dds_format", "") or "").strip()
            try:
                width = int(validation.get("width", 0) or 0)
                height = int(validation.get("height", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                width = 0
                height = 0
            if status in {"invalid", "error", "missing_payload"}:
                derived_risk_flags.append("invalid_dds_payload")
                errors.append(f"DDS validation failed for {target_path}: {status}.")
            elif status == "warning":
                warnings.append(f"DDS validation warning for {target_path}: {', '.join(finding_codes) or 'warning'}.")
            if width <= 0 or height <= 0:
                derived_risk_flags.append("missing_dds_dimensions")
                warnings.append(f"DDS validation is missing dimensions for {target_path}.")
            if not dds_format:
                derived_risk_flags.append("missing_dds_format")
                warnings.append(f"DDS validation is missing a DDS format for {target_path}.")
            if "missing_mips" in finding_codes:
                derived_risk_flags.append("missing_dds_mips")
            if "payload_truncated" in finding_codes:
                derived_risk_flags.append("truncated_dds_payload")
            if bool(validation.get("requires_pathc")):
                derived_risk_flags.append("dds_requires_pathc")
        else:
            texture_status_counts["missing"] += 1
            derived_risk_flags.append("invalid_dds_payload")
            errors.append(f"DDS validation missing for {target_path}.")
        role_diagnostic_codes: list[str] = []
        for diagnostic in tuple(texture.get("role_diagnostics", ()) or ()):
            if not isinstance(diagnostic, Mapping):
                continue
            code = str(diagnostic.get("code", "") or "unknown")
            severity = str(diagnostic.get("severity", "") or "")
            role_diagnostic_codes.append(code)
            role_diagnostic_counts[code] += 1
            risk_flag = ROLE_DIAGNOSTIC_RISK_FLAGS.get(code)
            if risk_flag:
                derived_risk_flags.append(risk_flag)
            if severity == "warning":
                warnings.append(f"Role diagnostic warning for {target_path}: {code}.")
        channel_visualizations = tuple(
            visualization
            for visualization in tuple(texture.get("channel_visualization", ()) or ())
            if isinstance(visualization, Mapping)
        )
        expected_packed_mapping = _packed_mask_channel_mapping(texture)
        for visualization in channel_visualizations:
            if not isinstance(visualization, Mapping):
                continue
            kind = str(visualization.get("kind", "") or "unknown")
            channel_visualization_counts[kind] += 1
            if kind == "visible_color":
                expected_mapping = _visible_color_channel_mapping(texture, validation, conversion_policy)
                if expected_mapping and not _channel_visualization_matches(visualization, expected_mapping):
                    channel_order_visualization_mismatches += 1
                    derived_risk_flags.append("channel_order_visualization_mismatch")
                    warnings.append(
                        f"Visible-color channel visualization does not match DDS channel order for {target_path}."
                    )
            if kind == "packed_material_mask" and expected_packed_mapping and not _channel_visualization_matches(
                visualization,
                expected_packed_mapping,
            ):
                packed_mask_semantics_mismatches += 1
                derived_risk_flags.append("packed_mask_semantics_mismatch")
                warnings.append(f"Packed material-mask channel visualization does not match expected semantics: {target_path}.")
        if (
            expected_packed_mapping
            and isinstance(conversion_policy, Mapping)
            and tuple(conversion_policy.get("packed_channel_semantics", ()) or ())
            and not _channel_visualization_matches(
                {"channels": tuple(conversion_policy.get("packed_channel_semantics", ()) or ())},
                expected_packed_mapping,
            )
        ):
            packed_mask_semantics_mismatches += 1
            derived_risk_flags.append("packed_mask_semantics_mismatch")
            warnings.append(f"Packed material-mask conversion policy does not match expected semantics: {target_path}.")
        if _texture_requires_channel_visualization(texture) and not channel_visualizations:
            derived_risk_flags.append("missing_channel_visualization")
            warnings.append(f"Channel visualization missing for material-bound DDS output: {target_path}.")
        if _texture_is_normal_output(texture) and "normal_y_policy" not in role_diagnostic_codes:
            derived_risk_flags.append("missing_normal_y_policy")
            warnings.append(f"Normal DDS output is missing recorded normal-Y policy: {target_path}.")
        dark_role_classes = set(expected_role_classes)
        if isinstance(conversion_policy, Mapping):
            dark_role_classes.update(
                str(role_class or "").strip()
                for role_class in tuple(conversion_policy.get("bound_role_classes", ()) or ())
                if str(role_class or "").strip()
            )
        if "base_color" in dark_role_classes:
            luma_mean = _visible_color_luma_mean(texture, package_root)
            if luma_mean is not None and luma_mean < 45.0:
                dark_visible_color_output_rows += 1
                derived_risk_flags.append("dark_visible_color_output")
                auto_brightness = _report_float(material_authority_export.get("auto_brightness_balance"), 0.0)
                source_brightness = _report_float(material_authority_export.get("dark_detail_lift"), 0.0)
                tone_contrast = _report_float(material_authority_export.get("tone_contrast"), 0.0)
                if auto_brightness <= 0.0 and source_brightness <= 0.0 and abs(tone_contrast) <= 0.0001:
                    warnings.append(
                        "Visible base-color output is very dark for "
                        f"{target_path} (luma mean {luma_mean:.1f}); no Material Authority brightness/tone adjustment was recorded."
                    )
                else:
                    warnings.append(
                        "Visible base-color output is still very dark for "
                        f"{target_path} (luma mean {luma_mean:.1f}) after recorded Material Authority brightness/tone adjustment "
                        f"(auto {auto_brightness:.0f}%, source {source_brightness:.0f}%, tone {tone_contrast:+.0f}%)."
                    )
    for material in source_materials:
        material_name = str(material.get("material_name", "") or material.get("texture_name", "") or "<unknown>")
        channel_profile = material.get("channel_profile")
        if isinstance(channel_profile, Mapping):
            source_channel_profile_rows += 1
        else:
            channel_profile = {}
        detected_channels = _source_channel_values(material.get("detected_channels"), channel_profile.get("detected_channels"))
        missing_channels = _source_channel_values(material.get("missing_channels"), channel_profile.get("missing_channels"))
        source_detected_channel_counts.update(detected_channels)
        source_missing_channel_counts.update(missing_channels)
        class_rows = tuple(row for row in tuple(material.get("material_classification", ()) or ()) if isinstance(row, Mapping))
        if class_rows:
            source_material_class_rows += len(class_rows)
            for row in class_rows:
                class_name = str(row.get("class", "") or row.get("material_class", "") or "").strip()
                if class_name:
                    source_material_class_counts[class_name] += 1
        else:
            derived_risk_flags.append("missing_source_material_classification")
            warnings.append(f"Source material classification missing for {material_name}.")
        texture_refs = _source_material_texture_ref_paths(material)
        texture_fact_rows = tuple(row for row in tuple(material.get("texture_facts", ()) or ()) if isinstance(row, Mapping))
        if texture_refs and not texture_fact_rows:
            source_materials_missing_texture_facts += 1
            derived_risk_flags.append("missing_source_texture_facts")
            warnings.append(f"Source material texture facts missing for {material_name}.")
        for texture_fact in texture_fact_rows:
            source_texture_fact_rows += 1
            texture_name = str(texture_fact.get("texture_name", "") or texture_fact.get("texture_path", "") or "<unknown>")
            if not str(texture_fact.get("image_format", "") or "").strip():
                source_textures_missing_format += 1
                derived_risk_flags.append("source_texture_missing_format")
                warnings.append(f"Source texture image format missing for {material_name}: {texture_name}.")
            if not str(texture_fact.get("color_space", "") or "").strip():
                source_textures_missing_color_space += 1
                derived_risk_flags.append("source_texture_missing_color_space")
                warnings.append(f"Source texture color-space assumption missing for {material_name}: {texture_name}.")
            resolution = tuple(texture_fact.get("resolution", ()) or ())
            if len(resolution) < 2 or _report_int(resolution[0], 0) <= 0 or _report_int(resolution[1], 0) <= 0:
                source_textures_missing_resolution += 1
                derived_risk_flags.append("source_texture_missing_resolution")
                warnings.append(f"Source texture resolution missing for {material_name}: {texture_name}.")
            if not tuple(texture_fact.get("channel_stats", ()) or ()):
                source_textures_missing_channel_stats += 1
                derived_risk_flags.append("source_texture_missing_channel_stats")
                warnings.append(f"Source texture channel statistics missing for {material_name}: {texture_name}.")
        section_rows = tuple(row for row in tuple(material.get("sections", ()) or ()) if isinstance(row, Mapping))
        if not section_rows:
            source_materials_missing_section_evidence += 1
            derived_risk_flags.append("missing_source_material_sections")
            warnings.append(f"Source material submesh/section evidence missing for {material_name}.")
        for section in section_rows:
            source_material_section_rows += 1
            vertex_count = _report_int(section.get("vertex_count"), 0)
            face_count = _report_int(section.get("face_count"), 0)
            source_section_vertex_count += max(0, vertex_count)
            source_section_face_count += max(0, face_count)
            if vertex_count <= 0 or face_count <= 0:
                source_material_sections_missing_geometry += 1
                derived_risk_flags.append("source_material_section_missing_geometry")
                warnings.append(f"Source material section has no geometry counts for {material_name}.")
            if not bool(section.get("has_uvs")):
                source_sections_missing_uvs += 1
            if not bool(section.get("has_normals")):
                source_sections_missing_normals += 1
            if bool(section.get("has_skinning")):
                source_skinned_sections += 1
        vertex_color = tuple(material.get("vertex_color_factor", ()) or ())
        if len(vertex_color) >= 3:
            source_vertex_color_materials += 1
        vertex_alpha = tuple(material.get("vertex_alpha", ()) or ())
        if len(vertex_alpha) >= 2:
            try:
                if float(vertex_alpha[0]) < 0.98 or float(vertex_alpha[1]) < 0.98:
                    source_vertex_alpha_materials += 1
            except (TypeError, ValueError, OverflowError):
                pass
        diagnostic_codes: set[str] = set()
        source_diagnostics = tuple(material.get("diagnostics", ()) or ()) + tuple(
            material.get("channel_diagnostics", ()) or ()
        )
        for diagnostic in source_diagnostics:
            if not isinstance(diagnostic, Mapping):
                continue
            code = str(diagnostic.get("code", "") or "unknown")
            severity = str(diagnostic.get("severity", "") or "")
            if code:
                diagnostic_codes.add(code)
            source_diagnostic_counts[code] += 1
            risk_flag = SOURCE_DIAGNOSTIC_RISK_FLAGS.get(code)
            if risk_flag:
                derived_risk_flags.append(risk_flag)
            if severity == "warning":
                warnings.append(f"Source material diagnostic warning for {material_name}: {code}.")
        if {"roughness", "metalness"}.issubset(missing_channels):
            derived_risk_flags.append("source_missing_roughness_metalness")
        if not detected_channels and not missing_channels and not diagnostic_codes:
            source_materials_missing_channel_diagnostics += 1
            derived_risk_flags.append("missing_source_channel_diagnostics")
            warnings.append(f"Source material channel diagnostics missing for {material_name}.")
        alpha_mode = str(material.get("alpha_mode", "") or "").strip().lower()
        alpha_relevant = _source_alpha_relevant(alpha_mode, detected_channels, missing_channels, diagnostic_codes, vertex_alpha)
        if alpha_relevant and not _source_channel_has_evidence(
            detected_channels,
            missing_channels,
            diagnostic_codes,
            ("alpha", "opacity"),
        ):
            source_materials_missing_alpha_diagnostics += 1
            derived_risk_flags.append("missing_source_alpha_diagnostics")
            warnings.append(f"Source material alpha/opacity diagnostics missing for {material_name}.")
        if not _source_channel_has_evidence(detected_channels, missing_channels, diagnostic_codes, ("emissive",)):
            source_materials_missing_emissive_diagnostics += 1
            derived_risk_flags.append("missing_source_emissive_diagnostics")
            warnings.append(f"Source material emissive diagnostics missing for {material_name}.")
        if not all(
            _source_channel_has_evidence(detected_channels, missing_channels, diagnostic_codes, (channel,))
            for channel in ("roughness", "metalness")
        ):
            source_materials_missing_roughness_metalness_diagnostics += 1
            derived_risk_flags.append("missing_source_roughness_metalness_diagnostics")
            warnings.append(f"Source material roughness/metalness diagnostics missing for {material_name}.")

    if tuple(report.get("unknown_material_response_parameters", ()) or ()):
        derived_risk_flags.append("unknown_material_response")
    preview_settings = report.get("preview_settings")
    if not isinstance(preview_settings, Mapping) or not preview_settings:
        derived_risk_flags.append("missing_preview_settings")
        derived_risk_flags.append("missing_normal_y_policy")
        warnings.append("Material authority report is missing preview settings evidence.")
    else:
        source_mesh_value = _preview_setting_int(preview_settings, "source_preview_mesh_parts", "visible_mesh_parts")
        final_mesh_value = _preview_setting_int(preview_settings, "final_preview_mesh_parts", "final_visible_mesh_parts")
        source_texture_value = _preview_setting_int(preview_settings, "source_preview_visible_texture_sets")
        final_texture_value = _preview_setting_int(preview_settings, "final_preview_visible_texture_sets")
        if source_mesh_value is None or source_texture_value is None:
            derived_risk_flags.append("missing_source_preview_evidence")
            warnings.append("Material authority report preview settings are missing source preview mesh/texture evidence.")
        else:
            source_preview_mesh_parts = source_mesh_value
            source_preview_visible_texture_sets = source_texture_value
        if final_mesh_value is None or final_texture_value is None:
            derived_risk_flags.append("missing_final_preview_evidence")
            warnings.append("Material authority report preview settings are missing final/tool preview mesh/texture evidence.")
        else:
            final_preview_mesh_parts = final_mesh_value
            final_preview_visible_texture_sets = final_texture_value
        if source_texture_value is not None and final_texture_value is not None and source_texture_value > final_texture_value:
            derived_risk_flags.append("preview_export_mismatch")
            warnings.append(
                "Source preview has more visible texture sets than final/tool preview "
                f"({source_texture_value}/{final_texture_value})."
            )
        if "normal_y_policy" not in preview_settings:
            derived_risk_flags.append("missing_normal_y_policy")
            warnings.append("Material authority report preview settings are missing normal-Y policy evidence.")
        if bool(preview_settings.get("require_source_owned_colors")) and not sidecar_reports:
            derived_risk_flags.append("missing_material_sidecar")
    report_warning_text = "\n".join(str(warning) for warning in tuple(report.get("warnings", ()) or ())).lower()
    for token, flag in (
        ("orphan dds", "orphan_dds"),
        ("draw-order fallback", "preview_draw_order_fallback"),
        ("fewer visible texture", "preview_export_mismatch"),
        ("not referenced by parsed material sidecar", "orphan_dds"),
        ("normal-looking", "normal_slot_suspicious"),
    ):
        if token in report_warning_text:
            derived_risk_flags.append(flag)

    all_risk_flags = tuple(_dedupe_text((*risk_flags, *derived_risk_flags)))
    active_blocking_risk_flags = set(fail_on_risk_flags)
    blocking_flags = tuple(flag for flag in all_risk_flags if flag in active_blocking_risk_flags)
    if blocking_flags:
        errors.append("Blocking material authority risk flag(s): " + ", ".join(blocking_flags))
    review_risk_flag_set = set(REVIEW_RISK_FLAGS) | (set(DEFAULT_BLOCKING_RISK_FLAGS) - active_blocking_risk_flags)
    review_flags = tuple(flag for flag in all_risk_flags if flag in review_risk_flag_set and flag not in blocking_flags)
    for flag in review_flags:
        warnings.append(f"Review material authority risk flag: {flag}.")

    status = "failed" if errors else "needs_review" if warnings else "passed"
    return {
        "schema": MATERIAL_AUTHORITY_REPORT_CHECK_SCHEMA,
        "status": status,
        "source_report_schema": schema,
        "source_path": source_path,
        "package_root": package_root,
        "risk_flags": list(all_risk_flags),
        "source_risk_flags": list(risk_flags),
        "derived_risk_flags": _dedupe_text(derived_risk_flags),
        "blocking_risk_flags": list(blocking_flags),
        "review_risk_flags": list(review_flags),
        "counts": {
            "texture_outputs": len(texture_outputs),
            "texture_output_unhashed_rows": texture_output_unhashed_rows,
            "texture_payload_provenance_missing_rows": texture_payload_provenance_missing_rows,
            "stock_shared_texture_output_rows": stock_shared_texture_output_rows,
            "dark_visible_color_output_rows": dark_visible_color_output_rows,
            "routing_rows": len(routing),
            "routing_output_missing_rows": routing_output_missing_rows,
            "routing_incomplete_rows": routing_incomplete_rows,
            "target_sections": len(target_sections),
            "sidecar_reports": len(sidecar_reports),
            "sidecar_outputs": len(sidecar_outputs),
            "pac_xml_wrapper_order_rows": pac_xml_wrapper_order_rows,
            "pac_xml_submesh_binding_rows": pac_xml_submesh_binding_rows,
            "pac_xml_scalar_range_rows": pac_xml_scalar_range_rows,
            "pac_xml_color_parameter_rows": pac_xml_color_parameter_rows,
            "pac_xml_alpha_control_rows": pac_xml_alpha_control_rows,
            "pac_xml_inherited_influence_rows": pac_xml_inherited_influence_rows,
            "pac_xml_unknown_material_response_rows": pac_xml_unknown_material_response_rows,
            "pac_xml_neutralization_action_rows": pac_xml_neutralization_action_rows,
            "pac_xml_neutralization_required_rows": pac_xml_neutralization_required_rows,
            "pac_xml_neutralization_missing_rows": pac_xml_neutralization_missing_rows,
            "pac_xml_neutralization_incomplete_rows": pac_xml_neutralization_incomplete_rows,
            "pac_xml_neutralization_not_required_rows": pac_xml_neutralization_not_required_rows,
            "pac_xml_neutralization_abi_unproven_rows": pac_xml_neutralization_abi_unproven_rows,
            "pac_xml_edit_summaries": pac_xml_edit_summaries,
            "pac_xml_texture_ref_change_rows": pac_xml_texture_ref_change_rows,
            "pac_xml_structural_compare_rows": pac_xml_structural_compare_rows,
            "pac_xml_structural_compare_missing": pac_xml_structural_compare_missing,
            "pac_xml_wrapper_order_changed": pac_xml_wrapper_order_changed,
            "pac_xml_submesh_binding_changed": pac_xml_submesh_binding_changed,
            "pac_xml_item_id_changed": pac_xml_item_id_changed,
            "pac_xml_parameter_abi_changed": pac_xml_parameter_abi_changed,
            "channel_order_visualization_mismatches": channel_order_visualization_mismatches,
            "packed_mask_semantics_mismatches": packed_mask_semantics_mismatches,
            "spec_gloss_conversion_policy_rows": spec_gloss_conversion_policy_rows,
            "spec_gloss_conversion_policy_missing": spec_gloss_conversion_policy_missing,
            "texture_conversion_source_route_diagnostic_rows": texture_conversion_source_route_diagnostic_rows,
            "texture_conversion_source_route_diagnostics": dict(sorted(texture_conversion_source_route_diagnostic_counts.items())),
            "source_materials": len(source_materials),
            "source_material_class_rows": source_material_class_rows,
            "source_material_classes": dict(sorted(source_material_class_counts.items())),
            "source_texture_fact_rows": source_texture_fact_rows,
            "source_materials_missing_texture_facts": source_materials_missing_texture_facts,
            "source_textures_missing_format": source_textures_missing_format,
            "source_textures_missing_color_space": source_textures_missing_color_space,
            "source_textures_missing_resolution": source_textures_missing_resolution,
            "source_textures_missing_channel_stats": source_textures_missing_channel_stats,
            "source_material_section_rows": source_material_section_rows,
            "source_materials_missing_section_evidence": source_materials_missing_section_evidence,
            "source_material_sections_missing_geometry": source_material_sections_missing_geometry,
            "source_section_vertex_count": source_section_vertex_count,
            "source_section_face_count": source_section_face_count,
            "source_sections_missing_uvs": source_sections_missing_uvs,
            "source_sections_missing_normals": source_sections_missing_normals,
            "source_skinned_sections": source_skinned_sections,
            "source_channel_profile_rows": source_channel_profile_rows,
            "source_detected_channels": dict(sorted(source_detected_channel_counts.items())),
            "source_missing_channels": dict(sorted(source_missing_channel_counts.items())),
            "source_materials_missing_channel_diagnostics": source_materials_missing_channel_diagnostics,
            "source_materials_missing_alpha_diagnostics": source_materials_missing_alpha_diagnostics,
            "source_materials_missing_emissive_diagnostics": source_materials_missing_emissive_diagnostics,
            "source_materials_missing_roughness_metalness_diagnostics": source_materials_missing_roughness_metalness_diagnostics,
            "source_vertex_color_materials": source_vertex_color_materials,
            "source_vertex_alpha_materials": source_vertex_alpha_materials,
            "source_preview_mesh_parts": source_preview_mesh_parts,
            "final_preview_mesh_parts": final_preview_mesh_parts,
            "source_preview_visible_texture_sets": source_preview_visible_texture_sets,
            "final_preview_visible_texture_sets": final_preview_visible_texture_sets,
            "preview_visible_texture_delta": source_preview_visible_texture_sets - final_preview_visible_texture_sets,
            "routing_statuses": dict(sorted(routing_status_counts.items())),
            "routing_binding_sources": dict(sorted(routing_binding_source_counts.items())),
            "routing_confidences": dict(sorted(routing_confidence_counts.items())),
            "unknown_material_response_parameters": len(tuple(report.get("unknown_material_response_parameters", ()) or ())),
            "texture_validation_statuses": dict(sorted(texture_status_counts.items())),
            "role_diagnostics": dict(sorted(role_diagnostic_counts.items())),
            "channel_visualizations": dict(sorted(channel_visualization_counts.items())),
            "texture_conversion_sources": dict(sorted(texture_conversion_source_counts.items())),
            "texture_conversion_roles": dict(sorted(texture_conversion_role_counts.items())),
            "source_diagnostics": dict(sorted(source_diagnostic_counts.items())),
        },
        "errors": _dedupe_text(errors),
        "warnings": _dedupe_text(warnings),
    }


def check_material_authority_report_path(
    path: str | Path,
    *,
    fail_on_risk_flags: Sequence[str] = DEFAULT_BLOCKING_RISK_FLAGS,
) -> dict[str, object]:
    return check_material_authority_report(load_material_authority_report(path), fail_on_risk_flags=fail_on_risk_flags)


def _finding_codes(findings: object) -> tuple[str, ...]:
    codes: list[str] = []
    for finding in tuple(findings or ()):
        if isinstance(finding, Mapping):
            code = str(finding.get("code", "") or "").strip()
            if code:
                codes.append(code)
    return tuple(_dedupe_text(codes))


def _texture_requires_channel_visualization(texture: Mapping[str, object]) -> bool:
    validation = texture.get("dds_validation")
    if not isinstance(validation, Mapping):
        return False
    dds_format = str(validation.get("dds_format", "") or "").strip()
    if not dds_format:
        return False
    parts = [
        str(texture.get("target_path", "") or ""),
        " ".join(str(value or "") for value in tuple(texture.get("bound_roles", ()) or ())),
        " ".join(str(value or "") for value in tuple(texture.get("bound_parameters", ()) or ())),
    ]
    for diagnostic in tuple(texture.get("role_diagnostics", ()) or ()):
        if isinstance(diagnostic, Mapping):
            parts.append(str(diagnostic.get("code", "") or ""))
    text = " ".join(parts).replace("\\", "/").lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    filename = Path(str(texture.get("target_path", "") or "")).stem.lower()
    suffix_tokens = tuple(token for token in filename.replace("-", "_").split("_") if token)
    if suffix_tokens and suffix_tokens[-1] in {"n", "normal", "ma", "m", "mg", "r", "roughness", "metallic", "metalness", "ao", "emissive", "base", "rgba"}:
        return True
    return any(
        token in compact
        for token in (
            "basecolor",
            "overlaycolor",
            "diffuse",
            "albedo",
            "emissive",
            "normal",
            "roughness",
            "metallic",
            "metalness",
            "material",
            "mask",
            "colorblending",
            "height",
            "displacement",
            "specular",
            "gloss",
            "occlusion",
        )
    )


def _texture_is_normal_output(texture: Mapping[str, object]) -> bool:
    validation = texture.get("dds_validation")
    if not isinstance(validation, Mapping):
        return False
    dds_format = str(validation.get("dds_format", "") or "").strip()
    if not dds_format:
        return False
    parts = [
        str(texture.get("target_path", "") or ""),
        " ".join(str(value or "") for value in tuple(texture.get("bound_roles", ()) or ())),
        " ".join(str(value or "") for value in tuple(texture.get("bound_parameters", ()) or ())),
    ]
    text = " ".join(parts).replace("\\", "/").lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    filename = Path(str(texture.get("target_path", "") or "")).stem.lower()
    suffix_tokens = tuple(token for token in filename.replace("-", "_").split("_") if token)
    return "normal" in compact or bool(suffix_tokens and suffix_tokens[-1] in {"n", "normal"})


def _texture_expected_role_classes(texture: Mapping[str, object]) -> set[str]:
    bound_role_text = " ".join(str(value or "") for value in tuple(texture.get("bound_roles", ()) or ()))
    bound_parameter_text = " ".join(str(value or "") for value in tuple(texture.get("bound_parameters", ()) or ()))
    parameter_text = "".join(
        ch
        for ch in bound_parameter_text.lower()
        if ch.isalnum()
    )
    emissive_control = any(token in parameter_text for token in ("emissiveintensitytexture", "emissiveprogresstexture"))
    parts = [bound_role_text, bound_parameter_text]
    if not bound_role_text.strip() and not bound_parameter_text.strip():
        parts.append(str(texture.get("target_path", "") or ""))
    text = " ".join(parts).replace("\\", "/").lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    classes: set[str] = set()
    material_like = any(
        token in compact
        for token in (
            "colorblending",
            "material",
            "rough",
            "metal",
            "ao",
            "occlusion",
            "mask",
            "detail",
            "specular",
            "gloss",
        )
    )
    if any(token in compact for token in ("base", "overlay", "albedo", "diffuse")) or (
        "color" in compact and not material_like
    ):
        classes.add("base_color")
    if emissive_control:
        classes.add("emissive_control")
    elif any(token in compact for token in ("emissive", "emission", "glow", "illum")):
        classes.add("emissive")
    if "normal" in compact:
        classes.add("normal")
    if any(token in compact for token in ("height", "displacement", "bump", "parallax")):
        classes.add("height")
    if material_like:
        classes.add("material")
    return classes


def _conversion_policy_has_packed_semantics(conversion_policy: Mapping[str, object]) -> bool:
    kinds = {
        str(kind or "").strip().lower()
        for kind in tuple(conversion_policy.get("channel_visualization_kinds", ()) or ())
        if str(kind or "").strip()
    }
    if "packed_material_mask" in kinds:
        return True
    for row in tuple(conversion_policy.get("packed_channel_semantics", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        semantic = str(row.get("semantic", "") or "").strip().lower()
        if semantic in {"ao", "occlusion", "roughness", "metallic", "metalness", "specular", "glossiness", "alpha"}:
            return True
    return False


def _conversion_policy_derived_channels_include(
    conversion_policy: Mapping[str, object],
    channels: Sequence[str],
) -> bool:
    derived = {
        str(value or "").strip().lower()
        for value in tuple(conversion_policy.get("source_derived_channels", ()) or ())
        if str(value or "").strip()
    }
    wanted = {str(value or "").strip().lower() for value in tuple(channels or ()) if str(value or "").strip()}
    return bool(wanted) and wanted.issubset(derived)


def _visible_color_channel_mapping(
    texture: Mapping[str, object],
    validation: object,
    conversion_policy: object,
) -> tuple[tuple[str, str], ...]:
    channel_order = ""
    if isinstance(validation, Mapping):
        channel_order = str(validation.get("channel_order", "") or "").strip().lower()
    if not channel_order and isinstance(conversion_policy, Mapping):
        channel_order = str(conversion_policy.get("channel_order", "") or "").strip().lower()
    if channel_order not in {"rgba", "bgra", "bgrx"}:
        return ()
    if not _texture_expected_role_classes(texture).intersection({"base_color", "emissive"}):
        return ()
    if channel_order == "bgra":
        return (("B", "red"), ("G", "green"), ("R", "blue"), ("A", "alpha"))
    if channel_order == "bgrx":
        return (("B", "red"), ("G", "green"), ("R", "blue"), ("X", "unused"))
    return (("R", "red"), ("G", "green"), ("B", "blue"), ("A", "alpha"))


def _packed_mask_channel_mapping(texture: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    if "material" not in _texture_expected_role_classes(texture):
        return ()
    parts = [
        str(texture.get("target_path", "") or ""),
        " ".join(str(value or "") for value in tuple(texture.get("bound_roles", ()) or ())),
        " ".join(str(value or "") for value in tuple(texture.get("bound_parameters", ()) or ())),
    ]
    text = re.sub(r"[^a-z0-9]+", "", " ".join(parts).replace("\\", "/").lower())
    if "detail" in text or text.endswith("mg") or "detailmask" in text:
        return (("R", "detail_or_grime"), ("G", "detail_or_grime"), ("B", "detail_or_grime"), ("A", "alpha"))
    if "specular" in text or "gloss" in text:
        return (("R", "specular"), ("G", "glossiness"), ("B", "unused_or_ao"), ("A", "alpha"))
    if "roughness" in text and "metal" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "roughness"),)
    if "metal" in text and "roughness" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "metallic"),)
    if "ao" in text or "occlusion" in text:
        return (("R", "ao"),)
    return (("R", "ao"), ("G", "roughness"), ("B", "metallic"), ("A", "alpha"))


def _channel_visualization_matches(
    visualization: Mapping[str, object],
    expected_mapping: Sequence[tuple[str, str]],
) -> bool:
    actual: list[tuple[str, str]] = []
    for row in tuple(visualization.get("channels", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        channel = str(row.get("channel", "") or "").strip().upper()
        semantic = str(row.get("semantic", "") or "").strip().lower()
        if channel and semantic:
            actual.append((channel, semantic))
    return tuple(actual[: len(expected_mapping)]) == tuple(expected_mapping)


def _visible_color_luma_mean(texture: Mapping[str, object], package_root: str) -> float | None:
    recorded = texture.get("visible_luma_mean")
    try:
        if recorded is not None and recorded != "":
            return float(recorded)
    except (TypeError, ValueError, OverflowError):
        pass
    root_text = str(package_root or "").strip()
    target_text = str(texture.get("target_path", "") or "").replace("\\", "/").strip().strip("/")
    if not root_text or not target_text or ".." in target_text.split("/"):
        return None
    root = Path(root_text).expanduser()
    candidate = root.joinpath(*(part for part in target_text.split("/") if part))
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if not resolved_candidate.is_file():
        return None
    try:
        from PIL import Image, ImageStat

        with Image.open(resolved_candidate) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((256, 256))
            red, green, blue = ImageStat.Stat(rgb).mean[:3]
    except Exception:
        return None
    return (0.2126 * float(red)) + (0.7152 * float(green)) + (0.0722 * float(blue))


def _is_stock_or_shared_texture_path(texture_path: str) -> bool:
    basename = Path(str(texture_path or "").replace("\\", "/")).name.lower()
    return (
        basename.startswith("cd_texturelayer_")
        or basename.startswith("cd_temp")
        or basename.startswith("cd_metal_")
        or basename.startswith("blackoil")
        or basename.startswith("cd_common_default")
        or basename.startswith("nonetexture")
        or basename.startswith("none_texture")
    )


def _normalized_report_texture_path(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip()
    text = re.sub(r"/+", "/", text).strip("/")
    return text.lower()


def _material_parameter_identity(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("wrapper_name", "") or "").strip(),
        str(row.get("parameter_name", "") or "").strip(),
        str(row.get("item_id", "") or "").strip(),
        str(row.get("index", "") or "").strip(),
    )


def _source_channel_values(primary: object, fallback: object = ()) -> set[str]:
    values = tuple(primary or ()) or tuple(fallback or ())
    return {
        str(value or "").strip().lower()
        for value in values
        if str(value or "").strip()
    }


def _source_material_texture_ref_paths(material: Mapping[str, object]) -> set[str]:
    paths = {
        str(material.get(key, "") or "").strip()
        for key in (
            "preview_texture_path",
            "preview_normal_texture_path",
            "preview_material_texture_path",
            "preview_height_texture_path",
        )
        if str(material.get(key, "") or "").strip()
    }
    for texture_input in tuple(material.get("material_inputs", ()) or ()):
        if not isinstance(texture_input, Mapping):
            continue
        path = str(
            texture_input.get("texture_path", "")
            or texture_input.get("source_texture_path", "")
            or texture_input.get("source_dds_path", "")
            or ""
        ).strip()
        if path:
            paths.add(path)
    return paths


def _report_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _report_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _source_alpha_relevant(
    alpha_mode: str,
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
    vertex_alpha: tuple[object, ...],
) -> bool:
    if alpha_mode in {"blend", "mask", "alpha", "transparent", "coverage", "cutout"}:
        return True
    if {"alpha", "opacity"}.intersection(detected_channels | missing_channels):
        return True
    if any("alpha" in code or "opacity" in code for code in diagnostic_codes):
        return True
    if len(vertex_alpha) >= 2:
        try:
            return float(vertex_alpha[0]) < 0.98 or float(vertex_alpha[1]) < 0.98
        except (TypeError, ValueError, OverflowError):
            return False
    return False


def _source_channel_has_evidence(
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
    channels: Sequence[str],
) -> bool:
    wanted = {str(channel or "").strip().lower() for channel in channels if str(channel or "").strip()}
    if wanted.intersection(detected_channels | missing_channels):
        return True
    for channel in wanted:
        if f"{channel}_scalar" in detected_channels:
            return True
        if channel in {"alpha", "opacity"} and any(
            "alpha" in code or "opacity" in code for code in diagnostic_codes
        ):
            return True
        if any(code == f"source_missing_{channel}" or code.endswith(f"_{channel}") for code in diagnostic_codes):
            return True
    return False


def _preview_setting_int(settings: Mapping[str, object], key: str, fallback_key: str = "") -> int | None:
    for candidate in (key, fallback_key):
        if not candidate or candidate not in settings:
            continue
        try:
            return int(settings.get(candidate, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _dedupe_text(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = [
    "DEFAULT_BLOCKING_RISK_FLAGS",
    "MATERIAL_AUTHORITY_REPORT_CHECK_SCHEMA",
    "MATERIAL_AUTHORITY_REPORT_FILENAME",
    "REVIEW_RISK_FLAGS",
    "check_material_authority_report",
    "check_material_authority_report_path",
    "load_material_authority_report",
    "resolve_material_authority_report_path",
]
