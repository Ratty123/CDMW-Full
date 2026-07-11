from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Mapping


def _hkx_xml_add_real_hkclass_metadata_v2(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    real_hkclass_metadata_v2 = document.get("real_hkclass_metadata_v2")
    if isinstance(real_hkclass_metadata_v2, Mapping) and real_hkclass_metadata_v2:
        metadata_element = ET.SubElement(
            root,
            "realHkclassMetadataV2",
            {
                "format": str(real_hkclass_metadata_v2.get("format") or ""),
                "status": str(real_hkclass_metadata_v2.get("status") or ""),
                "read_only": "true",
                "class_count": hkx._hkx_xml_scalar(real_hkclass_metadata_v2.get("class_count")),
                "member_count": hkx._hkx_xml_scalar(real_hkclass_metadata_v2.get("member_count")),
                "enum_count": hkx._hkx_xml_scalar(real_hkclass_metadata_v2.get("enum_count")),
                "synthetic_fallback_required": hkx._hkx_xml_scalar(
                    real_hkclass_metadata_v2.get("synthetic_fallback_required")
                ),
            },
        )
        classes = real_hkclass_metadata_v2.get("classes")
        if isinstance(classes, list):
            classes_element = ET.SubElement(metadata_element, "classes")
            for class_info in classes[:256]:
                if not isinstance(class_info, Mapping):
                    continue
                class_element = ET.SubElement(
                    classes_element,
                    "class",
                    {
                        "name": str(class_info.get("class_name") or class_info.get("name") or ""),
                        "record_index": hkx._hkx_xml_scalar(class_info.get("record_index")),
                        "base_class": str(class_info.get("base_class") or ""),
                        "object_size": hkx._hkx_xml_scalar(class_info.get("object_size")),
                        "version": hkx._hkx_xml_scalar(class_info.get("version")),
                        "signature_hex": str(class_info.get("signature_hex") or ""),
                        "metadata_source": str(class_info.get("metadata_source") or ""),
                        "confidence": str(class_info.get("confidence") or ""),
                    },
                )
                members = class_info.get("members")
                if isinstance(members, list) and members:
                    members_element = ET.SubElement(class_element, "members")
                    for member in members[:256]:
                        if not isinstance(member, Mapping):
                            continue
                        ET.SubElement(
                            members_element,
                            "member",
                            {
                                "name": str(member.get("name") or member.get("member_name") or ""),
                                "offset": hkx._hkx_xml_scalar(member.get("offset")),
                                "offset_hex": str(member.get("offset_hex") or ""),
                                "havok_member_type_code": hkx._hkx_xml_scalar(
                                    member.get("havok_member_type_code") or member.get("member_type_code")
                                ),
                                "member_type_name": str(member.get("member_type_name") or ""),
                                "subtype_name": str(member.get("subtype_name") or ""),
                                "flags_hex": str(member.get("flags_hex") or ""),
                                "array_status": str(member.get("array_status") or ""),
                                "reference_status": str(member.get("reference_status") or ""),
                                "class_ref_name": str(member.get("class_ref_name") or ""),
                                "enum_ref_name": str(member.get("enum_ref_name") or ""),
                                "template_ref": str(member.get("template_ref") or ""),
                                "confidence": str(member.get("confidence") or ""),
                                "editable": "false",
                            },
                        )


def _hkx_xml_add_fixup_semantics_v2(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    fixup_semantics_v2 = document.get("fixup_semantics_v2")
    if isinstance(fixup_semantics_v2, Mapping) and fixup_semantics_v2:
        fixup_v2_element = ET.SubElement(
            root,
            "fixupSemanticsV2",
            {
                "format": str(fixup_semantics_v2.get("format") or ""),
                "status": str(fixup_semantics_v2.get("status") or ""),
                "read_only": "true",
                "patch_site_count": hkx._hkx_xml_scalar(fixup_semantics_v2.get("patch_site_count")),
                "resolved_patch_site_count": hkx._hkx_xml_scalar(fixup_semantics_v2.get("resolved_patch_site_count")),
                "unresolved_patch_site_count": hkx._hkx_xml_scalar(
                    fixup_semantics_v2.get("unresolved_patch_site_count")
                ),
            },
        )
        bucket_counts = fixup_semantics_v2.get("semantic_bucket_counts")
        if isinstance(bucket_counts, Mapping):
            buckets_element = ET.SubElement(fixup_v2_element, "semanticBuckets")
            for bucket, count in sorted(bucket_counts.items()):
                ET.SubElement(
                    buckets_element,
                    "bucket",
                    {"name": str(bucket), "count": hkx._hkx_xml_scalar(count)},
                )
        bucket_taxonomy = fixup_semantics_v2.get("semantic_bucket_taxonomy")
        if isinstance(bucket_taxonomy, list):
            taxonomy_element = ET.SubElement(fixup_v2_element, "semanticBucketTaxonomy")
            for row in bucket_taxonomy:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    taxonomy_element,
                    "bucket",
                    {
                        "name": str(row.get("bucket") or ""),
                        "meaning": str(row.get("meaning") or ""),
                        "edit_policy": str(row.get("edit_policy") or ""),
                    },
                )
        corpus_counters = fixup_semantics_v2.get("corpus_evidence_counters")
        if isinstance(corpus_counters, Mapping):
            counters_element = ET.SubElement(fixup_v2_element, "corpusEvidenceCounters")
            for key, value in sorted(corpus_counters.items()):
                ET.SubElement(
                    counters_element,
                    "counter",
                    {"name": str(key), "value": hkx._hkx_xml_scalar(value)},
                )
        patch_sites = fixup_semantics_v2.get("patch_sites")
        if isinstance(patch_sites, list) and patch_sites:
            patch_sites_element = ET.SubElement(fixup_v2_element, "patchSites", {"truncated_after": "512"})
            for site in patch_sites[:512]:
                if not isinstance(site, Mapping):
                    continue
                ET.SubElement(
                    patch_sites_element,
                    "patchSite",
                    {
                        "index": hkx._hkx_xml_scalar(site.get("index")),
                        "section": str(site.get("section") or ""),
                        "tuple_shape": str(site.get("tuple_shape") or ""),
                        "owner_record_index": hkx._hkx_xml_scalar(site.get("owner_record_index")),
                        "owner_local_offset": hkx._hkx_xml_scalar(site.get("owner_local_offset")),
                        "patched_slot_value": hkx._hkx_xml_scalar(site.get("patched_slot_value")),
                        "target_record_index": hkx._hkx_xml_scalar(site.get("target_record_index")),
                        "target_status": str(site.get("target_status") or ""),
                        "semantic_bucket": str(site.get("semantic_bucket") or ""),
                        "reference_category": str(site.get("reference_category") or ""),
                        "confidence": str(site.get("confidence") or ""),
                    },
                )


def _hkx_xml_add_semantic_model_v1(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    semantic_model_v1 = document.get("semantic_model_v1")
    if isinstance(semantic_model_v1, Mapping) and semantic_model_v1:
        semantic_element = ET.SubElement(
            root,
            "semanticModelV1",
            {
                "format": str(semantic_model_v1.get("format") or ""),
                "status": str(semantic_model_v1.get("status") or ""),
                "read_only": "true",
                "object_count": hkx._hkx_xml_scalar(semantic_model_v1.get("object_count")),
                "field_count": hkx._hkx_xml_scalar(semantic_model_v1.get("field_count")),
                "raw_fallback_count": hkx._hkx_xml_scalar(semantic_model_v1.get("raw_fallback_count")),
                "root_record_index": hkx._hkx_xml_scalar(semantic_model_v1.get("root_record_index")),
                "root_type_name": str(semantic_model_v1.get("root_type_name") or ""),
            },
        )
        objects = semantic_model_v1.get("objects")
        source_priority = semantic_model_v1.get("source_priority")
        if isinstance(source_priority, list):
            priority_element = ET.SubElement(semantic_element, "sourcePriority")
            for source_name in source_priority:
                hkx._hkx_xml_add_text(priority_element, "source", source_name)
        field_kind_taxonomy = semantic_model_v1.get("field_kind_taxonomy")
        if isinstance(field_kind_taxonomy, list):
            taxonomy_element = ET.SubElement(semantic_element, "fieldKindTaxonomy")
            for kind in field_kind_taxonomy:
                hkx._hkx_xml_add_text(taxonomy_element, "kind", kind)
        if isinstance(objects, list) and objects:
            objects_element = ET.SubElement(semantic_element, "objects", {"truncated_after": "256"})
            for object_info in objects[:256]:
                if not isinstance(object_info, Mapping):
                    continue
                object_element = ET.SubElement(
                    objects_element,
                    "object",
                    {
                        "record_index": hkx._hkx_xml_scalar(object_info.get("record_index")),
                        "type_name": str(object_info.get("type_name") or ""),
                        "status": str(object_info.get("status") or ""),
                        "class_metadata_source": str(object_info.get("class_metadata_source") or ""),
                        "semantic_source": str(object_info.get("semantic_source") or object_info.get("class_metadata_source") or ""),
                        "field_count": hkx._hkx_xml_scalar(object_info.get("field_count")),
                        "reference_count": hkx._hkx_xml_scalar(object_info.get("reference_count")),
                        "raw_span_count": hkx._hkx_xml_scalar(object_info.get("raw_span_count")),
                        "byte_range_start": hkx._hkx_xml_scalar(object_info.get("byte_range_start")),
                        "byte_range_end": hkx._hkx_xml_scalar(object_info.get("byte_range_end")),
                    },
                )
                fields = object_info.get("fields")
                if isinstance(fields, list) and fields:
                    fields_element = ET.SubElement(object_element, "fields", {"truncated_after": "128"})
                    for field in fields[:128]:
                        if not isinstance(field, Mapping):
                            continue
                        ET.SubElement(
                            fields_element,
                            "field",
                            {
                                "name": str(field.get("name") or ""),
                                "kind": str(field.get("kind") or ""),
                                "offset": hkx._hkx_xml_scalar(field.get("offset")),
                                "offset_hex": str(field.get("offset_hex") or ""),
                                "size": hkx._hkx_xml_scalar(field.get("size")),
                                "byte_range_start": hkx._hkx_xml_scalar(field.get("byte_range_start")),
                                "byte_range_end": hkx._hkx_xml_scalar(field.get("byte_range_end")),
                                "data_type": str(field.get("data_type") or ""),
                                "confidence": str(field.get("confidence") or ""),
                                "editable_candidate": hkx._hkx_xml_scalar(field.get("editable_candidate")),
                                "write_enabled": "false",
                                "write_gate_status": str(field.get("write_gate_status") or ""),
                            },
                        )


def _hkx_xml_add_semantic_writer_gate_v1(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    semantic_writer_gate_v1 = document.get("semantic_writer_gate_v1")
    if isinstance(semantic_writer_gate_v1, Mapping) and semantic_writer_gate_v1:
        gate_element = ET.SubElement(
            root,
            "semanticWriterGateV1",
            {
                "format": str(semantic_writer_gate_v1.get("format") or ""),
                "status": str(semantic_writer_gate_v1.get("status") or ""),
                "enabled": hkx._hkx_xml_scalar(semantic_writer_gate_v1.get("enabled")),
                "semantic_rebuild_supported": hkx._hkx_xml_scalar(
                    semantic_writer_gate_v1.get("semantic_rebuild_supported")
                ),
                "havok_xml_import_unblocked": hkx._hkx_xml_scalar(
                    semantic_writer_gate_v1.get("havok_xml_import_unblocked")
                ),
                "fixed_size_patch_importable": hkx._hkx_xml_scalar(
                    semantic_writer_gate_v1.get("fixed_size_patch_importable")
                ),
                "patchable_slot_count": hkx._hkx_xml_scalar(semantic_writer_gate_v1.get("patchable_slot_count")),
            },
        )
        writer_modes = semantic_writer_gate_v1.get("writer_modes")
        if isinstance(writer_modes, list):
            modes_element = ET.SubElement(gate_element, "writerModes")
            for mode in writer_modes:
                if not isinstance(mode, Mapping):
                    continue
                ET.SubElement(
                    modes_element,
                    "mode",
                    {
                        "name": str(mode.get("mode") or ""),
                        "status": str(mode.get("status") or ""),
                        "enabled": hkx._hkx_xml_scalar(mode.get("enabled")),
                        "reason": str(mode.get("reason") or ""),
                    },
                )
        required_roles = semantic_writer_gate_v1.get("required_role_coverage")
        if isinstance(required_roles, list):
            roles_element = ET.SubElement(gate_element, "requiredRoleCoverage")
            for role in required_roles:
                if not isinstance(role, Mapping):
                    continue
                ET.SubElement(
                    roles_element,
                    "role",
                    {
                        "name": str(role.get("role") or ""),
                        "no_edit_status": str(role.get("no_edit_status") or ""),
                        "semantic_no_edit_status": str(role.get("semantic_no_edit_status") or ""),
                        "fixed_edit_status": str(role.get("fixed_edit_status") or ""),
                        "byte_identity_status": str(role.get("byte_identity_status") or ""),
                        "sample_required": hkx._hkx_xml_scalar(role.get("sample_required")),
                        "fixed_size_edits_allowed": hkx._hkx_xml_scalar(role.get("fixed_size_edits_allowed")),
                    },
                )
        representative_gates = semantic_writer_gate_v1.get("representative_role_gates")
        if isinstance(representative_gates, list):
            representative_element = ET.SubElement(gate_element, "representativeRoleGates")
            for role in representative_gates:
                if not isinstance(role, Mapping):
                    continue
                role_element = ET.SubElement(
                    representative_element,
                    "roleGate",
                    {
                        "role": str(role.get("role") or ""),
                        "required": hkx._hkx_xml_scalar(role.get("required")),
                        "status": str(role.get("status") or ""),
                        "no_edit_byte_identity": str(role.get("no_edit_byte_identity") or ""),
                        "mismatch_offset": hkx._hkx_xml_scalar(role.get("mismatch_offset")),
                        "fixed_size_edits_allowed": hkx._hkx_xml_scalar(role.get("fixed_size_edits_allowed")),
                    },
                )
                unsupported_fields = role.get("unsupported_field_kinds")
                if isinstance(unsupported_fields, list):
                    fields_element = ET.SubElement(role_element, "unsupportedFieldKinds")
                    for kind in unsupported_fields:
                        hkx._hkx_xml_add_text(fields_element, "kind", kind)
                unsupported_refs = role.get("unsupported_ref_kinds")
                if isinstance(unsupported_refs, list):
                    refs_element = ET.SubElement(role_element, "unsupportedRefKinds")
                    for kind in unsupported_refs:
                        hkx._hkx_xml_add_text(refs_element, "kind", kind)
        unsupported_field_kinds = semantic_writer_gate_v1.get("unsupported_field_kinds")
        if isinstance(unsupported_field_kinds, list):
            fields_element = ET.SubElement(gate_element, "unsupportedFieldKinds")
            for kind in unsupported_field_kinds:
                hkx._hkx_xml_add_text(fields_element, "kind", kind)
        unsupported_ref_kinds = semantic_writer_gate_v1.get("unsupported_ref_kinds")
        if isinstance(unsupported_ref_kinds, list):
            refs_element = ET.SubElement(gate_element, "unsupportedRefKinds")
            for kind in unsupported_ref_kinds:
                hkx._hkx_xml_add_text(refs_element, "kind", kind)
        requirements = semantic_writer_gate_v1.get("requirements")
        if isinstance(requirements, list):
            requirements_element = ET.SubElement(gate_element, "requirements")
            for requirement in requirements:
                hkx._hkx_xml_add_text(requirements_element, "requirement", requirement)
        blocked_classes = semantic_writer_gate_v1.get("blocked_edit_classes")
        if isinstance(blocked_classes, list):
            blocked_element = ET.SubElement(gate_element, "blockedEditClasses")
            for blocked in blocked_classes:
                hkx._hkx_xml_add_text(blocked_element, "blocked", blocked)


def _hkx_xml_add_edit_candidate_map_v1(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    edit_candidate_map_v1 = document.get("edit_candidate_map_v1")
    if isinstance(edit_candidate_map_v1, Mapping) and edit_candidate_map_v1:
        edit_map_element = ET.SubElement(
            root,
            "editCandidateMapV1",
            {
                "format": str(edit_candidate_map_v1.get("format") or ""),
                "status": str(edit_candidate_map_v1.get("status") or ""),
                "new_editable_fields_enabled": hkx._hkx_xml_scalar(
                    edit_candidate_map_v1.get("new_editable_fields_enabled")
                ),
                "candidate_count": hkx._hkx_xml_scalar(edit_candidate_map_v1.get("candidate_count")),
                "write_enabled_candidate_count": hkx._hkx_xml_scalar(
                    edit_candidate_map_v1.get("write_enabled_candidate_count")
                ),
            },
        )
        candidates = edit_candidate_map_v1.get("candidates")
        task_categories = edit_candidate_map_v1.get("task_categories")
        if isinstance(task_categories, list):
            tasks_element = ET.SubElement(edit_map_element, "taskCategories")
            for row in task_categories:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    tasks_element,
                    "task",
                    {
                        "key": str(row.get("key") or ""),
                        "label": str(row.get("label") or ""),
                        "status": str(row.get("status") or ""),
                        "write_enabled_count": hkx._hkx_xml_scalar(row.get("write_enabled_count")),
                        "candidate_only_count": hkx._hkx_xml_scalar(row.get("candidate_only_count")),
                    },
                )
        if isinstance(candidates, list) and candidates:
            candidates_element = ET.SubElement(edit_map_element, "candidates", {"truncated_after": "512"})
            for candidate in candidates[:512]:
                if not isinstance(candidate, Mapping):
                    continue
                ET.SubElement(
                    candidates_element,
                    "candidate",
                    {
                        "class": str(candidate.get("class") or ""),
                        "owner_class": str(candidate.get("owner_class") or candidate.get("class") or ""),
                        "category": str(candidate.get("category") or ""),
                        "category_label": str(candidate.get("category_label") or candidate.get("task_label") or ""),
                        "task_category": str(candidate.get("task_category") or ""),
                        "task_label": str(candidate.get("task_label") or ""),
                        "member": str(candidate.get("member") or ""),
                        "field": str(candidate.get("field") or candidate.get("member") or ""),
                        "original_value": hkx._hkx_xml_scalar(candidate.get("original_value")),
                        "record_index": hkx._hkx_xml_scalar(candidate.get("record_index") or candidate.get("record")),
                        "item_index": hkx._hkx_xml_scalar(candidate.get("item_index")),
                        "local_offset": hkx._hkx_xml_scalar(candidate.get("local_offset")),
                        "record_relative_offset": hkx._hkx_xml_scalar(candidate.get("record_relative_offset")),
                        "offset_hex": str(candidate.get("offset_hex") or ""),
                        "absolute_offset": hkx._hkx_xml_scalar(candidate.get("absolute_offset")),
                        "absolute_offset_hex": str(candidate.get("absolute_offset_hex") or ""),
                        "byte_size": hkx._hkx_xml_scalar(candidate.get("byte_size")),
                        "supported_write_type": str(candidate.get("supported_write_type") or ""),
                        "write_type": str(candidate.get("write_type") or candidate.get("supported_write_type") or ""),
                        "value_kind": str(candidate.get("value_kind") or ""),
                        "structural_kind": str(candidate.get("structural_kind") or ""),
                        "import_safety": str(candidate.get("import_safety") or ""),
                        "risk_label": str(candidate.get("risk_label") or ""),
                        "risk": str(candidate.get("risk") or candidate.get("risk_label") or ""),
                        "confidence": str(candidate.get("confidence") or ""),
                        "link_evidence": str(candidate.get("link_evidence") or ""),
                        "linked_by": str(candidate.get("linked_by") or ""),
                        "linked_target": str(candidate.get("linked_target") or ""),
                        "import_path": str(candidate.get("import_path") or ""),
                        "import_behavior": str(candidate.get("import_behavior") or ""),
                        "write_enabled": hkx._hkx_xml_scalar(candidate.get("write_enabled")),
                        "gate_status": str(candidate.get("gate_status") or ""),
                        "gate_reason": str(candidate.get("gate_reason") or ""),
                    },
                )


def _hkx_xml_add_hkx_edit_gate_v1(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    hkx_edit_gate_v1 = document.get("hkx_edit_gate_v1")
    if isinstance(hkx_edit_gate_v1, Mapping) and hkx_edit_gate_v1:
        gate_element = ET.SubElement(
            root,
            "hkxEditGateV1",
            {
                "format": str(hkx_edit_gate_v1.get("format") or ""),
                "native_format": str(hkx_edit_gate_v1.get("native_format") or ""),
                "status": str(hkx_edit_gate_v1.get("status") or ""),
                "read_only": "true",
                "new_editable_fields_enabled": hkx._hkx_xml_scalar(
                    hkx_edit_gate_v1.get("new_editable_fields_enabled")
                ),
                "write_enabled_candidate_count": hkx._hkx_xml_scalar(
                    hkx_edit_gate_v1.get("write_enabled_candidate_count")
                ),
                "candidate_only_count": hkx._hkx_xml_scalar(hkx_edit_gate_v1.get("candidate_only_count")),
            },
        )
        hkx._hkx_xml_add_text(gate_element, "blockedPolicy", hkx_edit_gate_v1.get("blocked_policy") or "")
        categories = hkx_edit_gate_v1.get("categories")
        if isinstance(categories, list):
            categories_element = ET.SubElement(gate_element, "categories")
            for row in categories:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    categories_element,
                    "category",
                    {
                        "name": str(row.get("category") or ""),
                        "category": str(row.get("category") or ""),
                        "owner_class": str(row.get("owner_class") or ""),
                        "status": str(row.get("status") or ""),
                        "write_enabled_count": hkx._hkx_xml_scalar(row.get("write_enabled_count")),
                        "candidate_only_count": hkx._hkx_xml_scalar(row.get("candidate_only_count")),
                        "fixed_edit_test_status": str(row.get("fixed_edit_test_status") or ""),
                        "gate_reason": str(row.get("gate_reason") or ""),
                    },
                )
        task_categories = hkx_edit_gate_v1.get("task_categories")
        if isinstance(task_categories, list):
            tasks_element = ET.SubElement(gate_element, "taskCategories")
            for row in task_categories:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    tasks_element,
                    "task",
                    {
                        "key": str(row.get("key") or ""),
                        "label": str(row.get("label") or ""),
                        "status": str(row.get("status") or ""),
                        "write_enabled_count": hkx._hkx_xml_scalar(row.get("write_enabled_count")),
                        "candidate_only_count": hkx._hkx_xml_scalar(row.get("candidate_only_count")),
                        "fixed_edit_test_status": str(row.get("fixed_edit_test_status") or ""),
                        "gate_reason": str(row.get("gate_reason") or ""),
                    },
                )
        roles = hkx_edit_gate_v1.get("required_role_coverage")
        if isinstance(roles, list):
            roles_element = ET.SubElement(gate_element, "requiredRoleCoverage")
            for row in roles:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    roles_element,
                    "role",
                    {
                        "name": str(row.get("role") or ""),
                        "status": str(row.get("status") or ""),
                        "no_edit_status": str(row.get("no_edit_status") or ""),
                        "fixed_edit_status": str(row.get("fixed_edit_status") or ""),
                    },
                )
        blocked_kinds = hkx_edit_gate_v1.get("blocked_kinds")
        if isinstance(blocked_kinds, list):
            blocked_element = ET.SubElement(gate_element, "blockedKinds")
            for kind in blocked_kinds:
                hkx._hkx_xml_add_text(blocked_element, "kind", kind)


def _hkx_xml_add_class_decoder_evidence_v2(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    class_decoder_evidence_v2 = document.get("class_decoder_evidence_v2")
    if isinstance(class_decoder_evidence_v2, Mapping) and class_decoder_evidence_v2:
        class_decoder_element = ET.SubElement(
            root,
            "classDecoderEvidenceV2",
            {
                "format": str(class_decoder_evidence_v2.get("format") or ""),
                "status": str(class_decoder_evidence_v2.get("status") or ""),
                "read_only": "true",
                "class_status_count": hkx._hkx_xml_scalar(class_decoder_evidence_v2.get("class_status_count")),
                "hard_target_count": hkx._hkx_xml_scalar(class_decoder_evidence_v2.get("hard_target_count")),
                "observed_hard_target_count": hkx._hkx_xml_scalar(
                    class_decoder_evidence_v2.get("observed_hard_target_count")
                ),
            },
        )
        class_statuses = class_decoder_evidence_v2.get("class_statuses")
        if isinstance(class_statuses, list):
            statuses_element = ET.SubElement(class_decoder_element, "classStatuses", {"truncated_after": "256"})
            for row in class_statuses[:256]:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    statuses_element,
                    "class",
                    {
                        "name": str(row.get("class") or row.get("type_name") or ""),
                        "record_count": hkx._hkx_xml_scalar(row.get("record_count")),
                        "byte_count": hkx._hkx_xml_scalar(row.get("byte_count")),
                        "decoded_field_count": hkx._hkx_xml_scalar(row.get("decoded_field_count")),
                        "reference_count": hkx._hkx_xml_scalar(row.get("reference_count")),
                        "editable_candidate_count": hkx._hkx_xml_scalar(row.get("editable_candidate_count")),
                        "status": str(row.get("status") or ""),
                        "friendly_status": str(row.get("friendly_status") or ""),
                        "read_only": "true",
                    },
                )
