"""Archive referenced-file export and selection dialogs."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.ui.widgets import make_tree_columns_persistent


class ArchiveReferenceExportMixin:
    """Referenced file export helpers and reference selection dialog."""
    def _archive_reference_export_filter(self, entry: ArchiveEntry) -> str:
        extension = str(entry.extension or "").strip().lower()
        if extension == ".dds":
            return "DDS (*.dds)"
        if extension == ".xml":
            return "XML (*.xml);;All Files (*)"
        if extension == ".pami":
            return "PAMI (*.pami);;All Files (*)"
        if extension == ".json":
            return "JSON (*.json);;All Files (*)"
        if extension:
            return f"{extension.upper()} (*{extension});;All Files (*)"
        return "All Files (*)"

    def _export_archive_reference_entry(self, entry: ArchiveEntry, *, title: str = "Export Referenced File") -> None:
        default_dir = self.settings_file_path.parent / "archive_related_export"
        default_target = default_dir / entry.basename
        output_path, _selected = QFileDialog.getSaveFileName(
            self,
            title,
            str(default_target),
            self._archive_reference_export_filter(entry),
        )
        if not output_path:
            return

        def _task(log: Callable[[str], None]) -> Path:
            log(f"Exporting referenced file for {entry.path}...")
            source_path, _note = ensure_archive_preview_source(entry)
            target_path = Path(output_path).expanduser()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            return target_path.resolve()

        def _handle_complete(result: object) -> None:
            if not isinstance(result, Path):
                self.set_status_message("Referenced file export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(self, "Export Complete", f"Exported file:\n{result}")
            self.set_status_message(f"Exported {entry.basename}.")

        self._run_utility_task(
            status_message=f"Exporting {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _export_archive_reference_entries_to_folder(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        title: str,
    ) -> None:
        unique_entries: List[ArchiveEntry] = []
        seen_paths: set[str] = set()
        for entry in entries:
            normalized_path = entry.path.replace("\\", "/").strip().lower()
            if not normalized_path or normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            unique_entries.append(entry)
        if not unique_entries:
            self.set_status_message("No resolved referenced files are available to export.", error=True)
            return

        default_dir = self.settings_file_path.parent / "archive_related_export"
        output_dir = QFileDialog.getExistingDirectory(
            self,
            title,
            str(default_dir),
        )
        if not output_dir:
            return

        def _task(log: Callable[[str], None]) -> List[Path]:
            exported_root = Path(output_dir).expanduser()
            exported_paths: List[Path] = []
            for related_entry in unique_entries:
                source_path, _note = ensure_archive_preview_source(related_entry)
                target_path = exported_root.joinpath(*PurePosixPath(related_entry.path.replace("\\", "/")).parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                log(f"Exporting referenced file: {related_entry.path}")
                shutil.copy2(source_path, target_path)
                exported_paths.append(target_path.resolve())
            return exported_paths

        def _handle_complete(result: object) -> None:
            if not isinstance(result, list) or not all(isinstance(path, Path) for path in result):
                self.set_status_message("Referenced-file export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(result)} referenced file(s) into:\n{Path(output_dir).expanduser()}",
            )
            self.set_status_message(f"Exported {len(result)} referenced file(s).")

        self._run_utility_task(
            status_message=f"Exporting {len(unique_entries)} referenced file(s)...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _prompt_archive_reference_selection(
        self,
        *,
        title: str,
        intro_text: str,
        references: Sequence[ArchiveModelTextureReference],
        confirm_button_text: str = "Continue",
        default_checked: bool = True,
        parent: Optional[QWidget] = None,
    ) -> Optional[Tuple[ArchiveEntry, ...]]:
        resolved_references: List[ArchiveModelTextureReference] = []
        seen_paths: set[str] = set()
        for reference in references:
            resolved_entry = getattr(reference, "resolved_entry", None)
            if not isinstance(resolved_entry, ArchiveEntry):
                continue
            normalized_path = resolved_entry.path.replace("\\", "/").strip().lower()
            if not normalized_path or normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            resolved_references.append(reference)
        if not resolved_references:
            return ()

        dialog_parent = parent if parent is not None else self
        dialog = QDialog(dialog_parent)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(900, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro_label = QLabel(intro_text)
        intro_label.setWordWrap(True)
        intro_label.setObjectName("HintLabel")
        layout.addWidget(intro_label)

        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Include", "Type", "Semantic", "Archive Path", "Package"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        tree.setUniformRowHeights(True)
        tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
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
            "dialog/archive_reference_selection",
            minimum_width=48,
            save_callback=self.schedule_settings_save,
        )

        def _reference_type_label(reference: ArchiveModelTextureReference) -> str:
            relation_group = str(getattr(reference, "relation_group", "") or "").strip().lower()
            resolved_entry = getattr(reference, "resolved_entry", None)
            extension = str(getattr(resolved_entry, "extension", "") or "").strip().lower()
            reference_kind = str(getattr(reference, "reference_kind", "") or "").strip().lower()
            if relation_group == "textures" or reference_kind == "texture" or extension in {".dds", ".seqmt"}:
                return "Texture"
            if relation_group == "material sidecars" or extension in {".xml", ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"}:
                return "Material Sidecar"
            if relation_group == "mesh / model" or reference_kind in {"mesh", "lod"} or extension in {".pac", ".pam", ".pamlod"}:
                return "Mesh / Model"
            if relation_group == "skeleton / rig" or extension == ".pab":
                return "Skeleton / Rig"
            if relation_group == "physics / collision" or reference_kind == "physics":
                return "Physics / Collision"
            if relation_group == "animation / motion" or extension in {".hkx", ".hkt", ".motionblending", ".paa", ".paa_metabin", ".pae", ".paem", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
                return "Animation / Motion"
            if extension:
                return extension.lstrip(".").upper()
            return "Related File"

        for index, reference in enumerate(resolved_references):
            resolved_entry = reference.resolved_entry
            if not isinstance(resolved_entry, ArchiveEntry):
                continue
            label = str(getattr(reference, "reference_name", "") or "").strip() or resolved_entry.basename
            type_label = _reference_type_label(reference)
            item = QTreeWidgetItem(
                [
                    label,
                    type_label,
                    str(getattr(reference, "semantic_label", "") or "").strip() or "-",
                    resolved_entry.path,
                    resolved_entry.package_label,
                ]
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)
            item.setData(0, Qt.UserRole, index)
            item.setToolTip(3, resolved_entry.path)
            tree.addTopLevelItem(item)

        layout.addWidget(tree, stretch=1)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        select_all_button = QPushButton("Select All")
        select_none_button = QPushButton("Select None")
        controls_row.addWidget(select_all_button)
        controls_row.addWidget(select_none_button)
        controls_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        confirm_button = QPushButton(confirm_button_text)
        confirm_button.setDefault(True)
        controls_row.addWidget(cancel_button)
        controls_row.addWidget(confirm_button)
        layout.addLayout(controls_row)

        result: List[ArchiveEntry] = []

        def _set_all(check_state: Qt.CheckState) -> None:
            for row_index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(row_index)
                if item is not None:
                    item.setCheckState(0, check_state)

        def _accept() -> None:
            selected_entries: List[ArchiveEntry] = []
            for row_index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(row_index)
                if item is None or item.checkState(0) != Qt.Checked:
                    continue
                raw_index = item.data(0, Qt.UserRole)
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < len(resolved_references):
                    resolved_entry = getattr(resolved_references[index], "resolved_entry", None)
                    if isinstance(resolved_entry, ArchiveEntry):
                        selected_entries.append(resolved_entry)
            result[:] = selected_entries
            dialog.accept()

        select_all_button.clicked.connect(lambda: _set_all(Qt.Checked))
        select_none_button.clicked.connect(lambda: _set_all(Qt.Unchecked))
        cancel_button.clicked.connect(dialog.reject)
        confirm_button.clicked.connect(_accept)

        if dialog.exec() != QDialog.Accepted:
            return None
        return tuple(result)

    def _choose_archive_write_target(
        self,
        *,
        title: str,
        message: str,
        allow_archive_patch: bool,
    ) -> str:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Question)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setInformativeText(
            "Patch Game Archives updates the installed package files and recalculates checksums. "
            "Write Mod-Ready Loose File creates a loose mod package instead."
        )
        patch_button = None
        if allow_archive_patch:
            patch_button = dialog.addButton("Patch Game Archives", QMessageBox.AcceptRole)
        loose_button = dialog.addButton("Write Mod-Ready Loose File", QMessageBox.ActionRole)
        cancel_button = dialog.addButton(QMessageBox.Cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        if patch_button is not None and clicked is patch_button:
            return "patch"
        if clicked is loose_button:
            return "loose"
        if clicked is cancel_button:
            return ""
        return ""
