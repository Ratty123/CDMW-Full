from __future__ import annotations

import ast
import csv
import dataclasses
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from cdmw.core import (
    archive_hkx,
    archive_hkx_collision_parser,
    archive_hkx_corpus_evidence,
    archive_hkx_corpus_planning,
    archive_hkx_corpus_report,
    archive_hkx_corpus_scan,
    archive_hkx_descriptor,
    archive_hkx_editable_geometry,
    archive_hkx_editing,
    archive_hkx_havok_xml,
    archive_hkx_overlay,
    archive_hkx_overlay_support,
    archive_hkx_preview,
    archive_hkx_preview_geometry,
    archive_hkx_parser,
    archive_hkx_patch_ops,
    archive_hkx_record_constants,
    archive_hkx_roles,
    archive_hkx_summary,
    archive_hkx_types,
    archive_hkx_xml_import,
)
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_XML = (
    '<PhysicsRoot _pbdSimulationMaterialName="hair_sim">'
    '<PhysicsAttachmentInstance>'
    '<BodyCreationDesc Name="_parentBodyDesc" _bodyName="Root" _socketName="Head" _angularDamping="0.2"/>'
    '<BodyCreationDesc Name="_childBodyDesc" _bodyName="PonyTail" _socketName="HairSocket" '
    '_physicsMaterialName="HairPhysics" _linearDamping="0.8">'
    '<CapsuleShapeDesc _sphereRadius="0.25" _cylinderHeight="1.5"/>'
    '</BodyCreationDesc>'
    '<RagdollConstraintDesc _name="HairJoint" _coneAngle="0.7"/>'
    '</PhysicsAttachmentInstance>'
    '<MaterialBinding _materialName="CapeCloth" _subMeshName="Cape" _jiggleWindWeight="0.5"/>'
    '</PhysicsRoot>'
)
DESCRIPTOR_GOLDEN_SHA256 = "a513c9863ed492ebd3a57df7ed301f2ba69053f4c9fca7cd3fd1cdb5477933a5"

DESCRIPTOR_SYMBOLS = (
    "_HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS",
    "_hkx_descriptor_body_documents",
    "_hkx_descriptor_constraint_documents",
    "_hkx_descriptor_core_attributes",
    "_hkx_descriptor_element_local_name",
    "_hkx_descriptor_hint_from_root",
    "_hkx_descriptor_material_simulation_documents",
    "_hkx_descriptor_numeric_hint_values",
    "_hkx_descriptor_shape_type",
    "_hkx_descriptor_unique_values",
    "build_hkx_descriptor_hint_from_xml_text",
)
ROLE_SYMBOLS = (
    "_HKX_SIMULATION_ROLE_DESCRIPTIONS",
    "_hkx_simulation_role_counts",
    "_hkx_simulation_role_description",
    "_hkx_simulation_role_from_parts",
)
EDITABLE_GEOMETRY_SYMBOLS = ("build_hkx_editable_geometry_document",)
OVERLAY_SYMBOLS = (
    "build_hkx_physics_overlay_from_document",
    "merge_hkx_physics_overlays",
)
OVERLAY_SUPPORT_SYMBOLS = (
    "_hkx_overlay_anchor_match_key",
    "_hkx_overlay_average_position",
    "_hkx_overlay_body_shape_targets",
    "_hkx_overlay_bones_from_skeleton_positions",
    "_hkx_overlay_descriptor_vector",
    "_hkx_overlay_name_aliases",
    "_hkx_overlay_shape_visual_center",
    "_hkx_overlay_skeleton_bone_match",
    "_hkx_overlay_translate_point",
    "_hkx_overlay_tuning_hint_text",
    "_hkx_overlay_vector",
)
PREVIEW_GEOMETRY_SYMBOLS = (
    "_hkx_preview_bounds",
    "_hkx_preview_box_mesh",
    "_hkx_preview_cylinder_mesh",
    "_hkx_preview_dimension",
    "_hkx_preview_edges_from_faces",
    "_hkx_preview_float",
    "_hkx_preview_marker_mesh",
    "_hkx_preview_shape_meshes",
    "_hkx_preview_skeleton_meshes",
    "_hkx_preview_sphere_mesh",
    "_hkx_preview_triangulated_indices",
    "_hkx_preview_vec_add",
    "_hkx_preview_vec_cross",
    "_hkx_preview_vec_length",
    "_hkx_preview_vec_normalize",
    "_hkx_preview_vec_scale",
    "_hkx_preview_vec_sub",
    "_hkx_preview_vector",
    "build_hkx_model_preview_from_document",
)
PREVIEW_SYMBOLS = ("build_hkx_preview",)
CORPUS_PLANNING_SYMBOLS = (
    "_HKX_CORPUS_ROLE_LABELS",
    "_HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS",
    "_HKX_REPRESENTATIVE_REAL_CORPUS_REQUIREMENTS",
    "_HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES",
    "_hkx_corpus_role_for_document",
    "_hkx_corpus_role_hint_from_path",
    "_hkx_enrich_balanced_corpus_content_hints",
    "_hkx_hard_decoder_corpus_proof_document",
    "_hkx_path_contains_binary_marker",
    "_hkx_ptch_semantics_proof_document",
    "_hkx_representative_real_corpus_plan_document",
    "_hkx_representative_real_role_matches",
    "_hkx_row_is_generated_hkx_sample",
    "_hkx_select_balanced_corpus_paths",
)
CORPUS_EVIDENCE_SYMBOLS = (
    "_HKX_CORPUS_PRIORITY_CLASS_TARGETS",
    "_hkx_corpus_counter_matching",
    "_hkx_corpus_counter_value",
    "_hkx_corpus_file_examples_for_ptch_case",
    "_hkx_corpus_file_examples_for_target",
    "_hkx_corpus_int",
    "_hkx_corpus_sorted_count_rows",
    "build_hkx_corpus_evidence_from_report",
    "load_hkx_corpus_evidence_json",
)
CORPUS_REPORT_SYMBOLS = (
    "_HKX_CORPUS_DEFAULT_DETAIL_LIMIT",
    "_HKX_CORPUS_DEFAULT_ROUNDTRIP_LIMIT",
    "build_hkx_converter_corpus_csv",
    "build_hkx_converter_corpus_json",
    "build_hkx_converter_corpus_report",
)
CORPUS_SCAN_SYMBOLS = (
    "_hkx_descriptor_hint_document",
    "_hkx_descriptor_hints_by_stem",
)
TYPE_SYMBOLS = (
    "HkxCollisionGeometryHint",
    "HkxGeometryPatchResult",
    "HkxItemPayloadSummary",
    "HkxItemRecord",
    "HkxPreviewResult",
    "HkxTagItem",
    "HkxTagfileSummary",
    "HkxTypeInfo",
)
PARSER_SYMBOLS = (
    "_HKX_KNOWN_TAG_SECTIONS",
    "_HKX_PRINTABLE_SCAN_LIMIT",
    "_HKX_PRINTABLE_STRING_LIMIT",
    "_HKX_TAG_ITEM_MARKERS",
    "_HKX_TYPE_NAME_RE",
    "_decode_hkx_length_word",
    "_detect_hkx_data_payload_offset",
    "_detect_hkx_declared_size",
    "_detect_hkx_sdk_version",
    "_detect_hkx_tag_sections",
    "_extract_hkx_declared_type_name_count",
    "_extract_hkx_printable_strings",
    "_extract_hkx_tst1_type_names",
    "_extract_hkx_type_names",
    "_find_hkx_tag_items",
    "_hkx_next_tag_item",
    "_hkx_sdk_version_label",
    "_hkx_tag_item_by_name",
    "_parse_hkx_item_records",
    "_parse_hkx_tna1_type_infos",
    "_read_hkx_var_uint",
    "parse_hkx_tagfile_summary",
)
SUMMARY_SYMBOLS = (
    "_assign_hkx_mass_property_records",
    "_build_hkx_hull_geometry_hint",
    "_decode_hkx_convex_face_vertex_indices",
    "_format_hkx_float_bounds",
    "_format_hkx_vector",
    "_hkx_hex",
    "_hkx_item_record_spans",
    "_hkx_offset_index_target",
    "_hkx_payload_slice",
    "_hkx_possible_record_link_documents",
    "_hkx_record_offset_indexes",
    "_read_hkx_float_vector_payload",
    "_summarize_hkx_float_rows",
    "_summarize_hkx_float_vectors",
    "_summarize_hkx_item_payloads",
    "_summarize_hkx_object_payload",
    "_summarize_hkx_possible_record_links",
    "_summarize_hkx_u32_words",
)
COLLISION_PARSER_SYMBOLS = (
    "_infer_hkx_capsule_hints",
    "_infer_hkx_collision_geometry_hints",
    "_infer_hkx_convex_and_box_hints",
    "_infer_hkx_mesh_hints",
    "_infer_hkx_sphere_hints",
)
HAVOK_XML_SYMBOLS = (
    "_hkx_havok_xml_add_objects",
    "_hkx_havok_xml_add_types",
    "_hkx_havok_xml_context",
    "_hkx_havok_xml_root",
    "build_hkx_havok_xml_view_xml",
)
EDITING_SYMBOLS = (
    "_patch_hkx_advanced_payloads",
    "_patch_hkx_shape_payloads",
    "_patch_hkx_shape_scalars",
    "_patch_hkx_shape_topology",
    "_patch_hkx_shapes",
    "apply_hkx_editable_geometry_document",
)
PATCH_OPS_SYMBOLS = (
    "_hkx_advanced_editable_values_content",
    "_hkx_compare_optional_scalar",
    "_hkx_mesh_primitive_rows_by_record",
    "_hkx_mesh_primitive_signature",
    "_hkx_physics_tuning_slot_map",
    "_hkx_validate_converter_invariants",
    "_hkx_validate_record_identity",
    "_hkx_validate_report_records",
    "_hkx_vectors_differ",
    "_normalize_hkx_mesh_primitive_bytes",
    "_patch_hkx_advanced_editable_values",
    "_patch_hkx_float_vectors",
    "_patch_hkx_mass_property_rows",
    "_patch_hkx_mesh_primitive_winding_edits",
    "_patch_hkx_physics_tuning_values",
    "_patch_hkx_record_payload",
    "_patch_hkx_shape_payload_float_slots",
    "_require_hkx_int",
    "_require_hkx_shape_payload_float_slots",
    "_require_hkx_vector_list",
    "_validate_hkx_same_length_payload_edit",
)
XML_IMPORT_SYMBOLS = (
    "_hkx_advanced_editable_values_from_xml",
    "_hkx_advanced_payloads_from_editable_xml",
    "_hkx_document_from_editable_geometry_xml",
    "_hkx_parse_xml_int_list",
    "_hkx_shape_base_from_xml",
    "_hkx_shape_geometry_from_xml",
    "_hkx_shape_mesh_from_xml",
    "_hkx_shape_topology_from_xml",
    "_hkx_shapes_from_editable_xml",
    "_hkx_source_from_editable_xml",
    "_hkx_tuning_from_editable_xml",
    "_hkx_xml_face_indices",
    "_hkx_xml_float_attr",
    "_hkx_xml_int_attr",
    "_hkx_xml_vector",
    "apply_hkx_editable_geometry_json",
    "apply_hkx_editable_geometry_xml",
)
RECORD_CONSTANT_SYMBOLS = ("_HKX_ENUM_RECORD_TYPES", "_HKX_SCALAR_ARRAY_TYPES")

HKX_CORPUS_FIXTURE_SHA256 = "75f707e774fe4b9b81068f415ffc5eb63f95338fa2cfb24059a63784e7ed0821"
HKX_DOCUMENT_GOLDEN_SHA256 = "0a3b9c8fe6a3e207685d30e3a518ffe5f2d70609afcec5ce98b755355775a3f5"
HKX_OVERLAY_GOLDEN_SHA256 = "958b03c74ec74e9400683b1cfc705a050e500a7a42c336ec00a1f4a8cfa42e1d"
HKX_MODEL_PREVIEW_GOLDEN_SHA256 = "3723ec84ace8824cad50f58b56b81aeeddfd59e5e77d1536921811b2d58a2f95"
HKX_TEXT_PREVIEW_GOLDEN_SHA256 = "11b604de532c41afd045bc888e13722d97a01d07474eb431ecfc5c2956b2f67f"
HKX_CORPUS_PURE_REPORT_SHA256 = "d378fb0ff11355e017e52e20c15f8a3607419dfdc096595d618c75f9734dc919"
HKX_CORPUS_PURE_EVIDENCE_SHA256 = "87d89b7da9058297f6bcc4db12fa3948a40994d64dddda679f8b2cc7bd5a4671"
HKX_CORPUS_NATIVE_REPORT_SHA256 = "c30539608fe5aa49da070654062d74d0e6ebce38f4bc00214817545543889965"
HKX_CORPUS_NATIVE_EVIDENCE_SHA256 = "2d41cd18a800b498b6abb579f85c342225aae3be7879b036ed802d6f78f6b845"
HKX_CORPUS_CSV_SHA256 = "16f90accac11e29d5798ec50449cfa32ac143b00d23306f6b3ff19b49245ca4c"
HKX_HAVOK_XML_GOLDEN_SHA256 = "b7ef892c6b89b0d9d2a2e7d7b0d60f3e3fbfe184687c2174629078a5e4e90356"
HKX_PATCH_XML_GOLDEN_SHA256 = "f6ed16b67dd54f99a6b795d953c58f4b8921c4ceee74493aa7d33306d44297bf"


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _representative_hkx_bytes() -> bytes:
    from tests.test_hkx_preview import HkxPreviewTests

    case = HkxPreviewTests(methodName="test_modern_tagfile_preview_reports_sdk_and_embedded_hknp_types")
    return case._modern_hkx_bytes()


def test_hkx_descriptor_and_role_exports_keep_owner_identity() -> None:
    for name in DESCRIPTOR_SYMBOLS:
        assert getattr(archive_hkx, name) is getattr(archive_hkx_descriptor, name), name
    for name in ROLE_SYMBOLS:
        assert getattr(archive_hkx, name) is getattr(archive_hkx_roles, name), name


def test_hkx_preview_and_editable_exports_keep_owner_identity() -> None:
    groups = (
        (archive_hkx_types, TYPE_SYMBOLS),
        (archive_hkx_parser, PARSER_SYMBOLS),
        (archive_hkx_summary, SUMMARY_SYMBOLS),
        (archive_hkx_collision_parser, COLLISION_PARSER_SYMBOLS),
        (archive_hkx_record_constants, RECORD_CONSTANT_SYMBOLS),
        (archive_hkx_havok_xml, HAVOK_XML_SYMBOLS),
        (archive_hkx_patch_ops, PATCH_OPS_SYMBOLS),
        (archive_hkx_editing, EDITING_SYMBOLS),
        (archive_hkx_xml_import, XML_IMPORT_SYMBOLS),
        (archive_hkx_corpus_evidence, CORPUS_EVIDENCE_SYMBOLS),
        (archive_hkx_corpus_planning, CORPUS_PLANNING_SYMBOLS),
        (archive_hkx_corpus_report, CORPUS_REPORT_SYMBOLS),
        (archive_hkx_corpus_scan, CORPUS_SCAN_SYMBOLS),
        (archive_hkx_editable_geometry, EDITABLE_GEOMETRY_SYMBOLS),
        (archive_hkx_overlay, OVERLAY_SYMBOLS),
        (archive_hkx_overlay_support, OVERLAY_SUPPORT_SYMBOLS),
        (archive_hkx_preview_geometry, PREVIEW_GEOMETRY_SYMBOLS),
        (archive_hkx_preview, PREVIEW_SYMBOLS),
    )
    for owner, symbols in groups:
        for name in symbols:
            assert getattr(archive_hkx, name) is getattr(owner, name), name


def test_hkx_descriptor_golden_output_is_unchanged() -> None:
    document = archive_hkx.build_hkx_descriptor_hint_from_xml_text(
        DESCRIPTOR_XML,
        "character/bin__/havokphysics/hair.xml",
    )
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert hashlib.sha256(canonical).hexdigest() == DESCRIPTOR_GOLDEN_SHA256
    assert document is not None
    assert document["body_desc_count"] == 2
    assert document["constraint_desc_count"] == 1
    assert document["shape_desc_count"] == 1
    assert document["material_simulation_hint_count"] == 4
    assert archive_hkx.build_hkx_descriptor_hint_from_xml_text("<broken") is None


def test_hkx_preview_geometry_corpus_outputs_are_unchanged() -> None:
    data = _representative_hkx_bytes()
    assert hashlib.sha256(data).hexdigest() == HKX_CORPUS_FIXTURE_SHA256
    bones = {
        "Root": {
            "name": "Root",
            "index": 0,
            "parent_index": -1,
            "position": (0.0, 0.0, 0.0),
            "source_path": "character/golden.pab",
        },
        "Spine": {
            "name": "Spine",
            "index": 1,
            "parent_index": 0,
            "parent_name": "Root",
            "position": (0.0, 2.0, 0.0),
            "source_path": "character/golden.pab",
        },
    }
    with mock.patch.object(archive_hkx, "_hkx_native_summary_parts", return_value=None):
        document = archive_hkx.build_hkx_editable_geometry_document(data, "object/golden.hkx")
        text_preview = archive_hkx.build_hkx_preview(data, "object/golden.hkx")
    overlay = archive_hkx.build_hkx_physics_overlay_from_document(
        document,
        source_path="object/golden.hkx",
        skeleton_bone_positions=bones,
    )
    model_preview = archive_hkx.build_hkx_model_preview_from_document(
        document,
        source_path="object/golden.hkx",
        skeleton_bone_positions=bones,
    )
    assert overlay is not None
    assert model_preview is not None
    assert _canonical_digest(document) == HKX_DOCUMENT_GOLDEN_SHA256
    assert _canonical_digest(dataclasses.asdict(overlay)) == HKX_OVERLAY_GOLDEN_SHA256
    assert _canonical_digest(dataclasses.asdict(model_preview)) == HKX_MODEL_PREVIEW_GOLDEN_SHA256
    assert _canonical_digest(
        {"preview_text": text_preview.preview_text, "detail_lines": text_preview.detail_lines}
    ) == HKX_TEXT_PREVIEW_GOLDEN_SHA256


def test_hkx_xml_and_no_edit_roundtrip_goldens_are_unchanged() -> None:
    data = _representative_hkx_bytes()
    with mock.patch.object(archive_hkx, "_hkx_native_summary_parts", return_value=None):
        havok_xml = archive_hkx.build_hkx_havok_xml_view_xml(data, "object/golden.hkx")
        patch_xml = archive_hkx.build_hkx_editable_geometry_xml(data, "object/golden.hkx")
        result = archive_hkx.apply_hkx_editable_geometry_xml(data, patch_xml)

    assert hashlib.sha256(havok_xml.encode("utf-8")).hexdigest() == HKX_HAVOK_XML_GOLDEN_SHA256
    assert hashlib.sha256(patch_xml.encode("utf-8")).hexdigest() == HKX_PATCH_XML_GOLDEN_SHA256
    assert result.data == data
    assert result.changed_fields == []
    assert result.warnings == []


def _normalized_corpus_value(value: object, root: Path) -> object:
    if isinstance(value, dict):
        return {
            key: 0.0 if key == "scan_seconds" else _normalized_corpus_value(item, root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalized_corpus_value(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "${ROOT}").replace(root.as_posix(), "${ROOT}")
    return value


def _normalized_corpus_csv(text: str, root: Path) -> str:
    reader = csv.DictReader(io.StringIO(text))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        row["path"] = row["path"].replace(str(root), "${ROOT}").replace(root.as_posix(), "${ROOT}")
        row["scan_seconds"] = "0.0"
        writer.writerow(row)
    return output.getvalue()


def test_hkx_corpus_report_evidence_and_csv_goldens_are_unchanged() -> None:
    data = _representative_hkx_bytes()
    native_preflight = {
        "format": "cd_hkx_corpus_stats_v1",
        "file_count": 1,
        "ok_count": 1,
        "total_item_records": 8,
        "total_physics_tuning_slots": 0,
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        object_dir = root / "object"
        object_dir.mkdir()
        (object_dir / "golden.hkx").write_bytes(data)
        for native_value, report_digest, evidence_digest in (
            (None, HKX_CORPUS_PURE_REPORT_SHA256, HKX_CORPUS_PURE_EVIDENCE_SHA256),
            (native_preflight, HKX_CORPUS_NATIVE_REPORT_SHA256, HKX_CORPUS_NATIVE_EVIDENCE_SHA256),
        ):
            with (
                mock.patch.object(archive_hkx, "_hkx_native_summary_parts", return_value=None),
                mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=native_value),
            ):
                report = archive_hkx.build_hkx_converter_corpus_report((root,))
            assert _canonical_digest(_normalized_corpus_value(report, root)) == report_digest
            assert _canonical_digest(_normalized_corpus_value(report["corpus_evidence"], root)) == evidence_digest
        with (
            mock.patch.object(archive_hkx, "_hkx_native_summary_parts", return_value=None),
            mock.patch("cdmw.core.hkx_native.scan_hkx_corpus_with_rust", return_value=None),
        ):
            csv_text = archive_hkx.build_hkx_converter_corpus_csv((root,))
        normalized_csv = _normalized_corpus_csv(csv_text, root)
        assert hashlib.sha256(normalized_csv.encode("utf-8")).hexdigest() == HKX_CORPUS_CSV_SHA256


def test_hkx_owner_modules_and_facade_size_ratchet() -> None:
    facade_path = Path("cdmw/core/archive_hkx.py")
    facade_tree = ast.parse(facade_path.read_text(encoding="utf-8"))
    facade_definitions = {
        node.name
        for node in facade_tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert facade_definitions.isdisjoint(DESCRIPTOR_SYMBOLS)
    assert facade_definitions.isdisjoint(ROLE_SYMBOLS)
    moved_symbols = (
        TYPE_SYMBOLS
        + PARSER_SYMBOLS
        + SUMMARY_SYMBOLS
        + COLLISION_PARSER_SYMBOLS
        + HAVOK_XML_SYMBOLS
        + PATCH_OPS_SYMBOLS
        + EDITING_SYMBOLS
        + XML_IMPORT_SYMBOLS
        + RECORD_CONSTANT_SYMBOLS
        + CORPUS_EVIDENCE_SYMBOLS
        + CORPUS_PLANNING_SYMBOLS
        + CORPUS_REPORT_SYMBOLS
        + CORPUS_SCAN_SYMBOLS
        + EDITABLE_GEOMETRY_SYMBOLS
        + OVERLAY_SYMBOLS
        + OVERLAY_SUPPORT_SYMBOLS
        + PREVIEW_GEOMETRY_SYMBOLS
        + PREVIEW_SYMBOLS
    )
    assert facade_definitions.isdisjoint(moved_symbols)
    assert len(facade_path.read_text(encoding="utf-8").splitlines()) <= 16_500

    for path in (
        Path("cdmw/core/archive_hkx_descriptor.py"),
        Path("cdmw/core/archive_hkx_collision_parser.py"),
        Path("cdmw/core/archive_hkx_corpus_evidence.py"),
        Path("cdmw/core/archive_hkx_corpus_files.py"),
        Path("cdmw/core/archive_hkx_corpus_planning.py"),
        Path("cdmw/core/archive_hkx_corpus_report.py"),
        Path("cdmw/core/archive_hkx_corpus_scan.py"),
        Path("cdmw/core/archive_hkx_editable_geometry.py"),
        Path("cdmw/core/archive_hkx_editing.py"),
        Path("cdmw/core/archive_hkx_havok_xml.py"),
        Path("cdmw/core/archive_hkx_overlay.py"),
        Path("cdmw/core/archive_hkx_overlay_support.py"),
        Path("cdmw/core/archive_hkx_preview.py"),
        Path("cdmw/core/archive_hkx_preview_geometry.py"),
        Path("cdmw/core/archive_hkx_parser.py"),
        Path("cdmw/core/archive_hkx_patch_ops.py"),
        Path("cdmw/core/archive_hkx_record_constants.py"),
        Path("cdmw/core/archive_hkx_roles.py"),
        Path("cdmw/core/archive_hkx_summary.py"),
        Path("cdmw/core/archive_hkx_types.py"),
        Path("cdmw/core/archive_hkx_xml_import.py"),
        Path("cdmw/core/archive_hkx_xml_export_content.py"),
        Path("cdmw/core/archive_hkx_xml_export_physics.py"),
        Path("cdmw/core/archive_hkx_xml_export_reports.py"),
        Path("cdmw/core/archive_hkx_xml_export_semantics.py"),
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        function_sizes = [
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert max(function_sizes, default=0) <= 150, path


def test_hkx_exports_keep_identity_for_clean_import_orders() -> None:
    scripts = (
        "import cdmw.core.archive_hkx_descriptor as owner; "
        "import cdmw.core.archive_hkx_roles as roles; "
        "import cdmw.core.archive_hkx_editable_geometry as editable; "
        "import cdmw.core.archive_hkx_overlay as overlay; "
        "import cdmw.core.archive_hkx_overlay_support as overlay_support; "
        "import cdmw.core.archive_hkx_preview as preview; "
        "import cdmw.core.archive_hkx_preview_geometry as preview_geometry; "
        "import cdmw.core.archive_hkx_corpus_evidence as corpus_evidence; "
        "import cdmw.core.archive_hkx_corpus_planning as corpus_planning; "
        "import cdmw.core.archive_hkx_corpus_report as corpus_report; "
        "import cdmw.core.archive_hkx_corpus_scan as corpus_scan; "
        "import cdmw.core.archive_hkx as facade; "
        "import cdmw.core.archive_modding as compat; ",
        "import cdmw.core.archive_modding as compat; "
        "import cdmw.core.archive_hkx as facade; "
        "import cdmw.core.archive_hkx_descriptor as owner; "
        "import cdmw.core.archive_hkx_corpus_scan as corpus_scan; "
        "import cdmw.core.archive_hkx_corpus_report as corpus_report; "
        "import cdmw.core.archive_hkx_corpus_planning as corpus_planning; "
        "import cdmw.core.archive_hkx_corpus_evidence as corpus_evidence; "
        "import cdmw.core.archive_hkx_preview_geometry as preview_geometry; "
        "import cdmw.core.archive_hkx_preview as preview; "
        "import cdmw.core.archive_hkx_overlay_support as overlay_support; "
        "import cdmw.core.archive_hkx_overlay as overlay; "
        "import cdmw.core.archive_hkx_editable_geometry as editable; "
        "import cdmw.core.archive_hkx_roles as roles; ",
        "import cdmw.core.archive_hkx as facade; "
        "import cdmw.core.archive_hkx_descriptor as owner; "
        "import cdmw.core.archive_modding as compat; "
        "import cdmw.core.archive_hkx_corpus_evidence as corpus_evidence; "
        "import cdmw.core.archive_hkx_corpus_report as corpus_report; "
        "import cdmw.core.archive_hkx_corpus_scan as corpus_scan; "
        "import cdmw.core.archive_hkx_corpus_planning as corpus_planning; "
        "import cdmw.core.archive_hkx_preview as preview; "
        "import cdmw.core.archive_hkx_overlay as overlay; "
        "import cdmw.core.archive_hkx_editable_geometry as editable; "
        "import cdmw.core.archive_hkx_overlay_support as overlay_support; "
        "import cdmw.core.archive_hkx_preview_geometry as preview_geometry; "
        "import cdmw.core.archive_hkx_roles as roles; ",
    )
    assertions = (
        "assert facade.build_hkx_descriptor_hint_from_xml_text is owner.build_hkx_descriptor_hint_from_xml_text; "
        "assert compat.build_hkx_descriptor_hint_from_xml_text is owner.build_hkx_descriptor_hint_from_xml_text; "
        "assert facade._hkx_simulation_role_from_parts is roles._hkx_simulation_role_from_parts; "
        "assert compat._hkx_simulation_role_from_parts is roles._hkx_simulation_role_from_parts; "
        "assert facade.build_hkx_editable_geometry_document is editable.build_hkx_editable_geometry_document; "
        "assert compat.build_hkx_editable_geometry_document is editable.build_hkx_editable_geometry_document; "
        "assert facade.build_hkx_physics_overlay_from_document is overlay.build_hkx_physics_overlay_from_document; "
        "assert compat.build_hkx_physics_overlay_from_document is overlay.build_hkx_physics_overlay_from_document; "
        "assert facade._hkx_overlay_vector is overlay_support._hkx_overlay_vector; "
        "assert compat._hkx_overlay_vector is overlay_support._hkx_overlay_vector; "
        "assert facade.build_hkx_model_preview_from_document is preview_geometry.build_hkx_model_preview_from_document; "
        "assert compat.build_hkx_model_preview_from_document is preview_geometry.build_hkx_model_preview_from_document; "
        "assert facade.build_hkx_preview is preview.build_hkx_preview; "
        "assert compat.build_hkx_preview is preview.build_hkx_preview; "
        "assert facade.build_hkx_converter_corpus_report is corpus_report.build_hkx_converter_corpus_report; "
        "assert compat.build_hkx_converter_corpus_report is corpus_report.build_hkx_converter_corpus_report; "
        "assert facade.build_hkx_corpus_evidence_from_report is corpus_evidence.build_hkx_corpus_evidence_from_report; "
        "assert compat.build_hkx_corpus_evidence_from_report is corpus_evidence.build_hkx_corpus_evidence_from_report; "
        "assert facade._hkx_ptch_semantics_proof_document is corpus_planning._hkx_ptch_semantics_proof_document; "
        "assert compat._hkx_ptch_semantics_proof_document is corpus_planning._hkx_ptch_semantics_proof_document; "
        "assert facade._hkx_descriptor_hint_document is corpus_scan._hkx_descriptor_hint_document; "
        "assert compat._hkx_descriptor_hint_document is corpus_scan._hkx_descriptor_hint_document"
    )
    for imports in scripts:
        result = subprocess.run(
            [sys.executable, "-c", imports + assertions],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout


def test_hkx_parser_xml_and_edit_exports_keep_identity_for_clean_import_orders() -> None:
    owners = (
        "import cdmw.core.archive_hkx_types as types; "
        "import cdmw.core.archive_hkx_parser as parser; "
        "import cdmw.core.archive_hkx_summary as summary; "
        "import cdmw.core.archive_hkx_collision_parser as collision; "
        "import cdmw.core.archive_hkx_havok_xml as havok_xml; "
        "import cdmw.core.archive_hkx_patch_ops as patch_ops; "
        "import cdmw.core.archive_hkx_editing as editing; "
        "import cdmw.core.archive_hkx_xml_import as xml_import; "
    )
    facade = "import cdmw.core.archive_hkx as facade; import cdmw.core.archive_modding as compat; "
    assertions = (
        "assert facade.HkxTagfileSummary is types.HkxTagfileSummary; "
        "assert compat.HkxTagfileSummary is types.HkxTagfileSummary; "
        "assert facade.parse_hkx_tagfile_summary is parser.parse_hkx_tagfile_summary; "
        "assert compat.parse_hkx_tagfile_summary is parser.parse_hkx_tagfile_summary; "
        "assert facade._hkx_item_record_spans is summary._hkx_item_record_spans; "
        "assert facade._infer_hkx_collision_geometry_hints is collision._infer_hkx_collision_geometry_hints; "
        "assert facade.build_hkx_havok_xml_view_xml is havok_xml.build_hkx_havok_xml_view_xml; "
        "assert compat.build_hkx_havok_xml_view_xml is havok_xml.build_hkx_havok_xml_view_xml; "
        "assert facade._patch_hkx_float_vectors is patch_ops._patch_hkx_float_vectors; "
        "assert facade.apply_hkx_editable_geometry_document is editing.apply_hkx_editable_geometry_document; "
        "assert compat.apply_hkx_editable_geometry_document is editing.apply_hkx_editable_geometry_document; "
        "assert facade.apply_hkx_editable_geometry_xml is xml_import.apply_hkx_editable_geometry_xml; "
        "assert compat.apply_hkx_editable_geometry_xml is xml_import.apply_hkx_editable_geometry_xml"
    )
    for imports in (owners + facade, facade + owners):
        result = subprocess.run(
            [sys.executable, "-c", imports + assertions],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
