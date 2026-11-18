"""Studio (fixed lights) is the default lighting, and Game icon studio is retired."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from cdmw.models import (
    ModelPreviewRenderSettings,
    clamp_model_preview_render_settings,
    normalize_lighting_preset,
)
from cdmw.ui.archive_browser.preview_settings_migration import (
    LIGHTING_DEFAULT_VERSION,
    LIGHTING_DEFAULT_VERSION_KEY,
    LIGHTING_SETTING_KEY,
    migrate_lighting_to_studio,
)
from cdmw.ui.preview.preview_settings_hub import LIGHTING_PRESETS


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "CrimsonDesertModWorkbench.cfg"), QSettings.Format.IniFormat)


def test_a_fresh_profile_uses_studio_fixed_lights() -> None:
    assert ModelPreviewRenderSettings().preview_lighting_preset == "studio_fixed"
    assert clamp_model_preview_render_settings().preview_lighting_preset == "studio_fixed"


def test_game_icon_studio_is_retired_and_reads_as_studio() -> None:
    assert "icon_studio" not in LIGHTING_PRESETS
    assert normalize_lighting_preset("icon_studio") == "studio_fixed"
    assert normalize_lighting_preset("nonsense") == "studio_fixed"
    for kept in ("neutral_studio", "showcase", "dark", "studio_fixed"):
        assert normalize_lighting_preset(kept.upper()) == kept
    settings = ModelPreviewRenderSettings(preview_lighting_preset="icon_studio")
    assert clamp_model_preview_render_settings(settings).preview_lighting_preset == "studio_fixed"


@pytest.mark.parametrize("stored", ["neutral_studio", "icon_studio"])
def test_the_old_default_and_the_retired_preset_move_once(tmp_path: Path, stored: str) -> None:
    settings = _settings(tmp_path)
    settings.setValue(LIGHTING_SETTING_KEY, stored)
    assert migrate_lighting_to_studio(settings) is True
    assert settings.value(LIGHTING_SETTING_KEY) == "studio_fixed"
    assert int(settings.value(LIGHTING_DEFAULT_VERSION_KEY)) == LIGHTING_DEFAULT_VERSION
    # A later choice of Neutral studio is kept.
    settings.setValue(LIGHTING_SETTING_KEY, "neutral_studio")
    assert migrate_lighting_to_studio(settings) is False
    assert settings.value(LIGHTING_SETTING_KEY) == "neutral_studio"


@pytest.mark.parametrize("stored", ["showcase", "dark"])
def test_a_deliberate_choice_is_kept(tmp_path: Path, stored: str) -> None:
    settings = _settings(tmp_path)
    settings.setValue(LIGHTING_SETTING_KEY, stored)
    assert migrate_lighting_to_studio(settings) is False
    assert settings.value(LIGHTING_SETTING_KEY) == stored


def test_a_profile_without_a_stored_choice_gets_studio(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert migrate_lighting_to_studio(settings) is False
    assert settings.value(LIGHTING_SETTING_KEY) == "studio_fixed"
