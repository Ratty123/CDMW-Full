"""P12 step 1 and the shell's part of step 2: one command, one state, one reason."""
from __future__ import annotations

import pytest
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
    assert registry.reason("shell.broken").startswith("Unavailable:")


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
    from cdmw.ui.shell.shell_commands import BUSY_REASON, SHELL_ACTIONS, install_shell_commands
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
    registry = install_shell_commands(shell)
    assert {c.id for c in registry.commands("shell")} == set(SHELL_ACTIONS)
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
