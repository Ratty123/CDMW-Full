"""Deterministic performance evidence for the exhaustive equipment material audit.

Aggregation is read-only: it summarizes published capture reports, matches preserved
pre-instrumentation reports, chooses deterministic stress assets, and validates
cold/warm evidence. The opt-in runner writes only to a separate evidence root.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import psutil

from cdmw.core.atomic_file import atomic_copy_file, atomic_write_text

EQUIPMENT_PERFORMANCE_SUMMARY_SCHEMA = "cdmw_equipment_material_performance_summary_v1"
EQUIPMENT_PERFORMANCE_REPETITION_PLAN_SCHEMA = (
    "cdmw_equipment_material_performance_repetition_plan_v1"
)
EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA = (
    "cdmw_equipment_material_performance_repetition_results_v1"
)
EQUIPMENT_CAPTURE_MANIFEST_SCHEMA = "cdmw_equipment_material_capture_manifest_v1"
EQUIPMENT_CAPTURE_SCHEMA = "cdmw_equipment_material_capture_v1"
EQUIPMENT_CAPTURE_IDENTITY_SCHEMA = "cdmw_equipment_material_capture_identity_v1"
EQUIPMENT_PERFORMANCE_SCHEMA = "cdmw_equipment_material_performance_v1"
RUST_MATERIAL_PHASE_TIMINGS_SCHEMA = (
    "cdmw_rust_material_capture_phase_timings_v1"
)
EQUIPMENT_PERFORMANCE_BASELINE_PROVENANCE_SCHEMA = (
    "cdmw_equipment_material_performance_baseline_provenance_v1"
)
EQUIPMENT_PERFORMANCE_BASELINE_INSTRUMENTATION_SCHEMA = (
    "cdmw_equipment_material_performance_baseline_instrumentation_v1"
)
A48F00CE_BASELINE_SAMPLES_SCHEMA = (
    "cdmw_a48f00ce_instrumented_baseline_samples_v1"
)
_BASELINE_PACKET_BUNDLE_SCHEMA = "cdmw_a48f00ce_baseline_packet_bundle_v1"

EXPECTED_LOGICAL_PAC_COUNT = 2_057
EXPECTED_SOURCE_ONLY_COUNT = 3
COLD_REPETITIONS = 7
WARM_REPETITIONS = 20
RHETT_LOGICAL_PAC = "cd_phm_02_sword_0009.pac"
PRODUCTION_RENDERER_PATH = "native_preview_core_to_direct_and_full_rust_to_wgpu_d3d12"
CURRENT_PREVIEW_CORE_SCHEMA_VERSION = 8
CURRENT_MATERIAL_GRAPH_VERSION = 4
CURRENT_MATERIAL_SEMANTICS_VERSION = 10
FULL_MODEL_VIEWS = (
    "front",
    "three-quarter-front",
    "side",
    "back",
    "slightly-above",
    "slightly-below",
)
_RUST_PHASE_FIELDS = (
    "package_load_complete_ms",
    "renderer_device_ready_ms",
    "texture_resources_ready_ms",
    "first_textured_frame_ms",
    "audit_completion_ms",
)

_MAX_JSON_BYTES = 32 * 1024 * 1024
_TIMING_THRESHOLDS_MS = {
    "first_usable_ms": 50.0,
    "full_texture_readiness_ms": 250.0,
    "warm_capture_ms": 5.0,
    "asset_wall_ms": 5.0,
    "direct_renderer_wall_ms": 5.0,
    "full_renderer_wall_ms": 5.0,
}
_MEMORY_METRICS = frozenset(
    {
        "peak_private_bytes",
        "gpu_resident_bytes",
        "direct_peak_private_bytes",
        "full_peak_private_bytes",
        "preview_core_process_private_bytes",
        "direct_peak_working_set_bytes",
        "full_peak_working_set_bytes",
        "preview_core_process_working_set_bytes",
        "direct_gpu_resident_bytes",
        "full_gpu_resident_bytes",
    }
)
_CONTROLLED_POST_JOB_RECYCLE_REASONS = frozenset(
    {"", "job_count", "decoded_cache_bytes", "process_private_bytes"}
)
_INFORMATIONAL_COMPARISON_METRICS = frozenset(
    {
        "preview_core_process_working_set_bytes",
        "direct_peak_working_set_bytes",
        "full_peak_working_set_bytes",
    }
)
_A48F00CE_BASE_REVISION = "a48f00ce47afa85439eaf17e6ab8bb90fb6bf5ff"
_A48F00CE_BASE_SHORT_REVISION = "a48f00ce"
_A48F00CE_INSTRUMENTATION_PURPOSE = (
    "measure_pre_goal_a48f00ce_performance_without_material_semantic_changes"
)
_A48F00CE_INSTRUMENTATION_MODIFIED_PATHS = (
    "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs",
    "tools/rust_mesh_lab/crates/cdmw_render_wgpu/src/lib.rs",
)
_A48F00CE_UNINSTRUMENTED_RUST_SHA256 = (
    "8e7f83e8caa045f876efa63143367ee94c7f7bd9daf657ce36766f41cd88284e"
)
_A48F00CE_UNINSTRUMENTED_RUST_BYTES = 13_359_104
_A48F00CE_UNINSTRUMENTED_PREVIEW_CORE_SHA256 = (
    "32541c64f1d99808046159abf80e0edeb542b6ba5157d48814c349c96379a09e"
)
_A48F00CE_UNINSTRUMENTED_PREVIEW_CORE_BYTES = 1_499_136
_A48F00CE_INSTRUMENTED_RUST_SHA256 = (
    "a2a63c87896612e5989d9403ae108c9d076470e41b0bb345a8a61050011edbd3"
)
_A48F00CE_INSTRUMENTED_RUST_BYTES = 13_447_680
_A48F00CE_SOURCE_TREE_SHA256 = (
    "9be0ad2e46ab9eb590769eb666455a0c74956722df2e43e6009846b2a423dbdd"
)
_A48F00CE_INSTRUMENTATION_PATCH_SHA256 = (
    "3669f86b7690233603213b6711b3e936ec9a743ec6f4d0813c1e42c860942a36"
)
_A48F00CE_BASELINE_PROVENANCE_SHA256 = (
    "97303066250c258049f838983069f697d18e079e9f40916cd518e06d8ed8cc00"
)
_A48F00CE_ARTIFACT_HASH_MANIFEST_SHA256 = (
    "0d6f842d2cc9f781fdb639c447cd5e7edc284876ef91b73944d407a63b0989a1"
)
_A48F00CE_COLD_DEFINITION = (
    "fresh helper process; one fixed six-view audit; OS filesystem and driver "
    "caches are not forcibly purged"
)
_A48F00CE_WARM_DEFINITION = (
    "twenty fixed six-view repetitions in one helper process after one package "
    "load, device creation, mesh/pipeline setup, and DDS upload pass"
)
_A48F00CE_OUTPUT_POLICY = (
    "repetition 0 publishes eighteen 768x768 BGRA BMP files; later warm "
    "repetitions render and read back the same three modes without republishing files"
)
_A48F00CE_MEMORY_DEFINITIONS = {
    "observed_peak_paged_memory_bytes": {
        "source": "Windows Process.PagedMemorySize64",
        "semantic": "peak_private_commit_bytes",
        "sampling": (
            "external launcher polling; interval is recorded by "
            "memory_sampling_interval_ms on each process envelope"
        ),
    }
}
_A48F00CE_METRIC_FORMULAS = {
    "cold_first_usable_ms": (
        "cold_samples[*].phase_timings.first_textured_frame_ms"
    ),
    "cold_full_texture_readiness_ms": (
        "cold_samples[*].phase_timings.texture_resources_ready_ms"
    ),
    "warm_capture_ms": "warm_samples[*].wall_ms",
    "peak_private_bytes": "process_envelope.observed_peak_paged_memory_bytes",
    "gpu_resident_bytes": (
        "process_envelope.runtime_dds.reported_gpu_resident_bytes"
    ),
}
_A48F00CE_REPORT_INTEGRITY = {
    "authoritative": True,
    "hash_algorithm": "SHA-256",
    "required_process_envelopes": ["cold_samples[*]", "warm_batch"],
    "report_path_field": "report_path",
    "report_sha256_field": "report_sha256",
}


class EquipmentPerformanceError(ValueError):
    """Raised when performance evidence is unsafe, malformed, or ambiguous."""


def build_equipment_performance_summary(
    evidence_root: Path | str,
    *,
    baseline_root: Path | str | None = None,
    repetition_results_path: Path | str | None = None,
    baseline_repetition_results_path: Path | str | None = None,
    expected_logical_count: int = EXPECTED_LOGICAL_PAC_COUNT,
) -> dict[str, object]:
    """Build a read-only census summary and objective-level acceptance state."""

    root = Path(evidence_root).expanduser().resolve(strict=True)
    manifest_path = root / "capture-manifest.json"
    manifest = _read_json_object(manifest_path, label="capture manifest")
    if manifest.get("schema") != EQUIPMENT_CAPTURE_MANIFEST_SCHEMA:
        raise EquipmentPerformanceError("Capture manifest schema is incompatible.")

    expected = int(expected_logical_count)
    if expected <= 0:
        raise EquipmentPerformanceError("Expected logical PAC count must be positive.")
    manifest_assets = _mapping_rows(manifest, "assets")
    census_identity = _mapping(manifest.get("census_identity"))
    asset_rows: list[dict[str, object]] = []
    missing_assets: list[dict[str, object]] = []
    source_only_assets: list[dict[str, object]] = []
    integrity_failures: list[dict[str, object]] = []
    ordinals = [_safe_int(row.get("ordinal"), -1) for row in manifest_assets]
    asset_ids = [str(row.get("asset_id", "") or "") for row in manifest_assets]
    identities = [
        str(row.get("identity", "") or "").casefold() for row in manifest_assets
    ]
    for gate, ok, detail in (
        (
            "manifest_ordinal_identity",
            len(manifest_assets) != expected
            or sorted(ordinals) == list(range(expected)),
            "complete-size manifest ordinals are not exactly 0..expected-1",
        ),
        (
            "manifest_asset_id_identity",
            all(asset_ids) and len(set(asset_ids)) == len(asset_ids),
            "manifest asset IDs are empty or duplicated",
        ),
        (
            "manifest_logical_identity",
            all(identities) and len(set(identities)) == len(identities),
            "manifest logical PAC identities are empty or duplicated",
        ),
        (
            "census_identity",
            manifest.get("capture_complete") is not True
            or census_identity.get("schema") == EQUIPMENT_CAPTURE_IDENTITY_SCHEMA,
            "complete manifest has no compatible census identity",
        ),
    ):
        if not ok:
            integrity_failures.append({"gate": gate, "detail": detail})
    if manifest.get("capture_complete") is True:
        integrity_failures.extend(
            _census_identity_failures(
                census_identity,
                manifest_capture_binaries=_mapping(manifest.get("capture_binaries")),
            )
        )
    for manifest_row in sorted(
        manifest_assets,
        key=lambda row: (
            _safe_int(row.get("ordinal"), 2**31 - 1),
            str(row.get("identity", "")).casefold(),
        ),
    ):
        asset_id = str(manifest_row.get("asset_id", "") or "")
        identity = str(manifest_row.get("identity", "") or "")
        report_path = root / "assets" / asset_id / "asset-report.json"
        if not report_path.is_file():
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "asset_report_missing",
                }
            )
            continue
        try:
            report = _read_json_object(report_path, label=f"asset report {asset_id}")
        except (OSError, EquipmentPerformanceError) as exc:
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": f"asset_report_unreadable:{exc}",
                }
            )
            continue
        if report.get("schema") != EQUIPMENT_CAPTURE_SCHEMA:
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "asset_report_schema_mismatch",
                }
            )
            continue
        if (
            str(report.get("asset_id", "") or "") != asset_id
            or _safe_int(report.get("catalogue_ordinal"), -1)
            != _safe_int(manifest_row.get("ordinal"), -2)
        ):
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "asset_report_manifest_row_mismatch",
                }
            )
            continue
        if manifest.get("capture_complete") is True and _canonical_json_sha256(
            _mapping(report.get("census_identity"))
        ) != _canonical_json_sha256(census_identity):
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "asset_report_census_identity_mismatch",
                }
            )
            continue
        if manifest.get("capture_complete") is True:
            expected_report_sha = str(
                manifest_row.get("report_sha256", "") or ""
            ).casefold()
            if (
                len(expected_report_sha) != 64
                or _sha256_file(report_path) != expected_report_sha
            ):
                missing_assets.append(
                    {
                        "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                        "asset_id": asset_id,
                        "identity": identity,
                        "reason": "asset_report_manifest_sha256_mismatch",
                    }
                )
                continue
        if str(report.get("identity", "")).casefold() != identity.casefold():
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "asset_report_identity_mismatch",
                }
            )
            continue
        if report.get("status") in {"source_only_captured", "source_only_reviewed"}:
            source_only_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "no_archive_geometry",
                }
            )
            continue
        performance = _mapping(report.get("performance"))
        if performance.get("schema") != EQUIPMENT_PERFORMANCE_SCHEMA:
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": "instrumented_performance_missing",
                }
            )
            continue
        try:
            row, failures = _instrumented_asset_row(
                root / "assets" / asset_id,
                manifest_row,
                report,
            )
        except (OSError, EquipmentPerformanceError) as exc:
            missing_assets.append(
                {
                    "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
                    "asset_id": asset_id,
                    "identity": identity,
                    "reason": f"instrumented_evidence_invalid:{exc}",
                }
            )
            continue
        asset_rows.append(row)
        integrity_failures.extend(failures)
        if not _capture_binaries_match(
            _mapping(report.get("capture_binaries")),
            _mapping(manifest.get("capture_binaries")),
        ):
            integrity_failures.append(
                {
                    "asset_id": asset_id,
                    "identity": identity,
                    "gate": "capture_binary_identity",
                    "detail": "asset and census binary hashes differ",
                }
            )

    expected_renderable = max(0, expected - len(source_only_assets))
    canonical_rhett_present = any(
        str(row.get("identity", "")).casefold() == RHETT_LOGICAL_PAC
        for row in asset_rows
    )
    census_complete = bool(
        len(manifest_assets) == expected
        and len(source_only_assets) == EXPECTED_SOURCE_ONLY_COUNT
        and len(asset_rows) == expected_renderable
        and not missing_assets
        and _safe_int(manifest.get("failed_count"), -1) == 0
        and _safe_int(manifest.get("missing_count"), -1) == 0
        and manifest.get("capture_complete") is True
        and not integrity_failures
        and canonical_rhett_present
    )
    distributions = _metric_distributions(asset_rows)
    worst_cases = _select_worst_cases(asset_rows)
    targets = _repetition_targets(asset_rows, worst_cases)
    plan = build_equipment_repetition_plan(
        root,
        targets=targets,
        census_complete=census_complete,
        expected_logical_count=expected,
        observed_instrumented_count=len(asset_rows),
        capture_binaries=_mapping(manifest.get("capture_binaries")),
    )

    if baseline_root is None:
        baseline = _missing_comparison("baseline_root_not_supplied")
    else:
        baseline = _compare_census_baseline(
            asset_rows,
            Path(baseline_root).expanduser().resolve(strict=True),
        )

    if repetition_results_path is None:
        repetitions = _missing_comparison("repetition_results_not_supplied")
    else:
        current_repetitions = _read_json_object(
            Path(repetition_results_path).expanduser().resolve(strict=True),
            label="repetition results",
        )
        baseline_repetitions = (
            _read_baseline_repetition_evidence(
                Path(baseline_repetition_results_path).expanduser()
            )
            if baseline_repetition_results_path is not None
            else None
        )
        repetitions = evaluate_equipment_repetition_results(
            current_repetitions,
            baseline=baseline_repetitions,
            expected_targets=targets,
            expected_capture_binaries=_mapping(manifest.get("capture_binaries")),
            expected_census_manifest_sha256=_sha256_file(manifest_path),
        )

    assessed_failures = repetitions.get("status") == "fail"
    missing_required_comparison = repetitions.get("status") != "pass"
    if integrity_failures or assessed_failures:
        acceptance_status = "fail"
    elif not census_complete or missing_required_comparison:
        acceptance_status = "incomplete"
    else:
        acceptance_status = "pass"

    return {
        "schema": EQUIPMENT_PERFORMANCE_SUMMARY_SCHEMA,
        "ok": acceptance_status == "pass",
        "acceptance_status": acceptance_status,
        "evidence_root": str(root),
        "capture_manifest": {
            "path": str(manifest_path),
            "sha256": _sha256_file(manifest_path),
            "capture_binaries": dict(_mapping(manifest.get("capture_binaries"))),
            "census_identity": dict(census_identity),
        },
        "census": {
            "expected_logical_count": expected,
            "manifest_asset_count": len(manifest_assets),
            "instrumented_renderable_count": len(asset_rows),
            "source_only_count": len(source_only_assets),
            "missing_or_uninstrumented_count": len(missing_assets),
            "complete": census_complete,
            "canonical_rhett_present": canonical_rhett_present,
            "source_only_assets": source_only_assets,
            "missing_or_uninstrumented_assets": missing_assets,
        },
        "metric_definitions": _metric_definitions(),
        "distributions": distributions,
        "integrity": {
            "ok": not integrity_failures,
            "failure_count": len(integrity_failures),
            "failures": integrity_failures,
        },
        "lifecycle": _lifecycle_summary(asset_rows, integrity_failures),
        "asset_metrics": asset_rows,
        "worst_cases": worst_cases,
        "repetition_plan": plan,
        "baseline_comparison": baseline,
        "repetition_acceptance": repetitions,
    }


def build_equipment_repetition_plan(
    evidence_root: Path | str,
    *,
    targets: Sequence[Mapping[str, object]],
    census_complete: bool,
    expected_logical_count: int,
    observed_instrumented_count: int,
    capture_binaries: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Describe the exact post-census cold/warm production runner contract."""

    root = Path(evidence_root).expanduser().resolve()
    target_rows = [dict(target) for target in targets]
    canonical_rhett_targeted = any(
        str(target.get("identity", "")).casefold() == RHETT_LOGICAL_PAC
        for target in target_rows
    )
    ready = bool(census_complete and target_rows and canonical_rhett_targeted)
    rerun_command = [
        sys.executable,
        "-m",
        "tools.mesh_harness.equipment_material_performance_cli",
        "--evidence-root",
        str(root),
        "--require-complete",
    ]
    catalogue_path = root / "catalogue.json"
    resolution_path = root / "resolution.json"
    helper_path = Path(
        str(_mapping(_mapping(capture_binaries).get("rust_helper")).get("path", ""))
    )
    repetition_cache = root.parent / f"{root.name}-performance-cache"
    baseline_path = root / "performance-baseline-pre-instrumentation"
    execution_inputs_available = bool(
        catalogue_path.is_file()
        and resolution_path.is_file()
        and helper_path.is_file()
    )
    repetition_output = root.parent / f"{root.name}-performance-repetitions"
    execution_command = (
        [
            sys.executable,
            "-m",
            "tools.mesh_harness.equipment_material_performance_cli",
            "--evidence-root",
            str(root),
            *(
                ["--baseline-root", str(baseline_path)]
                if baseline_path.is_dir()
                else []
            ),
            "--execute-repetitions",
            "--catalogue",
            str(catalogue_path),
            "--resolution",
            str(resolution_path),
            "--cache-root",
            str(repetition_cache),
            "--rust-helper",
            str(helper_path),
            "--repetition-output-root",
            str(repetition_output),
            "--output",
            str(repetition_output / "equipment-performance-summary.json"),
            "--require-complete",
        ]
        if execution_inputs_available
        else []
    )
    return {
        "schema": EQUIPMENT_PERFORMANCE_REPETITION_PLAN_SCHEMA,
        "status": "ready_for_production_runner"
        if ready
        else "waiting_for_complete_census",
        "reason": ""
        if ready
        else (
            "The exact final census is not complete and worst-case selection is provisional."
            if not census_complete
            else "The canonical Rhett target is unavailable from the finalized census."
        ),
        "expected_logical_count": int(expected_logical_count),
        "observed_instrumented_count": int(observed_instrumented_count),
        "cold_repetitions_per_target": COLD_REPETITIONS,
        "warm_repetitions_per_target": WARM_REPETITIONS,
        "targets": target_rows if ready else [],
        "provisional_targets": [] if ready else target_rows,
        "post_census_aggregation_command": rerun_command,
        "repetition_execution_command_status": (
            "ready"
            if execution_inputs_available and ready
            else "deferred_until_census_complete"
            if execution_inputs_available
            else "missing_required_local_inputs"
        ),
        "repetition_execution_command": execution_command,
        "preserved_baseline_status": (
            "available" if baseline_path.is_dir() else "not_found_explicit_missing"
        ),
        "runner_contract": {
            "production_path": PRODUCTION_RENDERER_PATH,
            "renderer": "wgpu_d3d12_rust",
            "adapter_backend": "dx12",
            "python_material_synthesis_used": False,
            "cold": (
                "Seven isolated empty-cache runs per target. Each disables the resident "
                "Preview Core service, starts a fresh Preview Core process, and starts "
                "fresh direct/full Rust D3D12 processes."
            ),
            "warm": (
                "Twenty captures per target in one resident renderer session after "
                "one package/resource load; every warm sample must report zero package "
                "and resource reloads and one unchanged process generation."
            ),
            "required_results_schema": EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA,
            "required_sample_metrics": [
                "first_usable_ms",
                "full_texture_readiness_ms",
                "warm_capture_ms",
                "peak_private_bytes",
                "gpu_resident_bytes",
            ],
            "phase_timing_schema": RUST_MATERIAL_PHASE_TIMINGS_SCHEMA,
            "phase_timing_semantics": (
                "Cumulative elapsed milestones from Rust helper entry. Six-view wall is "
                "audit completion only and is not first usable or full texture readiness."
            ),
            "production_stage_order": [
                "preview_core_complete",
                "direct_package_build_complete_and_published",
                "full_package_build_complete_and_published_without_waiting_for_direct_frame",
                "full_texture_resources_ready",
            ],
            "forbidden_events": [
                "timeout",
                "process_restart",
                "renderer_fallback",
                "warm_package_reload",
                "warm_resource_reload",
                "duplicate_upload_key",
                "duplicate_parameter_texture_bytes",
            ],
            "current_helper_note": (
                "The one-shot audit mode starts a new renderer process and does not "
                "prove resident warm reuse. Use --capture-audit-repetitions in one "
                "batch; do not relabel repeated one-shot runs as warm evidence."
            ),
        },
    }


def evaluate_equipment_repetition_results(
    current: Mapping[str, object],
    *,
    baseline: Mapping[str, object] | None,
    expected_targets: Sequence[Mapping[str, object]],
    expected_capture_binaries: Mapping[str, object] | None = None,
    expected_census_manifest_sha256: str = "",
) -> dict[str, object]:
    """Validate exact 7/20 coverage, production invariants, and performance deltas."""

    if current.get("schema") != EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA:
        raise EquipmentPerformanceError("Repetition result schema is incompatible.")
    target_ids = [str(row.get("asset_id", "")) for row in expected_targets]
    target_identities = [str(row.get("identity", "")) for row in expected_targets]
    if (
        not target_ids
        or any(not target for target in target_ids)
        or any(not identity for identity in target_identities)
        or len(set(target_ids)) != len(target_ids)
    ):
        return _missing_comparison("repetition_targets_unavailable")
    expected_identities = {
        str(row.get("asset_id", "")): str(row.get("identity", ""))
        for row in expected_targets
    }
    samples = _mapping_rows(current, "samples")
    failures: list[dict[str, object]] = []
    if current.get("complete") is not True:
        failures.append(
            {
                "gate": "result_complete",
                "detail": "repetition evidence is not marked complete",
            }
        )
    if expected_capture_binaries is not None and not _capture_binaries_match(
        _mapping(current.get("capture_binaries")), expected_capture_binaries
    ):
        failures.append(
            {
                "gate": "capture_binary_identity",
                "detail": "repetition helper hashes differ from the finalized census",
            }
        )
    expected_manifest_sha = str(expected_census_manifest_sha256 or "").casefold()
    if expected_manifest_sha and str(
        current.get("census_manifest_sha256", "") or ""
    ).casefold() != expected_manifest_sha:
        failures.append(
            {
                "gate": "census_manifest_identity",
                "detail": "repetition evidence targets another census manifest",
            }
        )
    coverage: list[dict[str, object]] = []
    for target_id in target_ids:
        target_samples = [row for row in samples if row.get("asset_id") == target_id]
        mismatched_identities = sorted(
            {
                str(row.get("identity", "") or "")
                for row in target_samples
                if str(row.get("identity", "") or "")
                != expected_identities[target_id]
            }
        )
        if mismatched_identities:
            failures.append(
                {
                    "asset_id": target_id,
                    "gate": "target_identity",
                    "detail": "samples do not match the frozen target identity",
                }
            )
        mode_counts: dict[str, int] = {}
        for mode, expected_count in (
            ("cold", COLD_REPETITIONS),
            ("warm", WARM_REPETITIONS),
        ):
            rows = [row for row in target_samples if row.get("mode") == mode]
            mode_counts[mode] = len(rows)
            ordinals = sorted(_safe_int(row.get("repetition"), -1) for row in rows)
            if len(rows) != expected_count or ordinals != list(
                range(1, expected_count + 1)
            ):
                failures.append(
                    {
                        "asset_id": target_id,
                        "gate": f"{mode}_coverage",
                        "detail": f"expected {expected_count} exact repetitions, found {len(rows)}",
                    }
                )
            for row in rows:
                failures.extend(_sample_failures(row, target_id=target_id, mode=mode))
        coverage.append({"asset_id": target_id, **mode_counts})
        unexpected_modes = sorted(
            {
                str(row.get("mode", "") or "")
                for row in target_samples
                if row.get("mode") not in {"cold", "warm"}
            }
        )
        if unexpected_modes:
            failures.append(
                {
                    "asset_id": target_id,
                    "gate": "unexpected_modes",
                    "detail": ", ".join(unexpected_modes),
                }
            )
    unexpected = sorted(
        {
            str(row.get("asset_id", ""))
            for row in samples
            if str(row.get("asset_id", "")) not in target_ids
        }
    )
    if unexpected:
        failures.append(
            {
                "gate": "unexpected_targets",
                "detail": ", ".join(unexpected),
            }
        )

    if baseline is None:
        comparison = _missing_comparison("baseline_repetition_results_not_supplied")
    else:
        baseline_samples, baseline_failures = _validated_baseline_repetition_samples(
            baseline,
            expected_targets=expected_targets,
        )
        if baseline_failures:
            comparison = {
                "status": "incomplete",
                "ok": False,
                "reason": "baseline_repetition_contract_invalid",
                "failure_count": len(baseline_failures),
                "failures": baseline_failures,
            }
        else:
            comparison = _compare_repetition_samples(
                samples, baseline_samples, target_ids
            )

    if failures or comparison.get("status") == "fail":
        status = "fail"
    elif comparison.get("status") != "pass":
        status = "incomplete"
    else:
        status = "pass"
    return {
        "status": status,
        "ok": status == "pass",
        "coverage": coverage,
        "failure_count": len(failures),
        "failures": failures,
        "baseline_comparison": comparison,
    }


def run_equipment_performance_repetitions(
    *,
    catalogue_path: Path | str,
    resolution_path: Path | str,
    evidence_root: Path | str,
    output_root: Path | str,
    cache_root: Path | str,
    rust_helper: Path | str,
    capture_timeout_seconds: float = 180.0,
) -> dict[str, object]:
    """Run exact cold and resident-warm samples for the finalized target set.

    The existing census is only read.  Compact JSON reports are retained under
    ``output_root`` while transient images and production packages are removed.
    """

    from cdmw.rendering.native_preview_core import run_native_preview_core_preview_job
    from cdmw.services.mesh_rust_preview_package import (
        build_rust_preview_package_from_preview_core,
    )
    from tools.mesh_harness.equipment_archive_worker import archive_entry_from_worker
    from tools.mesh_harness.equipment_material_capture import (
        _validate_native_manifest,
        _validate_rust_package_manifest,
        build_equipment_capture_plans,
        load_equipment_capture_inputs,
        resolve_capture_binary_evidence,
    )

    evidence = Path(evidence_root).expanduser().resolve(strict=True)
    output = Path(output_root).expanduser().resolve()
    cache = Path(cache_root).expanduser().resolve()
    helper = Path(rust_helper).expanduser().resolve(strict=True)
    catalogue_file = Path(catalogue_path).expanduser().resolve(strict=True)
    resolution_file = Path(resolution_path).expanduser().resolve(strict=True)
    if not helper.is_file():
        raise FileNotFoundError(helper)
    catalogue, resolution = load_equipment_capture_inputs(
        catalogue_file, resolution_file
    )
    protected_roots = [Path(__file__).resolve().parents[2], evidence]
    game_root_text = str(
        _mapping(resolution.get("live_archive")).get("package_root", "") or ""
    )
    if game_root_text:
        protected_roots.append(Path(game_root_text).expanduser().resolve())
    if any(
        output == protected
        or output.is_relative_to(protected)
        or protected.is_relative_to(output)
        for protected in protected_roots
    ):
        raise EquipmentPerformanceError(
            "Repetition output must remain outside the repository, census, and game install."
        )
    if any(
        cache == protected
        or cache.is_relative_to(protected)
        or protected.is_relative_to(cache)
        for protected in protected_roots
    ) or (
        cache == output
        or cache.is_relative_to(output)
        or output.is_relative_to(cache)
    ):
        raise EquipmentPerformanceError(
            "Repetition cache must remain separate from the repository, census, game install, and evidence output."
        )
    if (output / "equipment-performance-repetitions.json").exists():
        raise EquipmentPerformanceError(
            "Repetition output already exists; choose a new output root."
        )
    summary = build_equipment_performance_summary(evidence)
    census = _mapping(summary.get("census"))
    plan = _mapping(summary.get("repetition_plan"))
    if (
        census.get("complete") is not True
        or plan.get("status") != "ready_for_production_runner"
    ):
        raise EquipmentPerformanceError(
            "The exact final census must be complete before repetition targets are frozen."
        )
    targets = _mapping_rows(plan, "targets")
    _validate_repetition_inputs_against_census(
        _mapping(_mapping(summary.get("capture_manifest")).get("census_identity")),
        catalogue_path=catalogue_file,
        resolution_path=resolution_file,
        catalogue=catalogue,
        resolution=resolution,
    )
    capture_plans = build_equipment_capture_plans(catalogue, resolution)
    plans_by_asset = {str(row.get("asset_id", "")): row for row in capture_plans}
    missing_target_plans = [
        str(target.get("asset_id", ""))
        for target in targets
        if str(target.get("asset_id", "")) not in plans_by_asset
    ]
    if missing_target_plans:
        raise EquipmentPerformanceError(
            "Frozen targets are absent from the bound capture plan: "
            + ", ".join(missing_target_plans)
        )
    binaries = resolve_capture_binary_evidence(helper)
    census_binaries = _mapping(
        _mapping(summary.get("capture_manifest")).get("capture_binaries")
    )
    if not _capture_binaries_match(binaries, census_binaries):
        raise EquipmentPerformanceError(
            "Repetition helper hashes differ from the finalized census binaries."
        )
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    reports_root = output / "reports"
    reports_root.mkdir(parents=True, exist_ok=False)
    runtime_root = output / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=False)
    result_path = output / "equipment-performance-repetitions.json"
    result: dict[str, object] = {
        "schema": EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA,
        "complete": False,
        "production_path": PRODUCTION_RENDERER_PATH,
        "capture_binaries": binaries,
        "census_manifest_sha256": _mapping(summary.get("capture_manifest")).get(
            "sha256"
        ),
        "cold_repetitions_per_target": COLD_REPETITIONS,
        "warm_repetitions_per_target": WARM_REPETITIONS,
        "targets": targets,
        "samples": [],
        "retained_reports": [],
    }
    _write_repetition_checkpoint(result_path, result)

    timeout = max(30.0, float(capture_timeout_seconds))
    try:
        for target in targets:
            asset_id = str(target["asset_id"])
            plan_row = plans_by_asset.get(asset_id)
            if plan_row is None:
                raise EquipmentPerformanceError(
                    f"Frozen target {asset_id} is absent from the capture plan."
                )
            for repetition in range(1, COLD_REPETITIONS + 1):
                runtime = Path(
                    tempfile.mkdtemp(prefix=f"{asset_id}-cold-", dir=runtime_root)
                )
                try:
                    cold_cache = runtime / "isolated-empty-cache"
                    cold_cache.mkdir(parents=True, exist_ok=False)
                    prepared = _prepare_production_packages(
                        plan_row,
                        runtime,
                        cache_root=cold_cache,
                        use_service=False,
                        build_rust_preview_package_from_preview_core=(
                            build_rust_preview_package_from_preview_core
                        ),
                        run_native_preview_core_preview_job=run_native_preview_core_preview_job,
                        archive_entry_from_worker=archive_entry_from_worker,
                        validate_native_manifest=_validate_native_manifest,
                        validate_rust_manifest=_validate_rust_package_manifest,
                        timeout_seconds=timeout,
                    )
                    _append_full_package(
                        prepared,
                        runtime,
                        build_rust_preview_package_from_preview_core=(
                            build_rust_preview_package_from_preview_core
                        ),
                        validate_rust_manifest=_validate_rust_package_manifest,
                    )
                    direct_report, direct_process = _run_repeated_audit_process(
                        helper,
                        Path(str(prepared["direct_manifest_path"])),
                        runtime / "cold-direct",
                        repetitions=1,
                        timeout_seconds=timeout,
                    )
                    full_report, full_process = _run_repeated_audit_process(
                        helper,
                        Path(str(prepared["full_manifest_path"])),
                        runtime / "cold-full",
                        repetitions=1,
                        timeout_seconds=timeout,
                    )
                    retained = _retain_audit_reports(
                        reports_root / asset_id / f"cold-{repetition:02d}",
                        {"direct": direct_report, "full": full_report},
                    )
                    sample = _cold_sample(
                        target,
                        repetition,
                        prepared,
                        direct_report,
                        direct_process,
                        full_report,
                        full_process,
                        retained,
                    )
                    cast_samples = result["samples"]
                    cast_reports = result["retained_reports"]
                    if isinstance(cast_samples, list):
                        cast_samples.append(sample)
                    if isinstance(cast_reports, list):
                        cast_reports.extend(retained.values())
                    _write_repetition_checkpoint(result_path, result)
                finally:
                    shutil.rmtree(runtime, ignore_errors=True)

            runtime = Path(
                tempfile.mkdtemp(prefix=f"{asset_id}-warm-", dir=runtime_root)
            )
            try:
                prepared = _prepare_production_packages(
                    plan_row,
                    runtime,
                    cache_root=cache,
                    use_service=True,
                    build_rust_preview_package_from_preview_core=(
                        build_rust_preview_package_from_preview_core
                    ),
                    run_native_preview_core_preview_job=run_native_preview_core_preview_job,
                    archive_entry_from_worker=archive_entry_from_worker,
                    validate_native_manifest=_validate_native_manifest,
                    validate_rust_manifest=_validate_rust_package_manifest,
                    timeout_seconds=timeout,
                )
                _append_full_package(
                    prepared,
                    runtime,
                    build_rust_preview_package_from_preview_core=(
                        build_rust_preview_package_from_preview_core
                    ),
                    validate_rust_manifest=_validate_rust_package_manifest,
                )
                direct_report, _ = _run_repeated_audit_process(
                    helper,
                    Path(str(prepared["direct_manifest_path"])),
                    runtime / "warm-direct-prime",
                    repetitions=1,
                    timeout_seconds=timeout,
                )
                warm_report, warm_process = _run_repeated_audit_process(
                    helper,
                    Path(str(prepared["full_manifest_path"])),
                    runtime / "warm-full",
                    repetitions=WARM_REPETITIONS,
                    timeout_seconds=max(timeout, timeout * WARM_REPETITIONS),
                )
                retained = _retain_audit_reports(
                    reports_root / asset_id / "warm",
                    {"direct-prime": direct_report, "full-repetitions": warm_report},
                )
                warm_samples = _warm_samples(
                    target,
                    prepared,
                    warm_report,
                    warm_process,
                    retained,
                )
                cast_samples = result["samples"]
                cast_reports = result["retained_reports"]
                if isinstance(cast_samples, list):
                    cast_samples.extend(warm_samples)
                if isinstance(cast_reports, list):
                    cast_reports.extend(retained.values())
                _write_repetition_checkpoint(result_path, result)
            finally:
                shutil.rmtree(runtime, ignore_errors=True)
        result["complete"] = True
        result["acceptance"] = evaluate_equipment_repetition_results(
            result,
            baseline=None,
            expected_targets=targets,
            expected_capture_binaries=census_binaries,
            expected_census_manifest_sha256=str(
                _mapping(summary.get("capture_manifest")).get("sha256", "") or ""
            ),
        )
        _write_repetition_checkpoint(result_path, result)
        return result
    finally:
        try:
            runtime_root.rmdir()
        except OSError:
            pass


def _prepare_production_packages(
    plan: Mapping[str, object],
    runtime: Path,
    *,
    cache_root: Path,
    use_service: bool,
    build_rust_preview_package_from_preview_core: Any,
    run_native_preview_core_preview_job: Any,
    archive_entry_from_worker: Any,
    validate_native_manifest: Any,
    validate_rust_manifest: Any,
    timeout_seconds: float,
) -> dict[str, object]:
    primary_component = _mapping(plan.get("primary_component"))
    primary_entry_row = _mapping(primary_component.get("entry"))
    primary_entry = archive_entry_from_worker(primary_entry_row)
    dependencies = tuple(
        archive_entry_from_worker(_mapping(component.get("entry")))
        for component in _sequence(plan.get("physical_components"))
        if _mapping(component.get("entry")) != primary_entry_row
    )
    native_root = runtime / "preview-core"
    native_started = time.perf_counter()
    attempt = run_native_preview_core_preview_job(
        primary_entry,
        cache_root=cache_root,
        dependency_entries=dependencies,
        dependency_entries_complete=False,
        enabled_prefab_component_paths=tuple(
            str(value)
            for value in _sequence(plan.get("enabled_prefab_component_paths"))
        ),
        model_property_indices={
            str(key): _safe_int(value, 0)
            for key, value in _mapping(
                plan.get("canonical_model_property_indices")
            ).items()
        },
        package_root=Path(str(primary_entry.pamt_path)).parent.parent,
        output_root=native_root,
        timeout_seconds=timeout_seconds,
        use_service=use_service,
        dds_cache_max_bytes=8 * 1024 * 1024 * 1024,
        dds_cache_target_bytes=7 * 1024 * 1024 * 1024,
    )
    native_wall_ms = (time.perf_counter() - native_started) * 1000.0
    if not attempt.succeeded:
        raise RuntimeError(
            f"Preview Core failed for {plan.get('identity')}: "
            f"{attempt.fallback_reason or attempt.status}"
        )
    native_manifest_path = Path(attempt.package_path) / "manifest.json"
    native_manifest = _read_json_object(
        native_manifest_path, label="Preview Core manifest"
    )
    native_gates = validate_native_manifest(native_manifest, plan)
    if not all(native_gates.values()):
        failed = [str(key) for key, value in native_gates.items() if not value]
        raise RuntimeError(f"Preview Core material gates failed: {', '.join(failed)}")

    direct_started = time.perf_counter()
    direct = build_rust_preview_package_from_preview_core(
        native_root,
        output_package_dir=runtime / "rust-direct",
        material_quality="direct",
    )
    direct_build_ms = (time.perf_counter() - direct_started) * 1000.0
    validate_rust_manifest(
        _read_json_object(direct.manifest_path, label="direct Rust manifest"),
        quality="direct",
    )
    return {
        "native_elapsed_ms": float(attempt.elapsed_ms),
        "native_wall_ms": native_wall_ms,
        "preview_core_schema_version": _safe_int(
            native_manifest.get("schema_version"), -1
        ),
        "material_graph_version": _safe_int(
            native_manifest.get("material_graph_version"), -1
        ),
        "material_semantics_version": _safe_int(
            native_manifest.get("material_semantics_version"), -1
        ),
        "direct_build_ms": direct_build_ms,
        "direct_manifest_path": str(direct.manifest_path),
        "native_root": str(native_root),
        "native_cache_root": str(cache_root),
        "native_service_used": use_service,
        "native_cache_started_empty": not use_service,
        "native_process_private_bytes": _safe_int(
            _mapping(attempt.diagnostics).get("process_private_bytes"), -1
        ),
        "native_process_working_set_bytes": _safe_int(
            _mapping(attempt.diagnostics).get("process_working_set_bytes"), -1
        ),
        "fallback_reason": str(attempt.fallback_reason or ""),
        "service_recycle_reason": str(
            _mapping(attempt.diagnostics).get("service_recycle_reason", "") or ""
        ),
    }


def _validate_repetition_inputs_against_census(
    census_identity: Mapping[str, object],
    *,
    catalogue_path: Path,
    resolution_path: Path,
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
) -> None:
    if census_identity.get("schema") != EQUIPMENT_CAPTURE_IDENTITY_SCHEMA:
        raise EquipmentPerformanceError(
            "Finalized census has no compatible immutable input identity."
        )
    expected_catalogue = _mapping(census_identity.get("catalogue"))
    actual_catalogue = {
        "schema": catalogue.get("schema"),
        "file_sha256": _sha256_file(catalogue_path),
        "selection_sha256": _mapping(catalogue.get("selection")).get(
            "selection_sha256"
        ),
    }
    expected_resolution = _mapping(census_identity.get("resolution"))
    actual_resolution = {
        "schema": resolution.get("schema"),
        "file_sha256": _sha256_file(resolution_path),
        "resolution_sha256": resolution.get("resolution_sha256"),
    }
    live_archive = dict(_mapping(resolution.get("live_archive")))
    expected_archive = _mapping(census_identity.get("archive"))
    actual_archive = {
        "live_archive": live_archive,
        "sha256": _canonical_json_sha256(live_archive),
    }
    if dict(expected_catalogue) != actual_catalogue:
        raise EquipmentPerformanceError(
            "Repetition catalogue bytes/selection differ from the finalized census."
        )
    if dict(expected_resolution) != actual_resolution:
        raise EquipmentPerformanceError(
            "Repetition resolution bytes differ from the finalized census."
        )
    if dict(expected_archive) != actual_archive:
        raise EquipmentPerformanceError(
            "Repetition live-archive identity differs from the finalized census."
        )


def _append_full_package(
    prepared: dict[str, object],
    runtime: Path,
    *,
    build_rust_preview_package_from_preview_core: Any,
    validate_rust_manifest: Any,
) -> None:
    full_started = time.perf_counter()
    full = build_rust_preview_package_from_preview_core(
        Path(str(prepared["native_root"])),
        output_package_dir=runtime / "rust-full",
        material_quality="full",
    )
    prepared["full_build_ms"] = (time.perf_counter() - full_started) * 1000.0
    prepared["full_manifest_path"] = str(full.manifest_path)
    validate_rust_manifest(
        _read_json_object(full.manifest_path, label="full Rust manifest"),
        quality="full",
    )


def _run_repeated_audit_process(
    helper: Path,
    manifest_path: Path,
    output_root: Path,
    *,
    repetitions: int,
    timeout_seconds: float,
) -> tuple[dict[str, object], dict[str, object]]:
    command = [
        str(helper),
        "--capture-cdmw-preview-session",
        str(manifest_path),
        "--capture-audit-output",
        str(output_root),
        "--capture-audit-full-model-only",
    ]
    if repetitions > 1:
        command.extend(["--capture-audit-repetitions", str(repetitions)])
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=helper.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    peak_private_bytes = 0
    peak_working_set_bytes = 0
    observed = psutil.Process(process.pid)
    deadline = started + max(30.0, float(timeout_seconds))
    while process.poll() is None:
        try:
            memory = observed.memory_info()
            peak_private_bytes = max(
                peak_private_bytes, int(getattr(memory, "private", 0) or 0)
            )
            peak_working_set_bytes = max(
                peak_working_set_bytes,
                int(getattr(memory, "peak_wset", getattr(memory, "rss", 0)) or 0),
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        if time.perf_counter() >= deadline:
            process.kill()
            stdout, stderr = process.communicate()
            detail = (stderr or stdout or "")[-4000:]
            raise RuntimeError(f"Repeated Rust audit timed out: {detail}")
        time.sleep(0.005)
    stdout, stderr = process.communicate()
    process_wall_ms = (time.perf_counter() - started) * 1000.0
    if process.returncode != 0:
        detail = (stderr or stdout or "")[-4000:]
        raise RuntimeError(f"Repeated Rust audit exited {process.returncode}: {detail}")
    report_path = output_root / "audit-report.json"
    report = _read_json_object(report_path, label="repeated Rust audit report")
    _validate_repeated_audit_report(
        report,
        repetitions=repetitions,
        expected_manifest_path=manifest_path,
    )
    if peak_private_bytes <= 0 or peak_working_set_bytes <= 0:
        raise EquipmentPerformanceError(
            "Repeated Rust audit process memory sampling produced no positive sample."
        )
    return report, {
        "process_wall_ms": round(process_wall_ms, 3),
        "peak_private_bytes": peak_private_bytes,
        "peak_working_set_bytes": peak_working_set_bytes,
        "timed_out": False,
        "exit_code": int(process.returncode or 0),
    }


def _validate_repeated_audit_report(
    report: Mapping[str, object],
    *,
    repetitions: int,
    expected_manifest_path: Path | None = None,
) -> None:
    adapter = _mapping(report.get("adapter"))
    source = _mapping(report.get("source_dds"))
    runtime = _mapping(report.get("runtime_dds"))
    captures = _sequence(report.get("captures"))
    _validated_phase_timings(report, label="repeated Rust audit")
    runtime_count = _safe_int(runtime.get("resource_count"), -1)
    logical_runtime_count = _safe_int(runtime.get("logical_resource_count"), -1)
    copied_source_count = _safe_int(source.get("copied_source_dds_count"), -1)
    unique_source_count = _safe_int(source.get("unique_source_dds_count"), -1)
    uploaded_resource_bytes = _safe_int(runtime.get("uploaded_resource_bytes"), -1)
    unique_binary_bytes = _safe_int(runtime.get("unique_binary_bytes"), -1)
    capture_contract_ok = True
    for repetition_index in range(repetitions):
        repetition_captures = [
            _mapping(capture)
            for capture in captures
            if _safe_int(_mapping(capture).get("repetition_index"), -1)
            == repetition_index
        ]
        if [str(capture.get("name", "")) for capture in repetition_captures] != list(
            FULL_MODEL_VIEWS
        ):
            capture_contract_ok = False
            break
        for capture in repetition_captures:
            frames = _mapping(capture.get("frames"))
            if (
                capture.get("capture_kind") != "full_model"
                or _safe_int(capture.get("dds_textures_uploaded"), -2) != runtime_count
                or any(
                    _safe_int(
                        _mapping(frames.get(frame)).get("non_background_pixels"), 0
                    )
                    <= 0
                    for frame in ("textured", "base_color", "part_id")
                )
            ):
                capture_contract_ok = False
                break
    if not (
        report.get("schema") == "cdmw_rust_material_audit_capture_v2"
        and report.get("ok") is True
        and report.get("renderer") == "wgpu_d3d12_rust"
        and str(adapter.get("backend", "")).casefold() == "dx12"
        and report.get("full_model_only") is True
        and _safe_int(report.get("repetition_count"), 1) == repetitions
        and _safe_int(report.get("capture_count"), -1) == repetitions * 6
        and len(captures) == repetitions * 6
        and capture_contract_ok
        and report.get("dds_resources_uploaded_once_for_capture_set") is True
        and source.get("available") is True
        and source.get("measurement") == "actual_rust_source_dds_decode_events_v1"
        and source.get("each_source_binary_decoded_at_most_once") is True
        and source.get("full_source_decode_complete") is True
        and copied_source_count >= 0
        and unique_source_count >= 0
        and copied_source_count <= unique_source_count
        and runtime.get("no_duplicate_upload_keys") is True
        and runtime.get("upload_key") == "dds_sha256"
        and runtime.get("role_specific_sampling_views_share_one_physical_upload") is True
        and runtime.get("renderer_uploads_match_unique_binaries") is True
        and _safe_int(runtime.get("duplicate_upload_key_count"), -1) == 0
        and runtime_count >= 0
        and _safe_int(runtime.get("unique_binary_count"), -1) == runtime_count
        and logical_runtime_count >= runtime_count
        and _safe_int(runtime.get("renderer_reported_upload_count"), -2)
        == runtime_count
        and uploaded_resource_bytes >= 0
        and unique_binary_bytes >= 0
        and uploaded_resource_bytes == unique_binary_bytes
        and _safe_int(runtime.get("reported_gpu_resident_bytes"), -1) >= 0
    ):
        raise EquipmentPerformanceError(
            "Repeated Rust audit report failed its D3D12/dedup/capture contract."
        )
    if expected_manifest_path is not None:
        expected_manifest = expected_manifest_path.resolve(strict=True)
        source_manifest = _mapping(report.get("source_manifest"))
        source_path_text = str(source_manifest.get("path", "") or "")
        try:
            source_path = Path(source_path_text).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise EquipmentPerformanceError(
                "Repeated Rust audit report source manifest path is invalid."
            ) from exc
        if not (
            source_path == expected_manifest
            and _safe_int(source_manifest.get("bytes"), -1)
            == expected_manifest.stat().st_size
            and str(source_manifest.get("sha256", "") or "").casefold()
            == _sha256_file(expected_manifest)
        ):
            raise EquipmentPerformanceError(
                "Repeated Rust audit report does not match the requested source manifest."
            )
    if repetitions <= 1:
        return
    proof = _mapping(report.get("warm_cache_proof"))
    raw_timings = _sequence(proof.get("per_repetition_wall_ms"))
    timings = [
        value
        for raw in raw_timings
        if (value := _optional_number(raw)) is not None
    ]
    if not (
        proof.get("schema") == "cdmw_rust_warm_material_capture_v1"
        and proof.get("valid") is True
        and _safe_int(proof.get("package_load_count"), -1) == 1
        and _safe_int(proof.get("renderer_device_count"), -1) == 1
        and _safe_int(proof.get("renderer_batch_count"), -1) == 1
        and _safe_int(proof.get("texture_upload_pass_count"), -1) == 1
        and proof.get("dds_textures_uploaded_once_for_repetition_set") is True
        and _safe_int(proof.get("package_reloads_between_repetitions"), -1) == 0
        and _safe_int(proof.get("resource_reloads_between_repetitions"), -1) == 0
        and len(raw_timings) == repetitions
        and len(timings) == repetitions
    ):
        raise EquipmentPerformanceError(
            "Repeated Rust audit report failed its resident warm-cache proof."
        )


def _cold_sample(
    target: Mapping[str, object],
    repetition: int,
    prepared: Mapping[str, object],
    direct_report: Mapping[str, object],
    direct_process: Mapping[str, object],
    full_report: Mapping[str, object],
    full_process: Mapping[str, object],
    retained: Mapping[str, str],
) -> dict[str, object]:
    native_wall = _required_number(prepared, "native_wall_ms")
    direct_build = _required_number(prepared, "direct_build_ms")
    full_build = _required_number(prepared, "full_build_ms")
    direct_phase = _validated_phase_timings(direct_report, label="cold direct Rust audit")
    full_phase = _validated_phase_timings(full_report, label="cold full Rust audit")
    direct_first_frame_ms = _parent_observed_phase_ms(
        direct_process, direct_phase, "first_textured_frame_ms"
    )
    full_resources_ready_ms = _parent_observed_phase_ms(
        full_process, full_phase, "texture_resources_ready_ms"
    )
    first_usable_ms = native_wall + direct_build + direct_first_frame_ms
    full_texture_readiness_ms = (
        native_wall + direct_build + full_build + full_resources_ready_ms
    )
    direct_runtime = _mapping(direct_report.get("runtime_dds"))
    full_runtime = _mapping(full_report.get("runtime_dds"))
    peak_private_bytes = max(
        _required_positive_number(prepared, "native_process_private_bytes"),
        _required_positive_number(direct_process, "peak_private_bytes"),
        _required_positive_number(full_process, "peak_private_bytes"),
    )
    peak_working_set_bytes = max(
        _required_positive_number(prepared, "native_process_working_set_bytes"),
        _required_positive_number(direct_process, "peak_working_set_bytes"),
        _required_positive_number(full_process, "peak_working_set_bytes"),
    )
    return {
        "asset_id": target.get("asset_id"),
        "identity": target.get("identity"),
        "mode": "cold",
        "repetition": repetition,
        **_sample_contract_fields(prepared, full_report, direct_runtime, full_runtime),
        "first_usable_ms": round(first_usable_ms, 3),
        "full_texture_readiness_ms": round(full_texture_readiness_ms, 3),
        "timing_basis": "explicit_rust_phase_milestones_v1",
        "preview_core_wall_ms": round(native_wall, 3),
        "direct_package_build_ms": round(direct_build, 3),
        "full_package_build_ms": round(full_build, 3),
        "direct_phase_timings": {
            "schema": RUST_MATERIAL_PHASE_TIMINGS_SCHEMA,
            **direct_phase,
        },
        "full_phase_timings": {
            "schema": RUST_MATERIAL_PHASE_TIMINGS_SCHEMA,
            **full_phase,
        },
        "direct_process_boundary_overhead_ms": round(
            _process_boundary_overhead_ms(direct_process, direct_phase), 3
        ),
        "full_process_boundary_overhead_ms": round(
            _process_boundary_overhead_ms(full_process, full_phase), 3
        ),
        "direct_first_textured_frame_with_process_boundary_overhead_ms": round(
            direct_first_frame_ms, 3
        ),
        "full_texture_resources_ready_with_process_boundary_overhead_ms": round(
            full_resources_ready_ms, 3
        ),
        "direct_audit_completion_wall_ms": round(
            _required_number(direct_process, "process_wall_ms"), 3
        ),
        "full_audit_completion_wall_ms": round(
            _required_number(full_process, "process_wall_ms"), 3
        ),
        "peak_private_bytes": round(peak_private_bytes),
        "peak_working_set_bytes": round(peak_working_set_bytes),
        "gpu_resident_bytes": max(
            _safe_int(direct_runtime.get("reported_gpu_resident_bytes"), -1),
            _safe_int(full_runtime.get("reported_gpu_resident_bytes"), -1),
        ),
        "package_reload_count": 2,
        "resource_reload_count": 2,
        "reports": dict(retained),
    }


def _warm_samples(
    target: Mapping[str, object],
    prepared: Mapping[str, object],
    report: Mapping[str, object],
    process: Mapping[str, object],
    retained: Mapping[str, str],
) -> list[dict[str, object]]:
    proof = _mapping(report.get("warm_cache_proof"))
    timings = [float(value) for value in _sequence(proof.get("per_repetition_wall_ms"))]
    runtime = _mapping(report.get("runtime_dds"))
    phase = _validated_phase_timings(report, label="resident warm Rust audit")
    peak_private_bytes = max(
        _required_positive_number(prepared, "native_process_private_bytes"),
        _required_positive_number(process, "peak_private_bytes"),
    )
    peak_working_set_bytes = max(
        _required_positive_number(prepared, "native_process_working_set_bytes"),
        _required_positive_number(process, "peak_working_set_bytes"),
    )
    gpu_resident_bytes = _required_number(runtime, "reported_gpu_resident_bytes")
    base = {
        **_sample_contract_fields(prepared, report, runtime, runtime),
        "package_reload_count": _safe_int(
            proof.get("package_reloads_between_repetitions"), -1
        ),
        "resource_reload_count": _safe_int(
            proof.get("resource_reloads_between_repetitions"), -1
        ),
        "resident_package_load_count": _safe_int(proof.get("package_load_count"), -1),
        "resident_renderer_device_count": _safe_int(
            proof.get("renderer_device_count"), -1
        ),
        "resident_renderer_batch_count": _safe_int(
            proof.get("renderer_batch_count"), -1
        ),
        "resident_texture_upload_pass_count": _safe_int(
            proof.get("texture_upload_pass_count"), -1
        ),
        "resident_process_wall_ms": _required_number(process, "process_wall_ms"),
        "resident_phase_timings": {
            "schema": RUST_MATERIAL_PHASE_TIMINGS_SCHEMA,
            **phase,
        },
        "resident_peak_private_bytes": round(
            _required_positive_number(process, "peak_private_bytes")
        ),
        "resident_peak_working_set_bytes": round(
            _required_positive_number(process, "peak_working_set_bytes")
        ),
        "peak_private_bytes": round(peak_private_bytes),
        "peak_working_set_bytes": round(peak_working_set_bytes),
        "gpu_resident_bytes": round(gpu_resident_bytes),
        "reports": dict(retained),
    }
    return [
        {
            "asset_id": target.get("asset_id"),
            "identity": target.get("identity"),
            "mode": "warm",
            "repetition": index,
            **base,
            "warm_capture_ms": round(value, 3),
        }
        for index, value in enumerate(timings, 1)
    ]


def _sample_contract_fields(
    prepared: Mapping[str, object],
    report: Mapping[str, object],
    direct_runtime: Mapping[str, object],
    full_runtime: Mapping[str, object],
) -> dict[str, object]:
    adapter = _mapping(report.get("adapter"))
    duplicate_bytes = sum(
        max(
            0,
            _safe_int(runtime.get("uploaded_resource_bytes"), -1)
            - _safe_int(runtime.get("unique_binary_bytes"), -1),
        )
        for runtime in (direct_runtime, full_runtime)
    )
    physical_upload_identity_ok = all(
        runtime.get("upload_key") == "dds_sha256"
        and _safe_int(runtime.get("resource_count"), -1) >= 0
        and _safe_int(runtime.get("unique_binary_count"), -2)
        == _safe_int(runtime.get("resource_count"), -1)
        and _safe_int(runtime.get("logical_resource_count"), -1)
        >= _safe_int(runtime.get("resource_count"), 0)
        for runtime in (direct_runtime, full_runtime)
    )
    return {
        "renderer_path": PRODUCTION_RENDERER_PATH,
        "renderer": report.get("renderer"),
        "adapter_backend": adapter.get("backend"),
        "preview_core_schema_version": prepared.get(
            "preview_core_schema_version"
        ),
        "material_graph_version": prepared.get("material_graph_version"),
        "material_semantics_version": prepared.get("material_semantics_version"),
        "python_material_synthesis_used": False,
        "native_service_used": prepared.get("native_service_used"),
        "native_cache_started_empty": prepared.get("native_cache_started_empty"),
        "timed_out": False,
        "process_restart_count": int(
            str(prepared.get("service_recycle_reason", "") or "")
            not in _CONTROLLED_POST_JOB_RECYCLE_REASONS
        ),
        "post_job_service_recycle_reason": str(
            prepared.get("service_recycle_reason", "") or ""
        ),
        "renderer_fallback": bool(str(prepared.get("fallback_reason", "") or "")),
        "duplicate_upload_key_count": max(
            _safe_int(direct_runtime.get("duplicate_upload_key_count"), -1),
            _safe_int(full_runtime.get("duplicate_upload_key_count"), -1),
        ),
        "duplicate_parameter_texture_bytes": duplicate_bytes,
        "physical_upload_identity": "dds_sha256",
        "one_physical_upload_per_binary": physical_upload_identity_ok,
    }


def _retain_audit_reports(
    destination: Path, reports: Mapping[str, Mapping[str, object]]
) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    retained: dict[str, str] = {}
    for name, report in reports.items():
        source = Path(str(_mapping(report.get("source_manifest")).get("path", "")))
        report_path = destination / f"{name}-audit-report.json"
        atomic_write_text(
            report_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        retained[name] = str(report_path)
        if source.is_file():
            manifest_path = destination / f"{name}-manifest.json"
            atomic_copy_file(source, manifest_path)
            retained[f"{name}_manifest"] = str(manifest_path)
    return retained


def _write_repetition_checkpoint(path: Path, result: Mapping[str, object]) -> None:
    atomic_write_text(path, json.dumps(result, indent=2, sort_keys=True) + "\n")


def _instrumented_asset_row(
    asset_root: Path,
    manifest_row: Mapping[str, object],
    report: Mapping[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    performance = _mapping(report.get("performance"))
    preview = _mapping(performance.get("preview_core"))
    package = _mapping(performance.get("package_build"))
    render = _mapping(performance.get("render"))
    direct = _mapping(render.get("direct"))
    full = _mapping(render.get("full"))
    resources = _mapping(performance.get("resources"))
    direct_source = _mapping(resources.get("direct_source_dds"))
    full_source = _mapping(resources.get("full_source_dds"))
    direct_runtime = _mapping(resources.get("direct_runtime_dds"))
    full_runtime = _mapping(resources.get("full_runtime_dds"))
    direct_phase = _validated_phase_timings(
        direct, label=f"direct Rust audit {asset_root.name}"
    )
    full_phase = _validated_phase_timings(
        full, label=f"full Rust audit {asset_root.name}"
    )

    numeric = {
        "asset_wall_ms": _required_number(report, "wall_ms"),
        "preview_core_elapsed_ms": _required_number(preview, "elapsed_ms"),
        "preview_core_wall_ms": _required_number(preview, "wall_ms"),
        "direct_package_build_ms": _required_number(package, "direct_ms"),
        "full_package_build_ms": _required_number(package, "full_ms"),
        "direct_process_wall_ms": _required_number(direct, "process_wall_ms"),
        "full_process_wall_ms": _required_number(full, "process_wall_ms"),
        "direct_renderer_wall_ms": _required_number(direct, "renderer_wall_ms"),
        "full_renderer_wall_ms": _required_number(full, "renderer_wall_ms"),
        "direct_peak_private_bytes": _required_number(direct, "peak_private_bytes"),
        "full_peak_private_bytes": _required_number(full, "peak_private_bytes"),
        "direct_peak_working_set_bytes": _required_number(
            direct, "peak_working_set_bytes"
        ),
        "full_peak_working_set_bytes": _required_number(full, "peak_working_set_bytes"),
        "direct_gpu_resident_bytes": _required_number(
            direct_runtime, "reported_gpu_resident_bytes"
        ),
        "full_gpu_resident_bytes": _required_number(
            full_runtime, "reported_gpu_resident_bytes"
        ),
    }
    native_diagnostics = _mapping(
        _mapping(report.get("preview_core")).get("diagnostics")
    )
    numeric["preview_core_process_private_bytes"] = _required_number(
        native_diagnostics, "process_private_bytes"
    )
    numeric["preview_core_process_working_set_bytes"] = _required_number(
        native_diagnostics, "process_working_set_bytes"
    )
    for quality, phase in (("direct", direct_phase), ("full", full_phase)):
        for field, value in phase.items():
            numeric[f"{quality}_{field}"] = value
    numeric["direct_process_boundary_overhead_ms"] = _process_boundary_overhead_ms(
        direct, direct_phase
    )
    numeric["full_process_boundary_overhead_ms"] = _process_boundary_overhead_ms(
        full, full_phase
    )
    numeric["direct_first_textured_frame_with_process_boundary_overhead_ms"] = (
        _parent_observed_phase_ms(direct, direct_phase, "first_textured_frame_ms")
    )
    numeric["full_texture_resources_ready_with_process_boundary_overhead_ms"] = (
        _parent_observed_phase_ms(full, full_phase, "texture_resources_ready_ms")
    )
    numeric["first_usable_ms"] = (
        numeric["preview_core_wall_ms"]
        + numeric["direct_package_build_ms"]
        + numeric["direct_first_textured_frame_with_process_boundary_overhead_ms"]
    )
    numeric["full_texture_readiness_ms"] = (
        numeric["preview_core_wall_ms"]
        + numeric["direct_package_build_ms"]
        + numeric["full_package_build_ms"]
        + numeric[
            "full_texture_resources_ready_with_process_boundary_overhead_ms"
        ]
    )
    numeric["peak_private_bytes"] = max(
        numeric["preview_core_process_private_bytes"],
        numeric["direct_peak_private_bytes"],
        numeric["full_peak_private_bytes"],
    )
    numeric["gpu_resident_bytes"] = max(
        numeric["direct_gpu_resident_bytes"], numeric["full_gpu_resident_bytes"]
    )

    full_manifest_row = _mapping(
        _mapping(report.get("rust_packages")).get("full_manifest")
    )
    full_manifest = _read_evidence_object(
        asset_root,
        full_manifest_row,
        label=f"full Rust manifest {asset_root.name}",
    )
    geometry = _mapping(full_manifest.get("preview_core_geometry"))
    batches = _sequence(geometry.get("batches"))
    presentations = [
        _mapping(row) for row in _sequence(full_manifest.get("material_presentations"))
    ]
    categories = sorted(
        {
            str(row.get("material_category", "") or "")
            for row in presentations
            if str(row.get("material_category", "") or "")
        },
        key=str.casefold,
    )
    normalized_categories = {category.casefold() for category in categories}
    required_mixed_categories = {"metal", "leather", "cloth"}
    regions = _sequence(
        _mapping(report.get("composites")).get("material_region_sheets")
    )
    logical_edges = _safe_int(resources.get("logical_texture_edge_count"), -1)
    unique_dds_bytes = max(
        _safe_int(direct_source.get("unique_source_dds_bytes"), -1),
        _safe_int(full_source.get("unique_source_dds_bytes"), -1),
    )
    facts = {
        "graph_edge_count": logical_edges,
        "unique_dds_bytes": unique_dds_bytes,
        "visible_submesh_count": len(batches),
        "material_region_count": len(regions),
        "mixed_material_category_count": len(categories),
        "metal_leather_cloth_category_count": len(
            normalized_categories & required_mixed_categories
        ),
        "contains_metal_leather_cloth": required_mixed_categories.issubset(
            normalized_categories
        ),
        "material_categories": categories,
    }

    identity = str(report.get("identity", "") or "")
    asset_id = str(report.get("asset_id", "") or "")
    failures: list[dict[str, object]] = []

    def fail(gate: str, detail: str) -> None:
        failures.append(
            {"asset_id": asset_id, "identity": identity, "gate": gate, "detail": detail}
        )

    diagnostics = native_diagnostics
    if report.get("renderer_path") != PRODUCTION_RENDERER_PATH:
        fail("production_path", str(report.get("renderer_path", "")))
    if report.get("python_material_synthesis_used") is not False:
        fail("python_material_synthesis_disabled", "expected false")
    if str(diagnostics.get("fallback_reason", "") or ""):
        fail("renderer_fallback", str(diagnostics.get("fallback_reason")))
    service_recycle_reason = str(diagnostics.get("service_recycle_reason", "") or "")
    if service_recycle_reason not in _CONTROLLED_POST_JOB_RECYCLE_REASONS:
        fail("process_restart", service_recycle_reason)
    gates = _mapping(report.get("technical_gates"))
    failed_technical = sorted(
        str(key) for key, value in gates.items() if value is not True
    )
    if not gates or failed_technical:
        fail("technical_gates", ",".join(failed_technical) or "missing")
    for metric in (
        "preview_core_process_private_bytes",
        "preview_core_process_working_set_bytes",
        "direct_peak_private_bytes",
        "full_peak_private_bytes",
        "direct_peak_working_set_bytes",
        "full_peak_working_set_bytes",
    ):
        if numeric[metric] <= 0:
            fail("process_memory_sample", f"{metric} has no positive sample")
    for quality, process, source, runtime in (
        ("direct", direct, direct_source, direct_runtime),
        ("full", full, full_source, full_runtime),
    ):
        if process.get("timed_out") is not False:
            fail(f"{quality}_timeout", str(process.get("timed_out")))
        if _safe_int(process.get("exit_code"), -1) != 0:
            fail(f"{quality}_exit", str(process.get("exit_code")))
        copied_source_count = _safe_int(source.get("copied_source_dds_count"), -1)
        unique_source_count = _safe_int(source.get("unique_source_dds_count"), -1)
        if source.get("each_source_binary_decoded_at_most_once") is not True:
            fail(f"{quality}_decode_dedup", "source binary was decoded more than once")
        if (
            source.get("available") is not True
            or source.get("measurement")
            != "actual_rust_source_dds_decode_events_v1"
            or source.get("full_source_decode_complete") is not True
        ):
            fail(f"{quality}_decode_measurement", "actual source decode proof is missing")
        if (
            copied_source_count < 0
            or unique_source_count < 0
            or copied_source_count > unique_source_count
        ):
            fail(
                f"{quality}_copied_dds",
                "copied/unique source counts are missing, negative, or inconsistent",
            )
        if (
            runtime.get("no_duplicate_upload_keys") is not True
            or _safe_int(runtime.get("duplicate_upload_key_count"), -1) != 0
        ):
            fail(f"{quality}_upload_dedup", "duplicate upload key")
        if (
            runtime.get("upload_key") != "dds_sha256"
            or runtime.get("role_specific_sampling_views_share_one_physical_upload")
            is not True
            or runtime.get("renderer_uploads_match_unique_binaries") is not True
            or _safe_int(runtime.get("resource_count"), -1) < 0
            or _safe_int(runtime.get("unique_binary_count"), -2)
            != _safe_int(runtime.get("resource_count"), -1)
            or _safe_int(runtime.get("logical_resource_count"), -1)
            < _safe_int(runtime.get("resource_count"), 0)
            or _safe_int(runtime.get("renderer_reported_upload_count"), -2)
            != _safe_int(runtime.get("resource_count"), -1)
        ):
            fail(
                f"{quality}_physical_upload_identity",
                "runtime DDS resources are not one physical upload per SHA-256 binary",
            )
        uploaded_resource_bytes = _safe_int(runtime.get("uploaded_resource_bytes"), -1)
        unique_binary_bytes = _safe_int(runtime.get("unique_binary_bytes"), -1)
        if (
            uploaded_resource_bytes < 0
            or unique_binary_bytes < 0
            or uploaded_resource_bytes != unique_binary_bytes
        ):
            fail(
                f"{quality}_texture_byte_dedup",
                "uploaded bytes differ from unique binary bytes",
            )
    if logical_edges < 0 or unique_dds_bytes < 0 or not batches or not regions:
        fail("worst_case_facts", "graph/resource/submesh/region evidence is incomplete")

    return (
        {
            "ordinal": _safe_int(manifest_row.get("ordinal"), -1),
            "asset_id": asset_id,
            "identity": identity,
            "canonical_rhett": identity.casefold() == RHETT_LOGICAL_PAC,
            "post_job_service_recycle_reason": service_recycle_reason,
            "metrics": {key: round(value, 3) for key, value in numeric.items()},
            "selection_facts": facts,
        },
        failures,
    )


def _metric_distributions(
    asset_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    names = sorted(
        {str(name) for row in asset_rows for name in _mapping(row.get("metrics"))}
    )
    return {
        name: _distribution(
            [_required_number(_mapping(row.get("metrics")), name) for row in asset_rows]
        )
        for name in names
    }


def _lifecycle_summary(
    asset_rows: Sequence[Mapping[str, object]],
    integrity_failures: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    reason_counts: dict[str, int] = {}
    for row in asset_rows:
        reason = str(row.get("post_job_service_recycle_reason", "") or "")
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    restart_failures = [
        row for row in integrity_failures if row.get("gate") == "process_restart"
    ]
    return {
        "unexpected_process_restart_count": len(restart_failures),
        "controlled_post_job_service_recycle_count": sum(reason_counts.values()),
        "controlled_post_job_service_recycle_reasons": dict(
            sorted(reason_counts.items())
        ),
        "note": (
            "Preview Core may intentionally stop its service after a completed job at "
            "documented job/cache/private-memory bounds. These are lifecycle events, "
            "not an in-job retry or renderer process restart."
        ),
    }


def _select_worst_cases(
    asset_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    selectors: tuple[tuple[str, str], ...] = (
        ("graph_edge_count", "graph_edge_count"),
        ("unique_dds_bytes", "unique_dds_bytes"),
        ("visible_submesh_count", "visible_submesh_count"),
        ("material_region_count", "material_region_count"),
        ("mixed_material_category_count", "mixed_material_category_count"),
    )
    result: dict[str, object] = {}
    for label, fact in selectors:
        candidates = [
            row
            for row in asset_rows
            if _safe_int(_mapping(row.get("selection_facts")).get(fact), -1) >= 0
        ]
        if not candidates:
            result[label] = {"status": "unavailable"}
            continue
        selected = min(
            candidates,
            key=lambda row: (
                -_safe_int(_mapping(row.get("selection_facts")).get(fact), -1),
                -_safe_int(
                    _mapping(row.get("selection_facts")).get("material_region_count"),
                    -1,
                )
                if fact == "visible_submesh_count"
                else -_safe_int(
                    _mapping(row.get("selection_facts")).get(
                        "metal_leather_cloth_category_count"
                    ),
                    -1,
                )
                if fact == "mixed_material_category_count"
                else 0,
                str(row.get("identity", "")).casefold(),
                _safe_int(row.get("ordinal"), 2**31 - 1),
            ),
        )
        result[label] = {
            "status": "selected",
            "ordinal": selected.get("ordinal"),
            "asset_id": selected.get("asset_id"),
            "identity": selected.get("identity"),
            "value": _safe_int(_mapping(selected.get("selection_facts")).get(fact), -1),
            "selection_facts": dict(_mapping(selected.get("selection_facts"))),
            "tie_break": (
                "highest visible submesh count, highest material region count, "
                "then normalized identity and ordinal"
                if fact == "visible_submesh_count"
                else (
                    "most distinct material categories, then most metal/leather/cloth "
                    "categories, then normalized identity and ordinal"
                )
                if fact == "mixed_material_category_count"
                else "highest metric then normalized identity and ordinal"
            ),
        }
    return result


def _repetition_targets(
    asset_rows: Sequence[Mapping[str, object]],
    worst_cases: Mapping[str, object],
) -> list[dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    rhett = next(
        (
            row
            for row in asset_rows
            if str(row.get("identity", "")).casefold() == RHETT_LOGICAL_PAC
        ),
        None,
    )
    if rhett is not None:
        selected[str(rhett.get("asset_id"))] = {
            "ordinal": rhett.get("ordinal"),
            "asset_id": rhett.get("asset_id"),
            "identity": rhett.get("identity"),
            "reasons": ["canonical_rhett"],
            "selection_facts": dict(_mapping(rhett.get("selection_facts"))),
        }
    for reason in (
        "graph_edge_count",
        "unique_dds_bytes",
        "visible_submesh_count",
        "material_region_count",
        "mixed_material_category_count",
    ):
        row = _mapping(worst_cases.get(reason))
        asset_id = str(row.get("asset_id", "") or "")
        if not asset_id:
            continue
        target = selected.setdefault(
            asset_id,
            {
                "ordinal": row.get("ordinal"),
                "asset_id": asset_id,
                "identity": row.get("identity"),
                "reasons": [],
                "selection_facts": dict(_mapping(row.get("selection_facts"))),
            },
        )
        reasons = target["reasons"]
        if isinstance(reasons, list) and reason not in reasons:
            reasons.append(reason)
    return sorted(
        selected.values(),
        key=lambda row: (
            0 if "canonical_rhett" in row["reasons"] else 1,
            _safe_int(row.get("ordinal"), 2**31 - 1),
            str(row.get("identity", "")).casefold(),
        ),
    )


def _compare_census_baseline(
    current_rows: Sequence[Mapping[str, object]], baseline_root: Path
) -> dict[str, object]:
    current_by_identity = {
        str(row.get("identity", "")).casefold(): row for row in current_rows
    }
    baseline_rows: list[dict[str, object]] = []
    for asset_root in sorted(
        (baseline_root / "assets").iterdir()
        if (baseline_root / "assets").is_dir()
        else baseline_root.iterdir(),
        key=lambda path: path.name.casefold(),
    ):
        if not asset_root.is_dir():
            continue
        report_path = asset_root / "asset-report.json"
        if not report_path.is_file():
            continue
        try:
            report = _read_json_object(report_path, label=f"baseline {asset_root.name}")
        except (OSError, EquipmentPerformanceError):
            continue
        identity = str(report.get("identity", "") or "").casefold()
        if not identity:
            continue
        metrics: dict[str, float] = {}
        value = _optional_number(report.get("wall_ms"))
        if value is not None:
            metrics["asset_wall_ms"] = value
        native_diagnostics = _mapping(
            _mapping(report.get("preview_core")).get("diagnostics")
        )
        for metric, key in (
            ("preview_core_process_private_bytes", "process_private_bytes"),
            ("preview_core_process_working_set_bytes", "process_working_set_bytes"),
        ):
            value = _optional_number(native_diagnostics.get(key))
            if value is not None:
                metrics[metric] = value
        performance = _mapping(report.get("performance"))
        if performance.get("schema") == EQUIPMENT_PERFORMANCE_SCHEMA:
            metrics.update(_performance_comparison_metrics(performance))
        private_values = [
            value
            for name in (
                "preview_core_process_private_bytes",
                "direct_peak_private_bytes",
                "full_peak_private_bytes",
            )
            if (value := _optional_number(metrics.get(name))) is not None
        ]
        if private_values:
            metrics["peak_private_bytes"] = max(private_values)
        for quality, filename in (
            ("direct", "before/audit-report.json"),
            ("full", "after/audit-report.json"),
        ):
            audit_path = asset_root / filename
            if not audit_path.is_file():
                continue
            try:
                audit = _read_json_object(audit_path, label=f"baseline {quality} audit")
            except (OSError, EquipmentPerformanceError):
                continue
            wall_ms = _optional_number(audit.get("wall_ms"))
            if wall_ms is not None:
                metrics[f"{quality}_renderer_wall_ms"] = wall_ms
        baseline_rows.append({"identity": identity, "metrics": metrics})

    baseline_by_identity: dict[str, dict[str, object]] = {}
    duplicate_baseline_identities: set[str] = set()
    for row in baseline_rows:
        identity = str(row["identity"])
        if identity in baseline_by_identity:
            duplicate_baseline_identities.add(identity)
            continue
        baseline_by_identity[identity] = row
    matched = [
        baseline_by_identity[identity]
        for identity in sorted(baseline_by_identity)
        if identity in current_by_identity
    ]
    metric_names = (
        "asset_wall_ms",
        "preview_core_elapsed_ms",
        "preview_core_wall_ms",
        "direct_package_build_ms",
        "full_package_build_ms",
        "direct_process_wall_ms",
        "full_process_wall_ms",
        "direct_renderer_wall_ms",
        "full_renderer_wall_ms",
        "direct_package_load_complete_ms",
        "full_package_load_complete_ms",
        "direct_renderer_device_ready_ms",
        "full_renderer_device_ready_ms",
        "direct_texture_resources_ready_ms",
        "full_texture_resources_ready_ms",
        "direct_first_textured_frame_ms",
        "full_first_textured_frame_ms",
        "direct_audit_completion_ms",
        "full_audit_completion_ms",
        "direct_process_boundary_overhead_ms",
        "full_process_boundary_overhead_ms",
        "direct_first_textured_frame_with_process_boundary_overhead_ms",
        "full_texture_resources_ready_with_process_boundary_overhead_ms",
        "direct_peak_private_bytes",
        "full_peak_private_bytes",
        "preview_core_process_private_bytes",
        "direct_peak_working_set_bytes",
        "full_peak_working_set_bytes",
        "preview_core_process_working_set_bytes",
        "direct_gpu_resident_bytes",
        "full_gpu_resident_bytes",
        "first_usable_ms",
        "full_texture_readiness_ms",
        "peak_private_bytes",
        "gpu_resident_bytes",
    )
    comparisons: dict[str, object] = {}
    for name in metric_names:
        pairs: list[tuple[float, float]] = []
        for baseline_row in matched:
            baseline_value = _optional_number(
                _mapping(baseline_row.get("metrics")).get(name)
            )
            current_value = _optional_number(
                _mapping(
                    current_by_identity[baseline_row["identity"]].get("metrics")
                ).get(name)
            )
            if baseline_value is not None and current_value is not None:
                pairs.append((baseline_value, current_value))
        comparison = _compare_metric_pairs(name, pairs)
        comparison["acceptance_required"] = (
            name not in _INFORMATIONAL_COMPARISON_METRICS
        )
        comparisons[name] = comparison
    failed = [
        name
        for name, row in comparisons.items()
        if _mapping(row).get("status") == "fail"
        and name not in _INFORMATIONAL_COMPARISON_METRICS
    ]
    missing = [
        name
        for name, row in comparisons.items()
        if _mapping(row).get("status") == "missing_baseline"
        and name not in _INFORMATIONAL_COMPARISON_METRICS
    ]
    duplicate_identities = sorted(duplicate_baseline_identities)
    coverage_complete = bool(
        len(matched) == len(current_rows)
        and current_rows
        and not duplicate_identities
    )
    if failed:
        status = "fail"
    elif missing or not coverage_complete:
        status = "incomplete"
    else:
        status = "pass"
    return {
        "status": status,
        "ok": status == "pass",
        "baseline_root": str(baseline_root),
        "baseline_asset_count": len(baseline_rows),
        "unique_baseline_asset_count": len(baseline_by_identity),
        "duplicate_baseline_identities": duplicate_identities,
        "matched_asset_count": len(matched),
        "unmatched_baseline_count": len(baseline_rows) - len(matched),
        "unmatched_unique_baseline_count": len(baseline_by_identity) - len(matched),
        "current_asset_count": len(current_rows),
        "full_census_coverage": coverage_complete,
        "metrics": comparisons,
        "failed_metrics": failed,
        "missing_baseline_metrics": missing,
        "limitations": (
            [
                message
                for condition, message in (
                    (
                        bool(missing),
                        (
                            "Pre-instrumentation reports omit build, process-memory, GPU, and "
                            "end-to-end first/full readiness fields; omitted fields are not passed."
                        ),
                    ),
                    (
                        len(matched) != len(current_rows) or not current_rows,
                        "The preserved baseline is a partial sample, not a full-census baseline.",
                    ),
                    (
                        bool(duplicate_identities),
                        "Duplicate logical identities in the preserved baseline are rejected and never weighted twice.",
                    ),
                )
                if condition
            ]
        ),
    }


def _validated_baseline_repetition_samples(
    baseline: Mapping[str, object],
    *,
    expected_targets: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Validate authoritative a48f00ce packets and normalize only for comparison."""

    schema = baseline.get("schema")
    if schema == A48F00CE_BASELINE_SAMPLES_SCHEMA:
        packets = [dict(baseline)]
        bundle_failures: list[dict[str, object]] = []
    elif schema == _BASELINE_PACKET_BUNDLE_SCHEMA:
        raw_packets = _sequence(baseline.get("packets"))
        packets = [dict(row) for row in raw_packets if isinstance(row, Mapping)]
        bundle_failures = []
        if set(baseline) != {"schema", "packets"} or len(packets) != len(
            raw_packets
        ):
            bundle_failures.append(
                {
                    "gate": "baseline_packet_bundle",
                    "detail": "baseline packet bundle is malformed or ambiguous",
                }
            )
        if not packets:
            bundle_failures.append(
                {
                    "gate": "baseline_packet_bundle",
                    "detail": "baseline packet bundle contains no raw evidence packets",
                }
            )
    else:
        raise EquipmentPerformanceError(
            "Baseline repetition evidence is not an authoritative a48f00ce packet."
        )

    samples: list[dict[str, object]] = []
    failures = list(bundle_failures)
    packet_targets: list[str] = []
    for packet_index, packet in enumerate(packets):
        packet_samples, target_id, packet_failures = _normalize_a48f00ce_packet(
            packet,
            expected_targets=expected_targets,
            verify_binary_files=packet_index == 0,
        )
        samples.extend(packet_samples)
        failures.extend(packet_failures)
        if target_id:
            packet_targets.append(target_id)

    duplicate_targets = sorted(
        target_id
        for target_id in set(packet_targets)
        if packet_targets.count(target_id) != 1
    )
    if duplicate_targets:
        failures.append(
            {
                "gate": "baseline_duplicate_target_packets",
                "detail": ", ".join(duplicate_targets),
            }
        )

    expected_identities = {
        str(row.get("asset_id", "")): str(row.get("identity", ""))
        for row in expected_targets
    }
    for target_id, identity in expected_identities.items():
        target_samples = [row for row in samples if row.get("asset_id") == target_id]
        if any(str(row.get("identity", "")) != identity for row in target_samples):
            failures.append(
                {
                    "asset_id": target_id,
                    "gate": "baseline_target_identity",
                    "detail": "baseline samples do not match the frozen target identity",
                }
            )
        for mode, expected_count in (
            ("cold", COLD_REPETITIONS),
            ("warm", WARM_REPETITIONS),
        ):
            rows = [row for row in target_samples if row.get("mode") == mode]
            ordinals = sorted(_safe_int(row.get("repetition"), -1) for row in rows)
            if len(rows) != expected_count or ordinals != list(
                range(1, expected_count + 1)
            ):
                failures.append(
                    {
                        "asset_id": target_id,
                        "gate": f"baseline_{mode}_coverage",
                        "detail": (
                            f"expected {expected_count} exact repetitions, "
                            f"found {len(rows)}"
                        ),
                    }
                )
    unexpected_targets = sorted(
        {
            str(row.get("asset_id", "") or "")
            for row in samples
            if str(row.get("asset_id", "") or "") not in expected_identities
        }
    )
    if unexpected_targets:
        failures.append(
            {
                "gate": "baseline_unexpected_targets",
                "detail": ", ".join(unexpected_targets),
            }
        )
    return samples, failures


def _normalize_a48f00ce_packet(
    packet: Mapping[str, object],
    *,
    expected_targets: Sequence[Mapping[str, object]],
    verify_binary_files: bool,
) -> tuple[list[dict[str, object]], str, list[dict[str, object]]]:
    failures: list[dict[str, object]] = []

    def fail(gate: str, detail: str, *, mode: str = "") -> None:
        row: dict[str, object] = {"gate": gate, "detail": detail}
        if target_id:
            row["asset_id"] = target_id
        if mode:
            row["mode"] = mode
        failures.append(row)

    target_id = ""
    required_packet_fields = {
        "schema",
        "baseline_provenance",
        "baseline_provenance_sha256",
        "cold_definition",
        "measurement_definitions",
        "metric_formulas",
        "report_integrity",
        "cold_samples",
        "input_manifest_sha256",
        "instrumented_rust_sha256",
        "output_policy",
        "target_identity",
        "warm_batch",
        "warm_definition",
        "warm_samples",
    }
    if set(packet) != required_packet_fields:
        fail(
            "baseline_packet_fields",
            "raw baseline packet is missing required fields or contains ambiguity",
        )
    if packet.get("schema") != A48F00CE_BASELINE_SAMPLES_SCHEMA:
        fail("baseline_packet_schema", "raw baseline packet schema is incompatible")

    provenance_failures, provenance_sha256 = _a48f00ce_provenance_failures(
        packet,
        verify_binary_files=verify_binary_files,
    )
    failures.extend(provenance_failures)
    packet_file_failure = _a48f00ce_packet_file_failure(packet)
    if packet_file_failure:
        fail("baseline_packet_file_identity", packet_file_failure)
    if (
        str(packet.get("instrumented_rust_sha256", "") or "").casefold()
        != _A48F00CE_INSTRUMENTED_RUST_SHA256
    ):
        fail(
            "baseline_instrumented_helper",
            "raw baseline packet is not bound to the audited instrumented helper",
        )
    if packet.get("cold_definition") != _A48F00CE_COLD_DEFINITION:
        fail("baseline_cold_definition", "cold measurement definition is incompatible")
    if packet.get("warm_definition") != _A48F00CE_WARM_DEFINITION:
        fail("baseline_warm_definition", "warm measurement definition is incompatible")
    if packet.get("output_policy") != _A48F00CE_OUTPUT_POLICY:
        fail("baseline_output_policy", "baseline output policy is incompatible")
    if packet.get("measurement_definitions") != _A48F00CE_MEMORY_DEFINITIONS:
        fail(
            "baseline_memory_definition",
            "paged-memory evidence is not explicitly identified as peak private commit",
        )
    if packet.get("metric_formulas") != _A48F00CE_METRIC_FORMULAS:
        fail("baseline_metric_formulas", "baseline metric formulas are incompatible")
    if packet.get("report_integrity") != _A48F00CE_REPORT_INTEGRITY:
        fail(
            "baseline_report_integrity",
            "hashed audit reports are not declared authoritative",
        )

    target = dict(_mapping(packet.get("target_identity")))
    if set(target) != {
        "dimensions",
        "fixed_full_model_views",
        "input_manifest_sha256",
        "process_generation",
        "renderer",
        "session_id",
        "source_path",
    }:
        fail(
            "baseline_target_identity",
            "raw baseline target identity is incomplete or ambiguous",
        )
    source_path = str(target.get("source_path", "") or "")
    source_identity = PurePosixPath(source_path).name
    matching_targets = [
        row
        for row in expected_targets
        if str(row.get("identity", "") or "").casefold()
        in {source_identity.casefold(), source_path.casefold()}
    ]
    if len(matching_targets) == 1:
        target_id = str(matching_targets[0].get("asset_id", "") or "")
        target_identity = str(matching_targets[0].get("identity", "") or "")
    else:
        target_identity = source_identity
        fail(
            "baseline_target_identity",
            "raw baseline source path does not identify exactly one frozen target",
        )
    target_manifest_sha256 = str(
        target.get("input_manifest_sha256", "") or ""
    ).casefold()
    if (
        not source_path
        or "\\" in source_path
        or PurePosixPath(source_path).is_absolute()
        or ".." in PurePosixPath(source_path).parts
        or not source_identity.casefold().endswith(".pac")
        or not _is_sha256(target_manifest_sha256)
        or str(packet.get("input_manifest_sha256", "") or "").casefold()
        != target_manifest_sha256
        or tuple(_sequence(target.get("dimensions"))) != (768, 768)
        or tuple(_sequence(target.get("fixed_full_model_views"))) != FULL_MODEL_VIEWS
        or _safe_int(target.get("process_generation"), -1) != 1
        or target.get("renderer") != "wgpu_d3d12_rust"
        or not str(target.get("session_id", "") or "")
    ):
        fail(
            "baseline_target_identity",
            "raw baseline target facts are missing or do not match the fixed audit",
        )
    target_manifest_failure = _a48f00ce_target_manifest_failure(packet, target)
    if target_manifest_failure:
        fail("baseline_target_manifest", target_manifest_failure)

    normalized: list[dict[str, object]] = []
    cold_raw = _sequence(packet.get("cold_samples"))
    cold_rows = [dict(row) for row in cold_raw if isinstance(row, Mapping)]
    expected_cold_ids = [f"cold-{index:02d}" for index in range(1, 8)]
    if (
        len(cold_rows) != COLD_REPETITIONS
        or len(cold_rows) != len(cold_raw)
        or [str(row.get("sample_id", "") or "") for row in cold_rows]
        != expected_cold_ids
    ):
        fail(
            "baseline_cold_coverage",
            "raw baseline must contain cold-01 through cold-07 exactly once in order",
            mode="cold",
        )
    report_paths: list[str] = []
    for repetition, row in enumerate(cold_rows, 1):
        metrics, row_failures = _a48f00ce_process_envelope(
            row,
            target=target,
            expected_sample_id=f"cold-{repetition:02d}",
            repetitions=1,
            warm=False,
            provenance_sha256=provenance_sha256,
            asset_id=target_id,
        )
        failures.extend(row_failures)
        report_paths.append(str(row.get("report_path", "") or "").casefold())
        if target_id:
            normalized.append(
                {
                    "asset_id": target_id,
                    "identity": target_identity,
                    "mode": "cold",
                    "repetition": repetition,
                    "first_usable_ms": metrics.get("first_usable_ms"),
                    "full_texture_readiness_ms": metrics.get(
                        "full_texture_readiness_ms"
                    ),
                    "peak_private_bytes": metrics.get("peak_private_bytes"),
                    "gpu_resident_bytes": metrics.get("gpu_resident_bytes"),
                }
            )
    if len(set(report_paths)) != len(report_paths) or "" in report_paths:
        fail(
            "baseline_cold_process_isolation",
            "each cold sample must bind a distinct hashed helper-process report",
            mode="cold",
        )

    warm_batch = dict(_mapping(packet.get("warm_batch")))
    warm_metrics, warm_batch_failures = _a48f00ce_process_envelope(
        warm_batch,
        target=target,
        expected_sample_id="warm-resident-20",
        repetitions=WARM_REPETITIONS,
        warm=True,
        provenance_sha256=provenance_sha256,
        asset_id=target_id,
    )
    failures.extend(warm_batch_failures)
    warm_raw = _sequence(packet.get("warm_samples"))
    warm_rows = [dict(row) for row in warm_raw if isinstance(row, Mapping)]
    expected_warm_ids = [f"warm-{index:02d}" for index in range(1, 21)]
    expected_indices = list(range(WARM_REPETITIONS))
    if (
        len(warm_rows) != WARM_REPETITIONS
        or len(warm_rows) != len(warm_raw)
        or [str(row.get("sample_id", "") or "") for row in warm_rows]
        != expected_warm_ids
        or [_safe_int(row.get("repetition_index"), -1) for row in warm_rows]
        != expected_indices
    ):
        fail(
            "baseline_warm_coverage",
            "raw baseline must contain warm-01 through warm-20 with exact indices",
            mode="warm",
        )
    batch_id = str(warm_batch.get("resident_batch_id", "") or "")
    generation = _safe_int(warm_batch.get("resident_process_generation"), -1)
    warm_walls: list[float] = []
    expected_warm_fields = {
        "sample_id",
        "baseline_provenance_sha256",
        "repetition_index",
        "wall_ms",
        "resident_batch_id",
        "resident_process_generation",
        "package_load_count",
        "package_reloads_between_repetitions",
        "renderer_batch_count",
        "renderer_device_count",
        "texture_upload_pass_count",
        "resource_reloads_between_repetitions",
    }
    for repetition, row in enumerate(warm_rows, 1):
        wall_ms = _optional_number(row.get("wall_ms"))
        require_ok = (
            set(row) == expected_warm_fields
            and str(row.get("baseline_provenance_sha256", "") or "").casefold()
            == provenance_sha256
            and _safe_int(row.get("repetition_index"), -1) == repetition - 1
            and wall_ms is not None
            and wall_ms > 0.0
            and str(row.get("resident_batch_id", "") or "") == batch_id
            and _safe_int(row.get("resident_process_generation"), -1) == generation
            and _safe_int(row.get("package_load_count"), -1) == 1
            and _safe_int(row.get("package_reloads_between_repetitions"), -1) == 0
            and _safe_int(row.get("renderer_batch_count"), -1) == 1
            and _safe_int(row.get("renderer_device_count"), -1) == 1
            and _safe_int(row.get("texture_upload_pass_count"), -1) == 1
            and _safe_int(row.get("resource_reloads_between_repetitions"), -1) == 0
        )
        if not require_ok:
            fail(
                "baseline_warm_residency",
                f"warm repetition {repetition} is incomplete or not resident",
                mode="warm",
            )
        if wall_ms is not None:
            warm_walls.append(wall_ms)
        if target_id:
            normalized.append(
                {
                    "asset_id": target_id,
                    "identity": target_identity,
                    "mode": "warm",
                    "repetition": repetition,
                    "warm_capture_ms": wall_ms,
                    "peak_private_bytes": warm_metrics.get("peak_private_bytes"),
                    "gpu_resident_bytes": warm_metrics.get("gpu_resident_bytes"),
                }
            )
    proof_walls = [
        value
        for raw in _sequence(
            _mapping(warm_batch.get("warm_cache_proof")).get(
                "per_repetition_wall_ms"
            )
        )
        if (value := _optional_number(raw)) is not None
    ]
    if warm_walls != proof_walls:
        fail(
            "baseline_warm_timing_binding",
            "warm sample timings do not exactly match the hashed resident report",
            mode="warm",
        )
    return normalized, target_id, failures


def _a48f00ce_process_envelope(
    row: Mapping[str, object],
    *,
    target: Mapping[str, object],
    expected_sample_id: str,
    repetitions: int,
    warm: bool,
    provenance_sha256: str,
    asset_id: str,
) -> tuple[dict[str, float], list[dict[str, object]]]:
    failures: list[dict[str, object]] = []
    mode = "warm" if warm else "cold"

    def fail(gate: str, detail: str) -> None:
        failure: dict[str, object] = {
            "gate": gate,
            "detail": detail,
            "mode": mode,
        }
        if asset_id:
            failure["asset_id"] = asset_id
        failures.append(failure)

    expected_fields = {
        "sample_id",
        "baseline_provenance_sha256",
        "execution_attestation",
        "repetition_count",
        "resident_batch_id",
        "resident_process_generation",
        "process_exit_code",
        "external_wall_ms",
        "observed_peak_working_set_bytes",
        "observed_peak_paged_memory_bytes",
        "observed_peak_virtual_memory_bytes",
        "memory_sampling_interval_ms",
        "phase_timings",
        "runtime_dds",
        "warm_cache_proof",
        "report_path",
        "report_sha256",
        "stderr",
        "stdout",
    }
    if set(row) != expected_fields:
        fail(
            "baseline_process_envelope",
            f"{expected_sample_id} process envelope is incomplete or ambiguous",
        )
    if (
        row.get("sample_id") != expected_sample_id
        or str(row.get("baseline_provenance_sha256", "") or "").casefold()
        != provenance_sha256
        or _safe_int(row.get("repetition_count"), -1) != repetitions
        or str(row.get("resident_batch_id", "") or "")
        != str(target.get("session_id", "") or "")
        or _safe_int(row.get("resident_process_generation"), -1)
        != _safe_int(target.get("process_generation"), -2)
        or _safe_int(row.get("process_exit_code"), -1) != 0
    ):
        fail(
            "baseline_process_identity",
            f"{expected_sample_id} is not bound to the expected successful process",
        )

    expected_attestation = {
        "adapter_backend": "Dx12",
        "adapter_device_type": "DiscreteGpu",
        "complete": True,
        "fallback_used": False,
        "process_restart_count": 0,
        "renderer": "wgpu_d3d12_rust",
        "report_schema": "cdmw_rust_material_audit_capture_v2",
        "timed_out": False,
    }
    if row.get("execution_attestation") != expected_attestation:
        fail(
            "baseline_execution_attestation",
            f"{expected_sample_id} lacks explicit D3D12/no-timeout/no-restart/no-fallback proof",
        )

    numeric: dict[str, float] = {}
    for field in (
        "external_wall_ms",
        "observed_peak_working_set_bytes",
        "observed_peak_paged_memory_bytes",
        "observed_peak_virtual_memory_bytes",
        "memory_sampling_interval_ms",
    ):
        value = _optional_number(row.get(field))
        if value is None or value <= 0.0:
            fail(
                "baseline_process_metrics",
                f"{expected_sample_id} {field} is missing or not positive",
            )
        else:
            numeric[field] = value
    try:
        phase = _validated_phase_timings(
            {"phase_timings": _mapping(row.get("phase_timings"))},
            label=f"a48f00ce {expected_sample_id}",
        )
    except EquipmentPerformanceError as exc:
        phase = {}
        fail("baseline_phase_timings", str(exc))
    if phase and any(value <= 0.0 for value in phase.values()):
        fail(
            "baseline_phase_timings",
            f"{expected_sample_id} phase timings must all be positive",
        )
    if (
        phase
        and "external_wall_ms" in numeric
        and numeric["external_wall_ms"] + 0.01 < phase["audit_completion_ms"]
    ):
        fail(
            "baseline_process_wall_envelope",
            f"{expected_sample_id} external wall does not contain audit completion",
        )
    runtime = _mapping(row.get("runtime_dds"))
    gpu_resident = _optional_number(runtime.get("reported_gpu_resident_bytes"))
    if gpu_resident is None or gpu_resident <= 0.0:
        fail(
            "baseline_gpu_resident_bytes",
            f"{expected_sample_id} GPU residency is missing or not positive",
        )

    proof = _mapping(row.get("warm_cache_proof"))
    proof_walls = _sequence(proof.get("per_repetition_wall_ms"))
    if not (
        proof.get("schema") == "cdmw_rust_warm_material_capture_v1"
        and proof.get("valid") is warm
        and _safe_int(proof.get("full_model_views_per_repetition"), -1) == 6
        and _safe_int(proof.get("package_load_count"), -1) == 1
        and _safe_int(proof.get("renderer_device_count"), -1) == 1
        and _safe_int(proof.get("renderer_batch_count"), -1) == 1
        and _safe_int(proof.get("texture_upload_pass_count"), -1) == 1
        and proof.get("dds_textures_uploaded_once_for_repetition_set") is True
        and _safe_int(proof.get("package_reloads_between_repetitions"), -1) == 0
        and _safe_int(proof.get("resource_reloads_between_repetitions"), -1) == 0
        and len(proof_walls) == repetitions
        and all(
            (value := _optional_number(raw)) is not None and value > 0.0
            for raw in proof_walls
        )
    ):
        fail(
            "baseline_warm_cache_proof" if warm else "baseline_cold_process_proof",
            f"{expected_sample_id} package/device/upload/reload proof is invalid",
        )

    report = _load_a48f00ce_report(row, expected_sample_id=expected_sample_id)
    if isinstance(report, str):
        fail("baseline_report_integrity", report)
    else:
        failures.extend(
            _a48f00ce_report_failures(
                report,
                envelope=row,
                target=target,
                repetitions=repetitions,
                expected_sample_id=expected_sample_id,
                warm=warm,
                asset_id=asset_id,
            )
        )

    metrics = {
        "peak_private_bytes": numeric.get("observed_peak_paged_memory_bytes", 0.0),
        "gpu_resident_bytes": gpu_resident or 0.0,
    }
    if not warm:
        metrics["first_usable_ms"] = phase.get("first_textured_frame_ms", 0.0)
        metrics["full_texture_readiness_ms"] = phase.get(
            "texture_resources_ready_ms", 0.0
        )
    return metrics, failures


def _load_a48f00ce_report(
    envelope: Mapping[str, object], *, expected_sample_id: str
) -> dict[str, object] | str:
    path_text = str(envelope.get("report_path", "") or "")
    expected_sha256 = str(envelope.get("report_sha256", "") or "").casefold()
    if not path_text or not _is_sha256(expected_sha256):
        return f"{expected_sample_id} report path or SHA-256 is missing"
    path = Path(path_text).expanduser()
    if not path.is_absolute() or path.name.casefold() != "audit-report.json":
        return f"{expected_sample_id} report path is not an absolute audit-report.json"
    try:
        resolved = path.resolve(strict=True)
        if resolved.parent.name.casefold() != expected_sample_id.casefold():
            return f"{expected_sample_id} report path is bound to another process envelope"
        if _sha256_file(resolved) != expected_sha256:
            return f"{expected_sample_id} report SHA-256 does not match"
        return _read_json_object(resolved, label=f"a48f00ce {expected_sample_id} report")
    except (OSError, RuntimeError, EquipmentPerformanceError) as exc:
        return f"{expected_sample_id} report is unavailable or invalid: {exc}"


def _a48f00ce_report_failures(
    report: Mapping[str, object],
    *,
    envelope: Mapping[str, object],
    target: Mapping[str, object],
    repetitions: int,
    expected_sample_id: str,
    warm: bool,
    asset_id: str,
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []

    def fail(gate: str, detail: str) -> None:
        row: dict[str, object] = {
            "gate": gate,
            "detail": detail,
            "mode": "warm" if warm else "cold",
        }
        if asset_id:
            row["asset_id"] = asset_id
        failures.append(row)

    adapter = _mapping(report.get("adapter"))
    process_memory = _mapping(report.get("process_memory"))
    captures = [_mapping(row) for row in _sequence(report.get("captures"))]
    if not (
        report.get("schema") == "cdmw_rust_material_audit_capture_v2"
        and report.get("renderer") == "wgpu_d3d12_rust"
        and str(adapter.get("backend", "") or "").casefold() == "dx12"
        and adapter.get("device_type") == "DiscreteGpu"
        and report.get("preview_package") is True
        and report.get("full_model_only") is True
        and _safe_int(report.get("source_lod_index"), -1) == 0
        and report.get("source_path") == target.get("source_path")
        and report.get("session_id") == target.get("session_id")
        and _safe_int(report.get("process_generation"), -1)
        == _safe_int(target.get("process_generation"), -2)
        and _safe_int(report.get("repetition_count"), -1) == repetitions
        and _safe_int(report.get("capture_count"), -1) == repetitions * 6
        and len(captures) == repetitions * 6
        and _safe_int(report.get("fixed_full_model_view_count"), -1) == 6
        and _safe_int(report.get("material_region_view_count"), -1) == 0
        and _safe_int(report.get("output_repetition_count"), -1) == 1
        and report.get("dds_resources_uploaded_once_for_capture_set") is True
        and process_memory.get("available") is False
        and process_memory.get("measurement") == "external_os_observer_required"
    ):
        fail(
            "baseline_hashed_report_contract",
            f"{expected_sample_id} hashed report does not match its target/D3D12 process",
        )
    if (
        _mapping(report.get("phase_timings"))
        != _mapping(envelope.get("phase_timings"))
        or _mapping(report.get("runtime_dds"))
        != _mapping(envelope.get("runtime_dds"))
        or _mapping(report.get("warm_cache_proof"))
        != _mapping(envelope.get("warm_cache_proof"))
    ):
        fail(
            "baseline_report_envelope_binding",
            f"{expected_sample_id} copied metrics differ from its hashed report",
        )
    for repetition_index in range(repetitions):
        repetition_captures = [
            capture
            for capture in captures
            if _safe_int(capture.get("repetition_index"), -1) == repetition_index
        ]
        if [str(capture.get("name", "") or "") for capture in repetition_captures] != list(
            FULL_MODEL_VIEWS
        ) or any(
            capture.get("capture_kind") != "full_model"
            or tuple(_sequence(capture.get("dimensions"))) != (768, 768)
            or (_optional_number(capture.get("wall_ms")) or 0.0) <= 0.0
            for capture in repetition_captures
        ):
            fail(
                "baseline_hashed_report_views",
                f"{expected_sample_id} does not contain six fixed 768x768 views per repetition",
            )
            break
    attestation = _mapping(envelope.get("execution_attestation"))
    if not (
        attestation.get("report_schema") == report.get("schema")
        and attestation.get("renderer") == report.get("renderer")
        and str(attestation.get("adapter_backend", "") or "").casefold()
        == str(adapter.get("backend", "") or "").casefold()
        and attestation.get("adapter_device_type") == adapter.get("device_type")
    ):
        fail(
            "baseline_execution_report_binding",
            f"{expected_sample_id} execution attestation differs from its hashed report",
        )
    return failures


def _a48f00ce_provenance_failures(
    baseline: Mapping[str, object],
    *,
    verify_binary_files: bool,
) -> tuple[list[dict[str, object]], str]:
    failures: list[dict[str, object]] = []

    def fail(gate: str, detail: str) -> None:
        failures.append({"gate": gate, "detail": detail})

    provenance = dict(_mapping(baseline.get("baseline_provenance")))
    expected_provenance_fields = {
        "schema",
        "base_revision",
        "base_short_revision",
        "base_tree_clean",
        "instrumentation",
        "capture_binaries",
        "source_tree_sha256",
    }
    if set(provenance) != expected_provenance_fields:
        fail(
            "baseline_provenance",
            "baseline provenance is missing required fields or contains ambiguity",
        )
    provenance_sha256 = _canonical_json_sha256(provenance) if provenance else ""
    if (
        provenance_sha256 != _A48F00CE_BASELINE_PROVENANCE_SHA256
        or str(baseline.get("baseline_provenance_sha256", "") or "").casefold()
        != provenance_sha256
    ):
        fail(
            "baseline_provenance_binding",
            "baseline provenance canonical SHA-256 is missing or mismatched",
        )
    if (
        provenance.get("schema")
        != EQUIPMENT_PERFORMANCE_BASELINE_PROVENANCE_SCHEMA
    ):
        fail("baseline_provenance_schema", "baseline provenance schema is incompatible")
    if provenance.get("base_revision") != _A48F00CE_BASE_REVISION:
        fail("baseline_base_revision", "baseline is not pinned to exact a48f00ce")
    if provenance.get("base_short_revision") != _A48F00CE_BASE_SHORT_REVISION:
        fail(
            "baseline_base_short_revision",
            "baseline short revision does not match its exact base revision",
        )
    if provenance.get("base_tree_clean") is not True:
        fail(
            "baseline_base_tree_clean",
            "baseline did not prove a clean base tree before instrumentation",
        )
    source_tree_sha256 = str(
        provenance.get("source_tree_sha256", "") or ""
    ).casefold()
    if source_tree_sha256 != _A48F00CE_SOURCE_TREE_SHA256:
        fail(
            "baseline_source_tree_identity",
            "baseline clean source-tree SHA-256 is not the audited a48f00ce tree",
        )

    instrumentation = dict(_mapping(provenance.get("instrumentation")))
    patch_sha256 = str(instrumentation.get("patch_sha256", "") or "").casefold()
    if (
        set(instrumentation)
        != {"purpose", "schema", "patch_sha256", "modified_paths"}
        or instrumentation.get("schema")
        != EQUIPMENT_PERFORMANCE_BASELINE_INSTRUMENTATION_SCHEMA
        or instrumentation.get("purpose") != _A48F00CE_INSTRUMENTATION_PURPOSE
        or tuple(_sequence(instrumentation.get("modified_paths")))
        != _A48F00CE_INSTRUMENTATION_MODIFIED_PATHS
        or patch_sha256 != _A48F00CE_INSTRUMENTATION_PATCH_SHA256
    ):
        fail(
            "baseline_instrumentation_identity",
            "baseline measurement-only instrumentation is not the audited patch",
        )

    provenance_binaries = _mapping(provenance.get("capture_binaries"))
    expected_binaries = {
        "uninstrumented_rust": (
            "cdmw_mesh_lab.exe",
            _A48F00CE_UNINSTRUMENTED_RUST_BYTES,
            _A48F00CE_UNINSTRUMENTED_RUST_SHA256,
            "uninstrumented",
        ),
        "uninstrumented_preview_core": (
            "cdmw-preview-core.exe",
            _A48F00CE_UNINSTRUMENTED_PREVIEW_CORE_BYTES,
            _A48F00CE_UNINSTRUMENTED_PREVIEW_CORE_SHA256,
            "uninstrumented",
        ),
        "instrumented_rust": (
            "cdmw_mesh_lab.exe",
            _A48F00CE_INSTRUMENTED_RUST_BYTES,
            _A48F00CE_INSTRUMENTED_RUST_SHA256,
            "instrumented",
        ),
    }
    if set(provenance_binaries) != set(expected_binaries):
        fail(
            "baseline_binary_provenance",
            "baseline binary provenance does not name the exact three binaries",
        )
    for name, (filename, size, sha256, kind) in expected_binaries.items():
        row = dict(_mapping(provenance_binaries.get(name)))
        path = str(row.get("path", "") or "")
        if (
            set(row) != {"path", "bytes", "sha256", "kind"}
            or not path
            or Path(path).name.casefold() != filename.casefold()
            or _safe_int(row.get("bytes"), -1) != size
            or str(row.get("sha256", "") or "").casefold() != sha256
            or row.get("kind") != kind
        ):
            fail(
                "baseline_binary_provenance",
                f"baseline {name} identity does not match the audited binary",
            )
        elif verify_binary_files and not _baseline_binary_file_matches(
            row, expected_bytes=size, expected_sha256=sha256
        ):
            fail(
                "baseline_binary_file_identity",
                f"baseline {name} file is missing or differs from its audited hash",
            )
    if verify_binary_files:
        provenance_file_failure = _a48f00ce_provenance_file_failure(provenance)
        if provenance_file_failure:
            fail("baseline_provenance_files", provenance_file_failure)
    return failures, provenance_sha256


def _baseline_binary_file_matches(
    row: Mapping[str, object], *, expected_bytes: int, expected_sha256: str
) -> bool:
    try:
        path = Path(str(row.get("path", "") or "")).expanduser().resolve(strict=True)
        return (
            path.is_file()
            and path.stat().st_size == expected_bytes
            and _sha256_file(path) == expected_sha256
        )
    except (OSError, RuntimeError):
        return False


def _a48f00ce_provenance_file_failure(provenance: Mapping[str, object]) -> str:
    binaries = _mapping(provenance.get("capture_binaries"))
    instrumented_path_text = str(
        _mapping(binaries.get("instrumented_rust")).get("path", "") or ""
    )
    try:
        instrumented_path = Path(instrumented_path_text).expanduser().resolve(strict=True)
        provenance_root = (instrumented_path.parent / "provenance").resolve(strict=True)
        tree_path = (provenance_root / "base-source-tree.ls-tree").resolve(strict=True)
        patch_path = (
            provenance_root / "measurement-instrumentation.patch"
        ).resolve(strict=True)
        provenance_path = (
            provenance_root / "baseline-provenance.json"
        ).resolve(strict=True)
        checksum_path = (
            provenance_root / "baseline-provenance.sha256"
        ).resolve(strict=True)
        if (
            _sha256_file(tree_path) != _A48F00CE_SOURCE_TREE_SHA256
            or _sha256_file(patch_path) != _A48F00CE_INSTRUMENTATION_PATCH_SHA256
        ):
            return "retained clean tree or instrumentation patch has changed"
        retained_provenance = _read_json_object(
            provenance_path,
            label="a48f00ce retained baseline provenance",
        )
        if (
            retained_provenance != provenance
            or _canonical_json_sha256(retained_provenance)
            != _A48F00CE_BASELINE_PROVENANCE_SHA256
        ):
            return "retained provenance JSON differs from the bound canonical object"
        checksum_text = checksum_path.read_text(encoding="utf-8").strip()
        if checksum_text != (
            f"{_A48F00CE_BASELINE_PROVENANCE_SHA256}  "
            "baseline-provenance.canonical-json"
        ):
            return "retained canonical provenance checksum is missing or changed"
    except (OSError, RuntimeError, UnicodeError, EquipmentPerformanceError) as exc:
        return f"retained source/instrumentation provenance is unavailable: {exc}"
    return ""


def _a48f00ce_target_manifest_failure(
    packet: Mapping[str, object], target: Mapping[str, object]
) -> str:
    provenance_binaries = _mapping(
        _mapping(packet.get("baseline_provenance")).get("capture_binaries")
    )
    instrumented_path_text = str(
        _mapping(provenance_binaries.get("instrumented_rust")).get("path", "") or ""
    )
    target_sha256 = str(target.get("input_manifest_sha256", "") or "").casefold()
    try:
        instrumented_path = Path(instrumented_path_text).expanduser().resolve(strict=True)
        evidence_root = instrumented_path.parents[2]
        hashes_path = (
            instrumented_path.parent / "provenance" / "artifact-hashes.sha256"
        ).resolve(strict=True)
        if (
            hashes_path.stat().st_size > 64 * 1024
            or _sha256_file(hashes_path)
            != _A48F00CE_ARTIFACT_HASH_MANIFEST_SHA256
        ):
            return "audited artifact-hash manifest is missing or has changed"
        lines = hashes_path.read_text(encoding="utf-8").splitlines()
        matching = [
            line.split("  ", 1)[1]
            for line in lines
            if line.startswith(f"{target_sha256}  ") and "  " in line
        ]
        if len(matching) != 1:
            return "target input SHA-256 is not uniquely bound by artifact-hashes.sha256"
        relative = PurePosixPath(matching[0])
        if relative.is_absolute() or ".." in relative.parts:
            return "target input path in artifact-hashes.sha256 is unsafe"
        manifest_path = (
            evidence_root / Path(*relative.parts)
        ).resolve(strict=True)
        if not manifest_path.is_relative_to(evidence_root) or not manifest_path.is_file():
            return "target input manifest escapes the retained evidence root"
        if _sha256_file(manifest_path) != target_sha256:
            return "retained target input manifest SHA-256 does not match"
        manifest = _read_json_object(
            manifest_path,
            label="a48f00ce target input manifest",
        )
    except (OSError, RuntimeError, UnicodeError, EquipmentPerformanceError) as exc:
        return f"retained target input manifest is unavailable or invalid: {exc}"
    if not (
        manifest.get("schema") == "cdmw_rust_preview_package_v1"
        and manifest.get("renderer") == "wgpu_d3d12_rust"
        and _mapping(manifest.get("source")).get("path") == target.get("source_path")
    ):
        return "retained target input manifest does not match the packet source identity"
    return ""


def _a48f00ce_packet_file_failure(packet: Mapping[str, object]) -> str:
    cold_rows = _mapping_rows(packet, "cold_samples")
    report_path_text = (
        str(cold_rows[0].get("report_path", "") or "") if cold_rows else ""
    )
    provenance_binaries = _mapping(
        _mapping(packet.get("baseline_provenance")).get("capture_binaries")
    )
    instrumented_path_text = str(
        _mapping(provenance_binaries.get("instrumented_rust")).get("path", "") or ""
    )
    try:
        report_path = Path(report_path_text).expanduser().resolve(strict=True)
        packet_path = (report_path.parent.parent / "baseline-samples.json").resolve(
            strict=True
        )
        retained_packet = _read_json_object(
            packet_path,
            label="retained a48f00ce baseline packet",
        )
        if retained_packet != packet:
            return "in-memory baseline packet differs from retained baseline-samples.json"
        packet_sha256 = _sha256_file(packet_path)
        instrumented_path = Path(instrumented_path_text).expanduser().resolve(strict=True)
        evidence_root = instrumented_path.parents[2]
        if not packet_path.is_relative_to(evidence_root):
            return "retained baseline packet escapes the audited evidence root"
        hashes_path = (
            instrumented_path.parent / "provenance" / "artifact-hashes.sha256"
        ).resolve(strict=True)
        if (
            _sha256_file(hashes_path)
            != _A48F00CE_ARTIFACT_HASH_MANIFEST_SHA256
        ):
            return "audited artifact-hash manifest is missing or has changed"
        relative = packet_path.relative_to(evidence_root).as_posix()
        expected_line = f"{packet_sha256}  {relative}"
        lines = hashes_path.read_text(encoding="utf-8").splitlines()
        if lines.count(expected_line) != 1:
            return "retained baseline packet is not uniquely hash-bound by artifact-hashes.sha256"
    except (OSError, RuntimeError, UnicodeError, EquipmentPerformanceError) as exc:
        return f"retained baseline packet is unavailable or invalid: {exc}"
    return ""


def _compare_repetition_samples(
    current: Sequence[Mapping[str, object]],
    baseline: Sequence[Mapping[str, object]],
    target_ids: Sequence[str],
) -> dict[str, object]:
    result: dict[str, object] = {}
    failed: list[str] = []
    missing: list[str] = []
    for target_id in target_ids:
        target_result: dict[str, object] = {}
        for metric, mode in (
            ("first_usable_ms", "cold"),
            ("full_texture_readiness_ms", "cold"),
            ("warm_capture_ms", "warm"),
            ("peak_private_bytes", None),
            ("gpu_resident_bytes", None),
        ):
            baseline_mode_rows = [
                row
                for row in baseline
                if row.get("asset_id") == target_id
                and (mode is None or row.get("mode") == mode)
            ]
            current_values = [
                value
                for row in current
                if row.get("asset_id") == target_id
                and (mode is None or row.get("mode") == mode)
                if (value := _optional_number(row.get(metric))) is not None
            ]
            baseline_values = [
                value
                for row in baseline_mode_rows
                if (value := _optional_number(row.get(metric))) is not None
            ]
            expected_count = (
                COLD_REPETITIONS + WARM_REPETITIONS
                if mode is None
                else COLD_REPETITIONS
                if mode == "cold"
                else WARM_REPETITIONS
            )
            baseline_ordinals = sorted(
                _safe_int(row.get("repetition"), -1) for row in baseline_mode_rows
            )
            exact_ordinals = mode is None or baseline_ordinals == list(
                range(1, expected_count + 1)
            )
            if len(baseline_values) != expected_count or not exact_ordinals:
                comparison = {
                    "status": "missing_baseline",
                    "ok": False,
                    "matched_sample_count": min(
                        len(baseline_values), len(current_values)
                    ),
                    "expected_baseline_sample_count": expected_count,
                    "reason": (
                        "Baseline repetition evidence does not contain the exact "
                        f"{expected_count} {mode or 'cold/warm'} samples."
                    ),
                }
            else:
                comparison = _compare_metric_distributions(
                    metric, baseline_values, current_values
                )
            target_result[metric] = comparison
            key = f"{target_id}:{metric}"
            if comparison["status"] == "fail":
                failed.append(key)
            elif comparison["status"] != "pass":
                missing.append(key)
        result[target_id] = target_result
    status = "fail" if failed else "incomplete" if missing else "pass"
    return {
        "status": status,
        "ok": status == "pass",
        "targets": result,
        "failed_metrics": failed,
        "missing_metrics": missing,
    }


def _sample_failures(
    row: Mapping[str, object], *, target_id: str, mode: str
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []

    def require(condition: bool, gate: str, detail: str) -> None:
        if not condition:
            failures.append(
                {"asset_id": target_id, "mode": mode, "gate": gate, "detail": detail}
            )

    require(
        row.get("renderer_path") == PRODUCTION_RENDERER_PATH,
        "production_path",
        "wrong path",
    )
    require(
        _safe_int(row.get("preview_core_schema_version"), -1)
        == CURRENT_PREVIEW_CORE_SCHEMA_VERSION,
        "preview_core_schema",
        "current repetition sample is not Preview Core schema 8",
    )
    require(
        _safe_int(row.get("material_graph_version"), -1)
        == CURRENT_MATERIAL_GRAPH_VERSION,
        "material_graph_version",
        "current repetition sample is not material graph v4",
    )
    require(
        _safe_int(row.get("material_semantics_version"), -1)
        == CURRENT_MATERIAL_SEMANTICS_VERSION,
        "material_semantics_version",
        "current repetition sample is not material semantics v10",
    )
    require(row.get("renderer") == "wgpu_d3d12_rust", "renderer", "wrong renderer")
    require(
        str(row.get("adapter_backend", "")).casefold() == "dx12",
        "adapter_backend",
        "not D3D12",
    )
    require(
        row.get("python_material_synthesis_used") is False,
        "python_material_synthesis",
        "must be false",
    )
    require(row.get("timed_out") is False, "timeout", "timeout or missing flag")
    require(
        _safe_int(row.get("process_restart_count"), -1) == 0,
        "process_restart",
        "nonzero or missing",
    )
    require(
        row.get("renderer_fallback") is False,
        "renderer_fallback",
        "fallback or missing flag",
    )
    require(
        _safe_int(row.get("duplicate_upload_key_count"), -1) == 0,
        "duplicate_upload_key",
        "nonzero or missing",
    )
    require(
        _safe_int(row.get("duplicate_parameter_texture_bytes"), -1) == 0,
        "duplicate_parameter_texture_bytes",
        "nonzero or missing",
    )
    require(
        row.get("physical_upload_identity") == "dds_sha256"
        and row.get("one_physical_upload_per_binary") is True,
        "physical_upload_identity",
        "runtime uploads are not uniquely keyed by DDS SHA-256",
    )
    if mode == "warm":
        require(
            _safe_int(row.get("package_reload_count"), -1) == 0,
            "warm_package_reload",
            "nonzero or missing",
        )
        require(
            _safe_int(row.get("resource_reload_count"), -1) == 0,
            "warm_resource_reload",
            "nonzero or missing",
        )
        require(
            _safe_int(row.get("resident_package_load_count"), -1) == 1,
            "warm_package_load_count",
            "resident warm run must load the package exactly once",
        )
        require(
            _safe_int(row.get("resident_renderer_device_count"), -1) == 1,
            "warm_renderer_device_count",
            "resident warm run must create exactly one renderer device",
        )
        require(
            _safe_int(row.get("resident_renderer_batch_count"), -1) == 1,
            "warm_renderer_batch_count",
            "resident warm run must use exactly one renderer batch",
        )
        require(
            _safe_int(row.get("resident_texture_upload_pass_count"), -1) == 1,
            "warm_texture_upload_count",
            "resident warm run must upload texture resources exactly once",
        )
        try:
            _validated_phase_timings(
                {"phase_timings": _mapping(row.get("resident_phase_timings"))},
                label="resident warm sample",
            )
        except EquipmentPerformanceError as exc:
            require(False, "warm_phase_timings", str(exc))
    else:
        require(
            row.get("native_service_used") is False,
            "cold_fresh_preview_core_process",
            "cold sample must disable the resident Preview Core service",
        )
        require(
            row.get("native_cache_started_empty") is True,
            "cold_empty_cache",
            "cold sample must start with an isolated empty cache",
        )
        require(
            row.get("timing_basis") == "explicit_rust_phase_milestones_v1",
            "cold_timing_basis",
            "cold timing must use explicit Rust milestones",
        )
        try:
            direct_phase = _validated_phase_timings(
                {"phase_timings": _mapping(row.get("direct_phase_timings"))},
                label="cold direct sample",
            )
            full_phase = _validated_phase_timings(
                {"phase_timings": _mapping(row.get("full_phase_timings"))},
                label="cold full sample",
            )
        except EquipmentPerformanceError as exc:
            direct_phase = None
            full_phase = None
            require(False, "cold_phase_timings", str(exc))
        timing_parts = {
            key: _optional_number(row.get(key))
            for key in (
                "preview_core_wall_ms",
                "direct_package_build_ms",
                "full_package_build_ms",
                "direct_process_boundary_overhead_ms",
                "full_process_boundary_overhead_ms",
                "direct_first_textured_frame_with_process_boundary_overhead_ms",
                "full_texture_resources_ready_with_process_boundary_overhead_ms",
                "direct_audit_completion_wall_ms",
                "full_audit_completion_wall_ms",
            )
        }
        require(
            all(value is not None for value in timing_parts.values()),
            "cold_timing_components",
            "cold timing components are missing or non-finite",
        )
        if (
            direct_phase is not None
            and full_phase is not None
            and all(value is not None for value in timing_parts.values())
        ):
            direct_audit_wall = float(timing_parts["direct_audit_completion_wall_ms"])
            full_audit_wall = float(timing_parts["full_audit_completion_wall_ms"])
            direct_boundary_overhead = max(
                0.0, direct_audit_wall - direct_phase["audit_completion_ms"]
            )
            full_boundary_overhead = max(
                0.0, full_audit_wall - full_phase["audit_completion_ms"]
            )
            direct_with_boundary = (
                direct_boundary_overhead + direct_phase["first_textured_frame_ms"]
            )
            full_with_boundary = (
                full_boundary_overhead + full_phase["texture_resources_ready_ms"]
            )
            require(
                abs(
                    float(timing_parts["direct_process_boundary_overhead_ms"])
                    - direct_boundary_overhead
                )
                <= 0.01
                and abs(
                    float(timing_parts["full_process_boundary_overhead_ms"])
                    - full_boundary_overhead
                )
                <= 0.01,
                "cold_process_boundary_overhead",
                "process boundary overhead does not match process wall minus audit completion",
            )
            require(
                abs(
                    float(
                        timing_parts[
                            "direct_first_textured_frame_with_process_boundary_overhead_ms"
                        ]
                    )
                    - direct_with_boundary
                )
                <= 0.01,
                "cold_direct_phase_formula",
                "direct first-frame timing does not match the explicit phase milestone",
            )
            require(
                abs(
                    float(
                        timing_parts[
                            "full_texture_resources_ready_with_process_boundary_overhead_ms"
                        ]
                    )
                    - full_with_boundary
                )
                <= 0.01,
                "cold_full_phase_formula",
                "full resource timing does not match the explicit phase milestone",
            )
            native = float(timing_parts["preview_core_wall_ms"])
            direct_build = float(timing_parts["direct_package_build_ms"])
            full_build = float(timing_parts["full_package_build_ms"])
            expected_first = native + direct_build + direct_with_boundary
            expected_full = native + direct_build + full_build + full_with_boundary
            actual_first = _optional_number(row.get("first_usable_ms"))
            actual_full = _optional_number(row.get("full_texture_readiness_ms"))
            require(
                actual_first is not None and abs(actual_first - expected_first) <= 0.01,
                "cold_first_usable_formula",
                "first usable includes something other than the direct first-frame path",
            )
            require(
                actual_full is not None and abs(actual_full - expected_full) <= 0.01,
                "cold_full_readiness_formula",
                "full readiness does not match the sequential direct/full package path",
            )
    required_metrics = (
        ("warm_capture_ms", "peak_private_bytes", "gpu_resident_bytes")
        if mode == "warm"
        else (
            "first_usable_ms",
            "full_texture_readiness_ms",
            "peak_private_bytes",
            "gpu_resident_bytes",
        )
    )
    for metric in required_metrics:
        value = _optional_number(row.get(metric))
        require(
            value is not None
            and (metric not in {"peak_private_bytes"} or value > 0.0),
            metric,
            "missing, non-finite, negative, or not a positive private-memory sample",
        )
    return failures


def _performance_comparison_metrics(
    performance: Mapping[str, object],
) -> dict[str, float]:
    preview = _mapping(performance.get("preview_core"))
    package = _mapping(performance.get("package_build"))
    render = _mapping(performance.get("render"))
    direct = _mapping(render.get("direct"))
    full = _mapping(render.get("full"))
    resources = _mapping(performance.get("resources"))
    direct_runtime = _mapping(resources.get("direct_runtime_dds"))
    full_runtime = _mapping(resources.get("full_runtime_dds"))
    field_sources = {
        "preview_core_elapsed_ms": (preview, "elapsed_ms"),
        "preview_core_wall_ms": (preview, "wall_ms"),
        "direct_package_build_ms": (package, "direct_ms"),
        "full_package_build_ms": (package, "full_ms"),
        "direct_process_wall_ms": (direct, "process_wall_ms"),
        "full_process_wall_ms": (full, "process_wall_ms"),
        "direct_renderer_wall_ms": (direct, "renderer_wall_ms"),
        "full_renderer_wall_ms": (full, "renderer_wall_ms"),
        "direct_peak_private_bytes": (direct, "peak_private_bytes"),
        "full_peak_private_bytes": (full, "peak_private_bytes"),
        "direct_peak_working_set_bytes": (direct, "peak_working_set_bytes"),
        "full_peak_working_set_bytes": (full, "peak_working_set_bytes"),
        "direct_gpu_resident_bytes": (direct_runtime, "reported_gpu_resident_bytes"),
        "full_gpu_resident_bytes": (full_runtime, "reported_gpu_resident_bytes"),
    }
    values = {
        name: value
        for name, (source, key) in field_sources.items()
        if (value := _optional_number(source.get(key))) is not None
    }
    direct_phase = _optional_validated_phase_timings(
        direct, label="baseline direct Rust audit"
    )
    full_phase = _optional_validated_phase_timings(full, label="baseline full Rust audit")
    for quality, phase in (("direct", direct_phase), ("full", full_phase)):
        if phase is None:
            continue
        for field, value in phase.items():
            values[f"{quality}_{field}"] = value
    preview_wall = _optional_number(preview.get("wall_ms"))
    direct_build = _optional_number(package.get("direct_ms"))
    full_build = _optional_number(package.get("full_ms"))
    if direct_phase is not None and _optional_number(direct.get("process_wall_ms")) is not None:
        values["direct_process_boundary_overhead_ms"] = (
            _process_boundary_overhead_ms(direct, direct_phase)
        )
        direct_first = _parent_observed_phase_ms(
            direct, direct_phase, "first_textured_frame_ms"
        )
        values[
            "direct_first_textured_frame_with_process_boundary_overhead_ms"
        ] = direct_first
        if None not in (preview_wall, direct_build):
            values["first_usable_ms"] = preview_wall + direct_build + direct_first  # type: ignore[operator]
    if full_phase is not None and _optional_number(full.get("process_wall_ms")) is not None:
        values["full_process_boundary_overhead_ms"] = _process_boundary_overhead_ms(
            full, full_phase
        )
        full_resources = _parent_observed_phase_ms(
            full, full_phase, "texture_resources_ready_ms"
        )
        values[
            "full_texture_resources_ready_with_process_boundary_overhead_ms"
        ] = full_resources
        if None not in (preview_wall, direct_build, full_build):
            values["full_texture_readiness_ms"] = (  # type: ignore[operator]
                preview_wall + direct_build + full_build + full_resources
            )
    private_values = [
        value
        for value in (
            _optional_number(direct.get("peak_private_bytes")),
            _optional_number(full.get("peak_private_bytes")),
        )
        if value is not None
    ]
    gpu_values = [
        value
        for value in (
            _optional_number(direct_runtime.get("reported_gpu_resident_bytes")),
            _optional_number(full_runtime.get("reported_gpu_resident_bytes")),
        )
        if value is not None
    ]
    if private_values:
        values["peak_private_bytes"] = max(private_values)
    if gpu_values:
        values["gpu_resident_bytes"] = max(gpu_values)
    return values


def _compare_metric_pairs(
    name: str, pairs: Sequence[tuple[float, float]]
) -> dict[str, object]:
    if not pairs:
        return {
            "status": "missing_baseline",
            "ok": False,
            "matched_sample_count": 0,
            "reason": "No matched reports contain both baseline and current values.",
        }
    return _compare_metric_distributions(
        name,
        [pair[0] for pair in pairs],
        [pair[1] for pair in pairs],
    )


def _compare_metric_distributions(
    name: str, baseline_values: Sequence[float], current_values: Sequence[float]
) -> dict[str, object]:
    if not baseline_values or not current_values:
        return {
            "status": "missing_baseline",
            "ok": False,
            "matched_sample_count": min(len(baseline_values), len(current_values)),
            "reason": "Baseline or current samples are missing.",
        }
    baseline = _distribution(baseline_values)
    current = _distribution(current_values)
    if name in _MEMORY_METRICS:
        baseline_value = float(baseline["max"])
        current_value = float(current["max"])
        allowance = baseline_value * 0.05
        allowed = baseline_value + allowance
        gate = {
            "statistic": "max",
            "baseline": baseline_value,
            "current": current_value,
            "allowance": round(allowance, 3),
            "allowed_max": round(allowed, 3),
            "ok": current_value <= allowed,
        }
        ok = bool(gate["ok"])
        gates = [gate]
    else:
        absolute = _TIMING_THRESHOLDS_MS.get(name, 5.0)
        gates = []
        for statistic in ("median", "p95"):
            baseline_value = float(baseline[statistic])
            current_value = float(current[statistic])
            allowance = max(baseline_value * 0.05, absolute)
            allowed = baseline_value + allowance
            gates.append(
                {
                    "statistic": statistic,
                    "baseline": baseline_value,
                    "current": current_value,
                    "allowance": round(allowance, 3),
                    "allowed_max": round(allowed, 3),
                    "ok": current_value <= allowed,
                }
            )
        ok = all(bool(gate["ok"]) for gate in gates)
    return {
        "status": "pass" if ok else "fail",
        "ok": ok,
        "matched_sample_count": min(len(baseline_values), len(current_values)),
        "baseline": baseline,
        "current": current,
        "gates": gates,
        "threshold_rule": (
            "current <= baseline + 5%"
            if name in _MEMORY_METRICS
            else f"current <= baseline + max(5%, {_TIMING_THRESHOLDS_MS.get(name, 5.0):g} ms)"
        ),
    }


def _distribution(values: Sequence[float]) -> dict[str, object]:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p95": None,
            "max": None,
            "mean": None,
        }
    p95_index = min(len(finite) - 1, max(0, math.ceil(len(finite) * 0.95) - 1))
    return {
        "count": len(finite),
        "min": round(finite[0], 3),
        "median": round(statistics.median(finite), 3),
        "p95": round(finite[p95_index], 3),
        "max": round(finite[-1], 3),
        "mean": round(statistics.fmean(finite), 3),
    }


def _metric_definitions() -> dict[str, object]:
    return {
        "first_usable_ms": (
            "preview_core wall + direct package build + conservative process-boundary "
            "overhead + Rust first_textured_frame milestone"
        ),
        "full_texture_readiness_ms": (
            "preview_core wall + direct package build + full package build + parent "
            "process-boundary overhead + full Rust texture_resources_ready milestone; "
            "production builds direct then full but does not wait for the direct "
            "renderer frame"
        ),
        "process_boundary_overhead_ms": (
            "parent process wall minus Rust audit_completion milestone; conservatively "
            "includes process startup, report publication, and exit"
        ),
        "rust_phase_timings": (
            "monotonic cumulative elapsed milestones from Rust helper entry; package "
            "load complete, device ready, texture resources ready, first textured "
            "frame, and six-view audit completion"
        ),
        "renderer_wall_ms": "Rust-reported six-view D3D12 audit completion time",
        "process_wall_ms": (
            "parent-observed Rust process wall for audit completion only; never used "
            "as first-usable or texture-ready duration"
        ),
        "peak_private_bytes": (
            "maximum native-reported Preview Core or parent-sampled direct/full "
            "renderer private bytes"
        ),
        "gpu_resident_bytes": "maximum Rust-reported DDS GPU payload bytes across direct/full",
        "p95": "nearest-rank percentile: ceil(0.95 * count)",
    }


def _read_evidence_object(
    root: Path, row: Mapping[str, object], *, label: str
) -> dict[str, object]:
    relative = str(row.get("path", "") or "")
    if not relative:
        raise EquipmentPerformanceError(f"{label} path is missing.")
    candidate = (root / Path(relative.replace("/", "\\"))).resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if not candidate.is_relative_to(resolved_root):
        raise EquipmentPerformanceError(f"{label} escapes its asset evidence root.")
    expected_sha = str(row.get("sha256", "") or "").casefold()
    if not _is_sha256(expected_sha):
        raise EquipmentPerformanceError(f"{label} has no valid reported SHA-256.")
    if _sha256_file(candidate) != expected_sha:
        raise EquipmentPerformanceError(f"{label} SHA-256 does not match its report.")
    return _read_json_object(candidate, label=label)


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    size = path.stat().st_size
    if size > _MAX_JSON_BYTES:
        raise EquipmentPerformanceError(f"{label} exceeds {_MAX_JSON_BYTES} bytes.")
    raw = path.read_bytes()
    if len(raw) > _MAX_JSON_BYTES:
        raise EquipmentPerformanceError(f"{label} exceeds {_MAX_JSON_BYTES} bytes.")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EquipmentPerformanceError(f"{label} is not UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise EquipmentPerformanceError(f"{label} must contain a JSON object.")
    return value


def _read_baseline_repetition_evidence(path: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    if resolved.is_file():
        return _read_json_object(resolved, label="baseline repetition packet")
    if not resolved.is_dir():
        raise EquipmentPerformanceError(
            "Baseline repetition evidence must be a packet file or packet directory."
        )
    packet_paths = sorted(
        candidate.resolve(strict=True)
        for candidate in resolved.rglob("baseline-samples.json")
        if candidate.is_file()
    )
    if not packet_paths:
        raise EquipmentPerformanceError(
            "Baseline repetition directory contains no baseline-samples.json packets."
        )
    if len(packet_paths) > 64:
        raise EquipmentPerformanceError(
            "Baseline repetition directory contains an implausible number of packets."
        )
    packets = [
        _read_json_object(
            packet_path,
            label=f"baseline repetition packet {packet_path.name}",
        )
        for packet_path in packet_paths
    ]
    return {"schema": _BASELINE_PACKET_BUNDLE_SCHEMA, "packets": packets}


def _census_identity_failures(
    identity: Mapping[str, object],
    *,
    manifest_capture_binaries: Mapping[str, object],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []

    def require(condition: bool, gate: str, detail: str) -> None:
        if not condition:
            failures.append({"gate": gate, "detail": detail})

    require(
        identity.get("schema") == EQUIPMENT_CAPTURE_IDENTITY_SCHEMA,
        "census_identity_schema",
        "census identity schema is missing or incompatible",
    )
    require(
        bool(str(identity.get("census_run_id", "") or "").strip()),
        "census_run_id",
        "census run ID is empty",
    )
    catalogue = _mapping(identity.get("catalogue"))
    require(
        bool(str(catalogue.get("schema", "") or ""))
        and _is_sha256(str(catalogue.get("file_sha256", "") or ""))
        and _is_sha256(str(catalogue.get("selection_sha256", "") or "")),
        "census_catalogue_identity",
        "catalogue schema or SHA-256 identity is missing or malformed",
    )
    resolution = _mapping(identity.get("resolution"))
    require(
        bool(str(resolution.get("schema", "") or ""))
        and _is_sha256(str(resolution.get("file_sha256", "") or ""))
        and _is_sha256(str(resolution.get("resolution_sha256", "") or "")),
        "census_resolution_identity",
        "resolution schema or SHA-256 identity is missing or malformed",
    )
    archive = _mapping(identity.get("archive"))
    live_archive = _mapping(archive.get("live_archive"))
    require(
        bool(live_archive)
        and str(archive.get("sha256", "") or "").casefold()
        == _canonical_json_sha256(dict(live_archive)),
        "census_archive_identity",
        "live archive identity is empty or internally inconsistent",
    )
    identity_binaries = _mapping(identity.get("capture_binaries"))
    require(
        _capture_binaries_match(identity_binaries, manifest_capture_binaries)
        and _capture_binaries_match(
            manifest_capture_binaries, manifest_capture_binaries
        ),
        "census_capture_binary_identity",
        "manifest and census helper binary SHA-256 identities differ or are malformed",
    )
    harness = _mapping(identity.get("capture_harness"))
    harness_files = [
        dict(row) for row in _sequence(harness.get("files")) if isinstance(row, Mapping)
    ]
    harness_paths = [str(row.get("path", "") or "") for row in harness_files]
    harness_payload = {
        "schema": harness.get("schema"),
        "files": harness_files,
    }
    require(
        harness.get("schema") == "cdmw_equipment_material_capture_harness_v1"
        and bool(harness_files)
        and all(harness_paths)
        and len(set(harness_paths)) == len(harness_paths)
        and all(
            _safe_int(row.get("bytes"), -1) >= 0
            and _is_sha256(str(row.get("sha256", "") or ""))
            for row in harness_files
        )
        and str(harness.get("sha256", "") or "").casefold()
        == _canonical_json_sha256(harness_payload),
        "census_capture_harness_identity",
        "capture harness file inventory or canonical SHA-256 is malformed",
    )
    return failures


def _capture_binaries_match(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    for name in ("preview_core", "rust_helper"):
        actual_row = _mapping(actual.get(name))
        expected_row = _mapping(expected.get(name))
        expected_sha = str(expected_row.get("sha256", "") or "").casefold()
        if (
            not _is_sha256(expected_sha)
            or str(actual_row.get("sha256", "") or "").casefold() != expected_sha
        ):
            return False
        expected_bytes = _safe_int(expected_row.get("bytes"), -1)
        if (
            expected_bytes >= 0
            and _safe_int(actual_row.get("bytes"), -2) != expected_bytes
        ):
            return False
    return True


def _required_number(row: Mapping[str, object], key: str) -> float:
    value = _optional_number(row.get(key))
    if value is None or value < 0.0:
        raise EquipmentPerformanceError(
            f"Required non-negative metric {key} is missing."
        )
    return value


def _required_positive_number(row: Mapping[str, object], key: str) -> float:
    value = _required_number(row, key)
    if value <= 0.0:
        raise EquipmentPerformanceError(
            f"Required positive metric {key} has no positive sample."
        )
    return value


def _validated_phase_timings(
    report_or_render_row: Mapping[str, object],
    *,
    label: str,
) -> dict[str, float]:
    phase = _mapping(report_or_render_row.get("phase_timings"))
    if phase.get("schema") != RUST_MATERIAL_PHASE_TIMINGS_SCHEMA:
        raise EquipmentPerformanceError(
            f"{label} phase timing schema is missing or incompatible."
        )
    values = {field: _required_number(phase, field) for field in _RUST_PHASE_FIELDS}
    ordered = [values[field] for field in _RUST_PHASE_FIELDS]
    if ordered != sorted(ordered):
        raise EquipmentPerformanceError(
            f"{label} phase timings are not monotonic cumulative milestones."
        )
    return values


def _optional_validated_phase_timings(
    report_or_render_row: Mapping[str, object],
    *,
    label: str,
) -> dict[str, float] | None:
    if not _mapping(report_or_render_row.get("phase_timings")):
        return None
    try:
        return _validated_phase_timings(report_or_render_row, label=label)
    except EquipmentPerformanceError:
        return None


def _parent_observed_phase_ms(
    process: Mapping[str, object],
    phase: Mapping[str, float],
    field: str,
) -> float:
    """Charge the conservative process-boundary envelope, not the audit tail."""

    return _process_boundary_overhead_ms(process, phase) + _required_number(
        phase, field
    )


def _process_boundary_overhead_ms(
    process: Mapping[str, object], phase: Mapping[str, float]
) -> float:
    """Return startup + report-publication + exit time outside Rust milestones."""

    process_wall_ms = _required_number(process, "process_wall_ms")
    audit_completion_ms = _required_number(phase, "audit_completion_ms")
    return max(0.0, process_wall_ms - audit_completion_ms)


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0.0 else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: Mapping[str, object], key: str) -> list[dict[str, object]]:
    return [dict(row) for row in _sequence(value.get(key)) if isinstance(row, Mapping)]


def _sequence(value: object) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return fallback


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.casefold())


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _missing_comparison(reason: str) -> dict[str, object]:
    return {"status": "incomplete", "ok": False, "reason": reason}


__all__ = [
    "A48F00CE_BASELINE_SAMPLES_SCHEMA",
    "COLD_REPETITIONS",
    "EQUIPMENT_PERFORMANCE_REPETITION_PLAN_SCHEMA",
    "EQUIPMENT_PERFORMANCE_REPETITION_RESULTS_SCHEMA",
    "EQUIPMENT_PERFORMANCE_SUMMARY_SCHEMA",
    "WARM_REPETITIONS",
    "EquipmentPerformanceError",
    "build_equipment_performance_summary",
    "build_equipment_repetition_plan",
    "evaluate_equipment_repetition_results",
    "run_equipment_performance_repetitions",
]
