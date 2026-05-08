import json
import os
from pathlib import Path
import unittest
from unittest import mock

from cdmw.core import hkx_native
from cdmw.core.archive_modding import (
    build_hkx_editable_geometry_document,
    build_hkx_editable_geometry_xml,
    parse_hkx_tagfile_summary,
)


def json_bytes(value: object) -> bytes:
    return json.dumps(value).encode("utf-8")


class HkxNativeBackendTests(unittest.TestCase):
    def test_default_cd_hkx_binary_path_points_to_native_release_binary(self) -> None:
        path = hkx_native.default_cd_hkx_binary_path()

        self.assertIn("native", path.parts)
        self.assertIn("cd_hkx", path.parts)
        self.assertIn("release", path.parts)
        self.assertTrue(path.name.startswith("cd-hkx"))

    def test_native_summary_returns_none_when_binary_is_unavailable(self) -> None:
        with mock.patch.dict(os.environ, {"CDMW_CD_HKX_BIN": str(Path("Z:/missing/cd-hkx.exe"))}):
            with mock.patch("cdmw.core.hkx_native.default_cd_hkx_binary_path", return_value=Path("Z:/missing/default.exe")):
                self.assertIsNone(hkx_native.find_cd_hkx_binary())
                self.assertIsNone(hkx_native.parse_hkx_summary_with_rust(b"not hkx"))
                self.assertIsNone(hkx_native.roundtrip_hkx_noedit_with_rust(b"not hkx"))
                self.assertIsNone(
                    hkx_native.patch_hkx_fixed_float_with_rust(
                        b"not hkx",
                        record_index=0,
                        item_index=0,
                        offset=0x28,
                        value=0.6,
                    )
                )
                self.assertIsNone(hkx_native.scan_hkx_corpus_with_rust((Path("C:/missing"),)))

    def test_native_fixed_float_patch_wrapper_returns_patched_bytes(self) -> None:
        original = b"abcd"
        patched = b"wxyz"

        def fake_run(args, **kwargs):
            output_path = Path(args[3])
            output_path.write_bytes(patched)
            return mock.Mock(returncode=0, stdout=b"{}", stderr=b"")

        with mock.patch("cdmw.core.hkx_native.find_cd_hkx_binary", return_value=Path("C:/tools/cd-hkx.exe")):
            with mock.patch("subprocess.run", side_effect=fake_run) as run_mock:
                result = hkx_native.patch_hkx_fixed_float_with_rust(
                    original,
                    record_index=2,
                    item_index=1,
                    offset=0x28,
                    value=0.6,
                )

        self.assertEqual(patched, result)
        args = run_mock.call_args.args[0]
        self.assertIn("patch-fixed-f32", args)
        self.assertEqual("2", args[4])
        self.assertEqual("1", args[5])
        self.assertEqual("0x28", args[6])

    def test_native_noedit_roundtrip_wrapper_returns_identical_bytes_and_report(self) -> None:
        original = b"hkx bytes"
        report = {
            "format": "cd_hkx_no_edit_binary_writer_v1",
            "status": "byte_identical",
            "native_writer_status": "available",
            "no_edit_roundtrip_mode": "native_read_model_write_lossless_bytes",
            "read_model_write_pipeline": "raw_preserving_model",
            "available": True,
            "native_read_model_write_available": True,
            "byte_identical_no_edit_rebuild_supported": True,
        }

        def fake_run(args, **kwargs):
            output_path = Path(args[3])
            output_path.write_bytes(original)
            return mock.Mock(returncode=0, stdout=json_bytes(report), stderr=b"")

        with mock.patch("cdmw.core.hkx_native.find_cd_hkx_binary", return_value=Path("C:/tools/cd-hkx.exe")):
            with mock.patch("subprocess.run", side_effect=fake_run) as run_mock:
                result = hkx_native.roundtrip_hkx_noedit_with_rust(original)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(original, result["data"])
        self.assertEqual("byte_identical", result["report"]["status"])
        self.assertEqual("native_rust_cd_hkx", result["report"]["native_backend"])
        self.assertEqual("roundtrip-noedit", result["report"]["command"])
        args = run_mock.call_args.args[0]
        self.assertIn("roundtrip-noedit", args)

    def test_native_corpus_scan_wrapper_returns_report(self) -> None:
        payload = {
            "format": "cd_hkx_corpus_stats_v1",
            "file_count": 3,
            "ok_count": 3,
            "total_item_records": 12,
            "total_physics_tuning_slots": 2,
        }

        def fake_run(args, **kwargs):
            return mock.Mock(returncode=0, stdout=json_bytes(payload), stderr=b"")

        with mock.patch("cdmw.core.hkx_native.find_cd_hkx_binary", return_value=Path("C:/tools/cd-hkx.exe")):
            with mock.patch("subprocess.run", side_effect=fake_run) as run_mock:
                result = hkx_native.scan_hkx_corpus_with_rust((Path("C:/hkx"),), max_files=250)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("native_rust_cd_hkx", result["native_backend"])
        self.assertEqual("corpus-stats-json", result["command"])
        self.assertEqual(3, result["file_count"])
        args = run_mock.call_args.args[0]
        self.assertEqual("corpus-stats-json", args[1])
        self.assertEqual("250", args[3])

    def test_python_summary_can_use_native_tag_table_when_available(self) -> None:
        data = (32).to_bytes(4, "big") + b"TAG0" + b"\0" * 24
        native_summary = {
            "tag_items": [{"name": "TAG0", "offset": 4}],
            "string_table_names": ["hknpCompoundShape"],
            "type_infos": [{"index": 1, "name": "hknpCompoundShape", "template_parameters": []}],
            "declared_type_name_count": 2,
            "type_names": ["hknpCompoundShape"],
            "item_records": [
                {
                    "index": 0,
                    "raw_type_flags": 0x10000001,
                    "type_index": 1,
                    "flags": 0x10000000,
                    "data_offset": 0,
                    "absolute_data_offset": 32,
                    "count": 1,
                    "type_name": "hknpCompoundShape",
                }
            ],
            "object_records": [
                {
                    "record_index": 0,
                    "type_name": "hknpCompoundShape",
                    "status": "partially_decoded",
                    "byte_length": 32,
                    "fields": [],
                    "references": [],
                }
            ],
            "physics_tuning_groups": [
                {
                    "category": "motor_force_response",
                    "record_index": 0,
                    "slots": [{"item_index": 0, "offset": 0x28, "name": "stiffness_or_strength", "value": 0.8}],
                }
            ],
            "warnings": ["native test warning"],
        }

        with mock.patch("cdmw.core.hkx_native.parse_hkx_summary_with_rust", return_value=native_summary):
            summary = parse_hkx_tagfile_summary(data)

        self.assertEqual(1, len(summary.type_infos))
        self.assertEqual("hknpCompoundShape", summary.item_records[0].type_name)
        self.assertEqual(1, len(summary.native_object_records))
        self.assertEqual(1, len(summary.native_physics_tuning_groups))
        self.assertIn("native test warning", summary.warnings)

    def test_converter_document_exposes_native_backend_report(self) -> None:
        data = (32).to_bytes(4, "big") + b"TAG0" + b"\0" * 24
        native_summary = {
            "tag_items": [{"name": "TAG0", "offset": 4}],
            "string_table_names": ["hknpPositionConstraintMotor"],
            "type_infos": [{"index": 1, "name": "hknpPositionConstraintMotor", "template_parameters": []}],
            "declared_type_name_count": 2,
            "type_names": ["hknpPositionConstraintMotor"],
            "item_records": [
                {
                    "index": 0,
                    "raw_type_flags": 0x10000001,
                    "type_index": 1,
                    "flags": 0x10000000,
                    "data_offset": 0,
                    "absolute_data_offset": 32,
                    "count": 1,
                    "type_name": "hknpPositionConstraintMotor",
                }
            ],
            "object_records": [{"record_index": 0, "type_name": "hknpPositionConstraintMotor", "status": "editable"}],
            "tagfile_reference_fixups": {
                "format": "cd_hkx_tagfile_reference_fixups_v1",
                "status": "experimental_observation",
                "section_count": 1,
                "match_kind_counts": {"data_offset": 2},
                "reference_category_counts": {"object_reference": 2},
                "sections": [{"name": "INDX", "word_count": 2}],
            },
            "fixup_semantics_report": {
                "format": "cd_hkx_fixup_semantics_report_v1",
                "status": "experimental_observation",
                "ptch_table_count": 1,
                "ptch_patch_site_count": 1,
                "ptch_object_patch_site_count": 1,
                "ptch_null_patch_site_count": 0,
                "ptch_unresolved_patch_site_count": 0,
                "ptch_tuple_shape_counts": {"1,1,0,2": 1},
                "ptch_payload_match_kind_counts": {"ptch_object_patch_offset": 1},
                "ptch_remaining_case_priorities": [],
            },
            "fixup_semantics_v2": {
                "format": "cd_hkx_fixup_semantics_v2",
                "status": "ptch_patch_sites_normalized_read_only",
                "patch_site_count": 1,
                "resolved_patch_site_count": 1,
                "unresolved_patch_site_count": 0,
                "semantic_bucket_counts": {
                    "object_ref": 1,
                    "null_ref": 0,
                    "data_ref": 0,
                    "string_ref": 0,
                    "type_class_ref": 0,
                    "section_local_ref": 0,
                    "packed_or_varuint": 0,
                    "unresolved": 0,
                },
                "semantic_bucket_taxonomy": [
                    {
                        "bucket": "object_ref",
                        "meaning": "Fixup points to another ITEM/object record.",
                        "edit_policy": "read_only_reference",
                    },
                    {
                        "bucket": "data_ref",
                        "meaning": "Fixup likely points to data/array storage.",
                        "edit_policy": "corpus_proof_required",
                    },
                ],
                "corpus_evidence_counters": {
                    "patch_site_count": 1,
                    "resolved_patch_site_count": 1,
                    "unresolved_patch_site_count": 0,
                    "data_ref_count": 0,
                },
                "patch_sites": [
                    {
                        "index": 0,
                        "section": "PTCH",
                        "tuple_shape": "1,1,0,2",
                        "owner_record_index": 0,
                        "owner_local_offset": 0x28,
                        "patched_slot_value": 1,
                        "target_record_index": 1,
                        "target_status": "object",
                        "semantic_bucket": "object_ref",
                        "reference_category": "object_reference",
                        "confidence": "strong inference",
                    }
                ],
            },
            "native_model_graph": {
                "format": "cd_hkx_native_model_graph_v1",
                "status": "native_model_graph_partial",
                "node_count": 2,
                "edge_count": 1,
                "fixup_backed_reference_edge_count": 1,
                "inferred_reference_edge_count": 0,
                "owner_array_count": 0,
                "root": {
                    "record_index": 0,
                    "type_name": "hknpPositionConstraintMotor",
                    "method": "native_first_record_fallback",
                    "confidence": "experimental",
                    "named_variant_count": 0,
                    "named_variants": [],
                },
                "graph_order": [0, 1],
                "nodes": [],
                "edges": [],
                "owner_arrays": [],
            },
            "semantic_model_v1": {
                "format": "cd_hkx_semantic_model_v1",
                "status": "read_only_semantic_model_from_native_records",
                "object_count": 1,
                "field_count": 1,
                "raw_fallback_count": 0,
                "root_record_index": 0,
                "root_type_name": "hknpPositionConstraintMotor",
                "source_priority": ["real_hkclass_metadata_v2", "typed_layout_decoder", "raw_preserved_payload"],
                "field_kind_taxonomy": ["scalar", "vector", "array", "ref", "string", "enum", "struct", "raw_span"],
                "objects": [
                    {
                        "record_index": 0,
                        "type_name": "hknpPositionConstraintMotor",
                        "status": "editable",
                        "class_metadata_source": "typed_layout_decoder",
                        "semantic_source": "typed_layout_decoder",
                        "field_count": 1,
                        "reference_count": 0,
                        "raw_span_count": 0,
                        "fields": [
                            {
                                "name": "stiffness_or_strength",
                                "kind": "scalar",
                                "offset": 0x28,
                                "offset_hex": "0x28",
                                "size": 4,
                                "byte_range_start": 0x68,
                                "byte_range_end": 0x6C,
                                "data_type": "f32",
                                "confidence": "strong inference",
                                "editable_candidate": True,
                                "write_gate_status": "candidate_only_until_edit_gate",
                            }
                        ],
                    }
                ],
            },
            "semantic_writer_gate_v1": {
                "format": "cd_hkx_semantic_writer_gate_v1",
                "status": "semantic_writer_disabled_until_byte_identity_proof",
                "enabled": False,
                "semantic_rebuild_supported": False,
                "havok_xml_import_unblocked": False,
                "fixed_size_patch_importable": True,
                "patchable_slot_count": 1,
                "writer_modes": [
                    {
                        "mode": "raw_preserving_no_edit",
                        "status": "available",
                        "enabled": True,
                        "reason": "lossless byte segment writer",
                    },
                    {
                        "mode": "semantic_no_edit",
                        "status": "disabled_pending_representative_byte_identity",
                        "enabled": False,
                        "reason": "requires representative role coverage",
                    },
                ],
                "required_role_coverage": [
                    {
                        "role": role,
                        "no_edit_status": "required",
                        "semantic_no_edit_status": "required_not_verified_by_semantic_writer",
                        "fixed_edit_status": "required",
                        "byte_identity_status": "required_not_verified_by_semantic_writer",
                        "sample_required": True,
                        "fixed_size_edits_allowed": False,
                    }
                    for role in ("object", "meshphysics", "character_physics", "ragdoll_body", "mesh_heavy", "animation")
                ],
                "representative_role_gates": [
                    {
                        "role": role,
                        "required": True,
                        "status": "representative_corpus_required",
                        "no_edit_byte_identity": "not_proven_by_semantic_writer",
                        "mismatch_offset": None,
                        "fixed_size_edits_allowed": False,
                        "unsupported_field_kinds": ["array", "ref", "string"],
                        "unsupported_ref_kinds": ["data_ref", "string_ref", "type_class_ref"],
                    }
                    for role in ("object", "meshphysics", "character_physics", "ragdoll_body", "mesh_heavy", "animation")
                ],
                "unsupported_field_kinds": ["array", "ref", "string", "topology"],
                "unsupported_ref_kinds": ["data_ref", "string_ref", "type_class_ref"],
                "requirements": ["semantic no-edit byte identity across representative roles"],
                "blocked_edit_classes": ["array", "ref", "string", "topology"],
            },
            "edit_candidate_map_v1": {
                "format": "cd_hkx_edit_candidate_map_v1",
                "status": "fixed_size_numeric_candidates_only",
                "new_editable_fields_enabled": False,
                "candidate_count": 1,
                "write_enabled_candidate_count": 1,
                "candidates": [
                    {
                        "class": "hknpPositionConstraintMotor",
                        "member": "stiffness_or_strength",
                        "record_index": 0,
                        "item_index": 0,
                        "local_offset": 0x28,
                        "offset_hex": "0x28",
                        "byte_size": 4,
                        "supported_write_type": "f32",
                        "risk_label": "medium",
                        "confidence": "strong inference",
                        "import_path": "existing_fixed_size_patch",
                        "write_enabled": True,
                    }
                ],
            },
            "hkx_edit_gate_v1": {
                "format": "cd_hkx_edit_gate_v1",
                "status": "fixed_size_patch_gate",
                "read_only": True,
                "new_editable_fields_enabled": False,
                "write_enabled_candidate_count": 1,
                "candidate_only_count": 0,
                "blocked_policy": "arrays, strings, references, topology, counts, compressed tables, and class metadata remain blocked until semantic rebuild proof",
                "required_role_coverage": [
                    {
                        "role": "object",
                        "no_edit_status": "required",
                        "fixed_edit_status": "required",
                        "status": "representative_corpus_required",
                    }
                ],
                "categories": [
                    {
                        "category": "motor_force_response",
                        "owner_class": "hknpPositionConstraintMotor",
                        "status": "enabled",
                        "write_enabled_count": 1,
                        "candidate_only_count": 0,
                        "fixed_edit_test_status": "existing_route",
                        "gate_reason": "existing fixed-size patch route",
                    }
                ],
                "blocked_kinds": ["array", "string", "reference", "topology", "count"],
            },
            "class_decoder_evidence_v2": {
                "format": "cd_hkx_class_decoder_evidence_v2",
                "status": "class_specific_decode_evidence_available",
                "class_status_count": 1,
                "hard_target_count": 0,
                "observed_hard_target_count": 0,
                "class_statuses": [
                    {
                        "class": "hknpPositionConstraintMotor",
                        "type_name": "hknpPositionConstraintMotor",
                        "record_count": 1,
                        "byte_count": 32,
                        "decoded_field_count": 2,
                        "reference_count": 1,
                        "editable_candidate_count": 1,
                        "status": "editable",
                        "friendly_status": "Fixed-size patch slots recovered",
                    }
                ],
            },
            "decoder_evidence_v2": {
                "format": "cd_hkx_decoder_evidence_v2",
                "status": "read_only_native_evidence",
                "read_only": True,
                "class_status_count": 1,
                "priority_class_count": 1,
                "total_partial_byte_count": 32,
                "unresolved_or_packed_case_count": 0,
                "owner_array_count": 0,
                "reference_semantic_counts": {"object": 2, "null": 1},
                "link_evidence_counts": {"fixup_backed": 1},
                "class_statuses": [
                    {
                        "type_name": "hknpPositionConstraintMotor",
                        "record_count": 1,
                        "byte_count": 32,
                        "decoded_field_count": 2,
                        "reference_count": 1,
                        "editable_field_count": 1,
                        "status": "editable",
                        "friendly_status": "Fixed-size patch slots recovered; official hkClass names still partial",
                        "missing_requirements": ["real hkClass member metadata"],
                        "link_evidence": ["fixup_backed"],
                        "corpus_priority_score": 512,
                        "read_only": True,
                    }
                ],
                "fixup_backed_fields": [
                    {
                        "class_name": "hknpPositionConstraintMotor",
                        "field_name": "motor",
                        "reference_category": "object_reference",
                        "count": 1,
                        "confidence": "strong inference",
                    }
                ],
            },
            "physics_tuning_groups": [
                {
                    "category": "motor_force_response",
                    "record_index": 0,
                    "slots": [{"item_index": 0, "offset": 0x28, "name": "stiffness_or_strength", "value": 0.8}],
                }
            ],
            "no_edit_binary_writer": {
                "format": "cd_hkx_no_edit_binary_writer_v1",
                "status": "byte_identical",
                "native_writer_status": "available",
                "no_edit_roundtrip_mode": "native_read_model_write_lossless_bytes",
                "read_model_write_pipeline": "raw_preserving_model",
                "available": True,
                "native_read_model_write_available": True,
                "parsed_model_available": True,
                "byte_identical": True,
                "byte_identical_no_edit_rebuild_supported": True,
                "semantic_rebuild_supported": False,
                "havok_xml_import_unblocked": False,
                "input_byte_length": len(data),
                "output_byte_length": len(data),
                "parsed_tag_item_count": 1,
                "parsed_item_record_count": 1,
                "parsed_object_record_count": 1,
                "first_mismatch_offset": None,
                "validation_errors": [],
            },
            "warnings": [],
        }

        with mock.patch("cdmw.core.hkx_native.parse_hkx_summary_with_rust", return_value=native_summary):
            document = build_hkx_editable_geometry_document(data, "physics/native.hkx")

        native_backend = document["native_backend"]
        self.assertTrue(native_backend["available"])
        self.assertEqual("native_rust_cd_hkx", native_backend["backend"])
        self.assertEqual(1, native_backend["object_record_count"])
        self.assertEqual(1, native_backend["physics_tuning_group_count"])
        self.assertEqual(1, native_backend["physics_tuning_slot_count"])
        self.assertEqual(1, native_backend["tagfile_reference_fixup_section_count"])
        self.assertEqual({"object_reference": 2}, native_backend["tagfile_reference_fixup_reference_category_counts"])
        self.assertEqual("cd_hkx_tagfile_reference_fixups_v1", native_backend["tagfile_reference_fixups"]["format"])
        self.assertEqual("experimental_observation", native_backend["fixup_semantics_status"])
        self.assertEqual({"1,1,0,2": 1}, native_backend["fixup_semantics_ptch_tuple_shape_counts"])
        self.assertEqual("cd_hkx_fixup_semantics_report_v1", native_backend["fixup_semantics_report"]["format"])
        self.assertEqual("ptch_patch_sites_normalized_read_only", native_backend["fixup_semantics_v2_status"])
        self.assertEqual(1, native_backend["fixup_semantics_v2_semantic_bucket_counts"]["object_ref"])
        self.assertIn("data_ref", native_backend["fixup_semantics_v2_semantic_bucket_counts"])
        self.assertEqual("native_model_graph_partial", native_backend["native_model_graph_status"])
        self.assertEqual(2, native_backend["native_model_graph_node_count"])
        self.assertEqual(1, native_backend["native_model_graph_edge_count"])
        self.assertEqual(1, native_backend["native_model_graph_fixup_backed_reference_edge_count"])
        self.assertEqual("read_only_semantic_model_from_native_records", native_backend["semantic_model_v1_status"])
        self.assertEqual(1, native_backend["semantic_model_v1_object_count"])
        self.assertEqual("semantic_writer_disabled_until_byte_identity_proof", native_backend["semantic_writer_gate_v1_status"])
        self.assertFalse(native_backend["semantic_writer_gate_v1_havok_xml_import_unblocked"])
        self.assertEqual(6, native_backend["semantic_writer_gate_v1_required_role_count"])
        self.assertEqual(6, native_backend["semantic_writer_gate_v1_representative_role_gate_count"])
        self.assertEqual("fixed_size_numeric_candidates_only", native_backend["edit_candidate_map_v1_status"])
        self.assertEqual(1, native_backend["edit_candidate_map_v1_write_enabled_candidate_count"])
        self.assertEqual("fixed_size_patch_gate", native_backend["hkx_edit_gate_v1_status"])
        self.assertEqual(1, native_backend["hkx_edit_gate_v1_write_enabled_candidate_count"])
        self.assertEqual(0, native_backend["hkx_edit_gate_v1_candidate_only_count"])
        self.assertEqual("class_specific_decode_evidence_available", native_backend["class_decoder_evidence_v2_status"])
        self.assertEqual("read_only_native_evidence", native_backend["decoder_evidence_v2_status"])
        self.assertEqual({"object": 2, "null": 1}, native_backend["decoder_evidence_v2_reference_semantic_counts"])
        self.assertEqual(1, document["edit_candidate_map_v1"]["write_enabled_candidate_count"])
        self.assertEqual("cdmw_hkx_edit_gate_v1", document["hkx_edit_gate_v1"]["format"])
        self.assertEqual("cd_hkx_edit_gate_v1", document["hkx_edit_gate_v1"]["native_format"])
        self.assertTrue(
            any(
                row["category"] == "motor_force_response" and row["status"] == "enabled"
                for row in document["hkx_edit_gate_v1"]["categories"]
            )
        )
        self.assertFalse(document["semantic_writer_gate_v1"]["havok_xml_import_unblocked"])
        self.assertEqual("raw_preserving_no_edit", document["semantic_writer_gate_v1"]["writer_modes"][0]["mode"])
        self.assertEqual(6, len(document["semantic_writer_gate_v1"]["representative_role_gates"]))
        self.assertEqual(
            "candidate_only_until_edit_gate",
            document["semantic_model_v1"]["objects"][0]["fields"][0]["write_gate_status"],
        )
        decoder_evidence = document["decoder_evidence_v2"]
        self.assertEqual("cdmw_hkx_decoder_evidence_v2", decoder_evidence["format"])
        self.assertEqual("native_rust_cd_hkx", decoder_evidence["source"])
        self.assertFalse(decoder_evidence["edit_policy"]["new_editable_fields_enabled"])
        self.assertEqual("fixup_backed", decoder_evidence["class_statuses"][0]["link_evidence"][0])
        self.assertEqual("byte_identical", native_backend["no_edit_binary_writer_status"])
        self.assertTrue(native_backend["no_edit_binary_writer_available"])
        self.assertTrue(native_backend["native_read_model_write_available"])
        self.assertTrue(native_backend["byte_identical_no_edit_rebuild_supported"])
        readiness = document["hkclass_metadata_readiness"]
        self.assertEqual("synthetic_recovered_hkClass", readiness["__types_section_status"])
        self.assertFalse(readiness["real_hkclass_metadata_recovered"])
        self.assertIn("member_type_codes", readiness["unresolved_real_metadata_counts"])
        self.assertEqual("native_model_graph_partial", readiness["native_model_graph"]["status"])
        self.assertTrue(readiness["native_model_graph"]["native_backend_available"])
        self.assertTrue(readiness["native_model_graph"]["native_object_records_available"])
        self.assertTrue(readiness["native_model_graph"]["native_fixup_semantics_available"])
        self.assertEqual("available", readiness["native_model_graph"]["rust_low_level_parse_status"])
        self.assertTrue(readiness["native_model_graph"]["rust_parses_sections_items_fixups_objects"])
        self.assertTrue(readiness["native_model_graph"]["python_builds_richer_graph_export"])
        self.assertTrue(readiness["native_model_graph"]["native_object_graph_available"])
        self.assertTrue(readiness["native_model_graph"]["native_fixup_backed_reference_graph_available"])
        self.assertTrue(readiness["native_model_graph"]["native_relationship_graph_available"])
        self.assertEqual(2, readiness["native_model_graph"]["native_model_graph_node_count"])
        self.assertEqual(1, readiness["native_model_graph"]["native_model_graph_edge_count"])
        self.assertTrue(readiness["native_model_graph"]["native_writer_model_available"])
        self.assertTrue(readiness["native_model_graph"]["native_no_edit_binary_writer_available"])
        self.assertTrue(readiness["native_model_graph"]["native_no_edit_byte_identical"])
        self.assertEqual("byte_identical", readiness["no_edit_binary_writer"]["status"])
        self.assertTrue(readiness["no_edit_binary_writer"]["native_read_model_write_available"])
        self.assertTrue(readiness["no_edit_binary_writer"]["byte_identical_no_edit_rebuild_supported"])
        self.assertEqual("native_no_edit_read_model_write_byte_identity", readiness["biggest_remaining_gate"]["key"])
        self.assertEqual(
            "file_level_passed_representative_corpus_pending",
            readiness["biggest_remaining_gate"]["status"],
        )
        self.assertTrue(readiness["biggest_remaining_gate"]["native_read_model_write_available"])
        self.assertEqual("partial_synthetic_recovery", readiness["class_internals"]["status"])
        self.assertFalse(readiness["class_internals"]["real_class_internals_recovered"])
        self.assertEqual("open_hard_decoder_targets", readiness["hard_decoder_targets"]["status"])
        self.assertFalse(
            next(
                target
                for target in readiness["hard_decoder_targets"]["targets"]
                if target["key"] == "hknp_mesh_primitive_bit_layout"
            )["resolved"]
        )
        self.assertEqual("partial_user_friendly_modding", readiness["gui_readiness"]["status"])
        self.assertTrue(
            any(target["key"] == "visual_object_value_linking" for target in readiness["gui_readiness"]["targets"])
        )

        with mock.patch("cdmw.core.hkx_native.parse_hkx_summary_with_rust", return_value=native_summary):
            xml_text = build_hkx_editable_geometry_xml(data, "physics/native.hkx")
        self.assertIn("<decoderEvidence", xml_text)
        self.assertIn("<referenceSemantics>", xml_text)
        self.assertIn("fixupBackedFields", xml_text)
        self.assertIn("<fixupSemanticsV2", xml_text)
        self.assertIn("<semanticBucketTaxonomy", xml_text)
        self.assertIn("<corpusEvidenceCounters", xml_text)
        self.assertIn("<semanticModelV1", xml_text)
        self.assertIn("<fieldKindTaxonomy", xml_text)
        self.assertIn("<semanticWriterGateV1", xml_text)
        self.assertIn("<writerModes", xml_text)
        self.assertIn("<representativeRoleGates", xml_text)
        self.assertIn("<editCandidateMapV1", xml_text)
        self.assertIn("<classDecoderEvidenceV2", xml_text)

    def test_real_hkclass_metadata_overrides_synthetic_types(self) -> None:
        data = (32).to_bytes(4, "big") + b"TAG0" + b"\0" * 24
        recovered_requirements = {
            "member_type_codes": True,
            "member_flags": True,
            "base_classes": True,
            "enum_refs": True,
            "signatures": True,
            "versions": True,
            "default_values": True,
            "template_refs": True,
        }
        native_summary = {
            "tag_items": [{"name": "TAG0", "offset": 4}],
            "string_table_names": ["hknpFoo"],
            "type_infos": [{"index": 1, "name": "hknpFoo", "template_parameters": []}],
            "declared_type_name_count": 2,
            "type_names": ["hknpFoo"],
            "item_records": [],
            "object_records": [],
            "real_hkclass_metadata": {
                "format": "cd_hkx_real_hkclass_metadata_v1",
                "status": "real_hkclass_records_decoded",
                "class_count": 1,
                "member_count": 1,
                "enum_count": 0,
                "recovered_requirements": recovered_requirements,
                "unresolved_requirements": [],
                "classes": [
                    {
                        "name": "hknpFoo",
                        "record_index": 7,
                        "parent_name": "hkReferencedObject",
                        "parent_record_index": 6,
                        "object_size": 64,
                        "version": 3,
                        "flags": 4,
                        "signature": 0xABCDEF01,
                        "signature_hex": "0xABCDEF01",
                        "defaults_record_index": None,
                        "attributes_record_index": None,
                        "declared_enum_count": 0,
                        "declared_member_count": 1,
                        "members_record_index": 8,
                        "enums_record_index": None,
                        "recovered_requirements": recovered_requirements,
                        "unresolved_requirements": [],
                        "members": [
                            {
                                "name": "mass",
                                "record_index": 8,
                                "item_index": 0,
                                "type_code": 11,
                                "type_name": "TYPE_REAL",
                                "subtype_code": 0,
                                "subtype_name": "TYPE_VOID",
                                "c_array_size": 0,
                                "flags": 0x1234,
                                "flags_hex": "0x1234",
                                "offset": 0x20,
                                "offset_hex": "0x20",
                                "class_ref_record_index": None,
                                "class_ref_name": None,
                                "enum_ref_record_index": None,
                                "enum_ref_name": None,
                                "attributes_ref_record_index": None,
                                "template_ref": None,
                                "confidence": "strong inference",
                            }
                        ],
                        "enums": [],
                        "confidence": "strong inference",
                    }
                ],
            },
            "real_hkclass_metadata_v2": {
                "format": "cd_hkx_real_hkclass_metadata_v2",
                "status": "real_metadata_available_read_only",
                "class_count": 1,
                "member_count": 1,
                "enum_count": 0,
                "synthetic_fallback_required": False,
                "classes": [
                    {
                        "class_name": "hknpFoo",
                        "name": "hknpFoo",
                        "record_index": 7,
                        "base_class": "hkReferencedObject",
                        "object_size": 64,
                        "version": 3,
                        "flags": 4,
                        "signature": 0xABCDEF01,
                        "signature_hex": "0xABCDEF01",
                        "declared_enum_count": 0,
                        "declared_member_count": 1,
                        "members_record_index": 8,
                        "members": [
                            {
                                "name": "mass",
                                "member_type_code": 11,
                                "member_type_name": "TYPE_REAL",
                                "subtype_code": 0,
                                "subtype_name": "TYPE_VOID",
                                "c_array_size": 0,
                                "flags": 0x1234,
                                "flags_hex": "0x1234",
                                "offset": 0x20,
                                "offset_hex": "0x20",
                                "array_status": "not_array",
                                "reference_status": "not_reference",
                                "confidence": "strong inference",
                            }
                        ],
                        "confidence": "strong inference",
                    }
                ],
            },
            "warnings": [],
        }

        with mock.patch("cdmw.core.hkx_native.parse_hkx_summary_with_rust", return_value=native_summary):
            document = build_hkx_editable_geometry_document(data, "physics/real_hkclass.hkx")
            xml_text = build_hkx_editable_geometry_xml(data, "physics/real_hkclass.hkx")

        hkclass = next(row for row in document["havok_xml_view"]["hkclasses"] if row["name"] == "hknpFoo")
        self.assertEqual("real_hkClass_records", hkclass["metadata_status"])
        self.assertTrue(hkclass["real_hkclass_metadata_recovered"])
        self.assertEqual("hkReferencedObject", hkclass["parent"])
        self.assertEqual("0xABCDEF01", hkclass["signature"])
        self.assertEqual(3, hkclass["version"])
        member = hkclass["members"][0]
        self.assertEqual("mass", member["name"])
        self.assertEqual("TYPE_REAL", member["member_type"])
        self.assertEqual(11, member["member_type_code"])
        self.assertEqual(0x1234, member["member_flags"])
        self.assertEqual(0x20, member["offset"])

        readiness = document["hkclass_metadata_readiness"]
        self.assertEqual("real_hkClass_metadata", readiness["__types_section_status"])
        self.assertTrue(readiness["real_hkclass_metadata_recovered"])
        self.assertEqual("real_hkclass_records_decoded", readiness["real_hkclass_metadata_status"])
        self.assertEqual(1, readiness["native_real_hkclass_metadata_member_count"])
        self.assertTrue(
            all(requirement["recovered"] for requirement in readiness["missing_real_hkclass_metadata"])
        )

        self.assertIn('member_type_code="11"', xml_text)
        self.assertIn('real_hkclass_metadata_recovered="true"', xml_text)
        self.assertIn("<realHkclassMetadataV2", xml_text)
        self.assertIn('havok_member_type_code="11"', xml_text)


if __name__ == "__main__":
    unittest.main()
