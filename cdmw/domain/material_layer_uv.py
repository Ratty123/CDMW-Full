"""Pure PAC Byte4 detail-layer sampling rules shared by preview transports."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

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
