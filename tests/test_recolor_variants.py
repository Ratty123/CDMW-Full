from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from cdmw.core.recolor_variants import (
    RecolorVariantOutputProfile,
    RecolorVariantRule,
    RecolorVariantTemplate,
    analyze_recolor_variant_package,
    build_recolor_variant_outputs,
    default_recolor_variant_templates,
    export_recolor_variant_templates,
    import_recolor_variant_templates,
    recolor_export_options_for_manager,
    save_recolor_variant_templates,
)


def _dds(width: int = 4, height: int = 4, *, mips: int = 3, fourcc: bytes = b"DXT1") -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x0002100F)
    struct.pack_into("<I", header, 8, height)
    struct.pack_into("<I", header, 12, width)
    struct.pack_into("<I", header, 24, mips)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x4)
    header[80:84] = fourcc
    return b"DDS " + bytes(header) + b"\x00" * 64


def _sidecar() -> str:
    return """
<SkinnedMeshMaterialWrapper _subMeshName="Blade">
  <Material _materialName="SkinnedMeshStandard_Ver2">
    <Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_basecolor.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_n.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" _name="_colorBlendingMaskTexture" Index="2">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_ma.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterColor StringItemID="_tintColorR" _name="_tintColorR" Value="#112233ff"/>
    </Vector>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _write_mod(root: Path) -> Path:
    mod_root = root / "SourceMod"
    files = mod_root / "files"
    sidecar = files / "character" / "modelproperty" / "weapon.pac_xml"
    model = files / "character" / "model" / "weapon.pac"
    texture_dir = files / "character" / "texture"
    texture_dir.mkdir(parents=True)
    sidecar.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    (mod_root / "manifest.json").write_text(
        json.dumps({"title": "Source Mod", "version": "1.0", "author": "Tester"}),
        encoding="utf-8",
    )
    (mod_root / "modinfo.json").write_text(json.dumps({"name": "Source Mod"}), encoding="utf-8")
    model.write_bytes(b"PAC")
    sidecar.write_text(_sidecar(), encoding="utf-8")
    (texture_dir / "blade_basecolor.dds").write_bytes(_dds(fourcc=b"DXT1"))
    (texture_dir / "blade_n.dds").write_bytes(_dds(fourcc=b"BC5U"))
    (texture_dir / "blade_ma.dds").write_bytes(_dds(fourcc=b"DXT1"))
    return mod_root


class RecolorVariantTests(unittest.TestCase):
    def test_analysis_detects_safe_basecolor_and_locks_technical_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = _write_mod(Path(temp_dir))

            analysis = analyze_recolor_variant_package(source)

            by_path = {target.game_path: target for target in analysis.targets if target.target_kind == "texture_slot"}
            self.assertTrue(by_path["character/texture/blade_basecolor.dds"].editable)
            self.assertFalse(by_path["character/texture/blade_n.dds"].editable)
            self.assertIn("not a visible color slot", by_path["character/texture/blade_n.dds"].locked_reason)
            self.assertFalse(by_path["character/texture/blade_ma.dds"].editable)
            self.assertEqual("BC1_UNORM", by_path["character/texture/blade_basecolor.dds"].texconv_format)
            self.assertTrue(any(target.target_kind == "material_color" and target.parameter_name == "_tintColorR" for target in analysis.targets))

    def test_build_writes_multiple_outputs_and_never_overwrites_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            source_base = source / "files" / "character" / "texture" / "blade_basecolor.dds"
            original_source_bytes = source_base.read_bytes()
            analysis = analyze_recolor_variant_package(source)
            profiles = (
                RecolorVariantOutputProfile(
                    profile_id="universal",
                    label="Universal",
                    enabled=True,
                    export_options=recolor_export_options_for_manager("universal"),
                ),
                RecolorVariantOutputProfile(
                    profile_id="jmm",
                    label="JMM JSON",
                    enabled=True,
                    package_title_suffix="JMM",
                    export_options=recolor_export_options_for_manager("jmm"),
                ),
            )

            def _fake_recolor(dds_path: Path, *_args: object, **_kwargs: object) -> None:
                dds_path.write_bytes(b"RECOLORED")

            with mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=_fake_recolor):
                result = build_recolor_variant_outputs(
                    analysis,
                    default_recolor_variant_templates()[0],
                    root / "out",
                    profiles,
                    overwrite_existing=True,
                )

            self.assertTrue(result.succeeded)
            self.assertEqual(original_source_bytes, source_base.read_bytes())
            self.assertEqual(2, len(result.output_roots))
            universal_root = next(path for path in result.output_roots if not path.name.endswith("_jmm"))
            jmm_root = next(path for path in result.output_roots if path.name.endswith("_jmm"))
            self.assertEqual(b"RECOLORED", (universal_root / "character" / "texture" / "blade_basecolor.dds").read_bytes())
            self.assertNotEqual(b"RECOLORED", (universal_root / "character" / "texture" / "blade_n.dds").read_bytes())
            self.assertTrue((jmm_root / "mod.json").exists())
            self.assertFalse((jmm_root / "manifest.json").exists())

    def test_zip_source_analysis_and_build_preserve_payload_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            zip_path = root / "source.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(source).as_posix())

            analysis = analyze_recolor_variant_package(zip_path)
            base_target = next(target for target in analysis.targets if target.game_path == "character/texture/blade_basecolor.dds")
            self.assertTrue(base_target.editable)
            self.assertEqual(4, base_target.width)
            self.assertEqual(4, base_target.height)
            self.assertEqual(3, base_target.mip_count)

            def _fake_recolor(dds_path: Path, *_args: object, **_kwargs: object) -> None:
                dds_path.write_bytes(b"RECOLORED")

            with mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=_fake_recolor):
                result = build_recolor_variant_outputs(
                    analysis,
                    default_recolor_variant_templates()[0],
                    root / "out",
                    (
                        RecolorVariantOutputProfile(
                            profile_id="universal",
                            label="Universal",
                            enabled=True,
                            export_options=recolor_export_options_for_manager("universal"),
                        ),
                    ),
                    overwrite_existing=True,
                )

            self.assertTrue(result.succeeded, result.errors)
            self.assertEqual(b"RECOLORED", (result.output_roots[0] / "character" / "texture" / "blade_basecolor.dds").read_bytes())
            with zipfile.ZipFile(zip_path) as archive:
                self.assertNotEqual(b"RECOLORED", archive.read("files/character/texture/blade_basecolor.dds"))

    def test_material_color_template_updates_sidecar_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            analysis = analyze_recolor_variant_package(source)
            template = RecolorVariantTemplate(
                template_id="material",
                name="Material Color",
                rules=(
                    RecolorVariantRule(
                        target_kind="material_color",
                        parameter_name="_tintColorR",
                        operation="set_color",
                        target_color="#aabbcc",
                    ),
                ),
            )
            profiles = (
                RecolorVariantOutputProfile(
                    profile_id="universal",
                    label="Universal",
                    enabled=True,
                    export_options=recolor_export_options_for_manager("universal"),
                ),
            )

            result = build_recolor_variant_outputs(
                analysis,
                template,
                root / "out",
                profiles,
                overwrite_existing=True,
            )

            self.assertTrue(result.succeeded, result.errors)
            output_sidecar = result.output_roots[0] / "character" / "modelproperty" / "weapon.pac_xml"
            self.assertIn('Value="#aabbccff"', output_sidecar.read_text(encoding="utf-8"))

    def test_global_templates_import_export_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = RecolorVariantTemplate(
                template_id="shared",
                name="Shared Template",
                rules=(RecolorVariantRule(target_color="#123456"),),
            )
            save_recolor_variant_templates(root, (template,))
            exported = export_recolor_variant_templates(root, root / "exported.json")

            imported_root = root / "other_workspace"
            imported = import_recolor_variant_templates(imported_root, exported, merge=False)

            self.assertEqual(("shared",), tuple(item.template_id for item in imported))
            self.assertTrue((imported_root / "recolor_variant_templates.json").exists())

    def test_template_import_honors_false_boolean_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "templates.json"
            source.write_text(
                json.dumps(
                    {
                        "templates": [
                            {
                                "template_id": "bools",
                                "name": "Bool Test",
                                "rules": [
                                    {
                                        "enabled": "false",
                                        "preserve_luminance": "false",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            imported = import_recolor_variant_templates(root / "workspace", source, merge=False)

            self.assertFalse(imported[0].rules[0].enabled)
            self.assertFalse(imported[0].rules[0].preserve_luminance)

    def test_recolor_variants_ui_is_registered(self) -> None:
        main_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        tab_source = Path("cdmw/ui/recolor_variants_tab.py").read_text(encoding="utf-8")

        self.assertIn("from cdmw.ui.recolor_variants_tab import RecolorVariantsTab", main_source)
        self.assertIn('self.texture_tabs.addTab(self.recolor_variants_tab, "Recolor Variants")', main_source)
        self.assertIn('self._register_detachable_tool("recolor_variants"', main_source)
        self.assertIn('self.targets_tree.setObjectName("RecolorVariantTargetsTree")', tab_source)
        self.assertIn('self.preview_summary_label.setObjectName("RecolorVariantPreviewSummary")', tab_source)
        self.assertIn('self.outputs_tree.setObjectName("RecolorVariantOutputsTree")', tab_source)
        self.assertIn("Source mod will not be modified in place", tab_source)
        self.assertIn('QPushButton("Import JSON")', tab_source)
        self.assertIn('QPushButton("Export JSON")', tab_source)
        self.assertIn('self.overwrite_checkbox.setObjectName("RecolorVariantNoInPlaceOverwrite")', tab_source)


if __name__ == "__main__":
    unittest.main()
