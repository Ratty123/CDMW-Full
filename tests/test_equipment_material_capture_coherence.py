from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.mesh_harness.equipment_material_capture as capture
import tools.mesh_harness.equipment_material_capture_merge as merge
from tools.mesh_harness.equipment_material_capture import (
    EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
    EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA,
    EQUIPMENT_CAPTURE_SCHEMA,
    _canonical_json_sha256,
    _capture_identity_stamp,
    _capture_slice,
    _load_capture_state,
    _new_capture_state,
    _sha256_file,
    _valid_published_asset,
    build_capture_census_identity,
    build_capture_harness_fingerprint,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_capture_harness_fingerprint_is_path_sorted_and_content_sensitive(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "nested" / "b.py"
    first.write_text("FIRST = 1\n", encoding="utf-8")
    second.parent.mkdir()
    second.write_text("SECOND = 2\n", encoding="utf-8")

    initial = build_capture_harness_fingerprint(
        tmp_path, source_paths=("nested/b.py", "a.py")
    )
    reordered = build_capture_harness_fingerprint(
        tmp_path, source_paths=("a.py", "nested/b.py")
    )
    assert initial == reordered
    assert [row["path"] for row in initial["files"]] == ["a.py", "nested/b.py"]

    second.write_text("SECOND = 3\n", encoding="utf-8")
    changed = build_capture_harness_fingerprint(
        tmp_path, source_paths=("a.py", "nested/b.py")
    )
    assert changed["sha256"] != initial["sha256"]


def test_source_evidence_keeps_resolved_graph_edge_without_visible_batch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native" / "graph-only.dds"
    source.parent.mkdir()
    source.write_bytes(b"DDS graph-only source")
    parameter = {
        "parameter_kind": "texture",
        "component_scope_id": "character/model/component-b.pac#model-property:0",
        "owner_wrapper_item_id": "657",
        "parameter_name": "_normalTexture",
        "texture_path": "character/texture/blade_n.dds",
        "texture_resolved": True,
        "resolved_source_path": str(source),
        "resolved_archive_path": "character/texture/blade_n.dds",
        "source_resolution": "declared_exact",
        "semantic_type": "normal",
        "packed_channels": "xyz",
        "srgb_mode": "linear",
        "role": "normal",
        "sidecar_kind": ".pac_xml",
    }
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 1,
            "parameters": [parameter],
        },
        "batches": [],
    }

    textures, material_state = capture._publish_material_source_evidence(
        manifest,
        source_cache_root=tmp_path / "source-cache",
    )

    assert len(textures) == 1
    assert textures[0]["submesh_index"] == -1
    assert textures[0]["submesh_indices"] == []
    assert textures[0]["resolved_archive_path"] == parameter["texture_path"]
    assert textures[0]["source_resolution"] == "declared_exact"
    assert Path(textures[0]["source_path"]).read_bytes() == source.read_bytes()
    assert material_state["unassigned_parameters"] == [parameter]


def test_source_evidence_preserves_null_texture_parameter_without_making_dds_edge(
    tmp_path: Path,
) -> None:
    null_texture = {
        "parameter_kind": "texture",
        "component_scope_id": "character/model/component-a.pac#model-property:0",
        "owner_wrapper_item_id": "39",
        "parameter_name": "_heightTexture",
        "texture_path": "",
        "texture_resolved": False,
        "status": "transported_null_texture",
    }
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 0,
            "parameters": [null_texture],
        },
        "batches": [],
    }

    textures, material_state = capture._publish_material_source_evidence(
        manifest,
        source_cache_root=tmp_path / "source-cache",
    )

    assert textures == []
    assert material_state["parameters"] == [null_texture]
    assert material_state["unassigned_parameters"] == [null_texture]


def test_graph_source_board_coverage_is_exact_and_relativized(
    tmp_path: Path,
) -> None:
    visible = tmp_path / "source-boards" / "asset" / "submesh-000.png"
    graph_a = tmp_path / "source-boards" / "asset" / "graph-000.png"
    graph_b = tmp_path / "source-boards" / "asset" / "graph-001.png"
    manifest = tmp_path / "source-boards" / "asset" / "manifest.json"
    for path, value in ((graph_a, b"graph a"), (graph_b, b"graph b")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def graph_edge(ordinal: int) -> dict[str, object]:
        return {
            "source_texture_ordinal": ordinal,
            "component_scope_id": (
                f"character/model/component-{ordinal}.pac#model-property:0"
            ),
            "owner_wrapper_item_id": str(100 + ordinal),
            "material_wrapper_index": ordinal,
            "parameter_name": f"_graph{ordinal}",
            "declared_archive_path": f"texture/declared-{ordinal}.dds",
            "resolved_archive_path": f"texture/resolved-{ordinal}.dds",
            "source_resolution": "declared_exact",
            "source_sha256": f"{ordinal:064x}",
        }

    source_boards = {
        "schema": "source-board-v2",
        "asset_id": "asset",
        "manifest_path": str(manifest),
        "boards": [{"submesh_index": 0, "path": str(visible)}],
        "graph_boards": [
            {
                "path": str(graph_a),
                "sha256": capture._sha256_file(graph_a),
                "graph_board_index": 0,
                "shard_index": 0,
                "shard_count": 2,
                "texture_count": 1,
                "source_texture_ordinals": [1],
                "logical_edges": [graph_edge(1)],
            },
            {
                "path": str(graph_b),
                "sha256": capture._sha256_file(graph_b),
                "graph_board_index": 1,
                "shard_index": 1,
                "shard_count": 2,
                "texture_count": 1,
                "source_texture_ordinals": [3],
                "logical_edges": [graph_edge(3)],
            },
        ],
        "textures": [
            {"source_texture_ordinal": 0, "submesh_indices": [0]},
            {**graph_edge(1), "submesh_indices": []},
            {"source_texture_ordinal": 2, "submesh_indices": [-1, 0]},
            {**graph_edge(3), "submesh_index": -1},
        ],
        "materials": [],
        "parameters": [],
        "unassigned_parameters": [],
    }

    assert capture._graph_source_board_coverage_complete(source_boards) is True
    portable = capture._relativize_source_board_manifest(source_boards, tmp_path)
    assert portable["boards"][0]["path"] == (
        "source-boards/asset/submesh-000.png"
    )
    assert [row["path"] for row in portable["graph_boards"]] == [
        "source-boards/asset/graph-000.png",
        "source-boards/asset/graph-001.png",
    ]

    original_edge = source_boards["graph_boards"][1]["logical_edges"][0]
    source_boards["graph_boards"][1]["logical_edges"] = [
        {
            **original_edge,
            "component_scope_id": "character/model/wrong-component.pac#model-property:0",
        }
    ]
    assert capture._graph_source_board_coverage_complete(source_boards) is False
    source_boards["graph_boards"][1]["logical_edges"] = [original_edge]

    source_boards["graph_boards"][1]["logical_edges"] = [graph_edge(4)]
    assert capture._graph_source_board_coverage_complete(source_boards) is False


def test_source_evidence_matches_batch_by_declared_path_after_source_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native" / "default.dds"
    source.parent.mkdir()
    source.write_bytes(b"DDS technique default")
    declared = "character/texture/missing_overlay.dds"
    resolved = "texture/nonetexture0xff888888.dds"
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 1,
            "parameters": [
                {
                    "parameter_kind": "texture",
                    "component_scope_id": (
                        "character/model/guard.pac#model-property:0"
                    ),
                    "owner_wrapper_item_id": "92",
                    "material_wrapper_index": 0,
                    "parameter_name": "_overlayColorTexture",
                    "texture_path": declared,
                    "texture_resolved": True,
                    "resolved_source_path": str(source),
                    "resolved_archive_path": resolved,
                    "source_resolution": (
                        "technique_default_after_missing_declared_source"
                    ),
                    "declared_source_missing": True,
                }
            ],
        },
        "batches": [
            {
                "index": 3,
                "component_scope_id": "character/model/guard.pac#model-property:0",
                "material_name": "guard",
                "dds_textures": {
                    "material_inputs": [
                        {
                            "component_scope_id": (
                                "character/model/guard.pac#model-property:0"
                            ),
                            "owner_wrapper_item_id": "92",
                            "material_wrapper_index": 0,
                            "parameter_name": "_overlayColorTexture",
                            "declared_texture_path": declared,
                            "archive_path": resolved,
                            "source_path": str(source),
                            "source_resolution": (
                                "technique_default_after_missing_declared_source"
                            ),
                            "declared_source_missing": True,
                        }
                    ]
                },
            }
        ],
    }

    textures, _material_state = capture._publish_material_source_evidence(
        manifest,
        source_cache_root=tmp_path / "source-cache",
    )

    assert textures[0]["submesh_indices"] == [3]
    assert textures[0]["declared_archive_path"] == declared
    assert textures[0]["resolved_archive_path"] == resolved
    assert textures[0]["declared_source_missing"] is True


def test_source_evidence_keeps_colliding_local_owner_edges_component_scoped(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native" / "shared.dds"
    source.parent.mkdir()
    source.write_bytes(b"DDS shared source")
    declared = "character/texture/shared.dds"
    scopes = (
        "character/model/component-a.pac#model-property:0",
        "character/model/component-b.pac#model-property:0",
    )

    def parameter(scope: str) -> dict[str, object]:
        return {
            "parameter_kind": "texture",
            "component_scope_id": scope,
            "owner_wrapper_item_id": "1190",
            "material_wrapper_index": 0,
            "parameter_name": "_detailMaskTexture",
            "texture_path": declared,
            "texture_resolved": True,
            "resolved_source_path": str(source),
        }

    descriptor = {
        "component_scope_id": scopes[0],
        "owner_wrapper_item_id": "1190",
        "material_wrapper_index": 0,
        "parameter_name": "_detailMaskTexture",
        "declared_texture_path": declared,
        "archive_path": declared,
        "source_path": str(source),
    }
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 2,
            "parameters": [parameter(scopes[0]), parameter(scopes[1])],
        },
        "batches": [
            {
                "index": 0,
                "component_scope_id": scopes[0],
                "material_name": "component-a",
                "dds_textures": {"material_inputs": [descriptor]},
            }
        ],
    }

    textures, material_state = capture._publish_material_source_evidence(
        manifest,
        source_cache_root=tmp_path / "source-cache",
    )

    assert [row["component_scope_id"] for row in textures] == list(scopes)
    assert [row["submesh_indices"] for row in textures] == [[0], []]
    assert [
        row["component_scope_id"]
        for row in material_state["submeshes"][0]["pac_xml_parameters"]
    ] == [scopes[0]]
    assert [
        row["component_scope_id"] for row in material_state["unassigned_parameters"]
    ] == [scopes[1]]


def test_component_identity_validation_distinguishes_component_local_owners() -> None:
    declared = "character/texture/shared.dds"

    def parameter(scope: str) -> dict[str, object]:
        return {
            "parameter_kind": "texture",
            "component_scope_id": scope,
            "owner_wrapper_item_id": "1190",
            "material_wrapper_index": 0,
            "parameter_name": "_detailMaskTexture",
            "texture_path": declared,
        }

    first = "character/model/component-a.pac#model-property:0"
    second = "character/model/component-b.pac#model-property:0"
    manifest = {
        "material_conservation": {
            "parameters": [parameter(first), parameter(second)]
        },
        "batches": [],
    }

    assert capture._component_scoped_native_material_identity_complete(manifest)
    manifest["material_conservation"]["parameters"][1]["component_scope_id"] = first
    assert not capture._component_scoped_native_material_identity_complete(manifest)


def test_source_evidence_rejects_cross_component_renderer_descriptor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "native" / "shared.dds"
    source.parent.mkdir()
    source.write_bytes(b"DDS shared source")
    declared = "character/texture/shared.dds"
    parameter_scope = "character/model/component-a.pac#model-property:0"
    descriptor_scope = "character/model/component-b.pac#model-property:0"
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 1,
            "parameters": [
                {
                    "parameter_kind": "texture",
                    "component_scope_id": parameter_scope,
                    "owner_wrapper_item_id": "1190",
                    "material_wrapper_index": 0,
                    "parameter_name": "_detailMaskTexture",
                    "texture_path": declared,
                    "texture_resolved": True,
                    "resolved_source_path": str(source),
                }
            ],
        },
        "batches": [
            {
                "index": 0,
                "component_scope_id": descriptor_scope,
                "dds_textures": {
                    "material_inputs": [
                        {
                            "component_scope_id": descriptor_scope,
                            "owner_wrapper_item_id": "1190",
                            "material_wrapper_index": 0,
                            "parameter_name": "_detailMaskTexture",
                            "declared_texture_path": declared,
                            "archive_path": declared,
                            "source_path": str(source),
                        }
                    ]
                },
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="without a matching component-scoped conservation edge",
    ):
        capture._publish_material_source_evidence(
            manifest,
            source_cache_root=tmp_path / "source-cache",
        )


def test_resume_and_asset_validity_reject_another_run_or_harness(
    tmp_path: Path,
) -> None:
    identity = _fake_identity("shared-run", harness_sha="1" * 64)
    changed = _fake_identity("shared-run", harness_sha="2" * 64)
    resolution = {"resolution_sha256": "resolution"}
    state_path = tmp_path / "capture-run-state.json"
    state = _new_capture_state(
        resolution,
        census_identity=identity,
        capture_slice=_capture_slice(0, 1, 1),
    )
    _write_json(state_path, state)
    with pytest.raises(ValueError, match="another census run or capture harness"):
        _load_capture_state(
            state_path,
            resolution,
            expected_census_identity=changed,
            expected_capture_slice=_capture_slice(0, 1, 1),
        )

    asset_root = tmp_path / "asset"
    report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "identity": "example.pac",
        "asset_id": "0000-example",
        "catalogue_ordinal": 0,
        "status": "captured",
        "technical_gates": {"valid": True},
        **_capture_identity_stamp(identity),
    }
    _write_json(asset_root / "asset-report.json", report)
    assert _valid_published_asset(
        asset_root,
        identity="example.pac",
        expected_binaries=identity["capture_binaries"],
        expected_census_identity=identity,
    ) == report
    assert (
        _valid_published_asset(
            asset_root,
            identity="example.pac",
            expected_binaries=identity["capture_binaries"],
            expected_census_identity=changed,
        )
        is None
    )


def test_no_resume_starts_fresh_and_does_not_publish_stale_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalogue = {
        "schema": "catalogue-v1",
        "selection": {"selection_sha256": "selection"},
    }
    resolution = {
        "schema": "resolution-v1",
        "resolution_sha256": "resolution",
        "live_archive": {"generation_fingerprint": "archive"},
    }
    catalogue_path = tmp_path / "catalogue.json"
    resolution_path = tmp_path / "resolution.json"
    _write_json(catalogue_path, catalogue)
    _write_json(resolution_path, resolution)
    helper = tmp_path / "rust.exe"
    helper.write_bytes(b"rust")
    plan = {"ordinal": 0, "asset_id": "0000-stale", "identity": "stale.pac"}
    harness_payload = {
        "schema": EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
        "files": [{"path": "capture.py", "bytes": 1, "sha256": "c" * 64}],
    }
    harness = {
        **harness_payload,
        "sha256": _canonical_json_sha256(harness_payload),
    }
    binaries = {
        "preview_core": {"path": "preview.exe", "bytes": 10, "sha256": "a" * 64},
        "rust_helper": {"path": str(helper), "bytes": 4, "sha256": "b" * 64},
    }
    identity = build_capture_census_identity(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        catalogue=catalogue,
        resolution=resolution,
        census_run_id="same-explicit-run",
        capture_harness=harness,
        capture_binaries=binaries,
    )
    output_root = tmp_path / "evidence"
    stale_report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "identity": plan["identity"],
        "asset_id": plan["asset_id"],
        "catalogue_ordinal": 0,
        "status": "captured",
        "technical_gates": {"valid": True},
        **_capture_identity_stamp(identity),
    }
    _write_json(
        output_root / "assets" / plan["asset_id"] / "asset-report.json",
        stale_report,
    )
    stale_state = _new_capture_state(
        resolution,
        census_identity=identity,
        capture_slice=_capture_slice(0, 1, 1),
    )
    stale_state["assets"] = {
        plan["identity"]: {
            "ordinal": 0,
            "asset_id": plan["asset_id"],
            "status": "captured",
            "error": "",
        }
    }
    _write_json(output_root / "capture-run-state.json", stale_state)
    monkeypatch.setattr(
        capture,
        "load_equipment_capture_inputs",
        lambda *_args: (catalogue, resolution),
    )
    monkeypatch.setattr(
        capture, "build_equipment_capture_plans", lambda *_args: (plan,)
    )
    monkeypatch.setattr(capture, "resolve_capture_binary_evidence", lambda *_: binaries)
    monkeypatch.setattr(capture, "build_capture_harness_fingerprint", lambda: harness)
    monkeypatch.setattr(capture, "EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT", 1)

    manifest = capture.run_equipment_material_capture(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        output_root=output_root,
        cache_root=tmp_path / "cache",
        rust_helper=helper,
        limit=0,
        resume=False,
        census_run_id="same-explicit-run",
    )

    fresh_state = json.loads(
        (output_root / "capture-run-state.json").read_text(encoding="utf-8")
    )
    assert fresh_state["assets"] == {}
    assert fresh_state["capture_slice"] == _capture_slice(0, 0, 1)
    assert manifest["status_counts"] == {"missing": 1}
    assert manifest["assets"][0]["report"] == ""


def test_three_shards_assemble_only_with_exact_ordinal_and_report_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _assembly_fixture(monkeypatch, tmp_path)
    shards = [fixture["write_shard"](index, index, index + 1) for index in range(3)]
    destination = tmp_path / "assembled"

    manifest = merge.assemble_equipment_material_capture(
        catalogue_path=fixture["catalogue_path"],
        resolution_path=fixture["resolution_path"],
        shard_roots=shards,
        output_root=destination,
    )

    assert manifest["capture_complete"] is True
    assert manifest["status_counts"] == {"captured": 3}
    assert manifest["assembly"]["ordinal_coverage"] == {
        "first": 0,
        "last": 2,
        "count": 3,
        "sha256": manifest["assembly"]["ordinal_coverage"]["sha256"],
    }
    assert manifest["assembly"]["source_cache"]["copied"] is False
    assert (destination / "catalogue.json").read_bytes() == Path(
        fixture["catalogue_path"]
    ).read_bytes()
    assert (destination / "resolution.json").read_bytes() == Path(
        fixture["resolution_path"]
    ).read_bytes()
    assert manifest["assembly"]["frozen_inputs"]["catalogue"]["path"] == (
        "catalogue.json"
    )
    assembled_state = json.loads(
        (destination / "capture-run-state.json").read_text(encoding="utf-8")
    )
    assert assembled_state["assembly"] == manifest["assembly"]
    assert [path.name for path in sorted((destination / "assets").iterdir())] == [
        "0000-asset-0",
        "0001-asset-1",
        "0002-asset-2",
    ]


def test_assembly_rejects_report_tampering_gaps_and_existing_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _assembly_fixture(monkeypatch, tmp_path)
    shards = [fixture["write_shard"](index, index, index + 1) for index in range(3)]
    tampered = shards[1] / "assets" / "0001-asset-1" / "asset-report.json"
    tampered.write_text(tampered.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="report SHA mismatch"):
        merge.assemble_equipment_material_capture(
            catalogue_path=fixture["catalogue_path"],
            resolution_path=fixture["resolution_path"],
            shard_roots=shards,
            output_root=tmp_path / "tampered-output",
        )

    clean_root = tmp_path / "clean"
    clean_shards = [
        fixture["write_shard"](10 + index, index, index + 1)
        for index in range(3)
    ]
    existing = clean_root / "existing-output"
    existing.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="must be a new path"):
        merge.assemble_equipment_material_capture(
            catalogue_path=fixture["catalogue_path"],
            resolution_path=fixture["resolution_path"],
            shard_roots=clean_shards,
            output_root=existing,
        )

    duplicate = fixture["write_shard"](20, 1, 2)
    with pytest.raises(ValueError, match="Duplicate captured ordinal|cover every ordinal"):
        merge.assemble_equipment_material_capture(
            catalogue_path=fixture["catalogue_path"],
            resolution_path=fixture["resolution_path"],
            shard_roots=(clean_shards[0], clean_shards[1], duplicate),
            output_root=tmp_path / "gap-output",
        )


def _assembly_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, object]:
    catalogue = {
        "schema": "catalogue-v1",
        "selection": {"selection_sha256": "selection"},
    }
    resolution = {
        "schema": "resolution-v1",
        "resolution_sha256": "resolution",
        "live_archive": {"generation_fingerprint": "archive"},
    }
    catalogue_path = tmp_path / "catalogue.json"
    resolution_path = tmp_path / "resolution.json"
    _write_json(catalogue_path, catalogue)
    _write_json(resolution_path, resolution)
    plans = [
        {
            "ordinal": index,
            "asset_id": f"{index:04d}-asset-{index}",
            "identity": f"asset-{index}.pac",
        }
        for index in range(3)
    ]
    harness_payload = {
        "schema": EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
        "files": [{"path": "capture.py", "bytes": 1, "sha256": "c" * 64}],
    }
    harness = {
        **harness_payload,
        "sha256": _canonical_json_sha256(harness_payload),
    }
    binaries = {
        "preview_core": {"path": "preview.exe", "bytes": 10, "sha256": "a" * 64},
        "rust_helper": {"path": "rust.exe", "bytes": 20, "sha256": "b" * 64},
    }
    identity = build_capture_census_identity(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        catalogue=catalogue,
        resolution=resolution,
        census_run_id="shared-run",
        capture_harness=harness,
        capture_binaries=binaries,
    )
    monkeypatch.setattr(
        merge,
        "load_equipment_capture_inputs",
        lambda *_args: (catalogue, resolution),
    )
    monkeypatch.setattr(
        merge,
        "build_equipment_capture_plans",
        lambda *_args: tuple(plans),
    )
    monkeypatch.setattr(merge, "EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT", 3)
    monkeypatch.setattr(capture, "EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT", 3)

    def write_shard(number: int, start: int, end: int) -> Path:
        root = tmp_path / f"shard-{number}"
        capture_slice = _capture_slice(start, end, len(plans))
        state_assets: dict[str, object] = {}
        manifest_assets: list[dict[str, object]] = []
        for ordinal, plan in enumerate(plans):
            if start <= ordinal < end:
                report = {
                    "schema": EQUIPMENT_CAPTURE_SCHEMA,
                    "identity": plan["identity"],
                    "asset_id": plan["asset_id"],
                    "catalogue_ordinal": ordinal,
                    "status": "captured",
                    "technical_gates": {"valid": True},
                    **_capture_identity_stamp(identity),
                }
                report_path = root / "assets" / plan["asset_id"] / "asset-report.json"
                _write_json(report_path, report)
                report_sha256 = _sha256_file(report_path)
                state_assets[plan["identity"]] = {
                    "ordinal": ordinal,
                    "asset_id": plan["asset_id"],
                    "status": "captured",
                    "error": "",
                }
                status = "captured"
            else:
                report_path = Path()
                report_sha256 = ""
                status = "missing"
            manifest_assets.append(
                {
                    "ordinal": ordinal,
                    "asset_id": plan["asset_id"],
                    "identity": plan["identity"],
                    "status": status,
                    "report": str(report_path) if report_sha256 else "",
                    "report_sha256": report_sha256,
                    "error": "",
                }
            )
        state = {
            "schema": EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA,
            "resolution_sha256": resolution["resolution_sha256"],
            **_capture_identity_stamp(identity),
            "capture_slice": capture_slice,
            "assets": state_assets,
        }
        counts = {"captured": end - start, "missing": len(plans) - (end - start)}
        manifest = {
            "schema": EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
            **_capture_identity_stamp(identity),
            "capture_slice": capture_slice,
            "status_counts": counts,
            "assets": manifest_assets,
        }
        binary_manifest = {
            "schema": EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA,
            **_capture_identity_stamp(identity),
        }
        _write_json(root / "capture-run-state.json", state)
        _write_json(root / "capture-manifest.json", manifest)
        _write_json(root / "capture-binaries.json", binary_manifest)
        return root

    return {
        "catalogue_path": catalogue_path,
        "resolution_path": resolution_path,
        "write_shard": write_shard,
    }


def _fake_identity(run_id: str, *, harness_sha: str) -> dict[str, object]:
    return {
        "schema": capture.EQUIPMENT_CAPTURE_IDENTITY_SCHEMA,
        "census_run_id": run_id,
        "catalogue": {},
        "resolution": {},
        "archive": {},
        "capture_binaries": {
            "preview_core": {"sha256": "a" * 64, "bytes": 10},
            "rust_helper": {"sha256": "b" * 64, "bytes": 20},
        },
        "capture_harness": {
            "schema": EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
            "sha256": harness_sha,
            "files": [],
        },
    }
