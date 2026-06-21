"""PAMLOD rebuild and PAM-to-PAMLOD transfer helpers."""

from __future__ import annotations

import copy
import math
import re
import struct
from typing import Optional

from .logging import get_logger
from .mesh_builder_common import (
    _align_static_vertex_sequences,
    _align_submesh_order_like_original,
    _apply_quantized_vertex_patches,
    _build_spatial_hash,
    _choose_static_donor_indices,
    _collect_vertex_offset_refs,
    _compute_bbox,
    _expand_bbox_to_vertices,
    _make_temp_mesh,
    _make_vertex_template_record,
    _merge_partial_static_import,
    _nearby_point_indices,
    _nearest_point_index,
    _pack_static_vertex_record,
    _percentile,
    _submesh_uvs_match,
)
from .mesh_parser import (
    ParsedMesh,
    SubMesh,
    STRIDE_CANDIDATES,
    _compute_smooth_normals,
    _dequant_u16,
    parse_pam,
    parse_pamlod,
)

logger = get_logger("core.mesh_importer")

def transfer_pam_edit_to_pamlod_mesh(
    edited_pam_mesh: ParsedMesh,
    original_pam_data: bytes,
    original_pamlod_data: bytes,
    pamlod_path: str,
) -> ParsedMesh:
    """Project a PAM edit onto the paired PAMLOD levels via nearest displacement."""
    original_pam_mesh = parse_pam(original_pam_data, edited_pam_mesh.path)
    editable_pam_mesh = _merge_partial_static_import(original_pam_mesh, copy.deepcopy(edited_pam_mesh))
    _align_submesh_order_like_original(original_pam_mesh, editable_pam_mesh)

    source_orig = [v for sm in original_pam_mesh.submeshes for v in sm.vertices]
    source_new = [v for sm in editable_pam_mesh.submeshes for v in sm.vertices]
    if not source_orig or not source_new:
        raise ValueError("PAM to PAMLOD transfer requires non-empty source geometry.")

    if len(source_orig) == len(source_new):
        paired_points = zip(source_orig, source_new)
    else:
        # Topology edits cannot be transferred one-to-one, so approximate the
        # deformation field by matching each original PAM vertex to its nearest
        # edited-space vertex. This keeps paired PAMLOD patching alive for
        # sculpt/retopo-style edits instead of failing outright.
        edit_cell_size, edit_grid = _build_spatial_hash(source_new)
        nearest_points = [
            source_new[_nearest_point_index(orig_v, source_new, edit_cell_size, edit_grid)]
            for orig_v in source_orig
        ]
        paired_points = zip(source_orig, nearest_points)

    changed_points: list[tuple[float, float, float]] = []
    changed_displacements: list[tuple[float, float, float]] = []
    for orig_v, new_v in paired_points:
        disp = (new_v[0] - orig_v[0], new_v[1] - orig_v[1], new_v[2] - orig_v[2])
        if math.sqrt(disp[0] ** 2 + disp[1] ** 2 + disp[2] ** 2) > 1e-6:
            changed_points.append(orig_v)
            changed_displacements.append(disp)

    pamlod_mesh = parse_pamlod(original_pamlod_data, pamlod_path)
    if not changed_points:
        return pamlod_mesh

    cell_size, grid = _build_spatial_hash(changed_points)
    transferred = copy.deepcopy(pamlod_mesh)

    for lod_level in transferred.lod_levels:
        lod_vertices = [vertex for sm in lod_level for vertex in sm.vertices]
        if not lod_vertices:
            continue

        target_cell_size, target_grid = _build_spatial_hash(lod_vertices)
        sample_step = max(1, len(changed_points) // 512)
        target_distances = []
        for idx in range(0, len(changed_points), sample_step):
            source_vertex = changed_points[idx]
            nearest_idx = _nearest_point_index(
                source_vertex, lod_vertices, target_cell_size, target_grid
            )
            target_distances.append(math.dist(source_vertex, lod_vertices[nearest_idx]))

        influence_radius = max(
            _percentile(target_distances, 0.75) * 1.25,
            1e-4,
        )

        for sm in lod_level:
            new_vertices = []
            for vertex in sm.vertices:
                nearby = _nearby_point_indices(
                    vertex, changed_points, cell_size, grid, influence_radius
                )
                if not nearby:
                    new_vertices.append(vertex)
                    continue

                exact_disp = None
                acc_x = acc_y = acc_z = 0.0
                weight_sum = 0.0
                for idx in nearby:
                    src = changed_points[idx]
                    disp = changed_displacements[idx]
                    dist = math.dist(vertex, src)
                    if dist <= 1e-8:
                        exact_disp = disp
                        break
                    weight = (1.0 - min(dist / influence_radius, 1.0)) ** 2
                    if weight <= 0.0:
                        continue
                    acc_x += disp[0] * weight
                    acc_y += disp[1] * weight
                    acc_z += disp[2] * weight
                    weight_sum += weight

                if exact_disp is not None:
                    dx, dy, dz = exact_disp
                elif weight_sum > 0.0:
                    dx = acc_x / weight_sum
                    dy = acc_y / weight_sum
                    dz = acc_z / weight_sum
                else:
                    dx = dy = dz = 0.0

                new_vertices.append((vertex[0] + dx, vertex[1] + dy, vertex[2] + dz))
            sm.vertices = new_vertices
            sm.vertex_count = len(new_vertices)
            sm.normals = _compute_smooth_normals(sm.vertices, sm.faces)

    if transferred.lod_levels:
        for lod_level in transferred.lod_levels:
            if lod_level:
                transferred.submeshes = lod_level
                break

    transferred.total_vertices = sum(len(sm.vertices) for sm in transferred.submeshes)
    transferred.total_faces = sum(len(sm.faces) for sm in transferred.submeshes)
    transferred.has_uvs = any(sm.uvs for sm in transferred.submeshes)
    return transferred

def _pamlod_needs_full_rebuild(
    original_lod_levels: list[list[SubMesh]],
    target_lod_levels: list[list[SubMesh]],
) -> bool:
    if len(original_lod_levels) != len(target_lod_levels):
        return True
    for original_level, target_level in zip(original_lod_levels, target_lod_levels):
        if len(original_level) != len(target_level):
            return True
        for original_sm, target_sm in zip(original_level, target_level):
            if len(original_sm.vertices) != len(target_sm.vertices):
                return True
            if len(original_sm.faces) != len(target_sm.faces):
                return True
            if original_sm.faces != target_sm.faces:
                return True
            if not _submesh_uvs_match(original_sm, target_sm):
                return True
    return False


def _inspect_pamlod_lod0_layout(original_data: bytes) -> dict:
    if not original_data or len(original_data) < 0x50:
        return {"kind": "unsupported", "reason": "missing PAMLOD header"}
    lod_count = struct.unpack_from("<I", original_data, 0x00)[0]
    geom_off = struct.unpack_from("<I", original_data, 0x04)[0]
    if lod_count <= 0 or geom_off <= 0 or geom_off >= len(original_data):
        return {"kind": "unsupported", "reason": "invalid PAMLOD geometry header"}

    entries = []
    for match in re.finditer(rb"[^\x00]{1,255}\.dds\x00", original_data[0x50:geom_off]):
        tex_start = 0x50 + match.start()
        nv_off = tex_start - 0x10
        if nv_off < 0x50:
            continue
        nv, ni, voff, ioff = struct.unpack_from("<IIII", original_data, nv_off)
        if not (1 <= nv <= 131072 and ni > 0 and ni % 3 == 0):
            continue
        tex = original_data[tex_start:tex_start + 256].split(b"\x00")[0].decode("ascii", "replace")
        mat_start = tex_start + 0x100
        mat = original_data[mat_start:mat_start + 256].split(b"\x00")[0].decode("ascii", "replace") if mat_start < geom_off else ""
        entries.append({"nv": nv, "ni": ni, "voff": voff, "ioff": ioff, "tex_start": tex_start, "desc_off": nv_off, "tex": tex, "mat": mat})
    entries.sort(key=lambda entry: entry["tex_start"])
    if not entries:
        return {"kind": "unsupported", "reason": "PAMLOD entry table is empty"}

    groups = []
    current = []
    ve_acc = ie_acc = 0
    for entry in entries:
        if current and (entry["voff"] != ve_acc or entry["ioff"] != ie_acc):
            groups.append(current)
            current = []
        current.append(entry)
        ve_acc = entry["voff"] + entry["nv"]
        ie_acc = entry["ioff"] + entry["ni"]
    if current:
        groups.append(current)
    groups = groups[:lod_count]
    if not groups or not groups[0]:
        return {"kind": "unsupported", "reason": "PAMLOD LOD0 entry group is empty"}

    group = groups[0]
    total_nv = sum(entry["nv"] for entry in group)
    total_ni = sum(entry["ni"] for entry in group)
    for pad in list(range(0, 64, 2)) + list(range(64, 512, 4)) + list(range(512, 4096, 8)):
        base = geom_off + pad
        for stride in sorted(STRIDE_CANDIDATES, key=lambda value: (abs(value - 20), value)):
            idx_off = base + total_nv * stride
            if idx_off + total_ni * 2 > len(original_data):
                continue
            ok = True
            for j in range(min(total_ni, 100)):
                if struct.unpack_from("<H", original_data, idx_off + j * 2)[0] >= total_nv:
                    ok = False
                    break
            if ok:
                return {
                    "kind": "lod0" if len(group) > 1 else "lod0_single",
                    "lod_count": lod_count,
                    "geom_off": geom_off,
                    "entry": group[0],
                    "entries": group,
                    "vertex_base": base,
                    "stride": stride,
                    "idx_off": idx_off,
                    "old_lod0_end": idx_off + total_ni * 2,
                }
    return {"kind": "unsupported", "reason": "could not locate PAMLOD LOD0 geometry layout"}


def _pamlod_lod0_original_parts(original_data: bytes, layout: dict) -> list[SubMesh]:
    """Reconstruct the per-entry LOD0 parts hidden by the public flattened parser."""
    entries = list(layout.get("entries") or ([layout["entry"]] if layout.get("entry") else []))
    stride = int(layout.get("stride", 0) or 0)
    vertex_base = int(layout.get("vertex_base", 0) or 0)
    idx_base = int(layout.get("idx_off", 0) or 0)
    if not entries or stride <= 0 or vertex_base <= 0 or idx_base <= 0:
        return []

    bmin = struct.unpack_from("<fff", original_data, 0x10)
    bmax = struct.unpack_from("<fff", original_data, 0x1C)
    parts: list[SubMesh] = []
    for part_index, entry in enumerate(entries):
        nv = int(entry.get("nv", 0) or 0)
        ni = int(entry.get("ni", 0) or 0)
        voff = int(entry.get("voff", 0) or 0)
        ioff = int(entry.get("ioff", 0) or 0)
        idx_off = idx_base + ioff * 2
        if nv <= 0 or ni <= 0 or idx_off + ni * 2 > len(original_data):
            return []
        indices = [struct.unpack_from("<H", original_data, idx_off + j * 2)[0] for j in range(ni)]
        unique = sorted(index for index in set(indices) if 0 <= index < nv)
        idx_map = {global_index: local_index for local_index, global_index in enumerate(unique)}
        vertices: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        offsets: list[int] = []
        for global_index in unique:
            rec_off = vertex_base + (voff + global_index) * stride
            if rec_off + 6 > len(original_data):
                return []
            xu, yu, zu = struct.unpack_from("<HHH", original_data, rec_off)
            vertices.append(
                (
                    _dequant_u16(xu, bmin[0], bmax[0]),
                    _dequant_u16(yu, bmin[1], bmax[1]),
                    _dequant_u16(zu, bmin[2], bmax[2]),
                )
            )
            offsets.append(rec_off)
            if stride >= 12 and rec_off + 12 <= len(original_data):
                uvs.append((struct.unpack_from("<e", original_data, rec_off + 8)[0], struct.unpack_from("<e", original_data, rec_off + 10)[0]))
        faces: list[tuple[int, int, int]] = []
        for j in range(0, ni - 2, 3):
            a, b, c = indices[j], indices[j + 1], indices[j + 2]
            if a in idx_map and b in idx_map and c in idx_map:
                faces.append((idx_map[a], idx_map[b], idx_map[c]))
        part = SubMesh(
            name=f"lod00_part{part_index:02d}_{entry.get('mat') or part_index}",
            material=str(entry.get("mat") or ""),
            texture=str(entry.get("tex") or ""),
            vertices=vertices,
            uvs=uvs if len(uvs) == len(vertices) else [],
            faces=faces,
            normals=_compute_smooth_normals(vertices, faces),
            source_vertex_offsets=offsets,
            vertex_count=len(vertices),
            face_count=len(faces),
        )
        parts.append(part)
    return parts


def _split_pamlod_lod0_edit_by_entries(
    lod0_submeshes: list[SubMesh],
    original_parts: list[SubMesh],
) -> list[SubMesh]:
    """Split a flattened edited LOD0 back into original PAMLOD entry parts."""
    if not original_parts:
        raise ValueError("PAMLOD LOD0 original entry mapping is unavailable.")
    if len(lod0_submeshes) == len(original_parts):
        for submesh in lod0_submeshes:
            vertices = list(getattr(submesh, "vertices", []) or [])
            if len(vertices) > 65535:
                raise ValueError("PAMLOD LOD0 entry rebuild supports at most 65535 vertices per entry.")
            for face in getattr(submesh, "faces", []) or []:
                if len(face) != 3 or min(face) < 0 or max(face) >= len(vertices):
                    raise ValueError("PAMLOD face references an out-of-range vertex.")
        return lod0_submeshes
    if len(lod0_submeshes) != 1:
        raise ValueError("PAMLOD LOD0 rebuild requires either one flattened submesh or one submesh per LOD0 entry.")

    combined = lod0_submeshes[0]
    vertices = list(getattr(combined, "vertices", []) or [])
    faces = list(getattr(combined, "faces", []) or [])
    uvs = list(getattr(combined, "uvs", []) or [])
    original_ranges: list[tuple[int, int]] = []
    cursor = 0
    for part in original_parts:
        start = cursor
        cursor += len(getattr(part, "vertices", []) or [])
        original_ranges.append((start, cursor))
    original_total = cursor

    assignments = [-1] * len(vertices)
    if len(vertices) >= original_total:
        for part_index, (start, end) in enumerate(original_ranges):
            for vertex_index in range(start, min(end, len(vertices))):
                assignments[vertex_index] = part_index
    else:
        original_vertices = [
            vertex
            for part in original_parts
            for vertex in getattr(part, "vertices", []) or []
        ]

        def original_part_for_index(original_index: int) -> int:
            for part_index, (start, end) in enumerate(original_ranges):
                if start <= original_index < end:
                    return part_index
            return -1

        try:
            aligned_original_indices = _align_static_vertex_sequences(original_vertices, vertices)
        except Exception as exc:
            logger.debug("PAMLOD LOD0 deletion alignment fallback: %s", exc)
            aligned_original_indices = [-1] * len(vertices)
        for vertex_index, original_index in enumerate(aligned_original_indices):
            if 0 <= original_index < original_total:
                assignments[vertex_index] = original_part_for_index(original_index)

    part_vertices: list[list[tuple[float, float, float]]] = [[] for _ in original_parts]
    part_uvs: list[list[tuple[float, float]]] = [[] for _ in original_parts]
    part_faces: list[list[tuple[int, int, int]]] = [[] for _ in original_parts]
    part_vertex_maps: list[dict[int, int]] = [{} for _ in original_parts]
    part_centroids: list[tuple[float, float, float]] = []
    for part in original_parts:
        part_original_vertices = list(getattr(part, "vertices", []) or [])
        if part_original_vertices:
            xs, ys, zs = zip(*part_original_vertices)
            part_centroids.append((sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)))
        else:
            part_centroids.append((0.0, 0.0, 0.0))

    def nearest_part_for_vertex(vertex: tuple[float, float, float]) -> int:
        if not part_centroids:
            return 0
        return min(
            range(len(part_centroids)),
            key=lambda index: math.dist(vertex, part_centroids[index]),
        )

    def choose_face_part(face: tuple[int, int, int]) -> int:
        known = [assignments[index] for index in face if assignments[index] >= 0]
        if known:
            counts = {part_index: known.count(part_index) for part_index in set(known)}
            first_known = next(assignments[index] for index in face if assignments[index] >= 0)
            return max(counts, key=lambda part_index: (counts[part_index], part_index == first_known, -part_index))
        centroid = (
            sum(vertices[index][0] for index in face) / 3.0,
            sum(vertices[index][1] for index in face) / 3.0,
            sum(vertices[index][2] for index in face) / 3.0,
        )
        return nearest_part_for_vertex(centroid)

    def local_index_for(part_index: int, global_index: int) -> int:
        existing = part_vertex_maps[part_index].get(global_index)
        if existing is not None:
            return existing
        local_index = len(part_vertices[part_index])
        part_vertices[part_index].append(vertices[global_index])
        if len(uvs) == len(vertices):
            part_uvs[part_index].append(uvs[global_index])
        part_vertex_maps[part_index][global_index] = local_index
        return local_index

    for vertex_index, part_index in enumerate(assignments):
        if part_index >= 0:
            local_index_for(part_index, vertex_index)

    for face in faces:
        if len(face) != 3 or min(face) < 0 or max(face) >= len(vertices):
            raise ValueError("PAMLOD face references an out-of-range vertex.")
        part_index = choose_face_part(face)
        part_faces[part_index].append(
            (
                local_index_for(part_index, face[0]),
                local_index_for(part_index, face[1]),
                local_index_for(part_index, face[2]),
            )
        )

    for vertex_index in range(len(vertices)):
        if not any(vertex_index in vertex_map for vertex_map in part_vertex_maps):
            local_index_for(nearest_part_for_vertex(vertices[vertex_index]), vertex_index)

    split_parts: list[SubMesh] = []
    for part_index, original_part in enumerate(original_parts):
        if len(part_vertices[part_index]) > 65535:
            raise ValueError("PAMLOD LOD0 entry rebuild supports at most 65535 vertices per entry.")
        local_vertices = part_vertices[part_index]
        local_uvs = part_uvs[part_index] if len(part_uvs[part_index]) == len(local_vertices) else []
        split_parts.append(
            SubMesh(
                name=getattr(original_part, "name", "") or f"lod00_part{part_index:02d}",
                material=getattr(original_part, "material", ""),
                texture=getattr(original_part, "texture", ""),
                vertices=local_vertices,
                uvs=local_uvs,
                faces=part_faces[part_index],
                normals=_compute_smooth_normals(local_vertices, part_faces[part_index]),
                vertex_count=len(local_vertices),
                face_count=len(part_faces[part_index]),
            )
        )
    return split_parts


def _serialize_pamlod_lod0_full_rebuild(
    lod0_submeshes: list[SubMesh],
    original_mesh: ParsedMesh,
    original_data: bytes,
    mesh_path: str,
) -> bytes:
    layout = _inspect_pamlod_lod0_layout(original_data)
    if layout["kind"] not in {"lod0_single", "lod0"}:
        raise ValueError(
            "This PAMLOD layout currently supports position-only patching. "
            f"Topology/UV edits are not supported for it yet ({layout.get('reason', 'unknown layout')})."
        )
    original_parts = _pamlod_lod0_original_parts(original_data, layout)
    rebuilt_parts = _split_pamlod_lod0_edit_by_entries(lod0_submeshes, original_parts)

    all_vertices = [
        vertex
        for lod_level in original_mesh.lod_levels[1:]
        for submesh in lod_level
        for vertex in submesh.vertices
    ] + [vertex for part in rebuilt_parts for vertex in part.vertices]
    bmin, bmax = _compute_bbox(all_vertices)
    result = bytearray(original_data[:layout["vertex_base"]])
    struct.pack_into("<fff", result, 0x10, *bmin)
    struct.pack_into("<fff", result, 0x1C, *bmax)

    stride = layout["stride"]
    entries = list(layout.get("entries") or [layout["entry"]])
    vertex_cursor = 0
    index_cursor = 0
    geom_data = bytearray()
    index_data = bytearray()
    for entry, orig_part, part in zip(entries, original_parts, rebuilt_parts):
        vertices = list(part.vertices)
        faces = list(part.faces)
        struct.pack_into("<I", result, entry["desc_off"], len(vertices))
        struct.pack_into("<I", result, entry["desc_off"] + 4, len(faces) * 3)
        struct.pack_into("<I", result, entry["desc_off"] + 8, vertex_cursor)
        struct.pack_into("<I", result, entry["desc_off"] + 12, index_cursor)
        donor_indices = _choose_static_donor_indices(orig_part, part)
        uv_data = part.uvs if len(part.uvs) == len(vertices) else []
        source_offsets = list(getattr(orig_part, "source_vertex_offsets", []) or [])
        for vertex_index, vertex in enumerate(vertices):
            donor_index = donor_indices[vertex_index] if vertex_index < len(donor_indices) else vertex_index
            donor_index = max(0, min(int(donor_index), max(0, len(source_offsets) - 1)))
            source_offset = source_offsets[donor_index] if source_offsets else layout["vertex_base"]
            rec = _make_vertex_template_record(
                original_data,
                source_offset,
                stride,
                0,
                1,
            )
            uv = uv_data[vertex_index] if uv_data else None
            geom_data.extend(_pack_static_vertex_record(rec, stride, vertex, uv, bmin, bmax))
        for a, b, c in faces:
            if max(a, b, c) >= len(vertices) or min(a, b, c) < 0:
                raise ValueError("PAMLOD face references an out-of-range vertex.")
            index_data.extend(struct.pack("<HHH", a, b, c))
        vertex_cursor += len(vertices)
        index_cursor += len(faces) * 3

    result.extend(geom_data)
    result.extend(index_data)
    result.extend(original_data[layout["old_lod0_end"]:])
    logger.info(
        "Built PAMLOD %s with full LOD0 rebuild: %d parts, %d verts, %d faces",
        mesh_path,
        len(rebuilt_parts),
        sum(len(part.vertices) for part in rebuilt_parts),
        sum(len(part.faces) for part in rebuilt_parts),
    )
    return bytes(result)


def build_pamlod(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Rebuild a PAMLOD binary by patching vertex positions in-place."""
    if not original_data or len(original_data) < 0x20:
        raise ValueError("Original PAMLOD data required for rebuild")

    HDR_BBOX_MIN = 0x10
    HDR_BBOX_MAX = 0x1C

    result = bytearray(original_data)
    orig_bmin = struct.unpack_from("<fff", original_data, HDR_BBOX_MIN)
    orig_bmax = struct.unpack_from("<fff", original_data, HDR_BBOX_MAX)

    orig_mesh = parse_pamlod(original_data, mesh.path)
    if not orig_mesh.lod_levels:
        return bytes(result)

    target_lod_levels = copy.deepcopy(orig_mesh.lod_levels)
    replaced_lod_index: Optional[int] = None
    if mesh.lod_levels:
        for lod_idx, lod_level in enumerate(mesh.lod_levels):
            if lod_idx < len(target_lod_levels) and lod_level:
                target_lod_levels[lod_idx] = copy.deepcopy(lod_level)
                replaced_lod_index = lod_idx if replaced_lod_index is None else replaced_lod_index
    elif mesh.submeshes:
        replace_idx = next((i for i, lod in enumerate(target_lod_levels) if lod), 0)
        target_lod_levels[replace_idx] = copy.deepcopy(mesh.submeshes)
        replaced_lod_index = replace_idx

    if _pamlod_needs_full_rebuild(orig_mesh.lod_levels, target_lod_levels):
        if replaced_lod_index != 0:
            raise ValueError("PAMLOD topology-changing rebuild is currently supported for LOD0 only.")
        return _serialize_pamlod_lod0_full_rebuild(
            target_lod_levels[0],
            orig_mesh,
            original_data,
            mesh.path or orig_mesh.path,
        )

    all_vertices = [
        v
        for lod_level in target_lod_levels
        for sm in lod_level
        for v in sm.vertices
    ]
    bmin, bmax = _expand_bbox_to_vertices(orig_bmin, orig_bmax, all_vertices)
    struct.pack_into("<fff", result, HDR_BBOX_MIN, *bmin)
    struct.pack_into("<fff", result, HDR_BBOX_MAX, *bmax)

    offset_refs: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]]] = {}
    for lod_idx, orig_level in enumerate(orig_mesh.lod_levels):
        if lod_idx >= len(target_lod_levels):
            break
        new_level = target_lod_levels[lod_idx]
        if not orig_level or not new_level:
            continue

        level_orig_mesh = _make_temp_mesh(orig_mesh.path, "pamlod", orig_level)
        level_new_mesh = _make_temp_mesh(mesh.path or orig_mesh.path, "pamlod", new_level)
        level_refs = _collect_vertex_offset_refs(
            original_data, level_orig_mesh, level_new_mesh, orig_bmin, orig_bmax, search_start=0
        )
        for byte_off, refs in level_refs.items():
            offset_refs.setdefault(byte_off, []).extend(refs)

    patched_offsets = _apply_quantized_vertex_patches(
        result, offset_refs, bmin, bmax, allow_average_conflicts=True
    )
    logger.info("Built PAMLOD %s: %d bytes (patched %d verts in-place)",
                mesh.path, len(result), patched_offsets)
    return bytes(result)
