"""Read-only PABC/PAMT character-appearance parsing and mesh deformation."""

from __future__ import annotations

import copy
import math
import struct
from dataclasses import dataclass
from typing import Mapping, Sequence

from .mesh_parser import ParsedMesh, SubMesh
from .skeleton_parser import PAR_MAGIC

PABC_RECORD_OFFSET = 0x14
PABC_RECORD_STRIDE = 196
PABC_FLOAT_COUNT = 48
PAMT_HEADER_SIZE = 0x12
PAMT_TRANSFORM_FLOAT_COUNT = 10
PAMT_BONE_TRANSFORM_FLOAT_COUNT = 20
PAMT_BONE_TRANSFORM_STRIDE = PAMT_BONE_TRANSFORM_FLOAT_COUNT * 4
_MAX_PAMT_BONES = 4096
_MAX_PAMT_TARGETS = 1024


@dataclass(frozen=True, slots=True)
class SkeletonTransform:
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PamtMorphBone:
    index: int
    name_hash: int
    name: str
    parent_index: int


@dataclass(frozen=True, slots=True)
class PamtMorphBoneTransform:
    global_transform: SkeletonTransform
    local_transform: SkeletonTransform


@dataclass(frozen=True, slots=True)
class PamtMorphTarget:
    index: int
    name_hash: int
    name: str
    marker: int
    bone_transforms: tuple[PamtMorphBoneTransform, ...] = ()


@dataclass(frozen=True, slots=True)
class PamtMorphTargetSet:
    path: str = ""
    bone_count: int = 0
    bones: tuple[PamtMorphBone, ...] = ()
    target_count: int = 0
    targets: tuple[PamtMorphTarget, ...] = ()
    tail_size: int = 0
    parser_mode: str = "pamt_skeleton_morph_targets_v1"
    confidence: str = ""


@dataclass(frozen=True, slots=True)
class SkeletonVariationRecord:
    index: int
    offset: int
    bone_hash: int
    bone_index: int = -1
    bone_name: str = ""
    matrix_blocks: tuple[tuple[float, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class SkeletonVariation:
    path: str = ""
    format_version: int = 0
    record_count: int = 0
    records: tuple[SkeletonVariationRecord, ...] = ()
    record_offset: int = PABC_RECORD_OFFSET
    record_stride: int = PABC_RECORD_STRIDE
    tail_size: int = 0
    trailer_tag: int = 0
    secondary_table_tag: int = 0
    duplicate_record_table: bool = False
    parser_mode: str = "pabc_hash_bound_matrix_blocks"
    confidence: str = ""

    @property
    def matched_record_count(self) -> int:
        return sum(1 for record in self.records if record.bone_index >= 0)


def parse_pabc_skeleton_variation(data: bytes, filename: str = "", *, skeleton: object | None = None) -> SkeletonVariation:
    """Parse PABC records proven by real samples as bone-hash plus 48 floats."""

    if len(data) < PABC_RECORD_OFFSET or data[:4] != PAR_MAGIC:
        raise ValueError(f"Not a valid PABC/PAR file: {data[:4]!r}")
    record_count = struct.unpack_from("<I", data, 0x10)[0]
    if record_count <= 0:
        return SkeletonVariation(path=filename, format_version=data[4], record_count=0, confidence="empty")
    table_end = PABC_RECORD_OFFSET + record_count * PABC_RECORD_STRIDE
    if table_end > len(data):
        raise ValueError(
            f"PABC record table exceeds file size: count={record_count} stride={PABC_RECORD_STRIDE} size={len(data)}"
        )

    tail = data[table_end:]
    trailer_tag = 0
    secondary_table_tag = 0
    duplicate_record_table = False
    if len(tail) == 4:
        trailer_tag = struct.unpack_from("<I", tail, 0)[0]
    elif len(tail) == 8 + record_count * PABC_RECORD_STRIDE:
        secondary_table_tag, secondary_count = struct.unpack_from("<II", tail, 0)
        if secondary_count != record_count:
            raise ValueError(
                f"PABC duplicate table count differs from the primary table: {secondary_count} != {record_count}"
            )
        if tail[8:] != data[PABC_RECORD_OFFSET:table_end]:
            raise ValueError("PABC duplicate table does not match the primary record table")
        duplicate_record_table = True
    else:
        raise ValueError(f"PABC trailing layout is not recognized: {len(tail)} byte(s)")

    bone_lookup = _bone_hash_lookup(skeleton)
    records: list[SkeletonVariationRecord] = []
    for index in range(record_count):
        offset = PABC_RECORD_OFFSET + index * PABC_RECORD_STRIDE
        bone_hash = struct.unpack_from("<I", data, offset)[0]
        floats = struct.unpack_from(f"<{PABC_FLOAT_COUNT}f", data, offset + 4)
        bone_index, bone_name = bone_lookup.get(bone_hash, (-1, ""))
        records.append(
            SkeletonVariationRecord(
                index=index,
                offset=offset,
                bone_hash=bone_hash,
                bone_index=bone_index,
                bone_name=bone_name,
                matrix_blocks=(
                    tuple(floats[0:16]),
                    tuple(floats[16:32]),
                    tuple(floats[32:48]),
                ),
            )
        )

    matched = sum(1 for record in records if record.bone_index >= 0)
    confidence = "bone_hash_table_stride_196"
    if bone_lookup and matched == record_count:
        confidence = "all_records_match_pab_bone_hashes"
    elif bone_lookup and matched > 0:
        confidence = "partial_records_match_pab_bone_hashes"
    if duplicate_record_table:
        confidence += "_exact_duplicate"
    return SkeletonVariation(
        path=filename,
        format_version=data[4],
        record_count=record_count,
        records=tuple(records),
        tail_size=len(tail),
        trailer_tag=trailer_tag,
        secondary_table_tag=secondary_table_tag,
        duplicate_record_table=duplicate_record_table,
        confidence=confidence,
    )


def parse_pamt_morph_target_set(data: bytes, filename: str = "") -> PamtMorphTargetSet:
    """Parse the named skeletal targets linked by ``MorphTargetSet`` prefab data.

    The shipped character PAMT is a PAR payload, not an archive index. It starts
    with a hash/name/parent bone table, followed by named targets. Every target
    carries one global and one local scale/quaternion/position transform per
    bone. The trailing two bytes are retained as unowned tail data.
    """

    if len(data) < PAMT_HEADER_SIZE or data[:4] != PAR_MAGIC:
        raise ValueError(f"Not a valid morph-target PAMT/PAR file: {data[:4]!r}")
    bone_count = struct.unpack_from("<H", data, 0x10)[0]
    if bone_count <= 0 or bone_count > _MAX_PAMT_BONES:
        raise ValueError(f"PAMT bone count is invalid: {bone_count}")

    offset = PAMT_HEADER_SIZE
    bones: list[PamtMorphBone] = []
    for index in range(bone_count):
        name_hash, name, parent_index, offset = _read_pamt_named_bone(data, offset, index)
        if parent_index < -1 or parent_index >= bone_count:
            raise ValueError(f"PAMT bone {index} parent index is invalid: {parent_index}")
        bones.append(PamtMorphBone(index, name_hash, name, parent_index))

    if offset + 2 > len(data):
        raise ValueError("PAMT target count is truncated")
    target_count = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    if target_count <= 0 or target_count > _MAX_PAMT_TARGETS:
        raise ValueError(f"PAMT target count is invalid: {target_count}")

    targets: list[PamtMorphTarget] = []
    seen_names: set[str] = set()
    for target_index in range(target_count):
        if offset + 5 > len(data):
            raise ValueError(f"PAMT target {target_index} header is truncated")
        name_hash = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        name_length = data[offset]
        offset += 1
        if name_length <= 0 or offset + name_length + 2 > len(data):
            raise ValueError(f"PAMT target {target_index} name is truncated")
        name = data[offset : offset + name_length].decode("utf-8", "strict")
        offset += name_length
        normalized_name = name.casefold()
        if normalized_name in seen_names:
            raise ValueError(f"PAMT target name is duplicated: {name}")
        seen_names.add(normalized_name)
        marker = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        target_end = offset + bone_count * PAMT_BONE_TRANSFORM_STRIDE
        if target_end > len(data):
            raise ValueError(f"PAMT target {name} transform table is truncated")
        transforms: list[PamtMorphBoneTransform] = []
        for bone_index in range(bone_count):
            values = struct.unpack_from(
                f"<{PAMT_BONE_TRANSFORM_FLOAT_COUNT}f",
                data,
                offset + bone_index * PAMT_BONE_TRANSFORM_STRIDE,
            )
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"PAMT target {name} bone {bone_index} contains a non-finite transform")
            transforms.append(
                PamtMorphBoneTransform(
                    global_transform=_skeleton_transform(values[:PAMT_TRANSFORM_FLOAT_COUNT]),
                    local_transform=_skeleton_transform(values[PAMT_TRANSFORM_FLOAT_COUNT:]),
                )
            )
        offset = target_end
        targets.append(PamtMorphTarget(target_index, name_hash, name, marker, tuple(transforms)))

    base_count = sum(target.name.casefold() == "base" for target in targets)
    if base_count != 1:
        raise ValueError(f"PAMT requires exactly one base target; found {base_count}")
    marker_sequence = tuple(target.marker for target in targets)
    confidence = (
        "named_targets_exact_stride_80_marker_step_10"
        if marker_sequence == tuple(index * 10 for index in range(target_count))
        else "named_targets_exact_stride_80"
    )
    return PamtMorphTargetSet(
        path=filename,
        bone_count=bone_count,
        bones=tuple(bones),
        target_count=target_count,
        targets=tuple(targets),
        tail_size=max(0, len(data) - offset),
        confidence=confidence,
    )


def apply_skeleton_variation_to_mesh(
    mesh: ParsedMesh,
    skeleton: object,
    bone_palette: Sequence[int],
    variation: SkeletonVariation | None,
    *,
    morph_target_set: PamtMorphTargetSet | None = None,
) -> ParsedMesh:
    """Return a presentation clone in the optional PABC neutral pose with PAMT targets.

    Source positions, raw records, topology provenance, and archive bytes remain
    untouched. PAC vertices use the proven row-vector skinning convention:
    ``position * original_inverse_bind * target_global_bind``. PAMT expressions
    are composed as global deltas over the head-specific PABC neutral pose.
    """

    raw_bones = tuple(getattr(skeleton, "bones", ()) or ())
    if not raw_bones:
        raise ValueError("Skeleton variation requires a parsed skeleton")
    palette = tuple(int(value) for value in bone_palette)
    if not palette:
        raise ValueError("Skeleton variation requires a resolved PAC bone palette")
    if any(index < 0 or index >= len(raw_bones) for index in palette):
        raise ValueError("PAC bone palette references a missing skeleton bone")

    neutral_globals = [_bone_bind_matrix(bone) for bone in raw_bones]
    if variation is not None:
        for record in variation.records:
            if record.bone_index < 0:
                continue
            if record.bone_index >= len(neutral_globals):
                raise ValueError(f"PABC record references missing bone index {record.bone_index}")
            neutral_globals[record.bone_index] = _matrix4(record.matrix_blocks[0])
    skin_matrices = _skin_matrices(raw_bones, neutral_globals)

    clone = copy.copy(mesh)
    clone.submeshes = []
    morph_globals = _morph_target_globals(raw_bones, neutral_globals, morph_target_set)
    for source_submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        submesh = copy.copy(source_submesh)
        submesh.vertices = _deform_positions(source_submesh, palette, skin_matrices)
        submesh.normals = _deform_normals(source_submesh, palette, skin_matrices)
        submesh.morph_targets = {
            name: _deform_positions(source_submesh, palette, target_skin_matrices)
            for name, target_skin_matrices in morph_globals
        }
        clone.submeshes.append(submesh)
    if variation is not None:
        setattr(clone, "_cdmw_skeleton_variation_source", variation.path)
    if morph_target_set is not None:
        setattr(clone, "_cdmw_morph_target_set_source", morph_target_set.path)
    return clone


def _read_pamt_named_bone(data: bytes, offset: int, index: int) -> tuple[int, str, int, int]:
    if offset + 7 > len(data):
        raise ValueError(f"PAMT bone {index} header is truncated")
    name_hash = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    name_length = data[offset]
    offset += 1
    if name_length <= 0 or offset + name_length + 2 > len(data):
        raise ValueError(f"PAMT bone {index} name is truncated")
    name = data[offset : offset + name_length].decode("utf-8", "strict")
    offset += name_length
    parent_index = struct.unpack_from("<h", data, offset)[0]
    return name_hash, name, parent_index, offset + 2


def _skeleton_transform(values: Sequence[float]) -> SkeletonTransform:
    if len(values) != PAMT_TRANSFORM_FLOAT_COUNT:
        raise ValueError("Skeleton transform requires ten floats")
    scale = tuple(float(value) for value in values[:3])
    rotation = tuple(float(value) for value in values[3:7])
    position = tuple(float(value) for value in values[7:10])
    if any(abs(value) <= 1e-12 for value in scale):
        raise ValueError("Skeleton transform contains a zero scale")
    quaternion_length = math.sqrt(sum(value * value for value in rotation))
    if quaternion_length <= 1e-12:
        raise ValueError("Skeleton transform contains a zero quaternion")
    return SkeletonTransform(scale=scale, rotation=rotation, position=position)  # type: ignore[arg-type]


def _matrix4(values: Sequence[float]) -> tuple[float, ...]:
    if len(values) != 16 or not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Expected a finite 4x4 matrix")
    return tuple(float(value) for value in values)


def _matrix_from_transform(transform: SkeletonTransform) -> tuple[float, ...]:
    x, y, z, w = transform.rotation
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1e-12:
        raise ValueError("Cannot build a matrix from a zero quaternion")
    x, y, z, w = x / length, y / length, z / length, w / length
    sx, sy, sz = transform.scale
    px, py, pz = transform.position
    # Transposed standard quaternion matrix: Crimson uses row vectors. Scale,
    # rotation, and translation compose as S * R * T.
    return (
        sx * (1.0 - 2.0 * (y * y + z * z)), sx * (2.0 * (x * y + z * w)), sx * (2.0 * (x * z - y * w)), 0.0,
        sy * (2.0 * (x * y - z * w)), sy * (1.0 - 2.0 * (x * x + z * z)), sy * (2.0 * (y * z + x * w)), 0.0,
        sz * (2.0 * (x * z + y * w)), sz * (2.0 * (y * z - x * w)), sz * (1.0 - 2.0 * (x * x + y * y)), 0.0,
        px, py, pz, 1.0,
    )


def _matrix_multiply(left: Sequence[float], right: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        sum(float(left[row * 4 + k]) * float(right[k * 4 + column]) for k in range(4))
        for row in range(4)
        for column in range(4)
    )


def _invert_affine(matrix: Sequence[float]) -> tuple[float, ...]:
    m = _matrix4(matrix)
    a, b, c, d, e, f, g, h, i = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise ValueError("Skeleton transform matrix is singular")
    reciprocal = 1.0 / determinant
    inverse3 = (
        (e * i - f * h) * reciprocal,
        (c * h - b * i) * reciprocal,
        (b * f - c * e) * reciprocal,
        (f * g - d * i) * reciprocal,
        (a * i - c * g) * reciprocal,
        (c * d - a * f) * reciprocal,
        (d * h - e * g) * reciprocal,
        (b * g - a * h) * reciprocal,
        (a * e - b * d) * reciprocal,
    )
    tx, ty, tz = m[12], m[13], m[14]
    moved = tuple(-sum((tx, ty, tz)[k] * inverse3[k * 3 + column] for k in range(3)) for column in range(3))
    return (
        inverse3[0], inverse3[1], inverse3[2], 0.0,
        inverse3[3], inverse3[4], inverse3[5], 0.0,
        inverse3[6], inverse3[7], inverse3[8], 0.0,
        moved[0], moved[1], moved[2], 1.0,
    )


def _bone_bind_matrix(bone: object) -> tuple[float, ...]:
    return _matrix4(tuple(getattr(bone, "bind_matrix", ()) or ()))


def _bone_inverse_bind_matrix(bone: object) -> tuple[float, ...]:
    raw = tuple(getattr(bone, "inv_bind_matrix", ()) or ())
    return _matrix4(raw) if len(raw) == 16 else _invert_affine(_bone_bind_matrix(bone))


def _skin_matrices(bones: Sequence[object], target_globals: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    if len(bones) != len(target_globals):
        raise ValueError("Skeleton target bind count does not match the skeleton")
    return tuple(
        _matrix_multiply(_bone_inverse_bind_matrix(bone), target_globals[index])
        for index, bone in enumerate(bones)
    )


def _morph_target_globals(
    bones: Sequence[object],
    neutral_globals: Sequence[Sequence[float]],
    morph_target_set: PamtMorphTargetSet | None,
) -> tuple[tuple[str, tuple[tuple[float, ...], ...]], ...]:
    if morph_target_set is None:
        return ()
    base = next(target for target in morph_target_set.targets if target.name.casefold() == "base")
    pamt_index_by_hash = {bone.name_hash: bone.index for bone in morph_target_set.bones if bone.name_hash}
    result: list[tuple[str, tuple[tuple[float, ...], ...]]] = []
    for target in morph_target_set.targets:
        if target.name.casefold() == "base":
            continue
        target_globals: list[tuple[float, ...]] = []
        for bone_index, bone in enumerate(bones):
            pamt_index = pamt_index_by_hash.get(int(getattr(bone, "name_hash", 0) or 0))
            neutral = _matrix4(neutral_globals[bone_index])
            if pamt_index is None:
                target_globals.append(neutral)
                continue
            base_global = _matrix_from_transform(base.bone_transforms[pamt_index].global_transform)
            target_global = _matrix_from_transform(target.bone_transforms[pamt_index].global_transform)
            delta = _matrix_multiply(_invert_affine(base_global), target_global)
            target_globals.append(_matrix_multiply(neutral, delta))
        result.append((target.name, _skin_matrices(bones, target_globals)))
    return tuple(result)


def _influences(
    slots: Sequence[int],
    weights: Sequence[float],
    palette: Sequence[int],
    matrix_count: int,
) -> tuple[tuple[int, float], ...]:
    if len(slots) != len(weights):
        return ()
    rows: list[tuple[int, float]] = []
    for raw_slot, raw_weight in zip(slots, weights):
        slot = int(raw_slot)
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight <= 0.0 or slot < 0 or slot >= len(palette):
            continue
        bone_index = int(palette[slot])
        if 0 <= bone_index < matrix_count:
            rows.append((bone_index, weight))
    total = math.fsum(weight for _bone, weight in rows)
    if total <= 0.0:
        return ()
    return tuple((bone, weight / total) for bone, weight in rows)


def _deform_positions(
    submesh: SubMesh,
    palette: Sequence[int],
    matrices: Sequence[Sequence[float]],
) -> list[tuple[float, float, float]]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    if len(indices) != len(vertices) or len(weights) != len(vertices):
        return [tuple(float(value) for value in vertex[:3]) for vertex in vertices]
    result: list[tuple[float, float, float]] = []
    for vertex, row_slots, row_weights in zip(vertices, indices, weights):
        influences = _influences(row_slots, row_weights, palette, len(matrices))
        if not influences:
            result.append(tuple(float(value) for value in vertex[:3]))
            continue
        point = (float(vertex[0]), float(vertex[1]), float(vertex[2]), 1.0)
        moved = [0.0, 0.0, 0.0]
        for bone_index, weight in influences:
            matrix = matrices[bone_index]
            for column in range(3):
                moved[column] += weight * sum(point[row] * float(matrix[row * 4 + column]) for row in range(4))
        result.append((moved[0], moved[1], moved[2]))
    return result


def _deform_normals(
    submesh: SubMesh,
    palette: Sequence[int],
    matrices: Sequence[Sequence[float]],
) -> list[tuple[float, float, float]]:
    normals = tuple(getattr(submesh, "normals", ()) or ())
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    if len(normals) != len(vertices) or len(indices) != len(vertices) or len(weights) != len(vertices):
        return [tuple(float(value) for value in normal[:3]) for normal in normals]
    inverse_linear_transposes: list[tuple[float, ...]] = []
    for matrix in matrices:
        inverse = _invert_affine(matrix)
        inverse_linear_transposes.append(
            (
                inverse[0], inverse[4], inverse[8],
                inverse[1], inverse[5], inverse[9],
                inverse[2], inverse[6], inverse[10],
            )
        )
    result: list[tuple[float, float, float]] = []
    for normal, row_slots, row_weights in zip(normals, indices, weights):
        influences = _influences(row_slots, row_weights, palette, len(matrices))
        if not influences:
            result.append(tuple(float(value) for value in normal[:3]))
            continue
        source = tuple(float(value) for value in normal[:3])
        moved = [0.0, 0.0, 0.0]
        for bone_index, weight in influences:
            matrix = inverse_linear_transposes[bone_index]
            for column in range(3):
                moved[column] += weight * sum(source[row] * matrix[row * 3 + column] for row in range(3))
        length = math.sqrt(math.fsum(value * value for value in moved))
        result.append(
            tuple(value / length for value in moved) if length > 1e-12 else source
        )
    return result


def _bone_hash_lookup(skeleton: object | None) -> Mapping[int, tuple[int, str]]:
    if skeleton is None:
        return {}
    result: dict[int, tuple[int, str]] = {}
    for bone in tuple(getattr(skeleton, "bones", ()) or ()):
        try:
            bone_hash = int(getattr(bone, "name_hash", 0) or 0)
            bone_index = int(getattr(bone, "index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if bone_hash:
            result[bone_hash] = (bone_index, str(getattr(bone, "name", "") or ""))
    return result


__all__ = [
    "PAMT_BONE_TRANSFORM_STRIDE",
    "PAMT_HEADER_SIZE",
    "PABC_FLOAT_COUNT",
    "PABC_RECORD_OFFSET",
    "PABC_RECORD_STRIDE",
    "PamtMorphBone",
    "PamtMorphBoneTransform",
    "PamtMorphTarget",
    "PamtMorphTargetSet",
    "SkeletonTransform",
    "SkeletonVariation",
    "SkeletonVariationRecord",
    "apply_skeleton_variation_to_mesh",
    "parse_pabc_skeleton_variation",
    "parse_pamt_morph_target_set",
]
