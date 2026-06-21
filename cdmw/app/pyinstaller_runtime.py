from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Mapping, Optional


PYINSTALLER_RUNTIME_MARKER = "cdmw_pyinstaller_runtime.json"
PYINSTALLER_STALE_UNMARKED_MIN_AGE_SECONDS = 30 * 60


def current_pyinstaller_meipass() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    try:
        return Path(str(meipass)).resolve()
    except OSError:
        return Path(str(meipass))


def runtime_marker_path(runtime_dir: Path) -> Path:
    return runtime_dir / PYINSTALLER_RUNTIME_MARKER


def write_current_pyinstaller_runtime_marker(current_meipass: Optional[Path] = None) -> None:
    runtime_dir = current_meipass or current_pyinstaller_meipass()
    if runtime_dir is None:
        return
    try:
        payload = {
            "app": "CrimsonDesertModWorkbench",
            "pid": os.getpid(),
            "created_at": time.time(),
            "executable": str(Path(sys.executable).resolve()),
        }
        marker_path = runtime_marker_path(runtime_dir)
        temp_path = marker_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(marker_path)
    except Exception:
        pass


def read_pyinstaller_runtime_marker(runtime_dir: Path) -> Mapping[str, object]:
    try:
        marker_path = runtime_marker_path(runtime_dir)
        if not marker_path.is_file():
            return {}
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data if isinstance(data, Mapping) else {}
    except Exception:
        return {}


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def is_own_pyinstaller_runtime_dir(runtime_dir: Path) -> bool:
    if not runtime_dir.name.startswith("_MEI"):
        return False
    marker = read_pyinstaller_runtime_marker(runtime_dir)
    if marker.get("app") == "CrimsonDesertModWorkbench":
        return True
    return (runtime_dir / "assets" / "cdmw.ico").is_file() or (runtime_dir / "assets" / "cdmw.png").is_file()


def cleanup_stale_pyinstaller_runtime_dirs(
    *,
    temp_root: Optional[Path] = None,
    current_meipass: Optional[Path] = None,
    now: Optional[float] = None,
    unmarked_min_age_seconds: float = PYINSTALLER_STALE_UNMARKED_MIN_AGE_SECONDS,
) -> tuple[int, int]:
    current_runtime_dir = current_meipass or current_pyinstaller_meipass()
    if temp_root is None:
        if current_runtime_dir is None:
            return 0, 0
        temp_root = current_runtime_dir.parent
    current_time = time.time() if now is None else float(now)
    removed = 0
    failed = 0
    try:
        candidates = list(temp_root.iterdir())
    except OSError:
        return removed, failed
    try:
        current_resolved = current_runtime_dir.resolve() if current_runtime_dir is not None else None
    except OSError:
        current_resolved = current_runtime_dir
    for candidate in candidates:
        try:
            if not candidate.is_dir() or not candidate.name.startswith("_MEI"):
                continue
            try:
                candidate_resolved = candidate.resolve()
            except OSError:
                candidate_resolved = candidate
            if current_resolved is not None and candidate_resolved == current_resolved:
                continue
            if not is_own_pyinstaller_runtime_dir(candidate):
                continue
            marker = read_pyinstaller_runtime_marker(candidate)
            should_remove = False
            if marker.get("app") == "CrimsonDesertModWorkbench":
                try:
                    marker_pid = int(marker.get("pid", 0) or 0)
                except (TypeError, ValueError):
                    marker_pid = 0
                should_remove = not pid_is_alive(marker_pid)
            else:
                try:
                    age_seconds = current_time - float(candidate.stat().st_mtime)
                except OSError:
                    age_seconds = 0.0
                should_remove = age_seconds >= float(unmarked_min_age_seconds)
            if not should_remove:
                continue
            shutil.rmtree(candidate)
            removed += 1
        except Exception:
            failed += 1
    return removed, failed


def prepare_pyinstaller_runtime_temp_cleanup() -> None:
    current_meipass = current_pyinstaller_meipass()
    if current_meipass is None:
        return
    write_current_pyinstaller_runtime_marker(current_meipass)
    cleanup_stale_pyinstaller_runtime_dirs(current_meipass=current_meipass)
