from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.capture_crimson_renderdoc_frame import (
    build_capture_command,
    build_capture_plan,
    build_inject_command,
    main,
    renderdoc_ags_allow_unknown_patch_status,
    temporary_steam_appid_file,
    temporary_renderdoc_ags_allow_unknown_extensions,
)


class RenderDocCaptureLauncherTests(unittest.TestCase):
    def test_build_capture_command_uses_renderdoc_capture_file_and_working_dir(self) -> None:
        command = build_capture_command(
            renderdoccmd=Path("C:/RenderDoc/renderdoccmd.exe"),
            game_exe=Path("C:/game/bin64/CrimsonDesert.exe"),
            capture_file=Path("C:/captures/frame.rdc"),
            working_dir=Path("C:/game"),
            game_args=("--foo", "bar"),
        )

        self.assertEqual("capture", command[1])
        self.assertIn("--capture-file", command)
        self.assertIn("C:\\captures\\frame.rdc", command)
        self.assertIn("--working-dir", command)
        self.assertEqual(["--foo", "bar"], command[-2:])

    def test_build_inject_command_targets_existing_pid(self) -> None:
        command = build_inject_command(
            renderdoccmd=Path("C:/RenderDoc/renderdoccmd.exe"),
            pid=1234,
            capture_file=Path("C:/captures/frame.rdc"),
            working_dir=Path("C:/game"),
        )

        self.assertEqual("inject", command[1])
        self.assertIn("--PID=1234", command)
        self.assertIn("--opt-hook-children", command)

    def test_temp_steam_appid_file_restores_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            appid = root / "steam_appid.txt"

            with temporary_steam_appid_file(root, "3321460"):
                self.assertEqual("3321460\n", appid.read_text(encoding="ascii"))

            self.assertFalse(appid.exists())

    def test_temp_steam_appid_file_restores_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            appid = root / "steam_appid.txt"
            appid.write_text("old", encoding="utf-8")

            with temporary_steam_appid_file(root, "3321460"):
                self.assertEqual("3321460\n", appid.read_text(encoding="ascii"))

            self.assertEqual("old", appid.read_text(encoding="utf-8"))

    def test_plan_reports_missing_renderdoc_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")

            plan = build_capture_plan(
                game_root=root,
                game_exe=game_exe,
                capture_file=root / "capture.rdc",
                renderdoccmd=Path(root / "missing-renderdoccmd.exe"),
            )

        self.assertEqual("blocked", plan["status"])
        self.assertIn("renderdoccmd_not_found", plan["blockers"])

    def test_plan_can_describe_existing_pid_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")

            plan = build_capture_plan(
                game_root=root,
                capture_file=root / "capture.rdc",
                renderdoccmd=renderdoccmd,
                pid=4567,
            )

        self.assertEqual("ready", plan["status"])
        self.assertEqual("inject", plan["command_kind"])
        self.assertIn("--PID=4567", plan["command"])

    def test_plan_can_disable_high_impact_renderdoc_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")

            plan = build_capture_plan(
                game_root=root,
                game_exe=game_exe,
                capture_file=root / "capture.rdc",
                renderdoccmd=renderdoccmd,
                hook_children=False,
                ref_all_resources=False,
                capture_all_cmd_lists=False,
                disallow_fullscreen=False,
                soft_memory_limit_mb=1536,
            )

        self.assertEqual("ready", plan["status"])
        self.assertFalse(plan["options"]["hook_children"])
        self.assertFalse(plan["options"]["ref_all_resources"])
        self.assertFalse(plan["options"]["capture_all_cmd_lists"])
        self.assertFalse(plan["options"]["disallow_fullscreen"])
        self.assertEqual(1536, plan["options"]["soft_memory_limit_mb"])
        self.assertNotIn("--opt-hook-children", plan["command"])
        self.assertNotIn("--opt-ref-all-resources", plan["command"])
        self.assertNotIn("--opt-capture-all-cmd-lists", plan["command"])
        self.assertNotIn("--opt-disallow-fullscreen", plan["command"])
        self.assertIn("--opt-soft-memory-limit", plan["command"])

    def test_renderdoc_ags_allow_unknown_patch_restores_exact_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "renderdoc.conf"
            original = (
                '<?xml version="1.0"?>\n'
                '<config version="1"><AMD><ags>'
                '<AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions>'
                "</ags></AMD></config>\n"
            )
            config.write_text(original, encoding="utf-8")

            self.assertEqual("ready", renderdoc_ags_allow_unknown_patch_status(config)["status"])
            with temporary_renderdoc_ags_allow_unknown_extensions(True, config):
                self.assertIn(
                    '<AllowUnknownExtensions type="Boolean">true</AllowUnknownExtensions>',
                    config.read_text(encoding="utf-8"),
                )

            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_plan_records_amd_unknown_extension_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            config.write_text(
                '<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>',
                encoding="utf-8",
            )

            plan = build_capture_plan(
                game_root=root,
                game_exe=game_exe,
                capture_file=root / "capture.rdc",
                renderdoccmd=renderdoccmd,
                allow_amd_unknown_extensions=True,
                renderdoc_config=config,
            )

        self.assertEqual("ready", plan["status"])
        self.assertTrue(plan["renderdoc_config_patch"]["allow_amd_unknown_extensions"])
        self.assertEqual("ready", plan["renderdoc_config_patch"]["status"])

    def test_cli_writes_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out = root / "plan.json"
            exit_code = main(
                [
                    "--game-root",
                    str(root),
                    "--capture-file",
                    str(root / "frame.rdc"),
                    "--out-plan-json",
                    str(out),
                ]
            )

            self.assertEqual(2, exit_code)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("blocked", payload["status"])


if __name__ == "__main__":
    unittest.main()
