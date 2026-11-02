"""Constrained PAB skeleton edits for loose mod packages.

The service turns source PAB bytes and an ordered edit list into new bytes and
a report. It never reads or writes archives; callers package the result.

Policy, from what binds a bone (``cdmw.modding.skeleton_writer``):

- Appending a child bone is allowed. Existing indices and name hashes do not
  change, so PAC palettes, PAA tracks, PABC records, PAMT morph bones, prefab
  sockets, the bone offset table and index-keyed volumes keep binding.
- Renaming is allowed only for a bone appended earlier in the same edit list.
  A bone that exists in the source skeleton is named by data outside the file
  (palettes, clips, sockets, Havok skeletons), and renaming it would silently
  unbind all of it, so the service refuses.
- Removing or reordering bones is not offered: both shift indices.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from cdmw.modding.skeleton_writer import (
    PabEditRefused,
    append_child_bone,
    read_pab_document,
    rename_bone,
    write_pab_document,
)

PAB_APPEND_NOTES = (
    ("Existing bone indices and name hashes are unchanged, so meshes, clips, appearance "
     "variations and sockets that use them still bind."),
    "A mesh can weight vertices to a new bone only after its PAC palette lists it.",
    ("New bones have no animation tracks, appearance records, collision volumes or Havok "
     "bodies, so they follow their parent rigidly at the authored offset."),
    "Added bones are not proven in game.",
)


@dataclass(frozen=True, slots=True)
class PabAppendEdit:
    parent: str
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    core_flag: int = 0


@dataclass(frozen=True, slots=True)
class PabRenameEdit:
    bone: str
    new_name: str


@dataclass(frozen=True, slots=True)
class PabEditOutcome:
    data: bytes
    source_sha256: str
    output_sha256: str
    source_bone_count: int
    bone_count: int
    appended: tuple[str, ...]
    notes: tuple[str, ...]


def apply_pab_edits(
    data: bytes, edits: Sequence[PabAppendEdit | PabRenameEdit], *, path: str = "",
) -> PabEditOutcome:
    """Apply ``edits`` in order; raise PabEditRefused for the first refused one."""
    source = read_pab_document(data, path)
    source_names = {bone.name for bone in source.bones}
    document = source
    for edit in edits:
        if isinstance(edit, PabAppendEdit):
            document = append_child_bone(
                document, edit.parent, edit.name, position=edit.position, rotation=edit.rotation,
                scale=edit.scale, core_flag=edit.core_flag)
        elif isinstance(edit, PabRenameEdit):
            if edit.bone in source_names:
                raise PabEditRefused(
                    f"{edit.bone!r} is part of the source skeleton. Meshes, clips, appearance variations, "
                    "sockets and Havok files name it, so renaming it would unbind them. Rename only "
                    "bones added in this edit.")
            document = rename_bone(document, edit.bone, edit.new_name)
        else:
            raise PabEditRefused(f"Unsupported skeleton edit {type(edit).__name__}.")
    output = write_pab_document(document)
    appended = tuple(bone.name for bone in document.bones[len(source.bones):])
    return PabEditOutcome(
        data=output,
        source_sha256=hashlib.sha256(bytes(data)).hexdigest(),
        output_sha256=hashlib.sha256(output).hexdigest(),
        source_bone_count=len(source.bones),
        bone_count=len(document.bones),
        appended=appended,
        notes=PAB_APPEND_NOTES if appended else (),
    )
