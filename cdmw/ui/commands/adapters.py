"""Views of registry commands: a QAction or a button follows its command (P12 step 2).

A bound view takes its enabled state and tooltip reason from the command, and
running it goes through the registry, so a menu entry, a toolbar button and
the palette show the same state and the same reason.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtGui import QAction

from cdmw.ui.commands.registry import CommandRefused, CommandRegistry

_BOUND = "_cdmw_command_id"


def bind_action(action: QAction, registry: CommandRegistry, command_id: str) -> QAction:
    """Make ``action`` a view of ``command_id``: its state, reason and run come from the registry."""

    command = registry.get(command_id)
    action.setProperty(_BOUND, command_id)
    tooltip = action.toolTip() if action.toolTip() and action.toolTip() != action.text() else ""

    def sync(context: str = "") -> None:
        if context and context != command.context:
            return
        if not shiboken6.isValid(action):
            return
        reason = registry.reason(command_id)
        action.setEnabled(not reason)
        action.setToolTip(reason or tooltip)
        action.setStatusTip(reason)

    def trigger(_checked: bool = False) -> None:
        try:
            registry.run(command_id)
        except CommandRefused:
            sync()

    action.triggered.connect(trigger)
    registry.changed.connect(sync)
    sync()
    return action


def bound_command_id(action: QAction) -> str:
    """The command an action is a view of, or "" for an action outside the registry."""

    value = action.property(_BOUND)
    return str(value or "")
