"""A preview viewport moved into the Rust page stays in the page's control tree.

Create New Item's preview sits in a splitter row beside its Scene panel. Once the
viewport moved to the page, the splitter no longer held it, the next snapshot had
no viewport slot, the next layout hid it, and its preview never loaded.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QSplitter, QVBoxLayout, QWidget

from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_portals import PreviewPortals

_APP = QApplication.instance() or QApplication([])


class RustPreviewHostFrame(QFrame):
    """Stands in for the preview host: the document knows it by this class name."""


def _pump() -> None:
    for _ in range(3):
        _APP.processEvents()


@pytest.fixture
def scene():
    workflow = QWidget()
    workflow.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    QVBoxLayout(workflow).addWidget(QLabel("Preview", workflow))
    row = QSplitter(Qt.Orientation.Horizontal, workflow)  # the Scene panel's row
    workflow.layout().addWidget(row)
    host = RustPreviewHostFrame(row)
    row.addWidget(host)
    row.addWidget(QLabel("Scene", row))
    page = QWidget()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    page.resize(800, 600)
    workflow.resize(800, 600)
    page.show()
    workflow.show()
    _pump()
    bridge = NewItemPresentationBridge(workflow)
    portals = PreviewPortals(page)
    try:
        yield bridge, portals, host, row, page
    finally:
        portals.restore()
        workflow.deleteLater()
        page.deleteLater()
        _pump()


def _slots(bridge) -> list[str]:
    bridge.snapshot()
    return list(bridge.document.portals)


def _layout(portals, bridge, page, ids, *, clip=(0, 0, 800, 600)) -> None:
    portals.update(bridge.document, {"pixels_per_point": page.devicePixelRatioF(), "portals": [
        {"id": identifier, "rect": [10, 10, 300, 200], "clip": list(clip)} for identifier in ids]})
    _pump()


def test_a_viewport_in_a_splitter_row_keeps_its_slot_once_moved_to_the_page(scene):
    bridge, portals, host, row, page = scene
    slots = _slots(bridge)
    assert len(slots) == 1
    _layout(portals, bridge, page, slots)
    assert host.parentWidget() is page and host.isVisible()
    assert _slots(bridge) == slots  # was empty: the moved viewport left the tree

    # A layout without it (scrolled away) hides it; the next one shows it again.
    _layout(portals, bridge, page, [])
    assert host.isHidden()
    assert _slots(bridge) == slots
    _layout(portals, bridge, page, slots)
    assert host.isVisible()


def test_restore_puts_the_viewport_back_in_its_splitter_slot(scene):
    bridge, portals, host, row, page = scene
    _layout(portals, bridge, page, _slots(bridge))
    portals.restore()
    _pump()
    assert host.parentWidget() is row and row.indexOf(host) == 0 and row.count() == 2
    assert not host.isHidden()
