from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt

from cdmw.core.material_sidecar_editor import (
    apply_material_sidecar_edits,
    detect_material_sidecar_related_files,
    detect_material_sidecar_preview_model_candidates,
    discover_material_sidecar_preview_overrides,
    discover_material_sidecar_preview_overrides_for_edits,
    discover_material_sidecar_values,
    export_material_sidecar_mod_package,
)
from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.upscale_profiles import parse_material_sidecar_profile, parse_texture_sidecar_bindings
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ModelPreviewRenderSettings,
    ModPackageInfo,
    RunCancelled,
)
from cdmw.ui.archive_browser import material_sidecar_editor_dialog
from cdmw.ui.archive_browser.material_sidecar_editor_helpers import (
    material_sidecar_action_button_labels,
    material_sidecar_edit_failed_dialog_title,
    material_sidecar_editor_intro_text,
    material_sidecar_editor_window_title,
    material_sidecar_empty_values_dialog_text,
    material_sidecar_export_complete_dialog_text,
    material_sidecar_export_complete_status,
    material_sidecar_export_task_status,
    material_sidecar_export_target_title,
    material_sidecar_initial_preview_status_text,
    material_sidecar_kind_supports_live_preview,
    material_sidecar_live_preview_kinds,
    material_sidecar_live_preview_scheduled_status,
    material_sidecar_live_preview_start_failed_status,
    material_sidecar_live_preview_starting_status,
    material_sidecar_live_preview_queued_status,
    material_sidecar_live_preview_waiting_status,
    material_sidecar_lookup_pending_status,
    material_sidecar_no_changes_dialog_text,
    material_sidecar_background_task_busy_status,
    material_sidecar_building_preview_status,
    material_sidecar_building_model_log,
    material_sidecar_built_package_summary,
    material_sidecar_cached_geometry_log,
    material_sidecar_cached_geometry_note,
    material_sidecar_content_splitter_sizes,
    material_sidecar_dialog_size,
    material_sidecar_manifest_update_summary,
    material_sidecar_native_error_status,
    material_sidecar_native_loaded_status,
    material_sidecar_native_preview_exited_status,
    material_sidecar_native_preview_process_error_status,
    material_sidecar_native_preview_start_failed_status,
    material_sidecar_native_preview_stderr_status,
    material_sidecar_no_model_preview_status,
    material_sidecar_no_preview_model_status,
    material_sidecar_package_validation_failed_status,
    material_sidecar_preview_blocked_status,
    material_sidecar_preview_base_result_state,
    material_sidecar_preview_color_tooltip,
    material_sidecar_preview_control_labels,
    material_sidecar_preview_generation_state,
    material_sidecar_initial_lookup_delay_ms,
    material_sidecar_live_preview_interval_ms,
    material_sidecar_preview_host_minimum_size,
    material_sidecar_preview_lookup_pending_status,
    material_sidecar_preview_model_status,
    material_sidecar_preview_model_entry_state,
    material_sidecar_preview_package_cleanup_delay_ms,
    material_sidecar_preview_payload_status,
    material_sidecar_preview_process_kill_delay_ms,
    material_sidecar_preview_process_state,
    material_sidecar_preview_settings_tooltip_text,
    material_sidecar_skeleton_overlay_label_text,
    material_sidecar_skeleton_overlay_queued_status,
    material_sidecar_skeleton_overlay_status_text,
    material_sidecar_skeleton_overlay_tooltip_text,
    material_sidecar_preview_status_poll_interval_ms,
    material_sidecar_preview_task_status,
    material_sidecar_preview_unexpected_entry_status,
    material_sidecar_preview_unexpected_payload_status,
    material_sidecar_prepare_failed_message,
    material_sidecar_preview_warning_text,
    material_sidecar_read_failed_status,
    material_sidecar_reloading_native_preview_status,
    material_sidecar_reused_package_summary,
    material_sidecar_row_kind_by_id,
    material_sidecar_selected_color_swatch_stylesheet,
    material_sidecar_selected_color_tooltip_text,
    material_sidecar_selected_detail_text,
    material_sidecar_selected_value_live_refresh_interval_ms,
    material_sidecar_selected_value_label_text,
    material_sidecar_selected_value_placeholder_text,
    material_sidecar_selected_value_sync_interval_ms,
    material_sidecar_selected_value_sync_state,
    material_sidecar_starting_native_preview_status,
    material_sidecar_texture_edit_refresh_status,
    material_sidecar_tree_column_widths,
    material_sidecar_tree_headers,
    material_sidecar_unexpected_export_payload_status,
    material_sidecar_value_tree_item,
    material_sidecar_value_edit_tooltip_text,
)


def entry(path: str, root: Path) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=root / "package" / "pad00000_meta.pamt",
        paz_file=root / "package" / "pad00000.paz",
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class MaterialSidecarEditorTests(unittest.TestCase):
    def test_discovers_material_values_from_wrapped_multi_root_fragment(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper _subMeshName="cloak">
          <RepresentColor x="1" y="0.5" z="0.25" />
          <Material>
            <MaterialParameterColor _name="_tintColor" x="0.8" y="0.7" z="0.6" />
            <MaterialParameterFloat _name="_brightness" Value="1.2" />
            <MaterialParameterTexture _name="_overlayColorTexture">
              <ResourceReferencePath_ITexture _path="character/texture/cd_phm_00_cloak_00_0340.dds" />
            </MaterialParameterTexture>
          </Material>
        </SkinnedMeshMaterialWrapper>
        <SkinnedMeshMaterialWrapper _subMeshName="trim">
          <MaterialParameterFloat _name="_uvScale" Value="2" />
        </SkinnedMeshMaterialWrapper>
        """

        rows = discover_material_sidecar_values(text)
        names = {(row.kind, row.group_label, row.parameter_name, row.value) for row in rows}

        self.assertIn(("color", "cloak", "RepresentColor", "1, 0.5, 0.25"), names)
        self.assertIn(("color", "cloak", "_tintColor", "0.8, 0.7, 0.6"), names)
        self.assertIn(("float", "cloak", "_brightness", "1.2"), names)
        self.assertIn(("float", "trim", "_uvScale", "2"), names)
        self.assertIn(
            (
                "texture",
                "cloak",
                "_overlayColorTexture",
                "character/texture/cd_phm_00_cloak_00_0340.dds",
            ),
            names,
        )

    def test_applies_color_float_and_texture_edits_without_touching_unrelated_values(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper _subMeshName="cloak">
          <MaterialParameterColor _name="_tintColor" x="0.8" y="0.7" z="0.6" />
          <MaterialParameterFloat _name="_brightness" Value="1.2" />
          <MaterialParameterFloat _name="_unrelated" Value="9" />
          <MaterialParameterTexture _name="_overlayColorTexture">
            <ResourceReferencePath_ITexture _path="old.dds" />
          </MaterialParameterTexture>
        </SkinnedMeshMaterialWrapper>
        """
        rows = {row.parameter_name: row for row in discover_material_sidecar_values(text)}
        result = apply_material_sidecar_edits(
            text,
            {
                rows["_tintColor"].row_id: "#000000",
                rows["_brightness"].row_id: "0.75",
                rows["_overlayColorTexture"].row_id: "new/path.dds",
            },
        )

        self.assertIn('_name="_tintColor" x="0" y="0" z="0"', result.text)
        self.assertIn('_name="_brightness" Value="0.75"', result.text)
        self.assertIn('_name="_unrelated" Value="9"', result.text)
        self.assertIn('_path="new/path.dds"', result.text)
        self.assertEqual(3, len(result.changed_rows))

    def test_discovers_and_applies_hex_rgba_material_color_values(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper _subMeshName="cloak">
          <MaterialParameterColor _name="_tintColorR" _value="#4d1708ff" />
          <MaterialParameterColor _name="_dyeingColorMaskG" _value="#c3b3af4c" />
        </SkinnedMeshMaterialWrapper>
        """
        rows = {row.parameter_name: row for row in discover_material_sidecar_values(text)}

        self.assertEqual("#4d1708ff", rows["_tintColorR"].value)
        result = apply_material_sidecar_edits(text, {rows["_tintColorR"].row_id: "#050505"})

        self.assertIn('_name="_tintColorR" _value="#050505ff"', result.text)
        self.assertIn('_name="_dyeingColorMaskG" _value="#c3b3af4c"', result.text)

    def test_detects_same_stem_op_and_explicit_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/cd_phm_00_cloak_00_0340.pac_xml", root)
            mesh = entry("character/model/cd_phm_00_cloak_00_0340.pac", root)
            base = entry("character/texture/cd_phm_00_cloak_00_0340.dds", root)
            op = entry("character/texture/cd_phm_00_cloak_00_0340_op.dds", root)
            explicit = entry("character/texture/explicit_override.dds", root)
            basename_index = {
                mesh.basename.lower(): [mesh],
                base.basename.lower(): [base],
                op.basename.lower(): [op],
                explicit.basename.lower(): [explicit],
            }
            references = (
                ArchiveModelTextureReference(
                    reference_name="explicit_override.dds",
                    resolved_archive_path=explicit.path,
                    resolved_entry=explicit,
                ),
            )

            related = detect_material_sidecar_related_files(
                sidecar,
                references=references,
                archive_entries_by_basename=basename_index,
            )
            by_path = {item.entry.path: item for item in related}

            self.assertEqual("explicit", by_path[explicit.path].confidence)
            self.assertIn(mesh.path, by_path)
            self.assertIn(base.path, by_path)
            self.assertIn(op.path, by_path)

    def test_detects_same_stem_pac_preview_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/cd_phm_00_cloak_00_0340.pac_xml", root)
            mesh = entry("character/modelproperty/cd_phm_00_cloak_00_0340.pac", root)
            candidates = detect_material_sidecar_preview_model_candidates(
                sidecar,
                archive_entries_by_basename={mesh.basename.lower(): [mesh]},
            )

            self.assertEqual(mesh.path, candidates[0].entry.path)
            self.assertEqual("same-stem", candidates[0].confidence)

    def test_detects_op_sidecar_preview_model_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/cd_phm_00_cloak_00_0340_op.pac_xml", root)
            op_mesh = entry("character/modelproperty/cd_phm_00_cloak_00_0340_op.pac", root)
            base_mesh = entry("character/modelproperty/cd_phm_00_cloak_00_0340.pac", root)
            candidates = detect_material_sidecar_preview_model_candidates(
                sidecar,
                archive_entries_by_basename={
                    op_mesh.basename.lower(): [op_mesh],
                    base_mesh.basename.lower(): [base_mesh],
                },
            )

            self.assertEqual(op_mesh.path, candidates[0].entry.path)
            self.assertIn(base_mesh.path, {candidate.entry.path for candidate in candidates})

    def test_detects_pami_explicit_preview_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/example.pami", root)
            mesh = entry("character/model/static/example.pam", root)
            text = '<StaticMesh Path="character/model/static/example.pam" />'
            candidates = detect_material_sidecar_preview_model_candidates(
                sidecar,
                sidecar_text=text,
                archive_entries_by_normalized_path={mesh.path.lower(): [mesh]},
            )

            self.assertEqual(mesh.path, candidates[0].entry.path)
            self.assertEqual("explicit", candidates[0].confidence)

    def test_discovers_preview_overrides_for_tint_brightness_and_uv(self) -> None:
        text = """
        <Material PrimitiveName="cloak">
          <MaterialParameterColor _name="_tintColor" _value="#204060ff" />
          <MaterialParameterFloat _name="_brightness" _value="1.4" />
          <MaterialParameterFloat _name="_uvScale" _value="2.5" />
          <MaterialParameterTexture _name="_baseColorTexture">
            <ResourceReferencePath_ITexture _path="character/texture/example.dds" />
          </MaterialParameterTexture>
        </Material>
        """
        overrides = discover_material_sidecar_preview_overrides(text)
        bindings = parse_texture_sidecar_bindings(text, sidecar_path="character/modelproperty/example.pami")

        self.assertEqual("cloak", overrides[0].group_label)
        self.assertAlmostEqual(0x20 / 255.0, overrides[0].tint_color[0])
        self.assertEqual(1.4, overrides[0].brightness)
        self.assertEqual(2.5, overrides[0].uv_scale)
        self.assertAlmostEqual(0x20 / 255.0, bindings[0].tint_color[0])
        self.assertEqual(1.4, bindings[0].brightness)
        self.assertEqual(2.5, bindings[0].uv_scale)

    def test_discovers_preview_overrides_for_cloak_dye_channels(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper _subMeshName="cloak">
          <MaterialParameterColor _name="_tintColorR" _value="#050505ff" />
          <MaterialParameterColor _name="_dyeingColorMaskG" _value="#1111114c" />
          <MaterialParameterColor _name="_dyeingDetailLayerColorMaskR" _value="#0a0a0aff" />
          <MaterialParameterTexture _name="_baseColorTexture">
            <ResourceReferencePath_ITexture _path="character/texture/example.dds" />
          </MaterialParameterTexture>
        </SkinnedMeshMaterialWrapper>
        """
        overrides = discover_material_sidecar_preview_overrides(text)
        bindings = parse_texture_sidecar_bindings(text, sidecar_path="character/modelproperty/example.pac_xml")

        self.assertEqual("cloak", overrides[0].group_label)
        self.assertLess(overrides[0].tint_color[0], 0.06)
        self.assertIn("dye", overrides[0].reason.lower())
        self.assertLess(bindings[0].tint_color[0], 0.06)

    def test_material_profile_preserves_pac_xml_shader_parameters(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper ItemID="1192" _subMeshName="blade">
          <Material Name="_resourceMaterial" _materialName="SkinnedMeshEmissive_Ver2">
            <Vector Name="_parameters">
              <MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="6" Index="0"/>
              <MaterialParameterTexture StringItemID="_normalTexture" ItemID="6" _name="_normalTexture" Index="1">
                <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_n.dds"/>
              </MaterialParameterTexture>
              <MaterialParameterTexture StringItemID="_emissiveIntensityTexture" ItemID="1638159983050750" _name="_emissiveIntensityTexture" Index="2">
                <ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_emi.dds"/>
              </MaterialParameterTexture>
              <MaterialParameterColor StringItemID="_emissiveColor" _name="_emissiveColor" _value="#05ff9fff" Index="3"/>
              <MaterialParameterFloat StringItemID="_emissiveIntensity" _name="_emissiveIntensity" _value="1.25" Index="4"/>
              <MaterialParameterBitFlag32 StringItemID="_colorBlendingFlag" _name="_colorBlendingFlag" _value="4095" Index="5"/>
            </Vector>
          </Material>
        </SkinnedMeshMaterialWrapper>
        """
        profile = parse_material_sidecar_profile(text, sidecar_path="character/modelproperty/example.pac_xml")

        self.assertEqual("pac_xml", profile.sidecar_kind)
        self.assertEqual("character/model/example.pac", profile.linked_mesh_path)
        self.assertEqual(("SkinnedMeshEmissive_Ver2",), profile.shader_families)
        self.assertEqual(1, len(profile.materials))
        material = profile.materials[0]
        self.assertEqual("blade", material.part_name)
        self.assertTrue(material.is_emissive)
        self.assertEqual("6", material.parameter_value("_renderSettingFlag"))
        self.assertEqual("4095", material.parameter_value("_colorBlendingFlag"))
        self.assertEqual(("character/texture/blade_n.dds", "character/texture/blade_emi.dds"), tuple(parameter.texture_path for parameter in material.texture_parameters))
        self.assertEqual("_emissiveColor", material.color_parameters[0].parameter_name)
        self.assertAlmostEqual(1.25, material.float_parameters[0].numeric_value)

    def test_material_profile_reads_material_definition_technique_and_parameters(self) -> None:
        text = """
        <Technique Name="Standard"/>
        <Parameter Name="_rgbTexture" Type="Texture" sRGB="False" DefaultValue="Texture/NoneTexture0x7f0000.dds"/>
        <Parameter Name="_colorTextureG" Type="Texture" sRGB="True" DefaultValue="Texture/NoneTexture0x00000000.dds"/>
        <Parameter Name="_heightIntensityG" DefaultValue="0.75" MinValue="0.0" MaxValue="1.0"/>
        <Parameter Name="_tintColorG" DefaultValue="0x80ff40ff" Type="Color"/>
        <Parameter Name="_materialFlags" Type="BitFlag32">
          <Element Name="UseMultiTextured" BitFlagIndex="0" DefaultValue="True"/>
        </Parameter>
        """
        profile = parse_material_sidecar_profile(text, sidecar_path="material/dist/abyssmultitextured3.material")

        self.assertEqual("material", profile.sidecar_kind)
        self.assertEqual(("Standard",), profile.shader_families)
        self.assertEqual(1, len(profile.materials))
        material = profile.materials[0]
        self.assertEqual("abyssmultitextured3", material.material_name)
        self.assertEqual(2, len(material.texture_parameters))
        self.assertEqual({"_rgbTexture", "_colorTextureG"}, {parameter.parameter_name for parameter in material.texture_parameters})
        self.assertEqual("_heightIntensityG", material.float_parameters[0].parameter_name)
        self.assertAlmostEqual(0.75, material.float_parameters[0].numeric_value)
        self.assertEqual("_tintColorG", material.color_parameters[0].parameter_name)
        self.assertEqual("_materialFlags", material.flag_parameters[0].parameter_name)

    def test_material_profile_preserves_static_material_parameter_variants(self) -> None:
        text = """
        <StaticMesh Path="object/building/example.pam"/>
        <Material PrimitiveName="Wall">
          <Common MaterialName="MultiTextured"/>
          <Parameters>
            <MaterialParameterUint Name="_materialInfo" Value="13"/>
            <MaterialParameterInt Name="_placementId" Value="91"/>
            <MaterialParameterClothCategory Name="_clothCategory" Value="Velvet"/>
            <MaterialParameterFloat3 Name="_windDirection" Value="1.0 0.0 0.5"/>
            <MaterialParameterHalf2 Name="_layerOffset" Value="0.25 0.75"/>
          </Parameters>
        </Material>
        """
        profile = parse_material_sidecar_profile(text, sidecar_path="object/building/example.pami")

        self.assertEqual("pami", profile.sidecar_kind)
        self.assertEqual(1, len(profile.materials))
        material = profile.materials[0]
        flag_names = {parameter.parameter_name for parameter in material.flag_parameters}
        float_names = {parameter.parameter_name for parameter in material.float_parameters}
        self.assertIn("_materialInfo", flag_names)
        self.assertIn("_placementId", flag_names)
        self.assertIn("_clothCategory", flag_names)
        self.assertIn("_windDirection", float_names)
        self.assertIn("_layerOffset", float_names)
        self.assertEqual("13", material.parameter_value("_materialInfo"))

    def test_material_profile_reads_technique_definition_parameters(self) -> None:
        text = """
        <Technique Name="CharacterCustomRender" Abstract="True"/>
        <Technique Name="SkinnedMeshStandard" InputLayout="CharacterVertex"/>
        <Parameter Name="_baseColorTexture" Type="Texture" sRGB="True" DefaultValue="Texture/NoneTexture0x00000000.dds"/>
        <Parameter Name="_normalTexture" Type="Texture" sRGB="False" DefaultValue="Texture/NoneTexture0xff7f7f00.dds"/>
        <Parameter Name="_screenSpaceDisplacementScale" DefaultValue="0.0" MinValue="0.0" MaxValue="1.0"/>
        """
        profile = parse_material_sidecar_profile(text, sidecar_path="technique/character.technique")

        self.assertEqual("technique", profile.sidecar_kind)
        self.assertEqual(("SkinnedMeshStandard",), profile.shader_families)
        self.assertEqual(1, len(profile.materials))
        material = profile.materials[0]
        self.assertEqual(2, len(material.texture_parameters))
        self.assertEqual("_screenSpaceDisplacementScale", material.float_parameters[0].parameter_name)

    def test_preview_overrides_for_edits_ignore_unedited_dark_sidecar_colors(self) -> None:
        text = """
        <SkinnedMeshMaterialWrapper _subMeshName="cloak">
          <MaterialParameterColor _name="_tintColorR" _value="#050505ff" />
          <MaterialParameterColor _name="_tintColorG" _value="#050505ff" />
          <MaterialParameterColor _name="_tintColorB" _value="#050505ff" />
          <MaterialParameterColor _name="_dyeingColorMaskG" _value="#1111114c" />
        </SkinnedMeshMaterialWrapper>
        """
        rows = {row.parameter_name: row for row in discover_material_sidecar_values(text)}
        overrides = discover_material_sidecar_preview_overrides_for_edits(
            text,
            {rows["_tintColorR"].row_id: "#ff0000"},
        )

        self.assertEqual(1, len(overrides))
        self.assertEqual("cloak", overrides[0].group_label)
        self.assertAlmostEqual(1.0, overrides[0].tint_color[0])
        self.assertAlmostEqual(0.0, overrides[0].tint_color[1])
        self.assertAlmostEqual(0.0, overrides[0].tint_color[2])
        self.assertIn("edited", overrides[0].confidence)

    def test_exports_edited_sidecar_and_related_files_with_manifest_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/cd_phm_00_cloak_00_0340.pac_xml", root)
            op = entry("character/texture/cd_phm_00_cloak_00_0340_op.dds", root)
            payloads = {
                op.path: b"DDS related",
            }

            result = export_material_sidecar_mod_package(
                edited_entry=sidecar,
                edited_text="<SkinnedMeshMaterialWrapper />",
                related_entries=(op,),
                parent_root=root,
                package_info=ModPackageInfo(title="Material Edit"),
                read_entry_bytes=lambda archive_entry: payloads[archive_entry.path],
            )

            self.assertTrue((result.package_root / "character" / "modelproperty" / "cd_phm_00_cloak_00_0340.pac_xml").exists())
            self.assertTrue((result.package_root / "character" / "texture" / "cd_phm_00_cloak_00_0340_op.dds").exists())
            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            files = {item["path"]: item for item in manifest["files"]}
            self.assertIn("character/modelproperty/cd_phm_00_cloak_00_0340.pac_xml", files)
            self.assertIn("character/texture/cd_phm_00_cloak_00_0340_op.dds", files)
            self.assertIn("Edited material sidecar", files["character/modelproperty/cd_phm_00_cloak_00_0340.pac_xml"]["note"])
            self.assertTrue((result.package_root / "material_sidecar_edits.json").exists())
            self.assertTrue(all(path.is_file() and result.package_root in path.parents for path in result.written_files))
            self.assertTrue(all(path.is_file() and result.package_root in path.parents for path in result.metadata_files))

    def test_export_prefers_original_encoding_payload_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/test.pac_xml", root)
            edited_payload = b"\xff\xfe" + '<MaterialParameterFloat _name="_x" _value="2" />'.encode("utf-16-le")

            result = export_material_sidecar_mod_package(
                edited_entry=sidecar,
                edited_text="compatibility text must not be written",
                edited_payload=edited_payload,
                related_entries=(),
                parent_root=root,
                package_info=ModPackageInfo(title="Encoded Material Edit"),
                read_entry_bytes=lambda _entry: b"",
            )

            exported = result.package_root / "character" / "modelproperty" / "test.pac_xml"
            self.assertEqual(edited_payload, exported.read_bytes())

    def test_cancelled_export_preserves_existing_package_and_cleans_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "Material Edit"
            package_root.mkdir()
            (package_root / "old.txt").write_text("old package", encoding="utf-8")
            package_zip = package_root.with_suffix(".zip")
            package_zip.write_bytes(b"old zip")
            sidecar = entry("character/modelproperty/test.pac_xml", root)
            related = entry("character/texture/test.dds", root)
            stop_event = threading.Event()

            def cancel_after_read(_entry: ArchiveEntry) -> bytes:
                stop_event.set()
                return b"new related payload"

            with self.assertRaises(RunCancelled):
                export_material_sidecar_mod_package(
                    edited_entry=sidecar,
                    edited_text="<edited />",
                    related_entries=(related,),
                    parent_root=root,
                    package_info=ModPackageInfo(title="Material Edit"),
                    read_entry_bytes=cancel_after_read,
                    stop_event=stop_event,
                )

            self.assertEqual("old package", (package_root / "old.txt").read_text(encoding="utf-8"))
            self.assertEqual(b"old zip", package_zip.read_bytes())
            self.assertFalse(any(path.name.startswith(".Material Edit.") for path in root.iterdir()))

    def test_interrupted_write_preserves_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "Material Edit"
            package_root.mkdir()
            (package_root / "old.txt").write_text("old package", encoding="utf-8")
            sidecar = entry("character/modelproperty/test.pac_xml", root)
            related = entry("character/texture/test.dds", root)

            with self.assertRaisesRegex(OSError, "read interrupted"):
                export_material_sidecar_mod_package(
                    edited_entry=sidecar,
                    edited_text="<edited />",
                    related_entries=(related,),
                    parent_root=root,
                    package_info=ModPackageInfo(title="Material Edit"),
                    read_entry_bytes=lambda _entry: (_ for _ in ()).throw(OSError("read interrupted")),
                )

            self.assertEqual("old package", (package_root / "old.txt").read_text(encoding="utf-8"))
            self.assertFalse((package_root / "character").exists())
            self.assertFalse(any(path.name.startswith(".Material Edit.") for path in root.iterdir()))

    def test_zip_publish_failure_rolls_back_package_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "Material Edit"
            package_root.mkdir()
            (package_root / "old.txt").write_text("old package", encoding="utf-8")
            package_zip = package_root.with_suffix(".zip")
            package_zip.write_bytes(b"old zip")
            sidecar = entry("character/modelproperty/test.pac_xml", root)
            real_replace = os.replace

            def fail_staged_zip(source: object, target: object) -> None:
                if Path(source).name == "package.zip" and Path(target) == package_zip:
                    raise OSError("zip publish interrupted")
                real_replace(source, target)

            with patch("cdmw.core.material_sidecar_package.os.replace", side_effect=fail_staged_zip):
                with self.assertRaisesRegex(OSError, "zip publish interrupted"):
                    export_material_sidecar_mod_package(
                        edited_entry=sidecar,
                        edited_text="<edited />",
                        related_entries=(),
                        parent_root=root,
                        package_info=ModPackageInfo(title="Material Edit"),
                        export_options=ModPackageExportOptions(create_zip=True),
                        read_entry_bytes=lambda _entry: b"",
                    )

            self.assertEqual("old package", (package_root / "old.txt").read_text(encoding="utf-8"))
            self.assertEqual(b"old zip", package_zip.read_bytes())
            self.assertFalse(any(path.name.startswith(".Material Edit.") for path in root.iterdir()))

    def test_successful_fresh_publish_removes_stale_package_files_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "Material Edit"
            package_root.mkdir()
            (package_root / "stale.txt").write_text("stale", encoding="utf-8")
            package_root.with_suffix(".zip").write_bytes(b"stale zip")
            sidecar = entry("character/modelproperty/test.pac_xml", root)

            result = export_material_sidecar_mod_package(
                edited_entry=sidecar,
                edited_text="<edited />",
                related_entries=(),
                parent_root=root,
                package_info=ModPackageInfo(title="Material Edit"),
                read_entry_bytes=lambda _entry: b"",
            )

            self.assertEqual(package_root, result.package_root)
            self.assertFalse((package_root / "stale.txt").exists())
            self.assertFalse(package_root.with_suffix(".zip").exists())
            self.assertTrue((package_root / "character" / "modelproperty" / "test.pac_xml").exists())

    def test_cancellable_zip_export_publishes_readable_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = entry("character/modelproperty/test.pac_xml", root)

            result = export_material_sidecar_mod_package(
                edited_entry=sidecar,
                edited_text="<edited />",
                related_entries=(),
                parent_root=root,
                package_info=ModPackageInfo(title="Material Edit"),
                export_options=ModPackageExportOptions(create_zip=True),
                read_entry_bytes=lambda _entry: b"",
                stop_event=threading.Event(),
            )

            with zipfile.ZipFile(result.package_root.with_suffix(".zip")) as archive:
                self.assertIn("character/modelproperty/test.pac_xml", archive.namelist())
                self.assertEqual(b"<edited />", archive.read("character/modelproperty/test.pac_xml"))


class MaterialSidecarEditorHelperTests(unittest.TestCase):
    def test_material_sidecar_editor_preview_settings_clamp_is_available(self) -> None:
        clamped = material_sidecar_editor_dialog.clamp_model_preview_render_settings(
            ModelPreviewRenderSettings()
        )

        self.assertIsInstance(clamped, ModelPreviewRenderSettings)

    def test_material_sidecar_editor_setup_presentation_text(self) -> None:
        self.assertEqual("Could not read material sidecar: boom", material_sidecar_read_failed_status("boom"))
        self.assertEqual(
            ("Material Values", "No recognized material values were found in this sidecar."),
            material_sidecar_empty_values_dialog_text(),
        )
        self.assertEqual("Edit Material Values - armor.pac_xml", material_sidecar_editor_window_title("armor.pac_xml"))
        self.assertIn("comma-separated RGB floats", material_sidecar_editor_intro_text())
        self.assertIn("approximate CDMW preview shader", material_sidecar_preview_warning_text())
        self.assertIn("Test the exported mod in game", material_sidecar_preview_warning_text())
        self.assertEqual(("Part / Material", "Kind", "Parameter", "Value", "Detail"), material_sidecar_tree_headers())
        self.assertEqual(
            "0.1, 0.2, 0.3\nPreview color: #AABBCC",
            material_sidecar_preview_color_tooltip("0.1, 0.2, 0.3", "#aabbcc"),
        )

    def test_material_sidecar_editor_layout_and_timer_state(self) -> None:
        self.assertEqual((1460, 760), material_sidecar_dialog_size())
        self.assertEqual((190, 72, 210, 520), material_sidecar_tree_column_widths())
        self.assertEqual((420, 300), material_sidecar_preview_host_minimum_size())
        self.assertEqual((850, 560), material_sidecar_content_splitter_sizes())
        self.assertEqual(700, material_sidecar_live_preview_interval_ms())
        self.assertEqual(750, material_sidecar_selected_value_live_refresh_interval_ms())
        self.assertEqual(250, material_sidecar_selected_value_sync_interval_ms())
        self.assertEqual(250, material_sidecar_preview_status_poll_interval_ms())
        self.assertEqual(750, material_sidecar_preview_process_kill_delay_ms())
        self.assertEqual(1000, material_sidecar_preview_package_cleanup_delay_ms())
        self.assertEqual(0, material_sidecar_initial_lookup_delay_ms())

    def test_material_sidecar_editor_row_state_helpers(self) -> None:
        row = SimpleNamespace(
            group_label="cloak",
            kind="color",
            parameter_name="_tintColor",
            value="1, 0, 0",
            detail="color value",
            row_id="row-1",
        )
        item = material_sidecar_value_tree_item(row)

        self.assertEqual("cloak", item.text(0))
        self.assertEqual("color", item.text(1))
        self.assertEqual("_tintColor", item.text(2))
        self.assertEqual("1, 0, 0", item.text(3))
        self.assertEqual("color value", item.text(4))
        self.assertEqual("row-1", item.data(0, Qt.UserRole))
        self.assertEqual("1, 0, 0", item.data(3, Qt.UserRole))
        self.assertFalse(bool(item.flags() & Qt.ItemIsEditable))
        self.assertEqual({"row-1": "color"}, material_sidecar_row_kind_by_id((row,)))
        self.assertEqual({"entry": None, "resolved": False}, material_sidecar_preview_model_entry_state())
        self.assertEqual({"color", "float"}, material_sidecar_live_preview_kinds())
        self.assertTrue(material_sidecar_kind_supports_live_preview("Color"))
        self.assertTrue(material_sidecar_kind_supports_live_preview(" float "))
        self.assertFalse(material_sidecar_kind_supports_live_preview("texture"))

    def test_material_sidecar_editor_control_presentation_text(self) -> None:
        self.assertEqual("Selected value", material_sidecar_selected_value_label_text())
        self.assertEqual("Select a material value row to edit it here.", material_sidecar_selected_value_placeholder_text())
        self.assertIn("#RRGGBB", material_sidecar_value_edit_tooltip_text())
        self.assertEqual("Selected color preview", material_sidecar_selected_color_tooltip_text())
        self.assertEqual("Selected color: #112233", material_sidecar_selected_color_tooltip_text("#112233"))
        self.assertEqual(
            "QFrame#SelectedMaterialValueColorSwatch {background-color: #112233;border: 1px solid #d0d7de;border-radius: 4px;}",
            material_sidecar_selected_color_swatch_stylesheet("#112233"),
        )
        self.assertEqual(
            ("Show Preview", "Refresh Preview", "Preview Settings...", "Live Color Preview"),
            material_sidecar_preview_control_labels(),
        )
        self.assertIn("global preview settings", material_sidecar_preview_settings_tooltip_text())
        self.assertEqual("Show skeleton overlay", material_sidecar_skeleton_overlay_label_text())
        self.assertIn("Off by default", material_sidecar_skeleton_overlay_tooltip_text())
        self.assertIn("will be loaded", material_sidecar_skeleton_overlay_status_text(True))
        self.assertIn("only material-relevant", material_sidecar_skeleton_overlay_status_text(False))
        self.assertIn("change queued", material_sidecar_skeleton_overlay_queued_status())
        self.assertEqual("Preview has not been built yet.", material_sidecar_initial_preview_status_text())
        self.assertEqual(
            ("Pick Color...", "Reset Selected", "Export Edited Material Mod...", "Close"),
            material_sidecar_action_button_labels(),
        )
        self.assertEqual(
            "Selected: cloak | _tintColor | color value",
            material_sidecar_selected_detail_text("cloak", "_tintColor", "color value"),
        )

    def test_material_sidecar_editor_status_and_export_text(self) -> None:
        self.assertEqual("Preview model lookup will run after the editor opens.", material_sidecar_lookup_pending_status())
        self.assertEqual(
            "No associated .pac, .pam, or .pamlod model was found for this sidecar.",
            material_sidecar_no_preview_model_status(),
        )
        self.assertEqual(
            "Associated preview model: character/model/test.pac",
            material_sidecar_preview_model_status("character/model/test.pac"),
        )
        self.assertEqual("Live material preview refresh scheduled...", material_sidecar_live_preview_scheduled_status())
        self.assertEqual("Live material preview refresh starting...", material_sidecar_live_preview_starting_status())
        self.assertEqual(
            "Live material preview refresh could not start: boom",
            material_sidecar_live_preview_start_failed_status("boom"),
        )
        self.assertIn("live preview will be available", material_sidecar_live_preview_waiting_status())
        self.assertEqual("Texture path edits refresh when you click Refresh Preview.", material_sidecar_texture_edit_refresh_status())
        self.assertEqual(
            ("No Changes", "Change at least one material value before exporting."),
            material_sidecar_no_changes_dialog_text(),
        )
        self.assertEqual("Material Edit Failed", material_sidecar_edit_failed_dialog_title())
        self.assertEqual(
            "Material mod export finished with an unexpected result payload.",
            material_sidecar_unexpected_export_payload_status(),
        )
        self.assertEqual(
            ("Export Complete", "Exported edited material mod:\nC:/pkg"),
            material_sidecar_export_complete_dialog_text("C:/pkg"),
        )
        self.assertEqual("Exported edited material mod to C:/pkg.", material_sidecar_export_complete_status("C:/pkg"))
        self.assertEqual(
            "Exporting edited material mod for armor.pac_xml...",
            material_sidecar_export_task_status("armor.pac_xml"),
        )
        self.assertEqual("Export Edited Material Mod", material_sidecar_export_target_title())

    def test_material_sidecar_native_preview_status_text(self) -> None:
        self.assertEqual(
            ".NET/Vortice material preview loaded: 2 batch(es), 1,234 vertices, first frame 16.5 ms, texture failures: none.",
            material_sidecar_native_loaded_status(
                batch_count=2,
                vertex_count=1234,
                first_frame_ms=16.49,
                texture_failure_count=0,
            ),
        )
        self.assertIn(
            "texture failures: 3",
            material_sidecar_native_loaded_status(
                batch_count=1,
                vertex_count=4,
                first_frame_ms=1.0,
                texture_failure_count=3,
            ),
        )
        self.assertEqual("summary\nmessage", material_sidecar_preview_payload_status("summary", "message"))
        self.assertEqual("message", material_sidecar_preview_payload_status("", "message"))
        self.assertEqual(".NET/Vortice material preview failed.", material_sidecar_native_error_status())
        self.assertEqual("custom", material_sidecar_native_error_status("custom"))
        self.assertEqual(
            ".NET/Vortice material preview package validation failed: a; b",
            material_sidecar_package_validation_failed_status(("a", "b")),
        )
        self.assertEqual(
            "summary\nReloading .NET/Vortice material preview...",
            material_sidecar_reloading_native_preview_status("summary"),
        )
        self.assertEqual(
            ".NET/Vortice material preview could not start: boom",
            material_sidecar_native_preview_start_failed_status("boom"),
        )
        self.assertEqual(
            ".NET/Vortice material preview stderr: tail",
            material_sidecar_native_preview_stderr_status("tail"),
        )
        self.assertEqual(
            ".NET/Vortice material preview process error: bad",
            material_sidecar_native_preview_process_error_status("bad"),
        )
        self.assertEqual(".NET/Vortice material preview exited with code 2.", material_sidecar_native_preview_exited_status(2))
        self.assertEqual(
            "summary\nStarting .NET/Vortice material preview...",
            material_sidecar_starting_native_preview_status("summary"),
        )

    def test_material_sidecar_preview_lifecycle_status_text(self) -> None:
        self.assertEqual("Preview model lookup is still pending.", material_sidecar_preview_lookup_pending_status())
        self.assertEqual("Preview model lookup returned an unexpected entry.", material_sidecar_preview_unexpected_entry_status())
        self.assertEqual("Material edit cannot be previewed yet: bad", material_sidecar_preview_blocked_status("bad"))
        self.assertEqual(
            "Live material preview refresh queued; current preview build is still running.",
            material_sidecar_live_preview_queued_status(),
        )
        self.assertEqual(
            "Another background task is still running. Wait for it to finish before refreshing the material preview.",
            material_sidecar_background_task_busy_status(),
        )
        self.assertEqual(
            "Building approximate material preview with DirectXTex/native DDS support...",
            material_sidecar_building_preview_status(),
        )
        self.assertEqual(
            "Material preview finished with an unexpected result payload.",
            material_sidecar_preview_unexpected_payload_status(),
        )
        self.assertEqual("No model preview available for this material sidecar.", material_sidecar_no_model_preview_status())
        self.assertEqual("Building material preview for armor.pac_xml...", material_sidecar_preview_task_status("armor.pac_xml"))
        self.assertIn(
            "reused active Archive Browser .NET/Vortice package",
            material_sidecar_reused_package_summary(),
        )
        self.assertEqual(
            "Reusing cached material preview geometry for model.pac...",
            material_sidecar_cached_geometry_log("model.pac"),
        )
        self.assertEqual("Reused cached preview geometry for live material edit.", material_sidecar_cached_geometry_note())
        self.assertEqual(
            "Building material preview for model.pac from sidecar.pac_xml...",
            material_sidecar_building_model_log("model.pac", "sidecar.pac_xml"),
        )
        self.assertEqual(
            "No prepared model preview was produced for the material sidecar.",
            material_sidecar_prepare_failed_message(),
        )

    def test_material_sidecar_preview_summary_text(self) -> None:
        self.assertEqual(
            "\n".join(
                (
                    "Approximate sidecar preview",
                    "live color/scalar refresh",
                    "edited material colors shown as solid preview overlay",
                    "manifest updated in 12.3 ms for 2 batch(es), 1,200 vertices",
                    "note",
                )
            ),
            material_sidecar_manifest_update_summary(
                live=True,
                color_edits_active=True,
                elapsed_ms=12.34,
                batch_count=2,
                vertex_count=1200,
                notes=("note", ""),
            ),
        )

    def test_material_sidecar_preview_default_state(self) -> None:
        self.assertEqual(
            {
                "process": None,
                "status_file": None,
                "status_signature": (0, 0),
                "status_payload_text": "",
                "summary": "",
            },
            material_sidecar_preview_process_state(),
        )
        self.assertEqual({"value": 0, "queued_live": False}, material_sidecar_preview_generation_state())
        self.assertEqual({"key": "", "result": None}, material_sidecar_preview_base_result_state())
        self.assertEqual({"active": False}, material_sidecar_selected_value_sync_state())
        self.assertEqual(
            "\n".join(
                (
                    "Approximate sidecar preview",
                    "edited scalar material values applied to textured preview",
                    "package built in 4.6 ms for 3 batch(es), 456 vertices",
                    "note",
                    "warning",
                )
            ),
            material_sidecar_built_package_summary(
                live=False,
                color_edits_active=False,
                material_effects_active=True,
                elapsed_ms=4.56,
                batch_count=3,
                vertex_count=456,
                notes=("note",),
                warnings=("warning",),
            ),
        )


if __name__ == "__main__":
    unittest.main()
