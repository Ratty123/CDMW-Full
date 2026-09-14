"""Hair transactions restore guides, geometry and output intent together."""
import copy
from dataclasses import replace
import hashlib
import io
import json
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.domain.mesh.hair import hair_state_from_payload
from cdmw.domain.mesh.replacement import ReplacementFile, REPLACEMENT_POLICY
from cdmw.services.mesh_rust_hair import apply_hair_candidate, hair_ui_state
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids
from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
from cdmw.services.mesh_hair_output import validate_hair_output, prepare_authored_hair
import tests.test_mesh_rust_authoring as _fixtures
from tests.test_hair_registration import MESH, STEM, NEW, ICON, fixture as registration_fixture
from tests.test_character_finder_dialog import finder, publish_rows, row, detail

TEXTURE = "character/texture/hair.dds"
MATERIAL = MESH.replace("character/model/", "character/modelproperty/") + "_xml"


def dds():
    stream = io.BytesIO()
    Image.new("RGBA", (4, 4), (95, 40, 12, 255)).save(stream, format="DDS", pixel_format="DXT5")
    return stream.getvalue()


def test_hair_material_ignores_engine_unbound_slots_but_retains_them_in_xml():
    from cdmw.services.mesh_hair_output import material_texture_paths
    data = b'<Material><Texture _path="texture/nonetexture0xffffffff.dds"/><Texture _path="character/texture/hair.dds"/></Material>'
    root, textures = material_texture_paths(data)
    assert textures == ("character/texture/hair.dds",)
    assert next(root.iter("Texture")).get("_path") == "texture/nonetexture0xffffffff.dds"


def test_hair_mode_allows_mod_inclusion_without_conversion(editor):
    _, authoring = editor
    live = authoring.shadow_service._session(authoring.shadow_session_id)
    part_id = live.replacement_state.parts[0].part_id
    original = live.hair_state
    for included in (False, True):
        request = _fixtures._request(authoring, "command_request", 810 + included)
        request.update(command="replacement_include", arguments={"part_ids":[part_id], "included":included})
        authoring.run_command(request)
        assert live.replacement_state.parts[0].included is included
        assert live.hair_state == original and not live.hair_state.payload["converted"]


def test_reopened_hair_draft_can_save_and_export_again(editor, tmp_path):
    from cdmw.domain.mesh.replacement import bound_part_indices
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    apply_hair_candidate(authoring, candidate(authoring, topology=True), "Draw")
    for number in range(2):
        live.mesh_layer_project_path = tmp_path / f"save-{number}" / "project.json"
        service.retry_mesh_layer_autosave(sid)
        restored = copy.deepcopy(live.base_mesh)
        loaded = load_mesh_layer_project(restored, live.mesh_layer_project_path,
            expected_source_asset_sha256=live.mesh_asset_source_hash)
        bound_part_indices(restored, loaded["replacement_state"])
        prepared = service.prepare_working_mesh_replacement(sid, restored, replacement_state=loaded["replacement_state"],
            hair_state=loaded["hair_state"], replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY)
        bound_part_indices(prepared.working_mesh, loaded["replacement_state"])
        service.commit_prepared_working_mesh_replacement(prepared, history_action="hair_resume", history_label="Reopen",
            output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    snapshot = service.capture_export_snapshot(sid)
    assert service._replacement_output_for_snapshot(snapshot).data


def payload(digest="a" * 64, mode="generated"):
    return {"version": 1, "revision": 0, "converted": False,
        "scalp": {"identity": "head:a", "positions": [[0, 0, 0], [1, 0, 0], [0, 0, 1]], "triangles": [[0, 1, 2]]},
        "bound_reference": "head:a", "reference_parts": [],
        "template": {"path": MESH, "sha256": digest, "target_stem": NEW, "character": "Damiane", "physics_profile": "Hair"},
        "groups": [{"id": 0, "name": "Hair", "part": 0, "mode": mode, "width": .02, "cards_per_guide": 1, "uv_rect": [0, 0, 1, 1]}],
        "guides": [{"root": {"triangle": 0, "barycentric": [1, 0, 0]}, "group": 0, "points": [[0, 0, 0], [0, 1, 0]]}],
        "bindings": [], "collisions": []}


@pytest.fixture
def editor(tmp_path):
    authority, authoring = _fixtures.RustMeshAuthoringTests()._create(tmp_path / "session")
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(sid)
    session.working_mesh.path = session.base_mesh.path = MESH
    snapshot = service.capture_export_snapshot(sid)
    material = f'<Material _pbdSimulationMaterialName="Hair"><Texture _path="{TEXTURE}"/></Material>'.encode()
    dependencies = (ReplacementFile(MATERIAL, material), ReplacementFile(TEXTURE, dds()))
    output = initial_replacement_state(snapshot, None, dependencies)
    state = payload(hashlib.sha256(snapshot.original_data).hexdigest())
    state["bindings"] = [dict(part=0, vertex=i, guide=0, segment=0, t=0., offset=[0, 0, 0])
                         for i in range(len(snapshot.mesh.submeshes[0].vertices))]
    mesh = mesh_with_part_ids(snapshot, output)
    prepared = service.prepare_working_mesh_replacement(sid, mesh, replacement_state=output,
        hair_state=hair_state_from_payload(state), replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY)
    service.commit_prepared_working_mesh_replacement(prepared, history_action="hair_setup", history_label="Hair",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    try:
        yield authority, authoring
    finally:
        authoring.cancel()
        authority.close_edit_session(authoring.authoritative_session_id, force_without_saving=True)


def candidate(editor, *, topology=False):
    mesh = editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True)
    state = editor.shadow_service._session(editor.shadow_session_id).hair_state.payload
    state["revision"] += 1
    state["guides"][0]["points"][1][0] += .3
    parts = [{"positions": [list(p) for p in part.vertices], "normals": [list(p) for p in part.normals],
              "uvs": [list(p) for p in part.uvs], "indices": [i for face in part.faces for i in face]}
             for part in mesh.submeshes]
    parts[0]["positions"][0][0] += .25
    if topology:
        first = parts[0]
        n = len(first["positions"])
        first["positions"] += [[p[0] + .05, p[1] + .1, p[2]] for p in first["positions"]]
        first["normals"] *= 2
        first["uvs"] *= 2
        first["indices"] += [i+n for i in first["indices"]]
        state["bindings"] = [dict(part=0, vertex=i, guide=0, segment=0, t=0., offset=[0, 0, 0]) for i in range(n*2)]
    return {"submeshes": parts, "hair": state}


def test_state_is_immutable_and_unbound_head_can_be_saved_until_explicit_rebind():
    value = payload()
    state = hair_state_from_payload(value)
    value["guides"][0]["points"][1][0] = 7
    assert state.payload["guides"][0]["points"][1][0] == 0
    value = state.payload
    value["scalp"]["identity"] = "changed-head"
    value["guides"][0]["root"]["triangle"] = 10
    assert hair_state_from_payload(value)
    with pytest.raises(ValueError, match="rebind"):
        hair_state_from_payload(value, allow_unbound=False)


def test_acknowledgement_revision_does_not_decode_the_hair_document(monkeypatch):
    from cdmw.domain.mesh import hair

    state = hair_state_from_payload({**payload(), "revision": 37})
    def forbidden(*args, **kwargs):
        raise AssertionError("Reading a revision must not decode scalp, guides or bindings")
    monkeypatch.setattr(hair.json, "loads", forbidden)
    assert state.revision == 37
    assert state.revision == 37


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(version=True),
    lambda p: p["guides"][0]["points"][0].__setitem__(0, .1),
    lambda p: p["groups"].append(copy.deepcopy(p["groups"][0])),
    lambda p: p["guides"][0]["points"][1].__setitem__(0, float("nan")),
])
def test_invalid_state_is_rejected(mutate):
    value = payload()
    mutate(value)
    with pytest.raises(ValueError):
        hair_state_from_payload(value)


def test_topology_transaction_undo_redo_restores_all_state_and_writer(editor):
    _, session = editor
    service, sid = session.shadow_service, session.shadow_session_id
    before = service.capture_export_snapshot(sid)
    apply_hair_candidate(session, candidate(session, topology=True), "Generate bob")
    after = service.capture_export_snapshot(sid)
    assert len(after.mesh.submeshes[0].vertices) == 2 * len(before.mesh.submeshes[0].vertices)
    assert after.hair_state != before.hair_state
    assert all(not part.included for part in after.replacement_state.parts if part.target_index != 0)
    validate_hair_output(after)
    rebuilt = service._replacement_output_for_snapshot(after)
    assert rebuilt.data != before.original_data
    service.undo(sid)
    undone = service.capture_export_snapshot(sid)
    assert undone.hair_state == before.hair_state
    assert undone.replacement_state == before.replacement_state
    assert undone.mesh.submeshes[0].vertices == before.mesh.submeshes[0].vertices
    service.redo(sid)
    redone = service.capture_export_snapshot(sid)
    assert redone.hair_state == after.hair_state
    assert redone.replacement_state == after.replacement_state
    assert redone.mesh.submeshes[0].vertices == after.mesh.submeshes[0].vertices


def test_repeated_generated_topology_uses_original_skin_donor(editor):
    from cdmw.modding.mesh_parser import parse_mesh

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    original = service.capture_export_snapshot(sid)
    for label in ("Generate bob", "Draw first lock", "Draw second lock"):
        before = service.capture_export_snapshot(sid)
        apply_hair_candidate(authoring, candidate(authoring, topology=True), label)
        after = service.capture_export_snapshot(sid)
        assert len(after.mesh.submeshes[0].vertices) == 2 * len(before.mesh.submeshes[0].vertices)
        rebuilt = service._replacement_output_for_snapshot(after)
        parsed = parse_mesh(rebuilt.data, MESH)
        assert len(parsed.submeshes[0].bone_weights) == len(after.mesh.submeshes[0].vertices)
        assert all(abs(sum(row) - 1) < .01 for row in parsed.submeshes[0].bone_weights)
    service.undo(sid)
    assert service.capture_export_snapshot(sid).hair_state == before.hair_state
    service.redo(sid)
    assert service.capture_export_snapshot(sid).hair_state == after.hair_state
    assert after.original_data == original.original_data


@pytest.mark.parametrize("kind", ["stale", "donor", "uv", "cancel"])
def test_bad_or_cancelled_transaction_keeps_last_scene(editor, kind):
    _, session = editor
    before = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    value = candidate(session)
    stop = threading.Event()
    if kind == "stale":
        value["hair"]["revision"] = before.hair_state.revision
    elif kind == "donor":
        value["hair"]["template"]["sha256"] = "b"*64
    elif kind == "uv":
        value["hair"]["groups"][0]["mode"] = "existing"
        value["submeshes"][0]["uvs"][0][0] += .1
    else:
        stop.set()
    with pytest.raises((ValueError, RuntimeError)):
        apply_hair_candidate(session, value, "Bad edit", stop)
    after = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    assert after.mesh_revision == before.mesh_revision
    assert after.hair_state == before.hair_state
    assert after.replacement_state == before.replacement_state


def test_hair_file_is_stable_for_selection_only_updates(editor):
    _, session = editor
    first = hair_ui_state(session)["file"]
    path = session.root / first["path"]
    stamp = path.stat().st_mtime_ns
    assert hair_ui_state(session)["file"] == first
    assert path.stat().st_mtime_ns == stamp


def test_v5_draft_roundtrip_keeps_hair_geometry_and_output(editor, tmp_path):
    _, session = editor
    service, sid = session.shadow_service, session.shadow_session_id
    apply_hair_candidate(session, candidate(session, topology=True), "New hairstyle")
    current = service._session(sid)
    project = tmp_path / "draft/project.json"
    current.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(sid)
    assert json.loads(project.read_text())["format"] == "mesh_layer_project_v5"
    mesh = copy.deepcopy(current.base_mesh)
    loaded = load_mesh_layer_project(mesh, project, expected_source_asset_sha256=current.mesh_asset_source_hash)
    assert loaded["hair_state"] == current.hair_state
    assert loaded["replacement_state"] == current.replacement_state
    assert mesh.submeshes[0].vertices == current.working_mesh.submeshes[0].vertices


def test_missing_texture_blocks_game_output_but_preserves_draft(editor):
    _, session = editor
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    snapshot = replace(snapshot, replacement_state=replace(snapshot.replacement_state,
        dependencies=tuple(f for f in snapshot.replacement_state.dependencies if not f.path.endswith(".dds"))))
    with pytest.raises(ValueError, match="Missing required hair texture"):
        validate_hair_output(snapshot)


def test_authored_bundle_clones_textures_and_retains_existing_barber_choices(editor):
    from cdmw.core.pathc_format import block_infos_for, encode_pathc, parse_pathc
    from tests.test_pathc_format import build_table
    from cdmw.domain.hair_registration import read_hair_choices
    from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
    _, session = editor
    apply_hair_candidate(session, candidate(session, topology=True), "Generated bob")
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    rebuilt = session.shadow_service._replacement_output_for_snapshot(snapshot)
    files = registration_fixture()
    files[MESH] = snapshot.original_data
    files.update({f.path: f.data for f in snapshot.replacement_state.dependencies})
    files[ICON] = dds()
    table = build_table(headers=[dds()[:128]], entries=[(TEXTURE, 0, block_infos_for(dds())), (ICON, 0, block_infos_for(dds()))])
    before = copy.deepcopy(files)
    plan, pathc, _ = prepare_authored_hair(snapshot, rebuilt, files, files, encode_pathc(table))
    assert files == before
    writes = {f.path: f.data for f in (*plan.replacements, *plan.additions)}
    assert MESH not in writes and MATERIAL not in writes and TEXTURE not in writes
    assert writes[MESH.replace(STEM, NEW)] == rebuilt.data
    assert writes[MATERIAL.replace(STEM, NEW)] != files[MATERIAL]
    assert read_hair_choices(writes[DAMIANE_MESH_PARAM])[:-1] == read_hair_choices(files[DAMIANE_MESH_PARAM])
    assert len(parse_pathc(pathc).entries) == len(table.entries) + 2
    texture = next(f for f in plan.additions if "_texture_" in f.path)
    assert texture.data == files[TEXTURE]
    with pytest.raises(ValueError, match="already exists"):
        prepare_authored_hair(snapshot, rebuilt, files, {*files, texture.path}, encode_pathc(table))


def test_dds_edit_preserves_material_binding_and_undo(editor, tmp_path):
    from cdmw.services.mesh_rust_hair import hair_texture_command
    _, session = editor
    service, sid = session.shadow_service, session.shadow_session_id
    source = tmp_path / "before.dds"
    source.write_bytes(dds())
    current = service._session(sid)
    current.working_mesh.submeshes[0].preview_texture_dds_path = str(source)
    current.working_mesh.submeshes[0].preview_texture_path = str(source)
    modified = tmp_path / "changed.dds"
    Image.new("RGBA", (4, 4), (10, 120, 80, 255)).save(modified, format="DDS", pixel_format="DXT5")
    before = service.capture_export_snapshot(sid)
    hair_texture_command(session, {"texture_path": TEXTURE, "_dds_path": str(modified)}, threading.Event())
    after = service.capture_export_snapshot(sid)
    assert after.hair_state.revision == before.hair_state.revision + 1
    assert after.replacement_state.companion_files[0].data == modified.read_bytes()
    assert after.mesh.submeshes[0].uvs == before.mesh.submeshes[0].uvs
    assert after.mesh.submeshes[0].preview_texture_dds_path != str(source)
    service.undo(sid)
    assert service.capture_export_snapshot(sid).hair_state == before.hair_state


def test_float32_wire_reference_roundtrip_preserves_host_reference(editor):
    import struct
    _, session = editor
    current=session.shadow_service._session(session.shadow_session_id)
    value=current.hair_state.payload
    value['scalp']['positions'][1][0]=struct.unpack('<f',struct.pack('<f',0.1))[0]
    current.hair_state=hair_state_from_payload(value)
    data=candidate(session)
    data['hair']['scalp']['positions'][1][0]=0.1
    apply_hair_candidate(session,data,'Rust f32 wire')
    assert current.hair_state.payload['scalp'] == value['scalp']
    data=candidate(session)
    data['hair']['scalp']['positions'][1][0]=0.101
    with pytest.raises(ValueError,match='reference'):
        apply_hair_candidate(session,data,'Changed head')


def test_invalid_hair_draft_does_not_partially_replace_geometry(editor, tmp_path):
    _, session=editor
    service,sid=session.shadow_service,session.shadow_session_id
    apply_hair_candidate(session,candidate(session,topology=True),'New hair')
    current=service._session(sid)
    project=tmp_path/'draft/project.json'
    current.mesh_layer_project_path=project
    service.retry_mesh_layer_autosave(sid)
    descriptor=json.loads(project.read_text())
    generation=project.parent/descriptor['current_generation']/'generation.json'
    contents=json.loads(generation.read_text())
    contents.pop('replacement')
    generation.write_text(json.dumps(contents),encoding='utf-8')
    descriptor['current_generation_manifest_sha256']=hashlib.sha256(generation.read_bytes()).hexdigest()
    project.write_text(json.dumps(descriptor),encoding='utf-8')
    mesh=copy.deepcopy(current.base_mesh)
    before=copy.deepcopy(mesh)
    with pytest.raises(RuntimeError,match='output state'):
        load_mesh_layer_project(mesh,project,expected_source_asset_sha256=current.mesh_asset_source_hash)
    assert mesh.submeshes[0].vertices == before.submeshes[0].vertices


def test_hair_protocol_transaction_publishes_state_and_finish_atomically(editor):
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload, RUST_MESH_CANDIDATE
    authority, session=editor
    data=candidate(session,topology=True)
    data.update(schema=RUST_MESH_CANDIDATE,session_id=session.session_id)
    request=_fixtures._request(session,'transaction_request',901)
    request['candidate']=_atomic_write_payload(session.root,'candidate-901-hair.json',data,data_type='mesh_candidate_json',expected_root_identity=session.root_identity)
    result=session.apply_candidate(request)
    assert result['hair']['active'] is True
    assert session.shadow_service._session(session.shadow_session_id).hair_state.revision == data['hair']['revision']
    expected=session.shadow_service._session(session.shadow_session_id).hair_state
    session.finish(_fixtures._request(session,'finish_request',902))
    assert authority._session(session.authoritative_session_id).hair_state == expected


def test_cancel_during_body_loading_releases_head_reference_lease(monkeypatch):
    from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
    from cdmw.workers import mesh_archive_refit_worker
    from unittest.mock import Mock
    lease=SimpleNamespace(lease=Mock())
    released=lease.lease
    calls=[]
    def prepare(args,stop):
        calls.append(args)
        if len(calls)==2:
            raise ValueError('Body loading cancelled')
        return {**args,'_archive_preview_lease':lease}
    monkeypatch.setattr(mesh_archive_refit_worker,'prepare_archive_refit_source',prepare)
    session=SimpleNamespace(closed=True)
    worker=MeshRustProtocolWorker(1,session,{'event':'command_request','command':'hair_begin','request_id':1,
        'arguments':{'_body_archive_entry':object(),'_body_archive_dependencies':object()}})
    failures=[]; finished=[]
    worker.error.connect(lambda *args:failures.append(args))
    worker.finished.connect(lambda:finished.append(True))
    worker.run()
    assert len(calls)==2 and len(failures)==1 and finished==[True]
    released.release.assert_called_once()
    assert lease.lease is None


def test_finder_hair_button_routes_to_shared_setup_without_loading(finder, monkeypatch):
    from cdmw.ui.mesh_editor import hair_flow
    dialog, catalogue, _ = finder
    selected = row(1, role="hair", path=MESH)
    publish_rows(dialog, catalogue, [selected])
    dialog._details = replace(detail(selected), models=(SimpleNamespace(entry_id=8, path=MESH),))
    calls = []
    monkeypatch.setattr(hair_flow, "start_hair_workflow", lambda *args, **kw: calls.append((args, kw)))
    editor = SimpleNamespace()
    dialog._window.shell.mesh_editor_tab = editor
    dialog._window.shell._activate_tool_widget = lambda tab: None
    dialog._buttons()
    assert dialog._create_hair.isEnabled()
    dialog._create_hair.click()
    assert calls == [((editor, "generated"), {"character": "Damiane", "target_path": MESH})]
    assert dialog._hair_handoff is None
    assert not dialog.isVisible()


def test_finder_stale_hair_preparation_restores_actions(finder):
    dialog,catalogue,_=finder
    selected=row(1,role='hair',path=MESH)
    publish_rows(dialog,catalogue,[selected])
    dialog._details=replace(detail(selected),models=(SimpleNamespace(entry_id=8,path=MESH),))
    dialog._hair_handoff=(selected.key,8,'generated')
    dialog._buttons()
    dialog._hair_prepared(-1,SimpleNamespace())
    assert dialog._hair_handoff is None and dialog._create_hair.isEnabled()


@pytest.mark.parametrize("operation", ["reshape", "cut", "delete"])
def test_existing_hair_preserves_all_eight_influence_record_bytes(editor, operation):
    from tests.test_pac_skin_extra_influences import _record
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
    _, session=editor
    snapshot=session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    data=bytearray(snapshot.original_data)
    skin=_record(palette=(1,2,3,4,5,6),weights=(60,50,40,30,20,10,25,20),extra=(0.,7.),gate=0)
    original=parse_mesh(bytes(data),MESH)
    offsets=original.submeshes[0].source_vertex_offsets
    for offset in offsets:
        data[offset+12:offset+16]=skin[12:16]
        data[offset+20:offset+36]=skin[20:36]
        data[offset+39]=skin[39]
    source=bytes(data)
    original=parse_mesh(source,MESH)
    assert len(original.submeshes[0].bone_weights[0]) == 8
    snapshot=replace(snapshot,original_data=source,mesh=original,replacement_state=None)
    output=initial_replacement_state(snapshot)
    mesh=copy.deepcopy(original)
    for part,binding in zip(mesh.submeshes,output.parts):
        setattr(part,PART_ID_ATTRIBUTE,binding.part_id)
    mesh.submeshes[0].vertices=[(x+.03,y,z) for x,y,z in mesh.submeshes[0].vertices]
    state=payload(hashlib.sha256(source).hexdigest(),mode='existing')
    sources = list(range(len(mesh.submeshes[0].vertices)))
    if operation == "cut":
        from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TARGET_DONOR
        part = mesh.submeshes[0]
        sources = list(reversed(part.faces[0]))
        remap = {old: new for new, old in enumerate(sources)}
        part.faces = [tuple(remap[i] for i in part.faces[0])]
        for channel in ("vertices", "normals", "uvs", "bone_indices", "bone_weights", "source_vertex_offsets"):
            setattr(part, channel, [getattr(part, channel)[i] for i in sources])
        part.vertex_count, part.face_count = len(sources), 1
        part.source_vertex_map = sources
        part.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
        output = replace(output, parts=tuple(replace(p, import_positions=tuple(part.vertices), import_normals=tuple(part.normals)) if p.target_index == 0 else p for p in output.parts))
    elif operation == "delete":
        output = replace(output, parts=tuple(replace(p, included=False) if p.target_index == 0 else p for p in output.parts))
        sources = [0, 0, 0]
    snapshot=replace(snapshot,mesh=mesh,replacement_state=output,hair_state=hair_state_from_payload(state))
    rebuilt=prepare_replacement_output(snapshot)
    assert rebuilt.data != source
    reparsed = parse_mesh(rebuilt.data, MESH)
    for offset, source_index in zip(reparsed.submeshes[0].source_vertex_offsets, sources, strict=True):
        old = offsets[source_index]
        assert rebuilt.data[offset+12:offset+16] == source[old+12:old+16]
        assert rebuilt.data[offset+20:offset+36] == source[old+20:old+36]
        assert rebuilt.data[offset+39] == source[old+39]


def test_card_uv_defaults_reuse_one_donor_atlas_island():
    from cdmw.services.mesh_rust_hair import template_card_uv_rect
    part=SimpleNamespace(vertices=[[0,0,0]]*6,faces=[(0,1,2),(3,4,5)],
        uvs=[(.1,.2),(.2,.2),(.2,.9),(.6,.1),(.8,.1),(.8,.8)])
    assert template_card_uv_rect(part) == [.1,.2,.2,.9]


def test_reference_identity_tracks_appearance_geometry_with_unchanged_source_bytes():
    from cdmw.services.mesh_rust_hair import _reference_geometry_identity
    positions = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]
    faces = [[0, 1, 2]]
    before = _reference_geometry_identity("same-source", positions, faces, [])
    assert before == _reference_geometry_identity("same-source", copy.deepcopy(positions), faces, [])
    positions[1][0] += .03
    assert before != _reference_geometry_identity("same-source", positions, faces, [])


@pytest.mark.parametrize("has_capability", [False, True])
@pytest.mark.parametrize("starting", [False, True])
def test_hair_hello_and_real_qt_command_queue(editor, tmp_path, monkeypatch, has_capability, starting):
    import time
    from PySide6.QtWidgets import QApplication
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    from cdmw.services.mesh_rust_contract import (
        RUST_HAIR_AUTHORING_CAPABILITY, RUST_MESH_RENDERER, RUST_MESH_EDIT_BACKEND,
    )
    _, session = editor
    if starting:
        session.hair_start_mode = "generated"
        session.shadow_service._session(session.shadow_session_id).hair_state = None
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process_generation = session.process_generation
    failures, responses = [], []
    monkeypatch.setattr(tab, "_fail_rust_editor", lambda message, **kw: failures.append(message))
    monkeypatch.setattr(tab, "_send_rust_message", lambda message: responses.append(message) or True)
    monkeypatch.setattr(tab.standalone_native_host_frame, "attach_child_window", lambda *args: (True, ""))
    try:
        capabilities = ["embedded_child_window_v1"]
        if has_capability:
            capabilities.append(RUST_HAIR_AUTHORING_CAPABILITY)
        tab._handle_rust_hello({"renderer": RUST_MESH_RENDERER, "edit_backend": RUST_MESH_EDIT_BACKEND,
                                "capabilities": capabilities, "child_hwnd": 123, "embedded_parent_hwnd": 456})
        if not has_capability:
            assert failures and "Hair-capable" in failures[0]
            assert not tab.standalone_rust_hello_received and not responses
            return
        assert not failures and tab.standalone_rust_hello_received
        request = _fixtures._request(session, "command_request", 1)
        request.update(command="state", arguments={})
        tab.standalone_rust_protocol_queue.append(request)
        tab._start_next_rust_protocol_worker()
        deadline = time.monotonic() + 30
        while tab.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(.005)
        assert tab.standalone_rust_protocol_thread is None
        result = next(message for message in responses if message["event"] == "command_result")
        assert result["ok"] is True
        assert not tab.standalone_rust_protocol_queue
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


@pytest.mark.parametrize("stale", [False, True])
def test_hair_output_worker_uses_validated_revision_and_complete_package(editor, tmp_path, monkeypatch, stale):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    _, session = editor
    service, sid = session.shadow_service, session.shadow_session_id
    revision = service.capture_export_snapshot(sid).mesh_revision
    if stale:
        apply_hair_candidate(session, candidate(session), "Later groom")
    published, completed, errors, finished = [], [], [], []
    output = tmp_path / "hair-package"
    def export(snapshot, rebuilt, entry, path, **kwargs):
        assert snapshot.hair_state is not None and rebuilt.data
        assert path == output
        published.append(snapshot.mesh_revision)
        return path
    monkeypatch.setattr("cdmw.services.mesh_hair_output.export_hair_package", export)
    worker = MeshDirectOutputWorker(8, service, sid, object(), kind="overlay_package",
        output_path=output, manager_profile="dmm", expected_mesh_revision=revision)
    worker.completed.connect(lambda _, result: completed.append(result))
    worker.error.connect(lambda _, error: errors.append(error))
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert finished == [True]
    if stale:
        assert errors and not published and not completed
    else:
        assert not errors and published == [revision]
        assert completed[0].output_path == output and completed[0].manager_profile == "dmm"


@pytest.mark.parametrize("changed", [False, True])
def test_hair_output_folder_picker_rejects_changed_revision(editor, tmp_path, monkeypatch, changed):
    from PySide6.QtWidgets import QFileDialog
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    _, session = editor
    tab = _tab(tmp_path)
    target = _fixtures._prepared_dds_entry(tmp_path, MESH, b"owned")
    tab.standalone_controller = SimpleNamespace(mesh_service=session.shadow_service,
                                               active_session_id=session.shadow_session_id)
    tab.standalone_export_validation_revision = 5
    calls, errors = [], []
    monkeypatch.setattr(tab, "_mesh_output_target", lambda: target)
    monkeypatch.setattr(tab, "_current_target_entry", lambda: target)
    monkeypatch.setattr(tab, "_standalone_export_validation_ok", lambda: True)
    monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kw: calls.append((args, kw)))
    tab.status_message_requested.connect(lambda message, error: errors.append(message) if error else None)
    def choose(*args):
        if changed:
            tab.standalone_export_validation_revision += 1
        return str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose)
    try:
        tab._start_mesh_mod_build_requested()
        if changed:
            assert not calls and errors and "changed while choosing output" in errors[0]
        else:
            assert not errors and calls[0][0] == ("overlay_package", target)
    finally:
        tab.standalone_controller = None
        _dispose(tab)


@pytest.mark.parametrize("bad", [None, "identity", "duplicate", "stale"])
def test_incremental_hair_update_reuses_immutable_references_and_keeps_history(editor, bad):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    before = service.capture_export_snapshot(sid)
    value = candidate(authoring)
    value["hair_update"] = {"version": 2, "reference": value["hair"]["scalp"]["identity"], "parts": [0]}
    for field in ("scalp", "references", "collisions"):
        value["hair"].pop(field, None)
    value["submeshes"] = value["submeshes"][:1]
    if bad == "identity": value["hair_update"]["reference"] = "different-head"
    if bad == "duplicate": value["hair_update"]["parts"] = [0, 0]; value["submeshes"] *= 2
    if bad == "stale": value["hair"]["revision"] = before.hair_state.revision
    if bad:
        with pytest.raises(ValueError): apply_hair_candidate(authoring, value, "Move lock")
        assert service.capture_export_snapshot(sid).hair_state == before.hair_state
    else:
        apply_hair_candidate(authoring, value, "Move lock")
        after = service.capture_export_snapshot(sid)
        assert after.hair_state.payload["scalp"] == before.hair_state.payload["scalp"]
        assert after.mesh.submeshes[0].vertices != before.mesh.submeshes[0].vertices
        service.undo(sid)
        assert service.capture_export_snapshot(sid).hair_state == before.hair_state
        service.redo(sid)
        assert service.capture_export_snapshot(sid).hair_state == after.hair_state


@pytest.mark.parametrize("bad", ["", "stale", "overlap", "duplicate_vertex"])
def test_incremental_hair_vertex_patch_preserves_other_channels_and_reuses_state(editor,bad):
    _,authoring=editor
    service,sid=authoring.shadow_service,authoring.shadow_session_id
    before=service.capture_export_snapshot(sid)
    value=candidate(authoring)
    old=before.hair_state.payload
    reused=["groups","bindings","guides","locks","vertex_sources","prepared_parts"]
    value["hair"]={**old,"revision":old["revision"]+1}
    for field in ["scalp","references","collisions",*reused]:value["hair"].pop(field,None)
    vertex=list(before.mesh.submeshes[0].vertices[1]);vertex[0]+=.012
    normal=[0., 1., 0.]
    value["submeshes"]=[]
    value["hair_update"]={"version":2,"reference":old["scalp"]["identity"],"parts":[],"reuse":reused,"base_hair_revision":old["revision"],
        "vertex_updates":[{"part":0,"indices":[1],"positions":[vertex],"normals":[normal]}]}
    if bad=="stale":value["hair_update"]["base_hair_revision"]-=1
    if bad=="overlap":value["hair"]["bindings"]=old["bindings"]
    if bad=="duplicate_vertex":
        row=value["hair_update"]["vertex_updates"][0];row["indices"]=[1,1];row["positions"]*=2;row["normals"]*=2
    if bad:
        with pytest.raises(ValueError):apply_hair_candidate(authoring,value,"vertex patch")
        assert service.capture_export_snapshot(sid).hair_state==before.hair_state
    else:
        apply_hair_candidate(authoring,value,"vertex patch")
        after=service.capture_export_snapshot(sid)
        assert after.mesh.submeshes[0].vertices[1]==tuple(vertex)
        assert after.mesh.submeshes[0].vertices[0]==before.mesh.submeshes[0].vertices[0]
        assert after.mesh.submeshes[0].uvs==before.mesh.submeshes[0].uvs
        assert after.mesh.submeshes[0].bone_weights==before.mesh.submeshes[0].bone_weights
        service.undo(sid)
        restored=service.capture_export_snapshot(sid)
        assert restored.hair_state==before.hair_state
        assert restored.mesh.submeshes[0].normals==before.mesh.submeshes[0].normals
        assert restored.mesh.submeshes[0].vertices==before.mesh.submeshes[0].vertices
        service.redo(sid)
        restored=service.capture_export_snapshot(sid)
        assert restored.hair_state==after.hair_state
        assert restored.mesh.submeshes[0].normals==after.mesh.submeshes[0].normals
        assert restored.mesh.submeshes[0].vertices==after.mesh.submeshes[0].vertices
        # Saving after Redo opens a clean native snapshot. The next groom must
        # invalidate that snapshot, retain skin channels, and remain undoable.
        live = service._session(sid)
        live.mesh_layer_project_path = authoring.root / "saved-after-redo" / "project.json"
        service.retry_mesh_layer_autosave(sid)
        assert live.native_editor_session_ready and not live.native_editor_mesh_dirty
        value["hair"]["revision"] = live.hair_state.revision + 1
        value["hair_update"]["base_hair_revision"] = live.hair_state.revision
        value["hair_update"]["vertex_updates"][0]["positions"][0][0] += .01
        apply_hair_candidate(authoring, value, "Groom after saved Redo")
        assert live.working_mesh.submeshes[0].vertices[1][0] == pytest.approx(vertex[0])
        assert live.working_mesh.submeshes[0].bone_weights == before.mesh.submeshes[0].bone_weights


@pytest.mark.parametrize("scale", [.92, 1.02, .9])
def test_mounted_head_scale_uses_head_joint_and_preserves_neck(scale, monkeypatch):
    from cdmw.services.mesh_rust_hair import _head_component_scale
    from cdmw.modding import mesh_parser
    bones = [SimpleNamespace(index=i, parent_index=i-1, name=name, bind_matrix=[0.]*12+[0.,1.5,0.,1.])
             for i,name in enumerate(("Bip01 Neck", "Bip01 Head", "Face"))]
    skeleton = SimpleNamespace(bones=bones)
    part = SimpleNamespace(vertices=[(0.,1.,0.), (0.,1.5,0.), (0.,2.,0.)],
                           bone_indices=[[0], [1], [2]], bone_weights=[[1.], [1.], [1.]])
    mesh = SimpleNamespace(submeshes=[part])
    monkeypatch.setattr(mesh_parser, "resolve_pac_bone_palette", lambda *args: [0,1,2])
    _head_component_scale(mesh, scale, skeleton, None, b"pac", body=True)
    assert part.vertices[:2] == [(0.,1.,0.), (0.,1.5,0.)]
    assert part.vertices[2] == (0., 1.5 + .5 * scale, 0.)


def test_facial_details_are_head_references_not_hair_planting_surfaces(editor):
    from cdmw.services.mesh_rust_hair import prepare_hair_setup
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    head = service.working_mesh(sid, clone=True)
    detail = copy.deepcopy(head)
    for part in detail.submeshes:
        part.vertices = [(p[0] + 2., p[1], p[2]) for p in part.vertices]
    source_data = service._session(sid).original_data
    args = dict(character="Damiane", _archive_snapshot=SimpleNamespace(mesh=head, original_data=source_data),
                _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
                _prepared_head_details=[dict(_archive_snapshot=SimpleNamespace(mesh=detail, original_data=source_data), _archive_neutral_appearance=None, _scale=1.)])
    for _ in range(2):
        prepare_hair_setup(service, sid, args, None)
        state = service._session(sid).hair_state.payload
        assert state["scalp"]["positions"] == [list(p) for part in head.submeshes for p in part.vertices]
        assert len(state["references"]) == 1
        assert state["references"][0]["identity"].startswith("head:")
        assert state["references"][0]["positions"] == [list(p) for part in detail.submeshes for p in part.vertices]


@pytest.mark.parametrize("failure", ["", "publish", "memory", "cancel"])
def test_hair_metadata_transaction_is_atomic_and_does_not_rebuild_scene(editor, monkeypatch, failure):
    import threading
    from cdmw.services import mesh_service_hair_transaction as transactions
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    before = live.hair_state
    original_mesh, revision, undo, redo = live.working_mesh, live.revision, list(live.undo_stack), list(live.redo_stack)
    old = before.payload
    reuse = ["groups", "bindings", "guides", "locks", "vertex_sources", "prepared_parts"]
    value = {"hair": {**old, "revision": old["revision"] + 1, "style_name": "New name"}, "submeshes": [],
             "hair_update": {"version": 2, "reference": old["scalp"]["identity"], "parts": [],
                             "reuse": reuse, "base_hair_revision": old["revision"]}}
    for field in ("scalp", "references", "collisions", *reuse): value["hair"].pop(field, None)
    def forbidden(*args, **kwargs): raise AssertionError("Small hair edits must not rebuild the entire mesh")
    monkeypatch.setattr(service, "capture_export_snapshot", forbidden)
    monkeypatch.setattr(service, "prepare_working_mesh_replacement", forbidden)
    stop = threading.Event()
    if failure == "publish":
        publish = transactions._publish
        def failed(*args):
            publish(*args)
            raise RuntimeError("injected publication failure")
        monkeypatch.setattr(transactions, "_publish", failed)
    elif failure == "memory": service.max_history_bytes = 1
    elif failure == "cancel": stop.set()
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            apply_hair_candidate(authoring, value, "Name hair", stop)
        assert live.hair_state is before and live.working_mesh is original_mesh
        assert live.revision == revision and live.undo_stack == undo and live.redo_stack == redo
    else:
        apply_hair_candidate(authoring, value, "Name hair", stop)
        assert live.hair_state.payload["style_name"] == "New name"
        assert all(a is b for a,b in zip(live.working_mesh.submeshes, original_mesh.submeshes))
        service.undo(sid)
        assert live.hair_state == before
        service.redo(sid)
        assert live.hair_state.payload["style_name"] == "New name"


def test_incremental_protocol_acknowledges_without_document_and_finish_keeps_the_edit(editor):
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload, RUST_MESH_CANDIDATE
    authority, session = editor
    live = session.shadow_service._session(session.shadow_session_id)
    old = live.hair_state.payload
    reuse = ["groups", "bindings", "guides", "locks", "vertex_sources", "prepared_parts"]
    value = {"schema": RUST_MESH_CANDIDATE, "session_id": session.session_id,
        "hair": {**old, "revision": old["revision"] + 1, "style_name": "Finished name"}, "submeshes": [],
        "hair_update": {"version": 2, "reference": old["scalp"]["identity"], "parts": [],
                        "reuse": reuse, "base_hair_revision": old["revision"]}}
    for field in ("scalp", "references", "collisions", *reuse): value["hair"].pop(field, None)
    request = _fixtures._request(session, "transaction_request", 903)
    request["candidate"] = _atomic_write_payload(session.root, "candidate-903-hair.json", value,
        data_type="mesh_candidate_json", element_count=0, expected_root_identity=session.root_identity)
    ack = session.apply_candidate(request)
    assert ack["hair_ack"] == old["revision"] + 1 and "document" not in ack and "history_cursor" in ack
    session.finish(_fixtures._request(session, "finish_request", 904))
    assert authority._session(session.authoritative_session_id).hair_state.payload["style_name"] == "Finished name"
