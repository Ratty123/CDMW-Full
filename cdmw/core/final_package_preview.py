from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import shutil
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding import (
    ARCHIVE_MESH_EXTENSIONS,
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
    _mesh_loose_export_payload_path,
    parsed_mesh_to_preview_model,
)
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.upscale_profiles import (
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds
from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialTextureInput
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.mesh_parser import _find_pac_descriptors, _parse_par_sections, parse_mesh
from cdmw.modding.pac_xml_profiles import (
    build_pac_xml_material_authority_report,
    compare_pac_xml_material_authority_structure,
)
from cdmw.rendering.asset_fidelity_preflight import normal_y_policy_report


FINAL_PREVIEW_READY = "ready"
FINAL_PREVIEW_MISSING_BASE = "missing_base"
FINAL_PREVIEW_MISSING_DDS = "missing_dds"
FINAL_PREVIEW_DECODE_FAILED = "decode_failed"
FINAL_PREVIEW_SUPPORT_MAPS_ONLY = "support_maps_only"
FINAL_PREVIEW_ADVANCED_SHADER_ONLY = "advanced_shader_only"

FINAL_PREVIEW_BINDING_GENERATED = "generated"
FINAL_PREVIEW_BINDING_ORIGINAL = "original"
FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC = "basename_diagnostic"
FINAL_PREVIEW_BINDING_MISSING = "missing"

FINAL_PREVIEW_PACKAGE_SIDE_EFFECT_EXTENSIONS = (
    ".json",
    ".txt",
    ".md",
    ".ini",
)

SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS = (
    "grime",
    "detaildiffuse",
    "detailmask",
    "detailnormal",
    "detailheight",
    "detailmaterial",
    "dyeing",
    "texturelayer",
    "damage",
    "heighttexture",
    "materialtexture",
    "colorblending",
)


MATERIAL_PREFLIGHT_OVERRIDE_WARNING = (
    "Material preflight override used; in-game result may inherit original tint/gloss/layers or render grey/missing textures."
)


MATERIAL_PREFLIGHT_HARD_BLOCKER_TOKENS = (
    "visible color texture is not package-resolved",
    "exact texture path mismatch",
    "support map is bound as visible base color",
    "support map path is assigned to a visible color parameter",
    "pac runtime abi",
    "wrapper was emitted outside _submeshresources",
    "duplicates skinnedmeshmaterialwrapper itemid",
    "duplicates material parameter itemid",
    "material shader name is the source material label",
    "_submeshresources idbase",
    "_submeshresources wrapper order does not match",
)


@dataclass(slots=True, frozen=True)
class FinalPackageBindingRow:
    material_name: str
    part_name: str
    role: str
    parameter_name: str
    sidecar_path: str
    texture_path: str
    resolved_texture_path: str = ""
    status: str = FINAL_PREVIEW_MISSING_DDS
    material_status: str = FINAL_PREVIEW_MISSING_BASE
    confidence: str = "exact"
    binding_source: str = FINAL_PREVIEW_BINDING_MISSING
    detail: str = ""
    preview_texture_path: str = ""

@dataclass(slots=True, frozen=True)
class TextureResolutionManifestRow:
    material_name: str
    submesh_name: str
    role: str
    parameter_name: str
    sidecar_path: str
    requested_texture_path: str
    resolved_texture_path: str = ""
    binding_source: str = FINAL_PREVIEW_BINDING_MISSING
    status: str = FINAL_PREVIEW_MISSING_DDS
    reason: str = ""
    skipped_reason: str = ""


@dataclass(slots=True, frozen=True)
class TextureResolutionManifest:
    schema: str = "cdmw_texture_resolution_manifest_v1"
    rows: Tuple[TextureResolutionManifestRow, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "rows": [dataclasses.asdict(row) for row in self.rows],
            "warnings": list(self.warnings),
        }

from .final_package_material_authority import (
    FinalPackageMaterialAuthorityReport,
    FinalPackageMaterialStatus,
    _build_material_authority_report,
    _material_authority_sidecar_output_row,
    _material_authority_sidecar_edit_summary,
    _material_authority_sidecar_structural_compare,
    _material_authority_sidecar_texture_ref_changes,
    _material_authority_sidecar_binding_key,
    _material_authority_sidecar_change_row,
    _material_authority_preview_settings,
    _material_authority_render_normal_y_mode,
    _material_authority_texture_output_row,
    _sha256_file_evidence,
    _material_authority_texture_binding_rows,
    _material_authority_texture_conversion_policy,
    _material_authority_dds_validation,
    _material_authority_visible_luma_mean,
    _material_authority_dds_channel_order,
    _material_authority_texture_role_diagnostics,
    _material_authority_texture_channel_visualization,
    _material_authority_packed_channel_semantics,
    _material_authority_bound_source_material_rows,
    _material_authority_source_row_workflow,
    _material_authority_source_row_derived_channels,
    _material_authority_source_row_packed_channels,
    _material_authority_source_row_route_diagnostics,
    _material_authority_dedupe_source_route_diagnostics,
    _material_authority_source_packed_channel_semantics,
    _material_authority_bound_role_classes,
    _material_authority_source_normal_space,
    _material_authority_routing_row,
    _material_authority_target_section_rows,
    _material_authority_source_material_rows,
    _material_authority_source_material_rows_for_report,
    _material_authority_external_source_material_rows,
    _material_authority_fbx_source_material_rows,
    _material_authority_external_value,
    _material_authority_mapping_items,
    _material_authority_external_inventory_source_row,
    _material_authority_external_texture_slot_row,
    _material_authority_external_texture_fact_row,
    _material_authority_external_section_row,
    _material_authority_external_class_row,
    _material_authority_source_material_name_lookup,
    _material_authority_source_texture_fact_rows,
    _material_authority_source_texture_fact_row,
    _material_authority_source_texture_resolution,
    _material_authority_source_zip_texture_resolution,
    _material_authority_source_texture_channel_stats,
    _material_authority_source_zip_texture_channel_stats,
    _material_authority_image_channel_stats,
    _material_authority_payload_or_file_bytes,
    _material_authority_dds_channel_stats,
    _material_authority_uncompressed_dds_layout,
    _material_authority_read_u32,
    _material_authority_zip_member_info,
    _material_authority_dds_byte_resolution,
    _material_authority_source_texture_color_space,
    _material_authority_source_section_rows,
    _material_authority_bounds,
    _material_authority_safe_int,
    _material_authority_float,
    _material_authority_source_channel_profile,
    _material_authority_source_tuple3,
    _material_authority_source_vertex_alpha,
    _material_authority_add_source_channel,
    _material_authority_spec_gloss_base_conflict,
    _material_authority_source_classification,
    _material_authority_risk_flags,
)

from .final_package_texture_plan import (
    CDMaterialBindingContract,
    DdsOverrideTableRow,
    ReplacementTexturePlanRow,
    TEXTURE_PLAN_STATUS_IGNORED_ADVANCED,
    TEXTURE_PLAN_STATUS_LIKELY_GREY,
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    TexturePlanStatus,
    _assign_row_to_meshes,
    _assign_unmatched_visible_textures_by_order,
    _binding_row_is_exact_generated_ready,
    _binding_row_is_preserved_layer_color,
    _binding_row_is_relief_support_only,
    _binding_row_is_source_visible_authority,
    _binding_row_parameter_key,
    _dedupe,
    _fallback_assignment_detail,
    _is_stock_or_shared_texture_path,
    _looks_like_normal_source_path,
    _looks_like_normal_texture_path,
    _preview_result_texture_contract_warnings,
    _rows_for_source_owned_contract,
    _slot_role,
    _source_expected_support_roles_for_contract,
    _source_material_expected_support_roles,
    _source_material_rows_by_key,
    _source_owned_material_binding_contract,
    _source_owned_section_source_material_names,
    _visible_preview_texture_count,
    build_dds_override_table_row,
    build_replacement_texture_plan_rows,
    texture_plan_control_description,
    texture_plan_role_label,
    texture_plan_status_for_material,
    texture_plan_status_for_slot,
    _add_expected_support_channel,
    _basename_or_text,
)

from .final_package_preview_model import (
    _PART_LABEL_ALIASES,
    _PART_LABEL_IGNORED_TOKENS,
    _PART_LABEL_PRIORITY,
    _clear_texture_slots,
    _clone_preview_model,
    _decode_sidecar_bytes,
    _display_path,
    _final_payload_path,
    _is_dds_spec,
    _is_sidecar_spec,
    _material_label_for_mesh,
    _material_semantics_for_binding,
    _normalize_final_path,
    _payload_preview_file,
    _preview_texture_path_for_original,
    _preview_texture_path_for_payload,
    _rebuilt_preview_model,
    _spec_payload_bytes,
    _spec_payload_text,
    _spec_source_file_text,
    simplified_part_label,
)

from .final_package_pac_xml_preflight import (
    _binding_material_name,
    _candidate_mesh_indices,
    _material_key,
    _material_loose_key,
    _pac_runtime_abi_preflight_errors,
    _pac_xml_material_shader_name_errors,
    _pac_xml_material_wrapper_structure_errors,
    _pac_xml_submesh_resource_idbase_errors,
    _pac_xml_submesh_resource_order_errors,
    _pac_xml_submesh_resource_wrapper_names,
)


@dataclass(slots=True)
class FinalPackagePreviewResult:
    preview_model: ModelPreviewData
    binding_rows: Tuple[FinalPackageBindingRow, ...] = ()
    warnings: List[str] = field(default_factory=list)
    preflight_errors: List[str] = field(default_factory=list)
    likely_grey_materials: List[str] = field(default_factory=list)
    missing_texture_paths: List[str] = field(default_factory=list)
    summary_lines: List[str] = field(default_factory=list)
    material_statuses: Tuple[FinalPackageMaterialStatus, ...] = ()
    texture_resolution_manifest: TextureResolutionManifest = field(default_factory=TextureResolutionManifest)
    material_authority_report: FinalPackageMaterialAuthorityReport = field(default_factory=FinalPackageMaterialAuthorityReport)
    package_root: str = ""


def material_preflight_hard_blockers(lines: Sequence[str]) -> Tuple[str, ...]:
    """Return material preflight blockers that are unsafe to bypass."""

    hard: List[str] = []
    for line in tuple(lines or ()):
        text = str(line or "").strip()
        if not text:
            continue
        normalized = text.casefold()
        if any(token in normalized for token in MATERIAL_PREFLIGHT_HARD_BLOCKER_TOKENS):
            hard.append(text)
    return tuple(_dedupe(hard))


def apply_material_preflight_override(result: FinalPackagePreviewResult, *, include_hard: bool = False) -> Tuple[str, ...]:
    """Downgrade overridable material preflight errors to warnings.

    Returns hard blockers that were left in place.
    """

    blockers = tuple(str(line) for line in tuple(getattr(result, "preflight_errors", ()) or ()) if str(line or "").strip())
    hard = material_preflight_hard_blockers(blockers)
    if not blockers or (hard and not include_hard):
        return hard
    if MATERIAL_PREFLIGHT_OVERRIDE_WARNING not in result.warnings:
        result.warnings.append(MATERIAL_PREFLIGHT_OVERRIDE_WARNING)
    for line in blockers:
        warning = f"Unsafe material preflight override: {line}"
        if warning not in result.warnings:
            result.warnings.append(warning)
    result.preflight_errors.clear()
    return ()


@dataclass(slots=True)
class _FinalPayload:
    final_path: str
    basename: str
    source_path: Path
    payload_data: bytes = b""
    kind: str = ""
    note: str = ""


@dataclass(slots=True, frozen=True)
class _FinalTextureBinding:
    texture_path: str
    parameter_name: str = ""
    material_name: str = ""
    part_name: str = ""
    submesh_name: str = ""


def _build_texture_resolution_manifest(
    binding_rows: Sequence[FinalPackageBindingRow],
    warnings: Sequence[str],
) -> TextureResolutionManifest:
    manifest_rows: List[TextureResolutionManifestRow] = []
    for row in binding_rows:
        requested = str(row.texture_path or "")
        normalized_requested = requested.replace("\\", "/").lower()
        skipped_reason = ""
        if "nonetexture" in normalized_requested or "none_texture" in normalized_requested:
            skipped_reason = "engine null texture sentinel"
        elif row.status == FINAL_PREVIEW_MISSING_DDS:
            skipped_reason = "missing final DDS payload"
        elif row.status == FINAL_PREVIEW_ADVANCED_SHADER_ONLY:
            skipped_reason = "advanced/support shader binding"
        manifest_rows.append(
            TextureResolutionManifestRow(
                material_name=row.material_name,
                submesh_name=row.part_name or row.material_name,
                role=row.role,
                parameter_name=row.parameter_name,
                sidecar_path=row.sidecar_path,
                requested_texture_path=requested,
                resolved_texture_path=row.resolved_texture_path,
                binding_source=row.binding_source,
                status=row.status,
                reason=row.detail,
                skipped_reason=skipped_reason,
            )
        )
    return TextureResolutionManifest(
        rows=tuple(manifest_rows),
        warnings=tuple(str(warning) for warning in warnings),
    )


from .final_package_builder import (
    _package_spec_kind_for_path,
    _is_final_preview_payload_file,
    _is_mesh_payload_spec,
    _spec_payload_raw_bytes,
    _package_rebuilt_mesh_data,
    _package_specs_from_manifest,
    build_final_package_specs_from_package_root,
    stage_final_package_preview_payloads,
    build_final_package_preview,
)
