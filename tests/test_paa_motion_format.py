"""Unit tests for the `.paa` motion clip reader, evaluator, and glTF export.

The synthetic fixtures encode the format by hand, so these run without the game install.
The corpus gate that needs the extracted vanilla motion tree is marked `real_game`.
"""

from __future__ import annotations

import json
import math
import struct
import unittest
from pathlib import Path

import pytest

from tools.paa_motion import format as paa
from tools.paa_motion import gltf, pose

VANILLA_MOTION = Path("workspace/placement_studio/vanilla/character/motion")
VANILLA_SKELETON = Path(
    "workspace/placement_studio/vanilla/character/model/1_pc/1_phm/phm_01.pab"
)


def _half_keys(keys, components):
    out = b""
    for frame, values in keys:
        out += struct.pack("<H", frame) + struct.pack(f"<{components}e", *values)
    return struct.pack("<H", len(keys)) + out


def _float_keys(keys, components):
    out = b""
    for frame, values in keys:
        out += struct.pack("<HH", frame, 0) + struct.pack(f"<{components}f", *values)
    return struct.pack("<H", len(keys)) + out


def _track(name_hash, *, scale=(), rotation=(), translation=(), root=False):
    body = struct.pack("<I", name_hash)
    body += _half_keys(scale, 3)
    body += _half_keys(rotation, 4)
    body += (_float_keys if root else _half_keys)(translation, 3)
    return body


def _packed_keys(keys, components):
    out = bytes([len(keys)])
    for frame, values in keys:
        out += bytes([frame]) + struct.pack(f"<{components}b", *values)
    return out


def _packed_track(name_hash, *, scale=(), rotation=(), translation=()):
    """A byte-quantised record: u8 count then [u8 frame][signed byte per component]."""

    return (
        struct.pack("<I", name_hash)
        + _packed_keys(scale, 3)
        + _packed_keys(rotation, 4)
        + _packed_keys(translation, 3)
    )


def _packed_clip_bytes(packed_tracks, root_tracks, *, duration=1.0):
    """A packed clip: leading u32, 16-byte table, packed records, then half root records."""

    flags = paa.FLAG_PACKED | paa.FLAG_UNIT_SCALE
    body = b"".join(packed_tracks) + b"".join(root_tracks)
    key_bytes = (
        sum(len(t) for t in packed_tracks) - 7 * len(packed_tracks)
        + sum(len(t) for t in root_tracks) - 10 * len(root_tracks)
    )
    header = paa.PAR_MAGIC + bytes([2, 3]) + bytes(range(10))
    return (
        header
        + struct.pack("<I", flags)
        + struct.pack("<I", 0)              # the u32 the packed codec adds to the prelude
        + struct.pack("<f", 0.97222)        # unit scale
        + struct.pack("<f", duration)
        + struct.pack("<I", 5)              # leading table word
        + struct.pack("<HH", len(packed_tracks), len(root_tracks))
        + struct.pack("<I", 0)              # reserved
        + struct.pack("<I", key_bytes)
        + body
    )


def _clip_bytes(tracks, *, skeletal, roots, duration=1.0, flags=paa.FLAG_UNIT_SCALE,
                unit_scale=0.97222, tag="", skeleton_path=""):
    """Assemble a `.paa` the way the shipped writer does."""

    body = b"".join(tracks)
    key_bytes = sum(len(t) for t in tracks) - 10 * len(tracks)
    prelude = b""
    if flags & paa.FLAG_TAG:
        blob = tag.encode("utf-8") + b"\x00"
        prelude += struct.pack("<H", len(blob)) + blob
    if flags & paa.FLAG_BOUNDS:
        # One 40-byte frame, and a second only when the bit that adds it is set. The
        # shipped clips that clear 0x04 stop after one.
        frame = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        frames = frame * (2 if flags & paa.FLAG_BOUNDS_SECOND else 1)
        prelude += struct.pack(f"<{len(frames)}f", *frames)
    if flags & paa.FLAG_UNIT_SCALE:
        prelude += struct.pack("<f", unit_scale)
    if flags & paa.FLAG_SKELETON_PATH:
        encoded = skeleton_path.encode("ascii")
        prelude += bytes([len(encoded)]) + encoded
    header = paa.PAR_MAGIC + bytes([2, 3]) + bytes(range(10))
    return (
        header
        + struct.pack("<I", flags)
        + prelude
        + struct.pack("<f", duration)
        + struct.pack("<HHI", skeletal, roots, key_bytes)
        + body
    )


class _FakeBone:
    def __init__(self, index, name, name_hash, parent_index, position, rotation, scale=(1.0, 1.0, 1.0)):
        self.index = index
        self.name = name
        self.name_hash = name_hash
        self.parent_index = parent_index
        self.position = position
        self.rotation = rotation
        self.scale = scale


class _FakeSkeleton:
    def __init__(self, bones):
        self.bones = bones


def _two_bone_skeleton():
    return _FakeSkeleton([
        _FakeBone(0, "Root", 0x1111, -1, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        # A 90 degree turn about Y, so a delta in local axes lands on a different world axis.
        _FakeBone(1, "Child", 0x2222, 0, (0.0, 0.5, 0.0), (0.0, math.sqrt(0.5), 0.0, math.sqrt(0.5))),
    ])


class FormatTests(unittest.TestCase):
    def test_parses_header_prelude_and_tracks(self) -> None:
        data = _clip_bytes(
            [
                _track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (30, (0.0, 0.0, 0.0, 1.0))]),
                _track(0x2222, translation=[(0, (0.0, 0.0, 0.0)), (30, (1.0, 2.0, 3.0))], root=True),
            ],
            skeletal=1, roots=1, duration=1.0,
            flags=(
                paa.FLAG_BOUNDS | paa.FLAG_BOUNDS_SECOND | paa.FLAG_UNIT_SCALE
                | paa.FLAG_SKELETON_PATH | paa.FLAG_TAG
            ),
            tag="male;longsword;", skeleton_path="character/model/1_pc/1_phm/phm_01.pab",
        )
        clip = paa.parse_paa(data)
        self.assertEqual(clip.version, (2, 3))
        self.assertEqual(clip.tags, ("male", "longsword"))
        self.assertEqual(clip.skeleton_path, "character/model/1_pc/1_phm/phm_01.pab")
        self.assertAlmostEqual(clip.duration, 1.0, places=5)
        self.assertEqual(clip.frame_count, 31)
        self.assertEqual([t.name_hash for t in clip.tracks], [0x1111, 0x2222])
        self.assertFalse(clip.tracks[0].root_motion)
        self.assertTrue(clip.tracks[1].root_motion)

    def test_root_translation_keeps_full_float_precision(self) -> None:
        """A half would quantise a long run; the root records are float32 for that reason."""

        far = 9.944911
        data = _clip_bytes(
            [_track(0x2222, translation=[(0, (0.0, 0.0, 0.0)), (60, (far, 0.0, 0.0))], root=True)],
            skeletal=0, roots=1, duration=2.0,
        )
        clip = paa.parse_paa(data)
        self.assertAlmostEqual(clip.tracks[0].translation[-1][1][0], far, places=5)

    def test_key_bytes_header_matches_the_payload(self) -> None:
        data = _clip_bytes(
            [
                _track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0))], translation=[(0, (0.0, 0.0, 0.0))]),
                _track(0x2222, translation=[(0, (0.0, 0.0, 0.0)), (10, (1.0, 0.0, 0.0))], root=True),
            ],
            skeletal=1, roots=1,
        )
        clip = paa.parse_paa(data)
        self.assertEqual(paa.key_byte_total(clip), clip.key_bytes)

    def test_bit31_alone_is_a_word_table_not_the_tag_blob(self) -> None:
        """Reading it as a byte blob lands mid-prelude and yields a garbage duration."""

        header = paa.PAR_MAGIC + bytes([2, 3]) + bytes(range(10))
        track = _track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (40, (0.0, 0.0, 0.0, 1.0))])
        words = [0x1234, 0x5678, 0x9ABC]
        data = (
            header
            + struct.pack("<I", paa.FLAG_WORD_TABLE | paa.FLAG_UNIT_SCALE)
            + struct.pack("<H", len(words)) + struct.pack(f"<{len(words)}H", *words)
            + struct.pack("<f", 0.97222)
            + struct.pack("<f", 40 / 30)
            + struct.pack("<HHI", 1, 0, len(track) - 10)
            + track
        )
        clip = paa.parse_paa(data)
        self.assertAlmostEqual(clip.duration, 40 / 30, places=5)
        self.assertEqual(clip.frame_count, 41)
        self.assertEqual(clip.tag, "")
        self.assertEqual(paa.key_byte_total(clip), clip.key_bytes)

    def test_rejects_a_foreign_container(self) -> None:
        with self.assertRaises(paa.PaaFormatError):
            paa.parse_paa(b"NOPE" + bytes(64))

    def test_rejects_an_unsupported_version(self) -> None:
        data = bytearray(_clip_bytes([_track(0x1111, rotation=[(0, (0, 0, 0, 1))])], skeletal=1, roots=0))
        data[5] = 9
        with self.assertRaises(paa.PaaFormatError):
            paa.parse_paa(bytes(data))


class PackedCodecTests(unittest.TestCase):
    def test_packed_records_decode_at_one_sixty_fourth(self) -> None:
        data = _packed_clip_bytes(
            [_packed_track(0x1111, rotation=[(0, (0, 0, 0, 64)), (26, (-40, 10, -10, 48))],
                           translation=[(0, (0, 0, 0)), (26, (2, -3, 4))])],
            [_track(0x2222, rotation=[(0, (0.0, 0.0, 0.0, 1.0))],
                    translation=[(0, (0.5, 0.25, 0.125))])],
            duration=26 / 30,
        )
        clip = paa.parse_paa(data)
        self.assertEqual(len(clip.tracks), 2)
        packed, root = clip.tracks
        self.assertTrue(packed.packed)
        self.assertFalse(root.packed)
        self.assertEqual(packed.rotation[0][1], (0.0, 0.0, 0.0, 1.0))
        self.assertAlmostEqual(packed.rotation[1][1][0], -40 / 64)
        self.assertAlmostEqual(packed.translation[1][1][2], 4 / 64)
        self.assertEqual(paa.key_byte_total(clip), clip.key_bytes)

    def test_packed_root_records_stay_half_precision(self) -> None:
        """Packed clips do not widen root translation the way standard clips do."""

        data = _packed_clip_bytes(
            [_packed_track(0x1111, rotation=[(0, (0, 0, 0, 64))])],
            [_track(0x2222, translation=[(0, (0.0, 0.0, 0.0)), (10, (1.5, 0.0, 0.0))])],
            duration=10 / 30,
        )
        clip = paa.parse_paa(data)
        self.assertAlmostEqual(clip.tracks[1].translation[1][1][0], 1.5, places=3)
        self.assertEqual(paa.key_byte_total(clip), clip.key_bytes)

    def test_packed_frames_are_single_bytes(self) -> None:
        data = _packed_clip_bytes(
            [_packed_track(0x1111, rotation=[(0, (0, 0, 0, 64)), (200, (0, 0, 0, 64))])],
            [],
            duration=200 / 30,
        )
        clip = paa.parse_paa(data)
        self.assertEqual([frame for frame, _v in clip.tracks[0].rotation], [0, 200])
        self.assertEqual(clip.frame_count, 201)


class PoseTests(unittest.TestCase):
    def test_an_unanimated_bone_keeps_its_bind_pose(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0))])], skeletal=1, roots=0))
        transforms = pose.local_transforms(skeleton, clip, 0.0)
        self.assertEqual(transforms[1].translation, (0.0, 0.5, 0.0))
        for got, want in zip(transforms[1].rotation, skeleton.bones[1].rotation):
            self.assertAlmostEqual(got, want, places=6)

    def test_identity_delta_reproduces_the_bind_pose(self) -> None:
        """Keys are deltas, so an identity key must not flatten a rotated bind rotation."""

        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x2222, rotation=[(0, (0.0, 0.0, 0.0, 1.0))])], skeletal=1, roots=0))
        transform = pose.local_transforms(skeleton, clip, 0.0)[1]
        for got, want in zip(transform.rotation, skeleton.bones[1].rotation):
            self.assertAlmostEqual(got, want, places=6)

    def test_translation_delta_is_rotated_into_the_parent_frame(self) -> None:
        """The bind rotation turns +X into -Z, which is what keeps root motion pointing forward."""

        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x2222, translation=[(0, (2.0, 0.0, 0.0))])], skeletal=1, roots=0))
        transform = pose.local_transforms(skeleton, clip, 0.0)[1]
        self.assertAlmostEqual(transform.translation[0], 0.0, places=5)
        self.assertAlmostEqual(transform.translation[1], 0.5, places=5)
        self.assertAlmostEqual(transform.translation[2], -2.0, places=5)

    def test_keys_interpolate_between_sparse_frames(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, translation=[(0, (0.0, 0.0, 0.0)), (10, (1.0, 0.0, 0.0))])],
            skeletal=1, roots=0))
        halfway = pose.local_transforms(skeleton, clip, 5.0)[0]
        self.assertAlmostEqual(halfway.translation[0], 0.5, places=3)

    def test_sampling_past_the_last_key_clamps(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, translation=[(0, (0.0, 0.0, 0.0)), (10, (1.0, 0.0, 0.0))])],
            skeletal=1, roots=0))
        beyond = pose.local_transforms(skeleton, clip, 999.0)[0]
        self.assertAlmostEqual(beyond.translation[0], 1.0, places=3)

    def test_world_position_accumulates_through_the_parent(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0))])], skeletal=1, roots=0))
        positions = pose.world_positions(skeleton, clip, 0.0)
        self.assertAlmostEqual(positions[1][1], 1.5, places=5)


class GltfTests(unittest.TestCase):
    def test_glb_carries_the_hierarchy_and_only_the_channels_that_exist(self) -> None:
        """A rotation-only track must not bake repeated translation and scale samples."""

        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (30, (0.0, 0.0, 0.0, 1.0))])],
            skeletal=1, roots=0))
        document, blob = gltf.build_gltf(skeleton, clip, name="clip")
        self.assertEqual(document["scenes"][0]["nodes"], [0])
        self.assertEqual(document["nodes"][0]["children"], [1])
        channels = document["animations"][0]["channels"]
        self.assertEqual([c["target"]["path"] for c in channels], ["rotation"])
        self.assertTrue(all(c["target"]["node"] == 0 for c in channels))
        self.assertEqual(document["buffers"][0]["byteLength"], len(blob))

    def test_each_channel_is_baked_on_its_own_key_frames(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111,
                    rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (10, (0.0, 0.0, 0.0, 1.0))],
                    translation=[(0, (0.0, 0.0, 0.0)), (4, (1.0, 0.0, 0.0)), (9, (2.0, 0.0, 0.0))])],
            skeletal=1, roots=0))
        document, _blob = gltf.build_gltf(skeleton, clip)
        animation = document["animations"][0]
        counts = {}
        for channel in animation["channels"]:
            sampler = animation["samplers"][channel["sampler"]]
            counts[channel["target"]["path"]] = document["accessors"][sampler["input"]]["count"]
        self.assertEqual(counts, {"rotation": 2, "translation": 3})

    def test_an_unanimated_bone_gets_no_channels(self) -> None:
        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0))])], skeletal=1, roots=0))
        document, _blob = gltf.build_gltf(skeleton, clip)
        nodes = {c["target"]["node"] for c in document["animations"][0]["channels"]}
        self.assertEqual(nodes, {0})

    def test_glb_container_is_well_formed(self) -> None:
        import tempfile

        skeleton = _two_bone_skeleton()
        clip = paa.parse_paa(_clip_bytes(
            [_track(0x1111, rotation=[(0, (0.0, 0.0, 0.0, 1.0)), (30, (0.0, 0.0, 0.0, 1.0))])],
            skeletal=1, roots=0))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clip.glb"
            written = gltf.write_glb(path, skeleton, clip)
            raw = path.read_bytes()
        self.assertEqual(len(raw), written)
        magic, version, total = struct.unpack_from("<4sII", raw, 0)
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(total, len(raw))
        json_length, json_type = struct.unpack_from("<II", raw, 12)
        self.assertEqual(json_type, 0x4E4F534A)
        document = json.loads(raw[20:20 + json_length])
        self.assertEqual(document["asset"]["version"], "2.0")
        binary_length, binary_type = struct.unpack_from("<II", raw, 20 + json_length)
        self.assertEqual(binary_type, 0x004E4942)
        self.assertEqual(20 + json_length + 8 + binary_length, len(raw))


@pytest.mark.real_game
@unittest.skipUnless(
    VANILLA_MOTION.is_dir() and VANILLA_SKELETON.is_file(),
    "needs the extracted vanilla motion tree",
)
class VanillaCorpusTests(unittest.TestCase):
    """Reads the locally extracted game assets, so it is opt-in behind `real_game`."""

    def setUp(self) -> None:
        self.clips = sorted(VANILLA_MOTION.rglob("*.paa"))

    def test_every_clip_decodes_and_reproduces_its_key_byte_total(self) -> None:
        self.assertTrue(self.clips, "no clips found")
        packed_seen = False
        for path in self.clips:
            clip = paa.parse_paa(path.read_bytes(), name=path.name)
            # The header's key-byte total is an independent check on the whole walk.
            self.assertEqual(paa.key_byte_total(clip), clip.key_bytes, path.name)
            packed_seen = packed_seen or any(track.packed for track in clip.tracks)
        self.assertTrue(packed_seen, "expected at least one packed LOD clip in the corpus")

    def test_packed_rotations_decode_to_unit_quaternions(self) -> None:
        """The 1/64 fixed-point scale is what makes the byte-quantised keys come out unit."""

        checked = 0
        for path in self.clips:
            clip = paa.parse_paa(path.read_bytes(), name=path.name)
            for track in clip.tracks:
                if not track.packed:
                    continue
                for frame, values in track.rotation:
                    length = math.sqrt(sum(c * c for c in values))
                    self.assertAlmostEqual(length, 1.0, delta=0.05, msg=f"{path.name} f{frame}")
                    checked += 1
        self.assertGreater(checked, 100, "no packed rotation keys were exercised")

    def test_rotation_keys_are_unit_quaternions(self) -> None:
        for path in self.clips[:40]:
            try:
                clip = paa.parse_paa(path.read_bytes(), name=path.name)
            except paa.PaaFormatError:
                continue
            for track in clip.tracks:
                for frame, values in track.rotation:
                    length = math.sqrt(sum(c * c for c in values))
                    self.assertAlmostEqual(length, 1.0, places=2, msg=f"{path.name} f{frame}")

    def test_a_run_clip_travels_a_plausible_distance(self) -> None:
        from cdmw.modding.skeleton_parser import parse_pab

        path = VANILLA_MOTION / "1_pc/1_phm/cd_phm_longsword_00_00_normal_move_run_f_weapon_out_000.paa"
        if not path.is_file():
            self.skipTest("run clip not in this extraction")
        skeleton = parse_pab(VANILLA_SKELETON.read_bytes(), VANILLA_SKELETON.name)
        clip = paa.parse_paa(path.read_bytes())
        start = pose.world_positions(skeleton, clip, 0.0)[0]
        end = pose.world_positions(skeleton, clip, float(clip.last_frame))[0]
        travelled = math.dist(start, end)
        speed = travelled / clip.duration
        self.assertGreater(speed, 3.0, "a run should cover ground")
        self.assertLess(speed, 8.0, "but not teleport")
        # Hips stay at roughly standing height throughout, which a bad compose would break.
        for frame in (0, clip.last_frame // 2, clip.last_frame):
            hips = pose.world_positions(skeleton, clip, float(frame))[0]
            self.assertGreater(hips[1], 0.6)
            self.assertLess(hips[1], 1.2)


if __name__ == "__main__":
    unittest.main()
