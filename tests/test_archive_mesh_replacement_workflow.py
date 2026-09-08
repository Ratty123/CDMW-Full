"""Archive replacement entry points with real Qt wiring and owned mesh fixtures."""

from __future__ import annotations

import hashlib
import os
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QLabel, QMenu,
    QMessageBox, QPlainTextEdit, QRadioButton, QTabWidget,
)

from cdmw.app.events import AppEventBus
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser import source_mix_overlay
from cdmw.ui.archive_browser import actions as archive_actions
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import configure_synthetic_archive_context
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tests.test_static_mesh_replacer_preview import _minimal_pac_original


APP = QApplication.instance() or QApplication([])
REPLACE_LABEL = "Replace Mesh from File..."


def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Timed out waiting for the archive workflow"


@pytest.fixture
def archive_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    window = MainWindow(app_context=AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    ))
    window.settings_file_path = tmp_path / "settings.cfg"
    original, _mesh = _minimal_pac_original()
    # The shared fixture leaves its 40-byte PAC influence rows empty. Populate
    # valid rigid influences so the real importer can prove donor-weight reuse.
    original = bytearray(original)
    cursor = 0x50
    for section_index in range(5):
        if section_index:
            for vertex_index in range(3):
                original[cursor + vertex_index * 40 + 28] = 255
        cursor += struct.unpack_from("<I", original, 0x14 + section_index * 8)[0]
    pamt, paz = tmp_path / "0.pamt", tmp_path / "0.paz"
    pamt.write_bytes(b"owned synthetic archive index")
    paz.write_bytes(original)
    entry = ArchiveEntry("object/model/target.pac", pamt, paz, 0, len(original), len(original), 0, 0)
    configure_synthetic_archive_context(window, entry)
    monkeypatch.setattr(window.archive, "_current_archive_entry", lambda: entry)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (pamt, paz)}
    try:
        yield window, entry
    finally:
        for dialog in tuple(window._modeless_alignment_dialogs.values()):
            dialog.reject()
        if window.utility_worker is not None:
            window.utility_worker.stop()
        wait_for(lambda: window.worker_thread is None)
        window._finalize_close()
        window.deleteLater()
        APP.processEvents()
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


def test_loose_folder_button_scans_on_shell_worker_and_opens_review(
    archive_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, entry = archive_window
    source = tmp_path / "loose" / entry.path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"replacement game-format payload")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(tmp_path / "loose"))
    monkeypatch.setattr(window.archive, "_archive_lookup_indexes_snapshot", lambda: (
        window.archive.archive_entries_by_normalized_path,
        window.archive.archive_entries_by_basename,
    ))
    worker_threads, reviewed, warnings = [], [], []
    real_scan = source_mix_overlay.run_source_mix_scan

    def scan(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        return real_scan(*args, **kwargs)

    def review(dialog):
        assert dialog.windowTitle() == "Loose Mod Overlay Review"
        tree = dialog.findChild(QTabWidget).widget(0)
        candidate = tree.topLevelItem(0).data(0, Qt.UserRole)
        reviewed.append(candidate)
        dialog.reject()
        return QDialog.Rejected

    monkeypatch.setattr(source_mix_overlay, "run_source_mix_scan", scan)
    monkeypatch.setattr(QDialog, "exec", review)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))
    window.archive.archive_import_loose_mod_button.click()
    wait_for(lambda: reviewed or warnings)
    assert warnings == []
    assert reviewed[0].target_archive_entry == entry
    assert reviewed[0].source_path == source
    assert worker_threads and worker_threads[0] != threading.get_ident()
    assert window.worker_thread is None


def test_replacement_import_menu_tracks_target_and_busy_state(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, entry = archive_window
    archive = window.archive
    archive._update_archive_model_action_controls(None)
    action = next(a for a in archive.archive_import_menu_button.menu().actions() if a.text().rstrip(".") == REPLACE_LABEL.rstrip("."))
    calls = []
    monkeypatch.setattr(archive, "_start_archive_mesh_patch", calls.append)
    archive._update_archive_model_action_controls(None)
    assert action.isEnabled()
    action.trigger()
    assert calls == [entry]
    window.worker_thread = object()
    try:
        archive._update_archive_model_action_controls(None)
        assert not action.isEnabled()
    finally:
        window.worker_thread = None
    monkeypatch.setattr(archive, "_current_archive_entry", lambda: None)
    archive._update_archive_model_action_controls(None)
    assert not action.isEnabled()


def test_replacement_context_menu_uses_clicked_target(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, entry = archive_window
    archive = window.archive
    item = SimpleNamespace(isSelected=lambda: True)
    monkeypatch.setattr(archive.archive_tree, "itemAt", lambda _position: item)
    monkeypatch.setattr(archive.archive_tree, "setCurrentItem", lambda _item: None)
    monkeypatch.setattr(archive, "_archive_tree_item_kind", lambda _item: "file")
    monkeypatch.setattr(archive, "_archive_tree_item_value", lambda _item: 0)
    monkeypatch.setattr(archive, "_archive_entry_at_tree_position", lambda _position: entry)
    monkeypatch.setattr(archive, "_schedule_archive_selection_state_update", lambda: None)
    calls = []
    monkeypatch.setattr(archive, "_start_archive_mesh_patch", calls.append)

    class Menu(QMenu):
        def exec(self, *_args):
            action = next(a for a in self.actions() if a.text() == REPLACE_LABEL)
            assert action.isEnabled()
            action.trigger()
            return action

    monkeypatch.setattr(archive_actions, "QMenu", Menu)
    archive._show_archive_tree_context_menu(QPoint())
    assert calls == [entry]


def test_obj_import_builds_reparseable_loose_pac_without_opening_original_editor(
    archive_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, entry = archive_window
    source = tmp_path / "replacement.obj"
    source.write_text(
        "o replacement\nv 0 0 0\nv 2 0 0\nv 2 2 0\nv 0 2 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n",
        encoding="utf-8",
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(source), ""))
    opened, warnings, setup_modes = [], [], []
    monkeypatch.setattr(window, "_open_mesh_editor_for_entry", lambda *a, **kw: opened.append((a, kw)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))

    def accept_setup(dialog):
        modes = dialog.findChildren(QRadioButton)
        if not modes:
            warnings.append((dialog.windowTitle(), [widget.toPlainText() for widget in dialog.findChildren(QPlainTextEdit)]))
            dialog.reject()
            return QDialog.Rejected
        selected = next(button for button in modes if button.isChecked())
        setup_modes.append(selected.text())
        assert selected.text() == "Mesh Replacement"
        assert selected.isEnabled()
        dialog.accept()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_setup)
    window.archive._update_archive_model_action_controls(None)
    window.archive.archive_model_import_mesh_button.click()
    wait_for(lambda: window._modeless_alignment_dialogs or warnings)
    assert warnings == []
    assert opened == []
    assert setup_modes == ["Mesh Replacement"]
    dialog = next(iter(window._modeless_alignment_dialogs.values()))
    wait_for(lambda: bool(getattr(dialog, "_cdmw_builder_construction_complete", False)))
    context = dialog._cdmw_builder_construction_context
    assert context["entry"] == entry
    assert context["scene_import_result"].mesh.total_faces == 2
    assert context["original_mesh"].total_faces == 1
    assert callable(context["continue_build_callback"])
    assert dialog._source_mix_task_controller._owner is window
    assert dialog.parentWidget() is window.archive
    assert opened == []

    exported = []
    monkeypatch.setattr(window.archive, "_collect_archive_mod_ready_export_target", lambda **_kw: (
        tmp_path / "output", ModPackageInfo(title="Replacement regression"), True, False,
        ModPackageExportOptions(),
    ))
    monkeypatch.setattr(window.archive, "_prompt_archive_mesh_related_file_selection", lambda *_a, **_kw: ())
    monkeypatch.setattr(window.archive, "_show_archive_import_preview", lambda *a, **kw: exported.append((a, kw)))
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Ok)
    wait_for(lambda: window.worker_thread is None)
    complete_swap = dialog.findChild(QCheckBox, "MeshAlignmentCompleteExternalSwapCheckbox")
    complete_swap.setChecked(False)
    build_button = dialog._material_authority_build_button
    status = dialog.findChild(QLabel, "MeshReplacementBuilderStatus")
    assert build_button.isEnabled()
    build_button.click()
    wait_for(lambda: exported or warnings or "failed" in status.text().lower())
    assert warnings == []
    assert "failed" not in status.text().lower(), status.text()
    wait_for(lambda: "Wrote rebuilt" in status.text())
    assert len(exported) == 1
    result = exported[0][0][1]
    assert result.import_mode == "static_replacement"
    assert result.parsed_mesh.total_faces == 2
    package_root = exported[0][1]["loose_package_root"]
    output_files = list(package_root.rglob("target.pac"))
    assert len(output_files) == 1
    assert output_files[0].read_bytes() == result.rebuilt_data
    rebuilt = parse_pac(output_files[0].read_bytes(), entry.path)
    assert len(rebuilt.submeshes[0].vertices) == 4
    assert len(rebuilt.submeshes[0].faces) == 2
    assert len(rebuilt.submeshes[0].bone_weights) == 4
    assert all(sum(weights) == pytest.approx(1.0) for weights in rebuilt.submeshes[0].bone_weights)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert opened == []


def test_cancel_file_picker_preserves_editor_and_starts_no_worker(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _entry = archive_window
    opened = []
    monkeypatch.setattr(window, "_open_mesh_editor_for_entry", lambda *a, **kw: opened.append((a, kw)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    window.archive._update_archive_model_action_controls(None)
    window.archive.archive_model_import_mesh_button.click()
    assert opened == []
    assert window.worker_thread is None
    assert not window._modeless_alignment_dialogs
