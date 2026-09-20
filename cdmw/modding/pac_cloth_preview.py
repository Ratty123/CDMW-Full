"""Owned guide snapshot for a controlled native cloth preview, never PAC edits."""

from __future__ import annotations

import math

from ._pbd_numeric import round_pbd_half
from .pac_cloth_guides import (
    decode_pac_cloth_guides, inspect_guide_constraint_geometry,
    inspect_guide_particle_initialization,
)
from .pac_jiggle_skinning import prepare_jiggle_bone_skinning
from .pac_cloth_preparation import prepare_guide_cloth_attachments


def build_cloth_preview_snapshot(data: bytes, rig: dict) -> dict:
    """Retain decoded anchors/constraints in the resolved neutral rig's space.

    The host must supply its validated matching PAB/PAC palette snapshot. Guide
    animation uses byte weights /255; CPU rest geometry uses normalized weights
    and its distinct full-16-bit positions. The native preview chooses its own
    clock, forces and iteration schedule; no active game material is inferred.
    """
    guides = decode_pac_cloth_guides(data)
    if guides is None or not guides.vertices:
        raise ValueError("This PAC has no decoded cloth guide mesh.")
    inverse, poses, palette = (rig[key] for key in ("inverse_bind_matrices", "neutral_global_matrices", "bone_palette"))
    if len(inverse) != len(poses) or not poses:
        raise ValueError("Cloth preview needs matching inverse-bind and neutral bone matrices.")
    matrices = [prepare_jiggle_bone_skinning(inverse_bind_matrix=a, animation_matrix=b,
                                           jiggle_matrix=None, character_space_scale=(1., 1., 1.))["skeletal_matrix"]
                for a, b in zip(inverse, poses, strict=True)]
    frames, cpu_positions = [], []
    for source, cpu, slots, weights in zip(guides.vertices, guides.cpu_unskinned_vertices,
                                         guides.bone_indices, guides.bone_weight_bytes, strict=True):
        if (any(slot >= len(palette) for slot in slots)
                or any(type(palette[slot]) is not int or not 0 <= palette[slot] < len(matrices) for slot in slots)):
            raise ValueError("Cloth guide skinning refers outside the resolved PAC bone palette.")
        total = sum(weights)
        if not total:
            raise ValueError("Cloth preview cannot bind a guide with zero skeletal weight.")
        weighted = [[sum(matrices[palette[slot]][i][j]*weight for slot, weight in zip(slots, weights))
                     for j in range(3)] for i in range(4)]
        shader_position = [sum((*source, 1.)[i]*weighted[i][j] for i in range(4))/255. for j in range(3)]
        cpu_positions.append([sum((*cpu, 1.)[i]*weighted[i][j] for i in range(4))/total for j in range(3)])
        frames.append([[value/255. for value in row] + [1. if i == 0 else 0.]
                       for i, row in enumerate(weighted[:3])] + [shader_position + [1.]])
    if any(not math.isfinite(x) for frame in frames for row in frame for x in row):
        raise ValueError("Cloth guide skinning produced a non-finite frame.")
    geometry = inspect_guide_constraint_geometry(guides, particle_positions=cpu_positions)
    constraints = []
    for row in geometry["constraints"]:
        kind = row["kind"]
        field = {"pair": "rest_length", "hinge": "rest_angle_radians", "triangle": "rest_area"}.get(kind)
        if field is None:
            raise ValueError("This PAC contains an undecoded cloth constraint record.")
        constraints.append({"kind": kind, "indices": list(row["vertices"]), "rest": round_pbd_half(row[field])})
    initial = inspect_guide_particle_initialization(guides)
    # Explicit preview preparation: component-local anchors, authored alpha and
    # no automatic weighting. This does not identify the active game material.
    prepared = prepare_guide_cloth_attachments(
        guides, separate_components=True, use_vertex_alpha_position_blending=True,
        auto_weighting_enabled=False, particle_positions=cpu_positions)
    return {
        "version": 1, "source_positions": [list(v) for v in guides.vertices],
        "animation_frames": frames, "fixed": [b == 255 for b in guides.channel_b],
        "alpha_blends": initial["position_blend_with_vertex_alpha"],
        "orientation_neighbors": prepared["orientation_neighbor_indices"],
        "constraints": constraints,
    }
