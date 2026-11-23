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

It looks like part of the Mesh Editor: the file name on top with a warning marker when
the texture is shared or not drawn on the model live (the details in its tooltip), one
status line at the bottom (whether the edits are kept, what the sharing check found),
no Undo or Redo of its own (the Mesh Editor's cover texture edits too, and so do its
keys pressed here), and the Mesh Editor's font size throughout.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QFont, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.layout_utils import scaled_px
from cdmw.ui.mesh_editor.elided_label import ElidedLabel
from cdmw.ui.mesh_editor.live_texture_keeping import KEPT_TEXT
from cdmw.ui.mesh_editor.shared_texture_check import CHECKING_TEXT

LAUNCH_ORIGIN = "mesh_editor"
EMPTY_TEXT = "Double-click a texture in the Textures panel to edit it here."
#: The Texture Editor sections that edit the texture; the rest stay out.
_SECTIONS = ("tool_settings_section", "selection_section", "layers_section", "adjustments_section",
             "history_section")
#: The Mesh Editor's own Undo and Redo keys (the Rust editor's defaults for session.undo
#: and session.redo in shortcuts.rs); keys the user gave those commands replace them.
MESH_STEP_KEYS = {"undo": ("Ctrl+Z",), "redo": ("Ctrl+Shift+Z", "Ctrl+Y")}

_PREWARM_LOCK = threading.Lock()
_PREWARM_STARTED = False
#: Safe Python-only module pre-imports (never constructs QWidgets off the UI thread).
_PREWARM_MODULES = (
    "cdmw.domain.textures.original_output",
    "cdmw.services.mesh_live_texture_output",
    "cdmw.services.keymap_store",
    "cdmw.ui.texture_editor_tab",
)


def prewarm_texture_editor_imports() -> bool:
    """Pre-import the Texture Editor's Python modules on a background daemon thread so
    the first double-click in the Textures panel avoids the cold import spike on the UI
    thread. Returns True if this call launched the background importer."""
    global _PREWARM_STARTED
    if "cdmw.ui.texture_editor_tab" in sys.modules:
        _PREWARM_STARTED = True
        return False
    with _PREWARM_LOCK:
        if _PREWARM_STARTED:
            return False
        _PREWARM_STARTED = True

    def _run() -> None:
        for module_name in _PREWARM_MODULES:
            if module_name in sys.modules:
                continue
            try:
                importlib.import_module(module_name)
            except Exception:
                # Any genuine import error will surface deterministically on the UI
                # thread if the user later opens the docked Texture Editor.
                return

    threading.Thread(
        target=_run,
        name="cdmw-texture-editor-prewarm",
        daemon=True,
    ).start()
    return True


@dataclass(frozen=True, slots=True)
class _PendingTextureOpen:
    """Immutable snapshot captured on the UI thread before off-thread editability check."""

    request_id: int
    texture_id: str
    session_id: str
    decoded_path: str
    source_sha256: str
    game_path: str
    role: str
    file_name: str
    users: tuple[str, ...]
    in_renderer: bool
    tools_generation: int
    stop_event: threading.Event
    captured_warning: object = None


class _TextureOpenCheckSignals(QObject):
    checked = Signal(object, object, str)


class _TextureOpenCheckRunnable(QRunnable):
    """Runs `check_texture_editable` off the UI thread and relays the outcome."""

    def __init__(self, pending: _PendingTextureOpen, signals: _TextureOpenCheckSignals) -> None:
        super().__init__()
        self._pending = pending
        self._signals = signals

    def run(self) -> None:
        if self._pending.stop_event.is_set():
            return
        from cdmw.domain.textures.original_output import TextureOutputRefused, check_texture_editable

        original = None
        refused_reason = ""
        try:
            original = check_texture_editable(Path(self._pending.decoded_path))
        except TextureOutputRefused as exc:
            refused_reason = str(exc.reason)
        except Exception as exc:
            refused_reason = f"CDMW cannot read this texture, so it cannot edit it: {exc}"
        if self._pending.stop_event.is_set():
            return
        try:
            self._signals.checked.emit(self._pending, original, refused_reason)
        except RuntimeError:
            pass  # the owning tab went away while the check was in flight


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
    #: An edit shows on the model while the user paints (B item 6).
    in_renderer: bool = True


def rgba_array_image(rgba: object) -> QImage:
    """A detached QImage of a uint8 RGBA array."""

    array = np.ascontiguousarray(np.asarray(rgba, dtype=np.uint8))
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("texture pixels must be RGBA")
    height, width = int(array.shape[0]), int(array.shape[1])
    image = QImage(array.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return image.copy()


def panel_step_keys(settings: object) -> dict[str, tuple[str, ...]]:
    """The keys that take an Undo or Redo step while the panel has focus: the Mesh
    Editor's (as the user set them) and the Texture Editor's own. A key both commands
    claim stays Undo's."""

    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts

    mesh: dict[str, list[str]] = {}
    texture = default_texture_editor_shortcuts()
    if settings is not None:
        from cdmw.services.keymap_store import mesh_editor_overrides, texture_editor_keys

        try:
            mesh = mesh_editor_overrides(settings)
            texture = texture_editor_keys(settings)
        except (AttributeError, TypeError, ValueError):
            pass
    keys: dict[str, tuple[str, ...]] = {}
    taken: set[str] = set()
    for step, defaults in MESH_STEP_KEYS.items():
        chosen = [*mesh.get(f"session.{step}", defaults), texture.get(step, "")]
        normal = [QKeySequence(str(key)).toString() for key in chosen if str(key or "").strip()]
        keys[step] = tuple(key for key in dict.fromkeys(normal) if key and key not in taken)
        taken.update(keys[step])
    return keys


def shared_texture_notice(target: LiveTextureTarget | None) -> str:
    if target is None or len(target.users) < 2:
        return ""
    return "This texture is shared. Edits change it on: " + ", ".join(target.users)


def unseen_texture_notice(target: LiveTextureTarget | None) -> str:
    if target is None or target.in_renderer:
        return ""
    return ("The 3D view does not draw this file directly, so edits to it are not shown on "
            "the model while you paint. The file opens here so you can edit it.")


class MeshEditorTextureTools(QDockWidget):
    """One Mesh Editor document's texture tools."""

    texture_edited = Signal(str, str, QImage, bool)
    """session_id, source_sha256, the edited texture, and False when it was undone back
    to the texture as it was opened."""
    history_moved = Signal()
    """The shared history (B item 4) took in a texture edit, undo or redo made here."""
    texture_opened = Signal()
    """A texture was opened here: the panel has something to show."""
    emptied = Signal()
    """The panel holds no texture any more (the mesh closed, or another one loads)."""
    close_requested = Signal()
    """The panel's own close (Close Editor, or the title bar's) was pressed."""
    status_message = Signal(str, bool)
    """A line for the Mesh Editor's status bar (text, True for a refusal or failure)."""

    def __init__(self, parent: QWidget | None = None, *, settings: object = None, base_dir: Path | None = None,
                 editor_factory: Callable[[QWidget], QWidget] | None = None) -> None:
        super().__init__("Texture Editor", parent)
        self.setObjectName("MeshEditorTextureToolsDock")
        # Docks, floats, resizes and closes; closing it hides it and keeps the edit, and
        # a double-click in the Textures panel opens it again.
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                         | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.settings = settings
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self._editor_factory = editor_factory
        self.editor: QWidget | None = None
        self.target: LiveTextureTarget | None = None
        self._targets: dict[str, LiveTextureTarget] = {}
        # One history for mesh and texture edits (B item 4): set by the tab.
        self.shared_history = None
        self.step_handler: Callable[[str], bool] | None = None
        self.stepping = False
        self._step_shortcuts: list[QShortcut] = []
        #: What the panel says, as plain text, shown or not (the bridge reads them).
        self.notice_text = ""
        self.sharing_text = ""
        self.kept_text = ""
        #: The Mesh Editor's UI font, once it has said which (``sync_ui_font``).
        self._ui_font: QFont | None = None
        #: Monotonic counter bumped on ``show_empty`` to invalidate late async opens.
        self._open_generation = 0
        #: Set by the tab: the Mesh Editor session (or None), and the Textures panel's parts
        #: for a texture (source hash, game path) -> part numbers.
        self.mesh_session_reader: Callable[[], object] | None = None
        self.texture_parts_reader: Callable[[str, str], Iterable[int]] | None = None
        #: What Select From Mesh Selection last said ("" when nothing yet).
        self.mesh_selection_text = ""
        from cdmw.ui.mesh_editor.texture_mesh_selection_flow import MeshSelectionToTexture

        self.mesh_selection = MeshSelectionToTexture(self)
        self.mesh_selection.reported.connect(self._show_mesh_selection)
        self.select_from_mesh_button: QPushButton | None = None

        body = QWidget(self)
        body.setObjectName("MeshEditorTextureTools")
        layout = QVBoxLayout(body)
        pad = scaled_px(4, body)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(scaled_px(4, body))
        # The file name, with a marker when the texture is shared or not drawn live.
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(scaled_px(4, body))
        self.warning_marker = QLabel(body)
        self.warning_marker.setObjectName("MeshEditorTextureWarning")
        self.warning_marker.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.warning_marker.setVisible(False)
        self.header.addWidget(self.warning_marker)
        self.title_label = QLabel(EMPTY_TEXT, body)
        self.title_label.setObjectName("FlatSectionTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.header.addWidget(self.title_label, 1)
        # Its own close, named, beside the file name: the title bar's small cross looks
        # like the list's, and the Mesh Editor's Close ends the mesh. It hides the panel
        # as that cross does; the texture and its edits stay.
        self.close_button = QPushButton("Close Editor", body)
        self.close_button.setObjectName("MeshEditorTextureClose")
        self.close_button.setToolTip(
            "Close the Texture Editor panel. The texture's edits stay. Double-click a texture in the "
            "Textures panel to open it again; click Textures at the top first if the list is hidden."
        )
        self.close_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.close_button.clicked.connect(lambda _checked=False: self.close_requested.emit())
        self.header.addWidget(self.close_button)
        layout.addLayout(self.header)
        self.split = QSplitter(Qt.Orientation.Horizontal, body)
        self.split.setChildrenCollapsible(False)
        layout.addWidget(self.split, 1)
        # One status line under the tools, as the Mesh Editor has: each text on one
        # line, the whole of it in its tooltip.
        self.status_bar = QWidget(body)
        self.status_bar.setObjectName("MeshEditorTextureStatus")
        status = QHBoxLayout(self.status_bar)
        status.setContentsMargins(scaled_px(2, body), 0, scaled_px(2, body), 0)
        status.setSpacing(scaled_px(12, body))
        # Whether the edits are kept in the draft yet (step 8, item 3); not kept stands out.
        self.kept_label = ElidedLabel(self.status_bar)
        self.kept_label.setObjectName("HintLabel")
        self.kept_label.setVisible(False)
        status.addWidget(self.kept_label)
        # Which other game files use the opened texture (step 8, item 5).
        self.sharing_label = ElidedLabel(self.status_bar)
        self.sharing_label.setObjectName("HintLabel")
        self.sharing_label.setVisible(False)
        status.addWidget(self.sharing_label, 1)
        # What Select From Mesh Selection did, or why it could not.
        self.mesh_selection_label = ElidedLabel(self.status_bar)
        self.mesh_selection_label.setObjectName("HintLabel")
        self.mesh_selection_label.setVisible(False)
        status.addWidget(self.mesh_selection_label, 1)
        self.status_bar.setVisible(False)
        layout.addWidget(self.status_bar)
        self.setWidget(body)
        self._draw_warning_marker()

    # Opening -----------------------------------------------------------------

    def open_target(self, target: LiveTextureTarget) -> None:
        """Open ``target`` here (or bring it forward if it is already open)."""

        editor = self._ensure_editor()
        self.target = target
        self._targets[_target_key(target.source_path)] = target
        self._show_warning_marker()
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
        if self.select_from_mesh_button is not None:
            self.select_from_mesh_button.setEnabled(True)
        self.show()
        self.raise_()
        self.texture_opened.emit()

    def show_empty(self) -> None:
        """The mesh closed, or another one loads: nothing of the last one stays in view.
        The edits are the document's (its draft, Finish, Build Mod), not the panel's."""

        self._open_generation += 1
        cancel_open = getattr(self.editor, "cancel_pending_source_open", None)
        if callable(cancel_open):
            cancel_open()
        self.target = None
        self._targets = {}
        self.title_label.setText(EMPTY_TEXT)
        self.title_label.setToolTip("")
        self.sharing_text = ""
        self.sharing_label.setText("")
        self.set_kept_text("")
        self.mesh_selection.cancel()
        self.mesh_selection_text = ""
        self.mesh_selection_label.setText("")
        if self.select_from_mesh_button is not None:
            self.select_from_mesh_button.setEnabled(False)
        self._show_warning_marker()
        self._show_status()
        self.emptied.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # The host decides: it hides the panel; the edit stays.
        event.ignore()
        self.close_requested.emit()

    def _sharing_is_a_warning(self) -> bool:
        """What the sharing check found (other files, or that it could not tell); its
        progress is only a status."""

        return bool(self.sharing_text) and not self.sharing_text.startswith(CHECKING_TEXT.rstrip("."))

    def _show_warning_marker(self) -> None:
        """The marker by the file name, when the open texture is shared or not drawn
        live or other game files use it; its tooltip says which, one line each."""

        target = self.target
        self.notice_text = " ".join(text for text in (shared_texture_notice(target), unseen_texture_notice(target))
                                    if text)
        found = self.sharing_text if self._sharing_is_a_warning() else ""
        details = "\n".join(text for text in (shared_texture_notice(target), unseen_texture_notice(target), found)
                            if text)
        self.warning_marker.setToolTip(details)
        self.warning_marker.setVisible(bool(details))

    def _draw_warning_marker(self) -> None:
        side = max(8, self.title_label.fontMetrics().height() - scaled_px(2, self))
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        self.warning_marker.setPixmap(icon.pixmap(QSize(side, side)))

    def _show_status(self) -> None:
        self.kept_label.setVisible(bool(self.kept_text))
        self.sharing_label.setVisible(bool(self.sharing_text))
        self.mesh_selection_label.setVisible(bool(self.mesh_selection_text))
        self.status_bar.setVisible(bool(self.kept_text or self.sharing_text or self.mesh_selection_text))

    def select_from_mesh(self) -> bool:
        """Select From Mesh Selection: the faces selected in the 3D view, as pixels of this
        texture, combined with its selection by the selection Mode. False when refused."""

        return self.mesh_selection.start()

    def _show_mesh_selection(self, text: str, refused: bool) -> None:
        self.mesh_selection_text = str(text or "")
        self.mesh_selection_label.setText(self.mesh_selection_text)
        _restyle(self.mesh_selection_label, "WarningText" if refused else "HintLabel")
        if self.select_from_mesh_button is not None:
            self.select_from_mesh_button.setEnabled(not self.mesh_selection.busy)
        self._show_status()
        self.status_message.emit(self.mesh_selection_text, bool(refused))

    def set_shown_live_sources(self, sources: Iterable[str]) -> None:
        """The editor said which textures an edit shows on (B item 6): the open one's
        notice follows."""

        shown = {str(source).lower() for source in sources}
        self._targets = {key: dataclasses.replace(target, in_renderer=target.source_sha256.lower() in shown)
                         for key, target in self._targets.items()}
        if self.target is not None:
            self.target = dataclasses.replace(self.target, in_renderer=self.target.source_sha256.lower() in shown)
            self._show_warning_marker()
        if self._editor_factory is None:
            prewarm_texture_editor_imports()

    def set_sharing_text(self, game_path: str, text: str) -> None:
        """Say which other game files use ``game_path``, when it is the texture shown."""

        if self.target is None or self.target.game_path.casefold() != str(game_path).casefold():
            return
        self.sharing_text = str(text or "")
        self.sharing_label.setText(self.sharing_text)
        _restyle(self.sharing_label, "WarningText" if self._sharing_is_a_warning() else "HintLabel")
        self._show_warning_marker()
        self._show_status()

    def set_kept_text(self, text: str) -> None:
        """Say whether this document's texture edits are kept in its draft ("" hides it).
        Edits not kept yet stand out: closing asks about them first."""

        self.kept_text = str(text or "")
        self.kept_label.setText(self.kept_text)
        _restyle(self.kept_label, "WarningText" if self.kept_text and self.kept_text != KEPT_TEXT else "HintLabel")
        self._show_status()

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
        target = next((t for t in self._targets.values()
                       if t.session_id == session_id and t.source_sha256 == source_sha256), None)
        if target is None:
            return
        try:
            image = rgba_array_image(getattr(patch, "current_rgba", None))
        except (TypeError, ValueError):
            return
        # The editor's first history entry is the opened file; any later one is an edit.
        changed = int(getattr(self.editor, "history_index", 1) or 0) > 0
        self.texture_edited.emit(session_id, source_sha256, image, changed)
        self.observe_history(target)

    def observe_history(self, target: LiveTextureTarget | None) -> None:
        """Tell the shared history what the editor's history for ``target`` now holds."""

        history, editor = self.shared_history, self.editor
        if history is None or editor is None or target is None:
            return
        name = Path(str(target.game_path or target.display_name).replace("\\", "/")).name
        if history.observe_texture(_target_key(target.source_path), name,
                                   getattr(editor, "history_snapshots", ()) or (),
                                   int(getattr(editor, "history_index", 0) or 0)):
            self.history_moved.emit()

    def _step(self, step: str) -> None:
        """Undo or Redo pressed here: the shared history's next step (mesh or texture),
        or this texture's own when the dock is not joined to one."""

        handler = self.step_handler
        if callable(handler) and handler(step):
            return
        editor = self.editor
        if editor is not None:
            (editor.undo if step == "undo" else editor.redo)()

    def _install_step_shortcuts(self) -> None:
        """The Mesh Editor's Undo and Redo keys, and the Texture Editor's own, pressed
        anywhere in the panel take the step (a text field keeps its own undo)."""

        for shortcut in self._step_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._step_shortcuts = []
        for step, keys in panel_step_keys(self.settings).items():
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda s=step: self._step(s))
                self._step_shortcuts.append(shortcut)

    # Font --------------------------------------------------------------------

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        """The Mesh Editor's UI font, whose size its Rust editor is sent, on the whole
        panel: title, tools, their settings, Layers, Adjustments, History and the status
        line. Lists take it too, not the app's data font, as in the Rust editor."""

        _ = data_font
        self._ui_font = QFont(font)
        self._apply_ui_font()

    def _apply_ui_font(self) -> None:
        font = self._ui_font
        if font is None:
            return
        sync = getattr(self.editor, "sync_ui_font", None)
        if callable(sync):
            sync(QFont(font))  # its sizes that follow the font
        target_families = font.families() or [font.family()]
        target_size = font.pointSizeF()
        dock_class_font = QApplication.font("QDockWidget")
        for widget in (self, *self.findChildren(QWidget)):
            current = widget.font()
            if (
                widget is not self
                and widget.testAttribute(Qt.WidgetAttribute.WA_SetFont)
                and current.pointSizeF() == target_size
                and (current.families() or [current.family()]) == target_families
            ):
                continue
            # The size and family only: a bold title or section header stays bold.
            own = QFont(current)
            own.setFamilies(target_families)
            own.setPointSizeF(target_size)
            if widget is self and own == dock_class_font:
                # Qt paints a dock's title in the title font it read when the dock was
                # made unless the dock's font differs from its class font; a style hint
                # (used only when the family is missing) makes it differ, so the title
                # follows the size too.
                own.setStyleHint(QFont.StyleHint.System if own.styleHint() != QFont.StyleHint.System
                                 else QFont.StyleHint.AnyStyle)
            if own != current or not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                widget.setFont(own)
        self._fit_colour_fields()
        self._draw_warning_marker()

    def _fit_colour_fields(self) -> None:
        for name in ("paint_color_edit", "secondary_color_edit"):
            field = getattr(self.editor, name, None)
            if field is not None:  # a whole hex colour stays readable
                field.setMinimumWidth(field.fontMetrics().horizontalAdvance("#C8C8C8") + scaled_px(14, self))

    # Layout ------------------------------------------------------------------

    def _ensure_editor(self) -> QWidget:
        if self.editor is not None:
            return self.editor
        editor = self._editor_factory(self) if self._editor_factory is not None else self._default_editor()
        editor.hide()  # it does the editing; only its editing parts are shown, here
        # Every texture opens fitted to the canvas, never at 100 % overflowing it.
        editor.new_documents_open_fitted = True
        signal = getattr(editor, "resident_texture_patch_ready", None)
        if signal is not None:
            signal.connect(self._on_patch)
        self.editor = editor
        self._lay_out(editor)
        self._install_step_shortcuts()
        from cdmw.ui.commands.registry import command_registry

        registry = command_registry()
        if registry is not None:  # a key changed in Settings > Shortcuts applies at once
            registry.keymap_changed.connect(self._install_step_shortcuts)
        self._apply_ui_font()
        return editor

    def _default_editor(self) -> QWidget:
        from cdmw.ui.texture_editor_tab import TextureEditorTab

        # The whole editor, not only the panels the dock shows: the AI texture tools and the
        # editor's own commands work the controls of its other panels for the docked editor too.
        return TextureEditorTab(settings=self.settings, base_dir=self.base_dir, get_png_root=lambda: "", parent=self)

    def _lay_out(self, editor: QWidget) -> None:
        # The editor's canvas, tool buttons and sections move out of the editor's own
        # layouts below. Qt deletes their layout items there, and PySide must drop its
        # records of them or a later QThread or list item made at a freed address gets
        # one (cdmw/ui/layout_item_wrappers.py). The app sets that up at start; a
        # process that only builds this panel, such as a test, gets it here.
        from cdmw.ui.layout_item_wrappers import ensure_app_layout_item_wrapper_release

        ensure_app_layout_item_wrapper_release(QApplication.instance())
        for name, step in (("undo_button", "undo"), ("redo_button", "redo")):
            button = getattr(editor, name, None)
            if button is not None:
                # Not shown: the Mesh Editor's Undo and Redo cover texture edits (B item 4).
                # Clicked by code all the same, they take the shared history's next step,
                # so the editor's own connection to its texture-only undo is replaced.
                if button.receivers("2clicked(bool)") > 0:
                    button.clicked.disconnect()
                button.clicked.connect(lambda _checked=False, s=step: self._step(s))

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
        if self._ui_font is None:
            self._fit_colour_fields()
        for name in _SECTIONS:
            section = getattr(editor, name, None)
            if section is not None:
                section.setParent(rail)
                rail_layout.addWidget(section)
        actions = getattr(editor, "selection_actions_layout", None)
        if actions is not None:
            from cdmw.ui.mesh_editor.texture_mesh_selection_flow import BUTTON_TEXT, BUTTON_TOOLTIP

            # Only here, beside the model: the 3D selection, as a selection on this texture.
            button = QPushButton(BUTTON_TEXT)
            button.setObjectName("EditorPanelButton")
            button.setToolTip(BUTTON_TOOLTIP)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setEnabled(getattr(editor, "document", None) is not None)
            button.clicked.connect(lambda _checked=False: self.select_from_mesh())
            actions.addWidget(button, actions.rowCount(), 0, 1, 2)
            self.select_from_mesh_button = button
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
        # Never crushed: room for the tools and a canvas worth painting on.
        self.widget().setMinimumHeight(scaled_px(260, rail))
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


def _restyle(label: QLabel, name: str) -> None:
    """Give ``label`` the app stylesheet's look for ``name`` (muted, or a warning)."""

    if label.objectName() == name:
        return
    label.setObjectName(name)
    label.style().unpolish(label)
    label.style().polish(label)


__all__ = [
    "EMPTY_TEXT",
    "LiveTextureTarget",
    "MESH_STEP_KEYS",
    "MeshEditorTextureTools",
    "panel_step_keys",
    "prewarm_texture_editor_imports",
    "rgba_array_image",
    "shared_texture_notice",
    "unseen_texture_notice",
]
