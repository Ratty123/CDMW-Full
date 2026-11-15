"""Mesh Editor live texture edits written into Build Mod (step 8, stage 4).

A texture edited from the Mesh Editor's Textures panel is written back in the
original's DDS format, colour space, size and mip chain, at its own game path,
in the same mod as the mesh. A texture the edit left as it was is never
written. The plan (which file, which format) is made before the Build Mod
dialog opens so the dialog can show it; the encode runs on the build worker.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cdmw.domain.archives.filters import active_archive_entry_for_virtual_path
from cdmw.domain.archives.mutation import ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.textures.original_output import (
    OriginalTextureOutput,
    TextureOutputRefused,
    check_texture_editable,
)
from cdmw.models import ArchiveEntry

ENCODE_DIRNAME = "texture_encode"


@dataclass(frozen=True, slots=True)
class LiveTextureOutput:
    """One edited texture and how it is written into the mod."""

    entry: ArchiveEntry
    game_path: str
    original: OriginalTextureOutput
    rgba: np.ndarray
    users: tuple[str, ...] = ()

    @property
    def plan_line(self) -> str:
        line = (f"{self.game_path}: {self.original.dds_format}, {self.original.width} x {self.original.height}, "
                f"{self.original.mip_count} mips")
        if len(self.users) > 1:
            line += " (shared by " + ", ".join(self.users) + ")"
        return line


@dataclass(frozen=True, slots=True)
class LiveTextureEdit:
    """What the Mesh Editor knows about one edited texture."""

    source_sha256: str
    game_path: str
    original_path: str
    rgba: np.ndarray
    users: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LiveTexturePlan:
    outputs: tuple[LiveTextureOutput, ...] = ()
    #: One sentence per edited texture that cannot be written, saying why.
    refusals: tuple[str, ...] = ()

    @property
    def plan_lines(self) -> tuple[str, ...]:
        return tuple(output.plan_line for output in self.outputs)


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def plan_live_texture_outputs(
    edits: Iterable[LiveTextureEdit],
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
) -> LiveTexturePlan:
    outputs: list[LiveTextureOutput] = []
    refusals: list[str] = []
    seen: set[str] = set()
    for edit in edits:
        key = _normalized(edit.game_path)
        if "/" not in key:
            refusals.append(f"{edit.game_path}: CDMW does not know which game file this texture came from, "
                            "so it cannot write it.")
            continue
        if key in seen:
            continue
        seen.add(key)
        entry = active_archive_entry_for_virtual_path(
            [item for item in entries_by_normalized_path.get(key, ()) if isinstance(item, ArchiveEntry)])
        if entry is None:
            refusals.append(f"{edit.game_path}: the game file was not found in the archives.")
            continue
        try:
            original = check_texture_editable(Path(edit.original_path))
        except TextureOutputRefused as exc:
            refusals.append(f"{edit.game_path}: {exc.reason}")
            continue
        rgba = np.asarray(edit.rgba)
        if rgba.ndim != 3 or (int(rgba.shape[1]), int(rgba.shape[0])) != (original.width, original.height):
            refusals.append(f"{edit.game_path}: the edit is not the original's size.")
            continue
        outputs.append(LiveTextureOutput(entry=entry, game_path=edit.game_path, original=original,
                                         rgba=rgba, users=tuple(edit.users)))
    return LiveTexturePlan(outputs=tuple(outputs), refusals=tuple(refusals))


def encode_live_texture_outputs(
    outputs: Sequence[LiveTextureOutput],
    work_root: Path,
    *,
    stop_event: threading.Event | None = None,
    encoder: Callable[..., object] | None = None,
) -> tuple[ArchivePatchRequest, ...]:
    """Encode each output beside the session (never in the system temp folder)."""

    if not outputs:
        return ()
    if encoder is None:
        from cdmw.services.texture_editor_service import TextureEditorNativeDdsService

        encoder = TextureEditorNativeDdsService().export_rgba_matching_original
    folder = Path(work_root) / ENCODE_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    requests = []
    try:
        for index, output in enumerate(outputs):
            raise_if_cancelled(stop_event, "Mesh output cancelled")
            target = folder / f"texture-{index}.dds"
            encoder(output.rgba, output.original, target, temp_root=folder)
            requests.append(ArchivePatchRequest(output.entry, target.read_bytes()))
    finally:
        for path in folder.glob("texture-*.dds"):
            path.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
    return tuple(requests)


def live_texture_metadata(outputs: Sequence[LiveTextureOutput]) -> list[dict[str, object]]:
    return [
        {"path": output.game_path, "format": output.original.dds_format, "width": output.original.width,
         "height": output.original.height, "mip_count": output.original.mip_count,
         "srgb": output.original.srgb, "parts": list(output.users)}
        for output in outputs
    ]


__all__ = [
    "LiveTextureEdit",
    "LiveTextureOutput",
    "LiveTexturePlan",
    "encode_live_texture_outputs",
    "live_texture_metadata",
    "plan_live_texture_outputs",
]
