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
from cdmw.models import ArchiveEntry


class ArchiveCharacterDependencyExportMixin:
    """Build and export character dependency file sets from archive selections."""



    def _export_character_dependency_package_for_entry(
        self,
        entry: ArchiveEntry,
        *,
        selected_appearance_path: str = "",
    ) -> None:
        if not self.archive_entries:
            QMessageBox.warning(self, "Export Character Dependency Package", "Load Archive Browser data first.")
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

        self._run_utility_task(
            status_message=status_message,
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _handle_character_dependency_package_plan(self, entry: ArchiveEntry, result: object) -> None:
        if isinstance(result, dict) and result.get("error"):
            QMessageBox.warning(
                self,
                "Export Character Dependency Package",
                f"Could not build dependency plan:\n{result.get('error')}",
            )
            return
        if not isinstance(result, CharacterDependencyPlan):
            QMessageBox.warning(
                self,
                "Export Character Dependency Package",
                "Could not build dependency plan: unexpected worker result.",
            )
            return
        plan = result
        multiple_match_error = "Multiple matching appearance descriptors were found"
        if plan.blocking_errors and any(multiple_match_error in error for error in plan.blocking_errors):
            choices = list(plan.appearance_paths)
            if not choices:
                QMessageBox.warning(self, "Export Character Dependency Package", "\n".join(plan.blocking_errors))
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
            QMessageBox.warning(self, "Export Character Dependency Package", "\n".join(plan.blocking_errors))
            return
        entries = list(plan.entries)
        if not entries:
            QMessageBox.warning(
                self,
                "Export Character Dependency Package",
                f"No dependency entries were resolved for {entry.path}.",
            )
            return
        self.append_log(
            f"Character dependency package for {entry.path}: "
            f"{len(entries):,} file(s), appearance={plan.selected_appearance_path or '-'}."
        )
        self._run_character_dependency_package_export(entry, plan)

    def _run_character_dependency_package_export(
        self,
        entry: ArchiveEntry,
        plan: CharacterDependencyPlan,
    ) -> None:
        entries = tuple(plan.entries)
        output_root = self._suggest_archive_extract_root().resolve()
        extract_options = self._prompt_archive_extract_options(entries, output_root)
        if extract_options is None:
            self.set_status_message("Character dependency package export cancelled.")
            return
        clear_root, collision_mode = extract_options
        if collision_mode == "rename":
            QMessageBox.warning(
                self,
                "Export Character Dependency Package",
                "A reusable character package must preserve exact virtual paths. "
                "Run the export again and choose Overwrite Existing or Clear Root.",
            )
            return
        path_index = {
            str(key): tuple(value or ())
            for key, value in dict(getattr(self, "archive_entries_by_normalized_path", {}) or {}).items()
        }
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
                self.set_status_message(
                    f"Exported {extracted:,} character dependency file(s) and a self-contained Blender FBX to {output_root_value}."
                )
            elif failed:
                self.set_status_message(
                    f"Character dependency export finished with {failed:,} failed file(s).",
                    error=True,
                )
            else:
                detail = manifest_error or fbx_error or "required output was not published"
                self.set_status_message(
                    f"Exported {extracted:,} character dependency file(s), but the reusable bundle is incomplete: {detail}",
                    error=True,
                )
            self._dashboard_last_result_text = (
                f"Character dependency package: {extracted:,} extracted, {failed:,} failed, "
                f"manifest={'ready' if manifest_path else 'not created'}, "
                f"Blender FBX={'ready' if fbx_paths else 'not created'}. Output: {output_root_value}"
            )
            if fbx_error:
                self.append_log(f"Character dependency Blender FBX: {fbx_error}")
            if manifest_error:
                self.append_log(f"Character dependency manifest: {manifest_error}")
            self._refresh_dashboard()

        self._run_utility_task(
            status_message=f"Exporting character dependency package for {entry.basename}...",
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )

__all__ = ["ArchiveCharacterDependencyExportMixin"]
