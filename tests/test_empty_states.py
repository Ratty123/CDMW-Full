"""Empty states: one sentence and one button that runs the next step (P11 step 6)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from cdmw.ui.commands.registry import Command, CommandRegistry
from cdmw.ui.empty_states import ActionEmptyState, EmptyStateSwitch


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _registry(ran, reason=lambda: ""):
    registry = CommandRegistry()
    registry.register(Command("shell.settings", "&Settings", "shell", lambda: ran.append("settings"), reason))
    return registry


def test_the_button_runs_the_command_and_takes_its_label(app):
    ran = []
    state = ActionEmptyState("Choose your game folder to start.", "", "shell.settings", registry=_registry(ran))
    assert state.button.text() == "Settings" and state.button.isVisibleTo(state)
    state.button.click()
    assert ran == ["settings"] and state.last_reason == ""


def test_a_command_that_cannot_run_says_why(app):
    ran, blocked = [], ["Wait for the current task to finish."]
    registry = _registry(ran, lambda: blocked[0])
    state = ActionEmptyState("Choose your game folder to start.", "Open Settings", "shell.settings", registry=registry)
    assert not state.button.isEnabled() and state.button.toolTip() == blocked[0]
    blocked[0] = ""
    registry.refresh("shell")
    assert state.button.isEnabled() and state.button.toolTip() == ""


def test_a_page_without_a_command_yet_runs_its_own_step(app):
    ran = []
    state = ActionEmptyState("No textures are queued.", "Add Textures", run=lambda: ran.append("add"), registry=CommandRegistry())
    state.button.click()
    assert ran == ["add"]
    state.set_state("Nothing to show.")
    assert not state.button.isVisibleTo(state)


def test_the_switch_shows_the_content_or_the_state_never_both(app):
    content = QLabel("rows")
    state = ActionEmptyState("Nothing yet.", "Go", run=lambda: None, registry=CommandRegistry())
    switch = EmptyStateSwitch(content, state)
    switch.set_empty(True)
    assert switch.is_empty() and switch.currentWidget() is state
    switch.set_empty(False)
    assert not switch.is_empty() and switch.currentWidget() is content


def test_spacing_follows_the_font(app):
    state = ActionEmptyState("Nothing yet.", "Go", run=lambda: None, registry=CommandRegistry(), density="compact")
    font = state.font()
    font.setPointSizeF(6)
    state.setFont(font)
    small = state.button.minimumHeight()
    font.setPointSizeF(16)
    state.setFont(font)
    assert state.button.minimumHeight() > small
