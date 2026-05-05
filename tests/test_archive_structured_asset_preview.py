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
            self.assertEqual("metadata", archive_entry_role(_entry("gamedata/binary__/client/bin/iteminfo.pabgb", root)))
            self.assertEqual("animation", archive_entry_role(_entry("actionchart/bin__/animmeta/test.paa_metabin", root)))
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
