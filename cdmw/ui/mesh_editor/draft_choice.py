"""Ask which saved draft to open before Mesh Editor loads a game file.

Opening a game file that has saved drafts, from Archive Browser or anywhere
else that does not name a draft, stops after the drafts are found and asks:
Resume the newest, Start Fresh from the game file, or Choose a Draft... in
Drafts & Mods. Each answer loads the mesh once. Continue Editing, a next edit
pass and a retry already name what to open, so they never ask.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_saved_work_service import draft_lineage, read_draft_manifest
from cdmw.ui.mesh_editor.saved_work_launch import default_session_draft_request


class MeshEditorDraftChoiceMixin:
    def _build_draft_choice_page(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("MeshEditorDraftChoicePage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame(page)
        card.setObjectName("MeshEditorDraftChoiceCard")
        card.setMaximumWidth(620)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        self.draft_choice_title = QLabel("Continue where you left off?", card)
        self.draft_choice_title.setObjectName("EmptyStateTitle")
        font = self.draft_choice_title.font()
        font.setPointSizeF(font.pointSizeF() + 2)
        self.draft_choice_title.setFont(font)
        self.draft_choice_label = QLabel("", card)
        self.draft_choice_label.setObjectName("EmptyStateDetail")
        self.draft_choice_label.setWordWrap(True)
        self.draft_choice_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.draft_choice_title)
        layout.addWidget(self.draft_choice_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.draft_resume_button = QPushButton("Resume", card)
        self.draft_resume_button.setObjectName("MeshEditorDraftResumeButton")
        font = self.draft_resume_button.font()
        font.setBold(True)
        self.draft_resume_button.setFont(font)
        self.draft_start_fresh_button = QPushButton("Start Fresh", card)
        self.draft_start_fresh_button.setObjectName("MeshEditorDraftStartFreshButton")
        self.draft_choose_button = QPushButton("Choose a Draft...", card)
        self.draft_choose_button.setObjectName("MeshEditorDraftChooseButton")
        self.draft_choice_cancel_button = QPushButton("Cancel", card)
        self.draft_choice_cancel_button.setObjectName("MeshEditorDraftChoiceCancelButton")
        buttons.addWidget(self.draft_resume_button)
        buttons.addWidget(self.draft_start_fresh_button)
        buttons.addWidget(self.draft_choose_button)
        buttons.addStretch(1)
        buttons.addWidget(self.draft_choice_cancel_button)
        layout.addLayout(buttons)
        self.draft_resume_button.clicked.connect(self._resume_latest_archive_draft)
        self.draft_start_fresh_button.clicked.connect(self._start_fresh_from_archive_entry)
        self.draft_choose_button.clicked.connect(self._choose_archive_draft)
        self.draft_choice_cancel_button.clicked.connect(lambda _checked=False: self.show_empty_state())
        row.addWidget(card, 4)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.draft_choice_page = page
        self.mesh_editor_matching_drafts: tuple[object, ...] = ()
        return page

    def _draft_choice_showing(self) -> bool:
        page = getattr(self, "draft_choice_page", None)
        return page is not None and self.workspace_stack.currentWidget() is page

    def _leave_draft_choice(self) -> None:
        self.mesh_editor_matching_drafts = ()
        if self._draft_choice_showing():
            self.workspace_stack.setCurrentWidget(self.standalone_workspace)

    def _handle_archive_session_drafts_found(self, request_id: int, drafts: object) -> None:
        if int(request_id) != int(self.archive_session_load_request_id):
            return
        entry = self.archive_session_load_entry
        found = tuple(drafts or ())
        if not isinstance(entry, ArchiveEntry) or not found:
            return
        newest = found[0]
        newest_name = str(draft_lineage(read_draft_manifest(newest.manifest_path)).get("display_name") or "")
        saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest.updated_at))
        self.draft_choice_label.setText(
            f"{entry.basename} has {len(found)} saved draft(s). "
            f"The newest, {newest_name or newest.workspace_dir.name}, was saved {saved}. "
            "Resume it, or start fresh from this file. Your saved drafts are kept either way."
        )
        self.mesh_editor_matching_drafts = found
        self.standalone_status_label.setText("")
        self.workspace_stack.setCurrentWidget(self.draft_choice_page)
        self.draft_resume_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reopen_offered_archive_entry(self, **session_options: object) -> None:
        entry = self.current_archive_selection
        if not isinstance(entry, ArchiveEntry):
            self.show_empty_state()
            return
        self.open_archive_session(
            entry,
            material_preview_model=self.archive_session_load_material_model,
            material_companion_entry=self.archive_material_context_companion_entry,
            material_package_path=self.archive_material_context_package_path,
            material_package_lease=self.archive_material_context_package_lease,
            material_context_verified_for_rust=self.archive_material_context_verified_for_rust,
            material_source_identity=self.archive_material_context_source_identity,
            archive_dependencies=self.archive_session_dependencies,
            **session_options,
        )

    def _resume_latest_archive_draft(self, _checked: bool = False) -> None:
        drafts = tuple(self.mesh_editor_matching_drafts)
        manifest_path = getattr(drafts[0], "manifest_path", None) if drafts else None
        if manifest_path is None:
            self._start_fresh_from_archive_entry()
            return
        self._reopen_offered_archive_entry(resume_manifest_path=manifest_path)

    def _start_fresh_from_archive_entry(self, _checked: bool = False) -> None:
        entry = self.current_archive_selection
        if not isinstance(entry, ArchiveEntry):
            self.show_empty_state()
            return
        # Naming the request is what keeps the new open from asking again.
        self._reopen_offered_archive_entry(
            draft_request=default_session_draft_request(entry, self.archive_session_dependencies),
        )

    def _choose_archive_draft(self, _checked: bool = False) -> None:
        entry = self.current_archive_selection
        self.saved_work_requested.emit(entry.path if isinstance(entry, ArchiveEntry) else "")


__all__ = ["MeshEditorDraftChoiceMixin"]
