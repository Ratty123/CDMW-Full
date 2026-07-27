"""Compose `.paa` track deltas onto a `.pab` bind pose.

A clip does not store a bone's local transform; it stores the delta from the bind pose, in
the bone's own local axes. So the animated local transform is

    M_local = M_delta . M_bind_local

in the row-vector convention the `.pab` uses. Written as a quaternion that is
`q_bind * q_delta` — the delta applies first — and as a translation it is the bind
translation plus the delta rotated into the parent frame by the bind rotation. That last
part is what makes `Bip01` and `B_MoveControl_01` agree on how far a run clip travels
despite their bind rotations differing by 90 degrees; get it wrong and root motion goes
sideways.

Everything this module returns is in the column-vector convention a 3D format expects:
`rotate(q, v)` moves `v`, and `q_a * q_b` applies `b` first.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from .format import Key, MotionClip

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # x, y, z, w

IDENTITY_QUAT: Quat = (0.0, 0.0, 0.0, 1.0)
UNIT_SCALE: Vec3 = (1.0, 1.0, 1.0)


def quat_multiply(a: Quat, b: Quat) -> Quat:
    """Hamilton product: the result applies `b` first, then `a`."""

    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    """Rotate `v` by `q`."""

    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * (q.xyz X v); v' = v + w*t + q.xyz X t
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + y * tz - z * ty,
        vy + w * ty + z * tx - x * tz,
        vz + w * tz + x * ty - y * tx,
    )


def quat_normalize(q: Quat) -> Quat:
    length = math.sqrt(sum(c * c for c in q))
    if length == 0.0:
        return IDENTITY_QUAT
    return (q[0] / length, q[1] / length, q[2] / length, q[3] / length)


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:  # take the short way round
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(tuple(x + (y - x) * t for x, y in zip(a, b)))  # type: ignore[arg-type]
    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    wa = math.sin((1.0 - t) * theta) / sin_theta
    wb = math.sin(t * theta) / sin_theta
    return quat_normalize(tuple(x * wa + y * wb for x, y in zip(a, b)))  # type: ignore[arg-type]


def _bracket(keys: Sequence[Key], frame: float) -> tuple[Key, Key, float]:
    """The two keys `frame` falls between, and how far between them it lies."""

    frames = [key[0] for key in keys]
    index = bisect_right(frames, frame) - 1
    if index < 0:
        return keys[0], keys[0], 0.0
    if index >= len(keys) - 1:
        return keys[-1], keys[-1], 0.0
    left, right = keys[index], keys[index + 1]
    span = right[0] - left[0]
    return left, right, (frame - left[0]) / span if span else 0.0


def _lerp_vector(keys: Sequence[Key], frame: float, default: Vec3) -> Vec3:
    if not keys:
        return default
    left, right, t = _bracket(keys, frame)
    if t == 0.0:
        return tuple(left[1][:3])  # type: ignore[return-value]
    return tuple(a + (b - a) * t for a, b in zip(left[1][:3], right[1][:3]))  # type: ignore[return-value]


def _slerp_quat(keys: Sequence[Key], frame: float) -> Quat:
    if not keys:
        return IDENTITY_QUAT
    left, right, t = _bracket(keys, frame)
    if t == 0.0:
        return quat_normalize(tuple(left[1][:4]))  # type: ignore[arg-type]
    return quat_slerp(
        quat_normalize(tuple(left[1][:4])),  # type: ignore[arg-type]
        quat_normalize(tuple(right[1][:4])),  # type: ignore[arg-type]
        t,
    )


@dataclass(frozen=True)
class Transform:
    """A local transform in the column-vector convention: apply scale, rotation, translation."""

    translation: Vec3 = (0.0, 0.0, 0.0)
    rotation: Quat = IDENTITY_QUAT
    scale: Vec3 = UNIT_SCALE


def sample_delta(clip: MotionClip, name_hash: int, frame: float) -> Transform | None:
    """The clip's delta for one bone, or None when the clip does not animate it."""

    track = clip.track_for(name_hash)
    if track is None or not track.animated:
        return None
    return Transform(
        translation=_lerp_vector(track.translation, frame, (0.0, 0.0, 0.0)),
        rotation=_slerp_quat(track.rotation, frame),
        scale=_lerp_vector(track.scale, frame, UNIT_SCALE),
    )


def sample_delta_channel(track, channel: str, frame: float) -> Transform:
    """One channel's delta at `frame`, with the other two left identity.

    `compose` reads each output channel from a disjoint part of the input, so a delta built
    this way composes correctly for the channel asked for.
    """

    keys = getattr(track, channel)
    if channel == "rotation":
        return Transform(rotation=_slerp_quat(keys, frame))
    default = UNIT_SCALE if channel == "scale" else (0.0, 0.0, 0.0)
    return Transform(**{channel: _lerp_vector(keys, frame, default)})


def compose(bind: Transform, delta: Transform) -> Transform:
    """Apply a clip delta on top of a bind-pose local transform."""

    return Transform(
        translation=tuple(  # type: ignore[arg-type]
            b + r * s
            for b, r, s in zip(
                bind.translation,
                quat_rotate(bind.rotation, delta.translation),
                bind.scale,
            )
        ),
        rotation=quat_normalize(quat_multiply(bind.rotation, delta.rotation)),
        scale=tuple(b * d for b, d in zip(bind.scale, delta.scale)),  # type: ignore[arg-type]
    )


def bind_transform(bone) -> Transform:
    """The bind-pose local transform a `cdmw.modding.skeleton_parser.Bone` records."""

    return Transform(
        translation=tuple(bone.position),  # type: ignore[arg-type]
        rotation=quat_normalize(tuple(bone.rotation)),  # type: ignore[arg-type]
        scale=tuple(bone.scale),  # type: ignore[arg-type]
    )


def local_transforms(skeleton, clip: MotionClip, frame: float) -> list[Transform]:
    """Every bone's animated local transform at `frame`, in skeleton order."""

    out: list[Transform] = []
    for bone in skeleton.bones:
        bind = bind_transform(bone)
        delta = sample_delta(clip, bone.name_hash, frame)
        out.append(bind if delta is None else compose(bind, delta))
    return out


def world_positions(skeleton, clip: MotionClip, frame: float) -> list[Vec3]:
    """Every bone's world-space origin at `frame` — the cheapest way to eyeball a pose."""

    locals_ = local_transforms(skeleton, clip, frame)
    positions: list[Vec3] = [(0.0, 0.0, 0.0)] * len(skeleton.bones)
    rotations: list[Quat] = [IDENTITY_QUAT] * len(skeleton.bones)
    scales: list[Vec3] = [UNIT_SCALE] * len(skeleton.bones)
    for index, bone in enumerate(skeleton.bones):
        local = locals_[index]
        parent = bone.parent_index
        if parent < 0 or parent >= index:
            positions[index] = local.translation
            rotations[index] = local.rotation
            scales[index] = local.scale
            continue
        offset = quat_rotate(
            rotations[parent],
            tuple(t * s for t, s in zip(local.translation, scales[parent])),  # type: ignore[arg-type]
        )
        positions[index] = tuple(p + o for p, o in zip(positions[parent], offset))  # type: ignore[assignment]
        rotations[index] = quat_normalize(quat_multiply(rotations[parent], local.rotation))
        scales[index] = tuple(p * l for p, l in zip(scales[parent], local.scale))  # type: ignore[assignment]
    return positions


# 16 floats, row-major, row-vector convention: a point is a row and `point * matrix`
# transforms it, with the translation in row 3. Same layout the `.pab` stores, so a matrix
# from here can be dropped straight into anything that consumes a bind matrix.
Matrix = Tuple[float, ...]

IDENTITY_MATRIX: Matrix = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def matrix_of(transform: Transform) -> Matrix:
    """Scale, then rotate, then translate."""

    x, y, z, w = transform.rotation
    sx, sy, sz = transform.scale
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        sx * (1.0 - 2.0 * (yy + zz)), sx * (2.0 * (xy + wz)), sx * (2.0 * (xz - wy)), 0.0,
        sy * (2.0 * (xy - wz)), sy * (1.0 - 2.0 * (xx + zz)), sy * (2.0 * (yz + wx)), 0.0,
        sz * (2.0 * (xz + wy)), sz * (2.0 * (yz - wx)), sz * (1.0 - 2.0 * (xx + yy)), 0.0,
        transform.translation[0], transform.translation[1], transform.translation[2], 1.0,
    )


def matrix_multiply(a: Matrix, b: Matrix) -> Matrix:
    """Row-major multiply: the result applies `a` first, then `b`.

    Unrolled, and affine: the last column of a bone transform is always (0, 0, 0, 1), so the
    twelve terms that would compute it are skipped. The generic triple loop cost 434 bones x
    256 multiplies a frame and was the largest non-drawing cost in playback.
    """

    a0, a1, a2, _a3, a4, a5, a6, _a7, a8, a9, a10, _a11, a12, a13, a14, _a15 = a
    b0, b1, b2, _b3, b4, b5, b6, _b7, b8, b9, b10, _b11, b12, b13, b14, _b15 = b
    return (
        a0 * b0 + a1 * b4 + a2 * b8, a0 * b1 + a1 * b5 + a2 * b9, a0 * b2 + a1 * b6 + a2 * b10, 0.0,
        a4 * b0 + a5 * b4 + a6 * b8, a4 * b1 + a5 * b5 + a6 * b9, a4 * b2 + a5 * b6 + a6 * b10, 0.0,
        a8 * b0 + a9 * b4 + a10 * b8, a8 * b1 + a9 * b5 + a10 * b9,
        a8 * b2 + a9 * b6 + a10 * b10, 0.0,
        a12 * b0 + a13 * b4 + a14 * b8 + b12,
        a12 * b1 + a13 * b5 + a14 * b9 + b13,
        a12 * b2 + a13 * b6 + a14 * b10 + b14,
        1.0,
    )


def world_matrices(skeleton, clip: MotionClip, frame: float) -> list[Matrix]:
    """Every bone's animated world matrix at `frame`, in skeleton order.

    Drop-in for a bind matrix: anything that composes an offset onto a bone's world
    transform — a socket, an attachment marker — follows the animation for free.
    """

    locals_ = local_transforms(skeleton, clip, frame)
    world: list[Matrix] = [IDENTITY_MATRIX] * len(skeleton.bones)
    for index, bone in enumerate(skeleton.bones):
        local = matrix_of(locals_[index])
        parent = bone.parent_index
        # Bones are stored parents-first; a forward reference would mean an unresolved
        # parent, and treating it as a root beats indexing into a matrix not yet built.
        if 0 <= parent < index:
            world[index] = matrix_multiply(local, world[parent])
        else:
            world[index] = local
    return world


def animated_frames(clip: MotionClip, name_hash: int) -> Tuple[int, ...]:
    """The union of a bone's key frames, which is where a baked export needs samples."""

    track = clip.track_for(name_hash)
    if track is None:
        return ()
    frames: set[int] = set()
    for keys in (track.scale, track.rotation, track.translation):
        frames.update(frame for frame, _values in keys)
    return tuple(sorted(frames))


def iter_animated(skeleton, clip: MotionClip) -> Iterable[tuple[int, object]]:
    """(bone index, bone) for every skeleton bone this clip actually animates."""

    animated = {track.name_hash for track in clip.tracks if track.animated}
    for index, bone in enumerate(skeleton.bones):
        if bone.name_hash in animated:
            yield index, bone
