import json
import struct
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from cdmw.core.archive import (
    archive_entry_role,
    build_binary_sidecar_corpus_report,
    build_binary_sidecar_analysis_json,
    build_meshinfo_preview,
    build_par_structured_preview,
    build_simplified_text_asset_summary,
    build_structured_asset_preview,
)
from cdmw.core.archive_format import crypt_chacha20_filename, lz4_block, try_decrypt_archive_entry_data
from cdmw.models import ArchiveEntry


def _entry(path: str, root: Path) -> ArchiveEntry:
    pamt_path = root / "0009" / "0.pamt"
    paz_path = root / "0009" / "0.paz"
    pamt_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


def _indexes(entries: tuple[ArchiveEntry, ...]) -> tuple[dict[str, tuple[ArchiveEntry, ...]], dict[str, tuple[ArchiveEntry, ...]]]:
    path_index: dict[str, tuple[ArchiveEntry, ...]] = {}
    basename_index: dict[str, tuple[ArchiveEntry, ...]] = {}
    for entry in entries:
        normalized_path = entry.path.replace("\\", "/").strip().lower()
        basename = PurePosixPath(normalized_path).name.lower()
        path_index.setdefault(normalized_path, ())
        path_index[normalized_path] = (*path_index[normalized_path], entry)
        basename_index.setdefault(basename, ())
        basename_index[basename] = (*basename_index[basename], entry)
    return path_index, basename_index


def _decl(name: str, declared_type: str, descriptor: bytes) -> bytes:
    name_bytes = name.encode("ascii")
    type_bytes = declared_type.encode("ascii")
    return struct.pack("<I", len(name_bytes)) + name_bytes + struct.pack("<I", len(type_bytes)) + type_bytes + descriptor


def _seqmt_sample(columns: int, rows: int, *, flags: int = 0, extra_payload: bytes = b"") -> bytes:
    frame_count = columns * rows
    frame_records = bytes(
        value & 0xFF
        for index in range(frame_count)
        for value in (index, 255 - index, (index * 3) & 0xFF, 128 + (index % 64))
    )
    return (
        b"DDS!"
        + bytes([1])
        + struct.pack("<H", columns)
        + struct.pack("<H", rows)
        + bytes([flags & 0xFF])
        + struct.pack("<H", frame_count)
        + frame_records
        + extra_payload
    )


def _paccd_sample() -> bytes:
    header = struct.pack("<IIIIIIII", 0, 14, 2, 0, 0x01050000, 0, 3, 0x00FA0000)
    rows = bytearray()
    for slot_index in range(14):
        row = bytearray(19)
        row[0:3] = bytes((slot_index * 3 % 101, 50, 100))
        row[6] = 100 if slot_index % 2 == 0 else 0
        row[10:13] = bytes((50, 50, 50))
        rows.extend(row)
    return header + bytes(rows)


def _paseq_sample() -> bytes:
    data = bytearray(b"PAR " + b"\x00" * 12)
    data.extend(_decl("_animationFileNames", "staticstringA", bytes.fromhex("0A 00 01 00 20 10 00 00")))
    data.extend(_decl("_effectFileName", "staticstringA", bytes.fromhex("01 00 01 00 40 00 00 00")))
    data.extend(_decl("_startFrame", "uint32", bytes.fromhex("00 00 04 00 20 00 00 00")))
    data.extend(_decl("_endFrame", "uint32", bytes.fromhex("00 00 04 00 20 00 00 00")))
    data.extend(_decl("_framesPerSecond", "int32", bytes.fromhex("00 00 04 00 60 00 00 00")))
    data.extend(_decl("_framesPerSecond", "int32", bytes.fromhex("00 00 04 00 60 00 00 00")))
    data.extend(_decl("_startBlendingTime", "float", bytes.fromhex("00 00 04 00 20 00 00 00")))
    data.extend(_decl("_endBlendingTime", "float", bytes.fromhex("00 00 04 00 20 00 00 00")))
    data.extend(_decl("_eventTriggerNames", "staticstringA", bytes.fromhex("0A 00 01 00 20 10 00 00")))
    data.extend(b"StartEvent_PlayerAttack\x00LoopPhase_Main\x00EndEvent_Recover\x00")
    data.extend(b"actionchart/bin__/animation/test_combo_attack.paa\x00")
    data.extend(b"character/bin__/animation/test_combo.hkx\x00")
    data.extend(b"effect/bin__/test_combo_hit.paem\x00")
    data.extend(b"character/model/test_actor.pac\x00")
    data.extend(struct.pack("<I", 30) + b"LengthPrefixedFpsLikeString_30")
    while len(data) % 4:
        data.append(0)
    data.extend(struct.pack("<IIff", 0, 90, 1.25, 30.0))
    return bytes(data)


class ArchiveStructuredAssetPreviewTests(unittest.TestCase):
    def test_meshinfo_preview_and_json_include_sidecar_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("character/model/test.meshinfo", root)
            model = _entry("character/model/test.pac", root)
            path_index, basename_index = _indexes((source, model))
            data = bytearray(256)
            data[0:4] = b"PAR "
            data[0x20:0x20 + len(b"PhysicsBodyList\x00")] = b"PhysicsBodyList\x00"
            data[0x40:0x40 + len(b"character/model/test.pac\x00")] = b"character/model/test.pac\x00"
            struct.pack_into("<II", data, 0x80, 3, 0xA0)
            struct.pack_into("<4f", data, 0xA0, 1.0, 2.0, 3.0, 1.0)

            preview = build_meshinfo_preview(
                bytes(data),
                source.path,
                source_entry=source,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )
            document = json.loads(
                build_binary_sidecar_analysis_json(
                    bytes(data),
                    source.path,
                    extension=".meshinfo",
                    source_entry=source,
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                )
            )

            self.assertIn("MeshInfo inspector", preview.preview_text)
            self.assertIn("Candidate count/offset tables", preview.preview_text)
            self.assertEqual(document["document"], "Crimson Desert Mod Workbench binary sidecar decode document.")
            self.assertFalse(document["editing"]["supported"])
            self.assertGreaterEqual(document["summary"]["asset_reference_hints"], 1)
            self.assertGreaterEqual(document["summary"]["count_offset_pair_candidates"], 1)

    def test_meshinfo_sidecar_json_recovers_length_prefixed_declarations(self) -> None:
        data = bytearray()
        data.extend(b"\xFF\xFF\x04\x00")
        data.extend(struct.pack("<I", len(b"StaticMesh3")) + b"StaticMesh3")
        data.extend(_decl("_mass", "float", bytes.fromhex("00 00 04 00 00 00 00 00")))
        data.extend(_decl("_isBreakable", "bool", bytes.fromhex("00 00 01 00 20 00 00 00")))
        data.extend(_decl("_socketList", "ReflectObjectPtr", bytes.fromhex("07 00 00 00 08 10 00 00")))
        data.extend(_decl("_boundingBoxMin", "float3", bytes.fromhex("00 00 0C 00 20 00 00 00")))

        preview = build_meshinfo_preview(bytes(data), "object/test.meshinfo")
        document = json.loads(build_binary_sidecar_analysis_json(bytes(data), "object/test.meshinfo", extension=".meshinfo"))
        declarations = document["schema_declarations"]["declared_member_rows"]
        rows_by_name = {row["name"]: row for row in declarations}

        self.assertEqual(document["summary"]["schema_declarations"], 4)
        self.assertEqual(rows_by_name["_mass"]["declared_type"], "float")
        self.assertEqual(rows_by_name["_mass"]["likely_kind"], "numeric")
        self.assertEqual(rows_by_name["_isBreakable"]["group"], "Breakable")
        self.assertEqual(rows_by_name["_socketList"]["reference_status"], "object_reference")
        self.assertEqual(rows_by_name["_socketList"]["array_status"], "array_or_table")
        self.assertFalse(document["editing"]["supported"])
        self.assertIn("Declared Fields:", preview.preview_text)
        self.assertIn("_mass: float", preview.preview_text)
        self.assertIn("Breakable declared fields", preview.preview_text)

    def test_motionblending_preview_and_json_stay_read_only(self) -> None:
        data = bytearray(192)
        data[0:4] = b"PAR "
        data[0x20:0x20 + len(b"ParameterizedMotionSpace\x00")] = b"ParameterizedMotionSpace\x00"
        data[0x58:0x58 + len(b"character/animation/test_idle.paa\x00")] = b"character/animation/test_idle.paa\x00"
        struct.pack_into("<4f", data, 0x90, 0.0, 0.5, 1.0, 1.0)

        preview = build_par_structured_preview(
            bytes(data),
            "character/animation/test.motionblending",
            extension=".motionblending",
        )
        document = json.loads(
            build_binary_sidecar_analysis_json(
                bytes(data),
                "character/animation/test.motionblending",
                extension=".motionblending",
            )
        )

        self.assertIn("Motion blending inspector", preview.preview_text)
        self.assertIn("Editing: read-only", preview.preview_text)
        self.assertEqual(document["source"]["kind"], "Motion Blending")
        self.assertFalse(document["editing"]["supported"])

    def test_motionblending_declarations_are_grouped_by_motion_schema_area(self) -> None:
        data = bytearray()
        data.extend(b"\xFF\xFF\x03\x00")
        data.extend(struct.pack("<III", 0x0E0000, 0x050000, 0x18))
        data.extend(struct.pack("<I", len(b"ParameterizedMotionSpace")) + b"ParameterizedMotionSpace")
        data.extend(_decl("_skeletonFileName", "staticstringA", bytes.fromhex("01 00 01 00 41 00 00 00")))
        data.extend(_decl("_animationFileNames", "staticstringA", bytes.fromhex("0A 00 01 00 20 10 00 00")))
        data.extend(_decl("_parameterMinMax", "float", bytes.fromhex("03 00 04 00 41 10 00 00")))
        data.extend(_decl("_delaunayTriangles", "ReflectObjectPtr", bytes.fromhex("07 00 00 00 28 10 00 00")))

        preview = build_par_structured_preview(
            bytes(data),
            "character/binary/motionblending/test.motionblending",
            extension=".motionblending",
        )
        document = json.loads(
            build_binary_sidecar_analysis_json(
                bytes(data),
                "character/binary/motionblending/test.motionblending",
                extension=".motionblending",
            )
        )

        self.assertEqual(document["summary"]["schema_declarations"], 4)
        self.assertIn("Skeleton declared fields", preview.preview_text)
        self.assertIn("Animation Files declared fields", preview.preview_text)
        self.assertIn("Parameters declared fields", preview.preview_text)
        self.assertIn("Delaunay declared fields", preview.preview_text)
        self.assertFalse(document["editing"]["supported"])

    def test_paa_preview_recovers_half_float_keyframes_and_stays_read_only(self) -> None:
        data = bytearray(192)
        data[0:4] = b"PAR "
        struct.pack_into("<I", data, 0x10, 0x88)
        struct.pack_into("<f", data, 0x14, 4.3)
        row_offset = 0x40
        for frame in range(1, 9):
            value = min(0.95, frame * 0.03)
            w = (max(0.0, 1.0 - value * value)) ** 0.5
            struct.pack_into("<H4e", data, row_offset + (frame - 1) * 10, frame, value, 0.0, 0.0, w)

        preview = build_par_structured_preview(
            bytes(data),
            "object/animation/animation/test_idle_00.paa",
            extension=".paa",
        )
        document = json.loads(
            build_binary_sidecar_analysis_json(
                bytes(data),
                "object/animation/animation/test_idle_00.paa",
                extension=".paa",
            )
        )

        self.assertIn("PAA animation inspector", preview.preview_text)
        self.assertIn("Candidate animation keyframe tables: 1", preview.preview_text)
        self.assertIn("u16 frame + 4 half-float values", preview.preview_text)
        self.assertIn("frame=1", preview.preview_text)
        self.assertIn("Editing: read-only", preview.preview_text)
        self.assertEqual(document["source"]["kind"], "PAA Animation Clip")
        self.assertEqual(document["summary"]["animation_keyframe_table_candidates"], 1)
        self.assertGreaterEqual(document["summary"]["animation_keyframe_rows"], 8)
        self.assertTrue(document["animation"]["keyframe_table_candidates"])
        self.assertFalse(document["editing"]["supported"])

    def test_paa_metabin_preview_recovers_animation_metadata_and_same_stem_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry(
                "actionchart/bin__/animmeta/1_pc/cd_phm_basic_00_00_abn_dam_upper_l_end_05_00.paa_metabin",
                root,
            )
            paa = _entry(
                "actionchart/bin__/animation/1_pc/cd_phm_basic_00_00_abn_dam_upper_l_end_05_00.paa",
                root,
            )
            path_index, basename_index = _indexes((source, paa))
            data = bytearray(128)
            data[0:16] = bytes.fromhex("FF FF 04 00 00 00 00 00 00 00 00 00 00 00 0F 00")
            data[0x10:0x18] = bytes.fromhex("00 00 01 00 11 00 00 00")
            data[0x18:0x18 + len(b"AnimationMetaData")] = b"AnimationMetaData"
            struct.pack_into(">I", data, 0x2C, 1)
            struct.pack_into(">I", data, 0x30, 81)
            struct.pack_into(">I", data, 0x38, 255)
            struct.pack_into(">I", data, 0x40, 0xFFFFFF4B)
            struct.pack_into(">I", data, 0x44, 6)
            data[0x50:0x68] = bytes.fromhex("00 05 05 00 00 00 00 00 00 00 0C 00 00 00 00 F0 EE EE 3E 80 00 3C 06")

            preview = build_par_structured_preview(
                bytes(data),
                source.path,
                extension=".paa_metabin",
                source_entry=source,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )
            document = json.loads(
                build_binary_sidecar_analysis_json(
                    bytes(data),
                    source.path,
                    extension=".paa_metabin",
                    source_entry=source,
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                )
            )
            resolved_paths = {reference.resolved_archive_path for reference in preview.related_references}

            self.assertIn("PAA animation metadata inspector", preview.preview_text)
            self.assertIn("Declared metadata type: AnimationMetaData", preview.preview_text)
            self.assertIn("Filename-derived animation hints", preview.preview_text)
            self.assertIn("damage / hit reaction", preview.preview_text)
            self.assertIn("Packed metadata stream", preview.preview_text)
            self.assertIn(paa.path, resolved_paths)
            self.assertEqual(document["source"]["kind"], "PAA Animation Metadata")
            self.assertEqual(document["animation_metadata"]["declared_type"], "AnimationMetaData")
            self.assertGreater(document["summary"]["animation_metadata_stream_bytes"], 0)
            self.assertFalse(document["editing"]["supported"])

    def test_paseq_preview_recovers_timeline_lanes_and_playback_gaps(self) -> None:
        for extension in (".paseq", ".paseqc"):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                source = _entry(f"actionchart/bin__/sequence/test_combo{extension}", root)
                paa = _entry("actionchart/bin__/animation/test_combo_attack.paa", root)
                hkx = _entry("character/bin__/animation/test_combo.hkx", root)
                effect = _entry("effect/bin__/test_combo_hit.paem", root)
                model = _entry("character/model/test_actor.pac", root)
                path_index, basename_index = _indexes((source, paa, hkx, effect, model))

                preview = build_par_structured_preview(
                    _paseq_sample(),
                    source.path,
                    extension=extension,
                    source_entry=source,
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                )
                document = json.loads(
                    build_binary_sidecar_analysis_json(
                        _paseq_sample(),
                        source.path,
                        extension=extension,
                        source_entry=source,
                        archive_entries_by_normalized_path=path_index,
                        archive_entries_by_basename=basename_index,
                    )
                )

                resolved_paths = {reference.resolved_archive_path for reference in preview.related_references}
                timeline = document["paseq"]["timeline"]
                playback = document["paseq"]["playback_readiness"]
                timing_evidence = timeline["timing_evidence"]

                self.assertIn("Animation schedule inspector", preview.preview_text)
                self.assertIn("Recovered timeline lanes", preview.preview_text)
                self.assertIn("Timeline field evidence", preview.preview_text)
                self.assertIn("FPS timing evidence", preview.preview_text)
                self.assertIn("source_paseq_fps_field_declared_value_offset_unmapped", preview.preview_text)
                self.assertIn("candidate float32_fps_candidate", preview.preview_text)
                self.assertIn("Blend window evidence", preview.preview_text)
                self.assertIn("candidate float32_blend_candidate", preview.preview_text)
                self.assertIn("blend_fields_declared_value_offsets_unmapped", preview.preview_text)
                self.assertIn("Playback readiness", preview.preview_text)
                self.assertIn(paa.path, resolved_paths)
                self.assertIn(hkx.path, resolved_paths)
                self.assertIn(effect.path, resolved_paths)
                self.assertEqual("Animation Schedule", document["source"]["kind"])
                self.assertGreaterEqual(timeline["lane_kind_counts"]["animation"], 2)
                self.assertGreaterEqual(timeline["lane_kind_counts"]["effect"], 1)
                self.assertGreaterEqual(timeline["lane_kind_counts"]["context"], 1)
                self.assertGreaterEqual(timeline["timeline_field_count"], 4)
                self.assertGreaterEqual(timeline["event_marker_count"], 2)
                self.assertFalse(playback["ready_for_3d_playback"])
                self.assertFalse(playback["game_accurate_timing"])
                self.assertEqual("unknown", playback["timing_confidence"])
                self.assertEqual("declared_timing_fields_unbound", playback["timing_status"])
                self.assertEqual(2, timing_evidence["fps_field_declaration_count"])
                self.assertTrue(all(row["confidence"] == "proven" for row in timing_evidence["fps_field_declarations"]))
                self.assertTrue(all(row["value_confidence"] == "unknown" for row in timing_evidence["fps_field_declarations"]))
                self.assertEqual("source_paseq_fps_field_declared_value_offset_unmapped", timing_evidence["fps_binding_status"])
                self.assertEqual("unknown", timing_evidence["fps_binding_confidence"])
                self.assertEqual("aligned_4_byte_little_endian", timing_evidence["fps_candidate_value_scan"])
                self.assertGreaterEqual(timing_evidence["fps_candidate_value_counts"]["float32"]["30"], 1)
                fps_candidate_rows = timing_evidence["fps_candidate_value_rows"]
                self.assertTrue(
                    any(
                        row["kind"] == "u32_fps_candidate"
                        and row["value"] == 30
                        and row["status"] == "not_bound_length_prefixed_string_context"
                        and row["value_confidence"] == "blocked"
                        for row in fps_candidate_rows
                    )
                )
                self.assertTrue(
                    any(
                        row["kind"] == "float32_fps_candidate"
                        and row["value"] == 30
                        and row["confidence"] == "after_recovered_declaration_region"
                        and row["status"] == "unbound_binary_scalar_candidate"
                        and row["value_confidence"] == "unknown"
                        for row in fps_candidate_rows
                    )
                )
                self.assertEqual(2, timing_evidence["blend_field_declaration_count"])
                self.assertEqual("blend_fields_declared_value_offsets_unmapped", timing_evidence["blend_binding_status"])
                self.assertEqual("unknown", timing_evidence["blend_binding_confidence"])
                self.assertEqual({"_endBlendingTime", "_startBlendingTime"}, {row["name"] for row in timing_evidence["blend_field_declarations"]})
                self.assertTrue(all(row["value_confidence"] == "unknown" for row in timing_evidence["blend_field_declarations"]))
                blend_candidate_rows = timing_evidence["blend_candidate_value_rows"]
                self.assertTrue(
                    any(
                        row["kind"] == "float32_blend_candidate"
                        and row["value"] == 1.25
                        and row["confidence"] == "after_recovered_declaration_region"
                        and row["status"] == "unbound_binary_scalar_candidate"
                        and row["value_confidence"] == "unknown"
                        for row in blend_candidate_rows
                    )
                )
                self.assertTrue(any("Runtime binding" in gap for gap in playback["blocking_gaps"]))
                self.assertFalse(document["editing"]["supported"])

    def test_encrypted_compressed_papr_validates_as_structured_par_payload(self) -> None:
        if lz4_block is None:
            self.skipTest("lz4 is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gap = struct.pack("<I", 0) + struct.pack("<f", 0.5) + struct.pack("<I", 24) + struct.pack("<I", 1)
            plain = (
                b"PAR "
                + bytes(range(1, 80))
                + _decl("_constraintBoneName", "staticstringA", bytes.fromhex("01 00 01 00 20 00 00 00"))
                + b"Bip01 Head\x00" + gap + b"P_Bip01 Head\x00" + gap + b"Bip01 Head_Dummy\x00"
            )
            plain += (b"\x00" * (((len(plain) + 3) & ~3) - len(plain))) + struct.pack("<f", 3.0) + struct.pack("<f", 30.5) + gap
            plain += b"Local_Euler_Z*3+30.5\x00" + gap + b"amin(Local_Euler_Z*5+9.8) -1\x00"
            compressed = lz4_block.compress(plain, store_size=False)
            encrypted = crypt_chacha20_filename(compressed, "body.papr")
            entry = _entry("character/model/body.papr", root)
            entry.comp_size = len(compressed)
            entry.orig_size = len(plain)
            entry.flags = 0x32

            decrypted, note = try_decrypt_archive_entry_data(entry, encrypted)
            preview = build_par_structured_preview(plain, entry.path, extension=".papr")
            document = json.loads(build_binary_sidecar_analysis_json(plain, entry.path, extension=".papr"))

            self.assertEqual("ChaCha20", note)
            self.assertEqual(plain, lz4_block.decompress(decrypted, uncompressed_size=len(plain)))
            self.assertIn("Animation constraint inspector", preview.preview_text)
            self.assertIn("Constraint string evidence", preview.preview_text)
            self.assertIn("Constraint expression evidence", preview.preview_text)
            self.assertIn("Constraint field offset evidence", preview.preview_text)
            self.assertIn("Constraint record candidates", preview.preview_text)
            self.assertIn("linear_channel_transform_candidate", preview.preview_text)
            self.assertIn("channel_coefficient", preview.preview_text)
            self.assertIn("gaps=binary_like_interfield_gap_bytes_unbound", preview.preview_text)
            self.assertIn("scalars=unbound_interfield_scalar_candidates", preview.preview_text)
            self.assertIn("numeric_matches=unbound_scalar_numeric_constant_matches", preview.preview_text)
            self.assertIn("order=parent>helper>target>expression", preview.preview_text)
            self.assertIn("Constraint solving and editing remain disabled", " ".join(preview.detail_lines))
            self.assertEqual("Animation Constraint", preview.metadata_label)
            self.assertEqual("Animation Constraint", document["source"]["kind"])
            self.assertTrue(document["papr"]["recognized"])
            self.assertFalse(document["papr"]["constraint_solving_supported"])
            self.assertEqual("read_only_constraint_string_evidence", document["papr"]["status"])
            self.assertGreaterEqual(document["papr"]["string_evidence_count"], 5)
            self.assertGreaterEqual(document["papr"]["role_counts"]["bone_reference"], 1)
            self.assertGreaterEqual(document["papr"]["role_counts"]["parent_bone_reference"], 1)
            self.assertGreaterEqual(document["papr"]["role_counts"]["helper_bone_reference"], 1)
            self.assertGreaterEqual(document["papr"]["role_counts"]["driver_expression"], 1)
            self.assertGreaterEqual(document["papr"]["role_counts"]["limit_expression"], 1)
            self.assertGreaterEqual(document["papr"]["record_candidate_count"], 2)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["channel_counts"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["limit_operator_counts"]["amin"], 1)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["shape_counts"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["shape_counts"]["limit_linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(sum(document["papr"]["expression_evidence"]["syntax_signature_counts"].values()), 1)
            self.assertTrue(
                any(
                    "shape=linear_channel_transform_candidate" in signature
                    for signature in document["papr"]["expression_evidence"]["syntax_signature_counts"]
                )
            )
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["numeric_role_counts"]["channel_coefficient"], 2)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["numeric_role_counts"]["additive_offset"], 2)
            self.assertGreaterEqual(document["papr"]["expression_evidence"]["numeric_role_counts"]["limit_argument"], 1)
            self.assertEqual("unknown", document["papr"]["expression_evidence"]["semantics_confidence"])
            self.assertGreaterEqual(document["papr"]["offset_evidence"]["target_offset_count"], 1)
            self.assertEqual("proven", document["papr"]["offset_evidence"]["offset_confidence"])
            self.assertIn("Local_Euler_Z", document["papr"]["record_candidates"][0]["expression_channels"])
            self.assertGreater(document["papr"]["record_candidates"][0]["target_bone_offset"], 0)
            self.assertGreater(document["papr"]["record_candidates"][0]["target_bone_delta"], 0)
            self.assertEqual("proven_decoded_string_offsets", document["papr"]["record_candidates"][0]["field_offset_confidence"])
            self.assertEqual("linear_channel_transform_candidate", document["papr"]["record_candidates"][0]["expression_shape"])
            self.assertIn(
                "shape=linear_channel_transform_candidate",
                document["papr"]["record_candidates"][0]["expression_syntax_signature"],
            )
            self.assertEqual(
                ["channel_coefficient", "additive_offset"],
                document["papr"]["record_candidates"][0]["expression_numeric_roles"],
            )
            self.assertEqual(
                "inferred_readable_expression_syntax",
                document["papr"]["record_candidates"][0]["expression_shape_confidence"],
            )
            self.assertEqual(
                ["parent", "helper", "target", "expression"],
                document["papr"]["record_candidates"][0]["record_field_sequence"],
            )
            self.assertEqual(
                "proven_decoded_string_offset_order",
                document["papr"]["record_layout_evidence"]["field_sequence_confidence"],
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_status_counts"]["binary_like_interfield_gap_bytes_unbound"],
                1,
            )
            self.assertGreaterEqual(sum(document["papr"]["record_layout_evidence"]["gap_class_counts"].values()), 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_pair_count"], 1)
            self.assertGreater(document["papr"]["record_layout_evidence"]["max_gap_size"], 0)
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_scalar_status_counts"]["unbound_interfield_scalar_candidates"],
                1,
            )
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_aligned_word_count"], 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_scalar_candidate_count"], 1)
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_numeric_match_status_counts"]["unbound_scalar_numeric_constant_matches"],
                1,
            )
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(
                sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_value_confidence_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_numeric_match_value_confidence_counts"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_family_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_family_row_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_numeric_match_family_role_counts"][
                    "driver_expression_candidate"
                ]["channel_coefficient"],
                1,
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_numeric_match_family_pair_counts"][
                    "driver_expression_candidate"
                ]["target>expression"],
                1,
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["gap_numeric_match_family_value_confidence_counts"][
                    "driver_expression_candidate"
                ]["exact_float32_numeric_value_match_layout_unproven"],
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_signature_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_candidate_relative_signature_counts"].values()),
                1,
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "role=channel_coefficient" in signature
                    for signature in document["papr"]["record_layout_evidence"]["gap_numeric_match_signature_counts"]
                )
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "rel=" in signature
                    for signature in document["papr"]["record_layout_evidence"][
                        "gap_numeric_match_candidate_relative_signature_counts"
                    ]
                )
            )
            self.assertGreaterEqual(sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_previous_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_next_delta_counts"].values()), 1)
            self.assertGreaterEqual(
                sum(document["papr"]["record_layout_evidence"]["gap_numeric_match_candidate_relative_offset_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["max_gap_numeric_match_previous_delta"],
                document["papr"]["record_layout_evidence"]["min_gap_numeric_match_previous_delta"],
            )
            self.assertGreaterEqual(
                document["papr"]["record_layout_evidence"]["max_gap_numeric_match_candidate_relative_offset"],
                document["papr"]["record_layout_evidence"]["min_gap_numeric_match_candidate_relative_offset"],
            )
            self.assertEqual(
                "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                document["papr"]["record_layout_evidence"]["gap_numeric_match_offset_confidence"],
            )
            self.assertEqual(
                "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                document["papr"]["record_layout_evidence"]["gap_numeric_match_candidate_relative_offset_confidence"],
            )
            self.assertGreaterEqual(document["papr"]["record_layout_evidence"]["gap_numeric_match_count"], 1)
            layout_match_rows = document["papr"]["record_layout_evidence"]["gap_numeric_match_rows"]
            self.assertGreaterEqual(len(layout_match_rows), 1)
            self.assertEqual(document["papr"]["record_candidates"][0]["offset"], layout_match_rows[0]["candidate_offset"])
            self.assertEqual(
                layout_match_rows[0]["match_offset"] - layout_match_rows[0]["candidate_offset"],
                layout_match_rows[0]["candidate_relative_offset"],
            )
            self.assertEqual("driver_expression_candidate", layout_match_rows[0]["constraint_type"])
            self.assertEqual("target>expression", layout_match_rows[0]["between_fields"])
            self.assertIn(layout_match_rows[0]["numeric_role"], {"channel_coefficient", "additive_offset"})
            self.assertIn("previous_field_end_delta", layout_match_rows[0])
            self.assertIn("next_field_start_delta", layout_match_rows[0])
            self.assertIn("candidate_relative_match_signature", layout_match_rows[0])
            self.assertIn(
                layout_match_rows[0]["value_confidence"],
                {
                    "exact_u32_numeric_value_match_layout_unproven",
                    "exact_float32_numeric_value_match_layout_unproven",
                    "approx_float32_numeric_value_match_layout_unproven",
                },
            )
            self.assertEqual(
                "binary_like_interfield_gap_bytes_unbound",
                document["papr"]["record_candidates"][0]["record_gap_status"],
            )
            self.assertEqual(
                "unbound_interfield_scalar_candidates",
                document["papr"]["record_candidates"][0]["record_gap_scalar_status"],
            )
            self.assertEqual(
                "unbound_scalar_numeric_constant_matches",
                document["papr"]["record_candidates"][0]["record_gap_numeric_match_status"],
            )
            self.assertGreaterEqual(document["papr"]["record_candidates"][0]["record_gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(document["papr"]["record_candidates"][0]["record_gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(document["papr"]["record_candidates"][0]["record_gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(
                document["papr"]["record_candidates"][0]["record_gap_numeric_match_value_confidence_counts"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_candidates"][0]["record_gap_numeric_match_signature_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_candidates"][0]["record_gap_numeric_match_candidate_relative_signature_counts"].values()),
                1,
            )
            self.assertGreaterEqual(document["papr"]["record_candidates"][0]["record_gap_numeric_match_count"], 1)
            self.assertGreaterEqual(
                sum(document["papr"]["record_candidates"][0]["record_gap_numeric_match_previous_delta_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_candidates"][0]["record_gap_numeric_match_next_delta_counts"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(document["papr"]["record_candidates"][0]["record_gap_numeric_match_candidate_relative_offset_counts"].values()),
                1,
            )
            self.assertIn("previous_field_end_delta", document["papr"]["record_candidates"][0]["record_gap_numeric_match_rows"][0])
            self.assertIn("next_field_start_delta", document["papr"]["record_candidates"][0]["record_gap_numeric_match_rows"][0])
            self.assertIn("candidate_relative_offset", document["papr"]["record_candidates"][0]["record_gap_numeric_match_rows"][0])
            self.assertIn("match_signature", document["papr"]["record_candidates"][0]["record_gap_numeric_match_rows"][0])
            self.assertIn(
                "candidate_relative_match_signature",
                document["papr"]["record_candidates"][0]["record_gap_numeric_match_rows"][0],
            )
            self.assertEqual("proven", document["papr"]["record_candidates"][0]["expression_channel_confidence"])
            self.assertEqual("unknown", document["papr"]["record_candidates"][0]["expression_semantics_confidence"])
            self.assertTrue(all(row["solver_status"] == "blocked_record_layout_unproven" for row in document["papr"]["record_candidates"]))
            self.assertFalse(document["editing"]["supported"])

    def test_binary_sidecar_corpus_report_summarizes_paseq_timeline_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paseq = root / "test_combo.paseq"
            paseqc = root / "test_combo.paseqc"
            paseq.write_bytes(_paseq_sample())
            paseqc.write_bytes(_paseq_sample())

            report = build_binary_sidecar_corpus_report((root,), discovery_limit=10, detail_scan_limit=10)
            paseq_report = report["by_extension"][".paseq"]
            paseqc_report = report["by_extension"][".paseqc"]

            self.assertEqual(report["summary"]["paseq_files_scanned"], 1)
            self.assertEqual(report["summary"]["paseqc_files_scanned"], 1)
            self.assertEqual(paseq_report["files_scanned"], 1)
            self.assertEqual(paseqc_report["files_scanned"], 1)
            self.assertGreaterEqual(paseq_report["paseq"]["timeline_lane_buckets"][0]["lane_count"], 4)
            self.assertGreaterEqual(paseq_report["paseq"]["animation_lane_buckets"][0]["lane_count"], 2)
            self.assertGreaterEqual(paseqc_report["paseq"]["animation_lane_buckets"][0]["lane_count"], 2)
            self.assertFalse(report["editing"]["supported"])

    def test_binary_sidecar_corpus_report_ranks_layouts_and_stable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mesh_a = root / "a.meshinfo"
            mesh_b = root / "b.meshinfo"
            motion = root / "blend.motionblending"
            prefab = root / "test.prefab"
            mesh_payload = (
                b"\xFF\xFF\x04\x00"
                + _decl("_mass", "float", bytes.fromhex("00 00 04 00 00 00 00 00"))
                + _decl("_isBreakable", "bool", bytes.fromhex("00 00 01 00 20 00 00 00"))
                + _decl("_unknownPacked", "int", bytes.fromhex("3F 00 04 00 00 00 00 00"))
            )
            mesh_a.write_bytes(mesh_payload)
            mesh_b.write_bytes(mesh_payload)
            motion.write_bytes(
                b"\xFF\xFF\x03\x00"
                + _decl("_animationFileNames", "staticstringA", bytes.fromhex("0A 00 01 00 20 10 00 00"))
                + _decl("_parameterScale", "float", bytes.fromhex("00 00 04 00 41 00 00 00"))
            )
            prefab.write_bytes(
                b"SceneObject\x00"
                + _decl("_resourcePath", "normalizedPathA", bytes.fromhex("0A 00 01 00 20 10 00 00"))
                + b"character/model/test.pac\x00"
            )

            report = build_binary_sidecar_corpus_report((root,), discovery_limit=10, detail_scan_limit=10)
            mesh_report = report["by_extension"][".meshinfo"]
            motion_report = report["by_extension"][".motionblending"]
            stable_names = {row["name"] for row in mesh_report["stable_fields"]}

            self.assertEqual(report["format"], "cdmw_binary_sidecar_corpus_v1")
            self.assertEqual(report["summary"]["files_scanned"], 4)
            self.assertEqual(mesh_report["files_scanned"], 2)
            self.assertEqual(motion_report["files_scanned"], 1)
            self.assertEqual(report["summary"]["prefab_files_scanned"], 1)
            self.assertEqual(report["by_extension"][".prefab"]["files_scanned"], 1)
            self.assertIn("_mass", stable_names)
            self.assertTrue(mesh_report["layout_signatures"])
            self.assertTrue(mesh_report["unknown_descriptor_bytes"])
            self.assertFalse(report["editing"]["supported"])

    def test_binary_sidecar_corpus_report_summarizes_paa_metabin_animation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = root / "cd_phm_basic_00_00_nor_move_run_f_ing_00.paa_metabin"
            data = bytearray(112)
            data[0:16] = bytes.fromhex("FF FF 04 00 00 00 00 00 00 00 00 00 00 00 0F 00")
            data[0x10:0x18] = bytes.fromhex("00 00 01 00 11 00 00 00")
            data[0x18:0x18 + len(b"AnimationMetaData")] = b"AnimationMetaData"
            data[0x50:0x60] = bytes.fromhex("00 05 05 00 00 00 00 00 00 00 0C 00 80 00 3C 06")
            metadata.write_bytes(bytes(data))

            report = build_binary_sidecar_corpus_report((root,), discovery_limit=10, detail_scan_limit=10)
            paa_report = report["by_extension"][".paa_metabin"]
            declared_types = paa_report["animation_metadata"]["declared_types"]
            filename_hints = paa_report["animation_metadata"]["filename_hints"]

            self.assertEqual(report["summary"]["paa_metabin_files_scanned"], 1)
            self.assertEqual(declared_types[0]["declared_type"], "AnimationMetaData")
            self.assertTrue(any("movement" in row["hint"] for row in filename_hints))
            self.assertFalse(report["editing"]["supported"])

    def test_prefab_preview_resolves_model_and_motion_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("character/prefab/test.prefab", root)
            model = _entry("character/model/test_model.pac", root)
            motion = _entry("character/bin__/meshphysics/test_model.hkx", root)
            path_index, basename_index = _indexes((source, model, motion))
            data = (
                b"SceneObject\x00PrefabResource\x00"
                b"character/model/test_model.pac\x00"
                b"character/bin__/meshphysics/test_model.hkx\x00"
            )

            preview = build_structured_asset_preview(
                data,
                source.path,
                extension=".prefab",
                source_entry=source,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )

            self.assertIn("Prefab inspector", preview.preview_text)
            self.assertIn("Reference types: .pac: 1, .hkx: 1", preview.preview_text)
            self.assertIn("metadata, not the renderable mesh", "\n".join(preview.detail_lines))
            self.assertIn("bounded binary prefab relationship evidence", "\n".join(preview.detail_lines))
            resolved_paths = {reference.resolved_archive_path for reference in preview.related_references}
            self.assertIn(model.path, resolved_paths)
            self.assertIn(motion.path, resolved_paths)

    def test_prefab_preview_decodes_member_declarations_and_component_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("character/prefab/test.prefab", root)
            model = _entry("character/model/test_model.pac", root)
            socket = _entry("character/descriptors/socketbonedata/test.sockets.xml", root)
            path_index, basename_index = _indexes((source, model, socket))
            data = (
                b"\xFF\xFF\x04\x00\x00\x00"
                + struct.pack("<I", len(b"SceneObject"))
                + b"SceneObject"
                + _decl("_components", "ReflectObjectPtr", struct.pack("<4H", 7, 0, 4104, 3))
                + _decl("_childSceneObjects", "ReflectObjectPtr", struct.pack("<4H", 7, 0, 4136, 1))
                + _decl("_worldTransform", "Transform", struct.pack("<4H", 0, 40, 0, 0))
                + _decl("_objectFilename", "ReflectObject", struct.pack("<4H", 4, 8, 104, 0))
                + _decl("_socketFileName", "staticstringA", struct.pack("<4H", 1, 1, 64, 0))
                + b"character/model/test_model.pac\x00"
                + b"character/descriptors/socketbonedata/test.sockets.xml\x00"
            )

            preview = build_structured_asset_preview(
                data,
                source.path,
                extension=".prefab",
                source_entry=source,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )
            document = json.loads(
                build_binary_sidecar_analysis_json(
                    data,
                    source.path,
                    extension=".prefab",
                    source_entry=source,
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                )
            )
            prefab_labels = {
                row["label"]
                for row in document["prefab"]["evidence_rows"]
                if isinstance(row, dict)
            }
            rows_by_name = {
                row["name"]: row
                for row in document["schema_declarations"]["declared_member_rows"]
            }

            self.assertIn("Declared member rows: 5", preview.preview_text)
            self.assertIn("Prefab evidence:", preview.preview_text)
            self.assertIn("Scene hierarchy", preview.preview_text)
            self.assertIn("Static mesh/resource component", preview.preview_text)
            self.assertIn("Socket attachments", preview.preview_text)
            self.assertIn("Scene / Object declared fields", preview.preview_text)
            self.assertIn("_components: ReflectObjectPtr", preview.preview_text)
            self.assertIn("Transform / Bounds declared fields", preview.preview_text)
            self.assertIn("Resources declared fields", preview.preview_text)
            self.assertIn("length-prefixed member declaration", "\n".join(preview.detail_lines))
            self.assertFalse(document["editing"]["supported"])
            self.assertIn("Scene hierarchy", prefab_labels)
            self.assertIn("Static mesh/resource component", prefab_labels)
            self.assertEqual(rows_by_name["_objectFilename"]["group"], "Resources")
            self.assertEqual(rows_by_name["_socketFileName"]["group"], "Skeleton / Sockets")

    def test_part_prefab_and_model_property_headers_are_readable_relationship_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = _entry("character/model/body_a.pac", root)
            material = _entry("character/modelproperty/body_a.pac_xml", root)
            pappt = _entry("character/model/body_a.pappt", root)
            pamhc = _entry("character/model/body_a.pamhc", root)
            path_index, basename_index = _indexes((model, material, pappt, pamhc))

            pappt_preview = build_structured_asset_preview(
                b"SceneObject\x00PrefabResource\x00character/model/body_a.pac\x00",
                pappt.path,
                extension=".pappt",
                source_entry=pappt,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )
            pamhc_preview = build_structured_asset_preview(
                b"MaterialParameterTexture\x00ModelPropertyHeader\x00character/modelproperty/body_a.pac_xml\x00",
                pamhc.path,
                extension=".pamhc",
                source_entry=pamhc,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )

            self.assertIn("Part prefab table inspector", pappt_preview.preview_text)
            self.assertIn("linked model files still hold geometry", "\n".join(pappt_preview.detail_lines))
            self.assertIn(model.path, {reference.resolved_archive_path for reference in pappt_preview.related_references})
            self.assertIn("Model property header inspector", pamhc_preview.preview_text)
            self.assertIn("read-only relationship evidence", "\n".join(pamhc_preview.detail_lines))
            self.assertIn(material.path, {reference.resolved_archive_path for reference in pamhc_preview.related_references})

    def test_seqmt_preview_decodes_dds_sequence_texture_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("object/sequence/test_actor_8x8.seqmt", root)
            model = _entry("object/model/test_actor_8x8.pac", root)
            texture = _entry("object/texture/test_actor_8x8.dds", root)
            path_index, basename_index = _indexes((source, model, texture))
            data = _seqmt_sample(8, 8, flags=1, extra_payload=struct.pack("<Iff", 5, 0.25, 1.0))

            preview = build_structured_asset_preview(
                data,
                source.path,
                extension=".seqmt",
                source_entry=source,
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
            )
            document = json.loads(
                build_binary_sidecar_analysis_json(
                    data,
                    source.path,
                    extension=".seqmt",
                    source_entry=source,
                    archive_entries_by_normalized_path=path_index,
                    archive_entries_by_basename=basename_index,
                )
            )
            resolved_paths = {reference.resolved_archive_path for reference in preview.related_references}

            self.assertIn("SEQMT sequence texture inspector", preview.preview_text)
            self.assertIn("SEQMT atlas/frame table:", preview.preview_text)
            self.assertIn("Atlas grid: 8 x 8", preview.preview_text)
            self.assertIn("Frame count: 64", preview.preview_text)
            self.assertIn("Flag/packing byte: 0x01", preview.preview_text)
            self.assertIn("Extra trailing payload: 12 byte(s)", preview.preview_text)
            self.assertIn("Filename grid hint: 8 x 8 (matches header)", preview.preview_text)
            self.assertIn("Frame records (first", preview.preview_text)
            self.assertIn("DDS! atlas grid", "\n".join(preview.detail_lines))
            self.assertIn(model.path, resolved_paths)
            self.assertIn(texture.path, resolved_paths)
            self.assertEqual(document["source"]["kind"], "SEQMT Sequence Texture Metadata")
            self.assertTrue(document["seqmt"]["recognized"])
            self.assertEqual(document["seqmt"]["columns"], 8)
            self.assertEqual(document["seqmt"]["rows"], 8)
            self.assertEqual(document["seqmt"]["frame_count"], 64)
            self.assertEqual(document["seqmt"]["trailing_payload_bytes"], 12)
            self.assertTrue(document["seqmt"]["filename_grid_hint"]["matches_header"])
            self.assertFalse(document["editing"]["supported"])

    def test_binary_sidecar_corpus_report_includes_seqmt_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seqmt = root / "test_actor_4x4.seqmt"
            seqmt.write_bytes(_seqmt_sample(4, 4))

            report = build_binary_sidecar_corpus_report((root,), discovery_limit=10, detail_scan_limit=10)
            seqmt_report = report["by_extension"][".seqmt"]

            self.assertEqual(report["summary"]["seqmt_files_scanned"], 1)
            self.assertEqual(seqmt_report["files_scanned"], 1)
            self.assertEqual(seqmt_report["seqmt"]["atlas_grids"][0]["grid"], "4x4:16")
            self.assertEqual(seqmt_report["seqmt"]["payload_statuses"][0]["status"], "complete")
            self.assertFalse(report["editing"]["supported"])

    def test_paccd_preview_decodes_customization_slot_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("character/binary/customization/test_customization.paccd", root)
            data = _paccd_sample()

            preview = build_structured_asset_preview(data, source.path, extension=".paccd", source_entry=source)
            document = json.loads(
                build_binary_sidecar_analysis_json(data, source.path, extension=".paccd", source_entry=source)
            )

            self.assertIn("Character customization inspector", preview.preview_text)
            self.assertIn("PACCD customization table", preview.preview_text)
            self.assertIn("Slots: 14", preview.preview_text)
            self.assertIn("row stride 19", preview.preview_text)
            self.assertEqual(document["source"]["kind"], "Character Customization Data")
            self.assertTrue(document["paccd"]["recognized"])
            self.assertEqual(document["paccd"]["slot_count"], 14)
            self.assertEqual(document["paccd"]["row_stride"], 19)
            self.assertFalse(document["editing"]["supported"])

    def test_binary_sidecar_corpus_report_includes_paccd_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paccd = root / "test_customization.paccd"
            paccd.write_bytes(_paccd_sample())

            report = build_binary_sidecar_corpus_report((root,), discovery_limit=10, detail_scan_limit=10)
            paccd_report = report["by_extension"][".paccd"]

            self.assertEqual(report["summary"]["paccd_files_scanned"], 1)
            self.assertEqual(paccd_report["files_scanned"], 1)
            self.assertEqual(paccd_report["paccd"]["layout_families"][0]["format_family"], "compact_customization_rows")
            self.assertEqual(paccd_report["paccd"]["slot_counts"][0]["slot_count"], 14)
            self.assertFalse(report["editing"]["supported"])

    def test_world_navigation_preview_groups_nav_and_road_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _entry("world/nav/test.nav", root)
            data = b"NavigationGraph\x00RoadSector\x00WaypointList\x00character/prefab/road_marker.prefab\x00"

            preview = build_structured_asset_preview(data, source.path, extension=".nav", source_entry=source)

            self.assertIn("World navigation inspector", preview.preview_text)
            self.assertIn("Road / Path", preview.preview_text)
            self.assertIn("Navigation", preview.preview_text)
            self.assertIn("character/prefab/road_marker.prefab", preview.preview_text)

    def test_iteminfo_pabgb_preview_uses_item_database_language_not_rig_variant(self) -> None:
        data = (
            b"\x98\x08\x00\x00\x0f\x00\x00\x00"
            b"Pyeonjeon_Arrow\x00"
            b"\x64\x00\x00\x00"
            b"9448928051312\x00"
            b"Arrow\x00Quiver\x00Poison_Arrow\x00"
        )

        preview = build_structured_asset_preview(
            data,
            "gamedata/binary__/client/bin/iteminfo.pabgb",
            extension=".pabgb",
        )

        self.assertIn("Item info table inspector", preview.preview_text)
        self.assertIn("Item identifier candidates", preview.preview_text)
        self.assertIn("Pyeonjeon_Arrow", preview.preview_text)
        self.assertIn("Item Database", preview.metadata_label)
        self.assertNotIn("Rig variant inspector", preview.preview_text)

    def test_structured_sidecars_use_metadata_or_animation_archive_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual("metadata", archive_entry_role(_entry("object/test.meshinfo", root)))
            self.assertEqual("metadata", archive_entry_role(_entry("object/test.prefab", root)))
            self.assertEqual("metadata", archive_entry_role(_entry("object/test.pappt", root)))
            self.assertEqual("metadata", archive_entry_role(_entry("object/test.pamhc", root)))
            self.assertEqual("metadata", archive_entry_role(_entry("character/binary/customization/test.paccd", root)))
            self.assertEqual("metadata", archive_entry_role(_entry("gamedata/binary__/client/bin/iteminfo.pabgb", root)))
            self.assertEqual("animation", archive_entry_role(_entry("actionchart/bin__/animmeta/test.paa_metabin", root)))
            self.assertEqual("animation", archive_entry_role(_entry("actionchart/bin__/schedule/test.paschedule", root)))
            self.assertEqual("animation", archive_entry_role(_entry("sequencer/binary__/stage/test.paseqc", root)))
            self.assertEqual("physics", archive_entry_role(_entry("character/bin__/meshphysics/body.hkx", root)))
            self.assertEqual("animation", archive_entry_role(_entry("character/bin__/animation/body.hkx", root)))

    def test_simplified_xml_summary_explains_material_sidecar_values(self) -> None:
        xml_text = """
        <ModelPropertyList>
          <SkinnedMeshMaterialWrapper _subMeshName="cd_test_body">
            <Material _materialName="SkinnedMeshStandard_Ver2">
              <MaterialParameterTexture _name="_normalTexture">
                <ResourceReferencePath_ITexture _path="character/texture/cd_test_body_n.dds" />
              </MaterialParameterTexture>
              <MaterialParameterColor _name="_tintColorR" _value="#aabbccff" />
            </Material>
          </SkinnedMeshMaterialWrapper>
        </ModelPropertyList>
        """

        summary = build_simplified_text_asset_summary(
            xml_text,
            extension=".pac_xml",
            virtual_path="character/modelproperty/test.pac_xml",
        )

        self.assertIn("Simplified values", summary)
        self.assertIn("Material texture bindings: 1", summary)
        self.assertIn("Submesh/material slots: cd_test_body", summary)
        self.assertIn("character/texture/cd_test_body_n.dds", summary)
        self.assertIn("guided value editor", summary)

    def test_simplified_xml_summary_explains_physics_attachment_values(self) -> None:
        xml_text = """
        <SkinnedMeshPhysicsAttachmentInstanceDescSet>
          <Vector Name="_instanceDescs">
            <SkinnedMeshPhysicsAttachmentInstanceDesc ItemID="0">
              <SkinnedMeshPhysicsAttachmentBodyCreationDesc Name="_childBodyDesc" _bodyName="PhysicsAttachment_Lantern" _socketName="RHand_Lantern_Socket" _inertiaFactor="20.0" _angularDamping="0.9" _linearDamping="0.8">
                <SkinnedMeshPhysicsAttachmentCapsuleShapeDesc Name="_shapeDesc" _sphereRadius="0.05" _cylinderHeight="0.11"/>
              </SkinnedMeshPhysicsAttachmentBodyCreationDesc>
              <Vector Name="_constraintDescs">
                <SkinnedMeshPhysicsAttachment6DofConstraintDesc ItemID="0" _angularLimitMin="-2.1 -0.6 0.0" _angularLimitMax="-1.1 0.6 0.0" _maxFrictionTorque="2.0"/>
              </Vector>
            </SkinnedMeshPhysicsAttachmentInstanceDesc>
          </Vector>
        </SkinnedMeshPhysicsAttachmentInstanceDescSet>
        """

        summary = build_simplified_text_asset_summary(
            xml_text,
            extension=".xml",
            virtual_path="character/descriptors/physicsattachment/1_pc/2_phw/phw_01.xml",
        )

        self.assertIn("Physics attachment summary", summary)
        self.assertIn("Physics attachment instances: 1; bodies: 1; constraints: 1", summary)
        self.assertIn("RHand_Lantern_Socket", summary)
        self.assertIn("Angular Damping: 0.9 (physics damping value)", summary)
        self.assertIn("Max Friction Torque: 2.0 (physics friction value)", summary)


if __name__ == "__main__":
    unittest.main()
