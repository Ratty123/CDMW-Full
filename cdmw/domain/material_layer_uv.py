"""Pure PAC Byte4 detail-layer sampling rules shared by preview transports."""

from __future__ import annotations

import math
import re
import struct
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


def pac_blend_layer_uv_transform(
    parameters: Iterable[tuple[str, object]],
) -> tuple[float, float, float, float, float, float]:
    """Return where the Ver2 blend layer (the game's "symbol") sits on the mesh UV.

    The layer is placed once, not tiled: it draws where the transformed
    coordinate lies in 0.005 to 0.995. Scale is bytes 0 and 1 of
    `_dyeingTransformProperty4`, the angle byte 3 of `_dyeingPropertyBlend`, the
    translation the two half floats of `_dyeingBlendTextureTranslation`. Bits 2
    and 4 of `_colorBlendingOptionBitFlag` mirror it in U and V. An unauthored
    parameter takes the engine's default: scale 1, no turn, no translation.
    """
    scale, rotation, translation, mirror = (1.0, 1.0), 0.5, (0.0, 0.0), 0
    for name, value in parameters:
        key = "".join(character for character in str(name).casefold() if character.isalnum())
        if key == "dyeingtransformproperty4":
            parts = _byte4(value)
            if len(parts) == 4:
                scale = parts[0], parts[1]
        elif key == "dyeingpropertyblend":
            parts = _byte4(value)
            if len(parts) == 4:
                rotation = parts[3]
        elif key in {"dyeingblendtexturetranslation", "colorblendingoptionbitflag"}:
            text = str(value).strip() if value is not None else ""
            if not re.fullmatch(r"\d+", text):
                continue
            integer = min(0xFFFFFFFF, int(text))
            if key == "colorblendingoptionbitflag":
                mirror = integer
            else:
                translation = struct.unpack("<2e", struct.pack("<I", integer))
    sx, sy = max(scale[0], 1e-5), max(scale[1], 1e-5)
    angle = rotation * (2.0 * math.pi) - math.pi
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = (-0.5 - translation[0]) / sx, (-0.5 + translation[1]) / sy
    transform = [
        cosine / sx, sine / sx, -sine / sy, cosine / sy,
        x * cosine - y * sine + 0.5, x * sine + y * cosine + 0.5,
    ]
    if mirror & 2:
        transform[0], transform[2], transform[4] = -transform[0], -transform[2], 1.0 - transform[4]
    if mirror & 4:
        transform[1], transform[3], transform[5] = -transform[1], -transform[3], 1.0 - transform[5]
    return tuple(transform)  # type: ignore[return-value]


def pac_blend_layer_surface(
    parameters: Iterable[tuple[str, object]],
) -> tuple[int, tuple[float, float, float]]:
    """Return the Ver2 symbol's surface switches and steps: (flags, (rough, metal, angle)).

    The game (permutation d4ae32939fa23e46, %1782-%1908) weighs the symbol's
    normal and material by wn = (flag bit 12 ? texture alpha : 1) * opacity
    byte; bit 13 of `_colorBlendingFlag` draws `_detailNormalBlend` (rotated by
    the symbol's angle), bit 14 moves roughness and metal to
    `_detailMaterialBlend` .g and .b, and bit 6 of `_colorBlendingOptionBitFlag`
    makes the symbol's normal replace the surface's instead of blending over it.
    Roughness and metal also move by wn times bytes 2 and 3 of
    `_dyeingTransformProperty4` read as `byte * 2 / 255 - 1`.

    flags: bit 0 is flag bit 12, bit 1 flag bit 13, bit 2 flag bit 14, bit 3
    option bit 6. An unauthored flag is the engine's default, clear; an
    unauthored `_dyeingTransformProperty4` moves neither (its default is 0).
    The angle is the placement's, in radians.
    """
    flag = option = 0
    steps = (0.0, 0.0)
    rotation = 0.5
    for name, value in parameters:
        key = "".join(character for character in str(name).casefold() if character.isalnum())
        if key == "dyeingtransformproperty4":
            parts = _byte4(value)
            if len(parts) == 4:
                steps = (parts[2] * 2.0 - 1.0, parts[3] * 2.0 - 1.0)
        elif key == "dyeingpropertyblend":
            parts = _byte4(value)
            if len(parts) == 4:
                rotation = parts[3]
        elif key in {"colorblendingflag", "colorblendingoptionbitflag"}:
            text = str(value).strip() if value is not None else ""
            if re.fullmatch(r"\d+", text):
                if key == "colorblendingflag":
                    flag = min(0xFFFFFFFF, int(text))
                else:
                    option = min(0xFFFFFFFF, int(text))
    flags = ((flag >> 12) & 7) | (8 if option & 64 else 0)
    return flags, (steps[0], steps[1], rotation * (2.0 * math.pi) - math.pi)


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
    """Resolved `_detailMaskTexture`, `_maskTexture`, `_overlayColorTexture` and
    `_detailDiffuseBlend`, `_detailNormalBlend`, `_detailMaterialBlend` files of a
    native preview package manifest.

    The Ver2 grime and scratch rules read the first, the legacy families' dye the
    second, the Ver2 overlay step the third, the Ver2 blend layer the last three. No
    material layer row is certain to name them, so readers that protect, check or
    copy layer sources ask here as well.
    """
    conservation = manifest.get("material_conservation") if isinstance(manifest, Mapping) else None
    parameters = conservation.get("parameters") if isinstance(conservation, Mapping) else None
    if not isinstance(parameters, (list, tuple)):
        return ()
    sources: list[str] = []
    for parameter in parameters:
        if not isinstance(parameter, Mapping):
            continue
        if str(parameter.get("parameter_name", "")).casefold().lstrip("_") not in {
            "detailmasktexture", "masktexture", "overlaycolortexture", "detaildiffuseblend",
            "detailnormalblend", "detailmaterialblend",
        }:
            continue
        source = str(parameter.get("resolved_source_path", "") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return tuple(sources)
