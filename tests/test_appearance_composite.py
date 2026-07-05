import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core.appearance_composite import (
    AppearanceCompositeModelOverride,
    build_appearance_composite_model,
    build_appearance_composite_preview_plan,
    build_appearance_single_pac_swap_package_plan,
    build_appearance_single_pac_swap_plan,
    find_appearance_composite_candidates,
)
from cdmw.core.archive import build_archive_entry_basename_index, build_archive_entry_path_index
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


class AppearanceCompositeTests(unittest.TestCase):
    def _entries(self, payloads):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        paz_path = root / "0.paz"
        pamt_path = root / "0.pamt"
        offset = 0
        entries = []
        with paz_path.open("wb") as handle:
            for path, payload in payloads:
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

    def _indexes(self, entries):
        return build_archive_entry_path_index(entries), build_archive_entry_basename_index(entries)

    def _submesh(self, name, positions):
        return SubMesh(
            name=name,
            material=f"{name}_mat",
            texture=f"{name}_d.dds",
            vertices=list(positions),
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            normals=[(0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
            faces=[(0, 1, 2)],
        )

    def _parsed_mesh(self, path, name, positions):
        submesh = self._submesh(name, positions)
        return ParsedMesh(
            path=path,
            format="pac",
            submeshes=[submesh],
            total_vertices=len(submesh.vertices),
            total_faces=len(submesh.faces),
            has_uvs=True,
        )

    def _prefab_payload(self):
        return (
            b"SceneObject\x00"
            b"_attachedSocketName\x00_pivotSocketName\x00_skinnedMeshFileName\x00_socketFileName\x00"
            b"Pelvis_L_Socket\x00Pelvis_L_ChildSocket\x00"
            b"character/model/1_pc/1_phm/weapon/1_onehandweapon/test_sword.pac\x00"
            b"character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/test_sword.sockets.xml\x00"
        )

    def test_nested_app_xml_sections_are_preserved_and_defaults_set(self):
        app_xml = """
        <Appearance>
          <Nude>
            <Prefab Name="cd_phm_00_nude_01_0002_macduff" CharacterScale="1.2" />
          </Nude>
          <Head>
            <Prefab Name="cd_phm_00_head_00_0001_macduff" HeadScale="0.9" />
          </Head>
          <Hair>
            <Prefab Name="cd_phm_00_hair_00_0001" />
            <Prefab Name="cd_phm_00_hair_00_0002" />
          </Hair>
          <Armor>
            <Prefab Name="cd_phm_00_ub_inner_0054" />
            <Prefab Name="cd_phm_00_parthide_0054" />
            <Prefab Name="cd_phm_00_bag_0054" />
            <Prefab Name="cd_phm_00_ub_00_0054" Preview="true" />
          </Armor>
        </Appearance>
        """
        entries = self._entries(
            (
                ("character/appearance/1_pc/1_phm/cd_phm_macduff_00000.app_xml", app_xml),
                ("character/model/1_pc/1_phm/body/cd_phm_00_nude_01_0002.pac", b"PAR "),
                ("character/model/1_pc/1_phm/head/cd_phm_00_head_00_0001.pac", b"PAR "),
                ("character/model/1_pc/1_phm/hair/cd_phm_00_hair_00_0001.pac", b"PAR "),
                ("character/model/1_pc/1_phm/hair/cd_phm_00_hair_00_0002.pac", b"PAR "),
                ("character/model/1_pc/1_phm/armor/cd_phm_00_ub_inner_0054.pac", b"PAR "),
                ("character/model/1_pc/1_phm/armor/cd_phm_00_parthide_0054.pac", b"PAR "),
                ("character/model/1_pc/1_phm/armor/cd_phm_00_bag_0054.pac", b"PAR "),
                ("character/model/1_pc/1_phm/armor/cd_phm_00_ub_00_0054.pac", b"PAR "),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_composite_preview_plan(
            entries[0],
            entries,
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertEqual(["Nude", "Head", "Hair", "Hair", "Armor", "Armor", "Armor", "Armor"], [c.section for c in plan.components])
        nude = plan.components[0]
        self.assertEqual(1.2, nude.scale)
        self.assertTrue(nude.default_selected)
        self.assertEqual(("character/model/1_pc/1_phm/body/cd_phm_00_nude_01_0002.pac",), tuple(e.path for e in nude.resolved_model_entries))
        self.assertEqual(0.9, plan.components[1].scale)
        inner = next(component for component in plan.components if component.prefab_name == "cd_phm_00_ub_inner_0054")
        self.assertTrue(inner.default_selected)
        part_hide = next(component for component in plan.components if "parthide" in component.prefab_name)
        self.assertFalse(part_hide.default_selected)
        self.assertTrue(any("Part-hide" in warning for warning in part_hide.warnings))
        preview_armor = next(component for component in plan.components if component.prefab_name == "cd_phm_00_ub_00_0054")
        self.assertTrue(preview_armor.preview_flag)
        self.assertTrue(preview_armor.default_selected)

    def test_app_candidate_picker_finds_referencing_app_xml(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/cd_phm_macduff_00000.app_xml",
                    '<Appearance><Armor><Prefab Name="cd_phm_00_ub_00_0054" Preview="true" /></Armor></Appearance>',
                ),
                ("character/model/1_pc/1_phm/armor/cd_phm_00_ub_00_0054.pac", b"PAR "),
            )
        )

        candidates = find_appearance_composite_candidates(entries[1], entries)

        self.assertEqual((entries[0],), candidates)

    def test_actor_nude_prefabdata_falls_back_to_default_family_body_mesh(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/cd_phm_macduff/cd_phm_macduff_00000.app_xml",
                    '<Appearance><Nude><Prefab Name="cd_phm_00_nude_01_0002_macduff" CharacterScale="1.02571" /></Nude></Appearance>',
                ),
                (
                    "character/prefab/1_pc/01_phm/nude/cd_phm_00_nude_01_0002_macduff.prefabdata_xml",
                    '<NudePrefabData><SkeletonVariationName FileName="1_pc/1_phm/nude/cd_phm_00_nude_01_0002.pabc"/></NudePrefabData>',
                ),
                ("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac", b"PAR "),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_composite_preview_plan(
            entries[0],
            entries,
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertEqual(1, len(plan.components))
        self.assertEqual(("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac",), tuple(e.path for e in plan.components[0].resolved_model_entries))
        self.assertFalse(plan.components[0].unresolved_references)

    def test_prefab_relationship_resolves_model_and_socket_context(self):
        entries = self._entries(
            (
                ("character/bin__/prefab/weapon/test_sword.prefab", self._prefab_payload()),
                ("character/model/1_pc/1_phm/weapon/1_onehandweapon/test_sword.pac", b"PAR "),
                (
                    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/test_sword.sockets.xml",
                    "<SocketBoneData />",
                ),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_composite_preview_plan(
            entries[0],
            entries,
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertIsNone(plan.appearance_entry)
        self.assertEqual(1, len(plan.components))
        component = plan.components[0]
        self.assertEqual(("character/model/1_pc/1_phm/weapon/1_onehandweapon/test_sword.pac",), tuple(e.path for e in component.resolved_model_entries))
        self.assertEqual(
            ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/test_sword.sockets.xml",),
            tuple(e.path for e in component.resolved_context_entries),
        )

    def test_composite_builder_merges_before_final_normalization(self):
        app_xml = """
        <Appearance>
          <Nude><Prefab Name="body_a" /></Nude>
          <Armor><Prefab Name="armor_a" Preview="true" /></Armor>
        </Appearance>
        """
        entries = self._entries(
            (
                ("character/appearance/a.app_xml", app_xml),
                ("character/model/body_a.pac", b"PAR "),
                ("character/model/armor_a.pac", b"PAR "),
            )
        )
        path_index, basename_index = self._indexes(entries)
        plan = build_appearance_composite_preview_plan(
            entries[0],
            entries,
            path_index=path_index,
            basename_index=basename_index,
        )

        def fake_parse_mesh(data, path):
            if path.endswith("body_a.pac"):
                return self._parsed_mesh(path, "body", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
            return self._parsed_mesh(path, "armor", [(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)])

        with patch("cdmw.core.appearance_composite.parse_mesh", side_effect=fake_parse_mesh):
            result = build_appearance_composite_model(
                plan,
                selected_component_indexes=(0, 1),
                path_index=path_index,
                basename_index=basename_index,
            )

        self.assertIsNotNone(result.preview_model)
        preview_model = result.preview_model
        self.assertEqual(2, preview_model.mesh_count)
        self.assertEqual((5.5, 0.5, 0.0), preview_model.normalization_center)
        body_mesh = next(mesh for mesh in preview_model.meshes if "body_a.pac" in mesh.preview_role)
        armor_mesh = next(mesh for mesh in preview_model.meshes if "armor_a.pac" in mesh.preview_role)
        self.assertLess(max(position[0] for position in body_mesh.positions), min(position[0] for position in armor_mesh.positions))
        self.assertEqual(0, body_mesh.source_vertex_range_start)
        self.assertEqual(3, body_mesh.source_vertex_range_count)
        self.assertEqual(0, body_mesh.source_face_range_start)
        self.assertEqual(1, body_mesh.source_face_range_count)
        self.assertEqual([], body_mesh.source_vertex_indices)
        self.assertEqual([], body_mesh.source_face_indices)

    def test_composite_builder_can_use_what_if_model_override(self):
        app_xml = """
        <Appearance>
          <Nude><Prefab Name="body_a" /></Nude>
          <Armor><Prefab Name="armor_a" Preview="true" /></Armor>
        </Appearance>
        """
        entries = self._entries(
            (
                ("character/appearance/a.app_xml", app_xml),
                ("character/model/body_a.pac", b"PAR "),
                ("character/model/armor_a.pac", b"PAR "),
                ("character/model/armor_b.pac", b"PAR "),
            )
        )
        path_index, basename_index = self._indexes(entries)
        plan = build_appearance_composite_preview_plan(
            entries[0],
            entries,
            path_index=path_index,
            basename_index=basename_index,
        )

        parsed_paths = []

        def fake_parse_mesh(data, path):
            parsed_paths.append(path)
            if path.endswith("body_a.pac"):
                return self._parsed_mesh(path, "body", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
            if path.endswith("armor_b.pac"):
                return self._parsed_mesh(path, "armor_b", [(20.0, 0.0, 0.0), (21.0, 0.0, 0.0), (20.0, 1.0, 0.0)])
            return self._parsed_mesh(path, "armor_a", [(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)])

        with patch("cdmw.core.appearance_composite.parse_mesh", side_effect=fake_parse_mesh):
            result = build_appearance_composite_model(
                plan,
                selected_component_indexes=(0, 1),
                model_overrides=(
                    AppearanceCompositeModelOverride(
                        component_index=1,
                        model_entries=(entries[3],),
                    ),
                ),
                path_index=path_index,
                basename_index=basename_index,
            )

        self.assertIsNotNone(result.preview_model)
        self.assertIn("character/model/armor_b.pac", parsed_paths)
        self.assertNotIn("character/model/armor_a.pac", parsed_paths)
        self.assertTrue(any("What-if model override" in mesh.preview_role and "armor_b.pac" in mesh.preview_role for mesh in result.preview_model.meshes))
        self.assertTrue(any("What-if model override" in warning for warning in result.warnings))

    def test_single_pac_swap_package_maps_donor_model_sidecar_and_textures_without_app_patch(self):
        target_model_path = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0100.pac"
        target_sidecar_path = "character/modelproperty/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0100.pac_xml"
        donor_model_path = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0200.pac"
        donor_sidecar_path = "character/modelproperty/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0200.pac_xml"
        donor_texture_path = "character/texture/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0200.dds"
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/cd_phm_macduff/cd_phm_macduff_00000.app_xml",
                    '<Appearance><Armor><Prefab Name="cd_phm_00_ub_00_0100" Preview="true" /></Armor></Appearance>',
                ),
                (target_model_path, b"TARGETPAC"),
                (target_sidecar_path, b"<Material />"),
                (donor_model_path, b"DONORPAC"),
                (donor_sidecar_path, f'<Material><Texture Path="{donor_texture_path}" /></Material>'),
                (donor_texture_path, b"DDS DONOR"),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[3],
            entries,
            target_component_index=0,
            path_index=path_index,
            basename_index=basename_index,
        )
        package_plan = build_appearance_single_pac_swap_package_plan(plan)

        self.assertEqual((), plan.blocking_reasons)
        self.assertEqual(target_model_path, plan.target_model_entry.path)
        self.assertEqual(donor_sidecar_path, plan.donor_sidecar_entry.path)
        self.assertEqual((donor_texture_path,), tuple(entry.path for entry in plan.donor_texture_entries))
        self.assertEqual((), package_plan.blocking_reasons)
        self.assertEqual([(target_model_path, b"DONORPAC")], [(request.entry.path, request.payload_data) for request in package_plan.requests])
        self.assertIn((target_sidecar_path, b'<Material><Texture Path="' + donor_texture_path.encode("utf-8") + b'" /></Material>'), [
            (spec.target_path, spec.payload_data) for spec in package_plan.extra_payloads
        ])
        self.assertIn((donor_texture_path, b"DDS DONOR"), [(spec.target_path, spec.payload_data) for spec in package_plan.extra_payloads])
        written_paths = {request.entry.path for request in package_plan.requests} | {spec.target_path for spec in package_plan.extra_payloads}
        self.assertNotIn(entries[0].path, written_paths)

    def test_single_pac_swap_warns_without_donor_sidecar_but_builds_model_payload(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/a.app_xml",
                    '<Appearance><Armor><Prefab Name="target_ub" Preview="true" /></Armor></Appearance>',
                ),
                ("character/model/1_pc/1_phm/armor/9_upperbody/target_ub.pac", b"TARGETPAC"),
                ("character/model/1_pc/1_phm/armor/9_upperbody/donor_ub.pac", b"DONORPAC"),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[2],
            entries,
            target_component_index=0,
            path_index=path_index,
            basename_index=basename_index,
        )
        package_plan = build_appearance_single_pac_swap_package_plan(plan)

        self.assertEqual((), plan.blocking_reasons)
        self.assertTrue(any("Donor material sidecar was not resolved" in warning for warning in plan.warnings))
        self.assertEqual(1, len(package_plan.requests))
        self.assertEqual((), package_plan.extra_payloads)

    def test_single_pac_swap_reports_missing_donor_textures(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/a.app_xml",
                    '<Appearance><Armor><Prefab Name="target_ub" Preview="true" /></Armor></Appearance>',
                ),
                ("character/model/1_pc/1_phm/armor/9_upperbody/target_ub.pac", b"TARGETPAC"),
                ("character/modelproperty/1_pc/1_phm/armor/9_upperbody/target_ub.pac_xml", b"<Material />"),
                ("character/model/1_pc/1_phm/armor/9_upperbody/donor_ub.pac", b"DONORPAC"),
                (
                    "character/modelproperty/1_pc/1_phm/armor/9_upperbody/donor_ub.pac_xml",
                    '<Material><Texture Path="character/texture/missing_donor_ub.dds" /></Material>',
                ),
            )
        )
        path_index, basename_index = self._indexes(entries)

        plan = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[3],
            entries,
            target_component_index=0,
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertEqual(("character/texture/missing_donor_ub.dds",), plan.donor_texture_missing_paths)
        self.assertTrue(any("donor sidecar DDS" in warning for warning in plan.warnings))

    def test_single_pac_swap_blocks_slot_and_body_family_mismatches_until_experimental(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/a.app_xml",
                    '<Appearance><Armor><Prefab Name="target_ub" Preview="true" /></Armor></Appearance>',
                ),
                ("character/model/1_pc/1_phm/armor/9_upperbody/target_ub.pac", b"TARGETPAC"),
                ("character/model/1_pc/2_phw/armor/10_lowerbody/donor_lb.pac", b"DONORPAC"),
            )
        )
        path_index, basename_index = self._indexes(entries)

        blocked = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[2],
            entries,
            target_component_index=0,
            path_index=path_index,
            basename_index=basename_index,
        )
        experimental = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[2],
            entries,
            target_component_index=0,
            allow_experimental_mismatch=True,
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertTrue(any("Armor slot mismatch" in reason for reason in blocked.blocking_reasons))
        self.assertTrue(any("Body family mismatch" in reason for reason in blocked.blocking_reasons))
        self.assertEqual((), experimental.blocking_reasons)
        self.assertTrue(any("Experimental mismatch output is enabled" in warning for warning in experimental.warnings))

    def test_single_pac_swap_requires_explicit_target_model_when_component_resolves_many(self):
        entries = self._entries(
            (
                (
                    "character/appearance/1_pc/1_phm/a.app_xml",
                    '<Appearance><Armor><Prefab Name="target_ub.pami" Preview="true" /></Armor></Appearance>',
                ),
                ("character/modelproperty/1_pc/1_phm/armor/9_upperbody/target_ub.pami", b"<Material />"),
                ("character/model/1_pc/1_phm/armor/9_upperbody/target_ub.pac", b"TARGETPAC"),
                ("character/model/1_pc/1_phm/armor/9_upperbody/target_ub.pam", b"TARGETPAM"),
                ("character/model/1_pc/1_phm/armor/9_upperbody/donor_ub.pac", b"DONORPAC"),
            )
        )
        path_index, basename_index = self._indexes(entries)

        blocked = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[4],
            entries,
            target_component_index=0,
            path_index=path_index,
            basename_index=basename_index,
        )
        chosen = build_appearance_single_pac_swap_plan(
            entries[0],
            entries[4],
            entries,
            target_component_index=0,
            target_model_entry=entries[2],
            path_index=path_index,
            basename_index=basename_index,
        )

        self.assertTrue(any("multiple model paths" in reason for reason in blocked.blocking_reasons))
        self.assertEqual((), chosen.blocking_reasons)
        self.assertEqual(entries[2], chosen.target_model_entry)


if __name__ == "__main__":
    unittest.main()
