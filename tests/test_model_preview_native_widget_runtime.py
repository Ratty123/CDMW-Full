from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QUrl

from tests.native_source_text import d3d11_preview_source

from cdmw.models import (
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayData,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.rendering.material_combiner import (
    MaterialPreviewCombinerSettings,
    _decode_mode_for_input,
    combine_preview_material,
    decode_material_sample,
)
from cdmw.rendering.native_preview_package import (
    _input_texture_kind,
    _skeleton_overlay_metadata,
    build_native_preview_payloads,
    write_isolated_d3d11_preview_package,
)
from cdmw.ui.model_preview_native import (
    ARCHIVE_MODEL_RENDERER_D3D11,
    ARCHIVE_MODEL_RENDERER_DEFAULT,
    normalize_archive_model_renderer_backend,
)
from cdmw.ui.widgets import NativePreviewPanel


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


class NativePreviewWidgetRuntimeTests(unittest.TestCase):
    def test_native_preview_panel_keeps_alignment_view_state_api(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        widget.resize(120, 90)
        widget.show()
        app.processEvents()
        widget.set_view(yaw=12.0, pitch=-8.0, zoom_factor=2.0, fit_to_view=False, pan=(1.0, 2.0, 3.0))

        state = widget.view_state_snapshot()
        self.assertEqual((12.0, -8.0, False, 2.0), state[:4])
        self.assertEqual((1.0, 2.0, 3.0), state[5])
        widget.reset_view()
        widget.restore_view_state(state)
        self.assertEqual(state, widget.view_state_snapshot())
        self.assertFalse(widget.grab().isNull())

        widget.close()
        widget.deleteLater()
        app.processEvents()

    def test_native_preview_panel_selection_fallback_emits_compact_ranges(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        payloads: list[dict[str, object]] = []
        widget.mesh_edit_selection_changed.connect(lambda payload: payloads.append(dict(payload)))
        try:
            widget.set_mesh_edit_vertex_selection({2: [3, 5, 4, 3, -1]})
            group = payloads[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual(2, group["source_submesh_index"])
            self.assertEqual(3, group["source_vertex_start"])
            self.assertEqual(3, group["source_vertex_count"])
            self.assertNotIn("source_vertex_indices", group)
            self.assertEqual(3, payloads[-1]["selected_vertex_count"])

            widget.set_mesh_edit_vertex_selection({2: [5, 1, 5, -1]})
            group = payloads[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual([1, 5], group["source_vertex_indices"])
            self.assertNotIn("source_vertex_start", group)
            self.assertEqual(2, payloads[-1]["selected_vertex_count"])
        finally:
            widget.close()
            widget.deleteLater()
            app.processEvents()

    def test_repeated_payload_replacement_does_not_delete_live_geometry(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        model = ModelPreviewData(
            path="test.pam",
            summary="test model",
            meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
        )
        prepared = PreparedModelPreviewData(
            batches=(
                PreparedModelPreviewBatch(
                    vertex_blob=b"".join(
                        (
                            _vertex(0.0, 1.0, 0.0),
                            _vertex(-1.0, -1.0, 0.0),
                            _vertex(1.0, -1.0, 0.0),
                        )
                    ),
                    index_count=3,
                    has_texture_coordinates=True,
                ),
            )
        )

        for _attempt in range(3):
            widget.set_prepared_model(model, prepared)
            app.processEvents()
            widget.clear_model("reload")
            app.processEvents()
        widget.set_prepared_model(model, prepared)
        app.processEvents()

        self.assertTrue(widget.is_available(), widget.failure_reason())
        self.assertIn("1 batch", widget.debug_details_text())
        self.assertEqual(getattr(widget, "_vertex_count", 0), 3)
        widget.close()
        widget.deleteLater()
        app.processEvents()

    def test_textured_batches_use_white_material_color_and_disable_support_pbr_by_default(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "base.png"
            texture_image = QImage(2, 2, QImage.Format_RGBA8888)
            texture_image.setPixelColor(0, 0, QColor(255, 0, 0, 12))
            texture_image.setPixelColor(1, 0, QColor(255, 0, 0, 12))
            texture_image.setPixelColor(0, 1, QColor(0, 0, 255, 48))
            texture_image.setPixelColor(1, 1, QColor(0, 0, 255, 48))
            self.assertTrue(texture_image.save(str(texture_path), "PNG"))
            normal_path = Path(temp_dir) / "normal.png"
            normal_path.write_bytes(b"existing normal")
            widget = NativePreviewPanel("test", theme_key="dark")
            model = ModelPreviewData(
                path="test.pam",
                summary="test model",
                meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
            )
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join(
                            (
                                _vertex(0.0, 1.0, 0.0),
                                _vertex(-1.0, -1.0, 0.0),
                                _vertex(1.0, -1.0, 0.0),
                            )
                        ),
                        index_count=3,
                        preview_texture_path=str(texture_path),
                        preview_normal_texture_path=str(normal_path),
                        has_texture_coordinates=True,
                    ),
                )
            )

            widget.set_prepared_model(model, prepared)
            widget.set_use_textures(True)
            app.processEvents()

            details = widget.debug_details_text()
            self.assertIn(".NET/Vortice preview data ready", details)
            payload = build_native_preview_payloads(prepared)[0]
            self.assertFalse(payload.texture_flip_vertical)
            prepared_path = Path(QUrl(payload.texture_source).toLocalFile())
            self.assertTrue(prepared_path.is_file())
            prepared_image = QImage(str(prepared_path))
            self.assertFalse(prepared_image.isNull())
            self.assertEqual(12, prepared_image.pixelColor(0, 0).alpha())
            widget.close()
            widget.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
