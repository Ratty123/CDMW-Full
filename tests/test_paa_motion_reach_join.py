"""Reach (two-bone IK) and joining clips, on a small rig with real arms and legs."""

from __future__ import annotations

import math
from dataclasses import replace
import unittest

from cdmw.modding.skeleton_parser import Bone, Skeleton
from tools.paa_motion import edit
from tools.paa_motion.edit import ClipEdit, EditError, Join, ReachKey, ReachTrack, render
from tools.paa_motion.encode import encode_paa
from tools.paa_motion.format import FLAG_PACKED, BoneTrack, MotionClip, parse_paa
from tools.paa_motion.pose import world_matrices

# Laid out like the shipped humanoids: Y up, the left side on +X, facing -Z.
_NAMES = (
    ("Bip01", -1, (0.0, 0.0, 0.0)),
    ("Bip01 Pelvis", 0, (0.0, 1.0, 0.0)),
    ("Bip01 Spine", 1, (0.0, 0.3, 0.0)),
    ("Bip01 L UpperArm", 2, (0.2, 0.3, 0.0)),
    ("Bip01 L Forearm", 3, (0.0, -0.3, 0.03)),
    ("Bip01 L Hand", 4, (0.0, -0.25, -0.03)),
    ("Bip01 R UpperArm", 2, (-0.2, 0.3, 0.0)),
    ("Bip01 R Forearm", 6, (0.0, -0.3, 0.03)),
    ("Bip01 R Hand", 7, (0.0, -0.25, -0.03)),
    ("Bip01 L Thigh", 1, (0.1, -0.05, 0.0)),
    ("Bip01 L Calf", 9, (0.0, -0.45, -0.04)),
    ("Bip01 L Foot", 10, (0.0, -0.42, 0.04)),
    ("Bip01 L Toe0", 11, (0.0, -0.08, -0.15)),
    ("Bip01 R Thigh", 1, (-0.1, -0.05, 0.0)),
    ("Bip01 R Calf", 13, (0.0, -0.45, -0.04)),
    ("Bip01 R Foot", 14, (0.0, -0.42, 0.04)),
)
INDEX = {name: i for i, (name, _parent, _pos) in enumerate(_NAMES)}
HASH = {name: 0x2000 + i for name, i in INDEX.items()}


def _skeleton() -> Skeleton:
    bones = [Bone(index=i, name=name, name_hash=0x2000 + i, parent_index=parent, position=pos)
             for i, (name, parent, pos) in enumerate(_NAMES)]
    return Skeleton(path="limbs.pab", bones=bones, bone_count=len(bones))


def _q(axis, degrees):
    s = math.sin(math.radians(degrees) / 2)
    return tuple(a * s for a in axis) + (math.cos(math.radians(degrees) / 2),)


def _walk(frames: int = 30, *, travel: float = -0.04, turn: float = 0.0) -> MotionClip:
    """Swinging limbs over a root that moves forward (and turns, if asked)."""

    def keys(fn):
        return tuple((f, fn(f)) for f in range(0, frames + 1, 3))

    tracks = (
        BoneTrack(HASH["Bip01 L Thigh"], rotation=keys(lambda f: _q((1, 0, 0), 25 * math.sin(f / 5)))),
        BoneTrack(HASH["Bip01 L Calf"], rotation=keys(lambda f: _q((1, 0, 0), -10 - 10 * math.cos(f / 5)))),
        BoneTrack(HASH["Bip01 L UpperArm"], rotation=keys(lambda f: _q((1, 0, 0), -15 * math.sin(f / 5)))),
        BoneTrack(HASH["Bip01 L Forearm"], rotation=keys(lambda f: _q((1, 0, 0), 20))),
        BoneTrack(HASH["Bip01 Spine"], rotation=keys(lambda f: _q((0, 1, 0), f / 3))),
        BoneTrack(HASH["Bip01"], translation=keys(lambda f: (0.0, 0.01 * math.sin(f), travel * f)),
                  rotation=keys(lambda f: _q((0, 1, 0), turn * f / frames)),
                  root_motion=True, wide_translation=True),
    )
    return parse_paa(encode_paa(MotionClip(
        version=(2, 3), flags=0, tag="", unit_scale=0.0, skeleton_path="", duration=frames / 30.0,
        key_bytes=0, skeletal_bone_count=len(tracks) - 1, root_bone_count=1, tracks=tracks)))


def _at(skeleton, clip, name: str, frame: float):
    return tuple(world_matrices(skeleton, clip, frame)[INDEX[name]][12:15])


def _distance(a, b) -> float:
    return math.dist(a, b)


class ReachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skeleton = _skeleton()
        self.clip = _walk()

    def _render(self, track: ReachTrack) -> MotionClip:
        return parse_paa(encode_paa(render(ClipEdit(self.clip).with_reach(track), self.skeleton)))

    def _lengths(self, clip, frame, chain):
        points = [_at(self.skeleton, clip, name, frame) for name in chain]
        return [_distance(a, b) for a, b in zip(points, points[1:])]

    def test_the_hand_reaches_the_offset_and_the_arm_keeps_its_length(self) -> None:
        hand = HASH["Bip01 L Hand"]
        offset = (0.0, 0.12, -0.08)
        out = self._render(ReachTrack(hand, (ReachKey(12, offset),)))
        chain = ("Bip01 L UpperArm", "Bip01 L Forearm", "Bip01 L Hand")
        for frame in (0, 12, 25):
            here = _at(self.skeleton, self.clip, "Bip01 L Hand", frame)
            want = tuple(h + o for h, o in zip(here, offset))
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01 L Hand", frame), want), 0.0015)
            for before, after in zip(self._lengths(self.clip, frame, chain), self._lengths(out, frame, chain)):
                self.assertAlmostEqual(before, after, delta=0.001)

    def test_pinned_keys_plant_the_foot_while_the_body_travels(self) -> None:
        foot = HASH["Bip01 L Foot"]
        track = ReachTrack(foot, (ReachKey(6, pinned=True), ReachKey(18, pinned=True)))
        out = self._render(track)
        planted = _at(self.skeleton, self.clip, "Bip01 L Foot", 6)
        moved = _at(self.skeleton, self.clip, "Bip01 L Foot", 12)
        self.assertGreater(_distance(planted, moved), 0.1)  # the clip itself slides the foot
        for frame in range(6, 19, 3):
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01 L Foot", frame), planted), 0.0015)

    def test_a_free_key_after_the_plant_lets_the_foot_go(self) -> None:
        foot = HASH["Bip01 L Foot"]
        track = ReachTrack(foot, (ReachKey(6, pinned=True), ReachKey(12, pinned=True), ReachKey(18)))
        out = self._render(track)
        for frame in (18, 24, 30):
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01 L Foot", frame),
                                      _at(self.skeleton, self.clip, "Bip01 L Foot", frame)), 0.0015)

    def test_keeping_the_angle_keeps_the_hand_turned_as_the_clip_has_it(self) -> None:
        hand = HASH["Bip01 L Hand"]
        out = self._render(ReachTrack(hand, (ReachKey(0, (0.05, 0.1, 0.0)),), keep_angle=True))
        for frame in (0, 15):
            before = world_matrices(self.skeleton, self.clip, frame)[INDEX["Bip01 L Hand"]]
            after = world_matrices(self.skeleton, out, frame)[INDEX["Bip01 L Hand"]]
            for a, b in zip(before[:11], after[:11]):
                self.assertAlmostEqual(a, b, delta=0.003)

    def test_weight_zero_leaves_the_limb_alone(self) -> None:
        foot = HASH["Bip01 R Foot"]
        out = self._render(ReachTrack(foot, (ReachKey(0, (0.0, 0.3, 0.0), weight=0.0),)))
        for frame in (0, 10, 30):
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01 R Foot", frame),
                                      _at(self.skeleton, self.clip, "Bip01 R Foot", frame)), 1e-4)

    def test_out_of_reach_straightens_toward_the_target_without_stretching(self) -> None:
        hand = HASH["Bip01 L Hand"]
        out = self._render(ReachTrack(hand, (ReachKey(0, (2.0, 0.0, 0.0)),)))
        shoulder = _at(self.skeleton, out, "Bip01 L UpperArm", 0)
        reach = _distance(shoulder, _at(self.skeleton, out, "Bip01 L Hand", 0))
        lengths = self._lengths(self.clip, 0, ("Bip01 L UpperArm", "Bip01 L Forearm", "Bip01 L Hand"))
        self.assertAlmostEqual(reach, sum(lengths), delta=0.002)
        self.assertGreater(_at(self.skeleton, out, "Bip01 L Hand", 0)[0] - shoulder[0], sum(lengths) * 0.9)

    def test_only_the_limb_changes(self) -> None:
        out = render(ClipEdit(self.clip).with_reach(
            ReachTrack(HASH["Bip01 L Hand"], (ReachKey(0, (0.0, 0.1, 0.0)),))), self.skeleton)
        before = {t.name_hash: t for t in self.clip.tracks}
        limb = {HASH[n] for n in ("Bip01 L UpperArm", "Bip01 L Forearm", "Bip01 L Hand")}
        for track in out.tracks:
            if track.name_hash not in limb:
                self.assertEqual(track, before[track.name_hash])

    def test_editing_helpers_add_move_and_drop_keys(self) -> None:
        hand = HASH["Bip01 L Hand"]
        clip_edit = ClipEdit(self.clip).with_reach_key(hand, ReachKey(10, (0.0, 0.1, 0.0)))
        clip_edit = clip_edit.with_reach_key(hand, ReachKey(4))
        clip_edit = clip_edit.with_reach_key(hand, ReachKey(10, (0.0, 0.2, 0.0)))
        self.assertEqual([k.frame for k in clip_edit.reach_track(hand).keys], [4, 10])
        self.assertEqual(clip_edit.reach_track(hand).keys[1].offset, (0.0, 0.2, 0.0))
        clip_edit = clip_edit.without_reach_key(hand, 4).without_reach_key(hand, 10)
        self.assertIsNone(clip_edit.reach_track(hand))
        self.assertTrue(clip_edit.is_identity)

    def test_a_bone_without_a_limb_above_it_is_refused(self) -> None:
        with self.assertRaises(EditError):
            render(ClipEdit(self.clip).with_reach(ReachTrack(HASH["Bip01 Pelvis"], (ReachKey(0),))),
                   self.skeleton)

    def test_the_rig_names_its_limbs_and_faces_forward(self) -> None:
        self.assertEqual(set(edit.limb_ends(self.skeleton)),
                         {"Left hand", "Right hand", "Left foot", "Right foot"})
        left, up, forward = edit.character_axes(self.skeleton)
        self.assertAlmostEqual(left[0], 1.0, places=6)
        self.assertAlmostEqual(up[1], 1.0, places=6)
        self.assertAlmostEqual(forward[2], -1.0, places=6)


class JoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skeleton = _skeleton()
        self.first = _walk(30)
        self.second = _walk(45, travel=-0.03, turn=0.0)

    def test_the_join_overlaps_by_the_blend(self) -> None:
        clip_edit = ClipEdit(self.first, joins=(Join(self.second, blend=0.2),))
        self.assertAlmostEqual(clip_edit.duration, 1.0 + 1.5 - 0.2, places=6)
        out = parse_paa(encode_paa(render(clip_edit, self.skeleton)))
        self.assertAlmostEqual(out.duration, clip_edit.duration, delta=1.0 / 30)

    def test_before_the_fade_it_is_the_first_clip_and_after_it_the_second(self) -> None:
        out = render(ClipEdit(self.first, joins=(Join(self.second, blend=0.2),)), self.skeleton)
        thigh = INDEX["Bip01 L Thigh"]
        for frame in (0, 10, 20):
            a = world_matrices(self.skeleton, self.first, frame)[thigh]
            b = world_matrices(self.skeleton, out, frame)[thigh]
            for x, y in zip(a[:11], b[:11]):
                self.assertAlmostEqual(x, y, delta=0.002)
        start = 24  # the join starts 0.2 s before the first clip's end at frame 30
        for frame in (33, 45, 60):
            # Rotations only: the second clip's root is moved on, its limbs are not.
            a = world_matrices(self.skeleton, self.second, frame - start)[thigh]
            b = world_matrices(self.skeleton, out, frame)[thigh]
            for x, y in zip(a[:11], b[:11]):
                self.assertAlmostEqual(x, y, delta=0.003)

    def test_root_travel_carries_on_without_snapping_back(self) -> None:
        out = render(ClipEdit(self.first, joins=(Join(self.second, blend=0.2),)), self.skeleton)
        steps = [_at(self.skeleton, out, "Bip01", frame)[2] for frame in range(0, 70)]
        # Always moving forward (-Z), never back toward where the second clip starts.
        for a, b in zip(steps, steps[1:]):
            self.assertLessEqual(b, a + 1e-4)
        self.assertLess(steps[-1], _at(self.skeleton, self.first, "Bip01", 30)[2] - 0.5)

    def test_the_fade_eases_into_the_new_pace_without_a_surge(self) -> None:
        still = _walk(30, travel=0.0)
        out = render(ClipEdit(still, joins=(Join(self.second, blend=0.5),)), self.skeleton)
        steps = [_at(self.skeleton, out, "Bip01", frame) for frame in range(0, 70)]
        speeds = [abs(b[2] - a[2]) for a, b in zip(steps, steps[1:])]
        own = [_at(self.skeleton, self.second, "Bip01", frame)[2] for frame in range(0, 46)]
        pace = max(abs(b - a) for a, b in zip(own, own[1:]))
        self.assertLess(max(speeds), pace * 1.02)
        fade = speeds[15:30]  # 0.5 s from frame 15
        self.assertEqual(fade, sorted(fade))

    def test_a_turned_first_clip_turns_the_joined_one(self) -> None:
        first = _walk(30, turn=90.0)
        out = render(ClipEdit(first, joins=(Join(self.second, blend=0.0),)), self.skeleton)
        a = _at(self.skeleton, out, "Bip01", 31)
        b = _at(self.skeleton, out, "Bip01", 45)
        heading = (b[0] - a[0], b[2] - a[2])
        # The first clip ends turned a quarter turn about Y: -Z travel becomes -X travel.
        self.assertLess(heading[0], -0.3)
        self.assertLess(abs(heading[1]), 0.05)

    def test_a_distance_copy_cannot_be_joined(self) -> None:
        packed = _walk(10)
        packed = type(packed)(**{**packed.__dict__, "flags": packed.flags | FLAG_PACKED})
        with self.assertRaises(EditError):
            render(ClipEdit(self.first, joins=(Join(packed),)), self.skeleton)


if __name__ == "__main__":
    unittest.main()


class ReviewFindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skeleton = _skeleton()

    def test_a_join_faces_where_a_turning_clip_stops_whatever_the_fade(self) -> None:
        first = _walk(30, turn=90.0)
        for blend in (0.25, 0.5, 1.0):
            clip_edit = ClipEdit(first, joins=(Join(_walk(45), blend=blend),))
            out = render(clip_edit, self.skeleton)
            end = clip_edit.last_frame
            a = _at(self.skeleton, out, "Bip01", end - 12)
            b = _at(self.skeleton, out, "Bip01", end - 6)
            self.assertLess(b[0] - a[0], -0.1, blend)       # travelling along -X
            self.assertLess(abs(b[2] - a[2]), 0.03, blend)   # not drifting back to -Z

    def test_a_fade_only_overlaps_the_clip_before_it(self) -> None:
        short = _walk(15)  # 0.5 s
        clip_edit = ClipEdit(_walk(30), joins=(Join(short, blend=0.25), Join(_walk(60), blend=1.0)))
        spans = clip_edit.join_spans()
        self.assertAlmostEqual(spans[1][2], 0.25)            # the 0.5 s clip minus its own fade
        self.assertAlmostEqual(spans[1][0], spans[0][0] + 0.25)
        self.assertAlmostEqual(clip_edit.duration, 3.0)

    def test_a_plant_does_not_reach_back_before_its_first_key(self) -> None:
        clip = _walk()
        out = render(ClipEdit(clip).with_reach(
            ReachTrack(HASH["Bip01 L Foot"], (ReachKey(20, pinned=True),))), self.skeleton)
        for frame in (0, 10, 19):
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01 L Foot", frame),
                                      _at(self.skeleton, clip, "Bip01 L Foot", frame)), 1e-4)

    def test_a_nearly_straight_knee_bends_forward_whichever_side_the_noise_is(self) -> None:
        for noise in (0.0003, -0.0003):
            names = list(_NAMES)
            names[INDEX["Bip01 L Calf"]] = ("Bip01 L Calf", 9, (0.0, -0.45, noise))
            names[INDEX["Bip01 L Foot"]] = ("Bip01 L Foot", 10, (0.0, -0.42, 0.0))
            bones = [Bone(index=i, name=n, name_hash=0x2000 + i, parent_index=parent, position=pos)
                     for i, (n, parent, pos) in enumerate(names)]
            skeleton = Skeleton(path="straight.pab", bones=bones, bone_count=len(bones))
            still = _walk(30, travel=0.0)
            still = type(still)(**{**still.__dict__, "tracks": tuple(
                t for t in still.tracks if t.name_hash not in (HASH["Bip01 L Thigh"], HASH["Bip01 L Calf"]))})
            out = render(ClipEdit(still).with_reach(
                ReachTrack(HASH["Bip01 L Foot"], (ReachKey(0, (0.0, 0.15, 0.0)),))), skeleton)
            knee = _at(skeleton, out, "Bip01 L Calf", 10)
            hip = _at(skeleton, out, "Bip01 L Thigh", 10)
            self.assertLess(knee[2] - hip[2], -0.05, noise)  # forward is -Z

    def test_offsets_turn_with_the_character(self) -> None:
        turned = _walk(30, travel=0.0, turn=90.0)
        hand = HASH["Bip01 L Hand"]
        ahead = (0.0, 0.0, -0.1)  # the rest pose's forward
        out = render(ClipEdit(turned).with_reach(ReachTrack(hand, (ReachKey(0, ahead),))), self.skeleton)
        before = _at(self.skeleton, turned, "Bip01 L Hand", 30)
        after = _at(self.skeleton, out, "Bip01 L Hand", 30)
        moved = [b - a for a, b in zip(before, after)]
        # A quarter turn about Y makes the character's forward -X.
        self.assertLess(moved[0], -0.08)
        self.assertLess(abs(moved[2]), 0.02)

    def test_retiming_moves_keys_with_the_motion(self) -> None:
        clip = _walk()
        hand = HASH["Bip01 L Hand"]
        old = ClipEdit(clip).with_pose_key(hand, edit.PoseKey(24)).with_reach_key(hand, ReachKey(30))
        faster = edit.remap_keys(old, replace(old, speed=2.0))
        self.assertEqual([k.frame for k in faster.pose_track(hand).keys], [12])
        self.assertEqual([k.frame for k in faster.reach_track(hand).keys], [15])
        backwards = edit.remap_keys(old, replace(old, reverse=True))
        self.assertEqual([k.frame for k in backwards.pose_track(hand).keys], [6])
        held = replace(old, hold_end=0.5)
        held = held.with_pose_key(hand, edit.PoseKey(40))
        trimmed = edit.remap_keys(held, replace(held, trim_start=0.5))
        self.assertEqual(sorted(k.frame for k in trimmed.pose_track(hand).keys), [9, 25])


class RootStartTests(unittest.TestCase):
    """A trimmed or reversed clip starts its root where the untrimmed clip starts."""

    def setUp(self) -> None:
        self.skeleton = _skeleton()
        self.clip = _walk(30)

    def test_trimming_the_start_keeps_the_root_starting_where_the_clip_starts(self) -> None:
        out = render(ClipEdit(self.clip, trim_start=0.5), self.skeleton)
        start = _at(self.skeleton, self.clip, "Bip01", 0)
        self.assertLess(abs(_at(self.skeleton, out, "Bip01", 0)[2] - start[2]), 1e-4)
        # The motion itself is the trimmed part's: same steps, same distance.
        for frame in (5, 10, 15):
            moved = _at(self.skeleton, out, "Bip01", frame)[2] - _at(self.skeleton, out, "Bip01", 0)[2]
            own = (_at(self.skeleton, self.clip, "Bip01", 15 + frame)[2]
                   - _at(self.skeleton, self.clip, "Bip01", 15)[2])
            self.assertAlmostEqual(moved, own, delta=1e-4)
        # Height is kept as the clip has it at that moment.
        self.assertAlmostEqual(_at(self.skeleton, out, "Bip01", 0)[1],
                               _at(self.skeleton, self.clip, "Bip01", 15)[1], delta=1e-4)

    def test_playing_backwards_starts_where_the_clip_starts_and_walks_back(self) -> None:
        out = render(ClipEdit(self.clip, reverse=True), self.skeleton)
        start = _at(self.skeleton, self.clip, "Bip01", 0)
        self.assertLess(abs(_at(self.skeleton, out, "Bip01", 0)[2] - start[2]), 1e-4)
        self.assertGreater(_at(self.skeleton, out, "Bip01", 30)[2], start[2] + 1.0)

    def test_only_speed_changes_nothing_about_the_start(self) -> None:
        out = render(ClipEdit(self.clip, speed=2.0), self.skeleton)
        for frame in (0, 7, 15):
            self.assertLess(_distance(_at(self.skeleton, out, "Bip01", frame),
                                      _at(self.skeleton, self.clip, "Bip01", frame * 2)), 1e-3)
