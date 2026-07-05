from __future__ import annotations

import unittest

from cdmw.ui.texture_workflow.asset_authoring_panel import (
    material_maker_export_report_text,
    material_maker_export_status_text,
    openimageio_task_report_text,
    openimageio_task_status_text,
)


class TextureWorkflowAssetAuthoringPanelTests(unittest.TestCase):
    def test_material_maker_status_summarizes_mapped_channels(self) -> None:
        status, is_error = material_maker_export_status_text(
            {
                "status": "ok",
                "export_report": {"status": "ok", "project_path": "wood.mm", "output_dir": "exports"},
                "texture_set_report": {
                    "status": "ok",
                    "channels": {
                        "normal": {"path": "exports/wood_normal.png", "profile_hint": "normal_bc5"},
                        "base_color": {"path": "exports/wood_albedo.png", "profile_hint": "color_default"},
                    },
                },
            }
        )

        self.assertFalse(is_error)
        self.assertEqual("Material Maker export complete. 2 mapped channel(s): base_color, normal.", status)

    def test_material_maker_status_reports_unconfigured_export_as_error(self) -> None:
        status, is_error = material_maker_export_status_text(
            {
                "status": "cli_export_unconfigured",
                "export_report": {
                    "status": "cli_export_unconfigured",
                    "message": "Configure asset_authoring/material_maker_export_template before running Material Maker export.",
                },
                "texture_set_report": None,
            }
        )

        self.assertTrue(is_error)
        self.assertIn("asset_authoring/material_maker_export_template", status)

    def test_material_maker_report_lists_channels_and_warnings(self) -> None:
        report = material_maker_export_report_text(
            {
                "status": "ok",
                "export_report": {"status": "ok", "project_path": "wood.mm", "output_dir": "exports"},
                "texture_set_report": {
                    "status": "ok",
                    "channels": {"ao": {"path": "exports/wood_ao.png", "profile_hint": "scalar_high_precision_bc4"}},
                    "warnings": ["Duplicate normal map skipped: wood_normal_copy.png"],
                    "unmapped": ["exports/readme.txt"],
                },
            }
        )

        self.assertIn("Project: wood.mm", report)
        self.assertIn("ao: exports/wood_ao.png (scalar_high_precision_bc4)", report)
        self.assertIn("Duplicate normal map skipped", report)
        self.assertIn("exports/readme.txt", report)

    def test_openimageio_metadata_report_summarizes_image_properties(self) -> None:
        status, is_error = openimageio_task_status_text(
            {
                "status": "ok",
                "source_path": "source.exr",
                "metadata": {
                    "width": 1024,
                    "height": 512,
                    "channel_count": 4,
                    "bit_depth": 16,
                    "color_space": "linear",
                },
            },
            "metadata",
        )
        report = openimageio_task_report_text(
            {
                "status": "ok",
                "source_path": "source.exr",
                "metadata": {
                    "width": 1024,
                    "height": 512,
                    "channel_count": 4,
                    "bit_depth": 16,
                    "color_space": "linear",
                },
            },
            "metadata",
        )

        self.assertFalse(is_error)
        self.assertEqual("OpenImageIO metadata complete.", status)
        self.assertIn("Metadata: 1024 x 512, 4 channel(s), 16-bit, linear", report)

    def test_openimageio_diff_different_is_review_result_not_error(self) -> None:
        status, is_error = openimageio_task_status_text(
            {"status": "different", "left_path": "left.png", "right_path": "right.png", "returncode": 1},
            "diff",
        )

        self.assertFalse(is_error)
        self.assertEqual("OpenImageIO diff complete. Images differ.", status)


if __name__ == "__main__":
    unittest.main()
