"""Authored weights through detached import, history and real PAC serialization."""

from dataclasses import replace
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_glb_assets import transpose
from cdmw.modding.mesh_parser import parse_mesh, resolve_pac_bone_palette
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_import import prepare_import, compose_import, commit_replacement, mesh_with_part_ids
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette
from tests.test_mesh_neutral_face_editing import _appearance
from tests.test_scene_importer_gltf import _write_glb
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import command


@pytest.fixture
def editor():
    original, _ = _minimal_two_part_pac_original()
    skeleton = Skeleton(bones=[Bone(index=i, name=f"bone{i}", name_hash=0x12340000 + i,
                                    position=(float(i), 0.0, 0.0)) for i in range(8)])
    order = (7, 5, 2, 0, 1, 3, 4, 6)
    original = _with_resolvable_bone_palette(original, tuple(skeleton.bones[i].name_hash for i in order))
    data = bytearray(original)
    parsed = parse_mesh(original, "character/model/armor/target.pac")
    for level in parsed.lod_levels or [parsed.submeshes]:
        for part in level:
            for offset in part.source_vertex_offsets:
                data[offset + 28] = 255
                data[offset + 39] = 63
    mesh = parse_mesh(bytes(data), parsed.path)
    mesh._cdmw_original_data = bytes(data)
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    service._session(sid).skeleton = skeleton
    assert resolve_pac_bone_palette(bytes(data), skeleton) == order
    yield service, sid, order
    service.close_edit_session(sid)


def source_glb(tmp_path, *, names=("bone5", "bone2", "unused_other_rig"), mismatch=False,
               zero_weights=False, extras=0, with_skin=True, extension="glb", seven_influences=False):
    chunks, views, accessors = [], [], []
    def accessor(rows, code, kind, component):
        width = {"VEC3": 3, "VEC2": 2, "VEC4": 4, "SCALAR": 1, "MAT4": 16}[kind]
        values = [v for row in rows for v in row]
        raw = struct.pack("<" + code * len(values), *values)
        views.append({"buffer": 0, "byteOffset": sum(map(len, chunks)), "byteLength": len(raw)})
        chunks.append(raw + b"\0" * (-len(raw) % 4))
        accessors.append({"bufferView": len(views) - 1, "componentType": component, "count": len(rows), "type": kind})
        return len(accessors) - 1
    attrs = {"POSITION": accessor([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "f", "VEC3", 5126),
             "NORMAL": accessor([(0, 0, 1)] * 3, "f", "VEC3", 5126),
             "TEXCOORD_0": accessor([(0, 0), (1, 0), (0, 1)], "f", "VEC2", 5126),
             "JOINTS_0": accessor([(0, 1, 0, 0)] * 3, "H", "VEC4", 5123),
             "WEIGHTS_0": accessor([(0, 0, 0, 0)] * 3 if zero_weights else [(.25, .75, 0, 0), (1, 0, 0, 0), (.6, .4, 0, 0)], "f", "VEC4", 5126)}
    if seven_influences:
        names = tuple(f"bone{i}" for i in range(8))
        attrs.update({"JOINTS_0": accessor([(0, 1, 2, 3)] * 3, "H", "VEC4", 5123),
                      "WEIGHTS_0": accessor([(1 / 7,) * 4] * 3, "f", "VEC4", 5126),
                      "JOINTS_1": accessor([(4, 5, 6, 0)] * 3, "H", "VEC4", 5123),
                      "WEIGHTS_1": accessor([(1 / 7, 1 / 7, 1 / 7, 0)] * 3, "f", "VEC4", 5126)})
    indices = accessor([(0,), (1,), (2,)], "H", "SCALAR", 5123)
    matrices = []
    for i, name in enumerate(names):
        target_index = int(name[4:]) if name.startswith("bone") and name[4:].isdigit() else 7
        matrices.append(transpose((2., 0., 0., 10. - target_index + (1 if mismatch and i == 1 else 0),
                                   0., 2., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1.)))
    inverse = accessor(matrices, "f", "MAT4", 5126)
    document = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": sum(map(len, chunks))}],
                "bufferViews": views, "accessors": accessors, "materials": [{"name": "armour"}],
                "meshes": [{"primitives": [{"attributes": attrs, "indices": indices, "material": 0}]}],
                "nodes": [{"name": "armour", "mesh": 0, "translation": [100, 500, 900]},
                          *[{"name": name, "translation": [700 + i, 800, 900]} for i, name in enumerate(names)]],
                "skins": [{"joints": list(range(1, len(names) + 1)), "inverseBindMatrices": inverse}],
                "scenes": [{"nodes": list(range(len(names) + 1))}], "scene": 0}
    if with_skin:
        document["nodes"][0]["skin"] = 0
    if extras:
        # A second unskinned node tests that its donor transfer cannot erase
        # the first node's authored rows during a many-to-one merge.
        plain = dict(attrs)
        plain.pop("JOINTS_0")
        plain.pop("WEIGHTS_0")
        document["meshes"].append({"primitives": [{"attributes": plain, "indices": indices, "material": 0}]})
        document["scenes"][0]["nodes"].append(len(document["nodes"]))
        document["nodes"].append({"name": "plain", "mesh": 1} if extras == 1 else
                                 {"name": "second_skinned", "mesh": 0, "skin": 0})
    binary = b"".join(chunks)
    path = tmp_path / f"authored.{extension}"
    if extension == "glb":
        _write_glb(path, document, binary)
    else:
        (tmp_path / "authored.bin").write_bytes(binary)
        document["buffers"][0]["uri"] = "authored.bin"
        path.write_text(json.dumps(document))
    return path


@pytest.mark.parametrize("extension", ["glb", "gltf"])
def test_authored_skin_survives_pac_output_undo_redo_and_repeated_import(editor, tmp_path, extension):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, extension=extension))
    key = pending.target_part_ids[0]
    assert pending.source.mesh.submeshes[0].vertices == [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    assert not any("Baked glTF skin" in note for note in pending.source.diagnostics)
    mesh, state = compose_import(pending, (key,))
    assert mesh.submeshes[0].bone_indices == [(1, 2), (1,), (1, 2)]
    assert mesh.submeshes[0].bone_weights[0] == (.25, .75)
    assert mesh.submeshes[1].bone_weights == before.mesh.submeshes[1].bone_weights
    commit_replacement(service, before, mesh, state, label="Import authored rig")
    written = parse_mesh(prepare_replacement_output(service.capture_export_snapshot(sid)).data, state.target_path)
    first = dict(zip(written.submeshes[0].bone_indices[0], written.submeshes[0].bone_weights[0]))
    assert first == pytest.approx({1: .25, 2: .75}, abs=1 / 255)
    assert 0 not in first  # Original donor was rigid on palette slot zero.
    service.undo(sid)
    assert service.working_mesh(sid).submeshes[0].bone_weights == before.mesh.submeshes[0].bone_weights
    service.redo(sid)
    again = service.capture_export_snapshot(sid)
    pending = prepare_import(again, source_glb(tmp_path, extension=extension), target_part_ids=(key,))
    second, _ = compose_import(pending, (key,))
    assert second.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
    assert second.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights


def test_authored_skin_uses_display_transform_once_and_exports_original_bind_space(editor, tmp_path):
    service, sid, order = editor
    snapshot = service.capture_export_snapshot(sid)
    pending = prepare_import(snapshot, source_glb(tmp_path))
    appearance = replace(_appearance(), bone_palette=order)
    matrices = list(appearance.skin_matrices)
    matrices[5], matrices[2] = matrices[3], matrices[7]
    appearance = replace(appearance, skin_matrices=tuple(matrices))
    neutral_state = replace(pending.state, neutral_appearance=appearance, neutral_coordinates=True)
    expected = appearance.to_neutral(pending.source.mesh)
    shown = appearance.to_neutral(mesh_with_part_ids(snapshot, neutral_state))
    snapshot = replace(snapshot, mesh=shown, replacement_state=neutral_state)
    pending = prepare_import(snapshot, source_glb(tmp_path))
    mesh, state = compose_import(pending, (pending.target_part_ids[0],))
    assert mesh.submeshes[0].vertices == expected.submeshes[0].vertices
    assert mesh.submeshes[0].vertices != [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    output = prepare_replacement_output(replace(snapshot, mesh=mesh, replacement_state=state))
    written = parse_mesh(output.data, state.target_path)
    for actual, expected in zip(written.submeshes[0].vertices, [(10, 0, 0), (12, 0, 0), (10, 2, 0)]):
        assert actual == pytest.approx(expected, abs=.002)
    assert dict(zip(written.submeshes[0].bone_indices[0], written.submeshes[0].bone_weights[0])) == pytest.approx({1: .25, 2: .75}, abs=1 / 255)


@pytest.mark.parametrize("options,match", [
    ({"zero_weights": True}, "non-zero joint weights"),
    ({"with_skin": False}, "no skin binding"),
])
def test_malformed_authored_rig_refuses_without_mutating_session(editor, tmp_path, options, match):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    with pytest.raises(ValueError, match=match):
        prepare_import(before, source_glb(tmp_path, **options))
    after = service.capture_export_snapshot(sid)
    assert after.mesh_revision == before.mesh_revision
    assert after.mesh.submeshes[0].bone_weights == before.mesh.submeshes[0].bone_weights
    assert after.replacement_state is None


@pytest.mark.parametrize("options,match", [
    ({"names": ("foreign", "bone2", "unused")}, "no unique match"),
    ({"names": ("bone5", "bone5", "unused")}, "no unique match"),
    ({"mismatch": True}, "bind frames disagree"),
    ({"seven_influences": True}, "more than six bones"),
])
def test_unkeepable_rig_reaches_the_mapping_step_and_keep_is_refused(editor, tmp_path, options, match):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, **options))
    keep = pending.skin.option("preserve")
    assert pending.skin.rigged and not keep.available and match in keep.reason
    assert pending.skin.option("transfer").available
    with pytest.raises(ValueError, match=match):
        compose_import(pending, (pending.target_part_ids[0],), skin_policy="preserve")
    after = service.capture_export_snapshot(sid)
    assert after.mesh_revision == before.mesh_revision
    assert after.replacement_state is None


def test_authored_rig_requires_resolved_target_and_rejects_mixed_merge(editor, tmp_path):
    service, sid, _ = editor
    snapshot = service.capture_export_snapshot(sid)
    snapshot.mesh.interchange_skeleton = None
    pending = prepare_import(snapshot, source_glb(tmp_path))
    assert "matching skeleton" in pending.skin.option("preserve").reason
    with pytest.raises(ValueError, match="matching skeleton"):
        compose_import(pending, (pending.target_part_ids[0],), skin_policy="preserve")
    snapshot = service.capture_export_snapshot(sid)
    pending = prepare_import(snapshot, source_glb(tmp_path, extras=1))
    key = pending.target_part_ids[0]
    with pytest.raises(ValueError, match="separate game parts"):
        compose_import(pending, (key, key))


def test_authored_skin_requires_encodable_target_and_preserves_many_to_one(editor, tmp_path):
    service, sid, _ = editor
    snapshot = service.capture_export_snapshot(sid)
    pending = prepare_import(snapshot, source_glb(tmp_path, extras=2))
    key = pending.target_part_ids[0]
    mesh, state = compose_import(pending, (key, key))
    assert mesh.submeshes[0].bone_indices == [(1, 2), (1,), (1, 2)] * 2
    written = parse_mesh(prepare_replacement_output(replace(snapshot, mesh=mesh, replacement_state=state)).data, state.target_path)
    assert len(written.submeshes[0].vertices) == 6
    for vertex in (0, 3):
        assert dict(zip(written.submeshes[0].bone_indices[vertex], written.submeshes[0].bone_weights[vertex])) == pytest.approx({1: .25, 2: .75}, abs=1 / 255)
    snapshot.mesh.submeshes[0].source_skin_weight_layout = "unknown"
    with pytest.raises(ValueError, match="proven PAC layout"):
        compose_import(pending, (key, key))


def test_default_scene_import_keeps_static_bake_behavior(tmp_path):
    path = source_glb(tmp_path)
    result = import_scene_mesh_with_report(path)
    assert not result.mesh.has_bones
    assert not result.mesh.submeshes[0].bone_weights
    assert any("Baked glTF skin" in note for note in result.diagnostics)


def test_neutral_rust_replacement_handoff_retains_authored_weights_through_finish(editor, tmp_path):
    service, sid, order = editor
    appearance = replace(_appearance(), bone_palette=order)
    matrices = list(appearance.skin_matrices)
    matrices[5], matrices[2] = matrices[3], matrices[7]
    service._session(sid).neutral_appearance = replace(appearance, skin_matrices=tuple(matrices))
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid), tmp_path / "host", process_generation=1)
    try:
        path = source_glb(tmp_path)
        entry = ArchiveEntry(service.working_mesh(sid).path, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
        context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        result = command(host, "replacement_choose", {"scope": "entire", "source_path": str(path),
                         "_archive_entry": entry, "_archive_dependencies": context})
        key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
        command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        host.finish(_request(host, "finish_request", 2))
        snapshot = service.capture_export_snapshot(sid)
        written = parse_mesh(prepare_replacement_output(snapshot).data, snapshot.mesh.path)
        assert dict(zip(written.submeshes[0].bone_indices[0], written.submeshes[0].bone_weights[0])) == pytest.approx({1: .25, 2: .75}, abs=1 / 255)
        assert written.submeshes[0].vertices[0] == pytest.approx((10, 0, 0), abs=.002)
    finally:
        if not host.closed:
            host.cancel()


def _written_row(snapshot, part, vertex):
    written = parse_mesh(prepare_replacement_output(snapshot).data, snapshot.mesh.path)
    return dict(zip(written.submeshes[part].bone_indices[vertex], written.submeshes[part].bone_weights[vertex]))


def test_transfer_replaces_a_foreign_rig_with_the_original_weights(editor, tmp_path):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, names=("foreign", "bone2", "unused")))
    assert pending.skin.default_policy == ""
    notes = []
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="transfer", skin_notes=notes)
    # The rows are in the editor at once, from the original part's rigid slot 0.
    assert mesh.submeshes[0].bone_indices == [(0,)] * 3
    assert mesh.submeshes[0].bone_weights == [(1.0,)] * 3
    assert not mesh.submeshes[0].interchange_skin
    # bone2 alone proves the bind frame, so the geometry still moves into it.
    assert mesh.submeshes[0].vertices == [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    assert not any("used as authored" in note for note in notes)
    assert any("transferred 3 vertices" in note for note in notes)
    commit_replacement(service, before, mesh, state, label="Import with transferred weights")
    assert _written_row(service.capture_export_snapshot(sid), 0, 0) == pytest.approx({0: 1.0}, abs=1 / 255)


def test_reduce_keeps_the_six_strongest_influences(editor, tmp_path):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, seven_influences=True))
    assert pending.skin.over_capacity == 3
    assert pending.skin.option("reduce").available and not pending.skin.option("preserve").available
    notes = []
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="reduce", skin_notes=notes)
    assert all(len(row) == 6 for row in mesh.submeshes[0].bone_indices)
    assert all(sum(row) == pytest.approx(1.0) for row in mesh.submeshes[0].bone_weights)
    assert any("reduced 3 vertices to six bones" in note for note in notes)
    commit_replacement(service, before, mesh, state, label="Import with reduced weights")
    row = _written_row(service.capture_export_snapshot(sid), 0, 0)
    assert len(row) == 6 and sum(row.values()) == pytest.approx(1.0, abs=6 / 255)


def test_unrigged_parts_hold_transferred_weights_after_apply(editor, tmp_path):
    service, sid, _ = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, extras=1))
    first, second = pending.target_part_ids
    assert pending.skin.default_policy == "preserve"
    notes = []
    mesh, _state = compose_import(pending, (first, second), skin_notes=notes)
    # Kept weights are untouched; the plain part has weights before any write.
    assert mesh.submeshes[0].bone_indices == [(1, 2), (1,), (1, 2)]
    assert mesh.submeshes[1].bone_weights and len(mesh.submeshes[1].bone_weights) == 3
    assert [note for note in notes if "transferred" in note] and not [note for note in notes if "preserved" in note]


def test_static_original_drops_imported_weights_by_default(editor, tmp_path):
    service, sid, _ = editor
    snapshot = service.capture_export_snapshot(sid)
    for part in snapshot.mesh.submeshes:
        part.bone_indices, part.bone_weights = [], []
    pending = prepare_import(snapshot, source_glb(tmp_path))
    assert pending.skin.static_target and pending.skin.default_policy == "transfer"
    assert "dropped" in pending.skin.summary


def test_rust_mapping_step_reports_weights_and_applies_the_choice(editor, tmp_path):
    service, sid, _ = editor
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid), tmp_path / "host", process_generation=1)
    try:
        path = source_glb(tmp_path, mismatch=True)
        entry = ArchiveEntry(service.working_mesh(sid).path, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
        context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        result = command(host, "replacement_choose", {"scope": "entire", "source_path": str(path),
                         "_archive_entry": entry, "_archive_dependencies": context})
        pending = result["state"]["replacement"]["pending"]
        weights = pending["weights"]
        assert weights["rigged"] and weights["default"] == ""
        options = {option["policy"]: option for option in weights["options"]}
        assert not options["preserve"]["enabled"] and "bind frames disagree" in options["preserve"]["reason"]
        assert options["transfer"]["enabled"]
        key = pending["targets"][0]["id"]
        result = command(host, "replacement_apply", {"targets": [key], "materials": "original", "weights": "transfer"})
        notes = result["state"]["replacement"]["weight_notes"]
        assert any("transferred 3 vertices" in note for note in notes)
        assert any("used as authored" in note for note in notes)
        assert service.working_mesh(sid).submeshes[0].bone_indices == [(0,)] * 3
    finally:
        if not host.closed:
            host.cancel()


def test_fbx_replacement_is_converted_and_tracked_by_its_own_file(editor, tmp_path, monkeypatch):
    import shutil

    from cdmw.services import fbx_blender_conversion
    from cdmw.services.mesh_replacement_import import verify_import_sources

    service, sid, _ = editor
    glb = source_glb(tmp_path)
    fbx = tmp_path / "dragon.fbx"
    fbx.write_bytes(b"Kaydara FBX Binary  \x00stand-in")
    calls = []

    def convert(source, output_dir, blender, *, on_log=None, stop_event=None):
        calls.append((source, blender))
        output_dir.mkdir(parents=True, exist_ok=True)
        return shutil.copyfile(glb, output_dir / "dragon.glb")

    monkeypatch.setattr(fbx_blender_conversion, "convert_fbx_for_import", convert)
    pending = prepare_import(service.capture_export_snapshot(sid), fbx, blender="blender.exe", work_dir=tmp_path / "work")
    assert calls == [(fbx.resolve(), "blender.exe")]
    assert pending.label == "dragon.fbx" and Path(pending.source_path).name == "dragon.glb"
    assert pending.skin.default_policy == "preserve"
    assert str(fbx.resolve()) in dict(pending.source_files)
    fbx.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed during preparation"):
        verify_import_sources(pending)
    with pytest.raises(ValueError, match="working folder"):
        prepare_import(service.capture_export_snapshot(sid), fbx)
