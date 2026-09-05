"""Imported-model source retirement and nonblocking cleanup regressions."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.ui.new_item.controller import NewItemStudioController  # noqa: E402
from cdmw.ui.new_item.model_import import ModelImportSource  # noqa: E402


def test_discard_retires_the_source_without_waiting_for_preview_users_or_cleanup(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    extract_root = tmp_path / "retired-model-source"
    extract_root.mkdir()
    (extract_root / "texture.bin").write_bytes(b"texture")
    source = ModelImportSource(
        chosen_path=tmp_path / "model.zip",
        model_path=extract_root / "model.gltf",
        scene=None,
        preview_model=None,
        bounds=None,
        extract_root=extract_root,
        owns_extract_root=True,
    )
    usage = source.acquire_usage()
    assert usage is not None
    cleanup_started = threading.Event()
    cleanup_release = threading.Event()
    cleanup_finished = threading.Event()
    original_cleanup = source.cleanup

    def slow_cleanup() -> None:
        cleanup_started.set()
        cleanup_release.wait(1.0)
        original_cleanup()
        cleanup_finished.set()

    source.cleanup = slow_cleanup
    controller.model_import = source
    changes = []
    controller.model_import_changed.connect(lambda value: changes.append((value, extract_root.exists())))
    try:
        started = time.monotonic()
        controller.discard_model()
        assert time.monotonic() - started < 0.08
        assert changes == [(None, True)]
        assert not cleanup_started.is_set()
        assert controller.iter_shutdown_workers()

        usage.release()
        usage = None
        deadline = time.monotonic() + 2.0
        while not cleanup_started.is_set() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        assert cleanup_started.is_set()
        assert extract_root.is_dir()

        cleanup_release.set()
        while controller.iter_shutdown_workers() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        assert cleanup_finished.is_set()
        assert not extract_root.exists()
        assert controller.iter_shutdown_workers() == ()
    finally:
        cleanup_release.set()
        if usage is not None:
            usage.release()
        deadline = time.monotonic() + 2.0
        while controller.iter_shutdown_workers() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        controller.request_shutdown()


def test_preview_retirement_and_close_keep_file_cleanup_off_the_ui_thread(tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import QTimer
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.workers import new_item_cleanup_worker

    app = QApplication.instance() or QApplication([])
    roots = [tmp_path / name for name in ("geometry", "direct", "full")]
    for root in roots:
        root.mkdir()
        (root / "texture.dds").write_bytes(b"owned preview fixture")
    frame = ItemPreviewFrame(output_root=tmp_path)
    stopped = []
    frame.host = SimpleNamespace(
        controller=SimpleNamespace(shutdown=lambda: stopped.append(True)),
        set_display_mode=lambda *_: None, set_alignment_state=lambda **_: None,
        set_icon_capture_mode=lambda *_: None,
    )
    frame._package_dir = roots[2]
    frame._loaded_stage = "materials"
    frame._retire_after_ready = roots[:2]
    ui_thread = threading.get_ident()
    started = threading.Event()
    release = threading.Event()
    deleted = []
    original = new_item_cleanup_worker.shutil.rmtree

    def slow_remove(path, **kwargs):
        assert threading.get_ident() != ui_thread, "package deletion blocks the UI thread"
        started.set()
        assert release.wait(3), "the UI did not return while cleanup was blocked"
        original(path, **kwargs)
        deleted.append(path)

    monkeypatch.setattr(new_item_cleanup_worker.shutil, "rmtree", slow_remove)
    try:
        frame._host_state("ready", "")
        assert frame.is_ready
        deadline = time.monotonic() + 2
        while not started.is_set() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        assert started.is_set()
        assert len(frame.iter_shutdown_workers()) == 1, "cleanup concurrency is bounded"
        assert all(root.exists() for root in roots)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        assert ticks, "navigation events must run while deletion waits"
        frame.request_shutdown()
        assert stopped and frame._package_dir is None
        assert len(frame.iter_shutdown_workers()) == 1
        release.set()
        while frame.iter_shutdown_workers() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        assert frame.iter_shutdown_workers() == ()
        assert deleted == roots
        assert tmp_path.is_dir()
    finally:
        release.set()
        frame.request_shutdown()
        deadline = time.monotonic() + 3
        while frame.iter_shutdown_workers() and time.monotonic() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


@pytest.mark.parametrize("target", ["root", "outside"])
def test_preview_cleanup_cannot_remove_its_root_or_external_files(tmp_path, target) -> None:
    from cdmw.workers.new_item_cleanup_worker import PreviewPackageCleanup

    root = tmp_path / "previews"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    path = root if target == "root" else root / ".." / "outside"
    with pytest.raises(ValueError, match="inside its output root"):
        PreviewPackageCleanup(path, root).cleanup()
    assert root.is_dir() and outside.is_dir()
