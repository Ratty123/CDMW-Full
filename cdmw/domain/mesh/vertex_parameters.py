"""Pure selection, numeric and influence rules for the vertex inspector."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .editing import MeshEditSelection


def selected_vertices(mesh, selection: MeshEditSelection, check_cancel=lambda: None):
    """Use the editor's union of vertices, edge ends, faces and whole parts.

    Source indices in MeshEditSelection name whole parts, not vertex provenance.
    In particular an empty selection has no implicit whole-mesh scope.
    """
    groups = {part: set(indices) for part, indices in selection.vertices_by_submesh}
    for part, edges in selection.edges_by_submesh:
        check_cancel()
        group = groups.setdefault(part, set())
        for edge in edges:
            group.update(edge)
    for part, faces in selection.faces_by_submesh:
        check_cancel()
        group = groups.setdefault(part, set())
        for face in faces:
            group.update(mesh.submeshes[part].faces[face])
    for part in selection.source_indices:
        check_cancel()
        groups[part] = range(len(mesh.submeshes[part].vertices))
    return {part: tuple(sorted(indices)) for part, indices in sorted(groups.items()) if indices}


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    return result


def channel_edit(row, edit, *, channel, uv_limit=None):
    if not isinstance(edit, Mapping) or set(edit) - {"mode", "values"}:
        raise ValueError(f"Invalid {channel} edit.")
    mode = edit.get("mode", "set")
    if mode not in ("set", "offset") or channel == "normal" and mode != "set":
        raise ValueError(f"Unsupported {channel} operation.")
    width = 2 if channel == "uv0" else 3
    values = edit.get("values")
    if not isinstance(values, (tuple, list)) or len(values) != width:
        raise ValueError(f"{channel} needs {width} components.")
    if channel == "normal" and any(value is None for value in values):
        raise ValueError("Enter all three components of the normal direction.")
    result = list(row)
    for axis, value in enumerate(values):
        if value is not None:
            number = finite_number(value, channel)
            result[axis] = number if mode == "set" else result[axis] + number
    if any(not math.isfinite(value) or abs(value) > 3.4028234663852886e38 for value in result):
        raise ValueError(f"{channel} exceeds the finite float32 range.")
    if channel == "normal":
        length = math.hypot(*result)
        if length == 0.0:
            raise ValueError("Normal direction must not be zero-length.")
        result = [value / length for value in result]
    if channel == "uv0" and uv_limit is not None and any(abs(value) > uv_limit for value in result):
        raise ValueError(f"UV0 exceeds the output format range (+/-{uv_limit:g}).")
    return tuple(result)


def edit_weights(indices, weights, edit, *, slot, capacity):
    if not isinstance(edit, Mapping) or set(edit) - {"mode", "bone", "value"}:
        raise ValueError("Invalid skin-weight edit.")
    if len(indices) != len(weights) or len(set(indices)) != len(indices):
        raise ValueError("Skin-weight row has ambiguous influences.")
    values = {bone: finite_number(weight, "Skin weight") for bone, weight in zip(indices, weights)}
    if any(value < 0.0 for value in values.values()) or sum(values.values()) <= 0.0:
        raise ValueError("Skin-weight row must have a positive total and nonnegative weights.")
    values = {bone: weight for bone, weight in values.items() if weight > 0.0}
    mode = edit.get("mode")
    total = sum(values.values())
    if mode == "normalize":
        values = {bone: value / total for bone, value in values.items()}
    elif mode in {"set", "offset", "remove"}:
        if slot is None:
            raise ValueError("Choose a bone resolved by the source palette.")
        current = values.get(slot, 0.0)
        amount = 0.0 if mode == "remove" else finite_number(edit.get("value"), "Skin weight")
        amount = current + amount if mode == "offset" else amount
        if not 0.0 <= amount <= 1.0:
            raise ValueError("The resulting bone influence must be between 0 and 1.")
        if amount == current and math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-15):
            return tuple(indices), tuple(weights)
        others = {bone: value for bone, value in values.items() if bone != slot}
        other_total = sum(others.values())
        if not other_total and amount != 1.0:
            raise ValueError("Keep the last influence at 1, or add another bone first.")
        values = {bone: value * (1.0 - amount) / other_total for bone, value in others.items()} if other_total else {}
        if amount > 0.0:
            values[slot] = amount
        values = {bone: value for bone, value in values.items() if value > 0.0}
    else:
        raise ValueError("Unsupported skin-weight operation.")
    if not values or len(values) > capacity:
        raise ValueError(f"The output supports 1 to {capacity} skeletal influences per vertex.")
    # Preserve source row order; append a newly chosen slot deterministically.
    order = [bone for bone in indices if bone in values]
    order.extend(bone for bone in values if bone not in order)
    return tuple(order), tuple(values[bone] for bone in order)


class NumericSummary:
    """Streaming, exact mixed/range summary; missing channels are not zeroes."""

    def __init__(self, width):
        self.width = width
        self.count = 0
        self.first = None
        self.minimum = None
        self.maximum = None
        self.mixed = [False] * width

    def add(self, row):
        if row is None:
            return
        row = tuple(row)
        if len(row) != self.width or any(not math.isfinite(value) for value in row):
            return
        if self.first is None:
            self.first, self.minimum, self.maximum = row, list(row), list(row)
        for axis, value in enumerate(row):
            self.mixed[axis] |= value != self.first[axis]
            self.minimum[axis] = min(self.minimum[axis], value)
            self.maximum[axis] = max(self.maximum[axis], value)
        self.count += 1

    def payload(self, total):
        return {"available_count": self.count, "selection_count": total,
                "values": [None if mixed else self.first[axis] for axis, mixed in enumerate(self.mixed)] if self.count else None,
                "mixed": self.mixed, "min": self.minimum, "max": self.maximum}
