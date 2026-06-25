from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from cdmw.rendering.preview_comparison import compare_preview_images, image_color_stats, parse_roi, write_preview_comparison_report
from cdmw.rendering.native_preview_screenshot import (
    capture_native_d3d11_preview_package,
    native_preview_screenshot_command,
)
from cdmw.rendering.ingame_capture import (
    DEFAULT_CRIMSON_GAME_ROOT,
    _capture_hwnd_client,
    capture_crimson_ingame_screenshot,
    click_window_client,
    default_crimson_game_exe,
    find_crimson_game_window,
    interact_with_window_for_keyboard_prompts,
    send_key_to_window,
)
from cdmw.rendering.test_run_sword_tuning import (
    TEST_RUN_SWORD_BASELINE_SETTINGS,
    TEST_RUN_SWORD_MINIMUM_VARIANTS,
    build_loose_mod_file_manifest,
    build_test_run_sword_session_status,
    build_test_run_sword_variant_settings,
    build_test_run_sword_run_manifest,
    build_test_run_sword_tuning_recommendations,
    sync_test_run_sword_variant_to_dmm,
    write_test_run_sword_session_status,
    write_test_run_sword_session_plan,
    write_test_run_sword_run_manifest,
)


def _solid(path: Path, color: QColor) -> None:
    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(color)
    assert image.save(str(path), "PNG")


class PreviewComparisonTests(unittest.TestCase):
    def test_image_stats_and_report_fields_include_material_tuning_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = root / "preview.png"
            icon = root / "icon.png"
            ingame = root / "ingame.png"
            _solid(preview, QColor(20, 20, 24, 255))
            _solid(icon, QColor(210, 176, 56, 255))
            _solid(ingame, QColor(44, 126, 52, 255))

            stats = image_color_stats(preview)
            report = compare_preview_images(preview, item_icon_path=icon, in_game_path=ingame)
            outputs = write_preview_comparison_report(
                report,
                json_path=root / "comparison.json",
                csv_path=root / "comparison.csv",
            )

            self.assertEqual("ok", stats["status"])
            self.assertIn("preview_stats", report)
            self.assertIn("diagnostics", report)
            codes = {item["code"] for item in report["diagnostics"]}
            self.assertIn("too_dark", codes)
            self.assertIn("too_dull", codes)
            self.assertIn("missing_gold", codes)
            self.assertIn("missing_green", codes)
            self.assertTrue(Path(outputs["json"]).is_file())
            self.assertTrue(Path(outputs["csv"]).is_file())
            self.assertEqual(1, json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))["schema_version"])
            with Path(outputs["csv"]).open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["code"] == "too_dark" for row in rows))

    def test_compare_preview_cli_runs_directly_from_tools_folder(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "tools" / "compare_preview_screenshots.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = root / "preview.png"
            icon = root / "icon.png"
            out_json = root / "comparison.json"
            out_csv = root / "comparison.csv"
            _solid(preview, QColor(20, 20, 24, 255))
            _solid(icon, QColor(210, 176, 56, 255))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--preview",
                    str(preview),
                    "--item-icon",
                    str(icon),
                    "--out-json",
                    str(out_json),
                    "--out-csv",
                    str(out_csv),
                ],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(str(out_json), payload["outputs"]["json"])
            self.assertTrue(out_json.is_file())
            self.assertTrue(out_csv.is_file())

    def test_roi_sampling_records_red_blue_stats_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preview = root / "preview_blue.png"
            reference = root / "reference_red.png"
            blue_image = QImage(10, 10, QImage.Format_RGBA8888)
            red_image = QImage(10, 10, QImage.Format_RGBA8888)
            blue_image.fill(QColor(0, 0, 220, 255))
            red_image.fill(QColor(220, 0, 0, 255))
            self.assertTrue(blue_image.save(str(preview), "PNG"))
            self.assertTrue(red_image.save(str(reference), "PNG"))

            stats = image_color_stats(preview, roi="2,2,4,4")
            report = compare_preview_images(preview, in_game_path=reference, preview_roi="2,2,4,4", in_game_roi=(2, 2, 4, 4))

        self.assertEqual((2, 2, 4, 4), parse_roi("2,2,4,4"))
        self.assertEqual({"x": 2, "y": 2, "width": 4, "height": 4}, stats["sample_roi"])
        self.assertGreater(stats["blue_ratio"], 0.9)
        codes = {item["code"] for item in report["diagnostics"]}
        self.assertIn("missing_red", codes)
        self.assertIn("unexpected_blue", codes)


class TestRunSwordManifestTests(unittest.TestCase):
    def test_variant_settings_generate_twenty_distinct_material_probes(self) -> None:
        settings = [build_test_run_sword_variant_settings(index) for index in range(1, TEST_RUN_SWORD_MINIMUM_VARIANTS + 1)]

        self.assertEqual(TEST_RUN_SWORD_MINIMUM_VARIANTS, len(settings))
        self.assertEqual("material_tuning_001", settings[0]["variant_label"])
        self.assertTrue(any(item.get("masked_gold_strength_percent") for item in settings))
        self.assertTrue(any(item.get("neutral_metal_base_tint") == "cool_silver" for item in settings))
        self.assertTrue(any(item.get("environment_reflection_percent") for item in settings))

    def test_manifest_format_records_baseline_settings_and_run_artifacts(self) -> None:
        manifest = build_test_run_sword_run_manifest(
            run_index=7,
            preview_screenshot="run_007/preview.png",
            in_game_screenshot="run_007/ingame.png",
            in_game_capture_report="run_007/ingame_capture_report.json",
            package_manifest="run_007/package_manifest.json",
            comparison_report="run_007/comparison.json",
            mod_settings={"roughness": 0.62},
            notes="matte test",
        )

        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("run_007", manifest["run_id"])
        self.assertEqual(20, manifest["minimum_variants_required"])
        self.assertEqual("run_007/ingame_capture_report.json", manifest["artifacts"]["in_game_capture_report"])
        self.assertEqual(TEST_RUN_SWORD_BASELINE_SETTINGS["runtime_profile"], manifest["mod_settings"]["runtime_profile"])
        self.assertEqual(0.62, manifest["mod_settings"]["roughness"])
        self.assertIn("sync_variant_to_dmm_mod", manifest["loop_requirements"])

    def test_manifest_writer_creates_numbered_run_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = write_test_run_sword_run_manifest(temp_dir, run_index=3, notes="probe")
            data = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("run_003", manifest_path.parent.name)
        self.assertEqual("probe", data["notes"])

    def test_session_plan_creates_twenty_numbered_run_folders_with_package_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_mod = root / "source" / "TestRunSword"
            dmm_mod = root / "dmm" / "TestRunSword"
            source_mod.mkdir(parents=True)
            dmm_mod.mkdir(parents=True)
            (source_mod / "manifest.json").write_text("source", encoding="utf-8")
            (dmm_mod / "manifest.json").write_text("dmm", encoding="utf-8")

            session_path = write_test_run_sword_session_plan(
                root / "runs",
                source_mod_dir=source_mod,
                dmm_mod_dir=dmm_mod,
            )
            data = json.loads(session_path.read_text(encoding="utf-8"))

        self.assertEqual("planned", data["status"])
        self.assertEqual(TEST_RUN_SWORD_MINIMUM_VARIANTS, data["variant_count"])
        self.assertEqual(TEST_RUN_SWORD_MINIMUM_VARIANTS, len(data["runs"]))
        self.assertTrue(Path(data["runs"][0]["package_manifest"]).name == "package_manifest.json")

    def test_loose_mod_manifest_and_dmm_sync_are_explicit_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_mod = root / "source" / "TestRunSword"
            dmm_mod = root / "dmm" / "TestRunSword"
            run_dir = root / "run_001"
            source_file = source_mod / "character" / "model" / "blade.pac"
            dmm_file = dmm_mod / "character" / "model" / "blade.pac"
            source_file.parent.mkdir(parents=True)
            dmm_file.parent.mkdir(parents=True)
            source_file.write_text("new", encoding="utf-8")
            dmm_file.write_text("old", encoding="utf-8")

            manifest = build_loose_mod_file_manifest(source_mod)
            dry_run = sync_test_run_sword_variant_to_dmm(
                run_dir=run_dir,
                source_mod_dir=source_mod,
                dmm_mod_dir=dmm_mod,
                apply=False,
            )
            applied = sync_test_run_sword_variant_to_dmm(
                run_dir=run_dir,
                source_mod_dir=source_mod,
                dmm_mod_dir=dmm_mod,
                apply=True,
            )

            backup = run_dir / "dmm_restore" / "character" / "model" / "blade.pac"
            backed_up_text = backup.read_text(encoding="utf-8")
            current_text = dmm_file.read_text(encoding="utf-8")

        self.assertEqual(1, manifest["file_count"])
        self.assertFalse(dry_run["applied"])
        self.assertTrue(applied["applied"])
        self.assertIn("character/model/blade.pac", applied["copied"])
        self.assertEqual("old", backed_up_text)
        self.assertEqual("new", current_text)

    def test_test_run_sword_tuning_cli_plan_runs_from_tools_folder(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "tools" / "test_run_sword_tuning_loop.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "runs"
            source_mod = root / "source" / "TestRunSword"
            dmm_mod = root / "dmm" / "TestRunSword"
            source_mod.mkdir(parents=True)
            dmm_mod.mkdir(parents=True)
            (source_mod / "manifest.json").write_text("source", encoding="utf-8")
            (dmm_mod / "manifest.json").write_text("dmm", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "plan",
                    "--output-dir",
                    str(output_dir),
                    "--variants",
                    "20",
                    "--source-mod-dir",
                    str(source_mod),
                    "--dmm-mod-dir",
                    str(dmm_mod),
                ],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(str(output_dir / "session_manifest.json"), payload["session_manifest"])
        self.assertEqual(20, payload["variant_count"])

    def test_session_status_counts_completed_runs_and_recommends_tuning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "runs"
            source_mod = root / "source" / "TestRunSword"
            dmm_mod = root / "dmm" / "TestRunSword"
            source_mod.mkdir(parents=True)
            dmm_mod.mkdir(parents=True)
            (source_mod / "manifest.json").write_text("source", encoding="utf-8")
            (dmm_mod / "manifest.json").write_text("dmm", encoding="utf-8")
            write_test_run_sword_session_plan(output_dir, source_mod_dir=source_mod, dmm_mod_dir=dmm_mod)

            run_dir = output_dir / "run_001"
            preview = run_dir / "preview.png"
            ingame = run_dir / "ingame.png"
            _solid(preview, QColor(20, 20, 24, 255))
            _solid(ingame, QColor(70, 120, 70, 255))
            comparison = compare_preview_images(preview, in_game_path=ingame)
            write_preview_comparison_report(comparison, json_path=run_dir / "comparison.json", csv_path=run_dir / "comparison.csv")
            (run_dir / "ingame_capture_report.json").write_text(
                json.dumps({"ok": True, "diagnostics": [{"code": "key_sent", "key": "E"}]}, indent=2),
                encoding="utf-8",
            )

            status = build_test_run_sword_session_status(output_dir)
            status_path = write_test_run_sword_session_status(output_dir)
            written = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual("incomplete", status["status"])
        self.assertEqual(1, status["counts"]["artifact_complete_runs"])
        self.assertEqual(1, status["counts"]["captured_runs"])
        self.assertEqual(1, status["counts"]["compared_runs"])
        self.assertEqual(1, status["counts"]["e_only_capture_reports"])
        self.assertEqual(0, status["counts"]["non_e_input_reports"])
        self.assertEqual(19, status["missing_by_artifact"]["in_game_screenshot"])
        recommendation_codes = {item["code"] for item in status["runs"][0]["tuning_recommendations"]}
        self.assertIn("increase_preview_luma_or_source_brightness", recommendation_codes)
        self.assertEqual(status["counts"], written["counts"])

    def test_session_status_reads_bom_manifest_and_absolute_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "runs"
            source_mod = root / "source" / "TestRunSword"
            dmm_mod = root / "dmm" / "TestRunSword"
            source_mod.mkdir(parents=True)
            dmm_mod.mkdir(parents=True)
            write_test_run_sword_session_plan(output_dir, source_mod_dir=source_mod, dmm_mod_dir=dmm_mod)

            run_dir = output_dir / "run_001"
            preview = run_dir / "preview.png"
            ingame = run_dir / "ingame.png"
            _solid(preview, QColor(20, 20, 24, 255))
            _solid(ingame, QColor(70, 120, 70, 255))
            write_preview_comparison_report(
                compare_preview_images(preview, in_game_path=ingame),
                json_path=run_dir / "comparison.json",
                csv_path=run_dir / "comparison.csv",
            )
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["preview_screenshot"] = str(preview)
            manifest["artifacts"]["in_game_screenshot"] = str(ingame)
            manifest["artifacts"]["comparison_report"] = str(run_dir / "comparison.json")
            manifest_path.write_text("\ufeff" + json.dumps(manifest, indent=2), encoding="utf-8")

            status = build_test_run_sword_session_status(output_dir)

        self.assertTrue(status["runs"][0]["artifact_complete"])
        self.assertEqual(1, status["counts"]["artifact_complete_runs"])

    def test_tuning_recommendations_are_deduplicated_from_comparison_diagnostics(self) -> None:
        recommendations = build_test_run_sword_tuning_recommendations(
            {
                "diagnostics": [
                    {"code": "too_dark", "target": "in_game", "delta": -0.2},
                    {"code": "too_dark", "target": "item_icon", "delta": -0.3},
                    {"code": "missing_green", "target": "in_game", "delta": -0.1},
                    {"code": "unexpected_blue", "target": "in_game", "delta": 0.1},
                ]
            }
        )

        self.assertEqual(
            [
                "increase_preview_luma_or_source_brightness",
                "increase_masked_green_strength",
                "reduce_blue_gem_or_check_channel_swizzle",
            ],
            [item["code"] for item in recommendations],
        )


class NativePreviewScreenshotTests(unittest.TestCase):
    def test_native_screenshot_command_targets_package_and_status_file(self) -> None:
        command = native_preview_screenshot_command(
            Path("C:/tools/cdmw-d3d11-preview.exe"),
            Path("C:/package"),
            Path("C:/package/status.json"),
            diagnostic_log=Path("C:/package/diag.jsonl"),
        )

        self.assertIn("--preview-package", command)
        self.assertIn("C:\\package", command)
        self.assertIn("--status-file", command)
        self.assertIn("C:\\package\\status.json", command)
        self.assertIn("--diagnostic-log", command)

    def test_native_screenshot_capture_reports_unsupported_platform_before_launch(self) -> None:
        if sys.platform.startswith("win"):
            self.skipTest("unsupported-platform guard is for non-Windows hosts")
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            package_dir.mkdir()
            result = capture_native_d3d11_preview_package(package_dir, Path(temp_dir) / "preview.png")

        self.assertFalse(result.ok)
        self.assertEqual("unsupported_platform", result.diagnostics[0]["code"])


class InGameCaptureTests(unittest.TestCase):
    def test_default_game_exe_points_to_bin64_crimson_desert(self) -> None:
        exe = default_crimson_game_exe(DEFAULT_CRIMSON_GAME_ROOT)

        self.assertEqual("CrimsonDesert.exe", exe.name)
        self.assertEqual("bin64", exe.parent.name)

    def test_ingame_capture_reports_no_window_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.rendering.ingame_capture.find_crimson_game_window", return_value={}):
                result = capture_crimson_ingame_screenshot(Path(temp_dir) / "ingame.png", launch_game=False)

        self.assertFalse(result.ok)
        codes = {item["code"] for item in result.diagnostics}
        self.assertIn("game_window_not_found", codes)
        self.assertIn("capture_blocked", codes)

    def test_send_key_to_window_skips_input_when_focus_fails(self) -> None:
        with patch("cdmw.rendering.ingame_capture._focus_window_for_input", return_value={"foreground_ok": False, "foreground_hwnd": 20}), patch(
            "cdmw.rendering.ingame_capture._send_input_scan_key"
        ) as send:
            report = send_key_to_window(10, "E")

        self.assertEqual("focus_failed", report["code"])
        self.assertEqual(0, report["sent_input_count"])
        send.assert_not_called()

    def test_send_key_to_window_supports_renderdoc_f12_hotkey(self) -> None:
        with patch(
            "cdmw.rendering.ingame_capture._focus_window_for_input",
            return_value={"foreground_ok": True, "foreground_hwnd": 10, "foreground_pid": 100, "target_pid": 100},
        ), patch("cdmw.rendering.ingame_capture._send_input_scan_key", return_value=2) as send:
            report = send_key_to_window(10, "F12")

        self.assertEqual("key_sent", report["code"])
        self.assertEqual("F12", report["key"])
        send.assert_called_once_with(0x7B, hold_s=0.05)

    def test_click_window_client_skips_mouse_input_when_focus_fails(self) -> None:
        with patch(
            "cdmw.rendering.ingame_capture._focus_window_for_input",
            return_value={"foreground_ok": False, "foreground_hwnd": 20, "foreground_pid": 200, "target_pid": 100},
        ), patch("ctypes.windll.user32") as user32:
            report = click_window_client(10)

        self.assertEqual("focus_failed", report["code"])
        self.assertEqual(0, report["sent_input_count"])
        user32.mouse_event.assert_not_called()

    def test_click_window_client_sends_bounded_left_click(self) -> None:
        def get_client_rect(_hwnd: int, rect_ref: object) -> int:
            rect = rect_ref._obj
            rect.left = 0
            rect.top = 0
            rect.right = 200
            rect.bottom = 100
            return 1

        with patch(
            "cdmw.rendering.ingame_capture._focus_window_for_input",
            return_value={"foreground_ok": True, "foreground_hwnd": 10, "foreground_pid": 100, "target_pid": 100},
        ), patch("ctypes.windll.user32") as user32:
            user32.GetClientRect.side_effect = get_client_rect
            user32.ClientToScreen.return_value = 1
            user32.SetCursorPos.return_value = 1
            report = click_window_client(10, hold_s=0.01)

        self.assertEqual("mouse_click_sent", report["code"])
        self.assertEqual("left", report["button"])
        self.assertEqual(2, report["sent_input_count"])
        self.assertEqual(2, user32.mouse_event.call_count)

    def test_window_capture_skips_occluded_or_unfocused_window(self) -> None:
        with patch(
            "cdmw.rendering.ingame_capture._focus_window_for_input",
            return_value={"foreground_ok": False, "foreground_hwnd": 20, "foreground_pid": 200, "target_pid": 100},
        ), patch("ctypes.windll.user32") as user32, tempfile.TemporaryDirectory() as temp_dir:
            report = _capture_hwnd_client(10, Path(temp_dir) / "capture.png")

        self.assertEqual("focus_failed", report["code"])
        user32.GetClientRect.assert_not_called()

    def test_window_interaction_fails_closed_when_click_does_not_focus_game(self) -> None:
        def get_client_rect(_hwnd: int, rect_ref: object) -> int:
            rect = rect_ref._obj
            rect.left = 0
            rect.top = 0
            rect.right = 100
            rect.bottom = 100
            return 1

        with patch(
            "cdmw.rendering.ingame_capture._focus_window_for_input",
            side_effect=[
                {"foreground_ok": False, "foreground_hwnd": 20, "foreground_pid": 200, "target_pid": 100},
                {"foreground_ok": False, "foreground_hwnd": 20, "foreground_pid": 200, "target_pid": 100},
            ],
        ), patch("ctypes.windll.user32") as user32:
            user32.GetClientRect.side_effect = get_client_rect
            user32.ClientToScreen.return_value = 1
            user32.SetCursorPos.return_value = 1
            report = interact_with_window_for_keyboard_prompts(10)

        self.assertEqual("focus_failed", report["code"])
        self.assertEqual(2, user32.mouse_event.call_count)

    def test_capture_ingame_cli_writes_blocker_report_when_game_is_not_running(self) -> None:
        if find_crimson_game_window():
            self.skipTest("A real Crimson Desert window is running")
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "tools" / "test_run_sword_tuning_loop.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run_001"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "capture-ingame",
                    "--run-dir",
                    str(run_dir),
                    "--wait-for-window",
                    "0.1",
                ],
                cwd=temp_dir,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            report_exists = (run_dir / "ingame_capture_report.json").is_file()
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8")) if (run_dir / "run_manifest.json").is_file() else {}

        self.assertEqual(2, completed.returncode)
        self.assertFalse(payload["ok"])
        self.assertTrue(report_exists)
        self.assertEqual(str(run_dir / "ingame_capture_report.json"), manifest["artifacts"]["in_game_capture_report"])

    def test_test_run_sword_capture_cli_only_exposes_e_input(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_source = (repo_root / "tools" / "test_run_sword_tuning_loop.py").read_text(encoding="utf-8")

        self.assertIn("--press-e", script_source)
        self.assertIn("--auxiliary", script_source)
        self.assertIn("if not args.auxiliary", script_source)
        self.assertNotIn("--key", script_source)
        self.assertNotIn("wait_after_key", script_source)


if __name__ == "__main__":
    unittest.main()
