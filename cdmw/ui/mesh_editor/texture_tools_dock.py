"""The Mesh Editor's texture tools, docked beside the 3D view (step 8).

Double-clicking a texture in the Textures panel opens it here, under that panel and
beside the model; another texture opens in the same place. Like CDMW Native's tool
rail, the panel is tight: the tools in two columns with the options of the chosen
tool, Layers, Adjustments and History below them, and the canvas beside. Help is in
tooltips. It can float onto another monitor like any dock.

A Texture Editor does the editing; this panel shows only the parts of it that edit
the texture, so its file, export and workflow controls stay out of the Mesh Editor.
Every committed stroke or adjustment is handed to the document, which shows it on
the model at once. Hiding the panel keeps the edit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.layout_utils import scaled_px

LAUNCH_ORIGIN = "mesh_editor"
EMPTY_TEXT = "Double-click a texture in the Textures panel to edit it here."
#: The Texture Editor sections that edit the texture; the rest stay out.
_SECTIONS = ("tool_settings_section", "layers_section", "adjustments_section", "history_section")


@dataclass(frozen=True, slots=True)
class LiveTextureTarget:
    """What the panel needs to know about one texture it was asked to open."""

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


class MeshEditorTextureTools(QDockWidget):
    """One Mesh Editor document's texture tools."""

    texture_edited = Signal(str, str, QImage, bool)
    """session_id, source_sha256, the edited texture, and False when it was undone back
    to the texture as it was opened."""

    def __init__(self, parent: QWidget | None = None, *, settings: object = None, base_dir: Path | None = None,
                 editor_factory: Callable[[QWidget], QWidget] | None = None) -> None:
        super().__init__("Texture Editor", parent)
        self.setObjectName("MeshEditorTextureToolsDock")
        # Docks, floats and resizes; it cannot be closed, so it is never lost.
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.settings = settings
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self._editor_factory = editor_factory
        self.editor: QWidget | None = None
        self.target: LiveTextureTarget | None = None
        self._targets: dict[str, LiveTextureTarget] = {}

        body = QWidget(self)
        body.setObjectName("MeshEditorTextureTools")
        layout = QVBoxLayout(body)
        pad = scaled_px(4, body)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(scaled_px(4, body))
        self.header = QHBoxLayout()
        self.header.setSpacing(scaled_px(4, body))
        self.title_label = QLabel(EMPTY_TEXT, body)
        self.title_label.setObjectName("FlatSectionTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.header.addWidget(self.title_label, 1)
        layout.addLayout(self.header)
        self.notice = QLabel(body)
        self.notice.setObjectName("WarningText")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        layout.addWidget(self.notice)
        # Whether the edits are kept in the draft yet (step 8, item 3).
        self.kept_label = QLabel(body)
        self.kept_label.setObjectName("MeshEditorTextureKeptState")
        self.kept_label.setWordWrap(True)
        self.kept_label.setVisible(False)
        layout.addWidget(self.kept_label)
        self.split = QSplitter(Qt.Orientation.Horizontal, body)
        self.split.setChildrenCollapsible(False)
        layout.addWidget(self.split, 1)
        self.setWidget(body)

    # Opening -----------------------------------------------------------------

    def open_target(self, target: LiveTextureTarget) -> None:
        """Open ``target`` here (or bring it forward if it is already open)."""

        editor = self._ensure_editor()
        self.target = target
        self._targets[_target_key(target.source_path)] = target
        notice = " ".join(text for text in (shared_texture_notice(target), unseen_texture_notice(target)) if text)
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        self.title_label.setText(target.display_name)
        self.title_label.setToolTip(target.game_path or target.display_name)
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
        self.show()
        self.raise_()
        self._widen_for_the_canvas()

    def _widen_for_the_canvas(self) -> None:
        """Docked beside the model, the tools take about 45 % of the editor's width (once)."""

        host = self.parentWidget()
        resize = getattr(host, "resizeDocks", None)
        if self.isFloating() or not callable(resize) or getattr(self, "_widened", False):
            return
        self._widened = True
        width = max(scaled_px(560, self), int(host.width() * 0.45))
        if self.width() < width:
            resize([self], [width], Qt.Orientation.Horizontal)

    def set_kept_text(self, text: str) -> None:
        """Say whether this document's texture edits are kept in its draft ("" hides it)."""

        self.kept_label.setText(text)
        self.kept_label.setVisible(bool(text))

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
        # The editor's first history entry is the opened file; any later one is an edit.
        changed = int(getattr(self.editor, "history_index", 1) or 0) > 0
        self.texture_edited.emit(session_id, source_sha256, image, changed)

    # Layout ------------------------------------------------------------------

    def _ensure_editor(self) -> QWidget:
        if self.editor is not None:
            return self.editor
        editor = self._editor_factory(self) if self._editor_factory is not None else self._default_editor()
        editor.hide()  # it does the editing; only its editing parts are shown, here
        signal = getattr(editor, "resident_texture_patch_ready", None)
        if signal is not None:
            signal.connect(self._on_patch)
        self.editor = editor
        self._lay_out(editor)
        return editor

    def _default_editor(self) -> QWidget:
        from cdmw.ui.texture_editor_tab import TextureEditorTab

        return TextureEditorTab(settings=self.settings, base_dir=self.base_dir, get_png_root=lambda: "", parent=self)

    def _lay_out(self, editor: QWidget) -> None:
        body = self.widget()
        for name in ("undo_button", "redo_button"):
            button = getattr(editor, name, None)
            if button is not None:
                button.setParent(body)
                button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.header.addWidget(button)

        rail = QWidget()
        rail.setObjectName("MeshEditorTextureRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, scaled_px(2, rail), 0)
        rail_layout.setSpacing(scaled_px(4, rail))
        tools = getattr(editor, "tool_buttons", {}) or {}
        if tools:
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(scaled_px(2, rail))
            for index, button in enumerate(tools.values()):
                button.setParent(rail)
                button.setMinimumHeight(scaled_px(22, rail))
                grid.addWidget(button, index // 2, index % 2)
            rail_layout.addLayout(grid)
        form = getattr(editor, "tool_settings_layout", None)
        if form is not None:
            # Labels beside their fields, close together, as in Native's rail.
            from PySide6.QtWidgets import QFormLayout

            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form.setHorizontalSpacing(scaled_px(6, rail))
            form.setVerticalSpacing(scaled_px(3, rail))
        for name in ("paint_color_edit", "secondary_color_edit"):
            field = getattr(editor, name, None)
            if field is not None:  # a whole hex colour stays readable
                field.setMinimumWidth(field.fontMetrics().horizontalAdvance("#C8C8C8") + scaled_px(14, rail))
        for name in _SECTIONS:
            section = getattr(editor, name, None)
            if section is not None:
                section.setParent(rail)
                rail_layout.addWidget(section)
        rail_layout.addStretch(1)
        rail_scroll = QScrollArea()
        rail_scroll.setObjectName("EditorSidebarScroll")
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail_scroll.setWidget(rail)
        # Never narrower than what it holds, so no label or field is cut off on the
        # right; it follows the contents when a section opens or a tool's options change.
        _FitRail(rail, rail_scroll)
        self.split.addWidget(rail_scroll)

        canvas = getattr(editor, "canvas_scroll", None)
        if canvas is not None:
            canvas.setParent(None)
            canvas.setMinimumSize(scaled_px(160, rail), scaled_px(160, rail))
            self.split.addWidget(canvas)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(self.split.count() - 1, 1)
        self.split.setSizes([rail_scroll.minimumWidth(), scaled_px(420, rail)])
        fit = getattr(editor, "_set_fit_mode", None)
        if callable(fit):
            fit(True)  # the whole texture in view; zoom with the wheel


class _FitRail(QObject):
    """Keeps a rail's scroll area at least as wide as the rail's widest row."""

    def __init__(self, rail: QWidget, scroll: QScrollArea) -> None:
        super().__init__(rail)
        self.rail = rail
        self.scroll = scroll
        rail.installEventFilter(self)
        self.fit()

    def fit(self) -> None:
        bar = self.scroll.verticalScrollBar().sizeHint().width()
        self.scroll.setMinimumWidth(self.rail.minimumSizeHint().width() + bar + 2)

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self.fit()
        return False


def _target_key(path: str) -> str:
    return str(Path(path)).casefold()


__all__ = [
    "EMPTY_TEXT",
    "LiveTextureTarget",
    "MeshEditorTextureTools",
    "rgba_array_image",
    "shared_texture_notice",
    "unseen_texture_notice",
]
