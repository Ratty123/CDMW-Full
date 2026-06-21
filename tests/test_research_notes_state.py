from __future__ import annotations

from cdmw.core.research import ResearchNote
from cdmw.ui.research.notes_state import (
    research_note_delete_success_status_text,
    research_note_display_state,
    research_note_save_success_status_text,
    research_note_target_state,
    sorted_research_note_items,
)


def _note(target_key: str, *, tags: list[str] | None = None, note: str = "body") -> ResearchNote:
    return ResearchNote(
        target_key=target_key,
        source_kind="archive",
        tags=tags or [],
        note=note,
        updated_at="2026-06-14T00:00:00+00:00",
    )


def test_research_note_target_state_handles_missing_and_existing_notes() -> None:
    missing = research_note_target_state(source_kind="archive", target_key="", notes={})

    assert missing.is_error
    assert missing.status_text == "No current selection is available for notes."
    assert missing.normalized_target == ""

    notes = {
        "texture/armor.dds": _note("texture/armor.dds", tags=["dds", "armor"], note="Check alpha."),
    }
    loaded = research_note_target_state(
        source_kind="archive",
        target_key="texture\\armor.dds",
        notes=notes,
    )

    assert not loaded.is_error
    assert loaded.normalized_target == "texture/armor.dds"
    assert loaded.source_kind == "archive"
    assert loaded.tags_text == "dds, armor"
    assert loaded.note_text == "Check alpha."
    assert loaded.status_text == "Loaded note target: texture/armor.dds"


def test_sorted_research_note_items_orders_notes_case_insensitively() -> None:
    notes = {
        "z.dds": _note("z.dds"),
        "A.dds": _note("A.dds"),
    }

    assert [key for key, _note_value in sorted_research_note_items(notes)] == ["A.dds", "z.dds"]


def test_research_note_display_and_status_helpers_format_widget_state() -> None:
    note = _note("texture/armor.dds", tags=["dds", "armor"], note="Check alpha.")
    display_state = research_note_display_state(note)

    assert display_state.target_key == "texture/armor.dds"
    assert display_state.source_kind == "archive"
    assert display_state.tags_text == "dds, armor"
    assert display_state.note_text == "Check alpha."
    assert research_note_save_success_status_text() == "Saved research note."
    assert research_note_delete_success_status_text() == "Deleted research note."
