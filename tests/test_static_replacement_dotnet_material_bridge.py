from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    apply_material_parameter_preview,
    resident_material_parameter_group,
    resident_material_parameters_available,
    resident_material_preview_blocks_package_fallback,
    send_resident_material_parameters,
    send_source_role_material_parameters,
    source_part_material_parameter_groups_for_mesh,
    source_part_material_parameter_values,
)
from cdmw.modding.static_mesh_types import StaticSourcePartAdjustment


def test_resident_material_parameter_group_flattens_evaluated_values_and_preserves_zero() -> None:
    group = resident_material_parameter_group(
        {
            "texture_brightness": 1.2,
            "renderer_parameters": {"contrast": 1.4, "metalness": 0.0},
            "native_material_hints": {"roughness": 0.7},
            "ignored": "value",
        },
        source_submesh_indices=(3, 1, 3, -1),
    )

    assert group == {
        "source_submesh_indices": [1, 3],
        "editor_role": "replacement_preview",
        "texture_brightness": 1.2,
        "contrast": 1.4,
        "roughness": 0.7,
        "metalness": 0.0,
    }


def test_resident_material_parameter_bridge_requires_active_dotnet_session() -> None:
    calls: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )

    assert send_resident_material_parameters(dialog, ({"texture_brightness": 1.1},)) is True
    assert calls == [({"texture_brightness": 1.1},)]
    dialog._mesh_editor_embedded_dotnet_active = False
    assert send_resident_material_parameters(dialog, ({"texture_brightness": 1.2},)) is False
    assert len(calls) == 1

    dialog._mesh_editor_embedded_dotnet_active = True
    dialog._mesh_editor_embedded_resident_material_parameters_supported = False
    assert not resident_material_parameters_available(dialog)
    assert not send_resident_material_parameters(dialog, ({"texture_brightness": 1.3},))
    assert len(calls) == 1
    assert resident_material_preview_blocks_package_fallback(dialog, lambda: True)
    assert resident_material_preview_blocks_package_fallback(SimpleNamespace(), lambda: True)
    assert not resident_material_preview_blocks_package_fallback(SimpleNamespace(), lambda: False)


def test_resident_material_parameter_group_keeps_role_and_explicit_clear() -> None:
    group = resident_material_parameter_group(
        {"material_role": "cloth", "emissive_intensity": None, "emissive_color": None},
        source_submesh_indices=(2,),
    )

    assert group["material_role"] == "cloth"
    assert group["emissive_intensity"] is None
    assert group["emissive_color"] is None


def test_resident_material_parameter_group_preserves_part_visibility() -> None:
    hidden = resident_material_parameter_group({"visible": False}, source_submesh_indices=(3,))
    shown = resident_material_parameter_group({"visible": True}, source_submesh_indices=(3,))

    assert hidden["visible"] is False
    assert shown["visible"] is True


def test_material_preview_prefers_resident_dotnet_and_role_sender_normalizes_color() -> None:
    calls: list[tuple[dict[str, object], ...]] = []
    legacy = SimpleNamespace(set_material_overrides=lambda **_values: (_ for _ in ()).throw(AssertionError("legacy used")))
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )

    assert resident_material_parameters_available(dialog)
    assert apply_material_parameter_preview(
        dialog,
        {"texture_brightness": 1.25, "metalness": 0.0},
        legacy_active=True,
        legacy_host=legacy,
    )
    assert send_source_role_material_parameters(dialog, 4, "Glow", (255, 128, 0))
    assert calls[0][0]["metalness"] == 0.0
    assert calls[1][0]["material_role"] == "glow"
    assert calls[1][0]["emissive_color"] == (1.0, 128 / 255.0, 0.0)


def test_explicit_emissive_role_keeps_emissive_parameters_enabled() -> None:
    calls: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )

    assert send_source_role_material_parameters(dialog, 2, "emissive", (255, 255, 255), emissive_strength=0.5)
    assert calls[0][0]["material_role"] == "emissive"
    assert calls[0][0]["emissive_intensity"] == 0.5
    assert calls[0][0]["emissive_color"] == (1.0, 1.0, 1.0)


def test_global_material_preview_explicitly_clears_stale_optional_state() -> None:
    calls: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )
    model = SimpleNamespace(meshes=[SimpleNamespace(emissive_strength=2.0)])
    enabled = SimpleNamespace(emissive_mode="intensity", accent_glow_strength=100)
    disabled = SimpleNamespace(emissive_mode="disabled", accent_glow_strength=0)

    assert apply_material_parameter_preview(
        dialog,
        {"texture_brightness": 1.0, "roughness_blend_target": 1.0, "roughness_blend_strength": 1.0},
        legacy_active=False,
        legacy_host=None,
        preview_model=model,
        profile=enabled,
    )
    assert apply_material_parameter_preview(
        dialog,
        {"texture_brightness": 1.0},
        legacy_active=False,
        legacy_host=None,
        preview_model=model,
        profile=disabled,
    )

    assert calls[0][0]["roughness_blend_strength"] == 1.0
    assert calls[0][0]["emissive_intensity"] > 2.0
    reset = calls[1][0]
    assert reset["roughness_blend_target"] is None
    assert reset["roughness_blend_strength"] is None
    assert reset["emissive_intensity"] is None
    assert reset["emissive_color"] is None
    assert reset["material_role"] is None
    assert "visible" not in reset


def test_static_replacement_callbacks_route_parameters_before_legacy_fallback() -> None:
    root = Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "archive_browser"
    global_source = (root / "static_replacement_dialog_material_authority_callbacks.py").read_text(encoding="utf-8")
    part_source = (root / "static_replacement_dialog_callbacks_selected_part_control_part_01.py").read_text(encoding="utf-8")
    role_source = (root / "static_replacement_dialog_selection_mapping.py").read_text(encoding="utf-8")

    assert "apply_material_parameter_preview(" in global_source
    assert part_source.index("send_resident_material_parameters(") < part_source.index("set_material_overrides(")
    assert "send_source_role_material_parameters(" in role_source


def test_source_part_values_use_shared_export_evaluator() -> None:
    values = source_part_material_parameter_values(
        SimpleNamespace(
            brightness=20,
            contrast=-100,
            saturation=50,
            gamma=0.5,
            tint_rgb=(128, 255, 0),
        )
    )

    assert values["texture_brightness"] == 1.2
    assert values["contrast"] == pytest.approx(0.45)
    assert values["post_contrast_brightness"] == 1.1
    assert values["saturation"] == 1.5
    assert values["gamma"] == 0.5
    assert values["tint_color"] == [128 / 255.0, 1.0, 0.0]


def test_source_part_values_restore_static_adjustment_fields_and_glow() -> None:
    values = source_part_material_parameter_values(
        StaticSourcePartAdjustment(
            source_submesh_index=2,
            material_brightness=20,
            material_contrast=-100,
            material_saturation=50,
            material_gamma=0.5,
            material_tint_rgb=(128, 255, 0),
            material_role="glow",
            emissive_strength=0.25,
        )
    )

    assert values["texture_brightness"] == 1.2
    assert values["contrast"] == pytest.approx(0.45)
    assert values["saturation"] == 1.5
    assert values["gamma"] == 0.5
    assert values["material_role"] == "glow"
    assert values["emissive_intensity"] == 0.25


def test_auto_role_preserves_imported_emissive_in_resident_preview() -> None:
    calls: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: calls.append(tuple(groups)) or True,
    )

    assert send_source_role_material_parameters(
        dialog,
        1,
        "",
        (),
        source=SimpleNamespace(emissive_strength=0.25),
    )
    assert calls[0][0]["material_role"] == "emissive"
    assert calls[0][0]["emissive_intensity"] == 0.25


def test_restored_part_state_is_one_atomic_packet_with_explicit_role_clear() -> None:
    mesh = SimpleNamespace(
        submeshes=(SimpleNamespace(emissive_strength=0.5), SimpleNamespace(emissive_strength=None))
    )
    groups = source_part_material_parameter_groups_for_mesh(
        mesh,
        {
            0: StaticSourcePartAdjustment(0, enabled=False, material_role="glow", emissive_strength=2.0),
            1: StaticSourcePartAdjustment(1, material_brightness=25.0),
        },
        StaticSourcePartAdjustment,
    )

    assert len(groups) == 2
    assert groups[0]["visible"] is False
    assert groups[0]["material_role"] == "glow"
    assert groups[0]["emissive_intensity"] == 2.0
    assert groups[1]["texture_brightness"] == 1.25
    assert groups[1]["material_role"] is None
    assert groups[1]["emissive_intensity"] is None
    assert groups[1]["emissive_color"] is None
