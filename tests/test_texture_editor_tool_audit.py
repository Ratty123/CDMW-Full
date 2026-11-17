"""The Mesh Editor's docked Texture Editor tools, driven as a user drives them.

Each test opens a texture in the dock the way double-clicking it in the Textures panel
does, uses a tool through the same handler a click, drag or button reaches, and checks
the pixels, the canvas and the edit handed to the Mesh Editor for the model.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from cdmw.models import TextureEditorToolSettings  # noqa: E402
from cdmw.domain.textures.editor_raster_tools import apply_texture_editor_recolor  # noqa: E402

SHA = "ab" * 32


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _pump(seconds: float = 0.05) -> None:
    app = _app()
    end = time.monotonic() + seconds
    while True:
        app.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.002)


def _texture() -> np.ndarray:
    """64 x 64: a shaded red band on top, mid grey below, opaque."""
    rgba = np.zeros((64, 64, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    ramp = np.linspace(90, 230, 64).astype(np.uint8)
    rgba[:32, :, 0] = ramp[None, :]
    rgba[:32, :, 1] = 24
    rgba[:32, :, 2] = 24
    rgba[32:, :, :3] = 128
    return rgba


class _Dock:
    """The dock with a texture open in it and every edit it hands the Mesh Editor."""

    def __init__(self, tmp_path: Path, rgba: np.ndarray | None = None) -> None:
        from PySide6.QtCore import QSettings

        from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools

        _app()
        self.tmp_path = tmp_path
        self.tools = MeshEditorTextureTools(
            settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat), base_dir=tmp_path)
        self.edits: list[tuple[np.ndarray, bool]] = []
        self.edited_shas: list[str] = []
        self.tools.texture_edited.connect(self._edited)
        self.tools.resize(1000, 700)
        self._target_class = LiveTextureTarget
        self.open("texture.png", SHA, _texture() if rgba is None else rgba)

    def _edited(self, _session: str, sha: str, image, changed: bool) -> None:
        self.edits.append((_rgba(image), changed))
        self.edited_shas.append(sha)

    def open(self, name: str, sha: str, rgba: np.ndarray) -> None:
        source = self.tmp_path / name
        Image.fromarray(rgba, "RGBA").save(source)
        self.tools.open_target(self._target_class(
            session_id="doc", source_path=str(source), source_sha256=sha, channel="base",
            display_name=source.name, game_path="character/texture/" + source.name))
        self.editor = self.tools.editor
        deadline = time.monotonic() + 30
        while (self.editor.document is None or self.editor.document.source_binding.mesh_resource_id != sha) \
                and time.monotonic() < deadline:
            _pump(0.02)
        assert self.editor.document is not None and self.editor.document.source_binding.mesh_resource_id == sha
        _pump(0.05)
        self.edits.clear()
        self.edited_shas.clear()

    def composite(self) -> np.ndarray:
        return np.array(self.editor._current_composite_rgba(), copy=True)

    def canvas(self) -> np.ndarray:
        return _rgba(self.editor.canvas._edited_image)

    def live(self) -> np.ndarray | None:
        return self.edits[-1][0] if self.edits else None

    def close(self) -> None:
        from PySide6.QtCore import QEvent

        self.editor.request_shutdown()
        self.tools.deleteLater()
        _app().sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _rgba(image) -> np.ndarray:
    from cdmw.ui.mesh_editor.live_texture_updates import image_rgba8

    width, height, data = image_rgba8(image)
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4).copy()


@pytest.fixture
def dock(tmp_path):
    opened = _Dock(tmp_path)
    try:
        yield opened
    finally:
        opened.close()


def _recolor(**values) -> TextureEditorToolSettings:
    return TextureEditorToolSettings(tool="recolor", **values)


# Recolor --------------------------------------------------------------------------


def test_replace_colour_changes_only_colours_within_the_tolerance() -> None:
    rgba = _texture()
    settings = _recolor(recolor_mode="replace_color", recolor_source_hex="#C81818",
                        recolor_target_hex="#2100C8", recolor_tolerance=48, recolor_strength=100,
                        recolor_preserve_luminance=False)
    out = apply_texture_editor_recolor(rgba, settings)
    # Grey is about 160 away from the red source: far outside a tolerance of 48.
    assert np.array_equal(out[32:], rgba[32:]), "grey changed"
    near = int(np.argmin(np.abs(rgba[0, :, 0].astype(int) - 200)))
    assert out[0, near, 2] > rgba[0, near, 2] + 100, "the red the source names was not recoloured"
    far = 0  # red 90: about 110 from the source
    assert np.array_equal(out[0, far], rgba[0, far])
    # Closer colours move further towards the target (the tolerance's falloff).
    blue = out[0, :, 2].astype(int)
    assert blue[near] > blue[near - 12] > rgba[0, 0, 2]


def test_the_user_s_replace_settings_leave_a_far_colour_alone() -> None:
    """The reported case: a brown texture, source #800002, target #2100C8. Every pixel
    turned solid blue because the distance wrapped in uint8."""
    brown = np.zeros((8, 8, 4), dtype=np.uint8)
    brown[..., :3] = (79, 68, 51)
    brown[..., 3] = 255
    out = apply_texture_editor_recolor(brown, _recolor(
        recolor_mode="replace_color", recolor_source_hex="#800002", recolor_target_hex="#2100C8",
        recolor_tolerance=90, recolor_strength=100, recolor_preserve_luminance=True))
    assert np.array_equal(out, brown), "about 97 from the source, outside a tolerance of 90"


def test_recolor_skips_transparent_pixels_and_honours_the_selection() -> None:
    rgba = _texture()
    rgba[0, 0, 3] = 0
    mask = np.zeros(rgba.shape[:2], dtype=np.uint8)
    mask[:, 32:] = 255
    out = apply_texture_editor_recolor(rgba, _recolor(recolor_mode="tint", recolor_target_hex="#2100C8",
                                                      recolor_strength=100), selection_mask=mask)
    assert np.array_equal(out[:, :32], rgba[:, :32])
    assert not np.array_equal(out[:, 32:], rgba[:, 32:])
    assert np.array_equal(out[..., 3], rgba[..., 3])


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])


def test_preserve_luminance_keeps_the_shading_and_the_target_hue() -> None:
    rgba = _texture()
    out = apply_texture_editor_recolor(rgba, _recolor(
        recolor_mode="tint", recolor_target_hex="#2100C8", recolor_strength=100,
        recolor_preserve_luminance=True))
    # Every pixel keeps its brightness (the red ramp's shading and the grey), within rounding.
    assert np.max(np.abs(_luma(out) - _luma(rgba))) <= 1.0
    # And takes the target's hue: blue the strongest channel, then red, then green.
    r, g, b = (out[..., channel].astype(int) for channel in range(3))
    assert np.all(b > r) and np.all(r >= g)
    # Brighter pixels stay brighter: the shading is not flattened.
    assert np.all(np.diff(_luma(out[0])) >= -1.0) and _luma(out[0, -1]) - _luma(out[0, 0]) > 30


def test_apply_recolor_in_the_dock_reaches_canvas_model_and_history(dock) -> None:
    editor = dock.editor
    before = dock.composite()
    editor.tool_buttons["recolor"].click()
    editor.recolor_mode_combo.setCurrentIndex(editor.recolor_mode_combo.findData("replace_color"))
    editor.recolor_source_edit.setText("#C81818")
    editor.recolor_target_edit.setText("#2100C8")
    editor.recolor_tolerance_slider.setValue(48)
    editor.apply_recolor_button.click()
    _pump(0.05)
    after = dock.composite()
    assert np.array_equal(after[32:], before[32:]), "grey changed"
    assert not np.array_equal(after[:32], before[:32])
    assert np.array_equal(dock.canvas(), after)
    assert dock.live() is not None and np.array_equal(dock.live(), after) and dock.edits[-1][1]
    editor.undo()
    _pump(0.05)
    assert np.array_equal(dock.composite(), before)
    editor.redo()
    _pump(0.05)
    assert np.array_equal(dock.composite(), after)


# Every edit reaches the model -------------------------------------------------------


def _shows_on_the_model(dock, *, changed: bool = True) -> bool:
    _pump(0.05)
    live = dock.live()
    return live is not None and np.array_equal(live, dock.composite()) and dock.edits[-1][1] is changed


def test_move_layer_visibility_undo_and_history_restore_reach_the_model(dock) -> None:
    editor = dock.editor
    opened = dock.composite()
    editor.tool_buttons["move"].click()
    editor.canvas.stroke_committed.emit({"tool": "move", "points": [(10, 10), (20, 15)]})
    assert not np.array_equal(dock.composite(), opened)
    assert _shows_on_the_model(dock), "Move"

    dock.edits.clear()
    editor.layer_visible_checkbox.setChecked(False)
    assert int(dock.composite()[..., 3].max()) == 0
    assert _shows_on_the_model(dock), "hiding the layer"

    dock.edits.clear()
    editor.undo()
    assert _shows_on_the_model(dock), "Undo of hiding the layer"
    assert int(dock.composite()[..., 3].max()) == 255

    dock.edits.clear()
    editor.history_list.setCurrentRow(0)
    editor.history_restore_button.click()
    assert np.array_equal(dock.composite(), opened)
    assert _shows_on_the_model(dock, changed=False), "History restore to the opened texture"


def test_a_patch_for_one_texture_is_not_sent_once_another_is_shown(dock) -> None:
    dock.open("second.png", "cd" * 32, np.full((64, 64, 4), 200, dtype=np.uint8))
    editor = dock.editor
    first = next(index for index, session in enumerate(editor._sessions)
                 if session.document.source_binding.mesh_resource_id == SHA)
    editor.tool_buttons["move"].click()
    editor.canvas.stroke_committed.emit({"tool": "move", "points": [(10, 10), (20, 15)]})
    editor.document_tab_bar.setCurrentIndex(first)  # before the patch goes out
    _pump(0.05)
    assert editor.document.source_binding.mesh_resource_id == SHA
    assert SHA not in dock.edited_shas, "the second texture's edit went out as the first's"


# Adjustments ---------------------------------------------------------------------


def _add_adjustment(editor, kind: str) -> None:
    editor.adjustment_add_combo.setCurrentIndex(editor.adjustment_add_combo.findData(kind))
    editor.adjustment_add_button.click()
    _pump(0.05)


def test_an_adjustment_changed_by_key_or_wheel_is_an_undo_step_and_shows_on_the_model(dock) -> None:
    editor = dock.editor
    _add_adjustment(editor, "brightness_contrast")
    before = dock.composite()
    steps = editor.history_index
    dock.edits.clear()
    slider = editor.adjustment_param_a_slider
    slider.setValue(slider.maximum())  # a key press or the wheel: the slider is never pressed
    _pump(0.1)
    after = dock.composite()
    assert not np.array_equal(after, before)
    assert editor.history_index == steps + 1, "the change is its own Undo step"
    assert _shows_on_the_model(dock), "the model shows the brighter texture"
    editor.undo()
    _pump(0.05)
    assert np.array_equal(dock.composite(), before)
    editor.redo()
    _pump(0.05)
    assert np.array_equal(dock.composite(), after)


def test_an_adjustment_drag_is_one_undo_step_when_released(dock) -> None:
    editor = dock.editor
    _add_adjustment(editor, "brightness_contrast")
    before = dock.composite()
    steps = editor.history_index
    slider = editor.adjustment_param_a_slider
    slider.setSliderDown(True)
    for value in (10, 30, 60):
        slider.setValue(value)
        _pump(0.05)
    assert editor.history_index == steps, "nothing is committed while the slider is held"
    slider.setSliderDown(False)
    _pump(0.05)
    assert editor.history_index == steps + 1
    assert _shows_on_the_model(dock)
    editor.undo()
    _pump(0.05)
    assert np.array_equal(dock.composite(), before)


# Brush settings --------------------------------------------------------------------


def test_opacity_caps_the_stroke_and_flow_builds_up() -> None:
    from dataclasses import replace

    from cdmw.domain.textures.editor_brush import apply_texture_editor_stroke
    from cdmw.models import TextureEditorDocument, TextureEditorLayer

    document = TextureEditorDocument("Brush", 96, 32, active_layer_id="paint",
                                     layers=(TextureEditorLayer("paint", "Paint", "unused.png"),))
    blank = np.zeros((32, 96, 4), dtype=np.uint8)
    settings = TextureEditorToolSettings(tool="paint", size=16, hardness=100, opacity=100, flow=100,
                                         spacing=10, color_hex="#FFFFFF")
    line = [(16, 16), (80, 16)]

    def alpha(**values) -> int:
        out = apply_texture_editor_stroke(document, {"paint": blank}, replace(settings, **values), line)["paint"]
        return int(out[16, 48, 3])

    # Stamps overlap about ten times at the middle of the line.
    assert abs(alpha(opacity=30) - round(0.3 * 255)) <= 1, "opacity is the most a stroke covers"
    assert alpha(flow=30) > 200, "flow builds up where stamps overlap"
    assert abs(alpha(opacity=50, flow=30) - round(0.5 * alpha(flow=30))) <= 1
    assert alpha() == 255


def test_an_opacity_drag_in_the_dock_stays_at_its_opacity(dock) -> None:
    editor = dock.editor
    editor.tool_buttons["paint"].click()
    editor.paint_color_edit.setText("#00FF00")
    editor.brush_size_slider.setValue(12)
    editor.hardness_slider.setValue(100)
    editor.flow_slider.setValue(100)
    editor.opacity_slider.setValue(30)
    editor.spacing_slider.setValue(10)
    before = dock.composite()
    editor.canvas.stroke_committed.emit({"tool": "paint", "points": [(10, 48), (54, 48)]})
    after = dock.composite()
    green = int(after[48, 32, 1])
    expected = round(int(before[48, 32, 1]) + 0.3 * (255 - int(before[48, 32, 1])))
    assert abs(green - expected) <= 1, (green, expected)
    assert _shows_on_the_model(dock)


def test_hue_saturation_and_vibrance_at_zero_leave_the_texture_alone() -> None:
    from cdmw.domain.textures.editor_composite import _apply_adjustment_to_rgba
    from cdmw.models import TextureEditorAdjustmentLayer

    rgba = np.random.default_rng(3).integers(0, 256, (64, 64, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    for kind in ("hue_saturation", "vibrance"):
        out = _apply_adjustment_to_rgba(rgba, TextureEditorAdjustmentLayer("a", kind, kind))
        assert np.array_equal(out, rgba), kind
    # And a hue turn of 180 degrees takes red to cyan, keeping brightness and saturation.
    red = np.zeros((1, 1, 4), dtype=np.uint8)
    red[..., :] = (200, 40, 40, 255)
    turned = _apply_adjustment_to_rgba(red, TextureEditorAdjustmentLayer(
        "a", "h", "hue_saturation", parameters={"hue": 180.0}))
    assert tuple(int(v) for v in turned[0, 0]) == (40, 200, 200, 255)


def test_adding_an_adjustment_at_its_defaults_changes_nothing_on_the_model(dock) -> None:
    editor = dock.editor
    rgba = np.random.default_rng(5).integers(0, 256, (64, 64, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    dock.open("random.png", "ef" * 32, rgba)
    opened = dock.composite()
    for kind in ("hue_saturation", "vibrance", "brightness_contrast", "exposure", "color_balance",
                 "selective_color", "levels", "curves"):
        _add_adjustment(editor, kind)
        assert np.array_equal(dock.composite(), opened), kind


# History -------------------------------------------------------------------------


def test_the_dock_keeps_the_texture_history_the_mesh_editor_undoes_through(dock) -> None:
    """Clear History made the opened texture's edits look undone: after Clear, an edit and
    its Undo, the panel told the Mesh Editor the texture was as opened, so Build Mod would
    have left the edited texture out."""
    editor = dock.editor
    opened = dock.composite()
    editor.tool_buttons["paint"].click()
    editor.paint_color_edit.setText("#00FF00")
    editor.canvas.stroke_committed.emit({"tool": "paint", "points": [(10, 10), (40, 10)]})
    _pump(0.05)
    assert not editor.history_clear_button.isEnabled()
    assert "Undo history" in editor.history_clear_button.toolTip()
    steps = len(editor.history_snapshots)
    editor.clear_history()
    assert len(editor.history_snapshots) == steps
    editor.canvas.stroke_committed.emit({"tool": "paint", "points": [(10, 40), (40, 40)]})
    _pump(0.05)
    dock.edits.clear()
    editor.undo()
    assert not np.array_equal(dock.composite(), opened)
    assert _shows_on_the_model(dock, changed=True), "the first stroke is still an edit"
    editor.undo()
    assert np.array_equal(dock.composite(), opened)
    assert _shows_on_the_model(dock, changed=False)


def test_a_texture_opened_on_its_own_can_still_clear_its_history(tmp_path) -> None:
    from cdmw.services.settings_service import create_settings
    from cdmw.models import TextureEditorDocument, TextureEditorLayer
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    _app()
    editor = TextureEditorTab(settings=create_settings(settings_file_path=tmp_path / "settings.cfg"),
                              base_dir=tmp_path, get_png_root=lambda: str(tmp_path))
    try:
        document = TextureEditorDocument("Own", 16, 16, active_layer_id="base",
                                         layers=(TextureEditorLayer("base", "Base", "base.png"),))
        editor._create_session(document, {"base": np.full((16, 16, 4), 200, dtype=np.uint8)}, label="Own")
        editor._push_history("Open")
        editor.canvas.stroke_committed.emit({"tool": "paint", "points": [(2, 2), (12, 2)]})
        editor._refresh_ui()
        assert editor.history_clear_button.isEnabled()
        editor.clear_history()
        assert len(editor.history_snapshots) == 1 and editor.history_index == 0
    finally:
        from PySide6.QtCore import QEvent

        editor.request_shutdown()
        editor.deleteLater()
        _app().sendPostedEvents(None, QEvent.Type.DeferredDelete)


# The edit as the model gets it ----------------------------------------------------------


def test_a_recolor_reaches_the_file_the_mesh_editor_loads(dock, tmp_path) -> None:
    """The dock's edit goes through LiveTextureUpdates, as the Mesh Editor wires it, and
    the RGBA8 DDS it writes for the 3D view holds the recoloured pixels."""
    from PySide6.QtCore import QThreadPool

    from cdmw.ui.mesh_editor.live_texture_updates import EDITS_DIRNAME, LiveTextureUpdates

    session_root = tmp_path / "session"
    session_root.mkdir()
    sent: list[dict] = []
    pool = QThreadPool()
    live = LiveTextureUpdates(lambda: session_root, lambda payload: sent.append(dict(payload)) or True, pool=pool)
    dock.tools.texture_edited.connect(lambda _s, sha, image, changed: live.push(sha, image, changed=changed))
    editor = dock.editor
    editor.tool_buttons["recolor"].click()
    editor.recolor_mode_combo.setCurrentIndex(editor.recolor_mode_combo.findData("tint"))
    editor.recolor_target_edit.setText("#2100C8")
    editor.apply_recolor_button.click()
    deadline = time.monotonic() + 10
    while not sent and time.monotonic() < deadline:
        pool.waitForDone(100)
        _pump(0.02)
    assert sent and sent[-1]["source_sha256"] == SHA
    path = session_root / sent[-1]["file"]
    assert path.parent.name == EDITS_DIRNAME
    data = path.read_bytes()
    pixels = np.frombuffer(data[128:], dtype=np.uint8).reshape(64, 64, 4)
    assert np.array_equal(pixels, dock.composite())
    assert set(live.edited_textures()) == {SHA}
