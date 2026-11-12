"""The command palette (P12 step 3): every command of the current context, searchable.

Ctrl+Shift+P opens it by default, as in CDMW Next. It lists the shell's commands and the
active tool's, recent ones first, each with its keys; an unavailable command
is shown with its reason and does not run. Labels are shown and searched in
the interface language as well as in English.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from cdmw.ui.commands.registry import UNAVAILABLE_REASON, Command, CommandRegistry, display_label

PALETTE_KEYS = "Ctrl+Shift+P"
PALETTE_COMMAND = "shell.command_palette"
PALETTE_LABEL = "Command Palette"
#: Tool key in the shell -> command context.
TOOL_CONTEXTS = {
    "archive_browser": "browse",
    "mesh_editor": "mesh_editor",
    "texture_editor": "texture_editor",
    "new_item": "new_item",
    "new_item_studio": "new_item",
    "textures": "texture_editor",
    "mod_management": "mod_management",
}
_COMMAND_ROLE = Qt.ItemDataRole.UserRole + 1


def _translate(text: str) -> str:
    try:
        from cdmw.ui.localization import _active_ui_localizer

        localizer = _active_ui_localizer()
        return str(localizer.translate(text)) if localizer is not None else text
    except Exception:
        return text


class CommandPalette(QDialog):
    """A searchable list of the registry's commands for a context."""

    command_run = Signal(str)

    def __init__(self, registry: CommandRegistry, contexts: tuple[str, ...], parent: QWidget | None = None,
                 *, keys_for=None, popup: bool = True) -> None:
        # A popup takes the keyboard only while the app is the foreground one; opened
        # from a helper's window it is a frameless tool window that asks for focus and
        # closes when it loses it, as the popup closes on a click outside.
        flags = Qt.WindowType.Popup if popup else Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags | Qt.WindowType.FramelessWindowHint)
        self._closes_on_deactivate = not popup
        self.setObjectName("CommandPalette")
        self.registry = registry
        self.contexts = tuple(dict.fromkeys(("shell", *contexts)))
        self._keys_for = keys_for or (lambda command: command.keys)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.search = QLineEdit(self)
        self.search.setObjectName("CommandPaletteSearch")
        self.search.setPlaceholderText("Type a command")
        self.list = QListWidget(self)
        self.list.setObjectName("CommandPaletteList")
        self.reason = QLabel(self)
        self.reason.setObjectName("CommandPaletteReason")
        self.reason.setWordWrap(True)
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        layout.addWidget(self.reason)
        self.search.textChanged.connect(self.refill)
        self.search.returnPressed.connect(self.run_current)
        self.list.itemActivated.connect(lambda _item: self.run_current())
        self.list.currentItemChanged.connect(self._show_reason)
        self.search.installEventFilter(self)
        self.resize(560, 420)
        self.refill()

    # ----- content -----------------------------------------------------------
    def ordered_commands(self) -> list[Command]:
        commands = self.registry.commands(*self.contexts)
        recent = {command_id: rank for rank, command_id in enumerate(self.registry.recent())}
        return sorted(commands, key=lambda c: (recent.get(c.id, len(recent)), self.contexts.index(c.context)
                                                if c.context in self.contexts else 99, _translate(c.label).casefold()))

    def matches(self, command: Command, text: str) -> bool:
        words = [w for w in text.casefold().split() if w]
        haystack = " ".join((command.label, _translate(command.label), command.id, *command.keywords)).casefold()
        return all(word in haystack for word in words)

    def refill(self, _text: str = "") -> None:
        text = self.search.text()
        self.list.clear()
        for command in self.ordered_commands():
            if not self.matches(command, text):
                continue
            keys = ", ".join(self._keys_for(command))
            label = display_label(_translate(command.label))
            reason = self._reason(command.id)
            item = QListWidgetItem(f"{label}\t{keys}" if keys else label)
            item.setData(_COMMAND_ROLE, command.id)
            item.setToolTip(reason or command.id)
            if reason:
                # Still selectable, so its reason shows; running it is refused.
                item.setForeground(self.palette().color(self.palette().ColorGroup.Disabled,
                                                        self.palette().ColorRole.Text))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._show_reason()

    def _show_reason(self, *_args) -> None:
        command_id = self.current_command_id()
        self.reason.setText(_translate(self._reason(command_id)) if command_id else "")

    def _reason(self, command_id: str) -> str:
        try:
            return self.registry.reason(command_id)
        except KeyError:  # a helper's mirror was replaced while the palette was open
            return UNAVAILABLE_REASON

    def current_command_id(self) -> str:
        item = self.list.currentItem()
        return str(item.data(_COMMAND_ROLE) or "") if item is not None else ""

    # ----- running ---------------------------------------------------------
    def run_current(self) -> bool:
        command_id = self.current_command_id()
        if not command_id:
            return False
        refusal = self.registry.run_or_reason(command_id)
        if refusal:
            self.reason.setText(_translate(refusal))
            return False
        self.command_run.emit(command_id)
        self.accept()
        return True

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent

        if (self._closes_on_deactivate and event.type() == QEvent.Type.ActivationChange
                and not self.isActiveWindow() and self.isVisible()):
            self.reject()
        super().changeEvent(event)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent

        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
                self.list.setCurrentRow(row)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)


def current_contexts(shell) -> tuple[str, ...]:
    """The active tool's command context, besides the shell's."""

    try:
        key = shell._tool_key_for_widget(shell._current_navigation_widget())
    except Exception:
        key = ""
    context = TOOL_CONTEXTS.get(str(key or ""), "")
    return (context,) if context else ()


def keymap_keys(registry: CommandRegistry, shell):
    """Each command's keys as the keymap has them now (a command's ``keys`` are its defaults)."""

    settings = getattr(shell, "settings", None)
    if settings is None:
        return None
    from cdmw.ui.commands.keymap import keymap_rows

    keys = {row.command_id: row.keys for row in keymap_rows(registry, settings)}
    return lambda command: keys.get(command.id, command.keys)


def _shell_and_host(window):
    """The main window that owns the registry, and the window the palette opens over.

    ``window`` is the main window (its shortcut) or a tool's own window: a
    detached tool window when a helper inside it sent the palette chord. A
    shortcut pressed in a detached window reaches the main window's command, so
    the active window decides there.
    """

    shell = window if isinstance(getattr(window, "command_registry", None), CommandRegistry) else None
    if shell is None:
        owner = getattr(window, "owner", None)
        if isinstance(getattr(owner, "command_registry", None), CommandRegistry):
            shell, host = owner, window
            return shell, host
        return None, None
    host = shell
    try:
        from PySide6.QtWidgets import QApplication

        active = QApplication.activeWindow()
    except RuntimeError:
        active = None
    if active is not None and active is not shell and getattr(active, "owner", None) is shell:
        host = active
    return shell, host


def open_command_palette(window) -> CommandPalette | None:
    shell, host = _shell_and_host(window)
    if shell is None:
        return None
    registry = shell.command_registry
    previous = getattr(shell, "_command_palette", None)
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass
    tool_key = getattr(host, "tool_key", "") if host is not shell else ""
    contexts = ((TOOL_CONTEXTS[tool_key],) if tool_key in TOOL_CONTEXTS else ()) if tool_key else current_contexts(shell)
    from PySide6.QtWidgets import QApplication

    foreground = QApplication.applicationState() == Qt.ApplicationState.ApplicationActive
    palette = CommandPalette(registry, contexts, host, keys_for=keymap_keys(registry, shell), popup=foreground)
    shell._command_palette = palette
    geometry = host.geometry()
    palette.move(geometry.x() + (geometry.width() - palette.width()) // 2, geometry.y() + 80)
    palette.show()
    # Opened from a helper's window, the app is not the foreground one: a popup
    # would get no keys. Ask for activation so typing reaches the search field.
    palette.raise_()
    palette.activateWindow()
    palette.search.setFocus()
    return palette


def install_command_palette(shell) -> Command | None:
    """The palette is a shell command (``shell.command_palette``), Ctrl+Shift+P by default.

    Its key is a keymap row like any other: it can be rebound in Settings >
    Shortcuts, conflicts see it, and ``QtShortcutBinder`` binds it in every
    window of the app. (The Mesh Editor helper still reserves Ctrl+Shift+P
    itself; following the keymap there is the helper's part, see plan 8.7 E5.)
    """

    registry = getattr(shell, "command_registry", None)
    if not isinstance(registry, CommandRegistry):
        return None
    command = Command(PALETTE_COMMAND, PALETTE_LABEL, "shell", lambda: open_command_palette(shell),
                      keys=(PALETTE_KEYS,), keywords=("palette", "commands", "search"))
    return registry.register(command, replace=True)
