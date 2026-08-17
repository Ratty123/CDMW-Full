"""What the Builder's controls classify to, and what that operation writes.

The six option flags used to be six expressions evaluated side by side in the
Builder's accept path. These tests pin the classification and the derivation
separately, and then pin the pair against the expressions they replaced: the
whole value of naming the operation is lost if the naming quietly changes what a
build produces.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cdmw.domain.mesh.builder_operation import (
    BuilderMaterialControls,
    BuilderOperationFlags,
    builder_operation_flags,
    classify_builder_operation,
    derive_builder_operation_flags,
    operation_flag_disagreements,
    option_operation_disagreements,
)
from cdmw.domain.mesh.operation_spec import (
    MaterialAuthority as M,
    OperationKind as K,
)


ALL_CONTROLS_ON = BuilderMaterialControls(
    rebuild_sidecar=True,
    source_color_faithful=True,
    external_material_reset=True,
    inject_base_color=True,
    prune_unmapped_original_dds=True,
)


def _legacy_flags(
    *,
    modify_original_clone_mode: bool,
    complete_swap_enabled: bool,
    modify_original_tuning_enabled: bool,
    controls: BuilderMaterialControls,
) -> BuilderOperationFlags:
    """The expressions this module replaced, transcribed from the accept path.

    Kept as a test double rather than shared code on purpose: it is the thing
    under test, not a helper, and it should have to be edited deliberately if
    the product decision behind one of these flags ever changes.
    """

    clone = bool(modify_original_clone_mode)
    swap = bool(complete_swap_enabled) and not clone
    tuning = bool(modify_original_tuning_enabled)
    return BuilderOperationFlags(
        rebuild_material_sidecar=bool(
            tuning if clone else controls.rebuild_sidecar or swap
        ),
        complete_external_swap=bool(False if clone else swap),
        neutralize_inherited_material_layers=bool(
            False if clone else controls.source_color_faithful or swap
        ),
        complete_external_material_reset=bool(
            tuning if clone else controls.external_material_reset or swap
        ),
        enable_missing_base_color_parameters=bool(
            False if clone else controls.inject_base_color or swap
        ),
        prune_unmapped_original_texture_parameters=bool(
            False if clone else controls.prune_unmapped_original_dds or swap
        ),
    )


@pytest.mark.parametrize("clone", [False, True])
@pytest.mark.parametrize("swap", [False, True])
@pytest.mark.parametrize("tuning", [False, True])
@pytest.mark.parametrize(
    "controls",
    [
        BuilderMaterialControls(),
        ALL_CONTROLS_ON,
        BuilderMaterialControls(rebuild_sidecar=True),
        BuilderMaterialControls(source_color_faithful=True),
        BuilderMaterialControls(external_material_reset=True),
        BuilderMaterialControls(inject_base_color=True),
        BuilderMaterialControls(prune_unmapped_original_dds=True),
    ],
    ids=["none", "all", "sidecar", "faithful", "reset", "base_color", "prune"],
)
def test_deriving_from_a_specification_produces_the_flags_it_replaced(
    clone: bool,
    swap: bool,
    tuning: bool,
    controls: BuilderMaterialControls,
) -> None:
    _spec, flags = builder_operation_flags(
        modify_original_clone_mode=clone,
        complete_swap_enabled=swap,
        controls=controls,
        modify_original_tuning_enabled=tuning,
    )
    assert flags == _legacy_flags(
        modify_original_clone_mode=clone,
        complete_swap_enabled=swap,
        modify_original_tuning_enabled=tuning,
        controls=controls,
    )


def test_the_full_import_preset_classifies_as_the_full_asset() -> None:
    spec, flags = builder_operation_flags(full_import_model_replacement=True)
    assert spec.kind is K.REPLACE_FULL_ASSET
    assert flags == BuilderOperationFlags(
        rebuild_material_sidecar=True,
        complete_external_swap=True,
        neutralize_inherited_material_layers=True,
        complete_external_material_reset=True,
        enable_missing_base_color_parameters=True,
        prune_unmapped_original_texture_parameters=True,
    )


def test_the_full_import_preset_reaches_the_same_contract_as_the_swap_switch() -> None:
    preset, _ = builder_operation_flags(full_import_model_replacement=True)
    switch, _ = builder_operation_flags(complete_swap_enabled=True)
    assert preset == switch


def test_clone_mode_wins_over_the_swap_switch() -> None:
    # The Builder forces the switch off while cloning; a session that edits the
    # target's own mesh has no imported model to take material ownership.
    spec, flags = builder_operation_flags(
        modify_original_clone_mode=True,
        complete_swap_enabled=True,
        controls=ALL_CONTROLS_ON,
    )
    assert spec.kind is K.MODIFY_ORIGINAL
    assert flags == BuilderOperationFlags()


def test_modify_original_writes_a_sidecar_only_when_texture_tuning_is_on() -> None:
    plain = classify_builder_operation(modify_original_clone_mode=True)
    tuned = classify_builder_operation(
        modify_original_clone_mode=True,
        modify_original_tuning_enabled=True,
    )
    assert (plain.material, plain.writes_material_sidecar) == (M.ORIGINAL, False)
    assert (tuned.material, tuned.writes_material_sidecar) == (M.USER_MAPPED, True)
    assert tuned.kind is K.MODIFY_ORIGINAL


def test_geometry_only_keeps_the_targets_material_authority() -> None:
    spec = classify_builder_operation()
    assert spec.kind is K.REPLACE_GEOMETRY
    assert spec.material is M.ORIGINAL
    assert spec.retains_original_textures
    assert spec.retained_resources() == ("material_bindings", "textures")


def test_a_material_override_moves_geometry_only_to_user_mapped() -> None:
    spec = classify_builder_operation(
        controls=BuilderMaterialControls(source_color_faithful=True)
    )
    assert spec.kind is K.REPLACE_GEOMETRY
    assert spec.material is M.USER_MAPPED
    # The target still owns its texture files; only the bindings were overridden.
    assert spec.retains_original_textures
    assert spec.writes_material_sidecar is False


def test_the_sidecar_checkbox_is_what_makes_geometry_only_write_one() -> None:
    spec = classify_builder_operation(
        controls=BuilderMaterialControls(rebuild_sidecar=True)
    )
    assert spec.writes_material_sidecar is True
    assert "material_bindings" in spec.replaced_resources()


def test_the_full_asset_replaces_every_resource() -> None:
    spec = classify_builder_operation(complete_swap_enabled=True)
    assert spec.replaced_resources() == ("geometry", "material_bindings", "textures")
    assert spec.retained_resources() == ()


def test_the_tuning_bits_stop_being_the_users_where_the_import_owns_materials() -> None:
    spec = classify_builder_operation(complete_swap_enabled=True)
    with_controls = derive_builder_operation_flags(spec, ALL_CONTROLS_ON)
    without_controls = derive_builder_operation_flags(spec, BuilderMaterialControls())
    assert with_controls == without_controls


def test_controls_default_to_none_meaning_nothing_ticked() -> None:
    assert derive_builder_operation_flags(
        classify_builder_operation()
    ) == BuilderOperationFlags()


def test_option_field_names_match_the_options_dataclass() -> None:
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions

    fields = set(StaticMeshReplacementOptions.__dataclass_fields__)
    assert set(BuilderOperationFlags().as_option_fields()) <= fields


def test_flags_derived_from_an_operation_never_disagree_with_it() -> None:
    # The accept path builds both from one call, so this is the invariant that
    # says the check cannot fire on any route that exists today.
    for clone in (False, True):
        for swap in (False, True):
            for tuning in (False, True):
                for controls in (BuilderMaterialControls(), ALL_CONTROLS_ON):
                    spec, flags = builder_operation_flags(
                        modify_original_clone_mode=clone,
                        complete_swap_enabled=swap,
                        controls=controls,
                        modify_original_tuning_enabled=tuning,
                    )
                    assert operation_flag_disagreements(spec, flags) == ()


def test_the_full_import_preset_agrees_with_the_operation_it_names() -> None:
    from cdmw.modding.full_import_model_replacement import (
        apply_full_import_model_replacement_preset,
    )

    assert option_operation_disagreements(apply_full_import_model_replacement_preset()) == ()


def test_a_full_replacement_reduced_to_geometry_only_is_a_disagreement() -> None:
    spec = classify_builder_operation(complete_swap_enabled=True)
    _spec, honest = builder_operation_flags(complete_swap_enabled=True)
    reduced = replace(honest, complete_external_swap=False, rebuild_material_sidecar=False)

    problems = operation_flag_disagreements(spec, reduced)

    assert any("complete_external_swap" in problem for problem in problems)
    assert any("material sidecar" in problem for problem in problems)


def test_a_full_replacement_missing_one_tuning_bit_is_a_disagreement() -> None:
    spec, honest = builder_operation_flags(complete_swap_enabled=True)
    dropped = replace(honest, enable_missing_base_color_parameters=False)

    problems = operation_flag_disagreements(spec, dropped)

    assert len(problems) == 1
    assert "enable_missing_base_color_parameters" in problems[0]


def test_a_clone_that_neutralizes_the_targets_layers_is_a_disagreement() -> None:
    spec = classify_builder_operation(modify_original_clone_mode=True)
    leaked = BuilderOperationFlags(neutralize_inherited_material_layers=True)

    problems = operation_flag_disagreements(spec, leaked)

    assert any("neutralize_inherited_material_layers" in problem for problem in problems)


def test_geometry_only_leaves_its_four_tuning_bits_to_the_user() -> None:
    # The operation does not decide these, so no value of them contradicts it.
    # The sidecar flag is not among them: the operation does decide that one.
    spec = classify_builder_operation(controls=BuilderMaterialControls(inject_base_color=True))
    assert spec.writes_material_sidecar is False
    for flags in (
        BuilderOperationFlags(),
        BuilderOperationFlags(neutralize_inherited_material_layers=True),
        BuilderOperationFlags(enable_missing_base_color_parameters=True),
        BuilderOperationFlags(
            complete_external_material_reset=True,
            prune_unmapped_original_texture_parameters=True,
        ),
    ):
        assert operation_flag_disagreements(spec, flags) == ()


def test_geometry_only_still_decides_whether_a_sidecar_is_written() -> None:
    spec = classify_builder_operation()
    problems = operation_flag_disagreements(
        spec, BuilderOperationFlags(rebuild_material_sidecar=True)
    )
    assert any("material sidecar" in problem for problem in problems)


def test_options_without_an_operation_are_not_checked() -> None:
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions

    # Every preview construction and every direct construction in a test lands
    # here; guessing an operation for them would invent the intent this checks.
    assert option_operation_disagreements(StaticMeshReplacementOptions()) == ()
    assert option_operation_disagreements(object()) == ()


def test_options_carrying_an_operation_are_checked_against_their_flags() -> None:
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions

    options = StaticMeshReplacementOptions(
        operation_spec=classify_builder_operation(complete_swap_enabled=True),
    )

    problems = option_operation_disagreements(options)

    assert problems, "a full replacement with every flag off must not pass"
