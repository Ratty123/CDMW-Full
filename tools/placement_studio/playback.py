"""Pose the rig from a `.paa` motion clip so placement can be judged in motion.

A socket's world position is its local offset composed onto its parent bone's world matrix
(`BoneHierarchy.place`). So posing is a matter of swapping each bone's bind matrix for its
animated world matrix and letting everything downstream follow — sockets, attachment
markers, the mesh proxy and the gizmo anchor all move without knowing animation exists.

That is the whole point of doing it this way. Judging whether a weapon clips the hip or
reads wrong in the hand is a question about the *draw*, not about the bind pose, and the
bind pose is the one frame where a bad placement is least likely to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tools.paa_motion.format import FPS, MotionClip, PaaFormatError, parse_paa
from tools.paa_motion.pose import world_matrices

from .skeleton import BoneHierarchy, BoneNode


class PlaybackError(RuntimeError):
    """Raised when a clip cannot be posed onto the loaded rig."""


def load_clip(data: bytes, name: str = "") -> MotionClip:
    try:
        return parse_paa(data, name=name)
    except PaaFormatError as error:
        raise PlaybackError(str(error)) from error


def coverage(hierarchy: BoneHierarchy, clip: MotionClip) -> float:
    """The fraction of the clip's animated bones this rig defines.

    A clip authored for another character parses perfectly and then animates almost
    nothing, which on screen looks like a broken decoder rather than a mismatched rig.
    """

    wanted = {track.name_hash for track in clip.tracks if track.animated}
    if not wanted:
        return 0.0
    parsed = getattr(hierarchy, "parsed", None)
    if parsed is None:
        return 0.0
    have = {bone.name_hash for bone in parsed.bones}
    return len(wanted & have) / len(wanted)


def travel_extent(clip: MotionClip) -> float:
    """How far the clip carries the character, in metres.

    Taken from the root-motion records, which are the ones stored at full float precision
    precisely because they carry locomotion. Used to size the ground plane once per clip
    rather than per frame, so the grid does not resize under the playhead.
    """

    reach = 0.0
    for track in clip.tracks:
        if not track.root_motion:
            continue
        for _frame, values in track.translation:
            reach = max(reach, max(abs(component) for component in values))
    return reach


def posed_hierarchy(
    hierarchy: BoneHierarchy, clip: MotionClip, frame: float, matrices=None
) -> BoneHierarchy:
    """`hierarchy` with every bind matrix replaced by its animated world matrix.

    `matrices` lets a caller that already solved the pose — the session, which also hands
    them to the skinning path — avoid solving it twice per frame.
    """

    parsed = getattr(hierarchy, "parsed", None)
    if parsed is None:
        raise PlaybackError(
            "this rig was not loaded from a .pab, so it carries no bone hashes to match a clip"
        )
    if matrices is None:
        matrices = world_matrices(parsed, clip, frame)
    bones = [
        BoneNode(
            index=bone.index,
            name=bone.name,
            parent_index=bone.parent_index,
            bind_matrix=matrices[bone.index] if bone.index < len(matrices) else bone.bind_matrix,
            local_position=bone.local_position,
        )
        for bone in hierarchy.bones
    ]
    return BoneHierarchy(bones, hierarchy.source, parsed)


@dataclass
class Playback:
    """Which clip is loaded and where the playhead sits."""

    clip: Optional[MotionClip] = None
    label: str = ""
    frame: float = 0.0
    playing: bool = False
    looping: bool = True
    speed: float = 1.0

    @property
    def loaded(self) -> bool:
        return self.clip is not None

    @property
    def last_frame(self) -> int:
        return self.clip.last_frame if self.clip else 0

    @property
    def seconds(self) -> float:
        return self.frame / FPS

    @property
    def duration(self) -> float:
        return self.clip.duration if self.clip else 0.0

    def load(self, clip: MotionClip, label: str) -> None:
        self.clip = clip
        self.label = label
        self.frame = 0.0
        self.playing = False

    def clear(self) -> None:
        self.clip = None
        self.label = ""
        self.frame = 0.0
        self.playing = False

    def seek(self, frame: float) -> None:
        self.frame = max(0.0, min(float(frame), float(self.last_frame)))

    def advance(self, seconds: float) -> bool:
        """Step the playhead. Returns False when a non-looping clip has reached its end."""

        if not self.loaded or not self.playing:
            return True
        if self.last_frame <= 0:
            return True
        self.frame += seconds * FPS * self.speed
        if self.frame < self.last_frame:
            return True
        if self.looping:
            self.frame %= float(self.last_frame)
            return True
        self.frame = float(self.last_frame)
        self.playing = False
        return False

    def summary(self) -> str:
        if not self.loaded:
            return "No clip loaded"
        return (
            f"{self.label}  —  frame {int(round(self.frame))}/{self.last_frame}"
            f"  ({self.seconds:.2f}s of {self.duration:.2f}s)"
        )
