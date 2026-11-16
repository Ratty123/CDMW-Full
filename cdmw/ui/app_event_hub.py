"""One application event filter that hands each event only to the filters that want it.

Qt calls every application event filter for every event of every object. A
Python filter costs a call into Python, a wrapper for the event and one for
the object, even when it looks only at a Show or a Wheel. With a dozen of
them, building a Mesh Editor document (about 5,000 events) or Create New
Item's Model panel (about 9,000) spent close to half its time in filters that
returned False at once; the review measured 0.5 to 1.8 s stalls on the UI
thread made of such construction.

The hub is installed once. Each filter registers with the event types it
acts on and is called, through its own ``eventFilter``, only for those. The
order is Qt's: the filter registered last is asked first, a filter that
returns True ends the event, registering again moves a filter to the front,
and a filter whose object is destroyed is dropped.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from shiboken6 import isValid

_HUB_ATTRIBUTE = "_cdmw_app_event_hub"


class AppEventHub(QObject):
    def __init__(self, application: QCoreApplication) -> None:
        super().__init__(application)
        #: newest first, as Qt asks application filters
        self._entries: list[tuple[QObject, frozenset]] = []
        self._by_type: dict[object, tuple[QObject, ...]] = {}

    def add(self, event_filter: QObject, event_types: Iterable[QEvent.Type]) -> None:
        types = frozenset(event_types)
        self._entries = [entry for entry in self._entries if entry[0] is not event_filter]
        self._entries.insert(0, (event_filter, types))
        self._rebuild()

    def remove(self, event_filter: QObject) -> None:
        kept = [entry for entry in self._entries if entry[0] is not event_filter]
        if len(kept) != len(self._entries):
            self._entries = kept
            self._rebuild()

    def filters(self) -> tuple[QObject, ...]:
        return tuple(entry[0] for entry in self._entries)

    def _rebuild(self) -> None:
        by_type: dict[object, list[QObject]] = {}
        for event_filter, types in self._entries:
            for event_type in types:
                by_type.setdefault(event_type, []).append(event_filter)
        self._by_type = {event_type: tuple(filters) for event_type, filters in by_type.items()}

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt API
        try:
            targets = self._by_type.get(event.type())
        except RuntimeError:
            return False
        if not targets:
            return False
        stale = False
        for event_filter in targets:
            if not isValid(event_filter):
                stale = True
                continue
            try:
                if event_filter.eventFilter(watched, event):
                    return True
            except Exception:
                # What PySide does for an exception in an event filter: report
                # it and carry on as if the event was not handled.
                sys.excepthook(*sys.exc_info())
        if stale:
            self._entries = [entry for entry in self._entries if isValid(entry[0])]
            self._rebuild()
        return False


def app_event_hub(application: QCoreApplication | None = None) -> AppEventHub | None:
    app = application if application is not None else QCoreApplication.instance()
    if app is None:
        return None
    hub = getattr(app, _HUB_ATTRIBUTE, None)
    if isinstance(hub, AppEventHub) and isValid(hub):
        return hub
    hub = AppEventHub(app)
    app.installEventFilter(hub)
    setattr(app, _HUB_ATTRIBUTE, hub)
    return hub


def install_app_event_filter(
    application: QCoreApplication | None,
    event_filter: QObject,
    event_types: Iterable[QEvent.Type],
) -> None:
    """Let ``event_filter`` see the application's events of ``event_types`` (newest first)."""

    hub = app_event_hub(application)
    if hub is not None:
        hub.add(event_filter, event_types)


def remove_app_event_filter(application: QCoreApplication | None, event_filter: QObject) -> None:
    app = application if application is not None else QCoreApplication.instance()
    hub = getattr(app, _HUB_ATTRIBUTE, None) if app is not None else None
    if isinstance(hub, AppEventHub) and isValid(hub):
        hub.remove(event_filter)


__all__ = [
    "AppEventHub",
    "app_event_hub",
    "install_app_event_filter",
    "remove_app_event_filter",
]
