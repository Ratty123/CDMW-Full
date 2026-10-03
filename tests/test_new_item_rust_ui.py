"""Headless input-through-workflow checks for Create New Item's Rust presentation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
