from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.library.models import is_importable_model_path
from cdmw.services.model_library_service import ModelLibraryService
from cdmw.ui.model_library.actions import ModelLibraryActionsMixin
from cdmw.ui.model_library.catalogue import ModelLibraryCatalogueMixin
from cdmw.ui.model_library.commands import ModelLibraryCommandsMixin
from cdmw.ui.model_library.controller import ModelLibraryResultsMixin
from cdmw.ui.model_library.local_rows import ModelLibraryLocalRowsMixin
from cdmw.ui.model_library.panels import build_controls_panel, build_preview_panel, build_results_panel
from cdmw.ui.model_library.preview import ModelLibraryInlinePreviewMixin
from cdmw.ui.model_library.selection import ModelLibrarySelectionMixin
from cdmw.ui.model_library.settings import ModelLibrarySettingsMixin
from cdmw.ui.model_library.tasks import ModelLibraryTaskMixin
from cdmw.ui.model_library.texture_status import ModelLibraryTextureStatusMixin
from cdmw.ui.model_library.view_state import ModelLibraryResultsViewMixin
from cdmw.ui.layout_utils import responsive_sidebar_bounds
from cdmw.workers.model_library_workers import (
    ModelLibraryImportPathRequest,
    ModelLibraryImportPathResult,
    resolve_model_library_import_path,
)


class ModelLibraryTab(
    ModelLibraryCatalogueMixin,
    ModelLibraryActionsMixin,
    ModelLibraryCommandsMixin,
    ModelLibrarySettingsMixin,
    ModelLibraryTaskMixin,
    ModelLibraryInlinePreviewMixin,
    ModelLibraryResultsViewMixin,
    ModelLibrarySelectionMixin,
    ModelLibraryTextureStatusMixin,
    ModelLibraryLocalRowsMixin,
    ModelLibraryResultsMixin,
    QWidget,
):
    status_message_requested = Signal(str, bool)
    import_mesh_requested = Signal(str, object)
    preview_mesh_requested = Signal(str, object)
    item_icon_source_generated = Signal(str, object)
    RESULTS_FILTER_DEBOUNCE_MS = 140
    RESULTS_POPULATION_BATCH_SIZE = 200
    PREPARED_ROWS_APPLY_BATCH_SIZE = 1000

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        theme_key: str = "graphite",
        record_runtime_event: Optional[Callable[..., object]] = None,
        model_library_service: Optional[ModelLibraryService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = Path(base_dir)
        self.theme_key = str(theme_key or "graphite")
        self._record_runtime_event = record_runtime_event if callable(record_runtime_event) else None
        self.model_library_service = model_library_service or ModelLibraryService(settings=settings)
        self._model_library_shutting_down = False
        self.local_models: list[dict[str, object]] = []
        self.mirror_results: list[dict[str, object]] = []
        self._result_payloads_by_item: dict[int, dict[str, object]] = {}
        self._texture_status_cache: dict[tuple[str, str], int] = {}
        self._last_hidden_downloaded_count = 0
        self._active_results_view = "mirror"
        self._inline_preview_request_id = 0
        self._inline_preview_loaded_import_path: Optional[Path] = None
        self._inline_preview_loaded_payload: Optional[dict[str, object]] = None
        self._inline_d3d11_process: Optional[QProcess] = None
        self._inline_d3d11_active_package: Optional[Path] = None
        self._inline_d3d11_retired_packages: list[Path] = []
        self._inline_d3d11_status_file: Optional[Path] = None
        self._inline_d3d11_status_mtime = 0.0
        self._inline_preview_loaded_texture_count = 0
        self._inline_preview_loaded_renderer_backend = ""
        self._inline_preview_task_running = False
        self._pending_inline_preview_request: Optional[tuple[Path, dict[str, object], bool]] = None
        self._pending_model_action_after_task: Optional[Callable[[], None]] = None
        self._model_action_request_id = 0
        self._pending_icon_generation_request_id = 0
        self._icon_output_request_id = 0
        self._icon_output_active = False
        self._task_status_active = False
        self._result_sort_column = int(self.settings.value("model_library/result_sort_column", 1) or 1)
        self._result_sort_order = (
            Qt.SortOrder.DescendingOrder
            if str(self.settings.value("model_library/result_sort_order", "asc") or "asc") == "desc"
            else Qt.SortOrder.AscendingOrder
        )
        self._task_thread: Optional[object] = None
        self._task_worker: Optional[object] = None
        self._task_ui_bridge: Optional[object] = None
        self._task_complete_handler: Optional[Callable[[object], None]] = None
        self._task_error_handler: Optional[Callable[[str], None]] = None
        self._stop_event: Optional[object] = None
        self._results_request_id = 0
        self._delete_request_id = 0
        self._results_task_stop_event: Optional[threading.Event] = None
        self._results_task_kind = ""
        self._pending_results_refresh = False
        self._pending_results_request: Optional[object] = None
        self._pending_prepared_rows_result: Optional[object] = None
        self._pending_prepared_payloads: list[dict[str, object]] = []
        self._pending_prepared_cursor = 0
        self._results_selection_keys: dict[int, tuple[str, str, str]] = {}
        self._prepared_rows_by_payload_id: dict[int, object] = {}
        self._local_frozen_rows: tuple[object, ...] = ()
        self._mirror_frozen_rows: tuple[object, ...] = ()
        self._auto_preview_timer = QTimer(self)
        self._auto_preview_timer.setSingleShot(True)
        self._auto_preview_timer.setInterval(350)
        self._auto_preview_timer.timeout.connect(self._preview_current_model_if_auto_enabled)
        self._results_filter_timer = QTimer(self)
        self._results_filter_timer.setSingleShot(True)
        self._results_filter_timer.setInterval(self.RESULTS_FILTER_DEBOUNCE_MS)
        self._results_filter_timer.timeout.connect(self._flush_debounced_results_filter)
        self._results_population_timer = QTimer(self)
        self._results_population_timer.setSingleShot(True)
        self._results_population_timer.setInterval(0)
        self._results_population_timer.timeout.connect(self._flush_results_population_batch)
        self._pending_results_rows: list[dict[str, object]] = []
        self._pending_results_total_count = 0
        self._pending_results_visible_count = 0
        self._pending_results_selected_payload: Optional[dict[str, object]] = None
        self._pending_results_selected_key = ("", "", "")
        self._populating_results = False
        self._result_items_by_payload_id: dict[int, QTreeWidgetItem] = {}
        self._checked_payloads_by_item: dict[int, dict[str, object]] = {}
        self._no_texture_download_item_ids: set[int] = set()
        self._inline_d3d11_status_timer = QTimer(self)
        self._inline_d3d11_status_timer.setInterval(200)
        self._inline_d3d11_status_timer.timeout.connect(self._poll_inline_d3d11_status)
        self._updating_column_filters = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root_layout.addWidget(splitter, stretch=1)

        controls_panel = build_controls_panel(self)
        results_panel = build_results_panel(self)
        preview_panel = build_preview_panel(self)
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(8)
        splitter.addWidget(controls_panel)
        splitter.addWidget(content_splitter)
        content_splitter.addWidget(results_panel)
        content_splitter.addWidget(preview_panel)

        controls_min, controls_pref, controls_max = responsive_sidebar_bounds(self, role="wide")
        controls_panel.setMinimumWidth(max(controls_min, 430))
        controls_panel.setMaximumWidth(max(controls_max, 520))
        results_panel.setMinimumWidth(300)
        preview_panel.setMinimumWidth(280)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([max(controls_pref, 460), 900])
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setSizes([460, 440])

        self._load_settings()
        self._refresh_roots_tree()
        self._update_catalogue_status()
        initial_results_loaded = self._load_initial_results_view()
        self._update_selection_state()
        if not initial_results_loaded:
            self._set_status("Choose Mirror Catalogue or Local Library. Use Refresh to reload the active view.")

    def _model_import_path_request(
        self,
        payload: dict[str, object],
        *,
        selected_member: str = "",
    ) -> ModelLibraryImportPathRequest:
        filenames: tuple[str, ...] = ()
        if payload.get("kind") == "mirror":
            filenames = tuple(
                str(getattr(candidate, "filename", "") or "")
                for candidate in self._mirror_candidates_for_payload(payload)
                if str(getattr(candidate, "filename", "") or "")
            )
        return ModelLibraryImportPathRequest(
            kind=str(payload.get("kind", "") or ""),
            import_path=str(payload.get("import_path", "") or ""),
            archive_path=str(payload.get("archive_path", "") or ""),
            source_path=str(payload.get("path", "") or ""),
            asset_dir=str(payload.get("asset_dir", "") or ""),
            uid=str(payload.get("uid", "") or ""),
            download_root=str(self._download_output_root()),
            candidate_filenames=filenames,
            selected_member=str(selected_member or payload.get("archive_member", "") or ""),
        )

    def _apply_model_import_path_result(
        self,
        payload: dict[str, object],
        result: ModelLibraryImportPathResult,
    ) -> None:
        self._invalidate_prepared_row_source(payload)
        if result.asset_dir is not None:
            payload["asset_dir"] = str(result.asset_dir)
        if result.archive_path is not None:
            payload["archive_path"] = str(result.archive_path)
        if result.selected_member:
            payload["archive_member"] = result.selected_member
        if result.import_path is None:
            return
        payload["import_path"] = str(result.import_path)
        payload["import_supported"] = True
        if payload.get("kind") == "mirror":
            payload["local_status"] = "Ready"
        self._refresh_result_row_status(payload)

    def _request_payload_import_path(
        self,
        payload: dict[str, object],
        *,
        status: str,
        on_resolved: Callable[[Path], None],
        on_missing: Callable[[], None],
        selected_member: str = "",
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_status("A model library task is already running.", error=True)
            return
        self._model_action_request_id += 1
        request = self._model_import_path_request(dict(payload), selected_member=selected_member)
        for path_text in (request.import_path, request.source_path, request.archive_path):
            direct_path = Path(path_text).expanduser() if path_text else None
            if direct_path is not None and is_importable_model_path(direct_path):
                on_resolved(direct_path)
                return
        request_id = self._model_action_request_id
        selection_key = self._payload_population_key(payload)
        stop_event = threading.Event()
        self._stop_event = stop_event

        def task(_progress: Callable[[str], None]) -> object:
            return resolve_model_library_import_path(request, stop_event=stop_event)

        def complete(value: object) -> None:
            if request_id != self._model_action_request_id or not isinstance(value, ModelLibraryImportPathResult):
                return
            if self._payload_population_key(self._selected_payload()) != selection_key:
                return
            self._apply_model_import_path_result(payload, value)
            if value.candidate_members:
                self._pending_model_action_after_task = lambda: self._choose_model_archive_member(
                    payload,
                    value.candidate_members,
                    status=status,
                    on_resolved=on_resolved,
                    on_missing=on_missing,
                )
                return
            callback = (lambda: on_resolved(value.import_path)) if value.import_path is not None else on_missing
            self._pending_model_action_after_task = callback

        def handle_error(message: str) -> None:
            if request_id == self._model_action_request_id:
                self._set_status(f"Model resolution failed: {message}", error=True)

        self._run_task(status, task, complete, error_handler=handle_error)

    def _choose_model_archive_member(
        self,
        payload: dict[str, object],
        members: tuple[str, ...],
        *,
        status: str,
        on_resolved: Callable[[Path], None],
        on_missing: Callable[[], None],
    ) -> None:
        selected, accepted = QInputDialog.getItem(
            self,
            "Choose Model from ZIP",
            "This ZIP contains multiple importable models. Choose one:",
            list(members),
            0,
            False,
        )
        if not accepted:
            self._set_status("ZIP model selection cancelled.")
            return
        self._request_payload_import_path(
            payload,
            status=status,
            on_resolved=on_resolved,
            on_missing=on_missing,
            selected_member=str(selected),
        )

    def _apply_mirror_local_state(self, payload: dict[str, object]) -> None:
        """Compatibility shim; worker-prepared payloads already own local state."""

        if payload.get("kind") != "mirror":
            return

    def _invalidate_prepared_row_source(self, payload: Optional[dict[str, object]] = None) -> None:
        if payload is None or payload.get("kind") == "mirror":
            self._mirror_frozen_rows = ()
        if payload is None or payload.get("kind") != "mirror":
            self._local_frozen_rows = ()

    def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
        thread = self._task_thread
        if thread is None:
            return ()
        try:
            if not thread.isRunning():
                return ()
        except RuntimeError:
            return ()
        return (("task", thread, self._task_worker),)

    def request_shutdown(self) -> None:
        self._model_library_shutting_down = True
        self._auto_preview_timer.stop()
        self._results_filter_timer.stop()
        self._results_population_timer.stop()
        self._pending_inline_preview_request = None
        self._pending_model_action_after_task = None
        self._model_action_request_id = int(getattr(self, "_model_action_request_id", 0) or 0) + 1
        self._results_request_id = int(getattr(self, "_results_request_id", 0) or 0) + 1
        self._delete_request_id = int(getattr(self, "_delete_request_id", 0) or 0) + 1
        self._icon_output_request_id = int(getattr(self, "_icon_output_request_id", 0) or 0) + 1
        self._icon_output_active = False
        self._pending_results_request = None
        self._pending_results_refresh = False
        results_selection_keys = getattr(self, "_results_selection_keys", None)
        if results_selection_keys is not None:
            results_selection_keys.clear()
        self._pending_results_rows.clear()
        self._pending_prepared_rows_result = None
        pending_prepared_payloads = getattr(self, "_pending_prepared_payloads", None)
        if pending_prepared_payloads is not None:
            pending_prepared_payloads.clear()
        results_stop_event = getattr(self, "_results_task_stop_event", None)
        if results_stop_event is not None:
            results_stop_event.set()
        if self._stop_event is not None and hasattr(self._stop_event, "set"):
            self._stop_event.set()
        thread = self._task_thread
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass
        self._stop_inline_d3d11_process(cleanup_packages=True)

__all__ = ["ModelLibraryTab"]
