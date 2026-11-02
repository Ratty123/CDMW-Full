"""Editing `.paa` clips: layers over a base clip, baked by `render`, written by `encode_paa`.

Synthetic: a small biped with symmetric bind poses and one root-motion bone. The same checks
were run against the shipped player rig and clips (identity renders byte for byte; a mirror
puts every bone with a symmetric rest pose within 5 mm of its reflected partner; a Blender
round trip comes back within 4 mm).
"""

from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
from pathlib import Path

from cdmw.modding.skeleton_parser import Bone, Skeleton
from tools.paa_motion import edit
from tools.paa_motion.edit import ClipEdit, PoseKey, Splice, render
from tools.paa_motion.encode import encode_paa
from tools.paa_motion.format import FLAG_PACKED, BoneTrack, MotionClip, parse_paa
from tools.paa_motion.gltf import write_glb
from tools.paa_motion.gltf_import import GltfImportError, import_animation
from tools.paa_motion.pose import sample_delta, world_matrices

_NAMES = (
    ("Bip01", -1, (0.0, 0.0, 0.0)),
    ("Bip01 Pelvis", 0, (0.0, 1.0, 0.0)),
    ("Bip01 Spine", 1, (0.0, 0.2, 0.0)),
    ("Bip01 Neck", 2, (0.0, 0.4, 0.0)),
    ("Bip01 L Clavicle", 2, (0.1, 0.35, 0.0)),
    ("Bip01 L Hand", 4, (0.4, 0.0, 0.0)),
    ("Bip01 R Clavicle", 2, (-0.1, 0.35, 0.0)),
    ("Bip01 R Hand", 6, (-0.4, 0.0, 0.0)),
    ("Bip01 L Thigh", 1, (0.12, -0.05, 0.0)),
    ("Bip01 R Thigh", 1, (-0.12, -0.05, 0.0)),
)


def _skeleton() -> Skeleton:
    bones = [Bone(index=i, name=name, name_hash=0x1000 + i, parent_index=parent, position=pos)
             for i, (name, parent, pos) in enumerate(_NAMES)]
    return Skeleton(path="synthetic.pab", bones=bones, bone_count=len(bones))


def _q(axis, degrees):
    s = math.sin(math.radians(degrees) / 2)
    return tuple(a * s for a in axis) + (math.cos(math.radians(degrees) / 2),)


def _clip(frames: int = 30) -> MotionClip:
    def keys(fn):
        return tuple((f, fn(f)) for f in range(0, frames + 1, 5))

    tracks = (
        BoneTrack(0x1000 + 4, rotation=keys(lambda f: _q((0, 0, 1), 3 * f))),   # L clavicle
        BoneTrack(0x1000 + 5, rotation=keys(lambda f: _q((1, 0, 0), -2 * f))),  # L hand
        BoneTrack(0x1000 + 8, rotation=keys(lambda f: _q((1, 0, 0), f))),       # L thigh
        BoneTrack(0x1000 + 2, rotation=keys(lambda f: _q((0, 1, 0), f / 2))),   # spine
        BoneTrack(0x1000, translation=keys(lambda f: (0.0, 0.0, -0.05 * f)),
                  root_motion=True, wide_translation=True),
    )
    return MotionClip(version=(2, 3), flags=0, tag="", unit_scale=0.0, skeleton_path="",
                      duration=frames / 30.0, key_bytes=0, skeletal_bone_count=4,
                      root_bone_count=1, tracks=tracks)


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skeleton = _skeleton()
        self.clip = parse_paa(encode_paa(_clip()))

    def test_no_layers_writes_the_original_bytes(self) -> None:
        data = encode_paa(self.clip)
        self.assertEqual(encode_paa(render(ClipEdit(self.clip), self.skeleton)), data)

    def test_a_pose_key_changes_only_that_bone(self) -> None:
        hand = 0x1000 + 7
        rendered = render(ClipEdit(self.clip).with_pose_key(hand, PoseKey(0, _q((0, 0, 1), 20))),
                          self.skeleton)
        again = parse_paa(encode_paa(rendered))
        before = {t.name_hash: t for t in self.clip.tracks}
        for track in again.tracks:
            if track.name_hash != hand:
                self.assertEqual(track, before[track.name_hash])
        delta = sample_delta(again, hand, 12)
        self.assertAlmostEqual(math.degrees(2 * math.acos(delta.rotation[3])), 20.0, places=1)

    def test_pose_keys_ease_between_and_hold_outside(self) -> None:
        hand = 0x1000 + 5
        edited = (ClipEdit(self.clip)
                  .with_pose_key(hand, PoseKey(10, _q((0, 1, 0), 0)))
                  .with_pose_key(hand, PoseKey(20, _q((0, 1, 0), 40))))
        track = edited.pose_track(hand)
        angle = lambda frame: math.degrees(2 * math.acos(edit.pose_offset(track, frame)[0][3]))
        self.assertAlmostEqual(angle(5), 0.0, places=3)
        self.assertAlmostEqual(angle(15), 20.0, places=1)
        self.assertAlmostEqual(angle(28), 40.0, places=3)
        self.assertLess(angle(11), 40.0 * 0.1)  # eased: slow out of the first key
        removed = edited.without_pose_key(hand, 20).without_pose_key(hand, 10)
        self.assertEqual(removed.pose, ())

    def test_speed_trim_reverse_and_hold(self) -> None:
        spine = 0x1000 + 2
        fast = parse_paa(encode_paa(render(ClipEdit(self.clip, speed=2.0), self.skeleton)))
        self.assertEqual(fast.last_frame, 15)
        self.assertAlmostEqual(fast.duration, 0.5, places=5)
        self.assertAlmostEqual(sample_delta(fast, spine, 5).rotation[1],
                               sample_delta(self.clip, spine, 10).rotation[1], places=3)
        trimmed = render(ClipEdit(self.clip, trim_start=10 / 30, trim_end=20 / 30), self.skeleton)
        self.assertAlmostEqual(trimmed.duration, 10 / 30, places=5)
        backwards = render(ClipEdit(self.clip, reverse=True), self.skeleton)
        self.assertAlmostEqual(sample_delta(backwards, spine, 0).rotation[1],
                               sample_delta(self.clip, spine, 30).rotation[1], places=3)
        held = render(ClipEdit(self.clip, hold_end=0.5), self.skeleton)
        self.assertAlmostEqual(held.duration, 1.5, places=5)
        self.assertAlmostEqual(sample_delta(held, spine, 44).rotation[1],
                               sample_delta(self.clip, spine, 30).rotation[1], places=3)

    def test_keep_in_place_removes_travel_but_not_height(self) -> None:
        moving = self.clip.track_for(0x1000)
        self.assertNotEqual(moving.translation[0][1][2], moving.translation[-1][1][2])
        still = render(ClipEdit(self.clip, root_distance=0.0), self.skeleton)
        frames = [sample_delta(still, 0x1000, f).translation for f in (0, 15, 30)]
        self.assertTrue(all(abs(t[2] - frames[0][2]) < 1e-3 for t in frames))
        half = render(ClipEdit(self.clip, root_distance=0.5), self.skeleton)
        self.assertAlmostEqual(sample_delta(half, 0x1000, 30).translation[2], -0.75, places=2)

    def test_mirror_reflects_every_bone_onto_its_partner(self) -> None:
        mirrored = parse_paa(encode_paa(render(ClipEdit(self.clip, mirror=True), self.skeleton)))
        partners = edit.mirror_partners(self.skeleton)
        axis = edit.mirror_axis(self.skeleton)
        self.assertEqual(axis, 0)
        for frame in (0, 13, 30):
            source = world_matrices(self.skeleton, self.clip, frame)
            result = world_matrices(self.skeleton, mirrored, frame)
            for index, partner in partners.items():
                expected = list(source[partner][12:15])
                expected[axis] = -expected[axis]
                self.assertLess(math.dist(expected, result[index][12:15]), 0.002,
                                (frame, self.skeleton.bones[index].name))

    def test_mirroring_twice_gives_the_clip_back(self) -> None:
        once = parse_paa(encode_paa(render(ClipEdit(self.clip, mirror=True), self.skeleton)))
        twice = render(ClipEdit(once, mirror=True), self.skeleton)
        a = world_matrices(self.skeleton, self.clip, 17)
        b = world_matrices(self.skeleton, twice, 17)
        self.assertLess(max(math.dist(x[12:15], y[12:15]) for x, y in zip(a, b)), 0.002)

    def test_a_splice_takes_the_region_from_the_other_clip(self) -> None:
        other = parse_paa(encode_paa(render(ClipEdit(self.clip, mirror=True), self.skeleton)))
        regions = edit.body_regions(self.skeleton)
        left_arm = regions["Left arm"]
        spliced = render(ClipEdit(self.clip, splices=(Splice(other, left_arm, 1.0),)),
                         self.skeleton)
        for name_hash in left_arm:
            got, want = sample_delta(spliced, name_hash, 12), sample_delta(other, name_hash, 12)
            if want is not None:
                self.assertLess(max(abs(a - b) for a, b in zip(got.rotation, want.rotation)), 2e-3)
        legs = sample_delta(spliced, 0x1000 + 8, 12)
        self.assertEqual(legs, sample_delta(self.clip, 0x1000 + 8, 12))

    def test_regions_follow_the_hierarchy(self) -> None:
        regions = edit.body_regions(self.skeleton)
        self.assertEqual(regions["Left arm"], frozenset({0x1004, 0x1005}))
        self.assertNotIn(0x1002, regions["Lower body"])
        self.assertIn(0x1008, regions["Lower body"])

    def test_a_held_pose_is_a_new_clip_to_build_on(self) -> None:
        held = edit.hold_pose(self.clip, 0.5, length=2.0)
        self.assertAlmostEqual(held.duration, 2.0, places=5)
        data = encode_paa(held)
        again = parse_paa(data)
        self.assertEqual(sample_delta(again, 0x1002, 0), sample_delta(again, 0x1002, 50))

    def test_partner_names(self) -> None:
        self.assertEqual(edit.mirror_partner_name("Bip01 L Hand"), "Bip01 R Hand")
        self.assertEqual(edit.mirror_partner_name("B_Ear_02_L"), "B_Ear_02_R")
        self.assertEqual(edit.mirror_partner_name("Bip01 Spine"), "Bip01 Spine")

    def test_distance_copies_are_refused(self) -> None:
        packed = MotionClip(**{**self.clip.__dict__, "flags": FLAG_PACKED})
        with self.assertRaises(edit.EditError):
            render(ClipEdit(packed, speed=2.0), self.skeleton)

    def test_thinning_keeps_the_shape(self) -> None:
        keys = [(f, (0.0, 0.0, f * 0.01)) for f in range(31)]
        self.assertEqual([k[0] for k in edit.reduce_keys(keys, "translation")], [0, 30])
        bent = keys[:15] + [(15, (0.0, 0.0, 0.5))] + keys[16:]
        self.assertIn(15, [k[0] for k in edit.reduce_keys(bent, "translation")])


class ReviewFindingTests(unittest.TestCase):
    """Each of these failed against the first version of the editor."""

    def test_thinning_holds_its_tolerance_at_every_frame(self) -> None:
        import math as _m

        keys = []
        for frame in range(61):
            t = frame / 60
            eased = t * t * (3 - 2 * t)
            keys.append((frame, _q((0, 0, 1), 40 * eased)))
        kept = edit.reduce_keys(keys, "rotation")
        self.assertLess(len(kept), len(keys))
        frames = [k[0] for k in kept]
        for frame, wanted in keys:
            index = max(i for i, f in enumerate(frames) if f <= frame)
            if frames[index] == frame:
                continue
            a, b = kept[index], kept[index + 1]
            t = (frame - a[0]) / (b[0] - a[0])
            from tools.paa_motion.pose import quat_slerp

            got = quat_slerp(a[1], b[1], t)
            error = _m.degrees(2 * _m.acos(min(1.0, abs(sum(x * y for x, y in zip(got, wanted))))))
            self.assertLessEqual(error, edit.ROTATION_TOLERANCE_DEGREES + 1e-9, frame)

    def test_a_held_pose_keeps_height_but_not_the_ground_covered(self) -> None:
        clip = parse_paa(encode_paa(_clip()))
        held = edit.hold_pose(clip, 1.0, length=1.0, skeleton=_skeleton())
        start = sample_delta(clip, 0x1000, 0).translation
        self.assertAlmostEqual(sample_delta(held, 0x1000, 0).translation[2], start[2], places=4)

    def test_the_import_ends_untouched_bones_where_their_motion_is(self) -> None:
        from tools.paa_motion.gltf_import import _stretch

        track = BoneTrack(0x1002, rotation=((0, _q((0, 1, 0), 0)), (60, _q((0, 1, 0), 60))))
        clip = MotionClip(version=(2, 3), flags=0, tag="", unit_scale=0.0, skeleton_path="",
                          duration=2.0, key_bytes=0, skeletal_bone_count=1, root_bone_count=0,
                          tracks=(track,))
        cut = _stretch(track, 30, clip)
        self.assertEqual([k[0] for k in cut.rotation], [0, 30])
        angle = math.degrees(2 * math.acos(cut.rotation[-1][1][3]))
        self.assertAlmostEqual(angle, 30.0, places=3)

    def test_stepped_keys_are_read_on_their_own_frame(self) -> None:
        from tools.paa_motion.gltf_import import _sample

        times = [i / 30.0 + (1e-7 if i % 2 else -1e-7) for i in range(10)]
        values = [(float(i),) for i in range(10)]
        for frame in range(10):
            self.assertEqual(_sample(times, values, frame / 30.0, False, True), (float(frame),))


class GltfRoundTripTests(unittest.TestCase):
    def test_export_then_import_gives_the_motion_back(self) -> None:
        skeleton, clip = _skeleton(), parse_paa(encode_paa(_clip()))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion.glb"
            write_glb(path, skeleton, clip, name="motion")
            report = import_animation(path, skeleton, clip)
        self.assertEqual(report.unmatched, ())
        back = parse_paa(encode_paa(report.clip))
        self.assertEqual(back.last_frame, clip.last_frame)
        for frame in (0, 7, 30):
            a = world_matrices(skeleton, clip, frame)
            b = world_matrices(skeleton, back, frame)
            self.assertLess(max(math.dist(x[12:15], y[12:15]) for x, y in zip(a, b)), 0.004)

    def test_a_node_blender_renamed_is_still_matched(self) -> None:
        skeleton, clip = _skeleton(), parse_paa(encode_paa(_clip()))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion.glb"
            write_glb(path, skeleton, clip, name="motion")
            data = path.read_bytes()
            json_len = struct.unpack_from("<I", data, 12)[0]
            document = json.loads(data[20:20 + json_len])
            # Blender renames nodes it duplicates; the importer must still find the bone.
            hand = next(i for i, n in enumerate(document["nodes"]) if n["name"] == "Bip01 L Hand")
            document["nodes"][hand]["name"] = "Bip01 L Hand.001"
            payload = json.dumps(document).encode("utf-8")
            payload += b" " * (-len(payload) % 4)
            rest = data[20 + json_len:]
            rebuilt = (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload) + len(rest))
                       + struct.pack("<II", len(payload), 0x4E4F534A) + payload + rest)
            path.write_bytes(rebuilt)
            report = import_animation(path, skeleton, clip)
        self.assertIn("Bip01 L Hand", report.matched)
        self.assertEqual(report.unmatched, ())

    def test_a_file_with_no_matching_bones_is_refused(self) -> None:
        skeleton, clip = _skeleton(), parse_paa(encode_paa(_clip()))
        stranger = Skeleton(path="x", bones=[Bone(index=0, name="Other", name_hash=1)],
                            bone_count=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion.glb"
            write_glb(path, skeleton, clip, name="motion")
            with self.assertRaises(GltfImportError):
                import_animation(path, stranger, clip)


if __name__ == "__main__":
    unittest.main()
