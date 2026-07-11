from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Mapping


def _hkx_xml_add_physics_system(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_system = document.get("physics_system")
    if isinstance(physics_system, Mapping):
        physics_element = ET.SubElement(
            root,
            "physicsSystem",
            {"status": str(physics_system.get("status") or "partial_reverse_engineering")},
        )
        hkx._hkx_xml_add_text(physics_element, "description", physics_system.get("description", ""))
        type_counts = physics_system.get("type_counts")
        if isinstance(type_counts, Mapping):
            counts_element = ET.SubElement(physics_element, "typeCounts")
            for type_name, count in type_counts.items():
                ET.SubElement(counts_element, "type", {"name": str(type_name), "count": hkx._hkx_xml_scalar(count)})
        likely_controls = physics_system.get("likely_controls")
        if isinstance(likely_controls, list):
            controls_element = ET.SubElement(physics_element, "likelyControls")
            for control in likely_controls:
                if not isinstance(control, Mapping):
                    continue
                control_element = ET.SubElement(controls_element, "control", {"name": str(control.get("name") or "")})
                hkx._hkx_xml_add_text(control_element, "description", control.get("description", ""))
                control_types = control.get("types")
                if isinstance(control_types, list):
                    for type_name in control_types:
                        ET.SubElement(control_element, "typeRef", {"name": str(type_name)})
        editable_groups = physics_system.get("editable_record_groups")
        if isinstance(editable_groups, list):
            groups_element = ET.SubElement(physics_element, "editableRecordGroups")
            for group in editable_groups:
                if not isinstance(group, Mapping):
                    continue
                group_element = ET.SubElement(groups_element, "group", {"type_name": str(group.get("type_name") or "")})
                hkx._hkx_xml_add_text(group_element, "description", group.get("description", ""))
                indices = group.get("record_indices")
                if isinstance(indices, list):
                    group_element.set("record_indices", " ".join(str(int(index)) for index in indices if isinstance(index, int)))


def _hkx_xml_add_physics_names(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_names = document.get("physics_names")
    if isinstance(physics_names, Mapping):
        names_element = ET.SubElement(
            root,
            "physicsNames",
            {"status": str(physics_names.get("status") or "partial_reverse_engineering"), "imported": "false"},
        )
        hkx._hkx_xml_add_text(names_element, "description", physics_names.get("description", ""))
        char_strings = physics_names.get("char_strings")
        if isinstance(char_strings, list):
            strings_element = ET.SubElement(names_element, "charStrings")
            for row in char_strings:
                if not isinstance(row, Mapping):
                    continue
                ET.SubElement(
                    strings_element,
                    "string",
                    {
                        "record_index": hkx._hkx_xml_scalar(row.get("record_index")),
                        "text": hkx._hkx_xml_scalar(row.get("text")),
                        "simulation_role": str(row.get("simulation_role") or "collision"),
                        "simulation_role_description": str(row.get("simulation_role_description") or ""),
                        "confidence": str(row.get("confidence") or "confirmed"),
                        "description": str(row.get("description") or ""),
                    },
                )
        shape_name_properties = physics_names.get("shape_name_properties")
        if isinstance(shape_name_properties, list):
            properties_element = ET.SubElement(names_element, "shapeNameProperties")
            for shape_name in shape_name_properties:
                if not isinstance(shape_name, Mapping):
                    continue
                ET.SubElement(
                    properties_element,
                    "shapeName",
                    {
                        "index": hkx._hkx_xml_scalar(shape_name.get("index")),
                        "name": str(shape_name.get("name") or ""),
                        "property_record_index": hkx._hkx_xml_scalar(shape_name.get("property_record_index")),
                        "name_record_index": hkx._hkx_xml_scalar(shape_name.get("name_record_index")),
                        "raw_name_reference": hkx._hkx_xml_scalar(shape_name.get("raw_name_reference")),
                        "simulation_role": str(shape_name.get("simulation_role") or "collision"),
                        "simulation_role_description": str(shape_name.get("simulation_role_description") or ""),
                        "confidence": str(shape_name.get("confidence") or "experimental"),
                        "description": str(shape_name.get("description") or ""),
                    },
                )


def _hkx_xml_add_physics_body_summary(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_body_summary = document.get("physics_body_summary")
    if isinstance(physics_body_summary, Mapping):
        summary_element = ET.SubElement(
            root,
            "physicsBodySummary",
            {
                "status": str(physics_body_summary.get("status") or "partial_reverse_engineering"),
                "confidence": str(physics_body_summary.get("confidence") or "experimental"),
                "body_count": hkx._hkx_xml_scalar(physics_body_summary.get("body_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(summary_element, "description", physics_body_summary.get("description", ""))
        bodies = physics_body_summary.get("bodies")
        if isinstance(bodies, list):
            bodies_element = ET.SubElement(summary_element, "bodies")
            for body in bodies:
                if not isinstance(body, Mapping):
                    continue
                body_element = ET.SubElement(
                    bodies_element,
                    "body",
                    {
                        "index": hkx._hkx_xml_scalar(body.get("index")),
                        "shape_index": hkx._hkx_xml_scalar(body.get("shape_index")),
                        "shape_type": str(body.get("shape_type") or ""),
                        "body_name": str(body.get("body_name") or ""),
                        "simulation_role": str(body.get("simulation_role") or ""),
                        "simulation_role_description": str(body.get("simulation_role_description") or ""),
                        "socket_name": str(body.get("socket_name") or ""),
                        "fixed_socket_name": str(body.get("fixed_socket_name") or ""),
                        "physics_material_name": str(body.get("physics_material_name") or ""),
                        "confidence": str(body.get("confidence") or "experimental"),
                        "editable_fields": " ".join(str(field) for field in body.get("editable_fields", []) if field),
                    },
                )
                hkx._hkx_xml_add_text(body_element, "description", body.get("description", ""))
                descriptor_contexts = body.get("descriptor_contexts")
                if isinstance(descriptor_contexts, list) and descriptor_contexts:
                    contexts_element = ET.SubElement(body_element, "descriptorContexts", {"imported": "false"})
                    for context in descriptor_contexts:
                        if not isinstance(context, Mapping):
                            continue
                        ET.SubElement(
                            contexts_element,
                            "context",
                            {
                                "body_name": str(context.get("body_name") or ""),
                                "socket_name": str(context.get("socket_name") or ""),
                                "fixed_socket_name": str(context.get("fixed_socket_name") or ""),
                                "physics_material_name": str(context.get("physics_material_name") or ""),
                                "simulation_role": str(context.get("simulation_role") or ""),
                                "simulation_role_description": str(context.get("simulation_role_description") or ""),
                                "descriptor_path": str(context.get("descriptor_path") or ""),
                                "confidence": str(context.get("confidence") or "experimental"),
                            },
                        )
                capsule = body.get("capsule")
                if isinstance(capsule, Mapping):
                    capsule_element = ET.SubElement(
                        body_element,
                        "capsule",
                        {
                            "radius": hkx._hkx_xml_scalar(capsule.get("radius")),
                            "length": hkx._hkx_xml_scalar(capsule.get("length")),
                        },
                    )
                    start = capsule.get("start")
                    if isinstance(start, list) and len(start) == 3:
                        hkx._hkx_xml_add_vector(capsule_element, "start", start, ("x", "y", "z"))
                    end = capsule.get("end")
                    if isinstance(end, list) and len(end) == 3:
                        hkx._hkx_xml_add_vector(capsule_element, "end", end, ("x", "y", "z"))
                    hkx._hkx_xml_add_text(capsule_element, "description", capsule.get("description", ""))


def _hkx_xml_add_physics_constraint_summary(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_constraint_summary = document.get("physics_constraint_summary")
    if isinstance(physics_constraint_summary, Mapping):
        constraint_summary_element = ET.SubElement(
            root,
            "physicsConstraintSummary",
            {
                "status": str(physics_constraint_summary.get("status") or "partial_reverse_engineering"),
                "confidence": str(physics_constraint_summary.get("confidence") or "experimental"),
                "constraint_count": hkx._hkx_xml_scalar(physics_constraint_summary.get("constraint_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(constraint_summary_element, "description", physics_constraint_summary.get("description", ""))
        constraints = physics_constraint_summary.get("constraints")
        if isinstance(constraints, list):
            constraints_element = ET.SubElement(constraint_summary_element, "constraints")
            for constraint in constraints:
                if not isinstance(constraint, Mapping):
                    continue
                constraint_element = ET.SubElement(
                    constraints_element,
                    "constraint",
                    {
                        "index": hkx._hkx_xml_scalar(constraint.get("index")),
                        "name": str(constraint.get("name") or ""),
                        "type_name": str(constraint.get("type_name") or ""),
                        "constraint_record_index": hkx._hkx_xml_scalar(constraint.get("constraint_record_index")),
                        "motor_record_index": hkx._hkx_xml_scalar(constraint.get("motor_record_index")),
                        "name_record_index": hkx._hkx_xml_scalar(constraint.get("name_record_index")),
                        "confidence": str(constraint.get("confidence") or "experimental"),
                    },
                )
                hkx._hkx_xml_add_text(constraint_element, "description", constraint.get("description", ""))
                descriptor_context = constraint.get("descriptor_context")
                if isinstance(descriptor_context, Mapping):
                    context_element = ET.SubElement(
                        constraint_element,
                        "descriptorContext",
                        {
                            "descriptor_path": str(descriptor_context.get("descriptor_path") or ""),
                            "tag": str(descriptor_context.get("tag") or ""),
                            "body_name": str(descriptor_context.get("body_name") or ""),
                            "socket_name": str(descriptor_context.get("socket_name") or ""),
                            "fixed_socket_name": str(descriptor_context.get("fixed_socket_name") or ""),
                            "confidence": str(descriptor_context.get("confidence") or "descriptor_context"),
                            "imported": "false",
                        },
                    )
                    numeric_hints = descriptor_context.get("numeric_hints")
                    if isinstance(numeric_hints, list):
                        hints_element = ET.SubElement(context_element, "numericHints")
                        for hint in numeric_hints:
                            if not isinstance(hint, Mapping):
                                continue
                            ET.SubElement(
                                hints_element,
                                "hint",
                                {
                                    "name": str(hint.get("name") or ""),
                                    "value": str(hint.get("value") or ""),
                                    "description": str(hint.get("description") or ""),
                                },
                            )
                for slot_group_name, slot_tag in (("constraint_slots", "constraintSlot"), ("motor_slots", "motorSlot")):
                    slots = constraint.get(slot_group_name)
                    if not isinstance(slots, list) or not slots:
                        continue
                    slots_element = ET.SubElement(constraint_element, slot_group_name)
                    for slot in slots:
                        if not isinstance(slot, Mapping):
                            continue
                        ET.SubElement(
                            slots_element,
                            slot_tag,
                            {
                                "item_index": hkx._hkx_xml_scalar(slot.get("item_index")),
                                "offset": hkx._hkx_xml_scalar(slot.get("offset")),
                                "hex_offset": str(slot.get("hex_offset") or ""),
                                "name": str(slot.get("name") or ""),
                                "value": hkx._hkx_xml_scalar(slot.get("value")),
                                "confidence": str(slot.get("confidence") or "experimental"),
                                "description": str(slot.get("description") or ""),
                            },
                        )


def _hkx_xml_add_editable_field_catalog(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    editable_field_catalog = document.get("editable_field_catalog")
    if isinstance(editable_field_catalog, Mapping):
        catalog_element = ET.SubElement(
            root,
            "editableFieldCatalog",
            {
                "status": str(editable_field_catalog.get("status") or "generated_from_current_decoder"),
                "field_count": hkx._hkx_xml_scalar(editable_field_catalog.get("field_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(catalog_element, "description", editable_field_catalog.get("description", ""))
        category_counts = editable_field_catalog.get("category_counts")
        if isinstance(category_counts, Mapping):
            counts_element = ET.SubElement(catalog_element, "categoryCounts")
            for category, count in category_counts.items():
                ET.SubElement(counts_element, "category", {"name": str(category), "count": hkx._hkx_xml_scalar(count)})
        effect_counts = editable_field_catalog.get("effect_counts")
        if isinstance(effect_counts, Mapping):
            effects_element = ET.SubElement(catalog_element, "effectCounts")
            for effect, count in effect_counts.items():
                ET.SubElement(effects_element, "effect", {"name": str(effect), "count": hkx._hkx_xml_scalar(count)})
        fields = editable_field_catalog.get("fields")
        if isinstance(fields, list):
            fields_element = ET.SubElement(catalog_element, "fields")
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                attrs = {
                    "category": str(field.get("category") or ""),
                    "editor_tab": str(field.get("editor_tab") or ""),
                    "importable": "true" if bool(field.get("importable")) else "false",
                    "edit_rule": str(field.get("edit_rule") or ""),
                    "name": str(field.get("name") or ""),
                    "value_summary": str(field.get("value_summary") or ""),
                    "effect": str(field.get("effect") or ""),
                    "edit_guidance": str(field.get("edit_guidance") or ""),
                    "value_constraints": str(field.get("value_constraints") or ""),
                    "suggested_edit_step": str(field.get("suggested_edit_step") or ""),
                    "plain_language_effect": str(field.get("plain_language_effect") or ""),
                    "if_increased": str(field.get("if_increased") or ""),
                    "if_decreased": str(field.get("if_decreased") or ""),
                    "safe_edit_hint": str(field.get("safe_edit_hint") or ""),
                    "edit_risk": str(field.get("edit_risk") or ""),
                    "confidence": str(field.get("confidence") or "experimental"),
                    "description": str(field.get("description") or ""),
                }
                for key in ("shape_index", "shape_type", "record_index", "item_index", "offset", "hex_offset"):
                    value = field.get(key)
                    if value is not None:
                        attrs[key] = hkx._hkx_xml_scalar(value)
                subject = field.get("subject")
                if subject is not None:
                    attrs["subject"] = str(subject)
                ET.SubElement(fields_element, "field", attrs)


def _hkx_xml_add_byte_patch_map(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    byte_patch_map = document.get("byte_patch_map")
    if isinstance(byte_patch_map, Mapping):
        patch_map_element = ET.SubElement(
            root,
            "bytePatchMap",
            {
                "status": str(byte_patch_map.get("status") or "generated_from_current_decoder"),
                "entry_count": hkx._hkx_xml_scalar(byte_patch_map.get("entry_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(patch_map_element, "description", byte_patch_map.get("description", ""))
        entries = byte_patch_map.get("entries")
        if isinstance(entries, list):
            entries_element = ET.SubElement(patch_map_element, "entries")
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                attrs = {
                    "index": hkx._hkx_xml_scalar(entry.get("index")),
                    "path": str(entry.get("path") or ""),
                    "category": str(entry.get("category") or ""),
                    "category_label": str(entry.get("category_label") or entry.get("task_label") or ""),
                    "task_category": str(entry.get("task_category") or ""),
                    "task_label": str(entry.get("task_label") or ""),
                    "owner_class": str(entry.get("owner_class") or ""),
                    "member": str(entry.get("member") or entry.get("name") or ""),
                    "field": str(entry.get("field") or entry.get("member") or entry.get("name") or ""),
                    "name": str(entry.get("name") or ""),
                    "subject": str(entry.get("subject") or ""),
                    "record_index": hkx._hkx_xml_scalar(entry.get("record_index")),
                    "local_offset": hkx._hkx_xml_scalar(entry.get("local_offset")),
                    "relative_offset": hkx._hkx_xml_scalar(entry.get("relative_offset")),
                    "hex_relative_offset": str(entry.get("hex_relative_offset") or ""),
                    "absolute_offset": hkx._hkx_xml_scalar(entry.get("absolute_offset")),
                    "absolute_offset_hex": str(entry.get("absolute_offset_hex") or ""),
                    "absolute_data_offset": hkx._hkx_xml_scalar(entry.get("absolute_data_offset")),
                    "hex_absolute_data_offset": str(entry.get("hex_absolute_data_offset") or ""),
                    "byte_size": hkx._hkx_xml_scalar(entry.get("byte_size")),
                    "value_type": str(entry.get("value_type") or ""),
                    "write_type": str(entry.get("write_type") or entry.get("supported_write_type") or ""),
                    "supported_write_type": str(entry.get("supported_write_type") or ""),
                    "value_kind": str(entry.get("value_kind") or ""),
                    "structural_kind": str(entry.get("structural_kind") or ""),
                    "import_safety": str(entry.get("import_safety") or ""),
                    "risk_label": str(entry.get("risk_label") or ""),
                    "risk": str(entry.get("risk") or entry.get("risk_label") or ""),
                    "original_bytes_hex": str(entry.get("original_bytes_hex") or ""),
                    "decoded_value": hkx._hkx_xml_scalar(entry.get("decoded_value")),
                    "edit_rule": str(entry.get("edit_rule") or "fixed_size_value_only"),
                    "confidence": str(entry.get("confidence") or "experimental"),
                    "evidence": str(entry.get("evidence") or ""),
                    "link_evidence": str(entry.get("link_evidence") or ""),
                    "linked_by": str(entry.get("linked_by") or ""),
                    "linked_target": str(entry.get("linked_target") or ""),
                    "import_behavior": str(entry.get("import_behavior") or ""),
                    "gate_status": str(entry.get("gate_status") or ""),
                    "gate_reason": str(entry.get("gate_reason") or ""),
                    "fixed_edit_test_status": str(entry.get("fixed_edit_test_status") or ""),
                    "effect": str(entry.get("effect") or ""),
                    "value_constraints": str(entry.get("value_constraints") or ""),
                    "description": str(entry.get("description") or ""),
                }
                for key in ("item_index", "row_index", "component"):
                    value = entry.get(key)
                    if value is not None:
                        attrs[key] = hkx._hkx_xml_scalar(value)
                ET.SubElement(entries_element, "entry", attrs)


def _hkx_xml_add_physics_tuning(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_tuning = document.get("physics_tuning")
    if isinstance(physics_tuning, Mapping):
        tuning_element = ET.SubElement(
            root,
            "physicsTuning",
            {
                "status": str(physics_tuning.get("status") or "partial_reverse_engineering"),
                "edit_rule": str(physics_tuning.get("edit_rule") or "value_only_fixed_float_slots"),
            },
        )
        hkx._hkx_xml_add_text(tuning_element, "description", physics_tuning.get("description", ""))
        groups = physics_tuning.get("groups")
        if isinstance(groups, list):
            groups_element = ET.SubElement(tuning_element, "groups")
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                group_element = ET.SubElement(
                    groups_element,
                    "group",
                    {
                        "category": str(group.get("category") or ""),
                        "label": str(group.get("label") or ""),
                        "type_name": str(group.get("type_name") or ""),
                        "record_index": hkx._hkx_xml_scalar(group.get("record_index")),
                        "count": hkx._hkx_xml_scalar(group.get("count")),
                        "byte_length": hkx._hkx_xml_scalar(group.get("byte_length")),
                        "confidence": str(group.get("confidence") or "experimental"),
                        "edit_rule": str(group.get("edit_rule") or "edit_value_only_keep_record_item_and_offset"),
                    },
                )
                hkx._hkx_xml_add_text(group_element, "description", group.get("description", ""))
                descriptor_context_hints = group.get("descriptor_context_hints")
                if isinstance(descriptor_context_hints, list) and descriptor_context_hints:
                    context_element = ET.SubElement(group_element, "descriptorContextHints", {"imported": "false"})
                    for hint in descriptor_context_hints:
                        if not isinstance(hint, Mapping):
                            continue
                        ET.SubElement(
                            context_element,
                            "hint",
                            {
                                "source": str(hint.get("source") or ""),
                                "descriptor_path": str(hint.get("descriptor_path") or ""),
                                "body_name": str(hint.get("body_name") or ""),
                                "socket_name": str(hint.get("socket_name") or ""),
                                "constraint_tag": str(hint.get("constraint_tag") or ""),
                                "name": str(hint.get("name") or ""),
                                "value": str(hint.get("value") or ""),
                                "confidence": str(hint.get("confidence") or "descriptor_context"),
                                "description": str(hint.get("description") or ""),
                            },
                        )
                slots = group.get("slots")
                if isinstance(slots, list):
                    slots_element = ET.SubElement(group_element, "slots")
                    for slot in slots:
                        if not isinstance(slot, Mapping):
                            continue
                        slot_attrs = {
                            "item_index": hkx._hkx_xml_scalar(slot.get("item_index")),
                            "offset": hkx._hkx_xml_scalar(slot.get("offset")),
                            "hex_offset": str(slot.get("hex_offset") or ""),
                            "name": str(slot.get("name") or ""),
                            "value": hkx._hkx_xml_scalar(slot.get("value")),
                            "confidence": str(slot.get("confidence") or "experimental"),
                            "plain_language_effect": str(slot.get("plain_language_effect") or ""),
                            "if_increased": str(slot.get("if_increased") or ""),
                            "if_decreased": str(slot.get("if_decreased") or ""),
                            "safe_edit_hint": str(slot.get("safe_edit_hint") or ""),
                            "edit_risk": str(slot.get("edit_risk") or ""),
                            "value_constraints": str(slot.get("value_constraints") or ""),
                            "suggested_edit_step": str(slot.get("suggested_edit_step") or ""),
                            "description": str(slot.get("description") or ""),
                        }
                        ET.SubElement(slots_element, "slot", slot_attrs)
                vector_groups = group.get("slot_vector_groups")
                if isinstance(vector_groups, list) and vector_groups:
                    vectors_element = ET.SubElement(group_element, "vectorGroups", {"imported": "false"})
                    for vector_group in vector_groups:
                        if not isinstance(vector_group, Mapping):
                            continue
                        attrs = {
                            "name": str(vector_group.get("name") or ""),
                            "prefix": str(vector_group.get("prefix") or ""),
                            "item_index": hkx._hkx_xml_scalar(vector_group.get("item_index")),
                            "row_index": hkx._hkx_xml_scalar(vector_group.get("row_index")),
                            "likely_role": str(vector_group.get("likely_role") or ""),
                            "complete_xyzw": hkx._hkx_xml_scalar(vector_group.get("complete_xyzw")),
                            "confidence": str(vector_group.get("confidence") or "experimental"),
                            "edit_risk": str(vector_group.get("edit_risk") or "high"),
                            "description": str(vector_group.get("description") or ""),
                        }
                        vector_element = ET.SubElement(vectors_element, "vector", attrs)
                        components = vector_group.get("components")
                        offsets = vector_group.get("offsets")
                        if isinstance(components, Mapping):
                            for component in ("x", "y", "z", "w"):
                                if component not in components:
                                    continue
                                ET.SubElement(
                                    vector_element,
                                    "component",
                                    {
                                        "name": component,
                                        "value": hkx._hkx_xml_scalar(components.get(component)),
                                        "hex_offset": str(offsets.get(component) if isinstance(offsets, Mapping) else ""),
                                    },
                                )


def _hkx_xml_add_physics_body_context(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_body_context = document.get("physics_body_context")
    if isinstance(physics_body_context, Mapping):
        context_element = ET.SubElement(
            root,
            "physicsBodyContext",
            {
                "status": str(physics_body_context.get("status") or "descriptor_correlated_context"),
                "confidence": str(physics_body_context.get("confidence") or "experimental"),
                "body_count": hkx._hkx_xml_scalar(physics_body_context.get("body_count")),
                "constraint_hint_count": hkx._hkx_xml_scalar(physics_body_context.get("constraint_hint_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(context_element, "description", physics_body_context.get("description", ""))
        body_contexts = physics_body_context.get("body_contexts")
        if isinstance(body_contexts, list):
            bodies_element = ET.SubElement(context_element, "bodies")
            for body_context in body_contexts:
                if not isinstance(body_context, Mapping):
                    continue
                body_element = ET.SubElement(
                    bodies_element,
                    "body",
                    {
                        "descriptor_path": str(body_context.get("descriptor_path") or ""),
                        "descriptor_body_index": hkx._hkx_xml_scalar(body_context.get("descriptor_body_index")),
                        "body_name": str(body_context.get("body_name") or ""),
                        "simulation_role": str(body_context.get("simulation_role") or ""),
                        "simulation_role_description": str(body_context.get("simulation_role_description") or ""),
                        "socket_name": str(body_context.get("socket_name") or ""),
                        "fixed_socket_name": str(body_context.get("fixed_socket_name") or ""),
                        "physics_material_name": str(body_context.get("physics_material_name") or ""),
                    },
                )
                hkx._hkx_xml_add_text(body_element, "description", body_context.get("description", ""))
                numeric_hints = body_context.get("numeric_hints")
                if isinstance(numeric_hints, list) and numeric_hints:
                    numeric_element = ET.SubElement(body_element, "numericHints")
                    for hint in numeric_hints:
                        if not isinstance(hint, Mapping):
                            continue
                        ET.SubElement(
                            numeric_element,
                            "hint",
                            {
                                "name": str(hint.get("name") or ""),
                                "value": str(hint.get("value") or ""),
                                "description": str(hint.get("description") or ""),
                            },
                        )
                shape_matches = body_context.get("shape_matches")
                if isinstance(shape_matches, list) and shape_matches:
                    matches_element = ET.SubElement(body_element, "shapeMatches")
                    for match in shape_matches:
                        if not isinstance(match, Mapping):
                            continue
                        attrs = {
                            "descriptor_shape_index": hkx._hkx_xml_scalar(match.get("descriptor_shape_index")),
                            "descriptor_shape_kind": str(match.get("descriptor_shape_kind") or ""),
                            "descriptor_tag": str(match.get("descriptor_tag") or ""),
                            "decoded_shape_index": hkx._hkx_xml_scalar(match.get("decoded_shape_index")),
                            "decoded_shape_type": str(match.get("decoded_shape_type") or ""),
                            "decoded_shape_record_index": hkx._hkx_xml_scalar(match.get("decoded_shape_record_index")),
                            "confidence": str(match.get("confidence") or "experimental"),
                        }
                        for optional_key in (
                            "descriptor_radius",
                            "descriptor_height",
                            "decoded_radius",
                            "decoded_length",
                            "radius_delta",
                            "length_delta",
                            "decoded_vertex_count",
                            "decoded_plane_count",
                        ):
                            if match.get(optional_key) is not None:
                                attrs[optional_key] = hkx._hkx_xml_scalar(match.get(optional_key))
                        match_element = ET.SubElement(matches_element, "shape", attrs)
                        hkx._hkx_xml_add_text(match_element, "description", match.get("description", ""))
                        for vector_key in ("bounds_min", "bounds_max", "center", "extent"):
                            vector = match.get(vector_key)
                            if isinstance(vector, list) and len(vector) == 3:
                                hkx._hkx_xml_add_vector(match_element, vector_key, vector, ("x", "y", "z"))
        constraint_contexts = physics_body_context.get("constraint_contexts")
        if isinstance(constraint_contexts, list) and constraint_contexts:
            constraints_element = ET.SubElement(context_element, "constraints")
            for constraint in constraint_contexts:
                if not isinstance(constraint, Mapping):
                    continue
                constraint_element = ET.SubElement(
                    constraints_element,
                    "constraint",
                    {
                        "descriptor_path": str(constraint.get("descriptor_path") or ""),
                        "descriptor_constraint_index": hkx._hkx_xml_scalar(constraint.get("descriptor_constraint_index")),
                        "tag": str(constraint.get("tag") or ""),
                        "body_name": str(constraint.get("body_name") or ""),
                        "simulation_role": str(constraint.get("simulation_role") or ""),
                        "simulation_role_description": str(constraint.get("simulation_role_description") or ""),
                        "socket_name": str(constraint.get("socket_name") or ""),
                        "fixed_socket_name": str(constraint.get("fixed_socket_name") or ""),
                        "confidence": str(constraint.get("confidence") or "descriptor_context"),
                    },
                )
                hkx._hkx_xml_add_text(constraint_element, "description", constraint.get("description", ""))
                numeric_hints = constraint.get("numeric_hints")
                if isinstance(numeric_hints, list) and numeric_hints:
                    numeric_element = ET.SubElement(constraint_element, "numericHints")
                    for hint in numeric_hints:
                        if isinstance(hint, Mapping):
                            ET.SubElement(
                                numeric_element,
                                "hint",
                                {
                                    "name": str(hint.get("name") or ""),
                                    "value": str(hint.get("value") or ""),
                                    "description": str(hint.get("description") or ""),
                                },
                            )


def _hkx_xml_add_physics_material_context(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    physics_material_context = document.get("physics_material_context")
    if isinstance(physics_material_context, Mapping):
        material_context_element = ET.SubElement(
            root,
            "physicsMaterialContext",
            {
                "status": str(physics_material_context.get("status") or "descriptor_material_context"),
                "confidence": str(physics_material_context.get("confidence") or "descriptor_context"),
                "hint_count": hkx._hkx_xml_scalar(physics_material_context.get("hint_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(material_context_element, "description", physics_material_context.get("description", ""))
        role_counts = physics_material_context.get("role_counts")
        if isinstance(role_counts, Mapping):
            counts_element = ET.SubElement(material_context_element, "roleCounts")
            for role, count in role_counts.items():
                ET.SubElement(counts_element, "role", {"name": str(role), "count": hkx._hkx_xml_scalar(count)})
        hints = physics_material_context.get("hints")
        if isinstance(hints, list):
            hints_element = ET.SubElement(material_context_element, "hints")
            for hint in hints:
                if not isinstance(hint, Mapping):
                    continue
                attrs = {
                    "index": hkx._hkx_xml_scalar(hint.get("index")),
                    "descriptor_path": str(hint.get("descriptor_path") or ""),
                    "tag": str(hint.get("tag") or ""),
                    "simulation_role": str(hint.get("simulation_role") or ""),
                    "simulation_role_description": str(hint.get("simulation_role_description") or ""),
                    "pbd_simulation_material": str(hint.get("pbd_simulation_material") or ""),
                    "material_name": str(hint.get("material_name") or ""),
                    "submesh_name": str(hint.get("submesh_name") or ""),
                    "jiggle_wind_weight": str(hint.get("jiggle_wind_weight") or ""),
                    "parameter_name": str(hint.get("parameter_name") or ""),
                    "parameter_value": str(hint.get("parameter_value") or ""),
                }
                ET.SubElement(hints_element, "hint", attrs)


def _hkx_xml_add_advanced_payloads(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    advanced_payloads = document.get("advanced_record_payloads")
    if isinstance(advanced_payloads, list):
        advanced_element = ET.SubElement(
            root,
            "advancedRecordPayloads",
            {
                "editable": "true",
                "edit_rule": "same_length_hex_payload_only",
            },
        )
        for payload_info in advanced_payloads:
            if not isinstance(payload_info, Mapping):
                continue
            record_element = ET.SubElement(
                advanced_element,
                "record",
                {
                    "index": hkx._hkx_xml_scalar(payload_info.get("record_index")),
                    "type_index": hkx._hkx_xml_scalar(payload_info.get("type_index")),
                    "type_name": str(payload_info.get("type_name") or ""),
                    "count": hkx._hkx_xml_scalar(payload_info.get("count")),
                    "data_offset": hkx._hkx_xml_scalar(payload_info.get("data_offset")),
                    "absolute_data_offset": hkx._hkx_xml_scalar(payload_info.get("absolute_data_offset")),
                    "byte_length": hkx._hkx_xml_scalar(payload_info.get("byte_length")),
                    "edit_rule": str(payload_info.get("edit_rule") or "same_length_hex_payload_only"),
                },
            )
            hkx._hkx_xml_add_text(record_element, "description", payload_info.get("description", ""))
            warning = payload_info.get("warning")
            if warning:
                hkx._hkx_xml_add_text(record_element, "warning", warning)
            hkx._hkx_xml_add_record_interpretation(record_element, payload_info.get("interpretation"))
            hkx._hkx_xml_add_advanced_editable_values(record_element, payload_info.get("editable_values"))
            payload_element = ET.SubElement(record_element, "payload", {"encoding": "hex"})
            payload_element.text = str(payload_info.get("payload_hex") or "")


def _hkx_xml_add_raw_records(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    raw_records = document.get("raw_records")
    if isinstance(raw_records, list):
        raw_element = ET.SubElement(root, "rawRecords", {"status": "raw_preserved", "edit_rule": "same_length_only"})
        for raw_info in raw_records:
            if not isinstance(raw_info, Mapping):
                continue
            record_element = ET.SubElement(
                raw_element,
                "record",
                {
                    "index": hkx._hkx_xml_scalar(raw_info.get("record_index")),
                    "type_index": hkx._hkx_xml_scalar(raw_info.get("type_index")),
                    "type_name": str(raw_info.get("type_name") or ""),
                    "count": hkx._hkx_xml_scalar(raw_info.get("count")),
                    "byte_length": hkx._hkx_xml_scalar(raw_info.get("byte_length")),
                },
            )
            payload_element = ET.SubElement(record_element, "payload", {"encoding": "hex"})
            payload_element.text = str(raw_info.get("payload_hex") or "")
