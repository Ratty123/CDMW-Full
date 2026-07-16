from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QThread, Qt, QTimer, Signal
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
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    DEFAULT_UI_LOG_TEXT_STYLE,
    DEFAULT_UI_PREVIEW_COLOR_SCHEME,
    DEFAULT_UI_THEME,
)
from cdmw.services.archive_query_service import build_archive_tree_index
from cdmw.services.texture_workflow_service import (
    remove_registered_texture_classifications,
    set_registered_texture_classifications,
    texture_classification_registry_path,
)
from cdmw.domain.research.contracts import (
    ResearchNote,
    UnknownResolverGroup,
)
from cdmw.services.research_service import research_service
from cdmw.models import AppConfig, ArchiveEntry, ArchivePreviewResult
from cdmw.ui.research import archive_picker_controller as _research_archive_picker_controller
from cdmw.ui.research.archive_picker_state import (
    archive_picker_available_status_text,
    archive_picker_entries_from_sources,
    archive_picker_entry_for_path,
    archive_picker_entry_index_for_path,
    archive_picker_flat_limit_status_text,
    archive_picker_focus_flat_overflow_status_text,
    archive_picker_focus_missing_status_text,
    archive_picker_folder_parts,
    archive_picker_folder_status_text,
    archive_picker_path_lookup_maps,
    archive_picker_render_status_text,
    archive_picker_reusable_browser_tree_index,
    archive_picker_selected_entry_status_text,
    cached_archive_snapshot_cache_key,
    normalize_archive_path,
)
from cdmw.ui.research import analysis_controller as _research_analysis_controller
from cdmw.ui.research.analysis_task_controller import ResearchAnalysisTaskController
from cdmw.ui.research.analysis_state import (
    ANALYSIS_CONTEXT_HELP_TEXT,
    compare_path_missing_status_text,
    mip_focus_refresh_pending_state,
    missing_mip_focus_state,
    texture_analysis_context_text,
)
from cdmw.ui.research import classification_review_controller as _research_classification_review_controller
from cdmw.ui.research.classification_review_state import (
    can_accept_unknown_current_role,
    classification_review_focus_candidates,
    is_unknown_member_classifiable,
    preferred_unknown_choice_for_member,
    primary_unknown_member,
    semantic_subtype_for_unknown_member,
    unknown_no_current_family_unknown_status_text,
    unknown_no_current_role_status_text,
    unknown_no_selected_families_unknown_status_text,
    unknown_group_classification_text,
    unknown_group_display_name,
    unknown_group_empty_status_text,
    unknown_group_filter_progress_status_text,
    unknown_group_focus_status_text,
    unknown_group_matches_filters,
    unknown_group_package_text,
    unknown_group_ready_status_text,
    unknown_group_target_paths,
    unknown_label_choice_index,
    unknown_label_tuple,
    unknown_member_local_text,
    unknown_removed_current_file_status_text,
    unknown_removed_family_status_text,
    unknown_removed_selected_families_status_text,
    unknown_resolver_control_state,
    unknown_saved_current_file_status_text,
    unknown_saved_current_role_status_text,
    unknown_saved_family_status_text,
    unknown_saved_selected_families_status_text,
    unknown_select_dds_status_text,
    unknown_select_families_status_text,
    unknown_select_family_status_text,
)
from cdmw.ui.research.display_preferences_state import (
    clamp_preview_zoom_factor,
    normalize_research_preview_color_scheme,
    normalize_research_text_highlight_style,
    normalize_research_theme_key,
)
from cdmw.ui.research.layout_state import (
    research_analysis_splitter_default_sizes,
    research_analysis_splitter_responsive_sizes,
    research_analysis_splitter_saved_sizes,
    research_archive_picker_splitter_default_sizes,
    research_groups_splitter_default_sizes,
    research_groups_splitter_responsive_sizes,
    research_groups_splitter_saved_sizes,
    research_main_splitter_default_sizes,
    research_main_splitter_responsive_sizes,
    research_main_splitter_saved_sizes,
    research_notes_splitter_default_sizes,
    research_notes_splitter_responsive_sizes,
    research_notes_splitter_saved_sizes,
    research_reference_splitter_default_sizes,
    research_reference_splitter_responsive_sizes,
    research_reference_splitter_saved_sizes,
    research_unknown_splitter_default_sizes,
    research_unknown_splitter_responsive_sizes,
    research_unknown_splitter_saved_sizes,
)
from cdmw.ui.research.models import (
    archive_picker_folder_key as _archive_picker_folder_key,
    archive_picker_item_kind as _archive_picker_item_kind,
    build_archive_picker_file_item,
    build_archive_picker_folder_item,
    build_budget_class_item,
    build_budget_file_item,
    build_budget_group_item,
    build_budget_profile_item,
    build_classification_item,
    build_heatmap_scope_item,
    build_mip_item,
    build_normal_item,
    build_note_item,
    build_texture_group_item,
    build_ui_constraint_item,
    build_unknown_group_item,
    build_unknown_member_item,
    current_archive_picker_entry_from_item,
    current_unknown_group_from_item,
    find_archive_picker_file_item as _find_archive_picker_file_item,
    item_payload,
    item_user_role,
    selected_unknown_groups_from_items,
    selected_texture_group_from_items,
)
from cdmw.ui.research import notes_controller as _research_notes_controller
from cdmw.ui.research.notes_state import (
    research_note_delete_success_status_text,
    research_note_display_state,
    research_note_save_success_status_text,
    research_note_target_state,
    sorted_research_note_items,
)
from cdmw.ui.research.tree_population import (
    populate_research_classification_tree,
    populate_research_heatmap_tree,
    populate_research_mip_tree,
    populate_research_normal_tree,
    populate_research_reference_tree,
    populate_research_sidecar_tree,
    populate_research_texture_group_tree,
    populate_research_ui_constraint_tree,
)
from cdmw.ui.research.preview_controls import (
    apply_preview_zoom,
    next_manual_preview_zoom,
    set_preview_image_controls_enabled,
    set_preview_zoom_label,
)
from cdmw.ui.research import preview_controller as _research_preview_controller
from cdmw.ui.research.preview_state import (
    archive_picker_clear_preview_state,
    archive_picker_folder_preview_state,
    archive_picker_loading_preview_state,
    research_preview_display_state,
    unknown_clear_preview_state,
    unknown_loading_preview_state,
)
from cdmw.ui.research.progress_helpers import (
    set_progress_error,
    set_progress_idle,
    set_progress_ready,
    set_research_progress,
)
from cdmw.ui.research.tab_builders import build_archive_tab, build_texture_tab
from cdmw.ui.research.tab_side_panel_builders import (
    build_analysis_detail_group,
    build_archive_picker_group,
    build_notes_tab,
)
from cdmw.ui.research import reference_controller as _research_reference_controller
from cdmw.ui.research.reference_payload_state import (
    current_ui_constraint_related_paths,
    normalize_relative_path,
    reference_resolve_already_running_status_text,
    reference_resolve_complete_state,
    reference_resolve_missing_target_status_text,
    reference_resolve_start_state,
    reference_target_load_state,
    reference_row_review_enabled,
    reference_review_incomplete_status_text,
    reference_review_missing_status_text,
    resolved_extract_request_state,
    review_reference_text_search_payload,
    ui_constraint_initial_status_text,
    ui_constraint_refresh_preserved_status_text,
    ui_constraint_refresh_stale_status_text,
    ui_constraint_scan_complete_state,
    ui_constraint_scan_start_state,
)
from cdmw.ui.research import refresh_controller as _research_refresh_controller
from cdmw.ui.research.refresh_population_state import (
    research_refresh_initial_status_text,
    research_refresh_phase_status_text,
    research_refresh_population_rows,
    research_refresh_population_total,
    research_refresh_ready_status_text,
    research_refresh_start_state,
)
from cdmw.ui.research.texture_group_state import (
    texture_group_extract_state,
    texture_group_empty_status_text,
    texture_group_no_available_status_text,
    texture_group_population_selected_status_text,
    texture_group_selected_status_text,
)
from cdmw.ui.research.tree_column_specs import research_tree_column_specs
from cdmw.ui.research.tree_helpers import (
    auto_fit_persisted_research_tree_columns,
    make_research_tree_columns_persistent,
)
from cdmw.ui.research.help_widgets import (
    add_flat_section_help as _add_flat_section_help,
    add_help_row as _add_help_row,
    add_titled_help_header as _add_titled_help_header,
    make_research_help_button as _make_help_button,
    set_help_button_text as _set_help_button_text,
)
from cdmw.ui.research.workers import (
    ReferenceResolveWorker,
    ResearchRefreshWorker,
    UIConstraintRefreshWorker,
    UnknownResolverPreviewWorker,
    shutdown_thread as _shutdown_thread,
)
from cdmw.ui.widgets import (
    ArchiveDetailsEditor,
    EmptyStateTreeWidget,
    FlatSectionPanel,
    PreviewLabel,
    PreviewScrollArea,
    responsive_sidebar_bounds,
)


class ResearchTab(QWidget):
    status_message_requested = Signal(str, bool)
    extract_related_set_requested = Signal(object, str)
    focus_archive_browser_requested = Signal()
    review_reference_in_text_search_requested = Signal(str, str)
    REFRESH_POPULATION_BATCH_SIZE = 80
    REFRESH_GROUP_BATCH_SIZE = 20
    UNKNOWN_GROUP_BATCH_SIZE = 50
    ARCHIVE_PICKER_POPULATION_BATCH_SIZE = 250
    POPULATION_TIMER_INTERVAL_MS = 1
    refresh_archive_picker = _research_archive_picker_controller.refresh_archive_picker
    _archive_picker_view_mode = _research_archive_picker_controller._archive_picker_view_mode
    _populate_archive_picker_tree = _research_archive_picker_controller._populate_archive_picker_tree
    _flush_archive_picker_population_batch = _research_archive_picker_controller._flush_archive_picker_population_batch
    _handle_archive_picker_view_changed = _research_archive_picker_controller._handle_archive_picker_view_changed
    mark_archive_picker_dirty = _research_archive_picker_controller.mark_archive_picker_dirty
    refresh_archive_picker_if_pending = _research_archive_picker_controller.refresh_archive_picker_if_pending
    _rebuild_archive_picker_index = _research_archive_picker_controller._rebuild_archive_picker_index
    _create_archive_picker_folder_item = _research_archive_picker_controller._create_archive_picker_folder_item
    _create_archive_picker_file_item = _research_archive_picker_controller._create_archive_picker_file_item
    _ensure_archive_picker_folder_item_populated = _research_archive_picker_controller._ensure_archive_picker_folder_item_populated
    _handle_archive_picker_item_expanded = _research_archive_picker_controller._handle_archive_picker_item_expanded
    _ensure_archive_picker_folder_path = _research_archive_picker_controller._ensure_archive_picker_folder_path
    _focus_archive_picker_path = _research_archive_picker_controller._focus_archive_picker_path
    _archive_picker_entry_index_for_path = _research_archive_picker_controller._archive_picker_entry_index_for_path
    _archive_picker_entry_for_path = _research_archive_picker_controller._archive_picker_entry_for_path
    _handle_archive_picker_current_item_change = _research_archive_picker_controller._handle_archive_picker_current_item_change
    use_selected_archive_picker_for_reference = _research_archive_picker_controller.use_selected_archive_picker_for_reference
    use_selected_archive_picker_for_note = _research_archive_picker_controller.use_selected_archive_picker_for_note
    _populate_note_target = _research_notes_controller._populate_note_target
    _populate_notes_tree = _research_notes_controller._populate_notes_tree
    _save_note = _research_notes_controller._save_note
    _delete_note = _research_notes_controller._delete_note
    _load_selected_note = _research_notes_controller._load_selected_note
    resolve_references = _research_reference_controller.resolve_references
    focus_references_for_path = _research_reference_controller.focus_references_for_path
    _handle_reference_progress = _research_reference_controller._handle_reference_progress
    _handle_reference_complete = _research_reference_controller._handle_reference_complete
    _handle_reference_error = _research_reference_controller._handle_reference_error
    _cleanup_reference_refs = _research_reference_controller._cleanup_reference_refs
    _populate_reference_rows = _research_reference_controller._populate_reference_rows
    _populate_ui_constraint_rows = _research_reference_controller._populate_ui_constraint_rows
    _populate_sidecar_rows = _research_reference_controller._populate_sidecar_rows
    _handle_reference_selection_changed = _research_reference_controller._handle_reference_selection_changed
    review_selected_reference_in_text_search = _research_reference_controller.review_selected_reference_in_text_search
    _handle_sidecar_selection_changed = _research_reference_controller._handle_sidecar_selection_changed
    _populate_reference_target = _research_reference_controller._populate_reference_target
    extract_resolved_related_set = _research_reference_controller.extract_resolved_related_set
    _populate_heatmap_rows = _research_analysis_controller._populate_heatmap_rows
    _populate_mip_rows = _research_analysis_controller._populate_mip_rows
    _populate_normal_rows = _research_analysis_controller._populate_normal_rows
    _focus_pending_mip_row = _research_analysis_controller._focus_pending_mip_row
    _refresh_texture_analysis_summary = _research_analysis_controller._refresh_texture_analysis_summary
    _handle_mip_selection_changed = _research_analysis_controller._handle_mip_selection_changed
    _handle_normal_selection_changed = _research_analysis_controller._handle_normal_selection_changed
    _show_mip_row_details = _research_analysis_controller._show_mip_row_details
    _show_normal_row_details = _research_analysis_controller._show_normal_row_details
    _apply_analysis_detail_result = _research_analysis_controller._apply_analysis_detail_result
    _handle_analysis_detail_error = _research_analysis_controller._handle_analysis_detail_error
    _show_budget_details = _research_analysis_controller._show_budget_details
    _handle_budget_selection_changed = _research_analysis_controller._handle_budget_selection_changed
    _export_analysis_report = _research_analysis_controller._export_analysis_report
    _handle_analysis_export_complete = _research_analysis_controller._handle_analysis_export_complete
    _handle_analysis_export_error = _research_analysis_controller._handle_analysis_export_error
    _handle_analysis_export_idle = _research_analysis_controller._handle_analysis_export_idle
    refresh_research = _research_refresh_controller.refresh_research
    refresh_ui_constraints = _research_refresh_controller.refresh_ui_constraints
    focus_texture_analysis_for_compare_path = _research_refresh_controller.focus_texture_analysis_for_compare_path
    _handle_refresh_progress = _research_refresh_controller._handle_refresh_progress
    _handle_refresh_complete = _research_refresh_controller._handle_refresh_complete
    _handle_refresh_error = _research_refresh_controller._handle_refresh_error
    _cleanup_refresh_refs = _research_refresh_controller._cleanup_refresh_refs
    _handle_ui_constraint_progress = _research_refresh_controller._handle_ui_constraint_progress
    _handle_ui_constraint_complete = _research_refresh_controller._handle_ui_constraint_complete
    _handle_ui_constraint_error = _research_refresh_controller._handle_ui_constraint_error
    _cleanup_ui_constraint_refs = _research_refresh_controller._cleanup_ui_constraint_refs
    _stop_refresh_population = _research_refresh_controller._stop_refresh_population
    _begin_refresh_population = _research_refresh_controller._begin_refresh_population
    _flush_refresh_population_batch = _research_refresh_controller._flush_refresh_population_batch
    _finalize_texture_group_population = _research_refresh_controller._finalize_texture_group_population
    _finalize_classification_population = _research_refresh_controller._finalize_classification_population
    _finalize_heatmap_population = _research_refresh_controller._finalize_heatmap_population
    _finalize_mip_population = _research_refresh_controller._finalize_mip_population
    _finalize_normal_population = _research_refresh_controller._finalize_normal_population
    _finalize_ui_constraint_population = _research_refresh_controller._finalize_ui_constraint_population
    _finalize_budget_population = _research_refresh_controller._finalize_budget_population
    _finish_refresh_population = _research_refresh_controller._finish_refresh_population
    _populate_texture_groups = _research_refresh_controller._populate_texture_groups
    _selected_texture_group = _research_refresh_controller._selected_texture_group
    _handle_texture_group_selection_changed = _research_refresh_controller._handle_texture_group_selection_changed
    extract_selected_group = _research_refresh_controller.extract_selected_group
    _current_unknown_member = _research_classification_review_controller._current_unknown_member
    _update_unknown_member_group_visibility = _research_classification_review_controller._update_unknown_member_group_visibility
    _current_unknown_classifiable_member = _research_classification_review_controller._current_unknown_classifiable_member
    _handle_unknown_group_selection_changed = _research_classification_review_controller._handle_unknown_group_selection_changed
    _handle_unknown_group_item_selection_changed = _research_classification_review_controller._handle_unknown_group_item_selection_changed
    _handle_unknown_member_selection_changed = _research_classification_review_controller._handle_unknown_member_selection_changed
    _preview_selected_unknown_member = _research_classification_review_controller._preview_selected_unknown_member
    _select_all_unknown_groups = _research_classification_review_controller._select_all_unknown_groups
    _clear_unknown_group_selection = _research_classification_review_controller._clear_unknown_group_selection
    _selected_unknown_label = _research_classification_review_controller._selected_unknown_label
    _select_unknown_label_choice = _research_classification_review_controller._select_unknown_label_choice
    _accept_unknown_current_role = _research_classification_review_controller._accept_unknown_current_role
    _apply_unknown_current_file_label = _research_classification_review_controller._apply_unknown_current_file_label
    _apply_unknown_selected_file_label = _research_classification_review_controller._apply_unknown_selected_file_label
    _apply_unknown_group_label = _research_classification_review_controller._apply_unknown_group_label
    _clear_unknown_current_file_label = _research_classification_review_controller._clear_unknown_current_file_label
    _clear_unknown_selected_file_label = _research_classification_review_controller._clear_unknown_selected_file_label
    _clear_unknown_group_label = _research_classification_review_controller._clear_unknown_group_label
    _update_unknown_resolver_controls = _research_classification_review_controller._update_unknown_resolver_controls
    focus_classification_review_for_paths = _research_classification_review_controller.focus_classification_review_for_paths
    _handle_unknown_show_classified_toggled = _research_classification_review_controller._handle_unknown_show_classified_toggled
    _handle_unknown_name_filter_changed = _research_classification_review_controller._handle_unknown_name_filter_changed
    _handle_unknown_package_filter_changed = _research_classification_review_controller._handle_unknown_package_filter_changed
    _refresh_unknown_resolver_view = _research_classification_review_controller._refresh_unknown_resolver_view
    _current_unknown_resolver_groups = _research_classification_review_controller._current_unknown_resolver_groups
    _populate_unknown_resolver = _research_classification_review_controller._populate_unknown_resolver
    _build_unknown_group_item = _research_classification_review_controller._build_unknown_group_item
    _flush_unknown_group_population_batch = _research_classification_review_controller._flush_unknown_group_population_batch
    _finalize_unknown_group_population = _research_classification_review_controller._finalize_unknown_group_population
    _set_archive_picker_preview_image_controls_enabled = _research_preview_controller._set_archive_picker_preview_image_controls_enabled
    _update_archive_picker_preview_zoom_label = _research_preview_controller._update_archive_picker_preview_zoom_label
    _apply_archive_picker_preview_zoom = _research_preview_controller._apply_archive_picker_preview_zoom
    _set_archive_picker_preview_fit_mode = _research_preview_controller._set_archive_picker_preview_fit_mode
    _set_archive_picker_preview_zoom_factor = _research_preview_controller._set_archive_picker_preview_zoom_factor
    _adjust_archive_picker_preview_zoom = _research_preview_controller._adjust_archive_picker_preview_zoom
    _clear_archive_picker_preview = _research_preview_controller._clear_archive_picker_preview
    _show_archive_picker_folder_preview = _research_preview_controller._show_archive_picker_folder_preview
    _render_archive_picker_preview_for_entry = _research_preview_controller._render_archive_picker_preview_for_entry
    _start_archive_picker_preview_worker = _research_preview_controller._start_archive_picker_preview_worker
    _handle_archive_picker_preview_ready = _research_preview_controller._handle_archive_picker_preview_ready
    _handle_archive_picker_preview_error = _research_preview_controller._handle_archive_picker_preview_error
    _cleanup_archive_picker_preview_refs = _research_preview_controller._cleanup_archive_picker_preview_refs
    _apply_archive_picker_preview_result = _research_preview_controller._apply_archive_picker_preview_result
    _set_unknown_preview_image_controls_enabled = _research_preview_controller._set_unknown_preview_image_controls_enabled
    _update_unknown_preview_zoom_label = _research_preview_controller._update_unknown_preview_zoom_label
    _apply_unknown_preview_zoom = _research_preview_controller._apply_unknown_preview_zoom
    _set_unknown_preview_fit_mode = _research_preview_controller._set_unknown_preview_fit_mode
    _set_unknown_preview_zoom_factor = _research_preview_controller._set_unknown_preview_zoom_factor
    _adjust_unknown_preview_zoom = _research_preview_controller._adjust_unknown_preview_zoom
    _clear_unknown_preview = _research_preview_controller._clear_unknown_preview
    _render_unknown_preview_for_member = _research_preview_controller._render_unknown_preview_for_member
    _start_unknown_preview_worker = _research_preview_controller._start_unknown_preview_worker
    _handle_unknown_preview_ready = _research_preview_controller._handle_unknown_preview_ready
    _handle_unknown_preview_error = _research_preview_controller._handle_unknown_preview_error
    _cleanup_unknown_preview_refs = _research_preview_controller._cleanup_unknown_preview_refs
    _apply_unknown_preview_result = _research_preview_controller._apply_unknown_preview_result

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        if hasattr(self, "_column_autofit_timer"):
            self._column_autofit_timer.start()

    def __init__(
        self,
        *,
        settings,
        base_dir: Path,
        get_archive_entries: Callable[[], Sequence[object]],
        get_filtered_archive_entries: Callable[[], Sequence[object]],
        get_original_root: Callable[[], str],
        get_output_root: Callable[[], str],
        get_app_config: Callable[[], AppConfig],
        get_current_archive_path: Callable[[], str],
        get_current_text_search_path: Callable[[], str],
        get_current_compare_path: Callable[[], str],
        get_archive_browser_tree_state: Optional[Callable[[], Dict[str, object]]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.current_theme_key = self._read_theme_key()
        self.base_dir = base_dir
        self.get_archive_entries = get_archive_entries
        self.get_filtered_archive_entries = get_filtered_archive_entries
        self.get_original_root = get_original_root
        self.get_output_root = get_output_root
        self.get_app_config = get_app_config
        self.get_current_archive_path = get_current_archive_path
        self.get_current_text_search_path = get_current_text_search_path
        self.get_current_compare_path = get_current_compare_path
        self.get_archive_browser_tree_state = get_archive_browser_tree_state
        self.notes_path = self.base_dir / "research_notes.json"
        self.notes: Dict[str, ResearchNote] = research_service.notes.load(self.notes_path)
        self.refresh_thread: Optional[QThread] = None
        self.refresh_worker: Optional[ResearchRefreshWorker] = None
        self.ui_constraint_thread: Optional[QThread] = None
        self.ui_constraint_worker: Optional[UIConstraintRefreshWorker] = None
        self.resolve_thread: Optional[QThread] = None
        self.resolve_worker: Optional[ReferenceResolveWorker] = None
        self.unknown_preview_thread: Optional[QThread] = None
        self.unknown_preview_worker: Optional[UnknownResolverPreviewWorker] = None
        self.unknown_preview_request_id = 0
        self.pending_unknown_preview_request: Optional[tuple[int, Optional[ArchiveEntry]]] = None
        self.unknown_preview_fit_to_view = True
        self.unknown_preview_zoom_factor = 1.0
        self.archive_picker_preview_thread: Optional[QThread] = None
        self.archive_picker_preview_worker: Optional[UnknownResolverPreviewWorker] = None
        self.analysis_task_controller = ResearchAnalysisTaskController(self)
        self.archive_picker_preview_request_id = 0
        self.pending_archive_picker_preview_request: Optional[tuple[int, Optional[ArchiveEntry]]] = None
        self.archive_picker_preview_fit_to_view = True
        self.archive_picker_preview_zoom_factor = 1.0
        self.research_payload: Dict[str, object] = {}
        self.reference_payload: Dict[str, object] = {}
        self.pending_mip_focus_relative_path = ""
        self.archive_snapshot_cache: Dict[str, Dict[str, object]] = {}
        self.pending_archive_snapshot_cache_key = ""
        self.archive_picker_entries: List[ArchiveEntry] = []
        self.archive_picker_entry_index_by_path: Dict[str, int] = {}
        self.archive_picker_entry_by_path: Dict[str, ArchiveEntry] = {}
        self.archive_picker_lazy_entry_index_by_path: Dict[str, int] = {}
        self.archive_picker_child_folders: Dict[tuple[str, ...], List[tuple[str, tuple[str, ...]]]] = {}
        self.archive_picker_direct_files: Dict[tuple[str, ...], List[int]] = {}
        self.archive_picker_folder_entry_indexes: Dict[tuple[str, ...], List[int]] = {}
        self.archive_picker_folder_preview_stats: Dict[tuple[str, ...], tuple[int, int, int]] = {}
        self.archive_picker_items_by_folder_key: Dict[tuple[str, ...], QTreeWidgetItem] = {}
        self.archive_picker_flat_render_limit = 5000
        self.archive_picker_flat_rendered_count = 0
        self._pending_archive_picker_flat_total = 0
        self._pending_archive_picker_flat_index = 0
        self.archive_picker_refresh_pending = False
        self.defer_archive_picker_refresh = True
        self._column_autofit_timer = QTimer(self)
        self._column_autofit_timer.setSingleShot(True)
        self._column_autofit_timer.setInterval(80)
        self._column_autofit_timer.timeout.connect(self.auto_fit_columns)
        self.classification_registry_path = texture_classification_registry_path()
        self.pending_classification_review_focus_keys: set[str] = set()
        self._classification_review_focus_uses_full_archive = False
        self._archive_snapshot_key_cache: Dict[tuple[int, int, str, str], str] = {}
        self._ui_constraint_scan_archive_key = ""
        self._pending_ui_constraint_archive_key = ""
        self._pending_refresh_full_archive_key = ""
        self._populating_unknown_resolver_controls = False
        self._refresh_population_timer = QTimer(self)
        self._refresh_population_timer.setSingleShot(True)
        self._refresh_population_timer.setInterval(self.POPULATION_TIMER_INTERVAL_MS)
        self._refresh_population_timer.timeout.connect(self._flush_refresh_population_batch)
        self._refresh_population_phases: List[Dict[str, object]] = []
        self._refresh_population_phase_index = 0
        self._refresh_population_total = 0
        self._refresh_population_processed = 0
        self._unknown_population_timer = QTimer(self)
        self._unknown_population_timer.setSingleShot(True)
        self._unknown_population_timer.setInterval(self.POPULATION_TIMER_INTERVAL_MS)
        self._unknown_population_timer.timeout.connect(self._flush_unknown_group_population_batch)
        self._archive_picker_population_timer = QTimer(self)
        self._archive_picker_population_timer.setSingleShot(True)
        self._archive_picker_population_timer.setInterval(self.POPULATION_TIMER_INTERVAL_MS)
        self._archive_picker_population_timer.timeout.connect(self._flush_archive_picker_population_batch)
        self._pending_unknown_source_groups: List[UnknownResolverGroup] = []
        self._pending_unknown_groups: List[UnknownResolverGroup] = []
        self._pending_unknown_previous_group_key = ""
        self._pending_unknown_showing_classified = False
        self._pending_unknown_population_total = 0
        self._pending_unknown_scanned_total = 0
        self._pending_research_view_entry_count = 0
        self._pending_research_full_archive_entry_count = 0
        self._pending_research_uses_full_archive_view = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.refresh_button = QPushButton("Refresh Research")
        self.refresh_status_label = QLabel(
            "Ready. Research lists follow the current Archive Browser view, while DDS semantics can still use loaded .pac.xml / .pami sidecars when available."
        )
        self.refresh_status_label.setWordWrap(True)
        self.refresh_status_label.setObjectName("HintLabel")
        self.refresh_progress = QProgressBar()
        self.refresh_progress.setRange(0, 1)
        self.refresh_progress.setValue(0)
        self.refresh_progress.setFormat("Idle")
        self.refresh_progress.setMaximumWidth(180)
        self.refresh_progress.setMaximumHeight(18)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.refresh_status_label, stretch=1)
        top_row.addWidget(self.refresh_progress)
        root_layout.addLayout(top_row)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.main_splitter, stretch=1)

        self.tab_widget = QTabWidget()
        self.main_splitter.addWidget(self.tab_widget)

        self.archive_tab = build_archive_tab(self)
        self.texture_tab = build_texture_tab(self)
        self.notes_tab = build_notes_tab(self)
        self.tab_widget.addTab(self.archive_tab, "Archive Insights")
        self.tab_widget.addTab(self.texture_tab, "Texture Analysis")
        self.tab_widget.addTab(self.notes_tab, "Notes")
        self.right_panel_stack = QStackedWidget()
        self.archive_picker_group = build_archive_picker_group(self)
        self.analysis_detail_group = build_analysis_detail_group(self)
        self.right_panel_stack.addWidget(self.archive_picker_group)
        self.right_panel_stack.addWidget(self.analysis_detail_group)
        self.main_splitter.addWidget(self.right_panel_stack)
        details_min, _details_pref, _details_max = responsive_sidebar_bounds(self, role="wide")
        self.tab_widget.setMinimumWidth(420)
        self.right_panel_stack.setMinimumWidth(details_min)
        self.right_panel_stack.setMaximumWidth(16777215)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes(research_main_splitter_default_sizes(details_min))

        self.refresh_button.clicked.connect(self.refresh_research)
        self.ui_constraint_refresh_button.clicked.connect(self.refresh_ui_constraints)
        self.reference_use_archive_button.clicked.connect(
            self.use_selected_archive_picker_for_reference
        )
        self.reference_resolve_button.clicked.connect(self.resolve_references)
        self.reference_extract_button.clicked.connect(self.extract_resolved_related_set)
        self.reference_review_text_button.clicked.connect(self.review_selected_reference_in_text_search)
        self.reference_tree.currentItemChanged.connect(self._handle_reference_selection_changed)
        self.ui_constraint_tree.currentItemChanged.connect(self._handle_reference_selection_changed)
        self.sidecar_tree.currentItemChanged.connect(self._handle_sidecar_selection_changed)
        self.texture_group_extract_button.clicked.connect(self.extract_selected_group)
        self.texture_group_tree.currentItemChanged.connect(self._handle_texture_group_selection_changed)
        self.unknown_group_tree.currentItemChanged.connect(self._handle_unknown_group_selection_changed)
        self.unknown_group_tree.itemSelectionChanged.connect(self._handle_unknown_group_item_selection_changed)
        self.unknown_member_tree.currentItemChanged.connect(self._handle_unknown_member_selection_changed)
        self.unknown_show_classified_checkbox.toggled.connect(self._handle_unknown_show_classified_toggled)
        self.unknown_name_filter_edit.textChanged.connect(self._handle_unknown_name_filter_changed)
        self.unknown_package_filter_edit.textChanged.connect(self._handle_unknown_package_filter_changed)
        self.unknown_select_all_button.clicked.connect(self._select_all_unknown_groups)
        self.unknown_clear_family_selection_button.clicked.connect(self._clear_unknown_group_selection)
        self.unknown_preview_button.clicked.connect(self._preview_selected_unknown_member)
        self.unknown_accept_current_role_button.clicked.connect(self._accept_unknown_current_role)
        self.unknown_apply_current_file_button.clicked.connect(self._apply_unknown_current_file_label)
        self.unknown_apply_selected_button.clicked.connect(self._apply_unknown_selected_file_label)
        self.unknown_apply_group_button.clicked.connect(self._apply_unknown_group_label)
        self.unknown_clear_current_file_button.clicked.connect(self._clear_unknown_current_file_label)
        self.unknown_clear_selected_button.clicked.connect(self._clear_unknown_selected_file_label)
        self.unknown_clear_group_button.clicked.connect(self._clear_unknown_group_label)
        self.unknown_preview_zoom_fit_button.clicked.connect(self._set_unknown_preview_fit_mode)
        self.unknown_preview_zoom_100_button.clicked.connect(lambda: self._set_unknown_preview_zoom_factor(1.0))
        self.unknown_preview_zoom_out_button.clicked.connect(lambda: self._adjust_unknown_preview_zoom(-1))
        self.unknown_preview_zoom_in_button.clicked.connect(lambda: self._adjust_unknown_preview_zoom(1))
        self.export_report_csv_button.clicked.connect(lambda: self._export_analysis_report(".csv"))
        self.export_report_json_button.clicked.connect(lambda: self._export_analysis_report(".json"))
        self.tab_widget.currentChanged.connect(self._handle_research_subtab_changed)
        self.archive_insights_tabs.currentChanged.connect(self._handle_archive_insights_subtab_changed)
        self.notes_use_archive_button.clicked.connect(
            self.use_selected_archive_picker_for_note
        )
        self.notes_use_search_button.clicked.connect(
            lambda: self._populate_note_target("text_search", self.get_current_text_search_path())
        )
        self.notes_use_compare_button.clicked.connect(
            lambda: self._populate_note_target("compare", self.get_current_compare_path())
        )
        self.notes_save_button.clicked.connect(self._save_note)
        self.notes_delete_button.clicked.connect(self._delete_note)
        self.notes_tree.currentItemChanged.connect(self._load_selected_note)
        self._populate_notes_tree()
        self._handle_research_subtab_changed(self.tab_widget.currentIndex())
        self._clear_unknown_preview("Select an unknown DDS file to preview it here.")
        self._clear_archive_picker_preview("Select a file in Archive Files to preview it here.")
        self.archive_picker_refresh_pending = True
        self.defer_archive_picker_refresh = False
        QTimer.singleShot(0, self._apply_responsive_splitter_defaults)

    def _read_theme_key(self) -> str:
        return normalize_research_theme_key(self.settings.value("appearance/theme", DEFAULT_UI_THEME))

    def _current_text_highlight_style(self) -> str:
        return normalize_research_text_highlight_style(
            self.settings.value("appearance/log_text_style", DEFAULT_UI_LOG_TEXT_STYLE)
        )

    def _current_preview_color_scheme(self) -> str:
        return normalize_research_preview_color_scheme(
            self.settings.value("appearance/preview_color_scheme", DEFAULT_UI_PREVIEW_COLOR_SCHEME)
        )

    def _apply_archive_picker_preview_text_style(self) -> None:
        style = self._current_text_highlight_style()
        preview_scheme = self._current_preview_color_scheme()
        for editor in (self.archive_picker_preview_details_edit,):
            editor.set_highlight_style(style)
            editor.set_color_scheme(preview_scheme)

    def set_theme(self, theme_key: str) -> None:
        self.current_theme_key = str(theme_key or DEFAULT_UI_THEME)
        self.archive_picker_preview_details_edit.set_theme(self.current_theme_key)
        self._apply_archive_picker_preview_text_style()

    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        return (
            ("refresh_thread", self.refresh_thread, self.refresh_worker),
            ("ui_constraint_thread", self.ui_constraint_thread, self.ui_constraint_worker),
            ("resolve_thread", self.resolve_thread, self.resolve_worker),
            ("unknown_preview_thread", self.unknown_preview_thread, self.unknown_preview_worker),
            ("archive_picker_preview_thread", self.archive_picker_preview_thread, self.archive_picker_preview_worker),
        ) + self.analysis_task_controller.iter_shutdown_workers()

    def request_shutdown(self) -> None:
        self._refresh_population_timer.stop()
        self._unknown_population_timer.stop()
        self.analysis_task_controller.request_shutdown()
        if self.refresh_worker is not None:
            self.refresh_worker.stop()
        if self.ui_constraint_worker is not None:
            self.ui_constraint_worker.stop()
        if self.resolve_worker is not None:
            self.resolve_worker.stop()
        if self.unknown_preview_worker is not None:
            self.unknown_preview_worker.stop()
        if self.archive_picker_preview_worker is not None:
            self.archive_picker_preview_worker.stop()
        for _name, thread, _worker in self.iter_shutdown_workers():
            _shutdown_thread(thread)

    def shutdown(self) -> None:
        self.request_shutdown()


    def apply_responsive_splitter_sizes(self, total_width: Optional[int] = None) -> None:
        details_min, _details_pref, _details_max = responsive_sidebar_bounds(self, role="wide")
        if hasattr(self, "right_panel_stack"):
            self.right_panel_stack.setMinimumWidth(details_min)
            self.right_panel_stack.setMaximumWidth(16777215)
        total_width = total_width or max(1, self.width() - 32)
        self.main_splitter.setSizes(research_main_splitter_responsive_sizes(total_width, details_min))
        if hasattr(self, "groups_splitter"):
            self.groups_splitter.setSizes(research_groups_splitter_responsive_sizes(total_width))
        if hasattr(self, "unknown_splitter"):
            self.unknown_splitter.setSizes(research_unknown_splitter_responsive_sizes(total_width))
        if hasattr(self, "reference_splitter"):
            self.reference_splitter.setSizes(research_reference_splitter_responsive_sizes(total_width))
        if hasattr(self, "analysis_splitter"):
            self.analysis_splitter.setSizes(research_analysis_splitter_responsive_sizes(total_width))
        if hasattr(self, "notes_splitter"):
            self.notes_splitter.setSizes(research_notes_splitter_responsive_sizes(total_width))
        QTimer.singleShot(0, self.auto_fit_columns)

    def auto_fit_columns(self) -> None:
        for spec in research_tree_column_specs():
            auto_fit_persisted_research_tree_columns(
                getattr(self, spec.tree_attr),
                self.settings,
                spec.storage_name,
                stretch_column=spec.stretch_column,
                min_widths=spec.min_widths,
            )

    def _apply_responsive_splitter_defaults(self) -> None:
        self.apply_responsive_splitter_sizes()

    def set_main_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        details_min, _details_pref, _details_max = responsive_sidebar_bounds(self, role="wide")
        if hasattr(self, "right_panel_stack"):
            self.right_panel_stack.setMaximumWidth(16777215)
        available_width = total_width or max(1, self.width() - 32)
        self.main_splitter.setSizes(research_main_splitter_saved_sizes(available_width, sizes, details_min))

    def set_groups_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        available_width = total_width or max(1, self.width() - 32)
        self.groups_splitter.setSizes(research_groups_splitter_saved_sizes(available_width, sizes))

    def set_unknown_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        available_width = total_width or max(1, self.width() - 32)
        self.unknown_splitter.setSizes(research_unknown_splitter_saved_sizes(available_width, sizes))

    def set_reference_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        available_width = total_width or max(1, self.width() - 32)
        self.reference_splitter.setSizes(research_reference_splitter_saved_sizes(available_width, sizes))

    def set_analysis_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        available_width = total_width or max(1, self.width() - 32)
        self.analysis_splitter.setSizes(research_analysis_splitter_saved_sizes(available_width, sizes))

    def set_notes_splitter_sizes(self, sizes: Sequence[int], *, total_width: Optional[int] = None) -> None:
        available_width = total_width or max(1, self.width() - 32)
        self.notes_splitter.setSizes(research_notes_splitter_saved_sizes(available_width, sizes))

    def main_splitter_sizes(self) -> List[int]:
        return self.main_splitter.sizes()

    def groups_splitter_sizes(self) -> List[int]:
        return self.groups_splitter.sizes()

    def unknown_splitter_sizes(self) -> List[int]:
        return self.unknown_splitter.sizes()

    def reference_splitter_sizes(self) -> List[int]:
        return self.reference_splitter.sizes()

    def analysis_splitter_sizes(self) -> List[int]:
        return self.analysis_splitter.sizes()

    def notes_splitter_sizes(self) -> List[int]:
        return self.notes_splitter.sizes()


    def _populate_classifications(self, rows: object) -> None:
        populate_research_classification_tree(self.classifier_tree, rows)


    def _clear_pending_classification_review_focus(self) -> None:
        self.pending_classification_review_focus_keys.clear()
        self._classification_review_focus_uses_full_archive = False


    def _handle_research_subtab_changed(self, index: int) -> None:
        del index
        self._update_research_side_panel()

    def _handle_archive_insights_subtab_changed(self, _index: int) -> None:
        self._update_research_side_panel()

    def _update_research_side_panel(self) -> None:
        widget = self.tab_widget.currentWidget()
        if widget is self.texture_tab:
            self.right_panel_stack.setVisible(True)
            self.right_panel_stack.setCurrentWidget(self.analysis_detail_group)
            return
        current_archive_tab = self.archive_insights_tabs.currentWidget()
        if current_archive_tab is getattr(self, "classification_review_tab", None):
            self.right_panel_stack.setVisible(False)
            return
        if not self.defer_archive_picker_refresh:
            self.refresh_archive_picker_if_pending()
        self.right_panel_stack.setVisible(True)
        self.right_panel_stack.setCurrentWidget(self.archive_picker_group)

    def _ensure_archive_picker_ready(self) -> None:
        if self.defer_archive_picker_refresh:
            return
        self.refresh_archive_picker_if_pending()
