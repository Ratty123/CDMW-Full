"""Test rotations of a skinned body and outfit, for Fit to body's weight transfer.

Poses rotate named bones about world axes through their rest joints (the game's
characters face -z with +y up and their left at +x); every other bone follows
its parent rigidly. A bone a skeleton does not have is not rotated, so a pose
names Biped bones without failing on other rigs.

``DESIGN_POSES`` are moderate turns of the arms, legs and torso. On the body an
outfit was authored for, a garment point that moves with the skin beneath it in
all of them was made to follow that skin; one that stays behind (a cape beside
the arm) was not, and keeps its own weights when fitted to another body.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from cdmw.modding.mesh_refit_reference import bind_matrices, skin_retarget

DESIGN_POSES = (
    {"Bip01 L UpperArm": ("z", 45.0), "Bip01 R UpperArm": ("z", -45.0)},
    {"Bip01 L UpperArm": ("x", 45.0), "Bip01 R UpperArm": ("x", 45.0),
     "Bip01 L Forearm": ("x", 45.0), "Bip01 R Forearm": ("x", 45.0)},
    {"Bip01 L Thigh": ("x", 40.0), "Bip01 R Thigh": ("x", -25.0),
     "Bip01 L Calf": ("x", -50.0), "Bip01 R Calf": ("x", -20.0)},
    {"Bip01 Spine": ("y", 25.0), "Bip01 Spine1": ("x", -15.0)},
)


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


def rest_motion(parts: Sequence[object], slot_bones: Sequence[int], skeleton: object,
                poses: Sequence[dict] = DESIGN_POSES) -> np.ndarray:
    """How far each vertex of ``parts`` moves in each pose: ``(vertices, poses, 3)``, joined."""
    rests = [np.asarray(part.vertices, dtype=np.float64).reshape(-1, 3) for part in parts]
    motion = np.zeros((sum(len(rest) for rest in rests), len(poses), 3))
    for k, pose in enumerate(poses):
        transforms = slot_transforms(pose_matrices(skeleton, pose), slot_bones)
        offset = 0
        for part, rest in zip(parts, rests):
            motion[offset:offset + len(rest), k] = skin_retarget(rest, part.bone_indices, part.bone_weights, transforms) - rest
            offset += len(rest)
    return motion


__all__ = ["DESIGN_POSES", "pose_matrices", "rest_motion", "slot_transforms"]
