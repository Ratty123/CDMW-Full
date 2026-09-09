"""Interchange regressions exercised through real OBJ serialization and PAC rebuild."""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import pytest

from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_importer import build_mesh
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import parse_pac
from tests.test_static_skin_weight_export import _skinned_pac


def _export(tmp_path):
    raw, mesh = _skinned_pac()
    mesh._cdmw_original_data = raw
    path = export_obj(mesh, str(tmp_path), "source")[0]
    return raw, mesh, path


def test_untouched_skinned_obj_rebuild_preserves_donor_skin(tmp_path):
    raw, original, path = _export(tmp_path)
    imported = import_obj(path)
    rebuilt = parse_pac(build_mesh(imported, raw), original.path)
    assert rebuilt.submeshes[0].bone_indices == original.submeshes[0].bone_indices
    assert rebuilt.submeshes[0].bone_weights == original.submeshes[0].bone_weights
    assert rebuilt.submeshes[0].vertices == original.submeshes[0].vertices


def test_obj_donor_restore_does_not_hide_authored_bone_changes(tmp_path):
    raw, original, path = _export(tmp_path)
    imported = import_obj(path)
    imported.submeshes[0].bone_indices = copy.deepcopy(original.submeshes[0].bone_indices)
    imported.submeshes[0].bone_indices[0] = (31,)
    with pytest.raises(ValueError, match="bone_indices"):
        build_mesh(imported, raw)


def test_blender_object_order_is_restored_before_edit_operations(tmp_path):
    raw, original, _path = _export(tmp_path / "baseline")
    mesh = copy.deepcopy(original)
    mesh.submeshes.append(copy.deepcopy(mesh.submeshes[0]))
    mesh.submeshes[0].name = "Z_part"
    mesh.submeshes[1].name = "A_part"
    mesh.total_vertices *= 2
    mesh.total_faces *= 2
    path = tmp_path / "parts"
    exported = export_obj(mesh, str(path), "parts")[0]
    from pathlib import Path

    obj = Path(exported)
    text = obj.read_text()
    prefix, z, a = text.split("\no ")
    # Rebase the global face indices along with the two object blocks.
    def rebase(block, delta):
        lines = []
        for line in block.splitlines():
            if line.startswith("f "):
                line = "f " + " ".join(
                    "/".join(str(int(i) + delta) if i else "" for i in corner.split("/"))
                    for corner in line[2:].split()
                )
            lines.append(line)
        return "\n".join(lines)
    count = len(original.submeshes[0].vertices)
    obj.write_text(prefix + "\no " + rebase(a, -count) + "\no " + rebase(z, count) + "\n")
    imported = import_obj(str(obj))
    assert [s.name for s in imported.submeshes] == ["Z_part", "A_part"]
    assert imported.submeshes[0].source_vertex_map == list(range(count))

    # Some OBJ writers put one global vertex bank before all object groups.
    lines = obj.read_text().splitlines()
    vertex_lines = [line for line in lines if line.startswith(('v ', 'vt ', 'vn '))]
    object_lines = [line for line in lines if not line.startswith(('v ', 'vt ', 'vn '))]
    obj.write_text('\n'.join(vertex_lines + object_lines) + '\n')
    imported = import_obj(str(obj))
    assert len(imported.submeshes) == 2
    for part in imported.submeshes:
        assert sorted(part.source_vertex_map) == list(range(count))


@pytest.mark.parametrize("translate", [False, True])
@pytest.mark.parametrize("leading_space", [False, True])
def test_serialized_neutral_obj_restores_source_coordinates(tmp_path, translate, leading_space):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance

    raw, source = _skinned_pac()
    if leading_space:
        renamed = bytearray(raw)
        renamed[raw.index(source.submeshes[0].name.encode())] = ord(' ')
        raw = bytes(renamed)
        source = parse_pac(raw, source.path)
        assert source.submeshes[0].name.startswith(' ')
    source._cdmw_original_data = raw
    matrix = (1.2, 0., .4, 0., 0., 1., 0., 0., -.3, 0., .8, 0., .2, .1, -.1, 1.)
    appearance = NeutralMeshAppearance("owned/head.pabc", (0, 1, 2), (matrix,) * 3)
    neutral = appearance.to_neutral(source)
    neutral._cdmw_neutral_appearance = appearance
    obj = export_obj(neutral, str(tmp_path), "neutral")[0]
    imported = import_obj(obj)
    if translate:
        imported.submeshes[0].vertices = [(x + .01, y, z) for x,y,z in imported.submeshes[0].vertices]
    rebuilt = build_mesh(imported, raw)
    if not translate:
        assert rebuilt == raw
    else:
        redisplayed = appearance.to_neutral(parse_pac(rebuilt, source.path))
        for actual, expected in zip(redisplayed.submeshes[0].vertices, imported.submeshes[0].vertices):
            assert actual == pytest.approx(expected, abs=3e-5)
    assert parse_pac(rebuilt).submeshes[0].bone_indices == source.submeshes[0].bone_indices


def test_invalid_neutral_manifest_is_rejected(tmp_path):
    raw, source, obj = _export(tmp_path)
    sidecar = Path(obj + ".meta.json")
    payload = json.loads(sidecar.read_text())
    payload["neutral_appearance"] = {"version": 1, "bone_palette": [10], "skin_matrices": [[1.] * 16]}
    sidecar.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="neutral appearance bone palette"):
        build_mesh(import_obj(obj), raw)


def test_blender_duplicate_material_suffix_retains_matching_source_identity(tmp_path):
    raw, source = _skinned_pac()
    source._cdmw_original_data = raw
    source.submeshes.append(copy.deepcopy(source.submeshes[0]))
    source.submeshes[0].name, source.submeshes[1].name = 'first', 'second'
    obj = Path(export_obj(source, str(tmp_path), 'materials')[0])
    material = source.submeshes[0].material
    text = obj.read_text().replace('usemtl ' + material + '\n', 'usemtl ' + material + '.001\n', 1)
    obj.write_text(text)
    mtl = obj.with_suffix('.mtl')
    mtl.write_text(mtl.read_text() + mtl.read_text().replace('newmtl ' + material, 'newmtl ' + material + '.001'))
    imported = import_obj(str(obj))
    assert not getattr(imported, '_cdmw_sidecar_warnings', ())
    assert [part.material for part in imported.submeshes] == [material, material]
    obj.write_text(text.replace('usemtl ' + material + '.001', 'usemtl unrelated_material'))
    assert any(w['code']=='sidecar_material_name_changed' for w in import_obj(str(obj))._cdmw_sidecar_warnings)


def test_resolved_export_texture_is_accepted_without_changing_source_material(tmp_path):
    raw, source, obj = _export(tmp_path)
    part = source.submeshes[0]
    mtl = Path(obj).with_suffix('.mtl')
    mtl.write_text(f'newmtl {part.material}\nmap_Kd referenced_files/character/actual_diffuse.dds\n')
    sidecar = Path(obj + '.meta.json')
    payload = json.loads(sidecar.read_text())
    payload['exported_material_textures'] = {part.material: 'referenced_files/character/actual_diffuse.dds'}
    sidecar.write_text(json.dumps(payload))
    assert build_mesh(import_obj(obj), raw) == raw
    preview_import = import_obj(obj)
    preview_import.submeshes[0].texture = 'actual_diffuse.dds'
    assert build_mesh(preview_import, raw) == raw
    preview_import.submeshes[0].texture = 'changed_after_import.dds'
    with pytest.raises(ValueError, match='texture'):
        build_mesh(preview_import, raw)
    mtl.write_text(f'newmtl {part.material}\nmap_Kd another_texture.dds\n')
    with pytest.raises(ValueError, match='texture changed'):
        build_mesh(import_obj(obj), raw)


@pytest.mark.parametrize('duplicate', ['same', 'opposite', None])
def test_blender_duplicate_triangle_cleanup_preserves_original_lods(tmp_path, duplicate):
    from tests.test_mesh_pac_topology_serializer import _pac_fixture

    raw = bytearray(_pac_fixture(skinned=True))
    original = parse_pac(bytes(raw), 'duplicate.pac')
    if duplicate:
        part = original.submeshes[0]
        face = part.faces[0] if duplicate == 'same' else tuple(reversed(part.faces[0]))
        struct.pack_into('<HHH', raw, part.source_index_offset + 6, *face)
    raw = bytes(raw)
    original = parse_pac(raw, 'duplicate.pac')
    original._cdmw_original_data = raw
    obj = Path(export_obj(original, str(tmp_path), 'duplicate')[0])
    lines = obj.read_text().splitlines()
    last_face = max(i for i,line in enumerate(lines) if line.startswith('f '))
    obj.write_text('\n'.join(lines[:last_face] + lines[last_face+1:]) + '\n')
    imported = import_obj(str(obj))
    if duplicate:
        assert build_mesh(imported, raw) == raw
    else:
        with pytest.raises(ValueError, match='topology changed'):
            build_mesh(imported, raw)


def test_application_roundtrip_preview_uses_neutral_mesh_but_rebuild_keeps_source(tmp_path):
    from cdmw.core.archive_mesh_import_build import build_mesh_import_preview
    from cdmw.core.archive_mesh_import_scene_preview import parsed_mesh_to_preview_model
    from cdmw.models import ArchiveEntry
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance

    raw, source = _skinned_pac()
    source._cdmw_original_data = raw
    matrix = (1.2, 0., .4, 0., 0., 1., 0., 0., -.3, 0., .8, 0., .2, .1, -.1, 1.)
    context = NeutralMeshAppearance('owned/head.pabc', (0, 1, 2), (matrix,) * 3)
    neutral = context.to_neutral(source)
    neutral._cdmw_neutral_appearance = context
    obj = Path(export_obj(neutral, str(tmp_path / 'export'), 'neutral')[0])
    payload = tmp_path / 'owned.paz'
    payload.write_bytes(raw)
    entry = ArchiveEntry(path=source.path, pamt_path=tmp_path / '0.pamt', paz_file=payload,
                         offset=0, comp_size=len(raw), orig_size=len(raw), flags=0, paz_index=0)
    result = build_mesh_import_preview(entry, obj, import_mode='roundtrip')
    expected = parsed_mesh_to_preview_model(neutral)
    assert result.rebuilt_data == raw
    assert payload.read_bytes() == raw
    for actual, wanted in zip(result.preview_model.meshes[0].positions, expected.meshes[0].positions):
        assert actual == pytest.approx(wanted, abs=1e-6)


def _normal_split_obj(tmp_path):
    from tests.test_mesh_pac_topology_serializer import _pac_fixture
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance

    raw = _pac_fixture(skinned=True)
    source = parse_pac(raw, 'normal-split.pac')
    source._cdmw_original_data = raw
    matrix = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., .2, .1, -.1, 1.)
    appearance = NeutralMeshAppearance('owned/split.pabc', (0, 1, 2), (matrix,) * 3)
    displayed = appearance.to_neutral(source)
    displayed._cdmw_neutral_appearance = appearance
    obj = Path(export_obj(displayed, str(tmp_path), 'split')[0])
    lines = obj.read_text().splitlines()
    first_face = next(i for i, line in enumerate(lines) if line.startswith('f '))
    normal_count = sum(line.startswith('vn ') for line in lines)
    lines.insert(first_face, 'vn 0.0 1.0 0.0')
    last_face = max(i for i, line in enumerate(lines) if line.startswith('f '))
    corners = lines[last_face].split()
    vertex, uv, _normal = corners[1].split('/')
    corners[1] = f'{vertex}/{uv}/{normal_count + 1}'
    lines[last_face] = ' '.join(corners)
    obj.write_text('\n'.join(lines) + '\n')
    imported = import_obj(str(obj))
    assert len(imported.submeshes[0].vertices) == len(source.submeshes[0].vertices) + 1
    return raw, source, appearance, imported


@pytest.mark.parametrize('translate', [False, True])
def test_blender_normal_splits_recover_proven_source_slots(tmp_path, translate):
    raw, source, appearance, imported = _normal_split_obj(tmp_path)
    if translate:
        imported.submeshes[0].vertices = [(x + .01, y, z) for x, y, z in imported.submeshes[0].vertices]
    rebuilt = build_mesh(imported, raw)
    recovered = parse_pac(rebuilt, source.path)
    assert recovered.submeshes[0].faces == source.submeshes[0].faces
    assert recovered.submeshes[0].bone_indices == source.submeshes[0].bone_indices
    assert imported._cdmw_obj_normal_recovery_notes
    if not translate:
        assert rebuilt == raw
    else:
        displayed = appearance.to_neutral(recovered)
        for actual, expected in zip(displayed.submeshes[0].vertices, imported.submeshes[0].vertices):
            assert actual == pytest.approx(expected, abs=3e-5)


@pytest.mark.parametrize('channel', ['vertices', 'uvs', 'normals', 'bone_indices'])
def test_obj_normal_recovery_rejects_incompatible_split_channels(tmp_path, channel):
    raw, source, _appearance, imported = _normal_split_obj(tmp_path)
    part = imported.submeshes[0]
    original_index = part.source_vertex_map[-1]
    if channel == 'bone_indices':
        part.bone_indices = [source.submeshes[0].bone_indices[i] for i in part.source_vertex_map]
        part.bone_indices[-1] = (31,)
    elif channel == 'normals':
        part.normals[original_index] = (1., 0., 0.)
    else:
        value = getattr(part, channel)[-1]
        getattr(part, channel)[-1] = (value[0] + .1, *value[1:])
    with pytest.raises(ValueError, match='split vertex'):
        build_mesh(imported, raw)


def test_neutral_roundtrip_rejects_rebuild_that_drops_the_requested_edit(tmp_path, monkeypatch):
    raw, _source, _appearance, imported = _normal_split_obj(tmp_path)
    imported.submeshes[0].vertices = [(x + .01, y, z) for x, y, z in imported.submeshes[0].vertices]
    monkeypatch.setattr('cdmw.core.mesh_native.build_mesh_native', lambda mesh, original_data: original_data)
    with pytest.raises(ValueError, match='exceeds PAC position precision'):
        build_mesh(imported, raw)


def test_neutral_roundtrip_rejects_rebuild_that_drops_normal_edit(tmp_path, monkeypatch):
    raw, _source, _appearance, imported = _normal_split_obj(tmp_path)
    imported.submeshes[0].normals[2] = (0., 0., 1.)
    monkeypatch.setattr('cdmw.core.mesh_native.build_mesh_native', lambda mesh, original_data: original_data)
    with pytest.raises(ValueError, match='exceeds PAC normal precision'):
        build_mesh(imported, raw)


def test_neutral_roundtrip_reports_missing_blender_normal_direction(tmp_path):
    raw, _source, _appearance, imported = _normal_split_obj(tmp_path)
    imported.submeshes[0].normals[2] = (0., 0., 0.)
    with pytest.raises(ValueError, match='zero-length normal'):
        build_mesh(imported, raw)


def test_obj_rebuild_rejects_changes_to_tangent_bits_inside_normal_word(tmp_path, monkeypatch):
    raw, source, obj = _export(tmp_path)
    imported = import_obj(obj)
    imported.submeshes[0].uvs[0] = (.125, .25)
    corrupted = bytearray(raw)
    offset = source.submeshes[0].source_vertex_offsets[0] + 16
    corrupted[offset] ^= 1
    monkeypatch.setattr('cdmw.core.mesh_native.build_mesh_native', lambda *_args: bytes(corrupted))
    with pytest.raises(ValueError, match='protected PAC tangent bits'):
        build_mesh(imported, raw)


@pytest.mark.parametrize('sign', [1, -1])
def test_neutral_obj_recovers_normal_direction_noise_before_ill_conditioned_inverse(tmp_path, sign):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    from cdmw.modding.mesh_pac_builder import _pack_pac_normal

    raw, source = _skinned_pac()
    data = bytearray(raw)
    for offset in source.submeshes[0].source_vertex_offsets:
        struct.pack_into('<I', data, offset + 16, _pack_pac_normal((0., 0., 1.), 0x800002AB))
    raw = bytes(data)
    source = parse_pac(raw, source.path)
    source._cdmw_original_data = raw
    matrix = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., .001, 0., 0., 0., 0., 1.)
    appearance = NeutralMeshAppearance('owned/noise.pabc', (0, 1, 2), (matrix,) * 3)
    displayed = appearance.to_neutral(source)
    displayed._cdmw_neutral_appearance = appearance
    imported = import_obj(export_obj(displayed, str(tmp_path), 'noise')[0])
    imported.submeshes[0].normals = [(sign * x + .001, sign * y, sign * z) for x, y, z in imported.submeshes[0].normals]
    expected = bytearray(raw)
    if sign < 0:
        for normal, offset in zip(source.submeshes[0].normals, source.submeshes[0].source_vertex_offsets):
            packed = struct.unpack_from('<I', raw, offset + 16)[0]
            struct.pack_into('<I', expected, offset + 16, _pack_pac_normal(tuple(-v for v in normal), packed))
    assert build_mesh(imported, raw) == bytes(expected)


def test_neutral_normal_uses_source_when_inverse_quantization_is_less_accurate(tmp_path):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance

    raw, source = _skinned_pac()
    source._cdmw_original_data = raw
    matrix = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., .0001, 0., 0., 0., 0., 1.)
    appearance = NeutralMeshAppearance('owned/quantization.pabc', (0, 1, 2), (matrix,) * 3)
    displayed = appearance.to_neutral(source)
    displayed._cdmw_neutral_appearance = appearance
    imported = import_obj(export_obj(displayed, str(tmp_path), 'quantization')[0])
    imported.submeshes[0].normals = [(x, y, z + .004) for x, y, z in imported.submeshes[0].normals]
    # Packed XY quantization would turn this small normal edit almost 90 degrees
    # after redisplay. The unchanged source is within 0.23 degrees of the input.
    assert build_mesh(imported, raw) == raw


def test_blender_axis_rounding_near_coordinate_plane_does_not_become_position_edit(tmp_path):
    from cdmw.modding.mesh_importer import _prepare_mesh_for_rebuild

    raw, source, _appearance, imported = _normal_split_obj(tmp_path)
    imported.submeshes[0].vertices = [(x, y, z + (6.35e-7 if max(abs(x), abs(y)) > .5 else 0.))
                                     for x, y, z in imported.submeshes[0].vertices]
    _, prepared, _ = _prepare_mesh_for_rebuild(imported, raw)
    assert prepared.submeshes[0].vertices == source.submeshes[0].vertices
    assert build_mesh(imported, raw) == raw


def test_obj_object_and_material_names_preserve_spaces_and_hashes(tmp_path):
    raw, source = _skinned_pac()
    source._cdmw_original_data = raw
    source.submeshes[0].name = ' Part one #2'
    source.submeshes[0].material = 'Material #1127311293'
    obj = export_obj(source, str(tmp_path), 'names')[0]
    imported = import_obj(obj)
    assert imported.submeshes[0].name == source.submeshes[0].name
    assert imported.submeshes[0].material == source.submeshes[0].material
    assert not getattr(imported, '_cdmw_sidecar_warnings', ())
    text = Path(obj).read_text()
    Path(obj).write_text(text.replace('o  Part one #2', 'o _Part_one_#2').replace('usemtl Material #1127311293', 'usemtl Material_#1127311293'))
    imported = import_obj(obj)
    assert imported.submeshes[0].name == source.submeshes[0].name
    assert imported.submeshes[0].material == source.submeshes[0].material
    assert not getattr(imported, '_cdmw_sidecar_warnings', ())


def test_archive_export_omits_none_texture_sentinels(tmp_path):
    from cdmw.core.archive_mesh_export import _export_mtl_local_texture_reference, _rewrite_export_mtl_map_kd

    placeholder = 'texture/nonetexture0x00000000.dds'
    mtl = tmp_path / 'model.mtl'
    mtl.write_text(f'newmtl empty\nmap_Kd {placeholder}\nnewmtl visible\nmap_Kd diffuse.dds\n')
    assert _export_mtl_local_texture_reference(tmp_path, placeholder) == ''
    assert _rewrite_export_mtl_map_kd(mtl, {}, tmp_path) == 1
    assert mtl.read_text() == 'newmtl empty\nnewmtl visible\nmap_Kd diffuse.dds\n'


@pytest.mark.parametrize('missing_palette', [True, False])
def test_archive_obj_source_export_only_recovers_unresolved_palette(tmp_path, monkeypatch, missing_palette):
    from cdmw.core import archive_mesh_export
    from cdmw.core.archive_mesh_appearance import UnresolvedPacBonePaletteError
    from tests.test_archive_mesh_export_fidelity import _entry

    raw, source = _skinned_pac()
    source._cdmw_original_data = raw
    entry = _entry(tmp_path, source.path, raw)
    monkeypatch.setattr(archive_mesh_export, '_parse_archive_mesh', lambda *args, **kwargs: source)
    monkeypatch.setattr(archive_mesh_export, '_find_matching_skeleton_entry', lambda *args, **kwargs: (None, '', (), None))
    def unavailable(*args, **kwargs):
        raise (UnresolvedPacBonePaletteError if missing_palette else ValueError)('unresolved transform')
    monkeypatch.setattr('cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance', unavailable)
    if not missing_palette:
        with pytest.raises(ValueError, match='unresolved transform'):
            archive_mesh_export.export_archive_mesh(
                entry, tmp_path / 'export', 'obj', resolve_skeleton_for_obj=True, build_preview_context=False,
            )
        return
    result = archive_mesh_export.export_archive_mesh(
        entry, tmp_path / 'export', 'obj', resolve_skeleton_for_obj=True, build_preview_context=False,
    )
    obj = next(path for path in result.output_paths if path.suffix == '.obj')
    assert any('source coordinates' in line and 'unresolved' in line for line in result.summary_lines)
    assert build_mesh(import_obj(str(obj)), raw) == raw
