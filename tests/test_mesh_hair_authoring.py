"""Hair transactions restore guides, geometry and output intent together."""
import struct
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


def test_hair_material_slots_use_declared_roles_not_filename_suffixes():
    from cdmw.services.mesh_rust_hair import hair_texture_slots
    data = b'''<Material _name="Hair"><MaterialParameterTexture _name="_baseColorTexture">
      <ResourceReferencePath_ITexture _path="texture/color_sp.dds"/></MaterialParameterTexture>
      <MaterialParameterTexture _name="_flowTexture"><ResourceReferencePath_ITexture _path="texture/0003.dds"/></MaterialParameterTexture>
      <MaterialParameterTexture _name="_specularTexture"><ResourceReferencePath_ITexture _path="texture/response.dds"/></MaterialParameterTexture></Material>'''
    slots = hair_texture_slots(data, {"texture/color_sp.dds": b"dds", "texture/0003.dds": b"dds"})
    assert [row["role"] for row in slots] == ["base_color", "flow", "specular"]
    assert [row["available"] for row in slots] == [True, True, False]
    assert all(row["material"] == "Hair" for row in slots)


def test_hair_color_changes_only_declared_base_maps_and_is_undoable(editor, monkeypatch, tmp_path):
    from cdmw.services.mesh_rust_hair import hair_color_command
    from cdmw.services import mesh_hair_color
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    source = tmp_path / "hair.dds"
    source.write_bytes(dds())
    live.working_mesh.submeshes[0].texture = TEXTURE
    live.working_mesh.submeshes[0].preview_texture_dds_path = str(source)
    live.working_mesh.submeshes[0].preview_texture_path = str(source)
    support = "character/texture/hair_f.dds"
    material = (f'<Material><MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="{TEXTURE}"/></MaterialParameterTexture>'
                f'<MaterialParameterTexture _name="_flowTexture"><ResourceReferencePath_ITexture _path="{support}"/></MaterialParameterTexture></Material>').encode()
    output = live.replacement_state
    live.replacement_state = replace(output, dependencies=tuple(
        ReplacementFile(f.path, material) if f.path == MATERIAL else f for f in output.dependencies
    ) + (ReplacementFile(support, dds()),))
    before = live.replacement_state
    calls = []
    recolored = io.BytesIO()
    Image.new("RGBA", (4, 4), (30, 80, 150, 255)).save(recolored, format="DDS", pixel_format="DXT5")
    # Binding, history and publication remain real; the codec has its own test.
    monkeypatch.setattr(mesh_hair_color, "recolor_hair_dds", lambda data, color, stop: calls.append((data, color)) or recolored.getvalue())
    result = hair_color_command(authoring, {"color": [.6, .3, .1]}, threading.Event())
    assert result == {"textures_changed": 1} and calls == [(dds(), [.6, .3, .1])]
    assert {f.path for f in live.replacement_state.companion_files} - {f.path for f in before.companion_files} == {TEXTURE}
    assert next(f.data for f in live.replacement_state.dependencies if f.path == support) == dds()
    assert next(f.data for f in live.replacement_state.dependencies if f.path == MATERIAL) == material
    hair_color_command(authoring, {"color": [.2, .5, .8]}, threading.Event())
    assert calls[-1] == (dds(), [.2, .5, .8]), "Color changes must not compound earlier tints"
    service.undo(sid)
    service.undo(sid)
    assert live.replacement_state == before


def test_hair_color_preserves_dds_header_authored_mips_and_bc3_alpha():
    import struct
    from cdmw.core.dds_native import inspect_dds_native
    from cdmw.core.texture_native import find_directxtex_texture_binary
    from cdmw.services.mesh_hair_color import recolor_hair_dds
    if find_directxtex_texture_binary() is None:
        pytest.skip("Native DirectXTex helper is not available")
    levels = []
    for size in (8, 4, 2, 1):
        image = Image.new("RGBA", (size, size), (95, 40, 12, 80))
        image.putpixel((0, 0), (130, 80, 30, 0))
        stream = io.BytesIO()
        image.save(stream, format="DDS", pixel_format="DXT5")
        levels.append(stream.getvalue())
    original = bytearray(levels[0] + b"".join(level[128:] for level in levels[1:]))
    struct.pack_into("<I", original, 8, struct.unpack_from("<I", original, 8)[0] | 0x20000)
    struct.pack_into("<I", original, 28, 4)
    struct.pack_into("<I", original, 108, struct.unpack_from("<I", original, 108)[0] | 0x400008)
    original = bytes(original)
    changed = recolor_hair_dds(original, [.2, .5, .9], threading.Event())
    assert changed != original and changed[:128] == original[:128] and len(changed) == len(original)
    for mip in inspect_dds_native(original).mip_levels:
        for offset in range(mip.offset, mip.offset + mip.byte_count, 16):
            assert changed[offset:offset+8] == original[offset:offset+8]


@pytest.mark.parametrize("failure", ["missing_binding", "cancelled"])
def test_hair_color_batch_failure_keeps_all_textures_and_history(editor, monkeypatch, tmp_path, failure):
    from cdmw.services.mesh_rust_hair import hair_color_command
    from cdmw.services import mesh_hair_color
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    second = "character/texture/second.dds"
    material = ("<Material>" + "".join(f'<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="{p}"/></MaterialParameterTexture>'
        for p in (TEXTURE, second)) + "</Material>").encode()
    live.replacement_state = replace(live.replacement_state, dependencies=(ReplacementFile(MATERIAL, material),
        ReplacementFile(TEXTURE, dds()), ReplacementFile(second, dds())))
    source = tmp_path / "hair.dds"
    source.write_bytes(dds())
    live.working_mesh.submeshes[0].texture = TEXTURE
    live.working_mesh.submeshes[0].preview_texture_dds_path = str(source)
    before = service.capture_export_snapshot(sid)
    history = service.session_view(sid).undo_count
    calls = []
    def recolor(data, color, stop):
        calls.append(color)
        if failure == "cancelled" and len(calls) == 2:
            stop.set()
        return data
    monkeypatch.setattr(mesh_hair_color, "recolor_hair_dds", recolor)
    with pytest.raises(Exception, match="cancel|preview binding"):
        hair_color_command(authoring, {"color": [.6, .3, .1]}, threading.Event())
    after = service.capture_export_snapshot(sid)
    assert after.replacement_state == before.replacement_state and after.hair_state == before.hair_state
    assert after.mesh.submeshes[0].preview_texture_dds_path == str(source)
    assert service.session_view(sid).undo_count == history


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


@pytest.mark.parametrize("included", [False, True])
def test_generated_hair_edit_preserves_output_inclusion_and_history(editor, included):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    request = _fixtures._request(authoring, "command_request", 911)
    request.update(command="replacement_include",
                   arguments={"part_ids": [live.replacement_state.parts[0].part_id], "included": included})
    authoring.run_command(request)
    before = live.replacement_state
    apply_hair_candidate(authoring, candidate(authoring, topology=True), "Draw another lock")
    after = live.replacement_state
    assert after.parts[0].included is included
    snapshot = service.capture_export_snapshot(sid)
    if included:
        validate_hair_output(snapshot)
    else:
        with pytest.raises(ValueError, match="No authored hair section is included"):
            validate_hair_output(snapshot)
    service.undo(sid)
    assert live.replacement_state == before
    service.redo(sid)
    assert live.replacement_state == after


def test_generated_hair_first_draw_after_empty_is_included(editor):
    _, authoring = editor
    live = authoring.shadow_service._session(authoring.shadow_session_id)
    drawn = candidate(authoring, topology=True)
    empty = candidate(authoring)
    empty["hair"].update(guides=[], bindings=[], locks=[])
    empty["submeshes"][0] = dict(positions=[], normals=[], uvs=[], indices=[])
    apply_hair_candidate(authoring, empty, "Start empty")
    assert not live.replacement_state.parts[0].included
    drawn["hair"]["revision"] = live.hair_state.revision + 1
    apply_hair_candidate(authoring, drawn, "Draw first lock")
    assert live.replacement_state.parts[0].included


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


def test_short_guide_survives_full_and_incremental_float_encodings():
    import struct
    value = payload()
    value["guides"][0]["points"] = [[0, 0, 0], [0, 1.0000001, 0], [0, 1.0000002, 0]]
    state = hair_state_from_payload(value)
    value = state.payload
    value["converted"] = True
    assert hair_state_from_payload(value).payload["converted"]
    for point in value["guides"][0]["points"]:
        point[:] = struct.unpack("<3f", struct.pack("<3f", *point))
    assert hair_state_from_payload(value)


@pytest.mark.parametrize("tip", [1.00000013, 1e100])
def test_guide_rejects_collapsed_or_unrepresentable_renderer_coordinates(tip):
    value = payload()
    value["guides"][0]["points"] = [[0, 0, 0], [0, 1.0000001, 0], [0, tip, 0]]
    with pytest.raises(ValueError, match="zero-length|Invalid guide"):
        hair_state_from_payload(value)


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


@pytest.mark.parametrize("mask", [[True], [False, 1], "static", [False, True, False]])
def test_physics_paint_rejects_malformed_or_mismatched_masks(mask):
    value = payload()
    value["guides"][0]["pinned"] = mask
    with pytest.raises(ValueError, match="physics paint"):
        hair_state_from_payload(value)


def test_physics_paint_metadata_survives_undo_redo_and_draft(editor, tmp_path):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    before = live.hair_state
    mesh = live.working_mesh
    old = before.payload
    painted = copy.deepcopy(old)
    painted["guides"][0]["pinned"] = [False, True]
    painted["revision"] += 1
    reuse = ["groups", "bindings", "locks", "vertex_sources", "prepared_parts"]
    update = {"hair": painted, "submeshes": [], "hair_update": {"version": 2,
        "reference": old["scalp"]["identity"], "parts": [], "reuse": reuse, "base_hair_revision": old["revision"]}}
    for field in ("scalp", "references", "collisions", *reuse):
        painted.pop(field, None)
    apply_hair_candidate(authoring, update, "Paint hair physics")
    after = live.hair_state
    assert after.payload["guides"][0]["pinned"] == [False, True]
    assert all(a is b for a, b in zip(mesh.submeshes, live.working_mesh.submeshes))
    service.undo(sid)
    assert live.hair_state == before
    service.redo(sid)
    assert live.hair_state == after
    project = tmp_path / "paint/project.json"
    live.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(sid)
    loaded = load_mesh_layer_project(copy.deepcopy(live.base_mesh), project,
                                    expected_source_asset_sha256=live.mesh_asset_source_hash)
    assert loaded["hair_state"].payload["guides"][0]["pinned"] == [False, True]


def test_hair_setup_retains_full_collision_body_separately_from_cropped_bust(editor):
    from cdmw.services.mesh_rust_hair import prepare_hair_setup
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    head = service.working_mesh(sid, clone=True)
    head.submeshes = head.submeshes[:1]
    head.submeshes[0].vertices = [(-.1,1.5,0.), (.1,1.5,0.), (0.,1.8,0.)]
    head.submeshes[0].faces = [(0,1,2)]
    body = copy.deepcopy(head)
    body.submeshes[0].vertices = [(-.1,1.49,.1),(.1,1.49,.1),(0.,1.3,.1),
                                (-.2,.5,.1),(.2,.5,.1),(0.,0.,.1)]
    body.submeshes[0].faces = [(0,1,2),(3,4,5)]
    source_data = service._session(sid).original_data
    args = dict(character="Damiane", _archive_snapshot=SimpleNamespace(mesh=head, original_data=source_data),
        _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
        _body_snapshot=SimpleNamespace(mesh=body, original_data=source_data),
        _body_archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/nude/cd_phw_00_nude_test.pac"))
    prepare_hair_setup(service, sid, args, None)
    references = service._session(sid).hair_state.payload["references"]
    bust = next(r for r in references if not r["identity"].startswith("collision:"))
    collision = next(r for r in references if r["identity"].startswith("collision:body:"))
    assert min(p[1] for p in bust["positions"]) == 1.3
    assert min(p[1] for p in collision["positions"]) == 0.
    assert len(collision["triangles"]) == 2


def test_hair_setup_preserves_temples_between_face_and_body_crown(editor):
    from cdmw.services.mesh_rust_hair import prepare_hair_setup
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    head = service.working_mesh(sid, clone=True)
    head.submeshes[0].vertices = [(-.1,1.5,0.), (.1,1.5,0.), (0.,1.8,.05)]
    head.submeshes[0].faces = [(0,1,2)]
    body = copy.deepcopy(head)
    temple = [(.12,1.6,0.), (.14,1.7,0.), (.16,1.6,.02)]
    body.submeshes[0].vertices = temple + [(-.1,1.49,.1),(.1,1.49,.1),(0.,1.3,.1)]
    body.submeshes[0].faces = [(0,1,2),(3,4,5)]
    data = service._session(sid).original_data
    prepare_hair_setup(service, sid, dict(character="Damiane",
        _archive_snapshot=SimpleNamespace(mesh=head, original_data=data),
        _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
        _body_snapshot=SimpleNamespace(mesh=body, original_data=data),
        _body_archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/nude/cd_phw_00_nude_test.pac")), None)
    scalp = service._session(sid).hair_state.payload["scalp"]
    actual = {tuple(tuple(scalp["positions"][i]) for i in face) for face in scalp["triangles"]}
    assert tuple(temple) in actual


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


@pytest.mark.parametrize("smooth", ["true", 1, None])
def test_smooth_card_binding_requires_a_boolean(smooth):
    value = payload()
    value["bindings"] = [dict(part=0, vertex=0, guide=0, segment=0,
                              t=.5, offset=[0, 0, 0], smooth=smooth)]
    with pytest.raises(ValueError, match="hair vertex binding"):
        hair_state_from_payload(value)


@pytest.mark.parametrize("incremental", [False, True])
def test_smooth_card_bindings_survive_transaction_history_and_draft(editor, tmp_path, incremental):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    before = service.capture_export_snapshot(sid)
    value = candidate(authoring, topology=True)
    for i, binding in enumerate(value["hair"]["bindings"]):
        binding.update(smooth=True, t=i / (len(value["hair"]["bindings"]) - 1))
    bindings = copy.deepcopy(value["hair"]["bindings"])
    if incremental:
        value["hair_update"] = {"version": 2, "reference": value["hair"]["scalp"]["identity"], "parts": [0]}
        for field in ("scalp", "references", "collisions"):
            value["hair"].pop(field, None)
        value["submeshes"] = value["submeshes"][:1]
    apply_hair_candidate(authoring, value, "Smooth hair cards")
    after = service.capture_export_snapshot(sid)
    assert after.hair_state.payload["bindings"] == bindings
    validate_hair_output(after)
    service.undo(sid)
    assert service.capture_export_snapshot(sid).hair_state == before.hair_state
    service.redo(sid)
    assert service.capture_export_snapshot(sid).hair_state == after.hair_state
    live = service._session(sid)
    project = tmp_path / "smooth/project.json"
    live.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(sid)
    loaded = load_mesh_layer_project(copy.deepcopy(live.base_mesh), project,
                                    expected_source_asset_sha256=live.mesh_asset_source_hash)
    assert loaded["hair_state"].payload["bindings"] == bindings


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


@pytest.mark.parametrize("repeat_slot", [False, True])
@pytest.mark.parametrize("player_variant", [True, False])
def test_authored_bundle_clones_textures_and_retains_existing_barber_choices(editor, repeat_slot, player_variant):
    from cdmw.core.pathc_format import block_infos_for, encode_pathc, parse_pathc
    from tests.test_pathc_format import build_table
    from cdmw.domain.hair_registration import read_hair_choices
    from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
    _, session = editor
    apply_hair_candidate(session, candidate(session, topology=True), "Generated bob")
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    rebuilt = session.shadow_service._replacement_output_for_snapshot(snapshot)
    stem = STEM if player_variant else STEM.removesuffix("_player")
    mesh_path = MESH.replace(STEM, stem)
    if not player_variant:
        state = snapshot.hair_state.payload
        state["template"]["path"] = mesh_path
        snapshot = replace(snapshot, hair_state=hair_state_from_payload(state),
            replacement_state=replace(snapshot.replacement_state, dependencies=tuple(
                replace(f, path=f.path.replace(STEM, stem)) for f in snapshot.replacement_state.dependencies)))
    files = registration_fixture(stem=stem)
    if repeat_slot:
        duplicate = (f'<MeshSet Index="1" DecorationParamIndex="0 1" MinValue="40 50">'
                     f'<MeshList MeshFileName="{stem}" IconPath="ui/texture/image/questimage/questionmark.dds"/>'
                     '</MeshSet>').encode()
        boundary = b'</ParamDesc>\r\n<ParamDesc Index="3"'
        files[DAMIANE_MESH_PARAM] = files[DAMIANE_MESH_PARAM].replace(boundary, duplicate + boundary)
    files[mesh_path] = snapshot.original_data
    files.update({f.path.replace(STEM, stem): f.data for f in snapshot.replacement_state.dependencies})
    files[ICON] = dds()
    table = build_table(headers=[dds()[:128]], entries=[(TEXTURE, 0, block_infos_for(dds())), (ICON, 0, block_infos_for(dds()))])
    before = copy.deepcopy(files)
    plan, pathc, _ = prepare_authored_hair(snapshot, rebuilt, files, files, encode_pathc(table))
    assert files == before
    writes = {f.path: f.data for f in (*plan.replacements, *plan.additions)}
    assert MESH not in writes and MATERIAL not in writes and TEXTURE not in writes
    assert writes[MESH.replace(STEM, NEW)] == rebuilt.data
    assert writes[MATERIAL.replace(STEM, NEW)] != files[MATERIAL.replace(STEM, stem)]
    assert read_hair_choices(writes[DAMIANE_MESH_PARAM])[:-1] == read_hair_choices(files[DAMIANE_MESH_PARAM])
    import xml.etree.ElementTree as ET
    slot = ET.fromstring(writes[DAMIANE_MESH_PARAM]).find("ParamDesc[@UIKey='hairShape']")
    assert slot[-1].get("FutureField") == "keep"  # First slot, never the placeholder.
    assert plan.choice_index == 1 + int(repeat_slot)
    assert len(parse_pathc(pathc).entries) == len(table.entries) + 2
    texture = next(f for f in plan.additions if "_texture_" in f.path)
    assert texture.data == files[TEXTURE]
    with pytest.raises(ValueError, match="already exists"):
        prepare_authored_hair(snapshot, rebuilt, files, {*files, texture.path}, encode_pathc(table))


def test_export_resolves_registered_icon_outside_the_customizeimage_folder(editor, tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.services import mesh_hair_output as output
    from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
    _, session = editor
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    rebuilt = session.shadow_service._replacement_output_for_snapshot(snapshot)
    files = registration_fixture()
    files[MESH] = snapshot.original_data
    files.update({f.path: f.data for f in snapshot.replacement_state.dependencies})
    icon_path = "ui/texture/image/questimage/custom_hair.dds"
    files[DAMIANE_MESH_PARAM] = files[DAMIANE_MESH_PARAM].replace(ICON.encode(), icon_path.encode())
    files[icon_path] = dds()
    files[output.PBD_CONFIG] = b"owned config"
    files["character/descriptors/pbd/hair.xml"] = b"owned physics profile"
    game = tmp_path / "game"
    (game / "meta").mkdir(parents=True)
    for name in ("0.pathc", "0.paver"):
        (game / "meta" / name).write_bytes(b"owned metadata")
    # The compact, signed mount list games ship since the DLC update; the legacy
    # checksum reader refuses it, so the export must read it as metadata only.
    names = b"0001\0"
    (game / "meta/0.papgt").write_bytes(bytes((0, 0, 1, 2)) + struct.pack("<III", 0x7FFF00, 0, 0)
                                        + struct.pack("<I", len(names)) + names + b"\x07" * 64)
    pamt = game / "0001/0.pamt"
    pamt.parent.mkdir()
    pamt.write_bytes(b"owned index")
    paz = pamt.with_suffix(".paz"); paz.write_bytes(b"owned archive")
    entries = {path: ArchiveEntry(path, pamt, paz, index, len(data), len(data), 0, 0)
               for index, (path, data) in enumerate(files.items())}
    monkeypatch.setattr(output, "parse_archive_pamt", lambda _: tuple(entries.values()))
    monkeypatch.setattr(output, "read_archive_entry_data", lambda entry, *_: (files[entry.path], ""))
    monkeypatch.setattr(output, "parse_pbd_config_materials", lambda _: {"hair": SimpleNamespace(filename="hair.xml")})
    class ReadComplete(Exception): pass
    def prepared(_snapshot, _rebuilt, sources, *_args, **_kwargs):
        assert sources[icon_path] == files[icon_path]
        raise ReadComplete
    monkeypatch.setattr(output, "prepare_authored_hair", prepared)
    with pytest.raises(ReadComplete):
        output.export_hair_package(snapshot, rebuilt, entries[MESH], tmp_path / "new-hair")
    assert not (tmp_path / "new-hair").exists()


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


@pytest.mark.parametrize("kind", ["png", "larger_dds"])
def test_hair_texture_edit_reencodes_images_to_the_template_layout(editor, tmp_path, kind):
    from cdmw.core.pathc_format import dds_shape
    from cdmw.services.mesh_rust_hair import hair_texture_command
    _, session = editor
    service, sid = session.shadow_service, session.shadow_session_id
    source = tmp_path / "before.dds"
    source.write_bytes(dds())
    current = service._session(sid)
    current.working_mesh.submeshes[0].preview_texture_dds_path = str(source)
    current.working_mesh.submeshes[0].preview_texture_path = str(source)
    if kind == "png":
        edited = tmp_path / "painted.png"
        Image.new("RGBA", (16, 8), (10, 120, 80, 255)).save(edited, format="PNG")
    else:
        edited = tmp_path / "larger.dds"
        Image.new("RGBA", (8, 8), (10, 120, 80, 255)).save(edited, format="DDS", pixel_format="DXT5")
    hair_texture_command(session, {"texture_path": TEXTURE, "_dds_path": str(edited)}, threading.Event())
    after = service.capture_export_snapshot(sid)
    written = after.replacement_state.companion_files[0].data
    assert dds_shape(written) == dds_shape(dds())


@pytest.mark.parametrize("bindings", ["legacy", "native", "shared_cache", "rebased"])
def test_dds_edits_keep_distinct_identical_textures_separate(editor, tmp_path, bindings):
    from pathlib import Path
    from cdmw.models import PreviewMaterialParameterInput
    from cdmw.services.mesh_dotnet_material_bindings import apply_dotnet_native_material_batch_binding
    from cdmw.services.mesh_rust_hair import hair_texture_command

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    other_logical = "character/texture/other_hair.dds" if bindings == "legacy" else "character/texture/other/hair.dds"
    material = f'<Material _pbdSimulationMaterialName="Hair"><Texture _path="{TEXTURE}"/><Texture _path="{other_logical}"/></Material>'.encode()
    live.replacement_state = replace(live.replacement_state, dependencies=(
        ReplacementFile(MATERIAL, material), ReplacementFile(TEXTURE, dds()), ReplacementFile(other_logical, dds())))
    source = tmp_path / ("hair.dds" if bindings == "legacy" else "opaque-base.dds")
    other = source if bindings == "shared_cache" else tmp_path / ("other_hair.dds" if bindings == "legacy" else "opaque-material.dds")
    source.write_bytes(dds())
    other.write_bytes(dds())
    part = live.working_mesh.submeshes[0]
    if bindings == "legacy":
        part.preview_texture_dds_path = part.preview_texture_path = str(source)
        part.preview_material_texture_dds_path = part.preview_material_texture_path = str(other)
    else:
        assert apply_dotnet_native_material_batch_binding(part, {"dds_textures": {
            "base": {"source_path": str(source), "archive_path": TEXTURE, "semantic_type": "base_color"},
            "material": {"source_path": str(other), "archive_path": other_logical, "semantic_type": "material"},
        }})
        if bindings == "rebased":
            part.preview_material_texture_inputs = tuple(replace(item,
                parameter_name=f"texture{i}", source_texture_path=item.source_dds_path,
                material_parameters=(PreviewMaterialParameterInput(parameter_name=f"texture{i}",
                    texture_path=logical),))
                for i, (item, logical) in enumerate(zip(part.preview_material_texture_inputs, (TEXTURE, other_logical))))
    modified, later = tmp_path / "green.dds", tmp_path / "blue.dds"
    Image.new("RGBA", (4, 4), (10, 120, 80, 255)).save(modified, format="DDS", pixel_format="DXT5")
    Image.new("RGBA", (4, 4), (10, 40, 180, 255)).save(later, format="DDS", pixel_format="DXT5")
    before = service.capture_export_snapshot(sid)
    hair_texture_command(authoring, {"texture_path": TEXTURE, "_dds_path": str(modified)}, threading.Event())
    first = service.capture_export_snapshot(sid)
    part = first.mesh.submeshes[0]
    assert Path(part.preview_texture_dds_path).read_bytes() == modified.read_bytes()
    assert Path(part.preview_material_texture_dds_path).read_bytes() == dds()
    assert {file.path: file.data for file in first.replacement_state.companion_files} == {TEXTURE: modified.read_bytes()}
    if bindings != "legacy":
        inputs = part.preview_material_texture_inputs
        assert Path(inputs[0].source_dds_path).read_bytes() == modified.read_bytes()
        assert inputs[1] == before.mesh.submeshes[0].preview_material_texture_inputs[1]
    # Even equal edits of same-named source textures must keep independent bindings.
    hair_texture_command(authoring, {"texture_path": other_logical, "_dds_path": str(modified)}, threading.Event())
    both = service.capture_export_snapshot(sid)
    assert both.mesh.submeshes[0].preview_texture_dds_path != both.mesh.submeshes[0].preview_material_texture_dds_path
    hair_texture_command(authoring, {"texture_path": TEXTURE, "_dds_path": str(later)}, threading.Event())
    after = service.capture_export_snapshot(sid)
    assert Path(after.mesh.submeshes[0].preview_material_texture_dds_path).read_bytes() == modified.read_bytes()
    assert {file.path: file.data for file in after.replacement_state.companion_files} == {
        TEXTURE: later.read_bytes(), other_logical: modified.read_bytes()}
    service.undo(sid)
    service.undo(sid)
    undone = service.capture_export_snapshot(sid)
    assert undone.replacement_state == first.replacement_state and undone.hair_state == first.hair_state
    assert undone.mesh.submeshes[0].preview_material_texture_dds_path == first.mesh.submeshes[0].preview_material_texture_dds_path
    service.redo(sid)
    assert service.capture_export_snapshot(sid).replacement_state == both.replacement_state
    assert source.read_bytes() == other.read_bytes() == dds()


def test_dds_edit_rejects_ambiguous_legacy_bindings_without_publishing(editor, tmp_path):
    from cdmw.services.mesh_rust_hair import hair_texture_command

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    other = "character/texture/other/hair.dds"
    material = f'<Material><Texture _path="{TEXTURE}"/><Texture _path="{other}"/></Material>'.encode()
    live.replacement_state = replace(live.replacement_state, dependencies=(
        ReplacementFile(MATERIAL, material), ReplacementFile(TEXTURE, dds()), ReplacementFile(other, dds())))
    source = tmp_path / "opaque.dds"
    source.write_bytes(dds())
    live.working_mesh.submeshes[0].preview_texture_dds_path = str(source)
    before = service.capture_export_snapshot(sid)
    with pytest.raises(ValueError, match="no resolved preview binding"):
        hair_texture_command(authoring, {"texture_path": TEXTURE, "_dds_path": str(source)}, threading.Event())
    assert live.hair_state == before.hair_state and live.replacement_state == before.replacement_state


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
    monkeypatch.setattr(mesh_archive_refit_worker,'prepare_hair_reference_source',prepare)
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
    assert not dialog.isVisible()


def test_finder_hair_buttons_disable_when_invalid_and_enable_when_compatible(finder):
    dialog, catalogue, _ = finder
    selected = row(1, role="hair", path=MESH)
    publish_rows(dialog, catalogue, [selected])
    dialog._details = replace(detail(selected), models=(SimpleNamespace(entry_id=8, path=MESH),))
    dialog._buttons()
    assert dialog._create_hair.isEnabled() and dialog._edit_hair.isEnabled()
    dialog._invalid = True
    dialog._buttons()
    assert not dialog._create_hair.isEnabled() and not dialog._edit_hair.isEnabled()


@pytest.mark.parametrize("operation", ["reshape", "cut", "cut_and_weight_edit", "delete"])
def test_existing_hair_preserves_skeletal_and_cloth_record_bytes(editor, operation):
    from tests.test_pac_skin_extra_influences import _record
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
    _, session=editor
    snapshot=session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    data=bytearray(snapshot.original_data)
    original=parse_mesh(bytes(data),MESH)
    offsets=original.submeshes[0].source_vertex_offsets
    for index, offset in enumerate(offsets):
        skin=_record(palette=(1,2,3,4,5,6),weights=(60-2*index,50+2*index,40,30,20,10,25,20),extra=(0.,7.),gate=0)
        data[offset+12:offset+16]=skin[12:16]
        data[offset+20:offset+36]=skin[20:36]
        data[offset+39]=skin[39]
    source=bytes(data)
    original=parse_mesh(source,MESH)
    assert len(original.submeshes[0].bone_weights[0]) == 4
    snapshot=replace(snapshot,original_data=source,mesh=original,replacement_state=None)
    output=initial_replacement_state(snapshot)
    mesh=copy.deepcopy(original)
    for part,binding in zip(mesh.submeshes,output.parts):
        setattr(part,PART_ID_ATTRIBUTE,binding.part_id)
    mesh.submeshes[0].vertices=[(x+.03,y,z) for x,y,z in mesh.submeshes[0].vertices]
    state=payload(hashlib.sha256(source).hexdigest(),mode='existing')
    sources = list(range(len(mesh.submeshes[0].vertices)))
    if operation in {"cut", "cut_and_weight_edit"}:
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
        if operation == "cut_and_weight_edit":
            part.bone_weights[0] = tuple(reversed(part.bone_weights[0]))
        output = replace(output, parts=tuple(replace(p, import_positions=tuple(part.vertices), import_normals=tuple(part.normals)) if p.target_index == 0 else p for p in output.parts))
    elif operation == "delete":
        output = replace(output, parts=tuple(replace(p, included=False) if p.target_index == 0 else p for p in output.parts))
        sources = [0, 0, 0]
    snapshot=replace(snapshot,mesh=mesh,replacement_state=output,hair_state=hair_state_from_payload(state))
    if operation == "cut_and_weight_edit":
        with pytest.raises(ValueError, match="unchanged non-empty vertex count"):
            prepare_replacement_output(snapshot)
        return
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


def test_cancelling_the_edited_dds_picker_keeps_the_editor_session(editor, tmp_path, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication, QFileDialog
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    _, session = editor
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process_generation = session.process_generation
    responses = []
    monkeypatch.setattr(tab, "_send_rust_message", lambda message: responses.append(message) or True)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))
    try:
        request = _fixtures._request(session, "command_request", 1)
        request.update(command="hair_texture", arguments={"texture_path": TEXTURE})
        tab.standalone_rust_protocol_queue.append(request)
        tab._start_next_rust_protocol_worker()
        deadline = time.monotonic() + 30
        while tab.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(.005)
        result = next(message for message in responses if message["event"] == "command_result")
        assert result["ok"] is False and result["error"] == "DDS selection cancelled."
        # The editor closes the session on a refusal that carries no state to return to.
        assert result["payload"].get("state")
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
    from cdmw.ui.mesh_editor import tab_direct_output
    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    _, session = editor
    tab = _tab(tmp_path)
    target = _fixtures._prepared_dds_entry(tmp_path, MESH, b"owned")
    tab.standalone_controller = SimpleNamespace(mesh_service=session.shadow_service,
                                               active_session_id=session.shadow_session_id)
    tab.standalone_export_validation_revision = 5
    tab.settings.setValue("mesh_editor/last_mod_output_dir", str(tmp_path))
    calls, errors = [], []
    monkeypatch.setattr(tab, "_mesh_output_target", lambda: target)
    monkeypatch.setattr(tab, "_current_target_entry", lambda: target)
    monkeypatch.setattr(tab, "_standalone_export_validation_ok", lambda: True)
    monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kw: calls.append((args, kw)))
    tab.status_message_requested.connect(lambda message, error: errors.append(message) if error else None)

    class AcceptedHairDialog(MeshModExportDialog):
        def exec(self):
            assert self._hair_mode
            assert self.target_stem() == NEW
            if changed:
                tab.standalone_export_validation_revision += 1
            return self.DialogCode.Accepted

    monkeypatch.setattr(tab_direct_output, "MeshModExportDialog", AcceptedHairDialog)
    try:
        tab._start_mesh_mod_build_requested()
        if changed:
            assert not calls and errors and "changed while choosing output" in errors[0]
        else:
            assert not errors and calls[0][0] == ("overlay_package", target)
            assert calls[0][1]["hair_target_stem"] == NEW
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
@pytest.mark.parametrize("body", [False, True])
def test_mounted_head_scale_uses_head_joint_and_preserves_neck(scale, body, monkeypatch):
    from cdmw.services.mesh_rust_hair import _head_component_scale
    from cdmw.modding import mesh_parser
    bones = [SimpleNamespace(index=i, parent_index=i-1, name=name, bind_matrix=[0.]*12+[0.,1.5,0.,1.])
             for i,name in enumerate(("Bip01 Neck", "Bip01 Head", "Face"))]
    skeleton = SimpleNamespace(bones=bones)
    part = SimpleNamespace(vertices=[(0.,1.,0.), (0.,1.5,0.), (0.,2.,0.)],
                           bone_indices=[[0], [1], [2]], bone_weights=[[1.], [1.], [1.]])
    mesh = SimpleNamespace(submeshes=[part])
    monkeypatch.setattr(mesh_parser, "resolve_pac_bone_palette", lambda *args: [0,1,2])
    _head_component_scale(mesh, scale, skeleton, None, b"pac", body=body)
    assert part.vertices[:2] == [(0.,1.,0.), (0.,1.5,0.)]
    assert part.vertices[2] == (0., 1.5 + .5 * scale, 0.)


@pytest.mark.parametrize("fitted_caps", [False, True])
def test_facial_details_are_head_references_not_hair_planting_surfaces(editor, fitted_caps):
    from cdmw.services.mesh_rust_hair import prepare_hair_setup
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    head = service.working_mesh(sid, clone=True)
    detail = copy.deepcopy(head)
    for part in detail.submeshes:
        part.vertices = [(p[0] + 2., p[1], p[2]) for p in part.vertices]
    scalp_positions = [list(p) for part in head.submeshes for p in part.vertices]
    if fitted_caps:
        cap = copy.deepcopy(head.submeshes[0])
        cap.name = "CD_PHW_00_Head_00_0111_Eyecover"
        cap.vertices = [(p[0] - 2., p[1], p[2]) for p in cap.vertices]
        head.submeshes.append(cap)
    expected = ([list(p) for p in cap.vertices] if fitted_caps
                else [list(p) for part in detail.submeshes for p in part.vertices])
    source_data = service._session(sid).original_data
    args = dict(character="Damiane", _archive_snapshot=SimpleNamespace(mesh=head, original_data=source_data),
                _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
                _prepared_head_details=[dict(_archive_snapshot=SimpleNamespace(mesh=detail, original_data=source_data), _archive_neutral_appearance=None, _scale=1.)])
    for _ in range(2):
        prepare_hair_setup(service, sid, args, None)
        state = service._session(sid).hair_state.payload
        assert state["scalp"]["positions"] == scalp_positions
        assert len(state["references"]) == 1
        assert state["references"][0]["identity"].startswith("head:")
        assert state["references"][0]["positions"] == expected
    assert [list(p) for part in head.submeshes[:len(head.submeshes) - int(fitted_caps)] for p in part.vertices] == scalp_positions


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
    request["label"] = "Rename hairstyle"
    request["candidate"] = _atomic_write_payload(session.root, "candidate-903-hair.json", value,
        data_type="mesh_candidate_json", element_count=0, expected_root_identity=session.root_identity)
    ack = session.apply_candidate(request)
    assert ack["hair_ack"] == old["revision"] + 1 and "document" not in ack and "history_cursor" in ack
    assert len(ack["history_entries"]) == ack["undo_count"] + ack["redo_count"]
    assert ack["history_entries"][-1]["label"] == "Rename hairstyle"
    session.finish(_fixtures._request(session, "finish_request", 904))
    assert authority._session(session.authoritative_session_id).hair_state.payload["style_name"] == "Finished name"


def test_hair_color_and_dds_update_staged_material_payload_and_undo(editor, monkeypatch, tmp_path):
    from pathlib import Path
    from cdmw.services import mesh_hair_color
    from cdmw.services.mesh_rust_hair import hair_color_command, hair_texture_command
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    source = tmp_path / "base_hair.dds"
    source.write_bytes(dds())
    part = live.working_mesh.submeshes[0]
    part.texture = TEXTURE
    part.preview_texture_dds_path = str(source)
    part.preview_texture_path = str(source)
    material = (f'<Material _pbdSimulationMaterialName="Hair"><MaterialParameterTexture _name="_baseColorTexture">'
                f'<ResourceReferencePath_ITexture _path="{TEXTURE}"/></MaterialParameterTexture></Material>').encode()
    live.replacement_state = replace(live.replacement_state, dependencies=(
        ReplacementFile(MATERIAL, material), ReplacementFile(TEXTURE, dds())))

    baseline_state = authoring.state_payload(include_document=False)
    assert baseline_state["archive_refit_materials"]["key"] == "base"

    recolored = io.BytesIO()
    Image.new("RGBA", (4, 4), (40, 140, 210, 255)).save(recolored, format="DDS", pixel_format="DXT5")
    recolored_bytes = recolored.getvalue()
    monkeypatch.setattr(mesh_hair_color, "recolor_hair_dds", lambda *_args: recolored_bytes)
    hair_color_command(authoring, {"color": [0.2, 0.55, 0.85]}, threading.Event())

    colored_state = authoring.state_payload(include_document=False)
    colored_mat = colored_state["archive_refit_materials"]
    assert colored_mat["key"] != "base"
    staged_json = json.loads((authoring.root / colored_mat["file"]["path"]).read_text(encoding="utf-8"))
    staged_hashes = {
        hashlib.sha256((authoring.root / row["file"]["path"]).read_bytes()).hexdigest()
        for row in staged_json["textures"]
    }
    assert hashlib.sha256(recolored_bytes).hexdigest() in staged_hashes

    edited = tmp_path / "custom_hair.dds"
    Image.new("RGBA", (4, 4), (200, 90, 50, 255)).save(edited, format="DDS", pixel_format="DXT5")
    edited_bytes = edited.read_bytes()
    hair_texture_command(authoring, {"texture_path": TEXTURE, "_dds_path": str(edited)}, threading.Event())

    edited_state = authoring.state_payload(include_document=False)
    edited_mat = edited_state["archive_refit_materials"]
    assert edited_mat["key"] not in {"base", colored_mat["key"]}
    edited_json = json.loads((authoring.root / edited_mat["file"]["path"]).read_text(encoding="utf-8"))
    edited_hashes = {
        hashlib.sha256((authoring.root / row["file"]["path"]).read_bytes()).hexdigest()
        for row in edited_json["textures"]
    }
    assert hashlib.sha256(edited_bytes).hexdigest() in edited_hashes

    service.undo(sid)
    assert authoring.state_payload(include_document=False)["archive_refit_materials"]["key"] == colored_mat["key"]
    service.undo(sid)
    assert authoring.state_payload(include_document=False)["archive_refit_materials"]["key"] == "base"


def test_prepare_hair_editor_session_creates_draft_and_worker_registers_saved_work(tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_saved_work_service import list_saved_work
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
    from cdmw.workers import mesh_archive_refit_worker as refit_worker
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    pac_bytes = _fixtures._pac_fixture(skinned=True)
    pamt = tmp_path / "game" / "0001" / "0.pamt"
    paz = pamt.with_suffix(".paz")
    pamt.parent.mkdir(parents=True)
    pamt.write_bytes(b"pamt")
    paz.write_bytes(b"paz")
    entry = ArchiveEntry(
        path=MESH, pamt_path=pamt, paz_file=paz, offset=0,
        orig_size=len(pac_bytes), comp_size=len(pac_bytes), flags=0, paz_index=0,
    )
    material = f'<Material _pbdSimulationMaterialName="Hair"><Texture _path="{TEXTURE}"/></Material>'.encode()
    dds_bytes = dds()
    mat_entry = ArchiveEntry(
        path=MATERIAL, pamt_path=pamt, paz_file=paz, offset=1,
        orig_size=len(material), comp_size=len(material), flags=0, paz_index=0,
    )
    tex_entry = ArchiveEntry(
        path=TEXTURE, pamt_path=pamt, paz_file=paz, offset=2,
        orig_size=len(dds_bytes), comp_size=len(dds_bytes), flags=0, paz_index=0,
    )
    head_entry = SimpleNamespace(identity="head", path="character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0001.pac")
    body_entry = SimpleNamespace(identity="body", path="character/model/1_pc/2_phw/nude/phw_00_nude_00_0001.pac")
    by_norm = {item.path.casefold(): (item,) for item in (entry, mat_entry, tex_entry)}
    by_base = {}
    for item in (entry, mat_entry, tex_entry):
        by_base.setdefault(item.basename.casefold(), []).append(item)
    dependencies = ArchiveWorkflowDependencyContext(
        entry, (entry, mat_entry, tex_entry), by_norm, {k: tuple(v) for k, v in by_base.items()}, remote=False,
    )

    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
    donor_mesh = parse_mesh(pac_bytes, MESH)
    from cdmw.workers import mesh_editor_aux_workers as aux_workers
    monkeypatch.setattr(aux_workers, "read_archive_entry_data",
                        lambda item, *_args, **_kwargs: ({MESH: pac_bytes, MATERIAL: material, TEXTURE: dds_bytes}[item.path], False, ""))

    head_mesh = ParsedMesh(
        path=head_entry.path, format="pac",
        submeshes=[SubMesh(
            name="Head", material="Head",
            vertices=[(-0.05, 0.01, 0.0), (0.05, 0.01, 0.0), (0.0, 0.11, 0.0)],
            normals=[(0.0, 0.0, 1.0)] * 3, uvs=[(0.0, 0.0)] * 3, faces=[(0, 1, 2)],
        )],
    )
    body_mesh = ParsedMesh(
        path=body_entry.path, format="pac",
        submeshes=[SubMesh(
            name="Body", material="Body",
            vertices=[(-0.05, 0.02, 0.0), (0.05, 0.02, 0.0), (0.0, 0.08, 0.0),
                      (-0.05, 0.00, 0.0), (0.05, 0.00, 0.0), (0.0, -0.05, 0.0)],
            normals=[(0.0, 0.0, 1.0)] * 6, uvs=[(0.0, 0.0)] * 6, faces=[(0, 1, 2), (3, 4, 5)],
        )],
    )
    monkeypatch.setattr(refit_worker, "prepare_hair_reference_source", lambda args, _stop: {
        **args,
        "_archive_snapshot": SimpleNamespace(
            mesh=copy.deepcopy(body_mesh if "nude" in args["_archive_entry"].path else head_mesh),
            original_data=pac_bytes,
        ),
        "_archive_neutral_appearance": None, "_archive_skeleton": None,
        "_archive_preview_lease": None, "_archive_appearance_warning": "", "_archive_material_reason": "",
    })

    draft_root = tmp_path / "drafts"
    args = {
        "character": "Damiane", "mode": "generated", "start_preset": "empty",
        "_archive_entry": head_entry, "_archive_dependencies": dependencies,
        "_body_archive_entry": body_entry, "_body_archive_dependencies": dependencies,
    }
    loaded = refit_worker.prepare_hair_editor_session(entry, dependencies, args, draft_root, threading.Event())
    try:
        sid = loaded.view.session_id
        assert loaded.draft_manifest_path is not None
        assert loaded.service._session(sid).mesh_layer_project_path is not None
        loaded.service.retry_mesh_layer_autosave(sid)
        assert loaded.draft_manifest_path.is_file()

        def fake_export(snapshot, rebuilt, _entry, out_path, **kwargs):
            (out_path / "0036").mkdir(parents=True, exist_ok=True)
            (out_path / "0036" / "0.pamt").write_bytes(b"pamt")
            (out_path / "0036" / "0.paz").write_bytes(b"paz")
            (out_path / "manifest.json").write_text(json.dumps({"name": "Test Hair"}), encoding="utf-8")
            return out_path

        monkeypatch.setattr("cdmw.services.mesh_hair_output.export_hair_package", fake_export)
        mod_out = tmp_path / "built-hair-mod"
        completed, errors = [], []
        worker = MeshDirectOutputWorker(
            1, loaded.service, sid, entry, kind="overlay_package",
            output_path=mod_out, manager_profile="dmm", saved_work_root=draft_root,
        )
        worker.completed.connect(lambda _id, res: completed.append(res))
        worker.error.connect(lambda _id, msg: errors.append(msg))
        worker.run()
        assert not errors and len(completed) == 1
        result = completed[0]
        assert result.saved_work_error == ""
        assert result.saved_work_record is not None
        assert list_saved_work(draft_root)
    finally:
        loaded.service.close_edit_session(loaded.view.session_id, force_without_saving=True)


@pytest.mark.parametrize("additive", [True, False])
def test_export_hair_package_normalizes_partial_dds_and_cleans_mod_root(tmp_path, monkeypatch, additive):
    from cdmw.app import app_folder
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
    from cdmw.core.mod_export_history import mod_metadata_path
    from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
    from cdmw.core.pappt_format import PartPrefabPart, PartPrefabRecord, PartPrefabTable, encode_pappt
    from cdmw.core.pathc_format import encode_pathc, register_dds, with_stored_mip_sizes
    from cdmw.domain.hair_registration import apply_hair_choice_xml_patch, read_hair_choices
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services import mesh_hair_output as hair_out
    from cdmw.services.dmm_send import OPERATIONS_FILE
    from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
    from tests.test_pathc_format import build_table
    from tests.test_prefab_binary_edit import _build

    workspace_root = tmp_path / "workspace"
    monkeypatch.setattr(app_folder, "workspace_folder", lambda: workspace_root)
    monkeypatch.setattr(hair_out, "parse_pbd_config_materials", lambda _: {"hair": SimpleNamespace(filename="hair.xml")})

    pac_bytes = _fixtures._pac_fixture(skinned=True)
    base_dds = dds()
    # PartialDDS (0x1701): stale compressed dwReserved1 sizes in header.
    partial_dds = bytearray(base_dds)
    partial_dds[32:48] = struct.pack("<4I", 4, 4, 0, 0)
    partial_dds = bytes(partial_dds)
    # Tiny uncompressed 0x1700 texture with zeroed dwReserved1.
    tiny_sp_dds = bytearray(base_dds)
    tiny_sp_dds[32:76] = bytes(44)
    tiny_sp_dds = bytes(tiny_sp_dds)
    icon_dds = dds()

    sp_tex = "character/texture/hair_sp.dds"
    material_xml = (
        f'<Material _pbdSimulationMaterialName="Hair">'
        f'<Texture _path="{TEXTURE}"/><Texture _path="{sp_tex}"/></Material>'
    ).encode()
    record = PartPrefabRecord(STEM, "1_pc/02_phw/head/hair", "", flag=0, parts=(PartPrefabPart("Hair"),))
    pappt_bytes = encode_pappt(PartPrefabTable((record,), tag_prefix=b"\x01"))
    prefab_bytes = _build(MESH)
    hkx_bytes = b"opaque physics"
    pbd_config = b"<PbdConfig/>"
    hair_xml = b"<HairPbd/>"
    param_xml = registration_fixture()[DAMIANE_MESH_PARAM]

    overlay_files = [
        OverlayFile(MESH, pac_bytes, len(pac_bytes), 0),
        OverlayFile(MATERIAL, material_xml, len(material_xml), 0),
        OverlayFile(TEXTURE, partial_dds, len(partial_dds), 0x1701),
        OverlayFile(sp_tex, tiny_sp_dds, len(tiny_sp_dds), 0x1700),
        OverlayFile(ICON, icon_dds, len(icon_dds), 0x301),
        OverlayFile(hair_out.PART_PREFAB_TABLE, pappt_bytes, len(pappt_bytes), 0),
        OverlayFile(record.prefab_path, prefab_bytes, len(prefab_bytes), 0),
        OverlayFile(MESH.replace("character/model/", "character/bin__/meshphysics/")[:-4] + ".hkx", hkx_bytes, len(hkx_bytes), 0),
        OverlayFile("character/descriptors/customizationmeta/meshparam_example_damian.xml", param_xml, len(param_xml), 0),
        OverlayFile(hair_out.PBD_CONFIG, pbd_config, len(pbd_config), 0),
        OverlayFile("character/descriptors/pbd/hair.xml", hair_xml, len(hair_xml), 0),
    ]
    built = build_overlay_archive(overlay_files)
    game = tmp_path / "game"
    (game / "meta").mkdir(parents=True)
    (game / "0001").mkdir(parents=True)
    pamt_path = game / "0001" / "0.pamt"
    paz_path = game / "0001" / "0.paz"
    pamt_path.write_bytes(built.pamt_bytes)
    paz_path.write_bytes(built.paz_bytes)
    (game / "meta" / "0.papgt").write_bytes(serialize_papgt((PapgtDirectory("0001", PAPGT_DEFAULT_FLAGS, built.pamt_checksum),)))
    (game / "meta" / "0.paver").write_bytes(b"1.0.0.0")
    pathc = build_table(headers=[], entries=[])
    for tex_path, tex_bytes in ((TEXTURE, base_dds), (sp_tex, base_dds), (ICON, icon_dds)):
        pathc = register_dds(pathc, tex_path, tex_bytes)
    (game / "meta" / "0.pathc").write_bytes(encode_pathc(pathc))

    # Build snapshot referencing the synthetic game PAC.
    mesh = parse_mesh(pac_bytes, MESH)
    target_entry = next(item for item in parse_archive_pamt(pamt_path) if item.path == MESH)
    state = payload(hashlib.sha256(pac_bytes).hexdigest())
    state["bindings"] = [dict(part=0, vertex=i, guide=0, segment=0, t=0., offset=[0, 0, 0])
                         for i in range(len(mesh.submeshes[0].vertices))]
    raw_snap = SimpleNamespace(
        mesh=mesh, original_data=pac_bytes, replacement_state=None,
        archive_refit_context=None,
        hair_state=hair_state_from_payload(state),
        texture_resources=(), material_generation=0,
        mesh_revision=1, native_edit_revision=0, mesh_asset_source_hash=state["template"]["sha256"],
    )
    deps = (ReplacementFile(MATERIAL, material_xml), ReplacementFile(TEXTURE, base_dds), ReplacementFile(sp_tex, tiny_sp_dds))
    rep_state = initial_replacement_state(raw_snap, target_entry, deps)
    raw_snap.mesh = mesh_with_part_ids(raw_snap, rep_state)
    raw_snap.replacement_state = rep_state
    snap = raw_snap
    rebuilt = SimpleNamespace(data=pac_bytes, companion_files=())

    custom_stem = "cd_phw_00_hair_00_named_style_player"
    custom_icon_file = tmp_path / "custom_icon.dds"
    custom_icon_bytes = bytearray(base_dds)
    custom_icon_bytes[128:136] = b"\xAA\xBB\xCC\xDD\xEE\xFF\x11\x22"
    custom_icon_file.write_bytes(bytes(custom_icon_bytes))

    # The check Hair setup runs finds nothing the export would refuse.
    assert hair_out.additive_donor_problem(target_entry, MESH, "Damiane") == ""
    out_dir = tmp_path / "exported-hair"
    notes = []
    hair_out.export_hair_package(
        snap, rebuilt, target_entry, out_dir, create_zip=True,
        use_dmm_additive_tables=additive, target_stem_override=custom_stem,
        custom_icon_path=custom_icon_file, notes=notes,
    )
    assert out_dir.is_dir()
    assert out_dir.with_name(out_dir.name + ".zip").is_file()
    for internal_name in ("modinfo.json", "hair-authoring.json", "cdmw-compatibility.json", "cdmw-baseline.zip", "README.txt"):
        assert not (out_dir / internal_name).exists()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generator"] == "Crimson Desert Mod Workbench"
    assert mod_metadata_path(out_dir, "hair-authoring.json").is_file()

    packaged = {item.path: item for item in parse_archive_pamt(out_dir / "0036" / "0.pamt")}
    if additive:
        assert manifest["table_mode"] == "dmm_additive"
        assert hair_out.PART_PREFAB_TABLE not in packaged
        assert DAMIANE_MESH_PARAM not in packaged
        ops_path = out_dir / OPERATIONS_FILE
        assert ops_path.is_file()
        ops = json.loads(ops_path.read_text(encoding="utf-8"))
        assert ops["format"] == 3 and ops["targets"][0]["file"] == hair_out.PART_PREFAB_TABLE
        assert ops["targets"][0]["intents"][0]["op"] == "list_append"
        assert ops["targets"][0]["intents"][0]["new"]["key_a"] == custom_stem
        # DMM shows the registrations as a second entry; both must be enabled.
        assert ops["modinfo"]["description"] == hair_out.HAIR_REGISTRATION_DESCRIPTION
        assert any("(item registrations)" in note and "DMM 4.4.0" in note for note in notes)
        patch_file = out_dir / (DAMIANE_MESH_PARAM + ".patch")
        assert patch_file.is_file()
        replayed = apply_hair_choice_xml_patch(param_xml, patch_file.read_bytes())
        choices = read_hair_choices(replayed)
        assert choices[-1].prefab_stem == custom_stem
    else:
        assert manifest["table_mode"] == "full_tables"
        assert hair_out.PART_PREFAB_TABLE in packaged
        assert DAMIANE_MESH_PARAM in packaged
        assert not (out_dir / OPERATIONS_FILE).exists()
        assert not (out_dir / (DAMIANE_MESH_PARAM + ".patch")).exists()
        assert notes == []

    exported_icon_path = f"ui/texture/image/customizeimage/{custom_stem}.dds"
    assert exported_icon_path in packaged
    exported_icon_data, *_ = read_archive_entry_data(packaged[exported_icon_path])
    assert exported_icon_data == with_stored_mip_sizes(bytes(custom_icon_bytes))

    tex_items = sorted([k for k in packaged if k.endswith(".dds") and k.startswith("character/texture/")])
    assert len(tex_items) == 2 and all(custom_stem in k for k in tex_items)
    by_donor = {}
    for k in tex_items:
        data, *_ = read_archive_entry_data(packaged[k])
        by_donor[k] = (packaged[k], data)
    # Match each exported file to its donor by flags/payload.
    partial_out = next((item, data) for item, data in by_donor.values() if item.flags == 0x201)
    assert partial_out[1] == with_stored_mip_sizes(base_dds)
    sp_out = next((item, data) for item, data in by_donor.values() if item.flags == 0x1700)
    assert sp_out[1] == tiny_sp_dds


def test_converted_existing_hair_allows_topology_edit_after_physics_paint(editor):
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    snap0 = service.capture_export_snapshot(sid)
    st = snap0.hair_state.payload
    st["groups"][0]["mode"] = "existing"
    st["guides"][0]["pinned"] = [True, False]
    st["converted"] = True
    st["revision"] += 1
    st["bindings"] = [b for b in st["bindings"] if b["vertex"] < len(snap0.mesh.submeshes[0].vertices)]
    # Change vertex count / faces after conversion so it must bypass cloth preserve & existing topology lock.
    changed_mesh = copy.deepcopy(snap0.mesh)
    part = changed_mesh.submeshes[0]
    part.vertices = list(part.vertices) + [part.vertices[0]]
    part.normals = list(part.normals) + [part.normals[0]]
    part.uvs = list(part.uvs) + [part.uvs[0]]
    if part.tangents:
        part.tangents = list(part.tangents) + [part.tangents[0]]
    part.bone_indices = list(part.bone_indices) + [part.bone_indices[0]]
    part.bone_weights = list(part.bone_weights) + [part.bone_weights[0]]
    part.faces = list(part.faces) + [(0, 1, len(part.vertices) - 1)]
    part.vertex_count = len(part.vertices)
    part.face_count = len(part.faces)
    rep_part = replace(snap0.replacement_state.parts[0],
                       import_positions=tuple(part.vertices), import_normals=tuple(part.normals))
    rep = replace(snap0.replacement_state, parts=(rep_part,), revision=snap0.replacement_state.revision + 1)
    prepared = service.prepare_working_mesh_replacement(
        sid, changed_mesh, replacement_state=rep, hair_state=hair_state_from_payload(st),
        replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY,
    )
    service.commit_prepared_working_mesh_replacement(
        prepared, history_action="hair_convert", history_label="Edit converted",
        output_policy=REPLACEMENT_POLICY, require_reversible_history=True,
    )
    final_snap = service.capture_export_snapshot(sid)
    validate_hair_output(final_snap)
    rebuilt = prepare_replacement_output(final_snap)
    assert rebuilt.data and len(rebuilt.data) != len(final_snap.original_data) or rebuilt.data != final_snap.original_data


def test_encode_hair_icon_dds_encodes_png_to_matching_donor_shape(tmp_path):
    from cdmw.core.dds_native import inspect_dds_native
    from cdmw.core.pathc_format import dds_shape, with_stored_mip_sizes
    from cdmw.core.texture_native import find_directxtex_texture_binary
    from cdmw.services.mesh_hair_output import encode_hair_icon_dds
    if find_directxtex_texture_binary() is None:
        pytest.skip("Native DirectXTex helper is not available")
    donor_stream = io.BytesIO()
    Image.new("RGBA", (16, 16), (30, 30, 30, 255)).save(donor_stream, format="DDS", pixel_format="DXT5")
    donor_dds = donor_stream.getvalue()
    png_path = tmp_path / "icon.png"
    Image.new("RGBA", (64, 64), (210, 80, 40, 255)).save(png_path, format="PNG")
    encoded = encode_hair_icon_dds(png_path, donor_dds, threading.Event())
    info = inspect_dds_native(encoded)
    assert not info.reason and info.width == 16 and info.height == 16
    assert dds_shape(encoded) == dds_shape(donor_dds)
    assert encoded == with_stored_mip_sizes(encoded)


def test_hair_mod_export_dialog_modes_validation_and_send_to_dmm(tmp_path):
    from PySide6.QtWidgets import QApplication, QWidget
    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog

    _app = QApplication.instance() or QApplication([])
    dmm = tmp_path / "DMM"
    (dmm / "mods").mkdir(parents=True)
    (dmm / "DMM.exe").write_bytes(b"MZ")
    parent = QWidget()
    try:
        dialog = MeshModExportDialog(
            parent,
            title="Damiane - Silver Waves",
            description="Test hair mod",
            output_parent=str(tmp_path / "out"),
            output_choice="hair_add",
            manager_profile="dmm",
            hair_mode=True,
            hair_stem=NEW,
            hair_character="Damiane",
            dmm_install=dmm,
        )
        choices = [dialog.manager.itemData(i)[0] for i in range(dialog.manager.count())]
        assert choices == ["hair_add", "hair_replace_loose", "hair_add_full"]
        assert dialog.build_button.isEnabled()
        dialog.hair_stem.setText("Invalid Stem With Spaces!")
        assert not dialog.build_button.isEnabled()
        # Switching to Replace Existing hides stem/icon and re-enables build.
        dialog.manager.setCurrentIndex(dialog.manager.findData("hair_replace_loose", role=0)
                                        if False else 1)
        assert dialog.hair_export_choice() == "hair_replace_loose"
        assert dialog.hair_stem.isHidden() and dialog.custom_icon_path.isHidden()
        assert dialog.build_button.isEnabled()
        # Send to DMM points directly to DMM/mods/<Title>.
        dialog.manager.setCurrentIndex(0)
        dialog.hair_stem.setText(NEW)
        dialog.send_to_dmm.setChecked(True)
        assert dialog.send_to_dmm_enabled()
        assert not dialog.output_parent.isEnabled() and not dialog.create_zip.isEnabled()
        assert dialog.output_path() == (dmm / "mods" / "Damiane - Silver Waves")
        dialog.reject()
    finally:
        parent.deleteLater()


def test_hair_loose_mod_replace_and_send_to_dmm_atomic_publish(editor, tmp_path, monkeypatch):
    from cdmw.app import app_folder
    from cdmw.core.pathc_format import with_stored_mip_sizes
    from cdmw.models import ArchiveEntry, ModPackageInfo
    from cdmw.services.mesh_hair_color import recolor_hair_dds
    from cdmw.services.mesh_rust_hair import hair_texture_command
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    del recolor_hair_dds  # sanity
    workspace_root = tmp_path / "workspace"
    monkeypatch.setattr(app_folder, "workspace_folder", lambda: workspace_root)
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)

    pamt = tmp_path / "game" / "0001" / "0.pamt"
    paz = tmp_path / "game" / "0001" / "0.paz"
    pamt.parent.mkdir(parents=True)
    pamt.write_bytes(b"pamt")
    paz.write_bytes(b"paz")
    target = ArchiveEntry(
        path=MESH, pamt_path=pamt, paz_file=paz, offset=0,
        orig_size=len(live.original_data), comp_size=len(live.original_data), flags=0, paz_index=0,
    )
    edited_dds_raw = bytearray(dds())
    edited_dds_raw[32:48] = struct.pack("<4I", 3, 3, 0, 0)
    edited_dds_path = tmp_path / "edited_loose.dds"
    edited_dds_path.write_bytes(bytes(edited_dds_raw))
    src = tmp_path / "src.dds"
    src.write_bytes(dds())
    live.working_mesh.submeshes[0].texture = TEXTURE
    live.working_mesh.submeshes[0].preview_texture_dds_path = str(src)
    live.working_mesh.submeshes[0].preview_texture_path = str(src)
    tex_dep = next(d for d in live.replacement_state.dependencies if d.path == TEXTURE)
    tex_dep_with_loc = ReplacementFile(TEXTURE, tex_dep.data, archive_location=(str(pamt), str(paz), 1, len(tex_dep.data), len(tex_dep.data), 0x1701, 0))
    live.replacement_state = replace(
        live.replacement_state,
        dependencies=tuple(tex_dep_with_loc if d.path == TEXTURE else d for d in live.replacement_state.dependencies),
    )
    hair_texture_command(authoring, {"texture_path": TEXTURE, "_dds_path": str(edited_dds_path)}, threading.Event())
    # Re-attach archive location on companion dependency if replacement needed.
    snap = service.capture_export_snapshot(sid)
    assert snap.replacement_state.companion_files

    mods_dir = tmp_path / "DMM" / "mods"
    mods_dir.mkdir(parents=True)
    worker = MeshDirectOutputWorker(
        1, service, sid, target, kind="loose_mod",
        output_path=mods_dir / "Replaced Hair", manager_profile="dmm",
        package_info=ModPackageInfo(title="Replaced Hair", version="1.0", description="Replace existing hair"),
        send_to_dmm_mods=mods_dir,
    )
    completed, errors = [], []
    worker.completed.connect(lambda _id, res: completed.append(res))
    worker.error.connect(lambda _id, msg: errors.append(msg))
    worker.run()
    assert not errors and len(completed) == 1
    out_folder = mods_dir / "Replaced Hair"
    assert completed[0].output_path == out_folder
    assert (out_folder / MESH).is_file()
    assert (out_folder / TEXTURE).is_file()
    assert (out_folder / TEXTURE).read_bytes() == with_stored_mip_sizes(bytes(edited_dds_raw))
    assert json.loads((out_folder / "manifest.json").read_text(encoding="utf-8"))["generator"] == "Crimson Desert Mod Workbench"
    # Second send replaces CDMW-written folder cleanly.
    (out_folder / "stale.txt").write_text("stale", encoding="utf-8")
    completed.clear()
    worker2 = MeshDirectOutputWorker(
        2, service, sid, target, kind="loose_mod",
        output_path=mods_dir / "Replaced Hair", manager_profile="dmm",
        package_info=ModPackageInfo(title="Replaced Hair", version="1.0", description="Replace existing hair"),
        send_to_dmm_mods=mods_dir,
    )
    worker2.completed.connect(lambda _id, res: completed.append(res))
    worker2.error.connect(lambda _id, msg: errors.append(msg))
    worker2.run()
    assert not errors and not (out_folder / "stale.txt").exists()
    # Foreign mod folder with same name is never overwritten.
    foreign = mods_dir / "Foreign Hair"
    foreign.mkdir()
    (foreign / "manifest.json").write_text(json.dumps({"generator": "Other Tool"}), encoding="utf-8")
    errors.clear()
    worker3 = MeshDirectOutputWorker(
        3, service, sid, target, kind="loose_mod",
        output_path=foreign, manager_profile="dmm",
        package_info=ModPackageInfo(title="Foreign Hair", version="1.0", description="Should refuse"),
        send_to_dmm_mods=mods_dir,
    )
    worker3.error.connect(lambda _id, msg: errors.append(msg))
    worker3.run()
    assert errors and "CDMW did not write" in errors[0]


def test_hair_lock_uv_rect_validation():
    value = payload()
    value["version"] = 2
    value["locks"] = [{
        "id": 1, "part": 0, "guide": 0, "vertices": [], "kind": "generated",
        "mirrored": None, "width_scale": 1.0, "cards": 6, "uv_rect": [0.25, 0.5, 0.5, 1.0],
    }]
    value["next_lock_id"] = 2
    state = hair_state_from_payload(value)
    assert state.payload["locks"][0]["uv_rect"] == [0.25, 0.5, 0.5, 1.0]

    for bad_uv in ([0.6, 0.2, 0.4, 0.8], [0.0, 0.8, 1.0, 0.2], [0.0, 1.0]):
        invalid = copy.deepcopy(value)
        invalid["locks"][0]["uv_rect"] = bad_uv
        with pytest.raises(ValueError, match="UV strip"):
            hair_state_from_payload(invalid)


def test_extract_donor_card_uv_presets_filters_negative_u_outliers_and_uses_base_mesh(editor):
    from cdmw.modding.mesh_parser import SubMesh
    from cdmw.services.mesh_rust_hair import extract_donor_card_uv_presets, template_card_uv_rect

    # Island 0 (largest): negative-U outlier; Island 1 & 2: duplicate Top strip; Island 3: Lower strip.
    part = SubMesh(
        name="cards",
        vertices=[(0.0, 0.0, 0.0)] * 16,
        normals=[(0.0, 0.0, 1.0)] * 16,
        uvs=[
            (-0.86, 0.10), (-0.40, 0.10), (-0.86, 0.90), (-0.40, 0.90), (-0.60, 0.50),
            (0.05, 0.05), (0.30, 0.05), (0.30, 0.40),
            (0.06, 0.06), (0.29, 0.06), (0.29, 0.39),
            (0.50, 0.55), (0.85, 0.55), (0.85, 0.95), (0.50, 0.95), (0.65, 0.75),
        ],
        faces=[
            (0, 1, 2), (1, 3, 2), (0, 1, 4),
            (5, 6, 7),
            (8, 9, 10),
            (11, 12, 13), (11, 13, 14), (11, 12, 15),
        ],
    )
    rect = template_card_uv_rect(part)
    assert 0.0 <= rect[0] < rect[2] <= 1.0 and 0.0 <= rect[1] < rect[3] <= 1.0
    presets = extract_donor_card_uv_presets(part)
    assert len(presets) == 2
    assert [row["label"] for row in presets] == ["Strip 1 (Top)", "Strip 2 (Lower)"]
    assert all(row["uv_rect"][0] >= 0.0 and row["uv_rect"][2] <= 1.0 for row in presets)

    _, authoring = editor
    live = authoring.shadow_service._session(authoring.shadow_session_id)
    live.base_mesh.submeshes[0].uvs = list(part.uvs)
    live.base_mesh.submeshes[0].faces = list(part.faces)
    live.base_mesh.submeshes[0].vertices = list(part.vertices)
    live.base_mesh.submeshes[0].normals = list(part.normals)
    live.working_mesh.submeshes[0].vertices = []
    live.working_mesh.submeshes[0].uvs = []
    live.working_mesh.submeshes[0].faces = []
    ui = hair_ui_state(authoring)
    assert ui["uv_presets"]["0"] == presets


def test_prepare_hair_setup_keeps_donor_scalp_cap_when_enabled(editor):
    from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE
    from cdmw.services.mesh_rust_hair import prepare_hair_setup

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    scalp_part = copy.deepcopy(live.working_mesh.submeshes[0])
    scalp_part.name = "phw_00_Hair_Base_01"
    setattr(scalp_part, PART_ID_ATTRIBUTE, "scalp-cap-part")
    live.working_mesh.submeshes[0].name = "phw_00_Hair_01"
    live.working_mesh.submeshes.append(scalp_part)
    live.base_mesh.submeshes = copy.deepcopy(live.working_mesh.submeshes)
    first_part = live.replacement_state.parts[0]
    scalp_binding = replace(first_part, part_id="scalp-cap-part", target_index=1, included=True)
    live.replacement_state = replace(live.replacement_state, parts=(first_part, scalp_binding))
    live.hair_state = None

    head = service.working_mesh(sid, clone=True)
    head.submeshes = head.submeshes[:1]
    head.submeshes[0].vertices = [(-0.1, 1.5, 0.0), (0.1, 1.5, 0.0), (0.0, 1.8, 0.0)]
    head.submeshes[0].faces = [(0, 1, 2)]
    args = dict(
        character="Damiane", mode="generated", keep_scalp_cap=True,
        _archive_snapshot=SimpleNamespace(mesh=head, original_data=live.original_data),
        _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
    )
    prepare_hair_setup(service, sid, args, None)
    st = live.hair_state.payload
    assert [(g["part"], g["mode"]) for g in st["groups"]] == [(0, "generated"), (1, "existing")]
    assert len(st["locks"]) == 1 and st["locks"][0]["part"] == 1 and st["locks"][0]["kind"] == "rigid"
    assert st["prepared_parts"] == [1]

    # Emptying drawn cards keeps the scalp cap included while excluding the empty card part.
    empty_payload = copy.deepcopy(st)
    empty_payload["revision"] += 1
    scalp_mesh = live.working_mesh.submeshes[1]
    apply_hair_candidate(
        authoring,
        {
            "hair": empty_payload,
            "submeshes": [
                {"positions": [], "normals": [], "uvs": [], "indices": []},
                {
                    "positions": [list(v) for v in scalp_mesh.vertices],
                    "normals": [list(n) for n in scalp_mesh.normals],
                    "uvs": [list(u) for u in scalp_mesh.uvs],
                    "indices": [i for face in scalp_mesh.faces for i in face],
                    "source_vertices": list(range(len(scalp_mesh.vertices))),
                },
            ],
        },
        "Empty with scalp cap",
    )
    assert [p.included for p in live.replacement_state.parts] == [False, True]
    validate_hair_output(service.capture_export_snapshot(sid))


def _forge_unique_cloth_records(live):
    """Give every donor vertex its own cloth guide record, so a record cloned
    from the wrong vertex, or a binding left on new hair, is visible."""
    from dataclasses import replace as _replace
    from cdmw.modding.pac_cloth import pac_cloth_lods
    forged = bytearray(live.original_data)
    for level in pac_cloth_lods(forged):
        for i, offset in enumerate(level.submeshes[0].source_vertex_offsets):
            struct.pack_into("<2e", forged, offset + 12, 3., 4.)
            struct.pack_into("<I", forged, offset + 24, 1 << 10 | 2 << 20 | 0xC0000000)
            forged[offset + 28:offset + 32] = bytes((255, 0, 0, 0))
            forged[offset + 32:offset + 36] = bytes((1 + i % 200, 82, 42, 27))
            forged[offset + 39] = 0xC0
    live.original_data = bytes(forged)
    live.replacement_state = _replace(live.replacement_state,
                                      target_sha256=hashlib.sha256(live.original_data).hexdigest())
    return live.original_data


def test_hybrid_existing_hair_draw_preserves_donor_skinning_and_validates(editor):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_rust_hair import prepare_hair_setup

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    pac_bytes = live.original_data
    donor = parse_mesh(pac_bytes, MESH)
    donor_sub = donor.submeshes[0]
    n_donor = len(donor_sub.vertices)
    assert n_donor >= 3

    head = copy.deepcopy(donor)
    head.submeshes = head.submeshes[:1]
    head.submeshes[0].vertices = [(-0.1, 1.5, 0.0), (0.1, 1.5, 0.0), (0.0, 1.8, 0.0)]
    head.submeshes[0].faces = [(0, 1, 2)]
    live.hair_state = None
    prepare_hair_setup(
        service, sid,
        dict(
            character="Damiane", mode="existing",
            _archive_snapshot=SimpleNamespace(mesh=head, original_data=pac_bytes),
            _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
        ),
        None,
    )

    # Keep exact donor vertices 0..n_donor-1 + append 3 generated vertices (-1).
    st = copy.deepcopy(live.hair_state.payload)
    st["revision"] += 1
    st["locks"] = [
        {
            "id": 1, "part": 0, "guide": None,
            "vertices": list(range(n_donor)), "kind": "rigid",
            "mirrored": None, "width_scale": 1.0, "cards": 0,
        },
        {
            "id": 2, "part": 0, "guide": 0,
            "vertices": [n_donor, n_donor + 1, n_donor + 2], "kind": "generated",
            "mirrored": None, "width_scale": 1.0, "cards": 6,
            "uv_rect": [0.1, 0.2, 0.4, 0.8],
        },
    ]
    st["next_lock_id"] = 3
    st["prepared_parts"] = [0]
    src_map = list(range(n_donor)) + [-1, -1, -1]
    st["vertex_sources"] = {"0": src_map}
    root_pos = list(st["scalp"]["positions"][st["scalp"]["triangles"][0][0]])
    st["guides"] = [{"root": {"triangle": 0, "barycentric": [1.0, 0.0, 0.0]}, "group": 0,
                     "points": [root_pos, [root_pos[0], root_pos[1] - 0.1, root_pos[2]]]}]
    st["bindings"] = [
        {"part": 0, "vertex": n_donor + k, "guide": 0, "segment": 0, "t": 0.5, "smooth": True, "offset": [0.01 * k, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]}
        for k in range(3)
    ]

    sub = donor.submeshes[0]
    positions = [list(v) for v in sub.vertices] + [[0.0, 1.5, 0.0], [0.05, 1.5, 0.0], [0.02, 1.4, 0.0]]
    normals = [list(n) for n in sub.normals] + [[0.0, 0.0, 1.0]] * 3
    uvs = [list(u) for u in sub.uvs] + [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8]]
    indices = [i for face in sub.faces for i in face] + [n_donor, n_donor + 1, n_donor + 2]

    apply_hair_candidate(
        authoring,
        {
            "hair": st,
            "submeshes": [{
                "positions": positions, "normals": normals, "uvs": uvs,
                "indices": indices, "source_vertices": src_map,
            }],
        },
        "Hybrid draw",
    )
    snap = service.capture_export_snapshot(sid)
    part = snap.mesh.submeshes[0]
    assert part.source_vertex_map == src_map
    assert part.bone_indices[:n_donor] == list(donor_sub.bone_indices)
    assert part.bone_weights[:n_donor] == list(donor_sub.bone_weights)
    if donor_sub.source_vertex_offsets:
        assert part.source_vertex_offsets[:n_donor] == list(donor_sub.source_vertex_offsets)
        assert part.source_vertex_offsets[n_donor:] == [-1, -1, -1]
    validate_hair_output(snap)
    rebuilt = service._replacement_output_for_snapshot(snap)
    assert rebuilt.data


def test_hybrid_draw_keeps_exact_donor_records_for_groomed_original_vertices(editor):
    """Groomed original cards keep their own PAC records; new cards drop cloth."""
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_rust_hair import prepare_hair_setup

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    from cdmw.modding.pac_cloth import pac_cloth_binding
    pac_bytes = _forge_unique_cloth_records(live)
    donor = parse_mesh(pac_bytes, MESH)
    assert all(pac_cloth_binding(pac_bytes, offset) is not None for offset in donor.submeshes[0].source_vertex_offsets)
    donor_sub = donor.submeshes[0]
    n_donor = len(donor_sub.vertices)
    assert n_donor >= 3

    head = copy.deepcopy(donor)
    head.submeshes = head.submeshes[:1]
    head.submeshes[0].vertices = [(-0.1, 1.5, 0.0), (0.1, 1.5, 0.0), (0.0, 1.8, 0.0)]
    head.submeshes[0].faces = [(0, 1, 2)]
    live.hair_state = None
    prepare_hair_setup(
        service, sid,
        dict(
            character="Damiane", mode="existing",
            _archive_snapshot=SimpleNamespace(mesh=head, original_data=pac_bytes),
            _archive_entry=SimpleNamespace(path="character/model/1_pc/2_phw/head/head/test.pac"),
        ),
        None,
    )

    # Keep exact donor vertices 0..n_donor-1 + append 3 generated vertices (-1).
    st = copy.deepcopy(live.hair_state.payload)
    st["revision"] += 1
    st["locks"] = [
        {
            "id": 1, "part": 0, "guide": None,
            "vertices": list(range(n_donor)), "kind": "rigid",
            "mirrored": None, "width_scale": 1.0, "cards": 0,
        },
        {
            "id": 2, "part": 0, "guide": 0,
            "vertices": [n_donor, n_donor + 1, n_donor + 2], "kind": "generated",
            "mirrored": None, "width_scale": 1.0, "cards": 6,
            "uv_rect": [0.1, 0.2, 0.4, 0.8],
        },
    ]
    st["next_lock_id"] = 3
    st["prepared_parts"] = [0]
    src_map = list(range(n_donor)) + [-1, -1, -1]
    st["vertex_sources"] = {"0": src_map}
    root_pos = list(st["scalp"]["positions"][st["scalp"]["triangles"][0][0]])
    st["guides"] = [{"root": {"triangle": 0, "barycentric": [1.0, 0.0, 0.0]}, "group": 0,
                     "points": [root_pos, [root_pos[0], root_pos[1] - 0.1, root_pos[2]]]}]
    st["bindings"] = [
        {"part": 0, "vertex": n_donor + k, "guide": 0, "segment": 0, "t": 0.5, "smooth": True, "offset": [0.01 * k, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]}
        for k in range(3)
    ]

    sub = donor.submeshes[0]
    # Grooming moves the original cards, so exact-position matching cannot
    # recover their donor records; only the vertex provenance can.
    positions = [[v[0], v[1] + 0.5, v[2]] for v in sub.vertices] + [[0.0, 1.5, 0.0], [0.05, 1.5, 0.0], [0.02, 1.4, 0.0]]
    normals = [list(n) for n in sub.normals] + [[0.0, 0.0, 1.0]] * 3
    uvs = [list(u) for u in sub.uvs] + [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8]]
    indices = [i for face in sub.faces for i in face] + [n_donor, n_donor + 1, n_donor + 2]

    apply_hair_candidate(
        authoring,
        {
            "hair": st,
            "submeshes": [{
                "positions": positions, "normals": normals, "uvs": uvs,
                "indices": indices, "source_vertices": src_map,
            }],
        },
        "Hybrid draw",
    )
    snap = service.capture_export_snapshot(sid)
    part = snap.mesh.submeshes[0]
    assert part.source_vertex_map == src_map
    assert part.bone_indices[:n_donor] == list(donor_sub.bone_indices)
    assert part.bone_weights[:n_donor] == list(donor_sub.bone_weights)
    if donor_sub.source_vertex_offsets:
        assert part.source_vertex_offsets[:n_donor] == list(donor_sub.source_vertex_offsets)
        assert part.source_vertex_offsets[n_donor:] == [-1, -1, -1]
    validate_hair_output(snap)
    rebuilt = service._replacement_output_for_snapshot(snap).data
    written = parse_mesh(rebuilt, MESH).submeshes[0]
    assert len(written.vertices) == n_donor + 3
    for vertex in range(n_donor):
        before = donor_sub.source_vertex_offsets[vertex]
        after = written.source_vertex_offsets[vertex]
        # Skin, guide and shading lanes follow the vertex's own donor record.
        assert rebuilt[after + 12:after + 16] == pac_bytes[before + 12:before + 16]
        assert rebuilt[after + 20:after + 40] == pac_bytes[before + 20:before + 40]
    for vertex in range(n_donor, n_donor + 3):
        assert pac_cloth_binding(rebuilt, written.source_vertex_offsets[vertex]) is None


def test_hair_import_custom_cancel_rollback_and_obj_export(editor, tmp_path):
    from cdmw.services.mesh_rust_hair import hair_import_custom_command
    from cdmw.services.mesh_rust_replacement import run_replacement_command

    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = service._session(sid)
    _forge_unique_cloth_records(live)
    hair = copy.deepcopy(live.hair_state.payload)
    hair["template"]["sha256"] = hashlib.sha256(live.original_data).hexdigest()
    live.hair_state = hair_state_from_payload(hair)

    cancelled = hair_import_custom_command(authoring, {"cancelled": True}, threading.Event())
    assert cancelled == {"status": "cancelled"}
    assert not live.hair_state.payload["converted"]

    with pytest.raises(Exception):
        hair_import_custom_command(authoring, {"source_path": str(tmp_path / "missing.obj")}, threading.Event())
    assert not live.hair_state.payload["converted"]

    custom_obj = tmp_path / "custom_hair.obj"
    custom_obj.write_text(
        "v 0.0 1.5 0.0\nv 0.1 1.5 0.0\nv 0.05 1.7 0.0\n"
        "vt 0.1 0.1\nvt 0.4 0.1\nvt 0.25 0.6\n"
        "vn 0.0 0.0 1.0\nvn 0.0 0.0 1.0\nvn 0.0 0.0 1.0\n"
        "f 1/1/1 2/2/2 3/3/3\n",
        encoding="utf-8",
    )
    # Choosing a file only opens the mapping: Hair Tools stay active until it is applied.
    revision = live.revision
    choose = hair_import_custom_command(authoring, {"source_path": str(custom_obj)}, threading.Event())
    assert choose["status"] == "choose_mapping"
    assert not live.hair_state.payload["converted"]
    assert live.revision == revision
    assert authoring.pending_replacement is not None
    assert authoring.pending_replacement.snapshot.mesh_revision == live.revision
    # Cancelling the mapping dialog keeps the hairstyle editable.
    assert run_replacement_command(authoring, "replacement_cancel", {}, threading.Event()) == {"status": "cancelled"}
    assert not live.hair_state.payload["converted"]
    assert live.revision == revision
    assert authoring.pending_hair_import_token == ""

    choose = hair_import_custom_command(authoring, {"source_path": str(custom_obj)}, threading.Event())
    assert choose["status"] == "choose_mapping"

    part_id = live.replacement_state.parts[0].part_id
    run_replacement_command(
        authoring,
        "replacement_apply",
        {"token": authoring.pending_replacement.token, "targets": [part_id], "materials": "original"},
        threading.Event(),
    )
    # Applying converts the hair and replaces the mesh in one history step.
    assert live.hair_state.payload["converted"] is True
    assert live.revision == revision + 1
    service.undo(sid)
    assert not live.hair_state.payload["converted"]
    assert live.hair_state.payload["guides"] == hair["guides"]
    service.redo(sid)
    assert live.hair_state.payload["converted"] is True
    snap = service.capture_export_snapshot(sid)
    validate_hair_output(snap)
    rebuilt = service._replacement_output_for_snapshot(snap).data
    # Imported hair is static: no vertex keeps the donor's cloth guide binding.
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
    assert any(pac_cloth_binding(live.original_data, offset) is not None
               for offset in parse_mesh(live.original_data, MESH).submeshes[0].source_vertex_offsets)
    for level in pac_cloth_lods(rebuilt):
        assert all(pac_cloth_binding(rebuilt, offset) is None for offset in level.submeshes[0].source_vertex_offsets)




def test_additive_hair_slot_conflicts_name_other_mods_at_the_same_barber_slot(tmp_path):
    from cdmw.services.mesh_hair_output import additive_hair_slot_conflicts
    rel = "character/descriptors/customizationmeta/meshparam_example_damian.xml.patch"

    def patch(folder, index):
        path = tmp_path / folder / rel
        path.parent.mkdir(parents=True)
        path.write_text(f'<xml-patch><insert into="ParamDesc" match-Index="2" match-UIKey="Hair">'
                        f'<MeshSet Index="{index}"><MeshList MeshFileName="x"/></MeshSet></insert></xml-patch>',
                        encoding="utf-8")
    patch("Mine", 7)
    patch("Other hair", 7)
    patch("Later hair", 8)
    (tmp_path / "Broken" / rel).parent.mkdir(parents=True)
    (tmp_path / "Broken" / rel).write_text("<not xml", encoding="utf-8")
    assert additive_hair_slot_conflicts(tmp_path, tmp_path / "Mine", rel, 7) == ("Other hair",)
    assert additive_hair_slot_conflicts(tmp_path, tmp_path / "Mine", rel, 9) == ()


def test_additive_donor_check_reports_a_mod_added_hairstyle(monkeypatch):
    from cdmw.services import mesh_hair_output as hair_out
    from cdmw.domain.hair_characters import hair_character
    files = registration_fixture()
    with pytest.raises(ValueError, match="Replace Existing Hairstyle"):
        hair_out._read_additive_donor(files.__getitem__, hair_character("Damiane"),
                                      MESH.replace(STEM, "cd_phw_00_hair_00_mod_only_player"))


def _forge_session_cloth(authoring):
    """Distinct donor cloth records, with the hair template following the new bytes."""
    live = authoring.shadow_service._session(authoring.shadow_session_id)
    _forge_unique_cloth_records(live)
    hair = copy.deepcopy(live.hair_state.payload)
    hair["template"]["sha256"] = hashlib.sha256(live.original_data).hexdigest()
    live.hair_state = hair_state_from_payload(hair)
    return live


def _cloth_bindings(data):
    from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
    return [pac_cloth_binding(data, offset) for level in pac_cloth_lods(data)
            for offset in level.submeshes[0].source_vertex_offsets]


def test_generated_hair_part_exports_without_donor_cloth(editor):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = _forge_session_cloth(authoring)
    assert all(binding is not None for binding in _cloth_bindings(live.original_data))
    apply_hair_candidate(authoring, candidate(authoring, topology=True), "Generate bob")
    rebuilt = service._replacement_output_for_snapshot(service.capture_export_snapshot(sid)).data
    assert all(binding is None for binding in _cloth_bindings(rebuilt))


def test_converting_donor_hair_keeps_its_cloth_physics(editor):
    """Convert to ordinary mesh is not an import: the donor's own cards keep their guides."""
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    live = _forge_session_cloth(authoring)
    snap = service.capture_export_snapshot(sid)
    state = copy.deepcopy(snap.hair_state.payload)
    state["groups"][0]["mode"] = "existing"
    state["converted"] = True
    state["revision"] += 1
    part = replace(snap.replacement_state.parts[0], import_positions=tuple(snap.mesh.submeshes[0].vertices),
                   import_normals=tuple(snap.mesh.submeshes[0].normals), source_label="Hair guides")
    output = replace(snap.replacement_state, parts=(part, *snap.replacement_state.parts[1:]),
                     revision=snap.replacement_state.revision + 1)
    prepared = service.prepare_working_mesh_replacement(
        sid, snap.mesh, replacement_state=output, hair_state=hair_state_from_payload(state),
        replace_hair_state=True, validation_output_policy=REPLACEMENT_POLICY)
    service.commit_prepared_working_mesh_replacement(prepared, history_action="hair_convert",
        history_label="Convert", output_policy=REPLACEMENT_POLICY, require_reversible_history=True)
    rebuilt = service._replacement_output_for_snapshot(service.capture_export_snapshot(sid)).data
    assert _cloth_bindings(rebuilt) == _cloth_bindings(live.original_data)
