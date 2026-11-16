"""A lazy tool's widget is built, attached and published on separate event-loop turns.

The review measured 367 ms (545 ms cold) on the UI thread opening Model
Library, in one load step that ran the tool's constructor and then moved the
finished widget into its container, which restyles the whole subtree. The
move now has its own step.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab  # noqa: E402


def _factory():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    for index in range(10):
        layout.addWidget(QLabel(f"row {index}"))
    return widget


def _app():
    return QApplication.instance() or QApplication([])


def test_construction_and_attachment_are_separate_steps():
    _app()
    container = LazyToolTab(_factory)
    created = []
    container.when_created(created.append)
    container._construct_requested_widget()
    pending = container._pending_widget
    assert pending is not None
    assert pending.parentWidget() is None, "the constructor's step must not also move the widget"
    assert container._next_load_step == container._attach_requested_widget
    container._run_load_step()
    assert pending.parentWidget() is container
    assert not created
    container._run_load_step()
    assert created == [pending]
    assert container.widget_if_created() is pending
    container.deleteLater()


def test_shutdown_before_attachment_still_owns_the_widget():
    _app()
    container = LazyToolTab(_factory)
    container._construct_requested_widget()
    pending = container._pending_widget
    container.request_shutdown()
    assert container.widget_if_created() is pending
    assert pending.parentWidget() is container
    container.deleteLater()


def test_ensure_widget_still_builds_at_once():
    _app()
    container = LazyToolTab(_factory)
    widget = container.ensure_widget()
    assert widget.parentWidget() is container
    assert container.widget_if_created() is widget
    container.deleteLater()
