import json
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.tools.dmm_packages_page import PACKAGES_SETTING
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_dmm_packages_page import _files


def test_mod_management_list_and_package_changes_persist(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab()
    settings = QSettings(str(tmp_path / "dmm.ini"), QSettings.Format.IniFormat)
    tab.mods_page._settings = settings
    client = RailClient(tmp_path, widgets={"mod_management": tab})
    packages = _files(tmp_path, "Amber.cdmw", "Blue.cdmw")
    try:
        assert client.ok("mods.list")["packages"] == []
        client.ok("mods.change", action="add_packages", paths=packages)
        assert tab.mods_page.packages() == packages
        client.ok("mods.change", action="remove_packages", rows=[0])
        assert client.ok("mods.list")["packages"] == packages[1:]
        settings.sync()
        assert json.loads(settings.value(PACKAGES_SETTING)) == packages[1:]
        assert not client.ok("mods.list")["merge_available"]
        refused = client.call("mods.export", destination=str(tmp_path / "merged"))
        assert refused["error"]["code"] == "unavailable"
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.processEvents()


def test_retained_mod_management_controls_merge_owned_packages(tmp_path, retained_mod_folder_tools):
    from cdmw.services.independent_item_compatibility import _semantic_export_plan, _semantic_layer
    from cdmw.services.independent_item_install import resolve_items
    from cdmw.services.independent_item_package import package_bytes
    from cdmw.services.mod_merge_service import export_merged_mod
    from tests.test_independent_item_fields import field_package
    from tests.test_independent_items import setup_game

    app = QApplication.instance() or QApplication([])
    service, snapshot, _entries = setup_game(tmp_path)
    game = tmp_path / "game"
    folders = []
    for number in range(2):
        result = resolve_items((package_bytes(field_package(snapshot, value=1)),), game, rebuild=True)
        layers = [_semantic_layer(package, changes, result.registry) for package, changes in result.contributions]
        plan = _semantic_export_plan(game, (), layers, result.baseline, result.registry, result.pending, result.external,
                                     observed=result.observed)
        folders.append(export_merged_mod(plan, tmp_path / f"source-{number}").package_root)
    tab = ModManagementTab(service=service, get_package_root=lambda: str(game))
    client = RailClient(tmp_path, widgets={"mod_management": tab})
    try:
        assert client.ok("mods.list")["merge_available"]
        for path in folders:
            client.ok("mods.change", action="add_merge_folder", path=str(path))
        assert list(tab.merge_page._folder_paths()) == [str(path) for path in folders]
        client.ok("mods.change", action="check_merge")
        wait_for(lambda: not tab.controller.busy)
        assert tab.merge_page._plan is not None, tab.merge_page.status.text()
        assert tab.merge_page._plan.semantic_export is not None, tab.merge_page.status.text()
        destination = tmp_path / "merged"
        client.ok("mods.export", destination=str(destination), title="Owned combined mod")
        wait_for(lambda: not tab.controller.busy)
        assert "Merged mod written" in tab.merge_page.status.text()
        assert (destination / "cdmw-semantic.cdmw").is_file()
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.processEvents()


def test_mod_management_can_export_to_dmm_without_mounting(tmp_path, monkeypatch):
    from cdmw.services.dmm_send import DmmSendResult
    from cdmw.ui.tools.dmm_packages_page import DMM_MOD_TITLE

    app = QApplication.instance() or QApplication([])
    game = tmp_path / "game"
    game.mkdir()
    destination = tmp_path / "dmm-mods"
    destination.mkdir()
    source = _files(tmp_path, "Owned.cdmw")
    tab = ModManagementTab(get_package_root=lambda: str(game))
    tab.mods_page._settings = QSettings(str(tmp_path / "dmm.ini"), QSettings.Format.IniFormat)
    client = RailClient(tmp_path, widgets={"mod_management": tab})

    def write(packages, root, mods, title, **_):
        assert list(packages) == source and root == str(game) and title == DMM_MOD_TITLE
        target = mods / title
        target.mkdir()
        (target / "0.paz").write_bytes(b"owned output")
        return DmmSendResult(target, False, title)

    monkeypatch.setattr("cdmw.services.dmm_send_process.send_item_packages_in_subprocess", write)
    try:
        client.ok("mods.change", action="add_packages", paths=source)
        result = client.ok("mods.export", action="dmm", folder=str(destination))
        wait_for(lambda: not tab.controller.busy)
        assert "Sent 1 item package" in tab.mods_page.status.text()
        assert (Path(result["destination"]) / "0.paz").read_bytes() == b"owned output"
        assert list(game.iterdir()) == []
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.processEvents()
