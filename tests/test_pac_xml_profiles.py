import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from cdmw.modding.pac_xml_profiles import (
    PAC_XML_PROFILE_INDEX_V1_CACHE_NAME,
    PAC_XML_PROFILE_INDEX_V2_CACHE_NAME,
    build_pac_xml_material_authority_report,
    build_pac_xml_profile_match_report,
    build_pac_xml_corpus_index,
    build_pac_xml_corpus_sqlite_cache,
    classify_pac_xml_profile,
    classify_pac_xml_shader_family,
    clear_pac_xml_profile_index_cache,
    default_pac_xml_profile_cache_path,
    hydrate_pac_xml_corpus_index,
    is_stock_runtime_texture_path,
    legacy_pac_xml_profile_cache_path,
    load_or_build_pac_xml_corpus_index,
    pac_xml_corpus_signature,
    pac_xml_parameter_for_slot,
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
            cache = Path(temp_dir) / "settings" / PAC_XML_PROFILE_INDEX_V2_CACHE_NAME
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
            self.assertTrue(str(cache).endswith(PAC_XML_PROFILE_INDEX_V2_CACHE_NAME))
            self.assertTrue(second.sqlite_backed)
            self.assertEqual([], second.profiles)
            hydrate_pac_xml_corpus_index(second)
            self.assertEqual("character/texture/cached_base.dds", second.profiles[0].wrappers[0].texture_refs[0].texture_path)
            (xml_dir / "cd_phm_02_axe_0001.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="AxeHead"><Material _materialName="SkinnedMeshStandard_Ver2"/></SkinnedMeshMaterialWrapper></Root>',
                encoding="utf-8",
            )
            rebuilt = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            self.assertEqual(2, rebuilt.xml_count)

    def test_sqlite_cache_loads_without_reparsing_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "archive_extract"
            cache = Path(temp_dir) / "settings" / PAC_XML_PROFILE_INDEX_V2_CACHE_NAME
            xml_dir = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon"
            xml_dir.mkdir(parents=True)
            (xml_dir / "cd_phm_02_sword_0015.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material _materialName="SkinnedMeshStandard_Ver2">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/cached_base.dds"/></MaterialParameterTexture>'
                "</Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            built = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            self.assertTrue(built.sqlite_backed)
            with mock.patch("cdmw.modding.pac_xml_profiles.parse_pac_xml_profile", side_effect=AssertionError("reparsed")):
                cached = load_or_build_pac_xml_corpus_index(root, cache_path=cache)
            self.assertTrue(cached.sqlite_backed)
            self.assertEqual(1, cached.xml_count)
            self.assertEqual([], cached.profiles)

    def test_sqlite_cache_corrupt_file_rebuilds_and_legacy_json_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_dir = Path(temp_dir) / "settings"
            root = Path(temp_dir) / "archive_extract"
            xml_dir = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon"
            xml_dir.mkdir(parents=True)
            (xml_dir / "cd_phm_02_sword_0015.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material _materialName="SkinnedMeshStandard_Ver2"/></SkinnedMeshMaterialWrapper></Root>',
                encoding="utf-8",
            )
            legacy = legacy_pac_xml_profile_cache_path(settings_dir)
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"schema":"poison"}', encoding="utf-8")
            cache = default_pac_xml_profile_cache_path(settings_dir)
            cache.write_text("not sqlite", encoding="utf-8")

            rebuilt = load_or_build_pac_xml_corpus_index(root, cache_path=cache)

            self.assertEqual(1, rebuilt.xml_count)
            self.assertTrue(rebuilt.sqlite_backed)
            self.assertTrue(cache.exists())
            self.assertEqual('{"schema":"poison"}', legacy.read_text(encoding="utf-8"))

    def test_clear_pac_xml_profile_index_cache_removes_v1_and_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_dir = Path(temp_dir) / "settings"
            legacy = legacy_pac_xml_profile_cache_path(settings_dir)
            current = default_pac_xml_profile_cache_path(settings_dir)
            legacy.parent.mkdir(parents=True)
            legacy.write_text("old", encoding="utf-8")
            current.write_text("new", encoding="utf-8")

            removed = clear_pac_xml_profile_index_cache(settings_dir)

            self.assertFalse(legacy.exists())
            self.assertFalse(current.exists())
            self.assertEqual({legacy, current}, set(removed))

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

    def test_sqlite_template_matching_matches_in_memory_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "archive_extract"
            cache = Path(temp_dir) / "settings" / PAC_XML_PROFILE_INDEX_V2_CACHE_NAME
            corpus_dir = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon"
            model_dir = root / "character/model/1_pc/1_phm/weapon/2_twohandweapon"
            corpus_dir.mkdir(parents=True)
            model_dir.mkdir(parents=True)
            (model_dir / "cd_phm_02_sword_template.pac").write_bytes(b"pac")
            (corpus_dir / "cd_phm_02_sword_template.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_TEMPLATE">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/template.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/template_n.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            (corpus_dir / "cd_phm_02_sword_layer.pac_xml").write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_LAYER">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0202.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            memory_index = build_pac_xml_corpus_index(root)
            sqlite_index = build_pac_xml_corpus_sqlite_cache(root, cache)
            self.assertEqual(memory_index.xml_count, sqlite_index.xml_count)
            self.assertEqual(memory_index.wrapper_count, sqlite_index.wrapper_count)
            self.assertEqual(memory_index.parameter_count, sqlite_index.parameter_count)
            self.assertEqual(memory_index.texture_ref_count, sqlite_index.texture_ref_count)
            self.assertEqual(memory_index.paired_model_count, sqlite_index.paired_model_count)
            conn = sqlite3.connect(str(cache))
            try:
                self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM wrappers").fetchone()[0])
                blob_row = conn.execute(
                    "SELECT texture_refs_blob FROM wrappers WHERE wrapper_name = ?",
                    ("CD_PHM_02_Blade_TEMPLATE",),
                ).fetchone()
                self.assertIsInstance(blob_row[0], bytes)
                self.assertGreater(len(blob_row[0]), 0)
            finally:
                conn.close()
            target = parse_pac_xml_profile(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
            )
            memory_match = select_best_pac_xml_template(target, target.wrappers[0], "base", memory_index)
            sqlite_match = select_best_pac_xml_template(target, target.wrappers[0], "base", sqlite_index)
            self.assertEqual(memory_match, sqlite_match)

    def test_template_matching_does_not_treat_grime_layer_as_direct_base(self) -> None:
        grime_only = parse_pac_xml_profile(
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0202.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
        )

        self.assertEqual("", pac_xml_parameter_for_slot(grime_only.wrappers[0], "base"))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layer_xml = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_layer.pac_xml"
            direct_xml = root / "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_direct.pac_xml"
            layer_xml.parent.mkdir(parents=True)
            layer_xml.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0202.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            direct_xml.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_TEMPLATE">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/template.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            index = build_pac_xml_corpus_index(root)

        match = select_best_pac_xml_template(grime_only, grime_only.wrappers[0], "base", index)
        self.assertTrue(match.supports_slot)
        self.assertEqual("_baseColorTexture", match.template_parameter_name)
        self.assertEqual("character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_direct.pac_xml", match.template_path)

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

    def test_material_authority_report_flags_target_influence_and_unknowns(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="6" Index="0"/>'
            '<MaterialParameterClothCategory StringItemID="_clothCategory" ItemID="9" _name="_clothCategory" _value="Silk" Index="1"/>'
            '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="2"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture StringItemID="_detailMaskTexture" ItemID="2838988925698046" _name="_detailMaskTexture" Index="3"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0202.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture StringItemID="_grimeDiffuseTextureR" ItemID="2838988925698047" _name="_grimeDiffuseTextureR" Index="4"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0203.dds"/></MaterialParameterTexture>'
            '<MaterialParameterColor StringItemID="_tintColorR" ItemID="31" _name="_tintColorR" _value="#402c1aff" Index="5"/>'
            '<MaterialParameterColor StringItemID="_dyeingColorMaskG" ItemID="32" _name="_dyeingColorMaskG" _value="#1111114c" Index="6"/>'
            '<MaterialParameterFloat StringItemID="_brightness" ItemID="33" _name="_brightness" _value="1.500000" Index="7"/>'
            '<MaterialParameterFloat StringItemID="_wetnessBoost" ItemID="34" _name="_wetnessBoost" _value="0.250000" Index="8"/>'
            '<MaterialParameterBool StringItemID="_alphaTest" ItemID="35" _name="_alphaTest" _value="1" Index="9"/>'
            '<MaterialParameterBool StringItemID="_alphaBlend" ItemID="36" _name="_alphaBlend" _value="0" Index="10"/>'
            '<MaterialParameterFloat StringItemID="_alphaCutoff" ItemID="37" _name="_alphaCutoff" _value="0.420000" Index="11"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(
            text,
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
            authority_contract="true_source_authority",
        )

        inherited_names = {parameter.parameter_name for parameter in report.inherited_influence_parameters}
        unknown_names = {parameter.parameter_name for parameter in report.unknown_material_response_parameters}
        abi_names = {parameter.parameter_name for parameter in report.runtime_abi_parameters}
        source_names = {parameter.parameter_name for parameter in report.source_authority_parameters}
        report_dict = report.to_dict()
        wrapper_row = report_dict["wrapper_order"][0]
        wetness_row = next(
            parameter
            for parameter in report_dict["unknown_material_response_parameters"]
            if parameter["parameter_name"] == "_wetnessBoost"
        )
        overlay_row = next(
            parameter
            for parameter in report_dict["source_authority_parameters"]
            if parameter["parameter_name"] == "_overlayColorTexture"
        )
        scalar_ranges = {row["parameter_name"]: row for row in report_dict["scalar_ranges"]}
        color_rows = {row["parameter_name"]: row for row in report_dict["color_parameters"]}
        alpha_controls = {row["parameter_name"]: row for row in report_dict["alpha_controls"]}
        neutralization_actions = {row["parameter_name"]: row for row in report_dict["neutralization_actions"]}
        warning_text = "\n".join(report.warnings)
        self.assertEqual("needs_review", report.status)
        self.assertEqual("Blade", wrapper_row["wrapper_name"])
        self.assertEqual("1190", wrapper_row["item_id"])
        self.assertEqual("SkinnedMeshStandard_Ver2", wrapper_row["shader_name"])
        self.assertEqual(12, wrapper_row["parameter_count"])
        self.assertEqual("34", wetness_row["item_id"])
        self.assertEqual("8", wetness_row["index"])
        self.assertEqual("0.250000", wetness_row["value"])
        self.assertEqual("3936485985222654", overlay_row["item_id"])
        self.assertEqual(1.5, scalar_ranges["_brightness"]["min"])
        self.assertEqual(1.5, scalar_ranges["_brightness"]["max"])
        self.assertEqual(0.25, scalar_ranges["_wetnessBoost"]["min"])
        self.assertEqual((64, 44, 26, 255), color_rows["_tintColorR"]["color_rgba"])
        self.assertEqual("rgba", color_rows["_tintColorR"]["color_order"])
        self.assertEqual("alpha_test", alpha_controls["_alphaTest"]["mode"])
        self.assertEqual("alpha_blend", alpha_controls["_alphaBlend"]["mode"])
        self.assertEqual("alpha_cutout", alpha_controls["_alphaCutoff"]["mode"])
        self.assertEqual(0.42, alpha_controls["_alphaCutoff"]["numeric_value"])
        self.assertIn("_detailMaskTexture", inherited_names)
        self.assertIn("_grimeDiffuseTextureR", inherited_names)
        self.assertIn("_tintColorR", inherited_names)
        self.assertIn("_dyeingColorMaskG", inherited_names)
        self.assertIn("_brightness", inherited_names)
        self.assertIn("_wetnessBoost", unknown_names)
        self.assertIn("_renderSettingFlag", abi_names)
        self.assertIn("_clothCategory", abi_names)
        self.assertIn("_overlayColorTexture", source_names)
        self.assertEqual(5, len(report.neutralization_actions))
        self.assertEqual("replace_with_source_owned_texture_or_neutral_default", neutralization_actions["_detailMaskTexture"]["action"])
        self.assertEqual("neutralize_scalar_or_color_to_source_neutral_default", neutralization_actions["_tintColorR"]["action"])
        self.assertEqual("required", neutralization_actions["_grimeDiffuseTextureR"]["action_status"])
        self.assertTrue(neutralization_actions["_dyeingColorMaskG"]["preserve_runtime_abi"])
        self.assertEqual("31", neutralization_actions["_tintColorR"]["item_id"])
        self.assertEqual("5", neutralization_actions["_tintColorR"]["index"])
        self.assertIn("must neutralize or replace target-side influence", warning_text)
        self.assertIn("shared_texturelayer", warning_text)
        self.assertIn("unknown material-response parameter Blade _wetnessBoost", warning_text)
        self.assertIn("inherited=5", report.summary())

    def test_material_authority_report_records_submesh_resource_bindings(self) -> None:
        text = (
            '<Root><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="1190">'
            '<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Guard">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshMetal_Ver2"/>'
            "</SkinnedMeshMaterialWrapper></Vector></SkinnedMeshProperty></Root>"
        )

        report = build_pac_xml_material_authority_report(
            text,
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
        )

        rows = report.to_dict()["submesh_bindings"]
        self.assertEqual(2, len(rows))
        self.assertEqual("Blade", rows[0]["wrapper_name"])
        self.assertEqual("1190", rows[0]["item_id"])
        self.assertEqual("1190", rows[0]["id_base"])
        self.assertEqual("SkinnedMeshStandard_Ver2", rows[0]["shader_name"])
        self.assertEqual(1, rows[0]["parameter_count"])
        self.assertEqual("Guard", rows[1]["wrapper_name"])
        self.assertEqual("1191", rows[1]["item_id"])
        self.assertEqual("1190", rows[1]["id_base"])
        self.assertEqual("SkinnedMeshMetal_Ver2", rows[1]["shader_name"])

    def test_material_authority_report_keeps_flow_and_wrinkle_textures_runtime_abi(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Head">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshSkinWrinkle"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_flowTexture"><ResourceReferencePath_ITexture _path="character/texture/t0208_spiderwebhard_0001_f.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/cd_phm_0264_hel_hair_00_01_01_f.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_wrinkleMaskTexture0"><ResourceReferencePath_ITexture _path="character/texture/head_wrinkle_mask.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_wrinkleColorTexture0"><ResourceReferencePath_ITexture _path="character/texture/head_wrinkle_color.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_emissiveProgressMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/head_emi.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_maskTexture"><TextureRef Name="_value" _path="character/texture/head_m.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_maskTexture"></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(text, "character/modelproperty/head.pac_xml")

        runtime = {parameter.parameter_name: parameter for parameter in report.runtime_abi_parameters}
        source = {
            (parameter.parameter_name, parameter.texture_path): parameter
            for parameter in report.source_authority_parameters
        }
        unknown = {parameter.parameter_name: parameter for parameter in report.unknown_material_response_parameters}
        self.assertEqual("flow", runtime["_flowTexture"].role)
        self.assertEqual("normal", source[("_normalTexture", "character/texture/cd_phm_0264_hel_hair_00_01_01_f.dds")].role)
        self.assertEqual("wrinkle_mask", runtime["_wrinkleMaskTexture0"].role)
        self.assertEqual("wrinkle_color", runtime["_wrinkleColorTexture0"].role)
        self.assertEqual("emissive", source[("_emissiveProgressMaskTexture", "character/texture/head_emi.dds")].role)
        self.assertEqual("material_mask", source[("_maskTexture", "character/texture/head_m.dds")].role)
        self.assertEqual("material_mask", source[("_maskTexture", "")].role)
        self.assertEqual({}, unknown)

    def test_material_authority_texture_ref_child_records_texture_path(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Head">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture ItemID="13821" _name="_maskTexture" Index="4">'
            '<TextureRef Name="_value" _path="character/texture/cd_t0195_barnia_windchime_rope_0001_m.dds"/>'
            "</MaterialParameterTexture>"
            '<MaterialParameterTexture _name="_maskTexture"></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(text, "character/modelproperty/head.pac_xml")

        source = {
            (parameter.parameter_name, parameter.texture_path): parameter
            for parameter in report.source_authority_parameters
        }
        unknown = {parameter.parameter_name: parameter for parameter in report.unknown_material_response_parameters}
        self.assertEqual(
            "character/texture/cd_t0195_barnia_windchime_rope_0001_m.dds",
            source[("_maskTexture", "character/texture/cd_t0195_barnia_windchime_rope_0001_m.dds")].texture_path,
        )
        self.assertEqual("material_mask", source[("_maskTexture", "character/texture/cd_t0195_barnia_windchime_rope_0001_m.dds")].role)
        self.assertEqual("material_mask", source[("_maskTexture", "")].role)
        self.assertEqual({}, unknown)

    def test_material_authority_report_classifies_eye_texture_and_property_authority(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper ItemID="884" _subMeshName="Eye">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshEye"><Vector Name="_parameters">'
            '<MaterialParameterTexture ItemID="4501334226108414" _name="_alphaTexture" Index="3">'
            '<ResourceReferencePath_ITexture _path="character/texture/head_alpha.dds"/></MaterialParameterTexture>'
            '<MaterialParameterByte4 ItemID="2730506844110846" _name="_pupilProperty" _value="4201215" Index="5"/>'
            '<MaterialParameterTexture ItemID="4238362294616062" _name="_pupilTexture" Index="6">'
            '<ResourceReferencePath_ITexture _path="character/texture/head_pupil.dds"/></MaterialParameterTexture>'
            '<MaterialParameterByte4 ItemID="1656570634043390" _name="_irisProperty" _value="118" Index="7"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(text, "character/modelproperty/head_eye.pac_xml")

        source = {parameter.parameter_name: parameter for parameter in report.source_authority_parameters}
        self.assertEqual((), report.unknown_material_response_parameters)
        self.assertEqual("opacity", source["_alphaTexture"].role)
        self.assertEqual("pupil", source["_pupilTexture"].role)
        self.assertEqual("known_material_response", source["_pupilProperty"].reason)
        self.assertEqual("known_material_response", source["_irisProperty"].reason)

    def test_material_authority_report_classifies_shader_effect_and_translucent_buckets(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper ItemID="11" _subMeshName="Chain">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshChain"><Vector Name="_parameters">'
            '<MaterialParameterFloat ItemID="2456033947549694" _name="_cableUVScaleX" _value="0.344000" Index="5"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="12" _subMeshName="Hair">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshHair"><Vector Name="_parameters">'
            '<MaterialParameterFloat _name="_frequencyU" _value="2.000000" Index="7"/>'
            '<MaterialParameterFloat _name="_speedU" _value="1.000000" Index="8"/>'
            '<MaterialParameterFloat _name="_speedV" _value="1.000000" Index="9"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="13" _subMeshName="Ghost">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshGhost"><Vector Name="_parameters">'
            '<MaterialParameterFloat2 _name="_ghostNoiseUVSpeed" _value="0.300000 0.300000" Index="0"/>'
            '<MaterialParameterFloat _name="_ghostOpacity" _value="0.410000" Index="1"/>'
            '<MaterialParameterColor _name="_ghostColor" _value="#0d9ed2ff" Index="2"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="14" _subMeshName="Effect">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_maskTexture" Index="0">'
            '<ResourceReferencePath_ITexture _path="effect/texture/pafx_ice_skinneddecal_snow_area_001a.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_lavaTex" Index="1">'
            '<ResourceReferencePath_ITexture _path="texture/lava_d.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_lavaNormalTex" Index="2">'
            '<ResourceReferencePath_ITexture _path="texture/lava_rock_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat2 _name="_diffuseUVTiling" _value="1.500000 1.500000" Index="3"/>'
            '<MaterialParameterTexture _name="_noiseTex" Index="4">'
            '<ResourceReferencePath_ITexture _path="effect/texture/uvnoise_01b_ksh.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_parallaxTex" Index="5">'
            '<ResourceReferencePath_ITexture _path="character/texture/pa_terrain_pebbles_0004.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_parallaxNormalTex" Index="6">'
            '<ResourceReferencePath_ITexture _path="character/texture/pa_terrain_pebbles_0004_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat _name="_growthRatio" Index="7"/>'
            '<MaterialParameterFloat _name="_terrainBlendRatio" _value="0.780000" Index="8"/>'
            '<MaterialParameterTexture _name="_transientAgingColorTexture" Index="9">'
            '<ResourceReferencePath_ITexture _path="character/texture/head_aging.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat _name="_vertexOffsetScale" _value="7.000000" Index="10"/>'
            '<MaterialParameterFloat _name="_fresnelMask" _value="5.520000" Index="11"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="15" _subMeshName="Translucent">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshTranslucent"><Vector Name="_parameters">'
            '<MaterialParameterFloat _name="_thickness" _value="0.130000" Index="1"/>'
            '<MaterialParameterFloat _name="_extinctionCoefficient" _value="0.750000" Index="2"/>'
            '<MaterialParameterFloat _name="_velvetness" _value="0.800000" Index="3"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(text, "character/modelproperty/effect_buckets.pac_xml")

        runtime = {parameter.parameter_name for parameter in report.runtime_abi_parameters}
        inherited = {parameter.parameter_name: parameter for parameter in report.inherited_influence_parameters}
        source = {parameter.parameter_name: parameter for parameter in report.source_authority_parameters}
        self.assertEqual((), report.unknown_material_response_parameters)
        self.assertTrue({"_cableUVScaleX", "_frequencyU", "_speedU", "_speedV"} <= runtime)
        self.assertEqual("target_ghost_shader", inherited["_ghostOpacity"].reason)
        self.assertEqual("target_mask_effect", inherited["_maskTexture"].reason)
        self.assertEqual("target_lava_shader", inherited["_lavaNormalTex"].reason)
        self.assertEqual("target_uv_transform", inherited["_diffuseUVTiling"].reason)
        self.assertEqual("target_procedural_noise", inherited["_noiseTex"].reason)
        self.assertEqual("target_parallax_shader", inherited["_parallaxNormalTex"].reason)
        self.assertEqual("target_growth_shader", inherited["_growthRatio"].reason)
        self.assertEqual("target_terrain_blend", inherited["_terrainBlendRatio"].reason)
        self.assertEqual("target_skin_aging", inherited["_transientAgingColorTexture"].reason)
        self.assertEqual("target_vertex_offset", inherited["_vertexOffsetScale"].reason)
        self.assertEqual("target_fresnel_mask", inherited["_fresnelMask"].reason)
        self.assertEqual("known_material_response", source["_thickness"].reason)
        self.assertEqual("known_material_response", source["_extinctionCoefficient"].reason)
        self.assertEqual("known_material_response", source["_velvetness"].reason)

    def test_material_authority_report_keeps_torn_cloth_parameters_runtime_abi(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Cape">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshTornCloth_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture ItemID="414702243938302" _name="_tornPatternTexture" Index="40">'
            '<ResourceReferencePath_ITexture _path="character/texture/cape_torn.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat ItemID="1345291851661310" _name="_tornCrossGrainPower" _value="0.4" Index="41"/>'
            '<MaterialParameterFloat ItemID="2139607801004030" _name="_tornLengthGrainUVScale" _value="0.1" Index="42"/>'
            '<MaterialParameterFloat ItemID="958757867618302" _name="_tornCrossGrainUVScale" _value="0.06" Index="43"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(text, "character/modelproperty/cape.pac_xml")

        runtime_names = {parameter.parameter_name for parameter in report.runtime_abi_parameters}
        self.assertIn("_tornPatternTexture", runtime_names)
        self.assertIn("_tornCrossGrainPower", runtime_names)
        self.assertIn("_tornLengthGrainUVScale", runtime_names)
        self.assertIn("_tornCrossGrainUVScale", runtime_names)
        self.assertEqual((), report.unknown_material_response_parameters)

    def test_material_authority_report_runtime_xml_preserve_warns_without_true_source_action(self) -> None:
        text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0203.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        report = build_pac_xml_material_authority_report(
            text,
            "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
            authority_contract="runtime_xml_preserve",
        )

        warning_text = "\n".join(report.warnings)
        self.assertEqual("runtime_xml_preserve", report.authority_contract)
        self.assertEqual(1, len(report.inherited_influence_parameters))
        self.assertEqual(1, len(report.neutralization_actions))
        self.assertEqual("reported_only", report.neutralization_actions[0].action_status)
        self.assertFalse(report.neutralization_actions[0].required)
        self.assertIn("Runtime XML preserve warning", warning_text)
        self.assertIn("keeps target-side influence", warning_text)
        self.assertIn("keeps target tint/dye/detail/grime/shared texture-layer response", report.neutralization_policy)

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

    def test_transition_validation_warns_on_runtime_abi_drift(self) -> None:
        original = (
            '<Root><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="1190">'
            '<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="Blade">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="11" _name="_overlayColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Guard">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_normalTexture" ItemID="12" _name="_normalTexture" Index="1">'
            '<ResourceReferencePath_ITexture _path="character/texture/guard_n.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            "</Vector></SkinnedMeshProperty></Root>"
        )
        texture_only = original.replace("blade_base.dds", "blade_replacement_base.dds")
        drifted = (
            '<Root><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="777">'
            '<SkinnedMeshMaterialWrapper ItemID="1191" _subMeshName="Guard">'
            '<Material _materialName="SkinnedMeshMetal_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_normalTexture" ItemID="120" _name="_normalTexture" Index="9">'
            '<ResourceReferencePath_ITexture _path="character/texture/guard_n.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            '<SkinnedMeshMaterialWrapper ItemID="9999" _subMeshName="Blade">'
            '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="11" _name="_overlayColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture _path="character/texture/blade_base.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
            "</Vector></SkinnedMeshProperty></Root>"
        )

        texture_warnings = validate_pac_xml_sidecar_transition(
            original,
            texture_only,
            sidecar_path="character/modelproperty/sword.pac_xml",
            allow_stock_mask_override=True,
        )
        drift_warnings = validate_pac_xml_sidecar_transition(
            original,
            drifted,
            sidecar_path="character/modelproperty/sword.pac_xml",
            allow_stock_mask_override=True,
        )
        drift_text = "\n".join(drift_warnings)

        self.assertFalse(any("PAC XML runtime ABI changed" in warning for warning in texture_warnings))
        self.assertIn("wrapper order/name/shader differs", drift_text)
        self.assertIn("wrapper ItemID sequence differs", drift_text)
        self.assertIn("_subMeshResources binding order/name/shader differs", drift_text)
        self.assertIn("_subMeshResources ItemID/IdBase sequence differs", drift_text)
        self.assertIn("material parameter names/types/ItemIDs/indexes differ", drift_text)

    def test_runtime_xml_profile_engine_has_no_machine_local_default_paths(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        for relative in (
            "cdmw/modding/pac_xml_profiles.py",
            "cdmw/modding/material_replacer.py",
            "cdmw/core/archive_modding.py",
            "cdmw/ui/shell/app_window.py",
        ):
            source = (source_root / relative).read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("C:" + "\\Users\\Ratrider", source)
            self.assertNotIn("C:" + "/Users/Ratrider", source)
            self.assertNotIn("Desktop\\CTF\\archive_extract", source)


if __name__ == "__main__":
    unittest.main()
