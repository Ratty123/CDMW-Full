from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.domain.mesh.weight_transfer import percentile_95, sample_weight_row, spatial_transfer_distance_limit
from cdmw.modding import mesh_native_rigging
from cdmw.modding.mesh_native_rigging import find_native_mesh_core_binary, transfer_native_mesh_skin_weights_from_source
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service_rigging import _source_weight_row_for_transfer


def _weighted_triangle() -> SubMesh:
    return SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        bone_indices=[(0,), (1,), (2,)],
        bone_weights=[(1.0,), (1.0,), (1.0,)],
    )


def test_closest_triangle_transfer_interpolates_normalized_weights() -> None:
    source = _weighted_triangle()
    sample = sample_weight_row(
        (0.25, 0.25, 0.0),
        source.vertices,
        source.faces,
        source.bone_indices,
        source.bone_weights,
    )

    assert sample.source_face == (0, 1, 2)
    assert sample.distance == pytest.approx(0.0)
    assert sample.bone_indices == (0, 1, 2)
    assert sample.bone_weights == pytest.approx((0.5, 0.25, 0.25))
    assert sum(sample.bone_weights) == pytest.approx(1.0)


def test_transfer_rejects_zero_contributing_weight_row() -> None:
    source = _weighted_triangle()
    source.bone_indices[1] = ()
    source.bone_weights[1] = ()

    with pytest.raises(ValueError, match="empty or invalid"):
        sample_weight_row(
            (0.25, 0.25, 0.0),
            source.vertices,
            source.faces,
            source.bone_indices,
            source.bone_weights,
        )


def test_source_vertex_lineage_remains_exact_before_spatial_transfer() -> None:
    source = _weighted_triangle()
    target = SubMesh(vertices=[(50.0, 50.0, 50.0)], source_vertex_map=[1])

    indices, weights, distance = _source_weight_row_for_transfer(target, 0, source)

    assert indices == (1,)
    assert weights == (1.0,)
    assert distance is None


def test_spatial_distance_policy_uses_p95_and_five_percent_bbox() -> None:
    source = _weighted_triangle()
    assert spatial_transfer_distance_limit(source.vertices) == pytest.approx((2.0**0.5) * 0.05)
    assert percentile_95([0.01] * 18 + [0.5, 0.5]) == pytest.approx(0.5)


def test_native_transfer_can_reject_non_donor_source_vertex_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ParsedMesh(submeshes=[_weighted_triangle()], has_bones=True)
    target = ParsedMesh(submeshes=[SubMesh(
        vertices=[(0.25, 0.25, 0.0)],
        bone_indices=[(9,)],
        bone_weights=[(1.0,)],
        source_vertex_map=[2],
    )], has_bones=True)
    captured: dict[str, object] = {}

    monkeypatch.setattr(mesh_native_rigging, "find_native_mesh_core_binary", lambda: Path("native.exe"))
    monkeypatch.setattr(mesh_native_rigging, "_ensure_native_mesh_session_submesh", lambda *args, **kwargs: "session")

    def capture_job(_binary: Path, _command: str, payload: dict[str, object], *, timeout_seconds: float) -> None:
        captured.update(payload)
        return None

    monkeypatch.setattr(mesh_native_rigging, "_run_native_mesh_core_job", capture_job)

    assert transfer_native_mesh_skin_weights_from_source(
        target,
        source,
        {0: [0]},
        source_vertex_map_is_donor_lineage=False,
    ) is None
    item = captured["submeshes"][0]  # type: ignore[index]
    assert item["source_vertex_map_is_donor_lineage"] is False
    assert "source_vertex_map_binary" not in item
    assert "source_vertex_map_start" not in item


def test_native_transfer_uses_closest_triangle_and_reports_far_mapping() -> None:
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    source_submesh = _weighted_triangle()
    source = ParsedMesh(submeshes=[source_submesh], has_bones=True)
    target_submesh = SubMesh(
        vertices=[(0.25, 0.25, 0.0)],
        bone_indices=[(9,)],
        bone_weights=[(1.0,)],
        source_vertex_map=[2],
    )
    target = ParsedMesh(submeshes=[target_submesh], has_bones=True)

    result = transfer_native_mesh_skin_weights_from_source(
        target,
        source,
        {0: [0]},
        source_vertex_map_is_donor_lineage=False,
    )

    assert result is not None
    assert target_submesh.bone_indices == [(0, 1, 2)]
    assert target_submesh.bone_weights[0] == pytest.approx((0.5, 0.25, 0.25))

    exact_submesh = SubMesh(
        vertices=[(0.25, 0.25, 0.0)],
        bone_indices=[(9,)],
        bone_weights=[(1.0,)],
        source_vertex_map=[2],
    )
    exact = ParsedMesh(submeshes=[exact_submesh], has_bones=True)
    assert transfer_native_mesh_skin_weights_from_source(exact, source, {0: [0]}) is not None
    assert exact_submesh.bone_indices == [(2,)]
    assert exact_submesh.bone_weights == [(1.0,)]

    far = ParsedMesh(submeshes=[SubMesh(
        vertices=[(10.0, 10.0, 0.0)],
        bone_indices=[(9,)],
        bone_weights=[(1.0,)],
    )], has_bones=True)
    assert transfer_native_mesh_skin_weights_from_source(far, source, {0: [0]}) is None
    assert far.submeshes[0].bone_indices == [(9,)]
