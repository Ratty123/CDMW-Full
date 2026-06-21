"""Archive Browser extraction workflow helpers."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox

from cdmw.core.archive import (
    clear_directory_contents,
    count_existing_archive_targets,
    directory_has_contents,
    extract_archive_entries,
)
from cdmw.models import ArchiveEntry


class ArchiveExtractionMixin:
    """Archive extraction prompts, worker dispatch, and workflow handoff."""

    def extract_related_archive_set_from_paths(self, raw_paths: object, description: str) -> None:
        if not isinstance(raw_paths, list):
            self.set_status_message("No related archive paths were supplied for extraction.", error=True)
            return
        lookup = {
            entry.path.replace("\\", "/").lower(): entry
            for entry in self.archive_entries
        }
        entries: List[ArchiveEntry] = []
        seen_paths: set[str] = set()
        for raw_path in raw_paths:
            if not isinstance(raw_path, str):
                continue
            normalized = raw_path.strip().replace("\\", "/").lower()
            if not normalized or normalized in seen_paths:
                continue
            entry = lookup.get(normalized)
            if entry is None:
                continue
            seen_paths.add(normalized)
            entries.append(entry)
        if not entries:
            self.set_status_message("No matching archive entries were found for the related-set extraction.", error=True)
            return
        self._run_archive_extract(
            entries,
            allow_original_dds_root=False,
            description=description,
        )


    def _prompt_archive_extract_options(
        self,
        entries: Sequence[ArchiveEntry],
        output_root: Path,
    ) -> Optional[Tuple[bool, str]]:
        summary_box = QMessageBox(self)
        summary_box.setWindowTitle("Archive Extraction Target")
        summary_box.setIcon(QMessageBox.Information)
        summary_box.setText(f"{len(entries):,} archive file(s) will be extracted to:")
        summary_box.setInformativeText(
            f"{output_root}\n\n"
            "If this folder does not exist yet, the app will create it.\n"
            "If files already exist there, you will be asked whether to clear the folder, "
            "overwrite matching files, or keep both by renaming the new copies."
        )
        continue_button = summary_box.addButton("Continue", QMessageBox.AcceptRole)
        summary_cancel_button = summary_box.addButton(QMessageBox.Cancel)
        summary_box.setDefaultButton(continue_button)
        summary_box.exec()
        if summary_box.clickedButton() == summary_cancel_button:
            return None

        if not self._preference_bool("confirm_archive_extract_cleanup", True):
            return False, "overwrite"

        clear_root = False
        collision_mode = "overwrite"

        if output_root.exists() and directory_has_contents(output_root):
            clear_box = QMessageBox(self)
            clear_box.setWindowTitle("Target Folder Already Contains Files")
            clear_box.setIcon(QMessageBox.Question)
            clear_box.setText("The selected extraction target already contains files or folders.")
            clear_box.setInformativeText(
                f"{output_root}\n\nChoose whether to clear it first or keep the existing files."
            )
            clear_button = clear_box.addButton("Clear Root", QMessageBox.AcceptRole)
            keep_button = clear_box.addButton("Keep Existing", QMessageBox.ActionRole)
            cancel_button = clear_box.addButton(QMessageBox.Cancel)
            clear_box.setDefaultButton(keep_button)
            clear_box.exec()
            clicked = clear_box.clickedButton()
            if clicked == cancel_button:
                return None
            if clicked == clear_button:
                clear_root = True
                collision_mode = "overwrite"
            else:
                collisions = count_existing_archive_targets(entries, output_root)
                if collisions > 0:
                    collision_box = QMessageBox(self)
                    collision_box.setWindowTitle("Existing Files Found")
                    collision_box.setIcon(QMessageBox.Question)
                    collision_box.setText(f"{collisions:,} extracted path(s) already exist in the target.")
                    collision_box.setInformativeText(
                        f"Target folder:\n{output_root}\n\n"
                        "Choose whether to overwrite existing files or keep both by renaming the newly extracted copies."
                    )
                    overwrite_button = collision_box.addButton("Overwrite Existing", QMessageBox.AcceptRole)
                    rename_button = collision_box.addButton("Keep Both (Rename New Files)", QMessageBox.ActionRole)
                    collision_cancel_button = collision_box.addButton(QMessageBox.Cancel)
                    collision_box.setDefaultButton(overwrite_button)
                    collision_box.exec()
                    clicked_collision = collision_box.clickedButton()
                    if clicked_collision == collision_cancel_button:
                        return None
                    if clicked_collision == rename_button:
                        collision_mode = "rename"
                    else:
                        collision_mode = "overwrite"

        return clear_root, collision_mode

    def _prompt_archive_extract_target(
        self,
        entries: Sequence[ArchiveEntry],
        archive_extract_root: Path,
        *,
        prefer_original_dds_root: bool = False,
    ) -> Optional[Tuple[Path, bool]]:
        if not entries or any(entry.extension != ".dds" for entry in entries):
            return archive_extract_root, True

        original_root_text = self.original_dds_edit.text().strip()
        if not original_root_text:
            return archive_extract_root, True

        try:
            original_dds_root = Path(original_root_text).expanduser().resolve()
        except OSError:
            return archive_extract_root, True

        if original_dds_root == archive_extract_root:
            return archive_extract_root, True

        target_box = QMessageBox(self)
        target_box.setWindowTitle("DDS Extraction Target")
        target_box.setIcon(QMessageBox.Question)
        target_box.setText("Choose where to extract these DDS files.")
        target_box.setInformativeText(
            "Archive extract root:\n"
            f"{archive_extract_root}\n\n"
            "Original DDS root:\n"
            f"{original_dds_root}\n\n"
            "Use Original DDS root if you want the extracted DDS files to feed the workflow directly."
        )
        extract_root_button = target_box.addButton("Use Extract Root", QMessageBox.AcceptRole)
        original_root_button = target_box.addButton("Use Original DDS Root", QMessageBox.ActionRole)
        cancel_button = target_box.addButton(QMessageBox.Cancel)
        target_box.setDefaultButton(original_root_button if prefer_original_dds_root else extract_root_button)
        target_box.exec()

        clicked = target_box.clickedButton()
        if clicked == cancel_button:
            return None
        if clicked == original_root_button:
            return original_dds_root, False
        return archive_extract_root, True

    def _run_archive_extract(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        set_original_dds_root: bool = False,
        allow_original_dds_root: bool = False,
        description: str,
    ) -> None:
        if not entries:
            self.set_status_message("No archive entries selected for extraction.", error=True)
            return

        output_root = self._suggest_archive_extract_root().resolve()
        update_archive_extract_root = True
        if allow_original_dds_root:
            target_result = self._prompt_archive_extract_target(
                entries,
                output_root,
                prefer_original_dds_root=set_original_dds_root,
            )
            if target_result is None:
                self.set_status_message("Archive extraction cancelled.")
                return
            output_root, update_archive_extract_root = target_result
        extract_options = self._prompt_archive_extract_options(entries, output_root)
        if extract_options is None:
            self.set_status_message("Archive extraction cancelled.")
            return
        clear_root, collision_mode = extract_options

        def task(
            on_log: Callable[[str], None],
            on_progress: Callable[[int, int, str], None],
        ) -> Dict[str, object]:
            if clear_root:
                output_root.mkdir(parents=True, exist_ok=True)
                on_log(f"Clearing extract root contents under {output_root}")
                on_progress(0, 0, f"Clearing extract root contents under {output_root}...")
                clear_directory_contents(output_root)
            on_log(f"Extracting {len(entries):,} archive entries to {output_root}")
            stats = extract_archive_entries(
                entries,
                output_root,
                collision_mode=collision_mode,
                on_log=on_log,
                on_progress=on_progress,
            )
            return {
                "output_root": str(output_root),
                "stats": stats,
                "collision_mode": collision_mode,
                "cleared": clear_root,
            }

        def on_complete(result: object) -> None:
            if not isinstance(result, dict):
                return
            output_root_value = str(result.get("output_root", output_root))
            stats = result.get("stats", {})
            if isinstance(stats, dict):
                extracted = int(stats.get("extracted", 0))
                failed = int(stats.get("failed", 0))
                decompressed = int(stats.get("decompressed", 0))
                renamed = int(stats.get("renamed", 0))
            else:
                extracted = failed = decompressed = renamed = 0
            if update_archive_extract_root:
                self.archive_extract_root_edit.setText(output_root_value)
            if set_original_dds_root:
                self.original_dds_edit.setText(output_root_value)
                self._set_pending_archive_workflow_extract(
                    entries=entries,
                    output_root=Path(output_root_value).expanduser(),
                )
                self._pending_texture_editor_workflow_export = None
                workflow_filters: List[str] = []
                for entry in entries:
                    if not isinstance(entry, ArchiveEntry):
                        continue
                    package_root = entry.pamt_path.parent.name.strip() or "package"
                    relative_path = PurePosixPath(package_root, *PurePosixPath(entry.path.replace("\\", "/")).parts).as_posix()
                    workflow_filters.append(relative_path)
                if workflow_filters and len(workflow_filters) <= 256:
                    self.filters_edit.setPlainText("\n".join(workflow_filters))
                self._activate_tool_widget(self.workflow_tab)
                if workflow_filters and len(workflow_filters) == 1:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value}, set Original DDS root, and focused the workflow filter on {workflow_filters[0]}."
                    )
                elif workflow_filters and len(workflow_filters) <= 256:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value}, set Original DDS root, and focused the workflow filter on the extracted DDS set."
                    )
                else:
                    self.set_status_message(
                        f"Extracted {extracted} archive DDS file(s) to {output_root_value} and set Original DDS root."
                    )
            else:
                self.set_status_message(f"Extracted {extracted} archive file(s) to {output_root_value}.")
            self._dashboard_last_result_text = (
                "Archive extraction complete: "
                f"{extracted:,} extracted, {decompressed:,} decompressed, {renamed:,} renamed, {failed:,} failed. "
                f"Output: {output_root_value}"
            )
            self.append_log(
                f"Archive extraction summary: extracted={extracted}, decompressed={decompressed}, renamed={renamed}, failed={failed}."
            )
            self._refresh_dashboard()

        self._run_utility_task(
            status_message=description,
            task=task,
            on_complete=on_complete,
            show_archive_progress=True,
            task_accepts_progress=True,
        )

    def extract_selected_archive_entries(self) -> None:
        self._run_archive_extract(
            self._selected_archive_entries(),
            allow_original_dds_root=True,
            description="Extracting selected archive entries...",
        )

    def extract_filtered_archive_entries(self) -> None:
        self._run_archive_extract(
            self.archive_filtered_entries,
            allow_original_dds_root=True,
            description="Extracting filtered archive entries...",
        )

    def extract_filtered_archive_dds_to_workflow(self) -> None:
        dds_entries, used_selection = self._archive_entries_for_workflow_extract()
        if used_selection and not dds_entries:
            self.set_status_message(
                "The current archive selection does not include any DDS files. Select DDS files or clear the selection to use the filtered view.",
                error=True,
            )
            return
        self._run_archive_extract(
            dds_entries,
            set_original_dds_root=True,
            allow_original_dds_root=True,
            description=(
                "Extracting selected DDS archive entries to workflow root..."
                if used_selection
                else "Extracting filtered DDS archive entries to workflow root..."
            ),
        )
