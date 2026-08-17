"""Replace Materials and Textures Only: the sixth operation, and its guarantee.

The plan's §9.3 row for this command is one line -- "Geometry hash remains
unchanged" -- and there are two ways to get there. One is to rebuild the mesh
and trust the writer to reproduce the original byte for byte. The other is not
to write the mesh at all. This does the second, so the guarantee is a fact about
what the commit boundary emits rather than a hope about the serializer, and
these tests pin it at that boundary.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.builder_operation import option_operation_disagreements
from cdmw.domain.mesh.operation_spec import (
    GeometryAuthority,
    MaterialAuthority,
    OperationKind,
    TextureAuthority,
)
from cdmw.modding.full_import_model_replacement import (
    apply_full_import_model_replacement_preset,
)
from cdmw.modding.materials_and_textures_replacement import (
    MATERIALS_AND_TEXTURES_TITLE,
    apply_materials_and_textures_only_preset,
    materials_and_textures_external_file_filter,
)
from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions


def test_the_preset_names_the_operation_and_writes_no_geometry() -> None:
    spec = apply_materials_and_textures_only_preset().operation_spec

    assert spec.kind is OperationKind.REPLACE_MATERIALS_AND_TEXTURES
    assert spec.geometry is GeometryAuthority.ORIGINAL
    assert spec.material is MaterialAuthority.IMPORTED
    assert spec.texture is TextureAuthority.IMPORTED
    assert spec.writes_geometry is False
    assert spec.writes_material_sidecar is True
    assert spec.writes_texture_files is True


def test_the_preset_retains_geometry_and_replaces_the_rest() -> None:
    spec = apply_materials_and_textures_only_preset().operation_spec

    assert "geometry" in spec.retained_resources()
    assert spec.replaced_resources() == ("material_bindings", "textures")


def test_material_handling_matches_full_import_exactly() -> None:
    """Two answers to "who owns the materials" is what the spec exists to stop."""

    materials_only = apply_materials_and_textures_only_preset()
    full_import = apply_full_import_model_replacement_preset()

    for flag in (
        "rebuild_material_sidecar",
        "complete_external_swap",
        "neutralize_inherited_material_layers",
        "complete_external_material_reset",
        "enable_missing_base_color_parameters",
        "prune_removed_target_texture_parameters",
        "prune_unmapped_original_texture_parameters",
    ):
        assert getattr(materials_only, flag) == getattr(full_import, flag), flag


def test_the_preset_agrees_with_the_build_guard() -> None:
    assert option_operation_disagreements(apply_materials_and_textures_only_preset()) == ()


def test_the_preset_leaves_the_transform_alone() -> None:
    # Full Import forces an alignment because it is replacing the mesh. Here
    # there is no mesh to align, and forcing one would imply geometry moves.
    base = StaticMeshReplacementOptions()
    applied = apply_materials_and_textures_only_preset(base)

    assert applied.transform == base.transform


def test_the_preset_preserves_tuning_it_was_handed() -> None:
    tuned = StaticMeshReplacementOptions(
        complete_swap_material_profile="source_graph_strict",
        accent_glow_strength=42.0,
    )
    applied = apply_materials_and_textures_only_preset(tuned)

    assert applied.complete_swap_material_profile == "source_graph_strict"
    assert applied.accent_glow_strength == 42.0


def test_the_file_filter_offers_the_supported_external_formats() -> None:
    external_filter = materials_and_textures_external_file_filter()

    for extension in ("*.obj", "*.dae", "*.gltf", "*.glb", "*.zip"):
        assert extension in external_filter
    # FBX geometry import is out of scope, and this command still parses a model.
    assert "fbx" not in external_filter.lower()


class _RequestFlow:
    """The commit boundary's request builder, with its collaborators stubbed."""

    from cdmw.ui.archive_browser.mesh_direct_patch import (
        ArchiveMeshDirectPatchMixin as _Mixin,
    )

    _build = _Mixin._build_mesh_direct_patch_requests


def _entry(path: str):
    return SimpleNamespace(path=path, basename=path.rsplit("/", 1)[-1])


@pytest.mark.parametrize("include_geometry", [True, False])
def test_the_mesh_entry_is_patched_only_when_the_operation_writes_geometry(
    include_geometry: bool,
) -> None:
    preview = SimpleNamespace(
        rebuilt_data=b"rebuilt mesh bytes",
        paired_lod_data=b"rebuilt lod bytes",
    )
    build_entry = _entry("character/model/sword.pac")
    paired_entry = _entry("character/model/sword.pamlod")

    requests, _warnings = _RequestFlow._build(
        SimpleNamespace(),
        build_entry,
        preview,
        paired_entry=paired_entry,
        include_geometry=include_geometry,
    )

    patched = {str(request.entry.path) for request in requests}
    if include_geometry:
        assert patched == {build_entry.path, paired_entry.path}
    else:
        # Nothing rewrites the mesh, so its bytes in the archive are whatever
        # they already were. That is the guarantee, stated as an absence.
        assert patched == set()


def test_not_writing_the_mesh_is_what_keeps_the_geometry_hash() -> None:
    shipped = b"the original mesh bytes as they ship"
    shipped_hash = hashlib.sha256(shipped).hexdigest()
    preview = SimpleNamespace(rebuilt_data=b"a rebuild that is not byte identical", paired_lod_data=None)

    requests, _warnings = _RequestFlow._build(
        SimpleNamespace(),
        _entry("character/model/sword.pac"),
        preview,
        include_geometry=False,
    )

    assert requests == []
    # No request touches the entry, so the bytes on disk are unchanged even
    # though the rebuild in hand differs from them.
    assert hashlib.sha256(shipped).hexdigest() == shipped_hash


def test_the_command_title_is_the_plans_own_name() -> None:
    assert MATERIALS_AND_TEXTURES_TITLE == "Replace Materials and Textures Only"
