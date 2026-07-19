from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
from cdmw.ui.archive_browser.remote_window_bridge import compare_archive_shadow_page


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


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
