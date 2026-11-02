"""Action Chart Editor: change what a `.paac` chart plays, names and times.

The dialog only collects edits and shows results. Applying them runs
`apply_action_chart_edits` on a worker thread, and every table is then rebuilt
from the edited bytes, so each value on screen is one the new chart holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QStringListModel, QThread, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pathlib import PurePosixPath

from cdmw.core.action_chart_binary import ANIMATION_TABLE, BLEND_TABLE, ActionChartError, ChartValueEdit
from cdmw.services.action_chart_edit_service import (
    ActionChartChanges,
    ActionChartEditRequest,
    ActionChartEditResult,
    AnimationResourceEdit,
    ClipInfo,
    ClipUse,
    LinkedClipChange,
    ChartValueRow,
    EventFieldEdit,
    EventRow,
    StringRetarget,
    TableCatalog,
    animation_event_rows,
    animation_value_rows,
    apply_action_chart_edits,
    build_resource_catalog,
    chart_rate_row,
    event_field_table,
    load_editable_chart,
    string_rows,
    unknown_resources,
)
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.workers.utility_workers import UtilityTaskOutcome, UtilityWorker

_KEY_ROLE = Qt.ItemDataRole.UserRole + 1
_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
_MODE_FIELD = "mode"
_BLEND_TIME_FIELD = "blend time"
#: Pending-list item tags; integers so they are never mistaken for interface text.
_RETARGET, _RESOURCE, _EVENT, _VALUE, _LINKED = range(5)
_RESOURCE_FIELDS = ("clip", "blend")


@dataclass(frozen=True, slots=True)
class _Refused:
    message: str


@dataclass(frozen=True, slots=True)
class ActionChartEditorResult:
    data: bytes
    changes: ActionChartChanges
    linked: tuple[LinkedClipChange, ...] = ()


def _number(value: float) -> str:
    return f"{value:.6g}"


def _file_name(path: str) -> str:
    return PurePosixPath(str(path or "").replace("\\", "/")).name


def _path_item(path: str) -> QTableWidgetItem:
    """A cell showing a path's file name, with the whole path as its tooltip and data."""

    item = QTableWidgetItem(_file_name(path))
    item.setToolTip(path)
    item.setData(_PATH_ROLE, path)
    return item


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


def _field_label(field: str) -> QLabel:
    """The label for one event field. Each text is its own literal so it can be translated."""

    if field == "part":
        return QLabel("Equipment part:")
    if field == "parent socket":
        return QLabel("Parent socket:")
    if field == "child socket":
        return QLabel("Child socket:")
    if field == "effect":
        return QLabel("Effect:")
    if field == "bone":
        return QLabel("Bone:")
    if field == "prefab":
        return QLabel("Prefab:")
    if field == "sequencer":
        return QLabel("Sequencer:")
    if field == _MODE_FIELD:
        return QLabel("Socket mode:")
    if field == _BLEND_TIME_FIELD:
        return QLabel("Blend time (s):")
    return QLabel(field)


def _field_text(field: str) -> str:
    return translate_active_ui_text(_field_label(field).text()).rstrip(":")


class ActionChartEditorDialog(QDialog):
    """Edit one action chart; `result_payload` holds the edited bytes after Export."""

    def __init__(
        self,
        data: bytes,
        *,
        virtual_path: str,
        catalogs: Optional[Mapping[int, TableCatalog]] = None,
        used_by: Sequence[str] = (),
        export_details: Optional[Callable[[ActionChartEditorResult], object]] = None,
        export_writer: Optional[Callable[[ActionChartEditorResult, object, Callable[[str], None]], object]] = None,
        export_done: Optional[Callable[[object, object], None]] = None,
        edited: Optional[bytes] = None,
        edited_changes: Optional[ActionChartChanges] = None,
        clip_info: Optional[Callable[[str], ClipInfo]] = None,
        show_in_browser: Optional[Callable[[str], None]] = None,
        clip_uses: Optional[Mapping[str, Sequence[ClipUse]]] = None,
        chart_users_of: Optional[Callable[[str], Sequence[str]]] = None,
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
        if edited is not None and bytes(edited) != self._original:
            # Continuing a mod CDMW wrote: the edited copy is the working chart, and its
            # changes were worked out against the shipped chart before the dialog opened.
            self._data = bytes(edited)
            self._chart = load_editable_chart(self._data, virtual_path)
            self._changes = edited_changes or ActionChartChanges()
        self._clip_info = clip_info
        self._show_in_browser = show_in_browser
        self._clip_uses = clip_uses
        self._chart_users_of = chart_users_of
        #: Clip changes for other charts of the same mod: (chart, old clip) -> new clip.
        #: They are applied at export, so Apply and Re-read leaves them pending.
        self._linked: dict[tuple[str, str], str] = {}
        self._on_task_done: Optional[Callable[[UtilityTaskOutcome], None]] = None
        self._catalogs: dict[int, TableCatalog] = dict(catalogs) if catalogs else build_resource_catalog(self._chart, {})
        self._used_by = tuple(used_by)
        self._pending_retargets: dict[tuple[int, str], str] = {}
        self._pending_resources: dict[int, dict[str, str]] = {}
        self._pending_events: dict[tuple[int, int, str], tuple[object, bool]] = {}
        self._pending_values: dict[tuple[str, int, int], float] = {}
        self._rows: dict[tuple[str, int, int], ChartValueRow] = {}
        self._event_rows: tuple[EventRow, ...] = ()
        self._event_widgets: dict[str, QWidget] = {}
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._filling = False
        self.result_payload: Optional[ActionChartEditorResult] = None
        #: Asked on Export, before the editor closes; returning None keeps the editor open.
        self._export_details = export_details
        #: Writes the mod on the editor's worker; the editor stays open until it succeeds,
        #: so a refused or failed export keeps every edit.
        self._export_writer = export_writer
        self._export_done = export_done
        self.export_plan: object = None

        self.setWindowTitle(title or "Action Chart Editor")
        self._fit_to_screen()
        layout = QVBoxLayout(self)
        self.header_label = QLabel()
        self.header_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.header_label.setWordWrap(True)
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
        self.tabs.addTab(self._build_animations_tab(), "Animations")
        self.tabs.addTab(self._build_strings_tab(), "Names and Paths")
        self.review_splitter = QSplitter(Qt.Orientation.Vertical)
        self.review_splitter.addWidget(self.tabs)
        self.review_panel = self._build_review_panel()
        self.review_splitter.addWidget(self.review_panel)
        self.review_splitter.setCollapsible(0, False)
        self.review_splitter.setStretchFactor(0, 1)
        self.review_splitter.setStretchFactor(1, 0)
        # Collapsed until there is a pending edit or a change to show.
        self.review_splitter.setSizes([1, 0])
        layout.addWidget(self.review_splitter, 1)

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

    def _completer(self, table: int, owner: QWidget) -> QCompleter:
        catalog = self._catalogs.get(table)
        completer = QCompleter(list(catalog.suggestions) if catalog else [], owner)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(15)
        return completer

    def _build_animations_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.animation_filter_edit = QLineEdit()
        self.animation_filter_edit.setPlaceholderText("Filter animations by clip or blend space...")
        self.animation_filter_edit.textChanged.connect(self._filter_animations)
        layout.addWidget(self.animation_filter_edit)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.animation_table = QTableWidget(0, 6)
        self.animation_table.setHorizontalHeaderLabels(["#", "Clip", "Blend space", "Start (s)", "End (s)", "Events"])
        self.animation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.animation_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.animation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.animation_table.setWordWrap(False)
        self.animation_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        header = self.animation_table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 52), (2, 150), (3, 64), (4, 64), (5, 54)):
            self.animation_table.setColumnWidth(column, width)
        self.animation_table.setToolTip("Hover a clip or blend space to see its whole path.")
        self.animation_table.verticalHeader().setVisible(False)
        self.animation_table.itemSelectionChanged.connect(self._animation_selected)
        splitter.addWidget(self.animation_table)

        # The detail column is a splitter of panes that keep their minimum height; when
        # the window is short it scrolls instead of squashing the event editors.
        self.detail_splitter = QSplitter(Qt.Orientation.Vertical)
        self.detail_splitter.setChildrenCollapsible(False)

        resources = QGroupBox("Clip and blend space")
        grid = QGridLayout(resources)
        grid.addWidget(QLabel("Clip:"), 0, 0)
        self.clip_edit = QLineEdit()
        self.clip_edit.setPlaceholderText("1_pc/1_phm/cd_phm_....paa")
        self.clip_edit.setCompleter(self._completer(ANIMATION_TABLE, self.clip_edit))
        grid.addWidget(self.clip_edit, 0, 1)
        grid.addWidget(QLabel("Blend space:"), 1, 0)
        self.blend_edit = QLineEdit()
        self.blend_edit.setPlaceholderText("Empty: no blend space")
        self.blend_edit.setCompleter(self._completer(BLEND_TABLE, self.blend_edit))
        grid.addWidget(self.blend_edit, 1, 1)
        resource_buttons = QHBoxLayout()
        self.clip_length_button = QPushButton("Use Clip Length")
        self.clip_length_button.setToolTip("Read the clip in the Clip field and set this animation's Clip end to its length.")
        self.clip_length_button.clicked.connect(self._use_clip_length)
        self.clip_length_button.setVisible(self._clip_info is not None)
        self.show_clip_button = QPushButton("Show in Archive Browser")
        self.show_clip_button.setToolTip("Find the clip in the Archive Browser so you can preview it.")
        self.show_clip_button.clicked.connect(self._show_clip)
        self.show_clip_button.setVisible(self._show_in_browser is not None)
        self.set_resources_button = QPushButton("Set for This Animation")
        self.set_resources_button.setToolTip(
            "Only this animation changes; other animations that play the same clip keep it."
        )
        self.set_resources_button.clicked.connect(self._set_resources)
        self.undo_resources_button = QPushButton("Undo")
        self.undo_resources_button.clicked.connect(self._undo_resources)
        resource_buttons.addWidget(self.set_resources_button)
        resource_buttons.addWidget(self.undo_resources_button)
        resource_buttons.addStretch(1)
        grid.addLayout(resource_buttons, 2, 1)
        clip_buttons = QHBoxLayout()
        clip_buttons.addWidget(self.clip_length_button)
        clip_buttons.addWidget(self.show_clip_button)
        self.other_charts_button = QPushButton("Other Charts Playing This Clip...")
        self.other_charts_button.setToolTip(
            "Change this clip in other charts too. The game may play it from another chart than this one."
        )
        self.other_charts_button.clicked.connect(self._open_other_charts)
        self.other_charts_button.setVisible(self._clip_uses is not None)
        clip_buttons.addWidget(self.other_charts_button)
        clip_buttons.addStretch(1)
        grid.addLayout(clip_buttons, 3, 1)
        self.clip_info_label = QLabel()
        self.clip_info_label.setWordWrap(True)
        grid.addWidget(self.clip_info_label, 4, 1)
        resource_hint = QLabel(
            "Clip paths are relative to character/motion/. If the new clip is longer or shorter, "
            "change Clip start and Clip end under Timing."
        )
        resource_hint.setWordWrap(True)
        grid.addWidget(resource_hint, 5, 0, 1, 2)
        self.detail_splitter.addWidget(resources)

        timing = QGroupBox("Timing")
        timing_layout = QVBoxLayout(timing)
        self.value_table = QTableWidget(0, 3)
        self.value_table.setHorizontalHeaderLabels(["Value", "Current", "New"])
        self.value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.value_table.verticalHeader().setVisible(False)
        self.value_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.value_table.setToolTip("Type a new value in the New column. Clear the cell to drop the edit.")
        self.value_table.itemChanged.connect(self._value_edited)
        self.value_table.setMinimumHeight(140)
        timing_layout.addWidget(self.value_table)
        timing_hint = QLabel(
            "Some moves, such as dodges and rolls, may play from the character's lower-body chart "
            "(for Kliff, basic_lower). If a timing change does not show in game, check that chart too."
        )
        timing_hint.setWordWrap(True)
        timing_layout.addWidget(timing_hint)
        self.detail_splitter.addWidget(timing)

        events = QGroupBox("Frame events")
        events_layout = QVBoxLayout(events)
        self.event_table = QTableWidget(0, 5)
        self.event_table.setHorizontalHeaderLabels(["#", "Event", "Begins (s)", "Shared by", "Names"])
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.event_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.event_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.event_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.event_table.verticalHeader().setVisible(False)
        self.event_table.itemSelectionChanged.connect(self._event_selected)
        self.event_table.setMinimumHeight(120)
        events_layout.addWidget(self.event_table, 1)
        self.detail_splitter.addWidget(events)

        selected = QGroupBox("Selected event")
        selected_layout = QVBoxLayout(selected)
        events_layout = selected_layout
        self.event_form_host = QWidget()
        self.event_form = QFormLayout(self.event_form_host)
        self.event_form.setContentsMargins(0, 0, 0, 0)
        events_layout.addWidget(self.event_form_host)
        self.event_note = QLabel()
        self.event_note.setWordWrap(True)
        events_layout.addWidget(self.event_note)
        scope_row = QHBoxLayout()
        self.only_this_radio = QRadioButton("Only this animation")
        self.only_this_radio.setToolTip("A shared event is copied, so the other animations keep the old one.")
        self.every_user_radio = QRadioButton("Every animation using this event")
        self.only_this_radio.setChecked(True)
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self.only_this_radio)
        self._scope_group.addButton(self.every_user_radio)
        scope_row.addWidget(self.only_this_radio)
        scope_row.addWidget(self.every_user_radio)
        scope_row.addStretch(1)
        events_layout.addLayout(scope_row)
        event_buttons = QHBoxLayout()
        self.set_event_button = QPushButton("Set Event Fields")
        self.set_event_button.clicked.connect(self._set_event_fields)
        self.undo_event_button = QPushButton("Undo Event Edits")
        self.undo_event_button.clicked.connect(self._undo_event_fields)
        event_buttons.addWidget(self.set_event_button)
        event_buttons.addWidget(self.undo_event_button)
        event_buttons.addStretch(1)
        events_layout.addLayout(event_buttons)
        self.detail_splitter.addWidget(selected)
        self.detail_splitter.setStretchFactor(1, 2)
        self.detail_splitter.setStretchFactor(2, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.detail_splitter)
        splitter.addWidget(scroll)
        splitter.setSizes([600, 680])
        layout.addWidget(splitter, 1)
        return page

    def _build_strings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Replacing an entry changes everything in this chart that names it: every animation that plays a clip, "
            "every event that uses a socket or effect. To change one animation or one event, use the Animations tab."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("Table:"))
        self.table_combo = QComboBox()
        self.table_combo.addItems([
            "Names (sub-charts and groups)",
            "Clips",
            "Camera clips",
            "Effects",
            "Effect switches",
            "Blend spaces",
            "Bones and sockets",
            "Equipment parts",
            "Sequencers",
            "Prefabs",
        ])
        self.table_combo.setCurrentIndex(ANIMATION_TABLE)
        self.table_combo.currentIndexChanged.connect(self._table_changed)
        row.addWidget(self.table_combo, 1)
        self.string_filter_edit = QLineEdit()
        self.string_filter_edit.setPlaceholderText("Filter entries...")
        self.string_filter_edit.textChanged.connect(self._filter_strings)
        row.addWidget(self.string_filter_edit, 2)
        layout.addLayout(row)
        self.string_table = QTableWidget(0, 4)
        self.string_table.setHorizontalHeaderLabels(["#", "Entry", "Uses", "Replace with"])
        self.string_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.string_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.string_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.string_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.string_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.string_table.verticalHeader().setVisible(False)
        self.string_table.itemSelectionChanged.connect(self._string_selected)
        layout.addWidget(self.string_table, 1)
        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Replace with:"))
        self.new_string_edit = QLineEdit()
        self._string_model = QStringListModel(self.new_string_edit)
        completer = QCompleter(self._string_model, self.new_string_edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(15)
        self.new_string_edit.setCompleter(completer)
        replace_row.addWidget(self.new_string_edit, 1)
        self.replace_button = QPushButton("Replace Everywhere")
        self.replace_button.clicked.connect(self._replace_selected)
        self.undo_replace_button = QPushButton("Undo Replace")
        self.undo_replace_button.clicked.connect(self._undo_replace_selected)
        replace_row.addWidget(self.replace_button)
        replace_row.addWidget(self.undo_replace_button)
        layout.addLayout(replace_row)
        return page

    def _build_review_panel(self) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        pending_box = QGroupBox("Pending edits")
        pending_layout = QVBoxLayout(pending_box)
        self.pending_list = QListWidget()
        pending_layout.addWidget(self.pending_list, 1)
        self.remove_pending_button = QPushButton("Remove Selected Edit")
        self.remove_pending_button.clicked.connect(self._remove_pending)
        pending_layout.addWidget(self.remove_pending_button)
        layout.addWidget(pending_box, 1)
        changes_box = QGroupBox("Changes from the shipped chart, read back from the edited chart")
        changes_layout = QVBoxLayout(changes_box)
        self.changes_view = QPlainTextEdit()
        self.changes_view.setReadOnly(True)
        changes_layout.addWidget(self.changes_view)
        layout.addWidget(changes_box, 1)
        return panel

    # --- filling ----------------------------------------------------------------------

    def _fit_to_screen(self) -> None:
        screen = self.screen() if hasattr(self, "screen") else None
        available = screen.availableGeometry() if screen is not None else None
        width, height = 1280, 860
        if available is not None:
            width = min(width, int(available.width() * 0.94))
            height = min(height, int(available.height() * 0.9))
        self.resize(max(width, 640), max(height, 480))

    def _sync_review_panel(self) -> None:
        """Hide the pending and changes lists until either has something in it."""

        wanted = bool(self._pending_count() or not self._changes.empty or self._linked)
        sizes = self.review_splitter.sizes()
        if wanted and sizes[1] == 0:
            total = sum(sizes) if sum(sizes) > 400 else max(self.height() - 200, 600)
            self.review_splitter.setSizes([max(total - 170, 230), 170])
        elif not wanted and sizes[1] != 0:
            self.review_splitter.setSizes([sum(sizes), 0])

    def _refresh_all(self) -> None:
        chart = self._chart
        self.header_label.setText(
            f"{self._path}\n{len(chart.animations):,} animations, {len(chart.tables[1].raw):,} clips"
        )
        if self._used_by:
            self.header_label.setText(
                self.header_label.text() + "\n" + f"Used by: {', '.join(self._used_by)}"
            )
        self._filling = True
        try:
            self.rate_spin.setValue(self._pending_values.get(chart_rate_row(chart).key, chart.action_speed_rate))
        finally:
            self._filling = False
        self._fill_animations()
        self._fill_strings()
        self._fill_pending()
        self._show_changes()
        self._sync_buttons()
        self._sync_review_panel()

    def _fill_animations(self) -> None:
        current = self._selected_animation()
        chart = self._chart
        self.animation_table.setRowCount(len(chart.animations))
        for position, animation in enumerate(chart.animations):
            index_item = QTableWidgetItem(str(animation.index))
            index_item.setData(_KEY_ROLE, animation.index)
            cells = (
                index_item,
                _path_item(chart.clip_name(animation)),
                _path_item(chart.blend_name(animation)),
                QTableWidgetItem(_number(animation.start_time)),
                QTableWidgetItem(_number(animation.end_time)),
                QTableWidgetItem(str(len(animation.events))),
            )
            for column, item in enumerate(cells):
                self.animation_table.setItem(position, column, item)
        self._filter_animations(self.animation_filter_edit.text())
        if chart.animations:
            self.animation_table.selectRow(current if current is not None and current < len(chart.animations) else 0)
        self._animation_selected()

    def _animation_selected(self) -> None:
        index = self._selected_animation()
        self._fill_resources(index)
        self._fill_values(index)
        self._fill_events(index)

    def _fill_resources(self, index: Optional[int]) -> None:
        enabled = index is not None
        for widget in (self.clip_edit, self.blend_edit, self.set_resources_button, self.undo_resources_button):
            widget.setEnabled(enabled)
        if index is None:
            self.clip_edit.clear()
            self.blend_edit.clear()
            return
        animation = self._chart.animations[index]
        pending = self._pending_resources.get(index, {})
        bold = QFont()
        bold.setBold("clip" in pending)
        self.clip_edit.setFont(bold)
        self.clip_edit.setText(pending.get("clip", self._chart.clip_name(animation)))
        bold = QFont()
        bold.setBold("blend" in pending)
        self.blend_edit.setFont(bold)
        self.blend_edit.setText(pending.get("blend", self._chart.blend_name(animation)))
        self._show_other_charts(self._chart.clip_name(animation))

    def _other_charts(self, clip: str) -> tuple[ClipUse, ...]:
        if self._clip_uses is None:
            return ()
        own = self._path.replace("\\", "/").lower()
        return tuple(use for use in self._clip_uses.get(clip.lower(), ()) if use.chart.lower() != own)

    def _show_other_charts(self, clip: str) -> None:
        if self._clip_uses is None:
            return
        others = self._other_charts(clip)
        self.other_charts_button.setEnabled(bool(others) and not self.busy())
        if others:
            self.clip_info_label.setText(
                f"{_file_name(clip)} is also played by {len(others)} other chart(s). "
                "If an edit shows no change in game, the animation may come from one of them."
            )
        else:
            self.clip_info_label.setText(f"No other chart plays {_file_name(clip)}.")

    def _open_other_charts(self) -> None:
        from cdmw.ui.archive_browser.action_chart_link_dialog import ActionChartLinkDialog

        index = self._selected_animation()
        if index is None:
            return
        clip = self._chart.clip_name(self._chart.animations[index])
        others = self._other_charts(clip)
        if not others:
            return
        new_clip = self._clip_field()
        dialog = ActionChartLinkDialog(
            clip, others, new_clip=new_clip if new_clip != clip else "", users_of=self._chart_users_of, parent=self
        )
        if not dialog.exec():
            return
        for chart in dialog.selected_charts:
            self._linked[(chart, clip)] = dialog.new_clip
        self._pending_changed()
        self._show_changes()
        self._set_status(
            f"{len(dialog.selected_charts)} other chart(s) will play {_file_name(dialog.new_clip)} instead "
            "when you export."
        )

    def _fill_values(self, index: Optional[int]) -> None:
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

    def _fill_events(self, index: Optional[int]) -> None:
        self._event_rows = () if index is None else animation_event_rows(self._chart, self._data, index)
        self.event_table.setRowCount(len(self._event_rows))
        for position, row in enumerate(self._event_rows):
            names = ", ".join(f"{name}: {value}" for name, value in row.fields if isinstance(value, str) and value)
            pending = any(key[0] == row.animation and key[1] == row.item for key in self._pending_events)
            cells = (
                QTableWidgetItem(str(row.item + 1)),
                QTableWidgetItem(row.kind_name or "?"),
                QTableWidgetItem(_number(row.begin)),
                QTableWidgetItem(str(len(row.shared_by))),
                QTableWidgetItem(names),
            )
            if pending:
                bold = QFont()
                bold.setBold(True)
                for item in cells:
                    item.setFont(bold)
            for column, item in enumerate(cells):
                self.event_table.setItem(position, column, item)
        if self._event_rows:
            self.event_table.selectRow(0)
        self._event_selected()

    def _selected_event(self) -> Optional[EventRow]:
        rows = self.event_table.selectionModel().selectedRows() if self.event_table.selectionModel() else []
        if not rows or rows[0].row() >= len(self._event_rows):
            return None
        return self._event_rows[rows[0].row()]

    def _event_selected(self) -> None:
        while self.event_form.rowCount():
            self.event_form.removeRow(0)
        self._event_widgets = {}
        row = self._selected_event()
        editable = row is not None and bool(row.fields)
        for widget in (self.set_event_button, self.undo_event_button, self.only_this_radio, self.every_user_radio):
            widget.setEnabled(editable)
        if row is None:
            self.event_note.setText("")
            return
        if not row.fields:
            self.event_note.setText(f"{row.kind_name or '?'} events have no fields CDMW can change yet. "
                                    "Their timing is under Timing.")
            return
        others = len(row.shared_by) - 1
        if others > 0:
            self.event_note.setText(
                f"This event is shared with {others} other animation(s): "
                f"{', '.join(str(item) for item in row.shared_by if item != row.animation)}."
            )
        else:
            self.event_note.setText("Only this animation uses this event.")
        self.every_user_radio.setText(f"Every animation using this event ({len(row.shared_by)})")
        for name, value in row.fields:
            pending = self._pending_events.get((row.animation, row.item, name))
            current = pending[0] if pending is not None else value
            if name == _MODE_FIELD:
                widget = QComboBox()
                widget.addItems(["In", "Out", "Explicit sockets"])
                widget.setCurrentIndex(int(current) if int(current) in (0, 1, 2) else 2)
            elif name == _BLEND_TIME_FIELD:
                widget = QDoubleSpinBox()
                widget.setDecimals(3)
                widget.setRange(0.0, 60.0)
                widget.setSingleStep(0.05)
                widget.setValue(float(current))
            else:
                widget = QComboBox()
                widget.setEditable(True)
                table = event_field_table(name)
                catalog = self._catalogs.get(table) if table is not None else None
                widget.addItem("")
                widget.addItems(list(catalog.suggestions) if catalog else [])
                widget.setCurrentText(str(current))
                widget.lineEdit().setPlaceholderText("Empty: none")
            if pending is not None:
                bold = QFont()
                bold.setBold(True)
                widget.setFont(bold)
            widget.setMinimumHeight(widget.sizeHint().height())
            self._event_widgets[name] = widget
            self.event_form.addRow(_field_label(name), widget)

    def _fill_strings(self) -> None:
        table = self.table_combo.currentIndex()
        rows = string_rows(self._chart, self._data, table)
        selected = self._selected_string()
        bold = QFont()
        bold.setBold(True)
        self.string_table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            index_item = QTableWidgetItem(str(row.index))
            value_item = QTableWidgetItem(row.value)
            value_item.setData(_KEY_ROLE, row.value)
            uses_item = QTableWidgetItem("-" if row.uses is None else str(row.uses))
            uses_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            new_item = QTableWidgetItem(self._pending_retargets.get((table, row.value), ""))
            new_item.setFont(bold)
            for column, item in enumerate((index_item, value_item, uses_item, new_item)):
                self.string_table.setItem(position, column, item)
            if row.value == selected:
                self.string_table.selectRow(position)
        catalog = self._catalogs.get(table)
        self._string_model.setStringList(list(catalog.suggestions) if catalog else [])
        self._filter_strings(self.string_filter_edit.text())

    def _fill_pending(self) -> None:
        self.pending_list.clear()
        for (chart, old), new in self._linked.items():
            item = QListWidgetItem(f"At export, in {_file_name(chart)}: {_file_name(old)} -> {_file_name(new)}")
            item.setToolTip(f"{chart}: {old} -> {new}")
            item.setData(_KEY_ROLE, (_LINKED, (chart, old)))
            self.pending_list.addItem(item)
        for (table, old), new in self._pending_retargets.items():
            item = QListWidgetItem(f"Replace in {self.table_combo.itemText(table)}: {old} -> {new}")
            item.setData(_KEY_ROLE, (_RETARGET, (table, old)))
            self.pending_list.addItem(item)
        for animation, fields in self._pending_resources.items():
            if "clip" in fields:
                item = QListWidgetItem(f"Animation {animation} clip: {fields['clip']}")
                item.setData(_KEY_ROLE, (_RESOURCE, (animation, 0)))
                self.pending_list.addItem(item)
            if "blend" in fields:
                item = QListWidgetItem(f"Animation {animation} blend space: {fields['blend'] or '-'}")
                item.setData(_KEY_ROLE, (_RESOURCE, (animation, 1)))
                self.pending_list.addItem(item)
        for (animation, event, field), (value, only_this) in self._pending_events.items():
            label = _field_text(field)
            if only_this:
                item = QListWidgetItem(f"Animation {animation}, frame event {event + 1}, {label}: {value}")
            else:
                item = QListWidgetItem(f"Every user of frame event {event + 1} of animation {animation}, {label}: {value}")
            item.setData(_KEY_ROLE, (_EVENT, (animation, event, field)))
            self.pending_list.addItem(item)
        for key, value in self._pending_values.items():
            row = self._rows.get(key)
            if key[0] == "chart.action_speed_rate":
                item = QListWidgetItem(f"Chart speed rate: {_number(value)}")
            elif row is not None:
                label = translate_active_ui_text(_value_label_item(row).text())
                item = QListWidgetItem(f"Animation {key[1]}, {label}: {_number(value)}")
            else:
                item = QListWidgetItem(f"Animation {key[1]}, {key[0]}: {_number(value)}")
            item.setData(_KEY_ROLE, (_VALUE, key))
            self.pending_list.addItem(item)

    def _show_changes(self) -> None:
        view = self.changes_view
        view.clear()
        for change in self._changes.strings:
            view.appendPlainText(f"Replaced in {self.table_combo.itemText(change.table)}: {change.old} -> {change.new}")
        for change in self._changes.resources:
            if change.field == "clip":
                view.appendPlainText(f"Animation {change.animation} clip: {change.old} -> {change.new}")
            else:
                view.appendPlainText(f"Animation {change.animation} blend space: {change.old or '-'} -> {change.new or '-'}")
        for change in self._changes.events:
            label = _field_text(change.field)
            view.appendPlainText(
                f"Animation {change.animation}, frame event {change.item + 1} ({change.kind_name}), "
                f"{label}: {change.old} -> {change.new}"
            )
        for change in self._changes.values:
            row = change.row
            old, new = _number(change.old), _number(row.value)
            if row.animation < 0:
                view.appendPlainText(f"Chart speed rate: {old} -> {new}")
            else:
                label = translate_active_ui_text(_value_label_item(row).text())
                view.appendPlainText(f"Animation {row.animation}, {label}: {old} -> {new}")
        for table, value in self._changes.appended:
            view.appendPlainText(f"Added to {self.table_combo.itemText(table)}: {value}")
        for (chart, old), new in self._linked.items():
            view.appendPlainText(f"At export, also in {chart}: {old} -> {new}")
        if self._changes.empty and not self._linked:
            view.appendPlainText("No changes yet.")

    # --- selection and filters --------------------------------------------------------

    def _selected_animation(self) -> Optional[int]:
        rows = self.animation_table.selectionModel().selectedRows() if self.animation_table.selectionModel() else []
        if not rows:
            return None
        item = self.animation_table.item(rows[0].row(), 0)
        return None if item is None else int(item.data(_KEY_ROLE))

    def _selected_string(self) -> Optional[str]:
        rows = self.string_table.selectionModel().selectedRows() if self.string_table.selectionModel() else []
        if not rows:
            return None
        item = self.string_table.item(rows[0].row(), 1)
        return None if item is None else str(item.data(_KEY_ROLE))

    def _filter_animations(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for position in range(self.animation_table.rowCount()):
            clip = self.animation_table.item(position, 1)
            blend = self.animation_table.item(position, 2)
            haystack = " ".join(str(item.data(_PATH_ROLE) or "") for item in (clip, blend) if item is not None).lower()
            self.animation_table.setRowHidden(position, bool(needle) and needle not in haystack)

    def _filter_strings(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for position in range(self.string_table.rowCount()):
            item = self.string_table.item(position, 1)
            self.string_table.setRowHidden(position, bool(needle) and needle not in item.text().lower())

    def _table_changed(self, _index: int) -> None:
        self.new_string_edit.clear()
        self._fill_strings()

    def _string_selected(self) -> None:
        value = self._selected_string()
        if value is not None:
            self.new_string_edit.setText(self._pending_retargets.get((self.table_combo.currentIndex(), value), value))

    # --- pending edits ----------------------------------------------------------------

    def _pending_count(self) -> int:
        return (len(self._pending_retargets) + sum(len(item) for item in self._pending_resources.values())
                + len(self._pending_events) + len(self._pending_values))

    def _pending_changed(self) -> None:
        self._fill_pending()
        self._sync_buttons()
        self._sync_review_panel()
        count = self._pending_count()
        if count:
            self._set_status(f"{count} pending edit(s). Apply them to re-read the chart.")

    def _replace_selected(self) -> None:
        value = self._selected_string()
        if value is None:
            self._set_status("Select an entry to replace.", error=True)
            return
        new = self.new_string_edit.text().strip()
        table = self.table_combo.currentIndex()
        if not new:
            self._set_status("Enter what should replace the entry.", error=True)
            return
        if table == ANIMATION_TABLE:
            new = new.replace("\\", "/")
        if new == value:
            self._pending_retargets.pop((table, value), None)
        else:
            self._pending_retargets[(table, value)] = new
        self._fill_strings()
        self._pending_changed()

    def _undo_replace_selected(self) -> None:
        value = self._selected_string()
        table = self.table_combo.currentIndex()
        if value is not None and self._pending_retargets.pop((table, value), None) is not None:
            self.new_string_edit.setText(value)
            self._fill_strings()
            self._pending_changed()

    def _set_resources(self) -> None:
        index = self._selected_animation()
        if index is None:
            return
        animation = self._chart.animations[index]
        clip = self.clip_edit.text().strip().replace("\\", "/")
        blend = self.blend_edit.text().strip().replace("\\", "/")
        if not clip:
            self._set_status("An animation needs a clip.", error=True)
            return
        fields: dict[str, str] = {}
        if clip != self._chart.clip_name(animation):
            fields["clip"] = clip
        if blend != self._chart.blend_name(animation):
            fields["blend"] = blend
        if fields:
            self._pending_resources[index] = fields
        else:
            self._pending_resources.pop(index, None)
        self._fill_resources(index)
        self._pending_changed()

    def _clip_field(self) -> str:
        return self.clip_edit.text().strip().replace("\\", "/")

    def _use_clip_length(self) -> None:
        index = self._selected_animation()
        clip = self._clip_field()
        if index is None or not clip or self._clip_info is None or self.busy():
            return
        reader = self._clip_info
        self.clip_info_label.setText(f"Reading {_file_name(clip)}...")

        def _done(outcome: UtilityTaskOutcome) -> None:
            if outcome.kind != "completed" or not isinstance(outcome.value, ClipInfo):
                self.clip_info_label.setText(f"Could not read the clip: {outcome.message}")
                return
            info = outcome.value
            self.clip_info_label.setText(f"{_file_name(info.clip)}: {_number(info.duration)} s, {info.frames} frames")
            row = self._rows.get(("animation.end_time", index, 0))
            if row is not None and _number(row.value) == _number(info.duration):
                self._pending_values.pop(row.key, None)
            else:
                self._pending_values[("animation.end_time", index, 0)] = float(info.duration)
            if self._selected_animation() == index:
                self._fill_values(index)
            self._pending_changed()

        self._start_task(lambda _log: reader(clip), _done)

    def _show_clip(self) -> None:
        clip = self._clip_field()
        if clip and self._show_in_browser is not None:
            self._show_in_browser(clip)

    def _undo_resources(self) -> None:
        index = self._selected_animation()
        if index is not None and self._pending_resources.pop(index, None) is not None:
            self._fill_resources(index)
            self._pending_changed()

    def _set_event_fields(self) -> None:
        row = self._selected_event()
        if row is None or not row.fields:
            return
        only_this = self.only_this_radio.isChecked()
        current = dict(row.fields)
        for name, widget in self._event_widgets.items():
            if name == _MODE_FIELD:
                value: object = widget.currentIndex()
            elif name == _BLEND_TIME_FIELD:
                value = float(widget.value())
            else:
                value = widget.currentText().strip()
            key = (row.animation, row.item, name)
            same = (abs(float(value) - float(current[name])) < 0.0005) if name == _BLEND_TIME_FIELD else value == current[name]
            if same:
                self._pending_events.pop(key, None)
            else:
                self._pending_events[key] = (value, only_this)
        self._fill_events(row.animation)
        self._select_event(row.item)
        self._pending_changed()

    def _undo_event_fields(self) -> None:
        row = self._selected_event()
        if row is None:
            return
        for key in [key for key in self._pending_events if key[0] == row.animation and key[1] == row.item]:
            del self._pending_events[key]
        self._fill_events(row.animation)
        self._select_event(row.item)
        self._pending_changed()

    def _select_event(self, item: int) -> None:
        for position, row in enumerate(self._event_rows):
            if row.item == item:
                self.event_table.selectRow(position)
                return

    def _remove_pending(self) -> None:
        item = self.pending_list.currentItem()
        if item is None:
            return
        kind, key = item.data(_KEY_ROLE)
        if kind == _RETARGET:
            self._pending_retargets.pop(tuple(key), None)
        elif kind == _RESOURCE:
            animation, field = key
            fields = self._pending_resources.get(animation, {})
            fields.pop(_RESOURCE_FIELDS[field], None)
            if not fields:
                self._pending_resources.pop(animation, None)
        elif kind == _EVENT:
            self._pending_events.pop(tuple(key), None)
        elif kind == _LINKED:
            self._linked.pop(tuple(key), None)
            self._show_changes()
        elif kind == _VALUE:
            self._pending_values.pop(tuple(key), None)
            if key[0] == "chart.action_speed_rate":
                self._filling = True
                try:
                    self.rate_spin.setValue(self._chart.action_speed_rate)
                finally:
                    self._filling = False
        self._fill_strings()
        self._animation_selected()
        self._pending_changed()

    def _rate_changed(self, value: float) -> None:
        if self._filling:
            return
        row = chart_rate_row(self._chart)
        if abs(value - row.value) < 0.00005:
            self._pending_values.pop(row.key, None)
        else:
            self._pending_values[row.key] = float(value)
        self._pending_changed()

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
            self._fill_pending()
            self._sync_buttons()
            self._sync_review_panel()

    def _sync_buttons(self) -> None:
        busy = self._thread is not None
        pending = self._pending_count() > 0
        self.apply_button.setEnabled(not busy and pending)
        self.reset_button.setEnabled(not busy and (pending or self._data != self._original))
        self.export_button.setEnabled(not busy and not pending and (not self._changes.empty or bool(self._linked)))
        self.close_button.setEnabled(not busy)
        self.clip_length_button.setEnabled(not busy)
        # Edits made while a task runs would be cleared when it finishes; lock them until then.
        self.tabs.setEnabled(not busy)
        self.rate_spin.setEnabled(not busy)
        self.remove_pending_button.setEnabled(not busy and pending)
        if pending:
            self.export_button.setToolTip("Apply the pending edits first.")
        else:
            self.export_button.setToolTip("Write the edited chart as a DMM mod.")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setStyleSheet("color: #d9534f;" if error else "")
        self.status_label.setText(text)

    # --- apply, reset, export ---------------------------------------------------------

    def pending_request(self) -> ActionChartEditRequest:
        resources = tuple(
            AnimationResourceEdit(animation, clip=fields.get("clip"), blend=fields.get("blend"))
            for animation, fields in self._pending_resources.items()
        )
        events = tuple(
            EventFieldEdit(animation, event, field, value, only_this)
            for (animation, event, field), (value, only_this) in self._pending_events.items()
        )
        values = tuple(
            ChartValueEdit(field, float(value), animation=max(animation, 0), item=item)
            for (field, animation, item), value in self._pending_values.items()
        )
        retargets = tuple(StringRetarget(table, old, new) for (table, old), new in self._pending_retargets.items())
        return ActionChartEditRequest(retargets, resources, events, values)

    def _apply(self) -> None:
        request = self.pending_request()
        if request.empty:
            self._set_status("There are no pending edits.")
            return
        missing = unknown_resources(request, self._catalogs)
        if missing:
            listing = "\n".join(f"{value} ({self.table_combo.itemText(table)})" for table, value in missing)
            answer = QMessageBox.question(
                self,
                "Check Names",
                "These names are not in the game's archives or in this chart:\n\n" + listing
                + "\n\nA clip or file that does not exist cannot play, and a socket or part the character "
                "does not have does nothing. Apply anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        data, original, path = self._data, self._original, self._path
        self._set_status("Writing the edits and reading the chart back...")
        self._start_task(lambda _log: apply_action_chart_edits(data, request, virtual_path=path, original=original),
                         self._handle_outcome)

    def _start_task(self, task: Callable[..., object], on_done: Callable[[UtilityTaskOutcome], None]) -> None:
        self._on_task_done = on_done

        def guarded(log: Callable[[str], None]) -> object:
            # A refused edit or export is an answer for the user, not a crash to report.
            try:
                return task(log)
            except ActionChartError as exc:
                return _Refused(str(exc))

        worker = UtilityWorker(guarded)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.outcome.connect(self._task_outcome)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._task_finished)
        self._worker, self._thread = worker, thread
        self._sync_buttons()
        thread.start()

    def _task_outcome(self, outcome: UtilityTaskOutcome) -> None:
        handler, self._on_task_done = self._on_task_done, None
        if isinstance(outcome.value, _Refused):
            outcome = UtilityTaskOutcome("failed", message=outcome.value.message)
        if handler is not None:
            handler(outcome)

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
        self._clear_pending()
        # Names appended by the edit become suggestions for later edits.
        for table, catalog in build_resource_catalog(self._chart, {}).items():
            if catalog.form == "names":
                self._catalogs[table] = catalog
        self._refresh_all()
        self._set_status(
            f"Applied. The chart was read back: {result.changes.count} change(s) from the shipped chart."
        )

    def _clear_pending(self) -> None:
        self._pending_retargets.clear()
        self._pending_resources.clear()
        self._pending_events.clear()
        self._pending_values.clear()
        self._rows.clear()

    def _reset(self) -> None:
        self._data = self._original
        self._chart = self._original_chart
        self._changes = ActionChartChanges()
        self._clear_pending()
        self._linked.clear()
        self._refresh_all()
        self._set_status("Back to the shipped chart.")

    def _export(self) -> None:
        if (self._changes.empty and not self._linked) or self._pending_count() or self.busy():
            return
        linked = tuple(LinkedClipChange(chart, old, new) for (chart, old), new in self._linked.items())
        payload = ActionChartEditorResult(self._data, self._changes, linked)
        plan: object = None
        if self._export_details is not None:
            plan = self._export_details(payload)
            if plan is None:
                return
        if self._export_writer is None:
            self.export_plan = plan
            self.result_payload = payload
            self.accept()
            return
        writer = self._export_writer
        self._set_status("Writing the DMM mod...")

        def _exported(outcome: UtilityTaskOutcome) -> None:
            if outcome.kind != "completed":
                self._set_status(f"The export failed, and your edits are kept: {outcome.message}", error=True)
                return
            self.export_plan = plan
            self.result_payload = payload
            if self._export_done is not None:
                self._export_done(plan, outcome.value)
            self.accept()

        self._start_task(lambda log: writer(payload, plan, log), _exported)

    def busy(self) -> bool:
        return self._thread is not None

    def reject(self) -> None:
        if self.busy():
            self._set_status("Wait for the edit to finish.")
            return
        if self._pending_count() or not self._changes.empty or self._linked:
            answer = QMessageBox.question(
                self, "Close Action Chart Editor", "Close the editor and discard your edits?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.busy():
            event.ignore()
            self._set_status("Wait for the edit to finish.")
            return
        super().closeEvent(event)


__all__ = ["ActionChartEditorDialog", "ActionChartEditorResult"]
