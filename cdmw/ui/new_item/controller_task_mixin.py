"""Snapshot, plan, output, worker, and shutdown orchestration for New Item Studio."""
from __future__ import annotations

import copy
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.services.archive_workflow_service import archive_name_search_text_match, parse_archive_search_query
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.rules import ValidationIssue, has_errors
from cdmw.domain.new_item.spec import IconSource, ModelSource, NewItemSpec
from cdmw.models import ArchiveEntry
from cdmw.ui.new_item.blender_setting import blender_for_fbx
from cdmw.ui.new_item.model_import import (
    ModelImportSource,
    ModelPlacement,
    bake_mesh,
    build_placed_import,
    fbx_needing_blender,
    fbx_needs_blender_message,
    fitted_placement,
    load_model_import_source,
    mesh_bounds,
    mesh_centroid,
    prepare_model_import_mesh_edit,
)
from cdmw.services.effect_catalogue import EffectCatalogue
from cdmw.services.new_item_baseline import baseline_facts, baseline_lines
from cdmw.services.new_item_materials import glow_preview_mesh
from cdmw.services.new_item_planning import NewItemPlan, NewItemPlanError
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot, NewItemSnapshotError
from cdmw.ui.new_item.effect_workspace_controller import NewItemEffectWorkspaceControllerMixin
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, glow_choice, spec_from_draft, stat_grid_for, status_label, with_template
from cdmw.workers.effect_catalogue_worker import EffectCatalogueIndexLane
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.new_item_workers import export_task, install_overlay_task, install_task, overlay_migration_task, overlay_removal_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker


_PLAN_TASK = plan_task


def plan_task(*args, **kwargs):
    module = sys.modules.get("cdmw.ui.new_item.controller")
    target = getattr(module, "plan_task", _PLAN_TASK) if module is not None else _PLAN_TASK
    return target(*args, **kwargs)


class NewItemTaskControllerMixin:
    # ------------------------------------------------------------------ tasks

    def start_snapshot(
        self,
        entries: Iterable[ArchiveEntry],
        *,
        package_root: Optional[Path] = None,
        entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        entries_by_extension: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    ) -> bool:
        """Read the tables from `entries`, or, with none, list the archives under
        `package_root` first (the shell's catalogue backend leaves the legacy list empty)."""

        frozen = tuple(entries)
        if not frozen and package_root is None:
            self.snapshot_failed.emit("The archive list is empty; scan the archives first.")
            return False
        task = snapshot_task(
            frozen,
            service=self.service,
            read_entry=self._read_entry,
            package_root=package_root,
            entries_by_normalized_path=entries_by_normalized_path,
            entries_by_basename=entries_by_basename,
            entries_by_extension=entries_by_extension,
        )

        def done(result: object) -> None:
            if isinstance(result, NewItemSnapshot):
                self.snapshot = result
                self.invalidate_plan()
                # a different install can have different bodies and rigs
                self._character_references.clear()
                self._held_character = ()
                self._material_parts = ()
                self._effect_target_compatibility_cache.clear()
                self.snapshot_ready.emit()
            else:
                self.snapshot_failed.emit("The snapshot finished with an unexpected result.")

        return self._run("snapshot", task, done, self.snapshot_failed.emit)

    # ------------------------------------------------------------------ issued identities

    _ISSUED_SETTING = "ui/new_item_issued_identities"

    def _settings(self):
        from PySide6.QtCore import QSettings

        return QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")

    def persist_issued_identities(self) -> None:
        """Keep the identities this studio hands out in the user's settings, and take up
        the ones it kept before. The app calls this; tests leave it off."""

        self._persist_identities = True
        self._load_issued_identities()

    def _load_issued_identities(self) -> None:
        import json

        try:
            raw = str(self._settings().value(self._ISSUED_SETTING, "") or "")
            for item in (json.loads(raw) if raw else []):
                key = int(item.get("key", 0) or 0)
                stem = str(item.get("stem", "") or "")
                if key:
                    self.issued_keys.add(key)
                if stem:
                    self.issued_stems.add(stem)
        except Exception:  # noqa: BLE001 - unreadable settings cost nothing here
            pass

    def remember_issued_identity(self, item_key: int, stem: str = "") -> None:
        """Record an identity a plan handed out, so the next item takes another one."""

        import json

        key = int(item_key or 0)
        if key:
            self.issued_keys.add(key)
        if stem:
            self.issued_stems.add(str(stem))
        if not self._persist_identities:
            return
        try:
            payload = [{"key": value, "stem": ""} for value in sorted(self.issued_keys)[-200:]]
            payload += [{"key": 0, "stem": value} for value in sorted(self.issued_stems)[-200:]]
            self._settings().setValue(self._ISSUED_SETTING, json.dumps(payload))
        except Exception:  # noqa: BLE001 - remembering is best effort; this session's set still holds
            pass

    def set_mod_base(self, folder: Optional[Path]) -> str:
        """Plan the next item on the tables in `folder` rather than on the archives.

        Folder contents are inspected later by the planning worker; this UI-thread call
        only records the selected directory.
        """

        chosen = Path(folder) if folder and Path(folder).is_dir() else None
        if chosen != self.mod_base_folder:
            self.invalidate_plan()
        self.mod_base_folder = chosen
        return f"{chosen.name} already holds a mod and is selected as the base." if chosen is not None else ""

    def start_plan(self) -> bool:
        self.invalidate_plan()
        revision = self._draft_revision
        if self.snapshot is None:
            self.plan_failed.emit("Read the archives first.", ())
            return False
        try:
            spec = self.current_spec()
        except ValueError as exc:
            self.plan_failed.emit(str(exc), ())
            return False
        # Cheap validation stays immediate. Reading an existing mod and resolving an
        # icon folder happen in the planning worker.
        issues = self.service.validate(spec, self.snapshot)
        if has_errors(issues):
            self.plan_failed.emit("; ".join(issue.message for issue in issues if issue.is_error), issues)
            return False
        icon_source: Optional[Path] = None
        if spec.icon is IconSource.GENERATED:
            text = str(self.draft.icon_source_path or "").strip()
            if not text:
                self.plan_failed.emit("Choose an image (or a folder of images) to generate the icon from, or keep the template's icon.", ())
                return False
            icon_source = Path(text)
            if not icon_source.exists():
                self.plan_failed.emit(f"The icon source {icon_source} does not exist.", ())
                return False
        task = plan_task(
            spec, self.snapshot, service=self.service, model=self.model_result, scene=self.model_scene,
            icon_source_path=icon_source, reserved_keys=tuple(self.issued_keys), reserved_stems=tuple(self.issued_stems),
            mod_base_folder=self.mod_base_folder, read_entry=self._read_entry,
        )

        def done(result: object) -> None:
            if revision != self._draft_revision:
                return
            if isinstance(result, NewItemPlan):
                self.plan = result
                self._plan_revision = revision
                self.remember_issued_identity(result.spec.item_key, str(result.spec.stem or ""))
                self.plan_ready.emit(result)
            else:
                self.plan_failed.emit("The plan finished with an unexpected result.", ())

        def failed(message: str) -> None:
            if revision == self._draft_revision:
                shown = message
                prefix = "The mod folder could not be read as a base: "
                if message.startswith(prefix):
                    shown = f"The mod folder could not be read as a base: {message.removeprefix(prefix)}"
                elif icon_source is not None and icon_source.is_dir() and message.startswith("No image in "):
                    shown = f"No image in {icon_source} matched the new item closely enough; pick a file instead."
                self.plan_failed.emit(shown, ())

        return self._run("plan", task, done, failed)

    def start_export(self, package_root: Path, manager: str) -> bool:
        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = export_task(self.plan, Path(package_root), service=self.service, manager=manager)
        return self._run("export", task, self.export_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_install(self, mutation_service) -> bool:
        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = install_task(self.plan, service=self.service, mutation_service=mutation_service, confirmed=True)
        return self._run("install", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_install_overlay(self, mutation_service) -> bool:
        """Install the plan as its own archive directory instead of into the shipped ones."""

        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = install_overlay_task(self.plan, service=self.service, mutation_service=mutation_service, confirmed=True)
        return self._run("install", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_overlay_migration(self, mutation_service, package_root) -> bool:
        """Move what the shipped archives already carry into the overlay, off the UI thread."""

        task = overlay_migration_task(package_root, mutation_service=mutation_service)
        return self._run("overlay", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_overlay_removal(self, mutation_service, package_root) -> bool:
        """Unmount the overlay and delete it, off the UI thread."""

        task = overlay_removal_task(package_root, mutation_service=mutation_service)
        return self._run("overlay", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def _run(
        self,
        lane: str,
        task,
        on_done: Callable[[object], None],
        on_error: Callable[[str], None],
        *,
        task_accepts_progress: bool = False,
    ) -> bool:
        if self._shutdown_requested:
            return False
        if self.busy:
            self.status_message.emit(f"Still busy with the previous step ({self._lane}); wait for it to finish.", True)
            return False
        if self._synchronous:
            try:
                if task_accepts_progress:
                    result = task(
                        self.log_message.emit,
                        lambda current, total, detail: self.operation_progress.emit(
                            lane, int(current), int(total), str(detail or "")
                        ),
                        threading.Event(),
                    )
                else:
                    result = task(self.log_message.emit, threading.Event())
            except (NewItemPlanError, NewItemSnapshotError, NewItemInstallRefused, ValueError, RuntimeError, OSError) as exc:
                on_error(str(exc))
                return True
            on_done(result)
            return True
        worker = UtilityWorker(
            task,
            task_accepts_progress=task_accepts_progress,
            task_accepts_cancel=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker, self._lane = thread, worker, lane
        self._on_done, self._on_error = on_done, on_error
        self.busy_changed.emit(True)
        worker.log_message.connect(self.log_message.emit)
        worker.progress_changed.connect(self._task_progress)
        # Bound methods of this QObject, not closures: a plain function or lambda
        # connected to a worker's signal runs on the worker's own thread, so the panels'
        # slots (and everything they touch in Qt) ran off the UI thread for the whole of
        # an install. Connecting the controller's own methods gives a queued call back
        # onto the thread the controller lives on.
        worker.completed.connect(self._task_completed)
        worker.error.connect(self._task_failed)
        worker.finished.connect(self._worker_finished, Qt.DirectConnection)
        thread.finished.connect(self._task_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()
        return True

    def _task_progress(self, current: int, total: int, detail: str) -> None:
        if (
            self._shutdown_requested
            or not self._lane
            or self._cancel_requested_lane == self._lane
        ):
            return
        self.operation_progress.emit(self._lane, int(current), int(total), str(detail or ""))

    def cancel_operation(self, lane: str = "") -> bool:
        """Request cooperative cancellation for the current matching operation."""

        expected = str(lane or "")
        if self._worker is None or (expected and expected != self._lane):
            return False
        self._worker.stop()
        self._cancel_requested_lane = self._lane
        self.operation_progress.emit(self._lane, 0, 0, "Cancelling…")
        return True

    def _task_completed(self, result: object) -> None:
        if self._shutdown_requested:
            if isinstance(result, ModelImportSource):
                self._cleanup_model_source(result)
            else:
                cleanup = getattr(result, "cleanup", None)
                if callable(cleanup):
                    cleanup()
            return
        if self._cancel_requested_lane == self._lane:
            if isinstance(result, ModelImportSource):
                self._cleanup_model_source(result)
            else:
                cleanup = getattr(result, "cleanup", None)
                if callable(cleanup):
                    cleanup()
            self.status_message.emit("Operation cancelled.", False)
            return
        handler = self._on_done
        if handler is not None:
            handler(result)

    def _task_failed(self, message: object) -> None:
        if self._shutdown_requested:
            return
        text = str(message)
        if self._cancel_requested_lane == self._lane:
            self.status_message.emit("Operation cancelled.", False)
            return
        handler = self._on_error
        if handler is not None:
            handler(text)

    def _worker_finished(self) -> None:
        """Run on the worker thread: return its QObject, then stop that event loop."""

        worker = self._worker
        if worker is not None and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _task_finished(self) -> None:
        """Run on the controller thread only after the native worker thread ended."""

        thread, worker = self._thread, self._worker
        if thread is not None and not thread.wait(0):
            QTimer.singleShot(0, self._task_finished)
            return
        self._thread = None
        self._worker = None
        self._cancel_requested_lane = ""
        self._lane = ""
        self._on_done = None
        self._on_error = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        if self._shutdown_requested:
            self._cleanup_model_source(self.model_import)
            self.model_import = None
        self.busy_changed.emit(False)

    # ------------------------------------------------------------------ shutdown

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        workers = []
        if self._thread is not None:
            workers.append((self._lane or "task", self._thread, self._worker))
        workers.extend(self._model_cleanup_lane.iter_shutdown_workers())
        workers.extend(self._effect_lane.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
            thread.quit()
        source, self.model_import = self.model_import, None
        self._cleanup_model_source(source)
        self._effect_lane.request_shutdown()

    def shutdown(self) -> None:
        self.request_shutdown()
