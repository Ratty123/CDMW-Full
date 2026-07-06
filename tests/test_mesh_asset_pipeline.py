from __future__ import annotations

from dataclasses import replace

from cdmw.domain.mesh import validate_mesh_asset_rebuild
from cdmw.modding.mesh_asset import mesh_asset_from_parsed_mesh, mesh_asset_to_inspect_dict
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_roundtrip import (
    AllowedDifference,
    diff_byte_ranges,
    roundtrip_mesh_bytes,
)


def _parsed_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="body",
        material="skin",
        texture="skin.dds",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        bone_indices=[(0,), (0,), (0,)],
        bone_weights=[(1.0,), (1.0,), (1.0,)],
        source_vertex_map=[0, 1, 2],
        source_vertex_offsets=[4, 8, 12],
        source_index_offset=16,
        source_index_count=3,
        source_vertex_stride=4,
        source_descriptor_offset=2,
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="character/body.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
        has_bones=True,
    )


def test_mesh_asset_preserves_source_offsets_raw_records_and_inspection_counts() -> None:
    asset = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii", source_path="character/body.pac")

    submesh = asset.lods[0].submeshes[0]

    assert asset.layout_confidence == "exact"
    assert submesh.original_descriptor_offset == 2
    assert submesh.original_vertex_offset == 4
    assert submesh.original_index_offset == 16
    assert submesh.vertex_buffer.raw_vertex_records == (b"aaaa", b"bbbb", b"cccc")
    assert submesh.vertex_buffer.vertices[1].source_offset == 8
    assert mesh_asset_to_inspect_dict(asset)["lods"][0]["submeshes"][0]["raw_vertex_record_count"] == 3


def test_mesh_asset_validator_blocks_topology_bone_and_source_map_loss() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(
        submesh,
        source_vertex_map=(),
        index_buffer=replace(submesh.index_buffer, indices=(0, 1, 99)),
    )
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)
    codes = {issue.code for issue in result.issues}

    assert result.ok is False
    assert "INVALID_INDEX_RANGE" in codes
    assert "SOURCE_VERTEX_MAP_MISSING" in codes


def test_mesh_asset_validator_blocks_fallback_scan_rebuilds() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    fallback = replace(original, layout_confidence="fallback_scan")

    result = validate_mesh_asset_rebuild(fallback, fallback)

    assert result.ok is False
    assert result.fatal_issues[0].code == "FALLBACK_SCAN_REBUILD_BLOCKED"


def test_binary_diff_ranges_collapse_adjacent_differences() -> None:
    assert diff_byte_ranges(b"abcdef", b"abXYefZZ") == [(2, 4), (6, 8)]


def test_roundtrip_harness_reports_strict_and_tolerant_results() -> None:
    parsed = _parsed_mesh()

    def parser(data: bytes, filename: str) -> ParsedMesh:
        return parsed

    def changed_rebuilder(mesh: ParsedMesh, original: bytes) -> bytes:
        return original[:2] + b"XY" + original[4:]

    strict = roundtrip_mesh_bytes(
        b"abcdef",
        "mesh.pac",
        parser=parser,
        rebuilder=changed_rebuilder,
        strict=True,
    )
    tolerant = roundtrip_mesh_bytes(
        b"abcdef",
        "mesh.pac",
        parser=parser,
        rebuilder=changed_rebuilder,
        strict=False,
        allowed_differences=(AllowedDifference(2, 4, "checksum"),),
    )

    assert strict.report["result"] == "FAIL"
    assert strict.report["unexpected_differences"] == 1
    assert tolerant.report["result"] == "PASS"
    assert tolerant.report["allowed_differences"] == 1
    assert tolerant.report["unexpected_differences"] == 0
