from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from cdmw.core.iteminfo_row import DESC_TAG
from cdmw.core.pappt_format import (
    PartPrefabPart,
    PartPrefabRecord,
    PartPrefabTable,
    encode_pappt,
)
from cdmw.core.stringinfo_table import build_stringinfo_row, stringinfo_key
from tests.prefab_collection_builder import build_with_collection
from tools.mesh_harness import equipment_material_review as equipment_review
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
    EQUIPMENT_AUDIT_GENERATION_ID,
    EQUIPMENT_AUDIT_ICON_COUNT,
    EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    EQUIPMENT_AUDIT_RECORD_COUNT,
    EQUIPMENT_AUDIT_ROOT_ID,
    EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION,
)
from tools.mesh_harness.equipment_material_capture import (
    EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_SCHEMA,
    FULL_MODEL_VIEWS,
)
from tools.mesh_harness.equipment_material_review import (
    _RENDER_REQUIRED_TECHNICAL_GATES,
    _SOURCE_REQUIRED_TECHNICAL_GATES,
    EQUIPMENT_REVIEW_LIMITATION_SCHEMA,
    EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA,
    build_equipment_review_index,
    record_equipment_review_pages,
    record_equipment_review_units,
    summarize_equipment_review,
)

_BINARIES = {
    "preview_core": {"sha256": "a" * 64, "bytes": 10},
    "rust_helper": {"sha256": "b" * 64, "bytes": 20},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_png(path: Path, color: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 48), color).save(path)
    return path


def _evidence_row(path: Path, asset_root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(asset_root)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_renderable_asset(
    root: Path,
    ordinal: int,
    *,
    graph_board_count: int = 0,
) -> dict[str, object]:
    asset_id = f"{ordinal:04d}-rendered"
    identity = f"rendered-{ordinal}.pac"
    asset_root = root / "assets" / asset_id
    asset_root.mkdir(parents=True)
    before_report = asset_root / "before" / "audit-report.json"
    after_report = asset_root / "after" / "audit-report.json"
    before_report.parent.mkdir(parents=True)
    after_report.parent.mkdir(parents=True)
    before_report.write_text("{}", encoding="utf-8")
    after_report.write_text("{}", encoding="utf-8")
    icon_board = _write_png(asset_root / "source-boards" / "icon.png", (80, 90, 100))
    contact_sheet = _write_png(asset_root / "contact-sheet.png", (100, 110, 120))
    comparisons: dict[str, str] = {}
    comparison_hashes: dict[str, str] = {}
    for view in FULL_MODEL_VIEWS:
        _write_png(asset_root / "before" / "full-model" / f"{view}.png", (220, 30, 30))
        _write_png(asset_root / "after" / "full-model" / f"{view}.png", (30, 30, 220))
        comparison = _write_png(
            asset_root / "comparisons" / f"{view}.png", (120, 40, 150)
        )
        comparisons[view] = f"comparisons/{view}.png"
        comparison_hashes[view] = _sha256(comparison)
    region_sheet = _write_png(
        asset_root / "material-region-sheets" / "material-0000.png",
        (130, 90, 50),
    )
    source_board = _write_png(
        asset_root / "source-boards" / asset_id / "submesh-000-source-board.png",
        (40, 80, 120),
    )
    graph_boards: list[dict[str, object]] = []
    for graph_index in range(graph_board_count):
        texture_ordinal = 100 + graph_index
        graph_board = _write_png(
            asset_root
            / "source-boards"
            / asset_id
            / f"graph-source-board-{graph_index:03d}.png",
            (55 + graph_index, 85, 125),
        )
        graph_boards.append(
            {
                "graph_board_index": graph_index,
                "shard_index": graph_index,
                "shard_count": graph_board_count,
                "path": str(graph_board.relative_to(asset_root)).replace("\\", "/"),
                "sha256": _sha256(graph_board),
                "texture_count": 1,
                "source_texture_ordinals": [texture_ordinal],
                "logical_edges": [
                    {
                        "source_texture_ordinal": texture_ordinal,
                        "owner_wrapper_item_id": str(600 + graph_index),
                        "parameter_name": f"_graphOnly{graph_index}",
                    }
                ],
            }
        )
    report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "status": "captured",
        "verdict": "UNREVIEWED",
        "identity": identity,
        "capture_binaries": _BINARIES,
        "renderer_path": "native_preview_core_to_direct_and_full_rust_to_wgpu_d3d12",
        "python_material_synthesis_used": False,
        "logical_texture_edge_count": 2,
        "technical_gates": {key: True for key in _RENDER_REQUIRED_TECHNICAL_GATES},
        "before_report": _evidence_row(before_report, asset_root),
        "after_report": _evidence_row(after_report, asset_root),
        "icon_board": _evidence_row(icon_board, asset_root),
        "composites": {
            "before_after": comparisons,
            "before_after_sha256": comparison_hashes,
            "contact_sheet": "contact-sheet.png",
            "contact_sheet_sha256": _sha256(contact_sheet),
            "material_region_sheets": [
                {
                    "material_index": 0,
                    "path": "material-region-sheets/material-0000.png",
                    "sha256": _sha256(region_sheet),
                    "source_board_sha256": _sha256(source_board),
                }
            ],
        },
        "source_boards": {
            "boards": [
                {
                    "submesh_index": 0,
                    "path": (f"source-boards/{asset_id}/submesh-000-source-board.png"),
                    "sha256": _sha256(source_board),
                }
            ],
            "graph_boards": graph_boards,
        },
    }
    (asset_root / "asset-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "ordinal": ordinal,
        "asset_id": asset_id,
        "identity": identity,
        "status": "captured",
    }


def _write_source_only_asset(
    root: Path,
    ordinal: int,
    *,
    status: str = "source_only_captured",
    identity: str | None = None,
    owners: list[dict[str, object]] | None = None,
    owner_records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    asset_id = f"{ordinal:04d}-source-only"
    identity = identity or f"source-only-{ordinal}.pac"
    owners = owners or [
        {
            "declared_path": identity,
            "edge_index": ordinal,
            "item_id": 1_900_000 + ordinal,
            "record_id": f"{ordinal:04d}-{1_900_000 + ordinal}",
        }
    ]
    owner_records = owner_records or [
        {
            "record_id": owner["record_id"],
            "item_id": owner["item_id"],
            "pac_files": [identity],
            "prefab_hashes": [],
            "icon_paths": [
                f"ui/texture/icon/itemicon_source_only_{ordinal}.dds"
            ],
        }
        for owner in owners
    ]
    associated_icons = sorted(
        {
            str(icon)
            for record in owner_records
            for icon in record.get("icon_paths", [])
        }
    )
    asset_root = root / "assets" / asset_id
    asset_root.mkdir(parents=True)
    finding = {
        "finding": "catalogue_name_has_no_renderable_archive_binding",
        "candidate_path_tokens_present": [],
        "owner_prefab_hashes_empty": True,
        "owner_has_no_sibling_pac": True,
        "associated_icons": associated_icons,
    }
    icon_board = _write_png(
        asset_root / "source-boards" / "icon-board.png", (70, 90, 110)
    )
    contact_sheet = _write_png(asset_root / "contact-sheet.png", (45, 55, 65))
    comparisons: dict[str, str] = {}
    comparison_hashes: dict[str, str] = {}
    for view in FULL_MODEL_VIEWS:
        comparison = _write_png(
            asset_root / "comparisons" / f"{view}.png", (35, 45, 55)
        )
        comparisons[view] = f"comparisons/{view}.png"
        comparison_hashes[view] = _sha256(comparison)
    (asset_root / "source-only-report.json").write_text(
        json.dumps(
            {
                "schema": "cdmw_equipment_source_only_capture_v1",
                "ok": True,
                "identity": identity,
                "finding": finding,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "status": status,
        "verdict": "UNREVIEWED" if status == "source_only_captured" else "PASS",
        "identity": identity,
        "technical_gates": {key: True for key in _SOURCE_REQUIRED_TECHNICAL_GATES},
        "source_only_finding": finding,
        "owners": owners,
        "owner_records": owner_records,
        "icon_board": _evidence_row(icon_board, asset_root),
        "composites": {
            "before_after": comparisons,
            "before_after_sha256": comparison_hashes,
            "contact_sheet": "contact-sheet.png",
            "contact_sheet_sha256": _sha256(contact_sheet),
        },
    }
    (asset_root / "asset-report.json").write_text(json.dumps(report), encoding="utf-8")
    return {
        "ordinal": ordinal,
        "asset_id": asset_id,
        "identity": identity,
        "status": status,
        "owners": owners,
        "owner_records": owner_records,
        "finding": finding,
    }


def _write_capture_manifest(root: Path, assets: list[dict[str, object]]) -> None:
    (root / "capture-manifest.json").write_text(
        json.dumps(
            {
                "schema": EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
                "capture_complete": True,
                "failed_count": 0,
                "missing_count": 0,
                "capture_binaries": _BINARIES,
                "assets": assets,
            }
        ),
        encoding="utf-8",
    )


def _write_frozen_source_inputs(
    root: Path, assets: list[dict[str, object]]
) -> None:
    records = [
        dict(record)
        for asset in assets
        for record in asset.get("owner_records", [])
    ]
    for index in range(EQUIPMENT_AUDIT_RECORD_COUNT - len(records)):
        item_id = 2_100_000 + index
        records.append(
            {
                "record_id": f"dummy-{index:04d}-{item_id}",
                "item_id": item_id,
                "pac_files": [f"dummy-{index:04d}.pac"],
                "prefab_hashes": [],
                "icon_paths": [f"ui/texture/icon/dummy-{index:04d}.dds"],
            }
        )
    logical_models = [
        {
            "identity": asset["identity"],
            "declared_name": asset["identity"],
            "owners": asset["owners"],
        }
        for asset in assets
    ]
    for index in range(EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT - len(logical_models)):
        logical_models.append(
            {
                "identity": f"dummy-{index:04d}.pac",
                "declared_name": f"dummy-{index:04d}.pac",
                "owners": [],
            }
        )
    selection_sha256 = "d" * 64
    catalogue = {
        "schema": "cdmw_equipment_material_audit_catalogue_v1",
        "source": {
            "root_id": EQUIPMENT_AUDIT_ROOT_ID,
            "generation_id": EQUIPMENT_AUDIT_GENERATION_ID,
            "archive_fingerprint": EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
            "item_catalog_schema_version": EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION,
            "item_catalog_sha256": EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
        },
        "selection": {
            "record_count": EQUIPMENT_AUDIT_RECORD_COUNT,
            "unique_logical_pac_count": EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
            "unique_icon_count": EQUIPMENT_AUDIT_ICON_COUNT,
            "selection_sha256": selection_sha256,
        },
        "records": records,
        "logical_models": logical_models,
        "icons": [{"identity": f"dummy-{index:04d}.dds"} for index in range(EQUIPMENT_AUDIT_ICON_COUNT)],
    }
    resolved_logical = [
        {
            "identity": asset["identity"],
            "declared_name": asset["identity"],
            "owners": asset["owners"],
            "status": "catalogue_source_only",
            "physical_components": [],
            "direct_candidates": [],
            "prefab_candidates": [],
            "prefab_edges": [],
            "source_only_finding": asset["finding"],
        }
        for asset in assets
    ]
    for index in range(EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT - len(resolved_logical)):
        resolved_logical.append({"identity": f"dummy-{index:04d}.pac"})
    resolution = {
        "schema": "cdmw_equipment_material_audit_resolution_v1",
        "frozen_catalogue": {
            "schema": catalogue["schema"],
            "item_catalog_sha256": EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
            "selection_sha256": selection_sha256,
        },
        "counts": {
            "logical_models": EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
            "icons": EQUIPMENT_AUDIT_ICON_COUNT,
            "unresolved_logical_models": 0,
            "unresolved_icons": 0,
            "prefab_decode_errors": 0,
        },
        "logical_models": resolved_logical,
        "icons": [{"identity": f"dummy-{index:04d}.dds"} for index in range(EQUIPMENT_AUDIT_ICON_COUNT)],
        "prefab_decode_errors": [],
        "resolution_sha256": "e" * 64,
    }
    (root / "catalogue.json").write_text(json.dumps(catalogue), encoding="utf-8")
    (root / "resolution.json").write_text(json.dumps(resolution), encoding="utf-8")


def _iteminfo_row(
    item_id: int,
    *,
    item_type: int,
    equip_type_key: int,
    part_hash: int | None = None,
) -> bytes:
    string_key = f"Item_{item_id}".encode("ascii")
    description = f"description-{item_id}".encode("ascii")
    row = bytearray(struct.pack("<I", item_id))
    row += struct.pack("<I", len(string_key)) + string_key
    row += b"\x00"
    row += struct.pack("<II", 1, 0)
    row += b"\x00"
    row += struct.pack("<I", 0)
    row += struct.pack("<I", equip_type_key)
    row += struct.pack("<I", 0)
    row += DESC_TAG + struct.pack("<II", item_id, len(description)) + description
    row += b"\x00" * 17 + struct.pack("<H", item_type)
    row += b"\x00" * 12
    if part_hash is not None:
        row += struct.pack("<I", part_hash)
    row += b"\xff" * 8
    return bytes(row)


def _pabgh_pair(rows: list[bytes]) -> tuple[bytes, bytes]:
    payload = bytearray()
    directory = bytearray(struct.pack("<H", len(rows)))
    for raw in rows:
        directory += raw[:4] + struct.pack("<I", len(payload))
        payload += raw
    return bytes(payload), bytes(directory)


def _write_parser_source_packet(
    root: Path,
    item_specs: list[tuple[int, int, int, int | None]],
) -> tuple[dict[str, dict[str, str]], dict[int, str], str, int]:
    source_root = root / "review" / "source-evidence"
    source_root.mkdir(parents=True, exist_ok=True)
    raw_rows = {
        item_id: _iteminfo_row(
            item_id,
            item_type=item_type,
            equip_type_key=equip_type_key,
            part_hash=part_hash,
        )
        for item_id, item_type, equip_type_key, part_hash in item_specs
    }
    item_payload, item_header = _pabgh_pair(list(raw_rows.values()))
    empty_stem = "cd_t9999_empty"
    empty_hash = stringinfo_key(empty_stem)
    string_row = build_stringinfo_row(empty_stem)
    string_payload, string_header = _pabgh_pair([string_row])
    prefab_record = PartPrefabRecord(
        stem=empty_stem,
        folder="6_object/object/t9999_dummy",
        sockets_path="",
        extra="Empty",
        flag=0,
        parts=(PartPrefabPart("p1", 1),),
    )
    packet = {
        "iteminfo_payload": source_root / "iteminfo.pabgb",
        "iteminfo_header": source_root / "iteminfo.pabgh",
        "stringinfo_payload": source_root / "stringinfo.pabgb",
        "stringinfo_header": source_root / "stringinfo.pabgh",
        "active_part_prefab_table": source_root / "partprefabtable.pappt",
        "authoritative_prefab": source_root / "cd_t9999_empty.prefab",
    }
    packet["iteminfo_payload"].write_bytes(item_payload)
    packet["iteminfo_header"].write_bytes(item_header)
    packet["stringinfo_payload"].write_bytes(string_payload)
    packet["stringinfo_header"].write_bytes(string_header)
    packet["active_part_prefab_table"].write_bytes(
        encode_pappt(PartPrefabTable(records=(prefab_record,)))
    )
    packet["authoritative_prefab"].write_bytes(build_with_collection(names=()))
    packet["frozen_catalogue"] = root / "catalogue.json"
    packet["live_resolution"] = root / "resolution.json"
    evidence = {
        label: {
            "label": label,
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "sha256": _sha256(path),
        }
        for label, path in packet.items()
    }
    return (
        evidence,
        {item_id: hashlib.sha256(raw).hexdigest() for item_id, raw in raw_rows.items()},
        prefab_record.prefab_path,
        empty_hash,
    )


def test_review_verdicts_are_per_tile_and_bound_to_underlying_output_hashes(
    tmp_path: Path,
) -> None:
    assets = [_write_renderable_asset(tmp_path, index) for index in range(2)]
    _write_capture_manifest(tmp_path, assets)
    index = build_equipment_review_index(
        tmp_path,
        expected_asset_count=2,
        full_models_per_page=2,
        material_regions_per_page=2,
    )

    with pytest.raises(ValueError, match="independently reviewed tiles"):
        record_equipment_review_pages(
            tmp_path,
            ["full-model-0000"],
            verdict="PASS",
            observations="A page-wide decision must not fan out.",
        )

    first = index["assets"][0]
    first_units = [
        first["full_model_review_unit"],
        first["material_regions"][0]["review_unit_id"],
    ]
    record_equipment_review_units(
        tmp_path,
        first_units,
        verdict="PASS",
        observations="This exact PAC tile and material region were inspected.",
    )
    progress = json.loads(
        (tmp_path / "review" / "review-progress.json").read_text(encoding="utf-8")
    )
    full_decision = progress["units"][first_units[0]]
    assert len(full_decision["reviewed_outputs"]) == 19
    assert full_decision["reviewed_output_set_sha256"]
    summary = summarize_equipment_review(tmp_path)
    assert summary["assets"][0]["verdict"] == "PASS"
    assert summary["assets"][1]["verdict"] == "UNREVIEWED"

    atlas_path = tmp_path / index["full_model_pages"][0]["path"]
    with Image.open(atlas_path) as atlas:
        rgb = atlas.convert("RGB")
        colors = {
            color
            for _count, color in (rgb.getcolors(maxcolors=rgb.width * rgb.height) or [])
        }
    assert (220, 30, 30) in colors
    assert (30, 30, 220) in colors

    changed_output = (
        tmp_path
        / "assets"
        / assets[0]["asset_id"]
        / "after"
        / "full-model"
        / "front.png"
    )
    _write_png(changed_output, (1, 2, 3))
    invalidated = summarize_equipment_review(tmp_path)
    assert invalidated["assets"][0]["verdict"] == "UNREVIEWED"


def test_graph_boards_bind_only_to_the_full_model_review_unit(tmp_path: Path) -> None:
    assets = [_write_renderable_asset(tmp_path, 0, graph_board_count=2)]
    _write_capture_manifest(tmp_path, assets)

    index = build_equipment_review_index(
        tmp_path,
        expected_asset_count=1,
        full_models_per_page=1,
        material_regions_per_page=1,
    )

    full_entry = index["full_model_pages"][0]["entries"][0]
    assert [row["graph_board_index"] for row in full_entry["graph_boards"]] == [0, 1]
    full_labels = [row["label"] for row in full_entry["reviewed_outputs"]]
    assert full_labels[-2:] == [
        "logical_graph_source_board:000",
        "logical_graph_source_board:001",
    ]
    assert len(full_labels) == 21
    region_entry = index["material_region_pages"][0]["entries"][0]
    assert [row["label"] for row in region_entry["reviewed_outputs"]] == [
        "material_region_sheet",
        "pac_xml_dds_source_board",
    ]

    asset = index["assets"][0]
    record_equipment_review_units(
        tmp_path,
        [
            asset["full_model_review_unit"],
            asset["material_regions"][0]["review_unit_id"],
        ],
        verdict="PASS",
        observations="The whole model, graph sources, and visible region were reviewed.",
    )
    progress = json.loads(
        (tmp_path / "review" / "review-progress.json").read_text(encoding="utf-8")
    )
    assert len(progress["units"][asset["full_model_review_unit"]]["reviewed_outputs"]) == 21
    assert len(
        progress["units"][asset["material_regions"][0]["review_unit_id"]][
            "reviewed_outputs"
        ]
    ) == 2


def test_graph_board_tamper_invalidates_and_rejects_review(tmp_path: Path) -> None:
    assets = [_write_renderable_asset(tmp_path, 0, graph_board_count=1)]
    _write_capture_manifest(tmp_path, assets)
    index = build_equipment_review_index(tmp_path, expected_asset_count=1)
    full_unit = index["assets"][0]["full_model_review_unit"]
    record_equipment_review_units(
        tmp_path,
        [full_unit],
        verdict="PASS",
        observations="The graph source board was directly inspected before recording.",
    )
    graph_path = tmp_path / index["full_model_pages"][0]["entries"][0][
        "graph_boards"
    ][0]["path"]
    _write_png(graph_path, (1, 2, 3))

    summary = summarize_equipment_review(tmp_path)
    assert summary["assets"][0]["full_model_verdict"] == "UNREVIEWED"
    with pytest.raises(ValueError, match="Evidence hash disagrees"):
        record_equipment_review_units(
            tmp_path,
            [full_unit],
            verdict="PASS",
            observations="Changed graph evidence cannot retain its review.",
        )
    with pytest.raises(ValueError, match="Evidence hash disagrees"):
        build_equipment_review_index(tmp_path, expected_asset_count=1)


def test_limitation_requires_exact_supported_effect_and_complete_source_evidence(
    tmp_path: Path,
) -> None:
    assets = [_write_renderable_asset(tmp_path, 0)]
    _write_capture_manifest(tmp_path, assets)
    index = build_equipment_review_index(
        tmp_path,
        expected_asset_count=1,
        full_models_per_page=1,
        material_regions_per_page=1,
    )
    asset = index["assets"][0]
    record_equipment_review_units(
        tmp_path,
        [asset["full_model_review_unit"]],
        verdict="PASS",
        observations="All six paired direct/full views were inspected.",
    )
    source = tmp_path / "assets" / assets[0]["asset_id"] / "manifests" / "native.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"effect":"proprietary"}', encoding="utf-8")
    region_unit = asset["material_regions"][0]["review_unit_id"]
    evidence = {
        "schema": EQUIPMENT_REVIEW_LIMITATION_SCHEMA,
        "review_unit_id": region_unit,
        "finding_kind": "unsupported_proprietary_effect",
        "effect": {
            "owner_wrapper": "MaterialWrapper[0]",
            "parameter_name": "_proprietaryEffect",
            "source_value": 1,
            "description": "The proprietary effect opcode is not implemented.",
        },
        "color_source_faithful": True,
        "material_ownership_source_faithful": True,
        "implemented_surface_response_source_faithful": True,
        "missing_geometry": False,
        "missing_pac": False,
        "missing_pac_xml": False,
        "missing_icon": False,
        "missing_dds": False,
        "source_evidence": [
            {
                "label": "native material manifest",
                "path": str(source.relative_to(tmp_path)).replace("\\", "/"),
                "sha256": _sha256(source),
            }
        ],
    }
    invalid = {**evidence, "missing_dds": True}
    with pytest.raises(ValueError, match="Missing geometry"):
        record_equipment_review_units(
            tmp_path,
            [region_unit],
            verdict="LIMITATION",
            observations="This must not excuse absent source data.",
            limitation_evidence=invalid,
        )

    completed = record_equipment_review_units(
        tmp_path,
        [region_unit],
        verdict="LIMITATION",
        observations="Source-faithful response is complete except for the cited opcode.",
        limitation_evidence=evidence,
    )
    assert completed["ok"] is True
    assert completed["limitation_count"] == 1
    assert completed["rendered_pass_count"] == 0

    source.write_text('{"effect":"changed"}', encoding="utf-8")
    invalidated = summarize_equipment_review(tmp_path)
    assert invalidated["unreviewed_count"] == 1


def _assert_reviewed_source_dispositions_invalidate_on_change(
    index, tmp_path, packet, excluded, authored_labels, row_hashes, parsed_empty_hash, prefab_path,
):
    second_unit = index["assets"][1]["source_disposition_review_unit"]
    second_facts = {
        "catalogue_identity": "cd_boss_reward_masterthief.pac",
        "owner_item_ids": [1002159],
        "owner_record_ids": ["1828-1002159"],
        "item_row_sha256s": {"1002159": row_hashes[1002159]},
        "item_type": 4_001,
        "equip_type_key": 0,
        "equipment_slot_count": 0,
        "icon_only_false_positive": True,
    }
    record_equipment_review_units(
        tmp_path,
        [second_unit],
        verdict="EXCLUDED_CATALOGUE_DEFECT",
        observations="The second parsed row is also a non-equipment catalogue defect.",
        disposition_evidence={
            **excluded,
            "review_unit_id": second_unit,
            "source_facts": second_facts,
        },
    )

    third_unit = index["assets"][2]["source_disposition_review_unit"]
    authored = {
        "schema": EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA,
        "review_unit_id": third_unit,
        "disposition": "AUTHORED_EMPTY",
        "source_facts": {
            "catalogue_identity": "cd_t0000_fist_0001.pac",
            "owner_item_ids": [1001523, 1003687, 1003688],
            "owner_record_ids": [
                "1770-1001523",
                "1771-1003687",
                "1772-1003688",
            ],
            "item_row_sha256s": {
                "1001523": row_hashes[1001523],
                "1003687": row_hashes[1003687],
                "1003688": row_hashes[1003688],
            },
            "item_type": 108,
            "equip_type_key": 0x3338361E,
            "equipment_slot_count": 0,
            "authoritative_part_hash": parsed_empty_hash,
            "authoritative_part_stem": "cd_t9999_empty",
            "authoritative_prefab": prefab_path,
            "authoritative_prefab_selection": True,
            "model_edge_count": 0,
        },
        "source_evidence": [packet[label] for label in authored_labels],
    }
    completed = record_equipment_review_units(
        tmp_path,
        [third_unit],
        verdict="AUTHORED_EMPTY",
        observations="The selected source prefab authoritatively contains no model edge.",
        disposition_evidence=authored,
    )
    assert completed["ok"] is True
    assert completed["rendered_pass_count"] == 0
    assert completed["excluded_catalogue_defect_count"] == 2
    assert completed["authored_empty_count"] == 1
    assert completed["reviewed_count"] == 3

    packet_path = tmp_path / packet["iteminfo_payload"]["path"]
    packet_path.write_bytes(packet_path.read_bytes() + b"changed")
    invalidated = summarize_equipment_review(tmp_path)
    assert invalidated["unreviewed_count"] == 3


def _write_source_disposition_assets(tmp_path):
    source_assets = (
        (
            "cd_boss_reward_bigmoney.pac",
            [(1002142, "0928-1002142", 858)],
            "ui/texture/icon/itemicon_cd_boss_reward_bigmoney.dds",
        ),
        (
            "cd_boss_reward_masterthief.pac",
            [(1002159, "1828-1002159", 1759)],
            "ui/texture/icon/itemicon_cd_boss_reward_masterthief.dds",
        ),
        (
            "cd_t0000_fist_0001.pac",
            [
                (1001523, "1770-1001523", 1701),
                (1003687, "1771-1003687", 1702),
                (1003688, "1772-1003688", 1703),
            ],
            "ui/texture/icon/itemicon_prefab_cd_t0000_fist_0001.dds",
        ),
    )
    assets: list[dict[str, object]] = []
    for ordinal, (identity, owner_specs, icon_path) in enumerate(source_assets):
        owners = [
            {
                "declared_path": identity,
                "edge_index": edge_index,
                "item_id": item_id,
                "record_id": record_id,
            }
            for item_id, record_id, edge_index in owner_specs
        ]
        owner_records = [
            {
                "record_id": record_id,
                "item_id": item_id,
                "pac_files": [identity],
                "prefab_hashes": [],
                "icon_paths": [icon_path],
            }
            for item_id, record_id, _edge_index in owner_specs
        ]
        assets.append(
            _write_source_only_asset(
                tmp_path,
                ordinal,
                identity=identity,
                owners=owners,
                owner_records=owner_records,
            )
        )
    _write_capture_manifest(tmp_path, assets)
    _write_frozen_source_inputs(tmp_path, assets)
    return assets


def test_source_only_rows_need_parser_derived_non_rendered_dispositions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = _write_source_disposition_assets(tmp_path)
    index = build_equipment_review_index(
        tmp_path,
        expected_asset_count=3,
        full_models_per_page=3,
    )
    summary = summarize_equipment_review(tmp_path)
    assert summary["rendered_pass_count"] == 0
    assert summary["unreviewed_count"] == 3

    first_unit = index["assets"][0]["source_disposition_review_unit"]
    with pytest.raises(ValueError, match="not valid for source_disposition"):
        record_equipment_review_units(
            tmp_path,
            [first_unit],
            verdict="PASS",
            observations="A missing render cannot become a rendered pass.",
        )
    with pytest.raises(ValueError, match="not valid for source_disposition"):
        record_equipment_review_units(
            tmp_path,
            [first_unit],
            verdict="LIMITATION",
            observations="Missing PAC geometry is not a proprietary-effect limitation.",
        )

    empty_hash = stringinfo_key("cd_t9999_empty")
    packet, row_hashes, prefab_path, parsed_empty_hash = _write_parser_source_packet(
        tmp_path,
        [
            (1002142, 4_001, 0, None),
            (1002159, 4_001, 0, None),
            (1001523, 108, 0x3338361E, empty_hash),
            (1003687, 108, 0x3338361E, empty_hash),
            (1003688, 108, 0x3338361E, empty_hash),
        ],
    )
    common_labels = (
        "frozen_catalogue",
        "live_resolution",
        "iteminfo_payload",
        "iteminfo_header",
    )
    authored_labels = (
        *common_labels,
        "stringinfo_payload",
        "stringinfo_header",
        "active_part_prefab_table",
        "authoritative_prefab",
    )

    first_facts = {
        "catalogue_identity": "cd_boss_reward_bigmoney.pac",
        "owner_item_ids": [1002142],
        "owner_record_ids": ["0928-1002142"],
        "item_row_sha256s": {"1002142": row_hashes[1002142]},
        "item_type": 4_001,
        "equip_type_key": 0,
        "equipment_slot_count": 0,
        "icon_only_false_positive": True,
    }
    excluded = {
        "schema": EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA,
        "review_unit_id": first_unit,
        "disposition": "EXCLUDED_CATALOGUE_DEFECT",
        "source_facts": first_facts,
        "source_evidence": [packet[label] for label in common_labels],
    }
    with pytest.raises(ValueError, match="not the authoritative audited payload"):
        record_equipment_review_units(
            tmp_path,
            [first_unit],
            verdict="EXCLUDED_CATALOGUE_DEFECT",
            observations="Self-hashed parser fixtures are not authoritative source.",
            disposition_evidence=excluded,
        )

    monkeypatch.setattr(
        equipment_review,
        "_AUTHORITATIVE_SOURCE_SHA256",
        {
            label: packet[label]["sha256"]
            for label in authored_labels
        },
    )
    with pytest.raises(ValueError, match="parser-derived source packet facts"):
        record_equipment_review_units(
            tmp_path,
            [first_unit],
            verdict="EXCLUDED_CATALOGUE_DEFECT",
            observations="Asserted facts cannot override the parsed ItemInfo row.",
            disposition_evidence={
                **excluded,
                "source_facts": {**first_facts, "item_type": 108},
            },
        )
    record_equipment_review_units(
        tmp_path,
        [first_unit],
        verdict="EXCLUDED_CATALOGUE_DEFECT",
        observations="The frozen source proves this is not equipment.",
        disposition_evidence=excluded,
    )

    _assert_reviewed_source_dispositions_invalidate_on_change(index, tmp_path, packet, excluded, authored_labels, row_hashes, parsed_empty_hash, prefab_path)


def test_review_index_accepts_idempotently_finalized_source_only_capture(
    tmp_path: Path,
) -> None:
    assets = [
        _write_source_only_asset(
            tmp_path,
            0,
            status="source_only_reviewed",
        )
    ]
    _write_capture_manifest(tmp_path, assets)

    index = build_equipment_review_index(tmp_path, expected_asset_count=1)

    assert index["source_only_asset_count"] == 1
    assert index["assets"][0]["capture_status"] == "source_only_reviewed"
