"""Transactional Research note persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.research.contracts import ResearchNote


def load_research_notes(notes_path: Path) -> Dict[str, ResearchNote]:
    if not notes_path.exists():
        return {}
    try:
        payload = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    notes: Dict[str, ResearchNote] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        note_text = str(value.get("note", "")).strip()
        raw_tags = value.get("tags", [])
        tags = raw_tags if isinstance(raw_tags, list) else []
        if not note_text and not tags:
            continue
        notes[key] = ResearchNote(
            target_key=key,
            source_kind=str(value.get("source_kind", "unknown")),
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
            note=note_text,
            updated_at=str(value.get("updated_at", "")),
        )
    return notes


def save_research_notes(notes_path: Path, notes: Dict[str, ResearchNote]) -> None:
    payload = {
        key: {
            "source_kind": note.source_kind,
            "tags": list(note.tags),
            "note": note.note,
            "updated_at": note.updated_at,
        }
        for key, note in sorted(notes.items(), key=lambda item: item[0].lower())
    }
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    json.loads(text)
    atomic_write_text(notes_path, text, encoding="utf-8")


@dataclass(slots=True)
class ResearchNotesService:
    def load(self, notes_path: Path) -> Dict[str, ResearchNote]:
        return load_research_notes(notes_path)

    def save(self, notes_path: Path, notes: Dict[str, ResearchNote]) -> None:
        save_research_notes(notes_path, notes)


__all__ = ["ResearchNotesService", "load_research_notes", "save_research_notes"]
