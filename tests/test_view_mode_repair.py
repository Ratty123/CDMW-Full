"""A Faces (No Textures) view mode an editor session without textures left behind is repaired once.

In 0.12.0-alpha.6 the Mesh Editor saved its untextured fallback as the shared view mode, so
Browse Archives and every later editor drew untextured across restarts.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from cdmw.domain.preview_view_modes import (
    LEGACY_VIEW_MODE_KEY,
    VIEW_MODE_KEY,
    VIEW_MODE_REPAIR_VERSION,
    VIEW_MODE_REPAIR_VERSION_KEY,
    read_view_mode,
    repair_leaked_view_mode,
)
from cdmw.ui.preview.preview_settings_hub import PreviewSettingsHub


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "CrimsonDesertModWorkbench.cfg"), QSettings.Format.IniFormat)


def test_a_stored_faces_mode_moves_to_textured_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(VIEW_MODE_KEY, "faces")
    assert repair_leaked_view_mode(settings) is True
    assert read_view_mode(settings) == "textured"
    assert int(settings.value(VIEW_MODE_REPAIR_VERSION_KEY)) == VIEW_MODE_REPAIR_VERSION
    # Faces picked again afterwards is a choice, and it is kept.
    settings.setValue(VIEW_MODE_KEY, "faces")
    assert repair_leaked_view_mode(settings) is False
    assert read_view_mode(settings) == "faces"


def test_the_repair_survives_a_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(VIEW_MODE_KEY, "faces")
    repair_leaked_view_mode(settings)
    settings.setValue(VIEW_MODE_KEY, "faces")
    settings.sync()
    reloaded = _settings(tmp_path)
    assert repair_leaked_view_mode(reloaded) is False
    assert read_view_mode(reloaded) == "faces"


@pytest.mark.parametrize("stored", ["wire", "faces_wire", "base_color", "xray", "textured"])
def test_every_other_mode_is_kept(tmp_path: Path, stored: str) -> None:
    settings = _settings(tmp_path)
    settings.setValue(VIEW_MODE_KEY, stored)
    assert repair_leaked_view_mode(settings) is False
    assert read_view_mode(settings) == stored
    assert int(settings.value(VIEW_MODE_REPAIR_VERSION_KEY)) == VIEW_MODE_REPAIR_VERSION


def test_a_profile_without_a_stored_mode_is_only_marked(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.setValue(LEGACY_VIEW_MODE_KEY, "lit")
    assert repair_leaked_view_mode(settings) is False
    assert read_view_mode(settings) == "textured"
    # The old key is still what is read: nothing was rewritten.
    assert settings.value(VIEW_MODE_KEY, None) in (None, "")
    assert settings.value(LEGACY_VIEW_MODE_KEY) == "lit"


def test_no_viewport_starts_from_the_leaked_mode(tmp_path: Path) -> None:
    """The shared settings every viewport reads are repaired before their first read."""

    settings = _settings(tmp_path)
    settings.setValue(VIEW_MODE_KEY, "faces")
    hub = PreviewSettingsHub(settings)
    assert hub.values()["view_mode"] == "textured"
    assert read_view_mode(settings) == "textured"
    # A later choice of Faces, in any viewport, is stored and followed as before.
    assert hub.update(view_mode="faces") is True
    assert PreviewSettingsHub(settings).values()["view_mode"] == "faces"
