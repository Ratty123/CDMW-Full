from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from tools.mesh_harness.visual_audit_corpus import VISUAL_AUDIT_VIEWS


def _capture_integrity(
    *,
    run_id: str,
    expected_ids: list[str],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
    composite_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    integrity = {
        "schema": "cdmw_mesh_visual_audit_integrity_v1",
        "run_id": run_id,
        "expected_asset_ids": expected_ids,
        "archive_asset_ids": _report_asset_ids(archive_report),
        "dotnet_asset_ids": _report_asset_ids(dotnet_report),
        "composite_asset_ids": [str(row.get("id", "")) for row in composite_rows],
        "archive_run_matches": str(archive_report.get("run_id", "")) == run_id,
        "dotnet_run_matches": str(dotnet_report.get("run_id", "")) == run_id,
        "dotnet_camera_mapping_matches": _dotnet_camera_mapping_matches(dotnet_report),
        "paired_camera_views_match": _paired_camera_views_match(
            expected_ids,
            archive_report,
            dotnet_report,
        ),
        "rendered_camera_views_match": _rendered_camera_views_match(
            expected_ids,
            archive_report,
            dotnet_report,
        ),
        "composites_complete": all(
            row.get("archive_browser_capture_ok") is True
            and row.get("mesh_editor_capture_ok") is True
            for row in composite_rows
        ),
    }
    integrity["ok"] = (
        integrity["archive_run_matches"]
        and integrity["dotnet_run_matches"]
        and integrity["dotnet_camera_mapping_matches"]
        and integrity["paired_camera_views_match"]
        and integrity["rendered_camera_views_match"]
        and integrity["archive_asset_ids"] == expected_ids
        and integrity["dotnet_asset_ids"] == expected_ids
        and integrity["composite_asset_ids"] == expected_ids
        and integrity["composites_complete"]
    )
    return integrity


def _dotnet_camera_mapping_matches(report: Mapping[str, object]) -> bool:
    expected_mapping = "archive_to_dotnet_180_minus_yaw_negate_pitch"
    capture_count = 0
    for asset in tuple(report.get("assets", ()) or ()):
        if not isinstance(asset, Mapping):
            return False
        for capture in tuple(asset.get("captures", ()) or ()):
            if not isinstance(capture, Mapping):
                return False
            capture_count += 1
            if str(capture.get("camera_mapping", "")) != expected_mapping:
                return False
            try:
                yaw = float(capture.get("yaw"))
                pitch = float(capture.get("pitch"))
                renderer_yaw = float(capture.get("renderer_yaw"))
                renderer_pitch = float(capture.get("renderer_pitch"))
            except (TypeError, ValueError):
                return False
            if not all(
                math.isfinite(value)
                for value in (yaw, pitch, renderer_yaw, renderer_pitch)
            ):
                return False
            if abs(renderer_yaw - (180.0 - yaw)) > 0.05:
                return False
            if abs(renderer_pitch + pitch) > 0.05:
                return False
    return capture_count > 0


def _paired_camera_views_match(
    expected_ids: Sequence[str],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
) -> bool:
    archive_assets = tuple(archive_report.get("assets", ()) or ())
    dotnet_assets = tuple(dotnet_report.get("assets", ()) or ())
    if len(archive_assets) != len(expected_ids) or len(dotnet_assets) != len(
        expected_ids
    ):
        return False

    expected_views = tuple(VISUAL_AUDIT_VIEWS)
    for expected_id, archive_asset, dotnet_asset in zip(
        expected_ids,
        archive_assets,
        dotnet_assets,
        strict=True,
    ):
        if not isinstance(archive_asset, Mapping) or not isinstance(
            dotnet_asset, Mapping
        ):
            return False
        if (
            str(archive_asset.get("id", "")) != expected_id
            or str(dotnet_asset.get("id", "")) != expected_id
        ):
            return False
        archive_captures = tuple(archive_asset.get("captures", ()) or ())
        dotnet_captures = tuple(dotnet_asset.get("captures", ()) or ())
        if (
            len(archive_captures) != len(expected_views)
            or len(dotnet_captures) != len(expected_views)
        ):
            return False
        for expected_view, archive_capture, dotnet_capture in zip(
            expected_views,
            archive_captures,
            dotnet_captures,
            strict=True,
        ):
            if not isinstance(archive_capture, Mapping) or not isinstance(
                dotnet_capture, Mapping
            ):
                return False
            expected_name = str(expected_view["name"])
            if str(archive_capture.get("name", "")) != expected_name:
                return False
            if str(dotnet_capture.get("name", "")) != expected_name:
                return False
            expected_angles = _finite_yaw_pitch(expected_view)
            archive_angles = _finite_yaw_pitch(archive_capture)
            dotnet_angles = _finite_yaw_pitch(dotnet_capture)
            if (
                expected_angles is None
                or archive_angles is None
                or dotnet_angles is None
            ):
                return False
            if not _angles_match(archive_angles, expected_angles):
                return False
            if not _angles_match(dotnet_angles, expected_angles):
                return False
            camera_ack = archive_capture.get("camera_ack")
            if not isinstance(camera_ack, Mapping):
                return False
            archive_ack_angles = _finite_yaw_pitch(camera_ack)
            if archive_ack_angles is None or not _angles_match(
                archive_ack_angles, expected_angles
            ):
                return False
    return bool(expected_ids)


def _rendered_camera_views_match(
    expected_ids: Sequence[str],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
) -> bool:
    archive_assets = tuple(archive_report.get("assets", ()) or ())
    dotnet_assets = tuple(dotnet_report.get("assets", ()) or ())
    if len(archive_assets) != len(expected_ids) or len(dotnet_assets) != len(
        expected_ids
    ):
        return False

    expected_views = tuple(VISUAL_AUDIT_VIEWS)
    for expected_id, archive_asset, dotnet_asset in zip(
        expected_ids,
        archive_assets,
        dotnet_assets,
        strict=True,
    ):
        if not isinstance(archive_asset, Mapping) or not isinstance(
            dotnet_asset, Mapping
        ):
            return False
        if (
            str(archive_asset.get("id", "")) != expected_id
            or str(dotnet_asset.get("id", "")) != expected_id
        ):
            return False
        archive_captures = tuple(archive_asset.get("captures", ()) or ())
        dotnet_captures = tuple(dotnet_asset.get("captures", ()) or ())
        if len(archive_captures) != len(expected_views) or len(
            dotnet_captures
        ) != len(expected_views):
            return False
        archive_matrices: set[tuple[float, ...]] = set()
        dotnet_matrices: set[tuple[float, ...]] = set()
        for expected_view, archive_capture, dotnet_capture in zip(
            expected_views,
            archive_captures,
            dotnet_captures,
            strict=True,
        ):
            if not isinstance(archive_capture, Mapping) or not isinstance(
                dotnet_capture, Mapping
            ):
                return False
            expected_name = str(expected_view["name"])
            if str(archive_capture.get("name", "")) != expected_name:
                return False
            if str(dotnet_capture.get("name", "")) != expected_name:
                return False
            expected_angles = _finite_yaw_pitch(expected_view)
            if expected_angles is None:
                return False

            camera_ack = archive_capture.get("camera_ack")
            if not isinstance(camera_ack, Mapping):
                return False
            if str(camera_ack.get("event", "")).casefold() != "view_state":
                return False
            if str(camera_ack.get("reason", "")).casefold() != "set_view":
                return False
            if str(camera_ack.get("role", "")).casefold() != "replacement":
                return False

            capture_event = archive_capture.get("capture_event")
            if not isinstance(capture_event, Mapping) or capture_event.get("ok") is not True:
                return False
            archive_camera = capture_event.get("rendered_camera")
            dotnet_camera = dotnet_capture.get("rendered_camera")
            if not isinstance(archive_camera, Mapping) or not isinstance(
                dotnet_camera, Mapping
            ):
                return False
            if str(archive_camera.get("role", "")).casefold() not in {
                "all",
                "replacement",
            }:
                return False
            if str(dotnet_camera.get("role", "")).casefold() != "editable":
                return False

            archive_rendered_angles = _finite_rendered_camera_angles(archive_camera)
            dotnet_rendered_angles = _finite_rendered_camera_angles(dotnet_camera)
            dotnet_expected_angles = (180.0 - expected_angles[0], -expected_angles[1])
            if archive_rendered_angles is None or not _angles_match(
                archive_rendered_angles, expected_angles
            ):
                return False
            if dotnet_rendered_angles is None or not _angles_match(
                dotnet_rendered_angles, dotnet_expected_angles
            ):
                return False
            if not _rendered_camera_metrics_are_usable(archive_camera):
                return False
            if not _rendered_camera_metrics_are_usable(dotnet_camera):
                return False

            archive_matrix = _finite_world_view_projection(archive_camera)
            dotnet_matrix = _finite_world_view_projection(dotnet_camera)
            if archive_matrix is None or dotnet_matrix is None:
                return False
            archive_matrices.add(_matrix_signature(archive_matrix))
            dotnet_matrices.add(_matrix_signature(dotnet_matrix))
        if len(archive_matrices) != len(expected_views) or len(
            dotnet_matrices
        ) != len(expected_views):
            return False
    return bool(expected_ids)


def _finite_rendered_camera_angles(
    payload: Mapping[str, object],
) -> tuple[float, float] | None:
    try:
        yaw = float(payload.get("yaw_degrees"))
        pitch = float(payload.get("pitch_degrees"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(yaw) or not math.isfinite(pitch):
        return None
    return yaw, pitch


def _rendered_camera_metrics_are_usable(payload: Mapping[str, object]) -> bool:
    try:
        viewport_width = float(payload.get("viewport_width"))
        viewport_height = float(payload.get("viewport_height"))
        solid_draw_count = int(payload.get("solid_draw_count"))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        math.isfinite(viewport_width)
        and math.isfinite(viewport_height)
        and viewport_width > 0.0
        and viewport_height > 0.0
        and solid_draw_count > 0
    )


def _finite_world_view_projection(
    payload: Mapping[str, object],
) -> tuple[float, ...] | None:
    raw_matrix = payload.get("world_view_projection")
    if not isinstance(raw_matrix, Sequence) or isinstance(
        raw_matrix, (str, bytes, bytearray)
    ):
        return None
    try:
        matrix = tuple(float(value) for value in raw_matrix)
    except (TypeError, ValueError):
        return None
    if len(matrix) != 16 or not all(math.isfinite(value) for value in matrix):
        return None
    if not any(abs(value) > 1.0e-9 for value in matrix):
        return None
    return matrix


def _matrix_signature(matrix: Sequence[float]) -> tuple[float, ...]:
    return tuple(round(float(value), 6) for value in matrix)


def _finite_yaw_pitch(payload: Mapping[str, object]) -> tuple[float, float] | None:
    try:
        yaw = float(payload.get("yaw"))
        pitch = float(payload.get("pitch"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(yaw) or not math.isfinite(pitch):
        return None
    return yaw, pitch


def _angles_match(
    actual: tuple[float, float],
    expected: tuple[float, float],
) -> bool:
    return abs(actual[0] - expected[0]) <= 0.05 and abs(
        actual[1] - expected[1]
    ) <= 0.05


def _report_asset_ids(report: Mapping[str, object]) -> list[str]:
    return [
        str(row.get("id", ""))
        for row in tuple(report.get("assets", ()) or ())
        if isinstance(row, Mapping)
    ]
