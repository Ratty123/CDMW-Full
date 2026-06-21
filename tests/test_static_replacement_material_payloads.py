from __future__ import annotations

from cdmw.modding.static_mesh_replacer import (
    StaticDonorMaterialPlan,
    StaticDonorMaterialTextureBinding,
    StaticSourceMaterialTextureOverride,
)
from cdmw.ui.archive_browser.static_replacement_material_payloads import (
    apply_source_material_texture_overrides_to_texture_sets,
    current_donor_material_plans,
    current_source_material_texture_overrides,
    donor_material_plan_payload,
    source_material_texture_override_payload,
)


def test_current_source_material_texture_overrides_filters_and_normalizes_assignments() -> None:
    overrides = current_source_material_texture_overrides(
        {
            ("Body", "BASE"): " body.dds ",
            ("", "normal"): "normal.dds",
            ("Cape", ""): "cape.dds",
            ("Cape", "normal"): "",
        }
    )

    assert source_material_texture_override_payload(overrides) == [
        ("Body", "base", "body.dds"),
    ]
    assert overrides[0].enabled is True


def test_current_donor_material_plans_filters_disabled_and_payloads_bindings() -> None:
    enabled_plan = StaticDonorMaterialPlan(
        target_material_name="Body",
        donor_sidecar_path="donor.xml",
        donor_material_name="DonorBody",
        donor_submesh_name="DonorMesh",
        donor_shader_family="shader",
        patch_mode="material_behavior",
        texture_bindings=[
            StaticDonorMaterialTextureBinding(
                parameter_name="_base",
                texture_path="base.dds",
                slot_kind="base",
                semantic_subtype="color",
            )
        ],
        enabled=True,
    )
    disabled_plan = StaticDonorMaterialPlan(target_material_name="Cape", enabled=False)

    plans = current_donor_material_plans({2: disabled_plan, 1: enabled_plan})

    assert plans == [enabled_plan]
    assert donor_material_plan_payload(plans) == [
        (
            "Body",
            "donor.xml",
            "DonorBody",
            "DonorMesh",
            "shader",
            "material_behavior",
            (("_base", "base.dds", "base", "color"),),
        )
    ]


def test_apply_source_material_texture_overrides_adds_existing_sources(tmp_path) -> None:
    normal_path = tmp_path / "body_green_up_normal.dds"
    normal_path.write_bytes(b"dds")
    missing_path = tmp_path / "missing.dds"
    texture_sets = {}

    apply_source_material_texture_overrides_to_texture_sets(
        texture_sets,
        (
            StaticSourceMaterialTextureOverride("Body", "normal", str(normal_path)),
            StaticSourceMaterialTextureOverride("Cape", "base", str(missing_path)),
        ),
    )

    assert set(texture_sets) == {"body"}
    slot = texture_sets["body"].slots["normal"]
    assert slot.material_name == "Body"
    assert slot.source_path == normal_path.resolve()
    assert slot.normal_space == "green_up"


def test_apply_source_material_texture_overrides_delegates_part_role_adjustments() -> None:
    calls = []
    texture_sets = {}
    replacement_mesh = object()
    adjustments = {"body": object()}

    apply_source_material_texture_overrides_to_texture_sets(
        texture_sets,
        (),
        replacement_mesh=replacement_mesh,
        source_part_adjustments=adjustments,
        apply_source_part_role_overrides=lambda sets, mesh, values: calls.append((sets, mesh, values)),
    )

    assert calls == [(texture_sets, replacement_mesh, tuple(adjustments.values()))]
