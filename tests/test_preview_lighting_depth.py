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
        assert dialog.preview_lighting_preset_combo.currentData() == "neutral_studio"
        events = []
        dialog.settings_changed.connect(events.append)
        dialog.preview_shadows_checkbox.click()
        dialog.preview_ambient_occlusion_checkbox.click()
        dialog.preview_lighting_preset_combo.setCurrentIndex(dialog.preview_lighting_preset_combo.findData("studio_fixed"))
        assert len(events) == 3
        settings = events[-1]
        assert settings.preview_lighting_preset == "studio_fixed"
        assert not settings.preview_shadows and not settings.preview_ambient_occlusion
        flags = model_preview_settings_change_flags(defaults, settings)
        assert flags.d3d11_render_tuning_changed
        assert not flags.needs_asset_refresh and not flags.d3d11_package_affecting_changed
        quality, _ = render_tuning_payloads(settings, {})
        assert quality['preview_shadows'] is False
        assert quality['preview_ambient_occlusion'] is False
        assert quality['preview_lighting_preset'] == 'studio_fixed'
        store = QSettings(str(tmp_path / 'preview.ini'), QSettings.Format.IniFormat)
        shell = SimpleNamespace(settings=store, archive=SimpleNamespace(_current_model_preview_render_settings=lambda: settings))
        assert SettingsPersistenceMixin._save_model_preview_settings_if_loaded(shell)
        store.sync()
        restored = QSettings(str(tmp_path / 'preview.ini'), QSettings.Format.IniFormat)
        dialog.set_settings(replace(defaults,
            preview_lighting_preset=restored.value('preview/preview_lighting_preset', 'neutral_studio'),
            preview_shadows=restored.value('preview/preview_shadows', True, type=bool),
            preview_ambient_occlusion=restored.value('preview/preview_ambient_occlusion', True, type=bool)))
        assert not dialog.current_settings().preview_shadows
        assert not dialog.current_settings().preview_ambient_occlusion
        assert dialog.current_settings().preview_lighting_preset == 'studio_fixed'
        dialog.set_settings(defaults)
        assert dialog.current_settings().preview_shadows and dialog.current_settings().preview_ambient_occlusion
        assert dialog.current_settings().preview_lighting_preset == 'neutral_studio'
    finally:
        shiboken6.delete(dialog)
        app.processEvents()


def test_changing_a_setting_keeps_the_page_you_are_on():
    """Fredric (2026-11-15): a Lighting preset change jumped to Camera Input."""
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QSlider, QSpinBox, QDoubleSpinBox

    app = QApplication.instance() or QApplication([])
    defaults = ModelPreviewRenderSettings()
    dialog = ModelPreviewSettingsDialog(settings=defaults)
    try:
        for tab in (dialog._quality_tab, dialog._general_tab):
            if not dialog.tabs.isTabVisible(dialog.tabs.indexOf(tab)):
                continue
            dialog.tabs.setCurrentWidget(tab)
            dialog.preview_lighting_preset_combo.setCurrentIndex(
                dialog.preview_lighting_preset_combo.findData("studio_fixed"))
            assert dialog.tabs.currentWidget() is tab
            # Every control on the page: none may move the dialog to another page.
            for control in tab.findChildren(QComboBox):
                if control.isVisibleTo(tab) and control.count() > 1:
                    control.setCurrentIndex((control.currentIndex() + 1) % control.count())
                    assert dialog.tabs.currentWidget() is tab, control.objectName() or control.currentText()
            for control in tab.findChildren(QAbstractButton):
                if control.isVisibleTo(tab) and control.isCheckable():
                    control.click()
                    assert dialog.tabs.currentWidget() is tab, control.text()
            for control in [w for kind in (QSlider, QSpinBox, QDoubleSpinBox) for w in tab.findChildren(kind)]:
                if control.isVisibleTo(tab):
                    control.setValue(control.maximum())
                    assert dialog.tabs.currentWidget() is tab
            dialog.set_settings(defaults)  # a re-sync from the shared settings
            assert dialog.tabs.currentWidget() is tab
    finally:
        shiboken6.delete(dialog)
        app.processEvents()


def test_game_icon_studio_is_offered_and_survives_every_preset_gate():
    """The fifth preset reaches the renderer by its id from each place that validates one."""
    from cdmw.models import clamp_model_preview_render_settings
    from cdmw.ui.preview.preview_settings_hub import LIGHTING_PRESETS, normalize_preview_settings

    app = QApplication.instance() or QApplication([])
    dialog = ModelPreviewSettingsDialog(settings=ModelPreviewRenderSettings())
    try:
        combo = dialog.preview_lighting_preset_combo
        index = combo.findData("icon_studio")
        assert index == combo.count() - 1 and combo.itemText(index) == "Game icon studio"
        assert [combo.itemData(row) for row in range(combo.count())] == list(LIGHTING_PRESETS)
        combo.setCurrentIndex(index)
        settings = dialog.current_settings()
    finally:
        shiboken6.delete(dialog)
        app.processEvents()
    assert settings.preview_lighting_preset == "icon_studio"
    assert clamp_model_preview_render_settings(settings).preview_lighting_preset == "icon_studio"
    quality, _ = render_tuning_payloads(settings, {})
    assert quality["preview_lighting_preset"] == "icon_studio"
    assert normalize_preview_settings({"lighting_preset": "Icon_Studio"})["lighting_preset"] == "icon_studio"
    # Neutral studio stays the default, and an unknown id still falls back to it.
    assert ModelPreviewRenderSettings().preview_lighting_preset == "neutral_studio"
    assert normalize_preview_settings({"lighting_preset": "icon"})["lighting_preset"] == "neutral_studio"
