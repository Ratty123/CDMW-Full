from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from collections.abc import Mapping
from pathlib import Path


_VERDICTS = {"PASS", "CONCERN", "FAIL"}
_CONFIDENCE = {"high", "medium", "low"}
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
    corpus_rows = _mapping_rows(corpus, "assets")
    expected_ids = [str(row.get("asset_id", "")) for row in corpus_rows]
    composite_map = {str(row.get("id", "")): row for row in _mapping_rows(composites, "assets")}
    archive_map = {str(row.get("id", "")): row for row in _mapping_rows(archive_report, "assets")}
    dotnet_map = {str(row.get("id", "")): row for row in _mapping_rows(dotnet_report, "assets")}
    verdict_rows = _mapping_rows(verdicts, "assets")
    verdict_map = {str(row.get("id", "")): row for row in verdict_rows}
    require_material_classification = verdicts.get("require_material_classification") is True
    if [str(row.get("id", "")) for row in verdict_rows] != expected_ids:
        raise ValueError("Visual-audit verdict order must exactly match the corpus.")
    if set(composite_map) != set(expected_ids):
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
        _validate_verdict_row(
            verdict,
            require_material_classification=require_material_classification,
        )
        composite = composite_map[asset_id]
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
        material_classification = [
            str(value) for value in tuple(verdict.get("material_classification", ()) or ())
        ]
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
            "archive_browser_verdict": str(verdict["archive_browser_verdict"]),
            "mesh_editor_verdict": str(verdict["mesh_editor_verdict"]),
            "overall_verdict": str(verdict["overall_verdict"]),
            "defect_categories": defect_categories,
            "visual_observations": str(verdict["visual_observations"]),
            "likely_cause": str(verdict["likely_cause"]),
            "confidence": str(verdict["confidence"]),
            "code_changes_made": str(verdict["code_changes_made"]),
            "targeted_validation_performed": str(verdict["targeted_validation_performed"]),
            "remaining_uncertainty": str(verdict["remaining_uncertainty"]),
            "primary_final_png": str(final_path),
            "primary_final_sha256": _sha256_file(final_path),
            "multi_angle_contact_sheet": str(composite.get("contact_sheet", "") or ""),
            "archive_browser_capture_ok": archive_row.get("ok") is True,
            "mesh_editor_capture_ok": dotnet_row.get("ok") is True,
        }
        summary_rows.append(summary_row)
        review_lines.extend(_review_entry(summary_row))

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
    summary = {
        "schema": "cdmw_mesh_visual_audit_summary_v1",
        "status": "complete_visual_review",
        "run_id": run_id,
        "asset_count": len(summary_rows),
        "pass_count": counts["PASS"],
        "concern_count": counts["CONCERN"],
        "fail_count": counts["FAIL"],
        "unreviewed_count": 0,
        "material_classification_required": require_material_classification,
        "archive_browser_batch_ok": archive_report.get("ok") is True,
        "dotnet_batch_ok": dotnet_report.get("ok") is True,
        "integrity_ok": integrity.get("ok") is True,
        "archive_sources_unchanged": bool(before) and before == after,
        "renderer_session": dict(dotnet_report.get("renderer_session", {}) or {}),
        "assets": summary_rows,
        "scope_note": "CDMW visual/material consistency only; not real-game parity proof.",
    }
    _atomic_write_json(evidence_root / "summary.json", summary)
    _atomic_write_text(evidence_root / "review.md", "\n".join(review_lines).rstrip() + "\n")
    _atomic_write_json(evidence_root / "runtime" / "final-review.json", summary)
    return summary


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
    return [
        f"## {int(row['index']):03d} - {row['id']}",
        "",
        f"- PAC virtual path: `{row['pac_virtual_path']}`",
        f"- Archive provenance: `{json.dumps(row['archive_provenance'], sort_keys=True)}`",
        f"- Model category: `{row['model_category']}`",
        f"- Material families: `{', '.join(row['material_families'])}`",
        f"- Visual material classification: `{json.dumps(row['material_classification'])}`",
        f"- Selected camera angle: `{row['selected_camera_angle']}`",
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


def _mapping_rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [row for row in tuple(payload.get(key, ()) or ()) if isinstance(row, Mapping)]


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
