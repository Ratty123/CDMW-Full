from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.rendering import ingame_capture


STARTUP_CALIBRATION_SCHEMA_VERSION = 1


def _event(events: list[dict[str, Any]], name: str, start: float, clock: Callable[[], float], **extra: Any) -> None:
    events.append({"name": name, "t": round(float(clock() - start), 3), **extra})


def _region_metrics(pixels: Sequence[tuple[int, int, int]]) -> dict[str, Any]:
    total = max(1, len(pixels))
    lumas = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels]
    mean = sum(lumas) / total
    buckets = {(r // 32, g // 32, b // 32) for r, g, b in pixels}
    return {
        "mean_luma": round(mean, 3),
        "dark_ratio": sum(1 for value in lumas if value < 35) / total,
        "bright_ratio": sum(1 for value in lumas if value > 205) / total,
        "blue_ratio": sum(1 for r, g, b in pixels if b > max(r, g) * 1.35 and b > 75) / total,
        "red_ratio": sum(1 for r, g, b in pixels if r > max(g, b) * 1.35 and r > 75) / total,
        "color_bucket_count": len(buckets),
        "luma_span": round(max(lumas) - min(lumas), 3),
    }


def _pixels(image: Any) -> list[tuple[int, int, int]]:
    getter = getattr(image, "get_flattened_data", None)
    return list((getter or image.getdata)())


def image_startup_metrics(path: Path) -> dict[str, Any]:
    from PIL import Image

    image = Image.open(path).convert("RGB")
    if image.width > 480:
        height = max(1, int(image.height * (480 / image.width)))
        image = image.resize((480, height))
    width, height = image.size
    all_metrics = _region_metrics(_pixels(image))
    bottom = image.crop((0, int(height * 0.82), width, height))
    top_right = image.crop((int(width * 0.72), 0, width, int(height * 0.18)))
    return {
        "width": width,
        "height": height,
        **all_metrics,
        "bottom": _region_metrics(_pixels(bottom)),
        "top_right": _region_metrics(_pixels(top_right)),
    }


def classify_startup_screenshot(path: Path) -> dict[str, Any]:
    metrics = image_startup_metrics(Path(path))
    bottom = metrics["bottom"]
    top_right = metrics["top_right"]
    reasons: list[str] = []
    state = "unknown"
    if top_right["dark_ratio"] > 0.84 and top_right["bright_ratio"] > 0.01 and bottom["mean_luma"] < 35 and bottom["dark_ratio"] > 0.65:
        state = "title_or_splash_art"
        reasons.append("dark_title_art_with_bright_logo")
    elif (
        bottom["dark_ratio"] > 0.45
        and bottom["luma_span"] > 120
        and bottom["bright_ratio"] > 0.001
        and top_right["bright_ratio"] > 0.0005
        and metrics["blue_ratio"] < 0.18
        and metrics["red_ratio"] < 0.18
    ):
        state = "menu_ready"
        reasons.append("bottom_command_strip_and_version_area")
    elif metrics["dark_ratio"] > 0.88 and metrics["bright_ratio"] < 0.02:
        state = "boot_logo_or_black"
        reasons.append("mostly_dark")
    elif metrics["blue_ratio"] > 0.28 or metrics["red_ratio"] > 0.28:
        state = "load_transition"
        reasons.append("transition_color_dominant")
    elif metrics["dark_ratio"] < 0.68 and metrics["color_bucket_count"] >= 24 and metrics["luma_span"] > 70:
        state = "gameplay_candidate"
        reasons.append("detailed_non_menu_scene")
    return {"state": state, "metrics": metrics, "reasons": reasons}


def stable_state(
    screenshots: Sequence[Mapping[str, Any]],
    state: str,
    *,
    required_count: int,
    min_span_s: float,
) -> bool:
    matches = [shot for shot in screenshots if shot.get("state") == state]
    if len(matches) < required_count:
        return False
    return float(matches[-1].get("t", 0.0)) - float(matches[0].get("t", 0.0)) >= float(min_span_s)


def _real_screenshot(path: Path, *, game_root: Path, game_exe: Path) -> dict[str, Any]:
    result = ingame_capture.capture_crimson_ingame_screenshot(
        path,
        game_root=game_root,
        game_exe=game_exe,
        launch_game=False,
    )
    return result.to_dict()


def _shutdown_pid(pid: int) -> dict[str, Any]:
    if not pid:
        return {"code": "shutdown_skipped", "pid": 0}
    try:
        completed = subprocess.run(["taskkill", "/PID", str(int(pid)), "/T"], check=False, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"code": "shutdown_failed", "pid": int(pid), "error": str(exc)}
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _pid_running(int(pid)):
        time.sleep(0.25)
    forced = False
    force_returncode = ""
    if _pid_running(int(pid)):
        forced = True
        try:
            forced_result = subprocess.run(["taskkill", "/F", "/PID", str(int(pid)), "/T"], check=False, capture_output=True, text=True, timeout=15)
            force_returncode = forced_result.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            return {"code": "shutdown_failed", "pid": int(pid), "returncode": completed.returncode, "forced": True, "error": str(exc)}
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _pid_running(int(pid)):
            time.sleep(0.25)
    return {
        "code": "shutdown_requested",
        "pid": int(pid),
        "returncode": completed.returncode,
        "forced": forced,
        "force_returncode": force_returncode,
        "running_after": _pid_running(int(pid)),
    }


def _pid_running(pid: int) -> bool:
    if os.name != "nt" or not pid:
        return False
    try:
        completed = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return str(int(pid)) in completed.stdout


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def run_startup_calibration(
    run_dir: Path,
    *,
    run_id: str,
    game_root: Path = Path(ingame_capture.DEFAULT_CRIMSON_GAME_ROOT),
    game_exe: Path | None = None,
    renderdoc_enabled: bool = False,
    launch_game: bool = True,
    shutdown_launched_process: bool = True,
    window_timeout_s: float = 60.0,
    menu_timeout_s: float = 180.0,
    gameplay_timeout_s: float = 300.0,
    menu_cadence_s: float = 1.0,
    post_e_cadence_s: float = 0.5,
    gameplay_stable_s: float = 5.0,
    key_hold_s: float = 0.075,
    pre_e_interaction_wait_s: float = 0.25,
    e_press_count: int = 2,
    e_press_gap_s: float = 0.25,
    launch_func: Callable[..., tuple[int, Mapping[str, Any]]] | None = None,
    wait_window_func: Callable[..., Mapping[str, Any]] | None = None,
    screenshot_func: Callable[[Path], Mapping[str, Any]] | None = None,
    pre_e_interaction_func: Callable[..., Mapping[str, Any]] | None = None,
    send_key_func: Callable[..., Mapping[str, Any]] | None = None,
    shutdown_func: Callable[[int], Mapping[str, Any]] | None = None,
    find_window_func: Callable[..., Mapping[str, Any]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    root = Path(game_root)
    exe = Path(game_exe) if game_exe else ingame_capture.default_crimson_game_exe(root)
    run = Path(run_dir)
    screens = run / "screens"
    screens.mkdir(parents=True, exist_ok=True)
    start = float(clock())
    events: list[dict[str, Any]] = []
    screenshots: list[dict[str, Any]] = []
    diagnostics: list[Mapping[str, Any]] = []
    launched_pid = 0
    window: Mapping[str, Any] = {}

    def fail(blocker: str, result: str = "blocked") -> dict[str, Any]:
        window_pid = int(window.get("pid", 0) or 0) if isinstance(window, Mapping) else 0
        target_pid = window_pid or launched_pid
        report = {
            "schema_version": STARTUP_CALIBRATION_SCHEMA_VERSION,
            "run_id": run_id,
            "renderdoc_enabled": renderdoc_enabled,
            "game_root": str(root),
            "game_exe": str(exe),
            "pid": target_pid,
            "launched_pid": launched_pid,
            "hwnd": int(window.get("hwnd", 0) or 0) if isinstance(window, Mapping) else 0,
            "events": events,
            "screenshots": screenshots[-5:],
            "all_screenshot_count": len(screenshots),
            "diagnostics": [dict(item) for item in diagnostics],
            "result": result,
            "blocker": blocker,
        }
        if shutdown_launched_process and target_pid:
            shutdown = (shutdown_func or _shutdown_pid)(target_pid)
            report["shutdown"] = dict(shutdown)
        _write_report(run / "timing.json", report)
        return report

    if not exe.is_file():
        return fail("game_exe_missing")
    if launch_game:
        existing_window = (find_window_func or ingame_capture.find_crimson_game_window)()
        if existing_window:
            diagnostics.append({"code": "existing_game_window_running", "window": dict(existing_window)})
            return fail("existing_game_window_running")
    _event(events, "launch_requested", start, clock)
    if launch_game:
        launched_pid, launch_diag = (launch_func or ingame_capture.launch_crimson_desert)(game_root=root, game_exe=exe)
        diagnostics.append(launch_diag)
        if not launched_pid:
            return fail(str(launch_diag.get("code", "game_launch_failed")))
    window = (wait_window_func or ingame_capture.wait_for_crimson_game_window)(timeout_s=window_timeout_s)
    if not window:
        return fail("window_not_found")
    _event(events, "window_visible", start, clock, hwnd=int(window.get("hwnd", 0) or 0), pid=int(window.get("pid", launched_pid) or 0))

    capture = screenshot_func or (lambda path: _real_screenshot(path, game_root=root, game_exe=exe))
    pre_e_interaction = pre_e_interaction_func or ingame_capture.interact_with_window_for_keyboard_prompts
    send_key = send_key_func or ingame_capture.send_key_to_window
    pressed_play_keys = False
    menu_deadline = float(clock()) + menu_timeout_s
    while float(clock()) <= menu_deadline:
        path = screens / f"pre_menu_{len(screenshots) + 1:04d}.png"
        shot = dict(capture(path))
        diagnostics.extend(shot.get("diagnostics", []) if isinstance(shot.get("diagnostics", []), list) else [])
        if not shot.get("ok", False):
            return fail("window_capture_failed")
        shot_window = shot.get("window")
        if isinstance(shot_window, Mapping) and int(shot_window.get("hwnd", 0) or 0):
            window = shot_window
        detected = classify_startup_screenshot(path)
        record = {
            "state": detected["state"],
            "path": str(path.relative_to(run)),
            "t": round(float(clock() - start), 3),
            "classifier": {"reasons": detected["reasons"], "metrics": detected["metrics"]},
        }
        screenshots.append(record)
        if stable_state(screenshots, "menu_ready", required_count=2, min_span_s=1.0):
            _event(events, "menu_ready", start, clock)
            hwnd = int((shot.get("window") or window).get("hwnd", window.get("hwnd", 0)) or 0)
            interaction_report = dict(pre_e_interaction(hwnd))
            diagnostics.append(interaction_report)
            if interaction_report.get("code") != "window_interacted_for_keyboard_prompts":
                return fail("pre_e_interaction_failed")
            _event(events, "pre_e_window_interaction", start, clock, foreground_hwnd=interaction_report.get("foreground_hwnd", 0))
            sleep(pre_e_interaction_wait_s)
            key_reports: list[dict[str, Any]] = []
            for _ in range(max(1, int(e_press_count))):
                key_report = dict(send_key(hwnd, "E", hold_s=key_hold_s))
                diagnostics.append(key_report)
                key_reports.append(key_report)
                if key_report.get("code") != "key_sent":
                    return fail("e_send_failed")
                if len(key_reports) < max(1, int(e_press_count)):
                    sleep(e_press_gap_s)
            _event(
                events,
                "e_pressed",
                start,
                clock,
                press_count=len(key_reports),
                foreground_hwnd=key_reports[-1].get("foreground_hwnd", 0),
                sent_input_count=sum(int(report.get("sent_input_count", 0) or 0) for report in key_reports),
            )
            pressed_play_keys = True
            break
        sleep(menu_cadence_s)
    if not pressed_play_keys:
        return fail("menu_timeout")

    load_seen = False
    gameplay_screenshots: list[Mapping[str, Any]] = []
    post_e_menu_screenshots: list[Mapping[str, Any]] = []
    gameplay_deadline = float(clock()) + gameplay_timeout_s
    while float(clock()) <= gameplay_deadline:
        path = screens / f"post_e_{len(screenshots) + 1:04d}.png"
        shot = dict(capture(path))
        diagnostics.extend(shot.get("diagnostics", []) if isinstance(shot.get("diagnostics", []), list) else [])
        if not shot.get("ok", False):
            return fail("window_capture_failed")
        shot_window = shot.get("window")
        if isinstance(shot_window, Mapping) and int(shot_window.get("hwnd", 0) or 0):
            window = shot_window
        detected = classify_startup_screenshot(path)
        state = str(detected["state"])
        record = {
            "state": state,
            "path": str(path.relative_to(run)),
            "t": round(float(clock() - start), 3),
            "classifier": {"reasons": detected["reasons"], "metrics": detected["metrics"]},
        }
        screenshots.append(record)
        if state == "menu_ready":
            post_e_menu_screenshots.append(record)
            if stable_state(post_e_menu_screenshots, "menu_ready", required_count=2, min_span_s=1.0):
                return fail("play_key_no_effect")
        else:
            post_e_menu_screenshots.clear()
        if state in {"boot_logo_or_black", "load_transition"} and not load_seen:
            _event(events, "load_transition", start, clock, detected_state=state)
            load_seen = True
        if state == "gameplay_candidate":
            gameplay_screenshots.append(record)
            if stable_state(gameplay_screenshots, "gameplay_candidate", required_count=3, min_span_s=gameplay_stable_s):
                _event(events, "gameplay_stable", start, clock)
                report = fail("", result="ready_for_capture")
                report["blocker"] = ""
                report["screenshots"] = screenshots
                _write_report(run / "timing.json", report)
                return report
        else:
            gameplay_screenshots.clear()
        sleep(1.0 if gameplay_screenshots else post_e_cadence_s)
    return fail("gameplay_timeout")


def _event_time(report: Mapping[str, Any], name: str) -> float | None:
    for event in report.get("events", []):
        if isinstance(event, Mapping) and event.get("name") == name:
            return float(event.get("t", 0.0))
    return None


def summarize_startup_timing_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: dict[str, list[float]] = {
        "window_s": [],
        "menu_s": [],
        "e_to_load_transition_s": [],
        "e_to_gameplay_stable_s": [],
    }
    for report in reports:
        window = _event_time(report, "window_visible")
        menu = _event_time(report, "menu_ready")
        pressed = _event_time(report, "e_pressed")
        load = _event_time(report, "load_transition")
        stable = _event_time(report, "gameplay_stable")
        if window is not None:
            rows["window_s"].append(window)
        if menu is not None:
            rows["menu_s"].append(menu)
        if pressed is not None and load is not None:
            rows["e_to_load_transition_s"].append(round(load - pressed, 3))
        if pressed is not None and stable is not None:
            rows["e_to_gameplay_stable_s"].append(round(stable - pressed, 3))
    summary = {
        "schema_version": STARTUP_CALIBRATION_SCHEMA_VERSION,
        "run_count": len(reports),
        "ready_for_capture_count": sum(1 for report in reports if report.get("result") == "ready_for_capture"),
        "timings": {},
    }
    for key, values in rows.items():
        summary["timings"][key] = {
            "count": len(values),
            "min": min(values) if values else "",
            "median": statistics.median(values) if values else "",
            "max": max(values) if values else "",
        }
    return summary


def write_startup_timing_summary(calibration_dir: Path) -> dict[str, Any]:
    reports = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(calibration_dir).glob("baseline-*/timing.json"))
    ]
    summary = summarize_startup_timing_reports(reports)
    _write_report(Path(calibration_dir) / "startup_timing_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--game-root", type=Path, default=Path(ingame_capture.DEFAULT_CRIMSON_GAME_ROOT))
    parser.add_argument("--game-exe", type=Path)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--no-shutdown", action="store_true")
    args = parser.parse_args(argv)
    reports = []
    for index in range(1, max(1, int(args.runs)) + 1):
        reports.append(
            run_startup_calibration(
                args.output_dir / f"baseline-{index:03d}",
                run_id=f"baseline-{index:03d}",
                game_root=args.game_root,
                game_exe=args.game_exe,
                launch_game=not args.no_launch,
                shutdown_launched_process=not args.no_shutdown,
            )
        )
        if reports[-1].get("result") != "ready_for_capture":
            break
    if len(reports) > 1:
        write_startup_timing_summary(args.output_dir)
    print(json.dumps({"reports": [str(args.output_dir / f"baseline-{i + 1:03d}" / "timing.json") for i in range(len(reports))]}, indent=2))
    return 0 if all(report.get("result") == "ready_for_capture" for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
