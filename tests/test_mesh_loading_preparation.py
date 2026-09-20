"""Geometry preparation preserves validation while avoiding repeated Python scans."""
import struct
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_native_binary_io import (
    _read_face_binary_report_payload, _read_vec2_binary_report_payload, _read_vec3_binary_payload,
)
from cdmw.modding.mesh_native_core_payload_helpers import _face_count_json
from cdmw.services.mesh_service_object_transform import mesh_source_bounds_pivot


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_native_vector_decode_rejects_nonfinite_coordinates(tmp_path, bad):
    path = tmp_path / "vectors.bin"
    path.write_bytes(struct.pack("=dddddd", 1., 2., 3., 4., bad, 6.))
    assert _read_vec3_binary_payload(path, expected_count=2) is None


def test_native_vector_decode_preserves_values_and_exact_length(tmp_path):
    path = tmp_path / "vectors.bin"
    path.write_bytes(struct.pack("=dddddd", -1.5, 2., 3., 4., 5., -6.))
    assert _read_vec3_binary_payload(path, expected_count=2) == [(-1.5, 2., 3.), (4., 5., -6.)]
    assert _read_vec3_binary_payload(path, expected_count=1) is None
    path.write_bytes(b"")
    assert _read_vec3_binary_payload(path, expected_count=0) == []


def test_bounds_pivot_uses_all_finite_vertices_without_trusting_stale_bounds():
    mesh = SimpleNamespace(
        bbox_min=(99., 99., 99.), bbox_max=(100., 100., 100.),
        submeshes=[SimpleNamespace(vertices=[(-2., 3., -4.), (9., 9.), (float("nan"), 100., 100.)]),
                   SimpleNamespace(vertices=[("6", -5., 8.), (0., 0., float("inf"))])],
    )
    assert mesh_source_bounds_pivot(mesh) == (2., -1., 2.)
    assert mesh_source_bounds_pivot(SimpleNamespace(submeshes=[])) == (0., 0., 0.)


def test_native_uv_and_index_buffers_validate_before_materializing(tmp_path):
    path = tmp_path / "buffer.bin"
    descriptor = {"path": str(path)}
    path.write_bytes(struct.pack("=dd", .25, .5))
    assert _read_vec2_binary_report_payload(descriptor, expected_count=1) == [(.25, .5)]
    path.write_bytes(struct.pack("=dd", .25, float("nan")))
    assert _read_vec2_binary_report_payload(descriptor, expected_count=1) is None
    for face, valid in [((0, 1, 2), True), ((-1, 1, 2), False), ((0, 1, 3), False)]:
        path.write_bytes(struct.pack("=iii", *face))
        result = _read_face_binary_report_payload(descriptor, expected_count=1, vertex_count=3)
        assert result == ([face] if valid else None)


def test_native_face_count_retains_conversion_and_rejection_rules():
    assert _face_count_json([
        (0, 1, 2), [0, "1", 2.0], (0, 1, 2, 3),
        (True, 1, 2), (0, 1.5, 2), (0, float("nan"), 2),
        (0, -1, 2), (0, 1, 3), (0, 1), None,
    ], 3) == 3
