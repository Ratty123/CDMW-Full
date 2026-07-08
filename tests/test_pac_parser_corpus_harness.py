from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from tools import pac_parser_corpus_harness as harness


def _valid_submesh(vertex_count: int = 3) -> SubMesh:
    return SubMesh(
        name="part",
        material="part",
        vertices=[(float(index), 0.0, 0.0) for index in range(vertex_count)],
        uvs=[(0.0, 0.0)] * vertex_count,
        normals=[(0.0, 1.0, 0.0)] * vertex_count,
        faces=[(0, 1, 2)],
        source_vertex_map=list(range(vertex_count)),
        source_vertex_offsets=[0, 40, 80][:vertex_count],
        source_vertex_stride=40,
        source_index_count=3,
        bone_indices=[()] * vertex_count,
        bone_weights=[()] * vertex_count,
    )


def test_chunk_bounds_can_scan_multiple_chunks() -> None:
    assert harness._chunk_bounds(10, 3, 0, 1) == (0, 3)
    assert harness._chunk_bounds(10, 3, 2, 2) == (6, 10)
    assert harness._chunk_bounds(10, 3, 9, 1) == (10, 10)


@pytest.mark.parametrize(
    ("chunk_size", "chunk_index", "chunk_count"),
    [(0, 0, 1), (1, -1, 1), (1, 0, 0)],
)
def test_chunk_bounds_rejects_invalid_arguments(chunk_size: int, chunk_index: int, chunk_count: int) -> None:
    with pytest.raises(ValueError):
        harness._chunk_bounds(10, chunk_size, chunk_index, chunk_count)


def test_validate_parsed_pac_mesh_accepts_valid_unweighted_pac() -> None:
    submesh = _valid_submesh()
    mesh = ParsedMesh(
        path="character/model/sample.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_bones=False,
    )

    assert harness.validate_parsed_pac_mesh(mesh, data_size=200) == []


def test_validate_parsed_pac_mesh_reports_empty_fallback() -> None:
    mesh = ParsedMesh(path="character/model/sample.pac", format="pac")

    issues = harness.validate_parsed_pac_mesh(mesh, data_size=100)

    assert [issue.code for issue in issues] == ["empty_geometry"]
    assert issues[0].actual == {"submeshes": 0, "total_vertices": 0, "total_faces": 0}


def test_validate_parsed_pac_mesh_reports_non_pac_fallback_and_empty_geometry() -> None:
    mesh = ParsedMesh(path="character/model/sample.pac", format="pam")

    issues = harness.validate_parsed_pac_mesh(mesh, data_size=100)

    assert [issue.code for issue in issues] == ["fallback_format", "empty_geometry"]


def test_validate_parsed_pac_mesh_reports_missing_source_metadata() -> None:
    submesh = _valid_submesh()
    submesh.source_vertex_map = [0, 1]
    submesh.source_vertex_offsets = []
    submesh.source_vertex_stride = 0
    submesh.source_index_count = 0
    mesh = ParsedMesh(
        path="character/model/sample.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
    )

    issues = harness.validate_parsed_pac_mesh(mesh, data_size=200)

    assert {
        "source_vertex_map_length_mismatch",
        "source_vertex_offsets_length_mismatch",
        "source_vertex_stride_missing",
        "source_index_count_missing",
    }.issubset({issue.code for issue in issues})


def test_validate_parsed_pac_mesh_reports_skinned_bone_row_mismatch() -> None:
    submesh = _valid_submesh()
    submesh.bone_indices = [(0,), (0,)]
    submesh.bone_weights = [(1.0,), (1.0,), (1.0,)]
    mesh = ParsedMesh(
        path="character/model/sample.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_bones=True,
    )

    issues = harness.validate_parsed_pac_mesh(mesh, data_size=200)

    assert "bone_row_count_mismatch" in {issue.code for issue in issues}


def test_cumulative_summary_merges_chunk_reports(tmp_path: Path) -> None:
    first = {
        "format": "cdmw_pac_parser_corpus_v1",
        "report_type": "chunk",
        "chunk": {"chunk_index": 0, "chunk_size": 2, "start": 0, "end": 2, "scanned": 2},
        "rows": [
            {"entry_key": "a", "path": "character/model/a.pac", "status": "ok", "issues": [], "total_vertices": 3, "total_faces": 1, "submesh_count": 1},
            {"entry_key": "b", "path": "character/model/b.pac", "status": "ok", "issues": [], "total_vertices": 6, "total_faces": 2, "submesh_count": 2},
        ],
    }
    second = {
        "format": "cdmw_pac_parser_corpus_v1",
        "report_type": "chunk",
        "chunk": {"chunk_index": 1, "chunk_size": 2, "start": 2, "end": 3, "scanned": 1},
        "rows": [
            {
                "entry_key": "c",
                "path": "character/model/c.pac",
                "status": "unsupported_or_incomplete",
                "issues": [{"code": "empty_geometry"}],
                "total_vertices": 0,
                "total_faces": 0,
                "submesh_count": 0,
            }
        ],
    }
    (tmp_path / "chunk_00000_0000000-0000001.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "chunk_00001_0000002-0000002.json").write_text(json.dumps(second), encoding="utf-8")

    summary = harness._write_cumulative_summary(tmp_path, total_entries=3, chunk_size=2)

    assert summary["completed_chunk_count"] == 2
    assert summary["remaining_chunk_count"] == 0
    assert summary["summary"]["scanned"] == 3
    assert summary["summary"]["statuses"] == {"ok": 2, "unsupported_or_incomplete": 1}
    assert summary["summary"]["issue_codes"] == {"empty_geometry": 1}
    assert summary["gate"]["all_entries_scanned"] is True
    assert summary["gate"]["all_scanned_entries_ok"] is False
