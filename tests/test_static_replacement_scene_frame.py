from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_runtime_builder import _transformed_replacement_sources
from cdmw.modding.static_mesh_scene_frame import (
    build_authoritative_static_scene_frame,
    build_static_transform_frame,
    matrix_transform_point,
    static_scene_source_identity,
)
from cdmw.modding.static_mesh_types import StaticReplacementTransform
from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin


def _mesh(path: str, vertices: list[tuple[float, float, float]]) -> ParsedMesh:
    return ParsedMesh(
        path=path,
        format="pac",
        submeshes=[SubMesh(name=Path(path).stem, vertices=vertices, faces=[])],
        total_vertices=len(vertices),
    )


def _assert_vec(actual: tuple[float, float, float], expected: tuple[float, float, float]) -> None:
    assert actual == pytest.approx(expected, abs=1.0e-7)


def test_scene_frame_is_frozen_and_carries_automatic_and_manual_components() -> None:
    original = _mesh("original.pac", [(0.0, 0.0, 0.0), (10.0, 2.0, 2.0)])
    replacement = _mesh("replacement.obj", [(0.0, 1.0, 0.0), (2.0, 2.0, 1.0)])
    transform = StaticReplacementTransform(
        alignment_mode="auto_fit_original",
        scale_to_original_length=True,
        rotate_xyz_degrees=(10.0, 20.0, 30.0),
        scale_xyz=(1.25, 0.75, 2.0),
        offset_xyz=(3.0, 4.0, 5.0),
        manual_adjustment=(0.5, -0.25, 0.125),
    )

    frame = build_authoritative_static_scene_frame(
        original,
        replacement,
        transform,
        source_identity="source-a",
        scene_generation=7,
    )

    assert frame.transform.alignment.length_scale == pytest.approx(5.0)
    assert frame.transform.manual_delta.translation == (3.0, 4.0, 5.0)
    assert frame.transform.manual_delta.rotation_degrees == (10.0, 20.0, 30.0)
    assert frame.transform.manual_delta.scale_xyz == (1.25, 0.75, 2.0)
    assert frame.transform.manual_delta.manual_adjustment == (0.5, -0.25, 0.125)
    with pytest.raises(FrozenInstanceError):
        frame.scene_generation = 8  # type: ignore[misc]


def test_scene_source_identity_detects_same_path_and_topology_geometry_swap() -> None:
    first = _mesh("replacement.obj", [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 0.0, 0.0)])
    second = _mesh("replacement.obj", [(0.0, 0.0, 0.0), (1.0, 9.0, 1.0), (2.0, 0.0, 0.0)])
    first.submeshes[0].faces = [(0, 1, 2)]
    second.submeshes[0].faces = [(0, 1, 2)]

    assert static_scene_source_identity(first) != static_scene_source_identity(second)


def test_final_runtime_vertices_and_resident_scene_matrix_are_numerically_identical() -> None:
    original = _mesh("original.pac", [(-4.0, -2.0, -1.0), (8.0, 6.0, 5.0)])
    replacement = _mesh(
        "replacement.obj",
        [(-1.0, 3.0, 0.0), (2.0, 5.0, 4.0), (0.5, 4.0, -2.0)],
    )
    transform = StaticReplacementTransform(
        alignment_mode="auto_fit_original",
        scale_to_original_length=True,
        flip_source_axis=True,
        flip_target_axis=True,
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        rotate_xyz_degrees=(17.0, -23.0, 41.0),
        scale_xyz=(1.2, 0.8, 1.5),
        offset_xyz=(2.0, -3.0, 4.0),
        manual_adjustment=(0.25, 0.5, -0.75),
    )

    frame = build_authoritative_static_scene_frame(original, replacement, transform)
    runtime = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        [],
        alignment_basis_mesh=replacement,
    )

    for source_vertex, runtime_vertex in zip(
        replacement.submeshes[0].vertices,
        runtime[0].vertices,
        strict=True,
    ):
        _assert_vec(matrix_transform_point(frame.editable.model_matrix, source_vertex), runtime_vertex)


def test_world_bounds_use_transformed_vertices_and_pivots_follow_authority() -> None:
    original = _mesh("original.pac", [(-2.0, -1.0, -3.0), (5.0, 7.0, 9.0)])
    replacement = _mesh(
        "replacement.obj",
        [(-2.0, 4.0, 1.0), (1.0, -3.0, 5.0), (6.0, 2.0, -4.0)],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        scale_to_original_length=False,
        source_anchor=(1.0, 2.0, 3.0),
        target_anchor=(10.0, 20.0, 30.0),
        rotate_xyz_degrees=(5.0, 35.0, -15.0),
        scale_xyz=(2.0, 0.5, 1.25),
        offset_xyz=(3.0, -4.0, 5.0),
    )
    frame = build_authoritative_static_scene_frame(
        original,
        replacement,
        transform,
        selection_pivot_source=(0.0, 1.0, 2.0),
    )
    transformed = [frame.transform.transform_point(vertex) for vertex in replacement.submeshes[0].vertices]
    expected_min = tuple(min(vertex[axis] for vertex in transformed) for axis in range(3))
    expected_max = tuple(max(vertex[axis] for vertex in transformed) for axis in range(3))

    _assert_vec(frame.editable.world_bounds.minimum, expected_min)
    _assert_vec(frame.editable.world_bounds.maximum, expected_max)
    _assert_vec(frame.placement_pivot, frame.transform.transform_point((1.0, 2.0, 3.0)))
    assert frame.selection_pivot is not None
    _assert_vec(frame.selection_pivot, frame.transform.transform_point((0.0, 1.0, 2.0)))


def test_grid_flat_floor_correction_and_model_matrix_share_transform_frame() -> None:
    original = _mesh("original.pac", [(-3.0, 0.0, -1.0), (3.0, 2.0, 1.0)])
    replacement = _mesh(
        "replacement.obj",
        [(-1.0, 11.0, -0.25), (1.0, 12.0, 0.25), (0.0, 15.0, 0.0)],
    )
    transform = StaticReplacementTransform(
        alignment_mode="grid_flat",
        scale_to_original_length=False,
        rotate_xyz_degrees=(0.0, 22.0, 0.0),
        offset_xyz=(4.0, 3.0, -2.0),
    )

    transform_frame = build_static_transform_frame(original, replacement, transform)
    scene_frame = build_authoritative_static_scene_frame(original, replacement, transform)

    assert scene_frame.editable.model_matrix == pytest.approx(transform_frame.effective_model_matrix)
    assert scene_frame.editable.world_bounds.minimum[1] == pytest.approx(0.0, abs=1.0e-7)
    assert scene_frame.grid_origin[1] == pytest.approx(0.0, abs=1.0e-7)


def test_comparison_offsets_remain_presentation_only() -> None:
    original = _mesh("original.pac", [(0.0, 0.0, 0.0), (4.0, 2.0, 1.0)])
    replacement = _mesh("replacement.obj", [(0.0, 0.0, 0.0), (2.0, 1.0, 1.0)])
    transform = StaticReplacementTransform(alignment_mode="auto_fit_original")
    side_by_side = build_authoritative_static_scene_frame(
        original, replacement, transform, comparison_mode="side_by_side"
    )
    overlay = side_by_side.with_protocol_context(comparison_mode="overlay")

    assert side_by_side.editable.model_matrix == overlay.editable.model_matrix
    assert side_by_side.reference.model_matrix == overlay.reference.model_matrix
    assert side_by_side.editable.world_bounds == overlay.editable.world_bounds
    assert side_by_side.reference.world_bounds == overlay.reference.world_bounds


def test_protocol_payload_declares_matrix_and_coordinate_contract() -> None:
    original = _mesh("original.pac", [(0.0, 0.0, 0.0), (4.0, 2.0, 1.0)])
    replacement = _mesh("replacement.obj", [(0.0, 0.0, 0.0), (2.0, 1.0, 1.0)])
    frame = build_authoritative_static_scene_frame(
        original,
        replacement,
        StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        source_identity="identity",
        scene_generation=3,
        interaction_mode="mesh_edit",
    )

    payload = frame.to_protocol_payload()
    assert payload["format"] == "cdmw_resident_scene_frame_v2"
    assert payload["source_identity"] == "identity"
    assert payload["scene_generation"] == 3
    assert payload["coordinate_contract"] == {
        "matrix_layout": "row_major",
        "vector_convention": "row_vector",
        "handedness": "right_handed",
        "units": "source_mesh_units",
        "multiplication_order": "source_point_then_automatic_alignment_then_manual_delta",
    }
    assert payload["interaction_mode"] == "mesh_edit"
    assert len(payload["roles"]["editable"]["model_matrix"]) == 16  # type: ignore[index]


def test_scene_ack_rejects_stale_generation_and_retains_last_acknowledged_frame() -> None:
    old_frame = object()
    candidate = object()
    state = SimpleNamespace(
        standalone_dotnet_scene_pending={
            "session_id": "session-a",
            "request_id": 4,
            "process_generation": 2,
            "source_identity": "source-a",
            "scene_generation": 8,
        },
        standalone_dotnet_scene_candidate=candidate,
        standalone_dotnet_scene_frame=old_frame,
        standalone_dotnet_scene_acknowledged_generation=7,
        standalone_dotnet_scene_acknowledged=None,
        _dotnet_session_matches=lambda _payload: True,
        _set_dotnet_status=lambda *_args, **_kwargs: None,
        _record_mesh_dotnet_event=lambda *_args, **_kwargs: None,
    )

    stale = {
        "status": "applied",
        "session_id": "session-a",
        "request_id": 3,
        "process_generation": 2,
        "source_identity": "source-a",
        "scene_generation": 7,
    }
    assert MeshEditorDotNetProtocolMixin._handle_dotnet_scene_state_ack(state, stale) is False
    assert state.standalone_dotnet_scene_pending is not None
    assert state.standalone_dotnet_scene_frame is old_frame

    rejected = {
        **stale,
        "status": "rejected",
        "request_id": 4,
        "scene_generation": 8,
        "reason": "stale_source_identity",
    }
    assert MeshEditorDotNetProtocolMixin._handle_dotnet_scene_state_ack(state, rejected) is False
    assert state.standalone_dotnet_scene_pending is None
    assert state.standalone_dotnet_scene_candidate is None
    assert state.standalone_dotnet_scene_frame is old_frame


def test_mode_only_scene_update_bypasses_active_transform_worker() -> None:
    original = _mesh("original.pac", [(0.0, 0.0, 0.0), (4.0, 2.0, 1.0)])
    replacement = _mesh("replacement.obj", [(0.0, 0.0, 0.0), (2.0, 1.0, 1.0)])
    frame = build_authoritative_static_scene_frame(
        original,
        replacement,
        StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        source_identity="identity",
        scene_generation=7,
        comparison_mode="side_by_side",
        interaction_mode="placement",
    )
    published: list[tuple[int, object]] = []
    state = SimpleNamespace(
        standalone_dotnet_scene_desired={
            "comparison_mode": "side_by_side",
            "interaction_mode": "placement",
            "gizmo_tool": "move",
        },
        standalone_dotnet_scene_thread=object(),
        standalone_dotnet_scene_candidate=None,
        standalone_dotnet_scene_frame=frame,
        standalone_dotnet_scene_request_id=3,
        standalone_dotnet_scene_generation=7,
        _standalone_dotnet_editor_process_running=lambda: True,
        _publish_dotnet_scene_frame=lambda updated, request_id: (
            published.append((int(request_id), updated)) or True
        ),
    )

    assert MeshEditorStateMixin._send_dotnet_scene_state(
        state,
        comparison_mode="replacement_only",
        interaction_mode="mesh_edit",
    )
    assert state.standalone_dotnet_scene_request_id == 4
    assert state.standalone_dotnet_scene_generation == 8
    assert len(published) == 1
    request_id, updated = published[0]
    assert request_id == 4
    assert updated.scene_generation == 8
    assert updated.comparison_mode == "replacement_only"
    assert updated.interaction_mode == "mesh_edit"
    assert updated.editable.model_matrix == frame.editable.model_matrix


def test_live_scene_update_owner_does_not_rebuild_package_or_reparse_source() -> None:
    source = Path("cdmw/ui/mesh_editor/tab_state.py").read_text(encoding="utf-8")
    start = source.index("    def _queue_dotnet_scene_frame_update")
    end = source.index("    def _handle_embedded_viewport_display_mode", start)
    live_scene_owner = source[start:end]

    assert "MeshDotNetSceneFrameWorker" in live_scene_owner
    assert "build_mesh_dotnet_experiment_package" not in live_scene_owner
    assert "export_obj" not in live_scene_owner
    assert "parse_" not in live_scene_owner
