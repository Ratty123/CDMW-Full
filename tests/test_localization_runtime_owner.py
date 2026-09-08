from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cdmw.ui.localization import UiLocalizer
from cdmw.ui.shell.lazy_tool_tab import LazyToolTab


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


def test_applying_and_collecting_translations_do_not_construct_lazy_tools(tmp_path: Path) -> None:
    app = _app()
    root = QWidget()
    created: list[QWidget] = []
    lazy = LazyToolTab(lambda: created.append(QWidget()) or created[-1])
    lazy.setToolTip("Cancel")
    QVBoxLayout(root).addWidget(lazy)
    localizer = UiLocalizer(language_dir=tmp_path, language_code="fr")
    try:
        localizer.apply(root)
        sources = localizer.collect_source_strings(root)
        assert created == []
        assert lazy.widget_if_created() is None
        assert lazy.toolTip() == localizer.translate("Cancel")
        assert "Cancel" in sources
    finally:
        localizer.shutdown()
        root.deleteLater()
        app.processEvents()
