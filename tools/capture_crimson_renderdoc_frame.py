from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.common import hidden_subprocess_kwargs


RENDERDOC_CAPTURE_SCHEMA_VERSION = 1
RENDERDOC_AGS_ALLOW_UNKNOWN_PATTERN = re.compile(
    r'(<AllowUnknownExtensions\s+type="Boolean">)(.*?)(</AllowUnknownExtensions>)',
    re.IGNORECASE | re.DOTALL,
)


def find_renderdoccmd() -> str:
    path = shutil.which("renderdoccmd")
    if path:
        return path
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (
        repo_root / ".tools" / "renderdoc" / "1.44" / "RenderDoc_1.44_64" / "renderdoccmd.exe",
        repo_root / ".tools" / "renderdoc" / "RenderDoc_1.44_64" / "renderdoccmd.exe",
        Path("C:/Program Files/RenderDoc/renderdoccmd.exe"),
        Path("C:/Program Files (x86)/RenderDoc/renderdoccmd.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


def default_renderdoc_config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "renderdoc" / "renderdoc.conf" if appdata else Path()


def default_game_exe(game_root: Path) -> Path:
    return game_root / "bin64" / "CrimsonDesert.exe"


def build_capture_command(
    *,
    renderdoccmd: Path,
    game_exe: Path,
    capture_file: Path,
    working_dir: Path,
    game_args: Sequence[str] = (),
    hook_children: bool = True,
    ref_all_resources: bool = True,
    capture_all_cmd_lists: bool = True,
    disallow_fullscreen: bool = True,
    soft_memory_limit_mb: int = 0,
) -> list[str]:
    command = [
        str(renderdoccmd),
        "capture",
        "--capture-file",
        str(capture_file),
        "--working-dir",
        str(working_dir),
    ]
    if hook_children:
        command.append("--opt-hook-children")
    if ref_all_resources:
        command.append("--opt-ref-all-resources")
    if capture_all_cmd_lists:
        command.append("--opt-capture-all-cmd-lists")
    if disallow_fullscreen:
        command.append("--opt-disallow-fullscreen")
    if soft_memory_limit_mb > 0:
        command.extend(["--opt-soft-memory-limit", str(int(soft_memory_limit_mb))])
    command.extend([str(game_exe), *[str(arg) for arg in game_args]])
    return command


def build_inject_command(
    *,
    renderdoccmd: Path,
    pid: int,
    capture_file: Path,
    working_dir: Path,
    hook_children: bool = True,
    ref_all_resources: bool = True,
    capture_all_cmd_lists: bool = True,
    disallow_fullscreen: bool = True,
    soft_memory_limit_mb: int = 0,
) -> list[str]:
    command = [
        str(renderdoccmd),
        "inject",
        f"--PID={int(pid)}",
        "--capture-file",
        str(capture_file),
        "--working-dir",
        str(working_dir),
    ]
    if hook_children:
        command.append("--opt-hook-children")
    if ref_all_resources:
        command.append("--opt-ref-all-resources")
    if capture_all_cmd_lists:
        command.append("--opt-capture-all-cmd-lists")
    if disallow_fullscreen:
        command.append("--opt-disallow-fullscreen")
    if soft_memory_limit_mb > 0:
        command.extend(["--opt-soft-memory-limit", str(int(soft_memory_limit_mb))])
    return command


def build_capture_plan(
    *,
    game_root: Path,
    game_exe: Path | None = None,
    capture_file: Path,
    renderdoccmd: Path | None = None,
    game_args: Sequence[str] = (),
    pid: int | None = None,
    temporary_steam_appid: str = "",
    hook_children: bool = True,
    ref_all_resources: bool = True,
    capture_all_cmd_lists: bool = True,
    disallow_fullscreen: bool = True,
    soft_memory_limit_mb: int = 0,
    allow_amd_unknown_extensions: bool = False,
    renderdoc_config: Path | None = None,
) -> dict[str, object]:
    resolved_renderdoc = str(renderdoccmd) if renderdoccmd else find_renderdoccmd()
    resolved_game = game_exe or default_game_exe(game_root)
    command_kind = "inject" if pid else "capture"
    if pid:
        command = build_inject_command(
            renderdoccmd=Path(resolved_renderdoc or "renderdoccmd"),
            pid=pid,
            capture_file=capture_file,
            working_dir=game_root,
            hook_children=hook_children,
            ref_all_resources=ref_all_resources,
            capture_all_cmd_lists=capture_all_cmd_lists,
            disallow_fullscreen=disallow_fullscreen,
            soft_memory_limit_mb=soft_memory_limit_mb,
        )
    else:
        command = build_capture_command(
            renderdoccmd=Path(resolved_renderdoc or "renderdoccmd"),
            game_exe=resolved_game,
            capture_file=capture_file,
            working_dir=game_root,
            game_args=game_args,
            hook_children=hook_children,
            ref_all_resources=ref_all_resources,
            capture_all_cmd_lists=capture_all_cmd_lists,
            disallow_fullscreen=disallow_fullscreen,
            soft_memory_limit_mb=soft_memory_limit_mb,
        )
    blockers: list[str] = []
    if not resolved_renderdoc or not Path(resolved_renderdoc).is_file():
        blockers.append("renderdoccmd_not_found")
    if not game_root.exists():
        blockers.append("game_root_not_found")
    if pid is not None and pid <= 0:
        blockers.append("invalid_pid")
    if not pid and not resolved_game.is_file():
        blockers.append("game_exe_not_found")
    resolved_renderdoc_config = renderdoc_config or default_renderdoc_config_path()
    renderdoc_config_patch: dict[str, object] = {
        "allow_amd_unknown_extensions": bool(allow_amd_unknown_extensions),
        "path": str(resolved_renderdoc_config),
        "status": "not_requested",
    }
    if allow_amd_unknown_extensions:
        renderdoc_config_patch = {
            "allow_amd_unknown_extensions": True,
            **renderdoc_ags_allow_unknown_patch_status(resolved_renderdoc_config),
        }
        if renderdoc_config_patch.get("status") != "ready":
            blockers.append(str(renderdoc_config_patch.get("blocker", "renderdoc_config_patch_blocked")))
    return {
        "schema_version": RENDERDOC_CAPTURE_SCHEMA_VERSION,
        "command_kind": command_kind,
        "renderdoccmd": resolved_renderdoc,
        "game_root": str(game_root),
        "game_exe": str(resolved_game),
        "pid": int(pid or 0),
        "capture_file": str(capture_file),
        "temporary_steam_appid": str(temporary_steam_appid or ""),
        "steam_appid_path": str(game_root / "steam_appid.txt") if temporary_steam_appid else "",
        "renderdoc_config_patch": renderdoc_config_patch,
        "options": {
            "hook_children": bool(hook_children),
            "ref_all_resources": bool(ref_all_resources),
            "capture_all_cmd_lists": bool(capture_all_cmd_lists),
            "disallow_fullscreen": bool(disallow_fullscreen),
            "soft_memory_limit_mb": int(soft_memory_limit_mb or 0),
        },
        "command": command,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "notes": [
            "Run with --launch only when the game scene is ready to capture.",
            "After capture, inspect/export SRV slots, sampler states, constant buffers, shader metadata, sRGB views, normal Y, blend/raster state.",
            "Import normalized exported JSON with tools/import_renderdoc_truth_pass.py.",
            "renderdoccmd capture does not expose a capture-frame-N option; trigger capture with F12/overlay, RenderDoc UI, or tools/trigger_renderdoc_capture_api.py after launch.",
            "For Steam builds that bounce through SteamAPI_RestartAppIfNecessary, --temp-steam-appid can keep direct launch inside the RenderDoc-hooked process.",
            "If pre-launch D3D12 capture blocks game load, use minimal options or --pid late injection as a diagnostic; late injection may not capture an already-created D3D12 device.",
            "On AMD, --allow-amd-unknown-extensions can avoid Crimson Desert hanging after E by temporarily enabling RenderDoc AMD.ags.AllowUnknownExtensions.",
            "Use --soft-memory-limit-mb for smaller repeated captures; avoid --opt-ref-all-resources on heavy scenes.",
        ],
    }


@contextmanager
def temporary_steam_appid_file(game_root: Path, appid: str):
    if not appid:
        yield
        return
    appid_path = game_root / "steam_appid.txt"
    existed = appid_path.exists()
    old_text = appid_path.read_text(encoding="utf-8") if existed else ""
    appid_path.write_text(str(appid).strip() + "\n", encoding="ascii")
    try:
        yield
    finally:
        if existed:
            appid_path.write_text(old_text, encoding="utf-8")
        else:
            appid_path.unlink(missing_ok=True)


def renderdoc_ags_allow_unknown_patch_status(config_path: Path) -> dict[str, object]:
    if not config_path.is_file():
        return {"status": "blocked", "path": str(config_path), "blocker": "renderdoc_config_not_found"}
    text = config_path.read_text(encoding="utf-8")
    if not RENDERDOC_AGS_ALLOW_UNKNOWN_PATTERN.search(text):
        return {
            "status": "blocked",
            "path": str(config_path),
            "blocker": "renderdoc_ags_allow_unknown_node_not_found",
        }
    return {"status": "ready", "path": str(config_path)}


@contextmanager
def temporary_renderdoc_ags_allow_unknown_extensions(enabled: bool, config_path: Path | None = None):
    if not enabled:
        yield
        return
    resolved_config = config_path or default_renderdoc_config_path()
    status = renderdoc_ags_allow_unknown_patch_status(resolved_config)
    if status.get("status") != "ready":
        raise FileNotFoundError(str(status.get("blocker", "renderdoc_config_patch_blocked")))
    old_text = resolved_config.read_text(encoding="utf-8")
    patched_text, count = RENDERDOC_AGS_ALLOW_UNKNOWN_PATTERN.subn(r"\1true\3", old_text, count=1)
    if count != 1:
        raise ValueError("renderdoc_ags_allow_unknown_node_not_found")
    resolved_config.write_text(patched_text, encoding="utf-8")
    try:
        yield
    finally:
        resolved_config.write_text(old_text, encoding="utf-8")


def _launch_return_code(completed: subprocess.CompletedProcess[str]) -> int:
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return 0
    if completed.returncode > 1024 and "Launched as ID" in output:
        return 0
    return int(completed.returncode)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or launch RenderDoc capture for Crimson Desert.")
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--game-exe", default="")
    parser.add_argument("--renderdoccmd", default="")
    parser.add_argument("--capture-file", required=True)
    parser.add_argument("--game-arg", action="append", default=[])
    parser.add_argument("--pid", type=int, default=0, help="Inject RenderDoc into an existing PID instead of launching the game.")
    parser.add_argument("--temp-steam-appid", default="", help="Temporarily create/restore steam_appid.txt during launch.")
    parser.add_argument("--no-hook-children", action="store_true", help="Do not ask RenderDoc to hook child processes.")
    parser.add_argument("--no-ref-all-resources", action="store_true", help="Do not enable RenderDoc reference-all-resources capture option.")
    parser.add_argument("--no-capture-all-cmd-lists", action="store_true", help="Do not enable all-command-list capture option.")
    parser.add_argument("--allow-fullscreen", action="store_true", help="Do not ask RenderDoc to disallow fullscreen.")
    parser.add_argument("--soft-memory-limit-mb", type=int, default=0, help="RenderDoc soft memory limit in MB; 0 leaves default.")
    parser.add_argument(
        "--allow-amd-unknown-extensions",
        action="store_true",
        help="Temporarily enable RenderDoc AMD.ags.AllowUnknownExtensions during launch, then restore config.",
    )
    parser.add_argument("--renderdoc-config", default="", help="Override renderdoc.conf path for temporary config patching.")
    parser.add_argument("--out-plan-json", required=True)
    parser.add_argument("--launch", action="store_true", help="Actually launch renderdoccmd capture. Default is dry-run plan only.")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="Optional launch timeout; 0 waits for process exit.")
    parser.add_argument(
        "--post-launch-wait-seconds",
        type=float,
        default=0.0,
        help="Optional wait before restoring temp steam_appid.txt after renderdoccmd returns.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    game_root = Path(args.game_root)
    capture_file = Path(args.capture_file)
    plan = build_capture_plan(
        game_root=game_root,
        game_exe=Path(args.game_exe) if args.game_exe else None,
        capture_file=capture_file,
        renderdoccmd=Path(args.renderdoccmd) if args.renderdoccmd else None,
        game_args=tuple(args.game_arg or ()),
        pid=int(args.pid or 0) or None,
        temporary_steam_appid=str(args.temp_steam_appid or ""),
        hook_children=not bool(args.no_hook_children),
        ref_all_resources=not bool(args.no_ref_all_resources),
        capture_all_cmd_lists=not bool(args.no_capture_all_cmd_lists),
        disallow_fullscreen=not bool(args.allow_fullscreen),
        soft_memory_limit_mb=int(args.soft_memory_limit_mb or 0),
        allow_amd_unknown_extensions=bool(args.allow_amd_unknown_extensions),
        renderdoc_config=Path(args.renderdoc_config) if args.renderdoc_config else None,
    )
    out_plan = Path(args.out_plan_json)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    if not args.launch:
        print(f"wrote RenderDoc capture plan: {out_plan}")
        return 0 if plan["status"] == "ready" else 2
    if plan["status"] != "ready":
        print(f"RenderDoc capture blocked: {', '.join(str(item) for item in plan.get('blockers', []))}", file=sys.stderr)
        return 2
    capture_file.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    try:
        with temporary_renderdoc_ags_allow_unknown_extensions(
            bool(args.allow_amd_unknown_extensions),
            Path(args.renderdoc_config) if args.renderdoc_config else None,
        ):
            with temporary_steam_appid_file(game_root, str(args.temp_steam_appid or "")):
                completed = subprocess.run(
                    [str(part) for part in plan["command"]],
                    cwd=str(game_root),
                    env=env,
                    timeout=float(args.timeout_seconds) if float(args.timeout_seconds or 0) > 0 else None,
                    check=False,
                    capture_output=True,
                    text=True,
                    **hidden_subprocess_kwargs(),
                )
                if float(args.post_launch_wait_seconds or 0) > 0:
                    time.sleep(float(args.post_launch_wait_seconds))
    except (FileNotFoundError, ValueError) as exc:
        plan["launch_result"] = {
            "status": "config_patch_failed",
            "error": str(exc),
        }
        out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
        print(f"RenderDoc config patch failed: {exc}", file=sys.stderr)
        return 2
    except TimeoutExpired as exc:
        plan["launch_result"] = {
            "status": "timeout",
            "timeout_seconds": float(args.timeout_seconds or 0),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
        out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
        print("RenderDoc launch timed out", file=sys.stderr)
        return 124
    plan["launch_result"] = {
        "status": "started" if _launch_return_code(completed) == 0 else "failed",
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return _launch_return_code(completed)


if __name__ == "__main__":
    raise SystemExit(main())
