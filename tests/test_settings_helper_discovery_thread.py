"""Settings > Setup: the helper version check never reads the app's QSettings on its worker thread.

One QSettings object is not safe to use from two threads at once, and the GUI
thread can write the app's settings while the check runs.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from cdmw.ui.settings_helper_discovery import SettingsHelperDiscoveryMixin


class _RecordingSettings:
    def __init__(self, values):
        self.values, self.reads = dict(values), []

    def value(self, key, default=None):
        self.reads.append((threading.get_ident(), key))
        return self.values.get(key, default)


class _SetupPage(SettingsHelperDiscoveryMixin, QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.asset_authoring_service = None
        self._asset_authoring_service_factory = None
        self._asset_authoring_helper_thread = None
        self._asset_authoring_helper_worker = None
        self._asset_authoring_helpers_loaded = False
        self.asset_authoring_helper_refresh_button = QPushButton(self)
        self.asset_authoring_helper_status_label = QLabel(self)


def test_version_refresh_reads_settings_only_on_the_gui_thread(tmp_path, monkeypatch):
    for variable in ("CDMW_XATLAS_BIN", "CDMW_OIIO_BIN"):
        monkeypatch.delenv(variable, raising=False)
    app = QApplication.instance() or QApplication([])
    configured = tmp_path / "xatlas.exe"
    settings = _RecordingSettings({"asset_authoring/xatlas_path": str(configured)})
    page = _SetupPage(settings)
    try:
        page._start_asset_authoring_helper_version_refresh()
        thread = page._asset_authoring_helper_thread
        deadline = time.monotonic() + 30
        while page._asset_authoring_helper_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert page._asset_authoring_helper_thread is None, "The version check did not finish"
        assert thread is not None
        keys = {key for _ident, key in settings.reads}
        assert {"asset_authoring/xatlas_path", "asset_authoring/oiio_path"} <= keys
        assert {ident for ident, _key in settings.reads} == {threading.main_thread().ident}
        assert "Checking" not in page.asset_authoring_helper_status_label.text()
    finally:
        page.deleteLater()
        app.processEvents()
