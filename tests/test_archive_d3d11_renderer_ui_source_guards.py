from __future__ import annotations

from pathlib import Path
import unittest


def _archive_preview_shell_source() -> str:
    return "\n".join(
        (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_layout.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_renderer_controls.py").read_text(encoding="utf-8"),
        )
    )


def _archive_d3d11_runtime_source() -> str:
    return "\n".join(
        (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_d3d11_runtime.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/preview_renderer_controls.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/appearance_composite.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_open.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_transform.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_b.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_d3d11_state.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/archive_browser/attachment_safe_placement_dialog.py").read_text(encoding="utf-8"),
        )
    )


class ArchiveD3D11RendererSourceGuardTests(unittest.TestCase):
    def test_embedded_d3d11_renderer_option_is_removed(self) -> None:
        source = _archive_preview_shell_source()
        renderer_source = Path("cdmw/ui/model_preview_native.py").read_text(encoding="utf-8")

        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11", renderer_source)
        self.assertIn("from cdmw.ui.model_preview_native import", source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_" + "LEGACY", source)
        self.assertNotIn("archive_model_preview_renderer_combo", source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_" + "QT" + "QUICK3D", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertIn("self.archive_model_preview = NativePreviewPanel", source)
        self.assertNotIn("self.archive_model_preview_" + "qt" + "quick" + "3d", source)

    def test_d3d11_only_remains_available_under_settings(self) -> None:
        source = _archive_preview_shell_source()
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")

        self.assertIn("def _selected_archive_model_preview_widget", source)
        self.assertIn("return self.archive_model_preview", source)
        self.assertNotIn("ARCHIVE_RENDERER_" + "LEGACY", dialog_source)
        self.assertIn("Native D3D11", dialog_source)
        self.assertIn("archive_renderer_backend_changed", dialog_source)
        self.assertNotIn("Renderer backend", dialog_source)
        self.assertNotIn("Renderer " + "fallback:", source)

    def test_archive_preview_still_uses_existing_prepared_model_pipeline(self) -> None:
        source = _archive_d3d11_runtime_source()
        package_source = "\n".join(
            (
                Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8"),
                Path("cdmw/rendering/native_preview_package_writer.py").read_text(encoding="utf-8"),
            )
        )

        import_start = source.index("from cdmw.rendering.model_preview_prepare import")
        import_end = source.index(")", import_start)
        self.assertIn("prepare_model_preview", source[import_start:import_end])
        self.assertIn("prepare_model_preview(", source)
        self.assertNotIn("NativePreviewPanel.prepare_model_preview", source)
        self.assertIn("prepared_preview_model=prepared_preview_model", source)
        self.assertIn("PreparedModelPreviewData", package_source)
        self.assertNotIn("parse_mesh(", package_source)
        self.assertNotIn("build_archive_preview_result(", package_source)

    def test_old_renderer_terms_are_purged_from_tracked_sources(self) -> None:
        for root in ("cdmw", "native", "tests", "docs"):
            for path in Path(root).rglob("*"):
                if not path.is_file() or any(part in {"build", "target", "third_party", "__pycache__"} for part in path.parts):
                    continue
                if path.suffix.lower() not in {".py", ".md", ".txt", ".csv", ".rs", ".cpp", ".h", ".hpp", ".json", ".toml"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                old_renderer_token = "open" + "gl"
                self.assertNotIn(old_renderer_token, text.lower(), str(path))

    def test_native_d3d11_reload_keeps_previous_preview_until_loaded(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_loading.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_renderer_controls.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_d3d11_runtime.py").read_text(encoding="utf-8")
        )
        host_source = Path("cdmw/ui/native_d3d11_preview_host.py").read_text(encoding="utf-8")
        reload_start = source.index('def _start_archive_isolated_renderer_process(self, package_dir: Path)')
        reload_end = source.index('def _check_archive_isolated_renderer_start_timeout', reload_start)
        reload_source = source[reload_start:reload_end]

        self.assertIn("self._set_archive_d3d11_pending_package(", reload_source)
        self.assertIn("loading the next package while the current preview remains visible", reload_source)
        self.assertIn("next_model_key = self._d3d11_preview_package_model_key(package_dir)", reload_source)
        self.assertIn("same_d3d11_model", reload_source)
        self.assertIn("reset_view=not same_d3d11_model", reload_source)
        self.assertIn("archive_d3d11_has_view_state = False", reload_source)
        self.assertIn("_sanitize_d3d11_view_state_for_restore(self.archive_d3d11_view_state)", reload_source)
        self.assertNotIn("clear_preview(status_file)", reload_source)
        self.assertIn("_promote_archive_d3d11_pending_package_if_loaded(status_file)", source)
        self.assertIn("_discard_archive_d3d11_pending_package(status_file)", source)
        self.assertIn("keep_d3d11_visible", source)
        self.assertIn("_deactivate_archive_model_renderers_for_non_model_preview()", source)
        self.assertIn('quality_tier", "") or "").strip().lower() == "fast"', source)
        self.assertIn("SendMessageTimeoutW", host_source)
        self.assertIn("_kill_archive_isolated_renderer_process_if_running(process)", source)

    def test_native_d3d11_overlay_uses_view_specific_workspace_grid(self) -> None:
        native_source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("workspace_grid_y_for_view", native_source)
        grid_start = native_source.index("void draw_workspace_grid(")
        grid_body = native_source[grid_start: native_source.index("void draw_alignment_axes", grid_start)]
        self.assertIn("const float grid_y = workspace_grid_y_for_view(view);", grid_body)
        render_start = native_source.index("void draw_render_view")
        render_body = native_source[render_start: native_source.index("void draw_side_by_side_splitter_overlay", render_start)]
        self.assertIn('!(display_mode_ == "overlay" && view.role == PreviewViewRole::Reference)', render_body)
        self.assertIn("draw_workspace_grid(view, world_view_projection);", render_body)

    def test_model_preview_palette_is_theme_independent(self) -> None:
        constants_source = Path("cdmw/constants.py").read_text(encoding="utf-8")
        main_source = (
            Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_open.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_transform.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_b.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_preview_shell.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_d3d11_state.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/attachment_safe_placement_dialog.py").read_text(encoding="utf-8")
        )
        model_library_source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
        )
        native_source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('MODEL_PREVIEW_BACKGROUND_COLOR = "#15191d"', constants_source)
        self.assertIn('MODEL_PREVIEW_TEXT_COLOR = "#c8d3df"', constants_source)
        self.assertIn('MODEL_PREVIEW_GRID_COLOR = "#2f3740"', constants_source)

        for function_name in (
            "_archive_isolated_renderer_theme_payload",
            "_placement_d3d11_theme_payload",
        ):
            start = main_source.index(f"def {function_name}")
            body = main_source[start: main_source.index("\n\n", start)]
            self.assertIn('"background": MODEL_PREVIEW_BACKGROUND_COLOR', body)
            self.assertIn('"text": MODEL_PREVIEW_TEXT_COLOR', body)
            self.assertNotIn('theme["preview_bg"]', body)
            self.assertNotIn("get_theme(", body)

        self.assertIn(
            "theme_payload=_alignment_d3d11_theme_payload_helper(",
            main_source,
        )
        self.assertIn("MODEL_PREVIEW_BACKGROUND_COLOR,", main_source)
        self.assertIn("MODEL_PREVIEW_TEXT_COLOR,", main_source)
        helper_start = main_source.index("def alignment_d3d11_theme_payload")
        helper_body = main_source[helper_start: main_source.index("\n\n", helper_start)]
        self.assertIn('"background": str(background_color)', helper_body)
        self.assertIn('"text": str(text_color)', helper_body)
        self.assertNotIn('theme["preview_bg"]', helper_body)
        self.assertNotIn("get_theme(", helper_body)

        inline_start = model_library_source.index("def _inline_d3d11_theme_payload")
        inline_body = model_library_source[inline_start: model_library_source.index("\n\n", inline_start)]
        self.assertIn('"background": MODEL_PREVIEW_BACKGROUND_COLOR', inline_body)
        self.assertIn('"text": MODEL_PREVIEW_TEXT_COLOR', inline_body)
        self.assertNotIn("get_theme(", inline_body)

        self.assertIn("kFixedPreviewClearColor", native_source)
        self.assertIn("clear_color_ = kFixedPreviewClearColor;", native_source)
        pipeline_start = native_source.index("bool create_pipeline()")
        pipeline_body = native_source[pipeline_start: native_source.index("std::string shader_error;", pipeline_start)]
        self.assertNotIn("args_.theme_background", pipeline_body)
        self.assertIn('if (axis == "x") return DirectX::XMFLOAT3(1.0f, 0.05f, 0.03f);', native_source)
        self.assertIn('if (axis == "y") return DirectX::XMFLOAT3(0.0f, 1.0f, 0.24f);', native_source)
        self.assertIn("return DirectX::XMFLOAT3(0.0f, 0.50f, 1.0f);", native_source)
        self.assertIn("kOverlayPixelShaderSource", native_source)
        self.assertIn('compile_shader(overlay_shader_source, "ps_overlay", "ps_4_0"', native_source)
        self.assertIn("context_->PSSetShader(overlay_pixel_shader_.Get(), nullptr, 0);", native_source)
        self.assertIn("add_thick_line(segment.first, segment.second, active ? 11.0f : 9.2f, 0.92f, 0.96f, 1.0f)", native_source)
        self.assertIn("add_thick_line(segment.first, segment.second, active ? 6.4f : 5.4f, color.x, color.y, color.z)", native_source)
        self.assertIn("add_disc(segment.second, active ? 10.8f : 9.6f, color.x, color.y, color.z)", native_source)
        self.assertIn('add_axis_label(axis == "x" ? "X" : (axis == "y" ? "Y" : "Z")', native_source)
        self.assertIn("add_ring(origin, rotate_active ? 50.0f : 48.0f, rotate_active ? 8.6f : 7.0f, 0.92f, 0.96f, 1.0f)", native_source)
        self.assertIn("add_ring(origin, rotate_active ? 50.0f : 48.0f, rotate_active ? 5.2f : 4.2f, 1.0f, 0.72f, 0.05f)", native_source)
        self.assertIn("add_ring(origin, roll_active ? 76.0f : 74.0f, roll_active ? 5.2f : 4.2f, 1.0f, 0.18f, 1.0f)", native_source)
        self.assertIn("draw_colored_triangles(vertices, identity, true);", native_source)

    def test_native_d3d11_texture_integrity_and_diagnostics_are_reported(self) -> None:
        source = _archive_d3d11_runtime_source()
        native_source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("texture manifest empty despite", source)
        self.assertIn("Native D3D11 Texture Failures:", source)
        self.assertIn("texture_failures", native_source)
        self.assertIn("required_texture_failures", native_source)
        self.assertIn("texture_integrity", native_source)
        self.assertIn("failed_textures", native_source)
        self.assertIn("source_kind", native_source)
        self.assertIn("hresult_hex", native_source)
        self.assertIn("error_payload(\"native D3D11 package reload failed\"", native_source)
        self.assertIn("texture_cache_key(path, dds, create_flags)", native_source)
        self.assertIn("live_texture_bytes", native_source)
        self.assertIn("D3D11 preview loaded with texture integrity=", source)
        self.assertIn("Native D3D11 Texture Integrity:", source)
        self.assertIn("device_lost", native_source)
        self.assertIn("is_device_loss_hresult", native_source)
        self.assertIn("CDMW_D3D11_PREVIEW_FORCE_PRESENT_FAILURE", native_source)
        self.assertIn("CDMW_D3D11_PREVIEW_FORCE_RESIZE_FAILURE", native_source)
        self.assertIn('elif event == "device_lost":', source)


if __name__ == "__main__":
    unittest.main()
