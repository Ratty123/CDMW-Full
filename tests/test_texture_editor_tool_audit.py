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
        source = tmp_path / "texture.png"
        Image.fromarray(_texture() if rgba is None else rgba, "RGBA").save(source)
        self.tools = MeshEditorTextureTools(
            settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat), base_dir=tmp_path)
        self.edits: list[tuple[np.ndarray, bool]] = []
        self.tools.texture_edited.connect(lambda _s, _h, image, changed: self.edits.append((_rgba(image), changed)))
        self.tools.resize(1000, 700)
        self.tools.open_target(LiveTextureTarget(
            session_id="doc", source_path=str(source), source_sha256=SHA, channel="base",
            display_name=source.name, game_path="character/texture/" + source.name))
        self.editor = self.tools.editor
        deadline = time.monotonic() + 30
        while self.editor.document is None and time.monotonic() < deadline:
            _pump(0.02)
        assert self.editor.document is not None, "the texture did not open"
        _pump(0.05)
        self.edits.clear()

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
