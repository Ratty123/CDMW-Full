"""Original PAC skinning does not depend on inferred editor grooming guides."""
import copy
from dataclasses import replace
import hashlib
import struct

import pytest

from cdmw.domain.mesh.hair import hair_state_from_payload
from cdmw.domain.mesh.replacement import REPLACEMENT_POLICY
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_hair_output import validate_hair_output
from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_rust_hair import apply_hair_candidate
from tests.test_mesh_hair_authoring import editor, MESH


def original_snapshot(authoring, *, prepared=True):
    snapshot = authoring.shadow_service.capture_export_snapshot(authoring.shadow_session_id)
    state = snapshot.hair_state.payload
    state["groups"][0]["mode"] = "existing"
    state["guides"], state["bindings"] = [], []
    state["prepared_parts"] = [0] if prepared else []
    state["locks"] = [dict(id=1, part=0, guide=None, kind="unresolved", mirrored=None,
                           width_scale=1., vertices=list(range(len(snapshot.mesh.submeshes[0].vertices))))] if prepared else []
    state["next_lock_id"] = 2
    return replace(snapshot, hair_state=hair_state_from_payload(state))


@pytest.mark.parametrize("prepared", [False, True])
def test_untouched_existing_hair_exports_identical_pac_without_guides(editor, prepared):
    snapshot = original_snapshot(editor[1], prepared=prepared)
    validate_hair_output(snapshot)
    assert prepare_replacement_output(snapshot).data == snapshot.original_data


@pytest.mark.parametrize("channel", ["vertices", "normals", "uvs", "bone_indices", "bone_weights",
                                     "source_vertex_offsets", "source_vertex_map", "faces", "stride", "generated", "generated_with_guide", "topology", "draft_map"])
def test_unprepared_changed_or_unproven_sections_still_block_export(editor, channel):
    snapshot = original_snapshot(editor[1])
    part = snapshot.mesh.submeshes[0]
    if channel in {"generated", "generated_with_guide", "draft_map"}:
        state = snapshot.hair_state.payload
        if channel == "draft_map":
            state["vertex_sources"] = {"0": list(reversed(part.source_vertex_map))}
        else:
            state["groups"][0]["mode"] = "generated"
            if channel == "generated_with_guide":
                state["guides"] = editor[1].shadow_service._session(editor[1].shadow_session_id).hair_state.payload["guides"]
        snapshot = replace(snapshot, hair_state=hair_state_from_payload(state))
    elif channel == "topology":
        part.source_vertex_map_authority = "topology"
    elif channel == "stride":
        part.source_vertex_stride = 44
    elif channel in {"source_vertex_offsets", "source_vertex_map"}:
        getattr(part, channel)[0] += 1
    elif channel == "faces":
        part.faces[0] = tuple(reversed(part.faces[0]))
    else:
        rows = getattr(part, channel)
        rows[0] = (rows[0][0] + .125 if channel != "bone_indices" else rows[0][0] + 1, *rows[0][1:])
    with pytest.raises(ValueError, match="changed sections without grooming guides|Create and bind"):
        validate_hair_output(snapshot)


def test_unprepared_original_skinning_requires_exact_vertex_changes_even_one_float32_ulp(editor):
    snapshot = original_snapshot(editor[1])
    part = snapshot.mesh.submeshes[0]
    x, y, z = part.vertices[1]
    bits = struct.unpack("<I", struct.pack("<f", x))[0]
    part.vertices[1] = (struct.unpack("<f", struct.pack("<I", bits + 1))[0], y, z)
    with pytest.raises(ValueError, match="changed sections"):
        validate_hair_output(snapshot)


def test_unchanged_sections_export_alongside_groomed_sections_in_the_same_part(editor):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    snapshot = original_snapshot(authoring)
    state = snapshot.hair_state.payload
    state["guides"] = service._session(sid).hair_state.payload["guides"]
    state["locks"][0]["vertices"] = [0, 1, 2]
    state["locks"].append(dict(id=2, part=0, guide=0, kind="bound", mirrored=None, width_scale=1., vertices=[3]))
    state["next_lock_id"] = 3
    state["bindings"] = [dict(part=0, vertex=3, guide=0, segment=0, t=0., offset=[0, 0, 0])]
    live = service._session(sid)
    live.hair_state = hair_state_from_payload(state)
    state["revision"] += 1
    positions = [list(p) for p in snapshot.mesh.submeshes[0].vertices]
    positions[3][0] += .125
    request = {"hair": state, "submeshes": [{"positions": positions,
        "normals": [list(row) for row in snapshot.mesh.submeshes[0].normals], "uvs": [list(row) for row in snapshot.mesh.submeshes[0].uvs],
        "indices": [v for face in snapshot.mesh.submeshes[0].faces for v in face]}]}
    apply_hair_candidate(authoring, request, "Groom prepared section")
    for history in (None, service.undo, service.redo):
        if history:
            history(sid)
        result = service.capture_export_snapshot(sid)
        validate_hair_output(result)
        rebuilt = prepare_replacement_output(result)
        reparsed = parse_mesh(rebuilt.data, MESH)
        original = parse_mesh(snapshot.original_data, MESH).submeshes[0]
        for actual, expected in zip(reparsed.submeshes[0].vertices[:3], original.vertices[:3], strict=True):
            # A changed part can expand PAC's quantized position bounds.
            assert actual == pytest.approx(expected, abs=2e-5)
        for old, new in zip(original.source_vertex_offsets, reparsed.submeshes[0].source_vertex_offsets, strict=True):
            for start, end in ((12, 16), (20, 36), (39, 40)):
                assert snapshot.original_data[old + start:old + end] == rebuilt.data[new + start:new + end]
        assert result.mesh.submeshes[0].vertices[:3] == snapshot.mesh.submeshes[0].vertices[:3]
        assert (rebuilt.data == snapshot.original_data) is (history == service.undo)


def test_original_hair_uses_retained_neutral_coordinates_and_reopens_without_guides(editor, tmp_path):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    snapshot = original_snapshot(authoring)
    matrix = (2., 0., 0., 0., 0., 2., 0., 0., 0., 0., 2., 0., .25, -.5, .125, 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8)
    snapshot = replace(snapshot, mesh=appearance.to_neutral(snapshot.mesh),
        replacement_state=replace(snapshot.replacement_state, neutral_appearance=appearance, neutral_coordinates=True))
    validate_hair_output(snapshot)
    assert prepare_replacement_output(snapshot).data == snapshot.original_data
    prepared = service.prepare_working_mesh_replacement(sid, snapshot.mesh,
        replacement_state=snapshot.replacement_state, hair_state=snapshot.hair_state,
        replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY)
    service.commit_prepared_working_mesh_replacement(prepared, history_action="hair_setup", history_label="Original",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    live = service._session(sid)
    live.mesh_layer_project_path = tmp_path / "original-draft" / "project.json"
    service.retry_mesh_layer_autosave(sid)
    restored = copy.deepcopy(live.base_mesh)
    loaded = load_mesh_layer_project(restored, live.mesh_layer_project_path,
                                    expected_source_asset_sha256=live.mesh_asset_source_hash)
    reopened = replace(snapshot, mesh=restored, replacement_state=loaded["replacement_state"], hair_state=loaded["hair_state"])
    assert not reopened.hair_state.payload["guides"]
    for channel in ("vertices", "normals", "uvs", "bone_indices", "bone_weights", "source_vertex_map", "source_vertex_offsets"):
        assert getattr(restored.submeshes[0], channel) == getattr(snapshot.mesh.submeshes[0], channel), channel
    validate_hair_output(reopened)
    assert prepare_replacement_output(reopened).data == snapshot.original_data


def test_unprepared_retained_triangles_keep_eight_influence_skin_records(editor):
    from tests.test_pac_skin_extra_influences import _record
    from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TARGET_DONOR
    snapshot = original_snapshot(editor[1])
    data = bytearray(snapshot.original_data)
    record = _record(palette=(1, 2, 3, 4, 5, 6), weights=(60, 50, 40, 30, 20, 10, 25, 20), extra=(0., 7.), gate=0)
    offsets = snapshot.mesh.submeshes[0].source_vertex_offsets
    for offset in offsets:
        for start, end in ((12, 16), (20, 36), (39, 40)):
            data[offset + start:offset + end] = record[start:end]
    snapshot = replace(snapshot, original_data=bytes(data), mesh=parse_mesh(bytes(data), MESH), replacement_state=None)
    output = initial_replacement_state(snapshot, dependencies=editor[1].shadow_service._session(editor[1].shadow_session_id).replacement_state.dependencies)
    snapshot = replace(snapshot, replacement_state=output, mesh=mesh_with_part_ids(snapshot, output))
    state = snapshot.hair_state.payload
    state["template"]["sha256"] = hashlib.sha256(data).hexdigest()
    part = snapshot.mesh.submeshes[0]
    sources = list(reversed(part.faces[0]))
    remap = {old: new for new, old in enumerate(sources)}
    part.faces = [tuple(remap[v] for v in part.faces[0])]
    for channel in ("vertices", "normals", "uvs", "bone_indices", "bone_weights", "source_vertex_offsets"):
        setattr(part, channel, [getattr(part, channel)[v] for v in sources])
    part.vertex_count, part.face_count = len(sources), 1
    part.source_vertex_map = sources
    part.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
    state["vertex_sources"] = {"0": sources}
    state["locks"][0]["vertices"] = list(range(len(sources)))
    snapshot = replace(snapshot, hair_state=hair_state_from_payload(state), replacement_state=replace(output,
        parts=tuple(replace(p, import_positions=tuple(part.vertices), import_normals=tuple(part.normals)) for p in output.parts)))
    validate_hair_output(snapshot)
    rebuilt = prepare_replacement_output(snapshot)
    result = parse_mesh(rebuilt.data, MESH).submeshes[0]
    for offset, source in zip(result.source_vertex_offsets, sources, strict=True):
        for start, end in ((12, 16), (20, 36), (39, 40)):
            assert rebuilt.data[offset + start:offset + end] == data[offsets[source] + start:offsets[source] + end]
