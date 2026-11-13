"""Optional pen pressure in the stroke API and the tool settings (decision 48, P6)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from cdmw.domain.textures.editor_brush import (
    _interpolate_stroke,
    _interpolate_stroke_samples,
    apply_texture_editor_stroke,
    texture_editor_stroke_points_for_symmetry,
    texture_editor_stroke_pressures,
)
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorToolSettings

TOOLS = ["paint", "erase", "clone", "heal", "smudge", "dodge_burn", "soften", "sharpen"]


def _document() -> TextureEditorDocument:
    layer = TextureEditorLayer("paint", "Paint", "unused.png")
    return TextureEditorDocument("Brush", 128, 64, active_layer_id="paint", layers=(layer,))


def _settings(**overrides: object) -> TextureEditorToolSettings:
    settings = TextureEditorToolSettings(size=20, hardness=100, opacity=60, flow=100, spacing=50, color_hex="#FFFFFF")
    return replace(settings, **overrides)


def _pixels() -> np.ndarray:
    return np.random.default_rng(7).integers(0, 256, (64, 128, 4), dtype=np.uint8)


def test_the_default_is_full_pressure():
    assert TextureEditorToolSettings().pressure == 1.0


@pytest.mark.parametrize("tool", TOOLS)
def test_without_pressure_and_with_full_pressure_a_stroke_is_unchanged(tool):
    document, pixels = _document(), _pixels()
    settings = _settings(tool=tool, clone_source_point=(16, 8))
    points = [(16 + step, 30) for step in range(0, 60, 3)]
    plain = apply_texture_editor_stroke(document, {"paint": pixels}, settings, points, source_snapshot=pixels)["paint"]
    full = apply_texture_editor_stroke(document, {"paint": pixels}, settings, points, source_snapshot=pixels,
                                       pressures=[1.0] * len(points))["paint"]
    np.testing.assert_array_equal(plain, full)


def test_lighter_pressure_paints_less():
    document = _document()
    blank = np.zeros((64, 128, 4), dtype=np.uint8)
    settings = _settings()
    alpha = lambda pressure: apply_texture_editor_stroke(  # noqa: E731
        document, {"paint": blank}, settings, [(64, 32)], pressures=[pressure])["paint"][32, 64, 3]
    assert alpha(0.0) == 0
    assert 0 < alpha(0.25) < alpha(0.5) < alpha(1.0)


def test_pressure_follows_the_stroke_between_samples():
    document = _document()
    blank = np.zeros((64, 128, 4), dtype=np.uint8)
    painted = apply_texture_editor_stroke(document, {"paint": blank}, _settings(spacing=10), [(12, 32), (116, 32)],
                                          pressures=[0.1, 1.0])["paint"]
    # A light start and a firm end: alpha rises along the line.
    samples = [int(painted[32, x, 3]) for x in (20, 64, 108)]
    assert samples[0] < samples[1] < samples[2], samples


def test_the_settings_pressure_applies_when_the_stroke_brings_none():
    document, pixels = _document(), _pixels()
    points = [(20, 20), (60, 40)]
    by_settings = apply_texture_editor_stroke(document, {"paint": pixels}, _settings(pressure=0.4), points)["paint"]
    by_points = apply_texture_editor_stroke(document, {"paint": pixels}, _settings(), points, pressures=[0.4, 0.4])["paint"]
    np.testing.assert_array_equal(by_settings, by_points)


def test_a_mirrored_stamp_keeps_its_source_samples_pressure():
    document = _document()
    blank = np.zeros((64, 128, 4), dtype=np.uint8)
    painted = apply_texture_editor_stroke(document, {"paint": blank}, _settings(symmetry_mode="horizontal"),
                                          [(20, 32)], pressures=[0.5])["paint"]
    assert painted[32, 20, 3] == painted[32, 127 - 20, 3] > 0


def test_pressure_leaves_the_stroke_geometry_alone():
    points = [(0, 0), (3, 0), (3, 10), (20, 14)]
    spaced, values = _interpolate_stroke_samples(points, [0.0, 0.2, 0.6, 1.0], 5, smoothing=30)
    assert spaced == _interpolate_stroke(points, 5, smoothing=30)
    assert len(values) == len(spaced) and values[0] == 0.0 and values[-1] == 1.0
    assert values == sorted(values)
    mirrored = texture_editor_stroke_points_for_symmetry(spaced, 32, 32, "both")
    assert len(mirrored) >= len(spaced)


@pytest.mark.parametrize("pressures, message", [
    ([0.5], "one pressure per point"),
    ([0.5, 1.5], "between 0 and 1"),
    ([0.5, -0.1], "between 0 and 1"),
    ([0.5, float("nan")], "between 0 and 1"),
])
def test_bad_pressure_is_refused_with_the_reason(pressures, message):
    with pytest.raises(ValueError, match=message):
        texture_editor_stroke_pressures([(0, 0), (4, 4)], pressures)
    with pytest.raises(ValueError, match=message):
        apply_texture_editor_stroke(_document(), {"paint": _pixels()}, _settings(), [(0, 0), (4, 4)], pressures=pressures)
