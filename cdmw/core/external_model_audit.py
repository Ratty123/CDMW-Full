from __future__ import annotations

import dataclasses
import csv
import io
import json
import re
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

from cdmw.core.model_catalogue import LocalModelFile, safe_extract_zip, scan_local_model_files, zip_importable_members
from cdmw.modding.scene_importer import (
    SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS,
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    ExternalModelAudit,
    import_scene_mesh_with_report,
)


EXTERNAL_MODEL_AUDIT_EXTENSIONS = (".glb", ".gltf", ".fbx", ".obj", ".dae", ".zip")
_IMPORTABLE_EXTERNAL_MODEL_EXTENSIONS = (".glb", ".gltf", ".obj", ".dae")
_ZIP_EXTERNAL_METADATA_EXTENSIONS = (".fbx",)
_AUDIT_TEXTURE_EXTENSIONS = SCENE_TEXTURE_SOURCE_EXTENSIONS | SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS
_AUDIT_TEXTURE_FACT_MAX_IMAGE_BYTES = 256 * 1024 * 1024
_FBX_BINARY_HEADER = b"Kaydara FBX Binary"
_FBX_BINARY_PRINTABLE = re.compile(rb"[A-Za-z0-9_ ./\\:\-+()\[\]{}@#$%&=~'\",]{4,}")


def build_external_model_audit_catalogue(
    roots: Iterable[Path | str],
    *,
    max_files: int = 50_000,
    audit_zip_contents: bool = False,
    max_zip_audits: int | None = None,
) -> dict[str, object]:
    """Build a read-only material authority catalogue for external model roots."""
    normalized_roots = tuple(_normalize_root(root) for root in roots)
    model_files = scan_local_model_files(
        normalized_roots,
        extensions=EXTERNAL_MODEL_AUDIT_EXTENSIONS,
        max_files=max(1, int(max_files)),
    )
    zip_audit_limit = None if max_zip_audits is None or int(max_zip_audits) <= 0 else int(max_zip_audits)
    zip_audits_used = 0
    rows: list[dict[str, object]] = []
    for row in model_files:
        skip_reason = ""
        source_path = Path(str(getattr(row, "path", "") or ""))
        if bool(audit_zip_contents) and zip_audit_limit is not None and source_path.suffix.lower() == ".zip":
            importable_members = zip_importable_members(source_path)
            audit_members = _zip_external_model_members(source_path, importable_members)
            if audit_members:
                if zip_audits_used >= zip_audit_limit:
                    skip_reason = f"max_zip_audits:{zip_audit_limit}"
                else:
                    zip_audits_used += 1
        rows.append(
            _audit_external_model_file(
                row,
                audit_zip_contents=bool(audit_zip_contents),
                zip_content_audit_skip_reason=skip_reason,
            )
        )
    return {
        "schema_version": 1,
        "tool": "external_model_audit_catalogue",
        "generated_at_unix": int(time.time()),
        "roots": [str(root) for root in normalized_roots],
        "extensions": list(EXTERNAL_MODEL_AUDIT_EXTENSIONS),
        "audit_zip_contents": bool(audit_zip_contents),
        "max_zip_audits": zip_audit_limit,
        "summary": _external_catalogue_summary(rows),
        "models": rows,
    }


def write_external_model_audit_catalogue(report: Mapping[str, object], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def _normalize_root(root: Path | str) -> Path:
    path = Path(root).expanduser()
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _audit_external_model_file(
    row: LocalModelFile,
    *,
    audit_zip_contents: bool = False,
    zip_content_audit_skip_reason: str = "",
) -> dict[str, object]:
    base = row.to_dict()
    source_path = Path(str(base.get("path", "") or row.path))
    extension = source_path.suffix.lower()
    companion_textures = _companion_texture_inventory(source_path)
    if extension == ".zip":
        importable_members = zip_importable_members(source_path)
        audit_members = _zip_external_model_members(source_path, importable_members)
        zip_textures = _zip_texture_inventory(source_path)
        skip_reason = str(zip_content_audit_skip_reason or "").strip()
        if audit_zip_contents and audit_members and not skip_reason:
            audited_row = _audit_zip_external_model_file(
                row,
                source_path=source_path,
                companion_textures=tuple(companion_textures) + tuple(zip_textures),
                importable_members=importable_members,
                audit_members=audit_members,
            )
            if audited_row:
                return audited_row
        if skip_reason:
            warnings = (f"ZIP indexed read-only; content audit skipped because {skip_reason}.",)
        elif audit_members:
            warnings = (
                "ZIP indexed read-only; material inventory is not parsed until user enables temporary content audit.",
            )
        else:
            warnings = ("ZIP does not contain OBJ, DAE, glTF, GLB, FBX, PAC, PAM, or PAMLOD model members.",)
        return {
            **base,
            "audit_status": "archive_indexed" if audit_members else "archive_no_importable_model",
            "import_supported": bool(importable_members),
            "zip_importable_members": importable_members,
            "zip_audit_members": audit_members,
            "zip_content_audit_skipped": bool(skip_reason),
            "zip_content_audit_skip_reason": skip_reason,
            "companion_textures": tuple(companion_textures) + tuple(zip_textures),
            "missing_texture_refs": (),
            "ambiguous_texture_refs": (),
            "unresolved_texture_candidates": (),
            "warnings": warnings,
            "material_inventory": (),
            "material_classes": (),
        }
    if extension not in _IMPORTABLE_EXTERNAL_MODEL_EXTENSIONS:
        if extension == ".fbx":
            material_inventory = _fbx_ascii_material_inventory(source_path, companion_textures) or _fbx_binary_material_inventory(source_path, companion_textures)
        else:
            material_inventory = ()
        if not material_inventory:
            material_inventory = _unsupported_companion_material_inventory(source_path, companion_textures)
        material_classes = tuple(
            item
            for material in material_inventory
            for item in tuple(material.get("material_classes", ()) or ())
            if isinstance(item, Mapping)
        )
        inferred_from_file = _fbx_inventory_inferred_from_file(extension, material_inventory)
        fbx_metadata_source = next(
            (
                str(slot.get("source", "") or "")
                for material in material_inventory
                for slot in tuple(material.get("texture_slots", ()) or ())
                if isinstance(slot, Mapping) and str(slot.get("source", "") or "") in {"fbx_ascii", "fbx_binary"}
            ),
            next(
                (
                    str(material.get("metadata_source", "") or "")
                    for material in material_inventory
                    if isinstance(material, Mapping)
                    and str(material.get("metadata_source", "") or "") in {"fbx_ascii", "fbx_binary"}
                ),
                "",
            ),
        )
        ambiguous_refs = _ambiguous_texture_refs(material_inventory)
        warnings = list(
            (
                (
                    "FBX binary material inventory inferred from embedded texture filename strings; geometry import still requires OBJ, DAE, GLB, or glTF."
                    if fbx_metadata_source == "fbx_binary"
                    else "FBX ASCII material inventory inferred from embedded Material/Texture/Connection records; geometry import still requires OBJ, DAE, GLB, or glTF."
                ),
                "FBX material audit is metadata-only; verify material assignments after converting/importing the model.",
            )
            if inferred_from_file
            else (
                f"{extension.upper().lstrip('.')} is browsable but not material-audited without an importer; export OBJ, DAE, GLB, or glTF.",
                "Material inventory inferred from companion texture filenames only; geometry/material assignments are unavailable.",
            )
        )
        if ambiguous_refs:
            warnings.append(f"{len(ambiguous_refs):,} ambiguous texture role assignment(s) need manual review.")
        return {
            **base,
            "audit_status": "browsable_material_inferred" if inferred_from_file else "browsable_unsupported",
            "import_supported": False,
            "companion_textures": companion_textures,
            "missing_texture_refs": (),
            "ambiguous_texture_refs": ambiguous_refs,
            "unresolved_texture_candidates": (),
            "warnings": tuple(warnings),
            "material_inventory": material_inventory,
            "material_classes": material_classes,
        }
    try:
        scene_result = import_scene_mesh_with_report(source_path)
    except Exception as exc:
        return {
            **base,
            "audit_status": "failed",
            "import_supported": True,
            "companion_textures": companion_textures,
            "missing_texture_refs": (),
            "ambiguous_texture_refs": (),
            "unresolved_texture_candidates": (),
            "warnings": (str(exc),),
            "material_inventory": (),
            "material_classes": (),
        }
    audit = scene_result.external_audit
    missing_refs = _missing_texture_refs(audit)
    material_inventory = tuple(_material_inventory_rows(audit))
    ambiguous_refs = _ambiguous_texture_refs(material_inventory)
    unresolved_candidates = _unresolved_texture_candidates(audit, companion_textures)
    warnings = list(tuple(getattr(audit, "warnings", ()) or ()))
    if missing_refs:
        warnings.append(f"{len(missing_refs):,} referenced texture file(s) are missing on disk.")
    if unresolved_candidates:
        warnings.append(f"{len(unresolved_candidates):,} unresolved texture candidate(s) available for manual review.")
    if ambiguous_refs:
        warnings.append(f"{len(ambiguous_refs):,} ambiguous texture role assignment(s) need manual review.")
    return {
        **base,
        "audit_status": "audited",
        "import_supported": True,
        "diagnostics": tuple(scene_result.diagnostics or ()),
        "discovered_texture_files": tuple(str(path) for path in tuple(scene_result.discovered_texture_files or ())),
        "companion_textures": companion_textures,
        "missing_texture_refs": missing_refs,
        "ambiguous_texture_refs": ambiguous_refs,
        "unresolved_texture_candidates": unresolved_candidates,
        "audit": _external_audit_to_dict(audit),
        "material_inventory": material_inventory,
        "material_classes": tuple(_material_class_rows(audit)),
        "warnings": _dedupe_preserve_order(warnings),
    }


def _audit_zip_external_model_file(
    row: LocalModelFile,
    *,
    source_path: Path,
    companion_textures: Sequence[Mapping[str, object]],
    importable_members: Sequence[str],
    audit_members: Sequence[str],
) -> dict[str, object]:
    base = row.to_dict()
    with tempfile.TemporaryDirectory(prefix="cdmw_external_zip_audit_") as temp_dir:
        extract_root = Path(temp_dir) / source_path.stem
        try:
            safe_extract_zip(source_path, extract_root)
            resolved_path = _first_existing_zip_audit_member(extract_root, audit_members)
            if resolved_path is None:
                raise ValueError(f"ZIP file does not contain an auditable external model: {source_path}.")
            if resolved_path.suffix.lower() == ".fbx":
                return _audit_zip_fbx_metadata_file(
                    row,
                    source_path=source_path,
                    extract_root=extract_root,
                    resolved_path=resolved_path,
                    companion_textures=companion_textures,
                    importable_members=importable_members,
                    audit_members=audit_members,
                )
            scene_result = import_scene_mesh_with_report(resolved_path)
        except Exception as exc:
            return {
                **base,
                "audit_status": "archive_failed",
                "import_supported": bool(importable_members),
                "zip_importable_members": tuple(importable_members),
                "zip_audit_members": tuple(audit_members),
                "companion_textures": tuple(companion_textures),
                "missing_texture_refs": (),
                "ambiguous_texture_refs": (),
                "unresolved_texture_candidates": (),
                "warnings": (f"ZIP content material audit failed: {exc}",),
                "material_inventory": (),
                "material_classes": (),
            }
        audit = scene_result.external_audit
        missing_refs = _rewrite_extracted_paths(_missing_texture_refs(audit), source_path, extract_root)
        material_inventory = tuple(_material_inventory_rows(audit))
        ambiguous_refs = _rewrite_extracted_paths(_ambiguous_texture_refs(material_inventory), source_path, extract_root)
        unresolved_candidates = _rewrite_extracted_paths(
            _unresolved_texture_candidates(audit, companion_textures),
            source_path,
            extract_root,
        )
        warnings = list(tuple(getattr(audit, "warnings", ()) or ()))
        if missing_refs:
            warnings.append(f"{len(tuple(missing_refs or ())):,} referenced texture file(s) are missing on disk.")
        if unresolved_candidates:
            warnings.append(f"{len(tuple(unresolved_candidates or ())):,} unresolved texture candidate(s) available for manual review.")
        if ambiguous_refs:
            warnings.append(f"{len(tuple(ambiguous_refs or ())):,} ambiguous texture role assignment(s) need manual review.")
        warnings.append("ZIP material inventory audited from temporary extraction; downloads root was not modified.")
        resolved_member = _archive_member_reference(source_path, extract_root, resolved_path)
        return {
            **base,
            "audit_status": "archive_audited",
            "import_supported": True,
            "zip_importable_members": tuple(importable_members),
            "zip_audit_members": tuple(audit_members),
            "zip_audited_member": str(resolved_member).split("::", 1)[-1],
            "diagnostics": _rewrite_extracted_paths(tuple(scene_result.diagnostics or ()), source_path, extract_root),
            "discovered_texture_files": _rewrite_extracted_paths(
                tuple(str(path) for path in tuple(scene_result.discovered_texture_files or ())),
                source_path,
                extract_root,
            ),
            "companion_textures": tuple(companion_textures),
            "missing_texture_refs": missing_refs,
            "ambiguous_texture_refs": ambiguous_refs,
            "unresolved_texture_candidates": unresolved_candidates,
            "audit": _rewrite_extracted_paths(_external_audit_to_dict(audit), source_path, extract_root),
            "material_inventory": _rewrite_extracted_paths(material_inventory, source_path, extract_root),
            "material_classes": _rewrite_extracted_paths(tuple(_material_class_rows(audit)), source_path, extract_root),
            "warnings": _dedupe_preserve_order(warnings),
        }


def _zip_external_model_members(archive_path: Path, importable_members: Sequence[str]) -> tuple[str, ...]:
    members = list(tuple(importable_members or ()))
    seen = {str(member).replace("\\", "/").lower() for member in members}
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                member_name = member.filename.replace("\\", "/")
                if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                    continue
                if Path(member_name).suffix.lower() not in _ZIP_EXTERNAL_METADATA_EXTENSIONS:
                    continue
                key = member_name.lower()
                if key not in seen:
                    seen.add(key)
                    members.append(member.filename)
    except (OSError, zipfile.BadZipFile):
        return tuple(importable_members or ())
    priority = {".gltf": 0, ".glb": 1, ".obj": 2, ".dae": 3, ".fbx": 4, ".pac": 5, ".pam": 6, ".pamlod": 7}
    return tuple(sorted(members, key=lambda value: (priority.get(Path(value).suffix.lower(), 99), str(value).lower())))


def _first_existing_zip_audit_member(extract_root: Path, members: Sequence[str]) -> Path | None:
    for member in tuple(members or ()):
        member_path = PurePosixPath(str(member).replace("\\", "/"))
        candidate = extract_root.joinpath(*member_path.parts)
        if candidate.is_file():
            return candidate
    return None


def _audit_zip_fbx_metadata_file(
    row: LocalModelFile,
    *,
    source_path: Path,
    extract_root: Path,
    resolved_path: Path,
    companion_textures: Sequence[Mapping[str, object]],
    importable_members: Sequence[str],
    audit_members: Sequence[str],
) -> dict[str, object]:
    base = row.to_dict()
    try:
        stat = resolved_path.stat()
        extracted_row = LocalModelFile(
            path=resolved_path,
            root=extract_root,
            name=resolved_path.name,
            extension=resolved_path.suffix.lower(),
            size=int(stat.st_size),
            modified_at=float(stat.st_mtime),
            import_supported=False,
        )
    except OSError:
        extracted_row = LocalModelFile(
            path=resolved_path,
            root=extract_root,
            name=resolved_path.name,
            extension=resolved_path.suffix.lower(),
            size=0,
            modified_at=0.0,
            import_supported=False,
        )
    audited = _audit_external_model_file(extracted_row, audit_zip_contents=False)
    material_inventory = _rewrite_extracted_paths(tuple(audited.get("material_inventory", ()) or ()), source_path, extract_root)
    ambiguous_refs = _rewrite_extracted_paths(_ambiguous_texture_refs(material_inventory), source_path, extract_root)
    warnings = list(tuple(audited.get("warnings", ()) or ()))
    if ambiguous_refs:
        warnings.append(f"{len(tuple(ambiguous_refs or ())):,} ambiguous texture role assignment(s) need manual review.")
    warnings.append("ZIP FBX material inventory audited from temporary extraction; downloads root was not modified.")
    resolved_member = _archive_member_reference(source_path, extract_root, resolved_path)
    return {
        **base,
        "audit_status": "archive_audited",
        "import_supported": False,
        "zip_importable_members": tuple(importable_members),
        "zip_audit_members": tuple(audit_members),
        "zip_audited_member": str(resolved_member).split("::", 1)[-1],
        "companion_textures": _rewrite_extracted_paths(tuple(audited.get("companion_textures", ()) or companion_textures), source_path, extract_root),
        "missing_texture_refs": (),
        "ambiguous_texture_refs": ambiguous_refs,
        "unresolved_texture_candidates": (),
        "material_inventory": material_inventory,
        "material_classes": _rewrite_extracted_paths(tuple(audited.get("material_classes", ()) or ()), source_path, extract_root),
        "warnings": _dedupe_preserve_order(warnings),
    }


def _rewrite_extracted_paths(value: object, archive_path: Path, extract_root: Path) -> object:
    if isinstance(value, Mapping):
        return {str(key): _rewrite_extracted_paths(item, archive_path, extract_root) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_rewrite_extracted_paths(item, archive_path, extract_root) for item in value)
    if isinstance(value, list):
        return [_rewrite_extracted_paths(item, archive_path, extract_root) for item in value]
    if isinstance(value, Path):
        return _archive_member_reference(archive_path, extract_root, value)
    if isinstance(value, str):
        return _archive_member_reference(archive_path, extract_root, value)
    return value


def _archive_member_reference(archive_path: Path, extract_root: Path, value: object) -> object:
    text = str(value or "")
    if not text:
        return text
    try:
        path = Path(text).expanduser()
        if not path.is_absolute():
            return text
        relative = path.resolve().relative_to(extract_root.resolve())
    except (OSError, ValueError):
        return text
    return f"{archive_path}::{relative.as_posix()}"


def _external_audit_to_dict(audit: ExternalModelAudit | None) -> dict[str, object]:
    if audit is None:
        return {}
    payload = _jsonable_dataclass(audit)
    if isinstance(payload, dict):
        payload.pop("material_inventory", None)
        payload.pop("material_classes", None)
        return payload
    return {}


def _material_inventory_rows(audit: ExternalModelAudit | None) -> tuple[dict[str, object], ...]:
    if audit is None:
        return ()
    rows: list[dict[str, object]] = []
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        texture_slots = []
        for slot in tuple(getattr(material, "texture_slots", ()) or ()):
            slot_payload = _jsonable_dataclass(slot)
            if isinstance(slot_payload, dict):
                texture_slots.append(slot_payload)
        sections = tuple(
            section_payload
            for section_payload in (
                _jsonable_dataclass(section)
                for section in tuple(getattr(material, "sections", ()) or ())
            )
            if isinstance(section_payload, dict)
        )
        rows.append(
            _material_row_with_channel_profile(
                {
                    "material_index": _safe_int(getattr(material, "material_index", -1), -1),
                    "material_name": str(getattr(material, "material_name", "") or ""),
                    "submesh_indices": tuple(getattr(material, "submesh_indices", ()) or ()),
                    "submesh_names": tuple(getattr(material, "submesh_names", ()) or ()),
                    "sections": sections,
                    "section_count": len(sections),
                    "pbr_workflow": str(getattr(material, "pbr_workflow", "") or ""),
                    "alpha_mode": str(getattr(material, "alpha_mode", "") or ""),
                    "double_sided": bool(getattr(material, "double_sided", False)),
                    "scalar_hints": dict(tuple(getattr(material, "scalar_hints", ()) or ())),
                    "color_factor": tuple(getattr(material, "color_factor", ()) or ()),
                    "vertex_color_factor": tuple(getattr(material, "vertex_color_factor", ()) or ()),
                    "vertex_alpha": tuple(getattr(material, "vertex_alpha", ()) or ()),
                    "emissive_color": tuple(getattr(material, "emissive_color", ()) or ()),
                    "texture_slots": tuple(texture_slots),
                    "material_classes": tuple(_jsonable_dataclass(item) for item in tuple(getattr(material, "material_classes", ()) or ())),
                    "warnings": tuple(getattr(material, "warnings", ()) or ()),
                }
            )
        )
    return tuple(rows)


def _material_row_with_channel_profile(row: Mapping[str, object]) -> dict[str, object]:
    payload = dict(row)
    if not str(payload.get("pbr_workflow", "") or "").strip():
        payload["pbr_workflow"] = _fallback_material_workflow(payload)
    profile = _material_channel_profile(payload)
    payload["channel_profile"] = profile
    payload["detected_channels"] = tuple(profile.get("detected_channels", ()) or ())
    payload["missing_channels"] = tuple(profile.get("missing_channels", ()) or ())
    payload["channel_diagnostics"] = tuple(profile.get("diagnostics", ()) or ())
    return payload


def _fallback_material_workflow(row: Mapping[str, object]) -> str:
    texture_slots = tuple(slot for slot in tuple(row.get("texture_slots", ()) or ()) if isinstance(slot, Mapping))
    scalar_hints = row.get("scalar_hints") if isinstance(row.get("scalar_hints"), Mapping) else {}
    workflow = _unsupported_companion_workflow(texture_slots, scalar_hints)
    if workflow:
        return workflow
    scalar_keys = {str(key or "").strip().lower() for key in tuple((scalar_hints or {}).keys()) if str(key or "").strip()}
    if {"specular", "glossiness"}.intersection(scalar_keys):
        return "specular_glossiness"
    if {"roughness", "metalness"}.intersection(scalar_keys):
        return "metallic_roughness"
    if (
        texture_slots
        or scalar_keys
        or len(tuple(row.get("color_factor", ()) or ())) >= 3
        or len(tuple(row.get("vertex_color_factor", ()) or ())) >= 3
        or len(tuple(row.get("emissive_color", ()) or ())) >= 3
    ):
        return "legacy_fixed_function"
    return ""


def _material_channel_profile(row: Mapping[str, object]) -> dict[str, object]:
    texture_channels: set[str] = set()
    scalar_channels: set[str] = set()
    diagnostics: list[dict[str, object]] = []
    for slot in tuple(row.get("texture_slots", ()) or ()):
        if not isinstance(slot, Mapping):
            continue
        for value in (
            slot.get("slot_kind"),
            slot.get("semantic_type"),
            slot.get("semantic_subtype"),
            *tuple(slot.get("packed_channels", ()) or ()),
            slot.get("parameter_name"),
        ):
            _add_material_channel(texture_channels, value)
        alpha_usage = _slot_alpha_channel_usage(slot)
        if alpha_usage == "visible_alpha":
            texture_channels.add("opacity")
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "source_alpha_from_texture_channel",
                    "slot_kind": str(slot.get("slot_kind", "") or ""),
                    "texture_name": str(slot.get("texture_name", "") or ""),
                    "a_mean": _slot_channel_stat(slot, "a_mean", 1.0),
                    "a_min": _slot_channel_stat(slot, "a_min", 1.0),
                    "a_max": _slot_channel_stat(slot, "a_max", 1.0),
                }
            )
        elif alpha_usage == "technical_alpha":
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "source_packed_a_channel_technical",
                    "slot_kind": str(slot.get("slot_kind", "") or ""),
                    "texture_name": str(slot.get("texture_name", "") or ""),
                    "a_mean": _slot_channel_stat(slot, "a_mean", 1.0),
                    "a_min": _slot_channel_stat(slot, "a_min", 1.0),
                    "a_max": _slot_channel_stat(slot, "a_max", 1.0),
                }
            )
    scalar_hints = row.get("scalar_hints")
    if isinstance(scalar_hints, Mapping):
        for key in tuple(scalar_hints.keys()):
            _add_material_channel(scalar_channels, key)
    if len(tuple(row.get("color_factor", ()) or ())) >= 3:
        scalar_channels.add("base_color")
    if len(tuple(row.get("vertex_color_factor", ()) or ())) >= 3:
        scalar_channels.add("base_color")
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_vertex_color_present",
                "vertex_color_factor": tuple(row.get("vertex_color_factor", ()) or ()),
            }
        )
    vertex_alpha = tuple(row.get("vertex_alpha", ()) or ())
    if len(vertex_alpha) >= 2:
        try:
            if _safe_float(vertex_alpha[0], 1.0) < 0.98 or _safe_float(vertex_alpha[1], 1.0) < 0.98:
                scalar_channels.add("opacity")
                diagnostics.append(
                    {
                        "severity": "info",
                        "code": "source_vertex_alpha_opacity",
                        "vertex_alpha": vertex_alpha,
                    }
                )
        except (TypeError, ValueError, OverflowError):
            pass
    emissive_color = tuple(row.get("emissive_color", ()) or ())
    if any(_safe_float(component, 0.0) > 0.0 for component in emissive_color):
        scalar_channels.add("emissive")
    alpha_mode = str(row.get("alpha_mode", "") or "").strip().lower()
    workflow = str(row.get("pbr_workflow", "") or "").strip().lower()
    if workflow == "legacy_fixed_function":
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_legacy_fixed_function_workflow",
                "message": "Source material uses legacy fixed-function/scalar channels rather than glTF PBR workflow.",
            }
        )
    derived_channels: set[str] = set()
    effective_channels = texture_channels | scalar_channels
    if "specular_glossiness" in workflow or "speculargloss" in workflow:
        if "glossiness" in effective_channels:
            derived_channels.add("roughness")
        if "specular" in effective_channels:
            derived_channels.add("metalness")
        if derived_channels:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "source_spec_gloss_derived_material_channels",
                    "derived_channels": tuple(sorted(derived_channels)),
                }
            )
    effective_channels = effective_channels | derived_channels
    missing = [
        channel
        for channel in ("emissive", "roughness", "metalness")
        if channel not in effective_channels
    ]
    if "base_color" not in texture_channels and "base_color" not in scalar_channels:
        diagnostics.append({"severity": "warning", "code": "source_missing_base_color"})
    if alpha_mode in {"blend", "mask", "alpha", "transparent", "coverage", "cutout"} and "opacity" not in texture_channels and "opacity" not in scalar_channels:
        diagnostics.append({"severity": "warning", "code": "source_alpha_without_opacity_texture", "alpha_mode": alpha_mode})
    if _material_implies_visible_alpha(row) and "opacity" not in texture_channels and "opacity" not in scalar_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_alpha_intent_without_opacity_evidence",
                "message": "Material name/class implies glass or translucent response, but no alpha/opacity source channel was found.",
            }
        )
    if "emissive" in scalar_channels and "emissive" not in texture_channels:
        diagnostics.append({"severity": "info", "code": "source_emissive_scalar_no_texture"})
    for channel in missing:
        diagnostics.append({"severity": "info", "code": f"source_missing_{channel}"})
    if {"roughness", "metalness"}.issubset(set(missing)):
        diagnostics.append({"severity": "info", "code": "source_missing_roughness_metalness"})
    detected = tuple(sorted(texture_channels | derived_channels | {f"{channel}_scalar" for channel in scalar_channels}))
    return {
        "workflow": str(row.get("pbr_workflow", "") or ""),
        "detected_channels": detected,
        "texture_channels": tuple(sorted(texture_channels)),
        "scalar_channels": tuple(sorted(scalar_channels)),
        "derived_channels": tuple(sorted(derived_channels)),
        "missing_channels": tuple(missing),
        "diagnostics": tuple(diagnostics),
    }


def _material_implies_visible_alpha(row: Mapping[str, object]) -> bool:
    for item in tuple(row.get("material_classes", ()) or ()):
        if isinstance(item, Mapping) and str(item.get("material_class", "") or "").strip().lower() in {"glass", "crystal", "glass_crystal"}:
            return True
    text = " ".join(
        str(value or "")
        for value in (
            row.get("material_name"),
            row.get("runtime_material_name"),
            row.get("section_name"),
        )
    ).lower()
    return any(token in text for token in ("translucent", "transparent", "glass", "crystal", "gem"))


def _add_material_channel(channels: set[str], value: object) -> None:
    text = str(value or "").strip().lower()
    if not text:
        return
    if (
        text in {"base", "base color", "base_color", "albedo", "diffuse"}
        or any(token in text for token in ("basecolor", "base_color", "albedo", "diffuse", "overlaycolor", "rgbtexture", "color"))
        and "colorblending" not in text
        and not any(token in text for token in ("emissive", "specular", "gloss", "metal", "rough", "normal", "opacity", "alpha", "ao", "height"))
    ):
        channels.add("base_color")
    if "normal" in text:
        channels.add("normal")
    if any(token in text for token in ("roughness", "rough", "smoothness")):
        channels.add("roughness")
    if any(token in text for token in ("metallic", "metalness", "metal")):
        channels.add("metalness")
    if any(token in text for token in ("specular", "gloss", "specgloss")):
        channels.add("specular")
        channels.add("glossiness")
    if any(token in text for token in ("emissive", "emission", "glow", "illum")):
        channels.add("emissive")
    if any(token in text for token in ("opacity", "alpha", "transparent")):
        channels.add("opacity")
    if any(token in text for token in ("ao", "occlusion", "ambientocclusion")):
        channels.add("ao")
    if any(token in text for token in ("height", "displacement", "bump", "parallax")):
        channels.add("height")


def _slot_alpha_channel_usage(slot: Mapping[str, object]) -> str:
    if not _slot_has_nonopaque_alpha(slot):
        return ""
    slot_kind = str(slot.get("slot_kind", "") or "").strip().lower()
    semantic_type = str(slot.get("semantic_type", "") or "").strip().lower()
    semantic_subtype = str(slot.get("semantic_subtype", "") or "").strip().lower()
    parameter_name = str(slot.get("parameter_name", "") or "").strip().lower()
    packed_channels = {
        str(value or "").strip().lower()
        for value in tuple(slot.get("packed_channels", ()) or ())
        if str(value or "").strip()
    }
    text = " ".join((slot_kind, semantic_type, semantic_subtype, parameter_name))
    if any(token in text for token in ("opacity", "alpha", "transparent")):
        return "visible_alpha"
    if slot_kind in {"base", "diffuse", "albedo", "emissive"} or semantic_type in {"base", "base_color", "emissive"}:
        return "visible_alpha"
    if packed_channels or slot_kind in {
        "roughness",
        "metalness",
        "material",
        "specular",
        "occlusion",
        "ao",
        "normal",
        "height",
    }:
        return "technical_alpha"
    return "technical_alpha"


def _slot_has_nonopaque_alpha(slot: Mapping[str, object]) -> bool:
    stats = dict(tuple(slot.get("channel_stats", ()) or ()))
    return _safe_float(stats.get("a_min"), 1.0) < 0.999 or _safe_float(stats.get("a_mean"), 1.0) < 0.999


def _slot_channel_stat(slot: Mapping[str, object], key: str, default: float = 0.0) -> float:
    return round(_safe_float(dict(tuple(slot.get("channel_stats", ()) or ())).get(key), default), 4)


def _material_class_rows(audit: ExternalModelAudit | None) -> tuple[dict[str, object], ...]:
    if audit is None:
        return ()
    rows: list[dict[str, object]] = []
    for item in tuple(getattr(audit, "material_classes", ()) or ()):
        payload = _jsonable_dataclass(item)
        if isinstance(payload, dict):
            rows.append(payload)
    return tuple(rows)


def _jsonable_dataclass(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable_dataclass(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return tuple(_jsonable_dataclass(item) for item in value)
    if isinstance(value, list):
        return [_jsonable_dataclass(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable_dataclass(item) for key, item in value.items()}
    return value


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _missing_texture_refs(audit: ExternalModelAudit | None) -> tuple[str, ...]:
    if audit is None:
        return ()
    missing: list[str] = []
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        for slot in tuple(getattr(material, "texture_slots", ()) or ()):
            texture_path = str(getattr(slot, "texture_path", "") or "").strip()
            if texture_path and not Path(texture_path).is_file():
                missing.append(texture_path)
    return tuple(_dedupe_sorted(missing))


def _missing_texture_slot_rows(audit: ExternalModelAudit | None) -> tuple[tuple[str, str, str], ...]:
    if audit is None:
        return ()
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        material_name = str(getattr(material, "material_name", "") or "<unnamed>").strip() or "<unnamed>"
        for slot in tuple(getattr(material, "texture_slots", ()) or ()):
            slot_kind = str(getattr(slot, "slot_kind", "") or "").strip().lower()
            texture_path = str(getattr(slot, "texture_path", "") or "").strip()
            if not slot_kind or not texture_path or Path(texture_path).is_file():
                continue
            key = (material_name, slot_kind, texture_path)
            if key in seen:
                continue
            seen.add(key)
            rows.append(key)
    return tuple(rows)


def _unresolved_texture_candidates(
    audit: ExternalModelAudit | None,
    companion_textures: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    missing_rows = _missing_texture_slot_rows(audit)
    if not missing_rows:
        return ()
    candidates = tuple(row for row in tuple(companion_textures or ()) if isinstance(row, Mapping))
    if not candidates:
        return ()
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for material_name, slot_kind, missing_ref in missing_rows:
        ranked: list[tuple[int, Mapping[str, object]]] = []
        for candidate in candidates:
            candidate_path = str(candidate.get("path", "") or "").strip()
            if not candidate_path or candidate_path == missing_ref:
                continue
            candidate_slot = str(candidate.get("slot_guess", "") or "").strip().lower()
            compatible = _texture_slots_compatible(slot_kind, candidate_slot)
            rank = 0 if compatible else 1 if candidate_slot else 2
            ranked.append((rank, candidate))
        for _rank, candidate in sorted(ranked, key=lambda item: (item[0], str(item[1].get("name", "") or "").casefold()))[:8]:
            candidate_path = str(candidate.get("path", "") or "").strip()
            candidate_slot = str(candidate.get("slot_guess", "") or "").strip().lower()
            key = (material_name, slot_kind, missing_ref, candidate_path)
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "material_name": material_name,
                    "slot_kind": slot_kind,
                    "missing_texture_ref": missing_ref,
                    "candidate_path": candidate_path,
                    "candidate_name": str(candidate.get("name", "") or PurePosixPath(candidate_path.replace("\\", "/")).name),
                    "candidate_slot_guess": candidate_slot,
                    "candidate_extension": str(candidate.get("extension", "") or PurePosixPath(candidate_path).suffix).lower(),
                    "candidate_archive_member": str(candidate.get("archive_member", "") or ""),
                    "candidate_diagnostic_only": bool(candidate.get("diagnostic_only")),
                    "candidate_resolution": tuple(candidate.get("resolution", ()) or ()),
                    "candidate_channel_stats": tuple(candidate.get("channel_stats", ()) or ()),
                    "candidate_color_space": _unsupported_slot_color_space(candidate_slot or slot_kind),
                    "candidate_resolution_status": str(candidate.get("resolution_status", "") or ""),
                    "candidate_channel_stats_status": str(candidate.get("channel_stats_status", "") or ""),
                    "confidence": "same_role" if _texture_slots_compatible(slot_kind, candidate_slot) else "nearby_unmatched_role" if candidate_slot else "nearby_texture",
                    "evidence": str(candidate.get("evidence", "") or ""),
                }
            )
    return tuple(output)


def _texture_slots_compatible(wanted: str, candidate: str) -> bool:
    wanted = str(wanted or "").strip().lower()
    candidate = str(candidate or "").strip().lower()
    if not wanted or not candidate:
        return False
    if wanted == candidate:
        return True
    aliases = {
        "base": {"albedo", "diffuse", "base_color"},
        "base_color": {"base", "albedo", "diffuse"},
        "ao": {"occlusion"},
        "occlusion": {"ao"},
        "material": {"metalness", "roughness", "metallic_roughness"},
        "metalness": {"material", "metallic"},
        "roughness": {"material"},
        "opacity": {"alpha", "transparent"},
        "alpha": {"opacity", "transparent"},
    }
    return candidate in aliases.get(wanted, set())


def _ambiguous_texture_refs(material_inventory: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    ambiguous: list[str] = []
    for material in tuple(material_inventory or ()):
        if not isinstance(material, Mapping):
            continue
        material_name = str(material.get("material_name", "") or "<unnamed>").strip() or "<unnamed>"
        by_slot: dict[str, list[str]] = {}
        for slot in tuple(material.get("texture_slots", ()) or ()):
            if not isinstance(slot, Mapping):
                continue
            slot_kind = str(slot.get("slot_kind", "") or "").strip().lower()
            texture_path = str(slot.get("texture_path", "") or slot.get("texture_name", "") or "").strip()
            if not slot_kind or not texture_path:
                continue
            rows = by_slot.setdefault(slot_kind, [])
            normalized = texture_path.replace("\\", "/")
            if normalized not in rows:
                rows.append(normalized)
        for slot_kind, paths in sorted(by_slot.items()):
            if len(paths) > 1:
                ambiguous.append(f"{material_name}:{slot_kind}:{'|'.join(sorted(paths, key=str.casefold))}")
    return tuple(_dedupe_sorted(ambiguous))


def _fbx_inventory_inferred_from_file(
    extension: str,
    material_inventory: Sequence[Mapping[str, object]],
) -> bool:
    if str(extension or "").lower() != ".fbx" or not material_inventory:
        return False
    for material in tuple(material_inventory or ()):
        if not isinstance(material, Mapping):
            continue
        if str(material.get("metadata_source", "") or "") in {"fbx_ascii", "fbx_binary"}:
            return True
        for slot in tuple(material.get("texture_slots", ()) or ()):
            if isinstance(slot, Mapping) and str(slot.get("source", "") or "") in {"fbx_ascii", "fbx_binary"}:
                return True
    return False


def _companion_texture_inventory(model_path: Path) -> tuple[dict[str, object], ...]:
    candidates = _companion_texture_paths(model_path)
    rows: list[dict[str, object]] = []
    for path in candidates:
        slot = _guess_texture_slot(path)
        diagnostic_only = path.suffix.lower() in SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS
        resolution, channel_stats = _texture_image_facts(path)
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "extension": path.suffix.lower(),
                "slot_guess": slot,
                "diagnostic_only": diagnostic_only,
                "resolution": resolution,
                "channel_stats": channel_stats,
                "resolution_status": "available" if len(resolution) >= 2 else "missing_or_unreadable",
                "channel_stats_status": "available" if channel_stats else "missing_or_unreadable",
                "evidence": f"filename token:{slot}" if slot else "nearby texture file",
            }
        )
    return tuple(rows)


def _companion_texture_paths(model_path: Path) -> tuple[Path, ...]:
    roots = []
    for root in (model_path.parent, model_path.parent / "textures", model_path.parent.parent / "textures"):
        if root.is_dir() and root not in roots:
            roots.append(root)
    candidates: list[Path] = []
    model_key = _texture_group_key(model_path)
    for root in roots:
        try:
            iterator = root.rglob("*") if root != model_path.parent else root.iterdir()
        except OSError:
            continue
        for path in iterator:
            if not path.is_file() or path.suffix.lower() not in _AUDIT_TEXTURE_EXTENSIONS:
                continue
            texture_key = _texture_group_key(path)
            if (
                root != model_path.parent
                or texture_key == model_key
                or (model_key and (model_key in texture_key or texture_key in model_key))
            ):
                candidates.append(_resolve_path(path))
    return tuple(Path(path) for path in _dedupe_sorted(str(path) for path in candidates))


def _zip_texture_inventory(archive_path: Path) -> tuple[dict[str, object], ...]:
    if archive_path.suffix.lower() != ".zip" or not archive_path.is_file():
        return ()
    rows: list[dict[str, object]] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                member_name = member.filename.replace("\\", "/")
                if member.is_dir() or not member_name or member_name.startswith("/") or "../" in f"/{member_name}":
                    continue
                suffix = Path(member_name).suffix.lower()
                if suffix not in _AUDIT_TEXTURE_EXTENSIONS:
                    continue
                slot = _guess_texture_slot(Path(member_name))
                diagnostic_only = suffix in SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS
                resolution, channel_stats = _zip_member_texture_facts(archive, member)
                rows.append(
                    {
                        "path": f"{archive_path}::{member_name}",
                        "name": PurePosixPath(member_name).name,
                        "extension": suffix,
                        "slot_guess": slot,
                        "diagnostic_only": diagnostic_only,
                        "resolution": resolution,
                        "channel_stats": channel_stats,
                        "resolution_status": "available" if len(resolution) >= 2 else "missing_or_unreadable",
                        "channel_stats_status": "available" if channel_stats else "missing_or_unreadable",
                        "archive_member": member_name,
                        "bytes": int(getattr(member, "file_size", 0) or 0),
                        "evidence": f"zip filename token:{slot}" if slot else "zip texture member",
                    }
                )
    except (OSError, zipfile.BadZipFile):
        return ()
    return tuple(sorted(rows, key=lambda row: str(row.get("archive_member", "")).lower()))


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _texture_group_key(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    for token in (
        "basecolor",
        "basecolour",
        "albedo",
        "diffuse",
        "normal",
        "normalmap",
        "nrm",
        "metallicroughness",
        "roughnessmetallic",
        "roughness",
        "metallic",
        "metalness",
        "specularglossiness",
        "specular",
        "glossiness",
        "emissive",
        "emission",
        "opacity",
        "alpha",
        "ao",
        "occlusion",
        "height",
        "displacement",
        "texture",
        "tex",
        "base",
        "color",
        "colour",
    ):
        stem = stem.replace(token, "")
    return stem or re.sub(r"[^a-z0-9]+", "", path.stem.lower())


def _guess_texture_slot(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "colormap")) or stem.endswith("base"):
        return "base"
    if any(token in stem for token in ("normalmap", "normalgl", "normaldx", "normal", "nrm")):
        return "normal"
    if any(token in stem for token in ("metallicroughness", "roughnessmetallic", "metalrough", "metallicrough")):
        return "material"
    if "roughness" in stem or "rough" in stem:
        return "roughness"
    if any(token in stem for token in ("metallic", "metalness")):
        return "metalness"
    if any(token in stem for token in ("specularglossiness", "specgloss", "specular", "glossiness")):
        return "specular"
    if any(token in stem for token in ("emissive", "emission", "glow", "illum")):
        return "emissive"
    if any(token in stem for token in ("opacity", "alpha", "transparent")):
        return "opacity"
    if any(token in stem for token in ("ao", "occlusion", "ambientocclusion")):
        return "ao"
    if any(token in stem for token in ("height", "displacement", "bump")):
        return "height"
    return ""


def _fbx_ascii_material_inventory(
    model_path: Path,
    companion_textures: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    text = _read_ascii_fbx_text(model_path)
    if not text:
        return ()
    materials = _fbx_ascii_material_rows(text)
    textures = _fbx_ascii_texture_rows(model_path, text)
    if not materials and textures:
        materials = [("-1", model_path.stem)]
    if not materials:
        return ()
    material_properties = _fbx_ascii_material_properties(text)
    connections = _fbx_ascii_texture_connections(text)
    slots_by_material: dict[str, list[dict[str, object]]] = {material_id: [] for material_id, _name in materials}
    for texture_id, material_id, property_name in connections:
        texture = textures.get(texture_id)
        if not texture or material_id not in slots_by_material:
            continue
        slot_kind = _guess_fbx_texture_slot(texture, property_name)
        slot = _unsupported_texture_slot_from_path(
            slot_kind,
            str(texture["path"]),
            name=str(texture["name"]),
            source="fbx_ascii",
            confidence="fbx_ascii_connection",
            evidence=tuple(
                item
                for item in (
                    f"fbx_texture_id:{texture_id}",
                    f"fbx_material_id:{material_id}",
                    f"connection:{property_name}" if property_name else "",
                )
                if item
            ),
        )
        if slot:
            slots_by_material[material_id].append(slot)
    if textures and not any(slots_by_material.values()):
        first_material_id = materials[0][0]
        for texture_id, texture in textures.items():
            slot_kind = _guess_fbx_texture_slot(texture, "")
            slot = _unsupported_texture_slot_from_path(
                slot_kind,
                str(texture["path"]),
                name=str(texture["name"]),
                source="fbx_ascii",
                confidence="fbx_ascii_texture",
                evidence=(f"fbx_texture_id:{texture_id}", "fbx_unconnected_texture"),
            )
            if slot:
                slots_by_material[first_material_id].append(slot)
    companion_slots = tuple(
        slot
        for slot in (_unsupported_companion_texture_slot(row) for row in tuple(companion_textures or ()))
        if slot
    )
    output: list[dict[str, object]] = []
    for index, (material_id, material_name) in enumerate(materials):
        texture_slots = _dedupe_texture_slot_rows(tuple(slots_by_material.get(material_id, ())) or companion_slots)
        properties = material_properties.get(material_id, {})
        scalar_hints = dict(properties.get("scalar_hints", {}) if isinstance(properties.get("scalar_hints"), Mapping) else {})
        color_factor = tuple(properties.get("color_factor", ()) or ())
        vertex_alpha = tuple(properties.get("vertex_alpha", ()) or ())
        emissive_color = tuple(properties.get("emissive_color", ()) or ())
        classes = _unsupported_companion_material_classes(
            model_path,
            texture_slots,
            material_name=material_name,
            scalar_hints=scalar_hints,
            color_factor=color_factor,
            vertex_alpha=vertex_alpha,
            emissive_color=emissive_color,
        )
        output.append(
            _material_row_with_channel_profile(
                {
                    "material_index": index,
                    "metadata_source": "fbx_ascii",
                    "material_name": material_name or model_path.stem,
                    "submesh_indices": (),
                    "submesh_names": (),
                    "sections": (),
                    "section_count": 0,
                    "pbr_workflow": _unsupported_companion_workflow(texture_slots, scalar_hints),
                    "alpha_mode": (
                        "blend"
                        if vertex_alpha or any(slot.get("slot_kind") == "opacity" for slot in texture_slots)
                        else ""
                    ),
                    "double_sided": False,
                    "scalar_hints": scalar_hints,
                    "color_factor": color_factor,
                    "vertex_color_factor": (),
                    "vertex_alpha": vertex_alpha,
                    "emissive_color": emissive_color,
                    "texture_slots": texture_slots,
                    "material_classes": classes,
                    "warnings": ("FBX ASCII material inventory inferred without geometry/submesh assignment.",),
                }
            )
        )
    return tuple(output)


def _read_ascii_fbx_text(model_path: Path) -> str:
    try:
        data = model_path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in data[:4096]:
        return ""
    try:
        text = data.decode("utf-8", errors="ignore")
    except UnicodeDecodeError:
        return ""
    if "Material:" not in text and "Texture:" not in text:
        return ""
    return text


def _fbx_binary_material_inventory(
    model_path: Path,
    companion_textures: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    data = _read_binary_fbx_bytes(model_path)
    if not data:
        return ()
    texture_rows = _fbx_binary_texture_rows(model_path, data)
    if not texture_rows:
        return ()
    binary_slots = tuple(
        slot
        for texture in texture_rows
        for slot in (
            _unsupported_texture_slot_from_path(
                _guess_fbx_texture_slot(texture, ""),
                str(texture.get("path", "") or ""),
                name=str(texture.get("name", "") or ""),
                source="fbx_binary",
                confidence="fbx_binary_texture",
                evidence=(
                    "fbx_binary_string_ref",
                    f"raw_path:{texture.get('raw_path', '')}",
                ),
            ),
        )
        if slot
    )
    if not binary_slots:
        return ()
    companion_slots = tuple(
        slot
        for slot in (_unsupported_companion_texture_slot(row) for row in tuple(companion_textures or ()))
        if slot
    )
    texture_slots = _dedupe_texture_slot_rows(tuple(binary_slots) + companion_slots)
    material_name = _fbx_binary_material_name(data) or model_path.stem
    classes = _unsupported_companion_material_classes(model_path, texture_slots, material_name=material_name)
    return (
        _material_row_with_channel_profile(
            {
                "material_index": 0,
                "metadata_source": "fbx_binary",
                "material_name": material_name,
                "submesh_indices": (),
                "submesh_names": (),
                "sections": (),
                "section_count": 0,
                "pbr_workflow": _unsupported_companion_workflow(texture_slots),
                "alpha_mode": "blend" if any(slot.get("slot_kind") == "opacity" for slot in texture_slots) else "",
                "double_sided": False,
                "scalar_hints": {},
                "color_factor": (),
                "vertex_color_factor": (),
                "vertex_alpha": (),
                "emissive_color": (),
                "texture_slots": texture_slots,
                "material_classes": classes,
                "warnings": ("FBX binary material inventory inferred from embedded texture filename strings without geometry/submesh assignment.",),
            }
        ),
    )


def _read_binary_fbx_bytes(model_path: Path) -> bytes:
    try:
        data = model_path.read_bytes()
    except OSError:
        return b""
    if not data:
        return b""
    if data.startswith(_FBX_BINARY_HEADER) or b"\x00" in data[:4096]:
        return data
    return b""


def _fbx_binary_texture_rows(model_path: Path, data: bytes) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in _FBX_BINARY_PRINTABLE.finditer(data):
        value = match.group(0).decode("utf-8", errors="ignore").strip()
        reference = _fbx_binary_texture_reference(value)
        if not reference:
            continue
        key = reference.replace("\\", "/").casefold()
        if key in seen:
            continue
        seen.add(key)
        resolved = _resolve_fbx_texture_reference(model_path, reference)
        rows.append(
            {
                "name": PurePosixPath(reference.replace("\\", "/")).name,
                "path": resolved,
                "raw_path": reference,
            }
        )
    return tuple(rows)


def _fbx_binary_texture_reference(value: str) -> str:
    text = str(value or "").strip().strip("\"'")
    if not text:
        return ""
    lower = text.lower()
    suffix = next((item for item in sorted(_AUDIT_TEXTURE_EXTENSIONS, key=len, reverse=True) if item in lower), "")
    if not suffix:
        return ""
    end = lower.find(suffix) + len(suffix)
    reference = text[:end].strip().strip("\"'")
    reference = re.sub(r"^(?:relative)?filename\s*[:=]\s*", "", reference, flags=re.IGNORECASE).strip()
    return reference if Path(reference.replace("\\", "/")).suffix.lower() in _AUDIT_TEXTURE_EXTENSIONS else ""


def _fbx_binary_material_name(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore")
    for pattern in (r"Material::([^\x00\r\n\";:{}]+)", r"Model::([^\x00\r\n\";:{}]+)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            name = _fbx_object_name(match.group(1)).strip()
            if name:
                return name
    return ""


def _fbx_ascii_material_rows(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for match in re.finditer(r'Material:\s*([-\d]+),\s*"([^"]*)"', text, flags=re.IGNORECASE):
        material_id = str(match.group(1) or "").strip()
        name = _fbx_object_name(match.group(2))
        if material_id:
            rows.append((material_id, name or material_id))
    return rows


def _fbx_ascii_material_properties(text: str) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    pattern = re.compile(
        r'Material:\s*(?P<id>[-\d]+),\s*"(?P<name>[^"]*)"[^{}]*\{(?P<body>.*?)\n\s*\}',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        material_id = str(match.group("id") or "").strip()
        if not material_id:
            continue
        scalar_hints: dict[str, float] = {}
        color_factor: tuple[float, float, float] = ()
        emissive_color: tuple[float, float, float] = ()
        opacity: float | None = None
        for property_name, values in _fbx_ascii_material_property_values(match.group("body") or ""):
            key = _normalized_fbx_property_name(property_name)
            if not values:
                continue
            if key in {"diffusecolor", "basecolor", "basecolorfactor"} and len(values) >= 3:
                color_factor = _clamped_color(values[:3])
            elif key in {"emissivecolor", "emissioncolor"} and len(values) >= 3:
                emissive_color = _clamped_color(values[:3])
                if any(component > 0.003 for component in emissive_color):
                    scalar_hints.setdefault("emissive_intensity", 1.0)
            elif key in {"emissivefactor", "emissionfactor"}:
                scalar_hints["emissive_intensity"] = max(0.0, min(32.0, values[0]))
            elif key in {"opacity", "alpha"}:
                opacity = max(0.0, min(1.0, values[0]))
                scalar_hints["opacity"] = opacity
            elif key in {"roughness", "roughnessfactor"}:
                scalar_hints["roughness"] = max(0.0, min(1.0, values[0]))
            elif key in {"metalness", "metallic", "metallicfactor"}:
                scalar_hints["metalness"] = max(0.0, min(1.0, values[0]))
            elif key in {"specularfactor", "specular"}:
                scalar_hints["specular"] = max(0.0, min(1.0, values[0]))
            elif key == "specularcolor" and len(values) >= 3:
                scalar_hints["specular"] = max(0.0, min(1.0, _rgb_luma(values[:3])))
            elif key in {"shininess", "shininessexponent"}:
                glossiness = values[0] if 0.0 <= values[0] <= 1.0 else values[0] / 100.0
                scalar_hints.setdefault("roughness", max(0.0, min(1.0, 1.0 - glossiness)))
        payload: dict[str, object] = {"scalar_hints": scalar_hints}
        if color_factor:
            payload["color_factor"] = color_factor
        if emissive_color:
            payload["emissive_color"] = emissive_color
        if opacity is not None and opacity < 0.999:
            payload["vertex_alpha"] = (round(opacity, 4), round(opacity, 4))
        rows[material_id] = payload
    return rows


def _fbx_ascii_material_property_values(body: str) -> tuple[tuple[str, tuple[float, ...]], ...]:
    rows: list[tuple[str, tuple[float, ...]]] = []
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("p:"):
            continue
        try:
            fields = next(csv.reader([stripped[2:].strip()], skipinitialspace=True))
        except (csv.Error, StopIteration):
            continue
        if len(fields) < 5:
            continue
        name = str(fields[0] or "").strip()
        values: list[float] = []
        for field in fields[4:]:
            try:
                values.append(float(str(field).strip()))
            except (TypeError, ValueError, OverflowError):
                continue
        if name and values:
            rows.append((name, tuple(values)))
    return tuple(rows)


def _normalized_fbx_property_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clamped_color(values: Sequence[float]) -> tuple[float, float, float]:
    return tuple(round(max(0.0, min(1.0, float(value))), 4) for value in tuple(values)[:3])  # type: ignore[return-value]


def _rgb_luma(values: Sequence[float]) -> float:
    rgb = tuple(float(value) for value in tuple(values)[:3])
    if len(rgb) < 3:
        return 0.0
    return (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])


def _fbx_ascii_texture_rows(model_path: Path, text: str) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    pattern = re.compile(
        r'Texture:\s*(?P<id>[-\d]+),\s*"(?P<name>[^"]*)"[^{}]*\{(?P<body>.*?)\n\s*\}',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        texture_id = str(match.group("id") or "").strip()
        body = match.group("body") or ""
        filename = (
            _first_fbx_body_value(body, "RelativeFilename")
            or _first_fbx_body_value(body, "FileName")
            or _first_fbx_body_value(body, "Filename")
        )
        if not texture_id or not filename:
            continue
        resolved = _resolve_fbx_texture_reference(model_path, filename)
        rows[texture_id] = {
            "name": _fbx_object_name(match.group("name")) or PurePosixPath(str(filename).replace("\\", "/")).name,
            "path": resolved,
            "raw_path": filename,
        }
    return rows


def _fbx_ascii_texture_connections(text: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    pattern = re.compile(
        r'C:\s*"OP",\s*([-\d]+),\s*([-\d]+)(?:,\s*"([^"]*)")?',
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        texture_id = str(match.group(1) or "").strip()
        material_id = str(match.group(2) or "").strip()
        property_name = str(match.group(3) or "").strip()
        if texture_id and material_id:
            rows.append((texture_id, material_id, property_name))
    return rows


def _fbx_object_name(value: object) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    return text.strip()


def _first_fbx_body_value(body: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}:\s*\"([^\"]*)\"", str(body or ""), flags=re.IGNORECASE)
    return str(match.group(1) or "").strip() if match else ""


def _resolve_fbx_texture_reference(model_path: Path, reference: str) -> str:
    raw = str(reference or "").strip().replace("\\", "/")
    if not raw:
        return ""
    path = Path(raw)
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    candidates.append(model_path.parent / raw)
    candidates.append(model_path.parent / PurePosixPath(raw).name)
    for candidate in candidates:
        try:
            if candidate.expanduser().is_file():
                return candidate.expanduser().resolve().as_posix()
        except OSError:
            continue
    return raw


def _guess_fbx_texture_slot(texture: Mapping[str, object], property_name: str) -> str:
    combined = f"{property_name} {texture.get('name', '')} {texture.get('path', '')}".lower()
    if any(token in combined for token in ("diffuse", "basecolor", "base color", "albedo")):
        return "base"
    if "normal" in combined or "bump" in combined:
        return "normal"
    if "roughness" in combined or "metallicroughness" in combined:
        return "material" if "metal" in combined else "roughness"
    if "metal" in combined:
        return "metalness"
    if "specular" in combined or "gloss" in combined:
        return "specular"
    if "emissive" in combined or "emission" in combined or "glow" in combined:
        return "emissive"
    if "opacity" in combined or "alpha" in combined or "transparent" in combined:
        return "opacity"
    if "ao" in combined or "occlusion" in combined:
        return "ao"
    if "height" in combined or "displacement" in combined:
        return "height"
    return _guess_texture_slot(Path(str(texture.get("path", "") or "")))


def _unsupported_texture_slot_from_path(
    slot_kind: str,
    path_text: str,
    *,
    name: str = "",
    source: str,
    confidence: str,
    evidence: Sequence[str] = (),
) -> dict[str, object]:
    slot = str(slot_kind or "").strip().lower()
    if not slot or not path_text:
        return {}
    path = Path(path_text)
    resolution, channel_stats = _texture_image_facts(path)
    semantic_type, semantic_subtype, packed_channels = _unsupported_slot_semantics(slot)
    return {
        "slot_kind": slot,
        "parameter_name": _unsupported_slot_parameter(slot),
        "texture_path": path_text,
        "texture_name": name or path.name,
        "image_format": path.suffix.lower().lstrip("."),
        "resolution": resolution,
        "channel_stats": channel_stats,
        "semantic_type": semantic_type,
        "semantic_subtype": semantic_subtype,
        "packed_channels": packed_channels,
        "color_space": _unsupported_slot_color_space(slot),
        "diagnostic_only": path.suffix.lower() in SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS,
        "source": source,
        "confidence": confidence,
        "evidence": tuple(item for item in tuple(evidence or ()) + (f"slot:{slot}", _channel_stats_evidence(channel_stats)) if item),
    }


def _dedupe_texture_slot_rows(rows: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in tuple(rows or ()):
        slot = str(row.get("slot_kind", "") or "").strip().lower()
        path = str(row.get("texture_path", "") or "").strip().lower().replace("\\", "/")
        key = (slot, path)
        if not slot or not path or key in seen:
            continue
        seen.add(key)
        output.append(dict(row))
    return tuple(output)


def _unsupported_companion_material_inventory(
    model_path: Path,
    companion_textures: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    texture_slots = tuple(
        slot
        for slot in (_unsupported_companion_texture_slot(row) for row in tuple(companion_textures or ()))
        if slot
    )
    if not texture_slots:
        return ()
    classes = _unsupported_companion_material_classes(model_path, texture_slots)
    return (
        _material_row_with_channel_profile(
            {
                "material_index": -1,
                "material_name": model_path.stem,
                "submesh_indices": (),
                "submesh_names": (),
                "sections": (),
                "section_count": 0,
                "pbr_workflow": _unsupported_companion_workflow(texture_slots),
                "alpha_mode": "blend" if any(slot.get("slot_kind") == "opacity" for slot in texture_slots) else "",
                "double_sided": False,
                "scalar_hints": {},
                "color_factor": (),
                "vertex_color_factor": (),
                "vertex_alpha": (),
                "emissive_color": (),
                "texture_slots": texture_slots,
                "material_classes": classes,
                "warnings": ("Unsupported model material row inferred from companion texture filenames only.",),
            }
        ),
    )


def _unsupported_companion_texture_slot(row: Mapping[str, object]) -> dict[str, object]:
    slot = str(row.get("slot_guess", "") or "").strip().lower()
    path_text = str(row.get("path", "") or "").strip()
    if not slot or not path_text:
        return {}
    path = Path(path_text)
    diagnostic_only = bool(row.get("diagnostic_only"))
    resolution, channel_stats = _texture_image_facts(path)
    semantic_type, semantic_subtype, packed_channels = _unsupported_slot_semantics(slot)
    evidence = [
        str(row.get("evidence", "") or ""),
        f"slot:{slot}",
        "diagnostic_only_texture_format" if diagnostic_only else "",
        _channel_stats_evidence(channel_stats),
    ]
    return {
        "slot_kind": slot,
        "parameter_name": _unsupported_slot_parameter(slot),
        "texture_path": path_text,
        "texture_name": str(row.get("name", "") or path.name),
        "image_format": str(row.get("extension", "") or path.suffix).lower().lstrip("."),
        "resolution": resolution,
        "channel_stats": channel_stats,
        "semantic_type": semantic_type,
        "semantic_subtype": semantic_subtype,
        "packed_channels": packed_channels,
        "color_space": _unsupported_slot_color_space(slot),
        "diagnostic_only": diagnostic_only,
        "source": "companion_filename_diagnostic" if diagnostic_only else "companion_filename",
        "confidence": "filename_only_diagnostic" if diagnostic_only else "filename_only",
        "evidence": tuple(item for item in evidence if item),
    }


def _unsupported_slot_parameter(slot: str) -> str:
    return {
        "base": "_baseColorTexture",
        "normal": "_normalTexture",
        "material": "_metallicRoughnessTexture",
        "roughness": "_roughnessTexture",
        "metalness": "_metallicTexture",
        "specular": "_specularTexture",
        "emissive": "_emissiveTexture",
        "opacity": "_opacityTexture",
        "ao": "_occlusionTexture",
        "height": "_heightTexture",
    }.get(slot, "")


def _unsupported_slot_semantics(slot: str) -> tuple[str, str, tuple[str, ...]]:
    if slot == "base":
        return "base", "albedo", ()
    if slot == "normal":
        return "normal", "normal", ()
    if slot == "material":
        return "material", "metallic_roughness", ("roughness", "metallic")
    if slot == "roughness":
        return "roughness", "roughness", ("roughness",)
    if slot == "metalness":
        return "metalness", "metallic", ("metallic",)
    if slot == "specular":
        return "specular", "specular_glossiness", ("specular", "glossiness")
    if slot == "emissive":
        return "emissive", "emissive", ()
    if slot == "opacity":
        return "opacity", "alpha", ("alpha",)
    if slot == "ao":
        return "occlusion", "ao", ("ao",)
    if slot == "height":
        return "height", "height", ()
    return slot, slot, ()


def _unsupported_slot_color_space(slot: str) -> str:
    if slot in {"base", "emissive"}:
        return "srgb"
    if slot:
        return "linear"
    return ""


def _unsupported_companion_workflow(
    texture_slots: Sequence[Mapping[str, object]],
    scalar_hints: Mapping[str, object] | None = None,
) -> str:
    slots = {str(slot.get("slot_kind", "") or "").strip().lower() for slot in tuple(texture_slots or ()) if isinstance(slot, Mapping)}
    scalar_keys = {str(key or "").strip().lower() for key in tuple((scalar_hints or {}).keys()) if str(key or "").strip()}
    if "material" in slots or {"roughness", "metalness"}.intersection(slots):
        return "metallic_roughness"
    if {"roughness", "metalness"}.intersection(scalar_keys):
        return "metallic_roughness"
    if "specular" in slots:
        return "specular_glossiness"
    if {"specular", "glossiness"}.intersection(scalar_keys):
        return "specular_glossiness"
    return ""


def _unsupported_companion_material_classes(
    model_path: Path,
    texture_slots: Sequence[Mapping[str, object]],
    *,
    material_name: str = "",
    scalar_hints: Mapping[str, object] | None = None,
    color_factor: Sequence[float] = (),
    vertex_alpha: Sequence[float] = (),
    emissive_color: Sequence[float] = (),
) -> tuple[dict[str, object], ...]:
    text = " ".join(
        [model_path.stem, str(material_name or "")]
        + [str(slot.get("texture_name", "") or "") for slot in tuple(texture_slots or ()) if isinstance(slot, Mapping)]
    ).lower()
    evidence: dict[str, list[str]] = {}
    scalar_map = {
        str(key or "").strip().lower(): _safe_float(value, 0.0)
        for key, value in tuple((scalar_hints or {}).items())
        if str(key or "").strip()
    }

    def add(material_class: str, reason: str) -> None:
        evidence.setdefault(material_class, [])
        if reason not in evidence[material_class]:
            evidence[material_class].append(reason)

    def slot_stats(*slot_names: str) -> dict[str, float]:
        wanted = {str(name or "").strip().lower() for name in tuple(slot_names or ()) if str(name or "").strip()}
        for slot in tuple(texture_slots or ()):
            if not isinstance(slot, Mapping):
                continue
            if (
                str(slot.get("slot_kind", "") or "").strip().lower() in wanted
                or str(slot.get("semantic_subtype", "") or "").strip().lower() in wanted
            ):
                stats = {
                    str(key): _safe_float(value, 0.0)
                    for key, value in tuple(slot.get("channel_stats", ()) or ())
                }
                if stats:
                    return stats
        return {}

    for material_class, tokens in (
        ("gold", ("gold", "gilded")),
        ("bronze", ("bronze",)),
        ("copper", ("copper",)),
        ("metal", ("metal", "steel", "iron", "gold", "gilded", "bronze", "copper", "blade", "armor", "armour")),
        ("painted_metal", ("paintedmetal", "painted_metal")),
        ("cloth", ("cloth", "fabric", "cape", "robe")),
        ("leather", ("leather", "hide")),
        ("wood", ("wood", "timber")),
        ("stone", ("stone", "rock")),
        ("glass_crystal", ("glass", "crystal", "gem")),
        ("emissive", ("emissive", "emission", "glow")),
        ("skin_organic", ("skin", "face", "body", "organic", "flesh")),
    ):
        if any(token in text for token in tokens):
            add(material_class, f"name_token:{material_class}")

    slots = {str(slot.get("slot_kind", "") or "").strip().lower() for slot in tuple(texture_slots or ()) if isinstance(slot, Mapping)}
    if slots.intersection({"metalness", "material", "specular"}):
        add("metal", "companion_metal_workflow_texture")
    metalness = max(0.0, min(1.0, _safe_float(scalar_map.get("metalness"), 0.0)))
    roughness = max(0.0, min(1.0, _safe_float(scalar_map.get("roughness"), 0.0)))
    if metalness >= 0.5:
        add("metal", f"metallic factor {metalness:.2f}")
    material_stats = slot_stats("material", "metallic_roughness")
    if material_stats.get("b_mean", 0.0) >= 0.45:
        add("metal", f"metallic-roughness B channel mean {material_stats.get('b_mean', 0.0):.2f}")
    metalness_stats = slot_stats("metalness", "metallic")
    if metalness_stats.get("luma_mean", 0.0) >= 0.45:
        add("metal", f"metalness texture mean {metalness_stats.get('luma_mean', 0.0):.2f}")
    rgb: tuple[float, float, float] = ()
    if len(tuple(color_factor or ())) >= 3:
        rgb = tuple(max(0.0, min(1.0, _safe_float(value, 0.0))) for value in tuple(color_factor)[:3])  # type: ignore[assignment]
    base_stats = slot_stats("base", "albedo")
    if (not rgb or all(abs(value - 1.0) <= 1e-6 for value in rgb)) and {"r_mean", "g_mean", "b_mean"} <= set(base_stats):
        rgb = (base_stats["r_mean"], base_stats["g_mean"], base_stats["b_mean"])
    metal_evidence = "metal" in evidence or metalness >= 0.35 or material_stats.get("b_mean", 0.0) >= 0.45
    if rgb and metal_evidence:
        r, g, b = rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", f"metallic yellow color {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", f"warm metallic color {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", f"bronze-like metallic color {r:.2f},{g:.2f},{b:.2f}")
    if rgb and metalness < 0.2:
        r, g, b = rgb
        spread = max(rgb) - min(rgb)
        if r >= 0.22 and g >= 0.12 and b <= 0.18 and r >= g >= b and roughness >= 0.55:
            add("leather", f"rough warm brown color {r:.2f},{g:.2f},{b:.2f}")
        if spread <= 0.12 and 0.20 <= max(rgb) <= 0.75 and roughness >= 0.45:
            add("stone", f"rough neutral color {r:.2f},{g:.2f},{b:.2f}")
    if "emissive" in slots:
        add("emissive", "companion_emissive_texture")
    emissive_intensity = _safe_float(scalar_map.get("emissive_intensity"), 0.0)
    if emissive_intensity > 0.0 or any(_safe_float(value, 0.0) > 0.003 for value in tuple(emissive_color or ())[:3]):
        add("emissive", "emissive scalar/color factor")
    if "opacity" in slots:
        add("glass_crystal", "companion_opacity_texture")
    alpha_values = tuple(_safe_float(value, 1.0) for value in tuple(vertex_alpha or ())[:2])
    if alpha_values and (alpha_values[0] < 0.98 or alpha_values[-1] < 0.98):
        add("glass_crystal", f"vertex alpha mean/min {alpha_values[0]:.2f}/{alpha_values[-1]:.2f}")
    alpha_stats = slot_stats("base", "opacity")
    if alpha_stats.get("a_min", 1.0) < 0.98 or alpha_stats.get("a_mean", 1.0) < 0.98:
        add(
            "glass_crystal",
            f"source alpha channel mean {alpha_stats.get('a_mean', 1.0):.2f} min {alpha_stats.get('a_min', 1.0):.2f}",
        )

    if not evidence:
        return (
            {
                "material_class": "unknown",
                "confidence": 0.1,
                "evidence": ("companion_textures_without_class_tokens",),
            },
        )
    rows = [
        {
            "material_class": material_class,
            "confidence": 0.6 if len(reasons) > 1 else 0.45,
            "evidence": tuple(reasons),
        }
        for material_class, reasons in evidence.items()
    ]
    return tuple(sorted(rows, key=lambda item: (-float(item["confidence"]), str(item["material_class"]))))


def _texture_image_facts(path: Path) -> tuple[tuple[int, int], tuple[tuple[str, float], ...]]:
    try:
        if path.suffix.lower() == ".dds":
            return _dds_image_facts(path), _decoded_image_channel_stats(path)
        from PIL import Image

        with Image.open(path) as image:
            resolution = (int(image.width), int(image.height))
            return resolution, _image_channel_stats(image)
    except Exception:
        return (), ()


def _zip_member_texture_facts(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
) -> tuple[tuple[int, int], tuple[tuple[str, float], ...]]:
    size = int(getattr(member, "file_size", 0) or 0)
    if size <= 0 or size > _AUDIT_TEXTURE_FACT_MAX_IMAGE_BYTES:
        return (), ()
    try:
        with archive.open(member, "r") as stream:
            return _texture_image_facts_from_bytes(member.filename, stream.read())
    except Exception:
        return (), ()


def _texture_image_facts_from_bytes(
    name: str,
    payload: bytes,
) -> tuple[tuple[int, int], tuple[tuple[str, float], ...]]:
    suffix = PurePosixPath(str(name or "")).suffix.lower()
    try:
        if suffix == ".dds":
            return _dds_image_facts_from_bytes(payload), _decoded_image_channel_stats_from_bytes(payload)
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            resolution = (int(image.width), int(image.height))
            return resolution, _image_channel_stats(image)
    except Exception:
        return (), ()


def _decoded_image_channel_stats(path: Path) -> tuple[tuple[str, float], ...]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return _image_channel_stats(image)
    except Exception:
        return ()


def _decoded_image_channel_stats_from_bytes(payload: bytes) -> tuple[tuple[str, float], ...]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            return _image_channel_stats(image)
    except Exception:
        return ()


def _image_channel_stats(image: object) -> tuple[tuple[str, float], ...]:
    try:
        from PIL import ImageStat

        rgba = image.convert("RGBA")  # type: ignore[attr-defined]
        if max(rgba.size or (0, 0)) > 64:
            rgba.thumbnail((64, 64))
        stat = ImageStat.Stat(rgba)
        means = [max(0.0, min(1.0, float(value) / 255.0)) for value in stat.mean[:4]]
        extrema = rgba.getextrema()
        alpha_min = max(0.0, min(1.0, float(extrema[3][0]) / 255.0))
        alpha_max = max(0.0, min(1.0, float(extrema[3][1]) / 255.0))
        luma = max(0.0, min(1.0, 0.2126 * means[0] + 0.7152 * means[1] + 0.0722 * means[2]))
        return (
            ("r_mean", round(means[0], 4)),
            ("g_mean", round(means[1], 4)),
            ("b_mean", round(means[2], 4)),
            ("a_mean", round(means[3], 4)),
            ("a_min", round(alpha_min, 4)),
            ("a_max", round(alpha_max, 4)),
            ("luma_mean", round(luma, 4)),
        )
    except Exception:
        return ()


def _dds_image_facts(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as handle:
            header = handle.read(128)
    except OSError:
        return ()
    if len(header) < 20 or header[:4] != b"DDS ":
        return ()
    height = int.from_bytes(header[12:16], "little", signed=False)
    width = int.from_bytes(header[16:20], "little", signed=False)
    return (width, height) if width > 0 and height > 0 else ()


def _dds_image_facts_from_bytes(payload: bytes) -> tuple[int, int]:
    header = bytes(payload or b"")[:128]
    if len(header) < 20 or header[:4] != b"DDS ":
        return ()
    height = int.from_bytes(header[12:16], "little", signed=False)
    width = int.from_bytes(header[16:20], "little", signed=False)
    return (width, height) if width > 0 and height > 0 else ()


def _channel_stats_evidence(channel_stats: Sequence[tuple[str, float]]) -> str:
    stats = {str(key): float(value) for key, value in tuple(channel_stats or ())}
    if not stats:
        return ""
    return (
        "channels:"
        f"r={stats.get('r_mean', 0.0):.2f},"
        f"g={stats.get('g_mean', 0.0):.2f},"
        f"b={stats.get('b_mean', 0.0):.2f},"
        f"a={stats.get('a_mean', 0.0):.2f}"
    )


def _external_catalogue_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    status_counts = Counter(str(row.get("audit_status", "") or "unknown") for row in rows)
    slot_counts: Counter[str] = Counter()
    workflow_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    format_counts: Counter[str] = Counter()
    color_space_counts: Counter[str] = Counter()
    detected_channel_counts: Counter[str] = Counter()
    missing_channel_counts: Counter[str] = Counter()
    channel_diagnostic_counts: Counter[str] = Counter()
    textures_with_resolution = 0
    textures_missing_resolution = 0
    textures_with_channel_stats = 0
    textures_missing_channel_stats = 0
    diagnostic_only_texture_slots = 0
    source_channel_profile_rows = 0
    material_section_rows = 0
    section_vertex_count = 0
    section_face_count = 0
    sections_missing_uvs = 0
    sections_missing_normals = 0
    skinned_sections = 0
    multi_texcoord_sections = 0
    materials_missing_alpha_diagnostics = 0
    materials_missing_emissive_diagnostics = 0
    materials_missing_roughness_metalness_diagnostics = 0
    alpha_materials = 0
    emissive_materials = 0
    fbx_metadata_inferred_models = 0
    missing_texture_refs = 0
    ambiguous_texture_refs = 0
    unresolved_texture_candidates = 0
    warning_count = 0
    zip_content_audit_skipped_by_limit = 0
    for row in rows:
        warning_count += len(tuple(row.get("warnings", ()) or ()))
        missing_texture_refs += len(tuple(row.get("missing_texture_refs", ()) or ()))
        ambiguous_texture_refs += len(tuple(row.get("ambiguous_texture_refs", ()) or ()))
        unresolved_texture_candidates += len(tuple(row.get("unresolved_texture_candidates", ()) or ()))
        if bool(row.get("zip_content_audit_skipped")):
            zip_content_audit_skipped_by_limit += 1
        row_has_fbx_metadata = False
        for material in tuple(row.get("material_inventory", ()) or ()):
            if not isinstance(material, Mapping):
                continue
            workflow = str(material.get("pbr_workflow", "") or "").strip()
            if workflow:
                workflow_counts[workflow] += 1
            detected_channels = {
                str(channel or "").strip().lower()
                for channel in tuple(material.get("detected_channels", ()) or ())
                if str(channel or "").strip()
            }
            missing_channels = {
                str(channel or "").strip().lower()
                for channel in tuple(material.get("missing_channels", ()) or ())
                if str(channel or "").strip()
            }
            if isinstance(material.get("channel_profile"), Mapping):
                source_channel_profile_rows += 1
            for section in tuple(material.get("sections", ()) or ()):
                if not isinstance(section, Mapping):
                    continue
                material_section_rows += 1
                section_vertex_count += _safe_int(section.get("vertex_count"), 0)
                section_face_count += _safe_int(section.get("face_count"), 0)
                if not bool(section.get("has_uvs")):
                    sections_missing_uvs += 1
                if not bool(section.get("has_normals")):
                    sections_missing_normals += 1
                if bool(section.get("has_skinning")):
                    skinned_sections += 1
                if len(tuple(section.get("texture_texcoord_sets", ()) or ())) > 1:
                    multi_texcoord_sections += 1
            detected_channel_counts.update(detected_channels)
            missing_channel_counts.update(missing_channels)
            channel_diagnostic_codes: set[str] = set()
            for diagnostic in tuple(material.get("channel_diagnostics", ()) or ()):
                if isinstance(diagnostic, Mapping):
                    code = str(diagnostic.get("code", "") or "").strip()
                    if code:
                        channel_diagnostic_codes.add(code)
                        channel_diagnostic_counts[code] += 1
            alpha_relevant = str(material.get("alpha_mode", "") or "").strip().lower() in {
                "alpha",
                "blend",
                "coverage",
                "cutout",
                "mask",
                "transparent",
            } or bool({"alpha", "opacity"}.intersection(detected_channels | missing_channels))
            if alpha_relevant and not _material_channel_evidence_exists(
                detected_channels,
                missing_channels,
                channel_diagnostic_codes,
                ("alpha", "opacity"),
            ):
                materials_missing_alpha_diagnostics += 1
            if not _material_channel_evidence_exists(
                detected_channels,
                missing_channels,
                channel_diagnostic_codes,
                ("emissive",),
            ):
                materials_missing_emissive_diagnostics += 1
            if not all(
                _material_channel_evidence_exists(
                    detected_channels,
                    missing_channels,
                    channel_diagnostic_codes,
                    (channel,),
                )
                for channel in ("roughness", "metalness")
            ):
                materials_missing_roughness_metalness_diagnostics += 1
            alpha_material = str(material.get("alpha_mode", "") or "").strip().lower() in {
                "alpha",
                "blend",
                "coverage",
                "cutout",
                "mask",
                "transparent",
            }
            emissive_material = any(
                _safe_float(component, 0.0) > 0.0 for component in tuple(material.get("emissive_color", ()) or ())
            )
            for slot in tuple(material.get("texture_slots", ()) or ()):
                if isinstance(slot, Mapping):
                    slot_name = str(slot.get("slot_kind", "") or "").strip()
                    if slot_name:
                        slot_counts[slot_name] += 1
                    image_format = str(slot.get("image_format", "") or "").strip().lower()
                    if image_format:
                        format_counts[image_format] += 1
                    color_space = str(slot.get("color_space", "") or "").strip().lower()
                    if color_space:
                        color_space_counts[color_space] += 1
                    resolution = tuple(slot.get("resolution", ()) or ())
                    if len(resolution) >= 2 and _safe_int(resolution[0], 0) > 0 and _safe_int(resolution[1], 0) > 0:
                        textures_with_resolution += 1
                    else:
                        textures_missing_resolution += 1
                    if bool(slot.get("diagnostic_only")):
                        diagnostic_only_texture_slots += 1
                    if str(slot.get("source", "") or "") in {"fbx_ascii", "fbx_binary"}:
                        row_has_fbx_metadata = True
                    if slot_name.strip().lower() in {"alpha", "opacity"}:
                        alpha_material = True
                    if slot_name.strip().lower() == "emissive":
                        emissive_material = True
                    channel_stats = dict(tuple(slot.get("channel_stats", ()) or ()))
                    if channel_stats:
                        textures_with_channel_stats += 1
                    else:
                        textures_missing_channel_stats += 1
                    alpha_min = _safe_float(channel_stats.get("a_min"), 1.0)
                    alpha_max = _safe_float(channel_stats.get("a_max"), 1.0)
                    if alpha_min < 0.999 or alpha_max < 0.999:
                        alpha_material = True
            for item in tuple(material.get("material_classes", ()) or ()):
                if isinstance(item, Mapping):
                    class_name = str(item.get("material_class", "") or "").strip()
                    if class_name:
                        class_counts[class_name] += 1
                    if class_name in {"emissive"}:
                        emissive_material = True
                    if class_name in {"glass_crystal", "glass", "crystal"}:
                        alpha_material = True
            if alpha_material:
                alpha_materials += 1
            if emissive_material:
                emissive_materials += 1
        if row_has_fbx_metadata:
            fbx_metadata_inferred_models += 1
    return {
        "total_models": len(rows),
        "audited_models": status_counts.get("audited", 0),
        "zip_audited_models": status_counts.get("archive_audited", 0),
        "archive_models": status_counts.get("archive_indexed", 0),
        "metadata_inferred_models": status_counts.get("browsable_material_inferred", 0),
        "fbx_metadata_inferred_models": fbx_metadata_inferred_models,
        "zip_content_audit_skipped_by_limit": zip_content_audit_skipped_by_limit,
        "unsupported_models": status_counts.get("browsable_unsupported", 0),
        "failed_models": status_counts.get("failed", 0),
        "missing_texture_refs": missing_texture_refs,
        "ambiguous_texture_refs": ambiguous_texture_refs,
        "unresolved_texture_candidates": unresolved_texture_candidates,
        "warning_count": warning_count,
        "status_counts": dict(status_counts),
        "texture_slot_counts": dict(sorted(slot_counts.items())),
        "pbr_workflow_counts": dict(sorted(workflow_counts.items())),
        "material_class_counts": dict(sorted(class_counts.items())),
        "source_channel_profile_rows": source_channel_profile_rows,
        "material_section_rows": material_section_rows,
        "section_vertex_count": section_vertex_count,
        "section_face_count": section_face_count,
        "sections_missing_uvs": sections_missing_uvs,
        "sections_missing_normals": sections_missing_normals,
        "skinned_sections": skinned_sections,
        "multi_texcoord_sections": multi_texcoord_sections,
        "source_detected_channel_counts": dict(sorted(detected_channel_counts.items())),
        "source_missing_channel_counts": dict(sorted(missing_channel_counts.items())),
        "source_channel_diagnostic_counts": dict(sorted(channel_diagnostic_counts.items())),
        "materials_missing_alpha_diagnostics": materials_missing_alpha_diagnostics,
        "materials_missing_emissive_diagnostics": materials_missing_emissive_diagnostics,
        "materials_missing_roughness_metalness_diagnostics": materials_missing_roughness_metalness_diagnostics,
        "texture_format_counts": dict(sorted(format_counts.items())),
        "texture_color_space_counts": dict(sorted(color_space_counts.items())),
        "textures_with_resolution": textures_with_resolution,
        "textures_missing_resolution": textures_missing_resolution,
        "textures_with_channel_stats": textures_with_channel_stats,
        "textures_missing_channel_stats": textures_missing_channel_stats,
        "diagnostic_only_texture_slots": diagnostic_only_texture_slots,
        "alpha_materials": alpha_materials,
        "emissive_materials": emissive_materials,
    }


def _material_channel_evidence_exists(
    detected_channels: set[str],
    missing_channels: set[str],
    diagnostic_codes: set[str],
    channels: Sequence[str],
) -> bool:
    wanted = {str(channel or "").strip().lower() for channel in tuple(channels or ()) if str(channel or "").strip()}
    if wanted.intersection(detected_channels | missing_channels):
        return True
    for channel in wanted:
        if f"{channel}_scalar" in detected_channels:
            return True
        if channel in {"alpha", "opacity"} and any(
            "alpha" in code or "opacity" in code for code in diagnostic_codes
        ):
            return True
        if any(code == f"source_missing_{channel}" or code.endswith(f"_{channel}") for code in diagnostic_codes):
            return True
    return False


def _dedupe_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if str(value).strip()}, key=str.casefold))


def _dedupe_preserve_order(values: Iterable[object]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return tuple(output)


__all__ = [
    "EXTERNAL_MODEL_AUDIT_EXTENSIONS",
    "build_external_model_audit_catalogue",
    "write_external_model_audit_catalogue",
]
