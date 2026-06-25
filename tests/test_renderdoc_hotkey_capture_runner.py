from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.run_crimson_renderdoc_hotkey_capture import build_pose_plan, perform_post_gameplay_pose, run_renderdoc_hotkey_capture, wait_for_capture_file


class FakeProcess:
    def __init__(self, pid: int = 77) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1


class RenderDocHotkeyCaptureRunnerTests(unittest.TestCase):
    def test_wait_for_capture_file_finds_new_rdc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture = root / "crimson_water_stones_000000.rdc"
            capture.write_bytes(b"rdc")

            report = wait_for_capture_file(root / "crimson_water_stones", started_at=0, timeout_s=1.0, poll_s=0.1)

        self.assertEqual("capture_file_collected", report["code"])
        self.assertTrue(str(report["capture_path"]).endswith("crimson_water_stones_000000.rdc"))

    def test_runner_launches_renderdoc_then_sends_one_f12(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_root = root / "game"
            game_exe = game_root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            original_config = '<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>'
            config.write_text(original_config, encoding="utf-8")
            run_dir = root / "run"
            commands: list[list[str]] = []
            hotkeys: list[str] = []

            def popen(command: list[str], **_: object) -> FakeProcess:
                commands.append(command)
                return FakeProcess()

            def startup(run_dir: Path, **kwargs: object) -> dict[str, object]:
                pid, diagnostic = kwargs["launch_func"]()
                return {"result": "ready_for_capture", "pid": 1234, "hwnd": 44, "launch_pid": pid, "diagnostics": [diagnostic]}

            def send_key(hwnd: int, key: str, *, hold_s: float) -> dict[str, object]:
                hotkeys.append(key)
                return {"code": "key_sent", "hwnd": hwnd, "key": key, "sent_input_count": 2, "foreground_hwnd": hwnd}

            def wait_capture(capture_template: Path, **_: object) -> dict[str, object]:
                capture = Path(f"{capture_template}_000000.rdc")
                capture.write_bytes(b"rdc")
                return {"code": "capture_file_collected", "capture_path": str(capture), "capture_size": 3}

            report = run_renderdoc_hotkey_capture(
                run_dir,
                game_root=game_root,
                game_exe=game_exe,
                renderdoccmd=renderdoccmd,
                renderdoc_config=config,
                startup_func=startup,
                send_key_func=send_key,
                wait_capture_file_func=wait_capture,
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid, "running_after": False},
                popen_factory=popen,
            )
            saved = json.loads((run_dir / "capture" / "capture_run.json").read_text(encoding="utf-8"))
            restored_config = config.read_text(encoding="utf-8")
            appid_exists = (game_root / "steam_appid.txt").exists()

        self.assertEqual("capture_collected", report["result"])
        self.assertEqual(["F12"], hotkeys)
        self.assertIn("--wait-for-exit", commands[0])
        self.assertEqual(original_config, restored_config)
        self.assertFalse(appid_exists)
        self.assertEqual("capture_collected", saved["result"])

    def test_sword_pose_sends_bounded_movement_then_attack_clicks(self) -> None:
        events: list[tuple[object, ...]] = []
        sleeps: list[float] = []

        def send_key(hwnd: int, key: str, *, hold_s: float) -> dict[str, object]:
            events.append(("key", hwnd, key, hold_s))
            return {"code": "key_sent", "hwnd": hwnd, "key": key, "sent_input_count": 2, "foreground_hwnd": hwnd}

        def click(hwnd: int, *, button: str, x_ratio: float, y_ratio: float, hold_s: float) -> dict[str, object]:
            events.append(("mouse_click", hwnd, button, x_ratio, y_ratio, hold_s))
            return {"code": "mouse_click_sent", "hwnd": hwnd, "button": button, "sent_input_count": 2, "foreground_hwnd": hwnd}

        report = perform_post_gameplay_pose(44, preset="sword", send_key_func=send_key, click_func=click, sleep=sleeps.append)

        self.assertEqual("pose_completed", report["code"])
        self.assertEqual(["key", "key", "mouse_click", "mouse_click"], [event[0] for event in events])
        self.assertEqual(["W", "D"], [event[2] for event in events if event[0] == "key"])
        self.assertEqual(["left", "left"], [event[2] for event in events if event[0] == "mouse_click"])
        self.assertEqual([0.10, 0.05, 0.12, 0.08], sleeps)

    def test_sword_pose_plan_records_exact_bounded_actions(self) -> None:
        plan = build_pose_plan("sword")

        self.assertEqual("sword", plan["preset"])
        self.assertEqual(["key", "key", "mouse_click", "mouse_click"], [action["type"] for action in plan["actions"]])
        self.assertEqual(["W", "D"], [action["key"] for action in plan["actions"] if action["type"] == "key"])
        self.assertEqual(["left", "left"], [action["button"] for action in plan["actions"] if action["type"] == "mouse_click"])

    def test_runner_poses_before_capture_hotkey(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_root = root / "game"
            game_exe = game_root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            config.write_text('<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>', encoding="utf-8")
            run_dir = root / "run"
            events: list[str] = []

            def startup(run_dir: Path, **kwargs: object) -> dict[str, object]:
                kwargs["launch_func"]()
                return {"result": "ready_for_capture", "pid": 1234, "hwnd": 44, "diagnostics": []}

            def pose(hwnd: int, *, preset: str, send_key_func: object) -> dict[str, object]:
                events.append(f"pose:{preset}:{hwnd}")
                return {"code": "pose_completed", "preset": preset, "actions": []}

            def send_key(hwnd: int, key: str, *, hold_s: float) -> dict[str, object]:
                events.append(f"key:{key}:{hwnd}")
                return {"code": "key_sent", "hwnd": hwnd, "key": key, "sent_input_count": 2, "foreground_hwnd": hwnd}

            def wait_capture(capture_template: Path, **_: object) -> dict[str, object]:
                capture = Path(f"{capture_template}_000000.rdc")
                capture.write_bytes(b"rdc")
                return {"code": "capture_file_collected", "capture_path": str(capture), "capture_size": 3}

            report = run_renderdoc_hotkey_capture(
                run_dir,
                game_root=game_root,
                game_exe=game_exe,
                renderdoccmd=renderdoccmd,
                renderdoc_config=config,
                pose_preset="sword",
                startup_func=startup,
                pose_func=pose,
                send_key_func=send_key,
                wait_capture_file_func=wait_capture,
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid, "running_after": False},
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )
            saved = json.loads((run_dir / "capture" / "capture_plan.json").read_text(encoding="utf-8"))

        self.assertEqual("capture_collected", report["result"])
        self.assertEqual(["pose:sword:44", "key:F12:44"], events)
        self.assertEqual("pose_completed", report["pose"]["code"])
        self.assertEqual("sword", saved["pose_plan"]["preset"])

    def test_runner_can_process_reports_after_capture_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_root = root / "game"
            game_exe = game_root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            config.write_text('<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>', encoding="utf-8")
            seen: dict[str, object] = {}

            def startup(run_dir: Path, **kwargs: object) -> dict[str, object]:
                kwargs["launch_func"]()
                return {"result": "ready_for_capture", "pid": 1234, "hwnd": 44, "diagnostics": []}

            def wait_capture(capture_template: Path, **_: object) -> dict[str, object]:
                capture = Path(f"{capture_template}_000000.rdc")
                capture.write_bytes(b"rdc")
                return {"code": "capture_file_collected", "capture_path": str(capture), "capture_size": 3}

            def process(run_dir: Path, **kwargs: object) -> dict[str, object]:
                seen["run_dir"] = run_dir
                seen.update(kwargs)
                return {"status": "capture_reports_processed", "truth_report": str(Path(run_dir) / "reports" / "truth_report_rank1.json")}

            report = run_renderdoc_hotkey_capture(
                root / "run",
                game_root=game_root,
                game_exe=game_exe,
                renderdoccmd=renderdoccmd,
                renderdoc_config=config,
                process_reports=True,
                report_rank=2,
                startup_func=startup,
                send_key_func=lambda hwnd, key, *, hold_s: {"code": "key_sent", "hwnd": hwnd, "key": key},
                wait_capture_file_func=wait_capture,
                process_func=process,
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid, "running_after": False},
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )

        self.assertEqual("capture_processed", report["result"])
        self.assertEqual("capture_reports_processed", report["postprocess"]["status"])
        self.assertEqual(2, seen["rank"])
        self.assertTrue(str(seen["rdc_path"]).endswith("_000000.rdc"))

    def test_runner_blocks_when_requested_postprocess_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_root = root / "game"
            game_exe = game_root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            config.write_text('<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>', encoding="utf-8")

            def startup(run_dir: Path, **kwargs: object) -> dict[str, object]:
                kwargs["launch_func"]()
                return {"result": "ready_for_capture", "pid": 1234, "hwnd": 44, "diagnostics": []}

            def wait_capture(capture_template: Path, **_: object) -> dict[str, object]:
                capture = Path(f"{capture_template}_000000.rdc")
                capture.write_bytes(b"rdc")
                return {"code": "capture_file_collected", "capture_path": str(capture), "capture_size": 3}

            report = run_renderdoc_hotkey_capture(
                root / "run",
                game_root=game_root,
                game_exe=game_exe,
                renderdoccmd=renderdoccmd,
                renderdoc_config=config,
                process_reports=True,
                startup_func=startup,
                send_key_func=lambda hwnd, key, *, hold_s: {"code": "key_sent", "hwnd": hwnd, "key": key},
                wait_capture_file_func=wait_capture,
                process_func=lambda *_args, **_kwargs: {"status": "blocked", "blocker": "renderdoc_conversion_failed"},
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid, "running_after": False},
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )

        self.assertEqual("blocked", report["result"])
        self.assertEqual("renderdoc_conversion_failed", report["blocker"])
        self.assertEqual("blocked", report["postprocess"]["status"])

    def test_runner_blocks_before_hotkey_when_pose_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_root = root / "game"
            game_exe = game_root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir(parents=True)
            game_exe.write_text("", encoding="utf-8")
            renderdoccmd = root / "renderdoccmd.exe"
            renderdoccmd.write_text("", encoding="utf-8")
            config = root / "renderdoc.conf"
            config.write_text('<config><AMD><ags><AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions></ags></AMD></config>', encoding="utf-8")
            hotkeys: list[str] = []

            def startup(run_dir: Path, **kwargs: object) -> dict[str, object]:
                kwargs["launch_func"]()
                return {"result": "ready_for_capture", "pid": 1234, "hwnd": 44, "diagnostics": []}

            report = run_renderdoc_hotkey_capture(
                root / "run",
                game_root=game_root,
                game_exe=game_exe,
                renderdoccmd=renderdoccmd,
                renderdoc_config=config,
                pose_preset="sword",
                startup_func=startup,
                pose_func=lambda *_args, **_kwargs: {"code": "pose_failed", "blocker": "focus_failed", "actions": []},
                send_key_func=lambda hwnd, key, *, hold_s: hotkeys.append(key) or {"code": "key_sent", "hwnd": hwnd, "key": key},
                wait_capture_file_func=lambda *_args, **_kwargs: {"code": "capture_file_collected"},
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid, "running_after": False},
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )

        self.assertEqual("blocked", report["result"])
        self.assertEqual("focus_failed", report["blocker"])
        self.assertEqual([], hotkeys)


if __name__ == "__main__":
    unittest.main()
