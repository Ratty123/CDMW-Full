"""Synchronized character/attachment sampling without modifying source clips."""
from __future__ import annotations
import math

from tools.paa_motion.format import FPS
from tools.paa_motion.pose import (Transform, local_transforms, matrix_of, matrix_multiply,
                                   quat_slerp, world_matrices)
from tools.paa_motion.timing import duration_seconds

from .motionblending import BlendError


def blend_matrices(skeleton, samples):
    """Blend local transforms, then reconstruct the hierarchy once."""
    samples = [(clip, seconds, weight) for clip, seconds, weight in samples if weight > 0]
    if not samples:
        raise BlendError('No playable contributing clips')
    locals_by_clip = [(local_transforms(skeleton, clip, seconds * FPS), weight) for clip, seconds, weight in samples]
    total = sum(w for _, w in locals_by_clip)
    world = []
    for index, bone in enumerate(skeleton.bones):
        translation = tuple(sum(rows[index].translation[k] * w for rows, w in locals_by_clip) / total for k in range(3))
        scale = tuple(sum(rows[index].scale[k] * w for rows, w in locals_by_clip) / total for k in range(3))
        rotation, accumulated = locals_by_clip[0][0][index].rotation, locals_by_clip[0][1]
        for rows, weight in locals_by_clip[1:]:
            rotation = quat_slerp(rotation, rows[index].rotation, weight / (accumulated + weight))
            accumulated += weight
        local = matrix_of(Transform(translation, rotation, scale))
        world.append(matrix_multiply(local, world[bone.parent_index]) if 0 <= bone.parent_index < index else local)
    return world


def space_duration(space, clips, parameters, *, scale=1., weights=None):
    contributions = space.contributions(parameters) if weights is None else space.contributions_for_weights(weights)
    missing = [path for path, _ in contributions if path not in clips]
    if missing:
        raise BlendError('Missing blend clips: ' + ', '.join(missing))
    if not math.isfinite(scale) or scale <= 0:
        raise BlendError('Invalid playback scale')
    return sum(duration_seconds(clips[path]) * weight for path, weight in contributions) / scale


def samples_for_space(space, clips, parameters, seconds, *, replacements=None, looping=True, scale=1., weights=None):
    replacements = replacements or {}
    contributions = space.contributions(parameters) if weights is None else space.contributions_for_weights(weights)
    resolved = [(path, clips.get(replacements.get(path, path)), weight) for path, weight in contributions]
    missing = [path for path, clip, _ in resolved if clip is None]
    if missing:
        raise BlendError('Missing blend clips: ' + ', '.join(missing))
    end = sum(duration_seconds(clip) * weight for _, clip, weight in resolved)
    clock = seconds * scale
    phase = (clock % end if looping else min(clock, end)) / end if end > 0 else 0.
    samples, notes = [], []
    for path, clip, weight in resolved:
        duration = duration_seconds(clip)
        try:
            when = space.phase_seconds(space.clips.index(path), phase, duration)
        except BlendError:
            when = min(clock % duration if looping and duration else clock, duration)
            notes.append('Phase synchronization: Unverified; using the common seconds clock')
        samples.append((clip, when, weight))
    return samples, contributions, tuple(dict.fromkeys(notes))


def apply_space(session, space, clips, parameters, seconds, **settings):
    from .playback import posed_hierarchy
    samples, contributions, notes = samples_for_space(space, clips, parameters, seconds, **settings)
    if session._bind_hierarchy is None:
        session._bind_hierarchy = session.hierarchy
    hierarchy = session._bind_hierarchy
    matrices = blend_matrices(hierarchy.parsed, samples)
    session.pose_matrices = matrices
    session.hierarchy = posed_hierarchy(hierarchy, samples[0][0], 0, matrices=matrices)
    session._reposition()
    return contributions, notes


def attachment_points(binding, clip, seconds, matrix, *, looping=True):
    from .skinning import skin_matrices, deform
    import numpy as np
    duration = duration_seconds(clip)
    when = seconds % duration if looping and duration > 0 else min(seconds, duration)
    world = world_matrices(binding.skeleton, clip, when * FPS)
    points = deform(binding.mesh, skin_matrices(binding.skeleton, world))
    homogeneous = np.column_stack((points, np.ones(len(points))))
    return (homogeneous @ np.asarray(matrix).reshape(4, 4))[:, :3]
