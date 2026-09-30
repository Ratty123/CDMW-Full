"""Real headless workspace and worker, using only owned synthetic archives."""
from pathlib import Path
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.app.events import AppEventBus
from cdmw.domain.archives.catalogue import ArchiveQuery, ArchiveViewMode
from cdmw.domain.archives.catalogue_operations import FetchPageRequest, PrepareEntryRequest
from cdmw.domain.archives.item_catalogue import ItemCatalogSearchRequest
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter
from tests.helpers.character_catalog_fixture import write_character_archive

_APP = QApplication.instance() or QApplication([])
_ROOT = Path(__file__).resolve().parents[1]
_WORKER = _ROOT / "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe"


def _write_items(root):
    # Current table layout matches the native indexer's managed fixture.
    item_id, name, key, model_hash = 1234, b"Current_Cloth_Helm", b"12345678", 0xC4FFA63D
    row = (struct.pack("<II", item_id, len(name)) + name + b"\0" + struct.pack("<II", 1, 0)
           + bytes([7, 0x70, 0, 0, 0]) + struct.pack("<II", item_id, len(key)) + key
           + bytes(64) + struct.pack("<I", model_hash))
    text = b"Fixture Helm"
    tables = "gamedata/binarystaticinfo__/bin/"
    payloads = [
        (tables + "iteminfo.staticinfobody", row),
        (tables + "iteminfo.staticinfoheader", struct.pack("<HII", 1, item_id, 0)),
        (tables + "stringinfo.staticinfobody", struct.pack("<I", model_hash) + bytes(5)
         + struct.pack("<I", 23) + b"cd_marni_laser_hel_0001"),
        (tables + "stringinfo.staticinfoheader", struct.pack("<HII", 1, model_hash, 0)),
        ("gamedata/stringtable/binary__/eng/item.paloc", struct.pack("<I", len(key)) + key
         + struct.pack("<I", len(text)) + text),
        ("character/model/cd_marni_laser_hel_0001.pac", b"PAC synthetic item"),
    ]
    package = root / "0036"
    package.mkdir()
    names, data, entries = bytearray(), bytearray(), bytearray()
    for path, payload in payloads:
        encoded = path.encode()
        entries += struct.pack("<IIIIHH", len(names), len(data), len(payload), len(payload), 0, 0)
        names += struct.pack("<I", 0xFFFFFFFF) + bytes([len(encoded)]) + encoded
        data += payload
    (package / "0.paz").write_bytes(data)
    (package / "0.pamt").write_bytes(struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0)
        + struct.pack("<I", len(names)) + names + struct.pack("<II", 0, len(payloads)) + entries)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    archive.archive_backend_client._cache_root = tmp_path / "cache"
    archive.archive_backend_client._explicit_worker = _WORKER
    # Headless row selection must not launch a renderer for deliberately fake PAC bytes.
    archive._render_archive_preview = lambda *args, **kwargs: None
    archive._start_archive_preview_core_prewarm = lambda: None
    yield window
    if hasattr(window, "_scanner_original_consumers"):
        window.text_search_tab, window.replace_assistant_tab, window.research_tab = window._scanner_original_consumers
    window._finalize_close()
    assert _Awaiter._wait_until(lambda: archive.archive_backend_client.process_id == 0, timeout_ms=10_000)
    window.deleteLater()
    _APP.processEvents()


def _open(window, root, *, refresh=False):
    archive = window.archive
    old_session = archive.archive_remote_bridge.current_session
    archive.archive_package_root_edit.setText(str(root))
    archive.scan_archives(force_refresh=refresh, activate_archive_tab=False)
    assert _Awaiter._wait_until(lambda: archive.archive_backend_failure_dialog is not None
        or (not archive.archive_remote_query_pending and archive.archive_remote_bridge.current_session is not None
            and archive.archive_remote_bridge.current_session is not old_session), timeout_ms=15_000)
    assert archive.archive_backend_failure_dialog is None
    return archive.archive_remote_bridge.current_session


class _Consumer(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.sessions = []
        self.handles = []

    def is_busy(self):
        return False

    def apply_responsive_splitter_sizes(self, _width):
        pass

    def auto_fit_columns(self):
        pass

    def splitter_sizes(self):
        return []

    main_splitter_sizes = groups_splitter_sizes = unknown_splitter_sizes = splitter_sizes
    reference_splitter_sizes = analysis_splitter_sizes = notes_splitter_sizes = splitter_sizes

    def set_archive_catalogue_session(self, session):
        self.sessions.append(session)

    def set_archive_catalogue_context(self, session, handle):
        self.sessions.append(session)
        self.handles.append(handle)


def test_cold_warm_refresh_filter_pages_names_and_catalogue_handoffs(workspace, tmp_path):
    assert _WORKER.is_file(), "Build the affected managed worker before this test."
    window, root = workspace, tmp_path / "game"
    write_character_archive(root)
    _write_items(root)
    (root / "CrimsonDesert.exe").write_bytes(b"owned synthetic executable")
    for folder in ("backups", "Cdmods"):
        path = root / folder / "nested"
        path.mkdir(parents=True)
        (path / "broken.pamt").write_bytes(b"excluded invalid archive")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    consumers = [_Consumer(window) for _ in range(3)]
    window._scanner_original_consumers = (window.text_search_tab, window.replace_assistant_tab, window.research_tab)
    window.text_search_tab, window.replace_assistant_tab, window.research_tab = consumers
    archive = window.archive
    service = archive.archive_catalogue_service
    awaiter = _Awaiter(service)
    cold = _open(window, root)
    assert not cold.cache_hit and cold.entry_count == 106
    assert all(consumer.sessions[-1] == cold for consumer in consumers)
    assert archive.archive_tree.remote_model_active()
    assert not archive.archive_entries
    assert _Awaiter._wait_until(lambda: archive.archive_item_finder_warmup_controller._catalogue_ready
        or not archive.archive_item_names_failure_panel.isHidden(), timeout_ms=15_000)
    assert archive.archive_item_names_failure_panel.isHidden()
    names = awaiter.wait(service.search_item_catalog(ItemCatalogSearchRequest(cold.session_id, query="Fixture Helm"),
        ui_generation=archive.archive_remote_bridge.controller.generation))
    assert names.total_matches == 1 and names.items[0].display_name == "Fixture Helm"
    assert window._load_game_executable_fingerprints()
    warm = _open(window, root)
    assert warm.cache_hit and warm.fingerprint == cold.fingerprint
    fresh = _open(window, root, refresh=True)
    assert not fresh.cache_hit and fresh.session_id != warm.session_id
    bridge = archive.archive_remote_bridge
    bridge.controller.apply_query(ArchiveQuery(fresh.session_id, include_text="hero_body", extensions=(".pac",), view_mode=ArchiveViewMode.FLAT,
        sort_active=True, sort_descending=True))
    assert _Awaiter._wait_until(lambda: bridge.model.query_handle is not None
        and bridge.model.query_handle.generation == bridge.controller.generation, timeout_ms=10_000)
    handle = bridge.model.query_handle
    page = awaiter.wait(service.fetch_page(FetchPageRequest(handle.query_id, 72, 13), ui_generation=handle.generation))
    assert handle.total_matches == 85 and len(page.rows) == 13 and page.rows[0].path.endswith("0012.pac")
    assert all(consumer.sessions[-1] == fresh for consumer in consumers)
    assert consumers[-1].handles[-1] == handle
    prepared = awaiter.wait(service.prepare_entry(PrepareEntryRequest(fresh.session_id, page.rows[0].entry_id),
        ui_generation=handle.generation))
    assert Path(prepared.prepared_path).read_bytes() == b"PAC\0synthetic"
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("obsolete", ["legacy", "shadow", "v2", "invalid"])
def test_obsolete_override_and_missing_helper_never_create_legacy_workers(tmp_path, monkeypatch, obsolete):
    monkeypatch.setenv("CDMW_ARCHIVE_BACKEND", obsolete)
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    archive.archive_backend_client._explicit_worker = tmp_path / "missing-worker.exe"
    archive.archive_package_root_edit.setText(str(tmp_path))
    notices = []
    original_log = window.append_archive_log
    window.append_archive_log = lambda message, **kwargs: (notices.append(message), original_log(message, **kwargs))[-1]
    try:
        for _ in range(2):
            archive.scan_archives(activate_archive_tab=False)
            assert _Awaiter._wait_until(lambda: archive.archive_backend_failure_dialog is not None, timeout_ms=5_000)
            assert "worker_missing" in archive.archive_backend_failure_dialog.panel.report
            assert archive.archive_backend_client.process_id == 0
        assert sum("CDMW_ARCHIVE_BACKEND is obsolete" in message for message in notices) == 1
        assert archive.archive_remote_bridge is not None
        for name in ("archive_scan_worker", "archive_index_worker", "archive_filter_worker", "archive_scan_cache_worker",
                     "archive_backend_mode", "archive_backend_legacy_session_override"):
            assert not hasattr(archive, name)
    finally:
        window._finalize_close()
        window.deleteLater()
        _APP.processEvents()


def test_background_name_failure_keeps_browsing_and_offers_targeted_retry(workspace, tmp_path):
    root = tmp_path / "game"
    write_character_archive(root)
    session = _open(workspace, root)
    archive = workspace.archive
    panel = archive.archive_item_names_failure_panel
    assert _Awaiter._wait_until(lambda: not panel.isHidden(), timeout_ms=10_000)
    assert "Item names unavailable" in panel.message.text()
    assert "build_name_index" in panel.report and "item_names_unavailable" in panel.report
    assert archive.archive_remote_bridge.current_session == session
    assert archive.archive_remote_bridge.model.rowCount() == session.entry_count
    panel.retry_button.click()
    assert _Awaiter._wait_until(lambda: archive.archive_item_finder_warmup_controller._state == "failed", timeout_ms=10_000)
    assert archive.archive_remote_bridge.current_session == session
    assert archive.archive_backend_failure_dialog is None


def test_cancelled_refresh_preserves_uncached_pages_from_the_real_worker(workspace, tmp_path):
    root = tmp_path / "game"
    write_character_archive(root)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    bridge = workspace.archive.archive_remote_bridge
    bridge.model._page_size = 8
    session = _open(workspace, root)
    original_query = bridge.model.query_handle.query_id
    bridge.open_archive(root, force_refresh=True, activate_tab=False)
    assert bridge.cancel_pending_update()
    current_generation = bridge.controller.generation
    index = bridge.model.index(20, 0)
    assert bridge.model.entry_for_index(index) is None
    assert bridge.model.data(index) == "Loading..."
    assert _Awaiter._wait_until(lambda: bridge.model.entry_for_index(index) is not None
        or workspace.archive.archive_backend_failure_dialog is not None, timeout_ms=10_000)
    assert workspace.archive.archive_backend_failure_dialog is None
    assert bridge.current_session == session and bridge.model.query_handle.query_id == original_query
    assert bridge.model.query_handle.generation == current_generation
    assert bridge.model.entry_for_index(index).session_id == session.session_id
    assert not workspace.archive.archive_remote_query_pending
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_game_update_evidence_is_saved_only_after_current_backend_publication(workspace, tmp_path):
    root = tmp_path / "game"
    write_character_archive(root)
    executable = root / "CrimsonDesert.exe"
    executable.write_bytes(b"version one")
    _open(workspace, root)
    records = workspace._load_game_executable_fingerprints()
    first = next(iter(records.values()))
    first["compatible_features"] = {"fixture_feature": first["sha256"]}
    workspace._save_game_executable_fingerprints(records)
    warm = _open(workspace, root)
    assert warm.cache_hit
    executable.write_bytes(b"owned synthetic version two")
    updated = _open(workspace, root)
    second = next(iter(workspace._load_game_executable_fingerprints().values()))
    assert not updated.cache_hit
    assert second["previous_sha256"] == first["sha256"] and second["sha256"] != first["sha256"]
    assert second["update_detected_at"] and second["compatible_features"] == first["compatible_features"]


def test_root_change_invalidates_pending_opening_and_its_error_display(workspace, tmp_path):
    archive = workspace.archive
    archive.archive_backend_client._explicit_worker = tmp_path / "missing-worker.exe"
    archive.archive_package_root_edit.setText(str(tmp_path))
    archive.scan_archives(activate_archive_tab=False)
    generation = archive.archive_open_generation
    archive.archive_package_root_edit.setText(str(tmp_path / "different-root"))
    assert archive.archive_open_generation > generation and archive.archive_game_fingerprint_stop.is_set()
    for _ in range(20):
        _APP.processEvents()
    assert archive.archive_backend_failure_dialog is None and not archive.archive_remote_query_pending
