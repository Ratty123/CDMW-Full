"""Material semantic contracts and signatures for resident .NET state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from cdmw.domain.mesh.material_resource_policy import canonical_material_channel
from cdmw.rendering.crimson_shader_registry import (
    decode_crimson_texture_binding,
    infer_shader_family_contract,
    normalize_shader_family,
)
from cdmw.services.mesh_dotnet_material_bindings import (
    _dotnet_material_name,
    _dotnet_material_sources,
    _dotnet_texture_name,
    _safe_int,
)
from cdmw.services.mesh_dotnet_material_channels import (
    _dotnet_initial_material_parameters,
    _dotnet_material_channel_components,
    _dotnet_material_normal_y_policy,
    _dotnet_resolved_texture_channels,
    _finite_float,
    _normalized_color_space,
)


def _dotnet_material_shader_context(
    source: object | None,
    channels: Mapping[str, str],
    source_asset_path: str,
) -> tuple[str, tuple[object, ...], Mapping[str, object], dict[str, object], str, str]:
    raw_family = str(getattr(source, "preview_sidecar_shader_family", "") or "").strip()
    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    if not raw_family:
        raw_family = next(
            (
                str(
                    (item.get("shader_family", "") if isinstance(item, Mapping) else getattr(item, "shader_family", ""))
                    or ""
                ).strip()
                for item in inputs
                if str(
                    (item.get("shader_family", "") if isinstance(item, Mapping) else getattr(item, "shader_family", ""))
                    or ""
                ).strip()
            ),
            "",
        )
    material_name = _dotnet_material_name(source) if source is not None else ""
    resolved_asset_path = str(
        getattr(source, "preview_source_asset_path", "") if source is not None else ""
    ).strip() or str(source_asset_path or "").strip()
    raw_overrides = getattr(source, "preview_native_material_overrides", {}) or {}
    overrides = raw_overrides if isinstance(raw_overrides, Mapping) else {}
    has_emissive_factor = bool(
        any(
            key in overrides and overrides.get(key) not in (None, "")
            for key in ("emissive_color", "emissive_intensity")
        )
        or str(overrides.get("material_role", "") or "").strip().casefold()
        in {"emissive", "glow"}
    )
    family_contract = infer_shader_family_contract(
        raw_family,
        material_name=material_name,
        asset_path=resolved_asset_path,
        has_emissive=bool(channels.get("emissive")) or has_emissive_factor,
    )
    shader_family = normalize_shader_family(family_contract.get("family", "")) or "generic"
    family_authority = str(family_contract.get("authority", "guess") or "guess")
    return raw_family, inputs, overrides, family_contract, shader_family, family_authority


def _dotnet_material_channel_contract(
    source: object | None,
    channels: Mapping[str, str],
    raw_family: str,
    inputs: tuple[object, ...],
    family_authority: str,
) -> tuple[dict[str, str], dict[str, str], list[dict[str, object]]]:
    channel_color_spaces = {
        str(channel): "srgb" if canonical_material_channel(channel) in {"base", "emissive"} else "linear"
        for channel in channels
    }
    channel_authorities = {str(channel): family_authority for channel in channels}
    layer_bindings: list[dict[str, object]] = []
    for item in inputs:
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().casefold()
        parameter_name = str(
            values.get("parameter_name", "") or getattr(item, "parameter_name", "") or ""
        ).strip()
        decode = decode_crimson_texture_binding(
            shader_family=raw_family,
            parameter_name=parameter_name,
            source_path=str(
                values.get("source_dds_path", "")
                or values.get("source_texture_path", "")
                or values.get("preview_texture_path", "")
                or getattr(item, "source_dds_path", "")
                or getattr(item, "source_texture_path", "")
                or getattr(item, "preview_texture_path", "")
                or ""
            ),
            slot_name=semantic or "material",
            semantic_subtype=str(
                values.get("semantic_subtype", "") or getattr(item, "semantic_subtype", "") or ""
            ),
            packed_channels=tuple(
                values.get("packed_channels", ()) or getattr(item, "packed_channels", ()) or ()
            ),
            layer_channel=str(
                values.get("layer_channel", "") or getattr(item, "layer_channel", "") or ""
            ),
            blend_flags=tuple(values.get("blend_flags", ()) or getattr(item, "blend_flags", ()) or ()),
            sidecar_kind=str(values.get("sidecar_kind", "") or getattr(item, "sidecar_kind", "") or ""),
            parameter_declared_by=str(
                values.get("parameter_declared_by", "")
                or getattr(item, "parameter_declared_by", "")
                or ""
            ),
        )
        channel = canonical_material_channel(str(decode.get("slot", "") or semantic))
        if channel in channels:
            explicit_space = _normalized_color_space(
                values.get("srgb_mode", "") or getattr(item, "srgb_mode", "") or ""
            )
            registry_space = _normalized_color_space(decode.get("srgb", ""))
            channel_color_spaces[channel] = explicit_space or registry_space or channel_color_spaces[channel]
            channel_authorities[channel] = str(decode.get("authority", "") or channel_authorities[channel])
        layer_role = str(values.get("layer_role", "") or getattr(item, "layer_role", "") or "").strip()
        layer_channel = str(
            values.get("layer_channel", "") or getattr(item, "layer_channel", "") or ""
        ).strip()
        if layer_role or layer_channel or str(decode.get("disposition", "")) == "layer_only":
            layer_bindings.append(
                {
                    "parameter": parameter_name,
                    "role": layer_role,
                    "channel": layer_channel,
                    "slot": str(decode.get("slot", "") or semantic),
                    "authority": str(decode.get("authority", "") or "guess"),
                    "disposition": str(decode.get("disposition", "") or ""),
                }
            )
    return channel_color_spaces, channel_authorities, layer_bindings


def _dotnet_material_alpha_contract(
    source: object | None,
    shader_family: str,
    channels: Mapping[str, str],
    overrides: Mapping[str, object],
) -> dict[str, object]:
    raw_alpha_mode = str(getattr(source, "preview_alpha_mode", "") or "").strip().casefold()
    alpha_mode = {
        "mask": "cutout",
        "alpha_cutout": "cutout",
        "coverage": "cutout",
        "transparent": "blend",
        "alpha": "blend",
    }.get(raw_alpha_mode, raw_alpha_mode or "opaque")
    if raw_alpha_mode:
        alpha_authority = "sidecar"
        alpha_reason = f"source declared alpha mode {raw_alpha_mode}"
    elif shader_family == "hair" and any(
        channels.get(channel) for channel in ("base", "albedo", "diffuse")
    ):
        alpha_mode = "cutout"
        alpha_authority = "inferred"
        alpha_reason = "hair/fur material with a bound color texture uses conservative alpha cutout"
    else:
        alpha_authority = "guess"
        alpha_reason = "no source alpha contract was available; opaque fallback retained"
    alpha_cutoff = 0.5
    for name in ("alpha_cutoff", "alpha_clip_threshold", "alpha_threshold"):
        candidate = _finite_float(overrides.get(name), minimum=0.0, maximum=1.0)
        if candidate is not None:
            alpha_cutoff = candidate
            break
    opacity_factor = _finite_float(overrides.get("opacity"), minimum=0.0, maximum=1.0)
    if opacity_factor is None:
        opacity_factor = _dotnet_material_parameter_opacity(source)
    if opacity_factor is None:
        opacity_factor = _finite_float(
            getattr(source, "preview_vertex_alpha_mean", None),
            minimum=0.0,
            maximum=1.0,
        )
    return {
        "alpha_mode": alpha_mode,
        "alpha_cutoff": alpha_cutoff,
        "opacity_factor": 1.0 if opacity_factor is None else opacity_factor,
        "alpha_authority": alpha_authority,
        "alpha_reason": alpha_reason,
    }


def _dotnet_material_parameter_opacity(source: object | None) -> float | None:
    opacity_parameter_names = {
        "alphafactor",
        "basecoloralphafactor",
        "diffusealphafactor",
        "gltfbasecoloralphafactor",
        "gltfdiffusealphafactor",
        "opacity",
        "opacityfactor",
    }
    for parameter in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        values = parameter if isinstance(parameter, Mapping) else vars(parameter) if hasattr(parameter, "__dict__") else {}
        name = re.sub(
            r"[^a-z0-9]+",
            "",
            str(values.get("parameter_name", "") or getattr(parameter, "parameter_name", "") or "").casefold(),
        )
        if name not in opacity_parameter_names:
            continue
        opacity_factor = _finite_float(
            values.get("numeric_value", None)
            if values.get("numeric_value", None) is not None
            else getattr(parameter, "numeric_value", None),
            minimum=0.0,
            maximum=1.0,
        )
        if opacity_factor is None:
            opacity_factor = _finite_float(
                values.get("value", None) if "value" in values else getattr(parameter, "value", None),
                minimum=0.0,
                maximum=1.0,
            )
        if opacity_factor is not None:
            return opacity_factor
    return None


def _dotnet_material_double_sided_contract(
    source: object | None,
    shader_family: str,
    family_authority: str,
) -> dict[str, object]:
    explicit_double_sided = bool(getattr(source, "preview_double_sided", False))
    inferred_hair_double_sided = (
        not explicit_double_sided
        and shader_family == "hair"
        and family_authority == "inferred"
    )
    double_sided = explicit_double_sided or inferred_hair_double_sided
    if explicit_double_sided:
        authority = "sidecar"
        reason = "source declared a double-sided material"
    elif inferred_hair_double_sided:
        authority = "inferred"
        reason = "inferred hair/fur cards require visible back faces"
    else:
        authority = "guess"
        reason = "no source double-sided contract was available"
    return {
        "double_sided": double_sided,
        "double_sided_authority": authority,
        "double_sided_reason": reason,
    }


def _dotnet_material_unsupported_features(
    alpha_mode: object,
    layer_bindings: list[dict[str, object]],
    shader_family: str,
) -> list[str]:
    unsupported_features: list[str] = []
    if alpha_mode == "blend":
        unsupported_features.append("per_triangle_alpha_blend_sorting")
    if layer_bindings:
        unsupported_features.append("shader_family_layer_graph")
    if shader_family in {"hair", "fur"}:
        unsupported_features.append("hair_fur_anisotropy_and_flow")
    if shader_family in {"skin", "skin_wrinkle"}:
        unsupported_features.append("skin_subsurface_and_wrinkle_response")
    return sorted(set(unsupported_features))


def _dotnet_material_semantic_contract(
    source: object | None,
    resolved_channels: Mapping[str, str] | None = None,
    *,
    source_asset_path: str = "",
) -> dict[str, object]:
    """Translate existing material evidence without inventing shader parity."""

    channels = dict(resolved_channels or _dotnet_resolved_texture_channels(source))
    (
        raw_family,
        inputs,
        overrides,
        family_contract,
        shader_family,
        family_authority,
    ) = _dotnet_material_shader_context(source, channels, source_asset_path)
    color_spaces, channel_authorities, layer_bindings = _dotnet_material_channel_contract(
        source, channels, raw_family, inputs, family_authority
    )
    alpha_contract = _dotnet_material_alpha_contract(source, shader_family, channels, overrides)
    double_sided_contract = _dotnet_material_double_sided_contract(
        source, shader_family, family_authority
    )
    material_category = str(overrides.get("material_category", "generic") or "generic").strip().casefold()
    material_category_confidence = _finite_float(
        overrides.get("material_category_confidence", 0.35),
        minimum=0.0,
        maximum=1.0,
    )
    raw_material_response_promoted = overrides.get("material_response_promoted", False)
    material_response_promoted = (
        raw_material_response_promoted.strip().casefold() in {"1", "true", "yes", "on"}
        if isinstance(raw_material_response_promoted, str)
        else bool(raw_material_response_promoted)
    )
    return {
        "shader_family": shader_family,
        "shader_technique": raw_family,
        "shader_authority": family_authority,
        "shader_family_source": str(family_contract.get("source", "") or ""),
        "shader_family_reason": str(family_contract.get("reason", "") or ""),
        "material_category": material_category,
        "material_category_confidence": (
            0.35 if material_category_confidence is None else material_category_confidence
        ),
        "material_category_reason": str(
            overrides.get("material_category_reason", "") or ""
        ).strip(),
        "material_response_promoted": material_response_promoted,
        "channel_color_spaces": dict(sorted(color_spaces.items())),
        "channel_authorities": dict(sorted(channel_authorities.items())),
        **alpha_contract,
        **double_sided_contract,
        "layer_bindings": layer_bindings,
        "unsupported_features": _dotnet_material_unsupported_features(
            alpha_contract["alpha_mode"], layer_bindings, shader_family
        ),
        "vertex_color": {
            "count": max(0, _safe_int(getattr(source, "preview_vertex_color_count", 0), 0)),
            "mean": list(tuple(getattr(source, "preview_vertex_color_mean", ()) or ())[:3]),
            "alpha_mean": getattr(source, "preview_vertex_alpha_mean", None),
            "alpha_min": getattr(source, "preview_vertex_alpha_min", None),
        },
    }


def _source_file_stat_key(source: Path) -> str:
    resolved = source.resolve()
    stat = source.stat()
    return f"{resolved}|size:{stat.st_size}|mtime:{stat.st_mtime_ns}".casefold()


def mesh_dotnet_material_input_signature(mesh: object) -> str:
    rows: list[dict[str, object]] = []
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    for submesh in _dotnet_material_sources(mesh):
        channels: list[tuple[str, str]] = []
        resolved_channels = _dotnet_resolved_texture_channels(submesh)
        for channel, value in sorted(resolved_channels.items()):
            raw_path = str(value or "").strip()
            source = Path(raw_path).expanduser()
            try:
                identity = _source_file_stat_key(source) if source.is_file() else raw_path
            except OSError:
                identity = raw_path
            channels.append((channel, identity))
        rows.append(
            {
                "material": _dotnet_material_name(submesh),
                "texture": _dotnet_texture_name(submesh),
                "texture_flip_vertical": bool(
                    getattr(submesh, "preview_texture_flip_vertical", False)
                ),
                "channels": channels,
                "normal_y_policy": _dotnet_material_normal_y_policy(submesh),
                "channel_components": _dotnet_material_channel_components(submesh),
                "semantic_contract": _dotnet_material_semantic_contract(
                    submesh,
                    resolved_channels,
                    source_asset_path=source_asset_path,
                ),
                "parameters": _dotnet_initial_material_parameters(
                    submesh, resolved_channels
                ),
            }
        )
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
