"""Menus for the generic tools: a control's context menu or a button's drop-down, without showing it.

``app.ui_act`` with ``action: "menu"`` reads or picks an entry of the menu a
control would show:

* a button with a menu (``QPushButton.menu()``, ``QToolButton.menu()``) gives
  that menu, after its ``aboutToShow`` has filled it, as opening it does;
* a menu bar gives its menus;
* a control whose policy is ``ActionsContextMenu`` gives its actions;
* any other control is sent the context-menu event a right-click sends, at
  the named row of a list, table or tree (selected first, as a right-click
  selects it) or at the middle of the control. While it is handled,
  ``QMenu.exec`` and ``QMenu.popup`` are captured: the menu the app builds is
  read instead of shown.

Without an entry the menu's entries come back (text, enabled, checked,
tooltip, submenus) and nothing runs. With one, the entry is triggered where
the app expects it: inside the captured ``exec``, which then returns it, so
code that reads the returned action and code that listens to ``triggered``
both run as for the user's click. A disabled entry is refused with its
tooltip as the reason.

UI thread only.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ

#: An entry whose label holds one of these writes a file, or deletes something.
MENU_OUTPUT_WORDS = ("export", "extract", "save", "build", "write", "download", "generate")
MENU_DESTRUCTIVE_WORDS = ("delete", "remove", "unbind")
MAX_ENTRIES = 200
_SEPARATORS = (">", "›")


def clean_label(text: object) -> str:
    """A menu label as read: no accelerator marks, no shortcut after a tab, no trailing ellipsis."""

    label = str(text or "").split("\t", 1)[0].replace("&&", "\0").replace("&", "").replace("\0", "&")
    label = " ".join(label.split())
    for tail in ("...", "…"):
        if label.endswith(tail):
            label = label[: -len(tail)].rstrip()
    return label


def menu_path(text: object) -> list[str]:
    """``"Export > Batch Export Selected Models as GLB..."`` as its entries."""

    raw = str(text or "")
    for separator in _SEPARATORS[1:]:
        raw = raw.replace(separator, _SEPARATORS[0])
    parts = [clean_label(part) for part in raw.split(_SEPARATORS[0])]
    if not all(parts):
        raise ToolError(INVALID_ARGUMENTS, "menu names an entry by its text, or a path such as 'Export > "
                                           "Export File'.")
    return parts


# ----- reading a menu ------------------------------------------------------------------------
def _fill(menu) -> None:
    """What opening the menu does first: menus built on ``aboutToShow`` fill themselves."""

    try:
        menu.aboutToShow.emit()
    except RuntimeError:
        pass


def _visible_actions(actions) -> list:
    return [action for action in actions if action is not None and action.isVisible() and not action.isSeparator()]


def describe_entries(actions, depth: int = 0) -> list[dict[str, object]]:
    rows = []
    for action in _visible_actions(actions)[:MAX_ENTRIES]:
        row: dict[str, object] = {"text": clean_label(action.text()) or clean_label(action.iconText())}
        if not action.isEnabled():
            row["enabled"] = False
        if action.isCheckable():
            row["checked"] = action.isChecked()
        tip = " ".join(str(action.toolTip() or action.statusTip() or "").split())
        if tip and clean_label(tip) != row["text"]:
            row["tip"] = tip[:300]
        submenu = action.menu()
        if submenu is not None and depth < 4:
            _fill(submenu)
            row["entries"] = describe_entries(submenu.actions(), depth + 1)
        rows.append(row)
    return rows


def find_entry(actions, path: list[str]):
    """The action at ``path`` (each part matched by its label, then by a label that starts with it)."""

    current = list(actions)
    found = None
    for depth, part in enumerate(path):
        wanted = part.casefold()
        shown = _visible_actions(current)
        labels = [clean_label(action.text()).casefold() for action in shown]
        matches = [action for action, label in zip(shown, labels) if label == wanted]
        if not matches:
            matches = [action for action, label in zip(shown, labels) if label.startswith(wanted)]
        if not matches:
            where = " > ".join(path[:depth]) or "the menu"
            known = ", ".join(clean_label(action.text()) for action in shown) or "nothing"
            raise ToolError(NOT_FOUND, f"{where} has no entry {part!r}. It has: {known}.")
        found = matches[0]
        if depth < len(path) - 1:
            submenu = found.menu()
            if submenu is None:
                raise ToolError(NOT_FOUND, f"{clean_label(found.text())!r} has no submenu.")
            _fill(submenu)
            current = submenu.actions()
    return found


def refusal(action) -> str:
    """Why ``action`` cannot run now, or ""."""

    if action.isEnabled():
        if action.menu() is not None:
            return f"{clean_label(action.text())!r} opens a submenu; name one of its entries."
        return ""
    tip = " ".join(str(action.toolTip() or action.statusTip() or "").split())
    if tip and clean_label(tip) != clean_label(action.text()):
        return tip
    return f"{clean_label(action.text())!r} is disabled now."


# ----- classes -----------------------------------------------------------------------------
def _command_for(label: str):
    from cdmw.ui.commands.registry import command_registry, display_label

    registry = command_registry()
    if registry is None:
        return None
    wanted = clean_label(label).casefold()
    for command in registry.commands():
        if clean_label(display_label(command.label)).casefold() == wanted:
            return command
    return None


def entry_user_only(path: list[str]) -> bool:
    from cdmw.mcp.classification import USER_ONLY_COMMANDS

    command = _command_for(path[-1]) if path else None
    return command is not None and command.id in USER_ONLY_COMMANDS


def entry_effect(path: list[str] | None) -> str:
    """The class of picking the entry at ``path``: its registry command's class when there is one,
    otherwise the label's words (export, extract, save, build or write: output; delete or remove:
    destructive; anything else: edit). Reading a menu is a read."""

    if not path:
        return READ
    command = _command_for(path[-1])
    if command is not None:
        from cdmw.mcp.control_tools import command_effect

        return command_effect(command)
    words = [word.strip(".:,()") for word in path[-1].casefold().split()]
    if any(word in MENU_DESTRUCTIVE_WORDS for word in words):
        return DESTRUCTIVE
    if any(word in MENU_OUTPUT_WORDS for word in words):
        return OUTPUT
    return EDIT


# ----- capturing the menu the app builds ----------------------------------------------------
class _Capture:
    """While inside, a menu the app opens (``QMenu.exec``, ``QMenu.popup``) is caught as it is shown:
    its entries are read, then it is closed, or the entry is picked with the keys a user would press
    (Right into each submenu, Return on the entry). Picking by keys keeps Qt's own semantics:
    ``triggered`` is emitted and ``exec`` returns the entry, as for a click.

    ``QMenu.exec`` cannot be replaced from Python (it is both a static and an instance method), so
    the menu is caught by an application event filter instead.
    """

    #: Seconds after which any menu still open is closed, whatever happened.
    GIVE_UP_S = 5.0

    def __init__(self, path: list[str] | None):
        self.path = path
        self.menus: list[tuple[list, object]] = []
        self.picked_text = ""
        self.error: ToolError | None = None
        self.done = False
        self._depth = 0
        self._shows = 0
        self._gone: set[int] = set()
        self._filter = None

    def _shown(self, menu) -> None:
        import shiboken6
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMenu

        self._shows += 1
        # The filter's wrapper of a menu C++ made (a submenu) does not outlive the call: keep its address.
        address = shiboken6.getCppPointer(menu)[0]
        menu.destroyed.connect(lambda *_: self._gone.add(address))

        def later(work) -> None:
            def run() -> None:
                if address not in self._gone:
                    work(shiboken6.wrapInstance(address, QMenu))

            QTimer.singleShot(0, run)

        if self.done or (self._depth == 0 and self.menus):
            # A menu the picked entry's handler opens, or a second one at the same right-click,
            # is not shown either.
            later(lambda shown: shown.close())
            return
        if self._depth == 0:
            # Read now: a menu built for one right-click may be gone once it closes.
            self.menus.append((describe_entries(menu.actions()), None))
        later(self._step)

    def _step(self, menu) -> None:
        import shiboken6
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        if not shiboken6.isValid(menu):
            return
        if self.path is None:
            self.done = True
            menu.close()
            return
        try:
            action = find_entry(menu.actions(), [self.path[self._depth]])
            leaf = self._depth == len(self.path) - 1
            why = refusal(action) if leaf else ("" if action.isEnabled() else refusal(action))
            if why:
                raise ToolError(UNAVAILABLE if action.menu() is None or not leaf else NOT_FOUND, why)
            if not leaf and action.menu() is None:
                raise ToolError(NOT_FOUND, f"{clean_label(action.text())!r} has no submenu.")
        except ToolError as error:
            self.error = error
            self.done = True
            self._close_all()
            return
        if leaf:
            self.done = True
            self.picked_text = clean_label(action.text())
            menu.setActiveAction(action)
            key = Qt.Key.Key_Return
        else:
            self._depth += 1  # first: making a submenu's entry active may show the submenu at once
            shown = self._shows
            menu.setActiveAction(action)
            if self._shows != shown:
                return
            key = Qt.Key.Key_Right
        QApplication.sendEvent(menu, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    def _close_all(self) -> None:
        from PySide6.QtWidgets import QApplication

        for _ in range(16):
            popup = QApplication.activePopupWidget()
            if popup is None:
                return
            popup.close()

    def __enter__(self):
        from PySide6.QtCore import QEvent, QObject, QTimer
        from PySide6.QtWidgets import QApplication, QMenu

        capture = self

        class _Filter(QObject):
            def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
                if event.type() == QEvent.Type.Show and isinstance(watched, QMenu):
                    capture._shown(watched)
                return False

        self._filter = _Filter()
        QApplication.instance().installEventFilter(self._filter)
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._give_up)
        self._timer.start(int(self.GIVE_UP_S * 1000))
        return self

    def _give_up(self) -> None:
        if not self.done:
            self.error = ToolError(UNAVAILABLE, "The menu did not answer in time; it was closed.")
            self.done = True
        self._close_all()

    def settle(self) -> None:
        """For a menu opened with ``popup`` (it does not wait), run events until it is handled."""

        import time

        from PySide6.QtWidgets import QApplication

        deadline = time.monotonic() + self.GIVE_UP_S + 1
        while self.menus and not self.done and time.monotonic() < deadline:
            QApplication.processEvents()
        QApplication.processEvents()

    def __exit__(self, *_exc):
        from PySide6.QtWidgets import QApplication

        self._timer.stop()
        QApplication.instance().removeEventFilter(self._filter)
        self._filter = None


def _select_row(view, row):
    """Select the row a right-click lands on, as the view's own mouse handling does; its index."""

    from PySide6.QtCore import QItemSelectionModel

    from cdmw.mcp.ui_tree import _index_of_row

    index = _index_of_row(view, row)
    view.scrollTo(index)
    selection = view.selectionModel()
    if selection is not None and not selection.isSelected(index):
        flags = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
        selection.setCurrentIndex(index, flags)
    return index


def _send_context_menu(widget, row) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QApplication

    target = widget
    if isinstance(widget, QAbstractItemView):
        if row is not None:
            index = _select_row(widget, row)
            position = widget.visualRect(index).center()
        else:
            position = widget.viewport().rect().center()
        target = widget.viewport()
    elif row is not None:
        raise ToolError(INVALID_ARGUMENTS, "row applies to a list, table or tree.")
    else:
        if isinstance(widget, QAbstractScrollArea):
            target = widget.viewport()
        position = target.rect().center()
    if widget.contextMenuPolicy() == Qt.ContextMenuPolicy.PreventContextMenu:
        raise ToolError(UNAVAILABLE, "This control has no menu.")
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, target.mapToGlobal(position))
    QApplication.sendEvent(target, event)


def _own_menu(widget):
    """The actions of a menu the control holds itself, or None when it must be asked by right-click."""

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenuBar, QPushButton, QToolButton

    if isinstance(widget, (QPushButton, QToolButton)) and widget.menu() is not None:
        menu = widget.menu()
        _fill(menu)
        return menu.actions(), menu
    if isinstance(widget, QMenuBar):
        return widget.actions(), None
    if widget.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu:
        return widget.actions(), None
    return None


def act_menu(widget, entry: object = None, row: object = None) -> dict[str, object]:
    """List the control's menu, or pick ``entry`` from it. UI thread."""

    path = menu_path(entry) if entry not in (None, "") else None
    if path and entry_user_only(path):
        from cdmw.mcp.ui_tree import USER_ONLY_MESSAGE

        raise ToolError(REFUSED, USER_ONLY_MESSAGE)
    own = _own_menu(widget) if row is None else None
    if own is not None:
        actions, menu = own
        if path is None:
            return {"entries": describe_entries(actions)}
        action = find_entry(actions, path)
        why = refusal(action)
        if why:
            raise ToolError(UNAVAILABLE, why)
        action.trigger()
        if menu is not None:
            menu.triggered.emit(action)
        return {"picked": " > ".join(path[:-1] + [clean_label(action.text())])}
    with _Capture(path) as capture:
        _send_context_menu(widget, row)
        capture.settle()
    if not capture.menus:
        raise ToolError(UNAVAILABLE, "This control showed no menu here." if row is None else
                        f"Row {row!r} showed no menu.")
    if capture.error is not None:
        raise capture.error
    if path is None:
        return {"entries": capture.menus[0][0]}
    return {"picked": " > ".join(path[:-1] + [capture.picked_text])}


__all__ = ["act_menu", "clean_label", "describe_entries", "entry_effect", "entry_user_only", "find_entry",
           "menu_path"]
