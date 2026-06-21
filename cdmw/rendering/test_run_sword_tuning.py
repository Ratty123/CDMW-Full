from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping


TEST_RUN_SWORD_MANIFEST_SCHEMA_VERSION = 1
TEST_RUN_SWORD_SESSION_SCHEMA_VERSION = 1
TEST_RUN_SWORD_PACKAGE_MANIFEST_SCHEMA_VERSION = 1
TEST_RUN_SWORD_SYNC_SCHEMA_VERSION = 1
TEST_RUN_SWORD_STATUS_SCHEMA_VERSION = 1
TEST_RUN_SWORD_MINIMUM_VARIANTS = 20
_DEFAULT_CTF_ROOT = Path.home() / "Desktop" / "CTF"
TEST_RUN_SWORD_SOURCE_MOD = str(_DEFAULT_CTF_ROOT / "workspace" / "outputs" / "mod_packages" / "TestRunSword")
TEST_RUN_SWORD_DMM_MOD = r"C:\DMM\DMM 1.3.9B\mods\TestRunSword"
TEST_RUN_SWORD_OUTPUT_ROOT = str(_DEFAULT_CTF_ROOT / "benchmark_reports" / "TestRunSword_20run_material_tuning")

TEST_RUN_SWORD_BASELINE_SETTINGS = {
    "runtime_profile": "Material Authority",
    "gloss_matte_bias_percent": -10,
    "auto_brightness_percent": 0,
    "source_brightness_percent": 0,
    "tone_contrast_percent": -10,
    "edge_relief_percent": 0,
    "accent_glow_percent": 10,
}

_REQUESTED_RUN_ARTIFACTS = (
    "preview_screenshot",
    "in_game_screenshot",
    "package_manifest",
    "comparison_report",
)
_REQUESTED_RUN_FILES = (
    "mod_settings.json",
    "notes.md",
)
_TUNING_RECOMMENDATION_BY_DIAGNOSTIC = {
    "too_dark": {
        "code": "increase_preview_luma_or_source_brightness",
        "target": "preview",
        "message": "Preview is darker than the reference; raise source brightness slightly or lift the neutral metal base/tone response.",
    },
    "too_bright": {
        "code": "reduce_preview_luma_or_source_brightness",
        "target": "preview",
        "message": "Preview is brighter than the reference; lower source brightness or compress the metal base tone response.",
    },
    "too_saturated": {
        "code": "reduce_tint_or_mask_saturation",
        "target": "preview",
        "message": "Preview is more saturated than the reference; reduce tint strength or masked layer saturation.",
    },
    "too_dull": {
        "code": "increase_tint_or_mask_saturation",
        "target": "preview",
        "message": "Preview is less saturated than the reference; increase tint strength or masked green/gold/silver layer visibility.",
    },
    "too_glossy": {
        "code": "raise_roughness_or_reduce_reflection",
        "target": "preview",
        "message": "Preview has too many highlights; raise roughness or reduce specular/environment reflection.",
    },
    "too_matte": {
        "code": "lower_roughness_or_raise_reflection",
        "target": "preview",
        "message": "Preview lacks highlights; lower roughness or raise specular/environment reflection.",
    },
    "missing_gold": {
        "code": "increase_masked_gold_strength",
        "target": "masked_layers",
        "message": "Reference contains gold that preview under-represents; raise masked gold strength or mask contrast.",
    },
    "missing_silver": {
        "code": "increase_masked_silver_strength",
        "target": "masked_layers",
        "message": "Reference contains silver that preview under-represents; raise masked silver strength or neutral metal base visibility.",
    },
    "missing_green": {
        "code": "increase_masked_green_strength",
        "target": "masked_layers",
        "message": "Reference contains green that preview under-represents; raise masked green strength or mask visibility.",
    },
    "missing_red": {
        "code": "increase_red_gem_or_emissive_strength",
        "target": "gem_material",
        "message": "Reference contains red that preview under-represents; check gem base/emissive color and red channel handling.",
    },
    "unexpected_blue": {
        "code": "reduce_blue_gem_or_check_channel_swizzle",
        "target": "gem_material",
        "message": "Preview has more blue than the reference; check gem base/emissive color and possible red/blue channel swizzle.",
    },
    "missing_masked_details": {
        "code": "increase_masked_detail_contrast",
        "target": "masked_layers",
        "message": "Preview has weaker masked detail contrast than the reference; increase masked detail contrast before brightness hacks.",
    },
}


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_run_path(root: Path, run_dir: Path, value: object) -> Path:
    text = str(value or "").strip()
    if not text:
        return run_dir
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0].lower() == run_dir.name.lower():
        return root / path
    return run_dir / path


def build_test_run_sword_tuning_recommendations(comparison_report: Mapping[str, object] | object) -> list[dict[str, object]]:
    if isinstance(comparison_report, Mapping):
        report = comparison_report
    else:
        report = _read_json_object(Path(comparison_report).expanduser())
    recommendations: list[dict[str, object]] = []
    seen: set[str] = set()
    diagnostics = report.get("diagnostics", ()) if isinstance(report, Mapping) else ()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            continue
        code = str(diagnostic.get("code", "") or "")
        recommendation = _TUNING_RECOMMENDATION_BY_DIAGNOSTIC.get(code)
        if not recommendation or str(recommendation["code"]) in seen:
            continue
        item = dict(recommendation)
        item["source_diagnostic"] = code
        item["reference_target"] = str(diagnostic.get("target", "") or "")
        item["delta"] = diagnostic.get("delta", "")
        recommendations.append(item)
        seen.add(str(item["code"]))
    return recommendations


def _capture_input_policy(capture_report_path: Path) -> dict[str, object]:
    report = _read_json_object(capture_report_path)
    if not report:
        return {"status": "missing", "keys_sent": [], "non_e_keys": []}
    keys_sent: list[str] = []
    non_e_keys: list[str] = []
    for diagnostic in report.get("diagnostics", ()):
        if not isinstance(diagnostic, Mapping) or diagnostic.get("code") != "key_sent":
            continue
        key = str(diagnostic.get("key", "") or "").upper()
        if not key:
            continue
        keys_sent.append(key)
        if key != "E":
            non_e_keys.append(key)
    return {
        "status": "non_e_input_detected" if non_e_keys else "no_input_or_e_only",
        "keys_sent": keys_sent,
        "non_e_keys": non_e_keys,
    }


def build_test_run_sword_session_status(
    output_dir: object = TEST_RUN_SWORD_OUTPUT_ROOT,
    *,
    variants: int = TEST_RUN_SWORD_MINIMUM_VARIANTS,
) -> dict[str, object]:
    root = Path(output_dir).expanduser()
    count = max(TEST_RUN_SWORD_MINIMUM_VARIANTS, _safe_int(variants, TEST_RUN_SWORD_MINIMUM_VARIANTS))
    runs: list[dict[str, object]] = []
    missing_by_artifact: dict[str, int] = {name: 0 for name in (*_REQUESTED_RUN_ARTIFACTS, *_REQUESTED_RUN_FILES)}
    captured_runs = compared_runs = artifact_complete_runs = e_only_capture_reports = non_e_input_reports = sync_applied_runs = 0
    for index in range(1, count + 1):
        run_dir = root / f"run_{index:03d}"
        manifest_path = run_dir / "run_manifest.json"
        manifest = _read_json_object(manifest_path)
        artifacts = manifest.get("artifacts", {}) if isinstance(manifest.get("artifacts"), Mapping) else {}
        artifact_status: dict[str, dict[str, object]] = {}
        missing: list[str] = []
        for artifact_name in _REQUESTED_RUN_ARTIFACTS:
            path = _resolve_run_path(root, run_dir, artifacts.get(artifact_name, run_dir / f"{artifact_name}.missing"))
            exists = path.is_file()
            artifact_status[artifact_name] = {"path": str(path), "exists": exists}
            if not exists:
                missing.append(artifact_name)
                missing_by_artifact[artifact_name] += 1
        for file_name in _REQUESTED_RUN_FILES:
            path = run_dir / file_name
            exists = path.is_file()
            artifact_status[file_name] = {"path": str(path), "exists": exists}
            if not exists:
                missing.append(file_name)
                missing_by_artifact[file_name] += 1
        capture_path = _resolve_run_path(root, run_dir, artifacts.get("in_game_capture_report", run_dir / "ingame_capture_report.json"))
        capture_report = _read_json_object(capture_path)
        capture_ok = bool(capture_report.get("ok")) if capture_report else False
        input_policy = _capture_input_policy(capture_path)
        if capture_ok:
            captured_runs += 1
        if capture_report and not input_policy["non_e_keys"]:
            e_only_capture_reports += 1
        if input_policy["non_e_keys"]:
            non_e_input_reports += 1
        comparison_path = Path(str(artifact_status["comparison_report"]["path"]))
        comparison_report = _read_json_object(comparison_path)
        comparison_diagnostics = [
            str(item.get("code", "") or "")
            for item in comparison_report.get("diagnostics", ())
            if isinstance(item, Mapping) and str(item.get("code", "") or "")
        ]
        tuning_recommendations = build_test_run_sword_tuning_recommendations(comparison_report) if comparison_report else []
        if comparison_report:
            compared_runs += 1
        sync_report = _read_json_object(run_dir / "dmm_sync_report.json")
        sync_applied = bool(sync_report.get("applied")) if sync_report else False
        if sync_applied:
            sync_applied_runs += 1
        artifact_complete = not missing
        if artifact_complete:
            artifact_complete_runs += 1
        runs.append(
            {
                "run_id": f"run_{index:03d}",
                "run_dir": str(run_dir),
                "status": "ready_for_review" if artifact_complete else "missing_artifacts",
                "artifact_complete": artifact_complete,
                "missing": missing,
                "artifacts": artifact_status,
                "capture_ok": capture_ok,
                "capture_input_policy": input_policy,
                "comparison_diagnostics": comparison_diagnostics,
                "tuning_recommendations": tuning_recommendations,
                "sync": {
                    "report": str(run_dir / "dmm_sync_report.json"),
                    "report_exists": bool(sync_report),
                    "applied": sync_applied,
                    "policy": str(sync_report.get("policy", "") or "") if sync_report else "",
                },
            }
        )
    next_actions: list[str] = []
    if artifact_complete_runs < count:
        next_actions.append("complete_missing_preview_ingame_comparison_artifacts_for_each_run")
    if captured_runs < count:
        next_actions.append("capture_or_import_sword_on_back_screenshot_for_each_missing_run")
    if compared_runs < count:
        next_actions.append("run_preview_to_ingame_comparison_for_each_missing_run")
    if non_e_input_reports:
        next_actions.append("discard_or_recapture_runs_with_non_e_input_reports")
    if sync_applied_runs < count:
        next_actions.append("apply_guarded_dmm_sync_for_each_variant_when_ready")
    return {
        "schema_version": TEST_RUN_SWORD_STATUS_SCHEMA_VERSION,
        "output_dir": str(root),
        "minimum_variants_required": TEST_RUN_SWORD_MINIMUM_VARIANTS,
        "variant_count": count,
        "status": "complete" if artifact_complete_runs >= count and captured_runs >= count and compared_runs >= count else "incomplete",
        "counts": {
            "artifact_complete_runs": artifact_complete_runs,
            "captured_runs": captured_runs,
            "compared_runs": compared_runs,
            "e_only_capture_reports": e_only_capture_reports,
            "non_e_input_reports": non_e_input_reports,
            "sync_applied_runs": sync_applied_runs,
        },
        "missing_by_artifact": missing_by_artifact,
        "next_actions": next_actions,
        "runs": runs,
    }


def write_test_run_sword_session_status(
    output_dir: object = TEST_RUN_SWORD_OUTPUT_ROOT,
    *,
    output_path: object = "",
    variants: int = TEST_RUN_SWORD_MINIMUM_VARIANTS,
) -> Path:
    root = Path(output_dir).expanduser()
    path = Path(output_path).expanduser() if str(output_path or "").strip() else root / "session_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_test_run_sword_session_status(root, variants=variants)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_test_run_sword_variant_settings(run_index: int) -> dict[str, object]:
    index = max(1, _safe_int(run_index, 1))
    settings = dict(TEST_RUN_SWORD_BASELINE_SETTINGS)
    variants = [
        {},
        {"roughness_bias_percent": -8, "metalness_scale_percent": 104, "specular_scale_percent": 104},
        {"roughness_bias_percent": -4, "metalness_scale_percent": 108, "specular_scale_percent": 110},
        {"roughness_bias_percent": 4, "metalness_scale_percent": 96, "specular_scale_percent": 92},
        {"roughness_bias_percent": 8, "metalness_scale_percent": 92, "specular_scale_percent": 86},
        {"masked_gold_strength_percent": 110, "masked_silver_strength_percent": 100, "masked_green_strength_percent": 100},
        {"masked_gold_strength_percent": 120, "masked_silver_strength_percent": 105, "masked_green_strength_percent": 95},
        {"masked_gold_strength_percent": 95, "masked_silver_strength_percent": 115, "masked_green_strength_percent": 110},
        {"masked_gold_strength_percent": 90, "masked_silver_strength_percent": 100, "masked_green_strength_percent": 120},
        {"tone_contrast_percent": -6, "source_brightness_percent": 2, "auto_brightness_percent": 0},
        {"tone_contrast_percent": -14, "source_brightness_percent": -2, "auto_brightness_percent": 0},
        {"gloss_matte_bias_percent": -6, "roughness_bias_percent": -6, "accent_glow_percent": 8},
        {"gloss_matte_bias_percent": -14, "roughness_bias_percent": 6, "accent_glow_percent": 12},
        {"neutral_metal_base_tint": "cool_silver", "metalness_scale_percent": 108},
        {"neutral_metal_base_tint": "warm_gold", "masked_gold_strength_percent": 112},
        {"neutral_metal_base_tint": "desaturated_iron", "masked_green_strength_percent": 90},
        {"specular_scale_percent": 116, "environment_reflection_percent": 110, "roughness_bias_percent": -6},
        {"specular_scale_percent": 84, "environment_reflection_percent": 86, "roughness_bias_percent": 8},
        {"masked_detail_contrast_percent": 112, "tone_contrast_percent": -8},
        {"masked_detail_contrast_percent": 124, "source_brightness_percent": 1, "tone_contrast_percent": -12},
    ]
    settings.update(variants[(index - 1) % len(variants)])
    settings["variant_index"] = index
    settings["variant_label"] = f"material_tuning_{index:03d}"
    return settings


def build_test_run_sword_run_manifest(
    *,
    run_index: int,
    preview_screenshot: object = "",
    in_game_screenshot: object = "",
    in_game_capture_report: object = "",
    package_manifest: object = "",
    mod_settings: Mapping[str, object] | None = None,
    comparison_report: object = "",
    notes: object = "",
    source_mod_dir: object = TEST_RUN_SWORD_SOURCE_MOD,
    dmm_mod_dir: object = TEST_RUN_SWORD_DMM_MOD,
) -> dict[str, object]:
    index = max(1, int(run_index))
    settings = dict(TEST_RUN_SWORD_BASELINE_SETTINGS)
    if isinstance(mod_settings, Mapping):
        settings.update({str(key): value for key, value in mod_settings.items()})
    return {
        "schema_version": TEST_RUN_SWORD_MANIFEST_SCHEMA_VERSION,
        "run_index": index,
        "run_id": f"run_{index:03d}",
        "minimum_variants_required": TEST_RUN_SWORD_MINIMUM_VARIANTS,
        "source_mod_dir": str(source_mod_dir or ""),
        "dmm_mod_dir": str(dmm_mod_dir or ""),
        "artifacts": {
            "preview_screenshot": str(preview_screenshot or ""),
            "in_game_screenshot": str(in_game_screenshot or ""),
            "in_game_capture_report": str(in_game_capture_report or ""),
            "package_manifest": str(package_manifest or ""),
            "comparison_report": str(comparison_report or ""),
        },
        "mod_settings": settings,
        "notes": str(notes or ""),
        "loop_requirements": [
            "launch_game",
            "press_e_when_needed",
            "wait_character_loaded",
            "capture_sword_on_back",
            "compare_preview_to_ingame",
            "sync_variant_to_dmm_mod",
        ],
    }


def build_loose_mod_file_manifest(root_dir: object, *, max_files: int = 10000) -> dict[str, object]:
    root = Path(root_dir).expanduser()
    files: list[dict[str, object]] = []
    total_bytes = 0
    if root.is_dir():
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            if len(files) >= max(0, int(max_files)):
                break
            try:
                stat = path.stat()
            except OSError:
                continue
            total_bytes += int(stat.st_size)
            files.append(
                {
                    "path": _relative_to(path, root),
                    "size": int(stat.st_size),
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "schema_version": TEST_RUN_SWORD_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "root": str(root),
        "exists": root.is_dir(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "truncated": bool(root.is_dir() and len(files) >= max(0, int(max_files))),
        "files": files,
    }


def write_test_run_sword_package_manifest(
    output_path: object,
    *,
    source_mod_dir: object = TEST_RUN_SWORD_SOURCE_MOD,
    dmm_mod_dir: object = TEST_RUN_SWORD_DMM_MOD,
) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TEST_RUN_SWORD_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "source_mod": build_loose_mod_file_manifest(source_mod_dir),
        "dmm_mod": build_loose_mod_file_manifest(dmm_mod_dir),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def create_test_run_sword_run_artifacts(
    output_dir: object = TEST_RUN_SWORD_OUTPUT_ROOT,
    *,
    run_index: int,
    preview_screenshot: object = "",
    in_game_screenshot: object = "",
    in_game_capture_report: object = "",
    comparison_report: object = "",
    notes: object = "",
    source_mod_dir: object = TEST_RUN_SWORD_SOURCE_MOD,
    dmm_mod_dir: object = TEST_RUN_SWORD_DMM_MOD,
) -> dict[str, object]:
    root = Path(output_dir).expanduser()
    index = max(1, _safe_int(run_index, 1))
    run_dir = root / f"run_{index:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = build_test_run_sword_variant_settings(index)
    settings_path = run_dir / "mod_settings.json"
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    package_manifest_path = write_test_run_sword_package_manifest(
        run_dir / "package_manifest.json",
        source_mod_dir=source_mod_dir,
        dmm_mod_dir=dmm_mod_dir,
    )
    notes_path = run_dir / "notes.md"
    if not notes_path.exists() or notes:
        notes_path.write_text(str(notes or "Pending in-game screenshot and comparison.\n"), encoding="utf-8")
    manifest_path = write_test_run_sword_run_manifest(
        root,
        run_index=index,
        preview_screenshot=preview_screenshot or run_dir / "preview.png",
        in_game_screenshot=in_game_screenshot or run_dir / "ingame.png",
        in_game_capture_report=in_game_capture_report or run_dir / "ingame_capture_report.json",
        package_manifest=package_manifest_path,
        mod_settings=settings,
        comparison_report=comparison_report or run_dir / "comparison.json",
        notes=notes,
    )
    return {
        "run_dir": str(run_dir),
        "run_manifest": str(manifest_path),
        "mod_settings": str(settings_path),
        "package_manifest": str(package_manifest_path),
        "notes": str(notes_path),
    }


def write_test_run_sword_session_plan(
    output_dir: object = TEST_RUN_SWORD_OUTPUT_ROOT,
    *,
    variants: int = TEST_RUN_SWORD_MINIMUM_VARIANTS,
    source_mod_dir: object = TEST_RUN_SWORD_SOURCE_MOD,
    dmm_mod_dir: object = TEST_RUN_SWORD_DMM_MOD,
) -> Path:
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    count = max(TEST_RUN_SWORD_MINIMUM_VARIANTS, _safe_int(variants, TEST_RUN_SWORD_MINIMUM_VARIANTS))
    runs = [
        create_test_run_sword_run_artifacts(
            root,
            run_index=index,
            source_mod_dir=source_mod_dir,
            dmm_mod_dir=dmm_mod_dir,
        )
        for index in range(1, count + 1)
    ]
    payload = {
        "schema_version": TEST_RUN_SWORD_SESSION_SCHEMA_VERSION,
        "status": "planned",
        "minimum_variants_required": TEST_RUN_SWORD_MINIMUM_VARIANTS,
        "variant_count": count,
        "source_mod_dir": str(source_mod_dir or ""),
        "dmm_mod_dir": str(dmm_mod_dir or ""),
        "runs": runs,
        "blocked_until": [
            "in_game_screenshot_per_run",
            "game_window_interaction_and_reload",
        ],
    }
    session_path = root / "session_manifest.json"
    session_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return session_path


def _iter_source_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return (path for path in sorted(root.rglob("*")) if path.is_file())


def sync_test_run_sword_variant_to_dmm(
    *,
    run_dir: object,
    source_mod_dir: object = TEST_RUN_SWORD_SOURCE_MOD,
    dmm_mod_dir: object = TEST_RUN_SWORD_DMM_MOD,
    apply: bool = False,
) -> dict[str, object]:
    source = Path(source_mod_dir).expanduser().resolve()
    dmm = Path(dmm_mod_dir).expanduser().resolve()
    run_path = Path(run_dir).expanduser().resolve()
    report_path = run_path / "dmm_sync_report.json"
    diagnostics: list[dict[str, object]] = []
    copied: list[str] = []
    backed_up: list[str] = []
    if source.name.lower() != "testrunsword" or dmm.name.lower() != "testrunsword":
        diagnostics.append({"code": "unexpected_mod_name", "message": "Refusing to sync anything except TestRunSword."})
    if not source.is_dir():
        diagnostics.append({"code": "source_missing", "message": f"Source mod directory is missing: {source}"})
    if diagnostics:
        payload = {
            "schema_version": TEST_RUN_SWORD_SYNC_SCHEMA_VERSION,
            "applied": False,
            "source_mod_dir": str(source),
            "dmm_mod_dir": str(dmm),
            "diagnostics": diagnostics,
            "copied": copied,
            "backed_up": backed_up,
        }
        run_path.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    for source_file in _iter_source_files(source):
        relative = source_file.relative_to(source)
        target = dmm / relative
        copied.append(relative.as_posix())
        if apply:
            if target.is_file():
                backup = run_path / "dmm_restore" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backed_up.append(relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
    payload = {
        "schema_version": TEST_RUN_SWORD_SYNC_SCHEMA_VERSION,
        "applied": bool(apply),
        "source_mod_dir": str(source),
        "dmm_mod_dir": str(dmm),
        "diagnostics": diagnostics,
        "copied": copied,
        "backed_up": backed_up,
        "policy": "copy_overwrite_only; no archive mutation; no delete/prune of DMM extras",
    }
    run_path.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def write_test_run_sword_run_manifest(
    output_dir: object,
    *,
    run_index: int,
    preview_screenshot: object = "",
    in_game_screenshot: object = "",
    in_game_capture_report: object = "",
    package_manifest: object = "",
    mod_settings: Mapping[str, object] | None = None,
    comparison_report: object = "",
    notes: object = "",
) -> Path:
    root = Path(str(output_dir)).expanduser()
    run_dir = root / f"run_{max(1, int(run_index)):03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_test_run_sword_run_manifest(
        run_index=run_index,
        preview_screenshot=preview_screenshot,
        in_game_screenshot=in_game_screenshot,
        in_game_capture_report=in_game_capture_report,
        package_manifest=package_manifest,
        mod_settings=mod_settings,
        comparison_report=comparison_report,
        notes=notes,
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


__all__ = [
    "TEST_RUN_SWORD_BASELINE_SETTINGS",
    "TEST_RUN_SWORD_DMM_MOD",
    "TEST_RUN_SWORD_MANIFEST_SCHEMA_VERSION",
    "TEST_RUN_SWORD_MINIMUM_VARIANTS",
    "TEST_RUN_SWORD_OUTPUT_ROOT",
    "TEST_RUN_SWORD_PACKAGE_MANIFEST_SCHEMA_VERSION",
    "TEST_RUN_SWORD_SESSION_SCHEMA_VERSION",
    "TEST_RUN_SWORD_SOURCE_MOD",
    "build_test_run_sword_run_manifest",
    "build_test_run_sword_session_status",
    "build_test_run_sword_tuning_recommendations",
    "build_loose_mod_file_manifest",
    "create_test_run_sword_run_artifacts",
    "sync_test_run_sword_variant_to_dmm",
    "build_test_run_sword_variant_settings",
    "write_test_run_sword_package_manifest",
    "write_test_run_sword_run_manifest",
    "write_test_run_sword_session_plan",
    "write_test_run_sword_session_status",
]
