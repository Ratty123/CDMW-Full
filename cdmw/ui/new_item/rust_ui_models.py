"""Bounded projections of the existing New Item list and table models."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QTableView, QTreeView

from cdmw.services.new_item_rust_protocol import MAX_COLUMNS, PAGE_ROWS, PresentationProtocolError


def index_path(index: QModelIndex) -> list[int]:
    result = []
    while index.isValid():
        result.append(index.row())
        index = index.parent()
    return list(reversed(result))


def column_count(model, parent):
    # QAbstractListModel defines a single column; its columnCount is private in
    # PySide, including Python list models and QListWidget's private QListModel.
    return 1 if isinstance(model, QAbstractListModel) else model.columnCount(parent)


def resolve_index(model, path, column=0):
    if not isinstance(path, list) or not path or len(path) > 32:
        raise PresentationProtocolError("Invalid model row path.")
    parent = QModelIndex()
    for row in path:
        if type(row) is not int or not 0 <= row < model.rowCount(parent):
            raise PresentationProtocolError("The selected row is no longer present.")
        parent = model.index(row, 0, parent)
    if type(column) is not int or not 0 <= column < column_count(model, parent.parent()):
        raise PresentationProtocolError("The selected column is no longer present.")
    return parent.siblingAtColumn(column)


class ModelProjection:
    def __init__(self):
        self.ranges = {}
        self._serial = 0
        self._identities = weakref.WeakKeyDictionary()
        self._revisions = weakref.WeakKeyDictionary()

    def identity(self, model):
        if model not in self._identities:
            self._serial += 1
            self._identities[model] = self._serial
            self._revisions[model] = 0
            ref = weakref.ref(model)

            def changed(*_args):
                current = ref()
                if current is not None:
                    self._revisions[current] = self._revisions.get(current, 0) + 1

            for signal in (model.modelReset, model.layoutChanged, model.dataChanged,
                           model.rowsInserted, model.rowsRemoved, model.rowsMoved,
                           model.columnsInserted, model.columnsRemoved):
                signal.connect(changed)
        return [self._identities[model], self._revisions[model]]

    def _range(self, identifier, total, parent=()):
        offset = self.ranges.get((identifier, tuple(parent)), 0)
        offset = min(max(0, offset), max(0, total - 1))
        return offset, min(total, offset + PAGE_ROWS)

    def combo(self, combo: QComboBox, identifier):
        model = combo.model()
        start, end = self._range(identifier, combo.count())
        options = []
        for row in range(start, end):
            index = model.index(row, combo.modelColumn(), combo.rootModelIndex())
            options.append({"index": row, "text": combo.itemText(row),
                            "tooltip": str(index.data(Qt.ToolTipRole) or ""),
                            "enabled": bool(model.flags(index) & Qt.ItemIsEnabled)})
        return {"model": self.identity(model), "options": options, "offset": start,
                "total": combo.count(), "selected": combo.currentIndex(),
                "text": combo.currentText(), "editable": combo.isEditable()}

    def view(self, view: QAbstractItemView, identifier, widget_writer):
        model, root = view.model(), view.rootIndex()
        if model is None:
            return {"rows": [], "columns": [], "total": 0, "offset": 0}
        columns = column_count(model, root)
        if columns > MAX_COLUMNS:
            raise PresentationProtocolError(f"The table has {columns} columns; the limit is {MAX_COLUMNS}.")
        is_table = isinstance(view, QTableView)
        is_tree = isinstance(view, QTreeView)
        header = view.horizontalHeader() if is_table else view.header() if is_tree else None
        columns_data = []
        for col in range(columns):
            columns_data.append({"index": col,
                                 "text": str(model.headerData(col, Qt.Horizontal) or ""),
                                 "width": header.sectionSize(col) if header else 160,
                                 "resizable": bool(header and header.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive),
                                 "size_to_contents": bool(header and header.sectionResizeMode(col) == QHeaderView.ResizeMode.ResizeToContents),
                                 "stretch": bool(header and (header.sectionResizeMode(col) == QHeaderView.ResizeMode.Stretch
                                                            or header.stretchLastSection() and col == columns - 1)),
                                 "hidden": header.isSectionHidden(col) if header else False})
        selected = view.selectionModel()
        budget = [PAGE_ROWS]

        def rows_at(parent):
            path = index_path(parent)
            total = model.rowCount(parent)
            start, end = self._range(identifier, total, path)
            result = []
            for row in range(start, end):
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                first = model.index(row, 0, parent)
                row_data = {"path": index_path(first), "cells": [],
                            "children": bool(is_tree and model.rowCount(first)),
                            "expanded": is_tree and view.isExpanded(first),
                            "label": str(model.headerData(row, Qt.Vertical) or "")}
                for col in range(columns):
                    idx = model.index(row, col, parent)
                    flags = model.flags(idx)
                    check = idx.data(Qt.CheckStateRole)
                    displayed = idx.data(Qt.DisplayRole)
                    cell = {"text": "" if displayed is None else str(displayed),
                            "tooltip": str(idx.data(Qt.ToolTipRole) or ""),
                            "editable": bool(flags & Qt.ItemIsEditable) and view.editTriggers() != QAbstractItemView.EditTrigger.NoEditTriggers,
                            "enabled": bool(flags & Qt.ItemIsEnabled),
                            "selectable": bool(flags & Qt.ItemIsSelectable),
                            "selected": bool(selected and selected.isSelected(idx))}
                    for name, role in (("background", Qt.BackgroundRole), ("foreground", Qt.ForegroundRole)):
                        brush = idx.data(role)
                        if isinstance(brush, QBrush) and brush.style() != Qt.NoBrush:
                            cell[name] = brush.color().name()
                    font = idx.data(Qt.FontRole)
                    if isinstance(font, QFont):
                        cell.update(bold=font.bold(), italic=font.italic())
                    if check is not None and flags & Qt.ItemIsUserCheckable:
                        cell["check"] = int(check.value if hasattr(check, "value") else check)
                    embedded = view.indexWidget(idx)
                    if embedded is not None:
                        cell["control"] = widget_writer(embedded, force=True)
                    row_data["cells"].append(cell)
                if row_data["expanded"]:
                    row_data["nested"] = rows_at(first)
                result.append(row_data)
            return {"rows": result, "offset": start, "end": start + len(result), "total": total, "parent": path}

        result = rows_at(root)
        current = view.currentIndex()
        result.update({"columns": columns_data, "model": self.identity(model),
                       "current": index_path(current) if current.isValid() else [],
                       "current_column": current.column(),
                       "selection_mode": int(view.selectionMode().value),
                       "selection_behavior": int(view.selectionBehavior().value),
                       "sort_column": header.sortIndicatorSection() if header else -1,
                       "sort_descending": bool(header and header.sortIndicatorOrder() == Qt.DescendingOrder),
                       "sortable": bool(header and header.sectionsClickable()),
                       "headers": bool(header and not header.isHidden()),
                       "context_menu": view.contextMenuPolicy() == Qt.CustomContextMenu,
                       "row_headers": bool(is_table and not view.verticalHeader().isHidden()),
                       "tree": is_tree and view.rootIsDecorated()})
        return result
