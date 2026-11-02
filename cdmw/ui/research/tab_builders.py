from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
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

from cdmw.domain.research.classification import (
    unknown_resolver_choice_label,
    unknown_resolver_label_choices,
)
from cdmw.ui.research.analysis_state import ANALYSIS_CONTEXT_HELP_TEXT
from cdmw.ui.research.help_widgets import (
    add_flat_section_help as _add_flat_section_help,
    add_titled_help_header as _add_titled_help_header,
    intro_label,
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

def _page(margins: tuple[int, int, int, int] = (0, 8, 10, 0)) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(*margins)
    layout.setSpacing(8)
    return page, layout


def build_texture_sets_page(self) -> QWidget:
    tab, groups_layout = _page()
    intro_label(
        "Related textures grouped into sets, and the type Research gave each texture. "
        "Select a set to extract its textures and sidecar files together.",
        groups_layout,
    )

    group_buttons_row = QHBoxLayout()
    group_buttons_row.setSpacing(8)
    self.texture_group_extract_button = QPushButton("Extract Selected Set")
    self.texture_group_extract_button.setEnabled(False)
    self.texture_group_status_label = QLabel("No grouped texture set selected.")
    self.texture_group_status_label.setWordWrap(True)
    self.texture_group_status_label.setObjectName("HintLabel")
    group_buttons_row.addWidget(self.texture_group_extract_button)
    group_buttons_row.addWidget(self.texture_group_status_label, stretch=1)
    groups_layout.addLayout(group_buttons_row)

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
    self.groups_tab = tab
    return tab


def build_classification_review_page(self) -> QWidget:
    unknown_tab, unknown_layout = _page()
    intro_label(
        "Textures Research could not classify with confidence. Select one, check the preview, "
        "choose the right label and save it. Saved labels stay on this PC and are reused by later "
        "scans and texture policies.",
        unknown_layout,
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
    self.unknown_name_filter_edit.setClearButtonEnabled(True)
    self.unknown_package_filter_edit = QLineEdit()
    self.unknown_package_filter_edit.setPlaceholderText("Package filter, for example 0000 or 0015*")
    self.unknown_package_filter_edit.setClearButtonEnabled(True)
    unknown_filter_row.addWidget(QLabel("Name"))
    unknown_filter_row.addWidget(self.unknown_name_filter_edit, stretch=2)
    unknown_filter_row.addWidget(QLabel("Package"))
    unknown_filter_row.addWidget(self.unknown_package_filter_edit, stretch=1)
    unknown_filter_row.addWidget(self.unknown_show_classified_checkbox)
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

    selection_row = QHBoxLayout()
    selection_row.setSpacing(8)
    self.unknown_select_all_button = QPushButton("Select All Shown")
    self.unknown_clear_family_selection_button = QPushButton("Clear Selection")
    selection_hint = QLabel("Ctrl+click or Shift+click to select several families.")
    selection_hint.setObjectName("HintLabel")
    selection_hint.setWordWrap(True)
    selection_row.addWidget(self.unknown_select_all_button)
    selection_row.addWidget(self.unknown_clear_family_selection_button)
    selection_row.addWidget(selection_hint, stretch=1)
    unknown_left_layout.addLayout(selection_row)

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

    label_group = QGroupBox("Save A Label")
    label_grid = QGridLayout(label_group)
    label_grid.setContentsMargins(10, 12, 10, 10)
    label_grid.setHorizontalSpacing(8)
    label_grid.setVerticalSpacing(8)
    self.unknown_label_combo = QComboBox()
    for choice_key, texture_type, semantic_subtype in unknown_resolver_label_choices():
        self.unknown_label_combo.addItem(
            unknown_resolver_choice_label(choice_key),
            (choice_key, texture_type, semantic_subtype),
        )
    self.unknown_label_combo.setToolTip(
        "The label to save. Research preselects its best suggestion for the selected file."
    )
    self.unknown_accept_current_role_button = QPushButton("Keep Current Role")
    self.unknown_accept_current_role_button.setToolTip(
        "Save the role Research already inferred for the selected file, without changing it."
    )
    # Selecting a file already previews it; the button stays for callers that still drive it.
    self.unknown_preview_button = QPushButton("Preview Current", label_group)
    self.unknown_preview_button.setVisible(False)
    self.unknown_apply_current_file_button = QPushButton("This File")
    self.unknown_apply_current_file_button.setToolTip("Save the label for the selected DDS file only.")
    self.unknown_apply_selected_button = QPushButton("Unknown Files In This Family")
    self.unknown_apply_selected_button.setToolTip(
        "Save the label for every still-unknown DDS file in the selected family."
    )
    self.unknown_apply_group_button = QPushButton("Unknown Files In Selected Families")
    self.unknown_apply_group_button.setToolTip(
        "Save the label for every still-unknown DDS file in all selected families."
    )
    self.unknown_clear_current_file_button = QPushButton("This File")
    self.unknown_clear_current_file_button.setToolTip("Remove the saved label from the selected DDS file.")
    self.unknown_clear_selected_button = QPushButton("This Family")
    self.unknown_clear_selected_button.setToolTip(
        "Remove saved labels from every DDS file in the selected family."
    )
    self.unknown_clear_group_button = QPushButton("Selected Families")
    self.unknown_clear_group_button.setToolTip(
        "Remove saved labels from every DDS file in all selected families."
    )
    label_grid.addWidget(QLabel("Label"), 0, 0)
    label_grid.addWidget(self.unknown_label_combo, 0, 1, 1, 2)
    label_grid.addWidget(self.unknown_accept_current_role_button, 0, 3)
    label_grid.addWidget(QLabel("Save to"), 1, 0)
    label_grid.addWidget(self.unknown_apply_current_file_button, 1, 1)
    label_grid.addWidget(self.unknown_apply_selected_button, 1, 2)
    label_grid.addWidget(self.unknown_apply_group_button, 1, 3)
    label_grid.addWidget(QLabel("Remove from"), 2, 0)
    label_grid.addWidget(self.unknown_clear_current_file_button, 2, 1)
    label_grid.addWidget(self.unknown_clear_selected_button, 2, 2)
    label_grid.addWidget(self.unknown_clear_group_button, 2, 3)
    for column in (1, 2, 3):
        label_grid.setColumnStretch(column, 1)
    unknown_left_layout.addWidget(label_group)
    unknown_splitter.addWidget(unknown_left_panel)

    unknown_preview_group = QGroupBox("Selected Preview")
    unknown_preview_layout = QVBoxLayout(unknown_preview_group)
    unknown_preview_layout.setContentsMargins(10, 12, 10, 10)
    unknown_preview_layout.setSpacing(8)
    unknown_preview_title_row = QHBoxLayout()
    unknown_preview_title_row.setSpacing(8)
    self.unknown_preview_title_label = QLabel("Select a review item")
    self.unknown_preview_title_label.setWordWrap(True)
    (
        self.unknown_preview_zoom_out_button,
        self.unknown_preview_zoom_fit_button,
        self.unknown_preview_zoom_100_button,
        self.unknown_preview_zoom_in_button,
        self.unknown_preview_zoom_value,
    ) = build_preview_zoom_controls()
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
    return unknown_tab


def build_references_page(self) -> QWidget:
    reference_tab, reference_layout = _page()
    intro_label(
        "Find the materials, sidecars and XML files that point at a texture, or the textures a "
        "material uses. Pick a file in Archive Files on the right (double-click works too) or type "
        "its archive path, then click Resolve.",
        reference_layout,
    )

    target_input_row = QHBoxLayout()
    target_input_row.setSpacing(8)
    self.reference_target_edit = QLineEdit()
    self.reference_target_edit.setPlaceholderText(
        "Archive path to resolve, e.g. object/texture/example_diffuse.dds"
    )
    self.reference_target_edit.setClearButtonEnabled(True)
    self.reference_use_archive_button = QPushButton("Use Selected File")
    self.reference_resolve_button = QPushButton("Resolve")
    self.reference_resolve_button.setDefault(True)
    target_input_row.addWidget(self.reference_target_edit, stretch=1)
    target_input_row.addWidget(self.reference_use_archive_button)
    target_input_row.addWidget(self.reference_resolve_button)
    reference_layout.addLayout(target_input_row)

    target_actions_row = QHBoxLayout()
    target_actions_row.setSpacing(8)
    self.reference_extract_button = QPushButton("Extract Related Set")
    self.reference_review_text_button = QPushButton("Review In Text Search")
    self.reference_review_text_button.setEnabled(False)
    self.reference_review_text_button.setToolTip(
        "Open the selected reference row in Text Search to read the XML around it."
    )
    self.reference_status_label = QLabel("Select an archive file or enter a path to resolve relationships.")
    self.reference_status_label.setWordWrap(True)
    self.reference_status_label.setObjectName("HintLabel")
    self.reference_progress = QProgressBar()
    self.reference_progress.setRange(0, 1)
    self.reference_progress.setValue(0)
    self.reference_progress.setFormat("Idle")
    self.reference_progress.setMaximumWidth(180)
    self.reference_progress.setMaximumHeight(18)
    target_actions_row.addWidget(self.reference_extract_button)
    target_actions_row.addWidget(self.reference_review_text_button)
    target_actions_row.addWidget(self.reference_status_label, stretch=1)
    target_actions_row.addWidget(self.reference_progress)
    reference_layout.addLayout(target_actions_row)

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
    self.reference_tab = reference_tab
    return reference_tab


def build_ui_constraints_page(self) -> QWidget:
    ui_constraints_tab, ui_constraints_layout = _page()
    intro_label(
        "UI textures whose on-screen size is fixed by a GetRect box in the game's UI XML. "
        "Upscaling such a texture alone does not make it bigger in game while the XML keeps the same box. "
        "The scan reads archive XML, so it runs only when you click Scan.",
        ui_constraints_layout,
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
    ui_constraints_layout.addLayout(ui_constraints_actions)
    self.ui_constraint_tree = EmptyStateTreeWidget(
        "No UI constraints",
        "Click Scan UI Rect References to find UI textures whose displayed size is fixed by XML.",
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
    ui_constraints_layout.addWidget(self.ui_constraint_tree, stretch=1)
    self.ui_constraints_tab = ui_constraints_tab
    return ui_constraints_tab


def build_heatmap_page(self) -> QWidget:
    heatmap_tab, heatmap_layout = _page()
    intro_label(
        "Where textures concentrate in the current archive view, ranked by system area, folder and package. "
        "Heat adds up textures, texture sets, normal maps, UI textures, sidecars and impostors. "
        "Hover a row to see sample paths.",
        heatmap_layout,
    )
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
    heatmap_layout.addWidget(self.heatmap_tree, stretch=1)
    self.heatmap_tab = heatmap_tab
    return heatmap_tab


def build_preview_zoom_controls() -> tuple[QPushButton, QPushButton, QPushButton, QPushButton, QLabel]:
    zoom_out_button = QPushButton("-")
    zoom_out_button.setToolTip("Zoom out.")
    zoom_fit_button = QPushButton("Fit")
    zoom_fit_button.setToolTip("Fit the preview to the available space.")
    zoom_100_button = QPushButton("100%")
    zoom_100_button.setToolTip("Show the preview at 100% zoom.")
    zoom_in_button = QPushButton("+")
    zoom_in_button.setToolTip("Zoom in.")
    zoom_value = QLabel("")
    zoom_value.setObjectName("HintLabel")
    zoom_value.setMinimumWidth(44)
    return zoom_out_button, zoom_fit_button, zoom_100_button, zoom_in_button, zoom_value


def build_texture_tab(self) -> QWidget:
    tab, layout = _page()
    intro_label(
        "Checks your rebuilt textures in the Output root against the originals in the Original DDS root: "
        "mip chains, normal maps and memory budget. Set both folders in the Textures tool, then click Refresh Research.",
        layout,
    )
    self.analysis_roots_label = QLabel("")
    self.analysis_roots_label.setWordWrap(True)
    self.analysis_roots_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(self.analysis_roots_label)

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
    export_buttons_row.addWidget(self.analysis_status_label, stretch=1)
    export_buttons_row.addWidget(self.analysis_context_help_button)
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
