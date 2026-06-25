from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.rendering import ingame_capture
from tools.calibrate_crimson_startup import _shutdown_pid, run_startup_calibration
from tools.capture_crimson_renderdoc_frame import (
    build_capture_plan,
    temporary_renderdoc_ags_allow_unknown_extensions,
    temporary_steam_appid_file,
)


_SKIP_POSE_PRESETS = {"", "none", "off", "skip"}
_SWORD_POSE_ACTIONS: tuple[Mapping[str, Any], ...] = (
    {"type": "key", "key": "W", "hold_s": 0.35, "after_s": 0.10},
    {"type": "key", "key": "D", "hold_s": 0.22, "after_s": 0.05},
    {"type": "mouse_click", "button": "left", "x_ratio": 0.50, "y_ratio": 0.50, "hold_s": 0.08, "after_s": 0.12},
    {"type": "mouse_click", "button": "left", "x_ratio": 0.50, "y_ratio": 0.50, "hold_s": 0.08, "after_s": 0.08},
)


def build_pose_plan(preset: str = "none") -> dict[str, Any]:
    preset_key = str(preset or "none").strip().lower()
    if preset_key in _SKIP_POSE_PRESETS:
        return {"preset": "none", "actions": []}
    if preset_key not in {"sword", "weapon", "gear"}:
        return {"preset": preset_key, "actions": [], "blocker": "pose_unknown"}
    return {
        "preset": preset_key,
        "actions": [
            {
                key: value
                for key, value in dict(action).items()
                if key in {"type", "key", "button", "x_ratio", "y_ratio", "hold_s", "after_s"}
            }
            for action in _SWORD_POSE_ACTIONS
        ],
    }


def default_renderdoc_config() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "renderdoc" / "renderdoc.conf"


def perform_post_gameplay_pose(
    hwnd: int,
    *,
    preset: str = "none",
    send_key_func: Callable[..., Mapping[str, Any]] = ingame_capture.send_key_to_window,
    click_func: Callable[..., Mapping[str, Any]] = ingame_capture.click_window_client,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    preset_key = str(preset or "none").strip().lower()
    if preset_key in _SKIP_POSE_PRESETS:
        return {"code": "pose_skipped", "preset": "none", "actions": []}
    if preset_key not in {"sword", "weapon", "gear"}:
        return {"code": "pose_unknown", "preset": preset_key, "actions": []}

    actions: list[dict[str, Any]] = []
    for index, action in enumerate(_SWORD_POSE_ACTIONS, start=1):
        action_type = str(action.get("type", "") or "")
        if action_type == "key":
            report = dict(send_key_func(hwnd, str(action["key"]), hold_s=float(action["hold_s"])))
            expected_code = "key_sent"
        elif action_type == "mouse_click":
            report = dict(
                click_func(
                    hwnd,
                    button=str(action.get("button", "left")),
                    x_ratio=float(action.get("x_ratio", 0.5)),
                    y_ratio=float(action.get("y_ratio", 0.5)),
                    hold_s=float(action.get("hold_s", 0.05)),
                )
            )
            expected_code = "mouse_click_sent"
        else:
            report = {"code": "unsupported_pose_action", "type": action_type}
            expected_code = ""

        actions.append({"index": index, "type": action_type, "report": report})
        if report.get("code") != expected_code:
            return {
                "code": "pose_failed",
                "preset": preset_key,
                "failed_action": index,
                "blocker": str(report.get("code") or "pose_action_failed"),
                "actions": actions,
            }
        delay = float(action.get("after_s", 0.0) or 0.0)
        if delay > 0:
            sleep(delay)
    return {"code": "pose_completed", "preset": preset_key, "actions": actions}


def wait_for_capture_file(capture_template: Path, *, started_at: float, timeout_s: float = 120.0, poll_s: float = 0.5) -> dict[str, Any]:
    template = Path(capture_template)
    deadline = time.time() + float(timeout_s)
    stable_path = Path()
    stable_size = -1
    while time.time() <= deadline:
        captures = [
            path
            for path in template.parent.glob(f"{template.name}*.rdc")
            if path.is_file() and path.stat().st_mtime >= started_at - 1.0
        ]
        if captures:
            capture = max(captures, key=lambda path: path.stat().st_mtime)
            size = capture.stat().st_size
            if capture == stable_path and size == stable_size and size > 0:
                return {"code": "capture_file_collected", "capture_path": str(capture), "capture_size": size}
            stable_path = capture
            stable_size = size
        time.sleep(max(0.1, float(poll_s)))
    return {"code": "capture_file_timeout", "capture_template": str(template), "timeout_s": timeout_s}


def run_renderdoc_hotkey_capture(
    run_dir: Path,
    *,
    game_root: Path = Path(ingame_capture.DEFAULT_CRIMSON_GAME_ROOT),
    game_exe: Path | None = None,
    renderdoccmd: Path | None = None,
    renderdoc_config: Path | None = None,
    capture_tag: str = "crimson_water_stones",
    capture_hotkey: str = "F12",
    capture_timeout_s: float = 180.0,
    pose_preset: str = "none",
    process_reports: bool = False,
    report_rank: int = 1,
    dds_root: Path | None = None,
    dxc: Path | None = None,
    startup_func: Callable[..., Mapping[str, Any]] = run_startup_calibration,
    pose_func: Callable[..., Mapping[str, Any]] = perform_post_gameplay_pose,
    process_func: Callable[..., Mapping[str, Any]] | None = None,
    send_key_func: Callable[..., Mapping[str, Any]] = ingame_capture.send_key_to_window,
    wait_capture_file_func: Callable[..., Mapping[str, Any]] = wait_for_capture_file,
    shutdown_func: Callable[[int], Mapping[str, Any]] = _shutdown_pid,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    run = Path(run_dir)
    capture_dir = run / "capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    root = Path(game_root)
    exe = Path(game_exe) if game_exe else ingame_capture.default_crimson_game_exe(root)
    config = Path(renderdoc_config) if renderdoc_config else default_renderdoc_config()
    capture_template = capture_dir / capture_tag
    stdout_path = capture_dir / "renderdoc_stdout.txt"
    stderr_path = capture_dir / "renderdoc_stderr.txt"

    plan = build_capture_plan(
        game_root=root,
        game_exe=exe,
        capture_file=capture_template,
        renderdoccmd=renderdoccmd,
        allow_amd_unknown_extensions=True,
        renderdoc_config=config,
        wait_for_exit=True,
    )
    plan["pose_plan"] = build_pose_plan(pose_preset)
    if process_reports:
        plan["post_capture_processing"] = {
            "enabled": True,
            "rank": int(report_rank),
            "dds_root": str(dds_root or ""),
            "dxc": str(dxc or ""),
        }
    (capture_dir / "capture_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    if plan["status"] != "ready":
        report = {"result": "blocked", "blocker": plan["blockers"][0] if plan["blockers"] else "capture_plan_blocked", "capture_plan": plan}
        (capture_dir / "capture_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    renderdoc_process: Any | None = None

    def launch_with_renderdoc(**_: Any) -> tuple[int, Mapping[str, Any]]:
        nonlocal renderdoc_process
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = stdout_path.open("w", encoding="utf-8")
        stderr = stderr_path.open("w", encoding="utf-8")
        try:
            renderdoc_process = popen_factory(plan["command"], cwd=str(root), stdout=stdout, stderr=stderr)
        except Exception:
            stdout.close()
            stderr.close()
            raise
        stdout.close()
        stderr.close()
        return int(getattr(renderdoc_process, "pid", 0) or 0), {
            "code": "renderdoc_capture_launch_requested",
            "pid": int(getattr(renderdoc_process, "pid", 0) or 0),
            "command": plan["command"],
        }

    try:
        with temporary_steam_appid_file(root), temporary_renderdoc_ags_allow_unknown_extensions(True, config):
            startup_report = dict(
                startup_func(
                    capture_dir / "startup",
                    run_id="renderdoc-hotkey-001",
                    game_root=root,
                    game_exe=exe,
                    renderdoc_enabled=True,
                    launch_func=launch_with_renderdoc,
                    shutdown_launched_process=False,
                )
            )
            if startup_report.get("result") != "ready_for_capture":
                blocker = str(startup_report.get("blocker") or "startup_not_ready")
                report = {"result": "blocked", "blocker": blocker, "startup": startup_report, "capture_plan": plan}
                return _finish_capture_report(capture_dir, report, startup_report, shutdown_func, renderdoc_process)

            hwnd = int(startup_report.get("hwnd", 0) or 0)
            pid = int(startup_report.get("pid", 0) or 0)
            pose_report = dict(pose_func(hwnd, preset=pose_preset, send_key_func=send_key_func))
            if pose_report.get("code") in {"pose_failed", "pose_unknown"}:
                report = {
                    "result": "blocked",
                    "blocker": str(pose_report.get("blocker") or pose_report.get("code") or "post_gameplay_pose_failed"),
                    "pid": pid,
                    "hwnd": hwnd,
                    "startup": startup_report,
                    "pose": pose_report,
                    "capture_plan": plan,
                }
                return _finish_capture_report(capture_dir, report, startup_report, shutdown_func, renderdoc_process)
            trigger_started = time.time()
            hotkey_report = dict(send_key_func(hwnd, capture_hotkey, hold_s=0.08))
            if hotkey_report.get("code") != "key_sent":
                report = {
                    "result": "blocked",
                    "blocker": "capture_hotkey_failed",
                    "startup": startup_report,
                    "pose": pose_report,
                    "hotkey": hotkey_report,
                    "capture_plan": plan,
                }
                return _finish_capture_report(capture_dir, report, startup_report, shutdown_func, renderdoc_process)
            capture_report = dict(wait_capture_file_func(capture_template, started_at=trigger_started, timeout_s=capture_timeout_s))
            result = "capture_collected" if capture_report.get("code") == "capture_file_collected" else "blocked"
            blocker = "" if result == "capture_collected" else str(capture_report.get("code", "capture_file_timeout"))
            postprocess_report: dict[str, Any] = {}
            if result == "capture_collected" and process_reports:
                processor = process_func
                if processor is None:
                    from tools.process_renderdoc_capture_reports import process_rdc_capture_reports

                    processor = process_rdc_capture_reports
                postprocess_report = dict(
                    processor(
                        run,
                        rdc_path=Path(str(capture_report.get("capture_path", ""))),
                        renderdoccmd=renderdoccmd,
                        rank=report_rank,
                        dds_root=dds_root,
                        dxc=dxc,
                        scene_note=f"capture_tag={capture_tag}; pose_preset={pose_preset}",
                    )
                )
                if postprocess_report.get("status") == "capture_reports_processed":
                    result = "capture_processed"
                else:
                    result = "blocked"
                    blocker = str(postprocess_report.get("blocker") or postprocess_report.get("status") or "post_capture_processing_failed")
            report = {
                "result": result,
                "blocker": blocker,
                "pid": pid,
                "hwnd": hwnd,
                "startup": startup_report,
                "pose": pose_report,
                "hotkey": hotkey_report,
                "capture": capture_report,
                "postprocess": postprocess_report,
                "capture_plan": plan,
            }
            return _finish_capture_report(capture_dir, report, startup_report, shutdown_func, renderdoc_process)
    finally:
        if renderdoc_process is not None and getattr(renderdoc_process, "poll", lambda: 0)() is None:
            try:
                renderdoc_process.wait(timeout=10)
            except Exception:
                try:
                    renderdoc_process.terminate()
                except Exception:
                    pass


def _finish_capture_report(
    capture_dir: Path,
    report: dict[str, Any],
    startup_report: Mapping[str, Any],
    shutdown_func: Callable[[int], Mapping[str, Any]],
    renderdoc_process: Any | None,
) -> dict[str, Any]:
    pid = int(startup_report.get("pid", 0) or 0)
    if pid:
        report["shutdown"] = dict(shutdown_func(pid))
    if renderdoc_process is not None:
        try:
            report["renderdoc_returncode"] = renderdoc_process.wait(timeout=20)
        except Exception:
            report["renderdoc_returncode"] = "timeout"
    (Path(capture_dir) / "capture_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, default=Path(ingame_capture.DEFAULT_CRIMSON_GAME_ROOT))
    parser.add_argument("--game-exe", type=Path)
    parser.add_argument("--renderdoccmd", type=Path)
    parser.add_argument("--renderdoc-config", type=Path, default=default_renderdoc_config())
    parser.add_argument("--capture-tag", default="crimson_water_stones")
    parser.add_argument("--capture-timeout", type=float, default=180.0)
    parser.add_argument("--pose-preset", choices=["none", "sword", "weapon", "gear"], default="none")
    parser.add_argument("--process-reports", action="store_true")
    parser.add_argument("--report-rank", type=int, default=1)
    parser.add_argument("--dds-root", type=Path)
    parser.add_argument("--dxc", type=Path)
    args = parser.parse_args(argv)
    report = run_renderdoc_hotkey_capture(
        args.run_dir,
        game_root=args.game_root,
        game_exe=args.game_exe,
        renderdoccmd=args.renderdoccmd,
        renderdoc_config=args.renderdoc_config,
        capture_tag=args.capture_tag,
        capture_timeout_s=args.capture_timeout,
        pose_preset=args.pose_preset,
        process_reports=args.process_reports,
        report_rank=args.report_rank,
        dds_root=args.dds_root,
        dxc=args.dxc,
    )
    print(json.dumps({"result": report.get("result"), "blocker": report.get("blocker", ""), "report": str(Path(args.run_dir) / "capture" / "capture_run.json")}, indent=2))
    return 0 if report.get("result") in {"capture_collected", "capture_processed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
