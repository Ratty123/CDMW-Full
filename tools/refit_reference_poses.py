"""Posed scoring for the Fit to body harness.

Fit to body only moves vertex positions in the bind pose. In game, the body and
the garment are both skinned by the character's skeleton, the garment through
its own skin weights with its bones matched by name. This module poses both
through a few limb and torso rotations and scores what the motion adds, beside
the same outfit posed the same way on the body it was authored for:

- added inside: garment vertices inside the posed body that were outside at rest;
- added skin through: body vertices that come through the garment only when posed;
- follow error: how far cloth within FOLLOW_REACH of the skin ends up from where
  the body vertices around it would carry it (p95 and max), which is where the
  garment's weights disagree with the body's.

Poses rotate main Biped bones about world axes through their rest joints; the
character faces -z with +y up and its left at +x. Helper bones (twists, subs,
muscles) follow their parents rigidly, as no game constraint is evaluated.
"""

from __future__ import annotations

import numpy as np

from cdmw.modding.mesh_refit_reference import bind_matrices, skin_retarget

FOLLOW_REACH = 0.02

POSES = {
    "arms_up": {"Bip01 L UpperArm": ("z", 60.0), "Bip01 R UpperArm": ("z", -60.0)},
    "arms_forward": {"Bip01 L UpperArm": ("x", 70.0), "Bip01 R UpperArm": ("x", 70.0),
                     "Bip01 L Forearm": ("x", 60.0), "Bip01 R Forearm": ("x", 60.0)},
    "stride": {"Bip01 L Thigh": ("x", 45.0), "Bip01 R Thigh": ("x", -30.0),
               "Bip01 L Calf": ("x", -60.0), "Bip01 R Calf": ("x", -20.0)},
    "crouch": {"Bip01 L Thigh": ("x", 80.0), "Bip01 R Thigh": ("x", 80.0),
               "Bip01 L Calf": ("x", -100.0), "Bip01 R Calf": ("x", -100.0)},
    "twist_bend": {"Bip01 Spine": ("y", 30.0), "Bip01 Spine1": ("x", -20.0)},
}


def _rotation(axis: str, degrees: float) -> np.ndarray:
    """3x3 for row vectors (``p @ R``), a right-handed turn about a world axis."""
    angle = np.radians(degrees)
    c, s = np.cos(angle), np.sin(angle)
    column = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
              "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    return np.asarray(column, dtype=np.float64).T


def pose_matrices(skeleton: object, pose: dict[str, tuple[str, float]]) -> np.ndarray:
    """Per-bone 4x4 row-vector transforms from the rest pose into ``pose``."""
    bones = tuple(skeleton.bones)
    binds = bind_matrices(skeleton)
    local = np.tile(np.eye(4), (len(bones), 1, 1))
    for index, bone in enumerate(bones):
        if str(bone.name) in pose:
            axis, degrees = pose[str(bone.name)]
            rotation = _rotation(axis, degrees)
            pivot = binds[index][3, :3]
            local[index][:3, :3] = rotation
            local[index][3, :3] = pivot - pivot @ rotation
    posed = np.full((len(bones), 4, 4), np.nan)

    def resolve(index: int) -> np.ndarray:
        if not np.isnan(posed[index][0, 0]):
            return posed[index]
        parent = int(bones[index].parent_index)
        # A child's own turn applies first, about its rest joint, then its parents'.
        posed[index] = local[index] @ (resolve(parent) if 0 <= parent < len(bones) and parent != index else np.eye(4))
        return posed[index]

    for index in range(len(bones)):
        resolve(index)
    return posed


def slot_transforms(bone_matrices: np.ndarray, slot_bones) -> np.ndarray:
    """Palette slot transforms; a slot without a bone (-1) stays at rest."""
    slots = np.asarray(slot_bones, dtype=np.int64).reshape(-1)
    transforms = np.tile(np.eye(4), (len(slots), 1, 1))
    valid = (slots >= 0) & (slots < len(bone_matrices))
    transforms[valid] = bone_matrices[slots[valid]]
    return transforms


def skin_parts(parts, points, transforms) -> np.ndarray:
    """Posed positions of ``parts`` (weights) at ``points`` (one array per part), joined."""
    return np.concatenate([skin_retarget(p, part.bone_indices, part.bone_weights, transforms)
                           for part, p in zip(parts, points)])


def blended_matrices(parts, transforms) -> np.ndarray:
    """Each vertex's linear-blend skinning matrix, joined over ``parts``."""
    result = []
    for part in parts:
        count = len(part.vertices)
        matrices = np.tile(np.eye(4), (count, 1, 1))
        if len(part.bone_indices) == count and len(part.bone_weights) == count:
            for row, (slots, weights) in enumerate(zip(part.bone_indices, part.bone_weights)):
                pairs = [(int(s), float(w)) for s, w in zip(slots, weights) if 0 <= int(s) < len(transforms) and w > 0.0]
                total = sum(w for _s, w in pairs)
                if total > 0.0:
                    matrices[row] = sum(w * transforms[s] for s, w in pairs) / total
        result.append(matrices)
    return np.concatenate(result)


def follow_error(body_rest, body_matrices, garment_rest, garment_posed) -> np.ndarray:
    """How far cloth near the skin ends up from where the body would carry it, per point.

    For each garment point within FOLLOW_REACH of a body vertex, the smallest
    distance between its posed position and the point carried by any such
    body vertex's own skinning. A sleeve beside the torso follows the arm
    vertices near it and scores zero; cloth weighted unlike every body vertex
    around it scores what it slides or tears away.
    """
    from scipy.spatial import cKDTree

    neighbours = cKDTree(body_rest).query_ball_point(garment_rest, FOLLOW_REACH)
    rows = np.fromiter((i for i, items in enumerate(neighbours) for _ in items), dtype=np.int64)
    if not len(rows):
        return np.zeros(0)
    columns = np.fromiter((j for items in neighbours for j in items), dtype=np.int64)
    homogeneous = np.c_[garment_rest[rows], np.ones(len(rows))]
    carried = np.einsum("ni,nij->nj", homogeneous, body_matrices[columns])[:, :3]
    error = np.linalg.norm(garment_posed[rows] - carried, axis=1)
    best = np.full(len(garment_rest), np.inf)
    np.minimum.at(best, rows, error)
    return best[np.isfinite(best)]


__all__ = ["FOLLOW_REACH", "POSES", "blended_matrices", "follow_error", "pose_matrices", "skin_parts", "slot_transforms"]
