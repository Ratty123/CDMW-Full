from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.mesh_harness import (
    equipment_material_performance,
    equipment_material_performance_cli,
)
from tools.mesh_harness.equipment_material_capture import (
    _capture_source_manifest_matches,
)
from tools.mesh_harness.equipment_material_performance import (
    A48F00CE_BASELINE_SAMPLES_SCHEMA,
    EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA,
    PRODUCTION_RENDERER_PATH,
    EquipmentPerformanceError,
    _validate_repeated_audit_report,
    build_equipment_performance_summary,
    build_equipment_repetition_plan,
    evaluate_equipment_repetition_results,
)


def _write_equipment_performance_census(tmp_path):
    evidence = tmp_path / "evidence"
    census_identity = _census_identity()
    identities = [
        "alpha.pac",
        "cd_phm_02_sword_0009.pac",
        "gamma.pac",
        "delta.pac",
    ]
    facts = [
        (10, 1_000, 2, ["metal"]),
        (20, 2_000, 3, ["metal", "leather"]),
        (40, 1_500, 6, ["cloth"]),
        (40, 9_000, 4, ["metal", "cloth", "leather"]),
    ]
    manifest_assets: list[dict[str, object]] = []
    for ordinal in range(3):
        asset_id = f"{ordinal:04d}-source-only-{ordinal}"
        identity = f"source-only-{ordinal}.pac"
        manifest_assets.append(
            {"ordinal": ordinal, "asset_id": asset_id, "identity": identity}
        )
        report_path = evidence / "assets" / asset_id / "asset-report.json"
        _write_json(
            report_path,
            {
                "schema": "cdmw_equipment_material_capture_v1",
                "status": "source_only_captured",
                "identity": identity,
                "asset_id": asset_id,
                "catalogue_ordinal": ordinal,
                "census_identity": census_identity,
            },
        )
        manifest_assets[-1]["report_sha256"] = hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest()
    for offset, (identity, row_facts) in enumerate(
        zip(identities, facts, strict=True), 3
    ):
        asset_id = f"{offset:04d}-{Path(identity).stem}"
        manifest_assets.append(
            {"ordinal": offset, "asset_id": asset_id, "identity": identity}
        )
        _write_instrumented_asset(
            evidence / "assets" / asset_id,
            ordinal=offset,
            asset_id=asset_id,
            identity=identity,
            graph_edges=row_facts[0],
            unique_dds_bytes=row_facts[1],
            visible_submeshes=row_facts[2],
            categories=row_facts[3],
            base_ms=float((offset - 2) * 10),
            census_identity=census_identity,
        )
        report_path = evidence / "assets" / asset_id / "asset-report.json"
        manifest_assets[-1]["report_sha256"] = hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest()
    _write_json(
        evidence / "capture-manifest.json",
        {
            "schema": "cdmw_equipment_material_capture_manifest_v1",
            "capture_complete": True,
            "failed_count": 0,
            "missing_count": 0,
            "assets": manifest_assets,
            "census_identity": census_identity,
            "capture_binaries": {
                "preview_core": {"sha256": "a" * 64},
                "rust_helper": {"sha256": "b" * 64},
            },
        },
    )

    baseline = tmp_path / "baseline"
    for offset, identity in enumerate(identities[:2], 3):
        asset_id = f"{offset:04d}-{Path(identity).stem}"
        root = baseline / asset_id
        _write_json(
            root / "asset-report.json",
            {
                "schema": "cdmw_equipment_material_capture_v1",
                "identity": identity,
                "wall_ms": 100.0,
            },
        )
        _write_json(root / "before" / "audit-report.json", {"wall_ms": 50.0})
        _write_json(root / "after" / "audit-report.json", {"wall_ms": 75.0})
    _write_json(
        baseline / "duplicate-alpha" / "asset-report.json",
        {
            "schema": "cdmw_equipment_material_capture_v1",
            "identity": identities[0],
            "wall_ms": 1.0,
        },
    )
    return evidence, identities, baseline, census_identity


def test_summary_aggregates_exact_metrics_and_selects_deterministic_worst_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    evidence, identities, baseline, census_identity = _write_equipment_performance_census(tmp_path)

    summary = build_equipment_performance_summary(
        evidence,
        baseline_root=baseline,
        expected_logical_count=7,
    )

    assert summary["census"]["complete"] is True
    assert summary["census"]["instrumented_renderable_count"] == 4
    assert summary["integrity"]["ok"] is True
    assert summary["distributions"]["asset_wall_ms"] == {
        "count": 4,
        "min": 10.0,
        "median": 25.0,
        "p95": 40.0,
        "max": 40.0,
        "mean": 25.0,
    }
    alpha_metrics = summary["asset_metrics"][0]["metrics"]
    assert alpha_metrics["direct_process_boundary_overhead_ms"] == 10.0
    assert alpha_metrics["full_process_boundary_overhead_ms"] == 11.0
    assert alpha_metrics["first_usable_ms"] == 34.5
    assert alpha_metrics["full_texture_readiness_ms"] == 47.0
    assert summary["worst_cases"]["graph_edge_count"]["identity"] == "delta.pac"
    assert summary["worst_cases"]["unique_dds_bytes"]["identity"] == "delta.pac"
    assert summary["worst_cases"]["visible_submesh_count"]["identity"] == "gamma.pac"
    assert summary["worst_cases"]["material_region_count"]["identity"] == "gamma.pac"
    assert (
        summary["worst_cases"]["mixed_material_category_count"]["identity"]
        == "delta.pac"
    )
    assert summary["repetition_plan"]["status"] == "ready_for_production_runner"
    assert summary["repetition_plan"]["targets"][0]["identity"] == identities[1]
    assert (
        summary["repetition_plan"]["repetition_execution_command_status"]
        == "missing_required_local_inputs"
    )
    comparison = summary["baseline_comparison"]
    assert comparison["matched_asset_count"] == 2
    assert comparison["duplicate_baseline_identities"] == ["alpha.pac"]
    assert comparison["metrics"]["direct_renderer_wall_ms"]["status"] in {
        "pass",
        "fail",
    }
    assert comparison["metrics"]["first_usable_ms"]["status"] == "missing_baseline"
    assert summary["acceptance_status"] == "incomplete"

    targets = summary["repetition_plan"]["targets"]
    current_repetitions = _repetition_payload(
        targets[0], first=100.0, full=1_000.0, warm=100.0
    )
    baseline_repetition_packets = tmp_path / "baseline-repetition-packets"
    _write_json(
        baseline_repetition_packets
        / str(targets[0]["asset_id"])
        / "baseline-samples.json",
        _baseline_repetition_payload(
            targets[0],
            first=1_000.0,
            full=900.0,
            warm=100.0,
            root=baseline_repetition_packets / str(targets[0]["asset_id"]),
        ),
    )
    for target in targets[1:]:
        current_repetitions["samples"].extend(
            _repetition_payload(
                target, first=100.0, full=1_000.0, warm=100.0
            )["samples"]
        )
        packet_root = baseline_repetition_packets / str(target["asset_id"])
        _write_json(
            packet_root / "baseline-samples.json",
            _baseline_repetition_payload(
                target,
                first=1_000.0,
                full=900.0,
                warm=100.0,
                root=packet_root,
            ),
        )
    current_repetitions["census_manifest_sha256"] = hashlib.sha256(
        (evidence / "capture-manifest.json").read_bytes()
    ).hexdigest()
    current_path = tmp_path / "current-repetitions.json"
    _write_json(current_path, current_repetitions)

    missing_rigorous_baseline = build_equipment_performance_summary(
        evidence,
        baseline_root=baseline,
        repetition_results_path=current_path,
        expected_logical_count=7,
    )
    assert missing_rigorous_baseline["acceptance_status"] == "incomplete"
    assert missing_rigorous_baseline["baseline_comparison"]["status"] == "incomplete"
    assert missing_rigorous_baseline["repetition_acceptance"]["status"] == "incomplete"

    accepted_with_partial_legacy_context = build_equipment_performance_summary(
        evidence,
        baseline_root=baseline,
        repetition_results_path=current_path,
        baseline_repetition_results_path=baseline_repetition_packets,
        expected_logical_count=7,
    )
    assert accepted_with_partial_legacy_context["baseline_comparison"]["status"] == (
        "incomplete"
    )
    assert accepted_with_partial_legacy_context["repetition_acceptance"]["status"] == (
        "pass"
    )
    assert accepted_with_partial_legacy_context["acceptance_status"] == "pass"


def test_incomplete_census_emits_exact_deferred_repetition_plan(tmp_path: Path) -> None:
    plan = build_equipment_repetition_plan(
        tmp_path,
        targets=[],
        census_complete=False,
        expected_logical_count=2_057,
        observed_instrumented_count=197,
    )

    assert plan["status"] == "waiting_for_complete_census"
    assert plan["cold_repetitions_per_target"] == 7
    assert plan["warm_repetitions_per_target"] == 20
    assert plan["runner_contract"]["required_results_schema"].endswith(
        "repetition_results_v1"
    )
    assert "--require-complete" in plan["post_census_aggregation_command"]
    assert "do not relabel" in plan["runner_contract"]["current_helper_note"]


def test_repetition_acceptance_applies_thresholds_and_rejects_warm_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )
    current = _repetition_payload(target, first=150.0, full=350.0, warm=105.0)

    accepted = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )

    assert accepted["status"] == "pass"
    assert baseline["baseline_provenance_sha256"] == (
        "97303066250c258049f838983069f697d18e079e9f40916cd518e06d8ed8cc00"
    )
    assert accepted["coverage"] == [{"asset_id": "rhett", "cold": 7, "warm": 20}]
    assert "material_graph_version" not in baseline["cold_samples"][0]
    assert "physical_upload_identity" not in baseline["cold_samples"][0]
    first_gate = accepted["baseline_comparison"]["targets"]["rhett"]["first_usable_ms"]
    assert first_gate["gates"][0]["allowed_max"] == 150.0

    current["samples"][0]["material_graph_version"] = 3
    rejected_current_contract = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert any(
        row["gate"] == "material_graph_version"
        for row in rejected_current_contract["failures"]
    )
    current["samples"][0]["material_graph_version"] = 4

    current["samples"][0]["peak_private_bytes"] = 1_051.0
    rejected_memory = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert "rhett:peak_private_bytes" in rejected_memory["baseline_comparison"][
        "failed_metrics"
    ]
    current["samples"][0]["peak_private_bytes"] = 1_000.0

    current["samples"][0]["native_service_used"] = True
    rejected_cold = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert any(
        row["gate"] == "cold_fresh_preview_core_process"
        for row in rejected_cold["failures"]
    )
    current["samples"][0]["native_service_used"] = False
    current["samples"][0]["direct_audit_completion_wall_ms"] += 10.0
    rejected_phase_formula = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert any(
        row["gate"] == "cold_process_boundary_overhead"
        for row in rejected_phase_formula["failures"]
    )
    current["samples"][0]["direct_audit_completion_wall_ms"] -= 10.0
    current["samples"][-1]["resource_reload_count"] = 1
    rejected = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert rejected["status"] == "fail"
    assert any(row["gate"] == "warm_resource_reload" for row in rejected["failures"])

    current["samples"][-1]["resource_reload_count"] = 0
    baseline.pop("baseline_provenance_sha256")
    rejected_baseline = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert rejected_baseline["status"] == "incomplete"
    assert (
        rejected_baseline["baseline_comparison"]["reason"]
        == "baseline_repetition_contract_invalid"
    )

    baseline["baseline_provenance_sha256"] = _canonical_sha256(
        baseline["baseline_provenance"]
    )
    current["samples"][0]["identity"] = "another.pac"
    rejected_identity = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert rejected_identity["status"] == "fail"
    assert any(row["gate"] == "target_identity" for row in rejected_identity["failures"])


def test_current_repetitions_keep_v4_v10_schema8_and_sha_dedup_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )
    current = _repetition_payload(target, first=100.0, full=100.0, warm=100.0)

    for field, bad_value, expected_gate in (
        ("renderer_path", "legacy", "production_path"),
        ("preview_core_schema_version", 7, "preview_core_schema"),
        ("material_graph_version", 3, "material_graph_version"),
        ("material_semantics_version", 9, "material_semantics_version"),
        ("physical_upload_identity", "logical_edge", "physical_upload_identity"),
        ("duplicate_upload_key_count", 1, "duplicate_upload_key"),
    ):
        forged = _json_clone(current)
        forged["samples"][0][field] = bad_value
        rejected = evaluate_equipment_repetition_results(
            forged,
            baseline=baseline,
            expected_targets=[target],
        )
        assert expected_gate in {str(row["gate"]) for row in rejected["failures"]}


def test_baseline_repetition_rejects_missing_and_forged_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    current = _repetition_payload(target, first=100.0, full=1_000.0, warm=100.0)
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )

    missing = _json_clone(baseline)
    missing.pop("baseline_provenance")
    rejected_missing = evaluate_equipment_repetition_results(
        current,
        baseline=missing,
        expected_targets=[target],
    )
    assert rejected_missing["baseline_comparison"]["reason"] == (
        "baseline_repetition_contract_invalid"
    )
    assert "baseline_provenance" in _baseline_failure_gates(rejected_missing)

    forged = _json_clone(baseline)
    forged["baseline_provenance"]["base_revision"] = "f" * 40
    _rebind_baseline_provenance(forged)
    rejected_forged = evaluate_equipment_repetition_results(
        current,
        baseline=forged,
        expected_targets=[target],
    )
    assert "baseline_base_revision" in _baseline_failure_gates(rejected_forged)

    forged_binary = _json_clone(baseline)
    forged_binary["baseline_provenance"]["capture_binaries"]["instrumented_rust"][
        "sha256"
    ] = "f" * 64
    _rebind_baseline_provenance(forged_binary)
    rejected_binary = evaluate_equipment_repetition_results(
        current,
        baseline=forged_binary,
        expected_targets=[target],
    )
    assert "baseline_binary_provenance" in _baseline_failure_gates(rejected_binary)

    monkeypatch.setattr(
        equipment_material_performance,
        "_baseline_binary_file_matches",
        lambda *_args, **_kwargs: False,
    )
    rejected_missing_binary = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert "baseline_binary_file_identity" in _baseline_failure_gates(
        rejected_missing_binary
    )
    _accept_audited_baseline_binaries(monkeypatch)

    forged_sample_binding = _json_clone(baseline)
    forged_sample_binding["cold_samples"][0]["baseline_provenance_sha256"] = (
        "f" * 64
    )
    rejected_sample_binding = evaluate_equipment_repetition_results(
        current,
        baseline=forged_sample_binding,
        expected_targets=[target],
    )
    assert "baseline_process_identity" in _baseline_failure_gates(
        rejected_sample_binding
    )


def test_baseline_repetition_rejects_missing_positive_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    current = _repetition_payload(target, first=100.0, full=1_000.0, warm=100.0)
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )
    baseline["cold_samples"][0]["phase_timings"]["first_textured_frame_ms"] = 0
    baseline["warm_batch"]["runtime_dds"]["reported_gpu_resident_bytes"] = 0

    rejected = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )

    gates = _baseline_failure_gates(rejected)
    assert "baseline_phase_timings" in gates
    assert "baseline_gpu_resident_bytes" in gates


def test_baseline_repetition_rejects_nonresident_warm_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    current = _repetition_payload(target, first=100.0, full=1_000.0, warm=100.0)
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )
    baseline["warm_samples"][-1]["resource_reloads_between_repetitions"] = 1
    baseline["warm_samples"][-1]["resident_batch_id"] = "another-helper-process"

    rejected = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )

    gates = _baseline_failure_gates(rejected)
    assert "baseline_warm_residency" in gates


def test_raw_baseline_requires_execution_attestation_reports_and_every_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _accept_audited_baseline_binaries(monkeypatch)
    target = {"asset_id": "rhett", "identity": "cd_phm_02_sword_0009.pac"}
    current = _repetition_payload(target, first=100.0, full=100.0, warm=100.0)
    baseline = _baseline_repetition_payload(
        target,
        first=100.0,
        full=100.0,
        warm=100.0,
        root=tmp_path / "baseline",
    )

    forged_attestation = _json_clone(baseline)
    forged_attestation["cold_samples"][0]["execution_attestation"][
        "fallback_used"
    ] = True
    rejected_attestation = evaluate_equipment_repetition_results(
        current,
        baseline=forged_attestation,
        expected_targets=[target],
    )
    assert "baseline_execution_attestation" in _baseline_failure_gates(
        rejected_attestation
    )

    report_path = Path(str(baseline["cold_samples"][0]["report_path"]))
    report_path.write_text("{}", encoding="utf-8")
    rejected_report = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target],
    )
    assert "baseline_report_integrity" in _baseline_failure_gates(rejected_report)

    missing_target = {"asset_id": "worst", "identity": "worst-case.pac"}
    missing_current = _repetition_payload(
        missing_target, first=100.0, full=100.0, warm=100.0
    )
    current["samples"].extend(missing_current["samples"])
    rejected_coverage = evaluate_equipment_repetition_results(
        current,
        baseline=baseline,
        expected_targets=[target, missing_target],
    )
    gates = _baseline_failure_gates(rejected_coverage)
    assert {"baseline_cold_coverage", "baseline_warm_coverage"} <= gates


def test_repeated_rust_audit_requires_one_resident_load_and_twenty_timings(
    tmp_path: Path,
) -> None:
    source_manifest_path = tmp_path / "rust-manifest.json"
    _write_json(source_manifest_path, {"schema": "test"})
    report = {
        "schema": "cdmw_rust_material_audit_capture_v2",
        "ok": True,
        "renderer": "wgpu_d3d12_rust",
        "adapter": {"backend": "Dx12"},
        "full_model_only": True,
        "source_manifest": {
            "path": str(source_manifest_path),
            "bytes": source_manifest_path.stat().st_size,
            "sha256": hashlib.sha256(source_manifest_path.read_bytes()).hexdigest(),
        },
        "repetition_count": 20,
        "capture_count": 120,
        "phase_timings": _phase_timings(
            texture_resources_ready_ms=8.0,
            first_textured_frame_ms=10.0,
            audit_completion_ms=200.0,
        ),
        "captures": [
            {
                "name": name,
                "capture_kind": "full_model",
                "repetition_index": repetition,
                "dds_textures_uploaded": 2,
                "frames": {
                    "textured": {"non_background_pixels": 10},
                    "base_color": {"non_background_pixels": 10},
                    "part_id": {"non_background_pixels": 10},
                },
            }
            for repetition in range(20)
            for name in (
                "front",
                "three-quarter-front",
                "side",
                "back",
                "slightly-above",
                "slightly-below",
            )
        ],
        "dds_resources_uploaded_once_for_capture_set": True,
        "source_dds": {
            "available": True,
            "measurement": "actual_rust_source_dds_decode_events_v1",
            "each_source_binary_decoded_at_most_once": True,
            "full_source_decode_complete": True,
            "copied_source_dds_count": 2,
            "unique_source_dds_count": 2,
        },
        "runtime_dds": {
            "resource_count": 2,
            "logical_resource_count": 3,
            "unique_binary_count": 2,
            "upload_key": "dds_sha256",
            "role_specific_sampling_views_share_one_physical_upload": True,
            "renderer_uploads_match_unique_binaries": True,
            "renderer_reported_upload_count": 2,
            "no_duplicate_upload_keys": True,
            "duplicate_upload_key_count": 0,
            "uploaded_resource_bytes": 1_000,
            "unique_binary_bytes": 1_000,
            "reported_gpu_resident_bytes": 999,
        },
        "warm_cache_proof": {
            "schema": "cdmw_rust_warm_material_capture_v1",
            "valid": True,
            "package_load_count": 1,
            "renderer_device_count": 1,
            "renderer_batch_count": 1,
            "texture_upload_pass_count": 1,
            "dds_textures_uploaded_once_for_repetition_set": True,
            "package_reloads_between_repetitions": 0,
            "resource_reloads_between_repetitions": 0,
            "per_repetition_wall_ms": [10.0 + index for index in range(20)],
        },
    }

    _validate_repeated_audit_report(
        report,
        repetitions=20,
        expected_manifest_path=source_manifest_path,
    )
    assert _capture_source_manifest_matches(report, source_manifest_path) is True
    report["source_manifest"]["sha256"] = "0" * 64
    assert _capture_source_manifest_matches(report, source_manifest_path) is False
    with pytest.raises(EquipmentPerformanceError, match="requested source manifest"):
        _validate_repeated_audit_report(
            report,
            repetitions=20,
            expected_manifest_path=source_manifest_path,
        )
    report["source_manifest"]["sha256"] = hashlib.sha256(
        source_manifest_path.read_bytes()
    ).hexdigest()
    report["warm_cache_proof"]["resource_reloads_between_repetitions"] = 1
    with pytest.raises(EquipmentPerformanceError, match="warm-cache proof"):
        _validate_repeated_audit_report(report, repetitions=20)
    report["warm_cache_proof"]["resource_reloads_between_repetitions"] = 0
    report["runtime_dds"]["upload_key"] = "dds_sha256+texture_role"
    with pytest.raises(EquipmentPerformanceError, match="dedup/capture contract"):
        _validate_repeated_audit_report(report, repetitions=20)
    report["runtime_dds"]["upload_key"] = "dds_sha256"
    report["phase_timings"]["first_textured_frame_ms"] = 250.0
    with pytest.raises(EquipmentPerformanceError, match="not monotonic"):
        _validate_repeated_audit_report(report, repetitions=20)


def test_cli_requires_the_exact_census_and_full_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="exactly 2,057"):
        equipment_material_performance_cli.main(
            [
                "--evidence-root",
                str(tmp_path),
                "--expected-logical-count",
                "7",
            ]
        )

    census = {
        "expected_logical_count": 2_057,
        "manifest_asset_count": 2_057,
        "instrumented_renderable_count": 2_054,
        "source_only_count": 3,
        "missing_or_uninstrumented_count": 0,
        "complete": True,
    }
    monkeypatch.setattr(
        equipment_material_performance_cli,
        "build_equipment_performance_summary",
        lambda *args, **kwargs: {
            "acceptance_status": "incomplete",
            "census": census,
            "capture_manifest": {"census_identity": {}},
            "integrity": {"ok": True},
            "worst_cases": {},
            "repetition_plan": {},
            "baseline_comparison": {"status": "incomplete"},
            "repetition_acceptance": {"status": "incomplete"},
        },
    )
    assert (
        equipment_material_performance_cli.main(
            ["--evidence-root", str(tmp_path), "--require-complete"]
        )
        == 2
    )

    protected = tmp_path / "census"
    protected.mkdir()
    with pytest.raises(ValueError, match="outside"):
        equipment_material_performance_cli._require_external_summary_output(
            protected / "summary.json", protected_roots=[protected]
        )


def _write_instrumented_asset(
    root: Path,
    *,
    ordinal: int,
    asset_id: str,
    identity: str,
    graph_edges: int,
    unique_dds_bytes: int,
    visible_submeshes: int,
    categories: list[str],
    base_ms: float,
    census_identity: dict[str, object],
) -> None:
    full_manifest = {
        "preview_core_geometry": {"batches": [{} for _ in range(visible_submeshes)]},
        "material_presentations": [
            {"material_category": category} for category in categories
        ],
    }
    manifest_path = root / "manifests" / "rust-full-manifest.json"
    _write_json(manifest_path, full_manifest)
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    source = {
        "available": True,
        "measurement": "actual_rust_source_dds_decode_events_v1",
        "each_source_binary_decoded_at_most_once": True,
        "full_source_decode_complete": True,
        "copied_source_dds_count": 1,
        "unique_source_dds_count": 2,
        "unique_source_dds_bytes": unique_dds_bytes,
    }
    runtime = {
        "resource_count": 1,
        "logical_resource_count": 2,
        "unique_binary_count": 1,
        "upload_key": "dds_sha256",
        "role_specific_sampling_views_share_one_physical_upload": True,
        "renderer_uploads_match_unique_binaries": True,
        "renderer_reported_upload_count": 1,
        "no_duplicate_upload_keys": True,
        "duplicate_upload_key_count": 0,
        "reported_gpu_resident_bytes": unique_dds_bytes,
        "uploaded_resource_bytes": unique_dds_bytes,
        "unique_binary_bytes": unique_dds_bytes,
    }
    process = {
        "process_wall_ms": base_ms + 3,
        "renderer_wall_ms": base_ms + 2,
        "phase_timings": _phase_timings(
            texture_resources_ready_ms=2.0,
            first_textured_frame_ms=2.5,
            audit_completion_ms=3.0,
        ),
        "peak_private_bytes": 1_000 + ordinal,
        "peak_working_set_bytes": 900 + ordinal,
        "timed_out": False,
        "exit_code": 0,
    }
    _write_json(
        root / "asset-report.json",
        {
            "schema": "cdmw_equipment_material_capture_v1",
            "status": "captured",
            "identity": identity,
            "asset_id": asset_id,
            "catalogue_ordinal": ordinal,
            "census_identity": census_identity,
            "capture_binaries": {
                "preview_core": {"sha256": "a" * 64},
                "rust_helper": {"sha256": "b" * 64},
            },
            "wall_ms": base_ms,
            "renderer_path": PRODUCTION_RENDERER_PATH,
            "python_material_synthesis_used": False,
            "preview_core": {
                "diagnostics": {
                    "fallback_reason": "",
                    "service_recycle_reason": "",
                    "process_private_bytes": 800 + ordinal,
                    "process_working_set_bytes": 700 + ordinal,
                }
            },
            "technical_gates": {"capture": True},
            "rust_packages": {
                "full_manifest": {
                    "path": "manifests/rust-full-manifest.json",
                    "sha256": manifest_sha,
                }
            },
            "composites": {
                "material_region_sheets": [
                    {"material_index": index} for index in range(visible_submeshes)
                ]
            },
            "performance": {
                "schema": "cdmw_equipment_material_performance_v1",
                "preview_core": {"elapsed_ms": base_ms + 1, "wall_ms": base_ms + 1},
                "package_build": {"direct_ms": base_ms + 1, "full_ms": base_ms + 2},
                "render": {
                    "direct": process,
                    "full": {**process, "process_wall_ms": base_ms + 4},
                },
                "resources": {
                    "logical_texture_edge_count": graph_edges,
                    "direct_source_dds": source,
                    "full_source_dds": source,
                    "direct_runtime_dds": runtime,
                    "full_runtime_dds": runtime,
                },
            },
        },
    )


def _repetition_payload(
    target: dict[str, object], *, first: float, full: float, warm: float
) -> dict[str, object]:
    common = {
        "asset_id": target["asset_id"],
        "identity": target["identity"],
        "renderer_path": PRODUCTION_RENDERER_PATH,
        "preview_core_schema_version": 8,
        "material_graph_version": 4,
        "material_semantics_version": 10,
        "renderer": "wgpu_d3d12_rust",
        "adapter_backend": "dx12",
        "python_material_synthesis_used": False,
        "timed_out": False,
        "process_restart_count": 0,
        "renderer_fallback": False,
        "duplicate_upload_key_count": 0,
        "duplicate_parameter_texture_bytes": 0,
        "physical_upload_identity": "dds_sha256",
        "one_physical_upload_per_binary": True,
    }
    native_wall = 20.0
    direct_build = 10.0
    full_build = 20.0
    direct_with_boundary = first - native_wall - direct_build
    full_with_boundary = full - native_wall - direct_build - full_build
    direct_phase = _phase_timings(
        texture_resources_ready_ms=direct_with_boundary - 3.0,
        first_textured_frame_ms=direct_with_boundary - 2.0,
        audit_completion_ms=direct_with_boundary + 10.0,
    )
    full_phase = _phase_timings(
        texture_resources_ready_ms=full_with_boundary - 2.0,
        first_textured_frame_ms=full_with_boundary - 1.0,
        audit_completion_ms=full_with_boundary + 10.0,
    )
    samples = [
        {
            **common,
            "mode": "cold",
            "repetition": repetition,
            "first_usable_ms": first,
            "full_texture_readiness_ms": full,
            "peak_private_bytes": 1_000.0,
            "gpu_resident_bytes": 1_000.0,
            "native_service_used": False,
            "native_cache_started_empty": True,
            "package_reload_count": 2,
            "resource_reload_count": 2,
            "timing_basis": "explicit_rust_phase_milestones_v1",
            "preview_core_wall_ms": native_wall,
            "direct_package_build_ms": direct_build,
            "full_package_build_ms": full_build,
            "direct_phase_timings": direct_phase,
            "full_phase_timings": full_phase,
            "direct_process_boundary_overhead_ms": 2.0,
            "full_process_boundary_overhead_ms": 2.0,
            "direct_first_textured_frame_with_process_boundary_overhead_ms": (
                direct_with_boundary
            ),
            "full_texture_resources_ready_with_process_boundary_overhead_ms": (
                full_with_boundary
            ),
            "direct_audit_completion_wall_ms": direct_phase["audit_completion_ms"]
            + 2.0,
            "full_audit_completion_wall_ms": full_phase["audit_completion_ms"] + 2.0,
        }
        for repetition in range(1, 8)
    ]
    samples.extend(
        {
            **common,
            "mode": "warm",
            "repetition": repetition,
            "warm_capture_ms": warm,
            "peak_private_bytes": 1_000.0,
            "gpu_resident_bytes": 1_000.0,
            "package_reload_count": 0,
            "resource_reload_count": 0,
            "resident_package_load_count": 1,
            "resident_renderer_device_count": 1,
            "resident_renderer_batch_count": 1,
            "resident_texture_upload_pass_count": 1,
            "resident_phase_timings": _phase_timings(
                texture_resources_ready_ms=8.0,
                first_textured_frame_ms=10.0,
                audit_completion_ms=200.0,
            ),
        }
        for repetition in range(1, 21)
    )
    return {
        "schema": EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA,
        "complete": True,
        "capture_binaries": {
            "preview_core": {"sha256": "a" * 64},
            "rust_helper": {"sha256": "b" * 64},
        },
        "census_manifest_sha256": "c" * 64,
        "samples": samples,
    }


def _baseline_process_factory(root, session_id, source_path, provenance_sha256):
    runtime_dds = {
        "schema": "cdmw_rust_runtime_dds_measurement_v1",
        "duplicate_binary_resource_count": 0,
        "gpu_measurement": "validated DDS mip payload bytes submitted for residency",
        "logical_binding_key_count": 1,
        "logical_resource_bytes": 1_000,
        "logical_resource_count": 1,
        "renderer_reported_upload_count": 1,
        "reported_gpu_resident_bytes": 1_000,
        "unique_binary_bytes": 1_000,
        "unique_binary_count": 1,
        "unique_gpu_resident_bytes": 1_000,
        "uploaded_resource_bytes": 1_000,
        "uploads_match_unique_binaries": True,
    }
    attestation = {
        "adapter_backend": "Dx12",
        "adapter_device_type": "DiscreteGpu",
        "complete": True,
        "fallback_used": False,
        "process_restart_count": 0,
        "renderer": "wgpu_d3d12_rust",
        "report_schema": "cdmw_rust_material_audit_capture_v2",
        "timed_out": False,
    }

    def process_envelope(
        sample_id: str,
        *,
        repetitions: int,
        phase: dict[str, object],
        walls: list[float],
        warm_valid: bool,
    ) -> dict[str, object]:
        proof = {
            "schema": "cdmw_rust_warm_material_capture_v1",
            "valid": warm_valid,
            "dds_textures_uploaded_once_for_repetition_set": True,
            "full_model_views_per_repetition": 6,
            "package_load_count": 1,
            "package_reloads_between_repetitions": 0,
            "per_repetition_wall_ms": walls,
            "renderer_batch_count": 1,
            "renderer_device_count": 1,
            "resource_reloads_between_repetitions": 0,
            "texture_upload_pass_count": 1,
        }
        captures = [
            {
                "capture_kind": "full_model",
                "dimensions": [768, 768],
                "name": view,
                "repetition_index": repetition_index,
                "wall_ms": 10.0,
            }
            for repetition_index in range(repetitions)
            for view in equipment_material_performance.FULL_MODEL_VIEWS
        ]
        report = {
            "schema": "cdmw_rust_material_audit_capture_v2",
            "renderer": "wgpu_d3d12_rust",
            "adapter": {"backend": "Dx12", "device_type": "DiscreteGpu"},
            "preview_package": True,
            "full_model_only": True,
            "source_lod_index": 0,
            "source_path": source_path,
            "session_id": session_id,
            "process_generation": 1,
            "repetition_count": repetitions,
            "capture_count": repetitions * 6,
            "fixed_full_model_view_count": 6,
            "material_region_view_count": 0,
            "output_repetition_count": 1,
            "dds_resources_uploaded_once_for_capture_set": True,
            "process_memory": {
                "available": False,
                "measurement": "external_os_observer_required",
                "reason": "measured by the external launcher",
            },
            "phase_timings": phase,
            "runtime_dds": runtime_dds,
            "warm_cache_proof": proof,
            "captures": captures,
        }
        report_path = (root / sample_id / "audit-report.json").resolve()
        _write_json(report_path, report)
        return {
            "sample_id": sample_id,
            "baseline_provenance_sha256": provenance_sha256,
            "execution_attestation": dict(attestation),
            "repetition_count": repetitions,
            "resident_batch_id": session_id,
            "resident_process_generation": 1,
            "process_exit_code": 0,
            "external_wall_ms": float(phase["audit_completion_ms"]) + 10.0,
            "observed_peak_working_set_bytes": 900.0,
            "observed_peak_paged_memory_bytes": 1_000.0,
            "observed_peak_virtual_memory_bytes": 2_000.0,
            "memory_sampling_interval_ms": 5.0,
            "phase_timings": phase,
            "runtime_dds": dict(runtime_dds),
            "warm_cache_proof": proof,
            "report_path": str(report_path),
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "stderr": "",
            "stdout": "",
        }
    return process_envelope


def _baseline_build_provenance():
    provenance = {
        "schema": "cdmw_equipment_material_performance_baseline_provenance_v1",
        "base_revision": "a48f00ce47afa85439eaf17e6ab8bb90fb6bf5ff",
        "base_short_revision": "a48f00ce",
        "base_tree_clean": True,
        "instrumentation": {
            "purpose": (
                "measure_pre_goal_a48f00ce_performance_without_material_semantic_changes"
            ),
            "schema": (
                "cdmw_equipment_material_performance_baseline_instrumentation_v1"
            ),
            "patch_sha256": (
                "3669f86b7690233603213b6711b3e936"
                "ec9a743ec6f4d0813c1e42c860942a36"
            ),
            "modified_paths": [
                "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs",
                "tools/rust_mesh_lab/crates/cdmw_render_wgpu/src/lib.rs",
            ],
        },
        "capture_binaries": {
            "uninstrumented_rust": {
                "path": (
                    "C:\\Users\\Ratrider\\Documents\\CDMW Evidence\\"
                    "production-material-fidelity-20260902\\baseline-binaries\\"
                    "a48f00ce-uninstrumented\\cdmw_mesh_lab.exe"
                ),
                "bytes": 13_359_104,
                "sha256": (
                    "8e7f83e8caa045f876efa63143367ee94"
                    "c7f7bd9daf657ce36766f41cd88284e"
                ),
                "kind": "uninstrumented",
            },
            "uninstrumented_preview_core": {
                "path": (
                    "C:\\Users\\Ratrider\\Documents\\CDMW Evidence\\"
                    "production-material-fidelity-20260902\\baseline-binaries\\"
                    "a48f00ce-uninstrumented\\cdmw-preview-core.exe"
                ),
                "bytes": 1_499_136,
                "sha256": (
                    "32541c64f1d99808046159abf80e0edeb"
                    "542b6ba5157d48814c349c96379a09e"
                ),
                "kind": "uninstrumented",
            },
            "instrumented_rust": {
                "path": (
                    "C:\\Users\\Ratrider\\Documents\\CDMW Evidence\\"
                    "production-material-fidelity-20260902\\baseline-binaries\\"
                    "a48f00ce-instrumented\\cdmw_mesh_lab.exe"
                ),
                "bytes": 13_447_680,
                "sha256": (
                    "a2a63c87896612e5989d9403ae108c9d0"
                    "76470e41b0bb345a8a61050011edbd3"
                ),
                "kind": "instrumented",
            },
        },
        "source_tree_sha256": (
            "9be0ad2e46ab9eb590769eb666455a0c"
            "74956722df2e43e6009846b2a423dbdd"
        ),
    }
    return provenance


def _baseline_repetition_payload(
    target: dict[str, object],
    *,
    first: float,
    full: float,
    warm: float,
    root: Path,
) -> dict[str, object]:
    provenance = _baseline_build_provenance()
    provenance_sha256 = _canonical_sha256(provenance)
    source_path = f"character/model/{target['identity']}"
    session_id = f"baseline-{target['asset_id']}"
    target_identity = {
        "dimensions": [768, 768],
        "fixed_full_model_views": list(
            equipment_material_performance.FULL_MODEL_VIEWS
        ),
        "input_manifest_sha256": "d" * 64,
        "process_generation": 1,
        "renderer": "wgpu_d3d12_rust",
        "session_id": session_id,
        "source_path": source_path,
    }
    process_envelope = _baseline_process_factory(root, session_id, source_path, provenance_sha256)

    cold_phase = _phase_timings(
        texture_resources_ready_ms=full,
        first_textured_frame_ms=first,
        audit_completion_ms=max(first, full) + 20.0,
    )
    cold_samples = [
        process_envelope(
            f"cold-{repetition:02d}",
            repetitions=1,
            phase=dict(cold_phase),
            walls=[25.0],
            warm_valid=False,
        )
        for repetition in range(1, 8)
    ]
    warm_walls = [warm for _ in range(20)]
    warm_phase = _phase_timings(
        texture_resources_ready_ms=80.0,
        first_textured_frame_ms=90.0,
        audit_completion_ms=200.0,
    )
    warm_batch = process_envelope(
        "warm-resident-20",
        repetitions=20,
        phase=warm_phase,
        walls=warm_walls,
        warm_valid=True,
    )
    warm_samples = [
        {
            "sample_id": f"warm-{repetition:02d}",
            "baseline_provenance_sha256": provenance_sha256,
            "repetition_index": repetition - 1,
            "wall_ms": warm,
            "resident_batch_id": session_id,
            "resident_process_generation": 1,
            "package_load_count": 1,
            "package_reloads_between_repetitions": 0,
            "renderer_batch_count": 1,
            "renderer_device_count": 1,
            "texture_upload_pass_count": 1,
            "resource_reloads_between_repetitions": 0,
        }
        for repetition in range(1, 21)
    ]
    return {
        "schema": A48F00CE_BASELINE_SAMPLES_SCHEMA,
        "baseline_provenance": provenance,
        "baseline_provenance_sha256": provenance_sha256,
        "cold_definition": (
            "fresh helper process; one fixed six-view audit; OS filesystem and "
            "driver caches are not forcibly purged"
        ),
        "measurement_definitions": {
            "observed_peak_paged_memory_bytes": {
                "source": "Windows Process.PagedMemorySize64",
                "semantic": "peak_private_commit_bytes",
                "sampling": (
                    "external launcher polling; interval is recorded by "
                    "memory_sampling_interval_ms on each process envelope"
                ),
            }
        },
        "metric_formulas": {
            "cold_first_usable_ms": (
                "cold_samples[*].phase_timings.first_textured_frame_ms"
            ),
            "cold_full_texture_readiness_ms": (
                "cold_samples[*].phase_timings.texture_resources_ready_ms"
            ),
            "warm_capture_ms": "warm_samples[*].wall_ms",
            "peak_private_bytes": (
                "process_envelope.observed_peak_paged_memory_bytes"
            ),
            "gpu_resident_bytes": (
                "process_envelope.runtime_dds.reported_gpu_resident_bytes"
            ),
        },
        "report_integrity": {
            "authoritative": True,
            "hash_algorithm": "SHA-256",
            "required_process_envelopes": ["cold_samples[*]", "warm_batch"],
            "report_path_field": "report_path",
            "report_sha256_field": "report_sha256",
        },
        "cold_samples": cold_samples,
        "input_manifest_sha256": "d" * 64,
        "instrumented_rust_sha256": (
            "a2a63c87896612e5989d9403ae108c9d0"
            "76470e41b0bb345a8a61050011edbd3"
        ),
        "output_policy": (
            "repetition 0 publishes eighteen 768x768 BGRA BMP files; later warm "
            "repetitions render and read back the same three modes without "
            "republishing files"
        ),
        "target_identity": target_identity,
        "warm_batch": warm_batch,
        "warm_definition": (
            "twenty fixed six-view repetitions in one helper process after one "
            "package load, device creation, mesh/pipeline setup, and DDS upload pass"
        ),
        "warm_samples": warm_samples,
    }


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_clone(value: object) -> dict[str, object]:
    cloned = json.loads(json.dumps(value))
    assert isinstance(cloned, dict)
    return cloned


def _rebind_baseline_provenance(payload: dict[str, object]) -> None:
    provenance_sha256 = _canonical_sha256(payload["baseline_provenance"])
    payload["baseline_provenance_sha256"] = provenance_sha256
    for sample in payload["cold_samples"]:
        sample["baseline_provenance_sha256"] = provenance_sha256
    payload["warm_batch"]["baseline_provenance_sha256"] = provenance_sha256
    for sample in payload["warm_samples"]:
        sample["baseline_provenance_sha256"] = provenance_sha256


def _accept_audited_baseline_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        equipment_material_performance,
        "_baseline_binary_file_matches",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        equipment_material_performance,
        "_a48f00ce_target_manifest_failure",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        equipment_material_performance,
        "_a48f00ce_provenance_file_failure",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        equipment_material_performance,
        "_a48f00ce_packet_file_failure",
        lambda *_args, **_kwargs: "",
    )


def _baseline_failure_gates(result: dict[str, object]) -> set[str]:
    comparison = result["baseline_comparison"]
    return {str(row["gate"]) for row in comparison["failures"]}


def _census_identity() -> dict[str, object]:
    live_archive = {"package_root": "C:/test/game"}
    harness_files = [
        {"path": "capture.py", "bytes": 123, "sha256": "3" * 64}
    ]
    harness_payload = {
        "schema": "cdmw_equipment_material_capture_harness_v1",
        "files": harness_files,
    }
    harness_sha256 = hashlib.sha256(
        json.dumps(
            harness_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    archive_sha256 = hashlib.sha256(
        json.dumps(
            live_archive,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "cdmw_equipment_material_capture_identity_v1",
        "census_run_id": "focused-performance-test",
        "catalogue": {
            "schema": "cdmw_equipment_audit_catalogue_v1",
            "file_sha256": "d" * 64,
            "selection_sha256": "e" * 64,
        },
        "resolution": {
            "schema": "cdmw_equipment_live_resolution_v1",
            "file_sha256": "f" * 64,
            "resolution_sha256": "1" * 64,
        },
        "archive": {
            "live_archive": live_archive,
            "sha256": archive_sha256,
        },
        "capture_binaries": {
            "preview_core": {"sha256": "a" * 64},
            "rust_helper": {"sha256": "b" * 64},
        },
        "capture_harness": {
            **harness_payload,
            "sha256": harness_sha256,
        },
    }


def _phase_timings(
    *,
    texture_resources_ready_ms: float,
    first_textured_frame_ms: float,
    audit_completion_ms: float,
) -> dict[str, object]:
    return {
        "schema": "cdmw_rust_material_capture_phase_timings_v1",
        "package_load_complete_ms": 1.0,
        "renderer_device_ready_ms": 2.0,
        "texture_resources_ready_ms": texture_resources_ready_ms,
        "first_textured_frame_ms": first_textured_frame_ms,
        "audit_completion_ms": audit_completion_ms,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
