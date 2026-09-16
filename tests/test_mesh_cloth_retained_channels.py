"""Cloth settings must not turn edits to retained parts into LOD replacement."""

import hashlib
import json
import struct
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.pac_cloth import apply_pac_cloth_rules, pac_cloth_lods
from cdmw.services.mesh_replacement_import import commit_replacement
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from tests.test_mesh_cloth_influence import apply_rule, shadow_output
from tests.test_mesh_cloth_sequences import all_cloth_fixture
from tests.test_mesh_editor_replacement_sequences import open_editor, source_variants
from tests.test_mesh_editor_replacement_regressions import _distinct_lods
from tests.test_mesh_rust_authoring_exact_output import _candidate_reference, _open_exact_session, _request
from tests.test_mesh_rust_replacement import command
from tests.test_pac_skin_extra_influences import _record


def _edit_channels(host, values):
    mesh = host.shadow_service.working_mesh(host.shadow_session_id)
    ref = _candidate_reference(host, request_id=61, first_x=mesh.submeshes[0].vertices[0][0])
    path = host.root / ref["path"]
    candidate = json.loads(path.read_bytes())
    for channel, value in values.items():
        candidate["submeshes"][0][channel][0] = value
    payload = json.dumps(candidate, separators=(",", ":")).encode()
    path.write_bytes(payload)
    ref.update(byte_length=len(payload), sha256=hashlib.sha256(payload).hexdigest().upper())
    host.apply_candidate({**_request(host, "transaction_request", 61), "candidate": ref})


@pytest.mark.parametrize("neutral", [False, True])
@pytest.mark.parametrize("channel", ["uvs", "normals"])
def test_retained_channel_edit_preserves_lower_lods_with_cloth(tmp_path, monkeypatch, neutral, channel):
    source = bytearray(all_cloth_fixture())
    for level in pac_cloth_lods(source):
        for offset in level.submeshes[0].source_vertex_offsets:
            word = struct.unpack_from("<I", source, offset + 16)[0]
            struct.pack_into("<I", source, offset + 16, word | 0x800002AB)
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=appearance)
    try:
        apply_rule(host, tmp_path, PacClothRule(.5))
        before = shadow_output(host)
        _edit_channels(host, {channel: [.375, .625] if channel == "uvs" else [0, 0, 1]})
        after = shadow_output(host)
        levels = list(zip(pac_cloth_lods(before), pac_cloth_lods(after), strict=True))
        for lod in reversed(range(len(levels))):
            original, edited = levels[lod]
            a, b = original.submeshes[0], edited.submeshes[0]
            assert a.vertices == b.vertices, f"LOD{lod} positions changed during {channel} edit"
            assert a.faces == b.faces
            for vertex, (old, new) in enumerate(zip(a.source_vertex_offsets, b.source_vertex_offsets, strict=True)):
                allowed = set(range(8, 12) if channel == "uvs" else range(16, 20)) if lod == 0 and vertex == 0 else set()
                assert all(before[old + byte] == after[new + byte] for byte in range(40) if byte not in allowed)
                normal_bits_changed = struct.unpack_from("<I", before, old + 16)[0] ^ struct.unpack_from("<I", after, new + 16)[0]
                assert normal_bits_changed & 0x800003FF == 0  # Tangent Y and handedness belong to other channels.
            if lod == 0:
                if channel == "uvs":
                    assert b.uvs[0] == (.375, .625)
                else:
                    assert b.normals[0] == pytest.approx((0., 0., 1.), abs=.002)
        command(host, "undo")
        assert shadow_output(host) == before
        command(host, "redo")
        assert shadow_output(host) == after
        host.finish(_request(host, "finish_request", 62))
        snapshot = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(snapshot)[0].data == after
        assert snapshot.original_data == source
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def _first_part_records(data):
    return [(part.vertices, part.faces, tuple(data[offset:offset + 40] for offset in part.source_vertex_offsets))
            for level in pac_cloth_lods(data) for part in level.submeshes[:1]]


@pytest.mark.parametrize("neutral", [False, True])
@pytest.mark.parametrize("first_x", [.125, 5.])
@pytest.mark.parametrize("cloth", [False, True])
def test_retained_position_edit_matches_exact_output_with_cloth_or_mod(tmp_path, monkeypatch, neutral, first_x, cloth):
    source = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=appearance)
    rule = PacClothRule(.5)

    def activate_output():
        if cloth:
            apply_rule(host, tmp_path, rule)
        else:
            key = host.state_payload()["replacement"]["parts"][0]["id"]
            command(host, "replacement_include", {"part_ids": [key], "included": True,
                "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0),
                "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})

    try:
        mesh = host.shadow_service.working_mesh(host.shadow_session_id)
        position = (first_x, *mesh.submeshes[0].vertices[0][1:])
        _edit_channels(host, {"positions": position})
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        snapshot = host._source_coordinate_snapshot(snapshot)
        geometry = host.shadow_service.rebuild_result_from_snapshot(snapshot)[0].data
        expected = apply_pac_cloth_rules(geometry, {0: rule}, appearance=appearance) if cloth else geometry
        activate_output()
        for lod, (actual, wanted) in enumerate(zip(pac_cloth_lods(shadow_output(host)), pac_cloth_lods(expected), strict=True)):
            assert actual.submeshes[0].vertices == wanted.submeshes[0].vertices, f"Cloth/Mod output changed LOD{lod} positions"
            assert actual.submeshes[0].faces == wanted.submeshes[0].faces
        assert shadow_output(host) == expected
        command(host, "undo")  # Cloth settings / Mod inclusion.
        command(host, "undo")  # Position edit.
        activate_output()
        before = shadow_output(host)
        _edit_channels(host, {"positions": position})
        assert shadow_output(host) == expected
        command(host, "undo")
        assert shadow_output(host) == before
        command(host, "redo")
        assert shadow_output(host) == expected
        host.finish(_request(host, "finish_request", 66))
        snapshot = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(snapshot)[0].data == expected
        assert snapshot.original_data == source
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("field", ["source_vertex_offsets", "source_vertex_map"])
@pytest.mark.parametrize("channel,value", [("uvs", (.375, .625)), ("vertices", (.125, 0., 0.))])
def test_retained_channel_edit_still_requires_the_exact_source_record_map(tmp_path, monkeypatch, field, channel, value):
    source = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "host")
    try:
        apply_rule(host, tmp_path, PacClothRule(.5))
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        part = snapshot.mesh.submeshes[0]
        getattr(part, channel)[0] = value
        records = list(getattr(part, field))
        records[0], records[1] = records[1], records[0]
        setattr(part, field, records)
        part.source_vertex_stride = 0  # The legacy-draft repair must not waive ownership.
        with pytest.raises(ValueError, match="source map|vertex-record offset"):
            prepare_replacement_output(snapshot)
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("legacy_draft", [False, True])
def test_retained_channels_and_weights_survive_other_part_imports_reorder_and_draft(tmp_path, monkeypatch, legacy_draft):
    source = bytearray(_distinct_lods())
    record = _record(palette=(1, 2, 3, 4, 5, 6), weights=(60, 50, 40, 30, 20, 10, 25, 20), extra=(0., 7.), gate=0)
    for level in pac_cloth_lods(source):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                for start, end in ((12, 16), (20, 36), (39, 40)):
                    source[offset + start:offset + end] = record[start:end]
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    source, service, host = _open_exact_session(tmp_path / "host", resolved_rig=True)
    paths = source_variants(tmp_path / "sources")
    with ExitStack() as stack:
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        command(host, "rig_select_bone", {"bone_index": 7})
        command(host, "rig_adjust_weight", {"selection": {"vertices_by_submesh": {"0": [0]}, "source_indices": []}, "delta": 1})
        apply_rule(host, tmp_path, PacClothRule(.5))
        mesh = host.shadow_service.working_mesh(host.shadow_session_id)
        x, y, z = mesh.submeshes[0].vertices[0]
        _edit_channels(host, {"positions": [x + 5, y, z], "uvs": [.375, .625], "normals": [0, 0, 1]})
        expected = _first_part_records(shadow_output(host))
        shadow, sid = host.shadow_service, host.shadow_session_id
        snapshot = shadow.capture_export_snapshot(sid)
        first, second = (part.part_id for part in snapshot.replacement_state.parts)
        snapshot.mesh.submeshes.reverse()
        commit_replacement(shadow, snapshot, snapshot.mesh, snapshot.replacement_state, label="Reorder parts")
        for path in (paths[1], paths[3]):
            command(host, "replacement_choose", {"scope": "selected", "source_path": str(path), "part_ids": [second]})
            command(host, "replacement_apply", {"targets": [second], "materials": "original"})
            assert _first_part_records(shadow_output(host)) == expected
        for key in (first, second):
            command(host, "replacement_include", {"part_ids": [key], "included": False})
            command(host, "replacement_include", {"part_ids": [key], "included": True})
            assert _first_part_records(shadow_output(host)) == expected
        before = shadow_output(host)
        draft = tmp_path / "draft" / "mesh_layers.json"
        shadow._session(sid).mesh_layer_project_path = draft
        shadow.retry_mesh_layer_autosave(sid)
        if legacy_draft:
            descriptor = json.loads(draft.read_text())
            manifest = draft.parent / descriptor["current_generation"] / "generation.json"
            generation = json.loads(manifest.read_text())
            for part in generation["snapshot"]["submeshes"]:
                for name in tuple(part["metadata"]):
                    if name.startswith("source_"):
                        part["metadata"].pop(name)
            manifest.write_text(json.dumps(generation))
            descriptor["current_generation_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            draft.write_text(json.dumps(descriptor))
        loaded, loaded_sid = open_editor(stack, source, "owned-rust-exact.pac", draft)
        recovered = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=loaded, active_session_id=loaded_sid),
            tmp_path / "recovered", process_generation=21)
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        assert shadow_output(recovered) == before
        command(recovered, "replacement_cloth", {"part_ids": [first], "reset": True})
        command(recovered, "undo")
        assert shadow_output(recovered) == before
        recovered.finish(_request(recovered, "finish_request", 65))
        snapshot = loaded.capture_export_snapshot(loaded_sid)
        assert loaded.rebuild_result_from_snapshot(snapshot)[0].data == before
        assert snapshot.original_data == source
