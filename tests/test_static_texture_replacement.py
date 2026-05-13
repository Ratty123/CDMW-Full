from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core.archive_modding import (
    ArchivePatchRequest,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
    _build_mesh_import_supplemental_file_specs,
    _build_selected_sidecar_texture_bindings,
    export_archive_mesh_payloads_to_mod_ready_loose,
)
from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.pipeline import parse_dds
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, ModelPreviewData, ModPackageInfo
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.material_replacer import (
    ReplacementTextureSlot,
    SidecarPatchPlan,
    TextureSlotMapping,
    TextureReplacementPayload,
    TextureReplacementReport,
    _attach_source_face_counts,
    _append_texture_contract_warnings,
    _build_source_driven_sidecar_text,
    _choose_source_materials_for_targets,
    build_texture_replacement_payloads,
    build_source_material_routing_plan,
    _build_texture_payload,
    classify_texture_assignment_guidance,
    group_replacement_texture_sets,
    is_static_replacement_helper_material_name,
    is_shared_material_layer_texture,
    patch_material_sidecar_text,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import StaticSubmeshMapping, StaticTextureSlotOverride


def _entry(path: str, root: Path) -> ArchiveEntry:
    package_root = root / "0009"
    package_root.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=package_root / "package.pamt",
        paz_file=package_root / "package.paz",
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


def _write_fake_png_header(path: Path, width: int, height: int) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def _fake_dds_bytes(width: int, height: int, *, mips: int = 1, fourcc: bytes = b"DXT1") -> bytes:
    data = bytearray(128)
    data[0:4] = b"DDS "
    struct.pack_into("<I", data, 4 + 0, 124)
    struct.pack_into("<I", data, 4 + 8, height)
    struct.pack_into("<I", data, 4 + 12, width)
    struct.pack_into("<I", data, 4 + 24, mips)
    struct.pack_into("<I", data, 4 + 72, 32)
    struct.pack_into("<I", data, 4 + 76, 0x4)
    data[4 + 80 : 4 + 84] = fourcc
    return bytes(data)


class StaticTextureReplacementTests(unittest.TestCase):
    def test_loose_package_dds_without_sidecar_reference_targets_texture_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "IronMod" / "files" / "character"
            source_dir.mkdir(parents=True)
            source_dds = source_dir / "cd_test_helmet_o.dds"
            source_dds.write_bytes(_fake_dds_bytes(64, 64))
            entry = _entry("character/cd_test_helmet.pac", root)

            specs = _build_mesh_import_supplemental_file_specs(
                entry,
                [source_dds],
                (),
                archive_entries_by_normalized_path={},
                archive_entries_by_basename={},
            )

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].kind, "texture")
            self.assertEqual(specs[0].target_path, "character/texture/cd_test_helmet_o.dds")

    def test_local_source_pac_xml_prefers_selected_target_sidecar_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "IronMod" / "files" / "character"
            source_dir.mkdir(parents=True)
            source_sidecar = source_dir / "source_helmet.pac_xml"
            source_sidecar.write_text("<Root />", encoding="utf-8")
            entry = _entry("character/model/1_pc/1_phm/armor/13_hel/target_helmet.pac", root)

            specs = _build_mesh_import_supplemental_file_specs(
                entry,
                [source_sidecar],
                (),
                archive_entries_by_normalized_path={},
                archive_entries_by_basename={},
            )

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].kind, "sidecar")
            self.assertEqual(
                specs[0].target_path,
                "character/modelproperty/1_pc/1_phm/armor/13_hel/target_helmet.pac_xml",
            )

    def test_local_source_pac_xml_prefers_existing_archive_sidecar_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_sidecar = root / "source_helmet.pac_xml"
            source_sidecar.write_text("<Root />", encoding="utf-8")
            entry = _entry("character/model/armor/target_helmet.pac", root)
            sidecar_entry = _entry("character/modelproperty/armor/target_helmet.pac_xml", root)
            archive_entries_by_normalized_path = {sidecar_entry.path.lower(): (sidecar_entry,)}
            archive_entries_by_basename = {sidecar_entry.basename.lower(): (sidecar_entry,)}

            specs = _build_mesh_import_supplemental_file_specs(
                entry,
                [source_sidecar],
                (),
                archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                archive_entries_by_basename=archive_entries_by_basename,
            )

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].target_entry, sidecar_entry)
            self.assertEqual(specs[0].target_path, sidecar_entry.path)

    def test_selected_pac_xml_sidecar_bindings_accept_utf16_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar_path = root / "cd_test_helmet.pac_xml"
            sidecar_path.write_text(
                '<SkinnedMeshMaterialWrapper _subMeshName="helmet">'
                '<MaterialParameterTexture _name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/iron_red_base.dds"/>'
                "</MaterialParameterTexture>"
                "</SkinnedMeshMaterialWrapper>",
                encoding="utf-16",
            )

            bindings, sidecars, texts_by_path, texts_by_name = _build_selected_sidecar_texture_bindings([sidecar_path])

            self.assertEqual(len(bindings), 1)
            self.assertEqual(sidecars, ("cd_test_helmet.pac_xml",))
            self.assertIn("character/texture/iron_red_base.dds", texts_by_path)
            self.assertIn("iron_red_base.dds", texts_by_name)

    def test_png_to_dds_defaults_to_source_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_png = root / "replacement_Base_Color.png"
            original_dds = root / "original.dds"
            texconv = root / "texconv.exe"
            _write_fake_png_header(source_png, 4096, 4096)
            original_dds.write_bytes(_fake_dds_bytes(256, 512, mips=10))
            texconv.write_bytes(b"fake")

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("replacement", "base", source_png),
                    target_entry=object(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=TextureReplacementReport(),
                    on_log=None,
                )

            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            info = parse_dds(output_dds)
            self.assertEqual((4096, 4096), (info.width, info.height))
            self.assertEqual(13, info.mip_count)

    def test_png_to_dds_can_match_original_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_png = root / "replacement_Base_Color.png"
            original_dds = root / "original.dds"
            texconv = root / "texconv.exe"
            _write_fake_png_header(source_png, 4096, 4096)
            original_dds.write_bytes(_fake_dds_bytes(256, 512, mips=10))
            texconv.write_bytes(b"fake")
            report = TextureReplacementReport()

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("replacement", "base", source_png),
                    target_entry=object(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=report,
                    on_log=None,
                    texture_output_size_mode="original",
                )

            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            info = parse_dds(output_dds)
            self.assertEqual((256, 512), (info.width, info.height))
            self.assertEqual(10, info.mip_count)
            self.assertTrue(any("smaller than source" in warning for warning in report.warnings))

    def test_normal_png_uses_bc5_even_when_template_is_color_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_png = root / "Helmet_normal.png"
            original_dds = root / "original_color.dds"
            texconv = root / "texconv.exe"
            _write_fake_png_header(source_png, 4096, 4096)
            original_dds.write_bytes(_fake_dds_bytes(256, 256, mips=9, fourcc=b"DXT1"))
            texconv.write_bytes(b"fake")
            seen_formats: list[str] = []

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                fmt = str(command[command.index("-f") + 1])
                seen_formats.append(fmt)
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"BC5U" if fmt == "BC5_UNORM" else b"DXT1"))
                return 0, "", ""

            report = TextureReplacementReport()
            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("Helmet", "normal", source_png),
                    target_entry=object(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=report,
                    on_log=None,
                )

            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            self.assertEqual(["BC5_UNORM"], seen_formats)
            self.assertEqual("BC5_UNORM", parse_dds(output_dds).texconv_format)
            self.assertTrue(any("normal map output uses BC5_UNORM" in warning for warning in report.warnings))

    def test_direct_dds_replacement_reports_crimson_validation_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dds = root / "replacement.dds"
            original_dds = root / "original.dds"
            source_dds.write_bytes(_fake_dds_bytes(64, 64, mips=1, fourcc=b"DXT5"))
            original_dds.write_bytes(_fake_dds_bytes(64, 64, mips=1, fourcc=b"DXT5"))
            entry = _entry("character/texture/sample.dds", root)
            report = TextureReplacementReport()

            payload = _build_texture_payload(
                ReplacementTextureSlot("replacement", "base", source_dds),
                target_entry=entry,
                texconv_path=None,
                read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                original_texture_source_path=lambda _entry: original_dds,
                report=report,
                on_log=None,
            )

            self.assertEqual(source_dds.read_bytes(), payload)
            warning_text = "\n".join(report.warnings)
            self.assertIn("Crimson DDS warning", warning_text)
            self.assertIn("mip chain", warning_text)

    def test_shared_texture_layers_are_identified_as_optional(self) -> None:
        self.assertTrue(is_shared_material_layer_texture("character/texture/cd_texturelayer_003_0101.dds"))
        self.assertTrue(is_shared_material_layer_texture("character/texture/cd_temp_r_m.dds"))
        self.assertTrue(is_shared_material_layer_texture("character/texture/cd_metal_05.dds"))
        self.assertTrue(is_shared_material_layer_texture("character/texture/blackoil.dds"))
        self.assertTrue(is_shared_material_layer_texture("character/texture/blackoil_n.dds"))
        self.assertTrue(is_shared_material_layer_texture("character/texture/cd_common_default_mg.dds"))
        self.assertTrue(is_shared_material_layer_texture("texture/nonetexture0xffffffff.dds"))
        self.assertFalse(is_shared_material_layer_texture("character/texture/cd_phm_01_sword_blade_0278_o.dds"))

    def test_texture_assignment_guidance_is_conservative(self) -> None:
        direct = classify_texture_assignment_guidance(
            "_normalTexture",
            "character/texture/cd_phm_01_sword_blade_0278_n.dds",
            suggested_source=r"C:\tmp\Blade_Normal.png",
        )
        self.assertTrue(direct.checked_by_default)
        self.assertEqual(direct.confidence, "high")

        shared = classify_texture_assignment_guidance(
            "_detailTexture",
            "character/texture/cd_texturelayer_003_0101.dds",
            suggested_source=r"C:\tmp\detail.png",
        )
        self.assertFalse(shared.checked_by_default)
        self.assertTrue(shared.advanced)
        self.assertIn("shared", shared.state_label.lower())
        self.assertIn("tint", shared.reason.lower())
        self.assertIn("speckles", shared.reason.lower())

        shared_metal = classify_texture_assignment_guidance(
            "_grimeDiffuseTextureG",
            "character/texture/cd_metal_05.dds",
            suggested_source=r"C:\tmp\Blade_albedo.png",
        )
        self.assertFalse(shared_metal.checked_by_default)
        self.assertTrue(shared_metal.advanced)
        self.assertIn("shared", shared_metal.state_label.lower())
        self.assertIn("cd_metal", shared_metal.reason)

        emissive = classify_texture_assignment_guidance(
            "_emissiveIntensityTexture",
            "character/texture/cd_phm_02_blade_0014_emi.dds",
            suggested_source=r"C:\tmp\Blade_albedo.png",
        )
        self.assertFalse(emissive.checked_by_default)
        self.assertTrue(emissive.advanced)

        color_blend = classify_texture_assignment_guidance(
            "_colorBlendingMaskTexture",
            "character/texture/cd_phm_01_sword_handle_0278_ma.dds",
            suggested_source=r"C:\tmp\handle_mask.png",
        )
        self.assertFalse(color_blend.checked_by_default)
        self.assertTrue(color_blend.advanced)

        cd_material_mask = classify_texture_assignment_guidance(
            "_colorBlendingMaskTexture",
            "character/texture/cd_phm_01_sword_handle_0278_ma.dds",
            suggested_source=r"C:\tmp\handle_ma.png",
        )
        self.assertTrue(cd_material_mask.checked_by_default)
        self.assertEqual("high", cd_material_mask.confidence)

        repeated = classify_texture_assignment_guidance(
            "_baseColorTexture",
            "character/texture/cd_phm_01_sword_handle_0278_o.dds",
            suggested_source=r"C:\tmp\handle_BaseColor.png",
            repeated_suggestion_count=3,
        )
        self.assertFalse(repeated.checked_by_default)
        self.assertTrue(repeated.advanced)
        self.assertIn("repeated", repeated.state_label.lower())

    def test_gltf_metallic_roughness_is_detected_but_not_game_material_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pbr = root / "Helmet_metallicRoughness.png"
            pbr.write_bytes(b"")
            texture_sets = group_replacement_texture_sets(
                (pbr,),
                obj_mesh=ParsedMesh(
                    submeshes=[
                        SubMesh(
                            name="Helmet",
                            material="Helmet",
                            vertices=[(0.0, 0.0, 0.0)],
                            faces=[(0, 0, 0)],
                        )
                    ]
                ),
            )

            self.assertIn("helmet", texture_sets)
            self.assertIn("roughness", texture_sets["helmet"].slots)
            self.assertNotIn("material", texture_sets["helmet"].slots)

    def test_cd_material_family_roles_are_distinct(self) -> None:
        files = tuple(
            Path(name)
            for name in (
                "Helmet_o.dds",
                "Helmet_n.dds",
                "Helmet_disp.dds",
                "Helmet_ma.dds",
                "Helmet_mg.dds",
            )
        )
        texture_sets = group_replacement_texture_sets(files)

        self.assertEqual({"base", "normal", "height", "material_mask", "detail_mask"}, set(texture_sets["helmet"].slots))
        self.assertEqual(
            "material_mask",
            classify_texture_binding("_overlayColorTexture", "character/texture/helmet_ma.dds").slot_kind,
        )
        self.assertEqual(
            "detail_mask",
            classify_texture_binding("_detailMaskTexture", "character/texture/helmet_mg.dds").slot_kind,
        )

    def test_helper_material_wrappers_are_manual_texture_targets(self) -> None:
        self.assertTrue(is_static_replacement_helper_material_name("cd_phm_00_hel_0013_05_black"))
        self.assertTrue(is_static_replacement_helper_material_name("cd_phm_00_hel_0013_05_inside"))
        self.assertFalse(is_static_replacement_helper_material_name("cd_phm_00_hel_0013_05"))
        texture_sets = group_replacement_texture_sets((Path("Helmet_BaseColor.png"), Path("Helmet_Normal.png")))
        source_mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="Helmet",
                    material="Helmet",
                    vertices=[(0.0, 0.0, 0.0)],
                    faces=[(0, 0, 0)],
                )
            ]
        )
        routes = build_source_material_routing_plan(
            source_mesh,
            texture_sets,
            (
                StaticSubmeshMapping(0, "cd_phm_00_hel_0013_05_black", [0], 0),
                StaticSubmeshMapping(1, "cd_phm_00_hel_0013_05_inside", [0], 1),
                StaticSubmeshMapping(2, "cd_phm_00_hel_0013_05", [0], 2),
            ),
        )

        self.assertEqual(("Ignored", "Ignored", "Ready"), tuple(route.status for route in routes))
        self.assertTrue(all("helper material wrapper" in route.reason.lower() for route in routes[:2]))
        self.assertEqual("Helmet", routes[2].source_material_name)

    def test_mixed_original_and_added_material_blocks_auto_texture_routing(self) -> None:
        texture_sets = group_replacement_texture_sets((Path("AddedPart_BaseColor.png"),))
        source_mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="Checker",
                    material="Checker",
                    vertices=[(0.0, 0.0, 0.0)],
                    faces=[(0, 0, 0)],
                ),
                SubMesh(
                    name="chain",
                    material="AddedPart",
                    vertices=[(1.0, 0.0, 0.0)],
                    faces=[(0, 0, 0)],
                ),
            ]
        )

        routes = build_source_material_routing_plan(
            source_mesh,
            texture_sets,
            (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="SkullSlot",
                    source_submesh_indices=[0, 1],
                    target_material_slot_index=0,
                ),
            ),
        )

        self.assertEqual(1, len(routes))
        self.assertEqual("Blocked", routes[0].status)
        self.assertTrue(routes[0].blocker)
        self.assertEqual("AddedPart", routes[0].source_material_name)
        self.assertIn("same draw/material slot", routes[0].reason)

    def test_source_driven_sidecar_preserves_helper_wrappers_even_with_single_binding(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="cd_phm_00_hel_0013_05_black"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/blackoil.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/blackoil_n.dds"/></MaterialParameterTexture>'
            '</Vector></SkinnedMeshMaterialWrapper>'
            '<SkinnedMeshMaterialWrapper _subMeshName="cd_phm_00_hel_0013_05_inside"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_001_0001.dds"/></MaterialParameterTexture>'
            '</Vector></SkinnedMeshMaterialWrapper>'
            '<SkinnedMeshMaterialWrapper _subMeshName="cd_phm_00_hel_0013_05"><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
            "</Vector></SkinnedMeshMaterialWrapper></Root>"
        )

        patched_text, changed_wrappers, used_paths = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "cd_phm_00_hel_0013_05": (
                    ("_overlayColorTexture", "character/texture/generated_o.dds", "base"),
                    ("_normalTexture", "character/texture/generated_n.dds", "normal"),
                )
            },
        )

        self.assertEqual(1, changed_wrappers)
        self.assertEqual({"character/texture/generated_o.dds", "character/texture/generated_n.dds"}, used_paths)
        self.assertIn("character/texture/blackoil.dds", patched_text)
        self.assertIn("character/texture/blackoil_n.dds", patched_text)
        self.assertIn("character/texture/cd_texturelayer_001_0001.dds", patched_text)
        self.assertIn("character/texture/generated_o.dds", patched_text)
        self.assertIn("character/texture/generated_n.dds", patched_text)

    def test_texture_contract_warns_when_generated_normal_feeds_base_slot(self) -> None:
        report = TextureReplacementReport()
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name="Helmet",
                target_texture_path="(source-driven _normalTexture)",
                slot_kind="normal",
                source_material_name="UV_Samurai_Helmet",
                source_path=Path("UV_Samurai_Helmet_normal.png"),
                output_texture_path="character/texture/cd_phm_00_hel_0187_01_01_01.dds",
            )
        )
        texture_payload = TextureReplacementPayload(
            target_path="character/texture/cd_phm_00_hel_0187_01_01_01.dds",
            payload_data=b"DDS normal",
            kind="texture_generated",
            source_path=Path("UV_Samurai_Helmet_normal.png"),
        )
        sidecar_payload = TextureReplacementPayload(
            target_path="character/modelproperty/helmet.pac_xml",
            payload_data=(
                b'<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet">'
                b'<MaterialParameterTexture _name="_overlayColorTexture">'
                b'<ResourceReferencePath_ITexture _path="character/texture/cd_phm_00_hel_0187_01_01_01.dds"/>'
                b"</MaterialParameterTexture></SkinnedMeshMaterialWrapper></Root>"
            ),
            kind="sidecar_generated",
            source_path=Path("helmet.pac_xml"),
        )

        _append_texture_contract_warnings(
            texture_payloads=(texture_payload,),
            sidecar_payloads=(sidecar_payload,),
            report=report,
        )

        warning_text = "\n".join(report.warnings)
        self.assertIn("expects base", warning_text)
        self.assertIn("came from a normal source", warning_text)

    def test_manual_override_warns_for_shared_target_and_role_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            source_normal = root / "UV_Samurai_Helmet_normal.png"
            _write_fake_png_header(source_normal, 1024, 1024)
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"DXT1"))
            shared_entry = _entry("character/texture/cd_metal_rust_01.dds", root)
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=shared_entry.path,
                    material_name="Helmet",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=shared_entry.path,
                    resolved_entry=shared_entry,
                ),
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Helmet",
                        material="UV_Samurai_Helmet",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                _payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(source_normal,),
                    original_texture_refs=original_refs,
                    original_sidecars=(),
                    submesh_mappings=(StaticSubmeshMapping(0, "Helmet", [0], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: template.read_bytes(),
                    original_texture_source_path=lambda _entry: template,
                    texture_slot_overrides=(
                        StaticTextureSlotOverride(
                            target_texture_path=shared_entry.path,
                            source_path=str(source_normal),
                            slot_kind="base",
                            target_material_name="Helmet",
                        ),
                    ),
                    pac_driven_sidecar=True,
                )

        warning_text = "\n".join(report.warnings)
        self.assertIn("stock/shared shader texture", warning_text)
        self.assertIn("role mismatch", warning_text)
        self.assertIn("expects base", warning_text)
        self.assertIn("looks like normal", warning_text)

    def test_source_driven_helmet_texture_plan_does_not_auto_bind_gltf_pbr_or_stock_textures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "Helmet_baseColor.png"
            normal_png = root / "Helmet_normal.png"
            pbr_png = root / "Helmet_metallicRoughness.png"
            for source_texture in (base_png, normal_png, pbr_png):
                _write_fake_png_header(source_texture, 4096, 4096)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            material_template = root / "material.dds"
            base_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"BC5U"))
            material_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/blackoil.dds", root)
            normal_entry = _entry("character/texture/cd_phm_00_hel_0013_05_n.dds", root)
            material_entry = _entry("character/texture/cd_common_default_mg.dds", root)
            sidecar_entry = _entry(
                "character/modelproperty/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0013_05.pac_xml",
                root,
            )
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="Helmet",
                    sidecar_parameter_name="_baseColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=normal_entry.path,
                    material_name="Helmet",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=normal_entry.path,
                    resolved_entry=normal_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=material_entry.path,
                    material_name="Helmet",
                    sidecar_parameter_name="_detailMaskTexture",
                    resolved_archive_path=material_entry.path,
                    resolved_entry=material_entry,
                ),
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/blackoil.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/cd_phm_00_hel_0013_05_n.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/cd_common_default_mg.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Helmet",
                        material="Helmet",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mappings = (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="Helmet",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                ),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                fmt = str(command[command.index("-f") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"BC5U" if fmt == "BC5_UNORM" else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(base_png, normal_png, pbr_png),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: (
                        normal_template.read_bytes()
                        if entry is normal_entry
                        else material_template.read_bytes()
                        if entry is material_entry
                        else base_template.read_bytes()
                    ),
                    original_texture_source_path=lambda entry: (
                        normal_template
                        if entry is normal_entry
                        else material_template
                        if entry is material_entry
                        else base_template
                    ),
                    pac_driven_sidecar=True,
                )

            texture_payloads = [payload for payload in payloads if payload.kind == "texture_generated"]
            self.assertTrue(texture_payloads)
            self.assertFalse(any(payload.source_path.name == "Helmet_metallicRoughness.png" for payload in texture_payloads))
            self.assertFalse(any("blackoil" in payload.target_path.lower() for payload in texture_payloads))
            self.assertFalse(any("cd_common_default" in payload.target_path.lower() for payload in texture_payloads))
            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched_sidecar = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("_normalTexture", patched_sidecar)
            self.assertIn("_n.dds", patched_sidecar)
            self.assertEqual(1, len(report.material_routes))
            self.assertEqual("Ready", report.material_routes[0].status)
            self.assertEqual(("base", "normal", "roughness"), report.material_routes[0].detected_roles)
            self.assertTrue(any("standalone PBR source map" in warning for warning in report.warnings))

    def test_source_driven_cd_material_family_routes_o_n_disp_ma_mg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            source_files = tuple(root / name for name in ("Helmet_o.png", "Helmet_n.png", "Helmet_disp.png", "Helmet_ma.png", "Helmet_mg.png"))
            for source_texture in source_files:
                _write_fake_png_header(source_texture, 1024, 1024)
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"DXT1"))
            normal_template = root / "normal.dds"
            normal_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"BC5U"))
            ref_paths = {
                "_overlayColorTexture": "character/texture/cd_phm_00_hel_0145_01_o.dds",
                "_normalTexture": "character/texture/cd_phm_00_hel_0145_01_n.dds",
                "_heightTexture": "character/texture/cd_phm_00_hel_0145_01_disp.dds",
                "_overlayColorTexture_ma": "character/texture/cd_phm_00_hel_0145_01_ma.dds",
                "_detailMaskTexture": "character/texture/cd_phm_00_hel_0145_01_mg.dds",
            }
            entries = {key: _entry(path, root) for key, path in ref_paths.items()}
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=ref_paths["_overlayColorTexture"],
                    material_name="Helmet",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=ref_paths["_overlayColorTexture"],
                    resolved_entry=entries["_overlayColorTexture"],
                ),
                ArchiveModelTextureReference(
                    reference_name=ref_paths["_normalTexture"],
                    material_name="Helmet",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=ref_paths["_normalTexture"],
                    resolved_entry=entries["_normalTexture"],
                ),
                ArchiveModelTextureReference(
                    reference_name=ref_paths["_heightTexture"],
                    material_name="Helmet",
                    sidecar_parameter_name="_heightTexture",
                    resolved_archive_path=ref_paths["_heightTexture"],
                    resolved_entry=entries["_heightTexture"],
                ),
                ArchiveModelTextureReference(
                    reference_name=ref_paths["_overlayColorTexture_ma"],
                    material_name="Helmet",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=ref_paths["_overlayColorTexture_ma"],
                    resolved_entry=entries["_overlayColorTexture_ma"],
                ),
                ArchiveModelTextureReference(
                    reference_name=ref_paths["_detailMaskTexture"],
                    material_name="Helmet",
                    sidecar_parameter_name="_detailMaskTexture",
                    resolved_archive_path=ref_paths["_detailMaskTexture"],
                    resolved_entry=entries["_detailMaskTexture"],
                ),
            )
            sidecar_entry = _entry("character/modelproperty/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0145_01.pac_xml", root)
            sidecar_text = '<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet"><Vector Name="_parameters">' + "".join(
                f'<MaterialParameterTexture _name="{param}"><ResourceReferencePath_ITexture _path="{path}"/></MaterialParameterTexture>'
                for param, path in (
                    ("_overlayColorTexture", ref_paths["_overlayColorTexture"]),
                    ("_normalTexture", ref_paths["_normalTexture"]),
                    ("_heightTexture", ref_paths["_heightTexture"]),
                    ("_overlayColorTexture", ref_paths["_overlayColorTexture_ma"]),
                    ("_detailMaskTexture", ref_paths["_detailMaskTexture"]),
                )
            ) + "</Vector></SkinnedMeshMaterialWrapper></Root>"
            mesh = ParsedMesh(submeshes=[SubMesh(name="Helmet", material="Helmet", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])])
            mappings = (StaticSubmeshMapping(0, "Helmet", [0], 0),)

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                fmt = str(command[command.index("-f") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"BC5U" if fmt == "BC5_UNORM" else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=source_files,
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["_normalTexture"] else template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["_normalTexture"] else template,
                    pac_driven_sidecar=True,
                )

            generated_names = {payload.source_path.name for payload in payloads if payload.kind == "texture_generated"}
            self.assertEqual({path.name for path in source_files}, generated_names)
            patched_sidecar = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            self.assertIn("_ma.dds", patched_sidecar)
            self.assertIn("_mg.dds", patched_sidecar)
            self.assertIn("_disp.dds", patched_sidecar)
            self.assertEqual(("base", "normal", "height", "material_mask", "detail_mask"), report.material_routes[0].detected_roles)

    def test_source_driven_multi_material_helmet_route_blocks_instead_of_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            helmet_base = root / "UV_Samurai_Helmet_baseColor.png"
            helmet_normal = root / "UV_Samurai_Helmet_normal.png"
            mask_base = root / "UV_Samurai_Mask_baseColor.png"
            mask_normal = root / "UV_Samurai_Mask_normal.png"
            for source_texture in (helmet_base, helmet_normal, mask_base, mask_normal):
                _write_fake_png_header(source_texture, 1024, 1024)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            base_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(1024, 1024, mips=11, fourcc=b"BC5U"))
            base_entry = _entry("character/texture/cd_phm_00_hel_00_0377.dds", root)
            normal_entry = _entry("character/texture/cd_phm_00_hel_00_0377_n.dds", root)
            sidecar_entry = _entry(
                "character/modelproperty/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0377.pac_xml",
                root,
            )
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="CD_PHM_00_Hel_00_0377",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=normal_entry.path,
                    material_name="CD_PHM_00_Hel_00_0377",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=normal_entry.path,
                    resolved_entry=normal_entry,
                ),
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_00_Hel_00_0377"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/cd_phm_00_hel_00_0377.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/cd_phm_00_hel_00_0377_n.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></SkinnedMeshMaterialWrapper></Root>"
            )
            source_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Samurai_Helmet", material="UV_Samurai_Helmet", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Samurai_Mask", material="UV_Samurai_Mask", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Object002", material="M_UE4Man_Body", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="CD_PHM_00_Hel_00_0377",
                        material="CD_PHM_00_Hel_00_0377",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mappings = (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="CD_PHM_00_Hel_00_0377",
                    source_submesh_indices=[0, 1, 2],
                    target_material_slot_index=0,
                ),
            )

            with patch("cdmw.core.common.run_process_with_cancellation") as fake_texconv:
                fake_texconv.return_value = (0, "", "")
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=source_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(helmet_base, helmet_normal, mask_base, mask_normal),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is normal_entry else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is normal_entry else base_template,
                    pac_driven_sidecar=True,
                )

            self.assertFalse([payload for payload in payloads if payload.kind == "texture_generated"])
            self.assertEqual(1, len(report.material_routes))
            self.assertTrue(report.material_routes[0].blocker)
            self.assertEqual("Blocked", report.material_routes[0].status)
            self.assertIn("UV_Samurai_Helmet", report.material_routes[0].source_material_name)
            self.assertIn("UV_Samurai_Mask", report.material_routes[0].source_material_name)
            self.assertTrue(any("Texture routing blocker" in warning for warning in report.warnings))
            self.assertTrue(any("M_UE4Man_Body" in warning for warning in report.warnings))

    def test_texture_sets_can_match_part_named_files_when_obj_material_differs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blade_base = root / "blade.001_Base_Color.png"
            blade_normal = root / "blade.001_Normal_OpenGL.png"
            handle_base = root / "Handle.002_Base_Color.png"
            for path in (blade_base, blade_normal, handle_base):
                path.write_bytes(b"")

            obj_mesh = ParsedMesh(
                path="Rathalos_Sword_Final.obj",
                format="obj",
                submeshes=[
                    SubMesh(
                        name="Sword_Body_low_Cube.002",
                        material="Rathalos.001",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    ),
                    SubMesh(
                        name="Sword_Handle_low_Cube.004",
                        material="Handle.002",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    ),
                ],
            )
            texture_sets = group_replacement_texture_sets(
                (blade_base, blade_normal, handle_base),
                obj_mesh=obj_mesh,
            )
            chosen = _choose_source_materials_for_targets(
                obj_mesh,
                texture_sets,
                (
                    StaticSubmeshMapping(
                        target_submesh_index=0,
                        target_submesh_name="CD_PHM_01_Dagger_Blade_0078",
                        source_submesh_indices=[0],
                        target_material_slot_index=0,
                    ),
                    StaticSubmeshMapping(
                        target_submesh_index=1,
                        target_submesh_name="CD_PHM_01_Dagger_Handle_0078",
                        source_submesh_indices=[1],
                        target_material_slot_index=1,
                    ),
                ),
                TextureReplacementReport(),
            )

            self.assertEqual("blade.001", chosen["cd_phm_01_dagger_blade_0078"])
            self.assertEqual("Handle.002", chosen["cd_phm_01_dagger_handle_0078"])

    def test_texture_sets_can_match_gltf_texture_reference_when_material_differs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            material_base = root / "Material.020_baseColor.png"
            material_normal = root / "Material.020_normal.png"
            for path in (material_base, material_normal):
                path.write_bytes(b"")

            obj_mesh = ParsedMesh(
                path="musket_scene.gltf",
                format="gltf",
                submeshes=[
                    SubMesh(
                        name="scope",
                        material="Material.030",
                        texture=str(material_base),
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0), (0, 0, 0)],
                    )
                ],
            )
            texture_sets = group_replacement_texture_sets(
                (material_base, material_normal),
                obj_mesh=obj_mesh,
            )
            _attach_source_face_counts(texture_sets, obj_mesh)
            report = TextureReplacementReport()
            chosen = _choose_source_materials_for_targets(
                obj_mesh,
                texture_sets,
                (
                    StaticSubmeshMapping(
                        target_submesh_index=0,
                        target_submesh_name="CD_PHM_08_Musket_Scope_0006",
                        source_submesh_indices=[0],
                        target_material_slot_index=0,
                    ),
                ),
                report,
            )

            self.assertEqual("Material.020", chosen["cd_phm_08_musket_scope_0006"])
            self.assertEqual(2, texture_sets["material.020"].source_face_count)
            self.assertTrue(any("matched from source texture" in warning for warning in report.warnings))

    def test_texture_sets_detect_single_material_files_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_files = (
                root / "Base Color.png",
                root / "Normal OpenGL.png",
                root / "Height.png",
                root / "Mixed AO.png",
            )
            for path in texture_files:
                path.write_bytes(b"")

            obj_mesh = ParsedMesh(
                path="single.obj",
                format="obj",
                submeshes=[
                    SubMesh(
                        name="Blade.001",
                        material="HeroBlade",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ],
            )

            texture_sets = group_replacement_texture_sets(texture_files, obj_mesh=obj_mesh)
            self.assertIn("heroblade", texture_sets)
            slots = texture_sets["heroblade"].slots
            self.assertEqual("Base Color.png", slots["base"].source_path.name)
            self.assertEqual("Normal OpenGL.png", slots["normal"].source_path.name)
            self.assertEqual("opengl", slots["normal"].normal_space)
            self.assertEqual("Height.png", slots["height"].source_path.name)
            self.assertEqual("Mixed AO.png", slots["ao"].source_path.name)

    def test_source_material_override_uses_explicit_base_when_filename_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            chosen_base = root / "handpicked_surface.png"
            _write_fake_png_header(chosen_base, 256, 256)
            template_dds = root / "template_base.dds"
            template_dds.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            base_entry = _entry("character/texture/cd_target_slot_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/target_slot.pac_xml", root)
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="TargetSlot",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
            )
            sidecar_text = (
                '<Root><CDMaterialWrapper _subMeshName="TargetSlot"><Vector Name="_parameters">'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_target_slot_o.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></CDMaterialWrapper></Root>"
            )
            source_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="added_geo",
                        material="AddedPart",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="TargetSlot",
                        material="TargetSlot",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mappings = (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="TargetSlot",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                ),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=source_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(chosen_base,),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: template_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: template_dds,
                    source_material_texture_overrides=(("AddedPart", "base", str(chosen_base)),),
                    pac_driven_sidecar=True,
                )

            texture_payloads = [payload for payload in payloads if payload.kind == "texture_generated"]
            self.assertEqual(1, len(texture_payloads))
            self.assertEqual(chosen_base.resolve(), texture_payloads[0].source_path)
            self.assertTrue(
                any(
                    mapping.target_material_name == "TargetSlot"
                    and mapping.source_material_name == "AddedPart"
                    and mapping.slot_kind == "base"
                    and mapping.source_path == chosen_base.resolve()
                    for mapping in report.slot_mappings
                )
            )
            self.assertIn("Applied 1 source-material texture override(s).", report.warnings)
            self.assertFalse(
                any("No replacement texture files matched known material suffix patterns." in warning for warning in report.warnings)
            )

    def test_texture_sets_accept_space_separated_material_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "Handle.002 Base Color.png"
            normal = root / "Handle.002 Normal OpenGL.png"
            material = root / "Handle.002 Material Mask.png"
            for path in (base, normal, material):
                path.write_bytes(b"")

            obj_mesh = ParsedMesh(
                path="handle.obj",
                format="obj",
                submeshes=[
                    SubMesh(
                        name="Handle.002",
                        material="Handle.002",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ],
            )

            texture_sets = group_replacement_texture_sets((base, normal, material), obj_mesh=obj_mesh)
            self.assertIn("handle.002", texture_sets)
            slots = texture_sets["handle.002"].slots
            self.assertEqual("Handle.002 Base Color.png", slots["base"].source_path.name)
            self.assertEqual("Handle.002 Normal OpenGL.png", slots["normal"].source_path.name)
            self.assertEqual("Handle.002 Material Mask.png", slots["material"].source_path.name)

    def test_texture_sets_detect_gltf_metallic_roughness_as_review_only_pbr_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "20_-_Default_baseColor.png"
            normal = root / "20_-_Default_normal.png"
            material = root / "20_-_Default_metallicRoughness.png"
            for path in (base, normal, material):
                path.write_bytes(b"")

            texture_sets = group_replacement_texture_sets((base, normal, material))
            self.assertIn("20_-_default", texture_sets)
            slots = texture_sets["20_-_default"].slots
            self.assertEqual("20_-_Default_baseColor.png", slots["base"].source_path.name)
            self.assertEqual("20_-_Default_normal.png", slots["normal"].source_path.name)
            self.assertEqual("20_-_Default_metallicRoughness.png", slots["roughness"].source_path.name)
            self.assertNotIn("material", slots)
            self.assertNotIn("metallic", slots)

    def test_texture_sets_prefer_base_color_over_emissive_for_base_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            emissive = root / "New_Sword_lp_UV_Emissive.png"
            base = root / "New_Sword_lp_UV_BaseColor.png"
            for path in (emissive, base):
                path.write_bytes(b"")

            texture_sets = group_replacement_texture_sets((emissive, base))
            self.assertIn("new_sword_lp_uv", texture_sets)
            slots = texture_sets["new_sword_lp_uv"].slots
            self.assertEqual("New_Sword_lp_UV_BaseColor.png", slots["base"].source_path.name)

    def test_mesh_loose_export_includes_generated_payloads_but_not_unselected_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry("character/model/weapon/test_weapon.pac", root)
            pab = _entry("character/model/test_skeleton.pab", root)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"rebuilt",
                parsed_mesh=ParsedMesh(path=primary.path, format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
                texture_references=(
                    ArchiveModelTextureReference(
                        reference_name=pab.basename,
                        resolved_archive_path=pab.path,
                        resolved_entry=pab,
                        reference_kind="skeleton",
                        relation_group="Skeleton / Rig",
                    ),
                ),
                supplemental_file_specs=(
                    MeshImportSupplementalFileSpec(
                        source_path=root / "generated.dds",
                        target_path="character/texture/generated.dds",
                        kind="texture_generated",
                        payload_data=b"DDS generated",
                    ),
                    MeshImportSupplementalFileSpec(
                        source_path=root / "generated.pac_xml",
                        target_path="character/modelproperty/test_weapon.pac_xml",
                        kind="sidecar_generated",
                        payload_data=b"<Material />",
                    ),
                ),
            )

            result = export_archive_mesh_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(primary, b"rebuilt"),),
                primary_entry=primary,
                preview_result=preview,
                source_obj_path=root / "source.obj",
                parent_root=root,
                package_info=ModPackageInfo(title="Mesh Mod"),
                related_entries_to_include=(),
                supplemental_files_to_include=preview.supplemental_file_specs,
            )

            self.assertTrue((result.package_root / "character" / "texture" / "generated.dds").exists())
            self.assertTrue((result.package_root / "character" / "modelproperty" / "test_weapon.pac_xml").exists())
            self.assertFalse((result.package_root / "character" / "model" / "test_skeleton.pab").exists())
            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            files = {item["path"]: item for item in manifest["files"]}
            self.assertIn("Generated replacement texture", files["character/texture/generated.dds"]["note"])
            self.assertIn("Generated patched sidecar", files["character/modelproperty/test_weapon.pac_xml"]["note"])

    def test_mesh_loose_export_custom_compact_paths_keeps_textures_under_character_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry(
                "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0278.pac",
                root,
            )
            sidecar_path = "character/modelproperty/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0278.pac_xml"
            preview = MeshImportPreviewResult(
                rebuilt_data=b"rebuilt",
                parsed_mesh=ParsedMesh(path=primary.path, format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
                supplemental_file_specs=(
                    MeshImportSupplementalFileSpec(
                        source_path=root / "generated.dds",
                        target_path="character/texture/cd_phm_01_sword_0278_blade_base.dds",
                        kind="texture_generated",
                        payload_data=b"DDS generated",
                    ),
                    MeshImportSupplementalFileSpec(
                        source_path=root / "generated.pac_xml",
                        target_path=sidecar_path,
                        kind="sidecar_generated",
                        payload_data=b"<Material />",
                    ),
                ),
            )

            result = export_archive_mesh_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(primary, b"rebuilt"),),
                primary_entry=primary,
                preview_result=preview,
                source_obj_path=root / "source.obj",
                parent_root=root,
                package_info=ModPackageInfo(title="Compact Mesh Mod"),
                export_options=ModPackageExportOptions(structure="custom_compact_paths"),
                related_entries_to_include=(),
                supplemental_files_to_include=preview.supplemental_file_specs,
            )

            self.assertTrue((result.package_root / "files" / "character" / "cd_phm_01_sword_0278.pac").exists())
            self.assertTrue((result.package_root / "files" / "character" / "cd_phm_01_sword_0278.pac_xml").exists())
            self.assertTrue(
                (
                    result.package_root
                    / "files"
                    / "character"
                    / "texture"
                    / "cd_phm_01_sword_0278_blade_base.dds"
                ).exists()
            )
            self.assertFalse((result.package_root / "character").exists())
            self.assertFalse((result.package_root / "files" / "character" / "model").exists())
            self.assertFalse((result.package_root / "files" / "character" / "modelproperty").exists())

            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("custom_compact_paths", manifest["structure"])
            self.assertEqual("files", manifest["files_root"])
            self.assertEqual("character/cd_phm_01_sword_0278.pac", manifest["assets"][0]["entry_path"])
            files = {item["path"]: item for item in manifest["files"]}
            self.assertIn("character/cd_phm_01_sword_0278.pac", files)
            self.assertIn("character/cd_phm_01_sword_0278.pac_xml", files)
            self.assertIn("character/texture/cd_phm_01_sword_0278_blade_base.dds", files)

    def test_mesh_loose_export_includes_explicitly_selected_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry("character/model/weapon/test_weapon.pac", root)
            hkx = _entry("character/bin__/meshphysics/test_weapon.hkx", root)
            preview = MeshImportPreviewResult(
                rebuilt_data=b"rebuilt",
                parsed_mesh=ParsedMesh(path=primary.path, format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
            )

            def fake_extract(entry: ArchiveEntry, target_path: Path, **_kwargs: object) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(f"related:{entry.path}".encode("utf-8"))
                return target_path

            with patch("cdmw.core.archive.extract_archive_entry", side_effect=fake_extract):
                result = export_archive_mesh_payloads_to_mod_ready_loose(
                    (ArchivePatchRequest(primary, b"rebuilt"),),
                    primary_entry=primary,
                    preview_result=preview,
                    source_obj_path=root / "source.obj",
                    parent_root=root,
                    package_info=ModPackageInfo(title="Mesh Mod"),
                    related_entries_to_include=(hkx,),
                )

            self.assertTrue((result.package_root / "character" / "bin__" / "meshphysics" / "test_weapon.hkx").exists())
            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            files = {item["path"]: item for item in manifest["files"]}
            self.assertIn("Selected archive related file", files["character/bin__/meshphysics/test_weapon.hkx"]["note"])

    def test_pac_driven_sidecar_auto_injects_missing_active_base_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            handle_base = root / "Handle.002_BaseColor.png"
            handle_normal = root / "Handle.002_Normal.png"
            handle_metallic = root / "Handle.002_Metallic.png"
            handle_roughness = root / "Handle.002_Roughness.png"
            for source_texture in (handle_base, handle_normal, handle_metallic, handle_roughness):
                _write_fake_png_header(source_texture, 4096, 4096)
            template_base_dds = root / "template_base.dds"
            template_normal_dds = root / "template_normal.dds"
            template_material_dds = root / "template_material.dds"
            template_base_dds.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            template_normal_dds.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            template_material_dds.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            base_entry = _entry("character/texture/cd_phm_01_sword_blade_0278_o.dds", root)
            normal_entry = _entry("character/texture/cd_phm_01_sword_handle_0278_n.dds", root)
            material_entry = _entry("character/texture/cd_phm_01_sword_handle_0278_ma.dds", root)
            sidecar_entry = _entry(
                "character/modelproperty/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0278.pac_xml",
                root,
            )
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="Blade",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=normal_entry.path,
                    material_name="Handle.002",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=normal_entry.path,
                    resolved_entry=normal_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=material_entry.path,
                    material_name="Handle.002",
                    sidecar_parameter_name="_colorBlendingMaskTexture",
                    resolved_archive_path=material_entry.path,
                    resolved_entry=material_entry,
                ),
            )
            sidecar_text = (
                '<Root><CDMaterialWrapper _subMeshName="Handle.002"><Vector Name="_parameters">'
                '<MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="0">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phm_01_sword_handle_0278_n.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_heightTexture" _name="_heightTexture" Index="1">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phm_01_sword_handle_0278_disp.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture" Index="2">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phm_01_sword_handle_0278_ma.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_grimeDiffuseTextureG" _name="_grimeDiffuseTextureG" Index="3">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_texturelayer_003_0101.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></CDMaterialWrapper></Root>"
            )
            obj_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Handle.002",
                        material="Handle.002",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Handle.002",
                        material="Handle.002",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mappings = (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="Handle.002",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                ),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=obj_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(handle_base, handle_normal, handle_metallic, handle_roughness),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: (
                        template_base_dds.read_bytes()
                        if entry is base_entry
                        else template_material_dds.read_bytes()
                        if entry is material_entry
                        else template_normal_dds.read_bytes()
                    ),
                    original_texture_source_path=lambda entry: (
                        template_base_dds
                        if entry is base_entry
                        else template_material_dds
                        if entry is material_entry
                        else template_normal_dds
                    ),
                    pac_driven_sidecar=True,
                )

            payloads_by_path = {payload.target_path: payload for payload in payloads}
            self.assertIn(sidecar_entry.path, payloads_by_path)
            texture_payloads = [payload for payload in payloads if payload.kind == "texture_generated"]
            self.assertEqual(2, len(texture_payloads))
            self.assertTrue(any(payload.target_path.endswith("handle_002_basecolor.dds") for payload in texture_payloads))
            self.assertTrue(any(payload.target_path.endswith("handle_002_n.dds") for payload in texture_payloads))
            self.assertFalse(any(payload.target_path.endswith("handle_002_metallic.dds") for payload in texture_payloads))
            self.assertFalse(any(payload.target_path.endswith("handle_002_roughness.dds") for payload in texture_payloads))
            patched_sidecar = payloads_by_path[sidecar_entry.path].payload_data.decode("utf-8")
            self.assertIn("_overlayColorTexture", patched_sidecar)
            self.assertIn("_normalTexture", patched_sidecar)
            self.assertNotIn("_metallicTexture", patched_sidecar)
            self.assertNotIn("_roughnessTexture", patched_sidecar)
            self.assertNotIn("_ambientOcclusionTexture", patched_sidecar)
            self.assertIn("_overlayColorTexture", patched_sidecar)
            self.assertIn("_colorBlendingMaskTexture", patched_sidecar)
            self.assertIn("_grimeDiffuseTextureG", patched_sidecar)
            self.assertIn("cd_texturelayer_003_0101.dds", patched_sidecar)
            self.assertIn("character/texture/cd_phm_01_sword_handle_0278_ma.dds", patched_sidecar)
            self.assertIn("character/texture/cd_phm_01_sword_0278_handle_002_basecolor.dds", patched_sidecar)
            self.assertTrue(
                any(mapping.slot_kind == "base" and mapping.output_texture_path.endswith("handle_002_basecolor.dds") for mapping in report.slot_mappings)
            )

    def test_pac_driven_sidecar_honors_manual_texture_slot_overrides_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_source = root / "CD_PHW_00_Nude_0001.dds"
            normal_source = root / "CD_PHW_00_Nude_0001_n.dds"
            base_source.write_bytes(_fake_dds_bytes(1024, 1024, mips=11))
            normal_source.write_bytes(_fake_dds_bytes(1024, 1024, mips=11))
            template_base = root / "template_base.dds"
            template_normal = root / "template_normal.dds"
            template_base.write_bytes(_fake_dds_bytes(2048, 2048, mips=12))
            template_normal.write_bytes(_fake_dds_bytes(1024, 2048, mips=12))
            base_entry = _entry("character/texture/cd_phw_00_nude_00_0001.dds", root)
            normal_entry = _entry("character/texture/cd_phw_00_nude_00_0001_n.dds", root)
            sidecar_entry = _entry("character/modelproperty/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac_xml", root)
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="CD_PHW_00_Nude_00_0001",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=normal_entry.path,
                    material_name="CD_PHW_00_Nude_00_0001",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=normal_entry.path,
                    resolved_entry=normal_entry,
                ),
            )
            sidecar_text = (
                '<Root><CDMaterialWrapper _subMeshName="CD_PHW_00_Nude_00_0001"><Vector Name="_parameters">'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phw_00_nude_00_0001.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phw_00_nude_00_0001_n.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></CDMaterialWrapper></Root>"
            )
            replacement_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="CD_PHW_00_Nude_0001",
                        material="CD_PHW_00_Nude_0001",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="CD_PHW_00_Nude_00_0001",
                        material="CD_PHW_00_Nude_00_0001",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mappings = (
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="CD_PHW_00_Nude_00_0001",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                ),
            )

            with patch("cdmw.core.common.run_process_with_cancellation") as fake_texconv:
                fake_texconv.return_value = (0, "", "")
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=replacement_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(base_source, normal_source),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=None,
                    read_original_texture_bytes=lambda entry: template_base.read_bytes() if entry is base_entry else template_normal.read_bytes(),
                    original_texture_source_path=lambda entry: template_base if entry is base_entry else template_normal,
                    texture_slot_overrides=(
                        StaticTextureSlotOverride(
                            target_texture_path=base_entry.path,
                            source_path=str(base_source),
                            slot_kind="base",
                            target_material_name="CD_PHW_00_Nude_00_0001",
                        ),
                        StaticTextureSlotOverride(
                            target_texture_path=normal_entry.path,
                            source_path=str(normal_source),
                            slot_kind="normal",
                            target_material_name="CD_PHW_00_Nude_00_0001",
                        ),
                    ),
                    pac_driven_sidecar=True,
                )

            payloads_by_path = {payload.target_path: payload for payload in payloads}
            self.assertIn(base_entry.path, payloads_by_path)
            self.assertIn(normal_entry.path, payloads_by_path)
            self.assertIn("Applied 2 manual texture slot override(s).", report.warnings)
            self.assertTrue(
                any(
                    mapping.target_texture_path == base_entry.path
                    and mapping.output_texture_path == base_entry.path
                    and mapping.slot_kind == "base"
                    for mapping in report.slot_mappings
                )
            )
            self.assertTrue(
                any(
                    mapping.target_texture_path == normal_entry.path
                    and mapping.output_texture_path == normal_entry.path
                    and mapping.slot_kind == "normal"
                    for mapping in report.slot_mappings
                )
            )
            self.assertNotIn(sidecar_entry.path, payloads_by_path)
            self.assertIn(
                "PAC-driven texture payloads were built, but no .pac_xml sidecar changes were applied. "
                "This is expected only when texture paths are overwritten in-place.",
                report.warnings,
            )

    def test_material_sidecar_patch_keeps_unmapped_shader_texture_parameters(self) -> None:
        sidecar_text = (
            '<Root><CDMaterialWrapper _subMeshName="CD_PHM_02_Blade_0014"><Vector Name="_parameters">'
            '<MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">'
            '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_phm_02_blade_0014.dds"/>'
            '</MaterialParameterTexture>'
            '<MaterialParameterTexture StringItemID="_grimeDiffuseTextureG" _name="_grimeDiffuseTextureG" Index="1">'
            '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_texturelayer_013_0018.dds"/>'
            '</MaterialParameterTexture>'
            '<MaterialParameterTexture StringItemID="_detailMaterialMaskG" _name="_detailMaterialMaskG" Index="2">'
            '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_texturelayer_013_0018_sp.dds"/>'
            '</MaterialParameterTexture>'
            "</Vector></CDMaterialWrapper></Root>"
        )

        patched_sidecar, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac_xml",
                texture_path_replacements={
                    "character/texture/cd_phm_02_blade_0014.dds": "character/texture/hero_blade_base.dds",
                },
            ),
        )

        self.assertIn("character/texture/hero_blade_base.dds", patched_sidecar)
        self.assertIn("_grimeDiffuseTextureG", patched_sidecar)
        self.assertIn("cd_texturelayer_013_0018.dds", patched_sidecar)
        self.assertIn("_detailMaterialMaskG", patched_sidecar)
        self.assertIn("cd_texturelayer_013_0018_sp.dds", patched_sidecar)
        self.assertFalse(any("unmapped original texture parameter" in warning for warning in report.warnings))


if __name__ == "__main__":
    unittest.main()
