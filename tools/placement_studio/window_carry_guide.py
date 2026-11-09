"""Position > Where it is carried > Carry it somewhere else...: the guided move.

Steps 1 and 2 of `WEAPON_CARRY.md`'s panel: what moves (the slot's descriptor rows on this
body, and the hand it holds the item in) and where (a spot on this body, mirrored for a body
that holds the item in the left hand). It plans with `move_operation.plan_move`, or
`carry_plan.plan_mirrored_move` for a mirrored carry, shows the plan in words, and applies it
as one placement operation. Animations and timing stay on the Animations tab.

The dialog takes its answers from callbacks, so it can be built and driven without a game.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from . import carry_plan
from .move_weapon import PERSPECTIVE_NOTE, socket_choice_label

_ROW_COLUMNS = ("Row", "Put away on", "Put-away child", "Held in", "Held child", "Case")


def _row_headings():
    return [translate_active_ui_text("Part"), translate_active_ui_text("Row"),
            translate_active_ui_text("Put away on"), translate_active_ui_text("Put-away child"),
            translate_active_ui_text("Held in"), translate_active_ui_text("Held child"),
            translate_active_ui_text("Case")]


class CarryGuideDialog(QDialog):
    """Ask what moves and where, show the plan, and apply it.

    * `plan_for(socket, mirrored)` returns `(plan, error)`.
    * `apply(plan)` records it and returns "" or a reason it was not applied.
    """

    def __init__(
        self,
        parent=None,
        *,
        body: str,
        slot: str,
        rows: Sequence[Tuple[str, dict]],
        hand: str,
        positions: Sequence[Tuple[str, str]],
        current: str = "",
        plan_for: Callable[[str, bool], Tuple[object, str]],
        apply: Callable[[object], str],
        other_body: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate_active_ui_text("Carry it somewhere else"))
        self.setMinimumWidth(720)
        self._plan_for = plan_for
        self._apply = apply
        self._plan = None
        self._hand = hand
        layout = QVBoxLayout(self)

        intro = QLabel(translate_active_ui_text(
            f"Body: {body}. Where a weapon hangs is decided by its row in this body's "
            f"descriptor, and the case row moves with it."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        what = QGroupBox(translate_active_ui_text(f"1. What moves: {slot}"))
        what_layout = QVBoxLayout(what)
        self._rows = QTableWidget(len(rows), len(_ROW_COLUMNS) + 1)
        self._rows.setHorizontalHeaderLabels(_row_headings())
        self._rows.verticalHeader().setVisible(False)
        self._rows.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rows.setSelectionMode(QAbstractItemView.NoSelection)
        self._rows.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for index, (role, values) in enumerate(rows):
            cells = [role] + [values.get(column, "") or "-" for column in _ROW_COLUMNS]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(values.get("File", ""))
                self._rows.setItem(index, column, item)
        self._rows.setMaximumHeight(32 + 28 * max(1, len(rows)))
        what_layout.addWidget(self._rows)
        hand_text = {
            "left": translate_active_ui_text(
                "This body holds it in the left hand, so a carry made for the right hand looks "
                "wrong here: mirror it to the other side."),
            "right": translate_active_ui_text("This body holds it in the right hand."),
        }.get(hand, translate_active_ui_text("The row names no hand to hold it in."))
        self._hand_label = QLabel(hand_text)
        self._hand_label.setWordWrap(True)
        what_layout.addWidget(self._hand_label)
        layout.addWidget(what)

        where = QGroupBox(translate_active_ui_text("2. Where it is carried"))
        form = QFormLayout(where)
        self._spot = QComboBox()
        for socket, label in positions:
            self._spot.addItem(socket_choice_label(socket, label), socket)
        position = self._spot.findData(current)
        if position >= 0:
            self._spot.setCurrentIndex(position)
        self._spot.currentIndexChanged.connect(self._on_spot_changed)
        form.addRow(translate_active_ui_text("Spot:"), self._spot)
        self._mirror = QCheckBox(translate_active_ui_text("Mirror it to the other side of the body"))
        self._mirror.setToolTip(translate_active_ui_text(
            "Makes a new attach point so the weapon hangs where it would on the chosen spot, "
            "reflected across the body. Each body file gets its own value."))
        self._mirror.toggled.connect(lambda _checked: self._refresh())
        form.addRow("", self._mirror)
        perspective = QLabel(translate_active_ui_text(PERSPECTIVE_NOTE))
        perspective.setObjectName("HintLabel")
        form.addRow("", perspective)
        layout.addWidget(where)

        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setMinimumHeight(140)
        layout.addWidget(self._summary, 1)

        next_steps = translate_active_ui_text(
            "Afterwards: the draw and put-away animations stay as they are. Give the weapon "
            "draws for its new place on the Animations tab, then use Draw and put-away timing "
            "there.")
        if other_body:
            next_steps += " " + translate_active_ui_text(
                f"{other_body} has rows of its own: switch Character and do the same there, and "
                f"save each body as its own mod.")
        hint = QLabel(next_steps)
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox()
        self._move = QPushButton(translate_active_ui_text("Move it"))
        self._move.clicked.connect(self._on_move)
        buttons.addButton(self._move, QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)
        self._on_spot_changed()

    # ── reacting ────────────────────────────────────────────────────

    def spot(self) -> str:
        return str(self._spot.currentData() or "")

    def mirrored(self) -> bool:
        return self._mirror.isEnabled() and self._mirror.isChecked()

    def plan(self):
        return self._plan

    def _on_spot_changed(self, _index: int = 0) -> None:
        possible = carry_plan.mirrorable(self.spot())
        self._mirror.blockSignals(True)
        self._mirror.setEnabled(possible)
        self._mirror.setChecked(possible and self._hand == "left")
        self._mirror.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        spot = self.spot()
        plan, error = self._plan_for(spot, self.mirrored()) if spot else (None, "")
        self._plan = plan
        lines: list = []
        if error:
            lines.append(error)
        if plan is not None:
            lines += list(plan.review_lines())
        self._summary.setPlainText("\n".join(lines) or translate_active_ui_text("Choose a spot."))
        self._move.setEnabled(plan is not None and not plan.blocked and plan.changes_anything)
        if plan is not None and not plan.changes_anything:
            self._move.setText(translate_active_ui_text("It is already there"))
        else:
            self._move.setText(translate_active_ui_text("Move it"))

    def _on_move(self) -> None:
        if self._plan is None:
            return
        problem = self._apply(self._plan)
        if problem:
            self._summary.appendPlainText("\n" + problem)
            return
        self.accept()


class CarryGuideMixin:
    """Opens the guide from Position. Mixed into `PlacementStudioWindow`."""

    def _open_carry_guide(self) -> Optional[CarryGuideDialog]:
        from . import carry
        from .move_operation import MoveRequest, plan_move

        session, edits = self._session, self._edits
        binding = self._current_binding() if session is not None else None
        if session is None or edits is None or binding is None:
            self.statusBar().showMessage(translate_active_ui_text(
                "Choose a character and a slot first."))
            return None
        unit, error = self._resolve_unit(binding.part_name)
        if unit is None:
            self.statusBar().showMessage(error)
            return None
        part = session.descriptor_part(unit.primary_part) or binding.part

        def plan_for(socket: str, mirrored: bool):
            request = MoveRequest(unit=unit, destination_socket=socket,
                                  scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY))
            try:
                if mirrored:
                    return carry_plan.plan_mirrored_move(session, edits, request), ""
                return plan_move(session, edits, request), ""
            except carry_plan.MirrorError as exc:
                return None, str(exc)

        def apply(plan) -> str:
            before = len(edits.operations())
            self._apply_move_operation(plan, None)
            if len(edits.operations()) == before:
                return translate_active_ui_text("Nothing was changed; the status bar says why.")
            return ""

        other = {"1_phm": "2_phw", "2_phw": "1_phm"}.get(session.model, "")
        positions = [(socket, label) for socket, label in carry.carry_positions(session)
                     if socket not in carry.HELD_SOCKETS]
        dialog = CarryGuideDialog(
            self,
            body=carry_plan.body_label(session.model),
            slot=unit.primary_part,
            rows=carry_plan.describe_rows(unit, edits),
            hand=carry_plan.held_hand(part),
            positions=positions,
            current=part.in_socket or "",
            plan_for=plan_for,
            apply=apply,
            other_body=carry_plan.body_label(other) if other else "",
        )
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.open()
        return dialog
