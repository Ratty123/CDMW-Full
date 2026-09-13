"""Actual QProcess integration, independent of renderer availability."""
from dataclasses import replace
from pathlib import Path
import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest, PingResult
from cdmw.domain.archives.character_catalogue import (
    CharacterCatalogSearchRequest, CharacterCatalogDetailRequest, CharacterCatalogScopeRequest,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter
from tests.helpers.character_catalog_fixture import write_character_archive

_APPLICATION = None


def test_actual_worker_catalogue_paging_details_scope_and_refresh(tmp_path):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    worker = Path(__file__).resolve().parents[1] / "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe"
    assert worker.is_file(), "Build the affected archive worker before running this integration test."
    root = tmp_path / "game"
    write_character_archive(root)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    client = ArchiveBackendClient(cache_root=tmp_path / "cache", worker_executable=worker)
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    try:
        session = awaiter.wait(service.open_archive(OpenArchiveRequest(str(root)), ui_generation=1))
        assert service.character_catalog_available
        build = awaiter.wait(service.build_character_catalog(session.session_id, ui_generation=1))
        assert not build.used_cache and build.candidate_count == build.resolved_count + build.unresolved_count + build.excluded_count
        assert awaiter.wait(service.build_character_catalog(session.session_id, ui_generation=1)).used_cache
        request = CharacterCatalogSearchRequest(session.session_id)
        page = awaiter.wait(service.search_character_catalog(request, ui_generation=1))
        next_page = awaiter.wait(service.search_character_catalog(replace(request, page_start=72), ui_generation=1))
        assert len(page.rows) == 72 and page.total_matches == 86 and len(next_page.rows) == 14
        assert not {r.key for r in page.rows} & {r.key for r in next_page.rows}
        assert all(r.path.endswith(".pac") and r.model_count == 1 and r.role in {"body", "whole_character"}
                   and "_foot_" not in r.path and "_spline" not in r.path for r in (*page.rows, *next_page.rows))
        fur = awaiter.wait(service.search_character_catalog(replace(request, query="spline", tab="faces", role="hair"), ui_generation=1))
        assert len(fur.rows) == 1 and fur.rows[0].role == "hair"
        unknown = awaiter.wait(service.search_character_catalog(replace(request, role="unclassified"), ui_generation=1))
        assert len(unknown.rows) == 1 and unknown.rows[0].path.endswith("mystery.pac") and unknown.rows[0].preview_status == "base_appearance"
        selected = next(r for r in page.rows if r.path.endswith("hero_body_0000.pac"))
        detail = awaiter.wait(service.get_character_catalog_detail(CharacterCatalogDetailRequest(session.session_id, selected.key), ui_generation=1))
        assert len(detail.models) == 1 and len(detail.related) >= 2 and detail.row.usage_count >= 2
        appearances = awaiter.wait(service.search_character_catalog(replace(request, view="appearances", related_key=selected.key), ui_generation=1))
        assert appearances.total_matches == 2
        exact = awaiter.wait(service.scope_character_catalog(CharacterCatalogScopeRequest(session.session_id, selected.key), ui_generation=1))
        related = awaiter.wait(service.scope_character_catalog(CharacterCatalogScopeRequest(session.session_id, selected.key, True), ui_generation=1))
        assert tuple(exact.entry_ids) == (detail.models[0].entry_id,)
        assert set(exact.entry_ids) < set(related.entry_ids)
        assert any(f.extension == ".dds" for f in detail.files)
        capped = awaiter.wait(service.scope_character_catalog(CharacterCatalogScopeRequest(session.session_id, selected.key, True, 1), ui_generation=1))
        assert capped.truncated and capped.total_count == related.total_count and len(capped.entry_ids) == 1
        unresolved = awaiter.wait(service.search_character_catalog(replace(request, query="absent", tab="faces", view="appearances"), ui_generation=1))
        assert unresolved.rows[0].preview_status == "unresolved_model"
        fresh = awaiter.wait(service.refresh_archive(root, ui_generation=2))
        assert fresh.session_id != session.session_id
        assert not awaiter.wait(service.build_character_catalog(fresh.session_id, ui_generation=2)).used_cache
        assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    finally:
        client.shutdown()
        assert _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=10_000)
        client.deleteLater()
        _APPLICATION.processEvents()


def test_old_worker_ping_has_no_character_capability():
    old = PingResult.from_wire(dict(worker_version="old", protocol_version=3, native_abi_version=1, index_version=3, process_id=1))
    assert old.capabilities == ()
    with pytest.raises(ValueError):
        PingResult.from_wire(dict(worker_version="old", protocol_version=3, native_abi_version=1, index_version=3, process_id=1, capabilities=[3]))
