"""Action Chart Editor: retarget clips and change timing values in a `.paac` chart.

The dialog only collects edits and shows results. Applying them runs
`apply_action_chart_edits` on a worker thread, and the tables are then rebuilt
from the edited bytes, so every value on screen is one the new chart holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.action_chart_edit_service import (
    ActionChartChanges,
    ActionChartEditResult,
    ChartValueRow,
    animation_value_rows,
    apply_action_chart_edits,
    chart_rate_row,
    clip_rows,
    load_editable_chart,
    request_from_pending,
    unknown_clips,
)
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.workers.utility_workers import UtilityTaskOutcome, UtilityWorker

_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True, slots=True)
class ActionChartEditorResult:
    data: bytes
    changes: ActionChartChanges


def _number(value: float) -> str:
    return f"{value:.6g}"


def _value_label_item(row: ChartValueRow) -> QTableWidgetItem:
    """The label for one editable value. Each text is its own literal so it can be translated."""

    number = row.item + 1
    kind = row.event_kind or "?"
    field = row.field
    if field == "animation.start_time":
        return QTableWidgetItem("Clip start (s)")
    if field == "animation.end_time":
        return QTableWidgetItem("Clip end (s)")
    if field == "speed.start_time":
        return QTableWidgetItem(f"Speed window {number} start (s)")
    if field == "speed.end_time":
        return QTableWidgetItem(f"Speed window {number} end (s)")
    if field == "speed.rate":
        return QTableWidgetItem(f"Speed window {number} rate")
    if field == "frame_tag.start_time":
        return QTableWidgetItem(f"Frame tag {number} start (s)")
    if field == "frame_tag.end_time":
        return QTableWidgetItem(f"Frame tag {number} end (s)")
    if field == "just_time.start_time":
        return QTableWidgetItem(f"Just-time window {number} start (s)")
    if field == "just_time.end_time":
        return QTableWidgetItem(f"Just-time window {number} end (s)")
    if field == "event.begin":
        return QTableWidgetItem(f"Frame event {number} ({kind}) begins (s)")
    if field == "event.end":
        return QTableWidgetItem(f"Frame event {number} ({kind}) ends (s, -1 = instant)")
    return QTableWidgetItem(field)


class ActionChartEditorDialog(QDialog):
    """Edit one action chart; `result_payload` holds the edited bytes after Export."""

    def __init__(
        self,
        data: bytes,
        *,
        virtual_path: str,
        known_clips: Sequence[str] = (),
        title: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._path = virtual_path
        self._original = bytes(data)
        self._original_chart = load_editable_chart(self._original, virtual_path)
        self._data = self._original
        self._chart = self._original_chart
        self._changes = ActionChartChanges()
        self._known_clips = tuple(known_clips)
        self._pending_clips: dict[str, str] = {}
        self._pending_values: dict[tuple[str, int, int], float] = {}
        self._rows: dict[tuple[str, int, int], ChartValueRow] = {}
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._filling = False
        self.result_payload: Optional[ActionChartEditorResult] = None

        self.setWindowTitle(title or "Action Chart Editor")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        self.header_label = QLabel()
        self.header_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.header_label)
        warning = QLabel(
            "Action chart editing is new and has not been confirmed in game. Your game files are not changed: "
            "the edited chart is written into a DMM mod folder that you enable in DMM."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Chart speed rate (ActionSpeedRate):"))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setDecimals(4)
        self.rate_spin.setRange(0.0001, 100.0)
        self.rate_spin.setSingleStep(0.05)
        self.rate_spin.setToolTip("Scales the playback speed of every animation in this chart.")
        self.rate_spin.valueChanged.connect(self._rate_changed)
        rate_row.addWidget(self.rate_spin)
        rate_row.addStretch(1)
        layout.addLayout(rate_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_clips_tab(), "Clips")
        self.tabs.addTab(self._build_timing_tab(), "Timing")
        layout.addWidget(self.tabs, 1)

        layout.addWidget(QLabel("Changes from the shipped chart, read back from the edited chart:"))
        self.changes_view = QPlainTextEdit()
        self.changes_view.setReadOnly(True)
        self.changes_view.setMaximumHeight(140)
        layout.addWidget(self.changes_view)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Apply and Re-read")
        self.apply_button.setToolTip("Write the pending edits into a copy of the chart and read that copy back.")
        self.apply_button.clicked.connect(self._apply)
        self.reset_button = QPushButton("Reset to Shipped")
        self.reset_button.clicked.connect(self._reset)
        self.export_button = QPushButton("Export DMM Mod...")
        self.export_button.setToolTip("Write the edited chart into a loose DMM mod folder.")
        self.export_button.clicked.connect(self._export)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._refresh_all()

    # --- construction -----------------------------------------------------------------

    def _build_clips_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "A retarget changes every animation that plays the clip. Clip paths are relative to character/motion/. "
            "Each animation also stores its start and end time; if the new clip is longer or shorter, "
            "adjust them on the Timing tab."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.clip_filter_edit = QLineEdit()
        self.clip_filter_edit.setPlaceholderText("Filter clips...")
        self.clip_filter_edit.textChanged.connect(self._filter_clips)
        layout.addWidget(self.clip_filter_edit)
        self.clip_table = QTableWidget(0, 3)
        self.clip_table.setHorizontalHeaderLabels(["Clip", "Animations", "New clip"])
        self.clip_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.clip_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clip_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.clip_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.clip_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.clip_table.verticalHeader().setVisible(False)
        self.clip_table.itemSelectionChanged.connect(self._clip_selected)
        layout.addWidget(self.clip_table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("New clip:"))
        self.new_clip_edit = QLineEdit()
        self.new_clip_edit.setPlaceholderText("1_pc/1_phm/cd_phm_....paa")
        if self._known_clips:
            completer = QCompleter(list(self._known_clips), self.new_clip_edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setMaxVisibleItems(15)
            self.new_clip_edit.setCompleter(completer)
        row.addWidget(self.new_clip_edit, 1)
        self.retarget_button = QPushButton("Retarget Clip")
        self.retarget_button.clicked.connect(self._retarget_selected)
        self.undo_retarget_button = QPushButton("Undo Retarget")
        self.undo_retarget_button.clicked.connect(self._undo_retarget_selected)
        row.addWidget(self.retarget_button)
        row.addWidget(self.undo_retarget_button)
        layout.addLayout(row)
        return page

    def _build_timing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.animation_filter_edit = QLineEdit()
        self.animation_filter_edit.setPlaceholderText("Filter animations by clip...")
        self.animation_filter_edit.textChanged.connect(self._filter_animations)
        layout.addWidget(self.animation_filter_edit)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.animation_table = QTableWidget(0, 5)
        self.animation_table.setHorizontalHeaderLabels(["#", "Clip", "Start (s)", "End (s)", "Events"])
        self.animation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.animation_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.animation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.animation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.animation_table.verticalHeader().setVisible(False)
        self.animation_table.itemSelectionChanged.connect(self._fill_values)
        splitter.addWidget(self.animation_table)
        self.value_table = QTableWidget(0, 3)
        self.value_table.setHorizontalHeaderLabels(["Value", "Current", "New"])
        self.value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.value_table.verticalHeader().setVisible(False)
        self.value_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.value_table.itemChanged.connect(self._value_edited)
        splitter.addWidget(self.value_table)
        splitter.setSizes([600, 480])
        layout.addWidget(splitter, 1)
        return page

    # --- filling ----------------------------------------------------------------------

    def _refresh_all(self) -> None:
        chart = self._chart
        self.header_label.setText(
            f"{self._path}\n{len(chart.animations):,} animations, {len(chart.tables[1].raw):,} clips"
        )
        self._filling = True
        try:
            self.rate_spin.setValue(self._pending_values.get(chart_rate_row(chart).key, chart.action_speed_rate))
        finally:
            self._filling = False
        self._fill_clips()
        self._fill_animations()
        self._fill_values()
        self._show_changes()
        self._sync_buttons()

    def _fill_clips(self) -> None:
        selected = self._selected_clip()
        bold = QFont()
        bold.setBold(True)
        rows = clip_rows(self._chart)
        self.clip_table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            clip_item = QTableWidgetItem(row.clip)
            clip_item.setData(_KEY_ROLE, row.clip)
            uses_item = QTableWidgetItem(str(row.uses))
            uses_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            new_item = QTableWidgetItem(self._pending_clips.get(row.clip, ""))
            new_item.setFont(bold)
            self.clip_table.setItem(position, 0, clip_item)
            self.clip_table.setItem(position, 1, uses_item)
            self.clip_table.setItem(position, 2, new_item)
            if row.clip == selected:
                self.clip_table.selectRow(position)
        self._filter_clips(self.clip_filter_edit.text())

    def _fill_animations(self) -> None:
        current = self._selected_animation()
        chart = self._chart
        self.animation_table.setRowCount(len(chart.animations))
        for position, animation in enumerate(chart.animations):
            index_item = QTableWidgetItem(str(animation.index))
            index_item.setData(_KEY_ROLE, animation.index)
            cells = (
                index_item,
                QTableWidgetItem(chart.clip_name(animation)),
                QTableWidgetItem(_number(animation.start_time)),
                QTableWidgetItem(_number(animation.end_time)),
                QTableWidgetItem(str(len(animation.events))),
            )
            for column, item in enumerate(cells):
                self.animation_table.setItem(position, column, item)
        self._filter_animations(self.animation_filter_edit.text())
        if chart.animations:
            self.animation_table.selectRow(current if current is not None and current < len(chart.animations) else 0)

    def _fill_values(self) -> None:
        index = self._selected_animation()
        self._filling = True
        try:
            self.value_table.setRowCount(0)
            if index is None:
                return
            rows = animation_value_rows(self._chart, self._data, index)
            self._rows.update({row.key: row for row in rows})
            bold = QFont()
            bold.setBold(True)
            self.value_table.setRowCount(len(rows))
            for position, row in enumerate(rows):
                label = _value_label_item(row)
                label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
                label.setData(_KEY_ROLE, row.key)
                current = QTableWidgetItem(_number(row.value))
                current.setFlags(current.flags() & ~Qt.ItemFlag.ItemIsEditable)
                pending = self._pending_values.get(row.key)
                new = QTableWidgetItem("" if pending is None else _number(pending))
                new.setFont(bold)
                self.value_table.setItem(position, 0, label)
                self.value_table.setItem(position, 1, current)
                self.value_table.setItem(position, 2, new)
        finally:
            self._filling = False

    def _show_changes(self) -> None:
        view = self.changes_view
        view.clear()
        for change in self._changes.clips:
            view.appendPlainText(f"Clip {change.old} -> {change.new}")
        for change in self._changes.values:
            row = change.row
            old, new = _number(change.old), _number(row.value)
            if row.animation < 0:
                view.appendPlainText(f"Chart speed rate: {old} -> {new}")
            else:
                label = translate_active_ui_text(_value_label_item(row).text())
                view.appendPlainText(f"Animation {row.animation}, {label}: {old} -> {new}")
        if self._changes.empty:
            view.appendPlainText("No changes yet.")

    # --- selection and filters --------------------------------------------------------

    def _selected_clip(self) -> Optional[str]:
        rows = self.clip_table.selectionModel().selectedRows() if self.clip_table.selectionModel() else []
        if not rows:
            return None
        item = self.clip_table.item(rows[0].row(), 0)
        return None if item is None else str(item.data(_KEY_ROLE))

    def _selected_animation(self) -> Optional[int]:
        rows = self.animation_table.selectionModel().selectedRows() if self.animation_table.selectionModel() else []
        if not rows:
            return None
        item = self.animation_table.item(rows[0].row(), 0)
        return None if item is None else int(item.data(_KEY_ROLE))

    def _filter_clips(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for position in range(self.clip_table.rowCount()):
            item = self.clip_table.item(position, 0)
            self.clip_table.setRowHidden(position, bool(needle) and needle not in item.text().lower())

    def _filter_animations(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for position in range(self.animation_table.rowCount()):
            item = self.animation_table.item(position, 1)
            self.animation_table.setRowHidden(position, bool(needle) and needle not in item.text().lower())

    def _clip_selected(self) -> None:
        clip = self._selected_clip()
        if clip is not None:
            self.new_clip_edit.setText(self._pending_clips.get(clip, clip))

    # --- pending edits ----------------------------------------------------------------

    def _retarget_selected(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            self._set_status("Select a clip to retarget.", error=True)
            return
        new = self.new_clip_edit.text().strip().replace("\\", "/")
        if not new:
            self._set_status("Enter the clip to play instead.", error=True)
            return
        if new == clip:
            self._pending_clips.pop(clip, None)
        else:
            self._pending_clips[clip] = new
        self._fill_clips()
        self._set_status(f"{len(self._pending_clips) + len(self._pending_values)} pending edit(s). Apply them to re-read the chart.")
        self._sync_buttons()

    def _undo_retarget_selected(self) -> None:
        clip = self._selected_clip()
        if clip is not None and self._pending_clips.pop(clip, None) is not None:
            self.new_clip_edit.setText(clip)
            self._fill_clips()
            self._sync_buttons()

    def _rate_changed(self, value: float) -> None:
        if self._filling:
            return
        row = chart_rate_row(self._chart)
        if abs(value - row.value) < 0.00005:
            self._pending_values.pop(row.key, None)
        else:
            self._pending_values[row.key] = float(value)
        self._sync_buttons()

    def _value_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 2:
            return
        label = self.value_table.item(item.row(), 0)
        if label is None:
            return
        key = tuple(label.data(_KEY_ROLE))
        text = item.text().strip()
        self._filling = True
        try:
            if not text:
                self._pending_values.pop(key, None)
                return
            try:
                value = float(text)
            except ValueError:
                pending = self._pending_values.get(key)
                item.setText("" if pending is None else _number(pending))
                self._set_status(f"{text} is not a number.", error=True)
                return
            row = self._rows.get(key)
            if row is not None and value == row.value:
                self._pending_values.pop(key, None)
                item.setText("")
            else:
                self._pending_values[key] = value
        finally:
            self._filling = False
            self._sync_buttons()

    def _sync_buttons(self) -> None:
        busy = self._thread is not None
        pending = bool(self._pending_clips or self._pending_values)
        self.apply_button.setEnabled(not busy and pending)
        self.reset_button.setEnabled(not busy and (pending or self._data != self._original))
        self.export_button.setEnabled(not busy and not pending and not self._changes.empty)
        self.close_button.setEnabled(not busy)
        if pending:
            self.export_button.setToolTip("Apply the pending edits first.")
        else:
            self.export_button.setToolTip("Write the edited chart into a loose DMM mod folder.")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setStyleSheet("color: #d9534f;" if error else "")
        self.status_label.setText(text)

    # --- apply, reset, export ---------------------------------------------------------

    def _apply(self) -> None:
        request = request_from_pending(self._pending_clips, self._pending_values)
        if request.empty:
            self._set_status("There are no pending edits.")
            return
        missing = unknown_clips(request, self._known_clips) if self._known_clips else ()
        if missing:
            answer = QMessageBox.question(
                self,
                "Clip Not Found",
                "These clips are not in the game's archives:\n\n" + "\n".join(missing)
                + "\n\nThe game cannot play a clip that does not exist. Apply anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        data, original, path = self._data, self._original, self._path
        self._set_status("Writing the edits and reading the chart back...")
        self._start_task(lambda _log: apply_action_chart_edits(data, request, virtual_path=path, original=original))

    def _start_task(self, task: Callable[..., object]) -> None:
        worker = UtilityWorker(task)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.outcome.connect(self._handle_outcome)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._task_finished)
        self._worker, self._thread = worker, thread
        self._sync_buttons()
        thread.start()

    def _task_finished(self) -> None:
        self._worker = None
        self._thread = None
        self._sync_buttons()

    def _handle_outcome(self, outcome: UtilityTaskOutcome) -> None:
        if outcome.kind != "completed" or not isinstance(outcome.value, ActionChartEditResult):
            self._set_status(f"The edit was refused: {outcome.message}", error=True)
            return
        result = outcome.value
        self._data = result.data
        self._chart = result.chart
        self._changes = result.changes
        self._pending_clips.clear()
        self._pending_values.clear()
        self._rows.clear()
        self._refresh_all()
        self._set_status(
            f"Applied. The chart was read back: {len(result.changes.clips)} clip retarget(s) and "
            f"{len(result.changes.values)} value change(s) from the shipped chart."
        )

    def _reset(self) -> None:
        self._data = self._original
        self._chart = self._original_chart
        self._changes = ActionChartChanges()
        self._pending_clips.clear()
        self._pending_values.clear()
        self._rows.clear()
        self._refresh_all()
        self._set_status("Back to the shipped chart.")

    def _export(self) -> None:
        if self._changes.empty or self._pending_clips or self._pending_values:
            return
        self.result_payload = ActionChartEditorResult(self._data, self._changes)
        self.accept()

    def busy(self) -> bool:
        return self._thread is not None

    def reject(self) -> None:
        if self.busy():
            self._set_status("Wait for the edit to finish.")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.busy():
            event.ignore()
            self._set_status("Wait for the edit to finish.")
            return
        super().closeEvent(event)


__all__ = ["ActionChartEditorDialog", "ActionChartEditorResult"]
