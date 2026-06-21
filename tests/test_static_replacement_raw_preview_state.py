from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_raw_preview_state import (
    mesh_edit_raw_preview_initial_state,
    mesh_edit_raw_preview_record_state,
)


def test_mesh_edit_raw_preview_initial_state_is_inactive() -> None:
    assert mesh_edit_raw_preview_initial_state() == {"active": False}


def test_mesh_edit_raw_preview_record_state_returns_previous_and_current() -> None:
    state = mesh_edit_raw_preview_initial_state()

    assert mesh_edit_raw_preview_record_state(state, True) == (False, True)
    assert state == {"active": True}

    assert mesh_edit_raw_preview_record_state(state, False) == (True, False)
    assert state == {"active": False}
