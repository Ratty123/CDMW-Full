"""Model & Placement: every template model binding and what the export makes of it.

A thin view over ``controller.component_rows()``. Selecting a row scopes the
component editor below it; Hide in export and Show in export act on that row.
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from cdmw.domain.new_item.components import ComponentRole, ComponentSource
from cdmw.services.active_ui_translation import translate_active_ui_text

_IDENTITY_ROLE = Qt.ItemDataRole.UserRole


def _group_label(role: ComponentRole) -> str:
    if role is ComponentRole.WORN:
        return translate_active_ui_text("Worn components")
    if role is ComponentRole.DROPPED:
        return translate_active_ui_text("Ground model (when dropped)")
    return translate_active_ui_text("Other models")


def component_name(row) -> str:
    return row.component_name or row.model_file.rsplit(".", 1)[0]


def export_state_text(row) -> str:
    if row.source is ComponentSource.HIDDEN:
        return translate_active_ui_text("Hidden in export")
    if row.source is ComponentSource.IMPORTED:
        if row.source_name:
            return translate_active_ui_text("Imported: {name}").format(name=row.source_name)
        return translate_active_ui_text("Imported model")
    return translate_active_ui_text("Template model")


def body_state_text(row) -> str:
    if not row.cuts_body:
        return translate_active_ui_text("No cut rule")
    if row.body_kept_automatically:
        return translate_active_ui_text("Kept (hidden)")
    if row.body_kept:
        return translate_active_ui_text("Kept")
    return translate_active_ui_text("Cut by template rule")


class ComponentList(QGroupBox):
    """The visible, reversible component workflow that replaces the variant combobox."""

    def __init__(self, controller, parent=None):
        super().__init__(translate_active_ui_text("Item components"), parent)
        self.setObjectName("new_item_component_list")
        self._controller = controller
        self._rows = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        intro = QLabel("Each row is one model of the template. Select a row to edit it below. The list shows what the new item exports.")
        intro.setObjectName("new_item_intro")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("new_item_component_tree")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Component", "In the export", "Body underneath", "Model file"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(132)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header = self.tree.header()
        header.setStretchLastSection(True)
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setToolTip("Hidden in export: the component's model is replaced by empty geometry and draws nothing. "
                             "Its body-cut rule is removed too, so it no longer hides the body underneath.")
        self.tree.currentItemChanged.connect(self._current_changed)
        layout.addWidget(self.tree)
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.hide_button = QPushButton("Hide in export")
        self.hide_button.setObjectName("new_item_component_hide")
        self.hide_button.setToolTip("Export empty geometry for the selected component at every LOD. Show in export restores "
                                    "its previous model, placement and edits.")
        self.hide_button.clicked.connect(self._hide)
        actions.addWidget(self.hide_button)
        self.show_button = QPushButton("Show in export")
        self.show_button.setObjectName("new_item_component_show")
        self.show_button.setToolTip("Undo Hide in export for the selected component.")
        self.show_button.clicked.connect(self._show)
        actions.addWidget(self.show_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.note = QLabel("")
        self.note.setObjectName("new_item_component_note")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        for signal in (controller.template_changed, controller.plan_invalidated, controller.variant_changed,
                       controller.model_changed, controller.model_import_changed, controller.busy_changed):
            signal.connect(lambda *_args: self.refresh())
        self.refresh()

    # ------------------------------------------------------------------ view

    def rows(self):
        return self._rows

    def refresh(self) -> None:
        rows = self._controller.component_rows()
        self._rows = rows
        selected = next((row.identity for row in rows if row.selected), None)
        with QSignalBlocker(self.tree):
            self.tree.clear()
            current = None
            for role in (ComponentRole.WORN, ComponentRole.DROPPED, ComponentRole.OTHER):
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
                    item = QTreeWidgetItem(["   " + component_name(row), export_state_text(row), body_state_text(row), row.model_file])
                    item.setData(0, _IDENTITY_ROLE, row.identity)
                    tip = translate_active_ui_text("Prefab: {prefab}\nModel: {model}").format(
                        prefab=row.prefab_path, model=row.model_path)
                    for column in range(4):
                        item.setToolTip(column, tip)
                    if row.source is ComponentSource.HIDDEN:
                        for column in range(4):
                            font = item.font(column)
                            font.setItalic(True)
                            item.setFont(column, font)
                    self.tree.addTopLevelItem(item)
                    if row.identity == selected:
                        current = item
            if current is not None:
                self.tree.setCurrentItem(current)
        self._refresh_actions()

    def _selected_row(self):
        item = self.tree.currentItem()
        identity = item.data(0, _IDENTITY_ROLE) if item is not None else None
        return next((row for row in self._rows if row.identity == identity), None)

    def _refresh_actions(self) -> None:
        row = self._selected_row()
        busy = bool(getattr(self._controller, "busy", False))
        hidden = row is not None and row.source is ComponentSource.HIDDEN
        self.hide_button.setEnabled(row is not None and not hidden and not busy)
        self.show_button.setEnabled(row is not None and hidden and not busy)
        if row is None:
            self.note.setText(translate_active_ui_text("This template has no model bindings to edit."))
        elif row.role is ComponentRole.DROPPED:
            self.note.setText(translate_active_ui_text(
                "The ground model is drawn when the item lies on the ground. Hiding it makes a dropped item invisible."))
        elif hidden:
            self.note.setText(translate_active_ui_text(
                "{name} is hidden in export: the item draws nothing for it and it no longer hides the body.").format(
                name=component_name(row)))
        else:
            self.note.setText(translate_active_ui_text("Settings below apply only to {name}.").format(name=component_name(row)))

    # ------------------------------------------------------------------ actions

    def _current_changed(self, current, _previous=None) -> None:
        identity = current.data(0, _IDENTITY_ROLE) if current is not None else None
        if identity is None:
            self._refresh_actions()
            return
        if identity != self._controller.current_variant_identity() or self._controller._active_variant is None:
            try:
                self._controller.select_variant(identity)
            except ValueError as exc:
                self.note.setText(str(exc))
                return
        self._refresh_actions()

    def _hide(self) -> None:
        row = self._selected_row()
        if row is not None:
            self._controller.hide_component(row.identity)

    def _show(self) -> None:
        row = self._selected_row()
        if row is not None:
            self._controller.show_component(row.identity)


def export_summary_text(rows) -> str:
    """One line for the output review: what the export contains, before anything is written."""

    if not rows:
        return translate_active_ui_text("Choose a template to see its components.")
    worn = [row for row in rows if row.role is ComponentRole.WORN]
    counts = {kind: sum(1 for row in worn if row.source is kind) for kind in ComponentSource}
    kept = sum(1 for row in worn if row.body_kept)
    text = translate_active_ui_text(
        "Worn components: {imported} imported, {template} template, {hidden} hidden in export. "
        "Body underneath kept for {kept} of {total}.").format(
        imported=counts[ComponentSource.IMPORTED], template=counts[ComponentSource.TEMPLATE],
        hidden=counts[ComponentSource.HIDDEN], kept=kept, total=len(worn))
    dropped = [row for row in rows if row.role is ComponentRole.DROPPED]
    if any(row.source is ComponentSource.HIDDEN for row in dropped):
        text += " " + translate_active_ui_text("The ground model is hidden: a dropped item will be invisible.")
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
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Component", "In the export", "Body underneath", "Model file"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.table, 1)
        note = QLabel("Hidden components export empty geometry. Optional fitting references and the template are never exported.")
        note.setObjectName("new_item_intro")
        note.setWordWrap(True)
        layout.addWidget(note)
        for signal in (controller.template_changed, controller.plan_invalidated, controller.plan_ready, controller.variant_changed):
            signal.connect(lambda *_args: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        rows = self._controller.component_rows()
        self.headline.setText(export_summary_text(rows))
        self.table.clear()
        for role in (ComponentRole.WORN, ComponentRole.DROPPED, ComponentRole.OTHER):
            members = [row for row in rows if row.role is role]
            if not members:
                continue
            group = QTreeWidgetItem([_group_label(role)])
            group.setFirstColumnSpanned(True)
            self.table.addTopLevelItem(group)
            for row in members:
                self.table.addTopLevelItem(QTreeWidgetItem(
                    ["   " + component_name(row), export_state_text(row), body_state_text(row), row.model_file]))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        self.refresh()


__all__ = ["ComponentList", "ComponentSummary", "body_state_text", "component_name", "export_state_text",
           "export_summary_text"]
