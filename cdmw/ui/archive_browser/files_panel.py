"""Archive browser files panel construction."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
)

from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
from cdmw.ui.archive_browser.remote_finder_warmup import RemoteItemFinderWarmupController
from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge
from cdmw.ui.widgets import FlatSectionPanel, responsive_sidebar_bounds


class ArchiveFilesPanelMixin:
    """Build archive browser warmup and files panels."""

    def _build_archive_warmup_overlay(self, archive_tab_layout) -> None:
        self.archive_warmup_overlay = QFrame(self.archive_browser_tab)
        self.archive_warmup_overlay.setMinimumWidth(520)
        self.archive_warmup_overlay.setObjectName("ArchiveWarmupOverlay")
        archive_warmup_layout = QVBoxLayout(self.archive_warmup_overlay)
        archive_warmup_layout.setContentsMargins(16, 12, 16, 12)
        archive_warmup_layout.setSpacing(6)
        self.archive_warmup_title_label = QLabel("Preparing Archive Browser")
        self.archive_warmup_title_label.setObjectName("SectionTitle")
        self.archive_warmup_message_label = QLabel("")
        self.archive_warmup_message_label.setObjectName("HintLabel")
        self.archive_warmup_message_label.setWordWrap(True)
        self.archive_warmup_progress_bar = QProgressBar()
        self.archive_warmup_progress_bar.setTextVisible(True)
        self.archive_warmup_progress_bar.setRange(0, 0)
        self.archive_warmup_progress_bar.setFormat("Working...")
        archive_warmup_layout.addWidget(self.archive_warmup_title_label)
        archive_warmup_layout.addWidget(self.archive_warmup_message_label)
        archive_warmup_layout.addWidget(self.archive_warmup_progress_bar)
        self.archive_warmup_overlay.setVisible(False)
        archive_tab_layout.addWidget(self.archive_splitter, stretch=1)

    def _build_archive_files_panel(self) -> None:
        archive_files_group = FlatSectionPanel("Files")
        archive_files_min, _archive_files_pref, _archive_files_max = responsive_sidebar_bounds(self, role="narrow")
        self.archive_files_min_width = archive_files_min
        archive_files_group.setMinimumWidth(archive_files_min)
        archive_files_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.archive_files_group = archive_files_group
        archive_files_layout = archive_files_group.body_layout
        archive_files_layout.setSpacing(0)

        self.archive_tree = ArchiveBrowserTreeView(
            "No archive files loaded",
            "Scan archive packages to browse, preview, extract, and route files.",
        )
        self.archive_tree.setHeaderLabels(["Name", "Item Name", "Role / Type", "Size", "Comp", "Package", "State", "Path"])
        self.archive_tree.set_archive_providers(
            row_provider=self._archive_browser_row_payload,
            category_provider=self._archive_entry_category,
            category_sort_key=self._archive_category_sort_key,
        )
        selection = self.archive_backend_selection
        if selection.displays_v2 or selection.runs_shadow:
            self.archive_remote_bridge = ArchiveRemoteWindowBridge(
                self,
                display_v2=selection.displays_v2,
                shadow=selection.runs_shadow,
            )
            if selection.displays_v2:
                self.archive_item_finder_warmup_controller = RemoteItemFinderWarmupController(
                    self.archive_catalogue_service,
                    self.settings,
                    background_allowed=self._archive_browser_background_work_allowed,
                    parent=self,
                )
                self.archive_remote_bridge.backendFailed.connect(
                    self._handle_archive_backend_v2_failure
                )
                self.archive_remote_bridge.previewDependenciesReady.connect(
                    self._handle_archive_remote_preview_dependencies_ready
                )
                self.archive_remote_bridge.previewDependenciesFailed.connect(
                    self._handle_archive_remote_preview_dependencies_failed
                )
        self.archive_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_tree.setAlternatingRowColors(False)
        self.archive_tree.setRootIsDecorated(True)
        self.archive_tree.setUniformRowHeights(True)
        self.archive_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.archive_tree.setProperty("cdmw_disable_auto_column_fill", True)
        self.archive_tree.uiActivity.connect(self._note_archive_ui_activity)
        self.archive_scope_banner_label = QLabel("")
        self.archive_scope_banner_label.setObjectName("HintLabel")
        self.archive_scope_banner_label.setWordWrap(True)
        self.archive_scope_banner_label.setVisible(False)
        archive_files_layout.addWidget(self.archive_scope_banner_label)
        archive_header = self.archive_tree.header()
        archive_header.setStretchLastSection(False)
        archive_header.setSectionsClickable(True)
        archive_header.setSectionResizeMode(0, QHeaderView.Interactive)
        archive_header.setSectionResizeMode(1, QHeaderView.Interactive)
        archive_header.setSectionResizeMode(7, QHeaderView.Stretch)
        archive_header.setSectionsMovable(True)
        archive_header.setToolTip("Drag columns to reorder. Right-click the header to show, hide, or reset columns.")
        archive_header.setContextMenuPolicy(Qt.CustomContextMenu)
        archive_header.customContextMenuRequested.connect(self._show_archive_tree_header_context_menu)
        archive_header.sectionClicked.connect(self._handle_archive_tree_header_clicked)
        archive_header.sectionMoved.connect(self._handle_archive_tree_section_geometry_changed)
        archive_header.sectionResized.connect(self._handle_archive_tree_section_geometry_changed)
        with self._archive_tree_header_programmatic():
            for section in range(self.archive_tree.columnCount()):
                if section == 7:
                    archive_header.setSectionResizeMode(section, QHeaderView.Stretch)
                else:
                    archive_header.setSectionResizeMode(section, QHeaderView.Interactive)
            archive_header.resizeSection(0, 480)
            archive_header.resizeSection(1, 190)
            archive_header.resizeSection(2, 110)
            archive_header.resizeSection(3, 72)
            archive_header.resizeSection(4, 130)
            archive_header.resizeSection(5, 130)
            archive_header.resizeSection(6, 122)
            archive_header.resizeSection(7, 360)
            self._apply_archive_tree_header_settings()
            for section in range(self.archive_tree.columnCount()):
                archive_header.setSectionResizeMode(section, QHeaderView.Interactive)
        archive_files_layout.addWidget(self.archive_tree)
        self.archive_splitter.addWidget(archive_files_group)
