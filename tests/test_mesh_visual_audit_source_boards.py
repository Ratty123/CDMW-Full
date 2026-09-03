from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from tools.mesh_harness.visual_audit_source_boards import (
    _graph_texture_lines,
    _load_source_board_rgba,
    _source_parameter_lines,
    build_source_material_boards,
)


def test_source_board_load_retries_a_transient_partial_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    preview = tmp_path / "decoded.png"
    Image.new("RGBA", (3, 2), (40, 80, 120, 200)).save(preview, "PNG")
    calls = 0
    delays: list[float] = []

    def flaky_open(path: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("broken data stream when reading image file")
        return Image.open(path)

    monkeypatch.setattr(
        "tools.mesh_harness.visual_audit_source_boards.time.sleep",
        delays.append,
    )
    image = _load_source_board_rgba(
        preview,
        image_type=SimpleNamespace(open=flaky_open),
    )

    assert calls == 2
    assert delays == [0.1]
    assert image.mode == "RGBA"
    assert image.size == (3, 2)
    assert image.getpixel((0, 0)) == (40, 80, 120, 200)


def test_source_board_lists_exact_integer_and_selector_channel_parameters() -> None:
    lines = _source_parameter_lines(
        {
            "pac_xml_parameters": [
                {
                    "owner_wrapper_item_id": "338",
                    "parameter_kind": "byte4",
                    "parameter_name": "_dyeingTransformProperty0",
                    "integer_value": 4294967295,
                },
                {
                    "owner_wrapper_item_id": "338",
                    "parameter_kind": "texture",
                    "parameter_name": "_colorBlendingMaskTexture",
                    "texture_path": "character/texture/handle_ma.dds",
                    "role": "material",
                    "layer_channel": "",
                },
                {
                    "owner_wrapper_item_id": "338",
                    "parameter_kind": "texture",
                    "parameter_name": "_detailDiffuseMaskB",
                    "texture_path": "character/texture/detail.dds",
                    "role": "layer",
                    "layer_channel": "b",
                },
            ]
        }
    )

    assert "4294967295" in lines[0]
    assert lines[1].endswith("[material]")
    assert lines[2].endswith("[layer/b]")


def test_graph_only_texture_has_separate_hash_bound_board(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.mesh_harness.visual_audit_source_boards as boards

    preview = tmp_path / "decoded.png"
    Image.new("RGBA", (4, 2), (32, 96, 224, 128)).save(preview, "PNG")
    sources = []
    for index in range(3):
        source = tmp_path / f"source-{index}.dds"
        source.write_bytes(f"DDS source {index}".encode())
        sources.append(source)
    monkeypatch.setattr(
        boards,
        "ensure_native_dds_preview_png",
        lambda *_args, **_kwargs: preview,
    )
    monkeypatch.setattr(
        boards,
        "_dds_header_row",
        lambda _path: {
            "source_width": 4,
            "source_height": 2,
            "source_mip_count": 3,
            "source_format": "BC7",
        },
    )
    common = {
        "semantic": "material",
        "parameter_kind": "texture",
        "component_scope_id": "character/model/component.pac#model-property:0",
        "owner_slot_index": 4,
        "owner_wrapper_item_id": "657",
        "material_wrapper_index": 4,
        "binding_authority": "resolved",
        "binding_disposition": "logical_pac_texture_edge",
        "packed_channels": "rgba",
        "srgb_mode": "linear",
        "logical_graph_edge": True,
    }
    result = build_source_material_boards(
        "graph-separation",
        [
            {
                **common,
                "submesh_indices": [0],
                "source_path": str(sources[0]),
                "archive_path": "character/texture/visible.dds",
                "parameter_name": "_visibleTexture",
            },
            {
                **common,
                "submesh_index": -1,
                "submesh_indices": [],
                "source_path": str(sources[1]),
                "archive_path": "character/texture/declared_graph.dds",
                "declared_archive_path": "character/texture/declared_graph.dds",
                "resolved_archive_path": "texture/default/resolved_graph.dds",
                "source_resolution": "technique_default",
                "source_resolution_detail": "declared source absent",
                "parameter_name": "_graphOnlyTexture",
                "layer_role": "mask",
                "layer_channel": "a",
            },
            {
                **common,
                "submesh_indices": [-1, 0],
                "source_path": str(sources[2]),
                "archive_path": "character/texture/mixed.dds",
                "parameter_name": "_mixedTexture",
            },
        ],
        {
            "submeshes": [
                {
                    "submesh_index": 0,
                    "material_name": "visible-material",
                    "shader_family": "standard_v2",
                    "binding_conservation": {"conserved": True},
                }
            ]
        },
        tmp_path / "boards",
    )

    assert len(result["boards"]) == 1
    assert result["boards"][0]["texture_count"] == 2
    assert len(result["graph_boards"]) == 1
    graph_board = result["graph_boards"][0]
    assert graph_board["source_texture_ordinals"] == [1]
    assert graph_board["texture_count"] == 1
    assert graph_board["component_scope_ids"] == [common["component_scope_id"]]
    assert result["boards"][0]["component_scope_ids"] == [
        common["component_scope_id"]
    ]
    assert Path(graph_board["path"]).is_file()
    assert graph_board["sha256"] == hashlib.sha256(
        Path(graph_board["path"]).read_bytes()
    ).hexdigest()
    edge = graph_board["logical_edges"][0]
    assert edge["component_scope_id"] == common["component_scope_id"]
    assert edge["owner_wrapper_item_id"] == "657"
    assert edge["material_wrapper_index"] == 4
    assert edge["parameter_name"] == "_graphOnlyTexture"
    assert edge["declared_archive_path"] == "character/texture/declared_graph.dds"
    assert edge["resolved_archive_path"] == "texture/default/resolved_graph.dds"
    assert edge["source_resolution"] == "technique_default"
    assert edge["decoded_channels"] == ["R", "G", "B", "A"]
    assert edge["source_sha256"] == hashlib.sha256(sources[1].read_bytes()).hexdigest()
    graph_lines = _graph_texture_lines(result["textures"][1])
    assert f"component scope={common['component_scope_id']}" in graph_lines
    assert "owner=657 owner_slot=4" in graph_lines
    assert any("parameter=_graphOnlyTexture" in line for line in graph_lines)
    assert "declared archive source=character/texture/declared_graph.dds" in graph_lines
    assert "resolved archive source=texture/default/resolved_graph.dds" in graph_lines
    assert "archive resolution=technique_default | detail=declared source absent" in graph_lines
    assert "decoded channels=R/G/B/A" in graph_lines
    assert "DDS=4x2 mips=3 format=BC7" in graph_lines
    assert f"source sha256={edge['source_sha256']}" in graph_lines
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["graph_boards"] == result["graph_boards"]


def test_graph_only_boards_shard_below_the_png_height_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.mesh_harness.visual_audit_source_boards as boards

    preview = tmp_path / "decoded.png"
    Image.new("RGBA", (2, 2), (10, 20, 30, 255)).save(preview, "PNG")
    source = tmp_path / "source.dds"
    source.write_bytes(b"DDS shared graph source")
    monkeypatch.setattr(
        boards,
        "ensure_native_dds_preview_png",
        lambda *_args, **_kwargs: preview,
    )
    monkeypatch.setattr(
        boards,
        "_dds_header_row",
        lambda _path: {
            "source_width": 2,
            "source_height": 2,
            "source_mip_count": 1,
            "source_format": "BC3",
        },
    )
    two_row_cap = (
        boards._GRAPH_BOARD_HEADER_HEIGHT
        + 2 * (boards._GRAPH_BOARD_PANEL + boards._GRAPH_BOARD_ROW_GAP)
    )
    monkeypatch.setattr(boards, "GRAPH_BOARD_MAX_HEIGHT", two_row_cap)
    rows = [
        {
            "submesh_index": -1,
            "component_scope_id": (
                f"character/model/component-{index}.pac#model-property:0"
            ),
            "source_path": str(source),
            "archive_path": f"texture/graph-{index}.dds",
            "parameter_name": f"_graph{index}",
            "parameter_kind": "texture",
            "owner_wrapper_item_id": str(100 + index),
            "logical_graph_edge": True,
        }
        for index in range(5)
    ]

    result = build_source_material_boards(
        "graph-shards",
        rows,
        {"submeshes": []},
        tmp_path / "boards",
    )

    assert result["boards"] == []
    assert [row["texture_count"] for row in result["graph_boards"]] == [2, 2, 1]
    assert [
        ordinal
        for board in result["graph_boards"]
        for ordinal in board["source_texture_ordinals"]
    ] == [0, 1, 2, 3, 4]
    for index, graph_board in enumerate(result["graph_boards"]):
        assert graph_board["shard_index"] == index
        assert graph_board["shard_count"] == 3
        with Image.open(graph_board["path"]) as image:
            assert image.width == (
                boards._GRAPH_BOARD_TEXT_WIDTH + boards._GRAPH_BOARD_PANEL * 5
            )
            assert image.height <= two_row_cap
