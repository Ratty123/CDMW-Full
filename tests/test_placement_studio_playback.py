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

    def test_advance_uses_elapsed_time_not_a_fixed_step(self) -> None:
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))])]))
        state = Playback()
        state.load(clip, "clip")
        state.playing = True
        state.advance(0.5)  # half a second at 30 fps
        self.assertAlmostEqual(state.frame, 15.0, places=3)

    def test_a_looping_clip_wraps(self) -> None:
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))])]))
        state = Playback()
        state.load(clip, "clip")
        state.playing = True
        state.looping = True
        self.assertTrue(state.advance(1.2))  # 36 frames over a 30 frame clip
        self.assertLess(state.frame, 30.0)
        self.assertTrue(state.playing)

    def test_a_non_looping_clip_stops_at_the_end(self) -> None:
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))])]))
        state = Playback()
        state.load(clip, "clip")
        state.playing = True
        state.looping = False
        self.assertFalse(state.advance(2.0))
        self.assertEqual(state.frame, 30.0)
        self.assertFalse(state.playing)


class PosingTests(unittest.TestCase):
    def test_an_empty_clip_reproduces_the_bind_pose(self) -> None:
        rig = _rig()
        clip = parse_paa(_clip_bytes([_track(0xDEAD, rotation=[(0, (0, 0, 0, 1))])]))
        posed = posed_hierarchy(rig, clip, 0.0)
        for before, after in zip(rig.bones, posed.bones):
            self.assertAlmostEqual(before.world_position.y, after.world_position.y, places=5)

    def test_a_rotating_root_carries_the_child(self) -> None:
        """A 90 degree turn about Z takes the hand from +Y to -X."""

        rig = _rig()
        turn = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
        clip = parse_paa(_clip_bytes([
            _track(_ROOT_HASH, rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (30, turn)]),
        ]))
        posed = posed_hierarchy(rig, clip, 30.0)
        hand = posed.bones[1].world_position
        self.assertAlmostEqual(hand.x, -1.0, places=2)
        self.assertAlmostEqual(hand.y, 0.0, places=2)

    def test_a_socket_follows_the_bone_it_hangs_off(self) -> None:
        """This is the whole point: placement has to be judged in motion, not at rest."""

        rig = _rig()
        socket = Socket(name="Grip", parent_bone="Hand",
                        rotation=Quat(0.0, 0.0, 0.0, 1.0), translation=Vec3(0.0, 0.0, 0.0))
        at_rest = rig.place(socket).world_position
        self.assertAlmostEqual(at_rest.y, 1.0, places=5)

        lift = [(0, (0.0, 0.0, 0.0)), (30, (0.0, 0.5, 0.0))]
        clip = parse_paa(_clip_bytes([_track(_CHILD_HASH, translation=lift)]))
        posed = posed_hierarchy(rig, clip, 30.0)
        moved = posed.place(socket).world_position
        self.assertAlmostEqual(moved.y, 1.5, places=2)

    def test_posing_never_compounds_across_seeks(self) -> None:
        """Each pose must derive from bind; re-posing from the last frame would drift."""

        rig = _rig()
        clip = parse_paa(_clip_bytes([
            _track(_CHILD_HASH, translation=[(0, (0.0, 0.0, 0.0)), (30, (0.0, 0.5, 0.0))]),
        ]))
        once = posed_hierarchy(rig, clip, 30.0).bones[1].world_position
        twice = posed_hierarchy(posed_hierarchy(rig, clip, 10.0), clip, 30.0).bones[1].world_position
        self.assertAlmostEqual(once.y, twice.y, places=5)

    def test_a_rig_without_a_parsed_skeleton_is_refused(self) -> None:
        bare = BoneHierarchy([BoneNode(0, "Root", -1, (1.0,) + (0.0,) * 15, Vec3())], "bare")
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1))])]))
        with self.assertRaises(PlaybackError):
            posed_hierarchy(bare, clip, 0.0)


class CoverageTests(unittest.TestCase):
    def test_a_clip_for_another_character_reports_zero(self) -> None:
        rig = _rig()
        clip = parse_paa(_clip_bytes([_track(0xFEED, rotation=[(0, (0, 0, 0, 1))])]))
        self.assertEqual(coverage(rig, clip), 0.0)

    def test_a_matching_clip_reports_full(self) -> None:
        rig = _rig()
        clip = parse_paa(_clip_bytes([
            _track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1))]),
            _track(_CHILD_HASH, rotation=[(0, (0, 0, 0, 1))]),
        ]))
        self.assertEqual(coverage(rig, clip), 1.0)

    def test_load_clip_reports_a_bad_buffer_as_a_playback_error(self) -> None:
        with self.assertRaises(PlaybackError):
            load_clip(b"NOPE" + bytes(64), "broken.paa")


if __name__ == "__main__":
    unittest.main()
