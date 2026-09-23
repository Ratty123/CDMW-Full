"""Allowlisted user input routed through the existing controls and handlers."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox,
    QApplication, QGroupBox, QLabel, QLineEdit, QMenu, QPlainTextEdit, QSlider, QSpinBox,
    QSplitter, QTableView, QTabWidget, QTextEdit, QTreeView,
)

from cdmw.services.new_item_rust_protocol import MAX_EDITABLE_TEXT_CHARS, PAGE_ROWS, PresentationProtocolError, integer, number, text_value
from cdmw.ui.new_item.rust_ui_models import column_count, resolve_index
from cdmw.ui.new_item.workflow_header import WorkflowHeader


def _boolean(value):
    if type(value) is not bool:
        raise PresentationProtocolError("Expected a boolean value.")
    return value


def _mapping(value):
    if not isinstance(value, dict):
        raise PresentationProtocolError("Expected structured control input.")
    return value


def apply_action(document, widget, node, action, value):
    """No dynamic attribute invocation or arbitrary method names cross the bridge."""
    if action == "activate":
        if isinstance(widget, QAbstractButton):
            widget.click()
            return
        if isinstance(widget, QAction) and not widget.isSeparator():
            menu = widget.parent()
            if isinstance(menu, QMenu) and menu.isVisible():
                # QMenu.exec callers inspect its returned QAction. Triggering the
                # signal alone would leave exec open and lose that return value.
                point = QPointF(menu.actionGeometry(widget).center())
                for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                    QApplication.sendEvent(menu, QMouseEvent(kind, point, QPointF(menu.mapToGlobal(point.toPoint())),
                        Qt.LeftButton, Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier))
            else:
                widget.trigger()
            return
    elif action == "toggle":
        checked = _boolean(value)
        if isinstance(widget, QAbstractButton) and widget.isCheckable():
            if widget.isChecked() != checked:
                widget.click()
            return
        if isinstance(widget, QGroupBox) and widget.isCheckable():
            widget.setChecked(checked)
            widget.clicked.emit(checked)
            return
    elif action == "text":
        _set_text(widget, value)
        return
    elif action == "number" and isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
        if not isinstance(widget, QSlider) and widget.isReadOnly():
            raise PresentationProtocolError("This number is read-only.")
        parsed = number(value)
        if not widget.minimum() <= parsed <= widget.maximum():
            raise PresentationProtocolError("This number is outside the control's allowed range.")
        widget.setValue(parsed if isinstance(widget, QDoubleSpinBox) else int(parsed))
        return
    elif action == "choose" and isinstance(widget, QComboBox):
        row = integer(value, maximum=max(0, widget.count() - 1))
        index = widget.model().index(row, widget.modelColumn(), widget.rootModelIndex())
        if not index.isValid() or not widget.model().flags(index) & Qt.ItemIsEnabled:
            raise PresentationProtocolError("This choice is unavailable.")
        widget.setCurrentIndex(row)
        widget.activated.emit(row)
        widget.textActivated.emit(widget.currentText())
        return
    elif action == "tab":
        if isinstance(widget, QTabWidget):
            row = integer(value, maximum=widget.count() - 1)
            if not widget.isTabEnabled(row) or not widget.isTabVisible(row):
                raise PresentationProtocolError("This page is unavailable.")
            widget.setCurrentIndex(row)
            return
        if isinstance(widget, WorkflowHeader):
            widget.setCurrentRow(integer(value, maximum=widget.count() - 1))
            return
    elif action == "crop":
        from PySide6.QtCore import QRect
        from cdmw.ui.archive_browser.static_replacement_icon_selection import IconRegionSelector
        if not isinstance(widget, IconRegionSelector) or not isinstance(value,list) or len(value) != 4:
            raise PresentationProtocolError("Invalid icon selection.")
        x,y,width,height = [integer(v, maximum=32768) for v in value]
        if width < 2 or height < 2 or x+width > widget._image.width() or y+height > widget._image.height():
            raise PresentationProtocolError("The icon selection must remain inside the captured image.")
        widget._set_selection(QRect(x,y,width,height))
        return
    elif action == "split" and isinstance(widget, QSplitter):
        if not isinstance(value, list) or len(value) != widget.count():
            raise PresentationProtocolError("Invalid splitter sizes.")
        sizes = [integer(size, minimum=0 if widget.widget(i).isHidden() else 40, maximum=16000)
                 for i, size in enumerate(value)]
        widget.setSizes(sizes)
        return
    elif action in {"select", "cell", "check_cell", "expand", "sort", "menu", "resize_column"} and isinstance(widget, QAbstractItemView):
        _view_action(widget, action, value)
        return
    elif action == "range":
        values = _mapping(value)
        offset = integer(values.get("offset", 0), maximum=10_000_000)
        parent = values.get("parent", [])
        if not isinstance(parent, list) or len(parent) > 32:
            raise PresentationProtocolError("Invalid range parent.")
        parent = tuple(integer(row, maximum=10_000_000) for row in parent)
        if isinstance(widget, (QAbstractItemView, QComboBox, QPlainTextEdit, QTextEdit)):
            if isinstance(widget, (QPlainTextEdit, QTextEdit)) and not widget.isReadOnly():
                raise PresentationProtocolError("Editable text is not paged.")
            document.models.ranges[(node["id"], parent)] = offset
            if isinstance(widget, QAbstractItemView) and values.get("end") is True:
                bar = widget.verticalScrollBar()
                bar.setValue(bar.maximum())
            return
    elif action == "key" and isinstance(widget, (QAbstractItemView, QComboBox, WorkflowHeader)):
        from PySide6.QtGui import QKeyEvent
        from cdmw.ui.new_item.rust_ui_models import index_path
        values = _mapping(value)
        keys = {name: getattr(Qt.Key, "Key_" + name) for name in
                ("Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown", "Return", "Space")}
        key = values.get("key")
        if key not in keys:
            raise PresentationProtocolError("This navigation key is unavailable.")
        modifiers = Qt.NoModifier
        if _boolean(values.get("shift", False)):
            modifiers |= Qt.ShiftModifier
        if _boolean(values.get("control", False)):
            modifiers |= Qt.ControlModifier
        for event in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(event, keys[key], modifiers))
        if isinstance(widget, QAbstractItemView):
            current = widget.currentIndex()
            if current.isValid():
                path = index_path(current)
                document.models.ranges[(node["id"], tuple(path[:-1]))] = path[-1] // PAGE_ROWS * PAGE_ROWS
        return
    elif action == "submit" and isinstance(widget, QLineEdit):
        if widget.hasAcceptableInput():
            widget.returnPressed.emit()
            widget.editingFinished.emit()
        return
    elif action == "finish_edit":
        if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
            widget.editingFinished.emit()
            return
        if isinstance(widget, QComboBox) and widget.isEditable():
            widget.lineEdit().editingFinished.emit()
            return
        if isinstance(widget, QSlider):
            widget.sliderReleased.emit()
            return
    elif action == "copy":
        if isinstance(widget, (QPlainTextEdit, QTextEdit)):
            QGuiApplication.clipboard().setText(widget.toPlainText())
            return
        if isinstance(widget, (QLineEdit, QLabel)):
            QGuiApplication.clipboard().setText(widget.text())
            return
    elif action == "link" and isinstance(widget, QLabel):
        url = text_value(value, maximum=4096)
        if url not in {link["url"] for link in node["props"].get("links", [])}:
            raise PresentationProtocolError("This link is not part of the current control.")
        if widget.openExternalLinks():
            QDesktopServices.openUrl(QUrl(url))
        else:
            widget.linkActivated.emit(url)
        return
    elif action == "close_dialog" and isinstance(widget, (QDialog, QMenu)):
        widget.reject() if isinstance(widget, QDialog) else widget.close()
        return
    raise PresentationProtocolError(f"The {action} action is unsupported for this control.")


def _set_text(widget, value):
    value = text_value(value, maximum=MAX_EDITABLE_TEXT_CHARS)
    if isinstance(widget, QLineEdit):
        if widget.isReadOnly() or len(value) > widget.maxLength():
            raise PresentationProtocolError("This text cannot be edited to that value.")
        validator = widget.validator()
        if validator is not None and validator.validate(value, len(value))[0] == validator.State.Invalid:
            raise PresentationProtocolError("The text does not satisfy this field's validator.")
        widget.setText(value)
        widget.textEdited.emit(value)
    elif isinstance(widget, (QPlainTextEdit, QTextEdit)) and not widget.isReadOnly():
        widget.setPlainText(value)
    elif isinstance(widget, QComboBox) and widget.isEditable():
        widget.setEditText(value)
        widget.lineEdit().textEdited.emit(value)
    else:
        raise PresentationProtocolError("This control does not accept text edits.")


def _view_action(view, action, value):
    values = _mapping(value)
    if action in {"sort", "resize_column"}:
        column = integer(values.get("column"), maximum=column_count(view.model(), view.rootIndex()) - 1)
        header = view.horizontalHeader() if isinstance(view, QTableView) else view.header() if isinstance(view, QTreeView) else None
        if header is None or (action == "sort" and not header.sectionsClickable()):
            raise PresentationProtocolError("This table does not support sorting.")
        if action == "resize_column":
            from PySide6.QtWidgets import QHeaderView
            if header.sectionResizeMode(column) != QHeaderView.ResizeMode.Interactive:
                raise PresentationProtocolError("This column has an automatic width.")
            header.resizeSection(column, integer(values.get("width"), minimum=24, maximum=4000))
            return
        if view.isSortingEnabled():
            order = Qt.DescendingOrder if _boolean(values.get("descending", False)) else Qt.AscendingOrder
            view.sortByColumn(column, order)
        else:
            header.sectionClicked.emit(column)
        return
    index = resolve_index(view.model(), values.get("path"), values.get("column", 0))
    flags = view.model().flags(index)
    if not flags & Qt.ItemIsEnabled:
        raise PresentationProtocolError("This row is disabled.")
    if action == "select":
        if not flags & Qt.ItemIsSelectable:
            raise PresentationProtocolError("This row cannot be selected.")
        mode = values.get("mode", "click")
        if mode not in {"click", "double", "activate", "toggle", "range"}:
            raise PresentationProtocolError("Unknown selection mode.")
        selection = QItemSelectionModel.ClearAndSelect
        if mode == "toggle" and view.selectionMode() in (QAbstractItemView.SelectionMode.MultiSelection, QAbstractItemView.SelectionMode.ExtendedSelection):
            selection = QItemSelectionModel.Toggle
        if view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows:
            selection |= QItemSelectionModel.Rows
        elif view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectColumns:
            selection |= QItemSelectionModel.Columns
        if mode == "range" and view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection and view.currentIndex().isValid():
            anchor = view.currentIndex()
            if anchor.parent() != index.parent():
                raise PresentationProtocolError("A selection range must stay inside one tree branch.")
            span = QItemSelection(anchor, index)
            view.selectionModel().select(span, selection)
            view.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        else:
            view.selectionModel().setCurrentIndex(index, selection)
        view.scrollTo(index)
        if mode == "double":
            view.doubleClicked.emit(index)
        elif mode == "activate":
            view.activated.emit(index)
        else:
            view.clicked.emit(index)
    elif action == "cell":
        if not flags & Qt.ItemIsEditable or view.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers:
            raise PresentationProtocolError("This cell is read-only.")
        if not view.model().setData(index, text_value(values.get("text")), Qt.EditRole):
            raise PresentationProtocolError("The table rejected this edit.")
    elif action == "check_cell":
        if not flags & Qt.ItemIsUserCheckable:
            raise PresentationProtocolError("This cell has no editable check state.")
        checked = integer(values.get("check"), maximum=2)
        if not view.model().setData(index, checked, Qt.CheckStateRole):
            raise PresentationProtocolError("The table rejected this check state.")
    elif action == "expand" and isinstance(view, QTreeView):
        view.setExpanded(index, _boolean(values.get("expanded")))
    elif action == "menu":
        if view.contextMenuPolicy() != Qt.CustomContextMenu:
            raise PresentationProtocolError("This table has no context menu.")
        view.setCurrentIndex(index)
        rect = view.visualRect(index)
        view.customContextMenuRequested.emit(rect.center() if rect.isValid() else QPoint(1, 1))
    else:
        raise PresentationProtocolError("This table action is unavailable.")
