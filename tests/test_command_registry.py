"""P12 step 1 and the shell's part of step 2: one command, one state, one reason."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from cdmw.ui.commands import Command, CommandRefused, CommandRegistry
from cdmw.ui.commands.adapters import bind_action, bound_command_id


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_a_command_is_defined_once_and_refuses_with_its_reason(app):
    registry = CommandRegistry()
    state = {"busy": True, "ran": 0}
    registry.register(Command("shell.example", "Example", "shell",
                              lambda: state.__setitem__("ran", state["ran"] + 1),
                              lambda: "Wait." if state["busy"] else ""))
    with pytest.raises(ValueError):
        registry.register(Command("shell.example", "Again", "shell", lambda: None))
    for bad in (dict(id="noarea", context="shell"), dict(id="shell.x", context="nowhere")):
        with pytest.raises(ValueError):
            Command(bad["id"], "Label", bad["context"], lambda: None)
    assert registry.reason("shell.example") == "Wait." and not registry.available("shell.example")
    with pytest.raises(CommandRefused, match="Wait."):
        registry.run("shell.example")
    assert state["ran"] == 0
    state["busy"] = False
    registry.run("shell.example")
    assert state["ran"] == 1 and registry.recent() == ["shell.example"]


def test_a_broken_check_reads_as_unavailable_not_as_a_crash(app):
    registry = CommandRegistry()
    registry.register(Command("shell.broken", "Broken", "shell", lambda: None, lambda: 1 / 0))
    # The exception's text goes to the log, not into the reason (plan 8.7 E8).
    assert registry.reason("shell.broken") == "Unavailable"


def test_every_view_of_a_command_shows_its_state_and_reason(app):
    registry = CommandRegistry()
    state = {"reason": "Not now."}
    ran = []
    registry.register(Command("shell.example", "Example", "shell", lambda: ran.append(1), lambda: state["reason"]))
    menu_entry, toolbar_entry = QAction("Example"), QAction("Example")
    for action in (menu_entry, toolbar_entry):
        bind_action(action, registry, "shell.example")
        assert bound_command_id(action) == "shell.example"
        assert not action.isEnabled() and action.toolTip() == "Not now."
    state["reason"] = ""
    registry.refresh("shell")
    assert menu_entry.isEnabled() and toolbar_entry.isEnabled()
    toolbar_entry.trigger()
    assert ran == [1]
    # A view refreshes only for its own context.
    state["reason"] = "Later."
    registry.refresh("browse")
    assert menu_entry.isEnabled()
    registry.refresh("")
    assert not menu_entry.isEnabled() and menu_entry.toolTip() == "Later."


def test_the_shell_menus_are_views_of_shell_commands(app, monkeypatch):
    from cdmw.ui.shell.shell_commands import BUSY_REASON, SHELL_ACTIONS, TOOL_COMMAND_PREFIX, install_shell_commands
    from PySide6.QtWidgets import QMainWindow

    calls = []

    class Shell(QMainWindow):
        def __getattr__(self, name):
            if name.startswith(("show_", "export_", "import_", "copy_", "open_", "_detach", "_attach")):
                return lambda *a, **k: calls.append(name)
            raise AttributeError(name)

    shell = Shell()
    for attribute in SHELL_ACTIONS.values():
        setattr(shell, attribute, QAction(attribute, shell))
    from cdmw.ui.commands.palette import PALETTE_COMMAND

    registry = install_shell_commands(shell)
    # The registry is the application's, so a main window built by an earlier test file leaves
    # its palette command (installed with the window's shortcuts, not by install_shell_commands).
    assert {c.id for c in registry.commands("shell") if not c.id.startswith(TOOL_COMMAND_PREFIX)} - {
        PALETTE_COMMAND} == set(SHELL_ACTIONS)
    shell._shell_busy = True
    shell._window_menu_state = (True, False, False)
    registry.refresh("shell")
    assert not shell.open_settings_action.isEnabled()
    assert shell.open_settings_action.toolTip() == BUSY_REASON
    assert shell.report_problem_action.isEnabled()  # reporting a problem stays possible while busy
    assert shell.detach_current_tab_action.isEnabled() and not shell.attach_all_tools_action.isEnabled()
    shell._shell_busy = False
    registry.refresh("shell")
    shell.open_settings_action.trigger()
    assert calls == ["show_settings"]
    from PySide6.QtCore import QCoreApplication, QEvent

    from cdmw.ui.commands.registry import _ATTRIBUTE

    if getattr(app, _ATTRIBUTE, None) is registry:
        delattr(app, _ATTRIBUTE)
    shell.close()
    shell.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_the_palette_lists_the_context_s_commands_and_runs_one(app):
    from cdmw.ui.commands.palette import CommandPalette

    registry = CommandRegistry()
    ran = []
    registry.register(Command("shell.settings", "Settings", "shell", lambda: ran.append("settings"),
                              keys=("Ctrl+,",)))
    registry.register(Command("browse.extract", "Extract Selected", "browse", lambda: ran.append("extract"),
                              lambda: "Select a file first."))
    registry.register(Command("browse.preview", "Preview Selected", "browse", lambda: ran.append("preview")))
    registry.register(Command("mesh_editor.finish", "Finish Edit Mesh", "mesh_editor", lambda: ran.append("x")))
    palette = CommandPalette(registry, ("browse",))
    try:
        listed = [palette.list.item(i).data(Qt.ItemDataRole.UserRole + 1) for i in range(palette.list.count())]
        assert set(listed) == {"shell.settings", "browse.extract", "browse.preview"}  # no other tool's commands
        assert "Ctrl+," in palette.list.item(listed.index("shell.settings")).text()
        palette.search.setText("prev sel")
        assert palette.list.count() == 1 and palette.current_command_id() == "browse.preview"
        assert palette.run_current() and ran == ["preview"]
        # An unavailable command is listed with its reason and refuses to run.
        palette.search.setText("extract")
        assert palette.reason.text() == "Select a file first."
        assert not palette.run_current() and ran == ["preview"]
    finally:
        palette.deleteLater()
    # The command run last comes first next time.
    again = CommandPalette(registry, ("browse",))
    try:
        assert again.current_command_id() == "browse.preview"
    finally:
        again.deleteLater()


def test_the_palette_chord_from_a_helper_window_opens_the_palette(app, monkeypatch):
    """Keys typed in a helper window never reach Qt, so the helper sends the chord."""
    from types import SimpleNamespace

    from cdmw.ui.commands import palette as palette_module
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab

    opened = []
    monkeypatch.setattr(palette_module, "open_command_palette", opened.append)
    window = object()
    editor = SimpleNamespace(
        standalone_rust_protocol_events=[], standalone_rust_failure_reported=False,
        _validate_rust_event_identity=lambda payload: "app_shortcut", window=lambda: window)
    MeshEditorRustProcessMixin._handle_rust_protocol_event(editor, {"event": "app_shortcut",
                                                                    "command": "command_palette"})
    page = SimpleNamespace(_bridge=SimpleNamespace(session="s1"), window=lambda: window)
    RustNewItemStudioTab._handle_message(page, {"type": "app_shortcut", "session": "s1", "command": "command_palette"})
    assert opened == [window, window]


def test_the_mesh_editor_s_commands_are_mirrored_from_its_helper(app):
    from cdmw.ui.mesh_editor.editor_commands import (
        NOT_READY_REASON,
        clear_helper_commands,
        mirror_helper_commands,
        registry_id,
    )

    registry = CommandRegistry()
    registry.register(Command("mesh_editor.open_file", "Open Mesh...", "mesh_editor", lambda: None))
    sent, state = [], {"ready": True}
    rows = [{"id": "tool.move", "label": "Move", "keys": ["G"], "reason": ""},
            {"id": "page.uv", "label": "UV", "keys": [], "reason": "Authoring is unavailable"},
            {"id": "", "label": "No id"}]
    assert mirror_helper_commands(registry, rows, lambda i: sent.append(i) or True, lambda: state["ready"]) == 2
    move = registry.get(registry_id("tool.move"))
    assert move.helper and move.keys == ("G",) and move.context == "mesh_editor"
    registry.run(move.id)
    assert sent == ["tool.move"]
    assert registry.reason(registry_id("page.uv")) == "Authoring is unavailable"
    state["ready"] = False
    assert registry.reason(move.id) == NOT_READY_REASON
    # A new report replaces the mirrored commands; the tab's own stay.
    mirror_helper_commands(registry, rows[:1], lambda i: True, lambda: True)
    assert registry_id("page.uv") not in registry and "mesh_editor.open_file" in registry
    clear_helper_commands(registry)
    assert [c.id for c in registry.commands("mesh_editor")] == ["mesh_editor.open_file"]


def test_the_texture_editor_s_actions_are_registry_commands(app, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from cdmw.ui.commands import registry as registry_module
    from cdmw.ui.texture_editor_tab import TextureEditorTab
    from cdmw.ui.texture_workflow.editor_commands import NO_IMAGE_REASON, command_id

    registry = CommandRegistry()
    monkeypatch.setattr(registry_module, "command_registry", lambda: registry)
    monkeypatch.setattr("cdmw.ui.texture_workflow.editor_commands.command_registry", lambda: registry)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    editor = TextureEditorTab(settings=settings, base_dir=tmp_path, get_png_root=lambda: str(tmp_path))
    try:
        ids = {c.id for c in registry.commands("texture_editor")}
        # Saved shortcut ids are kept as they were.
        assert {command_id("open_file"), command_id("tool_paint"), command_id("export_dds")} <= ids
        assert registry.get(command_id("open_file")).keys == ("Ctrl+O",)
        assert registry.get(command_id("clear_selection")).keys == ("Ctrl+D", "Escape")
        # No image yet: document commands say why; opening one is possible.
        assert registry.reason(command_id("save_png")) == NO_IMAGE_REASON
        assert registry.available(command_id("open_file"))
        assert not editor.action_export_png.isEnabled()
        assert editor.action_export_png.toolTip() == NO_IMAGE_REASON
        assert editor.action_open_file.property("_cdmw_command_id") == command_id("open_file")
    finally:
        editor.deleteLater()


def test_a_browse_command_shows_its_button_s_state_and_reason(app, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QPushButton

    from cdmw.ui.archive_browser import browse_commands
    from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin

    registry = CommandRegistry()
    monkeypatch.setattr(browse_commands, "command_registry", lambda: registry)
    button = QPushButton("Open in Mesh Editor")
    pressed = []
    button.clicked.connect(lambda: pressed.append(1))
    browser = SimpleNamespace(archive_model_open_mesh_editor_button=button)
    browse_commands.install_browse_commands(browser)
    command = browse_commands.command_id("open_in_mesh_editor")
    assert registry.get(command).label == "Open in Mesh Editor"
    ArchiveBrowserActionMixin._set_action_button_state(button, False, "Open it.", "select a mesh/model archive entry first")
    assert registry.reason(command) == "Select a mesh/model archive entry first"
    assert button.toolTip().startswith("Unavailable: select a mesh")
    ArchiveBrowserActionMixin._set_action_button_state(button, True, "Open it.", "select a mesh")
    assert registry.available(command)
    registry.run(command)
    assert pressed == [1]
    button.deleteLater()


def test_rail_entries_are_commands_with_the_palettes_reason() -> None:
    """P15 step 1: each rail entry runs a registry command; a disabled tool gives one reason everywhere."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.ui.commands.palette import TOOL_CONTEXTS
    from cdmw.ui.commands.registry import CommandRefused, CommandRegistry
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS
    from cdmw.ui.shell.shell_commands import TOOL_UNAVAILABLE_REASON, tool_command_id, tool_commands

    QApplication.instance() or QApplication([])
    opened: list[str] = []
    widgets = {spec.key: QWidget() for spec in COMPACT_TOOL_SPECS}
    shell = SimpleNamespace(_tool_widgets_by_key=widgets, _activate_tool_key=opened.append)
    registry = CommandRegistry()
    registry.register_all(tool_commands(shell))
    assert {command.id for command in registry.commands("shell")} == {tool_command_id(spec.key) for spec in COMPACT_TOOL_SPECS}
    registry.run(tool_command_id("textures"))
    assert opened == ["textures"]
    widgets["mod_management"].setEnabled(False)
    widgets["mod_management"].setToolTip("Mod Management needs its helper, which was not found.")
    assert registry.reason(tool_command_id("mod_management")) == "Mod Management needs its helper, which was not found."
    widgets["research"].setEnabled(False)
    assert registry.reason(tool_command_id("research")) == TOOL_UNAVAILABLE_REASON
    try:
        registry.run(tool_command_id("research"))
    except CommandRefused as refused:
        assert str(refused) == TOOL_UNAVAILABLE_REASON
    else:
        raise AssertionError("a disabled tool's command ran")
    # The palette finds Create New Item's and the Textures tool's commands by their rail keys.
    assert TOOL_CONTEXTS["new_item_studio"] == "new_item" and TOOL_CONTEXTS["textures"] == "texture_editor"
    for widget in widgets.values():
        widget.deleteLater()
