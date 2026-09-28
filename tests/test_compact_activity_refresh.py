"""Activity bursts must not rebuild a full log in every status callback."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell.compact.activity import ActivityHistory
from cdmw.ui.shell.compact.drawer import CompactActivityDrawer


@pytest.fixture
def activity(monkeypatch):
    app = QApplication.instance() or QApplication([])
    history = ActivityHistory(capacity=20)
    calls = []
    original = history.formatted_text

    def formatted():
        calls.append(True)
        return original()

    monkeypatch.setattr(history, "formatted_text", formatted)
    drawer = CompactActivityDrawer(history)
    try:
        yield app, history, drawer, calls
    finally:
        drawer.close()
        drawer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def test_hidden_activity_retains_history_without_rendering_until_shown(activity):
    app, history, drawer, calls = activity
    for number in range(100):
        history.append(f"Message {number}")
    QTest.qWait(60)
    assert not calls and not drawer._refresh_timer.isActive()
    assert len(history.events) == 20
    drawer.show()
    app.processEvents()
    assert len(calls) == 1
    assert "Message 80" in drawer.activity_view.toPlainText()
    assert drawer.activity_view.toPlainText().endswith("Message 99")
    drawer.hide()
    drawer.show()
    app.processEvents()
    assert len(calls) == 1, "Reopening unchanged history should keep the existing document."


def test_visible_status_burst_batches_rendering_but_copy_is_always_current(activity):
    app, history, drawer, calls = activity
    drawer.show()
    app.processEvents()
    calls.clear()
    for number in range(100):
        history.append(f"Burst {number}")
    assert not calls
    assert drawer.copy_button.isEnabled()
    drawer._copy_current_view()
    assert app.clipboard().text().endswith("Burst 99")
    assert len(calls) == 1  # Explicit Copy reads the current authoritative history.
    QTest.qWait(70)
    assert len(calls) == 2
    assert drawer.activity_view.toPlainText() == app.clipboard().text()
    assert not drawer._refresh_timer.isActive()
    drawer._clear_current_view()
    assert history.events == () and drawer.activity_view.toPlainText() == ""
    assert not drawer.copy_button.isEnabled() and not drawer.clear_button.isEnabled()


def test_other_log_page_and_hiding_stop_pending_history_work(activity):
    app, history, drawer, calls = activity
    drawer.show()
    app.processEvents()
    calls.clear()
    history.append("Pending before changing pages")
    drawer.tabs.setCurrentIndex(1)
    for _ in range(100):
        history.append("Coalesced status")
    QTest.qWait(60)
    assert not calls and not drawer._refresh_timer.isActive()
    assert len(history.events) == 2
    drawer.tabs.setCurrentIndex(0)
    assert len(calls) == 1
    assert drawer.activity_view.toPlainText().endswith("Coalesced status")
    history.append("Pending before hiding")
    drawer.hide()
    QTest.qWait(60)
    assert len(calls) == 1 and not drawer._refresh_timer.isActive()
    history.clear()
    assert drawer.activity_view.toPlainText() == ""
    history.append("New activity while hidden")
    drawer.show()
    app.processEvents()
    assert len(calls) == 2
    assert drawer.activity_view.toPlainText().endswith("New activity while hidden")
