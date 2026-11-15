"""The test process collects reference cycles only on the main thread (tests/gui_thread_gc.py)."""

from __future__ import annotations

import gc
import os
import subprocess
import sys
import threading
from pathlib import Path


from tests.gui_thread_gc import collect_after_test

REPOSITORY = Path(__file__).resolve().parents[1]

# Run as a script: Python widgets whose event override allocates, windows that
# only a reference cycle keeps, a worker thread making garbage, thresholds that
# make an automatic collection near certain, then app-wide restyles. With
# "automatic" (no policy) this died with an access violation inside
# QApplication.setStyleSheet; with "policy" it must finish.
RESTYLE_SCENARIO = r"""
import gc, os, sys, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

if sys.argv[1] == "policy":
    from tests.gui_thread_gc import install
    install()
gc.set_threshold(1, 1, 1)
app = QApplication.instance() or QApplication([])

class Allocating(QWidget):
    def event(self, event):
        if event.type() == QEvent.Type.StyleChange:
            garbage = [[] for _ in range(64)]
            for item in garbage:
                item.append(garbage)
        return super().event(event)

class Leftover(QWidget):
    def __init__(self):
        super().__init__()
        self.cycle = self
        layout = QVBoxLayout(self)
        for index in range(100):
            layout.addWidget(QLabel(f"row {index}", self))

stop = threading.Event()
def churn():
    # Small and yielding, so it competes for the GIL the way a worker does.
    for _ in range(20000):
        if stop.is_set():
            return
        garbage = [[] for _ in range(16)]
        for item in garbage:
            item.append(garbage)
        time.sleep(0.0005)

keep = [Allocating() for _ in range(20)]
for widget in keep:
    widget.show()
worker = threading.Thread(target=churn, daemon=True)
worker.start()
for round_index in range(12):
    for _ in range(4):
        leftover = Leftover()
        leftover.show()
        app.processEvents()
        leftover.close()
    del leftover
    app.setStyleSheet(f"QLabel {{ padding: {round_index % 3}px; }}")
stop.set()
worker.join()
print("restyled", len(app.allWidgets()))
sys.stdout.flush()
os._exit(0)
"""


def run_restyle_scenario(mode: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", RESTYLE_SCENARIO, mode],
        cwd=REPOSITORY,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        capture_output=True,
        timeout=120,
    )


def test_automatic_collection_is_off_while_tests_run():
    assert not gc.isenabled(), "A collection could start inside a Qt call or on a worker thread"


def test_restyling_with_collectable_windows_survives_under_the_policy():
    result = run_restyle_scenario("policy")
    assert result.returncode == 0, f"exit {result.returncode:#x}\n{result.stdout}\n{result.stderr}"
    assert "restyled" in result.stdout


def test_teardown_collection_frees_a_finished_tests_cycles_on_the_main_thread():
    from PySide6.QtCore import QObject, Qt

    destroyed_on = []
    doomed = QObject()
    doomed.cycle = doomed
    doomed.destroyed.connect(lambda *_: destroyed_on.append(threading.get_ident()), Qt.DirectConnection)
    del doomed
    collect_after_test()
    assert destroyed_on == [threading.main_thread().ident]


def test_collection_refuses_to_run_off_the_main_thread():
    errors = []

    def worker():
        try:
            collect_after_test()
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert errors and "main thread" in errors[0]
