from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class ArchiveVorticeRendererSourceGuardTests(unittest.TestCase):
    def test_archive_model_surface_uses_resident_vortice_host_only(self) -> None:
        source = _read("cdmw/ui/archive_browser/preview_layout.py")

        self.assertIn("DotNetPreviewHostFrame(", source)
        self.assertIn("profile=DotNetPreviewProfile.PREVIEW", source)
        self.assertIn('setObjectName("DotNetVorticePreviewHost")', source)
        self.assertIn("self.archive_model_preview.setVisible(False)", source)
        self.assertNotIn("self.archive_preview_stack.addWidget(self.archive_model_preview)", source)

    def test_archive_result_consumes_only_canonical_dotnet_package(self) -> None:
        source = _read("cdmw/ui/archive_browser/preview_result.py")

        self.assertIn('getattr(result, "dotnet_preview_package_path"', source)
        self.assertIn("validate_dotnet_preview_package(package_dir)", source)
        self.assertIn("self.archive_d3d11_preview_host.load_package(", source)
        self.assertIn('set_viewport_display_mode("untextured_wire")', source)
        self.assertIn("_preserve_archive_resident_scene_error", source)
        self.assertNotIn("self.archive_d3d11_preview_host.clear_preview()", source)
        self.assertIn("The legacy renderer is not used as a fallback.", source)
        self.assertNotIn('getattr(result, "native_preview_package_path"', source)

    def test_shared_archive_lifecycle_never_starts_a_process(self) -> None:
        source = _read("cdmw/ui/archive_browser/preview_dotnet_lifecycle.py")

        self.assertIn("class ArchivePreviewDotNetLifecycleMixin", source)
        self.assertIn("controller.shutdown()", source)
        self.assertIn("controller.clear_preview()", source)
        self.assertNotIn("QProcess", source)
        self.assertNotIn(".start(", source)
        self.assertNotIn("WM_COPYDATA", source)

    def test_texture_action_accepts_direct_native_packages_without_python_model(self) -> None:
        source = _read("cdmw/ui/archive_browser/action_controls.py")

        self.assertIn("resident_texture_action_available", source)
        self.assertIn('getattr(current_result, "dotnet_preview_package_path", "")', source)
        self.assertNotIn(
            "d3d11_backend_active and can_export_preview and controls_enabled",
            source,
        )

        lifecycle = _read("cdmw/ui/archive_browser/preview_dotnet_lifecycle.py")
        self.assertIn('button.setText("Hide Textures")', lifecycle)
        self.assertIn('button.setText("Load Textures")', lifecycle)
        self.assertGreaterEqual(lifecycle.count("button.setEnabled(True)"), 2)

    def test_settings_keep_legacy_keys_but_name_the_single_renderer(self) -> None:
        dialog = _read("cdmw/ui/model_preview_settings_dialog.py")
        labels = _read("cdmw/ui/model_preview_native.py")

        self.assertIn('ARCHIVE_RENDERER_D3D11 = "d3d11_native"', dialog)
        self.assertIn('addItem(".NET/Vortice Preview", self.ARCHIVE_RENDERER_D3D11)', dialog)
        self.assertIn(".NET/Vortice is the only Archive Browser model-preview path.", dialog)
        self.assertIn('ARCHIVE_MODEL_RENDERER_D3D11: ".NET/Vortice Preview"', labels)
        self.assertNotIn("Native D3D11", dialog)

    def test_canonical_package_worker_does_not_invoke_legacy_writer(self) -> None:
        worker = _read("cdmw/workers/d3d11_package_workers.py")

        self.assertIn("build_or_lookup_dotnet_preview_package_from_model", worker)
        self.assertNotIn("write_isolated_d3d11_preview_package", worker)

    def test_non_model_preview_routes_remain_unchanged(self) -> None:
        source = _read("cdmw/ui/archive_browser/preview_result.py")

        self.assertIn('if preferred_view == "image"', source)
        self.assertIn('if preferred_view == "media"', source)
        self.assertIn('if preferred_view == "text"', source)
        self.assertIn("self.archive_media_preview.set_media(", source)
        self.assertIn("self.archive_preview_text_edit.setPlainText(preview_text)", source)


if __name__ == "__main__":
    unittest.main()
