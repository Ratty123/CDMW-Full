from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLineEdit

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveViewMode,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel
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

    def append_archive_log(self, message: str, **_kwargs: object) -> None:
        self.logs.append(message)


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


def _remote(entry_id: int, path: str | None = None) -> ArchiveEntryDto:
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
        ".pac",
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
