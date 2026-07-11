"""Pure Research note state transitions."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict

from cdmw.domain.research.contracts import ResearchNote


def upsert_research_note(
    notes: Dict[str, ResearchNote],
    *,
    target_key: str,
    source_kind: str,
    tags_text: str,
    note_text: str,
) -> Dict[str, ResearchNote]:
    normalized_key = target_key.strip().replace("\\", "/")
    if not normalized_key:
        raise ValueError("Choose a file/path before saving a note.")
    tags = [token.strip() for token in re.split(r"[,\s;|]+", tags_text) if token.strip()]
    normalized_note = note_text.strip()
    if not tags and not normalized_note:
        notes.pop(normalized_key, None)
        return notes
    notes[normalized_key] = ResearchNote(
        target_key=normalized_key,
        source_kind=source_kind.strip() or "unknown",
        tags=tags,
        note=normalized_note,
        updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    return notes


def delete_research_note(notes: Dict[str, ResearchNote], target_key: str) -> Dict[str, ResearchNote]:
    normalized_key = target_key.strip().replace("\\", "/")
    if normalized_key:
        notes.pop(normalized_key, None)
    return notes


__all__ = ["delete_research_note", "upsert_research_note"]
