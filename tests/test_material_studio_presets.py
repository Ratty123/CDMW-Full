"""Saved shader presets: a per-computer convenience of the Shader experiments panel."""

from __future__ import annotations

import json

import pytest

from cdmw.core.shader_preset_store import delete_user_preset, save_user_preset, store_file, user_presets
from cdmw.services.mesh_shader_controls import _change_user_preset, catalogue_with_user_presets

_VEIL = "SkinnedMeshTransparency"


@pytest.fixture(autouse=True)
def preset_file(tmp_path, monkeypatch):
    path = tmp_path / "settings" / "shader_presets.json"
    monkeypatch.setenv("CDMW_SHADER_PRESET_FILE", str(path))
    return path


def test_no_file_means_only_the_built_in_presets(preset_file):
    assert user_presets() == {}
    veil = next(family for family in catalogue_with_user_presets() if family["shader"] == _VEIL)
    assert veil["presets"] and not any(preset.get("user") for preset in veil["presets"])
    assert not preset_file.exists()


def test_a_saved_preset_follows_the_built_in_ones_and_survives_a_reload(preset_file):
    save_user_preset(_VEIL, "  My   soft veil ", {"_netPitch": [0.2], "_netThread": [0.4], "_dyeingColor": [1, 0.5, 0.25]})
    assert store_file() == preset_file
    veil = next(family for family in catalogue_with_user_presets() if family["shader"] == _VEIL)
    assert veil["presets"][-1] == {"label": "My soft veil", "user": True,
                                   "values": {"_netPitch": [0.2], "_netThread": [0.4], "_dyeingColor": [1, 0.5, 0.25]}}
    assert [preset.get("user", False) for preset in veil["presets"]][:-1] == [False] * (len(veil["presets"]) - 1)
    # Other shaders are untouched.
    glass = next(family for family in catalogue_with_user_presets() if family["shader"] == "SkinnedMeshGlass")
    assert not any(preset.get("user") for preset in glass["presets"])


def test_saving_the_same_name_replaces_and_delete_removes(preset_file):
    save_user_preset(_VEIL, "Mine", {"_netPitch": [0.2]})
    save_user_preset(_VEIL, "Other", {"_netPitch": [0.6]})
    save_user_preset(_VEIL, "MINE", {"_netPitch": [0.3]})
    assert [(row["name"], row["values"]) for row in user_presets()[_VEIL]] == [
        ("Other", {"_netPitch": [0.6]}), ("MINE", {"_netPitch": [0.3]})]
    delete_user_preset(_VEIL, "other")
    delete_user_preset(_VEIL, "mine")
    assert user_presets() == {}
    with pytest.raises(ValueError, match="no longer saved"):
        delete_user_preset(_VEIL, "mine")


@pytest.mark.parametrize("shader, name, values, message", [
    ("NotAShader", "x", {"_netPitch": [0.2]}, "shader this panel edits"),
    (_VEIL, "   ", {"_netPitch": [0.2]}, "name of up to 48"),
    (_VEIL, "x" * 49, {"_netPitch": [0.2]}, "name of up to 48"),
    (_VEIL, "x", {}, "no values"),
    (_VEIL, "x", {"_netPitch": [7.0]}, "."),
    (_VEIL, "x", {"_unknown": [0.2]}, "."),
])
def test_invalid_presets_are_refused_and_nothing_is_written(preset_file, shader, name, values, message):
    with pytest.raises(ValueError, match=message):
        save_user_preset(shader, name, values)
    assert not preset_file.exists()


def test_a_damaged_row_is_skipped_and_a_damaged_file_is_no_presets(preset_file):
    preset_file.parent.mkdir(parents=True)
    preset_file.write_text(json.dumps({"version": 1, "presets": {_VEIL: [
        {"name": "Good", "values": {"_netPitch": [0.2]}},
        {"name": "Out of range", "values": {"_netPitch": [9]}},
        {"values": {"_netPitch": [0.2]}},
    ], "Gone": [{"name": "x", "values": {}}]}}), encoding="utf-8")
    assert user_presets() == {_VEIL: [{"name": "Good", "values": {"_netPitch": [0.2]}}]}
    preset_file.write_text("not json", encoding="utf-8")
    assert user_presets() == {}
    save_user_preset(_VEIL, "Fresh", {"_netPitch": [0.2]})
    assert [row["name"] for row in user_presets()[_VEIL]] == ["Fresh"]


def test_the_panel_request_saves_and_deletes(preset_file):
    _change_user_preset({"action": "save", "shader": _VEIL, "name": "Mine", "values": {"_netPitch": [0.25]}})
    assert user_presets()[_VEIL][0]["values"] == {"_netPitch": [0.25]}
    _change_user_preset({"action": "delete", "shader": _VEIL, "name": "Mine"})
    assert user_presets() == {}
    for request in (None, {}, {"action": "rename"}):
        with pytest.raises(ValueError, match="Invalid shader preset request"):
            _change_user_preset(request)
