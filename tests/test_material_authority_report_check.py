from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from cdmw.core.material_authority_report_check import (
    MATERIAL_AUTHORITY_REPORT_FILENAME,
    check_material_authority_report,
    check_material_authority_report_path,
)
from tools.check_material_authority_report import main as check_report_main


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "schema": "cdmw_material_authority_report_v1",
        "source_path": "source.glb",
        "package_root": "package",
        "risk_flags": [],
        "target_sections": [{"target_name": "Body", "status": "ready", "binding_count": 1}],
        "texture_outputs": [
            {
                "target_path": "character/texture/body.dds",
                "source_path": "source.png",
                "kind": "texture_generated",
                "note": "Body base -> character/texture/body.dds",
                "bytes": 128,
                "sha256": "1" * 64,
                "output_sha256": "1" * 64,
                "payload_source": "inline_payload",
                "source_bytes": 0,
                "source_sha256": "",
                "dds_validation": {
                    "status": "valid",
                    "width": 4,
                    "height": 4,
                    "texconv_format": "BC7_UNORM",
                    "findings": [{"severity": "info", "code": "payload_size_valid"}],
                },
                "role_diagnostics": [],
                "conversion_policy": {
                    "source_extension": ".png",
                    "payload_kind": "texture_generated",
                    "generated": True,
                    "inline_payload": True,
                    "source_image_to_dds": True,
                    "bound_role_classes": ["base_color"],
                    "dds_format": "BC7_UNORM",
                    "channel_order": "block_color",
                    "mip_count": 3,
                    "normal_y_policy_required": False,
                    "channel_visualization_kinds": [],
                },
            }
        ],
        "routing": [
            {
                "material_name": "Body",
                "part_name": "Body",
                "role": "Base / Color",
                "parameter_name": "_overlayColorTexture",
                "sidecar_path": "character/modelproperty/body.pac_xml",
                "requested_texture_path": "character/texture/body.dds",
                "resolved_texture_path": "character/texture/body.dds",
                "binding_source": "generated",
                "status": "ready",
                "confidence": "exact",
            }
        ],
        "sidecar_reports": [
            {
                "status": "ok",
                "wrapper_order": [{"wrapper_name": "Body", "item_id": "1190"}],
                "submesh_bindings": [{"wrapper_name": "Body", "item_id": "1190", "id_base": "1190"}],
                "scalar_ranges": [{"parameter_name": "_roughness", "min": 0.2, "max": 0.8}],
                "color_parameters": [{"parameter_name": "_tintColor", "color_order": "rgba"}],
                "alpha_controls": [{"parameter_name": "_alphaBlend", "mode": "alpha_blend"}],
            }
        ],
        "sidecar_outputs": [
            {
                "target_path": "character/modelproperty/body.pac_xml",
                "authority_status": "ok",
                "bytes": 128,
                "sha256": "0" * 64,
                "pac_xml_edit_summary": {
                    "status": "source_compared",
                    "changed_from_source": True,
                    "structural_compare_status": "source_compared",
                    "wrapper_order_preserved": True,
                    "wrapper_item_ids_preserved": True,
                    "submesh_bindings_preserved": True,
                    "submesh_item_ids_preserved": True,
                    "parameter_abi_preserved": True,
                    "texture_ref_changes": [{"change": "changed", "parameter_name": "_overlayColorTexture"}],
                },
            }
        ],
        "unknown_material_response_parameters": [],
        "preview_settings": {
            "render_settings_source": "provided",
            "source_preview_mesh_parts": 1,
            "final_preview_mesh_parts": 1,
            "source_preview_visible_texture_sets": 1,
            "final_preview_visible_texture_sets": 1,
            "preview_visible_texture_delta": 0,
            "normal_y_policy": {
                "d3d11_normal_y_mode": "force_no_flip",
                "effective_preview_policy": "force_preserve_normal_y",
            },
            "require_source_owned_colors": False,
        },
    }
    report.update(overrides)
    return report


def _source_section(
    *,
    vertex_count: int = 3,
    face_count: int = 1,
    has_uvs: bool = True,
    has_normals: bool = True,
) -> dict[str, object]:
    return {
        "section_index": 0,
        "section_name": "SourceSection",
        "material_name": "SourceMaterial",
        "vertex_count": vertex_count,
        "face_count": face_count,
        "has_uvs": has_uvs,
        "has_normals": has_normals,
        "bounds_min": (0.0, 0.0, 0.0),
        "bounds_max": (1.0, 1.0, 0.0),
    }


class MaterialAuthorityReportCheckTests(unittest.TestCase):
    def test_passes_clean_report(self) -> None:
        result = check_material_authority_report(_report())

        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["errors"])
        self.assertEqual(1, result["counts"]["target_sections"])
        self.assertEqual(1, result["counts"]["sidecar_outputs"])
        self.assertEqual(1, result["counts"]["pac_xml_wrapper_order_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_submesh_binding_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_scalar_range_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_color_parameter_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_alpha_control_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_edit_summaries"])
        self.assertEqual(1, result["counts"]["pac_xml_texture_ref_change_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_structural_compare_rows"])
        self.assertEqual(1, result["counts"]["texture_conversion_sources"][".png"])
        self.assertEqual(1, result["counts"]["texture_conversion_roles"]["base_color"])

    def test_reviews_very_dark_visible_base_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            target = root / "character" / "texture" / "body.dds"
            target.parent.mkdir(parents=True)
            Image.new("RGBA", (4, 4), (28, 28, 28, 255)).save(target)
            report = _report(package_root=str(root))
            report["texture_outputs"][0]["bound_roles"] = ["Base / Color"]
            report["texture_outputs"][0]["bound_parameters"] = ["_overlayColorTexture"]

            result = check_material_authority_report(
                report,
                fail_on_risk_flags=(),
            )

        self.assertEqual("needs_review", result["status"])
        self.assertIn("dark_visible_color_output", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["dark_visible_color_output_rows"])
        self.assertTrue(any("no Material Authority brightness/tone adjustment was recorded" in warning for warning in result["warnings"]))

    def test_reviews_recorded_dark_visible_base_luma_without_package_file(self) -> None:
        report = _report(package_root="missing-package")
        report["texture_outputs"][0]["visible_luma_mean"] = 33.5

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("dark_visible_color_output", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["dark_visible_color_output_rows"])

    def test_dark_visible_base_warning_reports_recorded_brightness_adjustment(self) -> None:
        report = _report(package_root="missing-package")
        report["texture_outputs"][0]["visible_luma_mean"] = 33.5
        report["preview_settings"]["material_authority_export"] = {
            "auto_brightness_balance": 50.0,
            "dark_detail_lift": 20.0,
            "tone_contrast": -10.0,
        }

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertTrue(any("after recorded Material Authority brightness/tone adjustment" in warning for warning in result["warnings"]))

    def test_warns_when_pac_xml_binding_evidence_missing(self) -> None:
        report = _report(
            sidecar_reports=[
                {
                    "status": "ok",
                    "wrapper_order": [{"wrapper_name": "Body", "item_id": "1190"}],
                    "scalar_ranges": [],
                    "color_parameters": [],
                    "alpha_controls": [],
                }
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_submesh_bindings", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["pac_xml_submesh_binding_rows"])

    def test_warns_when_wrapper_order_differs_from_submesh_bindings(self) -> None:
        report = _report(
            sidecar_reports=[
                {
                    "path": "character/modelproperty/body.pac_xml",
                    "status": "ok",
                    "wrapper_order": [
                        {"wrapper_name": "Body", "item_id": "1190"},
                        {"wrapper_name": "Stale", "item_id": "1191"},
                    ],
                    "submesh_bindings": [{"wrapper_name": "Body", "item_id": "1190", "id_base": "1190"}],
                    "scalar_ranges": [],
                    "color_parameters": [],
                    "alpha_controls": [],
                }
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("submesh_binding_mismatch", result["review_risk_flags"])
        self.assertEqual(2, result["counts"]["pac_xml_wrapper_order_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_submesh_binding_rows"])

    def test_reviews_missing_core_report_evidence(self) -> None:
        report = _report(
            source_path="",
            package_root="",
            target_sections=[],
            texture_outputs=[],
            routing=[],
            sidecar_reports=[],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        for flag in (
            "missing_source_path",
            "missing_package_root",
            "missing_target_sections",
            "missing_texture_outputs",
            "missing_material_routing",
            "missing_pac_xml_sidecar_report",
        ):
            self.assertIn(flag, result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["target_sections"])
        self.assertEqual(0, result["counts"]["texture_outputs"])
        self.assertEqual(0, result["counts"]["routing_rows"])

    def test_reviews_incomplete_material_routing_rows(self) -> None:
        report = _report(
            routing=[
                {"parameter_name": "_overlayColorTexture"},
                {
                    "material_name": "Blade",
                    "role": "Base / Color",
                    "parameter_name": "_overlayColorTexture",
                    "status": "ready",
                    "binding_source": "generated",
                    "confidence": "exact",
                },
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("incomplete_material_routing", result["review_risk_flags"])
        self.assertIn("routing_output_missing", result["review_risk_flags"])
        self.assertEqual(2, result["counts"]["routing_incomplete_rows"])
        self.assertEqual(1, result["counts"]["routing_output_missing_rows"])

    def test_derives_texture_output_unhashed_risk(self) -> None:
        report = _report(
            risk_flags=[],
            texture_outputs=[
                {
                    "target_path": "character/texture/body.dds",
                    "source_path": "source.png",
                    "kind": "texture_generated",
                    "note": "Body base -> character/texture/body.dds",
                    "bytes": 0,
                    "sha256": "",
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "source_image_to_dds": True,
                        "bound_role_classes": ["base_color"],
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("texture_output_unhashed", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["texture_output_unhashed_rows"])

    def test_derives_missing_texture_payload_provenance_risk(self) -> None:
        report = _report(
            risk_flags=[],
            texture_outputs=[
                {
                    "target_path": "character/texture/body.dds",
                    "source_path": "body.dds",
                    "kind": "texture_generated",
                    "note": "Body base -> character/texture/body.dds",
                    "bytes": 128,
                    "sha256": "2" * 64,
                    "payload_source": "source_file",
                    "source_bytes": 0,
                    "source_sha256": "",
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "conversion_policy": {
                        "source_extension": ".dds",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "source_dds_passthrough": True,
                        "bound_role_classes": ["base_color"],
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("missing_texture_payload_provenance", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["texture_payload_provenance_missing_rows"])

    def test_accepts_source_file_texture_payload_provenance(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body.dds",
                    "source_path": "body.dds",
                    "kind": "texture_generated",
                    "note": "Body base -> character/texture/body.dds",
                    "bytes": 128,
                    "sha256": "2" * 64,
                    "payload_source": "source_file",
                    "source_bytes": 128,
                    "source_sha256": "2" * 64,
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "conversion_policy": {
                        "source_extension": ".dds",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "source_dds_passthrough": True,
                        "bound_role_classes": ["base_color"],
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                    },
                }
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertNotIn("missing_texture_payload_provenance", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["texture_payload_provenance_missing_rows"])

    def test_derives_stock_shared_risk_from_texture_outputs(self) -> None:
        report = _report(
            risk_flags=[],
            texture_outputs=[
                {
                    "target_path": "character/texture/cd_texturelayer_003_0203.dds",
                    "source_path": "source_base.png",
                    "kind": "texture_generated",
                    "note": "Blade base -> shared layer",
                    "bytes": 128,
                    "sha256": "2" * 64,
                    "stock_or_shared": True,
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {
                            "kind": "visible_color",
                            "channels": [
                                {"channel": "R", "semantic": "red"},
                                {"channel": "G", "semantic": "green"},
                                {"channel": "B", "semantic": "blue"},
                                {"channel": "A", "semantic": "alpha"},
                            ],
                        }
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "source_image_to_dds": True,
                        "bound_role_classes": ["base_color"],
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                        "channel_visualization_kinds": ["visible_color"],
                    },
                }
            ],
            routing=[
                {
                    "material_name": "Blade",
                    "role": "Base / Color",
                    "requested_texture_path": "character/texture/cd_texturelayer_003_0203.dds",
                    "resolved_texture_path": "character/texture/cd_texturelayer_003_0203.dds",
                    "status": "ready",
                    "binding_source": "generated",
                    "confidence": "exact",
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("stock_shared_texture_override", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["stock_shared_texture_output_rows"])

    def test_derives_pac_xml_review_flags_from_sidecar_rows(self) -> None:
        report = _report(
            risk_flags=[],
            sidecar_reports=[
                {
                    "status": "needs_review",
                    "wrapper_order": [{"wrapper_name": "Body", "item_id": "1190"}],
                    "submesh_bindings": [{"wrapper_name": "Body", "item_id": "1190", "id_base": "1190"}],
                    "inherited_influence_parameters": [{"parameter_name": "_detailMaskTexture"}],
                    "unknown_material_response_parameters": [{"parameter_name": "_wetnessBoost"}],
                    "scalar_ranges": [],
                    "color_parameters": [],
                    "alpha_controls": [],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("inherited_target_influence", result["review_risk_flags"])
        self.assertIn("unknown_material_response", result["review_risk_flags"])
        self.assertIn("missing_neutralization_actions", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["pac_xml_inherited_influence_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_unknown_material_response_rows"])
        self.assertEqual(0, result["counts"]["pac_xml_neutralization_action_rows"])

    def test_counts_pac_xml_neutralization_action_rows(self) -> None:
        report = _report(
            risk_flags=[],
            sidecar_reports=[
                {
                    "authority_contract": "true_source_authority",
                    "status": "needs_review",
                    "wrapper_order": [{"wrapper_name": "Body", "item_id": "1190"}],
                    "submesh_bindings": [{"wrapper_name": "Body", "item_id": "1190", "id_base": "1190"}],
                    "inherited_influence_parameters": [
                        {"wrapper_name": "Body", "parameter_name": "_detailMaskTexture", "item_id": "42", "index": "7"}
                    ],
                    "neutralization_actions": [
                        {
                            "wrapper_name": "Body",
                            "parameter_name": "_detailMaskTexture",
                            "item_id": "42",
                            "index": "7",
                            "action": "replace_with_source_owned_texture_or_neutral_default",
                            "action_status": "required",
                            "required": True,
                            "preserve_runtime_abi": True,
                        }
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("inherited_target_influence", result["review_risk_flags"])
        self.assertNotIn("missing_neutralization_actions", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_action_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_required_rows"])
        self.assertEqual(0, result["counts"]["pac_xml_neutralization_missing_rows"])

    def test_reviews_incomplete_or_unmatched_neutralization_actions(self) -> None:
        report = _report(
            risk_flags=[],
            sidecar_reports=[
                {
                    "authority_contract": "true_source_authority",
                    "status": "needs_review",
                    "wrapper_order": [{"wrapper_name": "Body", "item_id": "1190"}],
                    "submesh_bindings": [{"wrapper_name": "Body", "item_id": "1190", "id_base": "1190"}],
                    "inherited_influence_parameters": [
                        {"wrapper_name": "Body", "parameter_name": "_detailMaskTexture", "item_id": "42", "index": "7"},
                        {"wrapper_name": "Body", "parameter_name": "_tintColorR", "item_id": "43", "index": "8"},
                    ],
                    "neutralization_actions": [
                        {
                            "wrapper_name": "Body",
                            "parameter_name": "_detailMaskTexture",
                            "item_id": "42",
                            "index": "7",
                            "action": "",
                            "action_status": "required",
                            "required": False,
                            "preserve_runtime_abi": False,
                        },
                        {
                            "wrapper_name": "Body",
                            "parameter_name": "_unusedLayer",
                            "item_id": "99",
                            "index": "1",
                            "action": "neutralize_scalar_or_color_to_source_neutral_default",
                            "action_status": "required",
                            "required": True,
                            "preserve_runtime_abi": True,
                        },
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("neutralization_action_mismatch", result["review_risk_flags"])
        self.assertIn("neutralization_action_incomplete", result["review_risk_flags"])
        self.assertIn("neutralization_action_not_required", result["review_risk_flags"])
        self.assertIn("neutralization_abi_unproven", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_missing_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_incomplete_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_not_required_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_neutralization_abi_unproven_rows"])

    def test_fails_blocking_risk_and_invalid_dds(self) -> None:
        report = _report(
            risk_flags=["invalid_dds_payload", "base_texture_used_as_emissive", "missing_dds_mips"],
            texture_outputs=[
                {
                    "target_path": "character/texture/bad.dds",
                    "dds_validation": {
                        "status": "invalid",
                        "findings": [{"severity": "fatal", "code": "bad_magic"}],
                    },
                    "role_diagnostics": [],
                }
            ],
        )

        result = check_material_authority_report(report)

        self.assertEqual("failed", result["status"])
        self.assertIn("invalid_dds_payload", result["blocking_risk_flags"])
        self.assertIn("base_texture_used_as_emissive", result["blocking_risk_flags"])
        self.assertTrue(any("DDS validation failed" in error for error in result["errors"]))

    def test_texture_conversion_policy_source_route_diagnostics_drive_review(self) -> None:
        report = _report()
        conversion_policy = report["texture_outputs"][0]["conversion_policy"]
        conversion_policy["source_route_diagnostics"] = (
            {
                "severity": "warning",
                "code": "source_base_texture_bound_as_emissive",
                "material_name": "DiveSuit",
                "slot_kind": "emissive",
                "texture_path": "textures/5_DiveSuit_baseColor.jpeg",
            },
            {
                "severity": "warning",
                "code": "source_material_response_texture_bound_as_base",
                "material_name": "Blade",
                "slot_kind": "base",
                "texture_path": "blade_metallicRoughness.png",
            },
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("base_texture_used_as_emissive", result["review_risk_flags"])
        self.assertIn("visible_technical_role_conflict", result["review_risk_flags"])
        self.assertEqual(2, result["counts"]["texture_conversion_source_route_diagnostic_rows"])
        self.assertEqual(
            1,
            result["counts"]["texture_conversion_source_route_diagnostics"]["source_base_texture_bound_as_emissive"],
        )
        self.assertTrue(any("Texture conversion source-route diagnostic warning" in warning for warning in result["warnings"]))

    def test_review_flags_and_role_warnings_do_not_fail_when_allowed(self) -> None:
        report = _report(
            risk_flags=["missing_dds_mips", "normal_format_mismatch", "ambiguous_texture_role_binding"],
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "dds_validation": {
                        "status": "warning",
                        "findings": [{"severity": "warning", "code": "missing_mips"}],
                    },
                    "role_diagnostics": [
                        {"severity": "warning", "code": "normal_format_not_bc5"},
                    ],
                    "channel_visualization": [
                        {"kind": "normal_xy", "channels": [{"channel": "R", "semantic": "normal_x"}]},
                        {"kind": "packed_material_mask", "channels": [{"channel": "G", "semantic": "roughness"}]},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=("invalid_dds_payload",))

        self.assertEqual("needs_review", result["status"])
        self.assertEqual([], result["blocking_risk_flags"])
        self.assertIn("ambiguous_texture_role_binding", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["channel_visualizations"]["normal_xy"])
        self.assertEqual(1, result["counts"]["channel_visualizations"]["packed_material_mask"])
        self.assertTrue(result["warnings"])

    def test_reviews_missing_sidecar_output_evidence(self) -> None:
        missing_output = _report(sidecar_outputs=[])
        missing_hash = _report(
            sidecar_outputs=[
                {
                    "target_path": "character/modelproperty/body.pac_xml",
                    "authority_status": "ok",
                    "bytes": 0,
                    "sha256": "",
                }
            ]
        )

        missing_output_result = check_material_authority_report(missing_output, fail_on_risk_flags=())
        missing_hash_result = check_material_authority_report(missing_hash, fail_on_risk_flags=())

        self.assertEqual("needs_review", missing_output_result["status"])
        self.assertIn("missing_sidecar_output", missing_output_result["review_risk_flags"])
        self.assertEqual("needs_review", missing_hash_result["status"])
        self.assertIn("sidecar_output_unhashed", missing_hash_result["review_risk_flags"])

    def test_reviews_missing_pac_xml_edit_summary(self) -> None:
        report = _report(
            sidecar_outputs=[
                {
                    "target_path": "character/modelproperty/body.pac_xml",
                    "authority_status": "ok",
                    "bytes": 128,
                    "sha256": "0" * 64,
                }
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_pac_xml_edit_summary", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["pac_xml_edit_summaries"])
        self.assertEqual(1, result["counts"]["pac_xml_structural_compare_missing"])

    def test_reviews_pac_xml_structural_abi_drift(self) -> None:
        report = _report(
            sidecar_outputs=[
                {
                    "target_path": "character/modelproperty/body.pac_xml",
                    "authority_status": "needs_review",
                    "bytes": 128,
                    "sha256": "0" * 64,
                    "pac_xml_edit_summary": {
                        "status": "source_compared",
                        "changed_from_source": True,
                        "structural_compare_status": "source_compared",
                        "wrapper_order_preserved": False,
                        "wrapper_item_ids_preserved": False,
                        "submesh_bindings_preserved": False,
                        "submesh_item_ids_preserved": False,
                        "parameter_abi_preserved": False,
                        "texture_ref_changes": [],
                    },
                }
            ]
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("pac_xml_wrapper_order_changed", result["review_risk_flags"])
        self.assertIn("pac_xml_submesh_binding_changed", result["review_risk_flags"])
        self.assertIn("pac_xml_item_id_changed", result["review_risk_flags"])
        self.assertIn("pac_xml_parameter_abi_changed", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["pac_xml_structural_compare_rows"])
        self.assertEqual(1, result["counts"]["pac_xml_wrapper_order_changed"])
        self.assertEqual(1, result["counts"]["pac_xml_submesh_binding_changed"])
        self.assertEqual(1, result["counts"]["pac_xml_item_id_changed"])
        self.assertEqual(1, result["counts"]["pac_xml_parameter_abi_changed"])

    def test_reviews_material_texture_missing_channel_visualization(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "bound_roles": ["Normal"],
                    "bound_parameters": ["_normalTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC5_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [{"severity": "info", "code": "normal_y_policy"}],
                    "channel_visualization": [],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_channel_visualization", result["review_risk_flags"])
        self.assertTrue(any("Channel visualization missing" in warning for warning in result["warnings"]))

    def test_reviews_generated_texture_missing_conversion_evidence(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body.dds",
                    "kind": "texture_generated",
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_texture_conversion_policy", result["review_risk_flags"])
        self.assertIn("missing_texture_conversion_note", result["review_risk_flags"])
        self.assertTrue(any("conversion policy evidence" in warning for warning in result["warnings"]))

    def test_reviews_texture_conversion_policy_semantic_mismatches(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "source_path": "body_normal.png",
                    "kind": "texture_generated",
                    "note": "Body normal -> character/texture/body_n.dds",
                    "bound_roles": ["Normal"],
                    "bound_parameters": ["_normalTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC5_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [{"severity": "info", "code": "normal_y_policy"}],
                    "channel_visualization": [{"kind": "normal_xy", "channels": [{"semantic": "normal_x"}]}],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["base_color"],
                        "normal_y_policy_required": False,
                        "channel_order": "block_linear",
                    },
                },
                {
                    "target_path": "character/texture/body_ma.dds",
                    "source_path": "body_mask.png",
                    "kind": "texture_generated",
                    "note": "Body mask -> character/texture/body_ma.dds",
                    "bound_roles": ["Material / Mask"],
                    "bound_parameters": ["_colorBlendingMaskTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {"kind": "packed_material_mask", "channels": [{"semantic": "roughness"}]},
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["material"],
                        "normal_y_policy_required": False,
                        "channel_order": "block_color",
                        "channel_visualization_kinds": [],
                        "packed_channel_semantics": [],
                    },
                },
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("texture_conversion_role_mismatch", result["review_risk_flags"])
        self.assertIn("missing_normal_conversion_policy", result["review_risk_flags"])
        self.assertIn("missing_packed_mask_conversion_policy", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["texture_conversion_roles"]["base_color"])
        self.assertEqual(1, result["counts"]["texture_conversion_roles"]["material"])
        self.assertTrue(any("role mismatch" in warning for warning in result["warnings"]))

    def test_reviews_spec_gloss_material_output_missing_conversion_provenance(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_ma.dds",
                    "source_path": "body_specGloss.png",
                    "kind": "texture_generated",
                    "note": "Spec/gloss material mask -> character/texture/body_ma.dds",
                    "bound_roles": ["Material / Mask"],
                    "bound_parameters": ["_colorBlendingMaskTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {
                            "kind": "packed_material_mask",
                            "channels": [
                                {"channel": "R", "semantic": "ao"},
                                {"channel": "G", "semantic": "roughness"},
                                {"channel": "B", "semantic": "metallic"},
                                {"channel": "A", "semantic": "alpha"},
                            ],
                        }
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["material"],
                        "source_workflows": ["specular_glossiness"],
                        "source_derived_channels": ["roughness"],
                        "source_image_to_dds": True,
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                        "normal_y_policy_required": False,
                        "channel_visualization_kinds": ["packed_material_mask"],
                        "packed_channel_semantics": [
                            {"channel": "R", "semantic": "ao"},
                            {"channel": "G", "semantic": "roughness"},
                            {"channel": "B", "semantic": "metallic"},
                            {"channel": "A", "semantic": "alpha"},
                        ],
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_spec_gloss_conversion_policy", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["spec_gloss_conversion_policy_rows"])
        self.assertEqual(1, result["counts"]["spec_gloss_conversion_policy_missing"])
        self.assertTrue(any("Specular-glossiness material output" in warning for warning in result["warnings"]))

    def test_reviews_visible_color_channel_order_visualization_mismatch(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_base.dds",
                    "source_path": "body_base.png",
                    "kind": "texture_generated",
                    "note": "Body base -> character/texture/body_base.dds",
                    "bound_roles": ["Base Color"],
                    "bound_parameters": ["_overlayColorTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "B8G8R8A8_UNORM",
                        "channel_order": "bgra",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [{"severity": "info", "code": "uncompressed_channel_order"}],
                    "channel_visualization": [
                        {
                            "kind": "visible_color",
                            "channel_order": "bgra",
                            "channels": [
                                {"channel": "R", "semantic": "red"},
                                {"channel": "G", "semantic": "green"},
                                {"channel": "B", "semantic": "blue"},
                                {"channel": "A", "semantic": "alpha"},
                            ],
                        }
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["base_color"],
                        "source_image_to_dds": True,
                        "dds_format": "B8G8R8A8_UNORM",
                        "channel_order": "bgra",
                        "mip_count": 3,
                        "normal_y_policy_required": False,
                        "channel_visualization_kinds": ["visible_color"],
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("channel_order_visualization_mismatch", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["channel_order_visualization_mismatches"])
        self.assertTrue(any("channel order" in warning for warning in result["warnings"]))

    def test_accepts_emissive_intensity_control_map_without_visible_color_format_mismatch(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/gem_base_red_emi.dds",
                    "source_path": "gem_emi.png",
                    "kind": "texture_generated",
                    "note": "Gem emissive control -> character/texture/gem_base_red_emi.dds",
                    "bytes": 128,
                    "sha256": "1" * 64,
                    "payload_source": "inline_payload",
                    "bound_roles": ["Emissive"],
                    "bound_parameters": ["_emissiveIntensityTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC5_UNORM",
                        "channel_order": "block_linear",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {
                            "kind": "emissive_control",
                            "channels": [
                                {"channel": "R", "semantic": "emissive_intensity"},
                                {"channel": "G", "semantic": "emissive_progress_or_mask"},
                            ],
                        }
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["emissive_control"],
                        "source_image_to_dds": True,
                        "dds_format": "BC5_UNORM",
                        "channel_order": "block_linear",
                        "mip_count": 3,
                        "normal_y_policy_required": False,
                        "channel_visualization_kinds": ["emissive_control"],
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertNotIn("visible_color_format_mismatch", result["review_risk_flags"])
        self.assertNotIn("texture_conversion_role_mismatch", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["texture_conversion_roles"]["emissive_control"])
        self.assertEqual(1, result["counts"]["channel_visualizations"]["emissive_control"])

    def test_reviews_packed_material_mask_semantics_mismatch(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_ma.dds",
                    "source_path": "body_mask.png",
                    "kind": "texture_generated",
                    "note": "Body mask -> character/texture/body_ma.dds",
                    "bound_roles": ["Material / Mask"],
                    "bound_parameters": ["_colorBlendingMaskTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {
                            "kind": "packed_material_mask",
                            "channels": [
                                {"channel": "R", "semantic": "roughness"},
                            ],
                        }
                    ],
                    "conversion_policy": {
                        "source_extension": ".png",
                        "payload_kind": "texture_generated",
                        "generated": True,
                        "bound_role_classes": ["material"],
                        "source_image_to_dds": True,
                        "dds_format": "BC7_UNORM",
                        "channel_order": "block_color",
                        "mip_count": 3,
                        "normal_y_policy_required": False,
                        "channel_visualization_kinds": ["packed_material_mask"],
                        "packed_channel_semantics": [
                            {"channel": "R", "semantic": "ao"},
                            {"channel": "G", "semantic": "roughness"},
                            {"channel": "B", "semantic": "metallic"},
                            {"channel": "A", "semantic": "alpha"},
                        ],
                    },
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("packed_mask_semantics_mismatch", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["packed_mask_semantics_mismatches"])
        self.assertTrue(any("Packed material-mask" in warning for warning in result["warnings"]))

    def test_reviews_dds_validation_missing_dimensions_or_format(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body.dds",
                    "dds_validation": {
                        "status": "valid",
                        "width": 0,
                        "height": 0,
                        "texconv_format": "",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_dds_dimensions", result["review_risk_flags"])
        self.assertIn("missing_dds_format", result["review_risk_flags"])

    def test_reviews_normal_output_missing_normal_y_policy(self) -> None:
        report = _report(
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "bound_roles": ["Normal"],
                    "bound_parameters": ["_normalTexture"],
                    "dds_validation": {
                        "status": "valid",
                        "width": 4,
                        "height": 4,
                        "texconv_format": "BC5_UNORM",
                        "findings": [{"severity": "info", "code": "payload_size_valid"}],
                    },
                    "role_diagnostics": [],
                    "channel_visualization": [
                        {"kind": "normal_xy", "channels": [{"channel": "R", "semantic": "normal_x"}]},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_normal_y_policy", result["review_risk_flags"])
        self.assertTrue(any("normal-Y policy" in warning for warning in result["warnings"]))

    def test_reviews_missing_preview_settings(self) -> None:
        result = check_material_authority_report(_report(preview_settings={}), fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_preview_settings", result["review_risk_flags"])
        self.assertIn("missing_normal_y_policy", result["review_risk_flags"])
        self.assertTrue(any("preview settings" in warning for warning in result["warnings"]))

    def test_counts_source_material_diagnostics(self) -> None:
        report = _report(
            risk_flags=["source_alpha_missing_opacity"],
            source_materials=[
                {
                    "material_name": "Glass",
                    "vertex_color_factor": (0.8, 0.7, 0.4),
                    "vertex_alpha": (0.6, 0.3),
                    "material_classification": [{"class": "glass_crystal", "confidence": 0.8}],
                    "diagnostics": [
                        {"severity": "warning", "code": "source_alpha_without_opacity_texture"},
                        {"severity": "info", "code": "source_missing_roughness"},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertEqual(1, result["counts"]["source_materials"])
        self.assertEqual(1, result["counts"]["source_material_class_rows"])
        self.assertEqual(1, result["counts"]["source_material_classes"]["glass_crystal"])
        self.assertEqual(1, result["counts"]["source_vertex_color_materials"])
        self.assertEqual(1, result["counts"]["source_vertex_alpha_materials"])
        self.assertEqual(1, result["counts"]["source_preview_mesh_parts"])
        self.assertEqual(1, result["counts"]["final_preview_mesh_parts"])
        self.assertEqual(1, result["counts"]["source_preview_visible_texture_sets"])
        self.assertEqual(1, result["counts"]["final_preview_visible_texture_sets"])
        self.assertEqual(0, result["counts"]["preview_visible_texture_delta"])
        self.assertEqual(1, result["counts"]["source_diagnostics"]["source_alpha_without_opacity_texture"])
        self.assertEqual(0, result["counts"]["source_materials_missing_alpha_diagnostics"])
        self.assertNotIn("missing_source_alpha_diagnostics", result["review_risk_flags"])
        self.assertTrue(any("Source material diagnostic warning" in warning for warning in result["warnings"]))

    def test_maps_external_audit_route_diagnostics_from_channel_diagnostics(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Misrouted Source",
                    "detected_channels": ["base_color", "normal", "emissive", "roughness", "metalness"],
                    "missing_channels": [],
                    "material_classification": [{"class": "metal", "confidence": 0.8}],
                    "sections": [_source_section()],
                    "channel_diagnostics": [
                        {"severity": "warning", "code": "source_base_texture_bound_as_emissive"},
                        {"severity": "warning", "code": "source_spec_gloss_texture_bound_as_base"},
                        {"severity": "warning", "code": "source_material_response_texture_bound_as_base"},
                        {"severity": "warning", "code": "source_base_texture_bound_as_normal"},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report)

        self.assertEqual("failed", result["status"])
        self.assertIn("base_texture_used_as_emissive", result["blocking_risk_flags"])
        self.assertIn("source_spec_gloss_base_conflict", result["blocking_risk_flags"])
        self.assertIn("visible_technical_role_conflict", result["blocking_risk_flags"])
        self.assertIn("normal_slot_suspicious", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_diagnostics"]["source_base_texture_bound_as_emissive"])
        self.assertEqual(1, result["counts"]["source_diagnostics"]["source_spec_gloss_texture_bound_as_base"])
        self.assertEqual(0, result["counts"]["source_materials_missing_channel_diagnostics"])

    def test_counts_complete_source_channel_evidence(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Cloth",
                    "alpha_mode": "OPAQUE",
                    "channel_profile": {
                        "workflow": "metallic_roughness",
                        "detected_channels": ["base_color", "normal"],
                        "missing_channels": ["emissive", "roughness", "metalness"],
                    },
                    "detected_channels": ["base_color", "normal"],
                    "missing_channels": ["emissive", "roughness", "metalness"],
                    "material_classification": [{"class": "cloth", "confidence": 0.8}],
                    "diagnostics": [
                        {"severity": "info", "code": "source_missing_emissive"},
                        {"severity": "info", "code": "source_missing_roughness"},
                        {"severity": "info", "code": "source_missing_metalness"},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertEqual(1, result["counts"]["source_channel_profile_rows"])
        self.assertEqual(1, result["counts"]["source_detected_channels"]["base_color"])
        self.assertEqual(1, result["counts"]["source_missing_channels"]["emissive"])
        self.assertEqual(0, result["counts"]["source_materials_missing_channel_diagnostics"])
        self.assertEqual(0, result["counts"]["source_materials_missing_alpha_diagnostics"])
        self.assertEqual(0, result["counts"]["source_materials_missing_emissive_diagnostics"])
        self.assertEqual(0, result["counts"]["source_materials_missing_roughness_metalness_diagnostics"])
        self.assertNotIn("missing_source_channel_diagnostics", result["review_risk_flags"])
        self.assertNotIn("missing_source_emissive_diagnostics", result["review_risk_flags"])
        self.assertIn("source_missing_roughness_metalness", result["review_risk_flags"])

    def test_counts_scalar_roughness_metalness_as_source_channel_evidence(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "ScalarMetal",
                    "channel_profile": {
                        "workflow": "metallic_roughness",
                        "detected_channels": ["base_color_scalar", "roughness_scalar", "metalness_scalar"],
                        "missing_channels": ["emissive"],
                    },
                    "detected_channels": ["base_color_scalar", "roughness_scalar", "metalness_scalar"],
                    "missing_channels": ["emissive"],
                    "material_classification": [{"class": "metal", "confidence": 0.8}],
                    "sections": [_source_section()],
                    "section_count": 1,
                    "diagnostics": [{"severity": "info", "code": "source_missing_emissive"}],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("passed", result["status"])
        self.assertEqual(0, result["counts"]["source_materials_missing_roughness_metalness_diagnostics"])
        self.assertNotIn("missing_source_roughness_metalness_diagnostics", result["review_risk_flags"])
        self.assertNotIn("source_missing_roughness_metalness", result["review_risk_flags"])

    def test_reviews_missing_or_empty_source_material_sections(self) -> None:
        base_material = {
            "channel_profile": {
                "workflow": "metallic_roughness",
                "detected_channels": ["base_color", "roughness", "metalness"],
                "missing_channels": ["emissive"],
            },
            "detected_channels": ["base_color", "roughness", "metalness"],
            "missing_channels": ["emissive"],
            "material_classification": [{"class": "metal", "confidence": 0.8}],
            "diagnostics": [{"severity": "info", "code": "source_missing_emissive"}],
        }
        report = _report(
            source_materials=[
                {"material_name": "NoSections", **base_material},
                {
                    "material_name": "EmptySection",
                    **base_material,
                    "sections": [_source_section(vertex_count=0, face_count=0, has_uvs=False, has_normals=False)],
                    "section_count": 1,
                },
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_source_material_sections", result["review_risk_flags"])
        self.assertIn("source_material_section_missing_geometry", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_material_section_rows"])
        self.assertEqual(1, result["counts"]["source_materials_missing_section_evidence"])
        self.assertEqual(1, result["counts"]["source_material_sections_missing_geometry"])
        self.assertEqual(0, result["counts"]["source_section_vertex_count"])
        self.assertEqual(0, result["counts"]["source_section_face_count"])
        self.assertEqual(1, result["counts"]["source_sections_missing_uvs"])
        self.assertEqual(1, result["counts"]["source_sections_missing_normals"])

    def test_reviews_missing_source_channel_diagnostic_evidence(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Glass",
                    "alpha_mode": "BLEND",
                    "material_classification": [{"class": "glass_crystal", "confidence": 0.8}],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_source_channel_diagnostics", result["review_risk_flags"])
        self.assertIn("missing_source_alpha_diagnostics", result["review_risk_flags"])
        self.assertIn("missing_source_emissive_diagnostics", result["review_risk_flags"])
        self.assertIn("missing_source_roughness_metalness_diagnostics", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_materials_missing_channel_diagnostics"])
        self.assertEqual(1, result["counts"]["source_materials_missing_alpha_diagnostics"])
        self.assertEqual(1, result["counts"]["source_materials_missing_emissive_diagnostics"])
        self.assertEqual(1, result["counts"]["source_materials_missing_roughness_metalness_diagnostics"])
        self.assertTrue(any("alpha/opacity diagnostics missing" in warning for warning in result["warnings"]))

    def test_derives_preview_export_mismatch_from_preview_counts(self) -> None:
        report = _report(
            risk_flags=[],
            warnings=[],
            preview_settings={
                "source_preview_mesh_parts": 2,
                "final_preview_mesh_parts": 1,
                "source_preview_visible_texture_sets": 2,
                "final_preview_visible_texture_sets": 1,
                "normal_y_policy": {
                    "d3d11_normal_y_mode": "force_no_flip",
                    "effective_preview_policy": "force_preserve_normal_y",
                },
            },
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("preview_export_mismatch", result["review_risk_flags"])
        self.assertEqual(2, result["counts"]["source_preview_visible_texture_sets"])
        self.assertEqual(1, result["counts"]["final_preview_visible_texture_sets"])
        self.assertEqual(1, result["counts"]["preview_visible_texture_delta"])
        self.assertTrue(any("Source preview has more visible texture sets" in warning for warning in result["warnings"]))

    def test_reviews_missing_preview_mesh_or_texture_evidence(self) -> None:
        report = _report(
            preview_settings={
                "normal_y_policy": {
                    "d3d11_normal_y_mode": "force_no_flip",
                    "effective_preview_policy": "force_preserve_normal_y",
                },
            },
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_source_preview_evidence", result["review_risk_flags"])
        self.assertIn("missing_final_preview_evidence", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["source_preview_visible_texture_sets"])
        self.assertTrue(any("source preview mesh/texture evidence" in warning for warning in result["warnings"]))

    def test_reviews_source_material_missing_classification(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Unclassified",
                    "diagnostics": [],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_source_material_classification", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["source_material_class_rows"])
        self.assertTrue(any("classification missing" in warning for warning in result["warnings"]))

    def test_reviews_missing_source_texture_fact_rows(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Textured",
                    "preview_texture_path": "source_base.png",
                    "material_classification": [{"class": "metal", "confidence": 0.8}],
                    "sections": [_source_section()],
                    "detected_channels": ["base_color"],
                    "missing_channels": ["emissive"],
                    "diagnostics": [{"severity": "info", "code": "source_missing_emissive"}],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("missing_source_texture_facts", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_materials_missing_texture_facts"])

    def test_reviews_missing_source_texture_fact_fields(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Textured",
                    "preview_texture_path": "source_base.png",
                    "material_classification": [{"class": "metal", "confidence": 0.8}],
                    "sections": [_source_section()],
                    "detected_channels": ["base_color"],
                    "missing_channels": ["emissive"],
                    "diagnostics": [{"severity": "info", "code": "source_missing_emissive"}],
                    "texture_facts": [
                        {
                            "slot_kind": "base",
                            "texture_path": "source_base.png",
                            "image_format": "",
                            "resolution": (),
                            "color_space": "",
                        }
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertIn("source_texture_missing_format", result["review_risk_flags"])
        self.assertIn("source_texture_missing_color_space", result["review_risk_flags"])
        self.assertIn("source_texture_missing_resolution", result["review_risk_flags"])
        self.assertIn("source_texture_missing_channel_stats", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_texture_fact_rows"])
        self.assertEqual(1, result["counts"]["source_textures_missing_format"])
        self.assertEqual(1, result["counts"]["source_textures_missing_color_space"])
        self.assertEqual(1, result["counts"]["source_textures_missing_resolution"])
        self.assertEqual(1, result["counts"]["source_textures_missing_channel_stats"])

    def test_accepts_complete_source_texture_facts(self) -> None:
        report = _report(
            source_materials=[
                {
                    "material_name": "Textured",
                    "preview_texture_path": "source_base.png",
                    "material_classification": [{"class": "metal", "confidence": 0.8}],
                    "sections": [_source_section()],
                    "detected_channels": ["base_color", "roughness", "metalness"],
                    "missing_channels": ["emissive"],
                    "diagnostics": [{"severity": "info", "code": "source_missing_emissive"}],
                    "texture_facts": [
                        {
                            "slot_kind": "base",
                            "texture_path": "source_base.png",
                            "image_format": "png",
                            "resolution": (4, 4),
                            "color_space": "srgb",
                            "channel_stats": (("r_mean", 0.5), ("g_mean", 0.5), ("b_mean", 0.5), ("a_mean", 1.0)),
                        }
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertNotIn("missing_source_texture_facts", result["review_risk_flags"])
        self.assertNotIn("source_texture_missing_format", result["review_risk_flags"])
        self.assertNotIn("source_texture_missing_color_space", result["review_risk_flags"])
        self.assertNotIn("source_texture_missing_resolution", result["review_risk_flags"])
        self.assertNotIn("source_texture_missing_channel_stats", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["source_texture_fact_rows"])
        self.assertEqual(0, result["counts"]["source_textures_missing_channel_stats"])

    def test_derives_blockers_from_report_rows_when_risk_flags_missing(self) -> None:
        report = _report(
            risk_flags=[],
            preflight_errors=["source contract failed"],
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "dds_validation": {
                        "status": "valid",
                        "findings": [{"severity": "fatal", "code": "payload_truncated"}],
                    },
                    "role_diagnostics": [
                        {"severity": "warning", "code": "normal_format_not_bc5"},
                        {"severity": "warning", "code": "texture_bound_to_visible_and_technical_roles"},
                    ],
                }
            ],
            source_materials=[
                {
                    "material_name": "Glass",
                    "material_classification": [{"class": "glass_crystal", "confidence": 0.8}],
                    "missing_channels": ["roughness", "metalness"],
                    "diagnostics": [
                        {"severity": "warning", "code": "source_missing_base_color"},
                        {"severity": "warning", "code": "source_spec_gloss_texture_as_base_color"},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report)

        self.assertEqual("failed", result["status"])
        self.assertEqual([], result["source_risk_flags"])
        self.assertIn("preflight_blockers", result["derived_risk_flags"])
        self.assertIn("truncated_dds_payload", result["derived_risk_flags"])
        self.assertIn("normal_format_mismatch", result["blocking_risk_flags"])
        self.assertIn("visible_technical_role_conflict", result["blocking_risk_flags"])
        self.assertIn("source_missing_base_color", result["blocking_risk_flags"])
        self.assertIn("source_spec_gloss_base_conflict", result["blocking_risk_flags"])
        self.assertIn("source_missing_roughness_metalness", result["review_risk_flags"])

    def test_derives_routing_risks_from_routing_rows_when_flags_missing(self) -> None:
        report = _report(
            risk_flags=[],
            routing=[
                {
                    "material_name": "BladeMissing",
                    "role": "Base / Color",
                    "parameter_name": "_overlayColorTexture",
                    "requested_texture_path": "character/texture/missing_base.dds",
                    "status": "missing_dds",
                    "binding_source": "missing",
                    "confidence": "exact",
                },
                {
                    "material_name": "BladeBasename",
                    "role": "Base / Color",
                    "parameter_name": "_overlayColorTexture",
                    "requested_texture_path": "character/texture/folder_a/blade_base.dds",
                    "resolved_texture_path": "character/texture/folder_b/blade_base.dds",
                    "status": "ready",
                    "binding_source": "basename_diagnostic",
                    "confidence": "basename",
                },
                {
                    "material_name": "BladeStock",
                    "role": "Base / Color",
                    "parameter_name": "_overlayColorTexture",
                    "requested_texture_path": "character/texture/cd_texturelayer_003_0203.dds",
                    "resolved_texture_path": "character/texture/cd_texturelayer_003_0203.dds",
                    "status": "ready",
                    "binding_source": "generated",
                    "confidence": "exact",
                },
            ],
        )

        result = check_material_authority_report(report)

        self.assertEqual("failed", result["status"])
        self.assertIn("missing_final_dds", result["blocking_risk_flags"])
        self.assertIn("path_mismatch_basename_only", result["review_risk_flags"])
        self.assertIn("stock_shared_texture_override", result["review_risk_flags"])
        self.assertIn("routing_output_missing", result["review_risk_flags"])
        self.assertEqual(1, result["counts"]["routing_statuses"]["missing_dds"])
        self.assertEqual(2, result["counts"]["routing_statuses"]["ready"])
        self.assertEqual(1, result["counts"]["routing_binding_sources"]["basename_diagnostic"])
        self.assertEqual(1, result["counts"]["routing_confidences"]["basename"])
        self.assertEqual(1, result["counts"]["routing_output_missing_rows"])
        self.assertTrue(any("basename-only diagnostic" in warning for warning in result["warnings"]))

    def test_generated_ready_routes_must_match_texture_outputs(self) -> None:
        report = _report(
            risk_flags=[],
            routing=[
                {
                    "material_name": "BladeGenerated",
                    "role": "Base / Color",
                    "parameter_name": "_overlayColorTexture",
                    "requested_texture_path": "character/texture/body.dds",
                    "resolved_texture_path": "character/texture/body.dds",
                    "status": "ready",
                    "binding_source": "generated",
                    "confidence": "exact",
                },
                {
                    "material_name": "BladeOriginal",
                    "role": "Normal",
                    "parameter_name": "_normalTexture",
                    "requested_texture_path": "character/texture/original_n.dds",
                    "resolved_texture_path": "character/texture/original_n.dds",
                    "status": "ready",
                    "binding_source": "original",
                    "confidence": "exact",
                },
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertNotIn("routing_output_missing", result["review_risk_flags"])
        self.assertEqual(0, result["counts"]["routing_output_missing_rows"])

    def test_derives_review_flags_from_report_rows_when_allowed(self) -> None:
        report = _report(
            risk_flags=[],
            warnings=["orphan DDS not referenced by parsed material sidecar"],
            unknown_material_response_parameters=[{"parameter_name": "_mystery"}],
            preview_settings={"require_source_owned_colors": True},
            sidecar_reports=[],
            texture_outputs=[
                {
                    "target_path": "character/texture/body_n.dds",
                    "dds_validation": {
                        "status": "warning",
                        "requires_pathc": True,
                        "findings": [{"severity": "warning", "code": "missing_mips"}],
                    },
                    "role_diagnostics": [
                        {"severity": "warning", "code": "normal_y_policy_unconfirmed"},
                        {"severity": "info", "code": "multi_role_texture_binding"},
                    ],
                }
            ],
        )

        result = check_material_authority_report(report, fail_on_risk_flags=())

        self.assertEqual("needs_review", result["status"])
        self.assertIn("missing_dds_mips", result["review_risk_flags"])
        self.assertIn("dds_requires_pathc", result["review_risk_flags"])
        self.assertIn("normal_y_policy_unconfirmed", result["review_risk_flags"])
        self.assertIn("ambiguous_texture_role_binding", result["review_risk_flags"])
        self.assertIn("unknown_material_response", result["review_risk_flags"])
        self.assertIn("missing_material_sidecar", result["review_risk_flags"])
        self.assertIn("orphan_dds", result["review_risk_flags"])

    def test_loads_report_from_package_root_and_cli_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / MATERIAL_AUTHORITY_REPORT_FILENAME
            report_path.write_text(json.dumps(_report(risk_flags=["invalid_dds_payload"])), encoding="utf-8")

            result = check_material_authority_report_path(root)

            self.assertEqual("failed", result["status"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(1, check_report_main([str(root)]))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, check_report_main([str(root), "--warn-only"]))

    def test_cli_can_fail_or_allow_review_conversion_policy_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / MATERIAL_AUTHORITY_REPORT_FILENAME
            out_json = root / "check.json"
            report_path.write_text(
                json.dumps(
                    _report(
                        texture_outputs=[
                            {
                                "target_path": "character/texture/body.dds",
                                "kind": "texture_generated",
                                "dds_validation": {
                                    "status": "valid",
                                    "width": 4,
                                    "height": 4,
                                    "texconv_format": "BC7_UNORM",
                                    "findings": [{"severity": "info", "code": "payload_size_valid"}],
                                },
                                "role_diagnostics": [],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    1,
                    check_report_main(
                        [
                            str(root),
                            "--fail-on",
                            "missing_texture_conversion_policy",
                            "--out-json",
                            str(out_json),
                        ]
                    ),
                )
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual("failed", data["status"])
            self.assertIn("missing_texture_conversion_policy", data["blocking_risk_flags"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    check_report_main(
                        [
                            str(root),
                            "--fail-on",
                            "missing_texture_conversion_policy",
                            "--allow-risk",
                            "missing_texture_conversion_policy",
                        ]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
