from __future__ import annotations

import json
import struct
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

import cdmw.core.recolor_variants as recolor_variants_module
from cdmw.core.recolor_variants import (
    RecolorVariantOutputProfile,
    RecolorVariantRule,
    RecolorVariantTemplate,
    analyze_recolor_variant_package,
    build_recolor_variant_outputs,
    default_recolor_variant_templates,
    export_recolor_variant_templates,
    import_recolor_variant_templates,
    preview_recolor_variant_target_image,
    recolor_export_options_for_manager,
    save_recolor_variant_templates,
)
from cdmw.models import RunCancelled


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


def _fake_preview_png(path: Path, color: tuple[int, int, int, int] = (128, 128, 128, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), color).save(path)
    return path


class RecolorVariantTests(unittest.TestCase):
    def test_analysis_honors_pre_cancelled_request(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = _write_mod(Path(temp_dir))
            with self.assertRaises(RunCancelled):
                analyze_recolor_variant_package(source, stop_event=stop_event)

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

    def test_selected_texture_preview_renders_before_after_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            analysis = analyze_recolor_variant_package(source)
            target = next(target for target in analysis.targets if target.game_path == "character/texture/blade_basecolor.dds")
            original_source_bytes = (source / "files" / "character" / "texture" / "blade_basecolor.dds").read_bytes()

            def _fake_display_preview(_texconv_path: object, _dds_path: Path, **_kwargs: object) -> Path:
                return _fake_preview_png(root / "display_preview.png")

            with mock.patch("cdmw.core.recolor_variants.ensure_dds_display_preview_png", side_effect=_fake_display_preview):
                result = preview_recolor_variant_target_image(
                    analysis,
                    default_recolor_variant_templates()[0],
                    target.target_id,
                )

            self.assertEqual(target.target_id, result.target_id)
            self.assertTrue(result.source_png.is_file())
            self.assertTrue(result.preview_png.is_file())
            self.assertEqual(original_source_bytes, (source / "files" / "character" / "texture" / "blade_basecolor.dds").read_bytes())

    def test_selected_texture_preview_refuses_locked_technical_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = _write_mod(Path(temp_dir))
            analysis = analyze_recolor_variant_package(source)
            target = next(target for target in analysis.targets if target.game_path == "character/texture/blade_n.dds")

            with self.assertRaises(ValueError):
                preview_recolor_variant_target_image(
                    analysis,
                    default_recolor_variant_templates()[0],
                    target.target_id,
                )

    def test_build_writes_multiple_outputs_and_never_overwrites_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            source_base = source / "files" / "character" / "texture" / "blade_basecolor.dds"
            original_source_bytes = source_base.read_bytes()
            analysis = analyze_recolor_variant_package(source)
            profiles = (
                RecolorVariantOutputProfile(
                    profile_id="dmm",
                    label="Definitive Mod Manager",
                    enabled=True,
                    export_options=recolor_export_options_for_manager("dmm"),
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
            dmm_root = next(path for path in result.output_roots if not path.name.endswith("_jmm"))
            jmm_root = next(path for path in result.output_roots if path.name.endswith("_jmm"))
            self.assertEqual(b"RECOLORED", (dmm_root / "character" / "texture" / "blade_basecolor.dds").read_bytes())
            self.assertNotEqual(b"RECOLORED", (dmm_root / "character" / "texture" / "blade_n.dds").read_bytes())
            self.assertTrue((jmm_root / "mod.json").exists())
            self.assertFalse((jmm_root / "manifest.json").exists())

    def test_overwrite_failure_and_cancellation_preserve_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            analysis = analyze_recolor_variant_package(source)
            profiles = (
                RecolorVariantOutputProfile(
                    profile_id="dmm",
                    label="Definitive Mod Manager",
                    enabled=True,
                    export_options=recolor_export_options_for_manager("dmm"),
                ),
            )

            def _fake_recolor(dds_path: Path, *_args: object, **_kwargs: object) -> None:
                dds_path.write_bytes(b"RECOLORED")

            with mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=_fake_recolor):
                initial = build_recolor_variant_outputs(
                    analysis,
                    default_recolor_variant_templates()[0],
                    root / "out",
                    profiles,
                    overwrite_existing=True,
                )
            output_root = initial.output_roots[0]
            marker = output_root / "keep.txt"
            marker.write_text("previous", encoding="utf-8")

            with (
                mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=_fake_recolor),
                mock.patch("cdmw.core.recolor_variants.write_mod_package_manifest", side_effect=RuntimeError("write failed")),
                self.assertRaisesRegex(RuntimeError, "write failed"),
            ):
                build_recolor_variant_outputs(
                    analysis,
                    default_recolor_variant_templates()[0],
                    root / "out",
                    profiles,
                    overwrite_existing=True,
                )
            self.assertEqual("previous", marker.read_text(encoding="utf-8"))

            stop_event = threading.Event()
            real_manifest_writer = recolor_variants_module.write_mod_package_manifest

            def _write_then_cancel(*args: object, **kwargs: object) -> Path:
                result = real_manifest_writer(*args, **kwargs)  # type: ignore[arg-type]
                stop_event.set()
                return result

            with (
                mock.patch("cdmw.core.recolor_variants._apply_texture_rule_to_dds", side_effect=_fake_recolor),
                mock.patch("cdmw.core.recolor_variants.write_mod_package_manifest", side_effect=_write_then_cancel),
                self.assertRaises(RunCancelled),
            ):
                build_recolor_variant_outputs(
                    analysis,
                    default_recolor_variant_templates()[0],
                    root / "out",
                    profiles,
                    overwrite_existing=True,
                    stop_event=stop_event,
                )

            self.assertEqual("previous", marker.read_text(encoding="utf-8"))
            self.assertFalse(any(output_root.parent.glob("cdmw-recolor-stage-*")))
            self.assertFalse(any(output_root.parent.glob("cdmw-recolor-backup-*")))

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
                            profile_id="dmm",
                            label="Definitive Mod Manager",
                            enabled=True,
                            export_options=recolor_export_options_for_manager("dmm"),
                        ),
                    ),
                    overwrite_existing=True,
                )

            self.assertTrue(result.succeeded, result.errors)
            self.assertEqual(b"RECOLORED", (result.output_roots[0] / "character" / "texture" / "blade_basecolor.dds").read_bytes())
            with zipfile.ZipFile(zip_path) as archive:
                self.assertNotEqual(b"RECOLORED", archive.read("files/character/texture/blade_basecolor.dds"))

    def test_zip_source_preview_extracts_to_temp_without_mutating_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = _write_mod(root)
            zip_path = root / "source.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(source).as_posix())
            with zipfile.ZipFile(zip_path) as archive:
                original_zip_bytes = archive.read("files/character/texture/blade_basecolor.dds")

            analysis = analyze_recolor_variant_package(zip_path)
            target = next(target for target in analysis.targets if target.game_path == "character/texture/blade_basecolor.dds")

            def _fake_display_preview(_texconv_path: object, _dds_path: Path, **_kwargs: object) -> Path:
                return _fake_preview_png(root / "zip_display_preview.png")

            with mock.patch("cdmw.core.recolor_variants.ensure_dds_display_preview_png", side_effect=_fake_display_preview):
                result = preview_recolor_variant_target_image(
                    analysis,
                    default_recolor_variant_templates()[0],
                    target.target_id,
                )

            self.assertTrue(result.source_dds_path.is_file())
            self.assertNotEqual(zip_path, result.source_dds_path)
            with zipfile.ZipFile(zip_path) as archive:
                self.assertEqual(original_zip_bytes, archive.read("files/character/texture/blade_basecolor.dds"))

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
                    profile_id="dmm",
                    label="Definitive Mod Manager",
                    enabled=True,
                    export_options=recolor_export_options_for_manager("dmm"),
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
        main_source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/tool_tabs.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/texture_workflow/editor_bridge.py").read_text(encoding="utf-8")
        )
        tab_source = Path("cdmw/ui/recolor_variants_tab.py").read_text(encoding="utf-8")
        editor_source = (
            Path("cdmw/ui/texture_editor_tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/texture_workflow/editor_tool_coordination.py").read_text(encoding="utf-8")
        )

        self.assertIn("from cdmw.ui.recolor_variants_tab import RecolorVariantsTab", main_source)
        self.assertIn("self.recolor_variants_tab = self._add_lazy_shell_tool(", main_source)
        self.assertIn(
            'self.texture_tabs, "Recolor Variants", "recolor_variants", self._create_recolor_variants_tab',
            main_source,
        )
        self.assertIn('self._register_detachable_tool("recolor_variants"', main_source)
        self.assertIn("open_recolor_target_in_editor_requested.connect", main_source)
        self.assertIn("def _open_recolor_variant_target_in_texture_editor", main_source)
        self.assertIn('self.targets_tree.setObjectName("RecolorVariantTargetsTree")', tab_source)
        self.assertIn("controls_layout.addWidget(self.summary_label)", tab_source)
        self.assertNotIn("main_layout.addWidget(self.summary_label)", tab_source)
        self.assertIn('self.preview_summary_label.setObjectName("RecolorVariantPreviewSummary")', tab_source)
        self.assertIn('self.outputs_tree.setObjectName("RecolorVariantOutputsTree")', tab_source)
        self.assertIn('self.preview_source_image_label.setObjectName("RecolorVariantBeforePreview")', tab_source)
        self.assertIn('self.preview_result_image_label.setObjectName("RecolorVariantAfterPreview")', tab_source)
        self.assertIn('QPushButton("Refresh Preview")', tab_source)
        self.assertIn('QPushButton("Open In Editor")', tab_source)
        self.assertIn("def _build_results_section", tab_source)
        self.assertIn("self.splitter.setStretchFactor(2, 1)", tab_source)
        self.assertIn("class _RecolorPreviewLabel", tab_source)
        self.assertIn("QColorDialog.getColor", tab_source)
        self.assertIn('button.setObjectName("RecolorVariantColorPickerButton")', tab_source)
        self.assertIn("self.tolerance_slider = QSlider(Qt.Horizontal)", tab_source)
        self.assertIn("self.strength_slider = QSlider(Qt.Horizontal)", tab_source)
        self.assertIn('CollapsibleSection("Advanced Template Filters", expanded=False)', tab_source)
        self.assertIn('CollapsibleSection("Manager outputs", expanded=False)', tab_source)
        self.assertIn('section.header_widget.setVisible(False)', tab_source)
        self.assertIn('QLabel("Source Mod")', tab_source)
        self.assertIn('QPushButton("Save Templates")', tab_source)
        self.assertIn('QPushButton("Review Matches")', tab_source)
        self.assertNotIn('controls_layout.addStretch(1)', tab_source)
        self.assertIn("preview_recolor_variant_target_image", tab_source)
        self.assertIn("open_recolor_target_in_editor_requested", tab_source)
        self.assertIn("Source Mod will not be modified in place", tab_source)
        self.assertIn('QPushButton("Import JSON")', tab_source)
        self.assertIn('QPushButton("Export JSON")', tab_source)
        self.assertIn('self.overwrite_checkbox.setObjectName("RecolorVariantNoInPlaceOverwrite")', tab_source)
        self.assertIn("def set_recolor_tool_settings", editor_source)


if __name__ == "__main__":
    unittest.main()
