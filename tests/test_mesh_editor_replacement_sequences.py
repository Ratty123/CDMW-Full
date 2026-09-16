"""Repeated replacement workflows through real importers, history and writers."""

from contextlib import ExitStack
import json
from pathlib import Path

import pytest

from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_replacement_import import (
    commit_replacement, compose_import, initial_replacement_state,
    prepare_import, reset_or_fit_import, set_part_inclusion,
)
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_editor_replacement_formats import static_fixture
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_editor_replacement_regressions import _distinct_lods, _lod_part_records
from tests.test_scene_import_normalization import _write_gltf
from tests.test_scene_importer_gltf import _write_glb


def source_variants(root):
    """Different topology, bounds and formats, all with authored UVs/normals."""
    root.mkdir()
    obj = root / "legacy dress edit.obj"
    obj.write_text(
        "mtllib missing_v10.mtl\no dress\nusemtl wrong_material\n"
        "v 12 3 7\nv 16 3 7\nv 12 5 7\n"
        "vt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n"
    )
    dae = root / "quad.dae"
    dae.write_text('''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit meter="1"/><up_axis>Y_UP</up_axis></asset>
<library_geometries><geometry id="geo"><mesh>
<source id="positions"><float_array id="positions-array" count="12">-4 0 2 -1 0 2 -4 3 2 -1 3 2</float_array><technique_common><accessor source="#positions-array" count="4" stride="3"/></technique_common></source>
<source id="uv"><float_array id="uv-array" count="8">0 0 1 0 0 1 1 1</float_array><technique_common><accessor source="#uv-array" count="4" stride="2"/></technique_common></source>
<source id="normals"><float_array id="normals-array" count="3">0 0 1</float_array><technique_common><accessor source="#normals-array" count="1" stride="3"/></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="2"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><input semantic="NORMAL" source="#normals" offset="2"/><p>0 0 0 1 1 0 2 2 0 1 1 0 3 3 0 2 2 0</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node><instance_geometry url="#geo"/></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>''', encoding="utf-8")
    paths = [obj, dae]
    for extension, positions, indices, uvs in (
        ("gltf", [(2, -8, 4), (7, -8, 4), (2, -2, 4)], [0, 1, 2], [(0, 0), (1, 0), (0, 1)]),
        ("glb", [(0, 0, -3), (4, 0, -3), (5, 2, -3), (2, 4, -3), (0, 2, -3)],
         [0, 1, 2, 0, 2, 3, 0, 3, 4], [(0, 0), (.8, 0), (1, .5), (.4, 1), (0, .5)]),
    ):
        folder = root / extension
        folder.mkdir()
        path = _write_gltf(folder, positions=positions, indices=indices, uvs=uvs,
                           normals=[(0, 0, 1)] * len(positions))
        document = json.loads(path.read_text())
        binary = folder / document["buffers"][0]["uri"]
        if extension == "glb":
            document["buffers"][0].pop("uri")
            path = folder / "pentagon.glb"
            _write_glb(path, document, binary.read_bytes())
        else:
            binary.rename(folder / "geometry data.bin")
            document["buffers"][0]["uri"] = "geometry%20data.bin"
            path.write_text(json.dumps(document))
        paths.append(path)
    return paths


def open_editor(stack, original, path, draft=None):
    mesh = parse_mesh(original, path)
    mesh.lod_levels = []
    mesh._cdmw_original_data = original
    if draft is not None:
        mesh._cdmw_mesh_layer_project_path = str(draft)
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    stack.callback(service.close_edit_session, sid)
    return service, sid


def checked_output(service, sid, original):
    snapshot = service.capture_export_snapshot(sid)
    output, report = service.rebuild_result_from_snapshot(snapshot)
    assert report.validation_status == "passed"
    fresh = prepare_replacement_output(snapshot)
    assert output.data == fresh.data
    assert output.companion_files == fresh.companion_files
    assert snapshot.original_data == original
    parsed = parse_mesh(output.data, snapshot.mesh.path)
    assert len(parsed.submeshes) == len(snapshot.mesh.submeshes)
    for binding in snapshot.replacement_state.parts:
        part = parsed.submeshes[binding.target_index]
        expected = snapshot.mesh.submeshes[binding.target_index]
        if binding.included:
            assert part.faces == expected.faces
            for actual, desired in zip(part.vertices, expected.vertices, strict=True):
                assert actual == pytest.approx(desired, abs=.001)
            for actual, desired in zip(part.uvs, expected.uvs, strict=True):
                assert actual == pytest.approx(desired, abs=.001)
        else:
            assert len(part.faces) == 1
            assert max(max(v[a] for v in part.vertices) - min(v[a] for v in part.vertices) for a in range(3)) < .002
    return output


@pytest.mark.parametrize("extension", ["pac", "pam", "pamlod"])
@pytest.mark.parametrize("scope", ["selected", "entire"])
def test_format_switches_undo_draft_reopen_and_rebuild_do_not_accumulate_state(tmp_path, extension, scope):
    original = _distinct_lods() if extension == "pac" else static_fixture(extension, levels=2 if extension == "pamlod" else 1)
    target_path = f"character/model/replacement.{extension}"
    paths = source_variants(tmp_path / "sources")
    paired = ReplacementFile("character/model/replacement.pamlod", static_fixture("pamlod", levels=2))
    with ExitStack() as stack:
        service, sid = open_editor(stack, original, target_path)
        before = service.capture_export_snapshot(sid)
        key = initial_replacement_state(before).parts[0].part_id
        untouched = list(before.mesh.submeshes[1].vertices)
        previous = None
        for step, source_index in enumerate((0, 1, 2, 3, 2, 1, 0, 3)):
            before = service.capture_export_snapshot(sid)
            pending = prepare_import(before, paths[source_index], target_part_ids=(key,) if scope == "selected" else (),
                                     dependencies=(paired,) if extension == "pam" else ())
            candidate, state = compose_import(pending, (key,))
            assert list(candidate.submeshes[1].vertices) == untouched
            assert state.parts[1].included == (scope == "selected")
            commit_replacement(service, before, candidate, state, label=f"Import {step}")
            current = checked_output(service, sid, original)
            if extension == "pac" and scope == "selected":
                for lod in range(4):
                    assert _lod_part_records(current.data, lod) == _lod_part_records(original, lod)
            service.undo(sid)
            if previous is None:
                restored = service.capture_export_snapshot(sid)
                assert restored.replacement_state is None
                assert [list(p.vertices) for p in restored.mesh.submeshes] == [list(p.vertices) for p in before.mesh.submeshes]
            else:
                restored = checked_output(service, sid, original)
                assert (restored.data, restored.companion_files) == (previous.data, previous.companion_files)
            service.redo(sid)
            restored = checked_output(service, sid, original)
            assert (restored.data, restored.companion_files) == (current.data, current.companion_files)
            previous = current
            if step == 3:
                draft = tmp_path / "draft" / "mesh_layers.json"
                service._session(sid).mesh_layer_project_path = draft
                service.retry_mesh_layer_autosave(sid)
                service, sid = open_editor(stack, original, target_path, draft)
                restored = checked_output(service, sid, original)
                assert (restored.data, restored.companion_files) == (current.data, current.companion_files)
        snapshot = service.capture_export_snapshot(sid)
        set_part_inclusion(service, snapshot, [part.part_id for part in snapshot.replacement_state.parts], False)
        checked_output(service, sid, original)
        service.undo(sid)
        assert checked_output(service, sid, original).data == previous.data
        reset_or_fit_import(service, service.capture_export_snapshot(sid), fit=True)
        checked_output(service, sid, original)
        reset_or_fit_import(service, service.capture_export_snapshot(sid))
        assert checked_output(service, sid, original).data == previous.data


def test_repeated_material_choices_failures_and_finish_keep_one_current_package(editor, tmp_path):
    from types import SimpleNamespace
    from PIL import Image
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_editor_replacement_materials import material_fixture
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_mesh_rust_replacement import command

    service, sid = editor
    original = service.capture_export_snapshot(sid)
    target, context, red = material_fixture(tmp_path, original)
    blue = tmp_path / "blue.obj"
    blue.write_text(red.read_text().replace("import.mtl", "blue.mtl").replace("12 3 7", "10 3 7"))
    blue.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd blue.dds\n")
    Image.new("RGBA", (4, 4), (20, 50, 210, 255)).save(tmp_path / "blue.dds")
    legacy = tmp_path / "legacy.obj"
    legacy.write_text(red.read_text().replace("import.mtl", "missing.mtl"))
    archive_bytes = {item.paz_file: item.paz_file.read_bytes() for rows in context.entries_by_normalized_path.values() for item in rows}
    keys = [part.part_id for part in initial_replacement_state(original).parts]
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid), tmp_path / "host", process_generation=1)
    choices = ["original", "original"]
    previous = None
    try:
        for step, (index, path, choice) in enumerate((
            (0, red, "imported"), (1, blue, "imported"),
            (0, legacy, "original"), (1, legacy, "original"),
            (0, blue, "imported"), (1, red, "imported"),
            (0, legacy, "original"), (1, legacy, "original"), (0, blue, "imported"),
        )):
            command(host, "replacement_choose", {"scope": "selected", "part_ids": [keys[index]], "source_path": str(path),
                                                   "_archive_entry": target, "_archive_dependencies": context})
            before = host.shadow_service.session_view(host.shadow_session_id)
            if choice == "original":
                with pytest.raises(ValueError, match="Missing imported material library"):
                    command(host, "replacement_apply", {"targets": [keys[index]], "materials": "imported"})
                after = host.shadow_service.session_view(host.shadow_session_id)
                assert (after.revision, after.undo_count) == (before.revision, before.undo_count)
                assert checked_output(host.shadow_service, host.shadow_session_id, original.original_data).data == previous.data
            applied = command(host, "replacement_apply", {"targets": [keys[index]], "materials": choice})
            choices[index] = choice
            current = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
            textures = [file for file in current.companion_files if file.path.endswith(".dds")]
            assert len(textures) == choices.count("imported")
            assert len({file.path.casefold() for file in current.companion_files}) == len(current.companion_files)
            material_key = applied["state"]["archive_refit_materials"]["key"]
            assert (material_key == "base") == ("imported" not in choices)
            assert command(host, "replacement_compare", {"mode": "original"})["state"]["archive_refit_materials"]["key"] == "base"
            assert command(host, "replacement_compare", {"mode": "output"})["state"]["archive_refit_materials"]["key"] == material_key
            command(host, "replacement_compare", {"mode": "edit"})
            command(host, "undo")
            if previous is not None:
                restored = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                assert (restored.data, restored.companion_files) == (previous.data, previous.companion_files)
            assert command(host, "redo")["state"]["archive_refit_materials"]["key"] == material_key
            restored = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
            assert (restored.data, restored.companion_files) == (current.data, current.companion_files)
            previous = current
        host.finish(_request(host, "finish_request", 100))
        final = checked_output(service, sid, original.original_data)
        assert (final.data, final.companion_files) == (previous.data, previous.companion_files)
        for path in (red, blue, legacy, tmp_path / "color.dds", tmp_path / "blue.dds"):
            path.unlink()
        worker = MeshDirectOutputWorker(1, service, sid, target, kind="loose_mod", output_path=tmp_path / "package")
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and len(completed) == 1
        assert (tmp_path / "package" / target.path).read_bytes() == final.data
        for file in final.companion_files:
            assert (tmp_path / "package" / file.path).read_bytes() == file.data
        for path, data in archive_bytes.items():
            assert path.read_bytes() == data
    finally:
        if not host.closed:
            host.cancel()


def test_dense_import_limit_failure_and_retry_preserve_last_build(editor, tmp_path):
    from cdmw.workers.mesh_editor_workers import MeshRebuildReportWorker

    service, sid = editor
    original = service.capture_export_snapshot(sid)
    key = initial_replacement_state(original).parts[0].part_id
    previous = None
    output_path = tmp_path / "export" / "rebuilt.pac"
    for size in (33, 256, 17):
        folder = tmp_path / f"grid-{size}"
        folder.mkdir()
        positions = [(x / 16, y / 16, .25) for y in range(size) for x in range(size)]
        indices = [index for y in range(size - 1) for x in range(size - 1)
                   for index in (y * size + x, y * size + x + 1, (y + 1) * size + x,
                                 y * size + x + 1, (y + 1) * size + x + 1, (y + 1) * size + x)]
        path = _write_gltf(folder, positions=positions, indices=indices,
                           normals=[(0, 0, 1)] * len(positions),
                           uvs=[(x / (size - 1), y / (size - 1)) for y in range(size) for x in range(size)])
        before = service.capture_export_snapshot(sid)
        undo_count = service.session_view(sid).undo_count
        pending = prepare_import(before, path, target_part_ids=(key,))
        candidate, state = compose_import(pending, (key,))
        assert len(candidate.submeshes[0].vertices) == size * size
        if size == 256:
            with pytest.raises(ValueError, match="65,535"):
                commit_replacement(service, before, candidate, state, label="Oversized import")
            after = service.session_view(sid)
            assert (after.revision, after.undo_count) == (before.mesh_revision, undo_count)
            assert checked_output(service, sid, original.original_data).data == previous.data
            assert output_path.read_bytes() == previous.data
            continue
        commit_replacement(service, before, candidate, state, label="Grid import")
        current = checked_output(service, sid, original.original_data)
        worker = MeshRebuildReportWorker(size, service, sid, output_path=output_path)
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, report: completed.append(report))
        worker.run()
        assert not errors and len(completed) == 1
        assert output_path.read_bytes() == current.data
        report = json.loads(Path(f"{output_path}.export.json").read_text())
        assert report["export_snapshot"]["output_reparse"]["status"] == "passed"
        previous = current
