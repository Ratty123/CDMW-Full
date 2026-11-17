"""The New painting dialog's 3D view: built off the UI thread, and never left waiting.

The viewport frame is Create New Item's own `ItemPreviewFrame` with a stand-in host (no
native viewport offscreen) and a stand-in package builder; the dialog's waiting state is
what is checked, after the lessons of dcc749312 and ed3a8f58f.
"""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from tests.test_new_item_painting_dialog import LARGE, Controller  # noqa: E402

_APPLICATION = None


def _app():
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _fake_host_class(loads):
    class Signals(QObject):
        state_changed = Signal(str, str)
        capture_completed = Signal(object)

    class FakeController:
        def __init__(self):
            self._signals = Signals()
            self.state_changed = self._signals.state_changed
            self.capture_completed = self._signals.capture_completed

        def shutdown(self):
            loads.append("shutdown")

    class FakeHost(QWidget):
        alignment_drag_started = Signal()
        alignment_drag_changed = Signal(float, float, float)
        alignment_drag_finished = Signal(float, float, float)
        alignment_rotation_changed = Signal(float, float, float)
        alignment_rotation_finished = Signal(float, float, float)
        alignment_scale_changed = Signal(float, float, float)
        alignment_scale_finished = Signal(float, float, float)

        def __init__(self, parent):
            super().__init__(parent)
            self.controller = FakeController()

        def load_package(self, path, **_kwargs):
            loads.append(path)
            return True

        def __getattr__(self, name):
            if name.startswith("set_") or name in {"reset_view", "clear_local_preview_setting", "show_preparation_status"}:
                return lambda *args, **kwargs: True
            raise AttributeError(name)

    return FakeHost


class ViewportController(Controller):
    def __init__(self, *, fail=False):
        super().__init__()
        self.sources = []
        self.built_on = []
        self.fail = fail

    def painting_preview_source(self, frame, picture, fit):
        self.sources.append((frame.mesh, picture, fit))

        def build(stop_event):
            from cdmw.services.new_item_painting_preview import PaintingPreviewError

            self.built_on.append(threading.get_ident())
            if self.fail:
                raise PaintingPreviewError("The frame could not be read for the 3D view.")
            return SimpleNamespace(meshes=[], picture=picture)

        return build


def _until(condition, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _app().processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _packages(loads):
    return [value for value in loads if value != "shutdown"]


@pytest.fixture
def viewport_dialog(tmp_path, monkeypatch):
    _app()
    from cdmw.ui.new_item import item_preview
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.ui.new_item.painting_dialog import PaintingDialog

    def build_package(item, *, token, output_root, **_kwargs):
        output_root.mkdir(parents=True, exist_ok=True)
        package = output_root / f"package_{len(list(output_root.glob('package_*')))}"
        package.mkdir()
        return package

    monkeypatch.setattr(item_preview, "build_item_preview_package", build_package)
    loads, made, views = [], [], []

    def factory(parent):
        frame = ItemPreviewFrame(parent, output_root=tmp_path / "packages", host_factory=_fake_host_class(loads))
        made.append(frame)
        return frame

    def open_dialog(controller):
        view = PaintingDialog(controller, viewport_factory=factory)
        views.append(view)
        view.show()
        view.resize(1300, 850)
        return view

    yield SimpleNamespace(open=open_dialog, loads=loads, made=made)
    for view in views:
        if view.isVisible():
            view.done(0)
    for frame in made:
        frame.request_shutdown()
    _until(lambda: not any(tuple(frame.iter_shutdown_workers()) for frame in made))
    for view in views:
        view.deleteLater()


def test_the_3d_view_is_built_on_a_worker_only_when_its_tab_is_shown_and_ends_its_busy_state(viewport_dialog, tmp_path):
    """The 3D view shows the frame's mesh with the picture; its package is built off the
    UI thread, and "Preparing the 3D view" ends when the viewport says it is ready."""
    controller = ViewportController()
    view = viewport_dialog.open(controller)
    view.frame.set_current_frame_row(1)
    view._paintings[0]["picture"] = str(tmp_path / "mine.png")
    view._show_painting()
    _app().processEvents()
    assert controller.sources == [] and viewport_dialog.made == []  # the front view's tab is shown
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert controller.sources[-1] == (LARGE, str(tmp_path / "mine.png"), "fill")
    assert view.viewport_busy_now()
    assert _until(lambda: _packages(viewport_dialog.loads))
    assert controller.built_on and threading.get_ident() not in controller.built_on
    frame = viewport_dialog.made[0]
    assert frame.gizmo_visible.isHidden()
    frame.host.controller.state_changed.emit("ready", "")
    assert not view.viewport_busy_now()
    assert view.reset_view_button.isEnabled()
    # A change of fit builds the view again and waits for it.
    view.fit.setCurrentIndex(view.fit.findData("whole"))
    assert controller.sources[-1][2] == "whole" and view.viewport_busy_now()
    assert _until(lambda: len(_packages(viewport_dialog.loads)) == 2)
    frame.host.controller.state_changed.emit("ready", "")
    assert not view.viewport_busy_now()


def test_a_3d_view_that_already_shows_the_package_is_not_left_busy(viewport_dialog):
    """As Body & Face Finder's wait (ed3a8f58f): asking again for what the viewport shows
    loads nothing and says nothing, so the dialog must not wait for a ready."""
    view = viewport_dialog.open(ViewportController())
    view.frame.set_current_frame_row(0)
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert _until(lambda: _packages(viewport_dialog.loads))
    viewport_dialog.made[0].host.controller.state_changed.emit("ready", "")
    assert not view.viewport_busy_now()
    assert "game's own picture" in view.viewport_status.text()
    view.preview_tabs.setCurrentWidget(view.preview)
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert len(_packages(viewport_dialog.loads)) == 1
    assert not view.viewport_busy_now()


def test_a_failed_3d_view_says_why_and_stops_waiting(viewport_dialog):
    view = viewport_dialog.open(ViewportController(fail=True))
    view.frame.set_current_frame_row(0)
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert _until(lambda: not view.viewport_busy_now())
    assert "could not be read for the 3D view" in view.viewport_status.text()
    assert view.viewport_status.property("severity") == "error"


def test_a_missing_viewport_says_so_instead_of_waiting(tmp_path, monkeypatch):
    _app()
    from cdmw.ui.new_item import item_preview
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.ui.new_item.painting_dialog import PaintingDialog

    def build_package(item, *, token, output_root, **_kwargs):
        (output_root / "package_0").mkdir(parents=True, exist_ok=True)
        return output_root / "package_0"

    monkeypatch.setattr(item_preview, "build_item_preview_package", build_package)

    def no_host(_parent):
        raise RuntimeError("no GPU")

    made = []

    def factory(parent):
        made.append(ItemPreviewFrame(parent, output_root=tmp_path / "packages", host_factory=no_host))
        return made[-1]

    view = PaintingDialog(ViewportController(), viewport_factory=factory)
    view.show()
    view.frame.set_current_frame_row(0)
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert _until(lambda: not view.viewport_busy_now())
    assert "not available here" in view.viewport_status.text()
    view.done(0)
    _until(lambda: not any(tuple(frame.iter_shutdown_workers()) for frame in made))
    view.deleteLater()


def test_close_stops_the_3d_view_and_opening_again_starts_a_new_one(viewport_dialog):
    view = viewport_dialog.open(ViewportController())
    view.frame.set_current_frame_row(0)
    view.preview_tabs.setCurrentWidget(view.viewport_page)
    assert _until(lambda: _packages(viewport_dialog.loads))
    first = viewport_dialog.made[0]
    view.done(0)
    assert "shutdown" in viewport_dialog.loads
    assert view._viewport is None and first in view._retired_viewports
    assert _until(lambda: not tuple(view.iter_shutdown_workers()))
    view.open()
    assert _until(lambda: len(viewport_dialog.made) == 2)
    second = viewport_dialog.made[1]
    assert _until(lambda: len(_packages(viewport_dialog.loads)) == 2)
    second.host.controller.state_changed.emit("ready", "")
    assert not view.viewport_busy_now()
