"""Final package preview package scanning, staging, and build orchestration."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.atomic_file import atomic_publish_directory, atomic_write_bytes, atomic_write_text
from cdmw.core.archive_modding_constants import (
    ARCHIVE_MESH_EXTENSIONS,
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
)
from cdmw.core.archive_mesh_types import (
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings


def _package_spec_kind_for_path(path_value: object) -> str:
    suffix = PurePosixPath(str(path_value or "").replace("\\", "/")).suffix.lower()
    if suffix in ARCHIVE_MESH_EXTENSIONS:
        return "mesh"
    if suffix == ".dds":
        return "texture_generated"
    if suffix in MESH_IMPORT_SIDECAR_EXTENSIONS:
        return "sidecar_generated"
    if suffix in MESH_IMPORT_COMPANION_EXTENSIONS:
        return "companion"
    return "file"


def _is_final_preview_payload_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_MESH_EXTENSIONS:
        return True
    if suffix == ".dds":
        return True
    if suffix in MESH_IMPORT_SIDECAR_EXTENSIONS:
        return True
    if suffix in MESH_IMPORT_COMPANION_EXTENSIONS:
        return True
    return False


def _is_mesh_payload_spec(spec: MeshImportSupplementalFileSpec) -> bool:
    kind = str(getattr(spec, "kind", "") or "").strip().lower()
    target_suffix = PurePosixPath(str(getattr(spec, "target_path", "") or "")).suffix.lower()
    source_suffix = getattr(getattr(spec, "source_path", None), "suffix", "").lower()
    return kind == "mesh" or target_suffix in ARCHIVE_MESH_EXTENSIONS or source_suffix in ARCHIVE_MESH_EXTENSIONS


def _spec_payload_raw_bytes(spec: MeshImportSupplementalFileSpec) -> bytes:
    payload_data = bytes(getattr(spec, "payload_data", b"") or b"")
    if payload_data:
        return payload_data
    source_path = getattr(spec, "source_path", None)
    if isinstance(source_path, Path):
        try:
            resolved = source_path.expanduser().resolve()
            if resolved.is_file():
                return resolved.read_bytes()
        except OSError:
            return b""
    return b""


def _package_rebuilt_mesh_data(
    specs: Sequence[MeshImportSupplementalFileSpec],
    preview_result: MeshImportPreviewResult,
    export_options: object = None,
) -> bytes:
    from .final_package_preview import _final_payload_path, _normalize_final_path

    parsed_path = str(getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").replace("\\", "/").strip()
    model_path = str(getattr(getattr(preview_result, "preview_model", None), "path", "") or "").replace("\\", "/").strip()
    expected_keys = {
        _normalize_final_path(_final_payload_path(path, export_options))
        for path in (parsed_path, model_path)
        if path
    }
    mesh_specs = [spec for spec in tuple(specs or ()) if isinstance(spec, MeshImportSupplementalFileSpec) and _is_mesh_payload_spec(spec)]
    if not mesh_specs:
        return b""
    for spec in mesh_specs:
        target_key = _normalize_final_path(str(getattr(spec, "target_path", "") or ""))
        if target_key and target_key in expected_keys:
            return _spec_payload_raw_bytes(spec)
    if len(mesh_specs) == 1:
        return _spec_payload_raw_bytes(mesh_specs[0])
    return b""


def _package_specs_from_manifest(package_root: Path, manifest_payload: Mapping[str, object]) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    from .final_package_preview import _display_path

    files_root = str(manifest_payload.get("files_root") or manifest_payload.get("files_dir") or "").strip().strip("/\\")
    if files_root in {"", "."}:
        payload_root = package_root
    else:
        payload_root = package_root / files_root
    specs: List[MeshImportSupplementalFileSpec] = []
    for row in tuple(manifest_payload.get("files", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        target_path = _display_path(row.get("path"))
        if not target_path:
            continue
        source_path = payload_root.joinpath(*PurePosixPath(target_path).parts)
        if not source_path.is_file() or not _is_final_preview_payload_file(source_path):
            continue
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=source_path,
                target_path=target_path,
                kind=_package_spec_kind_for_path(target_path),
                used_for_preview=True,
                payload_data=b"",
                note="Scanned from exact final loose package manifest.",
            )
        )
    return tuple(specs)


def build_final_package_specs_from_package_root(package_root: Path) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    from .final_package_preview import _normalize_final_path

    """Return preview specs from files that actually exist in a written loose package."""

    root = package_root.expanduser().resolve()
    if not root.is_dir():
        return ()
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest_payload = {}
        if isinstance(manifest_payload, Mapping):
            manifest_specs = _package_specs_from_manifest(root, manifest_payload)
            if manifest_specs:
                return manifest_specs

    candidate_roots: List[Tuple[Path, PurePosixPath]] = []
    files_root = root / "files"
    if files_root.is_dir():
        candidate_roots.append((files_root, PurePosixPath()))
    candidate_roots.append((root, PurePosixPath()))
    specs_by_key: Dict[str, MeshImportSupplementalFileSpec] = {}
    ignored_names = {
        ".no_encrypt",
        "manifest.json",
        "mod.json",
        "modinfo.json",
        "info.json",
        "readme.txt",
        "cdmw_texture_resolution_manifest.json",
        "cdmw_material_authority_report.json",
        "cdmw_material_authority_report_check.json",
    }
    for physical_root, virtual_prefix in candidate_roots:
        try:
            files = tuple(path for path in physical_root.rglob("*") if path.is_file())
        except OSError:
            continue
        for path in files:
            if path.name.lower() in ignored_names or not _is_final_preview_payload_file(path):
                continue
            try:
                relative = path.relative_to(physical_root)
            except ValueError:
                continue
            target_path = PurePosixPath(virtual_prefix, *relative.parts).as_posix()
            normalized_target = _normalize_final_path(target_path)
            if not normalized_target or normalized_target in specs_by_key:
                continue
            specs_by_key[normalized_target] = MeshImportSupplementalFileSpec(
                source_path=path,
                target_path=target_path,
                kind=_package_spec_kind_for_path(target_path),
                used_for_preview=True,
                payload_data=b"",
                note="Scanned from exact final loose package files.",
            )
    return tuple(specs_by_key[key] for key in sorted(specs_by_key))


def stage_final_package_preview_payloads(
    preview_result: MeshImportPreviewResult,
    *,
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
    export_options: object = None,
    label: str = "test_build_preview",
) -> Path:
    from .final_package_preview import _final_payload_path

    """Write an in-memory final package candidate to the app temp cache and return its package root."""

    hasher = hashlib.sha1()
    hasher.update(bytes(getattr(preview_result, "rebuilt_data", b"") or b""))
    for spec in tuple(supplemental_file_specs or ()):
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        hasher.update(str(getattr(spec, "target_path", "") or "").encode("utf-8", errors="ignore"))
        payload = bytes(getattr(spec, "payload_data", b"") or b"")
        if payload:
            hasher.update(payload[:4096])
            hasher.update(str(len(payload)).encode("ascii"))
        else:
            source_path = getattr(spec, "source_path", None)
            if isinstance(source_path, Path):
                hasher.update(source_path.as_posix().encode("utf-8", errors="ignore"))
    digest = hasher.hexdigest()[:16]
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(label or "test_build_preview")).strip("._") or "test_build_preview"
    package_root = app_temp_cache_path("final_package_preview_stage") / f"{safe_label}_{digest}"
    package_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{package_root.name}.", suffix=".tmp", dir=package_root.parent))
    try:
        manifest_files: List[dict] = []
        parsed_path = str(getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").strip()
        rebuilt_data = bytes(getattr(preview_result, "rebuilt_data", b"") or b"")
        if parsed_path and rebuilt_data:
            target_path = _final_payload_path(parsed_path, export_options)
            if target_path:
                output_path = staging_root.joinpath(*PurePosixPath(target_path).parts)
                atomic_write_bytes(output_path, rebuilt_data)
                manifest_files.append({"path": target_path, "format": output_path.suffix.lstrip(".").lower()})

        seen: set[str] = {str(row["path"]).lower() for row in manifest_files}
        for spec in tuple(supplemental_file_specs or ()):
            if not isinstance(spec, MeshImportSupplementalFileSpec):
                continue
            target_path = _final_payload_path(str(getattr(spec, "target_path", "") or ""), export_options)
            if not target_path:
                continue
            key = target_path.lower()
            if key in seen:
                continue
            payload = _spec_payload_raw_bytes(spec)
            if not payload:
                continue
            output_path = staging_root.joinpath(*PurePosixPath(target_path).parts)
            atomic_write_bytes(output_path, payload)
            manifest_files.append({"path": target_path, "format": output_path.suffix.lstrip(".").lower()})
            seen.add(key)

        atomic_write_text(
            staging_root / "manifest.json",
            json.dumps(
                {
                    "format": "v1",
                    "kind": "mesh_loose_mod_preview_stage",
                    "files_root": ".",
                    "files": manifest_files,
                },
                indent=2,
            ),
        )
        atomic_publish_directory(staging_root, package_root)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    request_app_temp_cache_prune()
    return package_root


def build_final_package_preview(
    preview_result: MeshImportPreviewResult,
    *,
    supplemental_file_specs: Optional[Sequence[MeshImportSupplementalFileSpec]] = None,
    source_path: str | Path = "",
    export_options: object = None,
    texconv_path: Optional[Path] = None,
    original_dds_resolver: Optional[Callable[[str], Optional[Path]]] = None,
    original_dds_basename_resolver: Optional[Callable[[str], Sequence[Path]]] = None,
    package_root: Optional[Path] = None,
    require_source_owned_colors: bool = False,
    strict_source_owned_material_contract: bool = False,
    allow_inherited_layer_color_bindings: bool = False,
    material_authority_contract: str = "",
    render_settings: object = None,
) -> FinalPackagePreviewResult:
    from .final_package_preview import (
        FINAL_PREVIEW_ADVANCED_SHADER_ONLY,
        FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC,
        FINAL_PREVIEW_BINDING_GENERATED,
        FINAL_PREVIEW_BINDING_MISSING,
        FINAL_PREVIEW_BINDING_ORIGINAL,
        FINAL_PREVIEW_DECODE_FAILED,
        FINAL_PREVIEW_MISSING_BASE,
        FINAL_PREVIEW_MISSING_DDS,
        FINAL_PREVIEW_READY,
        FINAL_PREVIEW_SUPPORT_MAPS_ONLY,
        SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS,
        FinalPackageBindingRow,
        FinalPackageMaterialStatus,
        FinalPackagePreviewResult,
        TextureResolutionManifest,
        _FinalPayload,
        _FinalTextureBinding,
        _assign_row_to_meshes,
        _assign_unmatched_visible_textures_by_order,
        _binding_material_name,
        _binding_row_is_preserved_layer_color,
        _binding_row_is_relief_support_only,
        _binding_row_is_source_visible_authority,
        _build_material_authority_report,
        _build_texture_resolution_manifest,
        _candidate_mesh_indices,
        _clear_texture_slots,
        _dedupe,
        _fallback_assignment_detail,
        _final_payload_path,
        _is_dds_spec,
        _is_sidecar_spec,
        _is_stock_or_shared_texture_path,
        _looks_like_normal_source_path,
        _material_export_safety_blockers_for_specs,
        _material_authority_source_material_rows_for_report,
        _material_key,
        _material_label_for_mesh,
        _normalize_final_path,
        _pac_xml_normal_binding_warning,
        _pac_runtime_abi_preflight_errors,
        _pac_xml_material_shader_name_errors,
        _pac_xml_material_wrapper_structure_errors,
        _pac_xml_submesh_resource_idbase_errors,
        _pac_xml_submesh_resource_order_errors,
        _pac_xml_submesh_resource_wrapper_names,
        _preview_result_texture_contract_warnings,
        _preview_texture_path_for_original,
        _preview_texture_path_for_payload,
        _rebuilt_preview_model,
        _rows_for_source_owned_contract,
        _slot_role,
        _source_expected_support_roles_for_contract,
        _source_material_rows_by_key,
        _source_owned_material_binding_contract,
        _source_owned_section_source_material_names,
        _spec_payload_text,
        _visible_preview_texture_count,
    )

    """Build the texture-authoritative mesh preview for the package payloads that would be exported."""

    warnings: List[str] = []
    authority_contract = re.sub(r"[^a-z0-9_]+", "_", str(material_authority_contract or "").strip().lower()).strip("_")
    runtime_xml_preserve_contract = authority_contract == "runtime_xml_preserve" or bool(
        allow_inherited_layer_color_bindings
    )
    true_source_authority_contract = authority_contract.startswith("true_source_authority") or bool(
        strict_source_owned_material_contract
    )
    relief_support_allowed = "relief_support" in authority_contract
    detail_mask_material_allowed = "detail_mask" in authority_contract
    allow_inherited_layer_color_bindings = bool(runtime_xml_preserve_contract)
    strict_source_owned_material_contract = bool(true_source_authority_contract)
    source_owned_binding_contract_enabled = bool(require_source_owned_colors)
    package_root_text = ""
    if package_root is not None:
        try:
            resolved_package_root = package_root.expanduser().resolve()
            package_root_text = resolved_package_root.as_posix()
        except Exception:
            resolved_package_root = package_root
            package_root_text = str(package_root)
        package_specs = build_final_package_specs_from_package_root(resolved_package_root)
        if package_specs:
            specs = package_specs
        else:
            specs = tuple(supplemental_file_specs if supplemental_file_specs is not None else getattr(preview_result, "supplemental_file_specs", ()) or ())
            warnings.append(f"Final package preview could not scan package payloads from {package_root_text}; using in-memory payload specs.")
    else:
        specs = tuple(supplemental_file_specs if supplemental_file_specs is not None else getattr(preview_result, "supplemental_file_specs", ()) or ())
    source_path_text = str(source_path or "").replace("\\", "/").strip()
    if not source_path_text:
        source_path_text = str(getattr(getattr(preview_result, "preview_model", None), "path", "") or getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").replace("\\", "/")
    source_materials_for_report = _material_authority_source_material_rows_for_report(preview_result, source_path_text)

    effective_preview_result = preview_result
    package_mesh_data = _package_rebuilt_mesh_data(specs, preview_result, export_options)
    if package_mesh_data:
        effective_preview_result = dataclasses.replace(preview_result, rebuilt_data=package_mesh_data)

    preview_model = _rebuilt_preview_model(effective_preview_result, warnings)
    _clear_texture_slots(preview_model)
    warnings.extend(_preview_result_texture_contract_warnings(effective_preview_result))

    sidecars: Dict[str, Tuple[str, MeshImportSupplementalFileSpec]] = {}
    dds_by_path: Dict[str, _FinalPayload] = {}
    dds_by_basename: Dict[str, List[_FinalPayload]] = {}
    generated_sidecar_count = 0
    for spec in specs:
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        target_path = str(getattr(spec, "target_path", "") or "").strip()
        if not target_path:
            continue
        final_path = _final_payload_path(target_path, export_options)
        if not final_path:
            continue
        final_key = _normalize_final_path(final_path)
        if _is_sidecar_spec(spec):
            text = _spec_payload_text(spec)
            if text.strip():
                sidecars[final_key] = (final_path, spec)
                if str(getattr(spec, "kind", "") or "").strip().lower() == "sidecar_generated":
                    generated_sidecar_count += 1
            continue
        if _is_dds_spec(spec):
            payload_data = bytes(getattr(spec, "payload_data", b"") or b"")
            source_path = getattr(spec, "source_path", Path())
            resolved_source = source_path.expanduser().resolve() if isinstance(source_path, Path) else Path()
            if not payload_data and not resolved_source.is_file():
                continue
            payload = _FinalPayload(
                final_path=final_path,
                basename=PurePosixPath(final_path).name.lower(),
                source_path=resolved_source,
                payload_data=payload_data,
                kind=str(getattr(spec, "kind", "") or ""),
                note=str(getattr(spec, "note", "") or ""),
            )
            dds_by_path.setdefault(final_key, payload)
            if payload.basename:
                dds_by_basename.setdefault(payload.basename, []).append(payload)
            if _is_stock_or_shared_texture_path(final_path):
                warnings.append(
                    f"Texture contract warning: generated/copied payload overrides stock/shared shader texture {final_path}. "
                    "This can tint the model, add grime/speckles, or affect shared material layers."
                )

    binding_rows: List[FinalPackageBindingRow] = []
    missing_paths: List[str] = []
    rows_by_material: Dict[str, List[FinalPackageBindingRow]] = {}
    material_display_by_key: Dict[str, str] = {}
    mesh_indices_by_material: Dict[str, List[int]] = {}
    for index, mesh in enumerate(getattr(preview_model, "meshes", []) or []):
        material_name = _material_label_for_mesh(mesh, index)
        key = _material_key(material_name) or f"mesh{index}"
        material_display_by_key.setdefault(key, material_name)
        mesh_indices_by_material.setdefault(key, []).append(index)

    binding_sources: List[Tuple[str, object]] = []
    sidecar_structure_errors: List[str] = []
    sidecar_submesh_resource_names: List[str] = []
    for sidecar_path, spec in sidecars.values():
        sidecar_text = _spec_payload_text(spec)
        if require_source_owned_colors:
            sidecar_structure_errors.extend(_pac_xml_material_wrapper_structure_errors(sidecar_text, sidecar_path))
            sidecar_structure_errors.extend(_pac_xml_material_shader_name_errors(sidecar_text, sidecar_path))
            sidecar_structure_errors.extend(_pac_xml_submesh_resource_idbase_errors(sidecar_text, sidecar_path))
            sidecar_submesh_resource_names.extend(_pac_xml_submesh_resource_wrapper_names(sidecar_text, sidecar_path))
        for binding in parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path):
            binding_sources.append((sidecar_path, binding))
    if not binding_sources:
        for reference in tuple(getattr(preview_result, "texture_references", ()) or ()):
            if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
                continue
            texture_path = str(
                getattr(reference, "resolved_archive_path", "")
                or getattr(reference, "reference_name", "")
                or ""
            ).replace("\\", "/").strip()
            if not texture_path.lower().endswith(".dds"):
                continue
            binding_sources.append(
                (
                    "kept original sidecar bindings",
                    _FinalTextureBinding(
                        texture_path=texture_path,
                        parameter_name=str(getattr(reference, "sidecar_parameter_name", "") or ""),
                        material_name=str(getattr(reference, "material_name", "") or ""),
                        part_name=str(getattr(reference, "part_name", "") or ""),
                        submesh_name=str(getattr(reference, "material_name", "") or ""),
                    ),
                )
            )

    kept_original_material_keys = {
        _material_key(_binding_material_name(binding))
        for sidecar_path, binding in binding_sources
        if str(sidecar_path or "").strip().lower() == "kept original sidecar bindings"
        and _material_key(_binding_material_name(binding))
    }
    conservative_kept_original_binding_fallback = bool(not sidecars and len(kept_original_material_keys) > 1)

    for sidecar_path, binding in binding_sources:
            texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            if not texture_path.lower().endswith(".dds"):
                continue
            parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
            kept_original_binding = str(sidecar_path or "").strip().lower() == "kept original sidecar bindings"
            normal_warning = _pac_xml_normal_binding_warning(
                parameter_name, texture_path, kept_original=kept_original_binding
            )
            if normal_warning:
                warnings.append(normal_warning)
            role_key, role_label, visualized = _slot_role(parameter_name, texture_path)
            final_texture_path = _final_payload_path(texture_path, export_options)
            final_texture_key = _normalize_final_path(final_texture_path)
            texture_basename = PurePosixPath(final_texture_path or texture_path).name.lower()
            payload = dds_by_path.get(final_texture_key)
            if payload is not None and role_key == "base" and _looks_like_normal_source_path(payload.source_path):
                warnings.append(
                    f"Texture contract warning: base/overlay color slot {texture_path} resolves to a generated DDS "
                    f"from normal-map source {payload.source_path.name}."
                )
            confidence = "exact"
            binding_source = FINAL_PREVIEW_BINDING_MISSING
            detail = ""
            if payload is None:
                original_path: Optional[Path] = None
                if original_dds_resolver is not None:
                    try:
                        original_path = original_dds_resolver(final_texture_path or texture_path)
                    except Exception as exc:
                        warnings.append(f"Original DDS resolver failed for {final_texture_path or texture_path}: {exc}")
                if isinstance(original_path, Path) and original_path.expanduser().is_file():
                    preview_texture_path, decode_error = _preview_texture_path_for_original(original_path, texconv_path=texconv_path)
                    if decode_error:
                        status = FINAL_PREVIEW_DECODE_FAILED
                        detail = f"Original archive DDS exists at the exact final sidecar path but could not be decoded for preview: {decode_error}"
                        warnings.append(detail)
                    else:
                        status = FINAL_PREVIEW_READY
                        detail = "Resolved to the kept original archive DDS at the exact final sidecar path."
                    binding_source = FINAL_PREVIEW_BINDING_ORIGINAL
                    resolved_texture_path = final_texture_path or texture_path
                else:
                    fallback_payloads = list(dds_by_basename.get(texture_basename, ()))
                    fallback_original_paths: Sequence[Path] = ()
                    if original_dds_basename_resolver is not None and texture_basename:
                        try:
                            fallback_original_paths = tuple(original_dds_basename_resolver(texture_basename) or ())
                        except Exception:
                            fallback_original_paths = ()
                    if fallback_payloads or fallback_original_paths:
                        confidence = "basename"
                        binding_source = FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC
                        detail = (
                            "A DDS with the same basename exists, but the final sidecar path did not match exactly; "
                            "basename fallback is diagnostic only and is not treated as texture-ready."
                        )
                    else:
                        detail = "No generated/copied or kept-original DDS exists at the final sidecar texture path."
                    status = FINAL_PREVIEW_MISSING_DDS
                    missing_paths.append(final_texture_path or texture_path)
                    resolved_texture_path = ""
                    preview_texture_path = ""
            else:
                preview_texture_path, decode_error = _preview_texture_path_for_payload(payload, texconv_path=texconv_path)
                if decode_error:
                    status = FINAL_PREVIEW_DECODE_FAILED
                    detail = f"Generated/copied DDS exists but could not be decoded for preview: {decode_error}"
                    warnings.append(detail)
                    resolved_texture_path = payload.final_path
                    binding_source = FINAL_PREVIEW_BINDING_GENERATED
                else:
                    status = FINAL_PREVIEW_READY
                    detail = "Resolved to a generated/copied DDS payload at the exact final sidecar path."
                    resolved_texture_path = payload.final_path
                    binding_source = FINAL_PREVIEW_BINDING_GENERATED

            binding_material = _binding_material_name(binding)
            binding_key = _material_key(binding_material)
            mesh_indices = _candidate_mesh_indices(
                preview_model,
                binding,
                allow_single_mesh_fallback=not (conservative_kept_original_binding_fallback and kept_original_binding),
            )
            if mesh_indices:
                for mesh_index in mesh_indices:
                    mesh = preview_model.meshes[mesh_index]
                    material_name = _material_label_for_mesh(mesh, mesh_index)
                    material_key = _material_key(material_name) or f"mesh{mesh_index}"
                    material_display_by_key.setdefault(material_key, material_name)
                    rows_by_material.setdefault(material_key, [])
                if status == FINAL_PREVIEW_READY and confidence == "exact" and visualized:
                    _assign_row_to_meshes(
                        preview_model,
                        mesh_indices,
                        role_key,
                        preview_texture_path,
                        PurePosixPath(resolved_texture_path or texture_path).name,
                        parameter_name=parameter_name,
                        texture_path=texture_path,
                    )
            else:
                material_key = binding_key or f"sidecar{len(rows_by_material)}"
                material_display_by_key.setdefault(material_key, binding_material)
                rows_by_material.setdefault(material_key, [])

            row = FinalPackageBindingRow(
                material_name=binding_material,
                part_name=str(getattr(binding, "part_name", "") or getattr(binding, "submesh_name", "") or "").strip(),
                role=role_label,
                parameter_name=parameter_name,
                sidecar_path=sidecar_path,
                texture_path=texture_path,
                resolved_texture_path=resolved_texture_path,
                status=status,
                confidence=confidence,
                binding_source=binding_source,
                detail=detail,
                preview_texture_path=preview_texture_path,
            )
            binding_rows.append(row)
            target_keys = []
            if mesh_indices:
                target_keys.extend(
                    _material_key(_material_label_for_mesh(preview_model.meshes[mesh_index], mesh_index)) or f"mesh{mesh_index}"
                    for mesh_index in mesh_indices
                )
            else:
                target_keys.append(binding_key or row.material_name.lower())
            for target_key in target_keys:
                rows_by_material.setdefault(target_key, []).append(row)

    referenced_dds_keys = {
        _normalize_final_path(_final_payload_path(str(row.texture_path or ""), export_options))
        for row in binding_rows
        if str(row.texture_path or "").strip()
    }
    orphan_payload_paths = [
        payload.final_path
        for key, payload in sorted(dds_by_path.items())
        if key not in referenced_dds_keys
        and "/ui/" not in payload.final_path.replace("\\", "/").lower()
        and not payload.final_path.replace("\\", "/").lower().startswith("ui/")
    ]
    if sidecars and orphan_payload_paths:
        warnings.append(
            "Texture contract warning: generated/copied DDS payloads not referenced by parsed material sidecar: "
            + ", ".join(orphan_payload_paths[:8])
            + (" ..." if len(orphan_payload_paths) > 8 else "")
        )

    fallback_assignment_count, fallback_assignment_details = _assign_unmatched_visible_textures_by_order(
        preview_model,
        binding_rows,
        exclude_kept_original_sidecar=conservative_kept_original_binding_fallback,
    )
    if fallback_assignment_count:
        warnings.append(
            "Final preview assigned visible textures by draw-order fallback for "
            f"{fallback_assignment_count:,} unmatched mesh batch(es). This is preview-only; material names did not match final sidecar bindings exactly."
            + _fallback_assignment_detail(fallback_assignment_details)
        )
    if conservative_kept_original_binding_fallback:
        warnings.append(
            "Final preview ignored unmatched kept-original sidecar material bindings because the rebuilt mesh has fewer visible draw sections than the original sidecar. "
            "This prevents deleted or empty original material wrappers from overriding the remaining visible mesh texture."
        )

    source_visible_texture_count = _visible_preview_texture_count(getattr(preview_result, "preview_model", None))
    final_visible_texture_count = _visible_preview_texture_count(preview_model)
    if source_visible_texture_count > final_visible_texture_count:
        warnings.append(
            "Final preview is showing fewer visible texture set(s) than the replacement placement preview "
            f"({final_visible_texture_count:,}/{source_visible_texture_count:,}). This usually means imported source "
            "materials were merged into fewer game draw slots, or the final sidecar/DDS paths could not be validated. "
            "Use separate original target slots where possible, or bake/atlas the source textures when parts must share one slot."
        )

    material_statuses: List[FinalPackageMaterialStatus] = []
    likely_grey_materials: List[str] = []
    all_material_keys = (set(material_display_by_key) if sidecars else set()) | set(rows_by_material)
    for material_key in sorted(all_material_keys, key=lambda key: material_display_by_key.get(key, key).lower()):
        material_name = material_display_by_key.get(material_key, material_key or "Material")
        rows = rows_by_material.get(material_key, [])
        visible_rows = [row for row in rows if row.role in {"Base / Color", "Emissive"}]
        support_rows = [row for row in rows if row.role in {"Normal", "Height", "Material / Mask", "Detail Mask"}]
        ready_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_READY and row.confidence == "exact"]
        missing_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_MISSING_DDS]
        decode_failed_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_DECODE_FAILED]
        if ready_visible:
            status = FINAL_PREVIEW_READY
            detail = "Final sidecar visible texture binding resolves to a generated/copied DDS payload."
        elif missing_visible:
            status = FINAL_PREVIEW_MISSING_DDS
            detail = "Visible base/color/emissive sidecar binding points at a DDS that is not in the generated/copied payload set."
        elif decode_failed_visible:
            status = FINAL_PREVIEW_DECODE_FAILED
            detail = "Visible texture payload exists but failed preview decoding."
        elif support_rows:
            if any(row.role in {"Normal", "Height"} for row in support_rows):
                status = FINAL_PREVIEW_SUPPORT_MAPS_ONLY
                detail = "Only support maps are bound; normal/height/material maps do not add visible color."
            else:
                status = FINAL_PREVIEW_ADVANCED_SHADER_ONLY
                detail = "Only advanced material/mask shader inputs are bound; no base/color/emissive texture is available."
        else:
            status = FINAL_PREVIEW_MISSING_BASE
            detail = "No final base/color/emissive sidecar binding was found for this visible material."
        material_statuses.append(FinalPackageMaterialStatus(material_name=material_name, status=status, detail=detail))
        if status != FINAL_PREVIEW_READY:
            likely_grey_materials.append(material_name)

    material_status_by_name = {status.material_name: status.status for status in material_statuses}
    if material_statuses:
        status_by_key = {
            _material_key(status.material_name): status.status
            for status in material_statuses
        }
        binding_rows = [
            dataclasses.replace(row, material_status=status_by_key.get(_material_key(row.material_name), row.material_status))
            for row in binding_rows
        ]

    if likely_grey_materials:
        warnings.append(
            "This will likely be grey in-game for: "
            + ", ".join(likely_grey_materials[:8])
            + (" ..." if len(likely_grey_materials) > 8 else "")
        )
    if not sidecars and not binding_sources:
        warnings.append("No generated/copied material sidecar payloads were available for final package texture validation.")

    ready_materials = sum(1 for status in material_statuses if status.status == FINAL_PREVIEW_READY)
    contract_base_count = sum(1 for row in binding_rows if row.role in {"Base / Color", "Emissive"})
    contract_normal_count = sum(1 for row in binding_rows if row.role == "Normal")
    contract_material_count = sum(1 for row in binding_rows if row.role == "Material / Mask")
    ready_binding_count = sum(1 for row in binding_rows if row.status == FINAL_PREVIEW_READY)
    missing_binding_count = sum(1 for row in binding_rows if row.status == FINAL_PREVIEW_MISSING_DDS)
    visible_mesh_parts = len(tuple(getattr(preview_model, "meshes", ()) or ()))
    source_owned_color_count = sum(
        1
        for row in binding_rows
        if _binding_row_is_source_visible_authority(row)
    )
    inherited_color_count = sum(
        1
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        and row.status == FINAL_PREVIEW_READY
    )
    missing_color_count = sum(
        1
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.status != FINAL_PREVIEW_READY
    )
    unresolved_stock_count = sum(
        1
        for row in binding_rows
        if _is_stock_or_shared_texture_path(row.texture_path)
        and row.status != FINAL_PREVIEW_READY
    )
    stock_preserved_count = sum(
        1
        for row in binding_rows
        if _is_stock_or_shared_texture_path(row.texture_path)
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
    )
    planned_placeholder_material_keys: set[str] = set()
    planned_source_owned_material_keys: set[str] = set()
    planned_source_owned_material_display: Dict[str, str] = {}
    source_names_by_contract_key: Dict[str, List[str]] = {}
    if require_source_owned_colors:
        available_source_owned_contract_keys = set(rows_by_material) | {
            _material_key(name)
            for name in tuple(sidecar_submesh_resource_names or ())
            if _material_key(name)
        }

        def select_source_owned_contract_name(section: object) -> str:
            candidates = _dedupe(
                str(name or "").strip()
                for name in (
                    getattr(section, "target_submesh_name", ""),
                    getattr(section, "runtime_material_name", ""),
                    getattr(section, "runtime_slot_name", ""),
                    getattr(section, "atlas_material_name", ""),
                    getattr(section, "source_material_name", ""),
                )
                if str(name or "").strip()
            )
            for candidate in candidates:
                key = _material_key(candidate)
                if key and key in available_source_owned_contract_keys:
                    return candidate
            return candidates[0] if candidates else ""

        for section in getattr(preview_result, "source_owned_output_draw_sections", ()) or ():
            if tuple(getattr(section, "source_submesh_indices", ()) or ()):
                name = select_source_owned_contract_name(section)
                key = _material_key(name)
                if key:
                    planned_source_owned_material_keys.add(key)
                    planned_source_owned_material_display.setdefault(key, str(name or "").strip() or key)
                    source_names = _source_owned_section_source_material_names(section)
                    if source_names:
                        source_names_by_contract_key.setdefault(key, [])
                        source_names_by_contract_key[key].extend(source_names)
                continue
            for name in (
                getattr(section, "target_submesh_name", ""),
                getattr(section, "donor_material_name", ""),
            ):
                key = _material_key(name)
                if key:
                    planned_placeholder_material_keys.add(key)
    preflight_errors: List[str] = []
    if source_owned_binding_contract_enabled:
        preflight_errors.extend(_material_export_safety_blockers_for_specs(preview_result, source_materials_for_report, tuple(sidecars.values()), package_written=package_root is not None))
    for row in binding_rows:
        row_material_key = _material_key(getattr(row, "material_name", ""))
        row_is_planned_placeholder = bool(row_material_key and row_material_key in planned_placeholder_material_keys)
        row_is_planned_source_owned = bool(row_material_key and row_material_key in planned_source_owned_material_keys)
        basename = PurePosixPath(str(row.texture_path or "").replace("\\", "/")).name.lower()
        stem = PurePosixPath(basename).stem.lower()
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        if row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC:
            preflight_errors.append(
                f"Exact texture path mismatch: {row.sidecar_path} -> {row.texture_path}. A same-basename DDS exists, but the packaged path does not match."
            )
        if (
            not row_is_planned_placeholder
            and row.role in {"Base / Color", "Emissive"}
            and row.status in {FINAL_PREVIEW_MISSING_DDS, FINAL_PREVIEW_DECODE_FAILED}
        ):
            message = (
                f"Visible color texture is not package-resolved: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if (
                require_source_owned_colors
                and row_is_planned_source_owned
                and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
                and not strict_source_owned_material_contract
            ):
                warnings.append(message)
            else:
                preflight_errors.append(message)
        if (
            not row_is_planned_placeholder
            and row.role == "Base / Color"
            and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height"))
        ):
            preflight_errors.append(
                f"Support map is bound as visible base color: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            not row_is_planned_placeholder
            and
            any(token in parameter_key for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture"))
            and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height"))
        ):
            preflight_errors.append(
                f"Support map path is assigned to a visible color parameter: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            source_owned_binding_contract_enabled
            and row.role in {"Base / Color", "Emissive"}
            and row.status == FINAL_PREVIEW_READY
            and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and not (
                allow_inherited_layer_color_bindings
                and _binding_row_is_preserved_layer_color(row)
            )
        ):
            message = (
                f"Complete source-owned swap still inherits visible color from the game archive: "
                f"{row.material_name} -> {row.texture_path}."
            )
            if true_source_authority_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
        if (
            source_owned_binding_contract_enabled
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and row.role in {"Base / Color", "Emissive", "Normal", "Height", "Material / Mask", "Detail Mask"}
            and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        ):
            message = (
                f"Complete source-owned slot still inherits original {row.role} binding: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if (
                allow_inherited_layer_color_bindings
                and _binding_row_is_preserved_layer_color(row)
                and not strict_source_owned_material_contract
            ):
                warnings.append(message)
            elif runtime_xml_preserve_contract:
                warnings.append(message)
            elif relief_support_allowed and _binding_row_is_relief_support_only(row):
                warnings.append(message)
            elif strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
        if (
            source_owned_binding_contract_enabled
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
            and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
        ):
            message = (
                f"Complete source-owned wrapper still has non-generated original/support material parameter: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if relief_support_allowed and _binding_row_is_relief_support_only(row):
                warnings.append(message)
            elif strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
    source_materials_by_key = _source_material_rows_by_key(source_materials_for_report)
    if source_owned_binding_contract_enabled and planned_source_owned_material_keys:
        for material_key in sorted(planned_source_owned_material_keys):
            if material_key in planned_placeholder_material_keys:
                continue
            rows = _rows_for_source_owned_contract(material_key, rows_by_material, binding_rows)
            display_name = planned_source_owned_material_display.get(material_key) or material_display_by_key.get(material_key) or material_key
            expected_support_roles = _source_expected_support_roles_for_contract(
                material_key,
                source_names_by_contract_key,
                source_materials_by_key,
            )
            contract = _source_owned_material_binding_contract(
                material_key,
                display_name,
                rows,
                strict=bool(strict_source_owned_material_contract),
                allow_inherited_layer_color_bindings=bool(allow_inherited_layer_color_bindings),
                allow_relief_support=bool(relief_support_allowed),
                allow_detail_mask_material=bool(detail_mask_material_allowed),
                expected_support_roles=expected_support_roles,
            )
            preflight_errors.extend(contract.fatal_errors)
            warnings.extend(contract.warnings)
    if orphan_payload_paths:
        preflight_errors.append(
            "Generated/copied DDS payloads are not referenced by parsed material sidecars: "
            + ", ".join(orphan_payload_paths[:8])
            + (" ..." if len(orphan_payload_paths) > 8 else "")
        )
    if source_owned_binding_contract_enabled and not sidecars:
        message = "Complete source-owned swap has no packaged material sidecar payload to control visible color."
        if true_source_authority_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if source_owned_binding_contract_enabled and source_visible_texture_count > final_visible_texture_count:
        message = (
            "Complete source-owned swap lost visible texture coverage in the final package contract "
            f"({final_visible_texture_count:,}/{source_visible_texture_count:,})."
        )
        if strict_source_owned_material_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if source_owned_binding_contract_enabled and fallback_assignment_count:
        message = (
            "Complete source-owned swap final preview used draw-order fallback for "
            f"{fallback_assignment_count:,} mesh batch(es); generated material names did not match patched sidecar bindings."
            + _fallback_assignment_detail(fallback_assignment_details)
        )
        if strict_source_owned_material_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if require_source_owned_colors:
        preflight_errors.extend(_pac_runtime_abi_preflight_errors(bytes(getattr(effective_preview_result, "rebuilt_data", b"") or b""), preview_result))
        source_meshes = list(getattr(getattr(preview_result, "preview_model", None), "meshes", []) or [])
        visible_material_names = [_material_label_for_mesh(mesh, index) for index, mesh in enumerate(getattr(preview_model, "meshes", []) or [])]
        preflight_errors.extend(
            _pac_xml_submesh_resource_order_errors(sidecar_submesh_resource_names, visible_material_names)
        )
        visible_material_keys = {_material_key(name) for name in visible_material_names if _material_key(name)}
        parsed_material_keys: set[str] = set()
        parsed_mesh = getattr(preview_result, "parsed_mesh", None)
        for submesh in getattr(parsed_mesh, "submeshes", ()) or ():
            parsed_material_keys.update(
                _material_key(name)
                for name in (
                    getattr(submesh, "material", ""),
                    getattr(submesh, "name", ""),
                    getattr(submesh, "texture", ""),
                )
                if _material_key(name)
            )
        planned_material_keys: set[str] = set()
        for section in getattr(preview_result, "source_owned_output_draw_sections", ()) or ():
            planned_material_keys.update(
                _material_key(name)
                for name in (
                    getattr(section, "target_submesh_name", ""),
                    getattr(section, "donor_material_name", ""),
                )
                if _material_key(name)
            )
        valid_sidecar_material_keys = visible_material_keys | parsed_material_keys | planned_material_keys
        stale_sidecar_names = [
            name
            for name in sidecar_submesh_resource_names
            if _material_key(name) and _material_key(name) not in valid_sidecar_material_keys
        ]
        if source_owned_binding_contract_enabled and true_source_authority_contract and stale_sidecar_names:
            stale_names = _dedupe(stale_sidecar_names)
            preflight_errors.append(
                "Complete source-owned swap PAC XML still contains stale original _subMeshResources wrapper(s) "
                "that are not rebuilt PAC draw sections: "
                + ", ".join(stale_names[:8])
                + (" ..." if len(stale_names) > 8 else "")
            )
        missing_source_owned_materials: List[str] = []
        for index, mesh in enumerate(getattr(preview_model, "meshes", []) or []):
            source_mesh = source_meshes[index] if index < len(source_meshes) else None
            if source_mesh is not None and not str(getattr(source_mesh, "preview_texture_path", "") or "").strip():
                continue
            if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                continue
            material_name = _material_label_for_mesh(mesh, index)
            if material_name:
                missing_source_owned_materials.append(material_name)
        if source_owned_binding_contract_enabled and missing_source_owned_materials:
            missing_names = _dedupe(missing_source_owned_materials)
            message = (
                "Complete source-owned swap has no exact generated visible sidecar/DDS binding for: "
                + ", ".join(missing_names[:8])
                + (" ..." if len(missing_names) > 8 else "")
            )
            if strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
    if require_source_owned_colors and sidecar_structure_errors:
        preflight_errors.extend(sidecar_structure_errors)
    preflight_errors = _dedupe(preflight_errors)

    summary_lines = [
        "Final Output Preview",
        f"Package root: {package_root_text or '-'}",
        f"Visible mesh parts: {visible_mesh_parts:,}",
        f"Parsed sidecar payloads: {len(sidecars):,}" + ("; using kept original sidecar bindings" if binding_sources and not sidecars else ""),
        f"Patched sidecar payloads: {generated_sidecar_count:,}",
        f"Generated/copied DDS payloads: {len(dds_by_path):,}",
        f"Ready material(s): {ready_materials:,}/{len(material_statuses):,}",
        f"Sidecar texture refs used: {len(binding_rows):,}; found {ready_binding_count:,}; missing {missing_binding_count:,}",
        f"Color authority: source-owned {source_owned_color_count:,}, inherited {inherited_color_count:,}, missing {missing_color_count:,}",
        (
            "Texture Contract: "
            f"base/color {contract_base_count:,}, normal {contract_normal_count:,}, "
            f"material/mask {contract_material_count:,}, stock/shared preserved {stock_preserved_count:,}, "
            f"unresolved stock {unresolved_stock_count:,}, orphan DDS {len(orphan_payload_paths):,}"
        ),
    ]
    if require_source_owned_colors:
        if runtime_xml_preserve_contract:
            summary_lines.append(
                "Material Authority: Runtime XML preserve; stock layer/support bindings are allowed and may affect the final in-game look."
            )
        elif true_source_authority_contract:
            summary_lines.append(
                "Material Authority: True Source Authority; original visible/support influence is blocked for active source-owned wrappers."
            )
            if not preflight_errors:
                summary_lines.append(
                    "Source authority complete: active source-owned wrappers resolved to source/generated/neutral material bindings."
                )
    if preflight_errors:
        summary_lines.append(f"Preflight blocker(s): {len(preflight_errors):,}")
    if likely_grey_materials:
        summary_lines.append(f"Likely grey material(s): {', '.join(likely_grey_materials[:8])}" + (" ..." if len(likely_grey_materials) > 8 else ""))
    if missing_paths:
        summary_lines.append(f"Missing final DDS payload path(s): {len(_dedupe(missing_paths)):,}")
    texture_resolution_manifest = _build_texture_resolution_manifest(binding_rows, _dedupe(warnings))
    material_authority_report = _build_material_authority_report(
        preview_result,
        source_path=source_path_text,
        final_preview_model=preview_model,
        package_root=package_root_text,
        authority_contract=authority_contract,
        sidecars=sidecars,
        dds_by_path=dds_by_path,
        binding_rows=binding_rows,
        material_statuses=material_statuses,
        texture_resolution_manifest=texture_resolution_manifest,
        warnings=_dedupe(warnings),
        preflight_errors=preflight_errors,
        require_source_owned_colors=require_source_owned_colors,
        strict_source_owned_material_contract=strict_source_owned_material_contract,
        allow_inherited_layer_color_bindings=allow_inherited_layer_color_bindings,
        source_materials=source_materials_for_report,
        render_settings=render_settings,
    )
    if texture_resolution_manifest.rows:
        summary_lines.append(f"Texture resolution manifest rows: {len(texture_resolution_manifest.rows):,}")
    if material_authority_report.risk_flags:
        summary_lines.append("Material authority risk flags: " + ", ".join(material_authority_report.risk_flags[:8]))

    return FinalPackagePreviewResult(
        preview_model=preview_model,
        binding_rows=tuple(binding_rows),
        warnings=_dedupe(warnings),
        preflight_errors=preflight_errors,
        likely_grey_materials=_dedupe(likely_grey_materials),
        missing_texture_paths=_dedupe(missing_paths),
        summary_lines=summary_lines,
        material_statuses=tuple(material_statuses),
        texture_resolution_manifest=texture_resolution_manifest,
        material_authority_report=material_authority_report,
        package_root=package_root_text,
    )
