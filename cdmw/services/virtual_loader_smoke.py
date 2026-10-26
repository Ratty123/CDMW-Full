"""Headless launch check for a published launcher profile.

Starts the game the way a player or DMM does (through Steam), waits for the
runtime's own report and trace, closes only the process that report names, and
proves the installation's index files are unchanged afterwards. It sends no
input and captures no screen.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Callable

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_standalone import (
    STANDALONE_PATH, STATUS_PATH, TRACE_PATH, read_standalone_status, read_standalone_trace, standalone_published)
from cdmw.services.virtual_loader_state import load_profile, target

STEAM_URL = 'steam://rungameid/3321460'
GAME_PATH = 'bin64/CrimsonDesert.exe'
FIXED_FILES = ('meta/0.papgt', 'meta/0.pathc', 'bin64/CDMWVirtualLoader.asi', 'bin64/winmm.dll', STANDALONE_PATH)


@dataclass
class SmokeHooks:
    launch: Callable[[], None]
    alive: Callable[[int], bool]
    image: Callable[[int], str]
    close: Callable[[int, float], str]
    running: Callable[[], list]
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


def protected_files(root):
    """Index files a correct virtual launch must never change."""
    root = Path(root)
    groups = sorted(p.name for p in root.iterdir() if p.is_dir() and len(p.name) == 4 and p.name.isdigit())
    return list(FIXED_FILES) + [f'{group}/0.pamt' for group in groups]


def fingerprint(root, relatives):
    return {relative: (hash_file(path) if (path := target(root, relative)).is_file() else None) for relative in relatives}


def expected_redirects(profile):
    """Logical files the game must open through the runtime at startup."""
    files = profile['files']
    wanted = ['meta/0.papgt'] if 'meta/0.papgt' in files else []
    return wanted + sorted(path for path in files if path.endswith('/0.pamt'))


def _matches(path, logical):
    path, logical = path.replace('/', '\\').lower(), logical.replace('/', '\\').lower()
    return path == logical or path.endswith('\\' + logical)


def trace_evidence(rows, expected, files=()):
    redirected = [row for row in rows if row.redirected]
    def seen(logical):
        return any(_matches(row.path, logical) for row in redirected)
    return {
        'rows': len(rows),
        'hooks_ready': any(row.operation == 'file hooks ready' for row in rows),
        'redirected': len(redirected),
        'expected': {logical: seen(logical) for logical in expected},
        # Informational: which other profile files the game opened before the test closed it.
        'profile_files_opened': sorted(logical for logical in files if seen(logical)),
        'redirected_paths': sorted({row.path for row in redirected})[:64],
    }


def _status_value(status):
    return None if status is None else {'state': status.state, 'pid': status.pid, 'generation': status.generation,
                                        'elapsed_ms': status.elapsed_ms, 'detail': status.detail}


def run_smoke(root, *, hooks=None, start_timeout=240.0, evidence_timeout=120.0, hold=20.0, close_timeout=60.0):
    """Launch once, collect the runtime's evidence, close the game and compare the protected files."""
    root = Path(root).resolve()
    hooks = hooks or windows_hooks(root)
    if hooks.running():
        raise VirtualLoaderError('Close Crimson Desert before running the smoke test.')
    if not standalone_published(root):
        raise VirtualLoaderError('Publish the launcher profile first.')
    profile = load_profile(root)
    if not profile:
        raise VirtualLoaderError('Apply a virtual profile in CDMW first.')
    expected = expected_redirects(profile)
    relatives = protected_files(root)
    before = fingerprint(root, relatives)
    for relative in (STATUS_PATH, TRACE_PATH):
        target(root, relative).unlink(missing_ok=True)
    report = {'format': 'cdmw_cditem_smoke_v1', 'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'root': str(root), 'generation': profile['generation'], 'launch': STEAM_URL, 'reasons': []}
    reasons = report['reasons']
    started = hooks.clock()
    hooks.launch()
    status, pid = None, None
    while hooks.clock() - started < start_timeout:
        status = read_standalone_status(root)
        if status is not None:
            pid = status.pid
            break
        hooks.sleep(1.0)
    report['seconds_to_report'] = round(hooks.clock() - started, 1)
    report['status'] = _status_value(status)
    if status is None:
        reasons.append('The runtime wrote no report. The ASI did not run or found no launcher profile.')
        candidates = hooks.running()
        pid = candidates[0] if len(candidates) == 1 else None
    elif status.state != 'ready':
        reasons.append('The runtime refused the profile: ' + status.detail)
    if status is not None and status.generation != profile['generation']:
        reasons.append('The runtime loaded another profile generation.')
    evidence = trace_evidence([], expected)
    if status is not None and status.state == 'ready':
        deadline = hooks.clock() + evidence_timeout
        while True:
            evidence = trace_evidence(read_standalone_trace(root), expected, profile['files'])
            if all(evidence['expected'].values()) or hooks.clock() >= deadline or not hooks.alive(pid):
                break
            hooks.sleep(1.0)
        missing = [logical for logical, seen in evidence['expected'].items() if not seen]
        if missing:
            reasons.append('The game did not open these through the runtime: ' + ', '.join(missing))
        if not hooks.alive(pid):
            reasons.append('The game exited on its own before the hold time ended.')
        else:
            hold_until = hooks.clock() + hold
            while hooks.clock() < hold_until and hooks.alive(pid):
                hooks.sleep(1.0)
            if not hooks.alive(pid):
                reasons.append('The game exited on its own during the hold time.')
        evidence = trace_evidence(read_standalone_trace(root), expected, profile['files'])
    report['trace'] = evidence
    if pid is not None and hooks.alive(pid):
        image = hooks.image(pid)
        if Path(image).resolve() != target(root, GAME_PATH).resolve():
            reasons.append(f'Process {pid} is not this installation\'s game; it was left running.')
            report['close'] = 'left running'
        else:
            report['close'] = hooks.close(pid, close_timeout)
            if report['close'] != 'closed':
                reasons.append('The game did not close on request and was ended.')
    else:
        report['close'] = 'already exited'
    settle = hooks.clock() + 15
    while hooks.running() and hooks.clock() < settle:
        hooks.sleep(1.0)
    if hooks.running():
        reasons.append('A game process is still running after the test.')
    after = fingerprint(root, relatives)
    report['changed_files'] = sorted(relative for relative in relatives if before[relative] != after[relative])
    if report['changed_files']:
        reasons.append('Protected installation files changed: ' + ', '.join(report['changed_files']))
    report['protected_files'] = len(relatives)
    report['seconds'] = round(hooks.clock() - started, 1)
    report['verdict'] = 'passed' if not reasons else 'failed'
    return report


def windows_hooks(root):
    if os.name != 'nt':
        raise VirtualLoaderError('The smoke test launches the game and requires Windows.')
    import ctypes
    from ctypes import wintypes
    from cdmw.core.chainner import list_process_ids_by_image_name
    from cdmw.services.virtual_loader_runtime import _process_alive
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def image(pid):
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ''
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            return buffer.value if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ''
        finally:
            kernel.CloseHandle(handle)

    def close(pid, timeout):
        handle = kernel.OpenProcess(0x100000 | 0x0001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
        if not handle:
            return 'already exited'
        try:
            windows = []
            def collect(hwnd, _):
                owner = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == pid:
                    windows.append(hwnd)
                return True
            user.EnumWindows(callback(collect), 0)
            for hwnd in windows:
                user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            if windows and kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0:
                return 'closed'
            kernel.TerminateProcess(handle, 1)
            kernel.WaitForSingleObject(handle, 10000)
            return 'terminated'
        finally:
            kernel.CloseHandle(handle)

    def running():
        game = target(root, GAME_PATH).resolve()
        return sorted(pid for pid in list_process_ids_by_image_name('CrimsonDesert.exe')
                      if not image(pid) or Path(image(pid)).resolve() == game)

    return SmokeHooks(launch=lambda: os.startfile(STEAM_URL), alive=_process_alive, image=image, close=close, running=running)
