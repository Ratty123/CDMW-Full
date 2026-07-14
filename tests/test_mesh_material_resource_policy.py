from __future__ import annotations

from cdmw.domain.mesh.material_resource_policy import mesh_material_resource_policy
from cdmw.modding.material_profiles import complete_swap_material_runtime_profiles


_REQUIRED_SOURCE_BASE_PROFILES = {
    "source_graph_strict",
    "material_authority_clean_source",
    "material_authority_true_source",
    "material_authority_pbr_source_test",
    "material_authority_detail_mask",
    "material_authority_placeholder_safe_test",
    "material_authority_manual",
    "material_authority_bruteforce",
    "material_authority_bruteforce_tuned",
}


def test_every_supported_material_profile_has_one_explicit_texture_criticality_policy() -> None:
    profiles = complete_swap_material_runtime_profiles()
    assert profiles
    for profile in profiles:
        base = mesh_material_resource_policy(
            profile.name,
            "base_color",
            concrete_expected_resource=True,
        )
        normal = mesh_material_resource_policy(
            profile.name,
            "normal",
            concrete_expected_resource=True,
        )
        assert base.profile == profile.name
        assert base.required is (profile.name in _REQUIRED_SOURCE_BASE_PROFILES)
        assert normal.required is False
        assert normal.fallback_policy == "flat_normal"


def test_required_policy_needs_a_concrete_resource_and_unknown_profiles_stay_optional() -> None:
    assert mesh_material_resource_policy(
        "material_authority_true_source",
        "base",
        concrete_expected_resource=True,
    ).required
    assert not mesh_material_resource_policy(
        "material_authority_true_source",
        "base",
        concrete_expected_resource=False,
    ).required
    unknown = mesh_material_resource_policy(
        "future_profile",
        "base",
        concrete_expected_resource=True,
    )
    assert not unknown.required
    assert unknown.fallback_policy == "neutral_checker"
