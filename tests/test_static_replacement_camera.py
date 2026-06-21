from __future__ import annotations

import pytest

from cdmw.ui.archive_browser.static_replacement_camera import (
    alignment_active_qt_camera_role,
    alignment_d3d11_camera_active,
    alignment_preview_mode_key,
    alignment_preview_mode_saved_state,
    alignment_preview_view_sync_should_apply,
    fixed_alignment_camera_state,
    nudged_alignment_camera_state,
    qt_alignment_camera_state_mapping,
    qt_alignment_camera_tuple,
)


def test_alignment_camera_route_helpers_normalize_renderer_mode_and_saved_state() -> None:
    assert alignment_d3d11_camera_active(" D3D11 ", True) is True
    assert alignment_d3d11_camera_active("qt", True) is False
    assert alignment_preview_view_sync_should_apply({"active": False}, "side_by_side") is True
    assert alignment_preview_view_sync_should_apply({"active": True}, "side_by_side") is False
    assert alignment_preview_view_sync_should_apply({"active": False}, "overlay") is False
    assert alignment_active_qt_camera_role("replacement_only") == "replacement_only"
    assert alignment_active_qt_camera_role("overlay") == "overlay"
    assert alignment_active_qt_camera_role("") == "side_by_side"
    assert alignment_preview_mode_key("") == "side_by_side"
    saved = {"overlay": {"yaw": 12.0}, "bad": object()}
    assert alignment_preview_mode_saved_state(saved, "overlay") == {"yaw": 12.0}
    assert alignment_preview_mode_saved_state(saved, "bad") is None


def test_fixed_alignment_camera_state_builds_reset_view_payload() -> None:
    assert fixed_alignment_camera_state("90", "-10", role="replacement") == {
        "role": "replacement",
        "yaw": 90.0,
        "pitch": -10.0,
        "fit_to_view": True,
        "zoom_factor": 1.0,
        "pan": (0.0, 0.0, 0.0),
    }


def test_nudged_alignment_camera_state_preserves_extra_values_and_clamps_pitch() -> None:
    nudged = nudged_alignment_camera_state(
        {"yaw": 10.0, "pitch": 85.0, "zoom_factor": 2.0},
        delta_yaw=15.0,
        delta_pitch=20.0,
        role="replacement",
    )

    assert nudged == {
        "role": "replacement",
        "yaw": 25.0,
        "pitch": 89.0,
        "zoom_factor": 2.0,
    }


def test_qt_alignment_camera_state_mapping_converts_snapshot_to_restore_mapping() -> None:
    assert qt_alignment_camera_state_mapping(
        (1, "2.5", True, "3.5", 99.0, (4, "5.5", 6, 7)),
        role="replacement",
    ) == {
        "role": "replacement",
        "yaw": 1.0,
        "pitch": 2.5,
        "fit_to_view": True,
        "zoom_factor": 3.5,
        "pan": (4.0, 5.5, 6.0),
    }


def test_qt_alignment_camera_tuple_clamps_zoom_and_pads_pan() -> None:
    assert qt_alignment_camera_tuple(
        {
            "yaw": "12.5",
            "pitch": "-3.0",
            "fit_to_view": False,
            "zoom_factor": 0.01,
            "pan": (1.0, "2.5"),
        },
        fit_distance=64.0,
    ) == (12.5, -3.0, False, 0.1, 640.0, (1.0, 2.5, 0.0))


def test_qt_alignment_camera_tuple_uses_fit_distance_when_fit_to_view() -> None:
    assert qt_alignment_camera_tuple(
        {
            "zoom_factor": 99.0,
            "fit_to_view": True,
            "pan": (3.0, 4.0, 5.0, 6.0),
        },
        fit_distance=32.0,
    ) == (-35.0, 20.0, True, 16.0, 32.0, (3.0, 4.0, 5.0))


def test_qt_alignment_camera_tuple_falls_back_for_invalid_pan_only() -> None:
    assert qt_alignment_camera_tuple({"pan": object()}, fit_distance=16.0) == (
        -35.0,
        20.0,
        True,
        1.0,
        16.0,
        (0.0, 0.0, 0.0),
    )
    with pytest.raises(ValueError):
        qt_alignment_camera_tuple({"zoom_factor": "bad"}, fit_distance=16.0)
