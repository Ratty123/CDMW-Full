"""Compact non-modal Character Context selector shared by preview surfaces."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.character_context import (
    CharacterContextDiscoveryResult,
    CharacterContextOption,
    CharacterContextSelection,
    character_context_options_by_id,
)
from cdmw.models import ArchiveEntry


_OPTION_ID_ROLE = int(Qt.ItemDataRole.UserRole)


class CharacterContextPanel(QFrame):
    selection_applied = Signal(object, object)
    panel_hidden = Signal()

    def __init__(self, service: object, *, surface_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CharacterContextPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(300)
        self.setMaximumWidth(430)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._service = service
        self._surface_label = str(surface_label or "Preview")
        self._source_entry: ArchiveEntry | None = None
        self._source_key = ""
        self._result: CharacterContextDiscoveryResult | None = None
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel("Character Context")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.close_button = QPushButton("Hide")
        self.close_button.setMaximumWidth(58)
        header.addWidget(self.close_button)
        root.addLayout(header)

        self.source_label = QLabel("Select a character head model.")
        self.source_label.setObjectName("HintLabel")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)
        self.status_label = QLabel("Open the panel to discover authored context.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(5)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        root.addWidget(QLabel("Authored appearance"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.setToolTip(
            "Exact game-authored appearances referencing this model. Heuristic matches are never selected automatically."
        )
        root.addWidget(self.appearance_combo)

        root.addWidget(QLabel("Face Pieces"))
        self.face_tree = self._make_tree(("Part", "Contents"), maximum_height=118)
        root.addWidget(self.face_tree)

        root.addWidget(QLabel("Hair"))
        self.hair_filter = QLineEdit()
        self.hair_filter.setPlaceholderText("Search compatible hair...")
        root.addWidget(self.hair_filter)
        self.hair_tree = self._make_tree(("Name", "Type", "Compatibility", "Source"), maximum_height=150)
        root.addWidget(self.hair_tree)

        root.addWidget(QLabel("Body"))
        self.body_filter = QLineEdit()
        self.body_filter.setPlaceholderText("Search compatible bodies...")
        root.addWidget(self.body_filter)
        self.body_tree = self._make_tree(("Name", "Type", "Compatibility", "Source"), maximum_height=132)
        root.addWidget(self.body_tree)

        self.gear_toggle = QToolButton()
        self.gear_toggle.setText("Optional Gear")
        self.gear_toggle.setCheckable(True)
        self.gear_toggle.setChecked(False)
        self.gear_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.gear_toggle.setArrowType(Qt.ArrowType.RightArrow)
        root.addWidget(self.gear_toggle)
        self.gear_tree = self._make_tree(("Gear", "Source"), maximum_height=126)
        self.gear_tree.setVisible(False)
        root.addWidget(self.gear_tree)

        button_row = QHBoxLayout()
        self.authored_button = QPushButton("Add Authored Hair + Body")
        self.authored_button.setToolTip("Enable the exact authored hair and body for the selected appearance.")
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Restore the safe default: authored face pieces only.")
        self.clear_button = QPushButton("Clear Context")
        self.clear_button.setToolTip("Remove every preview-only context component.")
        button_row.addWidget(self.authored_button, 1)
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.clear_button)
        root.addLayout(button_row)
        root.addStretch(1)

        self.close_button.clicked.connect(self._hide_requested)
        self.appearance_combo.currentIndexChanged.connect(self._appearance_changed)
        self.face_tree.itemChanged.connect(self._face_item_changed)
        self.gear_tree.itemChanged.connect(self._gear_item_changed)
        self.hair_tree.itemSelectionChanged.connect(self._hair_selection_changed)
        self.body_tree.itemSelectionChanged.connect(self._body_selection_changed)
        self.hair_filter.textChanged.connect(lambda text: self._filter_tree(self.hair_tree, text))
        self.body_filter.textChanged.connect(lambda text: self._filter_tree(self.body_tree, text))
        self.gear_toggle.toggled.connect(self._gear_toggled)
        self.authored_button.clicked.connect(self._use_authored)
        self.reset_button.clicked.connect(self._reset)
        self.clear_button.clicked.connect(self._clear)
        service.discovery_started.connect(self._discovery_started)
        service.discovery_progress.connect(self._discovery_progress)
        service.discovery_ready.connect(self._discovery_ready)
        service.discovery_failed.connect(self._discovery_failed)
        service.selection_changed.connect(self._selection_changed)

    @staticmethod
    def _make_tree(headers: tuple[str, ...], *, maximum_height: int) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(list(headers))
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        tree.setMaximumHeight(maximum_height)
        tree.setMinimumHeight(min(84, maximum_height))
        tree.setUniformRowHeights(True)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return tree

    def set_source_entry(self, entry: ArchiveEntry | None) -> None:
        self._source_entry = entry if isinstance(entry, ArchiveEntry) else None
        self._result = None
        self._source_key = self._service.source_key(entry) if isinstance(entry, ArchiveEntry) else ""
        self._clear_widgets()
        if self._source_entry is None:
            self.source_label.setText("Select a character head model.")
            self.status_label.setText("Character Context is unavailable without an archive model selection.")
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self.source_label.setText(str(self._source_entry.path or self._source_entry.basename))
        self.status_label.setText("Open the panel to discover exact authored context.")
        cached = self._service.cached_result(self._source_entry)
        if isinstance(cached, CharacterContextDiscoveryResult):
            self._apply_result(cached)

    def activate(self) -> None:
        self.setVisible(True)
        if self._source_entry is not None:
            self._service.request_discovery(self._source_entry)

    def _hide_requested(self) -> None:
        self.setVisible(False)
        self.panel_hidden.emit()
        cancel = getattr(self._service, "cancel_pending_discovery", None)
        if callable(cancel) and self._source_entry is not None:
            cancel(self._source_entry)

    def _clear_widgets(self) -> None:
        self._updating = True
        try:
            self.appearance_combo.clear()
            self.face_tree.clear()
            self.hair_tree.clear()
            self.body_tree.clear()
            self.gear_tree.clear()
        finally:
            self._updating = False

    def _discovery_started(self, source_key: str, _source: object) -> None:
        if source_key != self._source_key:
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Discovering exact authored appearances...")

    def _discovery_progress(self, source_key: str, current: int, total: int, detail: str) -> None:
        if source_key != self._source_key:
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, max(1, int(total)))
        self.progress_bar.setValue(max(0, int(current)))
        self.status_label.setText(str(detail))

    def _discovery_ready(self, source_key: str, result: object) -> None:
        if source_key != self._source_key or not isinstance(result, CharacterContextDiscoveryResult):
            return
        self._apply_result(result)

    def _discovery_failed(self, source_key: str, message: str) -> None:
        if source_key != self._source_key:
            return
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Character Context unavailable: {message}")

    def _apply_result(self, result: CharacterContextDiscoveryResult) -> None:
        self._result = result
        self.progress_bar.setVisible(False)
        self._updating = True
        try:
            self.appearance_combo.clear()
            for appearance in result.appearances:
                self.appearance_combo.addItem(appearance.label, appearance.appearance_id)
            if result.appearances:
                self.status_label.setText(
                    f"{len(result.appearances):,} exact appearance(s); "
                    f"{len(result.compatible_hair):,} compatible hair and "
                    f"{len(result.compatible_body):,} compatible body option(s)."
                )
            else:
                self.status_label.setText(
                    result.warnings[0] if result.warnings else "No exact authored appearance was found."
                )
        finally:
            self._updating = False
        self._sync_selection(self._service.selection(result.source_entry))

    def _selection_changed(self, source_key: str, selection: object, components: object) -> None:
        if source_key != self._source_key or not isinstance(selection, CharacterContextSelection):
            return
        self._sync_selection(selection)
        self.selection_applied.emit(self._source_entry, components)

    def _selected_appearance(self, selection: CharacterContextSelection):
        result = self._result
        if result is None:
            return None
        return next(
            (item for item in result.appearances if item.appearance_id == selection.appearance_id),
            result.appearances[0] if result.appearances else None,
        )

    def _sync_selection(self, selection: CharacterContextSelection) -> None:
        result = self._result
        if result is None:
            return
        appearance = self._selected_appearance(selection)
        self._updating = True
        try:
            combo_index = self.appearance_combo.findData(selection.appearance_id)
            if combo_index >= 0:
                self.appearance_combo.setCurrentIndex(combo_index)
            authored_options = tuple(appearance.options) if appearance is not None else ()
            self._populate_check_tree(
                self.face_tree,
                tuple(option for option in authored_options if option.slot == "face"),
                set(selection.face_option_ids),
                face=True,
            )
            self._populate_choice_tree(
                self.hair_tree,
                tuple(option for option in authored_options if option.slot == "hair") + tuple(result.compatible_hair),
                selection.hair_option_id,
            )
            self._populate_choice_tree(
                self.body_tree,
                tuple(option for option in authored_options if option.slot == "body") + tuple(result.compatible_body),
                selection.body_option_id,
            )
            self._populate_check_tree(
                self.gear_tree,
                tuple(option for option in authored_options if option.slot == "gear"),
                set(selection.gear_option_ids),
                face=False,
            )
            self._filter_tree(self.hair_tree, self.hair_filter.text())
            self._filter_tree(self.body_tree, self.body_filter.text())
        finally:
            self._updating = False

    @staticmethod
    def _source_name(option: CharacterContextOption) -> str:
        return PurePosixPath(str(option.entry.path or "").replace("\\", "/")).name

    def _populate_check_tree(
        self,
        tree: QTreeWidget,
        options: tuple[CharacterContextOption, ...],
        selected: set[str],
        *,
        face: bool,
    ) -> None:
        tree.clear()
        for option in options:
            contents = ", ".join(option.face_contents) if face else self._source_name(option)
            item = QTreeWidgetItem((option.label, contents))
            item.setData(0, _OPTION_ID_ROLE, option.option_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if option.option_id in selected else Qt.CheckState.Unchecked)
            item.setToolTip(0, str(option.entry.path or ""))
            tree.addTopLevelItem(item)
        for column in range(tree.columnCount()):
            tree.resizeColumnToContents(column)

    def _populate_choice_tree(
        self,
        tree: QTreeWidget,
        options: tuple[CharacterContextOption, ...],
        selected_id: str,
    ) -> None:
        tree.clear()
        none_item = QTreeWidgetItem(("None", "Off", "No context geometry", ""))
        none_item.setData(0, _OPTION_ID_ROLE, "")
        tree.addTopLevelItem(none_item)
        selected_item = none_item if not selected_id else None
        for option in options:
            item = QTreeWidgetItem(
                (
                    option.label,
                    "Authored" if option.authority == "authored" else "Alternative",
                    option.compatibility,
                    self._source_name(option),
                )
            )
            item.setData(0, _OPTION_ID_ROLE, option.option_id)
            item.setToolTip(0, str(option.entry.path or ""))
            tree.addTopLevelItem(item)
            if option.option_id == selected_id:
                selected_item = item
        if selected_item is not None:
            tree.setCurrentItem(selected_item)
        for column in range(tree.columnCount()):
            tree.resizeColumnToContents(column)

    @staticmethod
    def _filter_tree(tree: QTreeWidget, text: str) -> None:
        needle = str(text or "").strip().casefold()
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            haystack = " ".join(item.text(column) for column in range(tree.columnCount())).casefold()
            item.setHidden(bool(needle and needle not in haystack))

    def _appearance_changed(self, index: int) -> None:
        if self._updating or self._source_entry is None or index < 0:
            return
        self._service.select_appearance(self._source_entry, str(self.appearance_combo.itemData(index) or ""))

    def _face_item_changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        if self._updating or self._source_entry is None:
            return
        selected = tuple(
            str(item.data(0, _OPTION_ID_ROLE) or "")
            for item in (self.face_tree.topLevelItem(index) for index in range(self.face_tree.topLevelItemCount()))
            if item.checkState(0) == Qt.CheckState.Checked
        )
        self._service.set_selection(self._source_entry, replace(self._service.selection(self._source_entry), face_option_ids=selected))

    def _gear_item_changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        if self._updating or self._source_entry is None:
            return
        selected = tuple(
            str(item.data(0, _OPTION_ID_ROLE) or "")
            for item in (self.gear_tree.topLevelItem(index) for index in range(self.gear_tree.topLevelItemCount()))
            if item.checkState(0) == Qt.CheckState.Checked
        )
        self._service.set_selection(self._source_entry, replace(self._service.selection(self._source_entry), gear_option_ids=selected))

    def _hair_selection_changed(self) -> None:
        if self._updating or self._source_entry is None:
            return
        item = self.hair_tree.currentItem()
        option_id = str(item.data(0, _OPTION_ID_ROLE) or "") if item is not None else ""
        self._service.set_selection(self._source_entry, replace(self._service.selection(self._source_entry), hair_option_id=option_id))

    def _body_selection_changed(self) -> None:
        if self._updating or self._source_entry is None:
            return
        item = self.body_tree.currentItem()
        option_id = str(item.data(0, _OPTION_ID_ROLE) or "") if item is not None else ""
        self._service.set_selection(self._source_entry, replace(self._service.selection(self._source_entry), body_option_id=option_id))

    def _gear_toggled(self, checked: bool) -> None:
        self.gear_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.gear_tree.setVisible(bool(checked))

    def _use_authored(self) -> None:
        if self._source_entry is not None:
            self._service.use_authored_hair_and_body(self._source_entry)

    def _reset(self) -> None:
        if self._source_entry is not None:
            self._service.reset_selection(self._source_entry)

    def _clear(self) -> None:
        if self._source_entry is not None:
            self._service.clear_selection(self._source_entry)


__all__ = ["CharacterContextPanel"]
