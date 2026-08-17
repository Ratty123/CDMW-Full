"""A full replacement cannot be committed with a reference and no file.

The final package preflight already blocks an unresolved *visible colour*
texture, because a grey mesh is what a reader notices. The rest of the sidecar
was only counted: a normal, mask, or material reference resolving to nothing
produced a `Missing final DDS payload path(s)` summary line and a package that
built anyway. For an operation whose textures the package owns outright, that is
the partial output ME-REP-003 calls a blocker -- new bindings with no files
behind them.

Which operations own their textures is `writes_texture_files` on the carried
specification, so this is off for a geometry-only replacement, where an
unresolved support map means the target keeps its own and nothing is missing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from cdmw.core.archive_modding import MeshImportSupplementalFileSpec
from cdmw.core.final_package_builder import build_final_package_preview
from cdmw.core.final_package_preview import material_preflight_hard_blockers
from cdmw.domain.mesh.operation_spec import OperationKind, operation_spec

from tests.test_final_package_preview import _dds, _preview, _sidecar


_NORMAL_SIDECAR_PATH = "character/texture/blade_n.dds"


def _specs_with_unresolved_normal(root: Path) -> tuple[MeshImportSupplementalFileSpec, ...]:
    """A package whose sidecar names a normal map the package does not carry."""

    return (
        MeshImportSupplementalFileSpec(
            source_path=root / "blade.dds",
            target_path="character/texture/blade_base.dds",
            kind="texture_generated",
            payload_data=_dds(),
        ),
        MeshImportSupplementalFileSpec(
            source_path=root / "test_weapon.pac_xml",
            target_path="character/modelproperty/test_weapon.pac_xml",
            kind="sidecar_generated",
            payload_data=(
                b'<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
                b'<MaterialParameterTexture _name="_overlayColorTexture">'
                b'<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/>'
                b"</MaterialParameterTexture>"
                b'<MaterialParameterTexture _name="_normalTexture">'
                b'<ResourceReferencePath_ITexture _path="' + _NORMAL_SIDECAR_PATH.encode() + b'"/>'
                b"</MaterialParameterTexture>"
                b"</SkinnedMeshMaterialWrapper></Root>"
            ),
        ),
    )


def _preflight(root: Path, *, require_complete_texture_payload: bool):
    return build_final_package_preview(
        _preview(),
        supplemental_file_specs=_specs_with_unresolved_normal(root),
        require_complete_texture_payload=require_complete_texture_payload,
    )


def test_an_unresolved_support_map_is_only_counted_by_default() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        result = _preflight(Path(temp_dir), require_complete_texture_payload=False)

    assert _NORMAL_SIDECAR_PATH in result.missing_texture_paths
    assert not any(
        "missing a required texture" in error for error in result.preflight_errors
    )


def test_a_full_replacement_is_blocked_by_the_same_unresolved_support_map() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        result = _preflight(Path(temp_dir), require_complete_texture_payload=True)

    blockers = [
        error for error in result.preflight_errors if "missing a required texture" in error
    ]
    assert len(blockers) == 1
    assert _NORMAL_SIDECAR_PATH in blockers[0]
    assert "_normalTexture" in blockers[0]


def test_the_blocker_is_acknowledgeable_rather_than_unbypassable() -> None:
    # Every other package-contract blocker here can be taken past with the
    # unsafe-export acknowledgement, which is logged and confirmed again before
    # a direct patch. This one is deliberately no different.
    with tempfile.TemporaryDirectory() as temp_dir:
        result = _preflight(Path(temp_dir), require_complete_texture_payload=True)

    hard = material_preflight_hard_blockers(result.preflight_errors)
    assert not any("missing a required texture" in error for error in hard)


def test_a_resolved_support_map_blocks_nothing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        specs = _specs_with_unresolved_normal(root) + (
            MeshImportSupplementalFileSpec(
                source_path=root / "blade_n.dds",
                target_path=_NORMAL_SIDECAR_PATH,
                kind="texture_generated",
                payload_data=_dds(),
            ),
        )
        result = build_final_package_preview(
            _preview(),
            supplemental_file_specs=specs,
            require_complete_texture_payload=True,
        )

    assert not any(
        "missing a required texture" in error for error in result.preflight_errors
    )


def test_only_the_texture_owning_operations_ask_for_a_complete_payload() -> None:
    # This is the value the Builder reads to decide the flag, so what it says
    # per operation is part of the contract rather than an implementation
    # detail of the call site.
    owning = {
        kind
        for kind in OperationKind
        if operation_spec(kind).writes_texture_files
    }
    assert owning == {
        OperationKind.REPLACE_FULL_ASSET,
        OperationKind.REPLACE_MATERIALS_AND_TEXTURES,
    }
