"""Animation playback in Placement & Animation Studio.

The point of posing the rig is that placement can be judged in motion, so the tests that
matter are the ones proving a socket follows the animated bone and that leaving playback
returns the rig exactly to its bind pose.

Synthetic fixtures throughout — no game install needed.
"""

from __future__ import annotations

import math
import struct
import unittest

from tools.paa_motion.format import parse_paa
from tools.placement_studio.model import Quat, Socket, Vec3
from tools.placement_studio.playback import (
    Playback,
    PlaybackError,
    coverage,
    load_clip,
    posed_hierarchy,
)
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode

_ROOT_HASH = 0x1111
_CHILD_HASH = 0x2222


def _half_keys(keys, components):
    out = b""
    for frame, values in keys:
        out += struct.pack("<H", frame) + struct.pack(f"<{components}e", *values)
    return struct.pack("<H", len(keys)) + out


def _track(name_hash, *, rotation=(), translation=()):
    return (
        struct.pack("<I", name_hash)
        + _half_keys((), 3)
        + _half_keys(rotation, 4)
        + _half_keys(translation, 3)
    )


def _clip_bytes(tracks):
    body = b"".join(tracks)
    key_bytes = sum(len(t) for t in tracks) - 10 * len(tracks)
    return (
        b"PAR " + bytes([2, 3]) + bytes(range(10))
        + struct.pack("<I", 0)          # no optional prelude fields
        + struct.pack("<f", 1.0)        # duration
        + struct.pack("<HHI", len(tracks), 0, key_bytes)
        + body
    )


class _FakeBone:
    """Stands in for `cdmw.modding.skeleton_parser.Bone`."""

    def __init__(self, index, name, name_hash, parent_index, position, rotation):
        self.index = index
        self.name = name
        self.name_hash = name_hash
        self.parent_index = parent_index
        self.position = position
        self.rotation = rotation
        self.scale = (1.0, 1.0, 1.0)
        self.bind_matrix = ()


class _FakeSkeleton:
    def __init__(self, bones):
        self.bones = bones


def _rig() -> BoneHierarchy:
    """Root at the origin, child one metre up, both unrotated in bind."""

    parsed = _FakeSkeleton([
        _FakeBone(0, "Root", _ROOT_HASH, -1, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        _FakeBone(1, "Hand", _CHILD_HASH, 0, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
    ])
    identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    raised = tuple(identity[:12]) + (0.0, 1.0, 0.0, 1.0)
    bones = [
        BoneNode(0, "Root", -1, identity, Vec3()),
        BoneNode(1, "Hand", 0, raised, Vec3(0.0, 1.0, 0.0)),
    ]
    return BoneHierarchy(bones, "test.pab", parsed)


class PlaybackStateTests(unittest.TestCase):
    def test_seek_clamps_to_the_clip(self) -> None:
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))])]))
        state = Playback()
        state.load(clip, "clip")
        state.seek(999)
        self.assertEqual(state.frame, 30.0)
        state.seek(-5)
        self.assertEqual(state.frame, 0.0)


if __name__ == "__main__":
    unittest.main()
