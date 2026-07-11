from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_mesh_types import MeshImportSupplementalFileSpec
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ImportAutoFixResult,
    ImportIssue,
    ImportIssueStatus,
    MeshImportDiff,
)
from cdmw.modding.mesh_parser import ParsedMesh

def _normalize_import_lookup_path(raw_path: str) -> str:
    return str(raw_path or "").replace("\\", "/").strip().lower()

def _normalize_import_binding_token(raw_value: str) -> str:
    return str(raw_value or "").strip().lower()

def _summarize_import_values(values: Sequence[str], *, limit: int = 3) -> str:
    compact_values = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not compact_values:
        return "None"
    if len(compact_values) <= limit:
        return ", ".join(compact_values)
    return ", ".join(compact_values[:limit]) + f" (+{len(compact_values) - limit} more)"

def _describe_sidecar_binding_locator(record: Mapping[str, str]) -> str:
    sidecar_path = str(record.get("sidecar_display") or "").strip()
    parameter_name = str(record.get("parameter_name") or "").strip() or "<unnamed parameter>"
    submesh_name = str(record.get("submesh_name") or "").strip()
    locator = f"{Path(sidecar_path).name or sidecar_path} :: {parameter_name}"
    if submesh_name:
        locator += f" [{submesh_name}]"
    return locator

def _build_selected_sidecar_target_overrides(
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for spec in supplemental_file_specs:
        if str(getattr(spec, "kind", "") or "").strip().lower() != "sidecar":
            continue
        target_path = _normalize_import_lookup_path(getattr(spec, "target_path", ""))
        if not target_path:
            continue
        source_path = getattr(spec, "source_path", None)
        if not isinstance(source_path, Path):
            continue
        candidate_keys = {
            _normalize_import_lookup_path(str(source_path)),
            _normalize_import_lookup_path(source_path.as_posix()),
            source_path.name.strip().lower(),
        }
        for candidate_key in candidate_keys:
            if candidate_key:
                overrides[candidate_key] = target_path
    return overrides

def _iter_normalized_sidecar_binding_records(
    bindings: Sequence[object],
    *,
    sidecar_target_overrides: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, str]]:
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

    records: List[Dict[str, str]] = []
    for binding in bindings:
        texture_path = str(getattr(binding, "texture_path", "") or "").strip()
        normalized_texture = normalize_texture_reference_for_sidecar_lookup(texture_path)
        if not normalized_texture:
            continue
        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        submesh_name = str(getattr(binding, "submesh_name", "") or "").strip()
        raw_sidecar_path = str(getattr(binding, "sidecar_path", "") or "").replace("\\", "/").strip()
        raw_sidecar_key = _normalize_import_lookup_path(raw_sidecar_path)
        sidecar_basename_key = PurePosixPath(raw_sidecar_path).name.lower() if raw_sidecar_path else ""
        target_sidecar_key = ""
        if sidecar_target_overrides:
            for candidate_key in (raw_sidecar_key, sidecar_basename_key):
                if candidate_key and candidate_key in sidecar_target_overrides:
                    target_sidecar_key = str(sidecar_target_overrides[candidate_key] or "").strip()
                    break
        compare_key = _normalize_import_lookup_path(target_sidecar_key or raw_sidecar_key or sidecar_basename_key)
        records.append(
            {
                "sidecar_compare_key": compare_key,
                "sidecar_display": str(target_sidecar_key or raw_sidecar_path or sidecar_basename_key),
                "parameter_name": parameter_name,
                "parameter_key": _normalize_import_binding_token(parameter_name),
                "submesh_name": submesh_name,
                "submesh_key": _normalize_import_binding_token(submesh_name),
                "texture_path": texture_path,
                "texture_key": normalized_texture,
            }
        )
    return records

def _selected_sidecar_input_findings(
    specs: Sequence[MeshImportSupplementalFileSpec],
    bindings: Sequence[object],
) -> Tuple[List[MeshImportDiff], List[ImportIssue], List[str]]:
    diffs: List[MeshImportDiff] = []
    issues: List[ImportIssue] = []
    warnings: List[str] = []
    unmapped = [spec for spec in specs if not str(getattr(spec, "target_path", "") or "").strip()]
    if unmapped:
        names = [spec.source_path.name for spec in unmapped if isinstance(spec.source_path, Path)]
        diff = MeshImportDiff(field_name="selected_sidecar_targets", original_value="mapped archive targets", imported_value=f"{len(unmapped):,} selected sidecar(s) unmapped", severity="warning", safe_to_auto_fix=False, detail="One or more selected local sidecar files could not be mapped to their original archive targets. Those files cannot be validated or patched safely.")
        diffs.append(diff)
        issues.append(ImportIssue(code="unmapped-sidecar-targets", title="Unmapped selected sidecars", status=ImportIssueStatus.WARNING.value, detail=f"{len(unmapped):,} selected sidecar file(s) could not be mapped back to archive targets. Examples: {_summarize_import_values(names)}.", diffs=(diff,)))
        warnings.append("selected_sidecar_targets")
    if not bindings:
        diff = MeshImportDiff(field_name="selected_sidecar_bindings", original_value="recognized material/texture bindings", imported_value="no recognized bindings parsed", severity="warning", safe_to_auto_fix=False, detail="Selected local sidecar files did not produce any recognized texture/material bindings.")
        diffs.append(diff)
        issues.append(ImportIssue(code="selected-sidecar-no-bindings", title="Selected sidecars exposed no recognized bindings", status=ImportIssueStatus.WARNING.value, detail="The selected material sidecar file(s) were loaded, but no supported material/texture bindings were detected. Import can continue, but compatibility checks are limited.", diffs=(diff,)))
        warnings.append("selected_sidecar_bindings")
    return diffs, issues, warnings


def _sidecar_record_groups(
    original_bindings: Sequence[object],
    selected_bindings: Sequence[object],
    specs: Sequence[MeshImportSupplementalFileSpec],
) -> Tuple[Dict[Tuple[str, str, str], List[Dict[str, str]]], Dict[Tuple[str, str, str], List[Dict[str, str]]]]:
    overrides = _build_selected_sidecar_target_overrides(specs)
    original = _iter_normalized_sidecar_binding_records(original_bindings)
    selected = _iter_normalized_sidecar_binding_records(selected_bindings, sidecar_target_overrides=overrides)
    targets = {_normalize_import_lookup_path(getattr(spec, "target_path", "")) for spec in specs if str(getattr(spec, "target_path", "") or "").strip()}
    if targets:
        original = [record for record in original if record["sidecar_compare_key"] in targets]
        selected = [record for record in selected if record["sidecar_compare_key"] in targets]
    original_groups: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    selected_groups: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for record in original:
        original_groups[(record["sidecar_compare_key"], record["submesh_key"], record["parameter_key"])].append(record)
    for record in selected:
        selected_groups[(record["sidecar_compare_key"], record["submesh_key"], record["parameter_key"])].append(record)
    return original_groups, selected_groups


def _compare_sidecar_record_groups(
    original: Mapping[Tuple[str, str, str], Sequence[Dict[str, str]]],
    selected: Mapping[Tuple[str, str, str], Sequence[Dict[str, str]]],
) -> Tuple[List[MeshImportDiff], List[MeshImportDiff], List[MeshImportDiff], int]:
    changed: List[MeshImportDiff] = []
    missing: List[MeshImportDiff] = []
    added: List[MeshImportDiff] = []
    matched = 0
    for locator in sorted(set(original) | set(selected)):
        old = list(original.get(locator, ())); new = list(selected.get(locator, ()))
        display = new[0] if new else old[0]
        old_paths = tuple(sorted({record["texture_path"] for record in old}))
        new_paths = tuple(sorted({record["texture_path"] for record in new}))
        old_keys = {record["texture_key"] for record in old}; new_keys = {record["texture_key"] for record in new}
        label = _describe_sidecar_binding_locator(display)
        if old_keys and new_keys and old_keys == new_keys:
            matched += 1
        elif old and new:
            changed.append(MeshImportDiff(field_name="sidecar_binding_texture", original_value=_summarize_import_values(old_paths), imported_value=_summarize_import_values(new_paths), severity="warning", safe_to_auto_fix=False, detail=f"Binding target changed for {label}."))
        elif old:
            missing.append(MeshImportDiff(field_name="sidecar_binding_missing", original_value=_summarize_import_values(old_paths), imported_value="missing", severity="warning", safe_to_auto_fix=False, detail=f"Original binding is missing from the selected sidecar for {label}."))
        else:
            added.append(MeshImportDiff(field_name="sidecar_binding_added", original_value="not present", imported_value=_summarize_import_values(new_paths), severity="warning", safe_to_auto_fix=False, detail=f"Selected sidecar introduced an extra binding for {label}."))
    return changed, missing, added, matched


def _report_sidecar_comparison(
    changed: Sequence[MeshImportDiff], missing: Sequence[MeshImportDiff], added: Sequence[MeshImportDiff], matched: int,
    diffs: List[MeshImportDiff], issues: List[ImportIssue], summary: List[str], warnings: List[str], manual: List[str],
) -> None:
    if changed:
        diffs.extend(changed)
        issues.append(ImportIssue(code="sidecar-binding-targets-changed", title="Material sidecar binding targets changed", status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value, detail=f"{len(changed):,} sidecar binding locator(s) now point to different texture target(s). This can change how the model shades or make parts render incorrectly.", diffs=tuple(changed[:8])))
        manual.append("sidecar_binding_texture"); summary.append(f"Import validation: detected {len(changed):,} sidecar binding target change(s) compared with the original archive sidecar.")
    if missing:
        diffs.extend(missing)
        issues.append(ImportIssue(code="sidecar-bindings-missing", title="Original material sidecar bindings are missing", status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value, detail=f"{len(missing):,} original sidecar binding locator(s) are missing from the selected local sidecar set. Missing bindings can leave textures, masks, or support maps unassigned.", diffs=tuple(missing[:8])))
        manual.append("sidecar_binding_missing"); summary.append(f"Import validation: {len(missing):,} original sidecar binding(s) are missing from the selected sidecar file(s).")
    if added:
        diffs.extend(added)
        issues.append(ImportIssue(code="sidecar-bindings-added", title="Selected sidecars added extra bindings", status=ImportIssueStatus.WARNING.value, detail=f"{len(added):,} extra sidecar binding locator(s) were added compared with the original archive sidecar. This is allowed, but it should be reviewed if the model is expected to remain game-compatible.", diffs=tuple(added[:8])))
        warnings.append("sidecar_binding_added"); summary.append(f"Import validation: {len(added):,} extra sidecar binding(s) were added by the selected sidecar file(s).")
    if matched and not changed and not missing:
        summary.append(f"Validated {matched:,} selected sidecar binding locator(s) against the original archive sidecar with no texture-target drift.")


def _build_sidecar_binding_validation(
    *,
    original_sidecar_bindings: Sequence[object],
    selected_sidecar_bindings: Sequence[object],
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
) -> Tuple[Tuple[MeshImportDiff, ...], Tuple[ImportIssue, ...], List[str], Tuple[str, ...], Tuple[str, ...]]:
    specs = [spec for spec in supplemental_file_specs if str(getattr(spec, "kind", "") or "").strip().lower() == "sidecar"]
    if not specs:
        return (), (), [], (), ()
    diffs, issues, warnings = _selected_sidecar_input_findings(specs, selected_sidecar_bindings)
    summary: List[str] = []; manual: List[str] = []
    if not selected_sidecar_bindings:
        return tuple(diffs), tuple(issues), summary, tuple(dict.fromkeys(warnings)), ()
    original, selected = _sidecar_record_groups(original_sidecar_bindings, selected_sidecar_bindings, specs)
    if not original:
        diff = MeshImportDiff(field_name="original_sidecar_bindings", original_value="archive sidecar bindings available", imported_value="not available for selected targets", severity="warning", safe_to_auto_fix=False, detail="The original archive sidecar bindings could not be recovered for the selected sidecar target(s).")
        diffs.append(diff)
        issues.append(ImportIssue(code="original-sidecar-baseline-missing", title="Original sidecar baseline unavailable", status=ImportIssueStatus.WARNING.value, detail="The tool could not recover the original archive sidecar bindings for one or more selected targets, so binding-level compatibility checks are incomplete.", diffs=(diff,)))
        warnings.append("original_sidecar_bindings")
        return tuple(diffs), tuple(issues), summary, tuple(dict.fromkeys(warnings)), ()
    changed, missing, added, matched = _compare_sidecar_record_groups(original, selected)
    _report_sidecar_comparison(changed, missing, added, matched, diffs, issues, summary, warnings, manual)
    return tuple(diffs), tuple(issues), summary, tuple(dict.fromkeys(warnings)), tuple(dict.fromkeys(manual))

def _validate_mesh_structure(
    original_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
    import_mode: str,
    diffs: List[MeshImportDiff],
    issues: List[ImportIssue],
    warnings: List[str],
    manual: List[str],
) -> None:
    if len(original_mesh.submeshes) != len(rebuilt_mesh.submeshes):
        static = str(import_mode or "").strip().lower() in {"static", "static_replacement", "static-mesh-replacement"}
        diff = MeshImportDiff(field_name="submesh_count", original_value=str(len(original_mesh.submeshes)), imported_value=str(len(rebuilt_mesh.submeshes)), severity="warning", safe_to_auto_fix=static, detail="Submesh count changed during import preview.")
        diffs.append(diff)
        detail = "Static replacement changed the parsed output submesh count after mapped or empty draw sections were rebuilt. This is expected when replacing a mesh with a different part layout; review the static mapping summary if parts are missing." if static else "Submesh count changed compared with the original mesh. This can break bindings or make parts invisible."
        issues.append(ImportIssue(code="submesh-count-drift", title="Static replacement submesh remap" if static else "Submesh count/order drift", status=ImportIssueStatus.WARNING.value if static else ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value, detail=detail, diffs=(diff,)))
        (warnings if static else manual).append("submesh_count")
    if any(not getattr(submesh, "uvs", None) for submesh in rebuilt_mesh.submeshes):
        diff = MeshImportDiff(field_name="uv_sets", original_value="present", imported_value="missing on one or more submeshes", severity="warning", safe_to_auto_fix=False, detail="One or more imported submeshes no longer contain UVs.")
        diffs.append(diff)
        issues.append(ImportIssue(code="missing-uvs", title="Missing UVs", status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value, detail="Missing UVs can make textures invisible or incorrect in-game.", diffs=(diff,)))
        manual.append("uv_sets")


def _validate_material_sidecars(
    texture_references: Sequence[ArchiveModelTextureReference],
    diffs: List[MeshImportDiff],
    issues: List[ImportIssue],
    warnings: List[str],
) -> None:
    if any(reference.relation_group == "Material Sidecars" for reference in texture_references):
        return
    diff = MeshImportDiff(field_name="material_sidecars", original_value="expected", imported_value="not resolved", severity="warning", safe_to_auto_fix=False, detail="No material sidecar could be resolved for the imported mesh.")
    diffs.append(diff)
    issues.append(ImportIssue(code="missing-sidecars", title="Missing sidecars", status=ImportIssueStatus.WARNING.value, detail="Material sidecars were not resolved. Import can continue, but texture bindings may be incomplete.", diffs=(diff,)))
    warnings.append("material_sidecars")


def _apply_import_auto_fixes(
    paired_lod_path: str,
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
    manifest_payload: Optional[dict],
    applied: List[str],
    issues: List[ImportIssue],
    summary: List[str],
) -> None:
    if paired_lod_path:
        applied.append("paired_pamlod_path")
        issues.append(ImportIssue(code="paired-pamlod-restored", title="Paired PAMLOD restored", status=ImportIssueStatus.AUTO_FIXED.value, detail=f"Paired PAMLOD rebuild is prepared for {paired_lod_path}."))
        summary.append(f"Auto-fixed: paired PAMLOD linkage restored ({paired_lod_path}).")
    mapped = [spec for spec in supplemental_file_specs if spec.target_path]
    if mapped:
        applied.append("selected_sidecar_association")
        issues.append(ImportIssue(code="supplemental-targets-restored", title="Selected companion targets restored", status=ImportIssueStatus.AUTO_FIXED.value, detail=f"Recovered {len(mapped):,} selected supplemental target path(s)."))
        summary.append(f"Auto-fixed: restored {len(mapped):,} selected companion target path(s).")
    if isinstance(manifest_payload, dict):
        applied.extend(field for field in ("source_path", "source_format", "family_graph", "skeleton_identity") if field in manifest_payload)
        if manifest_payload.get("skeleton_identity"):
            summary.append("Auto-fixed: restored original skeleton identity metadata from the round-trip manifest.")


def _build_mesh_import_validation(
    entry: ArchiveEntry,
    original_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
    *,
    import_mode: str = "roundtrip",
    texture_references: Sequence[ArchiveModelTextureReference] = (),
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec] = (),
    original_sidecar_bindings: Sequence[object] = (),
    selected_sidecar_bindings: Sequence[object] = (),
    paired_lod_path: str = "",
    manifest_payload: Optional[dict] = None,
) -> Tuple[Tuple[MeshImportDiff, ...], Tuple[ImportIssue, ...], ImportAutoFixResult, List[str]]:
    del entry
    diffs: List[MeshImportDiff] = []; issues: List[ImportIssue] = []
    applied: List[str] = []; warnings: List[str] = []; manual: List[str] = []; summary: List[str] = []
    _validate_mesh_structure(original_mesh, rebuilt_mesh, import_mode, diffs, issues, warnings, manual)
    _validate_material_sidecars(texture_references, diffs, issues, warnings)
    sidecar = _build_sidecar_binding_validation(original_sidecar_bindings=original_sidecar_bindings, selected_sidecar_bindings=selected_sidecar_bindings, supplemental_file_specs=supplemental_file_specs)
    diffs.extend(sidecar[0]); issues.extend(sidecar[1]); summary.extend(sidecar[2]); warnings.extend(sidecar[3]); manual.extend(sidecar[4])
    _apply_import_auto_fixes(paired_lod_path, supplemental_file_specs, manifest_payload, applied, issues, summary)
    if issues:
        counts = Counter(issue.status for issue in issues)
        summary.append("Import validation: " + ", ".join(f"{counts[status]:,} {status}" for status in (ImportIssueStatus.AUTO_FIXED.value, ImportIssueStatus.WARNING.value, ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value) if counts.get(status)))
    return tuple(diffs), tuple(issues), ImportAutoFixResult(applied_fields=tuple(dict.fromkeys(applied)), warning_fields=tuple(dict.fromkeys(warnings)), manual_review_fields=tuple(dict.fromkeys(manual)), issues=tuple(issues)), summary
