"""One dialog for the whole job, asked one decision at a time.

The job was previously spread across four controls in three places, and then collapsed into a
single long form. Both had the same fault: the form showed the *pending* state as though it
were the game's default, offered `Everything` beside `Draws only` with only a file count to
choose by, and enabled a button labelled `Move it` for a change that moved nothing.

Four pages now, in the order the question is actually asked:

1. **Equipment** — which item, and what else belongs to it.
2. **Placement and linked parts** — where it goes, what aims it there, and what comes along.
3. **Animations** — how much of the motion set follows, by preset and by context.
4. **Review** — every row, socket, file and family that will change, before anything does.

Nothing is applied until the review page has been seen and the action accepted. The action's
own text says what it will do, so a placement no-op cannot present itself as a move.
"""

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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import carry
from .move_operation import MovePlan, MoveRequest

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


class _Choice:
    """One decision, covering every clip that asks the same question.

    The game keeps several takes of each moment — `weapon_in_000`, `_002`, `_004` and their
    distance copies — and picks between them at runtime for variety. Asking which stand-in to
    use for each separately produced twenty rows of "put the weapon away, version 4" with
    identical-looking answers, which is not a question anyone can act on.

    So the choice is made once per *kind* of animation, and what is chosen is a style: every
    clip in the group then takes the stand-in of that style matching its own take.
    """

    def __init__(self, label: str, styles, on_preview=None) -> None:
        self.label = label
        self.box = QComboBox()
        self._examples: Dict[str, object] = {}
        for style, text, example, entry in styles:
            self.box.addItem(text, style)
            self.box.setItemData(self.box.count() - 1, example, Qt.ToolTipRole)
            self._examples[style] = entry

        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.box, 1)
        self.preview = QPushButton("Watch")
        # "Style 1" against "Style 2" is not a question anyone can answer from the name: the
        # two differ only in stance, which has no word for it. Being able to watch each one is
        # what turns it into a real choice.
        self.preview.setToolTip("Play this style on the character so you can see it.")
        self.preview.setMaximumWidth(72)
        if on_preview is None:
            self.preview.setEnabled(False)
        else:
            self.preview.clicked.connect(lambda: on_preview(self.example()))
        row.addWidget(self.preview)

    def style(self) -> str:
        return str(self.box.currentData() or "")

    def example(self):
        """A clip in the selected style, for the preview to play."""

        return self._examples.get(self.style())


class MoveWeaponDialog(QDialog):
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
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move a weapon")
        self.setMinimumSize(760, 620)

        self._unit = unit
        self._unit_error = ""
        self._unit_for = unit_for
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
        self._rows: List[Tuple[QTreeWidgetItem, list, Optional[_Choice]]] = []
        self._choices: Dict[object, _Choice] = {}
        self._link_boxes: Dict[str, QCheckBox] = {}
        self._context_boxes: Dict[str, QCheckBox] = {}
        self._plan: Optional[MovePlan] = None
        self._reviewed = False
        #: Set while controls are being rebuilt, so a programmatic change is not read as a
        #: user decision that would rebuild them again.
        self._syncing = True

        self._pages = QTabWidget()
        self._pages.addTab(self._build_equipment_page(parts), "1. Equipment")
        self._pages.addTab(self._build_placement_page(), "2. Placement and linked parts")
        self._pages.addTab(self._build_animation_page(), "3. Animations")
        self._pages.addTab(self._build_review_page(), "4. Review")
        self._pages.currentChanged.connect(self._on_page_changed)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._back = self._buttons.addButton("Back", QDialogButtonBox.ActionRole)
        self._next = self._buttons.addButton("Next", QDialogButtonBox.ActionRole)
        self._accept = self._buttons.addButton(REVIEW_FIRST_LABEL, QDialogButtonBox.AcceptRole)
        self._back.clicked.connect(lambda: self._step(-1))
        self._next.clicked.connect(lambda: self._step(1))
        # Not connected to `accept` directly: until the review page has been opened this
        # button's job is to open it.
        self._accept.clicked.connect(self._on_accept_clicked)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner())
        layout.addWidget(self._pages, 1)
        layout.addWidget(self._buttons)
        self._syncing = False
        self._point_destination_at_current()
        self._reload_clips()
        self._refresh()

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
        page = QWidget()
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
            "Allow leaving a required linked part behind (advanced, high risk)"
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
        layout.addWidget(self._link_warning)
        layout.addStretch(1)
        return page

    def _build_placement_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._to_box = QComboBox()
        for socket, label in self._positions:
            self._to_box.addItem(socket_choice_label(socket, label), socket)
        self._to_box.setToolTip("Where the item should hang when stowed.")
        self._to_box.currentIndexChanged.connect(self._on_destination_changed)

        form = QFormLayout()
        form.addRow("Move it to:", self._to_box)
        self._zone_label = QLabel()
        form.addRow("Destination zone:", self._zone_label)
        self._orientation_label = QLabel()
        self._orientation_label.setWordWrap(True)
        form.addRow("Orientation from:", self._orientation_label)
        self._new_socket_label = QLabel()
        self._new_socket_label.setWordWrap(True)
        form.addRow("New child sockets:", self._new_socket_label)
        self._shared_label = QLabel()
        self._shared_label.setWordWrap(True)
        form.addRow("Shared sockets:", self._shared_label)
        layout.addLayout(form)

        perspective = QLabel(PERSPECTIVE_NOTE)
        perspective.setWordWrap(True)
        layout.addWidget(perspective)

        # 5.2: three states, side by side. Showing only the third is how an earlier
        # experiment's `Pelvis_R_Socket` came to read as the game's default.
        self._states = QTableWidget(0, 4)
        self._states.setHorizontalHeaderLabels(
            ["Field", "Vanilla", "Pending before this operation", "Proposed"]
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
        layout.addWidget(self._states, 1)

        self._orientation_reviewed = QCheckBox(
            "I have looked at the orientation and it is correct"
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
        page = QWidget()
        layout = QVBoxLayout(page)

        scope_group = QGroupBox("How much of the animation set follows")
        scope_layout = QVBoxLayout(scope_group)
        self._scope_buttons: Dict[str, QRadioButton] = {}
        for kind in carry.SCOPE_ORDER:
            button = QRadioButton(carry.SCOPE_LABELS[kind])
            button.setToolTip(carry.SCOPE_HINTS.get(kind, ""))
            button.toggled.connect(lambda checked: self._on_scope_changed() if checked else None)
            scope_layout.addWidget(button)
            self._scope_buttons[kind] = button
        self._scope_buttons[carry.SCOPE_DRAW_STOW].setChecked(True)
        layout.addWidget(scope_group)

        self._advanced_confirm = QCheckBox(
            "I understand full-body replacement changes the off-hand, shield arm and stance"
        )
        self._advanced_confirm.toggled.connect(lambda _c: self._refresh())
        layout.addWidget(self._advanced_confirm)

        context_group = QGroupBox("Contexts (leave alone to use the preset's own set)")
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

        options = QHBoxLayout()
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
        options.addStretch(1)
        layout.addLayout(options)

        # A tree, not a flat list. Every row used to repeat its context — twelve rows each
        # opening "Standing — put the weapon away" — so the words that differed were at the far
        # end of a sentence that was the same every time. The context is the heading now.
        self._clip_list = QTreeWidget()
        self._clip_list.setHeaderHidden(True)
        self._clip_list.setColumnCount(3)
        self._clip_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._clip_list.setUniformRowHeights(True)
        self._clip_list.setMinimumHeight(200)
        self._clip_list.setRootIsDecorated(False)
        self._clip_list.setIndentation(14)
        clip_header = self._clip_list.header()
        clip_header.setStretchLastSection(False)
        clip_header.setSectionResizeMode(0, QHeaderView.Stretch)
        clip_header.setSectionResizeMode(1, QHeaderView.Fixed)
        clip_header.setSectionResizeMode(2, QHeaderView.Fixed)
        self._clip_list.setColumnWidth(1, 150)
        self._clip_list.setColumnWidth(2, 76)
        self._clip_list.setToolTip(
            "Every file that will be replaced. Untick any you want left alone, or select one "
            "and press Watch to see the animation it would get."
        )
        self._clip_list.itemChanged.connect(lambda _i, _c: self._refresh())
        layout.addWidget(self._clip_list, 1)

        self._risk_label = QLabel()
        self._risk_label.setObjectName("WarningText")
        self._risk_label.setWordWrap(True)
        layout.addWidget(self._risk_label)

        buttons = QHBoxLayout()
        self._count_label = QLabel("")
        buttons.addWidget(self._count_label, 1)
        watch = QPushButton("Watch selected")
        watch.setToolTip(
            "Play the animation this row would be given, so you can judge every replacement "
            "and not only the ones that offered a choice."
        )
        watch.setEnabled(self._on_preview is not None)
        watch.clicked.connect(self._watch_selected)
        buttons.addWidget(watch)
        for text, checked in (("Select all", True), ("Select none", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, value=checked: self._set_all(value))
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._play_after = QCheckBox("Play the new animation when this is done")
        self._play_after.setChecked(True)
        self._play_after.setToolTip(
            "Poses the character with the animation that was just installed, in its new "
            "position, so you can see both at once."
        )
        layout.addWidget(self._play_after)
        return page

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._review_view = QPlainTextEdit()
        self._review_view.setReadOnly(True)
        self._review_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self._review_view, 1)

        self._blocker_label = QLabel()
        self._blocker_label.setObjectName("HintLabel")
        self._blocker_label.setProperty("healthState", "unhealthy")
        self._blocker_label.setWordWrap(True)
        layout.addWidget(self._blocker_label)

        shortcuts = QHBoxLayout()
        self._preview_placement = QPushButton("Preview placement")
        self._preview_placement.setToolTip("Show the proposed placement on the character.")
        self._preview_placement.setEnabled(self._on_preview_placement is not None)
        self._preview_placement.clicked.connect(
            lambda: self._on_preview_placement and self._plan
            and self._on_preview_placement(self._plan)
        )
        shortcuts.addWidget(self._preview_placement)

        self._preview_animation = QPushButton("Preview selected animation")
        self._preview_animation.setEnabled(self._on_preview is not None)
        self._preview_animation.clicked.connect(self._watch_selected)
        shortcuts.addWidget(self._preview_animation)

        self._show_files = QPushButton("Show exact files")
        self._show_files.setEnabled(self._on_show_files is not None)
        self._show_files.clicked.connect(
            lambda: self._on_show_files and self._plan and self._on_show_files(self._plan)
        )
        shortcuts.addWidget(self._show_files)

        reset = QPushButton("Reset this operation")
        reset.setToolTip("Put every control on these pages back to its starting value.")
        reset.clicked.connect(self._reset)
        shortcuts.addWidget(reset)

        discard = QPushButton("Discard this operation")
        discard.setToolTip("Close without changing anything.")
        discard.clicked.connect(self.reject)
        shortcuts.addWidget(discard)
        shortcuts.addStretch(1)
        layout.addLayout(shortcuts)
        return page

    # ── navigation ──────────────────────────────────────────────────

    def _step(self, delta: int) -> None:
        self._pages.setCurrentIndex(
            max(0, min(self._pages.count() - 1, self._pages.currentIndex() + delta))
        )

    def _on_page_changed(self, index: int) -> None:
        if index == PAGE_REVIEW:
            self._reviewed = True
        self._refresh()

    def _on_accept_clicked(self) -> None:
        if not self._reviewed or self._pages.currentIndex() != PAGE_REVIEW:
            self._pages.setCurrentIndex(PAGE_REVIEW)
            return
        self.accept()

    # ── reacting to changes ─────────────────────────────────────────

    def _on_part_changed(self) -> None:
        """E4: changing the item invalidates and rebuilds *everything* that depends on it.

        Not only the "hangs on now" label, which is what it used to do — leaving handedness,
        the animation families, the donor list and the child-socket ownership belonging to the
        previously selected weapon.
        """

        if self._syncing or self._unit_for is None:
            return
        part_name = str(self._part_box.currentData() or "")
        unit, error = self._unit_for(part_name)
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
        # A same-zone move needs no animation change; a hip-to-back move needs draw and stow.
        # Recommended, never imposed: the user may already have chosen something wider.
        recommended = carry.recommended_scope(
            getattr(self._unit, "in_socket", "") or "", self._destination()
        )
        self._syncing = True
        self._scope_buttons[recommended].setChecked(True)
        self._syncing = False
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
        while self._links_layout.count():
            item = self._links_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._link_boxes = {}
        unit = self._unit
        links = list(getattr(unit, "linked_parts", ()) or ())
        primary = QCheckBox(f"{getattr(unit, 'primary_part', '(none)')}   —   primary item")
        primary.setChecked(True)
        primary.setEnabled(False)
        self._links_layout.addWidget(primary)
        if not links:
            self._links_layout.addWidget(QLabel("  No linked row — this item carries nothing."))
            return
        for link in links:
            box = QCheckBox(f"{link.part_name}   —   {link.role}")
            box.setChecked(True)
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
        """Fill the file list, and reduce it to one decision per kind of animation."""

        import collections

        from .clip_names import (
            family_label, friendly, group_key, lane_of, short_label, stance_of,
        )

        self._syncing = True
        try:
            self._clip_list.clear()
            self._rows = []
            self._choices = {}
            self._rebuild_links()
            if self._unit is None:
                return
            rows = list(self._pairs_for(self._unit, self.scope()))
            if not rows:
                return

            # Where every row borrows from the same family — the usual case, since a swap runs
            # in one direction — naming it on each row restates the sentence at the top of the
            # dialog twenty-eight times. It is shown only when rows actually differ.
            donor_families = {family_label(row.donor.name) for row in rows}
            name_the_donor = len(donor_families) > 1

            lanes: Dict[str, QTreeWidgetItem] = {}
            merged: "collections.OrderedDict[object, list]" = collections.OrderedDict()
            for row in rows:
                merged.setdefault(group_key(row.target.name), []).append(row)

            # Two rows in a lane that would read alike get the state that separates them, so
            # every row is distinguishable without repeating the heading's own word.
            labels = collections.Counter(
                (lane_of(v[0].target.name, self._chart_lanes), short_label(v[0].target.name))
                for v in merged.values()
            )

            for key, members in merged.items():
                first = members[0]
                target, donor = first.target, first.donor
                name = lane_of(target.name, self._chart_lanes)
                label = short_label(target.name)
                lane = lanes.get(name)
                if lane is None:
                    lane = QTreeWidgetItem(self._clip_list, [name])
                    lane.setFirstColumnSpanned(True)
                    lane.setExpanded(True)
                    lanes[name] = lane
                text = label
                # Both families, not just the one being replaced. `Drawing the weapon · dual
                # swords` named the clip this row *overwrites*, while Watch beside it plays the
                # clip that would replace it — reading the row as a description of what you are
                # about to see is the obvious reading, and it was wrong.
                worn, borrowed_family = family_label(target.name), family_label(donor.name)
                if labels[(name, label)] > 1 or worn != borrowed_family:
                    text = f"{text}  ·  {worn.lower()}"
                    if name_the_donor and borrowed_family and borrowed_family != worn:
                        text = f"{text}  ←  {borrowed_family.lower()}"

                risky = [row for row in members if row.risks]
                borrowed = [row for row in members if row.borrowed]
                if borrowed:
                    text += "   ·  borrowed" if len(borrowed) == len(members) else (
                        f"   ·  {len(borrowed)} borrowed"
                    )
                if any(row.dual_wield_donor for row in members):
                    text += "   ·  dual-wield donor"

                item = QTreeWidgetItem(lane, [text])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked)
                if borrowed:
                    borrowed_font = item.font(0)
                    borrowed_font.setItalic(True)
                    item.setFont(0, borrowed_font)
                risk_note = "\n".join(
                    f"{note}" for note in dict.fromkeys(n for row in risky for n in row.risks)
                )
                item.setToolTip(
                    0,
                    (f"{risk_note}\n\n" if risk_note else "")
                    + "\n".join(
                        f"{row.target.name}\n   ←  {row.donor.name}" for row in members
                    ),
                )

                # The style choice lives on the row it belongs to. It used to sit in a separate
                # block above, so the same thing appeared twice and the list under it looked
                # like a set of rows nobody had decided about.
                styles: Dict[str, object] = {}
                for row in members:
                    for option in (row.options or (row.donor,)):
                        styles.setdefault(stance_of(option.name), option)
                choice = None
                if len(styles) > 1:
                    ordered = sorted(styles.items())
                    choice = _Choice(
                        text,
                        [
                            (stance, f"Style {n + 1}",
                             f"{friendly(example.name)}\n     {example.name}", example)
                            for n, (stance, example) in enumerate(ordered)
                        ],
                        on_preview=self._on_preview,
                    )
                    self._choices[key] = choice
                    self._clip_list.setItemWidget(item, 1, choice.box)
                else:
                    stand_in = short_label(donor.name)
                    if stand_in != label:
                        item.setText(0, f"{text}   ←  {stand_in}")

                if self._on_preview is not None:
                    watch = QPushButton("Watch")
                    watch.setFlat(True)
                    watch.setMaximumWidth(64)
                    watch.setToolTip("Play the animation this row would be given.")
                    watch.clicked.connect(lambda _c=False, i=item: self._watch_row(i))
                    self._clip_list.setItemWidget(item, 2, watch)
                self._rows.append((item, members, choice))

            for name, lane in lanes.items():
                total = sum(
                    len(members) for item, members, _c in self._rows if item.parent() is lane
                )
                lane.setText(0, f"{name}   ({total})")
        finally:
            self._syncing = False

    # ── selection ───────────────────────────────────────────────────

    def _watch_selected(self) -> None:
        self._watch_row(self._clip_list.currentItem())

    def _watch_row(self, item) -> None:
        """Play the stand-in one row would be given. Lane headings play nothing."""

        if self._on_preview is None or item is None:
            return
        found = next((r for r in self._rows if r[0] is item), None)
        if found is None:
            return
        _item, members, choice = found
        donor = choice.example() if choice is not None else members[0].donor
        if donor is not None:
            self._on_preview(donor)

    def _set_all(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self._syncing = True
        for item, _members, _choice in self._rows:
            item.setCheckState(0, state)
        self._syncing = False
        self._refresh()

    def chosen_replacements(self) -> Tuple[object, ...]:
        """Every replacement a ticked row stands for, with its chosen style applied."""

        from .clip_names import stance_of

        chosen: List[object] = []
        for item, members, choice in self._rows:
            if item.checkState(0) != Qt.Checked:
                continue
            for row in members:
                if choice is None:
                    chosen.append(row)
                    continue
                wanted = choice.style()
                donor = next(
                    (o for o in (row.options or (row.donor,)) if stance_of(o.name) == wanted),
                    row.donor,
                )
                chosen.append(replace(row, donor=donor))
        return tuple(chosen)

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
        """The stand-in to play afterwards: the one the first decision settled.

        A decision the user actually made is the only honest thing to show. Picking a clip by
        any other rule means the animation that plays was never among the options, which reads
        as the choice having been ignored.
        """

        for choice in self._choices.values():
            if "drawing" in choice.label.lower():
                return choice.example()
        for choice in self._choices.values():
            return choice.example()
        chosen = self.chosen_replacements()
        return chosen[0].donor if chosen else None

    # ── refresh ─────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._syncing:
            return
        unit = self._unit
        self._unit_label.setText(unit.describe() if unit is not None else "(unresolved)")
        self._unit_problem.setText(self._unit_error)

        request = self.request()
        plan = None
        if request is not None and self._plan_for is not None:
            plan = self._plan_for(request)
        self._plan = plan

        self._refresh_placement(plan)
        self._refresh_animations(plan)
        self._refresh_review(plan)

        self._back.setEnabled(self._pages.currentIndex() > 0)
        self._next.setEnabled(self._pages.currentIndex() < self._pages.count() - 1)

        blocked = bool(self._unit_error) or plan is None or plan.blocked
        applicable = plan is not None and plan.changes_anything
        if not self._reviewed:
            self._accept.setText(REVIEW_FIRST_LABEL)
            self._accept.setEnabled(applicable and not blocked)
            return
        self._accept.setText(plan.action_label() if plan is not None else "No changes")
        self._accept.setEnabled(applicable and not blocked)

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
        total = sum(len(m) for _i, m, _c in self._rows)
        undecided = len(self._choices)
        note = f"  —  {undecided} offer a choice; see the Style column" if undecided else ""
        if total:
            self._count_label.setText(
                f"{len(chosen)} of {total} animation file(s) selected{note}"
            )
        elif self.scope().replaces_animations:
            self._count_label.setText("no animation has a counterpart for this weapon")
        else:
            self._count_label.setText("placement only — no animation will be changed")
        self._risk_label.setText("\n".join(carry.risk_warnings(chosen)))
        advanced = self.scope().is_advanced
        self._advanced_confirm.setVisible(advanced)
        self._advanced_confirm.setEnabled(advanced)

    def _refresh_review(self, plan: Optional[MovePlan]) -> None:
        if plan is None:
            self._review_view.setPlainText(
                self._unit_error or "Select an item to resolve this move."
            )
            self._blocker_label.setText(self._unit_error)
            return
        lines = list(plan.review_lines())
        lines += ["", "Files that would change", "-----------------------"]
        lines += [f"  {route.source_file}" for route in plan.routes[:1]]
        lines += [f"  {socket_file}" for socket_file, _name in plan.new_sockets]
        clips = [row.target_path for row in plan.request.replacements]
        lines += [f"  {path}" for path in clips[:40]]
        if len(clips) > 40:
            lines.append(f"  ... and {len(clips) - 40} more animation file(s)")
        self._review_view.setPlainText("\n".join(lines))
        self._blocker_label.setText("\n".join(plan.blockers))
