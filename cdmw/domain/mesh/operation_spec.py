"""One immutable description of what a Mesh Editor operation replaces.

Geometry ownership, material-binding ownership, and texture ownership were three
separate concerns spread across `rebuild_material_sidecar`,
`complete_external_swap`, `full_import_model_replacement`,
`neutralize_inherited_material_layers`, `complete_external_material_reset`, and
the branches that read them. Nothing named the combination, so nothing could
check that the preview and the export had reached the same one -- which is how a
preview can show one authority combination while the build produces another.

This module names them. A :class:`MeshOperationSpec` is created once at import
preflight and carried unchanged through preview, edit, export, and package
build; the flags above are derived from it rather than set beside it.

It is deliberately a pure description. It knows what an operation retains and
replaces, and it can say what a summary should read; it performs no replacement
and touches no file.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class GeometryAuthority(str, Enum):
    ORIGINAL = "original"
    IMPORTED = "imported"
    WORKING_EDITED = "working_edited"


class MaterialAuthority(str, Enum):
    ORIGINAL = "original"
    IMPORTED = "imported"
    USER_MAPPED = "user_mapped"


class TextureAuthority(str, Enum):
    ORIGINAL = "original"
    IMPORTED = "imported"
    USER_REPLACED = "user_replaced"
    GENERATED = "generated"


class OperationKind(str, Enum):
    VIEW = "view"
    MODIFY_ORIGINAL = "modify_original"
    REPLACE_GEOMETRY = "replace_geometry"
    REPLACE_GEOMETRY_AND_MATERIALS = "replace_geometry_and_materials"
    REPLACE_FULL_ASSET = "replace_full_asset"
    REPLACE_MATERIALS_AND_TEXTURES = "replace_materials_and_textures"


class PreviewValidity(str, Enum):
    NOT_READY = "not_ready"
    GEOMETRY_ONLY = "geometry_only"
    TEXTURED_PARTIAL = "textured_partial"
    TEXTURED_COMPLETE = "textured_complete"
    FAILED = "failed"


class ExportValidity(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    SAFE_EXACT = "safe_exact"
    SAFE_REBUILD = "safe_rebuild"
    BLOCKED_MISSING_RESOURCE = "blocked_missing_resource"
    BLOCKED_UNSUPPORTED_TOPOLOGY = "blocked_unsupported_topology"
    BLOCKED_UNPROVEN_FORMAT = "blocked_unproven_format"


# A visually correct preview does not prove the writer can produce the target
# output, and a grey but editable preview is useful while textures compile. The
# two states are therefore tracked apart; only these export states permit a
# build.
EXPORTABLE_VALIDITIES = frozenset({ExportValidity.SAFE_EXACT, ExportValidity.SAFE_REBUILD})


@dataclass(frozen=True, slots=True)
class MeshOperationSpec:
    """What one operation replaces, retains, and is allowed to produce."""

    kind: OperationKind
    geometry: GeometryAuthority
    material: MaterialAuthority
    texture: TextureAuthority
    editable: bool = False
    writes_geometry: bool = True
    writes_material_sidecar: bool = False
    writes_texture_files: bool = False

    @property
    def replaces_geometry(self) -> bool:
        return self.writes_geometry and self.geometry is not GeometryAuthority.ORIGINAL

    @property
    def retains_original_textures(self) -> bool:
        return self.texture is TextureAuthority.ORIGINAL

    @property
    def retains_original_material_bindings(self) -> bool:
        return self.material is MaterialAuthority.ORIGINAL

    @property
    def produces_output(self) -> bool:
        return self.writes_geometry or self.writes_material_sidecar or self.writes_texture_files

    def retained_resources(self) -> tuple[str, ...]:
        """What the target keeps, in the order a pre-commit summary reads them."""

        retained: list[str] = []
        if not self.writes_geometry:
            retained.append("geometry")
        if self.retains_original_material_bindings:
            retained.append("material_bindings")
        if self.retains_original_textures:
            retained.append("textures")
        return tuple(retained)

    def replaced_resources(self) -> tuple[str, ...]:
        replaced: list[str] = []
        if self.replaces_geometry:
            replaced.append("geometry")
        if self.writes_material_sidecar:
            replaced.append("material_bindings")
        if self.writes_texture_files:
            replaced.append("textures")
        return tuple(replaced)

    def with_edits(self) -> "MeshOperationSpec":
        """The same operation once the user has edited the working mesh.

        Export must serialize what was edited, never fall back to the source the
        edits started from, so the geometry authority moves rather than the
        edits being carried alongside an authority that still says ORIGINAL.
        """

        if not self.editable or self.geometry is GeometryAuthority.WORKING_EDITED:
            return self
        return replace(self, geometry=GeometryAuthority.WORKING_EDITED)

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "geometry_authority": self.geometry.value,
            "material_authority": self.material.value,
            "texture_authority": self.texture.value,
            "editable": bool(self.editable),
            "writes_geometry": bool(self.writes_geometry),
            "writes_material_sidecar": bool(self.writes_material_sidecar),
            "writes_texture_files": bool(self.writes_texture_files),
            "retained": self.retained_resources(),
            "replaced": self.replaced_resources(),
        }


def _spec(
    kind: OperationKind,
    geometry: GeometryAuthority,
    material: MaterialAuthority,
    texture: TextureAuthority,
    *,
    editable: bool = False,
    writes_geometry: bool = True,
    writes_material_sidecar: bool = False,
    writes_texture_files: bool = False,
) -> MeshOperationSpec:
    return MeshOperationSpec(
        kind=kind,
        geometry=geometry,
        material=material,
        texture=texture,
        editable=editable,
        writes_geometry=writes_geometry,
        writes_material_sidecar=writes_material_sidecar,
        writes_texture_files=writes_texture_files,
    )


# The operation matrix, one row per user-facing command. A command that is not
# in here has no defined contract, which is the state every replacement path was
# in before: predicting what a build would retain meant reading the branches.
OPERATION_SPECS: dict[OperationKind, MeshOperationSpec] = {
    OperationKind.VIEW: _spec(
        OperationKind.VIEW,
        GeometryAuthority.ORIGINAL,
        MaterialAuthority.ORIGINAL,
        TextureAuthority.ORIGINAL,
        writes_geometry=False,
    ),
    OperationKind.MODIFY_ORIGINAL: _spec(
        OperationKind.MODIFY_ORIGINAL,
        GeometryAuthority.ORIGINAL,
        MaterialAuthority.ORIGINAL,
        TextureAuthority.ORIGINAL,
        editable=True,
    ),
    # Geometry only: the target keeps its material slots and its texture files,
    # so the preview has to use the retained target materials or it is not
    # showing what the build will produce.
    OperationKind.REPLACE_GEOMETRY: _spec(
        OperationKind.REPLACE_GEOMETRY,
        GeometryAuthority.IMPORTED,
        MaterialAuthority.ORIGINAL,
        TextureAuthority.ORIGINAL,
        editable=True,
    ),
    OperationKind.REPLACE_GEOMETRY_AND_MATERIALS: _spec(
        OperationKind.REPLACE_GEOMETRY_AND_MATERIALS,
        GeometryAuthority.IMPORTED,
        MaterialAuthority.IMPORTED,
        TextureAuthority.ORIGINAL,
        editable=True,
        writes_material_sidecar=True,
    ),
    OperationKind.REPLACE_FULL_ASSET: _spec(
        OperationKind.REPLACE_FULL_ASSET,
        GeometryAuthority.IMPORTED,
        MaterialAuthority.IMPORTED,
        TextureAuthority.IMPORTED,
        editable=True,
        writes_material_sidecar=True,
        writes_texture_files=True,
    ),
    OperationKind.REPLACE_MATERIALS_AND_TEXTURES: _spec(
        OperationKind.REPLACE_MATERIALS_AND_TEXTURES,
        GeometryAuthority.ORIGINAL,
        MaterialAuthority.IMPORTED,
        TextureAuthority.IMPORTED,
        writes_geometry=False,
        writes_material_sidecar=True,
        writes_texture_files=True,
    ),
}


def operation_spec(kind: object) -> MeshOperationSpec:
    """The specification for a named operation.

    Raises rather than guessing. An unrecognised operation has no contract, and
    defaulting one would reintroduce exactly the silent policy change this type
    exists to prevent.
    """

    if isinstance(kind, MeshOperationSpec):
        return kind
    resolved = kind if isinstance(kind, OperationKind) else None
    if resolved is None:
        try:
            resolved = OperationKind(str(kind.value if isinstance(kind, Enum) else kind))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"unknown Mesh Editor operation: {kind!r}") from None
    return OPERATION_SPECS[resolved]


def spec_permits_build(
    spec: MeshOperationSpec,
    export_validity: ExportValidity,
) -> bool:
    """Whether this operation may be built at the given export validity.

    Preview validity is deliberately not consulted. A visually correct preview
    does not prove the writer can produce the target output, and an operation
    that writes no geometry is not made unsafe by geometry that never compiled.
    """

    if not spec.produces_output:
        return False
    return export_validity in EXPORTABLE_VALIDITIES


__all__ = [
    "EXPORTABLE_VALIDITIES",
    "OPERATION_SPECS",
    "ExportValidity",
    "GeometryAuthority",
    "MaterialAuthority",
    "MeshOperationSpec",
    "OperationKind",
    "PreviewValidity",
    "TextureAuthority",
    "operation_spec",
    "spec_permits_build",
]
