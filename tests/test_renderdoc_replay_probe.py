from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.probe_renderdoc_replay_truth import build_probe_plan, render_qrenderdoc_probe_script


class RenderDocReplayProbeTests(unittest.TestCase):
    def test_script_uses_ui_capture_load_and_blockinvoke(self) -> None:
        script = render_qrenderdoc_probe_script(
            capture_path=Path("C:/captures/frame.rdc"),
            out_json=Path("C:/captures/probe.json"),
            max_actions=32,
        )

        self.assertIn("pyrenderdoc.LoadCapture", script)
        self.assertIn("pyrenderdoc.Replay().BlockInvoke", script)
        self.assertIn("controller.GetPipelineState()", script)
        self.assertIn("QApplication.instance()", script)

    def test_plan_uses_absolute_paths_and_qrenderdoc_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture = root / "frame.rdc"
            qrenderdoc = root / "qrenderdoc.exe"
            renderdoc_config = root / "renderdoc.conf"
            capture.write_bytes(b"rdc")
            qrenderdoc.write_bytes(b"exe")
            renderdoc_config.write_text(
                '<AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions>',
                encoding="utf-8",
            )

            plan = build_probe_plan(
                capture_path=capture,
                out_json=root / "probe.json",
                work_dir=root / "work",
                qrenderdoc=qrenderdoc,
                max_actions=12,
                allow_amd_unknown_extensions=True,
                renderdoc_config=renderdoc_config,
            )

        self.assertEqual("ready", plan["status"])
        self.assertEqual("--script", plan["command"][1])
        self.assertTrue(Path(str(plan["capture_path"])).is_absolute())
        self.assertTrue(Path(str(plan["out_json"])).is_absolute())
        self.assertTrue(Path(str(plan["script_path"])).is_absolute())
        self.assertTrue(plan["renderdoc_config_patch"]["allow_amd_unknown_extensions"])

    def test_plan_reports_missing_qrenderdoc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch("tools.probe_renderdoc_replay_truth.find_qrenderdoc", return_value=""):
            root = Path(temp_dir)
            capture = root / "frame.rdc"
            capture.write_bytes(b"rdc")

            plan = build_probe_plan(
                capture_path=capture,
                out_json=root / "probe.json",
                work_dir=root / "work",
            )

        self.assertEqual("blocked", plan["status"])
        self.assertIn("qrenderdoc_not_found", plan["blockers"])


if __name__ == "__main__":
    unittest.main()
