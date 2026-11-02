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
import json
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


PAB_EDIT_JSON_FORMAT = "cdmw.pab-edit"
PAB_EDIT_JSON_VERSION = 1


class PabEditJsonError(ValueError):
    """A Skeleton Edit JSON document is malformed or does not match its source."""


def dumps_pab_edit_json(data: bytes, virtual_path: str = "") -> str:
    """Export a skeleton as Skeleton Edit JSON: read-only bones plus an empty ``add_bones`` list."""
    document = read_pab_document(data, virtual_path)
    bones = []
    for index, bone in enumerate(document.bones):
        row = {
            "index": index,
            "name": bone.name,
            "parent": document.bones[bone.parent_index].name if bone.parent_index >= 0 else None,
            "position": list(bone.position),
            "rotation": list(bone.rotation),
            "scale": list(bone.scale),
            "global_position": list(bone.bind_matrix[12:15]),
        }
        if document.core_flags is not None:
            row["core"] = document.core_flags[index]
        bones.append(row)
    payload = {
        "format": PAB_EDIT_JSON_FORMAT,
        "version": PAB_EDIT_JSON_VERSION,
        "source": {
            "path": virtual_path,
            "sha256": hashlib.sha256(bytes(data)).hexdigest(),
            "bone_count": len(document.bones),
            "layout": document.variant,
        },
        "help": [
            ("Only add_bones is applied. The bones list is a read-only reference; renaming, removing or "
             "reordering shipped bones is refused because meshes, clips and sockets bind them."),
            ("Each added bone: {\"parent\": existing or earlier added bone name, \"name\": new unique ASCII "
             "name, \"position\": [x, y, z] in the parent's space, \"rotation\": [x, y, z, w] unit quaternion, "
             "\"scale\": [x, y, z], \"core\": 0}."),
            *PAB_APPEND_NOTES,
        ],
        "add_bones": [],
        "bones": bones,
    }
    return json.dumps(payload, indent=2) + "\n"


def apply_pab_edit_json(data: bytes, text: str, *, virtual_path: str = "") -> PabEditOutcome:
    """Apply a Skeleton Edit JSON document to the skeleton it was exported from."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PabEditJsonError(f"Skeleton Edit JSON is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != PAB_EDIT_JSON_FORMAT:
        raise PabEditJsonError("This is not a Skeleton Edit JSON document.")
    if payload.get("version") != PAB_EDIT_JSON_VERSION:
        raise PabEditJsonError(f"Skeleton Edit JSON version {payload.get('version')!r} is not supported.")
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("sha256") != hashlib.sha256(bytes(data)).hexdigest():
        raise PabEditJsonError(
            "This Skeleton Edit JSON was exported from a different version of the skeleton. Export it again.")
    document = read_pab_document(data, virtual_path)
    expected = [(bone.name, document.bones[bone.parent_index].name if bone.parent_index >= 0 else None)
                for bone in document.bones]
    listed = payload.get("bones")
    if (not isinstance(listed, list)
            or [(row.get("name"), row.get("parent")) if isinstance(row, dict) else None for row in listed]
            != expected):
        raise PabEditJsonError(
            "The bones list was changed. Existing bones are read-only; add new bones under add_bones.")
    rows = payload.get("add_bones")
    if not isinstance(rows, list):
        raise PabEditJsonError("add_bones must be a list.")
    edits = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get("parent"), str) or not isinstance(row.get("name"), str):
            raise PabEditJsonError(f"Added bone {number} needs a parent and a name.")
        unknown = set(row) - {"parent", "name", "position", "rotation", "scale", "core"}
        if unknown:
            raise PabEditJsonError(f"Added bone {number} has unknown fields: {', '.join(sorted(unknown))}.")
        core = row.get("core", 0)
        if core not in (0, 1) or isinstance(core, bool):
            raise PabEditJsonError(f"Added bone {number}: core must be 0 or 1.")
        edits.append(PabAppendEdit(
            row["parent"], row["name"],
            position=_vector(row, "position", (0.0, 0.0, 0.0), number),
            rotation=_vector(row, "rotation", (0.0, 0.0, 0.0, 1.0), number),
            scale=_vector(row, "scale", (1.0, 1.0, 1.0), number),
            core_flag=core,
        ))
    try:
        return apply_pab_edits(data, edits, path=virtual_path)
    except PabEditRefused as exc:
        raise PabEditJsonError(str(exc)) from exc


def _vector(row: dict, key: str, default: tuple[float, ...], number: int) -> tuple[float, ...]:
    value = row.get(key, default)
    if (not isinstance(value, (list, tuple)) or len(value) != len(default)
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)):
        raise PabEditJsonError(f"Added bone {number}: {key} must be {len(default)} numbers.")
    return tuple(float(item) for item in value)
