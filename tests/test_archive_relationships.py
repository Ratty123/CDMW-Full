import tempfile
import unittest
from pathlib import Path

from cdmw.core.archive_relationships import (
    ARCHIVE_REL_INCLUDE_MANUAL,
    ARCHIVE_REL_INCLUDE_REQUIRED,
    SWAP_SCOPE_BODY_HEAD,
    build_archive_relationship_plan,
    build_character_swap_plan,
    resolve_material_texture_graph,
)
from cdmw.core.archive import (
    _prefab_evidence_rows,
    _prefab_material_override_evidence_rows,
    build_prefab_socket_name_patch,
    build_archive_entry_basename_index,
    build_archive_entry_path_index,
    build_archive_asset_family_graph,
    build_archive_item_icon_references_from_catalog,
    build_archive_preview_result,
    build_archive_relationship_references,
    build_part_in_out_socket_attach_point_patch,
    build_part_in_out_socket_profile_patch,
    build_socket_bone_data_profile_patch,
    inspect_prefab_socket_name_fields,
    infer_part_in_out_weapon_class,
    parse_part_in_out_socket_info_xml,
    parse_socket_bone_data_xml,
    part_in_out_rows_for_weapon_class,
)
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference


class ArchiveRelationshipTests(unittest.TestCase):
    def _prefab_decl(self, name: str, declared_type: str, descriptor: bytes) -> bytes:
        return (
            len(name).to_bytes(4, "little")
            + name.encode("ascii")
            + len(declared_type).to_bytes(4, "little")
            + declared_type.encode("ascii")
            + descriptor
        )

    def _prefab_string(self, value: str) -> bytes:
        encoded = value.encode("ascii")
        return len(encoded).to_bytes(4, "little") + encoded

    def _minimal_prefab_socket_payload(self) -> bytes:
        string_descriptor = b"\x01\x00\x01\x00\x10\x00\x00\x00"
        bool_descriptor = b"\x00\x00\x01\x00\x00\x00\x00\x00"
        declarations = b"".join(
            (
                self._prefab_decl("_attachedSocketName", "IndexedStringA", string_descriptor),
                self._prefab_decl("_pivotSocketName", "IndexedStringA", string_descriptor),
                self._prefab_decl("_applyPosition", "bool", bool_descriptor),
            )
        )
        return (
            b"\xff\xff\x04\x00"
            + declarations
            + b"\x00" * 32
            + self._prefab_string("Spine2_B_Socket")
            + self._prefab_string("Spine2_B_ChildSocket")
            + self._prefab_string("character/model/1_pc/1_phm/weapon/2_twohandweapon/test.pac")
        )

    def _entries(self, payloads):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        paz_path = root / "0.paz"
        pamt_path = root / "0.pamt"
        offset = 0
        entries = []
        with paz_path.open("wb") as handle:
            for index, (path, payload) in enumerate(payloads):
                data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
                handle.write(data)
                entries.append(
                    ArchiveEntry(
                        path=path,
                        pamt_path=pamt_path,
                        paz_file=paz_path,
                        offset=offset,
                        comp_size=len(data),
                        orig_size=len(data),
                        flags=0,
                        paz_index=0,
                    )
                )
                offset += len(data)
        return tuple(entries)

    def test_prefab_socket_name_patch_is_proven_for_same_length_rewrite(self):
        payload = self._minimal_prefab_socket_payload()

        fields = inspect_prefab_socket_name_fields(payload)
        self.assertEqual([field.value for field in fields], ["Spine2_B_Socket", "Spine2_B_ChildSocket"])

        result = build_prefab_socket_name_patch(
            payload,
            attached_socket_name="Pelvis_L_Socket",
            pivot_socket_name="Pelvis_L_ChildSocket",
        )

        self.assertEqual(len(result.data), len(payload))
        self.assertIn(b"Pelvis_L_Socket", result.data)
        self.assertIn(b"Pelvis_L_ChildSocket", result.data)
        self.assertNotIn(b"Spine2_B_Socket", result.data)
        self.assertIn("same-length only", "\n".join(result.proof_lines))

    def test_prefab_socket_name_patch_rejects_length_changing_rewrite(self):
        payload = self._minimal_prefab_socket_payload()

        with self.assertRaises(ValueError):
            build_prefab_socket_name_patch(
                payload,
                attached_socket_name="RHand_Socket",
                pivot_socket_name="Basic_ChildSocket",
            )

    def test_model_sidecar_resolves_exact_dds_paths(self):
        entries = self._entries(
            (
                ("character/model/body.pac", b"PAR "),
                (
                    "character/modelproperty/body.pac_xml",
                    '<Param name="_subMeshName" value="Body"/><ResourceReferencePath_ITexture value="character/texture/body.dds"/>',
                ),
                ("character/texture/body.dds", b"DDS "),
            )
        )

        plan = resolve_material_texture_graph(entries[0], entries)

        self.assertTrue(any(edge.relation_kind == "material_sidecar" for edge in plan.edges))
        texture_edges = [edge for edge in plan.edges if edge.relation_kind == "texture"]
        self.assertEqual([edge.related_path for edge in texture_edges], ["character/texture/body.dds"])
        self.assertEqual(texture_edges[0].confidence, "exact_path")

    def test_model_sidecar_resolves_hkt_physics_and_socket_descriptors(self):
        entries = self._entries(
            (
                ("character/model/body.pac", b"PAR "),
                (
                    "character/modelproperty/body.pac_xml",
                    '<SkinnedMesh _physicsFileName="character/bin__/meshphysics/body.hkt" '
                    'SocketFileName="character/descriptors/socketbonedata/body.sockets.xml" />',
                ),
                ("character/bin__/meshphysics/body.hkt", b"HKT"),
                ("character/descriptors/socketbonedata/body.sockets.xml", "<Sockets />"),
            )
        )

        plan = resolve_material_texture_graph(entries[0], entries)
        by_path = {edge.related_path: edge for edge in plan.edges}

        self.assertIn("character/bin__/meshphysics/body.hkt", by_path)
        self.assertEqual(by_path["character/bin__/meshphysics/body.hkt"].relation_kind, "physics")
        self.assertEqual(by_path["character/bin__/meshphysics/body.hkt"].role, "sidecar_physics_context")
        self.assertEqual(by_path["character/bin__/meshphysics/body.hkt"].include_policy, ARCHIVE_REL_INCLUDE_MANUAL)
        self.assertTrue(by_path["character/bin__/meshphysics/body.hkt"].risk)
        self.assertIn("character/descriptors/socketbonedata/body.sockets.xml", by_path)
        self.assertEqual(by_path["character/descriptors/socketbonedata/body.sockets.xml"].role, "sidecar_socket_descriptor")

    def test_model_sidecar_reports_missing_hkt_physics_descriptor(self):
        entries = self._entries(
            (
                ("character/model/body.pac", b"PAR "),
                ("character/modelproperty/body.pac_xml", '<SkinnedMesh _physicsFileName="character/model/body.hkt" />'),
            )
        )

        plan = resolve_material_texture_graph(entries[0], entries)
        unresolved = [edge for edge in plan.edges if edge.unresolved]

        self.assertEqual(1, len(unresolved))
        self.assertEqual("character/model/body.hkt", unresolved[0].related_path)
        self.assertEqual("sidecar_physics_context", unresolved[0].role)

    def test_app_xml_graph_reaches_prefab_model_sidecar_and_textures(self):
        entries = self._entries(
            (
                ("character/appearance/a.app_xml", '<Appearance><Nude Name="body_a" /><Customization MeshParamFile="meshparam_a" /></Appearance>'),
                ("character/prefab/body_a.prefabdata_xml", '<Prefab FileName="body_a.pac" />'),
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'),
                ("character/texture/body_a.dds", b"DDS "),
                ("character/customization/meshparam_a.xml", "<MeshParam />"),
            )
        )

        plan = build_archive_relationship_plan(entries[0], entries)
        paths = {edge.related_path for edge in plan.edges}

        self.assertIn("character/prefab/body_a.prefabdata_xml", paths)
        self.assertIn("character/model/body_a.pac", paths)
        self.assertIn("character/modelproperty/body_a.pac_xml", paths)
        self.assertIn("character/texture/body_a.dds", paths)
        self.assertIn("character/customization/meshparam_a.xml", paths)

    def test_table_catalog_edges_carry_field_provenance(self):
        entries = self._entries(
            (
                ("gamedata/binary__/client/bin/uimaptextureinfo.pabgb", b"\x00ui/map/world_icon.dds\x00"),
                ("ui/map/world_icon.dds", b"DDS "),
            )
        )

        plan = build_archive_relationship_plan(entries[0], entries)
        edges = [edge for edge in plan.edges if edge.related_path == "ui/map/world_icon.dds"]

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].source_table, "UIMapTextureInfo")
        self.assertEqual(edges[0].source_field, "_uiTextureName")
        self.assertEqual(edges[0].confidence, "table_string_reference")
        self.assertIn("UIMapTextureInfo._uiTextureName", edges[0].reason)

        references = build_archive_relationship_references(
            entries[0],
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = build_archive_asset_family_graph(entries[0], references)

        self.assertTrue(any(reference.source_table == "UIMapTextureInfo" for reference in references))
        self.assertTrue(
            any(
                row.confidence == "Table" and "UIMapTextureInfo._uiTextureName" in row.reason
                for row in graph.member_rows
            )
        )

    def test_app_xml_preview_referenced_files_uses_relationship_graph(self):
        entries = self._entries(
            (
                ("character/appearance/a.app_xml", '<Appearance><Nude Name="body_a" /><Customization MeshParamFile="meshparam_a" /></Appearance>'),
                ("character/prefab/body_a.prefabdata_xml", '<Prefab FileName="body_a.pac" />'),
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'),
                ("character/texture/body_a.dds", b"DDS "),
                ("character/customization/meshparam_a.xml", "<MeshParam />"),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        paths = {reference.resolved_archive_path for reference in result.model_texture_references}

        self.assertIn("character/prefab/body_a.prefabdata_xml", paths)
        self.assertIn("character/model/body_a.pac", paths)
        self.assertIn("character/modelproperty/body_a.pac_xml", paths)
        self.assertIn("character/texture/body_a.dds", paths)
        self.assertIn("character/customization/meshparam_a.xml", paths)

    def test_prefabdata_preview_referenced_files_resolves_model_skeleton_and_physics(self):
        entries = self._entries(
            (
                (
                    "character/prefab/body_a.prefabdata_xml",
                    '<Prefab FileName="body_a.pac" SkeletonName="identityskeleton.pab" RagdollName="body_a.hkx" />',
                ),
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'),
                ("character/texture/body_a.dds", b"DDS "),
                ("character/identityskeleton.pab", b"PAB"),
                ("character/bin/body_a.hkx", b"HKX"),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        paths = {reference.resolved_archive_path for reference in result.model_texture_references}

        self.assertIn("character/model/body_a.pac", paths)
        self.assertIn("character/modelproperty/body_a.pac_xml", paths)
        self.assertIn("character/texture/body_a.dds", paths)
        self.assertIn("character/identityskeleton.pab", paths)
        self.assertIn("character/bin/body_a.hkx", paths)

    def test_same_stem_metadata_relationships_include_prefab_and_animation_companions(self):
        entries = self._entries(
            (
                ("character/model/body_a.pac", b"PAR "),
                ("character/model/body_a.meshinfo", b"MeshInfo\x00"),
                ("character/model/body_a.prefab", b"SceneObject\x00character/model/body_a.pac\x00"),
                ("character/model/body_a.pappt", b"SceneObject\x00character/model/body_a.pac\x00"),
                ("character/model/body_a.pamhc", b"MaterialParameterTexture\x00character/modelproperty/body_a.pac_xml\x00"),
                ("character/bin__/meshphysics/body_a.hkx", b"HKX"),
                ("character/animation/body_a.motionblending", b"MotionBlend\x00"),
                ("character/animation/body_a.paa_metabin", b"AnimationMetaData\x00"),
            )
        )

        references = build_archive_relationship_references(
            entries[0],
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        by_path = {reference.resolved_archive_path: reference for reference in references}

        self.assertIn("character/model/body_a.meshinfo", by_path)
        self.assertIn("character/model/body_a.prefab", by_path)
        self.assertIn("character/model/body_a.pappt", by_path)
        self.assertIn("character/model/body_a.pamhc", by_path)
        self.assertIn("character/bin__/meshphysics/body_a.hkx", by_path)
        self.assertEqual(by_path["character/bin__/meshphysics/body_a.hkx"].relation_group, "Physics / Collision")
        self.assertEqual(by_path["character/bin__/meshphysics/body_a.hkx"].reference_kind, "physics")

    def test_model_family_resolves_left_right_prefab_variants_without_missing_prefab(self):
        prefab_payload = (
            b"_attachedSocketName\x00_pivotSocketName\x00_applyPosition\x00_applyRotation\x00_applyScale\x00"
            b"Pelvis_L_Socket\x00Pelvis_L_ChildSocket\x00"
            b"character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0110.pac\x00"
        )
        entries = self._entries(
            (
                ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0110.pac", b"PAR "),
                (
                    "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0110_l.prefab",
                    prefab_payload,
                ),
                (
                    "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_0110_r.prefab",
                    prefab_payload,
                ),
            )
        )

        references = build_archive_relationship_references(
            entries[0],
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = build_archive_asset_family_graph(entries[0], references)
        resolved_paths = {reference.resolved_archive_path for reference in references}
        prefab_rows = [row for row in graph.member_rows if row.group == "Prefab / Metadata"]

        self.assertIn(entries[1].path, resolved_paths)
        self.assertIn(entries[2].path, resolved_paths)
        self.assertTrue(any(row.display_name == "cd_phm_01_sword_0110_l.prefab" for row in prefab_rows))
        self.assertTrue(any(row.display_name == "cd_phm_01_sword_0110_r.prefab" for row in prefab_rows))
        self.assertFalse(any(row.status == "Missing" for row in prefab_rows))

    def test_asset_family_graph_groups_model_companions_with_evidence_and_summary(self):
        entries = self._entries(
            (
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'),
                ("character/texture/body_a.dds", b"DDS "),
                ("character/model/body_a.meshinfo", b"MeshInfo\x00"),
                ("character/model/body_a.prefab", b"SceneObject\x00character/model/body_a.pac\x00"),
                ("character/model/body_a.pappt", b"SceneObject\x00character/model/body_a.pac\x00"),
                ("character/model/body_a.pamhc", b"MaterialParameterTexture\x00character/modelproperty/body_a.pac_xml\x00"),
                ("character/bin__/meshphysics/body_a.hkx", b"HKX"),
                ("character/model/body_a.pab", b"PAB"),
                ("character/animation/body_a.motionblending", b"MotionBlend\x00"),
            )
        )
        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = result.asset_family_graph or build_archive_asset_family_graph(entries[0], result.model_texture_references)
        rows_by_group = {}
        for row in graph.member_rows:
            rows_by_group.setdefault(row.group, []).append(row)

        self.assertIn("Selected Model", rows_by_group)
        self.assertIn("Material", rows_by_group)
        self.assertIn("Textures", rows_by_group)
        self.assertIn("Physics / HKX", rows_by_group)
        self.assertIn("MeshInfo", rows_by_group)
        self.assertIn("Prefab / Metadata", rows_by_group)
        self.assertIn("Animation / Motion", rows_by_group)
        self.assertTrue(any(row.display_name == "body_a.pappt" for row in rows_by_group["Prefab / Metadata"]))
        self.assertTrue(any(row.display_name == "body_a.pamhc" for row in rows_by_group["Material"]))
        self.assertTrue(any(row.source_evidence in {"Sidecar", "Exact"} for row in rows_by_group["Material"]))
        self.assertTrue(any(row.source_evidence in {"Exact", "Path hint", "Sidecar"} for row in rows_by_group["Textures"]))
        self.assertTrue(any(row.include_policy == "manual" for row in rows_by_group["Physics / HKX"]))
        self.assertIn("Model OK", graph.summary)
        self.assertIn("texture", graph.summary)

    def test_asset_family_graph_uses_hkt_sidecar_physics_without_fake_missing_hkx(self):
        entries = self._entries(
            (
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<SkinnedMesh _physicsFileName="character/bin__/meshphysics/body_a.hkt" />'),
                ("character/bin__/meshphysics/body_a.hkt", b"HKT"),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = result.asset_family_graph or build_archive_asset_family_graph(entries[0], result.model_texture_references)
        physics_rows = [row for row in graph.member_rows if row.group == "Physics / HKX"]

        self.assertTrue(any(row.display_name == "body_a.hkt" and row.status == "Resolved" for row in physics_rows))
        self.assertFalse(any(row.status == "Missing" for row in physics_rows))

    def test_asset_family_graph_does_not_label_partial_dds_storage_as_partial_relationship(self):
        entries = self._entries(
            (
                ("character/model/body_a.pac", b"PAR "),
                ("character/texture/body_a.dds", b"DDS "),
            )
        )
        entries[1].flags = 1
        reference = ArchiveModelTextureReference(
            reference_name="character/texture/body_a.dds",
            resolved_archive_path="character/texture/body_a.dds",
            resolved_entry=entries[1],
            resolution_status="resolved",
            relation_confidence="exact_path",
            relation_group="Textures",
            relation_reason="Exact archive path.",
        )

        graph = build_archive_asset_family_graph(entries[0], (reference,))
        texture_rows = [row for row in graph.member_rows if row.group == "Textures"]

        self.assertEqual(1, len(texture_rows))
        self.assertEqual("Resolved", texture_rows[0].status)
        self.assertEqual("Exact", texture_rows[0].source_evidence)
        self.assertIn("Partial DDS storage", texture_rows[0].warning)

    def test_item_finder_catalog_icon_row_becomes_recommended_asset_family_member(self):
        entries = self._entries(
            (
                ("character/model/cd_phm_01_sword_0166.pac", b"PAR "),
                ("ui/itemicon/itemicon_prefab_cd_phm_01_sword_0166.dds", b"DDS "),
            )
        )
        catalog = [
            {
                "display_name": "Sword of the Lord",
                "internal_name": "Item_OneHandSword_0166",
                "pac_files": (entries[0].path,),
                "model_stems": ("cd_phm_01_sword_0166",),
                "icon_paths": (entries[1].path,),
            }
        ]

        references = build_archive_item_icon_references_from_catalog(
            entries[0],
            catalog,
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = build_archive_asset_family_graph(entries[0], references)
        icon_rows = [row for row in graph.member_rows if row.group == "Item Icons"]

        self.assertEqual(1, len(references))
        self.assertEqual("item_icon", references[0].reference_kind)
        self.assertEqual("Item Icons", references[0].relation_group)
        self.assertEqual(1, len(icon_rows))
        self.assertEqual("Inventory Icon", icon_rows[0].role)
        self.assertEqual("Resolved", icon_rows[0].status)
        self.assertEqual("Item Finder", icon_rows[0].source_evidence)
        self.assertEqual("recommended", icon_rows[0].include_policy)
        self.assertIs(icon_rows[0].resolved_entry, entries[1])
        export_default_entries = [
            row.resolved_entry
            for row in graph.member_rows
            if row.include_policy in {"required", "recommended"} and row.status != "Missing"
        ]
        self.assertIn(entries[1], export_default_entries)

    def test_item_finder_catalog_links_related_texture_selection_to_inventory_icon(self):
        entries = self._entries(
            (
                ("character/model/cd_phm_01_sword_0166.pac", b"PAR "),
                ("character/texture/cd_phm_01_sword_0166_d.dds", b"DDS "),
                ("ui/itemicon/icon_prefab_cd_phm_01_sword_0166.dds", b"DDS "),
            )
        )
        catalog = [
            {
                "display_name": "Sword of the Lord",
                "pac_files": (entries[0].path,),
                "model_stems": ("cd_phm_01_sword_0166",),
                "icon_paths": (entries[2].path,),
            }
        ]
        owner_model_reference = ArchiveModelTextureReference(
            reference_name=entries[0].basename,
            resolved_archive_path=entries[0].path,
            resolved_entry=entries[0],
            resolution_status="resolved",
            relation_confidence="derived_same_stem",
            relation_group="Used By / Model",
            reference_kind="used_by",
        )

        references = build_archive_item_icon_references_from_catalog(
            entries[1],
            catalog,
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
            related_references=(owner_model_reference,),
        )
        graph = build_archive_asset_family_graph(entries[1], (owner_model_reference, *references))
        icon_rows = [row for row in graph.member_rows if row.group == "Item Icons"]

        self.assertEqual([entries[2].path], [reference.resolved_archive_path for reference in references])
        self.assertEqual("Inventory Icon", icon_rows[0].role)
        self.assertEqual("Item Finder", icon_rows[0].source_evidence)
        self.assertEqual("recommended", icon_rows[0].include_policy)

    def test_item_finder_catalog_links_selected_inventory_icon_to_owner_model(self):
        entries = self._entries(
            (
                ("character/model/cd_phm_01_sword_0166.pac", b"PAR "),
                ("ui/itemicon/icon_cd_phm_01_sword_0166.dds", b"DDS "),
            )
        )
        catalog = [
            {
                "display_name": "Sword of the Lord",
                "pac_files": (entries[0].path,),
                "model_stems": ("cd_phm_01_sword_0166",),
                "icon_paths": (entries[1].path,),
            }
        ]

        references = build_archive_item_icon_references_from_catalog(
            entries[1],
            catalog,
            archive_entries_by_normalized_path=build_archive_entry_path_index(entries),
            archive_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        graph = build_archive_asset_family_graph(entries[1], references)
        model_rows = [row for row in graph.member_rows if row.group == "Selected Model"]
        icon_rows = [row for row in graph.member_rows if row.group == "Item Icons"]

        self.assertEqual([entries[0].path], [reference.resolved_archive_path for reference in references])
        self.assertEqual("used_by", references[0].reference_kind)
        self.assertEqual("Item Finder", model_rows[0].source_evidence)
        self.assertEqual("required", model_rows[0].include_policy)
        self.assertEqual("Inventory Icon", icon_rows[0].role)

    def test_socket_xml_parser_recovers_socket_transforms_and_stack_groups(self):
        document = parse_socket_bone_data_xml(
            """
            <SocketBoneData>
              <SocketList>
                <Socket Name="Pelvis_L_Socket" Parent="Bip01 Pelvis"
                  Rotation="0 0 0 1" Translation="1.0 2.5 -3.0" UIView="Pelvis L" />
                <Socket Name="Pelvis_L_ChildSocket" Parent="B_Weapon_0001"
                  Rotation="0.1 0.2 0.3 0.4" Translation="4 5 6" />
              </SocketList>
              <StackEquipInfoList>
                <StackEquipInfo EquipTypeName="Pelvis_L" OriginBoneName="Bip01 Pelvis" Axis="Y">
                  <Socket Name="Pelvis_L_Socket" />
                </StackEquipInfo>
              </StackEquipInfoList>
            </SocketBoneData>
            """,
            "character/phm_01.pab.sockets.xml",
        )

        self.assertEqual(2, len(document.sockets))
        self.assertEqual("Pelvis_L_Socket", document.sockets[0].name)
        self.assertEqual("Bip01 Pelvis", document.sockets[0].parent)
        self.assertEqual((1.0, 2.5, -3.0), document.sockets[0].translation)
        self.assertEqual(1, len(document.stack_equip_infos))
        self.assertEqual("Pelvis_L", document.stack_equip_infos[0].equip_type_name)
        self.assertEqual(("Pelvis_L_Socket",), document.stack_equip_infos[0].socket_names)

    def test_part_in_out_parser_and_class_filter_support_descriptor_rows(self):
        document = parse_part_in_out_socket_info_xml(
            """
            <PartInOutSocket PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"
                OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket" />
            <PartInOutSocket PartName="CD_TwoHandWeapon_Sword" InSocketBone="Spine2_B_SubWeapon_Socket"
                OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket" />
            """,
            "character/phm_description_player_kliff.xml",
        )

        self.assertEqual(2, len(document.rows))
        self.assertEqual("onehand_sword", infer_part_in_out_weapon_class(document.rows[0].part_name))
        self.assertEqual("twohand_sword", infer_part_in_out_weapon_class(document.rows[1].part_name))
        self.assertEqual(["CD_MainWeapon_Sword_R"], [row.part_name for row in part_in_out_rows_for_weapon_class(document, "onehand_sword")])

    def test_part_in_out_profile_patch_detects_imported_back_and_hip_style_changes(self):
        base = """
        <PartInOutSocket PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket" OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket" />
        <PartInOutSocket PartName="CD_TwoHandWeapon_Sword" InSocketBone="Spine2_B_SubWeapon_Socket" OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket" />
        """
        profile = """
        <PartInOutSocket PartName="CD_MainWeapon_Sword_R" InSocketBone="Spine1_B_Socket" OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket" />
        <PartInOutSocket PartName="CD_TwoHandWeapon_Sword" InSocketBone="Pelvis_B_Socket" OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket" />
        """

        one_hand = build_part_in_out_socket_profile_patch(base, profile, weapon_class="onehand_sword")
        self.assertIn('PartName="CD_MainWeapon_Sword_R" InSocketBone="Spine1_B_Socket"', one_hand.text)
        self.assertIn('PartName="CD_TwoHandWeapon_Sword" InSocketBone="Spine2_B_SubWeapon_Socket"', one_hand.text)
        self.assertEqual(("CD_MainWeapon_Sword_R",), one_hand.patched_part_names)

        two_hand = build_part_in_out_socket_profile_patch(base, profile, weapon_class="twohand_sword")
        self.assertIn('PartName="CD_TwoHandWeapon_Sword" InSocketBone="Pelvis_B_Socket"', two_hand.text)
        self.assertEqual(("CD_TwoHandWeapon_Sword",), two_hand.patched_part_names)

    def test_part_in_out_attach_point_patch_updates_selected_class_only(self):
        base = """
        <PartInOutSocket PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket" InChildSocketBone="Pelvis_L_ChildSocket" />
        <PartInOutSocket PartName="CD_TwoHandWeapon_Sword" InSocketBone="Spine2_B_SubWeapon_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket" />
        """

        result = build_part_in_out_socket_attach_point_patch(
            base,
            weapon_class="twohand_sword",
            in_socket_bone="Pelvis_B_Socket",
            in_child_socket_bone="Pelvis_R_ChildSocket",
        )

        self.assertIn('CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"', result.text)
        self.assertIn('CD_TwoHandWeapon_Sword" InSocketBone="Pelvis_B_Socket"', result.text)
        self.assertIn('InChildSocketBone="Pelvis_R_ChildSocket"', result.text)

    def test_socket_profile_patch_detects_manual_transform_changes(self):
        base = """
        <SocketBoneData><SocketList>
          <Socket Name="Spine1_B_Socket" Parent="Bip_Weapon_Attach_In_01" Rotation="0 0 0 1" Translation="0 0 0"/>
          <Socket Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00" Rotation="0 0 0 1" Translation="0 0 0"/>
        </SocketList></SocketBoneData>
        """
        profile = """
        <SocketBoneData><SocketList>
          <Socket Name="Spine1_B_Socket" Parent="Bip_Weapon_Attach_In_01" Rotation="0.181649 -0.660709 -0.705316 0.181649" Translation="-0.20000 0.250000 -0.055000"/>
          <Socket Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00" Rotation="0 0 0 1" Translation="0 0 0.050000"/>
        </SocketList></SocketBoneData>
        """

        result = build_socket_bone_data_profile_patch(base, profile, socket_names=("Spine1_B_Socket",))

        self.assertIn('Name="Spine1_B_Socket" Parent="Bip_Weapon_Attach_In_01" Rotation="0.181649 -0.660709 -0.705316 0.181649" Translation="-0.200000 0.250000 -0.055000"', result.text)
        self.assertIn('Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00" Rotation="0 0 0 1" Translation="0 0 0"', result.text)
        self.assertEqual(("Spine1_B_Socket",), result.patched_part_names)

    def test_asset_family_graph_adds_read_only_attachment_placement_evidence(self):
        prefab_payload = (
            b"_attachedSocketName\x00_pivotSocketName\x00_applyPosition\x00_applyRotation\x00_applyScale\x00"
            b"_worldTransform\x00_tiledTransform\x00_socketFileName\x00_skeletonFileName\x00_skinnedMeshFileName\x00"
            b"Pelvis_L_Socket\x00Pelvis_L_ChildSocket\x00CD_MainWeapon_Sword_R\x00"
            b"character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0053.pac\x00"
            b"character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml\x00"
            b"character/phm_01.pab\x00"
        )
        socket_xml = """
            <SocketBoneData>
              <SocketList>
                <Socket Name="Pelvis_L_Socket" Parent="Bip01 Pelvis"
                  Rotation="0 0 0 1" Translation="1 2 3" />
                <Socket Name="Pelvis_L_ChildSocket" Parent="B_Weapon_0001"
                  Rotation="0 0 0 1" Translation="4 5 6" />
              </SocketList>
            </SocketBoneData>
        """
        entries = self._entries(
            (
                ("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac", b"PAR "),
                ("character/prefab/cd_phm_02_sword_0015.prefab", prefab_payload),
                (
                    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml",
                    socket_xml,
                ),
                ("character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0053.pac", b"PAR "),
                ("character/phm_01.pab", b"PAB"),
            )
        )
        references = (
            ArchiveModelTextureReference(
                reference_name=entries[1].path,
                resolved_archive_path=entries[1].path,
                resolved_entry=entries[1],
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Prefab / Metadata",
                reference_kind="prefab",
            ),
            ArchiveModelTextureReference(
                reference_name=entries[2].path,
                resolved_archive_path=entries[2].path,
                resolved_entry=entries[2],
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Prefab / Metadata",
                reference_kind="prefab_socket_descriptor",
            ),
        )

        graph = build_archive_asset_family_graph(entries[0], references)
        evidence = graph.attachment_evidence[0]
        placement_rows = [row for row in graph.member_rows if row.group == "Attachment / Placement"]

        self.assertEqual("Pelvis_L_Socket", evidence.character_socket_name)
        self.assertEqual("Bip01 Pelvis", evidence.character_socket_parent)
        self.assertEqual("Pelvis_L_ChildSocket", evidence.weapon_socket_name)
        self.assertEqual("B_Weapon_0001", evidence.weapon_socket_parent)
        self.assertIn("Final Attachment", evidence.placement_modes)
        self.assertTrue(placement_rows)
        self.assertEqual("manual", placement_rows[0].include_policy)
        self.assertIn("placement", graph.summary)

    def test_asset_family_graph_marks_missing_model_companions_without_fake_entries(self):
        entries = self._entries((("character/model/body_a.pac", b"PAR "),))

        graph = build_archive_asset_family_graph(entries[0], ())
        missing_groups = {row.group for row in graph.member_rows if row.status == "Missing"}

        self.assertIn("Material", missing_groups)
        self.assertIn("MeshInfo", missing_groups)
        self.assertIn("Physics / HKX", missing_groups)
        self.assertIn("Prefab / Metadata", missing_groups)
        self.assertIn("meshinfo missing", graph.summary)
        self.assertTrue(all(row.resolved_entry is None for row in graph.member_rows if row.status == "Missing"))

    def test_binary_prefab_graph_resolves_model_socket_physics_and_textures(self):
        entries = self._entries(
            (
                (
                    "character/bin/_prefab/test_shield.prefab",
                    b"SceneObject\x00"
                    b"character/model/test_shield.pacR\x00"
                    b"character/descriptors/socketbonedata/test_shield.sockets.xmlK\x00"
                    b"character/bin__/meshphysics/test_shield.hkxZ\x00",
                ),
                ("character/model/test_shield.pac", b"PAR "),
                ("character/modelproperty/test_shield.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/test_shield.dds"/>'),
                ("character/texture/test_shield.dds", b"DDS "),
                ("character/descriptors/socketbonedata/test_shield.sockets.xml", "<Sockets />"),
                ("character/bin__/meshphysics/test_shield.hkx", b"HKX"),
            )
        )

        plan = build_archive_relationship_plan(
            entries[0],
            entries,
            path_index=build_archive_entry_path_index(entries),
            basename_index=build_archive_entry_basename_index(entries),
        )
        paths = {edge.related_path for edge in plan.edges}
        roles = {edge.related_path: edge.role for edge in plan.edges}

        self.assertIn("character/model/test_shield.pac", paths)
        self.assertIn("character/descriptors/socketbonedata/test_shield.sockets.xml", paths)
        self.assertIn("character/bin__/meshphysics/test_shield.hkx", paths)
        self.assertIn("character/modelproperty/test_shield.pac_xml", paths)
        self.assertIn("character/texture/test_shield.dds", paths)
        self.assertEqual(roles["character/model/test_shield.pac"], "prefab_model_resource")
        self.assertEqual(roles["character/descriptors/socketbonedata/test_shield.sockets.xml"], "prefab_socket_descriptor")
        self.assertEqual(roles["character/bin__/meshphysics/test_shield.hkx"], "prefab_physics_context")

    def test_prefab_evidence_marks_material_override_hooks(self):
        rows = _prefab_evidence_rows(
            (
                {"name": "_materialInstanceParameters", "declared_type": "ReflectObjectPtr"},
                {"name": "_prefabMaterialReferences", "declared_type": "PrefabMaterialReference"},
            ),
            ("character/modelproperty/test_shield.pac_xml",),
        )

        labels = {row["label"] for row in rows}

        self.assertIn("Material override hooks", labels)

    def test_prefab_material_override_evidence_preserves_field_and_reference_routing(self):
        rows = _prefab_material_override_evidence_rows(
            (
                {
                    "name": "_overridedPbdMaterialProperty",
                    "declared_type": "ResourceReferencePath_IMaterial",
                    "offset": "0x40",
                    "descriptor_hex": "01020304",
                },
                {"name": "_dyeingColorOverrides", "declared_type": "Vector<Byte4>"},
            ),
            (
                "character/modelproperty/test_shield.pac_xml",
                "character/shader/skinned.technique",
                "character/texture/test_shield_sp.dds",
            ),
        )

        roles = {row["role"] for row in rows}
        fields = {row["field_name"]: row for row in rows}

        self.assertIn("material_instance_override_field", roles)
        self.assertIn("resolved_material_sidecar_reference", roles)
        self.assertIn("resolved_shader_material_reference", roles)
        self.assertIn("resolved_texture_reference", roles)
        self.assertEqual("read_only_layout_unproven", fields["_overridedPbdMaterialProperty"]["edit_status"])

    def test_material_sidecar_preview_referenced_files_dedupes_graph_texture(self):
        entries = self._entries(
            (
                ("character/model/body_a.pac", b"PAR "),
                ("character/modelproperty/body_a.pac_xml", '<ResourceReferencePath_ITexture value="character/texture/body_a.dds"/>'),
                ("character/texture/body_a.dds", b"DDS "),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[1],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        paths = [reference.resolved_archive_path for reference in result.model_texture_references]

        self.assertEqual(paths.count("character/texture/body_a.dds"), 1)

    def test_direct_pam_and_pamlod_sidecar_previews_resolve_dds(self):
        for sidecar_path in (
            "character/modelproperty/body_a.pam_xml",
            "character/modelproperty/body_a.pamlod_xml",
        ):
            with self.subTest(sidecar_path=sidecar_path):
                entries = self._entries(
                    (
                        (
                            sidecar_path,
                            '<MaterialParameterTexture _name="_baseColorTexture">'
                            '<ResourceReferencePath_ITexture value="character/texture/body_a_d.dds"/>'
                            "</MaterialParameterTexture>",
                        ),
                        ("character/texture/body_a_d.dds", b"DDS "),
                    )
                )

                result = build_archive_preview_result(
                    None,
                    entries[0],
                    texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
                    texture_entries_by_basename=build_archive_entry_basename_index(entries),
                )
                paths = {reference.resolved_archive_path for reference in result.model_texture_references}

                self.assertIn("character/texture/body_a_d.dds", paths)

    def test_sidecar_graph_preserves_distinct_texture_parameter_roles(self):
        entries = self._entries(
            (
                (
                    "character/modelproperty/body_a.pac_xml",
                    '<SkinnedMeshMaterialWrapper _subMeshName="Body">'
                    '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture value="character/texture/body_a_d.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture value="character/texture/body_a_n.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_materialTexture"><ResourceReferencePath_ITexture value="character/texture/body_a_ma.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture value="character/texture/body_a_disp.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_maskTexture"><ResourceReferencePath_ITexture value="character/texture/body_a_mask.dds"/></MaterialParameterTexture>'
                    "</SkinnedMeshMaterialWrapper>",
                ),
                ("character/texture/body_a_d.dds", b"DDS "),
                ("character/texture/body_a_n.dds", b"DDS "),
                ("character/texture/body_a_ma.dds", b"DDS "),
                ("character/texture/body_a_disp.dds", b"DDS "),
                ("character/texture/body_a_mask.dds", b"DDS "),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        by_path = {reference.resolved_archive_path: reference for reference in result.model_texture_references}

        self.assertEqual(
            {
                "character/texture/body_a_d.dds",
                "character/texture/body_a_n.dds",
                "character/texture/body_a_ma.dds",
                "character/texture/body_a_disp.dds",
                "character/texture/body_a_mask.dds",
            },
            set(by_path),
        )
        self.assertEqual(by_path["character/texture/body_a_d.dds"].semantic_label, "Base Color Texture")
        self.assertEqual(by_path["character/texture/body_a_n.dds"].semantic_label, "Normal Texture")

    def test_app_xml_duplicate_basename_prefers_path_local_graph(self):
        entries = self._entries(
            (
                ("character/a/appearance/body.app_xml", '<Appearance><Nude Name="body" /></Appearance>'),
                ("character/a/prefab/body.prefabdata_xml", '<Prefab FileName="body.pac" />'),
                ("character/a/model/body.pac", b"PAR "),
                ("character/a/modelproperty/body.pac_xml", '<ResourceReferencePath_ITexture value="character/a/texture/body.dds"/>'),
                ("character/a/texture/body.dds", b"DDS A"),
                ("character/b/prefab/body.prefabdata_xml", '<Prefab FileName="body.pac" />'),
                ("character/b/model/body.pac", b"PAR "),
                ("character/b/modelproperty/body.pac_xml", '<ResourceReferencePath_ITexture value="character/b/texture/body.dds"/>'),
                ("character/b/texture/body.dds", b"DDS B"),
            )
        )

        result = build_archive_preview_result(
            None,
            entries[0],
            texture_entries_by_normalized_path=build_archive_entry_path_index(entries),
            texture_entries_by_basename=build_archive_entry_basename_index(entries),
        )
        paths = {reference.resolved_archive_path for reference in result.model_texture_references}

        self.assertIn("character/a/prefab/body.prefabdata_xml", paths)
        self.assertIn("character/a/model/body.pac", paths)
        self.assertIn("character/a/texture/body.dds", paths)
        self.assertNotIn("character/b/prefab/body.prefabdata_xml", paths)
        self.assertNotIn("character/b/model/body.pac", paths)
        self.assertNotIn("character/b/texture/body.dds", paths)

    def test_character_swap_patch_changes_body_and_head_only(self):
        entries = self._entries(
            (
                (
                    "character/appearance/target.app_xml",
                    '<Appearance><Nude Name="target_body" CharacterScale="1.0" /><Head Name="target_head" /><Hair Name="target_hair" /></Appearance>',
                ),
                (
                    "character/appearance/source.app_xml",
                    '<Appearance><Nude Name="source_body" CharacterScale="1.2" /><Head Name="source_head" /><Hair Name="source_hair" /></Appearance>',
                ),
                ("character/prefab/source_body.prefabdata_xml", "<Prefab />"),
                ("character/prefab/source_head.prefabdata_xml", "<Prefab />"),
            )
        )

        plan = build_character_swap_plan(entries[0], entries[1], entries, swap_scope=SWAP_SCOPE_BODY_HEAD)
        patched = plan.patched_target_app_xml.decode("utf-8")

        self.assertEqual(plan.patched_target_app_path, "character/appearance/target.app_xml")
        self.assertIn("source_body", patched)
        self.assertIn("source_head", patched)
        self.assertIn("target_hair", patched)
        self.assertNotIn("source_hair", patched)
        self.assertTrue(any(edge.relation_kind == "appearance_patch" and edge.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED for edge in plan.edges))

    def test_duplicate_dds_basenames_are_not_collapsed_for_exact_path(self):
        entries = self._entries(
            (
                ("object/model/rock.pam", b"PAR "),
                ("object/model/rock.pami", '<ResourceReferencePath_ITexture value="object/texture/b/shared.dds"/>'),
                ("object/texture/a/shared.dds", b"DDS A"),
                ("object/texture/b/shared.dds", b"DDS B"),
            )
        )

        plan = resolve_material_texture_graph(entries[0], entries)
        texture_paths = [edge.related_path for edge in plan.edges if edge.relation_kind == "texture"]

        self.assertEqual(texture_paths, ["object/texture/b/shared.dds"])

    def test_skeleton_physics_and_missing_descriptors_are_manual_or_unresolved(self):
        entries = self._entries(
            (
                ("character/prefab/body.prefabdata_xml", '<Prefab SkeletonName="identityskeleton.pab" RagdollName="body.hkx" MissingName="missing.pabc" />'),
                ("character/identityskeleton.pab", b"PAB"),
                ("character/bin/body.hkx", b"HKX"),
            )
        )

        plan = build_archive_relationship_plan(entries[0], entries)
        skeleton = next(edge for edge in plan.edges if edge.relation_kind == "skeleton")
        physics = next(edge for edge in plan.edges if edge.relation_kind == "physics")
        unresolved = next(edge for edge in plan.edges if edge.unresolved)

        self.assertEqual(skeleton.include_policy, ARCHIVE_REL_INCLUDE_MANUAL)
        self.assertTrue(skeleton.risk)
        self.assertEqual(physics.include_policy, ARCHIVE_REL_INCLUDE_MANUAL)
        self.assertTrue(physics.risk)
        self.assertEqual(unresolved.related_path, "missing.pabc")

    def test_sidecar_topology_difference_is_reported_for_character_swap(self):
        entries = self._entries(
            (
                ("character/model/target.pac", b"PAR "),
                ("character/model/source.pac", b"PAR "),
                ("character/modelproperty/target.pac_xml", '<Param name="_subMeshName" value="TargetBody"/>'),
                ("character/modelproperty/source.pac_xml", '<Param name="_subMeshName" value="SourceBody"/>'),
                ("character/appearance/target.app_xml", '<Appearance><Nude Name="target" /></Appearance>'),
                ("character/appearance/source.app_xml", '<Appearance><Nude Name="source" /></Appearance>'),
            )
        )

        plan = build_character_swap_plan(entries[0], entries[1], entries)

        self.assertTrue(any("submesh wrappers differ" in warning for warning in plan.warnings))
        self.assertTrue(any(edge.role == "topology_reference" and edge.risk for edge in plan.edges))


if __name__ == "__main__":
    unittest.main()
