"""Material channel inference for resident .NET material snapshots."""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from cdmw.core.dds_native import inspect_dds_native_path
from cdmw.domain.mesh.material_resource_policy import canonical_material_channel
from cdmw.domain.mesh.normal_y_policy import resolve_preview_normal_y_policy
from cdmw.modding.asset_replacement import infer_cd_texture_role_from_path
from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding
from cdmw.rendering.preview_tint_contract import resolve_preview_tint_contract


_COMPONENT_NAMES = ("r", "g", "b", "a")
_DEFAULT_INSPECT_DDS_NATIVE_PATH = inspect_dds_native_path

# A base texture this dark carries no usable colour: the part renders as a
# silhouette and the sidecar's declared tint is the only colour information
# available for it.  Measured against the shipped corpus, only a handful of
# submeshes fall here, so promoting the tint stays a narrow rescue rather than a
# blanket recolour -- applying it everywhere washes out material that is already
# correct, and paints per-layer dyes across whole submeshes.
_BASE_TINT_RESCUE_MAX_BASE_LUMA = 0.07
# ... and only when the tint is clearly brighter than what the texture gives, so
# a dark tint is not swapped in for an equally dark texture.  Measured gains on
# the shipped corpus separate cleanly: the parts this rescues sit at 3.4 and 4.5,
# while a dark green cannon tint sits at 3.0 and only tinted the barrel without
# making it readable.  The threshold sits between them.
_BASE_TINT_RESCUE_MIN_GAIN = 3.15


def _rescued_base_tint_strength(
    strength: float,
    base_color: Sequence[float],
    resolved_channels: Mapping[str, str],
) -> float:
    """Promote a declared tint only for parts whose base texture is unusable.

    ``base_tint_strength`` is otherwise derived from whether a separate texture
    tint exists, so a part can declare a colour that is then discarded.  Turning
    every one of those back on is a regression: the shader's tint path also lifts
    luminance, and the declared colours are per-layer dyes, so applying them to a
    whole submesh washes out correct material and mis-colours the rest.  This
    only rescues parts that would otherwise render as a black silhouette.
    """

    if strength > 0.001 or len(base_color) < 3:
        return strength
    base_path = next(
        (
            str(resolved_channels.get(channel, "") or "")
            for channel in ("base", "albedo", "diffuse")
            if str(resolved_channels.get(channel, "") or "")
        ),
        "",
    )
    if not base_path:
        return strength
    base_luma = _mean_texture_luma(base_path)
    if base_luma is None or base_luma > _BASE_TINT_RESCUE_MAX_BASE_LUMA:
        return strength
    tint_luma = (
        (0.2126 * float(base_color[0]))
        + (0.7152 * float(base_color[1]))
        + (0.0722 * float(base_color[2]))
    )
    if tint_luma < max(base_luma * _BASE_TINT_RESCUE_MIN_GAIN, 0.05):
        return strength
    return 0.85


@lru_cache(maxsize=512)
def _mean_texture_luma(path: str) -> float | None:
    """Mean luminance of a preview texture, or ``None`` if unreadable."""

    candidate = Path(str(path or "")).expanduser()
    if not candidate.is_file():
        return None
    try:
        from PySide6.QtGui import QImage

        image = QImage(str(candidate))
        if image.isNull():
            return None
        # A small sample is enough to decide whether a texture is black.
        thumbnail = image.scaled(32, 32).convertToFormat(QImage.Format.Format_RGB888)
        if thumbnail.isNull():
            return None
        total = 0.0
        count = 0
        for y in range(thumbnail.height()):
            for x in range(thumbnail.width()):
                colour = thumbnail.pixelColor(x, y)
                total += (
                    (0.2126 * colour.redF())
                    + (0.7152 * colour.greenF())
                    + (0.0722 * colour.blueF())
                )
                count += 1
        return (total / count) if count else None
    except Exception:
        return None

# Crimson Desert packs its material parameters into one RGB texture, referenced
# from the sidecar as ``_grimeMaterialTexture*`` / ``_detailMaterialMask*`` and
# stored on disk with an ``_sp`` suffix.  The suffix reads like "specular", but
# these are metal/roughness workflow maps: measured across the shipped ``_sp``
# corpus, red is occlusion (a flat 1.0 unless occlusion was authored, as on
# faces), green is roughness, and blue is a near-binary metal mask whose set
# regions pair with low roughness and bright desaturated albedo.  Treating blue
# as a specular level instead would be wrong -- 0.0 is not a legal dielectric
# reflectance, but it is the correct "not metal" value.
_CRIMSON_PACKED_MATERIAL_COMPONENTS = {
    "occlusion": "r",
    "roughness": "g",
    "metallic": "b",
}
# Only ``_sp`` carries these parameters.  ``_ma`` (``material_mask``), ``_mg``
# (``material_response``) and ``_m`` (``mask``) are layer selectors whose
# channels sum to roughly one across the image, so reading them as roughness and
# metal would feed the renderer layer weights instead of surface response.
_CRIMSON_PACKED_MATERIAL_SUBTYPES = frozenset({"specular"})


def _dotnet_dds_inspector():
    """Honor historical facade patch points while owning channel behavior here."""

    facade = sys.modules.get("cdmw.services.mesh_dotnet_material_state")
    facade_inspector = getattr(facade, "inspect_dds_native_path", None)
    if facade_inspector is not None and facade_inspector is not _DEFAULT_INSPECT_DDS_NATIVE_PATH:
        return facade_inspector
    return inspect_dds_native_path


def _dotnet_crimson_material_input_decode(
    source: object,
    item: object,
    values: Mapping[str, object],
) -> dict[str, object]:
    def field(name: str, fallback: object = "") -> object:
        return values.get(name, fallback) or getattr(item, name, fallback)

    return decode_crimson_texture_binding(
        shader_family=(
            getattr(source, "preview_sidecar_shader_family", "")
            or field("shader_family")
        ),
        parameter_name=field("parameter_name"),
        source_path=(
            field("source_dds_path")
            or field("source_texture_path")
            or field("preview_texture_path")
        ),
        slot_name=field("semantic_type") or field("slot_kind") or "material",
        semantic_subtype=field("semantic_subtype"),
        packed_channels=tuple(field("packed_channels", ()) or ()),
        layer_channel=field("layer_channel"),
        blend_flags=tuple(field("blend_flags", ()) or ()),
        sidecar_kind=field("sidecar_kind"),
        parameter_declared_by=field("parameter_declared_by"),
    )


def _dotnet_layer_mask_candidate_rank(
    *,
    semantic: str,
    semantic_subtype: str,
    parameter_name: str,
    layer_role: str,
    source_kind: str,
) -> int:
    """Rank actual selector masks without trusting the word ``Mask`` alone."""

    key = "".join(character for character in parameter_name.casefold() if character.isalnum())
    source_kind = source_kind.strip().casefold()
    semantic = semantic.strip().casefold()
    semantic_subtype = semantic_subtype.strip().casefold()
    layer_role = layer_role.strip().casefold()
    if source_kind == "crimson_color_blending_mask" and key == "colorblendingmasktexture":
        return 100
    if key == "colorblendingmasktexture":
        return 95
    if semantic == "layer_mask":
        return 85
    if key in {"layermasktexture", "layerblendmasktexture", "rgbtexture"}:
        return 80
    if source_kind == "crimson_detail_mask" or semantic == "detail_mask" or key == "detailmasktexture":
        return 65
    technical_parameter = any(
        token in key
        for token in ("diffuse", "normal", "material", "height", "displacement")
    )
    if technical_parameter:
        return -1
    if semantic == "mask" or layer_role == "mask":
        return 45
    if "mask" in semantic_subtype:
        return 35
    return -1


def _dotnet_material_input_channels(source: object | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if source is None:
        return result
    overrides = getattr(source, "preview_native_material_overrides", {}) or {}
    tint_only_base = bool(
        isinstance(overrides, Mapping) and overrides.get("base_tint_only_fallback", False)
    )
    layer_only_roles = {"damage", "decal", "detail", "dye", "grime", "layer", "overlay"}
    layer_mask_candidate = ""
    layer_mask_candidate_rank = -1
    source_owner_slot_index = getattr(
        source,
        "preview_pac_material_owner_slot_index",
        getattr(
            source,
            "material_slot_index",
            getattr(source, "source_submesh_index", getattr(source, "submesh_index", -1)),
        ),
    )
    try:
        source_owner_slot_index = int(source_owner_slot_index)
    except (TypeError, ValueError, OverflowError):
        source_owner_slot_index = -1
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        semantic_subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or ""
        ).strip().lower()
        layer_role = str(
            values.get("layer_role", "")
            or getattr(item, "layer_role", "")
            or ""
        ).strip().lower()
        parameter_name = str(
            values.get("parameter_name", "")
            or getattr(item, "parameter_name", "")
            or ""
        ).strip().lower()
        item_owner_slot_index = values.get(
            "owner_slot_index",
            getattr(item, "owner_slot_index", -1),
        )
        try:
            item_owner_slot_index = int(item_owner_slot_index)
        except (TypeError, ValueError, OverflowError):
            item_owner_slot_index = -1
        if (
            source_owner_slot_index >= 0
            and item_owner_slot_index >= 0
            and source_owner_slot_index != item_owner_slot_index
        ):
            continue
        # Preserve the source DDS when one is available. Preview PNGs are useful
        # fallbacks, but selecting them first discards the source format, mip
        # chain, precision, and color-space view before Vortice sees the asset.
        candidates = tuple(
            str(values.get(name, "") or getattr(item, name, "") or "").strip()
            for name in (
                "source_dds_path",
                "source_texture_path",
                "source_path",
                "preview_texture_path",
            )
        )
        path = next((value for value in candidates if value and Path(value).expanduser().is_file()), "")
        if not path:
            path = next((value for value in candidates if value), "")
        semantic = {"base_color": "base", "color": "base", "metalness": "metallic"}.get(
            semantic, semantic
        )
        decode = _dotnet_crimson_material_input_decode(source, item, values)
        disposition = str(
            values.get("binding_disposition", "")
            or getattr(item, "binding_disposition", "")
            or decode.get("disposition", "")
            or ""
        ).strip().casefold()
        promoted_channels = decode.get("promoted_channels")
        candidate_rank = _dotnet_layer_mask_candidate_rank(
            semantic=semantic,
            semantic_subtype=semantic_subtype,
            parameter_name=parameter_name,
            layer_role=layer_role,
            source_kind=str(decode.get("source_kind", "") or ""),
        )
        if path and candidate_rank > layer_mask_candidate_rank:
            layer_mask_candidate = path
            layer_mask_candidate_rank = candidate_rank
        if (
            path
            and str(decode.get("disposition", "") or "") == "promoted"
            and isinstance(promoted_channels, Mapping)
        ):
            for promoted_channel in promoted_channels:
                channel = canonical_material_channel(str(promoted_channel))
                if channel:
                    result.setdefault(channel, path)
        is_layer_only = layer_role in layer_only_roles or disposition == "layer_only"
        is_base_channel = semantic in {"albedo", "base", "diffuse"}
        source_bound = bool(
            values.get("binding_authority", "")
            or getattr(item, "binding_authority", "")
            or values.get("binding_disposition", "")
            or getattr(item, "binding_disposition", "")
            or values.get("sidecar_kind", "")
            or getattr(item, "sidecar_kind", "")
        )
        globally_bindable = (
            not source_bound
            or disposition in {"promoted", "recorded"}
            or semantic in {"detail_mask", "layer_mask", "mask", "material", "material_mask"}
        )
        if (
            semantic
            and path
            and semantic not in result
            and globally_bindable
            and not is_layer_only
            and not (tint_only_base and is_base_channel)
        ):
            result[semantic] = path
    if layer_mask_candidate:
        result["layer_mask"] = layer_mask_candidate
        result.setdefault("mask", layer_mask_candidate)
    return result


def _material_texture_metadata(source: object | None) -> tuple[str, tuple[str, ...]]:
    if source is None:
        return "", ()
    subtype = str(getattr(source, "preview_material_texture_subtype", "") or "").strip().lower()
    packed = tuple(
        str(value or "").strip().lower()
        for value in tuple(getattr(source, "preview_material_texture_packed_channels", ()) or ())
        if str(value or "").strip()
    )
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        if semantic != "material":
            continue
        subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or subtype
        ).strip().lower()
        item_packed = tuple(
            str(value or "").strip().lower()
            for value in tuple(values.get("packed_channels", ()) or getattr(item, "packed_channels", ()) or ())
            if str(value or "").strip()
        )
        if item_packed:
            packed = item_packed
        break
    return subtype, packed


def _dotnet_material_channel_components(source: object | None) -> dict[str, str]:
    subtype, packed = _material_texture_metadata(source)
    normalized = tuple(value.replace("metalness", "metallic") for value in packed)
    if subtype in _CRIMSON_PACKED_MATERIAL_SUBTYPES:
        # A component index only describes the packed texture it came from.  When
        # a channel already resolves to its own dedicated map -- the shared
        # material combiner emits separate roughness/metal/occlusion images --
        # that map carries its value in red, so claiming green or blue here would
        # sample the wrong channel.  Keep the packed layout for the channels this
        # texture actually supplies.
        already_bound = _dotnet_material_input_channels(source)
        material_path = already_bound.get("material", "")
        result: dict[str, str] = {
            channel: component
            for channel, component in _CRIMSON_PACKED_MATERIAL_COMPONENTS.items()
            if already_bound.get(channel, material_path) == material_path
        }
    elif subtype in {"metallic_roughness", "metallicroughness", "gltf_metallic_roughness"}:
        result = {"roughness": "g", "metallic": "b"}
    elif subtype in {"orm", "arm"}:
        result = {"roughness": "g", "metallic": "b"}
    elif subtype == "rma":
        result = {"roughness": "r", "metallic": "g"}
    elif subtype == "mra":
        result = {"metallic": "r", "roughness": "g"}
    elif subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        result = {"roughness": "a", "specular": "rgb"}
    elif normalized[:2] == ("roughness", "metallic"):
        result = {"roughness": "g", "metallic": "b"}
    else:
        result = {}
        for index, semantic in enumerate(normalized[:4]):
            if semantic in {"roughness", "metallic", "specular"}:
                result.setdefault(semantic, _COMPONENT_NAMES[index])
    layer_mask_component = ""
    layer_mask_component_rank = -1
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        decode = _dotnet_crimson_material_input_decode(source, item, values)
        promoted_channels = decode.get("promoted_channels")
        if (
            str(decode.get("disposition", "") or "") == "promoted"
            and isinstance(promoted_channels, Mapping)
        ):
            for raw_semantic, raw_component in promoted_channels.items():
                semantic = canonical_material_channel(str(raw_semantic))
                component = str(raw_component or "").strip().casefold()
                if semantic and component in _COMPONENT_NAMES:
                    result.setdefault(semantic, component)
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or ""
        ).strip().lower()
        parameter_name = str(
            values.get("parameter_name", "")
            or getattr(item, "parameter_name", "")
            or ""
        ).strip().lower()
        rank = _dotnet_layer_mask_candidate_rank(
            semantic=semantic,
            semantic_subtype=subtype,
            parameter_name=parameter_name,
            layer_role=str(
                values.get("layer_role", "")
                or getattr(item, "layer_role", "")
                or ""
            ),
            source_kind=str(decode.get("source_kind", "") or ""),
        )
        if rank <= layer_mask_component_rank:
            continue
        component = str(
            values.get("layer_channel", "")
            or getattr(item, "layer_channel", "")
            or "r"
        ).strip().lower()
        layer_mask_component = component if component in _COMPONENT_NAMES else "r"
        layer_mask_component_rank = rank
    if layer_mask_component:
        result["layer_mask"] = layer_mask_component
    return result


def _dotnet_material_normal_y_policy(source: object | None) -> str:
    """Compatibility wrapper for the shared preview normal-space rule."""

    return resolve_preview_normal_y_policy(source)


def _material_parameter_value(source: object | None, parameter_name: str) -> object | None:
    wanted = parameter_name.strip().casefold()
    for item in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        name = str(values.get("parameter_name", "") or getattr(item, "parameter_name", "") or "").strip().casefold()
        if name != wanted:
            continue
        color = tuple(values.get("color_value", ()) or getattr(item, "color_value", ()) or ())
        if len(color) >= 3:
            return tuple(color[:3])
        numeric = values.get("numeric_value", getattr(item, "numeric_value", None))
        if numeric is not None:
            return numeric
        return values.get("value", getattr(item, "value", None))
    return None


def _finite_float(value: object, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(minimum, min(maximum, number)) if math.isfinite(number) else None


def _color3(value: object) -> tuple[float, float, float] | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#"):
            text = text[1:]
        if len(text) not in {6, 8}:
            return None
        try:
            return tuple(int(text[offset : offset + 2], 16) / 255.0 for offset in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 3:
        return None
    components = tuple(_finite_float(component, minimum=0.0, maximum=2.0) for component in value[:3])
    return components if all(component is not None for component in components) else None  # type: ignore[return-value]


@lru_cache(maxsize=512)
def _dotnet_emissive_texture_is_scalar_mask_cached(
    path_text: str,
    file_size: int,
    modified_ns: int,
) -> bool:
    del file_size, modified_ns
    try:
        info = _dotnet_dds_inspector()(path_text)
    except (OSError, ValueError):
        return False
    return bool(
        info is not None
        and (
            str(getattr(info, "compressed_family", "") or "").strip().casefold() == "bc4"
            or str(getattr(info, "format_name", "") or "").strip().casefold().startswith("bc4")
        )
    )


def _dotnet_emissive_texture_is_scalar_mask(path_text: str) -> bool:
    path_text = str(path_text or "").strip()
    if not path_text or Path(path_text).suffix.casefold() != ".dds":
        return False
    try:
        source = Path(path_text).resolve()
        stat = source.stat()
    except OSError:
        return False
    return _dotnet_emissive_texture_is_scalar_mask_cached(
        str(source),
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
    )


def _dotnet_initial_material_parameters(
    source: object | None,
    resolved_channels: Mapping[str, str],
) -> dict[str, object]:
    if source is None:
        return {}
    result: dict[str, object] = {}
    subtype, _packed = _material_texture_metadata(source)
    is_gltf = subtype in {
        "metallic_roughness",
        "metallicroughness",
        "gltf_metallic_roughness",
        "specular_glossiness",
        "specularglossiness",
        "gltf_specular_glossiness",
    } or any(
        str(
            (item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}).get(
                "parameter_name", getattr(item, "parameter_name", "")
            )
            or ""
        ).startswith("_gltf")
        for item in tuple(getattr(source, "preview_material_parameters", ()) or ())
    )
    overrides = getattr(source, "preview_native_material_overrides", {})
    overrides = overrides if isinstance(overrides, Mapping) else {}
    native_hints_value = overrides.get("native_material_hints")
    native_hints = native_hints_value if isinstance(native_hints_value, Mapping) else None
    base_color = _color3(getattr(source, "preview_color", ()))
    tint_contract = resolve_preview_tint_contract(
        source,
        base_color=base_color or (),
        base_tint_strength=overrides.get("base_tint_strength"),
        source_path=getattr(source, "preview_source_asset_path", ""),
    )
    if len(tint_contract.base_color) >= 3:
        result["base_tint_color"] = list(tint_contract.base_color)
        result["base_tint_strength"] = _rescued_base_tint_strength(
            tint_contract.base_tint_strength,
            tint_contract.base_color,
            resolved_channels,
        )
        material_category = str(overrides.get("material_category", "") or "").strip().casefold()
        if material_category:
            result["base_tint_metallic"] = material_category == "metal"
    texture_tint = tint_contract.texture_tint
    if (
        len(texture_tint) < 3
        and is_gltf
        and base_color is not None
        and any(str(resolved_channels.get(channel, "") or "") for channel in ("base", "albedo", "diffuse"))
    ):
        # glTF baseColorFactor multiplies a sampled base texture. It is not the
        # Archive preview's luma-preserving base-tint policy.
        texture_tint = base_color
    if len(texture_tint) >= 3:
        result["texture_tint"] = list(texture_tint)
    if native_hints is not None:
        for parameter_name in ("roughness", "metalness", "specular"):
            presence_key = f"{parameter_name}_hint_present"
            hint_present = bool(
                overrides.get(
                    presence_key,
                    native_hints.get(presence_key, parameter_name in native_hints),
                )
            )
            if not hint_present:
                continue
            hint = _finite_float(
                overrides.get(parameter_name, native_hints.get(parameter_name)),
                minimum=0.0,
                maximum=1.0,
            )
            if hint is not None:
                result[f"{parameter_name}_hint"] = hint
    roughness = None if native_hints is not None else _finite_float(
        overrides.get("roughness", _material_parameter_value(source, "_roughnessFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    metallic = None if native_hints is not None else _finite_float(
        overrides.get("metalness", overrides.get("metallic", _material_parameter_value(source, "_metallicFactor"))),
        minimum=0.0,
        maximum=1.0,
    )
    if is_gltf and roughness is None and "roughness" not in resolved_channels:
        roughness = 1.0
    if is_gltf and metallic is None and "metallic" not in resolved_channels:
        metallic = 1.0
    specular = None if native_hints is not None else _finite_float(
        overrides.get("specular", _material_parameter_value(source, "_specularFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    if roughness is not None:
        result["roughness_scale" if "roughness" in resolved_channels else "roughness"] = roughness
    if metallic is not None:
        result["metalness_scale" if "metallic" in resolved_channels else "metalness"] = metallic
    if specular is not None and abs(specular - 1.0) > 1e-6:
        result["specular"] = specular
    if subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        result["roughness_inverted"] = True
    emissive_color = _color3(
        overrides.get("emissive_color", _material_parameter_value(source, "_emissiveColor"))
    )
    emissive_color_authoritative_value = overrides.get(
        "emissive_color_authoritative",
        native_hints.get("emissive_color_authoritative") if native_hints is not None else None,
    )
    emissive_color_authoritative = (
        bool(emissive_color_authoritative_value)
        if emissive_color_authoritative_value is not None
        else emissive_color is not None
    )
    emissive_intensity = _finite_float(
        overrides.get("emissive_intensity", _material_parameter_value(source, "_emissiveIntensity")),
        minimum=0.0,
        maximum=32.0,
    )
    if emissive_color is not None:
        result["emissive_color"] = list(emissive_color)
        result["emissive_color_authoritative"] = emissive_color_authoritative
    if emissive_intensity is not None:
        result["emissive_intensity"] = emissive_intensity
    emissive_path = str(resolved_channels.get("emissive", "") or "").strip()
    if emissive_path:
        result["emissive_scalar_mask"] = bool(
            overrides.get(
                "emissive_scalar_mask",
                _dotnet_emissive_texture_is_scalar_mask(emissive_path),
            )
        )
    return result


def _dotnet_resolved_texture_channels(source: object | None) -> dict[str, str]:
    if source is None:
        return {}
    texture = str(getattr(source, "texture", "") or "").strip()
    result = ({channel: texture for channel in ("base", "albedo", "diffuse")} if texture else {})
    material_input_channels = _dotnet_material_input_channels(source)
    result.update(material_input_channels)
    pairs = {
        "base": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "albedo": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "diffuse": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "normal": ("preview_normal_texture_dds_path", "preview_normal_texture_path", "preview_normal_texture_default_path"),
        "material": ("preview_material_texture_dds_path", "preview_material_texture_path", "preview_material_texture_default_path"),
        "height": ("preview_height_texture_dds_path", "preview_height_texture_path", "preview_height_texture_default_path"),
        "emissive": ("preview_emissive_texture_dds_path", "preview_emissive_texture_path", "preview_emissive_texture_default_path"),
    }
    for channel, attrs in pairs.items():
        for attr in attrs:
            value = str(getattr(source, attr, "") or "").strip()
            if value:
                result[channel] = value
                break
    # Base/albedo/diffuse are transport aliases for one color input. A resolved
    # material input (especially a source DDS) must replace every alias instead
    # of coexisting with a stale parser-level ``texture`` fallback. Otherwise
    # the manifest can load two different color resources for one material and
    # diagnostics/report ordering decides which one appears authoritative.
    preferred_color = next(
        (
            material_input_channels[channel]
            for channel in ("base", "albedo", "diffuse")
            if material_input_channels.get(channel)
        ),
        "",
    ) or next(
        (result[channel] for channel in ("base", "albedo", "diffuse") if result.get(channel)),
        "",
    )
    if preferred_color:
        for channel in ("base", "albedo", "diffuse"):
            result[channel] = preferred_color
    _remove_unpromoted_layer_color_fallbacks(source, result)
    _reroute_technical_color_fallback(source, result)
    material_path = result.get("material", "")
    if material_path:
        for channel in _dotnet_material_channel_components(source):
            result.setdefault(channel, material_path)
    return result


def _remove_unpromoted_layer_color_fallbacks(
    source: object,
    channels: dict[str, str],
) -> None:
    """Keep authoritative PAC layer inputs out of legacy base aliases.

    Archive preparation rebases source references into durable package paths.
    A parser-level ``texture`` fallback can therefore point at the same
    transport DDS as a PAC binding whose authoritative disposition is
    ``layer_only``. Such a binding must not become whole-material color unless
    another authoritative binding promotes that same resource as base color.
    """

    source_owner_slot_index = getattr(
        source,
        "preview_pac_material_owner_slot_index",
        getattr(
            source,
            "material_slot_index",
            getattr(source, "source_submesh_index", getattr(source, "submesh_index", -1)),
        ),
    )
    try:
        source_owner_slot_index = int(source_owner_slot_index)
    except (TypeError, ValueError, OverflowError):
        source_owner_slot_index = -1

    layer_only_paths: set[str] = set()
    promoted_base_paths: set[str] = set()
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        item_owner_slot_index = values.get(
            "owner_slot_index",
            getattr(item, "owner_slot_index", -1),
        )
        try:
            item_owner_slot_index = int(item_owner_slot_index)
        except (TypeError, ValueError, OverflowError):
            item_owner_slot_index = -1
        if (
            source_owner_slot_index >= 0
            and item_owner_slot_index >= 0
            and source_owner_slot_index != item_owner_slot_index
        ):
            continue

        decode = _dotnet_crimson_material_input_decode(source, item, values)
        disposition = str(
            values.get("binding_disposition", "")
            or getattr(item, "binding_disposition", "")
            or decode.get("disposition", "")
            or ""
        ).strip().casefold()
        paths = {
            str(values.get(name, "") or getattr(item, name, "") or "")
            .replace("\\", "/")
            .strip()
            .casefold()
            for name in (
                "source_dds_path",
                "source_texture_path",
                "source_path",
                "preview_texture_path",
            )
            if str(values.get(name, "") or getattr(item, name, "") or "").strip()
        }
        if not paths:
            continue
        if disposition == "layer_only":
            layer_only_paths.update(paths)
            continue
        semantic = canonical_material_channel(
            str(
                values.get("semantic_type", "")
                or values.get("slot_kind", "")
                or getattr(item, "semantic_type", "")
                or getattr(item, "slot_kind", "")
                or ""
            )
        )
        promoted_channels = {
            canonical_material_channel(str(channel))
            for channel in tuple(decode.get("promoted_channels", ()) or ())
        }
        if disposition == "promoted" and (
            semantic == "base" or "base" in promoted_channels
        ):
            promoted_base_paths.update(paths)

    forbidden_paths = layer_only_paths - promoted_base_paths
    if not forbidden_paths:
        return
    for channel in ("base", "albedo", "diffuse"):
        path = str(channels.get(channel, "") or "").replace("\\", "/").strip().casefold()
        if path in forbidden_paths:
            channels.pop(channel, None)


def _reroute_technical_color_fallback(source: object, channels: dict[str, str]) -> None:
    """Keep clearly named Crimson support maps out of the base-color slot.

    Native sidecar or source-format bindings remain authoritative. This only
    repairs legacy/fallback paths where a parser-level texture reference was
    treated as color despite an explicit Crimson role suffix such as ``_mg``.
    """

    color_paths = tuple(
        dict.fromkeys(
            str(channels.get(channel, "") or "").strip()
            for channel in ("base", "albedo", "diffuse")
            if str(channels.get(channel, "") or "").strip()
        )
    )
    for path in color_paths:
        role = infer_cd_texture_role_from_path(path)
        if role in {"", "base"} or _has_authoritative_color_input(source, path):
            continue
        for channel in ("base", "albedo", "diffuse"):
            if _same_texture_reference(channels.get(channel, ""), path):
                channels.pop(channel, None)
        if role == "normal":
            channels.setdefault("normal", path)
        elif role == "height":
            channels.setdefault("height", path)
        elif role == "emissive":
            channels.setdefault("emissive", path)
        elif role == "detail_mask":
            channels.setdefault("layer_mask", path)
        elif role == "material_mask":
            channels.setdefault("material", path)
        elif role == "material":
            stem = Path(path.replace("\\", "/")).stem.casefold()
            if stem.endswith(("_sp", "_spec", "_specular")):
                channels.setdefault("specular", path)
            else:
                channels.setdefault("material", path)
        elif role == "flow":
            channels.setdefault("flow", path)


def _has_authoritative_color_input(source: object, path: str) -> bool:
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = canonical_material_channel(
            str(
                values.get("semantic_type", "")
                or values.get("slot_kind", "")
                or getattr(item, "semantic_type", "")
                or getattr(item, "slot_kind", "")
                or ""
            )
        )
        if semantic != "base":
            continue
        candidate = next(
            (
                str(values.get(name, "") or getattr(item, name, "") or "").strip()
                for name in ("source_dds_path", "source_texture_path", "source_path", "preview_texture_path")
                if str(values.get(name, "") or getattr(item, name, "") or "").strip()
            ),
            "",
        )
        if not _same_texture_reference(candidate, path):
            continue
        confidence = str(values.get("confidence", "") or getattr(item, "confidence", "") or "").strip().casefold()
        declared_by = str(
            values.get("parameter_declared_by", "")
            or getattr(item, "parameter_declared_by", "")
            or ""
        ).strip()
        sidecar_kind = str(values.get("sidecar_kind", "") or getattr(item, "sidecar_kind", "") or "").strip()
        if declared_by or sidecar_kind or confidence in {
            "authoritative",
            "exact",
            "gltf",
            "manual",
            "scene",
            "shader_parameter_rule",
        }:
            return True
    return False


def _same_texture_reference(left: object, right: object) -> bool:
    return str(left or "").replace("\\", "/").strip().casefold() == str(right or "").replace(
        "\\", "/"
    ).strip().casefold()


def _normalized_color_space(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes", "srgb", "s_rgb", "color"}:
        return "srgb"
    if normalized in {"false", "0", "no", "linear", "data", "raw"}:
        return "linear"
    return ""
