"""Material spline modes decoded from the game's SplineData evaluator.

The scalar segment evaluator at RVA 0x3e393a0 uses cubic Bezier controls
``y0 + width * outer`` and ``y1 + width * inner`` for mode 0, linear for
mode 2 and a held value for mode 3. Tangents are not angles or Hermite slopes.
Other easing/noise modes need their own decoding and are not approximated here.
"""
from __future__ import annotations

import math
import struct


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def sample_material_spline(points, count: int = 128) -> tuple[float, ...]:
    """Bake an admitted scalar spline for the shader's 128-texel lookup."""
    if not points or count < 2:
        return ()
    if any(p["interpolation"] not in (0, 2, 3) for p in points[:-1]):
        return ()
    if any(not math.isfinite(v) for p in points for v in (*p["position"], p["inner_tangent"], p["outer_tangent"])):
        return ()
    if any(b["position"][0] <= a["position"][0] for a, b in zip(points, points[1:])):
        return ()
    result = []
    for index in range(count):
        x = _float32(index / (count - 1))
        if x <= points[0]["position"][0]:
            result.append(points[0]["position"][1])
            continue
        if x >= points[-1]["position"][0]:
            result.append(points[-1]["position"][1])
            continue
        for a, b in zip(points, points[1:]):
            x0, y0 = a["position"]
            x1, y1 = b["position"]
            if x > x1:
                continue
            width = _float32(x1 - x0)
            t = _float32(_float32(x - x0) / width)
            mode = a["interpolation"]
            if mode == 0:
                # The game forms control points in float32, then evaluates
                # the cubic in float64 before rounding the result to float32.
                c1 = _float32(y0 + _float32(width * a["outer_tangent"]))
                c2 = _float32(y1 + _float32(width * b["inner_tangent"]))
                u = 1.0 - t
                y = ((y0 * u + c1 * (3.0 * t)) * u + c2 * (3.0 * t * t)) * u + y1 * t * t * t
            elif mode == 2:
                y = _float32(y0 + _float32(_float32(y1 - y0) * t))
            else:
                y = y1 if mode == 3 and t == 1.0 else y0
            result.append(_float32(y))
            break
        else:
            result.append(points[-1]["position"][1])
    return tuple(result)
