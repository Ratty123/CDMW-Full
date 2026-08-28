from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid as qt_object_is_valid

from tests.conftest import _flush_qt_deferred_deletes


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def test_deferred_delete_cleanup_destroys_test_owned_qt_widgets() -> None:
    _app()
    widget = QWidget()
    widget.deleteLater()

    assert qt_object_is_valid(widget)
    _flush_qt_deferred_deletes()
    assert not qt_object_is_valid(widget)
