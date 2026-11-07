"""Archive browser character dependency package export flow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox

from cdmw.domain.archives.relationships import CharacterDependencyPlan
from cdmw.services.archive_extraction_service import clear_directory_contents, extract_archive_entries
from cdmw.services.archive_workflow_service import (
    build_character_dependency_plan,
    export_archive_mesh,
    write_character_appearance_bundle_manifest,
)
from cdmw.domain.archives.catalogue import ArchiveLookupKind
from cdmw.domain.archives.character_catalogue import CharacterCatalogScopeRequest, CharacterCatalogScopeResult
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.character_dependency_live import (
    CHARACTER_KEY_MISSING_TEXT,
    MAX_LOOKUPS_PER_ROUND,
    MAX_PLANNING_ENTRIES,
    MAX_PLANNING_ROUNDS,
    CatalogueCall,
    CharacterPlanningRound,
    character_catalogue_asset_key,
    plan_character_dependencies_round,
    planner_indexes,
    with_live_scope_warning,
)
from cdmw.ui.archive_browser.remote_entry_lookup import (
    LiveCatalogueState,
    RemoteLookupOutcome,
    compatibility_entries,
    live_catalogue_state,
    live_catalogue_unavailable_message,
    lookup_requests,
    start_live_catalogue_lookup,
)
from cdmw.ui.archive_browser.remote_window_identity import legacy_identity_key


_TITLE = "Export Character and Related Game Files"


def _not_eligible_message(path: str) -> str:
    return (
        f"No matching appearance descriptor was found for body/model {path}.\n\n"
        "Export Character and Related Game Files is for bodies, faces and other models that a character "
        "appearance uses. The character catalogue has no entry for this file; equipment such as armor is "
        "exported with Export This Model or Asset Family instead."
    )


class ArchiveCharacterDependencyExportMixin:
    """Build and export character dependency file sets from archive selections."""

    def _export_character_dependency_package_live(
        self,
        entry: ArchiveEntry,
        *,
        selected_appearance_path: str = "",
    ) -> None:
        """Plan from the files the worker relates to ``entry``, then export as usual."""

        bridge = getattr(self, "archive_remote_bridge", None)
        session = getattr(bridge, "current_session", None)
        service = getattr(self, "archive_catalogue_service", None)
        if session is None or service is None:
            QMessageBox.warning(self, _TITLE, live_catalogue_unavailable_message(self, _TITLE))
            return
        if not bool(getattr(service, "character_catalog_available", False)):
            QMessageBox.warning(
                self,
                _TITLE,
                "This export needs the character catalogue, which the installed archive helper does not provide. "
                "Install a current CDMW build, then reopen the archives.",
            )
            return
        previous = getattr(self, "_character_dependency_live_call", None)
        if isinstance(previous, CatalogueCall):
            previous.cancel()
        selected_path = str(selected_appearance_path or "").strip()
        generation = int(getattr(getattr(bridge, "controller", None), "generation", 0) or 0)
        key = character_catalogue_asset_key(entry.path)
        self.shell.set_status_message(f"Finding the character files related to {entry.basename}...")

        def scoped(payload: object) -> None:
            self._character_dependency_live_call = None
            if not isinstance(payload, CharacterCatalogScopeResult) or payload.session_id != session.session_id:
                QMessageBox.warning(self, _TITLE, "The archive worker returned an invalid character catalogue result.")
                return
            if payload.truncated:
                QMessageBox.warning(
                    self,
                    _TITLE,
                    f"{entry.path} relates to more than {len(payload.entry_ids):,} archive files, "
                    "more than this export plans at once. Export its appearance from Body & Face Finder instead.",
                )
                return
            self._start_character_dependency_live_lookup(
                entry,
                session.session_id,
                ArchiveLookupKind.ENTRY_IDS,
                payload.entry_ids,
                entries={},
                looked_up_paths=set(),
                looked_up_basenames=set(),
                selected_path=selected_path,
                planning_round=0,
                last_round=None,
            )

        def failed(message: str) -> None:
            self._character_dependency_live_call = None
            if CHARACTER_KEY_MISSING_TEXT.casefold() in message.casefold():
                QMessageBox.information(self, _TITLE, _not_eligible_message(entry.path))
                self.shell.set_status_message(f"No appearance descriptor uses {entry.basename}.")
                return
            QMessageBox.warning(self, _TITLE, f"Could not read the character catalogue:\n{message}")

        call = CatalogueCall(
            service,
            lambda: service.scope_character_catalog(
                CharacterCatalogScopeRequest(session.session_id, key, include_related=True, maximum_results=4096),
                ui_generation=generation,
            ),
            on_result=scoped,
            on_error=failed,
            parent=self,
        )
        self._character_dependency_live_call = call
        call.start()

    def _start_character_dependency_live_lookup(
        self,
        entry: ArchiveEntry,
        session_id: str,
        kind: ArchiveLookupKind,
        values: object,
        *,
        entries: dict,
        looked_up_paths: set,
        looked_up_basenames: set,
        selected_path: str,
        planning_round: int,
        last_round: CharacterPlanningRound | None,
        extra_requests: tuple = (),
    ) -> None:
        requests = (*lookup_requests(session_id, kind, values), *extra_requests)

        def resolved(outcome: RemoteLookupOutcome) -> None:
            before = len(entries)
            for candidate in compatibility_entries(self, outcome.entries):
                entries.setdefault(legacy_identity_key(candidate), candidate)
            entries.setdefault(legacy_identity_key(entry), entry)
            if last_round is not None and len(entries) == before:
                # Nothing new was found for what the planner asked; its plan stands.
                self._finish_character_dependency_live_plan(entry, last_round, entries)
                return
            if len(entries) > MAX_PLANNING_ENTRIES:
                QMessageBox.warning(
                    self,
                    _TITLE,
                    f"The dependency graph for {entry.path} grew past {MAX_PLANNING_ENTRIES:,} archive files; "
                    "the export was stopped instead of writing a partial set.",
                )
                return
            self._run_character_dependency_live_round(
                entry,
                session_id,
                entries=entries,
                looked_up_paths=looked_up_paths,
                looked_up_basenames=looked_up_basenames,
                selected_path=selected_path,
                planning_round=planning_round,
            )

        def failed(message: str) -> None:
            QMessageBox.warning(self, _TITLE, f"Could not resolve the character's archive files:\n{message}")
            self.shell.set_status_message(f"Character dependency lookup failed: {message}", error=True)

        if not requests:
            resolved(RemoteLookupOutcome(session_id, (), False))
            return
        start_live_catalogue_lookup(
            self,
            "_character_dependency_live_lookup",
            requests,
            on_done=resolved,
            on_error=failed,
        )

    def _run_character_dependency_live_round(
        self,
        entry: ArchiveEntry,
        session_id: str,
        *,
        entries: dict,
        looked_up_paths: set,
        looked_up_basenames: set,
        selected_path: str,
        planning_round: int,
    ) -> None:
        bounded_entries = tuple(entries.values())
        body_entry = entries.get(legacy_identity_key(entry), entry)

        def task(on_log: Callable[[str], None], stop_event: object) -> object:
            try:
                on_log(
                    f"Planning character dependencies for {entry.path} "
                    f"(pass {planning_round + 1}, {len(bounded_entries):,} resolved files)..."
                )
                return plan_character_dependencies_round(
                    body_entry,
                    bounded_entries,
                    selected_appearance_path=selected_path,
                    stop_event=stop_event,
                )
            except Exception as exc:
                return {"error": str(exc)}

        def on_complete(result: object) -> None:
            QTimer.singleShot(0, lambda task_result=result: planned(task_result))

        def planned(result: object) -> None:
            if not isinstance(result, CharacterPlanningRound):
                self._handle_character_dependency_package_plan(entry, result)
                return
            new_paths = sorted(result.missing_paths - looked_up_paths)[:MAX_LOOKUPS_PER_ROUND]
            new_basenames = sorted(result.missing_basenames - looked_up_basenames)[:MAX_LOOKUPS_PER_ROUND]
            if planning_round + 1 >= MAX_PLANNING_ROUNDS or not (new_paths or new_basenames):
                self._finish_character_dependency_live_plan(entry, result, entries)
                return
            looked_up_paths.update(new_paths)
            looked_up_basenames.update(new_basenames)
            self._start_character_dependency_live_lookup(
                entry,
                session_id,
                ArchiveLookupKind.EXACT_PATHS,
                new_paths,
                entries=entries,
                looked_up_paths=looked_up_paths,
                looked_up_basenames=looked_up_basenames,
                selected_path=selected_path,
                planning_round=planning_round + 1,
                last_round=result,
                extra_requests=lookup_requests(session_id, ArchiveLookupKind.BASENAMES, new_basenames),
            )

        self.shell._run_utility_task(
            status_message=f"Building character dependency plan for {entry.basename}...",
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _finish_character_dependency_live_plan(
        self,
        entry: ArchiveEntry,
        planning_round: CharacterPlanningRound,
        entries: dict,
    ) -> None:
        path_index, basename_index = planner_indexes(entries.values())
        self._character_dependency_live_indexes = (
            {key: tuple(value) for key, value in path_index.items()},
            {key: tuple(value) for key, value in basename_index.items()},
        )
        self._handle_character_dependency_package_plan(
            entry,
            with_live_scope_warning(planning_round.plan),
            live_catalogue=True,
        )


    def _export_character_dependency_package_for_entry(
        self,
        entry: ArchiveEntry,
        *,
        selected_appearance_path: str = "",
    ) -> None:
        if not self.archive_entries:
            # The live catalogue never fills the legacy list; plan from a bounded,
            # worker-resolved set instead of refusing.
            if live_catalogue_state(self) == LiveCatalogueState.READY:
                self._export_character_dependency_package_live(
                    entry,
                    selected_appearance_path=selected_appearance_path,
                )
                return
            QMessageBox.warning(
                self,
                _TITLE,
                live_catalogue_unavailable_message(self, "Export Character and Related Game Files"),
            )
            return
        archive_entries = tuple(self.archive_entries)
        selected_path = str(selected_appearance_path or "").strip()
        status_message = (
            f"Rebuilding character dependency plan for {entry.basename}..."
            if selected_path
            else f"Building character dependency plan for {entry.basename}..."
        )

        def task(on_log: Callable[[str], None], stop_event: object) -> object:
            try:
                if selected_path:
                    on_log(f"Building character dependency plan for {entry.path} using {selected_path}...")
                else:
                    on_log(f"Building character dependency plan for {entry.path}...")
                return build_character_dependency_plan(
                    entry,
                    archive_entries,
                    selected_appearance_path=selected_path,
                    stop_event=stop_event,
                )
            except Exception as exc:
                return {"error": str(exc)}

        def on_complete(result: object) -> None:
            QTimer.singleShot(
                0,
                lambda current_entry=entry, task_result=result: self._handle_character_dependency_package_plan(
                    current_entry,
                    task_result,
                ),
            )

        self.shell._run_utility_task(
            status_message=status_message,
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _handle_character_dependency_package_plan(
        self,
        entry: ArchiveEntry,
        result: object,
        *,
        live_catalogue: bool = False,
    ) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(
                self,
                "Export Character and Related Game Files",
                f"Could not build dependency plan:\n{result.get('error')}",
            )
            return
        if not isinstance(result, CharacterDependencyPlan):
            QMessageBox.warning(
                self,
                "Export Character and Related Game Files",
                "Could not build dependency plan: unexpected worker result.",
            )
            return
        plan = result
        multiple_match_error = "Multiple matching appearance descriptors were found"
        if plan.blocking_errors and any(multiple_match_error in error for error in plan.blocking_errors):
            choices = list(plan.appearance_paths)
            if not choices:
                QMessageBox.warning(self, "Export Character and Related Game Files", "\n".join(plan.blocking_errors))
                return
            selected, accepted = QInputDialog.getItem(
                self,
                "Select Appearance Descriptor",
                "Multiple appearance descriptors reference this model. Choose the one to export:",
                choices,
                0,
                False,
            )
            if not accepted or not selected:
                return
            self._export_character_dependency_package_for_entry(
                entry,
                selected_appearance_path=str(selected),
            )
            return
        if plan.blocking_errors:
            if live_catalogue and any(
                error.startswith("No matching appearance descriptor") for error in plan.blocking_errors
            ):
                QMessageBox.information(self, _TITLE, _not_eligible_message(entry.path))
                return
            QMessageBox.warning(self, "Export Character and Related Game Files", "\n".join(plan.blocking_errors))
            return
        for warning in plan.warnings:
            self.shell.append_log(f"Character dependency plan: {warning}")
        entries = list(plan.entries)
        if not entries:
            QMessageBox.warning(
                self,
                "Export Character and Related Game Files",
                f"No dependency entries were resolved for {entry.path}.",
            )
            return
        self.shell.append_log(
            f"Character dependency package for {entry.path}: "
            f"{len(entries):,} file(s), appearance={plan.selected_appearance_path or '-'}."
        )
        live_indexes = getattr(self, "_character_dependency_live_indexes", None) if live_catalogue else None
        if live_indexes is not None:
            self._run_character_dependency_package_export(
                entry,
                plan,
                path_index=live_indexes[0],
                basename_index=live_indexes[1],
            )
        else:
            self._run_character_dependency_package_export(entry, plan)

    def _run_character_dependency_package_export(
        self,
        entry: ArchiveEntry,
        plan: CharacterDependencyPlan,
        *,
        path_index: dict | None = None,
        basename_index: dict | None = None,
    ) -> None:
        entries = tuple(plan.entries)
        output_root = self.shell._suggest_archive_extract_root().resolve()
        extract_options = self._prompt_archive_extract_options(
            entries, output_root, include_package_directory=False,
        )
        if extract_options is None:
            self.shell.set_status_message("Character dependency package export cancelled.")
            return
        clear_root, collision_mode = extract_options
        if collision_mode == "rename":
            QMessageBox.warning(
                self,
                "Export Character and Related Game Files",
                "A reusable character package must preserve exact virtual paths. "
                "Run the export again and choose Overwrite Existing or Clear Root.",
            )
            return
        if path_index is None:
            path_index = {
                str(key): tuple(value or ())
                for key, value in dict(getattr(self, "archive_entries_by_normalized_path", {}) or {}).items()
            }
        if basename_index is None:
            basename_index = {
                str(key): tuple(value or ())
                for key, value in dict(getattr(self, "archive_entries_by_basename", {}) or {}).items()
            }

        def task(
            on_log: Callable[[str], None],
            on_progress: Callable[[int, int, str], None],
            stop_event: object,
        ) -> object:
            if clear_root:
                output_root.mkdir(parents=True, exist_ok=True)
                on_log(f"Clearing extract root contents under {output_root}")
                clear_directory_contents(output_root)
            stats = extract_archive_entries(
                entries,
                output_root,
                collision_mode=collision_mode,
                include_package_directory=False,
                on_log=on_log,
                on_progress=on_progress,
                stop_event=stop_event,
            )
            result: dict[str, object] = {
                "output_root": str(output_root),
                "stats": stats,
                "fbx_paths": (),
                "fbx_error": "",
                "manifest_path": "",
                "manifest_error": "",
            }
            if int(stats.get("failed", 0) or 0) > 0:
                result["fbx_error"] = "Blender FBX was skipped because one or more required companion files failed to extract."
                return result
            try:
                export_result = export_archive_mesh(
                    entry,
                    output_root / "cdmw_blender",
                    "fbx",
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                    allow_missing_skeleton=False,
                    build_preview_context=False,
                    on_log=on_log,
                    stop_event=stop_event,
                )
                result["fbx_paths"] = tuple(str(path) for path in export_result.output_paths)
                if export_result.requires_confirmation:
                    result["fbx_error"] = export_result.confirmation_message
            except Exception as exc:
                result["fbx_error"] = str(exc)
            try:
                result["manifest_path"] = str(
                    write_character_appearance_bundle_manifest(
                        output_root,
                        primary_model_path=entry.path,
                        selected_appearance_path=plan.selected_appearance_path,
                        entries=entries,
                        fbx_paths=tuple(result.get("fbx_paths", ()) or ()),
                        stop_event=stop_event,
                    )
                )
            except Exception as exc:
                result["manifest_error"] = str(exc)
            return result

        def on_complete(result: object) -> None:
            if not isinstance(result, dict):
                return
            stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
            extracted = int(stats.get("extracted", 0) or 0)
            failed = int(stats.get("failed", 0) or 0)
            fbx_paths = tuple(result.get("fbx_paths", ()) or ())
            fbx_error = str(result.get("fbx_error", "") or "").strip()
            manifest_path = str(result.get("manifest_path", "") or "").strip()
            manifest_error = str(result.get("manifest_error", "") or "").strip()
            output_root_value = str(result.get("output_root", output_root))
            self.archive_extract_root_edit.setText(output_root_value)
            if fbx_paths and manifest_path:
                self.shell.set_status_message(
                    f"Exported {extracted:,} character dependency file(s) and a self-contained Blender FBX to {output_root_value}."
                )
            elif failed:
                self.shell.set_status_message(
                    f"Character dependency export finished with {failed:,} failed file(s).",
                    error=True,
                )
            else:
                detail = manifest_error or fbx_error or "required output was not published"
                self.shell.set_status_message(
                    f"Exported {extracted:,} character dependency file(s), but the reusable bundle is incomplete: {detail}",
                    error=True,
                )
            self._dashboard_last_result_text = (
                f"Character dependency package: {extracted:,} extracted, {failed:,} failed, "
                f"manifest={'ready' if manifest_path else 'not created'}, "
                f"Blender FBX={'ready' if fbx_paths else 'not created'}. Output: {output_root_value}"
            )
            if fbx_error:
                self.shell.append_log(f"Character dependency Blender FBX: {fbx_error}")
            if manifest_error:
                self.shell.append_log(f"Character dependency manifest: {manifest_error}")
            self.shell._refresh_dashboard()

        self.shell._run_utility_task(
            status_message=f"Exporting character dependency package for {entry.basename}...",
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )

__all__ = ["ArchiveCharacterDependencyExportMixin"]
