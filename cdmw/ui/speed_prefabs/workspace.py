"""Speed & Prefabs (experimental): the Authoring tab for how fast things play.

Animation speed works on action charts: pick a character and a set (one chart), set a
factor for the whole set, per kind of move or per move, review what changes and export.
Prefabs lists prefabs that carry speed values (scene cameras, spinning and wind-driven
objects, clouds), shows the chosen one in the Prefab Inspector beside the list, and scales
every listed prefab into one item package. Game tables holds Edit Game Table Values for
the two speed tables.

The tab does no archive work itself: the Archive Browser passes the calls in, so it can
be tested with fakes. Writing speeds into the running game stays in Crimson Live Edit.
"""

from __future__ import annotations

from math import log10
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.animation_speed_service import (
    KIND_LABELS,
    MAX_FACTOR,
    MIN_FACTOR,
    NAMED_LABEL,
    SPEED_PRESETS,
    SpeedChart,
    SpeedCharacter,
    SpeedFactors,
    SpeedPlan,
    named_match,
    named_texts,
    speed_preset,
)
from cdmw.services.prefab_speed_service import MAX_SCALE, MIN_SCALE

TOOL_TITLE = "Speed & Prefabs"
_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
#: The app draws group boxes without a frame, as a heading over their contents. These
#: margins put the contents straight under the heading's text, and `_EDGE` puts the
#: rows outside a group (the set's title, the bottom buttons) on the same line.
_EDGE = 6
_BOX_MARGINS = (_EDGE, 6, _EDGE, 4)
_MOVE_COLUMNS = ("Move", "Kind", "Seconds", "Windows", "Factor")


def _spin(name: str, value: float = 1.0) -> QDoubleSpinBox:
    """A factor field: type a value, or use the wheel or arrow keys; no fiddly arrow buttons."""

    box = QDoubleSpinBox()
    box.setObjectName(name)
    # The theme gives "cleanField" boxes zero-width arrow buttons. NoButtons is not used:
    # with a style sheet it leaves the text field one pixel wide.
    box.setProperty("cleanField", True)
    box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    box.setRange(MIN_FACTOR, MAX_FACTOR)
    box.setSingleStep(0.1)
    box.setDecimals(2)
    box.setSuffix("x")
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setFixedWidth(76)
    # The style sheet's padding does not reach the inner text field, so keep the text off the edge here.
    box.lineEdit().setTextMargins(4, 0, 6, 0)
    return box


class _WheelOnlyWhenFocused(QObject):
    """Scrolling the moves list must not change the factor under the pointer."""

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.Wheel and not watched.hasFocus():
            parent = watched.parentWidget()
            if parent is not None:
                # The cell's parent is the table's viewport: scroll the list instead.
                QCoreApplication.sendEvent(parent, event)
            return True
        return False


_SLIDER_STEPS = 200
_LOG_MIN, _LOG_MAX = log10(MIN_FACTOR), log10(MAX_FACTOR)


def _slider_position(factor: float) -> int:
    factor = min(max(float(factor), MIN_FACTOR), MAX_FACTOR)
    return round((log10(factor) - _LOG_MIN) / (_LOG_MAX - _LOG_MIN) * _SLIDER_STEPS)


def _slider_factor(position: int) -> float:
    """The factor a slider position stands for, in steps of 0.05 so 0.5x, 1.5x and 2x can be hit."""

    factor = 10 ** (_LOG_MIN + (_LOG_MAX - _LOG_MIN) * position / _SLIDER_STEPS)
    return min(max(round(round(factor / 0.05) * 0.05, 2), MIN_FACTOR), MAX_FACTOR)


def _factor_slider(spin: QDoubleSpinBox) -> QSlider:
    """A slider tied to a factor field, on a log scale so 0.5x and 2x sit equally far from 1x."""

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName(spin.objectName() + "Slider")
    slider.setProperty("cleanSlider", True)
    slider.setRange(0, _SLIDER_STEPS)
    slider.setMinimumWidth(90)
    slider.setValue(_slider_position(spin.value()))

    def _from_slider(position: int) -> None:
        if _slider_position(spin.value()) != position:
            spin.setValue(_slider_factor(position))

    def _from_spin(value: float) -> None:
        # A dragged handle stays under the pointer: it only moves when the field holds
        # another value than the handle's place stands for (typed, reset or loaded).
        if abs(_slider_factor(slider.value()) - float(value)) < 1e-6:
            return
        slider.blockSignals(True)
        slider.setValue(_slider_position(value))
        slider.blockSignals(False)

    slider.valueChanged.connect(_from_slider)
    spin.valueChanged.connect(_from_spin)
    return slider


def _hint(text: str, tooltip: str = "") -> QLabel:
    """A one-line muted note; the longer explanation lives in its tooltip."""

    label = QLabel(text)
    label.setObjectName("HintLabel")
    label.setWordWrap(True)
    if tooltip:
        label.setToolTip(tooltip)
    return label


def plan_summary(plans: Sequence[SpeedPlan]) -> str:
    """The review text: a count of changed values and a before and after line per kind."""

    if not plans or all(plan.empty for plan in plans):
        return "No speed values change. Set a factor other than 1x to make a mod."
    lines = []
    for number, plan in enumerate(plans):
        if plan.empty:
            continue
        head = plan.path if number == 0 else f"{plan.path} (plays the same clips)"
        lines.append(f"{head}: {plan.changed_values} value(s) change.")
        if abs(plan.rate_after - plan.rate_before) > 1e-6:
            lines.append(f"  Whole set rate: {plan.rate_before:g} -> {plan.rate_after:g}")
        for kind in plan.kinds:
            before = f"{kind.before[0]:g}" if kind.before[0] == kind.before[1] else f"{kind.before[0]:g} to {kind.before[1]:g}"
            after = f"{kind.after[0]:g}" if kind.after[0] == kind.after[1] else f"{kind.after[0]:g} to {kind.after[1]:g}"
            lines.append(f"  {kind.label}: {kind.values} speed window(s), rate {before} -> {after}")
    return "\n".join(lines)


class SpeedPrefabsWorkspace(QWidget):
    """Speed factors for one set at a time, prefab speed values and speed tables, in one tab."""

    PAGES = ("animation", "prefabs", "tables")

    def __init__(
        self,
        characters: Sequence[SpeedCharacter] = (),
        *,
        load_set: Callable[[str], SpeedChart],
        plan: Callable[[str, SpeedFactors, Sequence[str]], Sequence[SpeedPlan]],
        linked_of: Optional[Callable[[str], Sequence[tuple[str, bool]]]] = None,
        export: Optional[Callable[[str, SpeedFactors, Sequence[str]], None]] = None,
        export_sets: Optional[Callable[[Sequence[str], SpeedFactors], None]] = None,
        open_mod: Optional[Callable[[Optional[object]], None]] = None,
        close_mod: Optional[Callable[[], None]] = None,
        open_chart: Optional[Callable[[str], None]] = None,
        prefab_search: Optional[Callable[[str], None]] = None,
        open_prefab: Optional[Callable[[str], None]] = None,
        scale_prefabs: Optional[Callable[[Sequence[str], float, str], None]] = None,
        prefab_categories: Sequence[tuple[str, str]] = (),
        open_game_table: Optional[Callable[[str], None]] = None,
        game_table_panel: Optional[QWidget] = None,
        retry_load: Optional[Callable[[], None]] = None,
        on_show: Optional[Callable[[], None]] = None,
        confirm_discard: Optional[Callable[[str], bool]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("speedPrefabsWorkspace")
        self._characters = tuple(characters)
        self._load_set = load_set
        self._plan = plan
        self._linked_of = linked_of
        self._export = export
        self._export_sets = export_sets
        self._open_mod = open_mod
        self._close_mod = close_mod
        self._mod_title = ""
        self._mod_folder = ""
        self._mod_charts: dict[str, str] = {}
        self._batch = False
        self._open_chart = open_chart
        self._prefab_search = prefab_search
        self._open_prefab = open_prefab
        self._scale_prefabs = scale_prefabs
        self._prefab_listed_category = ""
        self._prefab_scalable: tuple[str, ...] = ()
        self._prefab_scaling = False
        self._prefab_note = ""
        self._open_game_table = open_game_table
        self._retry_load = retry_load
        self._on_show = on_show
        self._confirm_discard = confirm_discard or self._ask_discard
        self._load_failed = False
        self._pending_set = ""
        self._chart: Optional[SpeedChart] = None
        self._linked: tuple[tuple[str, bool], ...] = ()
        self._move_factors: dict[str, float] = {}
        self._filling = False
        self._prefab_path = ""
        self._prefab_searching = False
        self.prefab_inspector: Optional[QWidget] = None
        self.game_table_panel = game_table_panel
        self.last_plans: tuple[SpeedPlan, ...] = ()
        self._wheel_guard = _WheelOnlyWhenFocused(self)
        self._review_timer = QTimer(self)
        self._review_timer.setSingleShot(True)
        self._review_timer.setInterval(250)
        self._review_timer.timeout.connect(self.refresh_review)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel("Experimental")
        badge.setObjectName("WarningBadge")
        badge.setToolTip("Chart speed edits were seen working in game through Crimson Live Edit. Prefab and game "
                         "table speed edits have not been tested in game. Check the result in game before sharing.")
        header.addWidget(badge)
        header.addWidget(_hint(
            "A factor multiplies the game's speed: 2x plays twice as fast. Exports a DMM mod; game files are only read.",
            "To try speeds in the running game without a mod, use Crimson Live Edit."), 1)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("speedPrefabsTabs")
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        # Only the animation page waits for the chart index: prefabs wait for it to search,
        # and the game tables need nothing from it.
        self.stack = QStackedWidget()
        self.stack.setObjectName("speedAnimationStack")
        self.stack.addWidget(self._build_loading_page())
        self.stack.addWidget(self._build_animation_page())
        self.stack.setCurrentIndex(1)
        self.tabs.addTab(self.stack, "Animation speed")
        self.tabs.addTab(self._build_prefab_page(prefab_categories), "Prefabs")
        self.tabs.addTab(self._build_table_page(), "Game tables")
        self.tabs.currentChanged.connect(self._page_changed)
        self._fill_characters()
        self._sync_buttons()

    # --- pages --------------------------------------------------------------------------

    def current_page(self) -> str:
        return self.PAGES[self.tabs.currentIndex()]

    def show_page(self, page: str) -> None:
        if page in self.PAGES:
            self.tabs.setCurrentIndex(self.PAGES.index(page))

    def _page_changed(self, index: int) -> None:
        # The first visit to Game tables reads the AI movement table, so the page is never empty.
        if self.PAGES[index] == "tables" and self.game_table_panel is not None:
            editor = getattr(self.game_table_panel, "editor", None)
            if editor is not None and not editor.loaded_table() and editor.load.isEnabled():
                self.open_table(next(iter(self.table_buttons)))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # The owner checks here whether the game folder changed since the sets were read.
        if self._on_show is not None:
            self._on_show()

    # --- loading ------------------------------------------------------------------------

    def _build_loading_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("speedLoadingPage")
        column = QVBoxLayout(page)
        column.setSpacing(12)
        column.addStretch(1)
        self.loading_title = QLabel("Reading the game's action charts…")
        self.loading_title.setObjectName("EmptyStateTitle")
        self.loading_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_title.setWordWrap(True)
        column.addWidget(self.loading_title)
        self.loading_bar = QProgressBar()
        self.loading_bar.setObjectName("speedLoadingBar")
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedWidth(320)
        self.loading_bar.setMaximumHeight(10)
        column.addWidget(self.loading_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        self.loading_detail = QLabel("The first time takes a few seconds.")
        self.loading_detail.setObjectName("EmptyStateDetail")
        self.loading_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_detail.setWordWrap(True)
        column.addWidget(self.loading_detail)
        self.retry_button = QPushButton("Try Again")
        self.retry_button.setObjectName("speedRetryButton")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._retry)
        column.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(2)
        return page

    @property
    def load_failed(self) -> bool:
        # Kept as a flag: the loading page is hidden while another page of the tab shows.
        return self._load_failed

    @property
    def loading(self) -> bool:
        return self.stack.currentIndex() == 0

    def show_loading(self, detail: str = "") -> None:
        """Show the loading page while the caller reads the charts on a worker."""

        self._load_failed = False
        self.loading_title.setText("Reading the game's action charts…")
        self.loading_bar.setVisible(True)
        self.retry_button.setVisible(False)
        if detail:
            self.loading_detail.setText(detail)
        self.stack.setCurrentIndex(0)
        self._sync_buttons()

    def show_load_error(self, message: str) -> None:
        self._load_failed = True
        self.loading_title.setText("The action charts could not be read.")
        self.loading_bar.setVisible(False)
        self.loading_detail.setText(str(message))
        self.retry_button.setVisible(self._retry_load is not None)
        self.stack.setCurrentIndex(0)
        self._sync_buttons()

    def _retry(self) -> None:
        if self._retry_load is not None:
            self.show_loading("The first time takes a few seconds.")
            self._retry_load()

    def set_characters(self, characters: Sequence[SpeedCharacter]) -> None:
        """Fill the sets once they are read, and leave the loading page."""

        self._load_failed = False
        self._characters = tuple(characters)
        self._fill_characters()
        self.stack.setCurrentIndex(1)
        self._sync_buttons()
        pending, self._pending_set = self._pending_set, ""
        if pending and self.select_set(pending):
            return
        if self.set_list.currentItem() is None:
            first = next((row for row in range(self.set_list.count()) if not self.set_list.item(row).isHidden()), -1)
            if first >= 0:
                self.set_list.setCurrentRow(first)

    def open_set(self, path: str) -> bool:
        """Show the animation page on ``path``; while loading, select it once the sets are read.

        False when the sets are read and none of them is ``path``.
        """

        self.show_page("animation")
        if not path:
            return True
        if self.loading:
            self._pending_set = path
            return True
        return self.select_set(path)

    def clear_sets(self) -> None:
        """Forget the sets, the open set and the prefab results; the owner reads another game folder."""

        self._chart = None
        self._linked = ()
        self._move_factors = {}
        self.last_plans = ()
        self._batch = False
        self.scope_combo.setCurrentIndex(0)
        self.set_mod("", {}, reload=False)
        self.set_characters(())
        self.set_title_label.setText("Choose a set.")
        self.set_path_label.setText("")
        self.served_label.setVisible(False)
        self.move_table.setRowCount(0)
        self.review_text.setPlainText("")
        self.linked_label.setText("")
        self.prefab_table.setRowCount(0)
        self._prefab_scalable = ()
        self._prefab_scaling = False
        self.prefab_progress.setVisible(False)
        self.prefab_status_label.setText("Choose a category and search.")
        self.show_prefab_inspector("", None)
        self._sync_buttons()

    # --- building -----------------------------------------------------------------------

    def _build_animation_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("speedAnimationPage")
        row = QHBoxLayout(page)
        row.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        row.addWidget(splitter)

        left = QGroupBox("Set")
        left.setToolTip("A set is one action chart: the moves of one weapon or stance.")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(*_BOX_MARGINS)
        left_layout.setSpacing(8)
        self.character_combo = QComboBox()
        self.character_combo.setObjectName("speedCharacterCombo")
        self.character_combo.setToolTip("Character")
        self.character_combo.currentIndexChanged.connect(lambda _index: self._fill_sets())
        left_layout.addWidget(self.character_combo)
        self.set_filter_edit = QLineEdit()
        self.set_filter_edit.setObjectName("speedSetFilterEdit")
        self.set_filter_edit.setPlaceholderText("Search sets...")
        self.set_filter_edit.setClearButtonEnabled(True)
        self.set_filter_edit.textChanged.connect(lambda _text: self._filter_sets())
        left_layout.addWidget(self.set_filter_edit)
        self.set_list = QListWidget()
        self.set_list.setObjectName("speedSetList")
        self.set_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.set_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.set_list.currentItemChanged.connect(lambda _current, _previous: self._open_selected_set())
        left_layout.addWidget(self.set_list, 1)
        self.mod_label = _hint("")
        self.mod_label.setObjectName("speedModLabel")
        self.mod_label.setVisible(False)
        left_layout.addWidget(self.mod_label)
        left.setMinimumWidth(240)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        heading_box = QWidget()
        heading = QVBoxLayout(heading_box)
        heading.setContentsMargins(_EDGE, 0, _EDGE, 0)
        heading.setSpacing(2)
        self.set_title_label = QLabel("Choose a set.")
        self.set_title_label.setObjectName("speedSetTitleLabel")
        self.set_title_label.setStyleSheet("font-size: 13pt; font-weight: 600;")
        self.set_title_label.setWordWrap(True)
        self.set_title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading.addWidget(self.set_title_label)
        self.set_path_label = _hint("")
        self.set_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading.addWidget(self.set_path_label)
        right_layout.addWidget(heading_box)
        self.served_label = QLabel()
        self.served_label.setObjectName("speedServedByLabel")
        self.served_label.setStyleSheet("color: #d9822b;")
        self.served_label.setWordWrap(True)
        self.served_label.setContentsMargins(_EDGE, 0, _EDGE, 0)
        self.served_label.setVisible(False)
        right_layout.addWidget(self.served_label)

        factors = QGroupBox("Speed factors")
        factors.setToolTip("A kind's factor applies to every move of that kind; a move's own factor wins over it.")
        grid = QGridLayout(factors)
        grid.setContentsMargins(*_BOX_MARGINS)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        # Two columns of label, slider and value; the gap column keeps them apart.
        whole = QLabel("Whole set:")
        whole.setToolTip("ActionSpeedRate: scales every move in this set.")
        whole.setStyleSheet("font-weight: 600;")
        grid.addWidget(whole, 0, 0)
        self.set_factor_spin = _spin("speedSetFactorSpin")
        self.set_factor_spin.setToolTip("ActionSpeedRate: scales every move in this set.")
        self.set_factor_spin.valueChanged.connect(lambda _value: self._changed())
        self.set_factor_slider = _factor_slider(self.set_factor_spin)
        grid.addWidget(self.set_factor_slider, 0, 1)
        grid.addWidget(self.set_factor_spin, 0, 2)
        self.whole_note_label = _hint("Applies on top of every kind and move below.")
        grid.addWidget(self.whole_note_label, 0, 4, 1, 3)
        self.kind_spins: dict[str, QDoubleSpinBox] = {}
        self.kind_labels: dict[str, QLabel] = {}
        self.kind_sliders: dict[str, QSlider] = {}
        for number, (kind, label) in enumerate(KIND_LABELS.items()):
            text = QLabel(label + ":")
            spin = _spin(f"speedKindFactor_{kind}")
            spin.valueChanged.connect(lambda _value: self._kind_changed())
            line, column = 1 + number // 2, (number % 2) * 4
            grid.addWidget(text, line, column)
            slider = _factor_slider(spin)
            grid.addWidget(slider, line, column + 1)
            grid.addWidget(spin, line, column + 2)
            self.kind_spins[kind] = spin
            self.kind_sliders[kind] = slider
            self.kind_labels[kind] = text
        # The user's own kind: moves picked by parts of their names, in this set and in every listed set.
        line = 1 + (len(KIND_LABELS) + 1) // 2
        named_tip = ("Type parts of move names, separated by commas. Every move whose name contains one of them "
                     "gets this factor. A move's own factor wins, then this, then its kind. Moves without speed "
                     "windows do not change.")
        self.named_label = QLabel(NAMED_LABEL + ":")
        self.named_label.setObjectName("speedNamedLabel")
        self.named_label.setToolTip(named_tip)
        grid.addWidget(self.named_label, line, 0)
        self.named_edit = QLineEdit()
        self.named_edit.setObjectName("speedNamedEdit")
        self.named_edit.setPlaceholderText("part of a move name, such as finish, takedown")
        self.named_edit.setClearButtonEnabled(True)
        self.named_edit.setToolTip(named_tip)
        self.named_edit.textChanged.connect(lambda _text: self._kind_changed())
        grid.addWidget(self.named_edit, line, 1, 1, 4)
        self.named_spin = _spin("speedNamedFactorSpin")
        self.named_spin.valueChanged.connect(lambda _value: self._kind_changed())
        self.named_slider = _factor_slider(self.named_spin)
        grid.addWidget(self.named_slider, line, 5)
        grid.addWidget(self.named_spin, line, 6)
        grid.setColumnMinimumWidth(3, 24)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(5, 1)
        right_layout.addWidget(factors)

        moves = QGroupBox("Moves")
        moves_layout = QVBoxLayout(moves)
        moves_layout.setContentsMargins(*_BOX_MARGINS)
        moves_layout.setSpacing(6)
        self.move_filter_edit = QLineEdit()
        self.move_filter_edit.setObjectName("speedMoveFilterEdit")
        self.move_filter_edit.setPlaceholderText("Filter moves...")
        self.move_filter_edit.setClearButtonEnabled(True)
        self.move_filter_edit.textChanged.connect(lambda _text: self._filter_moves())
        moves_layout.addWidget(self.move_filter_edit)
        self.move_table = QTableWidget(0, len(_MOVE_COLUMNS))
        self.move_table.setObjectName("speedMoveTable")
        self.move_table.setHorizontalHeaderLabels(list(_MOVE_COLUMNS))
        header = self.move_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(_MOVE_COLUMNS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        # The factor box keeps one fixed width, so its arrows stay usable however long the names are.
        header.setSectionResizeMode(len(_MOVE_COLUMNS) - 1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(len(_MOVE_COLUMNS) - 1, 96)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.verticalHeader().setDefaultSectionSize(32)
        self.move_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.move_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.move_table.setWordWrap(False)
        moves_layout.addWidget(self.move_table, 1)
        linked_row = QHBoxLayout()
        linked_row.setSpacing(10)
        self.linked_checkbox = QCheckBox("Also change linked charts")
        self.linked_checkbox.setObjectName("speedLinkedCheckbox")
        self.linked_checkbox.setToolTip("Also change these moves in the charts that include this set's clips.")
        self.linked_checkbox.toggled.connect(lambda _checked: self._changed())
        linked_row.addWidget(self.linked_checkbox)
        self.linked_label = _hint("")
        self.linked_label.setObjectName("speedLinkedLabel")
        linked_row.addWidget(self.linked_label, 1)
        moves_layout.addLayout(linked_row)
        right_layout.addWidget(moves, 1)

        review = QGroupBox("Review")
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(*_BOX_MARGINS)
        self.review_text = QPlainTextEdit()
        self.review_text.setObjectName("speedReviewText")
        self.review_text.setReadOnly(True)
        self.review_text.setMaximumHeight(72)
        review_layout.addWidget(self.review_text)
        right_layout.addWidget(review)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(_EDGE, 0, _EDGE, 0)
        self.reset_button = QPushButton("Reset to 1x")
        self.reset_button.setObjectName("speedResetButton")
        self.reset_button.clicked.connect(self.reset_factors)
        self.open_chart_button = QPushButton("Open in Action Chart Editor")
        self.open_chart_button.setObjectName("speedOpenChartButton")
        self.open_chart_button.setToolTip("Edit this set's clips, timing and events by hand.")
        self.open_chart_button.clicked.connect(self._open_in_editor)
        self.export_button = QPushButton("Export DMM Mod...")
        self.export_button.setObjectName("speedExportButton")
        self.export_button.setProperty("primaryAction", True)
        self.export_button.clicked.connect(self._export_clicked)
        self.start_combo = QComboBox()
        self.start_combo.setObjectName("speedStartCombo")
        self.start_combo.setToolTip("Starting points put factors into the sliders and leave the others as they are; "
                                    "the numbers are not tested in game. A speed mod you made shows that mod's "
                                    "factors, so you can change them and export again.")
        self.start_combo.activated.connect(self._start_chosen)
        self._fill_start_combo()
        self.scope_label = QLabel("Apply to:")
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("speedScopeCombo")
        self.scope_combo.setToolTip("All listed sets: every set shown in the list on the left gets these factors "
                                    "in one mod. Narrow the list with Search sets first.")
        self.scope_combo.addItem("This set", "set")
        self.scope_combo.addItem("All listed sets", "listed")
        self.scope_combo.setEnabled(self._export_sets is not None)
        self.scope_combo.currentIndexChanged.connect(lambda _index: self._scope_changed())
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.start_combo)
        buttons.addStretch(1)
        buttons.addWidget(self.open_chart_button)
        buttons.addSpacing(8)
        buttons.addWidget(self.scope_label)
        buttons.addWidget(self.scope_combo)
        buttons.addWidget(self.export_button)
        right_layout.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 880])
        return page

    def _build_prefab_page(self, categories: Sequence[tuple[str, str]]) -> QWidget:
        page = QWidget()
        page.setObjectName("speedPrefabPage")
        row = QHBoxLayout(page)
        row.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        row.addWidget(splitter)

        left = QGroupBox("Find prefabs")
        left.setToolTip("Speeds of scene cameras, spinning and wind-driven objects and clouds. Not the player's "
                        "moves, and not effects. Prefab speed edits have not been tested in game.")
        layout = QVBoxLayout(left)
        layout.setContentsMargins(*_BOX_MARGINS)
        layout.setSpacing(8)
        search = QHBoxLayout()
        self.prefab_category_combo = QComboBox()
        self.prefab_category_combo.setObjectName("speedPrefabCategoryCombo")
        self.prefab_category_combo.setToolTip("Category")
        self.prefab_category_combo.addItem("All categories", "")
        for key, label in categories:
            self.prefab_category_combo.addItem(label, key)
        search.addWidget(self.prefab_category_combo, 1)
        self.prefab_search_button = QPushButton("Search")
        self.prefab_search_button.setObjectName("speedPrefabSearchButton")
        self.prefab_search_button.setToolTip("The first search reads every prefab and takes a few minutes; "
                                             "later searches are quick.")
        self.prefab_search_button.clicked.connect(self._search_prefabs)
        search.addWidget(self.prefab_search_button)
        layout.addLayout(search)
        self.prefab_progress = QProgressBar()
        self.prefab_progress.setObjectName("speedPrefabProgress")
        self.prefab_progress.setTextVisible(False)
        self.prefab_progress.setMaximumHeight(8)
        self.prefab_progress.setVisible(False)
        layout.addWidget(self.prefab_progress)
        self.prefab_status_label = _hint("Choose a category and search.")
        self.prefab_status_label.setObjectName("speedPrefabStatusLabel")
        layout.addWidget(self.prefab_status_label)
        self.prefab_table = QTableWidget(0, 3)
        self.prefab_table.setObjectName("speedPrefabTable")
        self.prefab_table.setHorizontalHeaderLabels(["Prefab", "Category", "Speed values"])
        header = self.prefab_table.horizontalHeader()
        # The three columns always share the list's width (see _fit_prefab_columns): long
        # names are cut in the middle and shown whole in their tooltips, never scrolled sideways.
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.prefab_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.prefab_table.viewport().installEventFilter(self)
        self.prefab_table.verticalHeader().setVisible(False)
        self.prefab_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.prefab_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.prefab_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.prefab_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.prefab_table.setWordWrap(False)
        self.prefab_table.itemSelectionChanged.connect(self._prefab_selected)
        layout.addWidget(self.prefab_table, 1)
        batch = QHBoxLayout()
        batch.setSpacing(8)
        batch.addWidget(QLabel("Scale the listed prefabs by"))
        self.prefab_batch_spin = _spin("speedPrefabBatchFactorSpin")
        self.prefab_batch_spin.setRange(MIN_SCALE, MAX_SCALE)
        self.prefab_batch_spin.setFixedWidth(84)
        self.prefab_batch_spin.setToolTip("2x doubles every speed value, 0.5x halves it.")
        self.prefab_batch_spin.valueChanged.connect(lambda _value: self._sync_buttons())
        batch.addWidget(self.prefab_batch_spin)
        batch.addStretch(1)
        self.prefab_batch_button = QPushButton("Scale Listed Prefabs…")
        self.prefab_batch_button.setObjectName("speedPrefabBatchButton")
        self.prefab_batch_button.clicked.connect(self._scale_prefabs_clicked)
        batch.addWidget(self.prefab_batch_button)
        layout.addLayout(batch)
        left.setMinimumWidth(320)
        splitter.addWidget(left)

        self.prefab_host = QStackedWidget()
        self.prefab_host.setObjectName("speedPrefabInspectorHost")
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        title = QLabel("No prefab selected")
        title.setObjectName("EmptyStateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(title)
        self.prefab_empty_detail = QLabel("Search, then pick a prefab to see and scale its speed values here.")
        self.prefab_empty_detail.setObjectName("EmptyStateDetail")
        self.prefab_empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prefab_empty_detail.setWordWrap(True)
        empty_layout.addWidget(self.prefab_empty_detail)
        empty_layout.addStretch(2)
        self.prefab_host.addWidget(empty)
        # Framed like the list beside it, so both sides line up under one kind of heading.
        inspector_box = QGroupBox("Prefab Inspector")
        inspector_box.setObjectName("speedPrefabInspectorBox")
        inspector_layout = QVBoxLayout(inspector_box)
        inspector_layout.setContentsMargins(*_BOX_MARGINS)
        inspector_layout.addWidget(self.prefab_host)
        splitter.addWidget(inspector_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([460, 700])
        return page

    def _build_table_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("speedTablePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        choose = QHBoxLayout()
        choose.setContentsMargins(_EDGE, 0, _EDGE, 0)
        choose.setSpacing(6)
        self.table_buttons: dict[str, QPushButton] = {}
        for table, label, detail in (
                ("aimovespeedinfo", "AI movement speeds", "Move, minimum and turn speed of each AI speed row."),
                ("gimmickinfo", "Pushed objects", "How fast objects move when pushed.")):
            button = QPushButton(label)
            button.setObjectName(f"speedTableButton_{table}")
            button.setCheckable(True)
            button.setToolTip(detail + " Units are not known, and these edits have not been tested in game.")
            button.setEnabled(self._open_game_table is not None)
            button.clicked.connect(lambda _checked=False, name=table: self.open_table(name))
            choose.addWidget(button)
            self.table_buttons[table] = button
        choose.addSpacing(8)
        choose.addWidget(_hint("Change values in existing rows of the game's tables. Their effect in game has not "
                               "been verified."), 1)
        layout.addLayout(choose)
        editor = getattr(self.game_table_panel, "editor", None)
        if editor is not None and hasattr(editor, "intro"):
            editor.intro.setVisible(False)  # said once, beside the table buttons
        if self.game_table_panel is not None:
            layout.addWidget(self.game_table_panel, 1)
        else:
            layout.addWidget(_hint("Game tables open in Edit Game Table Values, which writes a DMM mod."))
            layout.addStretch(1)
        return page

    def open_table(self, table: str) -> None:
        """Choose ``table`` on the Game tables page and read it in place."""

        for name, button in self.table_buttons.items():
            button.setChecked(name == table)
        if self._open_game_table is not None:
            self._open_game_table(table)

    # --- sets ---------------------------------------------------------------------------

    def _fill_characters(self) -> None:
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for character in self._characters:
            self.character_combo.addItem(character.name, character.name)
        self.character_combo.blockSignals(False)
        self._fill_sets()

    def _current_character(self) -> Optional[SpeedCharacter]:
        index = self.character_combo.currentIndex()
        return self._characters[index] if 0 <= index < len(self._characters) else None

    def _fill_sets(self) -> None:
        self.set_list.blockSignals(True)
        self.set_list.clear()
        character = self._current_character()
        for item in (character.sets if character else ()):
            row = QListWidgetItem(item.label)
            row.setData(_PATH_ROLE, item.path)
            self.set_list.addItem(row)
        self.set_list.blockSignals(False)
        self._mark_mod_sets()
        self._filter_sets()

    def _mark_mod_sets(self) -> None:
        """The sets the open mod holds are bold, with what the mod does to them in the tooltip."""

        for number in range(self.set_list.count()):
            item = self.set_list.item(number)
            path = str(item.data(_PATH_ROLE))
            line = self._mod_charts.get(path.lower())
            font = QFont(self.set_list.font())
            font.setBold(line is not None)
            item.setFont(font)
            item.setToolTip(path if line is None else f"{path}\nIn the mod {self._mod_title}: {line}")

    def _filter_sets(self) -> None:
        text = self.set_filter_edit.text().strip().lower()
        for number in range(self.set_list.count()):
            item = self.set_list.item(number)
            shown = not text or text in item.text().lower() or text in str(item.data(_PATH_ROLE)).lower()
            item.setHidden(not shown)
        self._refresh_scope_text()

    def listed_sets(self) -> tuple[str, ...]:
        """The paths of the sets the list shows now: what "All listed sets" stands for."""

        return tuple(str(self.set_list.item(number).data(_PATH_ROLE)) for number in range(self.set_list.count())
                     if not self.set_list.item(number).isHidden())

    def scope(self) -> str:
        """"listed" while the factors go to every listed set, else "set"."""

        return "listed" if self._export_sets is not None and self.scope_combo.currentData() == "listed" else "set"

    def set_scope(self, scope: str) -> bool:
        position = self.scope_combo.findData(scope)
        if position < 0 or (scope == "listed" and self._export_sets is None):
            return False
        self.scope_combo.setCurrentIndex(position)
        return True

    def _refresh_scope_text(self) -> None:
        if not hasattr(self, "scope_combo"):
            return
        character = self._current_character()
        count = len(self.listed_sets())
        self.scope_combo.setItemText(1, f"All {count} listed sets of {character.name}" if character
                                     else "All listed sets")
        if self.scope() == "listed":
            self._changed()

    def _scope_changed(self) -> None:
        listed = self.scope() == "listed"
        self._filling = True
        try:
            if listed:
                self.set_factor_spin.setValue(1.0)  # one set at a time: see WHOLE_SET_ONE_AT_A_TIME
                self.linked_checkbox.setChecked(False)
            else:
                self.linked_checkbox.setChecked(any(inside for _path, inside in self._linked))
        finally:
            self._filling = False
        self._apply_scope()
        self._changed()

    def _apply_scope(self) -> None:
        """Which controls the scope leaves usable: no whole-set factor on many sets, every kind for them."""

        listed = self.scope() == "listed"
        self.set_factor_spin.setEnabled(not listed)
        self.set_factor_slider.setEnabled(not listed)
        self.whole_note_label.setText("Works on one set at a time." if listed
                                      else "Applies on top of every kind and move below.")
        kinds = {kind for kind, _label, _count in self._chart.kinds()} if self._chart is not None else set()
        for kind, spin in self.kind_spins.items():
            # A kind this set has no moves of stays visible but greyed, so the grid keeps its shape.
            for widget in (spin, self.kind_sliders[kind], self.kind_labels[kind]):
                widget.setEnabled(listed or kind in kinds)
        # The listed sets are the selection: what the list shows is what changes.
        self.linked_checkbox.setEnabled(not listed and bool(self._linked))

    @property
    def pending_set(self) -> str:
        """The set to open once the sets are read (see open_set)."""

        return self._pending_set

    def has_set(self, path: str) -> bool:
        wanted = str(path or "").replace("\\", "/").lower()
        return any(item.path.lower() == wanted for character in self._characters for item in character.sets)

    def select_set(self, path: str) -> bool:
        """Select a set by chart path in any character; False when none has it."""

        wanted = str(path or "").replace("\\", "/").lower()
        for number, character in enumerate(self._characters):
            if any(item.path.lower() == wanted for item in character.sets):
                self.character_combo.setCurrentIndex(number)
                for row in range(self.set_list.count()):
                    if str(self.set_list.item(row).data(_PATH_ROLE)).lower() == wanted:
                        self.set_list.setCurrentRow(row)
                        return True
        return False

    def _open_selected_set(self) -> None:
        item = self.set_list.currentItem()
        if item is None:
            return
        path = str(item.data(_PATH_ROLE))
        try:
            chart = self._load_set(path)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.set_title_label.setText(f"Could not read {path}: {exc}")
            self.set_path_label.setText("")
            self._chart = None
            self._sync_buttons()
            return
        linked: tuple[tuple[str, bool], ...] = ()
        if self._linked_of is not None:
            try:
                linked = tuple(self._linked_of(chart.path))
            except Exception:  # noqa: BLE001 - linked charts are a hint, never a blocker
                linked = ()
        self.show_chart(chart, linked)

    def show_chart(self, chart: SpeedChart, linked: Sequence[tuple[str, bool]] = ()) -> None:
        self._chart = chart
        self._linked = tuple(linked)
        self._filling = True
        try:
            self.set_title_label.setText(chart.label)
            if chart.mod:
                self.set_path_label.setText(f"{chart.path} · whole set rate {chart.rate:g} · factors from the mod {chart.mod}")
            else:
                self.set_path_label.setText(f"{chart.path} · whole set rate {chart.rate:g}")
            self.served_label.setText(
                f"The mounted DMM mod {chart.served_by} already serves this chart. A mod exported here competes "
                "with it in DMM's load order." if chart.served_by else "")
            self.served_label.setVisible(bool(chart.served_by))
            listed = self.scope() == "listed"
            counts = {kind: count for kind, _label, count in chart.kinds()}
            for kind in self.kind_spins:
                self.kind_labels[kind].setText(f"{KIND_LABELS[kind]} ({counts.get(kind, 0)}):")
            if not listed:
                # With "All listed sets" the factors belong to the whole list, so they stay as they are.
                self.set_factor_spin.setValue(float(chart.factors.set))
                for kind, spin in self.kind_spins.items():
                    spin.setValue(float(chart.factors.kinds.get(kind, 1.0)))
                self.named_edit.setText(", ".join(chart.factors.named))
                self.named_spin.setValue(float(chart.factors.named_factor))
                self._move_factors = {clip.lower(): float(value) for clip, value in chart.factors.moves.items()}
            self._fill_moves()
            self._refresh_named_label()
            included = [path for path, inside in self._linked if inside]
            others = [path for path, inside in self._linked if not inside]
            self.linked_checkbox.setChecked(bool(included) and not listed)
            self._apply_scope()
            if self._linked:
                if included:
                    self.linked_label.setText(f"{len(self._linked)} other chart(s) play some of these clips, "
                                              f"{len(included)} included by this set.")
                else:
                    self.linked_label.setText(f"{len(self._linked)} other chart(s) play some of these clips.")
                self.linked_label.setToolTip(
                    "A move can play from another chart, so a change here alone can show nothing in game.\n\n"
                    + "\n".join([f"{path} (included by this set)" for path in included] + others[:20]
                                 + ([f"and {len(others) - 20} more"] if len(others) > 20 else [])))
            else:
                self.linked_label.setText("")
                self.linked_label.setToolTip("")
        finally:
            self._filling = False
        self._changed()

    def _fill_moves(self) -> None:
        chart = self._chart
        self.move_table.setRowCount(0)
        if chart is None:
            return
        self.move_table.setRowCount(len(chart.moves))
        for row, move in enumerate(chart.moves):
            name = QTableWidgetItem(move.label)
            name.setToolTip(move.clip)
            name.setData(_PATH_ROLE, move.clip)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.move_table.setItem(row, 0, name)
            for column, text in ((1, KIND_LABELS[move.kind]), (2, f"{move.seconds:g}"), (3, str(move.windows))):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.move_table.setItem(row, column, cell)
            spin = _spin(f"speedMoveFactor_{row}", self._shown_factor(move.clip, move.kind))
            spin.setProperty("inCell", True)
            spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            # Puts the number on the same line and the same left edge as the row's other cells.
            spin.lineEdit().setTextMargins(2, 0, 0, 2)
            spin.setMinimumWidth(0)
            spin.setMaximumWidth(16777215)
            spin.setToolTip("Type a factor for this move.")
            spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            spin.installEventFilter(self._wheel_guard)
            spin.setEnabled(move.windows > 0)
            spin.valueChanged.connect(lambda value, clip=move.clip: self._move_changed(clip, value))
            self.move_table.setCellWidget(row, 4, spin)
        self._filter_moves()

    def _named(self) -> tuple[str, ...]:
        return named_texts(self.named_edit.text().split(","))

    def _base_factor(self, clip: str, kind: str) -> float:
        """What a move gets without a factor of its own: Moves named when its name matches, else its kind's."""

        texts = self._named()
        if texts and named_match(clip, texts):
            return float(self.named_spin.value())
        return float(self.kind_spins[kind].value())

    def _shown_factor(self, clip: str, kind: str) -> float:
        return self._move_factors.get(clip.lower(), self._base_factor(clip, kind))

    def _refresh_named_label(self) -> None:
        texts = self._named()
        if texts and self._chart is not None:
            count = sum(1 for move in self._chart.moves if named_match(move.clip, texts))
            self.named_label.setText(f"{NAMED_LABEL} ({count}):")
        else:
            self.named_label.setText(NAMED_LABEL + ":")

    def _filter_moves(self) -> None:
        text = self.move_filter_edit.text().strip().lower()
        for row in range(self.move_table.rowCount()):
            item = self.move_table.item(row, 0)
            kind = self.move_table.item(row, 1)
            shown = not text or text in str(item.data(_PATH_ROLE)).lower() or text in kind.text().lower()
            self.move_table.setRowHidden(row, not shown)

    # --- factors ------------------------------------------------------------------------

    def _move_changed(self, clip: str, value: float) -> None:
        if self._filling or self._chart is None:
            return
        kind = next((move.kind for move in self._chart.moves if move.clip == clip), "other")
        if abs(float(value) - self._base_factor(clip, kind)) < 1e-6:
            self._move_factors.pop(clip.lower(), None)
        else:
            self._move_factors[clip.lower()] = float(value)
        self._changed()

    def _kind_changed(self) -> None:
        """A kind's or the Moves named factor (or its texts) changed: the moves show what they now get."""

        if self._filling:
            return
        self._refresh_named_label()
        if self._chart is None:
            self._changed()
            return
        self._filling = True
        try:
            for row, move in enumerate(self._chart.moves):
                spin = self.move_table.cellWidget(row, 4)
                if spin is not None:
                    spin.setValue(self._shown_factor(move.clip, move.kind))
        finally:
            self._filling = False
        self._changed()

    def factors(self) -> SpeedFactors:
        """What the page asks for: move factors only where they differ from their kind's."""

        clips = {move.clip.lower(): move.clip for move in (self._chart.moves if self._chart else ())}
        kinds = {kind: round(float(spin.value()), 2) for kind, spin in self.kind_spins.items()
                 if abs(spin.value() - 1.0) > 1e-6}
        moves = {clips.get(key, key): round(value, 2) for key, value in self._move_factors.items()}
        return SpeedFactors(round(float(self.set_factor_spin.value()), 2), kinds, moves,
                            self._named(), round(float(self.named_spin.value()), 2))

    def linked_paths(self) -> tuple[str, ...]:
        if not self.linked_checkbox.isChecked():
            return ()
        return tuple(path for path, inside in self._linked if inside)

    def reset_factors(self) -> None:
        self.apply_factors(SpeedFactors())

    def apply_factors(self, factors: SpeedFactors, linked: Optional[bool] = None) -> None:
        """Put ``factors`` into the controls as if they were typed; ``linked`` sets the linked charts box."""

        self._filling = True
        try:
            self.set_factor_spin.setValue(1.0 if self.scope() == "listed" else float(factors.set))
            for kind, spin in self.kind_spins.items():
                spin.setValue(float(factors.kinds.get(kind, 1.0)))
            self.named_edit.setText(", ".join(factors.named))
            self.named_spin.setValue(float(factors.named_factor))
            self._move_factors = {clip.lower(): float(value) for clip, value in factors.moves.items()}
            self._fill_moves()
            self._refresh_named_label()
            if linked is not None and self.linked_checkbox.isEnabled():
                self.linked_checkbox.setChecked(bool(linked))
        finally:
            self._filling = False
        self._changed()

    def apply_preset(self, key: str) -> None:
        """Put a starting point's factors into the controls; the factors it does not name stay."""

        preset = speed_preset(key)
        now = self.factors()
        named = (preset.named, preset.named_factor) if preset.named else (now.named, now.named_factor)
        self.apply_factors(SpeedFactors(now.set, {**now.kinds, **preset.kinds}, now.moves, *named))

    # --- starting points and the open mod -------------------------------------------------

    def _fill_start_combo(self) -> None:
        combo = self.start_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Start from…", "")
        for preset in SPEED_PRESETS:
            combo.addItem(preset.label, f"preset:{preset.key}")
        if self._open_mod is not None:
            combo.insertSeparator(combo.count())
            combo.addItem("A speed mod you made…", "open_mod")
            if self._mod_title and self._close_mod is not None:
                combo.addItem(f"Close the mod {self._mod_title}", "close_mod")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _start_chosen(self, index: int) -> None:
        choice = str(self.start_combo.itemData(index) or "")
        self.start_combo.setCurrentIndex(0)  # a pick-and-apply list: it always shows its caption
        self.choose_start(choice)

    def choose_start(self, choice: str) -> bool:
        """Act as the Start from list does: "preset:<key>", "open_mod" or "close_mod"."""

        if choice.startswith("preset:"):
            self.apply_preset(choice.partition(":")[2])
        elif choice == "open_mod" and self._open_mod is not None:
            self._open_mod(None)  # the owner asks for the mod's folder
        elif choice == "close_mod" and self._close_mod is not None and self._mod_title:
            self._close_mod()
        else:
            return False
        return True

    def open_mod(self, summary: object) -> bool:
        """Show a speed mod the caller already read (a SpeedModSummary); False without an owner for it."""

        if self._open_mod is None:
            return False
        self._open_mod(summary)
        return True

    def set_mod(self, title: str, charts: Mapping[str, str], *, folder: str = "", derived: bool = False,
                reload: bool = True) -> None:
        """Show which speed mod is open (an empty title closes it) and mark the sets it holds.

        ``charts`` maps a chart path to one line on what the mod does to it. With ``reload`` the
        selected set is read again, so its controls show the mod's factors (or the game's speeds
        once the mod is closed).
        """

        self._mod_title = str(title or "")
        self._mod_folder = str(folder or "") if self._mod_title else ""
        self._mod_charts = {str(path).lower(): str(line) for path, line in charts.items()} if self._mod_title else {}
        if self._mod_title:
            text = f"Mod: {self._mod_title}, {len(self._mod_charts)} chart(s)"
            if derived:
                text += ". Some factors are worked out from the chart values and may be rounded."
            self.mod_label.setText(text)
        self.mod_label.setVisible(bool(self._mod_title))
        self._fill_start_combo()
        self._mark_mod_sets()
        if reload and self.set_list.currentItem() is not None:
            self._open_selected_set()

    def move_clips(self) -> tuple[str, ...]:
        return tuple(move.clip for move in (self._chart.moves if self._chart else ()))

    def _changed(self) -> None:
        if self._filling:
            return
        self._sync_buttons()
        self._review_timer.start()

    def refresh_review(self) -> None:
        self._review_timer.stop()
        if self._batch:
            return  # the Review shows the check of the listed sets until it ends
        if self._chart is None:
            self.review_text.setPlainText("")
            self.last_plans = ()
            return
        listed = self.scope() == "listed"
        head = ""
        if listed:
            character = self._current_character()
            head = (f"These factors go to all {len(self.listed_sets())} listed sets of "
                    f"{character.name if character else ''}. The other sets are checked when you export.\n")
        try:
            self.last_plans = tuple(self._plan(self._chart.path, self.factors(), self.linked_paths()))
            self.review_text.setPlainText(head + plan_summary(self.last_plans))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.last_plans = ()
            self.review_text.setPlainText(f"These factors cannot be applied: {exc}")
        self._sync_buttons()

    def show_batch_progress(self, done: int, total: int, path: str = "") -> None:
        """How far the owner's check of the listed sets got; the Review shows it until end_batch."""

        self._batch = True
        self.review_text.setPlainText(f"Checking set {min(int(done) + 1, int(total))} of {int(total)}…"
                                      if total > 0 else "Checking the listed sets…")
        self._sync_buttons()

    def end_batch(self) -> None:
        """The check or the export of the listed sets ended: the Review shows the open set again."""

        self._batch = False
        self.refresh_review()

    @property
    def has_changes(self) -> bool:
        return self._chart is not None and not self.factors().is_identity

    def _sync_buttons(self) -> None:
        chart_open = self._chart is not None
        if self.scope() == "listed":
            listed = bool(self.listed_sets())
            self.export_button.setEnabled(listed and self.has_changes and not self._batch)
            self.export_button.setToolTip("" if self.export_button.isEnabled()
                                          else "The listed sets are being checked." if self._batch
                                          else "No set is listed." if not listed
                                          else "Set a factor other than 1x first.")
        else:
            # A set back at 1x everywhere can still be exported when it came from a mod: that takes it out.
            self.export_button.setEnabled(chart_open and self._export is not None and not self._batch
                                          and (self.has_changes or bool(self._chart and self._chart.mod)))
            self.export_button.setToolTip("" if self.export_button.isEnabled()
                                          else "Set a factor other than 1x first.")
        self.reset_button.setEnabled(chart_open)
        self.open_chart_button.setEnabled(chart_open and self._open_chart is not None)
        if hasattr(self, "prefab_search_button"):
            ready = (self._prefab_search is not None and not self.loading and not self._prefab_searching
                     and not self._prefab_scaling)
            self.prefab_search_button.setEnabled(ready)
            self.prefab_search_button.setToolTip(
                self.loading_detail.text() if self.load_failed
                else "Waiting for the game's file index." if self.loading
                else "The first search reads every prefab and takes a few minutes; later searches are quick.")
            idle = not self._prefab_searching and not self._prefab_scaling
            changes = abs(self.prefab_batch_spin.value() - 1.0) > 1e-9
            self.prefab_batch_button.setEnabled(self._scale_prefabs is not None and idle and changes
                                                and bool(self._prefab_scalable))
            self.prefab_batch_button.setToolTip(
                "The listed prefabs are being read." if self._prefab_scaling
                else "No listed prefab holds a speed value that can be scaled." if not self._prefab_scalable
                else "Set a factor other than 1x first." if not changes
                else "Scales every speed value of the listed prefabs that is fully read and saves them as one "
                     "item package. Prefab speed edits have not been tested in game.")

    def _export_clicked(self) -> None:
        if self.scope() == "listed":
            paths = self.listed_sets()
            if paths and self._export_sets is not None:
                self._export_sets(paths, self.factors())
        elif self._chart is not None and self._export is not None:
            self.refresh_review()
            self._export(self._chart.path, self.factors(), self.linked_paths())

    def _open_in_editor(self) -> None:
        if self._chart is not None and self._open_chart is not None:
            self._open_chart(self._chart.path)

    # --- prefabs ------------------------------------------------------------------------

    def prefab_category(self) -> str:
        return str(self.prefab_category_combo.currentData() or "")

    def search_prefabs(self, category: Optional[str] = None) -> bool:
        """Press Search, on ``category`` when one is given; False when Search cannot be pressed now."""

        if category is not None:
            position = self.prefab_category_combo.findData(category)
            if position < 0:
                return False
            self.prefab_category_combo.setCurrentIndex(position)
        if not self.prefab_search_button.isEnabled():
            return False
        self.prefab_search_button.click()
        return True

    def _search_prefabs(self) -> None:
        if self._prefab_search is None:
            return
        self._prefab_searching = True
        self._prefab_listed_category = self.prefab_category()
        self.prefab_status_label.setText("Searching the game's prefabs…")
        self.prefab_progress.setRange(0, 0)
        self.prefab_progress.setVisible(True)
        self._sync_buttons()
        self._prefab_search(self.prefab_category())

    def show_prefab_progress(self, done: int, total: int, detail: str = "") -> None:
        """How far the caller's search worker got; ``total`` 0 keeps the bar moving without a count."""

        if total > 0:
            self.prefab_progress.setRange(0, int(total))
            self.prefab_progress.setValue(min(int(done), int(total)))
            self.prefab_status_label.setText(detail or f"{done:,} of {total:,} prefabs read…")
        elif detail:
            self.prefab_status_label.setText(detail)
        self.prefab_progress.setVisible(True)

    def show_prefab_results(self, rows: Sequence[Mapping[str, object]], *, note: str = "") -> None:
        """Rows with path, category label and what was reached; called by the caller's search worker.

        A row with ``values`` shows how many speed values were reached and their names, or why
        the prefab cannot be scaled (``state``); a row without it shows its ``members``.
        """

        self._prefab_searching = False
        self._prefab_scaling = False
        self.prefab_progress.setVisible(False)
        self.prefab_table.setRowCount(len(rows))
        scalable: list[str] = []
        counted = 0
        for number, row in enumerate(rows):
            full = str(row.get("path", ""))
            path = QTableWidgetItem(full.rsplit("/", 1)[-1])
            path.setData(_PATH_ROLE, full)
            path.setToolTip(full)
            self.prefab_table.setItem(number, 0, path)
            category = QTableWidgetItem(str(row.get("category_label", row.get("category", ""))))
            self.prefab_table.setItem(number, 1, category)
            if "values" not in row:
                members = [str(m) for m in row.get("members", ())]
                cell = QTableWidgetItem(", ".join(_short_member(m) for m in members))
                cell.setToolTip("\n".join(members))
                self.prefab_table.setItem(number, 2, cell)
                continue
            counted += 1
            count, state = int(row.get("values") or 0), str(row.get("state") or "")
            labels = [str(label) for label in row.get("labels", ())]
            if count and not state:
                scalable.append(full)
                cell = QTableWidgetItem(f"{count}: {', '.join(labels)}")
                cell.setToolTip("\n".join(labels))
            else:
                cell = QTableWidgetItem(state or "none reached")
                cell.setToolTip(f"Cannot be scaled: {state}." if state
                                else "The prefab names a speed type and holds no value of it.")
                for item in (path, category, cell):
                    item.setForeground(Qt.GlobalColor.gray)  # readable in the light and the dark themes
            self.prefab_table.setItem(number, 2, cell)
        self._prefab_scalable = tuple(scalable)
        if note:
            self.prefab_status_label.setText(note)
        elif not counted:
            self.prefab_status_label.setText(f"{len(rows):,} prefab(s) found.")
        elif counted == len(scalable):
            self.prefab_status_label.setText(f"{len(scalable):,} prefab(s) hold speed values.")
        else:
            self.prefab_status_label.setText(f"{len(scalable):,} prefab(s) hold speed values; "
                                             f"{counted - len(scalable):,} hold none that can be scaled.")
        self._fit_prefab_columns()
        self._select_prefab_row(self._prefab_path)  # the open prefab stays marked when it is listed again
        self._sync_buttons()

    def scalable_prefabs(self) -> tuple[str, ...]:
        """The listed prefabs that hold a speed value that can be scaled."""

        return self._prefab_scalable

    def scale_listed_prefabs(self, factor: Optional[float] = None) -> bool:
        """Press Scale Listed Prefabs, with ``factor`` when one is given; False when it cannot be pressed."""

        if factor is not None:
            if not MIN_SCALE <= float(factor) <= MAX_SCALE:
                return False
            self.prefab_batch_spin.setValue(float(factor))
        if not self.prefab_batch_button.isEnabled():
            return False
        self.prefab_batch_button.click()
        return True

    def _scale_prefabs_clicked(self) -> None:
        if self._scale_prefabs is None or not self._prefab_scalable:
            return
        self._scale_prefabs(self._prefab_scalable, float(self.prefab_batch_spin.value()), self._prefab_listed_category)

    def begin_prefab_scaling(self) -> None:
        """The caller's worker reads the listed prefabs: the bar moves and the buttons wait."""

        if not self._prefab_scaling:
            self._prefab_note = self.prefab_status_label.text()
        self._prefab_scaling = True
        self.prefab_progress.setRange(0, 0)
        self.prefab_progress.setVisible(True)
        self.prefab_status_label.setText("Reading the listed prefabs…")
        self._sync_buttons()

    def end_prefab_scaling(self) -> None:
        if self._prefab_scaling:
            self._prefab_scaling = False
            self.prefab_progress.setVisible(False)
            self.prefab_status_label.setText(self._prefab_note)
        self._sync_buttons()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.Resize and watched is self.prefab_table.viewport():
            self._fit_prefab_columns()
        return super().eventFilter(watched, event)

    def _fit_prefab_columns(self) -> None:
        """Share the list's width: the category as wide as it needs, the name before the speed values."""

        table = self.prefab_table
        width = table.viewport().width()
        if width <= 0:
            return
        header = table.horizontalHeader()
        wanted = [max(table.sizeHintForColumn(column), header.sectionSizeHint(column)) + 8 for column in range(3)]
        category = min(wanted[1], width * 3 // 10)
        rest = width - category
        values = min(wanted[2], rest * 2 // 5)
        for column, size in enumerate((rest - values, category, values)):
            header.resizeSection(column, max(size, 40))

    def _select_prefab_row(self, path: str) -> None:
        """Mark ``path``'s row without opening it again; no row when it is not listed."""

        table = self.prefab_table
        table.blockSignals(True)
        try:
            table.clearSelection()
            for row in range(table.rowCount()):
                if path and str(table.item(row, 0).data(_PATH_ROLE)) == path:
                    table.selectRow(row)
                    table.scrollToItem(table.item(row, 0), QAbstractItemView.ScrollHint.EnsureVisible)
                    break
        finally:
            table.blockSignals(False)

    def selected_prefab(self) -> str:
        rows = self.prefab_table.selectionModel().selectedRows() if self.prefab_table.selectionModel() else []
        if not rows:
            return ""
        item = self.prefab_table.item(rows[0].row(), 0)
        return str(item.data(_PATH_ROLE)) if item is not None else ""

    def _prefab_selected(self) -> None:
        path = self.selected_prefab()
        if path and path != self._prefab_path and self._open_prefab is not None:
            self.open_prefab(path)

    def open_prefab(self, path: str, *, discard: Optional[bool] = None) -> bool:
        """Open ``path`` beside the list; False when the open prefab's unsaved changes are kept.

        ``discard`` answers for those changes: True drops them, False keeps them, None asks.
        """

        if self._open_prefab is None:
            return False
        leave = self._may_leave_prefab() if discard is None else (discard or not self.prefab_has_unsaved_changes())
        if not leave:
            self._select_prefab_row(self._prefab_path)
            return False
        self._open_prefab(path)
        self._select_prefab_row(self._prefab_path)
        return True

    def prefab_has_unsaved_changes(self) -> bool:
        check = getattr(self.prefab_inspector, "has_unsaved_changes", None)
        return bool(check()) if callable(check) else False

    def _may_leave_prefab(self) -> bool:
        if not self.prefab_has_unsaved_changes():
            return True
        return bool(self._confirm_discard(self._prefab_path.rsplit("/", 1)[-1]))

    def _ask_discard(self, name: str) -> bool:
        answer = QMessageBox.question(self, TOOL_TITLE, f"Discard the unsaved changes to {name}?")
        return answer == QMessageBox.StandardButton.Yes

    def show_prefab_inspector(self, path: str, inspector: Optional[QWidget], *, note: str = "") -> None:
        """Show ``inspector`` beside the list for ``path``; None shows ``note`` instead."""

        old = self.prefab_inspector
        self.prefab_inspector = inspector
        self._prefab_path = path if inspector is not None else ""
        if inspector is not None:
            self.prefab_host.addWidget(inspector)
            self.prefab_host.setCurrentWidget(inspector)
        else:
            self.prefab_empty_detail.setText(note or "Search, then pick a prefab to see and scale its speed values here.")
            self.prefab_host.setCurrentIndex(0)
        if old is not None and old is not inspector:
            self.prefab_host.removeWidget(old)
            old.deleteLater()

    def state(self) -> dict[str, object]:
        """What the tab shows, for the speed.workspace tool."""

        chart = self._chart
        editor = getattr(self.game_table_panel, "editor", None)
        return {
            "page": self.current_page(),
            "loading": self.loading and not self.load_failed,
            "load_error": self.loading_detail.text() if self.load_failed else "",
            "waiting_for_set": self._pending_set,
            "characters": [character.name for character in self._characters],
            "set": chart.path if chart is not None else "",
            "set_label": chart.label if chart is not None else "",
            "factors": self.factors().to_data() if chart is not None else None,
            "linked": list(self.linked_paths()),
            "scope": self.scope(),
            "scope_sets": list(self.listed_sets()) if self.scope() == "listed" else [],
            "set_filter": self.set_filter_edit.text(),
            "presets": [{"key": preset.key, "label": preset.label} for preset in SPEED_PRESETS],
            "mod_title": self._mod_title,
            "mod_folder": self._mod_folder,
            "mod_charts": sorted(self._mod_charts),
            "checking_sets": self._batch,
            "can_export": self.export_button.isEnabled(),
            "review": self.review_text.toPlainText(),
            "prefab_category": self.prefab_category(),
            "prefab_searching": self._prefab_searching,
            "prefab_values": len(self._prefab_scalable),
            "prefab_scaling": self._prefab_scaling,
            "prefab_factor": float(self.prefab_batch_spin.value()),
            "prefab_status": self.prefab_status_label.text(),
            "prefabs": [str(self.prefab_table.item(row, 0).data(_PATH_ROLE))
                        for row in range(self.prefab_table.rowCount())],
            "prefab_categories": [str(self.prefab_category_combo.itemData(position) or "")
                                  for position in range(self.prefab_category_combo.count())],
            "prefab_open": self._prefab_path,
            "prefab_unsaved_changes": self.prefab_has_unsaved_changes(),
            "table": editor.current_table() if editor is not None else "",
            "table_loaded": editor.loaded_table() if editor is not None else "",
            "table_loading": bool(editor is not None and not editor.load.isEnabled()),
            "table_message": editor.message.text() if editor is not None else "",
            "table_changes": len(editor.edits()) if editor is not None else 0,
        }


def _short_member(member: str) -> str:
    """`CloudDensityVolumeComponent._cloudDriftSpeed` reads as `CloudDensityVolume.cloudDriftSpeed`."""

    owner, _, field = member.partition(".")
    owner = owner.removesuffix("Component")
    return f"{owner}.{field.lstrip('_')}" if field else owner


__all__ = ["SpeedPrefabsWorkspace", "TOOL_TITLE", "plan_summary"]
