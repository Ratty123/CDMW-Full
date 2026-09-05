"""Snapshot-owned preview warm-up, routing, and cancellation behavior."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings
from cdmw.workers.new_item_preview_warmup import NewItemPreviewWarmup
from cdmw.workers.new_item_workers import snapshot_task


def entry(root, path="character/model/head.pac", size=65536):
    return ArchiveEntry(path=path, pamt_path=root / "0000" / "0.pamt",
                        paz_file=root / "0000" / "0.paz", offset=0,
                        comp_size=size, orig_size=size, flags=0, paz_index=0)


def test_warmup_overlaps_archive_reads_and_finishes_before_snapshot_publication(tmp_path, monkeypatch):
    from cdmw.core import archive_format
    from cdmw.services import preview_rendering_service

    selected = entry(tmp_path)
    batches = [
        [entry(tmp_path, "character/skinnedmesh_box.pac"), entry(tmp_path, size=1024), selected],
        [entry(tmp_path, "character/model/second.pac")],
    ]
    tables = [tmp_path / "0000" / "0.pamt", tmp_path / "0001" / "0.pamt"]
    started, more_archive_work, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def native_job(candidate, **kwargs):
        calls.append((candidate, kwargs))
        started.set()
        assert more_archive_work.wait(1), "snapshot blocked on warm-up before reading the next archive"
        (kwargs["output_root"] / "manifest.json").write_text("{}")
        finished.set()
        return SimpleNamespace(status="ok")

    def parse(path):
        if path == tables[1]:
            assert started.wait(1)
            more_archive_work.set()
        return batches[tables.index(path)]

    expected = object()
    def build_snapshot(listed, **_kwargs):
        assert list(listed) == batches[0] + batches[1]
        assert finished.wait(1)
        return expected

    monkeypatch.setattr(archive_format, "discover_pamt_files", lambda _: tables)
    monkeypatch.setattr(archive_format, "parse_archive_pamt", parse)
    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", native_job)
    result = snapshot_task((), service=SimpleNamespace(build_snapshot=build_snapshot),
        package_root=tmp_path, native_preview_core_cache_root=tmp_path / "native-cache",
        preview_render_settings=ModelPreviewRenderSettings(d3d11_tone_gamma=1.17),
    )(lambda _: None, threading.Event())
    assert result is expected and len(calls) == 1
    candidate, context = calls[0]
    assert candidate == selected and candidate is not selected
    assert context["cache_root"] == tmp_path / "native-cache"
    assert context["package_root"] == tmp_path
    assert context["render_settings"].use_textures_by_default
    assert context["render_settings"].d3d11_tone_gamma == 1.17
    assert not context["output_root"].exists()
    assert not context["stop_event"].thread.is_alive()


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_snapshot_drains_unfinished_warmup_on_every_terminal_path(tmp_path, monkeypatch, outcome):
    from cdmw.services import preview_rendering_service

    started = threading.Event()
    stop = threading.Event()
    calls = []
    def native_job(_entry, **kwargs):
        calls.append(kwargs)
        started.set()
        while not kwargs["stop_event"].is_set():
            threading.Event().wait(0.005)
        raise RunCancelled("cancelled")

    def build_snapshot(_listed, **_kwargs):
        assert started.wait(1)
        if outcome == "error":
            raise ValueError("snapshot failure")
        if outcome == "cancel":
            stop.set()
            raise RunCancelled("snapshot cancelled")
        return "snapshot"

    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", native_job)
    task = snapshot_task((entry(tmp_path),), service=SimpleNamespace(build_snapshot=build_snapshot),
        native_preview_core_cache_root=tmp_path / "native-cache")
    if outcome == "success":
        assert task(lambda _: None, stop) == "snapshot"
    else:
        with pytest.raises(ValueError if outcome == "error" else RunCancelled, match="snapshot"):
            task(lambda _: None, stop)
    assert calls and not calls[0]["stop_event"].thread.is_alive()
    assert not calls[0]["output_root"].exists()


@pytest.mark.parametrize("disabled", ["cache", "cancelled"])
def test_disabled_warmup_does_not_start_a_native_job(tmp_path, disabled):
    stop = threading.Event()
    if disabled == "cancelled":
        stop.set()
    warmup = NewItemPreviewWarmup(None if disabled == "cache" else tmp_path, None, stop)
    warmup.offer((entry(tmp_path),))
    warmup.finish()
    assert warmup.thread is None


def test_snapshot_captures_settings_before_the_worker_starts(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(NewItemPreviewWarmup, "offer", lambda self, _: captured.append(self.render_settings))
    settings = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17)
    task = snapshot_task((entry(tmp_path),), service=SimpleNamespace(build_snapshot=lambda *_a, **_k: None),
        native_preview_core_cache_root=tmp_path / "native-cache", preview_render_settings=settings)
    settings.d3d11_tone_gamma = 0.8
    task(lambda _: None, threading.Event())
    assert captured[0].d3d11_tone_gamma == 1.17


def test_native_warmup_failure_does_not_fail_the_snapshot(tmp_path, monkeypatch):
    from cdmw.services import preview_rendering_service

    failed = threading.Event()
    def fail(*_args, **_kwargs):
        failed.set()
        raise OSError("optional helper unavailable")
    def build(_entries, **_kwargs):
        assert failed.wait(1)
        return "valid snapshot"
    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", fail)
    assert snapshot_task((entry(tmp_path),), service=SimpleNamespace(build_snapshot=build),
        native_preview_core_cache_root=tmp_path / "native-cache",
    )(lambda _: None, threading.Event()) == "valid snapshot"


@pytest.mark.parametrize("cache_mode", ["balanced", "off"])
def test_tab_routes_warmup_to_the_same_native_cache_as_template_preview(tmp_path, monkeypatch, cache_mode):
    from PySide6.QtWidgets import QApplication
    from cdmw.services.cache_layout import runtime_cache_layout
    from cdmw.ui.new_item.tab import NewItemStudioTab

    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(archive_cache_root=tmp_path / "archive-cache")
    window.shell = window
    window.archive = window
    window.textures = window
    tab = NewItemStudioTab(window=window, get_package_root=lambda: str(tmp_path))
    tab._preview_cache_mode = cache_mode
    requests = []
    monkeypatch.setattr(tab.controller, "start_snapshot", lambda *args, **kwargs: requests.append(kwargs) or False)
    try:
        tab.start_snapshot()
        expected = runtime_cache_layout(window.archive_cache_root).native_preview_root
        assert requests[0]["native_preview_core_cache_root"] == (expected if cache_mode == "balanced" else None)
        assert requests[0]["preview_render_settings"] == tab._preview_render_settings
        assert tab._native_preview_core_cache_root() == expected
    finally:
        tab.shutdown()
        tab.deleteLater()
        app.processEvents()


def test_cancelled_job_stops_waiting_for_native_service_without_interrupting_its_owner(tmp_path, monkeypatch):
    from cdmw.rendering.native_preview_core import NativePreviewCoreServiceClient

    client = NativePreviewCoreServiceClient(tmp_path / "unused-preview-core.exe")
    monkeypatch.setattr(client, "_start_locked", lambda **_: pytest.fail("cancelled waiter dispatched"))
    monkeypatch.setattr(client, "_kill_locked", lambda: pytest.fail("cancelled waiter killed the active job"))
    stop, started = threading.Event(), threading.Event()
    outcomes = []
    def wait_for_service():
        started.set()
        try:
            client.preview_job(tmp_path / "job.json", tmp_path / "report.json", timeout_seconds=1, stop_event=stop)
        except RunCancelled:
            outcomes.append("cancelled before dispatch")
    thread = threading.Thread(target=wait_for_service)
    client._lock.acquire()
    try:
        thread.start()
        assert started.wait(1)
        stop.set()
        thread.join(1)
        assert not thread.is_alive()
        assert outcomes == ["cancelled before dispatch"]
    finally:
        client._lock.release()
        thread.join(1)
