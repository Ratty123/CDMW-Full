from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.core.research import delete_research_note, save_research_notes, upsert_research_note
from cdmw.ui.research.models import build_note_item, item_payload
from cdmw.ui.research.notes_state import (
    research_note_delete_success_status_text,
    research_note_display_state,
    research_note_save_success_status_text,
    research_note_target_state,
    sorted_research_note_items,
)

def _populate_note_target(self, source_kind: str, target_key: str) -> None:
    target_state = research_note_target_state(
        source_kind=source_kind,
        target_key=target_key,
        notes=self.notes,
    )
    if target_state.is_error:
        self.status_message_requested.emit(target_state.status_text, True)
        return
    self.notes_target_edit.setText(target_state.normalized_target)
    self.notes_source_label.setText(target_state.source_kind)
    if target_state.tags_text:
        self.notes_tags_edit.setText(target_state.tags_text)
    if target_state.note_text:
        self.notes_edit.setPlainText(target_state.note_text)
    self.status_message_requested.emit(target_state.status_text, False)

def _populate_notes_tree(self) -> None:
    self.notes_tree.clear()
    for key, note in sorted_research_note_items(self.notes):
        self.notes_tree.addTopLevelItem(build_note_item(key, note))

def _save_note(self) -> None:
    try:
        upsert_research_note(
            self.notes,
            target_key=self.notes_target_edit.text(),
            source_kind=self.notes_source_label.text(),
            tags_text=self.notes_tags_edit.text(),
            note_text=self.notes_edit.toPlainText(),
        )
        save_research_notes(self.notes_path, self.notes)
        self._populate_notes_tree()
        self.status_message_requested.emit(research_note_save_success_status_text(), False)
    except Exception as exc:
        self.status_message_requested.emit(str(exc), True)

def _delete_note(self) -> None:
    delete_research_note(self.notes, self.notes_target_edit.text())
    save_research_notes(self.notes_path, self.notes)
    self._populate_notes_tree()
    self.notes_tags_edit.clear()
    self.notes_edit.clear()
    self.status_message_requested.emit(research_note_delete_success_status_text(), False)

def _load_selected_note(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
    if current is None:
        return
    key = item_payload(current, str)
    if not isinstance(key, str):
        return
    note = self.notes.get(key)
    if note is None:
        return
    display_state = research_note_display_state(note)
    self.notes_target_edit.setText(display_state.target_key)
    self.notes_source_label.setText(display_state.source_kind)
    self.notes_tags_edit.setText(display_state.tags_text)
    self.notes_edit.setPlainText(display_state.note_text)
