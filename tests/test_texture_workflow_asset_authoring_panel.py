from __future__ import annotations

import unittest

from cdmw.ui.texture_workflow.asset_authoring_panel import (
    openimageio_task_report_text,
    openimageio_task_status_text,
)


class TextureWorkflowAssetAuthoringPanelTests(unittest.TestCase):
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
