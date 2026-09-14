"""Lossless part preservation and placement through the production editor services."""

from dataclasses import replace
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest

from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import (
    _find_pac_descriptors, _parse_pac_geometry_section, _parse_par_sections, parse_mesh,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_replacement_import import (
    initial_replacement_state, prepare_import, compose_import, commit_replacement,
    reset_or_fit_import, set_part_inclusion,
)
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_editor_replacement import editor, source_obj
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_rust_authoring_exact_output import _request, _candidate_reference
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original


def _import(service, sid, path):
    snapshot = service.capture_export_snapshot(sid)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, path, target_part_ids=(key,))
    candidate, state = compose_import(pending, (key,))
    commit_replacement(service, snapshot, candidate, state, label="Import replacement")
    return service.capture_export_snapshot(sid)


@pytest.mark.parametrize("influence_count", [7, 8])
def test_mod_toggle_preserves_original_extra_skin_influences(tmp_path, influence_count):
    from tests.test_pac_skin_extra_influences import _record

    data, _ = _minimal_two_part_pac_original()
    source = bytearray(data)
    original = parse_mesh(data, "character/model/hair/owned.pac")
    for part in original.submeshes:
        for offset in part.source_vertex_offsets:
            source[offset + 28] = 255
    skin = _record(palette=(1, 2, 3, 4, 5, 6),
                   weights=(60, 50, 40, 30, 20, 10, 25, 20 if influence_count == 8 else 0),
                   extra=(0., 7.), gate=0)
    for offset in original.submeshes[1].source_vertex_offsets:
        source[offset + 12:offset + 16] = skin[12:16]
        source[offset + 20:offset + 36] = skin[20:36]
        source[offset + 39] = skin[39]
    source = bytes(source)
    original = parse_mesh(source, original.path)
    assert len(original.submeshes[1].bone_indices[0]) == influence_count
    original._cdmw_original_data = source
    service = MeshService()
    sid = service.open_edit_session(original).session_id
    host = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=sid),
        tmp_path / "host", process_generation=1,
    )
    try:
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        state = initial_replacement_state(before)
        keys = [part.part_id for part in state.parts]
        entry = ArchiveEntry(original.path, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
        context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        for selected in ([keys[1]], keys):
            for included in (False, True):
                command(host, "replacement_include", {"part_ids": selected, "included": included,
                    "_archive_entry": entry, "_archive_dependencies": context})
                snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
                assert snapshot.hair_state is None
                assert snapshot.mesh.submeshes[1].bone_weights == before.mesh.submeshes[1].bone_weights
                assert snapshot.mesh.submeshes[1].vertices == before.mesh.submeshes[1].vertices
                bundle = prepare_replacement_output(snapshot)
                if included:
                    assert bundle.data == source
                else:
                    parsed = parse_mesh(bundle.data, original.path)
                    assert len(parsed.submeshes[1].vertices) == 3
                    for offset in parsed.submeshes[1].source_vertex_offsets:
                        assert bundle.data[offset + 12:offset + 16] == skin[12:16]
                        assert bundle.data[offset + 20:offset + 36] == skin[20:36]
                        assert bundle.data[offset + 39] == skin[39]
        host.finish(_request(host, "finish_request", 9))
        assert prepare_replacement_output(service.capture_export_snapshot(sid)).data == source
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(sid)


@pytest.mark.parametrize("fit", [False, True])
def test_reset_and_fit_after_rotation_restore_exported_authored_normals(editor, tmp_path, fit):
    service, sid = editor
    host = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=sid),
        tmp_path / "host", process_generation=1,
    )
    try:
        path = source_obj(tmp_path)
        # An explicit normal unlike the face normal proves we retain authored shading.
        path.write_text(path.read_text().replace("f 1 2 3", "vn 0 1 0\nf 1//1 2//1 3//1"))
        entry = ArchiveEntry(service.working_mesh(sid).path, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
        context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        result = command(host, "replacement_choose", {
            "source_path": str(path), "_archive_entry": entry, "_archive_dependencies": context,
        })
        key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
        command(host, "replacement_apply", {"targets": [key]})
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        reference = _candidate_reference(host, request_id=31, first_x=12)
        payload = json.loads((host.root / reference["path"]).read_bytes())
        for channel in ("positions", "normals"):
            payload["submeshes"][0][channel] = [[x, -z, y] for x, y, z in payload["submeshes"][0][channel]]
        data = json.dumps(payload, separators=(",", ":")).encode()
        (host.root / reference["path"]).write_bytes(data)
        reference.update(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest().upper())
        host.apply_candidate({**_request(host, "transaction_request", 31), "candidate": reference})
        rotated = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert list(rotated.mesh.submeshes[0].normals) != list(before.mesh.submeshes[0].normals)
        command(host, "replacement_fit" if fit else "replacement_reset")
        after = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        if not fit:
            assert list(after.mesh.submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
        else:
            assert list(after.mesh.submeshes[0].vertices) != list(before.mesh.submeshes[0].vertices)
        assert list(after.mesh.submeshes[0].normals) == list(before.mesh.submeshes[0].normals)
        assert host.shadow_service.validate_export_snapshot(after).ok
        bundle = host.shadow_service._replacement_output_for_snapshot(after)
        exported = parse_mesh(bundle.data, after.mesh.path)
        for actual, expected in zip(exported.submeshes[0].normals, before.mesh.submeshes[0].normals, strict=True):
            assert actual == pytest.approx(expected, abs=.002)
        host.shadow_service.undo(host.shadow_session_id)
        assert list(host.shadow_service.working_mesh(host.shadow_session_id).submeshes[0].normals) == list(rotated.mesh.submeshes[0].normals)
        host.shadow_service.redo(host.shadow_session_id)
        assert list(host.shadow_service.working_mesh(host.shadow_session_id).submeshes[0].normals) == list(before.mesh.submeshes[0].normals)
    finally:
        if not host.closed:
            host.cancel()


def _lod_part_records(data, lod, part_index=1):
    sections = {section["index"]: section for section in _parse_par_sections(data)}
    sec0 = sections[0]
    descriptors = _find_pac_descriptors(data, sec0["offset"], sec0["size"], 4)
    part = _parse_pac_geometry_section(data, "lods.pac", descriptors, sections[4 - lod], lod).submeshes[part_index]
    return (
        data[part.source_descriptor_offset:part.source_descriptor_offset + 64],
        b"".join(data[offset:offset + 40] for offset in part.source_vertex_offsets),
        data[part.source_index_offset:part.source_index_offset + part.source_index_count * 2],
    )


def _distinct_lods():
    data, _ = _minimal_two_part_pac_original()
    raw = bytearray(data)
    for lod in range(4):
        vertex_start = struct.unpack_from("<I", raw, 0x50 + 5 + lod * 4)[0]
        for vertex in range(6):
            record = vertex_start + vertex * 40
            raw[record + 28] = 255
            if vertex >= 3:
                # Every level has distinct geometry, UVs, shading and mixed skin weights.
                struct.pack_into("<H", raw, record, 2048 * lod)
                struct.pack_into("<ee", raw, record + 8, lod / 8, vertex / 8)
                struct.pack_into("<I", raw, record + 16, 0x20080000 + lod)
                raw[record + 20:record + 22] = bytes([0, 1])
                raw[record + 28:record + 30] = bytes([200 - lod, 55 + lod])
        index_start = struct.unpack_from("<I", raw, 0x50 + 5 + 16 + lod * 4)[0]
        struct.pack_into("<3H", raw, index_start + 6, *((0, 2, 1) if lod % 2 else (0, 1, 2)))
    return bytes(raw)


def test_selected_import_preserves_untouched_records_at_every_lod_through_reorder_and_inclusion(tmp_path):
    data = _distinct_lods()
    mesh = parse_mesh(data, "character/model/lods.pac")
    mesh._cdmw_original_data = data
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    try:
        # Grow the preceding part to force the untouched part's records to move.
        path = source_obj(tmp_path)
        path.write_text("o replacement\nv 12 3 7\nv 16 3 7\nv 12 5 8\nv 16 5 8\nf 1 2 3\nf 2 4 3\n")
        after = _import(service, sid, path)
        after.mesh.submeshes.reverse()
        bundle = prepare_replacement_output(after)
        for lod in range(4):
            assert _lod_part_records(bundle.data, lod) == _lod_part_records(data, lod)
        key = after.replacement_state.parts[1].part_id
        set_part_inclusion(service, after, (key,), False)
        excluded = service.capture_export_snapshot(sid)
        hidden = prepare_replacement_output(excluded)
        for lod in range(4):
            assert _lod_part_records(hidden.data, lod) != _lod_part_records(data, lod)
        set_part_inclusion(service, excluded, (key,), True)
        restored = service.capture_export_snapshot(sid)
        output, report = service.rebuild_result_from_snapshot(restored)
        assert report.validation_status == "passed"
        for lod in range(4):
            assert _lod_part_records(output.data, lod) == _lod_part_records(data, lod)
        # An actual edit of that original part must still be written.
        from cdmw.domain.mesh.replacement import bound_part_indices
        index = bound_part_indices(restored.mesh, restored.replacement_state)[key]
        restored.mesh.submeshes[index].normals = [(0.0, 1.0, 0.0)] * 3
        edited = parse_mesh(prepare_replacement_output(restored).data, mesh.path)
        assert edited.submeshes[1].normals[0] == pytest.approx((0, 1, 0), abs=.002)
    finally:
        service.close_edit_session(sid)


def test_unproven_shared_lower_lod_records_are_rejected_without_publication(editor, tmp_path):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    data = bytearray(snapshot.original_data)
    index_start = struct.unpack_from("<I", data, 0x50 + 5 + 16 + 4)[0]
    struct.pack_into("<H", data, index_start + 6, 3)
    snapshot = replace(snapshot, original_data=bytes(data))
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, source_obj(tmp_path), target_part_ids=(key,))
    candidate, state = compose_import(pending, (pending.target_part_ids[0],))
    with pytest.raises(ValueError, match="shared or invalid vertex indices"):
        commit_replacement(service, snapshot, candidate, state, label="Import replacement")
    assert service.session_view(sid).revision == snapshot.mesh_revision
    assert service.session_view(sid).undo_count == 0


def test_prepared_report_revision_matches_publication_without_mutating_preflight(editor, tmp_path, monkeypatch):
    import cdmw.services.mesh_replacement_import as imports
    service, sid = editor
    prepared = []
    original_prepare = imports.prepare_replacement_output

    def capture(snapshot):
        output = original_prepare(snapshot)
        prepared.append(output)
        return output

    monkeypatch.setattr(imports, "prepare_replacement_output", capture)
    published = _import(service, sid, source_obj(tmp_path))
    for included in (None, False, True):
        if included is not None:
            set_part_inclusion(service, published, (published.replacement_state.parts[0].part_id,), included)
            published = service.capture_export_snapshot(sid)
        bundle, report = service.rebuild_result_from_snapshot(published)
        assert bundle.revision[0] == report.export_snapshot["mesh_revision"] == published.mesh_revision
        assert prepared[-1].report.export_snapshot["mesh_revision"] == published.mesh_revision - 1
        assert report is not prepared[-1].report


def test_rotated_draft_reopens_with_import_normals_and_reset_clears_tangents(editor, tmp_path):
    service, sid = editor
    imported = _import(service, sid, source_obj(tmp_path))
    part = imported.mesh.submeshes[0]
    part.vertices = [(x, -z, y) for x, y, z in part.vertices]
    part.normals = [(x, -z, y) for x, y, z in part.normals]
    part.tangents = [(1, 0, 0)] * len(part.vertices)
    part.tangent_signs = [1.0] * len(part.vertices)
    commit_replacement(service, imported, imported.mesh, imported.replacement_state, label="Rotate replacement")
    path = tmp_path / "draft" / "mesh_layers.json"
    service._session(sid).mesh_layer_project_path = path
    service.retry_mesh_layer_autosave(sid)
    seed = parse_mesh(imported.original_data, imported.mesh.path)
    seed._cdmw_original_data = imported.original_data
    seed._cdmw_mesh_layer_project_path = str(path)
    reopened = MeshService()
    loaded_id = reopened.open_edit_session(seed).session_id
    try:
        loaded = reopened.capture_export_snapshot(loaded_id)
        binding = loaded.replacement_state.parts[0]
        assert list(loaded.mesh.submeshes[0].normals) != list(binding.import_normals)
        assert loaded.mesh.submeshes[0].tangents
        reset_or_fit_import(reopened, loaded)
        reset = reopened.capture_export_snapshot(loaded_id)
        assert list(reset.mesh.submeshes[0].vertices) == list(binding.import_positions)
        assert list(reset.mesh.submeshes[0].normals) == list(binding.import_normals)
        assert not reset.mesh.submeshes[0].tangents
        assert not getattr(reset.mesh.submeshes[0], "tangent_signs", ())
    finally:
        reopened.close_edit_session(loaded_id)


@pytest.mark.parametrize("legacy", [False, True])
def test_normal_draft_schema_and_legacy_placement_guard(editor, tmp_path, legacy):
    from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
    service, sid = editor
    imported = _import(service, sid, source_obj(tmp_path))
    payload = save_replacement_state(imported.replacement_state, tmp_path, tmp_path)
    assert payload["version"] == 2
    if legacy:
        payload["version"] = 1
        for part in payload["parts"]:
            del part["import_normals"]
    loaded = load_replacement_state(payload, tmp_path)
    if legacy:
        assert loaded.parts[0].import_normals is None
        snapshot = replace(imported, replacement_state=loaded)
        assert prepare_replacement_output(snapshot).data == prepare_replacement_output(imported).data
        for fit in (False, True):
            with pytest.raises(ValueError, match="older replacement draft has no saved import normals"):
                reset_or_fit_import(service, snapshot, fit=fit)
        assert service.session_view(sid).revision == imported.mesh_revision
    else:
        assert loaded == imported.replacement_state
        del payload["parts"][0]["import_normals"]
        with pytest.raises(ValueError, match="missing saved import normals"):
            load_replacement_state(payload, tmp_path)


@pytest.mark.parametrize("normals,reason", [
    (((0.0, 1.0, 0.0),), "do not match"),
    (((float("nan"), 1.0, 0.0),) * 3, "Non-finite"),
])
def test_invalid_saved_normal_frames_are_rejected(tmp_path, normals, reason):
    from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart
    from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
    part = ReplacementPart("part", 0, import_positions=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                           import_normals=normals)
    state = MeshReplacementState("mesh.pac", "a" * 64, (part,))
    payload = save_replacement_state(state, tmp_path, tmp_path)
    with pytest.raises(ValueError, match=reason):
        load_replacement_state(payload, tmp_path)
