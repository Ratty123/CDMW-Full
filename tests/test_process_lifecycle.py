from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cdmw.core.common import (
    BoundedTextTail,
    finish_process_tree,
    read_bounded_text_line,
    start_bounded_text_stream_drain,
)
from cdmw.modding.mesh_native_core import NativeMeshCoreServiceClient
from cdmw.modding import mesh_native_core_temp_paths
from cdmw.models import RunCancelled
from cdmw.core import common


def test_bounded_text_stream_drain_consumes_pipe_and_keeps_only_tail() -> None:
    thread, tail = start_bounded_text_stream_drain(
        io.StringIO("prefix-" + "x" * 32 + "-suffix"),
        name="test-diagnostic-drain",
        max_chars=12,
    )
    thread.join(1.0)
    assert not thread.is_alive()
    assert tail.text() == "xxxxx-suffix"

    direct = BoundedTextTail(5)
    direct.append("abc")
    direct.append("def")
    assert direct.text() == "bcdef"


def test_finish_process_tree_forces_only_after_grace_expires() -> None:
    process = Mock()
    process.pid = 123
    process.wait.side_effect = [subprocess.TimeoutExpired(["helper"], 0.1), 0]
    with (
        patch("cdmw.core.common._windows_descendant_pids", return_value=(456,)),
        patch("cdmw.core.common._request_process_tree_stop") as request_stop,
        patch("cdmw.core.common._force_stop_process_tree") as force_stop,
    ):
        finish_process_tree(process, grace_seconds=0.1)

    request_stop.assert_called_once_with(process)
    force_stop.assert_called_once_with(process, (456,))
    assert process.wait.call_args_list[0].kwargs == {"timeout": 0.1}


@pytest.mark.skipif(os.name != "nt", reason="Windows process snapshot contract")
@pytest.mark.parametrize("root_start", (100, None))
def test_windows_descendants_reject_reused_parent_ids(monkeypatch, root_start) -> None:
    import ctypes

    # PID 500 was reused after the older host (PID 10) was created. The stale
    # parent link must not make that host, or its children, cleanup targets.
    entries = [(10, 500), (500, 10), (600, 500), (700, 600), (800, 500), (900, 600)]
    starts = {10: 10, 500: root_start, 600: 110, 700: 120, 800: None, 900: 50}
    iterator = iter(entries)

    def next_process(_snapshot, pointer):
        try:
            process_id, parent_id = next(iterator)
        except StopIteration:
            return False
        pointer._obj.th32ProcessID = process_id
        pointer._obj.th32ParentProcessID = parent_id
        return True

    def process_times(handle, creation, _exit, _kernel, _user):
        creation._obj.dwLowDateTime = starts[handle]
        creation._obj.dwHighDateTime = 0
        return True

    kernel32 = Mock()
    kernel32.CreateToolhelp32Snapshot.return_value = 99
    kernel32.Process32FirstW.side_effect = next_process
    kernel32.Process32NextW.side_effect = next_process
    kernel32.OpenProcess.side_effect = lambda _access, _inherit, pid: pid if starts[pid] is not None else 0
    kernel32.GetProcessTimes.side_effect = process_times
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32)

    assert common._windows_descendant_pids(500) == ((600, 700) if root_start is not None else ())


@pytest.mark.skipif(os.name != "nt", reason="Windows process tree integration")
def test_windows_process_tree_cleanup_stops_owned_child_and_grandchild(tmp_path) -> None:
    import ctypes
    from ctypes import wintypes

    child_pid_path = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "ready = pathlib.Path(sys.argv[1])\n"
        "pending = ready.with_suffix('.tmp')\n"
        "pending.write_text(str(child.pid)); pending.replace(ready)\n"
        "time.sleep(60)\n"
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    child_handle = None
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(child_pid_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not child_pid_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert child_pid_path.exists(), "owned subprocess did not report its child"
        child_pid = int(child_pid_path.read_text())
        child_handle = kernel32.OpenProcess(0x00100001, False, child_pid)
        assert child_handle
        descendants = common._windows_descendant_pids(process.pid)
        assert child_pid in descendants
        assert os.getpid() not in descendants

        finish_process_tree(process, grace_seconds=0.0, request_stop=False)

        assert process.poll() is not None
        assert kernel32.WaitForSingleObject(child_handle, 5000) == 0
    finally:
        if child_handle:
            kernel32.TerminateProcess(child_handle, 1)
            kernel32.CloseHandle(child_handle)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_helper_protocol_line_read_is_bounded() -> None:
    assert read_bounded_text_line(io.StringIO("ok\n"), max_chars=4) == "ok\n"
    with pytest.raises(ValueError, match="exceeds"):
        read_bounded_text_line(io.StringIO("12345"), max_chars=4)


def test_native_delta_allocation_amortizes_registry_pruning() -> None:
    mesh_native_core_temp_paths.cleanup_native_preview_delta_paths()
    mesh_native_core_temp_paths._allocations_since_prune = 0
    try:
        with patch.object(mesh_native_core_temp_paths, "_prune_missing_paths_locked") as prune:
            for _index in range(32):
                mesh_native_core_temp_paths.native_preview_delta_output_path()
        prune.assert_not_called()
    finally:
        mesh_native_core_temp_paths.cleanup_native_preview_delta_paths()


def test_persistent_mesh_helpers_drain_stderr_and_use_process_groups() -> None:
    mesh_source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("cdmw/modding/mesh_native_core.py", "cdmw/modding/mesh_native_client.py")
    )
    preview_source = Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8")
    for source in (mesh_source, preview_source):
        assert "start_bounded_text_stream_drain(" in source
        assert "hidden_process_group_kwargs()" in source
        assert "finish_process_tree(" in source
        assert "stderr=subprocess.PIPE" in source


def test_mesh_core_service_reuses_one_bounded_stdout_reader() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = NativeMeshCoreServiceClient(Path(temp_dir) / "cdmw-mesh-core.exe")
        client._process = type("Process", (), {"poll": lambda self: None})()  # type: ignore[assignment]
        client._start_stdout_reader_locked(io.StringIO('{"event":"ready"}\n{"status":"ok"}\n'))

        assert client._read_stdout_line_locked(1.0) == '{"event":"ready"}'
        stdout_thread = client._stdout_thread
        assert client._read_stdout_line_locked(1.0) == '{"status":"ok"}'
        assert client._stdout_thread is stdout_thread
        assert stdout_thread is not None
        stdout_thread.join(1.0)
        assert not stdout_thread.is_alive()


def test_mesh_core_persistent_stdout_wait_remains_cancellable() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client = NativeMeshCoreServiceClient(Path(temp_dir) / "cdmw-mesh-core.exe")
        client._process = type("Process", (), {"poll": lambda self: None})()  # type: ignore[assignment]
        stop_event = threading.Event()
        stop_event.set()
        with patch.object(client, "_kill_locked") as kill:
            with pytest.raises(RunCancelled, match="cancelled"):
                client._read_stdout_line_locked(1.0, stop_event=stop_event)
        kill.assert_called_once_with()
