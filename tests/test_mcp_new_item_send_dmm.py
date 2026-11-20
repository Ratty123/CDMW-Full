"""Create New Item > Send to DMM through the AI tools, on the real page with an owned archive."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.mcp import approvals
from tests.mcp_rail_helpers import RailClient, wait_for


@pytest.fixture
def page(tmp_path, monkeypatch):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.ui.new_item.tab import NewItemStudioTab
    from tests.test_new_item_service import TEMPLATE, _read, build_package, synthetic_files

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("cdmw.constants.MOD_FOLDER_TOOLS_ENABLED", True)
    monkeypatch.setattr(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("cdmw.ui.new_item.effect_placement_dialog._default_host_factory", lambda *_args: None)
    monkeypatch.setattr("cdmw.ui.new_item.panels_output.QDesktopServices.openUrl", lambda _url: True)
    monkeypatch.setattr("cdmw.ui.new_item.panels_output.resolve_settings_file_path", lambda: tmp_path / "CDMW.cfg")
    monkeypatch.setattr("cdmw.services.settings_service.resolve_settings_file_path", lambda: tmp_path / "CDMW.cfg")
    entries = tuple(parse_archive_pamt(build_package(tmp_path / "snapshot", synthetic_files())))

    presenter = QWidget()
    shell = SimpleNamespace(new_item_studio_tab=presenter,
                            settings=create_settings(settings_file_path=tmp_path / "studio.cfg"))
    window = SimpleNamespace(shell=shell)
    controller = NewItemStudioController(read_entry=_read, parent=presenter)
    controller.saved_work_root = tmp_path / "saved-work"
    tab = NewItemStudioTab(presenter, window=window, controller=controller, get_archive_entries=lambda: entries)
    presenter.workflow = tab
    presenter.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    presenter.resize(1200, 720)
    presenter.show()
    tab.start_snapshot()
    client = RailClient(tmp_path, window=window)
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    client.settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    try:
        wait_for(lambda: controller.ready and tab._panels_built, timeout=60)
        assert client.ok("new_item.search", text=str(TEMPLATE))["templates"]
        client.ok("new_item.pick", row=0)
        wait_for(lambda: controller.draft.template_key == TEMPLATE, timeout=60)
        assert client.ok("new_item.set", fields={
            "internal_name": "Mcp_Sword", "display_names": {"eng": "MCP Sword"}})["refused"] == {}
        yield client, tab
    finally:
        tab.close()
        wait_for(lambda: not tab.iter_shutdown_workers(), timeout=60)
        presenter.close()
        presenter.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _finished(client):
    wait_for(lambda: client.ok("new_item.plan")["build"]["status"] != "running", timeout=60)
    return client.ok("new_item.plan")["build"]


def test_send_to_dmm_writes_into_the_mods_folder_and_asks_before_replacing(page, tmp_path):
    client, tab = page
    dmm = tmp_path / "DMM"
    (dmm / "mods").mkdir(parents=True)
    (dmm / "DMM.exe").write_bytes(b"")

    # Without a current plan the page's own message comes back.
    assert client.call("new_item.send_to_dmm", dmm_folder=str(dmm))["error"]["code"] == "unavailable"
    assert client.ok("new_item.plan", action="refresh")["current"]
    elsewhere = tmp_path / "not-dmm"
    elsewhere.mkdir()
    assert client.call("new_item.send_to_dmm", dmm_folder=str(elsewhere))["error"]["code"] == "not_found"

    sent = client.ok("new_item.send_to_dmm", dmm_folder=str(dmm), mod_name="Copper Sword")
    assert sent["started"] and sent["dmm_mods_folder"] == str(dmm / "mods")
    first = _finished(client)
    assert first["status"] == "written" and Path(first["path"]).parent == dmm / "mods", first
    assert Path(first["path"]).is_dir() and not first.get("replaced")
    assert first["asked"][0]["answer"] == "ok"

    # A second send under the same name asks first, and no is the default.
    again = client.ok("new_item.send_to_dmm")
    assert not again["started"] and again["status"] == "cancelled" and "replace" in again["message"]
    replaced = client.ok("new_item.send_to_dmm", replace=True)
    assert replaced["started"]
    assert _finished(client)["replaced"]
    assert tab.output_panel.mod_name.text() == "Copper Sword"
