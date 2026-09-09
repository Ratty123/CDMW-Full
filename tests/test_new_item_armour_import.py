"""Wearable imports keep a target rig independently of material-section layout."""
from dataclasses import replace
import struct
from types import SimpleNamespace
from pathlib import Path

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.modding.static_mesh_build import build_static_mesh_replacement
from cdmw.modding.static_mesh_types import (
    StaticMeshReplacementOptions, StaticReplacementTransform, StaticSubmeshMapping,
)
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original
from tests.test_new_item_variant_rig import _snapshot_files


def _two_surface_armour():
    raw, mesh = _minimal_two_part_pac_original()
    data = bytearray(raw)
    for index, part in enumerate(mesh.submeshes):
        for offset in part.source_vertex_offsets:
            record = bytearray(data[offset:offset+40])
            pack_pac_skin_weights(record, (index+1,), (1.0,), context="armour fixture")
            data[offset:offset+40] = record
    raw = bytes(data)
    return raw, parse_pac(raw, "character/model/1_pc/1_phm/armor/9_upperbody/test.pac")


@pytest.mark.parametrize("full_swap", [False, True])
@pytest.mark.parametrize("material_target", [0, 1])
def test_complete_armour_import_transfers_weights_across_template_materials(full_swap, material_target):
    raw, original = _two_surface_armour()
    vertices, faces = [], []
    for part in original.submeshes:
        base = len(vertices)
        vertices.extend(part.vertices)
        faces.extend(tuple(base+index for index in face) for face in part.faces)
    source = ParsedMesh(path="combined.obj", format="obj", submeshes=[SubMesh(
        name="new_armour", vertices=vertices, faces=faces, uvs=[(0.0, 0.0)]*len(vertices),
    )], total_vertices=len(vertices), total_faces=len(faces))
    options = StaticMeshReplacementOptions(
        complete_external_swap=full_swap,
        transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        submesh_mappings=[StaticSubmeshMapping(index, part.name, [0] if index == material_target else [], index)
                          for index, part in enumerate(original.submeshes)],
    )

    output, report = build_static_mesh_replacement(raw, original, source, options)

    assert not report.errors
    rebuilt = parse_pac(output, "new_armour.pac").submeshes[material_target]
    # These vertices uniquely belong to different template surfaces; the shared
    # seam vertices may legitimately interpolate either surface's weights.
    assert rebuilt.bone_indices[1] == ((1,) if full_swap else (material_target+1,))
    assert rebuilt.bone_indices[-1] == ((2,) if full_swap else (material_target+1,))
    assert not source.has_bones and not source.submeshes[0].bone_weights
    assert [part.bone_indices[0] for part in original.submeshes] == [(1,), (2,)]


def _armour_rig_fixture(model_path):
    from tests.test_release_inspired_improvements import _pab_payload

    raw, _mesh = _two_surface_armour()
    data = bytearray(raw)
    hashes = tuple(0xA10000 + index for index in range(12))
    palette = struct.pack("<H12I", len(hashes), *hashes)
    metadata_size = struct.unpack_from("<I", data, 0x14)[0]
    data[0x50 + metadata_size:0x50 + metadata_size] = palette
    struct.pack_into("<I", data, 0x14, metadata_size + len(palette))
    for index in range(8):
        offset = 0x50 + 5 + 4 * index
        struct.pack_into("<I", data, offset, struct.unpack_from("<I", data, offset)[0] + len(palette))
    original = bytes(data)
    target = parse_pac(original, model_path)
    # A different row forces validation of a rebuilt import rather than the
    # unchanged-template fast path.
    offset = target.submeshes[0].source_vertex_offsets[0]
    record = bytearray(data[offset:offset+40])
    pack_pac_skin_weights(record, (3,), (1.0,), context="imported armour fixture")
    data[offset:offset+40] = record
    skeleton = bytearray(_pab_payload()[:0x16])
    struct.pack_into("<H", skeleton, 0x14, len(hashes))
    for index, name_hash in enumerate(hashes):
        skeleton.extend(_pab_payload(f"Bone{index}", name_hash)[0x16:])
    return original, bytes(data), bytes(skeleton)


@pytest.mark.parametrize("family", ["1_pc/10_pgw", "3_npc/other"])
def test_armour_variant_resolves_its_declared_skeleton_outside_the_model_family(family):
    from cdmw.services.new_item_variants import validate_variant_rig

    model = f"character/model/{family}/armor/9_upperbody/test.pac"
    descriptor = model.replace("character/model/", "character/prefab/").replace(".pac", ".prefabdata_xml")
    rig = "character/model/1_pc/2_phw/phw_01.pab"
    original, imported, skeleton = _armour_rig_fixture(model)
    files = {model: original, rig: skeleton, descriptor:
             b'<PrefabData><SkeletonName FileName="1_pc/2_phw/phw_01.pab"/></PrefabData>'}
    snapshot = _snapshot_files(files)

    assert validate_variant_rig(snapshot, model, imported) == rig

    # Resolving a descriptor must not approve an import with another palette.
    changed = imported.replace(struct.pack("<I", 0xA10000), struct.pack("<I", 0xB10000), 1)
    with pytest.raises(ValueError, match="skin palette differs"):
        validate_variant_rig(snapshot, model, changed)

    # Nor can it approve a validly packed influence outside that palette.
    changed = bytearray(imported)
    offset = parse_pac(imported, model).submeshes[0].source_vertex_offsets[0]
    record = bytearray(changed[offset:offset+40])
    pack_pac_skin_weights(record, (12,), (1.0,), context="outside target palette")
    changed[offset:offset+40] = record
    with pytest.raises(ValueError, match="outside the target palette"):
        validate_variant_rig(snapshot, model, bytes(changed))


def test_armour_variant_rejects_ambiguous_compatible_skeletons():
    from cdmw.services.new_item_variants import validate_variant_rig

    model = "character/model/1_pc/1_phm/armor/9_upperbody/test.pac"
    original, imported, skeleton = _armour_rig_fixture(model)
    files = {model: original, "character/model/rig_a/rig.pab": skeleton,
             "character/model/rig_b/rig.pab": skeleton}
    with pytest.raises(ValueError, match="skeleton is missing or ambiguous"):
        validate_variant_rig(_snapshot_files(files), model, imported)


def test_armour_transfer_fit_warning_survives_import_and_material_preparation():
    from cdmw.core.archive_mesh_import_build_stages import start_mesh_import_summary
    from cdmw.domain.new_item.spec import MaterialRoute
    from cdmw.services.new_item_materials import route_model_files
    from cdmw.services.new_item_planning import model_files_from_import

    raw, target = _two_surface_armour()
    part = target.submeshes[0]
    source = ParsedMesh(path="offset_armour.obj", format="obj", total_vertices=3, total_faces=1,
                        submeshes=[SubMesh(vertices=[(x, y, z+10.0) for x, y, z in part.vertices],
                                           faces=list(part.faces), uvs=[(0.0, 0.0)]*3)])
    payload, report = build_static_mesh_replacement(raw, target, source, StaticMeshReplacementOptions(
        complete_external_swap=True,
        transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
    ))
    assert not report.errors
    state = SimpleNamespace(
        entry=SimpleNamespace(path=target.path), parsed_mesh=parse_pac(payload, target.path),
        rebuilt_data=payload, normalized_import_mode="static_replacement", source_display_label="",
        original_baseline=SimpleNamespace(message=""), scene_import_result=SimpleNamespace(diagnostics=[]),
        imported_mesh=source, static_report=report,
    )
    start_mesh_import_summary(state, 0)
    files = model_files_from_import(state, family=SimpleNamespace(files_for=lambda _role: ()))
    routed = route_model_files(files, MaterialRoute.BUILDER)
    assert routed.pac_data == payload
    assert any("transferred" in line for line in routed.notes)
    assert any("far off the source surface" in line and "check the rig deforms" in line for line in routed.warnings)


def test_wearable_refit_preserves_the_templates_authored_orientation():
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, analyze_mesh_geometry

    tilt = ModelPlacement(rotation=(26.0, 11.0, 17.0), offset=(0.1, 1.0, 0.2))
    vertices = [tilt.apply((x, y, z)) for x in (-0.4, 0.4) for y in (-0.7, 0.7) for z in (-0.08, 0.08)]
    mesh = ParsedMesh(submeshes=[SubMesh(name="sleeve", vertices=vertices)])
    analysis = analyze_mesh_geometry(mesh)
    source = ModelImportSource(Path("armour.obj"), Path("armour.obj"), SceneImportResult(mesh=mesh), None,
                               analysis.bounds, centroid=analysis.centroid, principal_frame=analysis.principal_frame,
                               fit_template_bounds=analysis.bounds, fit_template_centroid=analysis.centroid,
                               fit_template_frame=analysis.principal_frame, fit_match_grip=False)

    fitted = NewItemStudioController._fitted_placement(None, source)

    for vertex in vertices:
        assert fitted.apply(vertex) == pytest.approx(vertex, abs=1e-6)


def _body_transfer_request():
    from cdmw.core.item_model_family import FamilyPart, ItemModelFamily
    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.modding.scene_import_result_ops import SceneImportResult

    model = "character/model/1_pc/1_phm/armor/9_upperbody/test.pac"
    prefab = "character/bin__/prefab/1_pc/01_phm/armor/9_upperbody/test.prefab"
    rig = "character/model/1_pc/1_phm/phm_01.pab"
    body = "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac"
    descriptor = model.replace("character/model/", "character/prefab/").replace(".pac", ".prefabdata_xml")
    original, imported, skeleton = _armour_rig_fixture(model)
    payload = bytearray(imported)
    offset = parse_pac(imported, model).submeshes[0].source_vertex_offsets[0]
    record = bytearray(payload[offset:offset+40])
    pack_pac_skin_weights(record, (12,), (1.0,), context="unresolved template influence")
    payload[offset:offset+40] = record
    hashes = tuple(0xA10000 + index for index in range(12))
    # The body's local slot numbers deliberately mean different bones.
    body_data = original.replace(struct.pack("<12I", *hashes), struct.pack("<12I", *reversed(hashes)), 1)
    snapshot = _snapshot_files({model: original, prefab: b"", rig: skeleton, body: body_data, descriptor:
                               b'<PrefabData><SkeletonName FileName="1_pc/1_phm/phm_01.pab"/></PrefabData>'})
    part = FamilyPart("test", 1, SimpleNamespace(prefab_path=prefab), model, True)
    family = ItemModelFamily(1, "test", "1_pc/1_phm/armor/9_upperbody", (part,), (), None, None)
    snapshot.family = lambda _key: family
    appearance = VariantAppearance(prefab, model, custom_model=True, material_route="builder")
    result = SimpleNamespace(rebuilt_data=bytes(payload), supplemental_file_specs=(), summary_lines=[])
    scene = SceneImportResult(mesh=ParsedMesh(submeshes=[SubMesh(vertices=[(0.0, 0.0, 0.0)])]))
    return snapshot, appearance, result, scene, body


def test_unrigged_armour_preparation_maps_body_bones_into_the_target_palette():
    from cdmw.modding.mesh_parser import resolve_pac_bone_palette
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.services.new_item_variants import prepare_variant_models, validate_variant_rig

    snapshot, appearance, result, scene, body = _body_transfer_request()
    original = snapshot.payload(appearance.model_path)
    original_body = snapshot.payload(body)
    spec = SimpleNamespace(template_key=1, variants=(appearance,))

    files = prepare_variant_models(spec, snapshot, {appearance.identity: result}, {appearance.identity: scene})[appearance.identity]

    parsed = parse_pac(files.pac_data, appearance.model_path)
    assert parsed.submeshes[0].bone_indices[1] == (10,)
    assert parsed.submeshes[1].bone_indices[-1] == (9,)
    before = parse_pac(result.rebuilt_data, appearance.model_path)
    for actual, expected in zip(parsed.submeshes, before.submeshes):
        extent = max(max(point[axis] for point in expected.vertices) - min(point[axis] for point in expected.vertices)
                     for axis in range(3))
        for vertex, original_vertex in zip(actual.vertices, expected.vertices):
            assert vertex == pytest.approx(original_vertex, abs=extent / 32767.0 + 2e-6)
    assert [part.faces for part in parsed.submeshes] == [part.faces for part in before.submeshes]
    rig = validate_variant_rig(snapshot, appearance.model_path, files.pac_data)
    skeleton = parse_pab(snapshot.payload(rig), rig)
    assert resolve_pac_bone_palette(files.pac_data, skeleton) == resolve_pac_bone_palette(original, skeleton)
    assert any(body in line for line in files.notes)
    assert any("character body" in warning and "cloth simulation" in warning for warning in files.warnings)
    assert snapshot.payload(body) == original_body and snapshot.payload(appearance.model_path) == original
    assert not scene.mesh.has_bones and not scene.mesh.submeshes[0].bone_weights


@pytest.mark.parametrize("source_kind", ["authored weights", "applied PAC", "changed palette", "retained physics"])
def test_body_transfer_does_not_override_an_explicit_or_incompatible_binding(source_kind):
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_variants import prepare_variant_models

    snapshot, appearance, result, scene, _body = _body_transfer_request()
    expected = "outside the target palette"
    if source_kind == "authored weights":
        scene.mesh.submeshes[0].bone_indices, scene.mesh.submeshes[0].bone_weights = [(1,)], [(1.0,)]
    elif source_kind == "applied PAC":
        result = ModelFiles(result.rebuilt_data)
    elif source_kind == "changed palette":
        result.rebuilt_data = result.rebuilt_data.replace(struct.pack("<I", 0xA10000), struct.pack("<I", 0xB10000), 1)
        expected = "skin palette differs"
    else:
        appearance = replace(appearance, keep_template_physics=True)
        expected = "Turn off Template cloth / physics"
    with pytest.raises(ValueError, match=expected):
        prepare_variant_models(SimpleNamespace(template_key=1, variants=(appearance,)), snapshot,
                               {appearance.identity: result}, {appearance.identity: scene})


def test_body_transfer_refuses_a_body_with_an_unresolved_palette():
    from cdmw.services.new_item_variants import prepare_variant_models

    snapshot, appearance, result, scene, body = _body_transfer_request()
    snapshot.entries[body] = snapshot.payload(body).replace(struct.pack("<I", 0xA10000), struct.pack("<I", 0xB10000), 1)
    with pytest.raises(ValueError, match="verified character body"):
        prepare_variant_models(SimpleNamespace(template_key=1, variants=(appearance,)), snapshot,
                               {appearance.identity: result}, {appearance.identity: scene})


def test_a_valid_armour_import_keeps_its_weights_without_loading_a_body():
    from cdmw.services.new_item_variants import prepare_variant_models

    snapshot, appearance, result, scene, body = _body_transfer_request()
    _original, result.rebuilt_data, _skeleton = _armour_rig_fixture(appearance.model_path)
    del snapshot.entries[body]
    prepared = prepare_variant_models(SimpleNamespace(template_key=1, variants=(appearance,)), snapshot,
                                      {appearance.identity: result}, {appearance.identity: scene})[appearance.identity]
    assert prepared.pac_data == result.rebuilt_data
    assert not prepared.warnings


def test_body_surface_excludes_triangles_whose_bones_the_armour_cannot_represent():
    from cdmw.services.new_item_skinning import _body_surface

    _data, body = _two_surface_armour()
    donor = _body_surface(body, (0, 1, 2), (1,))

    assert donor.vertices == body.submeshes[0].vertices
    assert donor.faces == body.submeshes[0].faces
    assert donor.bone_indices == [(0,)] * 3  # target slot 0 means body bone 1
    assert donor.bone_weights == [(1.0,)] * 3
