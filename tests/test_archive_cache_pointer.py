"""A cache pointer never makes the archive worker touch a folder outside its cache.

The real managed worker (cdmw-full-archive-worker.exe) over an owned synthetic game under
tmp_path, driven through Browse Archives as tests/test_archive_single_backend_workspace.py
does. From the review of rr/parity-deps-p20 (tests/test_review_archive_cache_pointer.py on
rr/parity-review), which found the fault in the shipped worker: it passes once the worker
is rebuilt from this branch.
"""

from __future__ import annotations

import hashlib
import json

from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
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


def _window(tmp_path):
    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    archive = window.archive
    archive.archive_backend_client._cache_root = tmp_path / "cache"
    archive.archive_backend_client._explicit_worker = _WORKER
    archive._render_archive_preview = lambda *args, **kwargs: None
    archive._start_archive_preview_core_prewarm = lambda: None
    return window


def _close(window):
    window._finalize_close()
    assert _Awaiter._wait_until(lambda: window.archive.archive_backend_client.process_id == 0, timeout_ms=10_000)
    window.deleteLater()
    _APP.processEvents()


def test_a_cache_pointer_never_makes_the_worker_touch_the_game(tmp_path, monkeypatch) -> None:
    """generationId is read from the cache's current.json. A pointer whose root_id and
    fingerprint match but whose generation_id names another folder (an absolute path, or
    ..\\ segments) once made the worker create <parent>\\.leases\\<name>.lock beside that
    folder and, when it failed validation, Directory.Move it into the cache's quarantine.
    The worker now accepts only the id form it writes and rebuilds instead."""

    assert _WORKER.is_file(), "Build the managed worker before this test."
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    root = tmp_path / "game"
    write_character_archive(root)
    _write_items(root)
    (root / "CrimsonDesert.exe").write_bytes(b"owned synthetic executable")
    first = _window(tmp_path)
    try:
        _open(first, root)
    finally:
        _close(first)
    (pointer_path,) = list((tmp_path / "cache").rglob("current.json"))
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["generation_id"] = str(root / "0036")  # a corrupt or crafted pointer naming a game package
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    before = _fingerprint(root)
    second = _window(tmp_path)  # a fresh start: a new worker reads the pointer
    try:
        try:
            _open(second, root)
        except AssertionError:
            pass  # the open may fail; what counts is the game folder
    finally:
        _close(second)
    assert (root / "0036" / "0.pamt").is_file(), "the worker moved a game package into its quarantine"
    assert _fingerprint(root) == before, "the worker changed the game folder"
    assert not (tmp_path / ".leases").exists(), "the worker wrote a lease beside the game folder"
