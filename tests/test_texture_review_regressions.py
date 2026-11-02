"""Regressions found in the 2026-11 Textures review: layers, history, settings, saves, matching."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from cdmw.models import (
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorToolSettings,
)


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _editor(tmp_path: Path, settings=None):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    _app()
    return TextureEditorTab(
        settings=settings or create_settings(settings_file_path=tmp_path / "settings.cfg"),
        base_dir=tmp_path,
        get_png_root=lambda: str(tmp_path),
    )


def _close(editor) -> None:
    from PySide6.QtCore import QEvent

    editor.request_shutdown()
    editor.deleteLater()
    _app().sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _two_layer_document() -> TextureEditorDocument:
    return TextureEditorDocument(
        "Layers", 32, 32, active_layer_id="top",
        layers=(TextureEditorLayer("bottom", "Bottom", "b.png"), TextureEditorLayer("top", "Top", "t.png")),
    )


def _open(editor, document: TextureEditorDocument) -> None:
    from PySide6.QtCore import Qt

    editor.document = document
    editor.layer_pixels = {layer.layer_id: np.full((32, 32, 4), 120, dtype=np.uint8) for layer in document.layers}
    editor._push_history("Open Document")
    editor._refresh_ui()
    for row in range(editor.layers_list.count()):
        item = editor.layers_list.item(row)
        if item.data(Qt.UserRole) == document.active_layer_id:
            editor.layers_list.setCurrentItem(item)


def _layer(editor, layer_id: str) -> TextureEditorLayer:
    return next(layer for layer in editor.document.layers if layer.layer_id == layer_id)


def test_layer_up_and_down_buttons_move_the_layer_the_way_they_say(tmp_path) -> None:
    editor = _editor(tmp_path)
    try:
        _open(editor, _two_layer_document())
        editor.layer_down_button.click()
        assert [layer.layer_id for layer in editor.document.layers] == ["top", "bottom"]
        editor.layer_up_button.click()
        assert [layer.layer_id for layer in editor.document.layers] == ["bottom", "top"]
    finally:
        _close(editor)


def test_an_opacity_drag_undoes_as_one_step_and_key_changes_are_recorded(tmp_path) -> None:
    editor = _editor(tmp_path)
    try:
        _open(editor, _two_layer_document())
        slider = editor.layer_opacity_slider
        slider.setSliderDown(True)
        for value in (90, 70, 40):
            slider.setValue(value)
        slider.setSliderDown(False)
        assert _layer(editor, "top").opacity == 40
        editor.undo()
        assert _layer(editor, "top").opacity == 100

        slider.setValue(65)  # keyboard, wheel and groove clicks never press the slider
        assert _layer(editor, "top").opacity == 65
        editor.undo()
        assert _layer(editor, "top").opacity == 100
    finally:
        _close(editor)


def test_a_blend_mode_change_is_its_own_history_step(tmp_path) -> None:
    editor = _editor(tmp_path)
    try:
        _open(editor, _two_layer_document())
        combo = editor.layer_blend_mode_combo
        multiply = combo.findData("multiply")
        assert multiply >= 0
        combo.setCurrentIndex(multiply)
        assert _layer(editor, "top").blend_mode == "multiply"
        editor.undo()
        assert _layer(editor, "top").blend_mode == "normal"
    finally:
        _close(editor)


def test_a_floating_drag_released_on_its_last_point_is_undoable(tmp_path) -> None:
    editor = _editor(tmp_path)
    try:
        document = replace(
            _two_layer_document(),
            floating_selection=TextureEditorFloatingSelection(source_layer_id="top", bounds=(2, 2, 8, 8), committed=False),
        )
        _open(editor, document)
        editor._floating_pixels = np.full((8, 8, 4), 255, dtype=np.uint8)
        editor._handle_canvas_floating_transform({"mode": "move", "offset_x": 6, "offset_y": 0})
        editor._handle_canvas_floating_transform({"mode": "move", "offset_x": 12, "offset_y": 0})
        editor._handle_canvas_floating_transform({"mode": "move", "offset_x": 12, "offset_y": 0, "commit": True})
        assert editor.document.floating_selection.offset_x == 12
        record = editor.history_snapshots[-1]
        assert record["command"]["label"] == "Move Floating Selection"
        # The repaint has to reach the gesture's starting position, not just the last step.
        x, _y, width, _h = record["command"]["dirty_bounds"]
        assert x <= 2 and x + width >= 2 + 12 + 8
        editor.undo()
        assert editor.document.floating_selection.offset_x == 0
    finally:
        _close(editor)


def test_floating_move_bounds_follow_the_current_offset_and_transformed_size() -> None:
    from cdmw.ui.texture_workflow.editor_floating_state import texture_editor_floating_move_state

    document = replace(
        _two_layer_document(),
        floating_selection=TextureEditorFloatingSelection(bounds=(4, 4, 8, 8), offset_x=50, scale_x=2.0, committed=False),
    )
    pixels = np.full((8, 8, 4), 255, dtype=np.uint8)
    state = texture_editor_floating_move_state(document, dx=10, dy=0, floating_pixels=pixels)
    x, y, width, height = state.dirty_bounds
    assert (x, y) == (54, 4)
    assert width == 10 + 16 and height == 8


def test_quick_mask_strokes_do_not_feather_the_whole_selection_again() -> None:
    from cdmw.domain.textures.editor_selection import apply_texture_editor_selection_stroke
    from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask

    document = replace(
        _two_layer_document(),
        selection=TextureEditorSelection(mode="rect", rect=(4, 4, 12, 12), feather_radius=3),
    )
    settings = TextureEditorToolSettings(size=4, hardness=100, opacity=100, flow=100, spacing=50, tool="paint")
    once = apply_texture_editor_selection_stroke(document, settings, [(28, 28)])
    twice = apply_texture_editor_selection_stroke(once, settings, [(28, 28)])
    np.testing.assert_array_equal(
        build_texture_editor_selection_mask(32, 32, once.selection),
        build_texture_editor_selection_mask(32, 32, twice.selection),
    )


def test_saved_false_editor_checkboxes_restore_as_false(tmp_path) -> None:
    from cdmw.services.settings_service import create_settings

    # Written as text: a QSettings in the same process would hand back cached Python bools,
    # while after a restart the INI file yields "true"/"false" strings.
    settings_path = tmp_path / "settings.cfg"
    settings_path.write_text(
        "[texture_editor]\n"
        "fill_contiguous=false\nclone_aligned=false\nsample_visible_layers=false\n"
        "recolor_preserve_luma=false\ngrid_enabled=true\nlasso_snap_to_edges=true\n",
        encoding="utf-8",
    )

    editor = _editor(tmp_path, settings=create_settings(settings_file_path=settings_path))
    try:
        assert not editor.fill_contiguous_checkbox.isChecked()
        assert not editor.clone_aligned_checkbox.isChecked()
        assert not editor.sample_visible_layers_checkbox.isChecked()
        assert not editor.recolor_preserve_luma_checkbox.isChecked()
        assert editor.grid_checkbox.isChecked()
        assert editor.lasso_snap_checkbox.isChecked()
    finally:
        _close(editor)


def _saved_project(tmp_path: Path):
    from cdmw.core.texture_editor_project_io import load_texture_editor_project, save_texture_editor_project

    document = TextureEditorDocument(
        "Project", 8, 8, active_layer_id="paint", layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    pixels = {"paint": np.full((8, 8, 4), 200, dtype=np.uint8)}
    project_path = tmp_path / "foo.ctfedit.json"
    save_texture_editor_project(document, pixels, project_path)
    return project_path, load_texture_editor_project(project_path)


def test_saving_a_reopened_project_keeps_files_exported_into_its_assets(tmp_path) -> None:
    from cdmw.core.texture_editor_project_io import save_texture_editor_project
    from cdmw.ui.texture_workflow.editor_export_state import texture_editor_workspace_exports_root

    project_path, (document, pixels, _floating) = _saved_project(tmp_path)
    exports = texture_editor_workspace_exports_root(document, tmp_path / "unused")
    assert exports.parent == document.workspace_root
    (exports / "native_previews").mkdir(parents=True)
    sent_png = exports / "foo.png"
    sent_png.write_bytes(b"sent to replace")
    (exports / "native_previews" / "foo_bc7.dds").write_bytes(b"preview")

    save_texture_editor_project(document, pixels, project_path)

    assert sent_png.read_bytes() == b"sent to replace"
    assert (exports / "native_previews" / "foo_bc7.dds").is_file()
    assert any((document.workspace_root / "layers").iterdir())
    assert not [path for path in tmp_path.iterdir() if path.name.endswith(".backup")]


def test_a_project_from_a_newer_editor_is_refused_with_a_reason(tmp_path) -> None:
    from cdmw.core.texture_editor_project_io import load_texture_editor_project

    project_path, _loaded = _saved_project(tmp_path)
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["version"] = 99
    project_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="newer version"):
        load_texture_editor_project(project_path)


def test_auto_match_keeps_originals_the_user_chose(tmp_path) -> None:
    from cdmw.core.replace_assistant import ReplaceAssistantArchiveIndex
    from cdmw.models import MatchedOriginalTexture, ReplaceAssistantItem
    from cdmw.ui.replace_assistant.workers import ReplaceAssistantAutoMatchWorker

    chosen = MatchedOriginalTexture(
        package_root="0009", archive_relative_path="character/texture/sword.dds",
        loose_relative_path=Path("0009/character/texture/sword.dds"), match_reason="manual archive original",
    )
    manual = ReplaceAssistantItem(tmp_path / "sword.png", "png", matched_original=chosen, status="matched")
    pending = ReplaceAssistantItem(tmp_path / "shield.png", "png")
    empty_index = ReplaceAssistantArchiveIndex({}, {}, {}, {}, {}, {}, (), None)
    worker = ReplaceAssistantAutoMatchWorker(
        [manual, pending], archive_entries=(), original_dds_root=None, archive_index=empty_index,
    )
    payloads: list[object] = []
    worker.completed.connect(payloads.append)
    worker.run()

    items = payloads[0]["items"]
    assert items[0].matched_original == chosen and items[0].status == "matched"
    assert items[1].matched_original is None and items[1].status == "unresolved"


def test_a_profile_keeps_its_ncnn_model_when_the_model_list_is_not_built() -> None:
    from PySide6.QtWidgets import QComboBox

    from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin

    _app()

    class _Section:
        @staticmethod
        def is_body_built() -> bool:
            return False

    class _Panel(TextureWorkflowProfilesPanelMixin):
        def __init__(self) -> None:
            self.workflow_profile_ncnn_model_combo = QComboBox()
            self.ncnn_model_combo = QComboBox()
            self.chainner_section = _Section()

    panel = _Panel()
    panel._refresh_workflow_profile_ncnn_model_combo("model-b")
    assert panel._combo_value(panel.workflow_profile_ncnn_model_combo) == "model-b"
    panel._refresh_workflow_profile_ncnn_model_combo("realesrgan-x4plus")
    assert panel._combo_value(panel.workflow_profile_ncnn_model_combo) == "realesrgan-x4plus"
    panel._refresh_workflow_profile_ncnn_model_combo()
    assert panel._combo_value(panel.workflow_profile_ncnn_model_combo) == "realesrgan-x4plus"
