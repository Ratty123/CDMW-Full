from __future__ import annotations

import dataclasses
import math
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers_region
from cdmw.models import (
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorLayer,
    TextureEditorToolSettings,
)
from cdmw.ui.texture_editor_tab import TextureEditorTab
from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas
from cdmw.ui.texture_workflow.editor_export_tasks import (
    load_texture_editor_project_task,
    save_texture_editor_project_task,
)
from cdmw.ui.texture_workflow.editor_floating_state import estimated_texture_editor_brush_dirty_bounds
from cdmw.ui.texture_workflow.editor_history_state import (
    TextureEditorHistoryLayerPatch,
    build_texture_editor_checkpoint_record,
    build_texture_editor_delta_history_record,
    decode_texture_editor_rgba_blob,
    encode_texture_editor_rgba_blob,
    texture_editor_history_record_application_state,
    texture_editor_history_replay_plan,
    texture_editor_history_should_checkpoint,
    texture_editor_history_with_appended_record,
)
from cdmw.ui.texture_workflow import editor_history_state
from cdmw.ui.texture_workflow.editor_tool_state import texture_editor_layer_stroke_state


_FRAME_BUDGET_MS = 1000.0 / 60.0


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))]


def _replay(history: list[dict[str, object]], index: int):
    pixels: dict[str, np.ndarray] = {}
    state = None
    for replay_index in texture_editor_history_replay_plan(history, index).apply_indices:
        state = texture_editor_history_record_application_state(
            history[replay_index],
            direction="after",
            current_layer_pixels=pixels,
            copy_patch_pixels=False,
        )
        pixels = state.layer_pixels
    assert state is not None
    return state


def test_normal_layer_dirty_region_preserves_transparent_alpha_semantics() -> None:
    document = TextureEditorDocument(
        "composite",
        3,
        1,
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    pixels = np.array(
        [[[90, 80, 70, 0], [10, 20, 30, 128], [40, 50, 60, 255]]],
        dtype=np.uint8,
    )

    result = flatten_texture_editor_layers_region(document, {"paint": pixels}, (0, 0, 3, 1))

    np.testing.assert_array_equal(
        result,
        np.array([[[0, 0, 0, 0], [10, 20, 30, 128], [40, 50, 60, 255]]], dtype=np.uint8),
    )


def test_history_uses_lz4_without_png_encoding() -> None:
    small = np.arange(4 * 8 * 8, dtype=np.uint8).reshape((8, 8, 4))
    large = np.zeros((512, 512, 4), dtype=np.uint8)
    large[400, 300] = [9, 8, 7, 6]

    with patch(
        "cdmw.ui.texture_workflow.editor_history_state.cv2.imencode",
        side_effect=AssertionError("PNG history encode"),
    ):
        small_blob = encode_texture_editor_rgba_blob(small)
        large_blob = encode_texture_editor_rgba_blob(large)
        restored_small = decode_texture_editor_rgba_blob(small_blob)
        restored_large = decode_texture_editor_rgba_blob(large_blob)

    assert isinstance(small_blob, bytes)
    assert small_blob.startswith(b"CDMWLZ4\0")
    np.testing.assert_array_equal(restored_small, small)
    np.testing.assert_array_equal(restored_large, large)


def test_history_encoder_shutdown_is_owned_and_pending_pixels_remain_exact() -> None:
    pixels = np.zeros((512, 512, 4), dtype=np.uint8)
    pixels[20, 30] = [1, 2, 3, 4]
    blob = encode_texture_editor_rgba_blob(pixels)
    assert editor_history_state._RGBA_ENCODER is not None

    editor_history_state.shutdown_texture_editor_history_encoder()

    assert editor_history_state._RGBA_ENCODER is None
    np.testing.assert_array_equal(decode_texture_editor_rgba_blob(blob), pixels)


def test_history_eviction_and_branching_preserve_exact_pixels() -> None:
    document = TextureEditorDocument(
        "doc",
        4,
        4,
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    pixels = np.arange(64, dtype=np.uint8).reshape((4, 4, 4))
    layer_pixels = {"base": pixels.copy()}
    history = [build_texture_editor_checkpoint_record(document, layer_pixels, "Base", timestamp=0.0)]
    history_index = 0
    expected_by_label = {"Base": (document, pixels.copy())}
    saw_eviction = False

    for edit_index in range(1, 126):
        before_document = document
        before_pixels = pixels.copy()
        x = edit_index % 4
        y = (edit_index // 4) % 4
        pixels = pixels.copy()
        pixels[y, x] = [edit_index, (edit_index * 3) % 256, (edit_index * 5) % 256, 255 - edit_index]
        document = dataclasses.replace(
            document,
            layers=(dataclasses.replace(document.layers[0], revision=edit_index),),
        )
        label = f"Edit {edit_index}"
        record = build_texture_editor_delta_history_record(
            label=label,
            before_document=before_document,
            after_document=document,
            before_layer_pixels={"base": before_pixels},
            after_layer_pixels={"base": pixels},
            kind="paint",
            timestamp=float(edit_index),
            dirty_bounds=(x, y, 1, 1),
            tracked_layer_ids=("base",),
        )
        expected_new_oldest_label = history[1]["entry"].label if len(history) == 100 else None
        history, history_index = texture_editor_history_with_appended_record(
            history,
            history_index,
            record,
            limit=100,
        )
        if expected_new_oldest_label is not None:
            saw_eviction = True
            assert history[0]["entry"].label == expected_new_oldest_label
            assert "checkpoint" in history[0]
        expected_by_label[label] = (document, pixels.copy())

    assert saw_eviction is True
    assert len(history) == 100
    pending_checkpoint = history[0]["checkpoint"]
    snapshot = getattr(pending_checkpoint, "snapshot", None)
    assert callable(snapshot)
    deadline = time.monotonic() + 2.0
    while snapshot()[1] and time.monotonic() < deadline:
        time.sleep(0.005)
    materialized_record, pending_records = snapshot()
    assert pending_records == ()
    assert isinstance(materialized_record.get("checkpoint"), dict)
    for retained_index in (0, 1, len(history) // 2, len(history) - 2, len(history) - 1):
        restored = _replay(history, retained_index)
        label = history[retained_index]["entry"].label
        expected_document, expected_pixels = expected_by_label[label]
        assert restored.document.layers[0].revision == expected_document.layers[0].revision
        np.testing.assert_array_equal(restored.layer_pixels["base"], expected_pixels)

    branch_index = len(history) - 8
    branch_before = _replay(history, branch_index)
    branch_pixels = branch_before.layer_pixels["base"].copy()
    branch_pixels[0, 0] = [9, 8, 7, 6]
    branch_document = dataclasses.replace(
        branch_before.document,
        layers=(dataclasses.replace(branch_before.document.layers[0], revision=999),),
    )
    branch_record = build_texture_editor_delta_history_record(
        label="Branch",
        before_document=branch_before.document,
        after_document=branch_document,
        before_layer_pixels=branch_before.layer_pixels,
        after_layer_pixels={"base": branch_pixels},
        kind="paint",
        timestamp=999.0,
        dirty_bounds=(0, 0, 1, 1),
        tracked_layer_ids=("base",),
    )
    history, history_index = texture_editor_history_with_appended_record(
        history,
        branch_index,
        branch_record,
        limit=100,
    )

    assert history_index == branch_index + 1 == len(history) - 1
    assert history[-1]["entry"].label == "Branch"
    undone = _replay(history, history_index - 1)
    redone = _replay(history, history_index)
    np.testing.assert_array_equal(undone.layer_pixels["base"], branch_before.layer_pixels["base"])
    np.testing.assert_array_equal(redone.layer_pixels["base"], branch_pixels)
    assert redone.document.layers[0].revision == 999


def test_loaded_project_history_baseline_undo_redo_is_exact(tmp_path: Path) -> None:
    document = TextureEditorDocument(
        "Project",
        3,
        2,
        layers=(TextureEditorLayer("base", "Base", ""),),
        floating_selection=TextureEditorFloatingSelection(bounds=(0, 0, 1, 1)),
    )
    pixels = np.arange(24, dtype=np.uint8).reshape((2, 3, 4))
    floating_pixels = np.array([[[11, 22, 33, 44]]], dtype=np.uint8)
    project_path = tmp_path / "history.ctfedit.json"
    save_texture_editor_project_task(
        document,
        {"base": pixels},
        project_path,
        floating_pixels=floating_pixels,
    )
    loaded_document, loaded_pixels, loaded_floating = load_texture_editor_project_task(project_path)
    history = [
        build_texture_editor_checkpoint_record(
            loaded_document,
            loaded_pixels,
            "Open Project",
            timestamp=1.0,
            floating_pixels=loaded_floating,
        )
    ]
    edited_pixels = loaded_pixels["base"].copy()
    edited_pixels[1, 2] = [201, 151, 101, 51]
    edited_floating = loaded_floating.copy()
    edited_floating[0, 0] = [1, 3, 5, 7]
    edited_document = dataclasses.replace(
        loaded_document,
        layers=(dataclasses.replace(loaded_document.layers[0], revision=1),),
    )
    edit = build_texture_editor_delta_history_record(
        label="Project Edit",
        before_document=loaded_document,
        after_document=edited_document,
        before_layer_pixels=loaded_pixels,
        after_layer_pixels={"base": edited_pixels},
        kind="paint",
        timestamp=2.0,
        dirty_bounds=(2, 1, 1, 1),
        tracked_layer_ids=("base",),
        before_floating_pixels=loaded_floating,
        after_floating_pixels=edited_floating,
    )
    history, history_index = texture_editor_history_with_appended_record(history, 0, edit)

    undone = _replay(history, history_index - 1)
    redone = _replay(history, history_index)
    assert undone.document.project_path == project_path.resolve()
    assert redone.document.project_path == project_path.resolve()
    np.testing.assert_array_equal(undone.layer_pixels["base"], pixels)
    np.testing.assert_array_equal(redone.layer_pixels["base"], edited_pixels)
    np.testing.assert_array_equal(undone.floating_pixels, floating_pixels)
    np.testing.assert_array_equal(redone.floating_pixels, edited_floating)


def test_4k_paint_history_20th_and_post100_strokes_fit_frame_budget() -> None:
    width = height = 4096
    document = TextureEditorDocument(
        "4k-hot-path",
        width,
        height,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    layer = np.zeros((height, width, 4), dtype=np.uint8)
    layer_pixels = {"paint": layer}
    settings = dataclasses.replace(
        TextureEditorToolSettings(tool="paint"),
        color_hex="#FF0000",
        size=32.0,
        spacing=20,
    )
    history = [
        build_texture_editor_checkpoint_record(
            document,
            layer_pixels,
            "Base",
            timestamp=0.0,
        )
    ]
    history_index = 0
    elapsed_ms: list[float] = []

    for edit_index in range(1, 126):
        x = 64 + ((edit_index * 31) % 3900)
        y = 64 + ((edit_index * 47) % 3900)
        dirty_bounds = (x - 17, y - 17, 34, 34)
        before_document = document
        started = time.perf_counter()
        state = texture_editor_layer_stroke_state(
            document,
            layer_pixels,
            settings,
            [(x, y)],
            layer_id="paint",
            editing_mask_target=False,
            selection_bounds=None,
            layer_canvas_bounds=(0, 0, width, height),
            brush_dirty_bounds=dirty_bounds,
        )
        assert state is not None
        assert state.layer_pixels["paint"] is layer
        assert isinstance(state.before_layer_pixels["paint"], TextureEditorHistoryLayerPatch)
        document = state.document
        layer_pixels = state.layer_pixels
        assert not texture_editor_history_should_checkpoint(
            history_count=len(history),
            force_checkpoint=False,
        )
        record = build_texture_editor_delta_history_record(
            label=state.history_label,
            before_document=before_document,
            after_document=document,
            before_layer_pixels=state.before_layer_pixels,
            after_layer_pixels=layer_pixels,
            kind=state.kind,
            timestamp=float(edit_index),
            dirty_bounds=dirty_bounds,
            tracked_layer_ids=state.tracked_layer_ids,
        )
        history, history_index = texture_editor_history_with_appended_record(
            history,
            history_index,
            record,
        )
        elapsed_ms.append((time.perf_counter() - started) * 1000.0)

    assert len(history) == 100
    assert elapsed_ms[19] < _FRAME_BUDGET_MS
    assert _percentile(elapsed_ms, 0.95) < _FRAME_BUDGET_MS
    assert _percentile(elapsed_ms[100:], 0.95) < _FRAME_BUDGET_MS

    oldest = _replay(history, 0)
    latest = _replay(history, history_index)
    undone = _replay(history, history_index - 1)
    assert oldest.document.layers[0].revision == 26
    assert latest.document.layers[0].revision == 125
    assert undone.document.layers[0].revision == 124
    np.testing.assert_array_equal(latest.layer_pixels["paint"], layer)
    assert not np.array_equal(undone.layer_pixels["paint"], latest.layer_pixels["paint"])


def test_symmetric_paint_dirty_patch_undo_redo_is_exact() -> None:
    document = TextureEditorDocument(
        "symmetric-paint",
        32,
        24,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    layer = np.zeros((24, 32, 4), dtype=np.uint8)
    settings = dataclasses.replace(
        TextureEditorToolSettings(tool="paint"),
        color_hex="#336699",
        size=4.0,
        symmetry_mode="both",
    )
    points = [(5, 7)]
    dirty_bounds = estimated_texture_editor_brush_dirty_bounds(document, settings, points)
    state = texture_editor_layer_stroke_state(
        document,
        {"paint": layer},
        settings,
        points,
        layer_id="paint",
        editing_mask_target=False,
        selection_bounds=None,
        layer_canvas_bounds=(0, 0, 32, 24),
        brush_dirty_bounds=dirty_bounds,
    )
    assert state is not None
    after_pixels = state.layer_pixels["paint"].copy()
    record = build_texture_editor_delta_history_record(
        label=state.history_label,
        before_document=document,
        after_document=state.document,
        before_layer_pixels=state.before_layer_pixels,
        after_layer_pixels=state.layer_pixels,
        kind=state.kind,
        timestamp=1.0,
        dirty_bounds=dirty_bounds,
        tracked_layer_ids=state.tracked_layer_ids,
    )

    undone = texture_editor_history_record_application_state(
        record,
        direction="before",
        current_layer_pixels=state.layer_pixels,
        copy_patch_pixels=False,
    )
    np.testing.assert_array_equal(undone.layer_pixels["paint"], np.zeros_like(layer))
    redone = texture_editor_history_record_application_state(
        record,
        direction="after",
        current_layer_pixels=undone.layer_pixels,
        copy_patch_pixels=False,
    )
    np.testing.assert_array_equal(redone.layer_pixels["paint"], after_pixels)


def test_4k_texture_editor_handler_20th_and_post100_strokes_fit_frame_budget(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = TextureEditorTab(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=tmp_path,
        get_png_root=lambda: "",
    )
    try:
        width = height = 4096
        layer = np.zeros((height, width, 4), dtype=np.uint8)
        tab.document = TextureEditorDocument(
            "4k-ui-hot-path",
            width,
            height,
            active_layer_id="paint",
            layers=(TextureEditorLayer("paint", "Paint", ""),),
        )
        tab.layer_pixels = {"paint": layer}
        tab.current_tool_settings = dataclasses.replace(
            TextureEditorToolSettings(tool="paint"),
            color_hex="#FF0000",
            size=32.0,
            spacing=20,
        )
        tab.history_snapshots = [tab._build_checkpoint_record("Base")]
        tab.history_index = 0
        tab._invalidate_composite_cache()
        tab._refresh_canvas()
        elapsed_ms: list[float] = []

        for edit_index in range(1, 126):
            x = 64 + ((edit_index * 31) % 3900)
            y = 64 + ((edit_index * 47) % 3900)
            started = time.perf_counter()
            tab._handle_canvas_stroke({"points": [(x, y)]})
            elapsed_ms.append((time.perf_counter() - started) * 1000.0)

        assert tab.layer_pixels["paint"] is layer
        assert len(tab.history_snapshots) == 100
        assert tab.history_list.count() == 100
        assert tab.history_list.currentRow() == tab.history_index == 99
        assert elapsed_ms[19] < _FRAME_BUDGET_MS
        assert _percentile(elapsed_ms, 0.95) < _FRAME_BUDGET_MS
        assert _percentile(elapsed_ms[100:], 0.95) < _FRAME_BUDGET_MS

        undo_started = time.perf_counter()
        tab.undo()
        assert (time.perf_counter() - undo_started) * 1000.0 < 50.0
        tab.undo()
        tab._handle_canvas_stroke({"points": [(2048, 2048)]})
        assert tab.history_list.count() == len(tab.history_snapshots) == 99
        assert tab.history_list.currentRow() == tab.history_index == 98
        assert [tab.history_list.item(row).text() for row in range(tab.history_list.count())][-1].endswith("(current)")
    finally:
        tab.request_shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()


class _TrackingCanvas(TextureEditorCanvas):
    def __init__(self) -> None:
        self.update_calls: list[tuple[object, ...]] = []
        super().__init__()

    def update(self, *args: object) -> None:  # type: ignore[override]
        self.update_calls.append(args)
        super().update(*args)  # type: ignore[arg-type]


def test_canvas_reuses_qimage_storage_and_repaints_dirty_region() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = _TrackingCanvas()
    rgba = np.zeros((64, 64, 4), dtype=np.uint8)
    canvas.set_rgba_images(rgba)
    image = canvas._edited_image
    canvas.update_calls.clear()

    rgba[10:14, 20:24] = [10, 20, 30, 255]
    canvas.set_rgba_images(rgba, dirty_bounds=(20, 10, 4, 4))

    assert canvas._edited_image is image
    assert any(call and isinstance(call[0], QRect) for call in canvas.update_calls)
    canvas.close()
    app.processEvents()


def test_canvas_reuses_channel_qimage_and_updates_dirty_pixels() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = _TrackingCanvas()
    rgba = np.zeros((64, 64, 4), dtype=np.uint8)
    canvas.set_rgba_images(rgba)
    canvas.set_view_mode("red")
    channel_image = canvas._channel_image
    canvas.update_calls.clear()

    rgba[10:14, 20:24, 0] = 117
    canvas.set_rgba_images(rgba, dirty_bounds=(20, 10, 4, 4))

    assert canvas._channel_image is channel_image
    assert canvas._channel_rgba is not None
    assert canvas._channel_rgba[10, 20].tolist() == [117, 117, 117, 255]
    assert any(call and isinstance(call[0], QRect) for call in canvas.update_calls)
    canvas.close()
    app.processEvents()
