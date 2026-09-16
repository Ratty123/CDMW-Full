from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ArchivePreviewResult
from cdmw.rendering.native_preview_package_cache import acquire_native_preview_package_cache_lease_for_path
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_package_retirement import track_archive_preview_package
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin
from cdmw.ui.new_item.item_preview import ProgressivePreviewSource, _PreviewPackageTask


_APP = QApplication.instance() or QApplication([])


def _package(root, name):
    path = root / f"cdmw_rust_preview_{name}" / "package"
    path.mkdir(parents=True)
    (path / "manifest.json").write_text("{}", encoding="utf-8")
    return path


@pytest.mark.parametrize("outcome", ["cancel_geometry", "reject_geometry", "reject_fast", "cancel_after_fast", "material_error", "success"])
def test_progressive_owner_removes_only_undelivered_packages(tmp_path, monkeypatch, outcome):
    geometry = _package(tmp_path, "geometry")
    fast = _package(tmp_path, "fast")
    full = _package(tmp_path, "full")
    ready = threading.Event()
    stop = threading.Event()
    delivered = []

    def materials(_stop, **context):
        context["fast_package_ready"](fast)
        ready.set()
        if outcome == "material_error":
            # The full builder owns its failed construction; here it produced
            # only the fast result that this parallel owner must account for.
            raise RunCancelled("materials failed")
        return full

    def build_geometry(_stop):
        assert ready.wait(1)
        if outcome == "cancel_geometry":
            raise RunCancelled("geometry cancelled")
        return object()

    def progress(stage, total, path):
        if (stage == 1 and outcome == "reject_geometry") or (stage == 2 and outcome == "reject_fast"):
            raise RuntimeError("receiver failed")
        delivered.append(Path(path))
        if stage == 2 and outcome == "cancel_after_fast":
            stop.set()

    monkeypatch.setattr("cdmw.ui.new_item.item_preview.build_item_preview_package", lambda *_args, **_kw: geometry)
    task = _PreviewPackageTask(
        output_root=tmp_path, token=("template", 1),
        candidate=ProgressivePreviewSource(build_geometry, materials, supports_fast_material_package=True),
        is_placement=False, full_stage=False, base_package=None, render_settings=None,
        cache_mode="off", native_preview_core_cache_root=tmp_path / "native",
        source_usage_required=False, source_usage_acquired=False,
    )
    if outcome == "success":
        delivered.append(task(None, progress, stop).package_dir)
    else:
        with pytest.raises((RunCancelled, RuntimeError)):
            task(None, progress, stop)
    # Geometry cancellation happens before a geometry package is built, and
    # material_error never transfers ownership of the full package to the task.
    produced = [fast]
    if outcome != "cancel_geometry":
        produced.append(geometry)
    if outcome != "material_error":
        produced.append(full)
    for path in produced:
        assert path.exists() == (path in delivered), (outcome, path)
        assert path.parent.exists() == (path in delivered), "the temp wrapper must retire too"


def test_progressive_cleanup_preserves_durable_and_foreign_packages(tmp_path):
    from cdmw.ui.new_item.item_preview import preview_package_cleanup
    from cdmw.services.mesh_rust_preview_cache import rust_preview_package_cache_root

    durable = rust_preview_package_cache_root(tmp_path) / "packages" / "key" / "package"
    durable.mkdir(parents=True)
    foreign = _package(tmp_path / "outside", "foreign")
    assert preview_package_cleanup(durable, tmp_path) is None
    assert preview_package_cleanup(foreign, tmp_path / "owned") is None
    assert preview_package_cleanup(tmp_path, tmp_path) is None
    assert durable.exists() and foreign.exists()


class _ArchiveOwner(QObject, ArchivePreviewCacheMixin, ArchivePreviewWorkerMixin):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.shell = SimpleNamespace(_shutting_down=False, _record_runtime_event=lambda *_a, **_kw: None)
        self.archive_preview_cache = OrderedDict()
        self.archive_preview_cache_limit = 1
        self.archive_preview_cache_keys = {}
        self.archive_preview_request_sources = {}
        self.archive_preview_request_started_at = {}
        self.archive_preview_request_phase_timings = {}
        self.archive_preview_request_id = 2
        self.current_archive_preview_result = None
        self.archive_preview_thread = None

    def _native_preview_package_cache_root(self):
        return self.root

    def _record_runtime_event(self, *_args, **_kwargs):
        pass

    def _archive_preview_result_cacheable(self, _result):
        return True


def _collect(owner):
    retirement = owner._archive_preview_package_retirement
    retirement.collect()
    deadline = time.monotonic() + 3
    while retirement.lane.iter_shutdown_workers() and time.monotonic() < deadline:
        _APP.processEvents()
        time.sleep(0.005)
    assert not retirement.lane.iter_shutdown_workers()
    retirement.collect()


@pytest.mark.parametrize("route", ["stale", "evicted", "cleared", "shutdown"])
def test_archive_retires_unreferenced_transient_packages(tmp_path, route):
    owner = _ArchiveOwner(tmp_path)
    package = _package(tmp_path, route)
    result = ArchivePreviewResult("ok", dotnet_preview_package_path=str(package))
    if route == "stale":
        owner._handle_archive_preview_ready(1, result)
    else:
        owner._store_cached_archive_preview_result("first", result)
        if route == "evicted":
            owner._store_cached_archive_preview_result("second", ArchivePreviewResult("ok"))
        elif route == "cleared":
            owner._clear_archive_preview_cache()
        else:
            owner.shell._shutting_down = True
    _collect(owner)
    assert not package.parent.exists()
    assert not list(tmp_path.glob(".cdmw_retired_preview_*"))
    assert not owner._archive_preview_package_retirement.timer.isActive()


@pytest.mark.parametrize("reader", ["cache", "current", "textures", "worker", "renderer", "retiring_helper"])
def test_archive_cleanup_waits_for_readers(tmp_path, reader):
    owner = _ArchiveOwner(tmp_path)
    package = _package(tmp_path, reader)
    result = ArchivePreviewResult("ok", dotnet_preview_package_path=str(package))
    track_archive_preview_package(owner, result)
    lease = None
    if reader == "cache":
        owner.archive_preview_cache["current"] = result
    elif reader == "current":
        owner.current_archive_preview_result = result
    elif reader == "textures":
        owner._archive_pending_texture_result = result
    elif reader == "worker":
        owner.archive_preview_thread = object()
    elif reader == "renderer":
        lease = acquire_native_preview_package_cache_lease_for_path(package)
    else:
        owner.archive_d3d11_preview_host = SimpleNamespace(controller=SimpleNamespace(
            process=None, _pending_process_exits={1},
        ))
    try:
        _collect(owner)
        assert package.exists()
    finally:
        if lease is not None:
            lease.release()
        owner.archive_preview_cache.clear()
        owner.current_archive_preview_result = None
        owner._archive_pending_texture_result = None
        owner.archive_preview_thread = None
        owner.archive_d3d11_preview_host = None
        _collect(owner)
    assert not package.parent.exists()


def test_archive_cleanup_ignores_foreign_and_durable_roots(tmp_path):
    owner = _ArchiveOwner(tmp_path / "owned")
    foreign = _package(tmp_path, "foreign")
    durable = tmp_path / "owned" / "rust_wgpu_v1" / "packages" / "key" / "package"
    durable.mkdir(parents=True)
    for package in (foreign, durable):
        track_archive_preview_package(owner, ArchivePreviewResult("ok", dotnet_preview_package_path=str(package)))
    _collect(owner)
    assert foreign.exists() and durable.exists()
