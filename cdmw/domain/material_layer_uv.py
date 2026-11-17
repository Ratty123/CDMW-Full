"""Pure PAC Byte4 detail-layer sampling rules shared by preview transports."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping

IDENTITY_UV_TRANSFORM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _byte4(value: object) -> tuple[float, ...]:
    text = str(value).strip() if value is not None else ""
    if not re.fullmatch(r"[+-]?\d+", text):
        return ()
    try:
        integer = max(0, min(0xFFFFFFFF, int(text)))
    except ValueError:
        return ()
    return tuple(((integer >> (8 * index)) & 255) / 255.0 for index in range(4))


def pac_layer_sampling_parameters(
    parameters: Iterable[tuple[str, object]], channel: str,
) -> tuple[float, float, float, float, float] | None:
    """Return scale, offset and angle without changing legacy sampling order."""
    index = {"r": 0, "g": 1, "b": 2}.get(str(channel).casefold())
    if index is None:
        return None
    transform_key = f"dyeingtransformproperty{(0, 1, 3)[index]}"
    transform, rotation = (), ()
    for name, value in parameters:
        key = "".join(character for character in str(name).casefold() if character.isalnum())
        if key == transform_key:
            transform = _byte4(value)
        elif key == "dyeingpropertyblend":
            rotation = _byte4(value)
    if len(transform) != 4:
        return None
    angle = rotation[index] * (2.0 * math.pi) - math.pi if rotation else 0.0
    return (*transform, angle)


def pac_layer_uv_transform(
    parameters: Iterable[tuple[str, object]], channel: str,
) -> tuple[float, float, float, float, float, float]:
    """Return the repeat-sampling affine; an authored zero is not absence.

    Coordinates follow u' = a0*u + a2*v + a4, v' = a1*u + a3*v + a5.
    The rendering consumer owns its texture-orientation convention.
    """
    values = pac_layer_sampling_parameters(parameters, channel)
    if values is None:
        return IDENTITY_UV_TRANSFORM
    sx, sy, ox, oy, angle = values
    sx, sy = max(sx, 1e-5), max(sy, 1e-5)
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = (-0.5 - ox) / sx, (-0.5 + oy) / sy
    return (
        cosine / sx, sine / sx, -sine / sy, cosine / sy,
        x * cosine - y * sine + 0.5, x * sine + y * cosine + 0.5,
    )


def pac_grime_uv_transform(
    value: object,
) -> tuple[float, float, float, float, float, float] | None:
    """Return the grime layer's own repeat-sampling affine, or None when unreadable.

    `_grimeBlendingParameter{R,G,B}` carries the grime tile scale in bytes 0 and
    1 and its angle in byte 2; grime has no offset, and does not follow the
    colour layer's `_dyeingTransformProperty*`.
    """
    parts = _byte4(value)
    if len(parts) != 4:
        return None
    sx, sy = max(parts[0], 1e-5), max(parts[1], 1e-5)
    angle = parts[2] * (2.0 * math.pi) - math.pi
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = -0.5 / sx, -0.5 / sy
    return (
        cosine / sx, sine / sx, -sine / sy, cosine / sy,
        x * cosine - y * sine + 0.5, x * sine + y * cosine + 0.5,
    )


def pac_grime_blend_bytes(
    parameters: Iterable[tuple[str, object]], channel: str,
) -> tuple[int, int, int] | None:
    """Return the grime ramp's low and high bytes and its intensity byte.

    The game shows grime where `_detailMaskTexture` green passes a smoothstep
    between the two ramp bytes, times the intensity byte (255 is 2.0). Red and
    green read `_grimeBlendingOpacityParameter` bytes 0, 1 and 2, 3; blue reads
    `_grimeBlendingOpacityParameter1` bytes 0, 1. None when either parameter is
    not authored, because the engine defaults are not known.
    """
    channel = str(channel).casefold()
    if channel not in {"r", "g", "b"}:
        return None
    range_key = "grimeblendingopacityparameter1" if channel == "b" else "grimeblendingopacityparameter"
    blend_key = f"grimeblendingparameter{channel}"
    found: dict[str, int] = {}
    for name, value in parameters:
        key = "".join(character for character in str(name).casefold() if character.isalnum())
        if key in {range_key, blend_key}:
            text = str(value).strip() if value is not None else ""
            if re.fullmatch(r"\d+", text):
                found[key] = min(0xFFFFFFFF, int(text))
    if range_key not in found or blend_key not in found:
        return None
    shift = 16 if channel == "g" else 0
    ramp = found[range_key] >> shift
    return ramp & 255, (ramp >> 8) & 255, (found[blend_key] >> 24) & 255


def pac_scratch_bytes(
    parameters: Iterable[tuple[str, object]], channel: str,
) -> tuple[int, int] | None:
    """Return a layer's scratch roughness and metal bytes, or None when unauthored.

    Where `_detailMaskTexture` red marks a scratch the game moves roughness and
    metal by `byte * 2 / 255 - 1`; `_scratchRoughness` and `_scratchMetallic`
    hold one byte per layer. 127, the value authors leave for no change, stands
    in for the one parameter a wrapper leaves out.
    """
    index = {"r": 0, "g": 1, "b": 2}.get(str(channel).casefold())
    if index is None:
        return None
    found: dict[str, int] = {}
    for name, value in parameters:
        key = "".join(character for character in str(name).casefold() if character.isalnum())
        if key in {"scratchroughness", "scratchmetallic"}:
            text = str(value).strip() if value is not None else ""
            if re.fullmatch(r"\d+", text):
                found[key] = (min(0xFFFFFFFF, int(text)) >> (8 * index)) & 255
    if not found:
        return None
    return found.get("scratchroughness", 127), found.get("scratchmetallic", 127)


def pac_color_bytes(value: object) -> tuple[float, float, float, float] | None:
    """Parse a PAC `#rrggbbaa` colour into unit sRGB components and alpha."""
    text = str(value or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{8}", text):
        return None
    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (1, 3, 5, 7))  # type: ignore[return-value]


def detail_mask_sources(manifest: object) -> tuple[str, ...]:
    """Resolved `_detailMaskTexture` files of a native preview package manifest.

    The Ver2 grime and scratch rules read this map. No material layer row names
    it, so readers that protect, check or copy layer sources ask here as well.
    """
    conservation = manifest.get("material_conservation") if isinstance(manifest, Mapping) else None
    parameters = conservation.get("parameters") if isinstance(conservation, Mapping) else None
    if not isinstance(parameters, (list, tuple)):
        return ()
    sources: list[str] = []
    for parameter in parameters:
        if not isinstance(parameter, Mapping):
            continue
        if str(parameter.get("parameter_name", "")).casefold().lstrip("_") != "detailmasktexture":
            continue
        source = str(parameter.get("resolved_source_path", "") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return tuple(sources)
