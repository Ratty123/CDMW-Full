from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.localization import UiLocalizer


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def test_runtime_tracking_transfers_the_single_application_owner(tmp_path: Path) -> None:
    app = _app()
    first_root = QWidget()
    second_root = QWidget()
    first = UiLocalizer(language_dir=tmp_path / "first", language_code="fr")
    second = UiLocalizer(language_dir=tmp_path / "second", language_code="de")

    first.activate_runtime_tracking(first_root, application=app)
    assert app.property("_cdmw_ui_localizer") is first

    second.activate_runtime_tracking(second_root, application=app)

    assert app.property("_cdmw_ui_localizer") is second
    assert first._application is None
    assert first._runtime_tracking_active is False
    assert first._registered_roots == []

    second.shutdown()
    first_root.deleteLater()
    second_root.deleteLater()
    app.processEvents()
