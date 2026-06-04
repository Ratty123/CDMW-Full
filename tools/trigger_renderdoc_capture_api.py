from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.common import hidden_subprocess_kwargs


RENDERDOC_API_TRIGGER_SCHEMA_VERSION = 1


def rust_string_literal(value: object) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render_trigger_dll_source(*, capture_template: Path, marker_json: Path) -> str:
    capture_literal = rust_string_literal(capture_template)
    marker_literal = rust_string_literal(marker_json)
    return f'''#![allow(non_snake_case, non_camel_case_types, dead_code)]

use std::ffi::{{c_char, c_void}};
use std::fs;
use std::ptr::null_mut;

const DLL_PROCESS_ATTACH: u32 = 1;
const CAPTURE_TEMPLATE: &[u8] = b"{capture_literal}\\0";
const MARKER_PATH: &str = "{marker_literal}";

type HMODULE = *mut c_void;
type HANDLE = *mut c_void;
type DWORD = u32;
type BOOL = i32;

type GetApiFn = unsafe extern "C" fn(i32, *mut *mut c_void) -> i32;
type VoidFn = unsafe extern "C" fn();
type SetPathFn = unsafe extern "C" fn(*const c_char);
type GetNumCapturesFn = unsafe extern "C" fn() -> u32;

#[repr(C)]
struct RenderDocApi {{
    GetAPIVersion: *const c_void,
    SetCaptureOptionU32: *const c_void,
    SetCaptureOptionF32: *const c_void,
    GetCaptureOptionU32: *const c_void,
    GetCaptureOptionF32: *const c_void,
    SetFocusToggleKeys: *const c_void,
    SetCaptureKeys: *const c_void,
    GetOverlayBits: *const c_void,
    MaskOverlayBits: *const c_void,
    RemoveHooks: *const c_void,
    UnloadCrashHandler: *const c_void,
    SetCaptureFilePathTemplate: SetPathFn,
    GetCaptureFilePathTemplate: *const c_void,
    GetNumCaptures: GetNumCapturesFn,
    GetCapture: *const c_void,
    TriggerCapture: VoidFn,
}}

#[link(name = "kernel32")]
extern "system" {{
    fn DisableThreadLibraryCalls(hLibModule: HMODULE) -> BOOL;
    fn CreateThread(
        lpThreadAttributes: *mut c_void,
        dwStackSize: usize,
        lpStartAddress: Option<unsafe extern "system" fn(*mut c_void) -> DWORD>,
        lpParameter: *mut c_void,
        dwCreationFlags: DWORD,
        lpThreadId: *mut DWORD,
    ) -> HANDLE;
    fn CloseHandle(hObject: HANDLE) -> BOOL;
    fn GetModuleHandleA(lpModuleName: *const c_char) -> HMODULE;
    fn GetProcAddress(hModule: HMODULE, lpProcName: *const c_char) -> *mut c_void;
    fn Sleep(dwMilliseconds: DWORD);
}}

unsafe fn json_escape(value: &str) -> String {{
    value.replace('\\\\', "\\\\\\\\").replace('"', "\\\\\\"")
}}

unsafe fn write_marker(status: &str, detail: &str, before: u32, after: u32) {{
    let capture_template = String::from_utf8_lossy(&CAPTURE_TEMPLATE[..CAPTURE_TEMPLATE.len() - 1]);
    let payload = format!(
        "{{{{\\"status\\":\\"{{}}\\",\\"detail\\":\\"{{}}\\",\\"before\\":{{}},\\"after\\":{{}},\\"capture_template\\":\\"{{}}\\"}}}}",
        json_escape(status),
        json_escape(detail),
        before,
        after,
        json_escape(&capture_template),
    );
    let _ = fs::write(MARKER_PATH, payload);
}}

unsafe extern "system" fn worker(_: *mut c_void) -> DWORD {{
    let module = GetModuleHandleA(b"renderdoc.dll\\0".as_ptr() as *const c_char);
    if module.is_null() {{
        write_marker("blocked", "renderdoc.dll_not_loaded", 0, 0);
        return 2;
    }}
    let proc = GetProcAddress(module, b"RENDERDOC_GetAPI\\0".as_ptr() as *const c_char);
    if proc.is_null() {{
        write_marker("blocked", "RENDERDOC_GetAPI_not_found", 0, 0);
        return 3;
    }}
    let get_api: GetApiFn = std::mem::transmute(proc);
    let mut api_ptr: *mut c_void = null_mut();
    let ok = get_api(10600, &mut api_ptr as *mut *mut c_void);
    if ok == 0 || api_ptr.is_null() {{
        write_marker("blocked", "renderdoc_api_1_6_unavailable", 0, 0);
        return 4;
    }}
    let api = &*(api_ptr as *const RenderDocApi);
    (api.SetCaptureFilePathTemplate)(CAPTURE_TEMPLATE.as_ptr() as *const c_char);
    let before = (api.GetNumCaptures)();
    (api.TriggerCapture)();
    let mut after = before;
    for _ in 0..120 {{
        Sleep(500);
        after = (api.GetNumCaptures)();
        if after > before {{
            write_marker("triggered", "capture_count_increased", before, after);
            return 0;
        }}
    }}
    write_marker("triggered", "capture_requested_no_count_change", before, after);
    1
}}

#[no_mangle]
pub unsafe extern "system" fn DllMain(hinst: HMODULE, reason: DWORD, _reserved: *mut c_void) -> BOOL {{
    if reason == DLL_PROCESS_ATTACH {{
        DisableThreadLibraryCalls(hinst);
        let thread = CreateThread(null_mut(), 0, Some(worker), null_mut(), 0, null_mut());
        if !thread.is_null() {{
            CloseHandle(thread);
        }}
    }}
    1
}}
'''


def render_injector_source() -> str:
    return r'''#![allow(non_snake_case, non_camel_case_types)]

use std::env;
use std::ffi::{c_char, c_void};
use std::ffi::CString;
use std::ptr::null_mut;

type HANDLE = *mut c_void;
type DWORD = u32;
type BOOL = i32;
type LPVOID = *mut c_void;
type HMODULE = *mut c_void;
type SIZE_T = usize;

const PROCESS_CREATE_THREAD: DWORD = 0x0002;
const PROCESS_QUERY_INFORMATION: DWORD = 0x0400;
const PROCESS_VM_OPERATION: DWORD = 0x0008;
const PROCESS_VM_WRITE: DWORD = 0x0020;
const PROCESS_VM_READ: DWORD = 0x0010;
const MEM_COMMIT: DWORD = 0x1000;
const MEM_RESERVE: DWORD = 0x2000;
const PAGE_READWRITE: DWORD = 0x04;
const WAIT_OBJECT_0: DWORD = 0x00000000;
const INFINITE: DWORD = 0xFFFFFFFF;

#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(dwDesiredAccess: DWORD, bInheritHandle: BOOL, dwProcessId: DWORD) -> HANDLE;
    fn VirtualAllocEx(hProcess: HANDLE, lpAddress: LPVOID, dwSize: SIZE_T, flAllocationType: DWORD, flProtect: DWORD) -> LPVOID;
    fn WriteProcessMemory(hProcess: HANDLE, lpBaseAddress: LPVOID, lpBuffer: *const c_void, nSize: SIZE_T, lpNumberOfBytesWritten: *mut SIZE_T) -> BOOL;
    fn GetModuleHandleA(lpModuleName: *const c_char) -> HMODULE;
    fn GetProcAddress(hModule: HMODULE, lpProcName: *const c_char) -> *mut c_void;
    fn CreateRemoteThread(hProcess: HANDLE, lpThreadAttributes: LPVOID, dwStackSize: SIZE_T, lpStartAddress: Option<unsafe extern "system" fn(LPVOID) -> DWORD>, lpParameter: LPVOID, dwCreationFlags: DWORD, lpThreadId: *mut DWORD) -> HANDLE;
    fn WaitForSingleObject(hHandle: HANDLE, dwMilliseconds: DWORD) -> DWORD;
    fn GetExitCodeThread(hThread: HANDLE, lpExitCode: *mut DWORD) -> BOOL;
    fn CloseHandle(hObject: HANDLE) -> BOOL;
}

fn main() {
    let mut args = env::args().skip(1);
    let pid: DWORD = args.next().expect("pid").parse().expect("pid_u32");
    let dll = args.next().expect("dll_path");
    let dll_c = CString::new(dll).expect("dll path contains nul");
    unsafe {
        let access = PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ;
        let process = OpenProcess(access, 0, pid);
        if process.is_null() {
            eprintln!("OpenProcess failed");
            std::process::exit(2);
        }
        let remote = VirtualAllocEx(process, null_mut(), dll_c.as_bytes_with_nul().len(), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if remote.is_null() {
            eprintln!("VirtualAllocEx failed");
            CloseHandle(process);
            std::process::exit(3);
        }
        let mut written: SIZE_T = 0;
        if WriteProcessMemory(process, remote, dll_c.as_ptr() as *const c_void, dll_c.as_bytes_with_nul().len(), &mut written as *mut SIZE_T) == 0 {
            eprintln!("WriteProcessMemory failed");
            CloseHandle(process);
            std::process::exit(4);
        }
        let kernel32 = GetModuleHandleA(b"kernel32.dll\0".as_ptr() as *const c_char);
        let loadlib = GetProcAddress(kernel32, b"LoadLibraryA\0".as_ptr() as *const c_char);
        if loadlib.is_null() {
            eprintln!("LoadLibraryA not found");
            CloseHandle(process);
            std::process::exit(5);
        }
        let start: Option<unsafe extern "system" fn(LPVOID) -> DWORD> = Some(std::mem::transmute(loadlib));
        let thread = CreateRemoteThread(process, null_mut(), 0, start, remote, 0, null_mut());
        if thread.is_null() {
            eprintln!("CreateRemoteThread failed");
            CloseHandle(process);
            std::process::exit(6);
        }
        let wait = WaitForSingleObject(thread, INFINITE);
        let mut code: DWORD = 0;
        GetExitCodeThread(thread, &mut code as *mut DWORD);
        CloseHandle(thread);
        CloseHandle(process);
        if wait != WAIT_OBJECT_0 || code == 0 {
            eprintln!("LoadLibrary failed wait={} code={}", wait, code);
            std::process::exit(7);
        }
        println!("injected pid={} dll_handle={}", pid, code);
    }
}
'''


def build_trigger_plan(
    *,
    pid: int,
    capture_template: Path,
    marker_json: Path,
    work_dir: Path,
    rustc: str = "",
    tag: str = "",
) -> dict[str, object]:
    rustc_path = rustc or shutil.which("rustc") or ""
    capture_template = Path(capture_template).resolve()
    marker_json = Path(marker_json).resolve()
    work_dir = Path(work_dir).resolve()
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag.strip()) if tag else str(time.time_ns())
    src_dir = work_dir / "src"
    bin_dir = work_dir / "bin"
    dll_path = bin_dir / f"renderdoc_api_trigger_{safe_tag}.dll"
    injector_path = bin_dir / "renderdoc_injector.exe"
    blockers: list[str] = []
    if pid <= 0:
        blockers.append("invalid_pid")
    if not rustc_path:
        blockers.append("rustc_not_found")
    return {
        "schema_version": RENDERDOC_API_TRIGGER_SCHEMA_VERSION,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "pid": int(pid),
        "capture_template": str(capture_template),
        "marker_json": str(marker_json),
        "work_dir": str(work_dir),
        "tag": safe_tag,
        "rustc": rustc_path,
        "dll_source": str(src_dir / f"renderdoc_api_trigger_{safe_tag}.rs"),
        "injector_source": str(src_dir / "renderdoc_injector.rs"),
        "dll_path": str(dll_path),
        "injector_path": str(injector_path),
        "inject_command": [str(injector_path), str(int(pid)), str(dll_path)],
        "notes": [
            "Target process must already have renderdoc.dll loaded before graphics API initialization for useful captures.",
            "Use tools/capture_crimson_renderdoc_frame.py --temp-steam-appid for Steam builds that bounce through Steam.",
            "Generated DLL/EXE live in ignored .tmp paths and are not package artifacts.",
        ],
    }


def write_sources(plan: Mapping[str, object]) -> None:
    dll_source = Path(str(plan["dll_source"]))
    injector_source = Path(str(plan["injector_source"]))
    dll_source.parent.mkdir(parents=True, exist_ok=True)
    injector_source.parent.mkdir(parents=True, exist_ok=True)
    capture_template = Path(str(plan["capture_template"]))
    marker_json = Path(str(plan["marker_json"]))
    dll_source.write_text(
        render_trigger_dll_source(capture_template=capture_template, marker_json=marker_json),
        encoding="utf-8",
    )
    injector_source.write_text(render_injector_source(), encoding="utf-8")


def build_artifacts(plan: Mapping[str, object]) -> None:
    write_sources(plan)
    rustc = str(plan["rustc"])
    dll_source = str(plan["dll_source"])
    injector_source = str(plan["injector_source"])
    dll_path = Path(str(plan["dll_path"]))
    injector_path = Path(str(plan["injector_path"]))
    dll_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [rustc, dll_source, "--edition=2021", "--crate-type", "cdylib", "-C", "linker=rust-lld", "-o", str(dll_path)],
        check=True,
        **hidden_subprocess_kwargs(),
    )
    subprocess.run(
        [rustc, injector_source, "--edition=2021", "-C", "linker=rust-lld", "-o", str(injector_path)],
        check=True,
        **hidden_subprocess_kwargs(),
    )


def inject_and_wait(plan: Mapping[str, object], timeout_seconds: float) -> dict[str, object]:
    marker = Path(str(plan["marker_json"]))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(part) for part in plan["inject_command"]],
        check=False,
        capture_output=True,
        text=True,
        **hidden_subprocess_kwargs(),
    )
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    marker_payload: dict[str, object] = {}
    while time.monotonic() <= deadline:
        if marker.is_file():
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
            break
        time.sleep(0.25)
    result = dict(plan)
    result["inject_result"] = {
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "marker": marker_payload,
    }
    if completed.returncode != 0:
        result["status"] = "inject_failed"
    elif not marker_payload:
        result["status"] = "marker_timeout"
    elif marker_payload.get("status") == "triggered" and marker_payload.get("detail") == "capture_count_increased":
        result["status"] = "capture_triggered"
    else:
        result["status"] = "capture_requested"
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trigger RenderDoc capture inside an already injected process.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--capture-template", required=True, help="RenderDoc capture path template, without frame suffix.")
    parser.add_argument("--marker-json", required=True)
    parser.add_argument("--work-dir", default=str(REPO_ROOT / ".tmp_crimson_shader_corpus" / "renderdoc_api_trigger"))
    parser.add_argument("--rustc", default="")
    parser.add_argument("--tag", default="", help="Optional unique DLL tag. Defaults to a timestamp nonce.")
    parser.add_argument("--out-plan-json", required=True)
    parser.add_argument("--inject", action="store_true", help="Build and inject helper DLL. Default writes dry-run plan only.")
    parser.add_argument("--timeout-seconds", type=float, default=75.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    plan = build_trigger_plan(
        pid=int(args.pid),
        capture_template=Path(args.capture_template),
        marker_json=Path(args.marker_json),
        work_dir=Path(args.work_dir),
        rustc=str(args.rustc or ""),
        tag=str(args.tag or ""),
    )
    out_plan = Path(args.out_plan_json)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    if plan["status"] != "ready":
        print(f"RenderDoc API trigger blocked: {', '.join(str(item) for item in plan['blockers'])}", file=sys.stderr)
        return 2
    if not args.inject:
        print(f"wrote RenderDoc API trigger plan: {out_plan}")
        return 0
    Path(args.capture_template).parent.mkdir(parents=True, exist_ok=True)
    build_artifacts(plan)
    result = inject_and_wait(plan, timeout_seconds=float(args.timeout_seconds))
    out_plan.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result.get("inject_result", {}), indent=2, sort_keys=True))
    if result["status"] == "capture_triggered":
        return 0
    if result["status"] == "capture_requested":
        return 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
