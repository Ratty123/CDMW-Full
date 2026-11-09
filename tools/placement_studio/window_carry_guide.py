"""Carry > Where it hangs: the guided move, inline.

Pick a spot and the plan shows in the pinned footer; **Move it** applies it as one placement
operation. A body that holds the weapon in the left hand (Damiane, and female Kliff with
Character Creator or Heroine of Pywel) is mirrored by default: `carry_plan.plan_mirrored_move`
makes a new attach point so the weapon hangs where it would on the chosen spot, reflected
across the body. The descriptor rows that decide where the weapon and its case hang are one
click away under **Rows**. Animations and timing stay on the Animations tab.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from . import carry_plan
from . import ui_kit as kit

_ROW_COLUMNS = ("Row", "Put away on", "Put-away child", "Held in", "Held child", "Case")


def _row_headings():
    return [translate_active_ui_text("Part"), translate_active_ui_text("Row"),
            translate_active_ui_text("Put away on"), translate_active_ui_text("Put-away child"),
            translate_active_ui_text("Held in"), translate_active_ui_text("Held child"),
            translate_active_ui_text("Case")]


class CarryRowsDialog(QDialog):
    """The descriptor rows that decide where the weapon and its case hang on this body."""

    def __init__(self, parent=None, *, body: str, rows: Sequence[Tuple[str, dict]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate_active_ui_text(f"Rows on {body}"))
        self.setMinimumWidth(760)
        layout = QVBoxLayout(self)
        layout.addWidget(kit.hint(translate_active_ui_text(
            "Where a weapon hangs is decided by its row in this body's descriptor; the case row "
            "moves with it.")))
        self.table = QTableWidget(len(rows), len(_ROW_COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels(_row_headings())
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for index, (role, values) in enumerate(rows):
            cells = [role] + [values.get(column, "") or "-" for column in _ROW_COLUMNS]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(values.get("File", ""))
                self.table.setItem(index, column, item)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class CarryGuideMixin:
    """The Where it hangs section and its pinned Move it. Mixed into `PlacementStudioWindow`."""

    # ── construction ────────────────────────────────────────────────

    def _build_carry_where_section(self) -> kit.Section:
        self._carry_plan = None
        self._carry_plan_error = ""
        self._carry_mirror_spot = ""
        self._carry_now = QLabel("-")
        self._carry_hand = QLabel("-")
        self._carry_mirror = QCheckBox(translate_active_ui_text("Mirror to the other side"))
        self._carry_mirror.setToolTip(translate_active_ui_text(
            "Makes a new attach point so the weapon hangs where it would on the chosen spot, "
            "reflected across the body. On by default for a body that holds the weapon in the "
            "left hand. Each body file gets its own value."))
        self._carry_mirror.toggled.connect(lambda _checked: self._refresh_carry_plan(keep_mirror=True))
        self._carry_rows_button = QPushButton(translate_active_ui_text("Weapon and case rows…"))
        self._carry_rows_button.setToolTip(translate_active_ui_text(
            "The descriptor rows that decide where the weapon and its case hang on this body."))
        self._carry_rows_button.clicked.connect(self._show_carry_rows)
        form = kit.Form()
        form.add(translate_active_ui_text("Now"), self._carry_now)
        form.add(translate_active_ui_text("Move to"), self._carry_box)
        form.add(translate_active_ui_text("Side"), self._carry_mirror)
        form.add(translate_active_ui_text("Held in"), self._carry_hand)
        form.add(translate_active_ui_text("Rows"), kit.row(self._carry_rows_button))
        return kit.Section(translate_active_ui_text("Where it hangs"), form)

    def _build_carry_footer(self) -> QWidget:
        self._carry_plan_label = QLabel("")
        self._carry_plan_label.setWordWrap(True)
        self._carry_move_button = kit.primary(translate_active_ui_text("Move it"))
        self._carry_move_button.setEnabled(False)
        self._carry_move_button.clicked.connect(self._on_carry_move_clicked)
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._carry_plan_label, 1)
        layout.addWidget(self._carry_move_button)
        return footer

    # ── the plan ────────────────────────────────────────────────────

    def _carry_unit(self):
        session = self._session
        binding = self._current_binding() if session is not None else None
        if session is None or self._edits is None or binding is None:
            return None, None, ""
        unit, error = self._resolve_unit(binding.part_name)
        if unit is None:
            return None, binding, error
        return unit, binding, ""

    def _plan_carry(self, socket: str, mirrored: bool):
        from . import carry
        from .move_operation import MoveRequest, plan_move

        unit, _binding, error = self._carry_unit()
        if unit is None:
            return None, error
        request = MoveRequest(unit=unit, destination_socket=socket,
                              scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY))
        try:
            if mirrored:
                return carry_plan.plan_mirrored_move(self._session, self._edits, request), ""
            return plan_move(self._session, self._edits, request), ""
        except carry_plan.MirrorError as exc:
            return None, str(exc)

    def _refresh_carry_plan(self, *, keep_mirror: bool = False) -> None:
        """Re-plan for the spot and side shown, and say in the footer what Move it would do."""

        if not hasattr(self, "_carry_move_button"):
            return
        from .clip_names import socket_label

        session = self._session
        binding = self._current_binding() if session is not None else None
        part = binding.part if binding is not None else None
        spot = str(self._carry_box.currentData() or "")
        current = getattr(part, "in_socket", "") or ""
        hand = carry_plan.held_hand(part) if part is not None else ""
        self._carry_now.setText(socket_label(current) if current else "-")
        self._carry_hand.setText({
            "left": translate_active_ui_text("Left hand: mirror spots made for the right hand"),
            "right": translate_active_ui_text("Right hand"),
        }.get(hand, "-"))
        possible = bool(spot) and carry_plan.mirrorable(spot)
        self._carry_mirror.blockSignals(True)
        self._carry_mirror.setEnabled(possible)
        if not keep_mirror or spot != self._carry_mirror_spot:
            self._carry_mirror.setChecked(possible and hand == "left")
        if not possible:
            self._carry_mirror.setChecked(False)
        self._carry_mirror.blockSignals(False)
        self._carry_mirror_spot = spot
        mirrored = self._carry_mirror.isChecked()
        plan, error = self._plan_carry(spot, mirrored) if spot and part is not None else (None, "")
        self._carry_plan, self._carry_plan_error = plan, error
        can_move = plan is not None and not plan.blocked and plan.changes_anything
        self._carry_move_button.setEnabled(can_move)
        if plan is None:
            text = error or translate_active_ui_text("Choose a spot.")
        elif plan.blocked:
            text = plan.blockers[0]
        elif not plan.changes_anything:
            text = translate_active_ui_text("It already hangs there.")
        elif mirrored:
            text = translate_active_ui_text(
                f"{socket_label(current)} → {socket_label(spot)}, mirrored "
                f"({plan.request.destination_socket})")
        else:
            text = f"{socket_label(current)} → {socket_label(spot)}"
        self._carry_plan_label.setText(text)
        self._carry_plan_label.setToolTip("\n".join(plan.review_lines()) if plan is not None else "")

    def _on_carry_spot_changed(self, _index: int) -> None:
        if getattr(self, "_carry_syncing", False):
            return
        self._refresh_carry_plan()

    def _on_carry_move_clicked(self) -> None:
        plan = getattr(self, "_carry_plan", None)
        if plan is None or plan.blocked or not plan.changes_anything:
            return
        if plan.mirror_of:
            # A created attach point is not something the move preparation replays, so a
            # mirrored placement is applied directly; it changes no animation.
            self._apply_move_operation(plan, None)
        else:
            self._on_carry_changed(0)
        self._refresh_carry_plan()

    def _show_carry_rows(self) -> Optional[CarryRowsDialog]:
        unit, _binding, error = self._carry_unit()
        if unit is None:
            self.statusBar().showMessage(error or translate_active_ui_text(
                "Choose a character and a slot first."))
            return None
        dialog = CarryRowsDialog(self, body=carry_plan.body_label(self._session.model),
                                 rows=carry_plan.describe_rows(unit, self._edits))
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.open()
        return dialog
