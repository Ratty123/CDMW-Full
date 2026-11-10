"""Depth controls use live presentation updates and survive settings round trips."""
from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import shiboken6

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_settings_state import model_preview_settings_change_flags
from cdmw.ui.model_preview_settings_dialog import ModelPreviewSettingsDialog
from cdmw.ui.preview.dotnet_host_render_tuning import render_tuning_payloads
from cdmw.ui.shell.settings_persistence import SettingsPersistenceMixin


def test_depth_controls_default_on_and_emit_live_updates_without_rebuilding_assets(tmp_path):
    app = QApplication.instance() or QApplication([])
    defaults = ModelPreviewRenderSettings()
    dialog = ModelPreviewSettingsDialog(settings=defaults)
    try:
        assert dialog.tabs.isTabVisible(dialog.tabs.indexOf(dialog._quality_tab))
        assert not dialog.preview_shadows_checkbox.isHidden()
        assert not dialog.preview_ambient_occlusion_checkbox.isHidden()
        assert dialog.preview_shadows_checkbox.isChecked()
        assert dialog.preview_ambient_occlusion_checkbox.isChecked()
        events = []
        dialog.settings_changed.connect(events.append)
        dialog.preview_shadows_checkbox.click()
        dialog.preview_ambient_occlusion_checkbox.click()
        assert len(events) == 2
        settings = events[-1]
        assert not settings.preview_shadows and not settings.preview_ambient_occlusion
        flags = model_preview_settings_change_flags(defaults, settings)
        assert flags.d3d11_render_tuning_changed
        assert not flags.needs_asset_refresh and not flags.d3d11_package_affecting_changed
        quality, _ = render_tuning_payloads(settings, {})
        assert quality['preview_shadows'] is False
        assert quality['preview_ambient_occlusion'] is False
        store = QSettings(str(tmp_path / 'preview.ini'), QSettings.Format.IniFormat)
        shell = SimpleNamespace(settings=store, archive=SimpleNamespace(_current_model_preview_render_settings=lambda: settings))
        assert SettingsPersistenceMixin._save_model_preview_settings_if_loaded(shell)
        store.sync()
        restored = QSettings(str(tmp_path / 'preview.ini'), QSettings.Format.IniFormat)
        dialog.set_settings(replace(defaults,
            preview_shadows=restored.value('preview/preview_shadows', True, type=bool),
            preview_ambient_occlusion=restored.value('preview/preview_ambient_occlusion', True, type=bool)))
        assert not dialog.current_settings().preview_shadows
        assert not dialog.current_settings().preview_ambient_occlusion
        dialog.set_settings(defaults)
        assert dialog.current_settings().preview_shadows and dialog.current_settings().preview_ambient_occlusion
    finally:
        shiboken6.delete(dialog)
        app.processEvents()
