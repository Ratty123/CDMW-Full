"""Strict deterministic assembly for independently captured equipment shards."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_text
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
)
from tools.mesh_harness.equipment_material_capture import (
    EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_HARNESS_SCHEMA,
    EQUIPMENT_CAPTURE_IDENTITY_SCHEMA,
    EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA,
    EQUIPMENT_SOURCE_ONLY_SCHEMA,
    _canonical_json_sha256,
    _capture_identity_matches,
    _capture_identity_stamp,
    _capture_slice,
    _json_text,
    _mapping,
    _sequence,
    _sha256_file,
    _valid_published_asset,
    build_equipment_capture_manifest,
    build_equipment_capture_plans,
    load_equipment_capture_inputs,
)

EQUIPMENT_CAPTURE_ASSEMBLY_SCHEMA = "cdmw_equipment_material_capture_assembly_v1"
_COMPLETE_STATUSES = frozenset(
    {"captured", "reviewed", "source_only_captured", "source_only_reviewed"}
)


def assemble_equipment_material_capture(
    *,
    catalogue_path: Path | str,
    resolution_path: Path | str,
    shard_roots: Sequence[Path | str],
    output_root: Path | str,
) -> dict[str, object]:
    """Validate complete non-overlapping shards, then publish one new evidence root.

    The destination must not already exist. This prevents a stale asset directory from
    being accepted or overwritten and lets the fully staged tree publish in one rename.
    """

    catalogue_file = Path(catalogue_path).expanduser().resolve(strict=True)
    resolution_file = Path(resolution_path).expanduser().resolve(strict=True)
    destination = Path(output_root).expanduser().resolve()
    shards = tuple(
        Path(value).expanduser().resolve(strict=True) for value in shard_roots
    )
    if not shards or len(set(shards)) != len(shards):
        raise ValueError("Capture assembly requires unique shard roots.")
    if destination.exists():
        raise FileExistsError(
            "Capture assembly destination must be a new path; existing evidence is "
            f"never overwritten: {destination}"
        )
    for shard in shards:
        if not shard.is_dir():
            raise NotADirectoryError(shard)
        if (
            destination == shard
            or destination.is_relative_to(shard)
            or shard.is_relative_to(destination)
        ):
            raise ValueError("Capture assembly destination must not overlap a shard root.")

    catalogue, resolution = load_equipment_capture_inputs(
        catalogue_file, resolution_file
    )
    plans = build_equipment_capture_plans(catalogue, resolution)
    if len(plans) != EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT:
        raise ValueError("Capture assembly plan is not the exact frozen catalogue.")
    validated = _validate_capture_shards(
        shards,
        plans=plans,
        catalogue_path=catalogue_file,
        resolution_path=resolution_file,
        catalogue=catalogue,
        resolution=resolution,
    )
    census_identity = dict(validated["census_identity"])
    assets = list(validated["assets"])
    shard_rows = list(validated["shards"])

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.{uuid4().hex}.assembly-staging"
    if staging.exists():
        raise FileExistsError(staging)
    try:
        staged_assets = staging / "assets"
        staged_assets.mkdir(parents=True)
        frozen_inputs: dict[str, dict[str, object]] = {}
        for label, source in (
            ("catalogue", catalogue_file),
            ("resolution", resolution_file),
        ):
            target = staging / f"{label}.json"
            shutil.copy2(source, target)
            source_sha256 = _sha256_file(source)
            if _sha256_file(target) != source_sha256:
                raise ValueError(f"Copied frozen {label} changed bytes.")
            frozen_inputs[label] = {
                "path": target.name,
                "bytes": target.stat().st_size,
                "sha256": source_sha256,
            }
        state_assets: dict[str, dict[str, object]] = {}
        for row in assets:
            source = Path(str(row["source_asset_root"]))
            target = staged_assets / str(row["asset_id"])
            _require_regular_evidence_tree(source)
            shutil.copytree(source, target, copy_function=shutil.copy2)
            copied_report = target / "asset-report.json"
            if _sha256_file(copied_report) != row["report_sha256"]:
                raise ValueError(
                    f"Copied asset report changed bytes: {row['asset_id']}"
                )
            state_assets[str(row["identity"])] = {
                "ordinal": row["ordinal"],
                "asset_id": row["asset_id"],
                "status": row["status"],
                "error": "",
                "report_sha256": row["report_sha256"],
            }

        full_slice = _capture_slice(0, len(plans), len(plans))
        assembly_provenance = _assembly_provenance(
            census_identity=census_identity,
            assets=assets,
            shards=shard_rows,
        )
        assembly_provenance["frozen_inputs"] = frozen_inputs
        state = {
            "schema": EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA,
            "resolution_sha256": resolution.get("resolution_sha256"),
            **_capture_identity_stamp(census_identity),
            "capture_slice": full_slice,
            "assembly": assembly_provenance,
            "assets": state_assets,
            "counts": _status_counts(assets),
        }
        atomic_write_text(staging / "capture-run-state.json", _json_text(state))
        atomic_write_text(
            staging / "capture-binaries.json",
            _json_text(
                {
                    "schema": EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA,
                    **_capture_identity_stamp(census_identity),
                }
            ),
        )
        manifest = build_equipment_capture_manifest(
            staging,
            catalogue,
            resolution,
            plans,
            state=state,
            expected_binaries=_mapping(census_identity.get("capture_binaries")),
            expected_census_identity=census_identity,
            report_reference_root=destination,
        )
        atomic_write_text(staging / "capture-manifest.json", _json_text(manifest))

        if destination.exists():
            raise FileExistsError(
                "Capture assembly destination appeared during staging; refusing to "
                f"overwrite it: {destination}"
            )
        staging.rename(destination)
        return manifest
    except Exception:
        if staging.is_dir() and staging.parent == destination.parent:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_capture_shards(
    shard_roots: Sequence[Path],
    *,
    plans: Sequence[Mapping[str, object]],
    catalogue_path: Path,
    resolution_path: Path,
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
) -> dict[str, object]:
    expected_count = len(plans)
    expected_catalogue = {
        "schema": catalogue.get("schema"),
        "file_sha256": _sha256_file(catalogue_path),
        "selection_sha256": _mapping(catalogue.get("selection")).get(
            "selection_sha256"
        ),
    }
    expected_resolution = {
        "schema": resolution.get("schema"),
        "file_sha256": _sha256_file(resolution_path),
        "resolution_sha256": resolution.get("resolution_sha256"),
    }
    live_archive = dict(_mapping(resolution.get("live_archive")))
    expected_archive = {
        "live_archive": live_archive,
        "sha256": _canonical_json_sha256(live_archive),
    }
    common_identity: dict[str, object] | None = None
    ranges: list[tuple[int, int, Path, dict[str, object]]] = []
    assets_by_ordinal: dict[int, dict[str, object]] = {}

    for shard_root in shard_roots:
        manifest_path = shard_root / "capture-manifest.json"
        state_path = shard_root / "capture-run-state.json"
        binaries_path = shard_root / "capture-binaries.json"
        manifest = _read_object(manifest_path, "shard capture manifest")
        state = _read_object(state_path, "shard capture state")
        binaries_manifest = _read_object(
            binaries_path, "shard capture binary manifest"
        )
        if manifest.get("schema") != EQUIPMENT_CAPTURE_MANIFEST_SCHEMA:
            raise ValueError(f"Shard capture manifest schema mismatch: {shard_root}")
        if state.get("schema") != EQUIPMENT_CAPTURE_RUN_STATE_SCHEMA:
            raise ValueError(f"Shard capture state schema mismatch: {shard_root}")
        if (
            binaries_manifest.get("schema")
            != EQUIPMENT_CAPTURE_BINARY_MANIFEST_SCHEMA
        ):
            raise ValueError(f"Shard binary manifest schema mismatch: {shard_root}")
        identity = dict(_mapping(manifest.get("census_identity")))
        _validate_census_identity(
            identity,
            expected_catalogue=expected_catalogue,
            expected_resolution=expected_resolution,
            expected_archive=expected_archive,
        )
        if common_identity is None:
            common_identity = identity
        elif not _capture_identity_matches(identity, common_identity):
            raise ValueError(
                "Capture shards do not share the same catalogue, resolution, archive, "
                "binaries, harness, and census run ID."
            )
        for label, payload in (
            ("manifest", manifest),
            ("state", state),
            ("binary manifest", binaries_manifest),
        ):
            if not _capture_identity_matches(
                _mapping(payload.get("census_identity")), identity
            ):
                raise ValueError(f"Shard {label} census identity mismatch: {shard_root}")
            if payload.get("census_run_id") != identity.get("census_run_id"):
                raise ValueError(f"Shard {label} census run ID mismatch: {shard_root}")
            if _mapping(payload.get("capture_harness")) != _mapping(
                identity.get("capture_harness")
            ):
                raise ValueError(f"Shard {label} harness mismatch: {shard_root}")
            if _mapping(payload.get("capture_binaries")) != _mapping(
                identity.get("capture_binaries")
            ):
                raise ValueError(f"Shard {label} binary mismatch: {shard_root}")

        capture_slice = _validate_capture_slice(
            _mapping(manifest.get("capture_slice")), expected_count
        )
        if dict(_mapping(state.get("capture_slice"))) != capture_slice:
            raise ValueError(f"Shard state/manifest slice mismatch: {shard_root}")
        start = int(capture_slice["start"])
        end = int(capture_slice["end"])
        ranges.append((start, end, shard_root, manifest))

        rows = _sequence(manifest.get("assets"))
        if len(rows) != expected_count:
            raise ValueError(f"Shard manifest does not enumerate every ordinal: {shard_root}")
        actual_counts: dict[str, int] = {}
        state_assets = _mapping(state.get("assets"))
        expected_state_identities = {
            str(plans[index]["identity"]) for index in range(start, end)
        }
        if set(state_assets) != expected_state_identities:
            raise ValueError(
                f"Shard state is not exactly its declared catalogue slice: {shard_root}"
            )
        for ordinal, raw_row in enumerate(rows):
            row = _mapping(raw_row)
            plan = plans[ordinal]
            if (
                int(row.get("ordinal", -1)) != ordinal
                or row.get("asset_id") != plan.get("asset_id")
                or row.get("identity") != plan.get("identity")
            ):
                raise ValueError(
                    f"Shard catalogue identity mismatch at ordinal {ordinal}: {shard_root}"
                )
            status = str(row.get("status", "") or "")
            actual_counts[status] = actual_counts.get(status, 0) + 1
            if not start <= ordinal < end:
                if status != "missing" or row.get("report") or row.get("report_sha256"):
                    raise ValueError(
                        f"Shard publishes outside its declared slice at ordinal {ordinal}: "
                        f"{shard_root}"
                    )
                continue
            if ordinal in assets_by_ordinal:
                raise ValueError(f"Duplicate captured ordinal across shards: {ordinal}")
            if status not in _COMPLETE_STATUSES:
                raise ValueError(
                    f"Shard ordinal {ordinal} is not complete ({status}): {shard_root}"
                )
            state_row = _mapping(state_assets.get(str(plan["identity"])))
            if (
                int(state_row.get("ordinal", -1)) != ordinal
                or state_row.get("asset_id") != plan.get("asset_id")
                or str(state_row.get("status", "") or "") not in _COMPLETE_STATUSES
            ):
                raise ValueError(f"Shard state row mismatch at ordinal {ordinal}")
            asset_root = shard_root / "assets" / str(plan["asset_id"])
            report_path = asset_root / "asset-report.json"
            report_sha256 = str(row.get("report_sha256", "") or "")
            if not report_sha256 or _sha256_file(report_path) != report_sha256:
                raise ValueError(f"Shard report SHA mismatch at ordinal {ordinal}")
            report = _valid_published_asset(
                asset_root,
                identity=str(plan["identity"]),
                expected_binaries=_mapping(identity.get("capture_binaries")),
                expected_census_identity=identity,
            )
            if report is None:
                raise ValueError(f"Shard report is unreadable or invalid at ordinal {ordinal}")
            if (
                report.get("status") != status
                or report.get("asset_id") != plan.get("asset_id")
                or int(report.get("catalogue_ordinal", -1)) != ordinal
            ):
                raise ValueError(f"Shard report identity/status mismatch at ordinal {ordinal}")
            if status in {"source_only_captured", "source_only_reviewed"}:
                source_only_report = _read_object(
                    asset_root / "source-only-report.json", "source-only report"
                )
                if (
                    source_only_report.get("schema") != EQUIPMENT_SOURCE_ONLY_SCHEMA
                    or source_only_report.get("identity") != plan.get("identity")
                    or source_only_report.get("ok") is not True
                    or not _capture_identity_matches(
                        _mapping(source_only_report.get("census_identity")), identity
                    )
                ):
                    raise ValueError(
                        f"Source-only report identity mismatch at ordinal {ordinal}"
                    )
            assets_by_ordinal[ordinal] = {
                "ordinal": ordinal,
                "asset_id": plan["asset_id"],
                "identity": plan["identity"],
                "status": status,
                "report_sha256": report_sha256,
                "source_asset_root": str(asset_root),
            }
        if dict(_mapping(manifest.get("status_counts"))) != actual_counts:
            raise ValueError(f"Shard status counts do not match its asset rows: {shard_root}")

    ranges.sort(key=lambda row: (row[0], row[1], str(row[2]).casefold()))
    cursor = 0
    for start, end, shard_root, _manifest in ranges:
        if start != cursor or end <= start:
            raise ValueError(
                "Capture shard slices must be non-empty, non-overlapping, and cover "
                f"every ordinal; expected {cursor}, got {start}:{end} from {shard_root}"
            )
        cursor = end
    if cursor != expected_count or sorted(assets_by_ordinal) != list(
        range(expected_count)
    ):
        raise ValueError(
            f"Capture shard coverage is not exact 0..{expected_count - 1}."
        )
    if common_identity is None:
        raise ValueError("Capture assembly found no census identity.")

    shard_provenance = [
        {
            "shard_index": index,
            "source_root": str(shard_root),
            "capture_slice": dict(_mapping(manifest.get("capture_slice"))),
            "capture_manifest_sha256": _sha256_file(
                shard_root / "capture-manifest.json"
            ),
            "capture_state_sha256": _sha256_file(
                shard_root / "capture-run-state.json"
            ),
            "capture_binaries_manifest_sha256": _sha256_file(
                shard_root / "capture-binaries.json"
            ),
        }
        for index, (_start, _end, shard_root, manifest) in enumerate(ranges)
    ]
    return {
        "census_identity": common_identity,
        "assets": [assets_by_ordinal[index] for index in range(expected_count)],
        "shards": shard_provenance,
    }


def _validate_census_identity(
    identity: Mapping[str, object],
    *,
    expected_catalogue: Mapping[str, object],
    expected_resolution: Mapping[str, object],
    expected_archive: Mapping[str, object],
) -> None:
    if identity.get("schema") != EQUIPMENT_CAPTURE_IDENTITY_SCHEMA:
        raise ValueError("Shard census identity schema is incompatible.")
    if _mapping(identity.get("catalogue")) != expected_catalogue:
        raise ValueError("Shard census belongs to different catalogue bytes.")
    if _mapping(identity.get("resolution")) != expected_resolution:
        raise ValueError("Shard census belongs to different resolution bytes.")
    if _mapping(identity.get("archive")) != expected_archive:
        raise ValueError("Shard census belongs to a different live archive identity.")
    run_id = str(identity.get("census_run_id", "") or "")
    if not run_id:
        raise ValueError("Shard census has no run ID.")
    harness = _mapping(identity.get("capture_harness"))
    harness_payload = {
        "schema": harness.get("schema"),
        "files": list(_sequence(harness.get("files"))),
    }
    if (
        harness.get("schema") != EQUIPMENT_CAPTURE_HARNESS_SCHEMA
        or not harness_payload["files"]
        or harness.get("sha256") != _canonical_json_sha256(harness_payload)
    ):
        raise ValueError("Shard capture-harness fingerprint is invalid.")
    binaries = _mapping(identity.get("capture_binaries"))
    for name in ("preview_core", "rust_helper"):
        row = _mapping(binaries.get(name))
        if len(str(row.get("sha256", "") or "")) != 64 or int(
            row.get("bytes", 0) or 0
        ) <= 0:
            raise ValueError(f"Shard {name} binary evidence is incomplete.")


def _validate_capture_slice(
    value: Mapping[str, object], expected_count: int
) -> dict[str, int]:
    try:
        start = int(value.get("start", -1))
        end = int(value.get("end", -1))
        count = int(value.get("count", -1))
        catalogue_count = int(value.get("catalogue_count", -1))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Shard capture slice is invalid.") from exc
    expected = _capture_slice(start, end, expected_count)
    if count != expected["count"] or catalogue_count != expected_count:
        raise ValueError("Shard capture slice count does not match its bounds.")
    return expected


def _assembly_provenance(
    *,
    census_identity: Mapping[str, object],
    assets: Sequence[Mapping[str, object]],
    shards: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    coverage = [
        {
            "ordinal": row["ordinal"],
            "asset_id": row["asset_id"],
            "identity": row["identity"],
            "report_sha256": row["report_sha256"],
        }
        for row in assets
    ]
    deterministic_payload = {
        "schema": EQUIPMENT_CAPTURE_ASSEMBLY_SCHEMA,
        "census_run_id": census_identity.get("census_run_id"),
        "capture_harness_sha256": _mapping(
            census_identity.get("capture_harness")
        ).get("sha256"),
        "shards": [
            {
                "shard_index": row["shard_index"],
                "capture_slice": row["capture_slice"],
                "capture_manifest_sha256": row["capture_manifest_sha256"],
                "capture_state_sha256": row["capture_state_sha256"],
                "capture_binaries_manifest_sha256": row[
                    "capture_binaries_manifest_sha256"
                ],
            }
            for row in shards
        ],
        "coverage": coverage,
    }
    return {
        **deterministic_payload,
        "sha256": _canonical_json_sha256(deterministic_payload),
        "ordinal_coverage": {
            "first": 0,
            "last": len(assets) - 1,
            "count": len(assets),
            "sha256": _canonical_json_sha256(coverage),
        },
        "source_shards": list(shards),
        "source_cache": {
            "mode": "referenced_in_place",
            "copied": False,
            "required_shard_roots": [row["source_root"] for row in shards],
            "limitation": (
                "Asset reports retain absolute content-addressed source-cache paths "
                "under their source shard roots; keep those roots with the assembly."
            ),
        },
    }


def _require_regular_evidence_tree(root: Path) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Capture asset is not a regular directory: {root}")
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"Capture asset contains a non-regular path: {path}")


def _status_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable or invalid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} root must be an object: {path}")
    return dict(value)


__all__ = [
    "EQUIPMENT_CAPTURE_ASSEMBLY_SCHEMA",
    "assemble_equipment_material_capture",
]
