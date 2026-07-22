"""Package-time material translation for the resident .NET Mesh Editor."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage

from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.rendering.material_combiner import (
    MaterialPreviewCombinerSettings,
    combine_preview_material,
    synthesize_material_texture_inputs,
)
from cdmw.rendering.native_preview_material_contract import (
    _combiner_generated_authoritative_albedo,
)
from cdmw.services.mesh_dotnet_material_bindings import (
    _canonical_dotnet_material_source,
    _dotnet_material_slot_index,
)
from cdmw.services.mesh_dotnet_material_channels import (
    _dotnet_initial_material_parameters,
    _dotnet_material_channel_components,
    _dotnet_material_normal_y_policy,
    _dotnet_resolved_texture_channels,
)
from cdmw.services.mesh_dotnet_material_payload import (
    _dotnet_manifest_resource_bindings,
)
from cdmw.services.mesh_dotnet_material_semantics import (
    _dotnet_material_semantic_contract,
    _source_file_stat_key,
)


_GENERATED_COLOR_CHANNELS = ("base", "albedo", "diffuse")
_GENERATED_LINEAR_CHANNELS = {
    "height",
    "metallic",
    "normal",
    "occlusion",
    "roughness",
    "specular",
}
_GENERATED_SUPPORT_CHANNELS = _GENERATED_LINEAR_CHANNELS - {"normal"}
_DOMINANT_EQUIPMENT_METAL_Q50_MIN = 0.35
_DOMINANT_EQUIPMENT_METAL_Q90_MIN = 0.40
_DOMINANT_EQUIPMENT_METAL_COVERAGE_MIN = 0.50
_EQUIPMENT_FAMILY_METAL_REASONS = {
    "metal:armor_family_material_response",
    "metal:equipment_family_material_response",
    "metal:weapon_family_material_response",
}
_PACKED_SUBTYPE_CHANNELS = {
    "arm": {"metallic", "occlusion", "roughness"},
    "gltfmetallicroughness": {"metallic", "roughness"},
    "gltfspecularglossiness": {"roughness", "specular"},
    "metallicroughness": {"metallic", "roughness"},
    "mra": {"metallic", "occlusion", "roughness"},
    "orm": {"metallic", "occlusion", "roughness"},
    "rma": {"metallic", "occlusion", "roughness"},
    "specularglossiness": {"roughness", "specular"},
}
_SYNTHESIS_INPUT_SEMANTICS = {
    "detail_mask",
    "glossiness",
    "layer_mask",
    "mask",
    "material",
    "material_mask",
}


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _texture_reference_with_suffix(texture: str, suffix: str) -> str:
    normalized = str(texture or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    return normalized if Path(normalized).suffix else f"{normalized}{suffix}"


def _texture_reference_variant(texture: str, suffix: str) -> str:
    normalized = str(texture or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    base = Path(normalized).stem if Path(normalized).suffix else normalized
    extension = Path(normalized).suffix or ".dds"
    return f"{base}{suffix}{extension}"


def _dotnet_texture_channels(texture: str) -> dict[str, object]:
    base = _texture_reference_with_suffix(texture, ".dds")
    return {
        "base": base,
        "albedo": base,
        "diffuse": base,
        "normal": _texture_reference_variant(texture, "_n"),
        "specular": _texture_reference_variant(texture, "_s"),
        "roughness": _texture_reference_variant(texture, "_r"),
        "metallic": _texture_reference_variant(texture, "_m"),
        "emissive": _texture_reference_variant(texture, "_e"),
        "height": _texture_reference_variant(texture, "_h"),
        "material": _texture_reference_variant(texture, "_mat"),
    }


def _link_or_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _copy_dotnet_texture_channel_resources(
    channels: Mapping[str, str],
    package_dir: Path,
    copy_cache: dict[str, str],
) -> dict[str, str]:
    textures_dir = package_dir / "textures"
    result: dict[str, str] = {}
    for channel, value in channels.items():
        source = Path(str(value or "")).expanduser()
        if not source.is_file():
            continue
        cache_key = _source_file_stat_key(source)
        cached = copy_cache.get(cache_key)
        if cached:
            result[channel] = cached
            continue
        digest = hashlib.sha1(cache_key.encode("utf-8", errors="ignore")).hexdigest()[:10]
        target = textures_dir / f"{channel}_{digest}_{source.name}"
        if not target.is_file():
            _link_or_copy_file(source, target)
        relative = target.relative_to(package_dir).as_posix()
        copy_cache[cache_key] = relative
        result[channel] = relative
    return result


def _dotnet_material_slot_payload(slot: object, fallback_index: int) -> dict[str, object]:
    slot_map = slot if isinstance(slot, Mapping) else {}
    index = _safe_int(slot_map.get("index"), fallback_index)
    name = str(slot_map.get("name", "") or "").strip()
    texture = str(slot_map.get("texture", "") or "").strip()
    return {
        "index": index,
        "name": name,
        "texture": texture,
        "channels": _dotnet_texture_channels(texture),
    }


def _input_value(item: object, name: str, fallback: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(name, fallback)
    return getattr(item, name, fallback)


def _package_synthesis_inputs(
    source: object | None,
    raw_contract: Mapping[str, object],
) -> tuple[object, ...]:
    if source is None:
        return ()
    inputs = tuple(synthesize_material_texture_inputs(source))
    if not inputs:
        return ()
    if tuple(raw_contract.get("layer_bindings", ()) or ()):
        return inputs
    for item in inputs:
        semantic = str(
            _input_value(item, "semantic_type")
            or _input_value(item, "slot_kind")
            or ""
        ).strip().casefold()
        packed = tuple(_input_value(item, "packed_channels", ()) or ())
        layer_role = str(_input_value(item, "layer_role") or "").strip()
        layer_channel = str(_input_value(item, "layer_channel") or "").strip()
        binding_disposition = str(
            _input_value(item, "binding_disposition") or ""
        ).strip().casefold()
        direct_dispositions = {
            "diagnostic_only",
            "fallback_black",
            "fallback_flat_normal",
            "promoted",
            "recorded",
            "scalar_hint",
        }
        is_layer_input = bool(
            layer_channel
            or binding_disposition
            in {"layer_direction", "layer_flow", "layer_material_response", "layer_only"}
            or (layer_role and binding_disposition not in direct_dispositions)
        )
        if (
            semantic in _SYNTHESIS_INPUT_SEMANTICS
            or packed
            or is_layer_input
        ):
            return inputs
    return ()


class _CallbackStopEvent:
    def __init__(self, cancelled: Callable[[], bool] | None) -> None:
        self._cancelled = cancelled

    def is_set(self) -> bool:
        return bool(self._cancelled is not None and self._cancelled())


def _synthesis_preview_profile(
    item: object,
    *,
    high_resolution_mask: bool = False,
) -> tuple[int, str, str, str]:
    slot = str(_input_value(item, "slot_kind") or "").strip().casefold()
    semantic = str(_input_value(item, "semantic_type") or "").strip().casefold()
    color_input = slot in {"base", "color", "emissive"} or semantic in {
        "albedo",
        "base",
        "color",
        "diffuse",
        "emissive",
    }
    normal_input = slot == "normal" or semantic == "normal"
    max_dimension = 512 if color_input or high_resolution_mask else 192
    decode_slot = "base" if color_input else ("normal" if normal_input else "material")
    srgb = str(_input_value(item, "srgb_mode") or "").strip().casefold()
    if not srgb:
        srgb = "srgb" if color_input else "linear"
    normal_space = str(_input_value(item, "normal_space") or "").strip().casefold() or "auto"
    return max_dimension, decode_slot, srgb, normal_space


def _local_synthesis_dds_path(item: object) -> Path | None:
    for field_name in (
        "preview_texture_path",
        "source_dds_path",
        "source_texture_path",
    ):
        raw_path = str(_input_value(item, field_name) or "").strip()
        if not raw_path:
            continue
        if raw_path.casefold().startswith("file:"):
            raw_path = QUrl(raw_path).toLocalFile()
        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if path.suffix.casefold() == ".dds" and path.is_file():
            return path
    return None


def _has_native_support_map(
    item: object,
    raw_channels: Mapping[str, str],
) -> bool:
    slot = str(_input_value(item, "slot_kind") or "").strip().casefold()
    semantic = str(_input_value(item, "semantic_type") or "").strip().casefold()
    if slot == "normal" or semantic == "normal":
        channel = "normal"
    elif slot in {"height", "displacement"} or semantic in {"height", "displacement"}:
        channel = "height"
    else:
        return False
    raw_path = _local_synthesis_dds_path(
        {"source_dds_path": raw_channels.get(channel, "")}
    )
    return raw_path is not None


def _decode_synthesis_input_previews(
    inputs: tuple[object, ...],
    raw_channels: Mapping[str, str],
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[tuple[object, ...], int]:
    from cdmw.core.texture_native import (
        directxtex_preview_result_key,
        ensure_directxtex_dds_preview_pngs,
    )
    from cdmw.rendering.material_combiner_rules import _mask_inputs_for_albedo

    jobs: list[dict[str, object]] = []
    job_keys: dict[int, str] = {}
    albedo_mask_ids = {
        id(item)
        for item in _mask_inputs_for_albedo(
            tuple(
                item
                for item in inputs
                if isinstance(item, PreviewMaterialTextureInput)
            )
        ).values()
    }
    for index, item in enumerate(inputs):
        dds_path = _local_synthesis_dds_path(item)
        if dds_path is None:
            continue
        if _has_native_support_map(item, raw_channels):
            continue
        max_dimension, slot_kind, srgb, normal_space = _synthesis_preview_profile(
            item,
            high_resolution_mask=id(item) in albedo_mask_ids,
        )
        jobs.append(
            {
                "dds_path": str(dds_path),
                "max_dimension": max_dimension,
                "slot_kind": slot_kind,
                "srgb": srgb,
                "normal_space": normal_space,
            }
        )
        job_keys[index] = directxtex_preview_result_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
        )
    if not jobs:
        return inputs, 0
    results = ensure_directxtex_dds_preview_pngs(
        jobs,
        include_job_keys=True,
        stop_event=_CallbackStopEvent(cancelled),
    )
    decoded = 0
    updated_inputs = list(inputs)
    for index, result_key in job_keys.items():
        preview_path = results.get(result_key)
        if preview_path is None or not preview_path.is_file():
            continue
        item = inputs[index]
        if not isinstance(item, PreviewMaterialTextureInput):
            continue
        updated_inputs[index] = replace(
            item,
            preview_texture_path=str(preview_path),
        )
        decoded += 1
    return tuple(updated_inputs), decoded


def _decoded_base_alpha_summary(
    inputs: tuple[object, ...],
    *,
    cutoff: float,
) -> dict[str, object]:
    """Summarize a decoded color texture only for conservative alpha policy."""

    from cdmw.rendering.material_combiner_rules import _is_visible_color_input

    for item in inputs:
        if not isinstance(item, PreviewMaterialTextureInput) or not _is_visible_color_input(item):
            continue
        source = str(getattr(item, "preview_texture_path", "") or "").strip()
        if not source:
            continue
        local_path = QUrl(source).toLocalFile() or source
        image = QImage(local_path)
        if image.isNull() or not image.hasAlphaChannel():
            continue
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width = int(image.width())
        height = int(image.height())
        if width <= 0 or height <= 0:
            continue
        step = 1
        while ((width + step - 1) // step) * ((height + step - 1) // step) > 65_536:
            step += 1
        samples = [
            image.pixelColor(x, y).alphaF()
            for y in range(0, height, step)
            for x in range(0, width, step)
        ]
        if not samples:
            continue
        samples.sort()
        q90 = samples[min(len(samples) - 1, int((len(samples) - 1) * 0.90))]
        resolved_cutoff = max(0.0, min(1.0, float(cutoff)))
        coverage = sum(value >= resolved_cutoff for value in samples) / len(samples)
        return {
            "source_texture_name": Path(local_path).name,
            "sample_count": len(samples),
            "alpha_q90": round(float(q90), 6),
            "coverage_at_cutoff": round(float(coverage), 6),
            "cutoff": round(resolved_cutoff, 6),
        }
    return {}


def _decoded_linear_channel_summary(source: object) -> dict[str, object]:
    """Summarize a decoded scalar map without retaining its pixel payload."""

    reference = str(source or "").strip()
    if not reference:
        return {}
    local_path = QUrl(reference).toLocalFile() or reference
    image = QImage(local_path)
    if image.isNull():
        return {}
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = int(image.width())
    height = int(image.height())
    if width <= 0 or height <= 0:
        return {}
    step = 1
    while ((width + step - 1) // step) * ((height + step - 1) // step) > 65_536:
        step += 1
    samples = [
        image.pixelColor(x, y).redF()
        for y in range(0, height, step)
        for x in range(0, width, step)
    ]
    if not samples:
        return {}
    samples.sort()
    q50 = samples[min(len(samples) - 1, int((len(samples) - 1) * 0.50))]
    q90 = samples[min(len(samples) - 1, int((len(samples) - 1) * 0.90))]
    coverage = sum(value > 0.25 for value in samples) / len(samples)
    return {
        "source_texture_name": Path(local_path).name,
        "sample_count": len(samples),
        "mean": round(float(sum(samples) / len(samples)), 6),
        "q50": round(float(q50), 6),
        "q90": round(float(q90), 6),
        "coverage_above_0_25": round(float(coverage), 6),
    }


def _refine_synthesized_material_contract(
    semantic_contract: Mapping[str, object],
    synthesis: Mapping[str, object],
    *,
    source_asset_path: str = "",
) -> dict[str, object]:
    """Apply evidence available only after shared material-map synthesis."""

    refined = dict(semantic_contract)
    generated = {
        str(value or "").strip().casefold()
        for value in tuple(synthesis.get("generated_channels", ()) or ())
    }
    metallic_summary = synthesis.get("metallic_summary")
    dominant_metal = (
        "metallic" in generated
        and isinstance(metallic_summary, Mapping)
        and float(metallic_summary.get("q50", 0.0) or 0.0)
        >= _DOMINANT_EQUIPMENT_METAL_Q50_MIN
        and float(metallic_summary.get("q90", 0.0) or 0.0)
        >= _DOMINANT_EQUIPMENT_METAL_Q90_MIN
        and float(metallic_summary.get("coverage_above_0_25", 0.0) or 0.0)
        >= _DOMINANT_EQUIPMENT_METAL_COVERAGE_MIN
    )
    source_category = str(
        refined.get("material_category", "") or ""
    ).strip().casefold()
    source_reason = str(
        refined.get("material_category_reason", "") or ""
    ).strip()
    normalized_source_path = str(source_asset_path or "").replace("\\", "/").casefold()
    if (
        str(refined.get("shader_family", "") or "").strip().casefold()
        in {"standard", "standard_v2"}
        and source_category == "metal"
        and source_reason.casefold()
        in _EQUIPMENT_FAMILY_METAL_REASONS
    ):
        refined["material_category_pre_synthesis_reason"] = source_reason
        if dominant_metal:
            refined["material_category_confidence"] = 0.88
            refined["material_category_reason"] = (
                "metal:dominant_decoded_equipment_metal_channel"
            )
            refined["material_response_promoted"] = True
        else:
            refined["material_category"] = "generic"
            refined["material_category_confidence"] = 0.72 if "metallic" in generated else 0.68
            if "metallic" in generated:
                # Mixed leather/cloth and metal armor still keeps its decoded
                # per-pixel map; it must not receive a whole-submesh metal
                # fallback merely because the PAC lives in an armor slot.
                refined["material_category_reason"] = (
                    "generic:equipment_material_response_without_dominant_decoded_metal_channel"
                )
            else:
                refined["material_category_reason"] = (
                    "generic:equipment_material_response_without_decoded_metal_channel"
                )
            refined["material_response_promoted"] = False
    elif (
        str(refined.get("shader_family", "") or "").strip().casefold()
        in {"standard", "standard_v2"}
        and source_category == "generic"
        and source_reason.casefold() == "generic:no_strong_material_token"
        and any(
            family_token in normalized_source_path
            for family_token in ("/armor/", "/equipment/", "/weapon/")
        )
        and dominant_metal
    ):
        # A generic part name such as ``...Sword_0036`` deliberately carries
        # no lexical metal promise.  The owning equipment path plus a dense
        # synthesized metal map is stronger post-synthesis evidence and does
        # not affect named cloth/leather/handle categories.
        refined["material_category_pre_synthesis_reason"] = source_reason
        refined["material_category"] = "metal"
        refined["material_category_confidence"] = 0.88
        refined["material_category_reason"] = (
            "metal:dominant_decoded_equipment_metal_channel"
        )
        refined["material_response_promoted"] = True

    alpha_summary = synthesis.get("base_alpha_summary")
    if (
        isinstance(alpha_summary, Mapping)
        and str(refined.get("alpha_mode", "") or "").strip().casefold() == "cutout"
        and str(refined.get("alpha_authority", "") or "").strip().casefold() == "inferred"
    ):
        cutoff = float(refined.get("alpha_cutoff", 0.5) or 0.5)
        q90 = float(alpha_summary.get("alpha_q90", 1.0) or 0.0)
        coverage = float(alpha_summary.get("coverage_at_cutoff", 1.0) or 0.0)
        if q90 <= cutoff and coverage <= 0.10:
            refined["alpha_mode"] = "opaque"
            refined["alpha_cutoff"] = 0.5
            refined["alpha_authority"] = "inferred_fallback"
            refined["alpha_reason"] = (
                "inferred hair cutout would discard at least 90% of the decoded color texture; "
                "opaque card fallback retained"
            )
    return refined


def _source_has_usable_tangents(source: object | None) -> bool:
    if source is None:
        return False
    explicit = getattr(source, "preview_tangents_usable", None)
    if explicit is not None:
        return bool(explicit)
    vertices = tuple(
        getattr(source, "vertices", ()) or getattr(source, "positions", ()) or ()
    )
    uvs = tuple(
        getattr(source, "uvs", ())
        or getattr(source, "texture_coordinates", ())
        or ()
    )
    return bool(vertices and len(vertices) == len(uvs))


def _local_combiner_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.casefold().startswith("file:"):
        return QUrl(text).toLocalFile()
    return text


def _normalized_support_channel(value: object) -> str:
    normalized = str(value or "").strip().casefold().replace("metalness", "metallic")
    normalized = {"ao": "occlusion", "glossiness": "roughness"}.get(
        normalized, normalized
    )
    return normalized if normalized in _GENERATED_SUPPORT_CHANNELS else ""


def _decoded_support_replacement_channels(
    inputs: tuple[object, ...],
    raw_contract: Mapping[str, object],
    combined: object,
) -> set[str]:
    decoded: set[str] = set()
    for item in inputs:
        decoded.update(
            channel
            for channel in (
                _normalized_support_channel(value)
                for value in tuple(_input_value(item, "packed_channels", ()) or ())
            )
            if channel
        )
        subtype_key = "".join(
            character
            for character in str(_input_value(item, "semantic_subtype") or "").casefold()
            if character.isalnum()
        )
        decoded.update(_PACKED_SUBTYPE_CHANNELS.get(subtype_key, ()))
        if _input_value(item, "layer_role") or _input_value(item, "layer_channel"):
            channel = _normalized_support_channel(
                _input_value(item, "semantic_type") or _input_value(item, "slot_kind")
            )
            if channel:
                decoded.add(channel)
    for binding in tuple(raw_contract.get("layer_bindings", ()) or ()):
        if not isinstance(binding, Mapping):
            continue
        channel = _normalized_support_channel(binding.get("slot"))
        if channel:
            decoded.add(channel)
    notes = tuple(
        str(note or "").strip().casefold()
        for note in tuple(getattr(combined, "notes", ()) or ())
    )
    if any(
        note.startswith(("material layer mask applied:", "material slots blended:"))
        for note in notes
    ):
        decoded.update(
            channel
            for channel in (
                _normalized_support_channel(value)
                for value in tuple(getattr(combined, "outputs", ()) or ())
            )
            if channel
        )
    return decoded


def _generated_channels(
    combined: object,
    raw_channels: Mapping[str, str],
    inputs: tuple[object, ...],
    raw_contract: Mapping[str, object],
) -> dict[str, str]:
    generated: dict[str, str] = {}
    base = _local_combiner_path(getattr(combined, "base_source", ""))
    raw_color_available = any(
        str(raw_channels.get(channel, "") or "").strip()
        for channel in _GENERATED_COLOR_CHANNELS
    )
    generated_albedo_is_authoritative = _combiner_generated_authoritative_albedo(
        {
            "notes": tuple(getattr(combined, "notes", ()) or ()),
            "outputs": tuple(getattr(combined, "outputs", ()) or ()),
        }
    )
    if base and (generated_albedo_is_authoritative or not raw_color_available):
        generated.update({channel: base for channel in _GENERATED_COLOR_CHANNELS})
    decoded_support_channels = _decoded_support_replacement_channels(
        inputs, raw_contract, combined
    )
    for source_field, channel in (
        ("normal_source", "normal"),
        ("roughness_source", "roughness"),
        ("metalness_source", "metallic"),
        ("specular_source", "specular"),
        ("height_source", "height"),
        ("occlusion_source", "occlusion"),
    ):
        path = _local_combiner_path(getattr(combined, source_field, ""))
        raw_channel_available = bool(str(raw_channels.get(channel, "") or "").strip())
        if not path:
            continue
        if channel == "normal" and raw_channel_available:
            continue
        if channel == "height" and _local_synthesis_dds_path(
            {"source_dds_path": raw_channels.get(channel, "")}
        ) is not None:
            continue
        if (
            channel in _GENERATED_SUPPORT_CHANNELS
            and raw_channel_available
            and channel not in decoded_support_channels
        ):
            continue
        generated[channel] = path
    return generated


def _synthesis_input_identity(item: object) -> str:
    for field in ("source_texture_path", "source_dds_path", "preview_texture_path"):
        value = str(_input_value(item, field) or "").replace("\\", "/").strip().casefold()
        if value:
            return value
    return ""


def _synthesis_input_channel(item: object) -> str:
    semantic = str(
        _input_value(item, "semantic_type") or _input_value(item, "slot_kind") or ""
    ).strip().casefold()
    if semantic in {"albedo", "base", "color", "diffuse"}:
        return "base"
    if semantic in {"detail", "detail_mask", "layer_mask", "mask", "material_mask"}:
        return "control"
    return semantic


def _layer_graph_is_source_identity(inputs: tuple[object, ...]) -> bool:
    """Return true only when every layer source reuses its owning base source."""

    baseline_sources: dict[str, set[str]] = {}
    for item in inputs:
        disposition = str(_input_value(item, "binding_disposition") or "").strip().casefold()
        channel = _synthesis_input_channel(item)
        identity = _synthesis_input_identity(item)
        parameter_key = "".join(
            character
            for character in str(_input_value(item, "parameter_name") or "").casefold()
            if character.isalnum()
        )
        is_baseline = disposition == "promoted" or (
            channel == "material"
            and parameter_key == "materialtexture"
            and disposition == "layer_material_response"
        )
        if is_baseline and channel and identity:
            baseline_sources.setdefault(channel, set()).add(identity)

    found_layer_source = False
    for item in inputs:
        disposition = str(_input_value(item, "binding_disposition") or "").strip().casefold()
        if disposition not in {"layer_material_response", "layer_only"}:
            continue
        channel = _synthesis_input_channel(item)
        if channel == "control":
            continue
        found_layer_source = True
        identity = _synthesis_input_identity(item)
        if not identity or identity not in baseline_sources.get(channel, set()):
            return False
    return found_layer_source


def _combiner_outputs_have_raw_channels(
    combined: object,
    raw_channels: Mapping[str, str],
) -> bool:
    outputs = {
        str(value or "").strip().casefold().replace("metalness", "metallic")
        for value in tuple(getattr(combined, "outputs", ()) or ())
        if str(value or "").strip()
    }
    if not outputs:
        return False
    for output in outputs:
        if output == "legacy_material":
            continue
        if output == "albedo":
            if not any(
                str(raw_channels.get(channel, "") or "").strip()
                for channel in _GENERATED_COLOR_CHANNELS
            ):
                return False
            continue
        if not str(raw_channels.get(output, "") or "").strip():
            return False
    return True


def _synthesize_dotnet_material_channels(
    source: object | None,
    raw_channels: Mapping[str, str],
    raw_contract: Mapping[str, object],
    *,
    output_dir: Path,
    batch_index: int,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, str], dict[str, object], tuple[str, ...]]:
    inputs = _package_synthesis_inputs(source, raw_contract)
    if not inputs:
        return dict(raw_channels), {"attempted": False, "succeeded": False}, ()
    if cancelled is not None and cancelled():
        return dict(raw_channels), {
            "attempted": False,
            "succeeded": False,
            "skipped": "cancelled",
        }, ()
    try:
        inputs, decoded_preview_input_count = _decode_synthesis_input_previews(
            inputs,
            raw_channels,
            cancelled=cancelled,
        )
        base_alpha_summary = (
            _decoded_base_alpha_summary(
                inputs,
                cutoff=float(raw_contract.get("alpha_cutoff", 0.5) or 0.5),
            )
            if str(raw_contract.get("alpha_mode", "") or "").strip().casefold() == "cutout"
            and str(raw_contract.get("alpha_authority", "") or "").strip().casefold()
            == "inferred"
            else {}
        )
        combined = combine_preview_material(
            SimpleNamespace(
                material_name=str(getattr(source, "material", "") or getattr(source, "name", "") or ""),
                texture_name=str(getattr(source, "texture", "") or ""),
                texture_flip_vertical=bool(getattr(source, "preview_texture_flip_vertical", False)),
                material_texture_inputs=inputs,
                alpha_mode=str(getattr(source, "preview_alpha_mode", "") or ""),
                tangents_usable=_source_has_usable_tangents(source),
                normal_texture_strength=max(
                    0.0, float(getattr(source, "preview_normal_texture_strength", 0.0) or 0.0)
                ),
            ),
            output_dir,
            batch_index,
            settings=MaterialPreviewCombinerSettings(
                normal_strength_floor=0.5,
                normal_strength_cap=1.0,
                height_amount=0.028,
                support_map_max_dimension=192,
                preserve_texture_orientation=True,
            ),
            cancelled=cancelled,
        )
    except RunCancelled:
        shutil.rmtree(output_dir, ignore_errors=True)
        return dict(raw_channels), {
            "attempted": True,
            "succeeded": False,
            "skipped": "cancelled_during_synthesis",
        }, ()
    except Exception as exc:
        shutil.rmtree(output_dir, ignore_errors=True)
        return dict(raw_channels), {
            "attempted": True,
            "succeeded": False,
            "failure": f"{type(exc).__name__}: {exc}",
        }, ()
    if cancelled is not None and cancelled():
        shutil.rmtree(output_dir, ignore_errors=True)
        return dict(raw_channels), {
            "attempted": True,
            "succeeded": False,
            "skipped": "cancelled_after_synthesis",
        }, ()
    generated = _generated_channels(combined, raw_channels, inputs, raw_contract)
    identity_noop = bool(
        not generated
        and tuple(raw_contract.get("layer_bindings", ()) or ())
        and _layer_graph_is_source_identity(inputs)
        and _combiner_outputs_have_raw_channels(combined, raw_channels)
    )
    if not generated:
        shutil.rmtree(output_dir, ignore_errors=True)
    channels = dict(raw_channels)
    channels.update(generated)
    synthesis_notes = list(tuple(getattr(combined, "notes", ()) or ()))
    if identity_noop:
        synthesis_notes.append("material graph resolved as source-identity no-op")
    metadata: dict[str, object] = {
        "attempted": True,
        "succeeded": bool(generated) or identity_noop,
        "identity_noop": identity_noop,
        "outputs": list(tuple(getattr(combined, "outputs", ()) or ())),
        "generated_channels": sorted(generated),
        "decode_modes": list(tuple(getattr(combined, "decode_modes", ()) or ())),
        "notes": synthesis_notes,
        "texture_flip_vertical": bool(getattr(combined, "texture_flip_vertical", False)),
        "decoded_preview_input_count": int(decoded_preview_input_count),
    }
    if base_alpha_summary:
        metadata["base_alpha_summary"] = base_alpha_summary
    metallic_summary = _decoded_linear_channel_summary(generated.get("metallic", ""))
    if metallic_summary:
        metadata["metallic_summary"] = metallic_summary
    if getattr(combined, "base_note", ""):
        metadata["base_note"] = str(combined.base_note)
    if generated.get("normal"):
        metadata["normal_strength"] = float(getattr(combined, "normal_strength", 0.0) or 0.0)
    if generated.get("height"):
        metadata["height_amount"] = float(getattr(combined, "height_amount", 0.0) or 0.0)
    return channels, metadata, tuple(sorted(generated))


def _resolved_synthesis_features(
    generated_channels: tuple[str, ...],
    raw_contract: Mapping[str, object],
    synthesis: Mapping[str, object],
) -> list[str]:
    features: list[str] = []
    if bool(synthesis.get("identity_noop", False)):
        features.append("preview_material_graph_identity")
    if tuple(raw_contract.get("layer_bindings", ()) or ()) and "base" in generated_channels:
        features.append("preview_material_graph_baked")
    if any(channel in _GENERATED_LINEAR_CHANNELS for channel in generated_channels):
        features.append("preview_support_maps_baked")
    return features


def _dotnet_submesh_material_payload(
    submesh: object,
    fallback_index: int,
    *,
    source_submesh: object | None,
    source_asset_path: str,
    package_dir: Path,
    texture_copy_cache: dict[str, str],
    resource_payloads: dict[str, dict[str, object]],
    role: str,
    cancelled: Callable[[], bool] | None,
) -> dict[str, object]:
    submesh_map = submesh if isinstance(submesh, Mapping) else {}
    texture = str(submesh_map.get("texture", "") or "").strip()
    raw_channels = _dotnet_resolved_texture_channels(source_submesh)
    raw_contract = _dotnet_material_semantic_contract(
        source_submesh,
        raw_channels,
        source_asset_path=source_asset_path,
    )
    resolved_channels, synthesis, generated = _synthesize_dotnet_material_channels(
        source_submesh,
        raw_channels,
        raw_contract,
        output_dir=package_dir / "material_synthesis" / f"submesh_{fallback_index:03d}",
        batch_index=fallback_index,
        cancelled=cancelled,
    )
    if cancelled is not None and cancelled():
        raise RunCancelled("Mesh .NET material package synthesis cancelled.")
    semantic_contract = _dotnet_material_semantic_contract(
        source_submesh,
        resolved_channels,
        source_asset_path=source_asset_path,
    )
    semantic_contract = _refine_synthesized_material_contract(
        semantic_contract,
        synthesis,
        source_asset_path=source_asset_path,
    )
    resolved_features = _resolved_synthesis_features(generated, raw_contract, synthesis)
    remaining_unsupported = list(raw_contract["unsupported_features"])
    if (
        "shader_family_layer_graph" in remaining_unsupported
        and bool(synthesis.get("succeeded", False))
        and resolved_features
    ):
        remaining_unsupported.remove("shader_family_layer_graph")
    semantic_contract["unsupported_features"] = remaining_unsupported
    semantic_contract["resolved_features"] = resolved_features
    semantic_contract["synthesis_evidence"] = {
        "compiler": "canonical_mesh_dotnet_material_compiler",
        "generated_channels": list(generated),
        "resolved_features": list(resolved_features),
        "required_graph_compiled": (
            "shader_family_layer_graph" not in remaining_unsupported
        ),
    }
    for channel in generated:
        semantic_contract["channel_authorities"][channel] = "synthesized_shared_combiner"
        semantic_contract["channel_color_spaces"][channel] = (
            "srgb" if channel in _GENERATED_COLOR_CHANNELS else "linear"
        )
    packaged_channels = _copy_dotnet_texture_channel_resources(
        resolved_channels, package_dir, texture_copy_cache
    )
    submesh_index = _safe_int(submesh_map.get("submesh_index"), fallback_index)
    resource_channels, resources = _dotnet_manifest_resource_bindings(
        resolved_channels,
        packaged_channels,
        source=source_submesh,
        source_asset_path=source_asset_path,
        submesh_index=submesh_index,
        role=role,
    )
    generated_paths = {resolved_channels[channel] for channel in generated}
    for resource in resources.values():
        if str(resource.get("source_reference", "") or "") in generated_paths:
            resource["semantic_authority"] = "synthesized_shared_combiner"
    for resource_id, resource in resources.items():
        resource_payloads.setdefault(resource_id, resource)
    components = _dotnet_material_channel_components(source_submesh)
    for channel in generated:
        if channel in _GENERATED_LINEAR_CHANNELS and channel != "normal":
            components[channel] = "r"
    parameters = _dotnet_initial_material_parameters(source_submesh, resolved_channels)
    if "base_tint_metallic" in parameters:
        parameters["base_tint_metallic"] = (
            str(semantic_contract.get("material_category", "") or "").strip().casefold()
            == "metal"
        )
    return {
        "submesh_index": submesh_index,
        "name": str(submesh_map.get("name", "") or "").strip(),
        "material_slot_index": _safe_int(submesh_map.get("material_slot_index"), fallback_index),
        "material": str(submesh_map.get("material", "") or "").strip(),
        "texture": texture,
        "channels": _dotnet_texture_channels(texture),
        "raw_resolved_channels": raw_channels,
        "resolved_channels": resolved_channels,
        "packaged_channels": packaged_channels,
        "resource_channels": resource_channels,
        "texture_flip_vertical": (
            bool(synthesis.get("texture_flip_vertical", False))
            if generated
            else bool(getattr(source_submesh, "preview_texture_flip_vertical", False))
        ),
        "normal_y_policy": (
            "preserve" if "normal" in generated else _dotnet_material_normal_y_policy(source_submesh)
        ),
        "channel_components": components,
        **semantic_contract,
        "raw_material_contract": raw_contract,
        "material_synthesis": synthesis,
        "parameters": parameters,
        "resolved_texture_count": len([value for value in resolved_channels.values() if value]),
        "packaged_texture_count": len(packaged_channels),
    }


def _material_manifest_inputs(
    mesh: ParsedMesh,
    sidecar_payload: Mapping[str, object],
) -> tuple[list[object], list[object], tuple[object, ...]]:
    source_submeshes = tuple(
        _canonical_dotnet_material_source(submesh, index)
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
    )
    raw_slots = sidecar_payload.get("material_slots", [])
    slots = list(raw_slots) if isinstance(raw_slots, list) else []
    if not slots:
        slots = [
            {
                "index": index,
                "name": str(submesh.material or submesh.name or ""),
                "texture": str(submesh.texture or ""),
            }
            for index, submesh in enumerate(source_submeshes)
        ]
    raw_lods = sidecar_payload.get("lods", [])
    lods = list(raw_lods) if isinstance(raw_lods, list) else []
    first_lod = lods[0] if lods and isinstance(lods[0], Mapping) else {}
    raw_submeshes = first_lod.get("submeshes", []) if isinstance(first_lod, Mapping) else []
    submeshes = list(raw_submeshes) if isinstance(raw_submeshes, list) else []
    if not submeshes:
        submeshes = [
            {
                "submesh_index": _safe_int(
                    getattr(
                        submesh,
                        "submesh_index",
                        getattr(submesh, "source_submesh_index", index),
                    ),
                    index,
                ),
                "name": str(submesh.name or ""),
                "material_slot_index": _dotnet_material_slot_index(
                    submesh,
                    source_submeshes,
                    index,
                ),
                "material": str(submesh.material or ""),
                "texture": str(submesh.texture or ""),
            }
            for index, submesh in enumerate(source_submeshes)
        ]
    return slots, submeshes, source_submeshes


def _write_dotnet_material_manifest(
    path: Path,
    *,
    mesh: ParsedMesh,
    sidecar_payload: Mapping[str, object],
    material_signature: str,
    editable_submesh_count: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    payload = compile_mesh_dotnet_material_manifest(
        mesh,
        sidecar_payload=sidecar_payload,
        package_dir=path.parent,
        material_signature=material_signature,
        editable_submesh_count=editable_submesh_count,
        cancelled=cancelled,
    )
    atomic_write_text(path, json.dumps(payload, indent=2))


def compile_mesh_dotnet_material_manifest(
    mesh: ParsedMesh | object,
    *,
    sidecar_payload: Mapping[str, object] | None = None,
    package_dir: Path,
    material_signature: str,
    editable_submesh_count: int | None = None,
    role: str | None = None,
    submesh_index_offset: int = 0,
    absolute_resource_paths: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Compile the canonical initial/resident .NET material manifest."""

    sidecar_payload = dict(sidecar_payload or {})
    slots, submeshes, source_submeshes = _material_manifest_inputs(mesh, sidecar_payload)
    texture_copy_cache: dict[str, str] = {}
    resource_payloads: dict[str, dict[str, object]] = {}
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    submesh_payloads = []
    for index, submesh in enumerate(submeshes):
        submesh_row = dict(submesh) if isinstance(submesh, Mapping) else submesh
        if isinstance(submesh_row, dict) and (
            str(role or "replacement") != "replacement" or submesh_index_offset
        ):
            submesh_row["submesh_index"] = max(0, int(submesh_index_offset)) + index
        effective_role = (
            str(role or "")
            if role is not None
            else (
                "original_reference"
                if editable_submesh_count is not None and index >= int(editable_submesh_count)
                else "replacement"
            )
        )
        submesh_payloads.append(
            _dotnet_submesh_material_payload(
                submesh_row,
                index,
                source_submesh=(source_submeshes[index] if index < len(source_submeshes) else None),
                source_asset_path=source_asset_path,
                package_dir=package_dir,
                texture_copy_cache=texture_copy_cache,
                resource_payloads=resource_payloads,
                role=effective_role,
                cancelled=cancelled,
            )
        )
    if absolute_resource_paths:
        for resource in resource_payloads.values():
            resource_path = Path(str(resource.get("path", "") or ""))
            if resource_path and not resource_path.is_absolute():
                resource["path"] = str((package_dir / resource_path).resolve())
    return {
        "format": "cdmw_mesh_dotnet_materials_v1",
        "renderer_authority": "dotnet_mesh_editor",
        "source": "mesh.cdmeta.json",
        "texture_channels": [
            "base",
            "normal",
            "specular",
            "roughness",
            "metallic",
            "emissive",
            "height",
            "material",
            "occlusion",
        ],
        "material_slots": [
            _dotnet_material_slot_payload(slot, index) for index, slot in enumerate(slots)
        ],
        "resources": [resource_payloads[key] for key in sorted(resource_payloads)],
        "submeshes": submesh_payloads,
        "fallbacks": {"base": "neutral_checker", "normal": "flat_normal", "emissive": "black"},
        "source_mesh": str(getattr(mesh, "path", "") or ""),
        "material_signature": str(material_signature or ""),
    }


__all__ = [
    "_copy_dotnet_texture_channel_resources",
    "_dotnet_texture_channels",
    "_write_dotnet_material_manifest",
    "compile_mesh_dotnet_material_manifest",
]
