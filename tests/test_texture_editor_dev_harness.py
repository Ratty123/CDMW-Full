from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from cdmw.services.texture_editor_service import TextureEditorNativeDdsResult
from tools.texture_editor_dev_harness import build_synthetic_document, run_scenario


class TextureEditorDevHarnessTests(unittest.TestCase):
    def test_preset_matrix_writes_result_json_without_starting_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("preset-matrix", output_dir)

            self.assertTrue(result["ok"])
            self.assertEqual("preset-matrix", result["scenario"])
            self.assertTrue((output_dir / "result.json").is_file())
            self.assertGreaterEqual(len(result["presets"]), 6)

    def test_full_suite_uses_service_and_writes_only_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            def fake_export(_self, _document, _layer_pixels, options):
                dds_path = Path(options.output_path)
                dds_path.parent.mkdir(parents=True, exist_ok=True)
                dds_path.write_bytes(b"DDS fake")
                return TextureEditorNativeDdsResult(
                    dds_path=dds_path,
                    report={"status": "encoded", "native_backend": "directxtex", "format": "BC7_UNORM"},
                )

            def fake_preview(_self, _document, _layer_pixels, options):
                dds_path = Path(options.output_path)
                preview_path = Path(options.preview_output_path or dds_path.with_suffix(".png"))
                dds_path.parent.mkdir(parents=True, exist_ok=True)
                preview_path.parent.mkdir(parents=True, exist_ok=True)
                dds_path.write_bytes(b"DDS fake")
                Image.fromarray(np.full((8, 8, 4), 255, dtype=np.uint8), "RGBA").save(preview_path)
                return TextureEditorNativeDdsResult(
                    dds_path=dds_path,
                    report={"status": "encoded", "native_backend": "directxtex", "format": "BC7_UNORM"},
                    preview_path=preview_path,
                    preview_report={"status": "decoded", "native_backend": "directxtex"},
                    preview_rgba=np.full((8, 8, 4), 255, dtype=np.uint8),
                )

            with (
                patch("cdmw.services.texture_editor_service.TextureEditorNativeDdsService.export_dds", fake_export),
                patch("cdmw.services.texture_editor_service.TextureEditorNativeDdsService.preview_compressed", fake_preview),
            ):
                result = run_scenario("full-suite-smoke", output_dir)

            self.assertTrue(result["ok"])
            self.assertTrue((output_dir / "native-dds-export" / "harness_texture.dds").is_file())
            self.assertTrue((output_dir / "compression-preview" / "harness_texture_preview.png").is_file())
            for path in output_dir.rglob("*"):
                self.assertTrue(path.resolve().is_relative_to(output_dir.resolve()))

    def test_harness_source_does_not_import_qt_or_main_window(self) -> None:
        source = Path("tools/texture_editor_dev_harness.py").read_text(encoding="utf-8")

        self.assertNotIn("MainWindow", source)
        self.assertNotIn("QApplication", source)
        self.assertNotIn("PySide6", source)

    def test_ui_wires_native_dds_export_through_task_service_not_core_native(self) -> None:
        ui_source = (
            Path("cdmw/ui/texture_editor_tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/texture_workflow/editor_file_io_ui.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/texture_workflow/editor_ui_shell.py").read_text(encoding="utf-8")
        )
        task_source = Path("cdmw/ui/texture_workflow/editor_export_tasks.py").read_text(encoding="utf-8")

        self.assertIn("export_texture_editor_native_dds_task", ui_source)
        self.assertIn("preview_texture_editor_native_dds_task", ui_source)
        self.assertIn("native_dds_ready = Signal(str, object)", ui_source)
        self.assertGreaterEqual(ui_source.count("native_dds_ready.emit"), 2)
        self.assertIn("_run_async_task(", ui_source)
        self.assertIn("TextureEditorNativeDdsService().export_dds", task_source)
        self.assertIn("TextureEditorNativeDdsService().preview_compressed", task_source)
        self.assertNotIn("from cdmw.core import texture_native", ui_source)
        self.assertNotIn("from cdmw.core.texture_native", ui_source)
        self.assertNotIn("encode_dds_with_directxtex", ui_source)

    def test_synthetic_document_has_layers_without_ui(self) -> None:
        document, pixels = build_synthetic_document()

        self.assertEqual("harness_texture", document.title)
        self.assertEqual(2, len(document.layers))
        self.assertEqual((8, 8, 4), pixels["base"].shape)


if __name__ == "__main__":
    unittest.main()
