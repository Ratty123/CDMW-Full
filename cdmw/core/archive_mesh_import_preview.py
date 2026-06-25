from __future__ import annotations

import dataclasses
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding_constants import (
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
    _MESH_IMPORT_ASSET_ROOT_MARKERS,
    _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS,
    _MESH_IMPORT_SHORT_TEXTURE_SUFFIXES,
    _MESH_IMPORT_TEXTURE_SUFFIXES,
)
from cdmw.core.archive_mesh_types import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.archive_patching import _normalize_virtual_path
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.core.model_preview import _build_lod_summary, _build_model_preview
from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ImportAutoFixResult,
    ImportIssue,
    ImportIssueStatus,
    MeshImportDiff,
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.modding.material_replacer import TextureReplacementPayload, build_texture_replacement_payloads
from cdmw.modding.mesh_importer import _load_obj_roundtrip_sidecar, build_mesh, transfer_pam_edit_to_pamlod_mesh
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.modding.scene_importer import (
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    SceneImportResult,
    discover_scene_texture_files,
    import_scene_mesh_with_report,
)
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    build_static_mesh_replacement,
    effective_static_replacement_source_mesh,
    suggest_static_submesh_mappings,
)

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


def _build_sidecar_binding_validation(
    *,
    original_sidecar_bindings: Sequence[object],
    selected_sidecar_bindings: Sequence[object],
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
) -> Tuple[Tuple[MeshImportDiff, ...], Tuple[ImportIssue, ...], List[str], Tuple[str, ...], Tuple[str, ...]]:
    selected_sidecar_specs = [
        spec for spec in supplemental_file_specs if str(getattr(spec, "kind", "") or "").strip().lower() == "sidecar"
    ]
    if not selected_sidecar_specs:
        return (), (), [], (), ()

    diffs: List[MeshImportDiff] = []
    issues: List[ImportIssue] = []
    summary_lines: List[str] = []
    warning_fields: List[str] = []
    manual_review_fields: List[str] = []

    unmapped_sidecars = [spec for spec in selected_sidecar_specs if not str(getattr(spec, "target_path", "") or "").strip()]
    if unmapped_sidecars:
        sidecar_names = [spec.source_path.name for spec in unmapped_sidecars if isinstance(spec.source_path, Path)]
        diff = MeshImportDiff(
            field_name="selected_sidecar_targets",
            original_value="mapped archive targets",
            imported_value=f"{len(unmapped_sidecars):,} selected sidecar(s) unmapped",
            severity="warning",
            safe_to_auto_fix=False,
            detail=(
                "One or more selected local sidecar files could not be mapped to their original archive targets. "
                "Those files cannot be validated or patched safely."
            ),
        )
        diffs.append(diff)
        issues.append(
            ImportIssue(
                code="unmapped-sidecar-targets",
                title="Unmapped selected sidecars",
                status=ImportIssueStatus.WARNING.value,
                detail=(
                    f"{len(unmapped_sidecars):,} selected sidecar file(s) could not be mapped back to archive targets. "
                    f"Examples: {_summarize_import_values(sidecar_names)}."
                ),
                diffs=(diff,),
            )
        )
        warning_fields.append("selected_sidecar_targets")

    if not selected_sidecar_bindings:
        diff = MeshImportDiff(
            field_name="selected_sidecar_bindings",
            original_value="recognized material/texture bindings",
            imported_value="no recognized bindings parsed",
            severity="warning",
            safe_to_auto_fix=False,
            detail="Selected local sidecar files did not produce any recognized texture/material bindings.",
        )
        diffs.append(diff)
        issues.append(
            ImportIssue(
                code="selected-sidecar-no-bindings",
                title="Selected sidecars exposed no recognized bindings",
                status=ImportIssueStatus.WARNING.value,
                detail=(
                    "The selected material sidecar file(s) were loaded, but no supported material/texture bindings were detected. "
                    "Import can continue, but compatibility checks are limited."
                ),
                diffs=(diff,),
            )
        )
        warning_fields.append("selected_sidecar_bindings")
        return tuple(diffs), tuple(issues), summary_lines, tuple(dict.fromkeys(warning_fields)), ()

    sidecar_target_overrides = _build_selected_sidecar_target_overrides(selected_sidecar_specs)
    original_records = _iter_normalized_sidecar_binding_records(original_sidecar_bindings)
    selected_records = _iter_normalized_sidecar_binding_records(
        selected_sidecar_bindings,
        sidecar_target_overrides=sidecar_target_overrides,
    )
    selected_target_keys = {
        _normalize_import_lookup_path(getattr(spec, "target_path", ""))
        for spec in selected_sidecar_specs
        if str(getattr(spec, "target_path", "") or "").strip()
    }
    if selected_target_keys:
        original_records = [record for record in original_records if record["sidecar_compare_key"] in selected_target_keys]
        selected_records = [record for record in selected_records if record["sidecar_compare_key"] in selected_target_keys]

    if not original_records:
        diff = MeshImportDiff(
            field_name="original_sidecar_bindings",
            original_value="archive sidecar bindings available",
            imported_value="not available for selected targets",
            severity="warning",
            safe_to_auto_fix=False,
            detail="The original archive sidecar bindings could not be recovered for the selected sidecar target(s).",
        )
        diffs.append(diff)
        issues.append(
            ImportIssue(
                code="original-sidecar-baseline-missing",
                title="Original sidecar baseline unavailable",
                status=ImportIssueStatus.WARNING.value,
                detail=(
                    "The tool could not recover the original archive sidecar bindings for one or more selected targets, "
                    "so binding-level compatibility checks are incomplete."
                ),
                diffs=(diff,),
            )
        )
        warning_fields.append("original_sidecar_bindings")
        return tuple(diffs), tuple(issues), summary_lines, tuple(dict.fromkeys(warning_fields)), ()

    from collections import defaultdict

    original_by_locator: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    selected_by_locator: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for record in original_records:
        locator = (record["sidecar_compare_key"], record["submesh_key"], record["parameter_key"])
        original_by_locator[locator].append(record)
    for record in selected_records:
        locator = (record["sidecar_compare_key"], record["submesh_key"], record["parameter_key"])
        selected_by_locator[locator].append(record)

    changed_diffs: List[MeshImportDiff] = []
    missing_diffs: List[MeshImportDiff] = []
    added_diffs: List[MeshImportDiff] = []
    matched_locator_count = 0

    for locator in sorted(set(original_by_locator) | set(selected_by_locator)):
        original_bucket = original_by_locator.get(locator, [])
        selected_bucket = selected_by_locator.get(locator, [])
        display_record = selected_bucket[0] if selected_bucket else original_bucket[0]
        original_textures = tuple(sorted({record["texture_path"] for record in original_bucket}))
        selected_textures = tuple(sorted({record["texture_path"] for record in selected_bucket}))
        original_texture_keys = {record["texture_key"] for record in original_bucket}
        selected_texture_keys = {record["texture_key"] for record in selected_bucket}
        locator_label = _describe_sidecar_binding_locator(display_record)
        if original_texture_keys and selected_texture_keys and original_texture_keys == selected_texture_keys:
            matched_locator_count += 1
            continue
        if original_bucket and selected_bucket:
            changed_diffs.append(
                MeshImportDiff(
                    field_name="sidecar_binding_texture",
                    original_value=_summarize_import_values(original_textures),
                    imported_value=_summarize_import_values(selected_textures),
                    severity="warning",
                    safe_to_auto_fix=False,
                    detail=f"Binding target changed for {locator_label}.",
                )
            )
            continue
        if original_bucket:
            missing_diffs.append(
                MeshImportDiff(
                    field_name="sidecar_binding_missing",
                    original_value=_summarize_import_values(original_textures),
                    imported_value="missing",
                    severity="warning",
                    safe_to_auto_fix=False,
                    detail=f"Original binding is missing from the selected sidecar for {locator_label}.",
                )
            )
            continue
        added_diffs.append(
            MeshImportDiff(
                field_name="sidecar_binding_added",
                original_value="not present",
                imported_value=_summarize_import_values(selected_textures),
                severity="warning",
                safe_to_auto_fix=False,
                detail=f"Selected sidecar introduced an extra binding for {locator_label}.",
            )
        )

    if changed_diffs:
        diffs.extend(changed_diffs)
        issues.append(
            ImportIssue(
                code="sidecar-binding-targets-changed",
                title="Material sidecar binding targets changed",
                status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value,
                detail=(
                    f"{len(changed_diffs):,} sidecar binding locator(s) now point to different texture target(s). "
                    "This can change how the model shades or make parts render incorrectly."
                ),
                diffs=tuple(changed_diffs[:8]),
            )
        )
        manual_review_fields.append("sidecar_binding_texture")
        summary_lines.append(
            f"Import validation: detected {len(changed_diffs):,} sidecar binding target change(s) compared with the original archive sidecar."
        )

    if missing_diffs:
        diffs.extend(missing_diffs)
        issues.append(
            ImportIssue(
                code="sidecar-bindings-missing",
                title="Original material sidecar bindings are missing",
                status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value,
                detail=(
                    f"{len(missing_diffs):,} original sidecar binding locator(s) are missing from the selected local sidecar set. "
                    "Missing bindings can leave textures, masks, or support maps unassigned."
                ),
                diffs=tuple(missing_diffs[:8]),
            )
        )
        manual_review_fields.append("sidecar_binding_missing")
        summary_lines.append(
            f"Import validation: {len(missing_diffs):,} original sidecar binding(s) are missing from the selected sidecar file(s)."
        )

    if added_diffs:
        diffs.extend(added_diffs)
        issues.append(
            ImportIssue(
                code="sidecar-bindings-added",
                title="Selected sidecars added extra bindings",
                status=ImportIssueStatus.WARNING.value,
                detail=(
                    f"{len(added_diffs):,} extra sidecar binding locator(s) were added compared with the original archive sidecar. "
                    "This is allowed, but it should be reviewed if the model is expected to remain game-compatible."
                ),
                diffs=tuple(added_diffs[:8]),
            )
        )
        warning_fields.append("sidecar_binding_added")
        summary_lines.append(
            f"Import validation: {len(added_diffs):,} extra sidecar binding(s) were added by the selected sidecar file(s)."
        )

    if matched_locator_count > 0 and not changed_diffs and not missing_diffs:
        summary_lines.append(
            f"Validated {matched_locator_count:,} selected sidecar binding locator(s) against the original archive sidecar with no texture-target drift."
        )

    return (
        tuple(diffs),
        tuple(issues),
        summary_lines,
        tuple(dict.fromkeys(warning_fields)),
        tuple(dict.fromkeys(manual_review_fields)),
    )


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
    diffs: List[MeshImportDiff] = []
    issues: List[ImportIssue] = []
    applied_fields: List[str] = []
    warning_fields: List[str] = []
    manual_review_fields: List[str] = []
    summary_lines: List[str] = []

    submesh_count_changed = len(original_mesh.submeshes) != len(rebuilt_mesh.submeshes)
    if submesh_count_changed:
        is_static_replacement = str(import_mode or "").strip().lower() in {
            "static",
            "static_replacement",
            "static-mesh-replacement",
        }
        status = (
            ImportIssueStatus.WARNING.value
            if is_static_replacement
            else ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value
        )
        detail = (
            "Static replacement changed the parsed output submesh count after mapped or empty draw sections were rebuilt. "
            "This is expected when replacing a mesh with a different part layout; review the static mapping summary if parts are missing."
            if is_static_replacement
            else "Submesh count changed compared with the original mesh. This can break bindings or make parts invisible."
        )
        diffs.append(
            MeshImportDiff(
                field_name="submesh_count",
                original_value=str(len(original_mesh.submeshes)),
                imported_value=str(len(rebuilt_mesh.submeshes)),
                severity="warning",
                safe_to_auto_fix=is_static_replacement,
                detail="Submesh count changed during import preview.",
            )
        )
        issues.append(
            ImportIssue(
                code="submesh-count-drift",
                title=(
                    "Static replacement submesh remap"
                    if is_static_replacement
                    else "Submesh count/order drift"
                ),
                status=status,
                detail=detail,
                diffs=(diffs[-1],),
            )
        )
        if is_static_replacement:
            warning_fields.append("submesh_count")
        else:
            manual_review_fields.append("submesh_count")

    missing_uvs = any(not getattr(submesh, "uvs", None) for submesh in rebuilt_mesh.submeshes)
    if missing_uvs:
        diff = MeshImportDiff(
            field_name="uv_sets",
            original_value="present",
            imported_value="missing on one or more submeshes",
            severity="warning",
            safe_to_auto_fix=False,
            detail="One or more imported submeshes no longer contain UVs.",
        )
        diffs.append(diff)
        issues.append(
            ImportIssue(
                code="missing-uvs",
                title="Missing UVs",
                status=ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value,
                detail="Missing UVs can make textures invisible or incorrect in-game.",
                diffs=(diff,),
            )
        )
        manual_review_fields.append("uv_sets")

    resolved_sidecars = [reference for reference in texture_references if reference.relation_group == "Material Sidecars"]
    if not resolved_sidecars:
        diff = MeshImportDiff(
            field_name="material_sidecars",
            original_value="expected",
            imported_value="not resolved",
            severity="warning",
            safe_to_auto_fix=False,
            detail="No material sidecar could be resolved for the imported mesh.",
        )
        diffs.append(diff)
        issues.append(
            ImportIssue(
                code="missing-sidecars",
                title="Missing sidecars",
                status=ImportIssueStatus.WARNING.value,
                detail="Material sidecars were not resolved. Import can continue, but texture bindings may be incomplete.",
                diffs=(diff,),
            )
        )
        warning_fields.append("material_sidecars")

    sidecar_diffs, sidecar_issues, sidecar_summary_lines, sidecar_warning_fields, sidecar_manual_review_fields = (
        _build_sidecar_binding_validation(
            original_sidecar_bindings=original_sidecar_bindings,
            selected_sidecar_bindings=selected_sidecar_bindings,
            supplemental_file_specs=supplemental_file_specs,
        )
    )
    if sidecar_diffs:
        diffs.extend(sidecar_diffs)
    if sidecar_issues:
        issues.extend(sidecar_issues)
    if sidecar_summary_lines:
        summary_lines.extend(sidecar_summary_lines)
    if sidecar_warning_fields:
        warning_fields.extend(sidecar_warning_fields)
    if sidecar_manual_review_fields:
        manual_review_fields.extend(sidecar_manual_review_fields)

    if paired_lod_path:
        applied_fields.append("paired_pamlod_path")
        issues.append(
            ImportIssue(
                code="paired-pamlod-restored",
                title="Paired PAMLOD restored",
                status=ImportIssueStatus.AUTO_FIXED.value,
                detail=f"Paired PAMLOD rebuild is prepared for {paired_lod_path}.",
            )
        )
        summary_lines.append(f"Auto-fixed: paired PAMLOD linkage restored ({paired_lod_path}).")

    mapped_specs = [spec for spec in supplemental_file_specs if spec.target_path]
    if mapped_specs:
        applied_fields.append("selected_sidecar_association")
        issues.append(
            ImportIssue(
                code="supplemental-targets-restored",
                title="Selected companion targets restored",
                status=ImportIssueStatus.AUTO_FIXED.value,
                detail=f"Recovered {len(mapped_specs):,} selected supplemental target path(s).",
            )
        )
        summary_lines.append(f"Auto-fixed: restored {len(mapped_specs):,} selected companion target path(s).")

    if isinstance(manifest_payload, dict):
        applied_fields.extend(
            field_name
            for field_name in (
                "source_path",
                "source_format",
                "family_graph",
                "skeleton_identity",
            )
            if field_name in manifest_payload
        )
        if manifest_payload.get("skeleton_identity"):
            summary_lines.append("Auto-fixed: restored original skeleton identity metadata from the round-trip manifest.")

    if issues:
        status_counts = Counter(issue.status for issue in issues)
        summary_lines.append(
            "Import validation: "
            + ", ".join(
                f"{status_counts.get(status, 0):,} {status}"
                for status in (
                    ImportIssueStatus.AUTO_FIXED.value,
                    ImportIssueStatus.WARNING.value,
                    ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value,
                )
                if status_counts.get(status, 0) > 0
            )
        )

    return (
        tuple(diffs),
        tuple(issues),
        ImportAutoFixResult(
            applied_fields=tuple(dict.fromkeys(applied_fields)),
            warning_fields=tuple(dict.fromkeys(warning_fields)),
            manual_review_fields=tuple(dict.fromkeys(manual_review_fields)),
            issues=tuple(issues),
        ),
        summary_lines,
    )

def _mesh_import_candidate_virtual_paths(source_path: Path) -> Tuple[str, ...]:
    normalized_parts = [part for part in source_path.expanduser().parts if part]
    if not normalized_parts:
        return ()
    lowered_parts = [str(part).strip() for part in normalized_parts]
    ordered: List[str] = []
    seen: set[str] = set()

    def _append(parts: Sequence[str]) -> None:
        candidate = PurePosixPath(*parts).as_posix().strip()
        normalized_candidate = _normalize_virtual_path(candidate)
        if not normalized_candidate or normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        ordered.append(candidate)

    for index, part in enumerate(lowered_parts):
        if str(part).strip().lower() == "files" and index + 1 < len(lowered_parts):
            _append(lowered_parts[index + 1 :])
            break

    for index, part in enumerate(lowered_parts):
        if str(part).strip().lower() in _MESH_IMPORT_ASSET_ROOT_MARKERS:
            _append(lowered_parts[index:])
            break

    _append([source_path.name])
    return tuple(ordered)


def _mesh_import_loose_texture_preferred_paths(source_path: Path) -> Tuple[str, ...]:
    if source_path.suffix.lower() != ".dds":
        return ()
    if not any(str(part).strip().lower() == "files" for part in source_path.expanduser().parts):
        return ()

    ordered: List[str] = []
    seen: set[str] = set()

    def _append(value: str) -> None:
        normalized = _normalize_virtual_path(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(value.replace("\\", "/"))

    for candidate in _mesh_import_candidate_virtual_paths(source_path):
        parts = tuple(part for part in PurePosixPath(candidate.replace("\\", "/")).parts if part)
        if len(parts) < 2 or parts[0].lower() not in _MESH_IMPORT_ASSET_ROOT_MARKERS:
            continue
        basename = parts[-1]
        if not basename.lower().endswith(".dds"):
            continue
        if len(parts) == 2:
            _append(PurePosixPath(parts[0], "texture", basename).as_posix())
        elif parts[1].lower() in {"texture", "textures"}:
            _append(PurePosixPath(parts[0], "texture", basename).as_posix())
    return tuple(ordered)


def _mesh_import_modelproperty_variant(mesh_path: str) -> str:
    parts = list(PurePosixPath(str(mesh_path or "").replace("\\", "/")).parts)
    for index, part in enumerate(parts):
        if part.lower() == "model":
            parts[index] = "modelproperty"
            return PurePosixPath(*parts).as_posix()
    return ""




def _mesh_import_target_sidecar_candidates_for_base(
    mesh_path: str,
    source_sidecar_path: Path,
) -> Tuple[str, ...]:
    mesh_pure = PurePosixPath(str(mesh_path or "").replace("\\", "/").strip())
    if not mesh_pure.name:
        return ()

    mesh_extension = mesh_pure.suffix.lower()
    source_extension = source_sidecar_path.suffix.lower()
    source_name = source_sidecar_path.name.lower()
    candidates: List[str] = []

    def _append(candidate: PurePosixPath) -> None:
        value = candidate.as_posix().strip()
        if value and value not in candidates:
            candidates.append(value)

    if source_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".app_xml", ".prefabdata_xml"}:
        _append(mesh_pure.with_suffix(source_extension))
    elif source_extension == ".pami":
        _append(mesh_pure.with_suffix(".pami"))
    elif source_extension == ".xml":
        if source_name.endswith(".pac.xml") or mesh_extension == ".pac":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pac_xml"))
        elif source_name.endswith(".pam.xml") or mesh_extension == ".pam":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pam_xml"))
        elif source_name.endswith(".pamlod.xml") or mesh_extension == ".pamlod":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pamlod_xml"))
        elif source_name.endswith(".app.xml"):
            _append(mesh_pure.with_suffix(".app_xml"))
        elif source_name.endswith(".prefabdata.xml"):
            _append(mesh_pure.with_suffix(".prefabdata_xml"))
        else:
            _append(mesh_pure.with_suffix(".xml"))
    return tuple(candidates)


def _mesh_import_sidecar_preferred_paths(
    entry: ArchiveEntry,
    source_sidecar_path: Path,
    related_entries_by_extension: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[str, ...]:
    source_extension = source_sidecar_path.suffix.lower()
    ordered: List[str] = []
    seen: set[str] = set()

    def _append(value: str) -> None:
        normalized = _normalize_virtual_path(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(str(value).replace("\\", "/"))

    target_names = {
        PurePosixPath(path).name.lower()
        for base_path in (entry.path, _mesh_import_modelproperty_variant(entry.path))
        for path in _mesh_import_target_sidecar_candidates_for_base(base_path, source_sidecar_path)
        if path
    }
    related_by_extension = list(related_entries_by_extension.get(source_extension, ()))
    for related_entry in related_by_extension:
        if PurePosixPath(related_entry.path.replace("\\", "/")).name.lower() in target_names:
            _append(related_entry.path)
    if len(related_by_extension) == 1:
        _append(related_by_extension[0].path)

    modelproperty_path = _mesh_import_modelproperty_variant(entry.path)
    for base_path in (modelproperty_path, entry.path):
        if not base_path:
            continue
        for candidate in _mesh_import_target_sidecar_candidates_for_base(base_path, source_sidecar_path):
            _append(candidate)
    return tuple(ordered)


def _resolve_supplemental_target_entry(
    source_path: Path,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    preferred_paths: Sequence[str] = (),
) -> Tuple[Optional[ArchiveEntry], str]:
    candidate_virtual_paths: List[str] = []
    seen_virtual_paths: set[str] = set()
    for raw_path in list(preferred_paths) + list(_mesh_import_candidate_virtual_paths(source_path)):
        normalized = _normalize_virtual_path(raw_path)
        if not normalized or normalized in seen_virtual_paths:
            continue
        seen_virtual_paths.add(normalized)
        candidate_virtual_paths.append(raw_path)

    if archive_entries_by_normalized_path is not None:
        for candidate_virtual_path in candidate_virtual_paths:
            normalized = _normalize_virtual_path(candidate_virtual_path)
            entries = archive_entries_by_normalized_path.get(normalized, ())
            if entries:
                return entries[0], candidate_virtual_path.replace("\\", "/")

    basename = source_path.name.lower()
    if archive_entries_by_basename is not None and basename:
        entries = archive_entries_by_basename.get(basename, ())
        if len(entries) == 1:
            return entries[0], entries[0].path

    if candidate_virtual_paths:
        return None, candidate_virtual_paths[0].replace("\\", "/")
    return None, ""


def _build_mesh_import_local_dds_lookup(
    supplemental_files: Sequence[Path],
) -> Tuple[Dict[str, Path], Dict[str, Path]]:
    by_normalized_path: Dict[str, Path] = {}
    by_basename: Dict[str, Path] = {}
    for supplemental_path in supplemental_files:
        if supplemental_path.suffix.lower() != ".dds":
            continue
        resolved_path = supplemental_path.expanduser().resolve()
        for candidate_virtual_path in _mesh_import_candidate_virtual_paths(resolved_path):
            normalized = _normalize_virtual_path(candidate_virtual_path)
            if normalized and normalized not in by_normalized_path:
                by_normalized_path[normalized] = resolved_path
        basename = resolved_path.name.lower()
        if basename and basename not in by_basename:
            by_basename[basename] = resolved_path
    return by_normalized_path, by_basename


def _apply_mesh_import_local_sidecar_texture_overrides(
    preview_model: ModelPreviewData,
    parsed_mesh: Optional[ParsedMesh],
    sidecar_texture_bindings: Sequence[object],
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not getattr(preview_model, "meshes", None) or not sidecar_texture_bindings:
        return []

    from cdmw.core.archive import (
        _is_visible_model_texture_type,
        _is_anonymous_model_submesh_reference_key,
        _iter_model_submesh_reference_candidates,
        _iter_parsed_model_submeshes,
        _model_texture_hint_priority,
        _model_texture_semantic_priority,
        _normalize_model_submesh_reference,
        _resolve_model_texture_semantics,
    )
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    preview_cache: Dict[str, str] = {}
    resolved_by_submesh: Dict[str, Tuple[Tuple[int, int, int, int], Path, str, str, str]] = {}
    global_visible_bindings: List[Tuple[Path, str, str, str]] = []
    fallback_visible_bindings: List[Tuple[Tuple[int, int, int, int], Path, str, str, str]] = []
    seen_fallback_binding_keys: set[Tuple[str, str, str]] = set()
    seen_global_binding_keys: set[Tuple[str, str]] = set()
    promoted_anonymous_fallback = False

    for binding in sidecar_texture_bindings:
        texture_path = str(getattr(binding, "texture_path", "") or "").strip()
        if not texture_path:
            continue
        normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(texture_path)
        basename = PurePosixPath(normalized_texture_path or texture_path.replace("\\", "/")).name.lower()
        override_path = supplemental_dds_by_normalized_path.get(normalized_texture_path)
        if override_path is None and basename:
            override_path = supplemental_dds_by_basename.get(basename)
        if override_path is None:
            continue

        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(texture_path)
        priority = _model_texture_hint_priority(parameter_name)
        if priority is None:
            priority = _model_texture_semantic_priority(texture_type, semantic_subtype)
        if priority[0] <= 0 and not _is_visible_model_texture_type(texture_type):
            continue

        candidate_key = (priority[0], priority[1], confidence, -len(texture_path or override_path.name))
        submesh_name = str(getattr(binding, "submesh_name", "") or "").strip()
        submesh_keys = _iter_model_submesh_reference_candidates(submesh_name)
        fallback_binding_key = (
            _normalize_model_submesh_reference(submesh_name),
            basename,
            parameter_name.lower(),
        )
        if fallback_binding_key not in seen_fallback_binding_keys:
            seen_fallback_binding_keys.add(fallback_binding_key)
            fallback_visible_bindings.append((candidate_key, override_path, parameter_name, submesh_name, texture_path))
        if submesh_keys:
            for submesh_key in submesh_keys:
                existing = resolved_by_submesh.get(submesh_key)
                if existing is None or candidate_key > existing[0]:
                    resolved_by_submesh[submesh_key] = (
                        candidate_key,
                        override_path,
                        parameter_name,
                        submesh_name,
                        texture_path,
                    )
        else:
            global_key = (basename, parameter_name.lower())
            if global_key not in seen_global_binding_keys:
                seen_global_binding_keys.add(global_key)
                global_visible_bindings.append((override_path, parameter_name, submesh_name, texture_path))

    def _preview_path_for_dds(dds_path: Path) -> str:
        cache_key = str(dds_path).lower()
        preview_path = preview_cache.get(cache_key, "")
        if preview_path:
            return preview_path
        dds_info = None
        try:
            dds_info = parse_dds(dds_path)
        except Exception:
            dds_info = None
        preview_path = ensure_dds_display_preview_png(
            resolved_texconv_path,
            dds_path,
            dds_info=dds_info,
        )
        preview_cache[cache_key] = preview_path
        return preview_path

    assigned_count = 0
    unresolved_meshes: List[ModelPreviewMesh] = []
    unresolved_mesh_indices_by_id: Dict[int, int] = {}

    def _mesh_reference_candidates_for_index(mesh_index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
        parsed_submesh = parsed_submeshes[mesh_index] if 0 <= mesh_index < len(parsed_submeshes) else None
        return _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )

    def _mesh_preview_identity_is_anonymous(mesh_index: int, mesh: ModelPreviewMesh) -> bool:
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        return not candidate_keys or all(_is_anonymous_model_submesh_reference_key(candidate_key) for candidate_key in candidate_keys)

    for mesh_index, mesh in enumerate(preview_model.meshes):
        if str(getattr(mesh, "preview_texture_path", "") or "").strip():
            continue
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        best_match: Optional[Tuple[Tuple[int, int, int, int], Path, str, str, str]] = None
        for candidate_key_text in candidate_keys:
            resolved = resolved_by_submesh.get(candidate_key_text)
            if resolved is None:
                continue
            if best_match is None or resolved[0] > best_match[0]:
                best_match = resolved
        if best_match is None:
            unresolved_meshes.append(mesh)
            unresolved_mesh_indices_by_id[id(mesh)] = mesh_index
            continue
        _candidate_key, override_path, _parameter_name, submesh_name, texture_path = best_match
        try:
            mesh.preview_texture_path = _preview_path_for_dds(override_path)
            mesh.texture_name = texture_path or override_path.name
            mesh.preview_texture_flip_vertical = False
            current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
            if submesh_name and not current_material_name:
                mesh.material_name = submesh_name
            assigned_count += 1
        except Exception:
            continue

    if not global_visible_bindings and unresolved_meshes and fallback_visible_bindings:
        unresolved_meshes_are_anonymous = all(
            _mesh_preview_identity_is_anonymous(unresolved_mesh_indices_by_id.get(id(mesh), -1), mesh)
            for mesh in unresolved_meshes
        )
        unique_named_sidecar_submeshes = {
            _normalize_model_submesh_reference(submesh_name)
            for _candidate_key, _override_path, _parameter_name, submesh_name, _texture_path in fallback_visible_bindings
            if _normalize_model_submesh_reference(submesh_name)
        }
        should_promote_fallback = (
            len(preview_model.meshes) == 1
            or (
                unresolved_meshes_are_anonymous
                and (
                    len(unresolved_meshes) == 1
                    or len(parsed_submeshes) <= 1
                    or len(unique_named_sidecar_submeshes) == 1
                )
            )
        )
        if should_promote_fallback:
            fallback_visible_bindings.sort(key=lambda item: item[0], reverse=True)
            _candidate_key, override_path, parameter_name, submesh_name, texture_path = fallback_visible_bindings[0]
            global_visible_bindings.append((override_path, parameter_name, submesh_name, texture_path))
            promoted_anonymous_fallback = True

    if global_visible_bindings and unresolved_meshes:
        if len(global_visible_bindings) == 1:
            override_path, _parameter_name, submesh_name, texture_path = global_visible_bindings[0]
            for mesh in unresolved_meshes:
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                try:
                    mesh.preview_texture_path = _preview_path_for_dds(override_path)
                    mesh.texture_name = texture_path or override_path.name
                    mesh.preview_texture_flip_vertical = False
                    current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
                    if submesh_name and not current_material_name:
                        mesh.material_name = submesh_name
                    assigned_count += 1
                except Exception:
                    continue
        else:
            binding_index = 0
            for mesh in unresolved_meshes:
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                if binding_index >= len(global_visible_bindings):
                    break
                override_path, _parameter_name, submesh_name, texture_path = global_visible_bindings[binding_index]
                binding_index += 1
                try:
                    mesh.preview_texture_path = _preview_path_for_dds(override_path)
                    mesh.texture_name = texture_path or override_path.name
                    mesh.preview_texture_flip_vertical = False
                    current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
                    if submesh_name and not current_material_name:
                        mesh.material_name = submesh_name
                    assigned_count += 1
                except Exception:
                    continue

    if assigned_count <= 0:
        return []
    info_lines = [
        f"Applied {assigned_count:,} local sidecar-driven texture preview binding(s) from the selected supplemental files."
    ]
    if promoted_anonymous_fallback:
        info_lines.append(
            "Used a local sidecar texture fallback because the rebuilt preview did not preserve a reliable submesh/material name match."
        )
    return info_lines


def _apply_mesh_import_local_support_texture_overrides(
    preview_model: ModelPreviewData,
    parsed_mesh: Optional[ParsedMesh],
    sidecar_texture_bindings: Sequence[object],
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not getattr(preview_model, "meshes", None) or not sidecar_texture_bindings:
        return []

    from collections import defaultdict

    from cdmw.core.archive import (
        _infer_model_preview_normal_strength,
        _infer_model_preview_texture_slot,
        _iter_model_submesh_reference_candidates,
        _iter_parsed_model_submeshes,
        _model_texture_candidate_slot_priority,
        _model_texture_slot_hint_priority,
        _normalize_model_submesh_reference,
        _refine_model_texture_semantic_from_hint,
        _resolve_model_texture_semantic_details,
    )
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    preview_cache: Dict[str, str] = {}
    support_slots = ("normal", "material", "height")
    slot_labels = {
        "normal": "local normal-map override(s)",
        "material": "local material-mask override(s)",
        "height": "local height/displacement override(s)",
    }
    resolved_by_submesh: Dict[Tuple[str, str], Tuple[Tuple[int, int, int, int], Path, str, str, str]] = {}
    global_bindings: Dict[str, List[Tuple[Tuple[int, int, int, int], Path, str, str, str]]] = defaultdict(list)
    seen_global_keys: set[Tuple[str, str, str]] = set()
    assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}

    for binding in sidecar_texture_bindings:
        texture_path = str(getattr(binding, "texture_path", "") or "").strip()
        if not texture_path:
            continue
        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        slot_name = _infer_model_preview_texture_slot(texture_path, semantic_hint=parameter_name)
        if slot_name not in support_slots:
            continue
        normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(texture_path)
        basename = PurePosixPath(normalized_texture_path or texture_path.replace("\\", "/")).name.lower()
        override_path = supplemental_dds_by_normalized_path.get(normalized_texture_path)
        if override_path is None and basename:
            override_path = supplemental_dds_by_basename.get(basename)
        if override_path is None:
            continue

        slot_priority = (
            _model_texture_slot_hint_priority(slot_name, parameter_name)
            or _model_texture_candidate_slot_priority(slot_name, texture_path)
            or (0, 0)
        )
        candidate_key = (
            slot_priority[0],
            slot_priority[1],
            len(parameter_name),
            -len(texture_path or override_path.name),
        )
        submesh_name = str(getattr(binding, "submesh_name", "") or "").strip()
        submesh_keys = _iter_model_submesh_reference_candidates(submesh_name)
        if submesh_keys:
            for submesh_key in submesh_keys:
                resolved_key = (slot_name, submesh_key)
                existing = resolved_by_submesh.get(resolved_key)
                if existing is None or candidate_key > existing[0]:
                    resolved_by_submesh[resolved_key] = (
                        candidate_key,
                        override_path,
                        parameter_name,
                        submesh_name,
                        texture_path,
                    )
        else:
            global_key = (slot_name, basename, parameter_name.lower())
            if global_key not in seen_global_keys:
                seen_global_keys.add(global_key)
                global_bindings[slot_name].append(
                    (
                        candidate_key,
                        override_path,
                        parameter_name,
                        submesh_name,
                        texture_path,
                    )
                )

    def _preview_path_for_dds(dds_path: Path) -> str:
        cache_key = str(dds_path).lower()
        preview_path = preview_cache.get(cache_key, "")
        if preview_path:
            return preview_path
        dds_info = None
        try:
            dds_info = parse_dds(dds_path)
        except Exception:
            dds_info = None
        preview_path = ensure_dds_display_preview_png(
            resolved_texconv_path,
            dds_path,
            dds_info=dds_info,
        )
        preview_cache[cache_key] = preview_path
        return preview_path

    def _assign_slot(
        mesh: ModelPreviewMesh,
        slot_name: str,
        override_path: Path,
        parameter_name: str,
        texture_path: str,
    ) -> bool:
        try:
            preview_path = _preview_path_for_dds(override_path)
        except Exception:
            return False
        if slot_name == "normal":
            mesh.preview_normal_texture_path = preview_path
            mesh.preview_normal_texture_name = texture_path or override_path.name
            mesh.preview_normal_texture_strength = _infer_model_preview_normal_strength(
                base_texture_path=str(getattr(mesh, "texture_name", "") or "").strip(),
                normal_texture_path=texture_path or override_path.name,
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                semantic_hint=parameter_name,
                prefer_stronger=False,
            )
            return True
        if slot_name == "material":
            semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
                texture_path or override_path.name
            )
            semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
                semantic_type,
                semantic_subtype,
                parameter_name,
            )
            mesh.preview_material_texture_path = preview_path
            mesh.preview_material_texture_name = texture_path or override_path.name
            mesh.preview_material_texture_type = semantic_type
            mesh.preview_material_texture_subtype = semantic_subtype
            mesh.preview_material_texture_packed_channels = tuple(packed_channels)
            return True
        if slot_name == "height":
            mesh.preview_height_texture_path = preview_path
            mesh.preview_height_texture_name = texture_path or override_path.name
            return True
        return False

    for mesh_index, mesh in enumerate(preview_model.meshes):
        parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
        candidate_keys = _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )
        for slot_name in support_slots:
            best_match: Optional[Tuple[Tuple[int, int, int, int], Path, str, str, str]] = None
            for candidate_key_text in candidate_keys:
                resolved = resolved_by_submesh.get((slot_name, candidate_key_text))
                if resolved is None:
                    continue
                if best_match is None or resolved[0] > best_match[0]:
                    best_match = resolved
            if best_match is None:
                continue
            _candidate_key, override_path, parameter_name, _submesh_name, texture_path = best_match
            if _assign_slot(mesh, slot_name, override_path, parameter_name, texture_path):
                assigned_by_slot[slot_name] += 1

    for slot_name in support_slots:
        bindings = global_bindings.get(slot_name, [])
        if not bindings:
            continue
        bindings.sort(key=lambda item: item[0], reverse=True)
        unresolved_meshes = [
            mesh
            for mesh in preview_model.meshes
            if not str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
        ]
        if not unresolved_meshes:
            continue
        if len(bindings) == 1:
            _candidate_key, override_path, parameter_name, _submesh_name, texture_path = bindings[0]
            for mesh in unresolved_meshes:
                if _assign_slot(mesh, slot_name, override_path, parameter_name, texture_path):
                    assigned_by_slot[slot_name] += 1
            continue
        binding_index = 0
        for mesh in unresolved_meshes:
            if binding_index >= len(bindings):
                break
            _candidate_key, override_path, parameter_name, _submesh_name, texture_path = bindings[binding_index]
            binding_index += 1
            if _assign_slot(mesh, slot_name, override_path, parameter_name, texture_path):
                assigned_by_slot[slot_name] += 1

    total_assigned = sum(assigned_by_slot.values())
    if total_assigned <= 0:
        return []
    info_lines = [f"Applied {total_assigned:,} local DDS support-map override(s) from the selected supplemental files."]
    for slot_name in support_slots:
        count = assigned_by_slot[slot_name]
        if count > 0:
            info_lines.append(f"{slot_labels[slot_name].capitalize()}: {count:,}.")
    return info_lines


def _apply_mesh_import_local_texture_overrides(
    preview_model: ModelPreviewData,
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not getattr(preview_model, "meshes", None):
        return []

    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    preview_cache: Dict[str, str] = {}
    override_count = 0
    unresolved_names: List[str] = []
    for mesh in preview_model.meshes:
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if not texture_name:
            continue
        normalized_texture_name = _normalize_virtual_path(texture_name)
        basename = PurePosixPath(texture_name.replace("\\", "/")).name.lower()
        override_path = supplemental_dds_by_normalized_path.get(normalized_texture_name)
        if override_path is None and basename:
            override_path = supplemental_dds_by_basename.get(basename)
        if override_path is None:
            if texture_name not in unresolved_names and len(unresolved_names) < 5:
                unresolved_names.append(texture_name)
            continue
        cache_key = str(override_path).lower()
        preview_path = preview_cache.get(cache_key, "")
        if not preview_path:
            dds_info = None
            try:
                dds_info = parse_dds(override_path)
            except Exception:
                dds_info = None
            preview_path = ensure_dds_display_preview_png(
                resolved_texconv_path,
                override_path,
                dds_info=dds_info,
            )
            preview_cache[cache_key] = preview_path
        mesh.preview_texture_path = preview_path
        mesh.preview_texture_flip_vertical = False
        override_count += 1

    info_lines: List[str] = []
    if override_count > 0:
        info_lines.append(f"Applied {override_count:,} local DDS override texture(s) from the selected supplemental files.")
    return info_lines


def _merge_sidecar_text_maps(
    base_map: Mapping[str, Tuple[str, ...]],
    extra_map: Mapping[str, Tuple[str, ...]],
) -> Dict[str, Tuple[str, ...]]:
    merged: Dict[str, List[str]] = {key: list(values) for key, values in base_map.items()}
    for key, values in extra_map.items():
        bucket = merged.setdefault(key, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return {key: tuple(values) for key, values in merged.items()}










def _preview_meshes_from_submeshes(submeshes: Sequence[SubMesh]) -> List[ModelPreviewMesh]:
    preview_meshes: List[ModelPreviewMesh] = []
    for submesh_index, submesh in enumerate(submeshes):
        if not submesh.vertices or not submesh.faces:
            continue
        indices: List[int] = []
        for face in submesh.faces:
            indices.extend(int(index) for index in face[:3])
        preview_mesh = ModelPreviewMesh(
            material_name=str(submesh.material or submesh.name or ""),
            texture_name=str(submesh.texture or ""),
            positions=[tuple(vertex) for vertex in submesh.vertices],
            texture_coordinates=[tuple(uv) for uv in submesh.uvs[: len(submesh.vertices)]],
            normals=[tuple(normal) for normal in submesh.normals[: len(submesh.vertices)]],
            indices=indices,
            source_submesh_index=submesh_index,
            source_vertex_indices=list(range(len(submesh.vertices))),
            source_face_indices=list(range(len(submesh.faces))),
        )
        preview_color = tuple(getattr(submesh, "preview_color", ()) or ())
        if len(preview_color) >= 3:
            preview_mesh.preview_color = tuple(float(component) for component in preview_color[:3])
        preview_texture_path = str(getattr(submesh, "preview_texture_path", "") or "").strip()
        if preview_texture_path:
            preview_mesh.preview_texture_path = preview_texture_path
            preview_mesh.preview_texture_image = None
        preview_texture_tint = tuple(getattr(submesh, "preview_texture_tint", ()) or ())
        if len(preview_texture_tint) >= 3:
            preview_mesh.preview_texture_tint = tuple(float(component) for component in preview_texture_tint[:3])
        preview_texture_uv_scale = tuple(getattr(submesh, "preview_texture_uv_scale", ()) or ())
        if len(preview_texture_uv_scale) >= 2:
            preview_mesh.preview_texture_uv_scale = tuple(float(component) for component in preview_texture_uv_scale[:2])
        preview_vertex_color = tuple(getattr(submesh, "preview_vertex_color_mean", ()) or ())
        if len(preview_vertex_color) >= 3:
            preview_mesh.preview_vertex_color_mean = tuple(float(component) for component in preview_vertex_color[:3])
            preview_mesh.preview_vertex_color_count = int(getattr(submesh, "preview_vertex_color_count", 0) or 0)
        preview_vertex_alpha_mean = getattr(submesh, "preview_vertex_alpha_mean", None)
        if preview_vertex_alpha_mean is not None:
            try:
                preview_mesh.preview_vertex_alpha_mean = float(preview_vertex_alpha_mean)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_vertex_alpha_min = getattr(submesh, "preview_vertex_alpha_min", None)
        if preview_vertex_alpha_min is not None:
            try:
                preview_mesh.preview_vertex_alpha_min = float(preview_vertex_alpha_min)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_texture_brightness = getattr(submesh, "preview_texture_brightness", None)
        if preview_texture_brightness is not None:
            try:
                preview_mesh.preview_texture_brightness = float(preview_texture_brightness)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_native_material_overrides = getattr(submesh, "preview_native_material_overrides", None)
        if isinstance(preview_native_material_overrides, dict):
            preview_mesh.preview_native_material_overrides = dict(preview_native_material_overrides)
        preview_mesh.preview_alpha_mode = str(getattr(submesh, "preview_alpha_mode", "") or "").strip()
        preview_mesh.preview_double_sided = bool(getattr(submesh, "preview_double_sided", False))
        preview_normal_texture_path = str(getattr(submesh, "preview_normal_texture_path", "") or "").strip()
        if preview_normal_texture_path:
            preview_mesh.preview_normal_texture_path = preview_normal_texture_path
            preview_mesh.preview_normal_texture_name = str(
                getattr(submesh, "preview_normal_texture_name", "") or Path(preview_normal_texture_path).name
            )
            preview_mesh.preview_normal_texture_strength = float(
                getattr(submesh, "preview_normal_texture_strength", 0.75) or 0.75
            )
        preview_material_texture_path = str(getattr(submesh, "preview_material_texture_path", "") or "").strip()
        if preview_material_texture_path:
            preview_mesh.preview_material_texture_path = preview_material_texture_path
            preview_mesh.preview_material_texture_name = str(
                getattr(submesh, "preview_material_texture_name", "") or Path(preview_material_texture_path).name
            )
            preview_mesh.preview_material_texture_type = str(getattr(submesh, "preview_material_texture_type", "") or "").strip()
            preview_mesh.preview_material_texture_subtype = str(
                getattr(submesh, "preview_material_texture_subtype", "") or ""
            ).strip()
            preview_mesh.preview_material_texture_packed_channels = tuple(
                str(channel or "").strip()
                for channel in (getattr(submesh, "preview_material_texture_packed_channels", ()) or ())
                if str(channel or "").strip()
            )
        preview_height_texture_path = str(getattr(submesh, "preview_height_texture_path", "") or "").strip()
        if preview_height_texture_path:
            preview_mesh.preview_height_texture_path = preview_height_texture_path
            preview_mesh.preview_height_texture_name = str(
                getattr(submesh, "preview_height_texture_name", "") or Path(preview_height_texture_path).name
            )
        preview_material_texture_inputs = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        if preview_material_texture_inputs:
            preview_mesh.preview_material_texture_inputs = preview_material_texture_inputs
            if any(
                "emissive" in str(getattr(item, "shader_family", "") or "").lower()
                or str(getattr(item, "slot_kind", "") or "").lower() == "emissive"
                for item in preview_material_texture_inputs
            ):
                preview_mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
        preview_meshes.append(preview_mesh)
    return preview_meshes


def parsed_mesh_to_preview_model(parsed_mesh: ParsedMesh) -> ModelPreviewData:
    if parsed_mesh.format == "pamlod" and parsed_mesh.lod_levels:
        source_submeshes = parsed_mesh.lod_levels[0]
        preview_model = _build_model_preview(parsed_mesh.path, "pamlod", _preview_meshes_from_submeshes(source_submeshes), "lod mesh")
        preview_model.lod_index = 0
        preview_model.lod_count = len(parsed_mesh.lod_levels)
        preview_model.summary = _build_lod_summary(
            parsed_mesh.path,
            displayed_lod_index=0,
            recovered_lod_count=len(parsed_mesh.lod_levels),
            vertex_count=preview_model.vertex_count,
            face_count=preview_model.face_count,
        )
        return preview_model

    source_submeshes = parsed_mesh.submeshes
    label = "submesh" if parsed_mesh.format != "pac" else "mesh"
    preview_model = _build_model_preview(parsed_mesh.path, parsed_mesh.format, _preview_meshes_from_submeshes(source_submeshes), label)
    if scene_import_normalizes_texture_v(parsed_mesh.format, parsed_mesh.path):
        for mesh in getattr(preview_model, "meshes", ()) or ():
            if getattr(mesh, "preview_texture_flip_vertical", None) is None:
                mesh.preview_texture_flip_vertical = True
    return preview_model


def attach_scene_preview_textures(
    preview_model: object,
    scene_result: SceneImportResult,
    scene_path: str | Path,
) -> int:
    if not isinstance(preview_model, ModelPreviewData):
        return 0
    source_path = Path(scene_path).expanduser()
    try:
        source_path = source_path.resolve()
    except OSError:
        source_path = source_path.absolute()

    texture_paths: List[Path] = []
    for candidate in tuple(scene_result.discovered_texture_files or ()) + tuple(scene_result.extracted_embedded_files or ()):
        if isinstance(candidate, Path) and candidate.is_file():
            texture_paths.append(candidate.resolve())
    for mesh in getattr(preview_model, "meshes", []) or []:
        for attr_name in (
            "preview_texture_path",
            "preview_normal_texture_path",
            "preview_material_texture_path",
            "preview_height_texture_path",
        ):
            candidate_text = str(getattr(mesh, attr_name, "") or "").strip()
            if not candidate_text:
                continue
            candidate = Path(candidate_text)
            if candidate.is_file():
                texture_paths.append(candidate.resolve())
    if not texture_paths:
        for root in (source_path.parent, source_path.parent / "textures", source_path.parent.parent / "textures"):
            if not root.is_dir():
                continue
            try:
                for candidate in root.iterdir():
                    if candidate.is_file() and candidate.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                        texture_paths.append(candidate.resolve())
            except OSError:
                continue
    texture_paths = list(dict.fromkeys(texture_paths))
    by_key: Dict[str, Path] = {}
    for texture_path in texture_paths:
        by_key[str(texture_path).replace("\\", "/").lower()] = texture_path
        by_key[texture_path.as_posix().lower()] = texture_path
        by_key[texture_path.name.lower()] = texture_path
        by_key[texture_path.stem.lower()] = texture_path

    def compact(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def slot_kind(path: Path) -> str:
        stem = compact(path.stem)
        if any(token in stem for token in ("emissive", "emission", "glow", "illumination", "illum")):
            return "emissive"
        if any(token in stem for token in ("normalmap", "normalgl", "normaldx", "normal", "nrm", "bump")):
            return "normal"
        if any(token in stem for token in ("heightmap", "height", "displacement", "disp", "depth")):
            return "height"
        if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "diffusemap", "colormap")):
            return "base"
        if any(
            token in stem
            for token in (
                "metallicroughness",
                "roughnessmetallic",
                "occlusionroughnessmetallic",
                "roughness",
                "metallic",
                "metalness",
                "ambientocclusion",
                "occlusion",
                "specular",
                "glossiness",
                "gloss",
                "opacity",
                "alpha",
                "orm",
                "rma",
                "mra",
                "arm",
                "mask",
            )
        ):
            return "material"
        return "base"

    def material_subtype(path: Path) -> str:
        stem = compact(path.stem)
        if "occlusionroughnessmetallic" in stem or "orm" in stem:
            return "orm"
        if "metallicroughness" in stem or "metalrough" in stem or "metallicrough" in stem:
            return "metallic_roughness"
        if "roughnessmetallic" in stem or "rma" in stem:
            return "rma"
        if "metallic" in stem or "metalness" in stem:
            return "metallic"
        if "roughness" in stem:
            return "roughness"
        if "occlusion" in stem or stem.endswith("ao"):
            return "ao"
        if "specular" in stem:
            return "specular"
        return "packed"

    def material_channels(subtype: str) -> Tuple[str, ...]:
        if subtype == "specular":
            return ("specular", "glossiness")
        if subtype == "metallic_roughness":
            return ("roughness", "metallic")
        if subtype == "orm":
            return ("ao", "roughness", "metallic")
        if subtype == "rma":
            return ("roughness", "metallic", "ao")
        return ()

    def texture_group_key(path: Path) -> str:
        stem = compact(path.stem)
        for token in (
            "metallicroughness",
            "roughnessmetallic",
            "occlusionroughnessmetallic",
            "basecolor",
            "basecolour",
            "diffuse",
            "albedo",
            "normalmap",
            "normalgl",
            "normaldx",
            "normal",
            "nrm",
            "bump",
            "roughness",
            "metallic",
            "metalness",
            "ambientocclusion",
            "occlusion",
            "specular",
            "glossiness",
            "gloss",
            "heightmap",
            "height",
            "displacement",
            "disp",
            "depth",
            "emissive",
            "emission",
            "glow",
            "illumination",
            "illum",
            "opacity",
            "alpha",
            "orm",
            "rma",
            "mra",
            "arm",
            "mask",
            "color",
            "colour",
            "base",
        ):
            stem = stem.replace(token, "")
        return stem or compact(path.stem)

    grouped: Dict[str, Dict[str, Path]] = defaultdict(dict)
    for texture_path in texture_paths:
        grouped[texture_group_key(texture_path)].setdefault(slot_kind(texture_path), texture_path)

    def resolve_texture(value: object) -> Optional[Path]:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            return None
        direct = Path(text)
        if direct.is_file():
            return direct.resolve()
        local = source_path.parent.joinpath(*PurePosixPath(text).parts)
        if local.is_file():
            return local.resolve()
        return by_key.get(text.lower()) or by_key.get(Path(text).name.lower()) or by_key.get(Path(text).stem.lower())

    def assign_base(mesh: ModelPreviewMesh, path: Path) -> int:
        path_text = str(path)
        mesh.preview_texture_path = path_text
        mesh.preview_texture_image = None
        mesh.preview_base_texture_default_path = path_text
        mesh.preview_base_texture_default_name = path.name
        return 1

    def assign_normal(mesh: ModelPreviewMesh, path: Path) -> int:
        path_text = str(path)
        mesh.preview_normal_texture_path = path_text
        mesh.preview_normal_texture_name = path.name
        mesh.preview_normal_texture_strength = float(getattr(mesh, "preview_normal_texture_strength", 0.0) or 0.75)
        mesh.preview_normal_texture_default_path = path_text
        mesh.preview_normal_texture_default_name = path.name
        mesh.preview_normal_texture_default_strength = mesh.preview_normal_texture_strength
        return 1

    def assign_material(mesh: ModelPreviewMesh, path: Path) -> int:
        path_text = str(path)
        subtype = material_subtype(path)
        mesh.preview_material_texture_path = path_text
        mesh.preview_material_texture_name = path.name
        mesh.preview_material_texture_type = subtype if subtype in {"ao", "specular", "roughness", "metallic"} else "material"
        mesh.preview_material_texture_subtype = subtype
        mesh.preview_material_texture_packed_channels = material_channels(subtype)
        mesh.preview_material_texture_default_path = path_text
        mesh.preview_material_texture_default_name = path.name
        mesh.preview_material_texture_default_type = mesh.preview_material_texture_type
        mesh.preview_material_texture_default_subtype = mesh.preview_material_texture_subtype
        mesh.preview_material_texture_default_packed_channels = mesh.preview_material_texture_packed_channels
        return 1

    def assign_material_input(
        mesh: ModelPreviewMesh,
        *,
        slot_kind: str,
        path: Path,
        semantic_type: str,
        semantic_subtype: str,
        packed_channels: Sequence[str] = (),
        shader_family: str = "",
        parameters: Sequence[PreviewMaterialParameterInput] = (),
    ) -> int:
        existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
        path_text = str(path)
        normalized_path_text = path_text.replace("\\", "/").lower()
        if any(
            str(getattr(item, "slot_kind", "") or "").lower() == slot_kind
            and (
                str(getattr(item, "texture_name", "") or "").lower() == path.name.lower()
                or str(
                    getattr(item, "preview_texture_path", "")
                    or getattr(item, "source_texture_path", "")
                    or ""
                ).replace("\\", "/").lower()
                == normalized_path_text
            )
            for item in existing
        ):
            return 0
        parameter_name = {
            "base": "_baseColorTexture",
            "normal": "_normalTexture",
            "material": "_metallicRoughnessTexture",
            "ao": "_occlusionTexture",
            "emissive": "_emissiveIntensityTexture",
            "height": "_heightTexture",
        }.get(slot_kind, "")
        existing.append(
            PreviewMaterialTextureInput(
                slot_kind=slot_kind,
                parameter_name=parameter_name,
                source_texture_path=path_text,
                source_dds_path=path_text if path.suffix.lower() == ".dds" else "",
                texture_name=path.name,
                preview_texture_path=path_text,
                semantic_type=semantic_type,
                semantic_subtype=semantic_subtype,
                packed_channels=tuple(str(channel) for channel in packed_channels if str(channel)),
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                shader_family=shader_family,
                confidence="scene",
                visualized=True,
                material_parameters=tuple(parameters),
            )
        )
        mesh.preview_material_texture_inputs = tuple(existing)
        if slot_kind == "emissive":
            mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
        return 1

    def assign_emissive(mesh: ModelPreviewMesh, path: Path) -> int:
        return assign_material_input(
            mesh,
            slot_kind="emissive",
            path=path,
            semantic_type="emissive",
            semantic_subtype="emissive",
            shader_family="SkinnedMeshEmissive_Ver2",
            parameters=(
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    value="1.000000",
                    numeric_value=1.0,
                ),
            ),
        )

    def assign_height(mesh: ModelPreviewMesh, path: Path) -> int:
        path_text = str(path)
        mesh.preview_height_texture_path = path_text
        mesh.preview_height_texture_name = path.name
        mesh.preview_height_texture_default_path = path_text
        mesh.preview_height_texture_default_name = path.name
        return 1

    meshes = [mesh for mesh in getattr(preview_model, "meshes", []) or [] if isinstance(mesh, ModelPreviewMesh)]
    base_candidates = [path for path in texture_paths if slot_kind(path) == "base"]
    single_mesh_base = base_candidates[0] if len(meshes) == 1 and len(base_candidates) == 1 else None
    resolved_count = 0
    for mesh in meshes:
        resolved_paths: Dict[str, Path] = {}
        for slot_name, attr_name in (
            ("base", "preview_texture_path"),
            ("normal", "preview_normal_texture_path"),
            ("material", "preview_material_texture_path"),
            ("height", "preview_height_texture_path"),
        ):
            existing = resolve_texture(getattr(mesh, attr_name, ""))
            if existing is not None:
                resolved_paths[slot_name] = existing
        named_texture = resolve_texture(getattr(mesh, "texture_name", ""))
        if named_texture is not None:
            named_kind = slot_kind(named_texture)
            if named_kind == "base":
                resolved_paths.setdefault("base", named_texture)
            elif named_kind == "normal":
                resolved_paths.setdefault("normal", named_texture)
            elif named_kind == "height":
                resolved_paths.setdefault("height", named_texture)
            else:
                resolved_paths.setdefault("material", named_texture)
        for item in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ()):
            slot_name = str(getattr(item, "slot_kind", "") or "").strip().lower()
            if slot_name not in {"base", "normal", "material", "ao", "emissive", "height"}:
                continue
            existing = resolve_texture(
                str(getattr(item, "preview_texture_path", "") or "")
                or str(getattr(item, "source_texture_path", "") or "")
                or str(getattr(item, "texture_name", "") or "")
            )
            if existing is not None:
                resolved_paths.setdefault(slot_name, existing)

        sibling_group: Mapping[str, Path] = {}
        group_source = resolved_paths.get("base") or resolved_paths.get("material") or resolved_paths.get("normal") or resolved_paths.get("height")
        if group_source is not None:
            sibling_group = grouped.get(texture_group_key(group_source), {})
        material_key = compact(getattr(mesh, "material_name", ""))
        if not resolved_paths.get("base") and material_key:
            for group_key, group in grouped.items():
                base_path = group.get("base")
                if base_path is None:
                    continue
                compact_group_key = compact(group_key)
                if compact_group_key and (compact_group_key in material_key or material_key in compact_group_key):
                    resolved_paths["base"] = base_path
                    sibling_group = group
                    break
        if not resolved_paths.get("base") and sibling_group.get("base") is not None:
            group_key = compact(texture_group_key(group_source)) if group_source is not None else ""
            if not material_key or (group_key and (group_key in material_key or material_key in group_key)):
                resolved_paths["base"] = sibling_group["base"]
        if not resolved_paths.get("base") and single_mesh_base is not None:
            resolved_paths["base"] = single_mesh_base

        if resolved_paths.get("base") is not None:
            resolved_count += assign_base(mesh, resolved_paths["base"])
        if sibling_group:
            resolved_paths.setdefault("normal", sibling_group.get("normal"))
            resolved_paths.setdefault("material", sibling_group.get("material"))
            resolved_paths.setdefault("emissive", sibling_group.get("emissive"))
            resolved_paths.setdefault("height", sibling_group.get("height"))
        if resolved_paths.get("normal") is not None:
            resolved_count += assign_normal(mesh, resolved_paths["normal"])
        if resolved_paths.get("material") is not None:
            resolved_count += assign_material(mesh, resolved_paths["material"])
            subtype = material_subtype(resolved_paths["material"])
            resolved_count += assign_material_input(
                mesh,
                slot_kind="material",
                path=resolved_paths["material"],
                semantic_type="material",
                semantic_subtype=subtype,
                packed_channels=material_channels(subtype),
            )
        if resolved_paths.get("ao") is not None:
            resolved_count += assign_material_input(
                mesh,
                slot_kind="ao",
                path=resolved_paths["ao"],
                semantic_type="ao",
                semantic_subtype="ao",
                packed_channels=("ao",),
            )
        if resolved_paths.get("emissive") is not None:
            resolved_count += assign_emissive(mesh, resolved_paths["emissive"])
        if resolved_paths.get("height") is not None:
            resolved_count += assign_height(mesh, resolved_paths["height"])
    return resolved_count


def _restore_rebuilt_mesh_texture_identity(
    source_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
) -> int:
    if not source_mesh.submeshes or not rebuilt_mesh.submeshes:
        return 0

    def _normalize_identity(value: str) -> str:
        return str(value or "").strip().lower()

    source_by_name: Dict[str, SubMesh] = {}
    duplicate_names: set[str] = set()
    for submesh in source_mesh.submeshes:
        normalized_name = _normalize_identity(submesh.name)
        if not normalized_name:
            continue
        if normalized_name in source_by_name:
            duplicate_names.add(normalized_name)
            continue
        source_by_name[normalized_name] = submesh
    for duplicate_name in duplicate_names:
        source_by_name.pop(duplicate_name, None)

    restored_count = 0
    for index, rebuilt_submesh in enumerate(rebuilt_mesh.submeshes):
        source_submesh: Optional[SubMesh] = None
        normalized_name = _normalize_identity(rebuilt_submesh.name)
        if normalized_name:
            source_submesh = source_by_name.get(normalized_name)
        if source_submesh is None and index < len(source_mesh.submeshes):
            source_submesh = source_mesh.submeshes[index]
        if source_submesh is None:
            continue

        source_texture = str(getattr(source_submesh, "texture", "") or "").strip()
        if source_texture and str(getattr(rebuilt_submesh, "texture", "") or "").strip() != source_texture:
            rebuilt_submesh.texture = source_texture
            restored_count += 1
        if not str(getattr(rebuilt_submesh, "material", "") or "").strip():
            rebuilt_submesh.material = str(getattr(source_submesh, "material", "") or "").strip()
        if not str(getattr(rebuilt_submesh, "name", "") or "").strip():
            rebuilt_submesh.name = str(getattr(source_submesh, "name", "") or "").strip()
    return restored_count


def build_mesh_preview_from_bytes(data: bytes, virtual_path: str) -> Tuple[ModelPreviewData, ParsedMesh]:
    parsed_mesh = parse_mesh(data, virtual_path)
    preview_model = parsed_mesh_to_preview_model(parsed_mesh)
    return preview_model, parsed_mesh


def _build_selected_sidecar_texture_bindings(
    supplemental_files: Sequence[Path],
) -> Tuple[
    Tuple[object, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    from collections import defaultdict

    from cdmw.core.archive import _ArchiveModelSidecarTextureBinding
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup, parse_texture_sidecar_bindings

    bindings: List[object] = []
    sidecar_paths: List[str] = []
    seen_binding_keys: set[Tuple[str, str, str]] = set()
    sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
    sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)

    def append_unique_text(target: Dict[str, List[str]], key: str, text: str) -> None:
        normalized_key = str(key or "").strip()
        normalized_text = str(text or "")
        if not normalized_key or not normalized_text.strip():
            return
        bucket = target[normalized_key]
        if normalized_text not in bucket:
            bucket.append(normalized_text)

    def read_sidecar_text(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
            try:
                return data.decode(encoding).replace("\ufeff", "")
            except UnicodeError:
                continue
        return data.decode("utf-8", errors="replace").replace("\ufeff", "")

    for supplemental_path in supplemental_files:
        if supplemental_path.suffix.lower() not in MESH_IMPORT_SIDECAR_EXTENSIONS:
            continue
        resolved_path = supplemental_path.expanduser().resolve()
        if not resolved_path.is_file():
            continue
        try:
            text = read_sidecar_text(resolved_path)
        except Exception:
            continue
        parsed_bindings = parse_texture_sidecar_bindings(text, sidecar_path=resolved_path.name)
        if not parsed_bindings:
            continue
        sidecar_paths.append(resolved_path.name)
        for binding in parsed_bindings:
            texture_role = binding.texture_role
            visualization_state = binding.visualization_state
            try:
                from cdmw.modding.asset_replacement import classify_texture_binding

                classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                texture_role = classification.slot_label or classification.slot_kind
                visualization_state = classification.visual_state
            except Exception:
                pass
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            key = (
                normalized_texture_path,
                str(binding.submesh_name or "").strip().lower(),
                str(binding.parameter_name or "").strip().lower(),
            )
            if normalized_texture_path:
                append_unique_text(sidecar_texts_by_normalized_path, normalized_texture_path, text)
                basename = PurePosixPath(normalized_texture_path).name
                if basename:
                    append_unique_text(sidecar_texts_by_basename, basename, text)
            if key in seen_binding_keys:
                continue
            seen_binding_keys.add(key)
            bindings.append(
                _ArchiveModelSidecarTextureBinding(
                    texture_path=binding.texture_path,
                    parameter_name=binding.parameter_name,
                    submesh_name=binding.submesh_name,
                    sidecar_path=resolved_path.name,
                    sidecar_kind=binding.sidecar_kind,
                    linked_mesh_path=binding.linked_mesh_path,
                    part_name=binding.part_name,
                    material_name=binding.material_name,
                    shader_family=binding.shader_family,
                    texture_role=texture_role,
                    visualization_state=visualization_state,
                    resolved_texture_exists=binding.resolved_texture_exists,
                    srgb_mode=str(getattr(binding, "srgb_mode", "") or ""),
                    parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or ""),
                    material_output_quality=str(getattr(binding, "material_output_quality", "") or ""),
                    layer_role=str(getattr(binding, "layer_role", "") or ""),
                    layer_channel=str(getattr(binding, "layer_channel", "") or ""),
                    blend_flags=tuple(
                        str(value)
                        for value in tuple(getattr(binding, "blend_flags", ()) or ())
                        if str(value)
                    ),
                )
            )
    return (
        tuple(bindings),
        tuple(sidecar_paths),
        {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
        {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
    )


def _build_mesh_import_supplemental_file_specs(
    entry: ArchiveEntry,
    supplemental_files: Sequence[Path],
    texture_references: Sequence[ArchiveModelTextureReference],
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    if not supplemental_files:
        return ()

    reference_candidates_by_basename: Dict[str, List[str]] = {}
    for reference in texture_references:
        resolved_archive_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
        reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        target_path = resolved_archive_path or reference_name
        if not target_path:
            continue
        basename = PurePosixPath(target_path.replace("\\", "/")).name.lower()
        if not basename:
            continue
        bucket = reference_candidates_by_basename.setdefault(basename, [])
        if target_path not in bucket:
            bucket.append(target_path)

    related_entries: Sequence[ArchiveEntry] = ()
    if archive_entries_by_basename is not None:
        from cdmw.core.archive import _find_archive_model_related_entries

        related_entries = _find_archive_model_related_entries(entry, dict(archive_entries_by_basename))
    related_entries_by_extension: Dict[str, List[ArchiveEntry]] = {}
    for related_entry in related_entries:
        related_entries_by_extension.setdefault(related_entry.extension.lower(), []).append(related_entry)

    specs: List[MeshImportSupplementalFileSpec] = []
    for supplemental_path in supplemental_files:
        resolved_source = supplemental_path.expanduser().resolve()
        if not resolved_source.is_file():
            continue
        extension = resolved_source.suffix.lower()
        if extension in SCENE_TEXTURE_SOURCE_EXTENSIONS - {".dds"}:
            continue
        preferred_paths: List[str] = []
        if extension == ".dds":
            preferred_paths.extend(reference_candidates_by_basename.get(resolved_source.name.lower(), ()))
            preferred_paths.extend(_mesh_import_loose_texture_preferred_paths(resolved_source))
        elif extension in MESH_IMPORT_SIDECAR_EXTENSIONS:
            preferred_paths.extend(
                _mesh_import_sidecar_preferred_paths(entry, resolved_source, related_entries_by_extension)
            )
        elif extension in MESH_IMPORT_COMPANION_EXTENSIONS:
            preferred_paths.extend(_mesh_import_candidate_virtual_paths(resolved_source))
        target_entry, target_path = _resolve_supplemental_target_entry(
            resolved_source,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
            preferred_paths=preferred_paths,
        )
        if extension == ".dds" and target_entry is None and not preferred_paths:
            continue
        kind = (
            "texture"
            if extension == ".dds"
            else "sidecar"
            if extension in MESH_IMPORT_SIDECAR_EXTENSIONS
            else "companion"
            if extension in MESH_IMPORT_COMPANION_EXTENSIONS
            else "file"
        )
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=resolved_source,
                target_path=target_path or (target_entry.path if isinstance(target_entry, ArchiveEntry) else ""),
                kind=kind,
                target_entry=target_entry if isinstance(target_entry, ArchiveEntry) else None,
                used_for_preview=kind in {"texture", "sidecar", "companion"},
            )
        )
    return tuple(specs)


def _find_first_archive_entry_by_virtual_path(
    virtual_path: str,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Optional[ArchiveEntry]:
    if archive_entries_by_normalized_path is None:
        return None
    candidates = archive_entries_by_normalized_path.get(_normalize_virtual_path(virtual_path), ())
    return candidates[0] if candidates else None


def _collect_original_mesh_sidecar_texts(
    entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[Tuple[ArchiveEntry, str], ...]:
    if archive_entries_by_basename is None:
        return ()
    from cdmw.core.archive import (
        _find_archive_model_sidecar_entries,
        read_archive_entry_data,
        try_decode_text_like_archive_data,
    )

    sidecars: List[Tuple[ArchiveEntry, str]] = []
    for sidecar_entry in _find_archive_model_sidecar_entries(entry, dict(archive_entries_by_basename)):
        try:
            sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry)
        except Exception:
            continue
        sidecar_text = try_decode_text_like_archive_data(sidecar_data)
        if sidecar_text:
            sidecars.append((sidecar_entry, sidecar_text))
    return tuple(sidecars)


def _source_owned_sidecar_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _source_owned_sidecar_name_is_helper_row(value: str) -> bool:
    key = _source_owned_sidecar_name_key(value)
    if not key:
        return False
    parts = tuple(part for part in key.split("_") if part)
    if not parts:
        return False
    if parts[-1] in {"black", "inside"}:
        return True
    return "mask" in parts and key.startswith(("cd_", "pew_", "pe_", "npc_", "monster_", "vehicle_"))


def _align_source_owned_target_names_to_mesh(
    wrapper_names: Sequence[str],
    original_mesh: ParsedMesh,
) -> Tuple[str, ...]:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if not wrapper_names or not submeshes:
        return tuple(str(name or "").strip() for name in tuple(wrapper_names or ()) if str(name or "").strip())
    wrappers = tuple(str(name or "").strip() for name in tuple(wrapper_names or ()) if str(name or "").strip())
    if not wrappers:
        return ()
    indices_by_key: Dict[str, List[int]] = defaultdict(list)
    for index, name in enumerate(wrappers):
        key = _source_owned_sidecar_name_key(name)
        if key:
            indices_by_key[key].append(index)

    aligned: List[str] = []
    used_indices: set[int] = set()
    for target_index, submesh in enumerate(submeshes):
        fallback_names = [
            str(getattr(submesh, "name", "") or "").strip(),
            str(getattr(submesh, "material", "") or "").strip(),
        ]
        fallbacks = [name for index, name in enumerate(fallback_names) if name and name not in fallback_names[:index]]
        chosen = ""
        for fallback in fallbacks:
            key = _source_owned_sidecar_name_key(fallback)
            for wrapper_index in indices_by_key.get(key, ()):
                if wrapper_index in used_indices:
                    continue
                chosen = wrappers[wrapper_index]
                used_indices.add(wrapper_index)
                break
            if chosen:
                break
        if not chosen and target_index < len(wrappers):
            candidate = wrappers[target_index]
            fallback = fallbacks[0] if fallbacks else candidate
            candidate_key = _source_owned_sidecar_name_key(candidate)
            fallback_key = _source_owned_sidecar_name_key(fallback)
            if not (
                candidate_key != fallback_key
                and fallback
                and _source_owned_sidecar_name_is_helper_row(candidate)
            ):
                chosen = candidate
                used_indices.add(target_index)
        if not chosen:
            chosen = fallbacks[0] if fallbacks else (wrappers[target_index] if target_index < len(wrappers) else "")
        if chosen:
            aligned.append(chosen)
    return tuple(aligned)


def _source_owned_target_names_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
    original_mesh: Optional[ParsedMesh] = None,
) -> Tuple[str, ...]:
    """Return game-runtime submesh wrapper names aligned to original PAC draw sections."""
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "")
        if "_subMeshResources" not in text or "SkinnedMeshMaterialWrapper" not in text:
            continue
        vector_match = re.search(
            r'<Vector\b[^>]*\bName="_subMeshResources"[^>]*>(?P<body>.*?)</Vector>\s*</SkinnedMeshProperty>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        body = vector_match.group("body") if vector_match is not None else text
        names: List[str] = []
        for match in re.finditer(
            r'<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            attrs = match.group("attrs") or ""
            name_match = re.search(
                r'\b(?:_subMeshName|subMeshName|SubMeshName)="([^"]+)"',
                attrs,
                flags=re.IGNORECASE,
            )
            name = str(name_match.group(1) if name_match else "").strip()
            if name:
                names.append(name)
        if names:
            if original_mesh is not None:
                return _align_source_owned_target_names_to_mesh(names, original_mesh)
            return tuple(names)
    return ()


def _mesh_import_normalize_runtime_stem_candidate(value: str) -> str:
    candidate = str(value or "").replace("\\", "/").strip().strip('"').strip("'").lower()
    if not candidate:
        return ""
    candidate = PurePosixPath(candidate).name
    for suffix in _MESH_IMPORT_TEXTURE_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            break
    for suffix in _MESH_IMPORT_SHORT_TEXTURE_SUFFIXES:
        if candidate.endswith(suffix) and len(candidate) > len(suffix):
            candidate = candidate[: -len(suffix)]
            break
    candidate = re.sub(r"[^a-z0-9_]+", "_", candidate).strip("_")
    if not candidate.startswith("cd_") or len(candidate) < 8:
        return ""
    return candidate


def _mesh_import_runtime_stem_candidates_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
) -> Tuple[str, ...]:
    stems: List[str] = []
    seen: set[str] = set()
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "").replace("\\", "/")
        if not text:
            continue
        for pattern in (
            r'\b(?:_subMeshName|subMeshName|SubMeshName)="([^"]+)"',
            r'\b_path="([^"]+)"',
            r'\bvalue="([^"]+)"',
        ):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                stem = _mesh_import_normalize_runtime_stem_candidate(match.group(1))
                if stem and stem not in seen:
                    stems.append(stem)
                    seen.add(stem)
    return tuple(stems)


def _mesh_import_runtime_mesh_paths_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
) -> Tuple[str, ...]:
    paths: List[str] = []
    seen: set[str] = set()
    extension_pattern = "|".join(re.escape(ext.lstrip(".")) for ext in sorted(_MESH_IMPORT_RUNTIME_MESH_EXTENSIONS))
    path_pattern = re.compile(
        rf"character/model/[^\s\"'<>]+?\.(?:{extension_pattern})\b",
        flags=re.IGNORECASE,
    )
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "")
        if not text:
            continue
        for match in path_pattern.finditer(text):
            path = match.group(0).replace("\\", "/").strip().strip('"').strip("'")
            key = path.lower()
            if key and key not in seen:
                paths.append(path)
                seen.add(key)
    return tuple(paths)


def _mesh_import_runtime_stem_candidates_from_mesh(mesh: ParsedMesh) -> Tuple[str, ...]:
    stems: List[str] = []
    seen: set[str] = set()
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for raw_value in (
            getattr(submesh, "name", ""),
            getattr(submesh, "material", ""),
            getattr(submesh, "texture", ""),
        ):
            stem = _mesh_import_normalize_runtime_stem_candidate(str(raw_value or ""))
            if stem and stem not in seen:
                stems.append(stem)
                seen.add(stem)
    return tuple(stems)


def _mesh_import_runtime_sibling_mesh_candidates(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()
    source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
    source_extension = str(getattr(entry, "extension", "") or "").strip().lower()
    if source_extension not in _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS:
        return ()
    # Submesh names and DDS stems often describe shared material families, not
    # runtime mesh identity. Only explicit model mesh paths from sidecars are
    # strong enough to warn that the selected PAC may not be the runtime target.
    runtime_paths = _mesh_import_runtime_mesh_paths_from_sidecars(original_sidecars)
    if not runtime_paths:
        return ()
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()
    for runtime_path in runtime_paths:
        runtime_key = str(runtime_path or "").replace("\\", "/").strip().lower()
        basename = PurePosixPath(runtime_key).name
        if not basename:
            continue
        basename_candidates = list(archive_entries_by_basename.get(basename, ()) or ())
        if basename != basename.lower():
            basename_candidates.extend(archive_entries_by_basename.get(basename.lower(), ()) or ())
        for candidate in tuple(basename_candidates):
            candidate_path = str(getattr(candidate, "path", "") or "").replace("\\", "/").strip()
            candidate_key = candidate_path.lower()
            if not candidate_key or candidate_key == source_path or candidate_key in seen_paths:
                continue
            if candidate_key != runtime_key:
                continue
            if str(getattr(candidate, "extension", "") or "").strip().lower() not in _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS:
                continue
            if "character/model/" not in candidate_key:
                continue
            candidates.append(candidate)
            seen_paths.add(candidate_key)

    def _score(candidate: ArchiveEntry) -> Tuple[int, int, str]:
        path = str(getattr(candidate, "path", "") or "").replace("\\", "/").lower()
        score = 0
        if "/1_pc/" in path:
            score += 80
        if "/armor/" in path:
            score += 30
        if "/2_mon/" in source_path and "/2_mon/" not in path:
            score += 20
        if "/modelproperty/" not in path and "character/model/" in path:
            score += 5
        return (score, -len(path), path)

    candidates.sort(key=_score, reverse=True)
    return tuple(candidates[:12])


def mesh_import_runtime_sibling_mesh_candidates(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[ArchiveEntry, ...]:
    """Return likely runtime mesh targets for display/preview clone sources."""

    return _mesh_import_runtime_sibling_mesh_candidates(
        entry,
        mesh,
        archive_entries_by_basename,
        original_sidecars,
    )


def _mesh_import_runtime_sibling_warning_lines(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[str, ...]:
    candidates = _mesh_import_runtime_sibling_mesh_candidates(
        entry,
        mesh,
        archive_entries_by_basename,
        original_sidecars,
    )
    if not candidates:
        return ()
    source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
    has_player_candidate = any("/1_pc/" in str(getattr(candidate, "path", "") or "").replace("\\", "/").lower() for candidate in candidates)
    if "/2_mon/" not in source_path and not has_player_candidate:
        return ()
    lines = [
        "Runtime target warning: this selected mesh appears to be a display/monster clone that references player equipment mesh names. "
        "Editing/exporting only this PAC can look correct in preview but leave the equipped in-game model unchanged."
        if "/2_mon/" in source_path and has_player_candidate
        else "Runtime target warning: related runtime mesh candidates with the same material/submesh family were found. "
        "If in-game output does not change, edit/export the runtime mesh path instead of only this preview source.",
        "Likely runtime mesh candidate(s):",
    ]
    for candidate in candidates[:6]:
        lines.append(f"  {candidate.path}")
    if len(candidates) > 6:
        lines.append(f"  ... {len(candidates) - 6:,} more candidate(s)")
    return tuple(lines)


def _decode_text_payload(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
        try:
            return bytes(data or b"").decode(encoding).replace("\ufeff", "")
        except UnicodeError:
            continue
    return bytes(data or b"").decode("utf-8", errors="replace").replace("\ufeff", "")


def _summarize_crimson_companion_supplemental_files(supplemental_files: Sequence[Path]) -> Tuple[str, ...]:
    companion_files = [
        path
        for path in tuple(supplemental_files or ())
        if isinstance(path, Path) and path.suffix.lower() in (MESH_IMPORT_COMPANION_EXTENSIONS | {".pami"})
    ]
    if not companion_files:
        return ()
    try:
        from cdmw.core.crimson_formats import (
            complete_swap_file_policy,
            decode_meshinfo,
            decode_paa_metabin,
            decode_prefab,
            parse_pami_material_instances,
        )
    except Exception:
        return ()
    try:
        from cdmw.rendering.material_channels import parse_crimson_material_definition_text
    except Exception:
        parse_crimson_material_definition_text = None  # type: ignore[assignment]

    lines: List[str] = ["Crimson companion metadata:"]
    for path in companion_files[:12]:
        extension = path.suffix.lower()
        policy = complete_swap_file_policy(extension)
        try:
            data = path.read_bytes()
        except OSError as exc:
            lines.append(f"  {path.name}: unreadable ({exc})")
            continue
        if extension == ".prefab":
            decoded = decode_prefab(data)
            roles = Counter(reference.role for reference in decoded.references)
            role_text = _summarize_compact([f"{role}={count}" for role, count in sorted(roles.items())]) or "no resource refs"
            lines.append(
                f"  {path.name}: prefab refs {role_text}; patchable={decoded.patchable_reference_count}; policy={policy}"
            )
        elif extension == ".meshinfo":
            decoded = decode_meshinfo(data)
            roles = Counter(reference.role for reference in decoded.references)
            role_text = _summarize_compact([f"{role}={count}" for role, count in sorted(roles.items())]) or "no visible refs"
            lines.append(f"  {path.name}: meshinfo refs {role_text}; policy={decoded.material_policy}")
        elif extension == ".paa_metabin":
            decoded = decode_paa_metabin(data)
            declared = decoded.declared_type or "AnimationMetaData"
            lines.append(f"  {path.name}: {declared}; policy={decoded.material_policy}")
        elif extension == ".pami":
            instances = parse_pami_material_instances(_decode_text_payload(data))
            texture_count = sum(len(instance.texture_parameters) for instance in instances)
            lines.append(
                f"  {path.name}: pami material instances={len(instances)}, texture params={texture_count}; policy={policy}"
            )
        elif extension == ".material" and parse_crimson_material_definition_text is not None:
            try:
                definition = parse_crimson_material_definition_text(_decode_text_payload(data), source_path=str(path))
                lines.append(
                    f"  {path.name}: material technique={definition.technique or '-'}, params={len(definition.parameters)}, groups={len(definition.parameter_groups)}; policy={policy}"
                )
            except Exception as exc:
                lines.append(f"  {path.name}: material definition parse failed ({exc}); policy={policy}")
        else:
            lines.append(f"  {path.name}: policy={policy}")
    if len(companion_files) > 12:
        lines.append(f"  ... {len(companion_files) - 12:,} more companion file(s)")
    return tuple(lines)


def _mesh_texture_original_source_path(texture_entry: object) -> Path:
    from cdmw.core.archive import ensure_archive_preview_source

    if not isinstance(texture_entry, ArchiveEntry):
        raise ValueError("Original texture archive entry is unavailable.")
    source_path, _note = ensure_archive_preview_source(texture_entry)
    return source_path


def _mesh_texture_original_bytes(texture_entry: object) -> bytes:
    from cdmw.core.archive import read_archive_entry_data

    if not isinstance(texture_entry, ArchiveEntry):
        raise ValueError("Original texture archive entry is unavailable.")
    data, _decompressed, _note = read_archive_entry_data(texture_entry)
    return data


def _texture_replacement_payloads_to_specs(
    payloads: Sequence[TextureReplacementPayload],
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    specs: List[MeshImportSupplementalFileSpec] = []
    for payload in payloads:
        target_entry = _find_first_archive_entry_by_virtual_path(
            payload.target_path,
            archive_entries_by_normalized_path,
        )
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=payload.source_path,
                target_path=payload.target_path,
                kind=payload.kind,
                target_entry=target_entry,
                used_for_preview=True,
                payload_data=payload.payload_data,
                note=payload.note,
            )
        )
    return tuple(specs)


def _generated_texture_preview_file(payload: TextureReplacementPayload) -> Path:
    digest = hashlib.sha1(payload.payload_data).hexdigest()[:16]
    target_name = PurePosixPath(str(payload.target_path or "").replace("\\", "/")).name
    if not target_name:
        target_name = payload.source_path.with_suffix(".dds").name
    if not target_name.lower().endswith(".dds"):
        target_name = f"{Path(target_name).stem}.dds"
    output_dir = app_temp_cache_path("static_mesh_texture_previews")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(target_name).stem}_{digest}.dds"
    if not output_path.is_file():
        output_path.write_bytes(payload.payload_data)
        request_app_temp_cache_prune()
    return output_path


def _apply_generated_static_texture_previews(
    preview_model: ModelPreviewData,
    *,
    generated_payloads: Sequence[TextureReplacementPayload],
    texture_replacement_report: object,
    texconv_path: Optional[Path],
) -> int:
    if not getattr(preview_model, "meshes", None):
        return 0
    texture_payloads_by_target = {
        str(payload.target_path or "").replace("\\", "/").strip().lower(): payload
        for payload in generated_payloads
        if payload.kind == "texture_generated" and payload.payload_data
    }
    if not texture_payloads_by_target:
        return 0

    from cdmw.core.archive import _resolve_model_texture_semantic_details
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    preview_cache: Dict[str, str] = {}

    def _preview_path_for_payload(payload: TextureReplacementPayload) -> str:
        dds_path = _generated_texture_preview_file(payload)
        cache_key = dds_path.as_posix().lower()
        cached = preview_cache.get(cache_key, "")
        if cached:
            return cached
        dds_info = None
        try:
            dds_info = parse_dds(dds_path)
        except Exception:
            dds_info = None
        preview_path = ensure_dds_display_preview_png(resolved_texconv_path, dds_path, dds_info=dds_info)
        preview_cache[cache_key] = preview_path
        return preview_path

    def _tokens(value: str) -> set[str]:
        stop_words = {"cd", "phm", "pc", "texture", "textures", "dds", "png", "normal", "base", "color", "roughness", "metallic"}
        tokens: set[str] = set()
        for raw_token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split():
            token = re.sub(r"\d+$", "", raw_token.strip())
            if len(token) > 1 and token not in stop_words and not token.isdigit():
                tokens.add(token)
        return tokens

    def _mesh_match_score(mesh: ModelPreviewMesh, material_name: str, texture_path: str) -> float:
        mesh_material = str(getattr(mesh, "material_name", "") or "")
        mesh_name = str(getattr(mesh, "name", "") or "")
        material_key = str(material_name or "").strip().lower()
        mesh_material_key = mesh_material.strip().lower()
        if material_key and mesh_material_key == material_key:
            return 100.0
        query_tokens = _tokens(f"{material_name} {texture_path}")
        mesh_tokens = _tokens(f"{mesh_material} {mesh_name}")
        if not query_tokens or not mesh_tokens:
            return 0.0
        overlap = query_tokens & mesh_tokens
        score = float(len(overlap) * 12)
        for token in overlap:
            score += min(6.0, len(token) * 0.75)
        for query_token in query_tokens:
            for mesh_token in mesh_tokens:
                if len(query_token) >= 4 and len(mesh_token) >= 4 and (query_token in mesh_token or mesh_token in query_token):
                    score += 3.0
        return score

    def _candidate_meshes(material_name: str, texture_path: str) -> List[ModelPreviewMesh]:
        scored = [
            (_mesh_match_score(mesh, material_name, texture_path), mesh)
            for mesh in preview_model.meshes
        ]
        best_score = max((score for score, _mesh in scored), default=0.0)
        if best_score > 0.0:
            return [mesh for score, mesh in scored if score == best_score]
        return list(preview_model.meshes) if len(preview_model.meshes) == 1 else []

    assigned_count = 0
    slot_mappings = list(getattr(texture_replacement_report, "slot_mappings", ()) or ())
    source_material_by_target: Dict[str, str] = {}
    base_targets: set[str] = set()
    for mapping in slot_mappings:
        target_path = str(getattr(mapping, "output_texture_path", "") or "").replace("\\", "/").strip().lower()
        payload = texture_payloads_by_target.get(target_path)
        if payload is None:
            continue
        target_material_name = str(getattr(mapping, "target_material_name", "") or "")
        source_material_name = str(getattr(mapping, "source_material_name", "") or "")
        if target_material_name and source_material_name:
            source_material_by_target.setdefault(target_material_name.strip().lower(), source_material_name)
        try:
            preview_path = _preview_path_for_payload(payload)
        except Exception:
            continue
        slot_kind = str(getattr(mapping, "slot_kind", "") or "").strip().lower()
        if slot_kind == "base" and target_material_name:
            base_targets.add(target_material_name.strip().lower())
        source_name = getattr(getattr(mapping, "source_path", None), "name", "") or PurePosixPath(payload.target_path).name
        for mesh in _candidate_meshes(
            target_material_name,
            str(getattr(mapping, "target_texture_path", "") or ""),
        ):
            if slot_kind == "base":
                mesh.preview_texture_path = preview_path
                mesh.texture_name = source_name
                mesh.preview_texture_flip_vertical = False
                assigned_count += 1
            elif slot_kind == "normal":
                mesh.preview_normal_texture_path = preview_path
                mesh.preview_normal_texture_name = source_name
                mesh.preview_normal_texture_strength = 0.75
                assigned_count += 1
            elif slot_kind == "height":
                mesh.preview_height_texture_path = preview_path
                mesh.preview_height_texture_name = source_name
                assigned_count += 1
            elif slot_kind in {"material", "material_mask", "detail_mask"}:
                semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(source_name)
                mesh.preview_material_texture_path = preview_path
                mesh.preview_material_texture_name = source_name
                mesh.preview_material_texture_type = semantic_type
                mesh.preview_material_texture_subtype = semantic_subtype
                mesh.preview_material_texture_packed_channels = tuple(packed_channels)
                assigned_count += 1

    # PAC-driven sidecar generation binds by the rebuilt draw-section names.
    # If the first pass did not find a fuzzy match for a renamed/merged section,
    # assign by token overlap without requiring a texture-path match so the
    # preview follows the same material routing that will be packaged.
    for mapping in slot_mappings:
        target_material_name = str(getattr(mapping, "target_material_name", "") or "")
        target_path = str(getattr(mapping, "output_texture_path", "") or "").replace("\\", "/").strip().lower()
        payload = texture_payloads_by_target.get(target_path)
        if payload is None:
            continue
        try:
            preview_path = _preview_path_for_payload(payload)
        except Exception:
            continue
        slot_kind = str(getattr(mapping, "slot_kind", "") or "").strip().lower()
        source_name = getattr(getattr(mapping, "source_path", None), "name", "") or PurePosixPath(payload.target_path).name
        target_tokens = _tokens(target_material_name)
        for mesh in preview_model.meshes:
            mesh_tokens = _tokens(f"{getattr(mesh, 'material_name', '')} {getattr(mesh, 'name', '')}")
            if target_tokens and mesh_tokens and not (target_tokens & mesh_tokens):
                continue
            if slot_kind == "base" and not str(getattr(mesh, "preview_texture_path", "") or "").strip():
                mesh.preview_texture_path = preview_path
                mesh.texture_name = source_name
                mesh.preview_texture_flip_vertical = False
                assigned_count += 1
            elif slot_kind == "normal" and not str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
                mesh.preview_normal_texture_path = preview_path
                mesh.preview_normal_texture_name = source_name
                mesh.preview_normal_texture_strength = 0.75
                assigned_count += 1
            elif slot_kind == "height" and not str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
                mesh.preview_height_texture_path = preview_path
                mesh.preview_height_texture_name = source_name
                assigned_count += 1
            elif slot_kind in {"material", "material_mask", "detail_mask"} and not str(getattr(mesh, "preview_material_texture_path", "") or "").strip():
                semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(source_name)
                mesh.preview_material_texture_path = preview_path
                mesh.preview_material_texture_name = source_name
                mesh.preview_material_texture_type = semantic_type
                mesh.preview_material_texture_subtype = semantic_subtype
                mesh.preview_material_texture_packed_channels = tuple(packed_channels)
                assigned_count += 1
    texture_sets_by_source = {
        str(getattr(texture_set, "material_name", "") or "").strip().lower(): texture_set
        for texture_set in (getattr(texture_replacement_report, "texture_sets", ()) or ())
    }
    for target_material_key, source_material_name in source_material_by_target.items():
        if target_material_key in base_targets:
            continue
        texture_set = texture_sets_by_source.get(str(source_material_name or "").strip().lower())
        base_slot = getattr(texture_set, "slots", {}).get("base") if texture_set is not None else None
        source_path = getattr(base_slot, "source_path", None)
        if not isinstance(source_path, Path) or not source_path.is_file():
            continue
        for mesh in _candidate_meshes(target_material_key, ""):
            mesh.preview_texture_path = source_path.as_posix()
            mesh.texture_name = source_path.name
            mesh.preview_texture_flip_vertical = False
            assigned_count += 1
    return assigned_count


def build_mesh_import_preview(
    entry: ArchiveEntry,
    obj_path: Path,
    *,
    import_mode: str = "roundtrip",
    static_replacement_options: Optional[StaticMeshReplacementOptions] = None,
    scene_import_result: Optional[SceneImportResult] = None,
    source_display_label: str = "",
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    texconv_path: Optional[Path] = None,
    texture_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    visible_texture_mode: str = "mesh_base_first",
    supplemental_files: Sequence[Path] = (),
) -> MeshImportPreviewResult:
    from cdmw.core.archive import (
        _attach_model_sidecar_texture_preview_paths,
        _attach_model_support_texture_preview_paths,
        _attach_model_texture_preview_paths,
        _extract_archive_model_sidecar_texture_references,
        _normalize_model_visible_texture_mode,
        build_archive_model_texture_references,
        read_archive_entry_data,
    )

    if scene_import_result is None:
        scene_import_result = import_scene_mesh_with_report(obj_path)
    imported_mesh = scene_import_result.mesh
    imported_mesh.path = entry.path
    imported_mesh.format = entry.extension.lstrip(".").lower()
    manifest_payload = (
        _load_obj_roundtrip_sidecar(str(obj_path))
        if obj_path.suffix.lower() == ".obj" and obj_path.expanduser().is_file()
        else None
    )
    original_baseline = read_archive_entry_baseline_data(entry, read_entry_data=read_archive_entry_data)
    original_data = original_baseline.data
    original_mesh = parse_mesh(original_data, entry.path)
    original_sidecars_for_static: Tuple[Tuple[ArchiveEntry, str], ...] = ()
    if texture_entries_by_basename is not None:
        original_sidecars_for_static = _collect_original_mesh_sidecar_texts(entry, texture_entries_by_basename)
    normalized_import_mode = str(import_mode or "roundtrip").strip().lower()
    static_mappings = []
    enable_missing_base_color_parameters = False
    effective_static_source_mesh = imported_mesh
    if normalized_import_mode in {"static", "static_replacement", "static-mesh-replacement"}:
        base_static_options = static_replacement_options or StaticMeshReplacementOptions()
        if bool(getattr(base_static_options, "full_import_model_replacement", False)) and not original_sidecars_for_static:
            raise ValueError(
                "Full Import Model Replacement requires a target material sidecar (.pac_xml/.pami) so "
                "the imported model can own texture/material bindings instead of inheriting old target slots."
            )
        effective_static_source_mesh = effective_static_replacement_source_mesh(
            original_mesh,
            imported_mesh,
            base_static_options,
        )
        enable_missing_base_color_parameters = bool(
            getattr(base_static_options, "enable_missing_base_color_parameters", False)
        )
        static_mappings = base_static_options.submesh_mappings or suggest_static_submesh_mappings(
            original_mesh,
            effective_static_source_mesh,
        )
        if not base_static_options.submesh_mappings:
            base_static_options = dataclasses.replace(base_static_options, submesh_mappings=static_mappings)
        if bool(getattr(base_static_options, "complete_external_swap", False)):
            source_owned_target_names = _source_owned_target_names_from_sidecars(
                original_sidecars_for_static,
                original_mesh=original_mesh,
            )
            if source_owned_target_names:
                base_static_options = dataclasses.replace(
                    base_static_options,
                    source_owned_target_names=list(source_owned_target_names),
                )
        rebuilt_data, static_report = build_static_mesh_replacement(
            original_data,
            original_mesh,
            imported_mesh,
            base_static_options,
        )
        normalized_import_mode = "static_replacement"
    else:
        if obj_path.suffix.lower() != ".obj":
            raise ValueError("Round-trip edit import only supports OBJ. Use Mesh Replacement for DAE, GLB, or glTF imports.")
        static_report = None
        normalized_import_mode = "roundtrip"
        rebuilt_data = build_mesh(imported_mesh, original_data)
    parsed_mesh = parse_mesh(rebuilt_data, entry.path)
    restored_texture_identity_count = _restore_rebuilt_mesh_texture_identity(imported_mesh, parsed_mesh)
    preview_model = parsed_mesh_to_preview_model(parsed_mesh)

    summary_lines = [
        f"Preview rebuilt mesh for {entry.path}",
        f"Import mode: {'Mesh replacement' if normalized_import_mode == 'static_replacement' else 'Round-trip edit'}",
        f"Vertices: {parsed_mesh.total_vertices:,}",
        f"Faces: {parsed_mesh.total_faces:,}",
        f"Submeshes: {len(parsed_mesh.submeshes):,}",
        f"Rebuilt size: {len(rebuilt_data):,} bytes",
    ]
    if source_display_label.strip():
        summary_lines.append(f"Replacement source: {source_display_label.strip()}")
    if original_baseline.message:
        summary_lines.append(f"Original mesh donor: {original_baseline.message}")
    if scene_import_result.diagnostics:
        summary_lines.append("Scene import notes:")
        summary_lines.extend(f"  {line}" for line in scene_import_result.diagnostics)
    if static_report is not None:
        summary_lines.append(
            "Static replacement analysis: "
            f"original {static_report.original_submesh_count} submesh(es), "
            f"replacement {static_report.replacement_submesh_count} source submesh(es)."
        )
        if static_report.mapping_summary:
            summary_lines.append("Static replacement mapping:")
            summary_lines.extend(f"  {line}" for line in static_report.mapping_summary)
        if static_report.warnings:
            summary_lines.append("Static replacement warnings:")
            summary_lines.extend(f"  {line}" for line in static_report.warnings)
        if static_report.alignment_summary:
            summary_lines.append("Static replacement alignment:")
            summary_lines.extend(f"  {line}" for line in static_report.alignment_summary)
    if restored_texture_identity_count > 0:
        summary_lines.append(
            f"Restored {restored_texture_identity_count:,} imported submesh texture identifier(s) onto rebuilt preview metadata."
        )
    resolved_supplemental_files = tuple(
        path.expanduser().resolve()
        for path in supplemental_files
        if isinstance(path, Path) and path.expanduser().resolve().is_file()
    )
    if normalized_import_mode == "static_replacement":
        auto_scene_supplemental_files = tuple(
            path
            for path in tuple(scene_import_result.discovered_texture_files)
            + tuple(scene_import_result.extracted_embedded_files)
            + tuple(getattr(scene_import_result, "discovered_supplemental_files", ()) or ())
            + (
                tuple(discover_scene_texture_files(obj_path, imported_mesh))
                if obj_path.expanduser().is_file()
                else ()
            )
            if path.is_file()
        )
        if auto_scene_supplemental_files:
            seen_supplemental = {str(path).lower() for path in resolved_supplemental_files}
            appended = [path for path in auto_scene_supplemental_files if str(path).lower() not in seen_supplemental]
            if appended:
                resolved_supplemental_files = tuple(resolved_supplemental_files) + tuple(appended)
                summary_lines.append(
                    f"Auto-discovered {len(appended):,} supplemental texture/sidecar file(s) next to the imported mesh."
                )
    if resolved_supplemental_files:
        summary_lines.append(f"Selected supplemental files: {len(resolved_supplemental_files):,}")
        summary_lines.extend(_summarize_crimson_companion_supplemental_files(resolved_supplemental_files))
    sidecar_texture_references: Tuple[object, ...] = ()
    sidecar_reference_paths: Tuple[str, ...] = ()
    sidecar_texts_by_normalized_path: Dict[str, Tuple[str, ...]] = {}
    sidecar_texts_by_basename: Dict[str, Tuple[str, ...]] = {}
    original_archive_sidecar_texture_references: Tuple[object, ...] = ()
    original_archive_sidecar_reference_paths: Tuple[str, ...] = ()
    selected_sidecar_texture_references: Tuple[object, ...] = ()
    selected_sidecar_reference_paths: Tuple[str, ...] = ()
    selected_sidecar_texts_by_normalized_path: Dict[str, Tuple[str, ...]] = {}
    selected_sidecar_texts_by_basename: Dict[str, Tuple[str, ...]] = {}
    normalized_visible_texture_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    if resolved_supplemental_files:
        (
            selected_sidecar_texture_references,
            selected_sidecar_reference_paths,
            selected_sidecar_texts_by_normalized_path,
            selected_sidecar_texts_by_basename,
        ) = _build_selected_sidecar_texture_bindings(resolved_supplemental_files)
        if selected_sidecar_texture_references:
            summary_lines.append(
                f"Using {len(selected_sidecar_texture_references):,} texture binding(s) from selected local sidecar file(s): {', '.join(selected_sidecar_reference_paths[:3])}"
                + (" ..." if len(selected_sidecar_reference_paths) > 3 else "")
            )
    if texture_entries_by_basename is not None:
        (
            original_archive_sidecar_texture_references,
            original_archive_sidecar_reference_paths,
            sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename,
        ) = _extract_archive_model_sidecar_texture_references(
            entry,
            archive_entries_by_basename=(
                dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
            ),
        )
        if original_archive_sidecar_texture_references and not selected_sidecar_texture_references:
            sidecar_suffix = (
                f" from {', '.join(original_archive_sidecar_reference_paths[:2])}"
                if original_archive_sidecar_reference_paths
                else ""
            )
            if len(original_archive_sidecar_reference_paths) > 2:
                sidecar_suffix += " ..."
            summary_lines.append(
                f"Companion material sidecar data contributed {len(original_archive_sidecar_texture_references):,} texture binding(s){sidecar_suffix}."
            )
            summary_lines.append(
                "Loose mesh mods may still need the matching companion .xml sidecar when custom material or texture remaps are involved."
            )
    if original_archive_sidecar_texture_references:
        sidecar_texture_references = original_archive_sidecar_texture_references
        sidecar_reference_paths = original_archive_sidecar_reference_paths
    if selected_sidecar_texture_references:
        sidecar_texture_references = selected_sidecar_texture_references
        sidecar_reference_paths = selected_sidecar_reference_paths
        sidecar_texts_by_normalized_path = selected_sidecar_texts_by_normalized_path
        sidecar_texts_by_basename = selected_sidecar_texts_by_basename
    summary_lines.extend(
        _mesh_import_runtime_sibling_warning_lines(
            entry,
            parsed_mesh,
            texture_entries_by_basename,
            original_sidecars_for_static,
        )
    )
    texture_references: Tuple[ArchiveModelTextureReference, ...] = ()
    if texconv_path is not None:
        if sidecar_texture_references:
            summary_lines.extend(
                _attach_model_sidecar_texture_preview_paths(
                    texconv_path,
                    entry,
                    preview_model,
                    parsed_mesh=parsed_mesh,
                    sidecar_texture_bindings=sidecar_texture_references,
                    visible_texture_mode=normalized_visible_texture_mode,
                    texture_entries_by_normalized_path=(
                        dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
                    ),
                    texture_entries_by_basename=(
                        dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
                    ),
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                )
            )
        summary_lines.extend(
            _attach_model_texture_preview_paths(
                texconv_path,
                entry,
                preview_model,
                texture_entries_by_normalized_path=(
                    dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
                ),
                texture_entries_by_basename=(
                    dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
                ),
                sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=sidecar_texts_by_basename,
            )
        )
        if sidecar_texture_references and normalized_visible_texture_mode == "mesh_base_first":
            summary_lines.extend(
                _attach_model_sidecar_texture_preview_paths(
                    texconv_path,
                    entry,
                    preview_model,
                    parsed_mesh=parsed_mesh,
                    sidecar_texture_bindings=sidecar_texture_references,
                    visible_texture_mode="layer_aware_visible",
                    texture_entries_by_normalized_path=(
                        dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
                    ),
                    texture_entries_by_basename=(
                        dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
                    ),
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                    fallback_only=True,
                )
            )
            summary_lines.extend(
                _attach_model_texture_preview_paths(
                    texconv_path,
                    entry,
                    preview_model,
                    texture_entries_by_normalized_path=(
                        dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
                    ),
                    texture_entries_by_basename=(
                        dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
                    ),
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                    override_existing_base=True,
                    prefer_material_name_for_base=True,
                )
            )
        summary_lines.extend(
            _attach_model_support_texture_preview_paths(
                texconv_path,
                entry,
                preview_model,
                parsed_mesh=parsed_mesh,
                sidecar_texture_bindings=sidecar_texture_references,
                texture_entries_by_normalized_path=(
                    dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
                ),
                texture_entries_by_basename=(
                    dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
                ),
                sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=sidecar_texts_by_basename,
            )
        )
        if resolved_supplemental_files:
            supplemental_dds_by_normalized_path, supplemental_dds_by_basename = _build_mesh_import_local_dds_lookup(
                resolved_supplemental_files
            )
            if selected_sidecar_texture_references:
                summary_lines.extend(
                    _apply_mesh_import_local_sidecar_texture_overrides(
                        preview_model,
                        parsed_mesh,
                        selected_sidecar_texture_references,
                        supplemental_dds_by_normalized_path,
                        supplemental_dds_by_basename,
                        texconv_path=texconv_path,
                    )
                )
                summary_lines.extend(
                    _apply_mesh_import_local_support_texture_overrides(
                        preview_model,
                        parsed_mesh,
                        selected_sidecar_texture_references,
                        supplemental_dds_by_normalized_path,
                        supplemental_dds_by_basename,
                        texconv_path=texconv_path,
                    )
                )
            summary_lines.extend(
                _apply_mesh_import_local_texture_overrides(
                    preview_model,
                    supplemental_dds_by_normalized_path,
                    supplemental_dds_by_basename,
                    texconv_path=texconv_path,
                )
            )
    texture_references = tuple(
        build_archive_model_texture_references(
            entry,
            preview_model,
            parsed_mesh=parsed_mesh,
            sidecar_texture_references=sidecar_texture_references,
            texture_entries_by_normalized_path=(
                dict(texture_entries_by_normalized_path) if texture_entries_by_normalized_path is not None else None
            ),
            texture_entries_by_basename=(
                dict(texture_entries_by_basename) if texture_entries_by_basename is not None else None
            ),
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
    )
    supplemental_file_specs = _build_mesh_import_supplemental_file_specs(
        entry,
        resolved_supplemental_files,
        texture_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=texture_entries_by_basename,
    )
    texture_slot_overrides = tuple(getattr(static_replacement_options, "texture_slot_overrides", ()) or ())
    source_material_texture_overrides = tuple(
        getattr(static_replacement_options, "source_material_texture_overrides", ()) or ()
    )
    donor_material_plans = tuple(getattr(static_replacement_options, "donor_material_plans", ()) or ())
    prune_removed_target_texture_parameters = bool(
        getattr(static_replacement_options, "prune_removed_target_texture_parameters", False)
    )
    prune_unmapped_original_texture_parameters = bool(
        getattr(static_replacement_options, "prune_unmapped_original_texture_parameters", False)
    )
    complete_external_material_reset = bool(
        getattr(static_replacement_options, "complete_external_material_reset", False)
    )
    complete_swap_material_profile = str(
        getattr(
            static_replacement_options,
            "complete_swap_material_profile",
            "source_graph_strict" if complete_external_material_reset else "arm_standard",
        )
        or ("source_graph_strict" if complete_external_material_reset else "arm_standard")
    )
    try:
        complete_swap_global_gloss_reduction = max(
            -100.0,
            min(100.0, float(getattr(static_replacement_options, "global_gloss_reduction", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_global_gloss_reduction = 0.0
    try:
        complete_swap_edge_relief_strength = max(
            0.0,
            min(100.0, float(getattr(static_replacement_options, "edge_relief_strength", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_edge_relief_strength = 0.0
    complete_swap_edge_relief_source = str(
        getattr(static_replacement_options, "edge_relief_source", "hybrid") or "hybrid"
    )
    try:
        complete_swap_accent_glow_strength = max(
            0.0,
            min(100.0, float(getattr(static_replacement_options, "accent_glow_strength", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_accent_glow_strength = 0.0
    try:
        complete_swap_auto_brightness_balance = max(
            0.0,
            min(100.0, float(getattr(static_replacement_options, "auto_brightness_balance", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_auto_brightness_balance = 0.0
    try:
        complete_swap_dark_detail_lift = max(
            -100.0,
            min(100.0, float(getattr(static_replacement_options, "dark_detail_lift", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_dark_detail_lift = 0.0
    try:
        complete_swap_tone_contrast = max(
            -100.0,
            min(100.0, float(getattr(static_replacement_options, "tone_contrast", 0.0) or 0.0)),
        )
    except (TypeError, ValueError, OverflowError):
        complete_swap_tone_contrast = 0.0
    material_authority_settings: dict[str, object] = {
        "enabled": bool(complete_external_material_reset),
        "requested_profile": complete_swap_material_profile,
        "resolved_profile": "",
        "global_gloss_reduction": float(complete_swap_global_gloss_reduction),
        "edge_relief_strength": float(complete_swap_edge_relief_strength),
        "edge_relief_source": complete_swap_edge_relief_source,
        "accent_glow_strength": float(complete_swap_accent_glow_strength),
        "auto_brightness_balance": float(complete_swap_auto_brightness_balance),
        "dark_detail_lift": float(complete_swap_dark_detail_lift),
        "tone_contrast": float(complete_swap_tone_contrast),
    }
    if (
        normalized_import_mode == "static_replacement"
        and bool(getattr(static_replacement_options, "neutralize_inherited_material_layers", False))
    ):
        summary_lines.append(
            "Source-color faithful material mode: enabled; generated material sidecars will neutralize inherited tint/grime/detail/color-blend layers on rebuilt draw sections."
        )
    if normalized_import_mode == "static_replacement" and complete_external_material_reset:
        summary_lines.append(
            "Complete external swap material reset: enabled; generated material sidecars will reset inherited target shader response on rebuilt draw sections."
        )
        summary_lines.append(
            f"Complete swap material profile: {complete_swap_material_profile}; source PBR maps/factors will be translated into CD runtime support masks."
        )
        if complete_swap_global_gloss_reduction < 0.0:
            summary_lines.append(
                "Global gloss boost requested: "
                f"{abs(complete_swap_global_gloss_reduction):.0f}%; generated source roughness will be lowered "
                "and compatible shine/scalar response increased."
            )
        elif complete_swap_global_gloss_reduction > 0.0:
            summary_lines.append(
                "Global gloss reduction requested: "
                f"{complete_swap_global_gloss_reduction:.0f}%; CD gloss/smoothness, metallic/spec, and shine response will be reduced."
            )
        if complete_swap_edge_relief_strength > 0.0:
            summary_lines.append(
                "Edge relief requested: "
                f"{complete_swap_edge_relief_strength:.0f}% via {complete_swap_edge_relief_source.replace('_', ' ')} support."
            )
        if complete_swap_accent_glow_strength > 0.0:
            summary_lines.append(
                "Accent glow requested: "
                f"{complete_swap_accent_glow_strength:.0f}%; accent/emissive source parts will receive emissive shader parameters."
            )
        if complete_swap_dark_detail_lift > 0.0:
            summary_lines.append(
                "Source brightness requested: "
                f"{complete_swap_dark_detail_lift:.0f}%; source base DDS shadows and midtones will be lifted."
            )
        elif complete_swap_dark_detail_lift < 0.0:
            summary_lines.append(
                "Source brightness requested: "
                f"{complete_swap_dark_detail_lift:.0f}%; source base DDS color will be dimmed before export."
            )
        if complete_swap_auto_brightness_balance > 0.0:
            summary_lines.append(
                "Auto brightness balance requested: "
                f"{complete_swap_auto_brightness_balance:.0f}%; source base DDS exposure will be nudged toward a stable midrange."
            )
        if abs(complete_swap_tone_contrast) > 0.0:
            summary_lines.append(
                "Tone contrast requested: "
                f"{complete_swap_tone_contrast:+.0f}%; generated source base DDS tone curve will be adjusted."
            )
    if (
        normalized_import_mode == "static_replacement"
        and (
            resolved_supplemental_files
            or texture_slot_overrides
            or source_material_texture_overrides
            or donor_material_plans
            or prune_removed_target_texture_parameters
            or prune_unmapped_original_texture_parameters
        )
    ):
        original_sidecars = original_sidecars_for_static or _collect_original_mesh_sidecar_texts(entry, texture_entries_by_basename)
        texture_source_files = tuple(
            path for path in resolved_supplemental_files if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
        )
        if (
            texture_source_files
            or texture_slot_overrides
            or source_material_texture_overrides
            or donor_material_plans
            or prune_removed_target_texture_parameters
            or prune_unmapped_original_texture_parameters
        ):
            try:
                generated_payloads, texture_replacement_report = build_texture_replacement_payloads(
                    obj_mesh=effective_static_source_mesh,
                    rebuilt_mesh=parsed_mesh,
                    texture_files=texture_source_files,
                    original_texture_refs=texture_references,
                    original_sidecars=original_sidecars,
                    submesh_mappings=static_mappings,
                    texconv_path=texconv_path,
                    read_original_texture_bytes=_mesh_texture_original_bytes,
                    original_texture_source_path=_mesh_texture_original_source_path,
                    enable_missing_base_color_parameters=enable_missing_base_color_parameters,
                    texture_slot_overrides=texture_slot_overrides,
                    source_material_texture_overrides=source_material_texture_overrides,
                    source_part_adjustments=tuple(
                        getattr(static_replacement_options, "source_part_adjustments", ()) or ()
                    ),
                    donor_material_plans=donor_material_plans,
                    texture_output_size_mode=str(
                        getattr(static_replacement_options, "texture_output_size_mode", "source") or "source"
                    ),
                    pac_driven_sidecar=bool(
                        getattr(static_replacement_options, "rebuild_material_sidecar", True)
                    ),
                    neutralize_inherited_material_layers=bool(
                        getattr(static_replacement_options, "neutralize_inherited_material_layers", False)
                    ),
                    complete_external_material_reset=complete_external_material_reset,
                    complete_swap_material_profile=complete_swap_material_profile,
                    complete_swap_global_gloss_reduction=complete_swap_global_gloss_reduction,
                    complete_swap_edge_relief_strength=complete_swap_edge_relief_strength,
                    complete_swap_edge_relief_source=complete_swap_edge_relief_source,
                    complete_swap_accent_glow_strength=complete_swap_accent_glow_strength,
                    complete_swap_auto_brightness_balance=complete_swap_auto_brightness_balance,
                    complete_swap_dark_detail_lift=complete_swap_dark_detail_lift,
                    complete_swap_tone_contrast=complete_swap_tone_contrast,
                    removed_target_material_names=tuple(
                        str(getattr(original_mesh.submeshes[int(index)], "material", "") or getattr(original_mesh.submeshes[int(index)], "name", "") or f"target {int(index)}")
                        for index in tuple(getattr(static_replacement_options, "removed_target_submesh_indices", ()) or ())
                        if str(index).strip().lstrip("-").isdigit()
                        and 0 <= int(index) < len(getattr(original_mesh, "submeshes", ()) or ())
                    ),
                    prune_removed_target_texture_parameters=prune_removed_target_texture_parameters,
                    prune_unmapped_original_texture_parameters=prune_unmapped_original_texture_parameters,
                    output_draw_sections=tuple(getattr(static_report, "output_draw_sections", ()) or ()),
                    pac_xml_corpus_root=str(getattr(static_replacement_options, "pac_xml_corpus_root", "") or ""),
                    pac_xml_profile_cache_path=str(getattr(static_replacement_options, "pac_xml_profile_cache_path", "") or ""),
                )
            except Exception as exc:
                generated_payloads = []
                texture_replacement_report = None
                summary_lines.append(f"Static texture replacement failed: {exc}")
            if texture_replacement_report is not None:
                material_profile_name = str(getattr(texture_replacement_report, "material_profile_name", "") or "").strip()
                if material_profile_name:
                    material_authority_settings["resolved_profile"] = material_profile_name
                probe_variants = tuple(getattr(texture_replacement_report, "material_probe_variants", ()) or ())
                if material_profile_name:
                    summary_lines.append(f"Complete swap material profile active: {material_profile_name}")
                    if probe_variants:
                        summary_lines.append(
                            "Complete swap calibration profiles available: "
                            + ", ".join(str(getattr(variant, "material_profile_name", "") or "") for variant in probe_variants[:5])
                        )
                material_routes = tuple(getattr(texture_replacement_report, "material_routes", ()) or ())
                if material_routes:
                    summary_lines.append("Static source material routing:")
                    for route in material_routes[:16]:
                        roles = ", ".join(tuple(getattr(route, "detected_roles", ()) or ())) or "-"
                        source_material = str(getattr(route, "source_material_name", "") or "-")
                        summary_lines.append(
                            "  "
                            f"{getattr(route, 'target_material_name', '')} <- {source_material} "
                            f"[{getattr(route, 'status', 'Unknown')}; {roles}]"
                        )
                    if len(material_routes) > 16:
                        summary_lines.append(f"  ... {len(material_routes) - 16:,} more routing row(s)")
                if texture_replacement_report.slot_mappings:
                    summary_lines.append("Static texture replacement mapping:")
                    summary_lines.extend(
                        "  "
                        f"{mapping.source_material_name} {mapping.slot_kind} "
                        f"({mapping.source_path.name}) -> {mapping.output_texture_path}"
                        for mapping in texture_replacement_report.slot_mappings[:16]
                    )
                    if len(texture_replacement_report.slot_mappings) > 16:
                        summary_lines.append(
                            f"  ... {len(texture_replacement_report.slot_mappings) - 16:,} more texture mapping(s)"
                        )
                if texture_replacement_report.warnings:
                    summary_lines.append("Static texture replacement warnings:")
                    summary_lines.extend(f"  {warning}" for warning in texture_replacement_report.warnings)
                if texture_replacement_report.errors:
                    summary_lines.append("Static texture replacement errors:")
                    summary_lines.extend(f"  {error}" for error in texture_replacement_report.errors)
                if (
                    not texture_replacement_report.slot_mappings
                    and not texture_replacement_report.warnings
                    and not texture_replacement_report.errors
                ):
                    summary_lines.append(
                        "Static texture replacement found no matching original texture bindings for the selected PNG/DDS files."
                    )
            if generated_payloads:
                preview_assignment_count = _apply_generated_static_texture_previews(
                    preview_model,
                    generated_payloads=generated_payloads,
                    texture_replacement_report=texture_replacement_report,
                    texconv_path=texconv_path,
                )
                if preview_assignment_count > 0:
                    summary_lines.append(
                        f"Applied {preview_assignment_count:,} generated static texture preview slot(s) from PNG/DDS replacements."
                    )
                elif texconv_path is None:
                    summary_lines.append(
                        "Generated static texture payloads were not shown in preview because the DirectXTex/native preview backend did not produce usable previews."
                    )
                generated_specs = _texture_replacement_payloads_to_specs(
                    generated_payloads,
                    archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                )
                supplemental_file_specs = tuple(supplemental_file_specs) + generated_specs
                generated_texture_count = sum(1 for payload in generated_payloads if payload.kind == "texture_generated")
                generated_sidecar_count = sum(1 for payload in generated_payloads if payload.kind == "sidecar_generated")
                if (
                    bool(getattr(static_replacement_options, "full_import_model_replacement", False))
                    and generated_sidecar_count <= 0
                ):
                    raise ValueError(
                        "Full Import Model Replacement could not generate a patched target material sidecar."
                    )
                summary_lines.append(
                    f"Generated static replacement payloads: {generated_texture_count:,} texture(s), {generated_sidecar_count:,} sidecar(s)."
                )
            if generated_payloads and not original_sidecars:
                summary_lines.append(
                    "Generated replacement texture payloads without a patched material sidecar because no original sidecar text was available."
                )
    if (
        normalized_import_mode == "static_replacement"
        and bool(getattr(static_replacement_options, "full_import_model_replacement", False))
        and not any(str(getattr(spec, "kind", "") or "") == "sidecar_generated" for spec in supplemental_file_specs)
    ):
        raise ValueError(
            "Full Import Model Replacement requires generated target material sidecar output."
        )
    if supplemental_file_specs:
        mapped_count = sum(1 for spec in supplemental_file_specs if spec.target_path)
        unmapped_count = len(supplemental_file_specs) - mapped_count
        summary_lines.append(f"Supplemental files mapped to package/archive targets: {mapped_count:,}")
        if unmapped_count > 0:
            summary_lines.append(
                f"{unmapped_count:,} supplemental file(s) could not be mapped to a known game-relative target automatically."
            )

    paired_lod_data: Optional[bytes] = None
    paired_lod_path = ""
    if (
        normalized_import_mode in {"roundtrip", "static_replacement"}
        and entry.extension == ".pam"
        and archive_entries_by_normalized_path is not None
    ):
        paired_path = f"{Path(entry.path).with_suffix('.pamlod').as_posix()}"
        paired_candidates = archive_entries_by_normalized_path.get(_normalize_virtual_path(paired_path), ())
        if paired_candidates:
            paired_entry = paired_candidates[0]
            paired_baseline = read_archive_entry_baseline_data(paired_entry, read_entry_data=read_archive_entry_data)
            paired_original = paired_baseline.data
            paired_source_mesh = parsed_mesh if normalized_import_mode == "static_replacement" else imported_mesh
            try:
                paired_mesh = transfer_pam_edit_to_pamlod_mesh(
                    paired_source_mesh,
                    original_data,
                    paired_original,
                    paired_entry.path,
                )
                paired_lod_data = build_mesh(paired_mesh, paired_original)
                paired_lod_path = paired_entry.path
                summary_lines.append(f"Paired PAMLOD rebuild prepared: {paired_entry.path}")
                if paired_baseline.message:
                    summary_lines.append(f"Paired LOD donor: {paired_baseline.message}")
            except Exception as exc:
                summary_lines.append(f"Paired PAMLOD rebuild could not be prepared: {exc}")

    import_diffs, import_issues, auto_fix_result, validation_summary_lines = _build_mesh_import_validation(
        entry,
        original_mesh,
        parsed_mesh,
        import_mode=normalized_import_mode,
        texture_references=texture_references,
        supplemental_file_specs=supplemental_file_specs,
        original_sidecar_bindings=original_archive_sidecar_texture_references,
        selected_sidecar_bindings=selected_sidecar_texture_references,
        paired_lod_path=paired_lod_path,
        manifest_payload=manifest_payload,
    )
    summary_lines.extend(validation_summary_lines)

    return MeshImportPreviewResult(
        rebuilt_data=rebuilt_data,
        parsed_mesh=parsed_mesh,
        preview_model=preview_model,
        summary_lines=summary_lines,
        import_mode=normalized_import_mode,
        texture_references=texture_references,
        supplemental_file_specs=supplemental_file_specs,
        paired_lod_data=paired_lod_data,
        paired_lod_path=paired_lod_path,
        import_diffs=import_diffs,
        import_issues=import_issues,
        auto_fix_result=auto_fix_result,
        roundtrip_manifest=manifest_payload if isinstance(manifest_payload, dict) else None,
        source_owned_output_draw_sections=tuple(getattr(static_report, "output_draw_sections", ()) or ()),
        material_authority_settings=material_authority_settings,
    )
