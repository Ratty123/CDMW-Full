from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

import pytest

from cdmw.domain.mesh import (
    MESH_MORPH_RULES,
    MeshMorphDefinition,
    MeshMorphRule,
    build_weighted_morph_selection,
    generate_procedural_morph_fields,
    mesh_topology_fingerprint,
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


# Derived from the rule set, so a new rule cannot ship without native readback
# proof. `radius` was added later and would otherwise have had none.
@pytest.mark.parametrize("rule_kind", MESH_MORPH_RULES)
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


def _tilt_mesh() -> ParsedMesh:
    """One driver triangle in z=0 plus two garment vertices bound to it.

    Garment vertex 0 sits above the centroid, so its closest point is strictly
    interior and its standoff is purely normal. Vertex 1 overhangs the far edge,
    so its closest point is a corner and its offset carries a tangential part.
    The two vertices are what separate the normal term from the tangential
    residual.
    """

    driver = _part(
        "body",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
        material="skin",
        texture="skin.dds",
    )
    garment = _part(
        "shirt",
        [(1.0 / 3.0, 1.0 / 3.0, 0.1), (2.0, 2.0, 0.1)],
        [(0, 1, 0)],
        material="shirt-mat",
        texture="shirt.dds",
    )
    parts = [driver, garment]
    return ParsedMesh(
        path="tilt.pac",
        format="pac",
        submeshes=parts,
        total_vertices=sum(len(part.vertices) for part in parts),
        total_faces=sum(len(part.faces) for part in parts),
        has_uvs=True,
        has_bones=True,
    )


def _tilt_profile_payload(lift: float) -> dict[str, object]:
    """A field that lifts only driver corner 0, so the bound face rotates."""

    return {
        "profile": {
            "profile_id": "tilt",
            "name": "Tilt",
            "topology_fingerprint": "b" * 64,
            "definitions": [
                {
                    "definition_id": "tilt",
                    "label": "Tilt",
                    "category": "Body",
                    "min_percent": -100.0,
                    "max_percent": 100.0,
                    "default_percent": 0.0,
                }
            ],
            "fields": [
                {
                    "definition_id": "tilt",
                    "submesh_index": 0,
                    "vertex_indices": [0],
                    "deltas": [[0.0, 0.0, lift]],
                }
            ],
        }
    }


def test_refit_standoff_rotates_with_a_tilting_driver_face_instead_of_staying_axis_pinned() -> None:
    mesh = _tilt_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
        _command(
            session_id,
            "morph_change",
            {"definition_id": "tilt", "value": 100.0, "phase": "end", "change_id": "tilt-1"},
        )
        after = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    # Driver corner 0 rises to z=0.6, so the face normal turns from (0, 0, 1) to
    # (0.6, 0.6, 1) normalised. The interior-bound garment vertex must land
    # exactly on the deformed surface point plus its 0.1 standoff along the new
    # normal; under translation-only refit it would sit at (1/3, 1/3, 0.3) with
    # no in-plane motion at all.
    scale = (0.6 * 0.6 + 0.6 * 0.6 + 1.0) ** 0.5
    normal = (0.6 / scale, 0.6 / scale, 1.0 / scale)
    surface = (1.0 / 3.0, 1.0 / 3.0, 0.2)
    assert after.submeshes[1].vertices[0] == pytest.approx(
        tuple(surface[axis] + 0.1 * normal[axis] for axis in range(3))
    )
    assert after.submeshes[1].vertices[0][0] != pytest.approx(1.0 / 3.0)


def test_refit_is_exactly_identity_at_zero_and_pure_translation_for_an_edge_bound_overhang() -> None:
    mesh = _tilt_mesh()
    garment_rest = list(mesh.submeshes[1].vertices)
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
        at_bind = _snapshot(mesh, session_id)
        _command(
            session_id,
            "morph_change",
            {"definition_id": "tilt", "value": 0.0, "phase": "end", "change_id": "zero-1"},
        )
        at_zero = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    # Vertex 1 overhangs the triangle, so its closest point is corner (1, 0, 0)
    # and most of its offset is tangential. A refit that rebuilt the vertex from
    # a normal-only height would snap that tangential part away the moment the
    # garment was bound. Binding and holding at zero must both be exact no-ops.
    _assert_positions_close(at_bind.submeshes[1].vertices, garment_rest)
    _assert_positions_close(at_zero.submeshes[1].vertices, garment_rest)


def test_residual_edit_is_retained_by_reset_while_refit_displacement_is_removed_then_bake_allows_topology() -> None:
    mesh = _driver_garment_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _profile_payload(mesh))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0, 1]})
        bound = _command(session_id, "morph_bind", {"garment_submesh_indices": [2]})
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
    # Translating only driver vertex 0 tilts the bound face, so the garment's
    # standoff turns with it instead of staying pinned to +Z: the vertex picks up
    # the in-plane motion the old translation-only refit could never produce, and
    # loses height by h * (n' - n0). Bound at barycentric (1, 0, 0) with h = 0.1,
    # the tilted normal is (0.25, 0.25, 1) / sqrt(1.125).
    assert after_edit.submeshes[2].vertices[0] == pytest.approx(
        (0.023570226039551587, 0.023570226039551587, 0.8442809041582063)
    )
    assert reset["history_published"] is True
    assert reset["morph_state"]["values"] == {"lift": 0}  # type: ignore[index]
    assert reset["morph_state"]["unbaked"] is False  # type: ignore[index]
    assert after_reset.submeshes[0].vertices[0] == pytest.approx((0.0, 0.0, 0.25))
    assert after_reset.submeshes[0].vertices[1] == pytest.approx((1.0, 0.0, 0.0))
    _assert_positions_close(after_reset.submeshes[2].vertices, mesh.submeshes[2].vertices)
    # Reset rebases onto the residual edit it just kept, so the diagnostics have
    # to describe that new rest state rather than the bind that preceded it. The
    # edit lifted driver corner 0 to z=0.25 while the garment returned to z=0.1,
    # so the vertices bound to that corner now stand 0.15 off their driver where
    # they stood 0.1 off it at bind. Reporting the bind-time figure would leave
    # the status line describing a rest state that no longer exists.
    assert bound["morph_state"]["refit"]["maximum_distance"] == pytest.approx(0.1)  # type: ignore[index]
    assert reset["morph_state"]["refit"]["maximum_distance"] == pytest.approx(0.15)  # type: ignore[index]
    assert reset["morph_state"]["refit"]["warning_distance"] == pytest.approx(  # type: ignore[index]
        (9.0 + 1.0 + 0.0625) ** 0.5 * 0.05
    )
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


def _dense_refit_grid(size: int = 28) -> ParsedMesh:
    vertices = [
        (float(column), float(row), 0.0)
        for row in range(size)
        for column in range(size)
    ]
    faces: list[tuple[int, int, int]] = []
    for row in range(size - 1):
        for column in range(size - 1):
            top_left = row * size + column
            faces.extend(
                (
                    (top_left, top_left + 1, top_left + size),
                    (top_left + 1, top_left + size + 1, top_left + size),
                )
            )
    driver = _part(
        "dense-body",
        vertices,
        faces,
        material="skin",
        texture="skin.dds",
    )
    garment = _part(
        "dense-shirt",
        [(x, y, z + 0.05) for x, y, z in vertices],
        faces,
        material="shirt",
        texture="shirt.dds",
    )
    return ParsedMesh(
        path="dense-refit.pac",
        format="pac",
        submeshes=[driver, garment],
        total_vertices=len(driver.vertices) + len(garment.vertices),
        total_faces=len(driver.faces) + len(garment.faces),
        has_uvs=True,
        has_bones=True,
    )


def test_dense_refit_binding_uses_exact_spatial_pruning_instead_of_every_triangle() -> None:
    mesh = _dense_refit_grid()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        bound = _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    refit = bound["morph_state"]["refit"]  # type: ignore[index]
    bound_vertices = len(mesh.submeshes[1].vertices)
    driver_triangles = len(mesh.submeshes[0].faces)
    exhaustive_tests = bound_vertices * driver_triangles
    assert refit["bound_vertex_count"] == bound_vertices
    assert refit["driver_triangle_count"] == driver_triangles
    assert refit["candidate_triangle_tests"] < exhaustive_tests // 10
    assert refit["maximum_distance"] == pytest.approx(0.05)


def test_refit_settings_are_per_garment_and_enabled_intensity_is_undoable() -> None:
    mesh = _driver_garment_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _profile_payload(mesh))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0, 1]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [2, 3]})
        configured = _command(
            session_id,
            "morph_configure_refit",
            {
                "garment_submesh_indices": [2],
                "enabled": True,
                "intensity_percent": 50.0,
                "mode": "surface",
                "clearance_percent": 0.0,
            },
        )
        _change(session_id, 100.0, "end", "per-garment")
        after_intensity = _snapshot(mesh, session_id)
        disabled = _command(
            session_id,
            "morph_configure_refit",
            {
                "garment_submesh_indices": [2],
                "enabled": False,
                "intensity_percent": 50.0,
                "mode": "surface",
                "clearance_percent": 0.0,
            },
        )
        after_disabled = _snapshot(mesh, session_id)
        undo = mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        after_undo = _snapshot(mesh, session_id)
        state_after_undo = _state(session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    settings = {
        item["submesh_index"]: item
        for item in configured["morph_state"]["refit"]["garment_settings"]  # type: ignore[index]
    }
    assert settings[2] == {
        "submesh_index": 2,
        "enabled": True,
        "intensity_percent": 50,
        "mode": "surface",
        "clearance_percent": 0,
    }
    assert settings[3]["intensity_percent"] == 100
    assert configured["history_published"] is True
    assert disabled["history_published"] is True
    _assert_positions_close(
        after_intensity.submeshes[2].vertices,
        [(x, y, z + 0.5) for x, y, z in mesh.submeshes[2].vertices],
    )
    _assert_positions_close(
        after_intensity.submeshes[3].vertices,
        [(x, y, z + 1.0) for x, y, z in mesh.submeshes[3].vertices],
    )
    _assert_positions_close(after_disabled.submeshes[2].vertices, mesh.submeshes[2].vertices)
    assert undo is not None
    _assert_positions_close(after_undo.submeshes[2].vertices, after_intensity.submeshes[2].vertices)
    restored = {
        item["submesh_index"]: item
        for item in state_after_undo["refit"]["garment_settings"]
    }
    assert restored[2]["enabled"] is True
    assert restored[2]["intensity_percent"] == 50


def test_rigid_refit_mode_preserves_face_local_distance_for_hard_surface_parts() -> None:
    mesh = _tilt_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
        _command(
            session_id,
            "morph_configure_refit",
            {
                "garment_submesh_indices": [1],
                "enabled": True,
                "intensity_percent": 100.0,
                "mode": "rigid",
                "clearance_percent": 0.0,
            },
        )
        _command(
            session_id,
            "morph_change",
            {"definition_id": "tilt", "value": 100.0, "phase": "end", "change_id": "rigid-tilt"},
        )
        after = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    baseline_centroid = tuple(
        sum(vertex[axis] for vertex in mesh.submeshes[0].vertices) / 3.0
        for axis in range(3)
    )
    current_driver = [(0.0, 0.0, 0.6), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    current_centroid = tuple(
        sum(vertex[axis] for vertex in current_driver) / 3.0
        for axis in range(3)
    )
    baseline_distance = sum(
        (mesh.submeshes[1].vertices[1][axis] - baseline_centroid[axis]) ** 2
        for axis in range(3)
    ) ** 0.5
    current_distance = sum(
        (after.submeshes[1].vertices[1][axis] - current_centroid[axis]) ** 2
        for axis in range(3)
    ) ** 0.5
    assert current_distance == pytest.approx(baseline_distance)


@pytest.mark.parametrize("mode", ["surface", "rigid"])
@pytest.mark.parametrize("intensity", [0.0, 100.0, 200.0])
def test_refit_clearance_repairs_initial_penetration_without_a_body_morph(mode: str, intensity: float) -> None:
    mesh = _tilt_mesh()
    mesh.submeshes[1].vertices = [(x, y, -0.002) for x, y, _ in mesh.submeshes[1].vertices]
    original = deepcopy(mesh)
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
        _command(session_id, "morph_configure_refit", {
            "garment_submesh_indices": [1], "enabled": True,
            "intensity_percent": intensity, "mode": mode, "clearance_percent": 0.0,
        })
        at_zero = _snapshot(mesh, session_id)
        fitted = _command(session_id, "morph_configure_refit", {
            "garment_submesh_indices": [1], "enabled": True,
            "intensity_percent": intensity, "mode": mode, "clearance_percent": 0.1,
        })
        after = _snapshot(mesh, session_id)
        _command(session_id, "morph_reset")
        after_reset = _snapshot(mesh, session_id)
        assert mesh_native_core.undo_native_mesh_editor_session(session_id, timeout_seconds=15.0)
        after_undo_reset = _snapshot(mesh, session_id)
        _command(session_id, "morph_bake")
        _command(session_id, "morph_reset")
        after_bake_reset = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    _assert_positions_close(at_zero.submeshes[1].vertices, original.submeshes[1].vertices)
    _assert_positions_close(after.submeshes[0].vertices, original.submeshes[0].vertices)
    _assert_positions_close(after.submeshes[1].vertices, [
        (x, y, (2.0 ** 0.5) * 0.001) for x, y, _ in original.submeshes[1].vertices
    ])
    assert fitted["morph_state"]["unbaked"] is True
    assert fitted["history_published"] is True
    _assert_positions_close(after_reset.submeshes[1].vertices, original.submeshes[1].vertices)
    _assert_positions_close(after_undo_reset.submeshes[1].vertices, after.submeshes[1].vertices)
    _assert_positions_close(after_bake_reset.submeshes[1].vertices, after.submeshes[1].vertices)


def test_refit_clearance_relief_pushes_a_stationary_garment_out_of_a_moving_driver() -> None:
    mesh = _tilt_mesh()
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1]})
        _command(
            session_id,
            "morph_configure_refit",
            {
                "garment_submesh_indices": [1],
                "enabled": True,
                "intensity_percent": 0.0,
                "mode": "surface",
                "clearance_percent": 1.0,
            },
        )
        _command(
            session_id,
            "morph_change",
            {"definition_id": "tilt", "value": 100.0, "phase": "end", "change_id": "clearance-tilt"},
        )
        after = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    normal_scale = (0.6 * 0.6 + 0.6 * 0.6 + 1.0) ** 0.5
    normal = (0.6 / normal_scale, 0.6 / normal_scale, 1.0 / normal_scale)
    surface = (1.0 / 3.0, 1.0 / 3.0, 0.2)
    signed_clearance = sum(
        (after.submeshes[1].vertices[0][axis] - surface[axis]) * normal[axis]
        for axis in range(3)
    )
    assert signed_clearance >= (2.0**0.5) * 0.01 - 1e-6


def test_surface_fit_preserves_the_gap_between_overlapping_clothing_layers() -> None:
    mesh = _tilt_mesh()
    mesh.submeshes[1].vertices = [(x, y, -.003) for x, y, _ in mesh.submeshes[1].vertices]
    outer = deepcopy(mesh.submeshes[1])
    outer.name = "outer-shell"
    outer.material = "outer-shell"
    outer.vertices = [(x, y, -.002) for x, y, _ in outer.vertices]
    mesh.submeshes.append(outer)
    mesh.total_vertices = sum(len(part.vertices) for part in mesh.submeshes)
    mesh.total_faces = sum(len(part.faces) for part in mesh.submeshes)
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", _tilt_profile_payload(0.6))
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1, 2]})
        _command(session_id, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2], "enabled": True,
            "intensity_percent": 100., "mode": "surface", "clearance_percent": .1,
        })
        after = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)
    for inside, outside in zip(after.submeshes[1].vertices, after.submeshes[2].vertices, strict=True):
        assert inside[2] >= 2.0 ** .5 * .001 - 1e-6
        assert outside[2] - inside[2] == pytest.approx(.001)


def test_surface_clearance_lifts_triangle_interiors_and_keeps_material_seams_closed() -> None:
    body = _part("body", [(0., 0., 0.), (1., 0., 0.), (1., 1., 0.), (0., 1., 0.), (.5, .5, .2)],
                 [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)], material="skin", texture="")
    first = _part("cloth-a", [(0., 0., .01), (1., 0., .01), (1., 1., .01)], [(0, 1, 2)],
                  material="cloth-a", texture="")
    second = _part("cloth-b", [(0., 0., .01), (1., 1., .01), (0., 1., .01)], [(0, 1, 2)],
                   material="cloth-b", texture="")
    mesh = ParsedMesh(path="curved-body.pac", format="pac", submeshes=[body, first, second],
                      total_vertices=11, total_faces=6)
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [], "fields": [],
        }})
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        _command(session_id, "morph_bind", {"garment_submesh_indices": [1, 2]})
        _command(session_id, "morph_configure_refit", {
            "garment_submesh_indices": [1, 2], "enabled": True,
            "intensity_percent": 100., "mode": "surface", "clearance_percent": .1,
        })
        after = _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    _assert_positions_close(after.submeshes[0].vertices, body.vertices)
    assert after.submeshes[1].vertices[0] == pytest.approx(after.submeshes[2].vertices[0])
    assert after.submeshes[1].vertices[2] == pytest.approx(after.submeshes[2].vertices[1])
    for part in after.submeshes[1:]:
        assert part.faces == [(0, 1, 2)]
        for weights in ((.5, .5, 0.), (0., .5, .5), (.5, 0., .5), (1/3, 1/3, 1/3)):
            x, y, z = (sum(v[axis] * w for v, w in zip(part.vertices, weights)) for axis in range(3))
            assert z >= .4 * min(x, y, 1 - x, 1 - y), "garment triangle still crosses the body roof"


def _initial_surface_fit(mesh: ParsedMesh) -> ParsedMesh:
    session_id = _open(mesh)
    try:
        _command(session_id, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [], "fields": [],
        }})
        _command(session_id, "morph_set_driver", {"submesh_indices": [0]})
        garments = list(range(1, len(mesh.submeshes)))
        _command(session_id, "morph_bind", {"garment_submesh_indices": garments})
        _command(session_id, "morph_configure_refit", {
            "garment_submesh_indices": garments, "enabled": True,
            "intensity_percent": 100., "mode": "surface", "clearance_percent": .1,
        })
        return _snapshot(mesh, session_id)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)


def test_surface_fit_keeps_a_coarse_shell_outside_a_detailed_lining() -> None:
    grid = [(x * .1, y * .1) for y in range(-2, 3) for x in range(-2, 3)]
    faces = [(a, a + 1, a + 6) for a in range(20) if a % 5 < 4]
    faces += [(a, a + 6, a + 5) for a in range(20) if a % 5 < 4]
    body = _part("body", [
        (x, y, .06 * max(0., 1. - math.hypot(x - .04, y - .04) / .14)) for x, y in grid
    ], faces, material="skin", texture="")
    lining = _part("lining", [(x, y, -.003) for x, y in grid], faces, material="lining", texture="")
    shell = _part("shell", [(-.2, -.2, .001), (.2, -.2, .001), (.2, .2, .001), (-.2, .2, .001)],
                  [(0, 1, 2), (0, 2, 3)], material="shell", texture="")
    mesh = ParsedMesh(path="layered-fit.pac", format="pac", submeshes=[body, lining, shell],
                      total_vertices=54, total_faces=66)
    fitted = _initial_surface_fit(mesh)
    checked = 0
    for x, y, z in fitted.submeshes[1].vertices:
        for face in shell.faces:
            a, b, c = [fitted.submeshes[2].vertices[index] for index in face]
            ab = tuple(b[axis] - a[axis] for axis in range(3))
            ac = tuple(c[axis] - a[axis] for axis in range(3))
            determinant = ab[0] * ac[1] - ab[1] * ac[0]
            u = ((x - a[0]) * ac[1] - (y - a[1]) * ac[0]) / determinant
            v = (ab[0] * (y - a[1]) - ab[1] * (x - a[0])) / determinant
            if u >= -1e-6 and v >= -1e-6 and u + v <= 1. + 1e-6:
                assert a[2] + u * ab[2] + v * ac[2] - z >= .002, "lining crosses the coarse outer shell"
                checked += 1
                break
    assert checked >= 9
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_does_not_pull_clear_lining_toward_a_lifted_outer_shell() -> None:
    grid = [(x * .05, y * .05) for y in range(-2, 3) for x in range(-4, 5)]
    faces = [(a, a + 1, a + 10) for a in range(36) if a % 9 < 8]
    faces += [(a, a + 10, a + 9) for a in range(36) if a % 9 < 8]
    body = _part("body", [
        (x, y, .06 * max(0., 1. - math.hypot(x + .1, y) / .075)) for x, y in grid
    ], faces, material="skin", texture="")
    lining = _part("clear-lining", [
        (x, y, .006) for x, y in ((.12, -.035), (.18, -.035), (.18, .035), (.12, .035))
    ], [(0, 1, 2), (0, 2, 3)], material="lining", texture="")
    shell = _part("coarse-shell", [
        (x, y, .012) for x, y in ((-.2, -.1), (.2, -.1), (.2, .1), (-.2, .1))
    ], [(0, 1, 2), (0, 2, 3)], material="shell", texture="")
    mesh = ParsedMesh(path="clear-lining.pac", format="pac", submeshes=[body, lining, shell],
                      total_vertices=53, total_faces=68)
    fitted = _initial_surface_fit(mesh)
    _assert_positions_close(fitted.submeshes[1].vertices, lining.vertices)
    assert max(p[2] for p in fitted.submeshes[2].vertices) > .06
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_limits_stretch_around_a_folded_sleeve_opening() -> None:
    def rings(name, heights, radii, segments, bulge):
        vertices = []
        for y, radius in zip(heights, radii, strict=True):
            for index in range(segments):
                angle = 2. * math.pi * index / segments
                r = radius + bulge * math.exp(-((y - .22) / .06) ** 2) * max(0., math.cos(angle)) ** 12
                vertices.append((r * math.cos(angle), y, r * math.sin(angle)))
        faces = []
        for ring in range(len(heights) - 1):
            for index in range(segments):
                a = ring * segments + index
                b = (ring + 1) * segments + index
                c = ring * segments + (index + 1) % segments
                d = (ring + 1) * segments + (index + 1) % segments
                faces.extend(((a, b, d), (a, d, c)))
        return _part(name, vertices, faces, material=name, texture="")

    body = rings("arm", (0., .15, .22, .3, .45, .6), (.1,) * 6, 32, .075)
    cuff = rings("folded-cuff", (.18, .185, .2, .27, .4), (.145, .135, .13, .13, .15), 48, 0.)
    mesh = ParsedMesh(path="cuff-fit.pac", format="pac", submeshes=[body, cuff],
                      total_vertices=len(body.vertices) + len(cuff.vertices), total_faces=len(body.faces) + len(cuff.faces))
    fitted = _initial_surface_fit(mesh)
    edges = {tuple(sorted((face[i], face[(i + 1) % 3]))) for face in cuff.faces for i in range(3)}
    for a, b in edges:
        before = math.dist(cuff.vertices[a], cuff.vertices[b])
        after = math.dist(fitted.submeshes[1].vertices[a], fitted.submeshes[1].vertices[b])
        assert after <= before * 1.6 + 1e-6, "a local fit correction stretches the cuff into a spike"
    assert fitted.submeshes[1].faces == cuff.faces
    assert fitted.submeshes[1].uvs == cuff.uvs
    assert fitted.submeshes[1].bone_weights == cuff.bone_weights
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def _refit_tube_part(name, radius, offset, heights, segments, caps=False):
    vertices = [
        (offset + radius * math.cos(i * 2. * math.pi / segments), y,
         radius * math.sin(i * 2. * math.pi / segments))
        for y in heights for i in range(segments)
    ]
    faces = []
    for ring in range(len(heights) - 1):
        for i in range(segments):
            a = ring * segments + i
            b = a + segments
            c = ring * segments + (i + 1) % segments
            d = c + segments
            faces.extend(((a, b, d), (a, d, c)))
    if caps:
        for ring, reverse in ((0, False), (len(heights) - 1, True)):
            center = len(vertices)
            vertices.append((offset, heights[ring], 0.))
            for i in range(segments):
                a = ring * segments + i
                b = ring * segments + (i + 1) % segments
                faces.append((center, b, a) if reverse else (center, a, b))
    return _part(name, vertices, faces, material=name, texture="")


def test_surface_fit_wraps_a_shifted_sleeve_around_the_arm_without_inverting_it() -> None:
    body = _refit_tube_part("arm", .08, 0., (0., .1, .2, .3, .4, .5), 64, True)
    sleeve = _refit_tube_part("shifted-sleeve", .065, .07, (.1, .15, .2, .25, .3, .35, .4), 32)
    mesh = ParsedMesh(path="shifted-sleeve.pac", format="pac", submeshes=[body, sleeve],
                      total_vertices=len(body.vertices) + len(sleeve.vertices),
                      total_faces=len(body.faces) + len(sleeve.faces))
    fitted = _initial_surface_fit(mesh)
    positions = fitted.submeshes[1].vertices
    for ring in range(7):
        winding = 0.
        for i in range(32):
            a = positions[ring * 32 + i]
            b = positions[ring * 32 + (i + 1) % 32]
            winding += math.atan2(a[0] * b[2] - a[2] * b[0], a[0] * b[0] + a[2] * b[2])
        assert winding == pytest.approx(2. * math.pi), "the sleeve moved off the arm instead of wrapping it"
    edges = {tuple(sorted((face[i], face[(i + 1) % 3]))) for face in sleeve.faces for i in range(3)}
    for a, b in edges:
        assert math.dist(positions[a], positions[b]) <= 1.6 * math.dist(sleeve.vertices[a], sleeve.vertices[b])
        midpoint = tuple((positions[a][axis] + positions[b][axis]) * .5 for axis in range(3))
        assert math.hypot(midpoint[0], midpoint[2]) >= .0803
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


@pytest.mark.parametrize("caps", (False, True))
def test_surface_fit_does_not_wrap_a_thin_attachment_around_the_arm(caps) -> None:
    body = _refit_tube_part("arm", .08, 0., (0., .1, .2, .3, .4, .5), 64, True)
    attachment = _refit_tube_part("thin-attachment", .008, .025, (.1, .15, .2, .25, .3, .35, .4), 12, caps)
    mesh = ParsedMesh(path="thin-attachment.pac", format="pac", submeshes=[body, attachment],
                      total_vertices=len(body.vertices) + len(attachment.vertices),
                      total_faces=len(body.faces) + len(attachment.faces))
    fitted = _initial_surface_fit(mesh)
    positions = fitted.submeshes[1].vertices
    assert min(p[0] for p in positions) > .06, "a narrow attachment should leave the body on its original side"
    edges = {tuple(sorted((face[i], face[(i + 1) % 3]))) for face in attachment.faces for i in range(3)}
    for a, b in edges:
        assert math.dist(positions[a], positions[b]) <= 1.6 * math.dist(attachment.vertices[a], attachment.vertices[b])
        midpoint = tuple((positions[a][axis] + positions[b][axis]) * .5 for axis in range(3))
        assert math.hypot(midpoint[0], midpoint[2]) >= .0803
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_does_not_couple_clothes_on_opposing_body_regions() -> None:
    square = [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]
    body = _part("two-nearby-body-regions", [(x, y, z) for x in (0., .02) for y, z in square],
                 [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)], material="skin", texture="")
    sleeve = _part("sleeve", [(-.008, y * .4, z * .4) for y, z in square],
                   [(0, 1, 2), (0, 2, 3)], material="sleeve", texture="")
    vest = _part("vest", [(.017, y * .4, z * .4) for y, z in square],
                 [(0, 2, 1), (0, 3, 2)], material="vest", texture="")
    mesh = ParsedMesh(path="adjacent-regions.pac", format="pac", submeshes=[body, sleeve, vest],
                      total_vertices=16, total_faces=8)
    fitted = _initial_surface_fit(mesh)
    assert all(point[0] >= .0014 for point in fitted.submeshes[1].vertices)
    _assert_positions_close(fitted.submeshes[2].vertices, vest.vertices)


@pytest.mark.parametrize("bulge", [.03, .06])
def test_surface_fit_localizes_contact_without_inflating_clear_clothing(bulge: float) -> None:
    grid = [(x * .05, y * .05) for y in range(-2, 3) for x in range(-4, 5)]
    faces = [(a, a + 1, a + 10) for a in range(36) if a % 9 < 8]
    faces += [(a, a + 10, a + 9) for a in range(36) if a % 9 < 8]
    body = _part("body", [
        (x, y, bulge * max(0., 1. - math.hypot(x + .1, y) / .075)) for x, y in grid
    ], faces, material="skin", texture="")
    cloth = _part("clothing", [(x, y, .008) for x, y in grid], faces, material="cloth", texture="")
    mesh = ParsedMesh(path="local-fit.pac", format="pac", submeshes=[body, cloth],
                      total_vertices=90, total_faces=128)
    fitted = _initial_surface_fit(mesh)
    for before, after in zip(cloth.vertices, fitted.submeshes[1].vertices, strict=True):
        if before[0] >= .1:
            assert math.dist(before, after) < .001, "contact elsewhere inflates already-clear clothing"
    assert max(vertex[2] for vertex in fitted.submeshes[1].vertices) > bulge
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_does_not_pull_a_panel_across_an_air_gap_to_another_body_region() -> None:
    vertices = []
    faces = []
    for left, right in ((0., .1), (.3, .4)):
        start = len(vertices)
        vertices.extend((x, y, z) for x in (left, right) for y in (-.5, .5) for z in (-.5, .5))
        for quad in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            center = len(vertices)
            vertices.append(tuple(sum(vertices[start + index][axis] for index in quad) / 4. for axis in range(3)))
            faces.extend((start + quad[i], start + quad[(i + 1) % 4], center) for i in range(4))
    body = _part("separated-body-regions", vertices, faces, material="skin", texture="")
    cloth = _part("panel", [(.098, y, z) for y, z in ((-.2, -.2), (.2, -.2), (.2, .2), (-.2, .2))],
                  [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    mesh = ParsedMesh(path="region-fit.pac", format="pac", submeshes=[body, cloth],
                      total_vertices=len(vertices) + 4, total_faces=len(faces) + 2)
    fitted = _initial_surface_fit(mesh)
    assert all(.1 < point[0] < .11 for point in fitted.submeshes[1].vertices), "a remote body region pulled the panel through the gap"
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


@pytest.mark.parametrize("panel_x", [.08, .11])
def test_surface_fit_clears_overlapping_body_volumes(panel_x: float) -> None:
    vertices = []
    faces = []
    for left, right in ((-.1, .1), (.05, .25)):
        start = len(vertices)
        vertices.extend((x, y, z) for x in (left, right) for y in (-.1, .1) for z in (-.1, .1))
        for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            faces.extend(((start + a, start + b, start + c), (start + a, start + c, start + d)))
    body = _part("overlapping-body-regions", vertices, faces, material="skin", texture="")
    panel = _part("underarm-panel", [(panel_x, y, z) for y, z in ((.06, -.01), (.08, -.01), (.08, .01), (.06, .01))],
                  [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    mesh = ParsedMesh(path="overlap-fit.pac", format="pac", submeshes=[body, panel],
                      total_vertices=20, total_faces=26)
    fitted = _initial_surface_fit(mesh)
    for point in fitted.submeshes[1].vertices:
        assert point[1] > .1, "the nearest body face is internal to another body region"
        assert abs(point[0] - panel_x) < .02, "the panel crossed the body instead of taking the nearby exit"
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_ignores_a_remote_open_body_shell() -> None:
    vertices = []
    faces = []
    quads = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    for box, (left, right) in enumerate(((-.1, 0.), (.1, .3))):
        start = len(vertices)
        vertices.extend((x, y, z) for x in (left, right) for y in (-.1, .1) for z in (-.1, .1))
        for a, b, c, d in quads[1 if box else 0:]:
            faces.extend(((start + a, start + b, start + c), (start + a, start + c, start + d)))
    body = _part("body-with-an-open-shell", vertices, faces, material="skin", texture="")
    panel = _part("clear-panel", [(.002, y, z) for y, z in ((-.02, -.02), (.02, -.02), (.02, .02), (-.02, .02))],
                  [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    mesh = ParsedMesh(path="open-shell-fit.pac", format="pac", submeshes=[body, panel],
                      total_vertices=20, total_faces=24)
    fitted = _initial_surface_fit(mesh)
    _assert_positions_close(fitted.submeshes[1].vertices, panel.vertices)
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def test_surface_fit_clears_a_gap_narrower_than_the_requested_clearance() -> None:
    vertices = []
    faces = []
    for left, right in ((-.05, 0.), (.0001, .05)):
        start = len(vertices)
        vertices.extend((x, y, z) for x in (left, right) for y in (-.02, .02) for z in (-.02, .02))
        for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            faces.extend(((start + a, start + b, start + c), (start + a, start + c, start + d)))
    body = _part("nearly-touching-body-regions", vertices, faces, material="skin", texture="")
    panel = _part("pinched-panel", [(.00005, y, z) for y, z in ((.015, -.001), (.018, -.001), (.018, .001), (.015, .001))],
                  [(0, 1, 2), (0, 2, 3)], material="cloth", texture="")
    mesh = ParsedMesh(path="pinched-fit.pac", format="pac", submeshes=[body, panel],
                      total_vertices=20, total_faces=26)
    fitted = _initial_surface_fit(mesh)
    assert all(point[1] >= .0201 for point in fitted.submeshes[1].vertices), "clearance corrections bounce between the two surfaces"
    assert all(abs(point[0]) < .01 for point in fitted.submeshes[1].vertices)
    _assert_positions_close(fitted.submeshes[0].vertices, body.vertices)


def _seed_refit_snapshot_session(mesh, source_session):
    _command(source_session, "morph_upload", _profile_payload(mesh))
    _command(source_session, "morph_set_driver", {"submesh_indices": [0, 1]})
    _command(source_session, "morph_bind", {"garment_submesh_indices": [2]})
    _command(
        source_session,
        "morph_configure_refit",
        {
            "garment_submesh_indices": [2],
            "enabled": True,
            "intensity_percent": 125.0,
            "mode": "rigid",
            "clearance_percent": 1.0,
        },
    )
    _change(source_session, 75.0, "end", "snapshot-source")


def test_morph_runtime_snapshot_is_file_backed_exact_and_restores_without_recomposition() -> None:
    mesh = _driver_garment_mesh()
    source_session = _open(mesh)
    target_session = ""
    snapshot: dict[str, object] | None = None
    try:
        _seed_refit_snapshot_session(mesh, source_session)
        source_geometry = _snapshot(mesh, source_session)
        snapshot = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(
            source_session,
            timeout_seconds=15.0,
        )
        assert snapshot is not None
        snapshot_path = Path(str(snapshot["path"]))
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_document = json.loads(snapshot_bytes)
        runtime = snapshot_document["runtime"]
        refit = runtime["refit"]

        assert snapshot["schema"] == "cdmw_mesh_editor_morph_runtime_snapshot_v1"
        assert snapshot["source_session_id"] == source_session
        assert snapshot["byte_length"] == len(snapshot_bytes)
        assert snapshot["sha256"] == hashlib.sha256(snapshot_bytes).hexdigest()
        assert snapshot["topology_digest"] == snapshot_document["topology_digest"]
        assert snapshot["topology_digest"] == mesh_topology_fingerprint(mesh)
        assert snapshot["retained_bytes"] == snapshot_document["retained_bytes"]
        assert snapshot_document["topology_digest_algorithm"] == "sha256"
        assert runtime["profile"]["fields"][0]["deltas"] == [[0, 0, 1]] * 3
        assert runtime["values"] == {"lift": 75}
        assert {item["submesh_index"] for item in runtime["current_layer"]} == {0, 1, 2}
        assert {item["submesh_index"] for item in refit["driver_baseline_positions"]} == {0, 1}
        assert len(refit["bindings"]) == len(mesh.submeshes[2].vertices)
        assert all(
            {
                "driver_vertices",
                "barycentric",
                "distance",
                "baseline_normal",
                "normal_height",
                "rigid_local_offset",
                "rigid_frame_valid",
            }.issubset(binding)
            for binding in refit["bindings"]
        )
        assert refit["garment_settings"] == [
            {
                "submesh_index": 2,
                "enabled": True,
                "intensity_percent": 125,
                "mode": "rigid",
                "clearance_percent": 1,
            }
        ]

        restored_source = mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            source_session,
            snapshot,
            timeout_seconds=15.0,
        )
        assert restored_source is not None
        assert restored_source["geometry_recomposed"] is False
        assert restored_source["history_cleared"] is True
        assert restored_source["gesture_cleared"] is True
        after_source_restore = _snapshot(mesh, source_session)
        for index in range(len(source_geometry.submeshes)):
            _assert_positions_close(
                after_source_restore.submeshes[index].vertices,
                source_geometry.submeshes[index].vertices,
            )
        assert mesh_native_core.undo_native_mesh_editor_session(
            source_session,
            timeout_seconds=10.0,
        ) is None

        mesh_native_core.close_native_mesh_editor_session(source_session)
        source_session = ""
        mesh_native_core.invalidate_native_mesh_session_submeshes(
            source_geometry,
            range(len(source_geometry.submeshes)),
        )
        target_session = _open(source_geometry)
        _command(target_session, "morph_upload", _profile_payload(source_geometry))
        _change(target_session, 0.0, "end", "target-history")
        before_restore = _snapshot(source_geometry, target_session)
        restored_target = mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            target_session,
            snapshot,
            timeout_seconds=15.0,
        )
        after_restore = _snapshot(source_geometry, target_session)
        state = _state(target_session)

        assert restored_target is not None
        assert restored_target["geometry_recomposed"] is False
        for index in range(len(before_restore.submeshes)):
            _assert_positions_close(
                after_restore.submeshes[index].vertices,
                before_restore.submeshes[index].vertices,
            )
        assert state["profile_id"] == "body"
        assert state["values"] == {"lift": 75}
        assert state["refit"]["bound_vertex_count"] == len(mesh.submeshes[2].vertices)  # type: ignore[index]
        assert state["refit"]["garment_settings"] == [  # type: ignore[index]
            {
                "submesh_index": 2,
                "enabled": True,
                "intensity_percent": 125,
                "mode": "rigid",
                "clearance_percent": 1,
            }
        ]
        assert mesh_native_core.undo_native_mesh_editor_session(
            target_session,
            timeout_seconds=10.0,
        ) is None

        _change(target_session, 50.0, "end", "after-restore")
        after_change = _snapshot(source_geometry, target_session)
        for driver_index in (0, 1):
            _assert_positions_close(
                after_change.submeshes[driver_index].vertices,
                [(x, y, z + 0.5) for x, y, z in mesh.submeshes[driver_index].vertices],
            )
        _assert_positions_close(
            after_change.submeshes[2].vertices,
            [(x, y, z + 0.625) for x, y, z in mesh.submeshes[2].vertices],
        )
    finally:
        if source_session:
            mesh_native_core.close_native_mesh_editor_session(source_session)
        if target_session:
            mesh_native_core.close_native_mesh_editor_session(target_session)
        if snapshot is not None:
            snapshot_path = Path(str(snapshot["path"]))
            assert mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(
                snapshot,
                timeout_seconds=10.0,
            )
            assert not snapshot_path.exists()


def test_morph_runtime_snapshot_rejects_busy_capture_and_topology_mismatch_atomically() -> None:
    mesh = _driver_garment_mesh()
    source_session = _open(mesh)
    target_session = ""
    snapshot: dict[str, object] | None = None
    try:
        _command(source_session, "morph_upload", _profile_payload(mesh))
        _change(source_session, 25.0, "begin", "busy-snapshot")
        assert mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(
            source_session,
            timeout_seconds=10.0,
        ) is None
        assert _state(source_session)["busy"] is True
        _change(source_session, 25.0, "cancel", "busy-snapshot")
        snapshot = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(
            source_session,
            timeout_seconds=15.0,
        )
        assert snapshot is not None

        mismatched = deepcopy(mesh)
        mismatched.submeshes[0].faces[0] = (0, 2, 1)
        mesh_native_core.invalidate_native_mesh_session_submeshes(
            mismatched,
            range(len(mismatched.submeshes)),
        )
        target_session = _open(mismatched)
        before_state = _state(target_session)
        before_geometry = _snapshot(mismatched, target_session)
        assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            target_session,
            snapshot,
            timeout_seconds=15.0,
        ) is None
        after_state = _state(target_session)
        after_geometry = _snapshot(mismatched, target_session)

        assert after_state == before_state
        for index in range(len(before_geometry.submeshes)):
            _assert_positions_close(
                after_geometry.submeshes[index].vertices,
                before_geometry.submeshes[index].vertices,
            )
            assert after_geometry.submeshes[index].faces == before_geometry.submeshes[index].faces
    finally:
        mesh_native_core.close_native_mesh_editor_session(source_session)
        if target_session:
            mesh_native_core.close_native_mesh_editor_session(target_session)
        if snapshot is not None:
            assert mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(
                snapshot,
                timeout_seconds=10.0,
            )
