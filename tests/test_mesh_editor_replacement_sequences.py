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


def multipart_source(root, extension, count):
    root.mkdir()
    translations = [(2, 3, 4), (-7, 5, 1), (4, -6, -2)][:count]
    expected = [tuple((offset[0] + x, offset[1] + y, offset[2]) for x, y in ((0, 0), (1, 0), (0, 1)))
                for offset in translations]
    if extension == "obj":
        path = root / "duplicate names.obj"
        lines = ["mtllib missing.mtl", "vt 0 0", "vt 1 0", "vt 0 1", "vn 0 0 1"]
        for positions in expected:
            lines.extend(("o repeated_name", "usemtl stale_material"))
            lines.extend(f"v {x} {y} {z}" for x, y, z in positions)
            lines.append("f -3/1/1 -2/2/1 -1/3/1")
        path.write_text("\n".join(lines) + "\n")
    else:
        path = _write_gltf(root, positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                           normals=[(0, 0, 1)] * 3, uvs=[(0, 0), (1, 0), (0, 1)])
        document = json.loads(path.read_text())
        document["nodes"] = [{"mesh": 0, "name": "repeated_name", "translation": offset} for offset in translations]
        document["scenes"][0]["nodes"] = list(range(count))
        path.write_text(json.dumps(document))
    return path, expected


@pytest.mark.parametrize("extension", ["obj", "gltf"])
def test_multipart_remapping_merging_and_part_count_changes_restore_exact_history(editor, tmp_path, extension):
    service, sid = editor
    original = service.capture_export_snapshot(sid)
    keys = [part.part_id for part in initial_replacement_state(original).parts]
    outputs = []
    for step, mapping in enumerate(((0, 1), (1, 0, 1), (1, 0), (0, 0, 0), (1,), (0, 1))):
        path, expected = multipart_source(tmp_path / f"source-{step}", extension, len(mapping))
        before = service.capture_export_snapshot(sid)
        pending = prepare_import(before, path)
        assert len(pending.source.mesh.submeshes) == len(mapping)
        with pytest.raises(ValueError, match="Choose a target part"):
            compose_import(pending, ["unavailable-part"] * len(mapping))
        assert service.session_view(sid).revision == before.mesh_revision
        candidate, state = compose_import(pending, [keys[index] for index in mapping])
        for target_index in range(2):
            wanted = [point for source_index, target in enumerate(mapping) if target == target_index for point in expected[source_index]]
            assert state.parts[target_index].included == bool(wanted)
            if wanted:
                assert list(candidate.submeshes[target_index].vertices) == wanted
                assert candidate.submeshes[target_index].material == original.mesh.submeshes[target_index].material
        commit_replacement(service, before, candidate, state, label=f"Multi-part import {step}")
        outputs.append(checked_output(service, sid, original.original_data).data)
    for index in range(len(outputs) - 2, -2, -1):
        service.undo(sid)
        if index >= 0:
            assert checked_output(service, sid, original.original_data).data == outputs[index]
        else:
            restored = service.capture_export_snapshot(sid)
            assert restored.replacement_state is None
            assert [list(part.vertices) for part in restored.mesh.submeshes] == [list(part.vertices) for part in original.mesh.submeshes]
    for expected_output in outputs:
        service.redo(sid)
        assert checked_output(service, sid, original.original_data).data == expected_output


@pytest.mark.parametrize("invalid", ["empty", "invalid-face", "nonfinite", "invalid-skin",
                                    "vertex-index", "negative-index", "uv-index", "normal-index"])
def test_invalid_geometry_then_valid_retry_preserves_current_replacement(editor, tmp_path, invalid):
    service, sid = editor
    original = service.capture_export_snapshot(sid)
    key = initial_replacement_state(original).parts[0].part_id
    path, _ = multipart_source(tmp_path / "good", "obj", 1)
    pending = prepare_import(original, path, target_part_ids=(key,))
    candidate, state = compose_import(pending, (key,))
    commit_replacement(service, original, candidate, state, label="Initial valid import")
    previous = checked_output(service, sid, original.original_data)
    before = service.capture_export_snapshot(sid)
    undo_count = service.session_view(sid).undo_count
    bad_path = tmp_path / "bad.obj"
    if invalid == "invalid-skin":
        bad_path = _write_gltf(tmp_path, positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                               uvs=[(0, 0), (1, 0), (0, 1)], weights=[(0, 0, 0, 0)] * 3)
    else:
        text = path.read_text()
        text = {"empty": "# no geometry\n", "invalid-face": text.replace("f -3/1/1 -2/2/1 -1/3/1", "f 0 1 2"),
                "vertex-index": text.replace("f -3/1/1", "f 4/1/1"),
                "negative-index": text.replace("f -3/1/1", "f -4/1/1"),
                "uv-index": text.replace("f -3/1/1", "f -3/4/1"),
                "normal-index": text.replace("f -3/1/1", "f -3/1/2"),
                "nonfinite": text.replace("v 2 3 4", "v nan 3 4")}[invalid]
        bad_path.write_text(text)
    with pytest.raises(ValueError):
        pending = prepare_import(before, bad_path, target_part_ids=(key,))
        candidate, state = compose_import(pending, (key,))
        commit_replacement(service, before, candidate, state, label="Invalid import")
    after = service.session_view(sid)
    assert (after.revision, after.undo_count) == (before.mesh_revision, undo_count)
    assert checked_output(service, sid, original.original_data).data == previous.data
    path.write_text(path.read_text().replace("v 2 3 4", "v 1 3 4"))
    pending = prepare_import(service.capture_export_snapshot(sid), path, target_part_ids=(key,))
    candidate, state = compose_import(pending, (key,))
    commit_replacement(service, before, candidate, state, label="Valid retry")
    assert checked_output(service, sid, original.original_data).data != previous.data


def test_gltf_skin_baking_preserves_static_positions_in_replacement(editor, tmp_path):
    service, sid = editor
    original = service.capture_export_snapshot(sid)
    key = initial_replacement_state(original).parts[0].part_id
    path = _write_gltf(tmp_path, positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                       normals=[(0, 0, 1)] * 3, uvs=[(0, 0), (1, 0), (0, 1)], weights=[(1, 0, 0, 0)] * 3)
    pending = prepare_import(original, path, target_part_ids=(key,))
    assert not pending.source.mesh.has_bones
    assert not pending.source.mesh.submeshes[0].bone_weights
    expected = [(0, 1, 0), (1, 1, 0), (0, 2, 0)]
    assert list(pending.source.mesh.submeshes[0].vertices) == expected
    candidate, state = compose_import(pending, (key,))
    assert list(candidate.submeshes[0].vertices) == expected
    commit_replacement(service, original, candidate, state, label="Baked static glTF import")
    checked_output(service, sid, original.original_data)


def test_same_texture_path_and_timestamp_reimports_use_current_pixels(editor, tmp_path):
    from io import BytesIO
    import os
    from PIL import Image
    from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
    from tests.test_mesh_editor_replacement_materials import material_fixture

    service, sid = editor
    original = service.capture_export_snapshot(sid)
    target, context, model = material_fixture(tmp_path, original)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(original).parts[0].part_id
    texture = tmp_path / "color.dds"
    metadata = texture.stat()
    outputs = []
    for color in ((210, 30, 60, 255), (20, 50, 210, 255), (20, 190, 90, 255), (210, 30, 60, 255)):
        Image.new("RGBA", (4, 4), color).save(texture)
        os.utime(texture, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        snapshot = service.capture_export_snapshot(sid)
        pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
        files = prepare_imported_materials(pending, (key,), tmp_path)
        candidate, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
        commit_replacement(service, snapshot, candidate, state, label="Updated source texture")
        output = checked_output(service, sid, original.original_data)
        textures = [file for file in output.companion_files if file.path.endswith(".dds")]
        assert len(textures) == 1
        with Image.open(BytesIO(textures[0].data)) as decoded:
            assert decoded.convert("RGBA").getpixel((0, 0)) == pytest.approx(color, abs=4)
        outputs.append(textures[0])
    assert len({file.data for file in outputs}) == 3
    assert outputs[0] == outputs[-1]


def test_offline_material_draft_reloads_preserve_edits_and_partial_restores(editor, tmp_path):
    from types import SimpleNamespace
    from PIL import Image
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from tests.test_mesh_editor_replacement_materials import material_fixture
    from tests.test_mesh_rust_authoring_exact_output import _candidate_reference, _request
    from tests.test_mesh_rust_replacement import command

    service, sid = editor
    original = service.capture_export_snapshot(sid)
    sources = tmp_path / "imported sources"
    sources.mkdir()
    target, context, model = material_fixture(sources, original)
    keys = [part.part_id for part in initial_replacement_state(original).parts]
    draft = tmp_path / "draft" / "mesh_layers.json"
    replacement_paths = source_variants(tmp_path / "other models")
    previous = None
    previous_state = None
    previous_material_key = None
    imported_files = {}
    with ExitStack() as stack:
        for generation in range(4):
            if generation:
                service, sid = open_editor(stack, original.original_data, original.mesh.path, draft)
                loaded = service.capture_export_snapshot(sid)
                assert loaded.replacement_state == previous_state
                current = checked_output(service, sid, original.original_data)
                assert (current.data, current.companion_files) == (previous.data, previous.companion_files)
            host = RustMeshAuthoringSession.create(
                SimpleNamespace(mesh_service=service, active_session_id=sid),
                tmp_path / f"host-{generation}", process_generation=generation + 1,
            )
            stack.callback(lambda host=host: host.cancel() if not host.closed else None)
            if generation:
                assert host.state_payload()["archive_refit_materials"]["key"] == previous_material_key
            if generation == 0:
                for index, color in enumerate(((210, 30, 60, 255), (20, 50, 210, 255))):
                    Image.new("RGBA", (4, 4), color).save(sources / "color.dds")
                    if index:
                        model.write_text(model.read_text().replace("v 12 3 7", "v 10 3 7"))
                    command(host, "replacement_choose", {"scope": "selected", "part_ids": [keys[index]],
                        "source_path": str(model), "_archive_entry": target, "_archive_dependencies": context})
                    command(host, "replacement_apply", {"targets": [keys[index]], "materials": "imported"})
                current = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                imported_files = {file.path: file.data for file in current.companion_files if file.path.endswith(".dds")}
                assert len(imported_files) == 2 and len(set(imported_files.values())) == 2
                for path in (model, model.with_suffix(".mtl"), sources / "color.dds"):
                    path.unlink()
            elif generation in (1, 2):
                # Continue editing the frozen import after its OBJ, MTL and DDS disappeared.
                before = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                reference = _candidate_reference(host, request_id=31, first_x=8 + generation)
                host.apply_candidate({**_request(host, "transaction_request", 31), "candidate": reference})
                edited = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                assert edited.data != before.data and edited.companion_files == before.companion_files
                command(host, "undo")
                assert checked_output(host.shadow_service, host.shadow_session_id, original.original_data).data == before.data
                command(host, "redo")
                assert checked_output(host.shadow_service, host.shadow_session_id, original.original_data).data == edited.data
                # Restore target 1 first, then target 0, using different geometry formats.
                index = 2 - generation
                command(host, "replacement_choose", {"scope": "selected", "part_ids": [keys[index]],
                    "source_path": str(replacement_paths[0 if generation == 1 else 3])})
                command(host, "replacement_apply", {"targets": [keys[index]], "materials": "original"})
                restored = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                retained = {file.path: file.data for file in restored.companion_files if file.path.endswith(".dds")}
                assert len(retained) == 2 - generation
                assert all(imported_files[path] == data for path, data in retained.items())
                command(host, "replacement_include", {"part_ids": keys, "included": False})
                checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                command(host, "replacement_include", {"part_ids": keys, "included": True})
                assert checked_output(host.shadow_service, host.shadow_session_id, original.original_data).data == restored.data
            else:
                assert not previous.companion_files
                before = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
                command(host, "replacement_fit")
                command(host, "replacement_reset")
                assert checked_output(host.shadow_service, host.shadow_session_id, original.original_data).data == before.data
            current = checked_output(host.shadow_service, host.shadow_session_id, original.original_data)
            material_key = host.state_payload()["archive_refit_materials"]["key"]
            assert (material_key == "base") == (generation >= 2)
            if generation < 2:
                textures = host.archive_refit_material_cache[material_key]["textures"]
                # Restored originals also recover their captured preview DDS.
                assert {index for row in textures for index in row["material_indices_by_lod"][0]} == {0, 1}
            assert command(host, "replacement_compare", {"mode": "original"})["state"]["archive_refit_materials"]["key"] == "base"
            assert command(host, "replacement_compare", {"mode": "output"})["state"]["archive_refit_materials"]["key"] == material_key
            command(host, "replacement_compare", {"mode": "edit"})
            host.finish(_request(host, "finish_request", 99))
            exported = checked_output(service, sid, original.original_data)
            assert (exported.data, exported.companion_files) == (current.data, current.companion_files)
            previous = exported
            previous_state = service.capture_export_snapshot(sid).replacement_state
            previous_material_key = material_key
            service._session(sid).mesh_layer_project_path = draft
            service.retry_mesh_layer_autosave(sid)
            service.close_edit_session(sid)


@pytest.mark.parametrize("material_choice", ["original", "imported"])
def test_obj_material_regions_within_one_object_keep_separate_target_bindings(editor, tmp_path, material_choice):
    from io import BytesIO
    from PIL import Image
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
    from tests.test_mesh_editor_replacement_materials import material_fixture

    service, sid = editor
    original = service.capture_export_snapshot(sid)
    target, context, model = material_fixture(tmp_path, original)
    colors = ((210, 30, 60, 255), (20, 50, 210, 255))
    Image.new("RGBA", (4, 4), colors[1]).save(tmp_path / "blue.dds")
    model.with_suffix(".mtl").write_text("newmtl red\nKd 1 1 1\nmap_Kd color.dds\nnewmtl blue\nKd 1 1 1\nmap_Kd blue.dds\n")
    model.write_text("mtllib import.mtl\no Combined dress edit\n"
        "v 12 3 7\nv 16 3 7\nv 12 5 7\nv -4 1 2\nv -2 1 2\nv -4 3 2\n"
        "vt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n"
        "usemtl red\nf 1/1/1 2/2/1 3/3/1\nusemtl blue\nf 4/1/1 5/2/1 6/3/1\n")
    keys = tuple(part.part_id for part in initial_replacement_state(original).parts)
    dependencies = capture_replacement_dependencies(target, context)
    pending = prepare_import(original, model, entry=target, dependencies=dependencies)
    assert [part.material for part in pending.source.mesh.submeshes] == ["red", "blue"]
    files = prepare_imported_materials(pending, keys, tmp_path) if material_choice == "imported" else None
    candidate, state = compose_import(pending, keys, material_choice=material_choice, companion_files=files)
    commit_replacement(service, original, candidate, state, label="Replace separate material regions")
    output = checked_output(service, sid, original.original_data)
    parsed = parse_mesh(output.data, original.mesh.path)
    assert [len(part.vertices) for part in parsed.submeshes] == [3, 3]
    assert all(part.included for part in state.parts)
    assert parsed.submeshes[0].vertices[0] == pytest.approx((12, 3, 7), abs=.001)
    assert parsed.submeshes[1].vertices[0] == pytest.approx((-4, 1, 2), abs=.001)
    if material_choice == "imported":
        files = {file.path: file.data for file in output.companion_files}
        sidecar = next(file for file in output.companion_files if file.path.endswith(".pac_xml"))
        bindings = _parse_archive_model_sidecar_texture_bindings(sidecar.data.decode(), sidecar_path=sidecar.path)
        for index, color in enumerate(colors):
            binding = next(row for row in bindings if row.submesh_name == f"target{index}")
            with Image.open(BytesIO(files[binding.texture_path])) as decoded:
                assert decoded.convert("RGBA").getpixel((0, 0)) == pytest.approx(color, abs=4)
    else:
        assert not output.companion_files
