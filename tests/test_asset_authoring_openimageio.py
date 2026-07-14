from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cdmw.services.asset_authoring_service import (
    ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA,
    AssetAuthoringService,
)


class AssetAuthoringOpenImageIOTests(unittest.TestCase):
    def test_openimageio_source_report_marks_missing_helper_without_blocking_existing_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.png"
            source.write_bytes(b"png")
            report = AssetAuthoringService().openimageio_source_report(
                source,
                {"openimageio": Path(temp_dir) / "missing-oiiotool.exe"},
            )

        self.assertEqual(ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA, report["schema"])
        self.assertEqual("helper_unavailable", report["status"])
        self.assertTrue(report["existing_workflow_unaffected"])
        self.assertFalse(report["can_convert"])
        self.assertEqual([], report["metadata_argv"])
        json.dumps(report)

    def test_openimageio_convert_and_diff_commands_use_configured_oiiotool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "oiiotool.exe"
            source = root / "source.psd"
            output = root / "converted.png"
            rebuilt = root / "rebuilt.png"
            helper.write_text("", encoding="utf-8")
            source.write_bytes(b"source")
            rebuilt.write_bytes(b"rebuilt")

            service = AssetAuthoringService()
            report = service.openimageio_source_report(source, {"openimageio": helper})
            convert = service.openimageio_convert_command(source, output, {"openimageio": helper})
            diff = service.openimageio_diff_command(output, rebuilt, {"openimageio": helper})

        self.assertEqual("ready", report["status"])
        self.assertTrue(report["openimageio_source_candidate"])
        self.assertEqual([str(helper), "--info", "-v", "--stats", str(source)], report["metadata_argv"])
        self.assertEqual([str(helper), str(source), "-o", str(output)], convert["argv"])
        self.assertFalse(diff["can_run"])
        self.assertEqual("missing_source", diff["status"])
        self.assertIn(str(output), diff["missing"])

    def test_run_openimageio_metadata_surfaces_color_space_and_bit_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "oiiotool.exe"
            source = root / "source.exr"
            helper.write_text("", encoding="utf-8")
            source.write_bytes(b"source")
            stdout = "\n".join(
                (
                    "source.exr : 1024 x 512, 4 channels, float openexr",
                    "    channel list: R, G, B, A",
                    "    oiio:ColorSpace: linear",
                    "    Bits per channel: 16",
                    "      Stats Min: 0.1 0.2 0.3 0.0 (of 1)",
                    "      Stats Max: 0.7 0.8 0.9 1.0 (of 1)",
                    "      Stats Avg: 0.4 0.5 0.6 0.25 (of 1)",
                    "      Stats StdDev: 0.1 0.1 0.1 0.4 (of 1)",
                )
            )
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout=stdout, stderr="")
                result = AssetAuthoringService().run_openimageio_metadata(
                    source,
                    {"openimageio": helper},
                )

        self.assertEqual("ok", result["status"])
        self.assertEqual((str(helper), "--info", "-v", "--stats", str(source)), run_mock.call_args.args[0])
        self.assertEqual(1024, result["metadata"]["width"])
        self.assertEqual(512, result["metadata"]["height"])
        self.assertEqual(4, result["metadata"]["channel_count"])
        self.assertEqual(16, result["metadata"]["bit_depth"])
        self.assertEqual("linear", result["metadata"]["color_space"])
        self.assertEqual(["R", "G", "B", "A"], result["metadata"]["channel_names"])
        self.assertTrue(result["metadata"]["has_alpha_channel"])
        self.assertTrue(result["metadata"]["alpha_varies"])
        self.assertTrue(result["metadata"]["alpha_has_transparency"])
        self.assertEqual(0.25, result["metadata"]["channel_stats"]["A"]["average"])
        json.dumps(result)

    def test_run_openimageio_convert_uses_configured_command_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "oiiotool.exe"
            source = root / "source.exr"
            output = root / "converted" / "source.png"
            helper.write_text("", encoding="utf-8")
            source.write_bytes(b"source")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
                result = AssetAuthoringService().run_openimageio_convert(
                    source,
                    output,
                    {"openimageio": helper},
                )

        self.assertEqual("ok", result["status"])
        run_mock.assert_called_once()
        argv = run_mock.call_args.args[0]
        self.assertEqual((str(helper), str(source), "-o", str(output)), argv)

    def test_run_openimageio_diff_reports_nonzero_as_different(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "oiiotool.exe"
            left = root / "left.png"
            right = root / "right.png"
            helper.write_text("", encoding="utf-8")
            left.write_bytes(b"left")
            right.write_bytes(b"right")
            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run") as run_mock:
                run_mock.return_value = mock.Mock(returncode=1, stdout="FAILURE", stderr="")
                result = AssetAuthoringService().run_openimageio_diff(
                    left,
                    right,
                    {"openimageio": helper},
                )

        self.assertEqual("different", result["status"])
        argv = run_mock.call_args.args[0]
        self.assertEqual((str(helper), str(left), str(right), "--diff"), argv)

    def test_run_openimageio_diff_reports_threshold_metrics_and_writes_visual_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "oiiotool.exe"
            left = root / "left.png"
            right = root / "right.png"
            difference = root / "reports" / "difference.png"
            helper.write_text("", encoding="utf-8")
            left.write_bytes(b"left")
            right.write_bytes(b"right")
            stdout = "\n".join(
                (
                    'Comparing "left.png" and "right.png"',
                    "  Mean error = 0.00450079",
                    "  RMS error = 0.00764215",
                    "  Peak SNR = 42.3357",
                    "  Max error  = 0.254902 @ (700, 222, B)",
                    "  12 pixels (1.5%) over 0.004",
                    "FAILURE",
                )
            )

            def completed(*_args: object, **_kwargs: object) -> mock.Mock:
                difference.write_bytes(b"difference")
                return mock.Mock(returncode=1, stdout=stdout, stderr="")

            with mock.patch("cdmw.services.asset_authoring_service.subprocess.run", side_effect=completed) as run_mock:
                result = AssetAuthoringService().run_openimageio_diff(
                    left,
                    right,
                    {"openimageio": helper},
                    fail_threshold=0.004,
                    fail_percent=1.0,
                    hard_fail_threshold=0.008,
                    difference_output_path=difference,
                    difference_scale=8.0,
                )

        self.assertEqual("different", result["status"])
        self.assertEqual(
            (
                str(helper),
                str(left),
                str(right),
                "--fail",
                "0.004",
                "--failpercent",
                "1",
                "--hardfail",
                "0.008",
                "--diff",
                "--absdiff",
                "--mulc",
                "8",
                "--ch",
                "R,G,B",
                "-o",
                str(difference),
            ),
            run_mock.call_args.args[0],
        )
        self.assertTrue(result["difference_output_written"])
        self.assertEqual(0.00450079, result["metrics"]["mean_error"])
        self.assertEqual(0.00764215, result["metrics"]["rms_error"])
        self.assertEqual(42.3357, result["metrics"]["peak_snr_db"])
        self.assertEqual(0.254902, result["metrics"]["max_error"])
        self.assertEqual("700, 222, B", result["metrics"]["max_error_location"])
        self.assertEqual("failure", result["metrics"]["result"])
        self.assertEqual(12, result["metrics"]["threshold_rows"][0]["pixel_count"])


if __name__ == "__main__":
    unittest.main()
