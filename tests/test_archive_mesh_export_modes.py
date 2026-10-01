from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from cdmw.domain.archives.mesh_contracts import MeshExportResult
from cdmw.models import ArchiveEntry, ArchivePreviewResult
from cdmw.ui.archive_browser import actions, mesh_import_export


_APPLICATION: QApplication | None = None


class _ExportWindow(actions.ArchiveBrowserActionMixin, mesh_import_export.ArchiveMeshImportExportMixin, QWidget):
    def __init__(self, entry: ArchiveEntry, directory: Path):
        super().__init__()
        self.shell = self.archive = self
        self.entry = entry
        self.settings_file_path = directory / "settings.json"
        self.archive_entries = (entry,)
        self.archive_entries_by_normalized_path = {entry.path: (entry,)}
        self.archive_entries_by_basename = {entry.basename: (entry,)}
        self.current_archive_preview_result = None
        self.archive_preview_showing_loose = False
        self.status_messages = []
        self.archive_tree = SimpleNamespace(
            itemAt=lambda _point: SimpleNamespace(isSelected=lambda: True),
            setCurrentItem=lambda _item: None,
            viewport=lambda: SimpleNamespace(mapToGlobal=lambda point: point),
        )

    def _archive_tree_item_kind(self, _item):
        return "file"

    def _archive_tree_item_value(self, _item):
        return 0

    def _archive_entry_at_tree_position(self, _position):
        return self.entry

    def _current_archive_entry(self):
        return self.entry

    def set_status_message(self, message, **kwargs):
        self.status_messages.append((message, kwargs))

    def _schedule_archive_selection_state_update(self):
        pass

    def _archive_entry_supports_family_context_actions(self, _entry):
        return False

    def _background_task_active(self):
        return False

    def append_archive_log(self, *_args, **_kwargs):
        pass

    def _prompt_archive_mesh_related_file_selection(self, _entry, **_kwargs):
        return ()

    def _run_utility_task(self, *, task, **_kwargs):
        task(lambda _message: None)


@pytest.mark.parametrize("extension,label,export_format,bake", [
    (".pac", "Export OBJ...", "obj", False),
    (".pac", "Export OBJ (Neutral Appearance)...", "obj", True),
    (".pac", "Export FBX...", "fbx", False),
    (".pam", "Export OBJ...", "obj", False),
])
def test_archive_context_menu_dispatches_selected_export_mode(tmp_path, monkeypatch, extension, label, export_format, bake):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/mesh" + extension,
        pamt_path=tmp_path / "0.pamt", paz_file=tmp_path / "0.paz",
        offset=0, comp_size=64, orig_size=64, flags=0, paz_index=0,
    )
    window = _ExportWindow(entry, tmp_path)
    calls = []

    class ExportMenu(QMenu):
        def exec(self, _position):
            choices = {action.text(): action for action in self.actions()}
            assert ("Export OBJ (Neutral Appearance)..." in choices) == (extension == ".pac")
            choices[label].trigger()

    def export(selected, output_dir, format_name, **kwargs):
        calls.append((selected, output_dir, format_name, kwargs))
        return MeshExportResult(output_paths=[], summary_lines=())

    monkeypatch.setattr(actions, "QMenu", ExportMenu)
    monkeypatch.setattr(mesh_import_export.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path))
    monkeypatch.setattr(mesh_import_export, "export_archive_mesh", export)
    try:
        window._show_archive_tree_context_menu(QPoint())
        assert len(calls) == 1
        selected, output_dir, format_name, kwargs = calls[0]
        assert selected is entry and output_dir == tmp_path
        assert format_name == export_format
        assert kwargs["resolve_skeleton_for_obj"] is bake
        assert kwargs["archive_entries_by_normalized_path"] == {entry.path: (entry,)}
    finally:
        window.close()


@pytest.mark.parametrize("native_preview", [False, True], ids=["before-preview", "native-preview"])
def test_selected_mesh_obj_export_does_not_require_python_preview(tmp_path, monkeypatch, native_preview):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/mesh.pac",
        pamt_path=tmp_path / "0.pamt", paz_file=tmp_path / "0.paz",
        offset=0, comp_size=64, orig_size=64, flags=0, paz_index=0,
    )
    window = _ExportWindow(entry, tmp_path)
    if native_preview:
        window.current_archive_preview_result = ArchivePreviewResult(
            status="ok", title=entry.basename, metadata_summary="", detail_text="",
            preview_model=None, dotnet_preview_package_path=str(tmp_path / "native-preview"),
        )
    prompts = []
    calls = []

    def choose_directory(_parent, title, _default):
        prompts.append(title)
        return str(tmp_path)

    def export(selected, output_dir, format_name, **kwargs):
        calls.append((selected, output_dir, format_name, kwargs))
        return MeshExportResult(output_paths=[], summary_lines=())

    monkeypatch.setattr(mesh_import_export.QFileDialog, "getExistingDirectory", choose_directory)
    monkeypatch.setattr(mesh_import_export, "export_archive_mesh", export)
    try:
        window._export_current_archive_model()
        assert prompts == ["Export OBJ"]
        assert len(calls) == 1
        selected, output_dir, format_name, kwargs = calls[0]
        assert selected is entry and output_dir == tmp_path
        assert format_name == "obj"
        assert kwargs["resolve_skeleton_for_obj"] is False
        assert kwargs["archive_entries_by_normalized_path"] == {entry.path: (entry,)}
        assert not window.status_messages
    finally:
        window.close()


@pytest.mark.parametrize("showing_loose", [False, True], ids=["preview-only", "loose-preview"])
def test_obj_preview_export_fallback_preserves_loose_preview_guard(tmp_path, monkeypatch, showing_loose):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(
        path="character/model/mesh.pac" if showing_loose else "character/model/material.xml",
        pamt_path=tmp_path / "0.pamt", paz_file=tmp_path / "0.paz",
        offset=0, comp_size=64, orig_size=64, flags=0, paz_index=0,
    )
    window = _ExportWindow(entry, tmp_path)
    preview_model = SimpleNamespace(path="character/model/preview.pac")
    window.current_archive_preview_result = ArchivePreviewResult(
        status="ok", title="Preview", metadata_summary="", detail_text="", preview_model=preview_model,
    )
    window.archive_preview_showing_loose = showing_loose
    target = tmp_path / "preview.obj"
    prompts = []
    exports = []

    def choose_file(_parent, title, default, file_filter):
        prompts.append((title, default, file_filter))
        return str(target), "Wavefront OBJ (*.obj)"

    def export_preview(model, output_path):
        exports.append((model, output_path))
        return output_path

    monkeypatch.setattr(mesh_import_export.QFileDialog, "getSaveFileName", choose_file)
    monkeypatch.setattr(mesh_import_export, "export_model_preview_to_obj", export_preview)
    try:
        window._export_current_archive_model()
        if showing_loose:
            assert not prompts and not exports
            assert window.status_messages == [("No model preview is available to export.", {"error": True})]
        else:
            assert prompts == [("Export Model Preview", str(tmp_path / "model_export" / "preview.obj"), "Wavefront OBJ (*.obj)")]
            assert exports == [(preview_model, target)]
            assert window.status_messages == [(f"Exported model preview to {target}", {})]
    finally:
        window.close()
