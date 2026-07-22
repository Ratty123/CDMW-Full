from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from cdmw.domain.mesh import (
    MeshMorphDefinition,
    MeshMorphRule,
    build_weighted_morph_selection,
    generate_procedural_morph_fields,
    procedural_morph_pivot,
)
from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _part(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    *,
    material: str,
    texture: str,
) -> SubMesh:
    count = len(vertices)
    return SubMesh(
        name=name,
        material=material,
        texture=texture,
        vertices=list(vertices),
        uvs=[(float(index % 2), float((index // 2) % 2)) for index in range(count)],
        normals=[(0.0, 0.0, 1.0)] * count,
        tangents=[(1.0, 0.0, 0.0)] * count,
        faces=list(faces),
        bone_indices=[(0, 1)] * count,
        bone_weights=[(0.75, 0.25)] * count,
        source_vertex_map=list(range(count)),
        source_vertex_map_authority="test",
        source_bone_palette=(4, 8),
        source_skin_weight_layout="two",
        vertex_count=count,
        face_count=len(faces),
    )


def _driver_garment_mesh(*, garment_height: float = 0.1) -> ParsedMesh:
    driver_a = _part(
        "body-a",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
        material="skin-a",
        texture="skin-a.dds",
    )
    driver_b = _part(
        "body-b",
        [(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
        [(0, 1, 2)],
        material="skin-b",
        texture="skin-b.dds",
    )
    garment = _part(
        "shirt",
        [
            (0.0, 0.0, garment_height),
            (1.0, 0.0, garment_height),
            (0.0, 1.0, garment_height),
            (0.0, 0.0, garment_height),
            (0.0, 1.0, garment_height),
            (1.0, 0.0, garment_height),
            (2.2, 0.2, garment_height),
        ],
        [(0, 1, 2), (3, 4, 5)],
        material="shirt-mat",
        texture="shirt.dds",
    )
    untouched = _part(
        "boots",
        [(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)],
        [(0, 1, 2)],
        material="boots-mat",
        texture="boots.dds",
    )
    parts = [driver_a, driver_b, garment, untouched]
    return ParsedMesh(
        path="character.pac",
        format="pac",
        submeshes=parts,
        total_vertices=sum(len(part.vertices) for part in parts),
        total_faces=sum(len(part.faces) for part in parts),
        has_uvs=True,
        has_bones=True,
    )


def _profile_payload(mesh: ParsedMesh) -> dict[str, object]:
    fields = []
    for submesh_index in (0, 1):
        count = len(mesh.submeshes[submesh_index].vertices)
        fields.append(
            {
                "definition_id": "lift",
                "submesh_index": submesh_index,
                "vertex_indices": list(range(count)),
                "deltas": [[0.0, 0.0, 1.0]] * count,
            }
        )
    return {
        "profile": {
            "profile_id": "body",
            "name": "Body",
            "topology_fingerprint": "a" * 64,
            "definitions": [
                {
                    "definition_id": "lift",
                    "label": "Lift",
                    "category": "Body",
                    "min_percent": -100.0,
                    "max_percent": 100.0,
                    "default_percent": 0.0,
                }
            ],
            "fields": fields,
        }
    }


def _require_native() -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")


def _open(mesh: ParsedMesh) -> str:
    _require_native()
    session_id = f"native-morph-refit-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=10.0) is not None
    return session_id


def _command(session_id: str, command: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    report = mesh_native_core.native_mesh_editor_session_command(
        command,
        session_id,
        payload or {},
        timeout_seconds=15.0,
    )
    assert report is not None, f"native {command} command failed"
    return report


def _state(session_id: str) -> dict[str, object]:
    return _command(session_id, "morph_state")["morph_state"]  # type: ignore[return-value]


def _snapshot(mesh: ParsedMesh, session_id: str) -> ParsedMesh:
    result = deepcopy(mesh)
    assert mesh_native_core.export_native_mesh_editor_session_to_mesh(result, session_id, timeout_seconds=15.0)
    return result


def _change(session_id: str, value: float, phase: str, change_id: str) -> dict[str, object]:
    return _command(
        session_id,
        "morph_change",
        {
            "definition_id": "lift",
            "value": value,
            "phase": phase,
            "change_id": change_id,
        },
    )


def _assert_positions_close(
    actual: list[tuple[float, float, float]],
    expected: list[tuple[float, float, float]],
) -> None:
    assert len(actual) == len(expected)
    for actual_point, expected_point in zip(actual, expected):
        assert actual_point == pytest.approx(expected_point)


@pytest.mark.parametrize("rule_kind", ("volume", "scale", "move", "flatten", "taper", "twist"))
def test_every_rule_at_100_percent_matches_its_generated_sparse_field_in_native_readback(rule_kind: str) -> None:
    mesh = _driver_garment_mesh()
    baseline = deepcopy(mesh)
    weighted = build_weighted_morph_selection(mesh, {0: (0, 1, 2)}, feather=0, falloff="constant")
    definition = MeshMorphDefinition(
        definition_id=rule_kind,
        label=rule_kind.title(),
        category="Readback",
        vertices=weighted,
        pivot=procedural_morph_pivot(mesh, weighted),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule(
            rule_kind,
            axis="x",
            amount=30.0 if rule_kind == "twist" else 0.25,
            feather=0,
            falloff="constant",
        ),
    )
    fields = generate_procedural_morph_fields(mesh, definition)
    assert fields
    field_deltas = {
        (field.submesh_index, vertex_index): delta
        for field in fields
        for vertex_index, delta in zip(field.vertex_indices, field.deltas)
    }
    assert any(sum(component * component for component in delta) > 1.0e-20 for delta in field_deltas.values())
    session_id = _open(mesh)
    try:
        _command(
            session_id,
            "morph_upload",
            {
                "profile": {
                    "profile_id": f"readback-{rule_kind}",
                    "name": f"Readback {rule_kind}",
                    "topology_fingerprint": "b" * 64,
                    "definitions": [
                        {
                            "definition_id": rule_kind,
                            "label": rule_kind.title(),
                            "category": "Readback",
                            "min_percent": -100.0,
                            "max_percent": 100.0,
                            "default_percent": 0.0,
                        }
                    ],
                    "fields": [
                        {
                            "definition_id": field.definition_id,
                            "submesh_index": field.submesh_index,
                            "vertex_indices": list(field.vertex_indices),
                            "deltas": [list(delta) for delta in field.deltas],
                        }
                        for field in fields
                    ],
                }
            },
        )
        report = _command(
            session_id,
            "morph_change",
            {
                "definition_id": rule_kind,
                "value": 100.0,
                "phase": "end",
                "change_id": f"readback-{rule_kind}",
            },
        )
        assert report["affected_submesh_indices"] == [0]
        readback = _snapshot(mesh, session_id)
        expected = []
        for vertex_index, point in enumerate(baseline.submeshes[0].vertices):
            delta = field_deltas.get((0, vertex_index), (0.0, 0.0, 0.0))
            expected.append(tuple(point[axis] + delta[axis] for axis in range(3)))
        _assert_positions_close(readback.submeshes[0].vertices, expected)
        for submesh_index in range(1, len(readback.submeshes)):
            assert readback.submeshes[submesh_index].vertices == baseline.submeshes[submesh_index].vertices
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_resident_morph_drag_refits_selected_garment_with_one_history_entry_and_preserves_metadata() -> None:
    mesh = _driver_garment_mesh()
    garment_before = deepcopy(mesh.submeshes[2])
    session_id = _open(mesh)
    try:
        untouched_before = _snapshot(mesh, session_id).submeshes[3]
        upload = _command(session_id, "morph_upload", _profile_payload(mesh))
        driver = _command(session_id, "morph_set_driver", {"submesh_indices": [0, 1]})
        bound = _command(session_id, "morph_bind", {"garment_submesh_indices": [2]})
        begin = _change(session_id, 25.0, "begin", "drag-1")
        update = _change(session_id, 50.0, "update", "drag-1")
        end = _change(session_id, 75.0, "end", "drag-1")
        after = _snapshot(mesh, session_id)
        state_after = _state(session_id)
        undo = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        state_undo = _state(session_id)
        after_undo = _snapshot(mesh, session_id)
        redo = mesh_native_core.redo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        state_redo = _state(session_id)
        after_redo = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    assert upload["morph_state"]["profile_id"] == "body"  # type: ignore[index]
    assert driver["morph_state"]["driver_submesh_indices"] == [0, 1]  # type: ignore[index]
    refit = bound["morph_state"]["refit"]  # type: ignore[index]
    assert refit["garment_submesh_indices"] == [2]
    assert refit["bound_vertex_count"] == len(mesh.submeshes[2].vertices)
    assert refit["maximum_distance"] == pytest.approx(0.1)
    assert begin["history_published"] is True
    assert update["history_published"] is False
    assert end["history_published"] is False
    revisions = [
        upload["morph_state"]["state_revision"],  # type: ignore[index]
        driver["morph_state"]["state_revision"],  # type: ignore[index]
        bound["morph_state"]["state_revision"],  # type: ignore[index]
        begin["morph_state"]["state_revision"],  # type: ignore[index]
        update["morph_state"]["state_revision"],  # type: ignore[index]
        end["morph_state"]["state_revision"],  # type: ignore[index]
        state_undo["state_revision"],
        state_redo["state_revision"],
    ]
    assert revisions == sorted(revisions)
    assert len(revisions) == len(set(revisions))
    assert state_after["values"] == {"lift": 75}
    assert state_after["unbaked"] is True
    assert state_after["topology_blocked"] is True
    _assert_positions_close(
        after.submeshes[0].vertices,
        [(x, y, z + 0.75) for x, y, z in mesh.submeshes[0].vertices],
    )
    _assert_positions_close(
        after.submeshes[1].vertices,
        [(x, y, z + 0.75) for x, y, z in mesh.submeshes[1].vertices],
    )
    _assert_positions_close(
        after.submeshes[2].vertices,
        [(x, y, z + 0.75) for x, y, z in mesh.submeshes[2].vertices],
    )
    assert after.submeshes[2].vertices[0] == pytest.approx(after.submeshes[2].vertices[3])
    assert after.submeshes[2].vertices[1] == pytest.approx(after.submeshes[2].vertices[5])
    assert after.submeshes[2].vertices[2] == pytest.approx(after.submeshes[2].vertices[4])
    assert after.submeshes[2].faces == garment_before.faces
    assert after.submeshes[2].uvs == garment_before.uvs
    assert after.submeshes[2].bone_indices == garment_before.bone_indices
    assert after.submeshes[2].bone_weights == garment_before.bone_weights
    assert after.submeshes[2].material == garment_before.material
    assert after.submeshes[2].texture == garment_before.texture
    assert after.submeshes[2].tangents == []
    assert len(after.submeshes[2].normals) == len(garment_before.vertices)
    assert after.submeshes[3] == untouched_before
    assert undo is not None
    assert state_undo["values"] == {"lift": 0}
    _assert_positions_close(after_undo.submeshes[0].vertices, mesh.submeshes[0].vertices)
    _assert_positions_close(after_undo.submeshes[2].vertices, mesh.submeshes[2].vertices)
    assert redo is not None
    assert state_redo["values"] == {"lift": 75}
    _assert_positions_close(after_redo.submeshes[2].vertices, after.submeshes[2].vertices)


def test_residual_edit_is_retained_by_reset_while_refit_displacement_is_removed_then_bake_allows_topology() -> None:
    mesh = _driver_garment_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _profile_payload(mesh))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0, 1]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [2]})
        _change(session_id, 50.0, "end", "numeric-1")
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"vertices_by_submesh": {0: (0,)}},
            timeout_seconds=10.0,
        ) is not None
        edited = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "transform", "translate": (0.0, 0.0, 0.25)},
            timeout_seconds=15.0,
        )
        after_edit = _snapshot(mesh, session_id)
        reset = _command(session_id, "morph_reset")
        after_reset = _snapshot(mesh, session_id)
        _change(session_id, 100.0, "end", "numeric-2")
        before_bake = _snapshot(mesh, session_id)
        bake = _command(session_id, "morph_bake")
        after_bake = _snapshot(mesh, session_id)
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"faces_by_submesh": {0: (0,)}},
            timeout_seconds=10.0,
        ) is not None
        subdivided = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "subdivide", "suppress_vertex_remap_report": True},
            timeout_seconds=15.0,
        )
        state_after_topology = _state(session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    assert edited is not None
    assert after_edit.submeshes[0].vertices[0][2] == pytest.approx(0.75)
    assert after_edit.submeshes[2].vertices[0][2] == pytest.approx(0.85)
    assert reset["history_published"] is True
    assert reset["morph_state"]["values"] == {"lift": 0}  # type: ignore[index]
    assert reset["morph_state"]["unbaked"] is False  # type: ignore[index]
    assert after_reset.submeshes[0].vertices[0] == pytest.approx((0.0, 0.0, 0.25))
    assert after_reset.submeshes[0].vertices[1] == pytest.approx((1.0, 0.0, 0.0))
    _assert_positions_close(after_reset.submeshes[2].vertices, mesh.submeshes[2].vertices)
    assert bake["history_published"] is True
    assert bake["morph_state"]["values"] == {"lift": 0}  # type: ignore[index]
    assert bake["morph_state"]["unbaked"] is False  # type: ignore[index]
    _assert_positions_close(after_bake.submeshes[0].vertices, before_bake.submeshes[0].vertices)
    _assert_positions_close(after_bake.submeshes[2].vertices, before_bake.submeshes[2].vertices)
    assert subdivided is not None
    assert subdivided["topology_changed"] is True
    assert state_after_topology["profile_id"] == ""
    assert state_after_topology["driver_submesh_indices"] == []
    assert state_after_topology["refit"]["garment_submesh_indices"] == []  # type: ignore[index]


def test_unbaked_morph_blocks_topology_cancel_restores_value_and_preset_is_single_undoable_change() -> None:
    mesh = _driver_garment_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _profile_payload(mesh))
        _change(session_id, 40.0, "end", "numeric")
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"faces_by_submesh": {0: (0,)}},
            timeout_seconds=10.0,
        ) is not None
        blocked = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "subdivide", "suppress_vertex_remap_report": True},
            timeout_seconds=10.0,
        )
        state_after_rejection = _state(session_id)
        begin = _change(session_id, 70.0, "begin", "cancel-me")
        cancelled = _change(session_id, 70.0, "cancel", "cancel-me")
        preset = _command(session_id, "morph_apply_preset", {"preset_id": "strong", "values": {"lift": 90.0}})
        state_preset = _state(session_id)
        undo = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        state_undo = _state(session_id)
        redo = mesh_native_core.redo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        state_redo = _state(session_id)
        finish = _command(session_id, "morph_finish")
        after_finish = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    assert blocked is None
    assert state_after_rejection["profile_id"] == "body"
    assert state_after_rejection["values"] == {"lift": 40}
    assert begin["morph_state"]["busy"] is True  # type: ignore[index]
    assert cancelled["morph_state"]["busy"] is False  # type: ignore[index]
    assert cancelled["morph_state"]["values"] == {"lift": 40}  # type: ignore[index]
    assert preset["history_published"] is True
    assert state_preset["preset_id"] == "strong"
    assert state_preset["values"] == {"lift": 90}
    assert undo is not None
    assert state_undo["preset_id"] == ""
    assert state_undo["values"] == {"lift": 40}
    assert redo is not None
    assert state_redo["preset_id"] == "strong"
    assert state_redo["values"] == {"lift": 90}
    assert finish["morph_state"]["unbaked"] is False  # type: ignore[index]
    assert finish["morph_state"]["values"] == {"lift": 0}  # type: ignore[index]
    _assert_positions_close(
        after_finish.submeshes[0].vertices,
        [(x, y, z + 0.9) for x, y, z in mesh.submeshes[0].vertices],
    )


def test_binding_reports_far_distance_and_rejects_noneditable_indices_without_omitting_vertices() -> None:
    mesh = _driver_garment_mesh(garment_height=10.0)
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _profile_payload(mesh))
        assert mesh_native_core.native_mesh_editor_session_command(
            "morph_set_driver",
            session_id,
            {"submesh_indices": [99]},
            timeout_seconds=10.0,
        ) is None
        _command(session_id, "morph_set_driver", {"submesh_indices": [0, 1]})
        bound = _command(session_id, "morph_bind", {"garment_submesh_indices": [2]})
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    refit = bound["morph_state"]["refit"]  # type: ignore[index]
    assert refit["bound_vertex_count"] == len(mesh.submeshes[2].vertices)
    assert refit["maximum_distance"] >= 10.0
    assert refit["p95_distance"] >= 10.0
    assert refit["distance_warning"] is True
