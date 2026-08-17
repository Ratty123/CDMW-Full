"""The operation matrix, pinned against the plan's own table.

The point of the type is that "what does this replace and what does it keep" has
one answer per operation rather than being read out of six loosely related
flags. So the tests are mostly the table itself: if a row changes, that is a
product decision and it should have to be made here.
"""

from __future__ import annotations

import pytest

from cdmw.domain.mesh.operation_spec import (
    EXPORTABLE_VALIDITIES,
    OPERATION_SPECS,
    ExportValidity,
    GeometryAuthority as G,
    MaterialAuthority as M,
    MeshOperationSpec,
    OperationKind as K,
    TextureAuthority as T,
    operation_spec,
    spec_permits_build,
)


@pytest.mark.parametrize(
    ("kind", "geometry", "material", "texture"),
    [
        (K.VIEW, G.ORIGINAL, M.ORIGINAL, T.ORIGINAL),
        (K.MODIFY_ORIGINAL, G.ORIGINAL, M.ORIGINAL, T.ORIGINAL),
        (K.REPLACE_GEOMETRY, G.IMPORTED, M.ORIGINAL, T.ORIGINAL),
        (K.REPLACE_GEOMETRY_AND_MATERIALS, G.IMPORTED, M.IMPORTED, T.ORIGINAL),
        (K.REPLACE_FULL_ASSET, G.IMPORTED, M.IMPORTED, T.IMPORTED),
        (K.REPLACE_MATERIALS_AND_TEXTURES, G.ORIGINAL, M.IMPORTED, T.IMPORTED),
    ],
)
def test_the_operation_matrix_matches_the_plan(
    kind: K,
    geometry: G,
    material: M,
    texture: T,
) -> None:
    spec = operation_spec(kind)
    assert (spec.geometry, spec.material, spec.texture) == (geometry, material, texture)


def test_every_operation_kind_has_a_specification() -> None:
    assert set(OPERATION_SPECS) == set(K)


def test_an_unknown_operation_is_refused_rather_than_defaulted() -> None:
    # Defaulting would reintroduce the silent policy change the type exists to
    # prevent: a build that quietly retains or replaces more than was asked.
    for value in ("replace_everything", "", None, 7):
        with pytest.raises(ValueError):
            operation_spec(value)


def test_a_specification_passes_through_operation_spec_unchanged() -> None:
    spec = operation_spec(K.REPLACE_FULL_ASSET)
    assert operation_spec(spec) is spec


def test_geometry_only_replacement_keeps_the_targets_materials_and_textures() -> None:
    spec = operation_spec(K.REPLACE_GEOMETRY)

    assert spec.replaces_geometry
    assert spec.retains_original_material_bindings
    assert spec.retains_original_textures
    # Nothing about materials is written, so no imported texture file is copied.
    assert not spec.writes_material_sidecar
    assert not spec.writes_texture_files
    assert spec.retained_resources() == ("material_bindings", "textures")
    assert spec.replaced_resources() == ("geometry",)


def test_full_replacement_writes_all_three_and_retains_nothing() -> None:
    spec = operation_spec(K.REPLACE_FULL_ASSET)

    assert spec.retained_resources() == ()
    assert spec.replaced_resources() == ("geometry", "material_bindings", "textures")


def test_material_and_texture_only_replacement_leaves_geometry_alone() -> None:
    spec = operation_spec(K.REPLACE_MATERIALS_AND_TEXTURES)

    assert not spec.writes_geometry
    assert not spec.replaces_geometry
    assert "geometry" in spec.retained_resources()
    assert spec.replaced_resources() == ("material_bindings", "textures")


def test_geometry_plus_materials_keeps_the_targets_texture_files() -> None:
    spec = operation_spec(K.REPLACE_GEOMETRY_AND_MATERIALS)

    assert spec.writes_material_sidecar
    assert not spec.writes_texture_files
    assert spec.retained_resources() == ("textures",)


def test_viewing_produces_no_output() -> None:
    spec = operation_spec(K.VIEW)
    assert not spec.produces_output
    assert not spec.editable


def test_editing_moves_geometry_authority_to_the_working_mesh() -> None:
    """Export must serialize what was edited, never the source it started from."""
    spec = operation_spec(K.MODIFY_ORIGINAL)
    assert spec.geometry is G.ORIGINAL

    edited = spec.with_edits()
    assert edited.geometry is G.WORKING_EDITED
    # Everything else about the operation is unchanged.
    assert (edited.kind, edited.material, edited.texture) == (
        spec.kind,
        spec.material,
        spec.texture,
    )
    # And it is idempotent.
    assert edited.with_edits() is edited


def test_a_non_editable_operation_cannot_acquire_edited_geometry() -> None:
    spec = operation_spec(K.REPLACE_MATERIALS_AND_TEXTURES)
    assert spec.with_edits() is spec


def test_a_specification_is_immutable() -> None:
    spec = operation_spec(K.REPLACE_FULL_ASSET)
    with pytest.raises(Exception):
        spec.geometry = G.ORIGINAL  # type: ignore[misc]


@pytest.mark.parametrize(
    ("validity", "permitted"),
    [
        (ExportValidity.SAFE_EXACT, True),
        (ExportValidity.SAFE_REBUILD, True),
        (ExportValidity.NOT_EVALUATED, False),
        (ExportValidity.BLOCKED_MISSING_RESOURCE, False),
        (ExportValidity.BLOCKED_UNSUPPORTED_TOPOLOGY, False),
        (ExportValidity.BLOCKED_UNPROVEN_FORMAT, False),
    ],
)
def test_only_a_safe_export_validity_permits_a_build(
    validity: ExportValidity,
    permitted: bool,
) -> None:
    spec = operation_spec(K.REPLACE_FULL_ASSET)
    assert spec_permits_build(spec, validity) is permitted


def test_an_operation_with_no_output_never_permits_a_build() -> None:
    spec = operation_spec(K.VIEW)
    for validity in ExportValidity:
        assert not spec_permits_build(spec, validity)


def test_exportable_validities_are_the_two_safe_ones() -> None:
    assert EXPORTABLE_VALIDITIES == {
        ExportValidity.SAFE_EXACT,
        ExportValidity.SAFE_REBUILD,
    }


def test_the_payload_names_retained_and_replaced_for_a_summary() -> None:
    payload = operation_spec(K.REPLACE_GEOMETRY).as_payload()

    assert payload["kind"] == "replace_geometry"
    assert payload["geometry_authority"] == "imported"
    assert payload["material_authority"] == "original"
    assert payload["texture_authority"] == "original"
    assert payload["retained"] == ("material_bindings", "textures")
    assert payload["replaced"] == ("geometry",)


def test_a_hand_built_specification_reports_consistently() -> None:
    spec = MeshOperationSpec(
        kind=K.REPLACE_GEOMETRY,
        geometry=G.WORKING_EDITED,
        material=M.USER_MAPPED,
        texture=T.GENERATED,
        editable=True,
        writes_material_sidecar=True,
        writes_texture_files=True,
    )

    assert spec.replaces_geometry
    assert not spec.retains_original_material_bindings
    assert not spec.retains_original_textures
    assert spec.retained_resources() == ()
    assert spec.replaced_resources() == ("geometry", "material_bindings", "textures")
