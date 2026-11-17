"""The interface as an AI tool reads and drives it: the controls of a window, each with an id.

``describe_tree`` lists the visible controls under a window, a dialog or one
widget: what kind each is, its text, value and state, and for lists, tables
and trees their rows. ``act`` does to one control what a click or a key press
does, through the control's own signals, so the handler that runs is the one
the user's click runs.

Controls only the user may touch are refused whatever the approval: anything
inside Settings > AI connections or the approval prompt (a tool never answers
its own question), the game folder's field and buttons, and
the buttons of the commands in ``classification.USER_ONLY_COMMANDS``.

UI thread only. Widgets drawn by a helper process (the Mesh Editor's and
Browse's 3D views) are not Qt widgets and do not appear here; their commands
are in the registry.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ

ROWS_SHOWN = 30
MAX_ROWS = 500
TEXT_LIMIT = 2000
ACTIONS = ("click", "set_text", "set_value", "check", "uncheck", "select", "activate", "focus")
#: A button whose text starts with one of these writes a file or deletes something.
OUTPUT_WORDS = ("build", "export", "save", "extract", "combine", "create", "write", "pack", "send", "generate")
DESTRUCTIVE_WORDS = ("delete", "remove", "discard", "clear", "reset", "uninstall", "revert")
USER_ONLY_MESSAGE = ("Only you can use this control in CDMW: AI connections, their approvals, Full access, the "
                     "game folder and what writes into the game are never driven by a tool.")
#: ``window.archive`` attributes that set the game folder, and the two buttons that
#: write into it (remove what an older CDMW installed, restore a backup).
_USER_ONLY_CONTROLS = ("archive_package_root_edit", "archive_package_root_browse_button",
                       "archive_package_root_detect_button", "archive_remove_old_install_button",
                       "archive_restore_patch_backup_button")
#: Windows whose every control is the user's: the AI settings, the approval question, and
#: the first-run dialog that sets the game folder.
_USER_ONLY_WINDOWS = ("AiConnectionsSettingsSection", "ApprovalPrompt", "StartupArchivePathDialog")

_IDS: dict[int, object] = {}
_NUMBERS: dict[int, int] = {}
_NEXT = [0]


def _valid(widget) -> bool:
    import shiboken6

    return widget is not None and shiboken6.isValid(widget)


def widget_id(widget) -> str:
    """The id a tool names this widget by; the same widget keeps its id while it lives."""

    number = _NUMBERS.get(id(widget))
    if number is None or _IDS.get(number) is not widget:
        if len(_IDS) > 20000:
            for stale in [key for key, value in _IDS.items() if not _valid(value)]:
                _NUMBERS.pop(id(_IDS.pop(stale)), None)
        _NEXT[0] += 1
        number = _NEXT[0]
        _IDS[number] = widget
        _NUMBERS[id(widget)] = number
    return f"w{number}"


def widget_by_id(text: str):
    try:
        widget = _IDS.get(int(str(text or "").lstrip("w")))
    except ValueError:
        widget = None
    if not _valid(widget):
        raise ToolError(NOT_FOUND, f"There is no control {text} now. Call app_ui for the controls shown.")
    return widget


def _clean(text: object) -> str:
    from cdmw.ui.commands.registry import display_label

    return display_label(" ".join(str(text or "").split()))[:TEXT_LIMIT]


def kind_of(widget) -> str:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
                                   QCheckBox, QComboBox, QDialog, QGroupBox, QLabel, QLineEdit, QListView,
                                   QMainWindow, QPlainTextEdit, QProgressBar, QRadioButton, QTabBar, QTabWidget,
                                   QTableView, QTextEdit, QTreeView)

    if isinstance(widget, (QCheckBox,)):
        return "check"
    if isinstance(widget, QRadioButton):
        return "radio"
    if isinstance(widget, QAbstractButton):
        return "check" if widget.isCheckable() else "button"
    if isinstance(widget, QComboBox):
        return "choice"
    if isinstance(widget, QLineEdit):
        return "field"
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return "text"
    if isinstance(widget, QAbstractSpinBox):
        return "number"
    if isinstance(widget, QAbstractSlider):
        return "slider"
    if isinstance(widget, (QTabWidget, QTabBar)):
        return "tabs"
    if isinstance(widget, QTreeView):
        return "tree"
    if isinstance(widget, QTableView):
        return "table"
    if isinstance(widget, (QListView, QAbstractItemView)):
        return "list"
    if isinstance(widget, QLabel):
        return "label"
    if isinstance(widget, QProgressBar):
        return "progress"
    if isinstance(widget, QGroupBox):
        return "group"
    if isinstance(widget, QDialog):
        return "dialog"
    if isinstance(widget, QMainWindow):
        return "window"
    return ""


_LEAVES = ("choice", "field", "text", "number", "slider", "tree", "table", "list", "button", "check", "radio",
           "label", "progress")


def _columns(model, parent=None) -> int:
    """How many columns to read: a list's model keeps its column count to itself."""

    try:
        count = model.columnCount(parent) if parent is not None else model.columnCount()
    except (RuntimeError, TypeError):
        return 1
    return max(1, min(int(count), 12))


# ----- rows -------------------------------------------------------------------------------
def _model_rows(view, offset: int, limit: int) -> tuple[list[dict[str, object]], int]:
    """The view's rows as shown, depth first for a tree: (rows from ``offset``, how many in all)."""

    from PySide6.QtCore import QModelIndex, Qt
    from PySide6.QtWidgets import QTreeView

    model = view.model()
    if model is None:
        return [], 0
    rows: list[dict[str, object]] = []
    total = 0
    selection = view.selectionModel()
    tree = isinstance(view, QTreeView)

    def walk(parent, depth: int) -> None:
        nonlocal total
        for row in range(model.rowCount(parent)):
            if total >= offset + MAX_ROWS * 40:
                return
            index = model.index(row, 0, parent)
            if offset <= total < offset + limit:
                cells = []
                for column in range(_columns(model, parent)):
                    if hasattr(view, "isColumnHidden") and view.isColumnHidden(column):
                        continue
                    cells.append(_clean(model.index(row, column, parent).data(Qt.ItemDataRole.DisplayRole)))
                entry: dict[str, object] = {"row": total, "cells": cells}
                if depth:
                    entry["depth"] = depth
                check = index.data(Qt.ItemDataRole.CheckStateRole)
                if check is not None:
                    entry["checked"] = check in (Qt.CheckState.Checked, 2)
                if selection is not None and selection.isSelected(index):
                    entry["selected"] = True
                rows.append(entry)
            total += 1
            if tree and model.hasChildren(index) and view.isExpanded(index):
                walk(index, depth + 1)

    walk(QModelIndex(), 0)
    return rows, total


def _index_of_row(view, wanted: object):
    """The model index of a row given by its number (as listed) or by text in any of its cells."""

    from PySide6.QtCore import QModelIndex, Qt
    from PySide6.QtWidgets import QTreeView

    model = view.model()
    if model is None:
        raise ToolError(NOT_FOUND, "The list is empty.")
    tree = isinstance(view, QTreeView)
    by_number = isinstance(wanted, int) and not isinstance(wanted, bool)
    text = str(wanted).casefold()
    count = 0
    partial = None

    def walk(parent):
        nonlocal count, partial
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if by_number:
                if count == wanted:
                    return index
            else:
                cells = [str(model.index(row, column, parent).data(Qt.ItemDataRole.DisplayRole) or "").casefold()
                         for column in range(_columns(model, parent))]
                if text in cells:
                    return index
                if partial is None and any(text in cell for cell in cells):
                    partial = index
            count += 1
            # A row named by text is found in closed branches too; numbers count shown rows.
            if tree and model.hasChildren(index) and (not by_number or view.isExpanded(index)):
                found = walk(index)
                if found is not None:
                    return found
        return None

    found = walk(QModelIndex())
    if found is None:
        found = partial
    if found is None:
        raise ToolError(NOT_FOUND, f"The list has no row {wanted!r}.")
    return found


# ----- describing --------------------------------------------------------------------------
def describe(widget, *, rows: bool = True, offset: int = 0, limit: int = ROWS_SHOWN) -> dict[str, object]:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QComboBox,
                                   QDoubleSpinBox, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
                                   QSpinBox, QTabBar, QTabWidget, QTextEdit)

    kind = kind_of(widget)
    row: dict[str, object] = {"widget": widget_id(widget), "kind": kind or type(widget).__name__}
    name = widget.objectName()
    if name and not name.startswith("qt_"):
        row["name"] = name
    if not widget.isEnabled():
        row["enabled"] = False
    tip = _clean(widget.toolTip())
    if isinstance(widget, QAbstractButton):
        row["text"] = _clean(widget.text()) or tip
        if widget.isCheckable():
            row["checked"] = widget.isChecked()
    elif isinstance(widget, QLabel):
        row["text"] = _clean(_plain(widget.text()))
    elif isinstance(widget, QGroupBox):
        row["text"] = _clean(widget.title())
        if widget.isCheckable():
            row["checked"] = widget.isChecked()
    elif isinstance(widget, QComboBox):
        row["value"] = widget.currentText()
        row["items"] = [widget.itemText(index) for index in range(min(widget.count(), 200))]
        if widget.isEditable():
            row["editable"] = True
    elif isinstance(widget, QLineEdit):
        row["value"] = widget.text()[:TEXT_LIMIT] if widget.echoMode() == QLineEdit.EchoMode.Normal else "[hidden]"
        if widget.placeholderText():
            row["hint"] = _clean(widget.placeholderText())
        if widget.isReadOnly():
            row["read_only"] = True
    elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
        text = widget.toPlainText()
        row["value"] = text[:TEXT_LIMIT]
        if len(text) > TEXT_LIMIT:
            row["characters"] = len(text)
        if widget.isReadOnly():
            row["read_only"] = True
    elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QAbstractSlider, QProgressBar)):
        row["value"] = widget.value()
        row["minimum"], row["maximum"] = widget.minimum(), widget.maximum()
    elif isinstance(widget, (QTabWidget, QTabBar)):
        row["items"] = [_clean(widget.tabText(index)) for index in range(widget.count())]
        row["value"] = _clean(widget.tabText(widget.currentIndex())) if widget.count() else ""
    elif isinstance(widget, QAbstractItemView):
        listed, total = _model_rows(widget, offset, max(1, min(limit, MAX_ROWS))) if rows else ([], 0)
        model = widget.model()
        if model is not None and kind in ("table", "tree"):
            from PySide6.QtCore import Qt

            headers = [_clean(model.headerData(column, Qt.Orientation.Horizontal))
                       for column in range(_columns(model))]
            if any(headers):
                row["columns"] = headers
        row["rows"] = listed
        row["row_count"] = total
        if total > offset + len(listed):
            row["more_rows"] = True
    if tip and tip != row.get("text"):
        row["tip"] = tip[:300]
    return row


def _plain(text: str) -> str:
    if "<" not in text:
        return text
    from PySide6.QtGui import QTextDocumentFragment

    return QTextDocumentFragment.fromHtml(text).toPlainText()


def _children(widget) -> list:
    from PySide6.QtWidgets import QWidget

    return [child for child in widget.children() if isinstance(child, QWidget)]


def describe_tree(root, *, query: str = "", kinds: tuple[str, ...] = (), include_labels: bool = True) -> list[dict]:
    """Every visible control under ``root`` in the order the page lays them out."""

    from PySide6.QtWidgets import QTabWidget

    words = str(query or "").casefold().split()
    rows: list[dict[str, object]] = []

    def add(child, depth: int) -> None:
        kind = kind_of(child)
        if isinstance(child, QTabWidget):
            rows.append(describe(child))
            current = child.currentWidget()
            if current is not None and current.isVisibleTo(root):
                add(current, depth + 1)
            return
        if kind and (kind != "label" or include_labels):
            row = describe(child)
            if row.get("text") or kind not in ("label", "group"):
                rows.append(row)
        if kind not in _LEAVES and kind != "tabs":
            visit(child, depth + 1)

    def visit(widget, depth: int) -> None:
        for child in sorted(_children(widget), key=lambda w: (w.y() // 12, w.x())):
            if _valid(child) and child.isVisibleTo(root) and not child.isWindow():
                add(child, depth)

    visit(root, 0)
    if kinds:
        rows = [row for row in rows if row["kind"] in kinds]
    if words:
        def matches(row) -> bool:
            text = " ".join(str(row.get(key, "")) for key in ("text", "name", "value", "tip", "hint")).casefold()
            return all(word in text for word in words)
        rows = [row for row in rows if matches(row)]
    return rows


def find_by_text(root, text: str, kind: str = ""):
    """The one visible control under ``root`` with this text (or object name)."""

    wanted = _clean(text).casefold()
    exact, partial = [], []
    for row in describe_tree(root, include_labels=False):
        if kind and row["kind"] != kind:
            continue
        label = str(row.get("text", "")).casefold()
        if wanted in (label, str(row.get("name", "")).casefold(), label.rstrip(".:")):
            exact.append(row)
        elif wanted and wanted in label:
            partial.append(row)
    found = exact or partial
    if not found:
        raise ToolError(NOT_FOUND, f"No control shown has the text {text!r}. Call app_ui for the controls shown.")
    if len(found) > 1:
        raise ToolError(INVALID_ARGUMENTS, f"{len(found)} controls have the text {text!r}; name one by its "
                                           "widget id.", {"widgets": [row["widget"] for row in found[:20]]})
    return widget_by_id(str(found[0]["widget"]))


# ----- pages a helper draws from hidden Qt controls -------------------------------------------
def mirrored_page(window) -> tuple[object, list]:
    """Create New Item's page: (its Qt controls, its open dialogs, newest last), or (None, []).

    Its helper draws the page from these controls, which are themselves never shown; a
    click in the helper runs the control's handler, and so does a tool.
    """

    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    tab = created_tool_widget(getattr(getattr(window, "shell", None), "new_item_studio_tab", None))
    workflow = getattr(tab, "workflow", None)
    if tab is None or not _valid(workflow) or getattr(tab, "_bridge", None) is None:
        return None, []
    try:
        dialogs = [dialog for dialog in getattr(tab, "_dialogs").dialogs() if _valid(dialog)]
    except (AttributeError, RuntimeError, TypeError):
        dialogs = []
    return workflow, dialogs


def mirrored_gate(widget, window=None) -> str:
    """Why Create New Item takes no input for ``widget`` now, or "": its own page refuses
    input while a file or colour chooser is open, and outside its newest dialog."""

    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    workflow, dialogs = mirrored_page(window)
    if workflow is None or not any(root is widget or root.isAncestorOf(widget) for root in (*dialogs, workflow)):
        return ""
    tab = created_tool_widget(getattr(getattr(window, "shell", None), "new_item_studio_tab", None))
    try:
        if getattr(tab, "_dialogs").native_modal():
            return "Complete the file or colour dialog before editing the item."
    except (AttributeError, RuntimeError, TypeError):
        pass
    if dialogs and not (dialogs[-1] is widget or dialogs[-1].isAncestorOf(widget)):
        return "Complete the active dialog before editing the item."
    return ""


def shown_to_user(widget, window=None) -> bool:
    """Whether the user can see and use ``widget``: on screen, or on a page a helper draws."""

    if widget.isVisible():
        return True
    workflow, dialogs = mirrored_page(window)
    for root in (*dialogs, workflow):
        if root is not None and (root is widget or root.isAncestorOf(widget)):
            return bool(widget.isVisibleTo(root))
    return False


# ----- who may act ---------------------------------------------------------------------------
def user_only_reason(widget, window=None) -> str:
    """Why no tool may drive ``widget``, or ""."""

    from PySide6.QtWidgets import QAbstractButton

    from cdmw.mcp.classification import USER_ONLY_COMMANDS
    from cdmw.ui.commands.registry import command_registry, display_label

    parent = widget
    while parent is not None:
        if any(base.__name__ in _USER_ONLY_WINDOWS for base in type(parent).__mro__):
            return USER_ONLY_MESSAGE
        parent = parent.parentWidget()
    archive = getattr(window, "archive", None)
    if archive is not None and any(getattr(archive, name, None) is widget for name in _USER_ONLY_CONTROLS):
        return USER_ONLY_MESSAGE
    if isinstance(widget, QAbstractButton):
        registry = command_registry()
        text = _clean(widget.text()).casefold()
        for command_id in USER_ONLY_COMMANDS:
            if registry is not None and command_id in registry:
                if text and text == display_label(registry.get(command_id).label).casefold():
                    return USER_ONLY_MESSAGE
    return ""


def effect_of_action(widget, action: str) -> str:
    """The safety class of doing ``action`` to ``widget``."""

    from PySide6.QtWidgets import QAbstractButton, QTabBar, QTabWidget

    if action == "focus":
        return READ
    if isinstance(widget, (QTabWidget, QTabBar)):
        return READ  # showing another page changes no document
    if isinstance(widget, QAbstractButton) and action == "click":
        words = (_clean(widget.text()) or _clean(widget.toolTip())).casefold().split()
        first = words[0].strip(".:") if words else ""
        if first in DESTRUCTIVE_WORDS:
            return DESTRUCTIVE
        if first in OUTPUT_WORDS:
            return OUTPUT
    return EDIT


# ----- acting ----------------------------------------------------------------------------------
def act(widget, action: str, *, value: object = None, row: object = None, window=None,
        game_folder: str = "") -> dict[str, object]:
    """Do ``action`` to ``widget`` as the user would; the control as it is afterwards.

    Text that names a place in the game is never typed: a field may be where an output
    goes (Build Mod's folder, an extract folder), and no tool writes into the game.
    """

    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QComboBox, QDoubleSpinBox,
                                   QGroupBox, QLineEdit, QPlainTextEdit, QSpinBox, QTabBar, QTabWidget, QTextEdit)

    reason = user_only_reason(widget, window)
    if reason:
        raise ToolError(REFUSED, reason)
    if action not in ACTIONS:
        raise ToolError(INVALID_ARGUMENTS, f"The action is one of {', '.join(ACTIONS)}.")
    shown = shown_to_user(widget, window)
    if action != "focus" and (not widget.isEnabled() or not shown):
        why = _clean(widget.toolTip()) or ("It is disabled now." if shown else "It is not shown now.")
        raise ToolError(UNAVAILABLE, why)

    gate = mirrored_gate(widget, window) if action != "focus" else ""
    if gate:
        raise ToolError(UNAVAILABLE, gate)

    def wrong() -> ToolError:
        return ToolError(INVALID_ARGUMENTS, f"{action} does not apply to a {kind_of(widget) or 'widget'}.")

    if action == "focus":
        widget.setFocus()
    elif action == "click":
        if not isinstance(widget, QAbstractButton):
            raise wrong()
        widget.click()
    elif action in ("check", "uncheck"):
        wanted = action == "check"
        if isinstance(widget, QAbstractButton) and widget.isCheckable():
            if widget.isChecked() != wanted:
                widget.click()
        elif isinstance(widget, QGroupBox) and widget.isCheckable():
            widget.setChecked(wanted)
        else:
            raise wrong()
    elif action == "set_text":
        from cdmw.domain.output_paths import game_path_reason

        text = "" if value is None else str(value)
        in_game = game_path_reason(text, game_folder=game_folder)
        if in_game:
            raise ToolError(REFUSED, in_game)
        if isinstance(widget, QComboBox) and widget.isEditable():
            widget = widget.lineEdit()
        if isinstance(widget, QLineEdit):
            if widget.isReadOnly():
                raise ToolError(UNAVAILABLE, "The field is read-only.")
            # Typed, not set: selectAll + insert emits textEdited as typing does.
            widget.setFocus()
            widget.selectAll()
            if text:
                widget.insert(text)
            else:
                widget.del_()
            widget.editingFinished.emit()
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            if widget.isReadOnly():
                raise ToolError(UNAVAILABLE, "The text is read-only.")
            widget.setPlainText(text)
        else:
            raise wrong()
    elif action == "set_value":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolError(INVALID_ARGUMENTS, "value must be a number.")
        if isinstance(widget, QAbstractSlider):
            number = max(widget.minimum(), min(widget.maximum(), int(round(value))))
            widget.setSliderDown(True)
            widget.setValue(number)
            widget.sliderMoved.emit(number)
            widget.setSliderDown(False)  # emits sliderReleased, where a drag commits
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(round(value)))
            widget.editingFinished.emit()
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value))
            widget.editingFinished.emit()
        else:
            raise wrong()
    elif action in ("select", "activate"):
        if row is None:
            raise ToolError(INVALID_ARGUMENTS, "row is needed: a row's number or its text.")
        if isinstance(widget, QComboBox) and action == "select":
            index = row if isinstance(row, int) and not isinstance(row, bool) else widget.findText(str(row))
            if not 0 <= index < widget.count():
                raise ToolError(NOT_FOUND, f"The list has no item {row!r}.")
            widget.setCurrentIndex(index)
            widget.activated.emit(index)
        elif isinstance(widget, (QTabWidget, QTabBar)) and action == "select":
            labels = [_clean(widget.tabText(index)).casefold() for index in range(widget.count())]
            index = row if isinstance(row, int) and not isinstance(row, bool) else (
                labels.index(_clean(row).casefold()) if _clean(row).casefold() in labels else -1)
            if not 0 <= index < widget.count():
                raise ToolError(NOT_FOUND, f"There is no tab {row!r}.")
            widget.setCurrentIndex(index)
        elif isinstance(widget, QAbstractItemView):
            index = _index_of_row(widget, row)
            flags = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
            widget.scrollTo(index)
            widget.selectionModel().setCurrentIndex(index, flags)
            widget.clicked.emit(index)
            if action == "activate":
                widget.doubleClicked.emit(index)
                widget.activated.emit(index)
        else:
            raise wrong()
    return describe(widget) if _valid(widget) else {"widget": "", "closed": True}


__all__ = ["ACTIONS", "act", "describe", "describe_tree", "effect_of_action", "find_by_text", "kind_of",
           "mirrored_gate", "mirrored_page", "shown_to_user", "user_only_reason", "widget_by_id", "widget_id"]
