"""The removed game installs cannot be selected or dispatched by application UI (decision 39)."""
import os
import json
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
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


def test_mesh_package_choices_keep_the_dmm_archive_group_folder(app, tmp_path):
    # A DMM archive group is a package folder DMM serves by path; it mounts nothing
    # into the game, so it stays available while overlays are disabled.
    dialog = MeshModExportDialog(None, title="Mesh", description="", output_parent=str(tmp_path),
                                 output_choice="dmm_archive", manager_profile="dmm")
    try:
        choices = [dialog.manager.itemData(i) for i in range(dialog.manager.count())]
        assert [choice[0] for choice in choices] == ["dmm_loose", "dmm_archive"]
        assert dialog.manager.currentData()[0] == "dmm_archive"
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


def test_the_overlay_and_virtual_loader_installs_are_gone(app):
    # Decision 39: the switched-off installs are removed, not hidden behind a switch.
    assert not hasattr(constants, "ARCHIVE_OVERLAYS_ENABLED")
    assert not hasattr(constants, "VIRTUAL_LOADING_ENABLED")
    assert not hasattr(MeshEditorDirectOutputMixin, "_restore_last_mesh_overlay_requested")
    assert not hasattr(MeshEditorDirectOutputMixin, "_start_mesh_overlay_prepare_requested")
    import importlib.util
    for name in ("cdmw.services.archive_overlay_migration", "cdmw.services.archive_overlay_rebuild",
                 "cdmw.services.archive_reference_cleanup", "cdmw.services.virtual_loader_runtime",
                 "cdmw.services.virtual_loader_process", "cdmw.ui.new_item.overlay_manager_dialog",
                 "cdmw.ui.new_item.independent_items_page", "cdmw.ui.new_item.virtual_loader_page"):
        assert importlib.util.find_spec(name) is None, name


def test_new_item_output_keeps_only_folder_and_portable_package(app, tmp_path, monkeypatch):
    controller = NewItemStudioController()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    panel = OutputPanel(controller, settings=settings)
    try:
        assert [panel.output_mode.itemData(i) for i in range(panel.output_mode.count())] == ["folder", "independent"]
        assert not hasattr(panel, "overlay_mode_button")
        assert not hasattr(panel, "include_mounted")
        assert [panel.manager.itemText(i) for i in range(panel.manager.count())] == ["DMM"]
        assert panel.manager.isHidden()
        assert [panel.output_mode.itemText(i) for i in range(panel.output_mode.count())] == [
            "Mod folder · DMM", "Item package · .cdmw"]
        from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
        projected = json.dumps(NewItemPresentationBridge(panel).snapshot())
        assert "Game overlay" not in projected
        assert "Install as an overlay..." not in projected
        panel.independent_mode_button.click()
        assert panel.output_mode.currentData() == "independent"
        assert not hasattr(panel, "install_overlay_button")
        assert not panel.send_dmm_button.isVisibleTo(panel)
        panel.folder_mode_button.click()
        assert panel.output_mode.currentData() == "folder"
        assert panel.send_dmm_button.isVisibleTo(panel)
        for removed in ("start_install_overlay", "start_overlay_migration", "start_overlay_removal",
                        "install_finished", "install_failed"):
            assert not hasattr(controller, removed), removed
        assert controller.start_export(tmp_path, "CDUMM") is False
    finally:
        controller.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_mod_management_offers_only_the_mods_page_by_default(app, tmp_path):
    assert not constants.MOD_FOLDER_TOOLS_ENABLED
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    try:
        assert [tab.pages.tabText(i) for i in range(tab.pages.count())] == ["Mods"]
        assert tab.virtual_page is tab.mods_page
        original = tab._current_page()
        assert original is tab.mods_page
        for key in ("overview", "recovery", "installed", "shared", "independent", "repackage", "merge", "updates"):
            tab.open_page(key)
            assert tab._current_page() is original
        for removed in ("overlay_removal_button", "overlay_migration_button", "independent_page", "recovery",
                        "inventory", "overview"):
            assert not hasattr(tab, removed), removed
        assert tab.update_page.source_kind.count() == 1
        assert tab.update_page.source_kind.currentData() is False
        assert tab.update_page.export_button.isHidden()
        assert not tab.update_page.export_button.isEnabled()
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


def test_new_item_start_screen_has_no_mod_update_check(app):
    from cdmw.ui.new_item.tab import NewItemStudioTab
    tab = NewItemStudioTab()
    try:
        assert not tab._update_button.isVisibleTo(tab)
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()
