"""The Mesh Editor's floating Texture Editor window (step 8, stage 3).

One window per app. Double-clicking a texture in the Mesh Editor's Textures
panel opens it here; picking another texture retargets the same window. It is a
top-level window, so it can sit beside the Mesh Editor on either monitor while
the model is orbited. Every committed stroke or adjustment is handed to the
document that opened the texture, which shows it on the model at once. Closing
the window hides it: the edit stays in the document.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cdmw.models import TextureEditorSourceBinding

GEOMETRY_KEY = "mesh_editor/texture_window_geometry"
LAUNCH_ORIGIN = "mesh_editor"


@dataclass(frozen=True, slots=True)
class LiveTextureTarget:
    """What the window needs to know about one texture it was asked to open."""

    session_id: str
    source_path: str
    source_sha256: str
    channel: str
    display_name: str
    game_path: str = ""
    users: tuple[str, ...] = ()
    in_renderer: bool = True


def rgba_array_image(rgba: object) -> QImage:
    """A detached QImage of a uint8 RGBA array."""

    array = np.ascontiguousarray(np.asarray(rgba, dtype=np.uint8))
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("texture pixels must be RGBA")
    height, width = int(array.shape[0]), int(array.shape[1])
    image = QImage(array.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return image.copy()


def shared_texture_notice(target: LiveTextureTarget) -> str:
    if len(target.users) < 2:
        return ""
    return "This texture is shared. Edits change it on: " + ", ".join(target.users)


def unseen_texture_notice(target: LiveTextureTarget) -> str:
    if target.in_renderer:
        return ""
    return ("The 3D view combines this layer in the shader, so edits to it are not shown on "
            "the model while you paint. The file opens here so you can edit it.")


class MeshEditorTextureWindow(QWidget):
    """The single floating Texture Editor of the Mesh Editor."""

    texture_edited = Signal(str, str, QImage)
    """session_id, source_sha256 and the edited texture."""

    def __init__(self, *, settings: object, base_dir: Path,
                 editor_factory: Callable[[QWidget], QWidget] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("MeshEditorTextureWindow")
        self.setWindowTitle("Texture Editor")
        self.settings = settings
        self.base_dir = Path(base_dir)
        self._editor_factory = editor_factory
        self.editor: QWidget | None = None
        self.target: LiveTextureTarget | None = None
        self._targets: dict[str, LiveTextureTarget] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.notice = QLabel(self)
        self.notice.setObjectName("MeshEditorTextureWindowNotice")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        layout.addWidget(self.notice)
        self.resize(1100, 760)
        self._restore_geometry()

    # Opening -----------------------------------------------------------------

    def open_target(self, target: LiveTextureTarget) -> None:
        """Open ``target`` (or bring it forward if it is already open) and show the window."""

        editor = self._ensure_editor()
        self.target = target
        self._targets[_target_key(target.source_path)] = target
        notice = " ".join(text for text in (shared_texture_notice(target), unseen_texture_notice(target)) if text)
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        self.setWindowTitle("Texture Editor: " + target.display_name)
        binding = TextureEditorSourceBinding(
            launch_origin=LAUNCH_ORIGIN,
            display_name=target.display_name,
            source_path=target.source_path,
            archive_relative_path=target.game_path,
            mesh_session_id=target.session_id,
            mesh_resource_id=target.source_sha256,
            mesh_channel=target.channel,
            mesh_commit_mode="live",
        )
        open_source = getattr(editor, "open_source_path", None)
        if callable(open_source):
            open_source(Path(target.source_path), binding=binding)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def forget_session(self, session_id: str) -> None:
        """A document went away; its textures no longer reach a model."""

        self._targets = {key: value for key, value in self._targets.items() if value.session_id != session_id}

    # Edits -------------------------------------------------------------------

    def _on_patch(self, patch: object) -> None:
        binding = getattr(patch, "binding", None)
        if binding is None or getattr(binding, "launch_origin", "") != LAUNCH_ORIGIN:
            return
        session_id = str(getattr(binding, "mesh_session_id", "") or "")
        source_sha256 = str(getattr(binding, "mesh_resource_id", "") or "")
        if not session_id or not source_sha256:
            return
        if not any(t.session_id == session_id and t.source_sha256 == source_sha256 for t in self._targets.values()):
            return
        try:
            image = rgba_array_image(getattr(patch, "current_rgba", None))
        except (TypeError, ValueError):
            return
        self.texture_edited.emit(session_id, source_sha256, image)

    # Window ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt)
        self._save_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt)
        self._save_geometry()
        super().hideEvent(event)

    def _ensure_editor(self) -> QWidget:
        if self.editor is not None:
            return self.editor
        editor = self._editor_factory(self) if self._editor_factory is not None else self._default_editor()
        self.layout().addWidget(editor, 1)
        signal = getattr(editor, "resident_texture_patch_ready", None)
        if signal is not None:
            signal.connect(self._on_patch)
        self.editor = editor
        return editor

    def _default_editor(self) -> QWidget:
        from cdmw.ui.texture_editor_tab import TextureEditorTab

        return TextureEditorTab(settings=self.settings, base_dir=self.base_dir, get_png_root=lambda: "", parent=self)

    def _restore_geometry(self) -> None:
        value = _setting(self.settings, GEOMETRY_KEY)
        if value:
            try:
                self.restoreGeometry(value)
            except (TypeError, ValueError):
                pass

    def _save_geometry(self) -> None:
        set_value = getattr(self.settings, "setValue", None)
        if callable(set_value):
            set_value(GEOMETRY_KEY, self.saveGeometry())


def _setting(settings: object, key: str) -> object:
    value = getattr(settings, "value", None)
    return value(key) if callable(value) else None


def _target_key(path: str) -> str:
    return str(Path(path)).casefold()


_window: MeshEditorTextureWindow | None = None


def shared_texture_window(*, settings: object, base_dir: Path) -> MeshEditorTextureWindow:
    """The app's one Mesh Editor texture window, made on first use."""

    global _window
    if _window is None:
        _window = MeshEditorTextureWindow(settings=settings, base_dir=base_dir)
        _window.destroyed.connect(_forget_window)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_window.deleteLater)
    return _window


def _forget_window(*_args: object) -> None:
    global _window
    _window = None


__all__ = [
    "GEOMETRY_KEY",
    "LiveTextureTarget",
    "MeshEditorTextureWindow",
    "rgba_array_image",
    "shared_texture_notice",
    "shared_texture_window",
    "unseen_texture_notice",
]
