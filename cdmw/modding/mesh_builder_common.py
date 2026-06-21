"""Shared mesh rebuild helpers for PAC/PAM/PAMLOD importers."""

from __future__ import annotations

import copy
import math
import struct
from typing import Optional

from .logging import get_logger
from .mesh_parser import ParsedMesh, SubMesh

logger = get_logger("core.mesh_importer")

def _quantize_u16(value: float, vmin: float, vmax: float) -> int:
    """Float → uint16 quantized: inverse of dequantize."""
    if abs(vmax - vmin) < 1e-10:
        return 32768
    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    return min(65535, max(0, round(t * 65535)))


def _compute_bbox(vertices: list[tuple[float, float, float]]):
    """Compute tight bounding box from vertex list."""
    if not vertices:
        return (0, 0, 0), (1, 1, 1)
    xs, ys, zs = zip(*vertices)
    # Add tiny epsilon to avoid zero-size bbox
    eps = 1e-6
    bmin = (min(xs) - eps, min(ys) - eps, min(zs) - eps)
    bmax = (max(xs) + eps, max(ys) + eps, max(zs) + eps)
    return bmin, bmax


def _reorder_submeshes_to_match_original(original_mesh: ParsedMesh, imported_mesh: ParsedMesh) -> None:
    """Restore original submesh and vertex slot order for PAM/PAMLOD rebuilds."""
    if len(original_mesh.submeshes) != len(imported_mesh.submeshes):
        raise ValueError(
            "PAM/PAMLOD import requires the same submesh count as the original mesh."
        )

    orig_names = [sm.name for sm in original_mesh.submeshes]
    imp_names = [sm.name for sm in imported_mesh.submeshes]
    if orig_names != imp_names:
        name_to_submesh = {}
        for sm in imported_mesh.submeshes:
            if not sm.name or sm.name in name_to_submesh:
                break
            name_to_submesh[sm.name] = sm
        if len(name_to_submesh) == len(imported_mesh.submeshes) and set(name_to_submesh) == set(orig_names):
            imported_mesh.submeshes = [name_to_submesh[name] for name in orig_names]

    for sm_idx, (orig_sm, imp_sm) in enumerate(zip(original_mesh.submeshes, imported_mesh.submeshes)):
        if len(orig_sm.vertices) != len(imp_sm.vertices):
            raise ValueError(
                f"Submesh {sm_idx} changed vertex count "
                f"({len(orig_sm.vertices)} -> {len(imp_sm.vertices)}). "
                "PAM/PAMLOD import currently requires keeping the same topology."
            )
        if len(orig_sm.faces) != len(imp_sm.faces):
            raise ValueError(
                f"Submesh {sm_idx} changed face count "
                f"({len(orig_sm.faces)} -> {len(imp_sm.faces)}). "
                "PAM/PAMLOD import currently requires keeping the same topology."
            )

        if imp_sm.faces == orig_sm.faces:
            continue

        mapping: dict[int, int] = {}
        reverse: dict[int, int] = {}
        mapping_ok = True

        for orig_face, imp_face in zip(orig_sm.faces, imp_sm.faces):
            if len(orig_face) != len(imp_face):
                mapping_ok = False
                break
            for orig_idx, imp_idx in zip(orig_face, imp_face):
                prev_orig = mapping.get(imp_idx)
                prev_imp = reverse.get(orig_idx)
                if (prev_orig is not None and prev_orig != orig_idx) or (
                    prev_imp is not None and prev_imp != imp_idx
                ):
                    mapping_ok = False
                    break
                mapping[imp_idx] = orig_idx
                reverse[orig_idx] = imp_idx
            if not mapping_ok:
                break

        if (not mapping_ok or
                len(mapping) != len(orig_sm.vertices) or
                len(reverse) != len(orig_sm.vertices)):
            raise ValueError(
                f"Submesh {sm_idx} no longer matches the original triangle order. "
                "PAM/PAMLOD import can handle vertex renumbering, but it still "
                "requires preserving the original triangle list."
            )

        reordered_vertices = [None] * len(orig_sm.vertices)
        reordered_uvs = [None] * len(orig_sm.vertices) if len(imp_sm.uvs) == len(imp_sm.vertices) else None
        reordered_normals = [None] * len(orig_sm.vertices) if len(imp_sm.normals) == len(imp_sm.vertices) else None

        for imp_idx, orig_idx in mapping.items():
            reordered_vertices[orig_idx] = imp_sm.vertices[imp_idx]
            if reordered_uvs is not None:
                reordered_uvs[orig_idx] = imp_sm.uvs[imp_idx]
            if reordered_normals is not None:
                reordered_normals[orig_idx] = imp_sm.normals[imp_idx]

        imp_sm.vertices = reordered_vertices
        imp_sm.uvs = reordered_uvs if reordered_uvs is not None else imp_sm.uvs
        imp_sm.normals = reordered_normals if reordered_normals is not None else imp_sm.normals
        imp_sm.faces = list(orig_sm.faces)
        imp_sm.vertex_count = len(imp_sm.vertices)
        imp_sm.face_count = len(imp_sm.faces)


def _resolve_pam_alias_vertex(
    byte_off: int,
    refs: list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]],
    eps: float = 1e-6,
    allow_average_conflicts: bool = False,
) -> tuple[float, float, float]:
    """Choose one final position for a shared vertex byte offset."""
    changed: list[tuple[tuple[float, float, float], int, int]] = []
    for orig_v, new_v, sm_idx, vert_idx in refs:
        if math.dist(orig_v, new_v) > eps:
            changed.append((new_v, sm_idx, vert_idx))

    if not changed:
        return refs[0][1]

    chosen = changed[0][0]
    for new_v, sm_idx, vert_idx in changed[1:]:
        if math.dist(new_v, chosen) > eps:
            if allow_average_conflicts:
                xs = [pos[0][0] for pos in changed]
                ys = [pos[0][1] for pos in changed]
                zs = [pos[0][2] for pos in changed]
                return (
                    sum(xs) / len(xs),
                    sum(ys) / len(ys),
                    sum(zs) / len(zs),
                )
            raise ValueError(
                "Mesh import detected linked vertices that share the same source bytes, "
                f"but they were edited differently (offset 0x{byte_off:X}, "
                f"submesh {sm_idx} vertex {vert_idx}). "
                "Edit all linked copies to the same position, or keep the topology "
                "and overlapping pieces unchanged."
            )
    return chosen


def _make_temp_mesh(path: str, fmt: str, submeshes: list[SubMesh]) -> ParsedMesh:
    """Build a lightweight ParsedMesh wrapper for helper operations."""
    return ParsedMesh(
        path=path,
        format=fmt,
        submeshes=submeshes,
        total_vertices=sum(len(sm.vertices) for sm in submeshes),
        total_faces=sum(len(sm.faces) for sm in submeshes),
        has_uvs=any(sm.uvs for sm in submeshes),
    )


def _expand_bbox_to_vertices(
    orig_bmin: tuple[float, float, float],
    orig_bmax: tuple[float, float, float],
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Expand an existing bbox to include all provided vertices."""
    if not vertices:
        return orig_bmin, orig_bmax
    xs, ys, zs = zip(*vertices)
    bmin = (
        min(orig_bmin[0], min(xs)),
        min(orig_bmin[1], min(ys)),
        min(orig_bmin[2], min(zs)),
    )
    bmax = (
        max(orig_bmax[0], max(xs)),
        max(orig_bmax[1], max(ys)),
        max(orig_bmax[2], max(zs)),
    )
    return bmin, bmax


def _collect_vertex_offset_refs(
    original_data: bytes,
    original_mesh: ParsedMesh,
    new_mesh: ParsedMesh,
    orig_bmin: tuple[float, float, float],
    orig_bmax: tuple[float, float, float],
    search_start: int = 0,
) -> dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]]]:
    """Map source byte offsets to original/new vertex pairs."""
    _reorder_submeshes_to_match_original(original_mesh, new_mesh)

    offset_refs: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]]] = {}
    search_cursor = search_start

    for sm_idx, (orig_sm, new_sm) in enumerate(zip(original_mesh.submeshes, new_mesh.submeshes)):
        n = min(len(orig_sm.vertices), len(new_sm.vertices))
        sm_offsets = list(orig_sm.source_vertex_offsets) if (
            len(orig_sm.source_vertex_offsets) == len(orig_sm.vertices)
        ) else []

        if not sm_offsets:
            for vi in range(len(orig_sm.vertices)):
                vx, vy, vz = orig_sm.vertices[vi]
                xu = _quantize_u16(vx, orig_bmin[0], orig_bmax[0])
                yu = _quantize_u16(vy, orig_bmin[1], orig_bmax[1])
                zu = _quantize_u16(vz, orig_bmin[2], orig_bmax[2])
                target = struct.pack("<HHH", xu, yu, zu)

                found = -1
                for scan in range(search_cursor, len(original_data) - 6):
                    if original_data[scan:scan + 6] == target:
                        found = scan
                        search_cursor = scan + 6
                        break

                sm_offsets.append(found)

        for vi in range(n):
            if vi >= len(sm_offsets) or sm_offsets[vi] < 0:
                continue
            byte_off = sm_offsets[vi]
            offset_refs.setdefault(byte_off, []).append(
                (orig_sm.vertices[vi], new_sm.vertices[vi], sm_idx, vi)
            )

    return offset_refs


def _apply_quantized_vertex_patches(
    result: bytearray,
    offset_refs: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]]],
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
    allow_average_conflicts: bool = False,
) -> int:
    """Patch quantized XYZ values at the collected byte offsets."""
    patched_offsets = 0
    for byte_off, refs in offset_refs.items():
        if byte_off + 6 > len(result):
            continue

        vx, vy, vz = _resolve_pam_alias_vertex(
            byte_off, refs, allow_average_conflicts=allow_average_conflicts
        )
        xu = _quantize_u16(vx, bmin[0], bmax[0])
        yu = _quantize_u16(vy, bmin[1], bmax[1])
        zu = _quantize_u16(vz, bmin[2], bmax[2])
        struct.pack_into("<HHH", result, byte_off, xu, yu, zu)
        patched_offsets += 1

    return patched_offsets


def _align_submesh_order_like_original(original_mesh: ParsedMesh, new_mesh: ParsedMesh) -> None:
    """Align submesh order by name when possible without enforcing topology."""
    if len(original_mesh.submeshes) != len(new_mesh.submeshes):
        return

    orig_names = [sm.name for sm in original_mesh.submeshes]
    if [sm.name for sm in new_mesh.submeshes] == orig_names:
        return

    name_to_submesh: dict[str, SubMesh] = {}
    for sm in new_mesh.submeshes:
        if not sm.name or sm.name in name_to_submesh:
            return
        name_to_submesh[sm.name] = sm

    if set(name_to_submesh) == set(orig_names):
        new_mesh.submeshes = [name_to_submesh[name] for name in orig_names]


def _submesh_uvs_match(orig_sm: SubMesh, new_sm: SubMesh, eps: float = 1e-6) -> bool:
    """Check whether two submeshes have equivalent UV payloads."""
    orig_has_uv = len(orig_sm.uvs) == len(orig_sm.vertices)
    new_has_uv = len(new_sm.uvs) == len(new_sm.vertices)
    if orig_has_uv != new_has_uv:
        return False
    if not orig_has_uv:
        return True
    return all(
        abs(ou - nu) <= eps and abs(ov - nv) <= eps
        for (ou, ov), (nu, nv) in zip(orig_sm.uvs, new_sm.uvs)
    )

def _make_vertex_template_record(
    original_data: bytes,
    base_off: int,
    stride: int,
    index: int,
    fallback_count: int,
) -> bytearray:
    """Copy a template vertex record from the original file when possible."""
    if fallback_count > 0:
        src_idx = min(index, fallback_count - 1)
        rec_off = base_off + src_idx * stride
        if rec_off + stride <= len(original_data):
            return bytearray(original_data[rec_off:rec_off + stride])
    return bytearray(stride)


def _pack_static_vertex_record(
    rec: bytearray,
    stride: int,
    vertex: tuple[float, float, float],
    uv: Optional[tuple[float, float]],
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> bytearray:
    """Write XYZ and optional UVs into a static-mesh vertex record."""
    if len(rec) < stride:
        rec.extend(b"\x00" * (stride - len(rec)))

    xu = _quantize_u16(vertex[0], bmin[0], bmax[0])
    yu = _quantize_u16(vertex[1], bmin[1], bmax[1])
    zu = _quantize_u16(vertex[2], bmin[2], bmax[2])
    struct.pack_into("<HHH", rec, 0, xu, yu, zu)

    if stride >= 12 and uv is not None:
        try:
            struct.pack_into("<e", rec, 8, uv[0])
            struct.pack_into("<e", rec, 10, uv[1])
        except (OverflowError, ValueError):
            struct.pack_into("<e", rec, 8, 0.0)
            struct.pack_into("<e", rec, 10, 0.0)

    return rec


def _static_alignment_match_cost(
    orig_vertex: tuple[float, float, float],
    new_vertex: tuple[float, float, float],
    orig_idx: int,
    new_idx: int,
    diag: float,
    max_count: int,
) -> float:
    """Score how likely an imported static vertex maps to an original slot."""
    dist = math.dist(orig_vertex, new_vertex)
    if orig_idx == new_idx:
        dist *= 0.75
    elif abs(orig_idx - new_idx) <= 2:
        dist *= 0.85

    order_penalty = (
        abs(orig_idx - new_idx) / max(max_count, 1)
    ) * max(diag * 0.05, 0.01)
    return dist + order_penalty


def _align_static_vertex_sequences(
    orig_vertices: list[tuple[float, float, float]],
    new_vertices: list[tuple[float, float, float]],
) -> list[int]:
    """Align original/new static vertex order while allowing inserted vertices."""
    orig_count = len(orig_vertices)
    new_count = len(new_vertices)
    aligned = [-1] * new_count
    if orig_count == 0 or new_count == 0:
        return aligned

    bbox_min, bbox_max = _compute_bbox(orig_vertices)
    diag = math.dist(bbox_min, bbox_max)
    gap_penalty = max(diag * 0.02, 0.01)
    band = max(128, abs(orig_count - new_count) + 128)
    max_states = (orig_count + 1) * min(new_count + 1, band * 2 + 1)
    if max_states > 3_000_000:
        raise ValueError(
            f"Static vertex alignment too large ({orig_count}x{new_count}, band={band})"
        )

    prev_row = {j: j * gap_penalty for j in range(0, min(new_count, band) + 1)}
    backtrack: dict[tuple[int, int], str] = {}
    for j in range(1, min(new_count, band) + 1):
        backtrack[(0, j)] = "left"

    max_count = max(orig_count, new_count)
    for i in range(1, orig_count + 1):
        j_start = max(0, i - band)
        j_end = min(new_count, i + band)
        curr_row: dict[int, float] = {}
        if j_start == 0:
            curr_row[0] = i * gap_penalty
            backtrack[(i, 0)] = "up"

        for j in range(max(1, j_start), j_end + 1):
            best_cost = float("inf")
            best_move = ""

            diag_prev = prev_row.get(j - 1)
            if diag_prev is not None:
                cost = diag_prev + _static_alignment_match_cost(
                    orig_vertices[i - 1],
                    new_vertices[j - 1],
                    i - 1,
                    j - 1,
                    diag,
                    max_count,
                )
                if cost < best_cost:
                    best_cost = cost
                    best_move = "diag"

            up_prev = prev_row.get(j)
            if up_prev is not None:
                cost = up_prev + gap_penalty
                if cost < best_cost:
                    best_cost = cost
                    best_move = "up"

            left_prev = curr_row.get(j - 1)
            if left_prev is not None:
                cost = left_prev + gap_penalty
                if cost < best_cost:
                    best_cost = cost
                    best_move = "left"

            if best_move:
                curr_row[j] = best_cost
                backtrack[(i, j)] = best_move

        prev_row = curr_row

    if new_count not in prev_row:
        raise ValueError("Static vertex alignment band did not reach the final state")

    i = orig_count
    j = new_count
    while i > 0 or j > 0:
        move = backtrack.get((i, j))
        if move == "diag":
            aligned[j - 1] = i - 1
            i -= 1
            j -= 1
        elif move == "left":
            j -= 1
        elif move == "up":
            i -= 1
        else:
            # Recover gracefully if a rare boundary state is missing.
            if j > 0 and i > 0:
                aligned[j - 1] = i - 1
                i -= 1
                j -= 1
            elif j > 0:
                j -= 1
            else:
                i -= 1

    return aligned


def _choose_static_donor_indices(orig_sm: SubMesh, new_sm: SubMesh) -> list[int]:
    """Choose donor records for a topology-changing static mesh rebuild."""
    orig_vertices = list(orig_sm.vertices)
    new_vertices = list(new_sm.vertices)
    if not new_vertices:
        return []
    if not orig_vertices:
        return [0] * len(new_vertices)

    try:
        donor_indices = _align_static_vertex_sequences(orig_vertices, new_vertices)
    except Exception as exc:
        logger.debug(
            "Static donor alignment fallback for %s: %s",
            getattr(new_sm, "name", "") or getattr(orig_sm, "name", "") or "<submesh>",
            exc,
        )
        donor_indices = [-1] * len(new_vertices)

    rounded_map: dict[tuple[int, int, int], list[int]] = {}
    for orig_idx, vertex in enumerate(orig_vertices):
        key = (
            round(vertex[0] * 100000),
            round(vertex[1] * 100000),
            round(vertex[2] * 100000),
        )
        rounded_map.setdefault(key, []).append(orig_idx)

    cell_size, grid = _build_spatial_hash(orig_vertices)
    for new_idx, vertex in enumerate(new_vertices):
        if 0 <= donor_indices[new_idx] < len(orig_vertices):
            continue

        key = (
            round(vertex[0] * 100000),
            round(vertex[1] * 100000),
            round(vertex[2] * 100000),
        )
        exact_hits = rounded_map.get(key)
        if exact_hits:
            donor_indices[new_idx] = min(
                exact_hits,
                key=lambda orig_idx: abs(orig_idx - new_idx),
            )
            continue

        donor_indices[new_idx] = _nearest_point_index(vertex, orig_vertices, cell_size, grid)

    return donor_indices


def _combine_static_submeshes(
    submeshes: list[SubMesh],
    *,
    template: Optional[SubMesh] = None,
) -> SubMesh:
    """Flatten multiple imported static OBJ objects into one submesh."""
    combined = SubMesh(
        name=(template.name if template is not None else "") or (submeshes[0].name if submeshes else ""),
        material=(template.material if template is not None else "") or (
            next((sm.material for sm in submeshes if sm.material), "")
        ),
        texture=(template.texture if template is not None else "") or (
            next((sm.texture for sm in submeshes if sm.texture), "")
        ),
    )
    wants_uvs = any(len(sm.uvs) == len(sm.vertices) for sm in submeshes)
    wants_normals = any(len(sm.normals) == len(sm.vertices) for sm in submeshes)

    for sm in submeshes:
        base_index = len(combined.vertices)
        combined.vertices.extend(copy.deepcopy(sm.vertices))

        if wants_uvs:
            if len(sm.uvs) == len(sm.vertices):
                combined.uvs.extend(copy.deepcopy(sm.uvs))
            else:
                combined.uvs.extend([(0.0, 0.0)] * len(sm.vertices))

        if wants_normals:
            if len(sm.normals) == len(sm.vertices):
                combined.normals.extend(copy.deepcopy(sm.normals))
            else:
                combined.normals.extend([(0.0, 1.0, 0.0)] * len(sm.vertices))

        for face in sm.faces:
            if len(face) == 3:
                combined.faces.append(
                    (face[0] + base_index, face[1] + base_index, face[2] + base_index)
                )

    combined.vertex_count = len(combined.vertices)
    combined.face_count = len(combined.faces)
    return combined


def _static_submesh_match_score(imported_sm: SubMesh, original_sm: SubMesh) -> float:
    """Score how likely an imported static OBJ object maps back to an original slot."""
    imp_center = tuple((mn + mx) * 0.5 for mn, mx in zip(*_compute_bbox(imported_sm.vertices)))
    orig_center = tuple((mn + mx) * 0.5 for mn, mx in zip(*_compute_bbox(original_sm.vertices)))
    center_dist = math.dist(imp_center, orig_center)

    vert_ratio = abs(math.log((len(imported_sm.vertices) + 1) / (len(original_sm.vertices) + 1)))
    face_ratio = abs(math.log((len(imported_sm.faces) + 1) / (len(original_sm.faces) + 1)))
    return center_dist + vert_ratio * 0.75 + face_ratio * 0.75


def _merge_partial_static_import(
    original_mesh: ParsedMesh,
    imported_mesh: ParsedMesh,
) -> ParsedMesh:
    """Map a flexible OBJ static import back onto the original PAM submesh layout."""
    if not imported_mesh.submeshes:
        raise ValueError("OBJ import did not contain any submesh data.")

    if len(imported_mesh.submeshes) == len(original_mesh.submeshes):
        return imported_mesh

    if len(original_mesh.submeshes) == 1:
        merged = copy.deepcopy(imported_mesh)
        merged.submeshes = [
            _combine_static_submeshes(
                [copy.deepcopy(sm) for sm in imported_mesh.submeshes],
                template=copy.deepcopy(original_mesh.submeshes[0]),
            )
        ]
        merged.total_vertices = sum(len(sm.vertices) for sm in merged.submeshes)
        merged.total_faces = sum(len(sm.faces) for sm in merged.submeshes)
        merged.has_uvs = any(sm.uvs for sm in merged.submeshes)
        logger.info(
            "Merged %d imported static OBJ object(s) into the single original submesh for %s.",
            len(imported_mesh.submeshes),
            imported_mesh.path or original_mesh.path,
        )
        return merged

    original_names = [sm.name for sm in original_mesh.submeshes]
    imported_by_name: dict[str, SubMesh] = {}
    unknown_named: list[SubMesh] = []
    unnamed: list[SubMesh] = []

    for sm in imported_mesh.submeshes:
        cloned = copy.deepcopy(sm)
        if cloned.name:
            if cloned.name in original_names:
                existing = imported_by_name.get(cloned.name)
                if existing is None:
                    imported_by_name[cloned.name] = cloned
                else:
                    imported_by_name[cloned.name] = _combine_static_submeshes(
                        [existing, cloned],
                        template=next(
                            (copy.deepcopy(orig_sm) for orig_sm in original_mesh.submeshes if orig_sm.name == cloned.name),
                            None,
                        ),
                    )
            else:
                unknown_named.append(cloned)
        else:
            unnamed.append(cloned)

    heuristic_by_name: dict[str, SubMesh] = {}
    unmatched_originals = [
        copy.deepcopy(sm)
        for sm in original_mesh.submeshes
        if sm.name not in imported_by_name
    ]
    for imported_unknown in sorted(unknown_named, key=lambda sm: len(sm.vertices), reverse=True):
        if not unmatched_originals:
            raise ValueError(
                "Static mesh import contains more renamed OBJ objects than the original mesh can match."
            )
        best_original = min(
            unmatched_originals,
            key=lambda original_sm: _static_submesh_match_score(imported_unknown, original_sm),
        )
        imported_unknown.name = best_original.name
        if not imported_unknown.material:
            imported_unknown.material = best_original.material
        if not imported_unknown.texture:
            imported_unknown.texture = best_original.texture
        heuristic_by_name[best_original.name] = imported_unknown
        unmatched_originals = [sm for sm in unmatched_originals if sm.name != best_original.name]

    merged_submeshes: list[SubMesh] = []
    unnamed_iter = iter(unnamed)
    used_named = 0
    for original_sm in original_mesh.submeshes:
        replacement = imported_by_name.get(original_sm.name)
        if replacement is None:
            replacement = heuristic_by_name.get(original_sm.name)
        if replacement is not None:
            merged_submeshes.append(replacement)
            used_named += 1
            continue

        try:
            fallback = next(unnamed_iter)
        except StopIteration:
            merged_submeshes.append(copy.deepcopy(original_sm))
        else:
            fallback.name = fallback.name or original_sm.name
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
            "Static mesh import contains extra unnamed OBJ objects that could not be matched to the original mesh."
        )

    if used_named == 0 and len(imported_mesh.submeshes) != len(original_mesh.submeshes):
        raise ValueError(
            "Static mesh import changed the OBJ object count without preserving recognizable original object names. "
            "Keep the exported object names when editing multi-submesh PAM meshes."
        )

    merged = copy.deepcopy(imported_mesh)
    merged.submeshes = merged_submeshes
    merged.total_vertices = sum(len(sm.vertices) for sm in merged_submeshes)
    merged.total_faces = sum(len(sm.faces) for sm in merged_submeshes)
    merged.has_uvs = any(sm.uvs for sm in merged_submeshes)
    logger.info(
        "Mapped %d imported static OBJ object(s) onto %d original submesh slot(s) for %s.",
        len(imported_mesh.submeshes),
        len(original_mesh.submeshes),
        imported_mesh.path or original_mesh.path,
    )
    return merged


def _replace_all_in_region(
    data: bytearray,
    start: int,
    end: int,
    old: bytes,
    new: bytes,
) -> int:
    """Replace all occurrences of a fixed-size pattern inside a bounded region."""
    if not old or old == new or start >= end:
        return 0

    hits = 0
    cursor = start
    while True:
        pos = data.find(old, cursor, end)
        if pos < 0:
            break
        data[pos:pos + len(old)] = new
        hits += 1
        cursor = pos + len(new)
    return hits

def _spatial_cell_key(point: tuple[float, float, float], cell_size: float) -> tuple[int, int, int]:
    return (
        int(math.floor(point[0] / cell_size)),
        int(math.floor(point[1] / cell_size)),
        int(math.floor(point[2] / cell_size)),
    )


def _build_spatial_hash(points: list[tuple[float, float, float]]) -> tuple[float, dict[tuple[int, int, int], list[int]]]:
    """Create a simple spatial hash for nearest-vertex transfer."""
    if not points:
        return 1.0, {}

    xs, ys, zs = zip(*points)
    extent = max(
        max(xs) - min(xs),
        max(ys) - min(ys),
        max(zs) - min(zs),
        1e-5,
    )
    cell_size = max(extent / max(round(len(points) ** (1.0 / 3.0)), 1), 1e-5)

    grid: dict[tuple[int, int, int], list[int]] = {}
    for idx, point in enumerate(points):
        grid.setdefault(_spatial_cell_key(point, cell_size), []).append(idx)
    return cell_size, grid


def _nearest_point_index(
    point: tuple[float, float, float],
    source_points: list[tuple[float, float, float]],
    cell_size: float,
    grid: dict[tuple[int, int, int], list[int]],
) -> int:
    """Find the nearest source point using the spatial hash."""
    if not source_points:
        raise ValueError("Cannot transfer displacement from an empty source mesh.")

    base = _spatial_cell_key(point, cell_size)
    best_idx = -1
    best_d2 = float("inf")

    for radius in range(0, 8):
        found_any = False
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    cell = (base[0] + dx, base[1] + dy, base[2] + dz)
                    for idx in grid.get(cell, ()):
                        found_any = True
                        sx, sy, sz = source_points[idx]
                        d2 = ((sx - point[0]) ** 2 +
                              (sy - point[1]) ** 2 +
                              (sz - point[2]) ** 2)
                        if d2 < best_d2:
                            best_d2 = d2
                            best_idx = idx
        if found_any and best_idx >= 0:
            return best_idx

    for idx, src in enumerate(source_points):
        d2 = ((src[0] - point[0]) ** 2 +
              (src[1] - point[1]) ** 2 +
              (src[2] - point[2]) ** 2)
        if d2 < best_d2:
            best_d2 = d2
            best_idx = idx

    return best_idx


def _nearby_point_indices(
    point: tuple[float, float, float],
    source_points: list[tuple[float, float, float]],
    cell_size: float,
    grid: dict[tuple[int, int, int], list[int]],
    radius: float,
) -> list[int]:
    """Return source points within the given radius."""
    if not source_points:
        return []

    base = _spatial_cell_key(point, cell_size)
    cell_radius = max(1, int(math.ceil(radius / max(cell_size, 1e-6))))
    radius_sq = radius * radius
    candidates: list[int] = []

    for dx in range(-cell_radius, cell_radius + 1):
        for dy in range(-cell_radius, cell_radius + 1):
            for dz in range(-cell_radius, cell_radius + 1):
                cell = (base[0] + dx, base[1] + dy, base[2] + dz)
                for idx in grid.get(cell, ()):
                    sx, sy, sz = source_points[idx]
                    d2 = ((sx - point[0]) ** 2 +
                          (sy - point[1]) ** 2 +
                          (sz - point[2]) ** 2)
                    if d2 <= radius_sq:
                        candidates.append(idx)

    return candidates


def _percentile(values: list[float], pct: float) -> float:
    """Return a simple percentile from a non-empty list."""
    if not values:
        return 0.0
    clamped = max(0.0, min(1.0, pct))
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * clamped))
    return ordered[idx]
