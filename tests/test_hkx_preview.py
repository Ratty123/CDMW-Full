import copy
import json
import os
from pathlib import Path
import threading
import unittest
import struct
import tempfile
import xml.etree.ElementTree as ET
from unittest import mock

from cdmw.core.archive_modding import (
    apply_hkx_editable_geometry_document,
    apply_hkx_editable_geometry_json,
    apply_hkx_editable_geometry_xml,
    build_hkx_converter_corpus_csv,
    build_hkx_corpus_evidence_from_report,
    build_hkx_converter_corpus_report,
    build_hkx_descriptor_hint_from_xml_text,
    build_hkx_editable_geometry_document,
    build_hkx_editable_geometry_json,
    build_hkx_editable_geometry_xml,
    build_hkx_havok_xml_view_xml,
    build_hkx_physics_overlay_from_document,
    build_hkx_preview,
    load_hkx_corpus_evidence_json,
    _hkx_xml_add_value_layout,
    parse_hkx_tagfile_summary,
)
from cdmw.models import RunCancelled


def _tag_item(marker: bytes, payload: bytes, *, flags: int = 0x40000000) -> bytes:
    length = 4 + len(payload) + 4
    return (flags | length).to_bytes(4, "big") + marker + payload


def _tna1_payload(type_name_count: int) -> bytes:
    return bytes((type_name_count + 1,)) + b"".join(bytes((index, 0)) for index in range(type_name_count))


class HkxPreviewTests(unittest.TestCase):
    def _modern_hkx_bytes(self) -> bytes:
        type_names = b"\0".join(
            (
                b"hknpCompoundShape",
                b"hknpConvexShape",
                b"hknpShapeProperties::Entry",
                b"hkFloat3",
                b"hkVector4",
                b"hknpConvexHull::Face",
                b"hkUint8",
                b"hknpShapeMassProperties",
            )
        ) + b"\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000003).to_bytes(4, "little") + (160).to_bytes(4, "little") + (3).to_bytes(4, "little"),
                (0x20000004).to_bytes(4, "little") + (208).to_bytes(4, "little") + (4).to_bytes(4, "little"),
                (0x20000005).to_bytes(4, "little") + (256).to_bytes(4, "little") + (4).to_bytes(4, "little"),
                (0x20000006).to_bytes(4, "little") + (320).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000007).to_bytes(4, "little") + (328).to_bytes(4, "little") + (8).to_bytes(4, "little"),
                (0x10000008).to_bytes(4, "little") + (336).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(400)
        struct.pack_into("<II", data_payload, 32 + 0x30, 0x58, 4)
        struct.pack_into("<ff", data_payload, 32 + 0x68, 0.125, 0.5)
        for index, vector in enumerate(
            (
                (-1.0, 0.0, -1.0),
                (-1.0, 2.0, 1.0),
                (1.0, 0.0, -1.0),
                (1.0, 2.0, 1.0),
            )
        ):
            struct.pack_into("<fff", data_payload, 208 + index * 12, *vector)
        for index, vector in enumerate(
            (
                (1.0, 0.0, 0.0, -1.0),
                (-1.0, 0.0, 0.0, -1.0),
                (0.0, 1.0, 0.0, -2.0),
                (0.0, -1.0, 0.0, 0.0),
            )
        ):
            struct.pack_into("<ffff", data_payload, 256 + index * 16, *vector)
        data_payload[320:328] = bytes((0, 0, 4, 127, 4, 0, 4, 127))
        data_payload[328:336] = bytes((0, 1, 3, 2, 0, 2, 3, 1))
        for index, value in enumerate(
            (
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        ):
            struct.pack_into("<f", data_payload, 336 + index * 4, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(8), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        return (len(body) + 4).to_bytes(4, "big") + body

    def _mesh_shape_hkx_bytes(self) -> bytes:
        type_names = b"\0".join(
            (
                b"hkArray",
                b"hkRefPtr",
                b"hknpShape",
                b"hkBuiltinContainerAllocator",
                b"hknpMeshShape",
                b"hknpMeshShape::ShapeTagTableEntry",
                b"hkcdSimdTreeNamespace::Node",
                b"hknpMeshShape::GeometrySection",
                b"hknpAabb8TreeNode",
                b"hknpMeshShape::GeometrySection::Primitive",
                b"hkUint8",
            )
        ) + b"\0\xff"
        record_specs = (
            (0x10000001, 0, 1),
            (0x20000002, 16, 1),
            (0x10000005, 32, 1),
            (0x20000006, 96, 2),
            (0x20000007, 128, 3),
            (0x20000008, 192, 1),
            (0x20000009, 256, 12),
            (0x2000000A, 512, 24),
            (0x2000000B, 768, 128),
            (0x2000000B, 896, 64),
        )
        records = b"".join(
            raw.to_bytes(4, "little") + offset.to_bytes(4, "little") + count.to_bytes(4, "little")
            for raw, offset, count in record_specs
        )
        data_payload = bytearray(960)
        struct.pack_into("<IIIIIIII", data_payload, 192, 64, 12, 312, 24, 560, 128, 680, 2)
        data_payload[512:512 + 24 * 4] = bytes((0, 1, 2, 3)) * 24
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(11), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        return (len(body) + 4).to_bytes(4, "big") + body

    def test_modern_tagfile_preview_reports_sdk_and_embedded_hknp_types(self) -> None:
        data = self._modern_hkx_bytes()

        preview = build_hkx_preview(data, "character/bin/body.hkx")

        self.assertIn("Havok SDK version: 20240200 (2024.2.0)", preview.preview_text)
        self.assertIn("Detected tag sections: TAG0, SDKV, DATA, TNA1, TPAD, INDX, ITEM", preview.preview_text)
        self.assertIn("Modern Havok Physics", preview.preview_text)
        self.assertIn("hknpCompoundShape", preview.preview_text)
        self.assertIn("Inferred ITEM records: 8", preview.preview_text)
        self.assertIn("hknpShapeProperties::Entry: 1", preview.preview_text)
        self.assertIn("Collision geometry hints:", preview.preview_text)
        self.assertIn("vertices=4; planes=4; faces=2; face-index bytes=8", preview.preview_text)
        self.assertIn("approx center=(0, 1, 0), extent=(2, 2, 2)", preview.preview_text)
        self.assertIn("face vertex loops: [0, 1, 3, 2]; [0, 2, 3, 1]", preview.preview_text)
        self.assertIn("DATA payload summaries:", preview.preview_text)
        self.assertIn("bounds: x=(-1..1), y=(0..2), z=(-1..1)", preview.preview_text)
        self.assertIn("object words (unverified layout)", preview.preview_text)
        self.assertTrue(any("Inferred collision geometry hints" in line for line in preview.detail_lines))
        self.assertTrue(any("modern Havok Physics" in line for line in preview.detail_lines))

    def test_modern_tagfile_summary_decodes_tst1_names_and_item_records(self) -> None:
        data = self._modern_hkx_bytes()

        summary = parse_hkx_tagfile_summary(data)

        self.assertEqual("20240200", summary.sdk_version)
        self.assertTrue(summary.size_matches)
        self.assertEqual(9, summary.declared_type_name_count)
        self.assertEqual(
            [
                "hknpCompoundShape",
                "hknpConvexShape",
                "hknpShapeProperties::Entry",
                "hkFloat3",
                "hkVector4",
                "hknpConvexHull::Face",
                "hkUint8",
                "hknpShapeMassProperties",
            ],
            summary.type_names,
        )
        self.assertEqual(8, len(summary.type_infos))
        self.assertEqual(8, len(summary.item_records))
        self.assertEqual("hknpCompoundShape", summary.item_records[0].type_name)
        self.assertEqual("hknpConvexShape", summary.item_records[1].type_name)
        self.assertEqual(32, summary.item_records[1].data_offset)
        self.assertEqual(1, summary.item_records[1].count)
        self.assertEqual(0x10000000, summary.item_records[1].flags)
        self.assertEqual("hknpShapeProperties::Entry", summary.item_records[2].type_name)
        self.assertEqual("hkFloat3", summary.item_records[3].type_name)
        self.assertEqual(1, len(summary.collision_geometry_hints))
        geometry_hint = summary.collision_geometry_hints[0]
        self.assertEqual("hknpConvexShape", geometry_hint.shape_type)
        self.assertEqual(4, geometry_hint.vertex_count)
        self.assertEqual(4, geometry_hint.plane_count)
        self.assertEqual(2, geometry_hint.face_count)
        self.assertEqual(8, geometry_hint.face_index_count)
        self.assertEqual([(0, 1, 3, 2), (0, 2, 3, 1)], geometry_hint.face_vertex_indices)
        self.assertEqual((-1.0, 0.0, -1.0), geometry_hint.bounds_min)
        self.assertEqual((1.0, 2.0, 1.0), geometry_hint.bounds_max)
        self.assertEqual((0.0, 1.0, 0.0), geometry_hint.center)
        self.assertEqual((2.0, 2.0, 2.0), geometry_hint.extent)
        float3_summary = next(item for item in summary.item_payload_summaries if item.record_index == 3)
        self.assertIn("bounds: x=(-1..1), y=(0..2), z=(-1..1)", float3_summary.lines)

    def test_editable_hkx_geometry_document_exports_and_reapplies_fixed_size_vertex_edits(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")

        self.assertEqual("cdmw_hkx_geometry_patch_v1", document["format"])
        self.assertEqual("cdmw_crimson_desert_hkx_converter_v1", document["converter_format"])
        self.assertIn("converter_report", document)
        self.assertIn("tag_sections", document)
        self.assertIn("type_registry", document)
        self.assertIn("havok_xml_view", document)
        self.assertIn("objects", document)
        self.assertIn("editor_model", document)
        self.assertIn("relationship_graph", document)
        self.assertIn("raw_records", document)
        self.assertIn("collision_shapes", document)
        self.assertEqual("strict_fixed_size_patch_only", document["reimport_policy"]["status"])
        self.assertIn("ITEM record count changes", document["reimport_policy"]["rejected_changes"])
        compatibility = document["cdmw_hkx_compatibility"]
        self.assertEqual("preview_linked", compatibility["status"])
        self.assertTrue(compatibility["gates"]["unknown_bytes_preserved"])
        self.assertGreater(compatibility["gates"]["editable_patch_targets"], 0)
        self.assertGreater(compatibility["gates"]["preview_linked_targets"], 0)
        converter_report = document["converter_report"]
        self.assertEqual("preview_linked", converter_report["status"])
        self.assertEqual("preview_linked", converter_report["cdmw_hkx_compatibility_status"])
        self.assertGreater(converter_report["decoded_coverage"], 0.0)
        self.assertEqual(1.0, converter_report["payload_record_coverage"])
        self.assertGreaterEqual(converter_report["decoded_field_count"], 0)
        self.assertGreater(converter_report["editable_slot_count"], 0)
        self.assertGreaterEqual(converter_report["reference_candidate_count"], 0)
        self.assertIn("decode_coverage_by_type", converter_report)
        self.assertTrue(any(row["type_name"] == "hknpConvexShape" for row in converter_report["decode_coverage_by_type"]))
        havok_xml_view = document["havok_xml_view"]
        self.assertEqual("cdmw_havok_xml_view_v1", havok_xml_view["format"])
        self.assertFalse(havok_xml_view["official_havok_xml"])
        self.assertGreater(havok_xml_view["exported_object_count"], 0)
        self.assertEqual("read_only_parity_view", havok_xml_view["hkpackfile_view"]["status"])
        self.assertEqual("__data__", havok_xml_view["hkpackfile_view"]["section_name"])
        self.assertTrue(any(row["name"] == "hknpConvexShape" for row in havok_xml_view["hkclasses"]))
        self.assertTrue(any(obj["class"] == "hknpConvexShape" for obj in havok_xml_view["hkobjects"]))
        shapes = document["shapes"]
        self.assertIsInstance(shapes, list)
        first_shape = shapes[0]
        self.assertIn("vertices", first_shape)
        self.assertIn("planes", first_shape)
        self.assertIn("faces", first_shape)
        self.assertIn("mass_properties", first_shape)
        self.assertIn("shape_payload", first_shape)
        self.assertIn("hull_topology", first_shape)
        self.assertTrue(first_shape["faces_read_only"])
        self.assertIn("vertices", first_shape["editable_fields"])
        self.assertIn("mass_properties", first_shape["editable_fields"])
        self.assertIn("shape_payload", first_shape["editable_fields"])
        self.assertIn("hull_topology", first_shape["editable_fields"])
        self.assertIn("description", document)
        self.assertIn("editable_value_descriptions", document)
        self.assertIn("vertices", document["editable_value_descriptions"])
        self.assertIn("editable_value_layouts", document)
        self.assertIn("vertices", document["editable_value_layouts"])
        self.assertIn("descriptions", first_shape)
        self.assertIn("vertices", first_shape["descriptions"])
        self.assertIn("faces", first_shape["descriptions"])
        self.assertIn("value_layouts", first_shape)
        self.assertIn("vertices", first_shape["value_layouts"])
        self.assertIn("mass_properties", first_shape["value_layouts"])
        self.assertIn("shape_payload", first_shape["value_layouts"])
        self.assertIn("hull_topology", first_shape["value_layouts"])
        self.assertEqual(2, len(first_shape["hull_topology"]["face_records"]))
        self.assertEqual(8, len(first_shape["hull_topology"]["face_indices"]))
        self.assertIn("schema_observations", document)
        observations = document["schema_observations"]
        self.assertIn("record_payload_summaries", observations)
        self.assertIn("advanced_record_payloads", document)
        advanced_payloads = document["advanced_record_payloads"]
        self.assertIsInstance(advanced_payloads, list)
        self.assertEqual(len(advanced_payloads), len(document["objects"]))
        self.assertEqual(len(advanced_payloads), len(document["raw_records"]))
        self.assertTrue(any(record["type_name"] == "hknpConvexShape" for record in advanced_payloads))
        first_object = document["objects"][0]
        self.assertIn("layout", first_object)
        self.assertIn("raw_ranges", first_object)
        self.assertEqual("same_length_only", first_object["raw_ranges"][0]["edit_rule"])
        editor_model = document["editor_model"]
        self.assertEqual("generated_from_current_decoder", editor_model["status"])
        self.assertGreater(editor_model["row_count"], 0)
        editor_groups = {group["key"]: group for group in editor_model["groups"]}
        self.assertIn("collision_shapes", editor_groups)
        self.assertIn("object_records", editor_groups)
        self.assertTrue(
            any(
                row["editor_tab"] == "Collision Editor"
                and row["importable"]
                and row["viewer_selection_id"] == "shape/0"
                for row in editor_groups["collision_shapes"]["rows"]
            )
        )
        graph = document["relationship_graph"]
        self.assertGreater(graph["node_count"], 0)
        self.assertTrue(any(node["kind"] == "item_record" for node in graph["nodes"]))
        self.assertTrue(any(node["kind"] == "editable_value" for node in graph["nodes"]))
        self.assertTrue(any(edge["relation"] == "contains" for edge in graph["edges"]))
        self.assertTrue(any(edge["relation"] == "has_editable_value" for edge in graph["edges"]))
        self.assertTrue(any(edge["relation"] == "writes_byte_offset" for edge in graph["edges"]))
        self.assertIn("reference_edge_count", graph)
        self.assertGreater(graph["identity_edge_count"], 0)
        self.assertGreater(graph["editable_value_node_count"], 0)
        self.assertGreater(graph["byte_patch_edge_count"], 0)
        first_payload = advanced_payloads[0]
        self.assertIn("payload_hex", first_payload)
        self.assertIn("description", first_payload)
        self.assertIn("interpretation", first_payload)
        self.assertIn("layout", first_payload)
        convex_payload = next(record for record in advanced_payloads if record["type_name"] == "hknpConvexShape")
        self.assertIn("offset_count_pairs", convex_payload["interpretation"])
        convex_object = next(record for record in document["objects"] if record["type_name"] == "hknpConvexShape")
        self.assertTrue(any(field["name"] == "vertices_offset_count" for field in convex_object["layout"]["fields"]))
        face_payload = next(record for record in advanced_payloads if record["type_name"] == "hknpConvexHull::Face")
        self.assertEqual("face_records", face_payload["editable_values"]["kind"])
        compound_summary = next(
            item for item in observations["record_payload_summaries"] if item["type_name"] == "hknpCompoundShape"
        )
        self.assertTrue(any("object words" in line for line in compound_summary["lines"]))
        byte_patch_entry = document["byte_patch_map"]["entries"][0]
        self.assertIn("original_bytes_hex", byte_patch_entry)
        self.assertIn("decoded_value", byte_patch_entry)
        self.assertEqual("fixed_size_value_only", byte_patch_entry["edit_rule"])

        edited_document = copy.deepcopy(document)
        edited_document["shapes"][0]["vertices"][0] = [-2.0, 0.5, -2.5]
        edited_document["shapes"][0]["mass_properties"]["float_rows"][3] = [9.0, 8.0, 7.0, 6.0]
        edited_document["shapes"][0]["shape_payload"]["float_slots"][0]["value"] = 0.25
        edited_document["shapes"][0]["hull_topology"]["face_indices"][0] = 1
        result = apply_hkx_editable_geometry_document(data, edited_document)

        self.assertEqual(len(data), len(result.data))
        self.assertIn("shape[0].vertices", result.changed_fields)
        self.assertIn("shape[0].mass_properties", result.changed_fields)
        self.assertIn("shape[0].shape_payload", result.changed_fields)
        self.assertIn("shape[0].hull_topology.face_indices", result.changed_fields)
        reparsed_document = build_hkx_editable_geometry_document(result.data, "object/test.hkx")
        self.assertEqual([-2.0, 0.5, -2.5], reparsed_document["shapes"][0]["vertices"][0])
        self.assertEqual(document["shapes"][0]["planes"], reparsed_document["shapes"][0]["planes"])
        self.assertEqual([9.0, 8.0, 7.0, 6.0], reparsed_document["shapes"][0]["mass_properties"]["float_rows"][3])
        self.assertEqual(0.25, reparsed_document["shapes"][0]["shape_payload"]["float_slots"][0]["value"])
        self.assertEqual(1, reparsed_document["shapes"][0]["hull_topology"]["face_indices"][0])

    def test_editable_hkx_geometry_document_no_edit_round_trip_is_byte_identical(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")

        result = apply_hkx_editable_geometry_document(data, copy.deepcopy(document))

        self.assertEqual(data, result.data)
        self.assertEqual([], result.changed_fields)
        self.assertEqual([], result.warnings)

    def test_hkx_editor_model_and_relationship_graph_are_exported_to_xml_and_ignored_on_import(self) -> None:
        data = self._modern_hkx_bytes()
        xml_text = build_hkx_editable_geometry_xml(data, "object/test.hkx")
        root = ET.fromstring(xml_text)

        self.assertIsNotNone(root.find("./editorModel"))
        self.assertIsNotNone(root.find("./editorModel/groups/group/rows/row"))
        self.assertIsNotNone(root.find("./relationshipGraph"))
        self.assertIsNotNone(root.find("./relationshipGraph/nodes/node[@kind='item_record']"))
        self.assertIsNotNone(root.find("./relationshipGraph/nodes/node[@kind='editable_value']"))
        self.assertIsNotNone(root.find("./relationshipGraph/edges/edge[@relation='contains']"))
        self.assertIsNotNone(root.find("./relationshipGraph/edges/edge[@relation='has_editable_value']"))
        self.assertIsNotNone(root.find("./relationshipGraph/edges/edge[@relation='writes_byte_offset']"))
        self.assertIsNotNone(root.find("./relationshipGraph[@reference_edge_count]"))
        self.assertIsNotNone(root.find("./relationshipGraph[@identity_edge_count]"))
        self.assertIsNotNone(root.find("./relationshipGraph[@editable_value_node_count]"))
        self.assertIsNotNone(root.find("./relationshipGraph[@byte_patch_edge_count]"))
        self.assertIsNotNone(root.find("./havokXmlView"))
        self.assertIsNotNone(root.find("./havokXmlView/hkobject/field"))
        self.assertIsNotNone(root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject/hkparam"))
        self.assertIsNotNone(root.find("./hkxXmlParityReport"))

        editor_row = root.find("./editorModel/groups/group/rows/row")
        self.assertIsNotNone(editor_row)
        assert editor_row is not None
        editor_row.set("value", "999999")
        editor_row.set("label", "ignored editor label")
        relationship_node = root.find("./relationshipGraph/nodes/node")
        self.assertIsNotNone(relationship_node)
        assert relationship_node is not None
        relationship_node.set("label", "ignored graph label")
        havok_field = root.find("./havokXmlView/hkobject/field")
        self.assertIsNotNone(havok_field)
        assert havok_field is not None
        havok_field.set("description", "ignored Havok-style browser note")
        value = havok_field.find("./value")
        if value is not None:
            value.text = "999999"
        hkparam = root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject/hkparam")
        self.assertIsNotNone(hkparam)
        assert hkparam is not None
        hkparam.text = "999999"
        parity_report = root.find("./hkxXmlParityReport")
        self.assertIsNotNone(parity_report)
        assert parity_report is not None
        parity_report.set("havok_like_params_emitted", "999999")

        result = apply_hkx_editable_geometry_xml(data, ET.tostring(root, encoding="unicode"))

        self.assertEqual(data, result.data)
        self.assertEqual([], result.changed_fields)

    def test_standalone_havok_xml_view_uses_hkpackfile_shape(self) -> None:
        data = self._modern_hkx_bytes()
        xml_text = build_hkx_havok_xml_view_xml(data, "object/test.hkx")
        root = ET.fromstring(xml_text)

        self.assertEqual("hkpackfile", root.tag)
        self.assertEqual("false", root.get("official_havok_xml"))
        self.assertEqual("object/test.hkx", root.get("source"))
        self.assertIsNotNone(root.find("./hksection[@name='__types__']/hkobject[@class='hkClass']/hkparam[@name='name']"))
        self.assertIsNotNone(root.find("./hksection[@name='__data__']"))
        self.assertIsNotNone(root.find("./hksection/hkobject[@class='hknpConvexShape']"))
        self.assertIsNotNone(root.find("./hksection/hkobject/hkparam"))
        self.assertIn("Read-only CDMW Havok XML parity view", xml_text)

    def test_havok_xml_view_exports_reference_candidates_as_record_refs(self) -> None:
        data = self._array_ref_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "physics/array_refs.hkx")
        havok_view = document["havok_xml_view"]
        referenced_objects = [obj for obj in havok_view["hkobjects"] if obj["reference_count"]]
        self.assertTrue(referenced_objects)
        self.assertTrue(
            any(
                field.get("reference_target") == "#record2" and field.get("hkparam_text") == "#record2"
                for obj in referenced_objects
                for field in obj["fields"]
            )
        )

        cdmw_xml = build_hkx_editable_geometry_xml(data, "physics/array_refs.hkx")
        cdmw_root = ET.fromstring(cdmw_xml)
        self.assertIsNotNone(cdmw_root.find("./havokXmlView/hkobject/references/reference[@target='#record2']"))
        self.assertIsNotNone(cdmw_root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject/hkparam[@reference_target='#record2']"))

        standalone_xml = build_hkx_havok_xml_view_xml(data, "physics/array_refs.hkx")
        standalone_root = ET.fromstring(standalone_xml)
        ref_param = standalone_root.find("./hksection/hkobject/hkparam[@cdmw_reference_target='#record2']")
        self.assertIsNotNone(ref_param)
        assert ref_param is not None
        self.assertEqual("#record2", ref_param.text)

    def test_havok_xml_view_exports_recovered_members_arrays_and_parity_report(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        havok_view = document["havok_xml_view"]

        convex_class = next(row for row in havok_view["hkclasses"] if row["name"] == "hknpConvexShape")
        convex_members = {member["name"]: member for member in convex_class["members"]}
        self.assertEqual("synthetic_recovered_hkClass", convex_class["metadata_status"])
        self.assertFalse(convex_class["real_hkclass_metadata_recovered"])
        self.assertEqual("TNA1_TYPE_NAMES_PLUS_CDMW_LAYOUT_RECOVERY", convex_class["metadata_source"])
        self.assertTrue(str(convex_class["signature"]).startswith("0x"))
        self.assertEqual("hkArray<hkFloat3>", convex_members["vertices"]["type"])
        self.assertEqual("TYPE_ARRAY", convex_members["vertices"]["member_type"])
        self.assertEqual("hkFloat3", convex_members["vertices"]["subtype"])
        self.assertEqual(["hkFloat3"], convex_members["vertices"]["template_arguments"])
        self.assertEqual("strong inference", convex_members["vertices"]["confidence"])
        self.assertEqual("array_data_reference", convex_members["vertices"]["reference_status"])
        convex_object = next(obj for obj in havok_view["hkobjects"] if obj["class"] == "hknpConvexShape")
        convex_params = {field["hkparam_name"]: field for field in convex_object["fields"]}
        self.assertEqual("#record3", convex_params["vertices"]["hkparam_text"])
        self.assertEqual(4, convex_params["vertices"]["numelements"])
        self.assertEqual("hkArray", convex_params["vertices"]["array_status"])
        self.assertEqual("array_data_reference", convex_params["vertices"]["reference_category"])
        self.assertEqual("#record4", convex_params["planes"]["hkparam_text"])
        self.assertEqual("#record5", convex_params["faces"]["hkparam_text"])
        self.assertEqual("#record6", convex_params["faceIndices"]["hkparam_text"])
        float3_object = next(obj for obj in havok_view["hkobjects"] if obj["class"] == "hkFloat3")
        values_param = next(field for field in float3_object["fields"] if field["hkparam_name"] == "values")
        self.assertEqual("hkArray<hkFloat3>", values_param["type"])
        self.assertIn("-1 0 -1", values_param["hkparam_text"])

        parity_report = document["hkx_xml_parity_report"]
        self.assertEqual("cdmw_hkx_xml_parity_report_v1", parity_report["format"])
        self.assertGreater(parity_report["havok_like_params_emitted"], 0)
        self.assertFalse(parity_report["import_safety"]["havok_xml_view_importable"])
        self.assertGreater(parity_report["array_params_with_numelements"], 0)
        self.assertTrue(any(row["class"] == "hknpConvexShape" for row in parity_report["class_parity"]))

        readiness = document["hkclass_metadata_readiness"]
        self.assertEqual("cdmw_hkx_hkclass_metadata_readiness_v1", readiness["format"])
        self.assertEqual("synthetic_recovered_hkClass", readiness["__types_section_status"])
        self.assertFalse(readiness["real_hkclass_metadata_recovered"])
        self.assertGreater(readiness["synthetic_class_count"], 0)
        self.assertIn("member_type_codes", readiness["unresolved_real_metadata_counts"])
        self.assertIn("member_flags", readiness["unresolved_real_metadata_counts"])
        self.assertIn("base_classes", readiness["unresolved_real_metadata_counts"])
        self.assertIn("enum_refs", readiness["unresolved_real_metadata_counts"])
        self.assertIn("signatures", readiness["unresolved_real_metadata_counts"])
        self.assertIn("versions", readiness["unresolved_real_metadata_counts"])
        self.assertIn("default_values", readiness["unresolved_real_metadata_counts"])
        self.assertIn("template_refs", readiness["unresolved_real_metadata_counts"])
        self.assertIn("status", readiness["native_model_graph"])
        self.assertTrue(readiness["native_model_graph"]["python_builds_richer_graph_export"])
        self.assertIsInstance(readiness["native_model_graph"]["native_object_graph_available"], bool)
        self.assertIsInstance(
            readiness["native_model_graph"]["native_fixup_backed_reference_graph_available"],
            bool,
        )
        self.assertIsInstance(readiness["native_model_graph"]["native_owner_array_resolution_available"], bool)
        self.assertIsInstance(readiness["native_model_graph"]["native_root_container_semantics_available"], bool)
        self.assertIn("native_model_graph_node_count", readiness["native_model_graph"])
        self.assertIn("native_model_graph_edge_count", readiness["native_model_graph"])
        self.assertEqual(
            {"fixup_backed_object_refs", "owner_arrays", "root_container_semantics", "native_export_graph"},
            {capability["key"] for capability in readiness["native_model_graph"]["required_native_graph_capabilities"]},
        )
        self.assertIn(readiness["no_edit_binary_writer"]["status"], {"byte_identical", "not_started"})
        self.assertIsInstance(readiness["no_edit_binary_writer"]["byte_identical_no_edit_rebuild_supported"], bool)
        self.assertIn(
            "representative_byte_identity",
            {requirement["key"] for requirement in readiness["no_edit_binary_writer"]["requirements"]},
        )
        self.assertEqual("native_no_edit_read_model_write_byte_identity", readiness["biggest_remaining_gate"]["key"])
        self.assertEqual("highest", readiness["biggest_remaining_gate"]["priority"])
        self.assertIn(
            readiness["biggest_remaining_gate"]["status"],
            {"blocked", "file_level_passed_representative_corpus_pending"},
        )
        self.assertIsInstance(readiness["biggest_remaining_gate"]["native_read_model_write_available"], bool)
        self.assertTrue(readiness["biggest_remaining_gate"]["havok_xml_import_blocked"])
        self.assertIn("object_hkx", readiness["biggest_remaining_gate"]["representative_file_roles"])
        self.assertEqual("partial_synthetic_recovery", readiness["class_internals"]["status"])
        self.assertFalse(readiness["class_internals"]["real_class_internals_recovered"])
        self.assertTrue(
            any(target["class"] == "hknpMeshShape" for target in readiness["class_internals"]["targets"])
        )
        hard_targets = {target["key"]: target for target in readiness["hard_decoder_targets"]["targets"]}
        self.assertEqual("open_hard_decoder_targets", readiness["hard_decoder_targets"]["status"])
        self.assertFalse(hard_targets["hknp_mesh_primitive_bit_layout"]["resolved"])
        self.assertFalse(hard_targets["hknp_mesh_aabb_tree"]["resolved"])
        self.assertFalse(hard_targets["hknp_mesh_shape_tags"]["resolved"])
        self.assertFalse(hard_targets["compound_child_transforms"]["resolved"])
        self.assertFalse(hard_targets["compressed_mass_properties"]["resolved"])
        self.assertFalse(hard_targets["material_property_entries"]["resolved"])
        self.assertFalse(hard_targets["skeleton_animation_containers"]["resolved"])
        gui_targets = {target["key"]: target for target in readiness["gui_readiness"]["targets"]}
        self.assertEqual("partial_user_friendly_modding", readiness["gui_readiness"]["status"])
        self.assertEqual("partial", gui_targets["visual_object_value_linking"]["status"])
        self.assertEqual("partial", gui_targets["value_formatting_and_color"]["status"])
        self.assertEqual("missing", gui_targets["before_after_preview"]["status"])
        self.assertEqual("missing", gui_targets["preset_workflows"]["status"])

        xml_text = build_hkx_editable_geometry_xml(data, "object/test.hkx")
        xml_root = ET.fromstring(xml_text)
        self.assertIsNotNone(
            xml_root.find(
                "./havokXmlView/hkpackfileView/hkpackfile/hksection[@name='__types__']"
                "/hkobject[@class='hkClass']/hkparam[@name='members']/member[@name='vertices'][@member_type='TYPE_ARRAY']"
            )
        )
        self.assertIsNotNone(xml_root.find("./hkxXmlParityReport/classParity/class[@name='hknpConvexShape']"))
        self.assertIsNotNone(
            xml_root.find(
                "./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject[@class='hknpConvexShape']"
                "/hkparam[@name='vertices'][@numelements='4']"
            )
        )
        self.assertIsNotNone(
            xml_root.find(
                "./hkclassMetadataReadiness[@real_hkclass_metadata_recovered='false']"
                "/missingRealHkclassMetadata/requirement[@key='member_type_codes']"
            )
        )
        self.assertIsNotNone(xml_root.find("./hkclassMetadataReadiness/nativeModelGraph"))
        self.assertIsNotNone(
            xml_root.find(
                "./hkclassMetadataReadiness/nativeModelGraph/requiredNativeGraphCapabilities"
                "/capability[@key='fixup_backed_object_refs']"
            )
        )
        no_edit_xml = xml_root.find("./hkclassMetadataReadiness/noEditBinaryWriter")
        self.assertIsNotNone(no_edit_xml)
        assert no_edit_xml is not None
        self.assertIn(no_edit_xml.get("status"), {"byte_identical", "not_started"})
        self.assertIsNotNone(
            no_edit_xml.find("./requirements/requirement[@key='representative_byte_identity']")
        )
        self.assertIsNotNone(
            xml_root.find(
                "./hkclassMetadataReadiness/biggestRemainingGate"
                "[@key='native_no_edit_read_model_write_byte_identity']"
            )
        )
        self.assertIsNotNone(
            xml_root.find("./hkclassMetadataReadiness/classInternals/targets/target[@class='hknpMeshShape']")
        )
        self.assertIsNotNone(
            xml_root.find(
                "./hkclassMetadataReadiness/hardDecoderTargets/targets"
                "/target[@key='hknp_mesh_primitive_bit_layout']"
            )
        )
        self.assertIsNotNone(
            xml_root.find("./hkclassMetadataReadiness/guiReadiness/targets/target[@key='visual_object_value_linking']")
        )
        standalone_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "object/test.hkx"))
        self.assertIn(standalone_root.get("cdmw_no_edit_binary_writer_status"), {"byte_identical", "not_started"})
        self.assertEqual(
            "native_no_edit_read_model_write_byte_identity",
            standalone_root.get("cdmw_biggest_remaining_gate"),
        )
        self.assertIn(
            standalone_root.get("cdmw_biggest_remaining_gate_status"),
            {"blocked", "file_level_passed_representative_corpus_pending"},
        )
        self.assertEqual("partial_synthetic_recovery", standalone_root.get("cdmw_class_internals_status"))
        self.assertEqual("open_hard_decoder_targets", standalone_root.get("cdmw_hard_decoder_targets_status"))
        self.assertEqual("partial_user_friendly_modding", standalone_root.get("cdmw_gui_readiness_status"))
        self.assertEqual("true", standalone_root.get("cdmw_python_builds_richer_graph_export"))
        self.assertIsNotNone(
            standalone_root.find("./hksection/hkobject[@class='hkFloat3']/hkparam[@name='values']/row[@index='0']")
        )

    def test_havok_xml_view_emits_mesh_shape_specialized_params(self) -> None:
        data = self._mesh_shape_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/mesh.hkx")
        mesh_object = next(obj for obj in document["havok_xml_view"]["hkobjects"] if obj["class"] == "hknpMeshShape")
        mesh_params = {field["hkparam_name"]: field for field in mesh_object["fields"]}

        self.assertIn("geometrySections", mesh_params)
        self.assertEqual("hkArray<hknpMeshShape::GeometrySection>", mesh_params["geometrySections"]["type"])
        self.assertIn("#record5", mesh_params["geometrySections"]["hkparam_text"])
        self.assertEqual(1, mesh_params["geometrySections"]["numelements"])
        self.assertEqual("array_data_reference", mesh_params["geometrySections"]["reference_category"])
        self.assertEqual(1, mesh_params["numGeometrySections"]["value"])
        self.assertEqual(24, mesh_params["numPrimitives"]["value"])

        standalone_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "object/mesh.hkx"))
        self.assertIsNotNone(
            standalone_root.find(
                "./hksection/hkobject[@class='hknpMeshShape']/hkparam[@name='geometrySections']"
            )
        )

    def test_havok_xml_view_recovers_root_object_when_not_first_record(self) -> None:
        type_names = b"hknpShape\0hkRootLevelContainer\0hkRootLevelContainer::NamedVariant\0char\0hknpPhysicsSystemData\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (64).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000004).to_bytes(4, "little") + (96).to_bytes(4, "little") + (16).to_bytes(4, "little"),
                (0x10000005).to_bytes(4, "little") + (128).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(192)
        struct.pack_into("<ff", data_payload, 0, 0.25, 1.5)
        struct.pack_into("<QII", data_payload, 32, 64, 1, 0x80000001)
        struct.pack_into("<QQQ", data_payload, 64, 96, 96, 128)
        data_payload[96:112] = b"PhysicsSystem\0\0\0"
        struct.pack_into("<II", data_payload, 128, 64, 1)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(5), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/out_of_order_root.hkx")
        havok_view = document["havok_xml_view"]

        self.assertEqual("#record1", havok_view["hkpackfile_view"]["toplevelobject"])
        self.assertEqual("preferred_root_class", havok_view["root_recovery"]["method"])
        variant_object = next(obj for obj in havok_view["hkobjects"] if obj["class"] == "hkRootLevelContainer::NamedVariant")
        variant_fields = {field["hkparam_name"]: field for field in variant_object["fields"]}
        self.assertEqual("#record4", variant_fields["variant"]["hkparam_text"])
        self.assertEqual("object_reference", variant_fields["variant"]["reference_category"])
        self.assertEqual("PhysicsSystem", variant_fields["name"]["hkparam_text"])
        self.assertEqual("PhysicsSystem", variant_fields["className"]["hkparam_text"])
        self.assertEqual("#record3", variant_fields["className"]["reference_target"])
        self.assertEqual("type_class_reference", variant_fields["className"]["reference_category"])
        self.assertEqual(1, havok_view["root_recovery"]["named_variant_count"])
        self.assertEqual("PhysicsSystem", havok_view["root_recovery"]["named_variants"][0]["name"])
        native_graph = document["native_backend"]["native_model_graph"]
        self.assertEqual("native_hkRootLevelContainer", native_graph["root"]["method"])
        self.assertEqual(1, native_graph["root"]["record_index"])
        self.assertEqual(1, native_graph["root"]["named_variant_count"])
        self.assertEqual("PhysicsSystem", native_graph["root"]["named_variants"][0]["name"])
        self.assertTrue(
            any(
                array["owner_record_index"] == 1
                and array["field_name"] == "namedVariants"
                and array["array_type"] == "hkArray<hkRootLevelContainer::NamedVariant>"
                for array in native_graph["owner_arrays"]
            )
        )

        standalone_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "physics/out_of_order_root.hkx"))
        self.assertEqual("#record1", standalone_root.get("toplevelobject"))
        self.assertEqual("1", standalone_root.get("cdmw_named_variant_count"))

    def test_hkx_tagfile_reference_fixups_are_exported_read_only(self) -> None:
        type_names = b"char\0hknpPhysicsSystemData\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (16).to_bytes(4, "little") + (12).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(96)
        data_payload[16:30] = b"RootVariant\0\0\0"
        struct.pack_into("<II", data_payload, 32, 0, 0)
        indx_payload = struct.pack("<IIII", 0, 16, 32, 2)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(2), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", indx_payload, flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/fixups.hkx")
        fixups = document["tagfile_reference_fixups"]
        indx_section = next(section for section in fixups["sections"] if section["name"] == "INDX")
        self.assertEqual(4, indx_section["word_count"])
        self.assertGreaterEqual(indx_section["record_offset_match_count"], 2)
        self.assertGreaterEqual(len(indx_section["resolved_references"]), 3)
        self.assertGreaterEqual(indx_section["reference_category_counts"]["object_reference"], 1)
        self.assertTrue(
            any(
                word.get("target_record_index") == 0 and word.get("reference_category") == "string_reference"
                for word in indx_section["words"]
            )
        )
        self.assertTrue(
            any(
                word.get("target_record_index") == 1 and word.get("reference_category") == "object_reference"
                for word in indx_section["words"]
            )
        )

        xml_text = build_hkx_editable_geometry_xml(data, "physics/fixups.hkx")
        xml_root = ET.fromstring(xml_text)
        self.assertIsNotNone(xml_root.find("./tagfileReferenceFixups/section[@name='INDX']/words/word[@target_record_index='1']"))
        self.assertIsNotNone(
            xml_root.find("./tagfileReferenceFixups/section[@name='INDX']/resolvedReferences/reference[@target_record_index='1']")
        )
        fixup_section = xml_root.find("./tagfileReferenceFixups/section[@name='INDX']")
        self.assertIsNotNone(fixup_section)
        assert fixup_section is not None
        fixup_section.set("record_offset_match_count", "999")
        result = apply_hkx_editable_geometry_xml(data, ET.tostring(xml_root, encoding="unicode"))
        self.assertEqual([], result.changed_fields)

    def test_hkx_tagfile_fixups_decode_nested_item_and_ptch_tables(self) -> None:
        type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(64)
        struct.pack_into("<Q", data_payload, 16, 2)
        item_payload = b"\0" * 12 + records
        item_section = (0x40000000 | (8 + len(item_payload))).to_bytes(4, "big") + b"ITEM" + item_payload
        ptch_payload = struct.pack("<IIIIII", 1, 1, 0, 2, 1, 16)
        indx_payload = item_section + _tag_item(b"PTCH", ptch_payload)
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", indx_payload, flags=0)
        data = (len(body) + 4).to_bytes(4, "big") + body

        summary = parse_hkx_tagfile_summary(data)
        self.assertIn("PTCH", [item.name for item in summary.tag_items])
        document = build_hkx_editable_geometry_document(data, "physics/nested_fixups.hkx")
        fixups = document["tagfile_reference_fixups"]
        indx_section = next(section for section in fixups["sections"] if section["name"] == "INDX")

        self.assertEqual(3, indx_section["match_kind_counts"]["item_type_flags"])
        self.assertEqual(3, indx_section["match_kind_counts"]["item_data_offset"])
        self.assertEqual(1, indx_section["match_kind_counts"]["ptch_length_word"])
        self.assertEqual(1, indx_section["match_kind_counts"]["ptch_marker"])
        self.assertEqual(4, indx_section["match_kind_counts"]["ptch_header_word"])
        self.assertEqual(1, indx_section["match_kind_counts"]["ptch_patch_site_count"])
        self.assertEqual(1, indx_section["match_kind_counts"]["ptch_object_patch_offset"])
        self.assertNotIn("unresolved_word", indx_section["match_kind_counts"])
        patch_word = next(word for word in indx_section["words"] if word["match_kind"] == "ptch_object_patch_offset")
        self.assertEqual(1, patch_word["owner_record_index"])
        self.assertEqual(0, patch_word["owner_local_offset"])
        self.assertEqual(2, patch_word["patch_value"])
        self.assertEqual(2, patch_word["target_record_index"])
        self.assertEqual("object_reference", patch_word["reference_category"])
        self.assertEqual("object", patch_word["target_status"])

        self.assertEqual(1, fixups["ptch_table_count"])
        self.assertEqual(1, fixups["ptch_patch_site_count"])
        self.assertEqual(1, fixups["ptch_resolved_patch_site_count"])
        self.assertEqual(0, fixups["ptch_null_patch_site_count"])
        self.assertEqual(0, fixups["ptch_unresolved_patch_site_count"])
        semantics_report = document["fixup_semantics_report"]
        self.assertEqual("cdmw_hkx_fixup_semantics_report_v1", semantics_report["format"])
        self.assertEqual(1, semantics_report["ptch_tuple_shape_counts"]["1,1,0,2"])
        self.assertEqual(1, semantics_report["ptch_payload_match_kind_counts"]["ptch_object_patch_offset"])
        self.assertEqual(1, semantics_report["ptch_target_status_counts"]["object"])
        ptch_table = indx_section["ptch_tables"][0]
        self.assertEqual([1, 1, 0, 2], ptch_table["header"])
        self.assertEqual(1, ptch_table["patch_site_count"])
        self.assertEqual(1, ptch_table["resolved_patch_site_count"])
        patch_site = ptch_table["patch_sites"][0]
        self.assertEqual(5, patch_site["ptch_word_index"])
        self.assertEqual(21, patch_site["section_word_index"])
        self.assertEqual(16, patch_site["patch_site_offset"])
        self.assertEqual(1, patch_site["owner_record_index"])
        self.assertEqual(0, patch_site["owner_local_offset"])
        self.assertEqual(2, patch_site["patch_value"])
        self.assertEqual("object", patch_site["target_status"])
        self.assertEqual(2, patch_site["target_record_index"])
        native_graph = document["native_backend"]["native_model_graph"]
        self.assertEqual("cd_hkx_native_model_graph_v1", native_graph["format"])
        self.assertEqual("native_model_graph_partial", native_graph["status"])
        self.assertEqual(3, native_graph["node_count"])
        self.assertEqual(1, native_graph["fixup_backed_reference_edge_count"])
        self.assertTrue(
            any(
                edge["source_record_index"] == 1
                and edge["target_record_index"] == 2
                and edge["owner_field_name"] == "ptr"
                and edge["resolution_source"] == "ptch"
                for edge in native_graph["edges"]
            )
        )

        refptr_object = next(obj for obj in document["havok_xml_view"]["hkobjects"] if obj["class"] == "hkRefPtr")
        refptr_params = {field["hkparam_name"]: field for field in refptr_object["fields"]}
        self.assertEqual("#record2", refptr_params["ptr"]["hkparam_text"])
        self.assertEqual("#record2", refptr_params["ptr"]["reference_target"])
        self.assertEqual("PTCH", refptr_params["ptr"]["fixup_source"])
        self.assertTrue(refptr_params["ptr"]["fixup_backed"])
        self.assertEqual("ptch", refptr_params["ptr"]["reference_resolution_source"])
        parity_report = document["hkx_xml_parity_report"]
        self.assertEqual(1, parity_report["ptch_patch_sites_found"])
        self.assertEqual(1, parity_report["ptch_patch_sites_object_resolved"])
        self.assertGreaterEqual(parity_report["ptch_fixup_backed_references"], 1)
        self.assertGreaterEqual(parity_report["object_references_resolved_by_ptch"], 1)

        xml_text = build_hkx_editable_geometry_xml(data, "physics/nested_fixups.hkx")
        xml_root = ET.fromstring(xml_text)
        self.assertIsNotNone(
            xml_root.find("./tagfileReferenceFixups/section[@name='INDX']/ptchTables/ptchTable/patchSites/patchSite[@target_status='object']")
        )
        self.assertIsNotNone(
            xml_root.find("./fixupSemanticsReport/ptchTupleShapes/ptchTupleShape[@shape='1,1,0,2'][@count='1']")
        )
        self.assertIsNotNone(
            xml_root.find("./fixupSemanticsReport/ptchPayloadMatchKinds/ptchPayloadMatchKind[@kind='ptch_object_patch_offset']")
        )
        self.assertIsNotNone(
            xml_root.find(
                "./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject[@class='hkRefPtr']"
                "/hkparam[@name='ptr'][@fixup_source='PTCH'][@reference_resolution_source='ptch']"
            )
        )
        self.assertIsNotNone(
            xml_root.find("./hkxXmlParityReport[@ptch_patch_sites_found='1'][@ptch_patch_sites_object_resolved='1']")
        )

    def test_havok_xml_view_uses_ptch_null_patch_sites_for_null_refs(self) -> None:
        type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (48).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(80)
        struct.pack_into("<Q", data_payload, 16, 2)
        struct.pack_into("<Q", data_payload, 48, 0)
        item_payload = b"\0" * 12 + records
        item_section = (0x40000000 | (8 + len(item_payload))).to_bytes(4, "big") + b"ITEM" + item_payload
        ptch_payload = struct.pack("<IIIIIII", 1, 1, 0, 2, 2, 16, 48)
        indx_payload = item_section + _tag_item(b"PTCH", ptch_payload)
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", indx_payload, flags=0)
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/nested_null_fixups.hkx")
        refptr_objects = [obj for obj in document["havok_xml_view"]["hkobjects"] if obj["class"] == "hkRefPtr"]
        self.assertEqual(2, len(refptr_objects))
        by_record = {obj["record_index"]: {field["hkparam_name"]: field for field in obj["fields"]} for obj in refptr_objects}
        self.assertEqual("#record2", by_record[1]["ptr"]["hkparam_text"])
        self.assertEqual("null", by_record[3]["ptr"]["hkparam_text"])
        self.assertEqual("null_reference", by_record[3]["ptr"]["reference_status"])
        self.assertEqual("PTCH", by_record[3]["ptr"]["fixup_source"])
        self.assertEqual("null", by_record[3]["ptr"]["ptch_target_status"])

        parity_report = document["hkx_xml_parity_report"]
        self.assertEqual(2, parity_report["ptch_patch_sites_found"])
        self.assertEqual(2, parity_report["ptch_patch_sites_resolved"])
        self.assertEqual(1, parity_report["ptch_patch_sites_null"])
        self.assertEqual(0, parity_report["ptch_patch_sites_unresolved"])
        semantics_report = document["fixup_semantics_report"]
        self.assertEqual(2, semantics_report["ptch_patch_site_count"])
        self.assertEqual(1, semantics_report["ptch_target_status_counts"]["object"])
        self.assertEqual(1, semantics_report["ptch_target_status_counts"]["null"])

        standalone_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "physics/nested_null_fixups.hkx"))
        self.assertIsNotNone(
            standalone_root.find(
                "./hksection/hkobject[@cdmw_record_index='3'][@class='hkRefPtr']"
                "/hkparam[@name='ptr'][@cdmw_fixup_source='PTCH'][@cdmw_ptch_target_status='null']"
            )
        )

    def test_havok_xml_view_resolves_skeleton_owner_arrays_and_null_refs(self) -> None:
        type_names = b"hkSkeleton\0hkBone\0hkInt16\0hkQsTransform\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (128).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000003).to_bytes(4, "little") + (160).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000004).to_bytes(4, "little") + (176).to_bytes(4, "little") + (2).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(288)
        struct.pack_into("<II", data_payload, 0x18, 128, 2)
        struct.pack_into("<II", data_payload, 0x28, 160, 2)
        struct.pack_into("<II", data_payload, 0x38, 176, 2)
        struct.pack_into("<ii", data_payload, 160, -1, 0)
        for transform_index in range(2):
            base = 176 + transform_index * 48
            struct.pack_into("<ffff", data_payload, base, float(transform_index), 0.0, 0.0, 1.0)
            struct.pack_into("<ffff", data_payload, base + 16, 0.0, 0.0, 0.0, 1.0)
            struct.pack_into("<ffff", data_payload, base + 32, 1.0, 1.0, 1.0, 1.0)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(4), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "character/skeleton.hkx")
        skeleton_object = next(obj for obj in document["havok_xml_view"]["hkobjects"] if obj["class"] == "hkSkeleton")
        skeleton_params = {field["hkparam_name"]: field for field in skeleton_object["fields"]}
        self.assertEqual("#record1", skeleton_params["bones"]["hkparam_text"])
        self.assertEqual(2, skeleton_params["bones"]["numelements"])
        self.assertEqual("owner_array_field", skeleton_params["bones"]["reference_kind"])
        self.assertEqual("#record2", skeleton_params["parentIndices"]["hkparam_text"])
        self.assertEqual("#record3", skeleton_params["referencePose"]["hkparam_text"])
        self.assertEqual("null", skeleton_params["floatSlots"]["hkparam_text"])
        self.assertEqual("null_reference", skeleton_params["floatSlots"]["reference_status"])

        skeleton_class = next(row for row in document["havok_xml_view"]["hkclasses"] if row["name"] == "hkSkeleton")
        bones_member = next(member for member in skeleton_class["members"] if member["name"] == "bones")
        self.assertEqual("TYPE_ARRAY", bones_member["member_type"])
        self.assertEqual("hkBone", bones_member["subtype"])

        standalone_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "character/skeleton.hkx"))
        self.assertIsNotNone(
            standalone_root.find("./hksection/hkobject[@class='hkSkeleton']/hkparam[@name='bones'][@numelements='2']")
        )
        self.assertIsNotNone(
            standalone_root.find("./hksection/hkobject[@class='hkQsTransform']/hkparam[@name='transforms']/row[@index='0']")
        )

    def test_hkx_physics_overlay_uses_model_preview_normalization(self) -> None:
        data = self._modern_hkx_bytes()
        descriptor_hint = build_hkx_descriptor_hint_from_xml_text(
            (
                '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                '<SkinnedMeshPhysicsAttachmentBodyCreationDesc _bodyName="PhysicsAttachment_Chest" '
                '_socketName="Spine2" _physicsMaterialName="cloth_body" _angularDamping="0.9" _linearDamping="0.8">'
                '<SkinnedMeshPhysicsAttachmentBoxShapeDesc />'
                '</SkinnedMeshPhysicsAttachmentBodyCreationDesc>'
                '<SkinnedMeshPhysicsAttachmentRagdollConstraintDesc _bodyName="PhysicsAttachment_Chest" '
                '_socketName="Spine2" _fixedSocketName="Spine1" _maxFrictionTorque="0.4" _coneAngle="45" />'
                '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
            ),
            "character/descriptors/physicsattachment/phw_01.xml",
        )
        self.assertIsNotNone(descriptor_hint)
        document = build_hkx_editable_geometry_document(data, "object/test.hkx", [descriptor_hint])
        self.assertEqual("cloth", document["physics_body_context"]["body_contexts"][0]["simulation_role"])
        xml_text = build_hkx_editable_geometry_xml(data, "object/test.hkx", [descriptor_hint])
        self.assertIn('simulation_role="cloth"', xml_text)

        overlay = build_hkx_physics_overlay_from_document(
            document,
            source_path="object/test.hkx",
            normalization_center=(1.0, 0.0, -1.0),
            normalization_scale=0.5,
            skeleton_bone_positions={
                "Spine2": {
                    "name": "Spine2",
                    "index": 7,
                    "parent_index": 6,
                    "parent_name": "Spine1",
                    "position": (10.0, 0.0, -1.0),
                    "source_path": "character/model/test.pab",
                },
                "Spine1": {
                    "name": "Spine1",
                    "index": 6,
                    "parent_index": -1,
                    "position": (8.0, 0.0, -1.0),
                    "source_path": "character/model/test.pab",
                },
            },
        )

        self.assertIsNotNone(overlay)
        assert overlay is not None
        self.assertEqual(1, len(overlay.shapes))
        shape = overlay.shapes[0]
        self.assertEqual("hknpConvexShape", shape.shape_type)
        self.assertEqual("object/test.hkx", shape.source_path)
        self.assertEqual((4.0, -0.5, -0.5), shape.vertices[0])
        self.assertEqual("skeleton_socket", shape.placement_source)
        self.assertEqual("Spine2", shape.placement_target)
        self.assertTrue(shape.faces)
        self.assertEqual("PhysicsAttachment_Chest", shape.body_name)
        self.assertEqual("Spine2", shape.socket_name)
        self.assertEqual("cloth", shape.simulation_role)
        self.assertIn("flexible attachment", shape.simulation_role_description)
        self.assertEqual(1, len(overlay.anchors))
        self.assertEqual(2, len(overlay.bones))
        spine2_bone = next(bone for bone in overlay.bones if bone.name == "Spine2")
        self.assertEqual(6, spine2_bone.parent_index)
        self.assertEqual("Spine1", spine2_bone.parent_name)
        self.assertEqual((3.5, 0.0, 0.0), spine2_bone.parent_position)
        self.assertEqual("PhysicsAttachment_Chest", overlay.anchors[0].body_name)
        self.assertEqual("Spine2", overlay.anchors[0].skeleton_bone_name)
        self.assertEqual(7, overlay.anchors[0].skeleton_bone_index)
        self.assertEqual("cloth", overlay.anchors[0].simulation_role)
        self.assertEqual((4.5, 0.0, 0.0), overlay.anchors[0].position)
        self.assertIn("_angularDamping=0.9", overlay.anchors[0].tuning_hints)
        self.assertEqual(1, len(overlay.constraints))
        self.assertEqual("PhysicsAttachment_Chest", overlay.constraints[0].body_name)
        self.assertEqual("cloth", overlay.constraints[0].simulation_role)
        self.assertEqual((4.5, 0.0, 0.0), overlay.constraints[0].start)
        self.assertEqual((3.5, 0.0, 0.0), overlay.constraints[0].end)
        self.assertIn("_maxFrictionTorque=0.4", overlay.constraints[0].limit_hints)
        self.assertIn(("cloth", 3), overlay.simulation_role_counts)
        self.assertIn("roles: cloth=3", overlay.summary)
        self.assertIn("Visual collision/physics structure overlay only.", overlay.limitations)

    def test_hkx_physics_overlay_places_named_ragdoll_shape_on_matching_skeleton_bone(self) -> None:
        overlay = build_hkx_physics_overlay_from_document(
            {
                "collision_shapes": [
                    {
                        "index": 12,
                        "shape_type": "hknpCapsuleShape",
                        "name_hint": {"name": "SkinnedMesh Ragdoll Bip01 Pelvis"},
                        "capsule_radius": 0.25,
                        "capsule_endpoints": [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    }
                ]
            },
            source_path="character/havokphysics/body.hkx",
            skeleton_bone_positions={
                "Bip01 Pelvis": {
                    "name": "Bip01 Pelvis",
                    "index": 4,
                    "parent_index": 3,
                    "position": (10.0, 0.0, 0.0),
                    "source_path": "character/model/test.pab",
                }
            },
        )

        self.assertIsNotNone(overlay)
        assert overlay is not None
        shape = overlay.shapes[0]
        self.assertEqual(12, shape.source_shape_index)
        self.assertEqual("skeleton_label", shape.placement_source)
        self.assertEqual("Bip01 Pelvis", shape.placement_target)
        self.assertEqual((10.0, -0.5, 0.0), shape.capsule_start)
        self.assertEqual((10.0, 0.5, 0.0), shape.capsule_end)

    def test_hkx_converter_exports_material_simulation_context_for_cloth_and_hair(self) -> None:
        data = self._modern_hkx_bytes()
        descriptor_hint = build_hkx_descriptor_hint_from_xml_text(
            (
                '<SkinnedMeshProperty _pbdSimulationMaterialName="Cloak">'
                '<SkinnedMeshMaterialWrapper _subMeshName="cloak_panel" _jiggleWindWeight="0.35">'
                '<Material _materialName="SkinnedMeshCloth_Ver2" />'
                '<MaterialParameterClothCategory _name="_clothCategory" _value="Velvet" />'
                '</SkinnedMeshMaterialWrapper>'
                '<SkinnedMeshMaterialWrapper _subMeshName="hair_tail">'
                '<Material _materialName="SkinnedMeshAnimalHair" />'
                '<MaterialParameterFloat _name="_hairAnisotropyDetailOpacity" _value="0.56" />'
                '</SkinnedMeshMaterialWrapper>'
                '</SkinnedMeshProperty>'
            ),
            "character/modelproperty/cloth_and_hair.pac_xml",
        )

        self.assertIsNotNone(descriptor_hint)
        assert descriptor_hint is not None
        self.assertGreaterEqual(descriptor_hint["material_simulation_hint_count"], 2)
        document = build_hkx_editable_geometry_document(data, "object/test.hkx", [descriptor_hint])
        material_context = document["physics_material_context"]
        self.assertEqual("descriptor_material_context", material_context["status"])
        self.assertGreaterEqual(material_context["role_counts"]["cloth"], 1)
        self.assertGreaterEqual(material_context["role_counts"]["hair"], 1)

        xml_text = build_hkx_editable_geometry_xml(data, "object/test.hkx", [descriptor_hint])
        self.assertIn("<physicsMaterialContext", xml_text)
        self.assertIn('simulation_role="hair"', xml_text)

    def test_editable_hkx_geometry_document_reapplies_advanced_same_length_payload_edits(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        edited_document = copy.deepcopy(document)
        payload = bytes.fromhex(edited_document["advanced_record_payloads"][0]["payload_hex"])
        edited_payload = bytes((0x7F,)) + payload[1:]
        edited_document["advanced_record_payloads"][0]["payload_hex"] = edited_payload.hex(" ")

        result = apply_hkx_editable_geometry_document(data, edited_document)
        reparsed_document = build_hkx_editable_geometry_document(result.data, "object/test.hkx")

        self.assertIn("record[0].payload", result.changed_fields)
        self.assertTrue(reparsed_document["advanced_record_payloads"][0]["payload_hex"].startswith("7f "))

    def test_editable_hkx_geometry_document_reapplies_typed_advanced_record_edits(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        edited_document = copy.deepcopy(document)
        face_payload = next(
            record
            for record in edited_document["advanced_record_payloads"]
            if record["type_name"] == "hknpConvexHull::Face"
        )
        face_payload["editable_values"]["records"][0]["meta"] = 126

        result = apply_hkx_editable_geometry_document(data, edited_document)
        reparsed_document = build_hkx_editable_geometry_document(result.data, "object/test.hkx")
        reparsed_face_payload = next(
            record
            for record in reparsed_document["advanced_record_payloads"]
            if record["type_name"] == "hknpConvexHull::Face"
        )

        self.assertIn("record[5].editable_values", result.changed_fields)
        self.assertEqual(126, reparsed_face_payload["editable_values"]["records"][0]["meta"])

    def test_modern_hkx_physics_system_exports_motor_float_slots(self) -> None:
        type_names = b"hknpPositionConstraintMotor\0\xff"
        records = (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
        data_payload = bytearray(56)
        for offset, value in ((0x20, -1000000.0), (0x24, 1000000.0), (0x28, 0.8), (0x2C, 1.0), (0x30, 2.0), (0x34, 1.0)):
            struct.pack_into("<f", data_payload, offset, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(1), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        descriptor_hint = build_hkx_descriptor_hint_from_xml_text(
            (
                '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                '<SkinnedMeshPhysicsAttachmentRagdollConstraintDesc _coneAngle="45" '
                '_twistMin="-5" _twistMax="8" _maxFrictionTorque="0.400000"/>'
                '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
            ),
            "character/descriptors/physicsattachment/phw_01.xml",
        )
        self.assertIsNotNone(descriptor_hint)
        document = build_hkx_editable_geometry_document(data, "physics/motor.hkx", [descriptor_hint])
        self.assertIsNotNone(document["physics_system"])
        self.assertIsNotNone(document["physics_tuning"])
        motor_payload = document["advanced_record_payloads"][0]
        self.assertEqual("fixed_float_slots", motor_payload["editable_values"]["kind"])
        self.assertIn("minimum motor force", motor_payload["editable_values"]["items"][0]["float_slots"][0]["description"])
        tuning_group = document["physics_tuning"]["groups"][0]
        self.assertEqual("motor_force_response", tuning_group["category"])
        self.assertEqual("experimental", tuning_group["confidence"])
        self.assertEqual("strong inference", tuning_group["slots"][0]["confidence"])
        self.assertEqual("stiffness_or_strength", tuning_group["slots"][2]["name"])
        self.assertEqual("motor stiffness", tuning_group["slots"][2]["plain_language_effect"])
        self.assertIn("tightens", tuning_group["slots"][2]["if_increased"])
        self.assertTrue(tuning_group["slots"][2]["safe_edit_hint"])
        self.assertIn("finite float", tuning_group["slots"][2]["value_constraints"])
        self.assertTrue(tuning_group["slots"][2]["suggested_edit_step"])
        self.assertIn("descriptor_context_hints", tuning_group)
        self.assertTrue(any(hint["name"] == "_maxFrictionTorque" for hint in tuning_group["descriptor_context_hints"]))
        catalog = document["editable_field_catalog"]
        self.assertIsNotNone(catalog)
        self.assertEqual("loose replacement package", document["reimport_policy"]["mod_creation"]["output_mode"])
        self.assertIn("never overwrite", document["reimport_policy"]["mod_creation"]["archive_policy"])
        self.assertIn("Structured Editor", catalog["workflow"]["edit_surface"])
        self.assertIn("stiffness/strength", catalog["effect_counts"])
        patch_map = document["byte_patch_map"]
        self.assertIsNotNone(patch_map)
        self.assertTrue(
            any(
                entry["path"] == "physics_tuning.groups[0].slots[2]"
                and entry["record_index"] == 0
                and entry["relative_offset"] == 0x28
                and entry["value_type"] == "float32"
                for entry in patch_map["entries"]
            )
        )
        self.assertTrue(
            any(
                field["category"] == "motor_force_response"
                and field["editor_tab"] == "Structured Editor"
                and field["record_index"] == 0
                and field["name"] == "stiffness_or_strength"
                and field["effect"] == "stiffness/strength"
                and field["plain_language_effect"] == "motor stiffness"
                and field["edit_risk"] == "medium"
                for field in catalog["fields"]
            )
        )

        edited_document = copy.deepcopy(document)
        edited_document["physics_tuning"]["groups"][0]["slots"][2]["value"] = 0.6
        def native_patch(data_bytes: bytes, **kwargs) -> bytes:
            patched = bytearray(data_bytes)
            old = struct.pack("<f", 0.8)
            index = patched.find(old)
            self.assertGreaterEqual(index, 0)
            patched[index : index + 4] = struct.pack("<f", float(kwargs["value"]))
            return bytes(patched)

        with mock.patch("cdmw.core.hkx_native.patch_hkx_fixed_float_with_rust", side_effect=native_patch) as native_patch_mock:
            result = apply_hkx_editable_geometry_document(data, edited_document)
        native_patch_mock.assert_called()
        reparsed = build_hkx_editable_geometry_document(result.data, "physics/motor.hkx")

        self.assertIn("physics_tuning.record[0].item[0].offset[0x28]", result.changed_fields)
        self.assertEqual(0.6000000238418579, reparsed["advanced_record_payloads"][0]["editable_values"]["items"][0]["float_slots"][2]["value"])

        xml_text = build_hkx_editable_geometry_xml(data, "physics/motor.hkx", [descriptor_hint])
        root = ET.fromstring(xml_text)
        context_hint = root.find("./physicsTuning/groups/group/descriptorContextHints/hint[@name='_maxFrictionTorque']")
        self.assertIsNotNone(context_hint)
        assert context_hint is not None
        self.assertEqual("false", root.find("./physicsTuning/groups/group/descriptorContextHints").get("imported"))
        xml_slot = root.find("./physicsTuning/groups/group/slots/slot[@name='stiffness_or_strength']")
        self.assertIsNotNone(xml_slot)
        assert xml_slot is not None
        self.assertEqual("experimental", xml_slot.get("confidence"))
        self.assertEqual("motor stiffness", xml_slot.get("plain_language_effect"))
        self.assertTrue(xml_slot.get("if_increased"))
        self.assertTrue(xml_slot.get("safe_edit_hint"))
        self.assertIn("finite float", xml_slot.get("value_constraints") or "")
        self.assertTrue(xml_slot.get("suggested_edit_step"))
        xml_catalog_slot = root.find("./editableFieldCatalog/fields/field[@name='stiffness_or_strength']")
        self.assertIsNotNone(xml_catalog_slot)
        assert xml_catalog_slot is not None
        self.assertEqual("Structured Editor", xml_catalog_slot.get("editor_tab"))
        self.assertTrue(xml_catalog_slot.get("subject"))
        self.assertEqual("stiffness/strength", xml_catalog_slot.get("effect"))
        self.assertTrue(xml_catalog_slot.get("edit_guidance"))
        self.assertIn("finite float", xml_catalog_slot.get("value_constraints") or "")
        self.assertTrue(xml_catalog_slot.get("suggested_edit_step"))
        self.assertEqual("motor stiffness", xml_catalog_slot.get("plain_language_effect"))
        self.assertEqual("medium", xml_catalog_slot.get("edit_risk"))
        self.assertEqual("true", xml_catalog_slot.get("importable"))
        self.assertEqual("false", root.find("./editableFieldCatalog").get("imported"))
        xml_patch_slot = root.find("./bytePatchMap/entries/entry[@path='physics_tuning.groups[0].slots[2]']")
        self.assertIsNotNone(xml_patch_slot)
        assert xml_patch_slot is not None
        self.assertEqual("0x28", xml_patch_slot.get("hex_relative_offset"))
        self.assertEqual("float32", xml_patch_slot.get("value_type"))
        xml_slot.set("value", "0.7")
        xml_result = apply_hkx_editable_geometry_xml(data, ET.tostring(root, encoding="unicode"))
        xml_reparsed = build_hkx_editable_geometry_document(xml_result.data, "physics/motor.hkx")

        self.assertIn("physics_tuning.record[0].item[0].offset[0x28]", xml_result.changed_fields)
        self.assertEqual(0.699999988079071, xml_reparsed["physics_tuning"]["groups"][0]["slots"][2]["value"])

    def test_hkx_converter_object_layout_decodes_array_and_ref_headers(self) -> None:
        data = self._array_ref_hkx_bytes()

        document = build_hkx_editable_geometry_document(data, "physics/array_refs.hkx")

        array_object = next(record for record in document["objects"] if record["type_name"] == "hkArray")
        array_fields = {field["name"]: field for field in array_object["layout"]["fields"]}
        self.assertEqual(3, array_fields["size"]["value"])
        self.assertEqual(0x80000003, array_fields["capacity_and_flags"]["value"])
        self.assertTrue(any(reference["target_record_index"] == 2 for reference in array_object["references"]))
        ref_object = next(record for record in document["objects"] if record["type_name"] == "hkRefPtr")
        ref_fields = {field["name"]: field for field in ref_object["layout"]["fields"]}
        self.assertEqual(32, ref_fields["referenced_object"]["value"]["low_u32"])
        self.assertTrue(any(reference["target_type_name"] == "hknpShape" for reference in ref_object["references"]))
        shape_object = next(record for record in document["objects"] if record["type_name"] == "hknpShape")
        self.assertTrue(any(field["name"] == "finite_float_0x0" for field in shape_object["layout"]["fields"]))

    def test_hkx_converter_decodes_shape_name_property_strings(self) -> None:
        type_names = b"char\0HavokShapeNameProperty\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (17).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(72)
        data_payload[:17] = b"Ragdoll_TestName\0"
        struct.pack_into("<I", data_payload, 32 + 0x20, 1)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(2), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/names.hkx")

        self.assertEqual("Ragdoll_TestName", document["physics_names"]["shape_name_properties"][0]["name"])
        self.assertEqual("Ragdoll_TestName", document["physics_names"]["char_strings"][0]["text"])
        self.assertEqual("ragdoll", document["physics_names"]["char_strings"][0]["simulation_role"])
        char_object = next(record for record in document["objects"] if record["type_name"] == "char")
        self.assertEqual("Ragdoll_TestName", char_object["decoded_fields"]["decoded_string"]["value"])
        name_object = next(record for record in document["objects"] if record["type_name"] == "HavokShapeNameProperty")
        self.assertEqual("Ragdoll_TestName", name_object["decoded_fields"]["decoded_shape_name"]["name"])

        xml_text = build_hkx_editable_geometry_xml(data, "physics/names.hkx")
        root = ET.fromstring(xml_text)
        char_string = root.find("./physicsNames/charStrings/string")
        self.assertIsNotNone(char_string)
        assert char_string is not None
        self.assertEqual("Ragdoll_TestName", char_string.get("text"))
        self.assertEqual("ragdoll", char_string.get("simulation_role"))
        shape_name = root.find("./physicsNames/shapeNameProperties/shapeName")
        self.assertIsNotNone(shape_name)
        assert shape_name is not None
        self.assertEqual("Ragdoll_TestName", shape_name.get("name"))
        self.assertEqual("false", root.find("./physicsNames").get("imported"))

    def test_hkx_converter_exports_constraint_motor_summary(self) -> None:
        type_names = b"char\0hknpRagdollConstraintData\0hknpPositionConstraintMotor\0\xff"
        constraint_name = b"hkRagdollConstraint000\0"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + len(constraint_name).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (160).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(216)
        data_payload[: len(constraint_name)] = constraint_name
        struct.pack_into("<I", data_payload, 32 + 0x04, 160)
        struct.pack_into("<f", data_payload, 32 + 0x18, 100.0)
        struct.pack_into("<f", data_payload, 32 + 0x40, 1.0)
        for offset, value in ((0x20, -1000000.0), (0x24, 1000000.0), (0x28, 0.8), (0x2C, 1.0)):
            struct.pack_into("<f", data_payload, 160 + offset, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body
        descriptor_hint = build_hkx_descriptor_hint_from_xml_text(
            (
                '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                '<SkinnedMeshPhysicsAttachmentRagdollConstraintDesc _coneAngle="45" '
                '_twistMin="-5" _twistMax="8" _maxFrictionTorque="0.400000"/>'
                '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
            ),
            "character/descriptors/physicsattachment/phw_01.xml",
        )
        self.assertIsNotNone(descriptor_hint)

        document = build_hkx_editable_geometry_document(data, "physics/constraint.hkx", [descriptor_hint])
        summary = document["physics_constraint_summary"]

        self.assertEqual(1, summary["constraint_count"])
        constraint = summary["constraints"][0]
        self.assertEqual("hkRagdollConstraint000", constraint["name"])
        self.assertEqual(1, constraint["constraint_record_index"])
        self.assertEqual(2, constraint["motor_record_index"])
        self.assertTrue(any(slot["name"] == "constraint_strength_or_tau" for slot in constraint["constraint_slots"]))
        self.assertTrue(any(slot["name"] == "joint_frame_a_row0_x" for slot in constraint["constraint_slots"]))
        self.assertTrue(any(slot["name"] == "stiffness_or_strength" for slot in constraint["motor_slots"]))
        tuning_group = next(
            group
            for group in document["physics_tuning"]["groups"]
            if group["type_name"] == "hknpRagdollConstraintData"
        )
        self.assertTrue(any(vector["name"] == "joint_frame_a_row0" for vector in tuning_group["slot_vector_groups"]))
        constraint_editor_group = next(group for group in document["editor_model"]["groups"] if group["key"] == "constraints")
        self.assertTrue(any(row["field"] == "joint_frame_a_row0" and row["importable"] is False for row in constraint_editor_group["rows"]))
        self.assertEqual("SkinnedMeshPhysicsAttachmentRagdollConstraintDesc", constraint["descriptor_context"]["tag"])
        constraint_object = next(record for record in document["objects"] if record["type_name"] == "hknpRagdollConstraintData")
        motor_object = next(record for record in document["objects"] if record["type_name"] == "hknpPositionConstraintMotor")
        self.assertTrue(any(field["name"] == "constraint_strength_or_tau" for field in constraint_object["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "joint_frame_a_row0_x" for field in constraint_object["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "stiffness_or_strength" for field in motor_object["layout"]["fields"]))
        self.assertTrue(
            any(
                edge["source"] == "record:1"
                and edge["target"] == "record:2"
                and edge["relation"] == "possible_constraint_motor"
                for edge in document["relationship_graph"]["edges"]
            )
        )

        xml_text = build_hkx_editable_geometry_xml(data, "physics/constraint.hkx", [descriptor_hint])
        root = ET.fromstring(xml_text)
        xml_constraint = root.find("./physicsConstraintSummary/constraints/constraint")
        self.assertIsNotNone(xml_constraint)
        assert xml_constraint is not None
        self.assertEqual("hkRagdollConstraint000", xml_constraint.get("name"))
        self.assertIsNotNone(xml_constraint.find("./motor_slots/motorSlot[@name='stiffness_or_strength']"))
        self.assertIsNotNone(root.find("./physicsTuning/groups/group/vectorGroups/vector[@name='joint_frame_a_row0']"))
        self.assertEqual("false", root.find("./physicsConstraintSummary").get("imported"))

    def test_hkx_converter_matches_constraint_names_by_constraint_kind(self) -> None:
        type_names = b"char\0hknpRagdollConstraintData\0hknpLimitedHingeConstraintData\0\xff"
        ragdoll_name = b"hkRagdollConstraint000\0"
        hinge_name = b"hkHingeConstraint001\0"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + len(ragdoll_name).to_bytes(4, "little"),
                (0x10000001).to_bytes(4, "little") + (32).to_bytes(4, "little") + len(hinge_name).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (64).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (128).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(192)
        data_payload[: len(ragdoll_name)] = ragdoll_name
        data_payload[32 : 32 + len(hinge_name)] = hinge_name
        struct.pack_into("<f", data_payload, 64 + 0x18, 100.0)
        struct.pack_into("<f", data_payload, 128 + 0x18, 100.0)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/constraint_names.hkx")
        constraints = document["physics_constraint_summary"]["constraints"]

        self.assertEqual("hkRagdollConstraint000", constraints[0]["name"])
        self.assertEqual("hknpRagdollConstraintData", constraints[0]["type_name"])
        self.assertEqual("hkHingeConstraint001", constraints[1]["name"])
        self.assertEqual("hknpLimitedHingeConstraintData", constraints[1]["type_name"])

    def test_hkx_converter_reports_schema_target_coverage_and_unknown_priorities(self) -> None:
        type_names = (
            b"hkRootLevelContainer\0"
            b"hkRootLevelContainer::NamedVariant\0"
            b"hknpPhysicsSceneData\0"
            b"hknpConstraintCinfo\0"
            b"hknpUnknownLargeThing\0\xff"
        )
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (96).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000004).to_bytes(4, "little") + (128).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000005).to_bytes(4, "little") + (160).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(224)
        struct.pack_into("<QII", data_payload, 0, 32, 1, 0x80000001)
        struct.pack_into("<QQQ", data_payload, 32, 72, 88, 96)
        struct.pack_into("<II", data_payload, 96, 128, 1)
        struct.pack_into("<II", data_payload, 128, 32, 96)
        struct.pack_into("<II", data_payload, 160, 0xABCD, 0x1234)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(5), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/root_scene.hkx")
        report = document["converter_report"]
        schema_targets = {row["type_name"]: row for row in report["schema_target_coverage"]}

        self.assertEqual("decoded", schema_targets["hkRootLevelContainer"]["coverage_status"])
        self.assertEqual("decoded", schema_targets["hkRootLevelContainer::NamedVariant"]["coverage_status"])
        self.assertEqual("decoded", schema_targets["hknpPhysicsSceneData"]["coverage_status"])
        self.assertEqual("decoded", schema_targets["hknpConstraintCinfo"]["coverage_status"])
        self.assertEqual("not_present", schema_targets["hknpRagdollData"]["coverage_status"])
        root_object = next(record for record in document["objects"] if record["type_name"] == "hkRootLevelContainer")
        self.assertTrue(any(field["name"] == "named_variants_size" for field in root_object["layout"]["fields"]))
        variant_object = next(record for record in document["objects"] if record["type_name"] == "hkRootLevelContainer::NamedVariant")
        self.assertTrue(any(field["name"] == "object_reference" for field in variant_object["layout"]["fields"]))
        self.assertEqual("hknpUnknownLargeThing", report["failed_or_unknown_schema_areas"][0]["type_name"])
        self.assertEqual(1, report["failed_or_unknown_schema_areas"][0]["priority_rank"])
        self.assertTrue(report["failed_or_unknown_schema_areas"][0]["suggested_next_decoder_step"])
        self.assertIn("missing_requirements", report["failed_or_unknown_schema_areas"][0])

        xml_text = build_hkx_editable_geometry_xml(data, "physics/root_scene.hkx")
        xml_root = ET.fromstring(xml_text)
        self.assertIsNotNone(xml_root.find("./converterReport/schemaTargetCoverage/target[@type_name='hknpPhysicsSceneData']"))
        unknown_area = xml_root.find("./converterReport/failedOrUnknownSchemaAreas/area[@type_name='hknpUnknownLargeThing']")
        self.assertIsNotNone(unknown_area)
        assert unknown_area is not None
        self.assertTrue(unknown_area.get("suggested_next_decoder_step"))

    def test_hkx_converter_decodes_compound_tree_instance_and_property_blockers(self) -> None:
        type_names = (
            b"hknpCompoundShape\0"
            b"hknpShapeInstance\0"
            b"hkcdSimdTreeNamespace::Node\0"
            b"hknpShapeProperties::Entry\0"
            b"hkFreeListArrayElement<tVALUE_TYPE=7>\0"
            b"hknpShapeMassProperties\0\xff"
        )
        specs = (
            (0x10000001, 0, 1),
            (0x20000002, 128, 2),
            (0x20000003, 192, 2),
            (0x20000004, 256, 2),
            (0x20000005, 288, 2),
            (0x10000006, 352, 1),
        )
        records = b"".join(
            raw.to_bytes(4, "little") + offset.to_bytes(4, "little") + count.to_bytes(4, "little")
            for raw, offset, count in specs
        )
        data_payload = bytearray(416)
        for offset, value in ((0x20, 128), (0x24, 2), (0x30, 192), (0x34, 2), (0x40, 288), (0x44, 2)):
            struct.pack_into("<I", data_payload, offset, value)
        for base in (128, 160, 192, 208, 256, 272, 288, 320):
            for index in range(4):
                struct.pack_into("<I", data_payload, base + index * 4, base + index)
        for index, value in enumerate((1.0, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0, 0.0, 0.0, 1.0, 4.0, 5.0, 6.0, 7.0, 8.0)):
            struct.pack_into("<f", data_payload, 352 + index * 4, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(6), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/compound_blockers.hkx")
        objects = {record["type_name"]: record for record in document["objects"]}

        self.assertTrue(any(field["name"] == "shape_instances_or_storage_pair" for field in objects["hknpCompoundShape"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "shape_instance[0]" for field in objects["hknpShapeInstance"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "simd_tree_node[0]" for field in objects["hkcdSimdTreeNamespace::Node"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "property_entry[0]" for field in objects["hknpShapeProperties::Entry"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "free_list_element[0]" for field in objects["hkFreeListArrayElement<tVALUE_TYPE=7>"]["layout"]["fields"]))
        target_coverage = {row["type_name"]: row for row in document["converter_report"]["schema_target_coverage"]}
        self.assertEqual("decoded", target_coverage["hknpCompoundShape"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hknpShapeInstance"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hkcdSimdTreeNamespace::Node"]["coverage_status"])
        self.assertEqual("value_editable", target_coverage["hknpShapeMassProperties"]["coverage_status"])

    def test_hkx_converter_decodes_box_shape_layout_as_compatibility_target(self) -> None:
        type_names = b"hknpBoxShape\0\xff"
        records = (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
        data_payload = bytearray(192)
        for offset, value in (
            (0x30, 14),
            (0x38, 136),
            (0x3C, 8),
            (0x40, 224),
            (0x44, 6),
            (0x48, 312),
            (0x4C, 6),
            (0x50, 336),
            (0x54, 24),
            (0x58, 360),
            (0x5C, 24),
            (0x60, 448),
            (0x64, 8),
        ):
            struct.pack_into("<I", data_payload, offset, value)
        struct.pack_into("<f", data_payload, 0x68, 0.015)
        struct.pack_into("<f", data_payload, 0x6C, 0.008)
        for index, value in enumerate(
            (
                1.0,
                0.0,
                0.0,
                0.075,
                0.0,
                1.0,
                0.0,
                0.048,
                0.0,
                0.0,
                1.0,
                0.009,
                -4.5,
                1.0,
                6.25,
                0.5,
            )
        ):
            struct.pack_into("<f", data_payload, 0x80 + index * 4, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(1), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "object/box.hkx")
        box_record = next(record for record in document["objects"] if record["type_name"] == "hknpBoxShape")
        field_names = {field["name"] for field in box_record["layout"]["fields"]}

        self.assertIn("box_vertices_offset_count", field_names)
        self.assertIn("convex_radius_or_collision_margin", field_names)
        self.assertIn("box_local_frame_or_extents", field_names)
        assert document["physics_system"] is not None
        self.assertEqual(1, document["physics_system"]["type_counts"]["hknpBoxShape"])
        self.assertTrue(
            any(
                "hknpBoxShape" in control["types"] and control["name"] == "static and attachment collision shapes"
                for control in document["physics_system"]["likely_controls"]
            )
        )
        self.assertEqual(1, len(document["collision_shapes"]))
        collision_shape = document["collision_shapes"][0]
        self.assertEqual("hknpBoxShape", collision_shape["shape_type"])
        for expected, actual in zip([-4.575, 0.952, 6.241], collision_shape["bounds_min"]):
            self.assertAlmostEqual(expected, actual, places=5)
        for expected, actual in zip([-4.425, 1.048, 6.259], collision_shape["bounds_max"]):
            self.assertAlmostEqual(expected, actual, places=5)
        for expected, actual in zip([0.15, 0.096, 0.018], collision_shape["extent"]):
            self.assertAlmostEqual(expected, actual, places=5)
        for expected, actual in zip([0.075, 0.048, 0.009], collision_shape["box_summary"]["half_extents"]):
            self.assertAlmostEqual(expected, actual, places=5)
        collision_group = next(group for group in document["editor_model"]["groups"] if group["key"] == "collision_shapes")
        collision_rows = [
            row
            for row in collision_group["rows"]
            if row["field"] == "summary"
        ]
        self.assertEqual(1, len(collision_rows))
        self.assertFalse(collision_rows[0]["importable"])
        self.assertEqual("shape/0", collision_rows[0]["viewer_selection_id"])
        self.assertIn("hknpBoxShape", collision_rows[0]["value"])
        self.assertIn("Read-only summary row", collision_rows[0]["safe_edit_hint"])
        target_coverage = {row["type_name"]: row for row in document["converter_report"]["schema_target_coverage"]}
        self.assertEqual("decoded", target_coverage["hknpBoxShape"]["coverage_status"])
        self.assertFalse(
            any(row["type_name"] == "hknpBoxShape" for row in document["converter_report"]["failed_or_unknown_schema_areas"])
        )
        xml_text = build_hkx_editable_geometry_xml(data, "object/box.hkx")
        self.assertIn("<box_summary", xml_text)
        self.assertIn("<local_frame_rows", xml_text)

    def test_hkx_converter_decodes_skeleton_and_material_support_records(self) -> None:
        type_names = (
            b"char\0"
            b"HavokShapeNameProperty\0"
            b"hkQsTransform\0"
            b"hkBone\0"
            b"hkInt16\0"
            b"hkSkeleton\0"
            b"hknpMaterial\0\xff"
        )
        specs = (
            (0x10000001, 0, 11),
            (0x10000002, 32, 1),
            (0x20000003, 80, 2),
            (0x20000004, 176, 2),
            (0x20000005, 208, 2),
            (0x10000006, 224, 1),
            (0x20000007, 320, 2),
        )
        records = b"".join(
            raw.to_bytes(4, "little") + offset.to_bytes(4, "little") + count.to_bytes(4, "little")
            for raw, offset, count in specs
        )
        data_payload = bytearray(480)
        data_payload[:11] = b"Bone_Test\0"
        struct.pack_into("<I", data_payload, 32 + 0x20, 1)
        for row_index in range(2):
            base = 80 + row_index * 48
            struct.pack_into("<ffff", data_payload, base, float(row_index), 1.0, 2.0, 1.0)
            struct.pack_into("<ffff", data_payload, base + 16, 0.0, 0.0, 0.0, 1.0)
            struct.pack_into("<ffff", data_payload, base + 32, 1.0, 1.0, 1.0, 1.0)
        struct.pack_into("<IIII", data_payload, 176, 1, 0, -1 & 0xFFFFFFFF, 0)
        struct.pack_into("<IIII", data_payload, 192, 1, 0, 0, 0)
        struct.pack_into("<hh", data_payload, 208, -1, 0)
        struct.pack_into("<II", data_payload, 224 + 0x18, 176, 2)
        struct.pack_into("<II", data_payload, 224 + 0x28, 208, 2)
        struct.pack_into("<II", data_payload, 224 + 0x38, 80, 2)
        for material_index in range(2):
            base = 320 + material_index * 80
            struct.pack_into("<I", data_payload, base, 27 + material_index)
            struct.pack_into("<fff", data_payload, base + 24, 1.0, 0.25, 0.1)
            struct.pack_into("<f", data_payload, base + 48, 5.0)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(7), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/skeleton_support.hkx")
        objects = {record["type_name"]: record for record in document["objects"]}

        self.assertTrue(any(field["name"] == "shape_name_reference" for field in objects["HavokShapeNameProperty"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "qs_transform[0]" for field in objects["hkQsTransform"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "bone[0]" for field in objects["hkBone"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "int16_values" for field in objects["hkInt16"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "bones_reference_or_count_pair" for field in objects["hkSkeleton"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "material[0]" for field in objects["hknpMaterial"]["layout"]["fields"]))
        target_coverage = {row["type_name"]: row for row in document["converter_report"]["schema_target_coverage"]}
        for type_name in ("HavokShapeNameProperty", "hkQsTransform", "hkBone", "hkInt16", "hkSkeleton", "hknpMaterial"):
            self.assertEqual("decoded", target_coverage[type_name]["coverage_status"])
        self.assertFalse(
            any(row["type_name"] in target_coverage for row in document["converter_report"]["failed_or_unknown_schema_areas"])
        )

    def test_hkx_converter_decodes_skeleton_mapper_support_records(self) -> None:
        type_names = (
            b"char\0"
            b"hkaSkeletonMapper\0"
            b"hkaSkeletonMapperData::SimpleMapping\0"
            b"hkaAnimationContainer\0"
            b"int\0\xff"
        )
        specs = (
            (0x10000001, 0, 15),
            (0x10000002, 32, 1),
            (0x20000003, 240, 2),
            (0x10000004, 368, 1),
            (0x20000005, 480, 4),
        )
        records = b"".join(
            raw.to_bytes(4, "little") + offset.to_bytes(4, "little") + count.to_bytes(4, "little")
            for raw, offset, count in specs
        )
        data_payload = bytearray(512)
        data_payload[:15] = b"SkeletonMapper\0"
        struct.pack_into("<II", data_payload, 32 + 0x20, 17, 0)
        struct.pack_into("<II", data_payload, 32 + 0x28, 19, 0)
        struct.pack_into("<II", data_payload, 32 + 0x60, 2, 0)
        for row_index in range(2):
            base = 240 + row_index * 64
            struct.pack_into("<III", data_payload, base, row_index, row_index + 10, row_index + 20)
            struct.pack_into("<ffff", data_payload, base + 0x20, 0.5 + row_index, 1.0, 1.0, 1.0)
            struct.pack_into("<I", data_payload, base + 0x40 - 4, row_index + 30)
        struct.pack_into("<II", data_payload, 368 + 0x18, 4, 0)
        struct.pack_into("<iiii", data_payload, 480, 0, 1, 2, 3)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(5), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "physics/mapper_support.hkx")
        objects = {record["type_name"]: record for record in document["objects"]}

        self.assertTrue(any(field["name"] == "ascii_or_utf8_text" for field in objects["char"]["layout"]["fields"]))
        self.assertTrue(any(field["name"] == "source_skeleton_or_root_reference" for field in objects["hkaSkeletonMapper"]["layout"]["fields"]))
        self.assertTrue(
            any(field["name"] == "simple_mapping[0]" for field in objects["hkaSkeletonMapperData::SimpleMapping"]["layout"]["fields"])
        )
        self.assertTrue(
            any(field["name"] == "animation_container_pair_0x18" for field in objects["hkaAnimationContainer"]["layout"]["fields"])
        )
        self.assertTrue(any(field["name"] == "int32_values" for field in objects["int"]["layout"]["fields"]))
        target_coverage = {row["type_name"]: row for row in document["converter_report"]["schema_target_coverage"]}
        for type_name in ("char", "hkaSkeletonMapper", "hkaSkeletonMapperData::SimpleMapping", "hkaAnimationContainer", "int"):
            self.assertEqual("decoded", target_coverage[type_name]["coverage_status"])
        graph_edges = document["relationship_graph"]["edges"]
        self.assertTrue(
            any(
                edge["source"] == "record:1"
                and edge["target"] == "record:2"
                and edge["relation"] == "possible_mapper_simple_mapping"
                for edge in graph_edges
            )
        )
        self.assertTrue(
            any(
                edge["source"] == "record:3"
                and edge["target"] == "record:4"
                and edge["relation"] == "possible_animation_container_record"
                for edge in graph_edges
            )
        )

    def _array_ref_hkx_bytes(self) -> bytes:
        type_names = b"hkArray\0hkRefPtr\0hknpShape\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(64)
        struct.pack_into("<QII", data_payload, 0, 32, 3, 0x80000003)
        struct.pack_into("<Q", data_payload, 16, 32)
        struct.pack_into("<ff", data_payload, 32, 0.25, 1.5)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        return (len(body) + 4).to_bytes(4, "big") + body

    def test_editable_hkx_geometry_import_rejects_array_and_reference_rebuilds(self) -> None:
        data = self._array_ref_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "physics/array_refs.hkx")
        self.assertGreaterEqual(document["relationship_graph"]["reference_edge_count"], 2)
        self.assertTrue(
            any(
                edge["source"] == "record:0"
                and edge["target"] == "record:2"
                and edge["relation"] == "data_offset"
                for edge in document["relationship_graph"]["edges"]
            )
        )

        edited_document = copy.deepcopy(document)
        array_payload = bytearray(bytes.fromhex(edited_document["advanced_record_payloads"][0]["payload_hex"]))
        struct.pack_into("<I", array_payload, 8, 4)
        edited_document["advanced_record_payloads"][0]["payload_hex"] = array_payload.hex(" ")
        with self.assertRaisesRegex(ValueError, "hkArray header"):
            apply_hkx_editable_geometry_document(data, edited_document)

        edited_document = copy.deepcopy(document)
        ref_payload = bytearray(bytes.fromhex(edited_document["advanced_record_payloads"][1]["payload_hex"]))
        struct.pack_into("<Q", ref_payload, 0, 48)
        edited_document["advanced_record_payloads"][1]["payload_hex"] = ref_payload.hex(" ")
        with self.assertRaisesRegex(ValueError, "hkRefPtr reference"):
            apply_hkx_editable_geometry_document(data, edited_document)

    def test_hkx_converter_corpus_report_summarizes_local_hkx_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hkx_path = root / "sample.hkx"
            hkx_path.write_bytes(self._modern_hkx_bytes())
            descriptor_dir = root / "character" / "descriptors" / "physicsattachment"
            descriptor_dir.mkdir(parents=True)
            (descriptor_dir / "sample.xml").write_text(
                (
                    '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                    '<SkinnedMeshPhysicsAttachmentBodyCreationDesc _bodyName="PhysicsAttachment_Test" '
                    '_socketName="Bip01 Pelvis" _physicsMaterialName="sliding" '
                    '_angularDamping="0.500000" _linearDamping="0.250000" _inertiaFactor="4.000000">'
                    '<SkinnedMeshPhysicsAttachmentCapsuleShapeDesc _sphereRadius="0.050000" '
                    '_cylinderHeight="0.110000"/>'
                    '</SkinnedMeshPhysicsAttachmentBodyCreationDesc>'
                    '<SkinnedMeshPhysicsAttachmentRagdollConstraintDesc _coneAngle="60" '
                    '_twistMin="-5" _twistMax="5" _maxFrictionTorque="0.400000"/>'
                    '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                ),
                encoding="utf-8",
            )

            native_report = {
                "format": "cd_hkx_corpus_stats_v1",
                "file_count": 1,
                "ok_count": 1,
                "total_item_records": 14,
                "total_physics_tuning_slots": 0,
            }
            with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=native_report):
                report = build_hkx_converter_corpus_report((root,))
                csv_text = build_hkx_converter_corpus_csv((root,))

        self.assertEqual("cdmw_hkx_converter_corpus_report_v1", report["format"])
        self.assertEqual("cd_hkx_corpus_stats_v1", report["native_fast_scan"]["format"])
        self.assertEqual(14, report["native_fast_scan"]["total_item_records"])
        self.assertEqual(1, report["discovered_file_count"])
        self.assertFalse(report["detail_scan_truncated"])
        self.assertEqual(1, report["file_count"])
        self.assertEqual(1, report["ok_count"])
        self.assertTrue(report["qualification"]["all_no_edit_json_roundtrips_identical"])
        self.assertTrue(report["qualification"]["all_no_edit_xml_roundtrips_identical"])
        self.assertTrue(report["qualification"]["all_unknown_data_preserved"])
        self.assertEqual(1, report["aggregate_compatibility_status_counts"]["preview_linked"])
        self.assertEqual("preview_linked", report["files"][0]["cdmw_hkx_compatibility_status"])
        self.assertTrue(report["qualification"]["has_cdmw_value_editable_or_preview_linked_file"])
        self.assertIn("hknpConvexShape", report["aggregate_type_counts"])
        self.assertEqual(1, report["descriptor_hint_count"])
        self.assertEqual(1, report["files"][0]["companion_descriptor_hint_count"])
        self.assertTrue(report["qualification"]["has_correlated_descriptor_context"])
        self.assertEqual(1, report["files"][0]["physics_body_context_body_count"])
        self.assertEqual(1, report["files"][0]["physics_body_context_constraint_hint_count"])
        self.assertEqual(0, report["files"][0]["physics_body_context_matched_shape_count"])
        self.assertGreater(report["files"][0]["editable_field_catalog_count"], 0)
        self.assertGreater(report["files"][0]["byte_patch_map_count"], 0)
        self.assertTrue(report["files"][0]["editable_field_effect_counts"])
        self.assertTrue(report["aggregate_editable_effect_counts"])
        self.assertTrue(report["qualification"]["has_editable_field_catalog"])
        self.assertTrue(report["qualification"]["has_byte_patch_map"])
        self.assertTrue(report["qualification"]["has_small_object_convex_sample"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["small_object_convex"])
        self.assertEqual(1, report["aggregate_corpus_role_roundtrip_counts"]["small_object_convex"])
        self.assertIn("small_object_convex", report["qualification"]["required_representative_roles"])
        self.assertTrue(report["qualification"]["representative_role_status"]["small_object_convex"]["covered"])
        self.assertTrue(report["qualification"]["representative_role_status"]["small_object_convex"]["roundtrip_complete"])
        self.assertFalse(report["qualification"]["representative_role_status"]["cloak_or_meshphysics"]["covered"])
        self.assertIn("cloak_or_meshphysics", report["qualification"]["missing_representative_roles"])
        self.assertEqual("needs_more_representative_coverage", report["qualification"]["compatibility_gate_status"])
        self.assertFalse(report["qualification"]["meets_full_representative_compatibility_gate"])
        self.assertIn("small_object_convex", report["qualification"]["representative_role_examples"])
        self.assertIn("aggregate_unknown_schema_frequency_priorities", report)
        self.assertIn("aggregate_havok_xml_parity_totals", report)
        self.assertGreater(report["aggregate_havok_xml_parity_totals"]["havok_like_params_emitted"], 0)
        self.assertIn("hknpConvexShape", report["aggregate_havok_xml_class_parity_counts"])
        self.assertIn("aggregate_hkclass_metadata_readiness_status_counts", report)
        self.assertIn("aggregate_native_model_graph_status_counts", report)
        self.assertIn("aggregate_native_low_level_parse_status_counts", report)
        self.assertIn("aggregate_no_edit_binary_writer_status_counts", report)
        self.assertTrue(
            {"byte_identical", "not_started"}.intersection(report["aggregate_no_edit_binary_writer_status_counts"])
        )
        self.assertIn("aggregate_biggest_remaining_gate_status_counts", report)
        self.assertTrue(
            {"blocked", "file_level_passed_representative_corpus_pending"}.intersection(
                report["aggregate_biggest_remaining_gate_status_counts"]
            )
        )
        self.assertIn("aggregate_class_internals_status_counts", report)
        self.assertIn("partial_synthetic_recovery", report["aggregate_class_internals_status_counts"])
        self.assertIn("aggregate_class_internals_target_counts", report)
        self.assertIn("aggregate_hard_decoder_target_status_counts", report)
        self.assertIn("open_hard_decoder_targets", report["aggregate_hard_decoder_target_status_counts"])
        self.assertIn("aggregate_hard_decoder_target_counts", report)
        self.assertIn("aggregate_hard_decoder_target_byte_counts", report)
        self.assertIn("aggregate_gui_readiness_status_counts", report)
        self.assertIn("partial_user_friendly_modding", report["aggregate_gui_readiness_status_counts"])
        self.assertIn("aggregate_gui_readiness_target_status_counts", report)
        self.assertIn("missing", report["aggregate_gui_readiness_target_status_counts"])
        self.assertIn("aggregate_hkclass_metadata_missing_counts", report)
        self.assertIn("member_type_codes", report["aggregate_hkclass_metadata_missing_counts"])
        self.assertIn("first_record_fallback", report["aggregate_havok_xml_root_methods"])
        self.assertIn("aggregate_tagfile_fixup_match_counts", report)
        self.assertIn("aggregate_tagfile_fixup_reference_category_counts", report)
        self.assertIn("aggregate_ptch_tuple_shape_counts", report)
        self.assertIn("corpus_evidence", report)
        self.assertEqual("cdmw_hkx_corpus_evidence_v1", report["corpus_evidence"]["format"])
        self.assertIn("priority_decoder_targets", report["corpus_evidence"])
        self.assertIn("ptch_semantic_targets", report["corpus_evidence"])
        self.assertIn("representative_sample_files", report["corpus_evidence"])
        self.assertEqual("available", report["corpus_evidence"]["native_scan_status"]["status"])
        self.assertIn("ptch_semantics_proof", report)
        self.assertEqual("needs_more_corpus_observations", report["ptch_semantics_proof"]["status"])
        self.assertFalse(report["ptch_semantics_proof"]["proven"])
        self.assertIn("data_references", report["ptch_semantics_proof"]["missing_observations"])
        self.assertEqual("needs_more_corpus_observations", report["qualification"]["ptch_semantics_proof_status"])
        self.assertFalse(report["qualification"]["ptch_semantics_proven"])
        self.assertIn("hard_decoder_corpus_proof", report)
        self.assertEqual("needs_more_corpus_observations", report["hard_decoder_corpus_proof"]["status"])
        self.assertFalse(report["hard_decoder_corpus_proof"]["proven"])
        self.assertIn("hknp_mesh_aabb_tree", report["hard_decoder_corpus_proof"]["missing_observations"])
        self.assertEqual(
            "needs_more_corpus_observations",
            report["qualification"]["hard_decoder_corpus_proof_status"],
        )
        self.assertFalse(report["qualification"]["hard_decoder_corpus_proven"])
        self.assertIn("representative_real_hkx_corpus_plan", report)
        real_corpus_plan = report["representative_real_hkx_corpus_plan"]
        self.assertEqual("cdmw_hkx_representative_real_corpus_plan_v1", real_corpus_plan["format"])
        self.assertEqual("needs_representative_real_hkx_files", real_corpus_plan["status"])
        self.assertTrue(real_corpus_plan["role_status"]["object_hkx"]["covered"])
        self.assertFalse(real_corpus_plan["role_status"]["animation_hkx"]["covered"])
        self.assertIn("cloak_meshphysics_hkx", real_corpus_plan["missing_roles"])
        self.assertIn("data_references", real_corpus_plan["ptch_missing_observations"])
        self.assertIn(
            "object_hkx",
            report["qualification"]["required_representative_real_hkx_roles"],
        )
        self.assertEqual(
            "needs_representative_real_hkx_files",
            report["qualification"]["representative_real_hkx_corpus_status"],
        )
        self.assertIn("fixup_semantics_summary", report["files"][0])
        self.assertIn("hkclass_metadata_readiness_summary", report["files"][0])
        self.assertFalse(report["files"][0]["hkclass_metadata_readiness_summary"]["real_hkclass_metadata_recovered"])
        self.assertTrue(report["files"][0]["hkclass_metadata_readiness_summary"]["python_builds_richer_graph_export"])
        self.assertIn(
            report["files"][0]["hkclass_metadata_readiness_summary"]["no_edit_binary_writer_status"],
            {"byte_identical", "not_started"},
        )
        self.assertIsInstance(
            report["files"][0]["hkclass_metadata_readiness_summary"][
                "byte_identical_no_edit_rebuild_supported"
            ],
            bool,
        )
        self.assertEqual(
            "native_no_edit_read_model_write_byte_identity",
            report["files"][0]["hkclass_metadata_readiness_summary"]["biggest_remaining_gate"],
        )
        self.assertIn(
            report["files"][0]["hkclass_metadata_readiness_summary"]["biggest_remaining_gate_status"],
            {"blocked", "file_level_passed_representative_corpus_pending"},
        )
        self.assertIsInstance(
            report["files"][0]["hkclass_metadata_readiness_summary"]["native_read_model_write_available"],
            bool,
        )
        self.assertIn(
            "object_hkx",
            report["files"][0]["hkclass_metadata_readiness_summary"]["representative_binary_writer_roles"],
        )
        self.assertEqual(
            "partial_synthetic_recovery",
            report["files"][0]["hkclass_metadata_readiness_summary"]["class_internals_status"],
        )
        self.assertEqual(
            "open_hard_decoder_targets",
            report["files"][0]["hkclass_metadata_readiness_summary"]["hard_decoder_targets_status"],
        )
        self.assertGreater(
            report["files"][0]["hkclass_metadata_readiness_summary"]["hard_decoder_unresolved_target_count"],
            0,
        )
        self.assertEqual(
            "partial_user_friendly_modding",
            report["files"][0]["hkclass_metadata_readiness_summary"]["gui_readiness_status"],
        )
        self.assertGreater(report["files"][0]["hkclass_metadata_readiness_summary"]["gui_missing_target_count"], 0)
        self.assertIn(
            "fixup_backed_object_refs",
            report["files"][0]["hkclass_metadata_readiness_summary"]["required_native_graph_capabilities"],
        )
        self.assertIn(
            "template_refs",
            report["files"][0]["hkclass_metadata_readiness_summary"]["missing_real_hkclass_metadata"],
        )
        self.assertEqual("small_object_convex", report["files"][0]["corpus_role"])
        self.assertTrue(report["files"][0]["raw_records_cover_items"])
        self.assertTrue(report["files"][0]["no_edit_json_roundtrip_identical"])
        self.assertTrue(report["files"][0]["no_edit_xml_roundtrip_identical"])
        self.assertGreater(report["files"][0]["hkx_xml_parity_summary"]["havok_like_params_emitted"], 0)
        self.assertEqual("experimental_observation", report["files"][0]["tagfile_reference_fixup_summary"]["status"])
        descriptor_hint = report["files"][0]["companion_descriptor_hints"][0]
        self.assertIn("PhysicsAttachment_Test", descriptor_hint["body_names"])
        self.assertTrue(any(hint["name"] == "_angularDamping" for hint in descriptor_hint["numeric_hints"]))
        self.assertIn("sample.hkx", csv_text)
        self.assertIn("decoded_coverage", csv_text)
        self.assertIn("corpus_role", csv_text)
        self.assertIn("cdmw_hkx_compatibility_status", csv_text)
        self.assertIn("no_edit_json_roundtrip_identical", csv_text)
        self.assertIn("companion_descriptor_hint_count", csv_text)
        self.assertIn("mesh_detail_shape_count", csv_text)
        self.assertIn("physics_shape_name_count", csv_text)
        self.assertIn("physics_named_collision_shape_count", csv_text)
        self.assertIn("editable_field_catalog_count", csv_text)
        self.assertIn("byte_patch_map_count", csv_text)
        self.assertIn("editable_field_effect_counts", csv_text)
        self.assertIn("physics_body_context_body_count", csv_text)
        self.assertIn("hkx_xml_parity_summary", csv_text)
        self.assertIn("hkclass_metadata_readiness_summary", csv_text)
        self.assertIn("tagfile_reference_fixup_summary", csv_text)
        self.assertIn("fixup_semantics_summary", csv_text)

    def test_hkx_converter_corpus_report_marks_ptch_semantics_blocked_without_local_hkx_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                report = build_hkx_converter_corpus_report((root,))

        proof = report["ptch_semantics_proof"]
        self.assertEqual("cdmw_hkx_ptch_semantics_proof_v1", proof["format"])
        self.assertEqual("blocked_no_local_hkx_corpus", proof["status"])
        self.assertFalse(proof["local_hkx_corpus_available"])
        self.assertFalse(proof["proven"])
        self.assertEqual(0, proof["discovered_hkx_file_count"])
        self.assertIn("No local .hkx corpus", proof["blocker"])
        self.assertIn("data_references", proof["missing_observations"])
        hard_proof = report["hard_decoder_corpus_proof"]
        self.assertEqual("cdmw_hkx_hard_decoder_corpus_proof_v1", hard_proof["format"])
        self.assertEqual("blocked_no_local_hkx_corpus", hard_proof["status"])
        self.assertFalse(hard_proof["local_hkx_corpus_available"])
        self.assertIn("hknp_mesh_primitive_bit_layout", hard_proof["missing_observations"])
        plan = report["representative_real_hkx_corpus_plan"]
        self.assertEqual("cdmw_hkx_representative_real_corpus_plan_v1", plan["format"])
        self.assertEqual("blocked_no_local_hkx_corpus", plan["status"])
        self.assertFalse(plan["local_hkx_corpus_available"])
        self.assertIn("object_hkx", plan["missing_roles"])
        self.assertIn("animation_hkx", plan["missing_roles"])

    def test_hkx_converter_corpus_report_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            object_dir = root / "object"
            object_dir.mkdir()
            (object_dir / "cancel.hkx").write_bytes(self._modern_hkx_bytes())
            stop_event = threading.Event()
            stop_event.set()
            with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                with self.assertRaises(RunCancelled):
                    build_hkx_converter_corpus_report((root,), stop_event=stop_event)

    def test_hkx_converter_corpus_plan_ignores_generated_target_hkx_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_dir = root / "native" / "cd_hkx" / "target"
            target_dir.mkdir(parents=True)
            (target_dir / "test-modern.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                report = build_hkx_converter_corpus_report((root,))

        self.assertEqual(1, report["discovered_file_count"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["small_object_convex"])
        plan = report["representative_real_hkx_corpus_plan"]
        self.assertEqual("blocked_no_representative_real_hkx_corpus", plan["status"])
        self.assertTrue(plan["local_hkx_corpus_available"])
        self.assertFalse(plan["representative_real_hkx_corpus_available"])
        self.assertEqual(0, plan["eligible_real_hkx_file_count"])
        self.assertEqual(1, plan["ignored_generated_or_build_artifact_count"])
        self.assertIn("object_hkx", plan["missing_roles"])

    def test_hkx_converter_corpus_report_caps_large_detail_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.hkx").write_bytes(self._modern_hkx_bytes())
            (root / "b.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch.dict(os.environ, {"CDMW_HKX_CORPUS_DETAIL_LIMIT": "1"}):
                with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                    report = build_hkx_converter_corpus_report((root,))

        self.assertEqual(2, report["discovered_file_count"])
        self.assertEqual(1, report["detail_file_limit"])
        self.assertTrue(report["detail_scan_truncated"])
        self.assertEqual(1, report["file_count"])

    def test_hkx_converter_corpus_report_caps_roundtrip_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.hkx").write_bytes(self._modern_hkx_bytes())
            (root / "b.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch.dict(os.environ, {"CDMW_HKX_CORPUS_ROUNDTRIP_LIMIT": "1"}):
                with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                    report = build_hkx_converter_corpus_report((root,))

        self.assertEqual(2, report["file_count"])
        self.assertEqual(1, report["roundtrip_file_limit"])
        self.assertTrue(report["roundtrip_scan_limited"])
        self.assertEqual(1, report["roundtrip_verified_file_count"])
        self.assertEqual(1, report["roundtrip_skipped_file_count"])
        self.assertEqual("verified", report["files"][0]["no_edit_roundtrip_status"])
        self.assertEqual("skipped_roundtrip_limit", report["files"][1]["no_edit_roundtrip_status"])
        self.assertIsNone(report["files"][1]["no_edit_json_roundtrip_identical"])

    def test_hkx_converter_corpus_report_balances_limited_representative_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            object_dir = root / "object"
            meshphysics_dir = root / "character" / "bin__" / "meshphysics" / "armor" / "19_cloak"
            havokphysics_dir = root / "character" / "bin__" / "havokphysics" / "1_pc" / "2_phw"
            for folder in (object_dir, meshphysics_dir, havokphysics_dir):
                folder.mkdir(parents=True)
            (object_dir / "a.hkx").write_bytes(self._modern_hkx_bytes())
            (object_dir / "b.hkx").write_bytes(self._modern_hkx_bytes())
            (meshphysics_dir / "cloak.hkx").write_bytes(self._modern_hkx_bytes())
            (havokphysics_dir / "body.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch.dict(os.environ, {"CDMW_HKX_CORPUS_DETAIL_LIMIT": "3"}):
                with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                    report = build_hkx_converter_corpus_report((root,))

        self.assertTrue(report["detail_scan_truncated"])
        self.assertEqual(3, report["file_count"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["small_object_convex"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["cloak_or_meshphysics"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["character_havokphysics_or_ragdoll"])
        plan = report["representative_real_hkx_corpus_plan"]
        self.assertTrue(plan["role_status"]["object_hkx"]["covered"])
        self.assertTrue(plan["role_status"]["cloak_meshphysics_hkx"]["covered"])
        self.assertTrue(plan["role_status"]["character_havokphysics_hkx"]["covered"])
        self.assertTrue(plan["role_status"]["ragdoll_body_hkx"]["covered"])
        self.assertIn("mesh_heavy_hkx", plan["missing_roles"])

    def test_hkx_converter_corpus_report_promotes_mesh_shape_marker_in_limited_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            object_dir = root / "object" / "plain_names"
            object_dir.mkdir(parents=True)
            (object_dir / "a_regular_object.hkx").write_bytes(self._modern_hkx_bytes())
            (object_dir / "b_regular_object.hkx").write_bytes(self._modern_hkx_bytes())
            (object_dir / "c_plain_mesh_object.hkx").write_bytes(self._mesh_shape_hkx_bytes())
            with mock.patch.dict(
                os.environ,
                {
                    "CDMW_HKX_CORPUS_DETAIL_LIMIT": "2",
                    "CDMW_HKX_CORPUS_BALANCE_CONTENT_LIMIT": "10",
                },
            ):
                with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                    report = build_hkx_converter_corpus_report((root,))

        self.assertTrue(report["detail_scan_truncated"])
        self.assertEqual(2, report["file_count"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["small_object_convex"])
        self.assertEqual(1, report["aggregate_corpus_role_counts"]["mesh_shape_heavy"])
        mesh_row = next(row for row in report["files"] if row["corpus_role"] == "mesh_shape_heavy")
        self.assertEqual(1, mesh_row["mesh_shape_count"])
        self.assertTrue(mesh_row["no_edit_json_roundtrip_identical"])
        self.assertTrue(mesh_row["no_edit_xml_roundtrip_identical"])

    def test_hkx_converter_corpus_report_can_limit_discovery_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                (root / f"{index}.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch.dict(
                os.environ,
                {
                    "CDMW_HKX_CORPUS_DISCOVERY_LIMIT": "2",
                    "CDMW_HKX_CORPUS_DETAIL_LIMIT": "10",
                },
            ):
                with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None):
                    report = build_hkx_converter_corpus_report((root,))

        self.assertEqual(2, report["discovered_file_count"])
        self.assertEqual(2, report["discovery_file_limit"])
        self.assertTrue(report["discovery_scan_limited"])
        self.assertFalse(report["detail_scan_truncated"])
        self.assertEqual(2, report["file_count"])

    def test_hkx_converter_corpus_report_accepts_explicit_ui_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(4):
                (root / f"{index}.hkx").write_bytes(self._modern_hkx_bytes())
            with mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None) as native_scan:
                report = build_hkx_converter_corpus_report(
                    (root,),
                    discovery_limit=3,
                    detail_scan_limit=2,
                )

        self.assertEqual(3, report["discovered_file_count"])
        self.assertEqual(3, report["discovery_file_limit"])
        self.assertTrue(report["discovery_scan_limited"])
        self.assertEqual(2, report["detail_file_limit"])
        self.assertTrue(report["detail_scan_truncated"])
        self.assertEqual(2, report["file_count"])
        self.assertEqual(2, native_scan.call_args.kwargs["max_files"])

    def test_hkx_corpus_evidence_extracts_decoder_priorities_from_existing_report(self) -> None:
        report = {
            "format": "cdmw_hkx_converter_corpus_report_v1",
            "discovered_file_count": 57268,
            "file_count": 57268,
            "ok_count": 57268,
            "native_fast_scan": None,
            "aggregate_unknown_schema_type_priorities": [
                {
                    "type_name": "hknpTriangleShape",
                    "record_count": 649,
                    "raw_preserved_byte_count": 80680,
                    "raw_preserved_byte_share": 0.917,
                },
                {
                    "type_name": "hknpBallAndSocketConstraintData",
                    "record_count": 26,
                    "raw_preserved_byte_count": 3328,
                    "raw_preserved_byte_share": 0.037,
                },
            ],
            "aggregate_unknown_schema_frequency_priorities": [
                {
                    "type_name": "hknpTriangleShape",
                    "record_count": 649,
                    "raw_preserved_byte_count": 80680,
                    "record_count_share": 0.89,
                }
            ],
            "aggregate_class_internals_target_counts": {
                "hknpPhysicsSystemData": 267,
                "hknpMaterial": 267,
                "hknpRagdollConstraintData": 224,
            },
            "aggregate_hard_decoder_target_counts": {
                "hknp_mesh_aabb_tree": 49372,
                "hknp_mesh_primitive_bit_layout": 2180,
            },
            "aggregate_hard_decoder_target_byte_counts": {
                "hknp_mesh_aabb_tree": 0,
                "hknp_mesh_primitive_bit_layout": 0,
            },
            "aggregate_mesh_detail_group_counts": {
                "aabb_tree_nodes": 545419,
                "primitive_buffers": 545419,
                "geometry_sections": 249900,
                "shape_tag_table": 249900,
                "mesh_byte_buffers": 180825,
            },
            "aggregate_tagfile_ptch_patch_site_count": 631193,
            "aggregate_tagfile_ptch_resolved_patch_site_count": 631193,
            "aggregate_tagfile_ptch_unresolved_patch_site_count": 0,
            "aggregate_tagfile_ptch_null_patch_site_count": 0,
            "aggregate_tagfile_ptch_target_status_counts": {"object": 631193},
            "aggregate_ptch_payload_match_kind_counts": {
                "ptch_type_index": 23134,
                "ptch_data_offset": 112,
            },
            "aggregate_ptch_semantics_reference_category_counts": {
                "type_reference": 2691831,
                "data_reference_candidate": 262,
                "unresolved_fixup_word": 13,
            },
            "aggregate_ptch_varuint_status_counts": {
                "decoded_sample": 53841,
                "not_decoded": 57267,
                "stopped: Unrecognized Havok packed integer marker byte 0xF8.": 2453,
            },
            "aggregate_ptch_remaining_case_priorities": [
                {
                    "case": "reference_category:type_reference",
                    "count": 2691831,
                    "description": "Observed reference category is not yet promoted.",
                },
                {
                    "case": "reference_category:data_reference_candidate",
                    "count": 262,
                    "description": "Data-reference candidate.",
                },
                {
                    "case": "reference_category:unresolved_fixup_word",
                    "count": 13,
                    "description": "Unresolved fixup word.",
                },
                {
                    "case": "varuint_status:stopped: Unrecognized Havok packed integer marker byte 0xF8.",
                    "count": 2453,
                    "description": "Packed marker needs proof.",
                },
            ],
            "aggregate_havok_xml_reference_category_counts": {
                "object_reference": 5266928,
                "string_reference": 11690,
                "type_class_reference": 267,
            },
            "aggregate_havok_xml_reference_resolution_source_counts": {
                "inferred_offset": 12246831,
                "ptch": 944099,
            },
            "ptch_semantics_proof": {
                "requirements": [
                    {"key": "object_or_null_patch_sites", "label": "PTCH object/null patch sites", "observed": True, "observation_count": 631193},
                    {"key": "data_references", "label": "PTCH data-reference candidates", "observed": True, "observation_count": 524},
                    {"key": "string_references", "label": "PTCH string-reference candidates", "observed": False, "observation_count": 0},
                    {"key": "type_references", "label": "PTCH type/class-reference candidates", "observed": True, "observation_count": 2714965},
                    {"key": "section_local_or_packed_indexes", "label": "Section-local or packed index variants", "observed": False, "observation_count": 0},
                    {"key": "packed_or_varuint_variants", "label": "Packed/varuint fixup variants", "observed": True, "observation_count": 57269},
                ]
            },
            "representative_real_hkx_corpus_plan": {
                "role_status": {
                    "object_hkx": {
                        "label": "Object HKX",
                        "covered": True,
                        "file_count": 57136,
                        "roundtrip_identical_count": 32,
                        "roundtrip_complete": False,
                        "examples": ["C:/HKX/0000/object/example.hkx"],
                    },
                    "mesh_heavy_hkx": {
                        "label": "Mesh-heavy HKX",
                        "covered": True,
                        "file_count": 2180,
                        "roundtrip_identical_count": 0,
                        "roundtrip_complete": False,
                        "examples": ["C:/HKX/0000/object/mesh.hkx"],
                    },
                }
            },
            "files": [
                {
                    "path": "C:/HKX/0000/object/break/debris.hkx",
                    "unknown_schema_areas": [{"type_name": "hknpTriangleShape"}],
                    "type_names": ["hknpTriangleShape"],
                    "fixup_semantics_summary": {
                        "ptch_remaining_case_priorities": [
                            {"case": "reference_category:data_reference_candidate", "count": 19}
                        ]
                    },
                },
                {
                    "path": "C:/HKX/0000/object/mesh.hkx",
                    "type_names": ["hknpMeshShape"],
                    "hkclass_metadata_readiness_summary": {
                        "hard_decoder_observed_targets": ["hknp_mesh_aabb_tree"]
                    },
                    "fixup_semantics_summary": {
                        "ptch_remaining_case_priorities": [
                            {"case": "reference_category:unresolved_fixup_word", "count": 13}
                        ]
                    },
                },
            ],
        }

        evidence = build_hkx_corpus_evidence_from_report(report)

        self.assertEqual("cdmw_hkx_corpus_evidence_v1", evidence["format"])
        self.assertFalse(evidence["source_report_external"])
        self.assertEqual("unavailable", evidence["native_scan_status"]["status"])
        self.assertEqual(631193, evidence["ptch_patch_site_summary"]["found"])
        self.assertEqual(631193, evidence["ptch_patch_site_summary"]["resolved"])
        targets = {target["target"]: target for target in evidence["priority_decoder_targets"]}
        self.assertEqual(80680, targets["hknpTriangleShape"]["raw_preserved_byte_count"])
        self.assertIn("C:/HKX/0000/object/break/debris.hkx", targets["hknpTriangleShape"]["sample_paths"])
        self.assertIn("hknpPhysicsSystemData", targets)
        self.assertIn("hknp_mesh_aabb_tree", targets)
        ptch_targets = {target["key"]: target for target in evidence["ptch_semantic_targets"]}
        self.assertTrue(ptch_targets["data_references"]["observed"])
        self.assertFalse(ptch_targets["string_references"]["observed"])
        self.assertTrue(ptch_targets["packed_or_varuint_variants"]["observed"])
        self.assertEqual("remaining_case", ptch_targets["reference_category:unresolved_fixup_word"]["status"])
        self.assertIn(
            "C:/HKX/0000/object/mesh.hkx",
            ptch_targets["reference_category:unresolved_fixup_word"]["sample_paths"],
        )
        self.assertEqual(2, len(evidence["roundtrip_required_files"]))
        self.assertEqual(545419, evidence["mesh_detail_group_counts"]["aabb_tree_nodes"])
        self.assertEqual(944099, evidence["reference_parity_summary"]["havok_xml_reference_resolution_sources"]["ptch"])

    def test_hkx_corpus_evidence_loader_reads_external_report_without_runtime_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "sample.hkx-corpus.json"
            report_path.write_text(
                json.dumps(
                    {
                        "format": "cdmw_hkx_converter_corpus_report_v1",
                        "discovered_file_count": 2,
                        "file_count": 1,
                        "ok_count": 1,
                        "native_fast_scan": {"format": "cd_hkx_corpus_stats_v1", "file_count": 1, "ok_count": 1},
                        "files": [{"path": "C:/HKX/object/a.hkx", "type_names": ["hknpBoxShape"]}],
                    }
                ),
                encoding="utf-8",
            )

            evidence = load_hkx_corpus_evidence_json(report_path)

        self.assertEqual("cdmw_hkx_corpus_evidence_v1", evidence["format"])
        self.assertTrue(evidence["source_report_external"])
        self.assertEqual(str(report_path), evidence["source_report_path"])
        self.assertGreater(evidence["source_report_size"], 0)
        self.assertEqual("available", evidence["native_scan_status"]["status"])
        self.assertNotIn("files", evidence)

    def test_hkx_xml_layout_text_strips_invalid_xml_characters(self) -> None:
        root = ET.Element("root")
        _hkx_xml_add_value_layout(
            root,
            "offset_count_pairs",
            [{"description": "bad\0description", "offset": 104}],
        )
        xml_text = ET.tostring(root, encoding="unicode")

        self.assertNotIn("\0", xml_text)
        ET.fromstring(xml_text)

    def test_editable_hkx_geometry_export_embeds_companion_descriptor_hints(self) -> None:
        data = self._modern_hkx_bytes()
        descriptor_text = (
            '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
            '<SkinnedMeshPhysicsAttachmentBodyCreationDesc _bodyName="PhysicsAttachment_Chest" '
            '_socketName="Spine2" _physicsMaterialName="cloth_body" '
            '_angularDamping="0.750000" _linearDamping="0.350000" _inertiaFactor="2.000000">'
            '<SkinnedMeshPhysicsAttachmentCapsuleShapeDesc _sphereRadius="0.090000" '
            '_cylinderHeight="0.250000"/>'
            '</SkinnedMeshPhysicsAttachmentBodyCreationDesc>'
            '<SkinnedMeshPhysicsAttachmentLimitedHingeConstraintDesc _angularLimitMin="-10 0 0" '
            '_angularLimitMax="15 0 0" _maxFrictionTorque="0.600000"/>'
            '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
        )
        hint = build_hkx_descriptor_hint_from_xml_text(descriptor_text, "character/bin__/havokphysics/phw_01.xml")

        self.assertIsNotNone(hint)
        document = build_hkx_editable_geometry_document(data, "character/bin__/havokphysics/phw_01.hkx", [hint])
        xml_text = build_hkx_editable_geometry_xml(data, "character/bin__/havokphysics/phw_01.hkx", [hint])

        self.assertEqual(1, len(document["companion_descriptor_hints"]))
        self.assertIn("PhysicsAttachment_Chest", document["companion_descriptor_hints"][0]["body_names"])
        self.assertTrue(any(item["name"] == "_angularDamping" for item in document["companion_descriptor_hints"][0]["numeric_hints"]))
        self.assertEqual(1, len(document["companion_descriptor_hints"][0]["body_descriptors"]))
        self.assertEqual("Spine2", document["companion_descriptor_hints"][0]["body_descriptors"][0]["socket_name"])
        self.assertEqual("capsule", document["companion_descriptor_hints"][0]["body_descriptors"][0]["shape_descriptors"][0]["shape_kind"])
        self.assertEqual(1, len(document["companion_descriptor_hints"][0]["constraint_descriptors"]))
        self.assertIn("<companionDescriptorHints", xml_text)
        self.assertIn("<bodyDescriptors>", xml_text)
        self.assertIn("<constraintDescriptors>", xml_text)
        self.assertIn("imported=\"false\"", xml_text)
        self.assertIn("PhysicsAttachment_Chest", xml_text)
        result = apply_hkx_editable_geometry_xml(data, xml_text)
        self.assertEqual(data, result.data)
        self.assertFalse(result.changed_fields)

    def test_editable_hkx_geometry_json_rejects_vertex_count_changes(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        edited_document = copy.deepcopy(document)
        edited_document["shapes"][0]["vertices"].append([0.0, 0.0, 0.0])

        with self.assertRaisesRegex(ValueError, "exactly 4 row"):
            apply_hkx_editable_geometry_document(data, edited_document)

    def test_editable_hkx_geometry_import_ignores_description_metadata(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        edited_document = copy.deepcopy(document)
        edited_document["description"] = "human note changed by editor"
        edited_document["editable_value_descriptions"]["vertices"] = "changed explanation"
        edited_document["editable_value_layouts"]["vertices"] = {"row": "changed explanation"}
        edited_document["shapes"][0]["descriptions"]["vertices"] = "changed field explanation"
        edited_document["shapes"][0]["value_layouts"]["vertices"] = {"row": "changed field explanation"}
        edited_document["shapes"][0]["custom_notes"] = {"vertices": [999.0, 999.0, 999.0]}
        edited_document["converter_report"]["records"][0]["status"] = "decoded_by_human_note"
        edited_document["tag_sections"][0]["declared_length"] = 999999
        edited_document["type_registry"]["type_infos"][0]["display_name"] = "changed display label"
        edited_document["objects"][0]["layout"]["fields"][0]["description"] = "changed layout note"
        edited_document["objects"][0]["raw_ranges"][0]["size"] = 1
        edited_document["raw_records"][0]["payload_hex"] = "ff"

        result = apply_hkx_editable_geometry_document(data, edited_document)

        self.assertEqual(data, result.data)
        self.assertEqual([], result.changed_fields)
        self.assertEqual([], result.warnings)

    def test_editable_hkx_geometry_import_rejects_advanced_payload_length_changes(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")
        edited_document = copy.deepcopy(document)
        edited_document["advanced_record_payloads"][0]["payload_hex"] = "00"

        with self.assertRaisesRegex(ValueError, "exactly"):
            apply_hkx_editable_geometry_document(data, edited_document)

    def test_editable_hkx_geometry_import_rejects_converter_structure_drift(self) -> None:
        data = self._modern_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/test.hkx")

        edited_document = copy.deepcopy(document)
        edited_document["converter_report"]["item_record_count"] += 1
        with self.assertRaisesRegex(ValueError, "converter_report.item_record_count"):
            apply_hkx_editable_geometry_document(data, edited_document)

        edited_document = copy.deepcopy(document)
        edited_document["objects"].pop()
        with self.assertRaisesRegex(ValueError, "objects must keep exactly"):
            apply_hkx_editable_geometry_document(data, edited_document)

        edited_document = copy.deepcopy(document)
        edited_document["advanced_record_payloads"][0]["type_name"] = "hknpDifferentShape"
        with self.assertRaisesRegex(ValueError, "advanced_record_payloads\\[0\\].type_name"):
            apply_hkx_editable_geometry_document(data, edited_document)

        edited_document = copy.deepcopy(document)
        edited_document["shapes"].append({"index": 999, "records": {}})
        with self.assertRaisesRegex(ValueError, "shapes must keep exactly"):
            apply_hkx_editable_geometry_document(data, edited_document)

    def test_editable_hkx_geometry_xml_exports_and_reapplies_fixed_size_vertex_edits(self) -> None:
        data = self._modern_hkx_bytes()
        xml_text = build_hkx_editable_geometry_xml(data, "object/test.hkx")

        root = ET.fromstring(xml_text)
        self.assertEqual("cdmwHkxGeometryPatch", root.tag)
        self.assertEqual("cdmw_hkx_geometry_patch_v1", root.get("format"))
        self.assertEqual("false", root.get("official_havok_xml"))
        self.assertIsNotNone(root.find("./editableValueDescriptions/field[@name='vertices']"))
        self.assertIsNotNone(root.find("./cdmwHkxCompatibility[@status='preview_linked']"))
        self.assertIsNotNone(root.find("./cdmwHkxCompatibility/gates/gate[@name='editable_patch_targets']"))
        self.assertEqual("preview_linked", root.find("./converterReport").get("cdmw_hkx_compatibility_status"))
        self.assertIsNotNone(root.find("./converterReport/decodeCoverageByType/type[@type_name='hknpConvexShape']"))
        self.assertIsNotNone(root.find("./converterReport/failedOrUnknownSchemaAreas"))
        converter_record = root.find("./converterReport/records/record")
        self.assertIsNotNone(converter_record)
        assert converter_record is not None
        self.assertTrue(converter_record.get("status_label"))
        self.assertTrue(converter_record.get("decode_category"))
        self.assertIsNotNone(converter_record.get("missing_requirements"))
        self.assertIsNotNone(root.find("./tagSections/section[@name='DATA']"))
        self.assertIsNotNone(root.find("./typeRegistry/type"))
        self.assertIsNotNone(root.find("./havokXmlView[@official_havok_xml='false']"))
        self.assertIsNotNone(root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection[@name='__types__']/hkobject[@class='hkClass']"))
        self.assertIsNotNone(root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject"))
        self.assertIsNotNone(root.find("./havokXmlView/hkpackfileView/hkpackfile/hksection/hkobject/hkparam"))
        self.assertIsNotNone(root.find("./havokXmlView/hkobject"))
        self.assertIsNotNone(root.find("./havokXmlView/hkobject/field"))
        object_record = root.find("./objects/object")
        self.assertIsNotNone(object_record)
        assert object_record is not None
        self.assertTrue(object_record.get("status_label"))
        self.assertTrue(object_record.get("decode_category"))
        self.assertIsNotNone(root.find("./objects/object/layout/field"))
        self.assertIsNotNone(root.find("./objects/object/rawRanges/range"))
        self.assertIsNotNone(root.find("./reimportPolicy/rejected_changes/rejectedChange"))
        self.assertEqual("strict_fixed_size_patch_only", root.find("./reimportPolicy").get("status"))
        self.assertIsNotNone(root.find("./rawRecords/record/payload"))
        self.assertIsNotNone(root.find("./schemaObservations/recordPayloadSummaries/record[@type_name='hknpCompoundShape']"))
        self.assertIsNotNone(root.find("./advancedRecordPayloads/record[@type_name='hknpConvexShape']/payload"))
        self.assertIsNotNone(root.find("./advancedRecordPayloads/record[@type_name='hknpConvexShape']/interpretation/role"))
        self.assertIsNotNone(root.find("./advancedRecordPayloads/record[@type_name='hknpConvexShape']/interpretation/offsetCountPair"))
        self.assertIsNotNone(root.find("./advancedRecordPayloads/record[@type_name='hknpConvexHull::Face']/editableValues/records/face"))
        self.assertIsNotNone(root.find("./shapes/shape/mass_properties/row"))
        self.assertIsNotNone(root.find("./shapes/shape/shape_payload/float"))
        self.assertIsNotNone(root.find("./shapes/shape/hull_topology/face_records/face"))
        self.assertIsNotNone(root.find("./shapes/shape/hull_topology/face_indices"))
        vertex_patch_entry = root.find("./bytePatchMap/entries/entry[@path='shapes[0].vertices[0].x']")
        self.assertIsNotNone(vertex_patch_entry)
        assert vertex_patch_entry is not None
        self.assertEqual("fixed_size_value_only", vertex_patch_entry.get("edit_rule"))
        self.assertTrue(vertex_patch_entry.get("original_bytes_hex"))
        self.assertEqual("false", root.find("./bytePatchMap").get("imported"))
        first_vertex = root.find("./shapes/shape/vertices/v")
        self.assertIsNotNone(first_vertex)
        assert first_vertex is not None
        first_vertex.set("x", "-3.25")
        first_vertex.set("y", "0.75")
        first_vertex.set("z", "-4.5")
        mass_row = root.find("./shapes/shape/mass_properties/row[@index='3']")
        self.assertIsNotNone(mass_row)
        assert mass_row is not None
        mass_row.set("x", "6.0")
        mass_row.set("y", "7.0")
        mass_row.set("z", "8.0")
        mass_row.set("w", "9.0")
        payload_slot = root.find("./shapes/shape/shape_payload/float[@offset='104']")
        self.assertIsNotNone(payload_slot)
        assert payload_slot is not None
        payload_slot.set("value", "0.375")
        raw_payload = root.find("./advancedRecordPayloads/record[@index='0']/payload")
        self.assertIsNotNone(raw_payload)
        assert raw_payload is not None
        raw_payload.text = "7E" + str(raw_payload.text or "")[2:]
        face_record = root.find("./advancedRecordPayloads/record[@type_name='hknpConvexHull::Face']/editableValues/records/face[@index='0']")
        self.assertIsNotNone(face_record)
        assert face_record is not None
        face_record.set("meta", "125")

        patch_result = apply_hkx_editable_geometry_xml(data, ET.tostring(root, encoding="unicode"))
        reparsed_document = build_hkx_editable_geometry_document(patch_result.data, "object/test.hkx")

        self.assertEqual(len(data), len(patch_result.data))
        self.assertIn("shape[0].vertices", patch_result.changed_fields)
        self.assertIn("shape[0].mass_properties", patch_result.changed_fields)
        self.assertIn("shape[0].shape_payload", patch_result.changed_fields)
        self.assertIn("record[0].payload", patch_result.changed_fields)
        self.assertIn("record[5].editable_values", patch_result.changed_fields)
        self.assertEqual([-3.25, 0.75, -4.5], reparsed_document["shapes"][0]["vertices"][0])
        self.assertEqual([6.0, 7.0, 8.0, 9.0], reparsed_document["shapes"][0]["mass_properties"]["float_rows"][3])
        self.assertEqual(0.375, reparsed_document["shapes"][0]["shape_payload"]["float_slots"][0]["value"])
        self.assertTrue(reparsed_document["advanced_record_payloads"][0]["payload_hex"].startswith("7e "))
        reparsed_face_payload = next(
            record
            for record in reparsed_document["advanced_record_payloads"]
            if record["type_name"] == "hknpConvexHull::Face"
        )
        self.assertEqual(125, reparsed_face_payload["editable_values"]["records"][0]["meta"])

    def test_modern_tagfile_summary_decodes_direct_sphere_shape_hint(self) -> None:
        type_names = b"\0".join(
            (
                b"hkArray",
                b"hkRefPtr",
                b"hknpShape",
                b"hkBuiltinContainerAllocator",
                b"hknpSphereShape",
                b"hkFloat3",
            )
        ) + b"\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000005).to_bytes(4, "little") + (24).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000006).to_bytes(4, "little") + (144).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(160)
        struct.pack_into("<f", data_payload, 24 + 0x68, 0.5)
        struct.pack_into("<fff", data_payload, 144, 1.0, 2.0, 3.0)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(6), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        summary = parse_hkx_tagfile_summary(data)
        preview = build_hkx_preview(data, "object/unitsphere.hkx")

        self.assertEqual(1, len(summary.collision_geometry_hints))
        geometry_hint = summary.collision_geometry_hints[0]
        self.assertEqual("hknpSphereShape", geometry_hint.shape_type)
        self.assertEqual(0.5, geometry_hint.radius)
        self.assertEqual((0.5, 1.5, 2.5), geometry_hint.bounds_min)
        self.assertEqual((1.5, 2.5, 3.5), geometry_hint.bounds_max)
        self.assertIn("hknpSphereShape; shape-record=2; radius=0.5", preview.preview_text)
        self.assertTrue(any("radius=0.5" in line for line in preview.detail_lines))

        exported = build_hkx_editable_geometry_json(data, "object/unitsphere.hkx")
        exported_document = json.loads(exported)
        exported_document["shapes"][0]["sphere_center"] = [2.0, 3.0, 4.0]
        exported_document["shapes"][0]["sphere_radius"] = 0.75
        patch_result = apply_hkx_editable_geometry_json(data, json.dumps(exported_document))
        reparsed = build_hkx_editable_geometry_document(patch_result.data, "object/unitsphere.hkx")

        self.assertEqual(len(data), len(patch_result.data))
        self.assertIn("shape[0].sphere_center", patch_result.changed_fields)
        self.assertIn("shape[0].sphere_radius", patch_result.changed_fields)
        self.assertEqual([2.0, 3.0, 4.0], reparsed["shapes"][0]["sphere_center"])
        self.assertEqual(0.75, reparsed["shapes"][0]["sphere_radius"])

    def test_modern_tagfile_summary_decodes_capsule_shape_hint(self) -> None:
        type_names = b"\0".join(
            (
                b"hkArray",
                b"hkRefPtr",
                b"hknpShape",
                b"hkBuiltinContainerAllocator",
                b"hknpCapsuleShape",
                b"hkFloat3",
            )
        ) + b"\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000005).to_bytes(4, "little") + (24).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000006).to_bytes(4, "little") + (144).to_bytes(4, "little") + (2).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(192)
        struct.pack_into("<f", data_payload, 24 + 0x68, 0.25)
        struct.pack_into("<fff", data_payload, 144, 0.0, 0.0, 0.0)
        struct.pack_into("<fff", data_payload, 156, 0.0, 2.0, 0.0)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(6), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        summary = parse_hkx_tagfile_summary(data)
        preview = build_hkx_preview(data, "object/capsule.hkx")
        descriptor_hint = build_hkx_descriptor_hint_from_xml_text(
            (
                '<SkinnedMeshPhysicsAttachmentInstanceDescSet>'
                '<SkinnedMeshPhysicsAttachmentBodyCreationDesc _bodyName="PhysicsAttachment_Capsule" '
                '_socketName="Pelvis" _physicsMaterialName="body">'
                '<SkinnedMeshPhysicsAttachmentCapsuleShapeDesc _sphereRadius="0.250000" '
                '_cylinderHeight="2.000000"/>'
                '</SkinnedMeshPhysicsAttachmentBodyCreationDesc>'
                '<SkinnedMeshPhysicsAttachmentRagdollConstraintDesc _coneAngle="45" _maxFrictionTorque="0.2"/>'
                '</SkinnedMeshPhysicsAttachmentInstanceDescSet>'
            ),
            "character/bin__/havokphysics/phw_01.xml",
        )
        self.assertIsNotNone(descriptor_hint)
        document = build_hkx_editable_geometry_document(data, "object/capsule.hkx", [descriptor_hint])
        xml_text = build_hkx_editable_geometry_xml(data, "object/capsule.hkx", [descriptor_hint])

        self.assertEqual(1, len(summary.collision_geometry_hints))
        geometry_hint = summary.collision_geometry_hints[0]
        self.assertEqual("hknpCapsuleShape", geometry_hint.shape_type)
        self.assertEqual(0.25, geometry_hint.radius)
        self.assertEqual(2.0, geometry_hint.capsule_length)
        self.assertEqual((-0.25, -0.25, -0.25), geometry_hint.bounds_min)
        self.assertEqual((0.25, 2.25, 0.25), geometry_hint.bounds_max)
        self.assertIn("hknpCapsuleShape; shape-record=2; radius=0.25; capsule length=2", preview.preview_text)
        capsule_shape = document["shapes"][0]
        self.assertEqual("hknpCapsuleShape", capsule_shape["shape_type"])
        self.assertEqual(0.25, capsule_shape["capsule_summary"]["radius"])
        self.assertEqual([0.0, 2.0, 0.0], capsule_shape["capsule_summary"]["end"])
        self.assertEqual(0.25, capsule_shape["capsule_radius"])
        self.assertEqual([[0.0, 0.0, 0.0], [0.0, 2.0, 0.0]], capsule_shape["capsule_endpoints"])
        self.assertIn("capsule_radius", capsule_shape["editable_fields"])
        self.assertIn("capsule_endpoints", capsule_shape["editable_fields"])
        self.assertTrue(
            any(
                field["category"] == "collision_shape"
                and field["editor_tab"] == "Collision Editor"
                and field["shape_index"] == 0
                and field["name"] == "capsule_radius"
                and field["subject"] == "PhysicsAttachment_Capsule"
                and field["effect"] == "collision volume"
                for field in document["editable_field_catalog"]["fields"]
            )
        )
        self.assertTrue(
            any(
                entry["path"] == "shapes[0].capsule_radius"
                and entry["hex_relative_offset"] == "0x68"
                and entry["value_type"] == "float32"
                for entry in document["byte_patch_map"]["entries"]
            )
        )
        self.assertIn("capsule_summary", xml_text)
        self.assertIn("<editableFieldCatalog", xml_text)
        self.assertIn("<bytePatchMap", xml_text)
        self.assertIsNotNone(document["physics_body_context"])
        body_context = document["physics_body_context"]["body_contexts"][0]
        self.assertEqual("PhysicsAttachment_Capsule", body_context["body_name"])
        shape_match = body_context["shape_matches"][0]
        self.assertEqual(0, shape_match["decoded_shape_index"])
        self.assertEqual("hknpCapsuleShape", shape_match["decoded_shape_type"])
        self.assertEqual(0.25, shape_match["descriptor_radius"])
        self.assertEqual(2.0, shape_match["descriptor_height"])
        self.assertEqual(0.0, shape_match["radius_delta"])
        self.assertEqual(0.0, shape_match["length_delta"])
        self.assertEqual("PhysicsAttachment_Capsule", capsule_shape["body_contexts"][0]["body_name"])
        self.assertEqual("Pelvis", capsule_shape["body_contexts"][0]["socket_name"])
        self.assertIn("<body_contexts imported=\"false\">", xml_text)
        self.assertIn("<physicsBodyContext", xml_text)
        self.assertIn("PhysicsAttachment_Capsule", xml_text)
        editor_collision_row = next(
            row
            for group in document["editor_model"]["groups"]
            if group["key"] == "collision_shapes"
            for row in group["rows"]
            if row["field"] == "capsule_radius"
        )
        self.assertEqual("PhysicsAttachment_Capsule", editor_collision_row["context_label"])
        self.assertEqual("PhysicsAttachment_Capsule: capsule_radius", editor_collision_row["display_label"])
        self.assertEqual("Pelvis", editor_collision_row["socket_name"])
        self.assertIn("body:PhysicsAttachment_Capsule", editor_collision_row["identity_path"])

        edited_document = copy.deepcopy(document)
        edited_document["shapes"][0]["capsule_radius"] = 0.375
        edited_document["shapes"][0]["capsule_endpoints"][1] = [0.0, 2.5, 0.0]
        patch_result = apply_hkx_editable_geometry_document(data, edited_document)
        reparsed = build_hkx_editable_geometry_document(patch_result.data, "object/capsule.hkx")

        self.assertEqual(len(data), len(patch_result.data))
        self.assertIn("shape[0].capsule_radius", patch_result.changed_fields)
        self.assertIn("shape[0].capsule_endpoints", patch_result.changed_fields)
        self.assertEqual(0.375, reparsed["shapes"][0]["capsule_radius"])
        self.assertEqual([0.0, 2.5, 0.0], reparsed["shapes"][0]["capsule_endpoints"][1])

        xml_root = ET.fromstring(xml_text)
        xml_editor_row = xml_root.find("./editorModel/groups/group[@key='collision_shapes']/rows/row[@field='capsule_radius']")
        self.assertIsNotNone(xml_editor_row)
        assert xml_editor_row is not None
        self.assertEqual("PhysicsAttachment_Capsule", xml_editor_row.get("context_label"))
        self.assertEqual("PhysicsAttachment_Capsule: capsule_radius", xml_editor_row.get("display_label"))
        self.assertEqual("Pelvis", xml_editor_row.get("socket_name"))
        xml_root.find("./shapes/shape/capsule_radius").set("value", "0.5")
        xml_root.find("./shapes/shape/capsule_endpoints/point[@index='1']").set("y", "3.0")
        xml_patch_result = apply_hkx_editable_geometry_xml(data, ET.tostring(xml_root, encoding="unicode"))
        xml_reparsed = build_hkx_editable_geometry_document(xml_patch_result.data, "object/capsule.hkx")

        self.assertIn("shape[0].capsule_radius", xml_patch_result.changed_fields)
        self.assertIn("shape[0].capsule_endpoints", xml_patch_result.changed_fields)
        self.assertEqual(0.5, xml_reparsed["shapes"][0]["capsule_radius"])
        self.assertEqual([0.0, 3.0, 0.0], xml_reparsed["shapes"][0]["capsule_endpoints"][1])

    def test_modern_tagfile_summary_decodes_mesh_shape_hint(self) -> None:
        data = self._mesh_shape_hkx_bytes()

        summary = parse_hkx_tagfile_summary(data)
        preview = build_hkx_preview(data, "object/mesh.hkx")
        document = build_hkx_editable_geometry_document(data, "object/mesh.hkx")
        xml_text = build_hkx_editable_geometry_xml(data, "object/mesh.hkx")

        self.assertEqual(1, len(summary.collision_geometry_hints))
        geometry_hint = summary.collision_geometry_hints[0]
        self.assertEqual("hknpMeshShape", geometry_hint.shape_type)
        self.assertEqual(1, geometry_hint.mesh_section_count)
        self.assertEqual(24, geometry_hint.mesh_primitive_count)
        self.assertEqual(12, geometry_hint.mesh_aabb_node_count)
        self.assertEqual(2, geometry_hint.mesh_shape_tag_count)
        self.assertEqual(192, geometry_hint.mesh_data_byte_count)
        self.assertIn(
            "hknpMeshShape; shape-record=2; mesh sections=1; mesh primitives=24; "
            "aabb nodes=12; shape tags=2; mesh data bytes=192",
            preview.preview_text,
        )
        mesh_shape = document["shapes"][0]
        self.assertEqual("hknpMeshShape", mesh_shape["shape_type"])
        self.assertIn("user_editing_guide", document)
        self.assertIn("mesh primitive tuple winding/order", " ".join(document["user_editing_guide"]["safe_first_edits"]))
        self.assertIn("shape-tag ranges", " ".join(document["user_editing_guide"]["avoid_until_decoded"]))
        self.assertEqual(24, mesh_shape["mesh_summary"]["primitives"])
        mesh_details = mesh_shape["mesh_details"]
        self.assertEqual("read_only_schema_recovery", mesh_details["status"])
        self.assertFalse(mesh_details["editability"]["editable"])
        self.assertEqual("blocked_until_mesh_schema_recovered", mesh_details["editability"]["status"])
        self.assertIn("primitive_buffers", mesh_details)
        self.assertIn("aabb_tree_nodes", mesh_details)
        self.assertEqual([2], mesh_details["records"]["mesh_shape_records"])
        self.assertEqual(24, mesh_details["primitive_buffers"][0]["count"])
        self.assertEqual(0x03020100, mesh_details["primitive_buffers"][0]["primitive_words"][0]["packed_u32"])
        self.assertEqual("read_only_bitfield_analysis", mesh_details["primitive_buffers"][0]["analysis"]["status"])
        self.assertEqual("read_only_tuple_index_analysis", mesh_details["primitive_buffers"][0]["analysis"]["topology_candidate_status"])
        self.assertEqual([0, 1, 2, 3], mesh_details["primitive_buffers"][0]["primitive_words"][0]["byte_indices"])
        self.assertIn("candidate_layout", mesh_details["geometry_sections"][0]["rows"][0])
        layout_fields = mesh_details["geometry_sections"][0]["rows"][0]["candidate_layout"]["fields"]
        primitive_offset_field = next(field for field in layout_fields if field["name"] == "primitive_relative_offset")
        self.assertEqual(7, primitive_offset_field["target_record_index"])
        self.assertEqual("resolved", primitive_offset_field["target_resolution"])
        aabb_offset_field = next(field for field in layout_fields if field["name"] == "aabb_tree_relative_offset")
        self.assertEqual(6, aabb_offset_field["target_record_index"])
        self.assertEqual(1, len(mesh_details["primitive_analysis_summary"]))
        collision_group = next(group for group in document["editor_model"]["groups"] if group["key"] == "collision_shapes")
        self.assertTrue(any(row["field"] == "mesh_editability" and row["importable"] is False for row in collision_group["rows"]))
        self.assertTrue(any(row["field"] == "mesh_supported_safe_operation" for row in collision_group["rows"]))
        self.assertTrue(any(row["field"] == "mesh_primitive_analysis" for row in collision_group["rows"]))
        self.assertIn("<mesh_details", xml_text)
        self.assertIn("<userEditingGuide", xml_text)
        self.assertIn("<safeFirstEdits", xml_text)
        self.assertIn("<editability editable=\"false\"", xml_text)
        self.assertIn("<supportedSafeOperation", xml_text)
        self.assertIn("<primitiveAnalysisSummary", xml_text)
        self.assertIn("<primitive_buffers", xml_text)
        self.assertIn("<aabb_tree_nodes", xml_text)
        hard_targets = {
            target["key"]: target
            for target in document["hkclass_metadata_readiness"]["hard_decoder_targets"]["targets"]
        }
        primitive_target = hard_targets["hknp_mesh_primitive_bit_layout"]
        self.assertEqual("open_observed_unproven", primitive_target["status"])
        self.assertEqual("needs_corpus_proof", primitive_target["proof_status"])
        self.assertGreater(primitive_target["observed_record_count"], 0)
        self.assertIn("hknpMeshShape::GeometrySection::Primitive", primitive_target["observed_types"])
        self.assertIn("primitive_tuple_summary", primitive_target["observed_fields"])
        self.assertIn("proof_status=\"needs_corpus_proof\"", xml_text)

    def test_mesh_shape_primitive_winding_edit_patches_only_tuple_bytes(self) -> None:
        data = self._mesh_shape_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/mesh.hkx")
        edited = copy.deepcopy(document)
        primitive = edited["shapes"][0]["mesh_details"]["primitive_buffers"][0]["primitive_words"][0]
        primitive["byte_indices"] = [3, 2, 1, 0]

        result = apply_hkx_editable_geometry_document(data, edited)
        self.assertEqual(["shape[0].mesh_details.primitive_buffers[7].winding"], result.changed_fields)
        differing_offsets = [index for index, (before, after) in enumerate(zip(data, result.data)) if before != after]
        self.assertEqual(list(range(differing_offsets[0], differing_offsets[0] + 4)), differing_offsets)
        reparsed = build_hkx_editable_geometry_document(result.data, "object/mesh.hkx")
        first_tuple = reparsed["shapes"][0]["mesh_details"]["primitive_buffers"][0]["primitive_words"][0]
        self.assertEqual([3, 2, 1, 0], first_tuple["byte_indices"])

    def test_mesh_shape_primitive_edit_rejects_changed_vertex_set(self) -> None:
        data = self._mesh_shape_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/mesh.hkx")
        edited = copy.deepcopy(document)
        primitive = edited["shapes"][0]["mesh_details"]["primitive_buffers"][0]["primitive_words"][0]
        primitive["byte_indices"] = [0, 1, 2, 9]

        with self.assertRaisesRegex(ValueError, "Only winding/order edits"):
            apply_hkx_editable_geometry_document(data, edited)

    def test_mesh_shape_raw_primitive_payload_edit_is_rejected(self) -> None:
        data = self._mesh_shape_hkx_bytes()
        document = build_hkx_editable_geometry_document(data, "object/mesh.hkx")
        edited = copy.deepcopy(document)
        primitive_payload = next(
            payload
            for payload in edited["advanced_record_payloads"]
            if payload["type_name"] == "hknpMeshShape::GeometrySection::Primitive"
        )
        raw = bytearray(bytes.fromhex(primitive_payload["payload_hex"]))
        raw[0] = (raw[0] + 1) & 0xFF
        primitive_payload["payload_hex"] = raw.hex(" ")

        with self.assertRaisesRegex(ValueError, "mesh-shape structural payload"):
            apply_hkx_editable_geometry_document(data, edited)

    def test_mesh_shape_primitive_winding_edit_imports_from_xml(self) -> None:
        data = self._mesh_shape_hkx_bytes()
        xml_text = build_hkx_editable_geometry_xml(data, "object/mesh.hkx")
        root = ET.fromstring(xml_text)
        first_bytes = root.find("./shapes/shape/mesh_details/primitive_buffers/primitive_buffer/primitive_words/primitive/byte_indices")
        self.assertIsNotNone(first_bytes)
        first_bytes.text = "3 2 1 0"

        result = apply_hkx_editable_geometry_xml(data, ET.tostring(root, encoding="unicode"))
        self.assertEqual(["shape[0].mesh_details.primitive_buffers[7].winding"], result.changed_fields)
        reparsed = build_hkx_editable_geometry_document(result.data, "object/mesh.hkx")
        first_tuple = reparsed["shapes"][0]["mesh_details"]["primitive_buffers"][0]["primitive_words"][0]
        self.assertEqual([3, 2, 1, 0], first_tuple["byte_indices"])

    def test_modern_tagfile_summary_decodes_mass_property_payload_observations(self) -> None:
        type_names = b"hknpShapeMassProperties\0\xff"
        record = (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
        data_payload = bytearray(64)
        for index, value in enumerate(
            (
                1.0,
                0.0,
                0.0,
                2.0,
                0.0,
                1.0,
                0.0,
                3.0,
                0.0,
                0.0,
                1.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
            )
        ):
            struct.pack_into("<f", data_payload, index * 4, value)
        item_payload = b"\0" * 12 + record
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(1), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        summary = parse_hkx_tagfile_summary(data)
        preview = build_hkx_preview(data, "object/mass.hkx")

        payload_summary = summary.item_payload_summaries[0]
        self.assertEqual("hknpShapeMassProperties", payload_summary.type_name)
        self.assertTrue(any("mass-property float rows" in line for line in payload_summary.lines))
        self.assertIn("mass-property float rows", preview.preview_text)
        document = build_hkx_editable_geometry_document(data, "object/mass.hkx")
        mass_record = next(record for record in document["objects"] if record["type_name"] == "hknpShapeMassProperties")
        layout_fields = mass_record["layout"]["fields"]
        self.assertTrue(any(field["name"] == "mass_properties_row3_center_mass_or_scale" for field in layout_fields))
        self.assertTrue(any(field["name"] == "mass_property_float4_rows" for field in layout_fields))

    def test_hkx_converter_decodes_compressed_mass_and_packed_vector_rows_read_only(self) -> None:
        type_names = b"hkCompressedMassProperties\0hkPackedVector3\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (64).to_bytes(4, "little") + (3).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(80)
        for index, value in enumerate((0x11223344, 0x55667788, 0x00010002, 0x00030004)):
            struct.pack_into("<I", data_payload, index * 4, value)
        data_payload[64:76] = bytes((0, 64, 128, 255, 1, 2, 3, 4, 250, 251, 252, 253))
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(2), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        preview = build_hkx_preview(data, "object/compressed_mass.hkx")
        document = build_hkx_editable_geometry_document(data, "object/compressed_mass.hkx")

        self.assertIn("compressed mass-property words", preview.preview_text)
        self.assertIn("packed vector3 rows", preview.preview_text)
        compressed = next(record for record in document["objects"] if record["type_name"] == "hkCompressedMassProperties")
        packed = next(record for record in document["objects"] if record["type_name"] == "hkPackedVector3")
        compressed_fields = compressed["layout"]["fields"]
        packed_fields = packed["layout"]["fields"]
        self.assertEqual("partially_decoded", compressed["status"])
        self.assertEqual("partially_decoded", packed["status"])
        self.assertEqual("compressed_mass_properties_sample", compressed_fields[0]["name"])
        self.assertFalse(compressed_fields[0]["editable"])
        self.assertEqual("packed_vector3_rows", packed_fields[0]["name"])
        self.assertFalse(packed_fields[0]["editable"])
        rows = packed_fields[0]["value"]["rows"]
        self.assertEqual([0, 64, 128, 255], rows[0]["bytes"])
        self.assertEqual([0, 64, -128, -1], rows[0]["signed_bytes"])
        target_coverage = {
            row["type_name"]: row
            for row in document["converter_report"]["schema_target_coverage"]
        }
        self.assertEqual("decoded", target_coverage["hkCompressedMassProperties"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hkPackedVector3"]["coverage_status"])

    def test_hkx_converter_decodes_scalar_arrays_and_enum_records_read_only(self) -> None:
        type_names = (
            b"unsigned int\0unsigned short\0unsigned long long\0"
            b"hknpShapeType::Enum\0hknpShape::FlagsEnum\0\xff"
        )
        records = b"".join(
            (
                (0x20000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (3).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (4).to_bytes(4, "little"),
                (0x20000003).to_bytes(4, "little") + (32).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000004).to_bytes(4, "little") + (64).to_bytes(4, "little") + (3).to_bytes(4, "little"),
                (0x20000005).to_bytes(4, "little") + (68).to_bytes(4, "little") + (2).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(80)
        for index, value in enumerate((7, 8, 0xABCDEF01)):
            struct.pack_into("<I", data_payload, index * 4, value)
        for index, value in enumerate((1, 2, 65535, 1024)):
            struct.pack_into("<H", data_payload, 16 + index * 2, value)
        for index, value in enumerate((0x1122334455667788, 0x0102030405060708)):
            struct.pack_into("<Q", data_payload, 32 + index * 8, value)
        data_payload[64:67] = bytes((3, 4, 7))
        struct.pack_into("<II", data_payload, 68, 0x10, 0x20)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(5), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        preview = build_hkx_preview(data, "object/scalars.hkx")
        document = build_hkx_editable_geometry_document(data, "object/scalars.hkx")

        self.assertIn("uint32[] scalar values", preview.preview_text)
        self.assertIn("enum/flags values", preview.preview_text)
        by_type = {record["type_name"]: record for record in document["objects"]}
        self.assertEqual("uint32_values", by_type["unsigned int"]["layout"]["fields"][0]["name"])
        self.assertEqual([7, 8, 0xABCDEF01], by_type["unsigned int"]["layout"]["fields"][0]["value"]["values"])
        self.assertFalse(by_type["unsigned short"]["layout"]["fields"][0]["editable"])
        self.assertEqual("enum_or_flags_values", by_type["hknpShapeType::Enum"]["layout"]["fields"][0]["name"])
        self.assertEqual([3, 4, 7], by_type["hknpShapeType::Enum"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual("enum_or_flags_values", by_type["hknpShape::FlagsEnum"]["layout"]["fields"][0]["name"])
        target_coverage = {
            row["type_name"]: row
            for row in document["converter_report"]["schema_target_coverage"]
        }
        self.assertEqual("decoded", target_coverage["unsigned int"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hknpShapeType::Enum"]["coverage_status"])

    def test_hkx_converter_uses_corpus_alias_types_as_read_only_targets(self) -> None:
        type_names = (
            b"hkUint16\0hkUint32\0hkInt32\0hkBool\0float\0hkMatrix4\0"
            b"hknpCylinderShape\0hknpWheelConstraintData\0hkxVertexBuffer\0\xff"
        )
        records = b"".join(
            (
                (0x20000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (3).to_bytes(4, "little"),
                (0x20000002).to_bytes(4, "little") + (8).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000003).to_bytes(4, "little") + (16).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000004).to_bytes(4, "little") + (24).to_bytes(4, "little") + (3).to_bytes(4, "little"),
                (0x20000005).to_bytes(4, "little") + (28).to_bytes(4, "little") + (2).to_bytes(4, "little"),
                (0x20000006).to_bytes(4, "little") + (48).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000007).to_bytes(4, "little") + (128).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000008).to_bytes(4, "little") + (288).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000009).to_bytes(4, "little") + (720).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(800)
        for index, value in enumerate((1, 2, 65535)):
            struct.pack_into("<H", data_payload, index * 2, value)
        for index, value in enumerate((0x11223344, 0xAABBCCDD)):
            struct.pack_into("<I", data_payload, 8 + index * 4, value)
        for index, value in enumerate((-7, 42)):
            struct.pack_into("<i", data_payload, 16 + index * 4, value)
        data_payload[24:27] = bytes((1, 0, 1))
        struct.pack_into("<ff", data_payload, 28, 1.25, -2.5)
        for index in range(16):
            struct.pack_into("<f", data_payload, 48 + index * 4, float(index + 1))
        struct.pack_into("<ff", data_payload, 128 + 0x68, 0.01, 0.25)
        struct.pack_into("<ffff", data_payload, 128 + 0x80, 0.0, 0.0, 0.5, 1.0)
        struct.pack_into("<ffff", data_payload, 128 + 0x90, 0.0, 0.0, -0.5, 1.0)
        struct.pack_into("<f", data_payload, 288 + 0x18, 100.0)
        struct.pack_into("<ffff", data_payload, 288 + 0x40, 1.0, 0.0, 0.0, 0.0)
        struct.pack_into("<IIII", data_payload, 720, 1, 2, 3, 4)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(9), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "object/corpus_aliases.hkx")

        by_type = {record["type_name"]: record for record in document["objects"]}
        self.assertEqual([1, 2, 65535], by_type["hkUint16"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual([0x11223344, 0xAABBCCDD], by_type["hkUint32"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual([-7, 42], by_type["hkInt32"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual([True, False, True], by_type["hkBool"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual([1.25, -2.5], by_type["float"]["layout"]["fields"][0]["value"]["values"])
        self.assertEqual("matrix4[0]", by_type["hkMatrix4"]["layout"]["fields"][0]["name"])
        self.assertEqual("cylinder_shape_candidates", by_type["hknpCylinderShape"]["layout"]["fields"][0]["name"])
        self.assertEqual("hknpWheelConstraintData[0]", by_type["hknpWheelConstraintData"]["layout"]["fields"][0]["name"])
        self.assertEqual("hkx_scene_payload_sample", by_type["hkxVertexBuffer"]["layout"]["fields"][0]["name"])
        target_coverage = {
            row["type_name"]: row
            for row in document["converter_report"]["schema_target_coverage"]
        }
        for type_name in (
            "hkUint16",
            "hkUint32",
            "hkInt32",
            "hkBool",
            "float",
            "hkMatrix4",
            "hknpCylinderShape",
            "hknpWheelConstraintData",
            "hkxVertexBuffer",
        ):
            self.assertEqual("decoded", target_coverage[type_name]["coverage_status"])
        unknown_types = {
            row["type_name"]
            for row in document["converter_report"]["failed_or_unknown_schema_areas"]
        }
        self.assertNotIn("hknpWheelConstraintData", unknown_types)
        self.assertNotIn("hkxVertexBuffer", unknown_types)

    def test_hkx_decode_gap_summary_and_priority_partials_export_to_xml(self) -> None:
        type_names = b"hknpTriangleShape\0hknpBallAndSocketConstraintData\0\xff"
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (160).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(320)
        for index, value in enumerate((0.0, 0.5, 1.0, 1.0, 1.5, 0.0, 0.0, 1.0)):
            struct.pack_into("<f", data_payload, index * 4, value)
        for offset, low, high in ((0x20, 64, 1), (0x28, 72, 3), (0x30, 12, 34)):
            struct.pack_into("<II", data_payload, offset, low, high)
        for index, value in enumerate((1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 50.0, 0.25)):
            struct.pack_into("<f", data_payload, 160 + 0x40 + index * 4, value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(2), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "object/partial_priority.hkx")
        xml_root = ET.fromstring(build_hkx_editable_geometry_xml(data, "object/partial_priority.hkx"))

        by_type = {record["type_name"]: record for record in document["objects"]}
        triangle_fields = by_type["hknpTriangleShape"]["layout"]["fields"]
        self.assertEqual("triangle_shape_candidate_layout", triangle_fields[0]["name"])
        self.assertFalse(triangle_fields[0]["editable"])
        self.assertEqual("read_only", triangle_fields[0]["safe_edit_policy"])
        self.assertEqual("typed_layout", triangle_fields[0]["decode_source"])
        ball_fields = by_type["hknpBallAndSocketConstraintData"]["layout"]["fields"]
        self.assertEqual("hknpBallAndSocketConstraintData[0]", ball_fields[0]["name"])
        self.assertFalse(ball_fields[0]["editable"])

        gap_summary = document["decode_gap_summary"]
        self.assertEqual("has_decode_gaps", gap_summary["status"])
        gaps_by_type = {gap["type_name"]: gap for gap in gap_summary["gaps"]}
        self.assertIn("hknpTriangleShape", gaps_by_type)
        self.assertIn("shape internals", gaps_by_type["hknpTriangleShape"]["friendly_status_label"])
        self.assertEqual("read_only", gaps_by_type["hknpTriangleShape"]["safe_edit_policy"])
        target_coverage = {
            row["type_name"]: row
            for row in document["converter_report"]["schema_target_coverage"]
        }
        self.assertEqual("decoded", target_coverage["hknpTriangleShape"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hknpBallAndSocketConstraintData"]["coverage_status"])

        xml_gap = xml_root.find("./decodeGapSummary/gaps/gap[@type_name='hknpTriangleShape']")
        self.assertIsNotNone(xml_gap)
        assert xml_gap is not None
        self.assertIn("shape internals", xml_gap.get("friendly_status_label") or "")
        self.assertIsNotNone(xml_gap.find("./missingRequirements/requirement"))

    def test_hkx_converter_decodes_root_scene_reference_payloads_read_only(self) -> None:
        type_names = (
            b"hkRefVariant\0hkStringPtr\0hkMemoryResourceContainer\0"
            b"hknpPhysicsSystemData\0hknpConstraintData\0"
            b"hknpRefDragProperties\0hknpRefMassDistribution\0\xff"
        )
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (16).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (32).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000004).to_bytes(4, "little") + (64).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000005).to_bytes(4, "little") + (112).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000006).to_bytes(4, "little") + (160).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000007).to_bytes(4, "little") + (208).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(256)
        struct.pack_into("<QII", data_payload, 0, 64, 4, 8)
        struct.pack_into("<QII", data_payload, 16, 80, 12, 16)
        for base, pair_a, pair_b, float_value in (
            (32, 64, 2, 0.25),
            (64, 112, 1, 1.5),
            (112, 160, 6, 2.5),
            (160, 208, 7, 0.75),
            (208, 32, 9, 3.25),
        ):
            struct.pack_into("<II", data_payload, base, pair_a, pair_b)
            struct.pack_into("<f", data_payload, base + 16, float_value)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(7), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "character/bin__/havokphysics/test.hkx")
        by_type = {record["type_name"]: record for record in document["objects"]}

        self.assertEqual("referenced_value", by_type["hkRefVariant"]["layout"]["fields"][0]["name"])
        self.assertEqual("reference_metadata_pair", by_type["hkStringPtr"]["layout"]["fields"][1]["name"])
        self.assertTrue(
            any(
                field["name"] == "materials_array_or_reference_pair"
                for field in by_type["hknpPhysicsSystemData"]["layout"]["fields"]
            )
        )
        self.assertIn("physics_system_named_pairs", by_type["hknpPhysicsSystemData"]["decoded_fields"])
        self.assertTrue(
            any(
                field["name"] == "finite_float_candidates"
                for field in by_type["hknpRefDragProperties"]["layout"]["fields"]
            )
        )
        self.assertFalse(by_type["hknpConstraintData"]["layout"]["fields"][0]["editable"])
        target_coverage = {
            row["type_name"]: row
            for row in document["converter_report"]["schema_target_coverage"]
        }
        self.assertEqual("decoded", target_coverage["hkRefVariant"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hknpPhysicsSystemData"]["coverage_status"])
        self.assertEqual("decoded", target_coverage["hknpRefMassDistribution"]["coverage_status"])

    def test_hkx_converter_decodes_body_and_constraint_reference_fields_read_only(self) -> None:
        type_names = (
            b"hknpPhysicsSystemData\0hknpPhysicsSystemData::ExtendedBodyCinfo\0"
            b"hknpConstraintCinfo\0\xff"
        )
        records = b"".join(
            (
                (0x10000001).to_bytes(4, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000002).to_bytes(4, "little") + (64).to_bytes(4, "little") + (1).to_bytes(4, "little"),
                (0x10000003).to_bytes(4, "little") + (192).to_bytes(4, "little") + (1).to_bytes(4, "little"),
            )
        )
        data_payload = bytearray(256)
        for offset, low, high in (
            (0x00, 320, 2),
            (0x08, 352, 3),
            (0x10, 64, 1),
            (0x18, 192, 1),
            (0x20, 400, 4),
        ):
            struct.pack_into("<II", data_payload, offset, low, high)
        for offset, low, high in (
            (64 + 0x08, 400, 12),
            (64 + 0x10, 352, 3),
            (64 + 0x18, 27, 5),
            (64 + 0x20, 99, 2),
            (64 + 0x60, 123, 456),
        ):
            struct.pack_into("<II", data_payload, offset, low, high)
        for index, value in enumerate((1.0, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0, 3.0)):
            struct.pack_into("<f", data_payload, 64 + 0x30 + index * 4, value)
        for offset, low, high in (
            (192 + 0x00, 10, 0),
            (192 + 0x08, 11, 0),
            (192 + 0x10, 160, 1),
            (192 + 0x18, 7, 9),
        ):
            struct.pack_into("<II", data_payload, offset, low, high)
        item_payload = b"\0" * 12 + records
        body = b"TAG0"
        body += _tag_item(b"SDKV", b"20240200")
        body += _tag_item(b"DATA", bytes(data_payload))
        body += _tag_item(b"TST1", type_names)
        body += _tag_item(b"TNA1", _tna1_payload(3), flags=0x40000000)
        body += _tag_item(b"TPAD", b"", flags=0)
        body += _tag_item(b"INDX", b"", flags=0x40000000)
        body += (8 + len(item_payload)).to_bytes(4, "big") + b"ITEM" + item_payload
        data = (len(body) + 4).to_bytes(4, "big") + body

        document = build_hkx_editable_geometry_document(data, "character/bin__/havokphysics/body.hkx")
        by_type = {record["type_name"]: record for record in document["objects"]}

        system_fields = by_type["hknpPhysicsSystemData"]["layout"]["fields"]
        body_fields = by_type["hknpPhysicsSystemData::ExtendedBodyCinfo"]["layout"]["fields"]
        constraint_fields = by_type["hknpConstraintCinfo"]["layout"]["fields"]
        self.assertTrue(any(field["name"] == "body_cinfo_array_or_reference_pair" for field in system_fields))
        self.assertTrue(any(field["name"] == "shape_reference_or_key_pair" for field in body_fields))
        self.assertTrue(any(field["name"] == "motion_properties_reference_pair" for field in body_fields))
        self.assertTrue(any(field["name"] == "body_transform_or_orientation_row0_x" for field in body_fields))
        self.assertTrue(any(field["name"] == "body_a_reference_or_index_pair" for field in constraint_fields))
        self.assertTrue(any(field["name"] == "constraint_data_reference_pair" for field in constraint_fields))
        self.assertFalse(next(field for field in constraint_fields if field["name"] == "body_a_reference_or_index_pair")["editable"])

        system_object = next(obj for obj in document["havok_xml_view"]["hkobjects"] if obj["class"] == "hknpPhysicsSystemData")
        system_params = {field["hkparam_name"]: field for field in system_object["fields"]}
        self.assertEqual("#record1", system_params["bodyCinfos"]["hkparam_text"])
        self.assertEqual(1, system_params["bodyCinfos"]["numelements"])
        self.assertEqual("owner_array_field", system_params["bodyCinfos"]["reference_kind"])
        self.assertEqual("hknpPhysicsSystemData::ExtendedBodyCinfo", system_params["bodyCinfos"]["reference_target_type"])
        self.assertEqual("#record2", system_params["constraintCinfos"]["hkparam_text"])
        self.assertEqual(1, system_params["constraintCinfos"]["numelements"])

        xml_root = ET.fromstring(build_hkx_havok_xml_view_xml(data, "character/bin__/havokphysics/body.hkx"))
        self.assertIsNotNone(
            xml_root.find(
                "./hksection/hkobject[@class='hknpPhysicsSystemData']/hkparam[@name='bodyCinfos'][@numelements='1']"
            )
        )


if __name__ == "__main__":
    unittest.main()
