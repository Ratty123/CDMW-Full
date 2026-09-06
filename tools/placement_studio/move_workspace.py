"""Layout and preparation lifecycle for the unified move workspace."""
from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSplitter,
    QTableView, QLineEdit, QHeaderView, QAbstractItemView, QLabel, QPushButton,
    QPlainTextEdit, QDialogButtonBox, QCheckBox, QComboBox, QSizePolicy, QStackedWidget)

from .background import LatestTask
from .move_file_model import MoveFileModel, DonorDelegate
from .move_preview import MovePreview
from cdmw.services.active_ui_translation import translate_active_ui_text as tr


def build_workspace(dialog, parts):
    equipment = dialog._build_equipment_page(parts)
    placement = dialog._build_placement_page()
    animation_options = dialog._build_animation_page()
    dialog._equipment_controls = equipment
    dialog._placement_controls = placement
    options = QWidget()
    settings = QVBoxLayout(options)
    settings.setContentsMargins(0, 0, 0, 0)
    for widget in (equipment, placement, animation_options):
        settings.addWidget(widget)
        for label in widget.findChildren(QLabel):
            if label.wordWrap():
                label.setMinimumWidth(0)
                label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for box in widget.findChildren(QComboBox):
            box.setMinimumContentsLength(12)
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
    settings.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(options)
    scroll.setMinimumWidth(290)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    dialog._preview = MovePreview()
    preview_panel = QWidget()
    preview_layout = QVBoxLayout(preview_panel)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preparation = QHBoxLayout()
    dialog._preview_placement = QPushButton("Prepare preview")
    dialog._preview_placement.clicked.connect(dialog._prepare_selection)
    preparation.addWidget(dialog._preview_placement)
    dialog._cancel_preparation = QPushButton("Cancel preparation")
    dialog._cancel_preparation.clicked.connect(dialog._cancel_prepare)
    dialog._cancel_preparation.hide()
    preparation.addWidget(dialog._cancel_preparation)
    dialog._check_summary = QLabel("Checks: Unverified — prepare the complete selection")
    dialog._check_summary.setWordWrap(True)
    dialog._check_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    preparation.addWidget(dialog._check_summary, 1)
    preview_layout.addLayout(preparation)
    preview_layout.addWidget(dialog._preview, 1)
    dialog._file_model = MoveFileModel(dialog)
    dialog._file_proxy = QSortFilterProxyModel(dialog)
    dialog._file_proxy.setSourceModel(dialog._file_model)
    dialog._file_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    dialog._file_proxy.setFilterKeyColumn(-1)
    dialog._file_table = QTableView()
    dialog._file_table.setObjectName("PlacementReplacementFiles")
    dialog._file_table.setModel(dialog._file_proxy)
    dialog._file_table.setItemDelegateForColumn(2, DonorDelegate(dialog._file_table))
    dialog._file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    dialog._file_table.setSelectionMode(QAbstractItemView.SingleSelection)
    dialog._file_table.setSortingEnabled(True)
    dialog._file_table.verticalHeader().hide()
    header = dialog._file_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionResizeMode(0, QHeaderView.Fixed)
    for column, width in enumerate((32, 180, 180, 135, 95, 55, 100, 110)):
        dialog._file_table.setColumnWidth(column, width)
    for column in (1, 2):
        header.setSectionResizeMode(column, QHeaderView.Stretch)
    # Keep validity next to selection even at the smallest supported window size.
    header.moveSection(header.visualIndex(6), 1)
    header.moveSection(header.visualIndex(5), 4)
    dialog._file_table.setTextElideMode(Qt.ElideMiddle)
    dialog._file_model.selection_changed.connect(dialog._refresh)
    dialog._file_table.doubleClicked.connect(lambda _i: dialog._watch_selected())

    files = QWidget()
    layout = QVBoxLayout(files)
    layout.setContentsMargins(0, 0, 0, 0)
    filter_row = QHBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText("Filter target, replacement, rig or check status")
    search.setClearButtonEnabled(True)
    search.textChanged.connect(dialog._file_proxy.setFilterFixedString)
    filter_row.addWidget(search, 1)
    for label, value in (("Select all", True), ("Select none", False)):
        button = QPushButton(label)
        button.clicked.connect(lambda _c=False, v=value: dialog._set_all(v))
        filter_row.addWidget(button)
    dialog._preview_animation = QPushButton("Watch selected")
    dialog._preview_animation.clicked.connect(dialog._watch_selected)
    filter_row.addWidget(dialog._preview_animation)
    layout.addLayout(filter_row)
    layout.addWidget(dialog._file_table, 1)
    dialog._count_label = QLabel()
    layout.addWidget(dialog._count_label)
    dialog._risk_label = QLabel()
    dialog._risk_label.setWordWrap(True)
    layout.addWidget(dialog._risk_label)

    dialog._review_view = QPlainTextEdit()
    dialog._review_view.setReadOnly(True)
    file_pages = QStackedWidget()
    file_pages.addWidget(files)
    file_pages.addWidget(dialog._review_view)

    right = QSplitter(Qt.Vertical)
    right.setChildrenCollapsible(False)
    right.addWidget(preview_panel)
    right.addWidget(file_pages)
    right.setStretchFactor(0, 1)
    right.setStretchFactor(1, 1)
    right.setSizes([460, 300])
    columns = QSplitter()
    columns.setChildrenCollapsible(False)
    columns.addWidget(scroll)
    columns.addWidget(right)
    columns.setStretchFactor(1, 1)
    columns.setSizes([340, 1000])

    dialog._blocker_label = QLabel()
    dialog._blocker_label.setWordWrap(True)
    actions = QHBoxLayout()
    dialog._show_files = QPushButton("Details and exact files")
    dialog._show_files.setCheckable(True)
    dialog._show_files.toggled.connect(
        lambda checked: file_pages.setCurrentWidget(dialog._review_view if checked else files))
    actions.addWidget(dialog._show_files)
    reset = QPushButton("Reset selection")
    reset.clicked.connect(dialog._reset)
    actions.addWidget(reset)
    actions.addStretch(1)
    dialog._play_after = QCheckBox("Play after applying")
    dialog._play_after.setChecked(True)
    actions.addWidget(dialog._play_after)
    dialog._buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
    dialog._accept = dialog._buttons.addButton("Prepare changes first", QDialogButtonBox.AcceptRole)
    dialog._accept.clicked.connect(dialog._on_accept_clicked)
    dialog._buttons.rejected.connect(dialog.reject)
    actions.addWidget(dialog._buttons)
    layout = QVBoxLayout(dialog)
    layout.addWidget(dialog._banner())
    layout.addWidget(columns, 1)
    layout.addWidget(dialog._blocker_label)
    layout.addLayout(actions)
    dialog._prepare_task = LatestTask(dialog)
    dialog._prepare_task.ready.connect(dialog._prepared_ready)
    dialog._prepare_task.progress.connect(
        lambda a, b: dialog._check_summary.setText(f"Preparing and analysing files: {a}/{b}"))
    dialog._freshness_task = LatestTask(dialog)
    dialog._freshness_task.ready.connect(dialog._freshness_ready)
    dialog._freshness_timer = QTimer(dialog)
    dialog._freshness_timer.setInterval(2000)
    dialog._freshness_timer.timeout.connect(dialog._check_freshness)
    dialog._freshness_timer.start()


class WorkspaceLifecycle:
    def _check_freshness(self):
        scene = self._prepared_scene
        if scene is None or self._freshness_task.busy:
            return
        parent = self.parent()
        edits = getattr(parent, "_edits", None)
        if edits is not None and edits.capture() != scene.prepared.snapshot:
            self._invalidate_preparation()
            self._check_summary.setText("Session changed; prepare again")
            return
        def work(cancelled, _progress):
            from pathlib import Path
            from .corpus import package_signature
            prepared = scene.prepared
            current = []
            for path, _, _ in prepared.source_identity:
                if cancelled():
                    return None
                try:
                    stat = Path(path).stat()
                    current.append((path,stat.st_size,stat.st_mtime_ns))
                except OSError:
                    return scene, False
            same = tuple(current) == prepared.source_identity
            if same and prepared.source_root:
                same = tuple(tuple(r) for r in package_signature(Path(prepared.source_root))) == prepared.root_identity
            return scene, same
        self._freshness_task.submit(work)

    def _freshness_ready(self, result, error):
        if error and self._prepared_scene is not None:
            self._invalidate_preparation()
            self._check_summary.setText(f'Checks invalidated: {error}')
            return
        if result is None or self._prepared_scene is not result[0]:
            return
        if error or not result[1]:
            self._invalidate_preparation()
            self._check_summary.setText("Source files changed; refresh the source index and prepare again")
            parent = self.parent()
            if parent is not None and hasattr(parent, "_ensure_clip_index"):
                parent._motion_relationships = None
                parent._stop_clip_index()
                parent._clip_index_started = False
                parent._ensure_clip_index()
                self._index_pending = True
                timer = QTimer(self)
                timer.setInterval(100)
                def updated():
                    if getattr(parent,"_clip_scan",None) is None:
                        timer.stop()
                        timer.deleteLater()
                        self._index_pending = False
                        self._reload_clips()
                        self._refresh()
                timer.timeout.connect(updated)
                timer.start()

    def _invalidate_preparation(self):
        self._prepared_scene = None
        self._accept.setEnabled(False)
        self._prepare_task.cancel()
        self._freshness_task.cancel()
        self._file_model.set_prepared(None)
        self._file_model.set_recommendations(())
        self._check_summary.setText("Checks: Unverified — selection changed; prepare again")
        if self._preview.scene is not None:
            self._preview.mark_stale("Previous preview · current selection is not prepared")
        self._cancel_preparation.hide()

    def _prepare_selection(self):
        self._freshness_task.cancel()
        if getattr(self, "_index_pending", False):
            self._check_summary.setText("Animation indexing is still running")
            return
        if self._plan is None or self._prepare_for is None:
            self._check_summary.setText("Preparation unavailable: no source session")
            return
        self._prepared_scene = None
        self._file_model.set_prepared(None)
        if self._preview.scene is not None:
            self._preview.mark_stale("Previous preview · preparing current selection")
        self._accept.setEnabled(False)
        self._check_summary.setText("Preparing complete selection…")
        self._cancel_preparation.show()
        try:
            work = self._prepare_for(self._plan)
        except Exception as error:
            self._prepared_ready(None, str(error))
            return
        self._prepare_task.submit(work)

    def _cancel_prepare(self):
        self._invalidate_preparation()
        self._check_summary.setText("Preparation cancelled; nothing was changed")

    def _prepared_ready(self, scene, error):
        self._cancel_preparation.hide()
        if error or scene is None:
            self._check_summary.setText(f"Blocked: {error or 'preparation cancelled'}")
            self._accept.setEnabled(False)
            return
        if self._plan is None or scene.prepared.plan.request != self._plan.request:
            return
        self._prepared_scene = scene
        parent = self.parent()
        if parent is not None and scene.relationships is not None:
            parent._motion_relationships = scene.relationships
        self._file_model.set_prepared(scene.prepared)
        self._file_model.set_recommendations(scene.candidates)
        self._preview.set_scene(scene)
        if getattr(self, "_pending_watch", ""):
            self._preview.watch(self._pending_watch)
            self._pending_watch = ""
        states = {}
        for check in scene.prepared.checks:
            states[check.status] = states.get(check.status, 0) + 1
        self._check_summary.setText(tr(f"Passed: {states.get('Passed',0)} · Warning: {states.get('Warning',0)} · Unverified: {states.get('Unverified',0)} · Blocked: {states.get('Blocked',0)}"))
        changed = len(scene.prepared.changed_files)
        unchanged = len(scene.prepared.files) - changed
        self._count_label.setText(tr(f"{changed} files will change · {unchanged} identical selections excluded"))
        self._refresh_review(self._plan)
        self._accept.setText(tr(f"Apply {changed} file changes"))
        self._accept.setEnabled(changed > 0 and not scene.prepared.blocked)

    def prepared(self):
        return self._prepared_scene.prepared if self._prepared_scene else None

    def done(self, result):
        self._freshness_timer.stop()
        self._freshness_task.shutdown()
        self._prepare_task.shutdown()
        self._preview.stop()
        super().done(result)
