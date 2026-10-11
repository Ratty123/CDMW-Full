from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh import (
    MESH_MORPH_AUTHORED_PROFILE_FORMAT,
    MESH_MORPH_PROFILE_FORMAT,
    MeshMorphFittingRecipe,
    MeshMorphProfile,
    MeshMorphSparseField,
    MeshMorphValuePreset,
    MeshRefitDriverRegion,
    MeshRefitGarmentSettings,
    build_morph_sparse_difference,
    create_authored_morph_definition,
    generate_morph_fields,
    mesh_morph_base_fingerprint,
    mesh_morph_driver_topology_fingerprint,
    mesh_morph_role_topology_fingerprint,
    validate_mesh_morph_fitting_recipe,
    validate_morph_definition_geometry,
    validate_morph_target_identity,
    with_morph_garment_corrections,
)
from cdmw.services.mesh_morph_profiles import (
    list_mesh_morph_profiles,
    mesh_morph_profile_from_payload,
    mesh_morph_profile_payload,
    read_mesh_morph_bundle,
    save_mesh_morph_profile,
    serialized_mesh_morph_bundle,
    serialized_mesh_morph_profile,
)


def _mesh():
    body = SimpleNamespace(
        vertices=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (-1.0, 2.0, 0.0), (1.0, 2.0, 0.0)],
        faces=[(0, 1, 2), (1, 3, 2)],
        source_vertex_map=[0, 1, 2, 3],
        source_vertex_map_authority="fixture",
        bone_indices=[(0,)] * 4,
        bone_weights=[(1.0,)] * 4,
        source_bone_palette=(4,),
        source_skin_weight_layout="fixture",
    )
    shirt = deepcopy(body)
    shirt.vertices = [(x, y, 0.2) for x, y, _z in body.vertices]
    return SimpleNamespace(submeshes=[body, shirt])


def _authored(mesh=None):
    mesh = mesh or _mesh()
    target = deepcopy(mesh)
    target.submeshes[0].vertices[0] = (-1.25, 0.0, 0.1)
    target.submeshes[0].vertices[3] = (1.5, 2.0, 0.0)
    return create_authored_morph_definition(
        mesh, target, definition_id="tailored", label="Tailored", submesh_indices=(0,),
    )


def _profile(mesh, definition=None):
    definitions = (definition or _authored(mesh),)
    return MeshMorphProfile(
        profile_id="authored-body", name="Authored Body",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions),
        definitions=definitions,
    )


def _preset(profile):
    return MeshMorphValuePreset(
        preset_id="fit", name="Fit", profile_id=profile.profile_id,
        topology_fingerprint=profile.topology_fingerprint,
        values=tuple((item.definition_id, 50.0) for item in profile.definitions),
    )


def _recipe(mesh):
    profile = _profile(mesh)
    return MeshMorphFittingRecipe(
        recipe_id="shirt-fit", name="Shirt Fit", profile=profile, preset=_preset(profile),
        driver_submesh_indices=(0,), garment_settings=(MeshRefitGarmentSettings(1),),
        topology_fingerprint=mesh_morph_role_topology_fingerprint(mesh, (0, 1)),
        base_geometry_fingerprint=mesh_morph_base_fingerprint(mesh, (0, 1)),
        garment_regions=((1, (MeshRefitDriverRegion(0, (0, 1, 2)),)),),
    )


def test_authored_capture_keeps_nonuniform_vertex_deltas_and_zero_base_identity():
    mesh = _mesh()
    definition = _authored(mesh)
    fields = generate_morph_fields(mesh, definition)

    assert definition.source_kind == "authored"
    assert fields == definition.authored_fields
    assert fields[0].vertex_indices == (0, 3)
    assert fields[0].deltas[0] == pytest.approx((-0.25, 0.0, 0.1))
    assert fields[0].deltas[1] == pytest.approx((0.5, 0.0, 0.0))
    assert definition.rule.amount == 0.0
    assert definition.base_geometry_fingerprint == mesh_morph_base_fingerprint(mesh, (0,))


def test_native_float_precision_identity_survives_neutral_readback():
    mesh = _mesh()
    mesh.submeshes[0].vertices[0] = (0.1, 0.2, 0.3)
    native = deepcopy(mesh)
    native.submeshes[0].vertices[0] = struct.unpack("<3f", struct.pack("<3f", 0.1, 0.2, 0.3))

    assert mesh_morph_base_fingerprint(mesh, (0,)) == mesh_morph_base_fingerprint(native, (0,))
    assert build_morph_sparse_difference(mesh, native, definition_id="none", submesh_indices=(0,)) == ()


@pytest.mark.parametrize("change", ("position", "faces", "source_vertex_map", "bone_weights", "source_bone_palette"))
def test_authored_targets_reject_wrong_neutral_geometry_order_or_skin_identity(change):
    mesh = _mesh()
    definition = _authored(mesh)
    wrong = deepcopy(mesh)
    part = wrong.submeshes[0]
    if change == "position":
        part.vertices[0] = (-1.1, 0.0, 0.0)
    elif change == "faces":
        part.faces[0] = (0, 2, 1)
    elif change == "source_vertex_map":
        part.source_vertex_map = [1, 0, 2, 3]
    elif change == "bone_weights":
        part.bone_weights[0] = (0.5,)
    else:
        part.source_bone_palette = (5,)

    with pytest.raises(ValueError, match="identity does not match"):
        validate_morph_definition_geometry(wrong, definition)


def test_authored_capture_refuses_changed_topology_or_source_mapping_and_no_change():
    mesh = _mesh()
    reordered = deepcopy(mesh)
    reordered.submeshes[0].faces[0] = (0, 2, 1)
    with pytest.raises(ValueError, match="topology differs"):
        create_authored_morph_definition(mesh, reordered, definition_id="bad", label="Bad", submesh_indices=(0,))
    wrong_source = deepcopy(mesh)
    wrong_source.submeshes[0].source_vertex_map = [1, 0, 2, 3]
    with pytest.raises(ValueError, match="source/skin identity differs"):
        build_morph_sparse_difference(mesh, wrong_source, definition_id="bad", submesh_indices=(0,))
    with pytest.raises(ValueError, match="No body vertex changes"):
        create_authored_morph_definition(mesh, mesh, definition_id="empty", label="Empty", submesh_indices=(0,))


@pytest.mark.parametrize(
    "indices,deltas",
    (
        ((0, 0), ((1, 0, 0), (2, 0, 0))),
        ((0.5,), ((1, 0, 0),)),
        ((True,), ((1, 0, 0),)),
        ((-1,), ((1, 0, 0),)),
        ((0,), ((float("nan"), 0, 0),)),
        ((0,), ((1, 0, 0, 4),)),
        ((0,), ((1e7, 0, 0),)),
        ((0, 1), ((1, 0, 0),)),
        ((), ()),
    ),
)
def test_sparse_fields_fail_closed_on_invalid_shape_indices_or_deltas(indices, deltas):
    with pytest.raises(ValueError):
        MeshMorphSparseField("target", 0, indices, deltas)


def test_sparse_fields_sort_indices_without_reordering_the_wrong_deltas():
    field = MeshMorphSparseField("target", 0, (3, 1), ((3, 0, 0), (1, 0, 0)))
    assert field.vertex_indices == (1, 3)
    assert field.deltas == ((1.0, 0.0, 0.0), (3.0, 0.0, 0.0))


def test_v3_roundtrip_and_portable_bundle_validate_neutral_body_identity(tmp_path):
    mesh = _mesh()
    profile = _profile(mesh)
    path = save_mesh_morph_profile(tmp_path, profile)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["format"] == MESH_MORPH_AUTHORED_PROFILE_FORMAT
    assert mesh_morph_profile_from_payload(payload) == profile
    loaded, diagnostics = list_mesh_morph_profiles(tmp_path, mesh)
    assert loaded == (profile,)
    assert diagnostics == ()

    portable = tmp_path / "portable.json"
    portable.write_text(serialized_mesh_morph_bundle(profile, _preset(profile), max_bytes=100_000), encoding="utf-8")
    assert read_mesh_morph_bundle(portable, mesh, max_bytes=100_000) == (profile, _preset(profile))
    wrong = deepcopy(mesh)
    wrong.submeshes[0].vertices[0] = (-1.5, 0.0, 0.0)
    with pytest.raises(ValueError, match="base geometry"):
        read_mesh_morph_bundle(portable, wrong, max_bytes=100_000)


def test_authored_body_profile_accepts_other_garment_until_corrections_bind_it(tmp_path):
    mesh = _mesh()
    profile = _profile(mesh)
    save_mesh_morph_profile(tmp_path, profile)
    other = deepcopy(mesh)
    other.submeshes[1].vertices[0] = (-9.0, 0.0, 0.2)

    assert list_mesh_morph_profiles(tmp_path, other)[0] == (profile,)
    correction = MeshMorphSparseField("tailored", 1, (0,), ((0.0, 0.0, 0.05),))
    corrected = with_morph_garment_corrections(profile.definitions[0], mesh, (correction,))
    profile = _profile(mesh, corrected)
    save_mesh_morph_profile(tmp_path, profile)
    assert mesh_morph_profile_from_payload(mesh_morph_profile_payload(profile)) == profile
    loaded, diagnostics = list_mesh_morph_profiles(tmp_path, other)
    assert loaded == ()
    assert any("Garment correction base geometry" in item for item in diagnostics)
    assert generate_morph_fields(mesh, corrected) == corrected.authored_fields


def test_corrections_cannot_target_driver_or_repeat_part_and_can_be_cleared():
    mesh = _mesh()
    definition = _authored(mesh)
    driver_field = MeshMorphSparseField("tailored", 0, (0,), ((0, 0, 0.1),))
    with pytest.raises(ValueError, match="cannot target a driver"):
        with_morph_garment_corrections(definition, mesh, (driver_field,))
    garment_field = replace(driver_field, submesh_index=1)
    with pytest.raises(ValueError, match="unique part indices"):
        with_morph_garment_corrections(definition, mesh, (garment_field, garment_field))
    corrected = with_morph_garment_corrections(definition, mesh, (garment_field,))
    assert with_morph_garment_corrections(corrected, mesh, ()) == definition


def test_extended_payloads_cannot_masquerade_as_v2_or_silently_drop_bad_rows():
    payload = mesh_morph_profile_payload(_profile(_mesh()))
    payload["format"] = MESH_MORPH_PROFILE_FORMAT
    with pytest.raises(ValueError, match="require a v3"):
        mesh_morph_profile_from_payload(payload)
    payload["format"] = MESH_MORPH_AUTHORED_PROFILE_FORMAT
    payload["definitions"][0]["authored_fields"].append("bad")
    with pytest.raises(ValueError, match="array of objects"):
        mesh_morph_profile_from_payload(payload)
    payload["definitions"] = ["bad"]
    with pytest.raises(ValueError, match="array of objects"):
        mesh_morph_profile_from_payload(payload)


def test_serialized_authored_profile_obeys_file_size_limit_without_partial_write(tmp_path):
    profile = _profile(_mesh())
    with pytest.raises(ValueError, match="exceeds its configured file limit"):
        serialized_mesh_morph_profile(profile, max_bytes=64)
    assert not tuple(tmp_path.iterdir())


def test_mask_none_empty_sparse_and_driver_regions_have_distinct_validated_semantics():
    assert MeshRefitGarmentSettings(1).vertex_mask is None
    assert MeshRefitGarmentSettings(1, vertex_mask=()).vertex_mask == ()
    assert MeshRefitGarmentSettings(1, vertex_mask=((3, 0.5), (1, 1))).vertex_mask == ((1, 1.0), (3, 0.5))
    assert MeshRefitDriverRegion(0, (2, 0, 1)).vertex_indices == (0, 1, 2)
    for mask in (((1, float("nan")),), ((1, 1.1),), ((1, 1), (1, 0)), ((0.1, 1),)):
        with pytest.raises(ValueError):
            MeshRefitGarmentSettings(1, vertex_mask=mask)
    with pytest.raises(ValueError):
        MeshRefitDriverRegion(0, ())
    with pytest.raises(ValueError):
        MeshRefitDriverRegion(0, (1, 1))


def test_recipe_validates_full_role_identity_and_keeps_region_scope_per_garment():
    mesh = _mesh()
    recipe = _recipe(mesh)
    validate_mesh_morph_fitting_recipe(mesh, recipe)
    other = deepcopy(mesh)
    other.submeshes[1].vertices[0] = (-2.0, 0.0, 0.2)
    with pytest.raises(ValueError, match="neutral geometry"):
        validate_mesh_morph_fitting_recipe(other, recipe)
    with pytest.raises(ValueError, match="cannot overlap"):
        replace(recipe, garment_settings=(MeshRefitGarmentSettings(0),))
    with pytest.raises(ValueError, match="configured garments"):
        replace(recipe, garment_regions=((0, (MeshRefitDriverRegion(0, (0, 1, 2)),)),))


def test_recipe_rejects_out_of_range_masks_incomplete_surface_and_nonuniform_rigid_component():
    mesh = _mesh()
    recipe = _recipe(mesh)
    with pytest.raises(ValueError, match="mask vertex is out of range"):
        validate_mesh_morph_fitting_recipe(mesh, replace(recipe, garment_settings=(MeshRefitGarmentSettings(1, vertex_mask=((9, 1.0),)),)))
    with pytest.raises(ValueError, match="no complete triangles"):
        validate_mesh_morph_fitting_recipe(mesh, replace(recipe, garment_regions=((1, (MeshRefitDriverRegion(0, (0, 1)),)),)))
    with pytest.raises(ValueError, match="must be uniform"):
        validate_mesh_morph_fitting_recipe(mesh, replace(recipe, garment_settings=(MeshRefitGarmentSettings(1, mode="rigid_component", vertex_mask=((0, 1.0),)),)))
    protected = replace(recipe, garment_settings=(MeshRefitGarmentSettings(1, mode="rigid_component", vertex_mask=()),))
    validate_mesh_morph_fitting_recipe(mesh, protected)


def test_profile_corrections_cannot_target_a_different_slider_driver():
    mesh = _mesh()
    body = _authored(mesh)
    correction = MeshMorphSparseField("tailored", 1, (0,), ((0, 0, 0.1),))
    body = with_morph_garment_corrections(body, mesh, (correction,))
    target = deepcopy(mesh)
    target.submeshes[1].vertices[0] = (-1.5, 0.0, 0.2)
    other_driver = create_authored_morph_definition(
        mesh, target, definition_id="other", label="Other", submesh_indices=(1,),
    )
    with pytest.raises(ValueError, match="any profile driver"):
        replace(_profile(mesh, body), definitions=(body, other_driver))


def test_authored_profile_rejects_fractional_or_boolean_selection_indices():
    for value in (0.5, True):
        payload = mesh_morph_profile_payload(_profile(_mesh()))
        payload["definitions"][0]["vertices"][0]["vertex_index"] = value
        with pytest.raises(ValueError, match="integer index"):
            mesh_morph_profile_from_payload(payload)


def test_target_identity_allows_sculpted_positions_and_normals_without_delta_capture(monkeypatch):
    from cdmw.domain.mesh import morph_targets

    mesh = _mesh()
    target = deepcopy(mesh)
    target.submeshes[0].vertices[0] = (-1.2, 0.0, 0.5)
    target.submeshes[0].normals = [(0.0, 1.0, 0.0)] * 4

    def no_sparse_allocation(*args, **kwargs):
        pytest.fail("Target identity checks must not allocate sparse difference fields")

    monkeypatch.setattr(morph_targets, "MeshMorphSparseField", no_sparse_allocation)
    assert validate_morph_target_identity(mesh, target, submesh_indices=(0, 1)) is None
    assert validate_morph_target_identity(
        mesh, target, submesh_indices=(0, 1), require_source_mapping=True,
    ) is None


def test_target_identity_accepts_existing_unmapped_native_sculpt_but_can_require_external_mapping():
    mesh = _mesh()
    for part in mesh.submeshes:
        part.source_vertex_map = []
        part.source_vertex_map_authority = ""
    target = deepcopy(mesh)
    target.submeshes[0].vertices[0] = (-1.2, 0.0, 0.5)

    assert validate_morph_target_identity(mesh, target, submesh_indices=(0,)) is None
    with pytest.raises(ValueError, match="mapping is unavailable"):
        validate_morph_target_identity(
            mesh, target, submesh_indices=(0,), require_source_mapping=True,
        )


@pytest.mark.parametrize(
    "change",
    ["part_count", "faces", "source_map_missing", "source_map_short",
     "source_map_negative", "source_map_bool", "source_map_changed", "skin"],
)
def test_target_identity_rejects_replaced_topology_or_mapping(change):
    mesh = _mesh()
    target = deepcopy(mesh)
    part = target.submeshes[0]
    if change == "part_count":
        target.submeshes.append(deepcopy(part))
    elif change == "faces":
        part.faces = list(reversed(part.faces))
    elif change == "source_map_missing":
        part.source_vertex_map = []
    elif change == "source_map_short":
        part.source_vertex_map = [0, 1, 2]
    elif change == "source_map_negative":
        part.source_vertex_map = [0, 1, 2, -1]
    elif change == "source_map_bool":
        part.source_vertex_map = [0, 1, 2, True]
    elif change == "source_map_changed":
        part.source_vertex_map = [1, 0, 2, 3]
    else:
        part.bone_weights[0] = (0.5,)

    with pytest.raises(ValueError, match="part count|topology|mapping|source/skin"):
        validate_morph_target_identity(mesh, target, submesh_indices=(0,))
