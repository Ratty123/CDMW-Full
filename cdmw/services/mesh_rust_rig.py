"""Bounded, read-only active-bone display data for the resident Rust editor."""

from __future__ import annotations

import math
import json

from cdmw.domain.mesh.skeleton import refresh_mesh_skinning_selection
from cdmw.services.mesh_rust_state_cache import skeleton_identity

MAX_INFLUENCE_VERTICES = 131_072


def cached_skeleton_summary(session, cache, build_summary):
    """Keep full weight aggregates while selection/active-bone fields change."""
    cache.observe(session)
    key = (
        cache.weight_revision, skeleton_identity(session),
        *(str(getattr(session, name, "")) for name in (
            "skeleton_source", "skeleton_descriptor_source", "skeleton_variation_source",
            "animation_constraint_source", "socket_source",
        )),
        json.dumps(getattr(session, "animation_constraint_evidence", {}), sort_keys=True, default=repr),
        bool(getattr(session, "pose_preview_enabled", False)),
        tuple(sorted(getattr(session, "bone_pose_rotations", {}).items())),
        getattr(session, "animation_clip", None),
        bool(getattr(session, "animation_playback_enabled", False)),
        getattr(session, "animation_time_seconds", 0.0),
        bool(getattr(session, "animation_loop", True)), getattr(session, "animation_speed", 1.0),
    )
    cached = cache.skeleton_summary
    if cached is None or cached[0] != key:
        summary = build_summary()
        cache.skeleton_summary = key, summary
        return summary
    return refresh_mesh_skinning_selection(
        cached[1], session.working_mesh, session.selection, int(session.selected_bone_index),
    )


def cached_selected_bone_influence(session, bone_index, palette, cache):
    cache.observe(session)
    key = cache.weight_revision, skeleton_identity(session), bone_index, palette
    cached = cache.bone_influence
    if cached is None or cached[0] != key:
        value = selected_bone_influence(session, bone_index, palette)
        rows = tuple((part["submesh_index"], tuple(tuple(row) for row in part["weights"]))
                     for part in value["parts"])
        cache.bone_influence = key, {name: item for name, item in value.items() if name != "parts"}, rows
    else:
        value = cached[1]
    # Cached rows are immutable. A caller can change its response without
    # changing the next response, and no old active-bone documents accumulate.
    cached = cache.bone_influence
    return {**cached[1], "parts": [
        {"submesh_index": index, "weights": [list(row) for row in rows]}
        for index, rows in cached[2]
    ]}


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
