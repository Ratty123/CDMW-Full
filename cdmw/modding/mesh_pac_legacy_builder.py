"""Legacy PAC section0 rebuild prototype kept for compatibility."""

from __future__ import annotations

import struct

from .logging import get_logger
from .mesh_builder_common import _compute_bbox, _quantize_u16
from .mesh_parser import ParsedMesh, SubMesh, parse_pac

logger = get_logger("core.mesh_importer")

def build_pac(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Rebuild a PAC binary from modified mesh + original file data.

    The original PAC is needed to preserve:
    - Header (magic, version, timestamp)
    - Section 0 structure (flags, bone data, Havok data)
    - Non-geometry metadata

    Only vertex positions, UVs, and face indices are replaced.
    """
    if not original_data or original_data[:4] != b"PAR ":
        raise ValueError("Original PAC data required for rebuild")

    # Parse original to get metadata
    header_size = 80
    s0_start = header_size
    flags = struct.unpack_from("<I", original_data, s0_start)[0]
    n_lods = original_data[s0_start + 4]

    if n_lods == 0 or n_lods > 10:
        raise ValueError(f"Invalid n_lods: {n_lods}")

    # Read original section offsets
    off = s0_start + 5
    orig_lod_offsets = [struct.unpack_from("<I", original_data, off + i * 4)[0] for i in range(n_lods)]
    off += n_lods * 4
    orig_split_offsets = [struct.unpack_from("<I", original_data, off + i * 4)[0] for i in range(n_lods)]
    off += n_lods * 4

    # Compute original section boundaries
    sorted_offsets = sorted(orig_lod_offsets)
    orig_boundaries = [header_size] + sorted_offsets + [len(original_data)]
    orig_sections = [(orig_boundaries[i], orig_boundaries[i + 1])
                     for i in range(len(orig_boundaries) - 1)]

    # Extract original section 0 content (everything from s0 start to first LOD)
    orig_s0 = bytearray(original_data[orig_sections[0][0]:orig_sections[0][1]])

    # Parse original submesh descriptors to get metadata we need to preserve
    orig_mesh = parse_pac(original_data, mesh.path)

    # ── Build LOD data sections ──
    # We only modify LOD0 (highest quality). Lower LODs get the same data
    # (simplified — proper LOD generation would decimate the mesh).

    lod0_verts_buf = bytearray()
    lod0_idx_buf = bytearray()

    for sm_idx, sm in enumerate(mesh.submeshes):
        bmin, bmax = _compute_bbox(sm.vertices)

        # Build vertex records (stride auto-matched to original)
        # Detect original stride from original LOD0 section
        orig_lod0 = orig_sections[-1]
        orig_lod0_size = orig_lod0[1] - orig_lod0[0]
        orig_total_verts = sum(
            s.get("vert_counts", [0])[0] if isinstance(s, dict) else s.vertex_count
            for s in (orig_mesh.submeshes if orig_mesh.submeshes else [{"vert_counts": [0]}])
        )
        orig_total_idx = sum(
            s.get("idx_counts", [0])[0] if isinstance(s, dict) else len(s.faces) * 3
            for s in (orig_mesh.submeshes if orig_mesh.submeshes else [{"idx_counts": [0]}])
        )

        if orig_total_verts > 0:
            stride = (orig_lod0_size - orig_total_idx * 2) // orig_total_verts
        else:
            stride = 40  # default

        stride = max(36, min(64, stride))  # clamp to reasonable range

        for vi in range(len(sm.vertices)):
            vx, vy, vz = sm.vertices[vi]
            xu = _quantize_u16(vx, bmin[0], bmax[0])
            yu = _quantize_u16(vy, bmin[1], bmax[1])
            zu = _quantize_u16(vz, bmin[2], bmax[2])

            rec = bytearray(stride)
            # Position: bytes 0-5
            struct.pack_into("<HHH", rec, 0, xu, yu, zu)
            # UV: bytes 8-11 as float16
            if vi < len(sm.uvs):
                u, v = sm.uvs[vi]
                try:
                    struct.pack_into("<e", rec, 8, u)
                    struct.pack_into("<e", rec, 10, v)
                except (OverflowError, ValueError):
                    pass
            # Constant at bytes 12-15
            struct.pack_into("<I", rec, 12, 0x3C000000)
            # Bone: bytes 28-31 = 0xFF000000 (no bone / default)
            if stride >= 32:
                struct.pack_into("<I", rec, 28, 0x000000FF)
            # Terminator at last 4 bytes
            struct.pack_into("<I", rec, stride - 4, 0xFFFFFFFF)

            lod0_verts_buf.extend(rec)

        # Index buffer: triangle list
        for a, b, c in sm.faces:
            lod0_idx_buf.extend(struct.pack("<HHH", a, b, c))

    # For lower LODs, copy LOD0 data (simplified)
    lod_data = [bytes(lod0_verts_buf) + bytes(lod0_idx_buf)] * n_lods

    # ── Rebuild section 0 ──
    # Update submesh descriptors in section 0 with new bbox and counts
    new_s0 = _rebuild_pac_section0(
        orig_s0, original_data, n_lods, mesh.submeshes, stride,
        flags, orig_lod_offsets, orig_split_offsets
    )

    # ── Assemble final PAC ──
    # Header (80 bytes) + section 0 + LOD sections (lowest to highest)
    # LOD sections are stored in ascending quality order: LOD(n-1), ..., LOD1, LOD0

    # Compute new section positions
    s0_size = len(new_s0)
    lod_sizes = [len(d) for d in lod_data]

    # Sections are ordered: sec0, LOD_lowest, ..., LOD_highest
    # LOD offsets (stored LOD0-first in section 0) are absolute file positions
    sec_positions = [header_size]  # sec0 start
    pos = header_size + s0_size
    for sz in reversed(lod_sizes):  # lowest LOD first in file
        sec_positions.append(pos)
        pos += sz

    # LOD offsets in descending order (LOD0 first)
    new_lod_offsets = list(reversed(sec_positions[1:]))

    # Split offsets: vertex data ends, index data begins
    new_split_offsets = []
    for i, sm_list_data in enumerate(lod_data):
        total_v = sum(len(s.vertices) for s in mesh.submeshes)
        split = sec_positions[n_lods - i] + total_v * stride  # absolute
        new_split_offsets.append(split)

    # Update offsets in section 0
    off = 5  # after flags(4) + n_lods(1)
    for i in range(n_lods):
        struct.pack_into("<I", new_s0, off + i * 4, new_lod_offsets[i])
    off += n_lods * 4
    for i in range(n_lods):
        struct.pack_into("<I", new_s0, off + i * 4, new_split_offsets[i])

    # Build header
    header = bytearray(original_data[:header_size])

    # Update section sizes in header (try u64 format first)
    all_sec_sizes = [s0_size] + list(reversed(lod_sizes))
    # Write as u64 at 0x14 (fits in 5 slots for up to 5 sections)
    for i, sz in enumerate(all_sec_sizes):
        if 0x14 + i * 8 + 8 <= header_size:
            struct.pack_into("<Q", header, 0x14 + i * 8, sz)

    # Assemble
    result = bytearray(header)
    result.extend(new_s0)
    for d in reversed(lod_data):  # lowest LOD first in file
        result.extend(d)

    logger.info("Built PAC %s: %d bytes (%d submeshes, %d verts, %d faces)",
                mesh.path, len(result), len(mesh.submeshes),
                mesh.total_vertices, mesh.total_faces)
    return bytes(result)


def _rebuild_pac_section0(orig_s0: bytearray, original_data: bytes,
                          n_lods: int, submeshes: list[SubMesh],
                          stride: int, flags: int,
                          orig_lod_offsets: list, orig_split_offsets: list) -> bytearray:
    """Rebuild section 0 with updated submesh bbox and counts.

    Preserves all original data (names, materials, bones, Havok data),
    only updates the bounding box floats and vertex/index counts.
    """
    s0 = bytearray(orig_s0)

    # Find submesh descriptors by scanning for strings (same as parser)
    off = 5 + n_lods * 4 * 2  # after flags + offset tables

    # Scan for first string
    scan = off
    while scan < len(s0) - 10:
        b = s0[scan]
        if 4 < b < 100:
            test = s0[scan + 1:scan + 1 + b]
            if len(test) == b and all(32 <= c < 127 for c in test):
                break
        scan += 1
    off = scan

    sm_idx = 0
    while off < len(s0) - 20 and sm_idx < len(submeshes):
        name_len = s0[off]
        if name_len == 0 or name_len > 200:
            break
        off += 1 + name_len  # skip name

        mat_len = s0[off]
        off += 1 + mat_len  # skip material

        # flag + pad
        off += 3

        # Update 8 bbox floats: [pivot_x, pivot_y, bmin_x, bmin_y, bmin_z, bmax_x, bmax_y, bmax_z]
        sm = submeshes[sm_idx]
        bmin, bmax = _compute_bbox(sm.vertices)

        # Preserve original pivot (floats[0:2])
        # Update bbox (floats[2:8])
        struct.pack_into("<f", s0, off + 2 * 4, bmin[0])
        struct.pack_into("<f", s0, off + 3 * 4, bmin[1])
        struct.pack_into("<f", s0, off + 4 * 4, bmin[2])
        struct.pack_into("<f", s0, off + 5 * 4, bmax[0])
        struct.pack_into("<f", s0, off + 6 * 4, bmax[1])
        struct.pack_into("<f", s0, off + 7 * 4, bmax[2])
        off += 32

        # Skip bone data
        bone_count = s0[off]
        off += 1
        bones_size = bone_count + (bone_count % 2)
        off += bones_size

        # Update vertex counts (n_lods × u16) — set all LODs to LOD0 value
        nv = len(sm.vertices)
        for i in range(n_lods):
            struct.pack_into("<H", s0, off + i * 2, nv)
        off += n_lods * 2

        # Update index counts (read until garbage, then update valid ones)
        ni = len(sm.faces) * 3
        for i in range(n_lods):
            if off + 4 > len(s0):
                break
            val = struct.unpack_from("<I", s0, off)[0]
            if val > 10_000_000:
                break
            struct.pack_into("<I", s0, off, ni)
            off += 4

        sm_idx += 1

        # Check next submesh
        if off >= len(s0) - 4:
            break
        next_b = s0[off]
        if next_b == 0 or next_b > 200:
            break
        peek = s0[off + 1:off + 1 + min(next_b, 6)]
        if not all(32 <= c < 127 for c in peek):
            break

    return s0
