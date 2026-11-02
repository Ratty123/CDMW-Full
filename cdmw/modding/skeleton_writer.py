"""Exact PAB skeleton documents: strict read, byte-exact write, constrained edits.

``skeleton_parser.parse_pab`` stays the lenient reader for previews and rigs.
This module is the strict one: every byte of the file must be explained, or
reading fails. All 269 shipped PABs (game 1.0.0.3446, base and dlc_01) read
and write back byte for byte.

PAB is a PAR 1.5 container::

    'PAR ' u8 1 u8 5 b'\\x00\\x01..\\x09'   u32 flags   u16 bone_count
    bone_count x bone record              (layout in skeleton_parser)
    if flags & 0x10: bone_count x i32     secondary parent
    if flags & 0x02: bone_count x u8      core-bone flag
    1 to 3 volume sets                    (pabv_parser; per-volume u32 flags if flags & 0x04)

Shipped files carry flags 0x00 (one empty volume set), 0x05, 0x07, 0x15, 0x17
or 0x1F (three sets). Bits 0x01 and 0x08 add no bytes.

The secondary parent equals the hierarchy parent for 98.4% of shipped bones;
the rest point elsewhere (clavicles at the neck, the tongue at the jaw), never
at a later bone. The core-bone flag is set on every root and on the main
locomotion chain, IK targets and weapon sockets; no shipped flagged bone has
an unflagged parent. What the engine does with either array is not known.

Bones are bound elsewhere by their name hash, the PA checksum of the
case-sensitive name (every shipped bone matches): PAC palettes, PAA tracks,
PABC records and PAMT morph bones. Prefab sockets, the bone offset table and
Havok files name bones as text. Volume keys inside the PAB are indices when
below the bone count and name hashes otherwise. Appending a bone at the end
keeps every existing index and hash valid; renaming one orphans everything
that names it, so the edits here refuse what they cannot keep consistent.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from cdmw.core.archive_format import calculate_pa_checksum

from .pabv_parser import PabvVolume, PabvVolumes, _decode_volume_records
from .skeleton_parser import PAB_HEADER_SIZE, PAR_MAGIC, _read_fixed_pab_bone

PAB_VERSION_PREFIX = PAR_MAGIC + b"\x01\x05" + bytes(range(10))
PAB_KNOWN_FLAGS = 0x1F
PAB_FLAG_SECONDARY_PARENTS = 0x10
PAB_FLAG_CORE_BONES = 0x02
PAB_FLAG_VOLUME_FLAGS = 0x04
# The engine's palette binding sizes its remap with explicit 1,024-entry bounds
# (research doc 5.2); no shipped rig comes close (largest: 502 bones).
PAB_MAX_BONES = 1024
_MAX_NAME_BYTES = 255
_BONE_TAIL = struct.Struct("<i16f16f16f16f3f4f3f")
_VOLUME_HEAD = struct.Struct("<I16fBB")
_MESH_SHAPE = 2
_PARAMETER_COUNTS = {0: 3, 1: 2, 4: 1, 5: 2}
_QUATERNION_TOLERANCE = 1e-3


class PabFormatError(ValueError):
    """The bytes are not a PAB layout this module can reproduce exactly."""


class PabEditRefused(ValueError):
    """An edit would leave the skeleton or something bound to it inconsistent."""


@dataclass(frozen=True, slots=True)
class PabBone:
    name: str
    name_hash: int
    parent_index: int
    bind_matrix: tuple[float, ...]
    inv_bind_matrix: tuple[float, ...]
    local_bind_matrix: tuple[float, ...]
    inv_local_bind_matrix: tuple[float, ...]
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    position: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class PabDocument:
    flags: int
    bones: tuple[PabBone, ...]
    secondary_parents: tuple[int, ...] | None
    core_flags: bytes | None
    # Raw authored keys (index below the bone count, name hash otherwise).
    volume_sets: tuple[PabvVolumes, ...]
    path: str = ""

    @property
    def variant(self) -> str:
        """Short label for the header flags and serialized set count."""
        return f"flags 0x{self.flags:02X}, {len(self.volume_sets)} volume set(s)"

    def bone_index(self, bone: int | str) -> int:
        if isinstance(bone, int) and not isinstance(bone, bool):
            if not 0 <= bone < len(self.bones):
                raise PabEditRefused(f"Bone index {bone} is out of range (0-{len(self.bones) - 1}).")
            return bone
        matches = [index for index, item in enumerate(self.bones) if item.name == bone]
        if len(matches) != 1:
            raise PabEditRefused(f"Bone {bone!r} is {'ambiguous' if matches else 'not in this skeleton'}.")
        return matches[0]


def pab_bone_name_hash(name: str) -> int:
    """The name hash PAB stores beside each bone (PA checksum, case-sensitive)."""
    return calculate_pa_checksum(name.encode("ascii"))


def read_pab_document(data: bytes, path: str = "") -> PabDocument:
    """Decode every byte of a PAB, or raise PabFormatError naming the first gap."""
    data = bytes(data)
    if len(data) < PAB_HEADER_SIZE or data[:16] != PAB_VERSION_PREFIX:
        raise PabFormatError("Not a PAR 1.5 skeleton (expected the 'PAR ' 1.5 header with bytes 0-9).")
    flags, count = struct.unpack_from("<IH", data, 16)
    if flags & ~PAB_KNOWN_FLAGS:
        raise PabFormatError(f"Header flags 0x{flags:X} include bits no shipped skeleton uses.")
    bones = []
    cursor = PAB_HEADER_SIZE
    for index in range(count):
        try:
            raw, cursor = _read_fixed_pab_bone(data, cursor, index)
        except ValueError as exc:
            raise PabFormatError(str(exc)) from exc
        name_bytes = data[raw.file_offset + 5:raw.file_offset + 5 + data[raw.file_offset + 4]]
        if not _printable_ascii(name_bytes):
            raise PabFormatError(f"Bone {index} name is not printable ASCII.")
        values = (*raw.bind_matrix, *raw.inv_bind_matrix, *raw.local_bind_matrix,
                  *raw.inv_local_bind_matrix, *raw.scale, *raw.rotation, *raw.position)
        if not all(math.isfinite(value) for value in values):
            raise PabFormatError(f"Bone {index} ({raw.name}) has a non-finite transform value.")
        bones.append(PabBone(raw.name, raw.name_hash, raw.parent_index, raw.bind_matrix, raw.inv_bind_matrix,
                             raw.local_bind_matrix, raw.inv_local_bind_matrix, raw.scale, raw.rotation,
                             raw.position))
    secondary = None
    if flags & PAB_FLAG_SECONDARY_PARENTS:
        if cursor + 4 * count > len(data):
            raise PabFormatError("Secondary parent array is truncated.")
        secondary = struct.unpack_from(f"<{count}i", data, cursor)
        cursor += 4 * count
    core = None
    if flags & PAB_FLAG_CORE_BONES:
        if cursor + count > len(data):
            raise PabFormatError("Core-bone flag array is truncated.")
        core = data[cursor:cursor + count]
        cursor += count
    record_flags = 2 if flags & PAB_FLAG_VOLUME_FLAGS else 0
    sets = []
    while len(sets) < 3 and (not sets or cursor < len(data)):
        try:
            volumes, cursor = _decode_volume_records(data, cursor, record_flags)
        except ValueError as exc:
            raise PabFormatError(f"Volume set {len(sets)}: {exc}") from exc
        sets.append(volumes)
    if cursor != len(data):
        raise PabFormatError(f"{len(data) - cursor} undecoded bytes remain at 0x{cursor:X}.")
    return PabDocument(flags, tuple(bones), secondary, core, tuple(sets), path)


def write_pab_document(document: PabDocument) -> bytes:
    """Serialize a document; an unedited read writes back byte for byte."""
    _check_document(document)
    count = len(document.bones)
    out = bytearray(PAB_VERSION_PREFIX + struct.pack("<IH", document.flags, count))
    for bone in document.bones:
        name = bone.name.encode("ascii")
        out += struct.pack("<IB", bone.name_hash, len(name)) + name
        out += _BONE_TAIL.pack(bone.parent_index, *bone.bind_matrix, *bone.inv_bind_matrix,
                               *bone.local_bind_matrix, *bone.inv_local_bind_matrix,
                               *bone.scale, *bone.rotation, *bone.position)
    if document.secondary_parents is not None:
        out += struct.pack(f"<{count}i", *document.secondary_parents)
    if document.core_flags is not None:
        out += document.core_flags
    per_volume_flags = bool(document.flags & PAB_FLAG_VOLUME_FLAGS)
    for volumes in document.volume_sets:
        out += struct.pack("<H", len(volumes.volumes))
        for volume in volumes.volumes:
            out += _encode_volume(volume, per_volume_flags)
    return bytes(out)


def pab_layout_summary(data: bytes) -> tuple[str, ...]:
    """Archive Browser lines: exact layout, tail arrays and round-trip status."""
    try:
        document = read_pab_document(data)
        exact = write_pab_document(document) == bytes(data)
    except (ValueError, struct.error) as exc:
        return (f"Exact layout: not decoded ({exc})",)
    count = len(document.bones)
    lines = [f"Exact layout: {document.variant}; "
             + ("writes back byte for byte" if exact else "does not write back byte for byte")]
    if document.secondary_parents is not None:
        differ = sum(1 for bone, other in zip(document.bones, document.secondary_parents)
                     if bone.parent_index != other)
        lines.append(f"Secondary parents: {differ:,} of {count:,} differ from the hierarchy parent")
    if document.core_flags is not None:
        lines.append(f"Core bones: {sum(document.core_flags):,} of {count:,}")
    lines.append("Volumes per set: " + ", ".join(f"{len(item.volumes):,}" for item in document.volume_sets))
    return tuple(lines)


def rename_bone(
    document: PabDocument, bone: int | str, new_name: str, *, protected_hashes: Iterable[int] = (),
) -> PabDocument:
    """Rename one bone, recomputing its hash and the volume keys that name it.

    ``protected_hashes`` are hashes something outside this file is known to
    bind (a PAC palette, a clip, a PABC); renaming one of those is refused.
    """
    index = document.bone_index(bone)
    old = document.bones[index]
    if old.name_hash != pab_bone_name_hash(old.name):
        raise PabEditRefused(f"Bone {old.name!r} stores a hash that is not the PA checksum of its name.")
    if old.name_hash in set(protected_hashes):
        raise PabEditRefused(
            f"Bone {old.name!r} is bound by name hash outside this skeleton; renaming it would unbind it.")
    new_hash = _checked_new_identity(document, new_name, ignore=index)
    count = len(document.bones)
    sets = tuple(
        replace(volumes, volumes=tuple(
            replace(volume, bone_key=new_hash) if volume.bone_key >= count and volume.bone_key == old.name_hash
            else volume
            for volume in volumes.volumes))
        for volumes in document.volume_sets)
    bones = list(document.bones)
    bones[index] = replace(old, name=new_name, name_hash=new_hash)
    return replace(document, bones=tuple(bones), volume_sets=sets)


def append_child_bone(
    document: PabDocument,
    parent: int | str,
    name: str,
    *,
    position: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    core_flag: int = 0,
    secondary_parent: int | None = None,
) -> PabDocument:
    """Append a bone after the last one, posed relative to ``parent``.

    ``position``, ``rotation`` (unit quaternion xyzw) and ``scale`` are the local
    bind transform in the parent's space, stored as the shipped files store
    them: ``local * parentGlobal = global`` in row-vector form. Appending at the
    end keeps every existing bone index, so index-keyed data stays valid.
    """
    parent_index = document.bone_index(parent)
    count = len(document.bones)
    if count + 1 > PAB_MAX_BONES:
        raise PabEditRefused(f"A skeleton cannot exceed {PAB_MAX_BONES} bones.")
    name_hash = _checked_new_identity(document, name)
    for volumes in document.volume_sets:
        for volume in volumes.volumes:
            if volume.bone_key == count:
                raise PabEditRefused(
                    f"Volume key {volume.bone_key} would turn from a name hash into a bone index.")
    position = _finite_vector(position, 3, "position")
    scale = _finite_vector(scale, 3, "scale")
    if any(abs(value) < 1e-6 for value in scale):
        raise PabEditRefused("Scale components must be non-zero.")
    rotation = _finite_vector(rotation, 4, "rotation")
    norm = math.sqrt(sum(value * value for value in rotation))
    if abs(norm - 1.0) > _QUATERNION_TOLERANCE:
        raise PabEditRefused(f"Rotation must be a unit quaternion (length {norm:.4f}).")
    rotation = tuple(value / norm for value in rotation)
    if secondary_parent is None:
        secondary_parent = parent_index
    if document.secondary_parents is not None and not -1 <= secondary_parent < count:
        raise PabEditRefused(f"Secondary parent {secondary_parent} must name an existing bone or -1.")
    if core_flag not in (0, 1):
        raise PabEditRefused("The core-bone flag is 0 or 1.")
    if document.core_flags is None and core_flag:
        raise PabEditRefused("This skeleton has no core-bone flag array.")
    if document.core_flags is not None and core_flag and not document.core_flags[parent_index]:
        raise PabEditRefused("A core bone needs a core parent; no shipped skeleton has otherwise.")

    local = _f32(_compose_local(scale, rotation, position))
    world = _f32(_multiply(local, document.bones[parent_index].bind_matrix))
    bone = PabBone(name, name_hash, parent_index, world, _f32(_invert_affine(world)), local,
                   _f32(_invert_affine(local)), _f32(scale), _f32(rotation), _f32(position))
    return replace(
        document,
        bones=document.bones + (bone,),
        secondary_parents=None if document.secondary_parents is None
        else document.secondary_parents + (secondary_parent,),
        core_flags=None if document.core_flags is None else document.core_flags + bytes((core_flag,)),
    )


@dataclass(frozen=True, slots=True)
class AppendedBone:
    """A bone appended after a source skeleton, with its links named, not indexed."""

    bone: PabBone
    parent: str
    secondary_parent: str | None
    core_flag: int | None

    def same_definition(self, other: AppendedBone) -> bool:
        return (replace(self.bone, parent_index=0) == replace(other.bone, parent_index=0)
                and (self.parent, self.secondary_parent, self.core_flag)
                == (other.parent, other.secondary_parent, other.core_flag))


def appended_bones(source: PabDocument, edited: PabDocument) -> tuple[AppendedBone, ...]:
    """The bones ``edited`` appends to ``source``; refuse any other difference.

    Everything ``source`` holds must be unchanged: header flags, every bone
    record, both tail arrays and every volume. Appended bones carry no volumes.
    """
    count = len(source.bones)
    if (edited.flags != source.flags or len(edited.bones) < count
            or edited.bones[:count] != source.bones
            or (edited.secondary_parents or ())[:count] != (source.secondary_parents or ())
            or (edited.core_flags or b"")[:count] != (source.core_flags or b"")
            or _volume_contents(edited) != _volume_contents(source)):
        raise PabEditRefused("The edited skeleton changes the source skeleton; only appended bones can be combined.")

    def name(index: int) -> str | None:
        return edited.bones[index].name if index >= 0 else None

    return tuple(
        AppendedBone(bone, name(bone.parent_index),
                     None if edited.secondary_parents is None else name(edited.secondary_parents[index]),
                     None if edited.core_flags is None else edited.core_flags[index])
        for index, bone in enumerate(edited.bones[count:], count))


def _volume_contents(document: PabDocument) -> tuple:
    """Every volume as written, without where it was read from."""
    return tuple(tuple(replace(volume, file_offset=0, file_end=0) for volume in volumes.volumes)
                 for volumes in document.volume_sets)


def append_bone_definitions(document: PabDocument, bones: Iterable[AppendedBone]) -> PabDocument:
    """Append bones taken from another edit of the same source, matching them by name.

    A bone ``document`` already appended with the identical definition is kept
    once; the same name with a different definition is refused. Bind matrices
    are copied, not recomputed, so every appended record stays byte-identical.
    """
    names = {bone.name: index for index, bone in enumerate(document.bones)}
    for added in bones:
        existing = names.get(added.bone.name)
        if existing is not None:
            current = document.bones[existing]
            mine = AppendedBone(
                current, document.bones[current.parent_index].name if current.parent_index >= 0 else None,
                None if document.secondary_parents is None else (
                    document.bones[document.secondary_parents[existing]].name
                    if document.secondary_parents[existing] >= 0 else None),
                None if document.core_flags is None else document.core_flags[existing])
            if not mine.same_definition(added):
                raise PabEditRefused(f"Two edits add bone {added.bone.name!r} with different definitions; "
                                     "give the bones different names in one of them.")
            continue
        count = len(document.bones)
        if count + 1 > PAB_MAX_BONES:
            raise PabEditRefused(f"A skeleton cannot exceed {PAB_MAX_BONES} bones.")
        _checked_new_identity(document, added.bone.name)
        for volumes in document.volume_sets:
            if any(volume.bone_key == count for volume in volumes.volumes):
                raise PabEditRefused(f"Volume key {count} would turn from a name hash into a bone index.")
        parent = document.bone_index(added.parent)
        secondary = (document.bone_index(added.secondary_parent) if added.secondary_parent is not None else -1)
        document = replace(
            document,
            bones=document.bones + (replace(added.bone, parent_index=parent),),
            secondary_parents=None if document.secondary_parents is None
            else document.secondary_parents + (secondary,),
            core_flags=None if document.core_flags is None else document.core_flags + bytes((added.core_flag or 0,)),
        )
        names[added.bone.name] = count
    return document


def merge_appended_bones(before: bytes, after: bytes, current: bytes, path: str = "") -> bytes:
    """Three-way merge of two edits that each append bones to ``before``.

    The bones ``after`` appends are added to ``current`` by name, in order. Both
    sides must leave every source byte alone; appended bones bind by name hash
    everywhere outside the file, so their final indices may differ per merge.
    """
    source = read_pab_document(before, path)
    edited, composed = read_pab_document(after, path), read_pab_document(current, path)
    appended_bones(source, composed)
    return write_pab_document(append_bone_definitions(composed, appended_bones(source, edited)))


def _check_document(document: PabDocument) -> None:
    count = len(document.bones)
    flags = document.flags
    if flags & ~PAB_KNOWN_FLAGS or not 0 <= count <= 0xFFFF:
        raise PabFormatError("Document header flags or bone count are out of range.")
    if (document.secondary_parents is None) != (not flags & PAB_FLAG_SECONDARY_PARENTS):
        raise PabFormatError("Secondary parents must be present exactly when header bit 0x10 is set.")
    if (document.core_flags is None) != (not flags & PAB_FLAG_CORE_BONES):
        raise PabFormatError("Core-bone flags must be present exactly when header bit 0x02 is set.")
    for values in (document.secondary_parents, document.core_flags):
        if values is not None and len(values) != count:
            raise PabFormatError("Per-bone tail arrays must have one entry per bone.")
    if not 1 <= len(document.volume_sets) <= 3:
        raise PabFormatError("A PAB serializes one to three volume sets.")
    for index, bone in enumerate(document.bones):
        if not -1 <= bone.parent_index < count:
            raise PabFormatError(f"Bone {index} parent {bone.parent_index} is out of range.")
        if not _valid_name(bone.name):
            raise PabFormatError(f"Bone {index} name must be 1-255 printable ASCII characters.")


def _encode_volume(volume: PabvVolume, per_volume_flags: bool) -> bytes:
    out = bytearray(_VOLUME_HEAD.pack(volume.bone_key, *volume.local_matrix, volume.usage,
                                      volume.serialized_shape))
    if volume.serialized_shape == _MESH_SHAPE:
        out += struct.pack("<H", len(volume.vertices))
        out += struct.pack(f"<{3 * len(volume.vertices)}f", *(c for vertex in volume.vertices for c in vertex))
        out += struct.pack(f"<H{len(volume.indices)}H", len(volume.indices), *volume.indices)
    else:
        if len(volume.parameters) != _PARAMETER_COUNTS[volume.serialized_shape]:
            raise PabFormatError("Volume parameters do not match its shape.")
        out += struct.pack(f"<{len(volume.parameters)}f", *volume.parameters)
    if per_volume_flags:
        out += struct.pack("<I", volume.flags)
    elif volume.flags:
        raise PabFormatError("Volume flags need header bit 0x04.")
    return bytes(out)


def _checked_new_identity(document: PabDocument, name: str, *, ignore: int = -1) -> int:
    if not _valid_name(name):
        raise PabEditRefused("Bone names must be 1-255 printable ASCII characters.")
    name_hash = pab_bone_name_hash(name)
    for index, bone in enumerate(document.bones):
        if index == ignore:
            continue
        if bone.name == name:
            raise PabEditRefused(f"Bone {name!r} already exists.")
        if bone.name_hash == name_hash:
            raise PabEditRefused(f"Bone {name!r} has the same name hash as {bone.name!r}.")
    if name_hash < PAB_MAX_BONES:
        raise PabEditRefused(f"Bone {name!r} hashes below {PAB_MAX_BONES}; volume keys would read it as an index.")
    return name_hash


def _valid_name(name: object) -> bool:
    return (isinstance(name, str) and name.isascii() and 1 <= len(name) <= _MAX_NAME_BYTES
            and _printable_ascii(name.encode("ascii")))


def _printable_ascii(data: bytes) -> bool:
    return all(0x20 <= value <= 0x7E for value in data)


def _finite_vector(values: Sequence[float], size: int, label: str) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise PabEditRefused(f"The {label} must be {size} numbers.") from exc
    if len(result) != size or not all(math.isfinite(value) for value in result):
        raise PabEditRefused(f"The {label} must be {size} finite numbers.")
    return result


def _f32(values: Sequence[float]) -> tuple[float, ...]:
    return struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values))


def _compose_local(scale, rotation, position) -> tuple[float, ...]:
    # Shipped bones satisfy diag(scale) * R(rotation) = local[:3, :3] with this R.
    x, y, z, w = rotation
    rows = (
        (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
        (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
        (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)),
    )
    out = []
    for axis in range(3):
        out.extend((scale[axis] * rows[axis][0], scale[axis] * rows[axis][1], scale[axis] * rows[axis][2], 0.0))
    out.extend((*position, 1.0))
    return tuple(out)


def _multiply(left: Sequence[float], right: Sequence[float]) -> tuple[float, ...]:
    return tuple(sum(left[row * 4 + k] * right[k * 4 + col] for k in range(4))
                 for row in range(4) for col in range(4))


def _invert_affine(matrix: Sequence[float]) -> tuple[float, ...]:
    a, b, c = matrix[0:3], matrix[4:7], matrix[8:11]
    det = (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if abs(det) < 1e-12:
        raise PabEditRefused("The bind transform is singular.")
    inv = (
        (b[1] * c[2] - b[2] * c[1]) / det, (a[2] * c[1] - a[1] * c[2]) / det, (a[1] * b[2] - a[2] * b[1]) / det,
        (b[2] * c[0] - b[0] * c[2]) / det, (a[0] * c[2] - a[2] * c[0]) / det, (a[2] * b[0] - a[0] * b[2]) / det,
        (b[0] * c[1] - b[1] * c[0]) / det, (a[1] * c[0] - a[0] * c[1]) / det, (a[0] * b[1] - a[1] * b[0]) / det,
    )
    t = matrix[12:15]
    translation = tuple(-(t[0] * inv[col] + t[1] * inv[3 + col] + t[2] * inv[6 + col]) for col in range(3))
    return (inv[0], inv[1], inv[2], 0.0, inv[3], inv[4], inv[5], 0.0,
            inv[6], inv[7], inv[8], 0.0, *translation, 1.0)
