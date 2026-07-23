"""Direct schema-8 Preview Core package adapter for the resident .NET renderer."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.atomic_file_service import atomic_write_text


NATIVE_DOTNET_ADAPTER_SCHEMA = 1
NATIVE_DOTNET_ADAPTER_MARKER = "cdmw_native_dotnet_adapter_v1.json"
SUPPORTED_NATIVE_PREVIEW_SCHEMA = 8
_BYTES_PER_VERTEX = 23 * 4
_MAXIMUM_VERTICES = 8_000_000
_TEXTURE_CHANNELS = (
    "base",
    "normal",
    "specular",
    "roughness",
    "metallic",
    "emissive",
    "height",
    "material",
    "occlusion",
    "opacity",
)
_LAYER_ONLY_ROLES = {"damage", "decal", "detail", "dye", "grime", "layer", "overlay"}
_LOGGER = logging.getLogger(__name__)


class NativeDotNetPreviewUnsupported(ValueError):
    """Raised when a native manifest needs the compatibility converter."""


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RunCancelled("Native .NET preview adaptation cancelled.")


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _contained_file(root: Path, raw_path: object, *, label: str) -> Path:
    text = str(raw_path or "").strip().replace("/", os.sep)
    if not text or Path(text).is_absolute():
        raise ValueError(f"Native preview {label} path must be package-relative.")
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / text).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Native preview {label} path escapes its package: {text}") from exc
    if not candidate.is_file():
        raise ValueError(f"Native preview {label} path is missing: {text}")
    return candidate


def _texture_file(root: Path, raw_path: object) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("Native preview DDS resource path is empty.")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = _contained_file(root, text, label="DDS resource")
    else:
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise ValueError(f"Native preview DDS resource is missing: {candidate}")
    if candidate.suffix.casefold() != ".dds":
        raise ValueError(f"Native preview texture resource is not DDS: {candidate}")
    return candidate


def _manifest_payload(root: Path) -> tuple[dict[str, object], bytes, str]:
    manifest_path = root / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Preview-core package manifest is missing or invalid.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Native preview manifest root must be an object.")
    schema = _safe_int(payload.get("schema_version"), -1)
    if schema != SUPPORTED_NATIVE_PREVIEW_SCHEMA:
        raise NativeDotNetPreviewUnsupported(
            f"Native preview manifest schema {schema} is unsupported; expected {SUPPORTED_NATIVE_PREVIEW_SCHEMA}."
        )
    return dict(payload), manifest_bytes, hashlib.sha256(manifest_bytes).hexdigest()


def _validated_batches(root: Path, manifest: Mapping[str, object]) -> list[dict[str, object]]:
    raw_batches = manifest.get("batches")
    if not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes, bytearray)):
        raise ValueError("Native preview manifest has no batches array.")
    batches: list[dict[str, object]] = []
    total_vertices = 0
    for position, raw_batch in enumerate(raw_batches):
        if not isinstance(raw_batch, Mapping):
            continue
        batch = dict(raw_batch)
        index = _safe_int(batch.get("index"), position)
        vertex_count = _safe_int(batch.get("vertex_count"), 0)
        if vertex_count <= 0 or vertex_count % 3:
            raise ValueError(f"Native preview batch {index} has an invalid triangle vertex count.")
        total_vertices += vertex_count
        if total_vertices > _MAXIMUM_VERTICES:
            raise ValueError(f"Native preview package exceeds the {_MAXIMUM_VERTICES:,}-vertex safety limit.")
        geometry = _contained_file(root, batch.get("vertex_file"), label=f"batch {index} geometry")
        expected = vertex_count * _BYTES_PER_VERTEX
        if geometry.stat().st_size != expected:
            raise ValueError(
                f"Native preview batch {index} geometry length is invalid; expected {expected:,} bytes."
            )
        batches.append(batch)
    if not batches:
        raise ValueError("Native preview package did not contain renderable batches.")
    return batches


def _compact(value: object) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _channel(value: object) -> str:
    return {
        "base": "base", "basecolor": "base", "albedo": "base", "color": "base", "diffuse": "base",
        "normal": "normal", "normalmap": "normal",
        "material": "material", "materialmask": "material", "packedmaterial": "material",
        "packedmaterialmask": "material", "specular": "specular", "specularresponse": "specular",
        "roughness": "roughness", "glossiness": "roughness", "metallic": "metallic",
        "metalness": "metallic", "occlusion": "occlusion", "ambientocclusion": "occlusion",
        "ao": "occlusion", "height": "height", "displacement": "height", "emissive": "emissive",
        "emission": "emissive", "opacity": "opacity", "alpha": "opacity",
    }.get(_compact(value), "")


def _component(value: object) -> str:
    return {"r": "r", "red": "r", "g": "g", "green": "g", "b": "b", "blue": "b", "a": "a", "alpha": "a"}.get(
        _compact(value), ""
    )


def _packed_components(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    text = str(value or "").replace(";", ",")
    for token in text.replace("\t", " ").replace("\n", " ").replace(" ", ",").split(","):
        separator = "=" if "=" in token else ":" if ":" in token else ""
        if not separator:
            continue
        left, right = token.split(separator, 1)
        left_component = _component(left)
        right_component = _component(right)
        semantic = _channel(right) if left_component else _channel(left)
        component = left_component or right_component
        if semantic and component:
            result[semantic] = component
    return result


def _descriptor_enabled(descriptor: Mapping[str, object]) -> bool:
    return bool(descriptor.get("available", True)) and bool(descriptor.get("direct_upload_candidate", True))


def _validate_declared_dds_resources(root: Path, batches: Sequence[Mapping[str, object]]) -> None:
    for batch in batches:
        raw_textures = batch.get("dds_textures")
        if not isinstance(raw_textures, Mapping):
            continue
        descriptors: list[object] = [
            value for key, value in raw_textures.items() if key != "material_inputs"
        ]
        raw_inputs = raw_textures.get("material_inputs")
        if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)):
            descriptors.extend(raw_inputs)
        for descriptor in descriptors:
            if (
                isinstance(descriptor, Mapping)
                and bool(descriptor.get("available", True))
                and str(descriptor.get("source_path", "") or "").strip()
            ):
                _texture_file(root, descriptor.get("source_path"))


def _resolve_channels(root: Path, batch: Mapping[str, object]) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    channels: dict[str, str] = {}
    components: dict[str, str] = {}
    color_spaces: dict[str, str] = {}
    authorities: dict[str, str] = {}
    raw_textures = batch.get("dds_textures")
    textures = raw_textures if isinstance(raw_textures, Mapping) else {}

    def add(raw_slot: object, raw_descriptor: object, *, overwrite: bool) -> None:
        if not isinstance(raw_descriptor, Mapping) or not _descriptor_enabled(raw_descriptor):
            return
        semantic = _channel(raw_slot)
        if not semantic or (not overwrite and semantic in channels):
            return
        path = _texture_file(root, raw_descriptor.get("source_path"))
        channels[semantic] = str(path)
        srgb = str(raw_descriptor.get("srgb_mode", "") or "").casefold()
        color_spaces[semantic] = "srgb" if "srgb" in srgb or (not srgb and semantic in {"base", "emissive"}) else "linear"
        authorities[semantic] = str(
            raw_descriptor.get("source_authority", raw_descriptor.get("binding_authority", "native_preview_core"))
            or "native_preview_core"
        )
        packed = _packed_components(raw_descriptor.get("packed_channels"))
        components.update(packed)
        if semantic == "material":
            for packed_semantic in ("specular", "roughness", "metallic", "occlusion"):
                if packed_semantic in packed and (overwrite or packed_semantic not in channels):
                    channels[packed_semantic] = str(path)
                    color_spaces[packed_semantic] = "linear"
                    authorities[packed_semantic] = authorities[semantic]

    for raw_slot, descriptor in textures.items():
        if raw_slot != "material_inputs":
            add(raw_slot, descriptor, overwrite=True)
    raw_inputs = textures.get("material_inputs")
    if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)):
        for descriptor in raw_inputs:
            if not isinstance(descriptor, Mapping) or str(descriptor.get("layer_role", "")).casefold() in _LAYER_ONLY_ROLES:
                continue
            add(descriptor.get("slot", descriptor.get("semantic_type")), descriptor, overwrite=False)
    return channels, components, color_spaces, authorities


def _resource_id(path: str) -> tuple[str, str]:
    stat = Path(path).stat()
    fingerprint = hashlib.sha256(
        f"{Path(path).resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return f"texture:{fingerprint}", f"stat:{fingerprint}"


def _shader_family(value: object) -> str:
    compact = _compact(value)
    if "skinnedmeshskin" in compact or ("skin" in compact and "skinnedmesh" not in compact):
        return "skin"
    if any(token in compact for token in ("hair", "fur")):
        return "hair"
    if "cloth" in compact:
        return "cloth_v2" if "v2" in compact or "ver2" in compact else "cloth"
    if "emissive" in compact:
        return "emissive_v2" if "v2" in compact or "ver2" in compact else "emissive"
    if any(token in compact for token in ("water", "sea")):
        return "environment_water"
    if "static" in compact and any(token in compact for token in ("multi", "rgbtexture")):
        return "static_multitextured"
    if "static" in compact:
        return "static_standard"
    if "standard" in compact:
        return "standard_v2" if "v2" in compact or "ver2" in compact else "standard"
    return str(value or "generic").strip().casefold().replace(" ", "_") or "generic"


def _alpha_mode(value: object) -> str:
    return {"mask": "cutout", "alpha_cutout": "cutout", "coverage": "cutout", "cutout": "cutout", "transparent": "blend", "alpha": "blend", "blend": "blend"}.get(
        str(value or "").strip().casefold(), "opaque"
    )


def _material_parameters(batch: Mapping[str, object], channels: Mapping[str, str]) -> dict[str, object]:
    color = batch.get("base_color")
    if not isinstance(color, Sequence) or isinstance(color, (str, bytes, bytearray)) or len(color) < 3:
        color = (0.65, 0.65, 0.65)
    category = str(batch.get("material_category", "unknown") or "unknown")
    result: dict[str, object] = {
        "base_tint_color": [_safe_float(value, 0.65) for value in color[:3]],
        "base_tint_strength": max(0.0, min(1.0, _safe_float(batch.get("base_tint_strength"), 0.0))),
        "base_tint_metallic": category.casefold() == "metal",
        "material_role": category,
    }
    roughness = max(0.0, min(1.0, _safe_float(batch.get("roughness"), 0.5)))
    metalness = max(0.0, min(1.0, _safe_float(batch.get("metalness"), 0.0)))
    result["roughness_scale" if "roughness" in channels else "roughness"] = roughness
    result["metalness_scale" if "metallic" in channels else "metalness"] = metalness
    if "emissive" in channels or _safe_float(batch.get("emissive_intensity"), 0.0) > 0.0:
        result["emissive_intensity"] = max(0.0, min(32.0, _safe_float(batch.get("emissive_intensity"), 1.0)))
    return result


def _declared_texture_paths(root: Path, batches: Sequence[Mapping[str, object]]) -> set[str]:
    declared: set[str] = set()
    for batch in batches:
        channels, _components, _spaces, _authorities = _resolve_channels(root, batch)
        declared.update(str(Path(path).resolve()).casefold() for path in channels.values())
    return declared


def validate_native_dotnet_preview_package(package_dir: Path | str) -> tuple[bool, tuple[str, ...]]:
    root = Path(package_dir).expanduser().resolve()
    errors: list[str] = []
    try:
        manifest, _manifest_bytes, manifest_signature = _manifest_payload(root)
        batches = _validated_batches(root, manifest)
        _validate_declared_dds_resources(root, batches)
    except (OSError, TypeError, ValueError) as exc:
        return False, (str(exc),)
    payloads: dict[str, Mapping[str, object]] = {}
    for name in ("net_materials.json", "dotnet_scene.json", "mesh.cdmeta.json", NATIVE_DOTNET_ADAPTER_MARKER):
        try:
            payload = json.loads((root / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            errors.append(f"invalid {name}:{exc}")
            continue
        if not isinstance(payload, Mapping):
            errors.append(f"invalid {name}:not an object")
            continue
        payloads[name] = payload
    marker = payloads.get(NATIVE_DOTNET_ADAPTER_MARKER, {})
    if _safe_int(marker.get("schema"), 0) != NATIVE_DOTNET_ADAPTER_SCHEMA:
        errors.append("stale native adapter schema")
    if str(marker.get("manifest_signature", "") or "") != manifest_signature:
        errors.append("stale native adapter manifest signature")
    sidecar_signatures = marker.get("sidecar_signatures")
    if not isinstance(sidecar_signatures, Mapping):
        errors.append("missing native adapter sidecar signatures")
    else:
        for name in ("net_materials.json", "dotnet_scene.json", "mesh.cdmeta.json"):
            try:
                signature = hashlib.sha256((root / name).read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"invalid {name}:{exc}")
                continue
            if str(sidecar_signatures.get(name, "") or "") != signature:
                errors.append(f"stale native adapter sidecar signature:{name}")
    materials = payloads.get("net_materials.json", {})
    if materials.get("renderer_authority") != "dotnet_mesh_editor":
        errors.append("invalid net_materials renderer authority")
    scene = payloads.get("dotnet_scene.json", {})
    if scene.get("renderer_authority") != "dotnet_vortice_resident_scene":
        errors.append("invalid dotnet_scene renderer authority")
    try:
        declared = _declared_texture_paths(root, batches)
    except (OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))
        declared = set()
    raw_resources = materials.get("resources", ())
    if not isinstance(raw_resources, Sequence) or isinstance(raw_resources, (str, bytes, bytearray)):
        errors.append("invalid net_materials resources")
    else:
        for index, resource in enumerate(raw_resources):
            if not isinstance(resource, Mapping):
                errors.append(f"invalid material resource:{index}")
                continue
            path = Path(str(resource.get("path", "") or "")).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if not resolved.is_file() or str(resolved).casefold() not in declared:
                errors.append(f"undeclared or missing DDS material resource:{index}")
    return not errors, tuple(errors)


def native_dotnet_preview_adapter_is_current(package_dir: Path | str) -> bool:
    return validate_native_dotnet_preview_package(package_dir)[0]


def adapt_native_dotnet_preview_package(
    package_dir: Path | str,
    *,
    source_identity: str,
    preview_overlays: Mapping[str, object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Validate base geometry and atomically rebuild only .NET adapter sidecars."""

    started = time.perf_counter()
    root = Path(package_dir).expanduser().resolve()
    manifest, _manifest_bytes, manifest_signature = _manifest_payload(root)
    batches = _validated_batches(root, manifest)
    _validate_declared_dds_resources(root, batches)
    resources: dict[str, dict[str, object]] = {}
    slots: list[dict[str, object]] = []
    submeshes: list[dict[str, object]] = []
    part_identities: list[dict[str, object]] = []
    total_vertices = 0
    for position, batch in enumerate(batches):
        _check_cancelled(cancelled)
        index = _safe_int(batch.get("index"), position)
        total_vertices += _safe_int(batch.get("vertex_count"), 0)
        material = str(batch.get("material_name", f"material_{index:03d}") or f"material_{index:03d}")
        channels, components, color_spaces, authorities = _resolve_channels(root, batch)
        resource_channels: dict[str, str] = {}
        for semantic, path in sorted(channels.items()):
            resource_id, fingerprint = _resource_id(path)
            resource_channels[semantic] = resource_id
            resources.setdefault(
                resource_id,
                {
                    "resource_id": resource_id,
                    "path": path,
                    "source_reference": path,
                    "fingerprint": fingerprint,
                    "role": "replacement",
                    "submesh_index": index,
                    "material_channel": semantic,
                    "semantic": semantic,
                    "color_space": color_spaces.get(semantic, "linear"),
                    "semantic_authority": authorities.get(semantic, "native_preview_core"),
                    "profile": "legacy_unknown",
                    "required": False,
                    "criticality": "optional",
                    "fallback_policy": {"base": "neutral_checker", "normal": "flat_normal", "emissive": "black"}.get(
                        semantic, "diagnostic_only"
                    ),
                },
            )
        slots.append({"index": index, "name": material, "texture": channels.get("base", ""), "channels": channels})
        raw_shader = str(batch.get("shader_family", "generic") or "generic")
        shader = _shader_family(raw_shader)
        alpha = _alpha_mode(batch.get("alpha_mode"))
        raw_inputs = (batch.get("dds_textures") or {}).get("material_inputs", ()) if isinstance(batch.get("dds_textures"), Mapping) else ()
        layer_bindings = [dict(value) for value in raw_inputs if isinstance(value, Mapping)] if isinstance(raw_inputs, Sequence) else []
        unsupported: list[str] = []
        if alpha == "blend":
            unsupported.append("per_triangle_alpha_blend_sorting")
        if shader in {"hair", "fur"}:
            unsupported.append("hair_fur_anisotropy_and_flow")
        if shader in {"skin", "skin_wrinkle"}:
            unsupported.append("skin_subsurface_and_wrinkle_response")
        submeshes.append(
            {
                "submesh_index": index,
                "material_slot_index": index,
                "material": material,
                "texture": channels.get("base", ""),
                "resolved_channels": channels,
                "packaged_channels": {},
                "resource_channels": resource_channels,
                "channel_components": components,
                "channel_color_spaces": color_spaces,
                "channel_authorities": authorities,
                "normal_y_policy": str(batch.get("normal_y_policy", "shader_invert_legacy_compat") or "shader_invert_legacy_compat"),
                "texture_flip_vertical": bool(batch.get("texture_flip_vertical", False)),
                "shader_family": shader,
                "shader_technique": raw_shader,
                "shader_authority": "guess" if shader == "generic" else "sidecar",
                "shader_family_source": "declared_shader_family",
                "material_category": str(batch.get("material_category", "unknown") or "unknown"),
                "material_category_confidence": _safe_float(batch.get("material_category_confidence"), 0.35),
                "alpha_mode": alpha,
                "alpha_cutoff": _safe_float(batch.get("alpha_threshold"), 0.5),
                "opacity_factor": 1.0,
                "alpha_authority": "native_preview_core",
                "double_sided": bool(batch.get("two_sided", False)),
                "double_sided_authority": "native_preview_core",
                "unsupported_features": unsupported,
                "layer_bindings": layer_bindings,
                "material_layers": [],
                "material_layer_compiler": "none",
                "parameters": _material_parameters(batch, channels),
            }
        )
        identity = batch.get("editor_identity") if isinstance(batch.get("editor_identity"), Mapping) else {}
        part_identities.append(
            {
                "scene_submesh_index": index,
                "source_submesh_index": _safe_int(identity.get("source_submesh_index"), index),
                "source_local_submesh_index": _safe_int(identity.get("source_local_submesh_index"), index),
                "source_component_index": _safe_int(identity.get("source_component_index"), 0),
                "source_component_label": str(identity.get("source_component_label", "") or ""),
                "prefab_component": bool(identity.get("prefab_component", False)),
                "role": "archive_model",
                "name": f"batch_{index:03d}",
                "material": material,
                "source_asset_path": str(manifest.get("source_path", "") or ""),
            }
        )

    signature = hashlib.sha256(
        f"{manifest_signature}:cdmw_native_dotnet_adapter:{NATIVE_DOTNET_ADAPTER_SCHEMA}".encode("utf-8")
    ).hexdigest()
    materials = {
        "format": "cdmw_mesh_dotnet_materials_v1",
        "renderer_authority": "dotnet_mesh_editor",
        "source": "manifest.json",
        "adapter": "cdmw_native_dotnet_adapter_v1",
        "texture_channels": list(_TEXTURE_CHANNELS),
        "material_signature": signature,
        "material_slots": slots,
        "resources": [resources[key] for key in sorted(resources)],
        "submeshes": submeshes,
        "fallbacks": {"base": "neutral_checker", "normal": "flat_normal", "emissive": "black"},
        "source_mesh": str(manifest.get("source_path", "") or ""),
    }
    scene: dict[str, object] = {
        "format": "cdmw_static_mesh_scene_v2",
        "protocol_version": 2,
        "renderer_authority": "dotnet_vortice_resident_scene",
        "session_id": "archive_preview",
        "source_identity": str(source_identity or manifest.get("source_path", "") or manifest_signature),
        "scene_generation": 1,
        "editable_submesh_count": len(submeshes),
        "reference_submesh_count": 0,
        "roles": {"replacement": [item["submesh_index"] for item in submeshes], "original_reference": []},
        "part_identities": part_identities,
        "interaction_mode": "placement",
        "comparison_mode": "replacement_only",
        "grid": {"visible": False, "origin": [0.0, -1.0, 0.0], "spacing": 0.25},
        "gizmo": {"visible": False, "tool": "move"},
        "bounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
        "archive_preview": {
            "source_path": str(manifest.get("source_path", "") or ""),
            "textures_enabled": bool(resources),
        },
    }
    if isinstance(preview_overlays, Mapping):
        if isinstance(preview_overlays.get("skeleton"), Mapping):
            scene["skeleton_overlay"] = dict(preview_overlays["skeleton"])
        if isinstance(preview_overlays.get("cloth"), Mapping):
            scene["cloth_overlay"] = dict(preview_overlays["cloth"])
    metadata = {
        "schema": "cdmw_native_preview_metadata_v1",
        "source_identity": str(source_identity or ""),
        "native_manifest": "manifest.json",
        "read_only": True,
    }
    elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    sidecars = {
        "net_materials.json": json.dumps(materials, indent=2, sort_keys=True),
        "dotnet_scene.json": json.dumps(scene, indent=2, sort_keys=True),
        "mesh.cdmeta.json": json.dumps(metadata, indent=2, sort_keys=True),
    }
    marker = {
        "schema": NATIVE_DOTNET_ADAPTER_SCHEMA,
        "manifest_signature": manifest_signature,
        "sidecar_signatures": {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in sidecars.items()
        },
        "source_identity": str(source_identity or ""),
        "textures_enabled": bool(resources),
        "resource_count": len(resources),
        "batch_count": len(submeshes),
        "vertex_count": total_vertices,
        "adapter_ms": round(elapsed_ms, 3),
    }
    _check_cancelled(cancelled)
    root.mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(exist_ok=True)
    for name, text in sidecars.items():
        atomic_write_text(root / name, text)
    atomic_write_text(
        root / NATIVE_DOTNET_ADAPTER_MARKER,
        json.dumps(marker, indent=2, sort_keys=True),
    )
    valid, errors = validate_native_dotnet_preview_package(root)
    if not valid:
        raise ValueError("Native .NET preview adapter validation failed: " + "; ".join(errors))
    _LOGGER.info(
        "native_dotnet_preview_adapter source=%s batches=%d vertices=%d resources=%d elapsed_ms=%.3f",
        root,
        len(submeshes),
        total_vertices,
        len(resources),
        elapsed_ms,
    )
    return marker


__all__ = [
    "NATIVE_DOTNET_ADAPTER_MARKER",
    "NATIVE_DOTNET_ADAPTER_SCHEMA",
    "NativeDotNetPreviewUnsupported",
    "adapt_native_dotnet_preview_package",
    "native_dotnet_preview_adapter_is_current",
    "validate_native_dotnet_preview_package",
]
