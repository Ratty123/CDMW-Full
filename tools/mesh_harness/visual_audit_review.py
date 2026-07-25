from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from tools.mesh_harness.visual_audit_corpus import VISUAL_AUDIT_VIEWS
from tools.mesh_harness.visual_audit_integrity import _capture_integrity
from tools.mesh_harness.visual_audit_manifest_v2 import (
    PRIOR_CONCERN_SWORD_PATH,
    REQUIRED_SWORD_PATH,
    visual_audit_v2_contract_for_asset_count,
)


_VERDICTS = {"PASS", "CONCERN", "FAIL"}
_CONFIDENCE = {"high", "medium", "low"}
_REFERENCE_STATUSES = {
    "exact_item",
    "shared_model_identity",
    "archive_related_candidate",
    "reference_unavailable",
    "not_applicable_control",
}
_MATERIAL_CLASSIFICATIONS = {
    "metal",
    "leather",
    "cloth",
    "skin",
    "hair_fur_feather",
    "wood",
    "glass_like",
    "emissive",
    "stone_ceramic",
    "painted_coated",
    "bone_horn",
    "organic_shell",
    "foliage",
    "mixed_hard_soft",
    "soft_nonmetal_unknown",
    "unknown",
}
_DEFECT_CATEGORIES = {
    "missing_texture",
    "incorrect_base_color",
    "color_space",
    "metallic_roughness",
    "packed_channels",
    "normal_map",
    "alpha_blend",
    "alpha_cutout",
    "culling",
    "emissive",
    "material_classification",
    "material_region",
    "excessive_darkness",
    "excessive_brightness",
    "camera_or_framing",
    "harness_or_capture",
    "renderer_exception",
    "geometry",
    "unknown",
}


def finalize_visual_audit_review(evidence_root: Path, verdicts_path: Path) -> dict[str, object]:
    evidence_root = Path(evidence_root).resolve()
    corpus = _read_json(evidence_root / "corpus.json")
    composites = _read_json(evidence_root / "runtime" / "composites.json")
    archive_report = _read_json(evidence_root / "runtime" / "archive-browser-capture.json")
    dotnet_report = _read_json(evidence_root / "runtime" / "dotnet-capture.json")
    integrity = _read_json(evidence_root / "runtime" / "integrity.json")
    verdicts = _read_json(Path(verdicts_path))
    run_id = str(corpus.get("run_id", "") or "")
    if not run_id or str(verdicts.get("run_id", "") or "") != run_id:
        raise ValueError("Visual-audit verdicts do not match the captured run ID.")
    verdict_v2 = str(verdicts.get("schema", "") or "") == "cdmw_mesh_visual_audit_verdict_v2"
    corpus_v2 = str(corpus.get("schema", "") or "") == "cdmw_mesh_visual_audit_corpus_v2"
    if corpus_v2 != verdict_v2:
        raise ValueError("Visual-audit v2 corpus and verdict schemas must be used together.")
    row_reader = _strict_mapping_rows if verdict_v2 else _mapping_rows
    corpus_rows = row_reader(corpus, "assets")
    expected_ids = [str(row.get("asset_id", "")) for row in corpus_rows]
    composite_rows = row_reader(composites, "assets")
    archive_rows = row_reader(archive_report, "assets")
    dotnet_rows = row_reader(dotnet_report, "assets")
    composite_map = {str(row.get("id", "")): row for row in composite_rows}
    archive_map = {str(row.get("id", "")): row for row in archive_rows}
    dotnet_map = {str(row.get("id", "")): row for row in dotnet_rows}
    verdict_rows = row_reader(verdicts, "assets")
    verdict_map = {str(row.get("id", "")): row for row in verdict_rows}
    require_material_classification = verdicts.get("require_material_classification") is True
    if [str(row.get("id", "")) for row in verdict_rows] != expected_ids:
        raise ValueError("Visual-audit verdict order must exactly match the corpus.")
    if [str(row.get("id", "")) for row in composite_rows] != expected_ids:
        raise ValueError("Visual-audit composites do not exactly cover the corpus.")

    final_root = evidence_root / "final"
    final_root.mkdir(parents=True, exist_ok=True)
    review_lines = [
        "# Mesh Editor Visual Material-Parity Audit",
        "",
        "Status: complete direct visual review.",
        "",
        f"- Run ID: `{run_id}`",
        f"- Corpus assets: {len(expected_ids)}",
        f"- Archive Browser batch: {'PASS' if archive_report.get('ok') is True else 'FAIL'}",
        f"- Mesh Editor .NET/Vortice batch: {'PASS' if dotnet_report.get('ok') is True else 'FAIL'}",
        f"- Run/corpus integrity: {'PASS' if integrity.get('ok') is True else 'FAIL'}",
        "- Scope: CDMW renderer/source-material consistency; this is not real-game parity proof.",
        "",
    ]
    summary_rows: list[dict[str, object]] = []
    for corpus_row in corpus_rows:
        asset_id = str(corpus_row.get("asset_id", ""))
        verdict = verdict_map[asset_id]
        composite = composite_map[asset_id]
        material_region_verdicts: list[dict[str, object]] = []
        asset_review: dict[str, object] = {}
        full_model_evidence: dict[str, object] = {}
        if verdict_v2:
            asset_review = _validate_v2_asset_verdict(verdict, corpus_row)
            full_model_evidence = _validate_v2_full_model_evidence(
                composite,
                evidence_root=evidence_root,
            )
            material_region_verdicts = _validate_v2_material_region_verdicts(
                verdict,
                tuple(composite.get("material_regions", ()) or ()),
                corpus_row,
                evidence_root=evidence_root,
            )
            selected = str(verdict.get("selected_camera_angle", "three-quarter-front") or "")
        else:
            _validate_verdict_row(
                verdict,
                require_material_classification=require_material_classification,
            )
            selected = str(verdict.get("selected_camera_angle", "") or "")
        candidates = composite.get("candidate_comparisons")
        if not isinstance(candidates, Mapping) or selected not in candidates:
            raise ValueError(f"Selected comparison angle is unavailable for {asset_id}: {selected!r}")
        source = Path(str(candidates[selected])).resolve()
        if not source.is_file():
            raise ValueError(f"Selected comparison PNG is missing for {asset_id}: {source}")
        final_path = final_root / f"{asset_id}.png"
        _atomic_copy(source, final_path)
        defect_categories = [str(value) for value in tuple(verdict.get("defect_categories", ()) or ())]
        material_classification = (
            sorted({str(row["classification"]) for row in material_region_verdicts})
            if verdict_v2
            else [str(value) for value in tuple(verdict.get("material_classification", ()) or ())]
        )
        archive_row = archive_map.get(asset_id, {})
        dotnet_row = dotnet_map.get(asset_id, {})
        summary_row = {
            "index": int(corpus_row.get("index", 0) or 0),
            "id": asset_id,
            "pac_virtual_path": str(corpus_row.get("virtual_path", "") or ""),
            "archive_provenance": dict(corpus_row.get("archive_provenance", {}) or {}),
            "model_category": str(corpus_row.get("model_category", "") or ""),
            "material_families": list(corpus_row.get("expected_material_families", ()) or ()),
            "shader_profile_classification": list(corpus_row.get("shader_profile_classification", ()) or ()),
            "expected_texture_channels": list(corpus_row.get("expected_texture_channels", ()) or ()),
            "alpha_modes": list(corpus_row.get("alpha_modes", ()) or ()),
            "material_classification": material_classification,
            "selected_camera_angle": selected,
            "full_model_reviewed_angles": list(asset_review.get("full_model_reviewed_angles", ())),
            "full_model_angle_reviews": list(asset_review.get("full_model_angle_reviews", ())),
            "full_model_direct_image_inspection": asset_review.get("full_model_direct_image_inspection") is True,
            "full_model_contact_sheet_direct_image_inspection": (
                asset_review.get("full_model_contact_sheet_direct_image_inspection") is True
            ),
            "full_model_contact_sheet_observations": str(
                asset_review.get("full_model_contact_sheet_observations", "") or ""
            ),
            "full_model_contact_sheet_verdict": str(
                asset_review.get("full_model_contact_sheet_verdict", "") or ""
            ),
            "full_model_geometry_coherent": asset_review.get("full_model_geometry_coherent"),
            "full_model_geometry_observations": str(asset_review.get("full_model_geometry_observations", "") or ""),
            "reference_status": str(asset_review.get("reference_status", "") or ""),
            "reference_identity": str(asset_review.get("reference_identity", "") or ""),
            "reference_urls": list(asset_review.get("reference_urls", ())),
            "reference_observations": str(asset_review.get("reference_observations", "") or ""),
            "reported_target_match": asset_review.get("reported_target_match"),
            "reported_target_observations": str(asset_review.get("reported_target_observations", "") or ""),
            "full_model_comparisons": dict(full_model_evidence.get("comparisons", {})),
            "full_model_comparison_sha256": dict(full_model_evidence.get("comparison_sha256", {})),
            "archive_browser_verdict": str(verdict.get("archive_browser_verdict", "SUPPORTING")),
            "mesh_editor_verdict": str(verdict.get("mesh_editor_verdict", verdict["overall_verdict"])),
            "overall_verdict": str(verdict["overall_verdict"]),
            "defect_categories": defect_categories,
            "visual_observations": str(verdict.get("visual_observations", "Submesh review rows are authoritative.")),
            "likely_cause": str(verdict.get("likely_cause", "See submesh PAC/source/render evidence.")),
            "confidence": str(verdict.get("confidence", _minimum_region_confidence(material_region_verdicts))),
            "code_changes_made": str(verdict.get("code_changes_made", "See task implementation history.")),
            "targeted_validation_performed": str(verdict.get("targeted_validation_performed", "Direct source-board and region-sheet inspection.")),
            "remaining_uncertainty": str(verdict.get("remaining_uncertainty", "None stated.")),
            "material_regions": material_region_verdicts,
            "primary_final_png": str(final_path),
            "primary_final_sha256": _sha256_file(final_path),
            "multi_angle_contact_sheet": str(full_model_evidence.get("contact_sheet", "") or ""),
            "multi_angle_contact_sheet_sha256": str(
                full_model_evidence.get("contact_sheet_sha256", "") or ""
            ),
            "archive_browser_capture_ok": archive_row.get("ok") is True,
            "mesh_editor_capture_ok": dotnet_row.get("ok") is True,
        }
        summary_rows.append(summary_row)
        review_lines.extend(_review_entry(summary_row))

    if verdict_v2:
        _validate_v2_unique_evidence_paths(summary_rows)

    expected_final = {f"{asset_id}.png" for asset_id in expected_ids}
    actual_final = {path.name for path in final_root.glob("*.png") if path.is_file()}
    if actual_final != expected_final:
        raise ValueError(
            f"Final comparison PNG set does not exactly match corpus: missing={sorted(expected_final - actual_final)}, "
            f"extra={sorted(actual_final - expected_final)}"
        )
    counts = Counter(str(row["overall_verdict"]) for row in summary_rows)
    before = _read_json(evidence_root / "runtime" / "archive-fingerprints-before.json")
    after = _read_json(evidence_root / "runtime" / "archive-fingerprints-after.json")
    package_state = (
        _read_json(evidence_root / "runtime" / "package-state.json")
        if verdict_v2
        else {}
    )
    prepared_before = (
        _read_json(evidence_root / "runtime" / "prepared-package-fingerprints.json")
        if verdict_v2
        else {}
    )
    prepared_after = (
        _read_json(evidence_root / "runtime" / "prepared-package-fingerprints-after.json")
        if verdict_v2
        else {}
    )
    archive_browser_batch_ok = archive_report.get("ok") is True
    dotnet_batch_ok = dotnet_report.get("ok") is True
    package_state_ok = (
        _v2_package_state_ok(
            package_state,
            corpus=corpus,
            evidence_root=evidence_root,
            expected_ids=expected_ids,
        )
        if verdict_v2
        else None
    )
    if verdict_v2:
        corpus_sha256 = _payload_sha256(corpus)
        archive_sources_unchanged = package_state_ok is True and _v2_archive_fingerprints_unchanged(
            before,
            after,
            tuple(package_state.get("archive_fingerprint_paths", ()) or ()),
        )
        prepared_packages_unchanged = (
            package_state_ok is True
            and prepared_before == prepared_after
            and _v2_prepared_package_seal_ok(
                prepared_before,
                run_id=run_id,
                corpus_sha256=corpus_sha256,
                expected_ids=expected_ids,
            )
        )
        recomputed_integrity = _capture_integrity(
            run_id=run_id,
            expected_ids=expected_ids,
            archive_report=archive_report,
            dotnet_report=dotnet_report,
            composite_rows=composite_rows,
            prepared_packages_unchanged=prepared_packages_unchanged,
        )
        integrity_ok = recomputed_integrity.get("ok") is True and integrity == recomputed_integrity
    else:
        archive_sources_unchanged = bool(before) and before == after
        prepared_packages_unchanged = None
        recomputed_integrity = integrity
        integrity_ok = integrity.get("ok") is True
    semantic_conservation_ok = _semantic_conservation_ok(corpus_rows)
    source_board_coverage_ok = _source_board_coverage_ok(corpus_rows)
    acceptance_checks = (
        {
            "corpus_selection": _v2_corpus_acceptance_ok(corpus),
            "source_board_coverage": source_board_coverage_ok,
            "semantic_conservation": semantic_conservation_ok,
            "asset_verdicts": _v2_acceptance_ok(summary_rows, corpus_rows),
            "archive_browser_batch": archive_browser_batch_ok,
            "dotnet_batch": dotnet_batch_ok,
            "capture_integrity": integrity_ok,
            "archive_sources_unchanged": archive_sources_unchanged,
            "prepared_package_state": package_state_ok is True,
            "prepared_packages_unchanged": prepared_packages_unchanged is True,
        }
        if verdict_v2
        else None
    )
    summary = {
        "schema": "cdmw_mesh_visual_audit_summary_v2" if verdict_v2 else "cdmw_mesh_visual_audit_summary_v1",
        "compatible_reader_schemas": ["cdmw_mesh_visual_audit_summary_v1"] if verdict_v2 else [],
        "status": "complete_visual_review",
        "run_id": run_id,
        "asset_count": len(summary_rows),
        "pass_count": counts["PASS"],
        "concern_count": counts["CONCERN"],
        "fail_count": counts["FAIL"],
        "unreviewed_count": 0,
        "material_classification_required": require_material_classification,
        "archive_browser_batch_ok": archive_browser_batch_ok,
        "dotnet_batch_ok": dotnet_batch_ok,
        "integrity_ok": integrity_ok,
        "integrity_recomputed": recomputed_integrity,
        "archive_sources_unchanged": archive_sources_unchanged,
        "prepared_package_state_ok": package_state_ok,
        "prepared_packages_unchanged": prepared_packages_unchanged,
        "renderer_session": dict(dotnet_report.get("renderer_session", {}) or {}),
        "assets": summary_rows,
        "visible_submesh_count": sum(len(tuple(row.get("material_regions", ()) or ())) for row in summary_rows),
        "full_model_direct_review_count": sum(
            row.get("full_model_direct_image_inspection") is True for row in summary_rows
        ),
        "full_model_angle_direct_review_count": sum(
            angle_review.get("direct_image_inspection") is True
            for row in summary_rows
            for angle_review in tuple(row.get("full_model_angle_reviews", ()) or ())
            if isinstance(angle_review, Mapping)
        ),
        "contact_sheet_direct_review_count": sum(
            row.get("full_model_contact_sheet_direct_image_inspection") is True
            for row in summary_rows
        ),
        "source_board_direct_review_count": sum(
            region.get("source_board_direct_image_inspection") is True
            for row in summary_rows
            for region in tuple(row.get("material_regions", ()) or ())
            if isinstance(region, Mapping)
        ),
        "submesh_review_sheet_direct_review_count": sum(
            region.get("review_sheet_direct_image_inspection") is True
            for row in summary_rows
            for region in tuple(row.get("material_regions", ()) or ())
            if isinstance(region, Mapping)
        ),
        "geometry_coherent_asset_count": sum(
            row.get("full_model_geometry_coherent") is True for row in summary_rows
        ),
        "geometry_coherent_submesh_count": sum(
            region.get("geometry_coherent") is True
            for row in summary_rows
            for region in tuple(row.get("material_regions", ()) or ())
            if isinstance(region, Mapping)
        ),
        "reference_status_counts": dict(
            Counter(str(row.get("reference_status", "") or "") for row in summary_rows)
        ),
        "source_board_coverage_ok": source_board_coverage_ok,
        "semantic_conservation_ok": semantic_conservation_ok,
        "acceptance_checks": acceptance_checks,
        "acceptance_ok": (
            all(acceptance_checks.values()) if acceptance_checks is not None else None
        ),
        "scope_note": "CDMW visual/material consistency only; not real-game parity proof.",
    }
    _atomic_write_json(evidence_root / "summary.json", summary)
    _atomic_write_text(evidence_root / "review.md", "\n".join(review_lines).rstrip() + "\n")
    _atomic_write_json(evidence_root / "runtime" / "final-review.json", summary)
    return summary


def _validate_v2_full_model_evidence(
    composite: Mapping[str, object],
    *,
    evidence_root: Path | None = None,
) -> dict[str, object]:
    expected_angles = tuple(str(row["name"]) for row in VISUAL_AUDIT_VIEWS)
    candidates = composite.get("candidate_comparisons", {})
    hashes = composite.get("candidate_comparison_sha256", {})
    if (
        not isinstance(candidates, Mapping)
        or len(candidates) != len(expected_angles)
        or set(candidates) != set(expected_angles)
    ):
        raise ValueError("Visual-audit v2 full-model comparisons must contain all six angles.")
    if (
        not isinstance(hashes, Mapping)
        or len(hashes) != len(expected_angles)
        or set(hashes) != set(expected_angles)
    ):
        raise ValueError("Visual-audit v2 full-model comparison hashes must match all six angles.")
    comparisons = {
        angle: _verified_evidence_file(
            str(candidates.get(angle, "") or ""),
            str(hashes.get(angle, "") or ""),
            label=f"full-model comparison {angle}",
            required_root=(evidence_root / "comparisons") if evidence_root else None,
        )
        for angle in expected_angles
    }
    if len(set(comparisons.values())) != len(comparisons):
        raise ValueError("Every v2 full-model angle requires a distinct comparison file.")
    contact_sheet = _verified_evidence_file(
        str(composite.get("contact_sheet", "") or ""),
        str(composite.get("contact_sheet_sha256", "") or ""),
        label="multi-angle contact sheet",
        required_root=(evidence_root / "contact-sheets") if evidence_root else None,
    )
    if contact_sheet in set(comparisons.values()):
        raise ValueError("The v2 contact sheet must be distinct from every angle comparison.")
    return {
        "comparisons": comparisons,
        "comparison_sha256": {angle: str(hashes[angle]).casefold() for angle in expected_angles},
        "contact_sheet": contact_sheet,
        "contact_sheet_sha256": str(composite["contact_sheet_sha256"]).casefold(),
    }


def _validate_v2_asset_verdict(
    asset_verdict: Mapping[str, object],
    corpus_row: Mapping[str, object],
) -> dict[str, object]:
    overall = str(asset_verdict.get("overall_verdict", "") or "")
    if overall not in _VERDICTS:
        raise ValueError(f"Invalid v2 asset overall_verdict: {overall!r}")
    defect_categories = {
        str(value) for value in tuple(asset_verdict.get("defect_categories", ()) or ())
    }
    if not defect_categories <= _DEFECT_CATEGORIES:
        raise ValueError(
            "Invalid v2 asset defect categories: "
            f"{sorted(defect_categories - _DEFECT_CATEGORIES)}"
        )
    confidence = str(asset_verdict.get("confidence", "") or "")
    if confidence and confidence not in _CONFIDENCE:
        raise ValueError(f"Invalid v2 asset confidence: {confidence!r}")
    expected_angles = tuple(str(row["name"]) for row in VISUAL_AUDIT_VIEWS)
    raw_angle_reviews = tuple(asset_verdict.get("full_model_angle_reviews", ()) or ())
    if len(raw_angle_reviews) != len(expected_angles) or any(
        not isinstance(row, Mapping) for row in raw_angle_reviews
    ):
        raise ValueError("Every v2 asset requires one review row for each full-model angle.")
    angle_reviews: list[dict[str, object]] = []
    for expected_angle, raw_row in zip(expected_angles, raw_angle_reviews, strict=True):
        row = raw_row if isinstance(raw_row, Mapping) else {}
        angle = str(row.get("angle", "") or "")
        if angle != expected_angle:
            raise ValueError("Full-model angle review order must exactly match all six captures.")
        if row.get("direct_image_inspection") is not True:
            raise ValueError(f"Full-model angle {angle!r} requires direct image inspection.")
        visual_observations = str(row.get("visual_observations", "") or "").strip()
        if not visual_observations:
            raise ValueError(f"Full-model angle {angle!r} requires visual observations.")
        angle_geometry_coherent = row.get("geometry_coherent")
        if not isinstance(angle_geometry_coherent, bool):
            raise ValueError(f"Full-model angle {angle!r} requires a geometry verdict.")
        angle_geometry_observations = str(
            row.get("geometry_observations", "") or ""
        ).strip()
        if not angle_geometry_observations:
            raise ValueError(f"Full-model angle {angle!r} requires geometry observations.")
        angle_verdict = str(row.get("verdict", "") or "")
        if angle_verdict not in _VERDICTS:
            raise ValueError(f"Full-model angle {angle!r} requires a visual verdict.")
        if angle_geometry_coherent is False and angle_verdict != "FAIL":
            raise ValueError(f"Broken geometry in full-model angle {angle!r} must receive FAIL.")
        angle_reviews.append(
            {
                "angle": angle,
                "direct_image_inspection": True,
                "visual_observations": visual_observations,
                "geometry_coherent": angle_geometry_coherent,
                "geometry_observations": angle_geometry_observations,
                "verdict": angle_verdict,
            }
        )
    if asset_verdict.get("full_model_contact_sheet_direct_image_inspection") is not True:
        raise ValueError("Every v2 asset requires direct contact-sheet image inspection.")
    contact_sheet_observations = str(
        asset_verdict.get("full_model_contact_sheet_observations", "") or ""
    ).strip()
    if not contact_sheet_observations:
        raise ValueError("Every v2 asset requires contact-sheet observations.")
    contact_sheet_verdict = str(
        asset_verdict.get("full_model_contact_sheet_verdict", "") or ""
    )
    if contact_sheet_verdict not in _VERDICTS:
        raise ValueError("Every v2 asset requires a contact-sheet visual verdict.")
    geometry_coherent = asset_verdict.get("full_model_geometry_coherent")
    if not isinstance(geometry_coherent, bool):
        raise ValueError("Every v2 asset requires an explicit full-model geometry verdict.")
    if geometry_coherent != all(
        row["geometry_coherent"] is True for row in angle_reviews
    ):
        raise ValueError("The full-model geometry verdict must match all six angle reviews.")
    geometry_observations = str(
        asset_verdict.get("full_model_geometry_observations", "") or ""
    ).strip()
    if not geometry_observations:
        raise ValueError("Every v2 asset requires full-model geometry observations.")
    if geometry_coherent is False and overall != "FAIL":
        raise ValueError("Broken full-model geometry must receive an asset FAIL verdict.")

    category = str(corpus_row.get("model_category", "") or "")
    reference_status = str(asset_verdict.get("reference_status", "") or "")
    if reference_status not in _REFERENCE_STATUSES:
        raise ValueError(f"Invalid v2 equipment reference status: {reference_status!r}")
    if category == "regression_control":
        if reference_status != "not_applicable_control":
            raise ValueError("Regression controls must use not_applicable_control reference status.")
    elif reference_status == "not_applicable_control":
        raise ValueError("Equipment rows cannot use not_applicable_control reference status.")
    reference_identity = str(asset_verdict.get("reference_identity", "") or "").strip()
    reference_urls = tuple(
        str(value).strip()
        for value in tuple(asset_verdict.get("reference_urls", ()) or ())
    )
    if any(not value for value in reference_urls):
        raise ValueError("Equipment reference URLs must not contain empty entries.")
    if any(not value.casefold().startswith(("https://", "http://")) for value in reference_urls):
        raise ValueError("Equipment reference URLs must use HTTP or HTTPS.")
    if reference_status in {
        "exact_item",
        "shared_model_identity",
        "archive_related_candidate",
    } and not reference_identity:
        raise ValueError("Resolved or candidate equipment references require an identity.")
    if reference_status in {"exact_item", "shared_model_identity"} and not reference_urls:
        raise ValueError("Exact or shared-model equipment references require public URLs.")
    if reference_status in {"reference_unavailable", "not_applicable_control"} and (
        reference_identity or reference_urls
    ):
        raise ValueError("Unavailable or inapplicable references cannot claim an item identity.")
    reference_observations = str(
        asset_verdict.get("reference_observations", "") or ""
    ).strip()
    if not reference_observations:
        raise ValueError("Every v2 asset requires reference observations or an unavailable reason.")

    virtual_path = str(corpus_row.get("virtual_path", "") or "")
    reported_target_match: bool | None = None
    reported_target_observations = ""
    if virtual_path.casefold() == REQUIRED_SWORD_PATH.casefold():
        raw_target_match = asset_verdict.get("reported_target_match")
        if not isinstance(raw_target_match, bool):
            raise ValueError("The reported sword requires an explicit target-match verdict.")
        reported_target_match = raw_target_match
        reported_target_observations = str(
            asset_verdict.get("reported_target_observations", "") or ""
        ).strip()
        if not reported_target_observations:
            raise ValueError("The reported sword requires target-match observations.")
        if reported_target_match is False and overall != "FAIL":
            raise ValueError("A reported-sword target mismatch must receive an asset FAIL verdict.")
    else:
        raw_target_match = asset_verdict.get("reported_target_match")
        if raw_target_match not in {None, "not_applicable"}:
            raise ValueError("Only the reported sword may carry a target-match verdict.")
        if str(asset_verdict.get("reported_target_observations", "") or "").strip():
            raise ValueError("Only the reported sword may carry target-match observations.")

    return {
        "full_model_reviewed_angles": list(expected_angles),
        "full_model_angle_reviews": angle_reviews,
        "full_model_direct_image_inspection": True,
        "full_model_contact_sheet_direct_image_inspection": True,
        "full_model_contact_sheet_observations": contact_sheet_observations,
        "full_model_contact_sheet_verdict": contact_sheet_verdict,
        "full_model_geometry_coherent": geometry_coherent,
        "full_model_geometry_observations": geometry_observations,
        "reference_status": reference_status,
        "reference_identity": reference_identity,
        "reference_urls": list(reference_urls),
        "reference_observations": reference_observations,
        "reported_target_match": reported_target_match,
        "reported_target_observations": reported_target_observations,
    }


def _validate_v2_unique_evidence_paths(summary_rows: list[dict[str, object]]) -> None:
    evidence_paths: list[tuple[str, str]] = []
    for row in summary_rows:
        asset_id = str(row.get("id", "") or "")
        comparisons = row.get("full_model_comparisons", {})
        if isinstance(comparisons, Mapping):
            evidence_paths.extend(
                (f"{asset_id} full-model {angle}", str(path))
                for angle, path in comparisons.items()
            )
        evidence_paths.append(
            (
                f"{asset_id} contact sheet",
                str(row.get("multi_angle_contact_sheet", "") or ""),
            )
        )
        for region in tuple(row.get("material_regions", ()) or ()):
            if isinstance(region, Mapping):
                index = int(region.get("source_submesh_index", -1))
                evidence_paths.extend(
                    (
                        (
                            f"{asset_id} submesh {index} review sheet",
                            str(region.get("review_sheet", "") or ""),
                        ),
                        (
                            f"{asset_id} submesh {index} source board",
                            str(region.get("source_board", "") or ""),
                        ),
                    )
                )
    if not evidence_paths or any(not path for _, path in evidence_paths):
        raise ValueError("Visual-audit v2 requires a distinct file for every evidence record.")
    seen: dict[str, str] = {}
    for label, path in evidence_paths:
        path_key = os.path.normcase(os.path.abspath(path))
        previous = seen.setdefault(path_key, label)
        if previous != label:
            raise ValueError(
                f"Visual-audit v2 evidence file is reused by {previous} and {label}."
            )


def _validate_v2_material_region_verdicts(
    asset_verdict: Mapping[str, object],
    composite_regions: tuple[object, ...],
    corpus_row: Mapping[str, object],
    *,
    evidence_root: Path | None = None,
) -> list[dict[str, object]]:
    if not composite_regions or any(not isinstance(row, Mapping) for row in composite_regions):
        raise ValueError("Visual-audit v2 composites require one mapping per visible submesh.")
    expected = [
        int(row.get("source_submesh_index", -1))
        for row in composite_regions
        if isinstance(row, Mapping)
    ]
    raw_material_rows = tuple(asset_verdict.get("material_regions", ()) or ())
    if not raw_material_rows or any(not isinstance(row, Mapping) for row in raw_material_rows):
        raise ValueError("Visual-audit v2 material_regions must contain only review objects.")
    raw_rows = [row for row in raw_material_rows if isinstance(row, Mapping)]
    actual = [int(row.get("source_submesh_index", -1)) for row in raw_rows]
    if not expected or actual != expected:
        raise ValueError(
            "Visual-audit v2 material-region verdict order must exactly match every visible submesh."
        )
    source_boards = corpus_row.get("source_boards", {})
    raw_corpus_boards = tuple(
        source_boards.get("boards", ()) if isinstance(source_boards, Mapping) else ()
    )
    if not raw_corpus_boards or any(not isinstance(row, Mapping) for row in raw_corpus_boards):
        raise ValueError("Visual-audit v2 source boards must contain only evidence objects.")
    corpus_boards = [row for row in raw_corpus_boards if isinstance(row, Mapping)]
    try:
        corpus_board_indices = [int(row.get("submesh_index", -1)) for row in corpus_boards]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Visual-audit v2 corpus source-board indices are invalid.") from exc
    if corpus_board_indices != expected:
        raise ValueError("Visual-audit v2 source boards must exactly match every visible submesh.")
    normalized: list[dict[str, object]] = []
    for row, composite, corpus_board in zip(
        raw_rows,
        composite_regions,
        corpus_boards,
        strict=True,
    ):
        classification = str(row.get("classification", "") or "")
        if classification not in _MATERIAL_CLASSIFICATIONS:
            raise ValueError(f"Invalid submesh material classification: {classification!r}")
        verdict = str(row.get("verdict", "") or "")
        if verdict not in _VERDICTS:
            raise ValueError(f"Invalid submesh visual verdict: {verdict!r}")
        geometry_coherent = row.get("geometry_coherent")
        if not isinstance(geometry_coherent, bool):
            raise ValueError("Every v2 submesh requires an explicit geometry verdict.")
        geometry_observations = str(row.get("geometry_observations", "") or "").strip()
        if not geometry_observations:
            raise ValueError("Every v2 submesh requires geometry observations.")
        if geometry_coherent is False and verdict != "FAIL":
            raise ValueError("Broken submesh geometry must receive a FAIL verdict.")
        confidence = str(row.get("confidence", "") or "")
        if confidence not in _CONFIDENCE:
            raise ValueError(f"Invalid submesh confidence: {confidence!r}")
        if row.get("source_board_direct_image_inspection") is not True:
            raise ValueError("Every v2 submesh requires separate direct source-board inspection.")
        if row.get("review_sheet_direct_image_inspection") is not True:
            raise ValueError("Every v2 submesh requires separate direct review-sheet inspection.")
        if not isinstance(row.get("automated_metrics_only"), bool):
            raise ValueError("Every v2 submesh requires an explicit automated-metrics-only flag.")
        if verdict == "PASS" and row.get("automated_metrics_only") is True:
            raise ValueError("Automated image metrics cannot issue a visual PASS.")
        for key in (
            "classification_basis",
            "source_map_observations",
            "pac_evidence",
            "render_observations",
        ):
            if not _has_evidence(row.get(key)):
                raise ValueError(f"Visual-audit v2 submesh evidence is empty: {key}")
        unsupported = tuple(str(value).strip() for value in tuple(row.get("unsupported_features", ()) or ()))
        if any(not value for value in unsupported):
            raise ValueError("Submesh unsupported_features entries must be non-empty.")
        composite_row = composite if isinstance(composite, Mapping) else {}
        review_sheet = _verified_evidence_path(
            composite_row,
            path_key="review_sheet",
            sha256_key="review_sheet_sha256",
            required_root=(evidence_root / "material-region-sheets") if evidence_root else None,
        )
        source_board = _verified_evidence_path(
            composite_row,
            path_key="source_board",
            sha256_key="source_board_sha256",
            required_root=(evidence_root / "source-boards") if evidence_root else None,
        )
        corpus_source_board = _verified_evidence_path(
            corpus_board,
            path_key="path",
            sha256_key="sha256",
            required_root=(evidence_root / "source-boards") if evidence_root else None,
        )
        if (
            source_board != corpus_source_board
            or str(composite_row.get("source_board_sha256", "") or "").casefold()
            != str(corpus_board.get("sha256", "") or "").casefold()
        ):
            raise ValueError("A v2 submesh source board does not match its frozen corpus evidence.")
        normalized.append(
            {
                "source_submesh_index": int(row["source_submesh_index"]),
                "classification": classification,
                "classification_basis": row["classification_basis"],
                "source_map_observations": row["source_map_observations"],
                "pac_evidence": row["pac_evidence"],
                "render_observations": row["render_observations"],
                "geometry_observations": geometry_observations,
                "geometry_coherent": geometry_coherent,
                "confidence": confidence,
                "unsupported_features": list(unsupported),
                "unsupported_feature_unchanged": row.get("unsupported_feature_unchanged") is True,
                "automated_metric_flags": list(tuple(row.get("automated_metric_flags", ()) or ())),
                "source_board_direct_image_inspection": True,
                "review_sheet_direct_image_inspection": True,
                "direct_image_inspection": True,
                "verdict": verdict,
                "review_sheet": review_sheet,
                "source_board": source_board,
                "binding_conservation": dict(composite_row.get("binding_conservation", {}) or {}),
            }
        )
    image_verdicts = [str(row["verdict"]) for row in normalized]
    image_verdicts.extend(
        str(row.get("verdict", "") or "")
        for row in tuple(asset_verdict.get("full_model_angle_reviews", ()) or ())
        if isinstance(row, Mapping) and str(row.get("verdict", "") or "") in _VERDICTS
    )
    contact_sheet_verdict = str(
        asset_verdict.get("full_model_contact_sheet_verdict", "") or ""
    )
    if contact_sheet_verdict in _VERDICTS:
        image_verdicts.append(contact_sheet_verdict)
    expected_overall = _worst_verdict(image_verdicts)
    if (
        asset_verdict.get("full_model_geometry_coherent") is False
        or asset_verdict.get("reported_target_match") is False
    ):
        expected_overall = "FAIL"
    if str(asset_verdict.get("overall_verdict", "") or "") != expected_overall:
        raise ValueError("Asset overall_verdict must equal its worst reviewed-image verdict.")
    return normalized


def _verified_evidence_path(
    row: Mapping[str, object],
    *,
    path_key: str,
    sha256_key: str,
    required_root: Path | None = None,
) -> str:
    return _verified_evidence_file(
        str(row.get(path_key, "") or ""),
        str(row.get(sha256_key, "") or ""),
        label=path_key,
        required_root=required_root,
    )


def _verified_evidence_file(
    value: str,
    expected_sha256: str,
    *,
    label: str,
    required_root: Path | None = None,
) -> str:
    path = Path(value).resolve()
    if not value or not path.is_file():
        raise ValueError(f"Visual-audit v2 evidence file is missing: {label}")
    if required_root is not None and not path.is_relative_to(Path(required_root).resolve()):
        raise ValueError(f"Visual-audit v2 evidence file is outside its owned root: {label}")
    expected_sha256 = expected_sha256.casefold()
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise ValueError(f"Visual-audit v2 evidence hash is invalid: {label}")
    if _sha256_file(path) != expected_sha256:
        raise ValueError(f"Visual-audit v2 evidence hash changed: {label}")
    return str(path)


def _has_evidence(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value) and any(_has_evidence(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return bool(value) and any(_has_evidence(child) for child in value)
    return value is not None


def _worst_verdict(values: object) -> str:
    ranks = {"PASS": 0, "CONCERN": 1, "FAIL": 2}
    rows = [str(value) for value in values]
    return max(rows, key=lambda value: ranks.get(value, 3), default="FAIL")


def _minimum_region_confidence(rows: list[dict[str, object]]) -> str:
    ranks = {"high": 0, "medium": 1, "low": 2}
    values = [str(row.get("confidence", "low")) for row in rows]
    return max(values, key=lambda value: ranks.get(value, 2), default="low")


def _payload_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").casefold()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _v2_package_state_ok(
    package_state: Mapping[str, object],
    *,
    corpus: Mapping[str, object],
    evidence_root: Path,
    expected_ids: list[str],
) -> bool:
    try:
        if (
            str(package_state.get("schema", "") or "")
            != "cdmw_mesh_visual_audit_package_state_v1"
            or str(package_state.get("run_id", "") or "")
            != str(corpus.get("run_id", "") or "")
            or Path(str(package_state.get("evidence_root", "") or "")).resolve()
            != evidence_root.resolve()
            or str(package_state.get("corpus_sha256", "") or "")
            != _payload_sha256(corpus)
        ):
            return False
        state_ids = [str(value) for value in tuple(package_state.get("asset_ids", ()) or ())]
        runtime_assets = tuple(package_state.get("runtime_assets", ()) or ())
        if (
            state_ids != expected_ids
            or len(runtime_assets) != len(expected_ids)
            or any(not isinstance(row, Mapping) for row in runtime_assets)
        ):
            return False
        temporary_root = Path(str(package_state.get("temporary_root", "") or "")).resolve()
        if not temporary_root.is_dir():
            return False
        seen_package_roots: set[str] = set()
        for expected_id, raw_row in zip(expected_ids, runtime_assets, strict=True):
            row = raw_row if isinstance(raw_row, Mapping) else {}
            if (
                str(row.get("id", "") or "") != expected_id
                or str(row.get("run_id", "") or "")
                != str(corpus.get("run_id", "") or "")
            ):
                return False
            for key in ("archive_package_dir", "dotnet_package_dir"):
                package_root = Path(str(row.get(key, "") or "")).resolve()
                folded = str(package_root).casefold()
                if (
                    not package_root.is_dir()
                    or not package_root.is_relative_to(temporary_root)
                    or folded in seen_package_roots
                ):
                    return False
                seen_package_roots.add(folded)
        archive_paths = [
            Path(str(value)).resolve()
            for value in tuple(package_state.get("archive_fingerprint_paths", ()) or ())
        ]
        return (
            bool(archive_paths)
            and len({str(path).casefold() for path in archive_paths}) == len(archive_paths)
            and all(path.is_file() for path in archive_paths)
        )
    except (OSError, TypeError, ValueError, OverflowError):
        return False


def _v2_archive_fingerprints_unchanged(
    before: Mapping[str, object],
    after: Mapping[str, object],
    expected_paths: tuple[object, ...],
) -> bool:
    if not before or before != after:
        return False
    try:
        resolved_expected = [str(Path(str(value)).resolve()) for value in expected_paths]
        expected_keys = [os.path.normcase(path) for path in resolved_expected]
        if not resolved_expected or len(set(expected_keys)) != len(expected_keys):
            return False
        keyed_rows = {
            os.path.normcase(str(Path(str(key)).resolve())): value
            for key, value in before.items()
        }
        if set(keyed_rows) != set(expected_keys) or len(keyed_rows) != len(before):
            return False
        for path_text, path_key in zip(resolved_expected, expected_keys, strict=True):
            row = keyed_rows[path_key]
            path = Path(path_text)
            if (
                not isinstance(row, Mapping)
                or row.get("exists") is not True
                or not _is_sha256(row.get("sha256"))
                or type(row.get("size")) is not int
                or int(row["size"]) <= 0
                or not path.is_file()
                or int(path.stat().st_size) != int(row["size"])
            ):
                return False
        return True
    except (OSError, TypeError, ValueError, OverflowError):
        return False


def _v2_prepared_package_seal_ok(
    seal: Mapping[str, object],
    *,
    run_id: str,
    corpus_sha256: str,
    expected_ids: list[str],
) -> bool:
    if (
        set(seal)
        != {
            "schema",
            "run_id",
            "corpus_sha256",
            "asset_count",
            "assets",
            "aggregate_sha256",
        }
        or str(seal.get("schema", "") or "")
        != "cdmw_mesh_visual_audit_prepared_package_fingerprints_v1"
        or str(seal.get("run_id", "") or "") != run_id
        or str(seal.get("corpus_sha256", "") or "") != corpus_sha256
        or type(seal.get("asset_count")) is not int
        or int(seal["asset_count"]) != len(expected_ids)
        or not _is_sha256(seal.get("aggregate_sha256"))
    ):
        return False
    asset_rows = tuple(seal.get("assets", ()) or ())
    if len(asset_rows) != len(expected_ids) or any(
        not isinstance(row, Mapping) for row in asset_rows
    ):
        return False
    for expected_id, raw_row in zip(expected_ids, asset_rows, strict=True):
        row = raw_row if isinstance(raw_row, Mapping) else {}
        if set(row) != {"id", "archive_package_dir", "dotnet_package_dir"}:
            return False
        if str(row.get("id", "") or "") != expected_id:
            return False
        for key in ("archive_package_dir", "dotnet_package_dir"):
            tree = row.get(key, {})
            if (
                not isinstance(tree, Mapping)
                or set(tree) != {"file_count", "total_bytes", "tree_sha256"}
                or type(tree.get("file_count")) is not int
                or int(tree["file_count"]) <= 0
                or type(tree.get("total_bytes")) is not int
                or int(tree["total_bytes"]) < 0
                or not _is_sha256(tree.get("tree_sha256"))
            ):
                return False
    encoded_assets = json.dumps(
        list(asset_rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded_assets).hexdigest() == str(
        seal.get("aggregate_sha256", "") or ""
    ).casefold()


def _semantic_conservation_ok(corpus_rows: list[Mapping[str, object]]) -> bool:
    if not corpus_rows:
        return False
    for asset in corpus_rows:
        try:
            submesh_count = int(asset.get("submesh_count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        raw_rows = tuple(asset.get("binding_conservation", ()) or ())
        if any(not isinstance(row, Mapping) for row in raw_rows):
            return False
        rows = [row for row in raw_rows if isinstance(row, Mapping)]
        if submesh_count <= 0 or len(rows) != submesh_count:
            return False
        if not all(
            row.get("conserved") is True
            and not tuple(row.get("dropped_parameters", ()) or ())
            and not tuple(row.get("cross_owner_bindings", ()) or ())
            and not tuple(row.get("layer_as_base_bindings", ()) or ())
            for row in rows
        ):
            return False
        equivalence = asset.get("initial_resident_material_equivalence", {})
        if (
            not isinstance(equivalence, Mapping)
            or equivalence.get("equivalent") is not True
            or tuple(equivalence.get("mismatches", ()) or ())
        ):
            return False
    return True


def _source_board_coverage_ok(corpus_rows: list[Mapping[str, object]]) -> bool:
    if not corpus_rows:
        return False
    for asset in corpus_rows:
        try:
            submesh_count = int(asset.get("submesh_count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        source_boards = asset.get("source_boards", {})
        if not isinstance(source_boards, Mapping) or submesh_count <= 0:
            return False
        raw_boards = tuple(source_boards.get("boards", ()) or ())
        if any(not isinstance(row, Mapping) for row in raw_boards):
            return False
        boards = [row for row in raw_boards if isinstance(row, Mapping)]
        try:
            indices = [int(row.get("submesh_index", -1)) for row in boards]
        except (TypeError, ValueError, OverflowError):
            return False
        if indices != list(range(submesh_count)):
            return False
        for row in boards:
            path = str(row.get("path", "") or "")
            sha256 = str(row.get("sha256", "") or "").casefold()
            if (
                not path
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256)
            ):
                return False
    return True


def _v2_corpus_acceptance_ok(
    corpus: Mapping[str, object],
    *,
    expected_asset_count: int | None = None,
) -> bool:
    if str(corpus.get("schema", "") or "") != "cdmw_mesh_visual_audit_corpus_v2":
        return False
    raw_rows = tuple(corpus.get("assets", ()) or ())
    if any(not isinstance(row, Mapping) for row in raw_rows):
        return False
    rows = [row for row in raw_rows if isinstance(row, Mapping)]
    # Take the requirement from the corpus's own declaration, not from the rows
    # it happens to carry. Deriving it from len(rows) makes the row-count check
    # tautological, so a truncated corpus would score itself as complete.
    asset_count = int(corpus.get("asset_count", 0) or 0)
    if expected_asset_count is not None and asset_count != int(expected_asset_count):
        return False
    try:
        required_category_counts, graph_minimums = (
            visual_audit_v2_contract_for_asset_count(asset_count)
        )
    except ValueError:
        return False
    if len(rows) != asset_count:
        return False
    ids = [str(row.get("asset_id", "") or "") for row in rows]
    paths = [str(row.get("virtual_path", "") or "") for row in rows]
    indices = [int(row.get("index", 0) or 0) for row in rows]
    if (
        not all(ids)
        or not all(paths)
        or len(set(ids)) != asset_count
        or len({path.casefold() for path in paths}) != asset_count
        or indices != list(range(1, asset_count + 1))
    ):
        return False
    category_counts = Counter(str(row.get("model_category", "") or "") for row in rows)
    if dict(category_counts) != dict(required_category_counts):
        return False
    coverage = corpus.get("coverage", {})
    if not isinstance(coverage, Mapping) or any(
        int(coverage.get(key, 0) or 0) < minimum
        for key, minimum in graph_minimums.items()
    ):
        return False
    folded_paths = {path.casefold() for path in paths}
    return {
        REQUIRED_SWORD_PATH.casefold(),
        PRIOR_CONCERN_SWORD_PATH.casefold(),
    }.issubset(folded_paths)


def _v2_acceptance_ok(
    summary_rows: list[dict[str, object]],
    corpus_rows: list[Mapping[str, object]],
) -> bool:
    corpus_by_id = {str(row.get("asset_id", "")): row for row in corpus_rows}
    target_required = any(
        str(row.get("virtual_path", "") or "").casefold() == REQUIRED_SWORD_PATH.casefold()
        for row in corpus_rows
    )
    reported_target_seen = not target_required
    for row in summary_rows:
        corpus_row = corpus_by_id.get(str(row.get("id", "")), {})
        category = str(corpus_row.get("model_category", ""))
        overall = str(row.get("overall_verdict", ""))
        regions = tuple(row.get("material_regions", ()) or ())
        angle_reviews = tuple(row.get("full_model_angle_reviews", ()) or ())
        if (
            row.get("full_model_direct_image_inspection") is not True
            or row.get("full_model_contact_sheet_direct_image_inspection") is not True
            or row.get("full_model_geometry_coherent") is not True
            or len(angle_reviews) != len(VISUAL_AUDIT_VIEWS)
            or any(
                not isinstance(angle_review, Mapping)
                or angle_review.get("direct_image_inspection") is not True
                or angle_review.get("geometry_coherent") is not True
                or str(angle_review.get("verdict", "") or "") not in _VERDICTS
                for angle_review in angle_reviews
            )
            or str(row.get("full_model_contact_sheet_verdict", "") or "") not in _VERDICTS
            or not regions
            or any(
                not isinstance(region, Mapping)
                or region.get("direct_image_inspection") is not True
                or region.get("source_board_direct_image_inspection") is not True
                or region.get("review_sheet_direct_image_inspection") is not True
                or region.get("geometry_coherent") is not True
                for region in regions
            )
        ):
            return False
        if str(corpus_row.get("virtual_path", "") or "").casefold() == REQUIRED_SWORD_PATH.casefold():
            reported_target_seen = True
            if row.get("reported_target_match") is not True:
                return False
        if category != "regression_control" and overall != "PASS":
            return False
        if category == "regression_control":
            if overall == "FAIL":
                return False
            if overall == "CONCERN":
                concern_regions = [
                    region
                    for region in regions
                    if isinstance(region, Mapping) and region.get("verdict") == "CONCERN"
                ]
                if not concern_regions or not all(
                    tuple(region.get("unsupported_features", ()) or ())
                    and region.get("unsupported_feature_unchanged") is True
                    for region in concern_regions
                ):
                    return False
    return reported_target_seen and _semantic_conservation_ok(corpus_rows)


def _validate_verdict_row(
    row: Mapping[str, object],
    *,
    require_material_classification: bool = False,
) -> None:
    for key in ("archive_browser_verdict", "mesh_editor_verdict", "overall_verdict"):
        if str(row.get(key, "")) not in _VERDICTS:
            raise ValueError(f"Invalid visual-audit verdict {key}: {row.get(key)!r}")
    if str(row.get("confidence", "")) not in _CONFIDENCE:
        raise ValueError(f"Invalid visual-audit confidence: {row.get('confidence')!r}")
    categories = {str(value) for value in tuple(row.get("defect_categories", ()) or ())}
    if not categories <= _DEFECT_CATEGORIES:
        raise ValueError(f"Invalid visual-audit defect categories: {sorted(categories - _DEFECT_CATEGORIES)}")
    material_classification = {
        str(value) for value in tuple(row.get("material_classification", ()) or ())
    }
    if require_material_classification and not material_classification:
        raise ValueError("Visual-audit material classification is required.")
    if not material_classification <= _MATERIAL_CLASSIFICATIONS:
        raise ValueError(
            "Invalid visual-audit material classifications: "
            f"{sorted(material_classification - _MATERIAL_CLASSIFICATIONS)}"
        )
    for key in (
        "selected_camera_angle",
        "visual_observations",
        "likely_cause",
        "code_changes_made",
        "targeted_validation_performed",
        "remaining_uncertainty",
    ):
        if not str(row.get(key, "") or "").strip():
            raise ValueError(f"Visual-audit verdict field is empty: {key}")


def _review_entry(row: Mapping[str, object]) -> list[str]:
    lines = [
        f"## {int(row['index']):03d} - {row['id']}",
        "",
        f"- PAC virtual path: `{row['pac_virtual_path']}`",
        f"- Archive provenance: `{json.dumps(row['archive_provenance'], sort_keys=True)}`",
        f"- Model category: `{row['model_category']}`",
        f"- Material families: `{', '.join(row['material_families'])}`",
        f"- Visual material classification: `{json.dumps(row['material_classification'])}`",
        f"- Selected camera angle: `{row['selected_camera_angle']}`",
    ]
    if row.get("full_model_direct_image_inspection") is True:
        lines.extend(
            [
                f"- Full-model reviewed angles: `{json.dumps(row['full_model_reviewed_angles'])}`",
                "- Full-model direct image inspection: True",
                f"- Full-model geometry coherent: {row['full_model_geometry_coherent']}",
                f"- Full-model geometry observations: {row['full_model_geometry_observations']}",
                "- Contact-sheet direct image inspection: True",
                f"- Contact-sheet observations: {row['full_model_contact_sheet_observations']}",
                f"- Contact-sheet verdict: {row['full_model_contact_sheet_verdict']}",
                f"- Reference status: `{row['reference_status']}`",
                f"- Reference identity: {row['reference_identity'] or 'None'}",
                f"- Reference URLs: `{json.dumps(row['reference_urls'])}`",
                f"- Reference observations: {row['reference_observations']}",
            ]
        )
        if row.get("reported_target_match") is not None:
            lines.extend(
                [
                    f"- Reported target match: {row['reported_target_match']}",
                    f"- Reported target observations: {row['reported_target_observations']}",
                ]
            )
        for angle_review in tuple(row.get("full_model_angle_reviews", ()) or ()):
            if not isinstance(angle_review, Mapping):
                continue
            lines.extend(
                [
                    f"### Full model - {angle_review['angle']}",
                    "",
                    f"- Direct image inspection: {angle_review['direct_image_inspection']}",
                    f"- Visual observations: {angle_review['visual_observations']}",
                    f"- Geometry coherent: {angle_review['geometry_coherent']}",
                    f"- Geometry observations: {angle_review['geometry_observations']}",
                    f"- Verdict: {angle_review['verdict']}",
                    "",
                ]
            )
    lines.extend(
        [
        f"- Archive Browser verdict: {row['archive_browser_verdict']}",
        f"- Mesh Editor verdict: {row['mesh_editor_verdict']}",
        f"- Overall verdict: {row['overall_verdict']}",
        f"- Defect categories: `{json.dumps(row['defect_categories'])}`",
        f"- Visual observations: {row['visual_observations']}",
        f"- Likely cause: {row['likely_cause']}",
        f"- Confidence: {row['confidence']}",
        f"- Code changes made: {row['code_changes_made']}",
        f"- Targeted validation performed: {row['targeted_validation_performed']}",
        f"- Remaining uncertainty: {row['remaining_uncertainty']}",
        f"- Primary comparison: `{row['primary_final_png']}`",
        f"- Multi-angle contact sheet: `{row['multi_angle_contact_sheet']}`",
        "",
        ]
    )
    for region in tuple(row.get("material_regions", ()) or ()):
        if not isinstance(region, Mapping):
            continue
        lines.extend(
            [
                f"### Submesh {int(region['source_submesh_index']):03d}",
                "",
                f"- Classification: `{region['classification']}`",
                f"- Classification basis: {_format_review_evidence(region['classification_basis'])}",
                f"- Source-map observations: {_format_review_evidence(region['source_map_observations'])}",
                f"- PAC evidence: {_format_review_evidence(region['pac_evidence'])}",
                f"- Render observations: {_format_review_evidence(region['render_observations'])}",
                f"- Geometry coherent: {region['geometry_coherent']}",
                f"- Geometry observations: {region['geometry_observations']}",
                f"- Confidence: {region['confidence']}",
                f"- Unsupported features: `{json.dumps(region['unsupported_features'])}`",
                f"- Source-board direct image inspection: {region['source_board_direct_image_inspection']}",
                f"- Review-sheet direct image inspection: {region['review_sheet_direct_image_inspection']}",
                f"- Verdict: {region['verdict']}",
                f"- Source board: `{region['source_board']}`",
                f"- Review sheet: `{region['review_sheet']}`",
                "",
            ]
        )
    return lines


def _format_review_evidence(value: object) -> str:
    if isinstance(value, str):
        return value
    return f"`{json.dumps(value, sort_keys=True)}`"


def _mapping_rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [row for row in tuple(payload.get(key, ()) or ()) if isinstance(row, Mapping)]


def _strict_mapping_rows(
    payload: Mapping[str, object],
    key: str,
) -> list[Mapping[str, object]]:
    raw_rows = tuple(payload.get(key, ()) or ())
    if not raw_rows or any(not isinstance(row, Mapping) for row in raw_rows):
        raise ValueError(f"Visual-audit v2 {key} must contain only review objects.")
    return [row for row in raw_rows if isinstance(row, Mapping)]


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Visual-audit JSON is not an object: {path}")
    return dict(payload)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: object) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["finalize_visual_audit_review"]
