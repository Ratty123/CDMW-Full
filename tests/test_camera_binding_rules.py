from __future__ import annotations

import pytest

from cdmw.domain.camera_bindings import (
    ALT,
    ALT_OR_CTRL,
    CAMERA_MODIFIER_CHOICES,
    CTRL,
    DEFAULT_ORBIT,
    DEFAULT_PAN,
    SHIFT,
    camera_bindings_conflict,
    camera_modifier_label,
    normalize_camera_modifier,
    resolve_camera_bindings,
)
from cdmw.models import ModelPreviewRenderSettings


def test_the_shipped_defaults_do_not_collide() -> None:
    assert not camera_bindings_conflict(DEFAULT_ORBIT, DEFAULT_PAN)
    defaults = ModelPreviewRenderSettings()
    assert defaults.camera_orbit_modifier == DEFAULT_ORBIT
    assert defaults.camera_pan_modifier == DEFAULT_PAN
    assert resolve_camera_bindings(
        defaults.camera_orbit_modifier, defaults.camera_pan_modifier
    ) == (DEFAULT_ORBIT, DEFAULT_PAN)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ALT", ALT),
        (" shift ", SHIFT),
        ("Alt_Or_Ctrl", ALT_OR_CTRL),
        ("", DEFAULT_PAN),
        (None, DEFAULT_PAN),
        ("meta", DEFAULT_PAN),
        (object(), DEFAULT_PAN),
    ],
)
def test_normalization_accepts_only_the_offered_choices(value: object, expected: str) -> None:
    assert normalize_camera_modifier(value, DEFAULT_PAN) == expected


def test_alt_or_ctrl_conflicts_with_either_key_alone() -> None:
    assert camera_bindings_conflict(ALT_OR_CTRL, ALT)
    assert camera_bindings_conflict(ALT_OR_CTRL, CTRL)
    assert camera_bindings_conflict(ALT, ALT_OR_CTRL)
    assert not camera_bindings_conflict(ALT_OR_CTRL, SHIFT)
    assert not camera_bindings_conflict(ALT, CTRL)


def test_a_colliding_pair_moves_orbit_and_never_pan() -> None:
    """Pan is tested first by the viewport, so orbit is the binding that loses.

    A shared key would pan and leave orbit silently dead, which reads as the
    rebind not working rather than as a conflict.
    """
    orbit, pan = resolve_camera_bindings(SHIFT, SHIFT)
    assert pan == SHIFT
    assert orbit != SHIFT
    assert not camera_bindings_conflict(orbit, pan)

    orbit, pan = resolve_camera_bindings(ALT_OR_CTRL, ALT)
    assert pan == ALT
    assert not camera_bindings_conflict(orbit, pan)


def test_every_offered_pair_resolves_to_something_usable() -> None:
    for orbit, _ in CAMERA_MODIFIER_CHOICES:
        for pan, _ in CAMERA_MODIFIER_CHOICES:
            resolved_orbit, resolved_pan = resolve_camera_bindings(orbit, pan)
            assert resolved_pan == pan
            assert not camera_bindings_conflict(resolved_orbit, resolved_pan)
            assert camera_modifier_label(resolved_orbit)
            assert camera_modifier_label(resolved_pan)


def test_labels_cover_every_choice_and_fall_back_for_junk() -> None:
    labels = {value: label for value, label in CAMERA_MODIFIER_CHOICES}
    assert labels[ALT_OR_CTRL] == "Alt or Ctrl"
    for value, label in labels.items():
        assert camera_modifier_label(value) == label
    assert camera_modifier_label("nonsense") == labels[DEFAULT_ORBIT]
