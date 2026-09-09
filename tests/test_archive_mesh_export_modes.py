from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from cdmw.domain.archives.mesh_contracts import MeshExportResult
from cdmw.models import ArchiveEntry
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
