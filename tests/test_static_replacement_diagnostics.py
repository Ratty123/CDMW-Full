from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_diagnostics import (
    mesh_editor_diagnostics_append_safe_value,
    mesh_editor_diagnostics_copied_status,
    mesh_editor_diagnostics_initial_state,
    mesh_editor_diagnostics_record_text,
    mesh_editor_diagnostics_set_text_widget,
    mesh_editor_diagnostics_text_widget,
)


def test_mesh_editor_diagnostics_copied_status_preserves_copy() -> None:
    assert mesh_editor_diagnostics_copied_status() == "Mesh Editor diagnostics copied."


def test_mesh_editor_diagnostics_state_tracks_text_widget() -> None:
    state = mesh_editor_diagnostics_initial_state()
    widget = object()

    assert state == {"text_widget": None, "last_text": ""}
    assert mesh_editor_diagnostics_text_widget(state) is None

    mesh_editor_diagnostics_set_text_widget(state, widget)

    assert mesh_editor_diagnostics_text_widget(state) is widget


def test_mesh_editor_diagnostics_record_text_skips_repeated_auto_update() -> None:
    state = mesh_editor_diagnostics_initial_state()

    assert mesh_editor_diagnostics_record_text(state, "first", auto=True) is True
    assert mesh_editor_diagnostics_record_text(state, "first", auto=True) is False
    assert mesh_editor_diagnostics_record_text(state, "first", auto=False) is True
    assert mesh_editor_diagnostics_record_text(state, "second", auto=True) is True
    assert state["last_text"] == "second"


def test_mesh_editor_diagnostics_append_safe_value_records_values_and_errors() -> None:
    lines: list[str] = []

    mesh_editor_diagnostics_append_safe_value(lines, "ok", lambda: 7)
    mesh_editor_diagnostics_append_safe_value(lines, "bad", lambda: (_ for _ in ()).throw(ValueError("nope")))

    assert lines == ["ok: 7", "bad: <error: nope>"]
