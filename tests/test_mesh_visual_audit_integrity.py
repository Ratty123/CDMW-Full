from __future__ import annotations

from tools.mesh_harness.visual_audit_corpus import VISUAL_AUDIT_VIEWS
from tools.mesh_harness.visual_audit_integrity import (
    _capture_integrity,
    _dotnet_camera_mapping_matches,
    _rendered_camera_views_match,
)


def _test_camera_matrix(index: int, backend_offset: float) -> list[float]:
    matrix = [0.0] * 16
    matrix[0] = 1.0 + backend_offset + float(index)
    matrix[5] = 1.0
    matrix[10] = 1.0
    matrix[15] = 1.0
    return matrix


def _archive_camera_report(
    *,
    rendered_pitch_overrides: dict[str, float] | None = None,
) -> dict[str, object]:
    rendered_pitch_overrides = rendered_pitch_overrides or {}
    captures = []
    for index, view in enumerate(VISUAL_AUDIT_VIEWS):
        capture = dict(view)
        name = str(view["name"])
        capture["camera_ack"] = {
            "event": "view_state",
            "reason": "set_view",
            "role": "replacement",
            "yaw": view["yaw"],
            "pitch": view["pitch"],
        }
        capture["capture_event"] = {
            "event": "frame_capture",
            "ok": True,
            "path": f"C:/audit/{name}.png",
            "rendered_camera": {
                "role": "replacement",
                "yaw_degrees": view["yaw"],
                "pitch_degrees": rendered_pitch_overrides.get(
                    name, float(view["pitch"])
                ),
                "viewport_width": 768,
                "viewport_height": 768,
                "world_view_projection": _test_camera_matrix(index, 0.0),
                "solid_draw_count": 1,
            },
        }
        captures.append(capture)
    return {
        "run_id": "camera-run",
        "assets": [{"id": "001-camera", "ok": True, "captures": captures}],
    }


def _dotnet_camera_report(
    *,
    pitch_overrides: dict[str, float] | None = None,
    renderer_pitch_overrides: dict[str, float] | None = None,
    rendered_pitch_overrides: dict[str, float] | None = None,
    omitted_views: set[str] | None = None,
) -> dict[str, object]:
    pitch_overrides = pitch_overrides or {}
    renderer_pitch_overrides = renderer_pitch_overrides or {}
    rendered_pitch_overrides = rendered_pitch_overrides or {}
    omitted_views = omitted_views or set()
    captures = []
    for index, view in enumerate(VISUAL_AUDIT_VIEWS):
        name = str(view["name"])
        if name in omitted_views:
            continue
        yaw = float(view["yaw"])
        pitch = pitch_overrides.get(name, float(view["pitch"]))
        renderer_yaw = 180.0 - yaw
        renderer_pitch = renderer_pitch_overrides.get(name, -pitch)
        captures.append(
            {
                "name": name,
                "yaw": yaw,
                "pitch": pitch,
                "renderer_yaw": renderer_yaw,
                "renderer_pitch": renderer_pitch,
                "camera_mapping": "archive_to_dotnet_180_minus_yaw_negate_pitch",
                "rendered_camera": {
                    "role": "editable",
                    "yaw_degrees": renderer_yaw,
                    "pitch_degrees": rendered_pitch_overrides.get(
                        name, renderer_pitch
                    ),
                    "viewport_width": 768,
                    "viewport_height": 768,
                    "world_view_projection": _test_camera_matrix(index, 100.0),
                    "solid_draw_count": 1,
                },
            }
        )
    return {
        "run_id": "camera-run",
        "assets": [
            {
                "id": "001-camera",
                "ok": True,
                "captures": captures,
            }
        ],
    }


def test_visual_audit_integrity_rejects_inverted_dotnet_pitch_mapping() -> None:
    report = _dotnet_camera_report()
    assert _dotnet_camera_mapping_matches(report) is True

    inverted = _dotnet_camera_report(
        renderer_pitch_overrides={"slightly-above": -28.0}
    )
    assert _dotnet_camera_mapping_matches(inverted) is False

    integrity = _capture_integrity(
        run_id="camera-run",
        expected_ids=["001-camera"],
        archive_report=_archive_camera_report(),
        dotnet_report=inverted,
        composite_rows=[
            {
                "id": "001-camera",
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        ],
    )
    assert integrity["dotnet_camera_mapping_matches"] is False
    assert integrity["ok"] is False


def test_visual_audit_integrity_requires_same_six_archive_and_dotnet_views() -> None:
    archive_report = _archive_camera_report()
    complete = _capture_integrity(
        run_id="camera-run",
        expected_ids=["001-camera"],
        archive_report=archive_report,
        dotnet_report=_dotnet_camera_report(),
        composite_rows=[
            {
                "id": "001-camera",
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        ],
    )
    assert complete["paired_camera_views_match"] is True
    assert complete["rendered_camera_views_match"] is True
    assert complete["ok"] is True

    opposite_side = _capture_integrity(
        run_id="camera-run",
        expected_ids=["001-camera"],
        archive_report=archive_report,
        dotnet_report=_dotnet_camera_report(
            pitch_overrides={"slightly-above": 28.0}
        ),
        composite_rows=[
            {
                "id": "001-camera",
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        ],
    )
    assert opposite_side["dotnet_camera_mapping_matches"] is True
    assert opposite_side["paired_camera_views_match"] is False
    assert opposite_side["ok"] is False

    incomplete = _capture_integrity(
        run_id="camera-run",
        expected_ids=["001-camera"],
        archive_report=archive_report,
        dotnet_report=_dotnet_camera_report(omitted_views={"slightly-below"}),
        composite_rows=[
            {
                "id": "001-camera",
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        ],
    )
    assert incomplete["paired_camera_views_match"] is False
    assert incomplete["ok"] is False


def test_visual_audit_integrity_requires_angles_from_the_captured_render_camera() -> None:
    assert _rendered_camera_views_match(
        ["001-camera"],
        _archive_camera_report(),
        _dotnet_camera_report(),
    ) is True

    native_wrong_render = _archive_camera_report(
        rendered_pitch_overrides={"slightly-above": 28.0}
    )
    assert _rendered_camera_views_match(
        ["001-camera"],
        native_wrong_render,
        _dotnet_camera_report(),
    ) is False
    integrity = _capture_integrity(
        run_id="camera-run",
        expected_ids=["001-camera"],
        archive_report=native_wrong_render,
        dotnet_report=_dotnet_camera_report(),
        composite_rows=[
            {
                "id": "001-camera",
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        ],
    )
    assert integrity["rendered_camera_views_match"] is False
    assert integrity["ok"] is False

    dotnet_wrong_render = _dotnet_camera_report(
        rendered_pitch_overrides={"slightly-above": -28.0}
    )
    assert _rendered_camera_views_match(
        ["001-camera"],
        _archive_camera_report(),
        dotnet_wrong_render,
    ) is False


def test_visual_audit_integrity_rejects_stale_or_nonfinite_render_matrices() -> None:
    stale = _dotnet_camera_report()
    stale_assets = stale["assets"]
    assert isinstance(stale_assets, list)
    stale_captures = stale_assets[0]["captures"]
    assert isinstance(stale_captures, list)
    front_camera = stale_captures[0]["rendered_camera"]
    side_camera = stale_captures[2]["rendered_camera"]
    assert isinstance(front_camera, dict) and isinstance(side_camera, dict)
    side_camera["world_view_projection"] = list(
        front_camera["world_view_projection"]
    )
    assert _rendered_camera_views_match(
        ["001-camera"],
        _archive_camera_report(),
        stale,
    ) is False

    nonfinite = _archive_camera_report()
    nonfinite_assets = nonfinite["assets"]
    assert isinstance(nonfinite_assets, list)
    nonfinite_captures = nonfinite_assets[0]["captures"]
    assert isinstance(nonfinite_captures, list)
    capture_event = nonfinite_captures[0]["capture_event"]
    assert isinstance(capture_event, dict)
    rendered_camera = capture_event["rendered_camera"]
    assert isinstance(rendered_camera, dict)
    matrix = list(rendered_camera["world_view_projection"])
    matrix[0] = float("nan")
    rendered_camera["world_view_projection"] = matrix
    assert _rendered_camera_views_match(
        ["001-camera"],
        nonfinite,
        _dotnet_camera_report(),
    ) is False
