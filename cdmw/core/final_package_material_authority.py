from __future__ import annotations

import dataclasses
import hashlib
import io
import re
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_mesh_types import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds
from cdmw.core.upscale_profiles import (
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.models import ModelPreviewData, PreviewMaterialTextureInput
from cdmw.modding.pac_xml_profiles import (
    build_pac_xml_material_authority_report,
    compare_pac_xml_material_authority_structure,
)
from cdmw.rendering.asset_fidelity_preflight import normal_y_policy_report

FINAL_PREVIEW_MISSING_DDS = "missing_dds"
FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC = "basename_diagnostic"

SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES = 256 * 1024 * 1024

MATERIAL_AUTHORITY_SOURCE_ROUTE_DIAGNOSTIC_CODES = {
    "source_base_texture_bound_as_emissive",
    "source_spec_gloss_texture_bound_as_base",
    "source_material_response_texture_bound_as_base",
    "source_base_texture_bound_as_normal",
}


@dataclass(slots=True, frozen=True)
class FinalPackageMaterialStatus:
    material_name: str
    status: str
    detail: str = ""


@dataclass(slots=True, frozen=True)
class FinalPackageMaterialAuthorityReport:
    schema: str = "cdmw_material_authority_report_v1"
    source_path: str = ""
    package_root: str = ""
    authority_contract: str = ""
    target_sections: Tuple[Mapping[str, object], ...] = ()
    source_materials: Tuple[Mapping[str, object], ...] = ()
    texture_outputs: Tuple[Mapping[str, object], ...] = ()
    routing: Tuple[Mapping[str, object], ...] = ()
    sidecar_reports: Tuple[Mapping[str, object], ...] = ()
    sidecar_outputs: Tuple[Mapping[str, object], ...] = ()
    preview_settings: Mapping[str, object] = field(default_factory=dict)
    unknown_material_response_parameters: Tuple[Mapping[str, object], ...] = ()
    risk_flags: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    preflight_errors: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "authority_contract": self.authority_contract,
            "target_sections": [dict(row) for row in self.target_sections],
            "source_materials": [dict(row) for row in self.source_materials],
            "texture_outputs": [dict(row) for row in self.texture_outputs],
            "routing": [dict(row) for row in self.routing],
            "sidecar_reports": [dict(row) for row in self.sidecar_reports],
            "sidecar_outputs": [dict(row) for row in self.sidecar_outputs],
            "preview_settings": dict(self.preview_settings),
            "unknown_material_response_parameters": [dict(row) for row in self.unknown_material_response_parameters],
            "risk_flags": list(self.risk_flags),
            "warnings": list(self.warnings),
            "preflight_errors": list(self.preflight_errors),
        }

def _preview_helper(name: str):
    from . import final_package_preview

    return getattr(final_package_preview, name)


def _normalize_final_path(path: object) -> str:
    return _preview_helper("_normalize_final_path")(path)


def _spec_payload_bytes(spec: MeshImportSupplementalFileSpec) -> bytes:
    return _preview_helper("_spec_payload_bytes")(spec)


def _spec_payload_text(spec: MeshImportSupplementalFileSpec) -> str:
    return _preview_helper("_spec_payload_text")(spec)


def _decode_sidecar_bytes(payload: bytes) -> str:
    return _preview_helper("_decode_sidecar_bytes")(payload)


def _spec_source_file_text(spec: MeshImportSupplementalFileSpec) -> str:
    return _preview_helper("_spec_source_file_text")(spec)


def _material_key(value: object) -> str:
    return _preview_helper("_material_key")(value)


def _dedupe(values: Iterable[str]) -> List[str]:
    return _preview_helper("_dedupe")(values)


def _visible_preview_texture_count(model: object) -> int:
    return _preview_helper("_visible_preview_texture_count")(model)


def _is_stock_or_shared_texture_path(texture_path: str) -> bool:
    return _preview_helper("_is_stock_or_shared_texture_path")(texture_path)


def _build_material_authority_report(
    preview_result: MeshImportPreviewResult,
    *,
    source_path: str,
    final_preview_model: ModelPreviewData,
    package_root: str,
    authority_contract: str,
    sidecars: Mapping[str, Tuple[str, MeshImportSupplementalFileSpec]],
    dds_by_path: Mapping[str, _FinalPayload],
    binding_rows: Sequence[FinalPackageBindingRow],
    material_statuses: Sequence[FinalPackageMaterialStatus],
    texture_resolution_manifest: TextureResolutionManifest,
    warnings: Sequence[str],
    preflight_errors: Sequence[str],
    require_source_owned_colors: bool,
    strict_source_owned_material_contract: bool,
    allow_inherited_layer_color_bindings: bool,
    source_materials: Optional[Sequence[Mapping[str, object]]] = None,
    render_settings: object = None,
) -> FinalPackageMaterialAuthorityReport:
    contract = str(authority_contract or "").strip() or (
        "true_source_authority" if strict_source_owned_material_contract else "runtime_xml_preserve" if allow_inherited_layer_color_bindings else ""
    )
    sidecar_reports: List[Mapping[str, object]] = []
    sidecar_outputs: List[Mapping[str, object]] = []
    unknowns: List[Mapping[str, object]] = []
    inherited_count = 0
    for sidecar_path, spec in sidecars.values():
        sidecar_text = _spec_payload_text(spec)
        if not sidecar_text.strip():
            sidecar_outputs.append(_material_authority_sidecar_output_row(sidecar_path, spec))
            continue
        report = build_pac_xml_material_authority_report(
            sidecar_text,
            sidecar_path,
            authority_contract=contract or "true_source_authority",
        )
        report_dict = report.to_dict()
        sidecar_reports.append(report_dict)
        sidecar_outputs.append(_material_authority_sidecar_output_row(sidecar_path, spec, report_dict=report_dict))
        inherited_count += len(report.inherited_influence_parameters)
        for parameter in report.unknown_material_response_parameters:
            parameter_row = parameter.to_dict()
            parameter_row["sidecar_path"] = sidecar_path
            unknowns.append(parameter_row)

    normal_y_mode = _material_authority_render_normal_y_mode(render_settings)
    routing = tuple(_material_authority_routing_row(row) for row in binding_rows)
    target_sections = tuple(_material_authority_target_section_rows(preview_result, material_statuses, binding_rows))
    source_materials = tuple(source_materials) if source_materials is not None else _material_authority_source_material_rows_for_report(preview_result, source_path)
    texture_outputs = tuple(
        _material_authority_texture_output_row(
            payload,
            binding_rows=binding_rows,
            source_materials=source_materials,
            normal_y_mode=normal_y_mode,
        )
        for _key, payload in sorted(dds_by_path.items(), key=lambda item: item[1].final_path.lower())
    )
    risk_flags = _material_authority_risk_flags(
        binding_rows=binding_rows,
        texture_outputs=texture_outputs,
        sidecar_reports=sidecar_reports,
        source_materials=source_materials,
        unknowns=unknowns,
        inherited_count=inherited_count,
        warnings=warnings,
        preflight_errors=preflight_errors,
        require_source_owned_colors=require_source_owned_colors,
    )
    preview_settings = _material_authority_preview_settings(
        preview_result,
        final_preview_model,
        texture_resolution_manifest,
        require_source_owned_colors=require_source_owned_colors,
        strict_source_owned_material_contract=strict_source_owned_material_contract,
        allow_inherited_layer_color_bindings=allow_inherited_layer_color_bindings,
        render_settings=render_settings,
    )
    return FinalPackageMaterialAuthorityReport(
        source_path=str(source_path or "").replace("\\", "/"),
        package_root=str(package_root or "").replace("\\", "/"),
        authority_contract=contract,
        target_sections=target_sections,
        source_materials=source_materials,
        texture_outputs=texture_outputs,
        routing=routing,
        sidecar_reports=tuple(sidecar_reports),
        sidecar_outputs=tuple(sidecar_outputs),
        preview_settings=preview_settings,
        unknown_material_response_parameters=tuple(unknowns),
        risk_flags=risk_flags,
        warnings=tuple(str(warning) for warning in tuple(warnings or ()) if str(warning or "").strip()),
        preflight_errors=tuple(str(error) for error in tuple(preflight_errors or ()) if str(error or "").strip()),
    )


def _material_authority_sidecar_output_row(
    sidecar_path: str,
    spec: MeshImportSupplementalFileSpec,
    *,
    report_dict: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    payload = _spec_payload_bytes(spec)
    payload_text = _decode_sidecar_bytes(payload)
    source_path = getattr(spec, "source_path", None)
    source_text = source_path.as_posix() if isinstance(source_path, Path) else str(source_path or "")
    kind = str(getattr(spec, "kind", "") or "")
    report_mapping = dict(report_dict or {})
    return {
        "target_path": str(sidecar_path or "").replace("\\", "/"),
        "source_path": source_text.replace("\\", "/"),
        "kind": kind,
        "generated": bool(payload) or kind.endswith("_generated") or kind == "sidecar_generated",
        "used_for_preview": bool(getattr(spec, "used_for_preview", False)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        "note": str(getattr(spec, "note", "") or ""),
        "authority_status": str(report_mapping.get("status", "") or ""),
        "wrapper_count": int(report_mapping.get("wrapper_count", 0) or 0),
        "submesh_binding_count": len(tuple(report_mapping.get("submesh_bindings", ()) or ())),
        "parameter_count": int(report_mapping.get("parameter_count", 0) or 0),
        "unknown_material_response_count": len(tuple(report_mapping.get("unknown_material_response_parameters", ()) or ())),
        "inherited_influence_count": len(tuple(report_mapping.get("inherited_influence_parameters", ()) or ())),
        "neutralization_action_count": len(tuple(report_mapping.get("neutralization_actions", ()) or ())),
        "pac_xml_edit_summary": _material_authority_sidecar_edit_summary(sidecar_path, spec, payload, payload_text),
    }


def _material_authority_sidecar_edit_summary(
    sidecar_path: str,
    spec: MeshImportSupplementalFileSpec,
    payload: bytes,
    payload_text: str,
) -> Mapping[str, object]:
    source_text = _spec_source_file_text(spec)
    source_payload = source_text.encode("utf-8") if source_text else b""
    source_bindings = tuple(parse_texture_sidecar_bindings(source_text, sidecar_path=sidecar_path)) if source_text else ()
    payload_bindings = tuple(parse_texture_sidecar_bindings(payload_text, sidecar_path=sidecar_path)) if payload_text else ()
    changes = _material_authority_sidecar_texture_ref_changes(source_bindings, payload_bindings)
    structural_compare = _material_authority_sidecar_structural_compare(sidecar_path, source_text, payload_text)
    status = "payload_empty" if not payload_text.strip() else "source_compared" if source_text.strip() else "source_unavailable"
    changed = bool(source_text.strip() and source_text != payload_text)
    return {
        "status": status,
        "changed_from_source": changed,
        "source_available": bool(source_text.strip()),
        "source_sha256": hashlib.sha256(source_payload).hexdigest() if source_payload else "",
        "payload_sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        "source_texture_ref_count": len(source_bindings),
        "payload_texture_ref_count": len(payload_bindings),
        "texture_refs_added_count": sum(1 for row in changes if row["change"] == "added"),
        "texture_refs_removed_count": sum(1 for row in changes if row["change"] == "removed"),
        "texture_refs_changed_count": sum(1 for row in changes if row["change"] == "changed"),
        "texture_ref_changes": changes,
        "changed_parameter_names": tuple(
            sorted({str(row.get("parameter_name", "") or "") for row in changes if str(row.get("parameter_name", "") or "")})
        ),
        **structural_compare,
    }


def _material_authority_sidecar_structural_compare(
    sidecar_path: str,
    source_text: str,
    payload_text: str,
) -> Mapping[str, object]:
    return compare_pac_xml_material_authority_structure(source_text, payload_text, sidecar_path)


def _material_authority_sidecar_texture_ref_changes(
    source_bindings: Sequence[object],
    payload_bindings: Sequence[object],
) -> Tuple[Mapping[str, object], ...]:
    source_by_key = {
        _material_authority_sidecar_binding_key(binding): binding
        for binding in tuple(source_bindings or ())
        if str(getattr(binding, "texture_path", "") or "").strip()
    }
    payload_by_key = {
        _material_authority_sidecar_binding_key(binding): binding
        for binding in tuple(payload_bindings or ())
        if str(getattr(binding, "texture_path", "") or "").strip()
    }
    rows: List[Mapping[str, object]] = []
    for key in sorted(set(payload_by_key) - set(source_by_key)):
        binding = payload_by_key[key]
        rows.append(_material_authority_sidecar_change_row("added", binding, before="", after=str(getattr(binding, "texture_path", "") or "")))
    for key in sorted(set(source_by_key) - set(payload_by_key)):
        binding = source_by_key[key]
        rows.append(_material_authority_sidecar_change_row("removed", binding, before=str(getattr(binding, "texture_path", "") or ""), after=""))
    for key in sorted(set(source_by_key) & set(payload_by_key)):
        source_binding = source_by_key[key]
        payload_binding = payload_by_key[key]
        before = str(getattr(source_binding, "texture_path", "") or "")
        after = str(getattr(payload_binding, "texture_path", "") or "")
        if normalize_texture_reference_for_sidecar_lookup(before) == normalize_texture_reference_for_sidecar_lookup(after):
            continue
        rows.append(_material_authority_sidecar_change_row("changed", payload_binding, before=before, after=after))
    return tuple(rows)


def _material_authority_sidecar_binding_key(binding: object) -> Tuple[str, str, str]:
    material_name = str(
        getattr(binding, "material_name", "")
        or getattr(binding, "submesh_name", "")
        or getattr(binding, "part_name", "")
        or ""
    ).strip().lower()
    parameter_name = str(getattr(binding, "parameter_name", "") or "").strip().lower()
    role = str(getattr(binding, "texture_role", "") or "").strip().lower()
    return material_name, parameter_name, role


def _material_authority_sidecar_change_row(
    change: str,
    binding: object,
    *,
    before: str,
    after: str,
) -> Mapping[str, object]:
    return {
        "change": change,
        "material_name": str(getattr(binding, "material_name", "") or getattr(binding, "submesh_name", "") or ""),
        "parameter_name": str(getattr(binding, "parameter_name", "") or ""),
        "texture_role": str(getattr(binding, "texture_role", "") or ""),
        "before": str(before or "").replace("\\", "/"),
        "after": str(after or "").replace("\\", "/"),
    }


def _material_authority_preview_settings(
    preview_result: MeshImportPreviewResult,
    final_preview_model: ModelPreviewData,
    texture_resolution_manifest: TextureResolutionManifest,
    *,
    require_source_owned_colors: bool,
    strict_source_owned_material_contract: bool,
    allow_inherited_layer_color_bindings: bool,
    render_settings: object = None,
) -> Mapping[str, object]:
    normal_y_mode = _material_authority_render_normal_y_mode(render_settings)
    source_preview_model = getattr(preview_result, "preview_model", None)
    source_preview_mesh_parts = len(tuple(getattr(source_preview_model, "meshes", ()) or ()))
    final_preview_mesh_parts = len(tuple(getattr(final_preview_model, "meshes", ()) or ()))
    source_preview_visible_texture_sets = _visible_preview_texture_count(source_preview_model)
    final_preview_visible_texture_sets = _visible_preview_texture_count(final_preview_model)
    settings = {
        "visible_mesh_parts": source_preview_mesh_parts,
        "final_visible_mesh_parts": final_preview_mesh_parts,
        "source_preview_mesh_parts": source_preview_mesh_parts,
        "final_preview_mesh_parts": final_preview_mesh_parts,
        "source_preview_visible_texture_sets": source_preview_visible_texture_sets,
        "final_preview_visible_texture_sets": final_preview_visible_texture_sets,
        "preview_visible_texture_delta": source_preview_visible_texture_sets - final_preview_visible_texture_sets,
        "require_source_owned_colors": bool(require_source_owned_colors),
        "strict_source_owned_material_contract": bool(strict_source_owned_material_contract),
        "allow_inherited_layer_color_bindings": bool(allow_inherited_layer_color_bindings),
        "texture_resolution_manifest_rows": len(tuple(texture_resolution_manifest.rows or ())),
        "normal_y_policy": normal_y_policy_report(normal_y_mode),
    }
    material_authority_settings = getattr(preview_result, "material_authority_settings", None)
    if isinstance(material_authority_settings, Mapping) and material_authority_settings:
        settings["material_authority_export"] = {
            str(key): value if isinstance(value, (bool, int, float, str)) or value is None else str(value)
            for key, value in material_authority_settings.items()
        }
    if render_settings is None:
        settings["render_settings_source"] = "not_provided"
        return settings
    settings["render_settings_source"] = "provided"
    for field_name in (
        "visible_texture_mode",
        "render_diagnostic_mode",
        "alpha_handling_mode",
        "texture_probe_source",
        "sampler_probe_mode",
        "diffuse_swizzle_mode",
        "d3d11_view_mode",
        "d3d11_normal_y_mode",
        "d3d11_texture_address_mode",
    ):
        settings[field_name] = str(getattr(render_settings, field_name, "") or "")
    for field_name in (
        "disable_tint",
        "disable_brightness",
        "disable_uv_scale",
        "force_nearest_no_mipmaps",
        "disable_normal_map",
        "disable_material_map",
        "disable_height_map",
        "disable_all_support_maps",
        "flip_texture_v",
        "disable_lighting",
        "show_texture_debug_strip",
    ):
        settings[field_name] = bool(getattr(render_settings, field_name, False))
    for field_name in (
        "d3d11_ao_strength",
        "d3d11_roughness_bias",
        "d3d11_metalness_scale",
        "d3d11_environment_strength",
        "d3d11_emissive_gain",
        "d3d11_tone_exposure",
        "d3d11_tone_contrast",
        "d3d11_tone_gamma",
        "ambient_strength",
        "diffuse_wrap_bias",
        "diffuse_light_scale",
    ):
        try:
            settings[field_name] = float(getattr(render_settings, field_name))
        except (TypeError, ValueError, OverflowError):
            settings[field_name] = 0.0
    return settings


def _material_authority_render_normal_y_mode(render_settings: object = None) -> str:
    mode = str(getattr(render_settings, "d3d11_normal_y_mode", "") or "asset").strip().lower() or "asset"
    if mode not in {"asset", "force_flip", "force_no_flip"}:
        return "asset"
    return mode


def _material_authority_texture_output_row(
    payload: _FinalPayload,
    *,
    binding_rows: Sequence[FinalPackageBindingRow] = (),
    source_materials: Sequence[Mapping[str, object]] = (),
    normal_y_mode: str = "asset",
) -> Mapping[str, object]:
    payload_bytes = bytes(getattr(payload, "payload_data", b"") or b"")
    source_path = getattr(payload, "source_path", Path())
    source_text = str(source_path) if isinstance(source_path, Path) and str(source_path) != "." else ""
    source_file_size = 0
    source_file_sha256 = ""
    if isinstance(source_path, Path) and source_path.is_file():
        try:
            source_file_size, source_file_sha256 = _sha256_file_evidence(source_path)
        except OSError:
            source_file_size = 0
            source_file_sha256 = ""
    size = len(payload_bytes)
    sha256 = hashlib.sha256(payload_bytes).hexdigest() if payload_bytes else ""
    payload_source = "inline_payload" if payload_bytes else "source_file" if source_file_sha256 else "missing"
    if not payload_bytes and source_file_sha256:
        size = source_file_size
        sha256 = source_file_sha256
    bound_rows = _material_authority_texture_binding_rows(payload.final_path, binding_rows)
    dds_validation = _material_authority_dds_validation(payload, payload_bytes)
    source_normal_space = _material_authority_source_normal_space(source_text)
    role_diagnostics = _material_authority_texture_role_diagnostics(
        bound_rows,
        dds_validation,
        source_normal_space=source_normal_space,
        normal_y_mode=normal_y_mode,
    )
    channel_visualization = _material_authority_texture_channel_visualization(bound_rows, dds_validation)
    conversion_policy = _material_authority_texture_conversion_policy(
        payload,
        bound_rows,
        source_materials,
        dds_validation,
        channel_visualization,
        source_normal_space=source_normal_space,
        normal_y_mode=normal_y_mode,
    )
    visible_luma_mean = _material_authority_visible_luma_mean(payload, payload_bytes, bound_rows)
    return {
        "target_path": payload.final_path,
        "source_path": source_text.replace("\\", "/"),
        "kind": payload.kind,
        "note": str(getattr(payload, "note", "") or ""),
        "bytes": size,
        "sha256": sha256,
        "output_sha256": sha256,
        "payload_source": payload_source,
        "source_bytes": source_file_size,
        "source_sha256": source_file_sha256,
        "stock_or_shared": _is_stock_or_shared_texture_path(payload.final_path),
        "bound_roles": tuple(_dedupe(str(row.role or "") for row in bound_rows if str(row.role or "").strip())),
        "bound_parameters": tuple(_dedupe(str(row.parameter_name or "") for row in bound_rows if str(row.parameter_name or "").strip())),
        "bound_materials": tuple(_dedupe(str(row.material_name or "") for row in bound_rows if str(row.material_name or "").strip())),
        "source_normal_space": source_normal_space,
        "dds_validation": dds_validation,
        "role_diagnostics": role_diagnostics,
        "channel_visualization": channel_visualization,
        "conversion_policy": conversion_policy,
        "visible_luma_mean": visible_luma_mean if visible_luma_mean is not None else "",
    }


def _sha256_file_evidence(path: Path) -> tuple[int, str]:
    size = int(path.stat().st_size)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _material_authority_texture_binding_rows(
    target_path: str,
    binding_rows: Sequence[FinalPackageBindingRow],
) -> Tuple[FinalPackageBindingRow, ...]:
    target_key = _normalize_final_path(target_path)
    if not target_key:
        return ()
    matches: List[FinalPackageBindingRow] = []
    for row in tuple(binding_rows or ()):
        resolved_key = _normalize_final_path(row.resolved_texture_path)
        requested_key = _normalize_final_path(row.texture_path)
        if resolved_key == target_key or requested_key == target_key:
            matches.append(row)
    return tuple(matches)


def _material_authority_texture_conversion_policy(
    payload: _FinalPayload,
    bound_rows: Sequence[FinalPackageBindingRow],
    source_materials: Sequence[Mapping[str, object]],
    dds_validation: Mapping[str, object],
    channel_visualization: Sequence[Mapping[str, object]],
    *,
    source_normal_space: str = "",
    normal_y_mode: str = "asset",
) -> Mapping[str, object]:
    source_path = getattr(payload, "source_path", Path())
    source_extension = str(getattr(source_path, "suffix", "") or "").strip().lower()
    role_classes = tuple(_dedupe(_material_authority_bound_role_classes(bound_rows)))
    channel_kinds = tuple(
        _dedupe(
            str(row.get("kind", "") or "")
            for row in tuple(channel_visualization or ())
            if isinstance(row, Mapping) and str(row.get("kind", "") or "").strip()
        )
    )
    dds_format = str(dds_validation.get("dds_format", "") or "")
    source_rows = _material_authority_bound_source_material_rows(bound_rows, source_materials)
    source_workflows = tuple(_dedupe(_material_authority_source_row_workflow(row) for row in source_rows))
    source_derived_channels = tuple(
        _dedupe(
            str(channel or "").strip().lower()
            for row in source_rows
            for channel in _material_authority_source_row_derived_channels(row)
            if str(channel or "").strip()
        )
    )
    source_classes = tuple(
        _dedupe(
            str(item.get("class", "") or item.get("material_class", "") or "").strip()
            for row in source_rows
            for item in tuple(row.get("material_classification", ()) or ())
            if isinstance(item, Mapping) and str(item.get("class", "") or item.get("material_class", "") or "").strip()
        )
    )
    source_packed_channels = tuple(
        _dedupe(
            channel
            for row in source_rows
            for channel in _material_authority_source_row_packed_channels(row)
        )
    )
    source_packed_semantics = _material_authority_source_packed_channel_semantics(
        source_packed_channels,
        source_workflows,
    )
    source_route_diagnostics = tuple(
        _material_authority_dedupe_source_route_diagnostics(
            diagnostic
            for row in source_rows
            for diagnostic in _material_authority_source_row_route_diagnostics(row)
        )
    )
    spec_gloss_conversion = "material" in role_classes and "specular_glossiness" in source_workflows
    return {
        "source_extension": source_extension,
        "payload_kind": str(getattr(payload, "kind", "") or ""),
        "generated": str(getattr(payload, "kind", "") or "").strip().lower().endswith("_generated"),
        "inline_payload": bool(bytes(getattr(payload, "payload_data", b"") or b"")),
        "source_dds_passthrough": source_extension == ".dds",
        "source_image_to_dds": bool(source_extension and source_extension != ".dds"),
        "bound_role_classes": role_classes,
        "dds_format": dds_format,
        "channel_order": str(dds_validation.get("channel_order", "") or ""),
        "mip_count": int(dds_validation.get("mip_count", 0) or 0),
        "normal_y_mode": str(normal_y_mode or "asset"),
        "source_normal_space": source_normal_space,
        "source_material_names": tuple(_dedupe(str(row.get("material_name", "") or "") for row in source_rows if str(row.get("material_name", "") or "").strip())),
        "source_workflows": source_workflows,
        "source_derived_channels": source_derived_channels,
        "source_material_classes": source_classes,
        "source_packed_channels": source_packed_channels,
        "source_packed_channel_semantics": tuple(dict(row) for row in source_packed_semantics),
        "source_packed_channel_note": (
            "Source packed-channel evidence is recorded separately from the generated Crimson material-mask channel layout."
            if source_packed_channels
            else ""
        ),
        "source_route_diagnostic_codes": tuple(_dedupe(str(row.get("code", "") or "") for row in source_route_diagnostics)),
        "source_route_diagnostics": source_route_diagnostics,
        "source_route_diagnostic_note": (
            "Source material texture routing needs review before trusting this DDS output as source-authoritative."
            if source_route_diagnostics
            else ""
        ),
        "spec_gloss_conversion": spec_gloss_conversion,
        "spec_gloss_conversion_note": (
            "Specular/glossiness source workflow: glossiness is inverted to roughness and specular luminance is mapped into the Crimson packed material mask."
            if spec_gloss_conversion
            else ""
        ),
        "normal_y_policy_required": "normal" in role_classes,
        "channel_visualization_kinds": channel_kinds,
        "packed_channel_semantics": tuple(
            dict(row)
            for visualization in tuple(channel_visualization or ())
            if isinstance(visualization, Mapping)
            for row in tuple(visualization.get("channels", ()) or ())
            if isinstance(row, Mapping)
        ),
    }


def _material_authority_dds_validation(payload: _FinalPayload, payload_bytes: bytes) -> Mapping[str, object]:
    source_path = getattr(payload, "source_path", Path())
    source: object
    if payload_bytes:
        source = payload_bytes
    elif isinstance(source_path, Path) and source_path.is_file():
        source = source_path
    else:
        return {
            "status": "missing_payload",
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "dds_format": "",
            "channel_order": "",
            "findings": (
                {
                    "severity": "fatal",
                    "code": "missing_payload",
                    "message": "DDS payload bytes and source file are unavailable.",
                },
            ),
        }
    try:
        info = inspect_crimson_dds(source, vpath=str(getattr(payload, "final_path", "") or ""))
    except Exception as exc:
        return {
            "status": "error",
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "dds_format": "",
            "channel_order": "",
            "findings": (
                {
                    "severity": "fatal",
                    "code": "inspection_failed",
                    "message": str(exc),
                },
            ),
        }
    findings = tuple(
        {
            "severity": str(getattr(finding, "severity", "") or ""),
            "code": str(getattr(finding, "code", "") or ""),
            "message": str(getattr(finding, "message", "") or ""),
        }
        for finding in tuple(getattr(info, "findings", ()) or ())
    )
    severity_values = {str(row.get("severity", "") or "") for row in findings}
    status = "invalid" if "fatal" in severity_values else "warning" if "warning" in severity_values else "valid"
    effective_last4 = getattr(info, "effective_last4", None)
    return {
        "status": status,
        "width": int(getattr(info, "width", 0) or 0),
        "height": int(getattr(info, "height", 0) or 0),
        "mip_count": int(getattr(info, "mip_count", 0) or 0),
        "raw_mip_count": int(getattr(info, "raw_mip_count", 0) or 0),
        "depth": int(getattr(info, "depth", 0) or 0),
        "dds_format": str(getattr(info, "dds_format", "") or ""),
        "channel_order": _material_authority_dds_channel_order(getattr(info, "dds_format", "")),
        "is_dx10": bool(getattr(info, "is_dx10", False)),
        "dxgi_format": int(getattr(info, "dxgi_format", 0) or 0),
        "fourcc": str(getattr(info, "fourcc", "") or ""),
        "block_bytes": int(getattr(info, "block_bytes", 0) or 0),
        "requires_pathc": bool(getattr(info, "requires_pathc", False)),
        "effective_last4": f"0x{int(effective_last4):04X}" if effective_last4 is not None else "",
        "findings": findings,
    }


def _material_authority_visible_luma_mean(
    payload: _FinalPayload,
    payload_bytes: bytes,
    bound_rows: Sequence[FinalPackageBindingRow],
) -> float | None:
    if "base_color" not in _material_authority_bound_role_classes(bound_rows):
        return None
    source_path = getattr(payload, "source_path", Path())
    try:
        from PIL import Image, ImageStat

        source = io.BytesIO(payload_bytes) if payload_bytes else source_path if isinstance(source_path, Path) and source_path.is_file() else None
        if source is None:
            return None
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((256, 256))
            red, green, blue = ImageStat.Stat(rgb).mean[:3]
    except Exception:
        stats = dict(_material_authority_dds_channel_stats(_material_authority_payload_or_file_bytes(payload, payload_bytes)))
        luma = _material_authority_float(stats.get("luma_mean"), -1.0)
        return round(luma * 255.0, 4) if luma >= 0.0 else None
    luma = (0.2126 * float(red)) + (0.7152 * float(green)) + (0.0722 * float(blue))
    return round(luma, 4)


def _material_authority_dds_channel_order(dds_format: object) -> str:
    normalized = str(dds_format or "").strip().upper()
    if normalized.startswith("R8G8B8A8"):
        return "rgba"
    if normalized.startswith("B8G8R8A8"):
        return "bgra"
    if normalized.startswith("B8G8R8X8"):
        return "bgrx"
    if normalized.startswith("R8G8_"):
        return "rg"
    if normalized.startswith("R8_"):
        return "r"
    if normalized.startswith("A8_"):
        return "a"
    if normalized.startswith(("BC1_", "BC2_", "BC3_", "BC7_")):
        return "block_color"
    if normalized.startswith(("BC4_", "BC5_", "BC6H_")):
        return "block_linear"
    return ""


def _material_authority_texture_role_diagnostics(
    bound_rows: Sequence[FinalPackageBindingRow],
    dds_validation: Mapping[str, object],
    *,
    source_normal_space: str = "",
    normal_y_mode: str = "asset",
) -> Tuple[Mapping[str, object], ...]:
    dds_format = str(dds_validation.get("dds_format", "") or "").upper()
    if not dds_format:
        return ()
    diagnostics: List[Mapping[str, object]] = []
    roles = {str(row.role or "").strip().lower() for row in tuple(bound_rows or ())}
    parameters = {str(row.parameter_name or "").strip().lower() for row in tuple(bound_rows or ())}
    role_text = " ".join(sorted(roles | parameters))
    role_classes = _material_authority_bound_role_classes(bound_rows)
    visible_role_classes = role_classes.intersection({"base_color", "emissive"})
    if "base_color" in role_classes and ("emissive" in role_classes or "emissive_control" in role_classes):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "base_texture_used_as_emissive",
                "message": "Same DDS is bound to both base/color and emissive parameters; source emissive authority is ambiguous.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if visible_role_classes and role_classes.intersection({"normal", "material", "height"}):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "texture_bound_to_visible_and_technical_roles",
                "message": "Same DDS is bound to visible color/emissive and technical material roles.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if len(role_classes) > 1:
        diagnostics.append(
            {
                "severity": "info",
                "code": "multi_role_texture_binding",
                "message": "DDS has multiple material binding roles; verify routing is intentional.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if "normal" in role_text:
        policy = normal_y_policy_report(normal_y_mode)
        diagnostics.append(
            {
                "severity": "info",
                "code": "normal_y_policy",
                "message": "Normal Y policy is recorded for preview/export review.",
                "normal_y_mode": str(policy.get("normal_y_mode", "") or ""),
                "d3d11_normal_y_mode": str(policy.get("d3d11_normal_y_mode", "") or ""),
                "effective_preview_policy": str(policy.get("effective_preview_policy", "") or ""),
                "archive_source_normal_space": str(policy.get("archive_source_normal_space", "") or ""),
                "source_normal_space": source_normal_space or "unknown",
            }
        )
        if not source_normal_space:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_y_policy_unconfirmed",
                    "message": "Normal source filename did not declare green_up/directx; verify Y was not flipped incorrectly.",
                }
            )
        if not dds_format.startswith("BC5_"):
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_format_not_bc5",
                    "message": "Normal texture is not BC5; verify tangent-space XY packing and normal Y policy.",
                }
            )
        if "SRGB" in dds_format:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_srgb_format",
                    "message": "Normal texture uses an sRGB format; normals should be linear.",
                }
            )
    if visible_role_classes:
        if dds_format.startswith(("BC4_", "BC5_", "R8_", "R8G8_")):
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "visible_color_technical_format",
                    "message": "Visible color slot uses a scalar/vector technical DDS format.",
                }
            )
        if dds_format in {"BC1_UNORM", "BC2_UNORM", "BC3_UNORM", "BC7_UNORM", "R8G8B8A8_UNORM", "B8G8R8A8_UNORM"}:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "visible_color_linear_format_review",
                    "message": "Visible color DDS is not marked sRGB; verify intended color space.",
                }
            )
    if "emissive_control" in role_classes or any(
        token in role_text for token in ("material", "roughness", "metal", "ao", "height", "mask", "detail")
    ):
        if "SRGB" in dds_format:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "technical_slot_srgb_format",
                    "message": "Technical/material slot uses sRGB format; packed scalar channels should be linear.",
                }
            )
    channel_order = str(dds_validation.get("channel_order", "") or "")
    if channel_order in {"rgba", "bgra", "bgrx"}:
        diagnostics.append(
            {
                "severity": "info",
                "code": "uncompressed_channel_order",
                "message": f"Uncompressed DDS channel order detected: {channel_order.upper()}. Verify RGBA/BGRA expectations.",
            }
        )
    return tuple(diagnostics)


def _material_authority_texture_channel_visualization(
    bound_rows: Sequence[FinalPackageBindingRow],
    dds_validation: Mapping[str, object],
) -> Tuple[Mapping[str, object], ...]:
    dds_format = str(dds_validation.get("dds_format", "") or "").upper()
    channel_order = str(dds_validation.get("channel_order", "") or "").strip().lower()
    width = int(dds_validation.get("width", 0) or 0)
    height = int(dds_validation.get("height", 0) or 0)
    role_classes = _material_authority_bound_role_classes(bound_rows)
    role_text = " ".join(
        sorted(
            str(value or "").strip().lower()
            for row in tuple(bound_rows or ())
            for value in (row.role, row.parameter_name, row.texture_path, row.resolved_texture_path)
            if str(value or "").strip()
        )
    )

    rows: list[Mapping[str, object]] = []

    def add(kind: str, channels: Sequence[tuple[str, str]], note: str) -> None:
        if not channels:
            return
        rows.append(
            {
                "kind": kind,
                "width": width,
                "height": height,
                "dds_format": dds_format,
                "channel_order": channel_order,
                "channels": tuple({"channel": channel, "semantic": semantic} for channel, semantic in channels),
                "note": note,
            }
        )

    if "normal" in role_classes:
        add(
            "normal_xy",
            (("R", "normal_x"), ("G", "normal_y")),
            "Visualize normal XY channels; blue/Z is reconstructed in shader/preview.",
        )
    if "height" in role_classes:
        add("height", (("R", "height"),), "Visualize height/displacement scalar channel.")
    if role_classes.intersection({"base_color", "emissive"}):
        if channel_order == "bgra":
            channels = (("B", "red"), ("G", "green"), ("R", "blue"), ("A", "alpha"))
        elif channel_order == "bgrx":
            channels = (("B", "red"), ("G", "green"), ("R", "blue"), ("X", "unused"))
        else:
            channels = (("R", "red"), ("G", "green"), ("B", "blue"), ("A", "alpha"))
        add(
            "visible_color",
            channels,
            "Visualize visible color with recorded DDS channel order to catch RGBA/BGRA mixups.",
        )
    if "emissive_control" in role_classes:
        channels = (("R", "emissive_intensity"), ("G", "emissive_progress_or_mask")) if (
            channel_order == "rg" or dds_format.startswith("BC5_")
        ) else (("R", "emissive_intensity"),)
        add(
            "emissive_control",
            channels,
            "Visualize Crimson emissive intensity/progress control channels separately from RGB emissive color.",
        )
    if "material" in role_classes:
        packed_channels = _material_authority_packed_channel_semantics(role_text)
        add(
            "packed_material_mask",
            packed_channels,
            "Visualize packed Crimson material/mask scalar channels.",
        )
    if not rows and dds_format:
        if channel_order == "r":
            add("scalar", (("R", "scalar"),), "Visualize single-channel scalar texture.")
        elif channel_order == "rg" or dds_format.startswith("BC5_"):
            add("vector2", (("R", "x"), ("G", "y")), "Visualize two-channel vector/scalar texture.")
    return tuple(rows)


def _material_authority_packed_channel_semantics(role_text: str) -> Tuple[tuple[str, str], ...]:
    text = re.sub(r"[^a-z0-9]+", "", str(role_text or "").lower())
    if "detail" in text or text.endswith("mg") or "detailmask" in text:
        return (("R", "detail_or_grime"), ("G", "detail_or_grime"), ("B", "detail_or_grime"), ("A", "alpha"))
    if "specular" in text or "gloss" in text:
        return (("R", "specular"), ("G", "glossiness"), ("B", "unused_or_ao"), ("A", "alpha"))
    if "roughness" in text and "metal" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "roughness"),)
    if "metal" in text and "roughness" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "metallic"),)
    if "ao" in text or "occlusion" in text:
        return (("R", "ao"),)
    return (("R", "ao"), ("G", "roughness"), ("B", "metallic"), ("A", "alpha"))


def _material_authority_bound_source_material_rows(
    bound_rows: Sequence[FinalPackageBindingRow],
    source_materials: Sequence[Mapping[str, object]],
) -> Tuple[Mapping[str, object], ...]:
    if not bound_rows or not source_materials:
        return ()
    by_key: Dict[str, Mapping[str, object]] = {}
    for row in tuple(source_materials or ()):
        if not isinstance(row, Mapping):
            continue
        for value in (row.get("material_name"), row.get("runtime_material_name"), row.get("texture_name")):
            key = _material_key(str(value or ""))
            if key:
                by_key.setdefault(key, row)
    matched: List[Mapping[str, object]] = []
    seen: set[int] = set()
    for binding in tuple(bound_rows or ()):
        for value in (binding.material_name, binding.part_name):
            key = _material_key(str(value or ""))
            row = by_key.get(key)
            if row is None:
                continue
            row_id = id(row)
            if row_id in seen:
                continue
            seen.add(row_id)
            matched.append(row)
    return tuple(matched)


def _material_authority_source_row_workflow(row: Mapping[str, object]) -> str:
    profile = row.get("channel_profile")
    if isinstance(profile, Mapping):
        workflow = str(profile.get("workflow", "") or "").strip().lower()
        if workflow:
            return workflow
    return str(row.get("pbr_workflow", "") or "").strip().lower()


def _material_authority_source_row_derived_channels(row: Mapping[str, object]) -> Tuple[str, ...]:
    profile = row.get("channel_profile")
    if isinstance(profile, Mapping):
        return tuple(str(channel or "").strip().lower() for channel in tuple(profile.get("derived_channels", ()) or ()) if str(channel or "").strip())
    return ()


def _material_authority_source_row_packed_channels(row: Mapping[str, object]) -> Tuple[str, ...]:
    output: List[str] = []
    for packed in tuple(row.get("preview_material_texture_packed_channels", ()) or ()):
        normalized = str(packed or "").strip().lower()
        if normalized:
            output.append(normalized)
    for slot in tuple(row.get("material_inputs", ()) or ()):
        if not isinstance(slot, Mapping):
            continue
        slot_text = " ".join(
            str(slot.get(key, "") or "").strip().lower()
            for key in ("slot_kind", "semantic_type", "semantic_subtype", "parameter_name", "texture_path")
        )
        packed = tuple(
            str(channel or "").strip().lower()
            for channel in tuple(slot.get("packed_channels", ()) or ())
            if str(channel or "").strip()
        )
        if not packed:
            continue
        if not any(token in slot_text for token in ("material", "metal", "rough", "specular", "gloss", "occlusion", "ao", "mask")):
            continue
        output.extend(packed)
    return tuple(_dedupe(output))


def _material_authority_source_row_route_diagnostics(row: Mapping[str, object]) -> Tuple[Mapping[str, object], ...]:
    output: List[Mapping[str, object]] = []
    material_name = str(row.get("material_name", "") or "")
    for diagnostic in tuple(row.get("diagnostics", ()) or ()) + tuple(row.get("channel_diagnostics", ()) or ()):
        if not isinstance(diagnostic, Mapping):
            continue
        code = str(diagnostic.get("code", "") or "").strip()
        if code not in MATERIAL_AUTHORITY_SOURCE_ROUTE_DIAGNOSTIC_CODES:
            continue
        payload = {
            "code": code,
            "severity": str(diagnostic.get("severity", "") or ""),
            "message": str(diagnostic.get("message", "") or ""),
            "material_name": material_name,
            "slot_kind": str(diagnostic.get("slot_kind", "") or ""),
            "texture_name": str(diagnostic.get("texture_name", "") or ""),
            "texture_path": str(diagnostic.get("texture_path", "") or ""),
        }
        output.append({key: value for key, value in payload.items() if str(value or "").strip()})
    return tuple(output)


def _material_authority_dedupe_source_route_diagnostics(
    diagnostics: Iterable[Mapping[str, object]],
) -> Tuple[Mapping[str, object], ...]:
    output: List[Mapping[str, object]] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for diagnostic in tuple(diagnostics or ()):
        if not isinstance(diagnostic, Mapping):
            continue
        key = (
            str(diagnostic.get("code", "") or ""),
            str(diagnostic.get("material_name", "") or ""),
            str(diagnostic.get("slot_kind", "") or ""),
            str(diagnostic.get("texture_path", "") or diagnostic.get("texture_name", "") or ""),
        )
        if not any(key) or key in seen:
            continue
        seen.add(key)
        output.append(dict(diagnostic))
        if len(output) >= 8:
            break
    return tuple(output)


def _material_authority_source_packed_channel_semantics(
    packed_channels: Sequence[str],
    source_workflows: Sequence[str],
) -> Tuple[Mapping[str, object], ...]:
    channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(packed_channels or ())
        if str(channel or "").strip()
    )
    channel_set = set(channels)
    workflows = {str(workflow or "").strip().lower() for workflow in tuple(source_workflows or ()) if str(workflow or "").strip()}
    if not channels:
        return ()
    if "specular_glossiness" in workflows or {"specular", "glossiness"}.issubset(channel_set):
        return (
            {"channel": "R", "semantic": "specular_red"},
            {"channel": "G", "semantic": "specular_green"},
            {"channel": "B", "semantic": "specular_blue"},
            {"channel": "A", "semantic": "glossiness"},
        )
    if {"roughness", "metallic"}.issubset(channel_set) or {"roughness", "metalness"}.issubset(channel_set):
        rows: List[Mapping[str, object]] = []
        if channel_set.intersection({"ao", "occlusion", "ambientocclusion"}):
            rows.append({"channel": "R", "semantic": "ao"})
        rows.extend(
            (
                {"channel": "G", "semantic": "roughness"},
                {"channel": "B", "semantic": "metallic"},
            )
        )
        if channel_set.intersection({"alpha", "opacity"}):
            rows.append({"channel": "A", "semantic": "alpha"})
        return tuple(rows)
    if channel_set.intersection({"ao", "occlusion", "ambientocclusion"}):
        return ({"channel": "R", "semantic": "ao"},)
    if "roughness" in channel_set:
        return ({"channel": "R", "semantic": "roughness"},)
    if channel_set.intersection({"metallic", "metalness"}):
        return ({"channel": "R", "semantic": "metallic"},)
    if channel_set.intersection({"alpha", "opacity"}):
        return ({"channel": "A", "semantic": "alpha"},)
    fallback_channels = ("R", "G", "B", "A")
    return tuple(
        {"channel": fallback_channels[index], "semantic": semantic}
        for index, semantic in enumerate(channels[: len(fallback_channels)])
    )


def _material_authority_bound_role_classes(bound_rows: Sequence[FinalPackageBindingRow]) -> set[str]:
    classes: set[str] = set()
    for row in tuple(bound_rows or ()):
        role = str(row.role or "").strip().lower()
        parameter = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        combined = f"{role} {parameter}"
        emissive_control = any(token in parameter for token in ("emissiveintensitytexture", "emissiveprogresstexture"))
        material_like = any(token in combined for token in ("colorblending", "material", "rough", "metal", "ao", "occlusion", "mask", "detail", "specular", "gloss"))
        if any(token in combined for token in ("base", "overlay", "albedo", "diffuse")) or (
            "color" in combined and not material_like
        ):
            classes.add("base_color")
        if emissive_control:
            classes.add("emissive_control")
        elif any(token in combined for token in ("emissive", "emission", "glow", "illum")):
            classes.add("emissive")
        if "normal" in combined:
            classes.add("normal")
        if "height" in combined or "displacement" in combined or "bump" in combined:
            classes.add("height")
        if material_like:
            classes.add("material")
    return classes


def _material_authority_source_normal_space(source_path: object) -> str:
    stem = PurePosixPath(str(source_path or "").replace("\\", "/")).stem.lower()
    if "green_up" in stem or ("open" + "gl") in stem or stem.endswith("_gl"):
        return "green_up"
    if "directx" in stem or stem.endswith("_dx") or "_dx_" in stem:
        return "directx"
    return ""


def _material_authority_routing_row(row: FinalPackageBindingRow) -> Mapping[str, object]:
    return {
        "material_name": row.material_name,
        "part_name": row.part_name,
        "role": row.role,
        "parameter_name": row.parameter_name,
        "sidecar_path": row.sidecar_path,
        "requested_texture_path": row.texture_path,
        "resolved_texture_path": row.resolved_texture_path,
        "binding_source": row.binding_source,
        "status": row.status,
        "confidence": row.confidence,
        "detail": row.detail,
    }


def _material_authority_target_section_rows(
    preview_result: MeshImportPreviewResult,
    material_statuses: Sequence[FinalPackageMaterialStatus],
    binding_rows: Sequence[FinalPackageBindingRow],
) -> Iterable[Mapping[str, object]]:
    status_by_key = {_material_key(row.material_name): row for row in tuple(material_statuses or ())}
    rows_by_key: Dict[str, List[FinalPackageBindingRow]] = defaultdict(list)
    for row in tuple(binding_rows or ()):
        rows_by_key[_material_key(row.material_name)].append(row)
    emitted: set[str] = set()
    for section in tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ()):
        name = str(
            getattr(section, "target_submesh_name", "")
            or getattr(section, "runtime_material_name", "")
            or getattr(section, "donor_material_name", "")
            or ""
        ).strip()
        key = _material_key(name)
        emitted.add(key)
        yield {
            "target_name": name,
            "runtime_material_name": str(getattr(section, "runtime_material_name", "") or ""),
            "source_material_name": str(getattr(section, "source_material_name", "") or ""),
            "source_submesh_indices": tuple(getattr(section, "source_submesh_indices", ()) or ()),
            "status": getattr(status_by_key.get(key), "status", ""),
            "binding_count": len(rows_by_key.get(key, ())),
        }
    for status in tuple(material_statuses or ()):
        key = _material_key(status.material_name)
        if key in emitted:
            continue
        yield {
            "target_name": status.material_name,
            "runtime_material_name": status.material_name,
            "source_material_name": "",
            "source_submesh_indices": (),
            "status": status.status,
            "binding_count": len(rows_by_key.get(key, ())),
            "detail": status.detail,
        }


def _material_authority_source_material_rows(preview_result: MeshImportPreviewResult) -> Iterable[Mapping[str, object]]:
    preview_model = getattr(preview_result, "preview_model", None)
    source_name_by_key, source_name_by_index = _material_authority_source_material_name_lookup(preview_result)
    for index, mesh in enumerate(tuple(getattr(preview_model, "meshes", ()) or ())):
        runtime_material_name = str(getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or "")
        source_index = _material_authority_safe_int(getattr(mesh, "source_submesh_index", -1), -1)
        source_material_name = (
            source_name_by_index.get(source_index)
            or source_name_by_key.get(_material_key(runtime_material_name))
            or runtime_material_name
        )
        texture_inputs = []
        input_tuple = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
        for texture_input in input_tuple:
            texture_inputs.append(
                {
                    "slot_kind": str(getattr(texture_input, "slot_kind", "") or ""),
                    "parameter_name": str(getattr(texture_input, "parameter_name", "") or ""),
                    "texture_path": str(
                        getattr(texture_input, "preview_texture_path", "")
                        or getattr(texture_input, "source_texture_path", "")
                        or ""
                    ).replace("\\", "/"),
                    "semantic_type": str(getattr(texture_input, "semantic_type", "") or ""),
                    "semantic_subtype": str(getattr(texture_input, "semantic_subtype", "") or ""),
                    "packed_channels": tuple(getattr(texture_input, "packed_channels", ()) or ()),
                    "srgb_mode": str(getattr(texture_input, "srgb_mode", "") or ""),
                    "confidence": str(getattr(texture_input, "confidence", "") or ""),
                }
            )
        channel_profile = _material_authority_source_channel_profile(mesh, input_tuple, material_name=source_material_name)
        sections = _material_authority_source_section_rows(index, mesh, material_name=source_material_name)
        yield {
            "mesh_index": index,
            "material_name": source_material_name,
            "runtime_material_name": runtime_material_name if runtime_material_name != source_material_name else "",
            "texture_name": str(getattr(mesh, "texture_name", "") or ""),
            "preview_texture_path": str(getattr(mesh, "preview_texture_path", "") or "").replace("\\", "/"),
            "preview_normal_texture_path": str(getattr(mesh, "preview_normal_texture_path", "") or "").replace("\\", "/"),
            "preview_material_texture_path": str(getattr(mesh, "preview_material_texture_path", "") or "").replace("\\", "/"),
            "preview_material_texture_subtype": str(getattr(mesh, "preview_material_texture_subtype", "") or ""),
            "preview_material_texture_packed_channels": tuple(getattr(mesh, "preview_material_texture_packed_channels", ()) or ()),
            "alpha_mode": str(getattr(mesh, "preview_alpha_mode", "") or ""),
            "double_sided": bool(getattr(mesh, "preview_double_sided", False)),
            "vertex_color_factor": tuple(channel_profile.get("vertex_color_factor", ())),
            "vertex_alpha": tuple(channel_profile.get("vertex_alpha", ())),
            "sections": sections,
            "section_count": len(sections),
            "material_inputs": tuple(texture_inputs),
            "texture_facts": _material_authority_source_texture_fact_rows(mesh, input_tuple),
            "channel_profile": channel_profile,
            "detected_channels": tuple(channel_profile.get("detected_channels", ())),
            "missing_channels": tuple(channel_profile.get("missing_channels", ())),
            "material_classification": tuple(channel_profile.get("material_classification", ())),
            "diagnostics": tuple(channel_profile.get("diagnostics", ())),
        }


def _material_authority_source_material_rows_for_report(
    preview_result: MeshImportPreviewResult,
    source_path: object,
) -> Tuple[Mapping[str, object], ...]:
    external_rows = _material_authority_external_source_material_rows(source_path)
    if external_rows:
        return external_rows
    return tuple(_material_authority_source_material_rows(preview_result))


def _material_authority_external_source_material_rows(source_path: object) -> Tuple[Mapping[str, object], ...]:
    path_text = str(source_path or "").strip()
    if not path_text:
        return ()
    path = Path(path_text).expanduser()
    if not path.is_file() or path.suffix.lower() not in {".glb", ".gltf", ".obj", ".dae", ".fbx", ".zip"}:
        return ()
    if path.suffix.lower() == ".fbx":
        return _material_authority_fbx_source_material_rows(path)
    try:
        from cdmw.core.external_model_audit import _material_row_with_channel_profile
        from cdmw.modding.scene_importer import import_scene_mesh_with_report

        scene_result = import_scene_mesh_with_report(path)
        audit = getattr(scene_result, "external_audit", None)
    except Exception:
        return ()
    rows: List[Mapping[str, object]] = []
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        row = _material_authority_external_inventory_source_row(material, _material_row_with_channel_profile)
        if row:
            rows.append(row)
    return tuple(rows)


def _material_authority_fbx_source_material_rows(path: Path) -> Tuple[Mapping[str, object], ...]:
    try:
        from cdmw.core.external_model_audit import _audit_external_model_file, _material_row_with_channel_profile
        from cdmw.core.model_catalogue import LocalModelFile

        resolved_path = path.expanduser().resolve()
        stat = resolved_path.stat()
        root = resolved_path.parent
        catalogue_row = LocalModelFile(
            path=resolved_path,
            root=root,
            name=resolved_path.stem,
            extension=resolved_path.suffix.lower(),
            size=int(stat.st_size),
            modified_at=float(stat.st_mtime),
            import_supported=False,
        )
        audited = _audit_external_model_file(catalogue_row)
    except Exception:
        return ()
    rows: List[Mapping[str, object]] = []
    for material in tuple(audited.get("material_inventory", ()) if isinstance(audited, Mapping) else ()):
        if not isinstance(material, Mapping):
            continue
        row = _material_authority_external_inventory_source_row(material, _material_row_with_channel_profile)
        if row:
            rows.append(row)
    return tuple(rows)


def _material_authority_external_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _material_authority_mapping_items(value: object) -> Tuple[tuple[object, object], ...]:
    if isinstance(value, Mapping):
        return tuple(value.items())
    try:
        return tuple(value or ())  # type: ignore[arg-type]
    except TypeError:
        return ()


def _material_authority_external_inventory_source_row(
    material: object,
    profile_builder: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> Mapping[str, object]:
    texture_slot_values = tuple(_material_authority_external_value(material, "texture_slots", ()) or ())
    texture_slots = tuple(_material_authority_external_texture_slot_row(slot) for slot in texture_slot_values)
    texture_facts = tuple(_material_authority_external_texture_fact_row(slot) for slot in texture_slot_values)
    sections = tuple(_material_authority_external_section_row(section) for section in tuple(_material_authority_external_value(material, "sections", ()) or ()))
    classes = tuple(_material_authority_external_class_row(row) for row in tuple(_material_authority_external_value(material, "material_classes", ()) or ()))
    scalar_hints = {
        str(key or ""): _material_authority_float(value, 0.0)
        for key, value in _material_authority_mapping_items(_material_authority_external_value(material, "scalar_hints", ()))
        if str(key or "").strip()
    }
    payload: Dict[str, object] = {
        "material_name": str(_material_authority_external_value(material, "material_name", "") or ""),
        "texture_name": next((str(slot.get("texture_name", "") or "") for slot in texture_slots if str(slot.get("texture_name", "") or "")), ""),
        "texture_slots": texture_slots,
        "material_classes": classes,
        "pbr_workflow": str(_material_authority_external_value(material, "pbr_workflow", "") or ""),
        "alpha_mode": str(_material_authority_external_value(material, "alpha_mode", "") or ""),
        "double_sided": bool(_material_authority_external_value(material, "double_sided", False)),
        "scalar_hints": scalar_hints,
        "color_factor": tuple(_material_authority_external_value(material, "color_factor", ()) or ()),
        "vertex_color_factor": tuple(_material_authority_external_value(material, "vertex_color_factor", ()) or ()),
        "vertex_alpha": tuple(_material_authority_external_value(material, "vertex_alpha", ()) or ()),
        "emissive_color": tuple(_material_authority_external_value(material, "emissive_color", ()) or ()),
    }
    profiled = dict(profile_builder(payload))
    channel_profile = dict(profiled.get("channel_profile", {}) or {})
    return {
        "mesh_index": _material_authority_safe_int(_material_authority_external_value(material, "material_index", -1), -1),
        "material_name": payload["material_name"],
        "runtime_material_name": "",
        "texture_name": payload["texture_name"],
        "preview_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "base"), ""),
        "preview_normal_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "normal"), ""),
        "preview_material_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "material"), ""),
        "preview_material_texture_subtype": next((str(slot.get("semantic_subtype", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "material"), ""),
        "alpha_mode": payload["alpha_mode"],
        "double_sided": payload["double_sided"],
        "color_factor": payload["color_factor"],
        "vertex_color_factor": payload["vertex_color_factor"],
        "vertex_alpha": payload["vertex_alpha"],
        "emissive_color": payload["emissive_color"],
        "scalar_hints": tuple(scalar_hints.items()),
        "pbr_workflow": str(profiled.get("pbr_workflow", "") or payload["pbr_workflow"]),
        "sections": sections,
        "section_count": len(sections),
        "material_inputs": texture_slots,
        "texture_facts": texture_facts,
        "channel_profile": channel_profile,
        "detected_channels": tuple(profiled.get("detected_channels", ()) or ()),
        "missing_channels": tuple(profiled.get("missing_channels", ()) or ()),
        "material_classification": classes,
        "diagnostics": tuple(profiled.get("channel_diagnostics", ()) or ()),
        "source": "external_model_audit",
    }


def _material_authority_external_texture_slot_row(slot: object) -> Mapping[str, object]:
    return {
        "slot_kind": str(_material_authority_external_value(slot, "slot_kind", "") or ""),
        "parameter_name": str(_material_authority_external_value(slot, "parameter_name", "") or ""),
        "texture_path": str(_material_authority_external_value(slot, "texture_path", "") or "").replace("\\", "/"),
        "texture_name": str(_material_authority_external_value(slot, "texture_name", "") or ""),
        "image_format": str(_material_authority_external_value(slot, "image_format", "") or ""),
        "resolution": tuple(_material_authority_external_value(slot, "resolution", ()) or ()),
        "channel_stats": tuple(_material_authority_external_value(slot, "channel_stats", ()) or ()),
        "semantic_type": str(_material_authority_external_value(slot, "semantic_type", "") or ""),
        "semantic_subtype": str(_material_authority_external_value(slot, "semantic_subtype", "") or ""),
        "packed_channels": tuple(_material_authority_external_value(slot, "packed_channels", ()) or ()),
        "color_space": str(_material_authority_external_value(slot, "color_space", "") or ""),
        "source": str(_material_authority_external_value(slot, "source", "") or ""),
        "confidence": str(_material_authority_external_value(slot, "confidence", "") or ""),
    }


def _material_authority_external_texture_fact_row(slot: object) -> Mapping[str, object]:
    row = dict(_material_authority_external_texture_slot_row(slot))
    row["resolution_status"] = "available" if len(tuple(row.get("resolution", ()) or ())) >= 2 else "missing_or_unreadable"
    row["channel_stats_status"] = "available" if tuple(row.get("channel_stats", ()) or ()) else "missing_or_unreadable"
    return row


def _material_authority_external_section_row(section: object) -> Mapping[str, object]:
    return {
        "section_index": _material_authority_safe_int(_material_authority_external_value(section, "section_index", -1), -1),
        "source_submesh_index": _material_authority_safe_int(_material_authority_external_value(section, "section_index", -1), -1),
        "section_name": str(_material_authority_external_value(section, "section_name", "") or ""),
        "material_name": str(_material_authority_external_value(section, "material_name", "") or ""),
        "runtime_material_name": "",
        "vertex_count": _material_authority_safe_int(_material_authority_external_value(section, "vertex_count", 0), 0),
        "face_count": _material_authority_safe_int(_material_authority_external_value(section, "face_count", 0), 0),
        "has_uvs": bool(_material_authority_external_value(section, "has_uvs", False)),
        "has_normals": bool(_material_authority_external_value(section, "has_normals", False)),
        "has_tangents": bool(_material_authority_external_value(section, "has_tangents", False)),
        "has_skinning": bool(_material_authority_external_value(section, "has_skinning", False)),
        "texture_texcoord_sets": tuple(_material_authority_external_value(section, "texture_texcoord_sets", ()) or ()),
        "bounds_min": tuple(_material_authority_external_value(section, "bounds_min", ()) or ()),
        "bounds_max": tuple(_material_authority_external_value(section, "bounds_max", ()) or ()),
    }


def _material_authority_external_class_row(row: object) -> Mapping[str, object]:
    material_class = str(_material_authority_external_value(row, "material_class", "") or "unknown")
    return {
        "class": material_class,
        "material_class": material_class,
        "confidence": _material_authority_float(_material_authority_external_value(row, "confidence", 0.0), 0.0),
        "evidence": tuple(_material_authority_external_value(row, "evidence", ()) or ()),
    }


def _material_authority_source_material_name_lookup(
    preview_result: MeshImportPreviewResult,
) -> Tuple[Dict[str, str], Dict[int, str]]:
    by_key: Dict[str, str] = {}
    by_index: Dict[int, str] = {}
    for section in tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ()):
        source_name = str(getattr(section, "source_material_name", "") or "").strip()
        if not source_name:
            atlas_names = tuple(
                str(name or "").strip()
                for name in tuple(getattr(section, "atlas_source_material_names", ()) or ())
                if str(name or "").strip()
            )
            if len(atlas_names) == 1:
                source_name = atlas_names[0]
        if not source_name:
            continue
        for value in (
            getattr(section, "target_submesh_name", ""),
            getattr(section, "runtime_material_name", ""),
            getattr(section, "runtime_slot_name", ""),
            getattr(section, "donor_material_name", ""),
            getattr(section, "atlas_material_name", ""),
        ):
            key = _material_key(str(value or ""))
            if key:
                by_key.setdefault(key, source_name)
        for source_index in tuple(getattr(section, "source_submesh_indices", ()) or ()):
            try:
                by_index.setdefault(int(source_index), source_name)
            except (TypeError, ValueError, OverflowError):
                continue
        for atlas_rect in tuple(getattr(section, "atlas_rects", ()) or ()):
            rect_name = str(getattr(atlas_rect, "source_material_name", "") or "").strip()
            if not rect_name:
                continue
            for source_index in tuple(getattr(atlas_rect, "source_submesh_indices", ()) or ()):
                try:
                    by_index.setdefault(int(source_index), rect_name)
                except (TypeError, ValueError, OverflowError):
                    continue
    return by_key, by_index


def _material_authority_source_texture_fact_rows(
    mesh: object,
    texture_inputs: Sequence[object],
) -> Tuple[Mapping[str, object], ...]:
    rows: List[Mapping[str, object]] = []
    seen: set[Tuple[str, str]] = set()

    def add(slot_kind: str, path_text: object, *, parameter_name: str = "", source: str = "") -> None:
        path_value = str(path_text or "").replace("\\", "/").strip()
        slot = str(slot_kind or "").strip().lower()
        if not path_value:
            return
        key = (slot, path_value.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            _material_authority_source_texture_fact_row(
                slot,
                path_value,
                parameter_name=parameter_name,
                source=source,
            )
        )

    add("base", getattr(mesh, "preview_texture_path", ""), source="preview_texture_path")
    add("normal", getattr(mesh, "preview_normal_texture_path", ""), source="preview_normal_texture_path")
    add("material", getattr(mesh, "preview_material_texture_path", ""), source="preview_material_texture_path")
    add("height", getattr(mesh, "preview_height_texture_path", ""), source="preview_height_texture_path")
    for texture_input in tuple(texture_inputs or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot = str(texture_input.slot_kind or texture_input.semantic_type or texture_input.semantic_subtype or "").strip().lower()
        source_path = texture_input.source_texture_path or texture_input.source_dds_path or texture_input.preview_texture_path
        add(
            slot or "texture",
            source_path,
            parameter_name=texture_input.parameter_name,
            source="material_input",
        )
    return tuple(rows)


def _material_authority_source_texture_fact_row(
    slot_kind: str,
    path_text: str,
    *,
    parameter_name: str = "",
    source: str = "",
) -> Mapping[str, object]:
    image_format = Path(path_text).suffix.lower().lstrip(".")
    resolution = _material_authority_source_texture_resolution(path_text)
    channel_stats = _material_authority_source_texture_channel_stats(path_text)
    return {
        "slot_kind": slot_kind,
        "parameter_name": str(parameter_name or ""),
        "texture_path": str(path_text or "").replace("\\", "/"),
        "texture_name": PurePosixPath(str(path_text or "").replace("\\", "/")).name,
        "image_format": image_format,
        "resolution": resolution,
        "channel_stats": channel_stats,
        "color_space": _material_authority_source_texture_color_space(slot_kind),
        "source": source,
        "resolution_status": "available" if len(resolution) >= 2 else "missing_or_unreadable",
        "channel_stats_status": "available" if channel_stats else "missing_or_unreadable",
    }


def _material_authority_source_texture_resolution(path_text: str) -> Tuple[int, int]:
    path_value = str(path_text or "").strip()
    if "::" in path_value:
        return _material_authority_source_zip_texture_resolution(path_value)
    path = Path(path_value).expanduser()
    if not path.is_file():
        return ()
    try:
        if path.suffix.lower() == ".dds":
            info = inspect_crimson_dds(path, vpath=path.as_posix())
            width = int(getattr(info, "width", 0) or 0)
            height = int(getattr(info, "height", 0) or 0)
            return (width, height) if width > 0 and height > 0 else ()
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return (int(width), int(height)) if width > 0 and height > 0 else ()
    except Exception:
        return ()


def _material_authority_source_zip_texture_resolution(path_text: str) -> Tuple[int, int]:
    archive_text, member_name = str(path_text or "").split("::", 1)
    archive_path = Path(archive_text).expanduser()
    member_name = member_name.replace("\\", "/").lstrip("/")
    if not archive_path.is_file() or not member_name or "../" in f"/{member_name}":
        return ()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            info = _material_authority_zip_member_info(archive, member_name)
            if info is None or info.is_dir():
                return ()
            suffix = Path(info.filename).suffix.lower()
            with archive.open(info, "r") as stream:
                if suffix == ".dds":
                    return _material_authority_dds_byte_resolution(stream.read(128))
                if int(getattr(info, "file_size", 0) or 0) > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                    return ()
                from PIL import Image

                with Image.open(io.BytesIO(stream.read())) as image:
                    width, height = image.size
                return (int(width), int(height)) if width > 0 and height > 0 else ()
    except Exception:
        return ()


def _material_authority_source_texture_channel_stats(path_text: str) -> Tuple[Tuple[str, float], ...]:
    path_value = str(path_text or "").strip()
    if "::" in path_value:
        return _material_authority_source_zip_texture_channel_stats(path_value)
    path = Path(path_value).expanduser()
    if not path.is_file():
        return ()
    try:
        if path.stat().st_size > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
            return ()
    except OSError:
        return ()
    if path.suffix.lower() == ".dds":
        try:
            stats = _material_authority_dds_channel_stats(path.read_bytes())
        except OSError:
            stats = ()
        if stats:
            return stats
    try:
        from PIL import Image

        with Image.open(path) as image:
            return _material_authority_image_channel_stats(image)
    except Exception:
        return ()


def _material_authority_source_zip_texture_channel_stats(path_text: str) -> Tuple[Tuple[str, float], ...]:
    archive_text, member_name = str(path_text or "").split("::", 1)
    archive_path = Path(archive_text).expanduser()
    member_name = member_name.replace("\\", "/").lstrip("/")
    if not archive_path.is_file() or not member_name or "../" in f"/{member_name}":
        return ()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            info = _material_authority_zip_member_info(archive, member_name)
            if info is None or info.is_dir() or int(getattr(info, "file_size", 0) or 0) > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                return ()
            with archive.open(info, "r") as stream:
                payload = stream.read()
                if Path(info.filename).suffix.lower() == ".dds":
                    stats = _material_authority_dds_channel_stats(payload)
                    if stats:
                        return stats
                from PIL import Image

                with Image.open(io.BytesIO(payload)) as image:
                    return _material_authority_image_channel_stats(image)
    except Exception:
        return ()


def _material_authority_image_channel_stats(image: object) -> Tuple[Tuple[str, float], ...]:
    try:
        from PIL import ImageStat

        rgba = image.convert("RGBA")  # type: ignore[attr-defined]
        rgba.thumbnail((256, 256))
        stat = ImageStat.Stat(rgba)
        means = [float(value) / 255.0 for value in stat.mean[:4]]
        extrema = rgba.getextrema()
        alpha_min = float(extrema[3][0]) / 255.0 if len(extrema) >= 4 else 1.0
        alpha_max = float(extrema[3][1]) / 255.0 if len(extrema) >= 4 else 1.0
        luma = (0.2126 * means[0]) + (0.7152 * means[1]) + (0.0722 * means[2])
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


def _material_authority_payload_or_file_bytes(payload: _FinalPayload, payload_bytes: bytes) -> bytes:
    if payload_bytes:
        return bytes(payload_bytes)
    source_path = getattr(payload, "source_path", Path())
    if isinstance(source_path, Path) and source_path.is_file():
        try:
            if source_path.stat().st_size <= SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                return source_path.read_bytes()
        except OSError:
            return b""
    return b""


def _material_authority_dds_channel_stats(blob: bytes) -> Tuple[Tuple[str, float], ...]:
    layout = _material_authority_uncompressed_dds_layout(blob)
    if layout is None:
        return ()
    width, height, pixel_offset, channel_order = layout
    pixel_count = min(int(width) * int(height), max(0, (len(blob) - pixel_offset) // 4))
    if pixel_count <= 0:
        return ()
    r_total = g_total = b_total = a_total = 0
    a_min = 255
    a_max = 0
    cursor = pixel_offset
    for _index in range(pixel_count):
        p0, p1, p2, p3 = blob[cursor : cursor + 4]
        cursor += 4
        if channel_order == "rgba":
            red, green, blue, alpha = p0, p1, p2, p3
        elif channel_order == "bgra":
            blue, green, red, alpha = p0, p1, p2, p3
        elif channel_order == "bgrx":
            blue, green, red, alpha = p0, p1, p2, 255
        else:
            return ()
        r_total += red
        g_total += green
        b_total += blue
        a_total += alpha
        a_min = min(a_min, alpha)
        a_max = max(a_max, alpha)
    scale = 255.0 * float(pixel_count)
    r_mean = float(r_total) / scale
    g_mean = float(g_total) / scale
    b_mean = float(b_total) / scale
    a_mean = float(a_total) / scale
    luma = (0.2126 * r_mean) + (0.7152 * g_mean) + (0.0722 * b_mean)
    return (
        ("r_mean", round(r_mean, 4)),
        ("g_mean", round(g_mean, 4)),
        ("b_mean", round(b_mean, 4)),
        ("a_mean", round(a_mean, 4)),
        ("a_min", round(float(a_min) / 255.0, 4)),
        ("a_max", round(float(a_max) / 255.0, 4)),
        ("luma_mean", round(luma, 4)),
    )


def _material_authority_uncompressed_dds_layout(blob: bytes) -> tuple[int, int, int, str] | None:
    if len(blob) < 128 or blob[:4] != b"DDS ":
        return None
    header_size = _material_authority_read_u32(blob, 4)
    if header_size != 124:
        return None
    height = _material_authority_read_u32(blob, 12)
    width = _material_authority_read_u32(blob, 16)
    if width <= 0 or height <= 0:
        return None
    pf_flags = _material_authority_read_u32(blob, 80)
    fourcc = blob[84:88]
    bit_count = _material_authority_read_u32(blob, 88)
    r_mask = _material_authority_read_u32(blob, 92)
    g_mask = _material_authority_read_u32(blob, 96)
    b_mask = _material_authority_read_u32(blob, 100)
    a_mask = _material_authority_read_u32(blob, 104)
    if (pf_flags & 0x4) and fourcc == b"DX10":
        if len(blob) < 148:
            return None
        dxgi_format = _material_authority_read_u32(blob, 128)
        if dxgi_format in {28, 29}:
            return width, height, 148, "rgba"
        if dxgi_format in {87, 91}:
            return width, height, 148, "bgra"
        if dxgi_format in {88, 93}:
            return width, height, 148, "bgrx"
        return None
    if not (pf_flags & 0x40) or bit_count != 32:
        return None
    if (r_mask, g_mask, b_mask, a_mask) == (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000):
        return width, height, 128, "rgba"
    if (r_mask, g_mask, b_mask, a_mask) == (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000):
        return width, height, 128, "bgra"
    if (r_mask, g_mask, b_mask, a_mask) == (0x00FF0000, 0x0000FF00, 0x000000FF, 0x00000000):
        return width, height, 128, "bgrx"
    return None


def _material_authority_read_u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        return 0
    return int(struct.unpack_from("<I", blob, offset)[0])


def _material_authority_zip_member_info(archive: zipfile.ZipFile, member_name: str) -> Optional[zipfile.ZipInfo]:
    try:
        return archive.getinfo(member_name)
    except KeyError:
        wanted = member_name.casefold()
        for info in archive.infolist():
            if info.filename.replace("\\", "/").casefold() == wanted:
                return info
    return None


def _material_authority_dds_byte_resolution(header: bytes) -> Tuple[int, int]:
    if len(header) < 20 or header[:4] != b"DDS ":
        return ()
    height = int.from_bytes(header[12:16], "little", signed=False)
    width = int.from_bytes(header[16:20], "little", signed=False)
    return (width, height) if width > 0 and height > 0 else ()


def _material_authority_source_texture_color_space(slot_kind: str) -> str:
    slot = str(slot_kind or "").strip().lower()
    if slot in {"base", "base_color", "albedo", "diffuse", "emissive"}:
        return "srgb"
    if slot:
        return "linear"
    return ""


def _material_authority_source_section_rows(
    mesh_index: int,
    mesh: object,
    *,
    material_name: str = "",
) -> Tuple[Mapping[str, object], ...]:
    positions = list(getattr(mesh, "positions", ()) or ())
    indices = list(getattr(mesh, "indices", ()) or ())
    texture_coordinates = list(getattr(mesh, "texture_coordinates", ()) or ())
    normals = list(getattr(mesh, "normals", ()) or ())
    if not positions and not indices:
        return ()
    source_index = _material_authority_safe_int(getattr(mesh, "source_submesh_index", -1), -1)
    section_index = source_index if source_index >= 0 else int(mesh_index)
    source_name = str(material_name or getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or f"mesh_{mesh_index}")
    runtime_material_name = str(getattr(mesh, "material_name", "") or "")
    bounds_min, bounds_max = _material_authority_bounds(positions)
    return (
        {
            "section_index": section_index,
            "source_submesh_index": source_index,
            "section_name": source_name,
            "material_name": source_name,
            "runtime_material_name": runtime_material_name if runtime_material_name != source_name else "",
            "vertex_count": len(positions),
            "face_count": len(indices) // 3,
            "has_uvs": bool(texture_coordinates and len(texture_coordinates) == len(positions)),
            "has_normals": bool(normals and len(normals) == len(positions)),
            "source_vertex_indices_count": len(tuple(getattr(mesh, "source_vertex_indices", ()) or ())),
            "bounds_min": bounds_min,
            "bounds_max": bounds_max,
        },
    )


def _material_authority_bounds(positions: Sequence[object]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    vertices = []
    for position in tuple(positions or ()):
        values = tuple(position or ()) if isinstance(position, (tuple, list)) else ()
        if len(values) < 3:
            continue
        try:
            vertices.append((float(values[0]), float(values[1]), float(values[2])))
        except (TypeError, ValueError, OverflowError):
            continue
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (
        (round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)),
        (round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)),
    )


def _material_authority_safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _material_authority_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _material_authority_source_channel_profile(
    mesh: object,
    texture_inputs: Sequence[object],
    *,
    material_name: str = "",
) -> Mapping[str, object]:
    texture_channels: set[str] = set()
    scalar_channels: set[str] = set()
    diagnostics: List[Mapping[str, object]] = []
    material_texture_subtypes: set[str] = set()

    base_path = str(getattr(mesh, "preview_texture_path", "") or "").replace("\\", "/")
    material_path = str(getattr(mesh, "preview_material_texture_path", "") or "").replace("\\", "/")
    alpha_mode = str(getattr(mesh, "preview_alpha_mode", "") or "").strip().lower()
    vertex_color_factor = _material_authority_source_tuple3(mesh, "preview_vertex_color_mean")
    vertex_alpha = _material_authority_source_vertex_alpha(mesh)
    texture_fact_rows = _material_authority_source_texture_fact_rows(mesh, texture_inputs)

    def stats_for(*slot_names: str) -> Dict[str, float]:
        wanted = {str(slot or "").strip().lower() for slot in tuple(slot_names or ()) if str(slot or "").strip()}
        for row in texture_fact_rows:
            slot = str(row.get("slot_kind", "") or "").strip().lower()
            if slot not in wanted:
                continue
            stats = {
                str(key): _material_authority_float(value, 0.0)
                for key, value in tuple(row.get("channel_stats", ()) or ())
            }
            if stats:
                return stats
        return {}

    def stats_from_row(row: Mapping[str, object]) -> Dict[str, float]:
        return {
            str(key): _material_authority_float(value, 0.0)
            for key, value in tuple(row.get("channel_stats", ()) or ())
        }

    def row_has_nonopaque_alpha(stats: Mapping[str, float]) -> bool:
        return stats.get("a_min", 1.0) < 0.98 or stats.get("a_mean", 1.0) < 0.98

    def alpha_usage_for_row(row: Mapping[str, object], stats: Mapping[str, float]) -> str:
        if not row_has_nonopaque_alpha(stats):
            return ""
        slot = str(row.get("slot_kind", "") or "").strip().lower()
        parameter_name = str(row.get("parameter_name", "") or "").strip().lower()
        text = " ".join((slot, parameter_name))
        if any(token in text for token in ("opacity", "alpha", "transparent")):
            return "visible_alpha"
        if slot in {"base", "base_color", "albedo", "diffuse", "emissive"}:
            return "visible_alpha"
        return "technical_alpha"

    if base_path:
        texture_channels.add("base_color")
    if str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
        texture_channels.add("normal")
    if str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
        texture_channels.add("height")
    subtype = str(getattr(mesh, "preview_material_texture_subtype", "") or "").strip().lower()
    if subtype:
        material_texture_subtypes.add(subtype)
        _material_authority_add_source_channel(texture_channels, subtype)
    for packed in tuple(getattr(mesh, "preview_material_texture_packed_channels", ()) or ()):
        _material_authority_add_source_channel(texture_channels, packed)

    for texture_input in tuple(texture_inputs or ()):
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
        _material_authority_add_source_channel(texture_channels, slot_kind)
        _material_authority_add_source_channel(texture_channels, semantic_subtype)
        if semantic_subtype:
            material_texture_subtypes.add(semantic_subtype)
        for packed in tuple(getattr(texture_input, "packed_channels", ()) or ()):
            _material_authority_add_source_channel(texture_channels, packed)
        parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
        _material_authority_add_source_channel(texture_channels, parameter_name)

    native_overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}
    if isinstance(native_overrides, Mapping):
        for key in tuple(native_overrides.keys()):
            normalized = str(key or "").strip().lower()
            if "roughness" in normalized:
                scalar_channels.add("roughness")
            elif "metal" in normalized:
                scalar_channels.add("metalness")
            elif "specular" in normalized:
                scalar_channels.add("specular")
            elif "gloss" in normalized:
                scalar_channels.add("glossiness")
            elif "emissive" in normalized:
                scalar_channels.add("emissive")
            elif "alpha" in normalized or "opacity" in normalized:
                scalar_channels.add("opacity")
    base_stats = stats_for("base", "base_color", "albedo")
    for row in texture_fact_rows:
        row_stats = stats_from_row(row)
        alpha_usage = alpha_usage_for_row(row, row_stats)
        if not alpha_usage:
            continue
        code = "source_alpha_from_texture_channel" if alpha_usage == "visible_alpha" else "source_packed_a_channel_technical"
        if alpha_usage == "visible_alpha":
            texture_channels.add("opacity")
        diagnostics.append(
            {
                "severity": "info",
                "code": code,
                "message": (
                    "Source texture alpha channel carries visible opacity evidence."
                    if alpha_usage == "visible_alpha"
                    else "Source packed material texture alpha channel carries technical data, not visible opacity."
                ),
                "slot_kind": str(row.get("slot_kind", "") or ""),
                "texture_name": str(row.get("texture_name", "") or ""),
                "texture_path": str(row.get("texture_path", "") or ""),
                "a_mean": round(row_stats.get("a_mean", 1.0), 4),
                "a_min": round(row_stats.get("a_min", 1.0), 4),
                "a_max": round(row_stats.get("a_max", 1.0), 4),
            }
        )
    if vertex_color_factor:
        scalar_channels.add("base_color")
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_vertex_color_present",
                "message": "Source material has vertex color data that can tint or replace base color.",
                "vertex_color_factor": vertex_color_factor,
            }
        )
    if vertex_alpha and (vertex_alpha[0] < 0.98 or vertex_alpha[1] < 0.98):
        scalar_channels.add("opacity")
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_vertex_alpha_opacity",
                "message": "Source material has vertex alpha opacity data.",
                "vertex_alpha": vertex_alpha,
            }
        )

    workflow = "specular_glossiness" if {"specular", "glossiness"}.intersection(texture_channels | scalar_channels) or "specular_glossiness" in material_texture_subtypes else "metallic_roughness"
    derived_channels: set[str] = set()
    effective_channels = texture_channels | scalar_channels
    if workflow == "specular_glossiness":
        if "glossiness" in effective_channels:
            derived_channels.add("roughness")
        if "specular" in effective_channels:
            derived_channels.add("metalness")
        if derived_channels:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "source_spec_gloss_derived_material_channels",
                    "message": "Specular/glossiness source channels will derive roughness/metalness for Crimson material masks.",
                    "derived_channels": tuple(sorted(derived_channels)),
                }
            )
    effective_channels = effective_channels | derived_channels
    if "base_color" not in texture_channels:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_missing_base_color",
                "message": "Source material has no base-color texture in the package preview model.",
            }
        )
    if alpha_mode in {"blend", "mask", "alpha", "transparent", "coverage", "cutout"} and "opacity" not in texture_channels and "opacity" not in scalar_channels:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_alpha_without_opacity_texture",
                "message": "Source material declares alpha but no opacity/alpha texture slot is present.",
                "alpha_mode": alpha_mode,
            }
        )
    if "emissive" in scalar_channels and "emissive" not in texture_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_emissive_scalar_no_texture",
                "message": "Source material has emissive scalar/color data but no emissive texture.",
            }
        )
    missing_channels = [
        channel
        for channel in ("emissive", "roughness", "metalness")
        if channel not in effective_channels
    ]
    if "roughness" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_roughness",
                "message": "Source material has no roughness texture or scalar hint; preview/export must use defaults or target response.",
            }
        )
    if "metalness" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_metalness",
                "message": "Source material has no metalness texture or scalar hint; preview/export must use defaults or target response.",
            }
        )
    if "emissive" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_emissive",
                "message": "Source material has no emissive texture or scalar hint.",
            }
        )
    if _material_authority_spec_gloss_base_conflict(base_path, material_path, material_texture_subtypes):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_spec_gloss_texture_as_base_color",
                "message": "Specular/gloss texture appears to be used as base color; verify source workflow routing.",
            }
        )

    detected = tuple(sorted(texture_channels | derived_channels | {f"{channel}_scalar" for channel in scalar_channels}))
    return {
        "workflow": workflow,
        "detected_channels": detected,
        "texture_channels": tuple(sorted(texture_channels)),
        "scalar_channels": tuple(sorted(scalar_channels)),
        "derived_channels": tuple(sorted(derived_channels)),
        "vertex_color_factor": vertex_color_factor,
        "vertex_alpha": vertex_alpha,
        "missing_channels": tuple(missing_channels),
        "material_classification": _material_authority_source_classification(
            texture_channels=texture_channels,
            scalar_channels=scalar_channels,
            alpha_mode=alpha_mode,
            workflow=workflow,
            material_name=str(material_name or getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or ""),
            double_sided=bool(getattr(mesh, "preview_double_sided", False)),
            vertex_color_factor=vertex_color_factor,
            vertex_alpha=vertex_alpha,
            base_texture_stats=base_stats,
            material_texture_stats=stats_for("material", "metallic_roughness"),
            metalness_texture_stats=stats_for("metalness", "metallic"),
        ),
        "diagnostics": tuple(diagnostics),
        "double_sided": bool(getattr(mesh, "preview_double_sided", False)),
    }


def _material_authority_source_tuple3(mesh: object, attr_name: str) -> Tuple[float, float, float]:
    values = tuple(getattr(mesh, attr_name, ()) or ())
    if len(values) < 3:
        return ()
    try:
        return tuple(round(max(0.0, min(1.0, float(value))), 4) for value in values[:3])  # type: ignore[return-value]
    except (TypeError, ValueError, OverflowError):
        return ()


def _material_authority_source_vertex_alpha(mesh: object) -> Tuple[float, float]:
    mean_value = getattr(mesh, "preview_vertex_alpha_mean", None)
    min_value = getattr(mesh, "preview_vertex_alpha_min", None)
    if mean_value is None and min_value is None:
        return ()
    try:
        alpha_mean = round(max(0.0, min(1.0, float(1.0 if mean_value is None else mean_value))), 4)
        alpha_min = round(max(0.0, min(1.0, float(alpha_mean if min_value is None else min_value))), 4)
        return (alpha_mean, alpha_min)
    except (TypeError, ValueError, OverflowError):
        return ()


def _material_authority_add_source_channel(channels: set[str], value: object) -> None:
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    if not text:
        return
    if any(token in text for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "base")):
        channels.add("base_color")
    if "normal" in text:
        channels.add("normal")
    if any(token in text for token in ("emissive", "emission", "glow", "illum")):
        channels.add("emissive")
    if any(token in text for token in ("opacity", "alpha", "transparent")):
        channels.add("opacity")
    if any(token in text for token in ("roughness", "rough")):
        channels.add("roughness")
    if any(token in text for token in ("metallic", "metalness", "metal")):
        channels.add("metalness")
    if text in {"ao", "aopbr"} or "occlusion" in text:
        channels.add("ao")
    if "specular" in text or text.endswith("spec"):
        channels.add("specular")
    if "glossiness" in text or "gloss" in text:
        channels.add("glossiness")
    if "height" in text or "displacement" in text or "bump" in text:
        channels.add("height")


def _material_authority_spec_gloss_base_conflict(
    base_path: str,
    material_path: str,
    material_texture_subtypes: set[str],
) -> bool:
    base_name = PurePosixPath(str(base_path or "")).name.lower()
    if not base_name:
        return False
    if any(token in base_name for token in ("speculargloss", "specular_gloss", "specular", "glossiness", "gloss")):
        return True
    if _normalize_final_path(base_path) == _normalize_final_path(material_path) and material_texture_subtypes.intersection({"specular", "glossiness", "specular_glossiness"}):
        return True
    return False


def _material_authority_source_classification(
    *,
    texture_channels: set[str],
    scalar_channels: set[str],
    alpha_mode: str,
    workflow: str,
    material_name: str,
    double_sided: bool = False,
    vertex_color_factor: Sequence[float] = (),
    vertex_alpha: Sequence[float] = (),
    base_texture_stats: Optional[Mapping[str, object]] = None,
    material_texture_stats: Optional[Mapping[str, object]] = None,
    metalness_texture_stats: Optional[Mapping[str, object]] = None,
) -> Tuple[Mapping[str, object], ...]:
    classes: List[Mapping[str, object]] = []
    raw_name = str(material_name or "")
    split_name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_name)
    name = split_name.lower()
    tokens = set(re.findall(r"[a-z0-9]+", name))
    compact_tokens = {
        re.sub(r"[^a-z0-9]+", "", token)
        for token in re.split(r"[\s._/\-\\]+", raw_name.lower())
        if re.sub(r"[^a-z0-9]+", "", token)
    }
    tokens.update(compact_tokens)

    def add(material_class: str, confidence: float, evidence: str) -> None:
        for index, existing in enumerate(classes):
            if existing.get("class") != material_class:
                continue
            if confidence > float(existing.get("confidence", 0.0) or 0.0):
                classes[index] = {"class": material_class, "confidence": confidence, "evidence": evidence}
            return
        classes.append({"class": material_class, "confidence": confidence, "evidence": evidence})

    def has_any(*terms: str) -> bool:
        wanted = {str(term or "").strip().lower() for term in terms if str(term or "").strip()}
        if tokens & wanted:
            return True
        for token in tokens:
            for term in wanted:
                if len(term) >= 5 and (token.startswith(term) or token.endswith(term)):
                    return True
        return False

    if "emissive" in texture_channels or "emissive" in scalar_channels or any(token in name for token in ("emissive", "glow", "lamp", "light")):
        add("emissive", 0.82, "emissive channel or material name")
    if "opacity" in texture_channels or "opacity" in scalar_channels or alpha_mode in {"blend", "mask", "transparent", "cutout"}:
        add("transparent_or_cutout", 0.75, "alpha/opacity channel or alpha mode")
    metal_evidence = "metalness" in texture_channels or "metalness" in scalar_channels or has_any(
        "metal",
        "steel",
        "iron",
        "silver",
        "chrome",
        "blade",
        "sword",
        "armor",
        "armour",
        "gold",
        "bronze",
        "brass",
        "copper",
    )
    if metal_evidence:
        add("metal", 0.68, "metalness channel or metal material name")
    base_stats_map = dict(base_texture_stats or {})
    material_stats_map = dict(material_texture_stats or {})
    metalness_stats_map = dict(metalness_texture_stats or {})
    material_metalness_mean = _material_authority_float(material_stats_map.get("b_mean"), 0.0)
    if material_metalness_mean >= 0.45:
        metal_evidence = True
        add("metal", 0.70, f"metallic-roughness B channel mean {material_metalness_mean:.2f}")
    metalness_luma = _material_authority_float(metalness_stats_map.get("luma_mean"), 0.0)
    if metalness_luma >= 0.45:
        metal_evidence = True
        add("metal", 0.70, f"metalness texture mean {metalness_luma:.2f}")
    if metal_evidence and has_any("painted", "paint", "paintjob", "coated", "enamel"):
        add("painted_metal", 0.70, "painted/coated token with metal evidence")
    if has_any("gold", "gilded"):
        add("gold", 0.90, "gold material/name token")
    if has_any("bronze", "brass"):
        add("bronze", 0.88, "bronze/brass material/name token")
    if has_any("copper"):
        add("copper", 0.88, "copper material/name token")
    if has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment"):
        add("cloth", 0.80, "cloth/fabric material/name token")
    if double_sided and has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment", "cape", "flag"):
        add("cloth", 0.82, "double-sided fabric surface")
    if has_any("leather", "hide", "suede"):
        add("leather", 0.85, "leather material/name token")
    if has_any("wood", "wooden", "timber", "oak", "pine", "walnut", "bark"):
        add("wood", 0.85, "wood material/name token")
    if has_any("stone", "rock", "granite", "marble", "concrete", "slate", "ceramic"):
        add("stone", 0.85, "stone/rock material/name token")
    if has_any("skin", "organic", "flesh", "body", "face", "hand", "arm", "leg", "head"):
        add("skin_organic", 0.82, "skin/organic material/name token")
    if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent", "transmission"):
        add("glass_crystal", 0.86, "glass/crystal material/name token")
    if (
        ("opacity" in texture_channels or "opacity" in scalar_channels or alpha_mode in {"blend", "mask", "transparent", "cutout"})
        and has_any("glass", "crystal", "gem", "lens", "pane", "window")
    ):
        add("glass_crystal", 0.88, "alpha/transparency evidence with glass/crystal token")
    base_rgb = ()
    if {"r_mean", "g_mean", "b_mean"} <= set(base_stats_map.keys()):
        base_rgb = (
            _material_authority_float(base_stats_map.get("r_mean"), 0.0),
            _material_authority_float(base_stats_map.get("g_mean"), 0.0),
            _material_authority_float(base_stats_map.get("b_mean"), 0.0),
        )
    if base_rgb and metal_evidence:
        r, g, b = base_rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.62, f"metal source with yellow base texture mean {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.54, f"metal source with warm base texture mean {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.48, f"metal source with bronze-like base texture mean {r:.2f},{g:.2f},{b:.2f}")
    alpha_min = _material_authority_float(base_stats_map.get("a_min"), 1.0)
    alpha_mean = _material_authority_float(base_stats_map.get("a_mean"), 1.0)
    if (
        (alpha_min < 0.98 or alpha_mean < 0.98)
        and not any(row.get("class") == "transparent_or_cutout" for row in classes)
    ):
        add("transparent_or_cutout", 0.68, "source base texture alpha channel")
        if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent"):
            add("glass_crystal", 0.72, "source base alpha with glass/crystal token")
    vertex_rgb = tuple(float(value) for value in tuple(vertex_color_factor or ())[:3]) if len(tuple(vertex_color_factor or ())) >= 3 else ()
    if vertex_rgb and metal_evidence:
        r, g, b = vertex_rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.60, "metal source with yellow vertex color")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.50, "metal source with warm vertex color")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.45, "metal source with bronze-like vertex color")
    vertex_alpha_values = tuple(float(value) for value in tuple(vertex_alpha or ())[:2]) if len(tuple(vertex_alpha or ())) >= 2 else ()
    if (
        vertex_alpha_values
        and (vertex_alpha_values[0] < 0.98 or vertex_alpha_values[1] < 0.98)
        and not any(row.get("class") == "transparent_or_cutout" for row in classes)
    ):
        add("transparent_or_cutout", 0.68, "vertex alpha opacity")
        if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent"):
            add("glass_crystal", 0.72, "vertex alpha with glass/crystal token")
    if workflow == "specular_glossiness":
        add("specular_glossiness_source", 0.78, "specular/glossiness workflow")
    if not classes:
        add("generic_surface", 0.35, "no specific source PBR class evidence")
    return tuple(classes)


def _material_authority_risk_flags(
    *,
    binding_rows: Sequence[FinalPackageBindingRow],
    texture_outputs: Sequence[Mapping[str, object]],
    sidecar_reports: Sequence[Mapping[str, object]],
    source_materials: Sequence[Mapping[str, object]],
    unknowns: Sequence[Mapping[str, object]],
    inherited_count: int,
    warnings: Sequence[str],
    preflight_errors: Sequence[str],
    require_source_owned_colors: bool,
) -> Tuple[str, ...]:
    flags: List[str] = []
    if preflight_errors:
        flags.append("preflight_blockers")
    if any(row.status == FINAL_PREVIEW_MISSING_DDS for row in tuple(binding_rows or ())):
        flags.append("missing_final_dds")
    if any(row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC for row in tuple(binding_rows or ())):
        flags.append("path_mismatch_basename_only")
    if any(bool(row.get("stock_or_shared")) for row in tuple(texture_outputs or ())):
        flags.append("stock_shared_texture_override")
    for row in tuple(texture_outputs or ()):
        validation = row.get("dds_validation")
        if isinstance(validation, Mapping):
            validation_status = str(validation.get("status", "") or "").strip().lower()
            dds_format = str(validation.get("dds_format", "") or "").strip()
            try:
                width = int(validation.get("width", 0) or 0)
                height = int(validation.get("height", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                width = 0
                height = 0
            if validation_status in {"invalid", "error", "missing_payload"}:
                flags.append("invalid_dds_payload")
            if width <= 0 or height <= 0:
                flags.append("missing_dds_dimensions")
            if not dds_format:
                flags.append("missing_dds_format")
            if bool(validation.get("requires_pathc")):
                flags.append("dds_requires_pathc")
            finding_codes = {
                str(finding.get("code", "") or "")
                for finding in tuple(validation.get("findings", ()) or ())
                if isinstance(finding, Mapping)
            }
            if "missing_mips" in finding_codes:
                flags.append("missing_dds_mips")
            if "payload_truncated" in finding_codes:
                flags.append("truncated_dds_payload")
        role_codes = {
            str(diagnostic.get("code", "") or "")
            for diagnostic in tuple(row.get("role_diagnostics", ()) or ())
            if isinstance(diagnostic, Mapping)
        }
        if "normal_format_not_bc5" in role_codes or "normal_srgb_format" in role_codes:
            flags.append("normal_format_mismatch")
        if "normal_y_policy_unconfirmed" in role_codes:
            flags.append("normal_y_policy_unconfirmed")
        if "base_texture_used_as_emissive" in role_codes:
            flags.append("base_texture_used_as_emissive")
        if "texture_bound_to_visible_and_technical_roles" in role_codes:
            flags.append("visible_technical_role_conflict")
        if "multi_role_texture_binding" in role_codes:
            flags.append("ambiguous_texture_role_binding")
        if "visible_color_technical_format" in role_codes:
            flags.append("visible_color_format_mismatch")
        if "technical_slot_srgb_format" in role_codes:
            flags.append("technical_slot_srgb_format")
        conversion_policy = row.get("conversion_policy")
        role_classes = {
            str(value or "").strip().lower()
            for value in tuple(conversion_policy.get("bound_role_classes", ()) if isinstance(conversion_policy, Mapping) else ())
            if str(value or "").strip()
        }
        luma_mean = _material_authority_float(row.get("visible_luma_mean"), -1.0)
        if "base_color" in role_classes and 0.0 <= luma_mean < 45.0:
            flags.append("dark_visible_color_output")
    for material in tuple(source_materials or ()):
        section_rows = tuple(row for row in tuple(material.get("sections", ()) or ()) if isinstance(row, Mapping))
        if not section_rows:
            flags.append("missing_source_material_sections")
        for section in section_rows:
            try:
                vertex_count = int(section.get("vertex_count", 0) or 0)
                face_count = int(section.get("face_count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                vertex_count = 0
                face_count = 0
            if vertex_count <= 0 or face_count <= 0:
                flags.append("source_material_section_missing_geometry")
        diagnostic_codes = {
            str(diagnostic.get("code", "") or "")
            for diagnostic in tuple(material.get("diagnostics", ()) or ())
            if isinstance(diagnostic, Mapping)
        }
        missing_channels = {
            str(channel)
            for channel in tuple(material.get("missing_channels", ()) or ())
            if str(channel).strip()
        }
        if "source_missing_base_color" in diagnostic_codes:
            flags.append("source_missing_base_color")
        if "source_alpha_without_opacity_texture" in diagnostic_codes:
            flags.append("source_alpha_missing_opacity")
        if "source_spec_gloss_texture_as_base_color" in diagnostic_codes or "source_spec_gloss_texture_bound_as_base" in diagnostic_codes:
            flags.append("source_spec_gloss_base_conflict")
        if "source_base_texture_bound_as_emissive" in diagnostic_codes:
            flags.append("base_texture_used_as_emissive")
        if "source_material_response_texture_bound_as_base" in diagnostic_codes:
            flags.append("visible_technical_role_conflict")
        if "source_base_texture_bound_as_normal" in diagnostic_codes:
            flags.append("normal_slot_suspicious")
        if {"roughness", "metalness"}.issubset(missing_channels):
            flags.append("source_missing_roughness_metalness")
        if "source_emissive_scalar_no_texture" in diagnostic_codes:
            flags.append("source_emissive_scalar_no_texture")
    if inherited_count:
        flags.append("inherited_target_influence")
    if unknowns:
        flags.append("unknown_material_response")
    if require_source_owned_colors and not sidecar_reports:
        flags.append("missing_material_sidecar")
    warning_text = "\n".join(str(warning) for warning in tuple(warnings or ())).lower()
    for token, flag in (
        ("orphan dds", "orphan_dds"),
        ("draw-order fallback", "preview_draw_order_fallback"),
        ("fewer visible texture", "preview_export_mismatch"),
        ("not referenced by parsed material sidecar", "orphan_dds"),
        ("normal-looking", "normal_slot_suspicious"),
    ):
        if token in warning_text:
            flags.append(flag)
    return tuple(_dedupe(flags))
