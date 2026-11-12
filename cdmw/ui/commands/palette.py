"""The command palette (P12 step 3): every command of the current context, searchable.

Ctrl+Shift+P opens it, as in CDMW Next. It lists the shell's commands and the
active tool's, recent ones first, each with its keys; an unavailable command
is shown with its reason and does not run. Labels are shown and searched in
the interface language as well as in English.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from cdmw.ui.commands.registry import Command, CommandRefused, CommandRegistry

PALETTE_KEYS = "Ctrl+Shift+P"
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
                 *, keys_for=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
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
            label = _translate(command.label).replace("&", "")
            reason = self.registry.reason(command.id)
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
        self.reason.setText(self.registry.reason(command_id) if command_id else "")

    def current_command_id(self) -> str:
        item = self.list.currentItem()
        return str(item.data(_COMMAND_ROLE) or "") if item is not None else ""

    # ----- running ---------------------------------------------------------
    def run_current(self) -> bool:
        command_id = self.current_command_id()
        if not command_id:
            return False
        try:
            self.registry.run(command_id)
        except CommandRefused as exc:
            self.reason.setText(str(exc))
            return False
        self.command_run.emit(command_id)
        self.accept()
        return True

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


def open_command_palette(shell) -> CommandPalette | None:
    registry = getattr(shell, "command_registry", None)
    if not isinstance(registry, CommandRegistry):
        return None
    previous = getattr(shell, "_command_palette", None)
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass
    palette = CommandPalette(registry, current_contexts(shell), shell)
    shell._command_palette = palette
    geometry = shell.geometry()
    palette.move(geometry.x() + (geometry.width() - palette.width()) // 2, geometry.y() + 80)
    palette.show()
    palette.search.setFocus()
    return palette


def install_command_palette(shell) -> QShortcut:
    """Ctrl+Shift+P anywhere in the app's own windows opens the palette."""

    shortcut = QShortcut(QKeySequence(PALETTE_KEYS), shell)
    shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
    shortcut.activated.connect(lambda: open_command_palette(shell))
    shell.command_palette_shortcut = shortcut
    return shortcut
