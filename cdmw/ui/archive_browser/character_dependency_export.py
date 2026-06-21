"""Archive browser character dependency package export flow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox

from cdmw.core.archive_relationships import CharacterDependencyPlan, build_character_dependency_plan
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

        def task(on_log: Callable[[str], None]) -> object:
            try:
                if selected_path:
                    on_log(f"Building character dependency plan for {entry.path} using {selected_path}...")
                else:
                    on_log(f"Building character dependency plan for {entry.path}...")
                return build_character_dependency_plan(
                    entry,
                    archive_entries,
                    selected_appearance_path=selected_path,
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
        self._run_archive_extract(
            entries,
            allow_original_dds_root=True,
            description=f"Exporting character dependency package for {entry.basename}...",
        )

__all__ = ["ArchiveCharacterDependencyExportMixin"]
