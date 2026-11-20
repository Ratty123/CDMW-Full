"""MCP gap plan item 13: Edit Game Table Values through typed tools."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QWidget

from cdmw.core.static_table_records import TableFieldEdit
from tests.mcp_rail_helpers import RailClient
from tests.test_game_table_edits import layers
from tests.test_game_tables_editor import _Shell


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(tmp_path, app, monkeypatch):
    import cdmw.services.settings_service as settings_service
    import cdmw.ui.archive_browser.game_table_actions as actions
    import cdmw.services.dmm_send as dmm_send
    import cdmw.ui.new_item.dmm_send_ui as dmm_send_ui
    from cdmw.services.game_table_edits import TableModResult

    written = {}

    def write(files, **kwargs):
        written.update(files=files, **kwargs)
        return TableModResult(kwargs["parent"] / kwargs["title"], False, kwargs["title"], tuple(files))

    ini = tmp_path / "cdmw.ini"
    monkeypatch.setattr(settings_service, "resolve_settings_file_path", lambda: ini)
    monkeypatch.setattr(dmm_send_ui, "resolve_settings_file_path", lambda: ini)
    # A real DMM install on the test machine must not be found.
    monkeypatch.setattr(dmm_send, "usual_dmm_places", lambda: [str(tmp_path / "no-usual-dmm")])
    monkeypatch.setattr(actions, "archive_table_layers", lambda root, table, **_kw: layers())
    monkeypatch.setattr(actions, "write_table_edit_mod", write)
    monkeypatch.setattr(actions, "composed_files", lambda layer: {"inventory.staticinfobody": (None, layer.body)})
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    class Browser(actions.ArchiveGameTableActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = _Shell()
            self.archive_package_root_edit = QLineEdit(str(tmp_path))

    browser = Browser()
    dmm = tmp_path / "DMM"
    (dmm / "mods").mkdir(parents=True)
    (dmm / "DMM.exe").write_bytes(b"")
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser.shell))
    yield client, browser, written, dmm
    dialog = getattr(browser, "_game_table_dialog", None)
    if dialog is not None:
        dialog.close()
    browser.deleteLater()


def test_open_read_set_and_write_a_table_through_the_dialog(browse) -> None:
    client, browser, written, dmm = browse
    assert client.ok("tables.editor_state")["open"] is False
    state = client.ok("tables.editor_edit", action="open", table="inventory")
    assert state["loaded"] == "inventory" and state["can_write"] is False
    money = next(row for row in state["rows"] if row["name"] == "Money")
    values = client.ok("tables.editor_state", row=money["row"])["values"]
    slots = next(value for value in values if value["label"] == "Maximum slots")

    changed = client.ok("tables.editor_edit", action="set", row=money["row"], value=slots["value"], new_value=500)
    assert changed["can_write"] is True
    assert changed["changes"] == [{"change": 0, "table": "inventory", "table_name": changed["changes"][0]["table_name"],
                                   "row": money["row"], "target": "_maxSlotCount", "value": 500}]
    assert next(v for v in changed["values"] if v["value"] == slots["value"])["in_this_mod"] == 500

    wrong = client.call("tables.editor_edit", action="set", row=money["row"], value=slots["value"], new_value=70000)
    assert wrong["error"]["code"] == "invalid_arguments" and "Enter a value from" in wrong["error"]["message"]

    result = client.ok("tables.editor_write", name="Bigger bags", dmm_folder=str(dmm))
    assert result["dmm_mods_folder"] == str(dmm / "mods")
    assert written["title"] == "Bigger bags" and written["parent"] == dmm / "mods"
    assert written["edits"] == (TableFieldEdit("inventory", money["row"], "_maxSlotCount", 500),)
    assert browser.shell.status[-1] == ("Wrote game table mod Bigger bags.", False)


def test_dlc_rows_unknown_tables_and_removing_a_change(browse) -> None:
    client, browser, _written, _dmm = browse
    refused = client.call("tables.editor_edit", action="open", table="no_such_table")
    assert refused["error"]["code"] == "refused"
    assert client.call("tables.editor_edit", action="load", table="inventory")["error"]["code"] == "unavailable"

    state = client.ok("tables.editor_edit", action="open",
                      path="gamedata/binarystaticinfo__/bin/inventory.dlc_01.staticinfoheader")
    locked = next(row for row in state["rows"] if not row["can_change"])
    dlc = client.call("tables.editor_edit", action="set", row=locked["row"], value=0, new_value=1)
    assert dlc["error"]["code"] == "refused" and "DLC" in dlc["error"]["message"]

    character = next(row for row in state["rows"] if row["name"] == "Character")
    client.ok("tables.editor_edit", action="set", row=character["row"], value=0, new_value=480)
    assert len(client.ok("tables.editor_state")["changes"]) == 1
    assert client.ok("tables.editor_edit", action="remove", change=0)["changes"] == []
    assert client.call("tables.editor_edit", action="set", row=999999, value=0, new_value=1)["error"]["code"] == (
        "not_found")


def test_write_needs_a_dmm_folder_it_can_find(browse, tmp_path) -> None:
    client, _browser, _written, _dmm = browse
    client.ok("tables.editor_edit", action="open", table="inventory")
    missing = client.call("tables.editor_write", name="Mod")
    assert missing["error"]["code"] == "invalid_arguments" and "DMM.exe" in missing["error"]["message"]
    elsewhere = tmp_path / "not-dmm"
    elsewhere.mkdir()
    assert client.call("tables.editor_write", dmm_folder=str(elsewhere))["error"]["code"] == "not_found"


def test_a_given_dmm_folder_is_the_one_written_and_remembered(browse, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from cdmw.services.dmm_send import DMM_FOLDER_SETTING

    client, _browser, written, dmm = browse
    other = tmp_path / "OtherDMM"
    (other / "mods").mkdir(parents=True)
    (other / "DMM.exe").write_bytes(b"")
    settings = QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat)
    settings.setValue(DMM_FOLDER_SETTING, str(other))
    settings.sync()

    state = client.ok("tables.editor_edit", action="open", table="inventory")
    money = next(row for row in state["rows"] if row["name"] == "Money")
    values = client.ok("tables.editor_state", row=money["row"])["values"]
    slots = next(value for value in values if value["label"] == "Maximum slots")
    assert client.ok("tables.editor_edit", action="set", row=money["row"], value=slots["value"],
                     new_value=500)["can_write"] is True
    result = client.ok("tables.editor_write", name="Given", dmm_folder=str(dmm))
    assert result["dmm_mods_folder"] == str(dmm / "mods") and written["parent"] == dmm / "mods"
    assert QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat).value(DMM_FOLDER_SETTING) == str(dmm)
