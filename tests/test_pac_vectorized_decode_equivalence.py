"""The vectorized PAC decode paths must match their scalar fallbacks exactly.

The scalar loops in ``cdmw.modding.mesh_parser`` and ``cdmw.core.model_preview``
stay authoritative; the numpy bulk paths exist only for speed. These tests feed
both implementations identical records, including the edge cases that shaped
the scalar code (zero weights, NaN texture coordinates, a degenerate bounding
axis, and a truncated final record), and require bit-identical output.
"""

from __future__ import annotations

import math
import struct

import pytest

import cdmw.core.model_preview as model_preview
import cdmw.modding.mesh_parser as mesh_parser

numpy = pytest.importorskip("numpy")


class _ForcedScalar:
    """Temporarily report numpy as unavailable to a module's _np_module()."""

    def __init__(self, module) -> None:
        self.module = module

    def __enter__(self):
        self.module._NUMPY_CHECKED = True
        self.module._NUMPY = None
        return self

    def __exit__(self, *_exc) -> None:
        self.module._NUMPY_CHECKED = False
        self.module._NUMPY = None


def _synthetic_descriptor() -> mesh_parser.PacDescriptor:
    return mesh_parser.PacDescriptor(
        name="synthetic",
        material="synthetic_mat",
        vertex_counts=[0, 0, 0, 0, 0],
        index_counts=[0, 0, 0, 0, 0],
        bbox_min=(-1.5, 0.0, 2.25),
        bbox_extent=(3.0, 0.0, 4.5),
        palette=(0, 3, 7),
        descriptor_offset=0,
        stored_lod_count=1,
    )


def _synthetic_records(count: int) -> bytes:
    payload = bytearray()
    for index in range(count):
        payload += struct.pack("<HHH", (index * 977) % 65536, 32767, (index * 31) % 65536)
        payload += b"\x00\x00"
        if index % 5 == 0:
            payload += struct.pack("<HH", 0x7E00, 0x3C00)  # NaN u, 1.0 v
        else:
            payload += struct.pack("<ee", index * 0.125, 1.0 - index * 0.0625)
        payload += b"\x00\x00\x00\x00"
        payload += struct.pack("<I", (index * 2654435761) % (1 << 32))
        payload += struct.pack("<II", (index * 73) % (1 << 30), (index * 1571) % (1 << 30))
        if index % 4 == 0:
            payload += b"\x00" * 6  # rigidly bound: every weight zero
        elif index % 4 == 1:
            payload += bytes([255, 0, 0, 0, 0, 0])
        else:
            payload += bytes([120, 80, 40, 10, 5, index % 3])
        payload += b"\x00\x00\x00\x00\x00\x00"
    assert len(payload) == count * 40
    return bytes(payload)


def _scalar_decode(data: bytes, base_off: int, count: int, desc) -> tuple:
    verts, uvs, normals, offsets, bones, weights = [], [], [], [], [], []
    for vertex_index in range(count):
        rec_off = base_off + vertex_index * 40
        if rec_off + 40 > len(data):
            break
        pos, uv, normal, packed_bones, packed_weights = mesh_parser._decode_pac_vertex_record(
            data, rec_off, desc
        )
        verts.append(pos)
        uvs.append(uv)
        normals.append(normal)
        offsets.append(rec_off)
        bones.append(packed_bones)
        weights.append(packed_weights)
    return verts, uvs, normals, offsets, bones, weights


def _values_identical(left, right) -> bool:
    if left == right:
        return True
    # NaN texture coordinates are equal by bit pattern but not by ==.
    return repr(left) == repr(right)


def test_bulk_vertex_decode_matches_scalar_loop() -> None:
    desc = _synthetic_descriptor()
    data = _synthetic_records(101)
    bulk = mesh_parser._decode_pac_vertex_records_bulk(data, 0, 101, desc)
    assert bulk is not None
    scalar = _scalar_decode(data, 0, 101, desc)
    labels = ("vertices", "uvs", "normals", "source_offsets", "bone_indices", "bone_weights")
    for label, bulk_values, scalar_values in zip(labels, bulk, scalar):
        assert _values_identical(bulk_values, scalar_values), label


def test_bulk_vertex_decode_stops_at_truncated_record() -> None:
    desc = _synthetic_descriptor()
    data = _synthetic_records(8)[:-7]  # last record incomplete
    bulk = mesh_parser._decode_pac_vertex_records_bulk(data, 0, 8, desc)
    assert bulk is not None
    scalar = _scalar_decode(data, 0, 8, desc)
    assert len(bulk[0]) == 7 == len(scalar[0])
    for bulk_values, scalar_values in zip(bulk, scalar):
        assert _values_identical(bulk_values, scalar_values)


def test_bulk_vertex_decode_empty_and_negative_offsets() -> None:
    desc = _synthetic_descriptor()
    assert mesh_parser._decode_pac_vertex_records_bulk(b"", 0, 4, desc) == ([], [], [], [], [], [])
    assert mesh_parser._decode_pac_vertex_records_bulk(b"\x00" * 80, -1, 2, desc) is None


def test_face_filter_matches_scalar_rules() -> None:
    indices = [0, 1, 2, 2, 2, 3, 1, 2, 3, 7, 1, 2, 0, 0, 0, 4, 5]  # tail not a full triple
    vertex_count = 5

    strict = mesh_parser._pac_faces_from_indices(indices, vertex_count, require_distinct=True)
    scalar_strict = []
    for i in range(0, len(indices) - 2, 3):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        if a < vertex_count and b < vertex_count and c < vertex_count and len({a, b, c}) == 3:
            scalar_strict.append((a, b, c))
    assert strict == scalar_strict

    offset = mesh_parser._pac_faces_from_indices(indices, 4, require_distinct=False, base_offset=10)
    scalar_offset = []
    for i in range(0, len(indices) - 2, 3):
        a, b, c = indices[i], indices[i + 1], indices[i + 2]
        if a < 4 and b < 4 and c < 4:
            scalar_offset.append((a + 10, b + 10, c + 10))
    assert offset == scalar_offset


def test_read_pac_indices_matches_scalar() -> None:
    values = tuple(index * 3 % 65536 for index in range(50))
    section = b"\x01" * 8 + struct.pack(f"<{len(values)}H", *values)
    fast = mesh_parser._read_pac_indices(section, 0, len(section), 8, len(values))
    with _ForcedScalar(mesh_parser):
        slow = mesh_parser._read_pac_indices(section, 0, len(section), 8, len(values))
    assert fast == slow == list(values)


def _triangle_fixture() -> tuple[list, list]:
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.25, 0.25, 1.0),
        (5.0, 5.0, 5.0),
        (5.0, 5.0, 5.0),  # degenerate partner
    ]
    indices = [
        0, 1, 2,
        1, 2, 3,
        4, 5, 4,  # zero-area triangle
        0, 2, 3,
        -1, 1, 2,  # negative index dropped
        0, 1, 99,  # out of range dropped
        2, 3, 1,
    ]
    return positions, indices


def test_vertex_normals_match_scalar() -> None:
    positions, indices = _triangle_fixture()
    fast = model_preview._build_vertex_normals(positions, indices)
    with _ForcedScalar(model_preview):
        slow = model_preview._build_vertex_normals(positions, indices)
    assert fast == slow
    assert all(len(normal) == 3 and all(math.isfinite(c) for c in normal) for normal in fast)


def test_non_degenerate_triangle_count_matches_scalar() -> None:
    positions, indices = _triangle_fixture()
    fast = model_preview._count_non_degenerate_triangles(positions, indices)
    with _ForcedScalar(model_preview):
        slow = model_preview._count_non_degenerate_triangles(positions, indices)
    assert fast == slow


def test_normalize_model_meshes_matches_scalar() -> None:
    from cdmw.models import ModelPreviewMesh

    def build_meshes():
        return [
            ModelPreviewMesh(
                material_name="a",
                texture_name="",
                positions=[(0.0, 0.0, 0.0), (4.0, 2.0, 1.0), (-2.0, 3.0, 0.5)],
                texture_coordinates=[],
                normals=[],
                indices=[0, 1, 2],
            ),
            ModelPreviewMesh(
                material_name="b",
                texture_name="",
                positions=[(10.0, -1.0, 2.0)],
                texture_coordinates=[],
                normals=[],
                indices=[],
            ),
        ]

    fast_meshes = build_meshes()
    fast_result = model_preview._normalize_model_meshes(fast_meshes)
    slow_meshes = build_meshes()
    with _ForcedScalar(model_preview):
        slow_result = model_preview._normalize_model_meshes(slow_meshes)
    assert fast_result == slow_result
    assert [mesh.positions for mesh in fast_meshes] == [mesh.positions for mesh in slow_meshes]


def _scalar_smooth_normals(vertices, faces):
    with _ForcedScalar(mesh_parser):
        return mesh_parser._compute_smooth_normals(vertices, faces)


def test_smooth_normals_match_scalar_including_degenerates() -> None:
    vertices = [
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (0.0, 2.0, 0.0),
        (1.0, 1.0, 3.0),
        (4.0, 4.0, 4.0),
        (4.0, 4.0, 4.0),
    ]
    faces = [
        (0, 1, 2),
        (1, 2, 3),
        (4, 5, 4),   # zero-area face still contributes the (0, 1, 0) fallback
        (0, 2, 3),
        (0, 1, 99),  # above range: dropped by both implementations
    ]
    assert mesh_parser._compute_smooth_normals(vertices, faces) == _scalar_smooth_normals(vertices, faces)
    assert mesh_parser._compute_smooth_normals(vertices, []) == _scalar_smooth_normals(vertices, [])
    assert mesh_parser._compute_smooth_normals([], faces) == _scalar_smooth_normals([], faces)


def _scalar_pam_gather(data, unique, vert_base, stride, bmin, bmax, has_uv):
    verts, uvs, offsets = [], [], []
    for gi in unique:
        foff = vert_base + gi * stride
        if foff + 6 > len(data):
            break
        xu, yu, zu = struct.unpack_from("<HHH", data, foff)
        offsets.append(foff)
        verts.append((
            mesh_parser._dequant_u16(xu, bmin[0], bmax[0]),
            mesh_parser._dequant_u16(yu, bmin[1], bmax[1]),
            mesh_parser._dequant_u16(zu, bmin[2], bmax[2]),
        ))
        if has_uv and foff + 12 <= len(data):
            u = struct.unpack_from("<e", data, foff + 8)[0]
            v = struct.unpack_from("<e", data, foff + 10)[0]
            uvs.append((u, v))
    return verts, uvs, offsets


def test_pam_unique_vertex_gather_matches_scalar_loop() -> None:
    stride = 12
    payload = bytearray()
    for index in range(40):
        payload += struct.pack("<HHH", (index * 991) % 65536, (index * 7) % 65536, 65535 - index)
        payload += b"\x00\x00"
        payload += struct.pack("<ee", index * 0.25, 1.0 - index * 0.03125)
    data = bytes(payload)[:-5]  # truncate so the tail straddles both bounds checks
    bmin = (-4.0, 0.0, 1.5)
    bmax = (4.0, 0.0, 9.5)  # a zero-extent axis dequantizes to bbox_min exactly
    unique = [0, 3, 4, 7, 21, 38, 39]

    for has_uv, use_stride in ((True, 12), (False, 8)):
        fast = mesh_parser._gather_pam_unique_vertices(
            data, unique, 0, use_stride, bmin, bmax, include_uv=has_uv
        )
        assert fast is not None
        slow = _scalar_pam_gather(data, unique, 0, use_stride, bmin, bmax, has_uv)
        assert _values_identical(fast[0], slow[0])
        assert _values_identical(fast[1], slow[1])
        assert fast[2] == slow[2]


def test_pam_face_mapping_matches_scalar_idx_map() -> None:
    indices = [9, 2, 5, 5, 5, 2, 9, 2, 9, 40, 2, 5, 9]  # trailing partial triple ignored
    unique = sorted(set(indices))
    idx_map = {gi: li + 7 for li, gi in enumerate(unique)}
    scalar = []
    for j in range(0, len(indices) - 2, 3):
        a, b, c = indices[j], indices[j + 1], indices[j + 2]
        if a in idx_map and b in idx_map and c in idx_map:
            scalar.append((idx_map[a], idx_map[b], idx_map[c]))
    assert mesh_parser._map_pam_faces(indices, unique, base_offset=7) == scalar


def test_pam_index_reader_matches_struct_loop() -> None:
    values = tuple((index * 13) % 65536 for index in range(64))
    data = b"\x55" * 6 + struct.pack(f"<{len(values)}H", *values)
    fast = mesh_parser._read_pam_u16_indices(data, 6, len(values))
    with _ForcedScalar(mesh_parser):
        slow = mesh_parser._read_pam_u16_indices(data, 6, len(values))
    assert fast == slow == list(values)
    array = mesh_parser._read_pam_u16_index_array(data, 6, len(values))
    assert array is not None and array.tolist() == list(values)
