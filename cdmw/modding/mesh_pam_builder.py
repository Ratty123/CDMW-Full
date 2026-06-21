"""PAM rebuild helpers for mesh round-trip imports."""

from __future__ import annotations

import copy
import math
import struct

from .logging import get_logger
from .mesh_builder_common import (
    _align_submesh_order_like_original,
    _apply_quantized_vertex_patches,
    _choose_static_donor_indices,
    _collect_vertex_offset_refs,
    _compute_bbox,
    _expand_bbox_to_vertices,
    _make_vertex_template_record,
    _merge_partial_static_import,
    _pack_static_vertex_record,
    _replace_all_in_region,
    _submesh_uvs_match,
)
from .mesh_parser import ParsedMesh, SubMesh, STRIDE_CANDIDATES, _find_local_stride, parse_pam

logger = get_logger("core.mesh_importer")

def _pam_needs_full_rebuild(original_mesh: ParsedMesh, new_mesh: ParsedMesh) -> bool:
    """Return True when edits go beyond in-place XYZ patching."""
    if len(original_mesh.submeshes) != len(new_mesh.submeshes):
        return True

    for orig_sm, new_sm in zip(original_mesh.submeshes, new_mesh.submeshes):
        if len(orig_sm.vertices) != len(new_sm.vertices):
            return True
        if len(orig_sm.faces) != len(new_sm.faces):
            return True
        if orig_sm.faces != new_sm.faces:
            return True
        if not _submesh_uvs_match(orig_sm, new_sm):
            return True

    return False


def _inspect_pam_layout(original_data: bytes) -> dict:
    """Inspect whether the PAM uses a standard layout we can serialize."""
    hdr_geom_off = 0x3C
    hdr_mesh_count = 0x10
    submesh_table = 0x410
    submesh_stride = 0x218
    pam_idx_off = 0x19840

    if not original_data or original_data[:4] != b"PAR ":
        return {"kind": "unsupported", "reason": "missing PAM header"}

    geom_off = struct.unpack_from("<I", original_data, hdr_geom_off)[0]
    mesh_count = struct.unpack_from("<I", original_data, hdr_mesh_count)[0]
    if mesh_count <= 0:
        return {"kind": "unsupported", "reason": "mesh table is empty"}

    entries = []
    for i in range(mesh_count):
        desc_off = submesh_table + i * submesh_stride
        if desc_off + submesh_stride > len(original_data):
            return {"kind": "unsupported", "reason": "submesh table is truncated"}
        nv = struct.unpack_from("<I", original_data, desc_off)[0]
        ni = struct.unpack_from("<I", original_data, desc_off + 4)[0]
        ve = struct.unpack_from("<I", original_data, desc_off + 8)[0]
        ie = struct.unpack_from("<I", original_data, desc_off + 12)[0]
        entries.append({
            "desc_off": desc_off,
            "nv": nv,
            "ni": ni,
            "ve": ve,
            "ie": ie,
        })

    is_combined = mesh_count > 1
    if is_combined:
        ve_acc = ie_acc = 0
        for entry in entries:
            if entry["ve"] != ve_acc or entry["ie"] != ie_acc:
                is_combined = False
                break
            ve_acc += entry["nv"]
            ie_acc += entry["ni"]

    total_nv = sum(entry["nv"] for entry in entries)
    total_ni = sum(entry["ni"] for entry in entries)

    def detect_forward_scan_layout() -> Optional[dict]:
        if total_nv <= 0 or total_ni <= 0:
            return None

        search_limit = min(len(original_data) - 100, geom_off + min(len(original_data) // 2, 2_000_000))
        step = 2 if (search_limit - geom_off) < 500_000 else 4
        scan_candidates = [6, 8, 10, 12, 14, 16, 20, 24, 28, 32]

        for scan_start in range(geom_off, search_limit, step):
            if scan_start + 60 > len(original_data):
                break
            vals = [struct.unpack_from("<H", original_data, scan_start + j * 2)[0] for j in range(30)]
            if max(vals) - min(vals) < 5000:
                continue

            for stride in scan_candidates:
                idx_base = scan_start + total_nv * stride
                if idx_base + total_ni * 2 > len(original_data):
                    continue

                valid = True
                for j in range(min(50, total_ni)):
                    val = struct.unpack_from("<H", original_data, idx_base + j * 2)[0]
                    if val >= total_nv:
                        valid = False
                        break
                if not valid:
                    continue

                valid = all(
                    struct.unpack_from("<H", original_data, idx_base + j * 2)[0] < total_nv
                    for j in range(min(total_ni, 500))
                )
                if not valid:
                    continue

                return {
                    "kind": "scan_combined",
                    "geom_off": geom_off,
                    "scan_start": scan_start,
                    "entries": entries,
                    "stride": stride,
                    "old_geom_end": idx_base + total_ni * 2,
                }
        return None

    def detect_backward_scan_layout() -> Optional[dict]:
        if total_nv <= 0 or total_ni <= 0:
            return None

        scan_candidates = [6, 8, 10, 12, 14, 16, 20, 24, 28, 32]
        for scan_end_off in range(len(original_data) - 2, geom_off + total_nv * 6, -2):
            idx_base = scan_end_off - total_ni * 2 + 2
            if idx_base < geom_off:
                break

            first_val = struct.unpack_from("<H", original_data, idx_base)[0]
            if first_val >= total_nv:
                continue

            valid = True
            for j in range(min(30, total_ni)):
                val = struct.unpack_from("<H", original_data, idx_base + j * 2)[0]
                if val >= total_nv:
                    valid = False
                    break
            if not valid:
                continue

            valid = all(
                struct.unpack_from("<H", original_data, idx_base + j * 2)[0] < total_nv
                for j in range(min(total_ni, 300))
            )
            if not valid:
                continue

            valid = all(
                struct.unpack_from("<H", original_data, idx_base + j * 2)[0] < total_nv
                for j in range(total_ni)
            )
            if not valid:
                continue

            vert_region = idx_base - geom_off
            stride = None
            for try_stride in scan_candidates:
                expected_end = geom_off + total_nv * try_stride
                if expected_end <= idx_base and (idx_base - expected_end) < 16384:
                    stride = try_stride
                    break
            if stride is None:
                stride = max(6, vert_region // max(total_nv, 1))

            vertex_end = geom_off + total_nv * stride
            if vertex_end > idx_base or vertex_end > len(original_data):
                continue

            return {
                "kind": "backward_scan_combined",
                "geom_off": geom_off,
                "entries": entries,
                "stride": stride,
                "idx_base": idx_base,
                "vertex_end": vertex_end,
                "old_geom_end": idx_base + total_ni * 2,
            }
        return None

    if is_combined:
        if total_nv <= 0:
            return {"kind": "unsupported", "reason": "combined PAM has no vertices"}
        avail = len(original_data) - geom_off
        target_stride = (avail - total_ni * 2) / total_nv
        stride = min(STRIDE_CANDIDATES, key=lambda s: abs(s - target_stride))
        idx_base = geom_off + total_nv * stride
        if idx_base + total_ni * 2 <= len(original_data):
            return {
                "kind": "combined",
                "geom_off": geom_off,
                "entries": entries,
                "stride": stride,
                "old_geom_end": idx_base + total_ni * 2,
            }

        scan_layout = detect_forward_scan_layout()
        if scan_layout is not None:
            return scan_layout

        backward_layout = detect_backward_scan_layout()
        if backward_layout is not None:
            return backward_layout

        return {"kind": "unsupported", "reason": "combined PAM geometry block is truncated"}

    idx_avail = max(0, (len(original_data) - pam_idx_off) // 2)
    local_entries = []
    uses_global = False
    old_geom_end = geom_off
    for entry in entries:
        stride, idx_off = _find_local_stride(
            original_data, geom_off, entry["ve"], entry["nv"], entry["ni"]
        )
        if stride is not None:
            entry = dict(entry)
            entry["stride"] = stride
            entry["idx_off"] = idx_off
            local_entries.append(entry)
            old_geom_end = max(old_geom_end, idx_off + entry["ni"] * 2)
            continue

        if entry["ie"] + entry["ni"] <= idx_avail:
            uses_global = True
        else:
            scan_layout = detect_forward_scan_layout()
            if scan_layout is not None:
                return scan_layout

            backward_layout = detect_backward_scan_layout()
            if backward_layout is not None:
                return backward_layout

            return {"kind": "unsupported", "reason": "PAM uses scan-fallback geometry layout"}

    if uses_global:
        backward_layout = detect_backward_scan_layout()
        if backward_layout is not None:
            return backward_layout

        return {"kind": "unsupported", "reason": "global-buffer PAM rebuild is not implemented yet"}

    return {
        "kind": "local",
        "geom_off": geom_off,
        "entries": local_entries,
        "old_geom_end": old_geom_end,
    }




def _sync_pam_header_mirrors(
    result: bytearray,
    original_mesh: ParsedMesh,
    new_mesh: ParsedMesh,
    geom_off: int,
) -> int:
    """Update mirrored PAM metadata between the main table and geometry block."""
    def _bbox_close(candidate: tuple[float, float, float, float, float, float], reference: tuple[float, float, float, float, float, float], tol: float = 1e-3) -> bool:
        return all(math.isfinite(value) and abs(value - target) <= tol for value, target in zip(candidate, reference))

    mesh_count = min(len(original_mesh.submeshes), len(new_mesh.submeshes))
    region_start = 0x410 + mesh_count * 0x218
    region_end = min(max(geom_off, region_start), len(result))
    if region_start >= region_end:
        return 0

    patched = 0

    for orig_sm, new_sm in zip(original_mesh.submeshes, new_mesh.submeshes):
        orig_nv = len(orig_sm.vertices)
        orig_ni = len(orig_sm.faces) * 3
        new_nv = len(new_sm.vertices)
        new_ni = len(new_sm.faces) * 3

        if orig_sm.vertices:
            oxs, oys, ozs = zip(*orig_sm.vertices)
            old_bbox = (
                min(oxs), min(oys), min(ozs),
                max(oxs), max(oys), max(ozs),
            )
        else:
            old_bbox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        if new_sm.vertices:
            nxs, nys, nzs = zip(*new_sm.vertices)
            new_bbox = (
                min(nxs), min(nys), min(nzs),
                max(nxs), max(nys), max(nzs),
            )
        else:
            new_bbox = old_bbox

        old_bbox_bytes = struct.pack("<6f", *old_bbox)
        new_bbox_bytes = struct.pack("<6f", *new_bbox)

        patched += _replace_all_in_region(
            result,
            region_start,
            region_end,
            struct.pack("<I", orig_ni) + old_bbox_bytes,
            struct.pack("<I", new_ni) + new_bbox_bytes,
        )
        patched += _replace_all_in_region(
            result,
            region_start,
            region_end,
            old_bbox_bytes,
            new_bbox_bytes,
        )

        for off in range(region_start, max(region_start, region_end - 28) + 1, 4):
            count_and_bbox = result[off:off + 28]
            if len(count_and_bbox) < 28:
                break
            count = struct.unpack_from("<I", count_and_bbox, 0)[0]
            bbox = struct.unpack_from("<6f", count_and_bbox, 4)
            if count == orig_ni and _bbox_close(bbox, old_bbox):
                struct.pack_into("<I", result, off, new_ni)
                struct.pack_into("<6f", result, off + 4, *new_bbox)
                patched += 1

        for off in range(region_start, max(region_start, region_end - 24) + 1, 4):
            bbox_bytes = result[off:off + 24]
            if len(bbox_bytes) < 24:
                break
            bbox = struct.unpack_from("<6f", bbox_bytes, 0)
            if _bbox_close(bbox, old_bbox):
                struct.pack_into("<6f", result, off, *new_bbox)
                patched += 1

        old_pair = struct.pack("<II", orig_nv, orig_ni)
        new_pair = struct.pack("<II", new_nv, new_ni)
        if old_pair == new_pair:
            continue

        anchor_names = []
        if orig_sm.texture:
            anchor_names.append(orig_sm.texture.encode("ascii", "ignore"))
        if orig_sm.material:
            anchor_names.append(orig_sm.material.encode("ascii", "ignore"))

        for anchor in anchor_names:
            if not anchor:
                continue
            cursor = region_start
            while True:
                pos = result.find(anchor, cursor, region_end)
                if pos < 0:
                    break
                pair_off = pos - 8
                if pair_off >= region_start and bytes(result[pair_off:pair_off + 8]) == old_pair:
                    result[pair_off:pair_off + 8] = new_pair
                    patched += 1
                cursor = pos + len(anchor)

    return patched


def _sync_pam_geom_size_header(
    result: bytearray,
    original_data: bytes,
    geom_off: int,
    old_geom_end: int,
    new_geom_end: int,
) -> bool:
    """Refresh PAM header geometry-size field when it mirrors the geometry block length."""
    header_geom_size_off = 0x40
    if (
        len(result) < header_geom_size_off + 4
        or len(original_data) < header_geom_size_off + 4
        or geom_off <= 0
        or old_geom_end < geom_off
        or new_geom_end < geom_off
    ):
        return False

    original_geom_len = old_geom_end - geom_off
    original_header_geom_len = struct.unpack_from("<I", original_data, header_geom_size_off)[0]
    if original_header_geom_len != original_geom_len:
        return False

    struct.pack_into("<I", result, header_geom_size_off, new_geom_end - geom_off)
    return True


def _serialize_pam_combined_layout(
    mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    original_data: bytes,
    layout: dict,
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> bytes:
    """Rebuild a standard combined-buffer PAM from scratch."""
    hdr_bbox_min = 0x14
    hdr_bbox_max = 0x20

    geom_off = layout["geom_off"]
    stride = layout["stride"]
    entries = layout["entries"]
    old_geom_end = layout["old_geom_end"]
    result = bytearray(original_data[:geom_off])

    struct.pack_into("<fff", result, hdr_bbox_min, *bmin)
    struct.pack_into("<fff", result, hdr_bbox_max, *bmax)

    geom_data = bytearray()
    index_data = bytearray()
    vert_cursor = 0
    idx_cursor = 0

    for sm_idx, (sm, orig_sm, entry) in enumerate(zip(mesh.submeshes, original_mesh.submeshes, entries)):
        struct.pack_into("<I", result, entry["desc_off"], len(sm.vertices))
        struct.pack_into("<I", result, entry["desc_off"] + 4, len(sm.faces) * 3)
        struct.pack_into("<I", result, entry["desc_off"] + 8, vert_cursor)
        struct.pack_into("<I", result, entry["desc_off"] + 12, idx_cursor)

        orig_vert_base = geom_off + entry["ve"] * stride
        orig_nv = entry["nv"]
        uv_data = sm.uvs if len(sm.uvs) == len(sm.vertices) else []
        donor_indices = _choose_static_donor_indices(orig_sm, sm)

        for vi, vertex in enumerate(sm.vertices):
            donor_idx = donor_indices[vi] if vi < len(donor_indices) else vi
            rec = _make_vertex_template_record(original_data, orig_vert_base, stride, donor_idx, orig_nv)
            uv = uv_data[vi] if uv_data else None
            geom_data.extend(_pack_static_vertex_record(rec, stride, vertex, uv, bmin, bmax))

        for a, b, c in sm.faces:
            index_data.extend(struct.pack("<HHH", a + vert_cursor, b + vert_cursor, c + vert_cursor))

        vert_cursor += len(sm.vertices)
        idx_cursor += len(sm.faces) * 3

    result.extend(geom_data)
    result.extend(index_data)
    new_geom_end = geom_off + len(geom_data) + len(index_data)
    _sync_pam_geom_size_header(result, original_data, geom_off, old_geom_end, new_geom_end)
    result.extend(original_data[old_geom_end:])
    mirror_patches = _sync_pam_header_mirrors(result, original_mesh, mesh, geom_off)
    logger.info(
        "Built PAM %s with full combined rebuild: %d submeshes, %d verts, %d faces (%d mirrored header patches)",
        mesh.path, len(mesh.submeshes), sum(len(sm.vertices) for sm in mesh.submeshes),
        sum(len(sm.faces) for sm in mesh.submeshes), mirror_patches,
    )
    return bytes(result)


def _serialize_pam_scan_combined_layout(
    mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    original_data: bytes,
    layout: dict,
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> bytes:
    """Rebuild a scan-fallback PAM whose real geometry starts after geom_off."""
    hdr_bbox_min = 0x14
    hdr_bbox_max = 0x20

    scan_start = layout["scan_start"]
    stride = layout["stride"]
    entries = layout["entries"]
    old_geom_end = layout["old_geom_end"]
    result = bytearray(original_data[:scan_start])

    struct.pack_into("<fff", result, hdr_bbox_min, *bmin)
    struct.pack_into("<fff", result, hdr_bbox_max, *bmax)

    geom_data = bytearray()
    index_data = bytearray()
    vert_cursor = 0
    idx_cursor = 0

    for sm, orig_sm, entry in zip(mesh.submeshes, original_mesh.submeshes, entries):
        struct.pack_into("<I", result, entry["desc_off"], len(sm.vertices))
        struct.pack_into("<I", result, entry["desc_off"] + 4, len(sm.faces) * 3)
        struct.pack_into("<I", result, entry["desc_off"] + 8, vert_cursor)
        struct.pack_into("<I", result, entry["desc_off"] + 12, idx_cursor)

        orig_vert_base = scan_start + entry["ve"] * stride
        orig_nv = entry["nv"]
        uv_data = sm.uvs if len(sm.uvs) == len(sm.vertices) else []
        donor_indices = _choose_static_donor_indices(orig_sm, sm)

        for vi, vertex in enumerate(sm.vertices):
            donor_idx = donor_indices[vi] if vi < len(donor_indices) else vi
            rec = _make_vertex_template_record(original_data, orig_vert_base, stride, donor_idx, orig_nv)
            uv = uv_data[vi] if uv_data else None
            geom_data.extend(_pack_static_vertex_record(rec, stride, vertex, uv, bmin, bmax))

        for a, b, c in sm.faces:
            index_data.extend(struct.pack("<HHH", a + vert_cursor, b + vert_cursor, c + vert_cursor))

        vert_cursor += len(sm.vertices)
        idx_cursor += len(sm.faces) * 3

    result.extend(geom_data)
    result.extend(index_data)
    new_geom_end = layout["geom_off"] + len(geom_data) + len(index_data)
    _sync_pam_geom_size_header(result, original_data, layout["geom_off"], old_geom_end, new_geom_end)
    result.extend(original_data[old_geom_end:])
    mirror_patches = _sync_pam_header_mirrors(result, original_mesh, mesh, layout["geom_off"])
    logger.info(
        "Built PAM %s with full scan-combined rebuild: %d submeshes, %d verts, %d faces (%d mirrored header patches)",
        mesh.path, len(mesh.submeshes), sum(len(sm.vertices) for sm in mesh.submeshes),
        sum(len(sm.faces) for sm in mesh.submeshes), mirror_patches,
    )
    return bytes(result)


def _serialize_pam_backward_scan_combined_layout(
    mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    original_data: bytes,
    layout: dict,
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> bytes:
    """Rebuild a backward-scan PAM with padding between vertices and indices."""
    hdr_bbox_min = 0x14
    hdr_bbox_max = 0x20

    geom_off = layout["geom_off"]
    stride = layout["stride"]
    idx_base = layout["idx_base"]
    vertex_end = layout["vertex_end"]
    entries = layout["entries"]
    old_geom_end = layout["old_geom_end"]
    result = bytearray(original_data[:geom_off])

    struct.pack_into("<fff", result, hdr_bbox_min, *bmin)
    struct.pack_into("<fff", result, hdr_bbox_max, *bmax)

    geom_data = bytearray()
    index_data = bytearray()
    vert_cursor = 0
    idx_cursor = 0

    for sm, orig_sm, entry in zip(mesh.submeshes, original_mesh.submeshes, entries):
        struct.pack_into("<I", result, entry["desc_off"], len(sm.vertices))
        struct.pack_into("<I", result, entry["desc_off"] + 4, len(sm.faces) * 3)
        struct.pack_into("<I", result, entry["desc_off"] + 8, vert_cursor)
        struct.pack_into("<I", result, entry["desc_off"] + 12, idx_cursor)

        orig_vert_base = geom_off + entry["ve"] * stride
        orig_nv = entry["nv"]
        uv_data = sm.uvs if len(sm.uvs) == len(sm.vertices) else []
        donor_indices = _choose_static_donor_indices(orig_sm, sm)

        for vi, vertex in enumerate(sm.vertices):
            donor_idx = donor_indices[vi] if vi < len(donor_indices) else vi
            rec = _make_vertex_template_record(original_data, orig_vert_base, stride, donor_idx, orig_nv)
            uv = uv_data[vi] if uv_data else None
            geom_data.extend(_pack_static_vertex_record(rec, stride, vertex, uv, bmin, bmax))

        for a, b, c in sm.faces:
            index_data.extend(struct.pack("<HHH", a + vert_cursor, b + vert_cursor, c + vert_cursor))

        vert_cursor += len(sm.vertices)
        idx_cursor += len(sm.faces) * 3

    result.extend(geom_data)
    result.extend(original_data[vertex_end:idx_base])
    result.extend(index_data)
    new_geom_end = geom_off + len(geom_data) + (idx_base - vertex_end) + len(index_data)
    _sync_pam_geom_size_header(result, original_data, geom_off, old_geom_end, new_geom_end)
    result.extend(original_data[old_geom_end:])
    mirror_patches = _sync_pam_header_mirrors(result, original_mesh, mesh, geom_off)
    logger.info(
        "Built PAM %s with full backward-scan rebuild: %d submeshes, %d verts, %d faces (%d mirrored header patches)",
        mesh.path, len(mesh.submeshes), sum(len(sm.vertices) for sm in mesh.submeshes),
        sum(len(sm.faces) for sm in mesh.submeshes), mirror_patches,
    )
    return bytes(result)


def _serialize_pam_local_layout(
    mesh: ParsedMesh,
    original_mesh: ParsedMesh,
    original_data: bytes,
    layout: dict,
    bmin: tuple[float, float, float],
    bmax: tuple[float, float, float],
) -> bytes:
    """Rebuild a single-submesh local-layout PAM from scratch."""
    hdr_bbox_min = 0x14
    hdr_bbox_max = 0x20

    geom_off = layout["geom_off"]
    entries = layout["entries"]
    old_geom_end = layout["old_geom_end"]
    result = bytearray(original_data[:geom_off])

    struct.pack_into("<fff", result, hdr_bbox_min, *bmin)
    struct.pack_into("<fff", result, hdr_bbox_max, *bmax)

    geom_data = bytearray()
    current_voff = 0

    for sm, orig_sm, entry in zip(mesh.submeshes, original_mesh.submeshes, entries):
        stride = entry["stride"]
        struct.pack_into("<I", result, entry["desc_off"], len(sm.vertices))
        struct.pack_into("<I", result, entry["desc_off"] + 4, len(sm.faces) * 3)
        struct.pack_into("<I", result, entry["desc_off"] + 8, current_voff)
        struct.pack_into("<I", result, entry["desc_off"] + 12, 0)

        orig_vert_base = geom_off + entry["ve"]
        orig_nv = entry["nv"]
        uv_data = sm.uvs if len(sm.uvs) == len(sm.vertices) else []
        donor_indices = _choose_static_donor_indices(orig_sm, sm)

        for vi, vertex in enumerate(sm.vertices):
            donor_idx = donor_indices[vi] if vi < len(donor_indices) else vi
            rec = _make_vertex_template_record(original_data, orig_vert_base, stride, donor_idx, orig_nv)
            uv = uv_data[vi] if uv_data else None
            geom_data.extend(_pack_static_vertex_record(rec, stride, vertex, uv, bmin, bmax))

        for a, b, c in sm.faces:
            geom_data.extend(struct.pack("<HHH", a, b, c))

        current_voff += len(sm.vertices) * stride + len(sm.faces) * 6

    result.extend(geom_data)
    new_geom_end = geom_off + len(geom_data)
    _sync_pam_geom_size_header(result, original_data, geom_off, old_geom_end, new_geom_end)
    result.extend(original_data[old_geom_end:])
    mirror_patches = _sync_pam_header_mirrors(result, original_mesh, mesh, geom_off)
    logger.info(
        "Built PAM %s with full local rebuild: %d submeshes, %d verts, %d faces (%d mirrored header patches)",
        mesh.path, len(mesh.submeshes), sum(len(sm.vertices) for sm in mesh.submeshes),
        sum(len(sm.faces) for sm in mesh.submeshes), mirror_patches,
    )
    return bytes(result)

def build_pam(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Rebuild a PAM binary from a modified mesh.

    Standard combined/local PAM layouts can be fully reserialized so UV
    edits and same-submesh topology edits survive round-trip. More exotic
    scan-fallback/global layouts still fall back to the older position-only
    patch path.
    """
    if not original_data or original_data[:4] != b"PAR ":
        raise ValueError("Original PAM data required for rebuild")

    HDR_BBOX_MIN = 0x14
    HDR_BBOX_MAX = 0x20
    HDR_GEOM_OFF = 0x3C

    result = bytearray(original_data)

    # Read original bbox — use for quantization, expand only if needed
    orig_bmin = struct.unpack_from("<fff", original_data, HDR_BBOX_MIN)
    orig_bmax = struct.unpack_from("<fff", original_data, HDR_BBOX_MAX)
    original_mesh = parse_pam(original_data, mesh.path)
    working_mesh = _merge_partial_static_import(original_mesh, copy.deepcopy(mesh))
    _align_submesh_order_like_original(original_mesh, working_mesh)

    all_v = [v for s in working_mesh.submeshes for v in s.vertices]
    if all_v:
        bmin, bmax = _compute_bbox(all_v)
    else:
        bmin, bmax = orig_bmin, orig_bmax

    if _pam_needs_full_rebuild(original_mesh, working_mesh):
        if len(original_mesh.submeshes) != len(working_mesh.submeshes):
            raise ValueError(
                "PAM import could not reconcile the OBJ object layout with the original submesh layout. "
                "For multi-submesh PAM files, keep the exported object names when editing in Blender."
            )

        layout = _inspect_pam_layout(original_data)
        if layout["kind"] == "combined":
            return _serialize_pam_combined_layout(
                working_mesh, original_mesh, original_data, layout, bmin, bmax
            )
        if layout["kind"] == "scan_combined":
            return _serialize_pam_scan_combined_layout(
                working_mesh, original_mesh, original_data, layout, bmin, bmax
            )
        if layout["kind"] == "backward_scan_combined":
            return _serialize_pam_backward_scan_combined_layout(
                working_mesh, original_mesh, original_data, layout, bmin, bmax
            )
        if layout["kind"] == "local":
            return _serialize_pam_local_layout(
                working_mesh, original_mesh, original_data, layout, bmin, bmax
            )
        raise ValueError(
            "This PAM layout currently supports position-only patching. "
            f"Topology/UV edits are not supported for it yet ({layout.get('reason', 'unknown layout')})."
        )

    if not original_mesh.submeshes:
        return bytes(result)

    bmin, bmax = _expand_bbox_to_vertices(orig_bmin, orig_bmax, all_v)
    struct.pack_into("<fff", result, HDR_BBOX_MIN, *bmin)
    struct.pack_into("<fff", result, HDR_BBOX_MAX, *bmax)

    geom_off = struct.unpack_from("<I", original_data, HDR_GEOM_OFF)[0]
    offset_refs = _collect_vertex_offset_refs(
        original_data, original_mesh, working_mesh, orig_bmin, orig_bmax, search_start=geom_off
    )
    patched_offsets = _apply_quantized_vertex_patches(result, offset_refs, bmin, bmax)

    total_patched = patched_offsets
    logger.info("Built PAM %s: %d bytes (patched %d verts in-place)",
                mesh.path, len(result), total_patched)
    return bytes(result)
