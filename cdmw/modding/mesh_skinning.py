"""Skin-weight provenance, validation, transfer, and PAC record encoding."""

from __future__ import annotations

import math
from typing import Sequence

from .mesh_parser import ParsedMesh, SubMesh


SOURCE_VERTEX_MAP_TARGET_DONOR = "target_donor_record"
SOURCE_VERTEX_MAP_TOPOLOGY = "topology"
PAC_SKIN_WEIGHT_LAYOUT = "pac_palette_u8x4"


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


def target_skin_palette(target: SubMesh) -> tuple[int, ...]:
    try:
        palette = tuple(int(value) for value in tuple(target.source_bone_palette or ()))
    except (TypeError, ValueError, OverflowError):
        return ()
    if len(palette) > 255 or len(set(palette)) != len(palette) or any(value < 0 or value > 255 for value in palette):
        return ()
    return palette


def has_skin_rows(submesh: SubMesh) -> bool:
    return any(bool(row) for row in tuple(submesh.bone_indices or ())) or any(
        bool(row) for row in tuple(submesh.bone_weights or ())
    )


def has_valid_target_skin_weights(submesh: SubMesh, palette: Sequence[int]) -> bool:
    vertices = tuple(submesh.vertices or ())
    index_rows = tuple(submesh.bone_indices or ())
    weight_rows = tuple(submesh.bone_weights or ())
    allowed = {int(value) for value in palette}
    if not vertices or not allowed or len(index_rows) != len(vertices) or len(weight_rows) != len(vertices):
        return False
    for indices, weights in zip(index_rows, weight_rows):
        try:
            bones = tuple(int(value) for value in tuple(indices or ()))
            values = tuple(float(value) for value in tuple(weights or ()))
        except (TypeError, ValueError, OverflowError):
            return False
        if not 1 <= len(bones) == len(values) <= 4 or any(bone not in allowed for bone in bones):
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
    palette = target_skin_palette(target)
    if not palette:
        raise ValueError(
            f"Cannot author skin weights for target {target_index} ({label}): PAC bone-palette provenance is unavailable."
        )
    if not target_has_rows:
        raise ValueError(
            f"Cannot author skin weights for target {target_index} ({label}): "
            "the proven PAC skin layout has no decoded donor influence rows."
        )
    if has_valid_target_skin_weights(merged, palette):
        merged.source_bone_palette = palette
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
    if not has_valid_target_skin_weights(merged, palette):
        raise ValueError(f"Skin-weight transfer for target {target_index} ({label}) produced invalid target-rig weights.")
    merged.source_bone_palette = palette
    if summary is not None:
        summary.append(
            f"Skin weights target {target_index} ({label}): transferred {len(merged.vertices):,} vertices; "
            f"surface-distance p95 {distance_p95:.6g} (limit {distance_limit:.6g})."
        )


def pack_pac_skin_weights(
    record: bytearray,
    bone_indices: Sequence[object],
    bone_weights: Sequence[object],
    palette: Sequence[int],
    *,
    context: str,
) -> None:
    if len(record) != 40:
        raise ValueError(f"Cannot encode {context}: expected proven 40-byte PAC vertex record, got {len(record)} bytes.")
    palette_values = tuple(int(bone) for bone in palette)
    if (
        not palette_values
        or len(palette_values) > 255
        or len(set(palette_values)) != len(palette_values)
        or any(bone < 0 or bone > 255 for bone in palette_values)
    ):
        raise ValueError(f"Cannot encode {context}: target PAC bone palette is invalid or exceeds slot 254.")
    palette_slots = {bone: slot for slot, bone in enumerate(palette_values)}
    merged: dict[int, float] = {}
    for raw_bone, raw_weight in zip(tuple(bone_indices or ()), tuple(bone_weights or ())):
        try:
            bone, weight = int(raw_bone), float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        if bone >= 0 and math.isfinite(weight) and weight > 0.0:
            merged[bone] = merged.get(bone, 0.0) + weight
    strongest = sorted(merged.items(), key=lambda item: (-item[1], item[0]))[:4]
    if not strongest:
        raise ValueError(f"Cannot encode {context}: skin-weight row is empty or invalid.")
    missing = [bone for bone, _weight in strongest if bone not in palette_slots]
    if missing:
        raise ValueError(f"Cannot encode {context}: target PAC bone palette does not contain global bone index(es) {missing}.")
    total = sum(weight for _bone, weight in strongest)
    available = 255 - len(strongest)
    scaled = [weight / total * available for _bone, weight in strongest]
    packed_weights = [1 + int(math.floor(value)) for value in scaled]
    remainder = 255 - sum(packed_weights)
    order = sorted(range(len(strongest)), key=lambda index: (scaled[index] - math.floor(scaled[index]), -index), reverse=True)
    for index in order[:remainder]:
        packed_weights[index] += 1
    slots = [palette_slots[bone] for bone, _weight in strongest]
    slots.extend([0xFF] * (4 - len(slots)))
    packed_weights.extend([0] * (4 - len(packed_weights)))
    record[28:32], record[32:36] = bytes(slots), bytes(packed_weights)


def pac_skin_weights_changed(original: SubMesh, updated: SubMesh) -> bool:
    return (
        tuple(original.bone_indices or ()) != tuple(updated.bone_indices or ())
        or tuple(original.bone_weights or ()) != tuple(updated.bone_weights or ())
    )


def pac_skin_export_palette(
    original: SubMesh,
    updated: SubMesh,
    descriptor_palette: Sequence[int],
    submesh_index: int,
) -> tuple[int, ...] | None:
    bone_indices = tuple(updated.bone_indices or ())
    bone_weights = tuple(updated.bone_weights or ())
    if not bone_indices and not bone_weights:
        return None
    if len(bone_indices) != len(updated.vertices) or len(bone_weights) != len(updated.vertices):
        raise ValueError(f"PAC submesh {submesh_index} has incomplete skin-weight rows.")
    if original.source_skin_weight_layout != PAC_SKIN_WEIGHT_LAYOUT:
        raise ValueError(f"PAC submesh {submesh_index} skin-weight layout is unsupported or unproven.")
    if original.source_vertex_stride != 40:
        raise ValueError(
            f"PAC submesh {submesh_index} skin weights require the proven 40-byte vertex layout; "
            f"found stride {original.source_vertex_stride}."
        )
    parsed_palette = tuple(int(value) for value in tuple(original.source_bone_palette or ()))
    palette = tuple(int(value) for value in tuple(descriptor_palette or ()))
    if not palette or (parsed_palette and parsed_palette != palette):
        raise ValueError(f"PAC submesh {submesh_index} bone-palette provenance is missing or inconsistent.")
    return palette


def patch_pac_vertex_skin(
    record: bytearray,
    submesh: SubMesh,
    vertex_index: int,
    palette: Sequence[int],
    submesh_index: int,
) -> None:
    if not 0 <= vertex_index < len(submesh.vertices):
        raise ValueError(f"PAC submesh {submesh_index} LOD skin-weight lineage is out of range.")
    pack_pac_skin_weights(
        record,
        submesh.bone_indices[vertex_index],
        submesh.bone_weights[vertex_index],
        palette,
        context=f"PAC submesh {submesh_index} vertex {vertex_index}",
    )


__all__ = [
    "PAC_SKIN_WEIGHT_LAYOUT",
    "ensure_final_target_skin_weights",
    "finalize_merged_skin_provenance",
    "pac_skin_export_palette",
    "pac_skin_weights_changed",
    "pack_pac_skin_weights",
    "patch_pac_vertex_skin",
    "source_vertex_map_is_target_donor_lineage",
]
