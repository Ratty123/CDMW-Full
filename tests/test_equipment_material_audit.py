from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from tools.mesh_harness.equipment_archive_resolution import (
    _active_entries_by_path,
    _fallback_model_basenames,
    _fallback_prefab_basenames,
    prefab_candidate_basenames,
    resolve_live_equipment_catalogue,
)
from tools.mesh_harness.equipment_archive_worker import (
    AuditArchiveSession,
    AuditArchiveWorkerClient,
)
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
    EQUIPMENT_AUDIT_GENERATION_ID,
    EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    EQUIPMENT_AUDIT_RECORD_COUNT,
    EQUIPMENT_AUDIT_RHETT_ITEM_ID,
    FrozenEquipmentCatalogue,
    _logical_identity_rows,
    build_frozen_equipment_catalogue,
    equipment_audit_generation_path,
    write_frozen_equipment_catalogue,
)
from tools.mesh_harness.equipment_material_capture import (
    EQUIPMENT_CAPTURE_SCHEMA,
    FULL_MODEL_VIEWS,
    _capture_report_ok,
    _publish_material_source_evidence,
    _relativize_source_board_manifest,
    _report_dds_dedup_ok,
    _valid_published_asset,
    _validate_native_manifest,
    build_equipment_capture_manifest,
    build_equipment_capture_plans,
    equipment_archive_paths_from_resolution,
)
from tools.mesh_harness.equipment_material_review import (
    _RENDER_REQUIRED_TECHNICAL_GATES,
    build_equipment_review_index,
    record_equipment_review_pages,
    summarize_equipment_review,
)


def test_frozen_equipment_catalogue_exact_local_snapshot(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    generation = equipment_audit_generation_path(repository_root)
    if not generation.is_dir():
        pytest.skip("The hash-pinned local catalogue generation is not present.")

    catalogue = build_frozen_equipment_catalogue(generation)

    assert catalogue.source_sha256 == EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256
    assert len(catalogue.records) == EQUIPMENT_AUDIT_RECORD_COUNT
    assert len(catalogue.logical_models) == EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT
    assert catalogue.payload["schema"] == EQUIPMENT_AUDIT_CATALOGUE_SCHEMA
    assert catalogue.payload["selection"] == {
        "rule": "category == Armor OR group in [Sword, Axe / Mace / Hammer]",
        "category_counts": {"Armor": 2158},
        "group_counts": {"Axe / Mace / Hammer": 114, "Sword": 62},
        "record_count": 2334,
        "logical_pac_edge_count": 2400,
        "unique_logical_pac_count": 2057,
        "icon_edge_count": 3069,
        "unique_icon_count": 2337,
        "selection_sha256": catalogue.payload["selection"]["selection_sha256"],
    }
    assert catalogue.payload["canonical_item"] == {
        "record_id": next(
            row["record_id"]
            for row in catalogue.records
            if row["item_id"] == EQUIPMENT_AUDIT_RHETT_ITEM_ID
        ),
        "item_id": 240026,
        "internal_name": "Rayhorn_TwoHandSword",
        "display_name": "Rhett's Longsword",
        "logical_pac": "cd_phm_02_sword_0009.pac",
        "icon_path": "ui/texture/icon/itemicon_prefab_cd_phm_02_sword_0009.dds",
    }

    destination = write_frozen_equipment_catalogue(
        catalogue,
        tmp_path / "catalogue.json",
    )
    assert json.loads(destination.read_text(encoding="utf-8")) == catalogue.payload


def test_equipment_catalogue_logical_identity_preserves_all_edges() -> None:
    records = (
        {
            "record_id": "0001-11",
            "item_id": 11,
            "pac_files": ["folder/Shared.PAC", "first-only.pac"],
            "icon_paths": [],
        },
        {
            "record_id": "0002-12",
            "item_id": 12,
            "pac_files": ["different/path/shared.pac"],
            "icon_paths": [],
        },
    )

    logical = _logical_identity_rows(records, source_key="pac_files")

    assert [row["identity"] for row in logical] == ["first-only.pac", "shared.pac"]
    shared = logical[1]
    assert shared["owner_count"] == 2
    assert [owner["edge_index"] for owner in shared["owners"]] == [0, 2]
    assert [owner["declared_path"] for owner in shared["owners"]] == [
        "folder/Shared.PAC",
        "different/path/shared.pac",
    ]


def test_equipment_catalogue_refuses_a_different_generation(tmp_path: Path) -> None:
    generation = tmp_path / "generations" / "newer-generation"
    generation.mkdir(parents=True)

    with pytest.raises(ValueError, match=EQUIPMENT_AUDIT_GENERATION_ID):
        build_frozen_equipment_catalogue(generation)


def test_equipment_audit_worker_client_uses_bounded_headless_protocol(
    tmp_path: Path,
) -> None:
    stub = Path(__file__).parent / "helpers" / "archive_backend_worker_stub.py"
    progress: list[tuple[str, object]] = []
    cache_root = tmp_path / "cache"

    with AuditArchiveWorkerClient(
        (sys.executable, stub),
        cache_root=cache_root,
        progress=lambda status, payload: progress.append((status, dict(payload))),
    ) as client:
        session = client.open_archive(tmp_path)
        assert session.session_id == "session-stub"
        assert session.cache_hit is True
        assert session.entry_count == 1
        assert client.resolve_values("basenames", ("example.pac",)) == ()
        assert 60_000 <= len(client.stderr_tail.encode("utf-8")) <= 65_536

    operations = (
        (cache_root / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    )
    assert operations == ["ping", "open_archive", "resolve_entries", "shutdown"]
    assert [status for status, _payload in progress].count("started") == 4


def _worker_row(path: str, entry_id: int, *, active: bool = False) -> dict[str, object]:
    extension = Path(path).suffix.lower()
    return {
        "session_id": "audit-session",
        "entry_id": entry_id,
        "identity": {
            "normalized_path": path.casefold(),
            "source_pamt": "C:/game/0009/0.pamt",
            "paz_index": 1,
            "archive_offset": entry_id * 100,
        },
        "path": path,
        "source_pamt": "C:/game/0009/0.pamt",
        "paz_file": "C:/game/0009/1.paz",
        "paz_index": 1,
        "offset": entry_id * 100,
        "stored_size": 10,
        "original_size": 20,
        "flags": 2,
        "extension": extension,
        "is_active_override": active,
        "override_state": "Active original" if active else "",
    }


def test_live_equipment_resolution_keeps_direct_and_prefab_logical_identities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    direct = _worker_row("character/model/direct.pac", 1)
    prefab = _worker_row("character/bin__/prefab/missing.prefab", 2)
    physical = _worker_row("character/model/physical.pac", 3)
    icon = _worker_row("ui/texture/icon/itemicon_direct.dds", 4)

    class Worker:
        session = AuditArchiveSession(
            session_id="audit-session",
            package_root=tmp_path,
            fingerprint="f" * 64,
            entry_count=100,
            index_version=3,
            cache_hit=True,
        )

        def resolve_values(
            self, kind: str, values: object, **_kwargs: object
        ) -> tuple[dict[str, object], ...]:
            requested = {str(value).casefold() for value in values}
            rows = (direct, prefab, physical, icon)
            if kind == "exact_paths":
                return tuple(
                    row for row in rows if str(row["path"]).casefold() in requested
                )
            return tuple(
                row
                for row in rows
                if Path(str(row["path"])).name.casefold() in requested
            )

    records = (
        {
            "record_id": "0001-1",
            "source_index": 1,
            "item_id": 1,
            "pac_files": ["direct.pac"],
            "icon_paths": ["ui/texture/icon/itemicon_direct.dds"],
        },
        {
            "record_id": "0002-2",
            "source_index": 2,
            "item_id": 2,
            "pac_files": ["missing.pac"],
            "icon_paths": [],
        },
    )
    logical_models = _logical_identity_rows(records, source_key="pac_files")
    icons = _logical_identity_rows(records, source_key="icon_paths")
    catalogue = FrozenEquipmentCatalogue(
        source_path=tmp_path / "catalogue.json",
        source_sha256="c" * 64,
        records=records,
        logical_models=tuple(logical_models),
        icons=tuple(icons),
        payload={
            "schema": EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
            "selection": {"selection_sha256": "s" * 64},
        },
    )
    monkeypatch.setattr(
        "tools.mesh_harness.equipment_archive_resolution.EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
        2,
    )

    resolution = resolve_live_equipment_catalogue(
        catalogue,
        Worker(),  # type: ignore[arg-type]
        prefab_reader=lambda row: (
            (
                {
                    "path": "character/model/physical.pac",
                    "role": "prefab_skinned_model_resource",
                    "confidence": "prefab_binary_reference",
                    "source_field": "_skinnedMeshFile",
                    "model_property_index": 7,
                },
            )
            if row["path"] == prefab["path"]
            else ()
        ),
    )

    assert resolution["counts"] == {
        "logical_models": 2,
        "logical_model_statuses": {"direct": 1, "prefab_binary_reference": 1},
        "unresolved_logical_models": 0,
        "physical_component_edges": 2,
        "unique_physical_entries": 2,
        "prefabs_decoded": 1,
        "prefab_decode_errors": 0,
        "icons": 1,
        "unresolved_icons": 0,
    }
    by_identity = {row["identity"]: row for row in resolution["logical_models"]}
    assert by_identity["direct.pac"]["physical_components"][0]["is_primary"] is True
    missing_component = by_identity["missing.pac"]["physical_components"][0]
    assert missing_component["entry"]["path"] == "character/model/physical.pac"
    assert missing_component["model_property_indices"] == [7]


def test_prefab_candidates_and_active_override_match_preview_core_contract() -> None:
    candidates = prefab_candidate_basenames("folder/example_ub_acc_0001.pac")
    assert candidates[:4] == (
        "example_ub_acc_0001_s.prefab",
        "example_ub_acc_0001_l.prefab",
        "example_ub_acc_0001_r.prefab",
        "example_ub_acc_0001.prefab",
    )
    assert "example_ub_0001.prefab" in candidates
    assert "example_0001.prefab" in candidates

    shadowed = _worker_row("character/model/shared.pac", 10)
    shadowed["override_state"] = "Shadowed original"
    active = _worker_row("character/model/shared.pac", 11, active=True)
    assert _active_entries_by_path((shadowed, active)) == (active,)


def test_unresolved_variant_fallbacks_are_bounded_and_source_derived() -> None:
    assert _fallback_model_basenames(
        "cd_pgm_00_ub_00_0006_y.pac",
        ("cd_pgm_00_ub_00_0006_y",),
    ) == ("cd_pgm_00_ub_00_0006.pac",)
    assert _fallback_model_basenames(
        "cd_phm_m0001_00_samuel_cloak_0001_v.pac",
        ("cd_phm_m0001_00_samuel_cloak_0001_v",),
    ) == (
        "cd_phm_m0001_00_samuel_cloak_0001.pac",
        "cd_m0001_00_samuel_cloak_0001_v.pac",
        "cd_m0001_00_samuel_cloak_0001.pac",
    )
    assert "cd_phm_00_hel_0142_03_dd.prefab" in _fallback_prefab_basenames(
        "cd_phm_00_hel_0142_03.pac",
        ("cd_phm_00_hel_0142_03",),
    )


def test_live_resolution_uses_only_owner_stems_for_their_logical_pac(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_prefab = _worker_row("character/bin__/prefab/first_index01_d.prefab", 20)
    second_prefab = _worker_row("character/bin__/prefab/second_t.prefab", 21)
    first_physical = _worker_row("character/model/first_physical.pac", 22)
    second_physical = _worker_row("character/model/second_physical.pac", 23)

    class Worker:
        session = AuditArchiveSession(
            session_id="audit-session",
            package_root=tmp_path,
            fingerprint="f" * 64,
            entry_count=100,
            index_version=3,
            cache_hit=True,
        )

        def resolve_values(
            self, kind: str, values: object, **_kwargs: object
        ) -> tuple[dict[str, object], ...]:
            requested = {str(value).casefold() for value in values}
            rows = (first_prefab, second_prefab, first_physical, second_physical)
            if kind == "exact_paths":
                return tuple(
                    row for row in rows if str(row["path"]).casefold() in requested
                )
            return tuple(
                row
                for row in rows
                if Path(str(row["path"])).name.casefold() in requested
            )

    records = (
        {
            "record_id": "0001-1",
            "source_index": 1,
            "item_id": 1,
            "model_stems": ["first_index01_d", "second_t"],
            "pac_files": ["first.pac", "second.pac"],
            "icon_paths": [],
        },
    )
    catalogue = FrozenEquipmentCatalogue(
        source_path=tmp_path / "catalogue.json",
        source_sha256="c" * 64,
        records=records,
        logical_models=tuple(_logical_identity_rows(records, source_key="pac_files")),
        icons=(),
        payload={
            "schema": EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
            "selection": {"selection_sha256": "s" * 64},
        },
    )
    monkeypatch.setattr(
        "tools.mesh_harness.equipment_archive_resolution.EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
        2,
    )

    resolution = resolve_live_equipment_catalogue(
        catalogue,
        Worker(),  # type: ignore[arg-type]
        prefab_reader=lambda row: (
            {
                "path": (
                    "character/model/first_physical.pac"
                    if row["path"] == first_prefab["path"]
                    else "character/model/second_physical.pac"
                ),
                "role": "prefab_model_resource",
                "confidence": "prefab_binary_reference",
            },
        ),
    )

    by_identity = {row["identity"]: row for row in resolution["logical_models"]}
    assert by_identity["first.pac"]["source_model_stems"] == ["first_index01_d"]
    assert [
        component["entry"]["path"]
        for component in by_identity["first.pac"]["physical_components"]
    ] == ["character/model/first_physical.pac"]
    assert by_identity["second.pac"]["source_model_stems"] == ["second_t"]
    assert [
        component["entry"]["path"]
        for component in by_identity["second.pac"]["physical_components"]
    ] == ["character/model/second_physical.pac"]


def test_capture_plan_preserves_every_owner_component_and_model_property_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "record_id": "0001-1",
        "item_id": 1,
        "icon_paths": ["ui/texture/icon/item.dds"],
    }
    primary = _worker_row("character/model/primary.pac", 30)
    component = _worker_row("character/model/component.pac", 31)
    catalogue = {"records": [record]}
    resolution = {
        "icons": [
            {
                "identity": "ui/texture/icon/item.dds",
                "owners": [{"record_id": "0001-1"}],
                "entries": [_worker_row("ui/texture/icon/item.dds", 32)],
            }
        ],
        "logical_models": [
            {
                "identity": "logical.pac",
                "declared_name": "logical.pac",
                "status": "prefab_binary_reference",
                "owners": [{"record_id": "0001-1", "item_id": 1}],
                "physical_components": [
                    {
                        "entry": primary,
                        "is_primary": True,
                        "model_property_indices": [],
                        "roles": ["logical_pac"],
                        "source_prefabs": ["logical.prefab"],
                    },
                    {
                        "entry": component,
                        "is_primary": False,
                        "model_property_indices": [7, 3, 7],
                        "roles": ["prefab_skinned_model_resource"],
                        "source_prefabs": ["logical.prefab"],
                    },
                ],
                "prefab_candidates": [],
                "prefab_edges": [],
            }
        ],
    }
    monkeypatch.setattr(
        "tools.mesh_harness.equipment_material_capture.EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
        1,
    )

    plan = build_equipment_capture_plans(catalogue, resolution)[0]

    assert plan["identity"] == "logical.pac"
    assert plan["owners"] == [{"record_id": "0001-1", "item_id": 1}]
    assert len(plan["physical_components"]) == 2
    assert plan["enabled_prefab_component_paths"] == [
        "character/model/primary.pac",
        "character/model/component.pac",
    ]
    assert plan["canonical_model_property_indices"] == {
        "character/model/component.pac": 3
    }
    assert plan["model_property_index_variants"][1]["model_property_indices"] == [3, 7]
    assert plan["icons"][0]["identity"] == "ui/texture/icon/item.dds"


def test_native_capture_gate_requires_exact_versions_conservation_and_identity() -> (
    None
):
    plan = {
        "primary_component": {
            "entry": {"path": "character/model/example.pac"},
        }
    }
    manifest = {
        "native_preview_core": {
            "runtime_backend": "native_cpp",
            "python_fallback_allowed": False,
            "material_graph_status": "active",
        },
        "schema_version": 8,
        "material_graph_version": 4,
        "material_semantics_version": 10,
        "source_path": "character/model/example.pac",
        "material_conservation": {
            "conserved": True,
            "declared_parameter_count": 1,
            "transported_parameter_count": 1,
            "resolved_texture_count": 0,
            "unresolved_texture_count": 0,
            "findings": [],
            "parameters": [
                {
                    "parameter_kind": "float",
                    "component_scope_id": (
                        "character/model/example.pac#model-property:0"
                    ),
                    "owner_wrapper_item_id": "model-property:0:wrapper:0",
                    "material_wrapper_index": 0,
                    "parameter_name": "_roughness",
                }
            ],
        },
        "rejected_candidates": ["normal rejected cross-wrapper candidate"],
    }

    gates = _validate_native_manifest(manifest, plan)

    assert gates and all(gates.values())
    manifest["material_conservation"]["transported_parameter_count"] = 0
    assert (
        _validate_native_manifest(manifest, plan)["parameter_count_conserved"] is False
    )
    manifest["material_conservation"]["transported_parameter_count"] = 1
    manifest["material_conservation"]["unresolved_texture_count"] = 1
    assert (
        _validate_native_manifest(manifest, plan)[
            "all_declared_texture_sources_resolved"
        ]
        is False
    )
    manifest["material_conservation"]["unresolved_texture_count"] = 0
    del manifest["material_conservation"]["parameters"][0]["component_scope_id"]
    assert (
        _validate_native_manifest(manifest, plan)[
            "component_scoped_material_identity"
        ]
        is False
    )


def test_source_evidence_preserves_all_parameters_and_repeated_submesh_ownership(
    tmp_path: Path,
) -> None:
    source = tmp_path / "shared.dds"
    source.write_bytes(b"DDS logical source")
    descriptor = {
        "component_scope_id": "character/model/shared.pac#model-property:0",
        "owner_wrapper_item_id": "42",
        "material_wrapper_index": 0,
        "parameter_name": "_detailMaskTexture",
        "archive_path": "character/texture/shared.dds",
        "source_path": str(source),
        "semantic_type": "material",
        "packed_channels": "rgba",
        "srgb_mode": "linear",
    }
    manifest = {
        "material_conservation": {
            "resolved_texture_count": 1,
            "parameters": [
                {
                    "parameter_kind": "texture",
                    "component_scope_id": (
                        "character/model/shared.pac#model-property:0"
                    ),
                    "parameter_name": "_detailMaskTexture",
                    "texture_path": "character/texture/shared.dds",
                    "owner_wrapper_item_id": "42",
                    "material_wrapper_index": 0,
                    "texture_resolved": True,
                    "logical_graph_edge": True,
                },
                {
                    "parameter_kind": "byte4",
                    "component_scope_id": (
                        "character/model/shared.pac#model-property:0"
                    ),
                    "parameter_name": "_dyeingTransformProperty0",
                    "integer_value": 4294967295,
                    "owner_wrapper_item_id": "42",
                    "material_wrapper_index": 0,
                },
                {
                    "parameter_kind": "color",
                    "component_scope_id": (
                        "character/model/shared.pac#model-property:0"
                    ),
                    "parameter_name": "_dyeingColorMaskR",
                    "value": "#1248ffff",
                    "owner_wrapper_item_id": "43",
                    "material_wrapper_index": 2,
                },
            ],
        },
        "batches": [
            {
                "index": 0,
                "component_scope_id": (
                    "character/model/shared.pac#model-property:0"
                ),
                "material_name": "shared-a",
                "dds_textures": {"material_inputs": [descriptor]},
                "material_layers": [
                    {
                        "owner_wrapper_item_id": "42",
                        "material_wrapper_index": 0,
                    }
                ],
            },
            {
                "index": 1,
                "component_scope_id": (
                    "character/model/shared.pac#model-property:0"
                ),
                "material_name": "shared-b",
                "dds_textures": {"material_inputs": [descriptor]},
                "material_layers": [
                    {
                        "owner_wrapper_item_id": "42",
                        "material_wrapper_index": 0,
                    }
                ],
            },
            {
                "index": 2,
                "component_scope_id": (
                    "character/model/shared.pac#model-property:0"
                ),
                "material_name": "scalar-only",
                "dds_textures": {"material_inputs": []},
                "material_layers": [
                    {
                        "owner_wrapper_item_id": "43",
                        "material_wrapper_index": 2,
                    }
                ],
            },
        ],
    }

    textures, material_state = _publish_material_source_evidence(
        manifest, source_cache_root=tmp_path / "source-cache"
    )

    assert len(textures) == 1
    assert textures[0]["submesh_indices"] == [0, 1]
    assert len(material_state["parameters"]) == 3
    assert material_state["unassigned_parameters"] == []
    assert [len(row["pac_xml_parameters"]) for row in material_state["submeshes"]] == [
        2,
        2,
        1,
    ]
    assert material_state["submeshes"][2]["pac_xml_parameters"][0]["value"] == (
        "#1248ffff"
    )


def test_rust_audit_report_requires_six_views_and_isolated_debug_frames() -> None:
    def capture(name: str, *, capture_kind: str = "full_model") -> dict[str, object]:
        frame_names = ["textured", "base_color", "part_id"]
        if capture_kind == "material_region":
            frame_names.extend(["normal_map", "material_response", "layer_mask"])
        return {
            "name": name,
            "capture_kind": capture_kind,
            "dds_textures_uploaded": 0,
            "frames": {key: {"non_background_pixels": 10} for key in frame_names},
        }

    report = {
        "schema": "cdmw_rust_material_audit_capture_v2",
        "ok": True,
        "renderer": "wgpu_d3d12_rust",
        "adapter": {"backend": "Dx12"},
        "dds_resources_uploaded_once_for_capture_set": True,
        "source_dds": {
            "available": True,
            "copied_source_dds_count": 0,
            "unique_source_dds_count": 0,
            "each_source_binary_decoded_at_most_once": True,
            "full_source_decode_complete": True,
        },
        "runtime_dds": {
            "resource_count": 0,
            "logical_resource_count": 0,
            "unique_binary_count": 0,
            "duplicate_upload_key_count": 0,
            "reported_gpu_resident_bytes": 0,
            "upload_key": "dds_sha256",
            "role_specific_sampling_views_share_one_physical_upload": True,
            "renderer_uploads_match_unique_binaries": True,
            "no_duplicate_upload_keys": True,
        },
        "full_model_only": True,
        "capture_count": 6,
        "material_indices": [0, 1],
        "captures": [capture(name) for name in FULL_MODEL_VIEWS],
    }

    assert _capture_report_ok(report, full_model_only=True) is True
    assert _report_dds_dedup_ok(report) is True
    report["runtime_dds"]["duplicate_upload_key_count"] = 1
    assert _report_dds_dedup_ok(report) is False
    report["runtime_dds"]["duplicate_upload_key_count"] = 0
    report["captures"][0]["frames"]["part_id"]["non_background_pixels"] = 0
    assert _capture_report_ok(report, full_model_only=True) is False

    full_report = {
        **report,
        "full_model_only": False,
        "capture_count": 8,
        "material_indices": [0],
        "captures": [capture(name) for name in FULL_MODEL_VIEWS]
        + [
            capture("front", capture_kind="material_region"),
            capture("back", capture_kind="material_region"),
        ],
    }
    assert _capture_report_ok(full_report, full_model_only=False) is True
    full_report["captures"][-1]["frames"]["layer_mask"]["non_background_pixels"] = 0
    assert _capture_report_ok(full_report, full_model_only=False) is False


def test_capture_manifest_keeps_rendered_and_source_only_capture_unreviewed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plans = [
        {"ordinal": 0, "asset_id": "0000-first", "identity": "first.pac"},
        {"ordinal": 1, "asset_id": "0001-second", "identity": "second.pac"},
    ]
    for plan, status in zip(
        plans,
        ("captured", "source_only_captured"),
        strict=True,
    ):
        report_root = tmp_path / "assets" / str(plan["asset_id"])
        report_root.mkdir(parents=True)
        (report_root / "asset-report.json").write_text(
            json.dumps(
                {
                    "schema": EQUIPMENT_CAPTURE_SCHEMA,
                    "identity": plan["identity"],
                    "status": status,
                    "technical_gates": {"valid": True},
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        "tools.mesh_harness.equipment_material_capture.EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
        2,
    )

    manifest = build_equipment_capture_manifest(tmp_path, {}, {}, plans)

    assert manifest["capture_complete"] is True
    assert manifest["capture_complete_count"] == 2
    assert manifest["reviewed_count"] == 0
    assert manifest["unreviewed_count"] == 2
    assert manifest["ok"] is False


def test_capture_manifest_preserves_checkpointed_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plans = [{"ordinal": 0, "asset_id": "0000-broken", "identity": "broken.pac"}]
    state = {
        "assets": {
            "broken.pac": {
                "status": "failed",
                "error": "RuntimeError: renderer failed",
            }
        }
    }
    monkeypatch.setattr(
        "tools.mesh_harness.equipment_material_capture.EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT",
        1,
    )

    manifest = build_equipment_capture_manifest(tmp_path, {}, {}, plans, state=state)

    assert manifest["status_counts"] == {"failed": 1}
    assert manifest["failed_count"] == 1
    assert manifest["assets"][0]["error"] == "RuntimeError: renderer failed"
    assert manifest["ok"] is False


def test_source_board_manifest_paths_remain_valid_after_staging_publish(
    tmp_path: Path,
) -> None:
    staging = tmp_path / ".asset.staging"
    board = staging / "source-boards" / "asset" / "submesh-000-source-board.png"
    manifest = board.parent / "source-board-manifest.json"
    board.parent.mkdir(parents=True)
    board.write_bytes(b"png")
    manifest.write_text("{}", encoding="utf-8")

    portable = _relativize_source_board_manifest(
        {
            "schema": "source-v2",
            "asset_id": "asset",
            "boards": [{"path": str(board), "sha256": "abc"}],
            "textures": [],
            "manifest_path": str(manifest),
        },
        staging,
    )

    assert portable["path_base"] == "asset_root"
    assert portable["boards"][0]["path"] == (
        "source-boards/asset/submesh-000-source-board.png"
    )
    assert portable["manifest_path"] == (
        "source-boards/asset/source-board-manifest.json"
    )


def test_published_render_capture_is_invalidated_when_binary_hash_changes(
    tmp_path: Path,
) -> None:
    report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "identity": "asset.pac",
        "status": "captured",
        "technical_gates": {"valid": True},
        "capture_binaries": {
            "preview_core": {"sha256": "a" * 64, "bytes": 10},
            "rust_helper": {"sha256": "b" * 64, "bytes": 20},
        },
    }
    tmp_path.joinpath("asset-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    assert (
        _valid_published_asset(
            tmp_path,
            identity="asset.pac",
            expected_binaries=report["capture_binaries"],
        )
        == report
    )
    changed = {
        **report["capture_binaries"],
        "preview_core": {"sha256": "c" * 64, "bytes": 10},
    }
    assert (
        _valid_published_asset(
            tmp_path,
            identity="asset.pac",
            expected_binaries=changed,
        )
        is None
    )


def test_source_only_capture_cannot_resume_as_a_legacy_auto_pass(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "asset-report.json"
    pending = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "identity": "catalogue-only.pac",
        "status": "source_only_captured",
        "verdict": "UNREVIEWED",
        "review_status": "pending_source_disposition_review",
        "technical_gates": {"valid": True},
    }
    report_path.write_text(json.dumps(pending), encoding="utf-8")
    assert (
        _valid_published_asset(tmp_path, identity="catalogue-only.pac") == pending
    )

    legacy = {
        **pending,
        "status": "source_only_reviewed",
        "verdict": "PASS",
        "review_status": "direct_source_resolution_reviewed",
    }
    report_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert _valid_published_asset(tmp_path, identity="catalogue-only.pac") is None


def test_archive_fingerprint_paths_cover_every_model_and_icon_archive(
    tmp_path: Path,
) -> None:
    first_pamt = tmp_path / "0009" / "0.pamt"
    first_paz = tmp_path / "0009" / "1.paz"
    icon_paz = tmp_path / "0012" / "2.paz"
    resolution = {
        "logical_models": [
            {
                "physical_components": [
                    {
                        "entry": {
                            "source_pamt": str(first_pamt),
                            "paz_file": str(first_paz),
                        }
                    }
                ]
            }
        ],
        "icons": [
            {
                "entries": [
                    {
                        "pamt_path": str(first_pamt),
                        "paz_file": str(icon_paz),
                    }
                ]
            }
        ],
    }

    assert equipment_archive_paths_from_resolution(resolution) == tuple(
        sorted(
            (first_pamt.resolve(), first_paz.resolve(), icon_paz.resolve()),
            key=lambda value: str(value).casefold(),
        )
    )


def test_review_requires_hash_pinned_full_model_and_every_material_region(
    tmp_path: Path,
) -> None:
    asset_id = "0000-example"
    identity = "example.pac"
    asset_root = tmp_path / "assets" / asset_id
    asset_root.mkdir(parents=True)
    binaries = {
        "preview_core": {"sha256": "a" * 64, "bytes": 10},
        "rust_helper": {"sha256": "b" * 64, "bytes": 20},
    }

    def write_png(relative: str, color: tuple[int, int, int]) -> Path:
        path = asset_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (48, 48), color).save(path)
        return path

    def evidence_row(path: Path) -> dict[str, object]:
        return {
            "path": str(path.relative_to(asset_root)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    before_report = asset_root / "before" / "audit-report.json"
    before_report.parent.mkdir(parents=True)
    before_report.write_text("{}", encoding="utf-8")
    after_report = asset_root / "after" / "audit-report.json"
    after_report.parent.mkdir(parents=True)
    after_report.write_text("{}", encoding="utf-8")
    icon_board = write_png("source-boards/icon-board.png", (60, 80, 100))
    contact_sheet = write_png("contact-sheet.png", (100, 120, 140))
    comparisons: dict[str, str] = {}
    comparison_hashes: dict[str, str] = {}
    for index, view in enumerate(FULL_MODEL_VIEWS):
        write_png(f"before/full-model/{view}.png", (60, 40, 20 + index))
        write_png(f"after/full-model/{view}.png", (20 + index, 40, 60))
        comparison = write_png(f"comparisons/{view}.png", (40, 50 + index, 60))
        comparisons[view] = f"comparisons/{view}.png"
        comparison_hashes[view] = hashlib.sha256(comparison.read_bytes()).hexdigest()
    region_sheet = write_png("material-region-sheets/material-0000.png", (120, 90, 60))
    source_board = write_png(
        f"source-boards/{asset_id}/submesh-000-source-board.png", (30, 60, 90)
    )
    region_sha = hashlib.sha256(region_sheet.read_bytes()).hexdigest()
    source_sha = hashlib.sha256(source_board.read_bytes()).hexdigest()
    report = {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "status": "captured",
        "verdict": "UNREVIEWED",
        "identity": identity,
        "capture_binaries": binaries,
        "renderer_path": "native_preview_core_to_direct_and_full_rust_to_wgpu_d3d12",
        "python_material_synthesis_used": False,
        "logical_texture_edge_count": 3,
        "technical_gates": {key: True for key in _RENDER_REQUIRED_TECHNICAL_GATES},
        "before_report": evidence_row(before_report),
        "after_report": evidence_row(after_report),
        "icon_board": evidence_row(icon_board),
        "composites": {
            "before_after": comparisons,
            "before_after_sha256": comparison_hashes,
            "contact_sheet": "contact-sheet.png",
            "contact_sheet_sha256": hashlib.sha256(
                contact_sheet.read_bytes()
            ).hexdigest(),
            "material_region_sheets": [
                {
                    "material_index": 0,
                    "path": "material-region-sheets/material-0000.png",
                    "sha256": region_sha,
                    "source_board_sha256": source_sha,
                }
            ],
        },
        "source_boards": {
            "boards": [
                {
                    "submesh_index": 0,
                    "path": (f"source-boards/{asset_id}/submesh-000-source-board.png"),
                    "sha256": source_sha,
                }
            ]
        },
    }
    (asset_root / "asset-report.json").write_text(json.dumps(report), encoding="utf-8")
    capture_manifest = {
        "schema": "cdmw_equipment_material_capture_manifest_v1",
        "capture_complete": True,
        "failed_count": 0,
        "missing_count": 0,
        "capture_binaries": binaries,
        "assets": [
            {
                "ordinal": 0,
                "asset_id": asset_id,
                "identity": identity,
                "status": "captured",
            }
        ],
    }
    (tmp_path / "capture-manifest.json").write_text(
        json.dumps(capture_manifest), encoding="utf-8"
    )

    index = build_equipment_review_index(
        tmp_path,
        expected_asset_count=1,
        full_models_per_page=1,
        material_regions_per_page=1,
    )
    assert index["asset_count"] == 1
    assert index["material_region_count"] == 1
    assert summarize_equipment_review(tmp_path)["verdict_counts"] == {
        "PASS": 0,
        "CONCERN": 0,
        "FAIL": 0,
        "UNREVIEWED": 1,
    }

    record_equipment_review_pages(
        tmp_path,
        ["full-model-0000"],
        verdict="PASS",
        observations="All six final camera views were directly inspected and coherent.",
    )
    assert summarize_equipment_review(tmp_path)["unreviewed_count"] == 1
    completed = record_equipment_review_pages(
        tmp_path,
        ["material-regions-00000"],
        verdict="PASS",
        observations="Source board and all isolated material diagnostics were inspected.",
    )
    assert completed["ok"] is True
    assert completed["reviewed_count"] == 1

    atlas = tmp_path / str(index["full_model_pages"][0]["path"])
    atlas.write_bytes(atlas.read_bytes() + b"tampered")
    invalidated = summarize_equipment_review(tmp_path)
    assert invalidated["ok"] is False
    assert invalidated["unreviewed_count"] == 1
