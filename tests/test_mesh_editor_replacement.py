from dataclasses import replace
from pathlib import Path
import hashlib
import json
import threading

import pytest

from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE, bound_part_indices
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_replacement_import import (
    initial_replacement_state, prepare_import, compose_import, commit_replacement,
    set_part_inclusion, reset_or_fit_import,
)
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original


@pytest.fixture
def editor():
    data, _ = _minimal_two_part_pac_original()
    # The old preview fixture had empty influence rows in a skinned layout.
    # Give its real binary records valid rigid donor weights for writer tests.
    raw = bytearray(data)
    for lod in (parse_mesh(data, "replacement.pac").submeshes,):
        for part in lod:
            for offset in part.source_vertex_offsets:
                raw[offset + 28] = 255
    data = bytes(raw)
    mesh = parse_mesh(data, "character/model/replacement.pac")
    mesh._cdmw_original_data = data
    service = MeshService()
    view = service.open_edit_session(mesh)
    yield service, view.session_id
    service.close_edit_session(view.session_id)


def source_obj(tmp_path):
    path = tmp_path / "asymmetric.obj"
    path.write_text("o asymmetric\nv 12 3 7\nv 16 3 7\nv 12 5 8\nf 1 2 3\n")
    return path


@pytest.mark.parametrize("extension", ["obj", "dae", "gltf", "glb"])
def test_import_preserves_coordinates_and_unselected_parts(editor, tmp_path, extension):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    state = initial_replacement_state(snapshot)
    key = state.parts[0].part_id
    if extension == "obj":
        path = source_obj(tmp_path)
    elif extension == "dae":
        path = tmp_path / "asymmetric.dae"
        path.write_text('''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit meter="1"/><up_axis>Y_UP</up_axis></asset>
<library_geometries><geometry id="geo"><mesh>
<source id="positions"><float_array id="positions-array" count="9">12 3 7 16 3 7 12 5 8</float_array><technique_common><accessor source="#positions-array" count="3" stride="3"/></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="1"><input semantic="VERTEX" source="#vertices" offset="0"/><p>0 1 2</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node><instance_geometry url="#geo"/></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>''', encoding="utf-8")
    else:
        from tests.test_scene_import_normalization import _write_gltf
        path = _write_gltf(tmp_path, positions=[(12, 3, 7), (16, 3, 7), (12, 5, 8)], indices=[0, 1, 2])
        if extension == "glb":
            from tests.test_scene_importer_gltf import _write_glb
            document = json.loads(path.read_text())
            binary = (tmp_path / document["buffers"][0].pop("uri")).read_bytes()
            path = tmp_path / "asymmetric.glb"
            _write_glb(path, document, binary)
    pending = prepare_import(snapshot, path, target_part_ids=(key,))
    mesh, state = compose_import(pending, (key,))
    assert list(mesh.submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
    untouched = snapshot.mesh.submeshes[1]
    assert list(mesh.submeshes[1].vertices) == list(untouched.vertices)
    assert mesh.submeshes[1].material == untouched.material
    commit_replacement(service, snapshot, mesh, state, label="Import replacement")
    output, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(session_id))
    assert report.validation_status == "passed"


def test_all_parts_exclusion_keeps_editable_mesh_and_reenable(editor):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    state = initial_replacement_state(snapshot)
    keys = [part.part_id for part in state.parts]
    set_part_inclusion(service, snapshot, keys, False)
    excluded = service.capture_export_snapshot(session_id)
    assert [list(part.vertices) for part in excluded.mesh.submeshes] == [list(part.vertices) for part in snapshot.mesh.submeshes]
    bundle = prepare_replacement_output(excluded)
    parsed = parse_mesh(bundle.data, state.target_path)
    assert len(parsed.submeshes) == 2
    for part in parsed.submeshes:
        assert len(part.vertices) == 3
        assert len(part.faces) == 1
        assert max(max(p[a] for p in part.vertices) - min(p[a] for p in part.vertices) for a in range(3)) < .001
    set_part_inclusion(service, excluded, keys, True)
    restored = service.capture_export_snapshot(session_id)
    assert [list(part.vertices) for part in restored.mesh.submeshes] == [list(part.vertices) for part in snapshot.mesh.submeshes]


def test_identity_reorder_cannot_redirect_output(editor):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    state = initial_replacement_state(snapshot)
    set_part_inclusion(service, snapshot, (state.parts[0].part_id,), False)
    snapshot = service.capture_export_snapshot(session_id)
    snapshot.mesh.submeshes.reverse()
    assert bound_part_indices(snapshot.mesh, snapshot.replacement_state)[state.parts[0].part_id] == 1
    bundle = prepare_replacement_output(snapshot)
    assert len(parse_mesh(bundle.data, state.target_path).submeshes) == 2
    setattr(snapshot.mesh.submeshes[0], PART_ID_ATTRIBUTE, "lost")
    with pytest.raises(ValueError, match="identit"):
        prepare_replacement_output(snapshot)


def test_history_restores_geometry_and_optional_state_together(editor, tmp_path):
    service, session_id = editor
    before = service.capture_export_snapshot(session_id)
    state = initial_replacement_state(before)
    pending = prepare_import(before, source_obj(tmp_path))
    mesh, state = compose_import(pending, (state.parts[0].part_id,))
    commit_replacement(service, before, mesh, state, label="Import replacement")
    service.undo(session_id)
    assert service._session(session_id).replacement_state is None
    assert service.session_view(session_id).output_policy == "exact_game_asset"
    assert list(service.working_mesh(session_id).submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
    service.redo(session_id)
    assert service._session(session_id).replacement_state == state
    assert service.session_view(session_id).output_policy == "replacement_game_asset"
    reset_or_fit_import(service, service.capture_export_snapshot(session_id), fit=True)
    reset_or_fit_import(service, service.capture_export_snapshot(session_id))
    assert list(service.working_mesh(session_id).submeshes[0].vertices) == list(mesh.submeshes[0].vertices)


def test_repeated_selected_import_and_failed_writer_preserve_scene(editor, tmp_path, monkeypatch):
    service, session_id = editor
    original = service.capture_export_snapshot(session_id)
    key = initial_replacement_state(original).parts[0].part_id
    for offset in (0, 10):
        path = source_obj(tmp_path)
        if offset:
            path.write_text("o replacement\nv 22 3 7\nv 26 3 7\nv 22 5 8\nf 1 2 3\n")
        before = service.capture_export_snapshot(session_id)
        pending = prepare_import(before, path, target_part_ids=(key,))
        mesh, state = compose_import(pending, (key,))
        commit_replacement(service, before, mesh, state, label="Import replacement")
    before = service.capture_export_snapshot(session_id)
    assert list(before.mesh.submeshes[1].vertices) == list(original.mesh.submeshes[1].vertices)
    history = service.session_view(session_id).undo_count
    monkeypatch.setattr("cdmw.services.mesh_replacement_import.prepare_replacement_output",
                        lambda *_: (_ for _ in ()).throw(ValueError("writer rejected")))
    with pytest.raises(ValueError, match="writer rejected"):
        set_part_inclusion(service, before, (key,), False)
    assert service._session(session_id).replacement_state == before.replacement_state
    assert service.session_view(session_id).undo_count == history
    assert service.session_view(session_id).revision == before.mesh_revision


def test_replacement_draft_roundtrip_is_versioned_and_restores_placement(editor, tmp_path):
    service, session_id = editor
    original = service.capture_export_snapshot(session_id)
    key = initial_replacement_state(original).parts[0].part_id
    pending = prepare_import(original, source_obj(tmp_path), target_part_ids=(key,))
    mesh, state = compose_import(pending, (key,))
    commit_replacement(service, original, mesh, state, label="Import replacement")
    snapshot = service.capture_export_snapshot(session_id)
    set_part_inclusion(service, snapshot, (key,), False)
    path = tmp_path / "draft" / "mesh_layers.json"
    session = service._session(session_id)
    session.mesh_layer_project_path = path
    service.retry_mesh_layer_autosave(session_id)
    assert json.loads(path.read_text())["format"] == "mesh_layer_project_v2"
    seed = parse_mesh(original.original_data, original.mesh.path)
    seed._cdmw_original_data = original.original_data
    seed._cdmw_mesh_layer_project_path = str(path)
    reopened = MeshService()
    view = reopened.open_edit_session(seed)
    try:
        loaded = reopened.capture_export_snapshot(view.session_id)
        assert loaded.replacement_state == session.replacement_state
        assert view.output_policy == "replacement_game_asset"
        assert list(loaded.mesh.submeshes[0].vertices) == list(mesh.submeshes[0].vertices)
        assert not loaded.replacement_state.parts[0].included
        assert prepare_replacement_output(loaded).data == prepare_replacement_output(service.capture_export_snapshot(session_id)).data
    finally:
        reopened.close_edit_session(view.session_id)


def test_cancelled_preparation_and_imported_material_rejection_are_inert(editor, tmp_path):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    stop = threading.Event()
    stop.set()
    from cdmw.models import RunCancelled
    with pytest.raises(RunCancelled):
        prepare_import(snapshot, source_obj(tmp_path), stop_event=stop)
    pending = prepare_import(snapshot, source_obj(tmp_path))
    with pytest.raises(ValueError, match="complete prepared material"):
        compose_import(pending, (pending.target_part_ids[0],), material_choice="imported")
    assert service.session_view(session_id).undo_count == 0
    assert service._session(session_id).replacement_state is None
