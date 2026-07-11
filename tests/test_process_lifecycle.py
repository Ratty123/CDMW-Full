from __future__ import annotations

import io
import subprocess
import tempfile
import threading
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
