from __future__ import annotations

from pathlib import Path
import unittest


class ArchiveD3D11RendererSourceGuardTests(unittest.TestCase):
    def test_embedded_d3d11_renderer_option_is_removed(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_" + "LEGACY", source)
        self.assertNotIn("archive_model_preview_renderer_combo", source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_" + "QT" + "QUICK3D", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertIn("self.archive_model_preview = NativePreviewPanel", source)
        self.assertNotIn("self.archive_model_preview_" + "qt" + "quick" + "3d", source)

    def test_d3d11_only_remains_available_under_settings(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")

        self.assertIn("def _selected_archive_model_preview_widget", source)
        self.assertIn("return self.archive_model_preview", source)
        self.assertNotIn("ARCHIVE_RENDERER_" + "LEGACY", dialog_source)
        self.assertIn("Native D3D11", dialog_source)
        self.assertIn("archive_renderer_backend_changed", dialog_source)
        self.assertNotIn("Renderer backend", dialog_source)
        self.assertNotIn("Renderer " + "fallback:", source)

    def test_archive_preview_still_uses_existing_prepared_model_pipeline(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        package_source = Path("cdmw/rendering/native_preview_package.py").read_text(encoding="utf-8")

        self.assertIn("from cdmw.rendering.model_preview_prepare import prepare_model_preview", source)
        self.assertIn("prepare_model_preview(", source)
        self.assertNotIn("NativePreviewPanel.prepare_model_preview", source)
        self.assertIn("prepared_preview_model=prepared_preview_model", source)
        self.assertIn("PreparedModelPreviewData", package_source)
        self.assertNotIn("parse_mesh(", package_source)
        self.assertNotIn("build_archive_preview_result(", package_source)

    def test_old_renderer_terms_are_purged_from_tracked_sources(self) -> None:
        for root in ("cdmw", "native", "tests", "docs"):
            for path in Path(root).rglob("*"):
                if not path.is_file() or any(part in {"target", "__pycache__"} for part in path.parts):
                    continue
                if path.suffix.lower() not in {".py", ".md", ".txt", ".csv", ".rs", ".cpp", ".h", ".hpp", ".json", ".toml"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                old_renderer_token = "open" + "gl"
                self.assertNotIn(old_renderer_token, text.lower(), str(path))

    def test_native_d3d11_reload_keeps_previous_preview_until_loaded(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
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
        self.assertIn("SendMessageTimeoutW", source)
        self.assertIn("_kill_archive_isolated_renderer_process_if_running(process)", source)

    def test_native_d3d11_texture_integrity_and_diagnostics_are_reported(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        native_source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("texture manifest empty despite", source)
        self.assertIn("Native D3D11 Texture Failures:", source)
        self.assertIn("texture_failures", native_source)
        self.assertIn("failed_textures", native_source)
        self.assertIn("hresult_hex", native_source)
        self.assertIn("error_payload(\"native D3D11 package reload failed\"", native_source)
        self.assertIn("texture_cache_key(path, dds, create_flags)", native_source)
        self.assertIn("live_texture_bytes", native_source)


if __name__ == "__main__":
    unittest.main()
