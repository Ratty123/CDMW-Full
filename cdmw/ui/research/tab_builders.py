from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.research import unknown_resolver_choice_label, unknown_resolver_label_choices
from cdmw.ui.research.analysis_state import ANALYSIS_CONTEXT_HELP_TEXT
from cdmw.ui.research.help_widgets import (
    add_flat_section_help as _add_flat_section_help,
    add_help_row as _add_help_row,
    add_titled_help_header as _add_titled_help_header,
    make_research_help_button as _make_help_button,
)
from cdmw.ui.research.layout_state import (
    research_analysis_splitter_default_sizes,
    research_archive_picker_splitter_default_sizes,
    research_groups_splitter_default_sizes,
    research_notes_splitter_default_sizes,
    research_reference_splitter_default_sizes,
    research_unknown_splitter_default_sizes,
)
from cdmw.ui.research.models import archive_picker_item_kind as _archive_picker_item_kind
from cdmw.ui.research.reference_payload_state import ui_constraint_initial_status_text
from cdmw.ui.research.tree_helpers import make_research_tree_columns_persistent
from cdmw.ui.widgets import (
    ArchiveDetailsEditor,
    EmptyStateTreeWidget,
    FlatSectionPanel,
    PreviewLabel,
    PreviewScrollArea,
)

def build_archive_tab(self) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    sub_tabs = QTabWidget()
    self.archive_insights_tabs = sub_tabs
    sub_tabs.setCornerWidget(
        _make_help_button(
            "Research rows in this tab are built from the current Archive Browser view/filter. When available, DDS classification can still consult loaded archive sidecars such as .pac.xml and .pami so color/albedo and other roles do not depend only on filename guessing."
        ),
        Qt.TopRightCorner,
    )
    layout.addWidget(sub_tabs, stretch=1)

    groups_tab = QWidget()
    groups_layout = QVBoxLayout(groups_tab)
    groups_layout.setContentsMargins(0, 0, 0, 0)
    groups_layout.setSpacing(10)

    group_actions = QVBoxLayout()
    group_actions.setSpacing(6)
    group_buttons_row = QHBoxLayout()
    group_buttons_row.setSpacing(8)
    self.texture_group_extract_button = QPushButton("Extract Selected Set")
    self.texture_group_status_label = QLabel("No grouped texture set selected.")
    self.texture_group_status_label.setWordWrap(True)
    self.texture_group_status_label.setObjectName("HintLabel")
    group_buttons_row.addWidget(self.texture_group_extract_button)
    group_buttons_row.addWidget(
        _make_help_button("Select a grouped texture set to extract its related files and sidecars.")
    )
    group_buttons_row.addStretch(1)
    group_actions.addLayout(group_buttons_row)
    group_actions.addWidget(self.texture_group_status_label)
    groups_layout.addLayout(group_actions)

    self.groups_splitter = QSplitter(Qt.Horizontal)
    groups_splitter = self.groups_splitter
    groups_splitter.setChildrenCollapsible(False)
    groups_layout.addWidget(groups_splitter, stretch=1)

    group_group = QGroupBox("")
    group_layout = QVBoxLayout(group_group)
    group_layout.setContentsMargins(10, 8, 10, 10)
    group_layout.setSpacing(6)
    _add_titled_help_header(
        group_layout,
        "Texture Set Grouper",
        "Bundles related texture members and sidecars such as base/_color, _n/_wn, _sp, _m/_ma/_mg, _d/_dmap/_disp, _op/_dr, XML, and material files."
    )
    self.texture_group_tree = EmptyStateTreeWidget(
        "Refresh Research",
        "Texture sets will appear here after the archive view has been analyzed.",
    )
    self.texture_group_tree.setAlternatingRowColors(True)
    self.texture_group_tree.setSelectionMode(QAbstractItemView.SingleSelection)
    self.texture_group_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    self.texture_group_tree.setHeaderLabels(["Group", "Members", "Kinds", "Packages"])
    self.texture_group_tree.header().resizeSection(0, 280)
    make_research_tree_columns_persistent(self.texture_group_tree, self.settings, "texture_group")
    group_layout.addWidget(self.texture_group_tree, stretch=1)
    groups_splitter.addWidget(group_group)

    classifier_group = QGroupBox("")
    classifier_layout = QVBoxLayout(classifier_group)
    classifier_layout.setContentsMargins(10, 8, 10, 10)
    classifier_layout.setSpacing(6)
    _add_titled_help_header(
        classifier_layout,
        "Texture-Type Classifier",
        "Classifies archive textures as color, normal, mask, roughness, emissive, UI, impostor, or unknown using naming/path heuristics plus exact sidecar bindings from files such as .pac.xml and .pami when available."
    )
    self.classifier_tree = EmptyStateTreeWidget(
        "No classifications yet",
        "Run Refresh Research to classify visible DDS files and review confidence by package.",
    )
    self.classifier_tree.setRootIsDecorated(False)
    self.classifier_tree.setAlternatingRowColors(True)
    self.classifier_tree.setUniformRowHeights(True)
    self.classifier_tree.setHeaderLabels(["File", "Type", "Confidence", "Package", "Reason"])
    self.classifier_tree.header().resizeSection(0, 340)
    self.classifier_tree.header().resizeSection(1, 120)
    self.classifier_tree.header().resizeSection(2, 90)
    self.classifier_tree.header().resizeSection(3, 120)
    make_research_tree_columns_persistent(self.classifier_tree, self.settings, "classifier")
    classifier_layout.addWidget(self.classifier_tree, stretch=1)
    groups_splitter.addWidget(classifier_group)
    groups_splitter.setSizes(research_groups_splitter_default_sizes())
    sub_tabs.addTab(groups_tab, "Groups")

    unknown_tab = QWidget()
    unknown_layout = QVBoxLayout(unknown_tab)
    unknown_layout.setContentsMargins(0, 0, 0, 0)
    unknown_layout.setSpacing(6)

    _add_help_row(
        unknown_layout,
        "Review DDS files here, preview them directly, and approve a label once so the app remembers it for future scans and policy planning. The list follows the current Research snapshot from Archive Browser, while inferred roles may still use loaded sidecar bindings."
    )

    self.unknown_resolver_status_label = QLabel(
        "Refresh Research to build the current classification review list."
    )
    self.unknown_resolver_status_label.setWordWrap(True)
    self.unknown_resolver_status_label.setObjectName("HintLabel")
    unknown_layout.addWidget(self.unknown_resolver_status_label)

    unknown_filter_row = QHBoxLayout()
    unknown_filter_row.setSpacing(8)
    self.unknown_show_classified_checkbox = QCheckBox("Also show already classified DDS families")
    self.unknown_show_classified_checkbox.setToolTip(
        "Include already classified texture families too, so you can override them manually if you want."
    )
    self.unknown_name_filter_edit = QLineEdit()
    self.unknown_name_filter_edit.setPlaceholderText("Name filter, supports * and ?")
    self.unknown_package_filter_edit = QLineEdit()
    self.unknown_package_filter_edit.setPlaceholderText("Package filter, for example 0000 or 0015*")
    self.unknown_select_all_button = QPushButton("Select All Shown")
    self.unknown_clear_family_selection_button = QPushButton("Clear Selection")
    unknown_filter_row.addWidget(self.unknown_show_classified_checkbox)
    unknown_filter_row.addWidget(QLabel("Name"))
    unknown_filter_row.addWidget(self.unknown_name_filter_edit, stretch=1)
    unknown_filter_row.addWidget(QLabel("Package"))
    unknown_filter_row.addWidget(self.unknown_package_filter_edit)
    unknown_filter_row.addWidget(self.unknown_select_all_button)
    unknown_filter_row.addWidget(self.unknown_clear_family_selection_button)
    unknown_layout.addLayout(unknown_filter_row)

    self.unknown_splitter = QSplitter(Qt.Horizontal)
    unknown_splitter = self.unknown_splitter
    unknown_splitter.setChildrenCollapsible(False)
    unknown_layout.addWidget(unknown_splitter, stretch=1)

    unknown_left_panel = QWidget()
    unknown_left_layout = QVBoxLayout(unknown_left_panel)
    unknown_left_layout.setContentsMargins(0, 0, 0, 0)
    unknown_left_layout.setSpacing(8)

    self.unknown_group_tree = EmptyStateTreeWidget(
        "No unknown groups",
        "Unclassified texture families will appear here when the current archive view contains unresolved DDS files.",
    )
    self.unknown_group_tree.setRootIsDecorated(False)
    self.unknown_group_tree.setAlternatingRowColors(True)
    self.unknown_group_tree.setUniformRowHeights(True)
    self.unknown_group_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    self.unknown_group_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    self.unknown_group_tree.setHeaderLabels(["Name", "Classification", "Local Approval", "Package"])
    self.unknown_group_tree.header().setStretchLastSection(False)
    self.unknown_group_tree.header().resizeSection(0, 340)
    self.unknown_group_tree.header().resizeSection(1, 220)
    self.unknown_group_tree.header().resizeSection(2, 110)
    self.unknown_group_tree.header().resizeSection(3, 120)
    make_research_tree_columns_persistent(self.unknown_group_tree, self.settings, "unknown_group")
    unknown_left_layout.addWidget(self.unknown_group_tree, stretch=1)

    unknown_actions_widget = QWidget()
    unknown_actions_layout = QVBoxLayout(unknown_actions_widget)
    unknown_actions_layout.setContentsMargins(0, 0, 0, 0)
    unknown_actions_layout.setSpacing(8)

    approval_row = QHBoxLayout()
    approval_row.setSpacing(8)
    self.unknown_label_combo = QComboBox()
    for choice_key, texture_type, semantic_subtype in unknown_resolver_label_choices():
        self.unknown_label_combo.addItem(
            unknown_resolver_choice_label(choice_key),
            (choice_key, texture_type, semantic_subtype),
        )
    self.unknown_preview_button = QPushButton("Preview Current")
    self.unknown_apply_selected_button = QPushButton("Apply To Current Family")
    self.unknown_apply_group_button = QPushButton("Apply To Selected Families")
    self.unknown_clear_selected_button = QPushButton("Clear Current Family")
    self.unknown_clear_group_button = QPushButton("Clear Selected Families")
    approval_row.addWidget(QLabel("Label"))
    approval_row.addWidget(self.unknown_label_combo, stretch=1)
    approval_row.addWidget(self.unknown_preview_button)
    unknown_actions_layout.addLayout(approval_row)

    self.unknown_accept_current_role_button = QPushButton("Save Current Role Locally")
    self.unknown_apply_current_file_button = QPushButton("Apply To Current File")
    self.unknown_clear_current_file_button = QPushButton("Clear Current File")
    self.unknown_apply_selected_button.setText("Apply To Unknown Files In Current Family")
    self.unknown_apply_group_button.setText("Apply To Unknown Files In Selected Families")
    self.unknown_clear_selected_button.setText("Clear Current Family")
    self.unknown_clear_group_button.setText("Clear Selected Families")

    file_actions_row = QHBoxLayout()
    file_actions_row.setSpacing(8)
    file_actions_row.addWidget(self.unknown_accept_current_role_button)
    file_actions_row.addWidget(self.unknown_apply_current_file_button)
    file_actions_row.addWidget(self.unknown_clear_current_file_button)
    file_actions_row.addStretch(1)
    unknown_actions_layout.addLayout(file_actions_row)

    current_family_actions_row = QHBoxLayout()
    current_family_actions_row.setSpacing(8)
    current_family_actions_row.addWidget(self.unknown_apply_selected_button)
    current_family_actions_row.addWidget(self.unknown_clear_selected_button)
    current_family_actions_row.addStretch(1)
    unknown_actions_layout.addLayout(current_family_actions_row)

    selected_family_actions_row = QHBoxLayout()
    selected_family_actions_row.setSpacing(8)
    selected_family_actions_row.addWidget(self.unknown_apply_group_button)
    selected_family_actions_row.addWidget(self.unknown_clear_group_button)
    selected_family_actions_row.addStretch(1)
    unknown_actions_layout.addLayout(selected_family_actions_row)
    unknown_left_layout.addWidget(unknown_actions_widget)

    unknown_members_group = QGroupBox("Family Members")
    self.unknown_members_group = unknown_members_group
    unknown_members_layout = QVBoxLayout(unknown_members_group)
    unknown_members_layout.setContentsMargins(10, 12, 10, 10)
    unknown_members_layout.setSpacing(8)
    self.unknown_members_hint_label = QLabel(
        "Shown only when the selected family has multiple texture files."
    )
    self.unknown_members_hint_label.setWordWrap(True)
    self.unknown_members_hint_label.setObjectName("HintLabel")
    unknown_members_layout.addWidget(self.unknown_members_hint_label)
    self.unknown_member_tree = EmptyStateTreeWidget(
        "Select a family",
        "Files in the selected unknown group will appear here.",
    )
    self.unknown_member_tree.setRootIsDecorated(False)
    self.unknown_member_tree.setAlternatingRowColors(True)
    self.unknown_member_tree.setSelectionMode(QAbstractItemView.SingleSelection)
    self.unknown_member_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    self.unknown_member_tree.setHeaderLabels(["File", "Current", "Local", "Role", "Package", "Reason"])
    self.unknown_member_tree.header().resizeSection(0, 320)
    self.unknown_member_tree.header().resizeSection(1, 90)
    self.unknown_member_tree.header().resizeSection(2, 130)
    self.unknown_member_tree.header().resizeSection(3, 90)
    self.unknown_member_tree.header().resizeSection(4, 120)
    make_research_tree_columns_persistent(self.unknown_member_tree, self.settings, "unknown_member")
    unknown_members_layout.addWidget(self.unknown_member_tree, stretch=1)
    unknown_left_layout.addWidget(unknown_members_group)
    unknown_splitter.addWidget(unknown_left_panel)

    unknown_preview_group = QGroupBox("Selected Preview")
    unknown_preview_layout = QVBoxLayout(unknown_preview_group)
    unknown_preview_layout.setContentsMargins(10, 12, 10, 10)
    unknown_preview_layout.setSpacing(8)
    unknown_preview_title_row = QHBoxLayout()
    unknown_preview_title_row.setSpacing(8)
    self.unknown_preview_title_label = QLabel("Select a review item")
    self.unknown_preview_title_label.setWordWrap(True)
    self.unknown_preview_zoom_out_button = QPushButton("-")
    self.unknown_preview_zoom_out_button.setToolTip("Zoom out.")
    self.unknown_preview_zoom_fit_button = QPushButton("Fit")
    self.unknown_preview_zoom_fit_button.setToolTip("Fit the preview to the available space.")
    self.unknown_preview_zoom_100_button = QPushButton("100%")
    self.unknown_preview_zoom_100_button.setToolTip("Show the preview at 100% zoom.")
    self.unknown_preview_zoom_in_button = QPushButton("+")
    self.unknown_preview_zoom_in_button.setToolTip("Zoom in.")
    self.unknown_preview_zoom_value = QLabel("-")
    self.unknown_preview_zoom_value.setObjectName("HintLabel")
    unknown_preview_title_row.addWidget(self.unknown_preview_title_label, stretch=1)
    unknown_preview_title_row.addWidget(self.unknown_preview_zoom_out_button)
    unknown_preview_title_row.addWidget(self.unknown_preview_zoom_fit_button)
    unknown_preview_title_row.addWidget(self.unknown_preview_zoom_100_button)
    unknown_preview_title_row.addWidget(self.unknown_preview_zoom_in_button)
    unknown_preview_title_row.addWidget(self.unknown_preview_zoom_value)
    unknown_preview_layout.addLayout(unknown_preview_title_row)

    self.unknown_preview_meta_label = QLabel("Select a DDS file to preview it here.")
    self.unknown_preview_meta_label.setWordWrap(True)
    self.unknown_preview_meta_label.setObjectName("HintLabel")
    unknown_preview_layout.addWidget(self.unknown_preview_meta_label)
    self.unknown_preview_warning_label = QLabel("")
    self.unknown_preview_warning_label.setWordWrap(True)
    self.unknown_preview_warning_label.setObjectName("WarningText")
    self.unknown_preview_warning_label.setVisible(False)
    unknown_preview_layout.addWidget(self.unknown_preview_warning_label)

    self.unknown_preview_stack = QStackedWidget()
    self.unknown_preview_label = PreviewLabel("Select a DDS file to preview it here.")
    self.unknown_preview_scroll = PreviewScrollArea()
    self.unknown_preview_scroll.setWidgetResizable(False)
    self.unknown_preview_scroll.setAlignment(Qt.AlignCenter)
    self.unknown_preview_scroll.setWidget(self.unknown_preview_label)
    self.unknown_preview_label.attach_scroll_area(self.unknown_preview_scroll)
    self.unknown_preview_label.set_wheel_zoom_handler(self._adjust_unknown_preview_zoom)
    self.unknown_preview_info_edit = QPlainTextEdit()
    self.unknown_preview_info_edit.setReadOnly(True)
    self.unknown_preview_info_edit.setPlaceholderText("Select a DDS file to preview it here.")
    self.unknown_preview_stack.addWidget(self.unknown_preview_scroll)
    self.unknown_preview_stack.addWidget(self.unknown_preview_info_edit)
    unknown_preview_layout.addWidget(self.unknown_preview_stack, stretch=1)
    unknown_preview_group.setMinimumWidth(400)
    unknown_splitter.addWidget(unknown_preview_group)

    unknown_details_group = QGroupBox("Details")
    unknown_details_layout = QVBoxLayout(unknown_details_group)
    unknown_details_layout.setContentsMargins(10, 12, 10, 10)
    unknown_details_layout.setSpacing(8)
    self.unknown_detail_edit = QPlainTextEdit()
    self.unknown_detail_edit.setReadOnly(True)
    self.unknown_detail_edit.setPlaceholderText(
        "Select a DDS review item to inspect suggestions, sidecars, DDS facts, and approval guidance."
    )
    unknown_details_layout.addWidget(self.unknown_detail_edit, stretch=1)
    unknown_details_group.setMinimumWidth(300)
    unknown_splitter.addWidget(unknown_details_group)
    unknown_splitter.setSizes(research_unknown_splitter_default_sizes())
    self.classification_review_tab = unknown_tab
    sub_tabs.addTab(unknown_tab, "Classification Review")

    reference_tab = QWidget()
    reference_layout = QVBoxLayout(reference_tab)
    reference_layout.setContentsMargins(0, 0, 0, 0)
    reference_layout.setSpacing(10)

    reference_controls = QGroupBox("")
    controls_layout = QVBoxLayout(reference_controls)
    controls_layout.setContentsMargins(10, 8, 10, 10)
    controls_layout.setSpacing(6)
    _add_titled_help_header(
        controls_layout,
        "Material-To-Texture Reference Resolver",
        "Resolve material/shader/XML references for a selected texture, or inspect outbound texture references from a selected material sidecar."
    )
    target_row = QVBoxLayout()
    target_row.setSpacing(6)
    target_input_row = QHBoxLayout()
    target_input_row.setSpacing(8)
    target_actions_row = QHBoxLayout()
    target_actions_row.setSpacing(8)
    self.reference_target_edit = QLineEdit()
    self.reference_target_edit.setPlaceholderText(
        "Archive path to resolve, e.g. object/texture/example_diffuse.dds"
    )
    self.reference_use_archive_button = QPushButton("Use Selected File")
    self.reference_resolve_button = QPushButton("Resolve")
    self.reference_extract_button = QPushButton("Extract Related Set")
    self.reference_review_text_button = QPushButton("Review In Text Search")
    self.reference_review_text_button.setEnabled(False)
    target_input_row.addWidget(self.reference_target_edit, stretch=1)
    target_actions_row.addWidget(self.reference_use_archive_button)
    target_actions_row.addWidget(self.reference_resolve_button)
    target_actions_row.addWidget(self.reference_extract_button)
    target_actions_row.addWidget(self.reference_review_text_button)
    target_actions_row.addStretch(1)
    target_row.addLayout(target_input_row)
    target_row.addLayout(target_actions_row)
    controls_layout.addLayout(target_row)
    self.reference_status_label = QLabel("Select an archive file or enter a path to resolve relationships.")
    self.reference_status_label.setWordWrap(True)
    self.reference_status_label.setObjectName("HintLabel")
    controls_layout.addWidget(self.reference_status_label)
    self.reference_progress = QProgressBar()
    self.reference_progress.setRange(0, 1)
    self.reference_progress.setValue(0)
    self.reference_progress.setFormat("Idle")
    controls_layout.addWidget(self.reference_progress)
    reference_layout.addWidget(reference_controls)

    self.reference_splitter = QSplitter(Qt.Horizontal)
    reference_splitter = self.reference_splitter
    reference_splitter.setChildrenCollapsible(False)
    reference_layout.addWidget(reference_splitter, stretch=1)

    reference_group = QGroupBox("Reference Results")
    reference_group_layout = QVBoxLayout(reference_group)
    reference_group_layout.setContentsMargins(10, 12, 10, 10)
    reference_group_layout.setSpacing(8)
    self.reference_tree = EmptyStateTreeWidget(
        "No material references",
        "Resolve references to list sidecar, skeleton, animation, and texture relationships.",
    )
    self.reference_tree.setRootIsDecorated(False)
    self.reference_tree.setAlternatingRowColors(True)
    self.reference_tree.setUniformRowHeights(True)
    self.reference_tree.setHeaderLabels(["Source", "Related", "GetRect", "Constraint", "Matches", "Package"])
    self.reference_tree.header().resizeSection(0, 300)
    self.reference_tree.header().resizeSection(1, 260)
    self.reference_tree.header().resizeSection(2, 110)
    self.reference_tree.header().resizeSection(3, 220)
    self.reference_tree.header().resizeSection(4, 80)
    make_research_tree_columns_persistent(self.reference_tree, self.settings, "reference")
    reference_group_layout.addWidget(self.reference_tree)
    reference_splitter.addWidget(reference_group)

    sidecar_group = QGroupBox("Archive-Side Sidecar Discovery")
    sidecar_layout = QVBoxLayout(sidecar_group)
    sidecar_layout.setContentsMargins(10, 12, 10, 10)
    sidecar_layout.setSpacing(8)
    self.sidecar_tree = EmptyStateTreeWidget(
        "No sidecars discovered",
        "Sidecar discovery results will appear here after analysis.",
    )
    self.sidecar_tree.setRootIsDecorated(False)
    self.sidecar_tree.setAlternatingRowColors(True)
    self.sidecar_tree.setUniformRowHeights(True)
    self.sidecar_tree.setHeaderLabels(["Related File", "Relation", "Confidence", "Package", "Reason"])
    self.sidecar_tree.header().resizeSection(0, 320)
    self.sidecar_tree.header().resizeSection(1, 160)
    self.sidecar_tree.header().resizeSection(2, 90)
    self.sidecar_tree.header().resizeSection(3, 120)
    make_research_tree_columns_persistent(self.sidecar_tree, self.settings, "sidecar")
    sidecar_layout.addWidget(self.sidecar_tree)
    reference_splitter.addWidget(sidecar_group)
    reference_splitter.setSizes(research_reference_splitter_default_sizes())
    sub_tabs.addTab(reference_tab, "References")

    ui_constraints_tab = QWidget()
    ui_constraints_layout = QVBoxLayout(ui_constraints_tab)
    ui_constraints_layout.setContentsMargins(0, 0, 0, 0)
    ui_constraints_layout.setSpacing(10)
    ui_constraints_group = QGroupBox("")
    ui_constraints_group_layout = QVBoxLayout(ui_constraints_group)
    ui_constraints_group_layout.setContentsMargins(10, 8, 10, 10)
    ui_constraints_group_layout.setSpacing(6)
    _add_titled_help_header(
        ui_constraints_group_layout,
        "UI Rect References",
        "Shows textures that are explicitly referenced by archive UI/XML text with a GetRect-style size box. "
        "This is informational evidence only: it warns that DDS-only upscaling may not change the rendered size if the UI still uses the same rect."
    )
    ui_constraints_actions = QHBoxLayout()
    ui_constraints_actions.setSpacing(8)
    self.ui_constraint_refresh_button = QPushButton("Scan UI Rect References")
    self.ui_constraint_status_label = QLabel(ui_constraint_initial_status_text())
    self.ui_constraint_status_label.setWordWrap(True)
    self.ui_constraint_status_label.setObjectName("HintLabel")
    self.ui_constraint_progress = QProgressBar()
    self.ui_constraint_progress.setRange(0, 1)
    self.ui_constraint_progress.setValue(0)
    self.ui_constraint_progress.setFormat("Idle")
    self.ui_constraint_progress.setMaximumWidth(180)
    self.ui_constraint_progress.setMaximumHeight(18)
    ui_constraints_actions.addWidget(self.ui_constraint_refresh_button)
    ui_constraints_actions.addWidget(self.ui_constraint_status_label, stretch=1)
    ui_constraints_actions.addWidget(self.ui_constraint_progress)
    ui_constraints_group_layout.addLayout(ui_constraints_actions)
    self.ui_constraint_tree = EmptyStateTreeWidget(
        "No UI constraints",
        "Refresh UI constraints to identify referenced files that must preserve dimensions or format.",
    )
    self.ui_constraint_tree.setRootIsDecorated(False)
    self.ui_constraint_tree.setAlternatingRowColors(True)
    self.ui_constraint_tree.setUniformRowHeights(True)
    self.ui_constraint_tree.setHeaderLabels(
        ["Texture", "Source XML", "DDS Size", "GetRect", "Constraint", "Package"]
    )
    self.ui_constraint_tree.header().resizeSection(0, 320)
    self.ui_constraint_tree.header().resizeSection(1, 280)
    self.ui_constraint_tree.header().resizeSection(2, 90)
    self.ui_constraint_tree.header().resizeSection(3, 90)
    self.ui_constraint_tree.header().resizeSection(4, 220)
    make_research_tree_columns_persistent(self.ui_constraint_tree, self.settings, "ui_constraint")
    ui_constraints_group_layout.addWidget(self.ui_constraint_tree)
    ui_constraints_layout.addWidget(ui_constraints_group, stretch=1)
    sub_tabs.addTab(ui_constraints_tab, "UI Constraints")

    heatmap_tab = QWidget()
    heatmap_layout = QVBoxLayout(heatmap_tab)
    heatmap_layout.setContentsMargins(0, 0, 0, 0)
    heatmap_layout.setSpacing(10)
    heatmap_group = QGroupBox("Texture Usage Heatmap")
    heatmap_group_layout = QVBoxLayout(heatmap_group)
    heatmap_group_layout.setContentsMargins(10, 12, 10, 10)
    heatmap_group_layout.setSpacing(8)
    self.heatmap_tree = EmptyStateTreeWidget(
        "No usage heatmap",
        "Texture usage hotspots will appear here after Research refresh.",
    )
    self.heatmap_tree.setAlternatingRowColors(True)
    self.heatmap_tree.setHeaderLabels(
        ["Label", "Heat", "Textures", "Sets", "Normals", "UI", "Sidecars", "Impostors"]
    )
    self.heatmap_tree.header().resizeSection(0, 360)
    make_research_tree_columns_persistent(self.heatmap_tree, self.settings, "heatmap")
    heatmap_group_layout.addWidget(self.heatmap_tree)
    heatmap_layout.addWidget(heatmap_group, stretch=1)
    sub_tabs.addTab(heatmap_tab, "Heatmap")

    return tab


def build_texture_tab(self) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    export_row = QVBoxLayout()
    export_row.setSpacing(6)
    export_buttons_row = QHBoxLayout()
    export_buttons_row.setSpacing(8)
    self.export_report_csv_button = QPushButton("Export Report CSV")
    self.export_report_json_button = QPushButton("Export Report JSON")
    self.analysis_status_label = QLabel("Ready.")
    self.analysis_status_label.setWordWrap(True)
    self.analysis_status_label.setObjectName("HintLabel")
    self.analysis_context_help_button = _make_help_button(ANALYSIS_CONTEXT_HELP_TEXT)
    export_buttons_row.addWidget(self.export_report_csv_button)
    export_buttons_row.addWidget(self.export_report_json_button)
    export_buttons_row.addWidget(self.analysis_status_label)
    export_buttons_row.addWidget(self.analysis_context_help_button)
    export_buttons_row.addStretch(1)
    export_row.addLayout(export_buttons_row)
    layout.addLayout(export_row)

    self.analysis_context_label = QLabel(ANALYSIS_CONTEXT_HELP_TEXT)
    self.analysis_context_label.setWordWrap(True)
    self.analysis_context_label.setObjectName("HintLabel")
    self.analysis_context_label.setVisible(False)

    self.analysis_splitter = QSplitter(Qt.Horizontal)
    splitter = self.analysis_splitter
    splitter.setChildrenCollapsible(False)
    layout.addWidget(splitter, stretch=1)

    mip_group = QGroupBox("")
    mip_layout = QVBoxLayout(mip_group)
    mip_layout.setContentsMargins(10, 8, 10, 10)
    mip_layout.setSpacing(6)
    _add_titled_help_header(
        mip_layout,
        "Mip Analysis",
        "Compares matching DDS files in Original DDS root and Output root. Results appear only when both roots exist and contain the same relative file path."
    )
    self.mip_tree = EmptyStateTreeWidget(
        "No mip analysis",
        "Refresh Research with original and output roots available to compare mip behavior.",
    )
    self.mip_tree.setRootIsDecorated(False)
    self.mip_tree.setAlternatingRowColors(True)
    self.mip_tree.setHeaderLabels(["Path", "Original", "Rebuilt", "Mips", "Warnings"])
    self.mip_tree.header().resizeSection(0, 320)
    make_research_tree_columns_persistent(self.mip_tree, self.settings, "mip")
    mip_layout.addWidget(self.mip_tree, stretch=1)
    splitter.addWidget(mip_group)

    normal_group = QGroupBox("")
    normal_layout = QVBoxLayout(normal_group)
    normal_layout.setContentsMargins(10, 8, 10, 10)
    normal_layout.setSpacing(6)
    _add_titled_help_header(
        normal_layout,
        "Bulk Normal Validator",
        "Scans normal-like DDS files from the current Original DDS root and Output root independently. "
        "This can show results even if no rebuilt outputs exist yet."
    )
    self.normal_tree = EmptyStateTreeWidget(
        "No normal-map validation",
        "Normal validation results will appear here after Research refresh.",
    )
    self.normal_tree.setRootIsDecorated(False)
    self.normal_tree.setAlternatingRowColors(True)
    self.normal_tree.setHeaderLabels(["Path", "Root", "Format", "Size", "Issues"])
    self.normal_tree.header().resizeSection(0, 340)
    make_research_tree_columns_persistent(self.normal_tree, self.settings, "normal")
    normal_layout.addWidget(self.normal_tree, stretch=1)
    splitter.addWidget(normal_group)

    budget_group = QGroupBox("")
    budget_layout = QVBoxLayout(budget_group)
    budget_layout.setContentsMargins(10, 8, 10, 10)
    budget_layout.setSpacing(6)
    _add_titled_help_header(
        budget_layout,
        "Budget Analysis",
        "Exact budget rows compare matching DDS files in Original DDS root and Output root. "
        "Class, terrain-group, and profile sections are heuristic summaries and are labeled as such."
    )
    self.budget_tabs = QTabWidget()
    self.budget_file_tree = EmptyStateTreeWidget(
        "No texture budget data",
        "Per-file budget rows will appear here after visible textures are analyzed.",
    )
    self.budget_file_tree.setRootIsDecorated(False)
    self.budget_file_tree.setAlternatingRowColors(True)
    self.budget_file_tree.setUniformRowHeights(True)
    self.budget_file_tree.setHeaderLabels(["Path", "Delta", "Ratio", "Size", "Type", "Risk"])
    self.budget_file_tree.header().resizeSection(0, 340)
    make_research_tree_columns_persistent(self.budget_file_tree, self.settings, "budget_file")
    self.budget_tabs.addTab(self.budget_file_tree, "Files")
    self.budget_class_tree = EmptyStateTreeWidget("No class summary", "Class-level budget totals will appear here.")
    self.budget_class_tree.setRootIsDecorated(False)
    self.budget_class_tree.setAlternatingRowColors(True)
    self.budget_class_tree.setUniformRowHeights(True)
    self.budget_class_tree.setHeaderLabels(["Texture Type", "Affected", "Byte Delta", "Avg Risk", "Band"])
    make_research_tree_columns_persistent(self.budget_class_tree, self.settings, "budget_class")
    self.budget_tabs.addTab(self.budget_class_tree, "Class Risk")
    self.budget_group_tree = EmptyStateTreeWidget("No group summary", "Grouped texture budget totals will appear here.")
    self.budget_group_tree.setRootIsDecorated(False)
    self.budget_group_tree.setAlternatingRowColors(True)
    self.budget_group_tree.setUniformRowHeights(True)
    self.budget_group_tree.setHeaderLabels(["Group", "Textures", "Byte Delta", "Avg Ratio", "Risk", "Band"])
    self.budget_group_tree.header().resizeSection(0, 300)
    make_research_tree_columns_persistent(self.budget_group_tree, self.settings, "budget_group")
    self.budget_tabs.addTab(self.budget_group_tree, "Terrain-Like Groups")
    self.budget_profile_tree = EmptyStateTreeWidget("No profile summary", "Profile budget totals will appear here.")
    self.budget_profile_tree.setRootIsDecorated(False)
    self.budget_profile_tree.setAlternatingRowColors(True)
    self.budget_profile_tree.setUniformRowHeights(True)
    self.budget_profile_tree.setHeaderLabels(["Profile", "Total Delta", "Total Ratio", "Changed", "Upscaled"])
    make_research_tree_columns_persistent(self.budget_profile_tree, self.settings, "budget_profile")
    self.budget_tabs.addTab(self.budget_profile_tree, "Profile")
    budget_layout.addWidget(self.budget_tabs, stretch=1)
    splitter.addWidget(budget_group)

    splitter.setSizes(research_analysis_splitter_default_sizes())
    self.mip_tree.currentItemChanged.connect(self._handle_mip_selection_changed)
    self.normal_tree.currentItemChanged.connect(self._handle_normal_selection_changed)
    self.budget_file_tree.currentItemChanged.connect(self._handle_budget_selection_changed)
    self.budget_class_tree.currentItemChanged.connect(self._handle_budget_selection_changed)
    self.budget_group_tree.currentItemChanged.connect(self._handle_budget_selection_changed)
    self.budget_profile_tree.currentItemChanged.connect(self._handle_budget_selection_changed)
    return tab
