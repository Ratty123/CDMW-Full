"""Python-owned texture criticality policy for the resident Mesh Editor."""

from __future__ import annotations

from dataclasses import dataclass


_BASE_CHANNELS = frozenset({"base", "albedo", "diffuse", "base_color", "color"})
_SOURCE_BASE_REQUIRED_PROFILES = frozenset(
    {
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
)
_FALLBACK_BY_CHANNEL = {
    "base": "neutral_checker",
    "normal": "flat_normal",
    "roughness": "neutral_roughness",
    "metallic": "nonmetal",
    "material": "neutral_material",
    "specular": "neutral_specular",
    "emissive": "black",
    "height": "neutral_height",
}


def _key(value: object) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", "_").split())


def canonical_material_channel(channel: object) -> str:
    normalized = _key(channel)
    if normalized in _BASE_CHANNELS:
        return "base"
    if normalized == "metalness":
        return "metallic"
    return normalized or "unknown"


@dataclass(frozen=True, slots=True)
class MeshMaterialResourcePolicy:
    profile: str
    channel: str
    required: bool
    fallback_policy: str

    @property
    def criticality(self) -> str:
        return "required" if self.required else "optional"


def mesh_material_resource_policy(
    profile: object,
    channel: object,
    *,
    concrete_expected_resource: bool,
) -> MeshMaterialResourcePolicy:
    """Return one explicit policy; unknown/legacy profiles remain optional."""

    profile_key = _key(profile)
    channel_key = canonical_material_channel(channel)
    required = bool(
        concrete_expected_resource
        and channel_key == "base"
        and profile_key in _SOURCE_BASE_REQUIRED_PROFILES
    )
    return MeshMaterialResourcePolicy(
        profile=profile_key or "legacy_unknown",
        channel=channel_key,
        required=required,
        fallback_policy="block_ready" if required else _FALLBACK_BY_CHANNEL.get(channel_key, "diagnostic_only"),
    )


__all__ = [
    "MeshMaterialResourcePolicy",
    "canonical_material_channel",
    "mesh_material_resource_policy",
]
