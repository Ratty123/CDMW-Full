"""The Rig behaviour panel: edit the pose-modifier settings the game actually runs.

`posemodifierdata.xml` holds 2,779 settings across 98 skeletons. Showing all of them
would be a spreadsheet; showing the 223 that apply to the character on screen is a tool.
So the panel keys on a skeleton and everything else follows from that.

Three things it insists on.

**Say which rig you are editing.** One block in the file serves several characters, so a
change to the player's LookAt also changes it for `phw_01`, `ptm_01` and `pdem_01`. The
Applies-to column names every skeleton sharing the block, because that is a consequence
a modder cannot see in the file and will not expect.

**Say when a section is switched off.** The file carries a `DisabledKeyList` per
section. Editing LookAt for a creature listed there produces no effect and no
explanation, so the panel refuses to hide it.

**Values are text, not floats.** A range is `-45 57` and a vector is `8 8 30`. The value
box takes the value as written and the multiply buttons scale every number in it while
keeping the shape, rather than collapsing a range into one number.

**The rig comes from the Studio, not from the user.** `show_rig_behaviour_for` keys on
the character's resolved `.pab`, so opening the tab already shows the character on
screen. When that skeleton has no block of its own the panel says which rig it fell back
to and that editing it will not change the viewport — silently showing another
character's settings is the one outcome worth going out of the way to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .table_columns import proportional_columns
from .what_is_this import guide_strip
from .rig_behaviour import (
    GAME_PATH,
    SECTION_LABELS,
    PoseModifierError,
    RigBehaviour,
    apply_edit,
    apply_scale,
    describe_changes,
    export_packages,
    load_rig_behaviour,
    pab_for_model,
)
from .rig_behaviour import guide as behaviour_guide

_ALL = "All sections"
_NOT_LOADED = "Pose-modifier descriptor not loaded."
#: The descriptor is one file for the whole game, so "not in the archives" is the only
#: way this panel can be empty -- and it means the install is not what we expect.
_NO_DESCRIPTOR = (
    "The archives do not contain {path}. Rig behaviour has nothing to edit without it; "
    "check that the game directory is a full install."
)


class RigBehaviourMixin:
    """The `posemodifierdata.xml` editor. Mixed into `PlacementStudioWindow`."""

    def _build_rig_behaviour_tab(self) -> QWidget:
        self._behaviour: Optional[RigBehaviour] = None
        self._behaviour_original: Optional[RigBehaviour] = None
        self._behaviour_updating = False

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # The counterpart to Driven bones' strip, and deliberately the other badge:
        # this file the engine demonstrably reads.
        self._guide = behaviour_guide()
        strip, badge, button = guide_strip(self._guide, panel)
        self._behaviour_badge = badge
        self._behaviour_guide_button = button
        outer.addWidget(strip)

        self._behaviour_header = QLabel(_NOT_LOADED)
        self._behaviour_header.setWordWrap(True)
        outer.addWidget(self._behaviour_header)

        self._behaviour_disabled = QLabel("")
        self._behaviour_disabled.setWordWrap(True)
        self._behaviour_disabled.setStyleSheet(
            "QLabel { background: #4a3a12; color: #f3e2b3; border: 1px solid #7a5f1c;"
            " padding: 5px; border-radius: 3px; }"
        )
        self._behaviour_disabled.setVisible(False)
        outer.addWidget(self._behaviour_disabled)

        picker = QHBoxLayout()
        picker.addWidget(QLabel("Skeleton"))
        self._behaviour_rig = QComboBox()
        self._behaviour_rig.setMinimumContentsLength(24)
        self._behaviour_rig.currentIndexChanged.connect(self._on_behaviour_rig_changed)
        picker.addWidget(self._behaviour_rig, 3)
        picker.addWidget(QLabel("Section"))
        self._behaviour_section = QComboBox()
        # Long enough for "WorldSpaceSpecificBoneModifier"; the default clipped even
        # "All sections" into "All sectio".
        self._behaviour_section.setMinimumContentsLength(18)
        self._behaviour_section.currentIndexChanged.connect(self._refresh_behaviour_table)
        picker.addWidget(self._behaviour_section, 3)
        outer.addLayout(picker)

        # Four columns, not five. At the width the Studio gives its tab column, five pushed
        # Applies-to off the right edge and middle-elided the Setting column into
        # `DefaultData/ArmP...and · LeftHand` -- the unreadable half of both ends. Note is a
        # source comment, often Korean, so it earns a tooltip rather than a column.
        self._behaviour_table = QTableWidget(0, 4)
        self._behaviour_table.setHorizontalHeaderLabels(
            ["Section", "Setting", "Value", "Applies to"]
        )
        self._behaviour_table.verticalHeader().setVisible(False)
        self._behaviour_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._behaviour_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._behaviour_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._behaviour_table.setWordWrap(False)
        # Elide the tail, not the middle: each cell now leads with the leaf name, so what
        # gets trimmed is the path prefix rather than the part you scan for.
        self._behaviour_table.setTextElideMode(Qt.ElideRight)
        # Fixed shares rather than one stretching column. `ResizeToContents` on Value let a
        # single long string claim 350px and squeeze the stretching Setting column down to
        # "ettin"; stretching Setting alone does the reverse at a wide window, leaving Value
        # narrow enough to elide a vector while Setting sits half empty.
        proportional_columns(
            self._behaviour_table,
            weights=(14, 44, 27, 15),
            minimums=(64, 132, 96, 74),
        )
        self._behaviour_table.itemSelectionChanged.connect(self._on_behaviour_selected)
        outer.addWidget(self._behaviour_table, 1)

        self._behaviour_what = QLabel("")
        self._behaviour_what.setWordWrap(True)
        outer.addWidget(self._behaviour_what)

        edit = QHBoxLayout()
        edit.addWidget(QLabel("Value"))
        self._behaviour_value = QLineEdit()
        self._behaviour_value.setEnabled(False)
        # A range is `-45 57` and a vector `8 8 30`. Five buttons on the same row squeezed
        # this to about 30px, too narrow to read back what you had typed.
        self._behaviour_value.setMinimumWidth(120)
        self._behaviour_value.setToolTip(
            "The value as the file writes it. A range is two numbers, a vector three; "
            "the multiply buttons scale every number and keep the shape."
        )
        self._behaviour_value.returnPressed.connect(self._on_behaviour_apply)
        edit.addWidget(self._behaviour_value, 1)
        self._behaviour_apply = QPushButton("Apply")
        self._behaviour_apply.setEnabled(False)
        self._behaviour_apply.clicked.connect(self._on_behaviour_apply)
        edit.addWidget(self._behaviour_apply)
        outer.addLayout(edit)

        # The scale buttons get their own row. Seven widgets on one line came to more than
        # the ~620px the panel has, and Qt resolves that by drawing them over each other --
        # Apply landed on top of the value box, over the text you were about to edit.
        scale = QHBoxLayout()
        for text, factor in (("×2", 2.0), ("×1.5", 1.5), ("÷2", 0.5)):
            button = QPushButton(text)
            button.setToolTip("Scale every number in the value, keeping its shape.")
            button.setEnabled(False)
            button.clicked.connect(lambda _c=False, f=factor: self._on_behaviour_scale(f))
            scale.addWidget(button)
            self._behaviour_scalers = getattr(self, "_behaviour_scalers", [])
            self._behaviour_scalers.append(button)
        scale.addStretch(1)
        self._behaviour_reset = QPushButton("Reset all")
        self._behaviour_reset.setToolTip("Put every setting back to what the game ships.")
        self._behaviour_reset.clicked.connect(self._on_behaviour_reset)
        scale.addWidget(self._behaviour_reset)
        outer.addLayout(scale)

        outer.addWidget(self._build_behaviour_export())
        return panel

    def _build_behaviour_export(self) -> QWidget:
        """Name, author and the button on one line, as in Driven bones.

        A row per field cost about 200px of panel height for two text boxes; placeholders
        carry the labels instead.
        """

        box = QGroupBox("Export as a mod")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self._behaviour_pending = QLabel("No changes.")
        self._behaviour_pending.setWordWrap(True)
        layout.addWidget(self._behaviour_pending)

        row = QHBoxLayout()
        self._behaviour_name = QLineEdit("Rig behaviour tweak")
        self._behaviour_name.setPlaceholderText("Mod name")
        self._behaviour_name.setToolTip("Mod name, as the mod manager will list it.")
        row.addWidget(self._behaviour_name, 3)
        self._behaviour_author = QLineEdit()
        self._behaviour_author.setPlaceholderText("Author")
        self._behaviour_author.setToolTip("Your name, written into the package metadata.")
        row.addWidget(self._behaviour_author, 2)
        self._behaviour_export = QPushButton("Build")
        self._behaviour_export.setToolTip("Write one package per supported mod manager.")
        self._behaviour_export.setEnabled(False)
        self._behaviour_export.clicked.connect(self._on_behaviour_export_clicked)
        row.addWidget(self._behaviour_export)
        layout.addLayout(row)

        self._behaviour_export_note = QLabel("")
        self._behaviour_export_note.setWordWrap(True)
        layout.addWidget(self._behaviour_export_note)
        return box

    # ------------------------------------------------------------------ loading

    def show_rig_behaviour_for(self, rig_files, rig_path: str, label: str) -> Optional[str]:
        """Load the descriptor and preselect the skeleton the Studio is showing.

        `rig_path` is the character's `.pab`; `pab_for_model` keys on its stem, so a
        variant that shares a base rig lands on the base rig's block rather than on
        nothing.
        """

        self._behaviour_shown_label = label
        if not rig_files.pose_modifier:
            self._behaviour_header.setText(_NO_DESCRIPTOR.format(path=GAME_PATH))
            self._behaviour_table.setRowCount(0)
            return None
        return self.load_rig_behaviour_data(rig_files.pose_modifier, rig_path)

    def load_rig_behaviour_data(self, data: bytes, model: str = "") -> Optional[str]:
        """Show the descriptor. Returns an error message, or None when it loaded."""

        try:
            rig = load_rig_behaviour(data)
        except Exception as error:  # noqa: BLE001 - never take the window down
            self._behaviour = None
            self._behaviour_header.setText(f"{GAME_PATH}: {error}")
            self._behaviour_table.setRowCount(0)
            return str(error)
        keys = rig.selectable_keys()
        matched = pab_for_model(model, keys)
        # Falling back to the first key silently shows another character's settings, which
        # a modder would take for their own. Record that it happened so the header can say.
        self._behaviour_matched_character = bool(matched)
        chosen = matched or (keys[0] if keys else "")
        self._behaviour = load_rig_behaviour(data, chosen)
        self._behaviour_original = self._behaviour

        self._behaviour_updating = True
        self._behaviour_rig.clear()
        self._behaviour_rig.addItems(list(keys))
        if chosen in keys:
            self._behaviour_rig.setCurrentIndex(keys.index(chosen))
        self._behaviour_updating = False
        self._refresh_behaviour_sections()
        return None

    def _refresh_behaviour_sections(self) -> None:
        rig = self._behaviour
        if rig is None:
            return
        self._behaviour_updating = True
        self._behaviour_section.clear()
        self._behaviour_section.addItem(_ALL)
        self._behaviour_section.addItems(list(rig.sections))
        self._behaviour_updating = False
        self._refresh_behaviour_table()

    def _on_behaviour_rig_changed(self) -> None:
        if self._behaviour_updating or self._behaviour is None:
            return
        pab = self._behaviour_rig.currentText()
        self._behaviour = RigBehaviour(
            document=self._behaviour.document, pab=pab, original=self._behaviour.original
        )
        self._refresh_behaviour_sections()

    def _refresh_behaviour_table(self) -> None:
        rig = self._behaviour
        if rig is None or self._behaviour_updating:
            return
        wanted = self._behaviour_section.currentText()
        rows = [s for s in rig.settings if wanted in (_ALL, "", s.section)]
        self._behaviour_rows = rows

        off = rig.disabled_sections()
        if off:
            self._behaviour_disabled.setText(
                "Switched off for this skeleton: " + ", ".join(off)
                + ". The file lists it in DisabledKeyList, so edits to those sections "
                  "will not take effect for this character."
            )
        self._behaviour_disabled.setVisible(bool(off))

        header = (
            f"{GAME_PATH} — {len(rig.document.settings):,} settings over "
            f"{len(rig.document.keys())} skeletons; {len(rig.settings)} apply to "
            f"{rig.pab or 'any rig'}"
        )
        label = getattr(self, "_behaviour_shown_label", "")
        if label and not getattr(self, "_behaviour_matched_character", True):
            header += (
                f". {label} has no block of its own, so this is {rig.pab} — a different "
                "rig. Editing it will not change the character in the viewport."
            )
        elif label and not rows:
            header += f". Nothing keyed to {rig.pab}; it uses the engine defaults."
        self._behaviour_header.setText(header)

        self._behaviour_updating = True
        self._behaviour_table.setRowCount(len(rows))
        for index, setting in enumerate(rows):
            section = QTableWidgetItem(setting.section)
            section.setToolTip(SECTION_LABELS.get(setting.section, setting.section))
            self._behaviour_table.setItem(index, 0, section)
            # Leaf name first. Leading with the path put every row's readable identity
            # past the elision point, so a screenful of settings all looked alike.
            name = QTableWidgetItem(f"{setting.label}   {setting.path}")
            tip = setting.path
            if setting.note:
                tip += f"\n\nComment in the file: {setting.note}"
            name.setToolTip(tip)
            self._behaviour_table.setItem(index, 1, name)
            self._behaviour_table.setItem(index, 2, QTableWidgetItem(setting.value))
            shared = ", ".join(setting.keys)
            applies = QTableWidgetItem(f"{len(setting.keys)} rig(s)")
            applies.setToolTip(shared or "no skeleton list on this block")
            self._behaviour_table.setItem(index, 3, applies)
        self._behaviour_updating = False
        # Land on a row, so the value box and the "who else does this affect" line are
        # populated rather than blank with everything greyed out.
        if rows and not self._behaviour_table.selectionModel().hasSelection():
            self._behaviour_table.selectRow(0)
        self._refresh_behaviour_pending()

    # ---------------------------------------------------------------- selection

    def _selected_setting(self):
        model = self._behaviour_table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows:
            return None
        index = rows[0].row()
        rows_cache = getattr(self, "_behaviour_rows", [])
        return rows_cache[index] if 0 <= index < len(rows_cache) else None

    def _on_behaviour_selected(self) -> None:
        if self._behaviour_updating:
            return
        setting = self._selected_setting()
        enabled = setting is not None
        self._behaviour_value.setEnabled(enabled)
        self._behaviour_apply.setEnabled(enabled)
        for button in getattr(self, "_behaviour_scalers", []):
            button.setEnabled(bool(setting and setting.numeric))
        if setting is None:
            self._behaviour_value.clear()
            self._behaviour_what.setText("")
            return
        self._behaviour_value.setText(setting.value)
        shared = ", ".join(setting.keys) or "no skeleton list"
        self._behaviour_what.setText(
            f"{SECTION_LABELS.get(setting.section, setting.section)} — "
            f"changing this also changes it for: {shared}"
        )

    # -------------------------------------------------------------------- edits

    def _on_behaviour_apply(self) -> None:
        setting = self._selected_setting()
        rig = self._behaviour
        if setting is None or rig is None:
            return
        try:
            self._behaviour = apply_edit(rig, setting, self._behaviour_value.text())
        except PoseModifierError as error:
            self._behaviour_pending.setText(f"Could not apply: {error}")
            return
        self._refresh_behaviour_table()

    def _on_behaviour_scale(self, factor: float) -> None:
        setting = self._selected_setting()
        rig = self._behaviour
        if setting is None or rig is None:
            return
        try:
            self._behaviour = apply_scale(rig, setting, factor)
        except PoseModifierError as error:
            self._behaviour_pending.setText(f"Could not scale: {error}")
            return
        self._refresh_behaviour_table()

    def _on_behaviour_reset(self) -> None:
        if self._behaviour_original is None:
            return
        self._behaviour = self._behaviour_original
        self._refresh_behaviour_table()

    def _refresh_behaviour_pending(self) -> None:
        rig, base = self._behaviour, self._behaviour_original
        lines = describe_changes(base, rig) if rig and base else ()
        self._behaviour_pending.setText(
            "No changes." if not lines
            else f"{len(lines)} change(s): " + "; ".join(lines[:4])
            + ("..." if len(lines) > 4 else "")
        )
        self._behaviour_export.setEnabled(bool(lines))

    # ------------------------------------------------------------------- export

    def rig_behaviour_mod_files(self) -> dict:
        rig = self._behaviour
        return dict(rig.changed()) if rig else {}

    def export_rig_behaviour_mod(self, out_root) -> str:
        rig = self._behaviour
        if rig is None or not rig.changed():
            return "Nothing to export: the descriptor is unchanged."
        try:
            results = export_packages(
                rig,
                out_root=Path(out_root),
                name=self._behaviour_name.text().strip() or "Rig behaviour tweak",
                author=self._behaviour_author.text().strip(),
            )
        except Exception as error:  # noqa: BLE001
            return f"Export failed: {error}"
        return f"Wrote {len(results)} package(s) to {out_root}"

    def _on_behaviour_export_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        out_root = QFileDialog.getExistingDirectory(None, "Where should the packages go?")
        if not out_root:
            return
        self._behaviour_export_note.setText(self.export_rig_behaviour_mod(out_root))
