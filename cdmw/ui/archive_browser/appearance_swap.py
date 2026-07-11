"""Archive appearance armor swap package actions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from cdmw.services.texture_workflow_service import (
    AppearanceCompositeModelOverride,
    AppearanceCompositePreviewPlan,
    AppearanceSinglePacSwapPlan,
    build_appearance_single_pac_swap_package_plan,
)
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.ui.shell.request_task_controller import request_task_controller_for_guard
from cdmw.workers.appearance_workers import (
    AppearanceCompositePlanRequest,
    AppearanceCompositePlanResult,
    AppearanceExactMatchRequest,
    AppearanceExactMatchResult,
    AppearanceSwapPlanRequest,
    AppearanceSwapPlanResult,
    run_appearance_composite_plan,
    run_appearance_exact_match,
    run_appearance_swap_plan,
)


class ArchiveAppearanceSwapMixin:
    """Archive appearance armor swap package actions."""
    def _open_current_archive_appearance_swap(self) -> None:
        entry = self._current_archive_entry()
        if entry is None:
            selected_entries = self._selected_archive_entries()
            entry = selected_entries[0] if selected_entries else None
        if not isinstance(entry, ArchiveEntry):
            QMessageBox.warning(self, "No Archive File Selected", "Select one target body .app_xml and one donor .pac/.pam/.pamlod model first.")
            return
        self._open_archive_appearance_swap_for_entry(entry)

    def _open_archive_appearance_swap_for_entry(self, entry: ArchiveEntry) -> None:
        if self.worker_thread is not None:
            self.set_status_message("Another background task is still running. Wait for it to finish before starting appearance armor swap.", error=True)
            return
        if str(entry.extension or "").lower() not in {".app_xml", ".pac", ".pam", ".pamlod"}:
            QMessageBox.warning(
                self,
                "Unsupported Appearance Armor Swap Source",
                "Appearance Armor Swap requires one target body .app_xml and one donor .pac/.pam/.pamlod model.",
            )
            return
        target_app_entry, donor_model_entry, reason = self._appearance_swap_selected_context(entry)
        if reason and donor_model_entry is None:
            QMessageBox.warning(self, "Appearance Armor Swap", reason)
            return
        if isinstance(target_app_entry, ArchiveEntry) and isinstance(donor_model_entry, ArchiveEntry):
            self._begin_archive_appearance_swap_review(target_app_entry, donor_model_entry)
            return
        if isinstance(donor_model_entry, ArchiveEntry) and target_app_entry is None:
            def _complete(payload: object) -> None:
                candidates = payload.candidates if isinstance(payload, AppearanceExactMatchResult) else ()
                if not candidates:
                    QMessageBox.information(
                        self,
                        "Choose Body Appearance Context",
                        "No exact app XML match was found for this donor model. Select the target body .app_xml together with the donor model instead.",
                    )
                    return
                selected_app = self._select_archive_appearance_candidate(donor_model_entry, candidates)
                if selected_app is not None:
                    self._begin_archive_appearance_swap_review(selected_app, donor_model_entry)

            extension_index = getattr(self, "archive_entries_by_extension", {}) or {}
            app_entries = tuple(extension_index.get(".app_xml", ()) or ())
            if not app_entries and getattr(self, "archive_entries", ()):
                ensure_index = getattr(self, "_ensure_archive_extension_index_ready", None)
                if callable(ensure_index):
                    ensure_index()
                self.set_status_message("Archive extension index is warming; retry appearance swap when indexing finishes.")
                return
            controller = request_task_controller_for_guard(
                self,
                self,
                attribute="_appearance_swap_task_controller",
                worker_label="appearance_swap",
            )
            controller.start(
                AppearanceExactMatchRequest(donor_model_entry, app_entries),
                run_appearance_exact_match,
                status_message=f"Finding exact body appearance contexts for {donor_model_entry.basename}...",
                on_complete=_complete,
                on_error=lambda message: QMessageBox.warning(self, "Appearance Armor Swap", message),
            )
            return
        QMessageBox.warning(self, "Appearance Armor Swap", reason or "Select one target body .app_xml and one donor model.")

    def _begin_archive_appearance_swap_review(self, target_app_entry: ArchiveEntry, donor_model_entry: ArchiveEntry) -> None:
        archive_entries = tuple(self.archive_entries)
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            return
        path_index, basename_index = lookup_indexes
        controller = request_task_controller_for_guard(
            self,
            self,
            attribute="_appearance_swap_task_controller",
            worker_label="appearance_swap",
        )

        def _composite_ready(payload: object) -> None:
            if not isinstance(payload, AppearanceCompositePlanResult):
                QMessageBox.warning(self, "Appearance Armor Swap", "Appearance planner returned an unexpected result.")
                return
            composite_plan = payload.plan
            component_index = self._prompt_appearance_composite_override_component(
                composite_plan,
                donor_model_entry,
                purpose="package",
            )
            if component_index is None:
                return
            component = composite_plan.components[component_index] if 0 <= component_index < len(composite_plan.components) else None
            model_candidates = tuple(
                entry
                for entry in tuple(getattr(component, "resolved_model_entries", ()) or ())
                if str(getattr(entry, "extension", "") or "").lower() in {".pac", ".pam", ".pamlod"}
            )
            target_model_entry: Optional[ArchiveEntry] = None
            if len(model_candidates) > 1:
                target_model_entry = self._prompt_appearance_swap_target_model(component, model_candidates)
                if target_model_entry is None:
                    return

            def _swap_ready(swap_payload: object) -> None:
                if not isinstance(swap_payload, AppearanceSwapPlanResult):
                    QMessageBox.warning(self, "Appearance Armor Swap", "Swap planner returned an unexpected result.")
                    return
                self._open_archive_appearance_swap_review_dialog(
                    composite_plan,
                    swap_payload.plan,
                    target_model_entry=target_model_entry,
                )

            controller.start(
                AppearanceSwapPlanRequest(
                    target_app_entry,
                    donor_model_entry,
                    archive_entries,
                    component_index,
                    target_model_entry,
                    False,
                    path_index,
                    basename_index,
                ),
                run_appearance_swap_plan,
                status_message=f"Building appearance swap plan for {donor_model_entry.basename}...",
                on_complete=_swap_ready,
                on_error=lambda message: QMessageBox.warning(self, "Appearance Armor Swap", message),
            )

        controller.start(
            AppearanceCompositePlanRequest(
                target_app_entry,
                donor_model_entry,
                archive_entries,
                path_index,
                basename_index,
            ),
            run_appearance_composite_plan,
            status_message=f"Building appearance context for {target_app_entry.basename}...",
            on_complete=_composite_ready,
            on_error=lambda message: QMessageBox.warning(self, "Appearance Armor Swap", message),
        )

    def _prompt_appearance_swap_target_model(
        self,
        component: object,
        candidates: Sequence[ArchiveEntry],
    ) -> Optional[ArchiveEntry]:
        candidate_entries = tuple(entry for entry in candidates if isinstance(entry, ArchiveEntry))
        if not candidate_entries:
            return None
        if len(candidate_entries) == 1:
            return candidate_entries[0]
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose Target Model Path")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label = QLabel(
            "The selected target component resolves multiple model paths. Choose exactly one virtual model path for single-PAC swap output.\n"
            f"Component: {getattr(component, 'section', 'Component')} / {getattr(component, 'prefab_name', '')}"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        model_list = QListWidget()
        model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        for index, candidate in enumerate(candidate_entries):
            item = QListWidgetItem(candidate.path)
            item.setToolTip(candidate.path)
            item.setData(Qt.UserRole, index)
            model_list.addItem(item)
        model_list.setCurrentRow(0)
        layout.addWidget(model_list, stretch=1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        choose_button = QPushButton("Use Target Model")
        choose_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(choose_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        choose_button.clicked.connect(dialog.accept)
        model_list.itemDoubleClicked.connect(lambda _item: dialog.accept())
        dialog.resize(900, 420)
        if dialog.exec() != QDialog.Accepted:
            return None
        item = model_list.currentItem()
        if item is None:
            return None
        try:
            return candidate_entries[int(item.data(Qt.UserRole))]
        except Exception:
            return candidate_entries[0]

    def _appearance_swap_plan_review_text(self, plan: AppearanceSinglePacSwapPlan) -> str:
        component = plan.target_component
        component_label = (
            f"{getattr(component, 'section', 'Component')} / {getattr(component, 'prefab_name', '')}"
            if component is not None
            else "none selected"
        )
        texture_count = len(tuple(plan.donor_texture_entries or ()))
        missing_count = len(tuple(plan.donor_texture_missing_paths or ()))
        lines = [
            "Single-PAC Appearance Armor Swap",
            "",
            f"Target body appearance context: {plan.target_app_entry.path}",
            f"Target component: {component_label}",
            f"Target model path: {getattr(plan.target_model_entry, 'path', '') or 'unresolved'}",
            f"Donor model path: {plan.donor_model_entry.path}",
            f"Target material sidecar path: {plan.target_sidecar_path or 'derived path unavailable'}",
            f"Donor material sidecar: {getattr(plan.donor_sidecar_entry, 'path', '') or 'unresolved'}",
            f"Included donor texture count: {texture_count:,}",
            "",
            f"Slot compatibility: target {plan.target_slot or 'unknown'} / donor {plan.donor_slot or 'unknown'} / {'match' if plan.slot_match else 'not proven'}",
            f"Body family compatibility: target {plan.target_body_family or 'unknown'} / donor {plan.donor_body_family or 'unknown'} / {'match' if plan.body_family_match else 'not proven'}",
            "",
            "Package writes:",
            "- donor PAC/PAM/PAMLOD bytes -> target component model virtual path",
            "- donor material sidecar bytes -> target component sidecar virtual path when resolved",
            "- donor sidecar-referenced DDS bytes -> original donor texture virtual paths",
            "",
            "Not written: target .app_xml, prefabdata, skeleton, ragdoll, part-hide files, or game archives.",
        ]
        if plan.blocking_reasons:
            lines.extend(("", "Build disabled:", *[f"- {reason}" for reason in plan.blocking_reasons]))
        if plan.warnings:
            lines.extend(("", "Warnings:", *[f"- {warning}" for warning in plan.warnings]))
        if missing_count:
            lines.extend(("", "Missing donor textures:", *[f"- {path}" for path in tuple(plan.donor_texture_missing_paths)[:12]]))
        return "\n".join(lines)

    def _open_archive_appearance_swap_review_dialog(
        self,
        composite_plan: AppearanceCompositePreviewPlan,
        swap_plan: AppearanceSinglePacSwapPlan,
        *,
        target_model_entry: Optional[ArchiveEntry] = None,
    ) -> None:
        archive_entries = tuple(self.archive_entries)
        lookup_indexes = self._archive_lookup_indexes_snapshot()
        if lookup_indexes is None:
            return
        path_index, basename_index = lookup_indexes
        dialog = QDialog(self)
        dialog.setWindowTitle("Appearance Armor Swap Review")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        review_edit = QPlainTextEdit()
        review_edit.setReadOnly(True)
        review_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(review_edit, stretch=1)

        experimental_checkbox = QCheckBox("Allow experimental mismatched body/slot package")
        experimental_checkbox.setToolTip(
            "Enables loose package output when the donor and target body family or armor slot do not match. Preview is still allowed without this."
        )
        layout.addWidget(experimental_checkbox)

        button_row = QHBoxLayout()
        preview_button = QPushButton("Preview What-If Donor")
        build_button = QPushButton("Build Loose Package")
        cancel_button = QPushButton("Cancel")
        button_row.addWidget(preview_button)
        button_row.addStretch(1)
        button_row.addWidget(build_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        plan_holder: Dict[str, AppearanceSinglePacSwapPlan] = {"plan": swap_plan}
        review_controller = request_task_controller_for_guard(
            self,
            dialog,
            attribute="_appearance_review_task_controller",
            worker_label="appearance_review",
        )

        def _apply_plan(refreshed: AppearanceSinglePacSwapPlan) -> None:
            plan_holder["plan"] = refreshed
            review_edit.setPlainText(self._appearance_swap_plan_review_text(refreshed))
            build_button.setEnabled(not bool(refreshed.blocking_reasons))

        def _refresh_plan() -> None:
            experimental_checkbox.setEnabled(False)
            build_button.setEnabled(False)

            def _complete(payload: object) -> None:
                if isinstance(payload, AppearanceSwapPlanResult):
                    _apply_plan(payload.plan)
                else:
                    review_edit.setPlainText("Appearance planner returned an unexpected result.")
                    build_button.setEnabled(False)

            started = review_controller.start(
                AppearanceSwapPlanRequest(
                    swap_plan.target_app_entry,
                    swap_plan.donor_model_entry,
                    archive_entries,
                    swap_plan.target_component_index,
                    target_model_entry,
                    experimental_checkbox.isChecked(),
                    path_index,
                    basename_index,
                ),
                run_appearance_swap_plan,
                status_message="Refreshing appearance swap compatibility...",
                on_complete=_complete,
                on_error=lambda message: review_edit.setPlainText(f"Could not refresh appearance swap plan:\n{message}"),
                on_idle=lambda: experimental_checkbox.setEnabled(True),
            )
            if not started:
                experimental_checkbox.setEnabled(True)

        def _preview_swap() -> None:
            current_plan = plan_holder["plan"]
            component_index = int(current_plan.target_component_index)
            if component_index < 0 or component_index >= len(composite_plan.components):
                QMessageBox.warning(dialog, "Preview What-If Donor", "No valid target component was selected for preview.")
                return
            selected_indexes = set(index for index, component in enumerate(composite_plan.components) if bool(getattr(component, "default_selected", False)))
            selected_indexes.add(component_index)
            dialog.accept()
            self._start_archive_appearance_composite_build(
                composite_plan,
                tuple(sorted(selected_indexes)),
                model_overrides=(
                    AppearanceCompositeModelOverride(
                        component_index=component_index,
                        model_entries=(current_plan.donor_model_entry,),
                        label="What-if donor",
                    ),
                ),
            )

        def _build_swap() -> None:
            current_plan = plan_holder["plan"]
            if current_plan.blocking_reasons:
                QMessageBox.warning(dialog, "Build Loose Package", "\n".join(current_plan.blocking_reasons))
                return
            export_target = self._collect_archive_mod_ready_export_target(
                browse_title="Select Appearance Armor Swap Export Root",
                prompt_for_metadata=True,
                dialog_title="Build Appearance Armor Swap Loose Package",
                allow_dmm_texture_structure=False,
                parent=dialog,
            )
            if export_target is None:
                return
            dialog.accept()
            self._start_archive_appearance_swap_package_build(current_plan, export_target)

        experimental_checkbox.toggled.connect(lambda _checked=False: _refresh_plan())
        preview_button.clicked.connect(lambda _checked=False: _preview_swap())
        build_button.clicked.connect(lambda _checked=False: _build_swap())
        cancel_button.clicked.connect(dialog.reject)
        _apply_plan(swap_plan)
        dialog.resize(980, 680)
        dialog.exec()

    def _start_archive_appearance_swap_package_build(
        self,
        swap_plan: AppearanceSinglePacSwapPlan,
        export_target: Tuple[Path, ModPackageInfo, bool, bool, ModPackageExportOptions],
    ) -> None:
        parent_root, package_info, create_no_encrypt_file, _include_related_files, export_options = export_target

        def _task(log: Callable[[str], None]) -> object:
            log("Building single-PAC appearance armor swap package plan...")
            package_plan = build_appearance_single_pac_swap_package_plan(swap_plan)
            if package_plan.blocking_reasons:
                raise ValueError("\n".join(package_plan.blocking_reasons))
            target_path = getattr(swap_plan.target_model_entry, "path", "") or "<unresolved>"
            log(f"Mapping donor model {swap_plan.donor_model_entry.path} -> {target_path}")
            log(
                f"Including {len(package_plan.extra_payloads):,} supplemental donor sidecar/texture payload(s). "
                "Target app XML, prefabdata, skeleton, ragdoll, and part-hide files are unchanged."
            )
            return export_archive_payloads_to_mod_ready_loose(
                package_plan.requests,
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                extra_payloads_to_include=package_plan.extra_payloads,
                on_log=log,
            )

        self._run_utility_task_when_idle(
            status_message=f"Writing appearance armor swap package for {swap_plan.donor_model_entry.basename}...",
            task=_task,
            on_complete=self._handle_archive_appearance_swap_package_result,
            show_archive_progress=True,
        )

    def _handle_archive_appearance_swap_package_result(self, payload: object) -> None:
        if not isinstance(payload, ArchiveLooseExportResult):
            self.set_status_message("Appearance armor swap export finished with an unexpected result payload.", error=True)
            return
        QMessageBox.information(
            self,
            "Appearance Armor Swap Export Complete",
            f"Wrote appearance armor swap loose package into:\n{payload.package_root}",
        )
        self.set_status_message(f"Wrote appearance armor swap loose package: {payload.package_root}")
