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
    #: The edit may be written at the source's own path: `TextureSharing.in_place` said so when
    #: the edit started. Without it an output at the source path is refused, so a caller that
    #: checked only `needs_unique` (False also while sharing is not known) cannot write a
    #: shared texture in place. Use `DraftTexture.for_sharing` to set it from the decision.
    in_place: bool = False

    def __post_init__(self) -> None:
        if not self.in_place and self.output_path and _same_path(self.output_path, self.source_path):
            raise ValueError(f"{self.source_path} is not known to be this model's own, so the edit cannot be "
                             "written at its own path. Make it unique first.")

    @classmethod
    def for_sharing(cls, sharing, **values) -> "DraftTexture":
        """A draft texture whose `in_place` is the sharing decision's (`cdmw.services.model_textures`)."""
        return cls(in_place=bool(getattr(sharing, "in_place", False)), **values)

    @property
    def key(self) -> str:
        return draft_texture_key(self.resource_id, self.channel)


def _same_path(first: str, second: str) -> bool:
    def fold(value: str) -> str:
        text = str(value or "").strip().replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        return text.strip("/").casefold()
    return fold(first) == fold(second)


def draft_texture_write_path(texture: "DraftTexture") -> str:
    """Where Build Mod writes the edited texture: the one route, checked again at write time.

    Refuses an output at the source's own path unless the texture was saved as `in_place`,
    and an empty output path.
    """
    if not texture.output_path:
        raise ValueError(f"The edit of {texture.source_path} has no output path.")
    if _same_path(texture.output_path, texture.source_path) and not texture.in_place:
        raise ValueError(f"{texture.source_path} is not known to be this model's own, so the edit cannot be "
                         "written at its own path. Make it unique first.")
    return texture.output_path


@dataclass(frozen=True, slots=True)
class LoadedDraftTexture:
    texture: DraftTexture
    document: Optional[TextureEditorDocument]
    layer_pixels: Dict[str, np.ndarray] = field(default_factory=dict)
    #: Why the project could not be read back ("" when it was).
    problem: str = ""
    #: The row names the source's own path as its output but not that it may be written
    #: there (`in_place`): the edit is kept and the sharing decision is asked again.
    needs_sharing: bool = False


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


def _restore_project_backup(project: Path, load):
    """Put back the previous save of a project a crash left half published, or None.

    ``save_texture_editor_project`` copies the project to ``.<name>.<id>.backup`` and moves
    the assets folder to ``.<name>_assets.<id>.backup`` before it moves the new ones in. A
    crash between its two moves leaves the old project beside the new assets, which does not
    load. A backup is complete when both of its halves are there; the newest complete one is
    restored, and kept until the restored project loads. If that fails too, everything is
    put back as it was found and None is returned.
    """
    import os
    import shutil

    from cdmw.core.texture_editor_project_io import _texture_editor_assets_dir

    folder, assets = project.parent, _texture_editor_assets_dir(project)
    prefix = f".{project.name}."
    backups = sorted((path for path in folder.glob(f"{prefix}*.backup") if path.is_file()),
                     key=lambda path: path.stat().st_mtime, reverse=True)
    for backup in backups:
        transaction = backup.name[len(prefix):-len(".backup")]
        assets_backup = folder / f".{assets.name}.{transaction}.backup"
        if not assets_backup.is_dir():
            continue  # half a backup: not enough to restore from
        aside_project = folder / f".{project.name}.{transaction}.failed"
        aside_assets = folder / f".{assets.name}.{transaction}.failed"
        moved_project = moved_assets = restored_assets = False
        try:
            if project.exists():
                os.replace(project, aside_project)
                moved_project = True
            if assets.exists():
                os.replace(assets, aside_assets)
                moved_assets = True
            os.replace(assets_backup, assets)
            restored_assets = True
            shutil.copy2(backup, project)
            document, pixels, _floating = load(project)
        except (OSError, ValueError, KeyError, TypeError):
            # Put it all back as it was found; the next backup, if any, is tried.
            try:
                project.unlink(missing_ok=True)
                if restored_assets:
                    os.replace(assets, assets_backup)
                if moved_assets:
                    os.replace(aside_assets, assets)
                if moved_project:
                    os.replace(aside_project, project)
            except OSError:
                return None
            continue
        for leftover in (backup, aside_project):
            leftover.unlink(missing_ok=True)
        shutil.rmtree(aside_assets, ignore_errors=True)
        return document, pixels
    return None


def load_draft_textures(draft_root: Path) -> Tuple[LoadedDraftTexture, ...]:
    """Every saved texture of the draft, in key order.

    A project that cannot be read comes back with `problem` set and no document, so the
    draft still opens and the panel can say which texture was lost; nothing is guessed.
    """
    from cdmw.core.texture_editor_project_io import load_texture_editor_project

    loaded = []
    for key, row in sorted(_read_manifest(draft_root).items()):
        source_path, output_path = str(row.get("source_path", "")), str(row.get("output_path", ""))
        in_place = row.get("in_place", False) is True
        # No in_place for an output at the source's own path: not lost, only unsettled.
        needs_sharing = bool(output_path) and not in_place and _same_path(output_path, source_path)
        try:
            texture = DraftTexture(
                resource_id=str(row.get("resource_id", "")), channel=str(row.get("channel", "base")),
                source_path=source_path, output_path="" if needs_sharing else output_path,
                parts=tuple(str(part) for part in row.get("parts", ()) or ()),
                affected_submeshes=tuple(int(index) for index in row.get("affected_submeshes", ()) or ()),
                original_format=str(row.get("original_format", "")), sidecar_path=str(row.get("sidecar_path", "")),
                source_sha256=str(row.get("source_sha256", "") or ""),
                source_width=int(row.get("source_width", 0) or 0), source_height=int(row.get("source_height", 0) or 0),
                finish_generation=int(row.get("finish_generation", 0) or 0),
                in_place=in_place)
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
            with _draft_lock(draft_root):  # a save of the same draft must not run while files move
                restored = _restore_project_backup(project, load_texture_editor_project)
            if restored is not None:
                document, pixels = restored
                loaded.append(LoadedDraftTexture(texture, document, pixels,
                                                 f"The saved edit of {texture.source_path} was incomplete (CDMW may "
                                                 "have closed while saving), so its previous save was restored."))
                continue
            loaded.append(LoadedDraftTexture(texture, None, {}, f"The saved edit of {texture.source_path} could not be read: {exc}"))
            continue
        if needs_sharing:
            loaded.append(LoadedDraftTexture(
                texture, document, pixels,
                f"Whether {source_path} is only this model's is not saved with its edit, so CDMW asks again "
                "before the edit is written.", needs_sharing=True))
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
