from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from tools.calibrate_crimson_startup import (
    classify_startup_screenshot,
    run_startup_calibration,
    stable_state,
    summarize_startup_timing_reports,
)


def _write_frame(path: Path, kind: str) -> None:
    image = Image.new("RGB", (320, 180), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    if kind == "menu":
        draw.rectangle((0, 148, 319, 179), fill=(5, 5, 5))
        for x in (18, 88, 165, 245):
            draw.rectangle((x, 157, x + 36, 162), fill=(240, 240, 240))
            draw.rectangle((x, 166, x + 50, 169), fill=(220, 220, 220))
        draw.rectangle((245, 12, 308, 20), fill=(230, 230, 230))
    elif kind == "blue":
        image = Image.new("RGB", (320, 180), (12, 35, 180))
    elif kind == "gameplay":
        for y in range(180):
            for x in range(320):
                image.putpixel((x, y), ((x * 3 + y) % 220 + 20, (x + y * 2) % 180 + 45, (x * y) % 150 + 25))
    elif kind == "explorer":
        image = Image.new("RGB", (320, 180), (18, 18, 18))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 319, 22), fill=(32, 32, 48))
        draw.rectangle((245, 8, 308, 16), fill=(170, 170, 170))
        for row in range(6):
            y = 42 + row * 20
            draw.rectangle((18, y, 56, y + 4), fill=(238, 238, 238))
            draw.rectangle((95, y, 130, y + 4), fill=(210, 210, 210))
    elif kind == "title_art":
        for y in range(180):
            for x in range(320):
                image.putpixel((x, y), ((x * 2 + y) % 120 + 25, (x + y) % 95 + 25, (x * 3 + y) % 115 + 25))
        draw = ImageDraw.Draw(image)
        draw.rectangle((230, 0, 319, 32), fill=(5, 8, 18))
        draw.rectangle((238, 11, 272, 12), fill=(245, 245, 245))
        draw.rectangle((250, 18, 287, 19), fill=(235, 235, 235))
        draw.rectangle((0, 148, 319, 179), fill=(12, 12, 12))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class RenderDocStartupCalibrationTests(unittest.TestCase):
    def test_classifies_startup_frames_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames = {}
            for kind in ("black", "menu", "blue", "gameplay"):
                path = root / f"{kind}.png"
                _write_frame(path, kind)
                frames[kind] = classify_startup_screenshot(path)["state"]

        self.assertEqual("boot_logo_or_black", frames["black"])
        self.assertEqual("menu_ready", frames["menu"])
        self.assertEqual("load_transition", frames["blue"])
        self.assertEqual("gameplay_candidate", frames["gameplay"])

    def test_rejects_occluding_windows_and_title_art(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames = {}
            for kind in ("explorer", "title_art"):
                path = root / f"{kind}.png"
                _write_frame(path, kind)
                frames[kind] = classify_startup_screenshot(path)["state"]

        self.assertEqual("unknown", frames["explorer"])
        self.assertEqual("title_or_splash_art", frames["title_art"])

    def test_stable_state_requires_count_and_span(self) -> None:
        shots = [{"state": "menu_ready", "t": 1.0}, {"state": "menu_ready", "t": 1.5}]
        self.assertFalse(stable_state(shots, "menu_ready", required_count=2, min_span_s=1.0))
        shots.append({"state": "menu_ready", "t": 2.1})
        self.assertTrue(stable_state(shots, "menu_ready", required_count=2, min_span_s=0.5))

    def test_stable_state_allows_more_frames_to_satisfy_span(self) -> None:
        shots = [{"state": "gameplay_candidate", "t": float(index)} for index in range(6)]

        self.assertTrue(stable_state(shots, "gameplay_candidate", required_count=3, min_span_s=5.0))

    def test_runner_presses_e_only_after_two_stable_menu_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir()
            game_exe.write_text("", encoding="utf-8")
            source_frames = []
            for index, kind in enumerate(["black", "menu", "menu", "blue", "gameplay", "gameplay", "gameplay"], start=1):
                path = root / f"source_{index}.png"
                _write_frame(path, kind)
                source_frames.append(path)
            clock = FakeClock()
            captures: list[Path] = []
            key_times: list[float] = []
            interaction_times: list[float] = []
            interaction_hwnds: list[int] = []
            key_hwnds: list[int] = []

            def capture(path: Path) -> dict[str, object]:
                frame = source_frames[len(captures)]
                path.write_bytes(frame.read_bytes())
                captures.append(path)
                return {"ok": True, "window": {"hwnd": 44, "pid": 1234}, "diagnostics": []}

            def interact(hwnd: int) -> dict[str, object]:
                interaction_times.append(clock.monotonic())
                interaction_hwnds.append(hwnd)
                return {"code": "window_interacted_for_keyboard_prompts", "hwnd": hwnd, "foreground_hwnd": hwnd}

            def send_key(hwnd: int, key: str, *, hold_s: float) -> dict[str, object]:
                key_times.append(clock.monotonic())
                key_hwnds.append(hwnd)
                return {"code": "key_sent", "hwnd": hwnd, "key": key, "sent_input_count": 2, "foreground_hwnd": hwnd}

            report = run_startup_calibration(
                root / "calibration" / "baseline-001",
                run_id="baseline-001",
                game_root=root,
                game_exe=game_exe,
                menu_timeout_s=10,
                gameplay_timeout_s=10,
                post_e_cadence_s=1,
                gameplay_stable_s=2,
                launch_func=lambda **_: (1234, {"code": "game_launch_requested", "pid": 1234}),
                wait_window_func=lambda **_: {"hwnd": 1, "pid": 1234},
                screenshot_func=capture,
                pre_e_interaction_func=interact,
                send_key_func=send_key,
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid},
                find_window_func=lambda: {},
                clock=clock.monotonic,
                sleep=clock.sleep,
            )

            timing = json.loads((root / "calibration" / "baseline-001" / "timing.json").read_text(encoding="utf-8"))

        self.assertEqual("ready_for_capture", report["result"])
        self.assertEqual(44, report["hwnd"])
        self.assertEqual([44], interaction_hwnds)
        self.assertEqual([44, 44], key_hwnds)
        self.assertEqual([2.0], interaction_times)
        self.assertEqual([2.25, 2.5], key_times)
        self.assertEqual(
            ["launch_requested", "window_visible", "menu_ready", "pre_e_window_interaction", "e_pressed", "load_transition", "gameplay_stable"],
            [event["name"] for event in report["events"]],
        )
        self.assertEqual(2, report["events"][4]["press_count"])
        self.assertEqual("ready_for_capture", timing["result"])
        self.assertEqual(7, len(timing["screenshots"]))

    def test_runner_blocks_when_launch_would_touch_existing_game_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir()
            game_exe.write_text("", encoding="utf-8")

            report = run_startup_calibration(
                root / "calibration" / "baseline-001",
                run_id="baseline-001",
                game_root=root,
                game_exe=game_exe,
                find_window_func=lambda: {"hwnd": 99, "pid": 999},
            )

        self.assertEqual("blocked", report["result"])
        self.assertEqual("existing_game_window_running", report["blocker"])
        self.assertEqual(0, report["pid"])

    def test_runner_stops_when_play_key_does_not_leave_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir()
            game_exe.write_text("", encoding="utf-8")
            source_frames = []
            for index, kind in enumerate(["menu", "menu", "menu", "menu"], start=1):
                path = root / f"source_{index}.png"
                _write_frame(path, kind)
                source_frames.append(path)
            clock = FakeClock()
            captures: list[Path] = []

            def capture(path: Path) -> dict[str, object]:
                frame = source_frames[len(captures)]
                path.write_bytes(frame.read_bytes())
                captures.append(path)
                return {"ok": True, "window": {"hwnd": 44, "pid": 1234}, "diagnostics": []}

            report = run_startup_calibration(
                root / "calibration" / "baseline-001",
                run_id="baseline-001",
                game_root=root,
                game_exe=game_exe,
                menu_timeout_s=10,
                gameplay_timeout_s=10,
                post_e_cadence_s=1,
                launch_func=lambda **_: (1234, {"code": "game_launch_requested", "pid": 1234}),
                wait_window_func=lambda **_: {"hwnd": 44, "pid": 1234},
                screenshot_func=capture,
                pre_e_interaction_func=lambda hwnd: {"code": "window_interacted_for_keyboard_prompts", "hwnd": hwnd, "foreground_hwnd": hwnd},
                send_key_func=lambda hwnd, key, *, hold_s: {"code": "key_sent", "hwnd": hwnd, "key": key, "sent_input_count": 2, "foreground_hwnd": hwnd},
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid},
                find_window_func=lambda: {},
                clock=clock.monotonic,
                sleep=clock.sleep,
            )

        self.assertEqual("blocked", report["result"])
        self.assertEqual("play_key_no_effect", report["blocker"])

    def test_runner_stops_when_pre_e_interaction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_exe = root / "bin64" / "CrimsonDesert.exe"
            game_exe.parent.mkdir()
            game_exe.write_text("", encoding="utf-8")
            source_frames = []
            for index, kind in enumerate(["menu", "menu"], start=1):
                path = root / f"source_{index}.png"
                _write_frame(path, kind)
                source_frames.append(path)
            clock = FakeClock()
            captures: list[Path] = []
            key_times: list[float] = []

            def capture(path: Path) -> dict[str, object]:
                frame = source_frames[len(captures)]
                path.write_bytes(frame.read_bytes())
                captures.append(path)
                return {"ok": True, "window": {"hwnd": 44, "pid": 1234}, "diagnostics": []}

            report = run_startup_calibration(
                root / "calibration" / "baseline-001",
                run_id="baseline-001",
                game_root=root,
                game_exe=game_exe,
                menu_timeout_s=10,
                launch_func=lambda **_: (1234, {"code": "game_launch_requested", "pid": 1234}),
                wait_window_func=lambda **_: {"hwnd": 44, "pid": 1234},
                screenshot_func=capture,
                pre_e_interaction_func=lambda hwnd: {"code": "focus_failed", "hwnd": hwnd, "foreground_hwnd": 0},
                send_key_func=lambda hwnd, key, *, hold_s: key_times.append(clock.monotonic()) or {"code": "key_sent", "hwnd": hwnd, "key": key},
                shutdown_func=lambda pid: {"code": "shutdown_requested", "pid": pid},
                find_window_func=lambda: {},
                clock=clock.monotonic,
                sleep=clock.sleep,
            )

        self.assertEqual("blocked", report["result"])
        self.assertEqual("pre_e_interaction_failed", report["blocker"])
        self.assertEqual([], key_times)

    def test_timing_summary_reports_min_median_max(self) -> None:
        summary = summarize_startup_timing_reports(
            [
                {"result": "ready_for_capture", "events": [{"name": "window_visible", "t": 1}, {"name": "menu_ready", "t": 4}, {"name": "e_pressed", "t": 5}, {"name": "load_transition", "t": 7}, {"name": "gameplay_stable", "t": 11}]},
                {"result": "ready_for_capture", "events": [{"name": "window_visible", "t": 3}, {"name": "menu_ready", "t": 8}, {"name": "e_pressed", "t": 9}, {"name": "load_transition", "t": 10}, {"name": "gameplay_stable", "t": 16}]},
            ]
        )

        self.assertEqual(2, summary["ready_for_capture_count"])
        self.assertEqual(2, summary["timings"]["window_s"]["median"])
        self.assertEqual(1, summary["timings"]["e_to_load_transition_s"]["min"])
        self.assertEqual(7, summary["timings"]["e_to_gameplay_stable_s"]["max"])


if __name__ == "__main__":
    unittest.main()
