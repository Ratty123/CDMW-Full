from __future__ import annotations

from cdmw.ui.research import (
    analysis_state,
    archive_picker_state,
    classification_review_state,
    display_preferences_state,
    notes_state,
    preview_state,
    reference_payload_state,
    refresh_population_state,
    state,
    texture_group_state,
)


OWNER_MODULES = (
    analysis_state,
    archive_picker_state,
    classification_review_state,
    display_preferences_state,
    notes_state,
    preview_state,
    reference_payload_state,
    refresh_population_state,
    texture_group_state,
)


def test_research_state_facade_exports_owner_objects() -> None:
    assert len(state.__all__) == len(set(state.__all__))

    for name in state.__all__:
        facade_value = getattr(state, name)
        assert any(
            hasattr(owner, name) and getattr(owner, name) is facade_value
            for owner in OWNER_MODULES
        ), name
