"""Driven runs must never leave the Mesh Editor's "Delete unavailable" dialog open.

Fredric (2026-11-17): automated runs kept leaving that dialog on screen for good,
because nobody is there to close it. Under automation the editor reports the
refusal to CDMW ("notice") instead of opening the dialog.
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QProcessEnvironment

from cdmw.ui.mesh_editor.tab_rust_process import (
    RUST_AUTOMATION_ENV,
    MeshEditorRustProcessMixin,
    rust_helper_environment,
)


def _editor(statuses: list[str], failures: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        standalone_rust_protocol_events=[],
        standalone_rust_failure_reported=False,
        _validate_rust_event_identity=lambda payload: str(payload.get("event", "")),
        _set_rust_status=lambda message, error=False: statuses.append(message),
        _fail_rust_editor=lambda message, incompatible=False: failures.append(message),
    )


def test_a_notice_from_the_editor_reaches_the_status_line_and_does_not_end_the_session():
    statuses: list[str] = []
    failures: list[str] = []
    editor = _editor(statuses, failures)
    MeshEditorRustProcessMixin._handle_rust_protocol_event(editor, {
        "event": "notice", "kind": "delete_unavailable",
        "message": "Still running: Select All. Delete again when it has finished.",
    })
    assert statuses == ["Still running: Select All. Delete again when it has finished."]
    assert failures == []


def test_the_editor_is_told_when_automation_drives_it(monkeypatch):
    monkeypatch.setenv("CDMW_AUTOMATION", "1")
    driven = rust_helper_environment(QProcessEnvironment())
    assert driven.value(RUST_AUTOMATION_ENV) == "1"
    assert driven.value("WGPU_BACKEND") == "dx12"


def test_a_normal_launch_never_passes_the_automation_flag_on(monkeypatch):
    monkeypatch.delenv("CDMW_AUTOMATION", raising=False)
    inherited = QProcessEnvironment()
    inherited.insert(RUST_AUTOMATION_ENV, "1")  # left over in the user's environment
    assert not rust_helper_environment(inherited).contains(RUST_AUTOMATION_ENV)
