"""The Mesh Editor's floating Texture Editor window (step 8, stage 3)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.mesh_editor.texture_editor_window import (
    LiveTextureTarget,
    MeshEditorTextureWindow,
    rgba_array_image,
    shared_texture_notice,
    unseen_texture_notice,
)

SHA = "cd" * 32


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeEditor(QWidget):
    resident_texture_patch_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.opened: list[tuple[Path, object]] = []

    def open_source_path(self, path, *, binding=None) -> None:
        self.opened.append((Path(path), binding))


def _target(tmp_path: Path, name: str = "a.dds", **extra) -> LiveTextureTarget:
    values = dict(session_id="session-1", source_path=str(tmp_path / name), source_sha256=SHA,
                  channel="normal", display_name=name)
    values.update(extra)
    return LiveTextureTarget(**values)


def _window(tmp_path: Path) -> MeshEditorTextureWindow:
    _app()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return MeshEditorTextureWindow(settings=settings, base_dir=tmp_path, editor_factory=_FakeEditor)


def test_one_window_retargets_and_binds_the_texture_to_the_document(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_target(_target(tmp_path, "a.dds"))
    editor = window.editor
    window.open_target(_target(tmp_path, "b.dds", source_sha256="ef" * 32))
    assert window.editor is editor
    assert [path.name for path, _ in editor.opened] == ["a.dds", "b.dds"]
    binding = editor.opened[0][1]
    assert binding.launch_origin == "mesh_editor"
    assert binding.mesh_session_id == "session-1"
    assert binding.mesh_resource_id == SHA
    assert binding.mesh_commit_mode == "live"
    assert window.isVisible()
    window.deleteLater()


def test_a_committed_edit_reaches_the_document_and_closing_only_hides(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_target(_target(tmp_path))
    edits: list[tuple[str, str, int, int]] = []
    window.texture_edited.connect(lambda s, h, image: edits.append((s, h, image.width(), image.height())))
    binding = window.editor.opened[0][1]
    rgba = np.zeros((2, 3, 4), dtype=np.uint8)
    window.editor.resident_texture_patch_ready.emit(SimpleNamespace(binding=binding, current_rgba=rgba))
    assert edits == [("session-1", SHA, 3, 2)]
    window.close()
    assert not window.isVisible()
    assert window.editor is not None  # the document and its history stay
    window.forget_session("session-1")
    window.editor.resident_texture_patch_ready.emit(SimpleNamespace(binding=binding, current_rgba=rgba))
    assert len(edits) == 1
    window.deleteLater()


def test_shared_and_shader_layer_textures_say_so(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_target(_target(tmp_path, users=("Upper body", "Belt"), in_renderer=False))
    text = window.notice.text()
    assert "Upper body" in text and "Belt" in text and "shader" in text
    assert shared_texture_notice(_target(tmp_path, users=("Upper body",))) == ""
    assert unseen_texture_notice(_target(tmp_path)) == ""
    window.deleteLater()


def test_rgba_arrays_become_detached_images() -> None:
    _app()
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[0, 1] = (10, 20, 30, 255)
    image = rgba_array_image(rgba)
    rgba[0, 1] = 0
    colour = image.pixelColor(1, 0)
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == (10, 20, 30, 255)
