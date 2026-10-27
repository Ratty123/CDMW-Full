"""Shell routes for the Drafts & Mods page: open it, find the source, continue."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_archive_results import EDITED_RESULT_NOTE
from cdmw.services.mesh_saved_work_service import (
    SavedWorkLaunch,
    SavedWorkRow,
    prepare_saved_work_launch,
)
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    ArchiveWorkflowDependencyContext,
    archive_workflow_dependency_context,
)
from cdmw.ui.mesh_editor.saved_work_launch import overlay_dependency_context
from cdmw.ui.mesh_editor.saved_work_sources import (
    SavedWorkSourceResolver,
    normalized_archive_path,
)

SOURCE_POLL_INTERVAL_MS = 250
SOURCE_POLL_TIMEOUT_SECONDS = 90.0


class MeshEditorSavedWorkBridgeMixin:
    """Open the Drafts & Mods page and continue a row in Mesh Editor."""

    def _mesh_saved_work_root(self) -> Path:
        # The same rule as MeshEditorTab.mesh_editor_draft_root, which saves them.
        settings_path = Path(str(self.settings.fileName() or "settings.ini")).expanduser()
        return workspace_paths(settings_path.parent)["modify_original_sessions_root"]

    def _mesh_saved_work_resolver(self) -> SavedWorkSourceResolver:
        resolver = getattr(self, "_mesh_saved_work_source_resolver", None)
        if resolver is None:
            resolver = SavedWorkSourceResolver(self.archive, self)
            self._mesh_saved_work_source_resolver = resolver
        return resolver

    def _mesh_saved_work_active_draft(self) -> Path | None:
        container = getattr(self, "mesh_editor_tab", None)
        created = getattr(container, "widget_if_created", None)
        tab = created() if callable(created) else container
        return getattr(tab, "mesh_editor_draft_manifest_path", None) if tab is not None else None

    def _open_mesh_editor_saved_work(self, path_filter: str = "") -> None:
        """Show Drafts & Mods, filtered to one game file when given."""

        container = self.saved_work_tab
        text = str(path_filter or "")

        def show(page) -> None:
            page.set_path_filter(text)
            page.refresh()

        self._activate_tool_widget(container)
        when_created = getattr(container, "when_created", None)
        if callable(when_created):
            when_created(show)
        else:
            show(container)

    def _continue_mesh_saved_work(self, row: object) -> None:
        if not isinstance(row, SavedWorkRow):
            return
        self._cancel_mesh_saved_work_source_wait()
        if row.is_built_mod and row.manifest_path is None and (row.mod_root is None or not row.mod_root.is_dir()):
            self.set_status_message("This mod's folder no longer exists, so it cannot be reopened.", error=True)
            return
        if self._mesh_editor_open_blocked():
            return
        wanted = normalized_archive_path(row.source_archive_path)
        current = self.archive._current_archive_mesh_entry()
        if isinstance(current, ArchiveEntry) and normalized_archive_path(current.path) == wanted:
            context = self._mesh_saved_work_dependencies(current)
            if context is not None:
                self._prepare_mesh_saved_work_launch(row, context)
                return
        self.set_status_message(f"Finding {Path(row.source_archive_path).name} in the game files...")
        self._mesh_saved_work_resolver().resolve(
            [row.source_archive_path],
            lambda sources, target=row: self._reveal_mesh_saved_work_source(target, sources),
        )

    def _mesh_saved_work_dependencies(self, entry: ArchiveEntry) -> ArchiveWorkflowDependencyContext | None:
        try:
            return archive_workflow_dependency_context(self, entry)
        except ArchiveWorkflowDependenciesUnavailable:
            return None

    def _reveal_mesh_saved_work_source(self, row: SavedWorkRow, sources: object) -> None:
        name = Path(row.source_archive_path).name
        if sources is None:
            self.set_status_message(
                "Open Archive Browser and load the game files, then choose Continue Editing again.", error=True,
            )
            return
        wanted = normalized_archive_path(row.source_archive_path)
        entry = dict(sources).get(wanted)
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message(
                f"The game file this was made from is not in the current game files: {row.source_archive_path}",
                error=True,
            )
            return
        bridge = getattr(self.archive, "archive_remote_bridge", None)
        if bridge is None or not bool(getattr(bridge, "displays_v2", False)):
            context = self._mesh_saved_work_dependencies(entry)
            if context is None:
                self.set_status_message(f"Archive Browser could not prepare {name}.", error=True)
                return
            self._prepare_mesh_saved_work_launch(row, context)
            return
        entry_id = self._mesh_saved_work_resolver().entry_ids.get(wanted)
        self._activate_tool_widget(self.archive_browser_tab)
        if entry_id is None or not bridge.apply_entry_id_scope((entry_id,), label=f"Continue editing {name}"):
            self.set_status_message(f"Select {name} in Archive Browser, then choose Continue Editing again.", error=True)
            return
        self._mesh_saved_work_pending = {
            "row": row,
            "path": wanted,
            "deadline": time.monotonic() + SOURCE_POLL_TIMEOUT_SECONDS,
            "preview_requested": False,
        }
        timer = getattr(self, "_mesh_saved_work_source_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(SOURCE_POLL_INTERVAL_MS)
            timer.timeout.connect(self._poll_mesh_saved_work_source)
            self._mesh_saved_work_source_timer = timer
        timer.start()
        self.set_status_message(f"Preparing {name} in Archive Browser before Mesh Editor opens...")

    def _cancel_mesh_saved_work_source_wait(self) -> None:
        self._mesh_saved_work_pending = None
        timer = getattr(self, "_mesh_saved_work_source_timer", None)
        if timer is not None:
            timer.stop()

    def _poll_mesh_saved_work_source(self) -> None:
        pending = getattr(self, "_mesh_saved_work_pending", None)
        if not isinstance(pending, dict) or bool(getattr(self, "_shutting_down", False)):
            self._cancel_mesh_saved_work_source_wait()
            return
        row = pending["row"]
        current = self.archive._current_archive_mesh_entry()
        if isinstance(current, ArchiveEntry) and normalized_archive_path(current.path) == pending["path"]:
            context = self._mesh_saved_work_dependencies(current)
            if context is not None:
                self._cancel_mesh_saved_work_source_wait()
                self._prepare_mesh_saved_work_launch(row, context)
                return
            if not pending["preview_requested"]:
                # Its dependencies are prepared by the preview that selection
                # normally starts; ask once in case automatic preview is off.
                pending["preview_requested"] = True
                preview = getattr(self.archive, "_preview_current_archive_entry", None)
                if callable(preview):
                    preview()
        if time.monotonic() > float(pending["deadline"]):
            self._cancel_mesh_saved_work_source_wait()
            self.set_status_message(
                f"Archive Browser did not finish preparing {Path(row.source_archive_path).name}. "
                "Select it there, then choose Continue Editing again.",
                error=True,
            )

    def _prepare_mesh_saved_work_launch(self, row: SavedWorkRow, context: ArchiveWorkflowDependencyContext) -> None:
        live_entry = context.selected_entry
        root = self._mesh_saved_work_root()
        self._run_utility_task_when_idle(
            status_message=f"Preparing {row.display_name} for Mesh Editor...",
            task=lambda _log: prepare_saved_work_launch(root, row, live_entry, edited_note=EDITED_RESULT_NOTE),
            on_complete=lambda launch, target=context: self._open_mesh_saved_work_launch(launch, target),
            on_error=lambda message: self.set_status_message(f"Continue Editing failed: {message}", error=True),
        )

    def _open_mesh_saved_work_launch(self, launch: object, context: ArchiveWorkflowDependencyContext) -> None:
        if not isinstance(launch, SavedWorkLaunch) or bool(getattr(self, "_shutting_down", False)):
            return
        row = launch.row
        if launch.game_updated:
            answer = QMessageBox.question(
                self,
                "Game File Updated",
                f"The game file {row.source_archive_path} has changed since {row.display_name} was made.\n\n"
                "Continue from the saved copy of the earlier file? A mod you build from it replaces "
                "the updated game file with your edited earlier version.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.set_status_message("Continue Editing was cancelled.")
                return
        dependencies = (
            overlay_dependency_context(context, launch.selected_entry, launch.replacements)
            if launch.replacements
            else context
        )
        self._open_archive_mesh_editor_with_dependencies(
            launch.selected_entry,
            dependencies,
            resume_manifest_path=launch.resume_manifest_path,
            draft_request=launch.draft_request,
        )


__all__ = ["MeshEditorSavedWorkBridgeMixin"]
