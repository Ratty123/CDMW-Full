from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from cdmw.core.archive_format import crypt_chacha20_filename, lz4_block, try_decrypt_archive_entry_data
from cdmw.models import ArchiveEntry
from cdmw.modding.animation_parser import parse_paa_animation_clip
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.skeleton_variation_parser import (
    PABC_RECORD_OFFSET,
    PABC_RECORD_STRIDE,
    apply_skeleton_variation_to_mesh,
    parse_pabc_skeleton_variation,
    parse_pamt_morph_target_set,
)


class RiggingBinaryParserTests(unittest.TestCase):
    @staticmethod
    def _transform(*, position: tuple[float, float, float]) -> tuple[float, ...]:
        return (1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, *position)

    def _pamt_payload(self, expression_name: bytes = b"jawOpen") -> bytes:
        root_hash = 0x11111111
        bone_name = b"Root"
        targets = (
            (0xAAAA0001, b"base", 0, self._transform(position=(0.0, 0.0, 0.0))),
            (0xAAAA0002, expression_name, 10, self._transform(position=(0.0, 2.0, 0.0))),
        )
        data = bytearray(b"PAR " + bytes(12))
        data.extend(struct.pack("<H", 1))
        data.extend(struct.pack("<IB", root_hash, len(bone_name)))
        data.extend(bone_name)
        data.extend(struct.pack("<h", -1))
        data.extend(struct.pack("<H", len(targets)))
        for target_hash, name, marker, transform in targets:
            data.extend(struct.pack("<IB", target_hash, len(name)))
            data.extend(name)
            data.extend(struct.pack("<H", marker))
            data.extend(struct.pack("<20f", *(transform + transform)))
        data.extend(b"\x00\x00")
        return bytes(data)

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

    def test_pabc_parser_recognizes_the_exact_duplicate_table_variant(self) -> None:
        data = bytearray(PABC_RECORD_OFFSET + PABC_RECORD_STRIDE)
        data[0:4] = b"PAR "
        data[4] = 0x35
        struct.pack_into("<I", data, 0x10, 1)
        struct.pack_into("<I48f", data, PABC_RECORD_OFFSET, 0x11111111, *([1.0] * 48))
        primary_table = bytes(data[PABC_RECORD_OFFSET:])
        data.extend(struct.pack("<II", 0xAABBCCDD, 1))
        data.extend(primary_table)

        variation = parse_pabc_skeleton_variation(bytes(data), "duplicate.pabc")

        self.assertTrue(variation.duplicate_record_table)
        self.assertEqual(0xAABBCCDD, variation.secondary_table_tag)
        self.assertEqual("bone_hash_table_stride_196_exact_duplicate", variation.confidence)

        data[-1] ^= 0x01
        with self.assertRaisesRegex(ValueError, "duplicate table does not match"):
            parse_pabc_skeleton_variation(bytes(data), "tampered.pabc")

    def test_pamt_parser_recovers_named_facial_targets_and_bone_transforms(self) -> None:
        morphs = parse_pamt_morph_target_set(self._pamt_payload(), "face.pamt")

        self.assertEqual(1, morphs.bone_count)
        self.assertEqual(2, morphs.target_count)
        self.assertEqual(("base", "jawOpen"), tuple(target.name for target in morphs.targets))
        self.assertEqual(10, morphs.targets[1].marker)
        self.assertEqual((0.0, 2.0, 0.0), morphs.targets[1].bone_transforms[0].global_transform.position)
        self.assertEqual("pamt_skeleton_morph_targets_v1", morphs.parser_mode)

    def test_pamt_parser_preserves_utf8_target_names(self) -> None:
        target_name = "기본얼굴_비대칭"

        morphs = parse_pamt_morph_target_set(
            self._pamt_payload(target_name.encode("utf-8")),
            "localized.pamt",
        )

        self.assertEqual(target_name, morphs.targets[1].name)

    def test_encrypted_in_archive_pamt_validates_as_a_compressed_par_payload(self) -> None:
        if lz4_block is None:
            self.skipTest("lz4 is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plain = self._pamt_payload()
            compressed = lz4_block.compress(plain, store_size=False)
            encrypted = crypt_chacha20_filename(compressed, "phw_damian.pamt")
            entry = ArchiveEntry(
                path="character/model/1_pc/2_phw/phw_damian.pamt",
                pamt_path=root / "0.pamt",
                paz_file=root / "0.paz",
                offset=0,
                comp_size=len(compressed),
                orig_size=len(plain),
                flags=0x32,
                paz_index=0,
            )

            decrypted, note = try_decrypt_archive_entry_data(entry, encrypted)

            self.assertEqual("ChaCha20", note)
            self.assertEqual(plain, lz4_block.decompress(decrypted, uncompressed_size=len(plain)))

    def test_pabc_neutral_and_pamt_target_deform_the_mesh_without_changing_source(self) -> None:
        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        neutral_global = list(identity)
        neutral_global[12] = 1.0
        local_values = self._transform(position=(1.0, 0.0, 0.0)) + (1.0,) * 6
        pabc = bytearray(PABC_RECORD_OFFSET + PABC_RECORD_STRIDE + 4)
        pabc[0:4] = b"PAR "
        struct.pack_into("<I", pabc, 0x10, 1)
        struct.pack_into(
            "<I48f",
            pabc,
            PABC_RECORD_OFFSET,
            0x11111111,
            *(tuple(neutral_global) + tuple(neutral_global) + local_values),
        )
        skeleton = Skeleton(
            bones=[
                Bone(
                    index=0,
                    name="Root",
                    name_hash=0x11111111,
                    parent_index=-1,
                    bind_matrix=identity,
                    inv_bind_matrix=identity,
                )
            ],
            bone_count=1,
        )
        source = ParsedMesh(
            path="face.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="Face",
                    vertices=[(0.0, 0.0, 0.0)],
                    normals=[(0.0, 0.0, 1.0)],
                    bone_indices=[(0,)],
                    bone_weights=[(1.0,)],
                    vertex_count=1,
                )
            ],
            total_vertices=1,
            has_bones=True,
        )

        deformed = apply_skeleton_variation_to_mesh(
            source,
            skeleton,
            (0,),
            parse_pabc_skeleton_variation(bytes(pabc), "face.pabc", skeleton=skeleton),
            morph_target_set=parse_pamt_morph_target_set(self._pamt_payload(), "face.pamt"),
        )

        self.assertEqual([(0.0, 0.0, 0.0)], source.submeshes[0].vertices)
        self.assertEqual([(1.0, 0.0, 0.0)], deformed.submeshes[0].vertices)
        self.assertEqual([(1.0, 2.0, 0.0)], deformed.submeshes[0].morph_targets["jawOpen"])
        self.assertEqual([(0.0, 0.0, 1.0)], deformed.submeshes[0].normals)

    def test_pamt_targets_can_be_applied_without_a_pabc_neutral_variation(self) -> None:
        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        skeleton = Skeleton(
            bones=[
                Bone(
                    index=0,
                    name="Root",
                    name_hash=0x11111111,
                    parent_index=-1,
                    bind_matrix=identity,
                    inv_bind_matrix=identity,
                )
            ],
            bone_count=1,
        )
        source = ParsedMesh(
            path="creature.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="Creature",
                    vertices=[(0.0, 0.0, 0.0)],
                    normals=[(0.0, 0.0, 1.0)],
                    bone_indices=[(0,)],
                    bone_weights=[(1.0,)],
                    vertex_count=1,
                )
            ],
            total_vertices=1,
            has_bones=True,
        )

        deformed = apply_skeleton_variation_to_mesh(
            source,
            skeleton,
            (0,),
            None,
            morph_target_set=parse_pamt_morph_target_set(self._pamt_payload(), "creature.pamt"),
        )

        self.assertEqual([(0.0, 0.0, 0.0)], deformed.submeshes[0].vertices)
        self.assertEqual([(0.0, 2.0, 0.0)], deformed.submeshes[0].morph_targets["jawOpen"])

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
