from __future__ import annotations

import hashlib
from dataclasses import replace

from cdmw.domain.mesh import validate_mesh_asset_rebuild
from cdmw.modding.mesh_asset import mesh_asset_from_parsed_mesh, mesh_asset_to_inspect_dict
from cdmw.modding.mesh_parser import BinarySectionRange, MeshBinaryLayout, ParsedMesh, SubMesh
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
    assert asset.parse_confidence == "exact"
    assert asset.skeleton_info["skinned"] is True
    assert asset.skeleton_info["inferred_bone_count"] == 1
    assert asset.skeleton_info["parts"][0]["max_influences"] == 1
    assert asset.original_file_size == len(b"0000aaaabbbbcccciiii")
    assert submesh.original_descriptor_offset == 2
    assert submesh.original_vertex_offset == 4
    assert submesh.original_index_offset == 16
    assert submesh.source_index_map == (0, 1, 2)
    assert submesh.vertex_buffer.raw_vertex_records == (b"aaaa", b"bbbb", b"cccc")
    assert submesh.vertex_buffer.vertices[1].source_offset == 8
    inspect = mesh_asset_to_inspect_dict(asset)
    assert inspect["parse_confidence"] == "exact"
    assert inspect["skeleton_info"]["skinned"] is True
    assert inspect["skeleton_info"]["inferred_bone_count"] == 1
    assert inspect["original_file_size"] == len(b"0000aaaabbbbcccciiii")
    assert inspect["lods"][0]["submeshes"][0]["raw_vertex_record_count"] == 3
    assert inspect["lods"][0]["submeshes"][0]["source_index_map_count"] == 3


def test_mesh_asset_source_index_map_uses_original_index_count() -> None:
    parsed = _parsed_mesh()
    parsed.submeshes[0].source_index_count = 6

    asset = mesh_asset_from_parsed_mesh(parsed, b"0000aaaabbbbcccciiii")
    submesh = asset.lods[0].submeshes[0]

    assert len(submesh.index_buffer.indices) == 3
    assert submesh.index_buffer.original_count == 6
    assert submesh.source_index_map == (0, 1, 2, 3, 4, 5)


def test_mesh_asset_from_parsed_mesh_inspects_layout_when_not_supplied(monkeypatch) -> None:
    layout = MeshBinaryLayout(
        format="pac",
        layout_confidence="exact",
        section_ranges=[
            BinarySectionRange("section_0", 80, 32, 0),
            BinarySectionRange("section_1", 112, 64, 1),
        ],
    )
    monkeypatch.setattr("cdmw.modding.mesh_asset.inspect_mesh_binary_layout", lambda _data, _path: layout)

    asset = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"source bytes", source_path="character/body.pac")

    assert asset.lods[0].original_section_offset == 112
    assert asset.lods[0].original_section_size == 64


def test_mesh_asset_validator_blocks_topology_bone_and_source_map_loss() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(
        submesh,
        source_vertex_map=(),
        source_index_map=(),
        index_buffer=replace(submesh.index_buffer, indices=(0, 1, 99)),
    )
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)
    codes = {issue.code for issue in result.issues}

    assert result.ok is False
    assert "INVALID_INDEX_RANGE" in codes
    assert "SOURCE_VERTEX_MAP_MISSING" in codes
    assert "SOURCE_INDEX_MAP_MISSING" in codes


def test_mesh_asset_validator_blocks_source_index_count_changes() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(
        submesh,
        index_buffer=replace(submesh.index_buffer, original_count=4),
        source_index_map=(0, 1, 2, 3),
    )
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)

    assert "SOURCE_INDEX_COUNT_CHANGED" in {issue.code for issue in result.issues}


def test_mesh_asset_validator_blocks_vertex_stride_changes() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(submesh, original_vertex_stride=8)
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)

    issue = next(issue for issue in result.issues if issue.code == "VERTEX_STRIDE_CHANGED")
    assert issue.expected == 4
    assert issue.actual == 8
    assert issue.lod_index == 0
    assert issue.submesh_index == 0


def test_mesh_asset_validator_blocks_raw_vertex_record_loss() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(
        submesh,
        vertex_buffer=replace(submesh.vertex_buffer, raw_vertex_records=()),
    )
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)

    issue = next(issue for issue in result.issues if issue.code == "RAW_VERTEX_RECORDS_CHANGED")
    assert issue.expected == 3
    assert issue.actual == 0
    assert issue.lod_index == 0
    assert issue.submesh_index == 0


def test_mesh_asset_validator_blocks_source_offset_changes() -> None:
    original = mesh_asset_from_parsed_mesh(_parsed_mesh(), b"0000aaaabbbbcccciiii")
    submesh = original.lods[0].submeshes[0]
    edited_submesh = replace(
        submesh,
        original_descriptor_offset=-1,
        original_vertex_offset=-1,
        original_index_offset=-1,
    )
    edited_lod = replace(original.lods[0], submeshes=(edited_submesh,))
    edited = replace(original, lods=(edited_lod,))

    result = validate_mesh_asset_rebuild(original, edited)
    issues = {issue.code: issue for issue in result.issues}

    assert issues["SOURCE_DESCRIPTOR_OFFSET_CHANGED"].expected == 2
    assert issues["SOURCE_DESCRIPTOR_OFFSET_CHANGED"].actual == "missing"
    assert issues["SOURCE_VERTEX_OFFSET_CHANGED"].expected == 4
    assert issues["SOURCE_INDEX_OFFSET_CHANGED"].expected == 16


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


def test_build_mesh_preserves_original_bytes_for_no_edit_pac(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    parsed = _parsed_mesh()
    original_data = b"PAR original bytes"
    monkeypatch.setattr(mesh_importer, "parse_pac", lambda _data, _path: parsed)
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mesh_importer,
        "build_pac",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lossy builder should not run")),
    )

    assert mesh_importer.build_mesh(parsed, original_data) == original_data

    result = mesh_importer.rebuild_mesh_with_report(parsed, original_data)
    assert result.data == original_data
    assert result.report.source_asset_hash == hashlib.sha256(original_data).hexdigest()
    assert result.report.rebuilt_asset_hash == result.report.source_asset_hash
    assert result.report.source_size == len(original_data)
    assert result.report.rebuilt_size == len(original_data)
    assert result.report.parse_confidence == "exact"
    assert result.report.validation_status == "not_run"
    assert result.report.byte_identical is True
    assert result.report.changed_range_count == 0
    assert result.report.changed_byte_ranges == ()
    assert result.report.edited_lods == ()
    assert result.report.edited_submeshes == ()
    assert result.report.changed_channels == ()


def test_build_mesh_uses_builder_when_pac_vertex_changes(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    original = _parsed_mesh()
    edited = _parsed_mesh()
    edited.submeshes[0].vertices[0] = (0.0, 0.0, 0.25)
    builder_inputs = []
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_positions_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": 3,
                "source": "mesh.obj",
            },
        ),
    )
    monkeypatch.setattr(mesh_importer, "parse_pac", lambda _data, _path: original)
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mesh_importer, "build_pac", lambda mesh, *_args, **_kwargs: builder_inputs.append(mesh) or b"rebuilt")

    assert mesh_importer.build_mesh(edited, b"PAR original bytes") == b"rebuilt"
    assert builder_inputs[0] is not edited
    assert builder_inputs[0].submeshes[0].vertices[0] == (0.0, 0.0, 0.25)
    assert builder_inputs[0].submeshes[0].uvs == original.submeshes[0].uvs

    result = mesh_importer.rebuild_mesh_with_report(edited, b"PAR original bytes", validation_status="passed")
    assert result.data == b"rebuilt"
    assert result.report.rebuilt_asset_hash == hashlib.sha256(b"rebuilt").hexdigest()
    assert result.report.validation_status == "passed"
    assert result.report.byte_identical is False
    assert result.report.changed_range_count > 0
    assert result.report.changed_byte_ranges
    assert result.report.edited_lods == (0,)
    assert result.report.edited_submeshes == ("lod0_submesh0",)
    assert result.report.changed_channels == ("positions",)
    assert result.report.edit_operations == (
        {
            "operation": "replace_positions_same_count",
            "lod_index": 0,
            "submesh_index": 0,
            "vertex_count": 3,
            "source": "mesh.obj",
            "created_by": "Mesh Editor v2",
        },
    )


def test_rebuild_report_uses_operation_scope_when_original_parse_fails(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    edited = _parsed_mesh()
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_uv0_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": 3,
                "source": "mesh.obj",
            },
        ),
    )
    monkeypatch.setattr(mesh_importer, "parse_pac", lambda _data, _path: (_ for _ in ()).throw(ValueError("bad parse")))
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mesh_importer, "build_pac", lambda *_args, **_kwargs: b"rebuilt")

    result = mesh_importer.rebuild_mesh_with_report(edited, b"not parseable", validation_status="passed")

    assert result.report.edited_lods == (0,)
    assert result.report.edited_submeshes == ("lod0_submesh0",)
    assert result.report.changed_channels == ("uv0",)
    assert result.report.edit_operations[0]["operation"] == "replace_uv0_same_count"


def test_build_mesh_blocks_invalid_attached_edit_operation(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    edited = _parsed_mesh()
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_positions_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": 99,
                "source": "mesh.obj",
            },
        ),
    )
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mesh_importer,
        "build_pac",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("builder should not run")),
    )

    import pytest

    with pytest.raises(ValueError, match="Mesh edit operation blocked rebuild"):
        mesh_importer.build_mesh(edited, b"PAR original bytes")


def test_build_mesh_blocks_same_count_operation_without_source_map(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    edited = _parsed_mesh()
    edited.submeshes[0].source_vertex_map = []
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_positions_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": 3,
                "source": "mesh.obj",
            },
        ),
    )
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mesh_importer,
        "build_pac",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("builder should not run")),
    )

    import pytest

    with pytest.raises(ValueError, match="source vertex map"):
        mesh_importer.build_mesh(edited, b"PAR original bytes")


def test_build_mesh_blocks_untracked_channel_change(monkeypatch) -> None:
    from cdmw.core import mesh_native
    from cdmw.modding import mesh_importer

    original = _parsed_mesh()
    edited = _parsed_mesh()
    edited.submeshes[0].vertices[0] = (0.0, 0.0, 0.25)
    edited.submeshes[0].uvs[0] = (0.5, 0.5)
    setattr(
        edited,
        "_cdmw_edit_operations",
        (
            {
                "operation": "replace_positions_same_count",
                "lod_index": 0,
                "submesh_index": 0,
                "vertex_count": 3,
                "source": "mesh.obj",
            },
        ),
    )
    monkeypatch.setattr(mesh_importer, "parse_pac", lambda _data, _path: original)
    monkeypatch.setattr(mesh_native, "build_mesh_native", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mesh_importer,
        "build_pac",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("builder should not run")),
    )

    import pytest

    with pytest.raises(ValueError, match="uv0"):
        mesh_importer.build_mesh(edited, b"PAR original bytes")
