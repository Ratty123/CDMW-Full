"""Drop PySide's wrappers of Qt-made layout items before Qt deletes the items.

``outer.addLayout(row)`` on a layout that already has a widget, and
``layout.itemAt(i)``, make PySide wrap each Qt-made layout item (a
``QWidgetItem`` for a widget, a ``QSpacerItem`` for a stretch) and keep the
wrapper as a child of the layout's wrapper. Qt deletes such an item by itself
when its widget is deleted or given another parent, and PySide is not told: the
wrapper stays registered under the item's freed address for as long as the
layout lives. The next Python-made QObject that Qt allocates at that address
(a QThreadWrapper is 80 bytes, a QWidgetItem 88: the same heap size class)
finds the old wrapper in PySide's address map instead of its own, and PySide
asks that wrapper's type, which is no QObject type, for a meta-object:
``SignalManager::retrieveMetaObject`` reads a null pointer and the process
dies of an access violation in the constructor. That is the crash of
2026-11-17 in ``QThread(self)`` in the Item Finder warm-up, while Mesh Editor
tabs were closed: its dump shows PySide handed an older wrapper, of a type with
no QObject data, for the new QThread's address. The Mesh Editor's panels leave
such wrappers behind when they move or delete their buttons.

Qt sends ChildRemoved to the parent before its layout deletes the child's item,
and application event filters see it first. The filter here then invalidates
those wrappers in the parent's layouts: an invalidated wrapper leaves PySide's
map and is never handed out again. The items are not touched, and the next
``itemAt`` simply makes a new wrapper. Only wrappers nothing but their layout
holds are dropped: a layout written in Python (``WrappingLayout``, ``FlowLayout``)
keeps its items' wrappers in a list and hands them back to Qt from ``itemAt``, so
those must stay valid, as must any wrapper Python code still holds. Wrappers of
items made in Python (their wrapper class tells PySide when they are deleted)
and items taken out with ``takeAt`` (no longer the layout's child) are left
alone too. The idle full garbage collection also sweeps every layout, for an
item Qt deletes without a ChildRemoved (a widget moved between two layouts of
one parent).
"""

from __future__ import annotations

import gc
import sys

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget

try:
    import shiboken6
except ImportError:  # pragma: no cover - PySide always ships it
    shiboken6 = None  # type: ignore[assignment]

_releaser: "LayoutItemWrapperReleaser | None" = None
#: References to a wrapper only its layout holds, as ``_references`` counts them.
_only_layout_references: int | None = None
_calibrating = False


def _layout_children(layout: object) -> tuple[list[object], list[object]]:
    """The sub-layouts, and the wrappers of Qt-made items, that ``layout``'s wrapper holds."""

    layouts: list[object] = []
    items: list[object] = []
    for child in gc.get_referents(layout):
        if isinstance(child, QObject):
            if isinstance(child, QLayout):
                layouts.append(child)
        elif (
            isinstance(child, QLayoutItem)
            and shiboken6.isValid(child)
            and not shiboken6.createdByPython(child)
        ):
            items.append(child)
    return layouts, items


def _references(items: list[object], index: int) -> int:
    return sys.getrefcount(items[index])


def _calibrated_only_layout_references() -> int | None:
    """Count the references of a wrapper only its layout holds, once, on a scratch layout.

    Counting this way rather than assuming a number keeps the rule right on
    every Python version (3.14 counts borrowed references differently)."""

    global _only_layout_references, _calibrating
    if _only_layout_references is None and not _calibrating and QCoreApplication.instance() is not None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

        _calibrating = True

        host = QWidget()
        outer = QVBoxLayout(host)
        row = QHBoxLayout()
        row.addWidget(QLabel(host))
        outer.addLayout(row)  # PySide wraps the label's item; only outer holds it
        _layouts, items = _layout_children(outer)
        if items:
            _only_layout_references = _references(items, 0)
        del items
        shiboken6.delete(host)
        _calibrating = False
    return _only_layout_references


def release_layout_item_wrappers(root: QLayout) -> int:
    """Invalidate PySide's wrappers of Qt-made items held by ``root`` and its sub-layouts.

    Only PySide's own bookkeeping changes: the items and the layout stay as they
    are. A wrapper anything else holds is kept. Returns how many were dropped."""

    if shiboken6 is None:
        return 0
    limit = _calibrated_only_layout_references()
    if limit is None:
        return 0
    released = 0
    stack: list[object] = [root]
    seen: set[int] = set()
    while stack:
        layout = stack.pop()
        if id(layout) in seen:
            continue
        seen.add(id(layout))
        layouts, items = _layout_children(layout)
        stack.extend(layouts)
        for index in range(len(items)):
            if _references(items, index) <= limit:
                shiboken6.invalidate(items[index])
                released += 1
    return released


def release_all_layout_item_wrappers() -> int:
    """The same for every layout PySide knows (the idle sweep)."""

    if shiboken6 is None:
        return 0
    # Keep only the layouts: the full list would hold every item wrapper too, and a
    # held wrapper is never dropped.
    layouts = [wrapper for wrapper in shiboken6.getAllValidWrappers() if isinstance(wrapper, QLayout)]
    return sum(release_layout_item_wrappers(layout) for layout in layouts)


def _layout_root(watched: object) -> QLayout | None:
    if isinstance(watched, QWidget):
        return watched.layout()
    if isinstance(watched, QLayout):
        parent = watched.parentWidget()
        top = parent.layout() if parent is not None else None
        return top if top is not None else watched
    return None


class LayoutItemWrapperReleaser(QObject):
    """Application filter for ChildRemoved (through the app event hub)."""

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802 - Qt API
        # Never event.child(): it may be half destroyed. The parent is whole.
        try:
            if event.type() == QEvent.Type.ChildRemoved:
                root = _layout_root(watched)
                if root is not None:
                    release_layout_item_wrappers(root)
        except RuntimeError:
            pass
        return False


def ensure_app_layout_item_wrapper_release(app: QCoreApplication | None) -> LayoutItemWrapperReleaser | None:
    global _releaser
    if app is None:
        return None
    from cdmw.ui.app_event_hub import install_app_event_filter

    if _releaser is not None:
        try:
            if _releaser.parent() == app:
                return _releaser
        except RuntimeError:
            pass  # deleted with an earlier application
    _calibrated_only_layout_references()
    _releaser = LayoutItemWrapperReleaser(app)
    install_app_event_filter(app, _releaser, (QEvent.Type.ChildRemoved,))
    return _releaser


__all__ = [
    "LayoutItemWrapperReleaser",
    "ensure_app_layout_item_wrapper_release",
    "release_all_layout_item_wrappers",
    "release_layout_item_wrappers",
]
