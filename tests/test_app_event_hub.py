"""The application's Python event filters see only the event types they act on.

Qt asks every application event filter about every event. The review found
Python filters (window interaction, layout persistence, display scaling,
localization, combo popups, the wheel guard, the New Item dialogs, the
automation placement) on the UI thread's stack throughout 0.3 to 1.8 s
stalls of building a Mesh Editor document, Create New Item, Model Library,
Drafts & Mods and the Textures workspace. One hub now takes every event and
calls each filter only for the types it registered.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QVBoxLayout, QWidget  # noqa: E402

from cdmw.ui.app_event_hub import (  # noqa: E402
    app_event_hub,
    install_app_event_filter,
    remove_app_event_filter,
)


def _app():
    return QApplication.instance() or QApplication([])


class _Recorder(QObject):
    def __init__(self, name, log, consume=False):
        super().__init__()
        self.name = name
        self.log = log
        self.consume = consume

    def eventFilter(self, watched, event):  # noqa: N802
        self.log.append((self.name, event.type()))
        return self.consume


def _send_user_event(target):
    QApplication.sendEvent(target, QEvent(QEvent.Type.User))


def test_filters_are_asked_newest_first_and_only_for_their_types():
    app = _app()
    log = []
    first = _Recorder("first", log)
    second = _Recorder("second", log)
    other = _Recorder("other", log)
    target = QObject()
    try:
        install_app_event_filter(app, first, (QEvent.Type.User,))
        install_app_event_filter(app, second, (QEvent.Type.User,))
        install_app_event_filter(app, other, (QEvent.Type.Wheel,))
        _send_user_event(target)
        assert [name for name, _ in log] == ["second", "first"]
        log.clear()
        install_app_event_filter(app, first, (QEvent.Type.User,))  # again: to the front
        _send_user_event(target)
        assert [name for name, _ in log] == ["first", "second"]
        log.clear()
        first.consume = True
        _send_user_event(target)
        assert [name for name, _ in log] == ["first"], "a filter that returns True ends the event"
        log.clear()
        remove_app_event_filter(app, first)
        _send_user_event(target)
        assert [name for name, _ in log] == ["second"]
    finally:
        for item in (first, second, other):
            remove_app_event_filter(app, item)


def test_a_destroyed_filter_is_dropped():
    app = _app()
    log = []
    holder = QObject()
    doomed = _Recorder("doomed", log)
    doomed.setParent(holder)
    install_app_event_filter(app, doomed, (QEvent.Type.User,))
    holder.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _send_user_event(QObject())
    assert log == []
    assert all(item is not doomed for item in app_event_hub(app).filters())


def test_an_exception_in_one_filter_does_not_stop_the_others(monkeypatch):
    app = _app()
    log = []
    reported = []
    monkeypatch.setattr("sys.excepthook", lambda *exc: reported.append(exc[0]))

    class _Broken(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            raise ValueError("broken")

    quiet = _Recorder("quiet", log)
    broken = _Broken()
    try:
        install_app_event_filter(app, quiet, (QEvent.Type.User,))
        install_app_event_filter(app, broken, (QEvent.Type.User,))
        _send_user_event(QObject())
        assert reported == [ValueError]
        assert [name for name, _ in log] == ["quiet"]
    finally:
        remove_app_event_filter(app, quiet)
        remove_app_event_filter(app, broken)


def _build_and_show_tree():
    root = QWidget()
    layout = QVBoxLayout(root)
    for index in range(30):
        layout.addWidget(QLabel(f"row {index}"))
    layout.addWidget(QComboBox())
    root.show()
    QApplication.processEvents()
    root.hide()
    root.deleteLater()
    QApplication.processEvents()


@pytest.mark.parametrize(
    ("module", "class_name", "install"),
    [
        ("cdmw.ui.combo_popup_limiter", "ComboPopupLimiter", "ensure_app_combo_popup_limiter"),
        ("cdmw.ui.display_scaling", "DisplayScalingPolicy", "ensure_app_display_scaling"),
        ("cdmw.ui.wheel_guard", "NonIntrusiveWheelGuard", "ensure_app_wheel_guard"),
        ("cdmw.ui.window_interaction", "WindowInteractionTracker", "ensure_window_interaction_tracker"),
    ],
)
def test_app_filters_see_only_the_events_they_act_on(monkeypatch, module, class_name, install):
    import importlib

    app = _app()
    loaded = importlib.import_module(module)
    getattr(loaded, install)(app)
    cls = getattr(loaded, class_name)
    seen = []
    original = cls.eventFilter

    def recording(self, watched, event):
        seen.append(event.type())
        return original(self, watched, event)

    monkeypatch.setattr(cls, "eventFilter", recording)
    _build_and_show_tree()
    allowed = {
        "ComboPopupLimiter": {QEvent.Type.Show},
        "NonIntrusiveWheelGuard": {QEvent.Type.Wheel},
        "WindowInteractionTracker": {QEvent.Type.Hide, QEvent.Type.WinIdChange},
        "DisplayScalingPolicy": set(loaded.__dict__.get("DISPLAY_SCALING_EVENT_TYPES", ())),
    }[class_name]
    unexpected = {event_type for event_type in seen if event_type not in allowed}
    assert not unexpected, f"{class_name} was asked about {sorted(str(t) for t in unexpected)[:5]}"
