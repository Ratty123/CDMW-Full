"""The worker's export destination rule, through the real managed worker.

An owned synthetic game under tmp_path, through Browse Archives' catalogue service. From
the review of 5940404b7 (tests/test_review_archive_export_destination.py on
rr/parity-review); they pass once the worker is rebuilt from this branch.
"""

from __future__ import annotations

import hashlib
import subprocess

from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
from cdmw.domain.archives.catalogue import ArchiveQuery, ArchiveViewMode
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportRequest,
    ArchiveExportSelectionKind,
    FetchPageRequest,
)
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tests.helpers.character_catalog_fixture import write_character_archive
from tests.test_archive_single_backend_workspace import _WORKER, _open, _write_items
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter

_APP = QApplication.instance() or QApplication([])


def _fingerprint(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _export_one(tmp_path, root, destination):
    """Open the owned game through Browse and export its first entry to `destination`."""

    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    archive.archive_backend_client._cache_root = tmp_path / "cache"
    archive.archive_backend_client._explicit_worker = _WORKER
    archive._render_archive_preview = lambda *args, **kwargs: None
    archive._start_archive_preview_core_prewarm = lambda: None
    try:
        session = _open(window, root)
        service = archive.archive_catalogue_service
        awaiter = _Awaiter(service)
        bridge = archive.archive_remote_bridge
        bridge.controller.apply_query(ArchiveQuery(session.session_id, view_mode=ArchiveViewMode.FLAT))
        assert _Awaiter._wait_until(lambda: bridge.model.query_handle is not None
                                    and bridge.model.query_handle.generation == bridge.controller.generation,
                                    timeout_ms=10_000)
        handle = bridge.model.query_handle
        page = awaiter.wait(service.fetch_page(FetchPageRequest(handle.query_id, 0, 1), ui_generation=handle.generation))
        request = ArchiveExportRequest(session.session_id, ArchiveExportSelectionKind.ENTRY_IDS,
                                       str(destination), entry_ids=(page.rows[0].entry_id,))
        return awaiter.wait(service.export(request, ui_generation=handle.generation))
    finally:
        window._finalize_close()
        _Awaiter._wait_until(lambda: archive.archive_backend_client.process_id == 0, timeout_ms=10_000)
        window.deleteLater()
        _APP.processEvents()


def test_an_export_into_a_cdmw_archive_mod_folder_is_allowed(tmp_path, monkeypatch) -> None:
    """CDMW's archive-style DMM mods hold their own meta\0.papgt (the Python guard says
    so and ignores it). GameFolderPolicy.IsGameRoot accepts meta\0.papgt alone, so an
    honest export into, or below, such a mod folder is refused as "inside a game
    installation"."""

    assert _WORKER.is_file(), "Build the managed worker before this test."
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    root = tmp_path / "game"
    write_character_archive(root)
    _write_items(root)
    (root / "CrimsonDesert.exe").write_bytes(b"owned synthetic executable")
    mod = tmp_path / "mods" / "My Archive Mod"
    (mod / "meta").mkdir(parents=True)
    (mod / "meta" / "0.papgt").write_bytes(b"the mod's own group table")
    _export_one(tmp_path, root, mod / "extracted")
    assert any((mod / "extracted").rglob("*")), "nothing was exported into the mod's folder"


def test_an_export_through_a_junction_never_writes_into_the_game(tmp_path, monkeypatch) -> None:
    """RejectProtectedDestination compares unresolved strings (Overlaps), walks up the
    destination's own path for CrimsonDesert.exe or meta\\0.papgt, and checks only the
    destination itself for a reparse point. With C:\\...\\link a junction to <game>\\0036,
    the destination link\\out overlaps nothing by string, no folder on its own path is a
    game root (0036 holds neither mark), and out does not exist yet: the export writes its
    files inside the game."""

    assert _WORKER.is_file(), "Build the managed worker before this test."
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    root = tmp_path / "game"
    write_character_archive(root)
    _write_items(root)
    (root / "CrimsonDesert.exe").write_bytes(b"owned synthetic executable")
    link = tmp_path / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root / "0036")], check=True, capture_output=True)
    before = _fingerprint(root)

    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    archive.archive_backend_client._cache_root = tmp_path / "cache"
    archive.archive_backend_client._explicit_worker = _WORKER
    archive._render_archive_preview = lambda *args, **kwargs: None
    archive._start_archive_preview_core_prewarm = lambda: None
    try:
        session = _open(window, root)
        service = archive.archive_catalogue_service
        awaiter = _Awaiter(service)
        bridge = archive.archive_remote_bridge
        bridge.controller.apply_query(ArchiveQuery(session.session_id, view_mode=ArchiveViewMode.FLAT))
        assert _Awaiter._wait_until(lambda: bridge.model.query_handle is not None
                                    and bridge.model.query_handle.generation == bridge.controller.generation,
                                    timeout_ms=10_000)
        handle = bridge.model.query_handle
        page = awaiter.wait(service.fetch_page(FetchPageRequest(handle.query_id, 0, 1), ui_generation=handle.generation))
        request = ArchiveExportRequest(session.session_id, ArchiveExportSelectionKind.ENTRY_IDS,
                                       str(link / "out"), entry_ids=(page.rows[0].entry_id,))
        try:
            awaiter.wait(service.export(request, ui_generation=handle.generation))
        except Exception:
            pass  # a refusal is the right outcome
    finally:
        window._finalize_close()
        _Awaiter._wait_until(lambda: archive.archive_backend_client.process_id == 0, timeout_ms=10_000)
        window.deleteLater()
        _APP.processEvents()
        try:
            link.rmdir()  # the junction only, never its target
        except OSError:
            pass
    assert _fingerprint(root) == before, "the export wrote into the game folder through a junction"
