"""Skin-weight provenance, validation, transfer, and PAC record encoding."""

from __future__ import annotations

import math
import struct
from typing import Sequence

from .mesh_parser import (
    PAC_SKIN_PALETTE_SLOTS,
    PAC_SKIN_MAX_BONE_INDEX,
    PAC_SKIN_SLOT_BITS,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_SLOTS_PER_GROUP,
    PAC_SKIN_WEIGHT_LAYOUT,
    PAC_SKIN_WEIGHT_OFFSET,
    ParsedMesh,
    SubMesh,
    _decode_pac_skin_influences,
)


SOURCE_VERTEX_MAP_TARGET_DONOR = "target_donor_record"
SOURCE_VERTEX_MAP_TOPOLOGY = "topology"


def source_vertex_map_is_target_donor_lineage(original: SubMesh, candidate: SubMesh) -> bool:
    values = tuple(candidate.source_vertex_map or ())
    if len(values) != len(candidate.vertices):
        return False
    try:
        mapped = tuple(int(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        return False
    if not mapped or any(value < 0 or value >= len(original.vertices) for value in mapped):
        return False

    authority = str(candidate.source_vertex_map_authority or "").strip().lower()
    if authority == SOURCE_VERTEX_MAP_TOPOLOGY:
        return False
    if (
        original.source_descriptor_offset >= 0
        and candidate.source_descriptor_offset >= 0
        and original.source_descriptor_offset != candidate.source_descriptor_offset
    ):
        return False
    if authority == SOURCE_VERTEX_MAP_TARGET_DONOR:
        return True
    return (
        len(candidate.source_vertex_offsets) == len(values)
        and candidate.source_vertex_stride > 0
        and original.source_vertex_stride > 0
        and candidate.source_vertex_stride == original.source_vertex_stride
    )


def finalize_merged_skin_provenance(merged: SubMesh, sources: Sequence[SubMesh], target: SubMesh) -> None:
    if sources and all(source_vertex_map_is_target_donor_lineage(target, source) for source in sources):
        merged.source_vertex_map = [int(value) for source in sources for value in source.source_vertex_map]
        merged.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
    else:
        merged.source_vertex_map = []
        merged.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
    if sources and all(
        len(source.bone_indices) == len(source.vertices) and len(source.bone_weights) == len(source.vertices)
        for source in sources
    ):
        merged.bone_indices = [row for source in sources for row in source.bone_indices]
        merged.bone_weights = [row for source in sources for row in source.bone_weights]
    merged.source_bone_palette = tuple(target.source_bone_palette or ())
    merged.source_skin_weight_layout = str(target.source_skin_weight_layout or "")


def has_skin_rows(submesh: SubMesh) -> bool:
    return any(bool(row) for row in tuple(submesh.bone_indices or ())) or any(
        bool(row) for row in tuple(submesh.bone_weights or ())
    )


def has_valid_target_skin_weights(submesh: SubMesh) -> bool:
    vertices = tuple(submesh.vertices or ())
    index_rows = tuple(submesh.bone_indices or ())
    weight_rows = tuple(submesh.bone_weights or ())
    if not vertices or len(index_rows) != len(vertices) or len(weight_rows) != len(vertices):
        return False
    for indices, weights in zip(index_rows, weight_rows):
        try:
            bones = tuple(int(value) for value in tuple(indices or ()))
            values = tuple(float(value) for value in tuple(weights or ()))
        except (TypeError, ValueError, OverflowError):
            return False
        # Bounded by what this writer can author, which is the six palette
        # lanes, not by what a record can carry. A row using the record's two
        # further influences is refused here so the donor's skin bytes survive
        # intact, rather than being rewritten from its six strongest and
        # silently losing the other two.
        if not 1 <= len(bones) == len(values) <= PAC_SKIN_PALETTE_SLOTS:
            return False
        if any(bone < 0 or bone > PAC_SKIN_MAX_BONE_INDEX for bone in bones):
            return False
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            return False
        if abs(sum(values) - 1.0) > (1.0 / 255.0 + 1.0e-6):
            return False
    return True


def ensure_final_target_skin_weights(
    merged: SubMesh,
    target: SubMesh,
    *,
    target_index: int,
    summary: list[str] | None,
) -> None:
    skin_layout = str(target.source_skin_weight_layout or "")
    target_has_rows = has_skin_rows(target)
    if not target_has_rows and not skin_layout:
        return
    label = str(target.name or target.material or target_index)
    if skin_layout != PAC_SKIN_WEIGHT_LAYOUT:
        raise ValueError(
            f"Cannot author skin weights for target {target_index} ({label}): "
            f"unsupported or unproven skin-weight layout {skin_layout or '<unknown>'}."
        )
    if not target_has_rows:
        raise ValueError(
            f"Cannot author skin weights for target {target_index} ({label}): "
            "the proven PAC skin layout has no decoded donor influence rows."
        )
    if source_vertex_map_is_target_donor_lineage(target, merged):
        donor_indices = [int(value) for value in merged.source_vertex_map]
        merged.bone_indices = [tuple(target.bone_indices[index]) for index in donor_indices]
        merged.bone_weights = [tuple(target.bone_weights[index]) for index in donor_indices]
        if not has_valid_target_skin_weights(merged):
            raise ValueError(
                f"Cannot preserve skin weights for target {target_index} ({label}): "
                "the exact target-donor map references an invalid donor influence row."
            )
        if summary is not None:
            summary.append(
                f"Skin weights target {target_index} ({label}): "
                f"preserved {len(donor_indices):,} exact donor rows."
            )
        return
    if has_valid_target_skin_weights(merged):
        if summary is not None:
            summary.append(f"Skin weights target {target_index} ({label}): preserved valid target-rig weights.")
        return
    if target.source_vertex_stride != 40:
        raise ValueError(
            f"Cannot author skin weights for target {target_index} ({label}): "
            f"PAC vertex stride {target.source_vertex_stride} is unsupported; expected proven 40-byte layout."
        )

    from .mesh_native_core import transfer_native_mesh_skin_weights_from_source

    transfer_metrics: dict[str, object] = {}
    transfer_result = transfer_native_mesh_skin_weights_from_source(
        ParsedMesh(submeshes=[merged], has_bones=has_skin_rows(merged)),
        ParsedMesh(submeshes=[target], has_bones=True),
        {},
        (0,),
        source_vertex_map_is_donor_lineage=False,
        transfer_report=transfer_metrics,
    )
    metric_rows = tuple(transfer_metrics.get("submeshes") or ())
    metric = metric_rows[0] if metric_rows and isinstance(metric_rows[0], dict) else {}
    distance_p95 = float(metric.get("distance_p95") or 0.0)
    distance_limit = float(metric.get("distance_limit") or 0.0)
    if transfer_result is None:
        if bool(transfer_metrics.get("distance_warning")):
            raise ValueError(
                f"Skin-weight transfer for target {target_index} ({label}) is too far from the source surface: "
                f"p95 {distance_p95:.6g} exceeds 5% bounds limit {distance_limit:.6g}."
            )
        reason = str(transfer_metrics.get("error") or "native mesh core returned no transfer result")
        raise RuntimeError(f"Skin-weight transfer failed for target {target_index} ({label}): {reason}.")
    if not has_valid_target_skin_weights(merged):
        raise ValueError(f"Skin-weight transfer for target {target_index} ({label}) produced invalid target-rig weights.")
    if summary is not None:
        summary.append(
            f"Skin weights target {target_index} ({label}): transferred {len(merged.vertices):,} vertices; "
            f"surface-distance p95 {distance_p95:.6g} (limit {distance_limit:.6g})."
        )


def pack_pac_skin_weights(
    record: bytearray,
    bone_indices: Sequence[object],
    bone_weights: Sequence[object],
    *,
    context: str,
) -> None:
    """Encode a skin row into a PAC vertex record's palette lanes, in place.

    Writes two u32 of three 10-bit palette slots each, then six u8 weights in
    descending order summing to 255. An unused influence is a zero weight, not a
    reserved slot value, because slot 0 is a real palette entry.

    A record can carry two influences beyond the palette, indexed at bytes 12-15
    with weights at bytes 34-35. This function does not author them: those lanes
    are protected by the exact topology serializer's ownership mask, and writing
    them would break its contract. A row with more than six influences is
    therefore reduced to its six strongest here, which is lossy and deliberate.
    Callers that must not lose an influence check the width before calling.

    Slot values are written verbatim. They are per-mesh palette tokens, not
    skeleton bone indices, so writing back what the reader decoded round-trips
    correctly; remapping them would require the unsolved palette mapping.
    """

    if len(record) != 40:
        raise ValueError(f"Cannot encode {context}: expected proven 40-byte PAC vertex record, got {len(record)} bytes.")
    merged: dict[int, float] = {}
    for raw_bone, raw_weight in zip(tuple(bone_indices or ()), tuple(bone_weights or ())):
        try:
            bone, weight = int(raw_bone), float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        if bone >= 0 and math.isfinite(weight) and weight > 0.0:
            merged[bone] = merged.get(bone, 0.0) + weight
    strongest = sorted(merged.items(), key=lambda item: (-item[1], item[0]))[:PAC_SKIN_PALETTE_SLOTS]
    if not strongest:
        raise ValueError(f"Cannot encode {context}: skin-weight row is empty or invalid.")
    out_of_range = [bone for bone, _weight in strongest if bone > PAC_SKIN_MAX_BONE_INDEX]
    if out_of_range:
        raise ValueError(
            f"Cannot encode {context}: bone index(es) {out_of_range} exceed the PAC limit of "
            f"{PAC_SKIN_MAX_BONE_INDEX}, the widest value a {PAC_SKIN_SLOT_BITS}-bit slot holds."
        )
    total = sum(weight for _bone, weight in strongest)
    available = 255 - len(strongest)
    scaled = [weight / total * available for _bone, weight in strongest]
    packed_weights = [1 + int(math.floor(value)) for value in scaled]
    remainder = 255 - sum(packed_weights)
    order = sorted(range(len(strongest)), key=lambda index: (scaled[index] - math.floor(scaled[index]), -index), reverse=True)
    for index in order[:remainder]:
        packed_weights[index] += 1
    slots = [bone for bone, _weight in strongest]
    slots.extend([0] * (PAC_SKIN_PALETTE_SLOTS - len(slots)))
    packed_weights.extend([0] * (PAC_SKIN_PALETTE_SLOTS - len(packed_weights)))

    for group, group_offset in enumerate(PAC_SKIN_SLOT_GROUPS):
        # The top two bits of each group carry no meaning we have proven, so a patch
        # leaves whatever the donor record held rather than clearing it.
        packed_group = struct.unpack_from("<I", record, group_offset)[0] & ~0x3FFFFFFF
        for position in range(PAC_SKIN_SLOTS_PER_GROUP):
            slot = slots[group * PAC_SKIN_SLOTS_PER_GROUP + position]
            packed_group |= slot << (PAC_SKIN_SLOT_BITS * position)
        struct.pack_into("<I", record, group_offset, packed_group)
    record[PAC_SKIN_WEIGHT_OFFSET:PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_PALETTE_SLOTS] = bytes(packed_weights)


def pac_skin_weights_changed(original: SubMesh, updated: SubMesh) -> bool:
    return (
        tuple(original.bone_indices or ()) != tuple(updated.bone_indices or ())
        or tuple(original.bone_weights or ()) != tuple(updated.bone_weights or ())
    )


def pac_skin_export_enabled(original: SubMesh, updated: SubMesh, submesh_index: int) -> bool:
    """True when this submesh carries skin rows that the writer is proven to encode."""

    bone_indices = tuple(updated.bone_indices or ())
    bone_weights = tuple(updated.bone_weights or ())
    if not bone_indices and not bone_weights:
        return False
    if len(bone_indices) != len(updated.vertices) or len(bone_weights) != len(updated.vertices):
        raise ValueError(f"PAC submesh {submesh_index} has incomplete skin-weight rows.")
    if original.source_skin_weight_layout != PAC_SKIN_WEIGHT_LAYOUT:
        raise ValueError(f"PAC submesh {submesh_index} skin-weight layout is unsupported or unproven.")
    if original.source_vertex_stride != 40:
        raise ValueError(
            f"PAC submesh {submesh_index} skin weights require the proven 40-byte vertex layout; "
            f"found stride {original.source_vertex_stride}."
        )
    return True


def patch_pac_vertex_skin(
    record: bytearray,
    submesh: SubMesh,
    vertex_index: int,
    submesh_index: int,
) -> None:
    if not 0 <= vertex_index < len(submesh.vertices):
        raise ValueError(f"PAC submesh {submesh_index} LOD skin-weight lineage is out of range.")
    bones = tuple(submesh.bone_indices[vertex_index] or ())
    weights = tuple(submesh.bone_weights[vertex_index] or ())
    # Leave a record that already carries these influences exactly as it is. Encoding is not a
    # bit-exact inverse of decoding -- u8 weights requantize by a count or two, and a slot left
    # behind a zero weight would be cleared -- and the replacement path depends on an untouched
    # row surviving byte for byte.
    if (bones, weights) == _decode_pac_skin_influences(bytes(record), 0):
        return
    pack_pac_skin_weights(
        record,
        bones,
        weights,
        context=f"PAC submesh {submesh_index} vertex {vertex_index}",
    )


__all__ = [
    "PAC_SKIN_WEIGHT_LAYOUT",
    "ensure_final_target_skin_weights",
    "finalize_merged_skin_provenance",
    "pac_skin_export_enabled",
    "pac_skin_weights_changed",
    "pack_pac_skin_weights",
    "patch_pac_vertex_skin",
    "source_vertex_map_is_target_donor_lineage",
]
