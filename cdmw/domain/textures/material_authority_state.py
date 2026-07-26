"""Canonical Material Authority control and resolved preview/export state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path


class MaterialAuthorityCapability(str, Enum):
    """How a Material Authority control participates in the exact pipeline."""

    ACTIVE = "active"
    INAPPLICABLE = "inapplicable"
    EXPERT_ONLY = "expert_only"
    BLOCKED = "blocked"


class MaterialAuthoritySyncStatus(str, Enum):
    """User-facing synchronization state for preview and export."""

    INACTIVE = "inactive"
    FAST_PREVIEW = "fast_preview"
    EXACT = "exact"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MaterialAuthorityControlSpec:
    key: str
    areas: tuple[str, ...]
    capability: MaterialAuthorityCapability
    artifact_channels: tuple[str, ...] = ()
    parameter_groups: tuple[str, ...] = ()
    expert_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialAuthorityControlState:
    key: str
    capability: MaterialAuthorityCapability
    effect: str
    reason: str = ""
    artifact_channels: tuple[str, ...] = ()
    parameter_groups: tuple[str, ...] = ()
    artifact_delta: bool | None = None
    parameter_delta: bool | None = None

    @property
    def enabled(self) -> bool:
        return self.capability is MaterialAuthorityCapability.ACTIVE


@dataclass(frozen=True, slots=True)
class MaterialAuthorityResolvedState:
    """Immutable state acknowledged by resident preview and consumed by export."""

    profile_token: str
    revision: int
    affected_submeshes: tuple[int, ...]
    dds_bindings: tuple[Mapping[str, object], ...]
    residual_parameter_groups: tuple[Mapping[str, object], ...]
    control_states: tuple[MaterialAuthorityControlState, ...]
    fingerprint: str
    status: MaterialAuthoritySyncStatus = MaterialAuthoritySyncStatus.FAST_PREVIEW
    status_reason: str = ""
    unsafe_expert_active: bool = False
    unsafe_export_acknowledged: bool = False
    preview_acknowledged: bool = False

    @property
    def exact(self) -> bool:
        return self.status is MaterialAuthoritySyncStatus.EXACT

    @property
    def build_allowed(self) -> bool:
        synchronized = self.exact or (
            self.unsafe_expert_active
            and self.unsafe_export_acknowledged
            and self.status is MaterialAuthoritySyncStatus.FAST_PREVIEW
        )
        return self.preview_acknowledged and synchronized and not any(
            state.capability is MaterialAuthorityCapability.BLOCKED
            for state in self.control_states
        )


def _spec(
    key: str,
    *areas: str,
    capability: MaterialAuthorityCapability = MaterialAuthorityCapability.ACTIVE,
    channels: Sequence[str] = (),
    parameters: Sequence[str] = (),
    expert_values: Sequence[str] = (),
) -> MaterialAuthorityControlSpec:
    return MaterialAuthorityControlSpec(
        key=key,
        areas=tuple(areas),
        capability=capability,
        artifact_channels=tuple(channels),
        parameter_groups=tuple(parameters),
        expert_values=tuple(expert_values),
    )


_CONTROL_SPECS = (
    # Automatic controls.
    _spec("global_gloss_reduction", "automatic", "manual", channels=("material_mask",)),
    _spec("auto_brightness", "automatic", channels=("base",)),
    _spec("source_brightness", "automatic", channels=("base",)),
    _spec("tone_contrast", "automatic", channels=("base",)),
    _spec("edge_relief", "automatic", channels=("normal", "height", "material_mask"), parameters=("height_scale",)),
    _spec("edge_relief_source", "automatic", channels=("normal", "height", "material_mask"), parameters=("height_scale",)),
    _spec("accent_glow", "automatic", channels=("emissive",), parameters=("emissive_intensity",)),
    _spec("part_colourise_color", "automatic", channels=("base",)),
    _spec("part_colourise_strength", "automatic", channels=("base",)),
    _spec("part_glow_color", "automatic", channels=("emissive",)),
    _spec("part_glow_strength", "automatic", channels=("emissive",), parameters=("emissive_intensity",)),
    # Manual routing and artifact controls.
    _spec(
        "base_binding_mode",
        "manual",
        channels=("base",),
        expert_values=("overlay_from_colorblend_slot",),
    ),
    _spec(
        "mask_binding_mode",
        "manual",
        channels=("material_mask",),
        expert_values=("color_blending_mask", "scratch_scalars"),
    ),
    _spec("support_policy", "manual", channels=("normal", "height", "material_mask")),
    _spec("emissive_mode", "manual", channels=("emissive",)),
    _spec("base_color_lift", "manual", channels=("base",)),
    _spec("base_color_gamma", "manual", channels=("base",)),
    _spec("base_color_saturation", "manual", channels=("base",)),
    _spec("base_color_value_max", "manual", channels=("base",)),
    _spec("base_color_scale", "manual", channels=("base",)),
    _spec("emissive_color_scale", "manual", channels=("emissive",)),
    _spec("emissive_color_saturation", "manual", channels=("emissive",)),
    _spec("emissive_color_value_max", "manual", channels=("emissive",)),
    _spec("roughness_default", "manual", channels=("material_mask",)),
    _spec("roughness_min", "manual", channels=("material_mask",)),
    _spec("roughness_scale", "manual", channels=("material_mask",)),
    _spec("roughness_max", "manual", channels=("material_mask",)),
    _spec("metallic_default", "manual", channels=("material_mask",)),
    _spec("metallic_min", "manual", channels=("material_mask",)),
    _spec("metallic_scale", "manual", channels=("material_mask",)),
    _spec("metallic_max", "manual", channels=("material_mask",)),
    _spec("displacement_scale_multiplier", "manual", channels=("height",), parameters=("height_scale",)),
    _spec("displacement_scale_max", "manual", channels=("height",), parameters=("height_scale",)),
    _spec("ao_default", "manual", channels=("material_mask",)),
    _spec("force_nonmetal", "manual", channels=("material_mask",)),
    _spec("roughness_inverted", "manual", channels=("material_mask",)),
    _spec("metallic_inverted", "manual", channels=("material_mask",)),
    _spec("allow_factor_only_authority", "manual", channels=("base",)),
    _spec("factor_only_material_mask", "manual", channels=("material_mask",)),
    _spec("force_neutral_layer_support", "manual", channels=("normal", "height", "material_mask")),
    # Target-dependent/sidecar-only controls stay outside the normal WYSIWYG contract.
    _spec("authority_contract", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("alpha_default", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("scratch_roughness", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("scratch_metallic", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("shine_scalar", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("neutral_color_rgb", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("preserve_scratch_alpha", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("preserve_target_layer_response", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
    _spec("source_color_layer_authority", "manual", capability=MaterialAuthorityCapability.EXPERT_ONLY),
)

MATERIAL_AUTHORITY_CONTROL_REGISTRY: Mapping[str, MaterialAuthorityControlSpec] = {
    spec.key: spec for spec in _CONTROL_SPECS
}
MATERIAL_AUTHORITY_AUTOMATIC_KEYS = frozenset(
    spec.key for spec in _CONTROL_SPECS if "automatic" in spec.areas
)
MATERIAL_AUTHORITY_MANUAL_KEYS = frozenset(
    spec.key for spec in _CONTROL_SPECS if "manual" in spec.areas
)
MATERIAL_AUTHORITY_EXPERT_KEYS = frozenset(
    spec.key
    for spec in _CONTROL_SPECS
    if spec.capability is MaterialAuthorityCapability.EXPERT_ONLY
)

if len(MATERIAL_AUTHORITY_CONTROL_REGISTRY) != len(_CONTROL_SPECS):
    raise RuntimeError("Material Authority controls must be classified exactly once.")


def material_authority_control_spec(key: object) -> MaterialAuthorityControlSpec | None:
    return MATERIAL_AUTHORITY_CONTROL_REGISTRY.get(str(key or "").strip())


def material_authority_control_states(
    values: Mapping[str, object],
    *,
    available_channels: Sequence[str],
    source_authoritative_channels: Sequence[str] = (),
    authoritative_default_keys: Sequence[str] | None = None,
    has_emissive_source: bool = False,
    has_explicit_glow_part: bool = False,
    target_height_supported: bool = True,
    target_support_readable: bool = True,
    factor_only_base_applicable: bool | None = None,
    factor_only_mask_applicable: bool | None = None,
    neutral_support_gap_applicable: bool | None = None,
    artifact_deltas: Mapping[str, bool] | None = None,
    parameter_deltas: Mapping[str, bool] | None = None,
) -> tuple[MaterialAuthorityControlState, ...]:
    """Resolve static registry entries against current source/target capabilities."""

    available = {str(channel or "").strip().lower() for channel in available_channels}
    authoritative = {
        str(channel or "").strip().lower() for channel in source_authoritative_channels
    }
    authoritative_defaults = (
        {str(key or "").strip() for key in authoritative_default_keys}
        if authoritative_default_keys is not None
        else None
    )
    deltas = dict(artifact_deltas or {})
    parameter_changes = dict(parameter_deltas or {})
    base_route_disabled = str(values.get("base_binding_mode", "") or "").strip().lower() == "disabled"
    mask_route_disabled = str(values.get("mask_binding_mode", "") or "").strip().lower() == "disabled"
    emissive_route_disabled = str(values.get("emissive_mode", "") or "").strip().lower() == "disabled"
    base_transform_keys = {
        "base_color_lift",
        "base_color_gamma",
        "base_color_saturation",
        "base_color_value_max",
        "base_color_scale",
        "auto_brightness",
        "source_brightness",
        "tone_contrast",
    }
    mask_transform_keys = {
        "global_gloss_reduction",
        "roughness_default",
        "roughness_min",
        "roughness_scale",
        "roughness_max",
        "metallic_default",
        "metallic_min",
        "metallic_scale",
        "metallic_max",
        "ao_default",
        "force_nonmetal",
        "roughness_inverted",
        "metallic_inverted",
    }
    emissive_transform_keys = {
        "emissive_color_scale",
        "emissive_color_saturation",
        "emissive_color_value_max",
        "accent_glow",
    }
    states: list[MaterialAuthorityControlState] = []
    for spec in _CONTROL_SPECS:
        capability = spec.capability
        reason = ""
        value = str(values.get(spec.key, "") or "").strip().lower()
        if capability is MaterialAuthorityCapability.EXPERT_ONLY:
            reason = "Target-dependent or sidecar-only; available under Unsafe Expert Controls."
        elif value and value in spec.expert_values:
            capability = MaterialAuthorityCapability.EXPERT_ONLY
            reason = f"{value} is an Unsafe Expert routing value."
        elif spec.key in base_transform_keys and base_route_disabled:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "The base color route is Disabled."
        elif spec.key in mask_transform_keys and mask_route_disabled:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "The PBR/material-mask route is Disabled."
        elif spec.key in emissive_transform_keys and emissive_route_disabled:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "The emissive route is Disabled."
        elif spec.key in {"part_glow_color", "part_glow_strength"} and not has_explicit_glow_part:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "At least one source part must be assigned Glow / emissive."
        elif spec.key == "allow_factor_only_authority" and factor_only_base_applicable is False:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "No source part has a missing base DDS with an imported base-color factor."
        elif spec.key == "factor_only_material_mask" and factor_only_mask_applicable is False:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "No source part has a missing PBR-mask DDS with imported roughness/metal factors."
        elif spec.key == "force_neutral_layer_support" and neutral_support_gap_applicable is False:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "The source already supplies the support channels; no neutral gap fill is needed."
        elif spec.key in {"roughness_default", "metallic_default", "ao_default"} and (
            spec.key in authoritative_defaults
            if authoritative_defaults is not None
            else any(channel in authoritative for channel in spec.artifact_channels)
        ):
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "The source channel is already authoritative; its missing-channel default is not used."
        elif spec.key in {"edge_relief", "edge_relief_source", "displacement_scale_multiplier", "displacement_scale_max"} and not target_height_supported:
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "No usable height/support resource is bound for preview and export."
        elif spec.key == "support_policy" and value == "keep_original_support" and not target_support_readable:
            capability = MaterialAuthorityCapability.EXPERT_ONLY
            reason = "The target support route cannot be read back exactly by the resident preview."
        elif spec.artifact_channels and not any(channel in available for channel in spec.artifact_channels):
            capability = MaterialAuthorityCapability.INAPPLICABLE
            missing = ", ".join(spec.artifact_channels)
            reason = f"Missing applicable source/target channel: {missing}."
        elif "emissive" in spec.artifact_channels and not (has_emissive_source or has_explicit_glow_part):
            capability = MaterialAuthorityCapability.INAPPLICABLE
            reason = "No source emissive channel or explicitly assigned glow part exists."

        delta = deltas.get(spec.key)
        parameter_delta = parameter_changes.get(spec.key)
        if capability is MaterialAuthorityCapability.ACTIVE and delta is False and parameter_delta is True:
            reason = "Canonical parameter delta; DDS bytes unchanged."
        elif capability is MaterialAuthorityCapability.ACTIVE and delta is False:
            reason = "No artifact delta at this value."
        effect = (
            "artifact+parameter"
            if spec.artifact_channels and spec.parameter_groups
            else "artifact"
            if spec.artifact_channels
            else "parameter"
        )
        states.append(
            MaterialAuthorityControlState(
                key=spec.key,
                capability=capability,
                effect=effect,
                reason=reason,
                artifact_channels=spec.artifact_channels,
                parameter_groups=spec.parameter_groups,
                artifact_delta=delta,
                parameter_delta=parameter_delta,
            )
        )
    return tuple(states)


_BAKED_PARAMETER_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "base": {
        "texture_brightness": 1.0,
        "contrast": 1.0,
        "post_contrast_brightness": 1.0,
        "saturation": 1.0,
        "gamma": 1.0,
        "tint_color": [1.0, 1.0, 1.0],
        # The recolour is baked into the published base DDS, so the
        # fast-preview parameter must return to identity or the exact result
        # would be repainted a second time by the shader.
        "base_tint_color": [1.0, 1.0, 1.0],
        "base_tint_strength": 0.0,
        "base_tint_authored": False,
        "base_color_lift": 0,
        "value_max": 255,
        "auto_balance": 0,
        "shadow_lift": 0,
    },
    "material_mask": {
        "roughness_inverted": False,
        "metalness_inverted": False,
        "roughness_scale": 1.0,
        "roughness_min": 0,
        "roughness_max": 255,
        "metalness_scale": 1.0,
        "metalness_min": 0,
        "metalness_max": 255,
        "roughness_blend_strength": 0.0,
        "metalness_blend_strength": 0.0,
    },
    "emissive": {
        "emissive_color": [1.0, 1.0, 1.0],
    },
}


def identity_residual_parameter_groups(
    groups: Sequence[Mapping[str, object]],
    *,
    baked_channels: Sequence[str],
) -> tuple[dict[str, object], ...]:
    """Return final renderer groups with every baked transform set to identity."""

    identities: dict[str, object] = {}
    for channel in baked_channels:
        identities.update(_BAKED_PARAMETER_IDENTITIES.get(str(channel or "").strip().lower(), {}))
    normalized: list[dict[str, object]] = []
    for raw_group in groups:
        group = dict(raw_group)
        group.update(identities)
        normalized.append(group)
    return tuple(normalized)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key) not in {"path", "source_dds_path", "output_root"}
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        rows = [_json_value(item) for item in value]
        return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True)) if isinstance(value, (set, frozenset)) else rows
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Material Authority fingerprints require finite values.")
        return round(value, 9)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def material_authority_fingerprint(
    *,
    profile_token: object,
    revision: int,
    affected_submeshes: Sequence[int],
    dds_bindings: Sequence[Mapping[str, object]],
    residual_parameter_groups: Sequence[Mapping[str, object]],
    control_states: Sequence[MaterialAuthorityControlState],
    unsafe_expert_active: bool = False,
    unsafe_export_acknowledged: bool = False,
) -> str:
    payload = {
        "profile_token": str(profile_token or ""),
        "revision": int(revision),
        "affected_submeshes": sorted({int(index) for index in affected_submeshes}),
        "dds_bindings": _json_value(tuple(dds_bindings)),
        "residual_parameter_groups": _json_value(tuple(residual_parameter_groups)),
        "control_states": _json_value(tuple(control_states)),
        "unsafe_expert_active": bool(unsafe_expert_active),
        "unsafe_export_acknowledged": bool(unsafe_export_acknowledged),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolved_material_authority_state(
    *,
    profile_token: object,
    revision: int,
    affected_submeshes: Sequence[int],
    dds_bindings: Sequence[Mapping[str, object]],
    residual_parameter_groups: Sequence[Mapping[str, object]],
    control_states: Sequence[MaterialAuthorityControlState],
    status: MaterialAuthoritySyncStatus = MaterialAuthoritySyncStatus.FAST_PREVIEW,
    status_reason: str = "",
    unsafe_expert_active: bool = False,
    unsafe_export_acknowledged: bool = False,
    preview_acknowledged: bool = False,
) -> MaterialAuthorityResolvedState:
    bindings = tuple(
        sorted(
            (dict(binding) for binding in dds_bindings),
            key=lambda binding: (
                str(binding.get("resource_id", "") or "").casefold(),
                str(binding.get("channel", "") or "").casefold(),
                str(binding.get("material_name", "") or "").casefold(),
                json.dumps(_json_value(binding.get("affected_submeshes", ())), sort_keys=True),
            ),
        )
    )
    parameters = tuple(
        sorted(
            (dict(group) for group in residual_parameter_groups),
            key=lambda group: json.dumps(_json_value(group), sort_keys=True),
        )
    )
    controls = tuple(control_states)
    affected = tuple(sorted({int(index) for index in affected_submeshes if int(index) >= 0}))
    fingerprint = material_authority_fingerprint(
        profile_token=profile_token,
        revision=revision,
        affected_submeshes=affected,
        dds_bindings=bindings,
        residual_parameter_groups=parameters,
        control_states=controls,
        unsafe_expert_active=unsafe_expert_active,
        unsafe_export_acknowledged=unsafe_export_acknowledged,
    )
    return MaterialAuthorityResolvedState(
        profile_token=str(profile_token or ""),
        revision=max(0, int(revision)),
        affected_submeshes=affected,
        dds_bindings=bindings,
        residual_parameter_groups=parameters,
        control_states=controls,
        fingerprint=fingerprint,
        status=status,
        status_reason=str(status_reason or ""),
        unsafe_expert_active=bool(unsafe_expert_active),
        unsafe_export_acknowledged=bool(unsafe_export_acknowledged),
        preview_acknowledged=bool(
            preview_acknowledged or status is MaterialAuthoritySyncStatus.EXACT
        ),
    )


def material_authority_status_text(
    status: MaterialAuthoritySyncStatus,
    reason: object = "",
) -> str:
    message = str(reason or "").strip()
    if status is MaterialAuthoritySyncStatus.INACTIVE:
        return "Inactive" if not message else f"Inactive: {message}"
    if status is MaterialAuthoritySyncStatus.FAST_PREVIEW:
        return "Fast preview—not yet exact" if not message else f"Fast preview—not yet exact: {message}"
    if status is MaterialAuthoritySyncStatus.EXACT:
        return "Exact preview/export synchronized"
    return f"Blocked: {message or 'Material Authority cannot be represented safely.'}"


__all__ = [
    "MATERIAL_AUTHORITY_AUTOMATIC_KEYS",
    "MATERIAL_AUTHORITY_CONTROL_REGISTRY",
    "MATERIAL_AUTHORITY_EXPERT_KEYS",
    "MATERIAL_AUTHORITY_MANUAL_KEYS",
    "MaterialAuthorityCapability",
    "MaterialAuthorityControlSpec",
    "MaterialAuthorityControlState",
    "MaterialAuthorityResolvedState",
    "MaterialAuthoritySyncStatus",
    "identity_residual_parameter_groups",
    "material_authority_control_spec",
    "material_authority_control_states",
    "material_authority_fingerprint",
    "material_authority_status_text",
    "resolved_material_authority_state",
]
