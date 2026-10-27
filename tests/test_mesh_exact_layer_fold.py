"""Pasted Geometry Layers written into their game Part by Exact PAC output."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.authoring_capability import (
    AuthoringCapability,
    AuthoringSupport,
    geometry_layer_authoring_capability,
)
from cdmw.domain.mesh.topology import TOPOLOGY_OPERATION_PASTE_COPIES
from cdmw.modding.mesh_pac_paste_fold import (
    PASTE_FOLD_BLOCKER,
    PastedPartFoldBlocked,
    exact_output_with_folded_copies,
    fold_pasted_parts,
)
from cdmw.modding.mesh_pac_topology_builder import build_pac_topology_rebuild
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from cdmw.services.mesh_rust_authoring import RustMeshValidationError
from cdmw.services.mesh_rust_contract import RUST_MESH_CANDIDATE
from tests import test_mesh_rust_authoring as rust_authoring_tests
from tests.test_mesh_pac_topology_serializer import _lower_lod_payloads, _pac_fixture

_FACE_0 = {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {"0": [0]}, "source_indices": []}


def _pasted_copy(original: ParsedMesh, *, dz: float = 0.5) -> SubMesh:
    """What Paste New Layer leaves for face 0 of Part 0, moved up by ``dz``."""
    source = original.submeshes[0]
    keep = (0, 1, 2)
    pasted = copy.deepcopy(source)
    pasted.name = f"{source.name} selection copy"
    pasted.vertices = [(x, y, z + dz) for x, y, z in (source.vertices[index] for index in keep)]
    for channel in ("uvs", "normals", "tangents", "bone_indices", "bone_weights", "shader_masks", "vertex_colors"):
        values = getattr(source, channel)
        setattr(pasted, channel, [values[index] for index in keep] if values else [])
    pasted.faces = [(0, 1, 2)]
    pasted.source_vertex_map = list(keep)
    pasted.source_vertex_offsets = [source.source_vertex_offsets[index] for index in keep]
    pasted.topology_provenance = None
    return pasted


def _with_copy(original: ParsedMesh, pasted: SubMesh) -> ParsedMesh:
    edited = copy.deepcopy(original)
    edited.submeshes.append(pasted)
    if edited.lod_levels:
        edited.lod_levels[0] = edited.submeshes
    return edited


def test_a_pasted_copy_folds_into_its_part_as_copies_of_the_original_records() -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    edited = _with_copy(original, _pasted_copy(original))

    folded, operations = fold_pasted_parts(original, edited, ())

    assert len(edited.submeshes) == 2
    assert len(folded.submeshes) == 1
    merged = folded.submeshes[0]
    assert (len(merged.vertices), len(merged.faces)) == (7, 3)
    assert merged.faces[2] == (4, 5, 6)
    assert [origin.parents for origin in merged.topology_provenance.vertex_origins[4:]] == [(0,), (1,), (2,)]
    assert merged.topology_provenance.face_origins[2] == 0
    assert operations[-1]["operation"] == TOPOLOGY_OPERATION_PASTE_COPIES
    assert operations[-1]["metadata"]["input_vertex_count"] == 4
    assert operations[-1]["metadata"]["output_vertex_count"] == 7

    rebuilt = build_pac_topology_rebuild(original, folded, data)
    reparsed = parse_pac(rebuilt, "target.pac")
    part = reparsed.submeshes[0]
    assert (len(part.vertices), len(part.faces)) == (7, 3)
    assert part.vertices[4][2] == pytest.approx(0.5, abs=1e-4)
    for index, parent in zip((4, 5, 6), (0, 1, 2)):
        record = rebuilt[part.source_vertex_offsets[index] : part.source_vertex_offsets[index] + 40]
        source_offset = original.submeshes[0].source_vertex_offsets[parent]
        source_record = data[source_offset : source_offset + 40]
        # Only the position lanes are authored; skin, UV and protected bytes are the record's.
        assert record[6:] == source_record[6:]
    assert _lower_lod_payloads(rebuilt) == _lower_lod_payloads(data)


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ("outside", "extends outside the bounds"),
        ("weights", "Weights on"),
        ("material", "no longer uses the material"),
        ("record", "not copies of game vertices"),
        ("face", "faces that are not copies"),
    ),
)
def test_a_copy_that_is_not_an_exact_record_copy_is_refused_with_its_reason(change: str, reason: str) -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    pasted = _pasted_copy(original, dz=2.0 if change == "outside" else 0.5)
    if change == "weights":
        pasted.bone_weights[0] = (1.0,)
        pasted.bone_indices[0] = (3,)
    elif change == "material":
        pasted.material = "another"
    elif change == "record":
        pasted.source_vertex_offsets[1] = 7
    elif change == "face":
        # Original vertices 0 and 1 share no face with 3 in that winding set.
        pasted.source_vertex_offsets[2] = original.submeshes[0].source_vertex_offsets[3]
    edited = _with_copy(original, pasted)

    with pytest.raises(PastedPartFoldBlocked, match=reason):
        fold_pasted_parts(original, edited, ())
    mesh, operations, refusal = exact_output_with_folded_copies(original, edited, ())
    assert mesh is edited
    assert operations == ()
    assert reason in refusal


def test_operations_on_the_copy_give_way_to_the_fold_and_keep_the_revision_chain() -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    edited = _with_copy(original, _pasted_copy(original))
    recorded = (
        {"operation": "remove_doubles_topology", "submesh_index": 0, "vertex_count": 4,
         "metadata": {"source_revision": 3, "result_revision": 4}},
        {"operation": "replace_positions_same_count", "submesh_index": 1, "vertex_count": 3},
    )

    _folded, operations = fold_pasted_parts(original, edited, recorded)

    assert [row["operation"] for row in operations] == ["remove_doubles_topology", TOPOLOGY_OPERATION_PASTE_COPIES]
    assert operations[-1]["metadata"]["source_revision"] == 4
    assert operations[-1]["metadata"]["result_revision"] == 5


@pytest.mark.parametrize(
    ("mesh_format", "lod_index", "policy", "ready", "authorable", "reason"),
    (
        ("pac", 0, "exact_game_asset", False, True, ""),
        ("pam", 0, "exact_game_asset", False, False, "PAC game files only"),
        ("pac", 1, "exact_game_asset", False, False, "LOD1 and above"),
        ("pac", 0, "free_edit_rebuild", False, False, "output folder"),
        ("pac", 0, "free_edit_rebuild", True, True, ""),
        ("pac", 0, "replacement_game_asset", False, False, "Paste has no exact writeback route"),
    ),
)
def test_layer_paste_capability_by_output_route(
    mesh_format: str, lod_index: int, policy: str, ready: bool, authorable: bool, reason: str,
) -> None:
    capability = geometry_layer_authoring_capability(
        "paste",
        mesh_format=mesh_format,
        lod_index=lod_index,
        output_policy=policy,
        free_edit_destination_ready=ready,
    )
    assert capability is not None
    assert capability.authorable is authorable
    assert reason in capability.reason


def _request(session, event: str, request_id: int, command: str | None = None, arguments=None) -> dict:
    request = rust_authoring_tests._request(session, event, request_id)
    if command is not None:
        request.update(command=command, arguments=dict(arguments or {}))
    return request


def _moved_part_candidate(session, *, request_id: int, submesh_index: int, dz: float) -> dict[str, object]:
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    submeshes = []
    for index, submesh in enumerate(mesh.submeshes):
        positions = [[x, y, z + dz] if index == submesh_index else [x, y, z] for x, y, z in submesh.vertices]
        submeshes.append({
            "positions": positions,
            "normals": [list(row) for row in submesh.normals],
            "uvs": [list(row) for row in submesh.uvs],
            "indices": [value for face in submesh.faces for value in face],
        })
    payload = {
        "schema": RUST_MESH_CANDIDATE,
        "session_id": session.session_id,
        "submeshes": submeshes,
        "selection": {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {},
                      "source_indices": [submesh_index]},
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    name = f"candidate-{request_id}-layer-fold.json"
    (session.root / name).write_bytes(data)
    return {
        "path": name,
        "data_type": "mesh_candidate_json",
        "count": len(submeshes),
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "content_type": "application/json",
    }


class ExactLayerFoldSessionTests(unittest.TestCase):
    def _create(self, root: Path):
        return rust_authoring_tests.RustMeshAuthoringTests._create(self, root)

    def _paste_copy(self, session) -> int:
        request_id = 1
        for command, arguments in (
            ("select", {"selection": _FACE_0, "operation": "replace"}),
            ("layer_copy", {"target": "face", "selection": _FACE_0}),
            ("layer_paste", {}),
        ):
            session.run_command(_request(session, "command_request", request_id, command, arguments))
            request_id += 1
        return request_id

    def test_exact_paste_move_and_finish_write_the_copy_into_its_game_part(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            try:
                state = session.state_payload(include_document=False)
                self.assertTrue(state["geometry_layers"]["paste_available"])
                request_id = self._paste_copy(session)
                transaction = _request(session, "transaction_request", request_id)
                transaction["candidate"] = _moved_part_candidate(
                    session, request_id=request_id, submesh_index=1, dz=0.5,
                )
                session.apply_candidate(transaction)
                request_id += 1
                # Exact output ignores viewport hiding, like Include.
                session.run_command(_request(
                    session, "command_request", request_id, "layer_visibility",
                    {"layer_id": "selection-copy-1", "visible": False},
                ))
                request_id += 1

                result = session.finish(_request(session, "finish_request", request_id))

                self.assertEqual("accepted", result["status"])
                session_id = session.authoritative_session_id
                self.assertEqual(2, authoritative.session_view(session_id).submesh_count)
                self.assertEqual(
                    ["base", "selection-copy-1"],
                    [layer.layer_id for layer in authoritative._session(session_id).geometry_layers],
                )
                built, report = authoritative.rebuild_result_from_snapshot(
                    authoritative.capture_export_snapshot(session_id)
                )
                self.assertEqual("pac_lod0_topology_exact_v1", report.topology_rebuild["serializer"])
                part = parse_pac(built.data, "owned-rust-authoring.pac").submeshes[0]
                self.assertEqual((7, 3), (len(part.vertices), len(part.faces)))
                self.assertAlmostEqual(0.5, part.vertices[4][2], places=3)
            finally:
                session.cancel()
                authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)

    def test_moving_a_copy_outside_its_parts_bounds_is_refused_with_the_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            try:
                request_id = self._paste_copy(session)
                revision = session.shadow_service.session_view(session.shadow_session_id).revision
                transaction = _request(session, "transaction_request", request_id)
                transaction["candidate"] = _moved_part_candidate(
                    session, request_id=request_id, submesh_index=1, dz=2.0,
                )

                with self.assertRaisesRegex(RustMeshValidationError, "extends outside the bounds"):
                    session.apply_candidate(transaction)
                self.assertEqual(revision, session.shadow_service.session_view(session.shadow_session_id).revision)
            finally:
                session.cancel()
                authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)

    def test_free_edit_copies_return_to_exact_only_when_they_fold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authoritative, session = self._create(root / "session")
            try:
                service, shadow_id = session.shadow_service, session.shadow_session_id
                service.configure_output_policy(shadow_id, "free_edit_rebuild", output_destination=root / "free-edit")
                service.apply_command(shadow_id, MeshEditCommand(
                    "select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"operation": "replace"},
                ))
                service.copy_selection(shadow_id, target="face")
                service.paste_selection(shadow_id)

                self.assertEqual(
                    "exact_game_asset",
                    service.configure_output_policy(shadow_id, "exact_game_asset").output_policy,
                )
                service.configure_output_policy(shadow_id, "free_edit_rebuild", output_destination=root / "again")
                shadow = service._session(shadow_id)
                shadow.working_mesh.submeshes[1].vertices = [
                    (x, y, z + 2.0) for x, y, z in shadow.working_mesh.submeshes[1].vertices
                ]
                with self.assertRaisesRegex(ValueError, "extends outside the bounds"):
                    service.configure_output_policy(shadow_id, "exact_game_asset")
            finally:
                session.cancel()
                authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)

    def test_the_host_refuses_layer_geometry_commands_without_a_writer(self) -> None:
        blocked = AuthoringCapability(AuthoringSupport.BLOCKED, "No writer for pasted layers here")
        with tempfile.TemporaryDirectory() as temporary:
            authoritative, session = self._create(Path(temporary) / "session")
            try:
                with patch.object(type(session), "_geometry_layer_capability", return_value=blocked):
                    for request_id, (command, arguments) in enumerate(
                        (
                            ("layer_copy", {"target": "face", "selection": _FACE_0}),
                            ("layer_paste", {}),
                            ("layer_delete", {"layer_id": "base"}),
                        ),
                        start=1,
                    ):
                        with self.assertRaisesRegex(RustMeshValidationError, "No writer for pasted layers"):
                            session.run_command(_request(session, "command_request", request_id, command, arguments))
                view = session.shadow_service.session_view(session.shadow_session_id)
                self.assertEqual((0, 1), (view.revision, view.submesh_count))
                self.assertFalse(session.shadow_service._session(session.shadow_session_id).native_clipboard_ready)
            finally:
                session.cancel()
                authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_validation_names_the_fold_refusal_first() -> None:
    from cdmw.domain.mesh.export_validation import validate_mesh_export
    from cdmw.modding.mesh_pac_paste_fold import with_paste_fold_refusal

    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    edited = _with_copy(original, _pasted_copy(original, dz=2.0))
    mesh, operations, refusal = exact_output_with_folded_copies(original, edited, ())
    report = with_paste_fold_refusal(
        validate_mesh_export(mesh, original_mesh=original, original_data=data, edit_operations=operations),
        refusal,
    )
    assert report.blockers[0].code == PASTE_FOLD_BLOCKER
    assert "extends outside the bounds" in report.blockers[0].message
