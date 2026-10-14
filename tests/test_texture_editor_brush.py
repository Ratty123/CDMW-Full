from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from cdmw.domain.textures.editor_brush import _interpolate_stroke, apply_texture_editor_stroke
from cdmw.domain.textures.editor_selection import apply_texture_editor_selection_stroke
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import (
    TextureEditorDocument,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorToolSettings,
)


def _document() -> TextureEditorDocument:
    layer = TextureEditorLayer("paint", "Paint", "unused.png")
    return TextureEditorDocument("Brush", 128, 64, active_layer_id="paint", layers=(layer,))


def _settings(**overrides: object) -> TextureEditorToolSettings:
    settings = TextureEditorToolSettings(
        size=20, hardness=100, opacity=25, flow=100, spacing=50, color_hex="#FFFFFF",
    )
    return replace(settings, **overrides)


@pytest.mark.parametrize("tool", ["paint", "erase", "clone", "heal", "smudge", "dodge_burn", "soften", "sharpen"])
@pytest.mark.parametrize("diagonal", [False, True])
def test_same_path_has_same_pixels_regardless_of_mouse_sampling(tool: str, diagonal: bool) -> None:
    document = _document()
    pixels = np.random.default_rng(42).integers(0, 256, (64, 128, 4), dtype=np.uint8)
    points = [(16 + offset, 12 + offset if diagonal else 32) for offset in range(37)]
    settings = _settings(tool=tool, clone_source_point=(16, 8))

    sparse = apply_texture_editor_stroke(
        document, {"paint": pixels}, settings, [points[0], points[-1]], source_snapshot=pixels,
    )["paint"]
    dense = apply_texture_editor_stroke(
        document, {"paint": pixels}, settings, points, source_snapshot=pixels,
    )["paint"]

    np.testing.assert_array_equal(sparse, dense)


def test_spacing_carries_across_corners_and_keeps_the_endpoint() -> None:
    assert _interpolate_stroke([(0, 0), (3, 0), (3, 10)], 5) == [
        (0, 0), (3, 2), (3, 7), (3, 10),
    ]


@pytest.mark.parametrize("points", [[], [(4, 4)], [(4, 4), (4, 4), (4, 4)]])
def test_empty_strokes_and_stationary_clicks(points: list[tuple[int, int]]) -> None:
    assert _interpolate_stroke(points, 5) == ([(4, 4)] if points else [])


@pytest.mark.parametrize("tool", ["paint", "erase"])
def test_quick_mask_strokes_are_independent_of_mouse_sampling(tool: str) -> None:
    document = _document()
    if tool == "erase":
        document = replace(document, selection=TextureEditorSelection(mode="rect", rect=(0, 0, 128, 64)))
    settings = _settings(tool=tool, hardness=60)
    points = [(x, 32) for x in range(16, 113)]

    sparse = apply_texture_editor_selection_stroke(document, settings, [points[0], points[-1]])
    dense = apply_texture_editor_selection_stroke(document, settings, points)

    np.testing.assert_array_equal(
        build_texture_editor_selection_mask(128, 64, sparse.selection),
        build_texture_editor_selection_mask(128, 64, dense.selection),
    )


@pytest.mark.parametrize("opacity, flow", [(100, 1), (100, 2), (100, 4), (100, 100), (25, 3)])
@pytest.mark.parametrize("quick_mask", [False, True])
def test_low_flow_and_fractional_stamp_strength_are_honoured(opacity: int, flow: int, quick_mask: bool) -> None:
    document = _document()
    settings = _settings(opacity=opacity, flow=flow)
    if quick_mask:
        updated = apply_texture_editor_selection_stroke(document, settings, [(32, 32)])
        alpha = build_texture_editor_selection_mask(128, 64, updated.selection)
        assert alpha is not None
    else:
        pixels = np.zeros((64, 128, 4), dtype=np.uint8)
        alpha = apply_texture_editor_stroke(document, {"paint": pixels}, settings, [(32, 32)])["paint"][..., 3]

    assert int(alpha[32, 32]) == round(255 * (opacity / 100) * (flow / 100))


@pytest.mark.parametrize("tool", ["paint", "erase"])
def test_strokes_preserve_selection_channel_and_layer_locks(tool: str) -> None:
    document = replace(
        _document(),
        selection=TextureEditorSelection(mode="rect", rect=(24, 20, 40, 24)),
        edit_red_channel=False,
        edit_alpha_channel=False,
    )
    pixels = np.full((64, 128, 4), 90, dtype=np.uint8)
    before = pixels.copy()
    points = [(16, 32), (112, 32)]
    updated = apply_texture_editor_stroke(document, {"paint": pixels}, _settings(tool=tool), points)["paint"]
    selected = build_texture_editor_selection_mask(128, 64, document.selection) > 0

    np.testing.assert_array_equal(updated[~selected], before[~selected])
    np.testing.assert_array_equal(updated[..., [0, 3]], before[..., [0, 3]])
    np.testing.assert_array_equal(pixels, before)
    locked = replace(document, layers=(replace(document.layers[0], locked=True),))
    np.testing.assert_array_equal(
        apply_texture_editor_stroke(locked, {"paint": pixels}, _settings(tool=tool), points)["paint"], before,
    )


@pytest.mark.parametrize("tool", ["paint", "erase"])
@pytest.mark.parametrize("mask_target", [False, True])
def test_editor_strokes_round_trip_through_undo_and_redo(tool: str, mask_target: bool) -> None:
    from cdmw.ui.texture_workflow.editor_history_state import (
        build_texture_editor_delta_history_record,
        texture_editor_history_record_application_state,
    )
    from cdmw.ui.texture_workflow.editor_tool_state import texture_editor_layer_stroke_state

    document = _document()
    layer_id = "mask" if mask_target else "paint"
    if mask_target:
        document = replace(document, layers=(
            replace(document.layers[0], mask_layer_id="mask"),
            TextureEditorLayer("mask", "Mask", "unused.png"),
        ))
    pixels = {layer.layer_id: np.full((64, 128, 4), 90, dtype=np.uint8) for layer in document.layers}
    before = {key: value.copy() for key, value in pixels.items()}
    state = texture_editor_layer_stroke_state(
        document, pixels, _settings(tool=tool), [(16, 32), (48, 32)],
        layer_id=layer_id, editing_mask_target=mask_target, selection_bounds=None,
        layer_canvas_bounds=(0, 0, 128, 64), brush_dirty_bounds=(4, 20, 56, 24),
    )
    assert state is not None
    after = {key: value.copy() for key, value in state.layer_pixels.items()}
    assert not np.array_equal(after[layer_id], before[layer_id])
    record = build_texture_editor_delta_history_record(
        label=state.history_label, before_document=document, after_document=state.document,
        before_layer_pixels=state.before_layer_pixels, after_layer_pixels=state.layer_pixels,
        kind=state.kind, timestamp=0.0, dirty_bounds=state.dirty_bounds, tracked_layer_ids=state.tracked_layer_ids,
    )
    undone = texture_editor_history_record_application_state(record, direction="before", current_layer_pixels=state.layer_pixels)
    redone = texture_editor_history_record_application_state(record, direction="after", current_layer_pixels=undone.layer_pixels)
    for key in before:
        np.testing.assert_array_equal(undone.layer_pixels[key], before[key])
        np.testing.assert_array_equal(redone.layer_pixels[key], after[key])


def test_editor_stroke_history_updates_visible_undo_redo_controls(tmp_path) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    app = QApplication.instance() or QApplication([])
    editor = TextureEditorTab(
        settings=create_settings(settings_file_path=tmp_path / "settings.cfg"),
        base_dir=tmp_path, get_png_root=lambda: str(tmp_path),
    )
    try:
        editor.document = _document()
        editor.layer_pixels = {"paint": np.full((64, 128, 4), 90, dtype=np.uint8)}
        editor.current_tool_settings = _settings(tool="paint")
        editor._push_history("Open Document")
        editor._refresh_ui()
        before = editor.layer_pixels["paint"].copy()
        editor._handle_canvas_stroke({"tool": "paint", "points": [(16, 32), (48, 32)]})
        after = editor.layer_pixels["paint"].copy()
        assert not np.array_equal(before, after)
        assert editor.undo_button.isEnabled()
        assert not editor.redo_button.isEnabled()
        editor.undo_button.click()
        np.testing.assert_array_equal(editor.layer_pixels["paint"], before)
        assert not editor.undo_button.isEnabled()
        assert editor.redo_button.isEnabled()
        editor.redo_button.click()
        np.testing.assert_array_equal(editor.layer_pixels["paint"], after)
        assert editor.undo_button.isEnabled()
        assert not editor.redo_button.isEnabled()
    finally:
        editor.request_shutdown()
        editor.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
