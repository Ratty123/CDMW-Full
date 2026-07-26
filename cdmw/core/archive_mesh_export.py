from __future__ import annotations

import dataclasses
import re
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.archive_loose_export import _export_related_archive_entries, _sha256_file
from cdmw.core.archive_modding_constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.core.archive_mesh_types import MeshExportResult
from cdmw.core.archive_patching import _safe_log
from cdmw.core.skeleton_resolver import SkeletonResolveReport, build_skin_binding_map, resolve_skeleton_for_model
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.modding.mesh_exporter import export_fbx, export_fbx_with_skeleton, export_obj, write_roundtrip_manifest
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.skeleton_parser import Skeleton, parse_pab

def _mesh_export_basename(entry: ArchiveEntry) -> str:
    stem = PurePosixPath(str(entry.path or "").replace("\\", "/")).stem.strip()
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" ._")
    return safe_stem or "archive_mesh"


_EXPORT_MTL_VISIBLE_TEXTURE_TERMS = (
    "base",
    "basecolor",
    "base_color",
    "color",
    "colour",
    "albedo",
    "diffuse",
    "detaildiffuse",
    "diffusemask",
)
_EXPORT_MTL_SUPPORT_TEXTURE_TERMS = (
    "normal",
    "height",
    "disp",
    "displacement",
    "material",
    "rough",
    "metal",
    "spec",
    "masktexture",
    "_ma",
    "_mg",
    "_sp",
)
_EXPORT_MTL_SUPPORT_SUFFIXES = (
    "_n",
    "_normal",
    "_ma",
    "_mg",
    "_sp",
    "_h",
    "_height",
    "_disp",
    "_displacement",
)


def _normalize_export_texture_alias(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if "/" in text:
        text = PurePosixPath(text).stem
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _resolved_export_texture_path(reference: ArchiveModelTextureReference) -> str:
    for value in (
        getattr(reference, "resolved_archive_path", ""),
        getattr(reference, "reference_name", ""),
    ):
        normalized = str(value or "").strip().replace("\\", "/")
        if normalized.lower().endswith(".dds"):
            return normalized
    return ""


def _export_mtl_visible_texture_priority(reference: ArchiveModelTextureReference) -> int:
    resolved_path = _resolved_export_texture_path(reference)
    if not resolved_path:
        return 0
    basename_stem = PurePosixPath(resolved_path).stem.casefold()
    combined = " ".join(
        str(value or "").strip().casefold()
        for value in (
            getattr(reference, "semantic_label", ""),
            getattr(reference, "semantic_hint", ""),
            getattr(reference, "sidecar_parameter_name", ""),
            getattr(reference, "texture_role", ""),
            getattr(reference, "reference_name", ""),
            resolved_path,
        )
    )
    has_visible_hint = any(term in combined for term in _EXPORT_MTL_VISIBLE_TEXTURE_TERMS)
    has_support_hint = any(term in combined for term in _EXPORT_MTL_SUPPORT_TEXTURE_TERMS)
    has_support_suffix = any(basename_stem.endswith(suffix) for suffix in _EXPORT_MTL_SUPPORT_SUFFIXES)
    if (has_support_hint or has_support_suffix) and not has_visible_hint:
        return 0

    priority = 20
    if "base" in combined or "basecolor" in combined or "albedo" in combined:
        priority += 50
    if "diffuse" in combined or "detaildiffuse" in combined:
        priority += 45
    if "sidecar" in str(getattr(reference, "relation_reason", "") or "").casefold():
        priority += 10
    confidence = str(getattr(reference, "relation_confidence", "") or "").casefold()
    if confidence in {"authoritative", "exact_path"}:
        priority += 10
    if not has_visible_hint and has_support_suffix:
        return 0
    return priority


def _build_export_mtl_texture_overrides(
    parsed_mesh: ParsedMesh,
    texture_references: Sequence[ArchiveModelTextureReference],
) -> Dict[str, str]:
    material_by_alias: Dict[str, str] = {}
    for submesh in parsed_mesh.submeshes:
        material_name = str(submesh.material or submesh.name or "").strip()
        if not material_name:
            continue
        for alias in (submesh.name, submesh.material, submesh.texture):
            normalized_alias = _normalize_export_texture_alias(alias)
            if normalized_alias:
                material_by_alias.setdefault(normalized_alias, material_name)

    best_by_material: Dict[str, Tuple[int, str]] = {}
    for reference in texture_references:
        priority = _export_mtl_visible_texture_priority(reference)
        if priority <= 0:
            continue
        resolved_path = _resolved_export_texture_path(reference)
        if not resolved_path:
            continue
        candidate_aliases = (
            getattr(reference, "material_name", ""),
            getattr(reference, "linked_mesh_path", ""),
            getattr(reference, "part_name", ""),
            getattr(reference, "reference_name", ""),
            resolved_path,
        )
        matched_material = ""
        for alias in candidate_aliases:
            normalized_alias = _normalize_export_texture_alias(str(alias or ""))
            if normalized_alias in material_by_alias:
                matched_material = material_by_alias[normalized_alias]
                break
        if not matched_material:
            continue
        previous = best_by_material.get(matched_material)
        if previous is None or priority > previous[0]:
            best_by_material[matched_material] = (priority, resolved_path)
    return {material: path for material, (_priority, path) in best_by_material.items()}


def _export_mtl_local_texture_reference(output_dir: Path, archive_texture_path: str) -> str:
    normalized = str(archive_texture_path or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    parts = PurePosixPath(normalized).parts
    copied_candidate = output_dir / "referenced_files"
    for part in parts:
        copied_candidate /= part
    if copied_candidate.is_file():
        return PurePosixPath("referenced_files").joinpath(*parts).as_posix()
    return PurePosixPath(normalized).name


def _rewrite_export_mtl_map_kd(
    mtl_path: Path,
    texture_overrides: Mapping[str, str],
    output_dir: Path,
) -> int:
    if not texture_overrides or not mtl_path.is_file():
        return 0
    lines = mtl_path.read_text(encoding="utf-8").splitlines()
    rewritten: List[str] = []
    current_material = ""
    changed = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("newmtl "):
            current_material = stripped[7:].strip()
        if current_material in texture_overrides and stripped.startswith("map_Kd "):
            texture_reference = _export_mtl_local_texture_reference(output_dir, texture_overrides[current_material])
            if texture_reference:
                replacement = f"map_Kd {texture_reference}"
                if line != replacement:
                    line = replacement
                    changed += 1
        rewritten.append(line)
    if changed:
        atomic_write_text(mtl_path, "\n".join(rewritten) + "\n")
    return changed


def _parse_archive_mesh(entry: ArchiveEntry) -> ParsedMesh:
    from cdmw.core.archive_extraction import read_archive_entry_data

    data, _decompressed, _note = read_archive_entry_data(entry)
    mesh = parse_mesh(data, entry.path)
    setattr(mesh, "_cdmw_original_data", bytes(data))
    return mesh


def _archive_family_graph_payload(family_graph: object) -> Dict[str, object]:
    if family_graph is None:
        return {}
    return {
        "root_path": getattr(family_graph, "root_path", ""),
        "family_key": getattr(family_graph, "family_key", ""),
        "members": list(getattr(family_graph, "members", ()) or ()),
        "grouped_paths": {
            key: list(value)
            for key, value in getattr(family_graph, "grouped_paths", {}).items()
        },
        "relations": [
            {
                "source_path": getattr(relation, "source_path", ""),
                "target_path": getattr(relation, "target_path", ""),
                "relation_kind": getattr(relation, "relation_kind", ""),
                "confidence": getattr(relation, "confidence", ""),
                "role_label": getattr(relation, "role_label", ""),
                "reason": getattr(relation, "reason", ""),
                "semantic_label": getattr(relation, "semantic_label", ""),
                "semantic_hint": getattr(relation, "semantic_hint", ""),
                "sidecar_parameter_name": getattr(relation, "sidecar_parameter_name", ""),
                "material_name": getattr(relation, "material_name", ""),
                "package_label": getattr(relation, "package_label", ""),
            }
            for relation in getattr(family_graph, "relations", ()) or ()
        ],
    }


def _find_matching_skeleton_entry(
    entry: ArchiveEntry,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> tuple[Optional[ArchiveEntry], str, Tuple[str, ...], SkeletonResolveReport]:
    from cdmw.core.archive_extraction import read_archive_entry_data

    try:
        pac_data, _decompressed, _note = read_archive_entry_data(entry)
    except Exception:
        pac_data = b""

    def _read_candidate(candidate: ArchiveEntry) -> bytes:
        payload, _decompressed, _note = read_archive_entry_data(candidate)
        return payload

    skeleton_entry, report = resolve_skeleton_for_model(
        entry,
        (),
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
        pac_data=pac_data,
        read_entry_data=_read_candidate,
    )
    if skeleton_entry is not None:
        return skeleton_entry, "", tuple(report.attempted_paths), report
    detail = (
        report.blocking_errors[0]
        if report.blocking_errors
        else f"Could not resolve a matching PAB skeleton for {entry.path}."
    )
    if report.attempted_paths:
        preview = ", ".join(report.attempted_paths[:5])
        if len(report.attempted_paths) > 5:
            preview += " ..."
        detail += f"\nTried: {preview}"
    return None, detail, tuple(report.attempted_paths), report


def export_archive_mesh(
    entry: ArchiveEntry,
    output_dir: Path,
    export_format: str,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    related_entries: Sequence[ArchiveEntry] = (),
    allow_missing_skeleton: bool = False,
    resolve_skeleton_for_obj: bool = True,
    model_texture_references: Optional[Sequence[ArchiveModelTextureReference]] = None,
    asset_family_graph: object = None,
    build_preview_context: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
) -> MeshExportResult:
    export_kind = export_format.strip().lower()
    if export_kind not in {"obj", "fbx"}:
        raise ValueError(f"Unsupported mesh export format: {export_format}")
    if entry.extension not in ARCHIVE_MESH_EXTENSIONS:
        raise ValueError(f"{entry.path} is not a supported mesh entry.")

    parsed_mesh = _parse_archive_mesh(entry)
    if not parsed_mesh.submeshes and not parsed_mesh.lod_levels:
        raise ValueError("No geometry could be recovered from the selected mesh.")

    output_dir.mkdir(parents=True, exist_ok=True)
    basename = _mesh_export_basename(entry)
    _safe_log(on_log, f"Exporting {entry.path} as {export_kind.upper()}...")

    output_paths: List[Path] = []
    skeleton: Optional[Skeleton] = None
    skeleton_entry: Optional[ArchiveEntry] = None
    skeleton_resolution_warning = ""
    skeleton_resolve_report: Optional[SkeletonResolveReport] = None
    copied_related_count = 0
    should_resolve_skeleton = entry.extension == ".pac" and (
        export_kind == "fbx" or bool(resolve_skeleton_for_obj)
    )
    if should_resolve_skeleton:
        skeleton_entry, skeleton_resolution_warning, _attempted_paths, skeleton_resolve_report = _find_matching_skeleton_entry(
            entry,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
    if export_kind == "obj":
        output_paths.extend(Path(path) for path in export_obj(parsed_mesh, str(output_dir), basename))
    else:
        if entry.extension == ".pac":
            if skeleton_entry is not None:
                from cdmw.core.archive_extraction import read_archive_entry_data

                try:
                    skeleton_data, _decompressed, _note = read_archive_entry_data(skeleton_entry)
                    skeleton = parse_pab(skeleton_data, skeleton_entry.path)
                    if not skeleton.bones:
                        skeleton_resolution_warning = (
                            f"Matched skeleton {skeleton_entry.path} did not contain any bones."
                        )
                        skeleton = None
                except Exception as exc:
                    skeleton_resolution_warning = (
                        f"Matched skeleton {skeleton_entry.path} could not be parsed: {exc}"
                    )
                    skeleton = None
            if skeleton is None and not allow_missing_skeleton:
                confirmation_message = (
                    f"Export {entry.path} as FBX without an armature?\n\n"
                    f"{skeleton_resolution_warning or 'No matching PAB skeleton could be resolved.'}\n\n"
                    "Choose Yes to continue with a mesh-only FBX export, or No to cancel."
                )
                return MeshExportResult(
                    output_paths=[],
                    summary_lines=[
                        f"Path: {entry.path}",
                        f"Format: {parsed_mesh.format.upper()}",
                        "FBX export is waiting for confirmation because no usable skeleton could be attached.",
                    ],
                    requires_confirmation=True,
                    confirmation_title="Export FBX Without Skeleton?",
                    confirmation_message=confirmation_message,
                )
        if skeleton is not None and skeleton.bones:
            output_paths.append(Path(export_fbx_with_skeleton(parsed_mesh, skeleton, str(output_dir), basename)))
        else:
            output_paths.append(Path(export_fbx(parsed_mesh, str(output_dir), basename)))

    if related_entries:
        related_output_root = output_dir / "referenced_files"
        copied_paths = _export_related_archive_entries(
            related_entries,
            related_output_root,
            on_log=on_log,
        )
        output_paths.extend(copied_paths)
        copied_related_count = len(copied_paths)

    manifest_target_path = next(
        (
            path for path in output_paths
            if path.suffix.lower() in {".obj", ".fbx"}
        ),
        None,
    )
    if manifest_target_path is not None:
        # One try covers several stages; track which one is running so a failure
        # in an early stage is not reported as a round-trip manifest problem.
        manifest_stage = "archive preview metadata rebuild"
        try:
            manifest_texture_references = tuple(model_texture_references or ())
            manifest_family_graph = asset_family_graph
            if build_preview_context and not manifest_texture_references and manifest_family_graph is None:
                from cdmw.core.archive_preview_result_builder import build_archive_preview_result

                preview_result = build_archive_preview_result(
                    entry,
                    (),
                    texture_entries_by_normalized_path=(
                        dict(archive_entries_by_normalized_path) if archive_entries_by_normalized_path is not None else None
                    ),
                    texture_entries_by_basename=(
                        dict(archive_entries_by_basename) if archive_entries_by_basename is not None else None
                    ),
                )
                manifest_texture_references = tuple(getattr(preview_result, "model_texture_references", ()) or ())
                manifest_family_graph = getattr(preview_result, "asset_family_graph", None)
            elif not build_preview_context and not manifest_texture_references:
                _safe_log(on_log, "Skipped archive preview metadata rebuild for internal Modify Original clone.")
            paired_lod_target = ""
            if entry.extension == ".pam" and archive_entries_by_normalized_path is not None:
                paired_candidates = archive_entries_by_normalized_path.get(
                    str(PurePosixPath(entry.path).with_suffix(".pamlod")).replace("\\", "/").strip().lower(),
                    (),
                )
                if paired_candidates:
                    paired_lod_target = paired_candidates[0].path
            manifest_stage = "OBJ material texture rebinding"
            companion_path = ""
            if manifest_target_path.suffix.lower() == ".obj":
                companion_candidate = manifest_target_path.with_suffix(".mtl")
                if companion_candidate.is_file():
                    companion_path = str(companion_candidate)
                    rewritten_mtl_rows = _rewrite_export_mtl_map_kd(
                        companion_candidate,
                        _build_export_mtl_texture_overrides(parsed_mesh, manifest_texture_references),
                        output_dir,
                    )
                    if rewritten_mtl_rows:
                        _safe_log(
                            on_log,
                            f"Updated {rewritten_mtl_rows:,} OBJ material texture binding(s) from resolved archive sidecar evidence.",
                        )
            selected_companion_files: List[str] = []
            seen_selected_companion_files: set[str] = set()
            sidecar_hashes: Dict[str, str] = {}
            for related_entry in related_entries:
                if not isinstance(related_entry, ArchiveEntry):
                    continue
                normalized_related_path = related_entry.path.replace("\\", "/").strip()
                normalized_related_key = normalized_related_path.lower()
                if normalized_related_path and normalized_related_key not in seen_selected_companion_files:
                    seen_selected_companion_files.add(normalized_related_key)
                    selected_companion_files.append(normalized_related_path)
                related_extension = related_entry.extension.lower()
                related_basename = PurePosixPath(normalized_related_path).name.lower()
                if related_extension in {".xml", ".pami", ".json"} or related_basename.endswith("_xml"):
                    copied_sidecar_path = (output_dir / "referenced_files").joinpath(
                        *PurePosixPath(normalized_related_path).parts
                    )
                    if copied_sidecar_path.is_file():
                        sidecar_hashes[normalized_related_path] = _sha256_file(copied_sidecar_path)
            family_graph_payload = _archive_family_graph_payload(manifest_family_graph)
            texture_binding_rows = [
                {
                    "reference_name": reference.reference_name,
                    "resolved_archive_path": reference.resolved_archive_path,
                    "semantic_label": reference.semantic_label,
                    "semantic_hint": reference.semantic_hint,
                    "sidecar_parameter_name": reference.sidecar_parameter_name,
                    "material_name": reference.material_name,
                    "relation_group": reference.relation_group,
                }
                for reference in manifest_texture_references
                if str(getattr(reference, "relation_group", "") or "").strip() == "Textures"
            ]
            skeleton_resolver_payload = (
                dataclasses.asdict(skeleton_resolve_report)
                if skeleton_resolve_report is not None
                else {}
            )
            skin_binding_payload = (
                build_skin_binding_map(
                    skeleton,
                    (),
                    source_path=skeleton_entry.path if skeleton_entry is not None else entry.path,
                    strict=True,
                ).to_dict()
                if skeleton is not None and getattr(skeleton, "bones", None)
                else {}
            )
            extra_payload = {
                "source_archive_path": entry.path,
                "source_archive_format": entry.extension.lstrip(".").lower(),
                "export_format": manifest_target_path.suffix.lstrip(".").lower(),
                "selected_companion_files": selected_companion_files,
                "texture_bindings": texture_binding_rows,
                "texture_semantics": texture_binding_rows,
                "sidecar_hashes": sidecar_hashes,
            }
            if family_graph_payload:
                extra_payload["family_graph"] = family_graph_payload
            if paired_lod_target:
                extra_payload["paired_pamlod_target"] = paired_lod_target
            if skeleton_entry is not None:
                extra_payload["skeleton_identity"] = skeleton_entry.path
            if skeleton_resolver_payload:
                extra_payload["skeleton_resolver"] = skeleton_resolver_payload
            if skin_binding_payload:
                extra_payload["skin_binding_map"] = skin_binding_payload
            manifest_stage = "round-trip manifest write"
            manifest_path = write_roundtrip_manifest(
                parsed_mesh,
                manifest_target_path,
                companion_path=companion_path,
                extra_payload=extra_payload,
            )
            if manifest_path not in output_paths:
                output_paths.append(manifest_path)
        except Exception as exc:
            _safe_log(on_log, f"Warning: {manifest_stage} failed for {entry.path}: {exc}")

    summary_lines = [
        f"Path: {entry.path}",
        f"Format: {parsed_mesh.format.upper()}",
        f"Submeshes: {len(parsed_mesh.submeshes):,}",
        f"Vertices: {parsed_mesh.total_vertices:,}",
        f"Faces: {parsed_mesh.total_faces:,}",
    ]
    if copied_related_count:
        summary_lines.append(f"Referenced files copied: {copied_related_count:,}")
    if skeleton_entry is not None and skeleton is not None and skeleton.bones:
        summary_lines.append(f"Skeleton: {skeleton_entry.path}")
        summary_lines.append(f"Skeleton bones: {len(skeleton.bones):,}")
        if skeleton_resolve_report is not None:
            summary_lines.append(
                f"Skeleton confidence: {skeleton_resolve_report.confidence}"
                + (f" ({skeleton_resolve_report.reason})" if skeleton_resolve_report.reason else "")
            )
            if skeleton_resolve_report.descriptor_path:
                summary_lines.append(f"Skeleton descriptor: {skeleton_resolve_report.descriptor_path}")
            if skeleton_resolve_report.skeleton_variation_path:
                summary_lines.append(f"Skeleton variation: {skeleton_resolve_report.skeleton_variation_path}")
    elif export_kind == "fbx" and entry.extension == ".pac":
        summary_lines.append("Skeleton: mesh-only export")
        if skeleton_resolution_warning:
            summary_lines.append(f"Skeleton fallback reason: {skeleton_resolution_warning}")
    return MeshExportResult(output_paths=output_paths, summary_lines=summary_lines)
