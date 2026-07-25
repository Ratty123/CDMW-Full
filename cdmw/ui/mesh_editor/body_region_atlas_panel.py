"""Body-region atlas panel: pick a body part, generate its sliders.

Self-contained on purpose. It takes a :class:`BodyRegionAtlas` and emits the
regions the user picked; it opens no session, touches no archive, and knows
nothing about its host. Building it that way keeps it testable offscreen and
lets the host decide where it lives.

All logic worth testing — grouping, colours, summaries, what counts as a
warning — is in ``cdmw.domain.mesh.body_region_atlas``. This file is only the
widget.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh.body_region_atlas import BodyRegionAtlas, BodyRegionAtlasRow


REGION_ID_ROLE = int(Qt.UserRole) + 1
SWATCH_SIZE = 12


class BodyRegionAtlasPanel(QWidget):
    """Grouped, colour-coded region list with a slider-generation action."""

    regions_selected = Signal(tuple)
    """Region ids the user has ticked, whenever that set changes."""

    sliders_requested = Signal(tuple)
    """Region ids to build sliders for. Empty means the whole body."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BodyRegionAtlasPanel")
        self._atlas = BodyRegionAtlas()
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        self.title_label = QLabel("Body Regions")
        self.title_label.setObjectName("SectionLabel")
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("HintLabel")
        self.summary_label.setWordWrap(True)
        self.warning_label = QLabel("")
        self.warning_label.setObjectName("HintLabel")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("BodyRegionAtlasTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Region", "Detail"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.itemChanged.connect(self._on_item_changed)

        self.select_all_button = QPushButton("Select All")
        self.clear_button = QPushButton("Clear")
        self.build_button = QPushButton("Generate Sliders")
        self.build_button.setToolTip(
            "Build Size, Length, Taper, Flatten and Shift sliders for the ticked regions. "
            "With nothing ticked, builds them for the whole body."
        )
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.clear_button.clicked.connect(lambda: self._set_all_checked(False))
        self.build_button.clicked.connect(
            lambda: self.sliders_requested.emit(self.selected_region_ids())
        )

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(3)
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.build_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.warning_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(button_row)
        self.set_atlas(BodyRegionAtlas())

    def set_atlas(self, atlas: BodyRegionAtlas) -> None:
        """Rebuild the panel for a new region map."""

        self._atlas = atlas
        self._updating = True
        try:
            self.tree.clear()
            for group in atlas.groups:
                parent = QTreeWidgetItem(self.tree, [group.name, f"{group.vertex_count:,} verts"])
                parent.setFlags(parent.flags() & ~Qt.ItemIsUserCheckable)
                parent.setExpanded(True)
                for row in group.rows:
                    self._add_row(parent, row)
        finally:
            self._updating = False

        self.summary_label.setText(atlas.summary)
        self.warning_label.setText("\n".join(atlas.warnings))
        self.warning_label.setVisible(bool(atlas.warnings))
        # Nothing to build from an empty atlas, so do not offer it.
        enabled = not atlas.empty
        for widget in (self.tree, self.select_all_button, self.clear_button, self.build_button):
            widget.setEnabled(enabled)
        self._emit_selection()

    def selected_region_ids(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(0, REGION_ID_ROLE))
            for item in self._region_items()
            if item.checkState(0) == Qt.Checked
        )

    def set_selected_region_ids(self, region_ids: Iterable[str]) -> None:
        wanted = {str(value).strip().lower() for value in region_ids}
        self._updating = True
        try:
            for item in self._region_items():
                checked = str(item.data(0, REGION_ID_ROLE)) in wanted
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        finally:
            self._updating = False
        self._emit_selection()

    def _add_row(self, parent: QTreeWidgetItem, row: BodyRegionAtlasRow) -> None:
        item = QTreeWidgetItem(parent, [row.label, row.detail])
        item.setData(0, REGION_ID_ROLE, row.region_id)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        item.setIcon(0, _swatch(row.colour))
        if not row.has_usable_axis:
            item.setToolTip(
                0,
                f"{row.label} has no usable bone axis, so only volume sliders can be built for it.",
            )

    def _region_items(self) -> tuple[QTreeWidgetItem, ...]:
        items: list[QTreeWidgetItem] = []
        for group_index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(group_index)
            items.extend(group.child(index) for index in range(group.childCount()))
        return tuple(items)

    def _set_all_checked(self, checked: bool) -> None:
        self._updating = True
        try:
            for item in self._region_items():
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        finally:
            self._updating = False
        self._emit_selection()

    def _on_item_changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        # Guarded: setCheckState during a rebuild would emit once per row.
        if not self._updating:
            self._emit_selection()

    def _emit_selection(self) -> None:
        self.regions_selected.emit(self.selected_region_ids())


def _swatch(colour: tuple[int, int, int]) -> QPixmap:
    pixmap = QPixmap(SWATCH_SIZE, SWATCH_SIZE)
    pixmap.fill(QColor(*colour))
    return pixmap
