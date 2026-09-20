"""Validated PAB/PABC pose input for the decoded bone-jiggle reference.

These functions assemble a full reference LOD0 rig in PAC model coordinates.
They do not recover game buffer allocation, select a live profile, sample a
game animation, or infer solver activation.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import struct

from .pac_jiggle_bones import step_jiggle_bone
from .pac_jiggle_skinning import prepare_jiggle_bone_skinning
from .skeleton_variation_parser import _invert_affine, _matrix4, _matrix_multiply


_IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


@dataclass(frozen=True, slots=True)
class JiggleRig:
    """Immutable snapshot; all indices are original PAB ordinals, not PAC slots.

    Global/local matrices describe the neutral display pose. Original inverse
    binds remain in the source PAC frame even when a PABC changes that pose.
    Matrix storage is flat, row-major, with translation at elements 12..14.
    """

    bone_palette: tuple[int, ...]
    parents: tuple[int, ...]
    order: tuple[int, ...]
    inverse_bind_matrices: tuple[tuple[float, ...], ...]
    neutral_global_matrices: tuple[tuple[float, ...], ...]
    neutral_local_matrices: tuple[tuple[float, ...], ...]


def _affine(values):
    result = _matrix4(values)
    if result[3::4] != (0., 0., 0., 1.):
        raise ValueError("Jiggle rig matrices must be row-major affine transforms.")
    inverse = _invert_affine(result)
    if any(not math.isfinite(value) for value in inverse):
        raise ValueError("Jiggle rig matrix inverse must be finite.")
    return result


def _require_near(actual, expected, label):
    # Consistency tolerance for independently stored float32 matrices, not a
    # recovered game constant. Do not silently replace inconsistent source data.
    if any(not math.isfinite(a) or abs(a - b) > 2e-5 * (1 + abs(a) + abs(b))
           for a, b in zip(actual, expected, strict=True)):
        raise ValueError(f"Jiggle rig has inconsistent {label}.")


def _bone_index(value, count):
    if type(value) is not int or not 0 <= value < count:
        raise ValueError("Jiggle rig refers to a missing original bone index.")
    return value


def prepare_jiggle_rig(skeleton, bone_palette: Sequence[int], *, appearance=None) -> JiggleRig:
    """Use a fixed-layout skeleton and an already resolved matching PAC palette.

    The caller resolves the palette with resolve_pac_bone_palette; slot numbers
    are never treated as bone numbers. No heuristic-scan rig, missing local
    matrix, identity substitution, invalid hierarchy or partial rig is accepted.
    PABC input is the editor's existing NeutralMeshAppearance, whose transforms
    already include its neutral-axis reconciliation. It must use this palette
    and contain one skin matrix per original bone.
    """
    bones = tuple(skeleton.bones)
    count = len(bones)
    if (skeleton.parser_mode != 'fixed' or not 0 < count <= 4096
            or skeleton.bone_count != count):
        raise ValueError("Jiggle needs a complete fixed-layout PAB within 4096 bones.")
    palette = tuple(_bone_index(index, count) for index in bone_palette)
    if not palette:
        raise ValueError("Jiggle needs a resolved PAC bone palette.")
    parents, children, roots = [], [[] for _ in bones], []
    globals_, inverses, locals_ = [], [], []
    for index, bone in enumerate(bones):
        if type(bone.index) is not int or bone.index != index:
            raise ValueError("Jiggle needs the original ordered PAB bone indices.")
        parent = bone.parent_index
        if type(parent) is not int or parent < -1 or parent >= count or parent == index:
            raise ValueError("Jiggle rig has an invalid parent index.")
        parents.append(parent)
        (roots if parent == -1 else children[parent]).append(index)
        bind, inverse = _affine(bone.bind_matrix), _affine(bone.inv_bind_matrix)
        local, local_inverse = _affine(bone.local_bind_matrix), _affine(bone.inv_local_bind_matrix)
        for left, right, label in ((bind, inverse, 'global inverse bind'),
                                   (local, local_inverse, 'local inverse bind')):
            _require_near(_matrix_multiply(left, right), _IDENTITY, label)
            _require_near(_matrix_multiply(right, left), _IDENTITY, label)
        globals_.append(bind)
        inverses.append(inverse)
        locals_.append(local)
    queue, order = deque(roots), []
    while queue:
        index = queue.popleft()
        order.append(index)
        queue.extend(children[index])
    if len(order) != count:
        raise ValueError("Jiggle rig hierarchy contains a cycle.")
    for index, parent in enumerate(parents):
        expected = locals_[index] if parent == -1 else _matrix_multiply(locals_[index], globals_[parent])
        _require_near(expected, globals_[index], 'local-to-parent bind')
    if appearance is not None:
        if tuple(appearance.bone_palette) != palette or len(appearance.skin_matrices) != count:
            raise ValueError("Neutral appearance does not match the jiggle rig and palette.")
        globals_ = [_affine(_matrix_multiply(bind, _affine(skin)))
                    for bind, skin in zip(globals_, appearance.skin_matrices, strict=True)]
        neutral_inverses = [_invert_affine(pose) for pose in globals_]
        locals_ = [_affine(pose if parent == -1 else _matrix_multiply(pose, neutral_inverses[parent]))
                   for pose, parent in zip(globals_, parents, strict=True)]
    return JiggleRig(palette, tuple(parents), tuple(order), tuple(inverses), tuple(globals_), tuple(locals_))


def compose_jiggle_pose(
    rig: JiggleRig, local_pose_overrides: Mapping[int, Sequence[float]] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Compose supplied absolute local poses and their descendants, in rig order.

    Keys are original bone ordinals. Values replace a local matrix; they are not
    Euler deltas or world transforms. Untouched branches retain their stored
    global pose exactly, avoiding rest-pose drift from repeated reconstruction.
    This assembles animation targets before jiggle: simulated parents must not
    be fed back into child targets. Root/world motion is supplied separately to
    step_jiggle_rig through CharacterTransformData.
    """
    overrides = {} if local_pose_overrides is None else {
        _bone_index(index, len(rig.parents)): _affine(pose)
        for index, pose in local_pose_overrides.items()
    }
    result = list(rig.neutral_global_matrices)
    changed = [False] * len(rig.parents)
    for index in rig.order:
        parent = rig.parents[index]
        local = overrides.get(index, rig.neutral_local_matrices[index])
        changed[index] = local != rig.neutral_local_matrices[index] or (parent != -1 and changed[parent])
        if changed[index]:
            result[index] = _affine(local if parent == -1 else _matrix_multiply(local, result[parent]))
    return tuple(result)


def _rows(flat):
    return tuple(tuple(flat[i:i + 4]) for i in range(0, 16, 4))


def step_jiggle_rig(
    rig: JiggleRig, previous_bones: Sequence[bytes] | None, *,
    shader_data: bytes, character_transform: bytes,
    view_position: Sequence[float], previous_view_position: Sequence[float],
    bone_scale: float, character_space_scales: Sequence[Sequence[float]],
    update_frame_index: int, delta_time: float, reset_requested: bool,
    local_pose_overrides: Mapping[int, Sequence[float]] | None = None,
    commands: Mapping[int, bytes] | None = None,
) -> dict:
    """Advance a complete LOD0 rig and produce the two render skinning buffers.

    Settings, motion, activation/reset, scale and pending command records remain
    explicit caller inputs. Missing commands mean no new command, not cancellation
    of an existing effect. Feed bone_states back only for the same rig; use None
    when creating/replacing it. Buffer indices are original bone ordinals, so the
    render reference uses an identity skinning_index_map for these assembled
    buffers. This is not a claim that the game's allocated LOD0 map is identity.

    Output matrices deform source PAC coordinates. Already-neutral editor
    geometry must first be mapped back through its blended appearance transform;
    replacing original inverse binds with neutral inverses would change the skin.
    No cloth, wind sample generation or special cross-LOD correction is inferred.
    """
    count = len(rig.parents)
    if len(character_space_scales) != count or (previous_bones is not None and len(previous_bones) != count):
        raise ValueError("Jiggle rig state and character-space scales must cover every bone.")
    pending = {} if commands is None else {
        _bone_index(index, count): value for index, value in commands.items()
    }
    poses = compose_jiggle_pose(rig, local_pose_overrides)
    states, skeletal, simulated, resets = [], [], [], []
    for index, pose in enumerate(poses):
        try:
            animation = struct.pack('<16f', *pose)
        except (OverflowError, struct.error) as exc:
            raise ValueError("Jiggle animation pose exceeds float32 storage.") from exc
        result = step_jiggle_bone(
            None if previous_bones is None else previous_bones[index],
            command_bone=pending.get(index, bytes(116)), shader_data=shader_data,
            animation_matrix=animation, character_transform=character_transform,
            view_position=view_position, previous_view_position=previous_view_position,
            bone_scale=bone_scale, original_bone_index=index, update_frame_index=update_frame_index,
            delta_time=delta_time, reset_requested=reset_requested)
        prepared = prepare_jiggle_bone_skinning(
            inverse_bind_matrix=_rows(rig.inverse_bind_matrices[index]),
            animation_matrix=_rows(struct.unpack('<16f', animation)), jiggle_matrix=result['matrix'],
            character_space_scale=character_space_scales[index])
        states.append(result['bone'])
        skeletal.append(prepared['skeletal_matrix'])
        simulated.append(prepared['jiggle_matrix'])
        if result['reset']:
            resets.append(index)
    return {'bone_states': tuple(states), 'skeletal_matrices': tuple(skeletal),
            'jiggle_matrices': tuple(simulated), 'reset_bones': tuple(resets)}
