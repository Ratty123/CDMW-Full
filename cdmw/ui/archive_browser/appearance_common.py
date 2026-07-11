"""Archive appearance candidate selection helpers."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from cdmw.models import ArchiveEntry
from cdmw.workers.appearance_workers import appearance_swap_exact_app_match


class ArchiveAppearanceCommonMixin:
    """Archive appearance candidate selection helpers."""
    def _appearance_composite_entry_summary(entries: Sequence[ArchiveEntry], *, limit: int = 4) -> str:
        paths = [str(getattr(entry, "path", "") or "") for entry in entries if isinstance(entry, ArchiveEntry)]
        if not paths:
            return ""
        visible = paths[: max(1, int(limit or 1))]
        summary = "; ".join(Path(path.replace("\\", "/")).name for path in visible)
        remaining = len(paths) - len(visible)
        if remaining > 0:
            summary = f"{summary}; +{remaining} more"
        return summary

    @staticmethod
    def _appearance_composite_entry_key(entry: ArchiveEntry) -> Tuple[str, str, int]:
        return (
            str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower(),
            str(getattr(entry, "pamt_path", "") or "").casefold(),
            int(getattr(entry, "offset", 0) or 0),
        )

    def _appearance_composite_selected_context(
        self,
        current_entry: ArchiveEntry,
    ) -> Tuple[ArchiveEntry, Optional[ArchiveEntry]]:
        selected_entries = [entry for entry in self._selected_archive_entries() if isinstance(entry, ArchiveEntry)]
        current_key = self._appearance_composite_entry_key(current_entry)
        selected_appearances = [entry for entry in selected_entries if str(entry.extension or "").lower() == ".app_xml"]
        selected_models = [
            entry
            for entry in selected_entries
            if str(entry.extension or "").lower() in {".pac", ".pam", ".pamlod"}
            and self._appearance_composite_entry_key(entry) != current_key
        ]
        if str(current_entry.extension or "").lower() in {".pac", ".pam", ".pamlod"}:
            selected_models = [current_entry] + [
                entry
                for entry in selected_models
                if self._appearance_composite_entry_key(entry) != current_key
            ]
            if selected_appearances:
                return selected_appearances[0], selected_models[0]
        if str(current_entry.extension or "").lower() == ".app_xml" and len(selected_models) == 1:
            return current_entry, selected_models[0]
        return current_entry, None

    def _select_archive_appearance_candidate(
        self,
        source_entry: ArchiveEntry,
        candidates: Sequence[ArchiveEntry],
    ) -> Optional[ArchiveEntry]:
        if str(source_entry.extension or "").lower() == ".app_xml":
            return source_entry
        candidate_entries = tuple(entry for entry in candidates if isinstance(entry, ArchiveEntry))
        if not candidate_entries:
            return None
        if len(candidate_entries) == 1:
            return candidate_entries[0]

        dialog = QDialog(self)
        dialog.setWindowTitle("Choose Body Appearance Context")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label = QLabel(
            "Multiple appearance XML files reference this selection. Choose the body/head/hair/armor context to use for the composite preview."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        candidate_list = QListWidget()
        candidate_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for index, candidate in enumerate(candidate_entries):
            item = QListWidgetItem(candidate.path)
            item.setToolTip(candidate.path)
            item.setData(Qt.UserRole, index)
            candidate_list.addItem(item)
        candidate_list.setCurrentRow(0)
        layout.addWidget(candidate_list, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        choose_button = QPushButton("Use Appearance")
        choose_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(choose_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        choose_button.clicked.connect(dialog.accept)
        candidate_list.itemDoubleClicked.connect(lambda _item: dialog.accept())
        dialog.resize(760, 420)
        if dialog.exec() != QDialog.Accepted:
            return None
        item = candidate_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        try:
            return candidate_entries[int(index)]
        except Exception:
            return candidate_entries[0]

    def _appearance_swap_selected_context(
        self,
        current_entry: Optional[ArchiveEntry],
    ) -> Tuple[Optional[ArchiveEntry], Optional[ArchiveEntry], str]:
        selected_entries = [entry for entry in self._selected_archive_entries() if isinstance(entry, ArchiveEntry)]
        if isinstance(current_entry, ArchiveEntry) and all(
            self._appearance_composite_entry_key(entry) != self._appearance_composite_entry_key(current_entry)
            for entry in selected_entries
        ):
            selected_entries.append(current_entry)
        deduped: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        for entry in selected_entries:
            key = self._appearance_composite_entry_key(entry)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        app_entries = [entry for entry in deduped if str(entry.extension or "").lower() == ".app_xml"]
        model_entries = [entry for entry in deduped if str(entry.extension or "").lower() in {".pac", ".pam", ".pamlod"}]
        if len(app_entries) == 1 and len(model_entries) == 1:
            return app_entries[0], model_entries[0], ""
        if len(model_entries) == 1 and not app_entries:
            return None, model_entries[0], ""
        if len(app_entries) == 1 and not model_entries:
            return app_entries[0], None, "Select exactly one donor .pac/.pam/.pamlod model with this target body appearance context."
        if len(app_entries) > 1 or len(model_entries) > 1:
            return None, None, "Select exactly one target body .app_xml and one donor .pac/.pam/.pamlod model for single-PAC armor swap."
        return None, None, "Select one target body .app_xml and one donor .pac/.pam/.pamlod model first."

    @staticmethod
    def _appearance_swap_exact_app_match(
        model_entry: ArchiveEntry,
        app_entry: ArchiveEntry,
        *,
        stop_event: threading.Event | None = None,
    ) -> bool:
        return appearance_swap_exact_app_match(model_entry, app_entry, stop_event=stop_event)

    def _find_exact_appearance_contexts_for_model(
        self,
        donor_model_entry: ArchiveEntry,
        *,
        stop_event: threading.Event | None = None,
    ) -> Tuple[ArchiveEntry, ...]:
        matches: List[ArchiveEntry] = []
        extension_index = getattr(self, "archive_entries_by_extension", {}) or {}
        for candidate in tuple(extension_index.get(".app_xml", ()) or ()):
            if self._appearance_swap_exact_app_match(donor_model_entry, candidate, stop_event=stop_event):
                matches.append(candidate)
        return tuple(matches)
