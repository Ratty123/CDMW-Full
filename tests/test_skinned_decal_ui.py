import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

from cdmw.core.skinned_decal import read_skinned_decal
from cdmw.models import ArchiveEntry
from cdmw.services.skinned_decal_service import DecalEditSource
from cdmw.ui.archive_browser import actions, skinned_decal_actions as wiring, skinned_decal_dialog as ui
from tests.test_archive_mesh_export_modes import _ExportWindow
from tests.test_skinned_decal import sequence_fixture

_APP = QApplication.instance() or QApplication([])


def test_real_dialog_retains_noop_and_invalid_input(monkeypatch):
    document = read_skinned_decal(sequence_fixture())
    dialog = ui.SkinnedDecalDialog(document)
    try:
        assert dialog.changes() == ()
        field, editor = next(row for row in dialog._editors if row[0].name == "_opacity")
        editor.setText("NaN")
        errors = []
        monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: errors.append(args[-1]))
        dialog.accept()
        assert errors and dialog.result() != QDialog.DialogCode.Accepted
        assert editor.text() == "NaN"
        editor.setText("0.25")
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.changes() == ((field.path, "0.25"),)
    finally:
        dialog.close()


def test_archive_menu_dispatches_selected_sequence(tmp_path, monkeypatch):
    entry = ArchiveEntry("test.paseq", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 64, 64, 0, 0)
    window = _ExportWindow(entry, tmp_path)
    calls = []
    window._edit_archive_skinned_decal = calls.append

    class Menu(QMenu):
        def exec(self, _position):
            next(a for a in self.actions() if a.text() == "Edit Skinned Decal...").trigger()

    monkeypatch.setattr(actions, "QMenu", Menu)
    try:
        window._show_archive_tree_context_menu(QPoint())
        assert calls == [entry]
    finally:
        window.close()


def test_loading_and_saving_are_queued_and_stale_results_ignored(tmp_path, monkeypatch):
    class Owner(wiring.SkinnedDecalActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = self
            self.settings_file_path = tmp_path / "settings.json"
            self.jobs = []
            self.messages = []

        def _run_utility_task(self, **kwargs):
            self.jobs.append(kwargs)

        _run_utility_task_when_idle = _run_utility_task

        def set_status_message(self, *args, **kwargs):
            self.messages.append(args)

    entry = ArchiveEntry("test.paseq", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 64, 64, 0, 0)
    source = DecalEditSource(entry, read_skinned_decal(sequence_fixture()))
    seen = []
    monkeypatch.setattr(wiring, "archive_workflow_dependency_context", lambda *a: SimpleNamespace(selected_entry=entry))
    monkeypatch.setattr(wiring, "load_decal_source", lambda *a, **kw: seen.append(kw) or source)
    owner = Owner()
    try:
        owner._edit_archive_skinned_decal(entry)
        assert not seen
        first = owner.jobs[-1]
        assert first["task_accepts_cancel"]
        assert first["task"](None, None) == source
        owner._edit_archive_skinned_decal(entry)
        first["on_complete"](source)  # Must not open a stale modal dialog.
        assert len(owner.jobs) == 2
        monkeypatch.setattr(wiring.SkinnedDecalDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        target = tmp_path / "saved.paseq"
        monkeypatch.setattr(wiring.QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
        owner.jobs[-1]["on_complete"](source)
        assert len(owner.jobs) == 3 and not target.exists()
        save = owner.jobs[-1]
        assert save["task_accepts_cancel"]
        assert save["task"](None, None) == target
        assert target.read_bytes() == source.document.source
        owner._skinned_decal_request_id += 1
        save["on_complete"](target)
        assert not owner.messages
    finally:
        owner.close()
