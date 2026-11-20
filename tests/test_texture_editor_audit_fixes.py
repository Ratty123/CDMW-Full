"""Regressions from the Browse Archive and Texture Editor audit (2026-11-20)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
from PIL import Image

from cdmw.core.texture_editor_project_io import load_texture_editor_project, save_texture_editor_project
from cdmw.domain.textures.editor_brush import apply_texture_editor_stroke
from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers
from cdmw.domain.textures.editor_document import flip_texture_editor_document
from cdmw.domain.textures.editor_layers import (
    add_texture_editor_adjustment_layer,
    add_texture_editor_layer,
    update_texture_editor_adjustment_layer,
)
from cdmw.domain.textures.editor_selection import (
    apply_texture_editor_rect_selection,
    grow_texture_editor_selection,
    select_all_texture_editor,
    update_texture_editor_selection_settings,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding, TextureEditorToolSettings
from cdmw.services.texture_editor_service import TextureEditorService
from cdmw.ui.texture_workflow.job import TextureJob


def _hidden_colour_pixels():
    rng = np.random.default_rng(7)
    pixels = rng.integers(0, 256, (16, 16, 4), dtype=np.uint8)
    pixels[::2, :, 3] = 0
    pixels[1::4, ::3, 3] = 255
    return pixels


def test_flatten_keeps_colour_under_fully_transparent_pixels():
    pixels = _hidden_colour_pixels()
    document = TextureEditorDocument(title="t", width=16, height=16)
    document, layers, _layer = add_texture_editor_layer(document, {}, name="Base", initial_pixels=pixels)
    assert np.array_equal(flatten_texture_editor_layers(document, layers), pixels)


def test_open_and_save_png_round_trips_hidden_colour(tmp_path):
    pixels = _hidden_colour_pixels()
    source = tmp_path / "hidden.png"
    Image.fromarray(pixels, "RGBA").save(source)
    document, layers, _png = TextureEditorService.create_document_from_source(source, workspace_root=tmp_path / "ws")
    output = tmp_path / "out.png"
    TextureEditorService.export_flattened_png(document, layers, output)
    with Image.open(output) as saved:
        assert np.array_equal(np.asarray(saved.convert("RGBA")), pixels)


def test_empty_layer_above_keeps_hidden_colour_of_the_layer_below():
    pixels = _hidden_colour_pixels()
    document = TextureEditorDocument(title="t", width=16, height=16)
    document, layers, _base = add_texture_editor_layer(document, {}, name="Base", initial_pixels=pixels)
    document, layers, _top = add_texture_editor_layer(document, layers, name="Empty",
                                                      initial_pixels=np.zeros((16, 16, 4), np.uint8))
    assert np.array_equal(flatten_texture_editor_layers(document, layers), pixels)


def test_multiply_and_overlay_show_their_own_colour_over_transparency():
    document = TextureEditorDocument(title="t", width=4, height=4)
    base = np.zeros((4, 4, 4), np.uint8)
    base[:2] = (200, 200, 200, 255)
    document, layers, _base = add_texture_editor_layer(document, {}, name="Base", initial_pixels=base)
    top = np.zeros((4, 4, 4), np.uint8)
    top[...] = (255, 0, 0, 255)
    for mode, over_grey in (("multiply", (200, 0, 0, 255)), ("overlay", (255, 145, 145, 255)),
                            ("normal", (255, 0, 0, 255)), ("screen", (255, 200, 200, 255))):
        blended_document, blended_layers, _top = add_texture_editor_layer(
            document, layers, name="Top", initial_pixels=top, blend_mode=mode)
        result = flatten_texture_editor_layers(blended_document, blended_layers)
        assert tuple(result[0, 0]) == over_grey, mode
        assert tuple(result[3, 0]) == (255, 0, 0, 255), mode


def test_adjustment_layer_opacity_zero_survives_a_project_round_trip(tmp_path):
    document = TextureEditorDocument(title="t", width=8, height=8)
    base = np.full((8, 8, 4), 120, np.uint8)
    base[..., 3] = 255
    document, layers, _base = add_texture_editor_layer(document, {}, name="Base", initial_pixels=base)
    document = add_texture_editor_adjustment_layer(document, adjustment_type="brightness_contrast", name="BC",
                                                   parameters={"brightness": 80.0, "contrast": 0.0})
    document = update_texture_editor_adjustment_layer(document, document.adjustment_layers[0].layer_id, opacity=0)
    path = tmp_path / "p.ctfedit.json"
    save_texture_editor_project(document, layers, path)
    loaded, loaded_layers, _floating = load_texture_editor_project(path)
    assert loaded.adjustment_layers[0].opacity == 0
    assert np.array_equal(flatten_texture_editor_layers(loaded, loaded_layers),
                          flatten_texture_editor_layers(document, layers))


def _feathered_rect_document():
    document = TextureEditorDocument(title="t", width=200, height=120)
    document = update_texture_editor_selection_settings(document, feather_radius=8)
    return apply_texture_editor_rect_selection(document, (40, 30, 60, 60))


def _mask(document):
    return build_texture_editor_selection_mask(document.width, document.height, document.selection)


def test_selection_feather_is_applied_once():
    document = _feathered_rect_document()
    once = _mask(document)
    added = document
    for _ in range(5):
        added = apply_texture_editor_rect_selection(added, (180, 100, 5, 5), combine_mode="add")
    assert np.array_equal(_mask(added)[:, :150], once[:, :150])
    flipped, _layers = flip_texture_editor_document(document, {}, horizontal=False, vertical=True)
    assert np.array_equal(_mask(flipped), np.flip(once, axis=0))
    grown = grow_texture_editor_selection(document, 1)
    # Grow moves the edge by one pixel; it does not widen the soft edge.
    assert int(np.count_nonzero((_mask(grown)[60] > 0) & (_mask(grown)[60] < 255))) == \
        int(np.count_nonzero((once[60] > 0) & (once[60] < 255)))


def test_brush_strokes_work_on_a_layer_past_the_canvas_with_a_selection():
    for offset in ((10, 36), (50, 10), (-6, 10), (10, -8)):
        document = TextureEditorDocument(title="t", width=64, height=48)
        base = np.full((48, 64, 4), 90, np.uint8)
        base[..., 3] = 255
        document, layers, _base = add_texture_editor_layer(document, {}, name="Base", initial_pixels=base)
        document, layers, layer_id = add_texture_editor_layer(
            document, layers, name="L2", initial_pixels=np.full((24, 20, 4), 200, np.uint8),
            offset_x=offset[0], offset_y=offset[1])
        document = select_all_texture_editor(document)
        for tool in ("paint", "erase", "smudge", "dodge_burn", "soften", "sharpen"):
            points = [(offset[0] + 1, offset[1] + 1), (offset[0] + 18, offset[1] + 22)]
            apply_texture_editor_stroke(document, layers, TextureEditorToolSettings(tool=tool, size=10.0), points)
        painted = apply_texture_editor_stroke(
            document, layers, TextureEditorToolSettings(tool="paint", size=10.0),
            [(offset[0] + 2, offset[1] + 2), (offset[0] + 10, offset[1] + 10)])
        assert painted is not None


class _Session:
    def __init__(self, label, document):
        self.label = label
        self.document = document


def test_project_over_its_open_source_texture_gets_its_own_row():
    binding = TextureEditorSourceBinding(source_path="/textures/a.png", source_identity_path="/textures/a.png")
    job = TextureJob()
    texture = _Session("a", TextureEditorDocument(title="a", width=4, height=4, source_binding=binding))
    job.sessions = [texture]
    job.synchronize_sessions(0)
    project = _Session("a", TextureEditorDocument(title="a", width=4, height=4, source_binding=binding,
                                                  project_path=Path("/projects/a.cdmwtex")))
    job.sessions = [texture, project]
    job.synchronize_sessions(1)
    assert len(job.assets) == 2
    assert {asset.session for asset in job.assets.values()} == {texture, project}
    labels = sorted(asset.label for asset in job.assets.values())
    assert labels == ["a", "a (a.cdmwtex)"]
    # Reopening after the texture closed reuses its free row.
    job.sessions = [project]
    job.synchronize_sessions(0)
    assert sum(asset.session is not None for asset in job.assets.values()) == 1


def test_layer_commands_refresh_the_canvas_composite(tmp_path):
    import time

    from PySide6.QtWidgets import QApplication

    from cdmw.services.settings_service import create_settings
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    app = QApplication.instance() or QApplication([])

    def pump(seconds=0.2):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.002)

    editor = TextureEditorTab(settings=create_settings(settings_file_path=tmp_path / "s.cfg"),
                              base_dir=tmp_path, get_png_root=lambda: str(tmp_path))
    rng = np.random.default_rng(5)
    try:
        for command in (editor.copy_selection_to_new_layer, editor.extract_active_channel_to_new_layer):
            document = TextureEditorDocument(title="t", width=64, height=48)
            base = rng.integers(0, 256, (48, 64, 4), dtype=np.uint8)
            base[..., 3] = 255
            document, layers, _base = add_texture_editor_layer(document, {}, name="Base", initial_pixels=base)
            editor._create_session(document, layers, label="t")
            editor._push_history("Open")
            pump()
            editor.canvas.selection_committed.emit({"mode": "rect", "rect": (10, 8, 30, 20)})
            pump()
            editor._current_composite_rgba()
            command()
            pump()
            assert np.array_equal(editor._current_composite_rgba(),
                                  flatten_texture_editor_layers(editor.document, editor.layer_pixels)), command
    finally:
        editor.request_shutdown()
        editor.deleteLater()
        pump()
