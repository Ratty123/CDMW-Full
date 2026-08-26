"""Pure placement-matrix updates shared by resident preview hosts and New Item."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from cdmw.ui.preview.dotnet_host_values import _triple


def placement_matrix(translation, rotation_degrees, scale_xyz) -> list:
    """Compose S, Rx, Ry, Rz, and T in the helper's row-vector convention."""

    sx, sy, sz = (float(value) for value in scale_xyz)
    ax, ay, az = (math.radians(float(value)) for value in rotation_degrees[:3])
    cx, sx_ = math.cos(ax), math.sin(ax)
    cy, sy_ = math.cos(ay), math.sin(ay)
    cz, sz_ = math.cos(az), math.sin(az)
    rx = ((1.0, 0.0, 0.0), (0.0, cx, sx_), (0.0, -sx_, cx))
    ry = ((cy, 0.0, -sy_), (0.0, 1.0, 0.0), (sy_, 0.0, cy))
    rz = ((cz, sz_, 0.0), (-sz_, cz, 0.0), (0.0, 0.0, 1.0))

    def multiply(left, right):
        return tuple(
            tuple(sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3))
            for row in range(3)
        )

    rotation = multiply(multiply(rx, ry), rz)
    rows = [
        [sx * rotation[0][0], sx * rotation[0][1], sx * rotation[0][2], 0.0],
        [sy * rotation[1][0], sy * rotation[1][1], sy * rotation[1][2], 0.0],
        [sz * rotation[2][0], sz * rotation[2][1], sz * rotation[2][2], 0.0],
        [float(translation[0]), float(translation[1]), float(translation[2]), 1.0],
    ]
    return [value for row in rows for value in row]


def apply_placement_to_editable_role(
    scene_state: dict,
    placement: Mapping[str, Sequence[float]],
) -> None:
    roles = scene_state.get("roles")
    editable = roles.get("editable") if isinstance(roles, dict) else None
    if not isinstance(editable, dict):
        return
    translation = _triple(tuple(placement["translation"]), (0.0, 0.0, 0.0))
    manual_matrix = placement_matrix(
        (0.0, 0.0, 0.0),
        placement["rotation_degrees"],
        placement["scale"],
    )
    alignment = scene_state.get("automatic_alignment")
    anchor = (
        _triple(tuple(alignment.get("source_anchor", ()) or ()), (0.0, 0.0, 0.0))
        if isinstance(alignment, Mapping)
        else (0.0, 0.0, 0.0)
    )
    automatic_values = alignment.get("model_matrix") if isinstance(alignment, Mapping) else None
    try:
        automatic = [float(value) for value in automatic_values] if isinstance(automatic_values, Sequence) else []
    except (TypeError, ValueError):
        automatic = []
    if len(automatic) == 16:
        matrix = [0.0] * 16
        for row in range(3):
            for column in range(3):
                matrix[row * 4 + column] = sum(
                    automatic[row * 4 + index] * manual_matrix[index * 4 + column]
                    for index in range(3)
                )
        matrix[15] = 1.0
        automatic_pivot = (
            anchor[0] * automatic[0] + anchor[1] * automatic[4] + anchor[2] * automatic[8] + automatic[12],
            anchor[0] * automatic[1] + anchor[1] * automatic[5] + anchor[2] * automatic[9] + automatic[13],
            anchor[0] * automatic[2] + anchor[1] * automatic[6] + anchor[2] * automatic[10] + automatic[14],
        )
        pivot = tuple(automatic_pivot[index] + translation[index] for index in range(3))
        matrix[12] = pivot[0] - (anchor[0] * matrix[0] + anchor[1] * matrix[4] + anchor[2] * matrix[8])
        matrix[13] = pivot[1] - (anchor[0] * matrix[1] + anchor[1] * matrix[5] + anchor[2] * matrix[9])
        matrix[14] = pivot[2] - (anchor[0] * matrix[2] + anchor[1] * matrix[6] + anchor[2] * matrix[10])
    else:
        matrix = placement_matrix(translation, placement["rotation_degrees"], placement["scale"])
        pivot = (
            anchor[0] * matrix[0] + anchor[1] * matrix[4] + anchor[2] * matrix[8] + matrix[12],
            anchor[0] * matrix[1] + anchor[1] * matrix[5] + anchor[2] * matrix[9] + matrix[13],
            anchor[0] * matrix[2] + anchor[1] * matrix[6] + anchor[2] * matrix[10] + matrix[14],
        )
    scene_state["placement_pivot"] = list(pivot)
    local = scene_state.get("_editable_local_bounds")
    if local is None:
        bounds = editable.get("world_bounds")
        current = editable.get("model_matrix")
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        if isinstance(bounds, dict) and (
            not isinstance(current, list)
            or [round(float(value), 6) for value in current] == identity
        ):
            local = {
                "min": list(bounds.get("min", (0.0, 0.0, 0.0))),
                "max": list(bounds.get("max", (0.0, 0.0, 0.0))),
            }
            scene_state["_editable_local_bounds"] = local
    editable["model_matrix"] = matrix
    if isinstance(local, dict):
        low, high = local["min"], local["max"]
        corners = [
            (x, y, z)
            for x in (low[0], high[0])
            for y in (low[1], high[1])
            for z in (low[2], high[2])
        ]
        moved = [
            (
                x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
                x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
                x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
            )
            for x, y, z in corners
        ]
        editable["world_bounds"] = {
            "min": [min(corner[index] for corner in moved) for index in range(3)],
            "max": [max(corner[index] for corner in moved) for index in range(3)],
        }


__all__ = ["apply_placement_to_editable_role", "placement_matrix"]
