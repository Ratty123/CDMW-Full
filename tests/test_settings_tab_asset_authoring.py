from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.settings_tab import SettingsTab, _asset_authoring_helper_status_text


_APP = QApplication.instance() or QApplication([])


def _report(*, version: str = "", version_status: str = "not_checked") -> dict[str, object]:
    return {
        "helpers": {
            "material_maker": {
                "key": "material_maker",
                "label": "Material Maker",
                "status": "available",
                "version": version,
                "version_status": version_status,
                "path": "C:/tools/material_maker.exe",
            },
            "xatlas": {
                "key": "xatlas",
                "label": "xatlas",
                "status": "unavailable",
                "version": "",
                "version_status": "unavailable",
                "path": "",
            },
        }
    }


class _AssetAuthoringServiceStub:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []

    def discovery_report(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return _report()


class SettingsTabAssetAuthoringTests(unittest.TestCase):
    def _settings_tab(self, service: object) -> SettingsTab:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        settings = QSettings(str(Path(temp_dir.name) / "settings.ini"), QSettings.IniFormat)
        tab = SettingsTab(settings=settings, theme_key="crimson_desert", asset_authoring_service=service)  # type: ignore[arg-type]
        self.addCleanup(tab.request_shutdown)
        self.addCleanup(tab.deleteLater)
        return tab

    def test_settings_tab_defers_helper_discovery_until_setup_is_visible(self) -> None:
        service = _AssetAuthoringServiceStub()
        tab = self._settings_tab(service)

        self.assertEqual([], service.calls)
        self.assertIn("loads when Setup is shown", tab.asset_authoring_helper_status_label.text())

        tab.show()
        _APP.processEvents()
        _APP.processEvents()
        text = tab.asset_authoring_helper_status_label.text()

        self.assertIn("Material Maker: available", text)
        self.assertIn("version not checked", text)
        self.assertIn("xatlas: unavailable", text)
        self.assertEqual([{"include_versions": False}], service.calls)

    def test_settings_tab_service_factory_is_lazy_and_resolves_once(self) -> None:
        service = _AssetAuthoringServiceStub()
        factory_calls: list[object] = []

        tab = self._settings_tab(lambda: factory_calls.append(object()) or service)

        self.assertEqual([], factory_calls)
        self.assertIsNone(tab.asset_authoring_service)
        tab.show()
        _APP.processEvents()
        _APP.processEvents()
        self.assertEqual(1, len(factory_calls))
        self.assertIs(tab.asset_authoring_service, service)

    def test_settings_tab_can_display_exact_helper_versions_from_report(self) -> None:
        tab = self._settings_tab(_AssetAuthoringServiceStub())

        tab._apply_asset_authoring_helper_report(_report(version="Material Maker 1.4.0", version_status="ok"))

        self.assertIn("Material Maker 1.4.0", tab.asset_authoring_helper_status_label.text())

    def test_settings_tab_shows_bundled_mesh_backends_as_available(self) -> None:
        text = _asset_authoring_helper_status_text(
            {
                "helpers": {
                    "xatlas": {
                        "key": "xatlas",
                        "label": "xatlas",
                        "status": "available",
                        "version": "bundled in CDMW Mesh Core",
                        "version_status": "bundled",
                        "path": "C:/app/native/cdmw-mesh-core.exe",
                    }
                }
            }
        )

        self.assertIn("xatlas: available | bundled in CDMW Mesh Core", text)
        self.assertNotIn("version unavailable", text)

    def test_asset_authoring_helper_status_text_handles_empty_report(self) -> None:
        self.assertEqual("No asset authoring helpers reported.", _asset_authoring_helper_status_text({}))


if __name__ == "__main__":
    unittest.main()
