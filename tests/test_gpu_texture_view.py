"""The two read-only hosts, direct DDS handoff and stale/fallback lifecycle."""
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QSettings, QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QWidget

from cdmw.ui.preview import texture_view as module


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and not predicate():
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def _png(path):
    image = QImage(4, 4, QImage.Format_RGBA8888)
    image.fill(0xFF347890)
    assert image.save(str(path))
    return image


def test_archive_texture_host_constructs_and_uses_existing_zoom_controls(app):
    from cdmw.ui.archive_browser.preview_layout import ArchivePreviewLayoutMixin
    from cdmw.ui.archive_browser.preview_zoom import ArchivePreviewZoomMixin

    class ArchiveHost(ArchivePreviewLayoutMixin, ArchivePreviewZoomMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.archive_preview_stack = QStackedWidget(self)
            self.archive_preview_zoom_value = QLabel(self)
            self.archive_preview_zoom_factor = 1.0
            self.archive_preview_fit_to_view = True
            self._build_archive_gpu_texture_preview()

    host = ArchiveHost()
    assert isinstance(host.archive_texture_preview, module.GpuTexturePreview)
    assert host._active_archive_preview_zoom_widget() is host.archive_texture_preview
    host._set_archive_preview_zoom_factor(2)
    assert host.archive_texture_preview._state["zoom"] == 2
    assert host.archive_preview_zoom_value.text() == "200%"
    host._set_archive_preview_fit_mode()
    assert host.archive_texture_preview._state["fit"]
    host.archive_texture_preview.shutdown()
    host.close()


def test_textures_replace_host_constructs_without_editor_decode(app, tmp_path):
    from cdmw.ui.replace_assistant_tab import ReplaceAssistantTab
    from cdmw.ui.texture_workflow.job_review import TextureJobReviewMixin
    from cdmw.ui.texture_workflow.job import _source_key
    calls = []
    workspace = SimpleNamespace(job=SimpleNamespace(cancel=calls.append))
    tab = ReplaceAssistantTab(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
        base_dir=tmp_path, get_archive_entries=lambda: (), get_original_root=lambda: "",
        get_current_config=lambda: None, workspace=workspace,
    )
    assert isinstance(tab.texture_preview, module.GpuTexturePreview)
    assert tab.main_splitter.indexOf(tab.texture_preview) == 1
    path = tmp_path / "owned.dds"
    key = "owned"
    # A real lazy-container consumer is exercised without loading the editing canvas.
    from cdmw.ui.texture_workflow import job_review
    original = job_review.created_tool_widget
    job_review.created_tool_widget = lambda value: tab if value is tab else None
    try:
        workspace.job = SimpleNamespace(mode="replace", assets={key: object()}, active_asset_key="", cancel=calls.append)
        workspace._replacement_asset_keys = {_source_key(path): key}
        workspace.matcher_container = tab
        TextureJobReviewMixin.select_replacement_asset(workspace, path)
        assert tab.texture_preview._path == str(path)
        assert workspace.job.active_asset_key == key
        tab._refresh_queue_tree()
        assert not tab.texture_preview._path
    finally:
        job_review.created_tool_widget = original
        tab.request_shutdown()
        tab.close()
    assert tab.texture_preview._closed


def test_gpu_controls_and_stale_events_do_not_replace_newer_file(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.load_path(tmp_path / "first.dds")
    stale = host._generation
    host.load_path(tmp_path / "second.dds")
    host._event({"event": "loaded", "generation": stale, "metadata": {}})
    assert not host._gpu
    sent = []
    monkeypatch.setattr(host, "_send", lambda **kw: sent.append(kw))
    host._event({"event": "loaded", "generation": host._generation,
                 "metadata": {"width": 4096, "height": 4096, "mip_count": 13, "format": "Bc5Snorm"}})
    assert host._gpu and host.normal_z.isEnabled()
    assert host.mips.count() == 13
    host.channels.setCurrentIndex(2)
    host.mips.setCurrentIndex(3)
    host.normal_z.setChecked(True)
    host._actual_size()
    assert sent[-1]["state"] == dict(channel=2, mip=3, reconstruct_z=True, fit=False, zoom=1.0, pan=[0.0, 0.0], pixel_ratio=host.viewport.devicePixelRatioF())
    monkeypatch.setattr(host.viewport, "devicePixelRatioF", lambda: 2.0)
    host.eventFilter(host.viewport, QEvent(QEvent.DevicePixelRatioChange))
    assert sent[-1]["state"]["pixel_ratio"] == 2.0
    assert host.current_display_scale() == 1.0
    host.load_path(tmp_path / "one-mip.dds")
    assert host._state["mip"] == 0 and host._state["channel"] == 0
    assert host.mips.currentIndex() == 0 and not host.normal_z.isChecked()
    host.shutdown()
    host._prepared(stale, {"image": _png(tmp_path / "stale.png")})
    assert host._closed
    host.close()


def test_missing_helper_and_failed_gpu_use_cancellable_image_fallback(app, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "validate_rust_mesh_editor_package", lambda _: "not available")
    image_path = tmp_path / "fallback.png"
    _png(image_path)
    from cdmw.services import preview_workflow_service
    calls = []
    def fallback(path, *, stop_event):
        calls.append((path, stop_event))
        return image_path
    monkeypatch.setattr(preview_workflow_service, "ensure_dds_display_preview_png", fallback)
    host = module.GpuTexturePreview()
    host.show()
    loaded = []
    host.loaded.connect(loaded.append)
    host.load_path(tmp_path / "owned.dds")
    _wait(app, lambda: bool(loaded))
    assert loaded[-1]["backend"] == "image" and len(calls) == 1
    assert not host.channels.isEnabled()
    host._gpu = True
    host._fallback()
    _wait(app, lambda: len(loaded) == 2)
    assert len(calls) == 2 and not host._gpu
    host.close()
    QThreadPool.globalInstance().waitForDone(1000)


def test_clear_and_hide_cancel_pending_preparation_and_ignore_old_process(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    pending = []
    monkeypatch.setattr(host, "_prepare", lambda **_: pending.append(host._generation))
    host.show()
    host.load_path(tmp_path / "owned.dds")
    generation = host._generation
    from threading import Event
    task = SimpleNamespace(stop=Event())
    process = object()
    stopped = []
    monkeypatch.setattr(module, "stop_qprocess_async", stopped.append)
    host._task, host._process = task, process
    host.hide()
    assert task.stop.is_set() and stopped == [process]
    assert host._generation != generation and host._process is None
    host._process_failed(process)
    assert len(pending) == 1
    host.show()
    assert len(pending) == 2
    host.clear_preview()
    assert not host._path and host._closed
    host.close()


def _resident_helper(host, monkeypatch):
    """Stand in for a helper that has started and reported ready."""
    sent, stopped, prepared = [], [], []
    monkeypatch.setattr(host, "_send", lambda **kw: sent.append(kw))
    monkeypatch.setattr(host, "_prepare", lambda **kw: prepared.append(kw))
    monkeypatch.setattr(module, "stop_qprocess_async", stopped.append)
    process = object()
    host._process, host._ready = process, True
    return process, sent, stopped, prepared


def _loads(sent):
    return [message for message in sent if message.get("command") == "load"]


def _loaded(host, generation):
    host._event({"event": "loaded", "generation": generation,
                 "metadata": {"width": 64, "height": 64, "mip_count": 1, "format": "Bc1Unorm"}})


def test_ready_helper_draws_the_next_dds_without_being_restarted(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.show()
    process, sent, stopped, prepared = _resident_helper(host, monkeypatch)
    host.load_path(tmp_path / "first.dds")
    first = _loads(sent)
    assert [load["path"] for load in first] == [str(tmp_path / "first.dds")]
    assert first[0]["generation"] == host._generation
    _loaded(host, host._generation)
    assert host._gpu and host.has_ready_helper()
    host.load_path(tmp_path / "second.dds")
    loads = _loads(sent)
    assert [load["path"] for load in loads] == [str(tmp_path / "first.dds"), str(tmp_path / "second.dds")]
    assert loads[1]["generation"] > loads[0]["generation"]
    assert stopped == [] and prepared == [] and host._process is process
    # The previous texture stays up, not a placeholder, until the new one is drawn.
    assert host.stack.currentWidget() is host.viewport and not host._gpu
    _loaded(host, loads[0]["generation"])
    assert not host._gpu
    _loaded(host, loads[1]["generation"])
    assert host._gpu
    # Only DDS files are drawn by the helper.
    host.load_path(tmp_path / "plain.png")
    assert stopped == [process] and host._process is None and not host.has_ready_helper()
    assert prepared == [{"fallback": False}] and host.stack.currentWidget() is host.scroll
    host.shutdown()
    host.close()


def test_helper_still_starting_loads_only_the_newest_path(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.show()
    process, sent, stopped, prepared = _resident_helper(host, monkeypatch)
    host._ready = False
    host.load_path(tmp_path / "first.dds")
    host.load_path(tmp_path / "second.dds")
    assert stopped == [] and prepared == [] and _loads(sent) == []
    assert host._timeout.isActive()
    host._event({"event": "ready", "protocol": "cdmw_texture_view_v1"})
    assert [load["path"] for load in _loads(sent)] == [str(tmp_path / "second.dds")]
    assert host.stack.currentWidget() is host.viewport
    host.shutdown()
    host.close()


def test_hidden_ready_helper_waits_for_the_next_texture_then_retires(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.show()
    process, sent, stopped, prepared = _resident_helper(host, monkeypatch)
    host.load_path(tmp_path / "first.dds")
    shown = host._generation
    host.hide()
    assert stopped == [] and host._process is process and host._idle.isActive()
    _loaded(host, shown)
    assert not host._gpu  # an answer for a view nobody sees is stale
    host.show()
    loads = _loads(sent)
    assert len(loads) == 2 and loads[1]["generation"] > loads[0]["generation"]
    assert not host._idle.isActive()
    host.hide()
    host._retire_idle_helper()
    assert stopped == [process] and host._process is None
    host.show()
    assert prepared == [{"fallback": False}]
    host.shutdown()
    host.close()


def test_texture_the_helper_cannot_draw_falls_back_and_keeps_the_helper(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.show()
    process, sent, stopped, prepared = _resident_helper(host, monkeypatch)
    host.load_path(tmp_path / "legacy.dds")
    host._event({"event": "error", "generation": host._generation, "message": "unsupported"})
    assert prepared == [{"fallback": True}] and stopped == [] and host._process is process
    assert host.stack.currentWidget() is host.scroll and host._idle.isActive()
    # An idle helper is not kept behind an image for ever.
    host._retire_idle_helper()
    assert stopped == [process]
    stopped.clear()
    host._process, host._ready = process, True
    host.load_path(tmp_path / "legacy.dds")
    host._event({"event": "error", "generation": host._generation, "message": "unsupported"})
    host.load_path(tmp_path / "next.dds")
    assert _loads(sent)[-1]["path"] == str(tmp_path / "next.dds") and stopped == []
    assert host.stack.currentWidget() is host.viewport
    # A protocol error is about the helper itself, so that one is replaced.
    host._event({"event": "error", "generation": 0, "message": "bad command"})
    assert stopped == [process] and host._process is None
    host.shutdown()
    host.close()


def test_helper_that_exits_while_hidden_is_started_again_not_replaced_by_an_image(app, tmp_path, monkeypatch):
    host = module.GpuTexturePreview()
    host.show()
    process, sent, stopped, prepared = _resident_helper(host, monkeypatch)
    host.load_path(tmp_path / "first.dds")
    host.hide()
    host._process_failed(process)
    assert host._process is None and prepared == [] and not host._idle.isActive()
    host.show()
    assert prepared == [{"fallback": False}]
    # On screen, a helper that exits leaves the image fallback.
    host._process, host._ready = process, True
    host._process_failed(process)
    assert prepared[-1] == {"fallback": True} and host._process is None
    host.shutdown()
    host.close()


def test_archive_worker_defers_dds_decode_only_for_opted_in_host(app, tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.workers.archive_preview_workers import ArchivePreviewWorker
    from cdmw.core import archive_preview_result_builder as builder
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<7I", header, 4, 124, 0x81007, 4, 4, 8, 0, 1)
    struct.pack_into("<II4s", header, 76, 32, 4, b"DXT1")
    struct.pack_into("<I", header, 108, 0x1000)
    source = tmp_path / "owned.dds"
    source.write_bytes(header + bytes(8))
    entry = ArchiveEntry("texture/owned.dds", tmp_path / "0.pamt", source, 0, 136, 136, 0, 0)
    monkeypatch.setattr(builder, "ensure_archive_preview_source", lambda *_, **__: (source, ""))
    decoded = []
    monkeypatch.setattr(builder, "ensure_dds_display_preview_png", lambda *_, **__: decoded.append(True) or tmp_path / "fallback.png")
    for gpu in (True, False):
        worker = ArchivePreviewWorker(1, entry, None, {}, {}, None, None, (), prefer_gpu_texture=gpu)
        result = worker._build_archive_preview_payload(quality_tier="full", render_settings=worker.render_settings)
        assert bool(result.preview_texture_path) is gpu
        assert bool(result.preview_image_path) is not gpu
        assert decoded == ([] if gpu else [True])


def test_browse_dispatch_constructs_the_real_worker_with_gpu_opt_in(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.ui.archive_browser import workers
    from cdmw.workers.archive_preview_workers import ArchivePreviewWorker

    class ControlledWorker(ArchivePreviewWorker):
        def moveToThread(self, thread):
            pass  # Inspect construction before starting asynchronous work.

    monkeypatch.setattr(workers, "ArchivePreviewWorker", ControlledWorker)
    monkeypatch.setattr(QThread, "start", lambda self: None)
    owner = QWidget()
    owner.shell = SimpleNamespace(_record_runtime_event=lambda *_, **__: None)
    owner._find_archive_preview_companion_entry = lambda *_, **__: None
    owner._current_model_preview_render_settings = ModelPreviewRenderSettings
    owner._archive_d3d11_enabled_prefab_component_paths = lambda _: ()
    owner._native_preview_package_cache_mode = lambda: "off"
    owner._native_preview_package_cache_budget = lambda: (0, 0)
    owner._archive_model_renderer_backend = lambda: "none"
    owner._archive_preview_support_texture_slots = lambda _: ()
    owner._native_preview_core_cache_root = lambda: tmp_path / "native"
    owner._native_preview_package_cache_root = lambda: tmp_path / "packages"
    owner.archive_package_root_edit = SimpleNamespace(text=lambda: "")
    owner.archive_sidecar_generation = 0
    for name in ("archive_entries_by_normalized_path", "archive_entries_by_basename",
                 "archive_sidecar_entries_by_texture_path", "archive_sidecar_entries_by_texture_basename"):
        setattr(owner, name, {})
    for name in ("_handle_archive_preview_ready", "_handle_archive_preview_error", "_cleanup_archive_preview_refs"):
        setattr(owner, name, lambda *args: None)
    workers.ArchivePreviewWorkerMixin._start_archive_preview_worker(owner, 1, None, ())
    assert isinstance(owner.archive_preview_worker, ArchivePreviewWorker)
    assert owner.archive_preview_worker.prefer_gpu_texture is True
    owner.archive_preview_worker.deleteLater()
    owner.close()


def test_repeated_prepare_and_process_starts_do_not_accumulate_destroyed_connections(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, SIGNAL

    host = module.GpuTexturePreview()
    destroyed_sig = SIGNAL("destroyed()")
    initial_receivers = host.receivers(destroyed_sig)
    stopped = []
    monkeypatch.setattr(module, "stop_qprocess_async", stopped.append)

    class _FakeProcess:
        def __init__(self, *_args):
            self.readyReadStandardOutput = SimpleNamespace(connect=lambda *_: None)
            self.readyReadStandardError = SimpleNamespace(connect=lambda *_: None)
            self.finished = SimpleNamespace(connect=lambda *_: None)
            self.errorOccurred = SimpleNamespace(connect=lambda *_: None)

        def setProgram(self, *_args): pass
        def setArguments(self, *_args): pass
        def start(self): pass

    monkeypatch.setattr(module, "QProcess", _FakeProcess)
    monkeypatch.setattr(module, "register_owned_qprocess_for_exit", lambda *_: None)
    monkeypatch.setattr(QThreadPool, "globalInstance", lambda: SimpleNamespace(start=lambda *_: None))

    for i in range(5):
        host._path = str(tmp_path / f"t{i}.dds")
        host._prepare()
        host._start_process("fake.exe")

    assert host.receivers(destroyed_sig) == initial_receivers
    active_task = host._task
    active_process = host._process
    assert active_task is not None and active_process is not None
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert active_task.stop.is_set()
    assert active_process in stopped
