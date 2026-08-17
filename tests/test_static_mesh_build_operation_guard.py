"""The static build refuses options that stopped describing their operation.

`option_operation_disagreements` is tested on its own in
`tests/test_mesh_builder_operation.py`. What is tested here is the thing a unit
test of the pure function cannot say: that the build actually consults it, and
that a disagreement stops it before any bytes are produced rather than being
reported alongside a successful rebuild.
"""

from __future__ import annotations

import dataclasses

import pytest

from cdmw.domain.mesh.builder_operation import classify_builder_operation
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    StaticReplacementTransform,
    StaticSubmeshMapping,
    build_static_mesh_replacement,
)
from cdmw.modding.mesh_parser import SubMesh

from tests.test_static_mesh_replacer_preview import _mesh, _minimal_pac_original


def _replacement_source():
    return _mesh(
        "replacement.obj",
        [
            SubMesh(
                name="replacement",
                material="replacement",
                vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )


def _options(**overrides) -> StaticMeshReplacementOptions:
    return StaticMeshReplacementOptions(
        transform=StaticReplacementTransform(
            alignment_mode="manual", scale_to_original_length=False
        ),
        submesh_mappings=[
            StaticSubmeshMapping(
                target_submesh_index=0,
                target_submesh_name="target",
                source_submesh_indices=[0],
                target_material_slot_index=0,
            )
        ],
        **overrides,
    )


def test_options_nobody_classified_still_build() -> None:
    # Every preview construction lands here. The guard must be inert for them,
    # or wiring it would have blocked paths it was never given an opinion about.
    original_data, original = _minimal_pac_original()

    rebuilt, report = build_static_mesh_replacement(
        original_data, original, _replacement_source(), _options()
    )

    assert report.ok
    assert rebuilt


def test_options_that_agree_with_their_operation_build() -> None:
    original_data, original = _minimal_pac_original()
    options = _options(operation_spec=classify_builder_operation())

    rebuilt, report = build_static_mesh_replacement(
        original_data, original, _replacement_source(), options
    )

    assert report.ok
    assert rebuilt


def test_a_full_replacement_reduced_to_geometry_only_is_refused() -> None:
    # The failure this closes: a build that produced new geometry against the
    # target's own material bindings while the session said it was replacing
    # everything, and reported success either way.
    original_data, original = _minimal_pac_original()
    options = _options(
        operation_spec=classify_builder_operation(complete_swap_enabled=True),
    )

    with pytest.raises(ValueError) as raised:
        build_static_mesh_replacement(
            original_data, original, _replacement_source(), options
        )

    message = str(raised.value)
    assert "no longer describe the operation" in message
    assert "complete_external_swap" in message


def test_a_clone_that_neutralizes_the_targets_layers_is_refused() -> None:
    original_data, original = _minimal_pac_original()
    options = _options(
        operation_spec=classify_builder_operation(modify_original_clone_mode=True),
        neutralize_inherited_material_layers=True,
    )

    with pytest.raises(ValueError) as raised:
        build_static_mesh_replacement(
            original_data, original, _replacement_source(), options
        )

    assert "neutralize_inherited_material_layers" in str(raised.value)


def test_the_full_import_preset_builds_because_it_names_its_own_operation() -> None:
    from cdmw.modding.full_import_model_replacement import (
        apply_full_import_model_replacement_preset,
    )

    original_data, original = _minimal_pac_original()
    preset = apply_full_import_model_replacement_preset(_options())
    # The preset forces the placement transform; this build wants the mappings
    # it was given rather than a refit, and neither is what is under test here.
    preset = dataclasses.replace(
        preset,
        transform=StaticReplacementTransform(
            alignment_mode="manual", scale_to_original_length=False
        ),
    )

    rebuilt, report = build_static_mesh_replacement(
        original_data, original, _replacement_source(), preset
    )

    assert report.ok
    assert rebuilt
