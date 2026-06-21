"""Archive attachment batch placement dialog and package build flow."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.archive_modding import (
    ArchiveLooseExportResult,
    ArchivePatchRequest,
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.shell.responsiveness_controller import expand_tree_columns_to_available_width


class ArchiveAttachmentBatchMixin:
    """Weapon Placement Batch UI and export coordination."""
    def _open_archive_bulk_attachment_placement_from_selection(self) -> None:
        targets = self._selected_archive_bulk_placement_targets()
        if len(targets) <= 1:
            QMessageBox.information(
                self,
                "Weapon Placement Batch",
                "Select two or more weapon/model/prefab/HKX/socket rows in Archive Browser first.",
            )
            return
        self._open_archive_bulk_attachment_placement_dialog(targets)

    def _open_archive_bulk_attachment_placement_dialog(
        self,
        target_entries: Sequence[ArchiveEntry],
    ) -> None:
        targets: List[ArchiveEntry] = []
        seen_targets: set[Tuple[str, str, int]] = set()
        for entry in target_entries:
            if not self._archive_entry_supports_attachment_placement_workflow(entry):
                continue
            key = self._attachment_package_entry_key(entry)
            if key in seen_targets:
                continue
            seen_targets.add(key)
            targets.append(entry)
        if len(targets) <= 0:
            QMessageBox.information(self, "Weapon Placement Batch", "No placement-capable target rows were selected.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Weapon Placement Batch - {len(targets):,} target(s)")
        dialog.resize(1240, 760)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            "Weapon Placement Batch runs the same per-target placement-copy package plan that the single workflow uses. "
            "Each row is a target to change; choose one placement source for that row, then build one combined mod folder."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        experimental_model_checkbox = QCheckBox("Legacy raw prefab copy for batch (risky)")
        experimental_model_checkbox.setToolTip(
            "Default off. Batch does not yet build the target-only prefab/descriptor patch used by the single workflow. Enable only for old raw prefab-copy behavior."
        )
        experimental_hkx_checkbox = QCheckBox("Replacement-only: copy source HKX/physics for each pair")
        experimental_hkx_checkbox.setToolTip(
            "Advanced replacement-only option. Normal placement keeps target-owned HKX/physics."
        )
        experimental_hkx_checkbox.setEnabled(False)
        option_row = QHBoxLayout()
        option_row.addWidget(experimental_model_checkbox)
        option_row.addWidget(experimental_hkx_checkbox)
        option_row.addStretch(1)
        layout.addLayout(option_row)

        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Target To Change", "Placement Source", "Package Rows", "Status", "Notes"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.header().setStretchLastSection(True)
        tree.header().resizeSection(0, 360)
        tree.header().resizeSection(1, 320)
        tree.header().resizeSection(2, 100)
        tree.header().resizeSection(3, 120)
        layout.addWidget(tree, stretch=1)

        status_label = QLabel("")
        status_label.setObjectName("HintLabel")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        button_row = QHBoxLayout()
        choose_source_button = QPushButton("Choose Source For Selected Target...")
        choose_source_button.setToolTip("Pick the placement source for the selected target row. The selected target remains the file being changed.")
        review_pair_button = QPushButton("Review Selected Pair...")
        review_pair_button.setToolTip("Open the normal single-target comparison for the selected target/source pair.")
        clear_source_button = QPushButton("Clear Source")
        build_button = QPushButton("Build One Mod Folder...")
        close_button = QPushButton("Close")
        button_row.addWidget(choose_source_button)
        button_row.addWidget(review_pair_button)
        button_row.addWidget(clear_source_button)
        button_row.addStretch(1)
        button_row.addWidget(build_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        pair_state: Dict[Tuple[str, str, int], Dict[str, object]] = {}
        items_by_key: Dict[Tuple[str, str, int], QTreeWidgetItem] = {}

        def _target_key(entry: ArchiveEntry) -> Tuple[str, str, int]:
            return self._attachment_package_entry_key(entry)

        def _current_target_item() -> Optional[QTreeWidgetItem]:
            item = tree.currentItem()
            if item is None:
                return None
            target = item.data(0, Qt.ItemDataRole.UserRole)
            return item if isinstance(target, ArchiveEntry) else None

        def _state_for_item(item: Optional[QTreeWidgetItem]) -> Optional[Dict[str, object]]:
            if item is None:
                return None
            target = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(target, ArchiveEntry):
                return None
            return pair_state.get(_target_key(target))

        def _refresh_status() -> None:
            assigned = 0
            ready = 0
            blocked = 0
            for state in pair_state.values():
                if isinstance(state.get("source"), ArchiveEntry):
                    assigned += 1
                rows = state.get("rows")
                if isinstance(rows, tuple) and rows:
                    ready += 1
                elif isinstance(state.get("source"), ArchiveEntry):
                    blocked += 1
            missing = max(0, len(targets) - assigned)
            status_label.setText(
                f"{ready:,} / {len(targets):,} target(s) ready. "
                f"{missing:,} missing source assignment(s), {blocked:,} blocked pair(s). "
                "Build writes one combined loose mod folder using the same package rows as each single placement swap."
            )
            current_state = _state_for_item(_current_target_item())
            has_source = bool(current_state and isinstance(current_state.get("source"), ArchiveEntry))
            review_pair_button.setEnabled(has_source)
            clear_source_button.setEnabled(has_source)
            build_button.setEnabled(ready == len(targets) and len(targets) > 0)

        def _set_item_state(
            target: ArchiveEntry,
            *,
            source: Optional[ArchiveEntry] = None,
            rows: Sequence[dict] = (),
            warnings: Sequence[str] = (),
            status: str = "Needs Source",
            note: str = "",
        ) -> None:
            key = _target_key(target)
            pair_state[key] = {
                "target": target,
                "source": source,
                "rows": tuple(dict(row) for row in rows),
                "warnings": tuple(str(warning) for warning in warnings if str(warning).strip()),
                "status": status,
                "note": note,
            }
            item = items_by_key.get(key)
            if item is None:
                return
            source_text = source.path if isinstance(source, ArchiveEntry) else "-"
            row_count = len(tuple(rows or ()))
            warning_text = "; ".join(tuple(str(warning) for warning in warnings if str(warning).strip())[:3])
            note_text = note or warning_text
            item.setText(1, source_text)
            item.setText(2, f"{row_count:,}" if row_count else "-")
            item.setText(3, status)
            item.setText(4, note_text)
            item.setToolTip(0, target.path)
            item.setToolTip(1, source_text)
            item.setToolTip(4, note_text)
            self._ui_style_status_columns(item, {3: status})
            _refresh_status()

        def _bulk_pair_compatibility_status(warnings: Sequence[str]) -> str:
            for warning in tuple(warnings or ()):
                text = str(warning or "").strip()
                if not text.startswith("Placement compatibility:"):
                    continue
                status_text = text.split(":", 1)[1].split("(", 1)[0].strip()
                if status_text in {"Known compatible", "Cross-category risky", "Unknown"}:
                    return status_text
            return "Ready"

        def _bulk_pair_ready_note(warnings: Sequence[str]) -> str:
            for warning in tuple(warnings or ()):
                text = str(warning or "").strip()
                if text.startswith("Placement compatibility:"):
                    return text
            return "Ready to build into the combined package."

        for target in targets:
            item = QTreeWidgetItem([target.path, "-", "-", "Needs Source", "Choose a placement source for this target."])
            item.setData(0, Qt.ItemDataRole.UserRole, target)
            item.setToolTip(0, target.path)
            tree.addTopLevelItem(item)
            items_by_key[_target_key(target)] = item
            pair_state[_target_key(target)] = {
                "target": target,
                "source": None,
                "rows": (),
                "warnings": (),
                "status": "Needs Source",
                "note": "",
            }
        if tree.topLevelItemCount() > 0:
            tree.setCurrentItem(tree.topLevelItem(0))

        def _choose_source_for_selected() -> None:
            item = _current_target_item()
            if item is None:
                self.set_status_message("Select a target row first.", error=True)
                return
            target = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(target, ArchiveEntry):
                return
            source = self._open_archive_attachment_donor_picker_dialog(dialog, target)
            if not isinstance(source, ArchiveEntry):
                return
            try:
                target_graph, _target_refs = self._archive_asset_family_graph_for_entry(target)
                source_graph, _source_refs = self._archive_asset_family_graph_for_entry(source)
                rows, warnings = self._build_attachment_donor_package_plan(
                    target,
                    source,
                    target_graph,
                    source_graph,
                    legacy_raw_prefab_copy=experimental_model_checkbox.isChecked(),
                    experimental_copy_source_model=False,
                    experimental_copy_source_hkx=experimental_hkx_checkbox.isChecked(),
                )
            except Exception as exc:
                _set_item_state(
                    target,
                    source=source,
                    rows=(),
                    warnings=(str(exc),),
                    status="Blocked",
                    note=f"Could not build package plan: {exc}",
                )
                return
            status = _bulk_pair_compatibility_status(warnings) if rows else "Blocked"
            note = _bulk_pair_ready_note(warnings) if rows else "Batch raw copy is off; use Review Selected Pair for target-only placement package."
            _set_item_state(target, source=source, rows=rows, warnings=warnings, status=status, note=note)

        def _rebuild_all_assigned_pairs() -> None:
            assigned_states = tuple(pair_state.values())
            for state in assigned_states:
                target = state.get("target")
                source = state.get("source")
                if not isinstance(target, ArchiveEntry) or not isinstance(source, ArchiveEntry):
                    continue
                try:
                    target_graph, _target_refs = self._archive_asset_family_graph_for_entry(target)
                    source_graph, _source_refs = self._archive_asset_family_graph_for_entry(source)
                    rows, warnings = self._build_attachment_donor_package_plan(
                        target,
                        source,
                        target_graph,
                        source_graph,
                        legacy_raw_prefab_copy=experimental_model_checkbox.isChecked(),
                        experimental_copy_source_model=False,
                        experimental_copy_source_hkx=experimental_hkx_checkbox.isChecked(),
                    )
                except Exception as exc:
                    _set_item_state(
                        target,
                        source=source,
                        rows=(),
                        warnings=(str(exc),),
                        status="Blocked",
                        note=f"Could not rebuild package plan: {exc}",
                    )
                    continue
                status = _bulk_pair_compatibility_status(warnings) if rows else "Blocked"
                note = _bulk_pair_ready_note(warnings) if rows else "Batch raw copy is off; use Review Selected Pair for target-only placement package."
                _set_item_state(target, source=source, rows=rows, warnings=warnings, status=status, note=note)

        def _refresh_bulk_experimental_options() -> None:
            if not experimental_model_checkbox.isChecked() and experimental_hkx_checkbox.isChecked():
                experimental_hkx_checkbox.setChecked(False)
            experimental_hkx_checkbox.setEnabled(experimental_model_checkbox.isChecked())
            _rebuild_all_assigned_pairs()

        def _clear_selected_source() -> None:
            item = _current_target_item()
            if item is None:
                return
            target = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(target, ArchiveEntry):
                _set_item_state(target, source=None, rows=(), warnings=(), status="Needs Source", note="Choose a placement source for this target.")

        def _review_selected_pair() -> None:
            state = _state_for_item(_current_target_item())
            if not state:
                return
            target = state.get("target")
            source = state.get("source")
            if isinstance(target, ArchiveEntry) and isinstance(source, ArchiveEntry):
                self._open_archive_attachment_placement_diff_dialog(target, source)

        def _build_bulk_package() -> None:
            ready_states = [
                state
                for state in pair_state.values()
                if isinstance(state.get("target"), ArchiveEntry)
                and isinstance(state.get("source"), ArchiveEntry)
                and isinstance(state.get("rows"), tuple)
                and bool(state.get("rows"))
            ]
            if len(ready_states) != len(targets):
                QMessageBox.information(
                    dialog,
                    "Weapon Placement Batch",
                    "Choose a valid placement source for every target before building the combined package.",
                )
                return
            preview_lines = []
            total_rows = 0
            for state in ready_states[:10]:
                target = state.get("target")
                source = state.get("source")
                rows = tuple(state.get("rows") or ())
                total_rows += len(rows)
                if isinstance(target, ArchiveEntry) and isinstance(source, ArchiveEntry):
                    preview_lines.append(f"- {target.basename} <- placement from {source.basename} ({len(rows):,} row(s))")
            if len(ready_states) > 10:
                preview_lines.append(f"- ...and {len(ready_states) - 10:,} more target(s)")
            if QMessageBox.question(
                dialog,
                "Build Weapon Placement Batch Mod Folder",
                (
                    f"Write one mod-ready loose folder for {len(ready_states):,} placement swap target(s)?\n\n"
                    + "\n".join(preview_lines)
                    + "\n\nNo original archives will be modified."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            target_settings = self._collect_archive_mod_ready_export_target(
                browse_title="Choose Weapon Placement Batch Export Root",
                prompt_for_metadata=True,
                dialog_title="Build Weapon Placement Batch Package",
                allow_dmm_texture_structure=False,
            )
            if target_settings is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related, export_options = target_settings
            state_snapshot = tuple(
                {
                    "target": state.get("target"),
                    "source": state.get("source"),
                    "rows": tuple(dict(row) for row in tuple(state.get("rows") or ())),
                }
                for state in ready_states
            )
            bulk_diagnostics = [
                f"Weapon Placement Batch pairs: {len(state_snapshot):,}",
                (
                    "Legacy batch raw prefab copy enabled for each pair."
                    if experimental_model_checkbox.isChecked()
                    else "Batch target-only placement build disabled; use Review Selected Pair for the safe single-target workflow."
                ),
                (
                    "Replacement-only source HKX/physics copied where each pair resolves a target path."
                    if experimental_hkx_checkbox.isChecked()
                    else "Target HKX/physics preserved by default."
                ),
            ]
            for state in ready_states[:12]:
                target = state.get("target")
                source = state.get("source")
                if isinstance(target, ArchiveEntry) and isinstance(source, ArchiveEntry):
                    bulk_diagnostics.append(f"{target.path} <- placement from {source.path}")
                for warning in tuple(state.get("warnings") or ())[:3]:
                    bulk_diagnostics.append(str(warning))
            package_info = self._placement_swap_package_info_with_diagnostics(package_info, bulk_diagnostics)

            def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
                requests_by_path: Dict[str, ArchivePatchRequest] = {}
                source_by_target_path: Dict[str, str] = {}
                for index, state in enumerate(state_snapshot, start=1):
                    target = state.get("target")
                    source = state.get("source")
                    rows = tuple(state.get("rows") or ())
                    if not isinstance(target, ArchiveEntry) or not isinstance(source, ArchiveEntry):
                        continue
                    log(f"Weapon Placement Batch pair {index:,}/{len(state_snapshot):,}: {target.path} <- {source.path}")
                    for row in rows:
                        source_entry = row.get("donor_entry") if isinstance(row, Mapping) else None
                        target_entry = row.get("target_entry") if isinstance(row, Mapping) else None
                        if not isinstance(source_entry, ArchiveEntry) or not isinstance(target_entry, ArchiveEntry):
                            continue
                        target_key = target_entry.path.replace("\\", "/").strip().casefold()
                        source_key = source_entry.path.replace("\\", "/").strip().casefold()
                        if target_key in requests_by_path:
                            if source_by_target_path.get(target_key) != source_key:
                                log(f"Skipping duplicate batch target path already assigned: {target_entry.path}")
                            continue
                        if not experimental_model_checkbox.isChecked() and not self._same_archive_entry(source_entry, target_entry):
                            log(f"Blocked batch donor row outside legacy raw copy mode: {source_entry.path} -> {target_entry.path}")
                            continue
                        payload_data, _decompressed, _note = read_archive_entry_data(source_entry)
                        raw_action = row.get("action") if isinstance(row, Mapping) else ""
                        action = str(raw_action or "Copy source bytes")
                        log(f"{action}: {source_entry.path} -> {target_entry.path}")
                        requests_by_path[target_key] = ArchivePatchRequest(target_entry, payload_data)
                        source_by_target_path[target_key] = source_key
                if not requests_by_path:
                    raise ValueError("No Weapon Placement Batch package payloads could be read.")
                return export_archive_payloads_to_mod_ready_loose(
                    list(requests_by_path.values()),
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if isinstance(result, ArchiveLooseExportResult):
                    QMessageBox.information(
                        dialog,
                        "Weapon Placement Batch Complete",
                        f"Wrote one combined placement swap package:\n{result.package_root}",
                    )
                    self.set_status_message(f"Wrote Weapon Placement Batch package for {len(ready_states):,} target(s).")
                    dialog.accept()
                else:
                    self.set_status_message("Weapon Placement Batch export finished with an unexpected result payload.", error=True)

            self._run_utility_task(
                status_message=f"Building Weapon Placement Batch package for {len(ready_states):,} target(s)...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        tree.currentItemChanged.connect(lambda _current, _previous: _refresh_status())
        tree.itemDoubleClicked.connect(lambda _item, _column: _choose_source_for_selected())
        experimental_model_checkbox.toggled.connect(lambda _checked=False: _refresh_bulk_experimental_options())
        experimental_hkx_checkbox.toggled.connect(lambda _checked=False: _rebuild_all_assigned_pairs())
        choose_source_button.clicked.connect(lambda _checked=False: _choose_source_for_selected())
        clear_source_button.clicked.connect(lambda _checked=False: _clear_selected_source())
        review_pair_button.clicked.connect(lambda _checked=False: _review_selected_pair())
        build_button.clicked.connect(lambda _checked=False: _build_bulk_package())
        close_button.clicked.connect(dialog.reject)
        _refresh_status()
        expand_tree_columns_to_available_width(tree)
        dialog.exec()
