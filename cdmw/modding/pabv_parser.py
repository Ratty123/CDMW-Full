"""Read-only skeleton volumes, traced in game build 1.0.0.2944.

The serialized shape tags differ from the CPU/GPU shape types. Standalone
PABV headers distinguish hash and index keys; embedded PAB/PAC sets use their
own loader conventions. Decoding does not select an active
character variant or infer collision activation.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
import math
import struct

from ._pbd_numeric import f32
from .skeleton_parser import Skeleton


_HEADER = b"PAR \x36\x01" + bytes(range(10))
_SHAPE_TYPES = {0: 2, 1: 3, 2: 4, 4: 1, 5: 5}
_PARAMETER_COUNTS = {0: 3, 1: 2, 4: 1, 5: 2}


@dataclass(frozen=True, slots=True)
class PabvVolume:
    file_offset: int
    file_end: int
    bone_key: int
    local_matrix: tuple[float, ...]
    usage: int
    serialized_shape: int
    parameters: tuple[float, ...]
    vertices: tuple[tuple[float, float, float], ...]
    indices: tuple[int, ...]
    flags: int

    @property
    def shape_type(self) -> int:
        """Engine types: sphere 1, box 2, cylinder 3, mesh 4, capsule 5."""
        return _SHAPE_TYPES[self.serialized_shape]


@dataclass(frozen=True, slots=True)
class PabvVolumes:
    flags: int
    volumes: tuple[PabvVolume, ...]

    @property
    def uses_bone_hashes(self) -> bool:
        return bool(self.flags & 1)

    @property
    def has_volume_flags(self) -> bool:
        return bool(self.flags & 2)


@dataclass(frozen=True, slots=True)
class PabvClothColliders:
    definitions: tuple[bytes, ...]
    bone_indices: tuple[int, ...]
    source_ordinals: tuple[int, ...]
    has_activation_flag: bool


@dataclass(frozen=True, slots=True)
class PabvVolumeMerge:
    volumes: PabvVolumes
    # (input index, original record ordinal): body is 0 and head is 1.
    source_records: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class PabEmbeddedVolumes:
    header_flags: int
    primary: PabvVolumes
    rendering: PabvVolumes | None
    physics: PabvVolumes | None


@dataclass(frozen=True, slots=True)
class PacEmbeddedVolumes:
    metadata_flags: int
    bone_palette: tuple[int, ...]
    bounds: tuple[float, ...]
    file_offset: int
    file_end: int
    # Raw authored keys: do not silently reinterpret them as PAB indices.
    volumes: tuple[PabvVolume, ...]


def decode_pabv(data: bytes) -> PabvVolumes:
    """Decode the known PAR 0x36/1 layout, rejecting incomplete geometry.

    Parameters retain file order: box (z, x, y), cylinder/capsule (radius,
    height), sphere (radius). Matrix rows retain their authored convention.
    Mesh indices address the record's own float3 vertices. The usage byte and
    flag words are retained without inventing activation rules. Missing optional
    volume flags initialize to zero, as in the CPU loader.
    """
    if len(data) < 22 or data[:16] != _HEADER:
        raise ValueError("PABV decoding requires the known PAR 0x36/1 header.")
    flags, = struct.unpack_from("<I", data, 16)
    volumes, cursor = _decode_volume_records(data, 20, flags)
    if cursor != len(data):
        raise ValueError(f"PABV has undecoded trailing data at byte {cursor}.")
    return volumes


def _decode_volume_records(
    data: bytes, cursor: int, flags: int, *, file_offset: int = 0,
) -> tuple[PabvVolumes, int]:
    if cursor + 2 > len(data):
        raise ValueError("PABV volume count is truncated.")
    count, = struct.unpack_from("<H", data, cursor)
    cursor += 2
    minimum_size = 74 + (4 if flags & 2 else 0)
    if count > (len(data) - cursor) // minimum_size:
        raise ValueError("PABV volume records are truncated.")

    def take(size: int, name: str) -> memoryview:
        nonlocal cursor
        end = cursor + size
        if end > len(data):
            raise ValueError(f"PABV {name} is truncated at byte {file_offset + cursor}.")
        result = memoryview(data)[cursor:end]
        cursor = end
        return result

    def floats(count: int, name: str) -> tuple[float, ...]:
        values = struct.unpack(f"<{count}f", take(4 * count, name))
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"PABV {name} must contain finite values.")
        return values

    volumes = []
    for ordinal in range(count):
        offset = file_offset + cursor
        bone_key, = struct.unpack("<I", take(4, "bone key"))
        local_matrix = floats(16, "local matrix")
        usage, shape = struct.unpack("<BB", take(2, "shape tags"))
        if shape not in _SHAPE_TYPES:
            raise ValueError(f"PABV volume {ordinal} shape tag {shape} is not decoded.")
        vertices, indices, parameters = (), (), ()
        if shape == 2:
            vertex_count, = struct.unpack("<H", take(2, "mesh vertex count"))
            xyz = floats(3 * vertex_count, "mesh vertices")
            vertices = tuple(tuple(xyz[i:i + 3]) for i in range(0, len(xyz), 3))
            index_count, = struct.unpack("<H", take(2, "mesh index count"))
            indices = struct.unpack(f"<{index_count}H", take(2 * index_count, "mesh indices"))
            if len(indices) % 3 or any(index >= vertex_count for index in indices):
                raise ValueError("PABV mesh indices must contain complete, in-range triangles.")
        else:
            parameters = floats(_PARAMETER_COUNTS[shape], "shape parameters")
            if any(value < 0 for value in parameters):
                raise ValueError("PABV shape dimensions must be nonnegative.")
        volume_flags = struct.unpack("<I", take(4, "volume flags"))[0] if flags & 2 else 0
        volumes.append(PabvVolume(
            offset, file_offset + cursor, bone_key, local_matrix, usage, shape, parameters,
            vertices, indices, volume_flags,
        ))
    return PabvVolumes(flags, tuple(volumes)), cursor


def decode_pab_embedded_volumes(skeleton: Skeleton) -> PabEmbeddedVolumes:
    """Decode the three volume sets after known PAB 1/5 bone records.

    This is the skeleton's default geometry, before appearance overrides. The
    PAB header's bits 0x10 and 0x2 add four bytes and one byte per bone ahead of
    the primary volume count. Bit 0x4 adds each volume's flags word. These are
    PAB flags, not the standalone PABV flags. Rendering and physics sets can be
    omitted at EOF; an explicitly serialized empty set remains distinguishable.

    The embedded loader converts keys below the bone count from indices to
    stored name hashes and retains larger keys. Return materialized hash keys,
    preserving absolute record offsets into the original PAB. Callers still
    use resolve_pabv_bones to reject unresolved/ambiguous hashes before binding.
    No later active appearance or runtime collision profile is inferred here.
    """
    header = skeleton.source_header
    if (skeleton.parser_mode != "fixed" or len(header) != 22
            or header[:16] != b"PAR \x01\x05" + bytes(range(10))):
        raise ValueError("Embedded volumes require a fixed-layout PAB with the known PAR 1/5 header.")
    flags, count = struct.unpack_from("<IH", header, 16)
    if (count != skeleton.bone_count or count != len(skeleton.bones)
            or any(bone.index != i for i, bone in enumerate(skeleton.bones))
            or skeleton.tail_offset != (skeleton.bones[-1].file_end if count else 22)):
        raise ValueError("Embedded volumes require complete, ordered PAB bone records.")
    cursor = (4 * count if flags & 0x10 else 0) + (count if flags & 0x2 else 0)
    data = skeleton.tail_data
    if cursor > len(data):
        raise ValueError("PAB per-bone tail arrays are truncated.")
    record_flags = 2 if flags & 0x4 else 0

    def read_set() -> PabvVolumes:
        nonlocal cursor
        raw, cursor = _decode_volume_records(data, cursor, record_flags, file_offset=skeleton.tail_offset)
        records = tuple(replace(volume, bone_key=skeleton.bones[volume.bone_key].name_hash)
                        if volume.bone_key < count else volume for volume in raw.volumes)
        return PabvVolumes(record_flags | 1, records)

    primary = read_set()
    rendering = read_set() if cursor < len(data) else None
    physics = read_set() if cursor < len(data) else None
    if cursor != len(data):
        raise ValueError(f"PAB has undecoded trailing data at byte {skeleton.tail_offset + cursor}.")
    return PabEmbeddedVolumes(flags, primary, rendering, physics)


def decode_pac_embedded_volumes(data: bytes) -> PacEmbeddedVolumes:
    """Read model volumes after known PAC 3/9 guide/auxiliary/palette data.

    Build 1.0.0.2944's 0x142C65090 reads these after the model bounds. Manager
    slot 0x50 (0x142CD0FD0) always enables per-record flags before invoking
    the shared volume reader. Later metadata is not part of the volume set.

    Retain raw bone keys and absolute offsets. This does not infer index/hash
    conversion, bind the model to a rig, or select its runtime collision set.
    The separate embedded bone-group branch (metadata bit 0x20) is not decoded.
    """
    from .mesh_parser import (
        _find_pac_descriptors, _parse_par_sections, _validated_pac_descriptor_prefix,
    )
    from .pac_cloth_guides import decode_pac_cloth_guides

    if len(data) < 80 or data[:6] != b"PAR \x03\x09":
        raise ValueError("Embedded model volumes require the known PAC 3/9 header.")
    sections = _parse_par_sections(data)
    metadata = next((section for section in sections if section["index"] == 0), None)
    if metadata is None or metadata["size"] < 5:
        raise ValueError("Embedded model volumes require complete PAC metadata.")
    stored, = struct.unpack_from("<I", data, 16)
    if stored not in (0, metadata["size"]):
        raise ValueError("Embedded model volumes require decompressed PAC metadata.")
    start, end = metadata["offset"], metadata["offset"] + metadata["size"]
    if end > len(data):
        raise ValueError("PAC model metadata is truncated.")
    flags, = struct.unpack_from("<I", data, start)
    if flags & 0x20:
        raise ValueError("PAC embedded bone-group metadata is not decoded.")
    guides = decode_pac_cloth_guides(data)
    if guides is not None:
        last = guides.ranges[-1]
        cursor = last.offset + last.count * last.stride
    else:
        lod_count = data[start + 4]
        count_offset = start + 5 + 8 * lod_count
        if not 2 <= lod_count <= 4 or count_offset + 2 > end:
            raise ValueError("PAC model descriptor layout is not decoded.")
        part_count, = struct.unpack_from("<H", data, count_offset)
        descriptors = _validated_pac_descriptor_prefix(
            _find_pac_descriptors(data, start, metadata["size"], lod_count), sections,
        )
        if not descriptors or len(descriptors) != part_count:
            raise ValueError("PAC model volumes cannot be located after every descriptor.")
        cursor = max(d.descriptor_offset + 40 + 6 * d.stored_lod_count for d in descriptors)

    def take(size: int, name: str) -> memoryview:
        nonlocal cursor
        stop = cursor + size
        if cursor < start or stop > end:
            raise ValueError(f"PAC model {name} is truncated.")
        value = memoryview(data)[cursor:stop]
        cursor = stop
        return value

    def array(stride: int, name: str) -> memoryview:
        count, = struct.unpack("<H", take(2, name + " count"))
        return take(count * stride, name)

    if flags & 0x2000:
        take(24, "auxiliary bounds")
        array(16, "auxiliary records A")
        array(24, "auxiliary records B")
    palette = tuple(row[0] for row in struct.iter_unpack("<I", array(4, "bone palette")))
    bounds = struct.unpack("<6f", take(24, "bounds"))
    if not all(math.isfinite(value) for value in bounds):
        raise ValueError("PAC model bounds must contain finite values.")
    if flags & 4:
        take(24, "secondary bounds")
    offset = cursor
    # Bound the shared record reader to metadata, never the following geometry.
    records, cursor = _decode_volume_records(data[:end], cursor, 2)
    return PacEmbeddedVolumes(flags, palette, bounds, offset, cursor, records.volumes)


def resolve_pabv_bones(volumes: PabvVolumes, skeleton: Skeleton) -> tuple[int, ...]:
    """Resolve every authored key against an explicit fixed-layout PAB rig.

    This is strict editor input validation. Missing/ambiguous keys fail instead
    of silently attaching geometry to the root or guessing a related rig.
    """
    if (skeleton.parser_mode != "fixed" or skeleton.bone_count != len(skeleton.bones)
            or any(bone.index != i for i, bone in enumerate(skeleton.bones))):
        raise ValueError("PABV binding requires a complete fixed-layout PAB rig.")
    by_hash: dict[int, list[int]] = {}
    if volumes.uses_bone_hashes:
        for bone in skeleton.bones:
            by_hash.setdefault(bone.name_hash, []).append(bone.index)
    result = []
    for ordinal, volume in enumerate(volumes.volumes):
        key = volume.bone_key
        if volumes.uses_bone_hashes:
            matches = by_hash.get(key, ())
            if len(matches) != 1:
                raise ValueError(f"PABV volume {ordinal} bone hash {key:#010x} is missing or ambiguous.")
            index = matches[0]
        else:
            if not 0 <= key < len(skeleton.bones):
                raise ValueError(f"PABV volume {ordinal} bone index {key} is out of range.")
            index = key
        result.append(index)
    return tuple(result)


def merge_pabv_body_head_volumes(
    body: PabvVolumes, head: PabvVolumes | None = None, *,
    body_skeleton: Skeleton | None = None, head_skeleton: Skeleton | None = None,
) -> PabvVolumeMerge:
    """Merge explicitly selected body/head sources as in 0x142D3EB50.

    The game copies the body records, then replaces only the first Bip01 Head
    record with the head source's first matching record. Other head records
    are not appended. A missing match fails the merge. The caller owns active
    prefab/resource selection and any resource-load failure fallback.

    The engine merges after legacy indices become name hashes. Each legacy
    source therefore needs its own explicit matching rig; a head index is
    never interpreted through an implicitly reused body rig. The returned
    flags=3 describes materialized hash keys and per-record flags, not an
    original file header. Record offsets refer to the identified input file.
    """
    def normalized(source, skeleton, label):
        if source.uses_bone_hashes or not source.volumes:
            return source.volumes
        if skeleton is None:
            raise ValueError(f"PABV {label} merge source needs its matching skeleton for legacy indices.")
        indices = resolve_pabv_bones(source, skeleton)
        return tuple(replace(volume, bone_key=skeleton.bones[index].name_hash)
                     for volume, index in zip(source.volumes, indices, strict=True))

    records = list(normalized(body, body_skeleton, "body"))
    origins = [(0, index) for index in range(len(records))]
    if head is not None:
        head_records = normalized(head, head_skeleton, "head")
        # The interned key at 0x146D034E4 is "Bip01 Head" (PA checksum).
        key = 0xA23A288E
        body_index = next((i for i, volume in enumerate(records) if volume.bone_key == key), None)
        head_index = next((i for i, volume in enumerate(head_records) if volume.bone_key == key), None)
        if body_index is None or head_index is None:
            raise ValueError("PABV body/head merge requires Bip01 Head in both sources.")
        records[body_index] = head_records[head_index]
        origins[body_index] = (1, head_index)
    return PabvVolumeMerge(PabvVolumes(3, tuple(records)), tuple(origins))


def pabv_cloth_collider_definition(volume: PabvVolume, *, resolved_flags: int) -> bytes:
    """Pack one supported character collider into the decoded 104-byte layout.

    The caller must supply the final runtime flags. The CPU producer rewrites
    source flag bits 1..3 from three bone sets; copying volume.flags alone does
    not reproduce that selection. Group activation, shape deduplication, bone
    mapping and resource dispatch remain caller work. Box/mesh volumes stay
    available for inspection but cannot enter the decoded primitive contacts.
    """
    if isinstance(resolved_flags, bool) or not isinstance(resolved_flags, int) or not 0 <= resolved_flags <= 0xFFFFFFFF:
        raise ValueError("PABV collider flags must be a resolved uint32.")
    if volume.shape_type not in (1, 3, 5):
        raise ValueError("PABV cloth contacts currently require a sphere, cylinder or capsule.")
    expected = 1 if volume.shape_type == 1 else 2
    if len(volume.parameters) != expected or len(volume.local_matrix) != 16:
        raise ValueError("PABV collider geometry is incomplete.")
    if (not all(math.isfinite(value) for value in (*volume.local_matrix, *volume.parameters))
            or any(value < 0 for value in volume.parameters)):
        raise ValueError("PABV collider geometry must be finite with nonnegative dimensions.")
    radius = volume.parameters[0]
    height = 0.0 if volume.shape_type == 1 else volume.parameters[1]
    # The skeleton-volume producer sets the low type word and both local
    # centers to zero. The guide update derives centers from this matrix.
    return struct.pack(
        "<I24fI", volume.shape_type << 16, radius, height,
        *volume.local_matrix, *([0.0] * 6), resolved_flags,
    )


def default_pabv_cloth_flag_bone_sets() -> dict[int, frozenset[int]]:
    """Return the fresh manager's collider flag sets in build 1.0.0.2944.

    PbdConfig loading at 0x1435F5F87..0x1435F6364 populates each empty set
    with these case-sensitive bone names. Existing nonempty runtime sets are
    retained by the game; this helper represents only the initial profile.
    Selection remains explicit in prepare_pabv_cloth_colliders. These sets
    are separate from individual simulation materials' collision filters.
    """
    from cdmw.core.archive_format import calculate_pa_checksum

    legs = (
        "Bip01 R Thigh", "Bip01 L Thigh", "Bip01 R Calf", "Bip01 L Calf",
        "Bip01 R Foot", "Bip01 L Foot",
    )
    names = {
        2: ("Bip01 Pelvis", *legs),
        4: ("Bip01 L UpperArm", "Bip01 R UpperArm"),
        8: legs,
    }
    # 0x141364800 uses the same length + 0xDEBA1DCD lookup3 initialization
    # and finalization as the existing PA checksum helper, without a NUL byte.
    return {bit: frozenset(calculate_pa_checksum(name) for name in bones)
            for bit, bones in names.items()}


def prepare_pabv_cloth_colliders(
    volumes: PabvVolumes, skeleton: Skeleton, *,
    flag_bone_sets: Mapping[int, Collection[int]],
) -> PabvClothColliders:
    """Prepare primitive definitions in the CPU producer's source order.

    The caller supplies the three actual runtime bone-hash sets keyed by their
    output bits 0x2, 0x4 and 0x8. All three must be explicit, including empty
    sets. They replace those bits; other authored flags remain unchanged. The
    material XML name lists are a separate source and must not be assumed to
    be these sets without resolving the runtime owner.

    The producer keeps the first definition when both type words and flags
    match and each radius/height/matrix float differs by at most float32(0.001).
    Bone identity is not part of that comparison. Returned bindings and source
    ordinals follow the first kept records, matching the mapped-output branch.
    This does not implement live resource discovery or the instance's later
    mapper/LOD updates. has_activation_flag reports the producer's OR of
    definition flag bit 0. Instance+0x49 retains it; the CPU group builder maps
    it to group bit 0x4, permitting same-source consideration for the same PAC.
    It is not a general collider-group enable switch.
    """
    if (set(flag_bone_sets) != {2, 4, 8}
            or any(type(bit) is not int for bit in flag_bone_sets)):
        raise ValueError("PABV preparation requires explicit bone sets for bits 0x2, 0x4 and 0x8.")
    sets = {}
    for bit, values in flag_bone_sets.items():
        if any(type(value) is not int or not 0 <= value <= 0xFFFFFFFF for value in values):
            raise ValueError("PABV runtime bone sets must contain uint32 hashes.")
        sets[bit] = frozenset(values)

    bindings = resolve_pabv_bones(volumes, skeleton)
    definitions, kept_bindings, ordinals, geometry = [], [], [], []
    has_activation = False
    tolerance = f32(.001)
    for ordinal, (volume, bone_index) in enumerate(zip(volumes.volumes, bindings)):
        bone_hash = skeleton.bones[bone_index].name_hash
        flags = volume.flags & ~0xE
        for bit, hashes in sets.items():
            if bone_hash in hashes:
                flags |= bit
        definition = pabv_cloth_collider_definition(volume, resolved_flags=flags)
        has_activation |= bool(flags & 1)
        values = struct.unpack_from('<18f', definition, 4)
        duplicate = False
        for previous, previous_values in zip(definitions, geometry):
            if previous[:4] != definition[:4] or previous[100:] != definition[100:]:
                continue
            # Large finite differences cannot match, and might overflow during
            # float32 subtraction. Only the tolerance neighborhood needs rounding.
            if all(abs(a - b) <= 2 * tolerance and abs(f32(a - b)) <= tolerance
                   for a, b in zip(values, previous_values)):
                duplicate = True
                break
        if duplicate:
            continue
        definitions.append(definition)
        geometry.append(values)
        kept_bindings.append(bone_index)
        ordinals.append(ordinal)
    return PabvClothColliders(
        tuple(definitions), tuple(kept_bindings), tuple(ordinals), has_activation,
    )
