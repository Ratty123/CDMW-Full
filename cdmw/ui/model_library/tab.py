from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.model_catalogue import (
    is_importable_model_path,
    resolve_importable_model_path,
)
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
from cdmw.ui.widgets import responsive_sidebar_bounds


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

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        theme_key: str = "graphite",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_dir = Path(base_dir)
        self.theme_key = str(theme_key or "graphite")
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
        self._inline_d3d11_status_file: Optional[Path] = None
        self._inline_d3d11_status_mtime = 0.0
        self._inline_preview_loaded_texture_count = 0
        self._inline_preview_loaded_renderer_backend = ""
        self._pending_icon_generation_request_id = 0
        self._task_status_active = False
        self._result_sort_column = int(self.settings.value("model_library/result_sort_column", 1) or 1)
        self._result_sort_order = (
            Qt.SortOrder.DescendingOrder
            if str(self.settings.value("model_library/result_sort_order", "asc") or "asc") == "desc"
            else Qt.SortOrder.AscendingOrder
        )
        self._task_thread: Optional[object] = None
        self._task_worker: Optional[object] = None
        self._task_complete_handler: Optional[Callable[[object], None]] = None
        self._task_error_handler: Optional[Callable[[str], None]] = None
        self._stop_event: Optional[object] = None
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
        self._populating_results = False
        self._result_items_by_payload_id: dict[int, QTreeWidgetItem] = {}
        self._checked_payloads_by_item: dict[int, dict[str, object]] = {}
        self._no_texture_download_item_ids: set[int] = set()
        self._activation_preview_timer = QTimer(self)
        self._activation_preview_timer.setSingleShot(True)
        self._activation_preview_timer.setInterval(90)
        self._activation_preview_timer.timeout.connect(self._schedule_auto_inline_preview)
        self._inline_d3d11_status_timer = QTimer(self)
        self._inline_d3d11_status_timer.setInterval(200)
        self._inline_d3d11_status_timer.timeout.connect(self._poll_inline_d3d11_status)
        self._updating_column_filters = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header = QLabel("Model Library")
        header.setObjectName("SectionTitle")
        root_layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root_layout.addWidget(splitter, stretch=1)

        controls_panel = build_controls_panel(self)
        results_panel = build_results_panel(self)
        preview_panel = build_preview_panel(self)
        splitter.addWidget(controls_panel)
        splitter.addWidget(results_panel)
        splitter.addWidget(preview_panel)

        controls_min, _controls_pref, controls_max = responsive_sidebar_bounds(self, role="wide")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        controls_panel.setMinimumWidth(controls_min)
        controls_panel.setMaximumWidth(max(controls_max, 430))
        preview_panel.setMinimumWidth(preview_min)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([max(controls_min, 380), 760, preview_min])

        self._load_settings()
        self._refresh_roots_tree()
        self._update_catalogue_status()
        initial_results_loaded = self._load_initial_results_view()
        self._update_selection_state()
        if not initial_results_loaded:
            self._set_status("Choose Mirror Catalogue or Local Library. Use Refresh to reload the active view.")

    def _resolve_payload_import_path(self, payload: dict[str, object]) -> Optional[Path]:
        if payload.get("kind") == "mirror":
            self._apply_mirror_local_state(payload)
            import_path = Path(str(payload.get("import_path", "") or ""))
            if import_path.is_file() and is_importable_model_path(import_path):
                return import_path
            archive_path = Path(str(payload.get("archive_path", "") or ""))
            if archive_path.is_file():
                asset_dir = Path(str(payload.get("asset_dir", "") or archive_path.parent))
                extract_root = asset_dir / "gltf" if archive_path.suffix.lower() == ".zip" else None
                resolved = resolve_importable_model_path(archive_path, extract_root=extract_root)
                if resolved is not None:
                    payload["import_path"] = str(resolved)
                    payload["local_status"] = self._mirror_local_status(payload)
                    self._refresh_result_row_status(payload)
                    return resolved
            return None
        import_path = Path(str(payload.get("import_path", "") or ""))
        if import_path.is_file() and is_importable_model_path(import_path):
            return import_path
        path = Path(str(payload.get("path", "") or ""))
        if not path.is_file():
            return None
        resolved = resolve_importable_model_path(path)
        if resolved is not None:
            payload["import_path"] = str(resolved)
            payload["import_supported"] = True
            self._refresh_result_row_status(payload)
        return resolved

    def _apply_mirror_local_state(self, payload: dict[str, object]) -> None:
        if payload.get("kind") != "mirror":
            return
        asset_dir = self._existing_mirror_asset_dir(payload)
        if asset_dir is not None:
            payload["asset_dir"] = str(asset_dir)
        archive_path = self._existing_mirror_archive_path(payload, asset_dir)
        if archive_path is not None:
            payload["archive_path"] = str(archive_path)
        import_path = Path(str(payload.get("import_path", "") or ""))
        if not import_path.is_file():
            if archive_path is not None and archive_path.suffix.lower() == ".glb":
                payload["import_path"] = str(archive_path)
            elif asset_dir is not None:
                discovered = self._find_importable_file_under(asset_dir)
                if discovered is not None:
                    payload["import_path"] = str(discovered)
        payload["local_status"] = self._mirror_local_status(payload)

    def _existing_mirror_asset_dir(self, payload: dict[str, object]) -> Optional[Path]:
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text)
            if asset_dir.is_dir():
                return asset_dir
        uid = str(payload.get("uid", "") or "").strip()
        if not uid:
            return None
        output_root = self._download_output_root()
        if not output_root.is_dir():
            return None
        matches = [path for path in output_root.glob(f"*-{uid}") if path.is_dir()]
        if not matches:
            return None
        matches.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
        return matches[0]

    def _existing_mirror_archive_path(self, payload: dict[str, object], asset_dir: Optional[Path]) -> Optional[Path]:
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        if archive_path.is_file():
            return archive_path
        if asset_dir is None or not asset_dir.is_dir():
            return None
        for candidate in self._mirror_candidates_for_payload(payload):
            path = asset_dir / str(getattr(candidate, "filename", "") or "")
            if path.is_file():
                return path
        archives = sorted(
            [path for path in asset_dir.iterdir() if path.is_file() and path.suffix.lower() in {".zip", ".glb"}],
            key=lambda path: path.name.lower(),
        )
        return archives[0] if archives else None

    def _find_importable_file_under(self, root: Path) -> Optional[Path]:
        priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3}
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file() and is_importable_model_path(path)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda path: (priority.get(path.suffix.lower(), 99), str(path).lower()))
        return candidates[0]

__all__ = ["ModelLibraryTab"]
