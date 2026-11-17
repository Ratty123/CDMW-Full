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

#: Build Mod's line for each edited texture, by its status (item 5): it is written, it is
#: left out (no part in the mod uses it), or it is blocked (it cannot be written, and
#: Build Mod stops). Each is translated through the catalogues when it is shown.
WRITES_TEXT = "{path}: writes, {format}, {width} x {height}, {mips} mips"
SHARED_BY_TEXT = "(shared by {parts})"
ALSO_USED_BY_TEXT = "(also used by {files})"
LEFT_OUT_TEXT = "{path}: left out, no part in this mod uses it ({parts})"
BLOCKED_TEXT = "{path}: blocked. {reason}"
UNKNOWN_GAME_FILE_REASON = "CDMW does not know which game file this texture came from, so it cannot write it."
NOT_IN_ARCHIVES_REASON = "The game file was not found in the archives."
WRONG_SIZE_REASON = "The edit is not the original's size."

WRITES = "writes"
LEFT_OUT = "left out"
BLOCKED = "blocked"


def _say(template: str, **values: str) -> str:
    """``template`` with ``values``, in the language the app shows (English without one)."""

    from cdmw.services.active_ui_translation import active_ui_localizer

    localizer = active_ui_localizer()
    render = getattr(localizer, "format", None)
    if callable(render):
        return str(render(template, **values))
    return template.format(**values)


def _said(text: str) -> str:
    """A sentence already written out (a reason), in the language the app shows."""

    from cdmw.services.active_ui_translation import translate_active_ui_text

    return translate_active_ui_text(text)


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
        line = _say(WRITES_TEXT, path=self.game_path, format=self.original.dds_format,
                    width=str(self.original.width), height=str(self.original.height),
                    mips=str(self.original.mip_count))
        if len(self.users) > 1:
            line += " " + _say(SHARED_BY_TEXT, parts=", ".join(self.users))
        if self.other_files:
            from cdmw.ui.mesh_editor.shared_texture_check import joined_file_names

            line += " " + _say(ALSO_USED_BY_TEXT, files=joined_file_names(self.other_files))
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


@dataclass(frozen=True, slots=True)
class LiveTextureStatus:
    """What Build Mod does with one edited texture: ``WRITES``, ``LEFT_OUT`` or ``BLOCKED``."""

    game_path: str
    status: str
    #: How it is written (``WRITES`` only).
    output: LiveTextureOutput | None = None
    #: The parts that use it (``LEFT_OUT``).
    parts: tuple[str, ...] = ()
    #: Why it cannot be written (``BLOCKED``), one English sentence.
    reason: str = ""

    @property
    def line(self) -> str:
        if self.status == WRITES and self.output is not None:
            return self.output.plan_line
        if self.status == LEFT_OUT:
            return _say(LEFT_OUT_TEXT, path=self.game_path, parts=", ".join(self.parts))
        return _say(BLOCKED_TEXT, path=self.game_path, reason=_said(self.reason))


@dataclass(frozen=True, slots=True)
class LiveTexturePlan:
    #: Every edited texture once, in the order they were edited, with its status.
    statuses: tuple[LiveTextureStatus, ...] = ()

    @property
    def outputs(self) -> tuple[LiveTextureOutput, ...]:
        """The textures Build Mod writes; nothing else edited reaches the mod."""

        return tuple(row.output for row in self.statuses if row.status == WRITES and row.output is not None)

    @property
    def refusals(self) -> tuple[str, ...]:
        """One line per edited texture that cannot be written, saying why (Build Mod stops)."""

        return tuple(row.line for row in self.statuses if row.status == BLOCKED)

    @property
    def left_out(self) -> tuple[str, ...]:
        """One line per edited texture that is not written because no part in the build
        uses it any more (its parts were deleted or their Include is off)."""

        return tuple(row.line for row in self.statuses if row.status == LEFT_OUT)

    @property
    def plan_lines(self) -> tuple[str, ...]:
        """Each edited texture's line, saying whether it writes, is left out or is blocked."""

        return tuple(row.line for row in self.statuses)


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def _part_name(user: str) -> str:
    """A Textures panel heading without the file it names for a set ("Part (file.pac)")."""

    text = str(user or "").strip()
    if text.endswith(")") and " (" in text:
        text = text[: text.rindex(" (")]
    return text.casefold()


def _part_in_build(user: str, kept: set[str]) -> bool:
    """A Textures panel heading names a part the mod holds. A set's part is compared with
    its file ("Belt (b.pac)"), so a part left out of one file is not kept by a part of
    the same name in another; a heading with a file also matches a build part named
    without one (a single file, whose panel still names the file of a Refit's body)."""

    return str(user or "").strip().casefold() in kept or _part_name(user) in kept


def parts_in_build(mesh, archive_refit_context=None, replacement_state=None) -> tuple[str, ...] | None:
    """The parts Build Mod writes, named as the Textures panel names them, or None when
    they cannot be read (then no edited texture is left out).

    Deleted parts are gone from ``mesh`` (the working mesh). A part whose Include is off
    stays in it and is not written: a set's part by its id in ``excluded_part_ids``, a
    single file's part by its replacement binding. With two or more files open the panel
    names each part with its file, and so does this."""

    from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE, PART_ATTRIBUTE, is_item_set

    parts = list(getattr(mesh, "submeshes", None) or ())
    names = [str(getattr(part, "name", "") or "") for part in parts]
    if not names or not all(names):
        return None
    kept = [True] * len(parts)
    assets = tuple(getattr(archive_refit_context, "assets", ()) or ())
    files: dict[int, str] = {}
    if is_item_set(archive_refit_context):
        excluded = frozenset(archive_refit_context.excluded_part_ids)
        by_asset = {asset.asset_id: asset for asset in assets}
        for index, part in enumerate(parts):
            if str(getattr(part, PART_ATTRIBUTE, "")) in excluded:
                kept[index] = False
            asset = by_asset.get(str(getattr(part, ASSET_ATTRIBUTE, "")))
            if asset is None:
                return None
            files[index] = _file_name(asset.entry)
    else:
        for asset in assets:
            for index in asset.part_indices:
                files.setdefault(int(index), _file_name(asset.entry))
        if replacement_state is not None:
            from cdmw.domain.mesh.replacement import bound_part_indices

            try:
                indices = bound_part_indices(mesh, replacement_state)
            except ValueError:
                return None
            for binding in replacement_state.parts:
                if not binding.included:
                    kept[indices[binding.part_id]] = False
    if len(assets) < 2:
        files = {}
    return tuple(names[index] + (f" ({files[index]})" if files.get(index) else "")
                 for index in range(len(parts)) if kept[index])


def _file_name(entry) -> str:
    return str(getattr(entry, "path", "") or "").replace("\\", "/").rsplit("/", 1)[-1]


def plan_live_texture_outputs(
    edits: Iterable[LiveTextureEdit],
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
    *,
    parts_in_build: Iterable[str] | None = None,
) -> LiveTexturePlan:
    """``parts_in_build``: the parts the mod holds, as ``parts_in_build()`` names them
    (None: not known, so every edited texture counts as used)."""

    statuses: list[LiveTextureStatus] = []
    seen: set[str] = set()
    kept = None if parts_in_build is None else {str(name).strip().casefold() for name in parts_in_build}

    def blocked(edit: LiveTextureEdit, reason: str) -> None:
        statuses.append(LiveTextureStatus(edit.game_path, BLOCKED, reason=reason))

    for edit in edits:
        key = _normalized(edit.game_path)
        # Left out comes first: a texture no part in the mod uses is not written, so
        # whether it could be does not stop Build Mod.
        if kept is not None and edit.users and not any(_part_in_build(user, kept) for user in edit.users):
            if key not in seen:
                seen.add(key)
                statuses.append(LiveTextureStatus(edit.game_path, LEFT_OUT, parts=tuple(edit.users)))
            continue
        if "/" not in key:
            blocked(edit, UNKNOWN_GAME_FILE_REASON)
            continue
        if key in seen:
            continue
        seen.add(key)
        entry = active_archive_entry_for_virtual_path(
            [item for item in entries_by_normalized_path.get(key, ()) if isinstance(item, ArchiveEntry)])
        if entry is None:
            blocked(edit, NOT_IN_ARCHIVES_REASON)
            continue
        original = edit.original
        if original is None:
            try:
                original = check_texture_editable(Path(edit.original_path))
            except TextureOutputRefused as exc:
                blocked(edit, exc.reason)
                continue
        rgba = np.asarray(edit.rgba)
        if rgba.ndim != 3 or (int(rgba.shape[1]), int(rgba.shape[0])) != (original.width, original.height):
            blocked(edit, WRONG_SIZE_REASON)
            continue
        output = LiveTextureOutput(entry=entry, game_path=edit.game_path, original=original,
                                   rgba=rgba, users=tuple(edit.users), other_files=tuple(edit.other_files))
        statuses.append(LiveTextureStatus(edit.game_path, WRITES, output=output))
    return LiveTexturePlan(statuses=tuple(statuses))


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
    "LiveTextureStatus",
    "encode_live_texture_outputs",
    "live_texture_metadata",
    "parts_in_build",
    "plan_live_texture_outputs",
]
