"""One authority for an edited texture's pixels (decision 48, P6).

Each texture being edited for a Mesh Editor session has exactly one document: its
layers, masks and pixels live here and nowhere else. The mesh session's texture store
(`MeshService.commit_texture_snapshot` / `commit_texture_region`, which Build Mod and
mesh undo read) is a derived copy: this authority writes the flattened result into it
after each finished stroke, and nothing else edits it. The app's Texture Editor and the
docked one look a document up here; a second widget never gets a second copy.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from cdmw.models import TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureDocumentKey:
    session_id: str
    resource_id: str
    channel: str = "base"

    @classmethod
    def of(cls, session_id: str, resource_id: str, channel: str = "base") -> "TextureDocumentKey":
        return cls(str(session_id or "").strip(), str(resource_id or "").strip().casefold(),
                   str(channel or "base").strip().casefold() or "base")


class TextureDocumentOpenElsewhere(RuntimeError):
    """The document is open in another widget; `owner` says which, so the caller can focus it."""

    def __init__(self, key: TextureDocumentKey, owner: str) -> None:
        super().__init__(f"This texture is already open in {owner}.")
        self.key = key
        self.owner = owner


@dataclass(slots=True)
class TextureDocumentEntry:
    key: TextureDocumentKey
    owner: str
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    #: The parts the mesh session marks as affected by this texture.
    affected_submeshes: Tuple[int, ...] = ()
    logical_path: str = ""
    #: The mesh store's revision after the last commit (None before the first).
    mesh_revision: Optional[int] = None
    #: The size the mesh store holds; a different size is written whole.
    mesh_size: Optional[Tuple[int, int]] = None
    revision: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def flattened_bgra(document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray]) -> np.ndarray:
    """The document as the mesh store holds it: tight BGRA, height x width x 4."""
    from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers

    rgba = np.ascontiguousarray(flatten_texture_editor_layers(document, dict(layer_pixels)), dtype=np.uint8)
    return np.ascontiguousarray(rgba[..., [2, 1, 0, 3]])


class TextureDocumentAuthority:
    """Documents by (session, resource, channel), and the one route into the mesh store."""

    def __init__(self, mesh_service) -> None:
        self._mesh = mesh_service
        self._entries: Dict[TextureDocumentKey, TextureDocumentEntry] = {}
        self._lock = threading.Lock()

    def open(self, key: TextureDocumentKey, document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray], *,
             owner: str, affected_submeshes=(), logical_path: str = "") -> TextureDocumentEntry:
        """Register a document; the same owner reopening gets its entry back unchanged."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if entry.owner != owner:
                    raise TextureDocumentOpenElsewhere(key, entry.owner)
                return entry
            entry = TextureDocumentEntry(key, owner, document, dict(layer_pixels), tuple(int(i) for i in affected_submeshes),
                                         str(logical_path or ""))
            self._entries[key] = entry
            return entry

    def get(self, key: TextureDocumentKey) -> Optional[TextureDocumentEntry]:
        with self._lock:
            return self._entries.get(key)

    def owner_of(self, key: TextureDocumentKey) -> str:
        entry = self.get(key)
        return entry.owner if entry is not None else ""

    def close(self, key: TextureDocumentKey, *, owner: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.owner != owner:
                raise TextureDocumentOpenElsewhere(key, entry.owner)
            self._entries.pop(key, None)

    def close_session(self, session_id: str) -> None:
        """The Mesh Editor session closed: its documents go with it."""
        with self._lock:
            for key in [key for key in self._entries if key.session_id == session_id]:
                del self._entries[key]

    def commit(self, key: TextureDocumentKey, document: TextureEditorDocument, layer_pixels: Mapping[str, np.ndarray], *,
               owner: str, rect: Optional[Tuple[int, int, int, int]] = None) -> int:
        """A stroke (or any edit) finished: keep the new document and update the mesh store.

        The first commit writes the whole texture; later ones write `rect` (x, y, w, h)
        when given, else the whole texture again. Returns the mesh store's revision.
        """
        entry = self.get(key)
        if entry is None:
            raise KeyError(f"No open texture document for {key.resource_id}:{key.channel}")
        if entry.owner != owner:
            raise TextureDocumentOpenElsewhere(key, entry.owner)
        with entry._lock:
            bgra = flattened_bgra(document, layer_pixels)
            height, width = bgra.shape[:2]
            if entry.mesh_revision is None or rect is None or entry.mesh_size != (width, height):
                revision = self._mesh.commit_texture_snapshot(
                    key.session_id, key.resource_id, channel=key.channel, affected_submeshes=entry.affected_submeshes,
                    width=width, height=height, row_pitch=width * 4, bgra=bgra.tobytes(), logical_path=entry.logical_path)
            else:
                x, y, w, h = (int(value) for value in rect)
                x0, y0 = max(0, x), max(0, y)
                x1, y1 = min(width, x + w), min(height, y + h)
                if x1 <= x0 or y1 <= y0:
                    return int(entry.mesh_revision)
                region = np.ascontiguousarray(bgra[y0:y1, x0:x1])
                revision = self._mesh.commit_texture_region(
                    key.session_id, key.resource_id, channel=key.channel, affected_submeshes=entry.affected_submeshes,
                    rect=(x0, y0, x1 - x0, y1 - y0), row_pitch=(x1 - x0) * 4, bgra=region.tobytes(),
                    expected_revision=entry.mesh_revision)
            entry.document = document
            entry.layer_pixels = dict(layer_pixels)
            entry.mesh_revision = int(revision)
            entry.mesh_size = (width, height)
            entry.revision += 1
            return int(revision)


__all__ = [
    "TextureDocumentAuthority",
    "TextureDocumentEntry",
    "TextureDocumentKey",
    "TextureDocumentOpenElsewhere",
    "flattened_bgra",
]
