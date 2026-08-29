"""Shell orchestration for the read-only Replace from Archive workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox, QProgressDialog

from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.archives.replace_from_archive import (
    ReplaceFromArchivePlan,
    ReplaceFromArchiveRequest,
)
from cdmw.models import ArchiveEntry
from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.services.replace_from_archive_service import (
    build_replace_from_archive_plan,
    export_replace_from_archive_plan,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
    merge_archive_workflow_dependency_contexts,
)
from cdmw.ui.mesh_editor.replace_from_archive_dialog import (
    ReplaceFromArchivePickerDialog,
    ReplaceFromArchiveReviewDialog,
    replacement_package_title,
)
from cdmw.ui.shell.close_controller import register_transient_worker_controller


class ReplaceFromArchiveFlowController(QObject):
    """Keep request identity and dialog/worker lifetime out of the shell bridge."""

    def __init__(self, owner: object) -> None:
        super().__init__(owner)  # type: ignore[arg-type]
        self._owner = owner
        self._generation = 0
        self._progress: QProgressDialog | None = None
        self._active_picker: ReplaceFromArchivePickerDialog | None = None
        self._retired_pickers: list[ReplaceFromArchivePickerDialog] = []
        register_transient_worker_controller(owner, self)

    def start(
        self, target_entry: ArchiveEntry, *, show_edit_notice: bool = True
    ) -> None:
        owner = self._owner
        if not isinstance(target_entry, ArchiveEntry):
            owner.set_status_message(
                "Mesh Editor has no valid archive-backed target mesh.", error=True
            )
            return
        service = getattr(owner, "archive_catalogue_service", None)
        session = getattr(service, "current_session", None)
        if service is None or session is None:
            owner.set_status_message(
                "Replace from Archive requires the loaded standalone archive catalogue.",
                error=True,
            )
            return
        background_active = getattr(owner, "_background_task_active", None)
        if callable(background_active) and background_active():
            owner.set_status_message(
                "Wait for the current background task before starting Replace from Archive.",
                error=True,
            )
            return
        try:
            target_dependencies = archive_workflow_dependency_context(
                owner, target_entry
            )
        except ArchiveWorkflowDependenciesUnavailable as exc:
            owner.set_status_message(str(exc), error=True)
            return
        target_entry = target_dependencies.selected_entry

        if show_edit_notice and self._active_session_has_edits():
            QMessageBox.information(
                owner,
                "Current Mesh Edits Stay Separate",
                "The current Mesh Editor session contains edits. Replace from Archive builds a separate package "
                "from exact archive payloads, so those edits are not included. The open session is not changed or discarded.",
            )

        picker = ReplaceFromArchivePickerDialog(
            service,
            session,
            target_entry=target_entry,
            target_dependencies=target_dependencies,
            parent=owner,
        )
        self._active_picker = picker
        result = picker.exec()
        target_preview = picker.target_preview_image
        source_preview = picker.source_preview_image
        source_entry = picker.selected_entry
        source_dependencies = picker.selected_dependencies
        character_mode = picker.character_mode
        self._active_picker = None
        self._retain_picker_until_idle(picker)
        if (
            result != QDialog.Accepted
            or not isinstance(source_entry, ArchiveEntry)
            or source_dependencies is None
        ):
            return
        try:
            dependencies = merge_archive_workflow_dependency_contexts(
                target_entry,
                target_dependencies,
                source_dependencies,
            )
        except ArchiveWorkflowDependenciesUnavailable as exc:
            owner.set_status_message(str(exc), error=True)
            return
        prepared_target = dependencies.entry_matching(target_entry)
        prepared_source = dependencies.entry_matching(source_entry)
        if prepared_target is None or prepared_source is None:
            owner.set_status_message(
                "The prepared target or source archive entry expired.", error=True
            )
            return

        self._generation += 1
        generation = self._generation
        request = ReplaceFromArchiveRequest(
            prepared_target,
            prepared_source,
            character_mode,
        )

        def _plan_task(
            _log: Callable[[str], None], stop_event: object
        ) -> ReplaceFromArchivePlan:
            if generation != self._generation:
                raise RuntimeError("Replace from Archive planning cancelled.")
            return build_replace_from_archive_plan(
                request,
                entries=dependencies.entries,
                entries_by_normalized_path=dependencies.entries_by_normalized_path,
                entries_by_basename=dependencies.entries_by_basename,
                stop_event=stop_event,  # type: ignore[arg-type]
            )

        def _plan_ready(payload: object) -> None:
            self._close_progress()
            if generation != self._generation or not isinstance(
                payload, ReplaceFromArchivePlan
            ):
                return
            current = getattr(
                getattr(owner, "mesh_editor_tab", None),
                "_current_target_entry",
                lambda: None,
            )()
            if (
                not isinstance(current, ArchiveEntry)
                or current.identity != target_entry.identity
            ):
                return
            review = ReplaceFromArchiveReviewDialog(
                payload,
                target_preview=target_preview,
                source_preview=source_preview,
                parent=owner,
            )
            review.exec()
            if review.choice == "back":
                QTimer.singleShot(
                    0, lambda: self.start(target_entry, show_edit_notice=False)
                )
                return
            if review.choice != "build" or not payload.can_build:
                return
            self._start_export(payload, generation)

        def _plan_failed(message: str) -> None:
            self._close_progress()
            if generation != self._generation or self._expected_cancel(message):
                return
            QMessageBox.warning(owner, "Replace from Archive", message)

        owner._run_utility_task_when_idle(
            status_message="Preparing Replace from Archive plan...",
            task=_plan_task,
            on_complete=_plan_ready,
            on_error=_plan_failed,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )
        self._show_progress(
            "Preparing source-to-target replacement plan...", generation
        )

    def _start_export(self, plan: ReplaceFromArchivePlan, generation: int) -> None:
        owner = self._owner
        target = owner._collect_archive_mod_ready_export_target(
            browse_title="Choose Replace from Archive output folder",
            prompt_for_metadata=True,
            initial_include_related_files=False,
            show_include_related_files_option=False,
            dialog_title="Build Replace from Archive Mod",
            initial_package_title=replacement_package_title(plan.request.target_entry),
            initial_package_description=(
                "Exact archive-to-archive replacement. Source game textures are referenced in place and are not duplicated."
            ),
            parent=owner,
        )
        if target is None or generation != self._generation:
            return
        (
            export_root,
            package_info,
            create_no_encrypt,
            _include_related,
            export_options,
        ) = target

        def _export_task(
            log: Callable[[str], None],
            stop_event: object,
        ) -> ArchiveLooseExportResult:
            if generation != self._generation:
                raise RuntimeError("Replace from Archive export cancelled.")
            return export_replace_from_archive_plan(
                plan,
                parent_root=export_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt,
                on_log=log,
                stop_event=stop_event,  # type: ignore[arg-type]
            )

        def _export_ready(payload: object) -> None:
            self._close_progress()
            if generation != self._generation or not isinstance(
                payload, ArchiveLooseExportResult
            ):
                return
            roots = tuple(payload.package_roots or (payload.package_root,))
            owner.set_status_message(f"Replace from Archive mod built at {roots[0]}.")
            recorder = getattr(owner, "_record_runtime_event", None)
            if callable(recorder):
                recorder(
                    "replace_from_archive_built",
                    target=plan.request.target_entry.path,
                    source=plan.request.source_entry.path,
                    package_roots=[str(path) for path in roots],
                    warning_count=len(plan.warnings),
                )
            QMessageBox.information(
                owner,
                "Replace from Archive Complete",
                "The loose replacement mod was validated and published atomically.\n\n"
                + "\n".join(str(path) for path in roots),
            )

        def _export_failed(message: str) -> None:
            self._close_progress()
            if generation != self._generation or self._expected_cancel(message):
                return
            QMessageBox.warning(owner, "Replace from Archive Export", message)

        owner._run_utility_task_when_idle(
            status_message="Building Replace from Archive loose mod...",
            task=_export_task,
            on_complete=_export_ready,
            on_error=_export_failed,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )
        self._show_progress(
            "Building and validating the loose replacement mod...", generation
        )

    def _active_session_has_edits(self) -> bool:
        controller = getattr(
            getattr(self._owner, "mesh_editor_tab", None), "standalone_controller", None
        )
        try:
            view = controller.session_view() if controller is not None else None
            return bool(
                int(getattr(view, "revision", 0) or 0) > 0
                or int(getattr(view, "undo_count", 0) or 0) > 0
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
        pickers = tuple(
            picker
            for picker in (self._active_picker, *self._retired_pickers)
            if isinstance(picker, ReplaceFromArchivePickerDialog)
        )
        return tuple(
            (f"replace_from_archive_{index}_{name}", thread, worker)
            for index, picker in enumerate(pickers)
            for name, thread, worker in picker.iter_shutdown_workers()
        )

    def request_shutdown(self) -> None:
        self._generation += 1
        self._close_progress()
        pickers = tuple(
            picker
            for picker in (self._active_picker, *self._retired_pickers)
            if isinstance(picker, ReplaceFromArchivePickerDialog)
        )
        for picker in pickers:
            picker.request_shutdown()

    def _show_progress(self, label: str, generation: int) -> None:
        self._close_progress()
        progress = QProgressDialog(label, "Cancel", 0, 0, self._owner)
        progress.setWindowTitle("Replace from Archive")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(lambda: self._cancel_generation(generation))
        self._progress = progress
        progress.show()

    def _close_progress(self) -> None:
        progress = self._progress
        self._progress = None
        if progress is not None:
            progress.hide()
            progress.deleteLater()

    def _cancel_generation(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._generation += 1
        worker = getattr(self._owner, "utility_worker", None)
        stop = getattr(worker, "stop", None)
        if callable(stop):
            stop()
        self._close_progress()
        self._owner.set_status_message("Replace from Archive cancelled.")

    def _retain_picker_until_idle(self, picker: ReplaceFromArchivePickerDialog) -> None:
        if not picker.has_live_preview_workers:
            picker.deleteLater()
            return
        self._retired_pickers.append(picker)

        def _release() -> None:
            if picker.has_live_preview_workers:
                return
            try:
                self._retired_pickers.remove(picker)
            except ValueError:
                pass
            picker.deleteLater()

        picker.preview_workers_idle.connect(_release)

    @staticmethod
    def _expected_cancel(message: str) -> bool:
        text = str(message or "")
        return is_expected_cancellation_message(text) or "cancel" in text.casefold()


__all__ = ["ReplaceFromArchiveFlowController"]
