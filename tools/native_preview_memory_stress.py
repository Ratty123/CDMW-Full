from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.native_d3d11_host import find_native_d3d11_host


WM_COPYDATA = 0x004A
CDMW_COMMAND_COPYDATA = 0x43444D57
HOST_CLASS_NAME = "CDMWNativeD3D11PreviewWindow"
PRIVATE_GROWTH_LIMIT_BYTES = 150 * 1024 * 1024


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class CopyDataStruct(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_size_t),
        ("cbData", ctypes.c_uint),
        ("lpData", ctypes.c_void_p),
    ]


def process_memory_snapshot(pid: int) -> Dict[str, int]:
    if os.name != "nt":
        return {}
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCountersEx),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, int(pid))
        if not handle:
            return {}
        try:
            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return {}
            return {
                "working_set_bytes": int(counters.WorkingSetSize),
                "private_bytes": int(counters.PrivateUsage),
            }
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return {}


def write_bmp(path: Path, *, width: int, height: int, seed: int) -> None:
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        for x in range(width):
            r = (seed * 37 + x * 11) & 0xFF
            g = (seed * 53 + y * 17) & 0xFF
            b = (seed * 97 + x * 5 + y * 3) & 0xFF
            pixels.extend((b, g, r, 255))
    image_size = len(pixels)
    header_size = 14 + 40
    with path.open("wb") as stream:
        stream.write(struct.pack("<2sIHHI", b"BM", header_size + image_size, 0, 0, header_size))
        stream.write(struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, image_size, 0, 0, 0, 0))
        stream.write(pixels)


def write_geometry(path: Path) -> None:
    vertices = [
        (-0.70, -0.55, 0.0, 0.0, 0.0, 1.0, 1.0, 0.8, 0.8, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        (0.70, -0.55, 0.0, 0.0, 0.0, 1.0, 0.8, 1.0, 0.8, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, 0.65, 0.0, 0.0, 0.0, 1.0, 0.8, 0.8, 1.0, 0.5, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    ]
    with path.open("wb") as stream:
        for vertex in vertices:
            stream.write(struct.pack("<23f", *(tuple(vertex) + (0.0,) * 6)))


def write_package(root: Path, index: int) -> Path:
    package_dir = root / f"package_{index:03d}"
    package_dir.mkdir(parents=True, exist_ok=True)
    write_geometry(package_dir / "geometry.bin")
    write_bmp(package_dir / "base.bmp", width=64, height=64, seed=index)
    manifest = {
        "schema_version": 4,
        "backend": "d3d11",
        "vertex_count": 3,
        "face_count": 1,
        "batches": [
            {
                "index": 0,
                "vertex_file": "geometry.bin",
                "vertex_count": 3,
                "base_color": [1.0, 1.0, 1.0],
                "textures": {"base": "base.bmp"},
                "texture_flip_vertical": False,
                "has_texture_coordinates": True,
            }
        ],
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    return package_dir


def find_host_window(pid: int, *, timeout_seconds: float = 10.0) -> int:
    if os.name != "nt":
        raise RuntimeError("native D3D11 preview stress requires Windows")
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_windows = user32.EnumWindows
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    enum_windows.argtypes = [enum_windows_proc, ctypes.c_void_p]
    enum_windows.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        found = ctypes.c_void_p()

        @enum_windows_proc
        def callback(hwnd: int, _lparam: int) -> bool:
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            window_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) == int(pid) and class_name.value == HOST_CLASS_NAME:
                found.value = int(hwnd)
                return False
            return True

        enum_windows(callback, None)
        if found.value:
            return int(found.value)
        if kernel32.GetLastError():
            kernel32.SetLastError(0)
        time.sleep(0.05)
    raise TimeoutError("timed out waiting for D3D11 preview host window")


def send_command(hwnd: int, command: Mapping[str, Any]) -> None:
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    encoded = json.dumps(dict(command), separators=(",", ":")).encode("utf-8") + b"\0"
    buffer = ctypes.create_string_buffer(encoded)
    cds = CopyDataStruct(CDMW_COMMAND_COPYDATA, len(encoded), ctypes.cast(buffer, ctypes.c_void_p))
    user32.SendMessageW(ctypes.c_void_p(hwnd), WM_COPYDATA, 0, ctypes.byref(cds))


def wait_status(status_file: Path, event: str, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        if status_file.is_file():
            try:
                payload = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                last_payload = payload
                if str(payload.get("event", "")).strip().lower() == event:
                    return payload
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {event!r} in {status_file}; last={last_payload!r}")


def private_growth(samples: List[Mapping[str, Any]]) -> int:
    values = [
        int(sample.get("memory", {}).get("private_bytes", 0) or 0)
        for sample in samples
        if int(sample.get("memory", {}).get("private_bytes", 0) or 0) > 0
    ]
    if len(values) < 2:
        return 0
    return max(values) - min(values)


def run_stress(host_binary: Path, *, reloads: int, output: Path) -> Dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("native D3D11 preview memory stress requires Windows")
    temp_root = Path(tempfile.mkdtemp(prefix="cdmw_native_preview_stress_"))
    packages = [write_package(temp_root, index) for index in range(max(1, reloads))]
    status_files = [package / "host_status.json" for package in packages]
    diagnostic_log = temp_root / "native_events.jsonl"
    command = [
        str(host_binary),
        "--backend",
        "d3d11",
        "--preview-package",
        str(packages[0]),
        "--status-file",
        str(status_files[0]),
        "--diagnostic-log",
        str(diagnostic_log),
    ]
    process = subprocess.Popen(command)
    samples: List[Dict[str, Any]] = []
    clear_payload: Dict[str, Any] = {}
    try:
        wait_status(status_files[0], "loaded")
        hwnd = find_host_window(process.pid)
        samples.append(
            {
                "iteration": 0,
                "status": json.loads(status_files[0].read_text(encoding="utf-8")),
                "memory": process_memory_snapshot(process.pid),
            }
        )
        for index in range(1, reloads):
            send_command(
                hwnd,
                {
                    "command": "load_package",
                    "package_dir": str(packages[index]),
                    "status_file": str(status_files[index]),
                    "reset_view": False,
                },
            )
            status = wait_status(status_files[index], "loaded")
            samples.append(
                {
                    "iteration": index,
                    "status": status,
                    "memory": process_memory_snapshot(process.pid),
                }
            )
        clear_status = temp_root / "clear_status.json"
        send_command(hwnd, {"command": "clear_preview", "status_file": str(clear_status)})
        clear_payload = wait_status(clear_status, "cleared")
    finally:
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    warmup = min(10, max(0, len(samples) // 5))
    last_ten = samples[max(warmup, len(samples) - 10) :]
    growth = private_growth(last_ten)
    cache_entries = [
        int(sample.get("status", {}).get("texture_cache_entries", 0) or 0)
        for sample in samples[warmup:]
    ]
    cache_entry_limit = max(16, reloads * 4)
    result = {
        "host_binary": str(host_binary),
        "reloads": reloads,
        "temp_root": str(temp_root),
        "diagnostic_log": str(diagnostic_log),
        "private_growth_last_window_bytes": growth,
        "private_growth_limit_bytes": PRIVATE_GROWTH_LIMIT_BYTES,
        "texture_cache_entry_limit": cache_entry_limit,
        "max_texture_cache_entries_after_warmup": max(cache_entries or [0]),
        "clear_texture_cache_entries": int(clear_payload.get("texture_cache_entries", -1) or 0),
        "accepted": (
            growth <= PRIVATE_GROWTH_LIMIT_BYTES
            and max(cache_entries or [0]) <= cache_entry_limit
            and int(clear_payload.get("texture_cache_entries", -1) or 0) <= cache_entry_limit
        ),
        "samples": samples,
        "clear_status": clear_payload,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress reload the native D3D11 preview host and sample process memory.")
    parser.add_argument("--host", type=Path, default=None, help="Path to cdmw-d3d11-preview.exe")
    parser.add_argument("--reloads", type=int, default=50, help="Number of unique preview packages to load")
    parser.add_argument("--output", type=Path, default=Path("native_preview_memory_stress_result.json"))
    args = parser.parse_args()
    host = args.host or find_native_d3d11_host()
    if host is None or not Path(host).is_file():
        raise SystemExit("cdmw-d3d11-preview.exe was not found; build it or pass --host")
    result = run_stress(Path(host), reloads=max(1, int(args.reloads)), output=Path(args.output))
    print(json.dumps({k: result[k] for k in ("accepted", "private_growth_last_window_bytes", "max_texture_cache_entries_after_warmup", "clear_texture_cache_entries")}, indent=2))
    return 0 if result.get("accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
