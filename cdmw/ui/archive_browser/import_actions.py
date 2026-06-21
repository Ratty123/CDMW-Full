"""Archive Browser import action shims."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from cdmw.core.archive_modding import apply_hkx_editable_geometry_json, apply_hkx_editable_geometry_xml


class ArchiveImportActionsMixin:
    """Small UI action shims for archive mesh/HKX imports."""
    def _import_current_archive_hkx_json(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry before importing HKX JSON.", error=True)
            return

        json_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import HKX Geometry JSON",
            str(self._default_archive_hkx_json_path(entry)),
            "HKX Geometry JSON (*.geometry.json *.json);;JSON (*.json)",
        )
        if not json_path:
            return

        self._start_current_archive_hkx_document_import(
            entry=entry,
            document_path=Path(json_path),
            document_label="JSON",
            apply_document=apply_hkx_editable_geometry_json,
        )

    def _import_current_archive_hkx_xml(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry before importing HKX XML.", error=True)
            return

        xml_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import HKX Geometry XML",
            str(self._default_archive_hkx_xml_path(entry)),
            "HKX Geometry XML (*.geometry.xml *.xml);;XML (*.xml)",
        )
        if not xml_path:
            return

        self._start_current_archive_hkx_document_import(
            entry=entry,
            document_path=Path(xml_path),
            document_label="XML",
            apply_document=apply_hkx_editable_geometry_xml,
        )

    def _preview_current_archive_mesh_import(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh before importing an OBJ preview.", error=True)
            return
        self._open_mesh_editor_for_entry(current_entry, mode="external_import", activate=True)
        self._start_archive_mesh_import_preview(current_entry)

    def _preview_current_archive_mesh_dds_import(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh before previewing an imported DDS.", error=True)
            return
        self._start_archive_mesh_dds_import_preview(current_entry)

    def _patch_current_archive_mesh_from_obj(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh before importing an OBJ.", error=True)
            return
        self._open_mesh_editor_for_entry(current_entry, mode="external_import", activate=True)
        self._start_archive_mesh_patch(current_entry)

    def _swap_current_archive_mesh_with_in_game(self) -> None:
        current_entry = self._current_archive_mesh_entry()
        if current_entry is None:
            self.set_status_message("Select a supported archive mesh before swapping with an in-game mesh.", error=True)
            return
        self._open_mesh_editor_for_entry(current_entry, mode="in_game_swap", activate=True)
        self._handle_archive_in_game_mesh_swap_entry(current_entry)
