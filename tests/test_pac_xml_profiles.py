import tempfile
import unittest
from pathlib import Path

from cdmw.modding.pac_xml_profiles import (
    build_pac_xml_profile_match_report,
    build_pac_xml_corpus_index,
    classify_pac_xml_profile,
    classify_pac_xml_shader_family,
    is_stock_runtime_texture_path,
    load_or_build_pac_xml_corpus_index,
    pac_xml_corpus_signature,
    parse_pac_xml_profile,
    select_best_pac_xml_template,
    validate_pac_xml_sidecar_transition,
    validate_pac_xml_texture_contract,
)


class PacXmlProfileTests(unittest.TestCase):
    def test_classifier_covers_core_asset_families_without_path_collisions(self) -> None:
        cases = [
            (
                "character/modelproperty/1_pc/1_phm/weapon/12_pike/cd_phm_12_pike_0034_sub01.pac_xml",
                '<SkinnedMeshProperty _pbdSimulationMaterialName="WeaponSpline"/>',
                "weapon",
                "pike",
                ("spline",),
            ),
            (
                "character/modelproperty/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0039_player.pac_xml",
                '<Material _materialName="SkinnedMeshHair_Ver2"/>',
                "hair",
                "",
                ("hair_physics",),
            ),
            (
                "character/modelproperty/1_pc/10_pgw/head/head/cd_pgw_00_head_00_0001.pac_xml",
                '<Material _materialName="SkinnedMeshSkin_Ver2"/>',
                "head",
                "",
                ("skin",),
            ),
            (
                "character/modelproperty/1_pc/14_ptm/armor/13_hel/cd_ptm_01_hel_00_0354_sub01.pac_xml",
                "",
                "armor",
                "helmet",
                (),
            ),
            (
                "character/modelproperty/1_pc/14_ptm/armor/9_upperbody/cd_ptm_00_ub_0001.pac_xml",
                "",
                "armor",
                "body",
                (),
            ),
            (
                "character/modelproperty/1_pc/14_ptm/armor/19_cloak/cd_ptm_01_cloak_0001.pac_xml",
                '<Material _materialName="SkinnedMeshCloth_Ver2"/>',
                "armor",
                "cloak",
                ("cloth",),
            ),
            (
                "character/modelproperty/1_pc/1_phm/weapon/3_shield/cd_phm_03_shield_0001.pac_xml",
                '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>',
                "weapon",
                "shield",
                (),
            ),
            (
                "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_axe_0001.pac_xml",
                "",
                "weapon",
                "axe",
                (),
            ),
            (
                "character/modelproperty/1_pc/1_phm/weapon/0_tools/cd_phm_00_musket_0001.pac_xml",
                "",
                "weapon",
                "musket",
                (),
            ),
            (
                "character/modelproperty/1_pc/10_pgw/head/head_sub/cd_pgw_00_eye_0001.pac_xml",
                '<Material _materialName="SkinnedMeshEye_Ver2"/>',
                "head",
                "",
                ("eye",),
            ),
            (
                "character/modelproperty/t0108_flag/cd_t0108_flag_0001.pac_xml",
                '<SkinnedMeshProperty _pbdSimulationMaterialName="Flag"/>',
                "prop",
                "static",
                ("cloth",),
            ),
            (
                "character/modelproperty/monster/wolf/cd_mon_wolf_0001.pac_xml",
                '<Material _materialName="SkinnedMeshFur_Ver2"/>',
                "monster",
                "organic",
                ("fur",),
            ),
            (
                "character/modelproperty/monster/mecha_golem/cd_mon_mecha_golem_0001.pac_xml",
                '<Material _materialName="SkinnedMeshEmissive_Ver2"/>',
                "monster",
                "mechanical",
                (),
            ),
            (
                "character/modelproperty/riding/horse/cd_mount_horse_0001.pac_xml",
                '<Material _materialName="SkinnedMeshFur_Ver2"/>',
                "riding",
                "animal",
                ("fur",),
            ),
            (
                "character/modelproperty/riding/wagon/cd_vehicle_wagon_0001.pac_xml",
                "",
                "riding",
                "vehicle",
                (),
            ),
        ]

        for path, xml, family, slot, profiles in cases:
            with self.subTest(path=path):
                profile = classify_pac_xml_profile(path, xml)
                self.assertEqual(family, profile.family)
                self.assertEqual(slot, profile.slot)
                for expected_profile in profiles:
                    self.assertIn(expected_profile, profile.profiles)

    def test_parse_pac_xml_profile_reads_wrappers_shaders_params_and_stock_refs(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_sp.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailMaskTexture" _path="cd_temp_r_m.dds"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = parse_pac_xml_profile(
            text,
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
        )

        self.assertEqual("weapon", report.profile.family)
        self.assertEqual("sword", report.profile.slot)
        self.assertEqual(("Standard_Ver2",), report.shader_families)
        self.assertEqual(1, len(report.wrappers))
        wrapper = report.wrappers[0]
        self.assertEqual("blade", wrapper.role)
        self.assertEqual("6", wrapper.render_setting_flag)
        self.assertEqual(("BitFlag32", "Texture", "Texture", "Texture"), wrapper.parameter_types)
        self.assertEqual(3, report.texture_ref_count)
        self.assertEqual(2, report.stock_texture_ref_count)
        self.assertTrue(is_stock_runtime_texture_path("character/texture/cd_temp_r_m.dds"))
        self.assertTrue(is_stock_runtime_texture_path("cd_texturelayer_003_0001_sp.dds"))

    def test_shader_family_and_texture_contract_validation(self) -> None:
        self.assertEqual("Cloth", classify_pac_xml_shader_family("SkinnedMeshTornCloth_Ver2"))
        self.assertEqual("EyeCover", classify_pac_xml_shader_family("SkinnedMeshEyeCover_Ver2"))
        text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )
        warnings = validate_pac_xml_texture_contract(text)
        self.assertEqual(1, len(warnings))
        self.assertIn("_normalTexture", warnings[0])

    def test_corpus_index_pairs_model_paths_and_counts_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            xml_path = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml"
            model_path = root / "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac"
            xml_path.parent.mkdir(parents=True)
            model_path.parent.mkdir(parents=True)
            xml_path.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blade.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            model_path.write_bytes(b"pac")

            index = build_pac_xml_corpus_index(root)
            count, newest = pac_xml_corpus_signature(root)

        self.assertEqual(1, index.xml_count)
        self.assertEqual(1, index.paired_model_count)
        self.assertEqual(
            "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
            index.profiles[0].paired_model_path,
        )
        self.assertEqual(1, index.wrapper_count)
        self.assertEqual(1, index.texture_ref_count)
        self.assertEqual(1, index.families["weapon"])
        self.assertEqual(1, index.shader_families["Standard_Ver2"])
        self.assertEqual(1, index.parameter_types["Texture"])
        self.assertEqual(1, count)
        self.assertGreater(newest, 0)

    def test_lazy_corpus_cache_rebuilds_when_signature_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "archive_extract"
            cache = Path(temp_dir) / "settings" / "pac_xml_profile_index_v1.json"
            xml_dir = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon"
            xml_dir.mkdir(parents=True)
            (xml_dir / "cd_phm_02_sword_0015.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material _materialName="SkinnedMeshStandard_Ver2">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/cached_base.dds"/></MaterialParameterTexture>'
                "</Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            first = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            second = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            self.assertEqual(1, first.xml_count)
            self.assertEqual(1, second.xml_count)
            self.assertTrue(str(cache).endswith("pac_xml_profile_index_v1.json"))
            self.assertEqual("character/texture/cached_base.dds", second.profiles[0].wrappers[0].texture_refs[0].texture_path)
            (xml_dir / "cd_phm_02_axe_0001.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="AxeHead"><Material _materialName="SkinnedMeshStandard_Ver2"/></SkinnedMeshMaterialWrapper></Root>',
                encoding="utf-8",
            )
            rebuilt = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            self.assertEqual(2, rebuilt.xml_count)

    def test_profile_match_report_scores_preserved_and_patched_parameters(self) -> None:
        original = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_sp.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )
        patched = original.replace("character/texture/original_base.dds", "character/texture/source_base.dds")

        report = build_pac_xml_profile_match_report(
            original,
            patched,
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
            changed_wrappers=1,
            generated_dds=2,
        )

        self.assertEqual("weapon", report.chosen_profile.profile.family)
        self.assertGreater(report.similarity_score, 0.95)
        self.assertEqual(4, report.preserved_params)
        self.assertEqual(1, report.patched_params)
        self.assertEqual(2, report.generated_dds)
        self.assertFalse(report.fallback_reason)
        self.assertIn("similarity=", report.summary())

    def test_template_matching_scores_family_role_shader_and_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus_xml = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_template.pac_xml"
            corpus_xml.parent.mkdir(parents=True)
            corpus_xml.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_TEMPLATE">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/template.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/template_n.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            index = build_pac_xml_corpus_index(root)
        target = parse_pac_xml_profile(
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
        )
        match = select_best_pac_xml_template(target, target.wrappers[0], "base", index)
        self.assertTrue(match.supports_slot)
        self.assertEqual("_baseColorTexture", match.template_parameter_name)
        self.assertGreaterEqual(match.score, 0.75)

    def test_template_matching_can_recover_unsafe_weapon_shader_with_standard_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus_xml = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_standard.pac_xml"
            model_path = root / "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_standard.pac"
            corpus_xml.parent.mkdir(parents=True)
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"pac")
            corpus_xml.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Guard_0015">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/template.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            index = build_pac_xml_corpus_index(root)
        target = parse_pac_xml_profile(
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Guard_0015">'
            '<Material _materialName="SkinnedMeshEmissive_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_emissiveIntensityTexture"><ResourceReferencePath_ITexture _path="character/texture/gem_emi.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
        )
        match = select_best_pac_xml_template(
            target,
            target.wrappers[0],
            "base",
            index,
            allow_shader_mismatch=True,
            preferred_shader_families=("Standard_Ver2", "Standard"),
        )
        self.assertTrue(match.supports_slot)
        self.assertEqual("SkinnedMeshStandard_Ver2", match.template_shader_name)
        self.assertEqual("Standard_Ver2", match.template_shader_family)
        self.assertEqual("character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_standard.pac", match.template_model_path)

    def test_transition_validation_protects_stock_support_and_special_params(self) -> None:
        original = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Cloak">'
            '<Material _materialName="SkinnedMeshCloth_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/cd_temp_r_m.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat _name="_clothThickness" _value="1.0"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )
        patched = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Cloak">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/new_mask_ma.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )
        warnings = validate_pac_xml_sidecar_transition(original, patched)
        self.assertTrue(any("stock runtime" in warning for warning in warnings))
        self.assertTrue(any("protected PAC XML param removed" in warning for warning in warnings))
        self.assertTrue(any("protected shader changed" in warning for warning in warnings))

    def test_runtime_xml_profile_engine_has_no_machine_local_default_paths(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        for relative in (
            "cdmw/modding/pac_xml_profiles.py",
            "cdmw/modding/material_replacer.py",
            "cdmw/core/archive_modding.py",
            "cdmw/ui/main_window.py",
        ):
            source = (source_root / relative).read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("C:" + "\\Users\\Ratrider", source)
            self.assertNotIn("C:" + "/Users/Ratrider", source)
            self.assertNotIn("Desktop\\CTF\\archive_extract", source)


if __name__ == "__main__":
    unittest.main()
