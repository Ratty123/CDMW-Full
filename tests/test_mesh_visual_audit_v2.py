from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from cdmw.models import ArchiveEntry
from tools.mesh_harness.visual_audit_cli import _load_specs, _write_draft_review
from tools.mesh_harness.visual_audit_integrity import (
    _capture_integrity,
    _material_region_captures_complete,
    _resident_renderer_unchanged,
)
from tools.mesh_harness.modify_original_audit import (
    MODIFY_ORIGINAL_SUBSET_ROLES,
    select_modify_original_subset,
)
from tools.mesh_harness.visual_audit_corpus import (
    VISUAL_AUDIT_VIEWS,
    VisualAuditAssetSpec,
    _pac_material_graph_summary,
    _source_board_corpus_summary,
    validate_visual_audit_specs,
)
from tools.mesh_harness.visual_audit_manifest_v2 import (
    PRIOR_CONCERN_SWORD_PATH,
    REQUIRED_SWORD_PATH,
    VISUAL_AUDIT_V2_CATEGORY_COUNTS,
    VISUAL_AUDIT_V2_GRAPH_MINIMUMS,
    VisualAuditV2Candidate,
    classify_visual_audit_v2_path,
    select_visual_audit_v2_candidates,
    validate_visual_audit_v2_selection,
)
from tools.mesh_harness.visual_audit_manifest_cli import (
    EXPANSION_REPEAT_PATHS,
    build_visual_audit_expansion_manifest,
    load_visual_audit_exclusion_registry,
    write_visual_audit_expansion_manifest,
)
from tools.mesh_harness.visual_audit_review import (
    _payload_sha256,
    _semantic_conservation_ok,
    _source_board_coverage_ok,
    _v2_acceptance_ok,
    _v2_corpus_acceptance_ok,
    _v2_prepared_package_seal_ok,
    _validate_v2_asset_verdict,
    _validate_v2_full_model_evidence,
    _validate_v2_material_region_verdicts,
    _validate_v2_unique_evidence_paths,
    finalize_visual_audit_review,
)
from tools.mesh_harness.visual_audit_source_boards import (
    SOURCE_BOARD_SCHEMA,
    build_source_material_boards,
)


_ALL_GRAPH_TAGS = tuple(VISUAL_AUDIT_V2_GRAPH_MINIMUMS)


def _synthetic_candidates(*, extra_per_category: int = 3) -> tuple[VisualAuditV2Candidate, ...]:
    rows: list[VisualAuditV2Candidate] = [
        VisualAuditV2Candidate(
            REQUIRED_SWORD_PATH,
            "weapon_sword",
            1,
            _ALL_GRAPH_TAGS,
            pac_xml_sha256=hashlib.sha256(REQUIRED_SWORD_PATH.encode()).hexdigest(),
            shader_families=("standardv2",),
        ),
        VisualAuditV2Candidate(
            PRIOR_CONCERN_SWORD_PATH,
            "weapon_sword",
            2,
            _ALL_GRAPH_TAGS,
            pac_xml_sha256=hashlib.sha256(PRIOR_CONCERN_SWORD_PATH.encode()).hexdigest(),
            shader_families=("standardv2",),
        ),
    ]
    for category, count in VISUAL_AUDIT_V2_CATEGORY_COUNTS.items():
        existing = sum(row.category == category for row in rows)
        for index in range(count + extra_per_category - existing):
            virtual_path = (
                f"character/model/synthetic/{category}/"
                f"cd_synthetic_{category}_{index:04d}.pac"
            )
            rows.append(
                VisualAuditV2Candidate(
                    virtual_path=virtual_path,
                    category=category,
                    graph_complexity=1000 - index,
                    graph_tags=_ALL_GRAPH_TAGS,
                    pac_xml_sha256=hashlib.sha256(virtual_path.encode()).hexdigest(),
                    wrapper_count=1 + index % 5,
                    parameter_count=10 + index,
                    texture_parameter_count=2 + index % 4,
                    shader_families=(f"shader_family_{index % 7}",),
                )
            )
    return tuple(rows)


def test_visual_audit_v2_selection_is_deterministic_exact_and_keeps_regressions() -> None:
    candidates = _synthetic_candidates()
    selected = select_visual_audit_v2_candidates(tuple(reversed(candidates)))
    repeated = select_visual_audit_v2_candidates(candidates)

    assert selected == repeated
    assert len(selected) == 120
    assert len({row.virtual_path.casefold() for row in selected}) == 120
    counts = Counter(row.category for row in selected)
    assert counts == Counter(VISUAL_AUDIT_V2_CATEGORY_COUNTS)
    paths = {row.virtual_path.casefold() for row in selected}
    assert REQUIRED_SWORD_PATH.casefold() in paths
    assert PRIOR_CONCERN_SWORD_PATH.casefold() in paths
    coverage = validate_visual_audit_v2_selection(selected)
    assert coverage["asset_count"] == 120
    assert all(
        coverage["graph_coverage"][tag] >= minimum
        for tag, minimum in VISUAL_AUDIT_V2_GRAPH_MINIMUMS.items()
    )


def test_visual_audit_v2_expansion_selection_excludes_history_except_allowed_repeats() -> None:
    candidates = _synthetic_candidates(extra_per_category=30)
    historical = select_visual_audit_v2_candidates(candidates)
    historical_paths = {row.virtual_path for row in historical}

    selected = select_visual_audit_v2_candidates(
        tuple(reversed(candidates)),
        excluded_paths=reversed(tuple(historical_paths)),
        allowed_repeat_paths=EXPANSION_REPEAT_PATHS,
        selection_seed="expanded-selection-test",
    )
    repeated = select_visual_audit_v2_candidates(
        candidates,
        excluded_paths=historical_paths,
        allowed_repeat_paths=reversed(EXPANSION_REPEAT_PATHS),
        selection_seed="expanded-selection-test",
    )

    assert selected == repeated
    selected_paths = {row.virtual_path.casefold() for row in selected}
    historical_normalized = {path.casefold() for path in historical_paths}
    assert selected_paths & historical_normalized == {
        path.casefold() for path in EXPANSION_REPEAT_PATHS
    }
    assert len(selected_paths - historical_normalized) == 118
    assert validate_visual_audit_v2_selection(selected)["asset_count"] == 120


def test_visual_audit_v2_expansion_requires_repeat_permission_for_excluded_priority() -> None:
    candidates = _synthetic_candidates(extra_per_category=30)
    historical = select_visual_audit_v2_candidates(candidates)

    with pytest.raises(ValueError, match="excluded without repeat permission"):
        select_visual_audit_v2_candidates(
            candidates,
            excluded_paths=(row.virtual_path for row in historical),
            selection_seed="expanded-selection-test",
        )


def test_visual_audit_v2_expansion_manifest_records_deterministic_history_and_hash(
    tmp_path: Path,
) -> None:
    candidates = _synthetic_candidates(extra_per_category=30)
    historical = select_visual_audit_v2_candidates(candidates)
    baseline_path = tmp_path / "baseline-corpus.json"
    manifest_path = tmp_path / "historical-manifest.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema": "cdmw_mesh_visual_audit_corpus_v2",
                "assets": [
                    {"virtual_path": row.virtual_path}
                    for row in historical[:60]
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "cdmw_mesh_visual_audit_selection_v1",
                "assets": [
                    {"virtual_path": row.virtual_path}
                    for row in historical[60:]
                ],
                "excluded_virtual_paths": [
                    historical[0].virtual_path.upper().replace("/", "\\")
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = load_visual_audit_exclusion_registry((manifest_path, baseline_path))
    repeated_registry = load_visual_audit_exclusion_registry((baseline_path, manifest_path))
    assert registry == repeated_registry
    assert len(registry.paths) == 120

    payload = build_visual_audit_expansion_manifest(
        tuple(reversed(candidates)),
        registry,
        selection_seed="expanded-manifest-test",
        archive_fingerprints_before={
            "C:/game/0009/0.pamt": {"exists": True, "size": 1, "sha256": "a" * 64}
        },
        archive_fingerprints_after={
            "C:/game/0009/0.pamt": {"exists": True, "size": 1, "sha256": "a" * 64}
        },
    )
    repeated_payload = build_visual_audit_expansion_manifest(
        candidates,
        repeated_registry,
        selection_seed="expanded-manifest-test",
        archive_fingerprints_before={
            "C:/game/0009/0.pamt": {"exists": True, "size": 1, "sha256": "a" * 64}
        },
        archive_fingerprints_after={
            "C:/game/0009/0.pamt": {"exists": True, "size": 1, "sha256": "a" * 64}
        },
    )
    assert payload == repeated_payload
    provenance = payload["selection_provenance"]
    assert provenance["excluded_path_count"] == 120
    assert provenance["new_path_count"] == 118
    assert provenance["allowed_repeat_paths"] == sorted(
        path.casefold() for path in EXPANSION_REPEAT_PATHS
    )
    assert len(provenance["manifest_core_sha256"]) == 64
    assert provenance["source_archive_fingerprints"]["unchanged"] is True

    output_path = tmp_path / "manifest-expanded-sixth-120.json"
    result = write_visual_audit_expansion_manifest(output_path, payload)
    assert hashlib.sha256(output_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    assert Path(result["sha256_path"]).read_text(encoding="ascii").startswith(
        result["manifest_sha256"]
    )
    assert len(_load_specs(output_path)) == 120

    with pytest.raises(ValueError, match="fingerprints changed"):
        build_visual_audit_expansion_manifest(
            candidates,
            registry,
            selection_seed="expanded-manifest-test",
            archive_fingerprints_before={"pamt": {"sha256": "a" * 64}},
            archive_fingerprints_after={"pamt": {"sha256": "b" * 64}},
        )


def test_visual_audit_v2_specs_use_the_v2_coverage_contract() -> None:
    selected = select_visual_audit_v2_candidates(_synthetic_candidates())
    specs = tuple(
        VisualAuditAssetSpec(
            index=index,
            asset_id=f"{index:03d}-v2-{Path(candidate.virtual_path).stem}",
            virtual_path=candidate.virtual_path,
            model_category=candidate.category,
            coverage_tags=(candidate.category, *candidate.graph_tags),
            selection_reason="test",
            graph_complexity=candidate.graph_complexity,
            graph_tags=candidate.graph_tags,
        )
        for index, candidate in enumerate(selected, 1)
    )

    coverage = validate_visual_audit_specs(specs)

    assert {key: coverage[key] for key in VISUAL_AUDIT_V2_CATEGORY_COUNTS} == dict(
        VISUAL_AUDIT_V2_CATEGORY_COUNTS
    )
    assert all(
        coverage[tag] >= minimum
        for tag, minimum in VISUAL_AUDIT_V2_GRAPH_MINIMUMS.items()
    )


def test_visual_audit_v2_validation_rejects_dropping_prior_concern() -> None:
    selected = list(select_visual_audit_v2_candidates(_synthetic_candidates()))
    prior_index = next(
        index
        for index, row in enumerate(selected)
        if row.virtual_path.casefold() == PRIOR_CONCERN_SWORD_PATH.casefold()
    )
    replacement = next(
        row
        for row in _synthetic_candidates()
        if row.category == "weapon_sword"
        and row.virtual_path.casefold() not in {item.virtual_path.casefold() for item in selected}
    )
    selected[prior_index] = replacement

    with pytest.raises(ValueError, match="prior in-scope concern"):
        validate_visual_audit_v2_selection(selected)


@pytest.mark.parametrize(
    ("path", "category"),
    [
        (REQUIRED_SWORD_PATH, "weapon_sword"),
        ("character/model/1_pc/1_phm/weapon/3_shield/cd_phm_03_shield_0001.pac", "weapon_shield"),
        ("character/model/1_pc/1_phm/weapon/4_bow/cd_phm_04_bow_0001.pac", "weapon_other"),
        ("character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_0001.pac", "armor_body"),
        ("character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0001.pac", "helmet_mask"),
        ("character/model/1_pc/1_phm/armor/12_foot/cd_phm_00_foot_0001.pac", "equipment_small"),
        ("character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_cloak_0001.pac", "equipment_soft"),
        ("character/model/1_pc/1_phm/head/hair/cd_phm_00_hair_0001.pac", "regression_control"),
    ],
)
def test_visual_audit_v2_equipment_categories(path: str, category: str) -> None:
    assert classify_visual_audit_v2_path(path) == category


def test_visual_audit_v2_metadata_recovers_first_material_group_from_malformed_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.mesh_harness.visual_audit_manifest_v2 as manifest

    payload = (
        "<Broken><Inner></Broken>"
        '<ModelProperty Index="0"><SkinnedMeshMaterialWrapper ItemID="4964" _subMeshName="Armor">'
        '<Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">'
        '<MaterialParameterTexture _name="_colorBlendingMaskTexture" Index="0">'
        '<ResourceReferencePath_ITexture _path="character/texture/armor_mask.dds"/>'
        "</MaterialParameterTexture>"
        '<MaterialParameterClothCategory _name="_clothCategory" _value="Velvet" Index="1"/>'
        '<MaterialParameterBitflag32 _name="_colorBlendingFlag" _value="4095" Index="2"/>'
        '<MaterialParameterFloat _name="_metalness" _value="0.5" Index="3"/>'
        "</Vector></Material></SkinnedMeshMaterialWrapper></ModelProperty>"
        '<ModelProperty Index="1"><SkinnedMeshMaterialWrapper ItemID="9999" _subMeshName="Wrong">'
        '<Material _materialName="SkinnedMeshStandard_Ver2">'
        '<MaterialParameterTexture _name="_baseColorTexture" _value="character/texture/wrong.dds"/>'
        "</Material></SkinnedMeshMaterialWrapper></ModelProperty>"
    ).encode("utf-8")
    sidecar_path = "character/modelproperty/armor.pac_xml"
    sidecar = ArchiveEntry(
        path=sidecar_path,
        pamt_path=Path("0009/0.pamt"),
        paz_file=Path("0009/1.paz"),
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=1,
    )
    monkeypatch.setattr(manifest, "_read_archive_payload", lambda _entry: payload)

    metadata = manifest._sidecar_graph_metadata(sidecar)

    assert metadata is not None
    assert metadata["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert metadata["wrapper_count"] == 1
    assert metadata["parameter_count"] == 4
    assert metadata["texture_parameter_count"] == 1
    candidate = manifest._candidate_from_metadata(
        "character/model/1_pc/2_phw/armor/9_upperbody/armor.pac",
        "armor_body",
        sidecar_path=sidecar_path,
        metadata=metadata,
    )
    assert candidate.graph_complexity > 0
    assert candidate.pac_xml_virtual_path == sidecar_path
    assert set(candidate.graph_tags) >= set(VISUAL_AUDIT_V2_GRAPH_MINIMUMS)


def _region_captures() -> list[dict[str, object]]:
    return [
        {
            "angle": angle,
            "debug_mode": mode,
            "ok": True,
            "rendered_camera": {"solid_draw_count": 1},
        }
        for angle, mode in (
            ("front", "final"),
            ("oblique", "final"),
            ("oblique", "base"),
            ("oblique", "normal"),
            ("oblique", "roughness"),
            ("oblique", "metallic"),
            ("oblique", "specular"),
            ("oblique", "layer_mask"),
        )
    ]


def test_visual_audit_v2_region_integrity_requires_every_submesh_and_exact_isolation() -> None:
    report = {
        "assets": [
            {
                "source_submesh_count": 2,
                "material_regions": [
                    {
                        "source_submesh_index": 0,
                        "hidden_submesh_indices": [1],
                        "captures": _region_captures(),
                        "ok": True,
                    },
                    {
                        "source_submesh_index": 1,
                        "hidden_submesh_indices": [0],
                        "captures": _region_captures(),
                        "ok": True,
                    },
                ],
            }
        ]
    }
    assert _material_region_captures_complete(report) is True

    report["assets"][0]["material_regions"][1]["hidden_submesh_indices"] = []
    assert _material_region_captures_complete(report) is False

    report["assets"][0]["material_regions"][1]["hidden_submesh_indices"] = [0]
    report["assets"][0]["material_regions"][1]["captures"][0]["rendered_camera"][
        "solid_draw_count"
    ] = 2
    assert _material_region_captures_complete(report) is False


def test_visual_audit_v2_integrity_requires_resident_material_application_without_reset() -> None:
    report = {
        "requested_asset_count": 12,
        "resident_material_update_count": 12,
        "resident_material_update_failure_count": 0,
        "process_start_count": 1,
        "process_restart_count": 0,
        "renderer_session": {
            "viewport_create_count": 1,
            "device_initialization_count": 1,
            "device_reset_attempt_count": 0,
            "device_reset_count": 0,
        },
    }
    assert _resident_renderer_unchanged(report) is True
    report["resident_material_update_count"] = 11
    assert _resident_renderer_unchanged(report) is False


def _region_verdict(index: int, *, verdict: str = "PASS") -> dict[str, object]:
    return {
        "source_submesh_index": index,
        "classification": "soft_nonmetal_unknown" if index else "metal",
        "classification_basis": "PAC graph plus direct source-board inspection.",
        "source_map_observations": "Packed metal is black for the wrap and bright for the blade.",
        "pac_evidence": "Owner-qualified base and layer parameters are conserved.",
        "render_observations": "The wrap remains rough while the blade carries the highlight.",
        "geometry_observations": "The isolated region and full silhouette remain contiguous.",
        "geometry_coherent": True,
        "confidence": "high",
        "unsupported_features": [],
        "unsupported_feature_unchanged": False,
        "automated_metric_flags": [],
        "automated_metrics_only": False,
        "source_board_direct_image_inspection": True,
        "review_sheet_direct_image_inspection": True,
        "direct_image_inspection": True,
        "verdict": verdict,
    }


def _composite_region(tmp_path: Path, index: int) -> dict[str, object]:
    source_board = tmp_path / "source-boards" / f"source-{index}.png"
    review_sheet = tmp_path / "material-region-sheets" / f"review-{index}.png"
    source_board.parent.mkdir(parents=True, exist_ok=True)
    review_sheet.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), (20 + index, 40, 60)).save(source_board)
    Image.new("RGB", (4, 4), (80 + index, 100, 120)).save(review_sheet)
    return {
        "source_submesh_index": index,
        "source_board": str(source_board),
        "source_board_sha256": hashlib.sha256(source_board.read_bytes()).hexdigest(),
        "review_sheet": str(review_sheet),
        "review_sheet_sha256": hashlib.sha256(review_sheet.read_bytes()).hexdigest(),
    }


def _corpus_row_for_regions(regions: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "source_boards": {
            "boards": [
                {
                    "submesh_index": int(region["source_submesh_index"]),
                    "path": region["source_board"],
                    "sha256": region["source_board_sha256"],
                }
                for region in regions
            ]
        }
    }


def _full_model_angle_reviews(*, coherent: bool = True) -> list[dict[str, object]]:
    return [
        {
            "angle": str(row["name"]),
            "direct_image_inspection": True,
            "visual_observations": "The complete silhouette and material regions are visible.",
            "geometry_coherent": coherent,
            "geometry_observations": "The assembled silhouette remains contiguous in this view.",
            "verdict": "PASS" if coherent else "FAIL",
        }
        for row in VISUAL_AUDIT_VIEWS
    ]


def _acceptance_camera_matrix(
    index: int,
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    scale_offset: float,
) -> list[float]:
    yaw = math.radians(yaw_degrees)
    pitch = math.radians(pitch_degrees)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    cos_pitch = math.cos(pitch)
    sin_pitch = math.sin(pitch)
    screen_x = (cos_yaw, sin_yaw * sin_pitch, sin_yaw * cos_pitch)
    screen_y = (0.0, cos_pitch, -sin_pitch)
    view_direction = (-sin_yaw, cos_yaw * sin_pitch, cos_yaw * cos_pitch)
    scale_x = 1.0 + scale_offset + index
    scale_y = 2.0 + scale_offset + index
    depth_scale = 0.5 + scale_offset + index
    return [
        scale_x * screen_x[0],
        scale_y * screen_y[0],
        depth_scale * view_direction[0],
        0.0,
        scale_x * screen_x[1],
        scale_y * screen_y[1],
        depth_scale * view_direction[1],
        0.0,
        scale_x * screen_x[2],
        scale_y * screen_y[2],
        depth_scale * view_direction[2],
        0.0,
        scale_offset * 0.001,
        index * 0.01,
        0.5,
        1.0,
    ]


def _acceptance_archive_captures(asset_id: str) -> list[dict[str, object]]:
    captures: list[dict[str, object]] = []
    for index, view in enumerate(VISUAL_AUDIT_VIEWS):
        name = str(view["name"])
        yaw = float(view["yaw"])
        pitch = float(view["pitch"])
        captures.append(
            {
                "name": name,
                "yaw": yaw,
                "pitch": pitch,
                "path": f"C:/synthetic/archive/{asset_id}/{name}.png",
                "camera_ack": {
                    "event": "view_state",
                    "reason": "set_view",
                    "role": "replacement",
                    "yaw": yaw,
                    "pitch": pitch,
                },
                "capture_event": {
                    "event": "frame_capture",
                    "ok": True,
                    "rendered_camera": {
                        "role": "replacement",
                        "yaw_degrees": yaw,
                        "pitch_degrees": pitch,
                        "viewport_width": 8,
                        "viewport_height": 8,
                        "solid_draw_count": 1,
                        "world_view_projection": _acceptance_camera_matrix(
                            index,
                            yaw_degrees=yaw,
                            pitch_degrees=pitch,
                            scale_offset=0.0,
                        ),
                    },
                },
            }
        )
    return captures


def _acceptance_dotnet_captures(asset_id: str) -> list[dict[str, object]]:
    captures: list[dict[str, object]] = []
    for index, view in enumerate(VISUAL_AUDIT_VIEWS):
        name = str(view["name"])
        yaw = float(view["yaw"])
        pitch = float(view["pitch"])
        captures.append(
            {
                "name": name,
                "yaw": yaw,
                "pitch": pitch,
                "renderer_yaw": yaw,
                "renderer_pitch": pitch,
                "camera_mapping": "archive_object_rotation_basis_orthographic_v1",
                "path": f"C:/synthetic/dotnet/{asset_id}/{name}.png",
                "rendered_camera": {
                    "role": "editable",
                    "yaw_degrees": yaw,
                    "pitch_degrees": pitch,
                    "viewport_width": 8,
                    "viewport_height": 8,
                    "solid_draw_count": 1,
                    "world_view_projection": _acceptance_camera_matrix(
                        index,
                        yaw_degrees=yaw,
                        pitch_degrees=pitch,
                        scale_offset=100.0,
                    ),
                },
            }
        )
    return captures


def _acceptance_region_captures() -> list[dict[str, object]]:
    return [
        {
            "angle": angle,
            "debug_mode": mode,
            "ok": True,
            "yaw": 0.0,
            "pitch": 0.0,
            "renderer_yaw": 0.0,
            "renderer_pitch": 0.0,
            "camera_mapping": "archive_object_rotation_basis_orthographic_v1",
            "rendered_camera": {"solid_draw_count": 1},
        }
        for angle, mode in (
            ("front", "final"),
            ("oblique", "final"),
            ("oblique", "base"),
            ("oblique", "normal"),
            ("oblique", "roughness"),
            ("oblique", "metallic"),
            ("oblique", "specular"),
            ("oblique", "layer_mask"),
        )
    ]


def test_visual_audit_v2_draft_requires_full_geometry_reference_and_region_review(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    corpus = {
        "run_id": "a" * 32,
        "asset_count": 1,
        "assets": [
            {
                "asset_id": "001-test",
                "index": 1,
                "virtual_path": REQUIRED_SWORD_PATH,
                "model_category": "weapon_sword",
                "archive_provenance": {},
                "expected_material_families": ["standard_v2"],
            }
        ],
    }
    composites = [
        {
            "id": "001-test",
            "selected_camera_angle": "three-quarter-front",
            "material_regions": [
                {
                    "source_submesh_index": 0,
                    "source_board": "source.png",
                    "review_sheet": "review.png",
                }
            ],
        }
    ]
    _write_draft_review(
        evidence,
        corpus,
        composites,
        {"ok": True},
        {"ok": True},
        True,
        True,
    )
    template = json.loads((evidence / "verdicts.template.json").read_text(encoding="utf-8"))
    asset = template["assets"][0]
    assert [row["angle"] for row in asset["full_model_angle_reviews"]] == [
        str(view["name"]) for view in VISUAL_AUDIT_VIEWS
    ]
    assert not any(
        row["direct_image_inspection"] for row in asset["full_model_angle_reviews"]
    )
    assert not any(row["verdict"] for row in asset["full_model_angle_reviews"])
    assert asset["full_model_contact_sheet_direct_image_inspection"] is False
    assert asset["full_model_contact_sheet_verdict"] == ""
    assert asset["full_model_geometry_coherent"] is None
    assert asset["reference_status"] == ""
    assert asset["reported_target_match"] is None
    assert asset["material_regions"][0]["geometry_coherent"] is None
    assert asset["material_regions"][0]["source_board_direct_image_inspection"] is False
    assert asset["material_regions"][0]["review_sheet_direct_image_inspection"] is False


def test_visual_audit_v2_finalizer_keeps_global_acceptance_fail_closed(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    runtime = evidence / "runtime"
    runtime.mkdir(parents=True)
    run_id = "b" * 32
    asset_id = "001-target"
    region = _composite_region(evidence, 0)
    comparisons: dict[str, str] = {}
    comparison_hashes: dict[str, str] = {}
    for index, view in enumerate(VISUAL_AUDIT_VIEWS):
        angle = str(view["name"])
        path = evidence / "comparisons" / asset_id / f"{angle}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), (30 + index, 50, 70)).save(path)
        comparisons[angle] = str(path)
        comparison_hashes[angle] = hashlib.sha256(path.read_bytes()).hexdigest()
    contact_sheet = evidence / "contact-sheets" / f"{asset_id}.png"
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (90, 110, 130)).save(contact_sheet)

    def write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    corpus_payload = {
            "schema": "cdmw_mesh_visual_audit_corpus_v2",
            "run_id": run_id,
            "asset_count": 1,
            "coverage": {},
            "assets": [
                {
                    "index": 1,
                    "asset_id": asset_id,
                    "virtual_path": REQUIRED_SWORD_PATH,
                    "model_category": "weapon_sword",
                    "submesh_count": 1,
                    "binding_conservation": [
                        {
                            "conserved": True,
                            "dropped_parameters": [],
                            "cross_owner_bindings": [],
                            "layer_as_base_bindings": [],
                        }
                    ],
                    "initial_resident_material_equivalence": {
                        "equivalent": True,
                        "mismatches": [],
                    },
                    "source_boards": {
                        "boards": [
                            {
                                "submesh_index": 0,
                                "path": region["source_board"],
                                "sha256": region["source_board_sha256"],
                            }
                        ]
                    },
                    "archive_provenance": {},
                    "expected_material_families": ["standard_v2"],
                    "shader_profile_classification": ["standard_v2"],
                    "expected_texture_channels": ["base", "normal", "material"],
                    "alpha_modes": ["opaque"],
                }
            ],
        }
    write_json(evidence / "corpus.json", corpus_payload)
    write_json(
        runtime / "composites.json",
        {
            "assets": [
                {
                    "id": asset_id,
                    "candidate_comparisons": comparisons,
                    "candidate_comparison_sha256": comparison_hashes,
                    "contact_sheet": str(contact_sheet),
                    "contact_sheet_sha256": hashlib.sha256(contact_sheet.read_bytes()).hexdigest(),
                    "material_regions": [region],
                }
            ]
        },
    )
    write_json(
        runtime / "archive-browser-capture.json",
        {"ok": True, "assets": [{"id": asset_id, "ok": True}]},
    )
    write_json(
        runtime / "dotnet-capture.json",
        {"ok": True, "renderer_session": {}, "assets": [{"id": asset_id, "ok": True}]},
    )
    temporary_root = tmp_path / "prepared"
    archive_package = temporary_root / "archive" / asset_id
    dotnet_package = temporary_root / "dotnet" / asset_id
    archive_package.mkdir(parents=True)
    dotnet_package.mkdir(parents=True)
    (archive_package / "manifest.json").write_text("{}", encoding="utf-8")
    (dotnet_package / "manifest.json").write_text("{}", encoding="utf-8")
    archive_source = tmp_path / "archive.paz"
    archive_source.write_bytes(b"archive-source")
    corpus_sha256 = _payload_sha256(corpus_payload)
    write_json(
        runtime / "package-state.json",
        {
            "schema": "cdmw_mesh_visual_audit_package_state_v1",
            "run_id": run_id,
            "evidence_root": str(evidence.resolve()),
            "temporary_root": str(temporary_root.resolve()),
            "corpus_sha256": corpus_sha256,
            "asset_ids": [asset_id],
            "runtime_assets": [
                {
                    "id": asset_id,
                    "run_id": run_id,
                    "archive_package_dir": str(archive_package.resolve()),
                    "dotnet_package_dir": str(dotnet_package.resolve()),
                }
            ],
            "archive_fingerprint_paths": [str(archive_source.resolve())],
        },
    )
    write_json(runtime / "integrity.json", {"ok": True})
    archive_fingerprints = {
        str(archive_source.resolve()): {
            "exists": True,
            "size": archive_source.stat().st_size,
            "sha256": hashlib.sha256(archive_source.read_bytes()).hexdigest(),
        }
    }
    write_json(runtime / "archive-fingerprints-before.json", archive_fingerprints)
    write_json(runtime / "archive-fingerprints-after.json", archive_fingerprints)
    seal_assets = [
        {
            "id": asset_id,
            "archive_package_dir": {
                "file_count": 1,
                "total_bytes": 2,
                "tree_sha256": "d" * 64,
            },
            "dotnet_package_dir": {
                "file_count": 1,
                "total_bytes": 2,
                "tree_sha256": "e" * 64,
            },
        }
    ]
    prepared_fingerprints = {
        "schema": "cdmw_mesh_visual_audit_prepared_package_fingerprints_v1",
        "run_id": run_id,
        "corpus_sha256": corpus_sha256,
        "asset_count": 1,
        "assets": seal_assets,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                seal_assets,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    write_json(runtime / "prepared-package-fingerprints.json", prepared_fingerprints)
    write_json(runtime / "prepared-package-fingerprints-after.json", prepared_fingerprints)
    verdicts = tmp_path / "verdicts.json"
    write_json(
        verdicts,
        {
            "schema": "cdmw_mesh_visual_audit_verdict_v2",
            "run_id": run_id,
            "assets": [
                {
                    "id": asset_id,
                    "selected_camera_angle": "front",
                    "full_model_angle_reviews": _full_model_angle_reviews(),
                    "full_model_contact_sheet_direct_image_inspection": True,
                    "full_model_contact_sheet_observations": "All six views are present and legible.",
                    "full_model_contact_sheet_verdict": "PASS",
                    "full_model_geometry_coherent": True,
                    "full_model_geometry_observations": "The assembled sword is contiguous.",
                    "reference_status": "exact_item",
                    "reference_identity": "Vessel of Dark Pursuit",
                    "reference_urls": ["https://example.test/vessel"],
                    "reference_observations": "Compared against the exact item page.",
                    "reported_target_match": True,
                    "reported_target_observations": "Steel, gold inset, and wrap match.",
                    "overall_verdict": "PASS",
                    "material_regions": [_region_verdict(0)],
                }
            ],
        },
    )

    summary = finalize_visual_audit_review(evidence, verdicts)

    assert summary["status"] == "complete_visual_review"
    assert summary["acceptance_checks"] == {
        "corpus_selection": False,
        "source_board_coverage": True,
        "semantic_conservation": True,
        "asset_verdicts": True,
        "archive_browser_batch": True,
        "dotnet_batch": True,
        "capture_integrity": False,
        "archive_sources_unchanged": True,
        "prepared_package_state": True,
        "prepared_packages_unchanged": True,
    }
    assert summary["acceptance_ok"] is False
    assert summary["geometry_coherent_asset_count"] == 1
    assert summary["geometry_coherent_submesh_count"] == 1
    assert summary["full_model_angle_direct_review_count"] == 6
    assert summary["contact_sheet_direct_review_count"] == 1
    assert summary["source_board_direct_review_count"] == 1
    assert summary["submesh_review_sheet_direct_review_count"] == 1


def test_visual_audit_v2_package_seal_rejects_tampered_tree_or_aggregate() -> None:
    run_id = "c" * 32
    corpus_sha256 = "d" * 64
    asset_rows = [
        {
            "id": "001-test",
            "archive_package_dir": {
                "file_count": 2,
                "total_bytes": 20,
                "tree_sha256": "e" * 64,
            },
            "dotnet_package_dir": {
                "file_count": 3,
                "total_bytes": 30,
                "tree_sha256": "f" * 64,
            },
        }
    ]
    seal = {
        "schema": "cdmw_mesh_visual_audit_prepared_package_fingerprints_v1",
        "run_id": run_id,
        "corpus_sha256": corpus_sha256,
        "asset_count": 1,
        "assets": asset_rows,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                asset_rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    assert _v2_prepared_package_seal_ok(
        seal,
        run_id=run_id,
        corpus_sha256=corpus_sha256,
        expected_ids=["001-test"],
    ) is True

    tampered = json.loads(json.dumps(seal))
    tampered["assets"][0]["archive_package_dir"]["tree_sha256"] = "0" * 64
    assert _v2_prepared_package_seal_ok(
        tampered,
        run_id=run_id,
        corpus_sha256=corpus_sha256,
        expected_ids=["001-test"],
    ) is False
    tampered = json.loads(json.dumps(seal))
    tampered["aggregate_sha256"] = "0" * 64
    assert _v2_prepared_package_seal_ok(
        tampered,
        run_id=run_id,
        corpus_sha256=corpus_sha256,
        expected_ids=["001-test"],
    ) is False


def test_visual_audit_v2_full_120_acceptance_survives_sorted_json_round_trip(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    runtime = evidence / "runtime"
    runtime.mkdir(parents=True)
    run_id = "f" * 32
    candidates = select_visual_audit_v2_candidates(_synthetic_candidates())
    assert len(candidates) == 120

    master_png = tmp_path / "master.png"
    Image.new("RGB", (2, 2), (30, 60, 90)).save(master_png)
    image_bytes = master_png.read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()

    def write_image(path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
        return str(path.resolve())

    def write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    corpus_assets: list[dict[str, object]] = []
    composite_assets: list[dict[str, object]] = []
    archive_assets: list[dict[str, object]] = []
    dotnet_assets: list[dict[str, object]] = []
    verdict_assets: list[dict[str, object]] = []
    runtime_assets: list[dict[str, object]] = []
    seal_assets: list[dict[str, object]] = []
    expected_ids: list[str] = []
    coverage = Counter(tag for candidate in candidates for tag in candidate.graph_tags)
    temporary_root = tmp_path / "prepared"

    for index, candidate in enumerate(candidates, start=1):
        asset_id = f"{index:03d}-acceptance"
        expected_ids.append(asset_id)
        source_board = write_image(
            evidence / "source-boards" / asset_id / "submesh-000.png"
        )
        review_sheet = write_image(
            evidence / "material-region-sheets" / asset_id / "submesh-000.png"
        )
        conservation = {
            "conserved": True,
            "dropped_parameters": [],
            "cross_owner_bindings": [],
            "layer_as_base_bindings": [],
        }
        corpus_assets.append(
            {
                "index": index,
                "asset_id": asset_id,
                "virtual_path": candidate.virtual_path,
                "model_category": candidate.category,
                "submesh_count": 1,
                "binding_conservation": [conservation],
                "initial_resident_material_equivalence": {
                    "equivalent": True,
                    "mismatches": [],
                },
                "source_boards": {
                    "boards": [
                        {
                            "submesh_index": 0,
                            "path": source_board,
                            "sha256": image_sha256,
                            "binding_conservation": conservation,
                        }
                    ]
                },
                "archive_provenance": {"synthetic_contract_only": True},
                "expected_material_families": ["standard_v2"],
                "shader_profile_classification": ["standard_v2"],
                "expected_texture_channels": ["base", "normal", "material"],
                "alpha_modes": ["opaque"],
            }
        )

        comparisons: dict[str, str] = {}
        comparison_hashes: dict[str, str] = {}
        for view in VISUAL_AUDIT_VIEWS:
            angle = str(view["name"])
            comparisons[angle] = write_image(
                evidence / "comparisons" / asset_id / f"{angle}.png"
            )
            comparison_hashes[angle] = image_sha256
        contact_sheet = write_image(
            evidence / "contact-sheets" / f"{asset_id}.png"
        )
        composite_assets.append(
            {
                "id": asset_id,
                "candidate_comparisons": comparisons,
                "candidate_comparison_sha256": comparison_hashes,
                "contact_sheet": contact_sheet,
                "contact_sheet_sha256": image_sha256,
                "material_regions": [
                    {
                        "source_submesh_index": 0,
                        "source_board": source_board,
                        "source_board_sha256": image_sha256,
                        "review_sheet": review_sheet,
                        "review_sheet_sha256": image_sha256,
                        "binding_conservation": conservation,
                    }
                ],
                "archive_browser_capture_ok": True,
                "mesh_editor_capture_ok": True,
            }
        )

        archive_assets.append(
            {
                "id": asset_id,
                "ok": True,
                "captures": _acceptance_archive_captures(asset_id),
            }
        )
        dotnet_assets.append(
            {
                "id": asset_id,
                "ok": True,
                "source_submesh_count": 1,
                "captures": _acceptance_dotnet_captures(asset_id),
                "material_regions": [
                    {
                        "source_submesh_index": 0,
                        "hidden_submesh_indices": [],
                        "captures": _acceptance_region_captures(),
                        "ok": True,
                    }
                ],
            }
        )

        is_target = candidate.virtual_path.casefold() == REQUIRED_SWORD_PATH.casefold()
        is_control = candidate.category == "regression_control"
        verdict_assets.append(
            {
                "id": asset_id,
                "selected_camera_angle": "front",
                "full_model_angle_reviews": _full_model_angle_reviews(),
                "full_model_contact_sheet_direct_image_inspection": True,
                "full_model_contact_sheet_observations": (
                    "All six synthetic contract panels are present."
                ),
                "full_model_contact_sheet_verdict": "PASS",
                "full_model_geometry_coherent": True,
                "full_model_geometry_observations": (
                    "Synthetic contract geometry is coherent in every declared view."
                ),
                "reference_status": (
                    "exact_item"
                    if is_target
                    else "not_applicable_control"
                    if is_control
                    else "reference_unavailable"
                ),
                "reference_identity": "Vessel of Dark Pursuit" if is_target else "",
                "reference_urls": ["https://example.test/vessel"] if is_target else [],
                "reference_observations": (
                    "Synthetic exact-target contract row."
                    if is_target
                    else "Synthetic regression control."
                    if is_control
                    else "No public identity is claimed by this synthetic contract test."
                ),
                "reported_target_match": True if is_target else "not_applicable",
                "reported_target_observations": (
                    "Synthetic target fields satisfy the explicit acceptance contract."
                    if is_target
                    else ""
                ),
                "overall_verdict": "PASS",
                "material_regions": [_region_verdict(0)],
            }
        )

        archive_package = temporary_root / "archive" / asset_id
        dotnet_package = temporary_root / "dotnet" / asset_id
        archive_package.mkdir(parents=True)
        dotnet_package.mkdir(parents=True)
        (archive_package / "manifest.json").write_text("{}", encoding="utf-8")
        (dotnet_package / "manifest.json").write_text("{}", encoding="utf-8")
        runtime_assets.append(
            {
                "id": asset_id,
                "run_id": run_id,
                "archive_package_dir": str(archive_package.resolve()),
                "dotnet_package_dir": str(dotnet_package.resolve()),
            }
        )
        seal_assets.append(
            {
                "id": asset_id,
                "archive_package_dir": {
                    "file_count": 1,
                    "total_bytes": 2,
                    "tree_sha256": hashlib.sha256(
                        f"archive-{asset_id}".encode("utf-8")
                    ).hexdigest(),
                },
                "dotnet_package_dir": {
                    "file_count": 1,
                    "total_bytes": 2,
                    "tree_sha256": hashlib.sha256(
                        f"dotnet-{asset_id}".encode("utf-8")
                    ).hexdigest(),
                },
            }
        )

    corpus = {
        "schema": "cdmw_mesh_visual_audit_corpus_v2",
        "run_id": run_id,
        "asset_count": 120,
        "coverage": dict(coverage),
        "assets": corpus_assets,
    }
    corpus_sha256 = _payload_sha256(corpus)
    archive_source = tmp_path / "source.paz"
    archive_source.write_bytes(b"synthetic-archive-source")
    package_state = {
        "schema": "cdmw_mesh_visual_audit_package_state_v1",
        "run_id": run_id,
        "evidence_root": str(evidence.resolve()),
        "temporary_root": str(temporary_root.resolve()),
        "corpus_sha256": corpus_sha256,
        "asset_ids": expected_ids,
        "runtime_assets": runtime_assets,
        "archive_fingerprint_paths": [str(archive_source.resolve())],
    }
    prepared_fingerprints = {
        "schema": "cdmw_mesh_visual_audit_prepared_package_fingerprints_v1",
        "run_id": run_id,
        "corpus_sha256": corpus_sha256,
        "asset_count": 120,
        "assets": seal_assets,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                seal_assets,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    archive_report = {
        "schema": "cdmw_mesh_visual_audit_archive_batch_v2",
        "run_id": run_id,
        "ok": True,
        "assets": archive_assets,
    }
    dotnet_report = {
        "schema": "cdmw_mesh_visual_audit_dotnet_batch_v2",
        "run_id": run_id,
        "ok": True,
        "requested_asset_count": 120,
        "resident_material_update_count": 120,
        "resident_material_update_failure_count": 0,
        "process_start_count": 1,
        "process_restart_count": 0,
        "renderer_session": {
            "viewport_create_count": 1,
            "device_initialization_count": 1,
            "device_reset_attempt_count": 0,
            "device_reset_count": 0,
        },
        "assets": dotnet_assets,
    }
    integrity = _capture_integrity(
        run_id=run_id,
        expected_ids=expected_ids,
        archive_report=archive_report,
        dotnet_report=dotnet_report,
        composite_rows=composite_assets,
        prepared_packages_unchanged=True,
    )
    assert integrity["ok"] is True
    archive_fingerprints = {
        str(archive_source.resolve()): {
            "exists": True,
            "size": archive_source.stat().st_size,
            "sha256": hashlib.sha256(archive_source.read_bytes()).hexdigest(),
        }
    }

    write_json(evidence / "corpus.json", corpus)
    write_json(runtime / "package-state.json", package_state)
    write_json(runtime / "composites.json", {"assets": composite_assets})
    write_json(runtime / "archive-browser-capture.json", archive_report)
    write_json(runtime / "dotnet-capture.json", dotnet_report)
    write_json(runtime / "integrity.json", integrity)
    write_json(runtime / "archive-fingerprints-before.json", archive_fingerprints)
    write_json(runtime / "archive-fingerprints-after.json", archive_fingerprints)
    write_json(runtime / "prepared-package-fingerprints.json", prepared_fingerprints)
    write_json(runtime / "prepared-package-fingerprints-after.json", prepared_fingerprints)
    verdicts_path = tmp_path / "verdicts.json"
    write_json(
        verdicts_path,
        {
            "schema": "cdmw_mesh_visual_audit_verdict_v2",
            "run_id": run_id,
            "assets": verdict_assets,
        },
    )

    summary = finalize_visual_audit_review(evidence, verdicts_path)

    assert summary["asset_count"] == 120
    assert summary["pass_count"] == 120
    assert summary["visible_submesh_count"] == 120
    assert summary["full_model_angle_direct_review_count"] == 720
    assert summary["contact_sheet_direct_review_count"] == 120
    assert summary["source_board_direct_review_count"] == 120
    assert summary["submesh_review_sheet_direct_review_count"] == 120
    assert summary["acceptance_ok"] is True
    assert all(summary["acceptance_checks"].values())


def test_visual_audit_v2_verdict_requires_direct_rows_for_every_visible_submesh(
    tmp_path: Path,
) -> None:
    composites = (
        _composite_region(tmp_path, 0),
        _composite_region(tmp_path, 1),
    )
    asset = {
        "overall_verdict": "PASS",
        "material_regions": [_region_verdict(0), _region_verdict(1)],
    }
    corpus_row = _corpus_row_for_regions(composites)
    rows = _validate_v2_material_region_verdicts(asset, composites, corpus_row)
    assert [row["source_submesh_index"] for row in rows] == [0, 1]

    angle_reviews = _full_model_angle_reviews()
    angle_reviews[0]["verdict"] = "CONCERN"
    with pytest.raises(ValueError, match="worst reviewed-image verdict"):
        _validate_v2_material_region_verdicts(
            {
                "overall_verdict": "PASS",
                "full_model_angle_reviews": angle_reviews,
                "full_model_contact_sheet_verdict": "PASS",
                "material_regions": [_region_verdict(0), _region_verdict(1)],
            },
            composites,
            corpus_row,
        )

    with pytest.raises(ValueError, match="every visible submesh"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [_region_verdict(0)]},
            composites,
            corpus_row,
        )
    with pytest.raises(ValueError, match="only review objects"):
        _validate_v2_material_region_verdicts(
            {
                "overall_verdict": "PASS",
                "material_regions": [_region_verdict(0), _region_verdict(1), "junk"],
            },
            composites,
            corpus_row,
        )
    automated = _region_verdict(0)
    automated["automated_metrics_only"] = True
    with pytest.raises(ValueError, match="cannot issue a visual PASS"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [automated]},
            composites[:1],
            _corpus_row_for_regions(composites[:1]),
        )
    automated.pop("automated_metrics_only")
    with pytest.raises(ValueError, match="explicit automated-metrics-only"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [automated]},
            composites[:1],
            _corpus_row_for_regions(composites[:1]),
        )
    broken = _region_verdict(0)
    broken["geometry_coherent"] = False
    with pytest.raises(ValueError, match="Broken submesh geometry"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [broken]},
            composites[:1],
            _corpus_row_for_regions(composites[:1]),
        )

    Path(str(composites[0]["review_sheet"])).write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence hash changed"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [_region_verdict(0)]},
            composites[:1],
            _corpus_row_for_regions(composites[:1]),
        )


def test_visual_audit_v2_requires_separate_source_and_render_inspection_records(
    tmp_path: Path,
) -> None:
    composite = (_composite_region(tmp_path, 0),)
    corpus_row = _corpus_row_for_regions(composite)
    verdict = _region_verdict(0)
    verdict["source_board_direct_image_inspection"] = False
    with pytest.raises(ValueError, match="separate direct source-board"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [verdict]},
            composite,
            corpus_row,
        )

    verdict = _region_verdict(0)
    verdict["review_sheet_direct_image_inspection"] = False
    with pytest.raises(ValueError, match="separate direct review-sheet"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [verdict]},
            composite,
            corpus_row,
        )

    other = (_composite_region(tmp_path / "other", 0),)
    with pytest.raises(ValueError, match="does not match its frozen corpus"):
        _validate_v2_material_region_verdicts(
            {"overall_verdict": "PASS", "material_regions": [_region_verdict(0)]},
            composite,
            _corpus_row_for_regions(other),
        )


def test_visual_audit_v2_rejects_cross_lane_evidence_file_reuse() -> None:
    summary = [
        {
            "id": "asset",
            "full_model_comparisons": {"front": "same.png"},
            "multi_angle_contact_sheet": "contact.png",
            "material_regions": [
                {
                    "source_submesh_index": 0,
                    "source_board": "source.png",
                    "review_sheet": "same.png",
                }
            ],
        }
    ]
    with pytest.raises(ValueError, match="evidence file is reused"):
        _validate_v2_unique_evidence_paths(summary)


def test_visual_audit_v2_acceptance_allows_only_explicit_unchanged_control_concerns() -> None:
    conserved = {
        "asset_id": "asset",
        "model_category": "regression_control",
        "submesh_count": 1,
        "binding_conservation": [
            {
                "conserved": True,
                "dropped_parameters": [],
                "cross_owner_bindings": [],
                "layer_as_base_bindings": [],
            }
        ],
        "initial_resident_material_equivalence": {"equivalent": True, "mismatches": []},
    }
    region = _region_verdict(0, verdict="CONCERN")
    region["unsupported_features"] = ["transmission"]
    region["unsupported_feature_unchanged"] = True
    summary = [
        {
            "id": "asset",
            "overall_verdict": "CONCERN",
            "full_model_direct_image_inspection": True,
            "full_model_angle_reviews": _full_model_angle_reviews(),
            "full_model_contact_sheet_direct_image_inspection": True,
            "full_model_contact_sheet_verdict": "PASS",
            "full_model_geometry_coherent": True,
            "material_regions": [region],
        }
    ]
    assert _v2_acceptance_ok(summary, [conserved]) is True

    region["verdict"] = "PASS"
    summary[0]["full_model_angle_reviews"][0]["verdict"] = "CONCERN"
    assert _v2_acceptance_ok(summary, [conserved]) is False
    region["verdict"] = "CONCERN"
    summary[0]["full_model_angle_reviews"][0]["verdict"] = "PASS"
    region["unsupported_feature_unchanged"] = False
    assert _v2_acceptance_ok(summary, [conserved]) is False
    conserved["model_category"] = "helmet_mask"
    region["unsupported_feature_unchanged"] = True
    assert _v2_acceptance_ok(summary, [conserved]) is False


def test_visual_audit_v2_full_model_evidence_requires_six_distinct_verified_images(
    tmp_path: Path,
) -> None:
    comparisons: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for index, row in enumerate(VISUAL_AUDIT_VIEWS):
        angle = str(row["name"])
        path = tmp_path / f"{angle}.png"
        Image.new("RGB", (4, 4), (20 + index, 40, 60)).save(path)
        comparisons[angle] = str(path)
        hashes[angle] = hashlib.sha256(path.read_bytes()).hexdigest()
    contact_sheet = tmp_path / "contact.png"
    Image.new("RGB", (8, 8), (80, 100, 120)).save(contact_sheet)
    composite = {
        # Production JSON is written with sort_keys=True; validation must restore
        # canonical camera order rather than depending on mapping insertion order.
        "candidate_comparisons": dict(sorted(comparisons.items())),
        "candidate_comparison_sha256": dict(sorted(hashes.items())),
        "contact_sheet": str(contact_sheet),
        "contact_sheet_sha256": hashlib.sha256(contact_sheet.read_bytes()).hexdigest(),
    }
    normalized = _validate_v2_full_model_evidence(composite)
    assert tuple(normalized["comparisons"]) == tuple(str(row["name"]) for row in VISUAL_AUDIT_VIEWS)

    Path(comparisons["side"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence hash changed"):
        _validate_v2_full_model_evidence(composite)


def test_visual_audit_v2_asset_verdict_requires_full_geometry_and_reference_evidence() -> None:
    verdict = {
        "overall_verdict": "PASS",
        "full_model_angle_reviews": _full_model_angle_reviews(),
        "full_model_contact_sheet_direct_image_inspection": True,
        "full_model_contact_sheet_observations": "All six comparisons are present and legible.",
        "full_model_contact_sheet_verdict": "PASS",
        "full_model_geometry_coherent": True,
        "full_model_geometry_observations": "The assembled silhouette is contiguous in all six views.",
        "reference_status": "exact_item",
        "reference_identity": "Hwando",
        "reference_urls": ["https://example.test/hwando"],
        "reference_observations": "The curved blade and wrapped grip match the exact item image.",
    }
    corpus_row = {"model_category": "weapon_sword", "virtual_path": "character/model/hwando.pac"}
    normalized = _validate_v2_asset_verdict(verdict, corpus_row)
    assert normalized["full_model_geometry_coherent"] is True
    assert normalized["reference_identity"] == "Hwando"

    verdict["full_model_angle_reviews"][0]["direct_image_inspection"] = False
    with pytest.raises(ValueError, match="requires direct image inspection"):
        _validate_v2_asset_verdict(verdict, corpus_row)
    verdict["full_model_angle_reviews"] = _full_model_angle_reviews()
    verdict["full_model_contact_sheet_direct_image_inspection"] = False
    with pytest.raises(ValueError, match="direct contact-sheet"):
        _validate_v2_asset_verdict(verdict, corpus_row)
    verdict["full_model_contact_sheet_direct_image_inspection"] = True
    verdict["full_model_angle_reviews"] = verdict["full_model_angle_reviews"][:1]
    with pytest.raises(ValueError, match="one review row for each"):
        _validate_v2_asset_verdict(verdict, corpus_row)
    verdict["full_model_angle_reviews"] = _full_model_angle_reviews(coherent=False)
    verdict["full_model_geometry_coherent"] = False
    with pytest.raises(ValueError, match="Broken full-model geometry"):
        _validate_v2_asset_verdict(verdict, corpus_row)


def test_visual_audit_v2_reported_sword_mismatch_is_a_hard_fail() -> None:
    verdict = {
        "overall_verdict": "PASS",
        "full_model_angle_reviews": _full_model_angle_reviews(),
        "full_model_contact_sheet_direct_image_inspection": True,
        "full_model_contact_sheet_observations": "All six comparisons are present and legible.",
        "full_model_contact_sheet_verdict": "PASS",
        "full_model_geometry_coherent": True,
        "full_model_geometry_observations": "The complete sword silhouette is coherent.",
        "reference_status": "exact_item",
        "reference_identity": "Vessel of Dark Pursuit",
        "reference_urls": ["https://example.test/vessel"],
        "reference_observations": "Compared against the exact target image.",
        "reported_target_match": False,
        "reported_target_observations": "The guard color does not match the target.",
    }
    corpus_row = {"model_category": "weapon_sword", "virtual_path": REQUIRED_SWORD_PATH}
    with pytest.raises(ValueError, match="target mismatch"):
        _validate_v2_asset_verdict(verdict, corpus_row)
    verdict["overall_verdict"] = "FAIL"
    normalized = _validate_v2_asset_verdict(verdict, corpus_row)
    assert normalized["reported_target_match"] is False


def test_visual_audit_v2_semantic_and_source_board_checks_cover_every_submesh() -> None:
    asset = {
        "asset_id": "asset",
        "submesh_count": 2,
        "binding_conservation": [
            {
                "conserved": True,
                "dropped_parameters": [],
                "cross_owner_bindings": [],
                "layer_as_base_bindings": [],
            },
            {
                "conserved": True,
                "dropped_parameters": [],
                "cross_owner_bindings": [],
                "layer_as_base_bindings": [],
            },
        ],
        "initial_resident_material_equivalence": {"equivalent": True, "mismatches": []},
        "source_boards": {
            "boards": [
                {"submesh_index": 0, "path": "zero.png", "sha256": "a" * 64},
                {"submesh_index": 1, "path": "one.png", "sha256": "b" * 64},
            ]
        },
    }
    assert _semantic_conservation_ok([asset]) is True
    assert _source_board_coverage_ok([asset]) is True
    asset["binding_conservation"].append("ignored-junk")
    assert _semantic_conservation_ok([asset]) is False
    asset["binding_conservation"].pop()
    asset["source_boards"]["boards"].append("ignored-junk")
    assert _source_board_coverage_ok([asset]) is False
    asset["source_boards"]["boards"].pop()
    asset["binding_conservation"] = asset["binding_conservation"][:1]
    assert _semantic_conservation_ok([asset]) is False
    asset["source_boards"]["boards"] = asset["source_boards"]["boards"][:1]
    assert _source_board_coverage_ok([asset]) is False


def test_visual_audit_v2_corpus_acceptance_requires_exact_120_selection() -> None:
    candidates = select_visual_audit_v2_candidates(_synthetic_candidates())
    coverage = Counter(tag for row in candidates for tag in row.graph_tags)
    corpus = {
        "schema": "cdmw_mesh_visual_audit_corpus_v2",
        "asset_count": len(candidates),
        "coverage": dict(coverage),
        "assets": [
            {
                "index": index,
                "asset_id": f"{index:03d}-asset",
                "virtual_path": row.virtual_path,
                "model_category": row.category,
            }
            for index, row in enumerate(candidates, start=1)
        ],
    }
    assert _v2_corpus_acceptance_ok(corpus) is True
    corpus["assets"].append("ignored-junk")
    assert _v2_corpus_acceptance_ok(corpus) is False
    corpus["assets"].pop()
    corpus["assets"][-1]["virtual_path"] = corpus["assets"][0]["virtual_path"]
    assert _v2_corpus_acceptance_ok(corpus) is False


def test_source_board_records_pac_authority_and_per_channel_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.mesh_harness.visual_audit_source_boards as boards

    preview = tmp_path / "decoded.png"
    Image.new("RGBA", (4, 2), (32, 96, 224, 128)).save(preview)
    dds = tmp_path / "source.dds"
    dds.write_bytes(b"DDS synthetic")
    monkeypatch.setattr(boards, "ensure_native_dds_preview_png", lambda *_args, **_kwargs: preview)
    monkeypatch.setattr(
        boards,
        "_dds_header_row",
        lambda _path: {
            "source_width": 4,
            "source_height": 2,
            "source_mip_count": 1,
            "source_format": "BC7",
        },
    )
    material_state = {
        "submeshes": [
            {
                "submesh_index": 0,
                "material_name": "CD_TEST_MAT",
                "shader_family": "standard_v2",
                "parameters": {"base_tint_color": [1.0, 0.75, 0.25, 1.0]},
                "source_contract": {"schema": "cdmw_pac_material_graph_v1"},
                "binding_conservation": {"conserved": True},
            }
        ]
    }
    result = build_source_material_boards(
        "001-test",
        [
            {
                "submesh_index": 0,
                "source_path": str(dds),
                "archive_path": "texture/test.dds",
                "archive_provenance": {"pamt_path": "0.pamt", "paz_path": "0.paz"},
                "semantic": "material",
                "parameter_name": "_materialMap",
                "owner_slot_index": 0,
                "owner_wrapper_item_id": "CD_TEST_MAT",
                "binding_authority": "pac_xml_exact",
                "binding_disposition": "promoted",
                "source_kind": "packed_material",
            }
        ],
        material_state,
        tmp_path / "boards",
    )

    assert result["schema"] == SOURCE_BOARD_SCHEMA
    assert Path(result["boards"][0]["path"]).is_file()
    texture = result["textures"][0]
    assert texture["owner_slot_index"] == 0
    assert texture["owner_wrapper_item_id"] == "CD_TEST_MAT"
    assert texture["binding_authority"] == "pac_xml_exact"
    assert texture["channel_statistics"]["R"]["mean"] == 32.0
    assert texture["channel_statistics"]["A"]["mean"] == 128.0
    assert texture["alpha_coverage"]["nonopaque_fraction"] == 1.0


def test_visual_audit_corpus_compacts_duplicate_graph_and_source_board_details(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source-board-manifest.json"
    manifest_path.write_text('{"textures":[{"large":"detail"}]}', encoding="utf-8")
    source_summary = _source_board_corpus_summary(
        {
            "schema": SOURCE_BOARD_SCHEMA,
            "asset_id": "001-test",
            "manifest_path": str(manifest_path),
            "boards": [{"submesh_index": 0, "path": "board.png", "sha256": "a" * 64}],
            "textures": [{"channel_statistics": {"R": {"samples": list(range(512))}}}],
        }
    )
    graph_summary = _pac_material_graph_summary(
        {
            "version": 1,
            "schema": "cdmw_pac_material_graph_v1",
            "source_submesh_index": 0,
            "graph_hash": "b" * 64,
            "bindings": [
                {"binding_disposition": "promoted", "large": list(range(512))},
                {"binding_disposition": "recorded", "large": list(range(512))},
            ],
            "parameters": [{"large": list(range(512))}],
            "wrappers": [{"large": list(range(512))}],
            "binding_conservation": {"conserved": True},
        }
    )

    assert "textures" not in source_summary
    assert source_summary["texture_count"] == 1
    assert source_summary["manifest_evidence"]["sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert "bindings" not in graph_summary
    assert "parameters" not in graph_summary
    assert graph_summary["binding_count"] == 2
    assert graph_summary["binding_dispositions"] == {"promoted": 1, "recorded": 1}
    assert graph_summary["binding_conservation"] == {"conserved": True}


def test_modify_original_subset_selects_twelve_unique_production_roles() -> None:
    rows = (
        (REQUIRED_SWORD_PATH, "weapon_sword", ()),
        (PRIOR_CONCERN_SWORD_PATH, "weapon_sword", ()),
        ("character/model/test/armor/mixed_ub.pac", "armor_body", ("mixed_hard_soft_candidate",)),
        ("character/model/test/armor/metal_hel.pac", "helmet_mask", ("true_metal_control_candidate",)),
        ("character/model/test/armor/soft_hel.pac", "helmet_mask", ("soft_control_candidate",)),
        ("character/model/test/armor/foot_boot.pac", "equipment_small", ()),
        ("character/model/test/weapon/shield.pac", "weapon_shield", ()),
        ("character/model/test/armor/belt.pac", "equipment_small", ()),
        ("character/model/test/armor/cloak.pac", "equipment_soft", ()),
        ("character/model/test/weapon/pike.pac", "weapon_other", ()),
        ("character/model/test/head/hair.pac", "regression_control", ()),
        ("character/model/test/armor/glasses.pac", "regression_control", ()),
    )
    specs = tuple(
        VisualAuditAssetSpec(
            index=index,
            asset_id=f"{index:03d}-test",
            virtual_path=path,
            model_category=category,
            coverage_tags=(category,),
            selection_reason="test",
            graph_tags=tags,
        )
        for index, (path, category, tags) in enumerate(rows, 1)
    )

    selected = select_modify_original_subset(specs)

    assert tuple(row.role for row in selected) == MODIFY_ORIGINAL_SUBSET_ROLES
    assert len({row.spec.virtual_path for row in selected}) == 12
