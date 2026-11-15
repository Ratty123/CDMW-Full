"""A draft autosave that fails says so in the Mesh Editor (2026-11-13).

The draft saves on a background thread after each change, so a failure comes
after the change's reply: the tab checks for one and sends the editor a
save_status line when it appears, and again when a later save clears it.
"""

from __future__ import annotations

from types import SimpleNamespace

import cdmw.ui.mesh_editor.tab  # noqa: F401  (loads the facade the mixins use)
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin


class _Service:
    def __init__(self) -> None:
        self.session = SimpleNamespace(mesh_layer_autosave_error="")

    def _session(self, _session_id):
        return self.session


class _Tab:
    _rust_save_status_error = MeshEditorRustProcessMixin._rust_save_status_error
    _poll_rust_save_status = MeshEditorRustProcessMixin._poll_rust_save_status

    def __init__(self) -> None:
        self.service = _Service()
        self.standalone_rust_authoring_session = SimpleNamespace(
            closed=False, shadow_service=self.service, shadow_session_id="shadow",
            authoritative_service=None, authoritative_session_id="")
        self.standalone_rust_ready = True
        self.standalone_rust_save_status_sent = ""
        self.sent: list[dict] = []

    def _rust_host_message(self, event, *, request_id, extra=None):
        return {"event": event, "request_id": request_id, **dict(extra or {})}

    def _send_rust_message(self, payload):
        self.sent.append(dict(payload))
        return True


def test_a_failed_autosave_is_sent_once_and_its_recovery_too() -> None:
    tab = _Tab()
    tab._poll_rust_save_status()
    assert tab.sent == []  # nothing to say while saves succeed

    tab.service.session.mesh_layer_autosave_error = "OSError: [WinError 206] The filename or extension is too long"
    tab._poll_rust_save_status()
    tab._poll_rust_save_status()
    assert [message["event"] for message in tab.sent] == ["save_status"]
    assert "too long" in tab.sent[0]["error"]

    tab.service.session.mesh_layer_autosave_error = ""
    tab._poll_rust_save_status()
    assert tab.sent[-1] == {"event": "save_status", "request_id": 0, "error": ""}
    assert len(tab.sent) == 2


def test_the_watch_stops_with_the_editor() -> None:
    tab = _Tab()
    stopped = []
    tab.standalone_rust_save_status_timer = SimpleNamespace(stop=lambda: stopped.append(True))
    tab.standalone_rust_ready = False
    tab.service.session.mesh_layer_autosave_error = "failed"
    tab._poll_rust_save_status()
    assert stopped and tab.sent == []
