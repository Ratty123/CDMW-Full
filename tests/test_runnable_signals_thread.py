"""A pool task's signal object is deleted on the GUI thread, never by the pool thread.

QThreadPool deletes a finished QRunnable on the pool thread. When its owner had
already dropped its Python reference (a newer scan replacing the task, a cancel,
the result slot clearing it), the task's signal object, a QObject that lives on
the GUI thread, went with it on the pool thread, which Qt does not support.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _run_dropped(app, make_task, count=4):
    """Start tasks, drop every Python reference at once, and record where each signal object died."""

    main = threading.get_ident()
    destroyed_on, delivered = [], []
    for index in range(count):
        task = make_task(index)
        task.signals.destroyed.connect(lambda *_: destroyed_on.append(threading.get_ident()), Qt.DirectConnection)
        task.signals.completed.connect(lambda *args: delivered.append(args), Qt.QueuedConnection)
        QThreadPool.globalInstance().start(task)
        task = None
    assert QThreadPool.globalInstance().waitForDone(10000)
    deadline = time.monotonic() + 5
    while len(destroyed_on) < count and time.monotonic() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.005)
    return main, destroyed_on, delivered


def test_fingerprint_task_signals_die_on_the_gui_thread_after_delivery(app, monkeypatch):
    from cdmw.workers import game_executable_fingerprint as module

    def check(root, records, *, stop_event):
        time.sleep(0.05)
        return records, (), False

    monkeypatch.setattr(module, "check_game_executable_fingerprints", check)
    main, destroyed_on, delivered = _run_dropped(
        app, lambda index: module.GameExecutableFingerprintTask(index, Path("."), {"n": index}, threading.Event()))
    assert destroyed_on == [main] * 4
    assert sorted(generation for generation, _result in delivered) == [0, 1, 2, 3]


def test_cancelled_fingerprint_task_signals_still_die_on_the_gui_thread(app, monkeypatch):
    from cdmw.models import RunCancelled
    from cdmw.workers import game_executable_fingerprint as module

    def cancelled(root, records, *, stop_event):
        time.sleep(0.05)
        raise RunCancelled("stopped")

    monkeypatch.setattr(module, "check_game_executable_fingerprints", cancelled)
    stop = threading.Event()
    stop.set()
    main, destroyed_on, delivered = _run_dropped(
        app, lambda index: module.GameExecutableFingerprintTask(index, Path("."), {}, stop))
    assert destroyed_on == [main] * 4
    assert delivered == []


def test_preview_core_prewarm_signals_die_on_the_gui_thread_after_delivery(app, monkeypatch, tmp_path):
    from cdmw.services import preview_rendering_service
    from cdmw.ui.archive_browser.preview_core_prewarm import _ArchivePreviewCorePrewarmTask

    def job(entry, **_kwargs):
        time.sleep(0.05)
        return SimpleNamespace(status="ok", fallback_reason="", elapsed_ms=1.0)

    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", job)
    main, destroyed_on, delivered = _run_dropped(
        app, lambda index: _ArchivePreviewCorePrewarmTask(
            SimpleNamespace(path=f"model/{index}.pac"), cache_root=tmp_path, package_root=None,
            render_settings=None, stop_event=threading.Event()))
    assert destroyed_on == [main] * 4
    assert [result["status"] for (result,) in delivered] == ["ok"] * 4


# The same fault in cdmw/ui/preview, which is the main thread's. The change for
# each task: create the signals with `application_owned(<Signals class>)` and end
# `run()` with `release(self.signals)` in a `finally` (cdmw/workers/runnable_signals.py).
# Remove the marker with the change; strict makes the fixed code fail until then.
_PREVIEW_HANDOVER = "cdmw/ui/preview is the main thread's: apply runnable_signals there (crash thread REPORT)"


def test_texture_view_prepare_signals_die_on_the_gui_thread_after_delivery(app, tmp_path):
    from PySide6.QtGui import QImage
    from cdmw.ui.preview.texture_view import _PrepareTexture

    path = tmp_path / "texture.png"
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(path))
    main, destroyed_on, delivered = _run_dropped(
        app, lambda index: _PrepareTexture(index, path, fallback=True))
    assert sorted(generation for generation, _result in delivered) == [0, 1, 2, 3]
    assert destroyed_on == [main] * 4


def test_dotnet_preview_prewarm_signals_die_on_the_gui_thread_after_delivery(app, monkeypatch, tmp_path):
    from cdmw.ui.preview import dotnet_host_prewarm as module

    def build(cache_root):
        time.sleep(0.05)
        raise RuntimeError("no package in this test")

    monkeypatch.setattr(module, "build_rust_preview_prewarm_package", build)
    main, destroyed_on, delivered = _run_dropped(app, lambda index: module.DotNetPreviewPrewarmTask(tmp_path))
    assert [result["error"] for (result,) in delivered] == ["no package in this test"] * 4
    assert destroyed_on == [main] * 4
