from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QProcess

from tests.test_mesh_rust_editor_selection import _dispose, _tab


def test_gpu_failure_and_retry_keep_the_authoring_process_and_shadow_session(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    session = SimpleNamespace(
        session_id="gpu-session", closed=False, shadow_session_id="shadow",
        shadow_service=SimpleNamespace(session_view=lambda _: SimpleNamespace(revision=7)),
    )
    process = SimpleNamespace(state=lambda: QProcess.ProcessState.Running)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process = process
    tab.standalone_rust_process_generation = 4
    tab.standalone_rust_ready = True
    tab.standalone_workspace.setEnabled(True)
    identity = {
        "protocol": "cdmw_rust_mesh_editor_protocol_v1", "session_id": "gpu-session",
        "request_id": 0, "base_revision": 7, "process_generation": 4,
    }
    try:
        with (
            patch.object(tab, "_fail_rust_editor") as fail,
            patch.object(tab, "_start_selected_mesh_editor") as restart,
            patch.object(tab, "_send_rust_message", return_value=True) as send,
        ):
            tab._handle_rust_protocol_event(dict(identity, event="renderer_failed", message="GPU paused"))
            assert tab.standalone_rust_gpu_failed
            assert tab.standalone_rust_ready
            assert not tab.standalone_native_host_frame._retry_button.isHidden()
            tab.standalone_native_host_frame._retry_button.click()
            send.assert_called_once_with(dict(identity, event="renderer_retry"))
            tab._handle_rust_protocol_event(dict(identity, event="renderer_recovered", message="GPU restored"))
            assert not tab.standalone_rust_gpu_failed
            assert tab.standalone_native_host_frame._editor_visible
            assert tab.standalone_rust_process is process
            assert tab.standalone_rust_authoring_session is session
            fail.assert_not_called()
            restart.assert_not_called()
    finally:
        tab.standalone_rust_process = None
        tab.standalone_rust_authoring_session = None
        _dispose(tab)
