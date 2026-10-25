"""Reference bodies for Morph & Refit's Fit to body.

A garment is authored on one body (the reference, for example the PHM nude body
for a PHM outfit) and fitted onto another (the driver). The native fitter needs
the reference twice: as authored, and moved from its own skeleton's bind pose
into the driver skeleton's bind pose with its own skin weights. What then
remains between the moved reference and the driver is the body difference the
fit transfers to the garment.

PAB bind matrices are row-major with the translation in the last row, so points
are row vectors: ``world = local @ bind``. A reference vertex bound to bone ``b``
moves by ``inv(bind_source[b]) @ bind_target[b]``. A bone the driver skeleton
lacks uses its nearest ancestor that both skeletons share.

An editing session may show a Part in its character's appearance (per-bone
PABC transforms, see :class:`~cdmw.modding.mesh_neutral_appearance.NeutralMeshAppearance`).
The reference is then posed the same way: as authored through the garment's
appearance, and retargeted through the driver's, so the fit sees the bodies the
viewport shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class RefitReferenceBody:
    """One reference body: authored positions, retargeted positions and faces."""

    label: str
    source_positions: np.ndarray
    fitted_positions: np.ndarray
    faces: np.ndarray
    # Palette bones that had to fall back to an ancestor ("name->ancestor") or
    # to no motion at all ("name->identity").
    substituted_bones: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        """The ``reference_body`` object of the native ``morph_set_reference_body`` command."""
        return {
            "label": self.label,
            "source_positions": np.asarray(self.source_positions, dtype=np.float64).ravel().tolist(),
            "fitted_positions": np.asarray(self.fitted_positions, dtype=np.float64).ravel().tolist(),
            "faces": np.asarray(self.faces, dtype=np.int64).ravel().tolist(),
        }


def bind_matrices(skeleton: object) -> np.ndarray:
    """Every bone's 4x4 bind matrix; a bone without one is the identity."""
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    matrices = np.tile(np.eye(4), (len(bones), 1, 1))
    for index, bone in enumerate(bones):
        values = tuple(getattr(bone, "bind_matrix", ()) or ())
        if len(values) == 16:
            matrices[index] = np.asarray(values, dtype=np.float64).reshape(4, 4)
    return matrices


def retarget_transforms(
    palette: Sequence[int], source_skeleton: object, target_skeleton: object
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    """Per-palette-slot transforms from the source bind pose into the target's.

    ``palette`` maps influence slots to source skeleton bone indices, as
    ``resolve_pac_bone_palette`` returns it. Also returns, per slot, the target
    bone each slot now follows (-1 when none), which places target-side
    appearance transforms.
    """
    source_bones = tuple(getattr(source_skeleton, "bones", ()) or ())
    target_bones = tuple(getattr(target_skeleton, "bones", ()) or ())
    source_binds = bind_matrices(source_skeleton)
    target_binds = bind_matrices(target_skeleton)
    target_by_name: dict[str, int] = {}
    for index, bone in enumerate(target_bones):
        target_by_name.setdefault(str(bone.name), index)
    transforms = np.tile(np.eye(4), (len(palette), 1, 1))
    target_palette = np.full(len(palette), -1, dtype=np.int64)
    substituted: list[str] = []
    for slot, bone_index in enumerate(palette):
        if not 0 <= int(bone_index) < len(source_bones):
            substituted.append(f"#{bone_index}->identity")
            continue
        name = str(source_bones[bone_index].name)
        current, seen = int(bone_index), set()
        while str(source_bones[current].name) not in target_by_name:
            seen.add(current)
            parent = int(source_bones[current].parent_index)
            if not 0 <= parent < len(source_bones) or parent in seen:
                current = -1
                break
            current = parent
        if current < 0:
            substituted.append(f"{name}->identity")
            continue
        shared = str(source_bones[current].name)
        if shared != name:
            substituted.append(f"{name}->{shared}")
        target_palette[slot] = target_by_name[shared]
        transforms[slot] = np.linalg.inv(source_binds[current]) @ target_binds[target_by_name[shared]]
    return transforms, target_palette, tuple(substituted)


def appearance_transforms(palette: Sequence[int], skin_matrices: Sequence[Sequence[float]]) -> tuple[np.ndarray, np.ndarray]:
    """Per-slot appearance transforms and which slots have one."""
    matrices = np.asarray([tuple(matrix) for matrix in skin_matrices], dtype=np.float64).reshape(-1, 4, 4)
    bones = np.asarray(palette, dtype=np.int64).reshape(-1)
    valid = (bones >= 0) & (bones < len(matrices))
    transforms = np.tile(np.eye(4), (len(bones), 1, 1))
    transforms[valid] = matrices[bones[valid]]
    return transforms, valid


def skin_retarget(
    vertices: Sequence[Sequence[float]],
    bone_indices: Sequence[Sequence[int]],
    bone_weights: Sequence[Sequence[float]],
    transforms: np.ndarray,
    slot_valid: np.ndarray | None = None,
) -> np.ndarray:
    """Linear blend skinning of ``vertices`` with per-palette-slot ``transforms``.

    Rows may have any number of influences. As in the editor's appearance
    skinning, influences without a transform are dropped and the rest
    renormalised; a vertex left with none keeps its position.
    """
    points = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    if not len(bone_indices) or len(bone_indices) != len(points) or len(bone_weights) != len(points):
        return points.copy()
    width = max((len(row) for row in bone_indices), default=0)
    if width == 0:
        return points.copy()
    slots = np.full((len(points), width), -1, dtype=np.int64)
    weights = np.zeros((len(points), width), dtype=np.float64)
    for row, (indices, values) in enumerate(zip(bone_indices, bone_weights)):
        if len(indices) != len(values):
            continue
        slots[row, :len(indices)] = indices
        weights[row, :len(values)] = values
    valid = (slots >= 0) & (slots < len(transforms))
    if slot_valid is not None:
        valid &= np.asarray(slot_valid, dtype=bool)[np.clip(slots, 0, len(transforms) - 1)]
    weights = np.where(valid & np.isfinite(weights) & (weights > 0.0), weights, 0.0)
    totals = weights.sum(axis=1, keepdims=True)
    weights = np.divide(weights, totals, out=np.zeros_like(weights), where=totals > 0.0)
    homogeneous = np.c_[points, np.ones(len(points))]
    moved = np.zeros_like(homogeneous)
    for lane in range(width):
        lane_transforms = transforms[np.where(valid[:, lane], slots[:, lane], 0)]
        moved += weights[:, lane:lane + 1] * np.einsum("ni,nij->nj", homogeneous, lane_transforms)
    unweighted = totals[:, 0] <= 0.0
    moved[unweighted] = homogeneous[unweighted]
    return moved[:, :3]


def retarget_reference_body(
    submeshes: Iterable[object],
    palette: Sequence[int],
    source_skeleton: object,
    target_skeleton: object,
    *,
    label: str = "",
    source_appearance: Sequence[Sequence[float]] | None = None,
    target_appearance: Sequence[Sequence[float]] | None = None,
) -> RefitReferenceBody:
    """Concatenate a body's Parts and retarget them into the target bind pose.

    ``source_appearance`` and ``target_appearance`` are per-bone skin matrices
    of the garment's and the driver's skeletons, when the session shows those
    Parts in a character appearance.
    """
    transforms, target_palette, substituted = retarget_transforms(palette, source_skeleton, target_skeleton)
    source_pose = appearance_transforms(palette, source_appearance) if source_appearance is not None else None
    target_pose = appearance_transforms(target_palette, target_appearance) if target_appearance is not None else None
    sources, fitted, faces = [], [], []
    offset = 0
    for part in submeshes:
        vertices = np.asarray(part.vertices, dtype=np.float64).reshape(-1, 3)
        part_faces = np.asarray(part.faces, dtype=np.int64).reshape(-1, 3)
        if not len(vertices) or not len(part_faces):
            continue
        weights = (part.bone_indices, part.bone_weights)
        moved = skin_retarget(vertices, *weights, transforms)
        sources.append(skin_retarget(vertices, *weights, *source_pose) if source_pose is not None else vertices)
        fitted.append(skin_retarget(moved, *weights, *target_pose) if target_pose is not None else moved)
        faces.append(part_faces + offset)
        offset += len(vertices)
    if not faces:
        raise ValueError("The reference body has no surface to fit against.")
    return RefitReferenceBody(
        label=str(label),
        source_positions=np.concatenate(sources),
        fitted_positions=np.concatenate(fitted),
        faces=np.concatenate(faces),
        substituted_bones=substituted,
    )


__all__ = [
    "RefitReferenceBody",
    "appearance_transforms",
    "bind_matrices",
    "retarget_reference_body",
    "retarget_transforms",
    "skin_retarget",
]
