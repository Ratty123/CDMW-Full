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
        if (
            semantic in _SYNTHESIS_INPUT_SEMANTICS
            or packed
            or layer_role
            or layer_channel
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


def _source_has_usable_tangents(source: object | None) -> bool:
    if source is None:
        return False
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
    if not generated:
        shutil.rmtree(output_dir, ignore_errors=True)
    channels = dict(raw_channels)
    channels.update(generated)
    metadata: dict[str, object] = {
        "attempted": True,
        "succeeded": bool(generated),
        "outputs": list(tuple(getattr(combined, "outputs", ()) or ())),
        "generated_channels": sorted(generated),
        "decode_modes": list(tuple(getattr(combined, "decode_modes", ()) or ())),
        "notes": list(tuple(getattr(combined, "notes", ()) or ())),
        "texture_flip_vertical": bool(getattr(combined, "texture_flip_vertical", False)),
        "decoded_preview_input_count": int(decoded_preview_input_count),
    }
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
) -> list[str]:
    if not generated_channels:
        return []
    features: list[str] = []
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
    semantic_contract["unsupported_features"] = list(raw_contract["unsupported_features"])
    semantic_contract["resolved_features"] = _resolved_synthesis_features(generated, raw_contract)
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
        "parameters": _dotnet_initial_material_parameters(source_submesh, resolved_channels),
        "resolved_texture_count": len([value for value in resolved_channels.values() if value]),
        "packaged_texture_count": len(packaged_channels),
    }


def _material_manifest_inputs(
    mesh: ParsedMesh,
    sidecar_payload: Mapping[str, object],
) -> tuple[list[object], list[object], tuple[object, ...]]:
    source_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
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
                "submesh_index": index,
                "name": str(submesh.name or ""),
                "material_slot_index": index,
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
    slots, submeshes, source_submeshes = _material_manifest_inputs(mesh, sidecar_payload)
    texture_copy_cache: dict[str, str] = {}
    resource_payloads: dict[str, dict[str, object]] = {}
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    submesh_payloads = []
    for index, submesh in enumerate(submeshes):
        submesh_payloads.append(
            _dotnet_submesh_material_payload(
                submesh,
                index,
                source_submesh=(source_submeshes[index] if index < len(source_submeshes) else None),
                source_asset_path=source_asset_path,
                package_dir=path.parent,
                texture_copy_cache=texture_copy_cache,
                resource_payloads=resource_payloads,
                role=(
                    "original_reference"
                    if editable_submesh_count is not None and index >= int(editable_submesh_count)
                    else "replacement"
                ),
                cancelled=cancelled,
            )
        )
    payload = {
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
    atomic_write_text(path, json.dumps(payload, indent=2))


__all__ = [
    "_copy_dotnet_texture_channel_resources",
    "_dotnet_texture_channels",
    "_write_dotnet_material_manifest",
]
