"""Exact PAC LOD0 serializer for validated topology changes.

This sits beside the in-place patcher and the generic full rebuild in
:mod:`cdmw.modding.mesh_pac_builder` and shares nothing with them. The generic
rebuild picks spatial donors and regenerates lower stored LOD variants, which is
right for importing a different model and wrong here: a topology edit of the
game's own mesh has exact provenance, so every output vertex either *is* an
original record or is derived from named original parents.

What this writer will not do, ever: choose a nearest donor, transfer skin weights
by proximity, drop a bone influence to fit six slots, guess a byte it has not
proven, or move the descriptor bounds. Lower LODs stay byte-identical except
for an explicitly deleted whole part or verified byte-identical copies of LOD0
that must follow a provenance-backed Remove Doubles operation.
Explicit skin edits may replace a direct survivor's proven skin lanes only
when its recorded authored row and original donor identity still validate.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Mapping, Sequence

from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.domain.mesh.topology import (
    SubmeshTopologyProvenance,
    TOPOLOGY_BOUNDS_EXCEED_SOURCE,
    TOPOLOGY_CONTRACT_UNSUPPORTED,
    TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED,
    TOPOLOGY_MAX_PAC_VERTEX_COUNT,
    TOPOLOGY_MAX_SKIN_INFLUENCES,
    TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED,
    TOPOLOGY_PROTECTED_BYTES_DIVERGE,
    TOPOLOGY_PROVENANCE_REQUIRED,
    TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_OPERATION_REMOVE_DOUBLES,
    TOPOLOGY_REBUILDABLE_OPERATIONS,
    TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,
    validate_topology_operation_history,
    validate_topology_provenance,
    identity_topology_provenance,
)

from .logging import get_logger
from .mesh_parser import (
    PAC_SKIN_PALETTE_SLOTS,
    PAC_SKIN_SLOT_BITS,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_SLOT_MASK,
    PAC_SKIN_SLOTS_PER_GROUP,
    PAC_SKIN_WEIGHT_LAYOUT,
    PAC_SKIN_WEIGHT_OFFSET,
    ParsedMesh,
    SubMesh,
    _find_pac_descriptors,
    _parse_par_sections,
    _validated_pac_descriptor_prefix,
    parse_pac,
)
from .mesh_pac_builder import _pack_pac_normal, _quantize_pac_u16
from .mesh_skinning import pack_pac_skin_weights

logger = get_logger("core.mesh_importer")

TOPOLOGY_SERIALIZER_ID = "pac_lod0_topology_exact_v1"
PROVEN_PAC_STRIDE = 40

#: Owned byte ranges of a proven 40-byte record, as [start, end) pairs.
_OWNED_RANGES_ALWAYS = ((0, 6), (8, 12), (16, 20))
_OWNED_RANGES_SKINNED = ((20, 28), (28, 34))
#: The top two bits of each owned u32 carry nothing we have proven, so they stay
#: protected even though the rest of their lane is ours to write.
_OWNED_U32_OFFSETS = (16, 20, 24)


class PacTopologyRebuildBlocked(ValueError):
    """The exact serializer refused to write. Carries stable blocker codes."""

    def __init__(self, blockers: Sequence[str], message: str) -> None:
        super().__init__(message)
        self.blockers = tuple(dict.fromkeys(str(code) for code in blockers))


def protected_byte_mask(*, skinned: bool, stride: int = PROVEN_PAC_STRIDE) -> bytes:
    """Per-byte mask of the bits a rebuild must leave exactly as it found them."""
    mask = bytearray(b"\xff" * stride)
    ranges = list(_OWNED_RANGES_ALWAYS)
    if skinned:
        ranges.extend(_OWNED_RANGES_SKINNED)
    for start, end in ranges:
        for offset in range(start, min(end, stride)):
            mask[offset] = 0x00
    for u32_offset in _OWNED_U32_OFFSETS:
        if u32_offset + 4 <= stride and mask[u32_offset + 3] == 0x00:
            mask[u32_offset + 3] = 0xC0
    return bytes(mask)


def _masked(record: bytes, mask: bytes) -> bytes:
    result = bytearray(value & mask_value for value, mask_value in zip(record, mask))
    if len(record) == PROVEN_PAC_STRIDE and record[39] & 63 != 63:
        # Cloth guide bindings are inherited, never interpolated as bone slots.
        struct.pack_into("<I", result, 24, struct.unpack_from("<I", result, 24)[0]
                         | (struct.unpack_from("<I", record, 24)[0] & 0xFFFFFC00))
        result[32:36] = record[32:36]
    return bytes(result)


def _decoded_live_slots(record: bytes) -> tuple[tuple[int, ...], tuple[int, ...]]:
    slots: list[int] = []
    for group_offset in PAC_SKIN_SLOT_GROUPS:
        group = struct.unpack_from("<I", record, group_offset)[0]
        slots.extend(
            (group >> (PAC_SKIN_SLOT_BITS * position)) & PAC_SKIN_SLOT_MASK
            for position in range(PAC_SKIN_SLOTS_PER_GROUP)
        )
    capacity = 4 if record[39] & 63 != 63 else PAC_SKIN_PALETTE_SLOTS
    weights = struct.unpack_from(f"<{capacity}B", record, PAC_SKIN_WEIGHT_OFFSET)
    live = [(slot, weight) for slot, weight in zip(slots, weights) if weight > 0]
    return tuple(slot for slot, _ in live), tuple(weight for _, weight in live)


def derived_skin_row(
    parent_records: Sequence[bytes],
    weights: Sequence[float],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Merge parent skin rows into one normalized row, losing no live influence.

    Observed source rows total ``255 +/- 2``, so each parent row is normalized on
    its own before it is scaled. Nothing is dropped: if the union needs more than
    six slots the caller blocks rather than selecting a top six.
    """
    merged: dict[int, list[float]] = {}
    for record, topology_weight in zip(parent_records, weights):
        slots, byte_weights = _decoded_live_slots(record)
        if not slots:
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_PROVENANCE_REQUIRED,),
                "A skinned parent record carries no positive influence to derive from.",
            )
        parent_total = math.fsum(float(value) for value in byte_weights)
        if parent_total <= 0.0:
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_PROVENANCE_REQUIRED,),
                "A skinned parent record has a non-positive influence total.",
            )
        for slot, byte_weight in zip(slots, byte_weights):
            merged.setdefault(slot, []).append(float(byte_weight) / parent_total * float(topology_weight))
    if not merged:
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_PROVENANCE_REQUIRED,), "Derived vertex has no parent influence to merge."
        )
    totals = {slot: math.fsum(values) for slot, values in merged.items()}
    live = {slot: value for slot, value in totals.items() if value > 0.0}
    capacity = 4 if any(record[39] & 63 != 63 for record in parent_records) else TOPOLOGY_MAX_SKIN_INFLUENCES
    if len(live) > capacity:
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,),
            f"Derived vertex needs {len(live)} palette slots; this writer authors "
            f"{capacity} for these records. Cloth guide lanes are inherited unchanged.",
        )
    total = math.fsum(live.values())
    if total <= 0.0 or not math.isfinite(total):
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_PROVENANCE_REQUIRED,), "Derived skin row does not sum to a positive total."
        )
    ordered = sorted(((slot, value / total) for slot, value in live.items()), key=lambda item: (-item[1], item[0]))
    return tuple(slot for slot, _ in ordered), tuple(value for _, value in ordered)


def _submesh_is_proven_layout(submesh: SubMesh, *, skinned_required: bool) -> bool:
    if int(getattr(submesh, "source_vertex_stride", 0) or 0) != PROVEN_PAC_STRIDE:
        return False
    offsets = tuple(getattr(submesh, "source_vertex_offsets", ()) or ())
    if len(offsets) != len(tuple(getattr(submesh, "vertices", ()) or ())):
        return False
    if any(int(value) < 0 for value in offsets):
        return False
    if skinned_required and str(getattr(submesh, "source_skin_weight_layout", "") or "") != PAC_SKIN_WEIGHT_LAYOUT:
        return False
    return True


def _submesh_is_skinned(submesh: SubMesh) -> bool:
    return any(bool(row) for row in tuple(getattr(submesh, "bone_indices", ()) or ()))


def _bounds_blockers(
    original: SubMesh,
    edited: SubMesh,
) -> tuple[str, ...]:
    """Authored positions must stay inside the original descriptor bounds.

    One source quantization unit of slack per axis, because a position that
    round-trips through the original u16 frame can land a unit outside the raw
    float extent without meaning anything.
    """
    bbox_min = tuple(float(value) for value in tuple(getattr(original, "source_bbox_min", ()) or ()))
    extent = tuple(float(value) for value in tuple(getattr(original, "source_bbox_extent", ()) or ()))
    if len(bbox_min) != 3 or len(extent) != 3:
        return (TOPOLOGY_CONTRACT_UNSUPPORTED,)
    for axis in range(3):
        unit = abs(extent[axis]) / 32767.0 if abs(extent[axis]) > 1e-10 else 0.0
        low = bbox_min[axis] - unit
        high = bbox_min[axis] + extent[axis] + unit
        for position in tuple(getattr(edited, "vertices", ()) or ()):
            value = float(position[axis])
            if not math.isfinite(value) or value < low or value > high:
                return (TOPOLOGY_BOUNDS_EXCEED_SOURCE,)
    return ()


def topology_rebuild_blockers(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    original_data: bytes,
) -> tuple[str, ...]:
    """Every reason the exact LOD0 serializer must refuse this pair.

    An empty tuple means the pair is admissible. This never mutates anything and
    never falls back; it is the single admission gate the writer routes through.
    """
    blockers: list[str] = []
    if not original_data or original_data[:4] != b"PAR ":
        return (TOPOLOGY_CONTRACT_UNSUPPORTED,)
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    edited_submeshes = tuple(getattr(edited_mesh, "submeshes", ()) or ())
    if not original_submeshes or len(original_submeshes) != len(edited_submeshes):
        return (TOPOLOGY_CONTRACT_UNSUPPORTED,)

    blockers.extend(_layout_blockers(original_mesh, edited_mesh, original_data))

    changed = 0
    for original, edited in zip(original_submeshes, edited_submeshes):
        provenance = getattr(edited, "topology_provenance", None)
        vertices = tuple(getattr(edited, "vertices", ()) or ())
        faces = tuple(getattr(edited, "faces", ()) or ())
        if provenance is None:
            # An unchanged submesh needs no contract; a changed one does.
            if len(vertices) != len(tuple(getattr(original, "vertices", ()) or ())) or len(faces) != len(
                tuple(getattr(original, "faces", ()) or ())
            ):
                blockers.append(TOPOLOGY_PROVENANCE_REQUIRED)
            continue
        changed += 1
        if bool(vertices) != bool(faces):
            blockers.append(TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED)
            continue
        if not vertices and any(getattr(edited, attr, ()) for attr in (
            "uvs", "normals", "tangents", "shader_masks", "bone_indices", "bone_weights",
            "source_vertex_map", "source_vertex_offsets",
        )):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
        if len(vertices) > TOPOLOGY_MAX_PAC_VERTEX_COUNT:
            blockers.append(TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED)
        blockers.extend(
            validate_topology_provenance(
                provenance,
                output_vertex_count=len(vertices),
                output_face_count=len(faces),
            )
        )
        if not isinstance(provenance, SubmeshTopologyProvenance):
            continue
        if (
            provenance.original_vertex_count != len(tuple(getattr(original, "vertices", ()) or ()))
            or provenance.original_face_count != len(tuple(getattr(original, "faces", ()) or ()))
        ):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        skinned = _submesh_is_skinned(original)
        if not _submesh_is_proven_layout(original, skinned_required=skinned):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        blockers.extend(_bounds_blockers(original, edited))
        blockers.extend(_derivation_blockers(original, provenance, original_data, skinned=skinned))

    if changed <= 0:
        blockers.append(TOPOLOGY_PROVENANCE_REQUIRED)
    deleted = _deleted_part_indices(edited_mesh)
    if deleted and not blockers:
        try:
            # Prove every stored LOD and the hidden draw before rebuilding.
            # Shared records, ambiguous slots and unrepresentable bounds refuse
            # the entire export; none may enter the generic donor rebuild.
            _hide_deleted_pac_parts(original_data, deleted)
        except ValueError:
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
    return tuple(dict.fromkeys(blockers))


def _deleted_part_indices(mesh: ParsedMesh) -> tuple[int, ...]:
    return tuple(index for index, part in enumerate(mesh.submeshes)
                 if part.topology_provenance is not None and not part.vertices and not part.faces)


def _hide_deleted_pac_parts(data: bytes, deleted: Sequence[int]) -> bytes:
    """Suppress only named descriptor slots, without remapping lower-LOD faces.

    Zero-count draws are unsafe for PAC consumers. Retain each slot's original
    records and counts, collapse its indices, and clone one exact source corner
    into a quantization-sized triangle. Identical skin/guide data keeps that
    triangle tiny during animation too. This is an output projection only.
    """
    from .mesh_islands import _preserve_empty_island_part
    from .pac_cloth import pac_cloth_lods

    levels = pac_cloth_lods(data)
    result = bytearray(data)
    for lod_index, level in enumerate(levels):
        for index in deleted:
            part = level.submeshes[index]
            if not part.vertices and not part.faces:
                continue  # The source already omits this slot at this LOD.
            if not part.faces or part.source_index_count % 3:
                raise ValueError("Deleted PAC part has no proven triangle layout.")
            corner = part.faces[0][0]
            for face_index in range(part.source_index_count // 3):
                struct.pack_into("<3H", result, part.source_index_offset + face_index * 6,
                                 corner, corner, corner)
            _preserve_empty_island_part(result, part, lod_index)
    rebuilt = bytes(result)
    # The parser must still recover every descriptor slot, including lower-LOD
    # slots that were already absent. It must never fall back to another part.
    for before, after in zip(levels, pac_cloth_lods(rebuilt), strict=True):
        for index, (old, new) in enumerate(zip(before.submeshes, after.submeshes, strict=True)):
            if old.source_vertex_offsets != new.source_vertex_offsets:
                raise ValueError("Deleted PAC part changed its source record ownership.")
            expected = old.faces[:1] if index in deleted else old.faces
            if new.faces != expected:
                raise ValueError("Deleted PAC part changed another part's connectivity.")
    return rebuilt


def _matching_cleanup_lods(original_mesh, edited_mesh, original_data, payloads, descriptors, lod_count, section_0):
    """Synchronize cleanup only into independently stored exact LOD0 copies.

    Matching counts or positions do not prove correspondence. Require identical
    complete geometry payloads, descriptor counts and vertex/index splits, plus
    valid direct-record cleanup lineage. Distinct lower LODs keep the rank guard.
    """
    operations = mesh_edit_operations_from_dicts(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
    names = {operation.operation for operation in operations
             if operation.operation in TOPOLOGY_REBUILDABLE_OPERATIONS}
    if names != {TOPOLOGY_OPERATION_REMOVE_DOUBLES} or validate_topology_operation_history(operations):
        return ()
    if _deleted_part_indices(edited_mesh):
        return ()
    changed = False
    for original, edited in zip(original_mesh.submeshes, edited_mesh.submeshes):
        provenance = getattr(edited, "topology_provenance", None)
        if provenance is None:
            continue
        if not isinstance(provenance, SubmeshTopologyProvenance) or validate_topology_provenance(
            provenance, output_vertex_count=len(edited.vertices), output_face_count=len(edited.faces)
        ):
            return ()
        if (provenance.original_vertex_count != len(original.vertices)
                or provenance.original_face_count != len(original.faces)
                or edited.source_vertex_map_authority != "topology"
                or provenance.derived_vertex_count
                or len({origin.direct_parent for origin in provenance.vertex_origins}) != len(edited.vertices)):
            return ()
        changed = True
    if not changed:
        return ()
    reference = payloads.get(lod_count)
    if not reference:
        return ()
    split = _original_split_bytes(original_data, section_0, 0)
    if (split != sum(len(part.vertices) for part in original_mesh.submeshes) * PROVEN_PAC_STRIDE
            or len(reference) != split + sum(len(part.faces) for part in original_mesh.submeshes) * 6):
        return ()  # Unknown geometry-section bytes cannot be copied into a new layout.
    return tuple(lod for lod in range(1, lod_count)
                 if payloads.get(lod_count - lod) == reference
                 and _original_split_bytes(original_data, section_0, lod) == split
                 and all(lod < len(descriptor.vertex_counts) and lod < len(descriptor.index_counts)
                         and descriptor.vertex_counts[lod] == descriptor.vertex_counts[0]
                         and descriptor.index_counts[lod] == descriptor.index_counts[0]
                         for descriptor in descriptors))


def _layout_blockers(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    original_data: bytes,
) -> tuple[str, ...]:
    """Refuse layouts this writer would silently reshape.

    Three real hazards, all of which produce a file that parses but is not the
    asset any more:

    * a shared LOD0 vertex buffer, where two descriptors read the same records
      and re-emitting each submesh separately would duplicate them;
    * a descriptor whose stored LOD0 counts disagree with what the parser
      recovered, which means copying the parsed geometry would drop records the
      file still counts;
    * a rebuilt LOD0 that no longer outranks a stored lower LOD, because
      ``parse_pac`` picks the geometry section with the most faces, then the
      most vertices, then the most non-empty submeshes, and would otherwise
      start reading a lower LOD as LOD0.
    """
    try:
        payloads, sections, lod_count, _section_0_data, section_0 = _section_payloads(original_data)
        descriptors = _validated_pac_descriptor_prefix(
            _find_pac_descriptors(original_data, section_0["offset"], section_0["size"], lod_count),
            sections,
        )
    except PacTopologyRebuildBlocked as blocked:
        return blocked.blockers
    except Exception:
        return (TOPOLOGY_CONTRACT_UNSUPPORTED,)

    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    edited_submeshes = tuple(getattr(edited_mesh, "submeshes", ()) or ())
    deleted_indices = frozenset(_deleted_part_indices(edited_mesh))
    if len(descriptors) < len(original_submeshes):
        return (TOPOLOGY_CONTRACT_UNSUPPORTED,)
    matching_cleanup_lods = _matching_cleanup_lods(
        original_mesh, edited_mesh, original_data, payloads, descriptors, lod_count, section_0)

    blockers: list[str] = []
    seen_offsets: set[int] = set()
    output_face_total = 0
    output_vertex_total = 0
    output_non_empty = 0
    for submesh_index, (original, descriptor) in enumerate(zip(original_submeshes, descriptors)):
        vertices = tuple(getattr(original, "vertices", ()) or ())
        faces = tuple(getattr(original, "faces", ()) or ())
        offsets = tuple(int(value) for value in tuple(getattr(original, "source_vertex_offsets", ()) or ()))
        stored_vertices = int(descriptor.vertex_counts[0]) if descriptor.vertex_counts else 0
        stored_indices = int(descriptor.index_counts[0]) if descriptor.index_counts else 0
        if len(vertices) != stored_vertices or len(faces) * 3 != stored_indices:
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        if len(offsets) != len(vertices):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        if any(right - left != PROVEN_PAC_STRIDE for left, right in zip(offsets, offsets[1:])):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        if seen_offsets & set(offsets):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        seen_offsets.update(offsets)
        edited = edited_submeshes[submesh_index] if submesh_index < len(edited_submeshes) else None
        rebuilt = edited if edited is not None and getattr(edited, "topology_provenance", None) is not None else original
        deleted = not rebuilt.vertices and not rebuilt.faces
        rebuilt_faces = 1 if deleted else len(rebuilt.faces)
        rebuilt_vertices = len(original.vertices) if deleted else len(rebuilt.vertices)
        output_face_total += rebuilt_faces
        output_vertex_total += rebuilt_vertices
        if rebuilt_faces and rebuilt_vertices:
            output_non_empty += 1

    output_rank = (output_face_total, output_vertex_total, output_non_empty)
    for lod_index in range(1, lod_count):
        if lod_index in matching_cleanup_lods:
            # This stored copy will receive the same validated records/indices,
            # so its rank remains exactly tied to LOD0 after serialization.
            continue
        lower_faces = 0
        lower_vertices = 0
        lower_non_empty = 0
        for submesh_index, descriptor in enumerate(descriptors[: len(original_submeshes)]):
            faces_at_lod = (
                int(descriptor.index_counts[lod_index]) // 3 if lod_index < len(descriptor.index_counts) else 0
            )
            vertices_at_lod = (
                int(descriptor.vertex_counts[lod_index]) if lod_index < len(descriptor.vertex_counts) else 0
            )
            if faces_at_lod and submesh_index in deleted_indices:
                faces_at_lod = 1
            lower_faces += faces_at_lod
            lower_vertices += vertices_at_lod
            if faces_at_lod and vertices_at_lod:
                lower_non_empty += 1
        # A full tie is safe: the parser breaks it on section index, and LOD0
        # always holds the highest one.
        if output_rank < (lower_faces, lower_vertices, lower_non_empty):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            break
    return tuple(dict.fromkeys(blockers))


def _original_records(original: SubMesh, original_data: bytes) -> tuple[bytes, ...]:
    records: list[bytes] = []
    for offset in tuple(getattr(original, "source_vertex_offsets", ()) or ()):
        start = int(offset)
        if start < 0 or start + PROVEN_PAC_STRIDE > len(original_data):
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,), "A PAC vertex record points outside the source file."
            )
        records.append(bytes(original_data[start : start + PROVEN_PAC_STRIDE]))
    return tuple(records)


def _derivation_blockers(
    original: SubMesh,
    provenance: SubmeshTopologyProvenance,
    original_data: bytes,
    *,
    skinned: bool,
) -> tuple[str, ...]:
    """Check every derived vertex can be built exactly, without writing anything."""
    try:
        records = _original_records(original, original_data)
    except PacTopologyRebuildBlocked as blocked:
        return blocked.blockers
    mask = protected_byte_mask(skinned=skinned)
    blockers: list[str] = []
    for origin in provenance.vertex_origins:
        if not origin.derived:
            continue
        if any(parent >= len(records) for parent in origin.parents):
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        template = _masked(records[origin.parents[0]], mask)
        if any(_masked(records[parent], mask) != template for parent in origin.parents[1:]):
            blockers.append(TOPOLOGY_PROTECTED_BYTES_DIVERGE)
            continue
        if not skinned:
            continue
        try:
            slots, _weights = derived_skin_row(
                [records[parent] for parent in origin.parents], origin.weights
            )
        except PacTopologyRebuildBlocked as blocked:
            blockers.extend(blocked.blockers)
            continue
        if len(slots) > TOPOLOGY_MAX_SKIN_INFLUENCES:
            blockers.append(TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED)
    return tuple(dict.fromkeys(blockers))


def _authored_record(
    template: bytes,
    *,
    position: Sequence[float],
    uv: Sequence[float] | None,
    normal: Sequence[float] | None,
    bbox_min: Sequence[float],
    extent: Sequence[float],
    skin: tuple[Sequence[int], Sequence[float]] | None,
) -> bytes:
    """Overwrite only owned lanes of ``template``; everything else survives."""
    record = bytearray(template)
    struct.pack_into(
        "<HHH",
        record,
        0,
        _quantize_pac_u16(float(position[0]), float(bbox_min[0]), float(extent[0])),
        _quantize_pac_u16(float(position[1]), float(bbox_min[1]), float(extent[1])),
        _quantize_pac_u16(float(position[2]), float(bbox_min[2]), float(extent[2])),
    )
    if uv is not None:
        try:
            struct.pack_into("<e", record, 8, float(uv[0]))
            struct.pack_into("<e", record, 10, float(uv[1]))
        except (OverflowError, ValueError):
            struct.pack_into("<e", record, 8, 0.0)
            struct.pack_into("<e", record, 10, 0.0)
    if normal is not None:
        existing = struct.unpack_from("<I", record, 16)[0]
        struct.pack_into(
            "<I",
            record,
            16,
            _pack_pac_normal((float(normal[0]), float(normal[1]), float(normal[2])), existing),
        )
    if skin is not None:
        pack_pac_skin_weights(record, skin[0], skin[1], context="PAC topology vertex")
    return bytes(record)


def _lod0_records_for_submesh(
    original: SubMesh,
    edited: SubMesh,
    original_data: bytes,
    provenance: SubmeshTopologyProvenance | None,
    metrics: dict[str, object],
    *,
    skin_weights_authorized: bool = False,
) -> list[bytes]:
    records = _original_records(original, original_data)
    if provenance is None:
        if not skin_weights_authorized:
            return list(records)
        provenance = identity_topology_provenance(len(original.vertices), len(original.faces))

    skinned = _submesh_is_skinned(original)
    bbox_min = tuple(float(value) for value in tuple(getattr(original, "source_bbox_min", ()) or (0.0, 0.0, 0.0)))
    extent = tuple(float(value) for value in tuple(getattr(original, "source_bbox_extent", ()) or (0.0, 0.0, 0.0)))
    positions = tuple(getattr(edited, "vertices", ()) or ())
    uvs = tuple(getattr(edited, "uvs", ()) or ())
    normals = tuple(getattr(edited, "normals", ()) or ())
    has_uvs = len(uvs) == len(positions)
    has_normals = len(normals) == len(positions)

    max_absolute_error = 0.0
    l1_error = 0.0
    influence_union_width = 0
    output: list[bytes] = []
    for index, origin in enumerate(provenance.vertex_origins):
        parent_records = [records[parent] for parent in origin.parents]
        template = parent_records[0]
        skin: tuple[Sequence[int], Sequence[float]] | None = None
        reference_weights: tuple[float, ...] = ()
        reference_slots: tuple[int, ...] = ()
        if skinned and origin.derived:
            reference_slots, reference_weights = derived_skin_row(parent_records, origin.weights)
            influence_union_width = max(influence_union_width, len(reference_slots))
            skin = (reference_slots, reference_weights)
        elif skinned and skin_weights_authorized:
            parent = origin.direct_parent
            if (tuple(edited.bone_indices[index]), tuple(edited.bone_weights[index])) != (
                tuple(original.bone_indices[parent]), tuple(original.bone_weights[parent]),
            ):
                live = [(slot, weight) for slot, weight in zip(
                    edited.bone_indices[index], edited.bone_weights[index],
                ) if weight > 0.0]
                reference_slots = tuple(slot for slot, _ in live)
                reference_weights = tuple(weight for _, weight in live)
                influence_union_width = max(influence_union_width, len(reference_slots))
                skin = (reference_slots, reference_weights)
        record = _authored_record(
            template,
            position=positions[index],
            uv=uvs[index] if has_uvs else None,
            normal=normals[index] if has_normals else None,
            bbox_min=bbox_min,
            extent=extent,
            skin=skin,
        )
        if skin is not None:
            decoded_slots, decoded_bytes = _decoded_live_slots(record)
            if set(decoded_slots) != set(reference_slots):
                raise PacTopologyRebuildBlocked(
                    (TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,),
                    f"Encoding topology vertex {index} changed its live palette slot set.",
                )
            if sum(decoded_bytes) != 255:
                raise PacTopologyRebuildBlocked(
                    (TOPOLOGY_PROTECTED_BYTES_DIVERGE,),
                    f"Topology vertex {index} encoded to a byte total of {sum(decoded_bytes)}, not 255.",
                )
            decoded_by_slot = dict(zip(decoded_slots, decoded_bytes))
            for slot, weight in zip(reference_slots, reference_weights):
                error = abs(decoded_by_slot[slot] / 255.0 - weight)
                max_absolute_error = max(max_absolute_error, error)
                l1_error += error
        output.append(record)

    metrics["influence_union_width"] = influence_union_width
    metrics["lost_influence_mass"] = 0.0
    metrics["max_absolute_quantization_error"] = max_absolute_error
    metrics["l1_quantization_error"] = l1_error
    return output


def _section_payloads(original_data: bytes) -> tuple[dict[int, bytes], list[dict], int, bytearray, dict]:
    sections = _parse_par_sections(original_data)
    by_index = {section["index"]: section for section in sections}
    section_0 = by_index.get(0)
    if not section_0:
        raise PacTopologyRebuildBlocked((TOPOLOGY_CONTRACT_UNSUPPORTED,), "PAC section table is missing section 0.")
    lod_count = original_data[section_0["offset"] + 4] if section_0["size"] >= 5 else 0
    if lod_count <= 0 or lod_count > 10:
        raise PacTopologyRebuildBlocked((TOPOLOGY_CONTRACT_UNSUPPORTED,), f"Invalid PAC LOD count: {lod_count}")
    payloads = {
        section["index"]: bytes(original_data[section["offset"] : section["offset"] + section["size"]])
        for section in sections
    }
    section_0_data = bytearray(payloads[0])
    return payloads, sections, lod_count, section_0_data, section_0


def build_pac_topology_rebuild(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    original_data: bytes,
    *,
    report: dict[str, object] | None = None,
) -> bytes:
    """Rebuild LOD0 exactly; suppress fully deleted slots at every stored LOD.

    Raises :class:`PacTopologyRebuildBlocked` with stable blocker codes rather
    than producing an approximate result.
    """
    blockers = topology_rebuild_blockers(original_mesh, edited_mesh, original_data)
    if blockers:
        raise PacTopologyRebuildBlocked(
            blockers, "Exact PAC LOD0 topology rebuild is blocked: " + ", ".join(blockers)
        )

    operations = mesh_edit_operations_from_dicts(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
    skin_targets = {operation.submesh_index for operation in operations
                    if operation.operation == "replace_skin_weights_same_count" and operation.lod_index == 0}
    changed_skin = False
    for original, edited in zip(original_mesh.submeshes, edited_mesh.submeshes):
        provenance = getattr(edited, "topology_provenance", None)
        parents = (tuple(origin.direct_parent for origin in provenance.vertex_origins)
                   if provenance is not None else tuple(range(len(edited.vertices))))
        for index, parent in enumerate(parents):
            if (0 <= parent < len(original.bone_indices) and parent < len(original.bone_weights)
                    and index < len(edited.bone_indices) and index < len(edited.bone_weights)
                    and (tuple(edited.bone_indices[index]), tuple(edited.bone_weights[index]))
                    != (tuple(original.bone_indices[parent]), tuple(original.bone_weights[parent]))):
                changed_skin = True
                break
    if skin_targets or changed_skin:
        # The topology writer must never discard an authored skin edit or trust
        # rows merely because a cleanup operation is present.
        validation = validate_mesh_export(
            edited_mesh, original_mesh=original_mesh, original_data=original_data,
            skeleton_bone_count=max((int(operation.metadata.get("palette_size", 0) or 0)
                                     for operation in operations
                                     if operation.operation == "replace_skin_weights_same_count"), default=0) or None,
        )
        if not validation.ok:
            raise PacTopologyRebuildBlocked(
                tuple(issue.code for issue in validation.blockers),
                "Exact PAC skin/cleanup validation failed: " + validation.blockers[0].message,
            )

    payloads, sections, lod_count, section_0_data, section_0 = _section_payloads(original_data)
    descriptors = _validated_pac_descriptor_prefix(
        _find_pac_descriptors(original_data, section_0["offset"], section_0["size"], lod_count),
        sections,
    )
    original_submeshes = tuple(original_mesh.submeshes)
    edited_submeshes = tuple(edited_mesh.submeshes)
    deleted_submeshes = _deleted_part_indices(edited_mesh)
    if len(descriptors) < len(original_submeshes):
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_CONTRACT_UNSUPPORTED,), "PAC descriptor count does not match the parsed original submeshes."
        )
    matching_cleanup_lods = _matching_cleanup_lods(
        original_mesh, edited_mesh, original_data, payloads, descriptors, lod_count, section_0)
    rebuilt_lods = (0, *matching_cleanup_lods)

    metrics: dict[str, object] = {}
    lod0_section_index = lod_count
    vertex_buffer = bytearray()
    index_buffer = bytearray()
    original_lod0_payload = payloads.get(lod0_section_index, b"")

    direct_vertices = 0
    derived_vertices = 0
    removed_vertices = 0
    removed_faces = 0
    admitted_submeshes: list[int] = []

    for submesh_index, (original, edited, descriptor) in enumerate(
        zip(original_submeshes, edited_submeshes, descriptors)
    ):
        provenance = getattr(edited, "topology_provenance", None)
        submesh_metrics: dict[str, object] = {}
        # Keep deleted slots' source storage until the all-LOD suppression below.
        # The working mesh and its provenance remain truly empty for Undo/Redo.
        output_provenance = None if submesh_index in deleted_submeshes else provenance
        records = _lod0_records_for_submesh(
            original, edited, original_data, output_provenance, submesh_metrics,
            skin_weights_authorized=submesh_index in skin_targets and submesh_index not in deleted_submeshes,
        )
        faces = tuple(getattr(edited, "faces", ()) or ()) if output_provenance is not None else tuple(
            getattr(original, "faces", ()) or ()
        )
        for record in records:
            vertex_buffer.extend(record)
        for face in faces:
            if any(int(value) < 0 or int(value) >= len(records) for value in face[:3]):
                raise PacTopologyRebuildBlocked(
                    (TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED,),
                    f"PAC submesh {submesh_index} face references a missing vertex.",
                )
            index_buffer.extend(struct.pack("<HHH", int(face[0]), int(face[1]), int(face[2])))

        relative_descriptor = int(descriptor.descriptor_offset) - int(section_0["offset"])
        if relative_descriptor < 0 or relative_descriptor + 40 > len(section_0_data):
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,), f"PAC descriptor {submesh_index} points outside section 0."
            )
        # Only proven targets change; descriptor bounds and distinct lower LOD
        # counts remain exactly as the source wrote them.
        vertex_count_offset = relative_descriptor + 40
        index_count_offset = vertex_count_offset + descriptor.stored_lod_count * 2
        for lod_index in rebuilt_lods:
            struct.pack_into("<H", section_0_data, vertex_count_offset + lod_index * 2, len(records))
            struct.pack_into("<I", section_0_data, index_count_offset + lod_index * 4, len(faces) * 3)

        if provenance is not None:
            admitted_submeshes.append(submesh_index)
            direct_vertices += provenance.direct_vertex_count
            derived_vertices += provenance.derived_vertex_count
            removed_vertices += provenance.original_vertex_count - len(
                {parent for origin in provenance.vertex_origins for parent in origin.parents}
            )
            removed_faces += provenance.original_face_count - len(set(provenance.face_origins))
            for key, value in submesh_metrics.items():
                if key in {"max_absolute_quantization_error", "influence_union_width"}:
                    metrics[key] = max(float(metrics.get(key, 0.0)), float(value))
                elif key == "l1_quantization_error":
                    metrics[key] = float(metrics.get(key, 0.0)) + float(value)
                else:
                    metrics[key] = value

    section_payloads: dict[int, bytes] = dict(payloads)
    section_payloads[lod0_section_index] = bytes(vertex_buffer + index_buffer)
    for lod_index in matching_cleanup_lods:
        section_payloads[lod_count - lod_index] = section_payloads[lod0_section_index]
    lod0_split = len(vertex_buffer)

    header = bytearray(original_data[:0x50])
    for slot in range(8):
        struct.pack_into("<I", header, 0x10 + slot * 8, 0)
        struct.pack_into("<I", header, 0x10 + slot * 8 + 4, 0)

    section_payloads[0] = bytes(section_0_data)
    section_offsets = {0: 0x50}
    next_offset = 0x50 + len(section_payloads[0])
    for slot in range(1, 8):
        payload = section_payloads.get(slot)
        if payload is None:
            continue
        section_offsets[slot] = next_offset
        next_offset += len(payload)

    cursor = 5
    for lod_index in range(lod_count):
        section_index = lod_count - lod_index
        struct.pack_into("<I", section_0_data, cursor + lod_index * 4, section_offsets[section_index])
    cursor += lod_count * 4
    for lod_index in range(lod_count):
        section_index = lod_count - lod_index
        split = lod0_split if lod_index in rebuilt_lods else _original_split_bytes(
            original_data, section_0, lod_index
        )
        struct.pack_into("<I", section_0_data, cursor + lod_index * 4, section_offsets[section_index] + split)
    section_payloads[0] = bytes(section_0_data)

    assembled = bytearray(header)
    for slot in range(8):
        payload = section_payloads.get(slot)
        if payload is None:
            continue
        struct.pack_into("<I", assembled, 0x10 + slot * 8, 0)
        struct.pack_into("<I", assembled, 0x10 + slot * 8 + 4, len(payload))
        assembled.extend(payload)

    rebuilt = bytes(assembled)
    _verify_rebuilt_pac(
        rebuilt,
        original_data=original_data,
        original_mesh=original_mesh,
        edited_mesh=edited_mesh,
        original_lod0_payload=original_lod0_payload,
        lod0_section_index=lod0_section_index,
        payloads=payloads,
        matching_cleanup_lods=matching_cleanup_lods,
    )
    if deleted_submeshes:
        try:
            rebuilt = _hide_deleted_pac_parts(rebuilt, deleted_submeshes)
        except ValueError as exc:
            raise PacTopologyRebuildBlocked((TOPOLOGY_CONTRACT_UNSUPPORTED,), str(exc)) from exc
        reparsed = parse_pac(rebuilt, str(edited_mesh.path))
        expected_counts = [(len(original.vertices), 1) if index in deleted_submeshes else
                           (len(edited.vertices), len(edited.faces))
                           for index, (original, edited) in enumerate(zip(original_submeshes, edited_submeshes))]
        if [(len(part.vertices), len(part.faces)) for part in reparsed.submeshes] != expected_counts:
            raise PacTopologyRebuildBlocked((TOPOLOGY_CONTRACT_UNSUPPORTED,),
                                            "Deleted PAC parts changed the recovered LOD0 layout.")

    if report is not None:
        report.update(
            {
                "serializer": TOPOLOGY_SERIALIZER_ID,
                "backend": "cdmw_mesh_core_0.1",
                "contract_version": TOPOLOGY_PROVENANCE_VERSION,
                "fallback_used": False,
                "admitted_submesh_indices": tuple(admitted_submeshes),
                "direct_vertex_count": direct_vertices,
                "blended_vertex_count": derived_vertices,
                "removed_vertex_count": removed_vertices,
                "removed_face_count": removed_faces,
                "influence_union_width": int(metrics.get("influence_union_width", 0) or 0),
                "lost_influence_mass": float(metrics.get("lost_influence_mass", 0.0) or 0.0),
                "max_absolute_quantization_error": float(
                    metrics.get("max_absolute_quantization_error", 0.0) or 0.0
                ),
                "l1_quantization_error": float(metrics.get("l1_quantization_error", 0.0) or 0.0),
                "protected_bytes_preserved": not bool(deleted_submeshes),
                "original_bounds_preserved": True,
                "lower_lods_preserved": not matching_cleanup_lods and (not bool(deleted_submeshes) or lod_count == 1),
                "synchronized_cleanup_lod_indices": matching_cleanup_lods,
                "unknown_sections_preserved": True,
                "deleted_submesh_indices": deleted_submeshes,
                "deleted_part_encoding": "source_record_tiny_draw" if deleted_submeshes else "",
                "unmodified_parts_preserved": True,
            }
        )

    logger.info(
        "Built PAC %s with the exact LOD0 topology serializer: %d bytes, %d submesh(es) rebuilt",
        getattr(edited_mesh, "path", ""),
        len(rebuilt),
        len(admitted_submeshes),
    )
    return rebuilt


def _original_split_bytes(original_data: bytes, section_0: Mapping[str, object], lod_index: int) -> int:
    """The vertex/index split of an untouched LOD, relative to its section start."""
    base = int(section_0["offset"])  # type: ignore[index]
    lod_count = original_data[base + 4]
    offset_table = base + 5
    split_table = offset_table + lod_count * 4
    section_offset = struct.unpack_from("<I", original_data, offset_table + lod_index * 4)[0]
    split_absolute = struct.unpack_from("<I", original_data, split_table + lod_index * 4)[0]
    return max(0, int(split_absolute) - int(section_offset))


def _verify_rebuilt_pac(
    rebuilt: bytes,
    *,
    original_data: bytes,
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    original_lod0_payload: bytes,
    lod0_section_index: int,
    payloads: Mapping[int, bytes],
    matching_cleanup_lods: Sequence[int] = (),
) -> None:
    """Reparse and compare before any caller sees the bytes."""
    reparsed = parse_pac(rebuilt, str(getattr(edited_mesh, "path", "") or ""))
    edited_submeshes = tuple(edited_mesh.submeshes)
    original_submeshes = tuple(original_mesh.submeshes)
    if len(reparsed.submeshes) != len(edited_submeshes):
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_CONTRACT_UNSUPPORTED,),
            f"Rebuilt PAC reparsed into {len(reparsed.submeshes)} submesh(es), expected {len(edited_submeshes)}.",
        )
    for index, (parsed, edited, original) in enumerate(zip(reparsed.submeshes, edited_submeshes, original_submeshes)):
        expected = edited if getattr(edited, "topology_provenance", None) is not None and edited.vertices else original
        if len(parsed.vertices) != len(expected.vertices) or len(parsed.faces) != len(expected.faces):
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,),
                f"Rebuilt PAC submesh {index} reparsed with "
                f"{len(parsed.vertices)}/{len(parsed.faces)} vertices/faces, expected "
                f"{len(expected.vertices)}/{len(expected.faces)}.",
            )
        if tuple(tuple(face) for face in parsed.faces) != tuple(tuple(int(value) for value in face[:3]) for face in expected.faces):
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,),
                f"Rebuilt PAC submesh {index} reparsed with different connectivity.",
            )

    rebuilt_sections = {section["index"]: section for section in _parse_par_sections(rebuilt)}
    lod0_section = rebuilt_sections[lod0_section_index]
    rebuilt_lod0_payload = rebuilt[lod0_section["offset"]:lod0_section["offset"] + lod0_section["size"]]
    for index, payload in payloads.items():
        if index == 0 or index == lod0_section_index:
            continue
        section = rebuilt_sections.get(index)
        if section is None:
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,), f"Rebuilt PAC dropped source section {index}."
            )
        rebuilt_payload = rebuilt[section["offset"] : section["offset"] + section["size"]]
        expected_payload = rebuilt_lod0_payload if lod0_section_index - index in matching_cleanup_lods else payload
        if hashlib.sha256(rebuilt_payload).hexdigest() != hashlib.sha256(expected_payload).hexdigest():
            raise PacTopologyRebuildBlocked(
                (TOPOLOGY_CONTRACT_UNSUPPORTED,),
                f"Rebuilt PAC section {index} does not match its proven source or synchronized cleanup output.",
            )
    if len(original_lod0_payload) == 0:
        raise PacTopologyRebuildBlocked(
            (TOPOLOGY_CONTRACT_UNSUPPORTED,), "The source PAC has no LOD0 geometry section to rebuild."
        )


__all__ = [
    "PROVEN_PAC_STRIDE",
    "PacTopologyRebuildBlocked",
    "TOPOLOGY_SERIALIZER_ID",
    "build_pac_topology_rebuild",
    "derived_skin_row",
    "protected_byte_mask",
    "topology_rebuild_blockers",
]
