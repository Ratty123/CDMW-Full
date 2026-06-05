from __future__ import annotations

import json
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cdmw.core.archive_modding import (
    ArchivePatchRequest,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
    _build_mesh_import_supplemental_file_specs,
    _build_selected_sidecar_texture_bindings,
    _mesh_import_auto_companion_entries,
    audit_loose_package_active_file_authority,
    export_archive_mesh_payloads_to_mod_ready_loose,
)
from cdmw.core.mod_package import ModPackageExportOptions
from cdmw.core.pipeline import parse_dds
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ModelPreviewData,
    ModPackageInfo,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.material_replacer import (
    ReplacementTextureSlot,
    ReplacementTextureSet,
    SidecarMaterialWrapperClone,
    SidecarPatchPlan,
    TextureSlotMapping,
    TextureReplacementPayload,
    TextureReplacementReport,
    _MANUAL_PROFILE_FIELD_NAMES,
    _attach_source_face_counts,
    _append_texture_contract_warnings,
    _apply_source_part_role_overrides,
    _apply_source_pbr_scalar_parameters,
    _bruteforce_source_authority_texture_parameters,
    _build_source_driven_sidecar_text,
    _choose_source_materials_for_targets,
    _complete_swap_accent_emissive_slot,
    _complete_swap_runtime_material_mask_png_path,
    _complete_swap_neutral_support_png_path,
    _neutralize_inherited_material_layers,
    apply_true_source_basic_controls_to_profile,
    apply_global_gloss_reduction_to_profile,
    complete_swap_material_authority_contract,
    complete_swap_material_requires_true_source_authority,
    complete_swap_material_runtime_profiles,
    complete_swap_material_probe_variants,
    get_complete_swap_material_profile,
    _prune_source_owned_sidecar_material_wrappers,
    _profile_scalar_values,
    _source_pbr_scalar_values,
    _source_slot_png_with_base_color_factor_path,
    _source_slot_needs_base_color_adjustment,
    _source_driven_parameter_name,
    _source_driven_slots,
    _texture_set_accent_glow_color_hex,
    _texture_set_is_accent_glow_candidate,
    _visible_gem_sensitive_wrappers_touched,
    build_texture_replacement_payloads,
    build_source_material_routing_plan,
    _build_texture_payload,
    classify_texture_assignment_guidance,
    group_replacement_texture_sets,
    is_static_replacement_helper_material_name,
    is_shared_material_layer_texture,
    material_authority_preview_texture_slots,
    patch_material_sidecar_text,
    read_complete_swap_calibrated_material_profile,
    replacement_texture_slot_preview_semantics,
    serialize_complete_swap_manual_material_profile,
    write_complete_swap_calibrated_material_profile,
    write_complete_swap_material_probe_manifests,
    write_complete_swap_material_probe_packages,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import (
    StaticMaterialAtlasRect,
    StaticOutputDrawSection,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    StaticTextureSlotOverride,
)


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


def _path_block(path: str) -> bytes:
    encoded = path.encode("utf-8")
    return struct.pack("<IB", 0xFFFFFFFF, len(encoded)) + encoded


def _write_single_file_pamt(package_dir: Path, virtual_path: str, payload: bytes) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    pamt_path = package_dir / "0.pamt"
    paz_path = package_dir / "0.paz"
    paz_path.write_bytes(payload)
    name_block = _path_block(virtual_path)
    data = bytearray()
    data.extend(struct.pack("<III", 0, 1, 0))
    data.extend(b"\x00" * 12)
    data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<I", len(name_block)))
    data.extend(name_block)
    data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<I", 1))
    data.extend(struct.pack("<IIIIHH", 0, 0, len(payload), len(payload), 0, 0))
    pamt_path.write_bytes(bytes(data))
    return pamt_path


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
    def test_sidecar_patch_can_neutralize_inherited_material_layers(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Target_A">
    <Material>
      <Vector Name="_parameters">
        <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="0">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/new_n.dds"/>
        </MaterialParameterTexture>
        <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="1">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/new_base.dds"/>
        </MaterialParameterTexture>
        <MaterialParameterTexture StringItemID="_detailMaskTexture" _name="_detailMaskTexture" Index="2">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/original_mg.dds"/>
        </MaterialParameterTexture>
        <MaterialParameterTexture StringItemID="_grimeDiffuseTextureR" _name="_grimeDiffuseTextureR" Index="3">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/cd_texturelayer_003_0101.dds"/>
        </MaterialParameterTexture>
        <MaterialParameterBitFlag32 _name="_colorBlendingFlag" _value="4095" Index="4"/>
        <MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="5"/>
        <MaterialParameterByte4 _name="_grimeBlendingParameterR" _value="536917686" Index="6"/>
      </Vector>
    </Material>
  </SkinnedMeshMaterialWrapper>
  <SkinnedMeshMaterialWrapper _subMeshName="Untouched_B">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_detailMaskTexture" _name="_detailMaskTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/keep_mg.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""
        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="target.pac_xml",
                neutralize_inherited_material_layers=True,
                neutralize_material_names=["Target_A"],
                texture_parameter_keep_rules=[
                    ("_normalTexture", "character/texture/new_n.dds"),
                    ("_overlayColorTexture", "character/texture/new_base.dds"),
                ],
            ),
        )

        self.assertIn("character/texture/new_n.dds", patched)
        self.assertIn("character/texture/new_base.dds", patched)
        self.assertNotIn("original_mg.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0101.dds", patched)
        self.assertIn('_colorBlendingFlag" _value="0"', patched)
        self.assertIn('_tintColorR" _value="#ffffff00"', patched)
        self.assertIn('_grimeBlendingParameterR" _value="0"', patched)
        self.assertIn("keep_mg.dds", patched)
        self.assertGreater(report.replaced_count, 0)

    def test_complete_external_swap_resets_inherited_material_response(self) -> None:
        sidecar_text = """
<Root>
  <OverridedPbdMaterialProperty useAutoWeightingPositionBlending="1"/>
  <SkinnedMeshProperty _pbdSimulationMaterialName="WeaponSpline">
    <Vector Name="_subMeshResources">
      <SkinnedMeshMaterialWrapper _subMeshName="Target_A">
        <Material Name="_resourceMaterial" _materialName="SkinnedMeshCloth_Ver2">
          <Vector Name="_parameters">
            <MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" _name="_renderSettingFlag" _value="6" Index="0"/>
            <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">
              <ResourceReferencePath_ITexture Name="_value" _path="character/texture/new_n.dds"/>
            </MaterialParameterTexture>
            <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="2">
              <ResourceReferencePath_ITexture Name="_value" _path="character/texture/new_base.dds"/>
            </MaterialParameterTexture>
            <MaterialParameterFloat StringItemID="_screenSpaceDisplacementScale" _name="_screenSpaceDisplacementScale" _value="0.150000" Index="3"/>
            <MaterialParameterFloat StringItemID="_detailScreenSpaceDisplacementScale" _name="_detailScreenSpaceDisplacementScale" _value="0.010000" Index="4"/>
            <MaterialParameterByte4 StringItemID="_scratchRoughness" _name="_scratchRoughness" _value="16744359" Index="5"/>
            <MaterialParameterByte4 StringItemID="_scratchMetallic" _name="_scratchMetallic" _value="16777215" Index="6"/>
            <MaterialParameterClothCategory StringItemID="_clothCategory" _name="_clothCategory" _value="Silk" Index="7"/>
            <MaterialParameterFloat StringItemID="_sheen" _name="_sheen" _value="0.200000" Index="8"/>
            <MaterialParameterBitFlag32 StringItemID="_clothMaskBit" _name="_clothMaskBit" _value="7" Index="9"/>
            <MaterialParameterColor StringItemID="_tintColorR" _name="_tintColorR" _value="#402c1aff" Index="10"/>
          </Vector>
        </Material>
      </SkinnedMeshMaterialWrapper>
    </Vector>
  </SkinnedMeshProperty>
</Root>
"""
        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="target.pac_xml",
                neutralize_inherited_material_layers=True,
                complete_external_material_reset=True,
                neutralize_material_names=["Target_A"],
                texture_parameter_keep_rules=[
                    ("_normalTexture", "character/texture/new_n.dds"),
                    ("_overlayColorTexture", "character/texture/new_base.dds"),
                ],
            ),
        )

        self.assertIn('SkinnedMeshStandard_Ver2"', patched)
        self.assertNotIn("SkinnedMeshCloth_Ver2", patched)
        self.assertIn("_pbdSimulationMaterialName", patched)
        self.assertIn("OverridedPbdMaterialProperty", patched)
        self.assertIn('_renderSettingFlag" _value="4"', patched)
        self.assertIn('_screenSpaceDisplacementScale" _value="0.000000"', patched)
        self.assertIn('_detailScreenSpaceDisplacementScale" _value="0.000000"', patched)
        self.assertNotIn("_scratchRoughness", patched)
        self.assertNotIn("_scratchMetallic", patched)
        self.assertNotIn("_clothCategory", patched)
        self.assertNotIn("_clothMaskBit", patched)
        self.assertNotIn("_sheen", patched)
        self.assertIn('_tintColorR" _value="#ffffffff"', patched)
        self.assertNotIn("#ffffff00", patched)
        self.assertIn("character/texture/new_n.dds", patched)
        self.assertIn("character/texture/new_base.dds", patched)
        self.assertGreater(report.replaced_count, 0)

    def test_complete_external_swap_resets_static_pami_color_state(self) -> None:
        sidecar_text = """
<MaterialData>
  <MaterialParameterTexture Name="_baseColorTexture" Value="object/texture/new_base.dds"/>
  <MaterialParameterTexture Name="_normalTexture" Value="object/texture/new_n.dds"/>
  <MaterialParameterTexture Name="_materialTexture" Value="object/texture/old_sp.dds"/>
  <MaterialParameterTexture Name="_heightTexture" Value="object/texture/old_d.dds"/>
  <MaterialParameterTexture Name="_layerBaseColorTexture" Value="object/texture/old_layer.dds"/>
  <MaterialParameterFloat Name="_brightness" Value="1.500000"/>
  <MaterialParameterColor Name="_tintColor" Value="0.596078 0.596078 0.596078"/>
  <MaterialParameterBitFlag32 Name="_colorBlendingFlag" Value="4095"/>
</MaterialData>
"""
        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="target.pami",
                neutralize_inherited_material_layers=True,
                complete_external_material_reset=True,
                texture_parameter_keep_rules=[
                    ("_baseColorTexture", "object/texture/new_base.dds"),
                    ("_normalTexture", "object/texture/new_n.dds"),
                ],
            ),
        )

        self.assertIn('Name="_baseColorTexture" Value="object/texture/new_base.dds"', patched)
        self.assertIn('Name="_normalTexture" Value="object/texture/new_n.dds"', patched)
        self.assertNotIn("_materialTexture", patched)
        self.assertNotIn("_heightTexture", patched)
        self.assertNotIn("_layerBaseColorTexture", patched)
        self.assertIn('Name="_brightness" Value="1.000000"', patched)
        self.assertIn('Name="_tintColor" Value="1.000000 1.000000 1.000000"', patched)
        self.assertIn('Name="_colorBlendingFlag" Value="0"', patched)
        self.assertGreater(report.replaced_count, 0)

    def test_pami_patch_replaces_leading_slash_value_paths(self) -> None:
        patched, report = patch_material_sidecar_text(
            '<MaterialParameterTexture Name="_baseColorTexture" Value="/object/texture/old_base.dds"/>',
            SidecarPatchPlan(
                sidecar_path="target.pami",
                texture_path_replacements={
                    "object/texture/old_base.dds": "object/texture/new_base.dds",
                },
            ),
        )

        self.assertIn('Value="object/texture/new_base.dds"', patched)
        self.assertNotIn("old_base.dds", patched)
        self.assertEqual(1, report.replaced_count)

    def test_complete_external_swap_does_not_route_gltf_pbr_as_color_blend_mask(self) -> None:
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

            strict_slots = _source_driven_slots(
                texture_sets["helmet"],
                include_pbr_material_fallback=True,
            )

            self.assertEqual([], strict_slots)

    def test_complete_external_swap_derives_scratch_metal_response_from_gltf_pbr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr = root / "Helmet_metallicRoughness.png"
            image = Image.new("RGBA", (2, 2), (240, 56, 235, 255))
            image.save(pbr)
            submesh = SubMesh(
                name="Helmet",
                material="Helmet",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.texture_slots = (("metallicRoughness", pbr),)
            texture_sets = group_replacement_texture_sets(
                (pbr,),
                obj_mesh=ParsedMesh(submeshes=[submesh]),
            )

            roughness_value, metallic_value, source_name = _source_pbr_scalar_values(texture_sets["helmet"])
            patched, edited = _apply_source_pbr_scalar_parameters(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/helmet_base.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>",
                material_names=("Helmet",),
                roughness_value=roughness_value,
                metallic_value=metallic_value,
            )

            self.assertEqual("Helmet_metallicRoughness.png", source_name)
            self.assertEqual(56 | (56 << 8) | (56 << 16), roughness_value)
            self.assertEqual(235 | (235 << 8) | (235 << 16), metallic_value)
            self.assertEqual(1, edited)
            self.assertIn("_scratchRoughness", patched)
            self.assertIn(str(56 | (56 << 8) | (56 << 16)), patched)
            self.assertIn("_scratchMetallic", patched)
            self.assertIn(str(235 | (235 << 8) | (235 << 16)), patched)

    def test_complete_external_swap_uses_mesh_material_referenced_gltf_pbr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "Helmet_baseColor.png"
            normal_png = root / "Helmet_normal.png"
            pbr_png = root / "Helmet_metallicRoughness.png"
            _write_fake_png_header(base_png, 512, 512)
            _write_fake_png_header(normal_png, 512, 512)
            Image.new("RGBA", (2, 2), (240, 56, 235, 255)).save(pbr_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            base_template.write_bytes(_fake_dds_bytes(512, 512, mips=10, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(512, 512, mips=10, fourcc=b"BC5U"))
            base_entry = _entry("character/texture/original_o.dds", root)
            normal_entry = _entry("character/texture/original_n.dds", root)
            sidecar_entry = _entry("character/modelproperty/helmet.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Helmet",
                        material="Helmet",
                        texture=str(base_png),
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            setattr(
                mesh.submeshes[0],
                "texture_slots",
                (("base", base_png), ("normal", normal_png), ("metallicRoughness", pbr_png)),
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture" Index="1">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                fmt = str(command[command.index("-f") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=1, fourcc=b"BC5U" if fmt == "BC5_UNORM" else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(base_png, normal_png),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="Helmet",
                            sidecar_parameter_name="_overlayColorTexture",
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
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(
                        StaticSubmeshMapping(
                            target_submesh_index=0,
                            target_submesh_name="Helmet",
                            source_submesh_indices=[0],
                            target_material_slot_index=0,
                        ),
                    ),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes()
                    if entry is normal_entry
                    else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is normal_entry else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("_renderSettingFlag", patched)
            self.assertIn('_value="4"', patched)
            self.assertIn("_colorBlendingMaskTexture", patched)
            self.assertNotIn("_scratchRoughness", patched)
            self.assertNotIn("_scratchMetallic", patched)
            material_payloads = [
                payload for payload in payloads
                if payload.kind == "texture_generated" and "_ma.dds" in payload.target_path
            ]
            self.assertEqual(1, len(material_payloads))
            self.assertTrue(any("generated CD runtime material mask" in warning for warning in report.warnings))

    def test_complete_external_swap_prefers_generated_material_mask_over_pbr_scratch_scalars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "Helmet_baseColor.png"
            pbr_png = root / "Helmet_metallicRoughness.png"
            _write_fake_png_header(base_png, 512, 512)
            Image.new("RGBA", (2, 2), (240, 56, 235, 255)).save(pbr_png)
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(512, 512, mips=10, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_o.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
            }
            sidecar_entry = _entry("character/modelproperty/helmet.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Helmet",
                        material="Helmet",
                        texture=str(base_png),
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", base_png), ("metallicRoughness", pbr_png))
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Helmet"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture" Index="1">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(base_png,),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=entries["base"].path,
                            material_name="Helmet",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=entries["base"].path,
                            resolved_entry=entries["base"],
                        ),
                        ArchiveModelTextureReference(
                            reference_name=entries["material_mask"].path,
                            material_name="Helmet",
                            sidecar_parameter_name="_colorBlendingMaskTexture",
                            resolved_archive_path=entries["material_mask"].path,
                            resolved_entry=entries["material_mask"],
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "Helmet", [0], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: template.read_bytes(),
                    original_texture_source_path=lambda _entry: template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("_colorBlendingMaskTexture", patched)
            self.assertNotIn("_scratchRoughness", patched)
            self.assertNotIn("_scratchMetallic", patched)
            material_payloads = [
                payload for payload in payloads
                if payload.kind == "texture_generated" and "_ma.dds" in payload.target_path
            ]
            self.assertEqual(1, len(material_payloads))
            self.assertIn("_material_mask_arm_standard_", material_payloads[0].source_path.name)
            self.assertTrue(any("generated CD runtime material mask" in warning for warning in report.warnings))
            self.assertFalse(any("standalone PBR source map" in warning for warning in report.warnings))

    def test_complete_swap_runtime_material_mask_uses_explicit_gltf_pbr_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "image0.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            submesh = SubMesh(
                name="Helmet",
                material="Helmet",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_metallicRoughnessTexture",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_type="material",
                    semantic_subtype="metallic_roughness",
                    packed_channels=("roughness", "metallic"),
                    material_name="Helmet",
                    confidence="gltf",
                ),
            )
            mesh = ParsedMesh(submeshes=[submesh])
            texture_sets = group_replacement_texture_sets((pbr_png,), obj_mesh=mesh)

            runtime_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["helmet"],
                get_complete_swap_material_profile("arm_standard"),
            )
            nonmetal_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["helmet"],
                get_complete_swap_material_profile("arm_nonmetal_matte"),
            )

            with Image.open(runtime_mask) as image:
                self.assertEqual((255, 56, 235, 0), image.convert("RGBA").getpixel((0, 0)))
            with Image.open(nonmetal_mask) as image:
                self.assertEqual((255, 56, 0, 0), image.convert("RGBA").getpixel((0, 0)))
            self.assertIn("probe_arm_standard", {variant.name for variant in complete_swap_material_probe_variants()})

    def test_material_authority_runtime_mask_uses_specular_glossiness_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            spec_gloss = root / "image0.png"
            Image.new("RGBA", (2, 2), (200, 100, 50, 220)).save(spec_gloss)
            submesh = SubMesh(
                name="AxeHead",
                material="AxeHead",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_specularGlossinessTexture",
                    source_texture_path=str(spec_gloss),
                    preview_texture_path=str(spec_gloss),
                    semantic_type="specular",
                    semantic_subtype="specular_glossiness",
                    packed_channels=("specular", "glossiness"),
                    material_name="AxeHead",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((spec_gloss,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            runtime_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["axehead"],
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(runtime_mask) as image:
                pixel = image.convert("RGBA").getpixel((0, 0))
            self.assertEqual(255, pixel[0])
            self.assertEqual(35, pixel[1])
            self.assertEqual(124, pixel[2])
            self.assertEqual(0, pixel[3])

    def test_material_authority_runtime_mask_multiplies_gltf_pbr_factors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr = root / "image0.png"
            Image.new("RGBA", (2, 2), (80, 200, 120, 255)).save(pbr)
            submesh = SubMesh(
                name="Blade",
                material="Blade",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_parameters = (
                PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_roughnessFactor", numeric_value=0.5),
                PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_metallicFactor", numeric_value=0.25),
                PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_gltfTextureStrength_occlusion", numeric_value=0.25),
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_metallicRoughnessTexture",
                    source_texture_path=str(pbr),
                    preview_texture_path=str(pbr),
                    semantic_type="material",
                    semantic_subtype="metallic_roughness",
                    packed_channels=("occlusion", "roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((pbr,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            runtime_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["blade"],
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(runtime_mask) as image:
                self.assertEqual((211, 100, 30, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_material_authority_runtime_mask_multiplies_specular_glossiness_factors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            spec_gloss = root / "image0.png"
            Image.new("RGBA", (2, 2), (200, 100, 50, 220)).save(spec_gloss)
            submesh = SubMesh(
                name="AxeHead",
                material="AxeHead",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_parameters = (
                PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_glossinessFactor", numeric_value=0.5),
                PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_specularFactor", numeric_value=0.5),
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_specularGlossinessTexture",
                    source_texture_path=str(spec_gloss),
                    preview_texture_path=str(spec_gloss),
                    semantic_type="specular",
                    semantic_subtype="specular_glossiness",
                    packed_channels=("specular", "glossiness"),
                    material_name="AxeHead",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((spec_gloss,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            runtime_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["axehead"],
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(runtime_mask) as image:
                self.assertEqual((255, 145, 62, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_gltf_specular_glossiness_slots_keep_authoritative_preview_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec_gloss = root / "axe_specularGlossiness.png"
            spec_gloss.write_bytes(b"")
            submesh = SubMesh(
                name="AxeHead",
                material="AxeHead",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_specularGlossinessTexture",
                    source_texture_path=str(spec_gloss),
                    preview_texture_path=str(spec_gloss),
                    semantic_type="specular",
                    semantic_subtype="specular_glossiness",
                    packed_channels=("specular", "glossiness"),
                    material_name="AxeHead",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((spec_gloss,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            slot = texture_sets["axehead"].slots["material"]

            self.assertEqual(spec_gloss, slot.source_path)
            self.assertEqual("specular_glossiness", slot.semantic_subtype)
            self.assertEqual(("specular", "glossiness"), slot.packed_channels)
            self.assertEqual("gltf", slot.source_authority)
            self.assertEqual(
                ("specular", "specular_glossiness", ("specular", "glossiness"), "_specularGlossinessTexture"),
                replacement_texture_slot_preview_semantics(slot, source_path=spec_gloss),
            )

    def test_gltf_color_specular_factor_maps_to_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            white_spec = root / "white_specularGlossiness.png"
            black_spec = root / "black_specularGlossiness.png"
            white_spec.write_bytes(b"")
            black_spec.write_bytes(b"")

            def make_submesh(material: str, path: Path, color: tuple[float, float, float]) -> SubMesh:
                submesh = SubMesh(
                    name=material,
                    material=material,
                    vertices=[(0.0, 0.0, 0.0)],
                    faces=[(0, 0, 0)],
                )
                submesh.preview_material_parameters = (
                    PreviewMaterialParameterInput(
                        parameter_kind="color",
                        parameter_name="_specularFactor",
                        value="#" + "".join(f"{int(component * 255):02x}" for component in color),
                        color_value=color,
                    ),
                )
                submesh.preview_material_texture_inputs = (
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_specularGlossinessTexture",
                        source_texture_path=str(path),
                        preview_texture_path=str(path),
                        semantic_type="specular",
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                        material_name=material,
                        confidence="gltf",
                    ),
                )
                return submesh

            texture_sets = group_replacement_texture_sets(
                (white_spec, black_spec),
                obj_mesh=ParsedMesh(
                    submeshes=[
                        make_submesh("WhiteSpec", white_spec, (1.0, 1.0, 1.0)),
                        make_submesh("BlackSpec", black_spec, (0.0, 0.0, 0.0)),
                    ]
                ),
            )

            self.assertAlmostEqual(1.0, texture_sets["whitespec"].specular_factor or 0.0)
            self.assertEqual(0.0, texture_sets["blackspec"].specular_factor)

    def test_material_authority_runtime_mask_uses_separate_specular_and_glossiness_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            specular = root / "tex_spec.png"
            glossiness = root / "tex_gloss.png"
            Image.new("RGBA", (2, 2), (180, 180, 180, 255)).save(specular)
            Image.new("RGBA", (2, 2), (200, 200, 200, 255)).save(glossiness)
            submesh = SubMesh(
                name="Trim",
                material="Trim",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="specular",
                    source_texture_path=str(specular),
                    preview_texture_path=str(specular),
                    semantic_subtype="specular",
                    material_name="Trim",
                    confidence="dae",
                ),
                PreviewMaterialTextureInput(
                    slot_kind="glossiness",
                    source_texture_path=str(glossiness),
                    preview_texture_path=str(glossiness),
                    semantic_subtype="glossiness",
                    material_name="Trim",
                    confidence="dae",
                ),
            )

            texture_sets = group_replacement_texture_sets((specular, glossiness), obj_mesh=ParsedMesh(submeshes=[submesh]))
            runtime_mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["trim"],
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(runtime_mask) as image:
                self.assertEqual((255, 55, 180, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_material_authority_accepts_webp_scene_texture_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "tex_0.webp"
            base.write_bytes(b"webp placeholder")
            submesh = SubMesh(
                name="ClothPanel",
                material="ClothPanel",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    source_texture_path=str(base),
                    preview_texture_path=str(base),
                    semantic_subtype="albedo",
                    material_name="ClothPanel",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((base,), obj_mesh=ParsedMesh(submeshes=[submesh]))

            self.assertEqual(base, texture_sets["clothpanel"].slots["base"].source_path)

    def test_material_authority_derives_source_role_tags_from_scene_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "oak_base.png"
            base.write_bytes(b"")
            submesh = SubMesh(
                name="PolishedOakClothGlow",
                material="PolishedOakClothGlow",
                texture=str(base),
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_roughnessFactor",
                    numeric_value=0.2,
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    numeric_value=1.0,
                ),
            )
            texture_sets = group_replacement_texture_sets((base,), obj_mesh=ParsedMesh(submeshes=[submesh]))

            tags = set(texture_sets["polishedoakclothglow"].source_role_tags)
            self.assertTrue({"wood", "cloth", "glow", "shiny"} <= tags)

    def test_global_gloss_reduction_profile_overlay_is_noop_at_zero(self) -> None:
        profile = get_complete_swap_material_profile("material_authority_true_source")

        adjusted = apply_global_gloss_reduction_to_profile(profile, 0)

        self.assertIs(adjusted, profile)

    def test_material_authority_zero_gloss_bias_is_exact_baseline(self) -> None:
        profile = get_complete_swap_material_profile("material_authority")

        adjusted = apply_global_gloss_reduction_to_profile(profile, 0)

        self.assertIs(adjusted, profile)
        self.assertEqual(0.0, adjusted.global_gloss_reduction)
        self.assertEqual(profile.roughness_default, adjusted.roughness_default)
        self.assertEqual(profile.roughness_min, adjusted.roughness_min)
        self.assertEqual(profile.roughness_scale, adjusted.roughness_scale)
        self.assertEqual(profile.roughness_max, adjusted.roughness_max)
        self.assertEqual(profile.scratch_roughness, adjusted.scratch_roughness)
        self.assertEqual(profile.shine_scalar, adjusted.shine_scalar)

    def test_global_gloss_reduction_profile_overlay_makes_material_more_matte(self) -> None:
        profile = get_complete_swap_material_profile("material_authority_true_source")

        mid = apply_global_gloss_reduction_to_profile(profile, 50)
        full = apply_global_gloss_reduction_to_profile(profile, 100)

        self.assertGreater(mid.roughness_default, profile.roughness_default)
        self.assertGreater(mid.roughness_min or 0, profile.roughness_min or 0)
        self.assertEqual(profile.metallic_default, mid.metallic_default)
        self.assertEqual(profile.metallic_scale, mid.metallic_scale)
        self.assertEqual(profile.metallic_max, mid.metallic_max)
        self.assertFalse(full.force_nonmetal)
        self.assertEqual(255, full.roughness_default)
        self.assertEqual(255, full.roughness_min)
        self.assertEqual(255, full.roughness_max)
        self.assertEqual(0, full.metallic_default)
        self.assertEqual(0.34, full.metallic_scale)
        self.assertEqual(112, full.metallic_max)
        self.assertEqual(1.0, full.scratch_roughness)
        self.assertIsNone(full.scratch_metallic)
        self.assertEqual(0.0, full.shine_scalar)
        roughness_value, metallic_value, shine_value, _source_name = _profile_scalar_values(full)
        self.assertEqual(0xFFFFFF, roughness_value)
        self.assertIsNone(metallic_value)
        self.assertEqual(0.0, shine_value)

    def test_global_gloss_boost_profile_overlay_makes_material_glossier(self) -> None:
        profile = get_complete_swap_material_profile("material_authority")

        glossy = apply_global_gloss_reduction_to_profile(profile, -100)

        self.assertLess(glossy.roughness_default, profile.roughness_default)
        self.assertLess(glossy.roughness_min or 0, profile.roughness_min or 0)
        self.assertLess(glossy.roughness_max or 255, profile.roughness_max or 255)
        self.assertLess(glossy.scratch_roughness or 0, profile.scratch_roughness or 0)
        self.assertGreater(glossy.shine_scalar or 0, profile.shine_scalar or 0)
        self.assertFalse(glossy.force_nonmetal)
        self.assertEqual(-100.0, glossy.global_gloss_reduction)

    def test_global_gloss_reduction_changes_generated_runtime_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "image0.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            submesh = SubMesh(name="Blade", material="Blade", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_subtype="metallic_roughness",
                    packed_channels=("occlusion", "roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )
            texture_sets = group_replacement_texture_sets((pbr_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            base_profile = get_complete_swap_material_profile("material_authority_clean_source")
            matte_profile = apply_global_gloss_reduction_to_profile(base_profile, 100)

            base_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], base_profile)
            matte_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], matte_profile)

            self.assertNotEqual(base_mask, matte_mask)
            with Image.open(base_mask) as image:
                base_pixel = image.convert("RGBA").getpixel((0, 0))
            with Image.open(matte_mask) as image:
                matte_pixel = image.convert("RGBA").getpixel((0, 0))
            self.assertGreater(matte_pixel[1], base_pixel[1])
            self.assertEqual(255, matte_pixel[1])
            self.assertEqual(base_pixel[2], matte_pixel[2])

    def test_global_gloss_boost_changes_generated_runtime_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "image0.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            submesh = SubMesh(name="Blade", material="Blade", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_subtype="metallic_roughness",
                    packed_channels=("occlusion", "roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )
            texture_sets = group_replacement_texture_sets((pbr_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            base_profile = get_complete_swap_material_profile("material_authority")
            glossy_profile = apply_global_gloss_reduction_to_profile(base_profile, -100)

            base_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], base_profile)
            glossy_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], glossy_profile)

            self.assertNotEqual(base_mask, glossy_mask)
            with Image.open(base_mask) as image:
                base_pixel = image.convert("RGBA").getpixel((0, 0))
            with Image.open(glossy_mask) as image:
                glossy_pixel = image.convert("RGBA").getpixel((0, 0))
            self.assertLess(glossy_pixel[1], base_pixel[1])
            self.assertEqual(24, glossy_pixel[1])
            self.assertEqual(base_pixel[2], glossy_pixel[2])

    def test_pbr_source_test_profile_keeps_source_metalness_and_raises_cd_roughness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "Blade_metallicRoughness.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            submesh = SubMesh(name="Blade", material="Blade", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_subtype="metallic_roughness",
                    packed_channels=("occlusion", "roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )
            texture_sets = group_replacement_texture_sets((pbr_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            base_profile = get_complete_swap_material_profile("material_authority_pbr_source_test")
            matte_profile = apply_global_gloss_reduction_to_profile(base_profile, 100)

            base_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], base_profile)
            matte_mask = _complete_swap_runtime_material_mask_png_path(texture_sets["blade"], matte_profile)

            self.assertEqual("true_source_authority", complete_swap_material_authority_contract(base_profile.name))
            self.assertFalse(base_profile.roughness_inverted)
            self.assertEqual(240, base_profile.roughness_min)
            self.assertEqual(255, base_profile.roughness_max)
            self.assertEqual(1.0, base_profile.scratch_roughness)
            self.assertFalse(base_profile.preserve_target_layer_response)
            self.assertFalse(base_profile.source_color_layer_authority)
            self.assertEqual("source_roughness_high", base_profile.gloss_reduction_mode)
            self.assertFalse(matte_profile.force_nonmetal)
            self.assertIsNone(matte_profile.scratch_metallic)
            roughness_value, metallic_value, shine_value, _source_name = _profile_scalar_values(
                base_profile,
                (0x383838, 0xEBEBEB, "Blade_metallicRoughness.png"),
            )
            self.assertEqual(0xFFFFFF, roughness_value)
            self.assertEqual(0xEBEBEB, metallic_value)
            self.assertEqual(0.0, shine_value)
            with Image.open(base_mask) as image:
                base_pixel = image.convert("RGBA").getpixel((0, 0))
            with Image.open(matte_mask) as image:
                matte_pixel = image.convert("RGBA").getpixel((0, 0))
            self.assertEqual((255, 240, 235, 0), base_pixel)
            self.assertEqual(255, matte_pixel[1])
            self.assertEqual(235, matte_pixel[2])

    def test_true_source_basic_gloss_overlay_changes_payload_mask_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "Blade_baseColor.png"
            pbr_png = root / "Blade_metallicRoughness.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(base_png)
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(64, 64, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_o.dds", root)
            mask_entry = _entry("character/texture/original_ma.dds", root)
            sidecar_entry = _entry("character/modelproperty/blade.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Blade",
                        material="Blade",
                        texture=str(base_png),
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", base_png), ("metallicRoughness", pbr_png))
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture" Index="1">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            def build(gloss: float) -> tuple[set[str], list[str]]:
                with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                    payloads, report = build_texture_replacement_payloads(
                        obj_mesh=mesh,
                        rebuilt_mesh=mesh,
                        texture_files=(base_png,),
                        original_texture_refs=(
                            ArchiveModelTextureReference(
                                reference_name=base_entry.path,
                                material_name="Blade",
                                sidecar_parameter_name="_overlayColorTexture",
                                resolved_archive_path=base_entry.path,
                                resolved_entry=base_entry,
                            ),
                            ArchiveModelTextureReference(
                                reference_name=mask_entry.path,
                                material_name="Blade",
                                sidecar_parameter_name="_colorBlendingMaskTexture",
                                resolved_archive_path=mask_entry.path,
                                resolved_entry=mask_entry,
                            ),
                        ),
                        original_sidecars=((sidecar_entry, sidecar_text),),
                        submesh_mappings=(StaticSubmeshMapping(0, "Blade", [0], 0),),
                        texconv_path=texconv,
                        read_original_texture_bytes=lambda _entry: template.read_bytes(),
                        original_texture_source_path=lambda _entry: template,
                        pac_driven_sidecar=True,
                        neutralize_inherited_material_layers=True,
                        complete_external_material_reset=True,
                        complete_swap_material_profile="material_authority_true_source",
                        complete_swap_global_gloss_reduction=gloss,
                    )
                return {
                    payload.target_path
                    for payload in payloads
                    if payload.kind == "texture_generated" and payload.target_path.endswith("_ma.dds")
                }, report.warnings

            default_masks, default_warnings = build(0)
            matte_masks, matte_warnings = build(100)

            self.assertTrue(default_masks)
            self.assertTrue(matte_masks)
            self.assertNotEqual(default_masks, matte_masks)
            self.assertFalse(any("Global gloss" in warning for warning in default_warnings))
            self.assertTrue(any("Global gloss reduction applied: 100%" in warning for warning in matte_warnings))
            self.assertTrue(any("Global gloss reduction channels" in warning for warning in matte_warnings))

    def test_source_brightness_control_lifts_dark_base_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (2, 1), (24, 24, 24, 255)).save(base_png)
            base_profile = get_complete_swap_material_profile("material_authority")
            profile = apply_true_source_basic_controls_to_profile(
                base_profile,
                dark_detail_lift=100,
            )
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            base_slot = next(
                slot
                for slot in _source_driven_slots(
                    texture_set,
                    include_complete_support_fallbacks=True,
                    material_profile=profile,
                )
                if slot.slot_kind == "base"
            )
            with Image.open(_source_slot_png_with_base_color_factor_path(base_slot)) as image:
                lifted_pixel = image.convert("RGB").getpixel((0, 0))

            self.assertEqual(100, profile.base_color_shadow_lift)
            self.assertLess(profile.base_color_gamma, 1.0)
            self.assertGreater(lifted_pixel[0], 24)

    def test_source_brightness_control_dims_bright_base_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (2, 1), (220, 220, 220, 255)).save(base_png)
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority"),
                dark_detail_lift=-75,
            )
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            base_slot = next(
                slot
                for slot in _source_driven_slots(
                    texture_set,
                    include_complete_support_fallbacks=True,
                    material_profile=profile,
                )
                if slot.slot_kind == "base"
            )
            with Image.open(_source_slot_png_with_base_color_factor_path(base_slot)) as image:
                dimmed_pixel = image.convert("RGB").getpixel((0, 0))

            self.assertLess(profile.base_color_scale, 1.0)
            self.assertEqual(0, profile.base_color_shadow_lift)
            self.assertLess(dimmed_pixel[0], 220)

    def test_material_authority_spec_gloss_keeps_real_diffuse_runtime_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            diffuse = root / "mango_diffuse.png"
            spec_gloss = root / "mango_specularGlossiness.png"
            Image.new("RGBA", (2, 1), (18, 16, 14, 255)).save(diffuse)
            Image.new("RGBA", (2, 1), (178, 132, 72, 220)).save(spec_gloss)
            texture_set = ReplacementTextureSet(
                "mango",
                slots={
                    "base": ReplacementTextureSlot("mango", "base", diffuse, source_authority="gltf"),
                    "material": ReplacementTextureSlot(
                        "mango",
                        "material",
                        spec_gloss,
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                        source_authority="gltf",
                    ),
                },
                specular_factor=1.0,
                glossiness_factor=1.0,
            )

            slots = _source_driven_slots(
                texture_set,
                include_pbr_material_fallback=True,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority"),
            )
            base_slot = next(slot for slot in slots if slot.slot_kind == "base")

            self.assertEqual(diffuse, base_slot.source_path)
            self.assertEqual("gltf", base_slot.source_authority)
            with Image.open(_source_slot_png_with_base_color_factor_path(base_slot)) as image:
                self.assertEqual((18, 16, 14, 255), image.convert("RGBA").getpixel((0, 0)))

    def test_material_authority_spec_gloss_routes_generated_runtime_mask_not_raw_spec_gloss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            diffuse = root / "mango_diffuse.png"
            spec_gloss = root / "mango_specularGlossiness.png"
            Image.new("RGBA", (2, 1), (18, 16, 14, 255)).save(diffuse)
            Image.new("RGBA", (2, 1), (178, 132, 72, 220)).save(spec_gloss)
            texture_set = ReplacementTextureSet(
                "mango",
                slots={
                    "base": ReplacementTextureSlot("mango", "base", diffuse, source_authority="gltf"),
                    "material": ReplacementTextureSlot(
                        "mango",
                        "material",
                        spec_gloss,
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                        source_authority="gltf",
                    ),
                },
                specular_factor=1.0,
                glossiness_factor=1.0,
            )

            slots = _source_driven_slots(
                texture_set,
                include_pbr_material_fallback=True,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority"),
            )
            material_slot = next(slot for slot in slots if slot.slot_kind == "material_mask")

            self.assertNotEqual(spec_gloss, material_slot.source_path)
            self.assertEqual("synthetic", material_slot.source_authority)
            self.assertIn("_material_mask_material_authority_detail_mask_", material_slot.source_path.name)
            with Image.open(material_slot.source_path) as image:
                self.assertNotEqual((178, 132, 72, 220), image.convert("RGBA").getpixel((0, 0)))

    def test_material_authority_black_spec_gloss_factor_keeps_runtime_base_diffuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            diffuse = root / "roca_diffuse.png"
            spec_gloss = root / "roca_specularGlossiness.png"
            Image.new("RGBA", (2, 1), (92, 86, 72, 255)).save(diffuse)
            Image.new("RGBA", (2, 1), (180, 180, 180, 220)).save(spec_gloss)
            texture_set = ReplacementTextureSet(
                "roca",
                slots={
                    "base": ReplacementTextureSlot("roca", "base", diffuse, source_authority="gltf"),
                    "material": ReplacementTextureSlot(
                        "roca",
                        "material",
                        spec_gloss,
                        semantic_subtype="specular_glossiness",
                        packed_channels=("specular", "glossiness"),
                        source_authority="gltf",
                    ),
                },
                specular_factor=0.0,
                glossiness_factor=1.0,
            )

            slots = _source_driven_slots(
                texture_set,
                include_pbr_material_fallback=True,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority"),
            )
            base_slot = next(slot for slot in slots if slot.slot_kind == "base")

            self.assertEqual(diffuse, base_slot.source_path)

    def test_auto_brightness_balance_lifts_dark_and_tames_bright_base_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            dark_png = root / "dark_baseColor.png"
            bright_png = root / "bright_baseColor.png"
            Image.new("RGBA", (4, 4), (32, 32, 32, 255)).save(dark_png)
            Image.new("RGBA", (4, 4), (230, 230, 230, 255)).save(bright_png)

            dark_slot = ReplacementTextureSlot(
                "Dark",
                "base",
                dark_png,
                base_color_auto_balance=100,
            )
            bright_slot = ReplacementTextureSlot(
                "Bright",
                "base",
                bright_png,
                base_color_auto_balance=100,
            )

            with Image.open(_source_slot_png_with_base_color_factor_path(dark_slot)) as image:
                dark_pixel = image.convert("RGB").getpixel((0, 0))
            with Image.open(_source_slot_png_with_base_color_factor_path(bright_slot)) as image:
                bright_pixel = image.convert("RGB").getpixel((0, 0))

            self.assertGreater(dark_pixel[0], 32)
            self.assertLess(bright_pixel[0], 230)

    def test_auto_brightness_control_marks_profile_for_base_slot_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (2, 1), (230, 230, 230, 255)).save(base_png)
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority"),
                auto_brightness_balance=75,
            )
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            base_slot = next(
                slot
                for slot in _source_driven_slots(
                    texture_set,
                    include_complete_support_fallbacks=True,
                    material_profile=profile,
                )
                if slot.slot_kind == "base"
            )

            self.assertEqual(75, profile.base_color_auto_balance)
            self.assertEqual(75, base_slot.base_color_auto_balance)
            self.assertTrue(_source_slot_needs_base_color_adjustment(base_slot))

    def test_tone_contrast_control_adjusts_base_color_both_directions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            image = Image.new("RGBA", (2, 1))
            image.putdata([(64, 64, 64, 255), (192, 192, 192, 255)])
            image.save(base_png)

            def adjusted_pixels(tone_contrast: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
                profile = apply_true_source_basic_controls_to_profile(
                    get_complete_swap_material_profile("material_authority"),
                    tone_contrast=tone_contrast,
                )
                texture_set = ReplacementTextureSet(
                    "Blade",
                    slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
                )
                base_slot = next(
                    slot
                    for slot in _source_driven_slots(
                        texture_set,
                        include_complete_support_fallbacks=True,
                        material_profile=profile,
                    )
                    if slot.slot_kind == "base"
                )
                self.assertEqual(float(tone_contrast), profile.base_color_tone_contrast)
                with Image.open(_source_slot_png_with_base_color_factor_path(base_slot)) as adjusted:
                    rgb = adjusted.convert("RGB")
                    return rgb.getpixel((0, 0)), rgb.getpixel((1, 0))

            positive = adjusted_pixels(100)
            negative = adjusted_pixels(-100)

            original_gap = 192 - 64
            positive_gap = positive[1][0] - positive[0][0]
            negative_gap = negative[1][0] - negative[0][0]
            self.assertGreater(positive_gap, original_gap)
            self.assertLess(negative_gap, original_gap)
            self.assertNotEqual(positive, negative)

    def test_material_authority_brightness_repro_builds_adjusted_base_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            image = Image.new("RGBA", (2, 1))
            image.putdata([(32, 32, 32, 255), (120, 120, 120, 255)])
            image.save(base_png)
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority"),
                auto_brightness_balance=30,
                dark_detail_lift=100,
                tone_contrast=10,
            )
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            base_slot = next(
                slot
                for slot in _source_driven_slots(
                    texture_set,
                    include_complete_support_fallbacks=True,
                    material_profile=profile,
                )
                if slot.slot_kind == "base"
            )

            self.assertEqual(30, profile.base_color_auto_balance)
            self.assertEqual(100, profile.base_color_shadow_lift)
            self.assertEqual(10.0, profile.base_color_tone_contrast)
            adjusted_path = _source_slot_png_with_base_color_factor_path(base_slot)
            self.assertNotEqual(base_png, adjusted_path)
            with Image.open(adjusted_path) as adjusted:
                adjusted_pixel = adjusted.convert("RGB").getpixel((0, 0))
            self.assertGreater(adjusted_pixel[0], 32)

    def test_material_authority_preview_helper_uses_adjusted_base_and_emissive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            emissive_png = root / "Blade_emissive.png"
            Image.new("RGBA", (2, 1), (32, 32, 32, 255)).save(base_png)
            Image.new("RGBA", (2, 1), (200, 180, 120, 255)).save(emissive_png)
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={
                    "base": ReplacementTextureSlot("Blade", "base", base_png),
                    "emissive": ReplacementTextureSlot("Blade", "emissive", emissive_png),
                },
            )
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_true_source"),
                auto_brightness_balance=30,
                dark_detail_lift=100,
                tone_contrast=10,
                accent_glow_strength=100,
            )

            slots = material_authority_preview_texture_slots(texture_set, profile)

            self.assertNotEqual(base_png, slots["base"].source_path)
            self.assertNotEqual(emissive_png, slots["emissive"].source_path)
            self.assertTrue(slots["base"].source_path.is_file())
            self.assertTrue(slots["emissive"].source_path.is_file())
            with Image.open(slots["base"].source_path) as adjusted_base:
                self.assertGreater(adjusted_base.convert("RGB").getpixel((0, 0))[0], 32)
            with Image.open(slots["emissive"].source_path) as adjusted_emissive:
                self.assertLessEqual(max(adjusted_emissive.convert("RGB").getpixel((0, 0))), 72)

    def test_material_authority_preview_helper_synthesizes_accent_glow_emissive(self) -> None:
        texture_set = ReplacementTextureSet(
            "Gem_inside",
            base_color_factor=(1.0, 0.0, 0.0),
            source_face_count=128,
        )
        profile = apply_true_source_basic_controls_to_profile(
            get_complete_swap_material_profile("material_authority_detail_mask"),
            accent_glow_strength=100,
        )

        slots = material_authority_preview_texture_slots(texture_set, profile)

        self.assertIn("emissive", slots)
        self.assertEqual("emissive", slots["emissive"].slot_kind)
        self.assertEqual("synthetic_accent_glow", slots["emissive"].source_authority)
        self.assertIn("accent_emissive", slots["emissive"].source_path.name)
        self.assertTrue(slots["emissive"].source_path.is_file())

    def test_material_authority_preview_helper_does_not_clone_real_base_as_accent_glow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Gem_outside_baseColor.png"
            Image.new("RGBA", (2, 2), (226, 190, 72, 255)).save(base_png)
            texture_set = ReplacementTextureSet(
                "Gem_outside",
                slots={
                    "base": ReplacementTextureSlot(
                        "Gem_outside",
                        "base",
                        base_png,
                        semantic_subtype="albedo",
                        source_authority="gltf",
                    )
                },
                source_face_count=128,
            )
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_detail_mask"),
                accent_glow_strength=100,
            )

            slots = material_authority_preview_texture_slots(texture_set, profile)

            self.assertIn("base", slots)
            self.assertNotIn("emissive", slots)

    def test_material_authority_preview_helper_disabled_returns_original_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (2, 1), (32, 32, 32, 255)).save(base_png)
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_true_source"),
                dark_detail_lift=100,
                tone_contrast=50,
            )

            slots = material_authority_preview_texture_slots(texture_set, profile, enabled=False)

            self.assertEqual(base_png, slots["base"].source_path)
            self.assertNotIn("material_mask", slots)

    def test_material_authority_preview_helper_gloss_bias_changes_material_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            roughness_png = root / "Blade_roughness.png"
            Image.new("RGBA", (4, 4), (96, 96, 96, 255)).save(roughness_png)
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"roughness": ReplacementTextureSlot("Blade", "roughness", roughness_png)},
            )
            base_profile = get_complete_swap_material_profile("material_authority_detail_mask")
            matte_profile = apply_global_gloss_reduction_to_profile(base_profile, 100)

            base_mask = material_authority_preview_texture_slots(texture_set, base_profile)["material_mask"].source_path
            matte_mask = material_authority_preview_texture_slots(texture_set, matte_profile)["material_mask"].source_path

            self.assertNotEqual(base_mask, matte_mask)
            self.assertNotEqual(base_mask.read_bytes(), matte_mask.read_bytes())

    def test_material_authority_preview_helper_returns_detail_mask_support_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (4, 4), (64, 64, 64, 255)).save(base_png)
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_true_source"),
                edge_relief_strength=100,
                edge_relief_source="generate_source",
            )

            slots = material_authority_preview_texture_slots(texture_set, profile)

            self.assertIn("detail_mask", slots)
            self.assertEqual("detail_mask", slots["detail_mask"].slot_kind)
            self.assertTrue(slots["detail_mask"].source_path.is_file())

    def test_edge_relief_generate_source_adds_height_and_detail_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Blade_baseColor.png"
            Image.new("RGBA", (4, 4), (16, 16, 16, 255)).save(base_png)
            texture_set = ReplacementTextureSet(
                "Blade",
                slots={"base": ReplacementTextureSlot("Blade", "base", base_png)},
            )
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_true_source"),
                edge_relief_strength=100,
                edge_relief_source="generate_source",
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=profile,
            )
            slot_kinds = {slot.slot_kind for slot in slots}

            self.assertIn("height", slot_kinds)
            self.assertIn("detail_mask", slot_kinds)
            self.assertTrue(any("edge_relief" in slot.source_path.name for slot in slots if slot.slot_kind == "height"))

    def test_gloss_reduction_scalar_patch_updates_existing_gloss_like_params(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material>'
            '<Vector Name="_parameters">'
            '<MaterialParameterFloat _name="_glossiness" _value="0.900000" Index="0"/>'
            '<MaterialParameterFloat _name="_smoothness" _value="0.800000" Index="1"/>'
            '<MaterialParameterFloat _name="_specularScale" _value="0.700000" Index="2"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, edited = _apply_source_pbr_scalar_parameters(
            sidecar_text,
            material_names=("Blade",),
            roughness_value=0xFFFFFF,
            metallic_value=0,
            shine_value=0.0,
        )

        self.assertEqual(1, edited)
        self.assertIn('_name="_glossiness" _value="0.000000"', patched)
        self.assertIn('_name="_smoothness" _value="0.000000"', patched)
        self.assertIn('_name="_specularScale" _value="0.000000"', patched)

    def test_complete_swap_profiles_write_distinct_runtime_masks_and_probe_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "image0.png"
            ao_png = root / "ao.png"
            Image.new("RGBA", (2, 2), (24, 56, 235, 255)).save(pbr_png)
            Image.new("RGBA", (2, 2), (33, 33, 33, 255)).save(ao_png)
            submesh = SubMesh(name="Blade", material="Blade", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_subtype="metallic_roughness",
                    packed_channels=("roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
                PreviewMaterialTextureInput(
                    slot_kind="ao",
                    source_texture_path=str(ao_png),
                    preview_texture_path=str(ao_png),
                    semantic_subtype="occlusion",
                    packed_channels=("ao",),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )
            texture_sets = group_replacement_texture_sets((pbr_png, ao_png), obj_mesh=ParsedMesh(submeshes=[submesh]))

            pixels = {}
            for profile_name in (
                "arm_standard",
                "rma_standard",
                "mra_standard",
                "arm_gloss",
                "arm_metal_invert",
                "arm_ao_white",
                "arm_nonmetal_matte",
            ):
                mask = _complete_swap_runtime_material_mask_png_path(
                    texture_sets["blade"],
                    get_complete_swap_material_profile(profile_name),
                )
                with Image.open(mask) as image:
                    pixels[profile_name] = image.convert("RGBA").getpixel((0, 0))

            self.assertEqual((33, 56, 235, 0), pixels["arm_standard"])
            self.assertEqual((56, 235, 33, 0), pixels["rma_standard"])
            self.assertEqual((235, 56, 33, 0), pixels["mra_standard"])
            self.assertEqual((33, 199, 235, 0), pixels["arm_gloss"])
            self.assertEqual((33, 56, 20, 0), pixels["arm_metal_invert"])
            self.assertEqual((255, 56, 235, 0), pixels["arm_ao_white"])
            self.assertEqual((33, 56, 0, 0), pixels["arm_nonmetal_matte"])

            manifests = write_complete_swap_material_probe_manifests(root / "probes")
            self.assertEqual(len(complete_swap_material_probe_variants()), len(manifests))
            data = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual("wolf_gravestone_sword_free (1).zip", data["source_package"])
            self.assertIn("material_profile", data)

    def test_complete_swap_runtime_mask_reads_packed_occlusion_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            pbr_png = root / "image0.png"
            Image.new("RGBA", (1, 1), (24, 56, 235, 255)).save(pbr_png)
            submesh = SubMesh(name="Blade", material="Blade", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
            submesh.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=str(pbr_png),
                    preview_texture_path=str(pbr_png),
                    semantic_subtype="metallic_roughness",
                    packed_channels=("occlusion", "roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets((pbr_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            mask = _complete_swap_runtime_material_mask_png_path(
                texture_sets["blade"],
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(mask) as image:
                self.assertEqual((24, 56, 235, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_complete_swap_runtime_mask_reads_direct_occlusion_slot_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            occlusion = root / "occlusion.png"
            Image.new("RGBA", (1, 1), (41, 41, 41, 255)).save(occlusion)
            texture_set = ReplacementTextureSet(
                material_name="Blade",
                slots={
                    "occlusion": ReplacementTextureSlot(
                        material_name="Blade",
                        slot_kind="occlusion",
                        source_path=occlusion,
                        source_authority="gltf",
                    )
                },
            )

            mask = _complete_swap_runtime_material_mask_png_path(
                texture_set,
                get_complete_swap_material_profile("arm_standard"),
            )

            with Image.open(mask) as image:
                self.assertEqual((41, 192, 0, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_profile_scalars_insert_scratch_and_sheen_parameters(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Blade">
    <Material><Vector Name="_parameters"></Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""
        profile = get_complete_swap_material_profile("arm_nonmetal_matte")
        roughness_value, metallic_value, shine_value, _source_name = _profile_scalar_values(profile)

        patched, changed = _apply_source_pbr_scalar_parameters(
            sidecar_text,
            material_names=("Blade",),
            roughness_value=roughness_value,
            metallic_value=metallic_value,
            shine_value=shine_value,
        )

        self.assertEqual(1, changed)
        self.assertIn('_name="_scratchRoughness"', patched)
        self.assertIn('_name="_scratchMetallic"', patched)
        self.assertIn('_name="_sheen"', patched)
        self.assertIn('_value="0.200000"', patched)

    def test_calibrated_profile_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "complete_swap_material_profile.json"

            write_complete_swap_calibrated_material_profile(profile_path, "arm_nonmetal_matte")
            loaded = read_complete_swap_calibrated_material_profile(profile_path)

            self.assertEqual("arm_nonmetal_matte", loaded.name)
            self.assertEqual(0.20, loaded.shine_scalar)

    def test_real_probe_package_helper_writes_payloads_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_zip = root / "wolf_gravestone_sword_free (1).zip"
            source_zip.write_bytes(b"source wolf package")

            def build_payloads(variant):
                profile = get_complete_swap_material_profile(variant.material_profile_name)
                mask = bytes([profile.ao_default & 0xFF, profile.roughness_default & 0xFF, profile.metallic_default & 0xFF])
                return (
                    TextureReplacementPayload("character/cd_phm_02_sword_0039.pac", b"same geometry", "mesh_generated", Path("mesh.pac")),
                    TextureReplacementPayload(f"character/texture/cd_phm_02_sword_0039_{profile.name}_ma.dds", b"DDS" + mask, "texture_generated", Path("ma.dds")),
                    TextureReplacementPayload("character/cd_phm_02_sword_0039.pac_xml", b"<Root/>", "sidecar_generated", Path("sidecar.pac_xml")),
                )

            result = write_complete_swap_material_probe_packages(
                root / "probe_packages",
                source_package_path=source_zip,
                target_pac_path="character/cd_phm_02_sword_0039.pac",
                build_variant_payloads=build_payloads,
            )

            self.assertEqual(len(complete_swap_material_probe_variants()), len(result.variant_dirs))
            manifest = json.loads(result.manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(source_zip.as_posix(), manifest["source_package"])
            self.assertEqual("character/cd_phm_02_sword_0039.pac", manifest["target_pac_path"])
            self.assertIn("source_package_sha256", manifest)
            self.assertTrue((result.variant_dirs[0] / "files" / "character" / "cd_phm_02_sword_0039.pac").is_file())

    def test_real_probe_package_helper_fails_when_source_zip_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(FileNotFoundError):
                write_complete_swap_material_probe_packages(
                    root / "probe_packages",
                    source_package_path=root / "wolf_gravestone_sword_free (1).zip",
                    build_variant_payloads=lambda _variant: (),
                )

    def test_gltf_base_texture_is_multiplied_by_base_color_factor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "image0.png"
            Image.new("RGBA", (1, 1), (100, 200, 50, 255)).save(base_png)
            submesh = SubMesh(
                name="Blade",
                material="Blade",
                texture=str(base_png),
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_color = (0.5, 0.25, 1.0)

            texture_sets = group_replacement_texture_sets((base_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            base_slot = texture_sets["blade"].slots["base"]
            factored = _source_slot_png_with_base_color_factor_path(base_slot)

            with Image.open(factored) as image:
                self.assertEqual((50, 50, 50, 255), image.convert("RGBA").getpixel((0, 0)))

    def test_gltf_base_texture_is_multiplied_by_vertex_color_and_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "image0.png"
            Image.new("RGBA", (1, 1), (100, 200, 50, 200)).save(base_png)
            submesh = SubMesh(
                name="Blade",
                material="Blade",
                texture=str(base_png),
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.preview_color = (0.5, 1.0, 0.8)
            submesh.preview_vertex_color_mean = (0.5, 0.25, 1.0)
            submesh.preview_vertex_alpha_mean = 0.5

            texture_sets = group_replacement_texture_sets((base_png,), obj_mesh=ParsedMesh(submeshes=[submesh]))
            base_slot = texture_sets["blade"].slots["base"]
            factored = _source_slot_png_with_base_color_factor_path(base_slot)

            with Image.open(factored) as image:
                self.assertEqual((25, 50, 40, 100), image.convert("RGBA").getpixel((0, 0)))

    def test_mesh_clone_preserves_imported_material_contract_for_complete_swap(self) -> None:
        source = SubMesh(
            name="Helmet",
            material="Helmet",
            texture="Helmet_baseColor.png",
            vertices=[(0.0, 0.0, 0.0)],
            faces=[(0, 0, 0)],
        )
        source.texture_slots = (
            ("base", Path("Helmet_baseColor.png")),
            ("metallicRoughness", Path("Helmet_metallicRoughness.png")),
        )
        source.preview_vertex_color_mean = (0.9, 0.6, 0.3)
        source.preview_vertex_alpha_mean = 0.5
        source.preview_vertex_alpha_min = 0.25
        source.preview_vertex_color_count = 3
        source.preview_material_texture_inputs = ("material contract marker",)
        mesh = ParsedMesh(submeshes=[source])

        cloned = clone_mesh_for_editing(mesh)

        self.assertEqual(source.texture_slots, getattr(cloned.submeshes[0], "texture_slots", ()))
        self.assertEqual(
            source.preview_material_texture_inputs,
            getattr(cloned.submeshes[0], "preview_material_texture_inputs", ()),
        )
        self.assertEqual(source.preview_vertex_color_mean, getattr(cloned.submeshes[0], "preview_vertex_color_mean", ()))
        self.assertEqual(source.preview_vertex_alpha_mean, getattr(cloned.submeshes[0], "preview_vertex_alpha_mean", None))
        self.assertEqual(source.preview_vertex_alpha_min, getattr(cloned.submeshes[0], "preview_vertex_alpha_min", None))
        self.assertEqual(source.preview_vertex_color_count, getattr(cloned.submeshes[0], "preview_vertex_color_count", 0))

    def test_complete_external_swap_generates_base_dds_from_gltf_base_color_factor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Gem_outside",
                        material="Gem_outside",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].preview_color = (1.0, 0.0, 0.0)
            texture_sets = group_replacement_texture_sets((), obj_mesh=mesh)
            self.assertIn("base", texture_sets["gem_outside"].slots)

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Gem_outside"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="Gem_outside",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(
                        StaticSubmeshMapping(0, "Gem_outside", [0], 0),
                    ),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("gem_outside_base", patched.lower())
            self.assertTrue(any(mapping.source_material_name == "Gem_outside" for mapping in report.slot_mappings))

    def test_complete_external_swap_generates_emissive_dds_from_gltf_emissive_factor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Gem_inside",
                        material="Gem_inside",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].preview_material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_emissiveColor",
                    value="#ff0000",
                    color_value=(1.0, 0.0, 0.0),
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    value="10.000000",
                    numeric_value=10.0,
                ),
            )
            texture_sets = group_replacement_texture_sets((), obj_mesh=mesh)
            self.assertIn("emissive", texture_sets["gem_inside"].slots)

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Gem_inside"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="Gem_inside",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(
                        StaticSubmeshMapping(0, "Gem_inside", [0], 0),
                    ),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="arm_emissive",
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("_emissiveIntensityTexture", patched)
            self.assertIn("gem_inside_emissive", patched.lower())
            self.assertIn("_emissiveColor", patched)
            self.assertIn("#FF0000FF", patched)
            self.assertNotIn("#FFFF0000", patched)
            self.assertTrue(any(mapping.slot_kind == "emissive" for mapping in report.slot_mappings))

    def test_accent_glow_control_synthesizes_emissive_for_gem_part(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Gem_inside",
                        material="Gem_inside",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].preview_color = (1.0, 0.0, 0.0)

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Gem_inside"><Material _materialName="SkinnedMeshStandard_Ver2">'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="Gem_inside",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "Gem_inside", [0], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_detail_mask",
                    complete_swap_accent_glow_strength=100,
                )

        sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
        patched = sidecar_payload.payload_data.decode("utf-8")
        self.assertIn('SkinnedMeshEmissive_Ver2', patched)
        self.assertIn("_emissiveIntensityTexture", patched)
        self.assertIn("_emissiveColor", patched)
        self.assertIn("#FF0000FF", patched)
        self.assertNotIn("#FFFF0000", patched)
        self.assertIn("_emissiveIntensity", patched)
        self.assertIn("5.500000", patched)
        self.assertTrue(any(mapping.slot_kind == "emissive" for mapping in report.slot_mappings))

    def test_accent_glow_control_does_not_bind_real_base_texture_as_emissive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_png = root / "Gem_outside_baseColor.png"
            Image.new("RGBA", (4, 4), (226, 190, 72, 255)).save(base_png)
            base_entry = _entry("character/texture/original_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(
                        name="Gem_outside",
                        material="Gem_outside",
                        texture=str(base_png),
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ]
            )
            mesh.submeshes[0].preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    source_texture_path=str(base_png),
                    preview_texture_path=str(base_png),
                    semantic_subtype="albedo",
                    material_name="Gem_outside",
                    confidence="gltf",
                ),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Gem_outside"><Material _materialName="SkinnedMeshStandard_Ver2">'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/>'
                '</MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=mesh,
                    texture_files=(base_png,),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="Gem_outside",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "Gem_outside", [0], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_detail_mask",
                    complete_swap_accent_glow_strength=100,
                )

        sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
        patched = sidecar_payload.payload_data.decode("utf-8")
        self.assertIn("gem_outside_basecolor", patched.lower())
        self.assertNotIn("_emissiveIntensityTexture", patched)
        self.assertNotIn("_emissiveColor", patched)
        self.assertNotIn("_emissiveIntensity", patched)
        self.assertFalse(any(mapping.slot_kind == "emissive" for mapping in report.slot_mappings))
        self.assertIn("Accent glow skipped for Gem_outside", "\n".join(report.warnings))

    def test_accent_glow_detects_saturated_factor_shell_parts(self) -> None:
        texture_set = ReplacementTextureSet(
            material_name="Outside",
            base_color_factor=(0.0, 0.05, 1.0),
            source_face_count=1648,
        )
        texture_set.slots["base"] = ReplacementTextureSlot(
            material_name="Outside",
            slot_kind="base",
            source_path=Path("outside_base.png"),
            source_authority="synthetic",
            base_color_factor=(0.0, 0.05, 1.0),
        )

        self.assertTrue(_texture_set_is_accent_glow_candidate(texture_set, "cd_phm_02_sword_handle_0015"))

        texture_set.source_face_count = 12000
        self.assertFalse(_texture_set_is_accent_glow_candidate(texture_set, "cd_phm_02_sword_handle_0015"))

    def test_source_part_glow_role_forces_accent_candidate(self) -> None:
        texture_set = ReplacementTextureSet(
            material_name="plain_panel",
            base_color_factor=(0.35, 0.35, 0.35),
            source_face_count=12000,
        )
        texture_sets = {"plain_panel": texture_set}
        mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="PartA",
                    material="plain_panel",
                    faces=[(0, 1, 2)] * 12000,
                )
            ]
        )

        self.assertFalse(_texture_set_is_accent_glow_candidate(texture_set, "cd_phm_02_sword_blade_0015"))

        _apply_source_part_role_overrides(
            texture_sets,
            mesh,
            [StaticSourcePartAdjustment(source_submesh_index=0, material_role="glow")],
        )

        self.assertIn("glow", texture_set.source_role_tags)
        self.assertTrue(_texture_set_is_accent_glow_candidate(texture_set, "cd_phm_02_sword_blade_0015"))

    def test_accent_glow_zero_suppresses_source_emissive_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            emissive_png = Path(temp_dir) / "def_cloud_001_emissive.png"
            Image.new("RGBA", (2, 2), (0, 255, 128, 255)).save(emissive_png)
            texture_set = ReplacementTextureSet(
                material_name="def_cloud_001",
                slots={
                    "emissive": ReplacementTextureSlot(
                        material_name="def_cloud_001",
                        slot_kind="emissive",
                        source_path=emissive_png,
                    )
                },
            )

            off_profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority"),
                accent_glow_strength=0,
            )
            on_profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority"),
                accent_glow_strength=100,
            )

            self.assertFalse(any(slot.slot_kind == "emissive" for slot in _source_driven_slots(texture_set, material_profile=off_profile)))
            self.assertTrue(any(slot.slot_kind == "emissive" for slot in _source_driven_slots(texture_set, material_profile=on_profile)))

    def test_source_part_glow_role_can_override_emissive_color(self) -> None:
        from PIL import Image

        texture_set = ReplacementTextureSet(
            material_name="plain_gem",
            base_color_factor=(0.35, 0.35, 0.35),
            source_face_count=12000,
        )
        texture_sets = {"plain_gem": texture_set}
        mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="Gem",
                    material="plain_gem",
                    faces=[(0, 1, 2)] * 12000,
                )
            ]
        )

        _apply_source_part_role_overrides(
            texture_sets,
            mesh,
            [
                StaticSourcePartAdjustment(
                    source_submesh_index=0,
                    material_role="glow",
                    emissive_color_rgb=(0, 128, 255),
                )
            ],
        )

        profile = apply_true_source_basic_controls_to_profile(
            get_complete_swap_material_profile("material_authority"),
            accent_glow_strength=100,
        )
        emissive_slot = _complete_swap_accent_emissive_slot(texture_set, "cd_phm_02_sword_blade_0015", profile)

        self.assertIsNotNone(emissive_slot)
        self.assertEqual((0.0, 128.0 / 255.0, 1.0), texture_set.accent_glow_color_rgb)
        self.assertEqual("#0080FFFF", _texture_set_accent_glow_color_hex(texture_set, emissive_slot))
        with Image.open(emissive_slot.source_path) as image:  # type: ignore[union-attr]
            pixel = image.convert("RGB").getpixel((0, 0))
        self.assertEqual((0, 128, 255), pixel)

        with tempfile.TemporaryDirectory() as temp_dir:
            emissive_png = Path(temp_dir) / "existing_emissive.png"
            Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(emissive_png)
            existing_set = ReplacementTextureSet(
                material_name="existing_gem",
                slots={
                    "emissive": ReplacementTextureSlot(
                        material_name="existing_gem",
                        slot_kind="emissive",
                        source_path=emissive_png,
                    )
                },
            )
            existing_sets = {"existing_gem": existing_set}
            existing_mesh = ParsedMesh(
                submeshes=[SubMesh(name="Gem", material="existing_gem", faces=[(0, 1, 2)])]
            )
            _apply_source_part_role_overrides(
                existing_sets,
                existing_mesh,
                [
                    StaticSourcePartAdjustment(
                        source_submesh_index=0,
                        material_role="glow",
                        emissive_color_rgb=(255, 64, 0),
                    )
                ],
            )
            existing_slot = _complete_swap_accent_emissive_slot(
                existing_set,
                "cd_phm_02_sword_blade_0015",
                profile,
            )
            tinted_path = _source_slot_png_with_base_color_factor_path(existing_slot)  # type: ignore[arg-type]
            with Image.open(tinted_path) as image:
                pixel = image.convert("RGB").getpixel((0, 0))
            self.assertEqual((255, 64, 0), pixel)

    def test_emissive_factor_material_uses_base_factor_not_emissive_as_base(self) -> None:
        from PIL import Image

        mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="Gem_inside",
                    material="Gem_inside",
                    vertices=[(0.0, 0.0, 0.0)],
                    faces=[(0, 0, 0)],
                )
            ]
        )
        mesh.submeshes[0].preview_color = (0.0, 1.0, 0.7)
        mesh.submeshes[0].preview_material_parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_emissiveColor",
                color_value=(1.0, 0.0, 0.0),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name="_emissiveIntensity",
                numeric_value=4.0,
            ),
        )

        texture_sets = group_replacement_texture_sets((), obj_mesh=mesh)
        base_slot = texture_sets["gem_inside"].slots["base"]
        self.assertIn("emissive", texture_sets["gem_inside"].slots)
        with Image.open(base_slot.source_path) as image:
            self.assertEqual((0, 255, 178, 255), image.convert("RGBA").getpixel((0, 0)))

    def test_source_driven_inserted_overlay_uses_runtime_overlay_item_id(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Gem">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_normalTexture" ItemID="6" _name="_normalTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_n.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {"Gem": (("_overlayColorTexture", "character/texture/new_base.dds", "base"),)},
            exact_only=True,
        )

        self.assertEqual(1, changed_count)
        self.assertIn("character/texture/new_base.dds", used_paths)
        self.assertIn('StringItemID="_overlayColorTexture" ItemID="1"', patched)

    def test_source_driven_existing_overlay_item_id_stays_runtime_overlay_id(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Gem">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="1" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_base.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {"Gem": (("_overlayColorTexture", "character/texture/new_base.dds", "base"),)},
            exact_only=True,
        )

        self.assertEqual(1, changed_count)
        self.assertIn("character/texture/new_base.dds", used_paths)
        self.assertIn('StringItemID="_overlayColorTexture" ItemID="1"', patched)
        self.assertNotIn('ItemID="3936485985222654"', patched)

    def test_source_driven_base_and_material_mask_use_distinct_runtime_item_ids(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Gem">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="3936485985222654" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_base.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_ma.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "Gem": (
                    ("_overlayColorTexture", "character/texture/new_base.dds", "base"),
                    ("_colorBlendingMaskTexture", "character/texture/new_ma.dds", "material_mask"),
                )
            },
            exact_only=True,
        )

        self.assertEqual(1, changed_count)
        self.assertEqual({"character/texture/new_base.dds", "character/texture/new_ma.dds"}, used_paths)
        self.assertIn('StringItemID="_overlayColorTexture" ItemID="1"', patched)
        self.assertIn('StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654"', patched)

    def test_visible_gem_sensitive_wrappers_include_blade_when_gem_pac_is_present(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture _name="_overlayColorTexture">
        <ResourceReferencePath_ITexture _path="character/texture/cd_phm_02_sword_0015_lambert1_basecolor.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
  <SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Sword_Handle_0015">
    <Material><Vector Name="_parameters">
      <MaterialParameterColor _name="_emissiveColor" _value="#FF0000FF"/>
      <MaterialParameterTexture _name="_emissiveIntensityTexture">
        <ResourceReferencePath_ITexture _path="character/texture/cd_phm_02_sword_0015_gem_inside_emissive_emi.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        risky = _visible_gem_sensitive_wrappers_touched(
            sidecar_text,
            ("CD_PHM_02_Blade_0015", "CD_PHM_02_Sword_Guard_0015", "CD_PHM_02_Boot_0015"),
        )

        self.assertEqual(("CD_PHM_02_Blade_0015", "CD_PHM_02_Sword_Guard_0015"), risky)

    def test_visible_gem_sensitive_wrappers_ignore_non_gem_sidecars(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture _name="_overlayColorTexture">
        <ResourceReferencePath_ITexture _path="character/texture/cd_phm_02_sword_0015_lambert1_basecolor.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        self.assertEqual((), _visible_gem_sensitive_wrappers_touched(sidecar_text, ("CD_PHM_02_Blade_0015",)))

    def test_material_authority_detail_mask_routes_source_mask_through_detail_slot(self) -> None:
        profile = get_complete_swap_material_profile("material_authority_detail_mask")
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Gem">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="1" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_base.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654" _name="_colorBlendingMaskTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_ma.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_detailMaskTexture" ItemID="2838988925698046" _name="_detailMaskTexture" Index="2">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_mg.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "Gem": (
                    (_source_driven_parameter_name("base", material_profile=profile), "character/texture/new_base.dds", "base"),
                    (_source_driven_parameter_name("material_mask", material_profile=profile), "character/texture/new_ma.dds", "material_mask"),
                )
            },
            exact_only=True,
            insert_missing_slots=True,
            material_profile=profile,
        )

        self.assertEqual(1, changed_count)
        self.assertEqual({"character/texture/new_base.dds", "character/texture/new_ma.dds"}, used_paths)
        self.assertIn('StringItemID="_overlayColorTexture" ItemID="3936485985222654"', patched)
        self.assertIn('StringItemID="_detailMaskTexture" ItemID="2838988925698046"', patched)
        self.assertIn("character/texture/new_ma.dds", patched)
        self.assertNotIn("_colorBlendingMaskTexture", patched)
        self.assertNotIn("old_mg.dds", patched)

    def test_material_authority_placeholder_safe_test_leaves_empty_runtime_slots_unpatched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            Image.new("RGB", (8, 8), (80, 64, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            Image.new("RGB", (8, 8), (255, 128, 0)).save(pbr_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name=material_name,
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for material_name in ("CD_PHM_02_Blade_0015", "CD_PHM_02_Acc_0015")
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            wrapper_body = (
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                "</Vector></Material>"
            )
            sidecar_text = (
                '<ModelPropertyList><ModelProperty><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="200">'
                f'<SkinnedMeshMaterialWrapper ItemID="199" _subMeshName="CD_PHM_02_Blade_0015">{wrapper_body}</SkinnedMeshMaterialWrapper>'
                f'<SkinnedMeshMaterialWrapper ItemID="200" _subMeshName="CD_PHM_02_Acc_0015">{wrapper_body}</SkinnedMeshMaterialWrapper>'
                "</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (
                ("base", base_png),
                ("normal", normal_png),
                ("metallicRoughness", pbr_png),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                            SubMesh(name="CD_PHM_02_Acc_0015", material="CD_PHM_02_Acc_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png, pbr_png),
                    original_texture_refs=refs,
                    original_sidecars=((_entry("character/modelproperty/test.pac_xml", root), sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_placeholder_safe_test",
                    complete_swap_accent_glow_strength=100.0,
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                        StaticOutputDrawSection(1, 1, "CD_PHM_02_Acc_0015", [], 1, 1, "CD_PHM_02_Acc_0015", 0, False),
                    ),
                )

            self.assertFalse(report.errors)
            patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            blade_block = patched[patched.index('_subMeshName="CD_PHM_02_Blade_0015"') : patched.index('_subMeshName="CD_PHM_02_Acc_0015"')]
            acc_block = patched[patched.index('_subMeshName="CD_PHM_02_Acc_0015"') :]
            self.assertIn("lambert1_basecolor", blade_block.lower())
            self.assertIn("lambert1_material_mask_material_authority_placeholder_safe_test", blade_block.lower())
            self.assertIn("original_base.dds", acc_block)
            self.assertIn("original_ma.dds", acc_block)
            self.assertNotIn("lambert1_basecolor", acc_block.lower())
            self.assertNotIn("_emissiveIntensity", acc_block)
            self.assertTrue(any("runtime placeholder material wrapper" in warning for warning in report.warnings))

    def test_complete_swap_inserts_missing_generated_support_slots(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Gem">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="1" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_base.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "Gem": (
                    ("_overlayColorTexture", "character/texture/new_base.dds", "base"),
                    ("_normalTexture", "character/texture/new_n.dds", "normal"),
                    ("_colorBlendingMaskTexture", "character/texture/new_ma.dds", "material_mask"),
                    ("_detailMaskTexture", "character/texture/new_mg.dds", "detail_mask"),
                )
            },
            exact_only=True,
            insert_missing_slots=True,
        )

        self.assertEqual(1, changed_count)
        self.assertEqual(
            {
                "character/texture/new_base.dds",
                "character/texture/new_n.dds",
                "character/texture/new_ma.dds",
                "character/texture/new_mg.dds",
            },
            used_paths,
        )
        self.assertIn('StringItemID="_normalTexture" ItemID="6"', patched)
        self.assertIn('StringItemID="_colorBlendingMaskTexture" ItemID="3936485985222654"', patched)
        self.assertIn('StringItemID="_detailMaskTexture" ItemID="2838988925698046"', patched)

    def test_complete_external_swap_routes_gltf_factor_materials_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lambert_base = root / "lambert1_baseColor.png"
            lambert_normal = root / "lambert1_normal.png"
            for path in (lambert_base, lambert_normal):
                path.write_bytes(b"")
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(lambert_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Broken_sword_Gem_outside_0", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Broken_sword_Gem_inside_0", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[1].preview_color = (1.0, 0.0, 0.0)
            mesh.submeshes[2].preview_material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_emissiveColor",
                    color_value=(1.0, 0.0, 0.0),
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    numeric_value=10.0,
                ),
            )
            texture_sets = group_replacement_texture_sets((lambert_base, lambert_normal), obj_mesh=mesh)
            routes = build_source_material_routing_plan(
                mesh,
                texture_sets,
                (
                    StaticSubmeshMapping(0, "CD_PHM_02_Handle_0015", [2], 0),
                    StaticSubmeshMapping(1, "CD_PHM_02_Gem_0015", [1], 1),
                    StaticSubmeshMapping(2, "CD_PHM_02_Blade_0015", [0], 2),
                ),
            )

            routed = {route.target_material_name: route.source_material_name for route in routes}
            self.assertEqual("Gem_inside", routed["CD_PHM_02_Handle_0015"])
            self.assertEqual("Gem_outside", routed["CD_PHM_02_Gem_0015"])
            self.assertEqual("lambert1", routed["CD_PHM_02_Blade_0015"])

    def test_source_graph_strict_wolf_sword_uses_only_real_gltf_texture_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            Image.new("RGB", (8, 8), (255, 96, 12)).save(pbr_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Sword_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            wrapper_body = (
                '<Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                "</Vector></Material>"
            )
            sidecar_text = (
                '<ModelPropertyList><ModelProperty><SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="200">'
                f'<SkinnedMeshMaterialWrapper ItemID="199" _subMeshName="CD_PHM_02_Handle_0015">{wrapper_body}</SkinnedMeshMaterialWrapper>'
                f'<SkinnedMeshMaterialWrapper ItemID="200" _subMeshName="CD_PHM_02_Blade_0015">{wrapper_body}</SkinnedMeshMaterialWrapper>'
                "</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Broken_sword_Gem_inside_0", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (
                ("base", base_png),
                ("normal", normal_png),
                ("metallicRoughness", pbr_png),
            )
            mesh.submeshes[1].preview_color = (0.0, 1.0, 0.8)

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Handle_0015", material="CD_PHM_02_Handle_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png, pbr_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="source_graph_strict",
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Handle_0015", [1], 0, 0, "CD_PHM_02_Handle_0015", 1, False),
                        StaticOutputDrawSection(1, 1, "CD_PHM_02_Blade_0015", [0], 1, 1, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

            self.assertFalse(report.errors)
            texture_payloads = [payload for payload in payloads if payload.kind == "texture_generated"]
            self.assertEqual(3, len(texture_payloads))
            target_text = "\n".join(payload.target_path.lower() for payload in texture_payloads)
            self.assertIn("basecolor", target_text)
            self.assertIn("_n.dds", target_text)
            self.assertIn("_ma.dds", target_text)
            self.assertNotIn("gem", target_text)
            self.assertNotIn("_disp", target_text)
            self.assertNotIn("_mg", target_text)
            patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            self.assertIn("_overlayColorTexture", patched)
            self.assertIn("_normalTexture", patched)
            self.assertIn("_colorBlendingMaskTexture", patched)
            self.assertNotIn("_heightTexture", patched)
            self.assertNotIn("_detailMaskTexture", patched)
            self.assertTrue(any("inherited real source texture set lambert1" in warning for warning in report.warnings))

    def test_material_authority_clean_source_routes_direct_source_slots_and_pbr_mask_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_set = ReplacementTextureSet("lambert1")
            texture_set.slots["base"] = ReplacementTextureSlot("lambert1", "base", root / "base.png")
            texture_set.slots["normal"] = ReplacementTextureSlot("lambert1", "normal", root / "normal.png")
            texture_set.slots["material"] = ReplacementTextureSlot(
                material_name="lambert1",
                slot_kind="material",
                source_path=root / "lambert1_metallicRoughness.png",
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                source_authority="gltf",
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority_clean_source"),
            )

        by_kind = {slot.slot_kind: slot for slot in slots}
        self.assertEqual(["base", "normal", "material_mask"], [slot.slot_kind for slot in slots])
        self.assertIn("_material_mask_material_authority_clean_source_", by_kind["material_mask"].source_path.name)
        self.assertNotIn("height", by_kind)
        self.assertNotIn("detail_mask", by_kind)

    def test_material_authority_true_source_aliases_keep_clean_source_compatibility(self) -> None:
        clean_profile = get_complete_swap_material_profile("material_authority_source")

        self.assertEqual("material_authority_clean_source", clean_profile.name)
        self.assertEqual("", complete_swap_material_authority_contract("material_authority_clean_source"))
        self.assertFalse(complete_swap_material_requires_true_source_authority("material_authority_clean_source"))
        self.assertEqual("source_only", clean_profile.support_policy)
        self.assertFalse(clean_profile.preserve_target_layer_response)

        profile = get_complete_swap_material_profile("true_source")
        self.assertEqual("material_authority_true_source", profile.name)
        self.assertEqual("true_source_authority", complete_swap_material_authority_contract("true_source"))
        self.assertTrue(complete_swap_material_requires_true_source_authority("true_source"))
        self.assertEqual("source_only", profile.support_policy)
        self.assertFalse(profile.preserve_target_layer_response)

        pbr_profile = get_complete_swap_material_profile("true_source_pbr")
        self.assertEqual("material_authority_pbr_source_test", pbr_profile.name)
        self.assertEqual("true_source_authority", complete_swap_material_authority_contract(pbr_profile.name))
        self.assertEqual("source_only", pbr_profile.support_policy)
        self.assertFalse(pbr_profile.force_nonmetal)
        self.assertFalse(pbr_profile.roughness_inverted)
        self.assertEqual(240, pbr_profile.roughness_min)
        self.assertEqual(255, pbr_profile.roughness_max)
        self.assertEqual(1.0, pbr_profile.scratch_roughness)
        self.assertFalse(pbr_profile.preserve_target_layer_response)
        self.assertFalse(pbr_profile.source_color_layer_authority)
        self.assertEqual("source_roughness_high", pbr_profile.gloss_reduction_mode)

        detail_profile = get_complete_swap_material_profile("true_source_detail_mask")
        self.assertEqual("material_authority_detail_mask", detail_profile.name)
        self.assertEqual("true_source_authority_detail_mask", complete_swap_material_authority_contract(detail_profile.name))
        self.assertTrue(complete_swap_material_requires_true_source_authority(detail_profile.name))
        self.assertEqual("detail_mask_material", detail_profile.mask_binding_mode)
        self.assertEqual("_detailMaskTexture", _source_driven_parameter_name("material_mask", material_profile=detail_profile))
        self.assertEqual("material_authority_detail_mask", get_complete_swap_material_profile("material_authority").name)

        placeholder_safe_profile = get_complete_swap_material_profile("placeholder_safe")
        self.assertEqual("material_authority_placeholder_safe_test", placeholder_safe_profile.name)
        self.assertEqual("true_source_authority_detail_mask", complete_swap_material_authority_contract(placeholder_safe_profile.name))
        self.assertTrue(placeholder_safe_profile.suppress_runtime_placeholder_material_bindings)
        self.assertEqual("detail_mask_material", placeholder_safe_profile.mask_binding_mode)

    def test_material_authority_runtime_xml_routes_direct_slots_and_preserves_masks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_set = ReplacementTextureSet("lambert1")
            texture_set.slots["base"] = ReplacementTextureSlot("lambert1", "base", root / "base.png")
            texture_set.slots["normal"] = ReplacementTextureSlot("lambert1", "normal", root / "normal.png")
            texture_set.slots["height"] = ReplacementTextureSlot("lambert1", "height", root / "height.png")
            texture_set.slots["detail_mask"] = ReplacementTextureSlot("lambert1", "detail_mask", root / "detail.png")
            texture_set.slots["material"] = ReplacementTextureSlot(
                material_name="lambert1",
                slot_kind="material",
                source_path=root / "lambert1_metallicRoughness.png",
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                source_authority="gltf",
            )

            profile = get_complete_swap_material_profile("material_authority_runtime_xml")
            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=profile,
            )
            patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
                (
                    '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
                    '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                    '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
                    '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                    '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                    "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
                ),
                {
                    "CD_PHM_02_Blade_0015": tuple(
                        (_source_driven_parameter_name(slot.slot_kind, material_profile=profile), f"character/texture/{slot.source_path.stem}.dds", slot.slot_kind)
                        for slot in slots
                    )
                },
                exact_only=True,
                insert_missing_slots=False,
                shader_name="",
                material_profile=profile,
            )

        self.assertEqual(["base", "normal"], [slot.slot_kind for slot in slots])
        self.assertEqual(1, changed_count)
        self.assertEqual({"character/texture/base.dds", "character/texture/normal.dds"}, used_paths)
        self.assertIn('_materialName="SkinnedMeshStandard_Ver2"', patched)
        self.assertIn('_name="_renderSettingFlag" _value="6"', patched)
        self.assertIn("_baseColorTexture", patched)
        self.assertIn("character/texture/base.dds", patched)
        self.assertIn("character/texture/normal.dds", patched)
        self.assertIn("original_disp.dds", patched)
        self.assertIn("original_ma.dds", patched)
        self.assertIn("original_mg.dds", patched)
        self.assertIn("cd_texturelayer_003_0101.dds", patched)
        self.assertNotIn("metallicRoughness", patched)

    def test_material_authority_runtime_xml_build_preserves_stock_support_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            Image.new("RGB", (8, 8), (255, 96, 12)).save(pbr_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Blade_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_baseColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015">'
                '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
                '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6"/>'
                '<MaterialParameterTexture _name="_baseColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (
                ("base", base_png),
                ("normal", normal_png),
                ("metallicRoughness", pbr_png),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png, pbr_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_runtime_xml",
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

        self.assertFalse(report.errors)
        texture_targets = "\n".join(payload.target_path.lower() for payload in payloads if payload.kind == "texture_generated")
        self.assertIn("basecolor", texture_targets)
        self.assertIn("_n.dds", texture_targets)
        self.assertNotIn("_ma.dds", texture_targets)
        self.assertNotIn("_disp", texture_targets)
        self.assertNotIn("_mg", texture_targets)
        patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
        self.assertIn("lambert1_basecolor", patched.lower())
        self.assertIn("lambert1_n", patched.lower())
        self.assertIn("original_disp.dds", patched)
        self.assertIn("original_ma.dds", patched)
        self.assertIn("original_mg.dds", patched)
        self.assertIn("cd_texturelayer_003_0101.dds", patched)
        self.assertIn('_materialName="SkinnedMeshStandard_Ver2"', patched)
        self.assertIn('_name="_renderSettingFlag" _value="6"', patched)
        self.assertTrue(any("Material authority runtime XML" in warning for warning in report.warnings))
        self.assertTrue(any("PAC XML profile: family=weapon/sword" in warning for warning in report.warnings))

    def test_material_authority_clean_source_lifts_dark_base_and_mutes_metal_gloss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "lambert1_baseColor.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            base_image = Image.new("RGB", (2, 2), (36, 34, 31))
            base_image.putpixel((1, 0), (255, 255, 255))
            base_image.save(base_png)
            Image.new("RGB", (2, 2), (255, 64, 255)).save(pbr_png)
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_clean_source"),
                accent_glow_strength=100,
            )
            texture_set = ReplacementTextureSet("lambert1")
            texture_set.slots["base"] = ReplacementTextureSlot("lambert1", "base", base_png, source_authority="gltf")
            texture_set.slots["material"] = ReplacementTextureSlot(
                material_name="lambert1",
                slot_kind="material",
                source_path=pbr_png,
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                source_authority="gltf",
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=profile,
            )
            base_slot = next(slot for slot in slots if slot.slot_kind == "base")
            prepared_base = _source_slot_png_with_base_color_factor_path(base_slot)
            mask = _complete_swap_runtime_material_mask_png_path(texture_set, profile)

            with Image.open(prepared_base) as image:
                converted = image.convert("RGB")
                pixel = converted.getpixel((0, 0))
                white_pixel = converted.getpixel((1, 0))
            with Image.open(mask) as image:
                mask_pixel = image.convert("RGBA").getpixel((0, 0))

        self.assertGreater(pixel[0], 100)
        self.assertGreater(pixel[1], 95)
        self.assertGreater(pixel[2], 90)
        self.assertLessEqual(max(white_pixel), 222)
        self.assertEqual(255, mask_pixel[0])
        self.assertGreaterEqual(mask_pixel[1], 240)
        self.assertLessEqual(mask_pixel[2], 126)

    def test_material_authority_clean_source_tones_synthetic_gem_and_emissive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            gem_base = root / "gem_outside_base.png"
            gem_emissive = root / "gem_outside_emissive.png"
            Image.new("RGB", (2, 2), (255, 0, 0)).save(gem_base)
            Image.new("RGB", (2, 2), (255, 0, 0)).save(gem_emissive)
            profile = apply_true_source_basic_controls_to_profile(
                get_complete_swap_material_profile("material_authority_clean_source"),
                accent_glow_strength=100,
            )
            texture_set = ReplacementTextureSet("Gem_outside")
            texture_set.slots["base"] = ReplacementTextureSlot(
                "Gem_outside",
                "base",
                gem_base,
                source_authority="synthetic",
                base_color_factor=(1.0, 0.0, 0.0),
            )
            texture_set.slots["emissive"] = ReplacementTextureSlot(
                "Gem_outside",
                "emissive",
                gem_emissive,
                source_authority="synthetic",
                base_color_factor=(1.0, 0.0, 0.0),
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=profile,
            )
            base_slot = next(slot for slot in slots if slot.slot_kind == "base")
            emissive_slot = next(slot for slot in slots if slot.slot_kind == "emissive")
            with Image.open(_source_slot_png_with_base_color_factor_path(base_slot)) as image:
                base_pixel = image.convert("RGB").getpixel((0, 0))
            with Image.open(_source_slot_png_with_base_color_factor_path(emissive_slot)) as image:
                emissive_pixel = image.convert("RGB").getpixel((0, 0))

        self.assertLess(base_pixel[0], 230)
        self.assertGreater(base_pixel[1], 20)
        self.assertGreater(base_pixel[2], 20)
        self.assertLessEqual(max(emissive_pixel), 96)
        self.assertGreater(emissive_pixel[0], emissive_pixel[1])

    def test_material_authority_manual_profile_token_overrides_runtime_knobs(self) -> None:
        token = serialize_complete_swap_manual_material_profile(
            {
                "base_color_lift": 90,
                "base_color_gamma": 0.5,
                "base_color_saturation": 0.4,
                "base_color_value_max": 180,
                "emissive_color_scale": 0.1,
                "roughness_min": 250,
                "metallic_scale": 0.2,
                "metallic_max": 80,
                "force_nonmetal": True,
                "support_policy": "source_only",
            }
        )
        profile = get_complete_swap_material_profile(token)

        self.assertEqual("material_authority_manual", profile.name)
        self.assertEqual("Material Authority Manual", profile.label)
        self.assertEqual(90, profile.base_color_lift)
        self.assertEqual(180, profile.base_color_value_max)
        self.assertEqual(250, profile.roughness_min)
        self.assertEqual(80, profile.metallic_max)
        self.assertTrue(profile.force_nonmetal)

    def test_material_authority_manual_token_reaches_pac_driven_material_mask_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image, ImageStat

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (255, 96, 180)).save(pbr_png)
            base_template = root / "base.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Blade_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (
                ("base", base_png),
                ("metallicRoughness", pbr_png),
            )
            manual_token = serialize_complete_swap_manual_material_profile(
                {
                    "roughness_default": 240,
                    "roughness_min": 255,
                    "roughness_max": 255,
                    "metallic_default": 0,
                    "metallic_min": 0,
                    "metallic_scale": 0.0,
                    "metallic_max": 0,
                    "force_nonmetal": True,
                    "mask_binding_mode": "color_blending_mask",
                    "support_policy": "source_only",
                }
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, pbr_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: support_template.read_bytes() if entry is entries["material_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: support_template if entry is entries["material_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile=manual_token,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

            self.assertFalse(report.errors)
            material_mask_payload = next(
                payload
                for payload in payloads
                if payload.kind == "texture_generated" and "_ma.dds" in payload.target_path.lower()
            )
            with Image.open(material_mask_payload.source_path) as image:
                means = tuple(int(round(value)) for value in ImageStat.Stat(image.convert("RGBA")).mean)
            self.assertEqual((255, 255, 0, 0), means)
            patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            self.assertIn("material_mask_material_authority_manual", patched.lower())

    def test_material_authority_manual_exposed_fields_are_profile_backed(self) -> None:
        values = {
            "ao_default": 201,
            "roughness_default": 202,
            "metallic_default": 3,
            "alpha_default": 4,
            "scratch_roughness": 0.91,
            "scratch_metallic": 0.12,
            "shine_scalar": 0.08,
            "neutral_color_rgb": (190, 191, 192),
            "displacement_scale_multiplier": 0.25,
            "displacement_scale_max": 0.35,
            "base_color_lift": 44,
            "base_color_scale": 0.88,
            "base_color_gamma": 0.72,
            "base_color_saturation": 0.77,
            "base_color_value_max": 210,
            "base_color_auto_balance": 65,
            "base_color_shadow_lift": 35,
            "base_color_tone_contrast": -55.0,
            "emissive_color_scale": 0.22,
            "emissive_color_saturation": 0.33,
            "emissive_color_value_max": 99,
            "roughness_min": 155,
            "roughness_scale": 1.25,
            "roughness_max": 245,
            "metallic_min": 5,
            "metallic_scale": 0.45,
            "metallic_max": 75,
            "roughness_inverted": True,
            "roughness_invert": True,
            "metallic_inverted": True,
            "metallic_invert": True,
            "force_nonmetal": True,
            "preserve_scratch_alpha": False,
            "allow_factor_only_authority": True,
            "factor_only_material_mask": True,
            "force_neutral_layer_support": True,
            "preserve_target_layer_response": True,
            "source_color_layer_authority": True,
            "emissive_mode": "intensity",
            "base_binding_mode": "overlay_from_colorblend_slot",
            "mask_binding_mode": "scratch_scalars",
            "support_policy": "generated_or_neutral",
            "authority_contract": "true_source_authority",
            "edge_relief_strength": 40,
            "edge_relief_source": "generate_source",
            "global_gloss_reduction": -20.0,
            "accent_glow_strength": 60,
            "accent_glow_intensity_max": 8.0,
        }
        self.assertLessEqual(set(_MANUAL_PROFILE_FIELD_NAMES), set(values))

        profile = get_complete_swap_material_profile(serialize_complete_swap_manual_material_profile(values))

        for field_name, expected in values.items():
            if field_name in {"roughness_invert", "metallic_invert"}:
                continue
            self.assertEqual(expected, getattr(profile, field_name), field_name)
        self.assertTrue(profile.roughness_invert)
        self.assertTrue(profile.metallic_invert)

    def test_material_authority_manual_defaults_track_material_authority(self) -> None:
        profiles = {profile.name: profile for profile in complete_swap_material_runtime_profiles()}
        manual = profiles["material_authority_manual"]
        material_authority = profiles["material_authority_detail_mask"]

        for field_name in (
            "support_policy",
            "allow_factor_only_authority",
            "factor_only_material_mask",
            "preserve_target_layer_response",
            "mask_binding_mode",
            "xml_profile_mode",
            "authority_contract",
            "base_color_lift",
            "base_color_scale",
            "base_color_gamma",
            "base_color_saturation",
            "base_color_value_max",
            "emissive_color_scale",
            "emissive_color_saturation",
            "emissive_color_value_max",
            "roughness_default",
            "roughness_min",
            "metallic_default",
            "metallic_scale",
            "metallic_max",
            "displacement_scale_multiplier",
            "displacement_scale_max",
        ):
            self.assertEqual(getattr(material_authority, field_name), getattr(manual, field_name), field_name)

    def test_manual_profile_token_controls_authority_contract(self) -> None:
        material_authority_token = serialize_complete_swap_manual_material_profile({"authority_contract": "true_source_authority_detail_mask"})
        runtime_token = serialize_complete_swap_manual_material_profile({"authority_contract": "runtime_xml_preserve"})
        true_source_token = serialize_complete_swap_manual_material_profile({"authority_contract": "true_source_authority"})

        self.assertEqual("true_source_authority_detail_mask", complete_swap_material_authority_contract(material_authority_token))
        self.assertEqual("runtime_xml_preserve", complete_swap_material_authority_contract(runtime_token))
        self.assertEqual("true_source_authority", complete_swap_material_authority_contract(true_source_token))

    def test_material_authority_clean_source_strips_old_layers_instead_of_repointing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            pbr_png = root / "lambert1_metallicRoughness.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            Image.new("RGB", (8, 8), (255, 96, 12)).save(pbr_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Blade_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailDiffuseMaskG"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0016.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_disp.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_lambert1_0", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (
                ("base", base_png),
                ("normal", normal_png),
                ("metallicRoughness", pbr_png),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png, pbr_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_clean_source",
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

        self.assertFalse(report.errors)
        texture_targets = "\n".join(payload.target_path.lower() for payload in payloads if payload.kind == "texture_generated")
        self.assertIn("basecolor", texture_targets)
        self.assertIn("_n.dds", texture_targets)
        self.assertIn("_ma.dds", texture_targets)
        self.assertNotIn("_disp", texture_targets)
        self.assertNotIn("_mg", texture_targets)
        patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
        self.assertIn("lambert1_basecolor", patched.lower())
        self.assertIn("lambert1_n", patched.lower())
        self.assertIn("material_mask_material_authority_clean_source", patched.lower())
        self.assertNotIn("original_disp.dds", patched)
        self.assertNotIn("original_mg.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0101.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0016.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0001_disp.dds", patched)
        self.assertNotIn('_name="_heightTexture"', patched)
        self.assertNotIn('_name="_detailMaskTexture"', patched)
        self.assertNotIn("_grimeDiffuseTextureR", patched)
        self.assertNotIn("_detailDiffuseMaskG", patched)
        self.assertNotIn("_detailHeightMaskR", patched)
        self.assertTrue(any("reset inherited target shader/material response" in warning for warning in report.warnings))

    def test_material_authority_clean_source_keeps_factor_only_gem_material_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            lambert_base = root / "lambert1_baseColor.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(lambert_base)
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_base.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Blade", material="lambert1", texture=str(lambert_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Gem", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", lambert_base),)
            mesh.submeshes[1].preview_color = (1.0, 0.0, 0.0)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Gem_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="1"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Gem_0015", material="CD_PHM_02_Gem_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(lambert_base,),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="CD_PHM_02_Gem_0015",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_clean_source",
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Gem_0015", [1], 0, 0, "CD_PHM_02_Gem_0015", 1, False),
                    ),
                )

        self.assertFalse(report.errors)
        self.assertFalse(any("inherited real source texture set lambert1" in warning for warning in report.warnings))
        patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
        self.assertIn("gem_outside_base", patched.lower())
        self.assertIn("gem_outside_material_mask", patched.lower())
        self.assertNotIn("lambert1", patched.lower())
        self.assertIn("#d8d8d8ff", patched)
        texture_targets = "\n".join(payload.target_path.lower() for payload in payloads if payload.kind == "texture_generated")
        self.assertIn("gem_outside_base", texture_targets)
        self.assertIn("gem_outside_material_mask", texture_targets)
        self.assertNotIn("lambert1", texture_targets)

    def test_material_authority_bruteforce_repoints_layer_texture_slots(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/grime.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailDiffuseMaskG"><ResourceReferencePath_ITexture _path="character/texture/detail_d.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailMaterialMaskB"><ResourceReferencePath_ITexture _path="character/texture/detail_ma.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )
        patched, changed_wrappers, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "Blade": (
                    ("_overlayColorTexture", "character/texture/source_base.dds", "base"),
                    ("_normalTexture", "character/texture/source_n.dds", "normal"),
                    ("_colorBlendingMaskTexture", "character/texture/source_ma.dds", "material_mask"),
                )
            },
            exact_only=True,
            insert_missing_slots=True,
            material_authority_bruteforce=True,
        )

        self.assertEqual(1, changed_wrappers)
        self.assertNotIn("original_o.dds", patched)
        self.assertNotIn("grime.dds", patched)
        self.assertNotIn("original_disp.dds", patched)
        self.assertIn('_name="_grimeDiffuseTextureR"', patched)
        self.assertIn('_name="_detailMaterialMaskB"', patched)
        self.assertIn("character/texture/source_base.dds", patched)
        self.assertIn("character/texture/source_n.dds", patched)
        self.assertIn("character/texture/source_ma.dds", patched)
        self.assertEqual(
            {
                "character/texture/source_base.dds",
                "character/texture/source_n.dds",
                "character/texture/source_ma.dds",
            },
            used_paths,
        )

    def test_material_authority_bruteforce_tuned_keeps_texture_routing_but_mutes_response(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/source_ma.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat _name="_screenSpaceDisplacementScale" _value="0.080000" Index="2"/>'
            '<MaterialParameterFloat _name="_detailScreenSpaceDisplacementScale" _value="0.200000" Index="3"/>'
            '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="4"/>'
            '<MaterialParameterColor _name="_scratchTintColorR" _value="#80604036" Index="5"/>'
            '<MaterialParameterByte4 _name="_grimeBlendingParameterR" _value="3344424" Index="6"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, wrappers, parameters = _neutralize_inherited_material_layers(
            sidecar_text,
            material_names=("Blade",),
            keep_rules=(
                ("_overlayColorTexture", "character/texture/source_base.dds"),
                ("_heightTexture", "character/texture/source_ma.dds"),
            ),
            complete_external_reset=True,
            material_profile=get_complete_swap_material_profile("material_authority_bruteforce_tuned"),
        )

        self.assertEqual(1, wrappers)
        self.assertGreater(parameters, 0)
        self.assertIn("character/texture/source_base.dds", patched)
        self.assertIn("character/texture/source_ma.dds", patched)
        self.assertIn('_name="_screenSpaceDisplacementScale" _value="0.000000"', patched)
        self.assertIn('_name="_detailScreenSpaceDisplacementScale" _value="0.000000"', patched)
        self.assertIn('_name="_tintColorR" _value="#d8d8d8ff"', patched)
        self.assertIn('_name="_scratchTintColorR" _value="#d8d8d836"', patched)
        self.assertIn('_name="_grimeBlendingParameterR" _value="0"', patched)

    def test_material_authority_bruteforce_tuned_adds_missing_layer_byte_values(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterByte4 _name="_grimeBlendingOpacityParameter" Index="1"/>'
            '<MaterialParameterByte4 _name="_dyeingMask" Index="2"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, wrappers, parameters = _neutralize_inherited_material_layers(
            sidecar_text,
            material_names=("Blade",),
            complete_external_reset=True,
            material_profile=get_complete_swap_material_profile("material_authority_bruteforce_tuned"),
        )

        self.assertEqual(1, wrappers)
        self.assertGreaterEqual(parameters, 2)
        self.assertIn('_name="_grimeBlendingOpacityParameter" Index="0" _value="0"', patched)
        self.assertIn('_name="_dyeingMask" Index="1" _value="0"', patched)

    def test_material_authority_bruteforce_tuned_routes_height_layers_to_neutral_support(self) -> None:
        wrapper_text = (
            '<SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/old_disp.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/old_dh.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailDiffuseMaskR"><ResourceReferencePath_ITexture _path="character/texture/old_diff.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailMaterialMaskR"><ResourceReferencePath_ITexture _path="character/texture/old_mat.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper>"
        )

        patched, changed, used_paths = _bruteforce_source_authority_texture_parameters(
            wrapper_text,
            (
                ("_overlayColorTexture", "character/texture/source_base.dds", "base"),
                ("_normalTexture", "character/texture/source_n.dds", "normal"),
                ("_heightTexture", "character/texture/neutral_height.dds", "height"),
                ("_colorBlendingMaskTexture", "character/texture/source_ma.dds", "material_mask"),
                ("_detailMaskTexture", "character/texture/neutral_detail.dds", "detail_mask"),
            ),
            material_profile=get_complete_swap_material_profile("material_authority_bruteforce_tuned"),
        )

        self.assertTrue(changed)
        self.assertIn("character/texture/neutral_height.dds", used_paths)
        self.assertIn('_name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/neutral_height.dds"', patched)
        self.assertIn('_name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/neutral_height.dds"', patched)
        self.assertIn('_name="_detailDiffuseMaskR"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"', patched)
        self.assertIn('_name="_detailMaterialMaskR"><ResourceReferencePath_ITexture _path="character/texture/source_ma.dds"', patched)

    def test_material_authority_bruteforce_tuned_keeps_source_pbr_material_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pbr_path = root / "lambert1_metallicRoughness.png"
            pbr_path.write_bytes(b"")
            texture_set = ReplacementTextureSet("lambert1")
            texture_set.slots["material"] = ReplacementTextureSlot(
                material_name="lambert1",
                slot_kind="material",
                source_path=pbr_path,
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                source_authority="gltf",
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority_bruteforce_tuned"),
            )

        by_kind = {slot.slot_kind: slot for slot in slots}
        self.assertIn("height", by_kind)
        self.assertIn("detail_mask", by_kind)
        self.assertIn("material_mask", by_kind)
        self.assertIn("_material_mask_material_authority_bruteforce_tuned_", by_kind["material_mask"].source_path.name)
        self.assertNotIn("_material_mask_neutral_", by_kind["material_mask"].source_path.name)

    def test_material_authority_bruteforce_default_neutralization_stays_white_zero(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterFloat _name="_screenSpaceDisplacementScale" _value="0.080000" Index="0"/>'
            '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="1"/>'
            '<MaterialParameterColor _name="_scratchTintColorR" _value="#80604036" Index="2"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, wrappers, parameters = _neutralize_inherited_material_layers(
            sidecar_text,
            material_names=("Blade",),
            complete_external_reset=True,
            material_profile=get_complete_swap_material_profile("material_authority_bruteforce"),
        )

        self.assertEqual(1, wrappers)
        self.assertGreater(parameters, 0)
        self.assertIn('_name="_screenSpaceDisplacementScale" _value="0.000000"', patched)
        self.assertIn('_name="_tintColorR" _value="#ffffffff"', patched)
        self.assertIn('_name="_scratchTintColorR" _value="#ffffffff"', patched)
        self.assertNotIn("#d8d8d8", patched)

    def test_material_authority_detail_preserve_keeps_target_layer_response(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
            '<MaterialParameterBitFlag32 _name="_renderSettingFlag" _value="6" Index="0"/>'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/source_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_disp.dds"/></MaterialParameterTexture>'
            '<MaterialParameterFloat _name="_screenSpaceDisplacementScale" _value="0.097000" Index="4"/>'
            '<MaterialParameterFloat _name="_detailScreenSpaceDisplacementScale" _value="0.044000" Index="5"/>'
            '<MaterialParameterBitFlag32 _name="_colorBlendingFlag" _value="4095" Index="6"/>'
            '<MaterialParameterColor _name="_tintColorR" _value="#818cb1ff" Index="7"/>'
            '<MaterialParameterByte4 _name="_grimeBlendingParameterR" _value="285215788" Index="8"/>'
            '<MaterialParameterByte4 _name="_scratchRoughness" _value="12418864" Index="9"/>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, wrappers, parameters = _neutralize_inherited_material_layers(
            sidecar_text,
            material_names=("Blade",),
            keep_rules=(
                ("_overlayColorTexture", "character/texture/source_base.dds"),
                ("_normalTexture", "character/texture/source_n.dds"),
            ),
            complete_external_reset=True,
            material_profile=get_complete_swap_material_profile("material_authority_detail_preserve"),
        )

        self.assertEqual(0, wrappers)
        self.assertEqual(0, parameters)
        self.assertIn('_name="_renderSettingFlag" _value="6"', patched)
        self.assertIn("cd_texturelayer_003_0001_disp.dds", patched)
        self.assertIn('_name="_screenSpaceDisplacementScale" _value="0.097000"', patched)
        self.assertIn('_name="_detailScreenSpaceDisplacementScale" _value="0.044000"', patched)
        self.assertIn('_name="_colorBlendingFlag" _value="4095"', patched)
        self.assertIn('_name="_tintColorR" _value="#818cb1ff"', patched)
        self.assertIn('_name="_grimeBlendingParameterR" _value="285215788"', patched)
        self.assertIn('_name="_scratchRoughness" _value="12418864"', patched)

    def test_material_authority_detail_preserve_routes_only_source_color_and_normal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_set = ReplacementTextureSet("lambert1")
            texture_set.slots["base"] = ReplacementTextureSlot("lambert1", "base", root / "base.png")
            texture_set.slots["normal"] = ReplacementTextureSlot("lambert1", "normal", root / "normal.png")
            texture_set.slots["material"] = ReplacementTextureSlot(
                material_name="lambert1",
                slot_kind="material",
                source_path=root / "metallicRoughness.png",
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                source_authority="gltf",
            )

            slots = _source_driven_slots(
                texture_set,
                include_complete_support_fallbacks=True,
                material_profile=get_complete_swap_material_profile("material_authority_detail_preserve"),
            )

        self.assertEqual(["base", "normal"], [slot.slot_kind for slot in slots])

    def test_material_authority_detail_preserve_disables_unmapped_prune(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Blade_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_disp.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Blade", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", base_png), ("normal", normal_png))

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_detail_preserve",
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

        self.assertFalse(report.errors)
        patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
        self.assertIn("lambert1_basecolor", patched.lower())
        self.assertIn("lambert1_n", patched.lower())
        self.assertIn("original_disp.dds", patched)
        self.assertIn("original_ma.dds", patched)
        self.assertIn("original_mg.dds", patched)
        self.assertIn("cd_texturelayer_003_0001_disp.dds", patched)
        self.assertTrue(any("keeping target CD height/material/detail" in warning for warning in report.warnings))
        self.assertFalse(any("unmapped original texture parameter" in warning for warning in report.warnings))

    def test_material_authority_source_color_relief_repoints_visible_layer_color_only(self) -> None:
        sidecar_text = (
            '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Material><Vector Name="_parameters">'
            '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailDiffuseMaskG"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0016.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_grimeNormalTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101_n.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_detailHeightMaskG"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0016_disp.dds"/></MaterialParameterTexture>'
            '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
            "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
        )

        patched, changed, used_paths, changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "Blade": (
                    ("_overlayColorTexture", "character/texture/source_base.dds", "base"),
                    ("_normalTexture", "character/texture/source_n.dds", "normal"),
                )
            },
            exact_only=True,
            insert_missing_slots=True,
            material_profile=get_complete_swap_material_profile("material_authority_source_color_relief_preserve"),
        )

        self.assertEqual(1, changed)
        self.assertEqual({"Blade"}, changed_names)
        self.assertEqual({"character/texture/source_base.dds", "character/texture/source_n.dds"}, used_paths)
        self.assertNotIn("cd_texturelayer_003_0101.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0016.dds", patched)
        self.assertIn('_name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"', patched)
        self.assertIn('_name="_detailDiffuseMaskG"><ResourceReferencePath_ITexture _path="character/texture/source_base.dds"', patched)
        self.assertIn("cd_texturelayer_003_0101_n.dds", patched)
        self.assertIn("cd_texturelayer_003_0016_disp.dds", patched)
        self.assertIn("original_ma.dds", patched)

    def test_material_authority_source_color_relief_keeps_support_without_stock_visible_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_png = root / "lambert1_baseColor.png"
            normal_png = root / "lambert1_normal.png"
            Image.new("RGB", (8, 8), (40, 40, 48)).save(base_png)
            Image.new("RGB", (8, 8), (128, 128, 255)).save(normal_png)
            base_template = root / "base.dds"
            normal_template = root / "normal.dds"
            support_template = root / "support.dds"
            base_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            normal_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U"))
            support_template.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Blade_0015",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Blade_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0101.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailDiffuseMaskG"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0016.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailHeightMaskR"><ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001_disp.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Blade", material="lambert1", texture=str(base_png), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", base_png), ("normal", normal_png))

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(8, 8, fourcc=b"BC5U" if "_normal" in command[-1].lower() else b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(base_png, normal_png),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: normal_template.read_bytes() if entry is entries["normal"] else support_template.read_bytes() if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template.read_bytes(),
                    original_texture_source_path=lambda entry: normal_template if entry is entries["normal"] else support_template if entry is entries["height"] or entry is entries["material_mask"] or entry is entries["detail_mask"] else base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_source_color_relief_preserve",
                    prune_unmapped_original_texture_parameters=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Blade_0015", [0], 0, 0, "CD_PHM_02_Blade_0015", 1, False),
                    ),
                )

        self.assertFalse(report.errors)
        patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
        self.assertIn("lambert1_basecolor", patched.lower())
        self.assertIn("lambert1_n", patched.lower())
        self.assertIn("original_disp.dds", patched)
        self.assertIn("original_ma.dds", patched)
        self.assertIn("original_mg.dds", patched)
        self.assertIn("cd_texturelayer_003_0001_disp.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0101.dds", patched)
        self.assertNotIn("cd_texturelayer_003_0016.dds", patched)
        self.assertTrue(any("source color authoritative; target relief/support preserved" in warning for warning in report.warnings))

    def test_material_authority_bruteforce_tuned_allows_exact_factor_only_gem_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_base.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Blade", material="lambert1", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Gem", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[1].preview_color = (1.0, 0.0, 0.0)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Gem_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="1"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Gem_0015", material="CD_PHM_02_Gem_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="CD_PHM_02_Gem_0015",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_bruteforce_tuned",
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Gem_0015", [1], 0, 0, "CD_PHM_02_Gem_0015", 1, False),
                    ),
                )

            self.assertFalse(report.errors)
            patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            self.assertIn("gem_outside_base", patched.lower())
            self.assertNotIn("lambert1", patched.lower())
            self.assertIn("#d8d8d8ff", patched)
            texture_targets = "\n".join(payload.target_path.lower() for payload in payloads if payload.kind == "texture_generated")
            self.assertIn("gem_outside_base", texture_targets)

    def test_material_authority_bruteforce_tuned_drops_unreferenced_factor_emissive_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_base.dds", root)
            sidecar_entry = _entry("character/modelproperty/gem.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Gem", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].preview_color = (1.0, 0.0, 0.0)
            mesh.submeshes[0].preview_material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_emissiveColor",
                    color_value=(1.0, 0.0, 0.0),
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    numeric_value=8.0,
                ),
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Gem_0015"><Material><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=ParsedMesh(
                        submeshes=[
                            SubMesh(name="CD_PHM_02_Gem_0015", material="CD_PHM_02_Gem_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                        ]
                    ),
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="CD_PHM_02_Gem_0015",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="material_authority_bruteforce_tuned",
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Gem_0015", [0], 0, 0, "CD_PHM_02_Gem_0015", 1, False),
                    ),
                )

            patched = next(payload.payload_data.decode("utf-8") for payload in payloads if payload.kind == "sidecar_generated")
            self.assertIn("gem_inside_base", patched.lower())
            self.assertNotIn("gem_inside_emissive", patched.lower())
            texture_targets = "\n".join(payload.target_path.lower() for payload in payloads if payload.kind == "texture_generated")
            self.assertIn("gem_inside_base", texture_targets)
            self.assertNotIn("gem_inside_emissive", texture_targets)
            self.assertNotIn("generated DDS is not referenced", "\n".join(report.warnings))

    def test_active_file_authority_audit_detects_stale_dmmsa_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "loose"
            local_path = package_root / "character" / "texture" / "sword_base.dds"
            local_path.parent.mkdir(parents=True)
            local_path.write_bytes(b"new loose payload")
            game_root = root / "game"
            virtual_path = "character/texture/sword_base.dds"
            _write_single_file_pamt(game_root / "0009", virtual_path, b"old vanilla payload")
            _write_single_file_pamt(game_root / "dmmsa", virtual_path, b"old active mod payload")

            result = audit_loose_package_active_file_authority(
                package_root,
                game_root=game_root,
                payload_files=(local_path,),
            )

            self.assertEqual(1, result.mismatch_count)
            self.assertTrue(result.audit_path and result.audit_path.is_file())
            self.assertEqual("mismatch", result.rows[0].status)
            self.assertEqual("dmmsa/0.pamt", result.rows[0].active_source)
            self.assertTrue(any("IN-GAME TEST BLOCKED" in warning for warning in result.warnings))

    def test_active_file_authority_audit_skips_report_for_base_archive_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "loose"
            local_path = package_root / "character" / "texture" / "sword_base.dds"
            local_path.parent.mkdir(parents=True)
            local_path.write_bytes(b"new loose payload")
            game_root = root / "game"
            virtual_path = "character/texture/sword_base.dds"
            _write_single_file_pamt(game_root / "0009", virtual_path, b"old vanilla payload")
            audit_output = root / "loose_cdmw_active_file_authority_audit.json"
            audit_output.write_text("stale report", encoding="utf-8")

            result = audit_loose_package_active_file_authority(
                package_root,
                game_root=game_root,
                payload_files=(local_path,),
                audit_output_path=audit_output,
            )

            self.assertEqual(0, result.mismatch_count)
            self.assertIsNone(result.audit_path)
            self.assertFalse(audit_output.exists())
            self.assertEqual("replaces_archive", result.rows[0].status)
            self.assertEqual("0009/0.pamt", result.rows[0].active_source)
            self.assertFalse(any("IN-GAME TEST BLOCKED" in warning for warning in result.warnings))

    def test_source_graph_strict_blocks_ambiguous_factor_only_texture_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            blade_base = root / "blade_baseColor.png"
            handle_base = root / "handle_baseColor.png"
            for path, color in ((blade_base, (40, 40, 48)), (handle_base, (120, 64, 32))):
                Image.new("RGB", (4, 4), color).save(path)
            template = root / "base.dds"
            template.write_bytes(_fake_dds_bytes(4, 4))
            base_entry = _entry("character/texture/original_base.dds", root)
            sidecar_entry = _entry("character/modelproperty/test_weapon.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Gem_0015">'
                '<MaterialParameterTexture _name="_overlayColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/>'
                '</MaterialParameterTexture></SkinnedMeshMaterialWrapper></Root>'
            )
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Blade", material="Blade", texture=str(blade_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Handle", material="Handle", texture=str(handle_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Gem", material="Gem", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].texture_slots = (("base", blade_base),)
            mesh.submeshes[1].texture_slots = (("base", handle_base),)
            mesh.submeshes[2].preview_color = (0.0, 1.0, 0.8)

            payloads, report = build_texture_replacement_payloads(
                obj_mesh=mesh,
                rebuilt_mesh=ParsedMesh(
                    submeshes=[
                        SubMesh(name="CD_PHM_02_Gem_0015", material="CD_PHM_02_Gem_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    ]
                ),
                texture_files=(blade_base, handle_base),
                original_texture_refs=(
                    ArchiveModelTextureReference(
                        reference_name=base_entry.path,
                        material_name="CD_PHM_02_Gem_0015",
                        sidecar_parameter_name="_overlayColorTexture",
                        resolved_archive_path=base_entry.path,
                        resolved_entry=base_entry,
                    ),
                ),
                original_sidecars=((sidecar_entry, sidecar_text),),
                submesh_mappings=(),
                texconv_path=texconv,
                read_original_texture_bytes=lambda _entry: template.read_bytes(),
                original_texture_source_path=lambda _entry: template,
                pac_driven_sidecar=True,
                complete_external_material_reset=True,
                complete_swap_material_profile="source_graph_strict",
                output_draw_sections=(
                    StaticOutputDrawSection(0, 0, "CD_PHM_02_Gem_0015", [2], 0, 0, "CD_PHM_02_Gem_0015", 1, False),
                ),
            )

            self.assertFalse([payload for payload in payloads if payload.kind == "texture_generated"])
            self.assertTrue(report.errors)
            self.assertIn("multiple source texture sets", "\n".join(report.errors))

    def test_complete_swap_binds_source_materials_into_original_runtime_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_template = root / "base.dds"
            base_template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            base_entry = _entry("character/texture/original_handle_o.dds", root)
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Broken_sword_Gem_inside_0", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="Broken_sword_Gem_outside_0", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].preview_material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_emissiveColor",
                    color_value=(1.0, 0.0, 0.0),
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    numeric_value=6.0,
                ),
            )
            mesh.submeshes[1].preview_color = (1.0, 0.0, 0.0)
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="CD_PHM_02_Handle_0015", material="CD_PHM_02_Handle_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="CD_PHM_02_Guard_0015", material="CD_PHM_02_Guard_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            sidecar_text = (
                '<ModelPropertyList><ModelProperty><SkinnedMeshProperty><Vector Name="_subMeshResources">'
                '<SkinnedMeshMaterialWrapper ItemID="1189" _subMeshName="CD_PHM_02_Handle_0015"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0">'
                '<ResourceReferencePath_ITexture _path="character/texture/original_handle_o.dds"/>'
                '</MaterialParameterTexture>'
                '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="1"/>'
                '<MaterialParameterColor _name="_scratchTintColorR" _value="#806040ff" Index="2"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper>"
                '<SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="CD_PHM_02_Guard_0015"><Material>'
                '<Vector Name="_parameters"></Vector></Material></SkinnedMeshMaterialWrapper>'
                '</Vector></SkinnedMeshProperty></ModelProperty></ModelPropertyList>'
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(),
                    original_texture_refs=(
                        ArchiveModelTextureReference(
                            reference_name=base_entry.path,
                            material_name="CD_PHM_02_Handle_0015",
                            sidecar_parameter_name="_overlayColorTexture",
                            resolved_archive_path=base_entry.path,
                            resolved_entry=base_entry,
                        ),
                    ),
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "CD_PHM_02_Handle_0015", [0, 1], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: base_template.read_bytes(),
                    original_texture_source_path=lambda _entry: base_template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    complete_swap_material_profile="arm_emissive",
                    output_draw_sections=(
                        StaticOutputDrawSection(0, 0, "CD_PHM_02_Handle_0015", [0], 0, 0, "CD_PHM_02_Handle_0015", 1, False),
                        StaticOutputDrawSection(1, 1, "CD_PHM_02_Guard_0015", [1], 1, 1, "CD_PHM_02_Guard_0015", 1, False),
                    ),
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertNotIn('_subMeshName="Gem_inside"', patched)
            self.assertNotIn('_subMeshName="Gem_outside"', patched)
            self.assertIn("_emissiveIntensityTexture", patched)
            self.assertIn("gem_inside_emissive", patched.lower())
            self.assertIn("gem_outside_base", patched.lower())
            self.assertIn("#ffffffff", patched)
            self.assertNotIn("#ffffff00", patched)
            self.assertIn('_subMeshName="CD_PHM_02_Handle_0015"', patched)
            self.assertIn('_subMeshName="CD_PHM_02_Guard_0015"', patched)
            placeholder_block = patched[
                patched.index('_subMeshName="CD_PHM_02_Handle_0015"') : patched.index('_subMeshName="CD_PHM_02_Guard_0015"')
            ]
            self.assertIn("gem_inside", placeholder_block.lower())
            self.assertLess(
                patched.index('_subMeshName="CD_PHM_02_Handle_0015"'),
                patched.index('_subMeshName="CD_PHM_02_Guard_0015"'),
            )
            routes = {route.target_material_name: route.source_material_name for route in report.material_routes}
            self.assertEqual("Gem_inside", routes["CD_PHM_02_Handle_0015"])
            self.assertEqual("Gem_outside", routes["CD_PHM_02_Guard_0015"])

    def test_complete_external_swap_bakes_atlas_for_merged_runtime_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            from PIL import Image

            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            gem_base = root / "Gem_inside_baseColor.png"
            lambert_base = root / "lambert1_baseColor.png"
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(gem_base)
            Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(lambert_base)
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            refs = tuple(
                ArchiveModelTextureReference(
                    reference_name=entry.path,
                    material_name="CD_PHM_02_Sword_0042",
                    sidecar_parameter_name=parameter,
                    resolved_archive_path=entry.path,
                    resolved_entry=entry,
                )
                for entry, parameter in (
                    (entries["base"], "_overlayColorTexture"),
                    (entries["normal"], "_normalTexture"),
                    (entries["height"], "_heightTexture"),
                    (entries["material_mask"], "_colorBlendingMaskTexture"),
                    (entries["detail_mask"], "_detailMaskTexture"),
                )
            )
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0042.pac_xml", root)
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Sword_0042"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_overlayColorTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/original_base.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_normalTexture" Index="1"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture" Index="2"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture" Index="3"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture" Index="4"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            obj_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="blade", material="lambert1", texture=str(lambert_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="gem", material="Gem_inside", texture=str(gem_base), vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="runtime", material="CD_PHM_02_Sword_0042", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=obj_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(gem_base, lambert_base),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "CD_PHM_02_Sword_0042", [0, 1], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: template.read_bytes(),
                    original_texture_source_path=lambda _entry: template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                    output_draw_sections=(
                        StaticOutputDrawSection(
                            0,
                            0,
                            "CD_PHM_02_Sword_0042",
                            [0, 1],
                            0,
                            0,
                            "CD_PHM_02_Sword_0042",
                            2,
                            False,
                            atlas_source_material_names=("lambert1", "Gem_inside"),
                            atlas_rects=(
                                StaticMaterialAtlasRect("lambert1", (0,), 0.0, 0.0, 0.5, 1.0),
                                StaticMaterialAtlasRect("Gem_inside", (1,), 0.5, 0.0, 0.5, 1.0),
                            ),
                        ),
                    ),
                )

            self.assertFalse(report.errors)
            texture_targets = {payload.target_path for payload in payloads if payload.kind == "texture_generated"}
            self.assertTrue(any("baked_base" in path for path in texture_targets))
            self.assertTrue(any("baked_normal" in path for path in texture_targets))
            self.assertTrue(any("baked_material_mask" in path for path in texture_targets))
            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("baked_base", patched)
            self.assertIn("baked_material_mask", patched)
            self.assertNotIn("gem_inside_base", patched.lower())
            routes = {route.target_material_name: route.source_material_name for route in report.material_routes}
            self.assertEqual("lambert1 + Gem_inside", routes["CD_PHM_02_Sword_0042"])

    def test_complete_swap_synthesizes_neutral_game_support_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            template = root / "template.dds"
            template.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
            entries = {
                "base": _entry("character/texture/original_base.dds", root),
                "normal": _entry("character/texture/original_n.dds", root),
                "height": _entry("character/texture/original_disp.dds", root),
                "material_mask": _entry("character/texture/original_ma.dds", root),
                "detail_mask": _entry("character/texture/original_mg.dds", root),
            }
            sidecar_entry = _entry("character/modelproperty/cd_phm_02_sword_0015.pac_xml", root)
            mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="Gem_outside", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mesh.submeshes[0].preview_color = (0.8, 0.1, 0.1)
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="CD_PHM_02_Handle_0015", material="CD_PHM_02_Handle_0015", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="CD_PHM_02_Handle_0015"><Material>'
                '<Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_normalTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_heightTexture" Index="1"><ResourceReferencePath_ITexture _path="character/texture/original_disp.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_colorBlendingMaskTexture" Index="2"><ResourceReferencePath_ITexture _path="character/texture/original_ma.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture" Index="3"><ResourceReferencePath_ITexture _path="character/texture/original_mg.dds"/></MaterialParameterTexture>'
                '<MaterialParameterColor _name="_tintColorR" _value="#402c1aff" Index="4"/>'
                "</Vector></Material></SkinnedMeshMaterialWrapper></Root>"
            )
            refs = (
                ArchiveModelTextureReference(reference_name=entries["base"].path, material_name="CD_PHM_02_Handle_0015", sidecar_parameter_name="_overlayColorTexture", resolved_archive_path=entries["base"].path, resolved_entry=entries["base"]),
                ArchiveModelTextureReference(reference_name=entries["normal"].path, material_name="CD_PHM_02_Handle_0015", sidecar_parameter_name="_normalTexture", resolved_archive_path=entries["normal"].path, resolved_entry=entries["normal"]),
                ArchiveModelTextureReference(reference_name=entries["height"].path, material_name="CD_PHM_02_Handle_0015", sidecar_parameter_name="_heightTexture", resolved_archive_path=entries["height"].path, resolved_entry=entries["height"]),
                ArchiveModelTextureReference(reference_name=entries["material_mask"].path, material_name="CD_PHM_02_Handle_0015", sidecar_parameter_name="_colorBlendingMaskTexture", resolved_archive_path=entries["material_mask"].path, resolved_entry=entries["material_mask"]),
                ArchiveModelTextureReference(reference_name=entries["detail_mask"].path, material_name="CD_PHM_02_Handle_0015", sidecar_parameter_name="_detailMaskTexture", resolved_archive_path=entries["detail_mask"].path, resolved_entry=entries["detail_mask"]),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(16, 16, mips=1, fourcc=b"DXT1"))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(),
                    original_texture_refs=refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=(StaticSubmeshMapping(0, "CD_PHM_02_Handle_0015", [0], 0),),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: template.read_bytes(),
                    original_texture_source_path=lambda _entry: template,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                    complete_external_material_reset=True,
                )

            sidecar_payload = next(payload for payload in payloads if payload.kind == "sidecar_generated")
            patched = sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("_colorBlendingMaskTexture", patched)
            self.assertIn("_detailMaskTexture", patched)
            self.assertIn("_heightTexture", patched)
            self.assertIn("_normalTexture", patched)
            self.assertIn("neutral", patched.lower())
            emitted = {mapping.slot_kind for mapping in report.slot_mappings}
            self.assertIn("material_mask", emitted)
            self.assertIn("detail_mask", emitted)
            self.assertIn("height", emitted)
            self.assertIn("normal", emitted)

    def test_complete_swap_neutral_support_maps_use_runtime_safe_defaults(self) -> None:
        from PIL import Image

        material_mask = _complete_swap_neutral_support_png_path("Gem_outside", "material_mask")
        detail_mask = _complete_swap_neutral_support_png_path("Gem_outside", "detail_mask")

        with Image.open(material_mask) as image:
            self.assertEqual((255, 192, 0, 0), image.convert("RGBA").getpixel((0, 0)))
        with Image.open(detail_mask) as image:
            self.assertEqual((0, 0, 0, 0), image.convert("RGBA").getpixel((0, 0)))

    def test_material_authority_detail_mask_factor_only_mask_is_inert_detail_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base_png = root / "Gem_outside_baseColor.png"
            Image.new("RGBA", (2, 2), (247, 4, 0, 255)).save(base_png)
            texture_set = ReplacementTextureSet(
                "Gem_outside",
                slots={"base": ReplacementTextureSlot("Gem_outside", "base", base_png, source_authority="gltf")},
            )
            profile = get_complete_swap_material_profile("material_authority_detail_mask")

            slots = _source_driven_slots(
                texture_set,
                include_pbr_material_fallback=True,
                include_complete_support_fallbacks=True,
                material_profile=profile,
            )

            material_slot = next(slot for slot in slots if slot.slot_kind == "material_mask")
            self.assertEqual("_detailMaskTexture", _source_driven_parameter_name("material_mask", material_profile=profile))
            self.assertIn("_detail_mask_neutral_", material_slot.source_path.name)
            with Image.open(material_slot.source_path) as image:
                self.assertEqual((0, 0, 0, 0), image.convert("RGBA").getpixel((0, 0)))
            preview_slots = material_authority_preview_texture_slots(texture_set, profile)
            self.assertIn("_detail_mask_neutral_", preview_slots["material_mask"].source_path.name)

    def test_complete_swap_wrapper_clone_stays_inside_submesh_resource_vector_with_unique_item_id(self) -> None:
        sidecar_text = """
<ModelPropertyList>
  <ModelProperty>
    <SkinnedMeshProperty>
      <Vector Name="_subMeshResources">
        <SkinnedMeshMaterialWrapper ItemID="1189" _subMeshName="CD_PHM_02_Handle_0015">
          <Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">
            <MaterialParameterTexture StringItemID="_overlayColorTexture" ItemID="1" _name="_overlayColorTexture" Index="0">
              <ResourceReferencePath_ITexture Name="_value" _path="character/texture/original_handle.dds"/>
            </MaterialParameterTexture>
          </Vector></Material>
        </SkinnedMeshMaterialWrapper>
      </Vector>
    </SkinnedMeshProperty>
  </ModelProperty>
</ModelPropertyList>
"""

        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="character/modelproperty/test_weapon.pac_xml",
                material_wrapper_clones=[
                    SidecarMaterialWrapperClone(
                        target_material_name="Gem_inside",
                        donor_material_name="CD_PHM_02_Handle_0015",
                    ),
                    SidecarMaterialWrapperClone(
                        target_material_name="Gem_outside",
                        donor_material_name="CD_PHM_02_Handle_0015",
                    ),
                ],
            ),
        )

        vector_start = patched.index('<Vector Name="_subMeshResources">')
        vector_end = patched.index("</SkinnedMeshProperty>")
        vector_body = patched[vector_start:vector_end]
        self.assertIn('_subMeshName="Gem_inside"', vector_body)
        self.assertIn('_subMeshName="Gem_outside"', vector_body)
        self.assertIn('ItemID="1190" _subMeshName="Gem_inside"', patched)
        self.assertIn('ItemID="1191" _subMeshName="Gem_outside"', patched)
        self.assertIn('_materialName="SkinnedMeshStandard_Ver2"', patched)
        self.assertNotIn('_materialName="Gem_inside"', patched)
        self.assertNotIn('_materialName="Gem_outside"', patched)
        self.assertNotIn("</ModelProperty>\n<SkinnedMeshMaterialWrapper", patched)
        self.assertTrue(any("cloned source-owned material wrapper" in warning for warning in report.warnings))

    def test_complete_swap_updates_submesh_resources_idbase_after_pruning(self) -> None:
        sidecar_text = """
<ModelPropertyList>
  <ModelProperty>
    <SkinnedMeshProperty>
      <Vector Name="_subMeshResources" IdBase="1336" isOverrided="true">
        <SkinnedMeshMaterialWrapper ItemID="1338" _subMeshName="Gem_outside"/>
        <SkinnedMeshMaterialWrapper ItemID="1337" _subMeshName="Gem_inside"/>
        <SkinnedMeshMaterialWrapper ItemID="1339" _subMeshName="lambert1"/>
      </Vector>
    </SkinnedMeshProperty>
  </ModelProperty>
</ModelPropertyList>
"""

        from cdmw.modding.material_replacer import _sync_submesh_resources_vector_idbase

        patched, updates = _sync_submesh_resources_vector_idbase(sidecar_text)

        self.assertEqual(1, updates)
        self.assertIn('IdBase="1339"', patched)
        self.assertNotIn('IdBase="1336"', patched)

    def test_complete_swap_prunes_self_closing_stale_submesh_wrappers(self) -> None:
        sidecar_text = """
<ModelPropertyList>
  <ModelProperty>
    <SkinnedMeshProperty>
      <Vector Name="_subMeshResources" IdBase="1339" isOverrided="true">
        <SkinnedMeshMaterialWrapper ItemID="1337" _subMeshName="Blade">
          <Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2"/>
        </SkinnedMeshMaterialWrapper>
        <SkinnedMeshMaterialWrapper ItemID="1338" _subMeshName="Handle"/>
        <SkinnedMeshMaterialWrapper ItemID="1339" _subMeshName="Skull"/>
        <SkinnedMeshMaterialWrapper ItemID="1190" _subMeshName="cd_phm_02_sword_handle_0015"/>
      </Vector>
    </SkinnedMeshProperty>
  </ModelProperty>
</ModelPropertyList>
"""

        patched, removed = _prune_source_owned_sidecar_material_wrappers(
            sidecar_text,
            keep_material_names=("Blade", "Handle", "Skull"),
        )

        self.assertIn('_subMeshName="Blade"', patched)
        self.assertIn('_subMeshName="Handle"', patched)
        self.assertIn('_subMeshName="Skull"', patched)
        self.assertNotIn("cd_phm_02_sword_handle_0015", patched)
        self.assertEqual(["cd_phm_02_sword_handle_0015"], removed)

    def test_sidecar_patch_can_prune_removed_target_texture_parameters(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Remove_A">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/remove_a.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_normalTexture" _name="_normalTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/remove_a_n.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
  <SkinnedMeshMaterialWrapper _subMeshName="Keep_B">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/keep_b.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""
        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="target.pac_xml",
                prune_unmapped_texture_parameters=True,
                prune_material_names=["Remove_A"],
            ),
        )

        self.assertNotIn("remove_a.dds", patched)
        self.assertNotIn("remove_a_n.dds", patched)
        self.assertIn("keep_b.dds", patched)
        self.assertGreaterEqual(report.replaced_count, 2)

    def test_sidecar_patch_can_prune_unmapped_original_texture_parameters(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Keep_A">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/visible_base.dds"/>
      </MaterialParameterTexture>
      <MaterialParameterTexture StringItemID="_detailMaskTexture" _name="_detailMaskTexture" Index="1">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/hidden_detail.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""
        patched, report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path="target.pac_xml",
                prune_unmapped_texture_parameters=True,
                texture_parameter_keep_rules=[
                    ("_overlayColorTexture", "character/texture/visible_base.dds"),
                ],
            ),
        )

        self.assertIn("visible_base.dds", patched)
        self.assertNotIn("hidden_detail.dds", patched)
        self.assertGreaterEqual(report.replaced_count, 1)

    def test_build_texture_payloads_can_prune_removed_target_without_new_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar_entry = _entry("character/modelproperty/target.pac_xml", root)
            sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Remove_A">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/remove_a.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

            payloads, report = build_texture_replacement_payloads(
                obj_mesh=ParsedMesh(format="pac"),
                rebuilt_mesh=ParsedMesh(format="pac"),
                texture_files=(),
                original_texture_refs=(),
                original_sidecars=((sidecar_entry, sidecar_text),),
                submesh_mappings=(StaticSubmeshMapping(0, "Remove_A", [], 0),),
                texconv_path=None,
                read_original_texture_bytes=lambda _entry: b"",
                original_texture_source_path=lambda _entry: root / "unused.dds",
                pac_driven_sidecar=True,
                removed_target_material_names=("Remove_A",),
                prune_removed_target_texture_parameters=True,
            )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        self.assertNotIn("remove_a.dds", payloads[0].payload_data.decode("utf-8"))
        self.assertFalse(any(payload.target_path.endswith(".dds") for payload in payloads))
        self.assertTrue(any("Removed original target texture parameters" in warning for warning in report.warnings))

    def test_build_texture_payloads_can_prune_unmapped_original_refs_without_new_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar_entry = _entry("character/modelproperty/target.pac_xml", root)
            sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Target_A">
    <Material><Vector Name="_parameters">
      <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
        <ResourceReferencePath_ITexture Name="_value" _path="character/texture/original_base.dds"/>
      </MaterialParameterTexture>
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

            payloads, report = build_texture_replacement_payloads(
                obj_mesh=ParsedMesh(format="pac"),
                rebuilt_mesh=ParsedMesh(format="pac"),
                texture_files=(),
                original_texture_refs=(),
                original_sidecars=((sidecar_entry, sidecar_text),),
                submesh_mappings=(StaticSubmeshMapping(0, "Target_A", [], 0),),
                texconv_path=None,
                read_original_texture_bytes=lambda _entry: b"",
                original_texture_source_path=lambda _entry: root / "unused.dds",
                pac_driven_sidecar=True,
                prune_unmapped_original_texture_parameters=True,
            )

        self.assertEqual(["sidecar_generated"], [payload.kind for payload in payloads])
        self.assertNotIn("original_base.dds", payloads[0].payload_data.decode("utf-8"))
        self.assertTrue(any("unmapped original texture parameter" in warning for warning in report.warnings))

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

    def test_auto_companion_omits_sidecar_and_hkx_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry(
                "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac",
                root,
            )
            sidecar = _entry(
                "character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac_xml",
                root,
            )
            hkx = _entry(
                "character/bin__/meshphysics/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.hkx",
                root,
            )
            preview = MeshImportPreviewResult(
                rebuilt_data=b"mesh",
                parsed_mesh=ParsedMesh(format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
                texture_references=(
                    ArchiveModelTextureReference(resolved_entry=sidecar),
                    ArchiveModelTextureReference(resolved_entry=hkx),
                ),
            )

            companions = _mesh_import_auto_companion_entries(primary, preview)

            self.assertEqual(tuple(entry.path for entry in companions), ())

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

    def test_material_mask_bc1_encode_forces_opaque_alpha_to_preserve_rgb(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            source_png = root / "helmet_material_mask_arm_standard.png"
            original_dds = root / "original_ma.dds"
            Image.new("RGBA", (2, 2), (255, 192, 0, 0)).save(source_png)
            original_dds.write_bytes(_fake_dds_bytes(2, 2, mips=1, fourcc=b"DXT1"))
            seen_pixels: list[tuple[int, int, int, int]] = []

            def fake_native_encode(source: Path, target: Path, **kwargs: object) -> dict[str, object]:
                with Image.open(source) as image:
                    seen_pixels.append(image.convert("RGBA").getpixel((0, 0)))
                width = int(kwargs["width"])
                height = int(kwargs["height"])
                mips = int(kwargs["mip_count"])
                target.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"DXT1"))
                return {"ok": True}

            with patch("cdmw.core.texture_native.encode_dds_with_directxtex", side_effect=fake_native_encode):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("Helmet", "material_mask", source_png),
                    target_entry=object(),
                    texconv_path=None,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=TextureReplacementReport(),
                    on_log=None,
                )

            self.assertEqual([(255, 192, 0, 255)], seen_pixels)
            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            self.assertEqual("BC1_UNORM", parse_dds(output_dds).texconv_format)

    def test_non_material_bc1_encode_keeps_source_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            source_png = root / "replacement_Base_Color.png"
            original_dds = root / "original.dds"
            Image.new("RGBA", (2, 2), (10, 20, 30, 0)).save(source_png)
            original_dds.write_bytes(_fake_dds_bytes(2, 2, mips=1, fourcc=b"DXT1"))
            seen_pixels: list[tuple[int, int, int, int]] = []

            def fake_native_encode(source: Path, target: Path, **kwargs: object) -> dict[str, object]:
                with Image.open(source) as image:
                    seen_pixels.append(image.convert("RGBA").getpixel((0, 0)))
                width = int(kwargs["width"])
                height = int(kwargs["height"])
                mips = int(kwargs["mip_count"])
                target.write_bytes(_fake_dds_bytes(width, height, mips=mips, fourcc=b"DXT1"))
                return {"ok": True}

            with patch("cdmw.core.texture_native.encode_dds_with_directxtex", side_effect=fake_native_encode):
                _build_texture_payload(
                    ReplacementTextureSlot("replacement", "base", source_png),
                    target_entry=object(),
                    texconv_path=None,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=TextureReplacementReport(),
                    on_log=None,
                )

            self.assertEqual([(10, 20, 30, 0)], seen_pixels)

    def test_png_to_dds_falls_back_when_native_encode_writes_invalid_dds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_png = root / "replacement_Base_Color.png"
            original_dds = root / "original.dds"
            texconv = root / "texconv.exe"
            _write_fake_png_header(source_png, 128, 64)
            original_dds.write_bytes(_fake_dds_bytes(128, 64, mips=8))
            texconv.write_bytes(b"fake")
            report = TextureReplacementReport()

            def fake_native_encode(_source: Path, target: Path, **_kwargs: object) -> dict[str, object]:
                target.write_bytes(b"bad")
                return {"ok": True}

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                width = int(command[command.index("-w") + 1])
                height = int(command[command.index("-h") + 1])
                mips = int(command[command.index("-m") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(width, height, mips=mips))
                return 0, "", ""

            with patch("cdmw.core.texture_native.encode_dds_with_directxtex", side_effect=fake_native_encode), patch(
                "cdmw.core.common.run_process_with_cancellation",
                side_effect=fake_texconv,
            ):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("replacement", "base", source_png),
                    target_entry=object(),
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=report,
                    on_log=None,
                )

            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            self.assertEqual((128, 64), (parse_dds(output_dds).width, parse_dds(output_dds).height))
            self.assertTrue(any("invalid DDS" in warning and "falling back to texconv" in warning for warning in report.warnings))

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

    def test_dds_source_color_adjustment_is_baked_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            source_dds = root / "dark_base.dds"
            original_dds = root / "original.dds"
            Image.new("RGBA", (4, 4), (32, 32, 32, 255)).save(source_dds)
            Image.new("RGBA", (4, 4), (32, 32, 32, 255)).save(original_dds)
            entry = _entry("character/texture/sample.dds", root)
            report = TextureReplacementReport()
            encoded_sources: list[Path] = []

            def fake_native_encode(source: Path, target: Path, **_kwargs: object) -> dict[str, object]:
                encoded_sources.append(source)
                with Image.open(source) as image:
                    image.save(target)
                return {"ok": True}

            with patch("cdmw.core.texture_native.encode_dds_with_directxtex", side_effect=fake_native_encode):
                payload = _build_texture_payload(
                    ReplacementTextureSlot("replacement", "base", source_dds, base_color_lift=90),
                    target_entry=entry,
                    texconv_path=None,
                    read_original_texture_bytes=lambda _entry: original_dds.read_bytes(),
                    original_texture_source_path=lambda _entry: original_dds,
                    report=report,
                    on_log=None,
                )

            output_dds = root / "output.dds"
            output_dds.write_bytes(payload)
            with Image.open(output_dds) as image:
                pixel = image.convert("RGBA").getpixel((0, 0))

            self.assertEqual(1, len(encoded_sources))
            self.assertEqual(".png", encoded_sources[0].suffix.lower())
            self.assertGreater(pixel[0], 32)
            self.assertTrue(any("baking source color adjustment" in warning for warning in report.warnings))

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

    def test_external_catalogue_pbr_suffix_variants_are_detected(self) -> None:
        texture_sets = group_replacement_texture_sets(
            (
                Path("Helmet_baseColor.png"),
                Path("Helmet_occlusion.png"),
                Path("Helmet_specularGlossiness.png"),
                Path("Helmet_clearcoat.png"),
                Path("Helmet_emissive.png"),
            )
        )

        slots = texture_sets["helmet"].slots
        self.assertEqual("base", slots["base"].slot_kind)
        self.assertEqual("ao", slots["ao"].slot_kind)
        self.assertEqual("material", slots["material"].slot_kind)
        self.assertEqual("emissive", slots["emissive"].slot_kind)

    def test_gltf_material_texture_slots_can_attach_generic_texture_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "tex_0.png"
            normal = root / "tex_1.png"
            specular = root / "tex_2.png"
            emissive = root / "tex_3.png"
            for path in (base, normal, specular, emissive):
                path.write_bytes(b"")

            submesh = SubMesh(
                name="HelmetShell",
                material="HelmetShell",
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            submesh.texture_slots = (
                ("base", base),
                ("normal", normal),
                ("specular_glossiness", specular),
                ("emissive", emissive),
            )
            texture_sets = group_replacement_texture_sets(
                (base, normal, specular, emissive),
                obj_mesh=ParsedMesh(submeshes=[submesh]),
            )

            slots = texture_sets["helmetshell"].slots
            self.assertEqual(base, slots["base"].source_path)
            self.assertEqual(normal, slots["normal"].source_path)
            self.assertEqual(specular, slots["material"].source_path)
            self.assertEqual(emissive, slots["emissive"].source_path)

    def test_gltf_shared_texture_file_can_bind_to_multiple_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            root = Path(temp_dir)
            base = root / "Handle_baseColor.png"
            pbr = root / "Handle_metallicRoughness.png"
            normal = root / "Blade_normal.png"
            Image.new("RGBA", (2, 2), (120, 40, 190, 255)).save(base)
            Image.new("RGBA", (2, 2), (0, 240, 0, 255)).save(pbr)
            Image.new("RGBA", (2, 2), (128, 128, 255, 255)).save(normal)

            handle = SubMesh(
                name="Object_3",
                material="Handle",
                texture=str(base),
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            handle.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    parameter_name="_baseColorTexture",
                    source_texture_path=str(base),
                    preview_texture_path=str(base),
                    semantic_type="color",
                    semantic_subtype="albedo",
                    material_name="Handle",
                    confidence="gltf",
                ),
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_metallicRoughnessTexture",
                    source_texture_path=str(pbr),
                    preview_texture_path=str(pbr),
                    semantic_type="material",
                    semantic_subtype="metallic_roughness",
                    packed_channels=("roughness", "metallic"),
                    material_name="Handle",
                    confidence="gltf",
                ),
            )
            blade = SubMesh(
                name="Object_4",
                material="Blade",
                texture=str(base),
                vertices=[(0.0, 0.0, 0.0)],
                faces=[(0, 0, 0)],
            )
            blade.preview_material_texture_inputs = (
                PreviewMaterialTextureInput(
                    slot_kind="base",
                    parameter_name="_baseColorTexture",
                    source_texture_path=str(base),
                    preview_texture_path=str(base),
                    semantic_type="color",
                    semantic_subtype="albedo",
                    material_name="Blade",
                    confidence="gltf",
                ),
                PreviewMaterialTextureInput(
                    slot_kind="normal",
                    parameter_name="_normalTexture",
                    source_texture_path=str(normal),
                    preview_texture_path=str(normal),
                    semantic_type="normal",
                    semantic_subtype="normal",
                    material_name="Blade",
                    confidence="gltf",
                ),
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    parameter_name="_metallicRoughnessTexture",
                    source_texture_path=str(pbr),
                    preview_texture_path=str(pbr),
                    semantic_type="material",
                    semantic_subtype="metallic_roughness",
                    packed_channels=("roughness", "metallic"),
                    material_name="Blade",
                    confidence="gltf",
                ),
            )

            texture_sets = group_replacement_texture_sets(
                (base, pbr, normal),
                obj_mesh=ParsedMesh(submeshes=[handle, blade]),
            )

            blade_slots = texture_sets["blade"].slots
            self.assertEqual(base, blade_slots["base"].source_path)
            self.assertEqual(pbr, blade_slots["material"].source_path)
            self.assertEqual(normal, blade_slots["normal"].source_path)
            source_driven_slot_kinds = {
                slot.slot_kind
                for slot in _source_driven_slots(
                    texture_sets["blade"],
                    include_complete_support_fallbacks=True,
                    material_profile=get_complete_swap_material_profile("material_authority"),
                )
            }
            self.assertIn("base", source_driven_slot_kinds)
            self.assertIn("normal", source_driven_slot_kinds)
            self.assertIn("material_mask", source_driven_slot_kinds)

    def test_source_driven_sidecar_can_insert_emissive_texture_for_direct_swap(self) -> None:
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Blade">
    <Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">
      <Vector Name="_parameters">
        <MaterialParameterTexture StringItemID="_overlayColorTexture" _name="_overlayColorTexture" Index="0">
          <ResourceReferencePath_ITexture Name="_value" _path="character/texture/old_o.dds"/>
        </MaterialParameterTexture>
      </Vector>
    </Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {"Blade": (("_emissiveIntensityTexture", "character/texture/new_emi.dds", "emissive"),)},
        )

        self.assertEqual(1, changed_count)
        self.assertIn("character/texture/new_emi.dds", used_paths)
        self.assertIn("_emissiveIntensityTexture", patched)
        self.assertIn("SkinnedMeshEmissive_Ver2", patched)

    def test_runtime_xml_inserts_only_template_allowed_direct_slots(self) -> None:
        profile = get_complete_swap_material_profile("material_authority_runtime_xml")
        sidecar_text = """
<Root>
  <SkinnedMeshMaterialWrapper _subMeshName="Blade">
    <Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard_Ver2">
      <Vector Name="_parameters">
        <MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" _name="_renderSettingFlag" Index="0" _value="6"/>
      </Vector>
    </Material>
  </SkinnedMeshMaterialWrapper>
</Root>
"""

        patched, changed_count, used_paths, _changed_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {"Blade": (("_baseColorTexture", "character/texture/new_base.dds", "base"),)},
            exact_only=True,
            material_profile=profile,
            template_allowed_insertions={"blade": {"base": "_baseColorTexture"}},
        )

        self.assertEqual(1, changed_count)
        self.assertIn("character/texture/new_base.dds", used_paths)
        self.assertIn("_baseColorTexture", patched)
        self.assertNotIn("_colorBlendingMaskTexture", patched)

        skipped, skipped_count, skipped_paths, _ = _build_source_driven_sidecar_text(
            sidecar_text,
            {"Blade": (("_normalTexture", "character/texture/new_n.dds", "normal"),)},
            exact_only=True,
            material_profile=profile,
            template_allowed_insertions={},
        )

        self.assertEqual(0, skipped_count)
        self.assertFalse(skipped_paths)
        self.assertNotIn("character/texture/new_n.dds", skipped)

        unsafe_sidecar_text = sidecar_text.replace("SkinnedMeshStandard_Ver2", "SkinnedMeshEmissive_Ver2")
        recovered, recovered_count, recovered_paths, _ = _build_source_driven_sidecar_text(
            unsafe_sidecar_text,
            {"Blade": (("_baseColorTexture", "character/texture/recovered_base.dds", "base"),)},
            exact_only=True,
            material_profile=profile,
            template_allowed_insertions={"blade": {"base": "_baseColorTexture"}},
            template_shader_overrides={"blade": "SkinnedMeshStandard_Ver2"},
        )

        self.assertEqual(1, recovered_count)
        self.assertIn("character/texture/recovered_base.dds", recovered_paths)
        self.assertIn("SkinnedMeshStandard_Ver2", recovered)

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
        direction = classify_texture_binding("_directionTexture", "character/texture/helmet_dr.dds")
        self.assertEqual("vector", direction.semantic_type)
        self.assertFalse(direction.visualized)

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

        patched_text, changed_wrappers, used_paths, changed_wrapper_names = _build_source_driven_sidecar_text(
            sidecar_text,
            {
                "cd_phm_00_hel_0013_05": (
                    ("_overlayColorTexture", "character/texture/generated_o.dds", "base"),
                    ("_normalTexture", "character/texture/generated_n.dds", "normal"),
                )
            },
        )

        self.assertEqual(1, changed_wrappers)
        self.assertEqual({"cd_phm_00_hel_0013_05"}, changed_wrapper_names)
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
            blade_normal = root / "blade.001_Normal_GreenUp.png"
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

    def test_texture_sets_use_gltf_material_metadata_when_texture_filename_differs(self) -> None:
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

            self.assertEqual("Material.030", chosen["cd_phm_08_musket_scope_0006"])
            self.assertEqual(2, texture_sets["material.030"].source_face_count)
            self.assertEqual("Material.030", texture_sets["material.030"].slots["base"].material_name)

    def test_texture_sets_use_obj_material_texture_reference_without_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_dir = root / "textures"
            texture_dir.mkdir()
            source_texture = texture_dir / "wood.png"
            source_texture.write_bytes(b"")

            obj_mesh = ParsedMesh(
                path="imported_prop.obj",
                format="obj",
                submeshes=[
                    SubMesh(
                        name="Board",
                        material="WoodMaterial",
                        texture="textures/wood.png",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[(0, 0, 0)],
                    )
                ],
            )

            texture_sets = group_replacement_texture_sets((source_texture,), obj_mesh=obj_mesh)
            self.assertNotIn("woo", texture_sets)
            self.assertIn("woodmaterial", texture_sets)
            slots = texture_sets["woodmaterial"].slots
            self.assertEqual("wood.png", slots["base"].source_path.name)

            routes = build_source_material_routing_plan(
                obj_mesh,
                texture_sets,
                (
                    StaticSubmeshMapping(
                        target_submesh_index=0,
                        target_submesh_name="CD_Wooden_Panel_0001",
                        source_submesh_indices=[0],
                        target_material_slot_index=0,
                    ),
                ),
            )

            self.assertEqual(1, len(routes))
            self.assertEqual("Ready", routes[0].status)
            self.assertEqual("WoodMaterial", routes[0].source_material_name)
            self.assertIn("base", routes[0].detected_roles)

    def test_texture_sets_do_not_parse_plain_words_as_one_letter_suffixes(self) -> None:
        texture_sets = group_replacement_texture_sets((Path("wood.png"), Path("iron.png"), Path("cloak.png")))

        self.assertEqual({}, texture_sets)

    def test_texture_sets_detect_single_material_files_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texture_files = (
                root / "Base Color.png",
                root / "Normal GreenUp.png",
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
            self.assertEqual("Normal GreenUp.png", slots["normal"].source_path.name)
            self.assertEqual("green_up", slots["normal"].normal_space)
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
            normal = root / "Handle.002 Normal GreenUp.png"
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
            self.assertEqual("Handle.002 Normal GreenUp.png", slots["normal"].source_path.name)
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
            stale_audit_path = root / "Mesh Mod_cdmw_active_file_authority_audit.json"
            stale_audit_path.write_text("stale", encoding="utf-8")

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
            self.assertIsNone(result.authority_audit_path)
            self.assertEqual(0, result.authority_mismatch_count)
            self.assertFalse((result.package_root / "cdmw_active_file_authority_audit.json").exists())
            self.assertFalse(stale_audit_path.exists())
            self.assertFalse(
                (result.package_root.parent / f"{result.package_root.name}_cdmw_active_file_authority_audit.json").exists()
            )
            manifest = json.loads((result.package_root / "manifest.json").read_text(encoding="utf-8"))
            files = {item["path"]: item for item in manifest["files"]}
            self.assertIn("Generated replacement texture", files["character/texture/generated.dds"]["note"])
            self.assertIn("Patched material sidecar", files["character/modelproperty/test_weapon.pac_xml"]["note"])

    def test_mesh_loose_export_active_file_authority_audit_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry("character/model/weapon/test_weapon.pac", root)
            active_loose = root / "character" / "model" / "weapon" / "test_weapon.pac"
            active_loose.parent.mkdir(parents=True, exist_ok=True)
            active_loose.write_bytes(b"stale")
            preview = MeshImportPreviewResult(
                rebuilt_data=b"rebuilt",
                parsed_mesh=ParsedMesh(path=primary.path, format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
            )

            result = export_archive_mesh_payloads_to_mod_ready_loose(
                (ArchivePatchRequest(primary, b"rebuilt"),),
                primary_entry=primary,
                preview_result=preview,
                source_obj_path=root / "source.obj",
                parent_root=root,
                package_info=ModPackageInfo(title="Mesh Mod Audit"),
                export_options=ModPackageExportOptions(create_active_file_authority_audit=True),
                related_entries_to_include=(),
            )

            expected_audit_path = root / "Mesh Mod Audit_cdmw_active_file_authority_audit.json"
            self.assertEqual(expected_audit_path, result.authority_audit_path)
            self.assertEqual(1, result.authority_mismatch_count)
            self.assertTrue(expected_audit_path.exists())
            audit = json.loads(expected_audit_path.read_text(encoding="utf-8"))
            self.assertEqual("cdmw_active_file_authority_audit_v1", audit["schema"])
            self.assertEqual(1, audit["mismatch_count"])
            self.assertEqual("mismatch", audit["rows"][0]["status"])

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

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                faithful_payloads, faithful_report = build_texture_replacement_payloads(
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
                    neutralize_inherited_material_layers=True,
                )

            faithful_by_path = {payload.target_path: payload for payload in faithful_payloads}
            faithful_sidecar_payload = faithful_by_path[sidecar_entry.path]
            faithful_sidecar = faithful_sidecar_payload.payload_data.decode("utf-8")
            self.assertIn("source-color faithful mode", faithful_sidecar_payload.note)
            self.assertIn("_overlayColorTexture", faithful_sidecar)
            self.assertIn("_normalTexture", faithful_sidecar)
            self.assertNotIn("_colorBlendingMaskTexture", faithful_sidecar)
            self.assertNotIn("_grimeDiffuseTextureG", faithful_sidecar)
            self.assertNotIn("cd_texturelayer_003_0101.dds", faithful_sidecar)
            self.assertTrue(any("source-color faithful mode" in warning for warning in faithful_report.warnings))

    def test_source_color_faithful_neutralizes_default_patched_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            texconv = root / "texconv.exe"
            texconv.write_bytes(b"fake")
            base_source = root / "lambert1_baseColor.png"
            normal_source = root / "lambert1_normal.png"
            _write_fake_png_header(base_source, 512, 512)
            _write_fake_png_header(normal_source, 512, 512)
            template_base = root / "template_base.dds"
            template_normal = root / "template_normal.dds"
            template_base.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            template_normal.write_bytes(_fake_dds_bytes(512, 512, mips=10))
            base_entry = _entry("character/texture/cd_phm_02_sword_0036_o.dds", root)
            normal_entry = _entry("character/texture/cd_phm_02_sword_0036_n.dds", root)
            sidecar_entry = _entry("character/modelproperty/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0036.pac_xml", root)
            original_refs = (
                ArchiveModelTextureReference(
                    reference_name=base_entry.path,
                    material_name="cd_phm_02_sword_0036",
                    sidecar_parameter_name="_overlayColorTexture",
                    resolved_archive_path=base_entry.path,
                    resolved_entry=base_entry,
                ),
                ArchiveModelTextureReference(
                    reference_name=normal_entry.path,
                    material_name="cd_phm_02_sword_0036",
                    sidecar_parameter_name="_normalTexture",
                    resolved_archive_path=normal_entry.path,
                    resolved_entry=normal_entry,
                ),
            )
            sidecar_text = (
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="cd_phm_02_sword_handle_0036_01"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_grimeDiffuseTextureR"><ResourceReferencePath_ITexture _path="character/texture/grime.dds"/></MaterialParameterTexture>'
                '<MaterialParameterBitFlag32 _name="_colorBlendingFlag" _value="4095" Index="3"/>'
                "</Vector></SkinnedMeshMaterialWrapper>"
                '<SkinnedMeshMaterialWrapper _subMeshName="cd_phm_02_sword_0036"><Vector Name="_parameters">'
                '<MaterialParameterTexture _name="_normalTexture"><ResourceReferencePath_ITexture _path="character/texture/original_n.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_overlayColorTexture"><ResourceReferencePath_ITexture _path="character/texture/original_o.dds"/></MaterialParameterTexture>'
                '<MaterialParameterTexture _name="_detailMaskTexture"><ResourceReferencePath_ITexture _path="character/texture/detail.dds"/></MaterialParameterTexture>'
                '<MaterialParameterBitFlag32 _name="_colorBlendingFlag" _value="4095" Index="3"/>'
                "</Vector></SkinnedMeshMaterialWrapper></Root>"
            )
            obj_mesh = ParsedMesh(
                submeshes=[SubMesh(name="lambert1", material="lambert1", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])]
            )
            rebuilt_mesh = ParsedMesh(
                submeshes=[
                    SubMesh(name="cd_phm_02_sword_handle_0036_01", material="cd_phm_02_sword_handle_0036_01", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                    SubMesh(name="cd_phm_02_sword_0036", material="cd_phm_02_sword_0036", vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)]),
                ]
            )
            mappings = (
                StaticSubmeshMapping(0, "cd_phm_02_sword_handle_0036_01", [0], 0),
                StaticSubmeshMapping(1, "cd_phm_02_sword_0036", [0], 1),
            )

            def fake_texconv(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
                out_dir = Path(command[command.index("-o") + 1])
                produced = out_dir / f"{Path(command[-1]).stem}.dds"
                produced.write_bytes(_fake_dds_bytes(512, 512, mips=10))
                return 0, "", ""

            with patch("cdmw.core.common.run_process_with_cancellation", side_effect=fake_texconv):
                payloads, report = build_texture_replacement_payloads(
                    obj_mesh=obj_mesh,
                    rebuilt_mesh=rebuilt_mesh,
                    texture_files=(base_source, normal_source),
                    original_texture_refs=original_refs,
                    original_sidecars=((sidecar_entry, sidecar_text),),
                    submesh_mappings=mappings,
                    texconv_path=texconv,
                    read_original_texture_bytes=lambda entry: template_base.read_bytes() if entry is base_entry else template_normal.read_bytes(),
                    original_texture_source_path=lambda entry: template_base if entry is base_entry else template_normal,
                    pac_driven_sidecar=True,
                    neutralize_inherited_material_layers=True,
                )

            patched_sidecar = {payload.target_path: payload for payload in payloads}[sidecar_entry.path].payload_data.decode("utf-8")
            self.assertNotIn("_grimeDiffuseTextureR", patched_sidecar)
            self.assertNotIn("_detailMaskTexture", patched_sidecar)
            self.assertNotIn('_value="4095"', patched_sidecar)
            self.assertIn('_value="0"', patched_sidecar)
            self.assertTrue(any("Neutralized inherited material layers" in warning for warning in report.warnings))

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
