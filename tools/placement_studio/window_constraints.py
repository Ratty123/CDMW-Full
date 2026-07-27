"""The Secondary motion panel: tune hair, cloth and jiggle, then ship it.

This lives in the Studio rather than in its own tool because secondary motion is only
meaningful next to the things the Studio already has: the rig, the armour on it, and a
clip playing. A standalone `.papr` editor would be a spreadsheet of 1,632 numbers.

Three decisions shape the panel.

**Chains, not bones.** `golem_imp_boss` has 437 entries and 13 chains. A braid is one
thing in the modder's head and six rows in the file, so the list shows chains and the
detail view shows what is inside one.

**One slider per chain.** Nobody tunes 1,632 weights individually. The slider carries
the chain's mean influence and scales every weight in it proportionally. Steps are whole
percent because that is the only shape `find_weight_sites` can locate again.

**No fake preview.** CDMW cannot simulate secondary motion — the viewport plays the
clip's baked bone tracks, and jiggle is solved by the game at runtime. The panel says so
rather than implying that what you see is what the change will look like. You tune, you
export, you look in game.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .constraints import (
    RigConstraints,
    describe_changes,
    freeze_chain,
    load_constraints,
    set_chain_strength,
)

_NO_RIG = "No constraint rig loaded for this character."
_CANNOT_PREVIEW = (
    "The viewport cannot show this. Secondary motion is solved by the game at runtime; "
    "the clip only carries the bones it animates directly. Export and look in game."
)


class SecondaryMotionMixin:
    """The `.papr` chain editor. Mixed into `PlacementStudioWindow`."""

    def _build_secondary_motion_tab(self) -> QWidget:
        self._rig_constraints: Optional[RigConstraints] = None
        self._rig_constraints_original: Optional[RigConstraints] = None
        self._rig_constraints_bytes: bytes = b""
        self._constraint_updating = False

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self._constraint_header = QLabel(_NO_RIG)
        self._constraint_header.setWordWrap(True)
        outer.addWidget(self._constraint_header)

        splitter = QSplitter(Qt.Horizontal)

        self._chain_table = QTableWidget(0, 3)
        self._chain_table.setHorizontalHeaderLabels(["Chain", "Bones", "Strength"])
        self._chain_table.verticalHeader().setVisible(False)
        self._chain_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._chain_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._chain_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._chain_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._chain_table.itemSelectionChanged.connect(self._on_chain_selected)
        splitter.addWidget(self._chain_table)

        right = QWidget()
        detail = QVBoxLayout(right)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(6)

        self._chain_detail = QTableWidget(0, 3)
        self._chain_detail.setHorizontalHeaderLabels(["Driven bone", "Driver", "Weight"])
        self._chain_detail.verticalHeader().setVisible(False)
        self._chain_detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._chain_detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        detail.addWidget(self._chain_detail, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Strength"))
        self._chain_slider = QSlider(Qt.Horizontal)
        self._chain_slider.setRange(0, 100)
        self._chain_slider.setSingleStep(1)
        self._chain_slider.setPageStep(5)
        self._chain_slider.setEnabled(False)
        self._chain_slider.valueChanged.connect(self._on_strength_preview)
        self._chain_slider.sliderReleased.connect(self._on_strength_committed)
        controls.addWidget(self._chain_slider, 1)
        self._chain_value = QLabel("--")
        self._chain_value.setMinimumWidth(48)
        controls.addWidget(self._chain_value)
        self._chain_off = QPushButton("Off")
        self._chain_off.setEnabled(False)
        self._chain_off.clicked.connect(self._on_chain_off)
        controls.addWidget(self._chain_off)
        self._chain_reset = QPushButton("Reset")
        self._chain_reset.setEnabled(False)
        self._chain_reset.clicked.connect(self._on_chain_reset)
        controls.addWidget(self._chain_reset)
        detail.addLayout(controls)

        self._constraint_note = QLabel(_CANNOT_PREVIEW)
        self._constraint_note.setWordWrap(True)
        detail.addWidget(self._constraint_note)

        self._constraint_pending = QLabel("No changes.")
        self._constraint_pending.setWordWrap(True)
        detail.addWidget(self._constraint_pending)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)
        return panel

    # ------------------------------------------------------------------ loading

    def load_constraint_rig(self, data: bytes, game_path: str) -> Optional[str]:
        """Show a rig. Returns an error message, or None when it loaded."""

        try:
            rig = load_constraints(data, game_path)
        except Exception as error:  # noqa: BLE001 - a bad rig must not close the window
            self._rig_constraints = None
            self._rig_constraints_original = None
            self._constraint_header.setText(f"{game_path}: {error}")
            self._chain_table.setRowCount(0)
            self._chain_detail.setRowCount(0)
            return str(error)
        self._rig_constraints = rig
        self._rig_constraints_original = rig
        self._rig_constraints_bytes = bytes(data)
        self._refresh_chain_table()
        return None

    def _refresh_chain_table(self) -> None:
        rig = self._rig_constraints
        if rig is None:
            return
        soft = sum(1 for chain in rig.chains if chain.soft)
        self._constraint_header.setText(
            f"{rig.game_path} — {rig.bone_count:,} bones, {len(rig.chains)} chains "
            f"({soft} look like hair or cloth)"
        )
        self._constraint_updating = True
        self._chain_table.setRowCount(len(rig.chains))
        for row, chain in enumerate(rig.chains):
            self._chain_table.setItem(row, 0, QTableWidgetItem(chain.name))
            self._chain_table.setItem(row, 1, QTableWidgetItem(str(chain.bone_count)))
            self._chain_table.setItem(row, 2, QTableWidgetItem(f"{chain.strength:.0f}%"))
        self._constraint_updating = False
        self._refresh_pending()

    # ----------------------------------------------------------------- selection

    def _selected_chain_name(self) -> Optional[str]:
        rows = self._chain_table.selectionModel().selectedRows() if self._chain_table.selectionModel() else []
        if not rows:
            return None
        item = self._chain_table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _on_chain_selected(self) -> None:
        if self._constraint_updating:
            return
        rig = self._rig_constraints
        name = self._selected_chain_name()
        chain = rig.chain_named(name) if rig and name else None
        self._chain_detail.setRowCount(0)
        enabled = chain is not None and chain.weight_count > 0
        for widget in (self._chain_slider, self._chain_off, self._chain_reset):
            widget.setEnabled(enabled)
        if chain is None:
            self._chain_value.setText("--")
            return
        rows = [(m.name, site.bone, site.value) for m in chain.members for site in m.weights]
        self._chain_detail.setRowCount(len(rows))
        for row, (driven, driver, value) in enumerate(rows):
            self._chain_detail.setItem(row, 0, QTableWidgetItem(driven))
            self._chain_detail.setItem(row, 1, QTableWidgetItem(driver))
            self._chain_detail.setItem(row, 2, QTableWidgetItem(f"{value:.0f}%"))
        self._constraint_updating = True
        self._chain_slider.setValue(int(round(chain.strength)))
        self._constraint_updating = False
        self._chain_value.setText(f"{chain.strength:.0f}%")

    # -------------------------------------------------------------------- edits

    def _on_strength_preview(self, value: int) -> None:
        """Label tracks the slider; the file is only touched on release."""

        self._chain_value.setText(f"{value}%")

    def _on_strength_committed(self) -> None:
        self._apply_strength(self._chain_slider.value())

    def _apply_strength(self, value: int) -> None:
        rig = self._rig_constraints
        name = self._selected_chain_name()
        if rig is None or not name:
            return
        chain = rig.chain_named(name)
        if chain is None or chain.strength <= 0:
            return
        try:
            self._rig_constraints = set_chain_strength(rig, name, float(value))
        except Exception as error:  # noqa: BLE001
            self._constraint_pending.setText(f"Could not apply: {error}")
            return
        self._refresh_chain_table()
        self._reselect(name)

    def _on_chain_off(self) -> None:
        rig = self._rig_constraints
        name = self._selected_chain_name()
        if rig is None or not name:
            return
        self._rig_constraints = freeze_chain(rig, name)
        self._refresh_chain_table()
        self._reselect(name)

    def _on_chain_reset(self) -> None:
        if self._rig_constraints_original is None:
            return
        name = self._selected_chain_name()
        self._rig_constraints = self._rig_constraints_original
        self._refresh_chain_table()
        if name:
            self._reselect(name)

    def _reselect(self, name: str) -> None:
        for row in range(self._chain_table.rowCount()):
            item = self._chain_table.item(row, 0)
            if item and item.text() == name:
                self._chain_table.selectRow(row)
                return
        self._on_chain_selected()

    # ------------------------------------------------------------------ pending

    def _refresh_pending(self) -> None:
        rig = self._rig_constraints
        base = self._rig_constraints_original
        if rig is None or base is None:
            self._constraint_pending.setText("No changes.")
            return
        lines = describe_changes(base, rig)
        self._constraint_pending.setText(
            "No changes." if not lines else "Pending: " + "; ".join(lines)
        )

    def constraint_mod_files(self) -> dict:
        """`{game path: bytes}` for the packager, empty when nothing changed."""

        from .constraints import changed_files

        rig = self._rig_constraints
        if rig is None or not self._rig_constraints_bytes:
            return {}
        return dict(changed_files(self._rig_constraints_bytes, rig))
