"""Speed & Prefabs (experimental): the Authoring tab for how fast things play.

Animation speed works on action charts: pick a character and a set (one chart), set a
factor for the whole set, per kind of move or per move, review what changes and export.
Prefabs lists prefabs that carry speed values (effects, cameras, moving objects, NPC
routes, weather) and shows the chosen one in the Prefab Inspector beside the list. Game
tables holds Edit Game Table Values for the two speed tables.

The tab does no archive work itself: the Archive Browser passes the calls in, so it can
be tested with fakes. Writing speeds into the running game stays in Crimson Live Edit.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
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
    SpeedChart,
    SpeedCharacter,
    SpeedFactors,
    SpeedPlan,
)

TOOL_TITLE = "Speed & Prefabs"
_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_MOVE_COLUMNS = ("Move", "Kind", "Seconds", "Windows", "Factor")


def _spin(name: str, value: float = 1.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setObjectName(name)
    box.setRange(MIN_FACTOR, MAX_FACTOR)
    box.setSingleStep(0.1)
    box.setDecimals(2)
    box.setSuffix("x")
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setMaximumWidth(120)
    return box


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
        open_chart: Optional[Callable[[str], None]] = None,
        prefab_search: Optional[Callable[[str], None]] = None,
        open_prefab: Optional[Callable[[str], None]] = None,
        prefab_categories: Sequence[tuple[str, str]] = (),
        open_game_table: Optional[Callable[[str], None]] = None,
        game_table_panel: Optional[QWidget] = None,
        retry_load: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("speedPrefabsWorkspace")
        self._characters = tuple(characters)
        self._load_set = load_set
        self._plan = plan
        self._linked_of = linked_of
        self._export = export
        self._open_chart = open_chart
        self._prefab_search = prefab_search
        self._open_prefab = open_prefab
        self._open_game_table = open_game_table
        self._retry_load = retry_load
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
                self._open_table(next(iter(self.table_buttons)))

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
        return self.loading and self.retry_button.isVisibleTo(self)

    @property
    def loading(self) -> bool:
        return self.stack.currentIndex() == 0

    def show_loading(self, detail: str = "") -> None:
        """Show the loading page while the caller reads the charts on a worker."""

        self.loading_title.setText("Reading the game's action charts…")
        self.loading_bar.setVisible(True)
        self.retry_button.setVisible(False)
        if detail:
            self.loading_detail.setText(detail)
        self.stack.setCurrentIndex(0)
        self._sync_buttons()

    def show_load_error(self, message: str) -> None:
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

        self._characters = tuple(characters)
        self._fill_characters()
        self.stack.setCurrentIndex(1)
        self._sync_buttons()
        pending, self._pending_set = self._pending_set, ""
        if pending:
            self.select_set(pending)
        elif self.set_list.currentItem() is None:
            first = next((row for row in range(self.set_list.count()) if not self.set_list.item(row).isHidden()), -1)
            if first >= 0:
                self.set_list.setCurrentRow(first)

    def open_set(self, path: str) -> None:
        """Show the animation page on ``path``; while loading, select it once the sets are read."""

        self.show_page("animation")
        if not path:
            return
        if self.loading:
            self._pending_set = path
        else:
            self.select_set(path)

    # --- building -----------------------------------------------------------------------

    def _build_animation_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("speedAnimationPage")
        row = QHBoxLayout(page)
        row.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        row.addWidget(splitter)

        left = QGroupBox("Set")
        left.setToolTip("A set is one action chart: the moves of one weapon or stance.")
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(6)
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
        left.setMinimumWidth(240)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        heading_box = QWidget()
        heading = QVBoxLayout(heading_box)
        heading.setContentsMargins(0, 0, 0, 0)
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
        self.served_label.setVisible(False)
        right_layout.addWidget(self.served_label)

        factors = QGroupBox("Speed factors")
        factors.setToolTip("A kind's factor applies to every move of that kind; a move's own factor wins over it.")
        grid = QGridLayout(factors)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        whole = QLabel("Whole set:")
        whole.setToolTip("ActionSpeedRate: scales every move in this set.")
        grid.addWidget(whole, 0, 0)
        self.set_factor_spin = _spin("speedSetFactorSpin")
        self.set_factor_spin.setToolTip("ActionSpeedRate: scales every move in this set.")
        self.set_factor_spin.valueChanged.connect(lambda _value: self._changed())
        grid.addWidget(self.set_factor_spin, 0, 1)
        self.kind_spins: dict[str, QDoubleSpinBox] = {}
        self.kind_labels: dict[str, QLabel] = {}
        for number, (kind, label) in enumerate(KIND_LABELS.items(), start=1):
            text = QLabel(label + ":")
            spin = _spin(f"speedKindFactor_{kind}")
            spin.valueChanged.connect(lambda _value: self._kind_changed())
            line, column = number // 3, (number % 3) * 3
            grid.addWidget(text, line, column)
            grid.addWidget(spin, line, column + 1)
            self.kind_spins[kind] = spin
            self.kind_labels[kind] = text
        for spacer in (2, 5):
            grid.setColumnMinimumWidth(spacer, 18)
        grid.setColumnStretch(8, 1)
        right_layout.addWidget(factors)

        moves = QGroupBox("Moves")
        moves_layout = QVBoxLayout(moves)
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
        header.resizeSection(len(_MOVE_COLUMNS) - 1, 112)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.verticalHeader().setDefaultSectionSize(30)
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
        self.review_text = QPlainTextEdit()
        self.review_text.setObjectName("speedReviewText")
        self.review_text.setReadOnly(True)
        self.review_text.setMaximumHeight(72)
        review_layout.addWidget(self.review_text)
        right_layout.addWidget(review)

        buttons = QHBoxLayout()
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
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.open_chart_button)
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
        splitter.setHandleWidth(10)
        row.addWidget(splitter)

        left = QGroupBox("Find prefabs")
        left.setToolTip("Speeds for effects, scene cameras, moving objects, NPC routes and weather. Not the player's "
                        "moves. Prefab speed edits have not been tested in game.")
        layout = QVBoxLayout(left)
        layout.setSpacing(6)
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
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.prefab_table.verticalHeader().setVisible(False)
        self.prefab_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.prefab_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.prefab_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.prefab_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.prefab_table.setWordWrap(False)
        self.prefab_table.itemSelectionChanged.connect(self._prefab_selected)
        layout.addWidget(self.prefab_table, 1)
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
        splitter.addWidget(self.prefab_host)
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
        choose.setSpacing(6)
        self.table_buttons: dict[str, QPushButton] = {}
        for table, label, detail in (
                ("aimovespeedinfo", "AI movement speeds", "Move, minimum and turn speed of each AI move type."),
                ("gimmickinfo", "Pushed objects", "How fast objects move when pushed.")):
            button = QPushButton(label)
            button.setObjectName(f"speedTableButton_{table}")
            button.setCheckable(True)
            button.setToolTip(detail + " Units are not known, and these edits have not been tested in game.")
            button.setEnabled(self._open_game_table is not None)
            button.clicked.connect(lambda _checked=False, name=table: self._open_table(name))
            choose.addWidget(button)
            self.table_buttons[table] = button
        choose.addStretch(1)
        layout.addLayout(choose)
        if self.game_table_panel is not None:
            layout.addWidget(self.game_table_panel, 1)
        else:
            layout.addWidget(_hint("Game tables open in Edit Game Table Values, which writes a DMM mod."))
            layout.addStretch(1)
        return page

    def _open_table(self, table: str) -> None:
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
            row.setToolTip(item.path)
            self.set_list.addItem(row)
        self.set_list.blockSignals(False)
        self._filter_sets()

    def _filter_sets(self) -> None:
        text = self.set_filter_edit.text().strip().lower()
        for number in range(self.set_list.count()):
            item = self.set_list.item(number)
            shown = not text or text in item.text().lower() or text in str(item.data(_PATH_ROLE)).lower()
            item.setHidden(not shown)

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
            self.set_factor_spin.setValue(float(chart.factors.set))
            kinds = {kind for kind, _label, _count in chart.kinds()}
            counts = {kind: count for kind, _label, count in chart.kinds()}
            for kind, spin in self.kind_spins.items():
                spin.setValue(float(chart.factors.kinds.get(kind, 1.0)))
                spin.setEnabled(kind in kinds)
                self.kind_labels[kind].setText(f"{KIND_LABELS[kind]} ({counts.get(kind, 0)}):")
            self._move_factors = {clip.lower(): float(value) for clip, value in chart.factors.moves.items()}
            self._fill_moves()
            included = [path for path, inside in self._linked if inside]
            others = [path for path, inside in self._linked if not inside]
            self.linked_checkbox.setEnabled(bool(self._linked))
            self.linked_checkbox.setChecked(bool(included))
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
            spin.setEnabled(move.windows > 0)
            spin.valueChanged.connect(lambda value, clip=move.clip: self._move_changed(clip, value))
            self.move_table.setCellWidget(row, 4, spin)
        self._filter_moves()

    def _shown_factor(self, clip: str, kind: str) -> float:
        return self._move_factors.get(clip.lower(), float(self.kind_spins[kind].value()))

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
        if abs(float(value) - float(self.kind_spins[kind].value())) < 1e-6:
            self._move_factors.pop(clip.lower(), None)
        else:
            self._move_factors[clip.lower()] = float(value)
        self._changed()

    def _kind_changed(self) -> None:
        if self._filling or self._chart is None:
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
        return SpeedFactors(round(float(self.set_factor_spin.value()), 2), kinds, moves)

    def linked_paths(self) -> tuple[str, ...]:
        if not self.linked_checkbox.isChecked():
            return ()
        return tuple(path for path, inside in self._linked if inside)

    def reset_factors(self) -> None:
        self._filling = True
        try:
            self.set_factor_spin.setValue(1.0)
            for spin in self.kind_spins.values():
                spin.setValue(1.0)
            self._move_factors.clear()
            self._fill_moves()
        finally:
            self._filling = False
        self._changed()

    def _changed(self) -> None:
        if self._filling:
            return
        self._sync_buttons()
        self._review_timer.start()

    def refresh_review(self) -> None:
        self._review_timer.stop()
        if self._chart is None:
            self.review_text.setPlainText("")
            self.last_plans = ()
            return
        try:
            self.last_plans = tuple(self._plan(self._chart.path, self.factors(), self.linked_paths()))
            self.review_text.setPlainText(plan_summary(self.last_plans))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.last_plans = ()
            self.review_text.setPlainText(f"These factors cannot be applied: {exc}")
        self._sync_buttons()

    @property
    def has_changes(self) -> bool:
        return self._chart is not None and not self.factors().is_identity

    def _sync_buttons(self) -> None:
        chart_open = self._chart is not None
        # A set back at 1x everywhere can still be exported when it came from a mod: that takes it out.
        self.export_button.setEnabled(chart_open and self._export is not None
                                      and (self.has_changes or bool(self._chart and self._chart.mod)))
        self.export_button.setToolTip("" if self.export_button.isEnabled()
                                      else "Set a factor other than 1x first.")
        self.reset_button.setEnabled(chart_open)
        self.open_chart_button.setEnabled(chart_open and self._open_chart is not None)
        if hasattr(self, "prefab_search_button"):
            ready = self._prefab_search is not None and not self.loading and not self._prefab_searching
            self.prefab_search_button.setEnabled(ready)
            self.prefab_search_button.setToolTip(
                "Waiting for the game's file index." if self.loading and not self.load_failed
                else "The first search reads every prefab and takes a few minutes; later searches are quick.")

    def _export_clicked(self) -> None:
        if self._chart is not None and self._export is not None:
            self.refresh_review()
            self._export(self._chart.path, self.factors(), self.linked_paths())

    def _open_in_editor(self) -> None:
        if self._chart is not None and self._open_chart is not None:
            self._open_chart(self._chart.path)

    # --- prefabs ------------------------------------------------------------------------

    def prefab_category(self) -> str:
        return str(self.prefab_category_combo.currentData() or "")

    def _search_prefabs(self) -> None:
        if self._prefab_search is None:
            return
        self._prefab_searching = True
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
        """Rows with path, category label and members; called by the caller's search worker."""

        self._prefab_searching = False
        self.prefab_progress.setVisible(False)
        self.prefab_table.setRowCount(len(rows))
        for number, row in enumerate(rows):
            full = str(row.get("path", ""))
            path = QTableWidgetItem(full.rsplit("/", 1)[-1])
            path.setData(_PATH_ROLE, full)
            path.setToolTip(full)
            self.prefab_table.setItem(number, 0, path)
            self.prefab_table.setItem(number, 1, QTableWidgetItem(str(row.get("category_label", row.get("category", "")))))
            members = [str(m) for m in row.get("members", ())]
            cell = QTableWidgetItem(", ".join(_short_member(m) for m in members))
            cell.setToolTip("\n".join(members))
            self.prefab_table.setItem(number, 2, cell)
        self.prefab_status_label.setText(note or f"{len(rows):,} prefab(s) found.")
        self._sync_buttons()

    def selected_prefab(self) -> str:
        rows = self.prefab_table.selectionModel().selectedRows() if self.prefab_table.selectionModel() else []
        if not rows:
            return ""
        item = self.prefab_table.item(rows[0].row(), 0)
        return str(item.data(_PATH_ROLE)) if item is not None else ""

    def _prefab_selected(self) -> None:
        path = self.selected_prefab()
        if path and path != self._prefab_path and self._open_prefab is not None:
            self._open_prefab(path)

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
            "characters": [character.name for character in self._characters],
            "set": chart.path if chart is not None else "",
            "set_label": chart.label if chart is not None else "",
            "factors": self.factors().to_data() if chart is not None else None,
            "linked": list(self.linked_paths()),
            "can_export": self.export_button.isEnabled(),
            "review": self.review_text.toPlainText(),
            "prefab_category": self.prefab_category(),
            "prefab_searching": self._prefab_searching,
            "prefab_status": self.prefab_status_label.text(),
            "prefabs": [str(self.prefab_table.item(row, 0).data(_PATH_ROLE))
                        for row in range(self.prefab_table.rowCount())],
            "prefab_open": self._prefab_path,
            "table": editor.current_table() if editor is not None else "",
            "table_loaded": editor.loaded_table() if editor is not None else "",
        }


def _short_member(member: str) -> str:
    """`CloudDensityVolumeComponent._cloudDriftSpeed` reads as `CloudDensityVolume.cloudDriftSpeed`."""

    owner, _, field = member.partition(".")
    owner = owner.removesuffix("Component")
    return f"{owner}.{field.lstrip('_')}" if field else owner


__all__ = ["SpeedPrefabsWorkspace", "TOOL_TITLE", "plan_summary"]
