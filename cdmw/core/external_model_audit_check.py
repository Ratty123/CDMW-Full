from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence


EXTERNAL_MODEL_AUDIT_REPORT_FILENAME = "external_model_material_audit.json"
EXTERNAL_MODEL_AUDIT_CHECK_SCHEMA = "cdmw_external_model_audit_check_v1"

DEFAULT_BLOCKING_RISK_FLAGS = (
    "missing_models",
    "failed_models",
    "audited_model_without_material_inventory",
)

SOURCE_DATA_RISK_FLAGS = (
    "metadata_only_inventory",
    "missing_pbr_workflow",
    "missing_texture_slot_facts",
    "texture_missing_resolution",
    "texture_missing_channel_stats",
    "missing_texture_refs",
    "ambiguous_texture_refs",
    "unresolved_texture_candidates",
    "source_texture_route_mismatch",
)
DEFAULT_ALLOWED_RISK_FLAGS = SOURCE_DATA_RISK_FLAGS

REVIEW_RISK_FLAGS = (
    "archive_content_not_audited",
    "zip_audit_limit_skipped",
    "metadata_only_inventory",
    "missing_material_classes",
    "missing_pbr_workflow",
    "missing_channel_diagnostics",
    "missing_texture_slot_facts",
    "texture_missing_resolution",
    "texture_missing_format",
    "texture_missing_color_space",
    "texture_missing_channel_stats",
    "material_missing_sections",
    "section_missing_geometry",
    "section_missing_uvs",
    "section_missing_normals",
    "missing_texture_refs",
    "ambiguous_texture_refs",
    "unresolved_texture_candidates",
    "missing_alpha_diagnostics",
    "missing_emissive_diagnostics",
    "missing_roughness_metalness_diagnostics",
    "source_texture_route_mismatch",
)

_AUDITED_STATUSES = {"audited", "archive_audited"}
_FAILED_STATUSES = {"failed", "archive_failed"}
_METADATA_ONLY_STATUSES = {"browsable_material_inferred", "browsable_unsupported"}
_ALPHA_MODES = {"alpha", "blend", "coverage", "cutout", "mask", "transparent"}
_SOURCE_TEXTURE_ROUTE_MISMATCH_CODES = {
    "source_base_texture_bound_as_emissive",
    "source_spec_gloss_texture_bound_as_base",
    "source_material_response_texture_bound_as_base",
    "source_base_texture_bound_as_normal",
}
_MAX_EXAMPLES_PER_RISK = 8


def resolve_external_model_audit_report_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        return candidate / EXTERNAL_MODEL_AUDIT_REPORT_FILENAME
    return candidate


def load_external_model_audit_report(path: str | Path) -> Mapping[str, object]:
    report_path = resolve_external_model_audit_report_path(path)
    with report_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"External model audit report is not a JSON object: {report_path}")
    return data


def check_external_model_audit_report(
    report: Mapping[str, object],
    *,
    fail_on_risk_flags: Sequence[str] = DEFAULT_BLOCKING_RISK_FLAGS,
    allowed_risk_flags: Sequence[str] = DEFAULT_ALLOWED_RISK_FLAGS,
) -> dict[str, object]:
    source_risk_flags = tuple(str(flag) for flag in tuple(report.get("risk_flags", ()) or ()) if str(flag).strip())
    derived_risk_flags: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    examples: dict[str, list[dict[str, object]]] = {}

    schema_version = report.get("schema_version")
    if schema_version != 1:
        errors.append(f"Unsupported external model audit schema_version: {schema_version or '<missing>'}.")
    tool = str(report.get("tool", "") or "")
    if tool != "external_model_audit_catalogue":
        errors.append(f"Unsupported external model audit tool: {tool or '<missing>'}.")

    roots = tuple(str(root) for root in tuple(report.get("roots", ()) or ()) if str(root).strip())
    models = tuple(model for model in tuple(report.get("models", ()) or ()) if isinstance(model, Mapping))

    status_counts: Counter[str] = Counter()
    texture_slot_counts: Counter[str] = Counter()
    texture_format_counts: Counter[str] = Counter()
    texture_color_space_counts: Counter[str] = Counter()
    material_class_counts: Counter[str] = Counter()
    pbr_workflow_counts: Counter[str] = Counter()
    detected_channel_counts: Counter[str] = Counter()
    missing_channel_counts: Counter[str] = Counter()
    channel_diagnostic_counts: Counter[str] = Counter()

    failed_models = 0
    audited_model_without_material_inventory = 0
    metadata_only_inventory_rows = 0
    archive_indexed_with_audit_members = 0
    zip_content_audit_skipped_by_limit = 0
    missing_texture_refs = 0
    ambiguous_texture_refs = 0
    unresolved_texture_candidates = 0
    material_inventory_rows = 0
    material_class_rows = 0
    materials_missing_classes = 0
    materials_missing_workflow = 0
    materials_missing_channel_diagnostics = 0
    materials_without_texture_slots = 0
    materials_missing_texture_facts = 0
    texture_slot_rows = 0
    texture_slots_missing_resolution = 0
    texture_slots_missing_format = 0
    texture_slots_missing_color_space = 0
    texture_slots_missing_channel_stats = 0
    material_section_rows = 0
    materials_missing_sections = 0
    sections_missing_geometry = 0
    sections_missing_uvs = 0
    sections_missing_normals = 0
    section_vertex_count = 0
    section_face_count = 0
    materials_missing_alpha_diagnostics = 0
    materials_missing_emissive_diagnostics = 0
    materials_missing_roughness_metalness_diagnostics = 0
    source_texture_route_mismatches = 0

    if not models:
        derived_risk_flags.append("missing_models")
        warnings.append("External model audit has no model rows.")

    for model in models:
        status = str(model.get("audit_status", "") or "unknown").strip() or "unknown"
        status_counts[status] += 1
        if status in _FAILED_STATUSES:
            failed_models += 1
            _append_example(examples, "failed_models", _model_example(model))

        row_missing_refs = len(tuple(model.get("missing_texture_refs", ()) or ()))
        row_ambiguous_refs = len(tuple(model.get("ambiguous_texture_refs", ()) or ()))
        missing_texture_refs += row_missing_refs
        ambiguous_texture_refs += row_ambiguous_refs
        unresolved_texture_candidates += len(tuple(model.get("unresolved_texture_candidates", ()) or ()))
        for missing_ref in tuple(model.get("missing_texture_refs", ()) or ()):
            _append_example(examples, "missing_texture_refs", {**_model_example(model), "texture_ref": str(missing_ref)})
        for ambiguous_ref in tuple(model.get("ambiguous_texture_refs", ()) or ()):
            _append_example(examples, "ambiguous_texture_refs", {**_model_example(model), "texture_ref": str(ambiguous_ref)})
        for candidate in tuple(model.get("unresolved_texture_candidates", ()) or ()):
            _append_example(
                examples,
                "unresolved_texture_candidates",
                {**_model_example(model), **_compact_mapping(candidate, fallback_key="candidate")},
            )

        if status == "archive_indexed" and tuple(model.get("zip_audit_members", ()) or ()):
            archive_indexed_with_audit_members += 1
            _append_example(
                examples,
                "archive_content_not_audited",
                {
                    **_model_example(model),
                    "zip_audit_members": list(tuple(model.get("zip_audit_members", ()) or ())[:4]),
                },
            )
        if bool(model.get("zip_content_audit_skipped")):
            zip_content_audit_skipped_by_limit += 1
            _append_example(
                examples,
                "zip_audit_limit_skipped",
                {
                    **_model_example(model),
                    "skip_reason": str(model.get("zip_content_audit_skip_reason", "") or ""),
                },
            )

        inventory = tuple(material for material in tuple(model.get("material_inventory", ()) or ()) if isinstance(material, Mapping))
        import_supported = bool(model.get("import_supported", True))
        if status in _AUDITED_STATUSES and import_supported and not inventory:
            audited_model_without_material_inventory += 1
            _append_example(examples, "audited_model_without_material_inventory", _model_example(model))
        if inventory and (status in _METADATA_ONLY_STATUSES or (status == "archive_audited" and not bool(model.get("import_supported")))):
            metadata_only_inventory_rows += len(inventory)
            for material in inventory:
                _append_example(examples, "metadata_only_inventory", _material_example(model, material))

        geometry_required = status in _AUDITED_STATUSES and import_supported
        for material in inventory:
            material_inventory_rows += 1
            workflow = str(material.get("pbr_workflow", "") or "").strip()
            if workflow:
                pbr_workflow_counts[workflow] += 1
            else:
                materials_missing_workflow += 1
                _append_example(examples, "missing_pbr_workflow", _material_example(model, material))

            material_classes = tuple(item for item in tuple(material.get("material_classes", ()) or ()) if isinstance(item, Mapping))
            if material_classes:
                material_class_rows += len(material_classes)
                for item in material_classes:
                    class_name = str(item.get("material_class", "") or "").strip()
                    if class_name:
                        material_class_counts[class_name] += 1
            else:
                materials_missing_classes += 1
                _append_example(examples, "missing_material_classes", _material_example(model, material))

            detected_channels = _source_channel_values(material.get("detected_channels"))
            missing_channels = _source_channel_values(material.get("missing_channels"))
            diagnostic_codes = _diagnostic_codes(material.get("channel_diagnostics"))
            detected_channel_counts.update(detected_channels)
            missing_channel_counts.update(missing_channels)
            channel_diagnostic_counts.update(diagnostic_codes)
            source_texture_route_mismatches += len(diagnostic_codes & _SOURCE_TEXTURE_ROUTE_MISMATCH_CODES)
            for diagnostic in tuple(material.get("channel_diagnostics", ()) or ()):
                if not isinstance(diagnostic, Mapping):
                    continue
                diagnostic_code = str(diagnostic.get("code", "") or "").strip()
                if diagnostic_code not in _SOURCE_TEXTURE_ROUTE_MISMATCH_CODES:
                    continue
                _append_example(
                    examples,
                    "source_texture_route_mismatch",
                    {
                        **_material_example(model, material),
                        "code": diagnostic_code,
                        "message": str(diagnostic.get("message", "") or ""),
                        "texture_path": str(diagnostic.get("texture_path", "") or diagnostic.get("texture_name", "") or ""),
                        "slot_kind": str(diagnostic.get("slot_kind", "") or ""),
                    },
                )

            texture_slots = tuple(slot for slot in tuple(material.get("texture_slots", ()) or ()) if isinstance(slot, Mapping))
            if not texture_slots:
                materials_without_texture_slots += 1
                if not _material_has_scalar_or_channel_evidence(material, detected_channels, missing_channels, diagnostic_codes):
                    materials_missing_texture_facts += 1
                    _append_example(examples, "missing_texture_slot_facts", _material_example(model, material))
            if (
                not isinstance(material.get("channel_profile"), Mapping)
                and not detected_channels
                and not missing_channels
                and not diagnostic_codes
            ):
                materials_missing_channel_diagnostics += 1
                _append_example(examples, "missing_channel_diagnostics", _material_example(model, material))

            for slot in texture_slots:
                texture_slot_rows += 1
                slot_kind = str(slot.get("slot_kind", "") or "").strip()
                if slot_kind:
                    texture_slot_counts[slot_kind] += 1
                image_format = str(slot.get("image_format", "") or "").strip().lower()
                if image_format:
                    texture_format_counts[image_format] += 1
                else:
                    texture_slots_missing_format += 1
                    _append_example(examples, "texture_missing_format", _texture_slot_example(model, material, slot))
                color_space = str(slot.get("color_space", "") or "").strip().lower()
                if color_space:
                    texture_color_space_counts[color_space] += 1
                else:
                    texture_slots_missing_color_space += 1
                    _append_example(examples, "texture_missing_color_space", _texture_slot_example(model, material, slot))
                if not _valid_resolution(slot.get("resolution")):
                    texture_slots_missing_resolution += 1
                    _append_example(examples, "texture_missing_resolution", _texture_slot_example(model, material, slot))
                if not tuple(slot.get("channel_stats", ()) or ()):
                    texture_slots_missing_channel_stats += 1
                    _append_example(examples, "texture_missing_channel_stats", _texture_slot_example(model, material, slot))

            if geometry_required:
                sections = tuple(section for section in tuple(material.get("sections", ()) or ()) if isinstance(section, Mapping))
                if not sections:
                    materials_missing_sections += 1
                    _append_example(examples, "material_missing_sections", _material_example(model, material))
                for section in sections:
                    material_section_rows += 1
                    vertex_count = _report_int(section.get("vertex_count"), 0)
                    face_count = _report_int(section.get("face_count"), 0)
                    section_vertex_count += vertex_count
                    section_face_count += face_count
                    if vertex_count <= 0 or face_count <= 0:
                        sections_missing_geometry += 1
                        _append_example(examples, "section_missing_geometry", _section_example(model, material, section))
                    if not bool(section.get("has_uvs")):
                        sections_missing_uvs += 1
                        _append_example(examples, "section_missing_uvs", _section_example(model, material, section))
                    if not bool(section.get("has_normals")):
                        sections_missing_normals += 1
                        _append_example(examples, "section_missing_normals", _section_example(model, material, section))

            if _source_alpha_relevant(material, detected_channels, missing_channels, diagnostic_codes, texture_slots) and not _source_channel_has_evidence(
                detected_channels,
                missing_channels,
                diagnostic_codes,
                texture_slots,
                ("alpha", "opacity"),
            ):
                materials_missing_alpha_diagnostics += 1
                _append_example(examples, "missing_alpha_diagnostics", _material_example(model, material))
            if not _source_channel_has_evidence(
                detected_channels,
                missing_channels,
                diagnostic_codes,
                texture_slots,
                ("emissive",),
            ):
                materials_missing_emissive_diagnostics += 1
                _append_example(examples, "missing_emissive_diagnostics", _material_example(model, material))
            if not (
                (
                    _source_channel_has_evidence(
                        detected_channels,
                        missing_channels,
                        diagnostic_codes,
                        texture_slots,
                        ("roughness",),
                    )
                    and _source_channel_has_evidence(
                        detected_channels,
                        missing_channels,
                        diagnostic_codes,
                        texture_slots,
                        ("metalness",),
                    )
                )
                or _source_channel_has_evidence(
                    detected_channels,
                    missing_channels,
                    diagnostic_codes,
                    texture_slots,
                    ("specular", "glossiness"),
                )
            ):
                materials_missing_roughness_metalness_diagnostics += 1
                _append_example(examples, "missing_roughness_metalness_diagnostics", _material_example(model, material))

    _append_count_flag(derived_risk_flags, warnings, failed_models, "failed_models", "model audit row(s) failed")
    _append_count_flag(
        derived_risk_flags,
        warnings,
        audited_model_without_material_inventory,
        "audited_model_without_material_inventory",
        "audited/importable model row(s) lack material inventory",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        archive_indexed_with_audit_members,
        "archive_content_not_audited",
        "archive row(s) contain auditable model members but were not content-audited",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        zip_content_audit_skipped_by_limit,
        "zip_audit_limit_skipped",
        "ZIP content audit row(s) were skipped by limit",
    )
    _append_count_flag(derived_risk_flags, warnings, metadata_only_inventory_rows, "metadata_only_inventory", "material inventory row(s) are metadata-only")
    _append_count_flag(derived_risk_flags, warnings, missing_texture_refs, "missing_texture_refs", "referenced texture path(s) are missing")
    _append_count_flag(derived_risk_flags, warnings, ambiguous_texture_refs, "ambiguous_texture_refs", "texture role reference(s) are ambiguous")
    _append_count_flag(
        derived_risk_flags,
        warnings,
        unresolved_texture_candidates,
        "unresolved_texture_candidates",
        "nearby texture candidate(s) are available for missing references",
    )
    _append_count_flag(derived_risk_flags, warnings, materials_missing_classes, "missing_material_classes", "material row(s) lack classifier output")
    _append_count_flag(derived_risk_flags, warnings, materials_missing_workflow, "missing_pbr_workflow", "material row(s) lack PBR workflow evidence")
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_channel_diagnostics,
        "missing_channel_diagnostics",
        "material row(s) lack source channel diagnostics",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_texture_facts,
        "missing_texture_slot_facts",
        "material row(s) lack texture slot facts",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        texture_slots_missing_resolution,
        "texture_missing_resolution",
        "texture slot row(s) lack resolution evidence",
    )
    _append_count_flag(derived_risk_flags, warnings, texture_slots_missing_format, "texture_missing_format", "texture slot row(s) lack image format")
    _append_count_flag(
        derived_risk_flags,
        warnings,
        texture_slots_missing_color_space,
        "texture_missing_color_space",
        "texture slot row(s) lack color-space classification",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        texture_slots_missing_channel_stats,
        "texture_missing_channel_stats",
        "texture slot row(s) lack channel statistics",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_sections,
        "material_missing_sections",
        "importable audited material row(s) lack mesh section evidence",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        sections_missing_geometry,
        "section_missing_geometry",
        "material section row(s) lack geometry counts",
    )
    _append_count_flag(derived_risk_flags, warnings, sections_missing_uvs, "section_missing_uvs", "material section row(s) lack UV evidence")
    _append_count_flag(
        derived_risk_flags,
        warnings,
        sections_missing_normals,
        "section_missing_normals",
        "material section row(s) lack normal evidence",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_alpha_diagnostics,
        "missing_alpha_diagnostics",
        "alpha-relevant material row(s) lack alpha diagnostics",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_emissive_diagnostics,
        "missing_emissive_diagnostics",
        "material row(s) lack emissive present/missing evidence",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        materials_missing_roughness_metalness_diagnostics,
        "missing_roughness_metalness_diagnostics",
        "material row(s) lack roughness/metalness or spec/gloss evidence",
    )
    _append_count_flag(
        derived_risk_flags,
        warnings,
        source_texture_route_mismatches,
        "source_texture_route_mismatch",
        "source texture slot-route mismatch diagnostic(s) need review",
    )

    all_risk_flags = tuple(_dedupe_text((*source_risk_flags, *derived_risk_flags)))
    allowed_flags = set(_dedupe_text(allowed_risk_flags))
    blocking_flags = tuple(flag for flag in all_risk_flags if flag in set(fail_on_risk_flags) and flag not in allowed_flags)
    if blocking_flags:
        errors.append("Blocking external model audit risk flag(s): " + ", ".join(blocking_flags))
    review_flags = tuple(flag for flag in all_risk_flags if flag in set(REVIEW_RISK_FLAGS) and flag not in blocking_flags and flag not in allowed_flags)
    for flag in review_flags:
        warnings.append(f"Review external model audit risk flag: {flag}.")
    allowed_present = tuple(flag for flag in all_risk_flags if flag in allowed_flags)

    status = "failed" if errors else "needs_review" if review_flags else "passed"
    return {
        "schema": EXTERNAL_MODEL_AUDIT_CHECK_SCHEMA,
        "status": status,
        "source_report_schema_version": schema_version,
        "source_tool": tool,
        "roots": list(roots),
        "audit_zip_contents": bool(report.get("audit_zip_contents")),
        "risk_flags": list(all_risk_flags),
        "source_risk_flags": list(source_risk_flags),
        "derived_risk_flags": _dedupe_text(derived_risk_flags),
        "allowed_risk_flags": list(allowed_present),
        "blocking_risk_flags": list(blocking_flags),
        "review_risk_flags": list(review_flags),
        "counts": {
            "total_models": len(models),
            "audited_models": status_counts.get("audited", 0),
            "zip_audited_models": status_counts.get("archive_audited", 0),
            "archive_models": status_counts.get("archive_indexed", 0),
            "metadata_inferred_models": status_counts.get("browsable_material_inferred", 0),
            "unsupported_models": status_counts.get("browsable_unsupported", 0),
            "failed_models": failed_models,
            "audited_model_without_material_inventory": audited_model_without_material_inventory,
            "archive_indexed_with_audit_members": archive_indexed_with_audit_members,
            "zip_content_audit_skipped_by_limit": zip_content_audit_skipped_by_limit,
            "missing_texture_refs": missing_texture_refs,
            "ambiguous_texture_refs": ambiguous_texture_refs,
            "unresolved_texture_candidates": unresolved_texture_candidates,
            "material_inventory_rows": material_inventory_rows,
            "metadata_only_inventory_rows": metadata_only_inventory_rows,
            "material_class_rows": material_class_rows,
            "materials_missing_classes": materials_missing_classes,
            "materials_missing_workflow": materials_missing_workflow,
            "materials_missing_channel_diagnostics": materials_missing_channel_diagnostics,
            "materials_without_texture_slots": materials_without_texture_slots,
            "materials_missing_texture_facts": materials_missing_texture_facts,
            "texture_slot_rows": texture_slot_rows,
            "texture_slots_missing_resolution": texture_slots_missing_resolution,
            "texture_slots_missing_format": texture_slots_missing_format,
            "texture_slots_missing_color_space": texture_slots_missing_color_space,
            "texture_slots_missing_channel_stats": texture_slots_missing_channel_stats,
            "material_section_rows": material_section_rows,
            "materials_missing_sections": materials_missing_sections,
            "sections_missing_geometry": sections_missing_geometry,
            "sections_missing_uvs": sections_missing_uvs,
            "sections_missing_normals": sections_missing_normals,
            "section_vertex_count": section_vertex_count,
            "section_face_count": section_face_count,
            "materials_missing_alpha_diagnostics": materials_missing_alpha_diagnostics,
            "materials_missing_emissive_diagnostics": materials_missing_emissive_diagnostics,
            "materials_missing_roughness_metalness_diagnostics": materials_missing_roughness_metalness_diagnostics,
            "source_texture_route_mismatches": source_texture_route_mismatches,
            "status_counts": dict(sorted(status_counts.items())),
            "texture_slot_counts": dict(sorted(texture_slot_counts.items())),
            "texture_format_counts": dict(sorted(texture_format_counts.items())),
            "texture_color_space_counts": dict(sorted(texture_color_space_counts.items())),
            "pbr_workflow_counts": dict(sorted(pbr_workflow_counts.items())),
            "material_class_counts": dict(sorted(material_class_counts.items())),
            "source_detected_channels": dict(sorted(detected_channel_counts.items())),
            "source_missing_channels": dict(sorted(missing_channel_counts.items())),
            "source_channel_diagnostics": dict(sorted(channel_diagnostic_counts.items())),
        },
        "examples": {key: value for key, value in sorted(examples.items()) if value},
        "errors": _dedupe_text(errors),
        "warnings": _dedupe_text(warnings),
    }


def check_external_model_audit_report_path(
    path: str | Path,
    *,
    fail_on_risk_flags: Sequence[str] = DEFAULT_BLOCKING_RISK_FLAGS,
    allowed_risk_flags: Sequence[str] = DEFAULT_ALLOWED_RISK_FLAGS,
) -> dict[str, object]:
    return check_external_model_audit_report(
        load_external_model_audit_report(path),
        fail_on_risk_flags=fail_on_risk_flags,
        allowed_risk_flags=allowed_risk_flags,
    )


def _append_example(examples: dict[str, list[dict[str, object]]], key: str, payload: Mapping[str, object]) -> None:
    clean_key = str(key or "").strip()
    if not clean_key:
        return
    rows = examples.setdefault(clean_key, [])
    if len(rows) >= _MAX_EXAMPLES_PER_RISK:
        return
    clean_payload = {
        str(item_key): _json_safe_example_value(item_value)
        for item_key, item_value in dict(payload or {}).items()
        if str(item_key or "").strip() and _example_value_present(item_value)
    }
    if clean_payload:
        rows.append(clean_payload)


def _model_example(model: Mapping[str, object]) -> dict[str, object]:
    return {
        "path": str(
            model.get("zip_audited_member", "")
            or model.get("path", "")
            or model.get("relative_path", "")
            or ""
        ),
        "audit_status": str(model.get("audit_status", "") or ""),
    }


def _material_example(model: Mapping[str, object], material: Mapping[str, object]) -> dict[str, object]:
    return {
        **_model_example(model),
        "material_name": str(material.get("material_name", "") or ""),
        "material_index": _report_int(material.get("material_index"), -1),
        "pbr_workflow": str(material.get("pbr_workflow", "") or ""),
    }


def _texture_slot_example(
    model: Mapping[str, object],
    material: Mapping[str, object],
    slot: Mapping[str, object],
) -> dict[str, object]:
    return {
        **_material_example(model, material),
        "slot_kind": str(slot.get("slot_kind", "") or ""),
        "texture_name": str(slot.get("texture_name", "") or ""),
        "texture_path": str(slot.get("texture_path", "") or ""),
        "source": str(slot.get("source", "") or ""),
        "confidence": str(slot.get("confidence", "") or ""),
    }


def _section_example(
    model: Mapping[str, object],
    material: Mapping[str, object],
    section: Mapping[str, object],
) -> dict[str, object]:
    return {
        **_material_example(model, material),
        "section_name": str(section.get("section_name", "") or ""),
        "vertex_count": _report_int(section.get("vertex_count"), 0),
        "face_count": _report_int(section.get("face_count"), 0),
        "has_uvs": bool(section.get("has_uvs")),
        "has_normals": bool(section.get("has_normals")),
    }


def _compact_mapping(value: object, *, fallback_key: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for key in (
            "wanted_slot",
            "slot_kind",
            "texture_name",
            "texture_path",
            "candidate",
            "candidate_path",
            "confidence",
            "missing_ref",
            "archive_member",
        ):
            if key in value and _example_value_present(value.get(key)):
                output[key] = _json_safe_example_value(value.get(key))
        if output:
            return output
    return {fallback_key: str(value)}


def _example_value_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _json_safe_example_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_example_value(item)
            for key, item in value.items()
            if str(key or "").strip() and _example_value_present(item)
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_example_value(item) for item in value if _example_value_present(item)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _append_count_flag(
    risk_flags: list[str],
    warnings: list[str],
    count: int,
    flag: str,
    message: str,
) -> None:
    if count <= 0:
        return
    risk_flags.append(flag)
    warnings.append(f"{count:,} {message}.")


def _source_channel_values(values: object) -> set[str]:
    return {
        str(value or "").strip().lower()
        for value in tuple(values or ())
        if str(value or "").strip()
    }


def _material_has_scalar_or_channel_evidence(
    material: Mapping[str, object],
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
) -> bool:
    if detected_channels or missing_channels or diagnostic_codes:
        return True
    scalar_hints = material.get("scalar_hints")
    if isinstance(scalar_hints, Mapping) and scalar_hints:
        return True
    for key in ("color_factor", "vertex_color_factor", "emissive_color", "vertex_alpha"):
        if tuple(material.get(key, ()) or ()):
            return True
    return False


def _diagnostic_codes(values: object) -> set[str]:
    codes: set[str] = set()
    for value in tuple(values or ()):
        if not isinstance(value, Mapping):
            continue
        code = str(value.get("code", "") or "").strip().lower()
        if code:
            codes.add(code)
    return codes


def _valid_resolution(value: object) -> bool:
    resolution = tuple(value or ())
    if len(resolution) < 2:
        return False
    return _report_int(resolution[0], 0) > 0 and _report_int(resolution[1], 0) > 0


def _source_alpha_relevant(
    material: Mapping[str, object],
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
    texture_slots: Sequence[Mapping[str, object]],
) -> bool:
    alpha_mode = str(material.get("alpha_mode", "") or "").strip().lower()
    if alpha_mode in _ALPHA_MODES:
        return True
    if {"alpha", "opacity"}.intersection(detected_channels | missing_channels):
        return True
    if any("alpha" in code or "opacity" in code for code in diagnostic_codes):
        return True
    for item in tuple(material.get("material_classes", ()) or ()):
        if isinstance(item, Mapping) and str(item.get("material_class", "") or "").strip().lower() in {"glass", "crystal", "glass_crystal"}:
            return True
    vertex_alpha = tuple(material.get("vertex_alpha", ()) or ())
    if len(vertex_alpha) >= 2 and (_report_float(vertex_alpha[0], 1.0) < 0.98 or _report_float(vertex_alpha[1], 1.0) < 0.98):
        return True
    for slot in texture_slots:
        if _slot_has_channel_evidence(slot, ("alpha", "opacity")):
            return True
        if _slot_visible_alpha_relevant(slot):
            return True
    return False


def _source_channel_has_evidence(
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
    texture_slots: Sequence[Mapping[str, object]],
    channels: Sequence[str],
) -> bool:
    wanted = {str(channel or "").strip().lower() for channel in tuple(channels or ()) if str(channel or "").strip()}
    if wanted.intersection(detected_channels | missing_channels):
        return True
    for channel in wanted:
        if f"{channel}_scalar" in detected_channels:
            return True
        if any(channel in code for code in diagnostic_codes):
            return True
    return any(_slot_has_channel_evidence(slot, tuple(wanted)) for slot in texture_slots)


def _slot_has_channel_evidence(slot: Mapping[str, object], channels: Sequence[str]) -> bool:
    wanted = {str(channel or "").strip().lower() for channel in tuple(channels or ()) if str(channel or "").strip()}
    if not wanted:
        return False
    values: list[str] = [
        str(slot.get("slot_kind", "") or ""),
        str(slot.get("parameter_name", "") or ""),
        str(slot.get("semantic_type", "") or ""),
        str(slot.get("semantic_subtype", "") or ""),
        str(slot.get("texture_name", "") or ""),
        str(slot.get("texture_path", "") or ""),
    ]
    values.extend(str(value or "") for value in tuple(slot.get("packed_channels", ()) or ()))
    text = " ".join(values).replace("\\", "/").lower()
    aliases = {
        "base_color": ("base", "basecolor", "albedo", "diffuse", "color"),
        "alpha": ("alpha", "opacity", "transparent"),
        "opacity": ("alpha", "opacity", "transparent"),
        "roughness": ("rough", "roughness", "smoothness"),
        "metalness": ("metal", "metallic", "metalness"),
        "specular": ("specular", "spec"),
        "glossiness": ("gloss", "glossiness", "specgloss"),
        "emissive": ("emissive", "emission", "glow", "illum"),
    }
    for channel in wanted:
        for token in aliases.get(channel, (channel,)):
            if token in text:
                return True
    return False


def _slot_visible_alpha_relevant(slot: Mapping[str, object]) -> bool:
    stats = dict(tuple(slot.get("channel_stats", ()) or ()))
    if _report_float(stats.get("a_min"), 1.0) >= 0.999 and _report_float(stats.get("a_mean"), 1.0) >= 0.999:
        return False
    slot_kind = str(slot.get("slot_kind", "") or "").strip().lower()
    semantic_type = str(slot.get("semantic_type", "") or "").strip().lower()
    semantic_subtype = str(slot.get("semantic_subtype", "") or "").strip().lower()
    parameter_name = str(slot.get("parameter_name", "") or "").strip().lower()
    packed_channels = tuple(slot.get("packed_channels", ()) or ())
    text = " ".join((slot_kind, semantic_type, semantic_subtype, parameter_name))
    if any(token in text for token in ("opacity", "alpha", "transparent")):
        return True
    if slot_kind in {"base", "diffuse", "albedo", "emissive"} or semantic_type in {"base", "base_color", "emissive"}:
        return True
    if packed_channels or slot_kind in {"roughness", "metalness", "material", "specular", "occlusion", "ao", "normal", "height"}:
        return False
    return False


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
    "DEFAULT_ALLOWED_RISK_FLAGS",
    "DEFAULT_BLOCKING_RISK_FLAGS",
    "EXTERNAL_MODEL_AUDIT_CHECK_SCHEMA",
    "EXTERNAL_MODEL_AUDIT_REPORT_FILENAME",
    "REVIEW_RISK_FLAGS",
    "SOURCE_DATA_RISK_FLAGS",
    "check_external_model_audit_report",
    "check_external_model_audit_report_path",
    "load_external_model_audit_report",
    "resolve_external_model_audit_report_path",
]
