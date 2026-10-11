"""Shared, disk-backed profile history; memory use is independent of file size."""

from __future__ import annotations

import hashlib
import io
import tempfile
import threading
import weakref
from contextlib import contextmanager
from typing import BinaryIO

from cdmw.core.streaming_json import write_json


_CHUNK_BYTES = 1024 * 1024
_INLINE_BYTES = 64 * 1024
_blobs: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_blobs_lock = threading.Lock()


class MorphProfileFile:
    __slots__ = ("_stream", "_lock", "size", "sha256", "__weakref__")

    def __init__(self, stream: BinaryIO, size: int, sha256: bytes):
        self._stream = stream
        self._lock = threading.Lock()
        self.size = size
        self.sha256 = sha256

    def __len__(self):
        return self.size

    def __eq__(self, other):
        if isinstance(other, MorphProfileFile):
            return self.size == other.size and self.sha256 == other.sha256
        if isinstance(other, bytes):
            return self.size == len(other) and self.sha256 == hashlib.sha256(other).digest()
        return NotImplemented

    def chunks(self):
        # Anonymous temporary files close/delete when the last shared snapshot
        # reference is released, including rollback, discarded redo and shutdown.
        with self._lock:
            self._stream.seek(0)
            digest = hashlib.sha256()
            size = 0
            while chunk := self._stream.read(_CHUNK_BYTES):
                size += len(chunk)
                digest.update(chunk)
                yield chunk
            if size != self.size or digest.digest() != self.sha256:
                raise RuntimeError("Mesh morph profile history data changed")


ProfileFileData = bytes | MorphProfileFile


def capture_profile_json(value: object) -> ProfileFileData:
    """Stage comparison/preflight data without assembling a giant JSON string."""
    with tempfile.TemporaryFile(prefix="cdmw_morph_json_") as stream:
        text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
        try:
            write_json(text, value)
            text.flush()
        finally:
            text.detach()
        stream.seek(0)
        return capture_profile_file(stream)


def capture_profile_file(stream: BinaryIO) -> ProfileFileData:
    first = stream.read(_INLINE_BYTES + 1)
    if len(first) <= _INLINE_BYTES:
        return first
    snapshot = tempfile.TemporaryFile(prefix="cdmw_morph_history_")
    try:
        digest = hashlib.sha256()
        size = 0
        chunk = first
        while chunk:
            snapshot.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            chunk = stream.read(_CHUNK_BYTES)
        snapshot.flush()
        key = (size, digest.digest())
        with _blobs_lock:
            existing = _blobs.get(key)
            if existing is not None:
                snapshot.close()
                return existing
            result = MorphProfileFile(snapshot, *key)
            _blobs[key] = result
            return result
    except BaseException:
        snapshot.close()
        raise


def profile_file_chunks(data: ProfileFileData):
    if isinstance(data, MorphProfileFile):
        yield from data.chunks()
    elif isinstance(data, bytes):
        for start in range(0, len(data), _CHUNK_BYTES):
            yield data[start:start + _CHUNK_BYTES]
    else:
        raise RuntimeError("Mesh morph profile history contains invalid file data")


def write_profile_file(stream: BinaryIO, data: ProfileFileData) -> None:
    for chunk in profile_file_chunks(data):
        stream.write(chunk)


class _ProfileReader(io.RawIOBase):
    def __init__(self, data):
        super().__init__()
        self.chunks = iter(profile_file_chunks(data))
        self.pending = memoryview(b"")

    def readable(self):
        return True

    def readinto(self, buffer):
        if not self.pending:
            self.pending = memoryview(next(self.chunks, b""))
        count = min(len(buffer), len(self.pending))
        buffer[:count] = self.pending[:count]
        self.pending = self.pending[count:]
        return count

    def close(self):
        self.chunks.close()
        super().close()


@contextmanager
def profile_file_text(data: ProfileFileData):
    with io.TextIOWrapper(io.BufferedReader(_ProfileReader(data)), encoding="utf-8-sig") as stream:
        yield stream
