from __future__ import annotations

from pathlib import Path
import unittest


class ArchiveQtQuick3DRendererSourceGuardTests(unittest.TestCase):
    def test_embedded_qtquick3d_renderer_option_is_removed(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("ARCHIVE_MODEL_RENDERER_LEGACY_OPENGL", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertIn("ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertNotIn("archive_model_preview_renderer_combo", source)
        self.assertNotIn("ARCHIVE_MODEL_RENDERER_QTQUICK3D", source)
        self.assertIn('"preview/archive_renderer_backend"', source)
        self.assertIn("self.archive_model_preview = ModelPreviewWidget", source)
        self.assertNotIn("self.archive_model_preview_qtquick3d", source)

    def test_legacy_opengl_remains_available_under_settings(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        dialog_source = Path("cdmw/ui/model_preview_settings_dialog.py").read_text(encoding="utf-8")

        self.assertIn("def _selected_archive_model_preview_widget", source)
        self.assertIn("return self.archive_model_preview", source)
        self.assertIn("Legacy OpenGL", dialog_source)
        self.assertIn("Native D3D11", dialog_source)
        self.assertIn("archive_renderer_backend_changed", dialog_source)
        self.assertNotIn("Renderer fallback:", source)

    def test_archive_preview_still_uses_existing_prepared_model_pipeline(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        package_source = Path("cdmw/rendering/qtquick3d_preview_package.py").read_text(encoding="utf-8")

        self.assertIn("ModelPreviewWidget.prepare_model_preview", source)
        self.assertIn("prepared_preview_model=prepared_preview_model", source)
        self.assertIn("PreparedModelPreviewData", package_source)
        self.assertNotIn("parse_mesh(", package_source)
        self.assertNotIn("build_archive_preview_result(", package_source)


if __name__ == "__main__":
    unittest.main()
