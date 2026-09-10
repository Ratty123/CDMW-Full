from __future__ import annotations

import copy
import hashlib
import json
import struct
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from cdmw.modding.skeleton_variation_parser import _deform_positions, _deform_normals
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, RustMeshValidationError
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette
from tests.test_mesh_rust_authoring_exact_output import (
    _apply_position_edit, _candidate_reference, _open_exact_session, _request,
)


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def _appearance():
    matrices = [IDENTITY] * 8
    # Different rotations/scales plus a translation: subtracting a baked delta
    # or averaging inverse bone matrices cannot restore this mixed influence.
    matrices[3] = (0., 2., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., .2, .1, 0., 1.)
    matrices[7] = (1.2, 0., .6, 0., 0., 1., 0., 0., -.3, 0., .75, 0., -.1, .2, .15, 1.)
    return NeutralMeshAppearance("owned/head.pabc", tuple(range(8)), tuple(matrices))


def test_neutral_transform_matches_archive_preview_and_inverts_mixed_skinning():
    source = ParsedMesh(format="pac", submeshes=[SubMesh(
        name="head", vertices=[(.3, .4, .5), (.1, .2, .3)],
        normals=[(.2, .4, .8), (0., 0., 1.)],
        bone_indices=[(3, 7), (3,)], bone_weights=[(.7, .3), (1.,)],
    )])
    source.lod_levels = [source.submeshes]
    before = copy.deepcopy(source)
    appearance = _appearance()
    neutral = appearance.to_neutral(source)
    for observed, expected in zip(neutral.submeshes[0].vertices, _deform_positions(source.submeshes[0], appearance.bone_palette, appearance.skin_matrices)):
        assert observed == pytest.approx(expected)
    for observed, expected in zip(neutral.submeshes[0].normals, _deform_normals(source.submeshes[0], appearance.bone_palette, appearance.skin_matrices)):
        assert observed == pytest.approx(expected)
    assert neutral.submeshes is neutral.lod_levels[0]
    restored = appearance.to_source(neutral, source)
    assert restored.submeshes[0].vertices == source.submeshes[0].vertices
    assert restored.submeshes[0].normals == source.submeshes[0].normals
    neutral.submeshes[0].vertices[0] = tuple(x + d for x, d in zip(neutral.submeshes[0].vertices[0], (.04, -.03, .02)))
    neutral.submeshes[0].normals[0] = (0., 1., 0.)
    edited = appearance.to_source(neutral, source)
    redisplayed = appearance.to_neutral(edited)
    assert redisplayed.submeshes[0].vertices[0] == pytest.approx(neutral.submeshes[0].vertices[0])
    assert redisplayed.submeshes[0].normals[0] == pytest.approx(neutral.submeshes[0].normals[0])
    assert source == before


def test_neutral_finish_without_edits_is_byte_identical(tmp_path):
    original, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=_appearance())
    source_positions = authoritative.working_mesh(session.authoritative_session_id).submeshes[0].vertices
    document = json.loads((session.root / "document.json").read_text())
    assert json.loads(session.manifest_path.read_text())["state"]["loaded_mesh"].endswith("(neutral appearance)")
    assert session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].vertices != source_positions
    assert document["lods"][0]["submeshes"][0]["positions"] == [
        list(row) for row in session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].vertices
    ]
    outcome = session.finish(_request(session, "finish_request", 1))
    assert outcome["exact_output_validation"]["byte_identical"] is True
    assert authoritative.working_mesh(session.authoritative_session_id).submeshes[0].vertices == source_positions
    rebuilt, _report = authoritative.rebuild_result_from_snapshot(authoritative.capture_export_snapshot(session.authoritative_session_id))
    assert rebuilt.data == original


def test_neutral_move_undo_redo_and_exact_writer_preserve_displayed_edit(tmp_path):
    appearance = _appearance()
    source, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=appearance)
    before = session.shadow_service.working_mesh(session.shadow_session_id)
    old_positions = list(before.submeshes[0].vertices)
    edited_x = _apply_position_edit(session)
    edited_positions = list(session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].vertices)
    for index, command in enumerate(("undo", "redo"), 2):
        request = _request(session, "command_request", index)
        request.update(command=command, arguments={})
        session.run_command(request)
        assert session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].vertices == (old_positions if command == "undo" else edited_positions)
    outcome = session.finish(_request(session, "finish_request", 4))
    assert outcome["exact_output_validation"]["status"] == "passed"
    committed = authoritative.working_mesh(session.authoritative_session_id)
    assert appearance.to_neutral(committed).submeshes[0].vertices[0][0] == pytest.approx(edited_x)
    rebuilt, _report = authoritative.rebuild_result_from_snapshot(authoritative.capture_export_snapshot(session.authoritative_session_id))
    assert appearance.to_neutral(parse_pac(rebuilt.data)).submeshes[0].vertices[0] == pytest.approx(edited_positions[0], abs=8e-5)
    assert authoritative.capture_export_snapshot(session.authoritative_session_id).original_data == source
    reopened = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=authoritative, active_session_id=session.authoritative_session_id),
        tmp_path / "reopened", process_generation=12,
    )
    try:
        assert reopened.shadow_service.working_mesh(reopened.shadow_session_id).submeshes[0].vertices[0] == pytest.approx(edited_positions[0])
    finally:
        reopened.cancel()


def test_singular_blended_transform_blocks_neutral_editing():
    source = ParsedMesh(submeshes=[SubMesh(vertices=[(0., 0., 0.)], bone_indices=[(0, 1)], bone_weights=[(.5, .5)])])
    flipped = (-1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
    with pytest.raises(ValueError, match="singular"):
        NeutralMeshAppearance("singular.pabc", (0, 1), (IDENTITY, flipped)).to_neutral(source)


def test_unweighted_geometry_and_normals_are_unchanged():
    mesh = ParsedMesh(submeshes=[SubMesh(vertices=[(.1, .2, .3)], normals=[(.2, .3, .4)])])
    assert _appearance().to_neutral(mesh).submeshes[0].normals == mesh.submeshes[0].normals
    assert _appearance().to_source(mesh, mesh).submeshes[0].normals == mesh.submeshes[0].normals


def test_free_edit_obj_after_finish_has_the_displayed_neutral_shape(tmp_path):
    _source, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=_appearance())
    edited_x = _apply_position_edit(session)
    request = _request(session, "command_request", 2)
    request.update(command="configure_output_policy", arguments={"policy": MeshOutputPolicy.FREE_EDIT.value, "destination": str(tmp_path / "obj-output")})
    session.run_command(request)
    session.finish(_request(session, "finish_request", 3))
    result = authoritative.export_free_edit_output(session.authoritative_session_id)
    positions = [tuple(map(float, line.split()[1:])) for line in result.obj_path.read_text().splitlines() if line.startswith("v ")]
    assert positions[0][0] == pytest.approx(edited_x, abs=1e-6)


def test_host_normal_edit_uses_the_neutral_mesh_and_converts_back(tmp_path):
    appearance = _appearance()
    _source, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=appearance)
    request = _request(session, "command_request", 1)
    request.update(command="mesh_action", arguments={
        "action": "recalculate_normals",
        "selection": {"source_indices": [0]}, "params": {},
    })
    session.run_command(request)
    normals = list(session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].normals)
    session.finish(_request(session, "finish_request", 2))
    redisplayed = appearance.to_neutral(authoritative.working_mesh(session.authoritative_session_id))
    for actual, expected in zip(redisplayed.submeshes[0].normals, normals):
        assert actual == pytest.approx(expected, abs=1e-6)


def test_weight_edit_recomputes_the_inverse_from_the_edited_weights(tmp_path):
    appearance = _appearance()
    _source, authoritative, session = _open_exact_session(
        tmp_path / "edit", neutral_appearance=appearance, resolved_rig=True,
    )
    visible = session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].vertices[0]
    bones = session.state_payload(include_document=False)["skeleton"]["bones"]
    assert bones[7]["position"] == pytest.approx(appearance.skin_matrices[7][12:15])
    for index, (command, arguments) in enumerate((
        ("rig_select_bone", {"bone_index": 7}),
        ("rig_adjust_weight", {"selection": {"vertices_by_submesh": {"0": [0]}}, "delta": .1}),
    ), 1):
        request = _request(session, "command_request", index)
        request.update(command=command, arguments=arguments)
        session.run_command(request)
    session.finish(_request(session, "finish_request", 3))
    committed = authoritative.working_mesh(session.authoritative_session_id)
    assert appearance.to_neutral(committed).submeshes[0].vertices[0] == pytest.approx(visible)
    rebuilt, _report = authoritative.rebuild_result_from_snapshot(authoritative.capture_export_snapshot(session.authoritative_session_id))
    assert appearance.to_neutral(parse_pac(rebuilt.data)).submeshes[0].vertices[0] == pytest.approx(visible, abs=.002)


@pytest.mark.parametrize("command", ["refit_load_mesh", "import_editable_package"])
def test_neutral_edit_does_not_apply_its_mapping_to_a_different_source(tmp_path, command):
    _source, _authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=_appearance())
    try:
        request = _request(session, "command_request", 1)
        request.update(command=command, arguments={})
        with pytest.raises(RustMeshValidationError, match="different source"):
            session.run_command(request)
    finally:
        session.cancel()


def test_neutral_cancel_discards_edits(tmp_path):
    _source, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=_appearance())
    before = copy.deepcopy(authoritative.working_mesh(session.authoritative_session_id).submeshes[0].vertices)
    _apply_position_edit(session)
    session.cancel()
    assert authoritative.working_mesh(session.authoritative_session_id).submeshes[0].vertices == before


def test_float32_selection_transaction_does_not_create_an_edit(tmp_path):
    _source, authoritative, session = _open_exact_session(tmp_path / "edit", neutral_appearance=_appearance())
    mesh = session.shadow_service.working_mesh(session.shadow_session_id)
    reference = _candidate_reference(session, request_id=1, first_x=mesh.submeshes[0].vertices[0][0])
    path = session.root / reference["path"]
    payload = json.loads(path.read_text())
    for part in payload["submeshes"]:
        for channel in ("positions", "normals", "uvs"):
            part[channel] = [[struct.unpack("<f", struct.pack("<f", x))[0] for x in row] for row in part[channel]]
    encoded = json.dumps(payload).encode()
    path.write_bytes(encoded)
    reference.update(byte_length=len(encoded), sha256=hashlib.sha256(encoded).hexdigest().upper())
    request = _request(session, "transaction_request", 1)
    request["candidate"] = reference
    session.apply_candidate(request)
    working = session.shadow_service.working_mesh(session.shadow_session_id)
    assert working.submeshes[0].vertices == mesh.submeshes[0].vertices
    assert working.submeshes[0].normals == mesh.submeshes[0].normals
    assert session.shadow_service._session(session.shadow_session_id).edit_operations == ()
    outcome = session.finish(_request(session, "finish_request", 2))
    assert outcome["exact_output_validation"]["byte_identical"] is True


@pytest.mark.parametrize("cancel_during_variation", [False, True])
def test_archive_worker_resolves_exact_head_variation_and_keeps_authority_raw(tmp_path, cancel_during_variation):
    stem = "cd_phw_00_head_00_0111"
    family = "1_pc/2_phw"
    hashes = tuple(0xA1000000 + index for index in range(8))
    source = _with_resolvable_bone_palette(_pac_fixture(skinned=True), hashes)
    pab = bytearray(b"PAR " + bytes(18))
    struct.pack_into("<H", pab, 20, len(hashes))
    for index, bone_hash in enumerate(hashes):
        name = f"Bone{index}".encode()
        pab.extend(struct.pack("<IB", bone_hash, len(name)) + name)
        pab.extend(struct.pack("<i", -1) + struct.pack("<16f", *IDENTITY) * 4)
        pab.extend(struct.pack("<3f4f3f", 1, 1, 1, 0, 0, 0, 1, 0, 0, 0))
    pabc = bytearray(20)
    pabc[:4] = b"PAR "
    struct.pack_into("<I", pabc, 16, 2)
    for index in (3, 7):
        matrix = _appearance().skin_matrices[index]
        pabc.extend(struct.pack("<I48f", hashes[index], *(matrix + matrix + IDENTITY)))
    pabc.extend(bytes(4))
    model_path = f"character/model/{family}/head/head/{stem}.pac"
    variation_path = f"character/binary/skeletonvariation/{family}/head/head/{stem}.pabc"
    payloads = {
        model_path: source,
        f"character/model/{family}/phw_01.pab": bytes(pab),
        variation_path: bytes(pabc),
        f"character/prefab/{family}/head/head/{stem}.prefabdata_xml": (
            f'<HeadPrefabData><SkeletonName FileName="{family}/phw_01.pab"/>'
            f'<SkeletonVariationName FileName="{family}/head/head/{stem}.pabc"/>'
            '</HeadPrefabData>'
        ).encode(),
    }
    entries = [ArchiveEntry(path=path, pamt_path=tmp_path / "0.pamt", paz_file=tmp_path / "0.paz",
                            offset=index * 10000, comp_size=len(payload), orig_size=len(payload), flags=0, paz_index=0)
               for index, (path, payload) in enumerate(payloads.items())]
    worker = MeshArchiveSessionLoadWorker(
        1, entries[0], archive_entries_by_normalized_path={entry.path: (entry,) for entry in entries},
        archive_entries_by_basename={entry.basename.casefold(): (entry,) for entry in entries},
    )
    loaded, errors = [], []
    worker.loaded.connect(lambda _request, result: loaded.append(result))
    worker.error.connect(lambda _request, error: errors.append(error))

    def read_entry(entry, **_kwargs):
        if cancel_during_variation and entry.path == variation_path:
            worker.stop()
        return payloads[entry.path], False, ""

    with patch("cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data", side_effect=read_entry), patch(
        "cdmw.core.archive_mesh_appearance.read_archive_entry_data", side_effect=read_entry,
    ):
        worker.run()
    assert not errors
    if cancel_during_variation:
        assert loaded == []
        return
    assert len(loaded) == 1
    loaded = loaded[0]
    service = loaded.service
    try:
        authoritative = service._session(loaded.view.session_id)
        assert authoritative.neutral_appearance.source == variation_path
        assert authoritative.working_mesh.submeshes[0].vertices == parse_pac(source).submeshes[0].vertices
        session = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=service, active_session_id=loaded.view.session_id),
            tmp_path / "editor", process_generation=1,
        )
        try:
            neutral = session.shadow_service.working_mesh(session.shadow_session_id)
            assert neutral.submeshes[0].vertices != authoritative.working_mesh.submeshes[0].vertices
        finally:
            session.cancel()
    finally:
        service.close_edit_session(loaded.view.session_id, force_without_saving=True)
