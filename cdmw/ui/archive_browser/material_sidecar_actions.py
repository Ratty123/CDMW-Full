"""Archive browser material-sidecar selection and preview helper actions."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.services.preview_workflow_service import try_decode_text_like_archive_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.material_sidecar_service import (
    MaterialSidecarRelatedFile,
    detect_material_sidecar_preview_model_candidates,
    discover_material_sidecar_preview_overrides,
    discover_material_sidecar_preview_overrides_for_edits,
    discover_material_sidecar_values,
    is_material_sidecar_entry,
    material_sidecar_candidate_basenames_for_model,
)
from cdmw.services.texture_workflow_service import normalize_texture_reference_for_sidecar_lookup
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
)
from cdmw.ui.widgets import make_tree_columns_persistent


class ArchiveMaterialSidecarActionsMixin:
    """Helpers used by the material-sidecar editor and related archive actions."""



    def _current_or_related_material_sidecar_entry(self) -> Optional[ArchiveEntry]:
        current_entry = self._current_archive_entry()
        if isinstance(current_entry, ArchiveEntry) and is_material_sidecar_entry(current_entry):
            try:
                return archive_workflow_dependency_context(self, current_entry).selected_entry
            except ArchiveWorkflowDependenciesUnavailable:
                return None
        for reference in self.current_archive_model_texture_references:
            resolved_entry = getattr(reference, "resolved_entry", None)
            if isinstance(resolved_entry, ArchiveEntry) and is_material_sidecar_entry(resolved_entry):
                return resolved_entry
        if not isinstance(current_entry, ArchiveEntry):
            return None
        return self._related_material_sidecar_entry_for_archive_entry(current_entry)

    def _related_material_sidecar_entry_for_archive_entry(self, entry: Optional[ArchiveEntry]) -> Optional[ArchiveEntry]:
        if not isinstance(entry, ArchiveEntry):
            return None
        try:
            dependencies = archive_workflow_dependency_context(self, entry)
        except ArchiveWorkflowDependenciesUnavailable:
            return None
        entry = dependencies.selected_entry
        if is_material_sidecar_entry(entry):
            return entry
        source_path = entry.path.replace("\\", "/").strip()
        source_virtual_path = PurePosixPath(source_path)
        candidate_basenames = material_sidecar_candidate_basenames_for_model(source_path)
        for basename in candidate_basenames:
            candidate_path = (source_virtual_path.parent / basename).as_posix()
            if dependencies.remote:
                candidate = dependencies.entry_for_path(candidate_path)
            else:
                candidate = self._find_archive_entry_by_virtual_path(candidate_path)
            if is_material_sidecar_entry(candidate):
                return candidate
        for basename in candidate_basenames:
            for candidate in dependencies.entries_by_basename.get(basename.lower(), ()):
                if is_material_sidecar_entry(candidate):
                    return candidate
        return None

    def _material_sidecar_selection_candidates(self) -> List[ArchiveEntry]:
        candidates: List[ArchiveEntry] = []
        seen_paths: set[str] = set()

        def add(entry: Optional[ArchiveEntry]) -> None:
            if not isinstance(entry, ArchiveEntry) or not is_material_sidecar_entry(entry):
                return
            normalized = entry.path.replace("\\", "/").strip().lower()
            if not normalized or normalized in seen_paths:
                return
            seen_paths.add(normalized)
            candidates.append(entry)

        add(self._current_archive_entry())
        for reference in self.current_archive_model_texture_references:
            add(getattr(reference, "resolved_entry", None))
        add(self._current_or_related_material_sidecar_entry())
        return candidates

    def _choose_material_sidecar_entry(self, entries: Sequence[ArchiveEntry]) -> Optional[ArchiveEntry]:
        unique_entries: List[ArchiveEntry] = []
        seen_paths: set[str] = set()
        for entry in entries:
            normalized = entry.path.replace("\\", "/").strip().lower()
            if normalized and normalized not in seen_paths:
                seen_paths.add(normalized)
                unique_entries.append(entry)
        if not unique_entries:
            return None
        if len(unique_entries) == 1:
            return unique_entries[0]
        labels = [f"{entry.path} [{entry.package_label}]" for entry in unique_entries]
        selected, accepted = QInputDialog.getItem(
            self,
            "Choose Material Sidecar",
            "Material sidecar",
            labels,
            0,
            False,
        )
        if not accepted or not selected:
            return None
        selected_index = labels.index(selected)
        return unique_entries[selected_index]

    def _edit_current_archive_material_sidecar(self) -> None:
        entry = self._choose_material_sidecar_entry(self._material_sidecar_selection_candidates())
        if entry is None:
            self.set_status_message("No material sidecar is available for the current archive selection.", error=True)
            return
        self._open_material_sidecar_editor(entry)

    def _edit_selected_archive_material_sidecar_reference(self) -> None:
        selected_entries = self._resolved_archive_reference_entries(self._selected_archive_texture_references())
        entry = selected_entries[0] if len(selected_entries) == 1 else None
        if not isinstance(entry, ArchiveEntry) or not is_material_sidecar_entry(entry):
            self.set_status_message("Select one resolved material sidecar reference first.", error=True)
            return
        self._open_material_sidecar_editor(entry)

    @staticmethod
    def _decode_material_sidecar_bytes(data: bytes) -> str:
        decoded = try_decode_text_like_archive_data(data)
        if decoded is not None:
            return decoded
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _qcolor_from_material_value(value: str) -> QColor:
        text = str(value or "").strip()
        if re.fullmatch(r"#?[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
            return QColor("#" + text.lstrip("#")[:6])
        numbers: List[float] = []
        for token in re.split(r"[\s,;]+", text):
            try:
                numbers.append(float(token))
            except ValueError:
                continue
            if len(numbers) >= 3:
                break
        if len(numbers) >= 3:
            return QColor(
                max(0, min(255, round(numbers[0] * 255))),
                max(0, min(255, round(numbers[1] * 255))),
                max(0, min(255, round(numbers[2] * 255))),
            )
        return QColor("#ffffff")

    def _prompt_material_sidecar_related_files(
        self,
        related_files: Sequence[MaterialSidecarRelatedFile],
        *,
        edited_entry: ArchiveEntry,
    ) -> Optional[Tuple[ArchiveEntry, ...]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Review Related Files")
        dialog.setModal(True)
        dialog.resize(920, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel("Review related files to include with the edited material sidecar.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Include", "Confidence", "Reason", "Archive Path", "Package"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        tree.setUniformRowHeights(True)
        edited_item = QTreeWidgetItem(
            [
                "",
                "edited",
                "Edited material sidecar; always included",
                edited_entry.path,
                edited_entry.package_label,
            ]
        )
        edited_item.setFlags((edited_item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
        edited_item.setCheckState(0, Qt.Checked)
        edited_item.setData(0, Qt.UserRole, -1)
        tree.addTopLevelItem(edited_item)
        for index, related in enumerate(related_files):
            entry = related.entry
            item = QTreeWidgetItem(
                [
                    "",
                    related.confidence,
                    related.reason,
                    entry.path,
                    entry.package_label,
                ]
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, index)
            tree.addTopLevelItem(item)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        make_tree_columns_persistent(
            tree,
            self.settings,
            "dialog/material_sidecar_related_files",
            minimum_width=48,
            save_callback=self.schedule_settings_save,
        )
        layout.addWidget(tree, stretch=1)

        button_row = QHBoxLayout()
        select_all_button = QPushButton("Select All")
        select_none_button = QPushButton("Select None")
        button_row.addWidget(select_all_button)
        button_row.addWidget(select_none_button)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        continue_button = QPushButton("Continue")
        continue_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(continue_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(dialog.accept)

        def _set_related_checks(state: Qt.CheckState) -> None:
            for row in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(row)
                raw_index = item.data(0, Qt.UserRole)
                try:
                    related_index = int(raw_index)
                except (TypeError, ValueError):
                    related_index = -1
                if related_index < 0:
                    item.setCheckState(0, Qt.Checked)
                else:
                    item.setCheckState(0, state)

        select_all_button.clicked.connect(lambda _checked=False: _set_related_checks(Qt.Checked))
        select_none_button.clicked.connect(lambda _checked=False: _set_related_checks(Qt.Unchecked))

        if dialog.exec() != QDialog.Accepted:
            return None
        selected_entries: List[ArchiveEntry] = []
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if item.checkState(0) != Qt.Checked:
                continue
            raw_index = item.data(0, Qt.UserRole)
            try:
                related_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if related_index < 0:
                continue
            if 0 <= related_index < len(related_files):
                selected_entries.append(related_files[related_index].entry)
        return tuple(selected_entries)

    def _material_sidecar_preview_model_candidate(
        self,
        entry: ArchiveEntry,
        sidecar_text: str,
    ) -> Optional[ArchiveEntry]:
        try:
            dependencies = archive_workflow_dependency_context(self, entry)
        except ArchiveWorkflowDependenciesUnavailable:
            return None
        entry = dependencies.selected_entry
        current_entry = self._current_archive_entry()
        candidates = detect_material_sidecar_preview_model_candidates(
            entry,
            sidecar_text=sidecar_text,
            current_entry=current_entry,
            references=tuple(self.current_archive_model_texture_references),
            archive_entries_by_basename=dependencies.entries_by_basename,
            archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
        )
        return candidates[0].entry if candidates else None

    def _material_sidecar_texture_resolution_warnings(
        self,
        sidecar_text: str,
        *,
        entry: Optional[ArchiveEntry] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[str, ...]:
        current_entry = entry
        current_entry_getter = getattr(self, "_current_archive_entry", None)
        if not isinstance(current_entry, ArchiveEntry) and callable(current_entry_getter):
            current_entry = current_entry_getter()
        if isinstance(current_entry, ArchiveEntry):
            try:
                dependencies = archive_workflow_dependency_context(self, current_entry)
            except ArchiveWorkflowDependenciesUnavailable:
                return ("Archive dependencies are unavailable for texture resolution.",)
            entries_by_normalized_path = dependencies.entries_by_normalized_path
            entries_by_basename = dependencies.entries_by_basename
        else:
            entries_by_normalized_path = getattr(self, "archive_entries_by_normalized_path", {}) or {}
            entries_by_basename = getattr(self, "archive_entries_by_basename", {}) or {}
        warnings: List[str] = []
        rows = discover_material_sidecar_values(sidecar_text)
        for row in rows:
            raise_if_cancelled(stop_event, "Material texture validation cancelled.")
            if row.kind != "texture":
                continue
            texture_path = str(row.value or "").replace("\\", "/").strip()
            if not texture_path:
                continue
            normalized = normalize_texture_reference_for_sidecar_lookup(texture_path)
            basename = PurePosixPath(texture_path).name.lower()
            if normalized and entries_by_normalized_path.get(normalized):
                continue
            if basename and entries_by_basename.get(basename):
                continue
            warnings.append(f"Unresolved texture path: {texture_path}")
            if len(warnings) >= 4:
                break
        return tuple(warnings)

    @staticmethod
    def _normalized_material_preview_label(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _apply_material_sidecar_preview_overrides_to_model(
        self,
        preview_model: Optional[object],
        sidecar_text: str,
        *,
        edited_values: Optional[Mapping[str, str]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[str, ...]:
        raise_if_cancelled(stop_event, "Material live preview cancelled.")
        if not isinstance(preview_model, ModelPreviewData):
            return ()
        meshes = [
            mesh
            for mesh in (getattr(preview_model, "meshes", None) or [])
            if isinstance(mesh, ModelPreviewMesh)
        ]
        if not meshes:
            return ()
        if edited_values is None:
            overrides = discover_material_sidecar_preview_overrides(sidecar_text)
        else:
            overrides = discover_material_sidecar_preview_overrides_for_edits(sidecar_text, edited_values)
        if not overrides:
            return ()
        notes: List[str] = []
        applied_count = 0
        low_confidence_count = 0

        def apply_override(mesh: ModelPreviewMesh, override: object, *, low_confidence: bool) -> None:
            nonlocal applied_count, low_confidence_count
            tint_color = tuple(getattr(override, "tint_color", ()) or ())
            if len(tint_color) >= 3:
                color = (
                    max(0.0, min(1.0, float(tint_color[0]))),
                    max(0.0, min(1.0, float(tint_color[1]))),
                    max(0.0, min(1.0, float(tint_color[2]))),
                )
                mesh.preview_color = color
                mesh.preview_texture_tint = (
                    max(0.0, min(2.0, float(tint_color[0]))),
                    max(0.0, min(2.0, float(tint_color[1]))),
                    max(0.0, min(2.0, float(tint_color[2]))),
                )
            brightness = max(0.1, min(3.0, float(getattr(override, "brightness", 1.0) or 1.0)))
            mesh.preview_texture_brightness = brightness
            uv_scale = max(0.05, min(64.0, float(getattr(override, "uv_scale", 1.0) or 1.0)))
            if abs(uv_scale - 1.0) > 1e-6:
                mesh.preview_texture_uv_scale = (uv_scale, uv_scale)
            if low_confidence:
                low_confidence_count += 1
            applied_count += 1
            mesh.preview_texture_approximation_note = "Edited material XML preview approximation."

        unused_overrides = list(overrides)
        for mesh in meshes:
            raise_if_cancelled(stop_event, "Material live preview cancelled.")
            mesh_labels = {
                self._normalized_material_preview_label(getattr(mesh, "material_name", "")),
                self._normalized_material_preview_label(getattr(mesh, "texture_name", "")),
                self._normalized_material_preview_label(getattr(mesh, "preview_sidecar_material_primitive", "")),
            }
            mesh_labels.discard("")
            matched_override = None
            for override in overrides:
                override_label = self._normalized_material_preview_label(getattr(override, "group_label", ""))
                if override_label and override_label in mesh_labels:
                    matched_override = override
                    break
            if matched_override is not None:
                apply_override(mesh, matched_override, low_confidence=False)
                if matched_override in unused_overrides:
                    unused_overrides.remove(matched_override)

        if applied_count <= 0:
            if len(overrides) == 1:
                for mesh in meshes:
                    raise_if_cancelled(stop_event, "Material live preview cancelled.")
                    apply_override(mesh, overrides[0], low_confidence=False)
            else:
                for mesh_index, mesh in enumerate(meshes):
                    raise_if_cancelled(stop_event, "Material live preview cancelled.")
                    override = overrides[min(mesh_index, len(overrides) - 1)]
                    apply_override(mesh, override, low_confidence=True)
        elif unused_overrides and len(meshes) == 1:
            apply_override(meshes[0], unused_overrides[0], low_confidence=True)

        if applied_count > 0:
            notes.append(f"Applied {applied_count:,} edited material preview approximation(s).")
        if low_confidence_count > 0:
            notes.append(f"{low_confidence_count:,} preview assignment(s) used low-confidence material matching.")
        if any("dye" in str(getattr(override, "reason", "") or "").lower() for override in overrides):
            notes.append("Dye and mask colors are approximated by the toolkit preview shader, not the exact game shader.")
        return tuple(notes)

__all__ = ["ArchiveMaterialSidecarActionsMixin"]
