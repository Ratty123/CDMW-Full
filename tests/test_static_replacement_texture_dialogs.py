from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_texture_dialogs import texture_assignment_action_initial_state


def test_texture_assignment_action_initial_state_preserves_default() -> None:
    assert texture_assignment_action_initial_state() == {"value": "cancel"}
