"""Session-local edited mesh results alongside the unchanged archive catalogue."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_archive_results import MeshArchiveResult
from cdmw.ui.archive_browser.workflow_dependencies import archive_result_dependency_context


class ArchiveEditedResultsMixin:
    def _build_archive_edited_results(self):
        group = QGroupBox("Edited results")
        group.setObjectName("ArchiveEditedResults")
        layout = QVBoxLayout(group)
        hint = QLabel("Edited meshes for this session, with their source materials, textures and rig.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.archive_edited_results_list = QListWidget()
        self.archive_edited_results_list.setObjectName("ArchiveEditedResultsList")
        self.archive_edited_results_list.setMaximumHeight(150)
        layout.addWidget(self.archive_edited_results_list)
        button = QPushButton("Open in Mesh Editor")
        button.setObjectName("ArchiveOpenEditedResult")
        button.clicked.connect(self._open_archive_edited_result)
        self.archive_edited_results_list.itemDoubleClicked.connect(lambda _item: self._open_archive_edited_result())
        layout.addWidget(button)
        self.archive_edited_results_group = group
        self._archive_edited_contexts = {}
        self._archive_edited_result_number = 0
        group.hide()
        return group

    def edited_result_context(self, entry):
        if not isinstance(entry, ArchiveEntry) or not entry.prepared_sha256:
            return None
        return getattr(self, "_archive_edited_contexts", {}).get(
            (entry.identity, entry.prepared_sha256, str(entry.prepared_path)))

    def add_mesh_editor_result(self, result):
        if not isinstance(result, MeshArchiveResult):
            return
        context = archive_result_dependency_context(result)
        self._archive_edited_result_number += 1
        for entry in result.assets:
            key = (entry.identity, entry.prepared_sha256, str(entry.prepared_path))
            self._archive_edited_contexts[key] = replace(context, selected_entry=entry)
            item = QListWidgetItem(f"{entry.basename} (edit {self._archive_edited_result_number})")
            item.setToolTip(entry.path)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.archive_edited_results_list.addItem(item)
            self.archive_edited_results_list.setCurrentItem(item)
        self.archive_edited_results_group.show()
        self.shell._activate_tool_widget(self)

    def _open_archive_edited_result(self):
        item = self.archive_edited_results_list.currentItem()
        if item is None:
            return
        context = self._archive_edited_contexts.get(item.data(Qt.ItemDataRole.UserRole))
        if context is not None:
            self.shell._launch_archive_mesh_editor_for_entry(context.selected_entry)
