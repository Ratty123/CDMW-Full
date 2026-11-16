"""Keep a Mesh Editor document's live texture edits in its draft (step 8, item 3).

A moment after an edit, and again right after a Finish (which creates the draft folder
when there was none), the edits not kept yet are written into the draft on a worker.
Reopening the draft (Resume, Continue editing) shows them on the model again. Until the
draft exists the edits are only in memory, and the dock says so; closing with edits not
kept asks first (``end_edit_prompt.has_pending_edit``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

KEPT_TEXT = "Texture edits are kept in this draft."
NOT_KEPT_TEXT = "Texture edits are not kept yet: Finish keeps them in the draft."
RESTORED_TEXT = "The texture edits kept in this draft are shown on the model again."
SAVE_DELAY_MS = 1500
#: After a Finish the draft folder is written by the session's own save, shortly after.
WAIT_FOR_DRAFT_TRIES = 20


class _Signals(QObject):
    saved = Signal(object, object, str)  # draft root, {key: edits}, error
    restored = Signal(object, object)  # draft root, restored edits


class _Job(QRunnable):
    def __init__(self, work: Callable[[], None]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        self._work()


class LiveTextureKeeper(QObject):
    """Saves and restores one document's live texture edits through its draft."""

    status = Signal(str, bool)
    kept_changed = Signal(str)

    def __init__(self, live, draft_root: Callable[[], Path | None], parent: QObject | None = None,
                 *, pool: QThreadPool | None = None, delay_ms: int = SAVE_DELAY_MS) -> None:
        super().__init__(parent)
        self._live = live
        self._draft_root = draft_root
        self._pool = pool or QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.saved.connect(self._on_saved)
        self._signals.restored.connect(self._on_restored)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(delay_ms))
        self._timer.timeout.connect(self.save_now)
        self._saving = False
        self._again = False
        self._wait_tries = 0
        #: Role and game path of edits restored from the draft, until their texture is opened.
        self.restored_info: dict[str, tuple[str, str]] = {}

    # ----- state ------------------------------------------------------------
    def unkept_count(self) -> int:
        return len(self._live.unkept())

    def kept_text(self) -> str:
        if not self._live.edited_textures() and not self.unkept_count():
            return ""
        return NOT_KEPT_TEXT if self.unkept_count() or self._draft_root() is None else KEPT_TEXT

    # ----- saving -----------------------------------------------------------
    def edited(self) -> None:
        """An edit was made: keep it in a moment (edits in a row are kept once)."""

        self.kept_changed.emit(self.kept_text())
        self._timer.start()

    def finished(self) -> None:
        """A Finish was accepted: keep the edits as soon as the draft folder exists."""

        self._wait_tries = WAIT_FOR_DRAFT_TRIES
        self.save_now()

    def save_now(self) -> None:
        due = self._live.unkept()
        if not due:
            self.kept_changed.emit(self.kept_text())
            return
        root = self._draft_root()
        if root is None:
            if self._wait_tries > 0:
                self._wait_tries -= 1
                QTimer.singleShot(500, self, self.save_now)
            self.kept_changed.emit(self.kept_text())
            return
        if self._saving:
            self._again = True
            return
        from cdmw.services.mesh_live_texture_drafts import LiveDraftEdit
        from cdmw.ui.mesh_editor.live_texture_updates import image_rgba8

        import numpy as np

        edits, forget, counts = [], [], {}
        for key, (count, image) in due.items():
            source = self._live.sources.get(key)
            role, game_path = (getattr(source, "role", ""), getattr(source, "game_path", "")) if source is not None \
                else self.restored_info.get(key, ("", ""))
            if not game_path:
                continue  # not opened from the panel: nothing to say where it goes
            counts[key] = count
            if image is None:
                forget.append((key, role))
                continue
            width, height, data = image_rgba8(image)
            original = getattr(source, "original", None)
            edits.append(LiveDraftEdit(
                live_key=key, role=role, game_path=game_path,
                rgba=np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4).copy(),
                original_format=str(getattr(original, "dds_format", "") or "")))
        if not counts:
            return
        self._saving = True
        signals = self._signals

        def work() -> None:
            from cdmw.services.mesh_live_texture_drafts import forget_live_edits, save_live_edits

            error = ""
            try:
                save_live_edits(root, edits)
                forget_live_edits(root, forget)
            except OSError as exc:
                error = str(exc)
            try:
                signals.saved.emit(root, counts, error)
            except RuntimeError:
                pass

        self._pool.start(_Job(work))

    def _on_saved(self, _root: object, counts: object, error: str) -> None:
        self._saving = False
        if error:
            self.status.emit(error, True)
        else:
            for key, count in dict(counts).items():
                self._live.mark_kept(key, count)
        self.kept_changed.emit(self.kept_text())
        if self._again:
            self._again = False
            self.save_now()

    # ----- restoring ----------------------------------------------------------
    def restore(self, root: Path) -> bool:
        """Read the edits kept in the draft at ``root`` and show them again; False when it
        keeps none."""

        if not (Path(root) / "textures" / "manifest.json").is_file():
            return False
        signals = self._signals

        def work() -> None:
            from cdmw.services.mesh_live_texture_drafts import restore_live_edits

            try:
                restored = restore_live_edits(Path(root))
            except (OSError, ValueError) as exc:
                restored = exc
            try:
                signals.restored.emit(root, restored)
            except RuntimeError:
                pass

        self._pool.start(_Job(work))
        return True

    def _on_restored(self, root: object, restored: object) -> None:
        if self._draft_root() != Path(root):
            return  # another draft opened meanwhile
        if isinstance(restored, Exception):
            self.status.emit(f"The texture edits kept in this draft could not be read: {restored}", True)
            return
        from cdmw.ui.mesh_editor.texture_tools_dock import rgba_array_image

        shown = 0
        for edit in restored:
            if edit.rgba is None:
                self.status.emit(edit.problem, True)
                continue
            self.restored_info[edit.live_key] = (edit.role, edit.game_path)
            self._live.push(edit.live_key, rgba_array_image(edit.rgba))
            # What the draft holds is kept already.
            count, _image = self._live.unkept().get(edit.live_key, (0, None))
            self._live.mark_kept(edit.live_key, count)
            shown += 1
        if shown:
            self.status.emit(RESTORED_TEXT, False)
        self.kept_changed.emit(self.kept_text())


__all__ = ["KEPT_TEXT", "LiveTextureKeeper", "NOT_KEPT_TEXT"]
