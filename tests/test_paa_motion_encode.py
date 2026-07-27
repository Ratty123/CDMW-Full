"""Gates for the `.paa` writer.

The corpus gate is the one that matters: parse every shipped clip, write it back, and
require the bytes to be identical. It is marked `real_game` because it reads the
extracted vanilla motion tree.
"""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.paa_motion import encode as paa_encode  # noqa: E402
from tools.paa_motion import format as paa  # noqa: E402

VANILLA_MOTION = Path("workspace/placement_studio/vanilla/character/motion")


def _clip(**overrides) -> paa.MotionClip:
    base = dict(
        version=paa.PAA_VERSION,
        flags=0,
        tag="",
        unit_scale=0.0,
        skeleton_path="",
        duration=1.0,
        key_bytes=0,
        skeletal_bone_count=1,
        root_bone_count=0,
        tracks=(
            paa.BoneTrack(
                name_hash=0x1234ABCD,
                scale=((0, (1.0, 1.0, 1.0)),),
                rotation=((0, (0.0, 0.0, 0.0, 1.0)),),
                translation=((0, (0.5, 0.25, -0.5)),),
            ),
        ),
    )
    base.update(overrides)
    return paa.MotionClip(**base)


class SynthesisTests(unittest.TestCase):
    def test_a_hand_built_clip_round_trips(self) -> None:
        clip = _clip()
        data = paa_encode.encode_paa(clip)
        again = paa.parse_paa(data, name="synthetic")
        self.assertEqual(again.tracks[0].name_hash, 0x1234ABCD)
        self.assertEqual(again.skeletal_bone_count, 1)
        self.assertAlmostEqual(again.duration, 1.0, places=6)
        self.assertEqual(paa_encode.encode_paa(again), data)

    def test_output_starts_with_the_container_header(self) -> None:
        data = paa_encode.encode_paa(_clip())
        self.assertEqual(data[:4], paa.PAR_MAGIC)
        self.assertEqual((data[4], data[5]), paa.PAA_VERSION)
        self.assertEqual(data[6:16], bytes(range(10)))

    def test_key_bytes_in_the_header_matches_the_tracks(self) -> None:
        clip = _clip()
        data = paa_encode.encode_paa(clip)
        parsed = paa.parse_paa(data, name="synthetic")
        self.assertEqual(parsed.key_bytes, paa.key_byte_total(parsed))

    def test_half_precision_values_survive_the_round_trip(self) -> None:
        # Every half has an exact float value, so this has to be lossless both ways.
        values = (0.5, -0.25, 1.0, -0.0, 0.0009765625)
        clip = _clip(
            tracks=(
                paa.BoneTrack(
                    name_hash=1,
                    translation=tuple((i, (v, v, v)) for i, v in enumerate(values)),
                ),
            )
        )
        parsed = paa.parse_paa(paa_encode.encode_paa(clip), name="halves")
        got = [key[1][0] for key in parsed.tracks[0].translation]
        self.assertEqual(got, list(values))

    def test_packed_components_quantise_back_to_the_same_bytes(self) -> None:
        clip = _clip(
            flags=paa.FLAG_PACKED,
            tracks=(
                paa.BoneTrack(
                    name_hash=7,
                    packed=True,
                    rotation=((0, (0.5, -0.5, 0.25, 1.0)),),
                ),
            ),
        )
        data = paa_encode.encode_paa(clip)
        parsed = paa.parse_paa(data, name="packed")
        self.assertEqual(parsed.tracks[0].rotation[0][1], (0.5, -0.5, 0.25, 1.0))
        self.assertEqual(paa_encode.encode_paa(parsed), data)

    def test_bounds_span_follows_the_second_frame_bit(self) -> None:
        one = paa_encode.encode_paa(_clip(flags=paa.FLAG_BOUNDS))
        two = paa_encode.encode_paa(_clip(flags=paa.FLAG_BOUNDS | paa.FLAG_BOUNDS_SECOND))
        self.assertEqual(len(two) - len(one), 40)


class RejectionTests(unittest.TestCase):
    def test_unsorted_frames_are_refused(self) -> None:
        clip = _clip(
            tracks=(paa.BoneTrack(name_hash=1, translation=((5, (0.0,) * 3), (2, (0.0,) * 3))),)
        )
        with self.assertRaises(paa_encode.PaaEncodeError):
            paa_encode.encode_paa(clip)

    def test_bone_counts_must_match_the_tracks(self) -> None:
        with self.assertRaises(paa_encode.PaaEncodeError):
            paa_encode.encode_paa(_clip(skeletal_bone_count=4))

    def test_a_packed_component_out_of_range_is_refused(self) -> None:
        clip = _clip(
            flags=paa.FLAG_PACKED,
            tracks=(paa.BoneTrack(name_hash=1, packed=True, translation=((0, (99.0, 0.0, 0.0)),)),),
        )
        with self.assertRaises(paa_encode.PaaEncodeError):
            paa_encode.encode_paa(clip)

    def test_a_wrong_component_count_is_refused(self) -> None:
        clip = _clip(tracks=(paa.BoneTrack(name_hash=1, rotation=((0, (0.0, 0.0, 0.0)),)),))
        with self.assertRaises(paa_encode.PaaEncodeError):
            paa_encode.encode_paa(clip)

    def test_another_version_is_not_written(self) -> None:
        with self.assertRaises(paa_encode.PaaEncodeError):
            paa_encode.encode_paa(_clip(version=(9, 9)))


class EditTests(unittest.TestCase):
    def test_retiming_a_clip_changes_only_the_frames(self) -> None:
        clip = _clip(
            tracks=(
                paa.BoneTrack(
                    name_hash=1,
                    translation=((0, (0.5, 0.0, 0.0)), (10, (0.25, 0.0, 0.0))),
                ),
            )
        )
        slowed = paa.MotionClip(
            **{
                **clip.__dict__,
                "tracks": (
                    paa.BoneTrack(
                        name_hash=1,
                        translation=tuple((f * 2, v) for f, v in clip.tracks[0].translation),
                    ),
                ),
            }
        )
        parsed = paa.parse_paa(paa_encode.encode_paa(slowed), name="slowed")
        self.assertEqual([f for f, _v in parsed.tracks[0].translation], [0, 20])


@pytest.mark.real_game
@unittest.skipUnless(VANILLA_MOTION.is_dir(), "needs the extracted vanilla motion tree")
class VanillaRoundTripTests(unittest.TestCase):
    """Write back every shipped clip and require the source bytes."""

    def test_every_clip_rebuilds_byte_for_byte(self) -> None:
        clips = sorted(VANILLA_MOTION.rglob("*.paa"))
        self.assertTrue(clips, "no clips found")
        failures = []
        for path in clips:
            data = path.read_bytes()
            if not paa_encode.rebuild_is_exact(data, name=path.name):
                failures.append(path.name)
        self.assertEqual(failures, [], f"{len(failures)} of {len(clips)} did not rebuild exactly")

    def test_the_corpus_covers_both_codecs_and_both_bounds_shapes(self) -> None:
        """A green round trip over one variant would not prove much."""

        packed = standard = one_frame = two_frame = 0
        for path in sorted(VANILLA_MOTION.rglob("*.paa")):
            flags = struct.unpack_from("<I", path.read_bytes(), 0x10)[0]
            packed += bool(flags & paa.FLAG_PACKED)
            standard += not flags & paa.FLAG_PACKED
            if flags & paa.FLAG_BOUNDS:
                if flags & paa.FLAG_BOUNDS_SECOND:
                    two_frame += 1
                else:
                    one_frame += 1
        self.assertGreater(packed, 0, "no packed clips in the corpus")
        self.assertGreater(standard, 0, "no standard clips in the corpus")
        self.assertGreater(two_frame, 0, "no two-frame bounds clips in the corpus")
