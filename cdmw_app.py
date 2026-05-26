#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Callable, Mapping, Optional, Sequence


PYINSTALLER_RUNTIME_MARKER = "cdmw_pyinstaller_runtime.json"
PYINSTALLER_STALE_UNMARKED_MIN_AGE_SECONDS = 30 * 60
APP_SINGLE_INSTANCE_MUTEX_NAME = "Local\\CrimsonDesertModWorkbench.SingleInstance"
STARTUP_SPLASH_COMMAND_FILE_ENV = "CDMW_STARTUP_SPLASH_COMMAND_FILE"

_single_instance_mutex_handle: Optional[int] = None
_single_instance_lock_handle: Optional[object] = None
_startup_maintenance_thread: Optional[threading.Thread] = None
_startup_splash_command_file: Optional[Path] = None
_startup_splash_process: Optional[subprocess.Popen[object]] = None


def _bootstrap_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _write_bootstrap_report(kind: str, title: str, body: str) -> None:
    try:
        report_dir = _bootstrap_root() / "crash_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1000):03d}"
        report_path = report_dir / f"{kind}_{timestamp}_{os.getpid()}.log"
        lines = [
            "Crimson Desert Mod Workbench bootstrap report",
            f"Kind: {kind}",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Process ID: {os.getpid()}",
            f"Python: {sys.version}",
            f"Platform: {platform.platform()}",
            "",
            title,
            "",
            body.rstrip(),
        ]
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def _current_pyinstaller_meipass() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    try:
        return Path(str(meipass)).resolve()
    except OSError:
        return Path(str(meipass))


def _runtime_marker_path(runtime_dir: Path) -> Path:
    return runtime_dir / PYINSTALLER_RUNTIME_MARKER


def _write_current_pyinstaller_runtime_marker(current_meipass: Optional[Path] = None) -> None:
    runtime_dir = current_meipass or _current_pyinstaller_meipass()
    if runtime_dir is None:
        return
    try:
        payload = {
            "app": "CrimsonDesertModWorkbench",
            "pid": os.getpid(),
            "created_at": time.time(),
            "executable": str(Path(sys.executable).resolve()),
        }
        marker_path = _runtime_marker_path(runtime_dir)
        temp_path = marker_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(marker_path)
    except Exception:
        pass


def _read_pyinstaller_runtime_marker(runtime_dir: Path) -> Mapping[str, object]:
    try:
        marker_path = _runtime_marker_path(runtime_dir)
        if not marker_path.is_file():
            return {}
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data if isinstance(data, Mapping) else {}
    except Exception:
        return {}


def _pid_is_alive(pid: int) -> bool:
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


def _is_own_pyinstaller_runtime_dir(runtime_dir: Path) -> bool:
    if not runtime_dir.name.startswith("_MEI"):
        return False
    marker = _read_pyinstaller_runtime_marker(runtime_dir)
    if marker.get("app") == "CrimsonDesertModWorkbench":
        return True
    return (runtime_dir / "assets" / "cdmw.ico").is_file() or (runtime_dir / "assets" / "cdmw.png").is_file()


def _cleanup_stale_pyinstaller_runtime_dirs(
    *,
    temp_root: Optional[Path] = None,
    current_meipass: Optional[Path] = None,
    now: Optional[float] = None,
    unmarked_min_age_seconds: float = PYINSTALLER_STALE_UNMARKED_MIN_AGE_SECONDS,
) -> tuple[int, int]:
    current_runtime_dir = current_meipass or _current_pyinstaller_meipass()
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
    current_resolved: Optional[Path]
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
            if not _is_own_pyinstaller_runtime_dir(candidate):
                continue
            marker = _read_pyinstaller_runtime_marker(candidate)
            should_remove = False
            if marker.get("app") == "CrimsonDesertModWorkbench":
                try:
                    marker_pid = int(marker.get("pid", 0) or 0)
                except (TypeError, ValueError):
                    marker_pid = 0
                should_remove = not _pid_is_alive(marker_pid)
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


def _prepare_pyinstaller_runtime_temp_cleanup() -> None:
    current_meipass = _current_pyinstaller_meipass()
    if current_meipass is None:
        return
    _write_current_pyinstaller_runtime_marker(current_meipass)
    _cleanup_stale_pyinstaller_runtime_dirs(current_meipass=current_meipass)


def _prepare_app_temp_cache_cleanup() -> None:
    try:
        from cdmw.constants import ARCHIVE_SCAN_CACHE_DIRNAME
        from cdmw.core.temp_cache import APP_TEMP_CACHE_ROOT_ENV, app_temp_root, prune_app_temp_cache

        legacy_temp_root = app_temp_root()
        os.environ.setdefault(APP_TEMP_CACHE_ROOT_ENV, str(_bootstrap_root() / ARCHIVE_SCAN_CACHE_DIRNAME))
        prune_app_temp_cache()
        prune_app_temp_cache(root=legacy_temp_root)
    except Exception:
        pass


def _run_startup_maintenance() -> None:
    _prepare_pyinstaller_runtime_temp_cleanup()
    _prepare_app_temp_cache_cleanup()


def _schedule_startup_maintenance(*, delay_seconds: float = 6.0) -> None:
    global _startup_maintenance_thread
    if _startup_maintenance_thread is not None and _startup_maintenance_thread.is_alive():
        return

    def _worker() -> None:
        try:
            delay = max(0.0, float(delay_seconds))
            if delay:
                time.sleep(delay)
            _run_startup_maintenance()
        except Exception:
            pass

    thread = threading.Thread(target=_worker, name="CDMWStartupMaintenance", daemon=True)
    _startup_maintenance_thread = thread
    thread.start()


def _acquire_single_instance_guard() -> bool:
    global _single_instance_mutex_handle, _single_instance_lock_handle
    if os.name != "nt":
        return True
    mutex_acquired = False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        handle = kernel32.CreateMutexW(None, True, APP_SINGLE_INSTANCE_MUTEX_NAME)
        if handle:
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            _single_instance_mutex_handle = int(handle)
            mutex_acquired = True
    except Exception:
        pass
    try:
        import msvcrt

        lock_dir = Path(tempfile.gettempdir()) / "CrimsonDesertModWorkbench"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "single_instance.lock"
        lock_path.touch(exist_ok=True)
        lock_handle = lock_path.open("r+b")
        try:
            lock_handle.seek(0, os.SEEK_END)
            if lock_handle.tell() <= 0:
                lock_handle.write(b"\0")
                lock_handle.flush()
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_handle.close()
            if mutex_acquired:
                _release_single_instance_guard()
            return False
        _single_instance_lock_handle = lock_handle
        try:
            lock_handle.seek(0)
            lock_handle.truncate()
            lock_handle.write(f"{os.getpid()}\n{time.time():.3f}\n".encode("ascii", "ignore"))
            lock_handle.flush()
        except Exception:
            pass
        return True
    except Exception:
        return bool(mutex_acquired)


def _release_single_instance_guard() -> None:
    global _single_instance_mutex_handle, _single_instance_lock_handle
    lock_handle = _single_instance_lock_handle
    if lock_handle is not None:
        try:
            import msvcrt

            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            lock_handle.close()
        except Exception:
            pass
        _single_instance_lock_handle = None
    handle = _single_instance_mutex_handle
    if not handle or os.name != "nt":
        _single_instance_mutex_handle = None
        return
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    _single_instance_mutex_handle = None


def _update_pyinstaller_boot_splash(text: str) -> None:
    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.update_text(str(text))
    except Exception:
        pass


def _write_startup_splash_command(
    path: Path,
    *,
    detail: str,
    current: int = 0,
    total: int = 0,
    closed: bool = False,
) -> None:
    try:
        payload = {
            "detail": str(detail or "Starting application..."),
            "current": max(0, int(current or 0)),
            "total": max(0, int(total or 0)),
            "closed": bool(closed),
            "updated_at": time.time(),
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass


def _startup_splash_host_command(command_file: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            str(Path(sys.executable).resolve()),
            "--startup-splash-host",
            str(command_file),
            "--parent-pid",
            str(os.getpid()),
        ]
    return [
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve()),
        "--startup-splash-host",
        str(command_file),
        "--parent-pid",
        str(os.getpid()),
    ]


def _start_external_startup_splash() -> Optional[Path]:
    global _startup_splash_command_file, _startup_splash_process
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE") == "1":
        return None
    try:
        splash_dir = Path(tempfile.gettempdir()) / "CrimsonDesertModWorkbench" / "startup_splash"
        splash_dir.mkdir(parents=True, exist_ok=True)
        command_file = splash_dir / f"splash_{os.getpid()}_{int(time.time() * 1000)}.json"
        _write_startup_splash_command(command_file, detail="Starting application...")
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        _startup_splash_process = subprocess.Popen(
            _startup_splash_host_command(command_file),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        ready_path = command_file.with_suffix(".ready")
        deadline = time.monotonic() + 1.25
        while time.monotonic() < deadline:
            if ready_path.exists():
                break
            if _startup_splash_process.poll() is not None:
                break
            time.sleep(0.025)
        if _startup_splash_process.poll() is None:
            _startup_splash_command_file = command_file
            os.environ[STARTUP_SPLASH_COMMAND_FILE_ENV] = str(command_file)
            return command_file
        _startup_splash_process = None
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        return None
    except Exception:
        os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)
        return None


def _close_external_startup_splash() -> None:
    global _startup_splash_command_file
    command_file = _startup_splash_command_file
    if command_file is None:
        return
    _write_startup_splash_command(command_file, detail="Opening workspace...", closed=True)
    os.environ.pop(STARTUP_SPLASH_COMMAND_FILE_ENV, None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Crimson Desert Mod Workbench")
    parser.add_argument("--cli", action="store_true", help="Run the command-line workflow using the top-level defaults.")
    parser.add_argument("--gui", action="store_true", help="Force the GUI workflow.")
    parser.add_argument("--isolated-renderer-host", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--backend", default="d3d11", choices=("d3d11", "vulkan"), help=argparse.SUPPRESS)
    parser.add_argument("--preview-package", default="", help=argparse.SUPPRESS)
    parser.add_argument("--status-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--theme-background", default="", help=argparse.SUPPRESS)
    parser.add_argument("--theme-text", default="", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-splash-host", default="", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.startup_splash_host:
        from cdmw.ui.startup_splash_host import run_startup_splash_host

        return run_startup_splash_host(Path(args.startup_splash_host), parent_pid=int(args.parent_pid or 0))

    if args.cli and args.gui:
        parser.error("Choose only one of --cli or --gui.")
    if args.isolated_renderer_host and (args.cli or args.gui):
        parser.error("Choose isolated renderer host without --cli or --gui.")

    run_gui_mode = not args.cli and not args.isolated_renderer_host
    if run_gui_mode:
        if not _acquire_single_instance_guard():
            _update_pyinstaller_boot_splash("Already running.")
            return 0
        _write_current_pyinstaller_runtime_marker()
        _start_external_startup_splash()
        _schedule_startup_maintenance()
        _update_pyinstaller_boot_splash("Loading...")
    elif args.cli:
        _run_startup_maintenance()

    try:
        if args.isolated_renderer_host:
            from cdmw.rendering.qtquick3d_isolated_host import run_isolated_renderer_host

            host_args = ["--backend", args.backend]
            if args.preview_package:
                host_args.extend(["--preview-package", args.preview_package])
            if args.status_file:
                host_args.extend(["--status-file", args.status_file])
            if args.theme_background:
                host_args.extend(["--theme-background", args.theme_background])
            if args.theme_text:
                host_args.extend(["--theme-text", args.theme_text])
            if args.self_test:
                host_args.append("--self-test")
            runner = lambda: run_isolated_renderer_host(host_args)
        elif args.cli:
            from cdmw.core.pipeline import run_cli

            runner: Callable[[], int] = run_cli
        else:
            from cdmw.ui.main_window import run_gui

            runner = run_gui
        return runner()
    except Exception:
        _write_bootstrap_report(
            "bootstrap_failure",
            "Application failed before the normal crash reporter completed startup",
            traceback.format_exc(),
        )
        raise
    finally:
        if run_gui_mode:
            _close_external_startup_splash()
            _release_single_instance_guard()


if __name__ == "__main__":
    raise SystemExit(main())
