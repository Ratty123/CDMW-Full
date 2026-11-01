"""Archive Browser action that opens the Prefab Inspector."""

from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.archives.prefab_companions import companion_extensions
from cdmw.models import ArchiveEntry
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.services.independent_prefab_authoring import prepare_prefab_package, write_prefab_package
from cdmw.services.prefab_structure_service import (
    asset_extension_for,
    collect_asset_paths,
    decode_prefab_binary,
    prefab_references,
)
from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog


class ArchivePrefabInspectorActionsMixin:
    """Open a decoded view of a prefab and write retargeted copies out."""

    def _open_current_archive_prefab_inspector(self) -> None:
        entry = self._current_archive_prefab_entry()
        if entry is None:
            self.shell.set_status_message("Select a .prefab archive entry before opening the inspector.", error=True)
            return
        status_message = f"Preparing Prefab Inspector for {entry.basename}..."
        # Said at once: the task may first wait for another one, and the index
        # below takes seconds. A click that changes nothing reads as broken.
        self.shell.set_status_message(status_message)
        # Read on the UI thread; the worker must not touch widgets.
        package_root = str(self.archive_package_root_edit.text() or "").strip()

        def _prepare(log: Callable[[str], None]) -> tuple[bytes, dict[str, tuple[str, ...]]]:
            """Read the prefab and index the archives for the asset kinds it references.

            Built here rather than inside the dialog because the underlying
            catalogue scan takes seconds, and a modal is the wrong place to
            spend them.
            """
            log(f"Reading prefab payload: {entry.path}")
            try:
                data, _decompressed, _note = read_archive_entry_data(entry)
            except Exception as exc:  # noqa: BLE001 - surfaced through the worker error path
                raise RuntimeError(f"Could not read {entry.path}: {exc}") from exc
            if not package_root:
                return data, {}
            try:
                document = decode_prefab_binary(data)
            except Exception:  # noqa: BLE001 - inspector still opens without an index
                return data, {}
            wanted = {
                asset_extension_for(item.text)
                for item in document.all_strings()
                if asset_extension_for(item.text)
            }
            if not wanted:
                return data, {}
            # Companion kinds are never referenced by the prefab, so they have
            # to be added explicitly or their existence can never be checked.
            wanted |= companion_extensions()
            log(f"Indexing archive paths for: {', '.join(sorted(wanted))}")
            return data, collect_asset_paths(package_root, wanted)

        def _open(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 2:
                self.shell.set_status_message(f"Could not read {entry.path}: {result!r}", error=True)
                return
            data, known = result
            self._show_prefab_inspector(entry, data, known if isinstance(known, dict) else {})

        self.shell._run_utility_task_when_idle(
            status_message=status_message,
            task=_prepare,
            on_complete=_open,
            show_archive_progress=True,
        )

    def _show_prefab_inspector(
        self,
        entry: ArchiveEntry,
        data: bytes,
        known_paths: dict[str, tuple[str, ...]],
    ) -> None:
        def _find_users(path: str) -> tuple[str, ...]:
            """Which other prefabs reference ``path``.

            Lives here rather than in the dialog because archive access belongs
            to the browser. A plain substring test rejects almost every entry
            before anything is decoded, which is what makes this affordable.
            """
            found: list[str] = []
            candidates = self.archive_entries_by_extension.get(".prefab", ())
            for candidate in candidates:
                if candidate.path == entry.path:
                    continue
                try:
                    payload, _decompressed, _note = read_archive_entry_data(candidate)
                except Exception:  # noqa: BLE001 - one unreadable entry is not fatal
                    continue
                if prefab_references(payload, path):
                    found.append(candidate.path)
            return tuple(found)

        # The decode and tree build happen in the constructor, before the window
        # can paint; the wait cursor covers that gap on large prefabs.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = PrefabInspectorDialog(
                data,
                title=f"Prefab Inspector - {entry.basename}",
                parent=self,
                known_paths=known_paths,
                find_users=_find_users if self.archive_entries_by_extension.get(".prefab") else None,
            )
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()
        payload = dialog.result_payload
        if payload is None or payload.data == data:
            return
        # Say the unproven part before they install it, not after it fails.
        # Prefab editing has never been confirmed to load in game, and a modder
        # deserves to know which of their mods is the experimental one.
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Export Edited Prefab")
        box.setText(f"{payload.summary}\n\nHow do you want to save the edited prefab?")
        box.setInformativeText(
            "An item package (.cditem) is added on the Mods page. It replaces only the game's own copy "
            "of this prefab and refuses to load after a game update changes that copy.\n\n"
            "A loose folder holds game-relative files for another mod manager.\n\n"
            "Prefab editing is new and has not yet been confirmed to load in game. "
            "Your game files are untouched either way, so if anything misbehaves, "
            "disable the mod in your manager and delete that package - that is the whole of the fix."
        )
        package_button = box.addButton("Item Package (.cditem)...", QMessageBox.ButtonRole.AcceptRole)
        loose_button = box.addButton("Loose Folder...", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(package_button)
        box.exec()
        if box.clickedButton() is package_button:
            self._export_inspected_prefab_package(entry, data, payload.data)
        elif box.clickedButton() is loose_button:
            self._export_inspected_prefab(entry, payload.data, payload.summary)

    def _export_inspected_prefab_package(self, entry: ArchiveEntry, original: bytes, patched: bytes) -> None:
        package_root = str(self.archive_package_root_edit.text() or "").strip()
        if not package_root:
            self.shell.set_status_message("Set the game package root before saving an item package.", error=True)
            return
        stem = Path(PurePosixPath(entry.path.replace("\\", "/")).name).stem or "prefab"
        default = self.shell.settings_file_path.parent / "prefab_packages" / f"{stem}.cditem"
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self, "Save Prefab Package", str(default), "Independent items (*.cditem)"
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != ".cditem":
            destination = destination.with_name(f"{destination.name}.cditem")

        def _task(log: Callable[[str], None], stop_event: threading.Event) -> tuple[Path, tuple[str, ...]]:
            # Reading the game catalogue takes seconds; the package pins the
            # shipped copy and refuses an edit made on another mod's version.
            log(f"Checking {entry.path} against the game's own copy...")
            review = prepare_prefab_package(
                package_root,
                entry.path,
                patched,
                edited_from=original,
                title=destination.stem,
                stop_event=stop_event,
                on_log=log,
            )
            write_prefab_package(review, destination, stop_event=stop_event, on_log=log)
            return destination, review.lines

        def _handle_complete(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 2:
                self.shell.set_status_message("Prefab export finished with an unexpected result payload.", error=True)
                return
            written, lines = result
            QMessageBox.information(
                self,
                "Prefab Package Complete",
                f"Wrote prefab item package:\n{written}\n\n" + "\n".join(lines),
            )
            self.shell.set_status_message(f"Wrote prefab item package: {written}")

        self.shell._run_utility_task_when_idle(
            status_message=f"Building prefab item package for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _export_inspected_prefab(self, entry: ArchiveEntry, patched: bytes, summary: str) -> None:
        export_target = self._collect_archive_mod_ready_export_target(
            browse_title="Choose Prefab Export Root",
            prompt_for_metadata=True,
            dialog_title="Build Prefab Package",
            allow_dmm_texture_structure=False,
            initial_package_title="Prefab Edit",
            initial_package_description=f"CDMW prefab path edit for {entry.path}",
        )
        if export_target is None:
            return
        export_root, package_info, create_no_encrypt_file, _include_related, export_options = export_target

        def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
            # Only the prefab goes in. A retargeted mesh's material and physics
            # are resolved by the engine from the mesh path, so the new mesh's
            # own companions apply and they already ship with the game --
            # bundling copies of them would add mod conflicts and change
            # nothing. A companion that does not exist is a blocking warning at
            # the review step instead.
            log(f"Source prefab: {entry.path}")
            log(summary)
            return export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry, patched)],
                parent_root=export_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchiveLooseExportResult):
                self.shell.set_status_message("Prefab export finished with an unexpected result payload.", error=True)
                return
            QMessageBox.information(
                self,
                "Prefab Package Complete",
                f"Wrote prefab loose package into:\n{result.package_root}",
            )
            self.shell.set_status_message(f"Wrote prefab loose package: {result.package_root}")

        self.shell._run_utility_task_when_idle(
            status_message=f"Building prefab package for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )


__all__ = ["ArchivePrefabInspectorActionsMixin"]
