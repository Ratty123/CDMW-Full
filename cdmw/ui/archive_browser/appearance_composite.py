"""Archive appearance composite preview actions."""

from __future__ import annotations

import dataclasses
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.services.texture_workflow_service import (
    AppearanceCompositeBuildResult,
    AppearanceCompositeModelOverride,
    AppearanceCompositePreviewPlan,
    build_appearance_composite_model,
    build_appearance_composite_preview_plan,
    find_appearance_composite_candidates,
)
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ModelPreviewData, PreparedModelPreviewData
from cdmw.services.preview_rendering_service import prepare_model_preview


class ArchiveAppearanceCompositeMixin:
    """Archive appearance composite preview actions."""
    @staticmethod
    def _appearance_composite_override_score(component: object, override_model_entry: ArchiveEntry) -> Tuple[int, int, int]:
        override_path = str(getattr(override_model_entry, "path", "") or "").replace("\\", "/").casefold()
        override_stem = PurePosixPath(override_path).stem
        component_name = str(getattr(component, "prefab_name", "") or "").casefold()
        component_paths = " ".join(
            str(getattr(entry, "path", "") or "").replace("\\", "/").casefold()
            for entry in tuple(getattr(component, "resolved_model_entries", ()) or ())
        )
        common_prefix = 0
        for left, right in zip(override_stem, component_name):
            if left != right:
                break
            common_prefix += 1
        slot_score = 0
        for slot in (
            "/9_upperbody/",
            "/10_lowerbody/",
            "/11_hand/",
            "/12_foot/",
            "/13_hel/",
            "/19_cloak/",
            "/18_acc/",
            "/head/",
            "/hair/",
            "/beard/",
            "/nude/",
        ):
            if slot in override_path and slot in component_paths:
                slot_score += 100
        token_score = sum(1 for token in re.split(r"[^a-z0-9]+", override_stem) if len(token) > 1 and token in component_name)
        return slot_score, common_prefix, token_score

    def _prompt_appearance_composite_override_component(
        self,
        plan: AppearanceCompositePreviewPlan,
        override_model_entry: ArchiveEntry,
        *,
        purpose: str = "preview",
    ) -> Optional[int]:
        components = tuple(plan.components or ())
        if not components:
            return None
        dialog = QDialog(self)
        package_mode = str(purpose or "").strip().lower() == "package"
        dialog.setWindowTitle("Choose Target Component" if package_mode else "Choose Component To Replace")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label_text = (
            "Choose the target app XML component whose existing model virtual path will receive the donor model in a loose package. "
            "The target app XML, game archives, skeleton, ragdoll, and part-hide files are not patched.\n"
            if package_mode
            else (
                "Choose the app XML component to temporarily replace with the selected model. "
                "This is a display-only what-if preview; the app XML and archives are not modified.\n"
            )
        )
        label = QLabel(f"{label_text}Selected model: {override_model_entry.path}")
        label.setWordWrap(True)
        layout.addWidget(label)
        component_list = QListWidget()
        component_list.setSelectionMode(QAbstractItemView.SingleSelection)
        best_row = 0
        best_score: Tuple[int, int, int] = (-1, -1, -1)
        for index, component in enumerate(components):
            model_summary = self._appearance_composite_entry_summary(tuple(getattr(component, "resolved_model_entries", ()) or ()), limit=2)
            text = (
                f"{getattr(component, 'section', 'Component')} / {getattr(component, 'prefab_name', '')}"
                f" -> {model_summary or 'currently unresolved'}"
            )
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.UserRole, index)
            component_list.addItem(item)
            score = self._appearance_composite_override_score(component, override_model_entry)
            if score > best_score:
                best_score = score
                best_row = index
        component_list.setCurrentRow(best_row)
        layout.addWidget(component_list, stretch=1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        choose_button = QPushButton("Use Target Component" if package_mode else "Use Override")
        choose_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(choose_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        choose_button.clicked.connect(dialog.accept)
        component_list.itemDoubleClicked.connect(lambda _item: dialog.accept())
        dialog.resize(860, 520)
        if dialog.exec() != QDialog.Accepted:
            return None
        item = component_list.currentItem()
        if item is None:
            return None
        try:
            return int(item.data(Qt.UserRole))
        except Exception:
            return best_row

    def _appearance_composite_component_notes(self, component: object) -> str:
        notes: List[str] = []
        if bool(getattr(component, "preview_flag", False)):
            notes.append("Preview=true")
        scale = float(getattr(component, "scale", 1.0) or 1.0)
        if abs(scale - 1.0) > 0.0001:
            notes.append(f"scale {scale:g}")
        context_entries = tuple(getattr(component, "resolved_context_entries", ()) or ())
        if context_entries:
            notes.append(
                "context: "
                + self._appearance_composite_entry_summary(context_entries, limit=2)
            )
        unresolved = tuple(str(value or "") for value in getattr(component, "unresolved_references", ()) or () if str(value or "").strip())
        if unresolved:
            notes.append("unresolved: " + ", ".join(unresolved[:2]))
        warnings = tuple(str(value or "") for value in getattr(component, "warnings", ()) or () if str(value or "").strip())
        if warnings:
            notes.extend(warnings[:2])
        return " | ".join(notes)

    def _prompt_appearance_composite_component_selection(
        self,
        plan: AppearanceCompositePreviewPlan,
        *,
        override_component_index: Optional[int] = None,
        override_model_entry: Optional[ArchiveEntry] = None,
    ) -> Optional[Tuple[int, ...]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Preview Composite Appearance")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        appearance_path = str(getattr(plan.appearance_entry, "path", "") or "").strip()
        source_path = str(getattr(plan.source_entry, "path", "") or "").strip()
        label_text = (
            f"Appearance XML: {appearance_path}\nSource: {source_path}"
            if appearance_path
            else f"No appearance XML selected. Using selected file evidence only.\nSource: {source_path}"
        )
        if override_model_entry is not None and override_component_index is not None:
            label_text = (
                f"{label_text}\nWhat-if override: component #{override_component_index + 1} "
                f"will use {override_model_entry.path} for this preview only."
            )
        label = QLabel(label_text)
        label.setWordWrap(True)
        layout.addWidget(label)

        component_tree = QTreeWidget()
        component_tree.setColumnCount(5)
        component_tree.setHeaderLabels(["Use", "Section", "Prefab / Evidence", "Models", "Notes"])
        component_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        component_tree.setRootIsDecorated(True)
        component_tree.setAlternatingRowColors(True)
        layout.addWidget(component_tree, stretch=1)

        group_items: Dict[str, QTreeWidgetItem] = {}
        component_items: List[Tuple[QTreeWidgetItem, int]] = []

        def group_for(section: str) -> QTreeWidgetItem:
            key = str(section or "Context/Unsupported")
            if key not in group_items:
                group_item = QTreeWidgetItem(component_tree, ["", key, "", "", ""])
                group_item.setFirstColumnSpanned(True)
                group_item.setExpanded(True)
                group_items[key] = group_item
            return group_items[key]

        for component_index, component in enumerate(tuple(plan.components or ())):
            section = str(getattr(component, "section", "") or "Context/Unsupported")
            prefab_name = str(getattr(component, "prefab_name", "") or "")
            model_entries = tuple(getattr(component, "resolved_model_entries", ()) or ())
            renderable = bool(model_entries)
            notes_text = self._appearance_composite_component_notes(component)
            if override_model_entry is not None and override_component_index == component_index:
                notes_text = (
                    f"What-if model override: {override_model_entry.basename}; "
                    f"{notes_text}" if notes_text else f"What-if model override: {override_model_entry.basename}"
                )
                renderable = True
            item = QTreeWidgetItem(
                group_for(section),
                [
                    "",
                    section,
                    prefab_name,
                    self._appearance_composite_entry_summary(model_entries),
                    notes_text,
                ],
            )
            item.setToolTip(2, prefab_name)
            item.setToolTip(3, "\n".join(str(getattr(entry, "path", "") or "") for entry in model_entries))
            item.setToolTip(4, notes_text)
            item.setData(0, Qt.UserRole, component_index)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            default_checked = bool(getattr(component, "default_selected", False)) or override_component_index == component_index
            item.setCheckState(0, Qt.Checked if default_checked and renderable else Qt.Unchecked)
            if not renderable:
                item.setDisabled(True)
            component_items.append((item, component_index))

        warning_lines: List[str] = [str(value) for value in tuple(plan.warnings or ()) if str(value).strip()]
        for component in tuple(plan.components or ()):
            warning_lines.extend(str(value) for value in tuple(getattr(component, "warnings", ()) or ()) if str(value).strip())
            context_entries = tuple(getattr(component, "resolved_context_entries", ()) or ())
            if context_entries:
                warning_lines.append(
                    f"{getattr(component, 'section', 'Context')} / {getattr(component, 'prefab_name', '')}: "
                    f"context-only entries: {self._appearance_composite_entry_summary(context_entries, limit=4)}"
                )
        warning_lines.append("Display-only preview: no archive or game files are modified.")
        warning_lines.append("Socket-only weapons/helmets use raw-origin fallback here unless a body/socket placement context is selected.")
        warnings_edit = QPlainTextEdit()
        warnings_edit.setReadOnly(True)
        warnings_edit.setMaximumHeight(118)
        warnings_edit.setPlainText("\n".join(dict.fromkeys(warning_lines)))
        layout.addWidget(warnings_edit)

        button_row = QHBoxLayout()
        defaults_button = QPushButton("Select Defaults")
        all_button = QPushButton("Select All Renderable")
        clear_button = QPushButton("Clear")
        button_row.addWidget(defaults_button)
        button_row.addWidget(all_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        preview_button = QPushButton("Preview")
        preview_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(preview_button)
        layout.addLayout(button_row)

        def set_defaults() -> None:
            for item, component_index in component_items:
                component = plan.components[component_index]
                if item.isDisabled():
                    item.setCheckState(0, Qt.Unchecked)
                else:
                    item.setCheckState(
                        0,
                        Qt.Checked
                        if bool(getattr(component, "default_selected", False)) or override_component_index == component_index
                        else Qt.Unchecked,
                    )

        def set_all_renderable() -> None:
            for item, _component_index in component_items:
                item.setCheckState(0, Qt.Unchecked if item.isDisabled() else Qt.Checked)

        def clear_all() -> None:
            for item, _component_index in component_items:
                item.setCheckState(0, Qt.Unchecked)

        def accept_if_valid() -> None:
            selected = [
                component_index
                for item, component_index in component_items
                if not item.isDisabled() and item.checkState(0) == Qt.Checked
            ]
            if not selected:
                QMessageBox.warning(dialog, "No Renderable Components Selected", "Select at least one renderable component to preview.")
                return
            dialog.accept()

        defaults_button.clicked.connect(set_defaults)
        all_button.clicked.connect(set_all_renderable)
        clear_button.clicked.connect(clear_all)
        cancel_button.clicked.connect(dialog.reject)
        preview_button.clicked.connect(accept_if_valid)
        component_tree.expandAll()
        for column in range(component_tree.columnCount()):
            component_tree.resizeColumnToContents(column)
        dialog.resize(1050, 650)
        if dialog.exec() != QDialog.Accepted:
            return None
        return tuple(
            component_index
            for item, component_index in component_items
            if not item.isDisabled() and item.checkState(0) == Qt.Checked
        )

    def _open_current_archive_appearance_composite_preview(self) -> None:
        entry = self._current_archive_entry()
        if entry is None:
            QMessageBox.warning(self, "No Archive File Selected", "Select an .app_xml, .pac/.pam/.pamlod, or prefab file first.")
            return
        appearance_entry, override_model_entry = self._appearance_composite_selected_context(entry)
        self._open_archive_appearance_composite_preview_for_entry(
            appearance_entry,
            override_model_entry=override_model_entry,
        )

    def _open_archive_appearance_composite_preview_for_entry(
        self,
        entry: ArchiveEntry,
        *,
        override_model_entry: Optional[ArchiveEntry] = None,
    ) -> None:
        if not isinstance(entry, ArchiveEntry):
            QMessageBox.warning(self, "No Archive File Selected", "Select an archive file first.")
            return
        if self.worker_thread is not None:
            self.set_status_message("Another background task is still running. Wait for it to finish before starting composite preview.", error=True)
            return
        extension = str(entry.extension or "").lower()
        if extension not in {".app_xml", ".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".prefabdata_xml"}:
            QMessageBox.warning(
                self,
                "Unsupported Composite Source",
                "Composite preview supports .app_xml, .pac/.pam/.pamlod, .prefabdata_xml, .prefab, and .pappt selections.",
            )
            return
        if extension == ".app_xml":
            self._begin_archive_appearance_composite_selection(
                entry,
                (entry,),
                override_model_entry=override_model_entry,
            )
            return

        archive_entries = tuple(self.archive_entries)

        def _task(log: Callable[[str], None]) -> object:
            log(f"Searching appearance XML files that reference {entry.basename}...")
            return find_appearance_composite_candidates(entry, archive_entries)

        def _complete(payload: object) -> None:
            candidates = tuple(payload) if isinstance(payload, tuple) else ()
            self._begin_archive_appearance_composite_selection(
                entry,
                candidates,
                override_model_entry=override_model_entry,
            )

        self._run_utility_task(
            status_message=f"Finding appearance contexts for {entry.basename}...",
            task=_task,
            on_complete=_complete,
            show_archive_progress=True,
        )

    def _begin_archive_appearance_composite_selection(
        self,
        entry: ArchiveEntry,
        candidates: Sequence[ArchiveEntry],
        *,
        override_model_entry: Optional[ArchiveEntry] = None,
    ) -> None:
        selected_appearance = self._select_archive_appearance_candidate(entry, candidates)
        if candidates and selected_appearance is None and str(entry.extension or "").lower() != ".app_xml":
            return
        archive_entries = tuple(self.archive_entries)
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            return
        path_index, basename_index = lookup_indexes
        try:
            plan = build_appearance_composite_preview_plan(
                entry,
                archive_entries,
                appearance_entry=selected_appearance,
                path_index=path_index,
                basename_index=basename_index,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Composite Plan Failed", f"Could not build the composite preview plan:\n{exc}")
            return
        override_component_index: Optional[int] = None
        if override_model_entry is not None:
            override_component_index = self._prompt_appearance_composite_override_component(plan, override_model_entry)
            if override_component_index is None:
                return
        selected_indexes = self._prompt_appearance_composite_component_selection(
            plan,
            override_component_index=override_component_index,
            override_model_entry=override_model_entry,
        )
        if selected_indexes is None:
            return
        model_overrides: Tuple[AppearanceCompositeModelOverride, ...] = ()
        if override_model_entry is not None and override_component_index is not None:
            model_overrides = (
                AppearanceCompositeModelOverride(
                    component_index=override_component_index,
                    model_entries=(override_model_entry,),
                    label="What-if model override",
                ),
            )
        self._start_archive_appearance_composite_build(plan, selected_indexes, model_overrides=model_overrides)

    def _start_archive_appearance_composite_build(
        self,
        plan: AppearanceCompositePreviewPlan,
        selected_indexes: Sequence[int],
        *,
        model_overrides: Sequence[AppearanceCompositeModelOverride] = (),
    ) -> None:
        archive_entries = tuple(self.archive_entries)
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            return
        path_index, basename_index = lookup_indexes
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        preview_settings = self._current_model_preview_render_settings()

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            log("Building read-only composite appearance preview...")
            result = build_appearance_composite_model(
                plan,
                selected_component_indexes=selected_indexes,
                model_overrides=model_overrides,
                texconv_path=texconv_path,
                path_index=path_index,
                basename_index=basename_index,
                stop_event=stop_event,
            )
            prepared_preview_model = None
            if isinstance(getattr(result, "preview_model", None), ModelPreviewData):
                try:
                    log("Preparing composite appearance preview for D3D11...")
                    prepared_model, prepared_preview_model = prepare_model_preview(
                        result.preview_model,
                        render_settings=preview_settings,
                        stop_event=stop_event,
                    )
                    result = dataclasses.replace(result, preview_model=prepared_model)
                except Exception as exc:
                    result = dataclasses.replace(
                        result,
                        warnings=tuple(result.warnings or ()) + (f"D3D11 composite preparation failed: {exc}",),
                    )
            return result, prepared_preview_model

        self._run_utility_task_when_idle(
            status_message="Building composite appearance preview...",
            task=_task,
            on_complete=self._handle_archive_appearance_composite_build_result,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _handle_archive_appearance_composite_build_result(self, payload: object) -> None:
        prepared_preview_model = None
        if (
            isinstance(payload, tuple)
            and len(payload) == 2
            and isinstance(payload[0], AppearanceCompositeBuildResult)
        ):
            prepared_preview_model = payload[1]
            payload = payload[0]
        if not isinstance(payload, AppearanceCompositeBuildResult):
            QMessageBox.warning(self, "Composite Preview Failed", "Composite preview finished with an unexpected result payload.")
            return
        preview_model = payload.preview_model
        warning_text = "\n".join(str(value) for value in tuple(payload.warnings or ()) if str(value).strip())
        if not isinstance(preview_model, ModelPreviewData):
            QMessageBox.warning(
                self,
                "No Composite Geometry",
                warning_text or "No selected appearance component produced renderable model geometry.",
            )
            return
        plan = payload.plan
        source_path = str(getattr(plan.source_entry, "path", "") or "")
        appearance_path = str(getattr(plan.appearance_entry, "path", "") or "")
        selected_components = [
            plan.components[index]
            for index in tuple(payload.selected_component_indexes or ())
            if 0 <= int(index) < len(plan.components)
        ]
        overrides_by_index = {
            int(getattr(override, "component_index", -1)): override
            for override in tuple(getattr(payload, "model_overrides", ()) or ())
            if isinstance(override, AppearanceCompositeModelOverride)
        }
        detail_lines = [
            "Read-only composite appearance preview.",
            "No archive or game files were modified.",
            f"Source: {source_path}",
            f"Appearance XML: {appearance_path or 'none; selected-file evidence only'}",
            "",
            "Selected components:",
        ]
        for component_index, component in [
            (index, plan.components[index])
            for index in tuple(payload.selected_component_indexes or ())
            if 0 <= int(index) < len(plan.components)
        ]:
            override = overrides_by_index.get(int(component_index))
            models = self._appearance_composite_entry_summary(tuple(getattr(component, "resolved_model_entries", ()) or ()), limit=6)
            if override is not None:
                models = self._appearance_composite_entry_summary(tuple(getattr(override, "model_entries", ()) or ()), limit=6)
            scale = float(getattr(component, "scale", 1.0) or 1.0)
            preview_flag = " Preview=true" if bool(getattr(component, "preview_flag", False)) else ""
            override_label = " [what-if override]" if override is not None else ""
            detail_lines.append(
                f"- {getattr(component, 'section', 'Component')} / {getattr(component, 'prefab_name', '')}"
                f"{preview_flag}{override_label} scale={scale:g} -> {models or 'no renderable model'}"
            )
        if warning_text:
            detail_lines.extend(("", "Warnings / context:", warning_text))
        title_source = appearance_path or source_path or "Composite Appearance"
        title_name = Path(title_source.replace("\\", "/")).name
        preview_result = ArchivePreviewResult(
            status="ok",
            title=f"Composite Appearance: {title_name}",
            metadata_summary=(
                f"{len(selected_components):,} component(s), {preview_model.mesh_count:,} mesh(es), "
                f"{preview_model.vertex_count:,} vertices, {preview_model.face_count:,} faces"
            ),
            detail_text="\n".join(detail_lines),
            preview_model=preview_model,
            prepared_preview_model=prepared_preview_model if isinstance(prepared_preview_model, PreparedModelPreviewData) else None,
            model_texture_references=tuple(payload.model_texture_references or ()),
            asset_family_graph=payload.asset_family_graph,
            preferred_view="model",
            warning_badge="Composite Context" if warning_text else "",
            warning_text=warning_text,
        )
        preview_result = self._attach_archive_preview_result_images(preview_result)
        self.current_archive_preview_result = preview_result
        self._show_archive_preview_result(preview_result, use_loose=False)
        self.set_status_message(f"Composite appearance preview ready: {title_name}")
