"""A Mesh Editor draft's texture work, kept so it survives a restart (decision 48, P6).

A draft holds one Texture Editor project (layers and masks, the existing project
format) per edited texture, beside the draft's mesh layers, plus a small manifest that
says which mesh texture each project belongs to. Undo across a restart is one step per
Finish, as for mesh steps (decision 38): the in-memory history is not saved.

Layout inside the draft folder (the folder that holds mesh_layers.json):

    textures/manifest.json
    textures/<key>/<key>.json   and its <key>_assets/ folder (save_texture_editor_project)
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from cdmw.models import TextureEditorDocument

MANIFEST_VERSION = 1
TEXTURES_FOLDER = "textures"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class DraftTexture:
    """Which mesh texture a saved project belongs to, and where its edit goes."""

    resource_id: str
    channel: str
    #: The game path the texture was read from.
    source_path: str
    #: Where the edited texture is written in the mod: the source path, or a Make unique copy.
    output_path: str
    parts: Tuple[str, ...] = ()
    affected_submeshes: Tuple[int, ...] = ()
    #: The original's format, for the matching output (cdmw.domain.textures.original_output).
    original_format: str = ""
    #: The material file a Make unique rewrote, when it did (its rewritten bytes are the draft's companion).
    sidecar_path: str = ""
    #: The game copy the edit started from (M8): its SHA-256 and size. A restore or Build Mod
    #: compares them with the game's current copy (`source_changed`) and says so plainly.
    source_sha256: str = ""
    source_width: int = 0
    source_height: int = 0
    #: The draft's Finish step that saved this texture; undo across a restart is per Finish.
    finish_generation: int = 0

    @property
    def key(self) -> str:
        return draft_texture_key(self.resource_id, self.channel)


@dataclass(frozen=True, slots=True)
class LoadedDraftTexture:
    texture: DraftTexture
    document: Optional[TextureEditorDocument]
    layer_pixels: Dict[str, np.ndarray] = field(default_factory=dict)
    #: Why the project could not be read back ("" when it was).
    problem: str = ""


def source_changed(texture: "DraftTexture", current_dds: bytes, *, width: int = 0, height: int = 0) -> str:
    """Why the saved edit no longer fits the game's copy of its source ("" when it still does).

    A game patch that replaced the texture, or changed its size, is said in so many words
    instead of surfacing later as a size error at Build Mod (M8 of the review).
    """
    if texture.source_sha256 and hashlib.sha256(bytes(current_dds)).hexdigest() != texture.source_sha256:
        if texture.source_width and width and (width, height) != (texture.source_width, texture.source_height):
            return (f"The game's {texture.source_path} is now {width}x{height}; the saved edit was made on "
                    f"{texture.source_width}x{texture.source_height}. Start the edit again from the new texture.")
        return (f"The game's {texture.source_path} changed since this edit was saved (a game update?). "
                "Start the edit again from the new texture.")
    return ""


def draft_texture_key(resource_id: str, channel: str) -> str:
    raw = f"{str(resource_id).strip().casefold()}:{str(channel or 'base').strip().casefold()}"
    readable = re.sub(r"[^a-z0-9_-]+", "-", raw)[:40].strip("-") or "texture"
    return f"{readable}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:10]}"


_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _draft_lock(draft_root: Path) -> threading.Lock:
    """One lock per draft folder: saves and removals rewrite the manifest in turn (M7)."""
    key = str(Path(draft_root).expanduser().resolve()).casefold()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _root(draft_root: Path) -> Path:
    return Path(draft_root).expanduser().resolve() / TEXTURES_FOLDER


def _read_manifest(draft_root: Path) -> Dict[str, dict]:
    path = _root(draft_root) / MANIFEST_NAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or int(data.get("version", 0) or 0) > MANIFEST_VERSION:
        raise ValueError("This draft's texture list was saved by a newer CDMW.")
    rows = data.get("textures") or {}
    return {str(key): dict(value) for key, value in rows.items() if isinstance(value, dict)}


def _write_manifest(draft_root: Path, rows: Dict[str, dict]) -> None:
    from cdmw.core.atomic_file import atomic_write_bytes

    payload = {"version": MANIFEST_VERSION, "textures": {key: rows[key] for key in sorted(rows)}}
    root = _root(draft_root)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(root / MANIFEST_NAME, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _project_path(draft_root: Path, key: str) -> Path:
    return _root(draft_root) / key / f"{key}.json"


def save_draft_texture(draft_root: Path, texture: DraftTexture, document: TextureEditorDocument,
                       layer_pixels: Dict[str, np.ndarray]) -> Path:
    """Save one texture's project into the draft (on Finish), then list it in the manifest.

    The project is published before the manifest names it, so a crash in between leaves
    the previous state readable.
    """
    from cdmw.core.texture_editor_project_io import save_texture_editor_project

    key = texture.key
    project = _project_path(draft_root, key)
    with _draft_lock(draft_root):
        # Read the manifest first: a draft a newer CDMW wrote is refused before anything in
        # it changes, including this texture's project (M6 of the review).
        _read_manifest(draft_root)
        save_texture_editor_project(document, dict(layer_pixels), project)
        rows = _read_manifest(draft_root)
        row = asdict(texture)
        row["parts"] = list(texture.parts)
        row["affected_submeshes"] = list(texture.affected_submeshes)
        row["project"] = project.relative_to(_root(draft_root)).as_posix()
        rows[key] = row
        _write_manifest(draft_root, rows)
    return project


def remove_draft_texture(draft_root: Path, resource_id: str, channel: str) -> None:
    """Forget a texture's saved work (its edit was undone back to the original)."""
    import shutil

    key = draft_texture_key(resource_id, channel)
    with _draft_lock(draft_root):
        rows = _read_manifest(draft_root)
        if rows.pop(key, None) is not None:
            _write_manifest(draft_root, rows)
        folder = _root(draft_root) / key
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


def load_draft_textures(draft_root: Path) -> Tuple[LoadedDraftTexture, ...]:
    """Every saved texture of the draft, in key order.

    A project that cannot be read comes back with `problem` set and no document, so the
    draft still opens and the panel can say which texture was lost; nothing is guessed.
    """
    from cdmw.core.texture_editor_project_io import load_texture_editor_project

    loaded = []
    for key, row in sorted(_read_manifest(draft_root).items()):
        try:
            texture = DraftTexture(
                resource_id=str(row.get("resource_id", "")), channel=str(row.get("channel", "base")),
                source_path=str(row.get("source_path", "")), output_path=str(row.get("output_path", "")),
                parts=tuple(str(part) for part in row.get("parts", ()) or ()),
                affected_submeshes=tuple(int(index) for index in row.get("affected_submeshes", ()) or ()),
                original_format=str(row.get("original_format", "")), sidecar_path=str(row.get("sidecar_path", "")),
                source_sha256=str(row.get("source_sha256", "") or ""),
                source_width=int(row.get("source_width", 0) or 0), source_height=int(row.get("source_height", 0) or 0),
                finish_generation=int(row.get("finish_generation", 0) or 0))
        except (TypeError, ValueError) as exc:
            # One bad row costs that texture only; the rest of the draft still opens.
            loaded.append(LoadedDraftTexture(DraftTexture(resource_id=key, channel="", source_path=key, output_path=""),
                                             None, {}, f"A saved texture entry could not be read: {exc}"))
            continue
        project = _root(draft_root) / str(row.get("project") or f"{key}/{key}.json")
        try:
            if not project.resolve().is_relative_to(_root(draft_root)):
                raise ValueError("its project is outside the draft")
            document, pixels, _floating = load_texture_editor_project(project)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            loaded.append(LoadedDraftTexture(texture, None, {}, f"The saved edit of {texture.source_path} could not be read: {exc}"))
            continue
        loaded.append(LoadedDraftTexture(texture, document, pixels))
    return tuple(loaded)


__all__ = [
    "DraftTexture",
    "LoadedDraftTexture",
    "draft_texture_key",
    "load_draft_textures",
    "remove_draft_texture",
    "source_changed",
    "save_draft_texture",
]
