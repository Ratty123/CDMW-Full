"""Headless input-through-workflow checks for Create New Item's Rust presentation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from PySide6.QtCore import QEvent, QProcess, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from cdmw.services.new_item_rust_protocol import (
    JsonLineReader, PROTOCOL, PresentationProtocolError, decode_message, encode_message,
)
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.new_item.rust_ui_document import PresentationDocument, theme_snapshot
import test_new_item_studio_tab as _support

TEMPLATE = _support.TEMPLATE


@pytest.fixture
def studio():
    _support.TabTests.setUpClass()
    fixture = _support.TabTests("runTest")
    fixture.setUp()
    tab = fixture._tab()
    tab.prefill_template(TEMPLATE)
    tab.resize(1440, 960)
    tab.show()
    QApplication.processEvents()
    try:
        yield fixture, tab, NewItemPresentationBridge(tab)
    finally:
        fixture.tearDown()


def _input(bridge, widget, action, value=None, *, revision=None):
    bridge.snapshot()
    identifier = bridge.document.registry.identify(widget)
    node = bridge.document.registry.current[identifier]
    return {"protocol": PROTOCOL, "type": "input", "session": bridge.session,
            "request": bridge._last_request + 1, "control": identifier,
            "revision": node["revision"] if revision is None else revision,
            "action": action, "value": value}


def _send(bridge, widget, action, value=None):
    result = bridge.dispatch(_input(bridge, widget, action, value))
    QApplication.processEvents()
    return result


def test_json_lines_preserve_split_unicode_and_reject_oversize_duplicate_and_nonfinite():
    reader = JsonLineReader()
    packet = encode_message({"type": "test", "text": "中文 – Ö"})
    messages = []
    for byte in packet:
        messages.extend(reader.feed(bytes([byte])))
    assert messages[0]["text"] == "中文 – Ö"
    with pytest.raises(PresentationProtocolError, match="limit"):
        JsonLineReader(limit=5).feed(b"123456")
    for suffix in ('"x": NaN', '"x": 1, "x": 2'):
        with pytest.raises(PresentationProtocolError):
            decode_message(('{"protocol":"' + PROTOCOL + '",' + suffix + '}').encode())


@pytest.fixture
def placement_ui(studio):
    _fixture, tab, bridge = studio
    panel = tab.model_panel
    with patch.object(type(panel.preview), "showing_placement", new_callable=PropertyMock, return_value=True), \
            patch.object(panel, "refresh_preview"):
        tab.show_step(2)
        panel._set_placement_visible(True)
        panel.inspector_tabs.setCurrentWidget(panel.placement_group)
        panel._refresh_placement_enabled()
        QApplication.processEvents()
        yield tab.controller, panel, bridge


def test_placement_axes_and_scale_directions_reach_the_rust_controls(placement_ui):
    _controller, panel, bridge = placement_ui
    state = bridge.snapshot()
    nodes = bridge.document.registry.current
    for spins in (panel.offset_spins, panel.rotation_spins, panel.scale_spins):
        for spin, axis in zip(spins, "XYZ"):
            node = nodes[bridge.document.registry.identify(spin)]
            assert node["kind"] == "number"
            assert node["props"]["prefix"] == f"{axis}: "
            assert node["enabled"]
    scale_ids = [bridge.document.registry.identify(spin) for spin in panel.scale_spins]
    projected, pending = [], [state["root"]]
    while pending:
        node = pending.pop()
        projected.append(node)
        pending.extend(node.get("children", []))
    grid = next(node for node in projected if node["kind"] == "grid"
                and any(child.get("id") == scale_ids[0] for child in node["children"]))
    for column, (identifier, direction) in enumerate(zip(scale_ids, ("Width", "Height", "Depth"))):
        number = next(child for child in grid["children"] if child["id"] == identifier)
        label = next(child for child in grid["children"] if child["props"].get("text") == direction)
        assert label["cell"] == [number["cell"][0] - 1, column, 1, 1]
        assert "before rotation" in number["tooltip"]
    uniform = nodes[bridge.document.registry.identify(panel.uniform_scale)]
    assert uniform["kind"] == "check"
    assert uniform["label"] == "Uniform scale"
    assert not uniform["props"]["checked"]


@pytest.mark.parametrize("initial,axis,value,expected", [
    ((1, 1, 1), 0, 2, (2, 2, 2)),
    ((2, 3, 4), 0, 6, (6, 9, 12)),
    ((2, 3, 4), 1, 6, (4, 6, 8)),
    ((2, 3, 4), 2, 6, (3, 4.5, 6)),
    ((500, 250, 125), 2, 1000, (1000, 500, 250)),
    ((1, 2, 4), 2, 0.0001, (0.0001, 0.0002, 0.0004)),
])
def test_uniform_scale_input_keeps_proportions_and_publishes_once(placement_ui, initial, axis, value, expected):
    from cdmw.ui.new_item.model_import import ModelPlacement

    controller, panel, bridge = placement_ui
    original = ModelPlacement(offset=(0.125, -0.25, 0.5), rotation=(10, 20, 30), scale=initial)
    controller.set_model_placement(original)
    _send(bridge, panel.uniform_scale, "toggle", True)
    assert controller.model_placement == original
    with patch.object(controller, "set_model_placement", wraps=controller.set_model_placement) as publish, \
            patch.object(controller, "invalidate_plan", wraps=controller.invalidate_plan) as invalidate:
        _send(bridge, panel.scale_spins[axis], "number", value)
    assert publish.call_count == 1
    assert invalidate.call_count == 1
    assert controller.model_placement.scale == pytest.approx(expected)
    assert controller.model_placement.offset == original.offset
    assert controller.model_placement.rotation == original.rotation
    assert tuple(spin.value() for spin in panel.scale_spins) == pytest.approx(expected)
    bridge.snapshot()
    for spin, expected_value in zip(panel.scale_spins, expected):
        node = bridge.document.registry.current[bridge.document.registry.identify(spin)]
        assert node["props"]["value"] == pytest.approx(expected_value)


def test_uniform_toggle_and_external_placement_keep_independent_edits_intact(placement_ui):
    from cdmw.ui.new_item.model_import import ModelPlacement

    controller, panel, bridge = placement_ui
    controller.set_model_placement(ModelPlacement())
    _send(bridge, panel.scale_spins[1], "number", 3)
    assert controller.model_placement.scale == (1, 3, 1)
    with patch.object(controller, "set_model_placement", wraps=controller.set_model_placement) as publish:
        _send(bridge, panel.uniform_scale, "toggle", True)
        publish.assert_not_called()
        external = ModelPlacement(scale=(2, 4, 8))
        panel._gizmo_moved(external, False)
        publish.assert_not_called()
        assert tuple(spin.value() for spin in panel.scale_spins) == external.scale
        panel._gizmo_moved(external, True)
        assert publish.call_count == 1
        assert controller.model_placement == external
    _send(bridge, panel.offset_spins[0], "number", 0.5)
    _send(bridge, panel.rotation_spins[2], "number", 45)
    assert controller.model_placement.scale == external.scale
    _send(bridge, panel.scale_spins[0], "number", 4)
    assert controller.model_placement.scale == (4, 8, 16)
    _send(bridge, panel.uniform_scale, "toggle", False)
    _send(bridge, panel.scale_spins[2], "number", 5)
    assert controller.model_placement.scale == (4, 8, 5)
    _send(bridge, panel.uniform_scale, "toggle", True)
    _send(bridge, panel.fit_button, "activate")
    assert controller.model_placement == ModelPlacement()
    _send(bridge, panel.scale_spins[2], "number", 2)
    assert controller.model_placement.scale == (2, 2, 2)
