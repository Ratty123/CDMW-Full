from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from tools.mesh_harness.visual_audit_corpus import VISUAL_AUDIT_VIEWS


_CAMERA_BASIS_COSINE_MIN = math.cos(math.radians(0.25))
_MAX_RESIDENT_ASSETS_PER_BATCH = 128


def _capture_integrity(
    *,
    run_id: str,
    expected_ids: list[str],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
    composite_rows: Sequence[Mapping[str, object]],
    prepared_packages_unchanged: bool = True,
) -> dict[str, object]:
    dotnet_v2 = str(dotnet_report.get("schema", "") or "").endswith("_v2")
    integrity = {
        "schema": "cdmw_mesh_visual_audit_integrity_v2",
        "compatible_reader_schemas": ["cdmw_mesh_visual_audit_integrity_v1"],
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
        "material_region_captures_complete": (
            _material_region_captures_complete(dotnet_report) if dotnet_v2 else True
        ),
        "resident_renderer_unchanged": (
            _resident_renderer_unchanged(dotnet_report) if dotnet_v2 else True
        ),
        "composites_complete": all(
            row.get("archive_browser_capture_ok") is True
            and row.get("mesh_editor_capture_ok") is True
            for row in composite_rows
        ),
        "prepared_packages_unchanged": prepared_packages_unchanged is True,
    }
    integrity["ok"] = (
        integrity["archive_run_matches"]
        and integrity["dotnet_run_matches"]
        and integrity["dotnet_camera_mapping_matches"]
        and integrity["paired_camera_views_match"]
        and integrity["rendered_camera_views_match"]
        and integrity["material_region_captures_complete"]
        and integrity["resident_renderer_unchanged"]
        and integrity["archive_asset_ids"] == expected_ids
        and integrity["dotnet_asset_ids"] == expected_ids
        and integrity["composite_asset_ids"] == expected_ids
        and integrity["composites_complete"]
        and integrity["prepared_packages_unchanged"]
    )
    return integrity


def _dotnet_camera_mapping_matches(report: Mapping[str, object]) -> bool:
    expected_mapping = "archive_object_rotation_basis_orthographic_v1"
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
            if abs(renderer_yaw - yaw) > 0.05:
                return False
            if abs(renderer_pitch - pitch) > 0.05:
                return False
        for region in tuple(asset.get("material_regions", ()) or ()):
            if not isinstance(region, Mapping):
                return False
            for capture in tuple(region.get("captures", ()) or ()):
                if not isinstance(capture, Mapping):
                    return False
                capture_count += 1
                if str(capture.get("camera_mapping", "")) != expected_mapping:
                    return False
                angles = _finite_yaw_pitch(capture)
                if angles is None:
                    return False
                try:
                    renderer_angles = (
                        float(capture.get("renderer_yaw")),
                        float(capture.get("renderer_pitch")),
                    )
                except (TypeError, ValueError):
                    return False
                if not _angles_match(renderer_angles, angles):
                    return False
    return capture_count > 0


def _material_region_captures_complete(report: Mapping[str, object]) -> bool:
    expected = (
        ("front", "final"),
        ("oblique", "final"),
        ("oblique", "base"),
        ("oblique", "normal"),
        ("oblique", "roughness"),
        ("oblique", "metallic"),
        ("oblique", "specular"),
        ("oblique", "layer_mask"),
    )
    region_count = 0
    for asset in tuple(report.get("assets", ()) or ()):
        if not isinstance(asset, Mapping):
            return False
        try:
            source_submesh_count = int(asset.get("source_submesh_count", 0))
        except (TypeError, ValueError, OverflowError):
            return False
        if source_submesh_count <= 0:
            return False
        regions = tuple(asset.get("material_regions", ()) or ())
        if not regions:
            return False
        seen_indices: set[int] = set()
        for region in regions:
            if not isinstance(region, Mapping) or region.get("ok") is not True:
                return False
            try:
                submesh_index = int(region.get("source_submesh_index"))
            except (TypeError, ValueError, OverflowError):
                return False
            if submesh_index < 0 or submesh_index in seen_indices:
                return False
            seen_indices.add(submesh_index)
            captures = tuple(region.get("captures", ()) or ())
            for capture in captures:
                if not isinstance(capture, Mapping) or capture.get("ok") is not True:
                    return False
                rendered_camera = capture.get("rendered_camera", {})
                if not isinstance(rendered_camera, Mapping):
                    return False
                try:
                    solid_draw_count = int(rendered_camera.get("solid_draw_count"))
                except (TypeError, ValueError, OverflowError):
                    return False
                if solid_draw_count != 1:
                    return False
            actual = tuple(
                (str(row.get("angle", "")), str(row.get("debug_mode", "")))
                for row in captures
                if isinstance(row, Mapping) and row.get("ok") is True
            )
            if actual != expected:
                return False
            try:
                hidden = tuple(int(value) for value in tuple(region.get("hidden_submesh_indices", ()) or ()))
            except (TypeError, ValueError, OverflowError):
                return False
            expected_hidden = tuple(index for index in range(source_submesh_count) if index != submesh_index)
            if hidden != expected_hidden:
                return False
            region_count += 1
        if seen_indices != set(range(source_submesh_count)):
            return False
    return region_count > 0


def _resident_renderer_unchanged(report: Mapping[str, object]) -> bool:
    session = report.get("renderer_session", {})
    if not isinstance(session, Mapping):
        return False
    try:
        requested_count = int(report.get("requested_asset_count", 0))
        batch_count = int(report.get("batch_count", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        return False
    if requested_count <= 0 or batch_count <= 0:
        return False

    raw_batch_counts = report.get("batch_asset_counts")
    explicit_batch_metadata = "batch_count" in report or raw_batch_counts is not None
    if batch_count == 1 and raw_batch_counts is None:
        batch_asset_counts = (requested_count,)
        sessions = (session,)
    else:
        if not isinstance(raw_batch_counts, Sequence) or isinstance(
            raw_batch_counts, (str, bytes, bytearray)
        ):
            return False
        try:
            batch_asset_counts = tuple(int(value) for value in raw_batch_counts)
        except (TypeError, ValueError, OverflowError):
            return False
        raw_sessions = session.get("batch_sessions")
        if not isinstance(raw_sessions, Sequence) or isinstance(
            raw_sessions, (str, bytes, bytearray)
        ):
            return False
        sessions = tuple(raw_sessions)

    if (
        len(batch_asset_counts) != batch_count
        or sum(batch_asset_counts) != requested_count
        or any(count <= 0 for count in batch_asset_counts)
        or (
            explicit_batch_metadata
            and any(
                count > _MAX_RESIDENT_ASSETS_PER_BATCH
                for count in batch_asset_counts
            )
        )
        or len(sessions) != batch_count
        or any(not isinstance(batch_session, Mapping) for batch_session in sessions)
    ):
        return False
    try:
        return (
            int(report.get("completed_asset_count", requested_count))
            == requested_count
            and int(report.get("resident_material_update_count", -1))
            == requested_count
            and int(report.get("resident_material_update_failure_count", -1)) == 0
            and int(report.get("process_start_count", 0)) == batch_count
            and int(report.get("process_restart_count", -1)) == 0
            and all(
                int(batch_session.get("viewport_create_count", 0)) == 1
                and int(batch_session.get("device_initialization_count", 0)) == 1
                and int(batch_session.get("device_reset_attempt_count", -1)) == 0
                and int(batch_session.get("device_reset_count", -1)) == 0
                for batch_session in sessions
            )
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _uses_direct_archive_capture(report: Mapping[str, object]) -> bool:
    return (
        report.get("schema") == "cdmw_mesh_visual_audit_archive_browser_batch_v2"
        and report.get("backend") == "d3d11_vortice_shader"
        and report.get("surface") == "archive_browser"
        and report.get("shared_package_artifacts") is True
    )


def _direct_archive_camera_matches(
    capture: Mapping[str, object],
    expected_angles: tuple[float, float],
) -> bool:
    if str(capture.get("camera_mapping", "")) != (
        "archive_object_rotation_basis_orthographic_v1"
    ):
        return False
    capture_angles = _finite_yaw_pitch(capture)
    try:
        renderer_angles = (
            float(capture.get("renderer_yaw")),
            float(capture.get("renderer_pitch")),
        )
    except (TypeError, ValueError):
        return False
    return (
        capture_angles is not None
        and all(math.isfinite(value) for value in renderer_angles)
        and _angles_match(capture_angles, expected_angles)
        and _angles_match(renderer_angles, expected_angles)
    )


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
    direct_archive_capture = _uses_direct_archive_capture(archive_report)
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
            if direct_archive_capture:
                if not _direct_archive_camera_matches(
                    archive_capture,
                    expected_angles,
                ):
                    return False
            else:
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
    direct_archive_capture = _uses_direct_archive_capture(archive_report)
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

            if direct_archive_capture:
                if not _direct_archive_camera_matches(
                    archive_capture,
                    expected_angles,
                ):
                    return False
                archive_camera = archive_capture.get("rendered_camera")
            else:
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
                if (
                    not isinstance(capture_event, Mapping)
                    or capture_event.get("ok") is not True
                ):
                    return False
                archive_camera = capture_event.get("rendered_camera")
            dotnet_camera = dotnet_capture.get("rendered_camera")
            if not isinstance(archive_camera, Mapping) or not isinstance(
                dotnet_camera, Mapping
            ):
                return False
            expected_archive_roles = (
                {"editable"} if direct_archive_capture else {"all", "replacement"}
            )
            if (
                str(archive_camera.get("role", "")).casefold()
                not in expected_archive_roles
            ):
                return False
            if str(dotnet_camera.get("role", "")).casefold() != "editable":
                return False

            archive_rendered_angles = _finite_rendered_camera_angles(archive_camera)
            dotnet_rendered_angles = _finite_rendered_camera_angles(dotnet_camera)
            if archive_rendered_angles is None or not _angles_match(
                archive_rendered_angles, expected_angles
            ):
                return False
            if dotnet_rendered_angles is None or not _angles_match(
                dotnet_rendered_angles, expected_angles
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
            if not _camera_screen_bases_match(archive_matrix, dotnet_matrix):
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


def _camera_screen_bases_match(
    archive_matrix: Sequence[float],
    dotnet_matrix: Sequence[float],
) -> bool:
    archive_basis = _camera_screen_basis(archive_matrix)
    dotnet_basis = _camera_screen_basis(dotnet_matrix)
    if archive_basis is None or dotnet_basis is None:
        return False
    return all(
        _unit_vectors_match(archive_axis, dotnet_axis)
        for archive_axis, dotnet_axis in zip(
            archive_basis,
            dotnet_basis,
            strict=True,
        )
    )


def _camera_screen_basis(
    matrix: Sequence[float],
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
] | None:
    if len(matrix) != 16:
        return None
    screen_x = _normalize_vector3((matrix[0], matrix[4], matrix[8]))
    screen_y = _normalize_vector3((matrix[1], matrix[5], matrix[9]))
    if screen_x is None or screen_y is None:
        return None
    view_direction = _normalize_vector3(_cross_vector3(screen_x, screen_y))
    if view_direction is None:
        return None
    return screen_x, screen_y, view_direction


def _normalize_vector3(
    vector: Sequence[float],
) -> tuple[float, float, float] | None:
    if len(vector) != 3:
        return None
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        return None
    length_squared = sum(value * value for value in values)
    if length_squared <= 1.0e-12:
        return None
    inverse_length = 1.0 / math.sqrt(length_squared)
    return tuple(value * inverse_length for value in values)


def _cross_vector3(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _unit_vectors_match(
    actual: Sequence[float],
    expected: Sequence[float],
) -> bool:
    cosine = sum(left * right for left, right in zip(actual, expected, strict=True))
    return cosine >= _CAMERA_BASIS_COSINE_MIN


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
