"""Compatibility facade for resident .NET material-state helpers."""

from __future__ import annotations

# Keep the historical module namespace import-compatible. Material ownership is
# split across focused modules below; this facade deliberately defines no logic.
import copy
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from cdmw.core.dds_native import inspect_dds_native_path
from cdmw.domain.mesh.material_resource_policy import (
    canonical_material_channel,
    mesh_material_resource_policy,
)
from cdmw.domain.mesh.normal_y_policy import resolve_preview_normal_y_policy
from cdmw.modding.asset_replacement import infer_cd_texture_role_from_path
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.rendering.crimson_shader_registry import (
    decode_crimson_texture_binding,
    infer_shader_family_contract,
    normalize_shader_family,
)
from cdmw.rendering.native_preview_material_contract import sidecar_preview_texture_tint_for_batch
from cdmw.services.mesh_dotnet_material_bindings import (
    _DOTNET_NATIVE_MATERIAL_OVERRIDE_KEYS,
    _DOTNET_PREVIEW_MATERIAL_ATTRS,
    _dotnet_material_name,
    _dotnet_material_sources,
    _dotnet_texture_name,
    _native_material_descriptor_path,
    _native_packed_channel_semantics,
    _safe_int,
    apply_dotnet_native_material_batch_binding,
    copy_dotnet_preview_material_bindings,
    defer_dotnet_preview_material_synthesis,
    set_dotnet_preview_texture_flip_vertical,
)
from cdmw.services.mesh_dotnet_material_channels import (
    _COMPONENT_NAMES,
    _color3,
    _dotnet_crimson_material_input_decode,
    _dotnet_emissive_texture_is_scalar_mask,
    _dotnet_emissive_texture_is_scalar_mask_cached,
    _dotnet_initial_material_parameters,
    _dotnet_material_channel_components,
    _dotnet_material_input_channels,
    _dotnet_material_normal_y_policy,
    _dotnet_resolved_texture_channels,
    _finite_float,
    _has_authoritative_color_input,
    _material_parameter_value,
    _material_texture_metadata,
    _normalized_color_space,
    _reroute_technical_color_fallback,
    _same_texture_reference,
)
from cdmw.services.mesh_dotnet_material_payload import (
    _dotnet_manifest_resource_bindings,
    _dotnet_material_resource,
    _material_profile_name,
    _resource_channel_rank,
    mesh_dotnet_material_state_payload,
    mesh_dotnet_texture_resource_id,
)
from cdmw.services.mesh_dotnet_material_semantics import (
    _dotnet_material_semantic_contract,
    _source_file_stat_key,
    mesh_dotnet_material_input_signature,
)


__all__ = [
    "apply_dotnet_native_material_batch_binding",
    "copy_dotnet_preview_material_bindings",
    "defer_dotnet_preview_material_synthesis",
    "mesh_dotnet_material_input_signature",
    "mesh_dotnet_material_state_payload",
    "mesh_dotnet_texture_resource_id",
    "set_dotnet_preview_texture_flip_vertical",
]
