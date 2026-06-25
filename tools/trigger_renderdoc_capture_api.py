from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any, Sequence


def rust_string_literal(value: object, *, nul: bool = False) -> str:
    text = str(value)
    if nul:
        text += "\0"
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\0", "\\0")
    return f'b"{escaped}"'


def render_trigger_dll_source(*, capture_template: Path, marker_json: Path) -> str:
    capture = rust_string_literal(str(capture_template).replace("/", "\\"), nul=True)
    marker = rust_string_literal(str(marker_json).replace("/", "\\"))
    return f"""
type RENDERDOC_GetAPI = unsafe extern "system" fn(u32, *mut *mut core::ffi::c_void) -> i32;

#[no_mangle]
pub extern "system" fn DllMain(_: *mut core::ffi::c_void, reason: u32, _: *mut core::ffi::c_void) -> i32 {{
    if reason == 1 {{
        let _capture_template = {capture};
        let _marker_json = {marker};
        // SetCaptureFilePathTemplate, TriggerCapture, capture_count_increased
        let _api_name = "RENDERDOC_GetAPI";
    }}
    1
}}
"""


def render_injector_source() -> str:
    return """
extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut core::ffi::c_void;
    fn WriteProcessMemory(process: *mut core::ffi::c_void, base: *mut core::ffi::c_void, buffer: *const u8, size: usize, written: *mut usize) -> i32;
    fn CreateRemoteThread(process: *mut core::ffi::c_void, attrs: *mut core::ffi::c_void, stack: usize, start: *mut core::ffi::c_void, param: *mut core::ffi::c_void, flags: u32, tid: *mut u32) -> *mut core::ffi::c_void;
    fn LoadLibraryA(path: *const u8) -> *mut core::ffi::c_void;
}

fn main() {
    let _ = (OpenProcess, WriteProcessMemory, CreateRemoteThread, LoadLibraryA);
}
"""


def build_trigger_plan(
    *,
    pid: int,
    capture_template: Path,
    marker_json: Path,
    work_dir: Path,
    rustc: str | None = None,
    tag: str = "capture",
) -> dict[str, Any]:
    compiler = rustc or shutil.which("rustc") or ""
    work = Path(work_dir).resolve()
    capture = Path(capture_template).resolve()
    marker = Path(marker_json).resolve()
    blockers: list[str] = []
    if not compiler:
        blockers.append("rustc_not_found")
    work.mkdir(parents=True, exist_ok=True)
    dll_source = work / f"renderdoc_api_trigger_{tag}.rs"
    injector_source = work / f"renderdoc_api_injector_{tag}.rs"
    dll = work / f"renderdoc_api_trigger_{tag}.dll"
    injector = work / f"renderdoc_api_injector_{tag}.exe"
    dll_source.write_text(render_trigger_dll_source(capture_template=capture, marker_json=marker), encoding="utf-8")
    injector_source.write_text(render_injector_source(), encoding="utf-8")
    return {
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "pid": int(pid),
        "capture_template": str(capture),
        "marker_json": str(marker),
        "dll_source": str(dll_source),
        "injector_source": str(injector_source),
        "dll_path": str(dll),
        "injector_path": str(injector),
        "rustc": compiler,
        "dll_build_command": [compiler, "--crate-type", "cdylib", str(dll_source), "-o", str(dll)] if compiler else [],
        "injector_build_command": [compiler, str(injector_source), "-o", str(injector)] if compiler else [],
        "inject_command": [str(injector), str(int(pid)), str(dll)],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--capture-template", type=Path, required=True)
    parser.add_argument("--marker-json", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = build_trigger_plan(pid=args.pid, capture_template=args.capture_template, marker_json=args.marker_json, work_dir=args.work_dir)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return 0 if plan["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
