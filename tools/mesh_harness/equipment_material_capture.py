"""Resumable production material capture for the frozen equipment catalogue.

The runner consumes the already-frozen catalogue and live-resolution evidence.
Each renderable logical PAC follows the production Preview Core -> direct/full
Rust -> D3D12 path.  Evidence is published one logical PAC at a time, outside
the repository and game install, so an interrupted census can resume safely.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import psutil
from PIL import Image, ImageDraw, ImageFont

from cdmw.core.atomic_file import (
    atomic_copy_file,
    atomic_publish_directory,
    atomic_write_bytes,
    atomic_write_text,
)
from cdmw.core.texture_native import ensure_native_dds_preview_png
from cdmw.rendering.native_preview_core import (
    NATIVE_PREVIEW_CORE_BACKEND_ID,
    find_native_preview_core_binary,
    run_native_preview_core_preview_job,
)
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package_from_preview_core,
)
from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.equipment_archive_resolution import (
    EQUIPMENT_AUDIT_RESOLUTION_SCHEMA,
)
from tools.mesh_harness.equipment_archive_worker import archive_entry_from_worker
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
    EQUIPMENT_AUDIT_ICON_COUNT,
    EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    EQUIPMENT_AUDIT_RECORD_COUNT,
    EQUIPMENT_AUDIT_RHETT_LOGICAL_PAC,
    normalized_archive_key,
)
from tools.mesh_harness.material_profile_corpus import _dds_header_row
from tools.mesh_harness.visual_audit_report import (
    _write_contact_sheet,
    _write_labeled_grid,
    _write_pair,
)
from tools.mesh_harness.visual_audit_source_boards import (
    build_source_material_boards,
)

EQUIPMENT_CAPTURE_SCHEMA = "cdmw_equipment_material_capture_v1"
EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA = "cdmw_equipment_material_capture_run_state_v1"
EQUIPMENT_CAPTURE_MANIFEST_SCHEMA = "cdmw_equipment_material_capture_manifest_v1"
EQUIPMENT_CAPTURE_IDENTITY_SCHEMA = "cdmw_equipment_material_capture_identity_v1"
EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA = (
    "cdmw_equipment_material_capture_binaries_v1"
)
EQUIPMENT_CAPTURE_HARNESS_SCHEMA = "cdmw_equipment_material_capture_harness_v1"
EQUIPMENT_SOURCE_ONLY_SCHEMA = "cdmw_equipment_source_only_capture_v1"
EQUIPMENT_ARCHIVE_FINGERPRINT_SCHEMA = "cdmw_equipment_archive_fingerprints_v1"
EQUIPMENT_REVIEW_SUMMARY_SCHEMA = "cdmw_equipment_material_review_summary_v2"
EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA = (
    "cdmw_equipment_material_review_source_disposition_v1"
)
RUST_AUDIT_CAPTURE_SCHEMA = "cdmw_rust_material_audit_capture_v2"
RUST_MATERIAL_PHASE_TIMINGS_SCHEMA = "cdmw_rust_material_capture_phase_timings_v1"
EXPECTED_PREVIEW_CORE_SCHEMA = 8
EXPECTED_MATERIAL_GRAPH_VERSION = 4
EXPECTED_MATERIAL_SEMANTICS_VERSION = 10
FULL_MODEL_VIEWS = (
    "front",
    "three-quarter-front",
    "side",
    "back",
    "slightly-above",
    "slightly-below",
)
_GIB = 1024 * 1024 * 1024
_CAPTURE_HARNESS_SOURCE_PATHS = (
    "cdmw/core/texture_native.py",
    "cdmw/rendering/native_preview_core.py",
    "cdmw/services/mesh_dotnet_material_bindings.py",
    "cdmw/services/mesh_rust_authoring.py",
    "cdmw/services/mesh_rust_contract.py",
    "cdmw/services/mesh_rust_preview_package.py",
    "tools/mesh_harness/equipment_archive_worker.py",
    "tools/mesh_harness/equipment_material_capture.py",
    "tools/mesh_harness/equipment_material_capture_cli.py",
    "tools/mesh_harness/material_profile_corpus.py",
    "tools/mesh_harness/visual_audit_report.py",
    "tools/mesh_harness/visual_audit_source_boards.py",
)


def build_capture_harness_fingerprint(
    repository_root: Path | str | None = None,
    *,
    source_paths: Sequence[str] = _CAPTURE_HARNESS_SOURCE_PATHS,
) -> dict[str, object]:
    """Hash the exact Python path that drives production material capture."""

    root = (
        Path(repository_root).expanduser().resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    normalized_paths = tuple(
        sorted(
            {
                PurePosixPath(str(value).replace("\\", "/")).as_posix()
                for value in source_paths
            }
        )
    )
    if not normalized_paths or any(
        not value or value.startswith("../") or PurePosixPath(value).is_absolute()
        for value in normalized_paths
    ):
        raise ValueError("Capture-harness source paths must be relative repository files.")
    files: list[dict[str, object]] = []
    for relative in normalized_paths:
        path = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Capture-harness source escaped the repository: {relative}")
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    fingerprint_payload = {
        "schema": EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
        "files": files,
    }
    return {
        **fingerprint_payload,
        "sha256": _canonical_json_sha256(fingerprint_payload),
    }


def build_capture_census_identity(
    *,
    catalogue_path: Path | str,
    resolution_path: Path | str,
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
    census_run_id: str,
    capture_harness: Mapping[str, object],
    capture_binaries: Mapping[str, object],
) -> dict[str, object]:
    """Build the immutable identity shared by every shard in one census run."""

    normalized_run_id = _normalize_census_run_id(census_run_id)
    live_archive = dict(_mapping(resolution.get("live_archive")))
    return {
        "schema": EQUIPMENT_CAPTURE_IDENTITY_SCHEMA,
        "census_run_id": normalized_run_id,
        "catalogue": {
            "schema": catalogue.get("schema"),
            "file_sha256": _sha256_file(Path(catalogue_path)),
            "selection_sha256": _mapping(catalogue.get("selection")).get(
                "selection_sha256"
            ),
        },
        "resolution": {
            "schema": resolution.get("schema"),
            "file_sha256": _sha256_file(Path(resolution_path)),
            "resolution_sha256": resolution.get("resolution_sha256"),
        },
        "archive": {
            "live_archive": live_archive,
            "sha256": _canonical_json_sha256(live_archive),
        },
        "capture_binaries": dict(capture_binaries),
        "capture_harness": dict(capture_harness),
    }


def load_equipment_capture_inputs(
    catalogue_path: Path | str,
    resolution_path: Path | str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Load and re-prove the immutable census inputs before any capture."""

    catalogue = _read_json_object(Path(catalogue_path), label="frozen catalogue")
    resolution = _read_json_object(Path(resolution_path), label="live resolution")
    if catalogue.get("schema") != EQUIPMENT_AUDIT_CATALOGUE_SCHEMA:
        raise ValueError("Equipment capture requires the frozen catalogue v1 schema.")
    source = _mapping(catalogue.get("source"))
    selection = _mapping(catalogue.get("selection"))
    if source.get("item_catalog_sha256") != EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256:
        raise ValueError(
            "Equipment capture item-catalogue SHA-256 is not the frozen value."
        )
    expected_catalogue_counts = {
        "record_count": EQUIPMENT_AUDIT_RECORD_COUNT,
        "unique_logical_pac_count": EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
        "unique_icon_count": EQUIPMENT_AUDIT_ICON_COUNT,
    }
    for key, expected in expected_catalogue_counts.items():
        if _safe_int(selection.get(key), -1) != expected:
            raise ValueError(f"Frozen equipment catalogue {key} is not {expected:,}.")
    if len(_sequence(catalogue.get("records"))) != EQUIPMENT_AUDIT_RECORD_COUNT:
        raise ValueError("Frozen equipment catalogue record rows are incomplete.")
    if (
        len(_sequence(catalogue.get("logical_models")))
        != EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT
    ):
        raise ValueError("Frozen equipment logical-model rows are incomplete.")
    if len(_sequence(catalogue.get("icons"))) != EQUIPMENT_AUDIT_ICON_COUNT:
        raise ValueError("Frozen equipment icon rows are incomplete.")

    if resolution.get("schema") != EQUIPMENT_AUDIT_RESOLUTION_SCHEMA:
        raise ValueError("Equipment capture requires the live-resolution v1 schema.")
    frozen = _mapping(resolution.get("frozen_catalogue"))
    if frozen.get("schema") != catalogue.get("schema"):
        raise ValueError("Live resolution does not name the frozen catalogue schema.")
    if frozen.get("item_catalog_sha256") != source.get("item_catalog_sha256"):
        raise ValueError(
            "Live resolution belongs to a different frozen item catalogue."
        )
    if frozen.get("selection_sha256") != selection.get("selection_sha256"):
        raise ValueError("Live resolution belongs to a different equipment selection.")
    counts = _mapping(resolution.get("counts"))
    exact_resolution_counts = {
        "logical_models": EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
        "icons": EQUIPMENT_AUDIT_ICON_COUNT,
        "unresolved_logical_models": 0,
        "unresolved_icons": 0,
        "prefab_decode_errors": 0,
    }
    for key, expected in exact_resolution_counts.items():
        if _safe_int(counts.get(key), -1) != expected:
            raise ValueError(f"Equipment resolution {key} is not {expected:,}.")
    rows = _sequence(resolution.get("logical_models"))
    if len(rows) != EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT:
        raise ValueError("Equipment resolution logical-model rows are incomplete.")
    identities = [str(_mapping(row).get("identity", "")).casefold() for row in rows]
    if len(set(identities)) != len(identities) or any(
        not value for value in identities
    ):
        raise ValueError(
            "Equipment resolution logical identities are empty or duplicated."
        )
    return catalogue, resolution


def equipment_archive_paths_from_resolution(
    resolution: Mapping[str, object],
) -> tuple[Path, ...]:
    paths: set[Path] = set()

    def add_entry(raw: object) -> None:
        entry = _mapping(raw)
        for key in ("source_pamt", "pamt_path", "paz_file"):
            value = str(entry.get(key, "") or "").strip()
            if value:
                paths.add(Path(value).expanduser().resolve())

    for logical in _sequence(resolution.get("logical_models")):
        for component in _sequence(_mapping(logical).get("physical_components")):
            add_entry(_mapping(component).get("entry"))
    for icon in _sequence(resolution.get("icons")):
        for entry in _sequence(_mapping(icon).get("entries")):
            add_entry(entry)
    return tuple(sorted(paths, key=lambda value: str(value).casefold()))


def write_equipment_archive_fingerprint_snapshot(
    resolution: Mapping[str, object],
    output_path: Path | str,
    *,
    phase: str,
) -> dict[str, object]:
    normalized_phase = str(phase or "").strip().casefold()
    if normalized_phase not in {"before", "after"}:
        raise ValueError("Equipment archive fingerprint phase must be before or after.")
    paths = equipment_archive_paths_from_resolution(resolution)
    fingerprints = _archive_content_fingerprints(paths)
    missing = [
        path for path, row in fingerprints.items() if row.get("exists") is not True
    ]
    payload = {
        "schema": EQUIPMENT_ARCHIVE_FINGERPRINT_SCHEMA,
        "ok": bool(paths) and not missing,
        "phase": normalized_phase,
        "captured_unix_ms": int(time.time() * 1000),
        "resolution_sha256": resolution.get("resolution_sha256"),
        "path_count": len(paths),
        "missing_paths": missing,
        "fingerprints": fingerprints,
    }
    atomic_write_text(Path(output_path), _json_text(payload))
    return payload


def build_equipment_capture_plans(
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Create a deterministic logical-PAC plan, preserving every owner and variant."""

    records = {
        str(row.get("record_id", "")): dict(row)
        for raw in _sequence(catalogue.get("records"))
        if (row := _mapping(raw))
    }
    icon_rows = {
        normalized_archive_key(row.get("identity")): dict(row)
        for raw in _sequence(resolution.get("icons"))
        if (row := _mapping(raw))
    }
    plans: list[dict[str, object]] = []
    for ordinal, raw_logical in enumerate(_sequence(resolution.get("logical_models"))):
        logical = dict(_mapping(raw_logical))
        identity = normalized_archive_key(logical.get("identity"))
        if not identity:
            raise ValueError(f"Equipment logical row {ordinal} has no identity.")
        owners = [dict(_mapping(row)) for row in _sequence(logical.get("owners"))]
        owner_record_ids = tuple(
            dict.fromkeys(str(row.get("record_id", "")) for row in owners)
        )
        owner_records = [
            records[value] for value in owner_record_ids if value in records
        ]
        if len(owner_records) != len(owner_record_ids):
            raise ValueError(
                f"Equipment logical row {identity} has an unknown owner record."
            )
        icon_identities = tuple(
            dict.fromkeys(
                normalized_archive_key(path)
                for record in owner_records
                for path in _sequence(record.get("icon_paths"))
                if normalized_archive_key(path)
            )
        )
        associated_icons = [
            icon_rows[value] for value in icon_identities if value in icon_rows
        ]
        if len(associated_icons) != len(icon_identities):
            raise ValueError(
                f"Equipment logical row {identity} has an unresolved owner icon."
            )

        components = [
            dict(_mapping(row)) for row in _sequence(logical.get("physical_components"))
        ]
        source_only = str(logical.get("status", "")) == "catalogue_source_only"
        primary_rows = [row for row in components if row.get("is_primary") is True]
        if source_only:
            if (
                components
                or primary_rows
                or not _mapping(logical.get("source_only_finding"))
            ):
                raise ValueError(
                    f"Source-only equipment row {identity} has invalid geometry evidence."
                )
        elif len(primary_rows) != 1:
            raise ValueError(
                f"Renderable equipment row {identity} does not have one primary component."
            )
        canonical_indices: dict[str, int] = {}
        index_variants: list[dict[str, object]] = []
        for component in components:
            entry = _mapping(component.get("entry"))
            path = str(entry.get("path", "") or "").replace("\\", "/").strip("/")
            indices = sorted(
                {
                    _safe_int(value, -1)
                    for value in _sequence(component.get("model_property_indices"))
                }
            )
            indices = [value for value in indices if value >= 0]
            if indices:
                canonical_indices[path] = indices[0]
            index_variants.append(
                {
                    "path": path,
                    "model_property_indices": indices,
                    "roles": list(_sequence(component.get("roles"))),
                    "source_prefabs": list(_sequence(component.get("source_prefabs"))),
                    "is_primary": component.get("is_primary") is True,
                }
            )
        component_paths = tuple(
            str(_mapping(row.get("entry")).get("path", "") or "").replace("\\", "/")
            for row in components
        )
        enabled_paths = (
            tuple(component_paths)
            if any(_sequence(row.get("source_prefabs")) for row in components)
            else ()
        )
        asset_id = f"{ordinal:04d}-{_safe_component(PurePosixPath(identity).stem)}"
        plans.append(
            {
                "ordinal": ordinal,
                "asset_id": asset_id,
                "identity": identity,
                "declared_name": str(logical.get("declared_name", "") or ""),
                "resolution_status": str(logical.get("status", "") or ""),
                "source_only": source_only,
                "source_only_finding": dict(
                    _mapping(logical.get("source_only_finding"))
                ),
                "owners": owners,
                "owner_records": owner_records,
                "icons": associated_icons,
                "physical_components": components,
                "primary_component": dict(primary_rows[0]) if primary_rows else None,
                "enabled_prefab_component_paths": list(enabled_paths),
                "canonical_model_property_indices": canonical_indices,
                "model_property_index_variants": index_variants,
                "prefab_candidates": [
                    dict(_mapping(row))
                    for row in _sequence(logical.get("prefab_candidates"))
                ],
                "prefab_edges": [
                    dict(_mapping(row))
                    for row in _sequence(logical.get("prefab_edges"))
                ],
            }
        )
    if len(plans) != EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT:
        raise ValueError("Equipment capture plan did not preserve all logical PACs.")
    return tuple(plans)


def run_equipment_material_capture(
    *,
    catalogue_path: Path | str,
    resolution_path: Path | str,
    output_root: Path | str,
    cache_root: Path | str,
    rust_helper: Path | str,
    start: int = 0,
    limit: int | None = None,
    resume: bool = True,
    census_run_id: str | None = None,
    capture_timeout_seconds: float = 180.0,
    stop_on_failure: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    """Capture a bounded or complete slice and checkpoint after every logical PAC."""

    catalogue, resolution = load_equipment_capture_inputs(
        catalogue_path, resolution_path
    )
    plans = build_equipment_capture_plans(catalogue, resolution)
    root = Path(output_root).expanduser().resolve()
    cache = Path(cache_root).expanduser().resolve()
    helper = Path(rust_helper).expanduser().resolve(strict=True)
    if not helper.is_file():
        raise FileNotFoundError(helper)
    root.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    assets_root = root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    runtime_root = root / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    source_cache_root = root / "source-cache"
    source_cache_root.mkdir(parents=True, exist_ok=True)
    state_path = root / "capture-run-state.json"
    capture_binaries = resolve_capture_binary_evidence(helper)
    begin = max(0, int(start))
    end = len(plans) if limit is None else min(len(plans), begin + max(0, int(limit)))
    capture_slice = _capture_slice(begin, end, len(plans))
    requested_run_id = _resolve_census_run_id(
        state_path,
        supplied=census_run_id,
        resume=resume,
    )
    capture_harness = build_capture_harness_fingerprint()
    census_identity = build_capture_census_identity(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        catalogue=catalogue,
        resolution=resolution,
        census_run_id=requested_run_id,
        capture_harness=capture_harness,
        capture_binaries=capture_binaries,
    )
    if resume:
        state = _load_capture_state(
            state_path,
            resolution,
            expected_census_identity=census_identity,
            expected_capture_slice=capture_slice,
        )
    else:
        state = _new_capture_state(
            resolution,
            census_identity=census_identity,
            capture_slice=capture_slice,
        )
        _write_capture_state(state_path, state)
    atomic_write_text(
        root / "capture-binaries.json",
        _json_text(
            {
                "schema": EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA,
                **_capture_identity_stamp(census_identity),
            }
        ),
    )
    icon_cache: dict[str, dict[str, object]] = {}
    selected = plans[begin:end]
    if progress is not None:
        progress(0, len(selected), f"capture slice {begin}:{end}")

    for slice_index, plan in enumerate(selected, 1):
        asset_id = str(plan["asset_id"])
        final_asset_root = assets_root / asset_id
        existing = _valid_published_asset(
            final_asset_root,
            identity=str(plan["identity"]),
            expected_binaries=capture_binaries,
            expected_census_identity=census_identity,
        )
        if resume and existing is not None:
            _checkpoint_asset(
                state, plan, status=str(existing.get("status", "captured"))
            )
            _write_capture_state(state_path, state)
            if progress is not None:
                progress(slice_index, len(selected), f"resume {plan['identity']}")
            continue
        staging = assets_root / f".{asset_id}.{uuid4().hex}.staging"
        runtime = Path(tempfile.mkdtemp(prefix=f"{asset_id}-", dir=runtime_root))
        started = time.perf_counter()
        failed_this_asset = False
        try:
            staging.mkdir(parents=True, exist_ok=False)
            if plan.get("source_only") is True:
                report = _capture_source_only_asset(
                    plan,
                    staging,
                    source_cache_root=source_cache_root,
                    icon_cache=icon_cache,
                    census_identity=census_identity,
                )
            else:
                report = _capture_renderable_asset(
                    plan,
                    staging,
                    runtime,
                    cache_root=cache,
                    source_cache_root=source_cache_root,
                    rust_helper=helper,
                    capture_binaries=capture_binaries,
                    capture_timeout_seconds=capture_timeout_seconds,
                    icon_cache=icon_cache,
                )
            report.update(_capture_identity_stamp(census_identity))
            report["catalogue_ordinal"] = plan["ordinal"]
            report["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            atomic_write_text(staging / "asset-report.json", _json_text(report))
            atomic_publish_directory(staging, final_asset_root)
            _checkpoint_asset(state, plan, status=str(report["status"]))
        except Exception as exc:  # noqa: BLE001 - each asset failure must be checkpointed
            failed_this_asset = True
            shutil.rmtree(staging, ignore_errors=True)
            _checkpoint_asset(
                state,
                plan,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if runtime.is_relative_to(runtime_root):
                shutil.rmtree(runtime, ignore_errors=True)
            _write_capture_state(state_path, state)
        if progress is not None:
            row = _mapping(_mapping(state.get("assets")).get(str(plan["identity"])))
            progress(
                slice_index,
                len(selected),
                f"{row.get('status', 'unknown')} {plan['identity']}",
            )
        if failed_this_asset and stop_on_failure:
            break

    manifest = build_equipment_capture_manifest(
        root,
        catalogue,
        resolution,
        plans,
        state=state,
        expected_binaries=capture_binaries,
        expected_census_identity=census_identity,
    )
    atomic_write_text(root / "capture-manifest.json", _json_text(manifest))
    return manifest


def build_equipment_capture_manifest(
    output_root: Path,
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
    plans: Sequence[Mapping[str, object]],
    *,
    state: Mapping[str, object] | None = None,
    expected_binaries: Mapping[str, object] | None = None,
    expected_census_identity: Mapping[str, object] | None = None,
    report_reference_root: Path | None = None,
) -> dict[str, object]:
    if state is None:
        state_path = output_root / "capture-run-state.json"
        state = (
            _load_capture_state(state_path, resolution)
            if state_path.is_file()
            else {"assets": {}}
        )
    census_identity = dict(
        expected_census_identity or _mapping(state.get("census_identity"))
    )
    strict_state = bool(census_identity)
    state_assets = _mapping(state.get("assets"))
    assets: list[dict[str, object]] = []
    status_counts: dict[str, int] = {}
    for plan in plans:
        asset_root = output_root / "assets" / str(plan["asset_id"])
        state_row = _mapping(state_assets.get(str(plan["identity"])))
        state_status = str(state_row.get("status", "") or "")
        report = None
        if not strict_state or state_status in {
            "captured",
            "reviewed",
            "source_only_captured",
            "source_only_reviewed",
        }:
            report = _valid_published_asset(
                asset_root,
                identity=str(plan["identity"]),
                expected_binaries=expected_binaries,
                expected_census_identity=census_identity if strict_state else None,
            )
        if report is not None:
            status = str(report.get("status", "missing"))
            error = ""
        elif state_row.get("status") == "failed":
            status = "failed"
            error = str(state_row.get("error", "") or "")
        else:
            status = "missing"
            error = ""
        status_counts[status] = status_counts.get(status, 0) + 1
        assets.append(
            {
                "ordinal": plan["ordinal"],
                "asset_id": plan["asset_id"],
                "identity": plan["identity"],
                "status": status,
                "report": str(
                    (report_reference_root or output_root)
                    / "assets"
                    / str(plan["asset_id"])
                    / "asset-report.json"
                )
                if report is not None
                else "",
                "report_sha256": _sha256_file(asset_root / "asset-report.json")
                if report is not None
                else "",
                "error": error,
            }
        )
    capture_complete = sum(
        value
        for key, value in status_counts.items()
        if key
        in {"captured", "reviewed", "source_only_captured", "source_only_reviewed"}
    )
    reviewed = status_counts.get("reviewed", 0) + status_counts.get(
        "source_only_reviewed", 0
    )
    unreviewed = status_counts.get("captured", 0) + status_counts.get(
        "source_only_captured", 0
    )
    failed = status_counts.get("failed", 0)
    missing = status_counts.get("missing", 0)
    return {
        "schema": EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
        **_capture_identity_stamp(census_identity),
        "capture_slice": dict(_mapping(state.get("capture_slice"))),
        **(
            {"assembly": dict(_mapping(state.get("assembly")))}
            if _mapping(state.get("assembly"))
            else {}
        ),
        "ok": len(plans) == EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT
        and reviewed == EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT
        and unreviewed == 0
        and failed == 0
        and missing == 0,
        "catalogue_schema": catalogue.get("schema"),
        "resolution_schema": resolution.get("schema"),
        "catalogue_selection_sha256": _mapping(catalogue.get("selection")).get(
            "selection_sha256"
        ),
        "resolution_sha256": resolution.get("resolution_sha256"),
        "capture_binaries": dict(
            expected_binaries or _mapping(census_identity.get("capture_binaries"))
        ),
        "live_archive": dict(_mapping(resolution.get("live_archive"))),
        "logical_model_count": len(plans),
        "capture_complete": capture_complete == EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
        "capture_complete_count": capture_complete,
        "completed_count": reviewed,
        "reviewed_count": reviewed,
        "captured_count": unreviewed,
        "renderable_captured_count": status_counts.get("captured", 0),
        "source_only_captured_count": status_counts.get("source_only_captured", 0),
        "status_counts": status_counts,
        "unreviewed_count": unreviewed,
        "failed_count": failed,
        "missing_count": missing,
        "assets": assets,
    }


def _capture_renderable_asset(
    plan: Mapping[str, object],
    staging: Path,
    runtime: Path,
    *,
    cache_root: Path,
    source_cache_root: Path,
    rust_helper: Path,
    capture_binaries: Mapping[str, object],
    capture_timeout_seconds: float,
    icon_cache: MutableMapping[str, dict[str, object]],
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
        timeout_seconds=max(5.0, float(capture_timeout_seconds)),
        use_service=True,
        dds_cache_max_bytes=8 * _GIB,
        dds_cache_target_bytes=7 * _GIB,
    )
    if not attempt.succeeded:
        raise RuntimeError(
            f"Preview Core failed for {plan['identity']}: {attempt.fallback_reason or attempt.status}"
        )
    native_manifest_path = Path(attempt.package_path) / "manifest.json"
    native_manifest = _read_json_object(
        native_manifest_path, label="Preview Core manifest"
    )
    native_gates = _validate_native_manifest(native_manifest, plan)
    if not all(native_gates.values()):
        failed = [key for key, value in native_gates.items() if not value]
        raise RuntimeError(f"Preview Core material gates failed: {', '.join(failed)}")
    native_wall_ms = round((time.perf_counter() - native_started) * 1000.0, 3)
    manifest_root = staging / "manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)
    native_manifest_copy = manifest_root / "preview-core-manifest.json"
    atomic_copy_file(native_manifest_path, native_manifest_copy)

    direct_build_started = time.perf_counter()
    direct_package = build_rust_preview_package_from_preview_core(
        native_root,
        output_package_dir=runtime / "rust-direct",
        material_quality="direct",
    )
    direct_package_build_ms = round(
        (time.perf_counter() - direct_build_started) * 1000.0, 3
    )
    full_build_started = time.perf_counter()
    full_package = build_rust_preview_package_from_preview_core(
        native_root,
        output_package_dir=runtime / "rust-full",
        material_quality="full",
    )
    full_package_build_ms = round(
        (time.perf_counter() - full_build_started) * 1000.0, 3
    )
    direct_manifest = _read_json_object(
        direct_package.manifest_path, label="direct Rust manifest"
    )
    full_manifest = _read_json_object(
        full_package.manifest_path, label="full Rust manifest"
    )
    _validate_rust_package_manifest(direct_manifest, quality="direct")
    _validate_rust_package_manifest(full_manifest, quality="full")
    direct_manifest_copy = manifest_root / "rust-direct-manifest.json"
    full_manifest_copy = manifest_root / "rust-full-manifest.json"
    atomic_copy_file(direct_package.manifest_path, direct_manifest_copy)
    atomic_copy_file(full_package.manifest_path, full_manifest_copy)

    before_root = staging / "before"
    after_root = staging / "after"
    before_report, before_process = _run_rust_audit_capture(
        rust_helper,
        direct_package.manifest_path,
        before_root,
        full_model_only=True,
        timeout_seconds=capture_timeout_seconds,
    )
    after_report, after_process = _run_rust_audit_capture(
        rust_helper,
        full_package.manifest_path,
        after_root,
        full_model_only=False,
        timeout_seconds=capture_timeout_seconds,
    )

    texture_rows, material_state = _publish_material_source_evidence(
        native_manifest,
        source_cache_root=source_cache_root,
    )
    source_boards = build_source_material_boards(
        str(plan["asset_id"]),
        texture_rows,
        material_state,
        staging / "source-boards",
        decoded_cache_root=source_cache_root / "decoded-dds",
    )
    icon_evidence = _capture_plan_icons(
        plan,
        source_cache_root=source_cache_root,
        memo=icon_cache,
    )
    icon_board = _write_icon_board(
        staging / "source-boards" / "icon-board.png", plan, icon_evidence
    )
    composites = _build_comparisons(
        plan, staging, before_root, after_root, source_boards
    )
    portable_source_boards = _relativize_source_board_manifest(source_boards, staging)
    source_board_manifest_path = Path(str(source_boards["manifest_path"]))
    atomic_write_text(source_board_manifest_path, _json_text(portable_source_boards))
    all_gates = {
        **native_gates,
        "direct_capture": _capture_report_ok(before_report, full_model_only=True),
        "full_capture": _capture_report_ok(after_report, full_model_only=False),
        "all_logical_dds_edges_published": len(texture_rows)
        == _safe_int(
            _mapping(native_manifest.get("material_conservation")).get(
                "resolved_texture_count"
            ),
            -1,
        ),
        "source_board_parameter_inventory_complete": len(
            _sequence(source_boards.get("parameters"))
        )
        == _safe_int(
            _mapping(native_manifest.get("material_conservation")).get(
                "declared_parameter_count"
            ),
            -1,
        ),
        "source_board_graph_edges_complete": (
            _graph_source_board_coverage_complete(source_boards)
        ),
        "source_board_visible_submeshes_complete": len(
            _sequence(source_boards.get("boards"))
        )
        == len(_sequence(native_manifest.get("batches"))),
        "source_dds_decoded": all(
            not str(row.get("decode_error", ""))
            for row in _sequence(source_boards.get("textures"))
        ),
        "owner_icons_resolved": bool(icon_evidence)
        and all(row.get("ok") is True for row in icon_evidence),
        "direct_dds_decode_upload_deduplicated": _report_dds_dedup_ok(before_report),
        "full_dds_decode_upload_deduplicated": _report_dds_dedup_ok(after_report),
        "performance_measurements_complete": all(
            value > 0.0
            for value in (
                direct_package_build_ms,
                full_package_build_ms,
                _safe_float(before_process.get("process_wall_ms"), 0.0),
                _safe_float(after_process.get("process_wall_ms"), 0.0),
                _safe_float(before_process.get("peak_private_bytes"), 0.0),
                _safe_float(after_process.get("peak_private_bytes"), 0.0),
                _safe_float(before_process.get("peak_working_set_bytes"), 0.0),
                _safe_float(after_process.get("peak_working_set_bytes"), 0.0),
                _safe_float(
                    _mapping(attempt.diagnostics).get("process_private_bytes"), 0.0
                ),
                _safe_float(
                    _mapping(attempt.diagnostics).get("process_working_set_bytes"),
                    0.0,
                ),
            )
        )
        and _capture_phase_timings_ok(before_report)
        and _capture_phase_timings_ok(after_report),
    }
    if not all(all_gates.values()):
        failed = [key for key, value in all_gates.items() if not value]
        raise RuntimeError(f"Equipment capture gates failed: {', '.join(failed)}")
    return {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "status": "captured",
        "verdict": "UNREVIEWED",
        "review_status": "pending_direct_visual_review",
        "identity": plan["identity"],
        "asset_id": plan["asset_id"],
        "canonical_rhett": plan["identity"] == EQUIPMENT_AUDIT_RHETT_LOGICAL_PAC,
        "resolution_status": plan["resolution_status"],
        "owners": list(_sequence(plan.get("owners"))),
        "owner_records": list(_sequence(plan.get("owner_records"))),
        "physical_components": list(_sequence(plan.get("physical_components"))),
        "enabled_prefab_component_paths": list(
            _sequence(plan.get("enabled_prefab_component_paths"))
        ),
        "canonical_model_property_indices": dict(
            _mapping(plan.get("canonical_model_property_indices"))
        ),
        "model_property_index_variants": list(
            _sequence(plan.get("model_property_index_variants"))
        ),
        "prefab_edges": list(_sequence(plan.get("prefab_edges"))),
        "renderer_path": "native_preview_core_to_direct_and_full_rust_to_wgpu_d3d12",
        "python_material_synthesis_used": False,
        "capture_binaries": dict(capture_binaries),
        "preview_core": {
            "backend": NATIVE_PREVIEW_CORE_BACKEND_ID,
            "elapsed_ms": round(attempt.elapsed_ms, 3),
            "wall_ms": native_wall_ms,
            "diagnostics": dict(attempt.diagnostics),
            "manifest": _file_evidence(native_manifest_copy, staging),
        },
        "rust_packages": {
            "direct_manifest": _file_evidence(direct_manifest_copy, staging),
            "full_manifest": _file_evidence(full_manifest_copy, staging),
        },
        "performance": {
            "schema": "cdmw_equipment_material_performance_v1",
            "preview_core": {
                "elapsed_ms": round(attempt.elapsed_ms, 3),
                "wall_ms": native_wall_ms,
            },
            "package_build": {
                "direct_ms": direct_package_build_ms,
                "full_ms": full_package_build_ms,
            },
            "render": {
                "direct": {
                    **before_process,
                    "phase_timings": dict(
                        _mapping(before_report.get("phase_timings"))
                    ),
                    "renderer_wall_ms": round(
                        _safe_float(before_report.get("wall_ms"), 0.0), 3
                    ),
                },
                "full": {
                    **after_process,
                    "phase_timings": dict(
                        _mapping(after_report.get("phase_timings"))
                    ),
                    "renderer_wall_ms": round(
                        _safe_float(after_report.get("wall_ms"), 0.0), 3
                    ),
                },
            },
            "resources": {
                "logical_texture_edge_count": len(texture_rows),
                "direct_source_dds": dict(_mapping(before_report.get("source_dds"))),
                "full_source_dds": dict(_mapping(after_report.get("source_dds"))),
                "direct_runtime_dds": dict(_mapping(before_report.get("runtime_dds"))),
                "full_runtime_dds": dict(_mapping(after_report.get("runtime_dds"))),
            },
        },
        "before_report": _file_evidence(before_root / "audit-report.json", staging),
        "after_report": _file_evidence(after_root / "audit-report.json", staging),
        "source_boards": portable_source_boards,
        "source_board_manifest": _file_evidence(source_board_manifest_path, staging),
        "logical_texture_edge_count": len(texture_rows),
        "icons": icon_evidence,
        "icon_board": _file_evidence(icon_board, staging),
        "composites": composites,
        "technical_gates": all_gates,
    }


def _capture_source_only_asset(
    plan: Mapping[str, object],
    staging: Path,
    *,
    source_cache_root: Path,
    icon_cache: MutableMapping[str, dict[str, object]],
    census_identity: Mapping[str, object],
) -> dict[str, object]:
    icon_evidence = _capture_plan_icons(
        plan, source_cache_root=source_cache_root, memo=icon_cache
    )
    source_root = staging / "source-boards"
    icon_board = _write_icon_board(source_root / "icon-board.png", plan, icon_evidence)
    before_root = staging / "before" / "full-model"
    after_root = staging / "after" / "full-model"
    finding = dict(_mapping(plan.get("source_only_finding")))
    for view in FULL_MODEL_VIEWS:
        _write_source_only_panel(
            before_root / f"{view}.png", plan, finding, phase="Before"
        )
        _write_source_only_panel(
            after_root / f"{view}.png", plan, finding, phase="After"
        )
    source_report = {
        "schema": EQUIPMENT_SOURCE_ONLY_SCHEMA,
        **_capture_identity_stamp(census_identity),
        "ok": True,
        "identity": plan["identity"],
        "finding": finding,
        "fixed_full_model_view_count": len(FULL_MODEL_VIEWS),
        "rendering_not_applicable": True,
    }
    atomic_write_text(staging / "source-only-report.json", _json_text(source_report))
    composites = _build_comparisons(
        plan, staging, staging / "before", staging / "after", {}
    )
    gates = {
        "source_only_finding_present": bool(finding),
        "no_substituted_geometry": not _sequence(plan.get("physical_components")),
        "owner_icons_resolved": bool(icon_evidence)
        and all(row.get("ok") is True for row in icon_evidence),
        "six_explicit_not_applicable_views": all(
            (before_root / f"{view}.png").is_file()
            and (after_root / f"{view}.png").is_file()
            for view in FULL_MODEL_VIEWS
        ),
    }
    if not all(gates.values()):
        raise RuntimeError(
            "Source-only equipment evidence did not satisfy its explicit gates."
        )
    return {
        "schema": EQUIPMENT_CAPTURE_SCHEMA,
        "status": "source_only_captured",
        "verdict": "UNREVIEWED",
        "render_verdict": "NOT_APPLICABLE_SOURCE_ONLY",
        "review_status": "pending_source_disposition_review",
        "identity": plan["identity"],
        "asset_id": plan["asset_id"],
        "resolution_status": plan["resolution_status"],
        "owners": list(_sequence(plan.get("owners"))),
        "owner_records": list(_sequence(plan.get("owner_records"))),
        "source_only_finding": finding,
        "renderer_path": "not_applicable_no_archive_geometry",
        "python_material_synthesis_used": False,
        "icons": icon_evidence,
        "icon_board": _file_evidence(icon_board, staging),
        "composites": composites,
        "technical_gates": gates,
    }


def _validate_native_manifest(
    manifest: Mapping[str, object],
    plan: Mapping[str, object],
) -> dict[str, bool]:
    conservation = _mapping(manifest.get("material_conservation"))
    native_contract = _mapping(manifest.get("native_preview_core"))
    parameters = _sequence(conservation.get("parameters"))
    declared = _safe_int(conservation.get("declared_parameter_count"), -1)
    transported = _safe_int(conservation.get("transported_parameter_count"), -1)
    resolved_textures = _safe_int(conservation.get("resolved_texture_count"), -1)
    unresolved_textures = _safe_int(conservation.get("unresolved_texture_count"), -1)
    declared_non_null_textures = sum(
        str(parameter.get("parameter_kind", "")) == "texture"
        and bool(str(parameter.get("texture_path", "") or ""))
        for parameter in parameters
    )
    findings = [str(value) for value in _sequence(conservation.get("findings"))]
    forbidden = ("cross-owner", "cross_owner", "layer-as-base", "layer_as_base")
    return {
        "preview_core_backend": native_contract.get("runtime_backend") == "native_cpp"
        and native_contract.get("python_fallback_allowed") is False
        and native_contract.get("material_graph_status") == "active",
        "preview_core_schema_8": _safe_int(manifest.get("schema_version"), -1)
        == EXPECTED_PREVIEW_CORE_SCHEMA,
        "material_graph_v4": _safe_int(manifest.get("material_graph_version"), -1)
        == EXPECTED_MATERIAL_GRAPH_VERSION,
        "material_semantics_v10": _safe_int(
            manifest.get("material_semantics_version"), -1
        )
        == EXPECTED_MATERIAL_SEMANTICS_VERSION,
        "source_identity_matches_primary": normalized_archive_key(
            manifest.get("source_path")
        )
        == normalized_archive_key(
            _mapping(_mapping(plan.get("primary_component")).get("entry")).get("path")
        ),
        "material_conservation": conservation.get("conserved") is True,
        "all_declared_texture_sources_resolved": unresolved_textures == 0
        and resolved_textures == declared_non_null_textures,
        "parameter_count_conserved": declared >= 0
        and declared == transported
        and declared == len(parameters),
        "component_scoped_material_identity": (
            _component_scoped_native_material_identity_complete(manifest)
        ),
        "no_material_conservation_findings": not findings,
        "no_cross_owner_or_layer_as_base": not any(
            token in finding.casefold() for finding in findings for token in forbidden
        ),
        "no_rejected_unsafe_material_fallback": not any(
            "fallback" in str(value).casefold()
            for value in _sequence(manifest.get("rejected_candidates"))
        ),
    }


def _validate_rust_package_manifest(
    manifest: Mapping[str, object], *, quality: str
) -> None:
    status = _mapping(manifest.get("texture_status"))
    graph = _mapping(manifest.get("preview_core_material_graph"))
    if manifest.get("schema") != "cdmw_rust_preview_package_v1":
        raise ValueError(f"Rust {quality} package schema is invalid.")
    if manifest.get("renderer") != "wgpu_d3d12_rust":
        raise ValueError(f"Rust {quality} package did not select D3D12 Rust.")
    if (
        str(status.get("quality", "")) != quality
        or str(graph.get("quality", "")) != quality
    ):
        raise ValueError(f"Rust package material quality is not {quality}.")
    if _safe_int(graph.get("graph_version"), -1) != EXPECTED_MATERIAL_GRAPH_VERSION:
        raise ValueError(f"Rust {quality} package did not preserve material graph v4.")
    if (
        _safe_int(graph.get("semantics_version"), -1)
        != EXPECTED_MATERIAL_SEMANTICS_VERSION
    ):
        raise ValueError(
            f"Rust {quality} package did not preserve material semantics v10."
        )


def _run_rust_audit_capture(
    helper: Path,
    manifest_path: Path,
    output_root: Path,
    *,
    full_model_only: bool,
    timeout_seconds: float,
) -> tuple[dict[str, object], dict[str, object]]:
    command = [
        str(helper),
        "--capture-cdmw-preview-session",
        str(manifest_path),
        "--capture-audit-output",
        str(output_root),
    ]
    if full_model_only:
        command.append("--capture-audit-full-model-only")
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    timeout = max(30.0, float(timeout_seconds))
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=helper.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    peak_private_bytes = 0
    peak_working_set_bytes = 0
    observed = psutil.Process(process.pid)
    deadline = started + timeout
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
            raise RuntimeError(
                f"Rust audit capture timed out after {timeout:.3f}s: {detail}"
            )
        time.sleep(0.005)
    stdout, stderr = process.communicate()
    process_wall_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if process.returncode != 0:
        detail = (stderr or stdout or "")[-4000:]
        raise RuntimeError(f"Rust audit capture exited {process.returncode}: {detail}")
    report = _read_json_object(
        output_root / "audit-report.json", label="Rust audit report"
    )
    if not _capture_report_ok(report, full_model_only=full_model_only):
        diagnostic = {
            "schema": report.get("schema"),
            "ok": report.get("ok"),
            "renderer": report.get("renderer"),
            "adapter": _mapping(report.get("adapter")),
            "full_model_only": report.get("full_model_only"),
            "capture_count": report.get("capture_count"),
            "material_indices": report.get("material_indices"),
            "dds_resources_uploaded_once_for_capture_set": report.get(
                "dds_resources_uploaded_once_for_capture_set"
            ),
            "source_dds": _mapping(report.get("source_dds")),
            "runtime_dds": _mapping(report.get("runtime_dds")),
        }
        raise RuntimeError(
            "Rust audit capture report failed its D3D12/frame contract: "
            + json.dumps(diagnostic, sort_keys=True)
        )
    if not _capture_source_manifest_matches(report, manifest_path):
        raise RuntimeError(
            "Rust audit capture report does not match its requested package manifest."
        )
    return report, {
        "process_wall_ms": process_wall_ms,
        "peak_private_bytes": peak_private_bytes,
        "peak_working_set_bytes": peak_working_set_bytes,
        "timed_out": False,
        "exit_code": int(process.returncode or 0),
    }


def _capture_phase_timings_ok(report: Mapping[str, object]) -> bool:
    phase = _mapping(report.get("phase_timings"))
    values = [
        _safe_float(phase.get(field), -1.0)
        for field in (
            "package_load_complete_ms",
            "renderer_device_ready_ms",
            "texture_resources_ready_ms",
            "first_textured_frame_ms",
            "audit_completion_ms",
        )
    ]
    return bool(
        phase.get("schema") == RUST_MATERIAL_PHASE_TIMINGS_SCHEMA
        and all(value >= 0.0 for value in values)
        and values == sorted(values)
    )


def _capture_source_manifest_matches(
    report: Mapping[str, object], manifest_path: Path
) -> bool:
    source = _mapping(report.get("source_manifest"))
    try:
        expected = manifest_path.resolve(strict=True)
        reported = Path(str(source.get("path", "") or "")).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return bool(
        reported == expected
        and _safe_int(source.get("bytes"), -1) == expected.stat().st_size
        and str(source.get("sha256", "") or "").casefold()
        == _sha256_file(expected)
    )


def _capture_report_ok(report: Mapping[str, object], *, full_model_only: bool) -> bool:
    captures = [_mapping(row) for row in _sequence(report.get("captures"))]
    expected_count = (
        len(FULL_MODEL_VIEWS)
        if full_model_only
        else len(FULL_MODEL_VIEWS) + 2 * len(_sequence(report.get("material_indices")))
    )
    names = [
        str(row.get("name", ""))
        for row in captures
        if row.get("capture_kind") == "full_model"
    ]
    frames_ok = True
    for capture in captures:
        frames = _mapping(capture.get("frames"))
        required_frames = ["textured", "base_color", "part_id"]
        if capture.get("capture_kind") == "material_region":
            required_frames.extend(["normal_map", "material_response", "layer_mask"])
        if any(
            _safe_int(_mapping(frames.get(key)).get("non_background_pixels"), 0) <= 0
            for key in required_frames
        ):
            frames_ok = False
            break
    adapter = _mapping(report.get("adapter"))
    source_dds = _mapping(report.get("source_dds"))
    runtime_dds = _mapping(report.get("runtime_dds"))
    return bool(
        report.get("schema") == RUST_AUDIT_CAPTURE_SCHEMA
        and report.get("ok") is True
        and report.get("renderer") == "wgpu_d3d12_rust"
        and str(adapter.get("backend", "")).casefold() == "dx12"
        and report.get("full_model_only") is full_model_only
        and report.get("dds_resources_uploaded_once_for_capture_set") is True
        and source_dds.get("available") is True
        and source_dds.get("each_source_binary_decoded_at_most_once") is True
        and source_dds.get("full_source_decode_complete") is True
        and runtime_dds.get("no_duplicate_upload_keys") is True
        and runtime_dds.get("upload_key") == "dds_sha256"
        and runtime_dds.get("role_specific_sampling_views_share_one_physical_upload")
        is True
        and runtime_dds.get("renderer_uploads_match_unique_binaries") is True
        and _safe_int(runtime_dds.get("duplicate_upload_key_count"), -1) == 0
        and _safe_int(runtime_dds.get("reported_gpu_resident_bytes"), -1) >= 0
        and _safe_int(report.get("capture_count"), -1) == expected_count
        and names == list(FULL_MODEL_VIEWS)
        and captures
        and frames_ok
        and all(
            _safe_int(row.get("dds_textures_uploaded"), -1) >= 0 for row in captures
        )
    )


def _report_dds_dedup_ok(report: Mapping[str, object]) -> bool:
    source = _mapping(report.get("source_dds"))
    runtime = _mapping(report.get("runtime_dds"))
    captures = [_mapping(row) for row in _sequence(report.get("captures"))]
    runtime_count = _safe_int(runtime.get("resource_count"), -1)
    logical_runtime_count = _safe_int(runtime.get("logical_resource_count"), -1)
    return bool(
        report.get("dds_resources_uploaded_once_for_capture_set") is True
        and source.get("each_source_binary_decoded_at_most_once") is True
        and source.get("full_source_decode_complete") is True
        and _safe_int(source.get("copied_source_dds_count"), -1)
        <= _safe_int(source.get("unique_source_dds_count"), -2)
        and runtime.get("no_duplicate_upload_keys") is True
        and runtime.get("upload_key") == "dds_sha256"
        and runtime.get("role_specific_sampling_views_share_one_physical_upload") is True
        and runtime.get("renderer_uploads_match_unique_binaries") is True
        and _safe_int(runtime.get("duplicate_upload_key_count"), -1) == 0
        and runtime_count >= 0
        and _safe_int(runtime.get("unique_binary_count"), -2) == runtime_count
        and logical_runtime_count >= runtime_count
        and captures
        and all(
            _safe_int(capture.get("dds_textures_uploaded"), -2) == runtime_count
            for capture in captures
        )
    )


def _component_scope_key(row: Mapping[str, object]) -> str:
    return normalized_archive_key(row.get("component_scope_id"))


def _component_owner_identity(
    row: Mapping[str, object],
) -> tuple[str, str, int]:
    return (
        _component_scope_key(row),
        str(row.get("owner_wrapper_item_id", "") or "").strip().casefold(),
        _safe_int(row.get("material_wrapper_index"), -1),
    )


def _component_texture_edge_identity(
    row: Mapping[str, object],
    *,
    descriptor: bool = False,
) -> tuple[str, str, int, str, str]:
    declared_path = (
        row.get("declared_texture_path") or row.get("archive_path")
        if descriptor
        else row.get("texture_path")
    )
    scope, owner, wrapper_index = _component_owner_identity(row)
    return (
        scope,
        owner,
        wrapper_index,
        str(row.get("parameter_name", "") or "").strip().casefold(),
        normalized_archive_key(declared_path),
    )


def _component_parameter_identity(
    row: Mapping[str, object],
) -> tuple[object, ...]:
    kind = str(row.get("parameter_kind", "") or "").strip().casefold()
    if kind == "texture":
        return _component_texture_edge_identity(row)
    scope, owner, wrapper_index = _component_owner_identity(row)
    value = row.get("integer_value")
    if value is None:
        value = row.get("numeric_value")
    if value is None:
        value = row.get("value", "")
    return (
        scope,
        owner,
        wrapper_index,
        kind,
        str(row.get("parameter_name", "") or "").strip().casefold(),
        str(row.get("tag_name", "") or "").strip().casefold(),
        str(row.get("string_item_id", "") or "").strip().casefold(),
        str(row.get("item_id", "") or "").strip().casefold(),
        _safe_int(row.get("index"), -1),
        str(value),
    )


def _require_component_parameter_identity(
    row: Mapping[str, object], *, label: str
) -> None:
    scope, owner, _wrapper_index = _component_owner_identity(row)
    parameter_name = str(row.get("parameter_name", "") or "").strip()
    if not scope:
        raise ValueError(f"{label} omitted component_scope_id.")
    if not owner:
        raise ValueError(f"{label} omitted owner_wrapper_item_id.")
    if not parameter_name:
        raise ValueError(f"{label} omitted parameter_name.")


def _batch_component_scope_key(batch: Mapping[str, object]) -> str:
    direct = normalized_archive_key(batch.get("component_scope_id"))
    if direct:
        return direct
    return normalized_archive_key(
        _mapping(batch.get("editor_identity")).get("component_scope_id")
    )


def _component_scoped_native_material_identity_complete(
    manifest: Mapping[str, object],
) -> bool:
    conservation = _mapping(manifest.get("material_conservation"))
    parameters = [
        _mapping(row) for row in _sequence(conservation.get("parameters"))
    ]
    parameter_identities: set[tuple[object, ...]] = set()
    texture_identities: set[tuple[str, str, int, str, str]] = set()
    owner_identities: set[tuple[str, str, int]] = set()
    for parameter in parameters:
        scope, owner, _wrapper_index = _component_owner_identity(parameter)
        if (
            not scope
            or not owner
            or not str(parameter.get("parameter_name", "") or "").strip()
        ):
            return False
        identity = _component_parameter_identity(parameter)
        if identity in parameter_identities:
            return False
        parameter_identities.add(identity)
        owner_identities.add(_component_owner_identity(parameter))
        if (
            str(parameter.get("parameter_kind", "")).casefold() == "texture"
            and normalized_archive_key(parameter.get("texture_path"))
        ):
            texture_identities.add(_component_texture_edge_identity(parameter))

    for raw_batch in _sequence(manifest.get("batches")):
        batch = _mapping(raw_batch)
        batch_scope = _batch_component_scope_key(batch)
        if not batch_scope:
            return False
        for raw_descriptor in _sequence(
            _mapping(batch.get("dds_textures")).get("material_inputs")
        ):
            descriptor = _mapping(raw_descriptor)
            scope, owner, _wrapper_index = _component_owner_identity(descriptor)
            if (
                not scope
                or scope != batch_scope
                or not owner
                or not str(descriptor.get("parameter_name", "") or "").strip()
            ):
                return False
            if _component_texture_edge_identity(
                descriptor, descriptor=True
            ) not in texture_identities:
                return False
        for raw_layer in _sequence(batch.get("material_layers")):
            layer = _mapping(raw_layer)
            owner = str(layer.get("owner_wrapper_item_id", "") or "").strip()
            if not owner:
                continue
            layer_scope = _component_scope_key(layer) or batch_scope
            if layer_scope != batch_scope:
                return False
            layer_identity = (
                layer_scope,
                owner.casefold(),
                _safe_int(layer.get("material_wrapper_index"), -1),
            )
            if layer_identity not in owner_identities:
                return False
    return True


def _publish_material_source_evidence(
    manifest: Mapping[str, object],
    *,
    source_cache_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    conservation = _mapping(manifest.get("material_conservation"))
    parameters = [
        dict(_mapping(row)) for row in _sequence(conservation.get("parameters"))
    ]
    parameter_identities: set[tuple[object, ...]] = set()
    for parameter in parameters:
        _require_component_parameter_identity(
            parameter, label="Preview Core conservation parameter"
        )
        identity = _component_parameter_identity(parameter)
        if identity in parameter_identities:
            raise ValueError(
                "Preview Core duplicated a component-scoped material parameter: "
                f"{identity}"
            )
        parameter_identities.add(identity)
    descriptors: dict[
        tuple[str, str, int, str, str],
        list[tuple[int, Mapping[str, object]]],
    ] = {}
    batches = [dict(_mapping(row)) for row in _sequence(manifest.get("batches"))]
    for batch in batches:
        batch_index = _safe_int(batch.get("index"), -1)
        batch_scope = _batch_component_scope_key(batch)
        if not batch_scope:
            raise ValueError(
                f"Preview Core batch {batch_index} omitted component_scope_id."
            )
        material_inputs = _sequence(
            _mapping(batch.get("dds_textures")).get("material_inputs")
        )
        for raw_descriptor in material_inputs:
            descriptor = _mapping(raw_descriptor)
            _require_component_parameter_identity(
                descriptor, label="Preview Core material input"
            )
            key = _component_texture_edge_identity(descriptor, descriptor=True)
            if key[0] != batch_scope:
                raise ValueError(
                    "Preview Core material input crossed component scope: "
                    f"batch={batch_scope}, input={key[0]}"
                )
            if not key[-1]:
                raise ValueError(
                    f"Preview Core material input omitted its declared path: {key}"
                )
            descriptors.setdefault(key, []).append((batch_index, descriptor))
    texture_rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str, int, str, str]] = set()
    for parameter in parameters:
        if (
            str(parameter.get("parameter_kind", "")) != "texture"
            or not normalized_archive_key(parameter.get("texture_path"))
        ):
            continue
        key = _component_texture_edge_identity(parameter)
        if key in seen_keys:
            raise ValueError(f"Preview Core duplicated a logical material key: {key}")
        seen_keys.add(key)
        matches = descriptors.get(key, [])
        resolved_source = Path(
            str(parameter.get("resolved_source_path", "") or "")
        )
        if not matches and not resolved_source.is_file():
            raise ValueError(
                f"Preview Core did not publish DDS bytes for logical edge: {key}"
            )
        batch_index, descriptor = matches[0] if matches else (-1, {})
        submesh_indices = sorted({index for index, _descriptor in matches})
        descriptor_source = Path(str(descriptor.get("source_path", "") or ""))
        source = resolved_source if resolved_source.is_file() else descriptor_source
        if not source.is_file():
            raise FileNotFoundError(f"Preview Core DDS source is missing: {source}")
        if parameter.get("texture_resolved") is not True:
            raise ValueError(f"Preview Core source row is not resolved: {key}")
        source_sha256 = _sha256_file(source)
        cache_path = source_cache_root / "dds" / f"{source_sha256}.dds"
        _publish_content_addressed_file(
            source, cache_path, expected_sha256=source_sha256
        )
        texture_rows.append(
            {
                "submesh_index": batch_index,
                "submesh_indices": submesh_indices,
                "source_path": str(cache_path),
                "native_source_path": str(source),
                "source_bytes": cache_path.stat().st_size,
                "source_sha256": source_sha256,
                "archive_path": str(parameter.get("texture_path", "") or ""),
                "declared_archive_path": str(
                    parameter.get("texture_path", "") or ""
                ),
                "resolved_archive_path": str(
                    parameter.get("resolved_archive_path", "")
                    or descriptor.get("archive_path", "")
                    or parameter.get("texture_path", "")
                    or ""
                ),
                "source_resolution": str(
                    parameter.get("source_resolution", "")
                    or descriptor.get("source_resolution", "")
                    or "legacy_batch_descriptor"
                ),
                "source_resolution_detail": str(
                    parameter.get("source_resolution_detail", "")
                    or descriptor.get("source_resolution_detail", "")
                    or ""
                ),
                "declared_source_missing": bool(
                    parameter.get("declared_source_missing") is True
                    or descriptor.get("declared_source_missing") is True
                ),
                "semantic": str(
                    parameter.get("semantic_type", "")
                    or descriptor.get("semantic_type", "")
                    or descriptor.get("slot", "")
                    or parameter.get("role", "")
                    or "material"
                ),
                "parameter_kind": parameter.get("parameter_kind"),
                "parameter_name": parameter.get("parameter_name"),
                "parameter_tag": parameter.get("tag_name"),
                "parameter_item_id": parameter.get("item_id"),
                "parameter_index": parameter.get("index"),
                "owner_slot_index": parameter.get("owner_slot_index"),
                "owner_wrapper_item_id": parameter.get("owner_wrapper_item_id"),
                "material_wrapper_index": parameter.get("material_wrapper_index"),
                "component_scope_id": parameter.get("component_scope_id"),
                "representation_sidecar_paths": list(
                    _sequence(parameter.get("representation_sidecar_paths"))
                ),
                "material_name": parameter.get("material_name"),
                "shader_family": parameter.get("shader_family"),
                "layer_role": parameter.get("layer_role"),
                "layer_channel": parameter.get("layer_channel"),
                "packed_channels": parameter.get("packed_channels")
                or descriptor.get("packed_channels"),
                "srgb_mode": parameter.get("srgb_mode")
                or descriptor.get("srgb_mode"),
                "logical_graph_edge": parameter.get("logical_graph_edge"),
                "binding_authority": str(parameter.get("status", "")),
                "binding_disposition": "logical_pac_texture_edge",
                "source_kind": str(
                    parameter.get("sidecar_kind", "")
                    or descriptor.get("sidecar_kind", "")
                ),
                "sidecar_path": parameter.get("sidecar_path"),
                "texture_resolved": parameter.get("texture_resolved"),
            }
        )
    unmatched_descriptors = set(descriptors).difference(seen_keys)
    if unmatched_descriptors:
        first = min(unmatched_descriptors)
        raise ValueError(
            "Preview Core published a renderer material input without a matching "
            f"component-scoped conservation edge: {first}"
        )
    if len(texture_rows) != _safe_int(conservation.get("resolved_texture_count"), -1):
        raise ValueError(
            "Logical PAC DDS edge count does not match Preview Core conservation."
        )

    by_batch_owner: dict[int, set[tuple[str, str, int]]] = {}
    for batch in batches:
        batch_index = _safe_int(batch.get("index"), -1)
        batch_scope = _batch_component_scope_key(batch)
        owners = by_batch_owner.setdefault(batch_index, set())
        for raw_descriptor in _sequence(
            _mapping(batch.get("dds_textures")).get("material_inputs")
        ):
            descriptor = _mapping(raw_descriptor)
            if str(descriptor.get("owner_wrapper_item_id", "") or ""):
                owners.add(_component_owner_identity(descriptor))
        for raw_layer in _sequence(batch.get("material_layers")):
            layer = _mapping(raw_layer)
            owner = str(layer.get("owner_wrapper_item_id", "") or "")
            if owner:
                layer_scope = _component_scope_key(layer) or batch_scope
                if layer_scope != batch_scope:
                    raise ValueError(
                        "Preview Core material layer crossed component scope: "
                        f"batch={batch_scope}, layer={layer_scope}"
                    )
                owners.add(
                    (
                        layer_scope,
                        owner.strip().casefold(),
                        _safe_int(layer.get("material_wrapper_index"), -1),
                    )
                )
        if not owners:
            local_index = _safe_int(
                _mapping(batch.get("editor_identity")).get(
                    "source_local_submesh_index"
                ),
                batch_index,
            )
            owners.update(
                _component_owner_identity(row)
                for row in parameters
                if _component_scope_key(row) == batch_scope
                and str(row.get("owner_wrapper_item_id", ""))
                and (
                    _safe_int(row.get("owner_slot_index"), -1) == local_index
                    or _safe_int(row.get("material_wrapper_index"), -1)
                    == local_index
                )
            )
    material_rows: list[dict[str, object]] = []
    for batch in batches:
        batch_index = _safe_int(batch.get("index"), -1)
        owners = by_batch_owner.get(batch_index, set())
        material_parameters = [
            row
            for row in parameters
            if _component_owner_identity(row) in owners
        ]
        component_scope_ids = sorted(
            {
                str(row.get("component_scope_id", "") or "")
                for row in material_parameters
                if str(row.get("component_scope_id", "") or "")
            },
            key=str.casefold,
        )
        owner_wrapper_item_ids = sorted(
            {
                str(row.get("owner_wrapper_item_id", "") or "")
                for row in material_parameters
                if str(row.get("owner_wrapper_item_id", "") or "")
            },
            key=str.casefold,
        )
        material_rows.append(
            {
                "submesh_index": batch_index,
                "component_scope_id": batch_scope,
                "material_name": str(batch.get("material_name", "") or ""),
                "shader_family": str(
                    _mapping(batch.get("native_material_hints")).get(
                        "shader_family", ""
                    )
                    or ""
                ),
                "parameters": {
                    "base_tint_color": list(_sequence(batch.get("base_color"))),
                    "roughness": batch.get("roughness"),
                    "metalness": batch.get("metalness"),
                    "specular": batch.get("specular"),
                    "height_scale": batch.get("height_scale"),
                },
                "pac_xml_parameters": material_parameters,
                "color_parameters": [
                    {
                        "name": row.get("parameter_name"),
                        "value": row.get("value"),
                    }
                    for row in material_parameters
                    if str(row.get("parameter_kind", "")) == "color"
                ],
                "source_contract": {
                    "schema": "cdmw_pac_material_graph_v4",
                    "material_semantics_version": EXPECTED_MATERIAL_SEMANTICS_VERSION,
                },
                "binding_conservation": {
                    "conserved": conservation.get("conserved") is True,
                    "parameter_count": len(material_parameters),
                    "logical_texture_edge_count": sum(
                        str(row.get("parameter_kind", "")) == "texture"
                        and bool(str(row.get("texture_path", "") or ""))
                        for row in material_parameters
                    ),
                    "resolved_texture_edge_count": sum(
                        str(row.get("parameter_kind", "")) == "texture"
                        and bool(str(row.get("texture_path", "") or ""))
                        and row.get("texture_resolved") is True
                        for row in material_parameters
                    ),
                    "unresolved_texture_edge_count": sum(
                        str(row.get("parameter_kind", "")) == "texture"
                        and bool(str(row.get("texture_path", "") or ""))
                        and row.get("texture_resolved") is not True
                        for row in material_parameters
                    ),
                    "component_scope_ids": component_scope_ids,
                    "owner_wrapper_item_ids": owner_wrapper_item_ids,
                    "exact_owner_identity": bool(owners)
                    and all(
                        _component_owner_identity(row) in owners
                        for row in material_parameters
                    ),
                },
            }
        )
    assigned_owners = (
        set().union(*by_batch_owner.values()) if by_batch_owner else set()
    )
    unassigned_parameters = [
        row
        for row in parameters
        if _component_owner_identity(row) not in assigned_owners
    ]
    return texture_rows, {
        "submeshes": material_rows,
        "parameters": parameters,
        "unassigned_parameters": unassigned_parameters,
    }


def _capture_plan_icons(
    plan: Mapping[str, object],
    *,
    source_cache_root: Path,
    memo: MutableMapping[str, dict[str, object]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for raw_icon in _sequence(plan.get("icons")):
        icon = _mapping(raw_icon)
        identity = normalized_archive_key(icon.get("identity"))
        cached = memo.get(identity)
        if cached is None:
            cached = _capture_icon(icon, source_cache_root=source_cache_root)
            memo[identity] = cached
        results.append({**cached, "owners": list(_sequence(icon.get("owners")))})
    return results


def _capture_icon(
    icon: Mapping[str, object], *, source_cache_root: Path
) -> dict[str, object]:
    entries = [_mapping(row) for row in _sequence(icon.get("entries"))]
    if not entries:
        return {
            "identity": icon.get("identity"),
            "ok": False,
            "error": "no resolved icon entry",
        }
    entry = archive_entry_from_worker(entries[0])
    payload, _decompressed, note = read_archive_entry_data(entry)
    payload = bytes(payload)
    source_sha256 = hashlib.sha256(payload).hexdigest()
    dds_path = source_cache_root / "icons" / "dds" / f"{source_sha256}.dds"
    if not dds_path.is_file():
        atomic_write_bytes(dds_path, payload)
    elif _sha256_file(dds_path) != source_sha256:
        raise ValueError(f"Content-addressed icon DDS cache collision: {dds_path}")
    png_path = source_cache_root / "icons" / "png" / f"{source_sha256}.png"
    if not png_path.is_file():
        preview = ensure_native_dds_preview_png(
            dds_path,
            max_dimension=512,
            slot_kind="base",
            srgb="auto",
            normal_space="auto",
            timeout_seconds=60.0,
        )
        if not Path(preview).is_file():
            raise RuntimeError(
                f"Icon DDS preview was not published: {icon.get('identity')}"
            )
        atomic_copy_file(preview, png_path)
    return {
        "identity": icon.get("identity"),
        "declared_name": icon.get("declared_name"),
        "ok": True,
        "archive_entry": dict(entries[0]),
        "source_dds": str(dds_path),
        "source_bytes": len(payload),
        "source_sha256": source_sha256,
        "decoded_png": str(png_path),
        "decoded_sha256": _sha256_file(png_path),
        "dds": _dds_header_row(dds_path),
        "read_note": str(note or ""),
    }


def _write_icon_board(
    path: Path,
    plan: Mapping[str, object],
    icon_rows: Sequence[Mapping[str, object]],
) -> Path:
    width = 1050
    row_height = 260
    height = 110 + max(1, len(icon_rows)) * row_height
    canvas = Image.new("RGB", (width, height), (17, 20, 25))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text(
        (16, 14),
        f"Equipment icon ownership | {plan['identity']}",
        fill=(240, 243, 248),
        font=font,
    )
    draw.text(
        (16, 38),
        f"owners={len(_sequence(plan.get('owners')))} icons={len(icon_rows)}",
        fill=(185, 200, 220),
        font=font,
    )
    for index, row in enumerate(
        icon_rows or ({"ok": False, "error": "no associated icon"},)
    ):
        y = 90 + index * row_height
        decoded = Path(str(row.get("decoded_png", "") or ""))
        if decoded.is_file():
            with Image.open(decoded) as source:
                image = source.convert("RGBA")
                image.thumbnail((230, 230))
                background = Image.new("RGBA", image.size, (35, 39, 46, 255))
                background.alpha_composite(image)
                canvas.paste(background.convert("RGB"), (16, y))
        else:
            draw.rectangle((16, y, 246, y + 230), outline=(220, 100, 100), width=2)
        draw.text(
            (270, y + 8),
            str(row.get("identity", "<missing icon>")),
            fill=(230, 235, 242),
            font=font,
        )
        draw.text(
            (270, y + 32),
            f"sha256={row.get('source_sha256', '')}",
            fill=(160, 176, 198),
            font=font,
        )
        dds = _mapping(row.get("dds"))
        draw.text(
            (270, y + 56),
            f"{dds.get('source_width', '?')}x{dds.get('source_height', '?')} mips={dds.get('source_mip_count', '?')} {dds.get('source_format', '')}",
            fill=(160, 176, 198),
            font=font,
        )
        draw.text(
            (270, y + 80),
            f"owner edges={len(_sequence(row.get('owners')))}",
            fill=(160, 176, 198),
            font=font,
        )
        if row.get("ok") is not True:
            draw.text(
                (270, y + 110),
                str(row.get("error", "icon unavailable")),
                fill=(255, 135, 120),
                font=font,
            )
    _atomic_save_png(canvas, path)
    canvas.close()
    return path


def _build_comparisons(
    plan: Mapping[str, object],
    staging: Path,
    before_root: Path,
    after_root: Path,
    source_boards: Mapping[str, object],
) -> dict[str, object]:
    comparisons: dict[str, str] = {}
    comparison_hashes: dict[str, str] = {}
    comparison_root = staging / "comparisons"
    for view in FULL_MODEL_VIEWS:
        output = comparison_root / f"{view}.png"
        _write_pair(
            before_root / "full-model" / f"{view}.png",
            after_root / "full-model" / f"{view}.png",
            output,
            left_label="Direct Rust (before)",
            right_label="Full material Rust (after)",
            footer=f"{plan['asset_id']} | {view}",
            strict=True,
        )
        comparisons[view] = str(output.relative_to(staging)).replace("\\", "/")
        comparison_hashes[view] = _sha256_file(output)
    contact_sheet = staging / "contact-sheet.png"
    _write_contact_sheet(
        tuple(comparison_root / f"{view}.png" for view in FULL_MODEL_VIEWS),
        contact_sheet,
        strict=True,
    )
    region_sheets = _build_region_review_sheets(staging, after_root, source_boards)
    return {
        "before_after": comparisons,
        "before_after_sha256": comparison_hashes,
        "contact_sheet": str(contact_sheet.relative_to(staging)).replace("\\", "/"),
        "contact_sheet_sha256": _sha256_file(contact_sheet),
        "material_region_sheets": region_sheets,
    }


def _build_region_review_sheets(
    staging: Path,
    after_root: Path,
    source_boards: Mapping[str, object],
) -> list[dict[str, object]]:
    report_path = after_root / "audit-report.json"
    if not report_path.is_file():
        return []
    report = _read_json_object(report_path, label="full Rust audit report")
    captures = [_mapping(row) for row in _sequence(report.get("captures"))]
    board_map = {
        _safe_int(_mapping(row).get("submesh_index"), -1): _mapping(row)
        for row in _sequence(source_boards.get("boards"))
    }
    results: list[dict[str, object]] = []
    for material_index in sorted(
        {
            _safe_int(row.get("material_index"), -1)
            for row in captures
            if row.get("capture_kind") == "material_region"
        }
    ):
        if material_index < 0:
            continue
        region_root = after_root / "material-regions" / f"material-{material_index:04d}"
        board = board_map.get(material_index, {})
        panels = [
            ("PAC / DDS source board", Path(str(board.get("path", "") or ""))),
            ("Full material region front", region_root / "front.png"),
            ("Full material region oblique", region_root / "oblique.png"),
            ("Base colour", region_root / "oblique-base-color.png"),
            ("Normal", region_root / "oblique-normal-map.png"),
            ("Material response", region_root / "oblique-material-response.png"),
            ("Layer mask", region_root / "oblique-layer-mask.png"),
            ("Part ID", region_root / "oblique-part-id.png"),
        ]
        output = (
            staging / "material-region-sheets" / f"material-{material_index:04d}.png"
        )
        _write_labeled_grid(
            panels,
            output,
            footer=f"material {material_index} | source authority and D3D12 diagnostics",
            strict=True,
        )
        results.append(
            {
                "material_index": material_index,
                "path": str(output.relative_to(staging)).replace("\\", "/"),
                "sha256": _sha256_file(output),
                "source_board_sha256": str(board.get("sha256", "") or ""),
            }
        )
    return results


def _write_source_only_panel(
    path: Path,
    plan: Mapping[str, object],
    finding: Mapping[str, object],
    *,
    phase: str,
) -> None:
    canvas = Image.new("RGB", (768, 768), (20, 24, 31))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.rectangle((20, 20, 748, 748), outline=(96, 150, 210), width=3)
    lines = [
        f"{phase} | source-only catalogue identity",
        str(plan.get("identity", "")),
        "No PAC geometry exists in the frozen name index or live archive.",
        "No substitute model was rendered.",
        f"finding={finding.get('finding', '')}",
        f"owner_prefab_hashes_empty={finding.get('owner_prefab_hashes_empty')}",
        f"owner_has_no_sibling_pac={finding.get('owner_has_no_sibling_pac')}",
        f"candidate tokens checked={len(_sequence(finding.get('candidate_path_tokens_checked')))}",
        f"candidate tokens present={len(_sequence(finding.get('candidate_path_tokens_present')))}",
    ]
    for index, line in enumerate(lines):
        draw.text((48, 60 + index * 42), line, fill=(232, 238, 246), font=font)
    _atomic_save_png(canvas, path)
    canvas.close()


def _relativize_source_board_manifest(
    source_boards: Mapping[str, object],
    staging: Path,
) -> dict[str, object]:
    def portable_boards(key: str) -> list[dict[str, object]]:
        boards: list[dict[str, object]] = []
        for raw in _sequence(source_boards.get(key)):
            row = dict(_mapping(raw))
            path = Path(str(row.get("path", "") or ""))
            if path.is_relative_to(staging):
                row["path"] = str(path.relative_to(staging)).replace("\\", "/")
            boards.append(row)
        return boards

    manifest_path = Path(str(source_boards.get("manifest_path", "") or ""))
    return {
        "schema": source_boards.get("schema"),
        "asset_id": source_boards.get("asset_id"),
        "path_base": "asset_root",
        "boards": portable_boards("boards"),
        "graph_boards": portable_boards("graph_boards"),
        "textures": list(_sequence(source_boards.get("textures"))),
        "materials": list(_sequence(source_boards.get("materials"))),
        "parameters": list(_sequence(source_boards.get("parameters"))),
        "unassigned_parameters": list(
            _sequence(source_boards.get("unassigned_parameters"))
        ),
        "manifest_path": str(manifest_path.relative_to(staging)).replace("\\", "/")
        if manifest_path.is_relative_to(staging)
        else str(manifest_path),
    }


def _graph_source_board_coverage_complete(
    source_boards: Mapping[str, object],
) -> bool:
    expected_edges: list[tuple[object, ...]] = []
    for raw in _sequence(source_boards.get("textures")):
        texture = _mapping(raw)
        submesh_indices = tuple(texture.get("submesh_indices", ()) or ())
        if not submesh_indices:
            submesh_indices = (_safe_int(texture.get("submesh_index"), -1),)
        if any(_safe_int(value, -1) >= 0 for value in submesh_indices):
            continue
        ordinal = _safe_int(texture.get("source_texture_ordinal"), -1)
        if ordinal < 0 or not _component_scope_key(texture):
            return False
        expected_edges.append(_graph_source_edge_identity(texture))

    actual_edges: list[tuple[object, ...]] = []
    graph_boards = _sequence(source_boards.get("graph_boards"))
    for graph_index, raw in enumerate(graph_boards):
        board = _mapping(raw)
        ordinals = [
            _safe_int(value, -1)
            for value in _sequence(board.get("source_texture_ordinals"))
        ]
        edge_ordinals = [
            _safe_int(_mapping(edge).get("source_texture_ordinal"), -1)
            for edge in _sequence(board.get("logical_edges"))
        ]
        logical_edges = [
            _mapping(edge) for edge in _sequence(board.get("logical_edges"))
        ]
        board_path = Path(str(board.get("path", "") or ""))
        if (
            not ordinals
            or any(value < 0 for value in ordinals)
            or any(not _component_scope_key(edge) for edge in logical_edges)
            or ordinals != edge_ordinals
            or len(ordinals) != _safe_int(board.get("texture_count"), -1)
            or _safe_int(board.get("graph_board_index"), -1) != graph_index
            or _safe_int(board.get("shard_index"), -1) != graph_index
            or _safe_int(board.get("shard_count"), -1) != len(graph_boards)
            or not board_path.is_file()
            or _sha256_file(board_path) != str(board.get("sha256", "") or "")
        ):
            return False
        actual_edges.extend(
            _graph_source_edge_identity(edge) for edge in logical_edges
        )

    return (
        actual_edges == expected_edges
        and len(actual_edges) == len(set(actual_edges))
    )


def _graph_source_edge_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _safe_int(row.get("source_texture_ordinal"), -1),
        normalized_archive_key(row.get("component_scope_id")),
        str(row.get("owner_wrapper_item_id", "") or ""),
        _safe_int(row.get("material_wrapper_index"), -1),
        str(row.get("parameter_name", "") or ""),
        normalized_archive_key(
            row.get("declared_archive_path") or row.get("archive_path")
        ),
        normalized_archive_key(
            row.get("resolved_archive_path") or row.get("archive_path")
        ),
        str(row.get("source_resolution", "") or ""),
        str(row.get("source_sha256", "") or ""),
    )


def _publish_content_addressed_file(
    source: Path, destination: Path, *, expected_sha256: str
) -> None:
    if destination.is_file():
        if _sha256_file(destination) != expected_sha256:
            raise ValueError(
                f"Content-addressed evidence cache collision: {destination}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_copy_file(source, destination)
    if _sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"Content-addressed evidence publication changed bytes: {destination}"
        )


def _file_evidence(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    root = root.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"Evidence file escaped the asset root: {resolved}")
    return {
        "path": str(resolved.relative_to(root)).replace("\\", "/"),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _valid_published_asset(
    path: Path,
    *,
    identity: str,
    expected_binaries: Mapping[str, object] | None = None,
    expected_census_identity: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    report_path = path / "asset-report.json"
    try:
        report = _read_json_object(report_path, label="asset report")
    except (OSError, ValueError):
        return None
    if report.get("schema") != EQUIPMENT_CAPTURE_SCHEMA:
        return None
    if normalized_archive_key(report.get("identity")) != normalized_archive_key(
        identity
    ):
        return None
    if report.get("status") not in {
        "captured",
        "source_only_captured",
        "source_only_reviewed",
        "reviewed",
    }:
        return None
    if not _valid_final_review_evidence(path, report):
        return None
    if expected_census_identity is not None and not _capture_identity_matches(
        _mapping(report.get("census_identity")), expected_census_identity
    ):
        return None
    if (
        report.get("status") in {"captured", "reviewed"}
        and expected_binaries is not None
        and not _capture_binaries_match(
            _mapping(report.get("capture_binaries")), expected_binaries
        )
    ):
        return None
    gates = _mapping(report.get("technical_gates"))
    if not gates or not all(value is True for value in gates.values()):
        return None
    return report


def _valid_final_review_evidence(
    asset_root: Path, report: Mapping[str, object]
) -> bool:
    """Reject legacy reviewed labels that have no hash-bound review decision."""

    status = str(report.get("status", "") or "")
    if status not in {"reviewed", "source_only_reviewed"}:
        return True
    verdict = str(report.get("verdict", "") or "")
    if status == "reviewed":
        if (
            verdict not in {"PASS", "LIMITATION"}
            or report.get("review_status") != "direct_visual_review_complete"
        ):
            return False
    elif (
        verdict not in {"EXCLUDED_CATALOGUE_DEFECT", "AUTHORED_EMPTY"}
        or report.get("review_status") != "source_disposition_review_complete"
    ):
        return False

    review = _mapping(report.get("review_evidence"))
    units = list(_sequence(review.get("units")))
    if review.get("schema") != EQUIPMENT_REVIEW_SUMMARY_SCHEMA or not units:
        return False
    census_root = asset_root.parent.parent.resolve()
    for key in ("review_index", "review_progress"):
        if not _review_file_matches(
            census_root,
            review.get(key),
            review.get(f"{key}_sha256"),
        ):
            return False

    unit_verdicts: list[str] = []
    for value in units:
        unit = _mapping(value)
        unit_id = str(unit.get("review_unit_id", "") or "")
        unit_verdict = str(unit.get("verdict", "") or "")
        outputs = list(_sequence(unit.get("reviewed_outputs")))
        if (
            not unit_id
            or unit.get("direct_image_inspection") is not True
            or not _review_file_matches(
                census_root, unit.get("page_path"), unit.get("page_sha256")
            )
            or not outputs
            or _canonical_json_sha256(outputs)
            != unit.get("reviewed_output_set_sha256")
            or not all(
                _review_file_matches(
                    census_root,
                    _mapping(output).get("path"),
                    _mapping(output).get("sha256"),
                )
                for output in outputs
            )
        ):
            return False
        unit_verdicts.append(unit_verdict)
        if status == "reviewed":
            if unit.get("kind") not in {"full_model", "material_region"} or (
                unit_verdict not in {"PASS", "LIMITATION"}
            ):
                return False
            continue
        disposition = _mapping(unit.get("disposition_evidence"))
        source_rows = list(_sequence(disposition.get("source_evidence")))
        facts = _mapping(disposition.get("source_facts"))
        if (
            len(units) != 1
            or unit.get("kind") != "source_disposition"
            or unit_verdict != verdict
            or disposition.get("schema")
            != EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA
            or disposition.get("review_unit_id") != unit_id
            or disposition.get("disposition") != verdict
            or not source_rows
            or not all(
                _review_file_matches(
                    census_root,
                    _mapping(source).get("path"),
                    _mapping(source).get("sha256"),
                )
                for source in source_rows
            )
            or disposition.get("source_evidence_binding_sha256")
            != _canonical_json_sha256(
                {"source_facts": dict(facts), "source_evidence": source_rows}
            )
            or not _accepted_source_disposition_facts(verdict, facts)
        ):
            return False
    combined = (
        "LIMITATION" if "LIMITATION" in unit_verdicts else "PASS"
    ) if status == "reviewed" else unit_verdicts[0]
    return combined == verdict


def _review_file_matches(root: Path, relative: object, expected_sha256: object) -> bool:
    try:
        path = (root / Path(str(relative or ""))).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    expected = str(expected_sha256 or "").casefold()
    return (
        path.is_file()
        and path.is_relative_to(root)
        and len(expected) == 64
        and _sha256_file(path).casefold() == expected
    )


def _accepted_source_disposition_facts(
    verdict: str, facts: Mapping[str, object]
) -> bool:
    if verdict == "EXCLUDED_CATALOGUE_DEFECT":
        return (
            _safe_int(facts.get("item_type"), -1) == 4_001
            and _safe_int(facts.get("equipment_slot_count"), -1) == 0
            and facts.get("icon_only_false_positive") is True
        )
    prefab = str(facts.get("authoritative_prefab", "") or "").replace("\\", "/")
    return (
        verdict == "AUTHORED_EMPTY"
        and prefab.casefold().split("/")[-1] == "cd_t9999_empty.prefab"
        and facts.get("authoritative_prefab_selection") is True
        and _safe_int(facts.get("model_edge_count"), -1) == 0
    )


def _capture_binaries_match(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    for key in ("preview_core", "rust_helper"):
        actual_row = _mapping(actual.get(key))
        expected_row = _mapping(expected.get(key))
        if (
            not expected_row.get("sha256")
            or actual_row.get("sha256") != expected_row.get("sha256")
            or _safe_int(actual_row.get("bytes"), -1)
            != _safe_int(expected_row.get("bytes"), -2)
        ):
            return False
    return True


def _load_capture_state(
    path: Path,
    resolution: Mapping[str, object],
    *,
    expected_census_identity: Mapping[str, object] | None = None,
    expected_capture_slice: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if path.is_file():
        state = _read_json_object(path, label="equipment capture state")
        if state.get("schema") != EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA:
            raise ValueError("Existing equipment capture state schema is incompatible.")
        if state.get("resolution_sha256") != resolution.get("resolution_sha256"):
            raise ValueError(
                "Existing equipment capture state belongs to another resolution."
            )
        if expected_census_identity is not None and not _capture_identity_matches(
            _mapping(state.get("census_identity")), expected_census_identity
        ):
            raise ValueError(
                "Existing equipment capture state belongs to another census run or "
                "capture harness. Use --no-resume to start fresh."
            )
        if expected_capture_slice is not None and dict(
            _mapping(state.get("capture_slice"))
        ) != dict(expected_capture_slice):
            raise ValueError(
                "Existing equipment capture state belongs to another catalogue slice. "
                "Use --no-resume to start fresh."
            )
        state.setdefault("assets", {})
        return state
    return _new_capture_state(
        resolution,
        census_identity=expected_census_identity or {},
        capture_slice=expected_capture_slice or {},
    )


def _new_capture_state(
    resolution: Mapping[str, object],
    *,
    census_identity: Mapping[str, object],
    capture_slice: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA,
        "resolution_sha256": resolution.get("resolution_sha256"),
        **_capture_identity_stamp(census_identity),
        "capture_slice": dict(capture_slice),
        "assets": {},
    }


def _checkpoint_asset(
    state: MutableMapping[str, object],
    plan: Mapping[str, object],
    *,
    status: str,
    error: str = "",
) -> None:
    assets = state.setdefault("assets", {})
    if not isinstance(assets, MutableMapping):
        raise TypeError("Equipment capture state assets must be an object.")
    assets[str(plan["identity"])] = {
        "ordinal": plan["ordinal"],
        "asset_id": plan["asset_id"],
        "status": status,
        "error": error,
        "updated_unix_ms": int(time.time() * 1000),
    }


def _write_capture_state(path: Path, state: Mapping[str, object]) -> None:
    assets = _mapping(state.get("assets"))
    counts: dict[str, int] = {}
    for value in assets.values():
        status = str(_mapping(value).get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    payload = {
        **dict(state),
        "counts": counts,
        "updated_unix_ms": int(time.time() * 1000),
    }
    atomic_write_text(path, _json_text(payload))


def _atomic_save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp.png")
    try:
        image.save(temporary, "PNG")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable or invalid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} root must be an object: {path}")
    return dict(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _normalize_census_run_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or any(
        not (character.isalnum() or character in "-_.:") for character in text
    ):
        raise ValueError(
            "Census run ID must be 1-128 letters, digits, hyphens, underscores, "
            "periods, or colons."
        )
    return text


def _resolve_census_run_id(
    state_path: Path,
    *,
    supplied: str | None,
    resume: bool,
) -> str:
    if supplied is not None:
        return _normalize_census_run_id(supplied)
    if resume and state_path.is_file():
        state = _read_json_object(state_path, label="equipment capture state")
        existing = str(state.get("census_run_id", "") or "").strip()
        if existing:
            return _normalize_census_run_id(existing)
    return uuid4().hex


def _capture_slice(start: int, end: int, total: int) -> dict[str, int]:
    if not (0 <= start <= end <= total):
        raise ValueError("Equipment capture slice is outside the frozen catalogue.")
    return {
        "start": start,
        "end": end,
        "count": end - start,
        "catalogue_count": total,
    }


def _capture_identity_stamp(
    census_identity: Mapping[str, object],
) -> dict[str, object]:
    if not census_identity:
        return {
            "census_run_id": "",
            "capture_harness": {},
            "census_identity": {},
        }
    return {
        "census_run_id": census_identity.get("census_run_id"),
        "capture_harness": dict(_mapping(census_identity.get("capture_harness"))),
        "capture_binaries": dict(_mapping(census_identity.get("capture_binaries"))),
        "census_identity": dict(census_identity),
    }


def _capture_identity_matches(
    actual: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    return (
        actual.get("schema") == EQUIPMENT_CAPTURE_IDENTITY_SCHEMA
        and expected.get("schema") == EQUIPMENT_CAPTURE_IDENTITY_SCHEMA
        and _canonical_json_sha256(actual) == _canonical_json_sha256(expected)
    )


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_float(value: object, fallback: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _safe_component(value: object) -> str:
    text = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in str(value or "")
    ).strip("-")
    return text[:100] or "asset"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def resolve_capture_binary_evidence(rust_helper: Path | str) -> dict[str, object]:
    native = find_native_preview_core_binary()
    helper = Path(rust_helper).expanduser().resolve(strict=True)
    if native is None:
        raise FileNotFoundError("cdmw-preview-core executable was not found")
    native = Path(native).resolve(strict=True)
    return {
        "preview_core": {
            "path": str(native),
            "bytes": native.stat().st_size,
            "sha256": _sha256_file(native),
        },
        "rust_helper": {
            "path": str(helper),
            "bytes": helper.stat().st_size,
            "sha256": _sha256_file(helper),
        },
    }


__all__ = [
    "EQUIPMENT_ARCHIVE_FINGERPRINT_SCHEMA",
    "EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA",
    "EQUIPMENT_CAPTURE_HARNESS_SCHEMA",
    "EQUIPMENT_CAPTURE_IDENTITY_SCHEMA",
    "EQUIPMENT_CAPTURE_MANIFEST_SCHEMA",
    "EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA",
    "EQUIPMENT_CAPTURE_SCHEMA",
    "FULL_MODEL_VIEWS",
    "build_capture_census_identity",
    "build_capture_harness_fingerprint",
    "build_equipment_capture_manifest",
    "build_equipment_capture_plans",
    "equipment_archive_paths_from_resolution",
    "load_equipment_capture_inputs",
    "resolve_capture_binary_evidence",
    "run_equipment_material_capture",
    "write_equipment_archive_fingerprint_snapshot",
]
