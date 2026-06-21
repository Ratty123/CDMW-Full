from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import traceback
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.domain.mesh.validation import mesh_import_mode_availability
from cdmw.services.diagnostics_service import (
    RuntimeEventRecorder,
    add_persisted_crash_breadcrumbs as _add_persisted_crash_breadcrumbs_service,
    check_previous_unclean_exit as _check_previous_unclean_exit_service,
    cleanup_native_fault_log_on_exit as _cleanup_native_fault_log_file,
    enable_native_fault_log as _enable_native_fault_log_file,
    format_timing_summary as _format_timing_summary,
    format_thread_dump as _format_thread_dump,
    merge_timing_maps as _merge_timing_maps,
    process_is_alive as _process_is_alive,
    read_jsonl_tail as _read_jsonl_tail,
    should_write_crash_report as _should_write_crash_report,
    start_hang_watchdog as _start_hang_watchdog_service,
    thread_exception_report as _thread_exception_report,
    timing_value as _timing_value,
    uncaught_exception_report as _uncaught_exception_report,
    unraisable_exception_report as _unraisable_exception_report,
    write_app_heartbeat as _write_app_heartbeat,
    write_crash_report as _write_crash_report_file,
    write_ui_breadcrumb as _write_ui_breadcrumb_file,
)
from cdmw.services.settings_service import create_settings, resolve_settings_file_path
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin
from cdmw.ui.archive_browser.action_controls import ArchiveBrowserActionControlsMixin
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.attachment_batch import ArchiveAttachmentBatchMixin
from cdmw.ui.archive_browser.attachment_donor_picker_dialog import ArchiveAttachmentDonorPickerDialogMixin
from cdmw.ui.archive_browser.attachment_placement_diff_dialog import ArchiveAttachmentPlacementDiffDialogMixin
from cdmw.ui.archive_browser.attachment_safe_placement_dialog import ArchiveAttachmentSafePlacementDialogMixin
from cdmw.ui.archive_browser.attachment_icons import ArchiveAttachmentIconMixin
from cdmw.ui.archive_browser.attachment_loose_files import ArchiveAttachmentLooseFileMixin
from cdmw.ui.archive_browser.attachment_package import ArchiveAttachmentPackageMixin
from cdmw.ui.archive_browser.attachment_plan import ArchiveAttachmentPlanMixin
from cdmw.ui.archive_browser.attachment_socket_editor import ArchiveAttachmentSocketEditorMixin
from cdmw.ui.archive_browser.attachment_visual_dialog import ArchiveAttachmentVisualDialogMixin
from cdmw.ui.archive_browser.attachment_visual_payload import ArchiveAttachmentVisualPayloadMixin
from cdmw.ui.archive_browser.weapon_placement_studio import ArchiveWeaponPlacementStudioMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_layout import ArchiveAssetFamilyLayoutMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.asset_catalog import ArchiveAssetCatalogMixin
from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
from cdmw.ui.archive_browser.asset_catalog_scope import ArchiveAssetCatalogScopeMixin
from cdmw.ui.archive_browser.character_dependency_export import ArchiveCharacterDependencyExportMixin
from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
from cdmw.ui.archive_browser.extraction import ArchiveExtractionMixin
from cdmw.ui.archive_browser.filter_controls import ArchiveFilterControlsMixin
from cdmw.ui.archive_browser.filter_workers import ArchiveFilterWorkerMixin
from cdmw.ui.archive_browser.files_panel import ArchiveFilesPanelMixin
from cdmw.ui.archive_browser.index_workers import ArchiveIndexWorkerMixin
from cdmw.ui.archive_browser.filters import (
    ArchiveFilterStateMixin,
)
from cdmw.ui.archive_browser.header import ArchiveBrowserHeaderMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin, ArchiveBrowserTreeControllerMixin
from cdmw.ui.archive_browser.appearance_common import ArchiveAppearanceCommonMixin
from cdmw.ui.archive_browser.appearance_composite import ArchiveAppearanceCompositeMixin
from cdmw.ui.archive_browser.appearance_swap import ArchiveAppearanceSwapMixin
from cdmw.ui.archive_browser.binary_sidecar_actions import ArchiveBinarySidecarActionsMixin
from cdmw.ui.archive_browser.hkx_document_actions import ArchiveHkxDocumentActionsMixin
from cdmw.ui.archive_browser.hkx_editor_dialog import ArchiveHkxEditorDialogMixin
from cdmw.ui.archive_browser.static_replacement_dialog import ArchiveStaticReplacementDialogMixin
from cdmw.ui.archive_browser.import_actions import ArchiveImportActionsMixin
from cdmw.ui.archive_browser.mesh_builder_lifecycle import ArchiveMeshBuilderLifecycleMixin
from cdmw.ui.archive_browser.mesh_dds_preview import ArchiveMeshDdsPreviewMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.mesh_swap_scope_dialog import ArchiveMeshSwapScopeDialogMixin
from cdmw.ui.archive_browser.mesh_launch_flow import ArchiveMeshLaunchFlowMixin
from cdmw.ui.archive_browser.mesh_patch_flow import ArchiveMeshPatchFlowMixin
from cdmw.ui.archive_browser.patch_actions import ArchivePatchActionsMixin
from cdmw.ui.archive_browser.mesh_import_export import ArchiveMeshImportExportMixin
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.archive_browser.mesh_setup_helpers import ArchiveMeshSetupHelperMixin
from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.material_finder import ArchiveMaterialFinderMixin
from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin
from cdmw.ui.archive_browser.material_sidecar_editor_dialog import ArchiveMaterialSidecarEditorMixin
from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin
from cdmw.ui.tools.mod_package_retrofit import ArchiveModPackageRetrofitDialogMixin
from cdmw.ui.archive_browser.progress import ArchiveProgressMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.sidecar_index import ArchiveSidecarIndexMixin
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.reference_export import ArchiveReferenceExportMixin
from cdmw.ui.archive_browser.reference_preview import ArchiveReferencePreviewMixin
from cdmw.ui.archive_browser.source_picker_dialog import ArchiveSourcePickerDialogMixin
from cdmw.ui.archive_browser.source_mix_actions import ArchiveSourceMixActionsMixin
from cdmw.ui.archive_browser.source_mix_overlay import ArchiveSourceMixOverlayMixin
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_d3d11_process import ArchivePreviewD3D11ProcessMixin
from cdmw.ui.archive_browser.preview_d3d11_runtime import ArchivePreviewD3D11RuntimeMixin
from cdmw.ui.archive_browser.preview_d3d11_worker import ArchivePreviewD3D11WorkerMixin
from cdmw.ui.archive_browser.preview_details import ArchivePreviewDetailsMixin
from cdmw.ui.archive_browser.preview_layout import ArchivePreviewLayoutMixin
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.preview_memory import ArchivePreviewMemoryAuditMixin
from cdmw.ui.archive_browser.preview_native_core import ArchivePreviewNativeCoreLifecycleMixin
from cdmw.ui.archive_browser.preview_native_prefetch import ArchivePreviewNativePrefetchMixin
from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_result import ArchivePreviewResultMixin
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.preview_state import ArchivePreviewStateMixin
from cdmw.ui.archive_browser.preview_timing import ArchivePreviewTimingMixin
from cdmw.ui.archive_browser.preview_zoom import ArchivePreviewZoomMixin
from cdmw.ui.archive_browser.ui_formatting import ArchiveUiFormattingMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin, ArchiveWorkerLifecycleMixin
from cdmw.ui.shell.settings_autosave import SettingsAutosaveMixin
from cdmw.ui.shell.settings_persistence import SettingsPersistenceMixin
from cdmw.ui.shell.about_controller import AboutControllerMixin
from cdmw.ui.shell.about_documentation import AboutDocumentationMixin
from cdmw.ui.shell.diagnostics_controller import (
    d3d11_cache_event_user_label as _d3d11_cache_event_user_label,
    d3d11_status_file_signature as _d3d11_status_file_signature,
    qt_wrapper_is_valid as _qt_wrapper_is_valid,
    start_heartbeat_timer as _start_heartbeat_timer_controller,
    windows_process_memory_snapshot as _windows_process_memory_snapshot,
)
from cdmw.ui.shell.activation_controller import ActivationControllerMixin
from cdmw.ui.shell.app_startup import (
    finish_gui_startup_smoke_if_requested,
    prepare_shell_application,
    prepare_shell_main_window,
    run_shell_event_loop,
)
from cdmw.ui.shell.icon_controller import apply_windows_app_user_model_id
from cdmw.ui.shell.language_controller import LanguageControllerMixin
from cdmw.ui.shell.log_controller import LogControllerMixin
from cdmw.ui.shell.main_window_proxy import (
    MAIN_WINDOW_CLASS_ONLY_ENV,
    MainWindow,
    set_loaded_main_window_class,
)
from cdmw.ui.shell.menus import ShellMenusMixin
from cdmw.ui.shell.responsiveness_controller import (
    ResponsivenessControllerMixin,
    expand_tree_columns_to_available_width,
)
from cdmw.ui.shell.root_layout import ShellRootLayoutMixin
from cdmw.ui.shell.startup_controller import StartupPromptMixin, queue_startup_archive_autoload
from cdmw.ui.shell.startup_splash import create_startup_splash, make_startup_splash_pump
from cdmw.ui.shell.signal_wiring import ShellSignalWiringMixin
from cdmw.ui.shell.startup_restore import ShellStartupRestoreMixin
from cdmw.ui.shell.support_dialog import SupportDialogMixin
from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin
from cdmw.ui.shell.window_bootstrap_state import ShellWindowBootstrapStateMixin
from cdmw.ui.shell.window_runtime_state import ShellWindowRuntimeStateMixin
from cdmw.ui.shell.theme_controller import (
    ThemeChangeBusyOverlay,
    ThemeControllerMixin,
    apply_window_text_highlight_style,
    build_monospace_font,
    read_log_text_style,
    read_text_color_scheme,
)
from cdmw.ui.app_icon import load_app_icon
from cdmw.ui.texture_workflow.compare_panel import TextureWorkflowComparePanelMixin
from cdmw.ui.texture_workflow.config_collection import TextureWorkflowConfigCollectionMixin
from cdmw.ui.texture_workflow.compare_preview import TextureWorkflowComparePreviewMixin
from cdmw.ui.texture_workflow.dds_output_panel import TextureWorkflowDdsOutputPanelMixin
from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin
from cdmw.ui.texture_workflow.editor_handoff import TextureWorkflowEditorHandoffMixin
from cdmw.ui.texture_workflow.paths_panel import TextureWorkflowPathsPanelMixin
from cdmw.ui.texture_workflow.progress_panel import TextureWorkflowProgressPanelMixin
from cdmw.ui.texture_workflow.settings_panel import TextureWorkflowSettingsPanelMixin
from cdmw.ui.texture_workflow.shell_controls import TextureWorkflowShellControlsMixin
from cdmw.ui.texture_workflow.setup_panel import TextureWorkflowSetupPanelMixin
from cdmw.ui.texture_workflow.setup_overview_panel import TextureWorkflowSetupOverviewPanelMixin
from cdmw.ui.texture_workflow.upscale_backend_panel import TextureWorkflowUpscaleBackendPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_ui import TextureWorkflowProfilesUiMixin
from cdmw.ui.texture_workflow.workers import TextureWorkflowWorkerMixin
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin


try:
    import shiboken6
except Exception:  # pragma: no cover - shipped with PySide6, defensive for test-only imports.
    shiboken6 = None


from cdmw.constants import APP_TITLE, APP_VERSION



def run_gui() -> int:
    try:
        from PySide6.QtCore import QByteArray, QModelIndex, QEvent, QPoint, QPointF, QProcess, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, QObject, Signal, Slot, QSignalBlocker
        from PySide6.QtGui import (
            QBrush,
            QColor,
            QDesktopServices,
            QFont,
            QIcon,
            QImage,
            QImageReader,
            QLinearGradient,
            QPainter,
            QPainterPath,
            QPen,
            QPixmap,
            QPolygonF,
            QKeySequence,
            QShortcut,
            QTextCursor,
        )
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QApplication,
            QCheckBox,
            QColorDialog,
            QComboBox,
            QDialog,
            QDoubleSpinBox,
            QFileDialog,
            QGridLayout,
            QGroupBox,
            QHeaderView,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QLineEdit,
            QListView,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMenu,
            QMessageBox,
            QPlainTextEdit,
            QProgressBar,
            QProgressDialog,
            QPushButton,
            QRadioButton,
            QSizePolicy,
            QSlider,
            QStackedWidget,
            QSpinBox,
            QTabWidget,
            QTableWidget,
            QTableWidgetItem,
            QTextBrowser,
            QToolButton,
            QTreeWidget,
            QTreeWidgetItem,
            QSystemTrayIcon,
        )
    except ImportError:
        print("PySide6 is required to run the GUI. Install it with: pip install PySide6", file=sys.stderr)
        return 1

    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.shell.app_state import AppState
    from cdmw.ui.shell.close_controller import CloseControllerMixin
    from cdmw.ui.shell.dashboard_controller import DashboardControllerMixin
    from cdmw.ui.shell.tab_registry import DetachedToolWindow, TabRegistry

    from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
    from cdmw.ui.archive_browser.weapon_placement_map import WeaponPlacementStudioPlacementMap

    from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette, build_app_stylesheet, get_theme
    from cdmw.ui.widgets import (
        AboutDialog,
        ArchiveDetailsEditor,
        available_layout_size_for,
        available_screen_size_for,
        available_screen_width_for,
        CodePreviewEditor,
        FlatSectionPanel,
        clamp_splitter_sizes,
        CollapsibleSection,
        has_persistent_tree_column_widths,
        LogHighlighter,
        make_tree_columns_persistent,
        MediaPreviewWidget,
        NativePreviewPanel,
        PreviewSyntaxHighlighter,
        PreviewLabel,
        PreviewScrollArea,
    )
    from cdmw.ui.archive_browser.model import (
        ArchiveBrowserRowPayload,
        ArchiveBrowserTreeView,
    )
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog
    from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
    from cdmw.rendering.model_preview_prepare import (
        MeshPreviewCacheSignature,
        MeshPreviewDirtyFlags,
        mesh_editor_load_trace_enabled,
        prepare_model_preview,
    )
    from cdmw.rendering.native_preview_core import (
        NativePreviewCoreAttempt,
        NativePreviewCoreServiceClient,
        find_native_preview_core_binary,
        render_settings_to_native_preview_core_dict,
        run_native_preview_core_preview_job,
        shutdown_native_preview_core_service,
    )
    from cdmw.rendering.native_preview_package_cache import (
        NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA,
        native_preview_package_cache_budget,
        prune_native_preview_package_cache,
        store_native_preview_package_cache,
    )
    from cdmw.modding.pac_xml_profiles import (
        clear_pac_xml_profile_index_cache,
        default_pac_xml_profile_cache_path,
    )
    from cdmw.ui.policy_preview_dialog import TexturePolicyPreviewDialog
    from cdmw.ui.safe_upscale_wizard import SafeUpscaleWizard
    from cdmw.ui.shell.model_library_bridge import ModelLibraryShellBridgeMixin
    from cdmw.ui.shell.navigation_controller import NavigationControllerMixin
    from cdmw.ui.shell.path_controller import PathControllerMixin
    from cdmw.ui.shell.profile_controller import ProfileControllerMixin
    from cdmw.ui.shell.utility_controller import UtilityControllerMixin
    from cdmw.ui.shell.workspace_layout import ShellWorkspaceLayoutMixin
    from cdmw.ui.shell.workspace_controller import WorkspaceControllerMixin

    settings_file_path = resolve_settings_file_path()
    create_settings(settings_file_path=settings_file_path)
    _workspace_paths = workspace_paths(settings_file_path.parent)
    crash_reports_dir = _workspace_paths["crash_reports_dir"]
    heartbeat_path = crash_reports_dir / "app_heartbeat.json"
    _default_sys_excepthook = sys.excepthook
    _default_threading_excepthook = getattr(threading, "excepthook", None)
    _default_unraisablehook = getattr(sys, "unraisablehook", None)
    _active_main_window: Optional["MainWindow"] = None
    _capture_crash_details_enabled = False
    _session_id = f"{os.getpid()}-{int(time.time() * 1000)}"
    _heartbeat_stop_event = threading.Event()
    _heartbeat_lock = threading.Lock()
    _last_heartbeat_written_at = time.time()
    _heartbeat_phase = "starting"
    _heartbeat_timer: Optional[QTimer] = None
    _fault_log_handle = None
    _cached_crash_context: Dict[str, object] = {}
    _previous_session_unclean = False
    _runtime_event_log_path = crash_reports_dir / "runtime_events_current.jsonl"
    _native_diagnostic_log_path = crash_reports_dir / "native_events_current.jsonl"
    _runtime_event_recorder = RuntimeEventRecorder(
        _runtime_event_log_path,
        session_id=_session_id,
        memory_snapshot=_windows_process_memory_snapshot,
    )
    _last_active_operation: Dict[str, object] = {
        "operation": "startup",
        "timestamp": time.time(),
        "pid": os.getpid(),
        "session_id": _session_id,
    }
    os.environ.setdefault("CDMW_CRASH_DIR", str(crash_reports_dir))
    os.environ.setdefault("CDMW_NATIVE_DIAGNOSTIC_LOG", str(_native_diagnostic_log_path))
    os.environ.setdefault("CDMW_TEMP_CACHE_ROOT", str(_workspace_paths["archive_cache_root"]))

    def _set_crash_capture_enabled(enabled: bool) -> None:
        nonlocal _capture_crash_details_enabled
        _capture_crash_details_enabled = bool(enabled)

    def _record_runtime_event(event: str, **fields: object) -> Dict[str, object]:
        return _runtime_event_recorder.record(event, **fields)

    def _set_last_active_operation(operation: str, **fields: object) -> None:
        nonlocal _last_active_operation
        _last_active_operation = _record_runtime_event(
            "last_active_operation",
            operation=str(operation or "operation"),
            **fields,
        )

    def _add_persisted_crash_breadcrumbs(context: Dict[str, object]) -> None:
        _add_persisted_crash_breadcrumbs_service(
            context,
            reports_dir=crash_reports_dir,
            runtime_event_log_path=_runtime_event_log_path,
            native_diagnostic_log_path=_native_diagnostic_log_path,
        )

    def _write_ui_breadcrumb(payload: Mapping[str, object]) -> None:
        _write_ui_breadcrumb_file(
            crash_reports_dir,
            payload,
            session_id=_session_id,
            pid=os.getpid(),
        )

    def _collect_crash_context() -> Dict[str, object]:
        nonlocal _cached_crash_context
        window = _active_main_window
        context: Dict[str, object] = {}
        app = QApplication.instance()
        if app is not None and app.thread() != QThread.currentThread():
            context.update(_cached_crash_context)
            _add_persisted_crash_breadcrumbs(context)
            return context
        if window is None:
            return context
        process_memory = _windows_process_memory_snapshot(os.getpid())
        if process_memory:
            context["process_memory"] = process_memory
        try:
            current_tab_index = window.main_tabs.currentIndex()
            if current_tab_index >= 0:
                context["current_tab"] = window.main_tabs.tabText(current_tab_index)
        except Exception:
            pass
        try:
            entry = window._current_archive_entry()
            if entry is not None:
                context["selected_archive_path"] = entry.path
                context["selected_archive_package"] = str(entry.pamt_path)
        except Exception:
            pass
        try:
            context["texconv_path"] = window.texconv_path_edit.text().strip()
        except Exception:
            pass
        try:
            context["archive_package_root"] = window.archive_package_root_edit.text().strip()
        except Exception:
            pass
        try:
            context["last_active_operation"] = dict(_last_active_operation)
        except Exception:
            pass
        try:
            context["runtime_event_tail"] = _runtime_event_recorder.tail(limit=120)
        except Exception:
            pass
        try:
            context["native_diagnostic_log_path"] = str(_native_diagnostic_log_path)
            context["native_diagnostic_event_tail"] = _read_jsonl_tail(_native_diagnostic_log_path, limit=120)
        except Exception:
            pass
        try:
            context["archive_renderer_backend"] = window._archive_model_renderer_backend()
            context["archive_preview_request_id"] = int(getattr(window, "archive_preview_request_id", 0) or 0)
            context["archive_isolated_package_request_id"] = int(
                getattr(window, "archive_isolated_package_request_id", 0) or 0
            )
            context["pending_archive_preview_request"] = str(getattr(window, "pending_archive_preview_request", None))
            context["scheduled_archive_preview_request"] = str(getattr(window, "scheduled_archive_preview_request", None))
            context["active_d3d11_package"] = str(getattr(window, "archive_isolated_renderer_active_package", "") or "")
            status_file = getattr(window, "archive_isolated_renderer_status_file", None)
            context["d3d11_status_file"] = str(status_file or "")
            if status_file is not None and Path(status_file).is_file():
                try:
                    status_payload = json.loads(Path(status_file).read_text(encoding="utf-8"))
                except Exception as exc:
                    status_payload = {"read_error": str(exc)}
                context["d3d11_status_payload"] = status_payload
            process = getattr(window, "archive_isolated_renderer_process", None)
            if process is not None:
                try:
                    context["d3d11_process_pid"] = int(process.processId())
                except RuntimeError:
                    context["d3d11_process_pid"] = "deleted"
                d3d11_process_memory = _windows_process_memory_snapshot(context.get("d3d11_process_pid", 0))
                if d3d11_process_memory:
                    context["d3d11_process_memory"] = d3d11_process_memory
                try:
                    context["d3d11_process_state"] = str(process.state())
                except RuntimeError:
                    context["d3d11_process_state"] = "deleted"
            package_worker = getattr(window, "archive_isolated_package_worker", None)
            package_thread = getattr(window, "archive_isolated_package_thread", None)
            context["archive_isolated_package_worker_active"] = package_worker is not None
            if package_thread is not None:
                try:
                    context["archive_isolated_package_thread_running"] = bool(package_thread.isRunning())
                except RuntimeError:
                    context["archive_isolated_package_thread_running"] = "deleted"
            preview_worker = getattr(window, "archive_preview_worker", None)
            preview_thread = getattr(window, "archive_preview_thread", None)
            context["archive_preview_worker_active"] = preview_worker is not None
            if preview_thread is not None:
                try:
                    context["archive_preview_thread_running"] = bool(preview_thread.isRunning())
                except RuntimeError:
                    context["archive_preview_thread_running"] = "deleted"
        except Exception:
            pass
        _add_persisted_crash_breadcrumbs(context)
        try:
            log_lines = window.log_view.toPlainText().splitlines()
            context["recent_log_tail"] = log_lines[-80:]
        except Exception:
            pass
        try:
            archive_log_lines = window.archive_log_view.toPlainText().splitlines()
            context["recent_archive_log_tail"] = archive_log_lines[-80:]
        except Exception:
            pass
        _cached_crash_context = dict(context)
        return context

    def _clear_active_main_window(window: object) -> None:
        nonlocal _active_main_window
        if _active_main_window is window:
            _active_main_window = None

    def _write_crash_report(
        kind: str,
        title: str,
        body: str,
        *,
        context: Optional[Dict[str, object]] = None,
        force: bool = False,
    ) -> None:
        if not _should_write_crash_report(
            kind,
            capture_enabled=_capture_crash_details_enabled,
            force=force,
        ):
            return
        report_context = context if context is not None else _collect_crash_context()
        _write_crash_report_file(
            crash_reports_dir,
            kind,
            title,
            body,
            app_title=APP_TITLE,
            app_version=APP_VERSION,
            session_id=_session_id,
            context=report_context,
            pid=os.getpid(),
            python_version=sys.version,
            platform_label=platform.platform(),
        )

    def _write_heartbeat(phase: str = "", *, clean_shutdown: bool = False) -> None:
        nonlocal _heartbeat_phase, _last_heartbeat_written_at
        try:
            if phase:
                _heartbeat_phase = str(phase)
            payload = _write_app_heartbeat(
                heartbeat_path,
                app_title=APP_TITLE,
                app_version=APP_VERSION,
                session_id=_session_id,
                phase=_heartbeat_phase,
                clean_shutdown=clean_shutdown,
            )
            with _heartbeat_lock:
                _last_heartbeat_written_at = float(payload["last_beat_epoch"])
        except Exception:
            pass

    def _check_previous_unclean_exit() -> bool:
        return _check_previous_unclean_exit_service(
            heartbeat_path,
            session_id=_session_id,
            reports_dir=crash_reports_dir,
            process_is_alive_fn=_process_is_alive,
            add_breadcrumbs_fn=_add_persisted_crash_breadcrumbs,
            write_crash_report_fn=_write_crash_report,
            record_runtime_event_fn=_record_runtime_event,
        )

    def _start_heartbeat_timer(app: QApplication) -> QTimer:
        return _start_heartbeat_timer_controller(app, _write_heartbeat)  # type: ignore[return-value]

    def _start_hang_watchdog() -> threading.Thread:
        def _last_heartbeat_written_epoch() -> float:
            with _heartbeat_lock:
                return _last_heartbeat_written_at

        return _start_hang_watchdog_service(
            _heartbeat_stop_event,
            _last_heartbeat_written_epoch,
            _write_crash_report,
            format_thread_dump_fn=_format_thread_dump,
        )

    def _enable_native_fault_log() -> None:
        nonlocal _fault_log_handle
        _fault_log_handle = _enable_native_fault_log_file(crash_reports_dir)

    def _cleanup_native_fault_log_on_exit(*, clean_exit: bool) -> None:
        nonlocal _fault_log_handle
        if _fault_log_handle is not None:
            _cleanup_native_fault_log_file(
                _fault_log_handle,
                crash_reports_dir,
                clean_exit=clean_exit,
            )
            _fault_log_handle = None

    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        kind, title, formatted = _uncaught_exception_report(exc_type, exc_value, exc_traceback)
        _write_crash_report(kind, title, formatted, force=True)
        _default_sys_excepthook(exc_type, exc_value, exc_traceback)

    def _handle_thread_exception(args) -> None:
        kind, title, formatted = _thread_exception_report(args)
        _write_crash_report(kind, title, formatted, force=True)
        if _default_threading_excepthook is not None:
            _default_threading_excepthook(args)

    def _handle_unraisable_exception(args) -> None:
        kind, title, formatted = _unraisable_exception_report(args)
        _write_crash_report(kind, title, formatted, force=True)
        if _default_unraisablehook is not None:
            _default_unraisablehook(args)

    sys.excepthook = _handle_uncaught_exception
    if _default_threading_excepthook is not None:
        threading.excepthook = _handle_thread_exception
    if _default_unraisablehook is not None:
        sys.unraisablehook = _handle_unraisable_exception
    _enable_native_fault_log()
    _previous_session_unclean = _check_previous_unclean_exit()
    _record_runtime_event(
        "session_start",
        crash_reports_dir=str(crash_reports_dir),
        previous_session_unclean=bool(_previous_session_unclean),
    )
    _write_heartbeat("starting")
    _start_hang_watchdog()

    class MainWindow(AboutControllerMixin, AboutDocumentationMixin, SupportDialogMixin, ShellMenusMixin, ShellRootLayoutMixin, ShellSignalWiringMixin, ShellStartupRestoreMixin, ShellToolTabsMixin, ShellWorkspaceLayoutMixin, ShellWindowBootstrapStateMixin, ShellWindowRuntimeStateMixin, SettingsPersistenceMixin, SettingsAutosaveMixin, CloseControllerMixin, ActivationControllerMixin, ResponsivenessControllerMixin, ArchiveWorkerLifecycleMixin, ArchivePreviewWorkerMixin, ArchivePreviewDetailsMixin, ArchivePreviewLayoutMixin, ArchivePreviewLoadingMixin, ArchivePreviewMemoryAuditMixin, ArchivePreviewNativeCoreLifecycleMixin, ArchivePreviewNativePrefetchMixin, ArchivePreviewRendererControlsMixin, ArchivePreviewResultMixin, ArchivePreviewSettingsMixin, ArchivePreviewD3D11PartsMixin, ArchivePreviewD3D11ProcessMixin, ArchivePreviewD3D11RuntimeMixin, ArchivePreviewD3D11WorkerMixin, ArchivePreviewStateMixin, ArchivePreviewTimingMixin, ArchivePreviewZoomMixin, ArchiveProgressMixin, ArchiveScanLifecycleMixin, ArchiveIndexWorkerMixin, ArchiveSidecarIndexMixin, ArchiveRenderLifecycleMixin, ArchiveFilterWorkerMixin, ArchiveFilterStateMixin, ArchiveFilterControlsMixin, ArchiveFilesPanelMixin, ArchiveUiFormattingMixin, ArchiveVirtualPathLookupMixin, ArchiveAssetCatalogMixin, ArchiveAssetCatalogScopeMixin, ArchiveAssetCatalogDialogMixin, ArchiveCharacterDependencyExportMixin, ArchiveControlsPanelMixin, ArchiveExtractionMixin, ArchiveIconPipelineMixin, ArchiveMaterialFinderMixin, ArchiveMaterialSidecarActionsMixin, ArchiveMaterialSidecarEditorMixin, ArchiveModReadyExportMixin, ArchiveModPackageRetrofitDialogMixin, ArchiveBrowserHeaderMixin, ArchiveBrowserRowPayloadMixin, ArchiveBrowserTreeControllerMixin, ArchiveBrowserActionMixin, ArchiveBrowserActionControlsMixin, ArchiveAppearanceCommonMixin, ArchiveAppearanceCompositeMixin, ArchiveAppearanceSwapMixin, ArchiveBinarySidecarActionsMixin, ArchiveHkxDocumentActionsMixin, ArchiveHkxEditorDialogMixin, ArchiveStaticReplacementDialogMixin, ArchiveMeshModifyOriginalMixin, ArchiveMeshSetupHelperMixin, ArchiveMeshBuilderLifecycleMixin, ArchiveMeshDdsPreviewMixin, ArchiveMeshDirectPatchMixin, ArchiveMeshSwapSupportMixin, ArchiveMeshSwapScopeDialogMixin, ArchiveMeshLaunchFlowMixin, ArchivePatchActionsMixin, ArchiveMeshPatchFlowMixin, ArchiveMeshImportExportMixin, ArchiveImportActionsMixin, ArchiveAttachmentBatchMixin, ArchiveAttachmentDonorPickerDialogMixin, ArchiveAttachmentIconMixin, ArchiveAttachmentLooseFileMixin, ArchiveAttachmentPackageMixin, ArchiveAttachmentPlanMixin, ArchiveAttachmentPlacementDiffDialogMixin, ArchiveAttachmentSafePlacementDialogMixin, ArchiveAttachmentSocketEditorMixin, ArchiveAttachmentVisualDialogMixin, ArchiveAttachmentVisualPayloadMixin, ArchiveWeaponPlacementStudioMixin, ArchiveAssetFamilyReferenceMixin, ArchiveAssetFamilyDialogMixin, ArchiveAssetFamilyPanelMixin, ArchiveAssetFamilyLayoutMixin, ArchiveReferenceExportMixin, ArchiveReferencePreviewMixin, ArchiveSourcePickerDialogMixin, ArchiveSourceMixActionsMixin, ArchiveSourceMixOverlayMixin, ArchivePreviewCacheMixin, ArchivePreviewTextToolsMixin, TextureWorkflowComparePanelMixin, TextureWorkflowConfigCollectionMixin, TextureWorkflowComparePreviewMixin, TextureWorkflowDdsOutputPanelMixin, TextureWorkflowEditorBridgeMixin, TextureWorkflowEditorHandoffMixin, TextureWorkflowPathsPanelMixin, TextureWorkflowProgressPanelMixin, TextureWorkflowSettingsPanelMixin, TextureWorkflowShellControlsMixin, TextureWorkflowSetupPanelMixin, TextureWorkflowSetupOverviewPanelMixin, TextureWorkflowUpscaleBackendPanelMixin, TextureWorkflowProfilesPanelMixin, TextureWorkflowProfilesUiMixin, TextureWorkflowWorkerMixin, LogControllerMixin, ThemeControllerMixin, LanguageControllerMixin, StartupPromptMixin, PathControllerMixin, UtilityControllerMixin, WorkspaceControllerMixin, ProfileControllerMixin, NavigationControllerMixin, DashboardControllerMixin, ModelLibraryShellBridgeMixin, MeshEditorShellBridgeMixin, QMainWindow):
        def __init__(self, startup_splash: Optional[object] = None, app_context: Optional[AppContext] = None) -> None:
            super().__init__()

            pump_startup_splash = make_startup_splash_pump(startup_splash)
            pump_startup_splash("Preparing application...")
            nonlocal _active_main_window
            _active_main_window = self
            self._initialize_window_bootstrap_state(
                app_context=app_context,
                settings_file_path=settings_file_path,
                crash_reports_dir=crash_reports_dir,
                session_id=_session_id,
                previous_session_unclean=bool(_previous_session_unclean),
                set_crash_capture_enabled=_set_crash_capture_enabled,
                record_runtime_event=_record_runtime_event,
                set_last_active_operation=_set_last_active_operation,
                collect_crash_context=_collect_crash_context,
                clear_active_main_window=_clear_active_main_window,
                write_crash_report=_write_crash_report,
                write_heartbeat=_write_heartbeat,
            )
            self._initialize_window_runtime_state()
            self._initialize_archive_runtime_state()
            pump_startup_splash("Preparing workspace...")

            app_icon, _icon_path = load_app_icon(self.current_theme_key)
            if not app_icon.isNull():
                self.setWindowIcon(app_icon)
            self._configure_system_tray_icon(app_icon)

            self._build_shell_menus()
            central = self._build_shell_root_tabs()

            self._build_texture_workflow_shell_tab(pump_startup_splash)
            self._build_archive_browser_shell_tab(pump_startup_splash)
            self._build_shell_tool_tabs(pump_startup_splash)
            self._register_shell_tool_tabs()
            self.setCentralWidget(central)
            self.theme_change_overlay = ThemeChangeBusyOverlay(central)
            self.theme_change_overlay.setGeometry(central.rect())
            self._restore_shell_startup_state(
                pump_startup_splash,
                previous_session_unclean=bool(_previous_session_unclean),
            )

    set_loaded_main_window_class(MainWindow)
    globals()["MainWindow"] = MainWindow
    if os.environ.get(MAIN_WINDOW_CLASS_ONLY_ENV) == "1":
        return MainWindow  # type: ignore[return-value]

    app: Optional[QApplication] = None
    normal_exit = False
    exit_code = 1
    try:
        apply_windows_app_user_model_id()
        app = QApplication(sys.argv)
        nonlocal_heartbeat_timer = _start_heartbeat_timer(app)
        globals()["_cdmw_heartbeat_timer_ref"] = nonlocal_heartbeat_timer
        _write_heartbeat("settings")
        application_startup = prepare_shell_application(app)
        startup_theme = application_startup.theme_key
        globals()["_cdmw_app_window_icon_filter_ref"] = application_startup.app_window_icon_filter
        globals()["_cdmw_tree_column_width_filter_ref"] = application_startup.tree_column_width_filter

        _write_heartbeat("startup_splash")
        startup_splash = create_startup_splash(app, startup_theme)

        _write_heartbeat("main_window")
        window = MainWindow(startup_splash=startup_splash)
        prepare_shell_main_window(
            window,
            app,
            startup_splash,
            application_startup.app_window_icon_filter,
            _record_runtime_event,
        )
        if finish_gui_startup_smoke_if_requested(window, app):
            normal_exit = True
            exit_code = 0
            return 0
        queue_startup_archive_autoload(window, startup_splash, _write_heartbeat)
        exit_code = run_shell_event_loop(app, _write_crash_report)
        normal_exit = True
        return exit_code
    except Exception:
        formatted = traceback.format_exc()
        _write_crash_report(
            "startup_failure" if app is None else "gui_runtime_failure",
            "GUI failed before clean shutdown",
            formatted,
            force=True,
        )
        raise
    finally:
        _heartbeat_stop_event.set()
        if normal_exit:
            _write_heartbeat("closed", clean_shutdown=True)
        _cleanup_native_fault_log_on_exit(clean_exit=bool(normal_exit))

__all__ = ["MainWindow", "mesh_import_mode_availability", "run_gui"]
