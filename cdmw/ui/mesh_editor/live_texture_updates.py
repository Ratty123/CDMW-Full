"""Edited textures shown live in the Mesh Editor's 3D view (step 8, stage 2).

CDMW writes the edited pixels as an uncompressed RGBA8 DDS inside the document's
session folder and sends the editor ``texture_update`` naming the texture by the
source hash it was first loaded with; the editor swaps that one texture and
answers ``texture_updated``. Per texture at most one update is in flight and the
latest edit wins, so painting never queues work behind itself. Files are written
on a worker, never on the UI thread. Edits made before the editor is ready wait
and go out when it is.
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
            self.target.parent.mkdir(parents=True, exist_ok=True)
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

    def push(self, source_sha256: str, image: QImage) -> int:
        """Show ``image`` in place of the texture loaded with ``source_sha256``; the
        returned revision is the one its acknowledgement names."""

        key = str(source_sha256).lower()
        state = self._textures.setdefault(key, _Texture(written={}))
        state.revision += 1
        state.pending = image.copy()
        if not state.in_flight:
            self._start(key, state)
        return state.revision

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

    def clear(self) -> None:
        """Forget everything; the session folder (and its edits) goes with the session."""

        self._textures.clear()
        self._unsent.clear()

    def _start(self, key: str, state: _Texture) -> None:
        root = self._session_root()
        if root is None or state.pending is None:
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
