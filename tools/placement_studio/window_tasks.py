"""The window's task layout: header, display strip, Position and Advanced.

Placement & Animations grew one control at a time, and every control landed where there was
room: 37 on screen at first open, 84 in the window, a tree of bone names as the first thing to
read, and every editing button disabled until a socket had been found in that tree. Moving a
weapon, adjusting it and saving it were spread across a header, a strip under the view, seven
tabs and four different ways to write output.

The layout is organised by what a person came to do instead:

* **Position** -- what to work on, where it is carried, fine-tuning, and checking the fit.
* **Animations** -- give the weapon other animations, and watch any clip.
* **Armour** -- try the item against real gear.
* **Your mod** -- every change in plain words, and the one button that saves them.
* **Advanced** -- attach points, Driven bones, Rig behaviour, action charts and file changes.

The controls themselves, and everything they do, still belong to the mixins that built them;
this module only decides where they sit and which attach point the editing controls act on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .clip_names import part_label, socket_label

#: The drag modes offered on the Position tab; the two that create or re-route are Advanced.
_SIMPLE_MODES = (
    ("off", "Look around", "Drag to turn the view. Nothing changes."),
    ("move", "Move", "Drag the selected point to move it."),
    ("rotate", "Rotate", "Drag to turn the selected point."),
    ("tilt", "Tilt", "Drag to roll the item along its own length."),
)
_ADVANCED_MODES = (
    ("route", "Click a point to hang the item there",
     "Then click an attach point in the view: the selected item hangs there when it is shown "
     "the way the Show it setting says."),
    ("pick", "Click the body to add an attach point",
     "Then click the body where the new point should sit."),
)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintLabel")
    label.setWordWrap(True)
    return label


class TaskPanelMixin:
    """Where every control sits. Mixed into `PlacementStudioWindow`."""

    # ── header and display strip ────────────────────────────────────

    def _build_header(self) -> QWidget:
        """What is on screen, the undo pair, and how much is waiting to be saved."""

        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 6, 8, 4)
        row.addWidget(QLabel("Character:"))
        row.addWidget(self._model_box, 2)
        row.addSpacing(12)
        row.addWidget(QLabel("Weapon:"))
        row.addWidget(self._weapon_box, 3)
        row.addSpacing(16)
        row.addWidget(self._undo_button)
        row.addWidget(self._redo_button)
        row.addSpacing(8)
        self._mod_summary_button = QPushButton("Your mod: no changes")
        self._mod_summary_button.setToolTip(
            "Everything you have changed. Open it to review the changes and save them as a mod."
        )
        self._mod_summary_button.clicked.connect(self._open_mod_tab)
        row.addWidget(self._mod_summary_button)
        return header

    def _build_view_strip(self) -> QWidget:
        """What the view draws. Plain names; the old ones were the rig's own vocabulary."""

        self._show_bones.setText("Skeleton")
        self._show_unused.setText("Spare attach points")
        self._show_meshes.setText("Body and gear")
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(8, 2, 8, 2)
        row.addWidget(QLabel("Show:"))
        for box in (self._show_bones, self._show_labels, self._show_unused,
                    self._show_meshes, self._solid_body):
            row.addWidget(box)
        row.addStretch(1)
        return strip

    # ── Position ────────────────────────────────────────────────────

    def _build_position_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        layout.addWidget(_hint(
            "Choose what to work on, where it is carried, then fine-tune it. Every change is "
            "listed under Your mod until you save it; nothing touches the game before that."
        ))

        subject = QGroupBox("1. What to work on")
        form = QFormLayout(subject)
        self._mesh_role_box.setItemText(0, "In hand")
        self._mesh_role_box.setItemText(1, "Put away")
        form.addRow("Slot:", self._part_box)
        form.addRow("Show it:", self._mesh_role_box)
        layout.addWidget(subject)

        carried = QGroupBox("2. Where it is carried")
        carried_layout = QVBoxLayout(carried)
        row = QHBoxLayout()
        row.addWidget(QLabel("Carried at:"))
        row.addWidget(self._carry_box, 1)
        carried_layout.addLayout(row)
        carried_layout.addWidget(_hint(
            "Pick a spot and the item moves there when put away, angle and all. Its draw and "
            "put-away animations stay as they are; to change those, use the Animations tab."
        ))
        row = QHBoxLayout()
        row.addWidget(self._carry_match)
        self._carry_status.setWordWrap(True)
        row.addWidget(self._carry_status, 1)
        carried_layout.addLayout(row)
        layout.addWidget(carried)

        layout.addWidget(self._build_fine_tune_box())

        fit = QGroupBox("4. Check the fit")
        fit_layout = QHBoxLayout(fit)
        fit_layout.addWidget(self._measure_clipping_button)
        fit_layout.addWidget(self._clipping_label, 1)
        layout.addWidget(fit)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_fine_tune_box(self) -> QGroupBox:
        box = QGroupBox("3. Fine-tune")
        layout = QVBoxLayout(box)

        self._adjust_target_box = QComboBox()
        self._adjust_target_box.addItem("This item's own attach point", "item")
        self._adjust_target_box.addItem("The spot on the body it hangs from", "body")
        self._adjust_target_box.setItemData(
            0, "Moves this item only, unless other items share the same point.", Qt.ToolTipRole)
        self._adjust_target_box.setItemData(
            1, "Moves everything that hangs from that spot on the body.", Qt.ToolTipRole)
        self._adjust_target_box.currentIndexChanged.connect(self._on_adjust_target_changed)
        row = QHBoxLayout()
        row.addWidget(QLabel("Adjust:"))
        row.addWidget(self._adjust_target_box, 1)
        layout.addLayout(row)
        layout.addWidget(self._edit_target)
        self._share_note = _hint("")
        self._share_note.setVisible(False)
        layout.addWidget(self._share_note)

        grid = QFormLayout()
        moves = QHBoxLayout()
        moves.setSpacing(4)
        for button in self._nudge_buttons:
            moves.addWidget(button)
        moves.addSpacing(8)
        moves.addWidget(QLabel("Step:"))
        moves.addWidget(self._step_box)
        moves.addStretch(1)
        grid.addRow("Move:", moves)
        position = QHBoxLayout()
        position.setSpacing(4)
        for spin in self._position:
            position.addWidget(spin)
        position.addStretch(1)
        grid.addRow("Position:", position)
        turns = QHBoxLayout()
        turns.setSpacing(4)
        for button in self._turn_buttons:
            turns.addWidget(button)
        turns.addSpacing(8)
        turns.addWidget(QLabel("Turn by:"))
        turns.addWidget(self._angle_box)
        turns.addStretch(1)
        grid.addRow("Turn:", turns)
        angles = QHBoxLayout()
        angles.setSpacing(4)
        for spin in self._euler:
            angles.addWidget(spin)
        angles.addStretch(1)
        grid.addRow("Angle:", angles)

        drag = QHBoxLayout()
        drag.setSpacing(4)
        self._mode_buttons = {}
        self._mode_group = QButtonGroup(box)
        self._mode_group.setExclusive(False)  # the Advanced modes switch these all off
        for value, label, hint in _SIMPLE_MODES:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(hint)
            button.clicked.connect(lambda _checked=False, v=value: self._set_mode(v))
            self._mode_group.addButton(button)
            self._mode_buttons[value] = button
            drag.addWidget(button)
        drag.addStretch(1)
        grid.addRow("Drag in view:", drag)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(self._turn_over_button)
        row.addWidget(self._revert_button)
        row.addStretch(1)
        layout.addLayout(row)
        self._sync_mode_buttons(str(self._mode_box.currentData() or "off"))
        return box

    def _set_mode(self, value: str) -> None:
        position = self._mode_box.findData(value)
        if position >= 0:
            self._mode_box.setCurrentIndex(position)
        # Clicking the live mode again leaves it on rather than toggling the button off.
        self._sync_mode_buttons(str(self._mode_box.currentData() or "off"))

    def _sync_mode_buttons(self, mode: str) -> None:
        """Show the live drag mode on both tabs' buttons; the mode combo is the record."""

        for buttons in (getattr(self, "_mode_buttons", {}),
                        getattr(self, "_advanced_mode_buttons", {})):
            for value, button in buttons.items():
                button.blockSignals(True)
                button.setChecked(value == mode)
                button.blockSignals(False)

    # ── which point the editing controls act on ─────────────────────

    def _on_adjust_target_changed(self, _index: int) -> None:
        # Chosen by hand from here on, so a shared point is no longer swapped for the body's.
        self._adjust_explicit = True
        self._auto_select_attach_point(force=True)

    def _auto_select_attach_point(self, *, force: bool = False) -> None:
        """Select the point Fine-tune should move, for the slot and the way it is shown.

        Only when nothing was chosen by hand: a point picked in the tree or the view stays
        selected until the slot, the Show it setting or the Adjust choice changes (`force`).
        """

        session = self._session
        binding = self._current_binding() if session is not None else None
        if binding is None:
            return
        current = self._selected_socket
        if not force and current and current != getattr(self, "_auto_selected", ""):
            return
        role = self._mesh_role_box.currentData() or "held"
        part = binding.part
        child = part.in_child_socket if role == "stowed" else part.out_child_socket
        body = part.in_socket if role == "stowed" else part.out_socket
        box = getattr(self, "_adjust_target_box", None)
        explicit = getattr(self, "_adjust_explicit", False)
        wanted = (box.currentData() if box is not None and explicit else "") or "item"
        own = child if child and self._socket_file_of(child) else ""
        shared = bool(own) and len(self._shared_socket_users().get(own) or ()) > 1
        # Unless chosen by hand, a shared point of the item's own is passed over for the body
        # spot: a change to a shared point can never be saved, and a body spot can.
        use_own = bool(own) and wanted == "item" and (explicit or not shared or not body)
        target = own if use_own else body
        if not target:
            return
        if box is not None:
            # The choice always names the point that is live, including when the item has no
            # point of its own for the way it is shown.
            box.blockSignals(True)
            box.setCurrentIndex(box.findData("item" if use_own else "body"))
            box.blockSignals(False)
        self._auto_selected = target
        if target != current:
            self._select_socket(target)
        else:
            self._refresh_edit_panel()

    def _refresh_share_note(self) -> None:
        """Say up front what else an adjustment moves, and when it cannot be saved."""

        note = getattr(self, "_share_note", None)
        if note is None:
            return
        session, name = self._session, self._selected_socket
        box = getattr(self, "_adjust_target_box", None)
        weapon = session.weapon if session is not None else None
        if box is not None and name:
            # A point picked in the view or under Advanced: the choice still names it.
            own = weapon is not None and name in weapon.sockets
            box.blockSignals(True)
            box.setCurrentIndex(box.findData("item" if own else "body"))
            box.blockSignals(False)
        if session is None or not name:
            note.setVisible(False)
            return
        shared = self._shared_socket_users().get(name) or ()
        if len(shared) > 1:
            names = ", ".join(part_label(p) for p in list(shared)[:3])
            more = f" and {len(shared) - 3} more" if len(shared) > 3 else ""
            note.setText(
                f"Shared by {len(shared)} slots ({names}{more}). Changing it moves all of them, "
                f"so a mod cannot be saved from that change. To move just this item, use "
                f"Carried at, which gives it a point of its own."
            )
            note.setVisible(True)
            return
        usage = session.usage(name)
        users = sorted(set(usage.stowed) | set(usage.held))
        if session.placed(name) is not None and len(users) > 1:
            note.setText(
                f"{socket_label(name)} is a spot on the body. Changing it moves all "
                f"{len(users)} items that hang there, not only this one."
            )
            note.setVisible(True)
            return
        note.setVisible(False)

    # ── Advanced ────────────────────────────────────────────────────

    def _build_advanced_tab(self, mono) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(_hint(
            "Tools for experienced modders. None of them is needed to move a weapon, change "
            "its animations or save a mod."
        ))
        self._advanced_tabs = QTabWidget()
        self._advanced_tabs.addTab(self._build_attach_points_page(), "Attach points")
        self._advanced_tabs.setTabToolTip(
            0, "Every attach point on the character, what hangs on it, and creating new ones.")
        self._constraints_page = self._build_secondary_motion_tab()
        self._advanced_tabs.addTab(self._constraints_page, "Driven bones")
        self._advanced_tabs.setTabToolTip(
            1, "Bones that follow other bones: muscle bulge, joint creasing and a few jiggle "
               "chains. Experimental: the game may not read these files.")
        self._behaviour_page = self._build_rig_behaviour_tab()
        self._advanced_tabs.addTab(self._behaviour_page, "Rig behaviour")
        self._advanced_tabs.setTabToolTip(
            2, "Settings the game applies on top of animations: look-at range, spine lag, "
               "reach. Per skeleton.")
        self._advanced_tabs.addTab(self._build_chart_tab(mono), "Action charts")
        self._advanced_tabs.setTabToolTip(
            3, "Which animations use an attach point, and pointing them at another one.")
        self._advanced_tabs.addTab(self._diff_view, "File changes")
        self._advanced_tabs.setTabToolTip(4, "Every change as the exact files and values it writes.")
        layout.addWidget(self._advanced_tabs, 1)
        return page

    def _build_attach_points_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(_hint(
            "Select an attach point here or click one in the view; Position's Fine-tune then "
            "acts on it. The panel below says what else moves if you change it."
        ))
        actions = QHBoxLayout()
        actions.addWidget(self._new_socket_button)
        actions.addWidget(self._use_orientation_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        modes = QHBoxLayout()
        self._advanced_mode_buttons = {}
        for value, label, hint in _ADVANCED_MODES:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(hint)
            button.clicked.connect(
                lambda checked=False, v=value: self._set_mode(v if checked else "off"))
            self._advanced_mode_buttons[value] = button
            modes.addWidget(button)
        modes.addStretch(1)
        layout.addLayout(modes)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self._tree)
        split.addWidget(self._inspector)
        split.setChildrenCollapsible(False)
        split.setSizes([360, 240])
        layout.addWidget(split, 1)
        return page
