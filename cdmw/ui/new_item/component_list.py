"""Model & Placement: every template model binding, its inclusion and what it exports.

A thin view over ``controller.component_rows()``. Lifetime contract: rows are
persistent items keyed by stable binding identity. Controller signals update them
in place; a different set of bindings (another template) is rebuilt on the next
event-loop turn. Neither happens while the view is still delivering a selection or
check-state change, so an index held by the Rust UI dispatcher (setCurrentIndex,
then scrollTo and clicked) never outlives its item. Selecting a row is applied
after that dispatch returns; ticking a row changes only its inclusion.
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHeaderView, QLabel, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.components import ComponentRole, ComponentSource
from cdmw.services.active_ui_translation import translate_active_ui_text

_IDENTITY_ROLE = Qt.ItemDataRole.UserRole
_ROLE_ORDER = (ComponentRole.WORN, ComponentRole.DROPPED, ComponentRole.OTHER)


def _group_label(role: ComponentRole) -> str:
    if role is ComponentRole.WORN:
        return translate_active_ui_text("Worn components")
    if role is ComponentRole.DROPPED:
        return translate_active_ui_text("Ground model (when dropped)")
    return translate_active_ui_text("Other models")


def component_name(row) -> str:
    return row.component_name or row.model_file.rsplit(".", 1)[0]


def source_text(row) -> str:
    if row.source is ComponentSource.IMPORTED:
        if row.source_name:
            return translate_active_ui_text("Imported: {name}").format(name=row.source_name)
        return translate_active_ui_text("Imported model")
    return translate_active_ui_text("Template model")


def body_state_text(row) -> str:
    if not row.cuts_body:
        return translate_active_ui_text("No cut rule")
    if row.body_kept_automatically:
        return translate_active_ui_text("Kept (left out)")
    if row.body_kept:
        return translate_active_ui_text("Kept")
    return translate_active_ui_text("Cut by template rule")


def _row_tooltip(row) -> str:
    tip = translate_active_ui_text("Prefab: {prefab}\nModel: {model}").format(prefab=row.prefab_path, model=row.model_path)
    if not row.included:
        tip += "\n" + translate_active_ui_text("Left out of the export. Tick to include it again with its previous model.")
    return tip


class ComponentList(QGroupBox):
    """Inclusion checkboxes and the selection that scopes the component editor."""

    #: a selection or inclusion change the viewport has not been refreshed for yet
    preview_out_of_date = Signal()

    def __init__(self, controller, panel=None, parent=None):
        super().__init__(translate_active_ui_text("Components"), parent or panel)
        self.setObjectName("new_item_component_list")
        self.setToolTip(translate_active_ui_text(
            "Tick the components the new item exports. A cleared box exports empty geometry for that component and drops "
            "its body-cut rule; its model and edits are kept for ticking it again. Select a row to edit that component. "
            "Changes reach the plan at once; use Refresh preview to see them."))
        self._controller = controller
        self._panel = panel
        self._rows = ()
        self._items = {}
        self._structure = None
        self._syncing = False
        self._pending_selection = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("new_item_component_tree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Component", "Model", "Body underneath"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 170)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree)
        self.note = QLabel("")
        self.note.setObjectName("new_item_component_note")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        layout.addWidget(self.note)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(0)
        self._selection_timer.timeout.connect(self._apply_selection)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(0)
        self._rebuild_timer.timeout.connect(self._rebuild)
        for signal in (controller.template_changed, controller.plan_invalidated, controller.variant_changed,
                       controller.model_changed, controller.model_import_changed):
            signal.connect(lambda *_args: self.refresh())
        self._rebuild()

    # ------------------------------------------------------------------ view

    def rows(self):
        return self._rows

    def item_for(self, identity):
        return self._items.get(identity)

    def refresh(self) -> None:
        """Update rows in place; a different set of bindings is rebuilt next turn."""

        rows = self._controller.component_rows()
        structure = tuple((row.role, row.identity) for row in rows)
        if structure != self._structure:
            self._rebuild_timer.start()
            return
        self._rows = rows
        self._syncing = True
        try:
            with QSignalBlocker(self.tree):
                for row in rows:
                    self._write_row(self._items[row.identity], row)
        finally:
            self._syncing = False

    def _rebuild(self) -> None:
        rows = self._controller.component_rows()
        self._rows = rows
        self._structure = tuple((row.role, row.identity) for row in rows)
        self._syncing = True
        try:
            with QSignalBlocker(self.tree):
                self.tree.clear()
                self._items = {}
                current = None
                for role in _ROLE_ORDER:
                    members = [row for row in rows if row.role is role]
                    if not members:
                        continue
                    group = QTreeWidgetItem([_group_label(role)])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    font = group.font(0)
                    font.setBold(True)
                    group.setFont(0, font)
                    group.setFirstColumnSpanned(True)
                    self.tree.addTopLevelItem(group)
                    for row in members:
                        item = QTreeWidgetItem(["", "", ""])
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setData(0, _IDENTITY_ROLE, row.identity)
                        self._write_row(item, row)
                        self.tree.addTopLevelItem(item)
                        self._items[row.identity] = item
                        if row.selected:
                            current = item
                if current is not None:
                    self.tree.setCurrentItem(current)
                # Body underneath matters only for a worn item.
                worn = getattr(self._controller, "template_is_worn", None)
                self.tree.setColumnHidden(2, callable(worn) and not worn())
                rows_shown = self.tree.topLevelItemCount()
                self.tree.setFixedHeight(min(10, max(3, rows_shown)) * 24 + 30)
        finally:
            self._syncing = False

    def _write_row(self, item, row) -> None:
        texts = ("  " + component_name(row), source_text(row), body_state_text(row))
        for column, text in enumerate(texts):
            if item.text(column) != text:
                item.setText(column, text)
        state = Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked
        if item.checkState(0) != state:
            item.setCheckState(0, state)
        tip = _row_tooltip(row)
        for column in range(3):
            if item.toolTip(column) != tip:
                item.setToolTip(column, tip)
            font = item.font(column)
            if font.italic() == row.included:
                font.setItalic(not row.included)
                item.setFont(column, font)

    # ------------------------------------------------------------------ input

    def _current_changed(self, current, _previous=None) -> None:
        if self._syncing or current is None:
            return
        identity = current.data(0, _IDENTITY_ROLE)
        if identity is None:
            return
        # Applied after the view (or the Rust dispatcher) has finished with its index.
        self._pending_selection = identity
        self._selection_timer.start()

    def _apply_selection(self) -> None:
        identity, self._pending_selection = self._pending_selection, None
        if identity is None or identity not in self._items:
            return
        controller = self._controller
        if identity == controller.current_variant_identity() and controller._active_variant is not None:
            return
        try:
            with self._deferred_preview():
                controller.select_variant(identity)
        except ValueError as exc:
            self.show_note(str(exc))
            self.refresh()
            return
        self.preview_out_of_date.emit()

    def _item_changed(self, item, column) -> None:
        if self._syncing or column != 0:
            return
        identity = item.data(0, _IDENTITY_ROLE)
        if identity is None:
            return
        included = item.checkState(0) == Qt.CheckState.Checked
        try:
            with self._deferred_preview():
                changed = self._controller.set_component_included(identity, included)
        except ValueError as exc:
            self.show_note(str(exc))
            self.refresh()
            return
        if changed:
            self.preview_out_of_date.emit()

    def set_included(self, identity, included: bool) -> None:
        """Programmatic tick/untick of one row by its stable identity."""

        item = self._items.get(identity)
        if item is not None:
            item.setCheckState(0, Qt.CheckState.Checked if included else Qt.CheckState.Unchecked)

    def show_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _deferred_preview(self):
        hold = getattr(self._panel, "deferred_preview", None)
        if callable(hold):
            return hold()
        from contextlib import nullcontext
        return nullcontext()


def export_summary_text(rows) -> str:
    """One line for the output review: what the export contains, before anything is written."""

    if not rows:
        return translate_active_ui_text("Choose a template to see its components.")
    worn = [row for row in rows if row.role is ComponentRole.WORN]
    included = [row for row in worn if row.included]
    imported = sum(1 for row in included if row.source is ComponentSource.IMPORTED)
    kept = sum(1 for row in worn if row.body_kept)
    text = translate_active_ui_text(
        "Worn components: {imported} imported, {template} template, {hidden} left out. "
        "Body underneath kept for {kept} of {total}.").format(
        imported=imported, template=len(included) - imported, hidden=len(worn) - len(included),
        kept=kept, total=len(worn))
    if any(not row.included for row in rows if row.role is ComponentRole.DROPPED):
        text += " " + translate_active_ui_text("The ground model is left out: a dropped item will be invisible.")
    return text


class ComponentSummary(QWidget):
    """Output review: the components the export contains, read from the live draft."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setObjectName("new_item_component_summary")
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.headline = QLabel("")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)
        self.table = QTreeWidget(self)
        self.table.setColumnCount(3)
        self.table.setHeaderLabels(["Component", "In the export", "Body underneath"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.table, 1)
        self.setToolTip(translate_active_ui_text(
            "Left-out components export empty geometry. Optional fitting references and the template are never exported."))
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        for signal in (controller.template_changed, controller.plan_invalidated, controller.plan_ready, controller.variant_changed):
            signal.connect(lambda *_args: self._refresh_timer.start())
        self.refresh()

    def refresh(self) -> None:
        rows = self._controller.component_rows()
        self.headline.setText(export_summary_text(rows))
        self.table.clear()
        for role in _ROLE_ORDER:
            members = [row for row in rows if row.role is role]
            if not members:
                continue
            group = QTreeWidgetItem([_group_label(role)])
            group.setFirstColumnSpanned(True)
            self.table.addTopLevelItem(group)
            for row in members:
                state = source_text(row) if row.included else translate_active_ui_text("Left out")
                self.table.addTopLevelItem(QTreeWidgetItem(["  " + component_name(row), state, body_state_text(row)]))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        self.refresh()


__all__ = ["ComponentList", "ComponentSummary", "body_state_text", "component_name", "export_summary_text",
           "source_text"]
