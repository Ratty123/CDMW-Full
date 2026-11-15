"""P3: textures are on by default, and stored profiles are moved once."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.ui.archive_browser.preview_settings_migration import (
    TEXTURES_DEFAULT_VERSION,
    TEXTURES_DEFAULT_VERSION_KEY,
    TEXTURES_SETTING_KEY,
    migrate_textures_on_by_default,
)


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "CrimsonDesertModWorkbench.cfg"), QSettings.Format.IniFormat)


def test_a_fresh_profile_shows_textures() -> None:
    assert ModelPreviewRenderSettings().use_textures_by_default is True
    assert clamp_model_preview_render_settings().use_textures_by_default is True


def test_a_profile_saved_with_the_old_default_is_moved_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(TEXTURES_SETTING_KEY, False)
    assert migrate_textures_on_by_default(settings) is True
    assert settings.value(TEXTURES_SETTING_KEY, False, type=bool) is True
    assert int(settings.value(TEXTURES_DEFAULT_VERSION_KEY)) == TEXTURES_DEFAULT_VERSION
    # The setting stays: a later choice of "off" is kept.
    settings.setValue(TEXTURES_SETTING_KEY, False)
    assert migrate_textures_on_by_default(settings) is False
    assert settings.value(TEXTURES_SETTING_KEY, True, type=bool) is False


def test_the_migration_survives_a_save_and_reload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(TEXTURES_SETTING_KEY, "false")
    migrate_textures_on_by_default(settings)
    settings.sync()
    reloaded = _settings(tmp_path)
    assert reloaded.value(TEXTURES_SETTING_KEY, False, type=bool) is True
    reloaded.setValue(TEXTURES_SETTING_KEY, False)
    assert migrate_textures_on_by_default(reloaded) is False
    assert reloaded.value(TEXTURES_SETTING_KEY, True, type=bool) is False


def test_a_profile_already_showing_textures_only_records_the_version(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(TEXTURES_SETTING_KEY, True)
    assert migrate_textures_on_by_default(settings) is False
    assert settings.value(TEXTURES_SETTING_KEY, False, type=bool) is True
    assert int(settings.value(TEXTURES_DEFAULT_VERSION_KEY)) == TEXTURES_DEFAULT_VERSION


def test_both_settings_readers_apply_the_migration(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
    from cdmw.ui.settings_tab import SettingsTab

    for read in (ArchivePreviewSettingsMixin._read_model_preview_render_settings,
                 SettingsTab._read_model_preview_render_settings):
        settings = _settings(tmp_path / read.__qualname__.split(".")[0])
        settings.setValue(TEXTURES_SETTING_KEY, False)

        def read_bool(key, default, settings=settings):
            return settings.value(key, default, type=bool)

        def read_float(key, default, settings=settings):
            return float(settings.value(key, default))

        def read_int(key, default, settings=settings):
            return int(settings.value(key, default))

        shell = SimpleNamespace(settings=settings, _read_bool=read_bool, _read_float=read_float, _read_int=read_int)
        owner = SimpleNamespace(shell=shell, settings=settings, _read_bool=read_bool, _read_float=read_float,
                                _read_int=read_int)
        assert read(owner).use_textures_by_default is True
