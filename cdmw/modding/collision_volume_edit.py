"""Resize, move, copy and remove collision volumes in a PABV or a PAC's own set.

Both containers store volumes with the shared record grammar decoded by
``pabv_parser``: bone key, a 4x4 local matrix (row vectors, translation in the
last row), usage and shape tags, the shape's float parameters or mesh, then an
optional flags word. A standalone PABV is header, flags, count and records with
nothing after them. A PAC stores its set inside section 0 after the palette and
bounds; only the section size and the LOD vertex/index offsets point past it, as
in the weapon-collider writer.

Every write rebuilds the record list from the decoded records, keeps each
untouched record byte for byte, rewrites only the dimension and translation
floats of an edited one, and decodes the result again before returning it.
Mesh volumes can be moved, copied or removed but not resized.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass

from cdmw.domain.mesh.collision_volumes import (
    MODEL_SOURCE, VOLUME_LIMIT, CollisionVolumeEdit,
)

from .pabv_parser import _PARAMETER_COUNTS, PabvVolume, decode_pabv, decode_pac_embedded_volumes

#: "Bip01 Head" (PA checksum). The body/head merge requires one in each source.
HEAD_BONE_HASH = 0xA23A288E
SHAPE_NAMES = {0: "box", 1: "cylinder", 2: "mesh", 4: "sphere", 5: "capsule"}
_TRANSLATION = 4 + 48
_PARAMETERS = 4 + 64 + 2


@dataclass(frozen=True, slots=True)
class VolumeSet:
    """A decoded set with the exact bytes of each record, ready for editing."""

    source: str
    sha256: str
    hashed_keys: bool
    volumes: tuple[PabvVolume, ...]
    records: tuple[bytes, ...]


def _check_records(data: bytes, volumes) -> tuple[bytes, ...]:
    records = tuple(bytes(data[v.file_offset:v.file_end]) for v in volumes)
    for volume, record in zip(volumes, records, strict=True):
        if record[69] != volume.serialized_shape or len(record) != volume.file_end - volume.file_offset:
            raise ValueError("Collision volume records do not match their decoded layout.")
    return records


def pabv_volume_set(data: bytes, path: str) -> VolumeSet:
    decoded = decode_pabv(data)
    return VolumeSet(path, hashlib.sha256(data).hexdigest(), decoded.uses_bone_hashes,
                     decoded.volumes, _check_records(data, decoded.volumes))


def _pac_layout(data: bytes):
    from .mesh_parser import _parse_par_sections
    from .pac_cloth_guide_builder import _validate_metadata_tail

    model = decode_pac_embedded_volumes(data)
    sections = _parse_par_sections(data)
    if not sections or sections[0]["index"] != 0:
        raise ValueError("Collision volume edits need complete PAC sections.")
    metadata = sections[0]
    stored, size = struct.unpack_from("<2I", data, 16)
    if stored not in (0, size) or size != metadata["size"]:
        raise ValueError("Collision volume edits need decompressed PAC metadata.")
    if sections[-1]["offset"] + sections[-1]["size"] != len(data):
        raise ValueError("Collision volume edits cannot move undecoded data after the PAC sections.")
    lods = data[metadata["offset"] + 4]
    if not 2 <= lods <= 4 or [s["index"] for s in sections] != list(range(lods + 1)):
        raise ValueError("Collision volume edits need the decoded 2, 3 or 4 LOD section layout.")
    # Everything after the set must be the fully decoded sequential trailer: no
    # unknown field may hold an absolute offset that the edit would invalidate.
    _validate_metadata_tail(data, model.file_end, metadata["offset"] + metadata["size"], model.metadata_flags)
    return model, metadata, lods


def pac_volume_set(data: bytes) -> VolumeSet:
    model, _, _ = _pac_layout(data)
    block = data[model.file_offset:model.file_end]
    # PAC keys are looked up as name hashes by the mapped collider producer.
    return VolumeSet(MODEL_SOURCE, hashlib.sha256(block).hexdigest(), True,
                     model.volumes, _check_records(data, model.volumes))


def edited_records(source: VolumeSet, edit: CollisionVolumeEdit) -> list[bytes]:
    """The new record list, or ValueError naming the first invalid edit."""
    if edit.source != source.source:
        raise ValueError("These collision volume edits belong to another source.")
    if edit.source_sha256 != source.sha256:
        raise ValueError("The collision volume source changed since it was edited. Restore the edits and make them again.")
    count = len(source.volumes)
    for row in (*edit.changes, *edit.copies):
        ordinal = getattr(row, "ordinal", getattr(row, "template", None))
        if ordinal >= count:
            raise ValueError(f"Collision volume {ordinal + 1} does not exist in this set of {count}.")

    def patched(index, parameters, position):
        volume, record = source.volumes[index], bytearray(source.records[index])
        if parameters is not None:
            if volume.serialized_shape == 2:
                raise ValueError(f"Collision volume {index + 1} is a mesh; it can be moved but not resized.")
            expected = _PARAMETER_COUNTS[volume.serialized_shape]
            if len(parameters) != expected:
                raise ValueError(f"Collision volume {index + 1} ({SHAPE_NAMES[volume.serialized_shape]}) "
                                 f"takes {expected} size value(s).")
            struct.pack_into(f"<{expected}f", record, _PARAMETERS, *parameters)
        if position is not None:
            struct.pack_into("<3f", record, _TRANSLATION, *position)
        return bytes(record)

    changes = {row.ordinal: row for row in edit.changes}
    result = []
    for index in range(count):
        row = changes.get(index)
        if row is None:
            result.append(source.records[index])
        elif not row.removed:
            result.append(patched(index, row.parameters, row.position))
    for row in edit.copies:
        result.append(patched(row.template, row.parameters, row.position))
    if len(result) > VOLUME_LIMIT:
        raise ValueError(f"Collision volume sets hold at most {VOLUME_LIMIT} volumes.")
    if count and not result:
        raise ValueError("Keep at least one collision volume in this set.")
    if source.source != MODEL_SOURCE and source.hashed_keys:
        heads = [i for i, volume in enumerate(source.volumes) if volume.bone_key == HEAD_BONE_HASH]
        if heads and all(i in edit.removed for i in heads):
            raise ValueError("Keep a Bip01 Head volume: the game merges body and head volumes through it.")
    return result


def _verify(decoded, expected: list[bytes], data: bytes):
    if len(decoded) != len(expected) or any(
            bytes(data[v.file_offset:v.file_end]) != record for v, record in zip(decoded, expected)):
        raise ValueError("Edited collision volumes did not decode back to the requested records.")
    for volume in decoded:
        if volume.serialized_shape != 2 and any(value <= 0 for value in volume.parameters):
            raise ValueError("Edited collision volumes must keep positive sizes.")
        if not all(math.isfinite(value) for value in volume.local_matrix):
            raise ValueError("Edited collision volumes must keep finite positions.")


def apply_pabv_volume_edit(data: bytes, path: str, edit: CollisionVolumeEdit) -> bytes:
    source = pabv_volume_set(data, path)
    records = edited_records(source, edit)
    result = data[:20] + struct.pack("<H", len(records)) + b"".join(records)
    _verify(decode_pabv(result).volumes, records, result)
    return result


def apply_pac_volume_edit(data: bytes, edit: CollisionVolumeEdit) -> bytes:
    """Rewrite the PAC's own set; geometry and every other metadata byte are kept."""
    from .mesh_parser import _parse_par_sections

    source = pac_volume_set(data)
    records = edited_records(source, edit)
    model, metadata, lods = _pac_layout(data)
    block = struct.pack("<H", len(records)) + b"".join(records)
    delta = len(block) - (model.file_end - model.file_offset)
    result = bytearray(data[:model.file_offset] + block + data[model.file_end:])
    stored, size = struct.unpack_from("<2I", data, 16)
    struct.pack_into("<2I", result, 16, stored and size + delta, size + delta)
    patched_words = [16, 20]
    for i in range(2 * lods):
        offset = metadata["offset"] + 5 + 4 * i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", data, offset)[0] + delta)
        patched_words.append(offset)
    result = bytes(result)
    after = decode_pac_embedded_volumes(result)
    if (after.file_offset != model.file_offset or after.bone_palette != model.bone_palette
            or after.bounds != model.bounds or after.metadata_flags != model.metadata_flags):
        raise ValueError("The collision volume edit changed PAC metadata it must keep.")
    _verify(after.volumes, records, result)
    # Every byte outside the set and the offset words is unchanged, and every
    # later section still holds the same bytes at its relocated offset.
    before_prefix, after_prefix = bytearray(data[:model.file_offset]), bytearray(result[:model.file_offset])
    for offset in patched_words:
        before_prefix[offset:offset + 4] = after_prefix[offset:offset + 4]
    if before_prefix != after_prefix or data[model.file_end:] != result[after.file_end:]:
        raise ValueError("The collision volume edit changed bytes outside the volume set.")
    sections = _parse_par_sections(result)
    if [s["size"] for s in sections[1:]] != [s["size"] for s in _parse_par_sections(data)[1:]]:
        raise ValueError("The collision volume edit changed the PAC geometry sections.")
    return result


def volume_rows(source: VolumeSet, *, bone_names=None) -> list[dict]:
    """UI rows: one per volume, with its editable values."""
    rows = []
    for ordinal, volume in enumerate(source.volumes):
        matrix = volume.local_matrix
        rows.append({
            "ordinal": ordinal, "shape": SHAPE_NAMES[volume.serialized_shape],
            "resizable": volume.serialized_shape != 2,
            "bone_key": volume.bone_key,
            "bone": (bone_names or {}).get(volume.bone_key, ""),
            "parameters": list(volume.parameters),
            "position": list(matrix[12:15]),
            "axis": list(matrix[4:7]),
            "flags": volume.flags, "usage": volume.usage,
        })
    return rows
