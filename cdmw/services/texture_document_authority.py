"""One authority for an edited texture's pixels (decision 48, P6).

Each texture being edited for a Mesh Editor session has exactly one document: its
layers, masks and pixels live here and nowhere else. The mesh session's texture store
(`MeshService.commit_texture_snapshot` / `commit_texture_region`, which Build Mod and
mesh undo read) is a derived copy: this authority writes the flattened result into it
after each finished stroke, and nothing else edits it. The app's Texture Editor and the
docked one look a document up here; a second widget never gets a second copy.

The review of the first version (REPORT-review.md, M2 to M5) set four rules kept here:
- a document is held by the token `open` returns, not by its owner's label (M3);
- keys match whatever the case or separators, while the store is always given the
  spelling the document was opened with (M4);
- what is written is what changed, found by comparing the flattened result with the last
  one written, not the caller's rectangle (M5);
- every write, whole or partial, checks the store's revision; a store changed by
  anything else (a mesh Undo, a second writer) is reported as stale, and the document is
  reloaded from the store before it is written again (M2).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from cdmw.models import TextureEditorDocument


def _fold(resource_id: str) -> str:
    return str(resource_id or "").strip().replace("\\", "/").casefold()


@dataclass(frozen=True, slots=True, eq=False)
class TextureDocumentKey:
    session_id: str
    #: As the mesh session spells it; matching ignores case and separators.
    resource_id: str
    channel: str = "base"

    @classmethod
    def of(cls, session_id: str, resource_id: str, channel: str = "base") -> "TextureDocumentKey":
        return cls(str(session_id or "").strip(), str(resource_id or "").strip(),
                   str(channel or "base").strip().lower() or "base")

    def _match(self) -> tuple[str, str, str]:
        return (self.session_id, _fold(self.resource_id), self.channel)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TextureDocumentKey) and self._match() == other._match()

    def __hash__(self) -> int:
        return hash(self._match())


class TextureDocumentOpenElsewhere(RuntimeError):
    """The document is held by another widget; `owner` says which, so the caller can focus it."""

    def __init__(self, key: TextureDocumentKey, owner: str) -> None:
        super().__init__(f"This texture is already open in {owner}.")
        self.key = key
        self.owner = owner


class TextureDocumentStale(RuntimeError):
    """The mesh store changed under the document (a mesh Undo or another writer)."""

    def __init__(self, key: TextureDocumentKey) -> None:
        super().__init__("This texture changed outside the editor (for example by Undo). "
                         "It is reloaded before the next change is written.")
        self.key = key


class TextureDocumentUnreadable(ValueError):
    """The store's copy of this texture cannot be read back; only this texture is affected."""

    def __init__(self, key: TextureDocumentKey, reason: str) -> None:
        super().__init__(f"{key.resource_id} could not be reloaded: {reason}. "
                         "Close this texture and open it again from the model.")
        self.key = key
        self.reason = reason


@dataclass(slots=True)
class TextureDocumentEntry:
    key: TextureDocumentKey
    owner: str
    #: Held by whoever opened it; commit and close need it (M3).
    token: str
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    #: The parts the mesh session marks as affected by this texture.
    affected_submeshes: Tuple[int, ...] = ()
    logical_path: str = ""
    #: The store's revision as this document last saw it (None: the store has no copy yet).
    mesh_revision: Optional[int] = None
    #: The last flattened pixels written, to find what a commit changed (M5).
    written: Optional[np.ndarray] = None
    revision: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def flattened_bgra(document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray]) -> np.ndarray:
    """The document as the mesh store holds it: tight BGRA, height x width x 4."""
    from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers

    rgba = np.ascontiguousarray(flatten_texture_editor_layers(document, dict(layer_pixels)), dtype=np.uint8)
    return np.ascontiguousarray(rgba[..., [2, 1, 0, 3]])


def _changed_rect(before: np.ndarray, after: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """The bounding box (x, y, w, h) of the pixels that differ, or None when none do."""
    changed = np.any(before != after, axis=2)
    rows = np.flatnonzero(changed.any(axis=1))
    if rows.size == 0:
        return None
    columns = np.flatnonzero(changed.any(axis=0))
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(columns[0]), int(columns[-1]) + 1
    return x0, y0, x1 - x0, y1 - y0


class TextureDocumentAuthority:
    """Documents by (session, resource, channel), and the one route into the mesh store."""

    def __init__(self, mesh_service) -> None:
        self._mesh = mesh_service
        self._entries: Dict[TextureDocumentKey, TextureDocumentEntry] = {}
        self._lock = threading.Lock()

    # ----- the store ---------------------------------------------------------------
    def _store(self, key: TextureDocumentKey):
        """The store's committed resource for `key` (the mesh service's own record), or None."""
        session = getattr(self._mesh, "_session", None)
        if session is None:
            return None
        resources = getattr(session(key.session_id), "committed_texture_resources", {}) or {}
        exact = resources.get((key.resource_id, key.channel))
        if exact is not None:
            return exact
        return next((resource for (resource_id, channel), resource in resources.items()
                     if channel == key.channel and _fold(resource_id) == _fold(key.resource_id)), None)

    def _store_revision(self, key: TextureDocumentKey) -> Optional[int]:
        resource = self._store(key)
        return None if resource is None else int(resource.revision)

    # ----- documents -------------------------------------------------------------------
    def open(self, key: TextureDocumentKey, document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray], *,
             owner: str, affected_submeshes=(), logical_path: str = "", token: str = "") -> TextureDocumentEntry:
        """Register a document and return its entry, whose ``token`` the caller keeps.

        Opening a key that is already open is refused (naming the widget that holds it),
        unless the caller passes that entry's token, which gives the same entry back.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if not token or token != entry.token:
                    raise TextureDocumentOpenElsewhere(key, entry.owner)
                return entry
            entry = TextureDocumentEntry(key, str(owner or "another editor"), uuid.uuid4().hex, document,
                                         dict(layer_pixels), tuple(int(i) for i in affected_submeshes),
                                         str(logical_path or ""), mesh_revision=self._store_revision(key))
            self._entries[key] = entry
            return entry

    def get(self, key: TextureDocumentKey) -> Optional[TextureDocumentEntry]:
        with self._lock:
            return self._entries.get(key)

    def owner_of(self, key: TextureDocumentKey) -> str:
        entry = self.get(key)
        return entry.owner if entry is not None else ""

    def _held(self, key: TextureDocumentKey, token: str) -> TextureDocumentEntry:
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            raise KeyError(f"No open texture document for {key.resource_id}:{key.channel}")
        if token != entry.token:
            raise TextureDocumentOpenElsewhere(key, entry.owner)
        return entry

    def close(self, key: TextureDocumentKey, *, token: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if token != entry.token:
                raise TextureDocumentOpenElsewhere(key, entry.owner)
            del self._entries[key]

    def close_session(self, session_id: str) -> None:
        """The Mesh Editor session closed: its documents go with it."""
        with self._lock:
            for key in [key for key in self._entries if key.session_id == session_id]:
                del self._entries[key]

    # ----- writing -----------------------------------------------------------------------
    def commit(self, key: TextureDocumentKey, document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray], *,
               token: str, rect: Optional[Tuple[int, int, int, int]] = None) -> int:
        """An edit finished: keep the new document and update the mesh store.

        Writes the pixels that changed since the last write (all of them the first time and
        after a resize); `rect` is accepted for callers that have one and is not trusted.
        Raises TextureDocumentStale when the store changed under the document. Returns the
        store's revision.
        """
        del rect  # what changed is measured, not taken from the caller (M5)
        entry = self._held(key, token)
        with entry._lock:
            current = self._store_revision(key)
            if current != entry.mesh_revision:
                raise TextureDocumentStale(key)
            bgra = flattened_bgra(document, layer_pixels)
            height, width = bgra.shape[:2]
            store_id = self._store_id(key)
            previous = entry.written
            # Both writes carry the revision this document last saw (0: no copy yet), so a writer
            # landing between the check above and the write is refused, not overwritten.
            expected = 0 if entry.mesh_revision is None else int(entry.mesh_revision)
            try:
                if previous is None or previous.shape != bgra.shape:
                    revision = self._mesh.commit_texture_snapshot(
                        key.session_id, store_id, channel=key.channel, affected_submeshes=entry.affected_submeshes,
                        width=width, height=height, row_pitch=width * 4, bgra=bgra.tobytes(),
                        logical_path=entry.logical_path, expected_revision=expected)
                else:
                    changed = _changed_rect(previous, bgra)
                    if changed is None:
                        entry.document, entry.layer_pixels = document, dict(layer_pixels)
                        return int(entry.mesh_revision)
                    x, y, w, h = changed
                    region = np.ascontiguousarray(bgra[y:y + h, x:x + w])
                    revision = self._mesh.commit_texture_region(
                        key.session_id, store_id, channel=key.channel, affected_submeshes=entry.affected_submeshes,
                        rect=(x, y, w, h), row_pitch=w * 4, bgra=region.tobytes(), expected_revision=expected)
            except RuntimeError as exc:
                if "stale resident texture revision" in str(exc):
                    raise TextureDocumentStale(key) from exc
                raise
            entry.document = document
            entry.layer_pixels = dict(layer_pixels)
            entry.mesh_revision = int(revision)
            entry.written = bgra
            entry.revision += 1
            return int(revision)

    def _store_id(self, key: TextureDocumentKey) -> str:
        """The resource id as the store spells it, when it has one; else the key's own."""
        resource = self._store(key)
        return str(getattr(resource, "resource_id", "") or key.resource_id)

    def reload_from_store(self, key: TextureDocumentKey, *, token: str) -> Optional[np.ndarray]:
        """After TextureDocumentStale: the store's pixels (BGRA, height x width x 4), which the
        caller makes the document again (``adopt``). None when the store holds no copy."""
        entry = self._held(key, token)
        with entry._lock:
            resource = self._store(key)
            if resource is None or not getattr(resource, "raw_bgra_path", ""):
                entry.mesh_revision, entry.written = None, None
                return None
            from pathlib import Path

            width, height, pitch = int(resource.width), int(resource.height), int(resource.row_pitch)
            try:
                data = Path(resource.raw_bgra_path).read_bytes()
            except OSError as exc:
                raise TextureDocumentUnreadable(key, f"its working copy cannot be read ({exc.strerror or exc})") from exc
            if pitch < width * 4 or len(data) < pitch * height:
                # A truncated working copy costs this texture only: the document and the store
                # stay as they were, and the caller shows the reason for this texture.
                raise TextureDocumentUnreadable(
                    key, f"its working copy holds {len(data):,} bytes; {width}x{height} needs {pitch * height:,}")
            rows = np.frombuffer(data, dtype=np.uint8)[: pitch * height].reshape(height, pitch)
            bgra = np.ascontiguousarray(rows[:, : width * 4].reshape(height, width, 4))
            entry.mesh_revision = int(resource.revision)
            entry.written = bgra
            return bgra.copy()

    def adopt(self, key: TextureDocumentKey, document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray], *,
              token: str) -> None:
        """Make `document` the entry's document without writing it (after a reload)."""
        entry = self._held(key, token)
        with entry._lock:
            entry.document, entry.layer_pixels = document, dict(layer_pixels)


__all__ = [
    "TextureDocumentAuthority",
    "TextureDocumentEntry",
    "TextureDocumentKey",
    "TextureDocumentOpenElsewhere",
    "TextureDocumentStale",
    "TextureDocumentUnreadable",
    "flattened_bgra",
]
