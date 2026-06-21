"""Archive browser asset-family splitter and column layout helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
)

from cdmw.ui.widgets import EmptyStateTreeWidget, make_tree_columns_persistent
from cdmw.ui.shell.responsiveness_controller import TreeHorizontalWheelGuard


class ArchiveAssetFamilyLayoutMixin:
    """Layout helpers for the archive preview asset-family pane."""

    def _build_archive_texture_references_panel(self) -> None:
        self.archive_texture_refs_group = QGroupBox("Referenced Files")
        self.archive_texture_refs_group.setVisible(False)
        self.archive_texture_refs_group.setMinimumWidth(320)
        self.archive_texture_refs_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        archive_texture_refs_layout = QVBoxLayout(self.archive_texture_refs_group)
        archive_texture_refs_layout.setContentsMargins(10, 10, 10, 10)
        archive_texture_refs_layout.setSpacing(8)
        self.archive_asset_family_summary_label = QLabel("")
        self.archive_asset_family_summary_label.setObjectName("HintLabel")
        self.archive_asset_family_summary_label.setWordWrap(True)
        self.archive_asset_family_summary_label.setVisible(False)
        archive_texture_refs_layout.addWidget(self.archive_asset_family_summary_label)
        self.archive_asset_map_tabs = QTabWidget()
        self.archive_asset_map_tree = EmptyStateTreeWidget(
            "No asset family",
            "Open a model-like preview to see recovered model, material, texture, HKX, meshinfo, prefab, rig, and animation links.",
        )
        self.archive_asset_map_tree.setColumnCount(5)
        self.archive_asset_map_tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])
        self.archive_asset_map_tree.setRootIsDecorated(True)
        self.archive_asset_map_tree.setAlternatingRowColors(True)
        self.archive_asset_map_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_asset_map_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_asset_map_tree.setUniformRowHeights(True)
        self.archive_asset_map_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive_asset_map_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.archive_asset_uses_tree = EmptyStateTreeWidget(
            "No outgoing links",
            "Uses shows files this selected entry directly or heuristically references.",
        )
        self.archive_asset_uses_tree.setColumnCount(5)
        self.archive_asset_uses_tree.setHeaderLabels(["File", "Role", "Status", "Confidence", "Why"])
        self.archive_asset_uses_tree.setRootIsDecorated(True)
        self.archive_asset_uses_tree.setAlternatingRowColors(True)
        self.archive_asset_uses_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_asset_uses_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_asset_uses_tree.setUniformRowHeights(True)
        self.archive_asset_uses_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive_asset_uses_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.archive_asset_used_by_tree = EmptyStateTreeWidget(
            "No known incoming links",
            "Used By is limited to current indexes and cached relationship evidence; it does not rescan every archive file on click.",
        )
        self.archive_asset_used_by_tree.setColumnCount(5)
        self.archive_asset_used_by_tree.setHeaderLabels(["File", "Role", "Status", "Confidence", "Why"])
        self.archive_asset_used_by_tree.setRootIsDecorated(True)
        self.archive_asset_used_by_tree.setAlternatingRowColors(True)
        self.archive_asset_used_by_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_asset_used_by_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_asset_used_by_tree.setUniformRowHeights(True)
        self.archive_asset_used_by_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive_asset_used_by_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.archive_asset_placement_tree = EmptyStateTreeWidget(
            "No placement chain",
            "Prefab/socket placement evidence has not been recovered for this file. Context skeleton display is visual only until a socket chain is found.",
        )
        self.archive_asset_placement_tree.setColumnCount(4)
        self.archive_asset_placement_tree.setHeaderLabels(["Mode / Link", "Target", "Evidence", "Why"])
        self.archive_asset_placement_tree.setRootIsDecorated(True)
        self.archive_asset_placement_tree.setAlternatingRowColors(True)
        self.archive_asset_placement_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.archive_asset_placement_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_asset_placement_tree.setUniformRowHeights(True)
        self.archive_asset_placement_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive_asset_placement_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.archive_texture_refs_tree = EmptyStateTreeWidget(
            "No referenced files",
            "Select a model or material entry to inspect related sidecars, textures, and companion files.",
        )
        self.archive_texture_refs_tree.setColumnCount(8)
        self.archive_texture_refs_tree.setHeaderLabels(
            ["Reference", "Status", "Part / Material", "Slot", "Visual", "Archive Path", "Package", "Uses"]
        )
        self.archive_texture_refs_tree.setRootIsDecorated(False)
        self.archive_texture_refs_tree.setAlternatingRowColors(True)
        self.archive_texture_refs_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_texture_refs_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_texture_refs_tree.setUniformRowHeights(True)
        self.archive_texture_refs_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.archive_texture_refs_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.archive_texture_refs_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        texture_refs_header = self.archive_texture_refs_tree.header()
        texture_refs_header.setStretchLastSection(False)
        texture_refs_header.setMinimumSectionSize(56)
        texture_refs_header.setSectionResizeMode(0, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(1, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(2, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(3, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(4, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(5, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(6, QHeaderView.Interactive)
        texture_refs_header.setSectionResizeMode(7, QHeaderView.Fixed)
        make_tree_columns_persistent(
            self.archive_texture_refs_tree,
            self.settings,
            "main/archive_texture_refs",
            minimum_width=56,
            save_callback=self.schedule_settings_save,
        )
        self._install_tree_horizontal_wheel_guard(self.archive_texture_refs_tree)
        for tree in (
            self.archive_asset_map_tree,
            self.archive_asset_uses_tree,
            self.archive_asset_used_by_tree,
            self.archive_asset_placement_tree,
        ):
            self._install_tree_horizontal_wheel_guard(tree)
            tree.setContextMenuPolicy(Qt.CustomContextMenu)
            header = tree.header()
            header.setStretchLastSection(False)
            header.setMinimumSectionSize(56)
            column_count = max(0, tree.columnCount())
            for column in range(max(0, column_count - 1)):
                header.setSectionResizeMode(column, QHeaderView.Interactive)
            if column_count:
                header.setSectionResizeMode(column_count - 1, QHeaderView.Stretch)
        self.archive_asset_map_tabs.addTab(self.archive_asset_map_tree, "Asset Family")
        self.archive_asset_map_tabs.addTab(self.archive_asset_uses_tree, "Uses")
        self.archive_asset_map_tabs.addTab(self.archive_asset_used_by_tree, "Used By")
        self.archive_asset_map_tabs.addTab(self.archive_asset_placement_tree, "Placement")
        self.archive_asset_map_tabs.addTab(self.archive_texture_refs_tree, "Raw Table")
        archive_texture_refs_layout.addWidget(self.archive_asset_map_tabs)
        archive_texture_actions_layout = QVBoxLayout()
        archive_texture_actions_layout.setSpacing(6)
        archive_texture_actions_grid = QGridLayout()
        archive_texture_actions_grid.setHorizontalSpacing(8)
        archive_texture_actions_grid.setVerticalSpacing(6)
        self.archive_texture_open_button = QPushButton("Preview Row")
        self.archive_texture_open_button.setToolTip("Open the selected Asset Family row in a referenced-file preview window.")
        self.archive_texture_edit_hkx_button = QPushButton("Edit Row HKX...")
        self.archive_texture_edit_hkx_button.setToolTip("Edit the selected Asset Family row when it is an HKX/HKT physics file.")
        self.archive_texture_scope_selected_button = QPushButton("Show Selected Rows")
        self.archive_texture_scope_selected_button.setToolTip("Filter Archive Files to the selected resolved Asset Family rows.")
        self.archive_texture_scope_all_button = QPushButton("Filter to Family")
        self.archive_texture_scope_all_button.setToolTip("Filter Archive Files to the required/recommended files in this Asset Family.")
        self.archive_texture_export_button = QPushButton("Export Selected Rows...")
        self.archive_texture_export_button.setToolTip("Export the selected resolved Asset Family rows to a folder.")
        self.archive_texture_export_all_button = QPushButton("Export Raw References...")
        self.archive_texture_export_all_button.setToolTip(
            "Export every resolved raw referenced-file row. Use Export Family for the curated Asset Family package."
        )
        self.archive_texture_export_asset_set_button = QPushButton("Export Family...")
        self.archive_texture_export_asset_set_button.setToolTip(
            "Choose which required/recommended Asset Family files to export, with optional hints."
        )
        self.archive_texture_smart_actions_button = QPushButton("Family Actions")
        self.archive_texture_smart_actions_button.setToolTip("Open role-aware actions for the current archive file and its Asset Family.")
        self.archive_texture_edit_material_button = QPushButton("Edit Row Material...")
        self.archive_texture_edit_material_button.setToolTip(
            "Edit the selected Asset Family row when it is a material sidecar."
        )
        for button in (
            self.archive_texture_open_button,
            self.archive_texture_edit_hkx_button,
            self.archive_texture_scope_selected_button,
            self.archive_texture_scope_all_button,
            self.archive_texture_export_button,
            self.archive_texture_export_all_button,
            self.archive_texture_export_asset_set_button,
            self.archive_texture_smart_actions_button,
            self.archive_texture_edit_material_button,
        ):
            button.setEnabled(False)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        archive_texture_actions_grid.addWidget(self.archive_texture_open_button, 0, 0)
        archive_texture_actions_grid.addWidget(self.archive_texture_edit_hkx_button, 0, 1)
        archive_texture_actions_grid.addWidget(self.archive_texture_edit_material_button, 1, 0)
        archive_texture_actions_grid.addWidget(self.archive_texture_export_button, 1, 1)
        archive_texture_actions_grid.addWidget(self.archive_texture_scope_selected_button, 2, 0)
        archive_texture_actions_grid.addWidget(self.archive_texture_scope_all_button, 2, 1)
        archive_texture_actions_grid.addWidget(self.archive_texture_smart_actions_button, 3, 0)
        archive_texture_actions_grid.addWidget(self.archive_texture_export_asset_set_button, 3, 1)
        archive_texture_actions_grid.addWidget(self.archive_texture_export_all_button, 4, 0, 1, 2)
        archive_texture_actions_grid.setColumnStretch(0, 1)
        archive_texture_actions_grid.setColumnStretch(1, 1)
        archive_texture_actions_layout.addLayout(archive_texture_actions_grid)
        archive_texture_refs_layout.addLayout(archive_texture_actions_layout)

    def _install_tree_horizontal_wheel_guard(self, tree: QTreeWidget) -> None:
        tree.setProperty("cdmw_disable_auto_column_fill", True)
        tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        guard = TreeHorizontalWheelGuard(tree)
        tree.viewport().installEventFilter(guard)
        self._tree_horizontal_wheel_guards.append(guard)

    def _layout_archive_texture_reference_columns(self, *_args) -> None:
        if not hasattr(self, "archive_texture_refs_tree"):
            return
        tree = self.archive_texture_refs_tree
        if tree.columnCount() < 8:
            return

        viewport_width = max(0, tree.viewport().width())
        available_width = max(viewport_width, 260)
        reference_width = 150
        status_width = 98
        part_width = 140
        slot_width = 126
        visual_width = 90
        package_width = 82
        uses_width = 52
        archive_width = max(
            160,
            available_width - (reference_width + status_width + part_width + slot_width + visual_width + package_width + uses_width + 12),
        )
        relation_trees = tuple(
            candidate
            for candidate in (
                getattr(self, "archive_asset_map_tree", None),
                getattr(self, "archive_asset_uses_tree", None),
                getattr(self, "archive_asset_used_by_tree", None),
                getattr(self, "archive_asset_placement_tree", None),
            )
            if isinstance(candidate, QTreeWidget)
        )
        horizontal_scroll_positions = [
            (candidate, int(candidate.horizontalScrollBar().value()))
            for candidate in (tree, *relation_trees)
        ]

        tree.setColumnWidth(0, reference_width)
        tree.setColumnWidth(1, status_width)
        tree.setColumnWidth(2, part_width)
        tree.setColumnWidth(3, slot_width)
        tree.setColumnWidth(4, visual_width)
        tree.setColumnWidth(5, archive_width)
        tree.setColumnWidth(6, package_width)
        tree.setColumnWidth(7, uses_width)
        for relation_tree in relation_trees:
            relation_width = max(280, relation_tree.viewport().width())
            if relation_tree.columnCount() >= 5:
                relation_tree.setColumnWidth(0, 118)
                relation_tree.setColumnWidth(1, 180)
                relation_tree.setColumnWidth(2, 104)
                relation_tree.setColumnWidth(3, 116)
                relation_tree.setColumnWidth(4, max(180, relation_width - 530))
            else:
                relation_tree.setColumnWidth(0, 140)
                relation_tree.setColumnWidth(1, 220)
                relation_tree.setColumnWidth(2, 118)
                relation_tree.setColumnWidth(3, max(180, relation_width - 478))
        for candidate, previous_value in horizontal_scroll_positions:
            horizontal_bar = candidate.horizontalScrollBar()
            horizontal_bar.setValue(max(horizontal_bar.minimum(), min(previous_value, horizontal_bar.maximum())))

    def _refresh_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:
        if not hasattr(self, "archive_texture_refs_group") or not self.archive_texture_refs_group.isVisible():
            return
        self.archive_texture_refs_group.updateGeometry()
        self.archive_asset_map_tabs.updateGeometry()
        self.archive_preview_content_splitter.updateGeometry()
        self.archive_preview_group.updateGeometry()
        self.archive_preview_content_splitter.setCollapsible(1, False)
        self._clamp_archive_preview_asset_map_splitter(prefer_default=prefer_default)
        self._layout_archive_texture_reference_columns()
        self.archive_texture_refs_group.update()
        self.archive_preview_content_splitter.update()

    def _schedule_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:
        QTimer.singleShot(
            0,
            lambda: self._refresh_archive_asset_family_panel_layout(prefer_default=prefer_default),
        )
        QTimer.singleShot(
            80,
            lambda: self._refresh_archive_asset_family_panel_layout(prefer_default=False),
        )

    def _clamp_archive_preview_asset_map_splitter(self, *, prefer_default: bool = False) -> None:
        if (
            not hasattr(self, "archive_texture_refs_group")
            or not self.archive_texture_refs_group.isVisible()
            or not (
                self.current_archive_model_texture_references
                or self.current_archive_used_by_references
                or self.current_archive_family_member_rows
            )
        ):
            return
        if getattr(self, "_archive_preview_splitter_clamping", False):
            return
        sizes = self.archive_preview_content_splitter.sizes()
        splitter_width = max(1, self.archive_preview_content_splitter.width())
        size_total = sum(sizes) if sizes else 0
        total = splitter_width if splitter_width > 16 else max(1, size_total)
        min_preview_width = 560
        configured_refs_min = int(self.archive_texture_refs_group.minimumWidth() or 0)
        min_refs_width = max(240, min(320, configured_refs_min or 300))
        max_refs_width = min(680, max(min_refs_width, int(total * 0.44)))
        max_refs_width = min(max_refs_width, max(0, total - min_preview_width))
        if total < min_preview_width + min_refs_width or max_refs_width < min_refs_width:
            # Keep Asset Family visible even in compact or freshly reflowed layouts.
            # Older logic collapsed this side to 0px; a later window resize was then
            # needed before Qt recalculated enough space for the pane to appear.
            if total < 480:
                refs_width = max(1, min(max(80, int(total * 0.34)), max(1, total - 120)))
            else:
                compact_preview_floor = 360 if total >= 700 else max(220, int(total * 0.58))
                compact_refs_floor = 220 if total >= 700 else max(120, int(total * 0.34))
                refs_ceiling = max(1, total - max(1, compact_preview_floor))
                refs_width = min(max(compact_refs_floor, int(total * 0.34)), refs_ceiling)
            preview_width = max(1, total - refs_width)
            self.archive_texture_refs_group.setMinimumWidth(min(min_refs_width, max(1, refs_width)))
            target_sizes = [preview_width, max(1, refs_width)]
        else:
            self.archive_texture_refs_group.setMinimumWidth(min_refs_width)
            current_refs_width = sizes[1] if len(sizes) >= 2 else 0
            current_preview_width = sizes[0] if len(sizes) >= 2 else 0
            needs_default = (
                prefer_default
                and (
                    len(sizes) < 2
                    or current_refs_width < min_refs_width
                    or current_refs_width > max_refs_width
                    or current_preview_width < min_preview_width
                    or abs(size_total - total) > 80
                )
            )
            if prefer_default or needs_default or current_refs_width <= 0:
                preferred_refs_width = int(getattr(self, "archive_asset_family_preferred_width", 420) or 420)
                desired_refs_width = min(520, max(min_refs_width, preferred_refs_width, int(total * 0.36)))
            else:
                desired_refs_width = current_refs_width
            refs_width = max(min_refs_width, min(desired_refs_width, max_refs_width))
            preview_width = max(min_preview_width, total - refs_width)
            target_sizes = [preview_width, max(0, total - preview_width)]
        if len(sizes) >= 2 and abs(sizes[0] - target_sizes[0]) <= 2 and abs(sizes[1] - target_sizes[1]) <= 2:
            return
        self._archive_preview_splitter_clamping = True
        try:
            self.archive_preview_content_splitter.setSizes(target_sizes)
        finally:
            self._archive_preview_splitter_clamping = False

    def _handle_archive_preview_content_splitter_moved(self, *_args) -> None:
        sizes = self.archive_preview_content_splitter.sizes()
        if (
            not getattr(self, "_archive_preview_splitter_clamping", False)
            and
            len(sizes) >= 2
            and sizes[1] > 0
            and hasattr(self, "archive_texture_refs_group")
            and self.archive_texture_refs_group.isVisible()
        ):
            self.archive_asset_family_preferred_width = sizes[1]
        self._clamp_archive_preview_asset_map_splitter(prefer_default=False)
        self._layout_archive_texture_reference_columns()
