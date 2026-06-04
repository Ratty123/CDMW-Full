from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.trigger_renderdoc_capture_api import (
    build_trigger_plan,
    render_injector_source,
    render_trigger_dll_source,
    rust_string_literal,
)


class RenderDocApiTriggerTests(unittest.TestCase):
    def test_rust_string_literal_escapes_paths_and_quotes(self) -> None:
        escaped = rust_string_literal('C:\\game\\"x"')

        self.assertIn("C:\\\\game", escaped)
        self.assertIn('\\"x\\"', escaped)

    def test_trigger_dll_source_calls_renderdoc_api(self) -> None:
        source = render_trigger_dll_source(
            capture_template=Path("C:/captures/crimson_api"),
            marker_json=Path("C:/captures/marker.json"),
        )

        self.assertIn("RENDERDOC_GetAPI", source)
        self.assertIn("SetCaptureFilePathTemplate", source)
        self.assertIn("TriggerCapture", source)
        self.assertIn("capture_count_increased", source)
        self.assertIn('b"C:\\\\captures\\\\crimson_api\\0"', source)

    def test_injector_source_uses_loadlibrary_remote_thread(self) -> None:
        source = render_injector_source()

        self.assertIn("OpenProcess", source)
        self.assertIn("WriteProcessMemory", source)
        self.assertIn("CreateRemoteThread", source)
        self.assertIn("LoadLibraryA", source)

    def test_plan_reports_missing_rustc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch("tools.trigger_renderdoc_capture_api.shutil.which", return_value=""):
            plan = build_trigger_plan(
                pid=1234,
                capture_template=Path(temp_dir) / "capture",
                marker_json=Path(temp_dir) / "marker.json",
                work_dir=Path(temp_dir) / "work",
                tag="unit",
            )

        self.assertEqual("blocked", plan["status"])
        self.assertIn("rustc_not_found", plan["blockers"])

    def test_plan_contains_inject_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_trigger_plan(
                pid=1234,
                capture_template=Path(temp_dir) / "capture",
                marker_json=Path(temp_dir) / "marker.json",
                work_dir=Path(temp_dir) / "work",
                rustc="rustc.exe",
                tag="unit",
            )

        self.assertEqual("ready", plan["status"])
        self.assertEqual("1234", plan["inject_command"][1])
        self.assertTrue(str(plan["inject_command"][2]).endswith("renderdoc_api_trigger_unit.dll"))
        self.assertTrue(Path(str(plan["inject_command"][0])).is_absolute())
        self.assertTrue(Path(str(plan["inject_command"][2])).is_absolute())
        self.assertTrue(Path(str(plan["marker_json"])).is_absolute())
        self.assertTrue(Path(str(plan["capture_template"])).is_absolute())


if __name__ == "__main__":
    unittest.main()
