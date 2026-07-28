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
visible before someone spends an hour looking for a control that does not exist. Above
it, `WHAT_THIS_TAB_IS_FOR` answers the question the warning provokes — if the game may
not read this, why is the tab here — and points at Rig behaviour for changes that stick.

**No fake preview.** CDMW cannot simulate secondary motion — the viewport plays the
clip's baked bone tracks, and jiggle is solved by the game at runtime. The panel says so
rather than implying that what you see is what the change will look like.

**Nothing may wrap or clip.** The Studio gives its tab column about 620px and the panel
about 780px, and every element here competed for it: side-by-side tables left the chain
list one truncated column wide, a form-per-field export box spent 200px on two text
inputs, and the capability bullets lost their second lines to a `QSizePolicy.Maximum`
group box. So the tables stack, the export row is one line, and anything that would need
to wrap is either short enough not to, or a tooltip. Verify this panel by rendering it,
not by reading the code: the failure mode is text that is present in the widget tree and
absent from the screen.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .table_columns import proportional_columns
from .constraints import (
    CAPABILITIES,
    LOADED_BY_GAME_EVIDENCE,
    LOADED_BY_GAME_WARNING,
    WHAT_THIS_TAB_IS_FOR,
    RigConstraints,
    changed_files,
    constraint_path_for_model,
    describe_changes,
    export_packages,
    freeze_chain,
    load_constraints,
    set_chain_strength,
)

_NO_RIG = "No constraint rig loaded for this character."
#: Shown when the panel followed the Studio's character and there is genuinely nothing
#: there. "Not loaded" reads as a tool that failed; this says whose fault it is.
_NO_RIG_FOR_MODEL = (
    "{label} does not ship a .papr, so there is nothing to tune here. Only {count} of the "
    "game's characters have one — the four playable rigs and sixteen creatures. Pick one "
    "of those to see this tab populated, or use Rig behaviour, which covers every rig."
)
#: One line, not a paragraph. The reason lives in `WHAT_THIS_TAB_IS_FOR` at the top of the
#: panel; repeating it at full length here cost 60px that the controls needed.
_CANNOT_PREVIEW = "The viewport cannot show this — export and look in game."
#: Softer/Stiffer step. Five points is roughly the smallest change worth exporting for.
_NUDGE = 5




def _chain_detail_rows(chain) -> list[tuple[str, str, str, str]]:
    """One row per weight site, plus a row for any bone that only carries a formula.

    Keying rows off weight sites alone hid every expression-only bone -- a driven bone
    with a formula and no influence weight had nothing to appear as, so the detail table
    said the chain was empty when it was the interesting kind.
    """

    rows: list[tuple[str, str, str, str]] = []
    for member in chain.members:
        formulas = list(member.formulas)
        if member.weights:
            for index, site in enumerate(member.weights):
                rows.append((
                    member.name,
                    site.bone,
                    f"{site.value:.0f}%",
                    formulas[index] if index < len(formulas) else "",
                ))
            continue
        for formula in formulas or [""]:
            rows.append((member.name, "—", "—", formula))
    return rows


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
        warning.setToolTip(LOADED_BY_GAME_EVIDENCE)
        warning.setStyleSheet(
            "QLabel { background: #4a3a12; color: #f3e2b3; border: 1px solid #7a5f1c;"
            " padding: 6px; border-radius: 3px; }"
        )
        self._constraint_warning = warning
        outer.addWidget(warning)

        # Directly under the warning, because "so what is this tab for" is the question the
        # warning provokes, and it went unanswered when this sat at the bottom of the panel.
        purpose = QLabel(WHAT_THIS_TAB_IS_FOR)
        purpose.setWordWrap(True)
        purpose.setStyleSheet("QLabel { color: #9fb4c7; }")
        outer.addWidget(purpose)

        self._constraint_header = QLabel(_NO_RIG)
        self._constraint_header.setWordWrap(True)
        outer.addWidget(self._constraint_header)

        # Stacked, not side by side. The Studio gives its tab column about 620px, and two
        # panes at that width left the chain list showing one truncated column -- the
        # Bones/Strength/Decoded numbers were off the right edge, and so was half of each
        # chain name. Full width for both tables is worth more than seeing them together.
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_chain_list())
        splitter.addWidget(self._build_chain_detail())
        splitter.setChildrenCollapsible(False)
        # The chain list gets the larger share, and a QSplitter keeps this ratio as the
        # window grows -- stretch factors do not override it. The list holds 13 to 71 rows
        # and is what you scroll to find anything; the detail shows one chain, 2 to 8 rows,
        # so the old 260:420 split left blank space under the detail's last row on a tall
        # window while the list stayed scrolled.
        splitter.setSizes([460, 300])
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
        # Chain names are the long value and get the largest share, but not all of it:
        # stretching column 0 alone left it 810px wide and mostly empty while the four
        # columns carrying the numbers were squeezed against the right edge.
        proportional_columns(
            self._chain_table,
            weights=(42, 18, 10, 15, 15),
            minimums=(116, 80, 46, 62, 66),
        )
        self._chain_table.itemSelectionChanged.connect(self._on_chain_selected)
        # A rig has 13 to 71 chains, and this is the list you pick from. Given no floor the
        # detail pane below claims everything and leaves this one visible row.
        self._chain_table.setMinimumHeight(150)
        layout.addWidget(self._chain_table)
        return box

    def _build_chain_detail(self) -> QWidget:
        box = QWidget()
        detail = QVBoxLayout(box)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(6)

        # Formula is the point of this table now that `papr_block` decodes the expression
        # payload: "follows Bip01 L Calf" is a fact, "at 5.5x its Z rotation, clamped at 8"
        # is the thing a modder came to change.
        self._chain_detail = QTableWidget(0, 4)
        self._chain_detail.setHorizontalHeaderLabels(
            ["Driven bone", "Follows", "Weight", "Formula"]
        )
        self._chain_detail.verticalHeader().setVisible(False)
        self._chain_detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Driven bone and Follows hold the same kind of value -- a bone name -- so they get
        # the same share. Stretching only the first elided `P_Bip01 L Clavicle_Sub` into
        # `P_Bip01 L ...` while 600px sat unused in the column beside it.
        proportional_columns(
            self._chain_detail, weights=(26, 26, 10, 38), minimums=(96, 96, 52, 120)
        )
        # Four rows plus a header. Any taller a floor and this pane starves the chain list
        # above it, which is the one you have to pick from before this fills at all.
        self._chain_detail.setMinimumHeight(110)
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
        detail.addWidget(self._build_capability_box(), 0)

        self._constraint_note = QLabel(_CANNOT_PREVIEW)
        self._constraint_note.setWordWrap(True)
        detail.addWidget(self._constraint_note)
        return box

    def _build_capability_box(self) -> QWidget:
        """The can/cannot summary. Nothing in it is allowed to wrap.

        This box used to lose text. Word-wrapped `QLabel`s report a one-line `sizeHint`,
        the group box was pinned to that hint by `QSizePolicy.Maximum`, and every bullet
        long enough to wrap had its tail cut off -- "follows its drivers" and "warning
        above" both vanished mid-panel, and one whole row with them.

        The fix is to remove the wrapping rather than to out-guess the height: the labels
        are short enough for one line (`CAPABILITIES` is gated on 30 characters), wrapping
        is off so a narrow panel elides instead of silently dropping a row, and the reason
        for each entry is on the tooltip where it costs no height at all.
        """

        box = QGroupBox("What you can do here")
        columns = QHBoxLayout(box)
        columns.setContentsMargins(8, 6, 8, 6)
        for allowed, title in ((True, "You can"), (False, "You cannot")):
            side = QVBoxLayout()
            side.setSpacing(2)
            side.addWidget(QLabel(f"<b>{title}</b>"))
            for is_allowed, text, why in CAPABILITIES:
                if is_allowed != allowed:
                    continue
                mark = "✓" if allowed else "✗"
                row = QLabel(f"{mark} {text}")
                row.setWordWrap(False)
                row.setToolTip(why)
                side.addWidget(row)
            side.addStretch(1)
            columns.addLayout(side, 1)
        self._constraint_capability = box
        return box

    def _build_export_row(self) -> QWidget:
        """Name, author and the button on one line.

        A `QFormLayout` with its own row per field spent about 200px of a 780px panel on
        two text boxes, which is what forced the chain list down to a single visible row.
        Placeholders carry the labels instead.
        """

        box = QGroupBox("Export as a mod")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self._constraint_pending = QLabel("No changes.")
        self._constraint_pending.setWordWrap(True)
        layout.addWidget(self._constraint_pending)

        row = QHBoxLayout()
        self._constraint_mod_name = QLineEdit("Secondary motion tweak")
        self._constraint_mod_name.setPlaceholderText("Mod name")
        self._constraint_mod_name.setToolTip("Mod name, as the mod manager will list it.")
        row.addWidget(self._constraint_mod_name, 3)
        self._constraint_mod_author = QLineEdit()
        self._constraint_mod_author.setPlaceholderText("Author")
        self._constraint_mod_author.setToolTip("Your name, written into the package metadata.")
        row.addWidget(self._constraint_mod_author, 2)
        self._constraint_export = QPushButton("Build")
        self._constraint_export.setToolTip("Write one package per supported mod manager.")
        self._constraint_export.setEnabled(False)
        self._constraint_export.clicked.connect(self._on_export_clicked)
        row.addWidget(self._constraint_export)
        layout.addLayout(row)

        self._constraint_export_note = QLabel("")
        self._constraint_export_note.setWordWrap(True)
        layout.addWidget(self._constraint_export_note)
        return box

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self._chain_slider, self._chain_off, self._chain_reset,
            self._chain_softer, self._chain_stiffer,
        ):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------------ loading

    def show_constraints_for(self, rig_files, rig_path: str, label: str) -> Optional[str]:
        """Point the panel at whichever `.papr` belongs to the character on screen.

        `rig_path` is the character's `.pab`, not its model id: a customization variant
        runs on the base rig's skeleton, and the `.papr` sits beside that skeleton. Returns
        an error message, or None when a rig loaded or none exists.
        """

        self._constraint_rig_shown = rig_path
        path = constraint_path_for_model(rig_path, rig_files.constraint_paths)
        data = rig_files.constraints.get(path or "", b"")
        if not path or not data:
            self._clear_constraints(
                _NO_RIG_FOR_MODEL.format(
                    label=label or "This character", count=len(rig_files.constraint_paths)
                )
            )
            return None
        return self.load_constraint_rig(data, path)

    def _clear_constraints(self, message: str) -> None:
        self._rig_constraints = None
        self._rig_constraints_original = None
        self._rig_constraints_bytes = b""
        self._constraint_header.setText(message)
        self._chain_table.setRowCount(0)
        self._chain_detail.setRowCount(0)
        self._set_controls_enabled(False)
        self._refresh_pending()

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
        # Land on a chain rather than on an empty detail pane and dead buttons. The list is
        # sorted with the categories worth tuning first, so row 0 is a reasonable answer to
        # "show me what this tab does".
        if self._chain_table.rowCount() and not self._selected_chain_name():
            self._chain_table.selectRow(0)
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
        rows = _chain_detail_rows(chain)
        self._chain_detail.setRowCount(len(rows))
        for row, (driven, driver, weight, formula) in enumerate(rows):
            self._chain_detail.setItem(row, 0, QTableWidgetItem(driven))
            self._chain_detail.setItem(row, 1, QTableWidgetItem(driver))
            self._chain_detail.setItem(row, 2, QTableWidgetItem(weight))
            cell = QTableWidgetItem(formula)
            cell.setToolTip(formula or "No expression on this bone.")
            self._chain_detail.setItem(row, 3, cell)
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
