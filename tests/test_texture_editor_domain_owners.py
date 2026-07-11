from __future__ import annotations

import numpy as np

from cdmw.core import texture_editor
from cdmw.core import texture_editor_layer_ops, texture_editor_raster_ops
from cdmw.domain.textures import editor_brush, editor_composite, editor_layers
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorToolSettings
from cdmw.services.texture_editor_service import TextureEditorService
from cdmw.core import texture_editor_project_io


def test_texture_editor_core_facades_preserve_domain_owner_identity() -> None:
    assert texture_editor.apply_texture_editor_stroke is editor_brush.apply_texture_editor_stroke
    assert texture_editor_raster_ops.flatten_texture_editor_layers is editor_composite.flatten_texture_editor_layers
    assert texture_editor_layer_ops.add_texture_editor_layer is editor_layers.add_texture_editor_layer
    assert texture_editor.add_texture_editor_layer is editor_layers.add_texture_editor_layer
    assert TextureEditorService.load_project is texture_editor_project_io.load_texture_editor_project
    assert TextureEditorService.save_project is texture_editor_project_io.save_texture_editor_project
    assert TextureEditorService.export_flattened_png is texture_editor_raster_ops.export_texture_editor_flattened_png


def test_domain_brush_paint_is_pixel_exact() -> None:
    document = TextureEditorDocument(
        "Paint",
        3,
        3,
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    pixels = np.zeros((3, 3, 4), dtype=np.uint8)
    settings = TextureEditorToolSettings(
        tool="paint",
        color_hex="#FF0000",
        size=1,
        hardness=100,
        opacity=100,
        flow=100,
        spacing=100,
    )

    result = editor_brush.apply_texture_editor_stroke(document, {"base": pixels}, settings, [(1, 1)])

    expected = np.zeros((3, 3, 4), dtype=np.uint8)
    expected[1, 1] = [255, 0, 0, 255]
    np.testing.assert_array_equal(result["base"], expected)
    np.testing.assert_array_equal(pixels, np.zeros_like(pixels))
