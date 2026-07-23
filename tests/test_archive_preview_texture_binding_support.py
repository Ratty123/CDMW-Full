from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import unittest
from unittest.mock import patch

from cdmw.core.archive import (
    _ArchiveModelSidecarTextureBinding,
    _archive_texture_family_mismatch_summary,
    _attach_model_sidecar_texture_preview_paths,
    _attach_model_texture_preview_paths,
    _attach_model_support_texture_preview_paths,
    _build_model_preview_texture_slot_detail_text,
    _iter_model_sidecar_binding_submesh_keys,
    normalize_texture_reference_for_sidecar_lookup,
)
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings
from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.services.pac_material_graph import build_pac_material_graph_v1


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0000/0.pamt"),
        paz_file=Path("0000/1.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def _texture_maps(*paths: str):
    by_normalized = defaultdict(list)
    by_basename = defaultdict(list)
    for path in paths:
        entry = _entry(path)
        by_normalized[normalize_texture_reference_for_sidecar_lookup(path)].append(entry)
        by_basename[Path(path).name.lower()].append(entry)
    return by_normalized, by_basename



class ArchivePreviewTextureBindingSupportTests(unittest.TestCase):
    def test_emissive_sidecar_binding_uses_emissive_channel_not_base(self) -> None:
        source_entry = _entry("character/model/cd_test_lantern.pac")
        emissive_path = "character/texture/cd_test_lantern_emissive.dds"
        by_normalized, by_basename = _texture_maps(emissive_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Lantern")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path=emissive_path,
                parameter_name="_emissiveTexture",
                submesh_name="CD_Test_Lantern",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        self.assertEqual("", mesh.preview_texture_path)
        self.assertEqual(f"preview://{emissive_path}", mesh.preview_emissive_texture_path)
        self.assertEqual(emissive_path, mesh.preview_emissive_texture_name)
        self.assertEqual("emissive", mesh.preview_material_texture_inputs[0].semantic_type)
        self.assertIn("Exact sidecar emissive bindings", "\n".join(lines))

    def test_base_texture_is_not_reused_as_emissive_sibling_fallback(self) -> None:
        source_entry = _entry("character/model/cd_test_cloth.pac")
        base_path = "character/texture/cd_test_cloth.dds"
        by_normalized, by_basename = _texture_maps(base_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Cloth",
                    texture_name=base_path,
                    preview_texture_path=f"preview://{base_path}",
                )
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_emissive_texture_path)
        self.assertNotIn("emissive bindings", "\n".join(lines))

    def test_emissive_sibling_fallback_requires_matching_material_family(self) -> None:
        source_entry = _entry("character/model/cd_test_sword.pac")
        blade_emissive = "character/texture/cd_test_blade_0014_emi.dds"
        by_normalized, by_basename = _texture_maps(blade_emissive)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Blade_0014",
                    texture_name="CD_Test_Blade_0014",
                    preview_sidecar_shader_family="SkinnedMeshEmissive_Ver2",
                ),
                ModelPreviewMesh(
                    material_name="CD_Test_Handle_0014",
                    texture_name="CD_Test_Handle_0014",
                ),
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual(f"preview://{blade_emissive}", model.meshes[0].preview_emissive_texture_path)
        self.assertEqual("", model.meshes[1].preview_emissive_texture_path)

    def test_emissive_sibling_fallback_requires_declared_emissive_authority(self) -> None:
        source_entry = _entry("character/model/cd_test_cloth.pac")
        cloth_emissive = "character/texture/cd_test_cloth_0011_emi.dds"
        by_normalized, by_basename = _texture_maps(cloth_emissive)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Cloth_0011",
                    texture_name="CD_Test_Cloth_0011",
                    preview_sidecar_shader_family="SkinnedMeshCloth_Ver2",
                ),
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_emissive_texture_path)

    def test_emissive_sibling_fallback_rejects_zero_intensity_and_black_color(self) -> None:
        source_entry = _entry("character/model/cd_test_cloth.pac")
        cloth_emissive = "character/texture/cd_test_cloth_0011_emi.dds"
        by_normalized, by_basename = _texture_maps(cloth_emissive)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Cloth_0011",
                    texture_name="CD_Test_Cloth_0011",
                    preview_native_material_overrides={
                        "emissive_intensity": 0.0,
                        "emissive_color": "#000000",
                    },
                    preview_material_parameters=(
                        PreviewMaterialParameterInput(
                            parameter_name="_EmissiveIntensity",
                            numeric_value=0.0,
                        ),
                        PreviewMaterialParameterInput(
                            parameter_name="_EmissiveColor",
                            color_value=(0.0, 0.0, 0.0),
                        ),
                    ),
                ),
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_emissive_texture_path)

    def test_emissive_sibling_fallback_accepts_declared_texture_binding(self) -> None:
        source_entry = _entry("character/model/cd_test_rune.pac")
        rune_emissive = "character/texture/cd_test_rune_0001_emi.dds"
        by_normalized, by_basename = _texture_maps(rune_emissive)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Test_Rune_0001",
                    texture_name="CD_Test_Rune_0001",
                    preview_material_texture_inputs=(
                        PreviewMaterialTextureInput(
                            slot_kind="emissive",
                            parameter_name="_emissiveTexture",
                            semantic_type="emissive",
                        ),
                    ),
                ),
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual(f"preview://{rune_emissive}", model.meshes[0].preview_emissive_texture_path)

    def test_anonymous_wrapper_order_does_not_spread_emissive_maps(self) -> None:
        source_entry = _entry("character/model/cd_test_sword.pac")
        paths = (
            "character/texture/cd_test_blade_0014_emi.dds",
            "character/texture/cd_test_acc_0037_emi.dds",
        )
        by_normalized, by_basename = _texture_maps(*paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="unknown_10"),
                ModelPreviewMesh(material_name="unknown_20"),
            ],
        )
        bindings = tuple(
            _ArchiveModelSidecarTextureBinding(
                texture_path=path,
                parameter_name="_emissiveIntensityTexture",
                submesh_name=f"wrapper_{index}",
            )
            for index, path in enumerate(paths)
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertTrue(all(not mesh.preview_emissive_texture_path for mesh in model.meshes))

    def test_placeholder_none_texture_is_not_applied_as_support_map(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("texture/nonetexture0x00000000.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Handle", texture_name="CD_Test_Handle")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="texture/nonetexture0x00000000.dds",
                parameter_name="_normalTexture",
                submesh_name="CD_Test_Handle",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("", model.meshes[0].preview_normal_texture_path)
        self.assertNotIn("Exact sidecar normal-map bindings", "\n".join(lines))

    def test_sidecar_material_color_survives_missing_visible_dds(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps()
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="CD_Test_Blade", texture_name="CD_Test_Blade")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path="character/texture/missing_base.dds",
                parameter_name="_baseColorTexture",
                submesh_name="CD_Test_Blade",
                sidecar_kind="pac_xml",
                tint_color=(0.22, 0.26, 0.42),
            ),
        )

        lines = _attach_model_sidecar_texture_preview_paths(
            source_entry,
            model,
            parsed_mesh=None,
            sidecar_texture_bindings=bindings,
            visible_texture_mode="mesh_base_first",
            texture_entries_by_normalized_path=by_normalized,
            texture_entries_by_basename=by_basename,
        )

        self.assertEqual((0.22, 0.26, 0.42), model.meshes[0].preview_color)
        self.assertEqual("", model.meshes[0].preview_texture_path)
        self.assertEqual("material_color_fallback", model.meshes[0].preview_base_texture_quality)
        self.assertIn("material color fallback", "\n".join(lines))

    def test_material_name_base_fallback_uses_visible_sibling_dds(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps(
            "character/texture/part_a_d.dds",
            "character/texture/part_a_n.dds",
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="part_a", texture_name="part_a")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_texture_preview_paths(
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a_d.dds", model.meshes[0].texture_name)
        self.assertEqual("preview://character/texture/part_a_d.dds", model.meshes[0].preview_texture_path)

    def test_material_name_base_correction_can_replace_sidecar_layer_fallback(self) -> None:
        source_entry = _entry("character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac")
        head_texture = "character/texture/cd_phm_00_head_00_0001_01.dds"
        layer_texture = "character/texture/cd_texturelayer_001_0101.dds"
        by_normalized, by_basename = _texture_maps(head_texture, layer_texture)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_PHM_00_Head_0001_01",
                    texture_name=head_texture,
                    preview_texture_path=f"preview://{layer_texture}",
                    preview_base_texture_source="pac_xml",
                )
            ],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_texture_preview_paths(
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
                override_existing_base=True,
                prefer_material_name_for_base=True,
            )

        self.assertEqual(head_texture, model.meshes[0].texture_name)
        self.assertEqual(f"preview://{head_texture}", model.meshes[0].preview_texture_path)
        self.assertIn("Corrected 1 mesh base texture preview", "\n".join(lines))

    def test_technical_sibling_dds_is_not_promoted_to_visible_base(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        by_normalized, by_basename = _texture_maps("character/texture/part_a_n.dds")
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="part_a", texture_name="part_a")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_texture_preview_paths(
                source_entry,
                model,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("part_a", model.meshes[0].texture_name)
        self.assertEqual("", model.meshes[0].preview_texture_path)

    def test_anonymous_meshes_use_ordered_sidecar_support_bindings(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = (
            "character/texture/part_a_n.dds",
            "character/texture/part_b_n.dds",
            "character/texture/part_a_ma.dds",
            "character/texture/part_b_ma.dds",
            "character/texture/part_a_disp.dds",
            "character/texture/part_b_disp.dds",
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name="unknown_10", texture_name="unknown_10"),
                ModelPreviewMesh(material_name="unknown_20", texture_name="unknown_20"),
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_n.dds", "_normalTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_n.dds", "_normalTexture", "Part_B"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_ma.dds", "_materialTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_ma.dds", "_materialTexture", "Part_B"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_disp.dds", "_heightTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding("character/texture/part_b_disp.dds", "_heightTexture", "Part_B"),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual("character/texture/part_a_n.dds", model.meshes[0].preview_normal_texture_name)
        self.assertEqual("character/texture/part_b_n.dds", model.meshes[1].preview_normal_texture_name)
        normal_input = next(
            item for item in model.meshes[0].preview_material_texture_inputs if item.slot_kind == "normal"
        )
        self.assertEqual("green_up", normal_input.normal_space)
        self.assertEqual("character/texture/part_a_ma.dds", model.meshes[0].preview_material_texture_name)
        self.assertEqual("character/texture/part_b_disp.dds", model.meshes[1].preview_height_texture_name)
        self.assertIn("anonymous support-map", "\n".join(lines))

    def test_exact_sidecar_support_preserves_multiple_material_inputs_for_preview(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = (
            "character/texture/part_a_ma.dds",
            "character/texture/part_a_sp.dds",
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding("character/texture/part_a_ma.dds", "_materialTexture", "Part_A"),
            _ArchiveModelSidecarTextureBinding(
                "character/texture/part_a_sp.dds",
                "_specularTexture",
                "Part_A",
                srgb_mode="linear",
                parameter_declared_by="pac_xml",
                material_output_quality="layer",
                layer_role="material_response",
                layer_channel="g",
                blend_flags=("role:material_response", "channel:g"),
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_inputs = [
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.slot_kind == "material"
        ]
        self.assertEqual(
            {
                "character/texture/part_a_ma.dds",
                "character/texture/part_a_sp.dds",
            },
            {item.source_texture_path for item in material_inputs},
        )
        specular_input = next(item for item in material_inputs if item.source_texture_path.endswith("_sp.dds"))
        self.assertEqual("character/texture/part_a_sp.dds", specular_input.source_dds_path)
        self.assertEqual("linear", specular_input.srgb_mode)
        self.assertEqual("pac_xml", specular_input.parameter_declared_by)
        self.assertEqual("layer", specular_input.material_output_quality)
        self.assertEqual("material_response", specular_input.layer_role)
        self.assertEqual("g", specular_input.layer_channel)
        self.assertIn("channel:g", specular_input.blend_flags)
        self.assertIn("material diagnostics and preview", "\n".join(lines))

    def test_exact_punctuation_identity_excludes_conflicting_fuzzy_sidecar_bindings(self) -> None:
        source_entry = _entry("character/model/cd_test_lightsource.pac")
        copper_base = "character/texture/cd_metal_copper_01.dds"
        copper_material = "character/texture/cd_metal_copper_01_sp.dds"
        coffin_base = "character/texture/cd_common_coffin_01.dds"
        coffin_material = "character/texture/cd_common_coffin_01_sp.dds"
        by_normalized, by_basename = _texture_maps(
            copper_base,
            copper_material,
            coffin_base,
            coffin_material,
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="CD_Common_Coffin_01",
                    texture_name="07 - Default",
                )
            ],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                copper_base,
                "_baseColorTexture",
                part_name="07___default",
                material_name="07___default",
            ),
            _ArchiveModelSidecarTextureBinding(
                copper_material,
                "_materialTexture",
                part_name="07___default",
                material_name="07___default",
            ),
            _ArchiveModelSidecarTextureBinding(
                coffin_base,
                "_baseColorTexture",
                part_name="07 - default",
                material_name="07 - default",
            ),
            _ArchiveModelSidecarTextureBinding(
                coffin_material,
                "_materialTexture",
                part_name="07 - default",
                material_name="07 - default",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        self.assertEqual(f"preview://{coffin_base}", mesh.preview_texture_path)
        self.assertEqual(coffin_material, mesh.preview_material_texture_name)
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertIn(coffin_base, material_sources)
        self.assertIn(coffin_material, material_sources)
        self.assertNotIn(copper_base, material_sources)
        self.assertNotIn(copper_material, material_sources)

    def test_ambiguous_fuzzy_sidecar_identity_is_not_used_as_a_fallback(self) -> None:
        source_entry = _entry("character/model/cd_test_lightsource.pac")
        copper_base = "character/texture/cd_metal_copper_01.dds"
        copper_material = "character/texture/cd_metal_copper_01_sp.dds"
        coffin_base = "character/texture/cd_common_coffin_01.dds"
        coffin_material = "character/texture/cd_common_coffin_01_sp.dds"
        by_normalized, by_basename = _texture_maps(
            copper_base,
            copper_material,
            coffin_base,
            coffin_material,
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="07 default", texture_name="07 default")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                copper_base,
                "_baseColorTexture",
                part_name="07___default",
                material_name="07___default",
            ),
            _ArchiveModelSidecarTextureBinding(
                copper_material,
                "_materialTexture",
                part_name="07___default",
                material_name="07___default",
            ),
            _ArchiveModelSidecarTextureBinding(
                coffin_base,
                "_baseColorTexture",
                part_name="07 - default",
                material_name="07 - default",
            ),
            _ArchiveModelSidecarTextureBinding(
                coffin_material,
                "_materialTexture",
                part_name="07 - default",
                material_name="07 - default",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        self.assertEqual("", mesh.preview_texture_path)
        self.assertEqual("", mesh.preview_material_texture_path)
        self.assertEqual((), mesh.preview_material_texture_inputs)

    def test_unique_fuzzy_sidecar_identity_remains_a_support_fallback(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        normal_path = "character/texture/part_a_n.dds"
        by_normalized, by_basename = _texture_maps(normal_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part A", texture_name="Part A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                normal_path,
                "_normalTexture",
                submesh_name="Part_A",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        self.assertEqual(normal_path, model.meshes[0].preview_normal_texture_name)

    def test_exact_sidecar_identity_selects_the_whole_connected_material_graph(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        base_path = "character/texture/part_a.dds"
        material_path = "character/texture/part_a_ma.dds"
        by_normalized, by_basename = _texture_maps(base_path, material_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part A", texture_name="Part A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                base_path,
                "_baseColorTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                material_path,
                "_materialTexture",
                submesh_name="Part_A",
                material_name="Part A",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertEqual(f"preview://{base_path}", mesh.preview_texture_path)
        self.assertIn(base_path, material_sources)
        self.assertIn(material_path, material_sources)

    def test_unique_fuzzy_sidecar_identity_selects_the_whole_connected_material_graph(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        base_path = "character/texture/part_a.dds"
        material_path = "character/texture/part_a_ma.dds"
        by_normalized, by_basename = _texture_maps(base_path, material_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part-A", texture_name="Part-A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                base_path,
                "_baseColorTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                material_path,
                "_materialTexture",
                submesh_name="Part_A",
                material_name="Part A",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertEqual(f"preview://{base_path}", mesh.preview_texture_path)
        self.assertIn(base_path, material_sources)
        self.assertIn(material_path, material_sources)

    def test_shared_material_alias_does_not_merge_distinct_submesh_graphs(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        part_a_base = "character/texture/part_a.dds"
        part_a_material = "character/texture/part_a_ma.dds"
        part_b_base = "character/texture/part_b.dds"
        part_b_material = "character/texture/part_b_ma.dds"
        by_normalized, by_basename = _texture_maps(
            part_a_base,
            part_a_material,
            part_b_base,
            part_b_material,
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Shared")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                part_a_base,
                "_baseColorTexture",
                submesh_name="Part_A",
                material_name="Shared",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_a_material,
                "_materialTexture",
                submesh_name="Part_A",
                material_name="Shared",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_base,
                "_baseColorTexture",
                submesh_name="Part_B",
                material_name="Shared",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_material,
                "_materialTexture",
                submesh_name="Part_B",
                material_name="Shared",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertEqual(f"preview://{part_a_base}", mesh.preview_texture_path)
        self.assertIn(part_a_base, material_sources)
        self.assertIn(part_a_material, material_sources)
        self.assertNotIn(part_b_base, material_sources)
        self.assertNotIn(part_b_material, material_sources)

    def test_exact_sidecar_owner_prevents_unrelated_fuzzy_candidate_promotion(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        part_a_base = "character/texture/part_a.dds"
        part_a_material = "character/texture/part_a_ma.dds"
        part_b_base = "character/texture/part_b.dds"
        part_b_material = "character/texture/part_b_ma.dds"
        by_normalized, by_basename = _texture_maps(
            part_a_base,
            part_a_material,
            part_b_base,
            part_b_material,
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part-B")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                part_a_base,
                "_baseColorTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_a_material,
                "_materialTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_base,
                "_baseColorTexture",
                submesh_name="Part_B",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_material,
                "_materialTexture",
                submesh_name="Part_B",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertEqual(f"preview://{part_a_base}", mesh.preview_texture_path)
        self.assertIn(part_a_base, material_sources)
        self.assertIn(part_a_material, material_sources)
        self.assertNotIn(part_b_base, material_sources)
        self.assertNotIn(part_b_material, material_sources)

    def test_distinct_fuzzy_sidecar_candidates_do_not_promote_multiple_graphs(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        part_a_base = "character/texture/part_a.dds"
        part_b_base = "character/texture/part_b.dds"
        by_normalized, by_basename = _texture_maps(part_a_base, part_b_base)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part A", texture_name="Part B")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                part_a_base,
                "_baseColorTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_base,
                "_baseColorTexture",
                submesh_name="Part_B",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        self.assertEqual("", mesh.preview_texture_path)
        self.assertEqual((), mesh.preview_material_texture_inputs)

    def test_exact_sidecar_candidate_precedence_selects_one_graph(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        part_a_base = "character/texture/part_a.dds"
        part_b_base = "character/texture/part_b.dds"
        by_normalized, by_basename = _texture_maps(part_a_base, part_b_base)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_B")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                part_a_base,
                "_baseColorTexture",
                submesh_name="Part_A",
            ),
            _ArchiveModelSidecarTextureBinding(
                part_b_base,
                "_baseColorTexture",
                submesh_name="Part_B",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_sidecar_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                visible_texture_mode="layer_aware_visible",
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        mesh = model.meshes[0]
        material_sources = {
            item.source_texture_path
            for item in mesh.preview_material_texture_inputs
        }
        self.assertEqual(f"preview://{part_a_base}", mesh.preview_texture_path)
        self.assertIn(part_a_base, material_sources)
        self.assertNotIn(part_b_base, material_sources)

    def test_exact_sidecar_material_input_survives_preview_conversion_failure(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_path = "character/texture/part_a_ma.dds"
        by_normalized, by_basename = _texture_maps(texture_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path,
                "_materialTexture",
                "Part_A",
                sidecar_kind="pac_xml",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=RuntimeError("native preview decode failed"),
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_input = next(
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.parameter_name == "_materialTexture"
        )
        self.assertEqual(texture_path, material_input.source_texture_path)
        self.assertEqual(texture_path, material_input.source_dds_path)
        self.assertEqual("", material_input.preview_texture_path)
        self.assertFalse(material_input.visualized)
        self.assertIn("material diagnostics and preview", "\n".join(lines))

    def test_owner_qualified_pac_family_alias_keeps_declared_reference_and_transport(self) -> None:
        source_entry = _entry("character/model/cd_phm_01_mace_0035.pac")
        declared_base = "tree/texture/branch_broad_cotton_01_color.dds"
        declared_material = "tree/texture/branch_broad_cotton_01_subsurface.dds"
        transport_base = "character/texture/branch_broad_cotton_01.dds"
        transport_material = "character/texture/branch_broad_cotton_01_sp.dds"
        by_normalized, by_basename = _texture_maps(transport_base, transport_material)
        parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_baseColorTexture",
                texture_path=declared_base,
            ),
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_materialTexture",
                texture_path=declared_material,
            ),
        )
        common = {
            "submesh_name": "Branch",
            "material_name": "Branch",
            "shader_family": "SkinnedMeshStandard_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 0,
            "owner_wrapper_item_id": "42",
            "binding_authority": "authoritative",
            "binding_disposition": "promoted",
            "material_parameters": parameters,
        }
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_base,
                parameter_name="_baseColorTexture",
                source_kind="crimson_base_color",
                **common,
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_material,
                parameter_name="_materialTexture",
                source_kind="crimson_standard_material_response",
                **common,
            ),
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Branch", texture_name="Branch")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        inputs = {
            item.parameter_name: item
            for item in model.meshes[0].preview_material_texture_inputs
        }
        self.assertEqual(declared_base, inputs["_baseColorTexture"].source_texture_path)
        self.assertEqual(transport_base, inputs["_baseColorTexture"].source_dds_path)
        self.assertEqual(declared_material, inputs["_materialTexture"].source_texture_path)
        self.assertEqual(transport_material, inputs["_materialTexture"].source_dds_path)
        self.assertEqual("sidecar-family-transport", inputs["_baseColorTexture"].confidence)
        graph = build_pac_material_graph_v1(model.meshes[0], {})
        self.assertTrue(graph["binding_conservation"]["conserved"])
        self.assertEqual([], graph["binding_conservation"]["dropped_parameters"])

    def test_owner_qualified_numbered_mask_variant_uses_shipped_family_transport(self) -> None:
        source_entry = _entry("character/model/cd_ptm_01_hel_00_0354_03.pac")
        declared_material = "character/texture/cd_phm_00_hel_00_0354_03_ma.dds"
        declared_detail = "character/texture/cd_phm_00_hel_00_0354_03_mg.dds"
        transport_material = "character/texture/cd_phm_00_hel_00_0354_ma.dds"
        transport_detail = "character/texture/cd_phm_00_hel_00_0354_mg.dds"
        by_normalized, by_basename = _texture_maps(transport_material, transport_detail)
        parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_colorBlendingMaskTexture",
                texture_path=declared_material,
            ),
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_detailMaskTexture",
                texture_path=declared_detail,
            ),
        )
        common = {
            "submesh_name": "Helmet",
            "material_name": "Helmet",
            "shader_family": "SkinnedMeshEmissive_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 0,
            "owner_wrapper_item_id": "13",
            "binding_authority": "authoritative",
            "binding_disposition": "promoted",
            "material_parameters": parameters,
        }
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_material,
                parameter_name="_colorBlendingMaskTexture",
                source_kind="crimson_material_mask",
                **common,
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_detail,
                parameter_name="_detailMaskTexture",
                source_kind="crimson_detail_mask",
                **common,
            ),
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Helmet", texture_name="Helmet")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        inputs = {
            item.parameter_name: item
            for item in model.meshes[0].preview_material_texture_inputs
        }
        self.assertEqual(
            declared_material,
            inputs["_colorBlendingMaskTexture"].source_texture_path,
        )
        self.assertEqual(
            transport_material,
            inputs["_colorBlendingMaskTexture"].source_dds_path,
        )
        self.assertEqual(declared_detail, inputs["_detailMaskTexture"].source_texture_path)
        self.assertEqual(transport_detail, inputs["_detailMaskTexture"].source_dds_path)
        self.assertEqual(
            "sidecar-family-transport",
            inputs["_colorBlendingMaskTexture"].confidence,
        )
        graph = build_pac_material_graph_v1(model.meshes[0], {})
        self.assertTrue(graph["binding_conservation"]["conserved"])
        self.assertEqual([], graph["binding_conservation"]["dropped_parameters"])

    def test_owner_qualified_fist_mask_uses_shipped_object_family_transport(self) -> None:
        source_entry = _entry("character/model/cd_t0281_abyss_gauntlet_0001_l.pac")
        declared_material = "character/texture/cd_phm_13_fist_0012_ma.dds"
        declared_detail = "character/texture/cd_phm_13_fist_0012_mg.dds"
        transport_material = "object/texture/cd_phm_01_fist_0012_ma.dds"
        transport_detail = "object/texture/cd_phm_01_fist_0012_mg.dds"
        by_normalized, by_basename = _texture_maps(transport_material, transport_detail)
        parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_colorBlendingMaskTexture",
                texture_path=declared_material,
            ),
            PreviewMaterialParameterInput(
                parameter_kind="texture",
                parameter_name="_detailMaskTexture",
                texture_path=declared_detail,
            ),
        )
        common = {
            "submesh_name": "Gauntlet",
            "material_name": "Gauntlet",
            "shader_family": "SkinnedMeshStandard_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 3,
            "owner_wrapper_item_id": "283",
            "binding_authority": "authoritative",
            "binding_disposition": "promoted",
            "material_parameters": parameters,
        }
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_material,
                parameter_name="_colorBlendingMaskTexture",
                source_kind="crimson_material_mask",
                **common,
            ),
            _ArchiveModelSidecarTextureBinding(
                texture_path=declared_detail,
                parameter_name="_detailMaskTexture",
                source_kind="crimson_detail_mask",
                **common,
            ),
        )
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(material_name=f"Other{index}", texture_name=f"Other{index}")
                for index in range(3)
            ]
            + [ModelPreviewMesh(material_name="Gauntlet", texture_name="Gauntlet")],
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        inputs = {
            item.parameter_name: item
            for item in model.meshes[3].preview_material_texture_inputs
        }
        self.assertEqual(
            declared_material,
            inputs["_colorBlendingMaskTexture"].source_texture_path,
        )
        self.assertEqual(
            transport_material,
            inputs["_colorBlendingMaskTexture"].source_dds_path,
        )
        self.assertEqual(declared_detail, inputs["_detailMaskTexture"].source_texture_path)
        self.assertEqual(transport_detail, inputs["_detailMaskTexture"].source_dds_path)
        graph = build_pac_material_graph_v1(model.meshes[3], {})
        self.assertTrue(graph["binding_conservation"]["conserved"])
        self.assertEqual([], graph["binding_conservation"]["dropped_parameters"])

    def test_owner_qualified_detail_diffuse_mask_resolves_as_layer_color_not_material_map(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_path = "character/texture/cd_texturelayer_003_0016.dds"
        by_normalized, by_basename = _texture_maps(texture_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        binding = _ArchiveModelSidecarTextureBinding(
            texture_path=texture_path,
            parameter_name="_detailDiffuseMaskR",
            submesh_name="Part_A",
            material_name="Part_A",
            shader_family="SkinnedMeshStandard_Ver2",
            sidecar_kind="pac_xml",
            parameter_declared_by="pac_xml",
            owner_slot_index=0,
            owner_wrapper_item_id="1189",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_layer_color",
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=(binding,),
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_input = next(
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.parameter_name == "_detailDiffuseMaskR"
        )
        self.assertEqual("base", material_input.slot_kind)
        self.assertEqual("layer_only", material_input.binding_disposition)
        self.assertEqual(0, material_input.owner_slot_index)
        self.assertEqual("", model.meshes[0].preview_texture_path)

    def test_owner_qualified_torn_pattern_survives_unknown_suffix_heuristics(self) -> None:
        source_entry = _entry("character/model/cd_test_cloak.pac")
        texture_path = "character/texture/cd_texturelayer_endpattern_0001_tp.dds"
        by_normalized, by_basename = _texture_maps(texture_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Cloth", texture_name="Cloth")],
        )
        binding = _ArchiveModelSidecarTextureBinding(
            texture_path=texture_path,
            parameter_name="_tornPatternTexture",
            submesh_name="Cloth",
            material_name="Cloth",
            shader_family="SkinnedMeshTornCloth_Ver2",
            sidecar_kind="pac_xml",
            parameter_declared_by="pac_xml",
            owner_slot_index=0,
            owner_wrapper_item_id="1343",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_detail_mask",
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=(binding,),
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_input = next(
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.parameter_name == "_tornPatternTexture"
        )
        self.assertEqual("detail", material_input.slot_kind)
        self.assertEqual(texture_path, material_input.source_dds_path)
        self.assertEqual("layer_only", material_input.binding_disposition)
        self.assertEqual(0, material_input.owner_slot_index)

    def test_owner_qualified_pac_parameters_override_conflicting_filename_suffix(self) -> None:
        source_entry = _entry("character/model/cd_test_vest.pac")
        base_path = "character/texture/cd_test_vest.dds"
        texture_path = "character/texture/cd_test_vest_emi.dds"
        by_normalized, by_basename = _texture_maps(base_path, texture_path)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[
                ModelPreviewMesh(
                    material_name="cd_test_vest",
                    texture_name="cd_test_vest",
                )
            ],
        )
        common = {
            "texture_path": texture_path,
            "submesh_name": "cd_test_vest",
            "material_name": "cd_test_vest",
            "shader_family": "SkinnedMeshEmissive_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 0,
            "owner_wrapper_item_id": "8910",
            "binding_authority": "authoritative",
        }
        bindings = (
            _ArchiveModelSidecarTextureBinding(
                **common,
                parameter_name="_colorBlendingMaskTexture",
                binding_disposition="layer_only",
                source_kind="crimson_color_blending_mask",
            ),
            _ArchiveModelSidecarTextureBinding(
                **common,
                parameter_name="_heightTexture",
                binding_disposition="recorded",
                source_kind="crimson_height",
            ),
        )

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=lambda texture_entry, **_kwargs: f"preview://{texture_entry.path}",
        ):
            _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        inputs = {
            item.parameter_name: item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.parameter_name
        }
        self.assertEqual(
            {"_colorBlendingMaskTexture", "_heightTexture"},
            set(inputs),
        )
        self.assertEqual("material", inputs["_colorBlendingMaskTexture"].slot_kind)
        self.assertEqual("height", inputs["_heightTexture"].slot_kind)
        self.assertEqual(texture_path, inputs["_colorBlendingMaskTexture"].source_dds_path)
        self.assertEqual(texture_path, inputs["_heightTexture"].source_dds_path)

    def test_exact_sidecar_material_inputs_are_capped_before_preview_conversion(self) -> None:
        source_entry = _entry("character/model/cd_test_model.pac")
        texture_paths = tuple(
            f"character/texture/part_a_layer_{index:02d}_ma.dds"
            for index in range(8)
        )
        by_normalized, by_basename = _texture_maps(*texture_paths)
        model = ModelPreviewData(
            path=source_entry.path,
            meshes=[ModelPreviewMesh(material_name="Part_A", texture_name="Part_A")],
        )
        bindings = tuple(
            _ArchiveModelSidecarTextureBinding(path, f"_materialTexture{index}", "Part_A")
            for index, path in enumerate(texture_paths)
        )
        converted_paths: list[str] = []

        def _preview_path(texture_entry, **_kwargs):
            converted_paths.append(texture_entry.path)
            return f"preview://{texture_entry.path}"

        with patch(
            "cdmw.core.archive_model_textures._ensure_archive_model_texture_preview_path",
            side_effect=_preview_path,
        ):
            lines = _attach_model_support_texture_preview_paths(
                source_entry,
                model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                texture_entries_by_normalized_path=by_normalized,
                texture_entries_by_basename=by_basename,
            )

        material_inputs = [
            item
            for item in model.meshes[0].preview_material_texture_inputs
            if item.slot_kind == "material"
        ]
        # One input is the active material slot itself; rich sidecar inputs are
        # capped before conversion so high-layer sidecars do not spawn dozens
        # of texconv jobs on the cold preview path.
        self.assertLessEqual(len(material_inputs), 6)
        self.assertLessEqual(len(set(converted_paths)), 5)
        self.assertIn("lower-priority sidecar material texture input", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
