from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QObject, Signal
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from cdmw.domain.archives.catalogue import (
    ArchiveChildNode,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRef,
    ArchiveEntryRole,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import ArchiveExportSelectionKind, PrepareEntryResult, ProgressUpdate
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel, RemoteChildrenFetch
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge, compare_archive_shadow_page


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _drain_events() -> None:
    app = _app()
    for _ in range(5):
        app.processEvents()


class _ShadowService(QObject):
    result_ready = Signal(str, str, object)
    batch_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    progress = Signal(str, object)

    compatibility_entry = staticmethod(ArchiveCatalogueService.compatibility_entry)


class _ShadowWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.archive_catalogue_service = _ShadowService(self)
        self.archive_package_root_edit = QLineEdit("C:/Game", parent=None)
        self.archive_entries = [_legacy(0)]
        self.archive_filtered_entries = list(self.archive_entries)
        self.archive_remote_actions_safe = True
        self.archive_filters_dirty = False
        self.archive_scan_finalize_pending = False
        self.archive_startup_saved_filter_apply_pending = False
        self.worker_thread = None
        self._shutting_down = False
        self.logs: list[str] = []
        self.cache_health: list[tuple[str, str, str]] = []

    def append_archive_log(self, message: str, **_kwargs: object) -> None:
        self.logs.append(message)

    def _set_archive_cache_health(self, state: str, reason: str, *, package_root: str = "") -> None:
        self.cache_health.append((state, reason, package_root))


class _RemoteExportWindow(_ShadowWindow):
    def __init__(self) -> None:
        super().__init__()
        self.archive_tree = ArchiveBrowserTreeView()


def _legacy(entry_id: int, path: str | None = None) -> ArchiveEntry:
    return ArchiveEntry(
        path=path or f"character/file_{entry_id}.pac",
        pamt_path=Path("C:/Game/0009/0.pamt"),
        paz_file=Path("C:/Game/0009/0.paz"),
        offset=entry_id * 10,
        comp_size=10,
        orig_size=20,
        flags=0,
        paz_index=0,
    )


def _remote(entry_id: int, path: str | None = None, *, extension: str = ".pac") -> ArchiveEntryDto:
    resolved = path or f"character/file_{entry_id}.pac"
    return ArchiveEntryDto(
        "session-a",
        entry_id,
        ArchiveDurableIdentity(resolved.upper(), "c:\\game\\0009\\0.pamt", 0, entry_id * 10),
        resolved,
        "C:/Game/0009/0.pamt",
        "C:/Game/0009/0.paz",
        0,
        entry_id * 10,
        10,
        20,
        0,
        extension,
        "0009/0.pamt",
        ArchiveEntryRole.MODEL,
        "model_mesh_physics",
        True,
    )


def test_shadow_comparison_matches_counts_order_and_normalized_identities() -> None:
    _app()
    legacy = [_legacy(index) for index in range(3)]
    model = RemoteArchiveBrowserModel(page_size=4)
    handle = ArchiveQueryHandle("session-a", "query-a", 1, 3)
    model.publish_query(handle, view_mode=ArchiveViewMode.FLAT, prime=False)
    assert model.accept_page(
        ArchivePage("session-a", "query-a", 1, 3, 0, tuple(_remote(index) for index in range(3)))
    )

    comparison = compare_archive_shadow_page(
        legacy,
        legacy,
        model,
        ArchiveSessionHandle("session-a", "C:/Game", "fingerprint", 3, 2, True),
        handle,
    )

    assert comparison.matches
    assert comparison.compared_rows == 3
    assert comparison.identity_mismatches == ()


def test_shadow_comparison_reports_bounded_identity_and_count_differences() -> None:
    _app()
    legacy = [_legacy(index) for index in range(20)]
    model = RemoteArchiveBrowserModel(page_size=32)
    handle = ArchiveQueryHandle("session-a", "query-a", 1, 20)
    model.publish_query(handle, view_mode=ArchiveViewMode.FLAT, prime=False)
    remote = tuple(_remote(index, path=f"wrong/file_{index}.pac") for index in range(20))
    assert model.accept_page(ArchivePage("session-a", "query-a", 1, 20, 0, remote))

    comparison = compare_archive_shadow_page(
        legacy,
        legacy,
        model,
        ArchiveSessionHandle("session-a", "C:/Game", "fingerprint", 21, 2, True),
        handle,
        row_limit=20,
    )

    assert not comparison.matches
    assert comparison.v2_entry_count == 21
    assert len(comparison.identity_mismatches) == 16


def test_shadow_scheduler_waits_for_legacy_work_and_latest_state() -> None:
    _app()
    window = _ShadowWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=False, shadow=True)
    opened: list[str] = []
    bridge.start_shadow = lambda root: opened.append(str(root))  # type: ignore[method-assign]

    window.worker_thread = object()
    bridge.schedule_shadow_comparison("filter_complete")
    _drain_events()
    assert opened == []

    window.worker_thread = None
    bridge._run_scheduled_shadow_comparison(bridge._shadow_schedule_generation, 1)
    assert opened == ["C:/Game"]


def test_shadow_safety_diagnostics_do_not_disable_legacy_actions() -> None:
    _app()
    window = _ShadowWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=False, shadow=True)

    bridge._handle_actions_safe(False)

    assert window.archive_remote_actions_safe


def test_v2_bridge_only_offers_session_recovery_for_catalogue_failures() -> None:
    _app()
    window = _RemoteExportWindow()
    window.archive_remote_query_pending = True
    window._update_archive_filter_button_state = lambda: None
    window._set_archive_warmup_overlay = lambda _visible: None
    window.set_busy = lambda _busy, **_kwargs: None
    window.set_status_message = lambda _message: None
    window._record_runtime_event = lambda _event, **_fields: None
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    failures: list[tuple[str, str]] = []
    bridge.backendFailed.connect(lambda kind, detail: failures.append((kind, detail)))

    bridge._handle_failure("selection_lookup", RuntimeError("selection lookup failed"))
    bridge._handle_failure("open", RuntimeError("worker unavailable"))

    assert failures == [("open", "worker unavailable")]
    assert len(window.cache_health) == 1
    assert window.cache_health[0][0] == "unhealthy"


def test_v2_bridge_maps_real_progress_contract_fields() -> None:
    _app()
    window = _RemoteExportWindow()
    updates: list[tuple[int, int, str]] = []
    window._handle_archive_scan_progress = lambda current, total, detail: updates.append((current, total, detail))
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)

    bridge._handle_progress(
        "open",
        ProgressUpdate(completed=17, total=40, phase="fingerprint_scan", current_item="0009/0.pamt"),
    )

    assert updates == [(17, 40, "Fingerprint scan: 0009/0.pamt")]


def test_v2_bridge_resets_each_operation_and_scales_query_progress_separately() -> None:
    _app()
    window = _RemoteExportWindow()
    resets: list[bool] = []
    displayed: list[tuple[str, dict[str, object]]] = []
    updates: list[tuple[int, int, str]] = []
    window._reset_archive_load_progress = lambda: resets.append(True)
    window._update_archive_filter_button_state = lambda: None
    window._set_archive_load_progress = lambda text, **kwargs: displayed.append((text, kwargs))
    window._set_archive_warmup_overlay = lambda *_args, **_kwargs: None
    window.set_status_message = lambda _message: None
    window._handle_archive_scan_progress = lambda current, total, detail: updates.append((current, total, detail))
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)

    bridge._begin_pending("Applying archive filters...", operation="query")
    bridge._handle_progress("query", ProgressUpdate(25, 100, "query_scan"))

    assert resets == [True]
    assert displayed == [
        (
            "Applying archive filters...",
            {"phase": "Filtering", "percent": 1, "allow_decrease": True},
        )
    ]
    assert updates == [(25, 100, "Filter query scan")]


def test_v2_bridge_scopes_busy_state_and_cancel_keeps_existing_view() -> None:
    _app()
    window = _RemoteExportWindow()
    window.archive_scan_button = QPushButton("Scan")
    window.archive_refresh_scan_button = QPushButton("Refresh")
    window._update_archive_filter_button_state = lambda: None
    window._set_archive_warmup_overlay = lambda *_args, **_kwargs: None
    progress: list[tuple[str, str, int]] = []
    window._set_archive_load_progress = lambda text, **kwargs: progress.append(
        (text, str(kwargs.get("phase", "")), int(kwargs.get("percent", 0)))
    )
    window.set_status_message = lambda _message: None
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    window.archive_remote_query_pending = True

    bridge._set_remote_operation_busy(True)

    assert window.archive_tree.isEnabled()
    assert not window.archive_scan_button.isEnabled()
    assert window.archive_refresh_scan_button.text() == "Cancel"
    assert bridge.cancel_pending_update()
    assert window.archive_refresh_scan_button.text() == "Refresh"
    assert progress[-1] == ("Archive catalogue loading cancelled.", "Ready", 100)
    assert window.cache_health[-1][0] == "unknown"


def test_remote_export_selection_uses_session_ids_without_materializing_global_entries() -> None:
    _app()
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    handle = ArchiveQueryHandle("session-a", "query-a", 5, 2)
    bridge.model.publish_query(handle, view_mode=ArchiveViewMode.FLAT, prime=False)
    rows = (
        _remote(7, "texture/albedo.dds", extension=".dds"),
        _remote(8, "texture/normal.dds", extension=".dds"),
    )
    assert bridge.model.accept_page(ArchivePage("session-a", "query-a", 5, 2, 0, rows))
    selection_model = window.archive_tree.selectionModel()
    assert selection_model is not None
    selection_model.select(
        bridge.model.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    selection_model.select(
        bridge.model.index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    selection = bridge.selected_export_selection()

    assert selection is not None
    assert selection.selection_kind is ArchiveExportSelectionKind.ENTRY_IDS
    assert selection.entry_ids == (7, 8)
    assert selection.requested_count == 2
    assert selection.all_dds
    assert selection.dds_count == 2
    assert selection.workflow_paths == ("0009/texture/albedo.dds", "0009/texture/normal.dds")
    assert not hasattr(window, "archive_entries_by_path")

    window.archive_tree.setCurrentIndex(bridge.model.index(0, 0))
    family_selection = bridge.current_family_export_selection()
    assert family_selection is not None
    assert family_selection.selection_kind is ArchiveExportSelectionKind.FAMILY
    assert family_selection.family_entry_id == 7
    assert not family_selection.include_package_root


def test_remote_current_entry_reuses_worker_prepared_dependency_snapshot() -> None:
    _app()
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    row = _remote(7, "character/model/hero.pac")
    bridge.model.publish_query(
        ArchiveQueryHandle("session-a", "query-a", 1, 1),
        view_mode=ArchiveViewMode.FLAT,
        prime=False,
    )
    assert bridge.model.accept_page(ArchivePage("session-a", "query-a", 1, 1, 0, (row,)))
    window.archive_tree.setCurrentIndex(bridge.model.index(0, 0))
    prepared = PrepareEntryResult(
        ArchiveEntryRef(row.session_id, row.entry_id, row.identity, row.path),
        "C:/cache/hero.pac",
        row.original_size,
        "sha-hero",
        "prepared test source",
    )
    snapshot = ArchivePreviewDependencySet.from_dtos(
        row,
        (),
        total_candidates=0,
        truncated=False,
        prepared={row.entry_id: prepared},
    )
    assert bridge._preview_dependencies is not None
    bridge._preview_dependencies._remember_snapshot(snapshot)

    current = bridge.current_compatibility_entry()

    assert current is snapshot.selected_entry
    assert current.prepared_path == Path("C:/cache/hero.pac")


def test_item_scope_selection_prefers_a_model_for_preview() -> None:
    _app()
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    handle = ArchiveQueryHandle("session-a", "query-item", 9, 3)
    bridge.model.publish_query(handle, view_mode=ArchiveViewMode.FLAT, prime=False)
    rows = (
        _remote(7, "ui/icon/item.dds", extension=".dds"),
        _remote(8, "equipment/item.pac", extension=".pac"),
        _remote(9, "equipment/item.xml", extension=".xml"),
    )
    assert bridge.model.accept_page(ArchivePage("session-a", "query-item", 9, 3, 0, rows))
    bridge._item_scope_selection_generation = 9

    bridge._select_item_scope_preview_or_first(9)

    selected = bridge.model.entry_for_index(window.archive_tree.currentIndex())
    assert selected is not None
    assert selected.entry_id == 8


def test_remote_export_selection_represents_folder_and_filtered_query_server_side() -> None:
    _app()
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    handle = ArchiveQueryHandle("session-a", "query-folder", 6, 43)
    bridge.model.publish_query(handle, view_mode=ArchiveViewMode.FOLDERS, prime=False)
    fetch = RemoteChildrenFetch("session-a", "query-folder", 6, "root", None, None, 0, 512)
    assert bridge.model.accept_children(
        fetch,
        ArchiveChildrenResult(
            "session-a",
            "query-folder",
            (ArchiveChildNode("0009/texture", "texture", True, 43),),
            False,
            offset=0,
            total_children=1,
            next_offset=None,
        ),
    )
    folder_index = bridge.model.index(0, 0, QModelIndex())
    selection_model = window.archive_tree.selectionModel()
    assert selection_model is not None
    selection_model.select(
        folder_index,
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
    )

    folder_selection = bridge.selected_export_selection()

    assert folder_selection is not None
    assert folder_selection.selection_kind is ArchiveExportSelectionKind.FOLDER
    assert folder_selection.query_id == "query-folder"
    assert folder_selection.folder_path == "0009/texture"
    assert folder_selection.requested_count == 43

    bridge.controller._current_query = ArchiveQuery("session-a", extensions=(".dds",))
    filtered_selection = bridge.filtered_export_selection()
    assert filtered_selection is not None
    assert filtered_selection.selection_kind is ArchiveExportSelectionKind.QUERY
    assert filtered_selection.query_id == "query-folder"
    assert filtered_selection.requested_count == 43
    assert filtered_selection.all_dds
    assert filtered_selection.dds_count == 43


def test_remote_export_rejects_an_explicit_selection_larger_than_the_protocol_bound() -> None:
    _app()
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
    bridge.model.publish_query(
        ArchiveQueryHandle("session-a", "query-large", 7, 5_000),
        view_mode=ArchiveViewMode.FLAT,
        prime=False,
    )
    selection_model = window.archive_tree.selectionModel()
    assert selection_model is not None
    selection_model.select(
        QItemSelection(bridge.model.index(0, 0), bridge.model.index(4_096, 0)),
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
    )

    assert bridge.selected_export_selection() is None
    assert bridge.export_selection_error == (
        "Select at most 4,096 individual files, or use Extract Filtered for a larger set."
    )
