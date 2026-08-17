"""Which operation the Builder's controls describe, and what that operation writes.

`operation_spec` names the six replacement contracts. Nothing produced one, so
the Builder still decided what a build replaces by evaluating six boolean
expressions side by side, each reading a different combination of
`modify_original_clone_mode`, the complete-swap switch, the Full Import preset,
and five checkboxes. Predicting what a build would retain meant reading all six
at once, and a preview reading one of them differently from the export was
invisible until the output was opened.

This module turns those inputs into a :class:`MeshOperationSpec` first, and
derives the flags from it second. The classification is the part worth naming:
clone mode is Modify Original, the complete-swap switch is the imported model
taking over material ownership, and the Full Import preset is the full asset.
The flags then follow.

Two of them follow from the specification alone -- the sidecar is written when
the operation says it writes one, and the external swap runs when the imported
model owns the materials. The four tuning bits do not, and are not forced to:
they are four independent user choices in the geometry-only case, and collapsing
them into one authority value would quietly change what a build produces. What
the specification decides is when they stop being the user's to set -- always on
where the imported model owns the materials, always off where the target keeps
its own.

Pure by construction: no Qt, no widgets, no options object.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cdmw.domain.mesh.operation_spec import (
    MaterialAuthority,
    MeshOperationSpec,
    OperationKind,
    operation_spec,
)


@dataclass(frozen=True, slots=True)
class BuilderMaterialControls:
    """The Builder's material checkboxes as read at the moment of a build.

    Named rather than passed positionally because five bools in a row is how
    two of them ended up swapped in an earlier reading of this state.
    """

    rebuild_sidecar: bool = False
    source_color_faithful: bool = False
    external_material_reset: bool = False
    inject_base_color: bool = False
    prune_unmapped_original_dds: bool = False


@dataclass(frozen=True, slots=True)
class BuilderOperationFlags:
    """The `StaticMeshReplacementOptions` fields this operation implies."""

    rebuild_material_sidecar: bool = False
    complete_external_swap: bool = False
    neutralize_inherited_material_layers: bool = False
    complete_external_material_reset: bool = False
    enable_missing_base_color_parameters: bool = False
    prune_unmapped_original_texture_parameters: bool = False

    def as_option_fields(self) -> dict[str, bool]:
        """Keyword arguments for the options constructor, by their field names."""

        return {
            "rebuild_material_sidecar": self.rebuild_material_sidecar,
            "complete_external_swap": self.complete_external_swap,
            "neutralize_inherited_material_layers": self.neutralize_inherited_material_layers,
            "complete_external_material_reset": self.complete_external_material_reset,
            "enable_missing_base_color_parameters": self.enable_missing_base_color_parameters,
            "prune_unmapped_original_texture_parameters": self.prune_unmapped_original_texture_parameters,
        }


def classify_builder_operation(
    *,
    modify_original_clone_mode: bool = False,
    complete_swap_enabled: bool = False,
    full_import_model_replacement: bool = False,
    controls: BuilderMaterialControls | None = None,
    modify_original_tuning_enabled: bool = False,
) -> MeshOperationSpec:
    """The operation the Builder's current control state describes.

    Clone mode wins over the complete-swap switch, matching the Builder, which
    forces the switch off while cloning: a Modify Original session edits the
    target's own mesh and has no imported model to take material ownership.
    """

    controls = controls or BuilderMaterialControls()

    if modify_original_clone_mode:
        spec = operation_spec(OperationKind.MODIFY_ORIGINAL)
        if not modify_original_tuning_enabled:
            return spec
        # The plan's matrix reads Modify Original as "modified original-compatible
        # mesh *and selected material changes*". Texture tuning is those changes,
        # and it writes a sidecar the base row does not.
        return replace(spec, material=MaterialAuthority.USER_MAPPED, writes_material_sidecar=True)

    if full_import_model_replacement or complete_swap_enabled:
        # The Full Import preset and the complete-swap switch reach the same
        # contract by different routes: the imported model owns the geometry,
        # the bindings, and the texture files.
        return operation_spec(OperationKind.REPLACE_FULL_ASSET)

    spec = operation_spec(OperationKind.REPLACE_GEOMETRY)
    if not _any_material_override(controls):
        return spec
    # The target still owns its texture files, but the user has overridden how
    # its bindings are rebuilt, which is neither the target's authority nor the
    # imported model's.
    return replace(
        spec,
        material=MaterialAuthority.USER_MAPPED,
        writes_material_sidecar=bool(controls.rebuild_sidecar),
    )


def derive_builder_operation_flags(
    spec: MeshOperationSpec,
    controls: BuilderMaterialControls | None = None,
) -> BuilderOperationFlags:
    """What the classified operation writes.

    The tuning bits are the user's only where the specification leaves them so.
    Where the imported model owns the materials they are all on, and where the
    operation is a Modify Original clone they are all off, because the target's
    inherited layers are the thing being preserved.
    """

    controls = controls or BuilderMaterialControls()

    if spec.kind is OperationKind.MODIFY_ORIGINAL:
        tuning = bool(spec.writes_material_sidecar)
        return BuilderOperationFlags(
            rebuild_material_sidecar=tuning,
            complete_external_material_reset=tuning,
        )

    if spec.material is MaterialAuthority.IMPORTED:
        return BuilderOperationFlags(
            rebuild_material_sidecar=True,
            complete_external_swap=True,
            neutralize_inherited_material_layers=True,
            complete_external_material_reset=True,
            enable_missing_base_color_parameters=True,
            prune_unmapped_original_texture_parameters=True,
        )

    return BuilderOperationFlags(
        rebuild_material_sidecar=bool(controls.rebuild_sidecar),
        complete_external_swap=False,
        neutralize_inherited_material_layers=bool(controls.source_color_faithful),
        complete_external_material_reset=bool(controls.external_material_reset),
        enable_missing_base_color_parameters=bool(controls.inject_base_color),
        prune_unmapped_original_texture_parameters=bool(controls.prune_unmapped_original_dds),
    )


def builder_operation_flags(
    *,
    modify_original_clone_mode: bool = False,
    complete_swap_enabled: bool = False,
    full_import_model_replacement: bool = False,
    controls: BuilderMaterialControls | None = None,
    modify_original_tuning_enabled: bool = False,
) -> tuple[MeshOperationSpec, BuilderOperationFlags]:
    """Classify, then derive, in one call for the Builder's single call site."""

    controls = controls or BuilderMaterialControls()
    spec = classify_builder_operation(
        modify_original_clone_mode=modify_original_clone_mode,
        complete_swap_enabled=complete_swap_enabled,
        full_import_model_replacement=full_import_model_replacement,
        controls=controls,
        modify_original_tuning_enabled=modify_original_tuning_enabled,
    )
    return spec, derive_builder_operation_flags(spec, controls)


def operation_flag_disagreements(
    spec: MeshOperationSpec,
    flags: BuilderOperationFlags,
) -> tuple[str, ...]:
    """Where these flags contradict the operation they claim to implement.

    Only the flags the operation decides for itself are compared. In the
    geometry-only case four of them are independent user choices, and an
    operation that leaves a flag to the user cannot be contradicted by it.

    This is the check behind "no silent policy changes": a full replacement
    quietly reduced to geometry-only, or an imported material authority quietly
    switched back to the target's, shows up here as a disagreement between what
    the operation says and what the flags would actually build.
    """

    problems: list[str] = []
    imported = spec.material is MaterialAuthority.IMPORTED

    if bool(flags.rebuild_material_sidecar) != bool(spec.writes_material_sidecar):
        problems.append(
            f"operation {spec.kind.value} "
            f"{'writes' if spec.writes_material_sidecar else 'does not write'} a material sidecar, "
            f"but rebuild_material_sidecar is {bool(flags.rebuild_material_sidecar)}"
        )
    if bool(flags.complete_external_swap) != imported:
        problems.append(
            f"operation {spec.kind.value} gives material authority to "
            f"{spec.material.value}, but complete_external_swap is "
            f"{bool(flags.complete_external_swap)}"
        )

    tuning = {
        "neutralize_inherited_material_layers": bool(flags.neutralize_inherited_material_layers),
        "complete_external_material_reset": bool(flags.complete_external_material_reset),
        "enable_missing_base_color_parameters": bool(flags.enable_missing_base_color_parameters),
        "prune_unmapped_original_texture_parameters": bool(flags.prune_unmapped_original_texture_parameters),
    }
    if imported:
        off = sorted(name for name, value in tuning.items() if not value)
        if off:
            problems.append(
                f"operation {spec.kind.value} replaces the target's materials, "
                f"but these are off: {', '.join(off)}"
            )
    elif spec.kind is OperationKind.MODIFY_ORIGINAL:
        # A clone preserves the target's inherited layers; the texture-tuning
        # switch may reset its material response and nothing else may fire.
        on = sorted(
            name
            for name, value in tuning.items()
            if value and name != "complete_external_material_reset"
        )
        if on:
            problems.append(
                f"operation {spec.kind.value} keeps the target's material layers, "
                f"but these are on: {', '.join(on)}"
            )
        if tuning["complete_external_material_reset"] != bool(spec.writes_material_sidecar):
            problems.append(
                f"operation {spec.kind.value} "
                f"{'tunes' if spec.writes_material_sidecar else 'does not tune'} textures, "
                "but complete_external_material_reset disagrees"
            )
    return tuple(problems)


def option_operation_disagreements(options: object) -> tuple[str, ...]:
    """The same check against a replacement options object.

    Returns nothing when the options carry no operation. An options object
    nobody classified cannot be checked against a specification it does not
    have, and inventing one here would guess at the very intent this exists to
    verify.
    """

    spec = getattr(options, "operation_spec", None)
    if spec is None:
        return ()
    return operation_flag_disagreements(
        spec,
        BuilderOperationFlags(
            rebuild_material_sidecar=bool(getattr(options, "rebuild_material_sidecar", False)),
            complete_external_swap=bool(getattr(options, "complete_external_swap", False)),
            neutralize_inherited_material_layers=bool(
                getattr(options, "neutralize_inherited_material_layers", False)
            ),
            complete_external_material_reset=bool(
                getattr(options, "complete_external_material_reset", False)
            ),
            enable_missing_base_color_parameters=bool(
                getattr(options, "enable_missing_base_color_parameters", False)
            ),
            prune_unmapped_original_texture_parameters=bool(
                getattr(options, "prune_unmapped_original_texture_parameters", False)
            ),
        ),
    )


def _any_material_override(controls: BuilderMaterialControls) -> bool:
    return bool(
        controls.rebuild_sidecar
        or controls.source_color_faithful
        or controls.external_material_reset
        or controls.inject_base_color
        or controls.prune_unmapped_original_dds
    )


__all__ = [
    "BuilderMaterialControls",
    "BuilderOperationFlags",
    "builder_operation_flags",
    "classify_builder_operation",
    "derive_builder_operation_flags",
    "operation_flag_disagreements",
    "option_operation_disagreements",
]
