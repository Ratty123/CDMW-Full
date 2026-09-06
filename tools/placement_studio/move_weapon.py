"""Unified replacement selection, private comparison and complete file review."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import carry
from .move_operation import MovePlan, MoveRequest
from .move_workspace import WorkspaceLifecycle, build_workspace

#: The four pages, in order.
PAGE_EQUIPMENT = 0
PAGE_PLACEMENT = 1
PAGE_ANIMATIONS = 2
PAGE_REVIEW = 3

#: Shown until the review page has been opened. A button that accepts before the scope has
#: been looked at is the whole of failure mode 3.4.
REVIEW_FIRST_LABEL = "Review changes"

PERSPECTIVE_NOTE = "Left and right are from the character's perspective, not the camera's."


def socket_choice_label(socket: str, label: str) -> str:
    """`Hip — right  [Pelvis_R_Socket]`.

    Friendly names alone are not enough to debug a side or socket problem: two entries that
    read `Hip — right` and `Hip — left` are one word apart, and the word is the thing that
    goes wrong. The raw name is what a descriptor, a chart and a bug report all use.
    """

    return f"{label}  [{socket}]" if label and label != socket else socket




class MoveWeaponDialog(WorkspaceLifecycle, QDialog):
    """Ask which item moves where, what comes with it, and which animations follow.

    Every expensive or session-dependent answer is supplied by the caller, so the dialog is
    testable without a game install:

    * `unit_for(part_name)` re-resolves the whole equipment unit when the item changes. It
      returns `(unit, error)`; an error is shown and the move is blocked rather than falling
      back to the previously selected weapon, which is failure mode 3.2.
    * `pairs_for(unit, scope)` returns `AnimationReplacement` rows for that unit at that scope.
    * `plan_for(request)` resolves a `MoveRequest` into a `MovePlan` — the three-state
      comparison, the orientation decisions, the blockers and the action label all come from it.
    """

    def __init__(
        self,
        parent=None,
        *,
        unit=None,
        parts: Sequence[Tuple[str, str]] = (),
        positions: Sequence[Tuple[str, str]] = (),
        unit_for: Optional[Callable[[str], Tuple[object, str]]] = None,
        pairs_for: Optional[Callable[..., Sequence[object]]] = None,
        plan_for: Optional[Callable[[MoveRequest], MovePlan]] = None,
        on_preview: Optional[Callable[[object], None]] = None,
        on_preview_placement: Optional[Callable[[MovePlan], None]] = None,
        on_show_files: Optional[Callable[[MovePlan], None]] = None,
        chart_lanes: Optional[dict] = None,
        earlier_operations: Sequence[str] = (),
        prepare_for=None,
        weapons=(),
        unit_for_weapon=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Placement & Animations — replacement workspace")
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(1050, 640)
        available = self.screen().availableGeometry()
        self.resize(min(1420, available.width() - 32), min(940, available.height() - 64))
        self._prepare_for = prepare_for
        self._prepared_scene = None

        self._unit = unit
        self._unit_error = ""
        self._unit_for = unit_for
        self._unit_for_weapon = unit_for_weapon
        self._weapons = tuple(weapons)
        self._pairs_for = pairs_for or (lambda *_a, **_k: [])
        self._plan_for = plan_for
        self._on_preview = on_preview
        self._on_preview_placement = on_preview_placement
        self._on_show_files = on_show_files
        #: clip -> the situation its action chart puts it in. Empty means every lane falls back
        #: to the file name, which is a guess and is only used when nothing better says.
        self._chart_lanes = dict(chart_lanes or {})
        self._positions = list(positions)
        self._earlier_operations = tuple(earlier_operations)
        self._link_boxes: Dict[str, QCheckBox] = {}
        self._context_boxes: Dict[str, QCheckBox] = {}
        self._plan: Optional[MovePlan] = None
        self._reviewed = False
        #: Set while controls are being rebuilt, so a programmatic change is not read as a
        #: user decision that would rebuild them again.
        self._syncing = True

        build_workspace(self, parts)
        self._syncing = False
        self._point_destination_at_current()
        self._reload_clips()
        self._refresh()
        self._part_box.setFocus()

    def _point_destination_at_current(self) -> None:
        """Open on where the item already hangs, so the first state shown is a no-op.

        Opening on whatever sorted first made the dialog propose a move nobody asked for, and
        the action label would then have offered to make it.
        """

        self._syncing = True
        position = self._to_box.findData(getattr(self._unit, "in_socket", "") or "")
        self._to_box.setCurrentIndex(max(0, position))
        self._syncing = False

    # ── construction ────────────────────────────────────────────────

    def _banner(self) -> QWidget:
        """E2: say that earlier work exists and that this operation is not it."""

        self._banner_label = QLabel()
        self._banner_label.setWordWrap(True)
        count = len(self._earlier_operations)
        if count:
            self._banner_label.setObjectName("WarningBadge")
            self._banner_label.setText(
                f"This session contains {count} earlier operation(s). They are not part of "
                f"this move and will not be packaged unless you select them."
            )
        else:
            self._banner_label.setObjectName("HintLabel")
            self._banner_label.setText("This is the first operation in this session.")
        return self._banner_label

    def _build_equipment_page(self, parts: Sequence[Tuple[str, str]]) -> QWidget:
        page = QGroupBox("Equipment")
        layout = QVBoxLayout(page)

        self._part_box = QComboBox()
        for name, label in parts:
            self._part_box.addItem(label, name)
        if self._unit is not None:
            position = self._part_box.findData(self._unit.primary_part)
            if position >= 0:
                self._part_box.setCurrentIndex(position)
        self._part_box.setToolTip(
            "The equipment row to move — a sword is a CD_MainWeapon or CD_TwoHandWeapon row.\n\n"
            "Changing this re-resolves the whole item: its case, its handedness, which "
            "animation families are its own, and which files may be written."
        )
        self._part_box.currentIndexChanged.connect(self._on_part_changed)

        form = QFormLayout()
        form.addRow("Item:", self._part_box)
        self._asset_box = QComboBox()
        for weapon in self._weapons:
            self._asset_box.addItem(weapon.label, weapon)
            self._asset_box.setItemData(self._asset_box.count()-1,
                f'{weapon.weapon_id}\n{weapon.mesh_path}\nSocket template: {weapon.game_path}\n{weapon.prefab_path}', Qt.ToolTipRole)
        for i,weapon in enumerate(self._weapons):
            if self._unit and weapon.weapon_id == self._unit.weapon_id:
                self._asset_box.setCurrentIndex(i)
                break
        self._asset_box.currentIndexChanged.connect(self._on_part_changed)
        if self._weapons:
            form.addRow('Equipment asset:', self._asset_box)
        else:
            self._asset_box.hide()
        self._unit_label = QLabel()
        self._unit_label.setWordWrap(True)
        form.addRow("Resolved as:", self._unit_label)
        self._unit_problem = QLabel()
        self._unit_problem.setObjectName("HintLabel")
        self._unit_problem.setProperty("healthState", "unhealthy")
        self._unit_problem.setWordWrap(True)
        form.addRow("", self._unit_problem)
        layout.addLayout(form)

        self._links_group = QGroupBox("Linked parts")
        self._links_group.setToolTip(
            "Rows that belong to this item — its sheath, scabbard, quiver or holster. A "
            "required row moves with the weapon; leaving one behind separates the two."
        )
        self._links_layout = QVBoxLayout(self._links_group)
        layout.addWidget(self._links_group)

        self._link_exception = QCheckBox(
            "Allow partial linked set"
        )
        self._link_exception.setToolTip(
            "The weapon and its case may separate, snap between positions, or draw and stow "
            "inconsistently. Every exception is recorded in the operation manifest."
        )
        self._link_exception.toggled.connect(self._on_link_exception_toggled)
        layout.addWidget(self._link_exception)
        self._link_warning = QLabel()
        self._link_warning.setObjectName("WarningText")
        self._link_warning.setWordWrap(True)
        self._link_warning.hide()
        layout.addWidget(self._link_warning)
        return page

    def _build_placement_page(self) -> QWidget:
        page = QGroupBox("Placement")
        layout = QVBoxLayout(page)

        self._to_box = QComboBox()
        for socket, label in self._positions:
            self._to_box.addItem(socket_choice_label(socket, label), socket)
        self._to_box.setToolTip("Where the item should hang when stowed.")
        self._to_box.currentIndexChanged.connect(self._on_destination_changed)

        form = QFormLayout()
        form.addRow("Destination:", self._to_box)
        self._zone_label = QLabel()
        form.addRow("Destination zone:", self._zone_label)
        layout.addLayout(form)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0,0,0,0)
        form = QFormLayout()
        self._orientation_label = QLabel()
        self._orientation_label.setWordWrap(True)
        form.addRow("Orientation from:", self._orientation_label)
        self._new_socket_label = QLabel()
        self._new_socket_label.setWordWrap(True)
        form.addRow("New child sockets:", self._new_socket_label)
        self._shared_label = QLabel()
        self._shared_label.setWordWrap(True)
        form.addRow("Shared sockets:", self._shared_label)
        details_layout.addLayout(form)

        perspective = QLabel(PERSPECTIVE_NOTE)
        perspective.setWordWrap(True)
        layout.addWidget(perspective)

        # 5.2: three states, side by side. Showing only the third is how an earlier
        # experiment's `Pelvis_R_Socket` came to read as the game's default.
        self._states = QTableWidget(0, 4)
        self._states.setHorizontalHeaderLabels(
            ["Field", "Installed", "Current session", "After"]
        )
        self._states.verticalHeader().setVisible(False)
        self._states.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._states.setSelectionMode(QAbstractItemView.NoSelection)
        header = self._states.horizontalHeader()
        for column in range(4):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        self._states.setToolTip(
            "Vanilla is what the game ships. Pending is what this session has already changed, "
            "including earlier operations. Proposed is what this operation would make it."
        )
        self._states.setMaximumHeight(140)
        details_layout.addWidget(self._states)
        details_toggle = QPushButton("Placement details")
        details_toggle.setCheckable(True)
        details_toggle.toggled.connect(details.setVisible)
        layout.addWidget(details_toggle)
        layout.addWidget(details)
        details.hide()

        self._orientation_reviewed = QCheckBox(
            "Orientation reviewed"
        )
        self._orientation_reviewed.setToolTip(
            "Required when the aim is borrowed from another item or authored by hand. The "
            "geometry check can warn that an item looks inverted; it will never rotate it for "
            "you, because mesh origins and attachment transforms differ by asset."
        )
        self._orientation_reviewed.toggled.connect(lambda _c: self._refresh())
        layout.addWidget(self._orientation_reviewed)
        return page

    def _build_animation_page(self) -> QWidget:
        page = QGroupBox("Animation")
        page.setToolTip("How much of the animation set follows")
        layout = QVBoxLayout(page)

        self._scope_buttons: Dict[str, QRadioButton] = {}
        for kind in carry.SCOPE_ORDER:
            button = QRadioButton(carry.SCOPE_LABELS[kind])
            button.setToolTip(carry.SCOPE_HINTS.get(kind, ""))
            button.toggled.connect(lambda checked: self._on_scope_changed() if checked else None)
            layout.addWidget(button)
            self._scope_buttons[kind] = button
        self._scope_buttons[carry.SCOPE_DRAW_STOW].setChecked(True)

        self._advanced_confirm = QCheckBox(
            "Full-body effects reviewed"
        )
        self._advanced_confirm.toggled.connect(lambda _c: self._refresh())
        self._advanced_confirm.setToolTip('Donor motion can change the off-hand, shield arm and whole-body stance. Review the complete file set and preview checks.')
        layout.addWidget(self._advanced_confirm)

        context_group = QGroupBox("Context")
        context_group.setToolTip("Contexts (leave alone to use the preset's own set)")
        context_layout = QVBoxLayout(context_group)
        for name, label in carry.CONTEXT_GROUPS:
            box = QCheckBox(label)
            if name in carry.OPT_IN_CONTEXTS:
                box.setToolTip(
                    "Off unless asked for: these clips move the whole body, or put the "
                    "character on another rig entirely."
                )
            box.toggled.connect(lambda _c: self._on_scope_changed())
            context_layout.addWidget(box)
            self._context_boxes[name] = box
        layout.addWidget(context_group)
        context_group.hide()
        details = QPushButton('Animation filters')
        details.setCheckable(True)
        details.toggled.connect(context_group.setVisible)
        layout.insertWidget(layout.indexOf(context_group), details)

        options = QVBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        self._include_mounted = QCheckBox("Include mounted clips")
        self._include_borrowed = QCheckBox("Include the other character's clips")
        self._include_borrowed.setToolTip(
            "A clip authored for the other playable character. It plays — the rigs share most "
            "of their bones — but the proportions differ, so a borrowed draw may reach near "
            "the hilt rather than onto it."
        )
        for box in (self._include_mounted, self._include_borrowed):
            box.toggled.connect(lambda _c: self._on_scope_changed())
            options.addWidget(box)
        options_panel = QWidget()
        options_panel.setLayout(options)
        options_panel.hide()
        details.toggled.connect(options_panel.setVisible)
        layout.addWidget(options_panel)

        return page



    # ── navigation ──────────────────────────────────────────────────





    def _on_accept_clicked(self) -> None:
        prepared = self.prepared()
        if prepared is not None and not prepared.blocked and prepared.changed_files:
            self.accept()


    # ── reacting to changes ─────────────────────────────────────────

    def _on_part_changed(self) -> None:
        """E4: changing the item invalidates and rebuilds *everything* that depends on it.

        Not only the "hangs on now" label, which is what it used to do — leaving handedness,
        the animation families, the donor list and the child-socket ownership belonging to the
        previously selected weapon.
        """

        if self._syncing or (self._unit_for is None and self._unit_for_weapon is None):
            return
        part_name = str(self._part_box.currentData() or "")
        if self._unit_for_weapon is not None and self._asset_box.currentData() is not None:
            unit, error = self._unit_for_weapon(part_name, self._asset_box.currentData())
        elif self._unit_for is not None:
            unit, error = self._unit_for(part_name)
        else:
            return
        self._unit = unit
        self._unit_error = error or ""
        self._reviewed = False
        self._orientation_reviewed.setChecked(False)
        self._point_destination_at_current()
        self._reload_clips()
        self._refresh()

    def _on_destination_changed(self) -> None:
        if self._syncing:
            return
        self._orientation_reviewed.setChecked(False)
        self._reviewed = False
        self._reload_clips()
        self._refresh()

    def _on_scope_changed(self) -> None:
        if self._syncing:
            return
        self._reviewed = False
        self._reload_clips()
        self._refresh()

    def _on_link_exception_toggled(self, enabled: bool) -> None:
        for part_name, box in self._link_boxes.items():
            if box.property("required"):
                box.setEnabled(enabled)
                if not enabled:
                    box.setChecked(True)
        self._reviewed = False
        self._refresh()

    def _reset(self) -> None:
        self._syncing = True
        self._file_model.selected.clear()
        self._file_model.donors.clear()
        self._scope_buttons[carry.SCOPE_DRAW_STOW].setChecked(True)
        for box in self._context_boxes.values():
            box.setChecked(False)
        self._include_mounted.setChecked(False)
        self._include_borrowed.setChecked(False)
        self._advanced_confirm.setChecked(False)
        self._orientation_reviewed.setChecked(False)
        self._link_exception.setChecked(False)
        for box in self._link_boxes.values():
            box.setChecked(True)
        position = self._to_box.findData(getattr(self._unit, "in_socket", "") or "")
        if position >= 0:
            self._to_box.setCurrentIndex(position)
        self._syncing = False
        self._reviewed = False
        self._reload_clips()
        self._refresh()

    # ── contents ────────────────────────────────────────────────────

    def _destination(self) -> str:
        return str(self._to_box.currentData() or "")

    def scope(self) -> carry.AnimationScope:
        kind = next(
            (name for name, button in self._scope_buttons.items() if button.isChecked()),
            carry.SCOPE_DRAW_STOW,
        )
        contexts = tuple(
            name for name, box in self._context_boxes.items() if box.isChecked()
        )
        return carry.AnimationScope(
            kind=kind,
            contexts=contexts,
            include_borrowed=self._include_borrowed.isChecked(),
            include_mounted=self._include_mounted.isChecked(),
        )

    def _rebuild_links(self) -> None:
        unit_id = getattr(self._unit, "unit_id", "")
        previous = {name:box.isChecked() for name,box in self._link_boxes.items()} if getattr(self, "_links_unit_id", None) == unit_id else {}
        self._links_unit_id = unit_id
        while self._links_layout.count():
            item = self._links_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._link_boxes = {}
        unit = self._unit
        links = list(getattr(unit, "linked_parts", ()) or ())
        primary = QCheckBox("Primary item")
        primary.setToolTip(getattr(unit, 'primary_part', '(none)'))
        primary.setChecked(True)
        primary.setEnabled(False)
        self._links_layout.addWidget(primary)
        if not links:
            self._links_layout.addWidget(QLabel("  No linked row — this item carries nothing."))
            return
        for link in links:
            from .clip_names import part_label
            box = QCheckBox(f"{part_label(link.part_name)} · {link.role}")
            box.setToolTip(link.part_name)
            box.setChecked(previous.get(link.part_name, True))
            box.setProperty("required", bool(link.required_for_stow))
            if link.required_for_stow:
                box.setEnabled(self._link_exception.isChecked())
                box.setToolTip(
                    "Required for a consistent stow: it moves with the primary item unless "
                    "you take the advanced exception below."
                )
            box.toggled.connect(lambda _c: self._on_link_toggled())
            self._links_layout.addWidget(box)
            self._link_boxes[link.part_name] = box

    def _on_link_toggled(self) -> None:
        if self._syncing:
            return
        self._reviewed = False
        self._refresh()

    def _reload_clips(self) -> None:
        import inspect
        self._syncing = True
        try:
            self._rebuild_links()
            rows = ()
            if self._unit is not None:
                if "destination_socket" in inspect.signature(self._pairs_for).parameters:
                    rows = self._pairs_for(self._unit, self.scope(), destination_socket=self._destination())
                else:
                    rows = self._pairs_for(self._unit, self.scope())
            self._file_model.set_rows(rows)
        finally:
            self._syncing = False


    # ── selection ───────────────────────────────────────────────────

    def _watch_selected(self) -> None:
        index = self._file_table.currentIndex()
        if not index.isValid():
            return
        source = self._file_proxy.mapToSource(index)
        row = self._file_model.replacement(source.row())
        if row is None:
            return
        if self._prepared_scene is not None:
            self._preview.watch(row.target_path)
        else:
            self._pending_watch = row.target_path
            self._prepare_selection()


    def _watch_row(self, index) -> None:
        self._file_table.setCurrentIndex(index)
        self._watch_selected()


    def _set_all(self, checked: bool) -> None:
        self._file_model.select_all(checked)


    def chosen_replacements(self) -> Tuple[object, ...]:
        return self._file_model.chosen()


    def leave_behind(self) -> Tuple[str, ...]:
        return tuple(
            part_name for part_name, box in self._link_boxes.items() if not box.isChecked()
        )

    def include_links(self) -> Tuple[str, ...]:
        return tuple(
            part_name for part_name, box in self._link_boxes.items() if box.isChecked()
        )

    # ── result ──────────────────────────────────────────────────────

    def request(self) -> Optional[MoveRequest]:
        if self._unit is None:
            return None
        return MoveRequest(
            unit=self._unit,
            destination_socket=self._destination(),
            scope=self.scope(),
            include_links=self.include_links(),
            leave_behind=self.leave_behind(),
            replacements=self.chosen_replacements(),
            orientation_reviewed=self._orientation_reviewed.isChecked(),
            advanced_confirmed=self._advanced_confirm.isChecked(),
        )

    def plan(self) -> Optional[MovePlan]:
        return self._plan

    @property
    def play_after(self) -> bool:
        return self._play_after.isChecked()

    def preview_clip(self):
        rows = self.chosen_replacements()
        return rows[0].donor if rows else None


    # ── refresh ─────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._syncing:
            return
        self._unit_label.setText(self._unit.weapon_id if self._unit is not None else "(unresolved)")
        self._unit_label.setToolTip(self._unit.describe() if self._unit is not None else "")
        self._unit_problem.setText(self._unit_error)
        self._unit_problem.setVisible(bool(self._unit_error))
        request = self.request()
        previous = self._plan.request if self._plan is not None else None
        self._plan = self._plan_for(request) if request is not None and self._plan_for else None
        if request != previous:
            self._invalidate_preparation()
        self._refresh_placement(self._plan)
        self._refresh_animations(self._plan)
        self._refresh_review(self._plan)
        self._preview_placement.setEnabled(self._plan is not None and self._prepare_for is not None)
        if self._prepared_scene is None:
            self._accept.setText(self._plan.action_label() if self._plan else "No changes")
            self._accept.setEnabled(False)


    def _refresh_placement(self, plan: Optional[MovePlan]) -> None:
        destination = self._destination()
        zone = carry.zone_of(destination)
        self._zone_label.setText(
            f"{carry.ZONE_LABELS.get(zone, zone or '(not a carry position)')}"
            f"{f'  [{zone}]' if zone else ''}"
        )
        if plan is None:
            for label in (self._orientation_label, self._new_socket_label, self._shared_label):
                label.setText("-")
            self._states.setRowCount(0)
            return

        sources = [
            f"{route.part_name}: {route.template.label}"
            for route in plan.routes
        ]
        self._orientation_label.setText("\n".join(sources) or "-")
        created = [name for _file, name in plan.new_sockets]
        self._new_socket_label.setText(", ".join(created) or "none — an existing one is reused")
        shared = [
            f"{route.proposed_child} ({', '.join(route.clone_decision.users)})"
            for route in plan.routes
            if route.clone_decision is not None and route.clone_decision.shared
        ]
        self._shared_label.setText(
            "; ".join(shared) or "none of this operation's sockets are shared"
        )
        needs_review = any(route.template.needs_manual_review for route in plan.routes)
        self._orientation_reviewed.setEnabled(needs_review)
        if not needs_review:
            self._orientation_reviewed.setToolTip(
                "The aim comes from this item's own child socket for that destination, so "
                "there is nothing to review."
            )

        self._states.setRowCount(len(plan.states))
        for row_index, row in enumerate(plan.states):
            for column, value in enumerate(
                (row.field_label, row.vanilla, row.pending, row.proposed)
            ):
                cell = QTableWidgetItem(value or "-")
                if column == 2 and row.already_changed:
                    borrowed_font = cell.font()
                    borrowed_font.setItalic(True)
                    cell.setFont(borrowed_font)
                    cell.setToolTip(
                        "An earlier operation in this session already changed this. It is not "
                        "the game's default."
                    )
                self._states.setItem(row_index, column, cell)

    def _refresh_animations(self, plan: Optional[MovePlan]) -> None:
        chosen = self.chosen_replacements()
        total = len(self._file_model.rows)
        self._count_label.setText(f"{len(chosen)} of {total} animation files selected")
        self._risk_label.setText(" · ".join(carry.risk_warnings(chosen)))
        self._risk_label.setVisible(bool(self._risk_label.text()))
        advanced = self.scope().is_advanced
        self._advanced_confirm.setVisible(advanced)
        self._advanced_confirm.setEnabled(advanced)


    def _refresh_review(self, plan: Optional[MovePlan]) -> None:
        if plan is None:
            self._review_view.setPlainText(self._unit_error or "Select an item")
            self._blocker_label.setText(self._unit_error)
            self._blocker_label.setVisible(bool(self._unit_error))
            return
        lines = list(plan.review_lines())
        prepared = self.prepared()
        if prepared is not None:
            lines += ["", "Exact export payloads"]
            for file in prepared.files:
                lines += [f"{'CHANGE' if file.changed else 'UNCHANGED'} {file.path}",
                          f"  From: {file.donor_path or 'placement edits'}"]
            lines += ["", "Checks"]
            lines += [f"{c.name}: {c.status} — {c.detail}" for c in prepared.checks]
        else:
            lines += ["", "Proposed animation mappings — preparation required"]
            lines += [f"{r.target_path} ← {r.donor.path}" for r in plan.request.replacements]
        self._review_view.setPlainText("\n".join(lines))
        self._blocker_label.setText("\n".join(plan.blockers))
        self._blocker_label.setVisible(bool(plan.blockers))
