from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from cdmw.domain.textures.material_parameters import (
    effective_emissive_intensity,
    evaluate_material_parameters,
    profile_source_emissive_enabled,
    source_emissive_strength,
)
from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.modding.material_sidecar_patching import _apply_source_emissive_parameters
from cdmw.modding.material_replacer import ReplacementTextureSet
from cdmw.modding.material_source_driven import _complete_swap_accent_emissive_slot
from cdmw.modding.static_mesh_types import StaticSourcePartAdjustment
from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_groups_for_model,
    send_source_role_material_parameters,
)
from cdmw.ui.archive_browser.static_replacement_preview_textures import (
    apply_source_role_emissive_preview,
)


def _profile(accent: float) -> SimpleNamespace:
    return SimpleNamespace(
        emissive_mode="intensity",
        name="material_authority_manual",
        authority_contract="true_source_authority",
        accent_glow_strength=accent,
        accent_glow_intensity_max=5.5,
    )


def _imported_source(strength: float) -> SimpleNamespace:
    parameter = PreviewMaterialParameterInput(
        parameter_kind="float",
        parameter_name="_emissiveIntensity",
        value=str(strength),
        numeric_value=strength,
    )
    return SimpleNamespace(
        preview_material_texture_inputs=(
            PreviewMaterialTextureInput(slot_kind="emissive", material_parameters=(parameter,)),
        )
    )


def test_optional_part_strength_is_backward_compatible_and_nonnegative() -> None:
    old = StaticSourcePartAdjustment(source_submesh_index=2)
    explicit = StaticSourcePartAdjustment(source_submesh_index=2, emissive_strength=-4)

    assert old.emissive_strength is None
    assert "emissive_strength" in asdict(old)
    assert explicit.emissive_strength == 0.0
    assert StaticSourcePartAdjustment(**{"source_submesh_index": 2}).emissive_strength is None


def test_imported_strength_and_global_boost_share_one_evaluator() -> None:
    source = _imported_source(2.0)
    manual = StaticSourcePartAdjustment(source_submesh_index=0, material_role="glow")

    assert source_emissive_strength(source) == 2.0
    assert profile_source_emissive_enabled(_profile(0))
    assert effective_emissive_intensity(_profile(0), source=source, part_adjustment=manual) == 2.0
    assert effective_emissive_intensity(_profile(100), source=source, part_adjustment=manual) == 11.0

    manual.emissive_strength = 3.0
    values = evaluate_material_parameters(_profile(0), source_slot=source, part_adjustment=manual)
    assert values.emissive_intensity == 3.0


def test_subunit_imported_strength_is_not_promoted_to_default() -> None:
    source = _imported_source(0.25)
    assert source_emissive_strength(source) == 0.25
    assert effective_emissive_intensity(_profile(0), source=source) == 0.25


def test_accent_zero_keeps_imported_strength_in_preview_and_resident_packet() -> None:
    source = _imported_source(4.5)
    adjustment = StaticSourcePartAdjustment(source_submesh_index=0, material_role="glow")
    mesh = SimpleNamespace(
        material_name="Glow",
        preview_color=(1.0, 1.0, 1.0),
        preview_material_texture_inputs=source.preview_material_texture_inputs,
        preview_native_material_overrides={},
    )

    apply_source_role_emissive_preview(
        mesh,
        source_index=0,
        target_name="Glow",
        texture_set=SimpleNamespace(emissive_strength=4.5, accent_glow_color_rgb=()),
        adjustment=adjustment,
        profile=_profile(0),
        source_label="Glow",
    )
    assert mesh.preview_native_material_overrides["emissive_intensity"] == 4.5

    calls: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )
    assert send_source_role_material_parameters(dialog, 0, "glow", (), source=source, profile=_profile(0))
    assert calls[0][0]["emissive_intensity"] == 4.5


def test_global_resident_update_keeps_per_part_imported_strength() -> None:
    model = SimpleNamespace(meshes=(_imported_source(2.0), SimpleNamespace()))

    groups = resident_material_parameter_groups_for_model(
        {"renderer_parameters": {"texture_brightness": 1.2, "emissive_intensity": 1.0}},
        model,
        profile=_profile(0),
    )

    by_index = {tuple(group["source_submesh_indices"]): group for group in groups}
    assert by_index[(0,)]["emissive_intensity"] == 2.0
    assert by_index[(1,)]["emissive_intensity"] is None
    assert all(group["texture_brightness"] == 1.2 for group in groups)

    disabled = resident_material_parameter_groups_for_model(
        {"renderer_parameters": {"texture_brightness": 1.2}},
        model,
        profile=SimpleNamespace(emissive_mode="disabled"),
    )
    assert all(group["emissive_intensity"] is None for group in disabled)


def test_zero_strength_is_exported_as_an_explicit_disable() -> None:
    xml = '<MeshMaterialWrapper _subMeshName="Glow"><Vector></Vector></MeshMaterialWrapper>'
    patched, count = _apply_source_emissive_parameters(xml, {"Glow": ("#FFFFFFFF", 0.0)})

    assert count == 1
    assert '_name="_emissiveIntensity"' in patched
    assert '_value="0.000000"' in patched


def test_manual_glow_at_zero_global_boost_still_builds_export_slot() -> None:
    texture_set = ReplacementTextureSet(
        material_name="ManualGlow",
        source_role_tags=("glow",),
        base_color_factor=(0.2, 0.6, 1.0),
    )

    slot = _complete_swap_accent_emissive_slot(texture_set, "Target", _profile(0))

    assert slot is not None
    assert slot.slot_kind == "emissive"
