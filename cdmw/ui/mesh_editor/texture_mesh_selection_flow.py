"""Select From Mesh Selection: the 3D selection as a selection on the docked texture.

The snapshot is taken on the UI thread, the pixels are worked out on a pool thread and the
selection is applied back on the UI thread, if the same texture is still open. The rules
are in :mod:`cdmw.services.mesh_texture_selection` and :mod:`cdmw.domain.textures.uv_selection`.
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal

from cdmw.services.mesh_texture_selection import (
    TextureMeshRefusal,
    TextureMeshSelection,
    TextureMeshSnapshot,
    build_texture_mesh_selection,
    snapshot_texture_mesh,
)

MODE_NAMES = {"replace": "Replace", "add": "Add", "subtract": "Subtract", "intersect": "Intersect"}
WORKING_TEXT = "Selecting from the mesh selection..."
NO_TEXTURE_TEXT = "Open a texture from the Textures panel first."


def document_key(editor: object) -> tuple:
    """What must not change between the snapshot and applying the selection."""

    document = getattr(editor, "document", None)
    if document is None:
        return ()
    binding = getattr(document, "source_binding", None)
    return (int(document.width), int(document.height), str(getattr(binding, "source_path", "") or ""),
            str(getattr(binding, "mesh_resource_id", "") or ""))


def dock_snapshot(tools: object, *, part_ids: Optional[Sequence[int]] = None,
                  every_face: bool = False) -> tuple[TextureMeshSnapshot, tuple]:
    """The docked texture's parts and the 3D selection (UI thread), with the document's key."""

    target = getattr(tools, "target", None)
    editor = getattr(tools, "editor", None)
    if target is None or getattr(editor, "document", None) is None:
        raise TextureMeshRefusal(NO_TEXTURE_TEXT)
    reader = getattr(tools, "mesh_session_reader", None)
    session = reader() if callable(reader) else None
    if session is None:
        raise TextureMeshRefusal("Open the mesh in the Mesh Editor first.")
    parts_reader = getattr(tools, "texture_parts_reader", None)
    fallback = tuple(parts_reader(target.source_sha256, target.game_path)) if callable(parts_reader) else ()
    snapshot = snapshot_texture_mesh(session, target.source_sha256, texture=target.display_name,
                                     role=target.channel, part_ids=part_ids, every_face=every_face,
                                     fallback_parts=fallback)
    return snapshot, document_key(editor)


def summary_text(snapshot: TextureMeshSnapshot, selection: TextureMeshSelection, mode: str) -> str:
    parts = snapshot.names(part for part in snapshot.chosen)
    text = (f"Selected {selection.pixels:,} pixels from {selection.report.faces:,} faces on {parts} "
            f"({MODE_NAMES.get(mode, mode)}).")
    return " ".join((text, *selection.notes))


def apply_selection(editor: object, key: tuple, snapshot: TextureMeshSnapshot,
                    selection: TextureMeshSelection, mode: str) -> str:
    """Combine the pixels with the editor's selection (UI thread); the status line's text."""

    if not key or document_key(editor) != key:
        raise TextureMeshRefusal("Another texture opened while the selection was made: try again.")
    editor.apply_mask_selection(selection.mask, combine_mode=mode, history_label="Select From Mesh")
    return summary_text(snapshot, selection, mode)


def selection_mode(editor: object) -> str:
    settings = getattr(editor, "current_tool_settings", None)
    mode = str(getattr(settings, "selection_combine_mode", "") or "replace")
    return mode if mode in MODE_NAMES else "replace"


class _Signals(QObject):
    built = Signal(int, object, str)


class _BuildRunnable(QRunnable):
    def __init__(self, request: int, snapshot: TextureMeshSnapshot, width: int, height: int,
                 signals: _Signals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._request, self._snapshot, self._size, self._signals = request, snapshot, (width, height), signals

    def run(self) -> None:
        try:
            selection = build_texture_mesh_selection(self._snapshot, *self._size)
        except TextureMeshRefusal as exc:
            self._emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001 - reported on the status line
            self._emit(None, f"Select From Mesh Selection failed: {exc}")
        else:
            self._emit(selection, "")

    def _emit(self, selection: object, error: str) -> None:
        try:
            self._signals.built.emit(self._request, selection, error)
        except RuntimeError:
            pass  # the panel went away while the pixels were worked out


class MeshSelectionToTexture(QObject):
    """The docked panel's Select From Mesh Selection: one request at a time, the newest wins."""

    #: The result line (text, True when refused); the Mesh Editor's status line shows it too.
    reported = Signal(str, bool)
    #: A request finished, applied or refused.
    finished = Signal()

    def __init__(self, tools: QObject, *, pool: QThreadPool | None = None) -> None:
        super().__init__(tools)
        self._tools = tools
        self._pool = pool or QThreadPool.globalInstance()
        self._request = 0
        self._pending: tuple[TextureMeshSnapshot, tuple, str] | None = None
        self._signals = _Signals(self)
        self._signals.built.connect(self._built, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self) -> bool:
        return self._pending is not None

    def start(self) -> bool:
        editor = getattr(self._tools, "editor", None)
        try:
            snapshot, key = dock_snapshot(self._tools)
        except TextureMeshRefusal as exc:
            self._report(str(exc), True)
            return False
        document = editor.document
        self._request += 1
        self._pending = (snapshot, key, selection_mode(editor))
        self._report(WORKING_TEXT, False)
        self._pool.start(_BuildRunnable(self._request, snapshot, int(document.width), int(document.height),
                                        self._signals))
        return True

    def cancel(self) -> None:
        self._request += 1
        self._pending = None

    def _built(self, request: int, selection: object, error: str) -> None:
        if request != self._request or self._pending is None:
            return
        snapshot, key, mode = self._pending
        self._pending = None
        try:
            if error:
                raise TextureMeshRefusal(error)
            text = apply_selection(getattr(self._tools, "editor", None), key, snapshot, selection, mode)
        except TextureMeshRefusal as exc:
            self._report(str(exc), True)
        else:
            self._report(text, False)
        self.finished.emit()

    def _report(self, text: str, refused: bool) -> None:
        self.reported.emit(text, refused)


__all__ = ["MODE_NAMES", "MeshSelectionToTexture", "apply_selection",
           "document_key", "dock_snapshot", "selection_mode", "summary_text"]
