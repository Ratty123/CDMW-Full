from __future__ import annotations

import struct
import unittest

from cdmw.modding.animation_parser import parse_paa_animation_clip
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.skeleton_variation_parser import PABC_RECORD_OFFSET, PABC_RECORD_STRIDE, parse_pabc_skeleton_variation


class RiggingBinaryParserTests(unittest.TestCase):
    def test_pabc_parser_binds_stride_records_to_pab_bone_hashes(self) -> None:
        skeleton = Skeleton(
            bones=[
                Bone(index=0, name="Root", name_hash=0x11111111),
                Bone(index=1, name="Spine", name_hash=0x22222222),
            ],
            bone_count=2,
        )
        data = bytearray(PABC_RECORD_OFFSET + PABC_RECORD_STRIDE * 2 + 4)
        data[0:4] = b"PAR "
        struct.pack_into("<I", data, 0x10, 2)
        for record_index, bone_hash in enumerate((0x11111111, 0x22222222)):
            offset = PABC_RECORD_OFFSET + record_index * PABC_RECORD_STRIDE
            struct.pack_into("<I48f", data, offset, bone_hash, *([float(record_index + 1)] * 48))

        variation = parse_pabc_skeleton_variation(bytes(data), "body.pabc", skeleton=skeleton)

        self.assertEqual(2, variation.record_count)
        self.assertEqual(2, variation.matched_record_count)
        self.assertEqual("all_records_match_pab_bone_hashes", variation.confidence)
        self.assertEqual("Root", variation.records[0].bone_name)
        self.assertEqual(1, variation.records[1].bone_index)
        self.assertEqual(4, variation.tail_size)
        self.assertEqual(3, len(variation.records[0].matrix_blocks))
        self.assertEqual(16, len(variation.records[0].matrix_blocks[0]))

    def test_paa_parser_builds_clip_only_from_exact_hash_owned_tables(self) -> None:
        skeleton = Skeleton(
            bones=[Bone(index=3, name="Spine", name_hash=0xAABBCCDD)],
            bone_count=4,
        )
        data = bytearray(160)
        data[0:4] = b"PAR "
        row_offset = 0x40
        struct.pack_into("<I", data, row_offset - 8, 0xAABBCCDD)
        for frame in range(6):
            struct.pack_into("<H4e", data, row_offset + frame * 10, frame, 0.0, 0.0, frame / 20.0, 1.0)

        clip, summary = parse_paa_animation_clip(bytes(data), "owned.paa", skeleton=skeleton, frame_rate=30.0)

        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertTrue(summary.ready)
        self.assertEqual(1, summary.exact_bone_hash_track_count)
        self.assertEqual(30.0, summary.frame_rate)
        self.assertEqual("parser_default_30fps", summary.frame_rate_source)
        self.assertEqual("inferred", summary.frame_rate_confidence)
        self.assertEqual("default_30fps_unproven", summary.timing_status)
        self.assertFalse(clip.game_accurate_timing)
        self.assertEqual("xyzw", summary.quaternion_order)
        self.assertEqual(3, clip.tracks[0].bone_index)
        self.assertEqual("Spine", clip.tracks[0].bone_name)
        self.assertEqual(6, len(clip.tracks[0].rotation_keyframes))
        self.assertGreater(abs(clip.tracks[0].rotation_keyframes[-1].rotation_degrees[2]), 0.0)

    def test_paa_parser_rejects_unowned_keyframe_tables(self) -> None:
        skeleton = Skeleton(
            bones=[Bone(index=0, name="Root", name_hash=0x11111111)],
            bone_count=1,
        )
        data = bytearray(160)
        data[0:4] = b"PAR "
        row_offset = 0x40
        struct.pack_into("<I", data, row_offset - 8, 0xDEADBEEF)
        for frame in range(6):
            struct.pack_into("<H4e", data, row_offset + frame * 10, frame, 0.0, 0.0, frame / 20.0, 1.0)

        clip, summary = parse_paa_animation_clip(bytes(data), "unowned.paa", skeleton=skeleton)

        self.assertIsNone(clip)
        self.assertFalse(summary.ready)
        self.assertEqual(0, summary.exact_bone_hash_track_count)

    def test_paa_parser_marks_proven_sequence_fps_only_when_source_is_proven(self) -> None:
        skeleton = Skeleton(
            bones=[Bone(index=0, name="Root", name_hash=0xAABBCCDD)],
            bone_count=1,
        )
        data = bytearray(160)
        data[0:4] = b"PAR "
        row_offset = 0x40
        struct.pack_into("<I", data, row_offset - 8, 0xAABBCCDD)
        for frame in range(6):
            struct.pack_into("<H4e", data, row_offset + frame * 10, frame, 0.0, 0.0, 0.0, 1.0)

        clip, summary = parse_paa_animation_clip(
            bytes(data),
            "owned.paa",
            skeleton=skeleton,
            frame_rate=60.0,
            frame_rate_source="source.paseq:_framesPerSecond",
            frame_rate_confidence="proven",
        )

        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertEqual(60.0, summary.frame_rate)
        self.assertEqual("source.paseq:_framesPerSecond", summary.frame_rate_source)
        self.assertEqual("proven", summary.frame_rate_confidence)
        self.assertEqual("game_sequence_fps_proven", summary.timing_status)
        self.assertTrue(clip.game_accurate_timing)
        self.assertAlmostEqual(5.0 / 60.0, clip.duration_seconds)

    def test_paa_parser_attaches_paseqc_lane_segment_evidence(self) -> None:
        skeleton = Skeleton(
            bones=[Bone(index=2, name="Hand", name_hash=0xAABBCCDD)],
            bone_count=3,
            path="character/model/hand.pab",
        )
        data = bytearray(180)
        data[0:4] = b"PAR "
        row_offset = 0x40
        struct.pack_into("<I", data, row_offset - 8, 0xAABBCCDD)
        for frame in range(6):
            struct.pack_into("<H4e", data, row_offset + frame * 10, frame, 0.0, 0.0, 0.0, 1.0)

        clip, summary = parse_paa_animation_clip(
            bytes(data),
            "character/motion/hand_idle.paa",
            skeleton=skeleton,
            sequence_path="sequencer/binary__/test.paseqc",
            sequence_lane_index=4,
            sequence_lane_source_offset=128,
            sequence_lane_confidence="asset_reference",
        )

        self.assertTrue(summary.ready)
        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertEqual(1, len(clip.sequence_segments))
        segment = clip.sequence_segments[0]
        self.assertEqual("sequencer/binary__/test.paseqc", segment.sequence_path)
        self.assertEqual("character/motion/hand_idle.paa", segment.clip_path)
        self.assertEqual(4, segment.lane_index)
        self.assertEqual(128, segment.lane_source_offset)
        self.assertEqual(0, segment.start_frame)
        self.assertEqual(5, segment.end_frame)
        self.assertEqual("character/model/hand.pab", segment.skeleton_source)
        self.assertEqual("paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown", segment.status)
        confidence = dict(segment.field_confidence)
        self.assertEqual("inferred", confidence["sequence_path"])
        self.assertEqual("proven", confidence["clip_path"])
        self.assertEqual("unknown", confidence["blend_weight"])


if __name__ == "__main__":
    unittest.main()
