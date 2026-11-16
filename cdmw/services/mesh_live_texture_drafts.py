"""Texture edits made live in the Mesh Editor, kept in the document's draft (step 8, item 3).

Each edited texture is kept as a one-layer Texture Editor project in the draft folder's
``textures/`` (the store of :mod:`cdmw.services.mesh_draft_textures`), so it survives a
restart, Duplicate copies it and Delete removes it with the draft. The edit is the
flattened image the Mesh Editor shows; its layers and history in the Texture Editor are
not kept, so undo after a restart starts from the saved image.

Keys: ``resource_id`` is the live key, the SHA-256 of the texture file the editor loaded
(it stays the same while the game's copy is unchanged); ``channel`` is the texture's role.
``source_sha256`` is the game copy's own digest when it is known, so a game update that
replaced the texture is said plainly on restore. Every live edit is written at its game
path (that is what the live flow's Build Mod does), so ``in_place`` records exactly that.

These functions read and write files: call them on a worker thread.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, Tuple

import numpy as np

from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.mesh_draft_textures import (
    DraftTexture,
    load_draft_textures,
    remove_draft_texture,
    save_draft_texture,
)


@dataclass(frozen=True, slots=True)
class LiveDraftEdit:
    """One edited texture to keep: its live key, role, game path and the edited pixels."""

    live_key: str
    role: str
    game_path: str
    rgba: np.ndarray
    original_format: str = ""
    game_sha256: str = ""


@dataclass(frozen=True, slots=True)
class RestoredLiveEdit:
    """A kept edit read back: its pixels, or why it could not be read."""

    live_key: str
    role: str
    game_path: str
    rgba: np.ndarray | None
    problem: str = ""


def _document_for(edit: LiveDraftEdit) -> tuple[TextureEditorDocument, dict[str, np.ndarray]]:
    rgba = np.ascontiguousarray(edit.rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"The edit of {edit.game_path} is not an RGBA image.")
    height, width = rgba.shape[:2]
    layer = TextureEditorLayer(layer_id=uuid.uuid4().hex, name="Edited texture",
                               relative_png_path="layers/edited.png")
    document = TextureEditorDocument(title=Path(edit.game_path).stem or "texture", width=int(width),
                                     height=int(height), active_layer_id=layer.layer_id, layers=(layer,))
    return document, {layer.layer_id: rgba}


def save_live_edits(draft_root: Path, edits: Iterable[LiveDraftEdit]) -> Tuple[str, ...]:
    """Keep ``edits`` in the draft; returns the live keys saved. One that fails costs that
    texture only and raises after the others were saved."""

    saved, failures = [], []
    for edit in edits:
        try:
            document, pixels = _document_for(edit)
            save_draft_texture(Path(draft_root), DraftTexture(
                resource_id=edit.live_key, channel=edit.role or "base",
                source_path=edit.game_path, output_path=edit.game_path, in_place=True,
                original_format=edit.original_format, source_sha256=edit.game_sha256,
                source_width=int(edit.rgba.shape[1]), source_height=int(edit.rgba.shape[0]),
            ), document, pixels)
            saved.append(edit.live_key)
        except (OSError, ValueError) as exc:
            failures.append(f"{edit.game_path}: {exc}")
    if failures:
        raise OSError("Some texture edits could not be kept in the draft: " + "; ".join(failures))
    return tuple(saved)


def forget_live_edits(draft_root: Path, keys: Iterable[tuple[str, str]]) -> None:
    """Remove kept edits (live key, role) that were undone back to the original."""

    for live_key, role in keys:
        remove_draft_texture(Path(draft_root), live_key, role or "base")


def restore_live_edits(draft_root: Path) -> Sequence[RestoredLiveEdit]:
    """Every edit kept in the draft, flattened back to the image the editor showed."""

    restored = []
    for loaded in load_draft_textures(Path(draft_root)):
        texture = loaded.texture
        pixels = None
        problem = loaded.problem
        if loaded.document is not None and not problem:
            layers = [layer for layer in loaded.document.layers if layer.visible]
            if len(layers) != 1 or layers[0].layer_id not in loaded.layer_pixels:
                problem = (f"The kept edit of {texture.source_path} has {len(layers)} visible layers; only a "
                           "one-layer edit made in the Mesh Editor can be shown again.")
            else:
                pixels = np.ascontiguousarray(loaded.layer_pixels[layers[0].layer_id], dtype=np.uint8)
        restored.append(RestoredLiveEdit(live_key=texture.resource_id, role=texture.channel,
                                         game_path=texture.source_path, rgba=pixels, problem=problem))
    return tuple(restored)


__all__ = ["LiveDraftEdit", "RestoredLiveEdit", "forget_live_edits", "restore_live_edits", "save_live_edits"]
