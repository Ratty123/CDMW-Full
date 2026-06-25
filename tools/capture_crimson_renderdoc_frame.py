from __future__ import annotations

from contextlib import contextmanager
import argparse
import json
from pathlib import Path
import shutil
from typing import Any, Iterator, Sequence


DEFAULT_RENDERDOCCMD = Path(".tools/renderdoc/1.44/RenderDoc_1.44_64/renderdoccmd.exe")


def _path(value: object) -> str:
    return str(Path(value))


def find_renderdoccmd() -> str:
    local = Path.cwd() / DEFAULT_RENDERDOCCMD
    if local.is_file():
        return str(local)
    return shutil.which("renderdoccmd") or ""


def build_capture_command(
    *,
    renderdoccmd: Path,
    game_exe: Path,
    capture_file: Path,
    working_dir: Path,
    game_args: Sequence[str] = (),
    hook_children: bool = True,
    ref_all_resources: bool = False,
    capture_all_cmd_lists: bool = False,
    disallow_fullscreen: bool = True,
    soft_memory_limit_mb: int | None = 4096,
    wait_for_exit: bool = False,
) -> list[str]:
    command = [_path(renderdoccmd), "capture", "--capture-file", _path(capture_file), "--working-dir", _path(working_dir)]
    if wait_for_exit:
        command.append("--wait-for-exit")
    if hook_children:
        command.append("--opt-hook-children")
    if disallow_fullscreen:
        command.append("--opt-disallow-fullscreen")
    if ref_all_resources:
        command.append("--opt-ref-all-resources")
    if capture_all_cmd_lists:
        command.append("--opt-capture-all-cmd-lists")
    if soft_memory_limit_mb:
        command += ["--opt-soft-memory-limit", str(int(soft_memory_limit_mb))]
    return command + [_path(game_exe), *[str(arg) for arg in game_args]]


def build_inject_command(
    *,
    renderdoccmd: Path,
    pid: int,
    capture_file: Path,
    working_dir: Path,
    hook_children: bool = True,
    soft_memory_limit_mb: int | None = 4096,
) -> list[str]:
    command = [_path(renderdoccmd), "inject", f"--PID={int(pid)}", "--capture-file", _path(capture_file), "--working-dir", _path(working_dir)]
    if hook_children:
        command.append("--opt-hook-children")
    if soft_memory_limit_mb:
        command += ["--opt-soft-memory-limit", str(int(soft_memory_limit_mb))]
    return command


@contextmanager
def temporary_steam_appid_file(game_root: Path, appid: str = "3321460") -> Iterator[None]:
    path = Path(game_root) / "steam_appid.txt"
    existed = path.exists()
    original = path.read_bytes() if existed else b""
    path.write_text(f"{appid}\n", encoding="ascii")
    try:
        yield
    finally:
        if existed:
            path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)


def renderdoc_ags_allow_unknown_patch_status(config: Path) -> dict[str, Any]:
    path = Path(config)
    if not path.is_file():
        return {"status": "blocked", "blocker": "renderdoc_config_not_found", "path": str(path)}
    text = path.read_text(encoding="utf-8")
    if "AllowUnknownExtensions" not in text:
        return {"status": "blocked", "blocker": "renderdoc_ags_setting_not_found", "path": str(path)}
    return {"status": "ready", "path": str(path)}


@contextmanager
def temporary_renderdoc_ags_allow_unknown_extensions(enabled: bool, config: Path) -> Iterator[None]:
    path = Path(config)
    original = path.read_text(encoding="utf-8")
    if enabled:
        text = original.replace(
            '<AllowUnknownExtensions type="Boolean">false</AllowUnknownExtensions>',
            '<AllowUnknownExtensions type="Boolean">true</AllowUnknownExtensions>',
        )
        path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def build_capture_plan(
    *,
    game_root: Path,
    capture_file: Path,
    renderdoccmd: Path | None = None,
    game_exe: Path | None = None,
    pid: int | None = None,
    game_args: Sequence[str] = (),
    hook_children: bool = True,
    ref_all_resources: bool = False,
    capture_all_cmd_lists: bool = False,
    disallow_fullscreen: bool = True,
    soft_memory_limit_mb: int | None = 4096,
    allow_amd_unknown_extensions: bool = False,
    renderdoc_config: Path | None = None,
    wait_for_exit: bool = False,
) -> dict[str, Any]:
    root = Path(game_root)
    rd = Path(renderdoccmd or find_renderdoccmd())
    exe = Path(game_exe) if game_exe else root / "bin64" / "CrimsonDesert.exe"
    blockers: list[str] = []
    if not rd.is_file():
        blockers.append("renderdoccmd_not_found")
    if not pid and not exe.is_file():
        blockers.append("game_exe_missing")
    patch = {"allow_amd_unknown_extensions": bool(allow_amd_unknown_extensions), "status": "not_requested"}
    if allow_amd_unknown_extensions and renderdoc_config:
        patch = {**patch, **renderdoc_ags_allow_unknown_patch_status(Path(renderdoc_config))}
        if patch.get("status") != "ready":
            blockers.append(str(patch.get("blocker", "renderdoc_config_patch_unavailable")))
    command = (
        build_inject_command(
            renderdoccmd=rd,
            pid=int(pid),
            capture_file=Path(capture_file),
            working_dir=root,
            hook_children=hook_children,
            soft_memory_limit_mb=soft_memory_limit_mb,
        )
        if pid
        else build_capture_command(
            renderdoccmd=rd,
            game_exe=exe,
            capture_file=Path(capture_file),
            working_dir=root,
            game_args=game_args,
            hook_children=hook_children,
            ref_all_resources=ref_all_resources,
            capture_all_cmd_lists=capture_all_cmd_lists,
            disallow_fullscreen=disallow_fullscreen,
            soft_memory_limit_mb=soft_memory_limit_mb,
            wait_for_exit=wait_for_exit,
        )
    )
    return {
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "command_kind": "inject" if pid else "capture",
        "command": command,
        "game_root": str(root),
        "game_exe": str(exe),
        "capture_file": str(Path(capture_file)),
        "renderdoccmd": str(rd),
        "options": {
            "hook_children": hook_children,
            "ref_all_resources": ref_all_resources,
            "capture_all_cmd_lists": capture_all_cmd_lists,
            "disallow_fullscreen": disallow_fullscreen,
            "soft_memory_limit_mb": soft_memory_limit_mb,
            "wait_for_exit": wait_for_exit,
        },
        "renderdoc_config_patch": patch,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--game-exe", type=Path)
    parser.add_argument("--capture-file", type=Path, required=True)
    parser.add_argument("--renderdoccmd", type=Path)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--out-plan-json", type=Path)
    args = parser.parse_args(argv)
    plan = build_capture_plan(
        game_root=args.game_root,
        game_exe=args.game_exe,
        capture_file=args.capture_file,
        renderdoccmd=args.renderdoccmd,
        pid=args.pid,
    )
    if args.out_plan_json:
        args.out_plan_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_plan_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return 0 if plan["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
