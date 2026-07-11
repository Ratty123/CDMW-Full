from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Mapping


def _hkx_xml_add_objects(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    objects = document.get("objects")
    if isinstance(objects, list):
        objects_element = ET.SubElement(root, "objects", {"status": "readable_converter_view"})
        for object_info in objects:
            if not isinstance(object_info, Mapping):
                continue
            object_element = ET.SubElement(
                objects_element,
                "object",
                {
                    "record_index": hkx._hkx_xml_scalar(object_info.get("record_index")),
                    "type_index": hkx._hkx_xml_scalar(object_info.get("type_index")),
                    "type_name": str(object_info.get("type_name") or ""),
                    "count": hkx._hkx_xml_scalar(object_info.get("count")),
                    "byte_length": hkx._hkx_xml_scalar(object_info.get("byte_length")),
                    "status": str(object_info.get("status") or ""),
                    "status_label": str(object_info.get("status_label") or ""),
                    "decode_category": str(object_info.get("decode_category") or ""),
                    "status_reason": str(object_info.get("status_reason") or ""),
                    "missing_requirements": "; ".join(
                        str(value)
                        for value in object_info.get("missing_requirements", [])
                        if str(value).strip()
                    )
                    if isinstance(object_info.get("missing_requirements"), list)
                    else str(object_info.get("missing_requirements") or ""),
                    "confidence": str(object_info.get("confidence") or ""),
                },
            )
            hkx._hkx_xml_add_text(object_element, "description", object_info.get("description", ""))
            references = object_info.get("references")
            if isinstance(references, list) and references:
                references_element = ET.SubElement(object_element, "references")
                for reference in references:
                    if isinstance(reference, Mapping):
                        ET.SubElement(
                            references_element,
                            "reference",
                            {
                                "offset": hkx._hkx_xml_scalar(reference.get("offset")),
                                "hex_offset": str(reference.get("hex_offset") or ""),
                            "kind": str(reference.get("reference_kind") or ""),
                            "category": str(reference.get("reference_category") or ""),
                            "raw_value": hkx._hkx_xml_scalar(reference.get("raw_value")),
                            "target_record_index": hkx._hkx_xml_scalar(reference.get("target_record_index")),
                            "target_type_index": hkx._hkx_xml_scalar(reference.get("target_type_index")),
                                "target_type_name": str(reference.get("target_type_name") or ""),
                                "confidence": str(reference.get("confidence") or "experimental"),
                            },
                        )
                    else:
                        hkx._hkx_xml_add_text(references_element, "reference", reference)
            decoded_fields = object_info.get("decoded_fields")
            if isinstance(decoded_fields, Mapping) and decoded_fields:
                fields_element = ET.SubElement(object_element, "decodedFields")
                for key, value in decoded_fields.items():
                    hkx._hkx_xml_add_text(fields_element, "field", json.dumps(value, sort_keys=True), name=str(key), encoding="json")
            layout = object_info.get("layout")
            if isinstance(layout, Mapping):
                layout_element = ET.SubElement(
                    object_element,
                    "layout",
                    {
                        "status": str(layout.get("status") or ""),
                        "stride": hkx._hkx_xml_scalar(layout.get("stride")),
                        "field_count": hkx._hkx_xml_scalar(layout.get("field_count")),
                        "truncated_fields": hkx._hkx_xml_scalar(layout.get("truncated_fields")),
                    },
                )
                fields = layout.get("fields")
                if isinstance(fields, list):
                    for field in fields:
                        if not isinstance(field, Mapping):
                            continue
                        field_attrs = {
                            "name": str(field.get("name") or ""),
                            "offset": hkx._hkx_xml_scalar(field.get("offset")),
                            "hex_offset": str(field.get("hex_offset") or ""),
                            "size": hkx._hkx_xml_scalar(field.get("size")),
                            "data_type": str(field.get("data_type") or ""),
                            "confidence": str(field.get("confidence") or ""),
                            "editable": hkx._hkx_xml_scalar(field.get("editable")),
                            "description": str(field.get("description") or ""),
                        }
                        if "item_index" in field:
                            field_attrs["item_index"] = hkx._hkx_xml_scalar(field.get("item_index"))
                        if "item_relative_offset" in field:
                            field_attrs["item_relative_offset"] = hkx._hkx_xml_scalar(field.get("item_relative_offset"))
                        field_element = ET.SubElement(layout_element, "field", field_attrs)
                        if "value" in field:
                            hkx._hkx_xml_add_text(field_element, "value", json.dumps(field.get("value"), sort_keys=True), encoding="json")
                raw_preservation = layout.get("raw_preservation")
                if isinstance(raw_preservation, Mapping):
                    ET.SubElement(
                        layout_element,
                        "rawPreservation",
                        {
                            "offset": hkx._hkx_xml_scalar(raw_preservation.get("offset")),
                            "size": hkx._hkx_xml_scalar(raw_preservation.get("size")),
                            "encoding": str(raw_preservation.get("encoding") or "hex"),
                            "edit_rule": str(raw_preservation.get("edit_rule") or "same_length_only"),
                        },
                    )
            raw_ranges = object_info.get("raw_ranges")
            if isinstance(raw_ranges, list) and raw_ranges:
                ranges_element = ET.SubElement(object_element, "rawRanges")
                for raw_range in raw_ranges:
                    if not isinstance(raw_range, Mapping):
                        continue
                    ET.SubElement(
                        ranges_element,
                        "range",
                        {
                            "name": str(raw_range.get("name") or ""),
                            "offset": hkx._hkx_xml_scalar(raw_range.get("offset")),
                            "hex_offset": str(raw_range.get("hex_offset") or ""),
                            "size": hkx._hkx_xml_scalar(raw_range.get("size")),
                            "encoding": str(raw_range.get("encoding") or "hex"),
                            "edit_rule": str(raw_range.get("edit_rule") or "same_length_only"),
                            "description": str(raw_range.get("description") or ""),
                        },
                    )
            hkx._hkx_xml_add_advanced_editable_values(object_element, object_info.get("editable_values"))


def _hkx_xml_add_editor_model(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    editor_model = document.get("editor_model")
    if isinstance(editor_model, Mapping):
        editor_model_element = ET.SubElement(
            root,
            "editorModel",
            {
                "status": str(editor_model.get("status") or "generated_from_current_decoder"),
                "group_count": hkx._hkx_xml_scalar(editor_model.get("group_count")),
                "row_count": hkx._hkx_xml_scalar(editor_model.get("row_count")),
                "importable_row_count": hkx._hkx_xml_scalar(editor_model.get("importable_row_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(editor_model_element, "description", editor_model.get("description", ""))
        groups = editor_model.get("groups")
        if isinstance(groups, list):
            groups_element = ET.SubElement(editor_model_element, "groups")
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                group_element = ET.SubElement(
                    groups_element,
                    "group",
                    {
                        "key": str(group.get("key") or ""),
                        "title": str(group.get("title") or ""),
                        "row_count": hkx._hkx_xml_scalar(group.get("row_count")),
                        "importable_row_count": hkx._hkx_xml_scalar(group.get("importable_row_count")),
                    },
                )
                rows = group.get("rows")
                if not isinstance(rows, list):
                    continue
                rows_element = ET.SubElement(group_element, "rows")
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    attrs = {
                        "id": str(row.get("id") or ""),
                        "category": str(row.get("category") or ""),
                        "label": str(row.get("label") or ""),
                        "display_label": str(row.get("display_label") or row.get("label") or ""),
                        "subject": str(row.get("subject") or ""),
                        "field": str(row.get("field") or ""),
                        "value": hkx._hkx_xml_scalar(row.get("value")),
                        "original_value": hkx._hkx_xml_scalar(row.get("original_value")),
                        "value_type": str(row.get("value_type") or ""),
                        "importable": "true" if bool(row.get("importable")) else "false",
                        "patch_path": str(row.get("patch_path") or ""),
                        "editor_tab": str(row.get("editor_tab") or ""),
                        "confidence": str(row.get("confidence") or ""),
                        "edit_risk": str(row.get("edit_risk") or ""),
                        "effect": str(row.get("effect") or ""),
                        "source": str(row.get("source") or ""),
                        "viewer_selection_id": str(row.get("viewer_selection_id") or ""),
                    }
                    for key in (
                        "record_index",
                        "item_index",
                        "offset",
                        "hex_offset",
                        "absolute_byte_offset",
                        "hex_absolute_byte_offset",
                        "context_label",
                        "body_name",
                        "socket_name",
                        "fixed_socket_name",
                        "physics_material_name",
                        "shape_index",
                        "shape_type",
                        "context_source",
                        "context_confidence",
                        "identity_path",
                    ):
                        value = row.get(key)
                        if value not in (None, ""):
                            attrs[key] = hkx._hkx_xml_scalar(value)
                    row_element = ET.SubElement(rows_element, "row", attrs)
                    for key, tag_name in (
                        ("explanation", "explanation"),
                        ("if_increased", "ifIncreased"),
                        ("if_decreased", "ifDecreased"),
                        ("safe_edit_hint", "safeEditHint"),
                        ("value_constraints", "valueConstraints"),
                    ):
                        value = row.get(key)
                        if value not in (None, ""):
                            hkx._hkx_xml_add_text(row_element, tag_name, value)


def _hkx_xml_add_relationship_graph(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    relationship_graph = document.get("relationship_graph")
    if isinstance(relationship_graph, Mapping):
        graph_element = ET.SubElement(
            root,
            "relationshipGraph",
            {
                "status": str(relationship_graph.get("status") or "generated_from_current_decoder"),
                "node_count": hkx._hkx_xml_scalar(relationship_graph.get("node_count")),
                "edge_count": hkx._hkx_xml_scalar(relationship_graph.get("edge_count")),
                "reference_edge_count": hkx._hkx_xml_scalar(relationship_graph.get("reference_edge_count")),
                "fixup_backed_reference_edge_count": hkx._hkx_xml_scalar(relationship_graph.get("fixup_backed_reference_edge_count")),
                "identity_edge_count": hkx._hkx_xml_scalar(relationship_graph.get("identity_edge_count")),
                "editable_value_node_count": hkx._hkx_xml_scalar(relationship_graph.get("editable_value_node_count")),
                "byte_patch_edge_count": hkx._hkx_xml_scalar(relationship_graph.get("byte_patch_edge_count")),
                "material_node_count": hkx._hkx_xml_scalar(relationship_graph.get("material_node_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(graph_element, "description", relationship_graph.get("description", ""))
        nodes = relationship_graph.get("nodes")
        if isinstance(nodes, list):
            nodes_element = ET.SubElement(graph_element, "nodes")
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue
                attrs = {
                    "id": str(node.get("id") or ""),
                    "kind": str(node.get("kind") or ""),
                    "label": str(node.get("label") or ""),
                }
                for key, value in node.items():
                    if key in {"id", "kind", "label"} or value is None:
                        continue
                    attrs[str(key)] = hkx._hkx_xml_scalar(value)
                ET.SubElement(nodes_element, "node", attrs)
        edges = relationship_graph.get("edges")
        if isinstance(edges, list):
            edges_element = ET.SubElement(graph_element, "edges")
            for edge in edges:
                if not isinstance(edge, Mapping):
                    continue
                attrs = {
                    "source": str(edge.get("source") or ""),
                    "target": str(edge.get("target") or ""),
                    "relation": str(edge.get("relation") or ""),
                }
                for key, value in edge.items():
                    if key in {"source", "target", "relation"} or value is None:
                        continue
                    attrs[str(key)] = hkx._hkx_xml_scalar(value)
                ET.SubElement(edges_element, "edge", attrs)


def _hkx_xml_add_descriptions(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    descriptions = document.get("editable_value_descriptions")
    if isinstance(descriptions, Mapping):
        descriptions_element = ET.SubElement(root, "editableValueDescriptions")
        for field_name, description in descriptions.items():
            hkx._hkx_xml_add_text(descriptions_element, "field", description, name=str(field_name))


def _hkx_xml_add_value_layouts(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    value_layouts = document.get("editable_value_layouts")
    if isinstance(value_layouts, Mapping):
        layouts_element = ET.SubElement(root, "editableValueLayouts")
        for field_name, layout in value_layouts.items():
            hkx._hkx_xml_add_value_layout(layouts_element, str(field_name), layout)


def _hkx_xml_add_limitations(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    limitations = document.get("limitations")
    if isinstance(limitations, list):
        limitations_element = ET.SubElement(root, "limitations")
        for limitation in limitations:
            hkx._hkx_xml_add_text(limitations_element, "limitation", limitation)


def _hkx_xml_add_reimport_policy(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    reimport_policy = document.get("reimport_policy")
    if isinstance(reimport_policy, Mapping):
        policy_element = ET.SubElement(
            root,
            "reimportPolicy",
            {
                "status": str(reimport_policy.get("status") or ""),
                "write_target": str(reimport_policy.get("write_target") or ""),
            },
        )
        hkx._hkx_xml_add_text(policy_element, "description", reimport_policy.get("description", ""))
        for list_key, tag_name in (
            ("ignored_metadata", "ignoredMetadata"),
            ("rejected_changes", "rejectedChange"),
            ("allowed_edits", "allowedEdit"),
        ):
            values = reimport_policy.get(list_key)
            if not isinstance(values, list):
                continue
            group_element = ET.SubElement(policy_element, list_key)
            for value in values:
                hkx._hkx_xml_add_text(group_element, tag_name, value)


def _hkx_xml_add_schema_observations(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    schema_observations = document.get("schema_observations")
    if isinstance(schema_observations, Mapping):
        observations_element = ET.SubElement(
            root,
            "schemaObservations",
            {"status": str(schema_observations.get("status") or "read_only_research")},
        )
        hkx._hkx_xml_add_text(observations_element, "description", schema_observations.get("description", ""))
        type_table = schema_observations.get("type_table")
        if isinstance(type_table, list):
            type_table_element = ET.SubElement(observations_element, "typeTable")
            for type_info in type_table:
                if not isinstance(type_info, Mapping):
                    continue
                type_element = ET.SubElement(
                    type_table_element,
                    "type",
                    {
                        "index": hkx._hkx_xml_scalar(type_info.get("index")),
                        "name": str(type_info.get("name") or ""),
                        "display_name": str(type_info.get("display_name") or ""),
                    },
                )
                parameters = type_info.get("template_parameters")
                if isinstance(parameters, list):
                    for parameter in parameters:
                        if isinstance(parameter, Mapping):
                            ET.SubElement(
                                type_element,
                                "templateParameter",
                                {
                                    "name": str(parameter.get("name") or ""),
                                    "value": hkx._hkx_xml_scalar(parameter.get("value")),
                                },
                            )
        payload_summaries = schema_observations.get("record_payload_summaries")
        if isinstance(payload_summaries, list):
            payloads_element = ET.SubElement(observations_element, "recordPayloadSummaries")
            for payload_summary in payload_summaries:
                if not isinstance(payload_summary, Mapping):
                    continue
                summary_element = ET.SubElement(
                    payloads_element,
                    "record",
                    {
                        "index": hkx._hkx_xml_scalar(payload_summary.get("record_index")),
                        "type_index": hkx._hkx_xml_scalar(payload_summary.get("type_index")),
                        "type_name": str(payload_summary.get("type_name") or ""),
                        "count": hkx._hkx_xml_scalar(payload_summary.get("count")),
                        "data_offset": hkx._hkx_xml_scalar(payload_summary.get("data_offset")),
                        "byte_length": hkx._hkx_xml_scalar(payload_summary.get("byte_length")),
                        "inferred_stride": hkx._hkx_xml_scalar(payload_summary.get("inferred_stride")),
                    },
                )
                for line in payload_summary.get("lines", []) if isinstance(payload_summary.get("lines"), list) else []:
                    hkx._hkx_xml_add_text(summary_element, "line", line)
