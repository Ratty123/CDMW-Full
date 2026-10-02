"""Keep cyclic Qt cleanup on the GUI thread under background allocation pressure."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("automatic_gc", [True, False])
def test_shell_collects_gui_cycles_on_gui_thread_and_restores_gc(tmp_path, automatic_gc):
    # A regression can crash in native Python/Qt code, so isolate the real handoff.
    script = textwrap.dedent("""
        import gc
        from pathlib import Path
        import sys
        import threading
        import time

        from PySide6.QtCore import QObject, QThread, Qt
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.shell.app_startup import prepare_shell_application
        from cdmw.workers.utility_workers import UtilityWorker

        automatic_gc = sys.argv[2] == 'True'
        (gc.enable if automatic_gc else gc.disable)()
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        prepare_shell_application(app, settings_file_path=Path(sys.argv[1]))
        # Repeated preparation must not install competing collectors or lose the
        # original enabled state that needs restoring after QApplication teardown.
        prepare_shell_application(app, settings_file_path=Path(sys.argv[1]))
        gui_thread = threading.get_ident()
        collections, destroyed, ran, errors = [], [], [], []

        def observed(phase, info):
            if phase == 'start':
                collections.append(threading.get_ident())

        def destroyed_here():
            destroyed.append(threading.get_ident())

        def allocate(log):
            ran.append(threading.get_ident())
            gc.set_threshold(32, 1, 1)
            for _ in range(1500):
                for _ in range(64):
                    cycle = []
                    cycle.append(cycle)
                time.sleep(.001)

        thread = QThread()
        worker = UtilityWorker(allocate)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.error.connect(errors.append)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        gc.set_threshold(1000000, 1, 1)
        gc.callbacks.append(observed)
        doomed = QObject()
        doomed.cycle = doomed
        doomed.destroyed.connect(destroyed_here, Qt.DirectConnection)
        del doomed
        thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and (thread.isRunning() or not destroyed):
            app.processEvents()
            time.sleep(.002)
        assert thread.wait(3000), 'allocation worker did not stop'
        app.processEvents()
        gc.callbacks.remove(observed)
        assert not errors, errors
        assert ran and ran[0] != gui_thread, ran
        assert destroyed == [gui_thread], (gui_thread, destroyed)
        assert collections and set(collections) == {gui_thread}, (gui_thread, ran, set(collections))
        assert not gc.isenabled(), 'automatic GC resumed while Qt was still alive'
        app.aboutToQuit.emit()
        assert not gc.isenabled(), 'GC resumed before Qt/worker teardown'
        app.shutdown()
        assert QApplication.instance() is None
        assert gc.isenabled() == automatic_gc, 'original GC state was not restored'
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script,
         str(tmp_path / "settings.ini"), str(automatic_gc)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("incremental, counts, thresholds, expected", [
    (False, (20, 20, 20), (0, 10, 10), []),
    (False, (19, 20, 20), (20, 10, 10), []),
    (False, (20, 1, 1), (20, 10, 10), [0]),
    (False, (20, 11, 1), (20, 10, 10), [1]),
    (False, (20, 11, 11), (20, 10, 10), [2]),
    (True, (20, 0, 0), (20, 10, 0), [1]),
    (True, (20, 11, 11), (20, 10, 10), [1]),
])
def test_collection_respects_pressure_and_runtime_generations(
    monkeypatch, incremental, counts, thresholds, expected,
):
    from cdmw.ui.shell import garbage_collection as module

    collector = SimpleNamespace(_collecting=False)
    collected = []

    def collect(generation):
        collected.append(generation)
        # A Qt finalizer can process nested events while collection is active.
        module.GuiGarbageCollector._collect(collector)

    monkeypatch.setattr(module, "_INCREMENTAL_GC", incremental)
    monkeypatch.setattr(module, "gc", SimpleNamespace(
        get_count=lambda: counts, get_threshold=lambda: thresholds, collect=collect,
    ))
    module.GuiGarbageCollector._collect(collector)
    assert collected == expected
    assert not collector._collecting
