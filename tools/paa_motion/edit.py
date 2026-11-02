"""Edit `.paa` motion clips: non-destructive layers over a base clip, baked on demand.

An edit never touches the base clip. It records what the animator asked for -- retime it,
borrow the upper body from another clip, mirror it, push the right hand up a few degrees
between two frames -- and `render` bakes that into a new `MotionClip`, which `encode_paa`
writes. Re-render after every change and the result is always the base plus the current
layers, so nothing an animator undoes leaves residue.

Order of operations, the order an animator reads them in:

1. **Timing.** Every output frame maps to a time on the base clip: trim, speed, reverse,
   then hold the last pose.
2. **Splices.** Bones in a splice's mask blend toward another clip's pose at that time,
   so a one-hand draw can take the two-hand draw's arms and keep its own legs.
3. **Joins.** Other clips play after this one, each faded in over its blend time. Root
   travel and heading carry on from where the clip before stops (see `Join`).
4. **Mirror.** Left and right swap, solved in world space so it is right whatever local
   axes the rig gives each side (see `_Mirror`).
5. **Pose keys.** Offsets keyed on the output timeline, in each bone's own axes, applied on
   top of whatever the clip does there. Between keys they ease; outside them they hold.
6. **Root motion.** Horizontal travel of the root bones scaled, or removed to play in place.
7. **Reach.** A hand or foot moved to a keyed point, or held where it is, with the arm or
   leg bent to get it there (two-bone IK, `_solve_limb`). Last, so a planted foot stays
   planted whatever the layers above did.

A bone no layer touches keeps its original track byte for byte, so an edit with no layers
renders to a clip that encodes to the original file. Everything that is touched is sampled
at every 30 Hz frame and then thinned (`reduce_keys`) back to the keys that matter.

Distance (LOD) copies use a lossy byte codec on their own clock and are not edited; edit
the full clip instead.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from .format import FLAG_PACKED, FPS, BoneTrack, Key, MotionClip
from .pose import (
    IDENTITY_QUAT,
    UNIT_SCALE,
    Matrix,
    Quat,
    Transform,
    Vec3,
    bind_transform,
    compose,
    matrix_multiply,
    matrix_of,
    quat_multiply,
    quat_normalize,
    quat_rotate,
    quat_slerp,
    sample_delta_seconds,
)
from .timing import duration_seconds

#: How far a thinned channel may stray from the baked one. A twentieth of a degree and a
#: tenth of a millimetre are below what half precision stores for most bones anyway.
ROTATION_TOLERANCE_DEGREES = 0.05
TRANSLATION_TOLERANCE = 0.0001
SCALE_TOLERANCE = 0.0001


class EditError(ValueError):
    """Raised when an edit cannot be rendered onto its base clip."""


# ── the edit ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PoseKey:
    """An offset for one bone at one frame of the edited clip."""

    frame: int
    #: In the bone's own axes, applied after the clip's own rotation for that bone.
    rotation: Quat = IDENTITY_QUAT
    #: In the bone's own axes, metres.
    translation: Vec3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class PoseTrack:
    name_hash: int
    keys: Tuple[PoseKey, ...] = ()
    #: Ease in and out between keys rather than moving at a constant rate.
    smooth: bool = True


@dataclass(frozen=True)
class Splice:
    """Bones that take another clip's pose, blended in by `weight`."""

    source: MotionClip
    bones: FrozenSet[int]
    weight: float = 1.0
    label: str = ""
    #: Stretch the source over the edited clip's length instead of playing it in step.
    fit_length: bool = False


@dataclass(frozen=True)
class ReachKey:
    """Where a hand or foot reaches at one frame of the edited clip."""

    frame: int
    #: Metres, in the clip's own axes (the ones root motion is expressed in); see
    #: `character_axes` for which way is left and forward on a given rig.
    offset: Vec3 = (0.0, 0.0, 0.0)
    #: Hold the hand or foot where the clip has it at this key's frame, rather than letting
    #: it follow the clip. Pinned keys in a row plant it where the first of them has it; an
    #: unpinned key after them lets it go again.
    pinned: bool = False
    #: 0 leaves the limb as the clip has it, 1 reaches all the way.
    weight: float = 1.0


@dataclass(frozen=True)
class ReachTrack:
    #: The hand or foot, by the hash its clip track is keyed with.
    end: int
    keys: Tuple[ReachKey, ...] = ()
    #: Keep the hand or foot at the angle the clip gives it while the arm or leg moves.
    keep_angle: bool = True
    smooth: bool = True


@dataclass(frozen=True)
class Join:
    """Another clip played after this one, faded in over `blend` seconds.

    The fade starts `blend` seconds before the clip before it ends, so the two overlap rather
    than one freezing while the other starts. Root travel and heading carry on from where the
    clip before has got to, so a draw joined to a walk walks on from where the draw stood
    instead of snapping back to the walk's own start.
    """

    source: MotionClip
    blend: float = 0.25
    label: str = ""


@dataclass(frozen=True)
class ClipEdit:
    base: MotionClip
    speed: float = 1.0
    #: Seconds into the base clip where the edited clip starts and stops.
    trim_start: float = 0.0
    trim_end: Optional[float] = None
    reverse: bool = False
    #: Seconds the final pose is held after the motion ends.
    hold_end: float = 0.0
    #: Scales how far the root bones travel horizontally; 0 is in place.
    root_distance: float = 1.0
    mirror: bool = False
    splices: Tuple[Splice, ...] = ()
    pose: Tuple[PoseTrack, ...] = ()
    reach: Tuple[ReachTrack, ...] = ()
    joins: Tuple[Join, ...] = ()

    @cached_property
    def base_length(self) -> float:
        # Cached: `duration_seconds` validates every track's timing, and `base_seconds` (so
        # `span`, so this) runs once per frame per bone in a render. Uncached, a 10 s clip on a
        # 448-bone rig took 17 s to retime, nearly all of it re-validating the same clip.
        return duration_seconds(self.base)

    @property
    def span(self) -> Tuple[float, float]:
        """The part of the base clip that plays, in base seconds."""

        length = self.base_length
        start = min(max(0.0, self.trim_start), length)
        end = length if self.trim_end is None else min(max(start, self.trim_end), length)
        return start, end

    @property
    def retimed(self) -> bool:
        start, end = self.span
        return (abs(self.speed - 1.0) > 1e-9 or start > 1e-9 or end < self.base_length - 1e-9
                or self.reverse or self.hold_end > 1e-9)

    @property
    def is_identity(self) -> bool:
        return not (self.retimed or self.mirror or self.splices or self.pose or self.reach
                    or self.joins or abs(self.root_distance - 1.0) > 1e-9)

    @property
    def motion_seconds(self) -> float:
        start, end = self.span
        return (end - start) / max(self.speed, 1e-6)

    @property
    def own_seconds(self) -> float:
        """The base clip's part of the timeline: its motion, then the held end."""

        return self.motion_seconds + max(0.0, self.hold_end)

    def join_spans(self) -> List[Tuple[float, float, float]]:
        """`(start, length, blend)` of every joined clip, in seconds of the edited clip."""

        return list(self._spans)

    @cached_property
    def _spans(self) -> Tuple[Tuple[float, float, float], ...]:
        spans = []
        end = room = self.own_seconds
        for join in self.joins:
            length = duration_seconds(join.source)
            # A fade overlaps only the clip right before it, and only the part of that clip
            # after its own fade, so a long fade cannot reach back past the previous clip.
            blend = min(max(0.0, join.blend), room, length)
            start = end - blend
            spans.append((start, length, blend))
            end = start + length
            room = length - blend
        return tuple(spans)

    @property
    def duration(self) -> float:
        spans = self.join_spans()
        return spans[-1][0] + spans[-1][1] if spans else self.own_seconds

    @property
    def last_frame(self) -> int:
        return max(0, int(round(self.duration * FPS)))

    def base_seconds(self, frame: float) -> float:
        """Where output `frame` reads the base clip."""

        start, end = self.span
        elapsed = min(max(0.0, frame / FPS), self.motion_seconds) * self.speed
        return end - elapsed if self.reverse else start + elapsed

    # Small editing helpers, so the window never rebuilds tuples by hand.

    def pose_track(self, name_hash: int) -> Optional[PoseTrack]:
        return next((t for t in self.pose if t.name_hash == name_hash), None)

    def with_pose_key(self, name_hash: int, key: PoseKey) -> "ClipEdit":
        track = self.pose_track(name_hash) or PoseTrack(name_hash)
        keys = tuple(sorted([k for k in track.keys if k.frame != key.frame] + [key],
                            key=lambda k: k.frame))
        return self._with_pose(replace(track, keys=keys))

    def without_pose_key(self, name_hash: int, frame: int) -> "ClipEdit":
        track = self.pose_track(name_hash)
        if track is None:
            return self
        return self._with_pose(replace(track, keys=tuple(k for k in track.keys if k.frame != frame)))

    def _with_pose(self, track: PoseTrack) -> "ClipEdit":
        others = tuple(t for t in self.pose if t.name_hash != track.name_hash)
        return replace(self, pose=others + ((track,) if track.keys else ()))

    def reach_track(self, end: int) -> Optional[ReachTrack]:
        return next((t for t in self.reach if t.end == end), None)

    def with_reach_key(self, end: int, key: ReachKey) -> "ClipEdit":
        track = self.reach_track(end) or ReachTrack(end)
        keys = tuple(sorted([k for k in track.keys if k.frame != key.frame] + [key],
                            key=lambda k: k.frame))
        return self.with_reach(replace(track, keys=keys))

    def without_reach_key(self, end: int, frame: int) -> "ClipEdit":
        track = self.reach_track(end)
        if track is None:
            return self
        return self.with_reach(replace(track, keys=tuple(k for k in track.keys if k.frame != frame)))

    def with_reach(self, track: ReachTrack) -> "ClipEdit":
        """`track` in place of the one for its hand or foot; a track with no keys is dropped."""

        others = tuple(t for t in self.reach if t.end != track.end)
        return replace(self, reach=others + ((track,) if track.keys else ()))


# ── sampling the layers ──────────────────────────────────────────────


def _ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def pose_offset(track: PoseTrack, frame: float) -> Tuple[Quat, Vec3]:
    """The offset a pose track applies at `frame`: held outside its keys, eased between."""

    if not track.keys:
        return IDENTITY_QUAT, (0.0, 0.0, 0.0)
    left, right, t = _held(track.keys, frame, track.smooth)
    if right is left:
        return left.rotation, left.translation
    rotation = quat_slerp(quat_normalize(left.rotation), quat_normalize(right.rotation), t)
    translation = tuple(a + (b - a) * t for a, b in zip(left.translation, right.translation))
    return rotation, translation  # type: ignore[return-value]


def _held(keys, frame: float, smooth: bool):
    """The two keys around `frame` and how far between them it is, held outside them."""

    if frame <= keys[0].frame:
        return keys[0], keys[0], 0.0
    if frame >= keys[-1].frame:
        return keys[-1], keys[-1], 0.0
    for left, right in zip(keys, keys[1:]):
        if left.frame <= frame <= right.frame:
            span = right.frame - left.frame
            t = (frame - left.frame) / span if span else 0.0
            return left, right, _ease(t) if smooth else t
    return keys[-1], keys[-1], 0.0


def reach_target(track: ReachTrack, frame: int, here: Vec3, pinned_at,
                 turn: Quat = IDENTITY_QUAT) -> Tuple[Vec3, float]:
    """Where `track` wants its hand or foot at `frame`, and how strongly.

    `here` is where the clip puts it at `frame`; `pinned_at(frame)` where the clip puts it at
    another frame, for pinned keys. A run of pinned keys holds it where it is at the run's
    first key, so pinning frames 6 and 18 plants it for the twelve frames between rather than
    sliding it to where the clip has it at 18. Before a plant's first key the clip has it, so
    one Plant here at frame 30 does not drag frames 0-29 to where the foot is at 30.

    Offsets are stored in the character's own directions and turned by `turn`, the way the
    character faces at `frame`, so Ahead stays ahead through a turn.
    """

    if track.keys and track.keys[0].pinned and frame < track.keys[0].frame:
        return here, 1.0

    origins: Dict[int, int] = {}
    run_start: Optional[int] = None
    for key in track.keys:
        run_start = (key.frame if run_start is None else run_start) if key.pinned else None
        if run_start is not None:
            origins[key.frame] = run_start

    def point(key: ReachKey) -> Vec3:
        origin = pinned_at(origins.get(key.frame, key.frame)) if key.pinned else here
        offset = quat_rotate(turn, key.offset) if turn != IDENTITY_QUAT else key.offset
        return tuple(o + d for o, d in zip(origin, offset))  # type: ignore[return-value]

    left, right, t = _held(track.keys, frame, track.smooth)
    a = point(left)
    if right is left:
        return a, min(1.0, max(0.0, left.weight))
    b = point(right)
    weight = left.weight + (right.weight - left.weight) * t
    return tuple(x + (y - x) * t for x, y in zip(a, b)), min(1.0, max(0.0, weight))  # type: ignore[return-value]


def reach_offset(track: ReachTrack, frame: int) -> Tuple[Vec3, float, bool]:
    """The offset, strength and pinning `track` has at `frame`, for showing in controls."""

    if not track.keys:
        return (0.0, 0.0, 0.0), 1.0, False
    left, right, t = _held(track.keys, frame, track.smooth)
    if right is left:
        return left.offset, left.weight, left.pinned
    offset = tuple(a + (b - a) * t for a, b in zip(left.offset, right.offset))
    return offset, left.weight + (right.weight - left.weight) * t, left.pinned and right.pinned  # type: ignore[return-value]


def remap_keys(old: ClipEdit, new: ClipEdit) -> ClipEdit:
    """`new` with its pose and reach keys moved to where `old` had them in the motion.

    Keys live on the edited clip's frames. Change the speed, trim, direction, held end or
    joins, and a key on the moment the foot lands would otherwise stay on the same frame
    number, which is now a different moment, or past the end where nothing can reach it.
    Each key goes to the frame that plays the same moment of the base clip; keys in the held
    end or in a joined clip keep their distance from where those start. Nothing ends up past
    the new last frame.
    """

    old_motion, new_motion = old.motion_seconds * FPS, new.motion_seconds * FPS
    old_own, new_own = old.own_seconds * FPS, new.own_seconds * FPS
    start, end = new.span
    last = new.last_frame

    def moved(frame: int) -> int:
        if frame <= old_motion + 1e-6:
            at = old.base_seconds(frame)
            elapsed = (end - at) if new.reverse else (at - start)
            target = min(max(elapsed, 0.0), end - start) / max(new.speed, 1e-6) * FPS
        elif frame <= old_own + 1e-6:
            target = new_motion + (frame - old_motion)
        else:
            target = frame + (new_own - old_own)
        return int(min(max(round(target), 0), last))

    def keys_of(keys):
        out = {}
        for key in keys:
            out[moved(key.frame)] = replace(key, frame=moved(key.frame))
        return tuple(out[f] for f in sorted(out))

    pose = tuple(replace(t, keys=keys_of(t.keys)) for t in new.pose)
    reach = tuple(replace(t, keys=keys_of(t.keys)) for t in new.reach)
    if pose == new.pose and reach == new.reach:
        return new
    return replace(new, pose=pose, reach=reach)


def _blend(a: Transform, b: Transform, weight: float) -> Transform:
    if weight >= 1.0:
        return b
    if weight <= 0.0:
        return a
    return Transform(
        translation=tuple(x + (y - x) * weight for x, y in zip(a.translation, b.translation)),  # type: ignore[arg-type]
        rotation=quat_slerp(a.rotation, b.rotation, weight),
        scale=tuple(x + (y - x) * weight for x, y in zip(a.scale, b.scale)),  # type: ignore[arg-type]
    )


_IDENTITY = Transform()


def _delta(clip: MotionClip, name_hash: int, seconds: float) -> Transform:
    return sample_delta_seconds(clip, name_hash, seconds) or _IDENTITY


# ── matrices, for the mirror ─────────────────────────────────────────


def _inverse(m: Matrix) -> Matrix:
    """Inverse of an affine row-vector matrix."""

    a, b, c = m[0], m[1], m[2]
    d, e, f = m[4], m[5], m[6]
    g, h, i = m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise EditError("A bone transform cannot be inverted")
    inv = (
        (e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
        (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
        (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det,
    )
    tx, ty, tz = m[12], m[13], m[14]
    return (
        inv[0], inv[1], inv[2], 0.0,
        inv[3], inv[4], inv[5], 0.0,
        inv[6], inv[7], inv[8], 0.0,
        -(tx * inv[0] + ty * inv[3] + tz * inv[6]),
        -(tx * inv[1] + ty * inv[4] + tz * inv[7]),
        -(tx * inv[2] + ty * inv[5] + tz * inv[8]),
        1.0,
    )


def transform_of(m: Matrix) -> Transform:
    """Scale, rotation and translation back out of a `matrix_of` matrix."""

    rows = [(m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])]
    scale = tuple(math.sqrt(sum(v * v for v in row)) or 1.0 for row in rows)
    r = [tuple(v / s for v in row) for row, s in zip(rows, scale)]
    # `matrix_of` stores the column-vector rotation transposed, row i = axis i.
    m00, m01, m02 = r[0][0], r[1][0], r[2][0]
    m10, m11, m12 = r[0][1], r[1][1], r[2][1]
    m20, m21, m22 = r[0][2], r[1][2], r[2][2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        q = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        q = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        q = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
    return Transform(translation=(m[12], m[13], m[14]), rotation=quat_normalize(q), scale=scale)  # type: ignore[arg-type]


def decompose(bind: Transform, local: Transform) -> Transform:
    """The delta `compose(bind, delta)` turns into `local`: the inverse of `compose`."""

    conj = (-bind.rotation[0], -bind.rotation[1], -bind.rotation[2], bind.rotation[3])
    offset = tuple((t - b) / (s or 1.0) for t, b, s in zip(local.translation, bind.translation,
                                                          bind.scale))
    return Transform(
        translation=quat_rotate(conj, offset),  # type: ignore[arg-type]
        rotation=quat_normalize(quat_multiply(conj, local.rotation)),
        scale=tuple(v / (b or 1.0) for v, b in zip(local.scale, bind.scale)),  # type: ignore[arg-type]
    )


def _swap_side(token: str) -> str:
    return {"L": "R", "R": "L", "l": "r", "r": "l", "Left": "Right", "Right": "Left",
            "left": "right", "right": "left"}.get(token, token)


def mirror_partner_name(name: str) -> str:
    """`Bip01 L Hand` <-> `Bip01 R Hand`, `B_Ear_02_L` <-> `B_Ear_02_R`; else the name itself."""

    parts = re.split(r"([ _])", name)
    return "".join(_swap_side(part) for part in parts)


def mirror_partners(skeleton) -> Dict[int, int]:
    """Bone index -> its mirror partner's index; centre bones map to themselves."""

    by_name = {bone.name: bone.index for bone in skeleton.bones}
    return {bone.index: by_name.get(mirror_partner_name(bone.name), bone.index)
            for bone in skeleton.bones}


def mirror_axis(skeleton) -> int:
    """The world axis left and right differ along, read off the bind pose."""

    partners = mirror_partners(skeleton)
    bind_world = _bind_world(skeleton)
    spread = [0.0, 0.0, 0.0]
    for index, partner in partners.items():
        if partner == index:
            continue
        for axis in range(3):
            spread[axis] += abs(bind_world[index][12 + axis] - bind_world[partner][12 + axis])
    return max(range(3), key=lambda axis: spread[axis])


def _bind_world(skeleton) -> List[Matrix]:
    world: List[Matrix] = []
    for index, bone in enumerate(skeleton.bones):
        local = matrix_of(bind_transform(bone))
        parent = bone.parent_index
        world.append(matrix_multiply(local, world[parent]) if 0 <= parent < index else local)
    return world


def _reflect(m: Matrix, axis: int) -> Matrix:
    """S . m . S with S the reflection along `axis`: a mirrored, still right-handed frame."""

    sign = [1.0, 1.0, 1.0, 1.0]
    sign[axis] = -1.0
    return tuple(m[r * 4 + c] * sign[r] * sign[c] for r in range(4) for c in range(4))  # type: ignore[return-value]


class _Mirror:
    """Everything the mirror needs about one skeleton, worked out once per render."""

    def __init__(self, skeleton) -> None:
        self.skeleton = skeleton
        self.partners = mirror_partners(skeleton)
        self.axis = mirror_axis(skeleton)
        bind_world = _bind_world(skeleton)
        # Maps a mirrored partner frame onto this bone's own axis convention, so the bind
        # pose mirrors onto itself whatever local axes the rig gave each side.
        self.correction = [
            matrix_multiply(bind_world[index], _inverse(_reflect(bind_world[partner], self.axis)))
            for index, partner in self.partners.items()
        ]

    def frame(self, deltas: Sequence[Transform]) -> List[Transform]:
        bones = self.skeleton.bones
        world: List[Matrix] = []
        for index, bone in enumerate(bones):
            local = matrix_of(compose(bind_transform(bone), deltas[index]))
            parent = bone.parent_index
            world.append(matrix_multiply(local, world[parent]) if 0 <= parent < index else local)
        mirrored = [
            matrix_multiply(self.correction[index], _reflect(world[self.partners[index]], self.axis))
            for index in range(len(bones))
        ]
        out: List[Transform] = []
        for index, bone in enumerate(bones):
            parent = bone.parent_index
            local = (matrix_multiply(mirrored[index], _inverse(mirrored[parent]))
                     if 0 <= parent < index else mirrored[index])
            out.append(decompose(bind_transform(bone), transform_of(local)))
        return out


# ── reaching: two-bone IK ────────────────────────────────────────────


#: The hands and feet Reach offers, by the names the shipped humanoid rigs give them.
LIMB_ENDS = (
    ("Left hand", "Bip01 L Hand"),
    ("Right hand", "Bip01 R Hand"),
    ("Left foot", "Bip01 L Foot"),
    ("Right foot", "Bip01 R Foot"),
)


def limb_chain(skeleton, end: int) -> Optional[Tuple[int, int, int]]:
    """`(upper, lower, end)` bone indices for the limb ending at `end` (a name hash).

    The two bones above the hand or foot: upper arm and forearm, or thigh and calf. None when
    the bone has fewer than two ancestors.
    """

    bones = list(getattr(skeleton, "bones", ()) or ())
    index = next((bone.index for bone in bones if bone.name_hash == end), None)
    if index is None:
        return None
    lower = bones[index].parent_index
    if not 0 <= lower < len(bones):
        return None
    upper = bones[lower].parent_index
    if not 0 <= upper < len(bones):
        return None
    return upper, lower, index


def limb_ends(skeleton) -> Dict[str, int]:
    """Label -> name hash of every hand and foot this rig has a full limb for."""

    by_name = {bone.name: bone for bone in getattr(skeleton, "bones", ()) or ()}
    out = {}
    for label, name in LIMB_ENDS:
        bone = by_name.get(name)
        if bone is not None and limb_chain(skeleton, bone.name_hash) is not None:
            out[label] = bone.name_hash
    return out


def character_axes(skeleton) -> Tuple[Vec3, Vec3, Vec3]:
    """The character's left, up and forward as unit vectors in the clip's axes.

    Up is +Y on every shipped rig. Left is read off the bind pose (the left foot or hand
    against the right one), forward off the toes against the ankle; a rig without toes faces
    the way `up x left` points, which is what the humanoid rigs do.
    """

    bones = list(getattr(skeleton, "bones", ()) or ())
    by_name = {bone.name: bone for bone in bones}
    world = _bind_world(skeleton) if bones else []
    up: Vec3 = (0.0, 1.0, 0.0)

    def at(name: str) -> Optional[Vec3]:
        bone = by_name.get(name)
        return tuple(world[bone.index][12:15]) if bone is not None else None  # type: ignore[return-value]

    left: Vec3 = (1.0, 0.0, 0.0)
    for left_name, right_name in (("Bip01 L Foot", "Bip01 R Foot"), ("Bip01 L Hand", "Bip01 R Hand")):
        a, b = at(left_name), at(right_name)
        if a and b:
            across = (a[0] - b[0], 0.0, a[2] - b[2])
            if _length(across) > 1e-6:
                left = _unit(across)
                break
    forward = _cross(up, left)
    foot, toe = at("Bip01 L Foot"), at("Bip01 L Toe0")
    if foot and toe:
        ahead = (toe[0] - foot[0], 0.0, toe[2] - foot[2])
        # Only the sign is taken from the toes; the axis stays square to left and up.
        if sum(x * y for x, y in zip(ahead, forward)) < 0.0:
            forward = (-forward[0], -forward[1], -forward[2])
    return left, up, _unit(forward)


def _length(v: Sequence[float]) -> float:
    return math.sqrt(sum(c * c for c in v))


def _unit(v: Sequence[float]) -> Vec3:
    length = _length(v)
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _arc(u: Sequence[float], v: Sequence[float]) -> Quat:
    """The smallest rotation turning direction `u` onto direction `v`."""

    u, v = _unit(u), _unit(v)
    if not any(u) or not any(v):
        return IDENTITY_QUAT
    d = _dot(u, v)
    if d > 1.0 - 1e-12:
        return IDENTITY_QUAT
    if d < -1.0 + 1e-9:
        # Half a turn about any axis square to u.
        axis = _unit(_cross(u, (1.0, 0.0, 0.0) if abs(u[0]) < 0.9 else (0.0, 1.0, 0.0)))
        return (axis[0], axis[1], axis[2], 0.0)
    c = _cross(u, v)
    return quat_normalize((c[0], c[1], c[2], 1.0 + d))


def _about(point: Sequence[float], q: Quat) -> Matrix:
    """World-space rotation `q` about `point`, as a row-vector matrix to post-multiply."""

    turned = quat_rotate(q, tuple(point))  # type: ignore[arg-type]
    return matrix_of(Transform(translation=_sub(point, turned), rotation=q))


def _perpendicular(v: Vec3) -> Vec3:
    return _unit(_cross(v, (0.0, 1.0, 0.0) if abs(v[1]) < 0.9 else (1.0, 0.0, 0.0)))


def _solve_limb(upper: Matrix, lower: Matrix, end: Matrix, target: Vec3, pole: Vec3,
                keep_angle: bool) -> Tuple[Matrix, Matrix, Matrix]:
    """New world matrices for a two-bone limb whose end should sit at `target`.

    Analytic: the law of cosines places the elbow or knee in the plane of the limb's own bend
    (`pole`, the way the joint points), the upper bone swings onto it, then the lower bone
    swings the end onto the target. Out of reach, the limb straightens toward the target;
    too close, it folds as far as the bones allow. Bone lengths never change.
    """

    a, b, c = upper[12:15], lower[12:15], end[12:15]
    l1, l2 = _length(_sub(b, a)), _length(_sub(c, b))
    to_target = _sub(target, a)
    distance = _length(to_target)
    if l1 < 1e-6 or l2 < 1e-6 or distance < 1e-6:
        return upper, lower, end
    direction = _unit(to_target)
    distance = min(max(distance, abs(l1 - l2) + 1e-5), l1 + l2 - 1e-5)
    bend = _sub(pole, tuple(direction[i] * _dot(pole, direction) for i in range(3)))
    bend = _unit(bend) if _length(bend) > 1e-6 else _perpendicular(direction)
    along = (l1 * l1 - l2 * l2 + distance * distance) / (2.0 * distance)
    height = math.sqrt(max(0.0, l1 * l1 - along * along))
    joint = tuple(a[i] + direction[i] * along + bend[i] * height for i in range(3))
    reach = tuple(a[i] + direction[i] * distance for i in range(3))

    swing = _about(a, _arc(_sub(b, a), _sub(joint, a)))
    moved_end = matrix_multiply(end, swing)[12:15]
    fold = _about(joint, _arc(_sub(moved_end, joint), _sub(reach, joint)))
    upper_out = matrix_multiply(upper, swing)
    lower_out = matrix_multiply(matrix_multiply(lower, swing), fold)
    end_out = matrix_multiply(matrix_multiply(end, swing), fold)
    if keep_angle:
        end_out = tuple(end[:12]) + tuple(end_out[12:])  # type: ignore[assignment]
    return upper_out, lower_out, end_out  # type: ignore[return-value]


def _to_local(m: Matrix, v: Vec3) -> Vec3:
    """A world direction in the axes of the bone whose world matrix is `m`."""

    rows = (m[0:3], m[4:7], m[8:11])
    return tuple(_dot(v, row) / max(_dot(row, row), 1e-12) for row in rows)  # type: ignore[return-value]


def _to_world(m: Matrix, v: Vec3) -> Vec3:
    return tuple(v[0] * m[i] + v[1] * m[4 + i] + v[2] * m[8 + i] for i in range(3))  # type: ignore[return-value]


def _bend_of(upper: Matrix, lower: Matrix, end: Matrix) -> Vec3:
    """Which way the elbow or knee points: the joint's offset from the shoulder-hand line."""

    a, b, c = upper[12:15], lower[12:15], end[12:15]
    line = _unit(_sub(c, a))
    offset = _sub(b, a)
    return _sub(offset, tuple(line[i] * _dot(offset, line) for i in range(3)))


def _apply_reach(track: ReachTrack, skeleton, frames, series_of, deltas, check) -> None:
    """Bend one arm or leg so its end follows `track`, rewriting the three bones' deltas."""

    bones = skeleton.bones
    chain = limb_chain(skeleton, track.end)
    if chain is None:
        raise EditError("Reach needs a hand or foot with an arm or leg above it")
    upper_i, lower_i, end_i = chain
    path: List[int] = []
    parent = bones[upper_i].parent_index
    while 0 <= parent < len(bones):
        path.append(parent)
        parent = bones[parent].parent_index
    path.reverse()
    binds = {i: bind_transform(bones[i]) for i in path + [upper_i, lower_i, end_i]}
    hashes = {i: bones[i].name_hash for i in binds}

    def local(index: int, frame: int) -> Matrix:
        return matrix_of(compose(binds[index], series_of(hashes[index])[frame]))

    poses = []
    headings = []
    for frame in frames:
        holder: Optional[Matrix] = None
        top: Optional[Matrix] = None
        for index in path:
            m = local(index, frame)
            holder = m if holder is None else matrix_multiply(m, holder)
            top = holder if top is None else top
        u = local(upper_i, frame)
        u = u if holder is None else matrix_multiply(u, holder)
        lo = matrix_multiply(local(lower_i, frame), u)
        e = matrix_multiply(local(end_i, frame), lo)
        poses.append((holder, u, lo, e))
        headings.append(top)
    positions = [tuple(pose[3][12:15]) for pose in poses]
    last = len(positions) - 1

    def pinned_at(frame: int) -> Vec3:
        return positions[min(max(frame, 0), last)]  # type: ignore[return-value]

    bind_world = _bind_world(skeleton)
    # The way the character faces: the top of the limb's chain (Bip01, which carries the root
    # motion on the shipped rigs) turned about Y from its rest pose.
    top_index = path[0] if path else upper_i
    rest = transform_of(bind_world[top_index]).rotation
    turns = [_yaw_between(rest, transform_of(m).rotation) if m is not None else IDENTITY_QUAT
             for m in headings]

    # Which way the elbow or knee points. A limb only a few millimetres off straight says
    # nothing reliable about that (the shipped bind legs bend by 0.4 mm, and half-precision
    # noise can flip the sign frame to frame), so below a few percent of the limb's length the
    # direction comes from the clip's most bent frame, carried in the upper bone's own axes so
    # it twists with the limb, or, for a clip that never bends it, from how the limb bends:
    # knees forward, elbows back.
    a, b, c = (bind_world[i][12:15] for i in (upper_i, lower_i, end_i))
    straight = 0.03 * (_length(_sub(b, a)) + _length(_sub(c, b)))
    bends = [_bend_of(u, lo, e) for _holder, u, lo, e in poses]
    most = max(range(len(bends)), key=lambda f: _length(bends[f])) if bends else 0
    reference = (_to_local(poses[most][1], bends[most])
                 if bends and _length(bends[most]) > straight else None)
    _left, _up, forward = character_axes(skeleton)
    leg = any(word in bones[end_i].name.lower() for word in ("foot", "toe", "ankle"))
    fallback = forward if leg else (-forward[0], -forward[1], -forward[2])
    for frame, (holder, u, lo, e) in zip(frames, poses):
        if frame % 16 == 0:
            check()
        here = positions[frame]
        target, weight = reach_target(track, frame, here, pinned_at, turns[frame])  # type: ignore[arg-type]
        target = tuple(h + (t - h) * weight for h, t in zip(here, target))
        if _length(_sub(target, here)) < 1e-7:
            continue
        bend = bends[frame]
        if _length(bend) > straight:
            pole = bend
        elif reference is not None:
            pole = _to_world(u, reference)
        else:
            pole = quat_rotate(turns[frame], fallback)
        u2, lo2, e2 = _solve_limb(u, lo, e, target, pole, track.keep_angle)  # type: ignore[arg-type]
        new_locals = (
            (upper_i, u2 if holder is None else matrix_multiply(u2, _inverse(holder))),
            (lower_i, matrix_multiply(lo2, _inverse(u2))),
            (end_i, matrix_multiply(e2, _inverse(lo2))),
        )
        for index, matrix in new_locals:
            deltas[hashes[index]][frame] = decompose(binds[index], transform_of(matrix))


# ── joining: root travel carries on ──────────────────────────────────


def _yaw_between(a: Quat, b: Quat) -> Quat:
    """The turn about the vertical (Y) axis that takes heading `a` to heading `b`.

    The twist part of `b . a^-1` about Y, so a lean or a bob in either pose does not leak into
    the heading.
    """

    conj = (-a[0], -a[1], -a[2], a[3])
    relative = quat_multiply(b, conj)
    twist = (0.0, relative[1], 0.0, relative[3])
    if abs(twist[1]) < 1e-12 and abs(twist[3]) < 1e-12:
        return IDENTITY_QUAT
    return quat_normalize(twist)


# ── thinning ─────────────────────────────────────────────────────────


def _angle(a: Quat, b: Quat) -> float:
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def _segment_errors(frames, values, starts, ends, rotation: bool):
    """For many segments at once: every interior key's error against interpolating its
    segment's two ends, plus which segment and which key each error belongs to.

    One vectorised pass for a whole level of the simplification. Done one segment at a time,
    the numpy call overhead alone took 2.5 s of a 5.5 s retime on a 448-bone rig.
    """

    import numpy as np

    lengths = ends - starts - 1
    segment = np.repeat(np.arange(len(starts)), lengths)
    offsets = np.cumsum(lengths) - lengths
    index = starts[segment] + 1 + (np.arange(int(lengths.sum())) - offsets[segment])
    a, b = starts[segment], ends[segment]
    t = (frames[index] - frames[a]) / (frames[b] - frames[a])
    here, left, right = values[index], values[a], values[b]
    if not rotation:
        return np.abs(left + (right - left) * t[:, None] - here).max(axis=1), segment, index, offsets
    dot = (left * right).sum(axis=1)
    right = np.where((dot < 0.0)[:, None], -right, right)
    dot = np.abs(dot)
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    near = dot > 0.9995
    sin_theta = np.where(near, 1.0, np.sin(theta))
    w0 = np.where(near, 1.0 - t, np.sin((1.0 - t) * theta) / sin_theta)
    w1 = np.where(near, t, np.sin(t * theta) / sin_theta)
    guess = w0[:, None] * left + w1[:, None] * right
    guess /= np.linalg.norm(guess, axis=1)[:, None]
    cos_half = np.clip(np.abs((guess * here).sum(axis=1)), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(cos_half)), segment, index, offsets


def reduce_keys(keys: Sequence[Key], channel: str) -> Tuple[Key, ...]:
    """The fewest keys whose interpolation stays within tolerance of every baked frame.

    Error-bounded simplification (Douglas-Peucker on the time axis): keep both ends, find the
    frame the straight interpolation misses by most, keep it if it is past the tolerance, and
    repeat on each half. Unlike dropping keys one neighbour at a time, every dropped frame
    is checked against the segment that finally replaces it, so the bound actually holds.
    """

    import numpy as np

    if len(keys) <= 2:
        if len(keys) == 2 and keys[0][1] == keys[1][1]:
            return (keys[0],)
        return tuple(keys)
    rotation = channel == "rotation"
    tolerance = (ROTATION_TOLERANCE_DEGREES if rotation else
                 TRANSLATION_TOLERANCE if channel == "translation" else SCALE_TOLERANCE)
    frames = np.array([float(frame) for frame, _values in keys])
    values = np.array([tuple(values) for _frame, values in keys], dtype=float)
    if rotation:
        values /= np.linalg.norm(values, axis=1)[:, None]
    keep = {0, len(keys) - 1}
    starts, ends = np.array([0]), np.array([len(keys) - 1])
    # Level by level: every open segment's worst key in one pass, split where it is past the
    # tolerance. The same keys as splitting one segment at a time, in far fewer numpy calls.
    while len(starts):
        wide = ends - starts >= 2
        starts, ends = starts[wide], ends[wide]
        if not len(starts):
            break
        errors, segment, index, offsets = _segment_errors(frames, values, starts, ends, rotation)
        worst = np.maximum.reduceat(errors, offsets)
        first = np.flatnonzero(errors == worst[segment])
        _segments, at = np.unique(segment[first], return_index=True)
        split = worst > tolerance
        middles = index[first[at]][split]
        keep.update(int(m) for m in middles)
        starts, ends = (np.concatenate((starts[split], middles)),
                        np.concatenate((middles, ends[split])))
    kept = [keys[i] for i in sorted(keep)]
    # A channel that never moves needs one key, not two.
    if len(kept) == 2 and kept[0][1] == kept[1][1]:
        return (kept[0],)
    return tuple(kept)


def _is_identity(values: Sequence[float], channel: str) -> bool:
    if channel == "rotation":
        return _angle(quat_normalize(values), IDENTITY_QUAT) <= ROTATION_TOLERANCE_DEGREES
    target = UNIT_SCALE if channel == "scale" else (0.0, 0.0, 0.0)
    return all(abs(v - t) <= 1e-6 for v, t in zip(values, target))


def _canonical(q: Quat, previous: Optional[Quat]) -> Quat:
    """Keep neighbouring quaternions on the same hemisphere, so the thinning compares like
    with like and nothing interpolates the long way round."""

    if previous is not None and sum(a * b for a, b in zip(q, previous)) < 0.0:
        return (-q[0], -q[1], -q[2], -q[3])
    return q


# ── rendering ────────────────────────────────────────────────────────


def _root_offset(edit: ClipEdit, track: BoneTrack, bone, deltas: List[Transform]) -> None:
    """Scale or remove horizontal travel on a root-motion bone, in its parent's space.

    Vertical stays: in-place keeps the bob of a run and the drop of a landing. "Up" is the
    parent-space Y axis, which is world Y for the root bones of every shipped rig.
    """

    factor = max(0.0, edit.root_distance)
    if abs(factor - 1.0) <= 1e-9 or not deltas:
        return
    bind = bind_transform(bone) if bone is not None else Transform()
    locals_ = [compose(bind, delta) for delta in deltas]
    start = locals_[0].translation
    for index, local in enumerate(locals_):
        moved = (start[0] + (local.translation[0] - start[0]) * factor,
                 local.translation[1],
                 start[2] + (local.translation[2] - start[2]) * factor)
        deltas[index] = decompose(bind, replace(local, translation=moved))


class RenderCancelled(EditError):
    """A newer edit superseded this render before it finished."""


def render(edit: ClipEdit, skeleton, *, should_stop=None) -> MotionClip:
    """Bake `edit` into a clip `encode_paa` can write. No layers renders the base itself.

    `should_stop` is polled between bones and between mirrored frames, so a preview that a
    newer change has made obsolete stops instead of finishing seconds of work.
    """

    def check() -> None:
        if should_stop is not None and should_stop():
            raise RenderCancelled("The render was replaced by a newer edit")

    base = edit.base
    if base.flags & FLAG_PACKED or any(track.packed for track in base.tracks):
        raise EditError(
            "This is a distance (LOD) copy of an animation, stored in a lossy format. Edit the "
            "full animation instead; the game builds the distance copy from it."
        )
    if edit.is_identity:
        return base
    if edit.speed <= 0:
        raise EditError("Speed must be above zero")

    bones = list(getattr(skeleton, "bones", ()) or ())
    bone_by_hash = {bone.name_hash: bone for bone in bones}
    for join in edit.joins:
        if join.source.flags & FLAG_PACKED or any(track.packed for track in join.source.tracks):
            raise EditError("Join a full animation, not a distance (LOD) copy")
    splice_bones = set().union(*(s.bones for s in edit.splices)) if edit.splices else set()
    pose_by_hash = {track.name_hash: track for track in edit.pose if track.keys}
    reach_tracks = [track for track in edit.reach if track.keys]
    if reach_tracks and not bones:
        raise EditError("Reach needs the character's skeleton")
    reach_bones = set()
    for track in reach_tracks:
        chain = limb_chain(skeleton, track.end)
        if chain is None:
            raise EditError("Reach needs a hand or foot with an arm or leg above it")
        reach_bones |= {bones[i].name_hash for i in chain}
    root_hashes = {t.name_hash for t in base.tracks if t.root_motion}
    for join in edit.joins:
        root_hashes |= {t.name_hash for t in join.source.tracks if t.root_motion}
    root_edit = abs(edit.root_distance - 1.0) > 1e-9
    timeline = edit.retimed or bool(edit.joins)
    whole = timeline or edit.mirror
    if edit.mirror and not bones:
        raise EditError("Mirroring needs the character's skeleton")

    touched = set(splice_bones) | set(pose_by_hash) | reach_bones
    if root_edit:
        touched |= root_hashes
    if whole:
        touched |= {t.name_hash for t in base.tracks if t.animated}
        for join in edit.joins:
            touched |= {t.name_hash for t in join.source.tracks if t.animated}
        if edit.mirror:
            touched |= {bone.name_hash for bone in bones}

    last = edit.last_frame if timeline else max(base.last_frame, int(round(edit.base_length * FPS)))
    own_last = max(1, int(round(edit.own_seconds * FPS)))
    frames = range(last + 1)

    # Worked out once per splice: validating a source clip's timing per frame per bone made
    # splicing quadratic.
    source_lengths = [duration_seconds(splice.source) or 1e-6 for splice in edit.splices]
    spans = edit.join_spans()

    def own(name_hash: int, frame: float) -> Transform:
        """The base clip after timing and splices, at output `frame`."""

        at = edit.base_seconds(frame) if timeline else frame / FPS
        delta = _delta(base, name_hash, at)
        for splice, source_length in zip(edit.splices, source_lengths):
            if name_hash not in splice.bones or splice.weight <= 0:
                continue
            if splice.fit_length:
                source_at = min(1.0, frame / own_last) * source_length
            else:
                source_at = min(at, source_length)
            delta = _blend(delta, _delta(splice.source, name_hash, source_at), splice.weight)
        return delta

    def bind_of(name_hash: int) -> Transform:
        bone = bone_by_hash.get(name_hash)
        return bind_transform(bone) if bone is not None else Transform()

    # (bone, join) -> where the timeline before the join has the root, the join's own first
    # root pose, and the turn between their headings.
    anchors: Dict[Tuple[int, int], Tuple[Transform, Transform, Quat]] = {}

    def carried(name_hash: int, k: int, at: float) -> Transform:
        """Join `k`'s root bone `at` seconds in, as a local transform moved onto the anchor."""

        source = edit.joins[k].source
        bind = bind_of(name_hash)
        key = (name_hash, k)
        if key not in anchors:
            start, _length_k, blend = spans[k]
            before = compose(bind, timeline_delta(name_hash, start, k))
            # Heading from where the clip before *stops*: one still turning through the fade
            # would otherwise hand over its heading from the fade's start, and the character
            # would turn back by however far it turned during the fade.
            facing = compose(bind, timeline_delta(name_hash, start + blend, k))
            first = compose(bind, _delta(source, name_hash, 0.0))
            anchors[key] = (before, first, _yaw_between(first.rotation, facing.rotation))
        before, first, turn = anchors[key]
        here = compose(bind, _delta(source, name_hash, min(at, spans[k][1])))
        travel = quat_rotate(turn, _sub(here.translation, first.translation))
        moved = (before.translation[0] + travel[0], here.translation[1],
                 before.translation[2] + travel[2])
        rotation = quat_normalize(quat_multiply(turn, here.rotation))
        return Transform(translation=moved, rotation=rotation, scale=here.scale)

    # (bone, join) -> ground covered since the fade began, at even steps through the fade, and
    # how far the join's own path is shifted after it.
    drifts: Dict[Tuple[int, int], Tuple[List[Tuple[float, float]], Tuple[float, float]]] = {}

    def drift(name_hash: int, k: int):
        """Blend the two clips' root *speeds* through the fade and add up the ground covered.

        Blending positions instead overshoots: while the weight rises, the gap between where
        each clip has got to is added on top of both speeds, and the character surges forward
        mid-fade. Integrating blended velocity eases from one pace into the other.
        """

        key = (name_hash, k)
        if key in drifts:
            return drifts[key]
        start, _length, blend = spans[k]
        bind = bind_of(name_hash)
        steps = max(1, int(math.ceil(blend * FPS * 4)))
        covered = [(0.0, 0.0)]
        x = z = 0.0
        previous = compose(bind, timeline_delta(name_hash, start, k)).translation
        source_previous = carried(name_hash, k, 0.0).translation
        for i in range(steps):
            at = start + blend * (i + 1) / steps
            here = compose(bind, timeline_delta(name_hash, at, k)).translation
            source_here = carried(name_hash, k, at - start).translation
            weight = _ease((i + 0.5) / steps)
            x += (1.0 - weight) * (here[0] - previous[0]) + weight * (source_here[0] - source_previous[0])
            z += (1.0 - weight) * (here[2] - previous[2]) + weight * (source_here[2] - source_previous[2])
            covered.append((x, z))
            previous, source_previous = here, source_here
        anchor = carried(name_hash, k, 0.0).translation
        own_path = carried(name_hash, k, blend).translation
        shift = (x - (own_path[0] - anchor[0]), z - (own_path[2] - anchor[2]))
        drifts[key] = (covered, shift)
        return drifts[key]

    def joined(name_hash: int, k: int, at: float) -> Transform:
        """Join `k`'s own delta `at` seconds in, its root travel carried on."""

        if name_hash not in root_hashes:
            return _delta(edit.joins[k].source, name_hash, at)
        local = carried(name_hash, k, at)
        _covered, shift = drift(name_hash, k)
        moved = (local.translation[0] + shift[0], local.translation[1], local.translation[2] + shift[1])
        return decompose(bind_of(name_hash), replace(local, translation=moved))

    def timeline_delta(name_hash: int, at: float, upto: int) -> Transform:
        """The edited timeline `at` seconds in, counting the first `upto` joins."""

        if upto == 0:
            return own(name_hash, at * FPS)
        k = upto - 1
        before = timeline_delta(name_hash, at, k)
        start, length, blend = spans[k]
        if at < start:
            return before
        weight = 1.0 if blend <= 1e-9 else _ease(min(1.0, (at - start) / blend))
        mixed = _blend(before, joined(name_hash, k, min(at - start, length)), weight)
        if name_hash not in root_hashes or weight >= 1.0:
            return mixed
        # Mid-fade, the root's ground position comes from the blended speeds (`drift`).
        covered, _shift = drift(name_hash, k)
        place = (at - start) / blend * (len(covered) - 1)
        i = min(int(place), len(covered) - 2)
        t = place - i
        x = covered[i][0] + (covered[i + 1][0] - covered[i][0]) * t
        z = covered[i][1] + (covered[i + 1][1] - covered[i][1]) * t
        bind = bind_of(name_hash)
        anchor = carried(name_hash, k, 0.0).translation
        local = compose(bind, mixed)
        moved = (anchor[0] + x, local.translation[1], anchor[2] + z)
        return decompose(bind, replace(local, translation=moved))

    # Per bone, per frame: the delta after timing, splices and joins.
    def layered(name_hash: int) -> List[Transform]:
        check()
        if edit.joins:
            return [timeline_delta(name_hash, frame / FPS, len(spans)) for frame in frames]
        return [own(name_hash, frame) for frame in frames]

    deltas: Dict[int, List[Transform]] = {name_hash: layered(name_hash) for name_hash in touched}

    if edit.mirror:
        mirror = _Mirror(skeleton)
        order = [bone.name_hash for bone in bones]
        for name_hash in order:
            if name_hash not in deltas:
                deltas[name_hash] = layered(name_hash)
        for frame in frames:
            check()
            mirrored = mirror.frame([deltas[h][frame] for h in order])
            for name_hash, delta in zip(order, mirrored):
                deltas[name_hash][frame] = delta

    for name_hash, track in pose_by_hash.items():
        series = deltas[name_hash]
        for frame in frames:
            rotation, translation = pose_offset(track, frame)
            delta = series[frame]
            series[frame] = Transform(
                translation=tuple(d + o for d, o in zip(delta.translation, translation)),  # type: ignore[arg-type]
                rotation=quat_normalize(quat_multiply(delta.rotation, rotation)),
                scale=delta.scale,
            )

    if root_edit:
        for name_hash in root_hashes:
            if name_hash in deltas:
                _root_offset(edit, base.track_for(name_hash), bone_by_hash.get(name_hash),
                             deltas[name_hash])

    if reach_tracks:
        # Bones above a limb that no layer touched still move with the clip; sample them once.
        untouched: Dict[int, List[Transform]] = {}

        def series_of(name_hash: int) -> List[Transform]:
            if name_hash in deltas:
                return deltas[name_hash]
            if name_hash not in untouched:
                untouched[name_hash] = layered(name_hash)
            return untouched[name_hash]

        # Parents first, so a limb sees the final pose of anything above it.
        order = sorted(reach_tracks, key=lambda t: getattr(bone_by_hash.get(t.end), "index", 0))
        for track in order:
            _apply_reach(track, skeleton, frames, series_of, deltas, check)

    check()
    skeletal: List[BoneTrack] = []
    root: List[BoneTrack] = []
    for track in base.tracks:
        rebuilt = _rebuild(track, deltas.get(track.name_hash)) if track.name_hash in touched else track
        (root if track.root_motion else skeletal).append(rebuilt)
    existing = {track.name_hash for track in base.tracks}
    templates = {t.name_hash: t for join in reversed(edit.joins) for t in join.source.tracks}
    for name_hash in sorted(touched - existing, key=lambda h: getattr(bone_by_hash.get(h), "index", 0)):
        template = templates.get(name_hash) or BoneTrack(name_hash)
        track = _rebuild(template, deltas[name_hash])
        if track.animated:
            (root if track.root_motion else skeletal).append(track)

    duration = (last / FPS) if timeline else base.duration
    return replace(
        base,
        duration=duration,
        tracks=tuple(skeletal + root),
        skeletal_bone_count=len(skeletal),
        root_bone_count=len(root),
        key_bytes=0,
        passthrough=replace(base.passthrough, trailing=b""),
    )


def _rebuild(template: BoneTrack, series: Optional[List[Transform]]) -> BoneTrack:
    """A track baked from per-frame deltas, keeping the template's storage choices."""

    if series is None:
        return template
    channels: Dict[str, Tuple[Key, ...]] = {}
    previous: Optional[Quat] = None
    rotations = []
    for frame, delta in enumerate(series):
        previous = _canonical(delta.rotation, previous)
        rotations.append((frame, previous))
    baked = {
        "rotation": rotations,
        "translation": [(frame, delta.translation) for frame, delta in enumerate(series)],
        "scale": [(frame, delta.scale) for frame, delta in enumerate(series)],
    }
    for channel, keys in baked.items():
        had = bool(getattr(template, channel))
        if not had and all(_is_identity(values, channel) for _frame, values in keys):
            channels[channel] = ()
            continue
        channels[channel] = reduce_keys([(f, tuple(float(v) for v in values)) for f, values in keys],
                                        channel)
    return replace(template, packed=False, **channels)


# ── making new clips ─────────────────────────────────────────────────


def hold_pose(clip: MotionClip, seconds: float, *, length: float = 1.0, skeleton=None) -> MotionClip:
    """A new clip that holds `clip`'s pose at `seconds` for `length` seconds.

    The starting point for an animation made from scratch: freeze a pose, then key the bones
    that should move.
    """

    if clip.flags & FLAG_PACKED or any(track.packed for track in clip.tracks):
        raise EditError("Start from a full animation, not a distance (LOD) copy")
    last = max(1, int(round(length * FPS)))
    bones = {bone.name_hash: bone for bone in getattr(skeleton, "bones", ()) or ()}
    tracks = []
    for track in clip.tracks:
        if not track.animated:
            tracks.append(track)
            continue
        delta = _delta(clip, track.name_hash, seconds)
        if track.root_motion and track.translation:
            # Keep the height of the pose but not the ground covered to reach it: a pose held
            # a second into a run would otherwise stand metres from where it starts.
            bone = bones.get(track.name_hash)
            bind = bind_transform(bone) if bone is not None else Transform()
            here = compose(bind, delta).translation
            start = compose(bind, _delta(clip, track.name_hash, 0.0)).translation
            moved = replace(compose(bind, delta), translation=(start[0], here[1], start[2]))
            delta = decompose(bind, moved)
        channels = {}
        for channel in ("scale", "rotation", "translation"):
            if getattr(track, channel):
                channels[channel] = ((0, tuple(getattr(delta, channel))),)
        tracks.append(replace(track, packed=False, **channels))
    return replace(clip, duration=last / FPS, tracks=tuple(tracks), key_bytes=0,
                   passthrough=replace(clip.passthrough, trailing=b""))


def body_regions(skeleton) -> Dict[str, FrozenSet[int]]:
    """Named groups of bones, by the hash each clip track is keyed with.

    Built from the rig's own hierarchy: a region is every bone under its root bone, so it
    includes fingers, twist bones and anything else the rig hangs there.
    """

    bones = list(getattr(skeleton, "bones", ()) or ())
    children: Dict[int, List[int]] = {}
    for bone in bones:
        children.setdefault(bone.parent_index, []).append(bone.index)

    def subtree(index: int) -> List[int]:
        out, stack = [], [index]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(children.get(current, ()))
        return out

    by_name = {bone.name.lower(): bone.index for bone in bones}

    def first(*names: str) -> Optional[int]:
        return next((by_name[n] for n in names if n in by_name), None)

    regions: Dict[str, List[int]] = {}
    spine = first("bip01 spine", "bip01 spine1")
    pelvis = first("bip01 pelvis")
    neck = first("bip01 neck", "bip01 neck1")
    for label, root in (("Left arm", first("bip01 l clavicle")),
                        ("Right arm", first("bip01 r clavicle")),
                        ("Left leg", first("bip01 l thigh")),
                        ("Right leg", first("bip01 r thigh")),
                        ("Head and neck", neck),
                        ("Upper body", spine)):
        if root is not None:
            regions[label] = subtree(root)
    if pelvis is not None:
        upper = set(regions.get("Upper body", ()))
        regions["Lower body"] = [i for i in subtree(pelvis) if i not in upper]
    regions["Whole body"] = [bone.index for bone in bones]
    by_index = {bone.index: bone.name_hash for bone in bones}
    return {label: frozenset(by_index[i] for i in indices) for label, indices in regions.items()}


__all__ = [
    "ClipEdit", "EditError", "Join", "LIMB_ENDS", "PoseKey", "PoseTrack", "ReachKey", "ReachTrack",
    "RenderCancelled", "Splice", "body_regions", "character_axes", "decompose", "hold_pose",
    "limb_chain", "limb_ends", "mirror_partner_name", "mirror_partners", "pose_offset",
    "reach_offset", "reach_target", "reduce_keys", "remap_keys", "render", "transform_of",
]
