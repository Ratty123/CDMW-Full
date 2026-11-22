"""AI connections: the generic tools (state, commands, controls, pictures) through the real server."""
from __future__ import annotations

import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

from cdmw.app import app_folder
from cdmw.mcp import approvals
from cdmw.services.settings_service import create_settings
from cdmw.ui.commands.registry import Command, command_registry
from tests.mcp_full_helpers import McpApp

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


@pytest.fixture
def settings(tmp_path):
    return create_settings(settings_file_path=tmp_path / "ai.cfg")


class _Window(QMainWindow):
    """A window with one of each control, recording what its handlers saw."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Crimson Desert Mod Workbench")
        self.seen: list[tuple] = []
        page = QWidget()
        layout = QVBoxLayout(page)
        self.heading = QLabel("Probe page")
        self.apply_button = QPushButton("&Apply change")
        self.apply_button.clicked.connect(lambda: self.seen.append(("apply",)))
        self.delete_button = QPushButton("Delete draft")
        self.delete_button.clicked.connect(lambda: self.seen.append(("delete",)))
        self.export_button = QPushButton("Export OBJ...")
        self.export_button.clicked.connect(self._export)
        self.off_button = QPushButton("Unavailable")
        self.off_button.setEnabled(False)
        self.off_button.setToolTip("Open a mesh first.")
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("probe_name")
        self.name_edit.textEdited.connect(lambda text: self.seen.append(("typed", text)))
        self.name_edit.editingFinished.connect(lambda: self.seen.append(("finished", self.name_edit.text())))
        self.tick = QCheckBox("Include textures")
        self.tick.toggled.connect(lambda on: self.seen.append(("tick", on)))
        self.choice = QComboBox()
        self.choice.addItems(["Low", "Medium", "High"])
        self.choice.activated.connect(lambda index: self.seen.append(("chosen", index)))
        self.slider = QSlider()
        self.slider.setRange(0, 100)
        self.slider.sliderReleased.connect(lambda: self.seen.append(("released", self.slider.value())))
        self.rows = QListWidget()
        self.rows.addItems([f"Row {index}" for index in range(60)])
        self.rows.itemClicked.connect(lambda item: self.seen.append(("row", item.text())))
        self.rows.itemDoubleClicked.connect(lambda item: self.seen.append(("opened", item.text())))
        self.tabs = QTabWidget()
        self.tabs.addTab(QLabel("First page text"), "First")
        self.tabs.addTab(QLabel("Second page text"), "Second")
        for widget in (self.heading, self.apply_button, self.delete_button, self.export_button, self.off_button,
                       self.name_edit, self.tick, self.choice, self.slider, self.rows, self.tabs):
            layout.addWidget(widget)
        self.setCentralWidget(page)
        self.resize(640, 900)

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export OBJ", "", "OBJ (*.obj)")
        self.seen.append(("export", path))


@pytest.fixture
def window(app):
    window = _Window()
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.fixture
def mcp(app, profile, settings, window):
    session = McpApp(app, profile, settings, window)
    yield session
    session.close()


@pytest.fixture
def commands(app):
    """Register probe commands; they are removed afterwards."""

    registry = command_registry()
    added: list[str] = []

    def add(command: Command) -> Command:
        registry.register(command, replace=True)
        added.append(command.id)
        return command

    yield add
    for command_id in added:
        registry._commands.pop(command_id, None)


def _controls(mcp, **arguments) -> dict[str, dict]:
    rows = mcp.ok("app_ui", {"limit": 500, **arguments})["controls"]
    return {str(row.get("text") or row.get("name") or row["widget"]): row for row in rows}


# ----- the tool list ------------------------------------------------------------------
def test_the_generic_tools_are_listed_with_their_class(mcp) -> None:
    tools = {tool["name"]: tool for tool in mcp.request("tools/list")["result"]["tools"]}
    for name in ("app_state", "app_open_tool", "app_ui", "app_screenshot", "app_settings_get"):
        assert tools[name]["annotations"]["readOnlyHint"], name
    for name in ("app_run_command", "app_ui_act"):
        assert not tools[name]["annotations"]["readOnlyHint"], name
    assert "app_ui_act" in mcp.hello["result"]["instructions"]


def test_app_state_names_the_window_its_dialog_and_what_runs_without_asking(mcp, window, settings) -> None:
    state = mcp.ok("app_state")
    assert state["title"].startswith("Crimson Desert Mod Workbench") and state["dialog"] is None
    assert state["access"] == {"full_access": True, "edit": "ask", "destructive": "ask", "output": "ask"}
    assert state["window"].startswith("w")


# ----- app_run_command ------------------------------------------------------------------
def test_run_command_runs_a_read_command_and_asks_for_the_others_by_their_own_class(mcp, commands, settings) -> None:
    ran: list[str] = []
    commands(Command("shell.mcp_look", "Look", "shell", lambda: ran.append("look"), effect="read"))
    commands(Command("shell.mcp_change", "Change", "shell", lambda: ran.append("change")))
    commands(Command("shell.mcp_other", "Other change", "shell", lambda: ran.append("other")))
    commands(Command("shell.mcp_wipe", "Delete Draft", "shell", lambda: ran.append("wipe"), effect="destructive"))
    # As the Mesh Editor's helper mirrors a command: the default class, a label that says more.
    commands(Command("mesh_editor.mcp.delete_faces", "Delete Faces", "mesh_editor", lambda: ran.append("faces"),
                     helper=True))
    commands(Command("shell.mcp_busy", "Busy", "shell", lambda: ran.append("busy"), lambda: "Wait for the scan."))
    settings.setValue(approvals.FULL_ACCESS_KEY, False)

    assert mcp.ok("app_run_command", {"command": "shell.mcp_look"}) == {"ran": True, "command": "shell.mcp_look",
                                                                         "asked": []}
    assert mcp.controller.prompts == []
    # An edit asks, as an edit; Deny keeps it from running.
    mcp.send("app_run_command", {"command": "shell.mcp_change"})
    prompt = mcp.wait_for_prompt()
    assert prompt.request.effect == "edit" and prompt.request.tool == "app.run_command:shell.mcp_change"
    prompt.deny_button.click()
    assert mcp.read()["structuredContent"]["error"]["code"] == "refused" and "change" not in ran
    # Allowed for the session: that command, not every command.
    mcp.send("app_run_command", {"command": "shell.mcp_change"})
    mcp.wait_for_prompt().allow_session_button.click()
    assert not mcp.read()["isError"]
    assert mcp.ok("app_run_command", {"command": "shell.mcp_change"})["ran"] and ran.count("change") == 2
    mcp.send("app_run_command", {"command": "shell.mcp_other"})
    mcp.wait_for_prompt().deny_button.click()
    assert mcp.read()["isError"] and "other" not in ran
    # A destructive command asks as destructive; so does a mirrored command named Delete.
    for command_id in ("shell.mcp_wipe", "mesh_editor.mcp.delete_faces"):
        mcp.send("app_run_command", {"command": command_id})
        prompt = mcp.wait_for_prompt()
        assert prompt.request.effect == "destructive", command_id
        prompt.allow_once_button.click()
        assert not mcp.read()["isError"]
    assert ran[-2:] == ["wipe", "faces"]
    listed = {row["id"]: row for row in mcp.ok("commands_list", {"query": "mcp", "limit": 500})["commands"]}
    assert listed["mesh_editor.mcp.delete_faces"]["effect"] == "destructive"
    assert listed["shell.mcp_change"]["tool"] == "app_run_command"
    # Unavailable: the interface's reason, and nothing runs. Unknown: not found. Both before any question.
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    assert mcp.error("app_run_command", {"command": "shell.mcp_busy"}) == {"code": "unavailable",
                                                                            "message": "Wait for the scan."}
    assert mcp.error("app_run_command", {"command": "shell.mcp_none"})["code"] == "not_found"
    assert "busy" not in ran


@pytest.mark.parametrize("command_id", ["shell.import_profile", "browse.remove_old_install",
                                        "browse.restore_backup"])
def test_run_command_never_runs_what_only_the_user_may(mcp, commands, command_id) -> None:
    ran: list[str] = []
    commands(Command(command_id, "User only", command_id.split(".")[0], lambda: ran.append(command_id)))
    error = mcp.error("app_run_command", {"command": command_id})  # under Full access
    assert error["code"] == "refused" and "Only you" in error["message"] and ran == []


def test_a_commands_chooser_question_and_message_are_answered_not_shown(mcp, commands, tmp_path, settings) -> None:
    seen: list[object] = []

    def export() -> None:
        path, _filter = QFileDialog.getSaveFileName(None, "Export mesh", "", "OBJ (*.obj);;GLB (*.glb)")
        if not path:
            return
        if QMessageBox.question(None, "Export", "Include textures?") == QMessageBox.StandardButton.Yes:
            seen.append("textures")
        seen.append(path)
        QMessageBox.information(None, "Export", "Exported 1 file.")

    commands(Command("browse.mcp_export", "Export OBJ", "browse", export, effect="output"))
    # No answer: the chooser is cancelled, as Esc does, and the result says what was asked.
    cancelled = mcp.ok("app_run_command", {"command": "browse.mcp_export"})
    assert cancelled["asked"] == [{"kind": "save_file", "title": "Export mesh", "answer": "cancelled",
                                   "filter": "OBJ (*.obj);;GLB (*.glb)"}] and seen == []
    # Into a game installation: refused by the output rule, under Full access too.
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    refused = mcp.ok("app_run_command", {"command": "browse.mcp_export",
                                         "answers": {"save_file": str(game / "mod.obj")}})["asked"][0]
    assert refused["answer"] == "cancelled" and "does not write into" in refused["refused"] and seen == []
    # Over an existing file: refused too.
    (tmp_path / "old.obj").write_text("o")
    again = mcp.ok("app_run_command", {"command": "browse.mcp_export",
                                       "answers": {"save_file": str(tmp_path / "old.obj")}})["asked"][0]
    assert "already exists" in again["refused"] and seen == []
    # Answered: the handler gets the path, the question's answer, and the message comes back as text.
    target = str(tmp_path / "new.obj")
    done = mcp.ok("app_run_command", {"command": "browse.mcp_export",
                                      "answers": {"save_file": target, "confirm": "yes"}})
    assert seen == ["textures", target]
    assert [(row["kind"], row["answer"]) for row in done["asked"]] == [
        ("save_file", target), ("question", "yes"), ("information", "ok")]
    assert done["asked"][2]["text"] == "Exported 1 file."
    # The real dialogs are back once the call is over.
    assert QFileDialog.getSaveFileName.__name__ != "answered" and QMessageBox.question.__name__ != "answered"


def test_open_folder_text_and_pick_prompts_take_their_answers(mcp, commands, tmp_path) -> None:
    seen: list[object] = []

    def ask() -> None:
        seen.append(QFileDialog.getOpenFileName(None, "Open", "", "PNG (*.png)")[0])
        seen.append(QFileDialog.getExistingDirectory(None, "Folder"))
        seen.append(QInputDialog.getText(None, "Name", "Mod name:"))
        seen.append(QInputDialog.getItem(None, "Pick", "Quality:", ["Low", "High"], 0, False))
        seen.append(QMessageBox.question(None, "Sure?", "Replace it?") == QMessageBox.StandardButton.No)

    commands(Command("shell.mcp_ask", "Ask", "shell", ask))
    picture = tmp_path / "a.png"
    picture.write_bytes(b"png")
    out = tmp_path / "out"
    out.mkdir()
    mcp.ok("app_run_command", {"command": "shell.mcp_ask", "answers": {
        "file": str(picture), "folder": str(out), "text": "My mod", "item": "High"}})
    assert seen == [str(picture), str(out), ("My mod", True), ("High", True), True], "a question is declined"
    seen.clear()
    asked = mcp.ok("app_run_command", {"command": "shell.mcp_ask", "answers": {
        "file": str(tmp_path / "missing.png"), "folder": str(tmp_path / "nowhere"), "item": "Ultra"}})["asked"]
    assert seen == ["", "", ("", False), ("", False), True]
    assert "There is no file" in asked[0]["refused"] and "There is no folder" in asked[1]["refused"]


def test_a_dialog_of_the_apps_own_stays_open_and_is_driven_with_the_control_tools(mcp, commands, window, app,
                                                                                 monkeypatch) -> None:
    from cdmw.mcp import ui_actions

    outcome: list[int] = []

    def options() -> None:
        dialog = QDialog(window)
        dialog.setWindowTitle("Build options")
        layout = QVBoxLayout(dialog)
        name = QLineEdit()
        name.setObjectName("mod_title")
        build = QPushButton("Build")
        build.clicked.connect(dialog.accept)
        layout.addWidget(name)
        layout.addWidget(build)
        dialog.name = name
        window.options = dialog
        outcome.append(dialog.exec())

    commands(Command("shell.mcp_options", "Options...", "shell", options))
    monkeypatch.setattr(ui_actions, "ACTION_WAIT_S", 1.0)

    def client() -> None:
        started = mcp.ok("app_run_command", {"command": "shell.mcp_options"})
        assert started["waiting_on"]["title"] == "Build options" and outcome == []
        assert mcp.ok("app_state")["dialog"]["title"] == "Build options"
        # app_ui reads the dialog that waits, not the window behind it.
        shown = mcp.ok("app_ui")
        assert shown["window"]["title"] == "Build options"
        assert [row["kind"] for row in shown["controls"]] == ["field", "button"]
        mcp.ok("app_ui_act", {"text": "mod_title", "action": "set_text", "value": "Red cloak"})
        assert window.options.name.text() == "Red cloak"
        # "Build" writes a file by its name: an output action.
        mcp.ok("app_ui_act", {"text": "Build", "action": "click"})

    mcp.as_client(client)
    mcp.wait_until(lambda: outcome)
    assert outcome == [int(QDialog.DialogCode.Accepted)] and mcp.ok("app_state")["dialog"] is None


def test_no_command_can_change_the_ai_settings_or_the_game_folder(mcp, commands, settings) -> None:
    commands(Command("shell.mcp_sneak", "Sneak", "shell",
                     lambda: (settings.setValue(approvals.APPROVAL_KEY.format(effect="output"), "allow"),
                              settings.setValue(approvals.GAME_FOLDER_KEY, "C:/elsewhere"))))
    settings.setValue(approvals.GAME_FOLDER_KEY, "C:/game")
    error = mcp.error("app_run_command", {"command": "shell.mcp_sneak"})
    assert error["code"] == "refused" and "Only you" in error["message"]
    assert approvals.approval_mode(settings, "output") == "ask"
    assert settings.value(approvals.GAME_FOLDER_KEY) == "C:/game"


# ----- app_ui and app_ui_act ---------------------------------------------------------------
def test_app_ui_lists_the_controls_with_text_value_state_and_rows(mcp, window) -> None:
    controls = _controls(mcp)
    assert controls["Probe page"]["kind"] == "label"
    assert controls["Apply change"]["kind"] == "button", "the mnemonic's & is not part of the text"
    assert controls["Unavailable"] == {"widget": controls["Unavailable"]["widget"], "kind": "button",
                                       "enabled": False, "text": "Unavailable", "tip": "Open a mesh first."}
    assert controls["probe_name"]["kind"] == "field" and controls["probe_name"]["value"] == ""
    assert controls["Include textures"]["checked"] is False
    choice = next(row for row in controls.values() if row["kind"] == "choice")
    assert choice["items"] == ["Low", "Medium", "High"] and choice["value"] == "Low"
    rows = next(row for row in controls.values() if row["kind"] == "list")
    assert rows["row_count"] == 60 and len(rows["rows"]) == 30 and rows["more_rows"]
    assert rows["rows"][0] == {"row": 0, "cells": ["Row 0"]}
    tabs = next(row for row in controls.values() if row["kind"] == "tabs")
    assert tabs["items"] == ["First", "Second"] and tabs["value"] == "First"
    assert "First page text" in controls and "Second page text" not in controls, "only what is shown"
    # One list, all its rows from a row on.
    more = mcp.ok("app_ui", {"widget": rows["widget"], "rows_from": 55})["controls"][0]
    assert [row["cells"][0] for row in more["rows"]] == [f"Row {index}" for index in range(55, 60)]
    assert list(_controls(mcp, query="export")) == ["Export OBJ..."]
    assert {row["kind"] for row in _controls(mcp, kinds=["button"]).values()} == {"button"}


def test_app_ui_act_does_what_the_users_click_and_typing_do(mcp, window) -> None:
    controls = _controls(mcp)
    mcp.ok("app_ui_act", {"text": "Apply change", "action": "click"})
    mcp.ok("app_ui_act", {"widget": controls["probe_name"]["widget"], "action": "set_text", "value": "Kliff"})
    ticked = mcp.ok("app_ui_act", {"text": "Include textures", "action": "check"})
    mcp.ok("app_ui_act", {"text": "Include textures", "action": "check"})  # already ticked: no second toggle
    choice = next(row for row in controls.values() if row["kind"] == "choice")["widget"]
    mcp.ok("app_ui_act", {"widget": choice, "action": "select", "row": "High"})
    slider = next(row for row in controls.values() if row["kind"] == "slider")["widget"]
    mcp.ok("app_ui_act", {"widget": slider, "action": "set_value", "value": 40})
    rows = next(row for row in controls.values() if row["kind"] == "list")["widget"]
    selected = mcp.ok("app_ui_act", {"widget": rows, "action": "select", "row": "Row 7"})
    mcp.ok("app_ui_act", {"widget": rows, "action": "activate", "row": 12})
    tabs = next(row for row in controls.values() if row["kind"] == "tabs")["widget"]
    mcp.ok("app_ui_act", {"widget": tabs, "action": "select", "row": "Second"})
    assert window.seen == [("apply",), ("typed", "Kliff"), ("finished", "Kliff"), ("tick", True), ("chosen", 2),
                           ("released", 40), ("row", "Row 7"), ("row", "Row 12"), ("opened", "Row 12")]
    assert ticked["control"]["checked"] is True and window.tabs.currentIndex() == 1
    assert [row for row in selected["control"]["rows"] if row.get("selected")] == [
        {"row": 7, "cells": ["Row 7"], "selected": True}]
    # A disabled control gives its own reason and nothing runs; an unknown one is not found.
    assert mcp.error("app_ui_act", {"text": "Unavailable", "action": "click"}) == {
        "code": "unavailable", "message": "Open a mesh first."}
    assert mcp.error("app_ui_act", {"text": "No such control", "action": "click"})["code"] == "not_found"
    assert mcp.error("app_ui_act", {"widget": "w999999", "action": "click"})["code"] == "not_found"
    assert mcp.error("app_ui_act", {"widget": rows, "action": "click"})["code"] == "invalid_arguments"


def test_a_button_that_deletes_or_exports_asks_as_that_class(mcp, window, settings, tmp_path) -> None:
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    mcp.send("app_ui_act", {"text": "Delete draft", "action": "click"})
    prompt = mcp.wait_for_prompt()
    # What a session allowance would allow: this button of this window, not every "Delete draft".
    assert prompt.request.effect == "destructive"
    assert prompt.request.tool == "app.ui_act:click:Crimson Desert Mod Workbench:Delete draft"
    prompt.deny_button.click()
    assert mcp.read()["structuredContent"]["error"]["code"] == "refused" and window.seen == []
    mcp.send("app_ui_act", {"text": "Export OBJ...", "action": "click",
                            "answers": {"save_file": str(tmp_path / "mesh.obj")}})
    prompt = mcp.wait_for_prompt()
    assert prompt.request.effect == "output"
    prompt.allow_once_button.click()
    assert mcp.read()["structuredContent"]["asked"][0]["answer"] == str(tmp_path / "mesh.obj")
    assert window.seen == [("export", str(tmp_path / "mesh.obj"))]
    # Showing another tab changes nothing: it does not ask.
    tabs = next(row for row in _controls(mcp).values() if row["kind"] == "tabs")["widget"]
    mcp.ok("app_ui_act", {"widget": tabs, "action": "select", "row": 1})
    assert [p for p in mcp.controller.prompts if not p.request.decided] == []


def test_no_tool_drives_the_ai_settings_the_approval_prompt_or_the_game_folder(mcp, window, settings, app) -> None:
    from types import SimpleNamespace

    from cdmw.ui.ai_connections.settings_section import AiConnectionsSettingsSection

    section = AiConnectionsSettingsSection(settings, controller_lookup=lambda: mcp.controller)
    window.centralWidget().layout().addWidget(section)
    game_folder = QLineEdit()
    window.centralWidget().layout().addWidget(game_folder)
    window.archive = SimpleNamespace(archive_package_root_edit=game_folder)
    app.processEvents()
    from cdmw.mcp.ui_tree import widget_id

    for widget, action in ((section.full_access_checkbox, "check"), (section.enabled_checkbox, "uncheck"),
                           (game_folder, "set_text")):
        error = mcp.error("app_ui_act", {"widget": widget_id(widget), "action": action, "value": "C:/x"})
        assert error["code"] == "refused" and "Only you" in error["message"]
    assert approvals.connections_enabled(settings) and game_folder.text() == ""
    # Its own approval question: a tool cannot press Allow.
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    mcp.send("app_ui_act", {"text": "Apply change", "action": "click"})
    prompt = mcp.wait_for_prompt()
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    error = mcp.error("app_ui_act", {"widget": widget_id(prompt.allow_once_button), "action": "click"})
    assert error["code"] == "refused" and not prompt.request.decided
    prompt.deny_button.click()
    assert mcp.read()["isError"] and window.seen == []


def test_a_translated_button_keeps_its_class_and_is_found_by_either_text(mcp, window, settings) -> None:
    # As the interface shows it in German: the English source is kept beside the shown text.
    window.delete_button.setProperty("_i18n_source_text", "Delete draft")
    window.delete_button.setText("Entwurf löschen")
    row = _controls(mcp)["Entwurf löschen"]
    assert row["english"] == "Delete draft"
    settings.setValue(approvals.FULL_ACCESS_KEY, False)
    for name in ("Entwurf löschen", "Delete draft"):
        mcp.send("app_ui_act", {"text": name, "action": "click"})
        prompt = mcp.wait_for_prompt()
        assert prompt.request.effect == "destructive", name
        prompt.deny_button.click()
        assert mcp.read()["isError"]
    assert window.seen == []


def test_no_tool_types_a_place_in_the_game_into_a_field(mcp, window, settings, tmp_path) -> None:
    # A field may be where an output goes (Build Mod's folder, an extract folder).
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    copy = tmp_path / "backup of the game"
    (copy / "meta").mkdir(parents=True)
    (copy / "meta" / "0.papgt").write_bytes(b"\0")
    window.choice.setEditable(True)
    field = _controls(mcp)["probe_name"]["widget"]
    choice = next(row for row in _controls(mcp).values() if row["kind"] == "choice")["widget"]
    for target in (game, game / "mods" / "mine", copy / "0009", str(game).upper()):
        for widget in (field, choice):
            error = mcp.error("app_ui_act", {"widget": widget, "action": "set_text", "value": str(target)})
            assert error["code"] == "refused" and "does not write into" in error["message"], target
    assert window.name_edit.text() == "" and window.seen == []
    outside = str(tmp_path / "mods")
    mcp.ok("app_ui_act", {"widget": field, "action": "set_text", "value": outside})
    assert window.name_edit.text() == outside


def test_the_controls_that_write_into_the_game_or_set_its_folder_are_the_users(mcp, window, app) -> None:
    from types import SimpleNamespace

    from cdmw.mcp.ui_tree import widget_id

    pressed: list[str] = []
    remove = QPushButton("Remove What an Older CDMW Installed...")
    restore = QPushButton("Restore Backup...")

    class StartupArchivePathDialog(QDialog):  # the first-run dialog's name: it sets the game folder
        pass

    first_run = StartupArchivePathDialog(window)
    use = QPushButton("Use this folder", first_run)
    # The command palette runs any command, the user-only ones too: a tool has app_run_command.
    from cdmw.ui.commands.palette import CommandPalette

    palette = CommandPalette(command_registry(), ("shell",), window, popup=False)
    palette.show()
    app.processEvents()
    for control in palette.findChildren(QLineEdit) + palette.findChildren(QListWidget):
        action = "set_text" if isinstance(control, QLineEdit) else "activate"
        error = mcp.error("app_ui_act", {"widget": widget_id(control), "action": action, "value": "Restore",
                                         "row": 0})
        assert error["code"] == "refused" and "Only you" in error["message"]
    palette.close()
    for button in (remove, restore, use):
        button.clicked.connect(lambda _checked=False, b=button: pressed.append(b.text()))
    for button in (remove, restore):
        window.centralWidget().layout().addWidget(button)
    window.archive = SimpleNamespace(archive_remove_old_install_button=remove,
                                     archive_restore_patch_backup_button=restore)
    first_run.show()
    app.processEvents()
    for button in (remove, restore, use):
        error = mcp.error("app_ui_act", {"widget": widget_id(button), "action": "click"})  # under Full access
        assert error["code"] == "refused" and "Only you" in error["message"], button.text()
    assert pressed == []
    first_run.close()


def test_a_question_of_a_flow_that_writes_into_the_game_is_never_answered_for_the_user(mcp, commands,
                                                                                      monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda _parent, title, _text, *_more: shown.append(title) or QMessageBox.StandardButton.No))
    answers: list[object] = []

    from cdmw.ui.archive_browser.old_install_removal import TITLE

    def ask() -> None:
        # As when the user's own Restore Backup or removal reaches its question while a
        # tool's action runs: the titles those two flows give their questions.
        answers.append(QMessageBox.question(None, "Restore Archive Patch Backup", "Restore the game's files?"))
        answers.append(QMessageBox.question(None, TITLE, "Remove these from the game folder?"))
        answers.append(QMessageBox.question(None, "Probe", "Go on?"))

    commands(Command("shell.mcp_question", "Question", "shell", ask))
    asked = mcp.ok("app_run_command", {"command": "shell.mcp_question", "answers": {"confirm": "yes"}})["asked"]
    assert shown == ["Restore Archive Patch Backup", TITLE], "the real questions were shown to the user"
    assert answers == [QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.Yes]
    assert [row["title"] for row in asked] == ["Probe"]


def test_an_action_that_is_still_working_is_reported_as_running_not_as_a_dialog(mcp, commands, monkeypatch) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    from cdmw.mcp import ui_actions

    finished: list[bool] = []

    def work() -> None:
        loop = QEventLoop()
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        finished.append(True)

    commands(Command("shell.mcp_slow", "Slow", "shell", work))
    monkeypatch.setattr(ui_actions, "ACTION_WAIT_S", 0.5)

    def client() -> tuple[dict, list[bool]]:
        answer = mcp.ok("app_run_command", {"command": "shell.mcp_slow"})
        return answer, list(finished)  # as it was when the answer came

    result, finished_then = mcp.as_client(client)
    assert result["running"] is True and "waiting_on" not in result and finished_then == []
    mcp.wait_until(lambda: finished)


# ----- pictures and settings ----------------------------------------------------------------
def test_a_screenshot_comes_back_as_a_png_image(mcp, window) -> None:
    from PySide6.QtGui import QImage

    result = mcp.call("app_screenshot", {"max_side": 320})
    assert not result["isError"]
    image, facts = result["content"]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    picture = QImage.fromData(base64.b64decode(image["data"]), "PNG")
    assert not picture.isNull() and max(picture.width(), picture.height()) == 320
    assert result["structuredContent"]["width"] == picture.width() and "data" not in result["structuredContent"]
    # One control, by its id.
    button = _controls(mcp)["Apply change"]["widget"]
    small = mcp.call("app_screenshot", {"widget": button})["structuredContent"]
    assert small["width"] == window.apply_button.width()
    # The call log has the size, never the picture.
    from cdmw.mcp.audit import audit_log_path

    assert "iVBOR" not in audit_log_path().read_text(encoding="utf-8")


def test_settings_are_read_without_secrets(mcp, settings) -> None:
    settings.setValue("appearance/theme", "graphite")
    settings.setValue("model_library/api_token", "secret-value")
    rows = {row["key"]: row["value"] for row in mcp.ok("app_settings_get", {"limit": 500})["settings"]}
    assert rows["appearance/theme"] == "graphite" and rows["model_library/api_token"] == "[removed]"
    only = mcp.ok("app_settings_get", {"prefix": "appearance/"})["settings"]
    assert [row["key"] for row in only] == ["appearance/theme"]


def test_a_popup_panel_without_a_title_is_listed_and_its_controls_are_reached(mcp, window, app) -> None:
    """Browse Archives' Edited Results..., Files DMM Adds and More Filters open as titleless
    Qt.Popup panels; app_state, app_ui and app_ui_act skipped them (2026-11-22)."""

    from PySide6.QtWidgets import QGroupBox, QToolButton

    from cdmw.ui.archive_browser.command_strip import _ArchiveFiltersPopup

    group = QGroupBox("Edited Results...")
    inner = QVBoxLayout(group)
    only_edited = QCheckBox("Only edited files")
    only_edited.toggled.connect(lambda on: window.seen.append(("edited", on)))
    inner.addWidget(only_edited)
    button = QToolButton(window.centralWidget())
    button.setText("Actions")
    window.centralWidget().layout().addWidget(button)
    popup = _ArchiveFiltersPopup(group, button, "ProbeEditedResultsPopup")
    try:
        popup.toggle()
        app.processEvents()
        assert popup.isVisible()

        listed = {row["title"]: row for row in mcp.ok("app_state")["windows"]}
        assert listed["Edited Results..."]["class"] == "_ArchiveFiltersPopup"
        assert "Only edited files" in _controls(mcp), "the open panel is what app_ui shows"
        assert "Only edited files" in _controls(mcp, widget=mcp.ok("app_state")["window"]), \
            "and the page it was opened from lists it too"
        mcp.ok("app_ui_act", {"text": "Only edited files", "action": "check"})
        assert ("edited", True) in window.seen
    finally:
        popup.hide()
        popup.deleteLater()
        app.processEvents()
