"""PAC rebuild helpers for mesh round-trip imports."""

from __future__ import annotations

import copy
import math
import struct
from typing import Sequence

from .logging import get_logger
from .mesh_builder_common import _align_submesh_order_like_original, _compute_bbox
from .mesh_parser import (
    ParsedMesh,
    SubMesh,
    _compute_smooth_normals,
    _find_pac_descriptors,
    _parse_par_sections,
    parse_pac,
)
from .mesh_skinning import pac_skin_export_palette, pac_skin_weights_changed, patch_pac_vertex_skin, source_vertex_map_is_target_donor_lineage

logger = get_logger("core.mesh_importer")

def _quantize_pac_u16(value: float, bbox_min: float, bbox_extent: float) -> int:
    """Float -> PAC uint16 quantized using bbox min/extent encoding."""
    if abs(bbox_extent) < 1e-10:
        return 0
    t = (value - bbox_min) / bbox_extent
    t = max(0.0, min(1.0, t))
    return min(32767, max(0, round(t * 32767.0)))

def _patch_pac_descriptor_bounds(
    data: bytearray,
    descriptor_offset: int,
    bbox_min: tuple[float, float, float],
    bbox_extent: tuple[float, float, float],
) -> None:
    """Update a PAC descriptor's bbox min/extent floats in section 0."""
    if descriptor_offset < 0 or descriptor_offset + 35 > len(data):
        return

    floats_off = descriptor_offset + 3
    struct.pack_into("<f", data, floats_off + 2 * 4, bbox_min[0])
    struct.pack_into("<f", data, floats_off + 3 * 4, bbox_min[1])
    struct.pack_into("<f", data, floats_off + 4 * 4, bbox_min[2])
    struct.pack_into("<f", data, floats_off + 5 * 4, bbox_extent[0])
    struct.pack_into("<f", data, floats_off + 6 * 4, bbox_extent[1])
    struct.pack_into("<f", data, floats_off + 7 * 4, bbox_extent[2])

def _pac_submesh_match_score(imported_sm: SubMesh, original_sm: SubMesh) -> float:
    """Score how likely an imported PAC object maps back to an original slot."""
    imp_center = tuple((mn + mx) * 0.5 for mn, mx in zip(*_compute_bbox(imported_sm.vertices)))
    orig_center = tuple((mn + mx) * 0.5 for mn, mx in zip(*_compute_bbox(original_sm.vertices)))
    center_dist = math.dist(imp_center, orig_center)

    vert_ratio = abs(math.log((len(imported_sm.vertices) + 1) / (len(original_sm.vertices) + 1)))
    face_ratio = abs(math.log((len(imported_sm.faces) + 1) / (len(original_sm.faces) + 1)))
    return center_dist + vert_ratio * 0.75 + face_ratio * 0.75

def _merge_partial_pac_import(
    original_mesh: ParsedMesh,
    imported_mesh: ParsedMesh,
) -> ParsedMesh:
    """Merge a partial PAC OBJ import onto the original submesh set by name.

    Blender exports sometimes omit hidden or unselected PAC objects. In that
    case named OBJ exports are treated as the user's authoritative visible
    part set: original PAC draw slots that are not present in the OBJ become
    empty placeholders so they do not silently reappear in game.
    """
    if len(imported_mesh.submeshes) >= len(original_mesh.submeshes):
        return imported_mesh

    original_names = [sm.name for sm in original_mesh.submeshes]
    imported_by_name: dict[str, SubMesh] = {}
    unknown_named: list[SubMesh] = []
    unnamed: list[SubMesh] = []

    for sm in imported_mesh.submeshes:
        if sm.name:
            if sm.name in original_names:
                if sm.name in imported_by_name:
                    raise ValueError(
                        f"PAC import contains duplicate submesh name '{sm.name}'. "
                        "Keep unique object names when exporting OBJ from Blender."
                    )
                imported_by_name[sm.name] = copy.deepcopy(sm)
            else:
                unknown_named.append(copy.deepcopy(sm))
        else:
            unnamed.append(copy.deepcopy(sm))

    heuristic_by_name: dict[str, SubMesh] = {}
    unmatched_originals = [
        copy.deepcopy(sm)
        for sm in original_mesh.submeshes
        if sm.name not in imported_by_name
    ]
    for imported_unknown in sorted(unknown_named, key=lambda sm: len(sm.vertices), reverse=True):
        if not unmatched_originals:
            raise ValueError(
                "PAC import contains more renamed submeshes than the original mesh can match."
            )
        best_original = min(
            unmatched_originals,
            key=lambda original_sm: _pac_submesh_match_score(imported_unknown, original_sm),
        )
        imported_unknown.name = best_original.name
        if not imported_unknown.material:
            imported_unknown.material = best_original.material
        if not imported_unknown.texture:
            imported_unknown.texture = best_original.texture
        heuristic_by_name[best_original.name] = imported_unknown
        unmatched_originals = [sm for sm in unmatched_originals if sm.name != best_original.name]

    obj_is_authoritative = bool(imported_by_name)
    dropped_names: list[str] = []
    merged_submeshes: list[SubMesh] = []
    unnamed_iter = iter(unnamed)
    used_named = 0
    for original_sm in original_mesh.submeshes:
        replacement = imported_by_name.get(original_sm.name)
        if replacement is None:
            replacement = heuristic_by_name.get(original_sm.name)
        if replacement is not None:
            if not replacement.material:
                replacement.material = original_sm.material
            if not replacement.texture:
                replacement.texture = original_sm.texture
            merged_submeshes.append(replacement)
            used_named += 1
            continue

        if obj_is_authoritative:
            placeholder = copy.deepcopy(original_sm)
            placeholder.vertices = []
            placeholder.uvs = []
            placeholder.normals = []
            placeholder.faces = []
            placeholder.bone_indices = []
            placeholder.bone_weights = []
            placeholder.source_vertex_offsets = []
            placeholder.source_vertex_map = []
            placeholder.source_index_count = 0
            placeholder.vertex_count = 0
            placeholder.face_count = 0
            merged_submeshes.append(placeholder)
            dropped_names.append(original_sm.name)
            continue

        try:
            fallback = next(unnamed_iter)
        except StopIteration:
            merged_submeshes.append(copy.deepcopy(original_sm))
        else:
            if not fallback.material:
                fallback.material = original_sm.material
            if not fallback.texture:
                fallback.texture = original_sm.texture
            merged_submeshes.append(fallback)

    try:
        extra_unnamed = next(unnamed_iter)
    except StopIteration:
        extra_unnamed = None
    if extra_unnamed is not None:
        raise ValueError(
            "PAC import contains extra unnamed submeshes that could not be matched to the original mesh."
        )

    if (
        not obj_is_authoritative
        and used_named == 0
        and imported_mesh.submeshes
        and len(imported_mesh.submeshes) != len(original_mesh.submeshes)
    ):
        raise ValueError(
            "PAC import only contained a partial mesh without recognizable original submesh names."
        )

    if dropped_names:
        logger.info(
            "PAC OBJ import is authoritative; emitting %d empty placeholder submesh(es): %s",
            len(dropped_names),
            ", ".join(dropped_names),
        )

    merged = copy.deepcopy(imported_mesh)
    merged.submeshes = merged_submeshes
    merged.total_vertices = sum(len(sm.vertices) for sm in merged_submeshes)
    merged.total_faces = sum(len(sm.faces) for sm in merged_submeshes)
    merged.has_uvs = any(sm.uvs for sm in merged_submeshes)
    merged.has_bones = any(sm.bone_indices for sm in merged_submeshes)
    return merged

def _pack_pac_normal(normal: tuple[float, float, float], existing_packed: int = 0) -> int:
    """Pack a float normal back into the PAC 10:10:10 layout."""

    def _enc(value: float) -> int:
        value = max(-1.0, min(1.0, value))
        return max(0, min(1023, round((value + 1.0) * 511.5)))

    nx, ny, nz = normal
    packed = _enc(nz) | (_enc(nx) << 10) | (_enc(ny) << 20)
    return (existing_packed & 0xC0000000) | packed

def _choose_pac_donor_indices(orig_sm: SubMesh, new_sm: SubMesh) -> list[int]:
    """Choose the closest original PAC vertex record to clone for each new vertex."""
    if not orig_sm.vertices:
        return [0] * len(new_sm.vertices)

    exact_map: dict[tuple[int, int, int], list[int]] = {}
    for orig_idx, pos in enumerate(orig_sm.vertices):
        key = (round(pos[0] * 100000), round(pos[1] * 100000), round(pos[2] * 100000))
        exact_map.setdefault(key, []).append(orig_idx)

    sidecar_source_map = (
        list(getattr(new_sm, "source_vertex_map", ()) or ())
        if source_vertex_map_is_target_donor_lineage(orig_sm, new_sm)
        else []
    )
    donor_indices: list[int] = []
    for vertex_index, new_pos in enumerate(new_sm.vertices):
        if vertex_index < len(sidecar_source_map):
            mapped_index = int(sidecar_source_map[vertex_index])
            if 0 <= mapped_index < len(orig_sm.vertices):
                donor_indices.append(mapped_index)
                continue

        key = (round(new_pos[0] * 100000), round(new_pos[1] * 100000), round(new_pos[2] * 100000))
        exact_hits = exact_map.get(key)
        if exact_hits:
            donor_indices.append(exact_hits[0])
            continue

        best_idx = 0
        best_dist = float("inf")
        for orig_idx, orig_pos in enumerate(orig_sm.vertices):
            dx = new_pos[0] - orig_pos[0]
            dy = new_pos[1] - orig_pos[1]
            dz = new_pos[2] - orig_pos[2]
            dist_sq = dx * dx + dy * dy + dz * dz
            if dist_sq < best_dist:
                best_dist = dist_sq
                best_idx = orig_idx
        donor_indices.append(best_idx)

    return donor_indices


def _pac_needs_full_rebuild(original_mesh: ParsedMesh, working_mesh: ParsedMesh) -> bool:
    """Return True when the PAC import changed topology or needs a fresh serializer."""
    if len(original_mesh.submeshes) != len(working_mesh.submeshes):
        return True

    for orig_sm, new_sm in zip(original_mesh.submeshes, working_mesh.submeshes):
        if len(orig_sm.vertices) != len(new_sm.vertices):
            return True
        if len(orig_sm.faces) != len(new_sm.faces) or pac_skin_weights_changed(orig_sm, new_sm):
            return True
        if orig_sm.source_vertex_stride < 12:
            return True
        if len(orig_sm.source_vertex_offsets) != len(orig_sm.vertices):
            return True
        if orig_sm.source_descriptor_offset < 0:
            return True
    return False


def _build_pac_in_place(
    original_mesh: ParsedMesh,
    working_mesh: ParsedMesh,
    original_data: bytes,
) -> bytes:
    """Patch a PAC binary in place while preserving its existing layout."""
    result = bytearray(original_data)
    vertex_updates: dict[int, bytes] = {}
    index_updates: dict[int, bytes] = {}

    for sm_idx, (orig_sm, new_sm) in enumerate(zip(original_mesh.submeshes, working_mesh.submeshes)):
        if len(orig_sm.vertices) != len(new_sm.vertices):
            raise ValueError(
                f"PAC submesh {sm_idx} changed vertex count "
                f"({len(orig_sm.vertices)} -> {len(new_sm.vertices)}). "
                "Keep the same topology when importing OBJ for PAC meshes."
            )
        if len(orig_sm.faces) != len(new_sm.faces):
            raise ValueError(
                f"PAC submesh {sm_idx} changed face count "
                f"({len(orig_sm.faces)} -> {len(new_sm.faces)}). "
                "Keep the same topology when importing OBJ for PAC meshes."
            )
        if orig_sm.source_vertex_stride < 12:
            raise ValueError(
                f"PAC submesh {sm_idx} is missing source vertex metadata and cannot be rebuilt safely."
            )

        bmin, bmax = _compute_bbox(new_sm.vertices)
        extent = tuple(bmax[i] - bmin[i] for i in range(3))
        _patch_pac_descriptor_bounds(result, orig_sm.source_descriptor_offset, bmin, extent)

        new_uvs = new_sm.uvs if len(new_sm.uvs) == len(new_sm.vertices) else []
        new_normals = (
            new_sm.normals
            if len(new_sm.normals) == len(new_sm.vertices)
            else _compute_smooth_normals(new_sm.vertices, new_sm.faces)
        )
        clean_shading_records = bool(
            getattr(new_sm, "clean_donor_shading_records", False)
            or getattr(working_mesh, "clean_donor_shading_records", False)
        )

        for vi, rec_off in enumerate(orig_sm.source_vertex_offsets):
            if rec_off < 0 or rec_off + orig_sm.source_vertex_stride > len(result):
                raise ValueError(
                    f"PAC vertex record {vi} for submesh {sm_idx} points outside the file."
                )

            rec = bytearray(result[rec_off:rec_off + orig_sm.source_vertex_stride])
            if clean_shading_records:
                if len(rec) >= 8:
                    struct.pack_into("<H", rec, 6, 0)
                if len(rec) >= 28:
                    rec[20:28] = b"\x00" * 8
            vx, vy, vz = new_sm.vertices[vi]
            struct.pack_into(
                "<HHH",
                rec,
                0,
                _quantize_pac_u16(vx, bmin[0], extent[0]),
                _quantize_pac_u16(vy, bmin[1], extent[1]),
                _quantize_pac_u16(vz, bmin[2], extent[2]),
            )

            if new_uvs:
                try:
                    struct.pack_into("<e", rec, 8, new_uvs[vi][0])
                    struct.pack_into("<e", rec, 10, new_uvs[vi][1])
                except (OverflowError, ValueError):
                    struct.pack_into("<e", rec, 8, 0.0)
                    struct.pack_into("<e", rec, 10, 0.0)

            if len(rec) >= 20:
                existing_normal = struct.unpack_from("<I", rec, 16)[0]
                struct.pack_into(
                    "<I",
                    rec,
                    16,
                    _pack_pac_normal(
                        new_normals[vi],
                        0 if clean_shading_records else existing_normal,
                    ),
                )

            payload = bytes(rec)
            prev = vertex_updates.get(rec_off)
            if prev is not None and prev != payload:
                raise ValueError(
                    "PAC import edited a shared vertex buffer inconsistently across submeshes. "
                    "Apply the same change to every linked PAC submesh before reimport."
                )
            vertex_updates[rec_off] = payload

        if orig_sm.source_index_offset >= 0:
            for fi, (a, b, c) in enumerate(new_sm.faces):
                if a >= len(new_sm.vertices) or b >= len(new_sm.vertices) or c >= len(new_sm.vertices):
                    raise ValueError(f"PAC face {fi} in submesh {sm_idx} references an out-of-range vertex.")
                face_off = orig_sm.source_index_offset + fi * 6
                if face_off + 6 > len(result):
                    raise ValueError(
                        f"PAC face record {fi} for submesh {sm_idx} points outside the file."
                    )
                payload = struct.pack("<HHH", a, b, c)
                prev = index_updates.get(face_off)
                if prev is not None and prev != payload:
                    raise ValueError(
                        "PAC import edited a shared index buffer inconsistently across submeshes."
                    )
                index_updates[face_off] = payload

    for rec_off, payload in vertex_updates.items():
        result[rec_off:rec_off + len(payload)] = payload
    for face_off, payload in index_updates.items():
        result[face_off:face_off + len(payload)] = payload

    logger.info(
        "Built PAC %s with in-place patching: %d submeshes, %d verts, %d faces",
        working_mesh.path,
        len(working_mesh.submeshes),
        sum(len(sm.vertices) for sm in working_mesh.submeshes),
        sum(len(sm.faces) for sm in working_mesh.submeshes),
    )
    return bytes(result)


def _pac_descriptor_record_length(desc: object) -> int:
    stored_lod_count = max(1, int(getattr(desc, "stored_lod_count", 0) or 0))
    if stored_lod_count >= 4:
        return 48 + stored_lod_count * 4
    if stored_lod_count == 3:
        return 46 + stored_lod_count * 4
    return 44 + stored_lod_count * 4


def _length_prefixed_ascii(value: object, fallback: str) -> bytes:
    text = str(value or "").strip() or fallback
    encoded = text.encode("ascii", "replace")[:120]
    if not encoded:
        encoded = fallback.encode("ascii", "replace")[:120] or b"clone"
    return bytes([len(encoded)]) + encoded


def _append_pac_cloned_descriptors(
    sec0_data: bytearray,
    *,
    sec0_offset: int,
    descriptors: list[object],
    clone_descriptor_sources: Sequence[int],
    clone_descriptor_names: Sequence[str] = (),
) -> list[object]:
    if not clone_descriptor_sources:
        return list(descriptors)
    planned = list(descriptors)
    for clone_ordinal, raw_source_index in enumerate(clone_descriptor_sources, start=1):
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            raise ValueError(f"PAC cloned draw section {clone_ordinal} has an invalid descriptor source.")
        if source_index < 0 or source_index >= len(descriptors):
            raise ValueError(f"PAC cloned draw section {clone_ordinal} references missing descriptor {source_index}.")
        source_desc = descriptors[source_index]
        rel_desc_off = int(getattr(source_desc, "descriptor_offset", -1)) - int(sec0_offset)
        desc_len = _pac_descriptor_record_length(source_desc)
        if rel_desc_off < 0 or rel_desc_off + desc_len > len(sec0_data):
            raise ValueError(f"PAC descriptor {source_index} cannot be cloned from section 0.")
        desc_bytes = bytes(sec0_data[rel_desc_off:rel_desc_off + desc_len])
        override_name = ""
        if clone_ordinal - 1 < len(clone_descriptor_names):
            override_name = str(clone_descriptor_names[clone_ordinal - 1] or "").strip()
        source_name = str(getattr(source_desc, "name", "") or f"clone_{source_index}").strip()
        source_material = str(getattr(source_desc, "material", "") or source_name).strip()
        if override_name:
            name = override_name
            material = override_name
        else:
            suffix = f"_clone{clone_ordinal}"
            name = f"{source_name}{suffix}"
            material = source_material
        prefix = _length_prefixed_ascii(name, f"clone_{clone_ordinal}")
        prefix += _length_prefixed_ascii(material, f"material_{source_index}")
        clone_desc_rel_off = len(sec0_data) + len(prefix)
        sec0_data.extend(prefix)
        sec0_data.extend(desc_bytes)
        cloned_desc = copy.copy(source_desc)
        cloned_desc.name = name
        cloned_desc.material = material
        cloned_desc.descriptor_offset = sec0_offset + clone_desc_rel_off
        planned.append(cloned_desc)
    return planned


def _build_pac_output_descriptors(
    sec0_data: bytearray,
    *,
    sec0_offset: int,
    descriptors: list[object],
    descriptor_source_indices: Sequence[int],
    descriptor_names: Sequence[str] = (),
) -> list[object]:
    planned: list[object] = []
    stored_lod_count = int(sec0_data[4]) if len(sec0_data) >= 5 else 0
    descriptor_table_start = 5 + max(0, stored_lod_count) * 8
    descriptor_table_start = max(5, min(descriptor_table_start, len(sec0_data)))
    rebuilt_sec0 = bytearray(sec0_data[:descriptor_table_start])
    for output_index, raw_source_index in enumerate(tuple(descriptor_source_indices or ())):
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            raise ValueError(f"PAC output draw section {output_index} has an invalid descriptor source.")
        if source_index < 0 or source_index >= len(descriptors):
            raise ValueError(f"PAC output draw section {output_index} references missing descriptor {source_index}.")
        source_desc = descriptors[source_index]
        rel_desc_off = int(getattr(source_desc, "descriptor_offset", -1)) - int(sec0_offset)
        desc_len = _pac_descriptor_record_length(source_desc)
        if rel_desc_off < 0 or rel_desc_off + desc_len > len(sec0_data):
            raise ValueError(f"PAC descriptor {source_index} cannot be copied from section 0.")
        raw_name = ""
        if output_index < len(descriptor_names):
            raw_name = str(descriptor_names[output_index] or "").strip()
        source_name = str(getattr(source_desc, "name", "") or f"section_{output_index}").strip()
        source_material = str(getattr(source_desc, "material", "") or source_name).strip()
        name = raw_name or source_name
        material = raw_name or source_material
        prefix = _length_prefixed_ascii(name, f"section_{output_index}")
        prefix += _length_prefixed_ascii(material, f"material_{output_index}")
        desc_rel_off = len(rebuilt_sec0) + len(prefix)
        rebuilt_sec0.extend(prefix)
        rebuilt_sec0.extend(sec0_data[rel_desc_off:rel_desc_off + desc_len])
        cloned_desc = copy.copy(source_desc)
        cloned_desc.name = name
        cloned_desc.material = material
        cloned_desc.descriptor_offset = sec0_offset + desc_rel_off
        planned.append(cloned_desc)
    sec0_data[:] = rebuilt_sec0
    return planned


def _pac_lod_submesh_variant(submesh: SubMesh, target_face_count: int) -> SubMesh:
    faces = list(getattr(submesh, "faces", ()) or [])
    if target_face_count <= 0 or not faces or target_face_count >= len(faces):
        variant = copy.copy(submesh)
        variant.vertices = list(getattr(submesh, "vertices", ()) or [])
        variant.uvs = list(getattr(submesh, "uvs", ()) or [])
        variant.normals = list(getattr(submesh, "normals", ()) or [])
        variant.faces = list(faces)
        variant.source_vertex_map = list(range(len(variant.vertices)))
        variant.vertex_count = len(variant.vertices)
        variant.face_count = len(variant.faces)
        return variant

    step = max(1, math.ceil(len(faces) / float(max(1, target_face_count))))
    sampled_faces = faces[::step][:target_face_count]
    source_to_lod: dict[int, int] = {}
    lod_vertices: list[tuple[float, float, float]] = []
    lod_faces: list[tuple[int, int, int]] = []
    source_order: list[int] = []
    for face in sampled_faces:
        remapped: list[int] = []
        for raw_index in face[:3]:
            source_index = int(raw_index)
            if source_index < 0 or source_index >= len(submesh.vertices):
                remapped = []
                break
            lod_index = source_to_lod.get(source_index)
            if lod_index is None:
                lod_index = len(lod_vertices)
                source_to_lod[source_index] = lod_index
                source_order.append(source_index)
                lod_vertices.append(submesh.vertices[source_index])
            remapped.append(lod_index)
        if len(remapped) == 3 and len(set(remapped)) == 3:
            lod_faces.append((remapped[0], remapped[1], remapped[2]))
    if not lod_vertices or not lod_faces:
        return _pac_lod_submesh_variant(submesh, len(faces))

    variant = copy.copy(submesh)
    variant.vertices = lod_vertices
    variant.faces = lod_faces
    variant.uvs = (
        [submesh.uvs[source_index] for source_index in source_order]
        if len(getattr(submesh, "uvs", ()) or ()) == len(submesh.vertices)
        else []
    )
    variant.normals = (
        [submesh.normals[source_index] for source_index in source_order]
        if len(getattr(submesh, "normals", ()) or ()) == len(submesh.vertices)
        else []
    )
    if not variant.normals or len(variant.normals) != len(variant.vertices):
        variant.normals = _compute_smooth_normals(variant.vertices, variant.faces)
    variant.source_vertex_map = source_order
    variant.vertex_count = len(variant.vertices)
    variant.face_count = len(variant.faces)
    return variant


def _pac_lod_variants_for_submesh(new_sm: SubMesh, desc: object, stored_lod_count: int) -> list[SubMesh]:
    faces = list(getattr(new_sm, "faces", ()) or [])
    if not faces:
        return []
    base_index_count = max(1, int((getattr(desc, "index_counts", ()) or [len(faces) * 3])[0] or len(faces) * 3))
    variants: list[SubMesh] = []
    for lod_idx in range(stored_lod_count):
        if lod_idx == 0:
            target_faces = len(faces)
        else:
            try:
                original_index_count = int(desc.index_counts[lod_idx] or 0)
            except Exception:
                original_index_count = 0
            ratio = max(0.0, min(1.0, float(original_index_count) / float(base_index_count))) if original_index_count else 1.0
            target_faces = max(1, min(len(faces), int(round(len(faces) * ratio))))
        variants.append(_pac_lod_submesh_variant(new_sm, target_faces))
    return variants


def _build_pac_full_rebuild(
    original_mesh: ParsedMesh,
    working_mesh: ParsedMesh,
    original_data: bytes,
    *,
    clone_descriptor_sources: Sequence[int] = (),
    clone_descriptor_names: Sequence[str] = (),
    output_descriptor_sources: Sequence[int] = (),
    output_descriptor_names: Sequence[str] = (),
    preserve_runtime_abi: bool = False,
) -> bytes:
    """Rebuild PAC geometry sections from scratch for topology-changing imports."""
    sections = _parse_par_sections(original_data)
    sec_by_idx = {sec["index"]: sec for sec in sections}
    sec0 = sec_by_idx.get(0)
    if not sec0:
        raise ValueError("PAC section table is missing section 0.")

    n_lods = original_data[sec0["offset"] + 4] if sec0["size"] >= 5 else 0
    if n_lods <= 0 or n_lods > 10:
        raise ValueError(f"Invalid PAC LOD count: {n_lods}")

    descriptors = _find_pac_descriptors(original_data, sec0["offset"], sec0["size"], n_lods)
    sec0_data = bytearray(original_data[sec0["offset"]:sec0["offset"] + sec0["size"]])
    if len(descriptors) < len(original_mesh.submeshes):
        raise ValueError("PAC descriptor count does not match the parsed original submesh set.")
    if preserve_runtime_abi and (clone_descriptor_sources or clone_descriptor_names or output_descriptor_sources or output_descriptor_names):
        raise ValueError("PAC runtime ABI preservation cannot clone or rename draw descriptors.")
    output_descriptor_sources = tuple(int(index) for index in tuple(output_descriptor_sources or ()))
    if output_descriptor_sources:
        if len(output_descriptor_sources) != len(working_mesh.submeshes):
            raise ValueError(
                "PAC source-owned output descriptor plan does not match the working mesh: "
                f"{len(output_descriptor_sources)} descriptor source(s), {len(working_mesh.submeshes)} submesh(es)."
            )
        descriptors = _build_pac_output_descriptors(
            sec0_data,
            sec0_offset=sec0["offset"],
            descriptors=descriptors[:len(original_mesh.submeshes)],
            descriptor_source_indices=output_descriptor_sources,
            descriptor_names=output_descriptor_names,
        )
        clone_descriptor_sources = ()
    else:
        clone_descriptor_sources = tuple(int(index) for index in tuple(clone_descriptor_sources or ()))
        expected_submesh_count = len(original_mesh.submeshes) + len(clone_descriptor_sources)
        if len(working_mesh.submeshes) != expected_submesh_count:
            raise ValueError(
                "PAC dense replacement output plan does not match the working mesh: "
                f"{len(working_mesh.submeshes)} submesh(es), expected {expected_submesh_count}."
            )
        descriptors = _append_pac_cloned_descriptors(
            sec0_data,
            sec0_offset=sec0["offset"],
            descriptors=descriptors[:len(original_mesh.submeshes)],
            clone_descriptor_sources=clone_descriptor_sources,
            clone_descriptor_names=clone_descriptor_names,
        )
    if len(descriptors) < len(working_mesh.submeshes):
        raise ValueError("PAC descriptor count does not match the planned submesh set.")
    preserved_sections = {
        sec["index"]: original_data[sec["offset"]:sec["offset"] + sec["size"]]
        for sec in sections
        if sec["index"] > n_lods
    }
    prepared_submeshes = []
    for sm_idx, (new_sm, desc) in enumerate(zip(working_mesh.submeshes, descriptors)):
        if output_descriptor_sources:
            source_target_index = output_descriptor_sources[sm_idx]
        elif sm_idx < len(original_mesh.submeshes):
            source_target_index = sm_idx
        else:
            source_target_index = clone_descriptor_sources[sm_idx - len(original_mesh.submeshes)]
        if source_target_index < 0 or source_target_index >= len(original_mesh.submeshes):
            raise ValueError(f"PAC cloned submesh {sm_idx} references invalid source target {source_target_index}.")
        orig_sm = original_mesh.submeshes[source_target_index]
        if not new_sm.vertices and not new_sm.faces:
            rel_desc_off = desc.descriptor_offset - sec0["offset"]
            if rel_desc_off < 0 or rel_desc_off + 40 > len(sec0_data):
                raise ValueError(f"PAC descriptor {sm_idx} points outside section 0.")
            vc_off = rel_desc_off + 40
            ic_off = vc_off + desc.stored_lod_count * 2
            for lod_idx in range(desc.stored_lod_count):
                struct.pack_into("<H", sec0_data, vc_off + lod_idx * 2, 0)
                struct.pack_into("<I", sec0_data, ic_off + lod_idx * 4, 0)
            logger.info(
                "PAC submesh %d ('%s') is an empty placeholder; writing zero vertex/index counts.",
                sm_idx,
                new_sm.name,
            )
            continue

        if not orig_sm.source_vertex_offsets or orig_sm.source_vertex_stride < 12:
            raise ValueError(
                f"PAC submesh {sm_idx} is missing source vertex metadata for a full rebuild."
            )

        donor_records = []
        for rec_off in orig_sm.source_vertex_offsets:
            if rec_off < 0 or rec_off + orig_sm.source_vertex_stride > len(original_data):
                raise ValueError(
                    f"PAC vertex record for submesh {sm_idx} points outside the file."
                )
            donor_records.append(original_data[rec_off:rec_off + orig_sm.source_vertex_stride])
        donor_indices = _choose_pac_donor_indices(orig_sm, new_sm)
        skin_palette = pac_skin_export_palette(orig_sm, new_sm, getattr(desc, "palette", ()) or (), sm_idx)
        normals = (
            new_sm.normals
            if len(new_sm.normals) == len(new_sm.vertices)
            else _compute_smooth_normals(new_sm.vertices, new_sm.faces)
        )
        new_uvs = new_sm.uvs if len(new_sm.uvs) == len(new_sm.vertices) else []
        clean_shading_records = bool(
            getattr(new_sm, "clean_donor_shading_records", False)
            or getattr(working_mesh, "clean_donor_shading_records", False)
        )
        bmin, bmax = _compute_bbox(new_sm.vertices)
        extent = tuple(bmax[i] - bmin[i] for i in range(3))
        stored_lod_count = max(1, min(n_lods, orig_sm.source_lod_count or desc.stored_lod_count or n_lods))
        lod_variants = _pac_lod_variants_for_submesh(new_sm, desc, stored_lod_count)
        if not lod_variants:
            lod_variants = [new_sm]
        rel_desc_off = desc.descriptor_offset - sec0["offset"]
        if rel_desc_off < 0 or rel_desc_off + 40 > len(sec0_data):
            raise ValueError(f"PAC descriptor {sm_idx} points outside section 0.")

        _patch_pac_descriptor_bounds(sec0_data, rel_desc_off, bmin, extent)
        vc_off = rel_desc_off + 40
        ic_off = vc_off + desc.stored_lod_count * 2
        for lod_idx in range(desc.stored_lod_count):
            variant = lod_variants[min(lod_idx, len(lod_variants) - 1)] if lod_variants else new_sm
            struct.pack_into("<H", sec0_data, vc_off + lod_idx * 2, len(variant.vertices))
            struct.pack_into("<I", sec0_data, ic_off + lod_idx * 4, len(variant.faces) * 3)

        prepared_submeshes.append({
            "submesh": new_sm,
            "donor_records": donor_records,
            "donor_indices": donor_indices,
            "bbox_min": bmin,
            "bbox_extent": extent,
            "stored_lod_count": stored_lod_count,
            "clean_shading_records": clean_shading_records,
            "lod_variants": lod_variants,
            "skin_palette": skin_palette,
        })
    lod_payloads: dict[int, bytes] = {}
    lod_split_bytes: dict[int, int] = {}
    for sec_idx in range(1, n_lods + 1):
        lod_idx = n_lods - sec_idx
        verts_buf = bytearray()
        idx_buf = bytearray()

        for sm_idx, prepared in enumerate(prepared_submeshes):
            if lod_idx >= prepared["stored_lod_count"]:
                continue
            lod_variants = prepared["lod_variants"]
            sm = lod_variants[min(lod_idx, len(lod_variants) - 1)] if lod_variants else prepared["submesh"]
            donor_records = prepared["donor_records"]
            donor_indices = prepared["donor_indices"]
            normals = (
                sm.normals
                if len(getattr(sm, "normals", ()) or ()) == len(sm.vertices)
                else _compute_smooth_normals(sm.vertices, sm.faces)
            )
            new_uvs = sm.uvs if len(getattr(sm, "uvs", ()) or ()) == len(sm.vertices) else []
            source_vertex_map = (
                list(getattr(sm, "source_vertex_map", ()) or [])
                if len(getattr(sm, "source_vertex_map", ()) or []) == len(sm.vertices)
                else list(range(len(sm.vertices)))
            )
            bbox_min = prepared["bbox_min"]
            bbox_extent = prepared["bbox_extent"]
            clean_shading_records = prepared["clean_shading_records"]
            for vi, vertex in enumerate(sm.vertices):
                base_vi = source_vertex_map[vi] if vi < len(source_vertex_map) else vi
                skin_vi = int(base_vi)
                base_vi = max(0, min(base_vi, len(donor_indices) - 1))
                donor_rec = bytearray(donor_records[donor_indices[base_vi]])
                if clean_shading_records:
                    if len(donor_rec) >= 8:
                        struct.pack_into("<H", donor_rec, 6, 0)
                    if len(donor_rec) >= 28:
                        donor_rec[20:28] = b"\x00" * 8
                struct.pack_into(
                    "<HHH",
                    donor_rec,
                    0,
                    _quantize_pac_u16(vertex[0], bbox_min[0], bbox_extent[0]),
                    _quantize_pac_u16(vertex[1], bbox_min[1], bbox_extent[1]),
                    _quantize_pac_u16(vertex[2], bbox_min[2], bbox_extent[2]),
                )

                if len(donor_rec) >= 12:
                    if new_uvs:
                        try:
                            struct.pack_into("<e", donor_rec, 8, new_uvs[vi][0])
                            struct.pack_into("<e", donor_rec, 10, new_uvs[vi][1])
                        except (OverflowError, ValueError):
                            struct.pack_into("<e", donor_rec, 8, 0.0)
                            struct.pack_into("<e", donor_rec, 10, 0.0)

                if len(donor_rec) >= 20:
                    existing_normal = struct.unpack_from("<I", donor_rec, 16)[0]
                    struct.pack_into(
                        "<I",
                        donor_rec,
                        16,
                        _pack_pac_normal(
                            normals[vi],
                            0 if clean_shading_records else existing_normal,
                        ),
                    )

                if prepared["skin_palette"] is not None:
                    patch_pac_vertex_skin(donor_rec, prepared["submesh"], skin_vi, prepared["skin_palette"], sm_idx)

                verts_buf.extend(donor_rec)

            for face in sm.faces:
                a, b, c = face
                if a >= len(sm.vertices) or b >= len(sm.vertices) or c >= len(sm.vertices):
                    raise ValueError(f"PAC face in submesh {sm_idx} references an out-of-range vertex.")
                idx_buf.extend(struct.pack("<HHH", a, b, c))

        lod_split_bytes[sec_idx] = len(verts_buf)
        lod_payloads[sec_idx] = bytes(verts_buf + idx_buf)

    section_payloads: dict[int, bytes] = {0: bytes(sec0_data)}
    section_payloads.update(lod_payloads)
    section_payloads.update(preserved_sections)

    header = bytearray(original_data[:0x50])
    for slot in range(8):
        struct.pack_into("<I", header, 0x10 + slot * 8, 0)
        struct.pack_into("<I", header, 0x10 + slot * 8 + 4, 0)

    section_offsets = {0: 0x50}
    next_offset = 0x50 + len(section_payloads[0])
    for slot in range(1, 8):
        payload = section_payloads.get(slot)
        if payload is None:
            continue
        section_offsets[slot] = next_offset
        next_offset += len(payload)

    off = 5
    for lod_idx in range(n_lods):
        sec_idx = n_lods - lod_idx
        struct.pack_into("<I", sec0_data, off + lod_idx * 4, section_offsets[sec_idx])
    off += n_lods * 4
    for lod_idx in range(n_lods):
        sec_idx = n_lods - lod_idx
        split_abs = section_offsets[sec_idx] + lod_split_bytes.get(sec_idx, 0)
        struct.pack_into("<I", sec0_data, off + lod_idx * 4, split_abs)
    section_payloads[0] = bytes(sec0_data)

    assembled = bytearray(header)
    for slot in range(8):
        payload = section_payloads.get(slot)
        if payload is None:
            continue
        struct.pack_into("<I", assembled, 0x10 + slot * 8, 0)
        struct.pack_into("<I", assembled, 0x10 + slot * 8 + 4, len(payload))
        assembled.extend(payload)

    logger.info(
        "Built PAC %s with full rebuild: %d bytes, %d submeshes, %d verts, %d faces",
        working_mesh.path,
        len(assembled),
        len(working_mesh.submeshes),
        sum(len(sm.vertices) for sm in working_mesh.submeshes),
        sum(len(sm.faces) for sm in working_mesh.submeshes),
    )
    return bytes(assembled)


def _format_roundtrip_topology_error(
    *,
    mesh_label: str,
    original_mesh: ParsedMesh,
    imported_mesh: ParsedMesh,
) -> str:
    return "\n".join(
        [
            f"{mesh_label} round-trip import failed.",
            "",
            "Original mesh:",
            f"  submeshes: {len(original_mesh.submeshes)}",
            f"  vertices: {sum(len(sm.vertices) for sm in original_mesh.submeshes)}",
            f"  faces: {sum(len(sm.faces) for sm in original_mesh.submeshes)}",
            "",
            "Imported OBJ:",
            f"  submeshes: {len(imported_mesh.submeshes)}",
            f"  vertices: {sum(len(sm.vertices) for sm in imported_mesh.submeshes)}",
            f"  faces: {sum(len(sm.faces) for sm in imported_mesh.submeshes)}",
            "",
            "This mode requires the imported OBJ to keep the original mesh structure. "
            "Use Static Mesh Replacement mode to import a different model.",
        ]
    )


def build_pac(mesh: ParsedMesh, original_data: bytes) -> bytes:  # noqa: F811
    """Rebuild a PAC binary from a modified mesh."""
    if not original_data or original_data[:4] != b"PAR ":
        raise ValueError("Original PAC data required for rebuild")

    original_mesh = parse_pac(original_data, mesh.path)
    if not original_mesh.submeshes:
        raise ValueError("Original PAC could not be parsed into usable geometry")

    working_mesh = copy.deepcopy(mesh)
    working_mesh = _merge_partial_pac_import(original_mesh, working_mesh)
    _align_submesh_order_like_original(original_mesh, working_mesh)

    if len(original_mesh.submeshes) != len(working_mesh.submeshes):
        raise ValueError(
            _format_roundtrip_topology_error(
                mesh_label="PAC",
                original_mesh=original_mesh,
                imported_mesh=working_mesh,
            )
        )

    if _pac_needs_full_rebuild(original_mesh, working_mesh):
        return _build_pac_full_rebuild(original_mesh, working_mesh, original_data)
    return _build_pac_in_place(original_mesh, working_mesh, original_data)
