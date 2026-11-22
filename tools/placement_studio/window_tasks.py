"""The window's layout: the top bar, the view's tools, the Carry tab and Advanced.

Every tab follows Create New Item's inspector layout (`ui_kit`): titled header bars that fold,
muted captions beside their fields, and one main action pinned under the part that scrolls.
What to work on (character, weapon, slot) sits in the top bar for every tab; how the view is
driven (drag modes, in hand or put away) sits on the view; what it draws is one Show menu.

* **Carry** -- where the weapon hangs (the guided move, mirrored for a left hand), fine-tuning
  its attach point, and checking the fit.
* **Animations** -- browse and play animations, replace a weapon's draws, fix their timing.
* **Edit** -- change an animation or make a new one.
* **Armour** -- try the item against real gear.
* **Your mod** -- every change in plain words, and saving them.
* **Advanced** -- attach points, Driven bones, Rig behaviour, action charts and file changes.

The controls themselves, and everything they do, still belong to the mixins that built them;
this module decides where they sit and which attach point the editing controls act on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from . import ui_kit as kit
from .clip_names import part_label, socket_label

#: The drag modes on the view's tool row; the two that create or re-route are Advanced.
_SIMPLE_MODES = (
    ("off", "Look", "Drag to turn the view. Nothing changes."),
    ("move", "Move", "Drag the selected point to move it."),
    ("rotate", "Rotate", "Drag to turn the selected point."),
    ("tilt", "Tilt", "Drag to roll the item along its own length."),
)
_ADVANCED_MODES = (
    ("route", "Click to hang it there",
     "Then click an attach point in the view: the selected item hangs there when it is shown "
     "the way the view shows it now."),
    ("pick", "Click to add a point",
     "Then click the body where the new attach point should sit."),
)


def _hint(text: str) -> QLabel:
    return kit.hint(text)


_HANG_LIKE_TIP = (
    "Copy this point from another item's file, so the item hangs the way that one "
    "does: a round shield like a tower shield, for example. Saved as a change of this "
    "item's own file."
)
_HANG_LIKE_SHARED_TIP = (
    "Other items share this item's file for this point, so copying another item's "
    "point here would move them too. Hang like is only offered for a point this item "
    "has to itself."
)


def _hang_like_text(label: str) -> str:
    """A Hang like menu entry: the shield types by name, other items by their own label."""

    known = {
        "round shield": translate_active_ui_text("Round shield"),
        "tower shield": translate_active_ui_text("Tower shield"),
        "kite shield": translate_active_ui_text("Kite shield"),
    }
    return known.get(label, label[:1].upper() + label[1:])


class TaskPanelMixin:
    """Where every control sits. Mixed into `PlacementStudioWindow`."""

    # ── top bar ─────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        """What is being worked on, the undo pair, and the way to Your mod."""

        header = QFrame()
        header.setObjectName("PlacementHeaderBar")
        header.setProperty("commandBar", True)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        for label, box, min_width, max_width in (
            ("Character", self._model_box, 140, 210),
            ("Weapon", self._weapon_box, 180, 340),
            ("Slot", self._part_box, 170, 280),
        ):
            row.addWidget(kit.caption(label))
            box.setMinimumWidth(min_width)
            box.setMaximumWidth(max_width)
            row.addWidget(box, 1)
            row.addSpacing(4)
        row.addStretch(1)
        row.addWidget(self._undo_button)
        row.addWidget(self._redo_button)
        row.addSpacing(4)
        self._mod_summary_button = kit.primary("Your mod: no changes",
                                               "Every change you have made, and saving them as a mod.")
        self._mod_summary_button.clicked.connect(self._open_mod_tab)
        row.addWidget(self._mod_summary_button)
        return header

    # ── the view's tools ────────────────────────────────────────────

    def _build_view_tools(self) -> QWidget:
        """Drag modes and in hand / put away, above the view."""

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 4)
        row.setSpacing(4)
        self._mode_buttons = {}
        self._mode_group = QButtonGroup(bar)
        self._mode_group.setExclusive(False)  # the Advanced modes switch these all off
        for value, label, tip_text in _SIMPLE_MODES:
            button = kit.tool(label, tip_text, checkable=True)
            button.clicked.connect(lambda _checked=False, v=value: self._set_mode(v))
            self._mode_group.addButton(button)
            self._mode_buttons[value] = button
            row.addWidget(button)
        row.addSpacing(16)
        self._role_switch = kit.Segmented((
            ("held", "In hand", "Show the item where it is held."),
            ("stowed", "Put away", "Show the item where it is carried when put away."),
        ))
        self._role_switch.changed.connect(self._on_role_switch)
        self._mesh_role_box.currentIndexChanged.connect(self._sync_role_switch)
        self._mesh_role_box.setVisible(False)
        row.addWidget(self._role_switch)
        row.addStretch(1)
        self._sync_mode_buttons(str(self._mode_box.currentData() or "off"))
        self._sync_role_switch()
        return bar

    def _on_role_switch(self, value: str) -> None:
        position = self._mesh_role_box.findData(value)
        if position >= 0:
            self._mesh_role_box.setCurrentIndex(position)

    def _sync_role_switch(self, _index: int = 0) -> None:
        switch = getattr(self, "_role_switch", None)
        if switch is not None:
            switch.set_value(str(self._mesh_role_box.currentData() or "held"))

    def _build_show_button(self) -> QToolButton:
        """One Show menu for what the view draws, in place of a row of check boxes."""

        self._show_bones.setText("Skeleton")
        self._show_unused.setText("Spare attach points")
        self._show_meshes.setText("Body and gear")
        button = kit.tool("Show", "What the view draws.")
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        self._show_actions = {}
        for box in (self._show_bones, self._show_labels, self._show_unused, self._show_meshes,
                    self._solid_body, self._reverse_orbit):
            action = menu.addAction(box.text())
            action.setCheckable(True)
            action.setChecked(box.isChecked())
            action.setToolTip(box.toolTip())
            action.toggled.connect(box.setChecked)
            box.toggled.connect(action.setChecked)
            box.setVisible(False)
            self._show_actions[box.text()] = action
        menu.setToolTipsVisible(True)
        button.setMenu(menu)
        return button

    def _build_view_strip(self) -> QWidget:
        """Kept for callers that ask for the strip: the Show menu, on its own row."""

        return kit.row(self._build_show_button())

    # ── Carry ───────────────────────────────────────────────────────

    def _build_position_tab(self) -> QWidget:
        page = kit.InspectorPage()
        page.add(self._build_carry_where_section())
        page.add(self._build_fine_tune_section())
        fit = kit.Form()
        fit.add_wide(kit.row(self._measure_clipping_button))
        fit.add_wide(self._clipping_label)
        page.add(kit.Section("Check the fit", fit, expanded=False))
        page.set_footer(self._build_carry_footer())
        self._carry_page = page
        return page

    def _build_fine_tune_section(self) -> kit.Section:
        self._adjust_target_box = QComboBox()
        self._adjust_target_box.addItem("This item's own attach point", "item")
        self._adjust_target_box.addItem("The spot on the body", "body")
        self._adjust_target_box.setItemData(
            0, "Moves this item only, unless other items share the same point.", Qt.ToolTipRole)
        self._adjust_target_box.setItemData(
            1, "Moves everything that hangs from that spot on the body.", Qt.ToolTipRole)
        self._adjust_target_box.currentIndexChanged.connect(self._on_adjust_target_changed)
        self._share_note = _hint("")
        self._share_note.setVisible(False)

        form = kit.Form()
        form.add("Adjust", self._adjust_target_box)
        form.add("Point", self._edit_target)
        form.add_wide(self._share_note)
        form.add("Position", kit.row(*self._position))
        form.add("Angle", kit.row(*self._euler))
        self._step_box.setMinimumWidth(78)
        self._angle_box.setMinimumWidth(64)
        form.add("Nudge", kit.row(*self._nudge_buttons, None, kit.caption("Step"), self._step_box,
                                  stretch=False))
        form.add("Turn", kit.row(*self._turn_buttons, None, kit.caption("By"), self._angle_box,
                                 stretch=False))
        form.add("", kit.row(self._turn_over_button, self._revert_button))
        form.add("", kit.row(*self._build_carry_point_actions()))
        self._back_move_row = kit.row(*self._build_back_move_controls())
        self._back_move_caption = form.add("On the back", self._back_move_row)
        form.add_wide(self._back_move_note)
        self._back_move_caption.setVisible(False)
        self._back_move_row.setVisible(False)
        return kit.Section("Fine-tune", form)

    def _build_back_move_controls(self):
        """Move the item in the back's plane by its own point, with the files in step with it."""

        from .back_move import MOVES

        self._back_move_box = QComboBox()
        # One call each, so the localization scanner reads the labels and not the keys.
        out, along, across, turn, tip_out = MOVES
        self._back_move_box.addItem("Out from the back", out)
        self._back_move_box.addItem("Up the blade", along)
        self._back_move_box.addItem("Across the blade", across)
        self._back_move_box.addItem("Turn seen from behind", turn)
        self._back_move_box.addItem("Tip out", tip_out)
        self._back_move_box.setToolTip(
            "Moves the item in the plane it lies in on the back, by changing the point in its "
            "own file. The body point stays where it is, so spears, hammers and tools that "
            "share it do not move. Turns are made about the guard.")
        self._back_move_buttons = []
        for glyph, sign in (("−", -1.0), ("+", 1.0)):
            button = QPushButton(glyph)
            button.setFixedWidth(34)
            button.setToolTip("One step: the Step distance, or the By angle for a turn.")
            button.clicked.connect(lambda _checked=False, s=sign: self._move_on_back(s))
            self._back_move_buttons.append(button)
        self._back_in_step_box = QCheckBox("With the files in step")
        self._back_in_step_box.setChecked(True)
        self._back_in_step_box.setToolTip(
            "Also move the other files that hang this kind of item the same way, such as the "
            "sword's sheaths, so they stay together.")
        self._back_in_step_box.toggled.connect(lambda _on: self._refresh_carry_point_actions())
        self._back_move_note = _hint("")
        self._back_move_note.setVisible(False)
        return (self._back_move_box, *self._back_move_buttons, self._back_in_step_box)

    def _build_carry_point_actions(self):
        """Over the other shoulder and Hang like, offered only where they apply."""

        self._other_shoulder_button = QPushButton("Over the other shoulder")
        self._other_shoulder_button.setToolTip(
            "Mirror the item across the middle of the body and write the back point it hangs "
            "from to match, in each of this body's files. For back points that have no left or "
            "right partner. Everything else that hangs from that point moves with it."
        )
        self._other_shoulder_button.clicked.connect(self._mirror_over_other_shoulder)
        self._hang_like_button = QPushButton("Hang like…")
        self._hang_like_button.setToolTip(_HANG_LIKE_TIP)
        self._hang_like_menu = QMenu(self._hang_like_button)
        self._hang_like_menu.setToolTipsVisible(True)
        self._hang_like_button.setMenu(self._hang_like_menu)
        self._other_shoulder_button.setVisible(False)
        self._hang_like_button.setVisible(False)
        return self._other_shoulder_button, self._hang_like_button

    def _refresh_carry_point_actions(self) -> None:
        """Show each action only for a point it can change, and list Hang like's sources."""

        button = getattr(self, "_other_shoulder_button", None)
        if button is None or getattr(self, "_drag_settle_pending", False):
            # Mid-drag the point stays the same; the refresh when the drag ends catches up.
            return
        name, _child = self._other_shoulder_target()
        button.setVisible(bool(name))
        sources = self._hang_like_sources()
        menu = self._hang_like_menu
        menu.clear()
        for source in sources:
            action = menu.addAction(_hang_like_text(source.label))
            action.setToolTip(source.socket_file)
            action.triggered.connect(lambda _checked=False, s=source: self._hang_like(s))
        self._hang_like_button.setVisible(bool(sources))
        # Like Turn over: a point other rows share is refused on save, so it is not offered.
        shared = len(self._point_users(self._selected_socket)) > 1
        self._hang_like_button.setEnabled(not shared)
        self._hang_like_button.setToolTip(_HANG_LIKE_SHARED_TIP if shared else _HANG_LIKE_TIP)
        self._refresh_back_move()

    def _refresh_back_move(self) -> None:
        """Offer On the back for an item's own point it hangs from on the back."""

        from .back_move import labels

        target = self._back_move_target()
        shown = target is not None
        self._back_move_caption.setVisible(shown)
        self._back_move_row.setVisible(shown)
        in_step = target.in_step if target is not None else ()
        self._back_in_step_box.setEnabled(bool(in_step))
        note = ""
        if shown and in_step:
            names = ", ".join(labels(step.socket_file for step in in_step))
            if self._back_in_step_box.isChecked():
                note = translate_active_ui_text(f"Moves these files with it: {names}.")
            else:
                note = translate_active_ui_text(f"These files stay as they are: {names}.")
        self._back_move_note.setText(note)
        self._back_move_note.setVisible(bool(note))

    def _set_mode(self, value: str) -> None:
        position = self._mode_box.findData(value)
        if position >= 0:
            self._mode_box.setCurrentIndex(position)
        # Clicking the live mode again leaves it on rather than toggling the button off.
        self._sync_mode_buttons(str(self._mode_box.currentData() or "off"))

    def _sync_mode_buttons(self, mode: str) -> None:
        """Show the live drag mode on both tabs' buttons; the mode combo is the record."""

        for buttons in (getattr(self, "_mode_buttons", {}),
                        self._built_attr("_advanced_mode_buttons", {})):
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
        shared = bool(own) and len(self._point_users(own)) > 1
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
        notes = []
        shared = self._point_users(name)
        own = weapon is not None and name in weapon.sockets
        if len(shared) > 1:
            names = ", ".join(part_label(p) for p in list(shared)[:3])
            more = f" and {len(shared) - 3} more" if len(shared) > 3 else ""
            note.setText(
                f"Shared by {len(shared)} slots ({names}{more}). Changing it moves all of them, "
                f"so a mod cannot be saved from that change. To move just this item, use "
                f"Move it, which gives it a point of its own."
            )
            note.setVisible(True)
            return
        if own:
            notes.append(self._file_models_note(weapon.game_path))
        usage = session.usage(name)
        users = sorted(set(usage.stowed) | set(usage.held))
        if session.placed(name) is not None and len(users) > 1:
            notes.append(self._body_point_users_note(name, users))
            if self._other_shoulder_target()[0]:
                notes.append(translate_active_ui_text(
                    "Over the other shoulder mirrors the item across the body and moves them "
                    "all with it."))
        if session.placed(name) is not None:
            notes.append(self._other_mod_point_note(name))
        # Each sentence is translated on its own, so the note reads whole in any language.
        text = " ".join(part for part in notes if part)
        note.setText(text)
        note.setVisible(bool(text))

    def _body_point_users_note(self, name: str, users) -> str:
        """`Left hip carries 6 items: ...`, naming the first few of what a change moves."""

        listed = ", ".join(part_label(p) for p in users[:4])
        if len(users) > 4:
            return translate_active_ui_text(
                f"{socket_label(name)} carries {len(users)} items: {listed} and "
                f"{len(users) - 4} more. Changing it moves all of them, not only this one.")
        return translate_active_ui_text(
            f"{socket_label(name)} carries {len(users)} items: {listed}. Changing it moves "
            f"all of them, not only this one.")

    def _file_models_note(self, socket_file: str) -> str:
        """Say when several models read this one file, so they all change together."""

        from .equipment_assets import TYPE_LABELS, socket_file_kind, type_label

        session = self._session
        models = session.models_reading(socket_file) if session is not None else ()
        kind = type_label(socket_file)
        if socket_file_kind(socket_file) in TYPE_LABELS:
            return translate_active_ui_text(
                f"Every {kind} model reads this one file, so changing this point changes all "
                f"of them.")
        if len(models) > 1:
            return translate_active_ui_text(
                f"{len(models)} models read this file, so changing this point changes all of "
                f"them.")
        return ""

    def _other_mod_point_note(self, name: str) -> str:
        """Say when one of this body's game files has no such point: another mod adds it."""

        from . import carry_plan

        session, edits = self._session, self._edits
        if session is None or edits is None:
            return ""
        missing = carry_plan.points_other_mods_add(edits, session.model, (name,))
        if not missing:
            return ""
        bodies = ", ".join(carry_plan.body_file_label(path) for path, _point in missing)
        return translate_active_ui_text(
            f"The game's body file for {bodies} has no {socket_label(name)} point. Another mod "
            f"adds it there (for example Character Creator Enhanced or Heroine of Pywel), and "
            f"CDMW edits the game's own files, so it cannot move that one here.")

    # ── Advanced ────────────────────────────────────────────────────

    def _init_advanced_state(self) -> None:
        self._init_constraint_state()
        self._init_behaviour_state()

    def _advanced_tab_built(self) -> None:
        """Wire the new pages in, and catch them up on what changed while Advanced was closed."""

        self._rig_tab_pages.update(
            {"constraints": self._constraints_page, "behaviour": self._behaviour_page})
        self._advanced_tabs.currentChanged.connect(self._on_lower_tab_changed)
        self._sync_mode_buttons(str(self._mode_box.currentData() or "off"))
        if self._edits is not None:
            self._refresh_diff_title(len(self._edits.to_plan().operations))
        self._refresh_animation()
        requested = getattr(self, "_chart_sources_requested", None)
        if requested is not None and requested != getattr(self, "_chart_sources_ready", None):
            # The charts are still being read; the pickers wait for them, as they did when
            # they were built at startup.
            self._chart_socket_box.setEnabled(False)
            self._retarget_button.setEnabled(False)

    def _build_advanced_tab(self, mono) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)
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
        # A dropdown picks the page: five tab captions do not fit the inspector's width, and
        # Qt answered that with scroll arrows that hid the last two.
        self._advanced_tabs.tabBar().setVisible(False)
        self._advanced_page_box = QComboBox()
        for index in range(self._advanced_tabs.count()):
            self._advanced_page_box.addItem(self._advanced_tabs.tabText(index))
            self._advanced_page_box.setItemData(index, self._advanced_tabs.tabToolTip(index),
                                                Qt.ToolTipRole)
        self._advanced_page_box.currentIndexChanged.connect(self._advanced_tabs.setCurrentIndex)
        self._advanced_tabs.currentChanged.connect(self._advanced_page_box.setCurrentIndex)
        layout.addWidget(kit.row(kit.caption("Page"), self._advanced_page_box, None, stretch=False))
        layout.addWidget(self._advanced_tabs, 1)
        return page

    def _set_advanced_page_text(self, widget: QWidget, text: str) -> None:
        """Rename one Advanced page in both the hidden tab and the dropdown."""

        index = self._advanced_tabs.indexOf(widget)
        if index >= 0:
            self._advanced_tabs.setTabText(index, text)
            box = getattr(self, "_advanced_page_box", None)
            if box is not None and index < box.count():
                box.setItemText(index, text)

    def _build_attach_points_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        self._advanced_mode_buttons = {}
        modes = []
        for value, label, tip_text in _ADVANCED_MODES:
            button = kit.tool(label, tip_text, checkable=True)
            button.clicked.connect(
                lambda checked=False, v=value: self._set_mode(v if checked else "off"))
            self._advanced_mode_buttons[value] = button
            modes.append(button)
        layout.addWidget(kit.row(self._new_socket_button, self._use_orientation_button))
        layout.addWidget(kit.row(*modes))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self._tree)
        split.addWidget(self._inspector)
        split.setChildrenCollapsible(False)
        split.setSizes([360, 240])
        layout.addWidget(split, 1)
        return page
