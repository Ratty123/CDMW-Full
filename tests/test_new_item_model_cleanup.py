"""Imported-model source retirement and nonblocking cleanup regressions."""

from __future__ import annotations

import os
import threading
import time

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
