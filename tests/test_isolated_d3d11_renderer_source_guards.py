from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from PySide6.QtGui import QColor, QImage

from tests.native_source_text import d3d11_preview_source, texture_dx_source

from cdmw.models import (
    ClothPreviewBatch,
    ClothPreviewConstraint,
    ClothPreviewData,
    HkxPhysicsOverlayData,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayShape,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PbdMaterialSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.core.texture_native import write_native_texture_report_sidecar
from cdmw.rendering.native_preview_package import (
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    _material_hex_color_rgb,
    read_isolated_d3d11_preview_manifest,
    write_isolated_d3d11_preview_package,
)
from cdmw.workers.d3d11_package_workers import AlignmentD3D11PackageWorker


def _archive_d3d11_ui_source() -> str:
    return "\n".join(
        (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/settings_persistence.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/window_runtime_state.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_layout.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_parts.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_runtime.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_worker.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8"),
            Path("cdmw/workers/d3d11_package_workers.py").read_text(encoding="utf-8"),
        )
    )


def _vertex(
    x: float,
    y: float,
    z: float,
    *,
    color: tuple[float, float, float] = (0.25, 0.50, 0.75),
    uv: tuple[float, float] = (0.0, 0.0),
) -> bytes:
    return struct.pack(
        "<23f",
        x,
        y,
        z,
        0.0,
        0.0,
        1.0,
        color[0],
        color[1],
        color[2],
        uv[0],
        uv[1],
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        0.0,
    )


def _minimal_bc_dds(fourcc: bytes = b"DXT1") -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = (4).to_bytes(4, "little")
    header[12:16] = (4).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = fourcc
    block_size = 8 if fourcc == b"DXT1" else 16
    return b"DDS " + bytes(header) + (b"\0" * block_size)


class IsolatedD3D11RendererSourceGuardTests(unittest.TestCase):
    def test_native_host_is_isolated_from_qt_scene_and_archive_stack(self) -> None:
        source = d3d11_preview_source()

        self.assertIn("D3D11CreateDevice", source)
        self.assertIn("D3D11CreateDeviceAndSwapChain", source)
        self.assertIn("D3DCompile", source)
        self.assertIn("DirectX::LoadFromDDSFile", source)
        self.assertIn("DirectX::CreateShaderResourceView", source)
        self.assertIn("--preview-package", source)
        self.assertIn("--status-file", source)
        self.assertIn("--parent-hwnd", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("dds_direct_upload_candidates", source)
        self.assertIn("dds_direct_uploads", source)
        self.assertIn("dds_upload_formats", source)
        self.assertIn("texture_cache_hits", source)
        self.assertIn("best_material_dds_for_role", source)
        self.assertIn("material_hints", source)
        self.assertIn("material_shader_family", source)
        self.assertIn("material_family_code", source)
        self.assertIn("row_major float4x4 normal_world", source)
        self.assertIn("mul(float4(input.normal, 0.0), normal_world)", source)
        self.assertIn("mul(float4(input.tangent, 0.0), normal_world)", source)
        self.assertIn("mul(float4(input.bitangent, 0.0), normal_world)", source)
        self.assertIn("batch_world * view_projection", source)
        self.assertIn("base_tint_strength", source)
        self.assertIn("boosted_preview_layer_weight", source)
        self.assertIn("float tint_alpha = saturate(layer_tint[ID].a) * (early_category_metal ? 0.18 : 1.0);", source)
        self.assertIn("float strong_dye_strength = saturate((layer_chroma - 0.38) * 1.65) * (early_category_metal ? 0.05 : 1.0);", source)
        self.assertIn("float3 dye_authority_color = saturate(layer_tint_rgb * (0.62 + layer_lifted_luma * 0.70));", source)
        self.assertIn("neutral_metal_tint", source)
        self.assertIn("neutral_metal_luma", source)
        self.assertIn('const bool draw_albedo_layer = lower_copy(layer.role) != "base";', source)
        self.assertIn("prefer_generated_base_texture", source)
        self.assertIn("batch.base_dds.clear()", source)
        self.assertIn("material_reference_albedo", source)
        self.assertIn("stable_ao", source)
        self.assertIn("float3 color = material_reference_albedo * stable_ao * nonmetal_texture_scale * diffuse_depth * metal_diffuse_scale;", source)
        self.assertIn("color += material_reference_albedo * metal_cue * 0.16;", source)
        self.assertNotIn("color += float3(0.78, 0.82, 0.88) * metal_cue;", source)
        self.assertIn("ggx_distribution", source)
        self.assertIn("geometry_smith", source)
        self.assertIn("fresnel_schlick", source)
        self.assertIn("aces_tonemap", source)
        self.assertIn("direct_metal_response", source)
        self.assertIn("category_metal_cap = max(category_metal_cap, 0.96)", source)
        self.assertIn("emissive_color = max(emissive_color, emissive_sample.rgb)", source)
        self.assertIn("roughness_bias", source)
        self.assertIn("explicit_material_authority_hint", source)
        self.assertIn("roughness = lerp(roughness, material_hints.x, 0.72);", source)
        self.assertIn("category_roughness_floor = min(category_roughness_floor, lerp(0.08, 0.42, saturate(material_hints.x)));", source)
        self.assertIn("roughness = lerp(roughness, material_hints.x, 0.55);", source)
        self.assertIn("relief_edge = saturate((abs(ddx(texture_luma)) + abs(ddy(texture_luma))) * 34.0)", source)
        self.assertIn("float matte_preview = saturate((material_hints.x - 0.62) * 2.63);", source)
        self.assertIn("float authority_gloss_cue = (explicit_material_authority_hint && !conservative_nonmetal)", source)
        self.assertIn("env_material_scale = max(env_material_scale, authority_gloss_cue * 0.32);", source)
        self.assertNotIn("0.62, 0.68, 0.75", source)
        self.assertNotIn("smoothness * 0.45", source)
        self.assertIn("RenderTuning", source)
        self.assertIn("parse_render_tuning", source)
        self.assertIn('normalized_view_mode == "game_outdoor"', source)
        package_source = "\n".join(
            (
                Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8"),
                Path("cdmw/rendering/native_preview_package_writer.py").read_text(encoding="utf-8"),
                Path("cdmw/rendering/native_preview_payloads.py").read_text(encoding="utf-8"),
            )
        )
        self.assertIn("game_outdoor_approx", package_source)
        self.assertIn("tuning.emissive_gain = std::max(tuning.emissive_gain, 1.80f)", source)
        self.assertIn("d3d11_tone_exposure", source)
        self.assertIn("d3d11_tone_contrast", source)
        self.assertIn("d3d11_tone_gamma", source)
        self.assertIn("mapped = aces_tonemap(color * tone_exposure)", source)
        self.assertIn("mapped = saturate((mapped - 0.5) * tone_contrast + 0.5)", source)
        self.assertIn("float3(tone_gamma, tone_gamma, tone_gamma)", source)
        self.assertIn("MaxAnisotropy", source)
        self.assertIn("render_tuning", source)
        self.assertIn("detail_tex", source)
        self.assertIn("CREATETEX_FORCE_SRGB", source)
        self.assertIn("CREATETEX_IGNORE_SRGB", source)
        self.assertIn("struct ComInitScope", source)
        self.assertIn("CoInitializeEx(nullptr, COINIT_MULTITHREADED)", source)
        self.assertIn("CoUninitialize()", source)
        self.assertIn("hr == RPC_E_CHANGED_MODE", source)
        self.assertIn("hr = create_srv(create_flags)", source)
        self.assertIn("hr = create_srv(static_cast<DirectX::CREATETEX_FLAGS>(0))", source)
        self.assertIn("Some WIC-decoded PNGs from external model archives fail", source)
        self.assertIn("srgb_color_uploads", source)
        self.assertIn("linear_to_srgb", source)
        self.assertIn("srgb_to_linear", source)
        self.assertIn("begin_mouse_drag", source)
        self.assertIn("void cancel_mouse_interaction(bool release_capture = true)", source)
        self.assertIn("case WM_CONTEXTMENU:", source)
        self.assertIn("case WM_CANCELMODE:", source)
        self.assertIn("case WM_KILLFOCUS:", source)
        self.assertIn("if (mesh_edit_.drag_active || mesh_edit_.selection_drag_active || alignment_.drag_active || alignment_.rotation_drag_active)", source)
        self.assertIn("if (drag_mode_ != 0)", source)
        self.assertIn("kZoomSteps", source)
        self.assertIn("kMaxZoomFactor = 64.0f", source)
        self.assertIn("std::clamp(zoom_factor, 0.1f, kMaxZoomFactor)", source)
        self.assertIn("WM_MOUSEWHEEL", source)
        self.assertIn("void set_camera_for_role(PreviewViewRole role, const PreviewCameraState& camera)", source)
        self.assertIn("if (role == PreviewViewRole::Reference) {\n            return reference_camera_;\n        }", source)
        self.assertIn("drag_view_role_ = input_view_role_at(x, y);", source)
        self.assertIn("const PreviewViewRole role = input_view_role_at(x, y);", source)
        self.assertNotIn("(void)role;\n        return replacement_camera();", source)
        self.assertIn("WM_COPYDATA", source)
        self.assertIn("kCdmwCommandCopyData", source)
        self.assertIn("process_pending_commands", source)
        self.assertIn("load_package", source)
        self.assertIn('if (command == "set_alignment_transforms")', source)
        load_start = source.index("bool load_package(")
        load_body = source[load_start: source.index("bool clear_preview", load_start)]
        self.assertNotIn("alignment_.selected_source_submeshes.clear();", load_body)
        self.assertNotIn("alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);", load_body)
        self.assertNotIn("alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);", load_body)
        self.assertIn("alignment_.part_translation_drag_bases.clear();", load_body)
        clear_start = source.index("bool clear_preview")
        clear_body = source[clear_start: source.index("bool process_pending_commands", clear_start)]
        self.assertIn("alignment_.part_transforms.clear();", clear_body)
        self.assertIn("alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);", clear_body)
        self.assertIn("source_submesh_indices", source)
        self.assertIn("highlight_strength", source)
        self.assertIn("png_fallbacks", source)
        self.assertIn("material_combiner_outputs", source)
        self.assertIn("Texture2D roughness_tex", source)
        self.assertIn("Texture2D metalness_tex", source)
        self.assertIn("Texture2D specular_tex", source)
        self.assertIn("Texture2D height_tex", source)
        self.assertNotIn("Qt" + "Quick", source)
        self.assertNotIn("Q" + "QuickWidget", source)
        self.assertNotIn("Q" + "QuickView", source)
        self.assertNotIn("QGreenUpWidget", source)
        self.assertNotIn("main_window", source)
        self.assertNotIn("configure_experimental_" + "qt" + "quick" + "3d_rhi", source)
        self.assertNotIn("parse_mesh(", source)
        self.assertNotIn("build_archive_preview_result", source)
        self.assertNotIn("std::cin", source)

    def test_directxtex_helper_reports_dds_direct_upload_metadata(self) -> None:
        source = texture_dx_source()

        self.assertIn("DirectX::LoadFromDDSFile", source)
        self.assertIn("DirectX::SaveToWICFile", source)
        self.assertIn("DirectX::SaveToDDSFile", source)
        self.assertIn("batch-encode-json", source)
        self.assertIn("native_diagnostics.h", source)
        self.assertIn("batch_preview_start", source)
        self.assertIn("batch_encode_start", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("parse_encode_jobs", source)
        self.assertIn("CoInitializeEx", source)
        self.assertIn("DXGI_FORMAT_BC1_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC3_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC5_UNORM", source)
        self.assertIn("DXGI_FORMAT_BC7_UNORM", source)
        self.assertIn("direct_upload_candidate", source)
        self.assertIn("compressed_family", source)
        self.assertIn("normal_green_inverted", source)
        self.assertIn("DirectX::Decompress(*first, DXGI_FORMAT_R8G8B8A8_UNORM", source)
        self.assertIn("rgba.InitializeFromImage(*convert_source)", source)
        self.assertIn("source_format=", source)

    def test_native_d3d11_is_archive_renderer_backend_and_qt_scene_is_not_used(self) -> None:
        source = _archive_d3d11_ui_source()
        renderer_source = Path("cdmw/ui/model_preview_native.py").read_text(encoding="utf-8")
        preview_worker_source = Path("cdmw/workers/archive_preview_native.py").read_text(encoding="utf-8")
        host_source = Path("cdmw/ui/native_d3d11_preview_host.py").read_text(encoding="utf-8")

        self.assertIn("archive_isolated_renderer_button", source)
        self.assertIn("archive_d3d11_preview_host", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11", renderer_source)
        self.assertIn("normalize_archive_model_renderer_backend", renderer_source)
        self.assertIn("from cdmw.ui.model_preview_native import", source)
        self.assertIn("low_res_base", source)
        self.assertIn("NativeD3D11PreviewHostFrame", source)
        self.assertIn("_WM_SET_ZOOM", host_source)
        self.assertIn("_WM_COPYDATA_COMMAND", host_source)
        self.assertIn('preferred_state["role"] = "replacement"', host_source)
        self.assertIn("load_package(self, package_dir", host_source)
        self.assertIn("clear_preview(self, status_file", host_source)
        self.assertIn("set_render_tuning(self, settings", host_source)
        self.assertIn("set_highlighted_source_submeshes", host_source)
        self.assertIn("set_hidden_source_submeshes", host_source)
        self.assertIn("archive_d3d11_part_visibility_button", source)
        self.assertIn("_populate_archive_d3d11_part_visibility_menu", source)
        self.assertIn("archive_d3d11_part_visibility_groups", source)
        self.assertIn("Hide added prefab pieces", source)
        self.assertIn("archive_isolated_renderer_package_source", source)
        self.assertIn("_native_preview_core_failure_result", preview_worker_source)
        self.assertIn("D3D11 runtime is native-only", preview_worker_source)
        self.assertNotIn("_native_preview_core_quality_fallback_reason", source)
        self.assertNotIn("material quality fallback", source)
        self.assertIn("native_preview_package_path", source)
        self.assertIn('Loading preview... starting renderer.', source)
        self.assertIn("base_srgb", source)
        self.assertIn("find_native_d3d11_host", source)
        self.assertIn("--preview-package", source)
        self.assertIn("--status-file", source)
        self.assertIn("--parent-hwnd", source)
        self.assertIn("--crash-dir", source)
        self.assertIn("--diagnostic-log", source)
        self.assertIn("enable_material_combiner=True", source)
        self.assertIn("prefer_direct_dds=True", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertNotIn("archive_model_preview_renderer_combo", source)
        self.assertNotIn('"--isolated-renderer-host"', source)

    def test_archive_launcher_is_one_shot_and_status_file_based(self) -> None:
        source = _archive_d3d11_ui_source()

        self.assertIn("QProcess", source)
        self.assertIn("ArchiveD3D11PackageWorker", source)
        self.assertIn("_start_archive_isolated_preview_package_worker", source)
        self.assertIn("_handle_archive_isolated_package_ready", source)
        self.assertIn("_launch_archive_isolated_preview_result", source)
        self.assertIn("_poll_archive_isolated_renderer_status", source)
        self.assertIn("archive_isolated_renderer_status_timer", source)
        self.assertIn("_clear_archive_isolated_renderer_surface_for_request", source)
        self.assertIn("keeping the current model visible while the next package is prepared", source)
        self.assertIn("self._clear_archive_d3d11_part_visibility_menu()", source)
        self.assertIn("self._populate_archive_d3d11_part_visibility_menu(package_dir)", source)
        self.assertNotIn("self.archive_d3d11_preview_host.clear_preview(status_file)", source)
        self.assertIn("archive_d3d11_view_state", source)
        self.assertIn("view_state_payload_changed.connect(self._handle_archive_d3d11_view_state_payload)", source)
        self.assertIn("preserved_view_state", source)
        self.assertIn("archive_d3d11_active_model_key", source)
        self.assertIn("same_d3d11_model", source)
        self.assertIn("reset_view=not same_d3d11_model", source)
        self.assertIn("_sanitize_d3d11_view_state_for_restore", source)
        self.assertIn("self.archive_d3d11_preview_host.restore_view_state(state)", source)
        self.assertIn("self.archive_d3d11_preview_host.set_render_tuning(self._current_model_preview_render_settings())", source)
        self.assertIn("Native D3D11 Preview Contract", source)
        self.assertIn("Material Channel Contract:", source)
        self.assertIn("_archive_material_channel_debug_from_package", source)
        self.assertIn("material_channel_contract", source)
        self.assertIn("Native D3D11 Overlay Metadata", source)
        self.assertIn("semantic_writes", source)
        self.assertIn('def _yes_no(value: object) -> str:', source)
        self.assertNotIn("self._yes_no", source)
        self.assertIn("process.terminate()", source)
        self.assertIn("generation = self._register_archive_isolated_renderer_process(process, status_file)", source)
        self.assertIn("partial(self._handle_archive_isolated_renderer_stderr, process, generation)", source)
        self.assertIn("partial(self._handle_archive_isolated_renderer_finished, process, generation)", source)
        self.assertIn("partial(self._handle_archive_isolated_renderer_error, process, generation)", source)
        self.assertIn("_mark_archive_isolated_renderer_expected_stop", source)
        self.assertIn("_consume_archive_isolated_renderer_expected_stop", source)
        self.assertIn("_check_archive_isolated_renderer_start_timeout", source)
        self.assertIn("_archive_isolated_renderer_signal_is_current", source)
        self.assertNotIn("process.disconnect()", source)
        self.assertIn('elif event == "loading":', source)
        self.assertNotIn("waitForFinished(", source)
        self.assertNotIn("readyReadStandardOutput.connect(self._handle_archive_isolated_renderer_stdout)", source)
        self.assertNotIn('"command": "load"', source)
        self.assertNotIn('"command": "shutdown"', source)

    def test_native_d3d11_host_supports_clear_command_for_stale_previews(self) -> None:
        source = d3d11_preview_source()

        self.assertIn("bool clear_preview", source)
        self.assertIn('command == "clear_preview"', source)
        self.assertIn('command == "set_render_tuning"', source)
        self.assertIn('command == "set_hidden_source_submeshes"', source)
        self.assertIn("hidden_source_submeshes_", source)
        self.assertIn('"{\\"event\\":\\"part_visibility\\"', source)
        self.assertIn("command_set_render_tuning", source)
        self.assertIn("d3d11_mip_lod_bias", source)
        self.assertIn("d3d11_texture_address_mode", source)
        self.assertIn("d3d11_cull_back_faces", source)
        self.assertIn("d3d11_normal_y_mode", source)
        self.assertIn("view_settings_overridden_", source)
        self.assertIn("render_tuning_overridden_", source)
        self.assertIn("if (!view_settings_overridden_)", source)
        self.assertIn("if (!render_tuning_overridden_)", source)
        self.assertNotIn("!stats_.lighting_preset.empty()", source)
        self.assertIn("texture_details", source)
        self.assertIn("material_contract_schema", source)
        self.assertIn("material_channel_contract_schema", source)
        self.assertIn("physics_overlay_enabled", source)
        self.assertIn('json_object_field(manifest, "skeleton_overlay")', source)
        self.assertIn("skeleton_bone_count", source)
        self.assertIn("skeleton_pose_enabled", source)
        self.assertIn("semantic_writes_enabled", source)
        self.assertIn("batches_.clear()", source)
        self.assertIn("Native D3D11 preview cleared", source)
        self.assertIn("native_diagnostics.h", source)
        self.assertIn("package_load_start", source)
        self.assertIn("upload_batches", source)
        self.assertIn("first_frame", source)
        reload_success_block = source[
            source.index("if (reset_view_state) {")
            : source.index('cdmw_native_diag::event(\n            "package_loaded"', source.index("if (reset_view_state) {"))
        ]
        self.assertIn("resources_loaded_payload(stats_)", reload_success_block)
        self.assertIn("request_render();", reload_success_block)
        self.assertNotIn("write_status(args_.status_file, loaded_payload(stats_));", reload_success_block)
        startup_success_block = source[
            source.index("if (!renderer.initialize()) {")
            : source.index(
                "const std::string close_reason = run_host_message_loop(",
                source.index("if (!renderer.initialize()) {"),
            )
        ]
        self.assertIn("resources_loaded_payload(stats)", startup_success_block)
        self.assertIn("renderer.request_render();", startup_success_block)
        self.assertNotIn("write_status(args.status_file, loaded_payload(stats));", startup_success_block)
        render_block = source[
            source.index("void render() {") : source.index("bool process_pending_commands", source.index("void render() {"))
        ]
        self.assertIn("HRESULT present_hr", render_block)
        self.assertIn("swap_chain_->Present(1, 0)", render_block)
        self.assertIn("is_device_loss_hresult(present_hr)", render_block)
        self.assertIn("handle_device_loss(\"Present\", present_hr)", render_block)
        self.assertIn("render_requested_ = !device_lost_;", render_block)
        self.assertIn("write_status(args_.status_file, loaded_payload(stats_));", render_block)
        resize_block = source[
            source.index("bool resize_if_needed()") : source.index("bool create_pipeline()", source.index("bool resize_if_needed()"))
        ]
        self.assertIn("CDMW_D3D11_PREVIEW_FORCE_RESIZE_FAILURE", resize_block)
        self.assertIn("resize_failure_hresult", resize_block)
        self.assertIn("handle_device_loss(\"ResizeBuffers\", hr)", resize_block)
        self.assertNotIn("width_ = next_width;\n        height_ = next_height;\n        if (context_)", resize_block)
        self.assertIn("native_unhandled_exception", Path("native/common/native_diagnostics.h").read_text(encoding="utf-8"))
        self.assertIn('if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score -= 220;', source)

    def test_native_d3d11_host_throttles_idle_rendering_and_prunes_srv_cache(self) -> None:
        source = d3d11_preview_source()

        self.assertIn("void request_render()", source)
        self.assertIn("bool should_render() const", source)
        self.assertIn("render_requested_", source)
        self.assertIn("renderer.should_render()", source)
        self.assertIn("MsgWaitForMultipleObjects", source)
        self.assertIn("kIdleWaitMs", source)
        self.assertIn("WM_PAINT", source)
        self.assertIn("BeginPaint(hwnd_, &ps)", source)
        self.assertIn("EndPaint(hwnd_, &ps)", source)
        self.assertIn("ValidateRect(hwnd_, nullptr)", source)
        self.assertIn("WM_SIZE", source)
        self.assertIn("SendMessageTimeoutW", source)
        self.assertIn("kParentHealthCheckMs", source)
        self.assertIn("kParentHangExitMs", source)
        self.assertIn("parent_unresponsive_exit", source)
        self.assertIn("parent_window_gone", source)
        self.assertIn("parent_not_renderable", source)
        self.assertIn("window_not_visible", source)
        self.assertIn("void note_render_suppressed", source)
        self.assertIn("render_suppressed", source)
        self.assertIn("frame_count", source)
        self.assertIn("render_request_count", source)
        self.assertIn("parent_health", source)
        self.assertIn("closed_payload(stats, close_reason)", source)
        self.assertIn("release_model_resources(close_reason.c_str())", source)
        self.assertIn("kSrvCacheSoftMaxEntries", source)
        self.assertIn("kSrvCacheSoftMaxBytes", source)
        self.assertIn("prune_srv_cache_if_needed", source)
        self.assertIn("texture_cache_pruned", source)
        self.assertIn('prune_srv_cache_if_needed("pre_upload_soft_cap")', source)
        self.assertIn('prune_srv_cache_if_needed("texture_load_soft_cap")', source)
        self.assertIn("texture_file_identity", source)
        self.assertIn("texture_cache_key(path, dds, create_flags)", source)
        self.assertIn("active_bound_texture_bytes", source)
        self.assertIn("texture_cache_bytes", source)
        self.assertIn("live_texture_bytes", source)
        self.assertIn('reason_text == "clear"', source)

    def test_native_d3d11_host_runs_tool_side_pbd_cloth_preview(self) -> None:
        source = d3d11_preview_source()
        main_window_source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_settings.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_settings_state.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")
        )

        self.assertIn("struct ClothRuntime", source)
        self.assertIn("struct ClothCollider", source)
        self.assertIn("cloth_enabled", source)
        self.assertIn("parse_cloth_colliders", source)
        self.assertIn("load_cloth_runtime", source)
        self.assertIn("step_cloth_simulation", source)
        self.assertIn("D3D11_USAGE_DYNAMIC", source)
        self.assertIn("D3D11_MAP_WRITE_DISCARD", source)
        self.assertIn("reset_tool_pbd_cloth_preview", source)
        self.assertIn("draw_cloth_debug_overlays", source)
        self.assertIn("show_tool_pbd_cloth_pins", source)
        self.assertIn("show_tool_pbd_cloth_colliders", source)
        self.assertIn("cloth_simulation_steps", source)
        self.assertIn("pbd_hint_count", source)
        self.assertIn("pbd_soft_hint_count", source)
        self.assertIn("pbd_cloth_hint_count", source)
        self.assertIn("Native D3D11 PBD Physics Preview", main_window_source)
        self.assertIn("metadata-only", main_window_source)
        self.assertIn("Tool-side PBD physics preview", main_window_source)

    def test_native_d3d11_host_rejects_stale_or_invalid_packages_and_exposes_debug_modes(self) -> None:
        source = d3d11_preview_source()

        self.assertIn('release_model_resources("load-missing-package")', source)
        self.assertIn("native D3D11 package validation failed", source)
        self.assertIn("native D3D11 manifest read/parse failed", source)
        self.assertIn("next_batches.empty() || !missing_paths.empty()", source)
        self.assertIn("diagnostic_mode_code", source)
        self.assertIn("render_diagnostic_mode", source)
        self.assertIn("uv_checker", source)
        self.assertIn("metal_shine", source)
        self.assertIn("roughness_response", source)
        self.assertIn("material_response", source)
        self.assertIn("albedo_base_only", source)
        self.assertIn("masked_layer_contribution", source)
        self.assertIn('mode == "metalness"', source)
        self.assertIn('mode == "specular_gloss"', source)
        self.assertIn("return float4(saturate(metalness).xxx, 1.0);", source)
        self.assertIn("return float4(saturate(specular), saturate(1.0 - roughness), saturate(metalness), 1.0);", source)
        self.assertIn("material_slot_id", source)
        self.assertIn("layer_masks", source)
        self.assertIn("flags4.y", source)
        self.assertIn("flags4.z", source)
        self.assertIn("base_alpha < max(flags3.w", source)
        self.assertIn("discard;", source)
        self.assertIn("batch.two_sided", source)
        self.assertIn('json_bool_field(object, "two_sided", json_bool_field(object, "double_sided", false))', source)
        self.assertIn("render_tuning_.cull_back_faces && !batch.two_sided && cull_rasterizer_", source)
        self.assertIn("float camera_shape = saturate(abs(dot(n, view_dir)));", source)
        self.assertIn("batch.two_sided ? 1.0f : 0.0f", source)
        self.assertIn("batch.alpha_threshold", source)

    def test_pyinstaller_includes_host_modules(self) -> None:
        source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

        self.assertIn("cdmw.rendering.native_d3d11_host", source)
        self.assertIn("cdmw.rendering.native_preview_package", source)
        self.assertIn("cd-texture-dx.exe", source)
        self.assertIn("cdmw-d3d11-preview.exe", source)

    def test_native_host_discovery_uses_env_override(self) -> None:
        from unittest.mock import patch

        from cdmw.rendering.native_d3d11_host import find_native_d3d11_host

        with tempfile.TemporaryDirectory() as temp_dir:
            host_path = Path(temp_dir) / "cdmw-d3d11-preview.exe"
            host_path.write_bytes(b"fake")
            with patch.dict("os.environ", {"CDMW_D3D11_PREVIEW_BIN": str(host_path)}):
                self.assertEqual(host_path, find_native_d3d11_host())


if __name__ == "__main__":
    unittest.main()
