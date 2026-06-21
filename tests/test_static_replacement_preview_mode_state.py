from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_preview_mode_state import (
    alignment_preview_mode_initial_state,
    alignment_preview_mode_record,
)


def test_alignment_preview_mode_initial_state_defaults_to_side_by_side() -> None:
    assert alignment_preview_mode_initial_state(None) == {"current": "side_by_side"}
    assert alignment_preview_mode_initial_state("replacement_only") == {"current": "replacement_only"}


def test_alignment_preview_mode_record_returns_previous_and_current() -> None:
    state = alignment_preview_mode_initial_state("side_by_side")

    assert alignment_preview_mode_record(state, "replacement_only") == ("side_by_side", "replacement_only")
    assert state == {"current": "replacement_only"}

    assert alignment_preview_mode_record(state, "") == ("replacement_only", "side_by_side")
    assert state == {"current": "side_by_side"}
