"""Direct-review atlas and verdict ledger for the frozen equipment census.

Capture and review deliberately remain separate states.  This module turns the
per-PAC evidence packages into bounded, hash-pinned atlas pages, records an
explicit decision for each PAC tile or visible material region, and only then
promotes covered asset reports from ``captured`` to ``reviewed``.  Source-only
catalogue rows require an independently hash-bound disposition and are never
substituted or silently counted as rendered passes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageFont

from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.item_model_family import find_part_stems
from cdmw.core.iteminfo_row import ItemInfoRow, parse_iteminfo_row
from cdmw.core.pappt_format import parse_pappt
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index
from cdmw.core.structured_binary_editor import parse_pabgh_table
from tools.mesh_harness.equipment_archive_resolution import (
    EQUIPMENT_AUDIT_MODEL_EXTENSIONS,
    EQUIPMENT_AUDIT_RESOLUTION_SCHEMA,
)
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
    EQUIPMENT_AUDIT_CATALOGUE_SCHEMA,
    EQUIPMENT_AUDIT_GENERATION_ID,
    EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    EQUIPMENT_AUDIT_ROOT_ID,
    EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION,
    normalize_archive_path,
)
from tools.mesh_harness.equipment_material_capture import (
    EQUIPMENT_CAPTURE_MANIFEST_SCHEMA,
    EQUIPMENT_CAPTURE_SCHEMA,
    FULL_MODEL_VIEWS,
    build_equipment_capture_manifest,
    build_equipment_capture_plans,
    load_equipment_capture_inputs,
)

EQUIPMENT_REVIEW_INDEX_SCHEMA = "cdmw_equipment_material_review_index_v2"
EQUIPMENT_REVIEW_PROGRESS_SCHEMA = "cdmw_equipment_material_review_progress_v2"
EQUIPMENT_REVIEW_SUMMARY_SCHEMA = "cdmw_equipment_material_review_summary_v2"
EQUIPMENT_REVIEW_LIMITATION_SCHEMA = "cdmw_equipment_material_review_limitation_v1"
EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA = (
    "cdmw_equipment_material_review_source_disposition_v1"
)
FULL_MODELS_PER_REVIEW_PAGE = 4
MATERIAL_REGIONS_PER_REVIEW_PAGE = 6
_RENDER_VERDICTS = frozenset({"PASS", "LIMITATION", "CONCERN", "FAIL"})
_SOURCE_DISPOSITION_VERDICTS = frozenset(
    {"EXCLUDED_CATALOGUE_DEFECT", "AUTHORED_EMPTY", "CONCERN", "FAIL"}
)
_SOURCE_COMMON_EVIDENCE_LABELS = (
    "frozen_catalogue",
    "live_resolution",
    "iteminfo_payload",
    "iteminfo_header",
)
_SOURCE_AUTHORED_EMPTY_EVIDENCE_LABELS = (
    *_SOURCE_COMMON_EVIDENCE_LABELS,
    "stringinfo_payload",
    "stringinfo_header",
    "active_part_prefab_table",
    "authoritative_prefab",
)
# A caller-provided checksum only proves that a file stayed unchanged.  These
# independently audited whole-file digests prove that it is the source used by
# this frozen census before the format parsers derive any accepted fact from it.
_AUTHORITATIVE_SOURCE_SHA256 = {
    "frozen_catalogue": (
        "875bfaf917cfe62ae5ac98fe33fb4c6b7a0fa6c9c2c86ff49be8a0076e25aed6"
    ),
    "live_resolution": (
        "6687b680b79dff868547cb39bb8484ce3abeb3ebf13fd26e61e39ab1930bcd20"
    ),
    "iteminfo_payload": (
        "51f87fb41046c1d8de9f84de6f11e51ba2a837205f121fa5825552c2e6948746"
    ),
    "iteminfo_header": (
        "2621a26d3432c02de4692361eba6f437b7b16d2233a6131ead280265fc52d627"
    ),
    "stringinfo_payload": (
        "1f6296d117e3e92ca4564b7a062059b58d538d14170e7285f8629ef706ac5b53"
    ),
    "stringinfo_header": (
        "85adb0fc8a817ee302ce4c8eaf35af89319753c3e8d20c089a495e6931ae1d18"
    ),
    "active_part_prefab_table": (
        "4b4dfe1e5445b8f8f5cc4048d6ef7cc2b8fc8271e5c267ce19ac6d70905d5312"
    ),
    "authoritative_prefab": (
        "894478418209655b0acf681aafb5ce8053d5e42fb54d99dbc53a882dc7a15399"
    ),
}
_AUTHORED_EMPTY_STEM = "cd_t9999_empty"
_AUTHORED_EMPTY_ITEM_TYPE = 108
_AUTHORED_EMPTY_EQUIP_TYPE_KEY = 0x3338361E
_REVIEW_VERDICTS = _RENDER_VERDICTS | _SOURCE_DISPOSITION_VERDICTS
_LIMITATION_FAITHFULNESS_FIELDS = (
    "color_source_faithful",
    "material_ownership_source_faithful",
    "implemented_surface_response_source_faithful",
)
_LIMITATION_MISSING_SOURCE_FIELDS = (
    "missing_geometry",
    "missing_pac",
    "missing_pac_xml",
    "missing_icon",
    "missing_dds",
)
_RENDER_REQUIRED_TECHNICAL_GATES = frozenset(
    {
        "preview_core_backend",
        "preview_core_schema_8",
        "material_graph_v4",
        "material_semantics_v10",
        "source_identity_matches_primary",
        "material_conservation",
        "all_declared_texture_sources_resolved",
        "parameter_count_conserved",
        "no_material_conservation_findings",
        "no_cross_owner_or_layer_as_base",
        "no_rejected_unsafe_material_fallback",
        "direct_capture",
        "full_capture",
        "all_logical_dds_edges_published",
        "source_board_parameter_inventory_complete",
        "source_board_graph_edges_complete",
        "source_board_visible_submeshes_complete",
        "source_dds_decoded",
        "owner_icons_resolved",
        "direct_dds_decode_upload_deduplicated",
        "full_dds_decode_upload_deduplicated",
        "performance_measurements_complete",
    }
)
_SOURCE_REQUIRED_TECHNICAL_GATES = frozenset(
    {
        "source_only_finding_present",
        "no_substituted_geometry",
        "owner_icons_resolved",
        "six_explicit_not_applicable_views",
    }
)


def build_equipment_review_index(
    evidence_root: Path | str,
    *,
    expected_asset_count: int = EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    full_models_per_page: int = FULL_MODELS_PER_REVIEW_PAGE,
    material_regions_per_page: int = MATERIAL_REGIONS_PER_REVIEW_PAGE,
) -> dict[str, object]:
    """Build deterministic review pages after technical capture is complete."""

    root = Path(evidence_root).expanduser().resolve(strict=True)
    capture_manifest_path = root / "capture-manifest.json"
    capture_manifest = _read_object(capture_manifest_path, "capture manifest")
    rows = _mapping_rows(capture_manifest, "assets")
    if (
        capture_manifest.get("schema") != EQUIPMENT_CAPTURE_MANIFEST_SCHEMA
        or capture_manifest.get("capture_complete") is not True
        or int(capture_manifest.get("failed_count", -1) or 0) != 0
        or int(capture_manifest.get("missing_count", -1) or 0) != 0
        or len(rows) != expected_asset_count
    ):
        raise ValueError(
            "Equipment review requires an exact, complete, failure-free capture manifest."
        )
    ordinals = [int(row.get("ordinal", -1)) for row in rows]
    if ordinals != list(range(expected_asset_count)):
        raise ValueError("Equipment capture manifest is not in exact catalogue order.")

    census_identity = dict(_mapping(capture_manifest.get("census_identity")))
    assets: list[dict[str, object]] = []
    full_tiles: list[dict[str, object]] = []
    region_tiles: list[dict[str, object]] = []
    source_tiles: list[dict[str, object]] = []
    capture_binaries = _mapping(capture_manifest.get("capture_binaries"))
    for row in rows:
        asset_id = str(row.get("asset_id", "") or "")
        identity = str(row.get("identity", "") or "")
        asset_root = root / "assets" / asset_id
        report_path = asset_root / "asset-report.json"
        report = _read_object(report_path, f"asset report {asset_id}")
        if (
            not asset_id
            or not identity
            or report.get("schema") != EQUIPMENT_CAPTURE_SCHEMA
            or str(report.get("identity", "") or "").casefold() != identity.casefold()
        ):
            raise ValueError(f"Equipment review asset identity mismatch: {asset_id}")
        status = str(report.get("status", "") or "")
        if status in {"source_only_captured", "source_only_reviewed"}:
            technical = _technical_evidence(
                asset_root,
                report,
                capture_binaries=capture_binaries,
                census_identity=census_identity,
                source_only=True,
            )
            composites = _mapping(report.get("composites"))
            contact_sheet = _verified_relative_file(
                asset_root,
                composites.get("contact_sheet"),
                composites.get("contact_sheet_sha256"),
                f"source-only comparison sheet {asset_id}",
            )
            comparison_sources = _verified_comparison_paths(
                asset_root, composites, asset_id=asset_id
            )
            source_report = _verified_relative_file(
                asset_root,
                "source-only-report.json",
                None,
                f"source-only report {asset_id}",
            )
            source_report_payload = _read_object(
                source_report, f"source-only report {asset_id}"
            )
            if (
                source_report_payload.get("schema")
                != "cdmw_equipment_source_only_capture_v1"
                or source_report_payload.get("ok") is not True
                or str(source_report_payload.get("identity", "") or "").casefold()
                != identity.casefold()
                or _mapping(source_report_payload.get("finding"))
                != _mapping(report.get("source_only_finding"))
                or (
                    census_identity
                    and _mapping(source_report_payload.get("census_identity"))
                    != census_identity
                )
            ):
                raise ValueError(
                    f"Source-only resolution report is not coherent for {asset_id}."
                )
            icon_board = _verified_relative_file(
                asset_root,
                _mapping(report.get("icon_board")).get("path"),
                _mapping(report.get("icon_board")).get("sha256"),
                f"source-only icon board {asset_id}",
            )
            review_unit = f"source-disposition:{asset_id}"
            outputs = [
                _reviewed_output(root, source_report, label="source_resolution_report"),
                _reviewed_output(root, icon_board, label="associated_icon_board"),
                _reviewed_output(
                    root, contact_sheet, label="no_substitute_comparison_sheet"
                ),
            ]
            outputs.extend(
                _reviewed_output(root, path, label=f"no_substitute_pair:{view}")
                for view, path in zip(FULL_MODEL_VIEWS, comparison_sources, strict=True)
            )
            source_tiles.append(
                {
                    "asset_id": asset_id,
                    "identity": identity,
                    "review_unit_id": review_unit,
                    "finding": dict(_mapping(report.get("source_only_finding"))),
                    "contact_sheet": _relative_to_root(contact_sheet, root),
                    "contact_sheet_sha256": _sha256_file(contact_sheet),
                    "icon_board": _relative_to_root(icon_board, root),
                    "icon_board_sha256": _sha256_file(icon_board),
                    "reviewed_outputs": outputs,
                    "reviewed_output_set_sha256": _canonical_json_sha256(outputs),
                    "_contact_sheet_path": contact_sheet,
                    "_icon_board_path": icon_board,
                }
            )
            assets.append(
                {
                    "ordinal": int(row["ordinal"]),
                    "asset_id": asset_id,
                    "identity": identity,
                    "source_only": True,
                    "capture_status": status,
                    "full_model_page": "",
                    "full_model_review_unit": "",
                    "source_disposition_page": "",
                    "source_disposition_review_unit": review_unit,
                    "material_regions": [],
                    "technical_evidence": technical,
                }
            )
            continue
        if status not in {"captured", "reviewed"}:
            raise ValueError(
                f"Equipment asset is not ready for review: {asset_id}={status}"
            )
        technical = _technical_evidence(
            asset_root,
            report,
            capture_binaries=capture_binaries,
            census_identity=census_identity,
            source_only=False,
        )
        composites = _mapping(report.get("composites"))
        contact_sheet = _verified_relative_file(
            asset_root,
            composites.get("contact_sheet"),
            composites.get("contact_sheet_sha256"),
            f"contact sheet {asset_id}",
        )
        comparison_sources = _verified_comparison_paths(
            asset_root, composites, asset_id=asset_id
        )
        direct_sources = [
            _verified_relative_file(
                asset_root,
                f"before/full-model/{view}.png",
                None,
                f"direct full-model {view} {asset_id}",
            )
            for view in FULL_MODEL_VIEWS
        ]
        full_sources = [
            _verified_relative_file(
                asset_root,
                f"after/full-model/{view}.png",
                None,
                f"final full-model {view} {asset_id}",
            )
            for view in FULL_MODEL_VIEWS
        ]
        source_board_manifest = _mapping(report.get("source_boards"))
        graph_boards = _verified_graph_boards(
            asset_root,
            root,
            source_board_manifest,
            asset_id=asset_id,
        )
        full_review_unit = f"whole-model:{asset_id}"
        full_outputs = [
            _reviewed_output(
                root,
                contact_sheet,
                label="paired_contact_sheet",
            )
        ]
        full_outputs.extend(
            _reviewed_output(root, path, label=f"paired_comparison:{view}")
            for view, path in zip(FULL_MODEL_VIEWS, comparison_sources, strict=True)
        )
        full_outputs.extend(
            _reviewed_output(
                root,
                path,
                label=f"direct:{view}",
            )
            for view, path in zip(FULL_MODEL_VIEWS, direct_sources, strict=True)
        )
        full_outputs.extend(
            _reviewed_output(
                root,
                path,
                label=f"full:{view}",
            )
            for view, path in zip(FULL_MODEL_VIEWS, full_sources, strict=True)
        )
        full_outputs.extend(
            _reviewed_output(
                root,
                path,
                label=f"logical_graph_source_board:{metadata['graph_board_index']:03d}",
            )
            for metadata, path in graph_boards
        )
        full_tile = {
            "asset_id": asset_id,
            "identity": identity,
            "review_unit_id": full_review_unit,
            "contact_sheet": _relative_to_root(contact_sheet, root),
            "contact_sheet_sha256": _sha256_file(contact_sheet),
            "comparison_views": [
                {
                    "view": view,
                    "path": _relative_to_root(path, root),
                    "sha256": _sha256_file(path),
                }
                for view, path in zip(FULL_MODEL_VIEWS, comparison_sources, strict=True)
            ],
            "direct_views": [
                {
                    "view": view,
                    "path": _relative_to_root(path, root),
                    "sha256": _sha256_file(path),
                }
                for view, path in zip(FULL_MODEL_VIEWS, direct_sources, strict=True)
            ],
            "final_views": [
                {
                    "view": view,
                    "path": _relative_to_root(path, root),
                    "sha256": _sha256_file(path),
                }
                for view, path in zip(FULL_MODEL_VIEWS, full_sources, strict=True)
            ],
            "graph_boards": [metadata for metadata, _path in graph_boards],
            "reviewed_outputs": full_outputs,
            "reviewed_output_set_sha256": _canonical_json_sha256(full_outputs),
            "material_region_count": 0,
            "_direct_source_paths": direct_sources,
            "_full_source_paths": full_sources,
        }
        region_rows = _mapping_rows(composites, "material_region_sheets")
        source_board_rows = _mapping_rows(source_board_manifest, "boards")
        visible_source_boards = {
            int(source.get("submesh_index", -1)): source for source in source_board_rows
        }
        source_board_indices = [
            int(source.get("submesh_index", -1)) for source in source_board_rows
        ]
        material_indices = [
            int(region.get("material_index", -1)) for region in region_rows
        ]
        if (
            not region_rows
            or material_indices != sorted(set(material_indices))
            or source_board_indices != sorted(set(source_board_indices))
            or set(material_indices) != set(visible_source_boards)
        ):
            raise ValueError(
                f"Material-region/source-board coverage is not exact for {asset_id}."
            )
        asset_regions: list[dict[str, object]] = []
        for region in region_rows:
            material_index = int(region["material_index"])
            sheet = _verified_relative_file(
                asset_root,
                region.get("path"),
                region.get("sha256"),
                f"material region {asset_id}:{material_index}",
            )
            source = visible_source_boards[material_index]
            source_board = _verified_relative_file(
                asset_root,
                source.get("path"),
                source.get("sha256"),
                f"source board {asset_id}:{material_index}",
            )
            if source_board in {path for _metadata, path in graph_boards}:
                raise ValueError(
                    f"Graph source board is falsely associated with visible region "
                    f"{asset_id}:{material_index}."
                )
            if str(region.get("source_board_sha256", "") or "") != _sha256_file(
                source_board
            ):
                raise ValueError(
                    f"Region/source-board hash link disagrees for {asset_id}:{material_index}."
                )
            tile = {
                "asset_id": asset_id,
                "identity": identity,
                "material_index": material_index,
                "review_unit_id": (f"material-region:{asset_id}:{material_index:04d}"),
                "path": _relative_to_root(sheet, root),
                "sha256": _sha256_file(sheet),
                "source_board": _relative_to_root(source_board, root),
                "source_board_sha256": _sha256_file(source_board),
                "reviewed_outputs": [
                    _reviewed_output(root, sheet, label="material_region_sheet"),
                    _reviewed_output(
                        root, source_board, label="pac_xml_dds_source_board"
                    ),
                ],
                "_source_path": sheet,
            }
            tile["reviewed_output_set_sha256"] = _canonical_json_sha256(
                tile["reviewed_outputs"]
            )
            region_tiles.append(tile)
            asset_regions.append(
                {
                    key: value
                    for key, value in tile.items()
                    if not key.startswith("_") and key not in {"identity"}
                }
            )
        full_tile["material_region_count"] = len(asset_regions)
        full_tiles.append(full_tile)
        assets.append(
            {
                "ordinal": int(row["ordinal"]),
                "asset_id": asset_id,
                "identity": identity,
                "source_only": False,
                "capture_status": status,
                "full_model_page": "",
                "full_model_review_unit": full_review_unit,
                "source_disposition_page": "",
                "source_disposition_review_unit": "",
                "material_regions": asset_regions,
                "technical_evidence": technical,
            }
        )

    atlas_root = root / "review" / "atlases"
    full_pages = _write_full_model_pages(
        root,
        atlas_root / "full-model",
        full_tiles,
        page_size=full_models_per_page,
    )
    region_pages = _write_region_pages(
        root,
        atlas_root / "material-regions",
        region_tiles,
        page_size=material_regions_per_page,
    )
    source_pages = _write_source_disposition_pages(
        root,
        atlas_root / "source-dispositions",
        source_tiles,
        page_size=full_models_per_page,
    )
    full_page_by_asset = {
        str(entry["asset_id"]): str(page["page_id"])
        for page in full_pages
        for entry in _mapping_rows(page, "entries")
    }
    region_page_by_key = {
        (str(entry["asset_id"]), int(entry["material_index"])): str(page["page_id"])
        for page in region_pages
        for entry in _mapping_rows(page, "entries")
    }
    source_page_by_asset = {
        str(entry["asset_id"]): str(page["page_id"])
        for page in source_pages
        for entry in _mapping_rows(page, "entries")
    }
    for asset in assets:
        if asset["source_only"] is True:
            asset["source_disposition_page"] = source_page_by_asset[
                str(asset["asset_id"])
            ]
            continue
        asset_id = str(asset["asset_id"])
        asset["full_model_page"] = full_page_by_asset[asset_id]
        for region in _mapping_rows(asset, "material_regions"):
            region["review_page"] = region_page_by_key[
                (asset_id, int(region["material_index"]))
            ]

    index = {
        "schema": EQUIPMENT_REVIEW_INDEX_SCHEMA,
        "capture_manifest": _relative_to_root(capture_manifest_path, root),
        "capture_manifest_sha256": _sha256_file(capture_manifest_path),
        "capture_binaries": dict(capture_binaries),
        "census_run_id": str(capture_manifest.get("census_run_id", "") or ""),
        "capture_harness": dict(_mapping(capture_manifest.get("capture_harness"))),
        "census_identity": census_identity,
        "asset_count": len(assets),
        "renderable_asset_count": len(full_tiles),
        "source_only_asset_count": sum(
            asset["source_only"] is True for asset in assets
        ),
        "material_region_count": len(region_tiles),
        "full_model_views": list(FULL_MODEL_VIEWS),
        "full_model_pages": full_pages,
        "material_region_pages": region_pages,
        "source_disposition_pages": source_pages,
        "assets": assets,
    }
    index_path = root / "review" / "review-index.json"
    atomic_write_text(index_path, _json_text(index))
    _reconcile_progress(root, index_path, full_pages + region_pages + source_pages)
    return index


def record_equipment_review_units(
    evidence_root: Path | str,
    review_unit_ids: Sequence[str],
    *,
    verdict: str,
    observations: str,
    limitation_evidence: Mapping[str, object] | None = None,
    disposition_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Record explicit decisions for named PAC tiles or visible material regions."""

    root = Path(evidence_root).expanduser().resolve(strict=True)
    index_path = root / "review" / "review-index.json"
    index = _read_object(index_path, "review index")
    _require_review_index(index)
    normalized_verdict = str(verdict or "").strip().upper()
    normalized_observations = str(observations or "").strip()
    if normalized_verdict not in _REVIEW_VERDICTS:
        raise ValueError(f"Unsupported review verdict: {verdict!r}")
    if not normalized_observations:
        raise ValueError("Direct review observations cannot be empty.")
    pages = {str(page["page_id"]): page for page in _all_pages(index)}
    units = _review_units(index)
    requested = tuple(
        dict.fromkeys(str(unit_id).strip() for unit_id in review_unit_ids)
    )
    if not requested or any(unit_id not in units for unit_id in requested):
        raise ValueError(
            "Every recorded review unit must name a PAC tile or material region "
            "in the current index."
        )
    progress_path = root / "review" / "review-progress.json"
    progress = _read_object(progress_path, "review progress")
    if progress.get("schema") != EQUIPMENT_REVIEW_PROGRESS_SCHEMA or progress.get(
        "review_index_sha256"
    ) != _sha256_file(index_path):
        raise ValueError("Review progress does not belong to the current review index.")
    decisions = dict(_mapping(progress.get("units")))
    reviewed_at = datetime.now(UTC).isoformat(timespec="seconds")
    for unit_id in requested:
        unit = units[unit_id]
        page = pages[str(unit["page_id"])]
        page_path = root / str(page["path"])
        if _sha256_file(page_path) != str(page["sha256"]):
            raise ValueError(
                "Review atlas page changed before inspection was recorded: "
                f"{page['page_id']}"
            )
        reviewed_outputs = _verified_unit_outputs(root, unit)
        is_source_disposition = unit["kind"] == "source_disposition"
        allowed_verdicts = (
            _SOURCE_DISPOSITION_VERDICTS if is_source_disposition else _RENDER_VERDICTS
        )
        if normalized_verdict not in allowed_verdicts:
            raise ValueError(
                f"Verdict {normalized_verdict} is not valid for {unit['kind']} "
                f"review unit {unit_id}."
            )
        normalized_limitation = None
        normalized_disposition = None
        if normalized_verdict == "LIMITATION":
            normalized_limitation = _validated_limitation_evidence(
                root,
                unit,
                limitation_evidence,
            )
        elif limitation_evidence is not None:
            raise ValueError(
                "Limitation evidence may only accompany a LIMITATION verdict."
            )
        if normalized_verdict in {
            "EXCLUDED_CATALOGUE_DEFECT",
            "AUTHORED_EMPTY",
        }:
            normalized_disposition = _validated_source_disposition_evidence(
                root,
                unit,
                normalized_verdict,
                disposition_evidence,
            )
        elif disposition_evidence is not None:
            raise ValueError(
                "Source disposition evidence may only accompany an accepted "
                "source-only disposition."
            )
        decision = {
            "review_unit_id": unit_id,
            "asset_id": unit["asset_id"],
            "kind": unit["kind"],
            "page_id": page["page_id"],
            "page_sha256": page["sha256"],
            "reviewed_outputs": reviewed_outputs,
            "reviewed_output_set_sha256": unit["reviewed_output_set_sha256"],
            "direct_image_inspection": True,
            "verdict": normalized_verdict,
            "observations": normalized_observations,
            "reviewer": "Codex direct visual inspection",
            "reviewed_at_utc": reviewed_at,
        }
        if normalized_limitation is not None:
            decision["limitation_evidence"] = normalized_limitation
        if normalized_disposition is not None:
            decision["disposition_evidence"] = normalized_disposition
        decisions[unit_id] = decision
    progress["units"] = decisions
    atomic_write_text(progress_path, _json_text(progress))
    return summarize_equipment_review(root)


def record_equipment_review_pages(
    evidence_root: Path | str,
    page_ids: Sequence[str],
    *,
    verdict: str,
    observations: str,
    limitation_evidence: Mapping[str, object] | None = None,
    disposition_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compatibility entry point restricted to one-review-unit atlas pages.

    A page containing multiple PAC tiles or material regions cannot be assigned a
    shared verdict.  Call :func:`record_equipment_review_units` with each explicit
    review-unit identity instead.
    """

    root = Path(evidence_root).expanduser().resolve(strict=True)
    index = _read_object(root / "review" / "review-index.json", "review index")
    _require_review_index(index)
    pages = {str(page["page_id"]): page for page in _all_pages(index)}
    requested_pages = tuple(dict.fromkeys(str(value).strip() for value in page_ids))
    if not requested_pages or any(page_id not in pages for page_id in requested_pages):
        raise ValueError("Every recorded review page must exist in the current index.")
    unit_ids: list[str] = []
    for page_id in requested_pages:
        entries = _mapping_rows(pages[page_id], "entries")
        if len(entries) != 1:
            raise ValueError(
                f"Atlas page {page_id} contains {len(entries)} independently reviewed "
                "tiles; record their review_unit_id values explicitly."
            )
        unit_ids.append(str(entries[0]["review_unit_id"]))
    return record_equipment_review_units(
        root,
        unit_ids,
        verdict=verdict,
        observations=observations,
        limitation_evidence=limitation_evidence,
        disposition_evidence=disposition_evidence,
    )


def summarize_equipment_review(evidence_root: Path | str) -> dict[str, object]:
    """Compute exact asset/region review coverage without promoting reports."""

    root = Path(evidence_root).expanduser().resolve(strict=True)
    index_path = root / "review" / "review-index.json"
    progress_path = root / "review" / "review-progress.json"
    index = _read_object(index_path, "review index")
    progress = _read_object(progress_path, "review progress")
    _require_review_index(index)
    if progress.get("schema") != EQUIPMENT_REVIEW_PROGRESS_SCHEMA or progress.get(
        "review_index_sha256"
    ) != _sha256_file(index_path):
        raise ValueError("Review progress does not belong to the current review index.")
    pages = {str(page["page_id"]): page for page in _all_pages(index)}
    units = _review_units(index)
    decisions = _mapping(progress.get("units"))
    unit_verdicts = {
        unit_id: _valid_unit_decision(
            root,
            unit,
            pages[str(unit["page_id"])],
            _mapping(decisions.get(unit_id)),
        )
        for unit_id, unit in units.items()
    }
    unit_counts = {
        key: sum(verdict == key for verdict in unit_verdicts.values())
        for key in (
            "PASS",
            "LIMITATION",
            "EXCLUDED_CATALOGUE_DEFECT",
            "AUTHORED_EMPTY",
            "CONCERN",
            "FAIL",
            "UNREVIEWED",
        )
    }
    page_counts: dict[str, int] = {}
    for page in pages.values():
        verdict = _combined_verdict(
            tuple(
                unit_verdicts[str(entry["review_unit_id"])]
                for entry in _mapping_rows(page, "entries")
            )
        )
        page_counts[verdict] = page_counts.get(verdict, 0) + 1

    asset_rows: list[dict[str, object]] = []
    for asset in _mapping_rows(index, "assets"):
        asset_id = str(asset["asset_id"])
        if asset.get("source_only") is True:
            source_unit_id = str(asset["source_disposition_review_unit"])
            status = unit_verdicts[source_unit_id]
            full_verdict = "NOT_RENDERED_SOURCE_DISPOSITION"
            region_verdicts: list[str] = []
            source_disposition_verdict = status
        else:
            full_unit_id = str(asset["full_model_review_unit"])
            full_verdict = unit_verdicts[full_unit_id]
            region_verdicts = []
            for region in _mapping_rows(asset, "material_regions"):
                region_verdicts.append(unit_verdicts[str(region["review_unit_id"])])
            status = _combined_verdict((full_verdict, *region_verdicts))
            source_disposition_verdict = "NOT_APPLICABLE_RENDERED"
        asset_rows.append(
            {
                "ordinal": int(asset["ordinal"]),
                "asset_id": asset_id,
                "identity": asset["identity"],
                "verdict": status,
                "full_model_verdict": full_verdict,
                "material_region_verdicts": region_verdicts,
                "source_disposition_verdict": source_disposition_verdict,
            }
        )
    verdict_counts = {
        key: sum(row["verdict"] == key for row in asset_rows)
        for key in ("PASS", "CONCERN", "FAIL", "UNREVIEWED")
    }
    limitation_count = sum(row["verdict"] == "LIMITATION" for row in asset_rows)
    excluded_count = sum(
        row["verdict"] == "EXCLUDED_CATALOGUE_DEFECT" for row in asset_rows
    )
    authored_empty_count = sum(row["verdict"] == "AUTHORED_EMPTY" for row in asset_rows)
    accepted_count = (
        verdict_counts["PASS"]
        + limitation_count
        + excluded_count
        + authored_empty_count
    )
    no_open_findings = (
        verdict_counts["CONCERN"] == 0
        and verdict_counts["FAIL"] == 0
        and verdict_counts["UNREVIEWED"] == 0
        and unit_counts["UNREVIEWED"] == 0
    )
    production_census_shape_ok = True
    if int(index["asset_count"]) == EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT:
        production_census_shape_ok = (
            int(index["renderable_asset_count"]) == 2_054
            and int(index["source_only_asset_count"]) == 3
            and verdict_counts["PASS"] == 2_054
            and excluded_count == 2
            and authored_empty_count == 1
        )
    summary = {
        "schema": EQUIPMENT_REVIEW_SUMMARY_SCHEMA,
        "ok": accepted_count == int(index["asset_count"])
        and no_open_findings
        and production_census_shape_ok,
        "review_index_sha256": _sha256_file(index_path),
        "census_run_id": str(index.get("census_run_id", "") or ""),
        "capture_harness": dict(_mapping(index.get("capture_harness"))),
        "census_identity": dict(_mapping(index.get("census_identity"))),
        "asset_count": int(index["asset_count"]),
        "renderable_asset_count": int(index["renderable_asset_count"]),
        "rendered_pass_count": verdict_counts["PASS"],
        "source_only_asset_count": int(index["source_only_asset_count"]),
        "material_region_count": int(index["material_region_count"]),
        "page_count": len(pages),
        "page_counts": page_counts,
        "review_unit_count": len(units),
        "unit_counts": unit_counts,
        "verdict_counts": verdict_counts,
        "limitation_count": limitation_count,
        "excluded_catalogue_defect_count": excluded_count,
        "authored_empty_count": authored_empty_count,
        "reviewed_count": accepted_count,
        "unreviewed_count": verdict_counts["UNREVIEWED"],
        "concern_count": verdict_counts["CONCERN"],
        "fail_count": verdict_counts["FAIL"],
        "assets": asset_rows,
    }
    atomic_write_text(root / "review" / "review-summary.json", _json_text(summary))
    return summary


def finalize_equipment_review(
    evidence_root: Path | str,
    catalogue_path: Path | str,
    resolution_path: Path | str,
) -> dict[str, object]:
    """Promote only fully inspected and explicitly accepted asset reports."""

    root = Path(evidence_root).expanduser().resolve(strict=True)
    summary = summarize_equipment_review(root)
    if summary.get("ok") is not True:
        raise ValueError(
            "Equipment review cannot finalize with FAIL, CONCERN, unreviewed "
            "units, or unsupported source-only dispositions."
        )
    index_path = root / "review" / "review-index.json"
    progress_path = root / "review" / "review-progress.json"
    index = _read_object(index_path, "review index")
    progress = _read_object(progress_path, "review progress")
    pages = {str(page["page_id"]): page for page in _all_pages(index)}
    units = _review_units(index)
    decisions = _mapping(progress.get("units"))
    summary_assets = {
        str(row["asset_id"]): row for row in _mapping_rows(summary, "assets")
    }
    for asset in _mapping_rows(index, "assets"):
        asset_id = str(asset["asset_id"])
        report_path = root / "assets" / asset_id / "asset-report.json"
        report = _read_object(report_path, f"asset report {asset_id}")
        if report.get("schema") != EQUIPMENT_CAPTURE_SCHEMA:
            raise ValueError(
                f"Asset report schema changed before review finalization: {asset_id}"
            )
        if asset.get("source_only") is True:
            unit_ids = [str(asset["source_disposition_review_unit"])]
            report["status"] = "source_only_reviewed"
            report["review_status"] = "source_disposition_review_complete"
        else:
            unit_ids = [str(asset["full_model_review_unit"])] + [
                str(region["review_unit_id"])
                for region in _mapping_rows(asset, "material_regions")
            ]
            report["status"] = "reviewed"
            report["review_status"] = "direct_visual_review_complete"
        report["verdict"] = summary_assets[asset_id]["verdict"]
        report["review_evidence"] = {
            "schema": EQUIPMENT_REVIEW_SUMMARY_SCHEMA,
            "review_index": "review/review-index.json",
            "review_index_sha256": _sha256_file(index_path),
            "review_progress": "review/review-progress.json",
            "review_progress_sha256": _sha256_file(progress_path),
            "units": [
                {
                    "review_unit_id": unit_id,
                    "kind": units[unit_id]["kind"],
                    "page_id": units[unit_id]["page_id"],
                    "page_path": pages[str(units[unit_id]["page_id"])]["path"],
                    "page_sha256": pages[str(units[unit_id]["page_id"])]["sha256"],
                    "reviewed_outputs": _mapping(decisions[unit_id])[
                        "reviewed_outputs"
                    ],
                    "reviewed_output_set_sha256": _mapping(decisions[unit_id])[
                        "reviewed_output_set_sha256"
                    ],
                    "verdict": _mapping(decisions[unit_id])["verdict"],
                    "observations": _mapping(decisions[unit_id])["observations"],
                    "direct_image_inspection": True,
                    **(
                        {
                            "limitation_evidence": dict(
                                _mapping(
                                    _mapping(decisions[unit_id]).get(
                                        "limitation_evidence"
                                    )
                                )
                            )
                        }
                        if _mapping(decisions[unit_id]).get("limitation_evidence")
                        else {}
                    ),
                    **(
                        {
                            "disposition_evidence": dict(
                                _mapping(
                                    _mapping(decisions[unit_id]).get(
                                        "disposition_evidence"
                                    )
                                )
                            )
                        }
                        if _mapping(decisions[unit_id]).get("disposition_evidence")
                        else {}
                    ),
                }
                for unit_id in unit_ids
            ],
        }
        atomic_write_text(report_path, _json_text(report))

    catalogue, resolution = load_equipment_capture_inputs(
        catalogue_path, resolution_path
    )
    plans = build_equipment_capture_plans(catalogue, resolution)
    manifest = build_equipment_capture_manifest(
        root,
        catalogue,
        resolution,
        plans,
        expected_binaries=_mapping(index.get("capture_binaries")),
        expected_census_identity=_mapping(index.get("census_identity")),
    )
    atomic_write_text(root / "capture-manifest.json", _json_text(manifest))
    if manifest.get("ok") is not True:
        raise ValueError(
            "Final review did not produce a 2,057/2,057 reviewed manifest."
        )
    summary = {
        **summary,
        "capture_manifest_sha256": _sha256_file(root / "capture-manifest.json"),
        "finalized": True,
    }
    atomic_write_text(root / "review" / "review-summary.json", _json_text(summary))
    return summary


def _technical_evidence(
    asset_root: Path,
    report: Mapping[str, object],
    *,
    capture_binaries: Mapping[str, object],
    census_identity: Mapping[str, object],
    source_only: bool,
) -> dict[str, object]:
    gates = _mapping(report.get("technical_gates"))
    required_gates = (
        _SOURCE_REQUIRED_TECHNICAL_GATES
        if source_only
        else _RENDER_REQUIRED_TECHNICAL_GATES
    )
    if (
        not gates
        or not required_gates.issubset(gates)
        or not all(value is True for value in gates.values())
    ):
        raise ValueError(f"Technical capture gate failed for {asset_root.name}.")
    if census_identity and _mapping(report.get("census_identity")) != census_identity:
        raise ValueError(f"Capture census identity changed for {asset_root.name}.")
    if source_only:
        icon = _verified_evidence_row(
            asset_root, report.get("icon_board"), "source-only icon board"
        )
        return {
            "technical_gates": dict(gates),
            "source_only_finding": dict(_mapping(report.get("source_only_finding"))),
            "icon_board": icon,
            "auto_accepted": False,
        }
    if (
        report.get("renderer_path")
        != "native_preview_core_to_direct_and_full_rust_to_wgpu_d3d12"
        or report.get("python_material_synthesis_used") is not False
        or _mapping(report.get("capture_binaries")) != capture_binaries
    ):
        raise ValueError(
            f"Production renderer/binary contract failed for {asset_root.name}."
        )
    before = _verified_evidence_row(
        asset_root, report.get("before_report"), "before report"
    )
    after = _verified_evidence_row(
        asset_root, report.get("after_report"), "after report"
    )
    icon = _verified_evidence_row(asset_root, report.get("icon_board"), "icon board")
    return {
        "technical_gates": dict(gates),
        "renderer_path": report["renderer_path"],
        "python_material_synthesis_used": False,
        "before_report": before,
        "after_report": after,
        "icon_board": icon,
        "logical_texture_edge_count": int(
            report.get("logical_texture_edge_count", 0) or 0
        ),
    }


def _verified_evidence_row(
    asset_root: Path,
    value: object,
    label: str,
) -> dict[str, object]:
    row = _mapping(value)
    path = _verified_relative_file(
        asset_root, row.get("path"), row.get("sha256"), label
    )
    if int(row.get("bytes", -1)) != path.stat().st_size:
        raise ValueError(f"Evidence byte count disagrees for {label}: {path}")
    return {
        "path": str(row["path"]),
        "bytes": int(row["bytes"]),
        "sha256": str(row["sha256"]),
    }


def _verified_comparison_paths(
    asset_root: Path,
    composites: Mapping[str, object],
    *,
    asset_id: str,
) -> list[Path]:
    paths = _mapping(composites.get("before_after"))
    hashes = _mapping(composites.get("before_after_sha256"))
    if set(paths) != set(FULL_MODEL_VIEWS) or set(hashes) != set(FULL_MODEL_VIEWS):
        raise ValueError(
            f"Before/direct to after/full comparison coverage is not exact for {asset_id}."
        )
    return [
        _verified_relative_file(
            asset_root,
            paths.get(view),
            hashes.get(view),
            f"paired comparison {view} {asset_id}",
        )
        for view in FULL_MODEL_VIEWS
    ]


def _verified_graph_boards(
    asset_root: Path,
    evidence_root: Path,
    source_boards: Mapping[str, object],
    *,
    asset_id: str,
) -> list[tuple[dict[str, object], Path]]:
    rows = _mapping_rows(source_boards, "graph_boards")
    indices = [int(row.get("graph_board_index", -1)) for row in rows]
    if indices != list(range(len(rows))):
        raise ValueError(
            f"Graph source-board order is not deterministic for {asset_id}."
        )
    verified: list[tuple[dict[str, object], Path]] = []
    seen_paths: set[Path] = set()
    all_ordinals: list[int] = []
    for graph_index, row in enumerate(rows):
        if (
            int(row.get("shard_index", -1)) != graph_index
            or int(row.get("shard_count", -1)) != len(rows)
        ):
            raise ValueError(
                f"Graph source-board shard metadata disagrees for {asset_id}."
            )
        texture_count = int(row.get("texture_count", -1))
        raw_ordinals = row.get("source_texture_ordinals")
        if not isinstance(raw_ordinals, Sequence) or isinstance(
            raw_ordinals, (str, bytes)
        ):
            raise TypeError(
                f"Graph source-board texture ordinals are missing for {asset_id}."
            )
        ordinals = [int(value) for value in raw_ordinals]
        raw_edges = row.get("logical_edges")
        if (
            texture_count <= 0
            or len(ordinals) != texture_count
            or ordinals != sorted(set(ordinals))
            or not isinstance(raw_edges, Sequence)
            or isinstance(raw_edges, (str, bytes))
            or any(not isinstance(edge, Mapping) for edge in raw_edges)
            or len(raw_edges) != texture_count
            or [
                int(_mapping(edge).get("source_texture_ordinal", -1))
                for edge in raw_edges
            ]
            != ordinals
        ):
            raise ValueError(
                f"Graph source-board texture binding is incomplete for {asset_id}."
            )
        path = _verified_relative_file(
            asset_root,
            row.get("path"),
            row.get("sha256"),
            f"graph source board {asset_id}:{graph_index}",
        )
        if path in seen_paths:
            raise ValueError(f"Graph source-board path is duplicated for {asset_id}.")
        seen_paths.add(path)
        all_ordinals.extend(ordinals)
        verified.append(
            (
                {
                    "graph_board_index": graph_index,
                    "shard_index": graph_index,
                    "shard_count": len(rows),
                    "path": _relative_to_root(path, evidence_root),
                    "sha256": _sha256_file(path),
                    "texture_count": texture_count,
                    "source_texture_ordinals": ordinals,
                },
                path,
            )
        )
    if all_ordinals != sorted(set(all_ordinals)):
        raise ValueError(
            f"Graph source-board texture ordinals overlap or are unordered for {asset_id}."
        )
    return verified


def _write_full_model_pages(
    root: Path,
    destination: Path,
    tiles: Sequence[Mapping[str, object]],
    *,
    page_size: int,
) -> list[dict[str, object]]:
    if page_size <= 0 or page_size > 4:
        raise ValueError("Full-model review pages support one to four assets.")
    destination.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, object]] = []
    for page_index, start in enumerate(range(0, len(tiles), page_size)):
        chunk = tiles[start : start + page_size]
        page_id = f"full-model-{page_index:04d}"
        path = destination / f"{page_id}.png"
        _render_full_model_page(chunk, path)
        pages.append(
            {
                "page_id": page_id,
                "kind": "full_model",
                "path": _relative_to_root(path, root),
                "sha256": _sha256_file(path),
                "entries": [
                    {
                        "asset_id": tile["asset_id"],
                        "identity": tile["identity"],
                        "review_unit_id": tile["review_unit_id"],
                        "contact_sheet": tile["contact_sheet"],
                        "contact_sheet_sha256": tile["contact_sheet_sha256"],
                        "comparison_views": tile["comparison_views"],
                        "direct_views": tile["direct_views"],
                        "final_views": tile["final_views"],
                        "graph_boards": tile["graph_boards"],
                        "reviewed_outputs": tile["reviewed_outputs"],
                        "reviewed_output_set_sha256": tile[
                            "reviewed_output_set_sha256"
                        ],
                        "material_region_count": tile["material_region_count"],
                    }
                    for tile in chunk
                ],
            }
        )
    return pages


def _render_full_model_page(
    tiles: Sequence[Mapping[str, object]], output: Path
) -> None:
    columns = 2
    cell_width = 1_536
    cell_height = 1_060
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), (11, 14, 18))
    draw = ImageDraw.Draw(canvas)
    label_font = _font(22)
    view_font = _font(15)
    for tile_index, tile in enumerate(tiles):
        cell_x = (tile_index % columns) * cell_width
        cell_y = (tile_index // columns) * cell_height
        draw.rectangle(
            (cell_x, cell_y, cell_x + cell_width - 1, cell_y + cell_height - 1),
            outline=(74, 86, 101),
            width=2,
        )
        draw.text(
            (cell_x + 14, cell_y + 12),
            f"{tile['review_unit_id']} | {tile['identity']} | "
            f"regions {tile['material_region_count']}",
            fill=(236, 240, 246),
            font=label_font,
        )
        direct_paths = tuple(tile.get("_direct_source_paths", ()) or ())
        full_paths = tuple(tile.get("_full_source_paths", ()) or ())
        for view_index, (view, direct_source, full_source) in enumerate(
            zip(FULL_MODEL_VIEWS, direct_paths, full_paths, strict=True)
        ):
            slot_width = cell_width // 3
            slot_height = 496
            slot_x = cell_x + (view_index % 3) * slot_width
            slot_y = cell_y + 55 + (view_index // 3) * slot_height
            draw.text(
                (slot_x + 10, slot_y + 6),
                view,
                fill=(190, 205, 224),
                font=view_font,
            )
            half_width = slot_width // 2
            draw.line(
                (
                    slot_x + half_width,
                    slot_y + 24,
                    slot_x + half_width,
                    slot_y + slot_height,
                ),
                fill=(52, 61, 74),
                width=1,
            )
            for phase_index, (phase, source) in enumerate(
                (("DIRECT", direct_source), ("FULL", full_source))
            ):
                phase_x = slot_x + phase_index * half_width
                draw.text(
                    (phase_x + 10, slot_y + 27),
                    phase,
                    fill=(146, 206, 232) if phase_index == 0 else (235, 181, 104),
                    font=view_font,
                )
                with Image.open(Path(source)) as opened:
                    image = opened.convert("RGB")
                image.thumbnail(
                    (half_width - 16, slot_height - 68),
                    Image.Resampling.LANCZOS,
                )
                canvas.paste(
                    image,
                    (
                        phase_x + (half_width - image.width) // 2,
                        slot_y + 55 + (slot_height - 55 - image.height) // 2,
                    ),
                )
                image.close()
    _atomic_save_png(canvas, output)
    canvas.close()


def _write_region_pages(
    root: Path,
    destination: Path,
    tiles: Sequence[Mapping[str, object]],
    *,
    page_size: int,
) -> list[dict[str, object]]:
    if page_size <= 0 or page_size > 6:
        raise ValueError("Material-region review pages support one to six regions.")
    destination.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, object]] = []
    for page_index, start in enumerate(range(0, len(tiles), page_size)):
        chunk = tiles[start : start + page_size]
        page_id = f"material-regions-{page_index:05d}"
        path = destination / f"{page_id}.png"
        _render_region_page(chunk, path)
        pages.append(
            {
                "page_id": page_id,
                "kind": "material_regions",
                "path": _relative_to_root(path, root),
                "sha256": _sha256_file(path),
                "entries": [
                    {
                        key: value
                        for key, value in tile.items()
                        if not key.startswith("_") and key not in {"identity"}
                    }
                    for tile in chunk
                ],
            }
        )
    return pages


def _render_region_page(tiles: Sequence[Mapping[str, object]], output: Path) -> None:
    columns = 3
    cell_width = 1_300
    cell_height = 1_520
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), (11, 14, 18))
    draw = ImageDraw.Draw(canvas)
    font = _font(20)
    for tile_index, tile in enumerate(tiles):
        cell_x = (tile_index % columns) * cell_width
        cell_y = (tile_index // columns) * cell_height
        draw.rectangle(
            (cell_x, cell_y, cell_x + cell_width - 1, cell_y + cell_height - 1),
            outline=(74, 86, 101),
            width=2,
        )
        draw.text(
            (cell_x + 12, cell_y + 10),
            str(tile["review_unit_id"]),
            fill=(236, 240, 246),
            font=font,
        )
        with Image.open(Path(str(tile["_source_path"]))) as opened:
            image = opened.convert("RGB")
        image.thumbnail((cell_width - 18, cell_height - 52), Image.Resampling.LANCZOS)
        canvas.paste(
            image,
            (
                cell_x + (cell_width - image.width) // 2,
                cell_y + 46 + (cell_height - 46 - image.height) // 2,
            ),
        )
        image.close()
    _atomic_save_png(canvas, output)
    canvas.close()


def _write_source_disposition_pages(
    root: Path,
    destination: Path,
    tiles: Sequence[Mapping[str, object]],
    *,
    page_size: int,
) -> list[dict[str, object]]:
    if page_size <= 0 or page_size > 4:
        raise ValueError("Source-disposition pages support one to four census rows.")
    destination.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, object]] = []
    for page_index, start in enumerate(range(0, len(tiles), page_size)):
        chunk = tiles[start : start + page_size]
        page_id = f"source-dispositions-{page_index:04d}"
        path = destination / f"{page_id}.png"
        _render_source_disposition_page(chunk, path)
        pages.append(
            {
                "page_id": page_id,
                "kind": "source_disposition",
                "path": _relative_to_root(path, root),
                "sha256": _sha256_file(path),
                "entries": [
                    {
                        key: value
                        for key, value in tile.items()
                        if not key.startswith("_")
                    }
                    for tile in chunk
                ],
            }
        )
    return pages


def _render_source_disposition_page(
    tiles: Sequence[Mapping[str, object]], output: Path
) -> None:
    columns = 2
    cell_width = 1_536
    cell_height = 1_060
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), (11, 14, 18))
    draw = ImageDraw.Draw(canvas)
    label_font = _font(20)
    detail_font = _font(15)
    for tile_index, tile in enumerate(tiles):
        cell_x = (tile_index % columns) * cell_width
        cell_y = (tile_index // columns) * cell_height
        draw.rectangle(
            (cell_x, cell_y, cell_x + cell_width - 1, cell_y + cell_height - 1),
            outline=(120, 93, 55),
            width=2,
        )
        draw.text(
            (cell_x + 14, cell_y + 12),
            str(tile["review_unit_id"]),
            fill=(244, 222, 181),
            font=label_font,
        )
        draw.text(
            (cell_x + 14, cell_y + 40),
            f"{tile['identity']} | NO RENDERED PAC - explicit disposition required",
            fill=(230, 232, 236),
            font=detail_font,
        )
        finding = _mapping(tile.get("finding"))
        draw.text(
            (cell_x + 14, cell_y + 65),
            f"finding={str(finding.get('finding', '') or '')[:150]}",
            fill=(188, 197, 209),
            font=detail_font,
        )
        panels = (
            ("SOURCE RESOLUTION / NO-SUBSTITUTE BOARD", tile["_contact_sheet_path"]),
            ("ASSOCIATED ICONS", tile["_icon_board_path"]),
        )
        panel_widths = (1_010, 498)
        panel_x = cell_x + 14
        for (label, source), panel_width in zip(panels, panel_widths, strict=True):
            draw.text(
                (panel_x + 6, cell_y + 92),
                label,
                fill=(170, 202, 226),
                font=detail_font,
            )
            with Image.open(Path(str(source))) as opened:
                image = opened.convert("RGB")
            image.thumbnail((panel_width - 12, 918), Image.Resampling.LANCZOS)
            canvas.paste(
                image,
                (
                    panel_x + (panel_width - image.width) // 2,
                    cell_y + 124 + (918 - image.height) // 2,
                ),
            )
            image.close()
            panel_x += panel_width
    _atomic_save_png(canvas, output)
    canvas.close()


def _reconcile_progress(
    root: Path,
    index_path: Path,
    pages: Sequence[Mapping[str, object]],
) -> None:
    progress_path = root / "review" / "review-progress.json"
    previous = (
        _read_object(progress_path, "review progress")
        if progress_path.is_file()
        else {}
    )
    previous_units = (
        _mapping(previous.get("units"))
        if previous.get("schema") == EQUIPMENT_REVIEW_PROGRESS_SCHEMA
        else {}
    )
    retained: dict[str, object] = {}
    page_map = {str(page["page_id"]): page for page in pages}
    for unit_id, unit in _review_units_from_pages(pages).items():
        decision = _mapping(previous_units.get(unit_id))
        if (
            _valid_unit_decision(
                root,
                unit,
                page_map[str(unit["page_id"])],
                decision,
            )
            != "UNREVIEWED"
        ):
            retained[unit_id] = dict(decision)
    progress = {
        "schema": EQUIPMENT_REVIEW_PROGRESS_SCHEMA,
        "review_index": "review/review-index.json",
        "review_index_sha256": _sha256_file(index_path),
        "units": retained,
    }
    atomic_write_text(progress_path, _json_text(progress))


def _valid_unit_decision(
    root: Path,
    unit: Mapping[str, object],
    page: Mapping[str, object],
    decision: Mapping[str, object],
) -> str:
    page_path = root / str(page.get("path", "") or "")
    if (
        not page_path.is_file()
        or _sha256_file(page_path) != str(page.get("sha256", "") or "")
        or decision.get("review_unit_id") != unit.get("review_unit_id")
        or decision.get("page_id") != page.get("page_id")
        or decision.get("page_sha256") != page.get("sha256")
        or decision.get("direct_image_inspection") is not True
        or decision.get("verdict") not in _REVIEW_VERDICTS
        or not str(decision.get("observations", "") or "").strip()
    ):
        return "UNREVIEWED"
    verdict = str(decision["verdict"])
    allowed = (
        _SOURCE_DISPOSITION_VERDICTS
        if unit.get("kind") == "source_disposition"
        else _RENDER_VERDICTS
    )
    if verdict not in allowed:
        return "UNREVIEWED"
    try:
        outputs = _verified_unit_outputs(root, unit)
        decision_outputs = _mapping_rows(decision, "reviewed_outputs")
        if decision_outputs != outputs or decision.get(
            "reviewed_output_set_sha256"
        ) != unit.get("reviewed_output_set_sha256"):
            return "UNREVIEWED"
        if verdict == "LIMITATION":
            normalized_limitation = _validated_limitation_evidence(
                root,
                unit,
                _mapping(decision.get("limitation_evidence")),
            )
            if _mapping(decision.get("limitation_evidence")) != normalized_limitation:
                return "UNREVIEWED"
        if verdict in {"EXCLUDED_CATALOGUE_DEFECT", "AUTHORED_EMPTY"}:
            normalized_disposition = _validated_source_disposition_evidence(
                root,
                unit,
                verdict,
                _mapping(decision.get("disposition_evidence")),
            )
            if _mapping(decision.get("disposition_evidence")) != normalized_disposition:
                return "UNREVIEWED"
    except (OSError, TypeError, ValueError):
        return "UNREVIEWED"
    return verdict


def _combined_verdict(verdicts: Sequence[str]) -> str:
    if not verdicts:
        return "UNREVIEWED"
    if "FAIL" in verdicts:
        return "FAIL"
    if "CONCERN" in verdicts:
        return "CONCERN"
    if "UNREVIEWED" in verdicts:
        return "UNREVIEWED"
    if "LIMITATION" in verdicts:
        return "LIMITATION"
    accepted = set(verdicts)
    if len(accepted) == 1:
        return next(iter(accepted))
    return "ACCEPTED_MIXED"


def _require_review_index(index: Mapping[str, object]) -> None:
    if index.get("schema") != EQUIPMENT_REVIEW_INDEX_SCHEMA:
        raise ValueError("Equipment review index schema is incompatible.")
    if int(index.get("asset_count", 0) or 0) <= 0:
        raise ValueError("Equipment review index is empty.")


def _all_pages(index: Mapping[str, object]) -> list[Mapping[str, object]]:
    pages = (
        _mapping_rows(index, "full_model_pages")
        + _mapping_rows(index, "material_region_pages")
        + _mapping_rows(index, "source_disposition_pages")
    )
    page_ids = [str(page.get("page_id", "") or "") for page in pages]
    if not all(page_ids) or len(page_ids) != len(set(page_ids)):
        raise ValueError("Equipment review page identities are not unique.")
    return pages


def _review_units(index: Mapping[str, object]) -> dict[str, dict[str, object]]:
    return _review_units_from_pages(_all_pages(index))


def _review_units_from_pages(
    pages: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    units: dict[str, dict[str, object]] = {}
    for page in pages:
        page_id = str(page.get("page_id", "") or "")
        kind = str(page.get("kind", "") or "")
        if kind not in {"full_model", "material_regions", "source_disposition"}:
            raise ValueError(f"Unknown equipment review page kind: {kind!r}")
        for entry in _mapping_rows(page, "entries"):
            unit_id = str(entry.get("review_unit_id", "") or "")
            if not unit_id or unit_id in units:
                raise ValueError("Equipment review-unit identities are not unique.")
            outputs = _mapping_rows(entry, "reviewed_outputs")
            output_set_sha256 = str(entry.get("reviewed_output_set_sha256", "") or "")
            if not outputs or _canonical_json_sha256(outputs) != output_set_sha256:
                raise ValueError(
                    f"Review output binding is incomplete for {unit_id or page_id}."
                )
            units[unit_id] = {
                "review_unit_id": unit_id,
                "asset_id": str(entry.get("asset_id", "") or ""),
                "identity": str(entry.get("identity", "") or ""),
                "kind": kind,
                "page_id": page_id,
                "reviewed_outputs": outputs,
                "reviewed_output_set_sha256": output_set_sha256,
                **(
                    {"material_index": int(entry["material_index"])}
                    if "material_index" in entry
                    else {}
                ),
            }
    return units


def _reviewed_output(root: Path, path: Path, *, label: str) -> dict[str, str]:
    return {
        "label": label,
        "path": _relative_to_root(path, root),
        "sha256": _sha256_file(path),
    }


def _verified_unit_outputs(
    root: Path, unit: Mapping[str, object]
) -> list[dict[str, object]]:
    rows = _mapping_rows(unit, "reviewed_outputs")
    labels = [str(row.get("label", "") or "") for row in rows]
    if not rows or not all(labels) or len(labels) != len(set(labels)):
        raise ValueError(
            f"Review output labels are incomplete for {unit.get('review_unit_id')}."
        )
    normalized: list[dict[str, object]] = []
    for row in rows:
        expected = str(row.get("sha256", "") or "")
        if len(expected) != 64:
            raise ValueError("Reviewed output SHA-256 is missing or malformed.")
        path = _verified_relative_file(
            root,
            row.get("path"),
            expected,
            f"review output {row.get('label')}",
        )
        normalized.append(
            {
                "label": str(row["label"]),
                "path": _relative_to_root(path, root),
                "sha256": expected,
            }
        )
    if _canonical_json_sha256(normalized) != str(
        unit.get("reviewed_output_set_sha256", "") or ""
    ):
        raise ValueError(f"Review output set changed for {unit.get('review_unit_id')}.")
    return normalized


def _validated_limitation_evidence(
    root: Path,
    unit: Mapping[str, object],
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    evidence = dict(_mapping(value))
    unit_id = str(unit.get("review_unit_id", "") or "")
    if unit.get("kind") == "source_disposition":
        raise ValueError("Missing geometry or PAC evidence cannot be a LIMITATION.")
    if (
        evidence.get("schema") != EQUIPMENT_REVIEW_LIMITATION_SCHEMA
        or evidence.get("review_unit_id") != unit_id
        or evidence.get("finding_kind") != "unsupported_proprietary_effect"
    ):
        raise ValueError(
            "LIMITATION requires the current review unit and the exact "
            "unsupported_proprietary_effect evidence schema."
        )
    effect = _mapping(evidence.get("effect"))
    for key in ("owner_wrapper", "parameter_name", "description"):
        if not str(effect.get(key, "") or "").strip():
            raise ValueError(f"LIMITATION effect evidence is missing {key}.")
    if "source_value" not in effect or effect.get("source_value") in (None, ""):
        raise ValueError("LIMITATION effect evidence is missing source_value.")
    if any(evidence.get(key) is not True for key in _LIMITATION_FAITHFULNESS_FIELDS):
        raise ValueError(
            "LIMITATION requires source-faithful color, ownership, and implemented "
            "surface response."
        )
    if any(evidence.get(key) is not False for key in _LIMITATION_MISSING_SOURCE_FIELDS):
        raise ValueError(
            "Missing geometry, PAC, PAC_XML, icon, or DDS evidence cannot be accepted "
            "as a LIMITATION."
        )
    source_evidence = _validated_source_evidence_rows(
        root, evidence, key="source_evidence"
    )
    normalized = {
        "schema": EQUIPMENT_REVIEW_LIMITATION_SCHEMA,
        "review_unit_id": unit_id,
        "finding_kind": "unsupported_proprietary_effect",
        "effect": {
            "owner_wrapper": str(effect["owner_wrapper"]),
            "parameter_name": str(effect["parameter_name"]),
            "source_value": effect["source_value"],
            "description": str(effect["description"]),
        },
        **{key: True for key in _LIMITATION_FAITHFULNESS_FIELDS},
        **{key: False for key in _LIMITATION_MISSING_SOURCE_FIELDS},
        "source_evidence": source_evidence,
    }
    normalized["source_evidence_binding_sha256"] = _canonical_json_sha256(
        {
            "effect": normalized["effect"],
            "source_evidence": source_evidence,
        }
    )
    return normalized


def _validated_source_disposition_evidence(
    root: Path,
    unit: Mapping[str, object],
    verdict: str,
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    evidence = dict(_mapping(value))
    unit_id = str(unit.get("review_unit_id", "") or "")
    if unit.get("kind") != "source_disposition":
        raise ValueError(
            "Source-only dispositions cannot be assigned to rendered units."
        )
    if (
        evidence.get("schema") != EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA
        or evidence.get("review_unit_id") != unit_id
        or evidence.get("disposition") != verdict
    ):
        raise ValueError(
            "An accepted source-only disposition must name the current review unit "
            "and exact disposition."
        )
    source_evidence = _validated_source_evidence_rows(
        root, evidence, key="source_evidence"
    )
    required_labels = (
        _SOURCE_COMMON_EVIDENCE_LABELS
        if verdict == "EXCLUDED_CATALOGUE_DEFECT"
        else _SOURCE_AUTHORED_EMPTY_EVIDENCE_LABELS
        if verdict == "AUTHORED_EMPTY"
        else ()
    )
    if not required_labels:
        raise ValueError(f"Unsupported accepted source disposition: {verdict}")
    by_label = {str(row["label"]): row for row in source_evidence}
    if set(by_label) != set(required_labels):
        raise ValueError(
            f"{verdict} requires exactly these parser-backed source evidence labels: "
            + ", ".join(required_labels)
        )
    source_evidence = [by_label[label] for label in required_labels]
    for label in required_labels:
        expected = _AUTHORITATIVE_SOURCE_SHA256.get(label)
        if expected is not None and by_label[label]["sha256"] != expected:
            raise ValueError(
                f"Source evidence {label} is not the authoritative audited payload."
            )
    paths = {
        label: (root / str(by_label[label]["path"])).resolve(strict=True)
        for label in required_labels
    }
    if paths["frozen_catalogue"] != (root / "catalogue.json").resolve(strict=True):
        raise ValueError("Source disposition must cite this census catalogue.json.")
    if paths["live_resolution"] != (root / "resolution.json").resolve(strict=True):
        raise ValueError("Source disposition must cite this census resolution.json.")
    catalogue, resolution = load_equipment_capture_inputs(
        paths["frozen_catalogue"], paths["live_resolution"]
    )
    context = _validated_source_disposition_context(
        root,
        unit,
        catalogue=catalogue,
        resolution=resolution,
    )
    owner_item_ids = tuple(context["owner_item_ids"])
    item_rows = _parsed_owner_iteminfo_rows(
        paths["iteminfo_payload"],
        paths["iteminfo_header"],
        owner_item_ids,
    )
    item_types = {row.item_type for row, _raw_hash in item_rows.values()}
    equip_type_keys = {row.equip_type_key for row, _raw_hash in item_rows.values()}
    slot_counts = {len(row.occupied_slots) for row, _raw_hash in item_rows.values()}
    if len(item_types) != 1 or None in item_types:
        raise ValueError("Source disposition owner ItemInfo types are not coherent.")
    if len(equip_type_keys) != 1 or len(slot_counts) != 1:
        raise ValueError("Source disposition owner equipment fields are not coherent.")
    item_type = int(next(iter(item_types)))
    equip_type_key = int(next(iter(equip_type_keys)))
    slot_count = int(next(iter(slot_counts)))
    normalized_facts: dict[str, object] = {
        "catalogue_identity": str(context["identity"]),
        "owner_item_ids": list(owner_item_ids),
        "owner_record_ids": list(context["owner_record_ids"]),
        "item_row_sha256s": {
            str(item_id): item_rows[item_id][1] for item_id in owner_item_ids
        },
        "item_type": item_type,
        "equip_type_key": equip_type_key,
        "equipment_slot_count": slot_count,
    }
    if verdict == "EXCLUDED_CATALOGUE_DEFECT":
        if item_type != 4_001 or equip_type_key != 0 or slot_count != 0:
            raise ValueError(
                "EXCLUDED_CATALOGUE_DEFECT requires parser-derived item_type 4001, "
                "equip_type_key 0, and zero equipment slots."
            )
        normalized_facts["icon_only_false_positive"] = True
    else:
        if (
            item_type != _AUTHORED_EMPTY_ITEM_TYPE
            or equip_type_key != _AUTHORED_EMPTY_EQUIP_TYPE_KEY
            or slot_count != 0
        ):
            raise ValueError(
                "AUTHORED_EMPTY requires the parser-derived Fist item type, equip "
                "key, and zero equipment slots."
            )
        string_rows = parse_stringinfo(
            paths["stringinfo_payload"].read_bytes(),
            paths["stringinfo_header"].read_bytes(),
            name="equipment source disposition StringInfo",
        )
        strings = stringinfo_index(string_rows)
        pappt = parse_pappt(
            paths["active_part_prefab_table"].read_bytes(),
            name="equipment source disposition active PAPPT",
        )
        selected_parts = {
            item_id: find_part_stems(row, strings, pappt)
            for item_id, (row, _raw_hash) in item_rows.items()
        }
        if any(
            len(parts) != 1 or parts[0][1] != _AUTHORED_EMPTY_STEM
            for parts in selected_parts.values()
        ):
            raise ValueError(
                "AUTHORED_EMPTY owners do not uniquely select cd_t9999_empty "
                "through parsed ItemInfo, StringInfo, and active PAPPT data."
            )
        selected_hashes = {parts[0][0] for parts in selected_parts.values()}
        if len(selected_hashes) != 1:
            raise ValueError("AUTHORED_EMPTY owner part hashes are not coherent.")
        prefab_record = pappt.find(_AUTHORED_EMPTY_STEM)
        if prefab_record is None:
            raise ValueError("Active PAPPT has no cd_t9999_empty record.")
        authoritative_prefab = normalize_archive_path(prefab_record.prefab_path)
        if (
            PurePosixPath(authoritative_prefab).name.casefold()
            != f"{_AUTHORED_EMPTY_STEM}.prefab"
        ):
            raise ValueError("Active PAPPT resolved an unexpected empty prefab path.")
        document = decode_prefab_binary(paths["authoritative_prefab"].read_bytes())
        if document.walk_complete is not True:
            raise ValueError(
                "AUTHORED_EMPTY requires a complete authoritative prefab decode."
            )
        model_edge_count = _decoded_prefab_model_edge_count(document)
        if model_edge_count != 0:
            raise ValueError(
                "AUTHORED_EMPTY authoritative prefab contains model geometry edges."
            )
        normalized_facts.update(
            {
                "authoritative_part_hash": int(next(iter(selected_hashes))),
                "authoritative_part_stem": _AUTHORED_EMPTY_STEM,
                "authoritative_prefab": authoritative_prefab,
                "authoritative_prefab_selection": True,
                "model_edge_count": model_edge_count,
            }
        )
    if dict(_mapping(evidence.get("source_facts"))) != normalized_facts:
        raise ValueError(
            "Source disposition facts must exactly match the parser-derived source "
            "packet facts."
        )
    normalized = {
        "schema": EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA,
        "review_unit_id": unit_id,
        "disposition": verdict,
        "source_facts": normalized_facts,
        "source_evidence": source_evidence,
    }
    normalized["source_evidence_binding_sha256"] = _canonical_json_sha256(
        {
            "source_facts": normalized_facts,
            "source_evidence": source_evidence,
        }
    )
    return normalized


def _validated_source_disposition_context(
    root: Path,
    unit: Mapping[str, object],
    *,
    catalogue: Mapping[str, object],
    resolution: Mapping[str, object],
) -> dict[str, object]:
    asset_id = str(unit.get("asset_id", "") or "")
    assets_root = (root / "assets").resolve(strict=True)
    asset_root = (assets_root / asset_id).resolve(strict=True)
    if not asset_id or asset_root.parent != assets_root:
        raise ValueError("Source disposition asset identity escaped the census assets.")
    report = _read_object(asset_root / "asset-report.json", "source asset report")
    identity = normalize_archive_path(report.get("identity")).casefold()
    unit_identity = normalize_archive_path(unit.get("identity")).casefold()
    if (
        report.get("schema") != EQUIPMENT_CAPTURE_SCHEMA
        or report.get("status") not in {"source_only_captured", "source_only_reviewed"}
        or not identity
        or identity != unit_identity
    ):
        raise ValueError("Source disposition does not belong to a source-only capture.")
    report_owners = _normalized_source_owners(
        _mapping_rows(report, "owners"), identity=identity
    )
    report_records = _normalized_source_owner_records(
        _mapping_rows(report, "owner_records"), identity=identity
    )
    if not report_owners or len(report_owners) != len(report_records):
        raise ValueError("Source-only capture owner evidence is incomplete.")
    report_owner_ids = {str(row["record_id"]) for row in report_owners}
    if report_owner_ids != {str(row["record_id"]) for row in report_records}:
        raise ValueError("Source-only capture owner records do not match its owners.")
    finding = dict(_mapping(report.get("source_only_finding")))
    if (
        finding.get("finding")
        != "catalogue_name_has_no_renderable_archive_binding"
        or finding.get("candidate_path_tokens_present") != []
        or finding.get("owner_prefab_hashes_empty") is not True
        or finding.get("owner_has_no_sibling_pac") is not True
    ):
        raise ValueError("Source-only capture finding is not the exact no-binding proof.")

    if catalogue.get("schema") != EQUIPMENT_AUDIT_CATALOGUE_SCHEMA:
        raise ValueError("Source evidence is not the frozen equipment catalogue.")
    source = _mapping(catalogue.get("source"))
    expected_source = {
        "root_id": EQUIPMENT_AUDIT_ROOT_ID,
        "generation_id": EQUIPMENT_AUDIT_GENERATION_ID,
        "archive_fingerprint": EQUIPMENT_AUDIT_ARCHIVE_FINGERPRINT,
        "item_catalog_schema_version": EQUIPMENT_AUDIT_SOURCE_SCHEMA_VERSION,
        "item_catalog_sha256": EQUIPMENT_AUDIT_ITEM_CATALOG_SHA256,
    }
    if any(source.get(key) != expected for key, expected in expected_source.items()):
        raise ValueError("Source evidence does not name the exact frozen catalogue.")
    catalogue_logical = [
        row
        for row in _mapping_rows(catalogue, "logical_models")
        if normalize_archive_path(row.get("identity")).casefold() == identity
    ]
    if len(catalogue_logical) != 1 or _normalized_source_owners(
        _mapping_rows(catalogue_logical[0], "owners"), identity=identity
    ) != report_owners:
        raise ValueError("Frozen catalogue owner links disagree with the capture.")
    catalogue_records = [
        row
        for row in _mapping_rows(catalogue, "records")
        if str(row.get("record_id", "") or "") in report_owner_ids
    ]
    if _normalized_source_owner_records(
        catalogue_records, identity=identity
    ) != report_records:
        raise ValueError("Frozen catalogue owner records disagree with the capture.")

    if resolution.get("schema") != EQUIPMENT_AUDIT_RESOLUTION_SCHEMA:
        raise ValueError("Source evidence is not the live equipment resolution.")
    resolution_rows = [
        row
        for row in _mapping_rows(resolution, "logical_models")
        if normalize_archive_path(row.get("identity")).casefold() == identity
    ]
    if len(resolution_rows) != 1:
        raise ValueError("Live resolution does not contain the source-only identity once.")
    resolved = resolution_rows[0]
    if (
        resolved.get("status") != "catalogue_source_only"
        or _normalized_source_owners(
            _mapping_rows(resolved, "owners"), identity=identity
        )
        != report_owners
        or _mapping_rows(resolved, "physical_components")
        or _mapping_rows(resolved, "direct_candidates")
        or _mapping_rows(resolved, "prefab_candidates")
        or _mapping_rows(resolved, "prefab_edges")
        or dict(_mapping(resolved.get("source_only_finding"))) != finding
    ):
        raise ValueError("Live source-only resolution disagrees with the capture.")
    expected_icons = {
        path
        for record in report_records
        for path in tuple(record["icon_paths"])
    }
    finding_icons = {
        normalize_archive_path(value).casefold()
        for value in _source_sequence(
            finding.get("associated_icons"), label="associated_icons"
        )
    }
    if finding_icons != expected_icons:
        raise ValueError("Source-only finding does not bind the owner icon evidence.")
    return {
        "identity": identity,
        "owner_item_ids": tuple(int(row["item_id"]) for row in report_owners),
        "owner_record_ids": tuple(str(row["record_id"]) for row in report_owners),
    }


def _normalized_source_owners(
    rows: Sequence[Mapping[str, object]], *, identity: str
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        try:
            item_id = int(row.get("item_id", 0) or 0)
            edge_index = int(row.get("edge_index", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Source-only owner link is malformed.") from exc
        record_id = str(row.get("record_id", "") or "")
        declared_path = normalize_archive_path(row.get("declared_path")).casefold()
        if item_id <= 0 or edge_index < 0 or not record_id or declared_path != identity:
            raise ValueError("Source-only owner link is incomplete or mismatched.")
        normalized.append(
            {
                "item_id": item_id,
                "record_id": record_id,
                "edge_index": edge_index,
                "declared_path": declared_path,
            }
        )
    normalized.sort(key=lambda row: (int(row["item_id"]), str(row["record_id"])))
    if len({str(row["record_id"]) for row in normalized}) != len(normalized):
        raise ValueError("Source-only owner record identities are duplicated.")
    return tuple(normalized)


def _normalized_source_owner_records(
    rows: Sequence[Mapping[str, object]], *, identity: str
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        try:
            item_id = int(row.get("item_id", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Source-only catalogue owner is malformed.") from exc
        record_id = str(row.get("record_id", "") or "")
        pac_files = tuple(
            normalize_archive_path(value).casefold()
            for value in _source_sequence(row.get("pac_files"), label="pac_files")
        )
        prefab_hashes = _source_sequence(
            row.get("prefab_hashes"), label="prefab_hashes"
        )
        icon_paths = tuple(
            normalize_archive_path(value).casefold()
            for value in _source_sequence(row.get("icon_paths"), label="icon_paths")
        )
        if (
            item_id <= 0
            or not record_id
            or pac_files != (identity,)
            or prefab_hashes
            or not icon_paths
            or any(PurePosixPath(path).suffix != ".dds" for path in icon_paths)
        ):
            raise ValueError(
                "Source-only catalogue owner lacks its exact synthetic PAC/icon-only "
                "shape."
            )
        normalized.append(
            {
                "item_id": item_id,
                "record_id": record_id,
                "pac_files": pac_files,
                "prefab_hashes": (),
                "icon_paths": icon_paths,
            }
        )
    normalized.sort(key=lambda row: (int(row["item_id"]), str(row["record_id"])))
    if len({str(row["record_id"]) for row in normalized}) != len(normalized):
        raise ValueError("Source-only catalogue owner records are duplicated.")
    return tuple(normalized)


def _source_sequence(value: object, *, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"Source-only evidence field {label} is not an array.")
    return tuple(value)


def _parsed_owner_iteminfo_rows(
    payload_path: Path,
    header_path: Path,
    owner_item_ids: Sequence[int],
) -> dict[int, tuple[ItemInfoRow, str]]:
    payload = payload_path.read_bytes()
    header = header_path.read_bytes()
    table = parse_pabgh_table(header, payload=payload)
    spans = table.row_spans(len(payload))
    if (
        table.key_width != 4
        or len(spans) != len(table.rows)
        or not spans
        or spans[0][1] != 0
        or len({row.row_id for row in table.rows}) != len(table.rows)
    ):
        raise ValueError("ItemInfo evidence has an invalid row directory.")
    by_item_id: dict[int, bytes] = {}
    for row, start, end in spans:
        raw = payload[start:end]
        if end <= start or len(raw) < 4 or int.from_bytes(raw[:4], "little") != row.row_id:
            raise ValueError("ItemInfo directory does not bind its inline row keys.")
        if row.row_id in owner_item_ids:
            by_item_id[row.row_id] = raw
    if set(by_item_id) != set(owner_item_ids):
        raise ValueError("ItemInfo evidence is missing a source-only owner row.")
    item_keys = tuple(row.row_id for row in table.rows)
    parsed: dict[int, tuple[ItemInfoRow, str]] = {}
    for item_id in owner_item_ids:
        raw = by_item_id[item_id]
        row = parse_iteminfo_row(raw, item_keys=item_keys)
        if row.key != item_id:
            raise ValueError("Parsed ItemInfo owner key disagrees with its directory.")
        parsed[item_id] = (row, hashlib.sha256(raw).hexdigest())
    return parsed


def _decoded_prefab_model_edge_count(document: object) -> int:
    objects = tuple(getattr(document, "objects", ()) or ())
    edges: set[tuple[str, str, int]] = set()
    for item in objects:
        for field, value in tuple(getattr(item, "values", ()) or ()):
            path = normalize_archive_path(getattr(value, "text", ""))
            if PurePosixPath(path).suffix.casefold() not in EQUIPMENT_AUDIT_MODEL_EXTENSIONS:
                continue
            edges.add((path.casefold(), str(field).casefold(), int(item.index)))
    return len(edges)


def _validated_source_evidence_rows(
    root: Path,
    evidence: Mapping[str, object],
    *,
    key: str,
) -> list[dict[str, str]]:
    rows = _mapping_rows(evidence, key)
    if not rows:
        raise ValueError("Accepted evidence must cite at least one hash-pinned source.")
    normalized: list[dict[str, str]] = []
    labels: set[str] = set()
    for row in rows:
        label = str(row.get("label", "") or "").strip()
        expected = str(row.get("sha256", "") or "")
        if not label or len(expected) != 64:
            raise ValueError("Source evidence requires a label and SHA-256.")
        if label in labels:
            raise ValueError(f"Source evidence label is duplicated: {label}")
        labels.add(label)
        path = _verified_relative_file(
            root,
            row.get("path"),
            expected,
            f"source evidence {label}",
        )
        normalized.append(
            {
                "label": label,
                "path": _relative_to_root(path, root),
                "sha256": expected,
            }
        )
    return normalized


def _verified_relative_file(
    base: Path,
    path_value: object,
    expected_sha256: object | None,
    label: str,
) -> Path:
    relative = Path(str(path_value or ""))
    if not str(path_value or "") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            f"Evidence path is not asset-relative for {label}: {path_value!r}"
        )
    path = (base / relative).resolve(strict=True)
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"Evidence path escaped its asset root for {label}: {path}")
    actual = _sha256_file(path)
    if expected_sha256 is not None and actual != str(expected_sha256 or ""):
        raise ValueError(f"Evidence hash disagrees for {label}: {path}")
    return path


def _atomic_save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        image.save(temporary, format="PNG", compress_level=3)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _read_object(path: Path, label: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} is not a JSON object: {path}")
    return dict(payload)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: Mapping[str, object], key: str) -> list[dict[str, object]]:
    raw = value.get(key, ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise TypeError(f"Equipment review field {key} is not an array.")
    if any(not isinstance(row, Mapping) for row in raw):
        raise ValueError(f"Equipment review field {key} contains a non-object row.")
    return [
        row if isinstance(row, dict) else dict(row)
        for row in raw
        if isinstance(row, Mapping)
    ]


def _relative_to_root(path: Path, root: Path) -> str:
    return str(path.resolve(strict=True).relative_to(root.resolve())).replace("\\", "/")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "EQUIPMENT_REVIEW_INDEX_SCHEMA",
    "EQUIPMENT_REVIEW_LIMITATION_SCHEMA",
    "EQUIPMENT_REVIEW_PROGRESS_SCHEMA",
    "EQUIPMENT_REVIEW_SOURCE_DISPOSITION_SCHEMA",
    "EQUIPMENT_REVIEW_SUMMARY_SCHEMA",
    "build_equipment_review_index",
    "finalize_equipment_review",
    "record_equipment_review_pages",
    "record_equipment_review_units",
    "summarize_equipment_review",
]
