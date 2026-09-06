"""Bounded, read-only active-bone display data for the resident Rust editor."""

from __future__ import annotations

import math

MAX_INFLUENCE_VERTICES = 131_072


def selected_bone_influence(session: object, bone_index: int, palette: tuple[int, ...]) -> dict[str, object]:
    """Resolve PAC slots before exposing weights; never label slot IDs as bones."""
    result: dict[str, object] = {
        "bone_index": bone_index,
        "available": False,
        "reason": "Choose a bone to inspect its influence.",
        "vertex_count": 0,
        "parts": [],
    }
    if bone_index < 0:
        return result
    if not palette:
        result["reason"] = "Weight display needs a resolved PAC palette and matching rig."
        return result
    bones = tuple(getattr(getattr(session, "skeleton", None), "bones", ()) or ())
    slots = {
        slot for slot, ordinal in enumerate(palette)
        if 0 <= ordinal < len(bones)
        and int(getattr(bones[ordinal], "index", ordinal)) == bone_index
    }
    parts = []
    count = 0
    for submesh_index, part in enumerate(session.working_mesh.submeshes):
        if not part.bone_indices and not part.bone_weights:
            continue
        if len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices):
            result["reason"] = "This mesh has incomplete weight rows; its weight display is unavailable."
            return result
        rows = []
        for vertex_index, (indices, weights) in enumerate(zip(part.bone_indices, part.bone_weights)):
            if len(indices) != len(weights) or any(int(slot) < 0 or int(slot) >= len(palette) for slot in indices):
                result["reason"] = "This mesh has unresolved weight rows; its weight display is unavailable."
                return result
            weight = sum(float(value) for slot, value in zip(indices, weights) if int(slot) in slots)
            if not math.isfinite(weight) or weight < 0.0 or weight > 1.00001:
                result["reason"] = "This bone has invalid weight rows; its weight display is unavailable."
                return result
            if weight <= 0.0:
                continue
            count += 1
            if count > MAX_INFLUENCE_VERTICES:
                result["reason"] = "This bone exceeds the weight display limit; no partial influence is shown."
                return result
            rows.append([vertex_index, min(weight, 1.0)])
        if rows:
            parts.append({"submesh_index": submesh_index, "weights": rows})
    result.update(available=True, reason="", vertex_count=count, parts=parts)
    return result
