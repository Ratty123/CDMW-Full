"""DLC-disabled overlays cannot be selected or dispatched by application UI."""
import os
import json
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw import constants
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.ui.mesh_editor.tab_direct_output import MeshEditorDirectOutputMixin
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_output import OutputPanel
from cdmw.ui.tools.mod_management import ModManagementTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_mesh_package_choices_ignore_saved_archive_output(app, tmp_path):
    dialog = MeshModExportDialog(None, title="Mesh", description="", output_parent=str(tmp_path),
                                 output_choice="dmm_archive", manager_profile="dmm")
    try:
        assert not constants.ARCHIVE_OVERLAYS_ENABLED
        choices = [dialog.manager.itemData(i) for i in range(dialog.manager.count())]
        assert {choice[0] for choice in choices} == {"dmm_loose", "jmm_loose", "cdumm_loose"}
        assert all(choice[1] == "loose_mod" for choice in choices)
        assert dialog.manager.currentData()[0] == "dmm_loose"
    finally:
        dialog.deleteLater()


def test_finished_mesh_has_no_install_action(app):
    from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame
    host = RustMeshEditorHostFrame()
    try:
        assert host.findChild(QPushButton, "MeshEditorRustResultInstallasOverlay") is None
        assert host.findChild(QPushButton, "MeshEditorRustResultBuildMod") is not None
    finally:
        host.deleteLater()


def test_mesh_overlay_requests_stop_before_looking_up_a_game_or_worker():
    owner = SimpleNamespace()
    MeshEditorDirectOutputMixin._start_mesh_overlay_prepare_requested(owner)
    MeshEditorDirectOutputMixin._restore_last_mesh_overlay_requested(owner)
    for kind in ("overlay_package", "overlay_prepare"):
        assert MeshEditorDirectOutputMixin._start_mesh_direct_output_worker(owner, kind, None) is False


def test_new_item_output_keeps_only_folder_and_portable_package(app, tmp_path, monkeypatch):
    controller = NewItemStudioController()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    panel = OutputPanel(controller, settings=settings)
    try:
        assert [panel.output_mode.itemData(i) for i in range(panel.output_mode.count())] == ["folder", "independent"]
        assert panel.overlay_mode_button.isHidden()
        assert not panel.overlay_mode_button.isEnabled()
        assert panel.include_mounted.isHidden()
        assert [panel.manager.itemText(i) for i in range(panel.manager.count())] == ["CDUMM", "JMM"]
        from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
        projected = json.dumps(NewItemPresentationBridge(panel).snapshot())
        assert "Game overlay" not in projected
        assert "Install as an overlay..." not in projected
        monkeypatch.setattr(NewItemStudioController, "has_current_plan", property(lambda self: True))
        monkeypatch.setattr(panel, "_refresh_export_state", lambda: None)
        for busy in (True, False):
            panel._busy_changed(busy)
            assert not panel.install_overlay_button.isEnabled()
            assert not panel.include_mounted.isEnabled()
        panel.independent_mode_button.click()
        assert panel.output_mode.currentData() == "independent"
        assert not panel.install_overlay_button.isVisibleTo(panel)
        panel.folder_mode_button.click()
        assert panel.output_mode.currentData() == "folder"
        assert controller.start_install_overlay(None) is False
        assert controller.start_overlay_migration(None, tmp_path) is False
        assert controller.start_overlay_removal(None, tmp_path) is False
        assert controller.start_export(tmp_path, "DMM") is False
    finally:
        controller.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_mod_management_hides_overlay_navigation_rows_and_actions(app, tmp_path):
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    try:
        tab._busy_changed(False)
        assert tab.recovery.isHidden() and not tab.recovery.isEnabled()
        assert tab.pages.indexOf(tab.independent_page.shared_page) == -1
        assert tab.update_page.source_kind.count() == 1
        assert tab.update_page.source_kind.currentData() is False
        assert tab.update_page.export_button.isHidden()
        assert not tab.update_page.export_button.isEnabled()
        for button in (tab.overlay_removal_button, tab.overlay_migration_button,
                       tab.independent_page.import_button, tab.independent_page.rebuild_button):
            assert not button.isEnabled()
            assert not button.isVisibleTo(tab)
        original = tab._current_page()
        for key in ("installed", "recovery", "shared"):
            tab.open_page(key)
            assert tab._current_page() is original
        # An old install must not reappear as an external-manager mod either.
        entry = SimpleNamespace(id="old-overlay", directory="0041")
        tab.inventory._entries = (entry,)
        tab.virtual_page._sources = ({}, (
            SimpleNamespace(name="0041", game=False, present=True),
            SimpleNamespace(name="0042", game=False, present=True),
        ), False)
        tab.virtual_page._render_sources()
        keys = [tab.virtual_page.selection.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(tab.virtual_page.selection.topLevelItemCount())]
        assert ("installed", "old-overlay") not in keys
        assert ("external", "0041") not in keys
        assert ("external", "0042") in keys
        tab.overview.set_entries((entry,))
        assert all(label.text() == "0" for label in tab.overview.counts.values())
        tab.inventory._run(lambda *_: pytest.fail("Overlay work started"), None, "unused", applying=True)
        tab.independent_page._apply(None)
        tab._migrate_overlay()
        tab._remove_overlay()
        tab.update_page._plan = SimpleNamespace(can_update=True)
        tab.update_page._buttons()
        assert not tab.update_page.export_button.isEnabled()
        tab.update_page._export()
        tab.merge_page.destination.setText(str(tmp_path / "merged"))
        tab.merge_page._plan = SimpleNamespace(conflicts=(), semantic_export=None)
        tab.merge_page._buttons()
        assert not tab.merge_page.export_button.isEnabled()
        tab.merge_page._export()
    finally:
        tab.shutdown()
        tab.deleteLater()
        app.processEvents()
