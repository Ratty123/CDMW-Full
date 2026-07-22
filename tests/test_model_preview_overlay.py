from __future__ import annotations

from array import array
import math
from pathlib import Path

from tests.hkx_editor_dialog_source_support import hkx_editor_dialog_source
import unittest

from PySide6.QtGui import QColor, QImage, QVector3D

from tests.native_source_text import d3d11_preview_source
from tests.static_replacement_source_support import (
    static_replacement_callback_factory_source,
    static_replacement_ui_section_source,
)

from cdmw.models import (
    MODEL_PREVIEW_ALPHA_HANDLING_MODES,
    MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES,
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS,
    MODEL_PREVIEW_SAMPLER_PROBE_MODES,
    MODEL_PREVIEW_TEXTURE_PROBE_SOURCES,
    ArchivePerformanceSettings,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    HkxPhysicsOverlayConstraint,
    HkxPhysicsOverlayShape,
    clamp_archive_performance_settings,
    clamp_model_preview_render_settings,
)
from cdmw.ui.widgets import (
    NativePreviewPanel,
    _BatchRenderDiagnostic,
    _FramebufferVisibilitySample,
    _ModelPreviewDrawBatch,
    _RENDER_DIAGNOSTIC_MODE_CODES,
    _TextureVisibilitySample,
)
from cdmw.rendering.model_preview_prepare import prepare_model_preview


class ModelPreviewOverlayClipTests(unittest.TestCase):
    def test_archive_performance_priority_can_prewarm_without_sidecar_indexing(self) -> None:
        settings = clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                enable_sidecar_indexing=False,
                maximum_indexing_priority=True,
            )
        )

        self.assertTrue(settings.maximum_indexing_priority)

    def test_keeps_visible_overlay_line_unchanged(self) -> None:
        clipped = NativePreviewPanel._clip_preview_line(
            (-0.25, 0.0, 0.0, 1.0),
            (0.25, 0.0, 0.0, 1.0),
        )

        self.assertEqual(
            clipped,
            ((-0.25, 0.0, 0.0, 1.0), (0.25, 0.0, 0.0, 1.0)),
        )

    def test_rejects_overlay_line_fully_outside_frustum(self) -> None:
        clipped = NativePreviewPanel._clip_preview_line(
            (2.0, 0.0, 0.0, 1.0),
            (3.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNone(clipped)

    def test_clips_overlay_line_against_near_plane(self) -> None:
        clipped = NativePreviewPanel._clip_preview_line(
            (0.0, 0.0, -2.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNotNone(clipped)
        assert clipped is not None
        self.assertAlmostEqual(clipped[0][2], -1.0)
        self.assertAlmostEqual(clipped[0][3], 1.0)
        self.assertEqual(clipped[1], (0.0, 0.0, 0.0, 1.0))

    def test_clips_overlay_line_before_perspective_divide_when_it_crosses_camera(self) -> None:
        clipped = NativePreviewPanel._clip_preview_line(
            (0.0, 0.0, 0.0, -1.0),
            (0.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNotNone(clipped)
        assert clipped is not None
        self.assertGreaterEqual(clipped[0][3], NativePreviewPanel._OVERLAY_CLIP_EPSILON)
        self.assertGreaterEqual(clipped[1][3], NativePreviewPanel._OVERLAY_CLIP_EPSILON)


class ModelPreviewRenderSafetyTests(unittest.TestCase):
    def test_alignment_live_rotation_matrix_matches_static_replacer_euler_order(self) -> None:
        matrix = NativePreviewPanel._alignment_euler_xyz_matrix((25.0, -35.0, 12.0))
        point = matrix.map(QVector3D(0.35, -0.4, 0.9))

        x, y, z = 0.35, -0.4, 0.9
        rx, ry, rz = (math.radians(value) for value in (25.0, -35.0, 12.0))
        cy, sy = math.cos(rx), math.sin(rx)
        y, z = y * cy - z * sy, y * sy + z * cy
        cx, sx = math.cos(ry), math.sin(ry)
        x, z = x * cx + z * sx, -x * sx + z * cx
        cz, sz = math.cos(rz), math.sin(rz)
        x, y = x * cz - y * sz, x * sz + y * cz

        self.assertAlmostEqual(x, point.x(), places=6)
        self.assertAlmostEqual(y, point.y(), places=6)
        self.assertAlmostEqual(z, point.z(), places=6)

    def test_alignment_live_rotation_delta_maps_current_rotation_to_committed_rotation(self) -> None:
        base_rotation = (18.0, -11.0, 7.0)
        live_delta = (3.5, 2.25, -1.0)
        point = QVector3D(0.4, -0.2, 0.8)

        base_matrix = NativePreviewPanel._alignment_euler_xyz_matrix(base_rotation)
        target_matrix = NativePreviewPanel._alignment_euler_xyz_matrix(
            tuple(base_rotation[index] + live_delta[index] for index in range(3))
        )
        delta_matrix = NativePreviewPanel._alignment_euler_delta_matrix(base_rotation, live_delta)

        current_point = base_matrix.map(point)
        expected_point = target_matrix.map(point)
        actual_point = delta_matrix.map(current_point)

        self.assertAlmostEqual(expected_point.x(), actual_point.x(), places=6)
        self.assertAlmostEqual(expected_point.y(), actual_point.y(), places=6)
        self.assertAlmostEqual(expected_point.z(), actual_point.z(), places=6)

    def test_hkx_preview_batches_are_not_mesh_edit_editable(self) -> None:
        mesh = ModelPreviewMesh(
            material_name="HKX shape",
            preview_role="hkx_collision_shape",
            source_submesh_index=2,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            indices=[0, 1, 2],
        )
        _model, prepared = prepare_model_preview(
            ModelPreviewData(
                path="body.hkx",
                format="hkx",
                mesh_count=1,
                vertex_count=3,
                face_count=1,
                meshes=[mesh],
            )
        )

        self.assertEqual(1, len(prepared.batches))
        self.assertEqual("hkx_collision_shape", prepared.batches[0].editor_role)
        self.assertFalse(prepared.batches[0].editor_editable)

    def test_original_reference_batches_are_not_mesh_edit_editable(self) -> None:
        mesh = ModelPreviewMesh(
            material_name="Body reference",
            preview_role="original_reference",
            source_submesh_index=2,
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            source_vertex_indices=[10, 11, 12],
            source_face_indices=[42],
            indices=[0, 1, 2],
        )
        _model, prepared = prepare_model_preview(
            ModelPreviewData(
                path="body.pac",
                format="pac",
                mesh_count=1,
                vertex_count=3,
                face_count=1,
                meshes=[mesh],
            )
        )

        self.assertEqual(1, len(prepared.batches))
        self.assertEqual("original_reference", prepared.batches[0].editor_role)
        self.assertEqual(2, prepared.batches[0].source_submesh_index)
        self.assertEqual((), prepared.batches[0].source_vertex_indices)
        self.assertEqual(10, prepared.batches[0].source_vertex_range_start)
        self.assertEqual(3, prepared.batches[0].source_vertex_range_count)
        self.assertFalse(prepared.batches[0].editor_editable)

    def test_render_settings_roundtrip_new_diagnostic_controls(self) -> None:
        for mode in MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES:
            settings = clamp_model_preview_render_settings(ModelPreviewRenderSettings(render_diagnostic_mode=mode))
            self.assertEqual(mode, settings.render_diagnostic_mode)
        for mode in ("height_depth", "material_response", "metal_shine", "roughness_response"):
            self.assertIn(mode, MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES)
            settings = clamp_model_preview_render_settings(ModelPreviewRenderSettings(render_diagnostic_mode=mode))
            self.assertEqual(mode, settings.render_diagnostic_mode)
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                alpha_handling_mode=MODEL_PREVIEW_ALPHA_HANDLING_MODES[-1],
                texture_probe_source=MODEL_PREVIEW_TEXTURE_PROBE_SOURCES[-1],
                sampler_probe_mode=MODEL_PREVIEW_SAMPLER_PROBE_MODES[-1],
                diffuse_swizzle_mode=MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES[-1],
                disable_tint=True,
                alignment_use_final_output_preview=True,
                disable_brightness=True,
                disable_uv_scale=True,
                force_nearest_no_mipmaps=True,
                disable_normal_map=True,
                disable_material_map=True,
                disable_height_map=True,
                disable_all_support_maps=True,
                disable_lighting=True,
                disable_depth_test=True,
                show_texture_debug_strip=True,
                solo_batch_index=3,
            )
        )
        self.assertEqual(MODEL_PREVIEW_ALPHA_HANDLING_MODES[-1], settings.alpha_handling_mode)
        self.assertEqual(MODEL_PREVIEW_TEXTURE_PROBE_SOURCES[-1], settings.texture_probe_source)
        self.assertEqual(MODEL_PREVIEW_SAMPLER_PROBE_MODES[-1], settings.sampler_probe_mode)
        self.assertEqual(MODEL_PREVIEW_DIFFUSE_SWIZZLE_MODES[-1], settings.diffuse_swizzle_mode)
        self.assertTrue(settings.disable_tint)
        self.assertTrue(settings.alignment_use_final_output_preview)
        self.assertTrue(settings.force_nearest_no_mipmaps)
        self.assertEqual(3, settings.solo_batch_index)

    def test_rich_lit_is_opt_in_and_lit_keeps_compatibility_code(self) -> None:
        defaults = clamp_model_preview_render_settings(ModelPreviewRenderSettings())

        self.assertEqual("lit", defaults.render_diagnostic_mode)
        self.assertEqual(0, _RENDER_DIAGNOSTIC_MODE_CODES["lit"])
        self.assertEqual(22, _RENDER_DIAGNOSTIC_MODE_CODES["rich_lit"])
        self.assertEqual(23, _RENDER_DIAGNOSTIC_MODE_CODES["height_calibrated"])
        self.assertEqual(24, _RENDER_DIAGNOSTIC_MODE_CODES["relief_control_test"])
        self.assertEqual(25, _RENDER_DIAGNOSTIC_MODE_CODES["matcap"])
        self.assertEqual(26, _RENDER_DIAGNOSTIC_MODE_CODES["wireframe"])
        self.assertEqual(27, _RENDER_DIAGNOSTIC_MODE_CODES["vertex_normals"])
        self.assertEqual(28, _RENDER_DIAGNOSTIC_MODE_CODES["uv_checker"])
        self.assertEqual(29, _RENDER_DIAGNOSTIC_MODE_CODES["source_pbr_preview"])
        self.assertEqual(30, _RENDER_DIAGNOSTIC_MODE_CODES["cd_runtime_approx"])
        self.assertEqual("Source PBR Preview", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["source_pbr_preview"])
        self.assertEqual("CD Runtime Approx Preview", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["cd_runtime_approx"])

        prep_source = Path("cdmw/rendering/model_preview_prepare.py").read_text(encoding="utf-8")
        self.assertIn('"cd_runtime_approx"', prep_source)
        self.assertIn("render_mode_uses_derived_relief", prep_source)
        package_source = "\n".join(
            (
                Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8"),
                Path("cdmw/rendering/native_preview_package_writer.py").read_text(encoding="utf-8"),
                Path("cdmw/rendering/native_preview_material_contract.py").read_text(encoding="utf-8"),
            )
        )
        self.assertIn('"source_pbr_preview"', package_source)
        self.assertIn('"cd_runtime_approx"', package_source)
        self.assertIn("preview_divergence_reasons", package_source)

    def test_vortice_view_modes_are_an_explicit_renderer_allow_list(self) -> None:
        source = Path("tools/dotnet_mesh_editor_experiment/DotNetPreviewViewModes.cs").read_text(encoding="utf-8")
        settings_ui = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")

        for mode in ("lit", "game_outdoor", "base_direct", "normal", "uv_checker", "base_alpha", "part_id", "material_response", "layer_mask"):
            self.assertIn(f'"{mode}"', source)
        for retired_mode in ("matcap", "wireframe", "vertex_normals", "normal_raw"):
            self.assertNotIn(f'"{retired_mode}"', source)
        self.assertNotIn('general_form.addRow("Visible texture mode"', settings_ui)
        self.assertNotIn('general_form.addRow("Diagnostic render mode"', settings_ui)
        global_settings_ui = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
        self.assertNotIn('preview_layout.addRow("Visible texture mode"', global_settings_ui)
        self.assertNotIn('preview_layout.addRow("Diagnostic render mode"', global_settings_ui)
        self.assertNotIn('preview_layout.addRow("Alpha handling"', global_settings_ui)
        self.assertNotIn('preview_layout.addRow("Texture source probe"', global_settings_ui)
        self.assertNotIn('preview_layout.addRow("Sampler probe"', global_settings_ui)
        self.assertNotIn('preview_layout.addRow("Diffuse swizzle"', global_settings_ui)

    def test_normal_diagnostics_distinguish_geometry_from_texture_maps(self) -> None:
        self.assertEqual("Geometry Normal", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["normal"])
        self.assertEqual("Normal Texture Raw", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["normal_raw"])
        self.assertEqual(5, _RENDER_DIAGNOSTIC_MODE_CODES["normal"])
        self.assertEqual(11, _RENDER_DIAGNOSTIC_MODE_CODES["normal_raw"])

        vortice_source = Path("tools/dotnet_mesh_editor_experiment/DotNetPreviewViewModes.cs").read_text(encoding="utf-8")
        self.assertIn('"normal" => 2', vortice_source)
        self.assertNotIn('"normal_raw"', vortice_source)

    def test_derived_relief_texture_generation_is_relief_mode_only(self) -> None:
        self.assertFalse(
            NativePreviewPanel._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="lit")
            )
        )
        self.assertFalse(
            NativePreviewPanel._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="base_raw")
            )
        )
        self.assertFalse(
            NativePreviewPanel._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="relief_control_test")
            )
        )
        self.assertTrue(
            NativePreviewPanel._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="rich_lit")
            )
        )
        self.assertTrue(
            NativePreviewPanel._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="height_calibrated")
            )
        )

    def test_height_visibility_sampling_reports_relief_contrast(self) -> None:
        image = QImage(3, 1, QImage.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(32, 32, 32, 255))
        image.setPixelColor(1, 0, QColor(128, 128, 128, 255))
        image.setPixelColor(2, 0, QColor(224, 224, 224, 255))

        sample = NativePreviewPanel._sample_base_texture_visibility(
            image,
            [(0.0, 0.0), (0.5, 0.0), (0.99, 0.0)],
            flip_vertical=False,
            max_samples=8,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertLess(sample.min_luma, sample.average_luma)
        self.assertGreater(sample.max_luma, sample.average_luma)
        self.assertGreater(sample.luma_contrast, 0.70)

    def test_derived_relief_generation_uses_base_texture_detail(self) -> None:
        image = QImage(4, 4, QImage.Format_RGBA8888)
        for y in range(4):
            for x in range(4):
                value = 40 if (x + y) % 2 == 0 else 220
                image.setPixelColor(x, y, QColor(value, value, value, 255))

        relief = NativePreviewPanel._derive_relief_image_from_base(image)

        self.assertIsNotNone(relief)
        assert relief is not None
        sample = NativePreviewPanel._sample_base_texture_visibility(
            relief,
            [(0.0, 0.0), (0.33, 0.0), (0.66, 0.0), (0.99, 0.0)],
            flip_vertical=False,
            max_samples=8,
        )
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertGreater(sample.luma_contrast, 0.10)

    def test_derived_relief_generation_ignores_flat_base_texture(self) -> None:
        image = QImage(4, 4, QImage.Format_RGBA8888)
        image.fill(QColor(120, 120, 120, 255))

        self.assertIsNone(NativePreviewPanel._derive_relief_image_from_base(image))

    def test_enhanced_relief_status_reports_true_and_derived_sources(self) -> None:
        active_state, active_reason, active_usable, active_source = NativePreviewPanel._enhanced_relief_status(
            render_mode_code=22,
            high_quality_enabled=True,
            support_maps_enabled=True,
            support_maps_disabled=False,
            height_key="height.png",
            height_texture_available=True,
            height_luma=_TextureVisibilitySample(
                average_color=(0.5, 0.5, 0.5),
                average_luma=0.5,
                dark_ratio=0.0,
                min_luma=0.20,
                max_luma=0.80,
                luma_contrast=0.60,
            ),
            height_map_disabled=False,
            height_effect_max=0.7,
        )
        derived_state, derived_reason, derived_usable, derived_source = NativePreviewPanel._enhanced_relief_status(
            render_mode_code=22,
            high_quality_enabled=True,
            support_maps_enabled=False,
            support_maps_disabled=True,
            height_key="",
            height_texture_available=False,
            height_luma=None,
            derived_relief_key="derived_relief:0:base.png",
            derived_relief_texture_available=True,
            derived_relief_luma=_TextureVisibilitySample(
                average_color=(0.5, 0.5, 0.5),
                average_luma=0.5,
                dark_ratio=0.0,
                min_luma=0.15,
                max_luma=0.85,
                luma_contrast=0.70,
            ),
            height_map_disabled=True,
            height_effect_max=0.7,
        )
        flat_state, flat_reason, flat_usable, flat_source = NativePreviewPanel._enhanced_relief_status(
            render_mode_code=22,
            high_quality_enabled=True,
            support_maps_enabled=True,
            support_maps_disabled=False,
            height_key="height.png",
            height_texture_available=True,
            height_luma=_TextureVisibilitySample(
                average_color=(0.5, 0.5, 0.5),
                average_luma=0.5,
                dark_ratio=0.0,
                min_luma=0.50,
                max_luma=0.505,
                luma_contrast=0.005,
            ),
            height_map_disabled=False,
            height_effect_max=0.7,
        )

        self.assertEqual("active", active_state)
        self.assertIn("Calibrated", active_reason)
        self.assertTrue(active_usable)
        self.assertEqual("height-map", active_source)
        self.assertEqual("active", derived_state)
        self.assertIn("Derived", derived_reason)
        self.assertTrue(derived_usable)
        self.assertEqual("derived-base", derived_source)
        self.assertEqual("inactive", flat_state)
        self.assertIn("nearly flat", flat_reason)
        self.assertFalse(flat_usable)
        self.assertEqual("inactive", flat_source)

    def test_render_settings_clamp_invalid_diagnostic_controls(self) -> None:
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                render_diagnostic_mode="bad",
                alpha_handling_mode="bad",
                texture_probe_source="bad",
                sampler_probe_mode="bad",
                diffuse_swizzle_mode="bad",
                solo_batch_index=-22,
            )
        )
        defaults = ModelPreviewRenderSettings()
        self.assertEqual(defaults.render_diagnostic_mode, settings.render_diagnostic_mode)
        self.assertEqual(defaults.alpha_handling_mode, settings.alpha_handling_mode)
        self.assertEqual(defaults.texture_probe_source, settings.texture_probe_source)
        self.assertEqual(defaults.sampler_probe_mode, settings.sampler_probe_mode)
        self.assertEqual(defaults.diffuse_swizzle_mode, settings.diffuse_swizzle_mode)
        self.assertEqual(-1, settings.solo_batch_index)

    def test_base_texture_diagnostics_ignore_material_probe_source(self) -> None:
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(texture_probe_source="material")
        )

        for mode in ("base_direct", "base_no_tint", "base_alpha", "base_color", "sampler_swap_base_on_unit2"):
            self.assertEqual(
                "base",
                NativePreviewPanel._diffuse_probe_source_for_render_mode(settings, mode),
            )
        self.assertEqual(
            "material",
            NativePreviewPanel._diffuse_probe_source_for_render_mode(settings, "sampler_swap_material_on_unit0"),
        )
        self.assertEqual(
            "material",
            NativePreviewPanel._diffuse_probe_source_for_render_mode(settings, "texture_probe"),
        )
        self.assertEqual(
            "base",
            NativePreviewPanel._diffuse_probe_source_for_render_mode(
                ModelPreviewRenderSettings(texture_probe_source="not-a-slot"),
                "texture_probe",
            ),
        )

    def test_depth_and_shine_controls_clamp_to_safe_ranges(self) -> None:
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                height_effect_max=99.0,
                specular_max=99.0,
                shininess_max=999.0,
                specular_min=0.8,
                shininess_min=300.0,
                d3d11_mip_lod_bias=-99.0,
                d3d11_light_azimuth_degrees=999.0,
                d3d11_light_elevation_degrees=-999.0,
                d3d11_ao_strength=99.0,
                d3d11_roughness_bias=-99.0,
                d3d11_metalness_scale=99.0,
                d3d11_environment_strength=99.0,
                d3d11_emissive_gain=99.0,
                d3d11_tone_exposure=99.0,
                d3d11_tone_contrast=99.0,
                d3d11_tone_gamma=99.0,
                d3d11_view_mode="bad",
                d3d11_normal_y_mode="bad",
                d3d11_texture_address_mode="bad",
            )
        )

        self.assertLessEqual(settings.height_effect_max, 1.0)
        self.assertLessEqual(settings.specular_max, 1.0)
        self.assertLessEqual(settings.shininess_max, 256.0)
        self.assertLessEqual(settings.specular_min, settings.specular_max)
        self.assertLessEqual(settings.shininess_min, settings.shininess_max)
        self.assertGreaterEqual(settings.d3d11_mip_lod_bias, -2.0)
        self.assertLessEqual(settings.d3d11_light_azimuth_degrees, 180.0)
        self.assertGreaterEqual(settings.d3d11_light_elevation_degrees, -80.0)
        self.assertLessEqual(settings.d3d11_ao_strength, 2.0)
        self.assertGreaterEqual(settings.d3d11_roughness_bias, -0.5)
        self.assertLessEqual(settings.d3d11_metalness_scale, 2.0)
        self.assertLessEqual(settings.d3d11_environment_strength, 2.0)
        self.assertLessEqual(settings.d3d11_emissive_gain, 4.0)
        self.assertLessEqual(settings.d3d11_tone_exposure, 2.0)
        self.assertLessEqual(settings.d3d11_tone_contrast, 1.75)
        self.assertLessEqual(settings.d3d11_tone_gamma, 2.20)
        self.assertEqual("lit", settings.d3d11_view_mode)
        self.assertEqual("asset", settings.d3d11_normal_y_mode)
        self.assertEqual("wrap", settings.d3d11_texture_address_mode)

    def test_game_outdoor_d3d11_view_mode_survives_clamping(self) -> None:
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(d3d11_view_mode="game_outdoor")
        )

        self.assertEqual("game_outdoor", settings.d3d11_view_mode)

    def test_depth_shine_and_rough_settings_survive_clamping(self) -> None:
        settings = clamp_model_preview_render_settings(
            ModelPreviewRenderSettings(
                height_effect_max=0.82,
                specular_max=0.67,
                shininess_min=18.0,
                shininess_base=84.0,
                shininess_max=190.0,
                height_shininess_boost=42.0,
            )
        )

        self.assertAlmostEqual(0.82, settings.height_effect_max)
        self.assertAlmostEqual(0.67, settings.specular_max)
        self.assertAlmostEqual(18.0, settings.shininess_min)
        self.assertAlmostEqual(84.0, settings.shininess_base)
        self.assertAlmostEqual(190.0, settings.shininess_max)
        self.assertAlmostEqual(42.0, settings.height_shininess_boost)

    def test_default_lit_settings_do_not_enable_diagnostic_modes(self) -> None:
        defaults = clamp_model_preview_render_settings(ModelPreviewRenderSettings())

        self.assertEqual("lit", defaults.render_diagnostic_mode)
        self.assertFalse(defaults.disable_all_support_maps)
        self.assertGreater(defaults.height_effect_max, 0.0)

    def test_default_d3d11_settings_favor_metal_weapon_preview(self) -> None:
        defaults = clamp_model_preview_render_settings(ModelPreviewRenderSettings())

        self.assertEqual(16, defaults.max_anisotropy)
        self.assertAlmostEqual(-2.0, defaults.d3d11_mip_lod_bias)
        self.assertAlmostEqual(0.84, defaults.ambient_strength)
        self.assertAlmostEqual(0.62, defaults.diffuse_light_scale)
        self.assertAlmostEqual(0.58, defaults.diffuse_wrap_bias)
        self.assertAlmostEqual(-10.0, defaults.d3d11_light_azimuth_degrees)
        self.assertAlmostEqual(0.0, defaults.d3d11_light_elevation_degrees)
        self.assertAlmostEqual(1.00, defaults.height_effect_max)
        self.assertAlmostEqual(0.055, defaults.specular_base)
        self.assertAlmostEqual(0.52, defaults.specular_max)
        self.assertAlmostEqual(152.0, defaults.shininess_max)
        self.assertAlmostEqual(0.45, defaults.d3d11_ao_strength)
        self.assertAlmostEqual(-0.04, defaults.d3d11_roughness_bias)
        self.assertAlmostEqual(1.45, defaults.d3d11_metalness_scale)
        self.assertAlmostEqual(0.62, defaults.d3d11_environment_strength)
        self.assertAlmostEqual(2.2, defaults.d3d11_emissive_gain)
        self.assertAlmostEqual(1.00, defaults.d3d11_tone_exposure)
        self.assertAlmostEqual(1.08, defaults.d3d11_tone_contrast)
        self.assertAlmostEqual(1.00, defaults.d3d11_tone_gamma)
        self.assertGreater(defaults.specular_max, 0.0)

    def test_enhanced_relief_shader_path_is_gated(self) -> None:
        prep_source = Path("cdmw/rendering/model_preview_prepare.py").read_text(encoding="utf-8")
        vortice_modes = Path("tools/dotnet_mesh_editor_experiment/DotNetPreviewViewModes.cs").read_text(encoding="utf-8")
        settings_ui = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")

        self.assertIn("def enhanced_relief_status", prep_source)
        self.assertIn('"height_calibrated"', prep_source)
        self.assertIn('"cd_runtime_approx"', prep_source)
        self.assertIn("height_effect_max", prep_source)
        self.assertNotIn('"height_calibrated"', vortice_modes)
        self.assertNotIn('"cd_runtime_approx"', vortice_modes)
        self.assertNotIn('general_form.addRow("Diagnostic render mode"', settings_ui)

    def test_black_output_triage_distinguishes_missing_base_from_support_only(self) -> None:
        framebuffer = _FramebufferVisibilitySample(visible_pixels=100, average_luma=0.02, dark_ratio=0.95)
        missing_base_lines = NativePreviewPanel._black_output_triage_lines(
            [
                _BatchRenderDiagnostic(
                    batch_index=0,
                    mesh_index=0,
                    label="Blade",
                    texture_path_set=False,
                    use_texture=False,
                )
            ],
            framebuffer,
        )
        support_only_lines = NativePreviewPanel._black_output_triage_lines(
            [
                _BatchRenderDiagnostic(
                    batch_index=0,
                    mesh_index=0,
                    label="Blade",
                    texture_path_set=False,
                    use_texture=False,
                    use_normal=True,
                    use_height=True,
                )
            ],
            framebuffer,
        )

        self.assertIn("Missing base/color", "\n".join(missing_base_lines))
        self.assertIn("support maps cannot provide visible color", "\n".join(missing_base_lines))
        self.assertIn("only normal/material/height support maps active", "\n".join(support_only_lines))

    def test_support_map_slot_and_active_counts_are_summarized(self) -> None:
        batches = [
            _ModelPreviewDrawBatch(
                mesh_index=0,
                material_name="",
                texture_name="",
                first_vertex=0,
                vertex_count=3,
                normal_texture_key="normal.png",
                material_texture_key="material.png",
            ),
            _ModelPreviewDrawBatch(
                mesh_index=1,
                material_name="",
                texture_name="",
                first_vertex=3,
                vertex_count=3,
                height_texture_key="height.png",
            ),
        ]
        diagnostics = {
            0: _BatchRenderDiagnostic(0, 0, "batch 0", use_normal=True),
            1: _BatchRenderDiagnostic(1, 1, "batch 1", use_height=True),
        }

        available = NativePreviewPanel._support_map_slot_counts_from_batches(batches)
        active = NativePreviewPanel._support_map_active_counts_from_diagnostics(diagnostics)

        self.assertEqual({"normal": 1, "material": 1, "height": 1}, available)
        self.assertEqual({"normal": 1, "material": 0, "height": 1}, active)
        self.assertEqual("n:1 m:0 h:1", NativePreviewPanel._format_support_map_counts(active))

    def test_vertex_blob_repairs_invalid_normals_and_preserves_uv_batch(self) -> None:
        mesh = ModelPreviewMesh(
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            normals=[
                (0.0, 0.0, 0.0),
                (math.nan, 0.0, 0.0),
                (0.0, math.inf, 0.0),
            ],
            texture_coordinates=[
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
            ],
            indices=[0, 1, 2],
            preview_texture_path="example.png",
            preview_color=(math.nan, -1.0, 2.0),
        )
        model = ModelPreviewData(meshes=[mesh])

        vertex_blob, vertex_count, batches = NativePreviewPanel._build_vertex_blob(model)
        values = array("f")
        values.frombytes(vertex_blob)

        self.assertEqual(3, vertex_count)
        self.assertEqual(1, len(batches))
        self.assertTrue(batches[0].has_texture_coordinates)
        self.assertGreaterEqual(batches[0].normal_repair_count, 1)
        self.assertTrue(all(math.isfinite(value) for value in values))
        first_normal = tuple(values[3:6])
        self.assertAlmostEqual(1.0, math.sqrt(sum(component * component for component in first_normal)))

    def test_degenerate_uvs_block_support_map_geometry(self) -> None:
        mesh = ModelPreviewMesh(
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            normals=[
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
            ],
            texture_coordinates=[
                (0.0, 0.0),
                (0.0, 0.0),
                (0.0, 0.0),
            ],
            indices=[0, 1, 2],
            preview_texture_path="base.png",
            preview_normal_texture_path="normal.png",
            preview_normal_texture_strength=0.4,
            preview_material_texture_path="material.png",
            preview_height_texture_path="height.png",
        )

        _vertex_blob, _vertex_count, batches = NativePreviewPanel._build_vertex_blob(ModelPreviewData(meshes=[mesh]))

        self.assertTrue(batches[0].has_texture_coordinates)
        self.assertEqual(0.0, batches[0].tangent_finite_ratio)
        self.assertEqual(0.0, batches[0].bitangent_finite_ratio)
        self.assertFalse(NativePreviewPanel._support_map_geometry_usable(batches[0]))

    def test_tangent_frame_preserves_mirrored_uv_handedness(self) -> None:
        mesh = ModelPreviewMesh(
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            normals=[
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
            ],
            texture_coordinates=[
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, -1.0),
            ],
            indices=[0, 1, 2],
            preview_texture_path="base.png",
            preview_normal_texture_path="normal.png",
        )

        vertex_blob, _vertex_count, batches = NativePreviewPanel._build_vertex_blob(ModelPreviewData(meshes=[mesh]))
        values = array("f")
        values.frombytes(vertex_blob)
        normal = tuple(values[3:6])
        tangent = tuple(values[11:14])
        bitangent = tuple(values[14:17])

        self.assertEqual(1.0, batches[0].tangent_finite_ratio)
        self.assertEqual(1.0, batches[0].bitangent_finite_ratio)
        self.assertAlmostEqual(0.0, sum(normal[index] * tangent[index] for index in range(3)), places=5)
        self.assertAlmostEqual(0.0, sum(normal[index] * bitangent[index] for index in range(3)), places=5)
        self.assertAlmostEqual(0.0, sum(tangent[index] * bitangent[index] for index in range(3)), places=5)
        self.assertLess(bitangent[1], -0.9)

    def test_vertex_blob_includes_preview_smoothed_normals_for_rich_lighting(self) -> None:
        mesh = ModelPreviewMesh(
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ],
            normals=[
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
            ],
            texture_coordinates=[
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
                (0.0, 0.0),
                (0.0, 1.0),
                (1.0, 1.0),
            ],
            indices=[0, 1, 2, 3, 4, 5],
            preview_texture_path="example.png",
        )
        model = ModelPreviewData(meshes=[mesh])

        vertex_blob, _vertex_count, batches = NativePreviewPanel._build_vertex_blob(model)
        values = array("f")
        values.frombytes(vertex_blob)

        self.assertGreater(batches[0].smooth_normal_ratio, 0.0)
        first_smooth_normal = tuple(values[17:20])
        self.assertGreater(first_smooth_normal[0], 0.2)
        self.assertGreater(first_smooth_normal[2], 0.2)

    def test_base_texture_quality_reaches_prepared_preview_batches(self) -> None:
        mesh = ModelPreviewMesh(
            material_name="mat",
            texture_name="base.dds",
            preview_base_texture_quality="low_authority_overlay",
            positions=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            texture_coordinates=[
                (0.0, 0.0),
                (1.0, 0.0),
                (0.0, 1.0),
            ],
            normals=[
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
                (0.0, 0.0, 1.0),
            ],
            indices=[0, 1, 2],
            preview_texture_path="base.png",
        )
        model = ModelPreviewData(meshes=[mesh])

        _clone, prepared = prepare_model_preview(model)

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual("low_authority_overlay", prepared.batches[0].preview_base_texture_quality)

    def test_texture_visibility_sampling_reports_luma_dark_ratio_and_alpha(self) -> None:
        image = QImage(2, 1, QImage.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(0, 0, 0, 128))
        image.setPixelColor(1, 0, QColor(255, 255, 255, 255))

        sample = NativePreviewPanel._sample_base_texture_visibility(
            image,
            [(0.0, 0.0), (0.99, 0.0)],
            flip_vertical=False,
            max_samples=8,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertAlmostEqual(0.5, sample.average_luma, places=2)
        self.assertAlmostEqual(0.5, sample.dark_ratio, places=2)
        self.assertGreater(sample.average_alpha, 0.70)
        self.assertLess(sample.average_alpha, 1.0)

    def test_framebuffer_visibility_sampling_ignores_background_pixels(self) -> None:
        background = QColor(10, 10, 10)
        image = QImage(4, 4, QImage.Format_RGBA8888)
        image.fill(background)
        image.setPixelColor(1, 1, QColor(220, 220, 220))
        image.setPixelColor(2, 1, QColor(8, 8, 8))

        sample = NativePreviewPanel._sample_framebuffer_visibility(
            image,
            background,
            max_samples=64,
        )

        self.assertGreaterEqual(sample.visible_pixels, 1)
        self.assertGreater(sample.background_ratio, 0.5)
        self.assertGreater(sample.average_luma, 0.5)

    def test_enabling_textures_rebuilds_derived_relief_textures(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "native_preview_panel.py").read_text(encoding="utf-8")
        self.assertIn("def set_use_textures", source)
        self.assertIn("self._use_textures = bool(use_textures)", source)
        self.assertNotIn("_rebuild_gl_textures", source)
        self.assertNotIn("_texture_objects", source)

    def test_model_preview_reuses_textures_for_transform_only_updates(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        prep_source = (Path(__file__).resolve().parents[1] / "cdmw" / "rendering" / "model_preview_prepare.py").read_text(encoding="utf-8")
        self.assertNotIn("def _upload_geometry", source)
        self.assertNotIn("_texture_upload_cache_signature", source)
        self.assertIn("def prepare_model_preview", prep_source)
        self.assertIn("def build_vertex_blob", prep_source)

    def test_model_preview_has_committed_transform_fast_path_and_timing_diagnostics(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        native_panel_source = (root / "cdmw" / "ui" / "native_preview_panel.py").read_text(encoding="utf-8")
        main_source = "\n".join(
            (
                (root / "cdmw" / "ui" / "shell" / "app_window.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_shell.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_open.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_state_callbacks.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_transform.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_base.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_a.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_b.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_callbacks.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py").read_text(encoding="utf-8"),
                static_replacement_ui_section_source(root),
                static_replacement_callback_factory_source(root),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_runtime_state.py").read_text(encoding="utf-8"),
                (root / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_drag_ui_state.py").read_text(encoding="utf-8"),
            )
        )
        self.assertIn("from cdmw.ui.native_preview_panel import NativePreviewPanel", source)
        self.assertIn("def set_alignment_committed_preview_transform", native_panel_source)
        self.assertIn("class NativePreviewPanel(QWidget)", native_panel_source)
        self.assertIn("prepare_model_preview = staticmethod(_prep.prepare_model_preview)", native_panel_source)
        self.assertIn("def alignment_d3d11_record_fast_transform_payload(", main_source)
        self.assertIn('state["pending_fast_transform"] = payload', main_source)
        self.assertIn("pending_part_fast_transforms", main_source)
        self.assertIn("def alignment_d3d11_fast_transform_payload(", main_source)
        self.assertIn("set_alignment_preview_transforms", main_source)
        self.assertIn("def _replay_alignment_d3d11_fast_transform() -> None:", main_source)
        self.assertIn("capture_generation >= committed_generation", main_source)
        self.assertIn("request_transform_generation", main_source)
        self.assertIn("_replay_alignment_d3d11_fast_transform()", main_source)
        self.assertIn("_queue_static_preview_rebuild()", main_source)
        self.assertNotIn("functions.glGetString", native_panel_source)
        self.assertNotIn("_read_green_up_renderer_info", native_panel_source)

    def test_hkx_physics_overlay_supports_hover_and_ctrl_click_selection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        host_source = (root / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")
        protocol_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.OverlayProtocol.cs").read_text(encoding="utf-8")
        renderer_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialViewport.PreviewOverlays.cs").read_text(encoding="utf-8")
        package_source = (root / "cdmw" / "services" / "mesh_dotnet_preview_package.py").read_text(encoding="utf-8")

        self.assertIn('"overlay_state_update"', host_source)
        self.assertIn("set_skeleton_selected_bone", host_source)
        self.assertIn("reset_tool_pbd_cloth_preview", host_source)
        self.assertIn('"overlay_state_update_ack"', protocol_source)
        self.assertIn('"skeleton_overlay_v1"', protocol_source)
        self.assertIn('"pbd_cloth_overlay_v1"', protocol_source)
        self.assertIn("DrawSkeletonPreviewOverlay", renderer_source)
        self.assertIn("DrawClothPreviewOverlay", renderer_source)
        self.assertIn("ClothColliders", renderer_source)
        self.assertIn("dotnet_preview_overlays_from_preview_core_package", package_source)

    def test_hkx_skeleton_context_is_static_for_approx_motion_preview(self) -> None:
        widget = NativePreviewPanel.__new__(NativePreviewPanel)

        self.assertFalse(hasattr(widget, "_physics_simulation_constraint_is_dynamic"))
        self.assertFalse(hasattr(widget, "_physics_simulation_shape_is_dynamic"))
        self.assertTrue(hasattr(NativePreviewPanel, "physics_overlay_bones_visible"))

    def test_referenced_hkx_previews_disable_legacy_guide_motion(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "cdmw" / "ui" / "archive_browser" / "reference_preview.py").read_text(encoding="utf-8")
        package_source = (root / "cdmw" / "services" / "mesh_dotnet_preview_package.py").read_text(encoding="utf-8")

        self.assertIn("DotNetPreviewHostFrame", source)
        self.assertIn("build_or_lookup_dotnet_preview_package(", source)
        self.assertIn("dotnet_reference_package_path", source)
        self.assertIn("dotnet_preview_overlays_from_preview_core_package", package_source)
        self.assertNotIn("NativeD3D11PreviewHostFrame", source)

    def test_framebuffer_visibility_probe_is_throttled(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "rendering" / "model_preview_prepare.py").read_text(encoding="utf-8")
        self.assertIn("def sample_framebuffer_visibility", source)
        self.assertIn("background_ratio", source)
        self.assertNotIn("grabFramebuffer", (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8"))

    def test_render_sampling_diagnostics_include_geometry_and_output_buckets(self) -> None:
        widget = NativePreviewPanel.__new__(NativePreviewPanel)
        widget._mesh_batches = [
            _ModelPreviewDrawBatch(mesh_index=0, material_name="mat", texture_name="", first_vertex=0, vertex_count=3)
        ]
        widget._batch_render_diagnostics = {
            0: _BatchRenderDiagnostic(
                batch_index=0,
                mesh_index=0,
                label="mat",
                texture_path_set=True,
                image_loaded=True,
                image_size="2x2",
                uv_valid=True,
                uv_count=3,
                position_count=3,
                texture_uploaded=True,
                use_texture=True,
                sampled_luma=0.4,
                sampled_dark_ratio=0.0,
                normal_finite_ratio=0.67,
                normal_repair_count=1,
                tangent_finite_ratio=1.0,
                bitangent_finite_ratio=1.0,
                uv_finite_ratio=1.0,
            )
        }
        widget._framebuffer_visibility_diagnostic = _FramebufferVisibilitySample(
            visible_pixels=10,
            average_luma=0.5,
            dark_ratio=0.0,
            background_ratio=0.9,
        )
        widget._render_settings = ModelPreviewRenderSettings(render_diagnostic_mode="base_color")

        self.assertFalse(hasattr(widget, "_render_sampling_diagnostic_lines"))
        text = "\n".join(NativePreviewPanel._black_output_triage_lines((), widget._framebuffer_visibility_diagnostic))
        self.assertIn("Native renderer diagnostics", text)


if __name__ == "__main__":
    unittest.main()
