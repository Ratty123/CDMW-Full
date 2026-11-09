"""The Animations tab's draw and put-away timing: measure, plot, and move hand-offs.

A draw or a sheathe swaps the weapon between the body and the hand at a chart event, not
inside the clip (`carry_timing`). After a weapon is moved or its draw replaced, the event still
fires at the old moment and the weapon pops early or late. This panel measures every hand-off
of the selected slot on a private session off the UI thread, plots the hand-to-weapon gap
under the selected one with its event marked, and records the moves the user accepts as one
operation under Your mod.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.active_ui_translation import translate_active_ui_text

from . import carry_timing

def _columns():
    """The timing table's headings, as literals so the localization manifest finds them."""

    return [translate_active_ui_text("Clip"), translate_active_ui_text("Chart"),
            translate_active_ui_text("Animation"), translate_active_ui_text("Action"),
            translate_active_ui_text("Hand-off now"), translate_active_ui_text("Hand reaches it"),
            translate_active_ui_text("Gap"), translate_active_ui_text("Status")]


def _status_text(status: str) -> str:
    return {
        carry_timing.STATUS_ON_TIME: translate_active_ui_text("On time"),
        carry_timing.STATUS_EARLY: translate_active_ui_text("Swaps early"),
        carry_timing.STATUS_LATE: translate_active_ui_text("Swaps late"),
        carry_timing.STATUS_UNREACHED: translate_active_ui_text("Hand never reaches it"),
        carry_timing.STATUS_UNMEASURED: translate_active_ui_text("Not measured"),
    }.get(status, status)


def _action_text(mode: int) -> str:
    return translate_active_ui_text("Draw") if mode == 1 else translate_active_ui_text("Put away")

#: Marker colours on the plot, on top of the palette's own text and highlight colours.
_NOW = QColor(240, 128, 96)
_CONTACT = QColor(120, 200, 140)


class GapPlot(QWidget):
    """The hand-to-weapon gap over one clip, the played stretch, and both hand-off times."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._retime: Optional[carry_timing.Retime] = None
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setToolTip(translate_active_ui_text(
            "Distance between the weapon in the hand and the weapon on the body. The shaded "
            "stretch is the part of the clip the animation plays; orange is when the hand-off "
            "happens now, green is where the hand reaches the weapon."))

    def show_retime(self, retime: Optional[carry_timing.Retime]) -> None:
        self._retime = retime
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.Base))
        text = palette.color(QPalette.Text)
        retime = self._retime
        curve = retime.curve if retime is not None else None
        if curve is None or len(curve.times) < 2:
            painter.setPen(text)
            painter.drawText(self.rect(), Qt.AlignCenter, translate_active_ui_text(
                "Measure, then select a row to see its gap."))
            return
        area = QRectF(self.rect()).adjusted(44, 10, -10, -24)
        duration = max(curve.duration, retime.event.end, 1e-6)
        top = max(max(curve.gaps), carry_timing.MAX_CONTACT_GAP) * 1.1

        def point(seconds: float, gap: float) -> QPointF:
            return QPointF(area.left() + area.width() * seconds / duration,
                           area.bottom() - area.height() * min(gap, top) / top)

        played = QRectF(point(retime.event.start, top), point(min(retime.event.end, duration), 0))
        shade = QColor(palette.color(QPalette.Highlight))
        shade.setAlpha(40)
        painter.fillRect(played, shade)
        grid = QColor(text)
        grid.setAlpha(90)
        painter.setPen(QPen(grid, 1, Qt.DashLine))
        reach = point(0, carry_timing.MAX_CONTACT_GAP).y()
        painter.drawLine(QPointF(area.left(), reach), QPointF(area.right(), reach))
        painter.setPen(QPen(grid, 1))
        painter.drawLine(area.bottomLeft(), area.bottomRight())
        painter.drawLine(area.bottomLeft(), area.topLeft())
        painter.drawText(QRectF(0, area.top() - 6, 40, 14), Qt.AlignRight, f"{top:.2f} m")
        painter.drawText(QRectF(0, area.bottom() - 7, 40, 14), Qt.AlignRight, "0 m")
        painter.drawText(QRectF(area.right() - 60, area.bottom() + 4, 60, 16), Qt.AlignRight,
                         f"{duration:.2f} s")

        path = QPainterPath(point(curve.times[0], curve.gaps[0]))
        for seconds, gap in zip(curve.times[1:], curve.gaps[1:]):
            path.lineTo(point(seconds, gap))
        painter.setPen(QPen(text, 1.6))
        painter.drawPath(path)

        for seconds, colour, label in (
                (retime.event.begin, _NOW, translate_active_ui_text("now")),
                (retime.contact, _CONTACT, translate_active_ui_text("reaches"))):
            if seconds is None:
                continue
            x = point(seconds, 0).x()
            painter.setPen(QPen(colour, 2))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            painter.drawText(QRectF(x + 3, area.top(), 80, 14), Qt.AlignLeft, label)


class TimingPanelMixin:
    """Draw and put-away timing. Mixed into `PlacementStudioWindow`."""

    def _build_handoff_timing_box(self) -> QGroupBox:
        box = QGroupBox(translate_active_ui_text("Draw and put-away timing"))
        layout = QVBoxLayout(box)
        hint = QLabel(translate_active_ui_text(
            "When a weapon is drawn or put away, the game swaps it between the body and the "
            "hand at a set moment of each animation. After moving a weapon or changing its "
            "animations, that moment can come before or after the hand gets there, and the "
            "weapon pops. Measure finds where the hand reaches the weapon in every draw and "
            "put-away of the selected slot; move a hand-off to that moment and it goes into "
            "Your mod."))
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self._timing_measure = QPushButton(translate_active_ui_text("Measure timing"))
        self._timing_measure.setToolTip(translate_active_ui_text(
            "Plays each draw and put-away of the selected slot on this character, with your "
            "changes, and measures how far the hand is from the weapon on every frame."))
        self._timing_measure.clicked.connect(self._start_timing)
        row.addWidget(self._timing_measure)
        self._timing_status = QLabel("")
        self._timing_status.setWordWrap(True)
        row.addWidget(self._timing_status, 1)
        layout.addLayout(row)

        headings = _columns()
        self._timing_table = QTableWidget(0, len(headings))
        self._timing_table.setHorizontalHeaderLabels(headings)
        self._timing_table.verticalHeader().setVisible(False)
        self._timing_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._timing_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._timing_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        header = self._timing_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self._timing_table.itemSelectionChanged.connect(self._on_timing_selection)
        self._timing_table.setMinimumHeight(120)
        layout.addWidget(self._timing_table, 1)

        self._timing_plot = GapPlot()
        layout.addWidget(self._timing_plot)

        actions = QHBoxLayout()
        self._timing_move = QPushButton(translate_active_ui_text("Move selected to contact"))
        self._timing_move.clicked.connect(lambda: self._move_timing(selected_only=True))
        self._timing_move_all = QPushButton(translate_active_ui_text("Move all to contact"))
        self._timing_move_all.setToolTip(translate_active_ui_text(
            "Every hand-off marked early or late. Those the hand never reaches keep their time."))
        self._timing_move_all.clicked.connect(lambda: self._move_timing(selected_only=False))
        for button in (self._timing_move, self._timing_move_all):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        shared = QLabel(translate_active_ui_text(
            "Timing is saved as whole action charts, and one chart holds the draws of several "
            "weapons. DMM serves one copy of each chart, so another mod that ships the same "
            "chart (Character Creator ships one for the two-hand sword) and this one replace "
            "each other: load this mod after it."))
        shared.setObjectName("HintLabel")
        shared.setWordWrap(True)
        layout.addWidget(shared)

        self._timing_rows: List[carry_timing.Retime] = []
        self._timing_signature = None
        self._timing_task = None
        #: part -> the timing operation in Your mod, and every move it holds.
        self._timing_ops: Dict[str, str] = {}
        self._timing_moves: Dict[str, Dict[str, float]] = {}
        return box

    # ── measuring ───────────────────────────────────────────────────

    def _timing_part(self) -> str:
        binding = self._current_binding() if self._session is not None else None
        return binding.part.part_name if binding is not None else ""

    def _history_signature(self):
        edits = self._edits
        if edits is None:
            return None
        return tuple(edits.commands())

    def _timing_current_signature(self):
        session = self._session
        weapon = session.weapon if session is not None else None
        return (self._history_signature(), session.model if session is not None else "",
                self._timing_part(), weapon.game_path if weapon is not None else "")

    def _start_timing(self) -> None:
        part = self._timing_part()
        if self._session is None or self._edits is None or not part:
            self._timing_status.setText(translate_active_ui_text(
                "Choose a character and a slot on the Position tab first."))
            return
        self._when_clips_ready("timing", self._submit_timing)

    def _submit_timing(self) -> None:
        from copy import copy

        from .animation import actionchart_model
        from .background import LatestTask

        session, edits, part = self._session, self._edits, self._timing_part()
        if session is None or edits is None or not part:
            return
        model = session.model
        charts = {path: edits.chart_bytes(path) for path in edits.charts()
                  if actionchart_model(path) == model}
        files = edits.current_files()
        entries = {entry.path.lower(): entry for entry in getattr(self._clip_index, "entries", ())
                   if not entry.is_lod}
        weapon_path = session.weapon.game_path if session.weapon is not None else ""
        source = copy(session)
        signature = self._timing_current_signature()
        if getattr(self, "_timing_task", None) is None:
            self._timing_task = LatestTask(self)
            self._timing_task.setObjectName("timing_measurement")
            self._timing_task.ready.connect(self._on_timing_ready)
            self._timing_task.progress.connect(self._on_timing_progress)
        self._timing_measure.setEnabled(False)
        self._timing_move.setEnabled(False)
        self._timing_move_all.setEnabled(False)
        self._timing_status.setText(translate_active_ui_text("Measuring..."))
        self._timing_task.submit(lambda cancelled, progress: (signature, _measure(
            source, model, part, weapon_path, charts, files, entries, cancelled, progress)))

    def _on_timing_progress(self, done: int, total: int) -> None:
        self._timing_status.setText(translate_active_ui_text(f"Measuring {done}/{total}..."))

    def _on_timing_ready(self, value, error: str) -> None:
        self._timing_measure.setEnabled(True)
        if value is None:
            self._timing_status.setText(error or translate_active_ui_text("Measuring stopped."))
            return
        signature, (rows, problems) = value
        if signature != self._timing_current_signature():
            self._timing_status.setText(translate_active_ui_text(
                "Something changed while measuring. Measure again."))
            return
        self._timing_signature = signature
        self._show_timing_rows(rows)
        self._timing_status.setToolTip("\n".join(problems))
        movable = sum(1 for row in rows if row.movable)
        if not rows:
            text = translate_active_ui_text(
                "No draw or put-away animation hands this slot over in this character's charts.")
        else:
            text = translate_active_ui_text(
                f"{len(rows)} hand-off(s); {movable} swap early or late.")
        if problems:
            text += " " + translate_active_ui_text(
                f"{len(problems)} could not be read (hover for details).")
        self._timing_status.setText(text)

    def _show_timing_rows(self, rows: List[carry_timing.Retime]) -> None:
        self._timing_rows = list(rows)
        table = self._timing_table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            event = row.event
            contact = f"{row.contact:.3f} s" if row.contact is not None else "-"
            gap = f"{row.gap:.2f} m" if row.gap is not None else "-"
            values = (event.clip_name, event.chart_name, str(event.animation),
                      _action_text(event.mode), f"{event.begin:.3f} s", contact, gap,
                      _status_text(row.status))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip("\n".join(
                    [event.clip, f"{event.chart} :: {event.animation}:{event.event}",
                     translate_active_ui_text(
                         f"Plays {event.start:.3f} to {event.end:.3f} s of the clip")]
                    + list(row.notes)))
                table.setItem(index, column, item)
        self._timing_move_all.setEnabled(any(row.movable for row in rows))
        self._timing_move.setEnabled(False)
        if rows:
            table.selectRow(0)
        else:
            self._timing_plot.show_retime(None)

    def _selected_timing_rows(self) -> List[carry_timing.Retime]:
        indexes = sorted({index.row() for index in self._timing_table.selectedIndexes()})
        return [self._timing_rows[i] for i in indexes if i < len(self._timing_rows)]

    def _on_timing_selection(self) -> None:
        chosen = self._selected_timing_rows()
        self._timing_plot.show_retime(chosen[0] if chosen else None)
        self._timing_move.setEnabled(any(row.movable for row in chosen))

    # ── moving ──────────────────────────────────────────────────────

    def _move_timing(self, *, selected_only: bool) -> None:
        from .editing import EditError, OP_RETIME_EVENTS, OperationScope

        rows = self._selected_timing_rows() if selected_only else list(self._timing_rows)
        rows = [row for row in rows if row.movable]
        part = self._timing_part()
        if not rows or self._edits is None or self._session is None:
            return
        if self._timing_signature != self._timing_current_signature():
            self._timing_status.setText(translate_active_ui_text(
                "The character, slot or your changes moved on since this was measured. "
                "Measure again first."))
            return
        moves = dict(self._timing_moves.get(part, {}))
        for row in rows:
            moves[row.event.key] = row.proposed
        previous = self._timing_ops.get(part, "")
        scope = OperationScope(kind=OP_RETIME_EVENTS, model=self._session.model,
                               allowed_chart_events=tuple(sorted(moves)))
        label = translate_active_ui_text(f"Draw and put-away timing: {part}")
        try:
            # Moving more hand-offs later replaces this slot's earlier timing change, so one
            # event is never set by two changes; on a failure the earlier one stays.
            with self._edits.keep_on_failure():
                if previous and any(op.operation_id == previous for op in self._edits.operations()):
                    self._edits.discard_operation(previous)
                with self._edits.begin_operation(scope, label=label) as handle:
                    for key, seconds in sorted(moves.items()):
                        chart, animation, event = carry_timing.parse_event_key(key)
                        handle.retime_event(chart, animation, event, seconds)
        except (EditError, carry_timing.TimingError) as exc:
            QMessageBox.warning(self, translate_active_ui_text("Draw and put-away timing"), str(exc))
            return
        operation = self._edits.latest_operation()
        if operation is not None:
            self._timing_ops[part] = operation.operation_id
            self._timing_moves[part] = moves
        moved = {row.event.key for row in rows}
        updated = [carry_timing.decide(replace(row.event, begin=row.proposed), row.curve)
                   if row.event.key in moved else row for row in self._timing_rows]
        self._after_edit()
        self._timing_signature = self._timing_current_signature()
        self._show_timing_rows(updated)
        self._timing_status.setText(translate_active_ui_text(
            f"Moved {len(rows)} hand-off(s). They are in Your mod; save them there."))


def _measure(source, model, part_name, weapon_path, charts, files, entries, cancelled, progress):
    """Worker side: a private session, the clips with every pending change, and the survey."""

    from .clips import read_clip
    from .playback import load_clip
    from .resolver import PlacementResolver
    from .session import PlacementSession

    resolver = PlacementResolver()
    resolver.add_files(dict(files))
    session = PlacementSession(model, source._bind_hierarchy or source.hierarchy, resolver,
                               skeleton_path=source.skeleton_path)
    # Child sockets come from the selected weapon's file, with its pending changes.
    candidates = list(session.weapons()) + list(resolver.weapons(model=model))
    weapon = next((w for w in candidates if w.game_path == weapon_path), source.weapon)
    if weapon is not None:
        session.select_weapon(weapon)
    part = session.descriptor_part(part_name)
    if part is None:
        raise carry_timing.TimingError(f"{part_name} has no descriptor row on this character")
    lowered = {path.lower(): data for path, data in files.items() if path.lower().endswith(".paa")}

    def read(path: str):
        key = path.lower()
        data = lowered.get(key)
        if data is None:
            entry = entries.get(key)
            if entry is None:
                return None
            data = read_clip(entry)
        return load_clip(data, path.rsplit("/", 1)[-1])

    def measure(path, clip, _part):
        return carry_timing.gap_curve(session, clip, part, clip_path=path)

    return carry_timing.survey(charts, (part_name,), read_clip=read, measure=measure,
                               cancelled=cancelled, progress=progress)

