"""The Driven bones panel: tune how a body deforms as it moves, then ship it.

This lives in the Studio rather than in its own tool because a driven bone is only
meaningful next to the things the Studio already has: the rig, the armour on it, and a
clip playing. A standalone `.papr` editor would be a spreadsheet of 1,632 numbers.

The name to resist is "jiggle". Across the twenty shipped rigs 259 chains are corrective
deformation and only 5 are jiggle, so on a player character this panel is editing how
muscles bulge and knees crease — not hair. The category column says which is which per
row rather than making the modder infer it from bone names.

Four decisions shape the panel.

**Chains, not bones.** `golem_imp_boss` has 437 entries and 13 chains. A muscle group is
one thing in the modder's head and several rows in the file, so the list shows chains and
the detail view shows what is inside one.

**Intent, not arithmetic.** Softer / Stiffer / Off are what a person actually wants; the
slider is there for when they want the number. Steps are whole percent because that is
the only shape `find_weight_sites` can locate again.

**Say what is possible.** A "What you can do here" box lists both the things this panel
can change and the things it cannot, from `constraints.CAPABILITIES`, so the limits are
visible before someone spends an hour looking for a control that does not exist.

**No fake preview.** CDMW cannot simulate secondary motion — the viewport plays the
clip's baked bone tracks, and jiggle is solved by the game at runtime. The panel says so
rather than implying that what you see is what the change will look like.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .constraints import (
    CAPABILITIES,
    LOADED_BY_GAME_WARNING,
    RigConstraints,
    changed_files,
    describe_changes,
    export_packages,
    freeze_chain,
    load_constraints,
    set_chain_strength,
)

_NO_RIG = "No constraint rig loaded for this character."
_CANNOT_PREVIEW = (
    "The viewport cannot show this. Secondary motion is solved by the game at runtime; "
    "the clip only carries the bones it animates directly. Export and look in game."
)
#: Softer/Stiffer step. Five points is roughly the smallest change worth exporting for.
_NUDGE = 5


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

        # The warning goes above everything. Somebody who reads only one line of this
        # panel should read the one that says their edit may not do anything.
        warning = QLabel(LOADED_BY_GAME_WARNING)
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "QLabel { background: #4a3a12; color: #f3e2b3; border: 1px solid #7a5f1c;"
            " padding: 6px; border-radius: 3px; }"
        )
        self._constraint_warning = warning
        outer.addWidget(warning)

        self._constraint_header = QLabel(_NO_RIG)
        self._constraint_header.setWordWrap(True)
        outer.addWidget(self._constraint_header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_chain_list())
        splitter.addWidget(self._build_chain_detail())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        # Without an explicit split the name column eats the pane and Bones/Strength/
        # Decoded end up off the right edge, which is where the useful numbers are.
        splitter.setSizes([560, 660])
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_export_row())
        return panel

    # ------------------------------------------------------------------- widgets

    def _build_chain_list(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self._chain_table = QTableWidget(0, 5)
        self._chain_table.setHorizontalHeaderLabels(
            ["Chain", "What it is", "Bones", "Strength", "Decoded"]
        )
        self._chain_table.verticalHeader().setVisible(False)
        self._chain_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._chain_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._chain_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._chain_table.setWordWrap(False)
        self._chain_table.setTextElideMode(Qt.ElideMiddle)
        header = self._chain_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._chain_table.itemSelectionChanged.connect(self._on_chain_selected)
        layout.addWidget(self._chain_table)
        return box

    def _build_chain_detail(self) -> QWidget:
        box = QWidget()
        detail = QVBoxLayout(box)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(6)

        self._chain_detail = QTableWidget(0, 3)
        self._chain_detail.setHorizontalHeaderLabels(["Driven bone", "Follows", "Weight"])
        self._chain_detail.verticalHeader().setVisible(False)
        self._chain_detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._chain_detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._chain_detail.setMinimumHeight(180)
        detail.addWidget(self._chain_detail, 3)

        intent = QHBoxLayout()
        self._chain_softer = QPushButton("Softer")
        self._chain_softer.setToolTip("Follow the body less, so the chain swings more.")
        self._chain_softer.clicked.connect(lambda: self._nudge(-_NUDGE))
        intent.addWidget(self._chain_softer)
        self._chain_stiffer = QPushButton("Stiffer")
        self._chain_stiffer.setToolTip("Follow the body more, so the chain moves less.")
        self._chain_stiffer.clicked.connect(lambda: self._nudge(_NUDGE))
        intent.addWidget(self._chain_stiffer)
        self._chain_off = QPushButton("Off")
        self._chain_off.setToolTip("Take all secondary motion out of this chain.")
        self._chain_off.clicked.connect(self._on_chain_off)
        intent.addWidget(self._chain_off)
        self._chain_reset = QPushButton("Reset")
        self._chain_reset.setToolTip("Put every chain back to what the game ships.")
        self._chain_reset.clicked.connect(self._on_chain_reset)
        intent.addWidget(self._chain_reset)
        intent.addStretch(1)
        detail.addLayout(intent)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Strength"))
        self._chain_slider = QSlider(Qt.Horizontal)
        self._chain_slider.setRange(0, 100)
        self._chain_slider.setSingleStep(1)
        self._chain_slider.setPageStep(_NUDGE)
        self._chain_slider.valueChanged.connect(self._on_strength_preview)
        self._chain_slider.sliderReleased.connect(self._on_strength_committed)
        controls.addWidget(self._chain_slider, 1)
        self._chain_value = QLabel("--")
        self._chain_value.setMinimumWidth(48)
        controls.addWidget(self._chain_value)
        detail.addLayout(controls)

        self._set_controls_enabled(False)

        # Two columns rather than one list: as a single wrapped column this box grew to
        # seven lines and squeezed the detail table down to four visible rows.
        capability = QGroupBox("What you can do here")
        columns = QHBoxLayout(capability)
        for allowed, title in ((True, "You can"), (False, "You cannot")):
            side = QVBoxLayout()
            heading = QLabel(f"<b>{title}</b>")
            side.addWidget(heading)
            for is_allowed, text in CAPABILITIES:
                if is_allowed != allowed:
                    continue
                row = QLabel("• " + text)
                row.setWordWrap(True)
                side.addWidget(row)
            side.addStretch(1)
            columns.addLayout(side, 1)
        # Keep the box to its content height; left to expand it starves the detail table.
        capability.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        detail.addWidget(capability, 0)

        self._constraint_note = QLabel(_CANNOT_PREVIEW)
        self._constraint_note.setWordWrap(True)
        detail.addWidget(self._constraint_note)
        return box

    def _build_export_row(self) -> QWidget:
        box = QGroupBox("Export as a mod")
        layout = QVBoxLayout(box)
        self._constraint_pending = QLabel("No changes.")
        self._constraint_pending.setWordWrap(True)
        layout.addWidget(self._constraint_pending)

        form = QFormLayout()
        self._constraint_mod_name = QLineEdit("Secondary motion tweak")
        form.addRow("Mod name", self._constraint_mod_name)
        self._constraint_mod_author = QLineEdit()
        form.addRow("Author", self._constraint_mod_author)
        layout.addLayout(form)

        row = QHBoxLayout()
        self._constraint_export = QPushButton("Build mod packages")
        self._constraint_export.setEnabled(False)
        self._constraint_export.clicked.connect(self._on_export_clicked)
        row.addWidget(self._constraint_export)
        self._constraint_export_note = QLabel("")
        self._constraint_export_note.setWordWrap(True)
        row.addWidget(self._constraint_export_note, 1)
        layout.addLayout(row)
        return box

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self._chain_slider, self._chain_off, self._chain_reset,
            self._chain_softer, self._chain_stiffer,
        ):
            widget.setEnabled(enabled)

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
            self._set_controls_enabled(False)
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
        counts = Counter(chain.category for chain in rig.chains)
        known = sum(1 for chain in rig.chains if chain.fully_understood)
        summary = ", ".join(
            f"{count} {name}" for name, count in counts.most_common(3)
        )
        self._constraint_header.setText(
            f"{rig.game_path} — {rig.bone_count:,} bones in {len(rig.chains)} chains "
            f"({summary}; {known} fully decoded)"
        )
        self._constraint_updating = True
        self._chain_table.setRowCount(len(rig.chains))
        for row, chain in enumerate(rig.chains):
            name_cell = QTableWidgetItem(chain.name)
            name_cell.setToolTip(f"{chain.name}\nhangs off {chain.anchor}\n{chain.label}")
            self._chain_table.setItem(row, 0, name_cell)
            kind = QTableWidgetItem(chain.category)
            kind.setToolTip(chain.label)
            self._chain_table.setItem(row, 1, kind)
            self._chain_table.setItem(row, 2, QTableWidgetItem(str(chain.bone_count)))
            self._chain_table.setItem(row, 3, QTableWidgetItem(f"{chain.strength:.0f}%"))
            mark = QTableWidgetItem("full" if chain.fully_understood else "partial")
            mark.setToolTip(
                "Every byte of this chain's config is decoded."
                if chain.fully_understood else
                "Part of this chain's config is carried through untouched. Editing the "
                "strength is still safe; those bytes are written back unchanged."
            )
            self._chain_table.setItem(row, 4, mark)
        self._constraint_updating = False
        self._refresh_pending()

    # ----------------------------------------------------------------- selection

    def _selected_chain_name(self) -> Optional[str]:
        model = self._chain_table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows:
            return None
        item = self._chain_table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _selected_chain(self):
        rig = self._rig_constraints
        name = self._selected_chain_name()
        return rig.chain_named(name) if rig and name else None

    def _on_chain_selected(self) -> None:
        if self._constraint_updating:
            return
        chain = self._selected_chain()
        self._chain_detail.setRowCount(0)
        self._set_controls_enabled(chain is not None and chain.weight_count > 0)
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

    def _nudge(self, delta: int) -> None:
        chain = self._selected_chain()
        if chain is None:
            return
        self._apply_strength(max(0, min(100, int(round(chain.strength)) + delta)))

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
        lines = describe_changes(base, rig) if rig and base else ()
        self._constraint_pending.setText(
            "No changes." if not lines else "Pending: " + "; ".join(lines)
        )
        self._constraint_export.setEnabled(bool(lines))

    def constraint_mod_files(self) -> dict:
        """`{game path: bytes}` for the packager, empty when nothing changed."""

        rig = self._rig_constraints
        if rig is None or not self._rig_constraints_bytes:
            return {}
        return dict(changed_files(self._rig_constraints_bytes, rig))

    # ------------------------------------------------------------------- export

    def export_constraint_mod(self, out_root) -> str:
        """Build the packages and return a line describing what happened."""

        rig = self._rig_constraints
        if rig is None or not self.constraint_mod_files():
            return "Nothing to export: the rig is unchanged."
        name = self._constraint_mod_name.text().strip() or "Secondary motion tweak"
        try:
            results = export_packages(
                rig,
                self._rig_constraints_bytes,
                out_root=Path(out_root),
                name=name,
                author=self._constraint_mod_author.text().strip(),
            )
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            return f"Export failed: {error}"
        if not results:
            return "Nothing to export: the rig is unchanged."
        return f"Wrote {len(results)} package(s) to {out_root}"

    def _on_export_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        out_root = QFileDialog.getExistingDirectory(None, "Where should the packages go?")
        if not out_root:
            return
        self._constraint_export_note.setText(self.export_constraint_mod(out_root))
