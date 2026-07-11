"""Loose-mod overlay source-mix dialog."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.services.texture_workflow_service import (
    SourceMixCandidate,
    SourceMixSelection,
    group_source_mix_candidates_by_family,
    source_mix_role_for_virtual_path,
    validate_source_mix_selections,
)
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.source_mix_task_controller import (
    source_mix_task_controller_for_guard,
)
from cdmw.workers.source_mix_workers import (
    SceneImportRequest,
    SceneImportTaskResult,
    SourceMixIndexSnapshot,
    SourceMixScanRequest,
    SourceMixScanResult,
    run_scene_import,
    run_source_mix_scan,
)


class ArchiveSourceMixOverlayMixin:
    def _open_archive_loose_mod_overlay_dialog(
        self,
        _checked: bool = False,
        *,
        _scan_result: object | None = None,
        _selected_dir: str = "",
    ) -> None:
        if not isinstance(_scan_result, SourceMixScanResult):
            selected_dir = QFileDialog.getExistingDirectory(
                self,
                "Import Loose Mod Folder",
                str(self._suggest_workspace_base_dir()),
            )
            if not selected_dir:
                return
            scan_root = Path(selected_dir)
            controller = source_mix_task_controller_for_guard(
                self,
                self,
                attribute="_source_mix_overlay_scan_controller",
            )
            request = SourceMixScanRequest(
                source_path=scan_root,
                source_kind="loose",
                index_snapshot=SourceMixIndexSnapshot.capture(
                    self.archive_entries_by_normalized_path,
                    self.archive_entries_by_basename,
                ),
            )
            controller.start(
                request,
                run_source_mix_scan,
                status_message=f"Scanning loose mod folder: {scan_root.name}...",
                on_complete=lambda result: self._open_archive_loose_mod_overlay_dialog(
                    _scan_result=result,
                    _selected_dir=str(scan_root),
                ),
                on_error=lambda message: QMessageBox.warning(
                    self,
                    "Import Loose Mod Folder",
                    message,
                ),
            )
            return
        selected_dir = str(_selected_dir or _scan_result.source_path)
        candidates = _scan_result.candidates
        if not candidates:
            QMessageBox.information(self, "Import Loose Mod Folder", "No payload files were found in the selected folder.")
            return

        exact_candidates = [candidate for candidate in candidates if isinstance(candidate.target_archive_entry, ArchiveEntry)]
        extras = [candidate for candidate in candidates if not isinstance(candidate.target_archive_entry, ArchiveEntry)]
        conflicts = [candidate for candidate in candidates if candidate.conflict_status == "conflict"]
        family_groups = group_source_mix_candidates_by_family(candidates)
        dialog = QDialog(self)
        dialog.setWindowTitle("Loose Mod Overlay Review")
        dialog.resize(1180, 760)
        source_task_controller = source_mix_task_controller_for_guard(self, dialog)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        summary = QLabel(
            f"{len(candidates):,} source file(s) scanned from {Path(selected_dir).name}. "
            f"{len(exact_candidates):,} archive target match(es), {len(family_groups):,} asset family group(s), "
            f"{len(extras):,} extra file(s), {len(conflicts):,} conflict row(s). "
            "Archive matches default to Replace. Compact loose mods can match by filename when their paths are flattened. "
            "Extras are skipped unless a later workflow explicitly includes them."
        )
        summary.setObjectName("HintLabel")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        all_tree = QTreeWidget()
        family_tree = QTreeWidget()
        conflict_tree = QTreeWidget()
        extras_tree = QTreeWidget()
        for tree in (all_tree, family_tree, conflict_tree, extras_tree):
            tree.setColumnCount(7)
            tree.setHeaderLabels(["Use", "Virtual Path", "Role", "Target", "Source", "Size", "Status"])
            tree.setRootIsDecorated(tree is family_tree)
            tree.setAlternatingRowColors(True)
            tree.setUniformRowHeights(True)
            tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
            tree.header().setStretchLastSection(True)
            tree.header().resizeSection(0, 64)
            tree.header().resizeSection(1, 360)
            tree.header().resizeSection(2, 140)
            tree.header().resizeSection(3, 150)
            tree.header().resizeSection(4, 220)
            tree.header().resizeSection(5, 90)
        tabs.addTab(all_tree, "All Matches")
        tabs.addTab(family_tree, "Asset Families")
        tabs.addTab(conflict_tree, "Conflicts")
        tabs.addTab(extras_tree, "Extras")

        candidate_item_by_key: Dict[Tuple[str, str, int, str], List[QTreeWidgetItem]] = {}

        def _candidate_key(candidate: SourceMixCandidate) -> Tuple[str, str, int, str]:
            return (
                candidate.normalized_virtual_path,
                str(candidate.source_path or ""),
                int(candidate.size or 0),
                candidate.layer.source_id,
            )

        def _candidate_status(candidate: SourceMixCandidate) -> str:
            parts = [
                str(candidate.match_status or "extra"),
                str(candidate.conflict_status or "none"),
                str(candidate.default_action or "skip"),
            ]
            return " | ".join(part for part in parts if part)

        def _make_candidate_item(candidate: SourceMixCandidate) -> QTreeWidgetItem:
            target_entry = candidate.target_archive_entry
            target_text = target_entry.package_label if isinstance(target_entry, ArchiveEntry) else "-"
            item = QTreeWidgetItem(
                [
                    "Replace" if candidate.default_action == "replace" else "Skip",
                    candidate.display_path,
                    candidate.role or source_mix_role_for_virtual_path(candidate.display_path),
                    target_text,
                    candidate.layer.label,
                    f"{int(candidate.size or 0):,}",
                    _candidate_status(candidate),
                ]
            )
            item.setData(0, Qt.UserRole, candidate)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if candidate.default_action == "replace" else Qt.Unchecked)
            item.setToolTip(1, candidate.display_path)
            item.setToolTip(6, candidate.confidence or "Source-mix evidence.")
            if candidate.default_action == "resolve":
                item.setForeground(6, QBrush(QColor("#fbbf24")))
            elif candidate.default_action == "replace":
                item.setForeground(0, QBrush(QColor("#86efac")))
            elif not isinstance(candidate.target_archive_entry, ArchiveEntry):
                item.setForeground(0, QBrush(QColor("#9ca3af")))
            candidate_item_by_key.setdefault(_candidate_key(candidate), []).append(item)
            return item

        for candidate in candidates:
            all_tree.addTopLevelItem(_make_candidate_item(candidate))
        for family_id, family_candidates in sorted(family_groups.items(), key=lambda item: item[0]):
            exact_count = sum(1 for candidate in family_candidates if isinstance(candidate.target_archive_entry, ArchiveEntry))
            family_item = QTreeWidgetItem(
                [
                    "",
                    family_id,
                    "Asset Family",
                    f"{exact_count:,} matched",
                    "",
                    f"{len(family_candidates):,}",
                    "family group",
                ]
            )
            family_item.setData(0, Qt.UserRole, ("family", family_id))
            family_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            family_item.setExpanded(False)
            family_tree.addTopLevelItem(family_item)
            for candidate in sorted(family_candidates, key=lambda row: (row.role, row.display_path)):
                family_item.addChild(_make_candidate_item(candidate))
        for candidate in conflicts:
            conflict_tree.addTopLevelItem(_make_candidate_item(candidate))
        for candidate in extras:
            extras_tree.addTopLevelItem(_make_candidate_item(candidate))

        status_label = QLabel("Selected archive matches are written byte-for-byte into a mod-ready loose package.")
        status_label.setObjectName("HintLabel")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        def _all_candidate_items() -> List[QTreeWidgetItem]:
            items: List[QTreeWidgetItem] = []
            for tree in (all_tree, family_tree, conflict_tree, extras_tree):
                stack = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
                while stack:
                    item = stack.pop(0)
                    if item is None:
                        continue
                    if isinstance(item.data(0, Qt.UserRole), SourceMixCandidate):
                        items.append(item)
                    stack[0:0] = [item.child(index) for index in range(item.childCount())]
            return items

        def _set_candidate_checked(candidate: SourceMixCandidate, checked: bool) -> None:
            for item in candidate_item_by_key.get(_candidate_key(candidate), ()):
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                item.setText(0, "Replace" if checked else "Skip")

        def _select_candidates(predicate: Callable[[SourceMixCandidate], bool], checked: bool = True) -> None:
            for candidate in candidates:
                if predicate(candidate):
                    _set_candidate_checked(candidate, checked)
            _refresh_overlay_status()

        def _checked_exact_candidates() -> List[SourceMixCandidate]:
            selected: List[SourceMixCandidate] = []
            seen: set[Tuple[str, str, int, str]] = set()
            for item in _all_candidate_items():
                candidate = item.data(0, Qt.UserRole)
                if not isinstance(candidate, SourceMixCandidate):
                    continue
                key = _candidate_key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                if item.checkState(0) == Qt.Checked and isinstance(candidate.target_archive_entry, ArchiveEntry):
                    selected.append(candidate)
            return selected

        def _refresh_overlay_status() -> None:
            selected = _checked_exact_candidates()
            status_label.setText(
                f"{len(selected):,} archive replacement row(s) selected. "
                f"{len(extras):,} extra source file(s) remain skipped by default; {len(conflicts):,} conflict row(s) require review."
            )

        overlay_sync_state = {"active": False}

        def _overlay_item_changed(item: QTreeWidgetItem, column: int) -> None:
            if column != 0 or overlay_sync_state["active"]:
                _refresh_overlay_status()
                return
            candidate = item.data(0, Qt.UserRole)
            if isinstance(candidate, SourceMixCandidate):
                overlay_sync_state["active"] = True
                try:
                    _set_candidate_checked(candidate, item.checkState(0) == Qt.Checked)
                finally:
                    overlay_sync_state["active"] = False
            _refresh_overlay_status()

        for tree in (all_tree, family_tree, conflict_tree, extras_tree):
            tree.itemChanged.connect(_overlay_item_changed)

        button_row = QHBoxLayout()
        select_family_button = QPushButton("Select Exact Family")
        select_all_families_button = QPushButton("Select All Families")
        select_all_exact_button = QPushButton("Select All Exact Matches")
        clear_button = QPushButton("Clear")
        use_mesh_source_button = QPushButton("Use as Mesh Replacement Source")
        write_button = QPushButton("Write Loose Package")
        close_button = QPushButton("Close")
        button_row.addWidget(select_family_button)
        button_row.addWidget(select_all_families_button)
        button_row.addWidget(select_all_exact_button)
        button_row.addWidget(clear_button)
        button_row.addWidget(use_mesh_source_button)
        button_row.addStretch(1)
        button_row.addWidget(write_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _selected_family_id() -> str:
            item = family_tree.currentItem()
            while item is not None:
                data = item.data(0, Qt.UserRole)
                if isinstance(data, tuple) and len(data) == 2 and data[0] == "family":
                    return str(data[1] or "")
                item = item.parent()
            return ""

        def _select_exact_family() -> None:
            family_id = _selected_family_id()
            if not family_id:
                self.set_status_message("Select a family row first.", error=True)
                return
            _select_candidates(
                lambda candidate: candidate.family_id == family_id and isinstance(candidate.target_archive_entry, ArchiveEntry),
                True,
            )

        select_family_button.clicked.connect(lambda _checked=False: _select_exact_family())
        select_all_families_button.clicked.connect(
            lambda _checked=False: _select_candidates(lambda candidate: isinstance(candidate.target_archive_entry, ArchiveEntry), True)
        )
        select_all_exact_button.clicked.connect(
            lambda _checked=False: _select_candidates(lambda candidate: isinstance(candidate.target_archive_entry, ArchiveEntry), True)
        )
        clear_button.clicked.connect(lambda _checked=False: _select_candidates(lambda _candidate: True, False))
        close_button.clicked.connect(dialog.reject)

        def _current_overlay_candidate() -> Optional[SourceMixCandidate]:
            current_tree = tabs.currentWidget()
            if not isinstance(current_tree, QTreeWidget):
                return None
            item = current_tree.currentItem()
            while item is not None:
                candidate = item.data(0, Qt.UserRole)
                if isinstance(candidate, SourceMixCandidate):
                    return candidate
                item = item.parent()
            return None

        def _use_current_candidate_as_mesh_source() -> None:
            candidate = _current_overlay_candidate()
            if not isinstance(candidate, SourceMixCandidate):
                self.set_status_message("Select a loose model candidate first.", error=True)
                return
            if candidate.extension not in ARCHIVE_MESH_EXTENSIONS or not isinstance(candidate.source_path, Path):
                self.set_status_message("Only loose .pac/.pam/.pamlod rows can be used as Mesh Replacement sources.", error=True)
                return
            target_entry = candidate.target_archive_entry
            if not isinstance(target_entry, ArchiveEntry):
                self.set_status_message("This source row has no archive target to replace.", error=True)
                return
            source_path = candidate.source_path

            def _scene_imported(result: object) -> None:
                if not isinstance(result, SceneImportTaskResult):
                    QMessageBox.warning(dialog, "Use as Mesh Replacement Source", "Scene import returned an unexpected result.")
                    return
                scene_result = result.scene
                supplemental_paths = (
                    tuple(scene_result.discovered_texture_files)
                    + tuple(scene_result.extracted_embedded_files)
                    + tuple(getattr(scene_result, "discovered_supplemental_files", ()) or ())
                )
                dialog.accept()
                QTimer.singleShot(
                    0,
                    lambda target=target_entry, imported_path=source_path, scene=scene_result, supplementals=supplemental_paths: self._start_archive_mesh_patch(
                        target,
                        preset_setup=MeshImportSetupSelection(
                            scene_path=imported_path,
                            import_mode="static_replacement",
                            supplemental_files=tuple(supplementals),
                            scene_import_result=scene,
                            source_label=f"Loose family source: {imported_path}",
                            placement_review_title="Loose Family Mesh Source Placement",
                            placement_context_note=(
                                "This source came from a loose mod family overlay. Review geometry, textures, and placement before export."
                            ),
                        ),
                    ),
                )

            started = source_task_controller.start(
                SceneImportRequest(source_path=source_path),
                run_scene_import,
                status_message=f"Importing loose mesh source: {source_path.name}...",
                on_complete=_scene_imported,
                on_error=lambda message: QMessageBox.warning(
                    dialog,
                    "Use as Mesh Replacement Source",
                    message,
                ),
                on_idle=lambda: use_mesh_source_button.setEnabled(True),
            )
            if started:
                use_mesh_source_button.setEnabled(False)

        use_mesh_source_button.clicked.connect(lambda _checked=False: _use_current_candidate_as_mesh_source())

        def _write_overlay_package() -> None:
            selected = _checked_exact_candidates()
            if not selected:
                QMessageBox.information(dialog, "Loose Mod Overlay Review", "Select at least one archive target match first.")
                return
            selections = [
                SourceMixSelection(
                    candidate.target_archive_entry.path if isinstance(candidate.target_archive_entry, ArchiveEntry) else candidate.display_path,
                    candidate,
                    "replace",
                )
                for candidate in selected
            ]
            validation = validate_source_mix_selections(selections)
            if not validation.ok:
                QMessageBox.warning(dialog, "Loose Mod Overlay Validation", "\n".join(validation.blocking_errors[:12]))
                return
            extra_payload_specs = self._source_mix_sidecar_referenced_payload_specs(selected, candidates)
            dialog.accept()
            export_target = self._collect_archive_mod_ready_export_target(
                browse_title="Select Mod-Ready Loose Export Root",
                prompt_for_metadata=True,
                dialog_title="Write Loose Mod Overlay Package",
                allow_dmm_texture_structure=False,
            )
            if export_target is None:
                return
            parent_root, package_info, create_no_encrypt, _include_related_files, export_options = export_target

            def _commit_task(log: Callable[[str], None]) -> object:
                requests: List[ArchivePatchRequest] = []
                for candidate in selected:
                    if not isinstance(candidate.target_archive_entry, ArchiveEntry):
                        continue
                    log(f"Reading {candidate.display_path} from {candidate.layer.label}...")
                    requests.append(
                        ArchivePatchRequest(
                            entry=candidate.target_archive_entry,
                            payload_data=candidate.read_payload(),
                        )
                    )
                if not requests:
                    raise ValueError("No exact archive replacement payloads were selected.")
                if extra_payload_specs:
                    log(
                        f"Auto-including {len(extra_payload_specs):,} sidecar-referenced texture payload(s) from the loose source package."
                    )
                log(
                    f"Writing {len(requests):,} overlay replacement(s). "
                    f"Skipped extras: {len(extras):,}; conflict rows in source folder: {len(conflicts):,}."
                )
                return export_archive_payloads_to_mod_ready_loose(
                    requests,
                    parent_root=parent_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt,
                    extra_payloads_to_include=extra_payload_specs,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if not isinstance(result, ArchiveLooseExportResult):
                    self.set_status_message("Loose mod overlay export finished with an unexpected result payload.", error=True)
                    return
                QMessageBox.information(
                    self,
                    "Loose Mod Overlay Export Complete",
                    f"Wrote selected overlay payload(s) into:\n{result.package_root}",
                )
                self.set_status_message(f"Wrote loose mod overlay package: {result.package_root}")

            self._run_utility_task_when_idle(
                status_message=f"Writing loose mod overlay package from {Path(selected_dir).name}...",
                task=_commit_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        write_button.clicked.connect(lambda _checked=False: _write_overlay_package())
        _refresh_overlay_status()
        dialog.exec()
