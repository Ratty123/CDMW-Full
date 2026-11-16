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
    #: Other game files that use the texture, as the reference search found them.
    other_files: tuple[str, ...] = ()

    @property
    def plan_line(self) -> str:
        line = (f"{self.game_path}: {self.original.dds_format}, {self.original.width} x {self.original.height}, "
                f"{self.original.mip_count} mips")
        if len(self.users) > 1:
            line += " (shared by " + ", ".join(self.users) + ")"
        if self.other_files:
            from cdmw.ui.mesh_editor.shared_texture_check import joined_file_names

            line += " (also used by " + joined_file_names(self.other_files) + ")"
        return line


@dataclass(frozen=True, slots=True)
class LiveTextureSource:
    """An opened texture's game path, how it is written back and the parts that share it.

    Read when the texture is opened, so it outlives the editor session's folder."""

    game_path: str
    original: OriginalTextureOutput
    users: tuple[str, ...] = ()
    #: The texture's role in its material (base colour, normal...), the draft keeps it by.
    role: str = ""


@dataclass(frozen=True, slots=True)
class LiveTextureEdit:
    """What the Mesh Editor knows about one edited texture."""

    source_sha256: str
    game_path: str
    rgba: np.ndarray
    users: tuple[str, ...] = ()
    #: The original's output settings, or the file to read them from.
    original: OriginalTextureOutput | None = None
    original_path: str = ""
    other_files: tuple[str, ...] = ()


LEFT_OUT_TEXT = "{path}: left out, no part in this mod uses it ({parts})"


@dataclass(frozen=True, slots=True)
class LiveTexturePlan:
    outputs: tuple[LiveTextureOutput, ...] = ()
    #: One sentence per edited texture that cannot be written, saying why.
    refusals: tuple[str, ...] = ()
    #: One line per edited texture that is not written because no part in the build
    #: uses it any more (its parts were deleted or left out), as the native app says.
    left_out: tuple[str, ...] = ()

    @property
    def plan_lines(self) -> tuple[str, ...]:
        return tuple(output.plan_line for output in self.outputs) + self.left_out


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def _part_name(user: str) -> str:
    """A Textures panel heading without the file it names for a set ("Part (file.pac)")."""

    text = str(user or "").strip()
    if text.endswith(")") and " (" in text:
        text = text[: text.rindex(" (")]
    return text.casefold()


def plan_live_texture_outputs(
    edits: Iterable[LiveTextureEdit],
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
    *,
    parts_in_build: Iterable[str] | None = None,
) -> LiveTexturePlan:
    """``parts_in_build``: the names of the parts the mod holds (None: not known, so every
    edited texture counts as used)."""

    outputs: list[LiveTextureOutput] = []
    refusals: list[str] = []
    left_out: list[str] = []
    seen: set[str] = set()
    kept = None if parts_in_build is None else {_part_name(name) for name in parts_in_build}
    for edit in edits:
        key = _normalized(edit.game_path)
        if kept is not None and edit.users and not any(_part_name(user) in kept for user in edit.users):
            if key not in seen:
                seen.add(key)
                left_out.append(LEFT_OUT_TEXT.format(path=edit.game_path, parts=", ".join(edit.users)))
            continue
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
        original = edit.original
        if original is None:
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
                                         rgba=rgba, users=tuple(edit.users), other_files=tuple(edit.other_files)))
    return LiveTexturePlan(outputs=tuple(outputs), refusals=tuple(refusals), left_out=tuple(left_out))


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
    "LiveTextureSource",
    "encode_live_texture_outputs",
    "live_texture_metadata",
    "plan_live_texture_outputs",
]
