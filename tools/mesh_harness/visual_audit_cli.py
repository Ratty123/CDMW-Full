from __future__ import annotations

import hashlib
import json
import os
import time
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from tools.mesh_harness.visual_audit_corpus import VISUAL_AUDIT_VIEWS, VisualAuditAssetSpec
from tools.mesh_harness.visual_audit_manifest_v2 import REQUIRED_SWORD_PATH


















def _payload_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()




def _load_specs(path: Path) -> tuple[VisualAuditAssetSpec, ...]:
    payload = _read_json(path)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Visual-audit corpus manifest must contain an assets array.")
    specs: list[VisualAuditAssetSpec] = []
    for index, row in enumerate(assets, 1):
        if not isinstance(row, Mapping):
            raise ValueError(f"Visual-audit manifest asset {index} is not an object.")
        category = str(row.get("model_category", "") or "model")
        virtual_path = str(row.get("virtual_path", "") or "")
        asset_id = str(row.get("asset_id", "") or f"{index:03d}-{category}-{Path(virtual_path).stem}")
        specs.append(
            VisualAuditAssetSpec(
                index=int(row.get("index", index) or index),
                asset_id=asset_id,
                virtual_path=virtual_path,
                model_category=category,
                coverage_tags=tuple(str(value) for value in tuple(row.get("coverage_tags", ()) or ())),
                selection_reason=str(row.get("selection_reason", "") or "User-supplied corpus manifest."),
                graph_complexity=int(row.get("graph_complexity", 0) or 0),
                graph_tags=tuple(str(value) for value in tuple(row.get("graph_tags", ()) or ())),
                pac_xml_virtual_path=str(row.get("pac_xml_virtual_path", "") or ""),
                pac_xml_sha256=str(row.get("pac_xml_sha256", "") or ""),
            )
        )
    result = tuple(specs)
    _validate_manifest_constraints(payload, result)
    return result


def _validate_manifest_constraints(
    payload: Mapping[str, object],
    specs: Sequence[VisualAuditAssetSpec],
) -> None:
    raw_minimum = payload.get("minimum_asset_count", 0)
    try:
        minimum = int(raw_minimum or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Visual-audit minimum_asset_count must be an integer.") from exc
    if minimum < 0:
        raise ValueError("Visual-audit minimum_asset_count cannot be negative.")
    if len(specs) < minimum:
        raise ValueError(
            f"Visual-audit manifest requires at least {minimum} assets; found {len(specs)}."
        )

    excluded = {
        str(value or "").replace("\\", "/").strip().casefold()
        for value in tuple(payload.get("excluded_virtual_paths", ()) or ())
        if str(value or "").strip()
    }
    overlap = sorted(
        spec.virtual_path
        for spec in specs
        if spec.virtual_path.replace("\\", "/").strip().casefold() in excluded
    )
    if overlap:
        raise ValueError(f"Visual-audit manifest reuses excluded PAC paths: {overlap}")

    raw_required = payload.get("required_coverage", {})
    if not isinstance(raw_required, Mapping):
        raise ValueError("Visual-audit required_coverage must be an object.")
    short: dict[str, tuple[int, int]] = {}
    for raw_tag, raw_count in raw_required.items():
        tag = str(raw_tag or "").strip()
        try:
            required_count = int(raw_count)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"Visual-audit coverage requirement for {tag or '<empty>'} must be an integer."
            ) from exc
        if not tag or required_count < 0:
            raise ValueError("Visual-audit coverage tags must be non-empty with non-negative counts.")
        actual_count = sum(tag in spec.coverage_tags for spec in specs)
        if actual_count < required_count:
            short[tag] = (actual_count, required_count)
    if short:
        raise ValueError(f"Visual-audit manifest coverage is incomplete: {short}")


def _write_draft_review(
    evidence_root: Path,
    corpus: Mapping[str, object],
    composites: Sequence[Mapping[str, object]],
    archive_report: Mapping[str, object],
    dotnet_report: Mapping[str, object],
    archives_unchanged: bool,
    prepared_packages_unchanged: bool,
) -> None:
    composite_map = {str(row.get("id", "")): row for row in composites}
    lines = [
        "# Mesh Editor Visual Material-Parity Audit",
        "",
        "Status: captures complete; visual verdicts pending direct image inspection.",
        "",
        f"- Run ID: `{corpus.get('run_id', '')}`",
        f"- Corpus assets: {int(corpus.get('asset_count', 0) or 0)}",
        f"- Archive Browser batch: {'PASS' if archive_report.get('ok') else 'FAIL'}",
        f"- Mesh Editor .NET/Vortice batch: {'PASS' if dotnet_report.get('ok') else 'FAIL'}",
        f"- Game archive fingerprints unchanged: {archives_unchanged}",
        f"- Prepared package fingerprints unchanged: {prepared_packages_unchanged}",
        "",
    ]
    verdict_assets: list[dict[str, object]] = []
    unreviewed_submesh_count = 0
    for asset in tuple(corpus.get("assets", ()) or ()):
        if not isinstance(asset, Mapping):
            continue
        asset_id = str(asset.get("asset_id", "") or "")
        composite = composite_map.get(asset_id, {})
        region_templates: list[dict[str, object]] = []
        for region in tuple(composite.get("material_regions", ()) or ()):
            if not isinstance(region, Mapping):
                continue
            unreviewed_submesh_count += 1
            region_templates.append(
                {
                    "source_submesh_index": int(region.get("source_submesh_index", -1)),
                    "classification": "",
                    "classification_basis": "",
                    "source_map_observations": "",
                    "pac_evidence": "",
                    "render_observations": "",
                    "geometry_observations": "",
                    "geometry_coherent": None,
                    "confidence": "",
                    "unsupported_features": [],
                    "unsupported_feature_unchanged": False,
                    "automated_metric_flags": [],
                    "automated_metrics_only": False,
                    "source_board_direct_image_inspection": False,
                    "review_sheet_direct_image_inspection": False,
                    "verdict": "",
                    "source_board": str(region.get("source_board", "") or ""),
                    "review_sheet": str(region.get("review_sheet", "") or ""),
                }
            )
        verdict_assets.append(
            {
                "id": asset_id,
                "selected_camera_angle": str(composite.get("selected_camera_angle", "three-quarter-front")),
                "full_model_angle_reviews": [
                    {
                        "angle": str(view["name"]),
                        "direct_image_inspection": False,
                        "visual_observations": "",
                        "geometry_coherent": None,
                        "geometry_observations": "",
                        "verdict": "",
                    }
                    for view in VISUAL_AUDIT_VIEWS
                ],
                "full_model_contact_sheet_direct_image_inspection": False,
                "full_model_contact_sheet_observations": "",
                "full_model_contact_sheet_verdict": "",
                "full_model_geometry_coherent": None,
                "full_model_geometry_observations": "",
                "reference_status": "",
                "reference_identity": "",
                "reference_urls": [],
                "reference_observations": "",
                "reported_target_match": (
                    None
                    if str(asset.get("virtual_path", "") or "").casefold()
                    == REQUIRED_SWORD_PATH.casefold()
                    else "not_applicable"
                ),
                "reported_target_observations": "",
                "overall_verdict": "",
                "material_regions": region_templates,
            }
        )
        lines.extend(
            [
                f"## {int(asset.get('index', 0) or 0):03d} - {asset_id}",
                "",
                f"- PAC virtual path: `{asset.get('virtual_path', '')}`",
                f"- Archive provenance: `{asset.get('archive_provenance', {})}`",
                f"- Model category: `{asset.get('model_category', '')}`",
                f"- Material families: `{', '.join(asset.get('expected_material_families', ()) or ())}`",
                "- Visual material classification: PENDING",
                f"- Selected camera angle: `{composite.get('selected_camera_angle', '')}`",
                "- Archive Browser verdict: PENDING",
                "- Mesh Editor verdict: PENDING",
                "- Overall verdict: PENDING",
                "- Defect categories: `[]`",
                "- Visual observations: Pending direct multi-angle inspection.",
                "- Likely cause: Pending.",
                "- Confidence: Pending.",
                "- Code changes made: None assigned yet.",
                "- Targeted validation performed: paired six-angle direct renderer capture.",
                "- Remaining uncertainty: Visual adjudication pending.",
                f"- Primary comparison: `{composite.get('primary_final_png', '')}`",
                f"- Multi-angle contact sheet: `{composite.get('contact_sheet', '')}`",
                f"- Visible submeshes awaiting review: {len(region_templates)}",
                "",
            ]
        )
    (evidence_root / "review.md").write_text("\n".join(lines), encoding="utf-8")
    _atomic_write_json(
        evidence_root / "summary.json",
        {
            "schema": "cdmw_mesh_visual_audit_summary_v2",
            "run_id": str(corpus.get("run_id", "") or ""),
            "status": "pending_visual_review",
            "asset_count": int(corpus.get("asset_count", 0) or 0),
            "pass_count": 0,
            "concern_count": 0,
            "fail_count": 0,
            "unreviewed_count": int(corpus.get("asset_count", 0) or 0),
            "unreviewed_submesh_count": unreviewed_submesh_count,
            "archive_browser_batch_ok": bool(archive_report.get("ok")),
            "dotnet_batch_ok": bool(dotnet_report.get("ok")),
            "archive_sources_unchanged": bool(archives_unchanged),
            "prepared_packages_unchanged": bool(prepared_packages_unchanged),
            "assets": [dict(row) for row in composites],
        },
    )
    _atomic_write_json(
        evidence_root / "verdicts.template.json",
        {
            "schema": "cdmw_mesh_visual_audit_verdict_v2",
            "run_id": str(corpus.get("run_id", "") or ""),
            "review_policy": (
                "Separate direct-inspection records for every PAC/DDS source board, every submesh "
                "review sheet, all six individual full-model comparisons, and the contact sheet; "
                "every rendered image receives PASS/CONCERN/FAIL and the asset takes the worst; "
                "geometry coherence is a hard gate, and source/automated evidence may flag "
                "candidates but cannot issue visual PASS."
            ),
            "assets": verdict_assets,
        },
    )




def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}




def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        replace_delays = (0.01, 0.025, 0.05)
        for attempt in range(len(replace_delays) + 1):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt >= len(replace_delays):
                    raise
                time.sleep(replace_delays[attempt])
    finally:
        temporary.unlink(missing_ok=True)


__all__ = []
