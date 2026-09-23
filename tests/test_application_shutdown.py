from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import application_shutdown_service as shutdown


@pytest.fixture
def isolated_shutdown(monkeypatch):
    monkeypatch.setattr(shutdown, "_condition", threading.Condition())
    monkeypatch.setattr(shutdown, "_archive_write_depth", threading.local())
    monkeypatch.setattr(shutdown, "_active_archive_writes", 0)
    monkeypatch.setattr(shutdown, "_shutdown_started_at", None)
    return shutdown


def test_close_refuses_new_archive_writes_but_allows_nested_recovery(isolated_shutdown):
    with shutdown.archive_write_scope():
        assert shutdown.archive_write_in_progress()
        shutdown._shutdown_started_at = time.monotonic()
        with shutdown.archive_write_scope():
            assert shutdown.archive_write_in_progress()
        assert shutdown.archive_write_in_progress()
        refused = []

        def try_unrelated_write():
            try:
                with shutdown.archive_write_scope():
                    refused.append(False)
            except RunCancelled:
                refused.append(True)

        other_worker = threading.Thread(target=try_unrelated_write)
        other_worker.start()
        other_worker.join(2)
        assert not other_worker.is_alive()
        assert refused == [True]
    assert not shutdown.archive_write_in_progress()
    with pytest.raises(RunCancelled, match="CDMW is closing"):
        with shutdown.archive_write_scope():
            pytest.fail("A new transaction started after shutdown")


def test_failed_transaction_releases_shutdown_barrier(isolated_shutdown):
    with pytest.raises(OSError, match="write failed"):
        with shutdown.archive_write_scope():
            raise OSError("write failed")
    assert not shutdown.archive_write_in_progress()


def test_widgets_without_app_containment_never_terminate_their_host(isolated_shutdown, monkeypatch):
    monkeypatch.setattr(shutdown, "app_lifetime_job_is_bound", lambda: False)
    shutdown.begin_application_shutdown()
    assert shutdown._shutdown_started_at is None


def test_repeated_close_arms_only_one_watchdog(isolated_shutdown, monkeypatch):
    monkeypatch.setattr(shutdown, "app_lifetime_job_is_bound", lambda: True)
    thread = Mock()
    factory = Mock(return_value=thread)
    monkeypatch.setattr(shutdown.threading, "Thread", factory)
    shutdown.begin_application_shutdown()
    started = shutdown._shutdown_started_at
    shutdown.begin_application_shutdown()
    assert shutdown._shutdown_started_at == started
    factory.assert_called_once()
    thread.start.assert_called_once()


_HELPER_SCRIPT = """
import json, os, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'helper': os.getpid(), 'grandchild': child.pid}), flush=True)
time.sleep(60)
"""

_APP_SCRIPT = """
import json, os, pathlib, subprocess, sys, threading, time
from cdmw.services.process_job_service import bind_process_tree_to_app_lifetime
from cdmw.services import application_shutdown_service as shutdown
ready, release, committed = map(pathlib.Path, sys.argv[1:4])
owner = ready.with_suffix('.owner')
pending_owner = owner.with_suffix('.pending-owner')
pending_owner.write_text(str(os.getpid()))
pending_owner.replace(owner)
assert bind_process_tree_to_app_lifetime()
mode, helper_script = sys.argv[4:6]
helper = subprocess.Popen([sys.executable, '-u', '-c', helper_script],
                          stdout=subprocess.PIPE, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)
record = json.loads(helper.stdout.readline())
record['parent'] = os.getpid()
def publish_ready():
    pending = ready.with_suffix('.pending')
    pending.write_text(json.dumps(record))
    pending.replace(ready)
shutdown.APPLICATION_SHUTDOWN_GRACE_SECONDS = 0.25
if mode == 'shell':
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from types import MethodType
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.shell.close_controller import CloseControllerMixin
    from tests.test_shell_close_controller import _BlockingThread, _ShutdownCoordinatorWindow
    app = QApplication([])
    window = _ShutdownCoordinatorWindow()
    worker = _BlockingThread(window)
    window._tracked_worker_threads = lambda: [('blocked_worker', worker, None)]
    window._running_worker_thread_entries = MethodType(CloseControllerMixin._running_worker_thread_entries, window)
    window._request_tracked_workers_to_stop = lambda: (worker.requestInterruption(), worker.quit())
    window.archive_backend_client.shutdown = lambda: setattr(window.archive_backend_client.state, 'value', 'stopped')
    timer = window._close_worker_wait_timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(window._finish_deferred_close_if_workers_stopped)
    worker.start()
    assert worker.started_event.wait(2)
    publish_ready()
    sys.stdin.readline()
    window.show()
    QTimer.singleShot(0, window.close)
    app.exec()
    raise AssertionError('The stuck worker unexpectedly allowed a clean close')
elif mode == 'protected':
    with shutdown.archive_write_scope():
        publish_ready()
        sys.stdin.readline()
        shutdown.begin_application_shutdown()
        while not release.exists():
            time.sleep(0.01)
        # A rollback admitted by the original transaction must still run.
        with shutdown.archive_write_scope():
            committed.write_text('recovery completed')
    time.sleep(60)
elif mode == 'watchdog':
    publish_ready()
    sys.stdin.readline()
    threading.Thread(target=lambda: time.sleep(60), daemon=False).start()
    shutdown.begin_application_shutdown()
    # Simulate app.exec() returning while Python waits for a stuck worker.
else:
    publish_ready()
    sys.stdin.readline()
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows job and process lifetime contract")
@pytest.mark.parametrize("mode", ["normal", "forced", "watchdog", "protected", "shell"])
def test_owned_process_tree_dies_with_application(tmp_path: Path, mode: str):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    ready, release, committed = (tmp_path / name for name in ("ready.json", "release", "committed"))
    # Only the Qt shell probe needs the virtualenv. Record/open the actual app
    # PID too, so failure cleanup never stops at a Windows redirector parent.
    executable = sys.executable if mode == "shell" else sys._base_executable
    process = subprocess.Popen(
        [executable, "-u", "-c", _APP_SCRIPT, str(ready), str(release),
         str(committed), mode, _HELPER_SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    handles = {}
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "Contained probe did not start"
        record = json.loads(ready.read_text())
        for name in ("parent", "helper", "grandchild"):
            handles[name] = kernel.OpenProcess(0x00100001, False, record[name])
            assert handles[name], name
        if mode in {"protected", "watchdog", "shell"}:
            process.stdin.write("begin\n")
            process.stdin.flush()
        if mode == "protected":
            # The shortened deadline expires while recovery owns the barrier.
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.6)
            assert not committed.exists()
            assert all(kernel.WaitForSingleObject(handle, 0) != 0 for handle in handles.values())
            release.write_text("finish")
        elif mode == "normal":
            process.stdin.write("exit\n")
            process.stdin.flush()
        elif mode == "forced":
            process.kill()
        process.wait(timeout=5)
        if mode in {"watchdog", "protected", "shell"}:
            assert process.returncode == 1
        if mode == "protected":
            assert committed.read_text() == "recovery completed"
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles.values())
    finally:
        if process.poll() is None:
            owner = ready.with_suffix(".owner")
            if not handles.get("parent") and owner.exists():
                handles["parent"] = kernel.OpenProcess(0x00100001, False, int(owner.read_text()))
            if handles.get("parent"):
                kernel.TerminateProcess(handles["parent"], 1)
            process.kill()
        process.communicate(timeout=5)
        for handle in handles.values():
            if not handle:
                continue
            if kernel.WaitForSingleObject(handle, 0) != 0:
                kernel.TerminateProcess(handle, 1)
            kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)
