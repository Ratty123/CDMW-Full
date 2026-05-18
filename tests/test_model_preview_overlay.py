from __future__ import annotations

from array import array
import math
from pathlib import Path
import unittest

from PySide6.QtGui import QColor, QImage, QVector3D

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
    ModelPreviewWidget,
    _BatchRenderDiagnostic,
    _FramebufferVisibilitySample,
    _ModelPreviewDrawBatch,
    _RENDER_DIAGNOSTIC_MODE_CODES,
    _TextureVisibilitySample,
)


class ModelPreviewOverlayClipTests(unittest.TestCase):
    def test_archive_performance_priority_requires_sidecar_indexing(self) -> None:
        settings = clamp_archive_performance_settings(
            ArchivePerformanceSettings(
                enable_sidecar_indexing=False,
                maximum_indexing_priority=True,
            )
        )

        self.assertFalse(settings.maximum_indexing_priority)

    def test_keeps_visible_overlay_line_unchanged(self) -> None:
        clipped = ModelPreviewWidget._clip_preview_line(
            (-0.25, 0.0, 0.0, 1.0),
            (0.25, 0.0, 0.0, 1.0),
        )

        self.assertEqual(
            clipped,
            ((-0.25, 0.0, 0.0, 1.0), (0.25, 0.0, 0.0, 1.0)),
        )

    def test_rejects_overlay_line_fully_outside_frustum(self) -> None:
        clipped = ModelPreviewWidget._clip_preview_line(
            (2.0, 0.0, 0.0, 1.0),
            (3.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNone(clipped)

    def test_clips_overlay_line_against_near_plane(self) -> None:
        clipped = ModelPreviewWidget._clip_preview_line(
            (0.0, 0.0, -2.0, 1.0),
            (0.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNotNone(clipped)
        assert clipped is not None
        self.assertAlmostEqual(clipped[0][2], -1.0)
        self.assertAlmostEqual(clipped[0][3], 1.0)
        self.assertEqual(clipped[1], (0.0, 0.0, 0.0, 1.0))

    def test_clips_overlay_line_before_perspective_divide_when_it_crosses_camera(self) -> None:
        clipped = ModelPreviewWidget._clip_preview_line(
            (0.0, 0.0, 0.0, -1.0),
            (0.0, 0.0, 0.0, 1.0),
        )

        self.assertIsNotNone(clipped)
        assert clipped is not None
        self.assertGreaterEqual(clipped[0][3], ModelPreviewWidget._OVERLAY_CLIP_EPSILON)
        self.assertGreaterEqual(clipped[1][3], ModelPreviewWidget._OVERLAY_CLIP_EPSILON)


class ModelPreviewRenderSafetyTests(unittest.TestCase):
    def test_alignment_live_rotation_matrix_matches_static_replacer_euler_order(self) -> None:
        matrix = ModelPreviewWidget._alignment_euler_xyz_matrix((25.0, -35.0, 12.0))
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

        base_matrix = ModelPreviewWidget._alignment_euler_xyz_matrix(base_rotation)
        target_matrix = ModelPreviewWidget._alignment_euler_xyz_matrix(
            tuple(base_rotation[index] + live_delta[index] for index in range(3))
        )
        delta_matrix = ModelPreviewWidget._alignment_euler_delta_matrix(base_rotation, live_delta)

        current_point = base_matrix.map(point)
        expected_point = target_matrix.map(point)
        actual_point = delta_matrix.map(current_point)

        self.assertAlmostEqual(expected_point.x(), actual_point.x(), places=6)
        self.assertAlmostEqual(expected_point.y(), actual_point.y(), places=6)
        self.assertAlmostEqual(expected_point.z(), actual_point.z(), places=6)

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

    def test_sketchfab_style_geometry_diagnostic_modes_are_available(self) -> None:
        for mode, label in (
            ("matcap", "Matcap"),
            ("wireframe", "Wireframe"),
            ("vertex_normals", "Vertex Normals"),
            ("uv_checker", "UV Checker"),
        ):
            self.assertIn(mode, MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES)
            self.assertEqual(label, MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS[mode])
            settings = clamp_model_preview_render_settings(ModelPreviewRenderSettings(render_diagnostic_mode=mode))
            self.assertEqual(mode, settings.render_diagnostic_mode)

        shader_source = Path("cdmw/ui/widgets.py").read_text(encoding="utf-8")
        self.assertIn("attribute vec3 barycentric;", shader_source)
        self.assertIn("wireframe_edge_factor", shader_source)
        self.assertIn("procedural_matcap", shader_source)
        self.assertIn("def _draw_vertex_normals_overlay", shader_source)
        self.assertIn("uv_checker_color", shader_source)

    def test_normal_diagnostics_distinguish_geometry_from_texture_maps(self) -> None:
        self.assertEqual("Geometry Normal", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["normal"])
        self.assertEqual("Normal Texture Raw", MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS["normal_raw"])
        self.assertEqual(5, _RENDER_DIAGNOSTIC_MODE_CODES["normal"])
        self.assertEqual(11, _RENDER_DIAGNOSTIC_MODE_CODES["normal_raw"])

        shader_source = Path("cdmw/ui/widgets.py").read_text(encoding="utf-8")
        self.assertIn("varying vec3 frag_object_normal;", shader_source)
        self.assertIn("vec3 geometry_normal = safe_normalize(frag_object_normal", shader_source)

    def test_derived_relief_texture_generation_is_relief_mode_only(self) -> None:
        self.assertFalse(
            ModelPreviewWidget._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="lit")
            )
        )
        self.assertFalse(
            ModelPreviewWidget._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="base_raw")
            )
        )
        self.assertFalse(
            ModelPreviewWidget._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="relief_control_test")
            )
        )
        self.assertTrue(
            ModelPreviewWidget._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="rich_lit")
            )
        )
        self.assertTrue(
            ModelPreviewWidget._render_mode_uses_derived_relief(
                ModelPreviewRenderSettings(render_diagnostic_mode="height_calibrated")
            )
        )

    def test_height_visibility_sampling_reports_relief_contrast(self) -> None:
        image = QImage(3, 1, QImage.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(32, 32, 32, 255))
        image.setPixelColor(1, 0, QColor(128, 128, 128, 255))
        image.setPixelColor(2, 0, QColor(224, 224, 224, 255))

        sample = ModelPreviewWidget._sample_base_texture_visibility(
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

        relief = ModelPreviewWidget._derive_relief_image_from_base(image)

        self.assertIsNotNone(relief)
        assert relief is not None
        sample = ModelPreviewWidget._sample_base_texture_visibility(
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

        self.assertIsNone(ModelPreviewWidget._derive_relief_image_from_base(image))

    def test_enhanced_relief_status_reports_true_and_derived_sources(self) -> None:
        active_state, active_reason, active_usable, active_source = ModelPreviewWidget._enhanced_relief_status(
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
        derived_state, derived_reason, derived_usable, derived_source = ModelPreviewWidget._enhanced_relief_status(
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
        flat_state, flat_reason, flat_usable, flat_source = ModelPreviewWidget._enhanced_relief_status(
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
                ModelPreviewWidget._diffuse_probe_source_for_render_mode(settings, mode),
            )
        self.assertEqual(
            "material",
            ModelPreviewWidget._diffuse_probe_source_for_render_mode(settings, "sampler_swap_material_on_unit0"),
        )
        self.assertEqual(
            "material",
            ModelPreviewWidget._diffuse_probe_source_for_render_mode(settings, "texture_probe"),
        )
        self.assertEqual(
            "base",
            ModelPreviewWidget._diffuse_probe_source_for_render_mode(
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
        self.assertEqual("lit", settings.d3d11_view_mode)
        self.assertEqual("asset", settings.d3d11_normal_y_mode)
        self.assertEqual("wrap", settings.d3d11_texture_address_mode)

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
        self.assertGreater(defaults.specular_max, 0.0)

    def test_enhanced_relief_shader_path_is_gated(self) -> None:
        source = Path("cdmw/ui/widgets.py").read_text(encoding="utf-8")

        self.assertIn("bool rich_lit = render_diagnostic_mode == 22;", source)
        self.assertIn("for (int relief_step = 0; relief_step < 8; ++relief_step)", source)
        self.assertIn("height_relief_usable != 0", source)
        self.assertIn("effective_height_effect_max = rich_lit ? height_effect_max : 0.35", source)
        self.assertIn("relief_source_code == 2", source)
        self.assertIn("render_diagnostic_mode == 24", source)
        self.assertIn("control_color = max(control_color, vec3(0.22, 0.22, 0.22))", source)
        self.assertIn('MODEL_PREVIEW_RENDER_BUILD_ID = "2026-05-13-native-dds-v1"', source)
        self.assertIn("relief_emboss_rgb", source)
        self.assertIn("relief_local_contrast", source)
        self.assertIn("radical_chiseled", source)
        self.assertIn("radical_cavity", source)
        self.assertIn("normal_detail_strength", source)
        self.assertIn("normal_light_delta", source)
        self.assertIn("self._batch_render_diagnostics = {}", source)
        self.assertIn("Diagnostics pending repaint:", source)

    def test_black_output_triage_distinguishes_missing_base_from_support_only(self) -> None:
        framebuffer = _FramebufferVisibilitySample(visible_pixels=100, average_luma=0.02, dark_ratio=0.95)
        missing_base_lines = ModelPreviewWidget._black_output_triage_lines(
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
        support_only_lines = ModelPreviewWidget._black_output_triage_lines(
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

        available = ModelPreviewWidget._support_map_slot_counts_from_batches(batches)
        active = ModelPreviewWidget._support_map_active_counts_from_diagnostics(diagnostics)

        self.assertEqual({"normal": 1, "material": 1, "height": 1}, available)
        self.assertEqual({"normal": 1, "material": 0, "height": 1}, active)
        self.assertEqual("n:1 m:0 h:1", ModelPreviewWidget._format_support_map_counts(active))

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

        vertex_blob, vertex_count, batches = ModelPreviewWidget._build_vertex_blob(model)
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

        _vertex_blob, _vertex_count, batches = ModelPreviewWidget._build_vertex_blob(ModelPreviewData(meshes=[mesh]))

        self.assertTrue(batches[0].has_texture_coordinates)
        self.assertEqual(0.0, batches[0].tangent_finite_ratio)
        self.assertEqual(0.0, batches[0].bitangent_finite_ratio)
        self.assertFalse(ModelPreviewWidget._support_map_geometry_usable(batches[0]))

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

        vertex_blob, _vertex_count, batches = ModelPreviewWidget._build_vertex_blob(model)
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

        _clone, prepared = ModelPreviewWidget.prepare_model_preview(model)

        self.assertIsNotNone(prepared)
        assert prepared is not None
        self.assertEqual("low_authority_overlay", prepared.batches[0].preview_base_texture_quality)

    def test_texture_visibility_sampling_reports_luma_dark_ratio_and_alpha(self) -> None:
        image = QImage(2, 1, QImage.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(0, 0, 0, 128))
        image.setPixelColor(1, 0, QColor(255, 255, 255, 255))

        sample = ModelPreviewWidget._sample_base_texture_visibility(
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

        sample = ModelPreviewWidget._sample_framebuffer_visibility(
            image,
            background,
            max_samples=64,
        )

        self.assertGreaterEqual(sample.visible_pixels, 1)
        self.assertGreater(sample.background_ratio, 0.5)
        self.assertGreater(sample.average_luma, 0.5)

    def test_enabling_textures_rebuilds_derived_relief_textures(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("def set_use_textures", source)
        self.assertIn("previous != self._use_textures", source)
        self.assertIn("self._gl_ready", source)
        self.assertIn("self._clear_gl_textures()", source)
        self.assertIn("self._rebuild_gl_textures()", source)

    def test_model_preview_reuses_textures_for_transform_only_updates(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        upload_start = source.index("def _upload_geometry")
        upload_end = source.index("def _current_texture_upload_cache_signature", upload_start)
        upload_block = source[upload_start:upload_end]
        self.assertIn("texture_cache_signature = self._current_texture_upload_cache_signature()", upload_block)
        self.assertIn("if texture_cache_signature != self._texture_upload_cache_signature:", upload_block)
        self.assertIn("self._texture_upload_cache_signature = texture_cache_signature", upload_block)
        self.assertNotIn("        self._clear_gl_textures()\n        self._program.bind()", upload_block)
        self.assertIn("def _current_texture_upload_cache_signature", source)
        self.assertIn("upload_support_maps = bool(", source)
        self.assertIn("if upload_support_maps:", source)
        self.assertIn("existing_texture = self._texture_objects.get(cache_key)", source)
        self.assertIn("continue", source[source.index("existing_texture = self._texture_objects.get(cache_key)"):])

    def test_model_preview_has_committed_transform_fast_path_and_timing_diagnostics(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("def set_alignment_committed_preview_transform", source)
        self.assertIn("_alignment_committed_preview_translation", source)
        self.assertIn("_alignment_committed_preview_rotation", source)
        self.assertIn("_alignment_committed_preview_scale", source)
        self.assertIn("or has_committed_transform", source)
        self.assertIn("self._alignment_committed_preview_translation = QVector3D(0.0, 0.0, 0.0)", source)
        self.assertIn("self._last_model_prepare_ms", source)
        self.assertIn("prepare_elapsed_ms: Optional[float] = None", source)
        self.assertIn("self.set_prepared_model(cloned_model, prepared_preview, prepare_elapsed_ms=prepare_elapsed_ms)", source)
        self.assertIn("self._last_gl_upload_ms", source)
        self.assertIn("def _read_opengl_renderer_info", source)
        self.assertIn("functions.glGetString", source)
        self.assertIn("string_at(raw)", source)
        self.assertIn('"Renderer: "', source)

    def test_hkx_physics_overlay_supports_hover_and_ctrl_click_selection(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("_physics_overlay_target_at", source)
        self.assertIn("_physics_hover_target", source)
        self.assertIn("_physics_selected_target", source)
        self.assertIn("_physics_edited_viewer_ids", source)
        self.assertIn("set_physics_overlay_edited_targets", source)
        self.assertIn("_draw_physics_edited_badge", source)
        self.assertIn("edited shape", source)
        self.assertIn("edited constraint", source)
        self.assertIn("physics_overlay_target_selected = Signal", source)
        self.assertIn("_set_physics_overlay_selected_target", source)
        self.assertIn("_physics_overlay_anchor_is_context_skeleton", source)
        self.assertIn("_physics_overlay_shape_is_context_skeleton", source)
        self.assertIn("_physics_overlay_constraint_is_context_skeleton", source)
        self.assertIn("_physics_simulation_shape_is_dynamic", source)
        self.assertIn("_physics_simulation_constraint_is_dynamic", source)
        self.assertIn("context skeleton hidden", source)
        self.assertIn("Click/Ctrl-click overlay: show linked HKX rows", source)
        self.assertIn("Qt.PointingHandCursor", source)
        self.assertIn("max_labels = 0", source)
        self.assertIn("_physics_simulation_role_color", source)
        self.assertIn("_draw_physics_motion_envelope", source)
        self.assertIn("simulation_role_counts", source)
        self.assertIn("_step_physics_simulation_preview", source)
        self.assertIn("_physics_simulation_state", source)
        self.assertIn("_physics_shape_simulation_key", source)
        self.assertIn("_physics_shape_rest_position", source)
        self.assertIn("_draw_simulated_physics_shape", source)
        self.assertIn("shape:" , source)
        self.assertIn("Physics Animation Preview", source)
        self.assertIn("dynamic_shapes", source)
        self.assertIn("disabled: approximate animation off", source)
        self.assertIn("disabled: overlay hidden", source)
        self.assertIn("wind_scale * 2.4", source)
        self.assertIn("live sim", source)
        self.assertIn("cloth_preview_strength", source)
        self.assertIn("_batch_cloth_deformation_strength", source)
        self.assertIn("mesh_deform_batches", source)
        self.assertIn("cloak", source)
        self.assertIn("cloth mesh physics preview", source)
        self.assertIn("cloth_preview_offset", source)
        self.assertIn("_cloth_deformation_preview_offset", source)
        self.assertIn("_last_emitted_debug_details_text", source)
        self.assertIn("_physics_simulation_last_debug_refresh", source)
        self.assertIn(">= 0.50", source)
        self.assertIn("wave_a * 0.060", source)
        self.assertIn("Native Texture Backend", source)
        self.assertIn("_load_native_texture_report", source)
        self.assertIn("native_texture_backend", source)

    def test_hkx_skeleton_context_is_static_for_approx_motion_preview(self) -> None:
        widget = ModelPreviewWidget.__new__(ModelPreviewWidget)

        self.assertFalse(
            widget._physics_simulation_constraint_is_dynamic(
                HkxPhysicsOverlayConstraint(simulation_role="cloth", confidence="skeleton_context")
            )
        )
        self.assertTrue(
            widget._physics_simulation_constraint_is_dynamic(
                HkxPhysicsOverlayConstraint(simulation_role="cloth", confidence="descriptor_context")
            )
        )
        self.assertFalse(
            widget._physics_simulation_shape_is_dynamic(
                HkxPhysicsOverlayShape(simulation_role="cloth", placement_source="skeleton_socket")
            )
        )
        self.assertTrue(widget._physics_simulation_shape_is_dynamic(HkxPhysicsOverlayShape(simulation_role="cloth")))

    def test_referenced_hkx_previews_disable_legacy_guide_motion(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "main_window.py").read_text(encoding="utf-8")
        reference_start = source.index("def _show_archive_reference_preview_dialog")
        reference_end = source.index("def _update_archive_texture_reference_action_controls", reference_start)
        reference_source = source[reference_start:reference_end]
        embedded_start = source.index("def _enable_hkx_preview_overlay")
        embedded_end = source.index("def _current_hkx_link_preview_model", embedded_start)
        embedded_source = source[embedded_start:embedded_end]
        main_apply_start = source.index("model_preview_widget.set_prepared_model(")
        main_apply_end = source.index("self._sync_archive_isolated_renderer_if_running(result)", main_apply_start)
        main_apply_source = source[main_apply_start:main_apply_end]

        self.assertIn('str(entry.extension or "").lower() in {".hkx", ".hkt"}', reference_source)
        self.assertIn("show_physics_overlay=True", reference_source)
        self.assertIn("show_physics_simulation_preview=False", reference_source)
        self.assertIn("show_physics_simulation_preview", embedded_source)
        self.assertIn("show_physics_simulation_preview=False", embedded_source)
        self.assertIn('str(getattr(selected_entry, "extension", "") or "").lower() in {".hkx", ".hkt"}', main_apply_source)
        self.assertIn("show_physics_simulation_preview=False", main_apply_source)

    def test_framebuffer_visibility_probe_is_throttled(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("_framebuffer_visibility_sampled_at", source)
        self.assertIn("time.monotonic()", source)
        self.assertIn(">= 0.50", source)
        self.assertIn("self.grabFramebuffer()", source)

    def test_render_sampling_diagnostics_include_geometry_and_output_buckets(self) -> None:
        widget = ModelPreviewWidget.__new__(ModelPreviewWidget)
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

        text = "\n".join(widget._render_sampling_diagnostic_lines())

        self.assertIn("Diagnostic Render Mode: Base Color", text)
        self.assertIn("Framebuffer probe:", text)
        self.assertIn("rich_material=no", text)
        self.assertIn("normals=67% repaired=1", text)
        self.assertIn("tangent=100%", text)
        self.assertIn("final_bucket=invalid normals repaired", text)


if __name__ == "__main__":
    unittest.main()
