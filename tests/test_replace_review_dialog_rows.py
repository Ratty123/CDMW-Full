"""Texture Replacer Review loads the row chosen while an earlier compare was still running."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.ui.replace_assistant import review_dialog as module


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def compares(monkeypatch):
    """A compare worker that runs until released, recording every item it was asked for."""

    started, release = [], threading.Event()

    class BlockingCompare(QObject):
        completed = Signal(int, object)
        error = Signal(int, str)
        finished = Signal()

        def __init__(self, request_id, item):
            super().__init__()
            self.request_id, self.item = request_id, item
            started.append(item)

        def stop(self):
            pass  # The real worker only sets a flag that its next step reads.

        def run(self):
            release.wait(5)
            self.error.emit(self.request_id, f"compared {self.item.relative_path}")
            self.finished.emit()

    monkeypatch.setattr(module, "ReplaceAssistantReviewCompareWorker", BlockingCompare)
    return SimpleNamespace(started=started, release=release)


def _items(count):
    return [SimpleNamespace(relative_path=PurePosixPath(f"texture/{index}.dds"),
                            source_path=Path(f"{index}.png"), output_dds_path=Path(f"{index}.dds"))
            for index in range(count)]


def _wait(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    return predicate()


def test_row_chosen_during_a_compare_is_loaded_when_the_compare_ends(app, compares):
    items = _items(3)
    dialog = module.ReplaceAssistantReviewDialog(items)
    try:
        dialog.item_list.setCurrentRow(0)
        assert compares.started == [items[0]]
        dialog.item_list.setCurrentRow(1)
        assert compares.started == [items[0]], "A second compare must wait for the first"
        compares.release.set()
        assert _wait(app, lambda: len(compares.started) == 2), "The chosen row was never loaded"
        assert compares.started[1] is items[1]
        assert _wait(app, lambda: dialog.source_meta.text() == "compared texture/1.dds")
    finally:
        compares.release.set()
        dialog.close()
        _wait(app, lambda: dialog.compare_thread is None)
        dialog.deleteLater()
        app.processEvents()


def test_closing_during_a_compare_starts_no_further_compare(app, compares):
    items = _items(2)
    dialog = module.ReplaceAssistantReviewDialog(items)
    dialog.item_list.setCurrentRow(0)
    dialog.item_list.setCurrentRow(1)
    thread = dialog.compare_thread
    dialog.close()
    compares.release.set()
    assert _wait(app, lambda: thread.isFinished())
    for _ in range(20):
        app.processEvents()
    assert compares.started == [items[0]]
    dialog.deleteLater()
    app.processEvents()


def test_dialog_keeps_qobject_thread(app):
    dialog = module.ReplaceAssistantReviewDialog(_items(1))
    try:
        assert dialog.thread() is app.thread()
    finally:
        dialog.deleteLater()
        app.processEvents()
