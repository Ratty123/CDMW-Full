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
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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


class TaskPanelMixin:
    """Where every control sits. Mixed into `PlacementStudioWindow`."""

    # ── top bar ─────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        """What is being worked on, the undo pair, and the way to Your mod."""

        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)
        for label, box, width in (("Character", self._model_box, 200),
                                  ("Weapon", self._weapon_box, 300),
                                  ("Slot", self._part_box, 260)):
            row.addWidget(kit.caption(label))
            box.setMinimumWidth(140)
            box.setMaximumWidth(width)
            row.addWidget(box, 1)
            row.addSpacing(6)
        row.addStretch(1)
        row.addWidget(self._undo_button)
        row.addWidget(self._redo_button)
        row.addSpacing(6)
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
        return kit.Section("Fine-tune", form)

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
                f"Move it, which gives it a point of its own."
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
