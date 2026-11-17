"""Edited textures shown live in the Mesh Editor's 3D view (step 8, stage 2).

CDMW writes the edited pixels as an uncompressed RGBA8 DDS inside the document's
session folder and sends the editor ``texture_update`` naming the texture by the
source hash it was first loaded with; the editor swaps that one texture and
answers ``texture_updated``. Per texture at most one update is in flight and the
latest edit wins, so painting never queues work behind itself. Files are written
on a worker, never on the UI thread. Edits made before the editor is ready wait
and go out when it is.

The edits belong to the document, not to one editor session: Finish closes the
session (and deletes its folder), and the edited textures stay for Build Mod and
are shown again when the document's next session is ready. Discard or closing
the document forgets them.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

#: Below the session folder; the editor accepts only plain names under it.
EDITS_DIRNAME = "texture_edits"

_DDSD_CAPS, _DDSD_HEIGHT, _DDSD_WIDTH, _DDSD_PITCH, _DDSD_PIXELFORMAT = 0x1, 0x2, 0x4, 0x8, 0x1000
_DDPF_ALPHAPIXELS, _DDPF_RGB = 0x1, 0x40
_DDSCAPS_TEXTURE = 0x1000


def rgba8_dds_bytes(width: int, height: int, rgba: bytes) -> bytes:
    """A single-mip, uncompressed R8G8B8A8 DDS with a legacy header."""

    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("RGBA8 pixels do not match the size")
    header = struct.pack(
        "<4s7I44x8I5I",
        b"DDS ",
        124,
        _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH | _DDSD_PITCH | _DDSD_PIXELFORMAT,
        height,
        width,
        width * 4,
        0,
        1,
        32,
        _DDPF_RGB | _DDPF_ALPHAPIXELS,
        0,
        32,
        0x000000FF,
        0x0000FF00,
        0x00FF0000,
        0xFF000000,
        _DDSCAPS_TEXTURE,
        0,
        0,
        0,
        0,
    )
    return header + bytes(rgba)


def image_rgba8(image: QImage) -> tuple[int, int, bytes]:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    stride = converted.bytesPerLine()
    data = bytes(converted.constBits())
    if stride == width * 4:
        return width, height, data[: width * height * 4]
    rows = (data[row * stride: row * stride + width * 4] for row in range(height))
    return width, height, b"".join(rows)


@dataclass
class _Texture:
    revision: int = 0
    pending: QImage | None = None
    in_flight: int = 0
    written: dict[int, Path] | None = None
    #: The texture as last edited, and whether it differs from the one it was opened from.
    latest: QImage | None = None
    changed: bool = False
    #: Edits made (re-showing one after a restart is not an edit), and the last one kept
    #: in the document's draft (item 3).
    edits: int = 0
    kept: int = 0


class _WriteSignals(QObject):
    written = Signal(str, int, str, str)


class _WriteJob(QRunnable):
    def __init__(self, image: QImage, target: Path, source_sha256: str, revision: int,
                 signals: _WriteSignals) -> None:
        super().__init__()
        self.image = image
        self.target = target
        self.source_sha256 = source_sha256
        self.revision = revision
        self.signals = signals

    def run(self) -> None:
        error = ""
        try:
            width, height, rgba = image_rgba8(self.image)
            self.target.parent.mkdir(exist_ok=True)  # never the session folder itself
            partial = self.target.with_suffix(".partial")
            partial.write_bytes(rgba8_dds_bytes(width, height, rgba))
            partial.replace(self.target)
        except (OSError, ValueError) as exc:
            error = str(exc)
        try:
            self.signals.written.emit(self.source_sha256, self.revision, str(self.target), error)
        except RuntimeError:
            pass  # the tab went away while the file was written


class LiveTextureUpdates(QObject):
    """One document's live texture edits, latest-wins per texture."""

    failed = Signal(str, str)
    """source_sha256 and why the editor could not show the edit."""

    def __init__(self, session_root: Callable[[], Path | None], send: Callable[[Mapping[str, object]], bool],
                 parent: QObject | None = None, *, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self._session_root = session_root
        self._send = send
        self._pool = pool or QThreadPool.globalInstance()
        self._textures: dict[str, _Texture] = {}
        self._signals = _WriteSignals()
        self._signals.written.connect(self._on_written)
        self._unsent: dict[str, tuple[int, str]] = {}
        #: What Build Mod needs about each opened texture, by source hash (stays after Finish).
        self.sources: dict[str, object] = {}

    def push(self, source_sha256: str, image: QImage, *, changed: bool = True) -> int:
        """Show ``image`` in place of the texture loaded with ``source_sha256``; the
        returned revision is the one its acknowledgement names. ``changed`` is False
        when the edit was undone back to the texture as it was opened."""

        key = str(source_sha256).lower()
        state = self._textures.setdefault(key, _Texture(written={}))
        state.revision += 1
        state.edits += 1
        state.pending = image.copy()
        state.latest = state.pending
        state.changed = bool(changed)
        if not state.in_flight:
            self._start(key, state)
        return state.revision

    def unkept(self) -> dict[str, tuple[int, QImage | None]]:
        """Edits not yet kept in the draft, by source hash: (edit count, image), the image
        None when the texture was undone back to the one it was opened from."""

        return {key: (state.edits, state.latest if state.changed else None)
                for key, state in self._textures.items() if state.edits != state.kept}

    def mark_kept(self, source_sha256: str, edits: int) -> None:
        """The draft now holds this texture as it was after ``edits`` edits."""

        state = self._textures.get(str(source_sha256).lower())
        if state is not None:
            state.kept = max(state.kept, int(edits))

    def flush(self) -> None:
        """Send what waited for the editor (it was not running or not ready)."""

        for key, (revision, path) in tuple(self._unsent.items()):
            if self._deliver(key, revision, path):
                del self._unsent[key]

    def acknowledge(self, payload: Mapping[str, object]) -> None:
        key = str(payload.get("source_sha256", "") or "").lower()
        state = self._textures.get(key)
        if state is None:
            return
        try:
            revision = int(payload.get("revision", 0) or 0)
        except (TypeError, ValueError):
            return
        if revision != state.in_flight:
            return
        state.in_flight = 0
        if not bool(payload.get("ok", False)):
            self.failed.emit(key, str(payload.get("error", "") or "The editor could not show the edit."))
        self._forget_older(state, keep=revision)
        if state.pending is not None:
            self._start(key, state)

    def edited_textures(self) -> dict[str, QImage]:
        """Every texture that differs from the one it was opened from, by source hash."""

        return {key: state.latest for key, state in self._textures.items()
                if state.changed and state.latest is not None}

    def remember_source(self, source_sha256: str, source: object) -> None:
        self.sources[str(source_sha256).lower()] = source

    def detach(self) -> None:
        """The editor session ended (Finish, a crash, a park): its folder and the files in
        it go with it, the edits stay and are shown again by ``reapply``."""

        for state in self._textures.values():
            state.in_flight = 0
            state.pending = None
            state.written = {}
        self._unsent.clear()

    def reapply(self) -> None:
        """A new editor session is ready: show every edited texture in it."""

        for key, state in self._textures.items():
            if state.changed and state.latest is not None and not state.in_flight:
                state.revision += 1
                state.pending = state.latest
                self._start(key, state)

    def clear(self) -> None:
        """Forget everything (Discard, or the document closed)."""

        self._textures.clear()
        self._unsent.clear()
        self.sources.clear()

    def _start(self, key: str, state: _Texture) -> None:
        root = self._session_root()
        # The session's folder is made by its preparation, which refuses one that already
        # exists; an edit restored from the draft before then waits (still pending) and is
        # shown by ``reapply`` when the editor is ready (B pass 12: the restore wrote first
        # and the session could not be prepared).
        if root is None or state.pending is None or not Path(root).is_dir():
            return
        image, state.pending = state.pending, None
        revision = state.revision
        state.in_flight = revision
        target = Path(root) / EDITS_DIRNAME / f"{key[:16]}-r{revision}.dds"
        self._pool.start(_WriteJob(image, target, key, revision, self._signals))

    def _on_written(self, key: str, revision: int, path: str, error: str) -> None:
        state = self._textures.get(key)
        if state is None or state.in_flight != revision:
            return
        if error:
            state.in_flight = 0
            self.failed.emit(key, error)
            if state.pending is not None:
                self._start(key, state)
            return
        assert state.written is not None
        state.written[revision] = Path(path)
        if not self._deliver(key, revision, path):
            self._unsent[key] = (revision, path)

    def _deliver(self, key: str, revision: int, path: str) -> bool:
        root = self._session_root()
        if root is None:
            return False
        try:
            relative = Path(path).relative_to(Path(root)).as_posix()
        except ValueError:
            return False
        return bool(self._send({"source_sha256": key, "file": relative, "revision": revision}))

    @staticmethod
    def _forget_older(state: _Texture, *, keep: int) -> None:
        assert state.written is not None
        for revision in [revision for revision in state.written if revision < keep]:
            try:
                state.written.pop(revision).unlink(missing_ok=True)
            except OSError:
                pass
