"""Research note target and list state rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cdmw.domain.research.contracts import ResearchNote
from cdmw.ui.research.reference_payload_state import normalize_research_target_key

__all__ = [
    "ResearchNoteDisplayState",
    "ResearchNoteTargetState",
    "research_note_delete_success_status_text",
    "research_note_display_state",
    "research_note_save_success_status_text",
    "research_note_target_state",
    "sorted_research_note_items",
]


@dataclass(frozen=True, slots=True)
class ResearchNoteTargetState:
    normalized_target: str
    source_kind: str
    tags_text: str
    note_text: str
    status_text: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class ResearchNoteDisplayState:
    target_key: str
    source_kind: str
    tags_text: str
    note_text: str


def research_note_target_state(
    *,
    source_kind: str,
    target_key: str,
    notes: Mapping[str, ResearchNote],
) -> ResearchNoteTargetState:
    normalized_key = normalize_research_target_key(target_key)
    if not normalized_key:
        return ResearchNoteTargetState(
            normalized_target="",
            source_kind=str(source_kind or ""),
            tags_text="",
            note_text="",
            status_text="No current selection is available for notes.",
            is_error=True,
        )
    existing = notes.get(normalized_key)
    return ResearchNoteTargetState(
        normalized_target=normalized_key,
        source_kind=str(source_kind or ""),
        tags_text=", ".join(existing.tags) if existing is not None else "",
        note_text=existing.note if existing is not None else "",
        status_text=f"Loaded note target: {normalized_key}",
        is_error=False,
    )


def sorted_research_note_items(notes: Mapping[str, ResearchNote]) -> list[tuple[str, ResearchNote]]:
    return sorted(notes.items(), key=lambda item: item[0].lower())


def research_note_display_state(note: ResearchNote) -> ResearchNoteDisplayState:
    return ResearchNoteDisplayState(
        target_key=note.target_key,
        source_kind=note.source_kind,
        tags_text=", ".join(note.tags),
        note_text=note.note,
    )


def research_note_save_success_status_text() -> str:
    return "Saved research note."


def research_note_delete_success_status_text() -> str:
    return "Deleted research note."
