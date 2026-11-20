from __future__ import annotations

from PySide6.QtCore import QSettings

from cdmw.mcp.ui_actions import _protected_values, _restore_protected


def _settings(tmp_path):
    return QSettings(str(tmp_path / "cdmw.ini"), QSettings.Format.IniFormat)


def test_a_settings_save_writing_an_unset_game_folder_as_empty_is_not_a_change(tmp_path):
    settings = _settings(tmp_path)
    before = _protected_values(settings)
    settings.setValue("archive/package_root", "")
    assert _restore_protected(settings, before) == []


def test_a_real_game_folder_change_is_put_back(tmp_path):
    settings = _settings(tmp_path)
    settings.setValue("archive/package_root", "C:/Game")
    before = _protected_values(settings)
    settings.setValue("archive/package_root", "C:/Other")
    assert _restore_protected(settings, before) == ["archive/package_root"]
    assert settings.value("archive/package_root") == "C:/Game"
