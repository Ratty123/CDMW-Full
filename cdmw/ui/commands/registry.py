"""One definition per action (P12 step 1).

A command has an id, a label (its English text, which is also its
localization key), the context it belongs to, default keys, an availability
check that returns the reason it cannot run (empty when it can), and the call
that runs it. Menus, toolbars, buttons, the palette and shortcuts all reach an
action through its command, so they share its label, state and reason.

The registry never runs slow work itself: a command's call starts the same
worker its button always started.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QObject, Signal

from cdmw.mcp.names import DEFAULT_EFFECT, EFFECT_CLASSES, reserved_prefix

#: Where a command applies. ``shell`` commands are available everywhere.
CONTEXTS = ("shell", "browse", "mesh_editor", "texture_editor", "new_item", "mod_management")
RECENT_LIMIT = 12
UNAVAILABLE_REASON = "Unavailable"
COMMAND_FAILED_REASON = "The command failed. The log has the details."
_LOGGER = logging.getLogger(__name__)


def _always() -> str:
    return ""


def display_label(label: str) -> str:
    """A label as plain text: "&&" and an "&" before a space are ampersands; "&" before a letter marks a mnemonic."""

    return re.sub(r"&(&|(?=[^\s&]))", lambda match: match.group(1), str(label or ""))


class CommandDefinitionError(ValueError):
    """A command was defined wrongly: a programming error, not a message for users."""


@dataclass(frozen=True, slots=True)
class Command:
    id: str
    label: str
    context: str
    run: Callable[[], object]
    reason: Callable[[], str] = _always
    keys: tuple[str, ...] = ()
    icon: str = ""
    #: Drawn by a helper process and mirrored here (P12 step 2); run sends its id to the helper.
    helper: bool = False
    #: Words the palette also matches, besides the label.
    keywords: tuple[str, ...] = field(default_factory=tuple)
    #: What running it can change, for AI connections (P13 stage C): read,
    #: edit, destructive or output. A command that does not say is an edit.
    effect: str = DEFAULT_EFFECT

    def __post_init__(self) -> None:
        if not self.id or "." not in self.id:
            raise CommandDefinitionError(f"A command id names its area and action, such as shell.settings: {self.id!r}")
        if reserved_prefix(self.id):
            raise CommandDefinitionError(
                f"Command ids may not start with {reserved_prefix(self.id)!r}; typed AI tools use it: {self.id}")
        if self.effect not in EFFECT_CLASSES:
            raise CommandDefinitionError(f"Unknown effect class {self.effect!r} for {self.id}")
        if self.context not in CONTEXTS:
            raise CommandDefinitionError(f"Unknown command context {self.context!r} for {self.id}")
        if not self.label.strip():
            raise CommandDefinitionError(f"Command {self.id} needs a label")


class CommandRefused(RuntimeError):
    """A command was asked to run while unavailable; the message is its reason."""


class CommandRegistry(QObject):
    """The application's commands. ``changed`` carries the context that changed ("" for all)."""

    changed = Signal(str)
    ran = Signal(str)
    #: A key was rebound, unbound or reset; every place that binds keys reads the keymap again.
    keymap_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._commands: dict[str, Command] = {}
        self._recent: list[str] = []

    # ----- definitions -------------------------------------------------------
    def register(self, command: Command, *, replace: bool = False) -> Command:
        if command.id in self._commands and not replace:
            raise CommandDefinitionError(f"Command {command.id} is already registered")
        self._commands[command.id] = command
        self.changed.emit(command.context)
        return command

    def register_all(self, commands: Iterable[Command], *, replace: bool = False) -> None:
        for command in commands:
            self.register(command, replace=replace)

    def replace_helper_commands(self, context: str, commands: Iterable[Command]) -> None:
        """Replace the commands a helper process mirrors for ``context``; others stay."""

        for command_id in [i for i, c in self._commands.items() if c.context == context and c.helper]:
            del self._commands[command_id]
        for command in commands:
            if command.context != context or not command.helper:
                raise CommandDefinitionError(f"{command.id} is not a {context} helper command")
            self._commands[command.id] = command
        self.changed.emit(context)

    def unregister_context(self, context: str) -> None:
        for command_id in [i for i, c in self._commands.items() if c.context == context]:
            del self._commands[command_id]
        self.changed.emit(context)

    def get(self, command_id: str) -> Command:
        try:
            return self._commands[command_id]
        except KeyError:
            raise KeyError(f"No command {command_id}") from None

    def __contains__(self, command_id: object) -> bool:
        return command_id in self._commands

    def commands(self, *contexts: str) -> list[Command]:
        wanted = set(contexts)
        return [c for c in self._commands.values() if not wanted or c.context in wanted]

    # ----- state ---------------------------------------------------------------
    def reason(self, command_id: str) -> str:
        """Why the command cannot run now, or "" when it can."""

        command = self.get(command_id)
        try:
            return str(command.reason() or "")
        except Exception:  # a broken check must not break the menu that asks
            # The exception's own text is for the log, not for the user (plan 8.7 E8).
            _LOGGER.exception("The availability check of %s failed", command_id)
            return UNAVAILABLE_REASON

    def available(self, command_id: str) -> bool:
        return not self.reason(command_id)

    def refresh(self, context: str = "") -> None:
        """Ask every view of these commands to read their state again."""

        self.changed.emit(context)

    # ----- running ---------------------------------------------------------
    def run(self, command_id: str) -> object:
        reason = self.reason(command_id)
        if reason:
            raise CommandRefused(reason)
        command = self.get(command_id)
        result = command.run()
        self._recent = [command_id, *[i for i in self._recent if i != command_id]][:RECENT_LIMIT]
        self.ran.emit(command_id)
        return result

    def run_or_reason(self, command_id: str) -> str:
        """Run a command for a menu, the palette or a key: "" when it ran, else why it did not.

        A refusal gives the command's reason; a command that is gone (a helper's
        mirror was replaced) or that raised gives a fixed text, and the error goes
        to the log. Nothing escapes into the Qt slot that called it (plan 8.7 E9).
        """

        try:
            self.run(command_id)
        except CommandRefused as exc:
            return str(exc)
        except KeyError:
            return UNAVAILABLE_REASON
        except Exception:
            _LOGGER.exception("Command %s failed", command_id)
            return COMMAND_FAILED_REASON
        return ""

    def recent(self) -> list[str]:
        return [i for i in self._recent if i in self._commands]


_ATTRIBUTE = "_cdmw_command_registry"


def command_registry() -> CommandRegistry | None:
    """The application's registry (one per application), created on first use."""

    import shiboken6

    app = QCoreApplication.instance()
    if app is None:
        return None
    registry = getattr(app, _ATTRIBUTE, None)
    # A main window owns its registry; once that window is gone, start a new one.
    if registry is None or not shiboken6.isValid(registry):
        registry = CommandRegistry(app)
        setattr(app, _ATTRIBUTE, registry)
    return registry
