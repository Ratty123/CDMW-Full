"""A lazy tool's widget is built, attached and published on separate event-loop turns.

The review measured 367 ms (545 ms cold) on the UI thread opening Model
Library, in one load step that ran the tool's constructor and then moved the
finished widget into its container, which restyles the whole subtree. The
move now has its own step.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
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


class _StepBuiltTool(QWidget):
    """Builds its rows in steps, as Texture Editor does (``build_in_steps``)."""

    def __init__(self, steps: int = 3, rows: int = 40) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._left = steps
        self._rows = rows
        self.parents_while_building: list[object] = []

    @property
    def construction_complete(self) -> bool:
        return self._left == 0

    def continue_construction(self) -> bool:
        if self._left == 0:
            return False
        self.parents_while_building.append(self.parentWidget())
        for index in range(self._rows):
            self._layout.addWidget(QLabel(f"row {index}"))
        self._left -= 1
        return True


class _StyleChanges(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.StyleChange:
            self.count += 1
        return False


def test_a_tool_built_in_steps_is_attached_before_its_steps_restyle_nothing_later():
    """Textures held the UI thread 106 ms (158 ms warm) in the attach step in the
    2026-11-17 review: moving a finished widget into the container restyles every
    widget in it. A step-built tool moves in while it is still nearly empty."""

    app = _app()
    previous_sheet = app.styleSheet()
    app.setStyleSheet("QLabel { padding: 1px; }")  # the app always runs with a style sheet
    tool = _StepBuiltTool()
    container = LazyToolTab(lambda: tool)
    counter = _StyleChanges()
    try:
        container._construct_requested_widget()
        while container._next_load_step == container._continue_requested_construction:
            container._run_load_step()
        assert tool.parents_while_building == [container] * 3, "the steps built a widget outside its container"
        assert container._next_load_step == container._attach_requested_widget
        app.installEventFilter(counter)
        container._run_load_step()  # the attach step
        app.removeEventFilter(counter)
        assert counter.count == 0, f"the attach step restyled {counter.count} widgets"
        container._run_load_step()
        assert container.widget_if_created() is tool
    finally:
        app.removeEventFilter(counter)
        app.setStyleSheet(previous_sheet)
        container.deleteLater()
