"""Isolated Rust Mesh Editor session, package, and atomic publication boundary.

The Rust process never receives the live :class:`MeshService`.  It edits an
owned package backed by a second service and the result crosses into the live
session only through ``prepare_working_mesh_replacement`` followed by one
revision-checked commit.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import tempfile
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from ctypes import wintypes
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from functools import wraps
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from uuid import uuid4

from cdmw.core.archive import ensure_archive_preview_source
from cdmw.core.common import (
    read_file_bytes_cancellable,
)
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.authoring_capability import (
    MeshOutputPolicy,
    action_authoring_capability,
)
from cdmw.modding.mesh_glb_interchange import import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import (
    PAC_SKIN_WEIGHT_LAYOUT,
    ParsedMesh,
    resolve_pac_bone_palette,
)
from cdmw.models import ArchiveEntry
from cdmw.rendering.crimson_shader_registry import normalize_shader_family
from cdmw.rendering.material_category_contract import (
    MATERIAL_CATEGORY_UNCLASSIFIED,
    is_known_material_category,
    material_category_code,
)
from cdmw.services.material_authority_resource_service import (
    _encode_owned_dds,
    _encode_owned_image_dds_batch,
)
from cdmw.services.mesh_dotnet_material_bindings import (
    _DOTNET_PREVIEW_MATERIAL_ATTRS,
    copy_dotnet_preview_material_bindings,
    count_dotnet_own_material_bindings,
)
from cdmw.services.mesh_dotnet_material_package import (
    compile_mesh_dotnet_material_manifest,
)
from cdmw.services.mesh_dotnet_material_state import (
    mesh_dotnet_material_state_payload,
)
from cdmw.services.mesh_free_edit_output import publish_free_edit_output
from cdmw.services.mesh_morph_profiles import mesh_morph_profile_root
from cdmw.services.mesh_refit_loading import append_refit_mesh, stage_refit_morph_runtime
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_AUTHORING_PACKAGE,
    RUST_MESH_CANDIDATE,
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_BINARY,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_MAX_PAYLOAD_BYTES,
    RUST_MESH_RENDERER,
    RustMeshExecutableResolution,
    resolve_rust_mesh_editor,
    rust_mesh_editor_candidate_paths,
)
from cdmw.services.mesh_service import (
    MeshService,
    _dispose_history_snapshot,
    _geometry_layers_from_project_payload,
)
from cdmw.services.mesh_service_history import (
    _mesh_history_directory_identity,
    _mesh_morph_profile_directory_state,
    _pinned_mesh_history_parent,
)
from cdmw.services.mesh_service_kernel import _invalidate_tangents_after_edit
from cdmw.services.mesh_service_morph import mesh_morph_profile_lock
from cdmw.services.mesh_service_selection import _prune_selection_to_mesh

_CANDIDATE_FILE_RE = re.compile(r"candidate-[0-9]+-[A-Za-z0-9_-]+\.json\Z")
_STATE_FILE_RE = re.compile(r"state-[0-9]+-[0-9a-f]{10}\.json\Z")
_MATERIAL_STATE_FILE_RE = re.compile(r"material-state-(?:base|[0-9a-f]{32})\.json\Z")
_TEXTURE_FILE_RE = re.compile(r"texture-[0-9]{4}-[0-9a-f]{12}\.dds\Z")
_PREVIEW_GEOMETRY_FILE_RE = re.compile(
    r"preview-geometry-[0-9]{4}-[0-9a-f]{12}\.bin\Z"
)
_PREVIEW_IDENTITY_FILE_RE = re.compile(
    r"preview-identity-[0-9]{4}-[0-9a-f]{12}\.bin\Z"
)
_TEXTURE_IDENTITY_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<identity>[0-9]{4})(?P<suffix>(?:_[a-z0-9]+)*)$",
    re.IGNORECASE,
)
_TEXTURE_SLOT_DISCRIMINATOR_RE = re.compile(
    r"^(?P<base>.+_[0-9]{4})_[0-9]{2}$",
    re.IGNORECASE,
)
_TEXTURE_FAMILY_RE = re.compile(r"^(?P<family>cd_[a-z0-9]+_)", re.IGNORECASE)
_RUST_TEXTURE_SNAPSHOT_LIMIT = 2_048
_RUST_PREVIEW_MATERIAL_SOURCE_LIMIT = 4_096
# Layered armor can legitimately carry several independently owned PAC material
# graphs in one preview.  Keep the traversal bounded, but allow the seven-owner
# Wandering Freesword graph (~70k visited metadata nodes) through unchanged.
_RUST_PREVIEW_MATERIAL_VALUE_ITEMS = 131_072
_RUST_PREVIEW_MATERIAL_VALUE_DEPTH = 8
_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES = 16 * 1024 * 1024
_RUST_PREVIEW_PACKAGE_BATCH_LIMIT = 4_096
_RUST_PREVIEW_PACKAGE_TEXTURE_LIMIT = 65_536
_RUST_FAST_PREVIEW_TEXTURE_BUDGET_BYTES = 128 * 1024 * 1024
_RUST_EXTERNAL_PREVIEW_TEXTURE_MAX_DIMENSION = 2_048
_RUST_MATERIAL_PRESENTATION_LIMIT = 2_048
_RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT = 64
_RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_TEXT_LIMIT = 384
_RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION = 128
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_IMAGE_DIMENSION = 8_192
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_IMAGE_PIXELS = 16_777_216
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_MULTIPLIER = 1.20
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_ABSOLUTE_INCREASE = 20.0 / 255.0
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_FACES = 2_048
_RUST_MATERIAL_LUMINANCE_GUARD_SAMPLES_PER_FACE = 7
_RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_SAMPLES = (
    _RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_FACES
    * _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLES_PER_FACE
)
_LAYER_GENERATION_RE = re.compile(r"generation-[0-9]+-[0-9a-f]{8}\Z")
_PROFILE_MAX_DEPTH = 4
_PROFILE_MAX_ENTRIES = 4096
_PROFILE_MAX_FILE_BYTES = 8 * 1024 * 1024
_PROFILE_MAX_TOTAL_BYTES = 64 * 1024 * 1024
_MORPH_STATE_MAX_BYTES = 16 * 1024 * 1024
_GENERATED_MAX_ENTRIES = 65_536
_GENERATED_MAX_DEPTH = 8
_GENERATED_MAX_FILE_BYTES = 64 * 1024 * 1024
_GENERATED_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_SESSION_MAX_ENTRIES = 131_072
_SESSION_MAX_TOTAL_BYTES = 768 * 1024 * 1024
_TEXTURE_MAX_FILE_BYTES = 512 * 1024 * 1024
_TEXTURE_RESOURCE_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "base_color",
        (
            "preview_texture_dds_path",
            "preview_texture_path",
            "preview_base_texture_default_path",
            "texture",
        ),
    ),
    (
        "normal",
        (
            "preview_normal_texture_dds_path",
            "preview_normal_texture_path",
            "preview_normal_texture_default_path",
        ),
    ),
    (
        "material",
        (
            "preview_material_texture_dds_path",
            "preview_material_texture_path",
            "preview_material_texture_default_path",
        ),
    ),
    (
        "height",
        (
            "preview_height_texture_dds_path",
            "preview_height_texture_path",
            "preview_height_texture_default_path",
        ),
    ),
    (
        "emissive",
        (
            "preview_emissive_texture_dds_path",
            "preview_emissive_texture_path",
            "preview_emissive_texture_default_path",
        ),
    ),
)
_RUST_TEXTURE_PATH_NAME_COMPANIONS: Mapping[str, str] = MappingProxyType(
    {
        "preview_normal_texture_path": "preview_normal_texture_name",
        "preview_normal_texture_dds_path": "preview_normal_texture_name",
        "preview_normal_texture_default_path": "preview_normal_texture_default_name",
        "preview_material_texture_path": "preview_material_texture_name",
        "preview_material_texture_dds_path": "preview_material_texture_name",
        "preview_material_texture_default_path": "preview_material_texture_default_name",
        "preview_height_texture_path": "preview_height_texture_name",
        "preview_height_texture_dds_path": "preview_height_texture_name",
        "preview_height_texture_default_path": "preview_height_texture_default_name",
        "preview_emissive_texture_path": "preview_emissive_texture_name",
        "preview_emissive_texture_dds_path": "preview_emissive_texture_name",
        "preview_emissive_texture_default_path": "preview_emissive_texture_default_name",
    }
)
_RUST_ARCHIVE_TEXTURE_ROLE_NAME_ATTRIBUTES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "normal": (
            "preview_normal_texture_name",
            "preview_normal_texture_default_name",
        ),
        "material": (
            "preview_material_texture_name",
            "preview_material_texture_default_name",
        ),
        "height": (
            "preview_height_texture_name",
            "preview_height_texture_default_name",
        ),
        "emissive": (
            "preview_emissive_texture_name",
            "preview_emissive_texture_default_name",
        ),
    }
)
_RUST_SYNTHESIZED_TEXTURE_ROLES: tuple[
    tuple[str, tuple[str, ...], str], ...
] = (
    ("base_color", ("base", "albedo", "diffuse"), "base"),
    ("normal", ("normal",), "normal"),
    ("roughness", ("roughness",), "roughness"),
    ("metalness", ("metallic", "metalness"), "metalness"),
    ("occlusion", ("occlusion",), "occlusion"),
    ("specular", ("specular",), "specular"),
    ("height", ("height",), "height"),
    ("emissive", ("emissive",), "emissive"),
)
_RUST_SYNTHESIZED_SCALAR_ROLES = frozenset(
    {"roughness", "metalness", "occlusion", "specular"}
)
_RUST_SYNTHESIS_OUTPUT_CHANNELS = frozenset(
    {"base", "normal", "roughness", "metalness", "occlusion", "specular", "height"}
)
_RUST_PACKED_SURFACE_COMPONENT_ROLES = frozenset({"roughness", "metalness"})
_RUST_DIRECT_FALLBACK_PARAMETER_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "base_color": frozenset({"basecolortexture", "overlaycolortexture"}),
        "normal": frozenset({"normalmap", "normaltexture"}),
        "material": frozenset({"materialtexture"}),
        "height": frozenset({"displacementtexture", "heighttexture"}),
    }
)
_RUST_DIRECT_FALLBACK_SEMANTICS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "base_color": frozenset(
            {"albedo", "base", "base_color", "color", "diffuse", "material"}
        ),
        "normal": frozenset({"material", "normal"}),
        "material": frozenset(
            {
                "material",
                "material_response",
                "packed_material",
                "specular",
                "surface",
            }
        ),
        "height": frozenset({"displacement", "height", "material"}),
    }
)
_RUST_DIRECT_FALLBACK_DISPOSITIONS = frozenset(
    {"", "direct", "layer_material_response", "promoted", "recorded"}
)
_RUST_CONSERVED_PACKED_SURFACE_OUTPUT_ROLES = frozenset(
    {"material", "roughness", "metalness", "occlusion", "specular"}
)
_RUST_DEDICATED_MATERIAL_INPUT_ROLES = frozenset(
    {
        "layer_mask",
        "skin_detail_mask",
        "skin_detail_normal",
        "skin_detail_material",
    }
)
_RUST_REJECTED_GLOBAL_INPUT_DISPOSITIONS = frozenset(
    {
        "layer_only",
        "layer_material_response",
        "layer_direction",
        "layer_flow",
        "diagnostic_only",
    }
)
_RUST_GLOBAL_INPUT_DISPOSITIONS = frozenset(
    {"", "direct", "promoted", "recorded"}
)
_RUST_REJECTED_GLOBAL_INPUT_SOURCE_KINDS = frozenset(
    {
        "crimson_flow_vector",
        "crimson_hair_aging_color",
        "crimson_hair_direction",
        "crimson_eye_layer",
    }
)
_RUST_PRIMARY_MATERIAL_SOURCE_KINDS = frozenset(
    {
        "",
        "crimson_hair_material_response",
        "crimson_layer_material_response",
        "crimson_skin_material_response",
        "crimson_static_multitextured_material_response",
    }
)


@dataclass(slots=True)
class _RustMaterialSynthesisState:
    attempted: bool = False
    generated_binding_count: int = 0
    fast_preview_texture_bytes: int = 0
    presentation_overrides: dict[tuple[int, int], dict[str, object]] = field(
        default_factory=dict
    )
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    dropped_diagnostic_count: int = 0
    luminance_guard_count: int = 0
    luminance_guard_adjustments: list[dict[str, object]] = field(
        default_factory=list
    )
    dropped_luminance_guard_count: int = 0


def _encode_rust_preview_dds(
    source: Path,
    target: Path,
    channel: str,
    stop_event: threading.Event,
    synthesis_state: _RustMaterialSynthesisState,
    *,
    source_color_policy: str = "auto",
) -> dict[str, object]:
    """Encode a generated Rust preview map while bounding RGBA DDS expansion."""

    remaining_budget = max(
        0,
        _RUST_FAST_PREVIEW_TEXTURE_BUDGET_BYTES
        - max(0, int(synthesis_state.fast_preview_texture_bytes)),
    )
    artifact = _encode_owned_dds(
        source,
        target,
        channel,
        stop_event,
        source_color_policy=source_color_policy,
        preview_uncompressed_max_bytes=remaining_budget,
    )
    if bool(artifact.get("preview_uncompressed", False)):
        synthesis_state.fast_preview_texture_bytes += max(
            0,
            int(artifact.get("byte_count", 0) or 0),
        )
    return artifact


def _encode_rust_preview_dds_batch(
    jobs: Sequence[tuple[Path, Path, str]],
    stop_event: threading.Event,
    synthesis_state: _RustMaterialSynthesisState,
) -> tuple[dict[str, object], ...]:
    """Encode one preview's external images in a single native batch."""

    remaining_budget = max(
        0,
        _RUST_FAST_PREVIEW_TEXTURE_BUDGET_BYTES
        - max(0, int(synthesis_state.fast_preview_texture_bytes)),
    )
    artifacts = _encode_owned_image_dds_batch(
        jobs,
        stop_event,
        preview_uncompressed_max_bytes=remaining_budget,
        max_dimension=_RUST_EXTERNAL_PREVIEW_TEXTURE_MAX_DIMENSION,
    )
    synthesis_state.fast_preview_texture_bytes += sum(
        max(0, int(artifact.get("byte_count", 0) or 0))
        for artifact in artifacts
        if bool(artifact.get("preview_uncompressed", False))
    )
    return artifacts


def _record_rust_material_synthesis_diagnostic(
    state: _RustMaterialSynthesisState,
    code: str,
    *,
    lod_index: int,
    submesh_index: int | None = None,
    detail: object = "",
) -> None:
    if len(state.diagnostics) >= _RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT:
        state.dropped_diagnostic_count += 1
        return
    row: dict[str, object] = {
        "code": str(code or "material_synthesis_fallback")[:64],
        "lod_index": max(0, int(lod_index)),
        "fallback": "direct_dds",
    }
    if submesh_index is not None:
        row["submesh_index"] = max(0, int(submesh_index))
    text = " ".join(str(detail or "").split())[
        :_RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_TEXT_LIMIT
    ]
    if text:
        row["detail"] = text
    state.diagnostics.append(row)


def _record_rust_material_luminance_guard(
    state: _RustMaterialSynthesisState,
    *,
    lod_index: int,
    submesh_index: int,
    direct_mean_luma: float,
    generated_mean_luma: float,
    capped_mean_luma: float,
    rgb_scale: float,
    sampling_basis: str = "whole_image_alpha_weighted",
    sample_count: int = 0,
) -> None:
    state.luminance_guard_count += 1
    if (
        len(state.luminance_guard_adjustments)
        >= _RUST_MATERIAL_SYNTHESIS_DIAGNOSTIC_LIMIT
    ):
        state.dropped_luminance_guard_count += 1
        return
    state.luminance_guard_adjustments.append(
        {
            "code": "generated_base_luminance_capped",
            "lod_index": max(0, int(lod_index)),
            "submesh_index": max(0, int(submesh_index)),
            "direct_mean_luma": round(float(direct_mean_luma), 6),
            "generated_mean_luma": round(float(generated_mean_luma), 6),
            "capped_mean_luma": round(float(capped_mean_luma), 6),
            "rgb_scale": round(float(rgb_scale), 6),
            "sampling_basis": str(sampling_basis or "whole_image_alpha_weighted")[
                :64
            ],
            "sample_count": max(0, min(int(sample_count), 0x7FFF_FFFF)),
        }
    )


def _rust_generated_presentation_overrides(
    row: Mapping[str, object],
    applied_roles: set[str],
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if "normal" in applied_roles:
        normal_y_policy = str(
            row.get("normal_y_policy", "preserve") or "preserve"
        ).strip().casefold()
        overrides["normal_y_policy"] = (
            normal_y_policy
            if normal_y_policy in {"preserve", "invert_green_for_directx"}
            else "preserve"
        )
    if "base_color" in applied_roles:
        alpha_mode = str(row.get("alpha_mode", "") or "").strip().casefold()
        if alpha_mode in {"opaque", "cutout", "blend"}:
            overrides["alpha_mode"] = alpha_mode
        if "alpha_cutoff" in row:
            overrides["alpha_cutoff"] = row.get("alpha_cutoff")
        if "double_sided" in row:
            overrides["double_sided"] = bool(row.get("double_sided", False))
        parameters = row.get("parameters", {})
        if isinstance(parameters, Mapping):
            texture_tint = _rust_material_optional_color(
                parameters,
                "texture_tint",
            )
            if texture_tint is not None:
                overrides["texture_tint"] = texture_tint
            base_tint_strength = _rust_material_optional_scalar(
                parameters,
                "base_tint_strength",
                minimum=0.0,
                maximum=1.0,
            )
            if base_tint_strength is not None:
                overrides["base_tint_strength"] = base_tint_strength
    return overrides


def _clear_rust_material_synthesis_results(
    state: _RustMaterialSynthesisState,
) -> None:
    state.generated_binding_count = 0
    state.presentation_overrides.clear()
    state.luminance_guard_count = 0
    state.luminance_guard_adjustments.clear()
    state.dropped_luminance_guard_count = 0


_HOST_TOPOLOGY_ACTION_PARAMS: dict[str, frozenset[str]] = {
    "delete": frozenset({"delete_parts"}),
    "subdivide": frozenset(),
    "refine_smooth": frozenset({"smooth_strength", "smooth_iterations"}),
    "duplicate": frozenset(),
    "extrude": frozenset({"offset"}),
    "inset": frozenset({"amount"}),
    "loop_cut": frozenset({"cuts", "factor"}),
    "edge_split": frozenset(),
    "split": frozenset(),
    "dissolve": frozenset(),
    "bridge": frozenset(),
    "fill": frozenset(),
    "merge": frozenset(),
    "weld": frozenset({"threshold"}),
    "separate": frozenset(),
}
_HOST_TOPOLOGY_ACTIONS = frozenset(_HOST_TOPOLOGY_ACTION_PARAMS)

_HOST_MESH_ACTION_PARAMS: dict[str, frozenset[str]] = {
    "mirror": frozenset({"axis", "in_place"}),
    "remove_doubles": frozenset({"threshold", "distance", "merge_distance"}),
    "delete_loose_vertices": frozenset(),
    "compact_orphans": frozenset(),
    "fix_winding": frozenset(),
    "fill_holes": frozenset(),
    "recalculate_normals": frozenset(),
    "generate_tangents": frozenset(),
    "flip_normals": frozenset(),
    "sharpen_normals": frozenset(),
    "soften_normals": frozenset(),
    "weighted_normals": frozenset(),
    "copy_normals": frozenset(),
    "uv_transform": frozenset(
        {
            "offset",
            "scale",
            "rotate",
            "rotate_degrees",
            "pivot",
            "flip_u",
            "flip_v",
            "uv_island",
            "selection_mode",
            "normalize",
            "target_min",
            "target_max",
            "align_u",
            "align_v",
            "projection",
            "plane",
            "axis",
            "pack",
            "pack_columns",
            "padding",
            "snap_grid",
            "snap_pixels",
            "texture_width",
            "texture_height",
            "texture_size",
            "auto_uv",
            "resolution",
            "allow_topology_change",
            "fallback_projection",
        }
    ),
}

# Only actions whose result can grow the mesh need the expensive disposable
# execution before the authoritative shadow command.  Same-size and shrinking
# actions are bounded from the current document and then execute their native
# kernel once.
_HOST_MESH_ACTIONS_REQUIRING_RESULT_PREFLIGHT = frozenset(
    {
        "mirror",
        "fill_holes",
        "generate_tangents",
    }
)


def _mesh_action_requires_result_preflight(command: MeshEditCommand) -> bool:
    action = str(command.action or "").strip().lower()
    if action in _HOST_MESH_ACTIONS_REQUIRING_RESULT_PREFLIGHT:
        return True
    return action == "uv_transform" and _command_truthy(
        (command.params or {}).get("auto_uv", False)
    )


def _mesh_action_capacity_factor(command: MeshEditCommand) -> int:
    """Conservatively admit same-size edits that may add one vertex channel."""

    action = str(command.action or "").strip().lower()
    if action in {
        "recalculate_normals",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
        "uv_transform",
    }:
        return 2
    return 1


def _mesh_topology_counts(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple(
        (len(submesh.vertices), len(submesh.faces))
        for level in _mesh_lods(mesh)
        for submesh in level
    )
_RUST_MESH_ACTION_ARGUMENTS = frozenset({"action", "selection", "params", "label"})
_RUST_TOPOLOGY_ARGUMENTS = frozenset({"action", "selection", "params", "label"})
_RUST_RIG_SELECTION_ARGUMENTS = frozenset({"selection"})
_RUST_RIG_SELECT_BONE_ARGUMENTS = frozenset({"bone_index"})
_RUST_RIG_ADJUST_ARGUMENTS = frozenset({"selection", "delta"})
_SKELETON_STATE_MAX_BONES = 512
_SKELETON_STATE_MAX_PARTS = 4096
_SKELETON_STATE_MAX_SELECTED_WEIGHTS = 256
_SKELETON_STATE_MAX_TEXT = 1024

_EDITABLE_PACKAGE_MESH_NAMES = (
    "mesh.glb",
    "edited_mesh.glb",
    "edited.glb",
    "mesh.obj",
    "edited_mesh.obj",
    "edited.obj",
)


class RustMeshAuthoringError(RuntimeError):
    """Base error returned to the managed Rust process."""


class RustMeshProtocolError(RustMeshAuthoringError):
    """The process supplied a malformed, stale, or unowned protocol payload."""


class RustMeshValidationError(RustMeshAuthoringError):
    """A candidate could not pass the existing CDMW export contract."""


class RustMeshCancellationError(RustMeshAuthoringError):
    """The owning CDMW window cancelled before a Finish commit linearized."""


_RUST_PREVIEW_MATERIAL_CONTEXT_ATTR = "_cdmw_rust_mesh_preview_material_context"


@dataclass(frozen=True, slots=True)
class _RustMeshPreviewMaterialContext:
    preview_model: object | None
    material_package_path: str
    unavailable_reason: str
    target_entry: ArchiveEntry | None = None
    texture_entries: tuple[ArchiveEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class _RustPreviewMaterialSourceSnapshot:
    values: Mapping[str, object]

    def __getattr__(self, name: str) -> object:
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@dataclass(frozen=True, slots=True)
class _RustPreviewMaterialModelSnapshot:
    path: str
    submeshes: tuple[_RustPreviewMaterialSourceSnapshot, ...]
    meshes: tuple[object, ...] = ()


_RUST_PREVIEW_MATERIAL_IDENTITY_ATTRS = (
    "name",
    "material",
    "material_name",
    "texture",
    "texture_name",
    "submesh_index",
    "source_submesh_index",
    "material_slot_index",
    "preview_dotnet_scene_material_slot_index",
    "preview_pac_material_owner_slot_index",
)


def _validate_bounded_rust_material_value(
    value: object,
    budget: list[int],
    *,
    depth: int = 0,
) -> None:
    budget[0] -= 1
    if budget[0] < 0 or depth > _RUST_PREVIEW_MATERIAL_VALUE_DEPTH:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context exceeds the safe snapshot limit."
        )
    if isinstance(value, str) and len(value) > 32_768:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context exceeds the safe snapshot limit."
        )
    if isinstance(value, (bytes, bytearray, memoryview)) and len(value) > 65_536:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context exceeds the safe snapshot limit."
        )
    if isinstance(value, Mapping):
        if len(value) > _RUST_PREVIEW_MATERIAL_VALUE_ITEMS:
            raise RustMeshAuthoringError(
                "Resolved Archive Browser material context exceeds the safe snapshot limit."
            )
        for key, item in value.items():
            _validate_bounded_rust_material_value(key, budget, depth=depth + 1)
            _validate_bounded_rust_material_value(item, budget, depth=depth + 1)
        return
    if is_dataclass(value) and not isinstance(value, type):
        for item in getattr(value, "__dataclass_fields__", {}).values():
            _validate_bounded_rust_material_value(
                getattr(value, item.name),
                budget,
                depth=depth + 1,
            )
        return
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray, memoryview),
    ):
        if len(value) > _RUST_PREVIEW_MATERIAL_VALUE_ITEMS:
            raise RustMeshAuthoringError(
                "Resolved Archive Browser material context exceeds the safe snapshot limit."
            )
        for item in value:
            _validate_bounded_rust_material_value(item, budget, depth=depth + 1)


def _deduplicate_rust_texture_input_parameters(
    value: object,
    source_parameters: tuple[object, ...],
) -> object:
    """Drop only exact per-input copies of the source parameter table.

    Archive Browser texture bindings can each retain the complete owning PAC
    material-parameter tuple.  Copying that same immutable table into every
    Rust snapshot input multiplies a legitimate layered weapon by tens of
    thousands of recursively visited values without adding any information.
    Keep the authoritative source-level table once and preserve any input that
    carries a distinct parameter tuple.
    """

    if not source_parameters or not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray, memoryview),
    ):
        return value
    normalized: list[object] = []
    changed = False
    for item in value:
        input_parameters = getattr(item, "material_parameters", None)
        if (
            input_parameters
            and is_dataclass(item)
            and not isinstance(item, type)
            and tuple(input_parameters) == source_parameters
        ):
            item = replace(item, material_parameters=())
            changed = True
        normalized.append(item)
    if not changed:
        return value
    return tuple(normalized)


def _rust_rgb_texture_parameter_identity(
    value: object,
) -> tuple[str, str, str] | None:
    """Return the channel-local identity for an explicit PAC texture row."""

    parameter_name = str(getattr(value, "parameter_name", "") or "").strip()
    if not parameter_name or parameter_name[-1:] not in {"R", "G", "B"}:
        return None
    parameter_kind = str(
        getattr(value, "parameter_kind", "") or ""
    ).strip().casefold()
    if parameter_kind and parameter_kind != "texture":
        return None
    texture_path = str(
        getattr(value, "texture_path", "")
        or getattr(value, "source_texture_path", "")
        or getattr(value, "source_dds_path", "")
        or getattr(value, "texture_name", "")
        or ""
    ).replace("\\", "/").strip()
    family = "".join(
        character
        for character in parameter_name[:-1].casefold()
        if character.isalnum()
    )
    if not family or not texture_path:
        return None
    return family, parameter_name[-1].casefold(), texture_path.casefold()


def _rust_input_matches_declared_texture(value: object, texture_path: str) -> bool:
    declared = str(texture_path or "").replace("\\", "/").strip().casefold()
    if not declared:
        return False
    declared_name = PurePosixPath(declared).name
    for attribute in ("source_texture_path", "source_dds_path", "texture_name"):
        candidate = str(getattr(value, attribute, "") or "").replace(
            "\\", "/"
        ).strip().casefold()
        if not candidate:
            continue
        if candidate == declared or PurePosixPath(candidate).name == declared_name:
            return True
    return False


def _rust_input_is_owner_qualified_sidecar(value: object) -> bool:
    sidecar_kind = str(getattr(value, "sidecar_kind", "") or "").strip(
        "."
    ).casefold()
    if sidecar_kind not in {"pac_xml", "pami"}:
        return False
    authority = str(
        getattr(value, "binding_authority", "") or ""
    ).strip().casefold()
    if authority and authority not in {"authoritative", "exact"}:
        return False
    try:
        owner_slot_index = int(getattr(value, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        owner_slot_index = -1
    return owner_slot_index >= 0 or bool(
        str(getattr(value, "owner_wrapper_item_id", "") or "").strip()
    )


def _preserve_rust_same_path_rgb_texture_inputs(
    value: object,
    source_parameters: tuple[object, ...],
) -> object:
    """Restore channel-local PAC bindings collapsed by a path-only preview row.

    PAC materials legitimately bind one DDS to separate R/G/B parameters.  A
    prepared preview may retain only the first row while its authoritative
    source parameter table still contains all three declarations.  Clone only
    an owner-qualified same-family peer so Rust keeps the separate channel
    semantics without duplicating the DDS payload itself.
    """

    if not source_parameters or not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray, memoryview),
    ):
        return value
    inputs = list(value)
    present = {
        identity[:2]
        for item in inputs
        if (identity := _rust_rgb_texture_parameter_identity(item)) is not None
    }
    changed = False
    for parameter in source_parameters:
        identity = _rust_rgb_texture_parameter_identity(parameter)
        if identity is None or identity[:2] in present:
            continue
        family, channel, texture_path = identity
        template = next(
            (
                item
                for item in inputs
                if is_dataclass(item)
                and not isinstance(item, type)
                and _rust_input_is_owner_qualified_sidecar(item)
                and (
                    item_identity := _rust_rgb_texture_parameter_identity(item)
                )
                is not None
                and item_identity[0] == family
                and _rust_input_matches_declared_texture(item, texture_path)
            ),
            None,
        )
        if template is None:
            continue
        inputs.append(
            replace(
                template,
                parameter_name=str(
                    getattr(parameter, "parameter_name", "") or ""
                ).strip(),
                source_texture_path=str(
                    getattr(parameter, "texture_path", "") or ""
                ).strip(),
                texture_name=PurePosixPath(texture_path).name,
                layer_channel=channel,
                material_parameters=source_parameters,
            )
        )
        present.add((family, channel))
        changed = True
    return tuple(inputs) if changed else value


def _snapshot_rust_preview_model(preview_model: object | None) -> object | None:
    """Capture only bounded material metadata, never preview geometry or images."""

    if preview_model is None:
        return None
    source_values = getattr(preview_model, "submeshes", ()) or getattr(
        preview_model,
        "meshes",
        (),
    ) or ()
    try:
        source_count = len(source_values)
    except TypeError as exc:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context has an unbounded material source."
        ) from exc
    if source_count > _RUST_PREVIEW_MATERIAL_SOURCE_LIMIT:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context has too many material sources."
        )
    sources = tuple(source_values)
    if len(sources) != source_count:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context changed while it was captured."
        )
    attribute_names = tuple(
        dict.fromkeys(
            _RUST_PREVIEW_MATERIAL_IDENTITY_ATTRS + _DOTNET_PREVIEW_MATERIAL_ATTRS
        )
    )
    budget = [_RUST_PREVIEW_MATERIAL_VALUE_ITEMS]
    snapshots: list[_RustPreviewMaterialSourceSnapshot] = []
    try:
        for source in sources:
            source_parameters = tuple(
                getattr(source, "preview_material_parameters", ()) or ()
            )
            values: dict[str, object] = {}
            for name in attribute_names:
                if not hasattr(source, name):
                    continue
                value = getattr(source, name)
                if name == "preview_material_texture_inputs":
                    value = _preserve_rust_same_path_rgb_texture_inputs(
                        value,
                        source_parameters,
                    )
                    value = _deduplicate_rust_texture_input_parameters(
                        value,
                        source_parameters,
                    )
                _validate_bounded_rust_material_value(value, budget)
                values[name] = copy.deepcopy(value)
            snapshots.append(
                _RustPreviewMaterialSourceSnapshot(MappingProxyType(values))
            )
    except Exception as exc:
        if isinstance(exc, RustMeshAuthoringError):
            raise
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context could not be captured safely."
        ) from exc
    model_path = str(getattr(preview_model, "path", "") or "").strip()
    if len(model_path) > 32_768:
        raise RustMeshAuthoringError(
            "Resolved Archive Browser material context exceeds the safe snapshot limit."
        )
    return _RustPreviewMaterialModelSnapshot(
        path=model_path,
        submeshes=tuple(snapshots),
    )


def _rust_texture_identity_variants(value: object) -> tuple[str, ...]:
    """Return bounded DDS basename variants used by the archive preview family.

    PAC slots are not fully uniform: a wrapper may retain an owner segment such
    as ``_00_`` that the DDS omits, while a material name can omit the same
    segment even though its DDS keeps it.  The Archive Browser resolves those
    identities semantically.  Rust keeps that resolution read-only and captures
    only the exact candidate entries it may need before its worker starts.
    """

    text = str(value or "").replace("\\", "/").strip().casefold()
    if not text:
        return ()
    name = Path(text).name
    stem = name[:-4] if name.endswith(".dds") else name
    if not stem:
        return ()
    variants: list[str] = []

    def remember(candidate: str) -> None:
        normalized = str(candidate or "").strip().casefold()
        if normalized and normalized not in variants:
            variants.append(normalized)

    remember(stem)
    discriminator = _TEXTURE_SLOT_DISCRIMINATOR_RE.fullmatch(stem)
    if discriminator is not None:
        remember(discriminator.group("base"))
    for candidate in tuple(variants):
        match = _TEXTURE_IDENTITY_RE.fullmatch(candidate)
        if match is None:
            continue
        prefix = match.group("prefix")
        identity = match.group("identity")
        suffix = match.group("suffix")
        prefix_parts = prefix.rsplit("_", 1)
        if len(prefix_parts) == 2 and re.fullmatch(r"[0-9]{2}", prefix_parts[1]):
            remember(f"{prefix_parts[0]}_{identity}{suffix}")
        else:
            remember(f"{prefix}_00_{identity}{suffix}")
    return tuple(f"{candidate}.dds" for candidate in variants[:12])


def _rust_texture_identity_candidates(
    texture_name: object,
    material_name: object,
) -> tuple[str, ...]:
    """Order exact texture identity first, then material and family fallbacks."""

    texture_text = str(texture_name or "").strip()
    material_text = str(material_name or "").strip()
    identities: list[str] = []

    def remember_many(value: object) -> None:
        for candidate in _rust_texture_identity_variants(value):
            if candidate not in identities:
                identities.append(candidate)

    remember_many(texture_text)
    remember_many(material_text)
    texture_name_only = Path(texture_text.replace("\\", "/")).name.casefold()
    material_name_only = Path(material_text.replace("\\", "/")).name.casefold()
    texture_family = _TEXTURE_FAMILY_RE.match(texture_name_only)
    material_family = _TEXTURE_FAMILY_RE.match(material_name_only)
    if texture_family is not None and material_family is not None:
        blended = (
            material_family.group("family")
            + texture_name_only[texture_family.end() :]
        )
        remember_many(blended)
    return tuple(identities[:32])


def _rust_texture_candidate_basenames(
    identity_pairs: Sequence[tuple[str, str]],
    *,
    exact_basenames: Sequence[str] = (),
    suppress_material_guesses: bool | None = None,
) -> tuple[str, ...]:
    basenames: list[str] = []
    seen: set[str] = set()

    def remember(candidate: object) -> bool:
        normalized = PurePosixPath(
            str(candidate or "").replace("\\", "/")
        ).name.casefold()
        if not normalized or normalized in seen:
            return False
        seen.add(normalized)
        basenames.append(normalized)
        return len(basenames) == 512

    # Exact PAC XML texture inputs outrank family guesses.  When they are
    # available they are the complete authority for packed surface selectors:
    # never supplement them with a guessed ``*_m``/``*_sp`` binding.  Emissive
    # is never a family guess; it is valid only as an authored input or an
    # already-resolved direct channel.
    for candidate in exact_basenames:
        if remember(candidate):
            return tuple(basenames)
    suppress_material = (
        bool(basenames)
        if suppress_material_guesses is None
        else bool(suppress_material_guesses)
    )
    for texture_name, material_name in identity_pairs:
        for base_name in _rust_texture_identity_candidates(
            texture_name,
            material_name,
        ):
            stem = base_name[:-4]
            candidates = [
                base_name,
                f"{stem}_n.dds",
            ]
            if not suppress_material:
                # ``*_sp`` is the packed surface response.  ``*_m`` is a
                # selector/layer mask and must never be guessed as material.
                candidates.append(f"{stem}_sp.dds")
            for candidate in candidates:
                if remember(candidate):
                    return tuple(basenames)
    return tuple(basenames)


def _rust_exact_texture_basenames(*values: object) -> tuple[str, ...]:
    basenames: list[str] = []
    for value in values:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            continue
        name = PurePosixPath(text).name.casefold()
        suffix = PurePosixPath(name).suffix
        if not suffix:
            name = f"{name}.dds"
        elif suffix != ".dds":
            continue
        if name and name not in basenames:
            basenames.append(name)
    return tuple(basenames)


def _rust_material_input_exact_basenames(value: object) -> tuple[str, ...]:
    return _rust_exact_texture_basenames(
        *(
            getattr(value, attribute, "")
            for attribute in (
                "texture_name",
                "source_texture_path",
                "source_dds_path",
                "preview_texture_path",
            )
        )
    )


def _rust_preview_material_input_basenames(
    preview_model: object | None,
) -> tuple[str, ...]:
    basenames: list[str] = []
    seen: set[str] = set()
    sources = getattr(preview_model, "submeshes", ()) or getattr(
        preview_model,
        "meshes",
        (),
    ) or ()
    for source in sources:
        for item in tuple(
            getattr(source, "preview_material_texture_inputs", ()) or ()
        ):
            for basename in _rust_material_input_exact_basenames(item):
                if basename in seen:
                    continue
                seen.add(basename)
                basenames.append(basename)
                if len(basenames) == 512:
                    return tuple(basenames)
    return tuple(basenames)


def _rust_preview_direct_texture_basenames(
    preview_model: object | None,
) -> tuple[str, ...]:
    basenames: list[str] = []
    seen: set[str] = set()
    sources = getattr(preview_model, "submeshes", ()) or getattr(
        preview_model,
        "meshes",
        (),
    ) or ()
    for source in sources:
        for _role, attributes in _TEXTURE_RESOURCE_SPECS:
            for attribute in attributes:
                if attribute == "texture":
                    continue
                for basename in _rust_exact_texture_basenames(
                    getattr(source, attribute, "")
                ):
                    if basename in seen:
                        continue
                    seen.add(basename)
                    basenames.append(basename)
                    if len(basenames) == 512:
                        return tuple(basenames)
    return tuple(basenames)


def _rust_controller_texture_identities(
    authoritative_controller: object,
    preview_model: object | None,
) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def remember(texture_name: object, material_name: object) -> bool:
        pair = (
            str(texture_name or "").strip(),
            str(material_name or "").strip(),
        )
        if any(pair) and pair not in seen:
            seen.add(pair)
            pairs.append(pair)
        return len(pairs) >= 256

    sources = getattr(preview_model, "submeshes", ()) or getattr(
        preview_model,
        "meshes",
        (),
    ) or ()
    for source in sources:
        if remember(
            getattr(source, "texture", "")
            or getattr(source, "texture_name", ""),
            getattr(source, "material", "")
            or getattr(source, "material_name", ""),
        ):
            return tuple(pairs)
    service = getattr(authoritative_controller, "mesh_service", None)
    session_id = str(
        getattr(authoritative_controller, "active_session_id", "") or ""
    )
    if isinstance(service, MeshService) and session_id:
        session = service._session(session_id)
        with session.export_lock:
            mesh = service._working_mesh_locked(session, clone=False)
            for level in _mesh_lods(mesh):
                for source in level:
                    if remember(
                        getattr(source, "texture", ""),
                        getattr(source, "material", ""),
                    ):
                        return tuple(pairs)
    return tuple(pairs)


def _snapshot_rust_texture_entries(
    candidate_basenames: Sequence[str],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None,
) -> tuple[ArchiveEntry, ...]:
    snapshots: list[ArchiveEntry] = []
    seen: set[object] = set()
    index = entries_by_basename or {}
    for basename in candidate_basenames:
        remaining_capacity = _RUST_TEXTURE_SNAPSHOT_LIMIT - len(snapshots)
        if remaining_capacity <= 0:
            return tuple(snapshots)
        bucket_values = index.get(str(basename).casefold(), ()) or ()
        try:
            if len(bucket_values) > remaining_capacity:
                continue
        except TypeError:
            # A caller-supplied unbounded iterable is not safe to scan on the
            # UI thread. Archive basename indexes are required to be sequences.
            continue
        bucket: list[ArchiveEntry] = []
        bucket_seen: set[object] = set()
        overflow = False
        for entry in bucket_values:
            if not isinstance(entry, ArchiveEntry) or entry.extension != ".dds":
                continue
            if entry.basename.casefold() != str(basename).casefold():
                continue
            identity = entry.identity
            if identity in seen or identity in bucket_seen:
                continue
            bucket_seen.add(identity)
            bucket.append(entry)
            if len(bucket) > remaining_capacity:
                overflow = True
                break
        if overflow:
            # Never turn an ambiguous overlay collision into an apparently
            # unique DDS candidate by truncating a basename bucket midway.
            # Omitting the whole bucket makes this bounded snapshot fail closed.
            continue
        snapshots.extend(copy.deepcopy(entry) for entry in bucket)
        seen.update(bucket_seen)
        if len(snapshots) == _RUST_TEXTURE_SNAPSHOT_LIMIT:
            return tuple(snapshots)
    return tuple(snapshots)


def concise_rust_texture_unavailable_reason(value: object) -> str:
    """Convert resolver diagnostics into one honest compact viewport reason."""

    text = " ".join(str(value or "").split())
    lowered = text.casefold()
    if not text:
        return ""
    if (
        "no direct visible dds match" in lowered
        or "no resolved texture bindings" in lowered
        or "contains no texture bindings" in lowered
        or "returned no resolved texture" in lowered
    ):
        return "No matching archive DDS textures were resolved for this mesh."
    if "outside the leased package" in lowered:
        return "Resolved texture references were outside the leased package."
    if "texture package is unavailable" in lowered:
        return "The resolved Archive Browser texture package is unavailable."
    if len(text) > 220:
        return text[:217].rstrip() + "..."
    return text


def prime_rust_mesh_preview_context(
    authoritative_controller: object,
    preview_model: object | None,
    *,
    material_package_path: Path | str | None = None,
    unavailable_reason: str = "",
    target_entry: ArchiveEntry | None = None,
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
) -> int:
    """Attach Archive Browser material evidence for the isolated shadow clone."""

    if authoritative_controller is None:
        raise RustMeshAuthoringError("CDMW has no controller for texture context")
    preview_model_snapshot = _snapshot_rust_preview_model(preview_model)
    binding_count = (
        count_dotnet_own_material_bindings(preview_model_snapshot)
        if preview_model_snapshot is not None
        else 0
    )
    reason = concise_rust_texture_unavailable_reason(unavailable_reason)
    if preview_model_snapshot is not None and binding_count <= 0 and not reason:
        reason = "Resolved Archive Browser material context contains no texture bindings."
    identity_pairs = _rust_controller_texture_identities(
        authoritative_controller,
        preview_model_snapshot,
    )
    exact_material_inputs = _rust_preview_material_input_basenames(
        preview_model_snapshot
    )
    exact_basenames = tuple(
        dict.fromkeys(
            exact_material_inputs
            + _rust_preview_direct_texture_basenames(preview_model_snapshot)
        )
    )
    texture_entries = _snapshot_rust_texture_entries(
        _rust_texture_candidate_basenames(
            identity_pairs,
            exact_basenames=exact_basenames,
            suppress_material_guesses=bool(exact_material_inputs),
        ),
        entries_by_basename,
    )
    setattr(
        authoritative_controller,
        _RUST_PREVIEW_MATERIAL_CONTEXT_ATTR,
        _RustMeshPreviewMaterialContext(
            preview_model=preview_model_snapshot,
            material_package_path=str(material_package_path or "").strip(),
            unavailable_reason=reason,
            target_entry=copy.deepcopy(target_entry)
            if isinstance(target_entry, ArchiveEntry)
            else None,
            texture_entries=texture_entries,
        ),
    )
    return binding_count


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _editable_package_mesh_path(path: Path) -> Path:
    if path.is_dir():
        for name in _EDITABLE_PACKAGE_MESH_NAMES:
            candidate = path / name
            if candidate.is_file():
                return candidate
        raise RustMeshValidationError(
            "The selected editable package does not contain mesh.glb or mesh.obj."
        )
    if not path.is_file():
        raise RustMeshValidationError("The selected editable package does not exist.")
    return path


def _editable_package_sidecar_path(mesh_path: Path) -> Path | None:
    sidecar_path = Path(f"{mesh_path}.meta.json")
    if sidecar_path.is_file():
        return sidecar_path
    cdmeta_path = mesh_path.parent / "mesh.cdmeta.json"
    return cdmeta_path if cdmeta_path.is_file() else None


def _is_reparse_point(path: Path) -> bool:
    attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0))


def _require_owned_path(path: Path, root: Path) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        raise RustMeshProtocolError(
            f"Mesh session contains a link or reparse point: {path.name}"
        )
    resolved = path.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise RustMeshProtocolError("Mesh session entry escaped its owned directory")


def _validate_owned_profile_tree(root: Path) -> tuple[int, int]:
    owned_root = root.resolve(strict=True)
    _require_owned_path(root, owned_root)
    stack: list[tuple[Path, int]] = [(root, 0)]
    entry_count = 0
    total_bytes = 0
    while stack:
        directory, depth = stack.pop()
        for item in directory.iterdir():
            entry_count += 1
            if entry_count > _PROFILE_MAX_ENTRIES:
                raise RustMeshProtocolError(
                    "Mesh morph profiles contain too many entries"
                )
            _require_owned_path(item, owned_root)
            if item.is_dir():
                if depth >= _PROFILE_MAX_DEPTH:
                    raise RustMeshProtocolError(
                        "Mesh morph profiles exceed the directory-depth limit"
                    )
                stack.append((item, depth + 1))
                continue
            if not item.is_file() or item.suffix != ".json":
                raise RustMeshProtocolError(
                    "Mesh morph profiles contain an unexpected entry"
                )
            length = item.stat().st_size
            if length > _PROFILE_MAX_FILE_BYTES:
                raise RustMeshProtocolError(
                    "Mesh morph profile file exceeds the 8 MiB limit"
                )
            total_bytes += length
            if total_bytes > _PROFILE_MAX_TOTAL_BYTES:
                raise RustMeshProtocolError(
                    "Mesh morph profiles exceed the 64 MiB session limit"
                )
    return entry_count, total_bytes


def _profile_files_fingerprint(files: Sequence[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, data in files:
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes(data))
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _capture_owned_profile_tree(
    root: Path | None,
) -> tuple[bool, tuple[tuple[str, bytes], ...], str]:
    """Read one bounded, link-free profile snapshot for copying or CAS."""

    if root is None or not root.exists():
        digest = hashlib.sha256()
        digest.update(b"missing")
        return False, (), digest.hexdigest().upper()
    if not root.is_dir():
        raise RustMeshProtocolError("Mesh morph profile root is not a directory")
    owned_root = root.resolve(strict=True)
    _require_owned_path(root, owned_root)
    root_stat = root.stat()
    stack: list[tuple[Path, int]] = [(root, 0)]
    entry_count = 0
    total_bytes = 0
    captured: list[tuple[str, bytes]] = []
    while stack:
        directory, depth = stack.pop()
        for item in directory.iterdir():
            entry_count += 1
            if entry_count > _PROFILE_MAX_ENTRIES:
                raise RustMeshProtocolError(
                    "Mesh morph profiles contain too many entries"
                )
            _require_owned_path(item, owned_root)
            if item.is_dir():
                if depth >= _PROFILE_MAX_DEPTH:
                    raise RustMeshProtocolError(
                        "Mesh morph profiles exceed the directory-depth limit"
                    )
                stack.append((item, depth + 1))
                continue
            if not item.is_file() or item.suffix != ".json":
                raise RustMeshProtocolError(
                    "Mesh morph profiles contain an unexpected entry"
                )
            declared_length = item.stat().st_size
            if declared_length > _PROFILE_MAX_FILE_BYTES:
                raise RustMeshProtocolError(
                    "Mesh morph profile file exceeds the 8 MiB limit"
                )
            declared_stat = item.stat()
            with item.open("rb") as stream:
                opened_stat = os.fstat(stream.fileno())
                if (
                    int(opened_stat.st_dev) != int(declared_stat.st_dev)
                    or int(opened_stat.st_ino) != int(declared_stat.st_ino)
                    or int(opened_stat.st_size) != declared_length
                ):
                    raise RustMeshProtocolError(
                        "Mesh morph profile changed before it could be read"
                    )
                data = stream.read(_PROFILE_MAX_FILE_BYTES + 1)
                final_stat = os.fstat(stream.fileno())
            _require_owned_path(item, owned_root)
            current_stat = item.stat()
            if (
                len(data) > _PROFILE_MAX_FILE_BYTES
                or len(data) != declared_length
                or int(final_stat.st_size) != declared_length
                or int(current_stat.st_dev) != int(declared_stat.st_dev)
                or int(current_stat.st_ino) != int(declared_stat.st_ino)
            ):
                raise RustMeshProtocolError(
                    "Mesh morph profile changed or exceeded the 8 MiB limit"
                )
            total_bytes += len(data)
            if total_bytes > _PROFILE_MAX_TOTAL_BYTES:
                raise RustMeshProtocolError(
                    "Mesh morph profiles exceed the 64 MiB session limit"
                )
            captured.append((item.relative_to(root).as_posix(), data))
    current_root_stat = root.stat()
    _require_owned_path(root, owned_root)
    if (
        root.resolve(strict=True) != owned_root
        or int(current_root_stat.st_dev) != int(root_stat.st_dev)
        or int(current_root_stat.st_ino) != int(root_stat.st_ino)
    ):
        raise RustMeshProtocolError(
            "Mesh morph profile root changed while it was being read"
        )
    files = tuple(sorted(captured, key=lambda item: item[0].casefold()))
    return True, files, _profile_files_fingerprint(files)


def _write_owned_profile_tree(
    destination: Path,
    files: Sequence[tuple[str, bytes]],
) -> None:
    destination.mkdir()
    for relative, data in files:
        parts = tuple(Path(relative).parts)
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise RustMeshProtocolError(
                "Mesh morph profile snapshot contains an unsafe path"
            )
        target = destination.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))


def _validate_owned_generated_tree(root: Path, session_root: Path) -> tuple[int, int]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    entry_count = 0
    total_bytes = 0
    while stack:
        directory, depth = stack.pop()
        for item in directory.iterdir():
            entry_count += 1
            if entry_count > _GENERATED_MAX_ENTRIES:
                raise RustMeshProtocolError(
                    "Mesh layer history contains too many generated entries"
                )
            _require_owned_path(item, session_root)
            if item.is_dir():
                if depth >= _GENERATED_MAX_DEPTH:
                    raise RustMeshProtocolError(
                        "Mesh layer history exceeds the directory-depth limit"
                    )
                stack.append((item, depth + 1))
                continue
            if not item.is_file():
                raise RustMeshProtocolError(
                    "Mesh layer history contains an unexpected entry"
                )
            length = item.stat().st_size
            if length > _GENERATED_MAX_FILE_BYTES:
                raise RustMeshProtocolError(
                    "Mesh layer history file exceeds the 64 MiB limit"
                )
            total_bytes += length
            if total_bytes > _GENERATED_MAX_TOTAL_BYTES:
                raise RustMeshProtocolError(
                    "Mesh layer history exceeds the 512 MiB session limit"
                )
    return entry_count, total_bytes


def _session_root_identity(
    root: Path | str,
    expected: tuple[int, int] | None = None,
) -> tuple[int, int]:
    path = Path(os.path.abspath(os.fspath(root)))
    if not path.exists() or path.is_symlink() or _is_reparse_point(path):
        raise RustMeshProtocolError(
            "Mesh session root is missing, replaced, or redirected"
        )
    if not path.is_dir():
        raise RustMeshProtocolError("Mesh session root is not a directory")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise RustMeshProtocolError("Mesh session root changed canonical location")
    root_stat = path.stat()
    identity = (int(root_stat.st_dev), int(root_stat.st_ino))
    if expected is not None and identity != tuple(expected):
        raise RustMeshProtocolError("Mesh session root was replaced")
    return identity


@contextmanager
def _pinned_session_root(
    root: Path,
    expected_identity: tuple[int, int],
):
    """Keep the allocated Windows directory from being renamed into a junction."""

    _session_root_identity(root, expected_identity)
    handle: int | None = None
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(root),
            0,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise RustMeshProtocolError(
                "Mesh session root could not be pinned for a safe operation"
            )
    try:
        _session_root_identity(root, expected_identity)
        yield
    finally:
        if handle is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _with_pinned_session_root(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with _pinned_session_root(self.root, self.root_identity):
            return method(self, *args, **kwargs)

    return wrapped


def _with_protocol_lock(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._protocol_lock:
            return method(self, *args, **kwargs)

    return wrapped


def _cleanup_failed_session_root(
    root: Path,
    expected_identity: tuple[int, int],
) -> None:
    """Quarantine and remove exactly the directory allocated by create()."""

    if not root.exists():
        return
    _session_root_identity(root, expected_identity)
    quarantine = root.parent / f".{root.name}.create-failed-{uuid4().hex}"
    os.replace(root, quarantine)
    try:
        quarantined = quarantine.stat()
        identity = (int(quarantined.st_dev), int(quarantined.st_ino))
        if identity != tuple(expected_identity):
            if not root.exists():
                os.replace(quarantine, root)
            raise RustMeshProtocolError(
                "Refusing to clean a replaced Mesh session directory"
            )
        shutil.rmtree(quarantine)
    except Exception:
        if quarantine.exists() and not root.exists():
            os.replace(quarantine, root)
        raise


def _validate_owned_session_tree(
    root: Path,
    expected_root_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    _session_root_identity(root, expected_root_identity)
    owned_root = root.resolve(strict=True)
    allowed_files = {
        "manifest.json",
        "document.json",
        "channels.json",
        "shadow-mesh-layers.json",
    }
    entry_count = 0
    total_bytes = 0
    for item in root.iterdir():
        entry_count += 1
        _require_owned_path(item, owned_root)
        name = item.name
        if item.is_file() and (
            name in allowed_files
            or _STATE_FILE_RE.fullmatch(name) is not None
            or _MATERIAL_STATE_FILE_RE.fullmatch(name) is not None
            or _CANDIDATE_FILE_RE.fullmatch(name) is not None
            or _TEXTURE_FILE_RE.fullmatch(name) is not None
            or _PREVIEW_GEOMETRY_FILE_RE.fullmatch(name) is not None
            or _PREVIEW_IDENTITY_FILE_RE.fullmatch(name) is not None
        ):
            total_bytes += item.stat().st_size
            continue
        if item.is_dir() and name == "mesh_slider_profiles":
            child_entries, child_bytes = _validate_owned_profile_tree(item)
            entry_count += child_entries
            total_bytes += child_bytes
            continue
        if item.is_dir() and _LAYER_GENERATION_RE.fullmatch(name) is not None:
            child_entries, child_bytes = _validate_owned_generated_tree(item, owned_root)
            entry_count += child_entries
            total_bytes += child_bytes
            continue
        raise RustMeshProtocolError(f"Unexpected Mesh session entry: {name}")
    if entry_count > _SESSION_MAX_ENTRIES:
        raise RustMeshProtocolError("Mesh session contains too many owned entries")
    if total_bytes > _SESSION_MAX_TOTAL_BYTES:
        raise RustMeshProtocolError("Mesh session exceeds the 768 MiB aggregate limit")
    _session_root_identity(root, expected_root_identity)
    return entry_count, total_bytes


def _discard_candidate_reference(
    root: Path,
    reference: object,
    *,
    expected_root_identity: tuple[int, int] | None = None,
) -> None:
    if not isinstance(reference, Mapping):
        return
    name = str(reference.get("path", "") or "")
    if _CANDIDATE_FILE_RE.fullmatch(name) is None:
        return
    candidate = root / name
    try:
        _session_root_identity(root, expected_root_identity)
        if (
            candidate.parent == root
            and candidate.is_file()
            and not candidate.is_symlink()
            and not _is_reparse_point(candidate)
        ):
            _require_owned_path(candidate, root)
            candidate.unlink()
    except (OSError, RustMeshProtocolError):
        pass


def _prune_state_payloads(
    root: Path,
    *,
    keep: Path | None = None,
    expected_root_identity: tuple[int, int] | None = None,
) -> None:
    _session_root_identity(root, expected_root_identity)
    for item in root.iterdir():
        if (
            item.is_file()
            and _STATE_FILE_RE.fullmatch(item.name) is not None
            and item != keep
        ):
            _require_owned_path(item, root)
            try:
                item.unlink()
            except OSError:
                # The newly published state document is already authoritative
                # for this response.  A locked obsolete document is cleanup
                # debt, not a reason to report the completed mutation as
                # failed.  Capacity projection retains every such document.
                pass


def _projected_state_payload_usage(
    root: Path,
    data_length: int,
    *,
    expected_root_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Return owned entry/byte usage after adding a state payload.

    The old recovery document must remain available until the new document is
    fully serialized and atomically installed.  Obsolete documents can also
    remain locked after publication, so they stay in the projection until a
    later best-effort prune removes them.  Computing this conservative usage up
    front lets an oversized response fail without pruning recovery state or
    exceeding the stable session bounds.
    """

    entry_count, total_bytes = _validate_owned_session_tree(
        root,
        expected_root_identity,
    )
    return entry_count + 1, total_bytes + max(0, int(data_length))


def _canonical_json_bytes(payload: object) -> bytes:
    # The standard encoder already owns dict/list/tuple and scalar traversal in
    # C. Walking every vertex through _json_safe first doubled large-mesh
    # startup work; only convert the uncommon object types when requested by
    # the encoder.
    return json.dumps(
        payload,
        default=_json_safe,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _atomic_write_payload(
    root: Path,
    name: str,
    payload: object,
    *,
    data_type: str = "json",
    element_count: int | None = None,
    expected_root_identity: tuple[int, int] | None = None,
) -> dict[str, object]:
    if Path(name).name != name or not name.lower().endswith(".json"):
        raise ValueError("Mesh payload names must be simple JSON filenames")
    data = _canonical_json_bytes(payload)
    if len(data) > RUST_MESH_MAX_PAYLOAD_BYTES:
        raise RustMeshProtocolError("Mesh payload exceeds the 512 MiB session limit")
    entry_count, total_bytes = _projected_state_payload_usage(
        root,
        len(data),
        expected_root_identity=expected_root_identity,
    )
    if entry_count > _SESSION_MAX_ENTRIES:
        raise RustMeshProtocolError("Mesh session contains too many owned entries")
    if total_bytes > _SESSION_MAX_TOTAL_BYTES:
        raise RustMeshProtocolError("Mesh session exceeds the 768 MiB aggregate limit")
    destination = root / name
    temporary = root / f".{name}.{uuid4().hex}.tmp"
    try:
        temporary.write_bytes(data)
        _session_root_identity(root, expected_root_identity)
        os.replace(temporary, destination)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
    return {
        "path": name,
        "data_type": str(data_type or "json"),
        "count": max(0, int(element_count if element_count is not None else 1)),
        "byte_length": len(data),
        "sha256": _sha256_bytes(data),
        "content_type": "application/json",
    }


def _atomic_write_state_payload(
    root: Path,
    name: str,
    payload: object,
    *,
    element_count: int,
    expected_root_identity: tuple[int, int] | None = None,
) -> dict[str, object]:
    if _STATE_FILE_RE.fullmatch(name) is None:
        raise ValueError("Mesh state payload name is invalid")
    data = _canonical_json_bytes(payload)
    if len(data) > RUST_MESH_MAX_PAYLOAD_BYTES:
        raise RustMeshProtocolError("Mesh payload exceeds the 512 MiB session limit")
    entry_count, total_bytes = _projected_state_payload_usage(
        root,
        len(data),
        expected_root_identity=expected_root_identity,
    )
    if entry_count > _SESSION_MAX_ENTRIES:
        raise RustMeshProtocolError("Mesh session contains too many owned entries")
    if total_bytes > _SESSION_MAX_TOTAL_BYTES:
        raise RustMeshProtocolError("Mesh session exceeds the 768 MiB aggregate limit")

    destination = root / name
    temporary = root / f".{name}.{uuid4().hex}.tmp"
    try:
        temporary.write_bytes(data)
        _session_root_identity(root, expected_root_identity)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    _prune_state_payloads(
        root,
        keep=destination,
        expected_root_identity=expected_root_identity,
    )
    return {
        "path": name,
        "data_type": "mesh_document_json",
        "count": max(0, int(element_count)),
        "byte_length": len(data),
        "sha256": _sha256_bytes(data),
        "content_type": "application/json",
    }


def read_owned_payload_reference(
    root: Path | str,
    reference: Mapping[str, object],
    *,
    candidate_only: bool = False,
    expected_root_identity: tuple[int, int] | None = None,
) -> dict[str, object]:
    root_path = Path(root)
    pinned_identity = _session_root_identity(root_path, expected_root_identity)
    owned_root = root_path.resolve(strict=True)
    resolved_root_stat = owned_root.stat()
    resolved_root_identity = (
        int(resolved_root_stat.st_dev),
        int(resolved_root_stat.st_ino),
    )
    if resolved_root_identity != pinned_identity:
        raise RustMeshProtocolError("Mesh session root changed while opening a payload")
    relative_text = str(reference.get("path", "") or "").strip()
    relative = Path(relative_text)
    if (
        not relative_text
        or relative.is_absolute()
        or len(relative.parts) != 1
        or relative.name != relative_text
        or relative.suffix.lower() != ".json"
    ):
        raise RustMeshProtocolError("Mesh payload path must be one owned JSON filename")
    if candidate_only and _CANDIDATE_FILE_RE.fullmatch(relative.name) is None:
        raise RustMeshProtocolError("Mesh candidate filename is not session-owned")
    candidate = (owned_root / relative).resolve(strict=True)
    if candidate.parent != owned_root or not candidate.is_file():
        raise RustMeshProtocolError("Mesh payload escaped its owned session directory")
    _require_owned_path(candidate, owned_root)
    candidate_stat = candidate.stat()
    try:
        declared_size = int(reference.get("byte_length", -1))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError("Mesh payload byte length is invalid") from exc
    if declared_size < 0 or declared_size != candidate_stat.st_size:
        raise RustMeshProtocolError("Mesh payload byte length does not match")
    if candidate_stat.st_size > RUST_MESH_MAX_PAYLOAD_BYTES:
        raise RustMeshProtocolError("Mesh payload exceeds the 512 MiB session limit")
    data_type = str(reference.get("data_type", "") or "").strip()
    content_type = str(reference.get("content_type", "") or "").strip().lower()
    try:
        declared_count = int(reference.get("count", -1))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError("Mesh payload element count is invalid") from exc
    if not data_type or declared_count < 0:
        raise RustMeshProtocolError("Mesh payload type or element count is missing")
    if content_type != "application/json":
        raise RustMeshProtocolError("Mesh payload content type must be application/json")
    if candidate_only and data_type != "mesh_candidate_json":
        raise RustMeshProtocolError("Mesh candidate data type does not match")
    with candidate.open("rb") as stream:
        opened_stat = os.fstat(stream.fileno())
        if (
            int(opened_stat.st_dev) != int(candidate_stat.st_dev)
            or int(opened_stat.st_ino) != int(candidate_stat.st_ino)
            or int(opened_stat.st_size) != declared_size
        ):
            raise RustMeshProtocolError("Mesh payload changed before it could be read")
        data = stream.read(declared_size + 1)
        final_stat = os.fstat(stream.fileno())
    if len(data) != declared_size or int(final_stat.st_size) != declared_size:
        raise RustMeshProtocolError("Mesh payload changed while it was being read")
    _session_root_identity(root_path, expected_root_identity)
    current_stat = candidate.stat()
    if (
        int(current_stat.st_dev) != int(candidate_stat.st_dev)
        or int(current_stat.st_ino) != int(candidate_stat.st_ino)
        or int(current_stat.st_size) != declared_size
    ):
        raise RustMeshProtocolError("Mesh payload was replaced while it was being read")
    declared_hash = str(reference.get("sha256", "") or "").strip().upper()
    if len(declared_hash) != 64 or declared_hash != _sha256_bytes(data):
        raise RustMeshProtocolError("Mesh payload SHA-256 does not match")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RustMeshProtocolError("Mesh payload is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise RustMeshProtocolError("Mesh payload root must be an object")
    if candidate_only:
        raw_submeshes = payload.get("submeshes")
        if not isinstance(raw_submeshes, list) or declared_count != len(raw_submeshes):
            raise RustMeshProtocolError("Mesh candidate element count does not match")
    return payload


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        return [_json_safe(item) for item in value]
    return str(value)


def _mesh_lods(mesh: ParsedMesh) -> tuple[tuple[object, ...], ...]:
    lod_levels = tuple(tuple(level or ()) for level in tuple(mesh.lod_levels or ()))
    if lod_levels:
        return lod_levels
    return (tuple(mesh.submeshes or ()),)


def _mesh_format(mesh: ParsedMesh) -> str:
    value = str(mesh.format or "").strip().lower()
    if value not in {"pac", "pam", "pamlod"}:
        raise RustMeshValidationError(
            f"Edit Mesh requires PAC, PAM, or PAMLOD input; received {value or 'unknown'}."
        )
    return value


def _source_hash(mesh: ParsedMesh) -> str:
    explicit = str(
        getattr(mesh, "_cdmw_mesh_asset_source_hash", "")
        or getattr(mesh, "_cdmw_sidecar_source_asset_hash", "")
        or ""
    ).strip()
    if explicit:
        return explicit.upper()
    original_data = bytes(getattr(mesh, "_cdmw_original_data", b"") or b"")
    return _sha256_bytes(original_data) if original_data else ""


def _submesh_indices(submesh: object) -> list[int]:
    return [int(index) for face in tuple(getattr(submesh, "faces", ()) or ()) for index in face]


def _mesh_document_payload(
    mesh: ParsedMesh,
    *,
    allow_preview_formats: bool = False,
) -> dict[str, object]:
    lod_payloads: list[dict[str, object]] = []
    fingerprint = hashlib.sha256()
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        encoded_submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes):
            positions = [list(map(float, row)) for row in tuple(getattr(submesh, "vertices", ()) or ())]
            normals = [list(map(float, row)) for row in tuple(getattr(submesh, "normals", ()) or ())]
            uvs = [list(map(float, row)) for row in tuple(getattr(submesh, "uvs", ()) or ())]
            indices = _submesh_indices(submesh)
            fingerprint.update(_canonical_json_bytes((positions, indices)))
            encoded_submeshes.append(
                {
                    "name": str(getattr(submesh, "name", "") or f"Part {submesh_index + 1}"),
                    "material": str(getattr(submesh, "material", "") or ""),
                    "positions": positions,
                    "normals": normals,
                    "uvs": uvs,
                    "indices": indices,
                    # In the managed session this is the current local vertex index.
                    # Original-relative provenance remains authoritative in CDMW.
                    "source_vertex_indices": list(range(len(positions))),
                    "source_range": {"offset": 0, "length": 0},
                    "vertex_stride": int(getattr(submesh, "source_vertex_stride", 0) or 0),
                    "layout": str(getattr(submesh, "source_skin_weight_layout", "") or "cdmw_session"),
                }
            )
        lod_payloads.append({"level": lod_index, "submeshes": encoded_submeshes})
    if allow_preview_formats:
        source_format = str(mesh.format or "").strip().lower()
        mesh_format = (
            source_format
            if source_format in {"pac", "pam", "pamlod"}
            else "preview"
        )
    else:
        mesh_format = _mesh_format(mesh)
    return {
        "format": mesh_format,
        "source_sha256": _source_hash(mesh),
        "parser": RUST_MESH_AUTHORING_PACKAGE,
        "lod_count_reported": len(lod_payloads),
        "lods": lod_payloads,
        "warnings": [],
        "structural_fingerprint": fingerprint.hexdigest().upper(),
    }


def _mesh_channel_payload(mesh: ParsedMesh) -> dict[str, object]:
    """Encode channels that are not already authoritative in document.json.

    Positions, normals, UV0, and triangle indices used to be emitted a second
    time here even though the Rust renderer loads them from ``document.json``.
    Keep the PAC-only authoring/provenance channels and point explicitly at the
    matching document row instead, which materially shortens every launch.
    """

    lods: list[dict[str, object]] = []
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes):
            items.append(
                {
                    "submesh_index": submesh_index,
                    "name": str(getattr(submesh, "name", "") or ""),
                    "material": str(getattr(submesh, "material", "") or ""),
                    "texture": str(getattr(submesh, "texture", "") or ""),
                    "document_submesh": {
                        "lod_index": lod_index,
                        "submesh_index": submesh_index,
                    },
                    "tangents": tuple(getattr(submesh, "tangents", ()) or ()),
                    "uv1": tuple(
                        getattr(submesh, "uv1", ())
                        or getattr(submesh, "uvs1", ())
                        or getattr(submesh, "secondary_uvs", ())
                        or ()
                    ),
                    "bone_indices": tuple(getattr(submesh, "bone_indices", ()) or ()),
                    "bone_weights": tuple(getattr(submesh, "bone_weights", ()) or ()),
                    "source_vertex_map": tuple(getattr(submesh, "source_vertex_map", ()) or ()),
                    "source_vertex_offsets": tuple(getattr(submesh, "source_vertex_offsets", ()) or ()),
                    "source_index_offset": int(
                        -1
                        if getattr(submesh, "source_index_offset", None) is None
                        else getattr(submesh, "source_index_offset")
                    ),
                    "source_index_count": int(getattr(submesh, "source_index_count", 0) or 0),
                    "source_face_map": tuple(getattr(submesh, "source_face_map", ()) or ()),
                    "source_vertex_map_authority": str(
                        getattr(submesh, "source_vertex_map_authority", "") or ""
                    ),
                    "topology_provenance": getattr(submesh, "topology_provenance", None),
                }
            )
        lods.append({"lod_index": lod_index, "submeshes": items})
    return {
        "schema": RUST_MESH_AUTHORING_PACKAGE,
        "geometry_source": {
            "path": "document.json",
            "channels": ["positions", "normals", "uv0", "indices"],
        },
        "lods": lods,
    }


def _resolved_dds_path(value: object, *, declared_dds: bool = False) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    size = resolved.stat().st_size
    if size <= 0 or size > _TEXTURE_MAX_FILE_BYTES:
        raise RustMeshProtocolError(
            f"Mesh texture payload is outside the 512 MiB file limit: {resolved.name}"
        )
    try:
        with resolved.open("rb") as stream:
            signature = stream.read(4)
    except OSError as exc:
        raise RustMeshProtocolError(
            f"Mesh could not read resolved texture {resolved.name}: {exc}"
        ) from exc
    if signature != b"DDS ":
        if declared_dds or resolved.suffix.casefold() == ".dds":
            raise RustMeshProtocolError(
                f"Mesh resolved texture is not a DDS payload: {resolved.name}"
            )
        return None
    return resolved


def _rust_material_package_root(
    material_package_path: object,
) -> tuple[Path | None, str]:
    text = str(material_package_path or "").strip()
    if not text:
        return None, ""
    try:
        candidate = Path(text).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None, "Resolved Archive Browser texture package is unavailable."
    if candidate.is_file() and candidate.name.casefold() == "manifest.json":
        candidate = candidate.parent
    if not candidate.is_dir():
        return None, "Resolved Archive Browser texture package is unavailable."
    return candidate, ""


def _rust_material_package_presentation_overrides(
    mesh: ParsedMesh,
    package_root: Path,
    *,
    stop_event: threading.Event | None,
) -> dict[tuple[int, int], dict[str, object]]:
    """Retain the exact per-owner presentation already proven by CDMW.

    ``net_materials.json`` is the compatibility material manifest emitted by
    the shared Archive Preview Core contract. The editable mesh copy can lose
    its decoded PAC category, so
    read only the bounded presentation fields from the leased package and
    require an exact part index/name match before forwarding them to Rust.
    Texture paths and arbitrary parameters are deliberately excluded here.
    """

    materials_path = package_root / "net_materials.json"
    try:
        _require_owned_path(materials_path, package_root)
        payload_bytes = read_file_bytes_cancellable(
            materials_path,
            stop_event=stop_event,
            max_bytes=_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
        )
        payload = json.loads(payload_bytes)
    except RunCancelled as exc:
        raise RustMeshCancellationError(
            "Mesh texture preparation was cancelled"
        ) from exc
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    rows = payload.get("submeshes", ())
    if not isinstance(rows, Sequence) or isinstance(
        rows,
        (str, bytes, bytearray),
    ):
        return {}

    lods = _mesh_lods(mesh)
    try:
        lod_index = max(
            0,
            min(
                len(lods) - 1,
                int(
                    getattr(
                        mesh,
                        "active_lod_index",
                        getattr(mesh, "displayed_lod_index", 0),
                    )
                    or 0
                ),
            ),
        )
    except (TypeError, ValueError, OverflowError):
        lod_index = 0
    submeshes = lods[lod_index]
    if len(rows) != len(submeshes) or len(rows) > _RUST_MATERIAL_PRESENTATION_LIMIT:
        return {}

    result: dict[tuple[int, int], dict[str, object]] = {}
    seen: set[int] = set()
    for fallback_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            return {}
        try:
            submesh_index = int(row.get("submesh_index", fallback_index))
        except (TypeError, ValueError, OverflowError):
            return {}
        if (
            submesh_index < 0
            or submesh_index >= len(submeshes)
            or submesh_index in seen
        ):
            return {}
        expected_material = str(
            getattr(submeshes[submesh_index], "material", "") or ""
        ).strip()
        actual_material = str(
            row.get("material", row.get("material_name", "")) or ""
        ).strip()
        if expected_material.casefold() != actual_material.casefold():
            return {}
        seen.add(submesh_index)

        category = str(
            row.get("material_category", MATERIAL_CATEGORY_UNCLASSIFIED)
            or MATERIAL_CATEGORY_UNCLASSIFIED
        ).strip().casefold()
        if not is_known_material_category(category):
            category = MATERIAL_CATEGORY_UNCLASSIFIED
        try:
            confidence = float(row.get("material_category_confidence", 0.35))
        except (TypeError, ValueError, OverflowError):
            confidence = 0.35
        if not math.isfinite(confidence):
            confidence = 0.35
        shader_family = str(row.get("shader_family", "generic") or "generic").strip()
        if not shader_family or len(shader_family) > 64:
            shader_family = "generic"
        normal_y_policy = str(
            row.get("normal_y_policy", "preserve") or "preserve"
        ).strip().casefold()
        if normal_y_policy not in {"preserve", "invert_green_for_directx"}:
            normal_y_policy = "preserve"
        alpha_mode = str(row.get("alpha_mode", "opaque") or "opaque").strip().casefold()
        if alpha_mode not in {"opaque", "cutout", "blend"}:
            alpha_mode = "opaque"
        try:
            alpha_cutoff = float(row.get("alpha_cutoff", 0.5))
        except (TypeError, ValueError, OverflowError):
            alpha_cutoff = 0.5
        if not math.isfinite(alpha_cutoff):
            alpha_cutoff = 0.5
        result[(lod_index, submesh_index)] = {
            "material_category": category,
            "material_category_confidence": max(0.0, min(1.0, confidence)),
            "shader_family": shader_family,
            "normal_y_policy": normal_y_policy,
            "alpha_mode": alpha_mode,
            "alpha_cutoff": max(0.0, min(1.0, alpha_cutoff)),
            "double_sided": bool(row.get("double_sided", False)),
        }
    return result if seen == set(range(len(submeshes))) else {}


def _rust_material_package_external_texture_roots(
    package_root: Path,
) -> tuple[Path, ...]:
    """Return only the DDS caches governed by this preview package lease.

    Archive Browser's durable package is stored below ``preview/models`` while
    its native, directly uploadable DDS files live below the sibling
    ``preview/native/dds`` cache.  The package-cache lease deliberately keeps
    manifest-referenced DDS files alive during pruning, so Rust may copy those
    exact manifest members into its own session.  Unrelated absolute paths are
    never admitted merely because they appear on a preview-model object.
    """

    root = package_root.resolve()
    candidates: list[Path] = []
    for ancestor in (root, *root.parents):
        name = ancestor.name.casefold()
        if name == "models":
            candidates.append(ancestor.parent / "native" / "dds")
            break
        if name == "native_preview_core":
            candidates.append(ancestor / "dds")
            break
    resolved: list[Path] = []
    for candidate in candidates:
        try:
            path = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if path.is_dir() and path not in resolved:
            resolved.append(path)
    return tuple(resolved)


def _rust_material_package_declared_texture_paths(
    package_root: Path | None,
    *,
    stop_event: threading.Event | None = None,
) -> frozenset[str]:
    """Snapshot exact readable DDS paths declared by one leased manifest.

    This runs on the Rust preparation worker.  The UI only hands over the
    already-leased package path and never reads package or texture files.
    """

    if package_root is None:
        return frozenset()
    manifest_path = package_root / "manifest.json"
    try:
        manifest_stat = manifest_path.stat()
    except OSError:
        return frozenset()
    if (
        not manifest_path.is_file()
        or manifest_stat.st_size <= 0
        or manifest_stat.st_size > _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES
    ):
        return frozenset()
    if stop_event is not None and stop_event.is_set():
        raise RustMeshCancellationError("Mesh texture preparation was cancelled")
    try:
        with manifest_path.open("rb") as stream:
            manifest_bytes = stream.read(
                _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES + 1
            )
    except (OSError, UnicodeError, ValueError):
        return frozenset()
    if len(manifest_bytes) > _RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES:
        return frozenset()
    try:
        payload = json.loads(manifest_bytes)
    except (UnicodeError, ValueError):
        return frozenset()
    if stop_event is not None and stop_event.is_set():
        raise RustMeshCancellationError("Mesh texture preparation was cancelled")
    if not isinstance(payload, Mapping):
        return frozenset()
    batches = payload.get("batches")
    if not isinstance(batches, Sequence) or isinstance(
        batches,
        (str, bytes, bytearray),
    ):
        return frozenset()
    if len(batches) > _RUST_PREVIEW_PACKAGE_BATCH_LIMIT:
        return frozenset()

    package_root = package_root.resolve()
    external_roots = _rust_material_package_external_texture_roots(package_root)
    paths: set[str] = set()
    descriptor_count = 0

    def contained(path: Path) -> bool:
        for root in (package_root, *external_roots):
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def remember(descriptor: object) -> bool:
        nonlocal descriptor_count
        if not isinstance(descriptor, Mapping):
            return True
        descriptor_count += 1
        if descriptor_count > _RUST_PREVIEW_PACKAGE_TEXTURE_LIMIT:
            return False
        if descriptor.get("available") is False or descriptor.get(
            "direct_upload_candidate"
        ) is False:
            return True
        text = str(
            descriptor.get("source_path", "")
            or descriptor.get("source_dds_path", "")
            or descriptor.get("source_texture_path", "")
            or ""
        ).strip()
        if not text or len(text) > 32_768:
            return True
        try:
            source = Path(text).expanduser()
            resolved = (
                source if source.is_absolute() else package_root / source
            ).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return True
        if not resolved.is_file() or not contained(resolved):
            return True
        try:
            with resolved.open("rb") as stream:
                if stream.read(4) != b"DDS ":
                    return True
        except OSError:
            return True
        paths.add(os.path.normcase(str(resolved)))
        return True

    for batch in batches:
        if stop_event is not None and stop_event.is_set():
            raise RustMeshCancellationError(
                "Mesh texture preparation was cancelled"
            )
        if not isinstance(batch, Mapping):
            continue
        dds_textures = batch.get("dds_textures")
        if not isinstance(dds_textures, Mapping):
            continue
        for key, descriptor in dds_textures.items():
            if key == "material_inputs" and isinstance(
                descriptor,
                Sequence,
            ) and not isinstance(descriptor, (str, bytes, bytearray)):
                for material_input in descriptor:
                    if not remember(material_input):
                        return frozenset()
            elif not remember(descriptor):
                return frozenset()
    return frozenset(paths)


def _rust_material_package_owned_texture_aliases(
    package_root: Path | None,
    *,
    stop_event: threading.Event | None = None,
) -> Mapping[str, str]:
    """Map package-declared source identities onto owned DDS copies.

    Full .NET preview packages keep the original absolute cache path only as
    provenance in ``net_materials.json``.  Rust must not copy that external
    path directly: it resolves the provenance key to the package-owned
    ``resources[].path`` member, verifies its content fingerprint, and copies
    that bounded file into the isolated authoring session instead.
    """

    if package_root is None:
        return MappingProxyType({})
    materials_path = package_root / "net_materials.json"
    try:
        _require_owned_path(materials_path, package_root)
        payload_bytes = read_file_bytes_cancellable(
            materials_path,
            stop_event=stop_event,
            max_bytes=_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES,
        )
        payload = json.loads(payload_bytes)
    except RunCancelled as exc:
        raise RustMeshCancellationError(
            "Mesh texture preparation was cancelled"
        ) from exc
    except (OSError, UnicodeError, ValueError, TypeError):
        return MappingProxyType({})
    if not isinstance(payload, Mapping):
        return MappingProxyType({})
    resources = payload.get("resources", ())
    if not isinstance(resources, Sequence) or isinstance(
        resources,
        (str, bytes, bytearray),
    ) or len(resources) > _RUST_PREVIEW_PACKAGE_TEXTURE_LIMIT:
        return MappingProxyType({})

    root = package_root.resolve()
    aliases: dict[str, str] = {}
    alias_fingerprints: dict[str, str] = {}
    conflicts: set[str] = set()
    for resource in resources:
        if stop_event is not None and stop_event.is_set():
            raise RustMeshCancellationError(
                "Mesh texture preparation was cancelled"
            )
        if not isinstance(resource, Mapping):
            continue
        relative_text = str(resource.get("path", "") or "").strip()
        source_text = str(resource.get("source_reference", "") or "").strip()
        fingerprint = str(resource.get("fingerprint", "") or "").strip()
        if (
            not relative_text
            or not source_text
            or len(relative_text) > 32_768
            or len(source_text) > 32_768
            or "\\" in relative_text
            or ":" in relative_text
            or not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint)
        ):
            continue
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            continue
        try:
            owned = root.joinpath(*relative.parts).resolve(strict=True)
            owned.relative_to(root)
            source = Path(source_text).expanduser()
            if not source.is_absolute():
                continue
            source_key = os.path.normcase(os.path.abspath(os.fspath(source)))
            stat_result = owned.stat()
        except (OSError, RuntimeError, ValueError):
            continue
        if (
            not owned.is_file()
            or stat_result.st_size <= 0
            or stat_result.st_size > _TEXTURE_MAX_FILE_BYTES
        ):
            continue
        digest = hashlib.sha256()
        try:
            with owned.open("rb") as stream:
                if stream.read(4) != b"DDS ":
                    continue
                digest.update(b"DDS ")
                while chunk := stream.read(1024 * 1024):
                    if stop_event is not None and stop_event.is_set():
                        raise RustMeshCancellationError(
                            "Mesh texture preparation was cancelled"
                        )
                    digest.update(chunk)
        except RustMeshCancellationError:
            raise
        except OSError:
            continue
        if digest.hexdigest().casefold() != fingerprint.casefold():
            continue
        owned_text = str(owned)
        previous = aliases.get(source_key)
        if previous is not None and os.path.normcase(previous) != os.path.normcase(
            owned_text
        ):
            if alias_fingerprints.get(source_key, "").casefold() == fingerprint.casefold():
                # The package may publish the same owned bytes under multiple
                # channel-specific resource names.  Either copy is exact.
                continue
            conflicts.add(source_key)
            aliases.pop(source_key, None)
            alias_fingerprints.pop(source_key, None)
            continue
        if source_key not in conflicts:
            aliases[source_key] = owned_text
            alias_fingerprints[source_key] = fingerprint
    return MappingProxyType(aliases)


def _package_resolved_texture_path(
    value: object,
    package_root: Path | None,
    *,
    require_package_root: bool = False,
    declared_texture_paths: frozenset[str] = frozenset(),
    owned_texture_aliases: Mapping[str, str] = MappingProxyType({}),
) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        source = Path(text).expanduser()
        if package_root is None:
            if require_package_root or not source.is_absolute():
                return ""
            resolved = source.resolve(strict=True)
        else:
            if source.is_absolute():
                alias = owned_texture_aliases.get(
                    os.path.normcase(os.path.abspath(os.fspath(source)))
                )
                if alias:
                    owned = Path(alias).resolve(strict=True)
                    owned.relative_to(package_root)
                    return str(owned) if owned.is_file() else ""
            resolved = (
                source if source.is_absolute() else package_root / source
            ).resolve(strict=True)
            try:
                resolved.relative_to(package_root)
            except ValueError:
                if os.path.normcase(str(resolved)) not in declared_texture_paths:
                    return ""
    except (OSError, RuntimeError, ValueError):
        return ""
    return str(resolved) if resolved.is_file() else ""


def _rebase_rust_material_input_paths(
    value: object,
    package_root: Path | None,
    *,
    require_package_root: bool,
    declared_texture_paths: frozenset[str],
    owned_texture_aliases: Mapping[str, str],
) -> tuple[object, int, int]:
    updates: dict[str, str] = {}
    rejected_count = 0
    for field_name in (
        "source_dds_path",
        "source_texture_path",
        "preview_texture_path",
    ):
        current = str(getattr(value, field_name, "") or "").strip()
        rebased = _package_resolved_texture_path(
            current,
            package_root,
            require_package_root=require_package_root,
            declared_texture_paths=declared_texture_paths,
            owned_texture_aliases=owned_texture_aliases,
        )
        if current and rebased != current:
            updates[field_name] = rebased
            rejected_count += int(not rebased)
    if not updates:
        return value, 0, rejected_count
    if is_dataclass(value):
        field_names = set(getattr(value, "__dataclass_fields__", {}))
        applicable = {key: item for key, item in updates.items() if key in field_names}
        if applicable:
            return replace(value, **applicable), len(applicable), rejected_count
        return value, 0, rejected_count
    try:
        copied = copy.deepcopy(value)
        for key, item in updates.items():
            setattr(copied, key, item)
        return copied, len(updates), rejected_count
    except (AttributeError, TypeError, RuntimeError):
        return value, 0, rejected_count


def _rebase_rust_preview_texture_paths(
    mesh: ParsedMesh,
    material_package_path: object,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[int, str]:
    require_package_root = bool(str(material_package_path or "").strip())
    package_root, unavailable_reason = _rust_material_package_root(
        material_package_path
    )
    declared_texture_paths = _rust_material_package_declared_texture_paths(
        package_root,
        stop_event=stop_event,
    )
    owned_texture_aliases = _rust_material_package_owned_texture_aliases(
        package_root,
        stop_event=stop_event,
    )
    path_attributes = tuple(
        dict.fromkeys(
            attribute
            for _role, attributes in _TEXTURE_RESOURCE_SPECS
            for attribute in attributes
            if attribute != "texture"
        )
    )
    rebased_count = 0
    rejected_count = 0
    for submeshes in _mesh_lods(mesh):
        for submesh in submeshes:
            for attribute in path_attributes:
                current = str(getattr(submesh, attribute, "") or "").strip()
                rebased = _package_resolved_texture_path(
                    current,
                    package_root,
                    require_package_root=require_package_root,
                    declared_texture_paths=declared_texture_paths,
                    owned_texture_aliases=owned_texture_aliases,
                )
                if current and rebased != current:
                    if not rebased:
                        companion = _RUST_TEXTURE_PATH_NAME_COMPANIONS.get(attribute)
                        if companion and not str(
                            getattr(submesh, companion, "") or ""
                        ).strip():
                            basenames = _rust_exact_texture_basenames(current)
                            if basenames:
                                setattr(submesh, companion, basenames[0])
                    setattr(submesh, attribute, rebased)
                    rebased_count += 1
                    rejected_count += int(not rebased)
            inputs = tuple(
                getattr(submesh, "preview_material_texture_inputs", ()) or ()
            )
            if not inputs:
                continue
            updated_inputs: list[object] = []
            changed = False
            for item in inputs:
                updated, count, rejected = _rebase_rust_material_input_paths(
                    item,
                    package_root,
                    require_package_root=require_package_root,
                    declared_texture_paths=declared_texture_paths,
                    owned_texture_aliases=owned_texture_aliases,
                )
                updated_inputs.append(updated)
                rebased_count += count
                rejected_count += rejected
                changed = changed or count > 0
            if changed:
                setattr(
                    submesh,
                    "preview_material_texture_inputs",
                    tuple(updated_inputs),
                )
    if unavailable_reason:
        return rebased_count, unavailable_reason
    if rejected_count:
        return (
            rebased_count,
            "Resolved Archive Browser texture references were missing or outside the leased package.",
        )
    return rebased_count, ""


def _first_resolved_dds_path(source: object, attributes: Sequence[str]) -> Path | None:
    for attribute in attributes:
        path = _resolved_dds_path(
            getattr(source, attribute, ""),
            declared_dds="dds_path" in attribute,
        )
        if path is not None:
            return path
    return None


_RUST_ARCHIVE_TEXTURE_ROLE_CANDIDATES: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "base_color",
        ("",),
        ("preview_texture_dds_path", "preview_texture_path"),
    ),
    (
        "normal",
        ("_n",),
        ("preview_normal_texture_dds_path", "preview_normal_texture_path"),
    ),
    (
        "material",
        ("_sp",),
        ("preview_material_texture_dds_path", "preview_material_texture_path"),
    ),
    (
        "height",
        (),
        ("preview_height_texture_dds_path", "preview_height_texture_path"),
    ),
    (
        "emissive",
        (),
        ("preview_emissive_texture_dds_path", "preview_emissive_texture_path"),
    ),
)


def _rust_texture_entry_basename_index(
    context: _RustMeshPreviewMaterialContext | None,
) -> dict[str, tuple[ArchiveEntry, ...]]:
    result: dict[str, list[ArchiveEntry]] = {}
    for entry in tuple(getattr(context, "texture_entries", ()) or ()):
        if not isinstance(entry, ArchiveEntry) or entry.extension != ".dds":
            continue
        key = Path(str(entry.path or "").replace("\\", "/")).name.casefold()
        if key:
            result.setdefault(key, []).append(entry)
    return {key: tuple(values) for key, values in result.items()}


def _rust_role_texture_candidates(
    texture_name: object,
    material_name: object,
    suffixes: Sequence[str],
) -> tuple[str, ...]:
    candidates: list[str] = []
    for base_name in _rust_texture_identity_candidates(texture_name, material_name):
        stem = base_name[:-4]
        for suffix in suffixes:
            candidate = f"{stem}{suffix}.dds"
            if candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates[:96])


def _rust_exact_texture_path_hints(
    candidate: str,
    *values: object,
) -> tuple[str, ...]:
    """Return only caller-supplied virtual paths that exactly name candidate."""

    expected_name = PurePosixPath(candidate.replace("\\", "/")).name.casefold()
    paths: list[str] = []
    for value in values:
        text = str(value or "").replace("\\", "/").strip().strip("/")
        if "/" not in text:
            continue
        if re.match(r"^[a-zA-Z]:/", text) or str(value or "").strip().startswith(
            ("/", "\\")
        ):
            # Local cache paths are not virtual archive ownership evidence.
            continue
        path = PurePosixPath(text.casefold())
        if path.suffix != ".dds":
            path = path.with_suffix(".dds")
        normalized = path.as_posix()
        if path.name == expected_name and normalized not in paths:
            paths.append(normalized)
    return tuple(paths)


def _unambiguous_rust_texture_entries(
    candidate: str,
    entries: Sequence[ArchiveEntry],
    *,
    target_entry: ArchiveEntry | None,
    exact_path_hints: Sequence[str] = (),
) -> tuple[ArchiveEntry, ...]:
    """Fail closed on overlay collisions unless one owner is uniquely proven."""

    unique = {
        entry.identity: entry
        for entry in entries
        if isinstance(entry, ArchiveEntry)
        and entry.extension == ".dds"
        and entry.basename.casefold()
        == PurePosixPath(candidate.replace("\\", "/")).name.casefold()
    }
    candidates = tuple(unique.values())
    if not candidates:
        return ()
    path_hints = {
        PurePosixPath(
            str(value or "").replace("\\", "/").strip().strip("/")
        )
        .as_posix()
        .casefold()
        for value in exact_path_hints
        if str(value or "").strip()
    }
    target_pamt = (
        target_entry.identity.source_pamt
        if isinstance(target_entry, ArchiveEntry)
        else ""
    )
    # Supplied ownership evidence is a constraint even when basename lookup
    # happened to yield only one entry.  Otherwise a lone wrong-path overlay
    # (or wrong PAMT owner) would be accepted merely because its collision was
    # not present in the bounded snapshot.
    proven = {entry.identity for entry in candidates}
    has_proof = False
    if path_hints:
        has_proof = True
        proven.intersection_update(
            entry.identity
            for entry in candidates
            if entry.identity.normalized_path in path_hints
        )
    if target_pamt:
        has_proof = True
        proven.intersection_update(
            entry.identity
            for entry in candidates
            if entry.identity.source_pamt == target_pamt
        )
    if not proven or (len(unique) > 1 and not has_proof):
        return ()
    if len(proven) != 1:
        return ()
    identity = next(iter(proven))
    return (unique[identity],)


def _resolve_proven_rust_texture_entry(
    entry: ArchiveEntry,
    *,
    stop_event: threading.Event | None,
) -> Path | None:
    """Extract one already-proven ArchiveEntry without a local-name lookup."""

    try:
        source_path, _note = ensure_archive_preview_source(
            entry,
            stop_event=stop_event,
        )
    except TypeError:
        # Preserve compatibility with test doubles and older archive readers
        # that predate cancellation, while retaining the exact entry identity.
        source_path, _note = ensure_archive_preview_source(entry)
    return _resolved_dds_path(source_path, declared_dds=True)


def _resolve_material_input_archive_fallbacks(inputs, submesh, entries_by_basename, target_entry, stop_event, resolved_count):
    if inputs:
        updated_inputs: list[object] = []
        inputs_changed = False
        for item in inputs:
            updated_item = item
            if _material_input_dds_path(item) is None:
                identity_values = tuple(
                    getattr(item, attribute, "")
                    for attribute in (
                        "texture_name",
                        "source_texture_path",
                        "source_dds_path",
                        "preview_texture_path",
                    )
                )
                for candidate in _rust_material_input_exact_basenames(item):
                    if stop_event is not None and stop_event.is_set():
                        raise RustMeshCancellationError(
                            "Mesh texture preparation was cancelled"
                        )
                    matching_entries = _unambiguous_rust_texture_entries(
                        candidate,
                        entries_by_basename.get(candidate.casefold(), ()),
                        target_entry=target_entry
                        if isinstance(target_entry, ArchiveEntry)
                        else None,
                        exact_path_hints=_rust_exact_texture_path_hints(
                            candidate,
                            *identity_values,
                        ),
                    )
                    if not matching_entries:
                        continue
                    try:
                        resolved = _resolve_proven_rust_texture_entry(
                            matching_entries[0],
                            stop_event=stop_event,
                        )
                    except Exception:
                        if stop_event is not None and stop_event.is_set():
                            raise RustMeshCancellationError(
                                "Mesh texture preparation was cancelled"
                            )
                        continue
                    if resolved is None:
                        continue
                    field_names = set(
                        getattr(item, "__dataclass_fields__", {})
                    )
                    if (
                        is_dataclass(item)
                        and not isinstance(item, type)
                        and "source_dds_path" in field_names
                    ):
                        updated_item = replace(
                            item,
                            source_dds_path=str(resolved),
                        )
                    else:
                        try:
                            updated_item = copy.deepcopy(item)
                            setattr(
                                updated_item,
                                "source_dds_path",
                                str(resolved),
                            )
                        except (AttributeError, TypeError, RuntimeError):
                            updated_item = item
                    if updated_item is not item:
                        inputs_changed = True
                        resolved_count += 1
                    break
            updated_inputs.append(updated_item)
        if inputs_changed:
            setattr(
                submesh,
                "preview_material_texture_inputs",
                tuple(updated_inputs),
            )
    return resolved_count


def _resolve_rust_archive_texture_fallbacks(
    mesh: ParsedMesh,
    context: _RustMeshPreviewMaterialContext | None,
    *,
    stop_event: threading.Event | None,
) -> int:
    """Resolve only captured archive entries into the isolated shadow mesh.

    This is the package-miss branch used when Archive Browser has geometry and
    material identities but its cached renderer package contains no DDS files.
    The UI captures a bounded immutable entry set before the worker starts; the
    worker performs archive I/O, validates DDS payloads, and the normal manifest
    writer immediately copies them into the owned session directory.
    """

    entries_by_basename = _rust_texture_entry_basename_index(context)
    if not entries_by_basename:
        return 0
    target_entry = getattr(context, "target_entry", None)
    resolved_count = 0
    for level in _mesh_lods(mesh):
        for submesh in level:
            inputs = tuple(
                getattr(submesh, "preview_material_texture_inputs", ()) or ()
            )
            resolved_count = _resolve_material_input_archive_fallbacks(inputs, submesh, entries_by_basename, target_entry, stop_event, resolved_count)
            texture_name = getattr(submesh, "texture", "")
            material_name = getattr(submesh, "material", "")
            has_exact_material_inputs = any(
                _rust_material_input_exact_basenames(item) for item in inputs
            )
            for role, suffixes, attributes in _RUST_ARCHIVE_TEXTURE_ROLE_CANDIDATES:
                if role == "material" and has_exact_material_inputs:
                    continue
                if _first_resolved_dds_path(submesh, attributes) is not None:
                    continue
                direct_values = tuple(
                    getattr(submesh, attribute, "") for attribute in attributes
                ) + tuple(
                    getattr(submesh, attribute, "")
                    for attribute in _RUST_ARCHIVE_TEXTURE_ROLE_NAME_ATTRIBUTES.get(
                        role,
                        (),
                    )
                )
                direct_candidates = _rust_exact_texture_basenames(*direct_values)
                family_candidates = _rust_role_texture_candidates(
                    texture_name,
                    material_name,
                    suffixes,
                )
                candidates = tuple(
                    dict.fromkeys(direct_candidates + family_candidates)
                )
                for candidate in candidates:
                    if stop_event is not None and stop_event.is_set():
                        raise RustMeshCancellationError(
                            "Mesh texture preparation was cancelled"
                        )
                    matching_entries = _unambiguous_rust_texture_entries(
                        candidate,
                        entries_by_basename.get(candidate.casefold(), ()),
                        target_entry=target_entry
                        if isinstance(target_entry, ArchiveEntry)
                        else None,
                        exact_path_hints=_rust_exact_texture_path_hints(
                            candidate,
                            *direct_values,
                            texture_name,
                            material_name,
                        ),
                    )
                    if not matching_entries:
                        continue
                    try:
                        resolved = _resolve_proven_rust_texture_entry(
                            matching_entries[0],
                            stop_event=stop_event,
                        )
                    except Exception:
                        if stop_event is not None and stop_event.is_set():
                            raise RustMeshCancellationError(
                                "Mesh texture preparation was cancelled"
                            )
                        continue
                    if resolved is None:
                        continue
                    for attribute in attributes:
                        setattr(submesh, attribute, str(resolved))
                    resolved_count += 1
                    break
    return resolved_count


def _material_input_texture_role(value: object) -> str:
    tokens = " ".join(
        str(getattr(value, name, "") or "")
        for name in ("semantic_type", "semantic_subtype", "slot_kind", "parameter_name")
    ).casefold()
    compact = "".join(character for character in tokens if character.isalnum())
    parameter_name = "".join(
        character
        for character in str(getattr(value, "parameter_name", "") or "").casefold()
        if character.isalnum()
    )
    source_kind = "".join(
        character
        for character in str(getattr(value, "source_kind", "") or "").casefold()
        if character.isalnum()
    )
    shader_family = normalize_shader_family(getattr(value, "shader_family", ""))
    if parameter_name == "skindetailmasktexture":
        return "skin_detail_mask"
    if parameter_name == "skindetailnormaltexture":
        return "skin_detail_normal"
    if parameter_name == "skindetailmaterialtexture":
        return "skin_detail_material"
    if parameter_name in {
        "basecolortexture",
        "basetexture",
        "diffusetexture",
        "albedotexture",
        "colortexture",
        "overlaycolortexture",
    }:
        return "base_color"
    if parameter_name in {"normaltexture", "normalmap"}:
        return "normal"
    if parameter_name in {"heighttexture", "displacementtexture"}:
        return "height"
    if parameter_name == "materialtexture":
        if (
            source_kind == "crimsonskinmaterialresponse"
            or shader_family == "skin"
        ):
            # Crimson skin ``*_sp`` stores specular/surface response, with a
            # flat blue channel; treating it as packed metalness makes skin
            # metallic.  Standard/cloth/weapon ``_materialTexture`` remains
            # the packed material response.
            return "specular"
        return "material"
    if parameter_name == "emissiveintensitytexture":
        return "emissive"
    if parameter_name.endswith("masktexture"):
        return "layer_mask"
    if "normal" in compact:
        return "normal"
    if "roughness" in compact:
        return "roughness"
    if "metalness" in compact or "metallic" in compact:
        return "metalness"
    if "occlusion" in compact or "ambientocclusion" in compact:
        return "occlusion"
    if "specular" in compact:
        return "specular"
    if "gloss" in compact:
        return "glossiness"
    if "emissive" in compact:
        return "emissive"
    if "opacity" in compact or "alpha" in compact:
        return "opacity"
    if "height" in compact or "displacement" in compact:
        return "height"
    if "flow" in compact or "direction" in compact:
        return "flow"
    if "detailmask" in compact or "layermask" in compact or "colorblendingmask" in compact:
        return "layer_mask"
    if "material" in compact or "surface" in compact:
        return "material"
    if any(token in compact for token in ("basecolor", "diffuse", "albedo", "colortexture")):
        return "base_color"
    return ""


def _material_input_dds_path(value: object) -> Path | None:
    for attribute in ("source_dds_path", "preview_texture_path", "source_texture_path"):
        path = _resolved_dds_path(
            getattr(value, attribute, ""),
            declared_dds=attribute == "source_dds_path",
        )
        if path is not None:
            return path
    return None


def _material_input_is_exact_owner_binding(source: object, value: object) -> bool:
    """Accept only one PAC material owner's authoritative binding metadata.

    Older import-only rows do not carry owner metadata and retain their local
    single-owner behavior.  Once a row declares PAC binding metadata, both its
    authority and owner slot must prove that it belongs to this source.
    """

    authority = str(getattr(value, "binding_authority", "") or "").strip().casefold()
    try:
        source_owner = int(
            getattr(source, "preview_pac_material_owner_slot_index", -1)
        )
    except (TypeError, ValueError, OverflowError):
        source_owner = -1
    try:
        value_owner = int(getattr(value, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        value_owner = -1

    # A few import-only callers receive a synthesized source owner from the
    # package builder even though their texture rows predate the PAC binding
    # contract.  Treat a row as legacy unless the row itself declares owner or
    # authority metadata *and* the whole input set is legacy.  A blank ownerless
    # diagnostic duplicate must not regain authority beside modern owner-bound
    # PAC rows (for example an undeclared sibling ``*_disp.dds``).
    has_input_contract = value_owner >= 0 or bool(authority)
    if not has_input_contract:
        siblings = tuple(
            getattr(source, "preview_material_texture_inputs", ()) or ()
        )
        return not any(
            _material_input_declares_owner_contract(item) for item in siblings
        )
    if authority not in {"authoritative", "exact"}:
        return False
    if source_owner >= 0:
        return value_owner == source_owner
    return value_owner >= 0


def _material_input_declares_owner_contract(value: object) -> bool:
    authority = str(getattr(value, "binding_authority", "") or "").strip().casefold()
    try:
        owner = int(getattr(value, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        owner = -1
    return bool(authority) or owner >= 0


def _material_input_is_global_declaration_eligible(
    source: object,
    value: object,
) -> bool:
    """Validate the common global-role portion of one material declaration."""

    authority = str(getattr(value, "binding_authority", "") or "").strip().casefold()
    disposition = str(
        getattr(value, "binding_disposition", "") or ""
    ).strip().casefold()
    source_kind = str(getattr(value, "source_kind", "") or "").strip().casefold()
    if not _material_input_is_exact_owner_binding(source, value):
        return False
    if disposition in _RUST_REJECTED_GLOBAL_INPUT_DISPOSITIONS:
        return False
    if authority == "guess":
        return False
    if disposition not in _RUST_GLOBAL_INPUT_DISPOSITIONS:
        return False
    if source_kind.startswith("crimson_layer"):
        return False
    if source_kind in _RUST_REJECTED_GLOBAL_INPUT_SOURCE_KINDS:
        return False
    return True


def _material_input_has_authoritative_role_declaration(
    source: object,
    role: str,
) -> bool:
    """Return whether PAC metadata declares an owner-bound source for ``role``.

    Declaration authority is checked independently of file availability.  A
    missing declared XML DDS must fail closed rather than allowing a diagnostic
    sibling or top-level preview guess to replace it.
    """

    for item in tuple(
        getattr(source, "preview_material_texture_inputs", ()) or ()
    ):
        if _material_input_texture_role(item) != role:
            continue
        authority = str(
            getattr(item, "binding_authority", "") or ""
        ).strip().casefold()
        if authority not in {"authoritative", "exact"}:
            continue
        if _material_input_is_global_declaration_eligible(source, item):
            return True
    return False


def _material_input_matches_direct_base_path(source: object, value: object) -> bool:
    """Retain one old direct-base preview without promoting other guesses.

    A small set of PAC owners expose their visible colour only through the
    submesh's already-resolved top-level preview DDS.  Their accompanying input
    row is diagnostic/guessed metadata rather than an exact XML binding.  It is
    safe only when both references name that exact same local DDS, and only for
    ``base_color``; it must never make a guessed material/height/normal global.
    """

    input_path = _material_input_dds_path(value)
    if input_path is None:
        return False
    base_attributes = next(
        attributes
        for role, attributes in _TEXTURE_RESOURCE_SPECS
        if role == "base_color"
    )
    direct_path = _first_resolved_dds_path(source, base_attributes)
    if direct_path is None or input_path != direct_path:
        return False
    try:
        source_owner = int(
            getattr(source, "preview_pac_material_owner_slot_index", -1)
        )
    except (TypeError, ValueError, OverflowError):
        source_owner = -1
    try:
        value_owner = int(getattr(value, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        value_owner = -1
    return source_owner < 0 or value_owner < 0 or source_owner == value_owner


def _material_input_is_renderer_role_eligible(
    source: object,
    value: object,
    role: str,
) -> bool:
    """Gate raw PAC inputs before they become renderer-global textures."""

    authority = str(getattr(value, "binding_authority", "") or "").strip().casefold()
    disposition = str(
        getattr(value, "binding_disposition", "") or ""
    ).strip().casefold()
    source_kind = str(getattr(value, "source_kind", "") or "").strip().casefold()
    layer_role = str(getattr(value, "layer_role", "") or "").strip().casefold()
    layer_channel = str(
        getattr(value, "layer_channel", "") or ""
    ).strip().casefold()

    if role in _RUST_DEDICATED_MATERIAL_INPUT_ROLES:
        # Layer masks and the three skin-detail resources are deliberately
        # consumed as local support data, never as the global surface map.
        return _material_input_is_exact_owner_binding(source, value)

    parameter_name = "".join(
        character
        for character in str(getattr(value, "parameter_name", "") or "").casefold()
        if character.isalnum()
    )
    if role == "flow":
        # Hair Flow is a renderer input, despite the registry correctly
        # classifying it as layer-local control data.  Publish only the exact
        # PAC owner's canonical ``_flowTexture`` vector; other direction maps,
        # guessed vectors, and channel-addressed layer controls stay rejected.
        return (
            parameter_name == "flowtexture"
            and authority in {"authoritative", "exact"}
            and _rust_input_is_strict_exact_owner_binding(source, value)
            and disposition == "layer_flow"
            and source_kind == "crimson_flow_vector"
            and layer_role in {"", "vector", "flow"}
            and not layer_channel
        )

    if (
        role in {"material", "specular"}
        and parameter_name == "materialtexture"
        and authority in {"authoritative", "exact"}
        and _material_input_is_exact_owner_binding(source, value)
        and disposition
        in {"", "direct", "layer_material_response", "promoted", "recorded"}
        and source_kind in _RUST_PRIMARY_MATERIAL_SOURCE_KINDS
        and layer_role in {"", "material_response"}
        and not layer_channel
    ):
        # The unsuffixed PAC XML _materialTexture is the owner's complete
        # surface response for cloth/leather/equipment (and the packed skin SP
        # map).  Registry disposition calls it a material response, but it is
        # not a subordinate grime/detail/damage layer.
        return True

    if (
        role == "base_color"
        and authority in {"", "guess"}
        and disposition in {"", "diagnostic_only"}
        and not _material_input_has_authoritative_role_declaration(
            source,
            "base_color",
        )
        and _material_input_matches_direct_base_path(source, value)
    ):
        return True

    return _material_input_is_global_declaration_eligible(source, value)


def _first_texture_resource_dds_path(
    source: object,
    role: str,
    attributes: Sequence[str],
) -> Path | None:
    """Resolve one publisher-trusted DDS while preserving binding precedence."""

    material_inputs = tuple(
        getattr(source, "preview_material_texture_inputs", ()) or ()
    )
    declared_role_inputs = tuple(
        item
        for item in material_inputs
        if _material_input_texture_role(item) == role
    )
    exact_role_inputs = tuple(
        item
        for item in declared_role_inputs
        if _material_input_is_renderer_role_eligible(source, item, role)
    )
    if exact_role_inputs:
        paths = {
            path
            for item in exact_role_inputs
            if (path := _material_input_dds_path(item)) is not None
        }
        # A single same-owner role is safe to publish directly.  Missing or
        # conflicting files fail closed so the conserved material compositor
        # can supply the renderer-ready result instead.
        return next(iter(paths)) if len(paths) == 1 else None

    if declared_role_inputs:
        # A role was explicitly present but none of its rows passed the global
        # authority gate.  Never resurrect a rejected guess/layer map through a
        # flattened top-level preview attribute.
        return None

    has_exact_owner_contract = bool(material_inputs) and any(
        _material_input_declares_owner_contract(item)
        for item in material_inputs
    )
    if has_exact_owner_contract or (role == "material" and material_inputs):
        # PAC XML inputs are authoritative.  A flattened top-level selector,
        # layer mask, or family guess cannot invent a different texture role.
        return None
    path = _first_resolved_dds_path(source, attributes)
    if path is not None:
        return path
    for item in material_inputs:
        if _material_input_texture_role(item) != role:
            continue
        path = _material_input_dds_path(item)
        if path is not None:
            return path
    return None


def _raise_if_texture_copy_cancelled(
    stop_event: threading.Event | None,
) -> None:
    if stop_event is not None and stop_event.is_set():
        raise RustMeshCancellationError("Mesh texture preparation was cancelled")


def _bounded_luminance_image(path: Path, stop_event: threading.Event | None):
    """Load one bounded RGBA image without trusting mutable compiler output."""

    from PIL import Image

    _raise_if_texture_copy_cancelled(stop_event)
    before = path.stat()
    if before.st_size <= 0 or before.st_size > _GENERATED_MAX_FILE_BYTES:
        raise ValueError("material luminance image is outside the 64 MiB limit")
    before_identity = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_size),
        int(before.st_mtime_ns),
    )
    with Image.open(path) as source_image:
        width = int(source_image.width)
        height = int(source_image.height)
        if (
            width <= 0
            or height <= 0
            or width > _RUST_MATERIAL_LUMINANCE_GUARD_MAX_IMAGE_DIMENSION
            or height > _RUST_MATERIAL_LUMINANCE_GUARD_MAX_IMAGE_DIMENSION
            or width * height > _RUST_MATERIAL_LUMINANCE_GUARD_MAX_IMAGE_PIXELS
        ):
            raise ValueError("material luminance image dimensions are outside the limit")
        image = source_image.convert("RGBA")
        image.load()
    after = path.stat()
    after_identity = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_size),
        int(after.st_mtime_ns),
    )
    if after_identity != before_identity:
        raise ValueError("material luminance image changed while it was read")
    _raise_if_texture_copy_cancelled(stop_event)
    return image


def _sampled_alpha_weighted_mean_luma(image, stop_event: threading.Event | None) -> float | None:
    """Return bounded sRGB preview luma while ignoring transparent padding."""

    from PIL import Image

    sampled = image.copy()
    sampled.thumbnail(
        (
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
        ),
        resample=Image.Resampling.BOX,
    )
    _raise_if_texture_copy_cancelled(stop_event)
    weighted_luma = 0.0
    alpha_total = 0.0
    pixel_data = (
        sampled.get_flattened_data()
        if hasattr(sampled, "get_flattened_data")
        else sampled.getdata()
    )
    for red, green, blue, alpha in pixel_data:
        alpha_weight = float(alpha) / 255.0
        alpha_total += alpha_weight
        weighted_luma += alpha_weight * (
            0.2126 * (float(red) / 255.0)
            + 0.7152 * (float(green) / 255.0)
            + 0.0722 * (float(blue) / 255.0)
        )
    _raise_if_texture_copy_cancelled(stop_event)
    if alpha_total <= 0.0:
        return None
    return max(0.0, min(1.0, weighted_luma / alpha_total))


def _sampled_rgb_mean_luma(image, stop_event: threading.Event | None) -> float | None:
    """Return bounded sRGB luma for an opaque presentation, ignoring base alpha."""

    from PIL import Image

    sampled = image.convert("RGB")
    sampled.thumbnail(
        (
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
        ),
        resample=Image.Resampling.BOX,
    )
    _raise_if_texture_copy_cancelled(stop_event)
    pixel_data = (
        sampled.get_flattened_data()
        if hasattr(sampled, "get_flattened_data")
        else sampled.getdata()
    )
    total_luma = 0.0
    pixel_count = 0
    for red, green, blue in pixel_data:
        pixel_count += 1
        total_luma += (
            0.2126 * (float(red) / 255.0)
            + 0.7152 * (float(green) / 255.0)
            + 0.0722 * (float(blue) / 255.0)
        )
    _raise_if_texture_copy_cancelled(stop_event)
    if pixel_count <= 0:
        return None
    return max(0.0, min(1.0, total_luma / float(pixel_count)))


def _deterministic_luminance_face_indices(face_count: int) -> tuple[int, ...]:
    count = max(0, int(face_count))
    limit = _RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_FACES
    if count <= limit:
        return tuple(range(count))
    if limit <= 1:
        return (0,)
    return tuple(
        (sample_index * (count - 1)) // (limit - 1)
        for sample_index in range(limit)
    )


def _rust_surface_uv_luminance_samples(
    submesh: object,
    stop_event: threading.Event | None,
) -> tuple[tuple[float, float, float], ...]:
    """Build bounded, deterministic area-weighted UV0 samples for one surface."""

    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    uvs = tuple(getattr(submesh, "uvs", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    if not vertices or len(uvs) != len(vertices) or not faces:
        return ()
    barycentric_points = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.5, 0.0),
        (0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5),
        (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    )
    samples: list[tuple[float, float, float]] = []
    for ordinal, face_index in enumerate(
        _deterministic_luminance_face_indices(len(faces))
    ):
        if ordinal % 128 == 0:
            _raise_if_texture_copy_cancelled(stop_event)
        face = faces[face_index]
        if not isinstance(face, Sequence) or isinstance(face, (str, bytes)):
            continue
        if len(face) != 3:
            continue
        try:
            indices = tuple(int(value) for value in face)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            len(set(indices)) != 3
            or min(indices) < 0
            or max(indices) >= len(vertices)
        ):
            continue
        try:
            positions = tuple(
                tuple(float(component) for component in vertices[index][:3])
                for index in indices
            )
            triangle_uvs = tuple(
                tuple(float(component) for component in uvs[index][:2])
                for index in indices
            )
        except (TypeError, ValueError, OverflowError, IndexError):
            continue
        if any(
            len(row) != width or not all(math.isfinite(value) for value in row)
            for rows, width in ((positions, 3), (triangle_uvs, 2))
            for row in rows
        ):
            continue
        edge_a = tuple(positions[1][axis] - positions[0][axis] for axis in range(3))
        edge_b = tuple(positions[2][axis] - positions[0][axis] for axis in range(3))
        cross = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        area = 0.5 * math.sqrt(sum(component * component for component in cross))
        if not math.isfinite(area) or area <= 1.0e-20:
            continue
        sample_weight = area / float(len(barycentric_points))
        for weight_a, weight_b, weight_c in barycentric_points:
            samples.append(
                (
                    triangle_uvs[0][0] * weight_a
                    + triangle_uvs[1][0] * weight_b
                    + triangle_uvs[2][0] * weight_c,
                    triangle_uvs[0][1] * weight_a
                    + triangle_uvs[1][1] * weight_b
                    + triangle_uvs[2][1] * weight_c,
                    sample_weight,
                )
            )
        if len(samples) >= _RUST_MATERIAL_LUMINANCE_GUARD_MAX_SURFACE_SAMPLES:
            break
    _raise_if_texture_copy_cancelled(stop_event)
    if not samples:
        return ()
    total_weight = sum(sample[2] for sample in samples)
    if not math.isfinite(total_weight) or total_weight <= 0.0:
        return ()
    return tuple((u, v, weight / total_weight) for u, v, weight in samples)


def _repeat_linear_rgba_sample(
    pixels: object,
    width: int,
    height: int,
    u: float,
    v: float,
) -> tuple[float, float, float, float]:
    wrapped_u = u - math.floor(u)
    wrapped_v = v - math.floor(v)
    x = wrapped_u * float(width) - 0.5
    y = wrapped_v * float(height) - 0.5
    x0 = math.floor(x)
    y0 = math.floor(y)
    fraction_x = x - float(x0)
    fraction_y = y - float(y0)
    x_indices = (x0 % width, (x0 + 1) % width)
    y_indices = (y0 % height, (y0 + 1) % height)
    rows = (
        pixels[x_indices[0], y_indices[0]],
        pixels[x_indices[1], y_indices[0]],
        pixels[x_indices[0], y_indices[1]],
        pixels[x_indices[1], y_indices[1]],
    )
    weights = (
        (1.0 - fraction_x) * (1.0 - fraction_y),
        fraction_x * (1.0 - fraction_y),
        (1.0 - fraction_x) * fraction_y,
        fraction_x * fraction_y,
    )
    return tuple(
        sum(float(row[channel]) * weights[index] for index, row in enumerate(rows))
        for channel in range(4)
    )


def _sampled_surface_uv_mean_luma(
    image,
    samples: Sequence[tuple[float, float, float]],
    *,
    alpha_mode: str,
    stop_event: threading.Event | None,
) -> float | None:
    rgba = image.convert("RGBA")
    width, height = int(rgba.width), int(rgba.height)
    if width <= 0 or height <= 0:
        return None
    pixels = rgba.load()
    opaque = str(alpha_mode or "").strip().casefold() == "opaque"
    weighted_luma = 0.0
    total_weight = 0.0
    for sample_index, (u, v, surface_weight) in enumerate(samples):
        if sample_index % 256 == 0:
            _raise_if_texture_copy_cancelled(stop_event)
        red, green, blue, alpha = _repeat_linear_rgba_sample(
            pixels,
            width,
            height,
            float(u),
            float(v),
        )
        alpha_weight = 1.0 if opaque else max(0.0, min(1.0, alpha / 255.0))
        weight = max(0.0, float(surface_weight)) * alpha_weight
        total_weight += weight
        weighted_luma += weight * (
            0.2126 * (red / 255.0)
            + 0.7152 * (green / 255.0)
            + 0.0722 * (blue / 255.0)
        )
    _raise_if_texture_copy_cancelled(stop_event)
    if total_weight <= 0.0 or not math.isfinite(total_weight):
        return None
    result = weighted_luma / total_weight
    if not math.isfinite(result):
        return None
    return max(0.0, min(1.0, result))


def _whole_image_luminance_sample_count(image, *, opaque: bool) -> int:
    from PIL import Image

    sampled = image.convert("RGB") if opaque else image.copy()
    sampled.thumbnail(
        (
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
            _RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
        ),
        resample=Image.Resampling.BOX,
    )
    return max(0, int(sampled.width) * int(sampled.height))


def _guard_generated_base_luminance(
    generated_source: Path,
    direct_preview: Path,
    guarded_target: Path,
    *,
    alpha_mode: str,
    surface_uv_samples: Sequence[tuple[float, float, float]] = (),
    owned_root: Path,
    expected_root_identity: tuple[int, int],
    stop_event: threading.Event | None,
) -> dict[str, float] | None:
    """Cap a brighter synthesized base against its valid direct-base preview."""

    from PIL import Image

    _session_root_identity(owned_root, expected_root_identity)
    resolved_root = owned_root.resolve(strict=True)
    for source in (generated_source, direct_preview):
        _require_owned_path(source, resolved_root)
    generated_image = _bounded_luminance_image(generated_source, stop_event)
    direct_image = _bounded_luminance_image(direct_preview, stop_event)
    opaque = str(alpha_mode or "").strip().casefold() == "opaque"
    if surface_uv_samples:
        sampling_basis = "surface_uv0_repeat_linear"
        sample_count = len(surface_uv_samples)
        generated_mean = _sampled_surface_uv_mean_luma(
            generated_image,
            surface_uv_samples,
            alpha_mode=alpha_mode,
            stop_event=stop_event,
        )
        direct_mean = _sampled_surface_uv_mean_luma(
            direct_image,
            surface_uv_samples,
            alpha_mode=alpha_mode,
            stop_event=stop_event,
        )
    else:
        sampling_basis = (
            "whole_image_rgb_opaque"
            if opaque
            else "whole_image_alpha_weighted"
        )
        mean_luma = (
            _sampled_rgb_mean_luma
            if opaque
            else _sampled_alpha_weighted_mean_luma
        )
        generated_mean = mean_luma(generated_image, stop_event)
        direct_mean = mean_luma(direct_image, stop_event)
        sample_count = _whole_image_luminance_sample_count(
            generated_image,
            opaque=opaque,
        )
    if generated_mean is None or direct_mean is None or generated_mean <= 0.0:
        return None
    cap = min(
        1.0,
        max(
            direct_mean * _RUST_MATERIAL_LUMINANCE_GUARD_MAX_MULTIPLIER,
            direct_mean + _RUST_MATERIAL_LUMINANCE_GUARD_MAX_ABSOLUTE_INCREASE,
        ),
    )
    if generated_mean <= cap + (1.0 / 255.0):
        return None

    rgb_scale = max(0.0, min(1.0, cap / generated_mean))
    red, green, blue, alpha = generated_image.split()
    scale_table = tuple(
        max(0, min(255, int(round(value * rgb_scale)))) for value in range(256)
    )
    guarded = Image.merge(
        "RGBA",
        (
            red.point(scale_table),
            green.point(scale_table),
            blue.point(scale_table),
            alpha,
        ),
    )
    _raise_if_texture_copy_cancelled(stop_event)
    guarded_target.parent.mkdir(parents=True, exist_ok=True)
    _require_owned_path(guarded_target.parent, resolved_root)
    staged = guarded_target.with_name(f".{guarded_target.name}.{uuid4().hex}.tmp")
    try:
        guarded.save(staged, format="PNG", optimize=False)
        _require_owned_path(staged, resolved_root)
        staged_size = staged.stat().st_size
        if staged_size <= 0 or staged_size > _GENERATED_MAX_FILE_BYTES:
            raise ValueError("guarded material image is outside the 64 MiB limit")
        _raise_if_texture_copy_cancelled(stop_event)
        os.replace(staged, guarded_target)
        _require_owned_path(guarded_target, resolved_root)
    finally:
        staged.unlink(missing_ok=True)
    _session_root_identity(owned_root, expected_root_identity)
    return {
        "direct_mean_luma": direct_mean,
        "generated_mean_luma": generated_mean,
        "capped_mean_luma": cap,
        "rgb_scale": rgb_scale,
        "sampling_basis": sampling_basis,
        "sample_count": sample_count,
    }


def _guard_synthesized_base_against_direct(
    generated_source: Path,
    direct_dds: Path,
    synthesis_root: Path,
    *,
    alpha_mode: str,
    owner_submesh: object,
    lod_index: int,
    submesh_index: int,
    expected_root_identity: tuple[int, int],
    stop_event: threading.Event | None,
) -> tuple[Path, dict[str, float] | None]:
    """Fail-soft preview guard; cancellation remains an authoritative abort."""

    from cdmw.core.texture_native import decode_dds_preview_with_directxtex

    try:
        _session_root_identity(synthesis_root, expected_root_identity)
        resolved_root = synthesis_root.resolve(strict=True)
        _require_owned_path(generated_source, resolved_root)
        generated_size = generated_source.stat().st_size
        direct_dds = direct_dds.resolve(strict=True)
        direct_stat = direct_dds.stat()
        if (
            generated_size <= 0
            or generated_size > _GENERATED_MAX_FILE_BYTES
            or direct_stat.st_size <= 0
            or direct_stat.st_size > _TEXTURE_MAX_FILE_BYTES
            or direct_dds.is_symlink()
            or _is_reparse_point(direct_dds)
        ):
            return generated_source, None
        direct_identity = (
            int(direct_stat.st_dev),
            int(direct_stat.st_ino),
            int(direct_stat.st_size),
            int(direct_stat.st_mtime_ns),
        )
        guard_dir = synthesis_root / "luminance-guard"
        guard_dir.mkdir(exist_ok=True)
        _require_owned_path(guard_dir, resolved_root)
        stem = f"lod-{lod_index:04d}-material-{submesh_index:04d}"
        direct_preview = guard_dir / f"{stem}-direct.png"
        guarded_target = guard_dir / f"{stem}-guarded.png"
        _raise_if_texture_copy_cancelled(stop_event)
        report = decode_dds_preview_with_directxtex(
            direct_dds,
            direct_preview,
            max_dimension=_RUST_MATERIAL_LUMINANCE_GUARD_SAMPLE_DIMENSION,
            slot_kind="base",
            requested_mip=0,
            output_pixel_type="rgba8",
            timeout_seconds=60.0,
            temp_root=synthesis_root,
            stop_event=stop_event,
        )
        if not report or not direct_preview.is_file():
            return generated_source, None
        _require_owned_path(direct_preview, resolved_root)
        after = direct_dds.stat()
        if (
            int(after.st_dev),
            int(after.st_ino),
            int(after.st_size),
            int(after.st_mtime_ns),
        ) != direct_identity:
            return generated_source, None
        metrics = _guard_generated_base_luminance(
            generated_source,
            direct_preview,
            guarded_target,
            alpha_mode=alpha_mode,
            surface_uv_samples=_rust_surface_uv_luminance_samples(
                owner_submesh,
                stop_event,
            ),
            owned_root=synthesis_root,
            expected_root_identity=expected_root_identity,
            stop_event=stop_event,
        )
        return (guarded_target, metrics) if metrics is not None else (generated_source, None)
    except RunCancelled as exc:
        raise RustMeshCancellationError(
            "Mesh texture preparation was cancelled"
        ) from exc
    except RustMeshCancellationError:
        raise
    except Exception:
        # The direct/generated DDS remains the authoritative fallback when this
        # conservative preview-only comparison cannot be completed.
        return generated_source, None


def _atomic_copy_texture_payload(
    root: Path,
    source: Path,
    file_index: int,
    *,
    expected_root_identity: tuple[int, int],
    aggregate_bytes_before: int = 0,
    stop_event: threading.Event | None = None,
) -> dict[str, object]:
    _session_root_identity(root, expected_root_identity)
    _raise_if_texture_copy_cancelled(stop_event)
    try:
        source_size = source.stat().st_size
    except OSError as exc:
        raise RustMeshProtocolError(
            f"Mesh could not inspect resolved texture {source.name}: {exc}"
        ) from exc
    if source_size <= 0 or source_size > _TEXTURE_MAX_FILE_BYTES:
        raise RustMeshProtocolError(
            f"Mesh texture payload is outside the 512 MiB file limit: {source.name}"
        )
    aggregate_bytes_before = max(0, int(aggregate_bytes_before))
    if aggregate_bytes_before + source_size > _SESSION_MAX_TOTAL_BYTES:
        raise RustMeshProtocolError(
            "Mesh texture payload exceeds the 768 MiB aggregate limit"
        )
    _raise_if_texture_copy_cancelled(stop_event)
    temporary = root / f".texture-{file_index:04d}-{uuid4().hex}.tmp"
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            source_before = os.fstat(input_stream.fileno())
            while True:
                _raise_if_texture_copy_cancelled(stop_event)
                chunk = input_stream.read(1024 * 1024)
                if not chunk:
                    break
                _raise_if_texture_copy_cancelled(stop_event)
                next_byte_length = byte_length + len(chunk)
                if next_byte_length > _TEXTURE_MAX_FILE_BYTES:
                    raise RustMeshProtocolError(
                        f"Mesh texture payload exceeds 512 MiB: {source.name}"
                    )
                if (
                    aggregate_bytes_before + next_byte_length
                    > _SESSION_MAX_TOTAL_BYTES
                ):
                    raise RustMeshProtocolError(
                        "Mesh texture payload exceeds the 768 MiB aggregate limit"
                    )
                digest.update(chunk)
                output_stream.write(chunk)
                byte_length = next_byte_length
            source_after = os.fstat(input_stream.fileno())
        source_identity_before = (
            int(source_before.st_dev),
            int(source_before.st_ino),
            int(source_before.st_size),
            int(source_before.st_mtime_ns),
        )
        source_identity_after = (
            int(source_after.st_dev),
            int(source_after.st_ino),
            int(source_after.st_size),
            int(source_after.st_mtime_ns),
        )
        if source_identity_before != source_identity_after or byte_length != source_after.st_size:
            raise RustMeshProtocolError(
                f"Mesh texture changed while it was being packaged: {source.name}"
            )
        sha256 = digest.hexdigest().upper()
        name = f"texture-{file_index:04d}-{sha256[:12].lower()}.dds"
        destination = root / name
        _raise_if_texture_copy_cancelled(stop_event)
        _session_root_identity(root, expected_root_identity)
        os.replace(temporary, destination)
        return {
            "path": name,
            "data_type": "dds_texture",
            "count": 1,
            "byte_length": byte_length,
            "sha256": sha256,
            "content_type": "image/vnd-ms.dds",
        }
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _submesh_has_material_synthesis_inputs(submesh: object) -> bool:
    # Scene importers already bind these images to renderer roles. Their input
    # provenance survives composition with PAC references and placement helpers;
    # the combined mesh's format describes only its first role.
    for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
        confidence = str(getattr(texture_input, "confidence", "") or "").strip().casefold()
        if (
            confidence not in {"gltf", "obj_mtl", "dae", "filename", "scene"}
            or getattr(texture_input, "owner_slot_index", -1) != -1
            or getattr(texture_input, "binding_authority", "")
            or getattr(texture_input, "sidecar_path", "")
        ):
            return True
    return False


def _mesh_has_material_synthesis_inputs(mesh: ParsedMesh) -> bool:
    return any(
        _submesh_has_material_synthesis_inputs(submesh)
        for level in _mesh_lods(mesh)
        for submesh in level
    )


def rust_preview_mesh_needs_material_synthesis(mesh: ParsedMesh) -> bool:
    """Whether a full tier can add anything beyond the direct texture tier."""

    return _mesh_has_material_synthesis_inputs(mesh)


def _validate_rust_material_synthesis_tree(
    root: Path,
    expected_root_identity: tuple[int, int],
) -> None:
    """Bound the compiler's disposable output before any file is packaged."""

    _session_root_identity(root, expected_root_identity)
    owned_root = root.resolve(strict=True)
    stack: list[tuple[Path, int]] = [(root, 0)]
    entry_count = 0
    total_bytes = 0
    while stack:
        directory, depth = stack.pop()
        for item in directory.iterdir():
            entry_count += 1
            if entry_count > _SESSION_MAX_ENTRIES:
                raise RustMeshProtocolError(
                    "Mesh material synthesis contains too many entries"
                )
            _require_owned_path(item, owned_root)
            if item.is_dir():
                if depth >= _GENERATED_MAX_DEPTH:
                    raise RustMeshProtocolError(
                        "Mesh material synthesis exceeds the directory-depth limit"
                    )
                stack.append((item, depth + 1))
                continue
            if not item.is_file():
                raise RustMeshProtocolError(
                    "Mesh material synthesis contains an unexpected entry"
                )
            length = item.stat().st_size
            if length <= 0 or length > _TEXTURE_MAX_FILE_BYTES:
                raise RustMeshProtocolError(
                    "Mesh material synthesis contains a file outside the 512 MiB limit"
                )
            total_bytes += length
            if total_bytes > _SESSION_MAX_TOTAL_BYTES:
                raise RustMeshProtocolError(
                    "Mesh material synthesis exceeds the 768 MiB aggregate limit"
                )
    _session_root_identity(root, expected_root_identity)


def _rust_exact_direct_fallback_overrides(
    row: Mapping[str, object],
    source_submesh: object,
    *,
    lod_index: int,
    submesh_index: int,
    protected_keys: frozenset[tuple[int, int, str]],
    applied_roles: set[str],
) -> dict[tuple[int, int, str], Path]:
    """Fill only a missing compositor group from exact owner-bound DDS rows."""

    entries_value = row.get("direct_fallback_channels", {})
    if not isinstance(entries_value, Mapping) or len(entries_value) > 8:
        return {}
    entries = {
        str(role or "").strip().casefold(): entry
        for role, entry in entries_value.items()
        if isinstance(entry, Mapping)
    }
    if not entries:
        return {}

    def owner_index(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return -1

    try:
        source_owner = int(
            getattr(source_submesh, "preview_pac_material_owner_slot_index", -1)
        )
    except (TypeError, ValueError, OverflowError):
        source_owner = -1
    entry_owners = {
        owner
        for entry in entries.values()
        if (owner := owner_index(entry.get("owner_slot_index", -1))) >= 0
    }
    if source_owner >= 0:
        effective_owner = source_owner
    elif len(entry_owners) == 1:
        effective_owner = next(iter(entry_owners))
    else:
        return {}

    packed_surface_output_present = bool(
        applied_roles & _RUST_CONSERVED_PACKED_SURFACE_OUTPUT_ROLES
    )
    source_inputs = tuple(
        getattr(source_submesh, "preview_material_texture_inputs", ()) or ()
    )
    overrides: dict[tuple[int, int, str], Path] = {}
    for role in ("base_color", "normal", "material", "height"):
        entry = entries.get(role)
        if entry is None:
            continue
        override_key = (lod_index, submesh_index, role)
        if override_key in protected_keys:
            continue
        if role in {"base_color", "normal", "height"} and role in applied_roles:
            continue
        if role == "material" and packed_surface_output_present:
            continue
        if owner_index(entry.get("owner_slot_index", -1)) != effective_owner:
            continue
        authority = str(
            entry.get("binding_authority", "") or ""
        ).strip().casefold()
        if authority not in {"authoritative", "exact"}:
            continue
        disposition = str(
            entry.get("binding_disposition", "") or ""
        ).strip().casefold()
        if disposition not in _RUST_DIRECT_FALLBACK_DISPOSITIONS:
            continue
        parameter_key = "".join(
            character
            for character in str(entry.get("parameter_name", "") or "").casefold()
            if character.isalnum()
        )
        if parameter_key not in _RUST_DIRECT_FALLBACK_PARAMETER_KEYS[role]:
            continue
        semantic = str(entry.get("semantic", "") or "").strip().casefold()
        if semantic not in _RUST_DIRECT_FALLBACK_SEMANTICS[role]:
            continue
        direct_path = _resolved_dds_path(entry.get("path", ""), declared_dds=True)
        if direct_path is None:
            continue

        # Revalidate compiler metadata against the immutable source snapshot.
        # This prevents a malformed row from promoting a layer or another PAC
        # wrapper's texture merely because it points at a readable DDS.
        exact_source_match = False
        for source_input in source_inputs:
            source_parameter_key = "".join(
                character
                for character in str(
                    getattr(source_input, "parameter_name", "") or ""
                ).casefold()
                if character.isalnum()
            )
            if source_parameter_key != parameter_key:
                continue
            if _material_input_texture_role(source_input) != role:
                continue
            try:
                input_owner = int(getattr(source_input, "owner_slot_index", -1))
            except (TypeError, ValueError, OverflowError):
                input_owner = -1
            input_authority = str(
                getattr(source_input, "binding_authority", "") or ""
            ).strip().casefold()
            if input_owner != effective_owner or input_authority not in {
                "authoritative",
                "exact",
            }:
                continue
            if _material_input_dds_path(source_input) == direct_path:
                exact_source_match = True
                break
        if not exact_source_match:
            continue
        overrides[override_key] = direct_path
    return overrides


def _encode_generated_material_channel(
    source, role, encode_channel, synthesis_root, lod_index, submesh_index, cancellation_event,
    synthesis_state, encoded_cache, cache_key,
):
    encoded_dir = synthesis_root / "encoded"
    encoded_dir.mkdir(exist_ok=True)
    encoded = encoded_dir / (
        f"lod-{lod_index:04d}-material-{submesh_index:04d}-{encode_channel}.dds"
    )
    try:
        encode_options = {}
        if role == "base_color" and source.suffix.casefold() == ".png":
            encode_options = {"source_color_policy": "assume_srgb"}
        elif role in _RUST_SYNTHESIZED_SCALAR_ROLES:
            encode_options = {
                "source_color_policy": "ignore_srgb_metadata"
            }
        _encode_rust_preview_dds(
            source,
            encoded,
            encode_channel,
            cancellation_event,
            synthesis_state,
            **encode_options,
        )
    except RunCancelled as exc:
        raise RustMeshCancellationError(
            "Mesh texture preparation was cancelled"
        ) from exc
    except Exception as exc:
        # Retain the direct DDS for this owner/channel when the
        # authoritative generated image cannot be encoded.
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "generated_channel_encode_failed",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail=f"{encode_channel}: {type(exc).__name__}: {exc}",
        )
        return None
    encoded_cache[cache_key] = encoded
    return encoded


def _apply_synthesized_material_roles(
    lod_index, submesh_index, submeshes, protected_keys, skin_surface_contract, generated_channels,
    resolved_channels, layered_normal_is_authoritative, runtime_skin_detail, synthesis_root, synthesis_state,
    base_alpha_mode, expected_root_identity, stop_event, encoded_cache, cancellation_event, overrides,
    applied_roles,
):
    for role, channel_candidates, encode_channel in _RUST_SYNTHESIZED_TEXTURE_ROLES:
        override_key = (lod_index, submesh_index, role)
        if override_key in protected_keys:
            continue
        if role in _RUST_SYNTHESIZED_SCALAR_ROLES and skin_surface_contract:
            # SkinnedMeshSkin `_sp` is not an equipment surface map:
            # R is subsurface response, G is direct roughness, and B is
            # not metalness.  Keep the exact owner-bound packed DDS for
            # Rust's dedicated skin path rather than replacing it with
            # compiler-derived single-channel approximations.
            continue
        if (
            role in _RUST_PACKED_SURFACE_COMPONENT_ROLES
            and (lod_index, submesh_index, "material") in protected_keys
        ):
            # The shared material combiner already supplied exact packed G/B
            # roughness/metalness for this owner.  Separate maps would
            # override those baked channels in the Rust shader.
            continue
        source_channel = next(
            (
                channel
                for channel in channel_candidates
                if channel in generated_channels
                and str(resolved_channels.get(channel, "") or "").strip()
            ),
            "",
        )
        direct_attributes = next(
            (
                attributes
                for direct_role, attributes in _TEXTURE_RESOURCE_SPECS
                if direct_role == role
            ),
            (),
        )
        direct_path = (
            _first_texture_resource_dds_path(
                submeshes[submesh_index],
                role,
                direct_attributes,
            )
            if direct_attributes
            else None
        )
        generated_is_renderer_ready = bool(
            source_channel
            and (
                role
                in {
                    "base_color",
                    "roughness",
                    "metalness",
                    "occlusion",
                    "specular",
                    "height",
                    "emissive",
                }
                or (
                    role == "normal"
                    and layered_normal_is_authoritative
                    and not runtime_skin_detail
                )
            )
        )
        if direct_path is not None and not generated_is_renderer_ready:
            # A conserved generated base/surface/emissive/height channel
            # is the complete PAC material result and therefore outranks
            # any individual dye, overlay, mask, or source-map ingredient.
            # Normal only wins when the compiler explicitly proves it
            # combined authored normal layers; runtime skin detail stays
            # separate for Rust's dedicated skin path.
            continue
        if not source_channel:
            continue
        source = Path(
            str(resolved_channels.get(source_channel, "") or "")
        )
        try:
            source = source.resolve(strict=True)
        except OSError:
            _record_rust_material_synthesis_diagnostic(
                synthesis_state,
                "generated_channel_missing",
                lod_index=lod_index,
                submesh_index=submesh_index,
                detail=source_channel,
            )
            continue
        if source != synthesis_root and synthesis_root not in source.parents:
            _record_rust_material_synthesis_diagnostic(
                synthesis_state,
                "generated_channel_outside_owned_root",
                lod_index=lod_index,
                submesh_index=submesh_index,
                detail=source_channel,
            )
            continue
        luminance_guard_metrics: dict[str, float] | None = None
        if role == "base_color":
            direct_base = _first_texture_resource_dds_path(
                submeshes[submesh_index],
                role,
                _TEXTURE_RESOURCE_SPECS[0][1],
            )
            if direct_base is not None:
                source, luminance_guard_metrics = (
                    _guard_synthesized_base_against_direct(
                        source,
                        direct_base,
                        synthesis_root,
                        alpha_mode=base_alpha_mode,
                        owner_submesh=submeshes[submesh_index],
                        lod_index=lod_index,
                        submesh_index=submesh_index,
                        expected_root_identity=expected_root_identity,
                        stop_event=stop_event,
                    )
                )
        cache_key = (str(source), encode_channel)
        encoded = encoded_cache.get(cache_key)
        if encoded is None:
            encoded = _encode_generated_material_channel(
                source, role, encode_channel, synthesis_root, lod_index, submesh_index, cancellation_event,
                synthesis_state, encoded_cache, cache_key,
            )
            if encoded is None:
                continue
        if override_key not in overrides:
            synthesis_state.generated_binding_count += 1
        overrides[override_key] = encoded
        applied_roles.add(role)
        if luminance_guard_metrics is not None:
            _record_rust_material_luminance_guard(
                synthesis_state,
                lod_index=lod_index,
                submesh_index=submesh_index,
                **luminance_guard_metrics,
            )


def _validated_synthesized_material_row(row, lod_index, submesh_index, submeshes, synthesis_state, protected_keys, overrides):
    if not isinstance(row, Mapping):
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_manifest_invalid",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail="canonical material compiler returned an invalid submesh row",
        )
        _clear_rust_material_synthesis_results(synthesis_state)
        return {}
    synthesis = row.get("material_synthesis", {})
    resolved_channels = row.get("resolved_channels", {})
    if not isinstance(synthesis, Mapping) or not isinstance(
        resolved_channels,
        Mapping,
    ):
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_manifest_invalid",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail="canonical material compiler returned invalid channel metadata",
        )
        _clear_rust_material_synthesis_results(synthesis_state)
        return {}
    generated_value = synthesis.get("generated_channels", ())
    if not isinstance(generated_value, Sequence) or isinstance(
        generated_value,
        (str, bytes),
    ):
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_manifest_invalid",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail="canonical material compiler returned an invalid generated-channel list",
        )
        _clear_rust_material_synthesis_results(synthesis_state)
        return {}
    generated_channels = {
        str(value or "").strip().casefold()
        for value in generated_value
        if str(value or "").strip()
    }
    synthesis_notes_value = synthesis.get("notes", ())
    synthesis_notes = (
        {
            str(value or "").strip().casefold()
            for value in synthesis_notes_value
            if str(value or "").strip()
        }
        if isinstance(synthesis_notes_value, Sequence)
        and not isinstance(synthesis_notes_value, (str, bytes))
        else set()
    )
    layered_normal_is_authoritative = any(
        note.startswith("normal layers synthesized:")
        for note in synthesis_notes
    )
    source_submesh = submeshes[submesh_index]
    runtime_skin_detail = _rust_has_available_runtime_skin_detail(
        source_submesh
    )
    skin_surface_contract = (
        normalize_shader_family(row.get("shader_family", "")) == "skin"
        or _rust_has_exact_skin_category_evidence(
            source_submesh,
            "skin",
        )
    )
    if len(generated_channels) > 32:
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_manifest_invalid",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail="canonical material compiler exceeded the generated-channel limit",
        )
        _clear_rust_material_synthesis_results(synthesis_state)
        return {}
    conservation = row.get("binding_conservation", {})
    cross_owner_bindings = (
        conservation.get("cross_owner_bindings", ())
        if isinstance(conservation, Mapping)
        else ()
    )
    layer_as_base_bindings = (
        conservation.get("layer_as_base_bindings", ())
        if isinstance(conservation, Mapping)
        else ()
    )
    owner_bindings_conserved = bool(
        isinstance(conservation, Mapping)
        and conservation.get("conserved") is True
        and isinstance(cross_owner_bindings, Sequence)
        and not isinstance(cross_owner_bindings, (str, bytes, bytearray))
        and not cross_owner_bindings
        and isinstance(layer_as_base_bindings, Sequence)
        and not isinstance(layer_as_base_bindings, (str, bytes, bytearray))
        and not layer_as_base_bindings
    )
    if generated_channels and not owner_bindings_conserved:
        direct_fallbacks = _rust_exact_direct_fallback_overrides(
            row,
            source_submesh,
            lod_index=lod_index,
            submesh_index=submesh_index,
            protected_keys=protected_keys,
            applied_roles=set(),
        )
        for override_key, direct_path in direct_fallbacks.items():
            overrides.setdefault(override_key, direct_path)
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_owner_conservation_failed",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail=(
                "generated PAC channels were rejected because their exact material owner was not conserved"
            ),
        )
        return None
    failure_detail = synthesis.get("failure")
    skipped_detail = synthesis.get("skipped")
    if (
        bool(synthesis.get("attempted", False))
        and not bool(synthesis.get("succeeded", False))
        and (failure_detail or skipped_detail)
    ):
        detail = failure_detail or skipped_detail
        _record_rust_material_synthesis_diagnostic(
            synthesis_state,
            "compiler_fallback",
            lod_index=lod_index,
            submesh_index=submesh_index,
            detail=detail,
        )
    return resolved_channels, generated_channels, layered_normal_is_authoritative, source_submesh, runtime_skin_detail, skin_surface_contract


def _mesh_synthesized_texture_overrides(
    mesh: ParsedMesh,
    synthesis_root: Path,
    *,
    expected_root_identity: tuple[int, int],
    stop_event: threading.Event | None,
    synthesis_state: _RustMaterialSynthesisState,
    protected_keys: frozenset[tuple[int, int, str]] = frozenset(),
) -> dict[tuple[int, int, str], Path]:
    """Compile authoritative PAC graphs and encode only renderer-safe channels.

    The canonical .NET compiler owns PAC layer/tint interpretation.  Rust's
    protocol accepts DDS resources, so authoritative generated images are
    encoded into this disposable owned tree and copied into the session by the
    normal hashed texture publisher.  Rust samples the canonical scalar maps
    through dedicated linear roughness, metalness, occlusion, and specular
    slots; skin keeps its exact packed ``_sp`` response instead.
    """

    if not _mesh_has_material_synthesis_inputs(mesh):
        return {}
    cancellation_event = stop_event or threading.Event()
    overrides: dict[tuple[int, int, str], Path] = {}
    encoded_cache: dict[tuple[str, str], Path] = {}
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        if not any(_submesh_has_material_synthesis_inputs(submesh) for submesh in submeshes):
            continue
        synthesis_state.attempted = True
        _raise_if_texture_copy_cancelled(stop_event)
        package_dir = synthesis_root / f"lod-{lod_index:04d}"
        requested_channels_by_submesh: dict[int, frozenset[str]] = {}
        for submesh_index, submesh in enumerate(submeshes):
            if not _submesh_has_material_synthesis_inputs(submesh):
                requested_channels_by_submesh[submesh_index] = frozenset()
                continue
            requested_channels = set(_RUST_SYNTHESIS_OUTPUT_CHANNELS)
            if (lod_index, submesh_index, "base_color") in protected_keys:
                requested_channels.discard("base")
            if (lod_index, submesh_index, "material") in protected_keys:
                requested_channels.difference_update({"roughness", "metalness"})
            if requested_channels != set(_RUST_SYNTHESIS_OUTPUT_CHANNELS):
                requested_channels_by_submesh[submesh_index] = frozenset(
                    requested_channels
                )
        try:
            manifest = compile_mesh_dotnet_material_manifest(
                _RustMaterialLodSnapshot(
                    path=str(getattr(mesh, "path", "") or ""),
                    submeshes=tuple(submeshes),
                ),
                sidecar_payload={},
                package_dir=package_dir,
                material_signature=f"cdmw_rust_material_synthesis_v1:lod:{lod_index}",
                role=f"rust_lod_{lod_index}",
                include_resources=True,
                cancelled=cancellation_event.is_set,
                support_map_max_dimension=2048,
                requested_synthesis_channels_by_submesh=(
                    requested_channels_by_submesh or None
                ),
            )
        except RunCancelled as exc:
            raise RustMeshCancellationError(
                "Mesh texture preparation was cancelled"
            ) from exc
        except Exception as exc:
            # Material synthesis is preview enhancement.  A compiler failure
            # must not prevent Rust from opening when the direct DDS bindings
            # remain usable; cancellation is the sole abort path above.
            _record_rust_material_synthesis_diagnostic(
                synthesis_state,
                "compiler_failed",
                lod_index=lod_index,
                detail=f"{type(exc).__name__}: {exc}",
            )
            _clear_rust_material_synthesis_results(synthesis_state)
            return {}
        _raise_if_texture_copy_cancelled(stop_event)
        rows = manifest.get("submeshes", ()) if isinstance(manifest, Mapping) else ()
        if (
            not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes))
            or len(rows) != len(submeshes)
        ):
            _record_rust_material_synthesis_diagnostic(
                synthesis_state,
                "compiler_manifest_invalid",
                lod_index=lod_index,
                detail="canonical material compiler returned an invalid submesh list",
            )
            _clear_rust_material_synthesis_results(synthesis_state)
            return {}
        for submesh_index, row in enumerate(rows):
            row_state = _validated_synthesized_material_row(row, lod_index, submesh_index, submeshes, synthesis_state, protected_keys, overrides)
            if row_state is None:
                continue
            resolved_channels, generated_channels, layered_normal_is_authoritative, source_submesh, runtime_skin_detail, skin_surface_contract = row_state
            applied_roles: set[str] = set()
            base_presentation = _rust_generated_presentation_overrides(
                row,
                {"base_color"},
            )
            base_alpha_mode = str(
                base_presentation.get("alpha_mode", "") or ""
            )
            _apply_synthesized_material_roles(lod_index, submesh_index, submeshes, protected_keys, skin_surface_contract, generated_channels, resolved_channels, layered_normal_is_authoritative, runtime_skin_detail, synthesis_root, synthesis_state, base_alpha_mode, expected_root_identity, stop_event, encoded_cache, cancellation_event, overrides, applied_roles)
            direct_fallbacks = _rust_exact_direct_fallback_overrides(
                row,
                source_submesh,
                lod_index=lod_index,
                submesh_index=submesh_index,
                protected_keys=protected_keys,
                applied_roles=applied_roles,
            )
            for override_key, direct_path in direct_fallbacks.items():
                overrides.setdefault(override_key, direct_path)
            presentation_overrides = _rust_generated_presentation_overrides(
                row,
                applied_roles,
            )
            if presentation_overrides:
                synthesis_state.presentation_overrides.setdefault(
                    (lod_index, submesh_index), {}
                ).update(presentation_overrides)
    _validate_rust_material_synthesis_tree(
        synthesis_root,
        expected_root_identity,
    )
    return overrides


def _mesh_material_synthesis_context(
    root: Path,
    mesh: ParsedMesh,
    *,
    has_layer_manifest: bool,
    enabled: bool,
):
    if not enabled or not (_mesh_has_material_synthesis_inputs(mesh) or has_layer_manifest):
        return nullcontext(None)
    return tempfile.TemporaryDirectory(
        prefix="cdmw-rust-material-synthesis-",
        dir=root.parent,
    )


def _publish_rust_texture_resources(root, bindings, sources, stop_event, expected_root_identity):
    entry_count, aggregate_bytes = _validate_owned_session_tree(
        root,
        expected_root_identity,
    )
    initial_entry_count = entry_count
    initial_aggregate_bytes = aggregate_bytes
    file_references: dict[str, dict[str, object]] = {}
    for file_index, path_text in enumerate(sorted(sources, key=str.casefold)):
        _raise_if_texture_copy_cancelled(stop_event)
        if entry_count + 1 > _SESSION_MAX_ENTRIES:
            raise RustMeshProtocolError(
                "Mesh session contains too many owned entries"
            )
        reference = _atomic_copy_texture_payload(
            root,
            sources[path_text],
            file_index,
            expected_root_identity=expected_root_identity,
            aggregate_bytes_before=aggregate_bytes,
            stop_event=stop_event,
        )
        file_references[path_text] = reference
        entry_count += 1
        aggregate_bytes += int(reference["byte_length"])

    final_entry_count, final_aggregate_bytes = _validate_owned_session_tree(
        root,
        expected_root_identity,
    )
    if (
        final_entry_count != initial_entry_count + len(file_references)
        or final_aggregate_bytes
        != initial_aggregate_bytes
        + sum(
            int(reference["byte_length"])
            for reference in file_references.values()
        )
    ):
        raise RustMeshProtocolError(
            "Mesh session changed while texture payloads were being packaged"
        )

    resources: list[dict[str, object]] = []
    for (path_text, role), ownership in sorted(
        bindings.items(),
        key=lambda item: (item[0][1], item[0][0].casefold()),
    ):
        resources.append(
            {
                "label": sources[path_text].name,
                "role": role,
                "file": dict(file_references[path_text]),
                "material_indices_by_lod": [
                    sorted(indices) for indices in ownership
                ],
            }
        )
    return resources


def _mesh_texture_payloads(
    root: Path,
    mesh: ParsedMesh,
    *,
    expected_root_identity: tuple[int, int],
    stop_event: threading.Event | None = None,
    synthesis_state: _RustMaterialSynthesisState | None = None,
    material_package_path: object = "",
    preview_texture_overrides: Mapping[tuple[int, int, str], Path] | None = None,
    enable_material_synthesis: bool = True,
) -> list[dict[str, object]]:
    lods = _mesh_lods(mesh)
    material_synthesis = synthesis_state or _RustMaterialSynthesisState()
    package_root, _package_reason = _rust_material_package_root(
        material_package_path
    )
    package_presentations: dict[tuple[int, int], dict[str, object]] = {}
    if package_root is not None:
        package_presentations = _rust_material_package_presentation_overrides(
            mesh,
            package_root,
            stop_event=stop_event,
        )
        for key, values in package_presentations.items():
            material_synthesis.presentation_overrides.setdefault(key, {}).update(
                values
            )
    has_layer_manifest = bool(
        package_root is not None
        and (package_root / "net_materials.json").is_file()
    )
    synthesis_context = _mesh_material_synthesis_context(
        root,
        mesh,
        has_layer_manifest=has_layer_manifest,
        enabled=enable_material_synthesis,
    )
    with synthesis_context as synthesis_temporary:
        synthesized: dict[tuple[int, int, str], Path] = dict(
            preview_texture_overrides or {}
        )
        if synthesis_temporary is not None:
            synthesis_root = Path(synthesis_temporary).resolve()
            synthesis_identity = _session_root_identity(synthesis_root)
            with _pinned_session_root(synthesis_root, synthesis_identity):
                # Rust preparation is self-contained. The complete PAC/PAC_XML
                # graph and shared CDMW material combiner retain dye colours,
                # layer ordering, masks, and material response without launching
                # a hidden renderer process.
                canonical = _mesh_synthesized_texture_overrides(
                    mesh,
                    synthesis_root,
                    expected_root_identity=synthesis_identity,
                    stop_event=stop_event,
                    synthesis_state=material_synthesis,
                    protected_keys=frozenset(),
                )
                synthesized.update(canonical)
                generated_binding_count = 0
                for path in synthesized.values():
                    try:
                        if path.resolve().is_relative_to(synthesis_root):
                            generated_binding_count += 1
                    except (OSError, RuntimeError, ValueError):
                        continue
                material_synthesis.generated_binding_count = generated_binding_count

        # Compiler failures clear their own partial overrides.  Restore the
        # independently validated package presentation afterward, while
        # retaining any exact exporter result for the same field.
        for key, values in package_presentations.items():
            current = dict(material_synthesis.presentation_overrides.get(key, {}))
            material_synthesis.presentation_overrides[key] = {
                **values,
                **current,
            }

        bindings: dict[tuple[str, str], list[set[int]]] = {}
        sources: dict[str, Path] = {}
        for lod_index, submeshes in enumerate(lods):
            for submesh_index, submesh in enumerate(submeshes):
                resolved_roles: set[str] = set()
                for role, attributes in _TEXTURE_RESOURCE_SPECS:
                    path = synthesized.get((lod_index, submesh_index, role))
                    if path is None:
                        path = _first_texture_resource_dds_path(
                            submesh,
                            role,
                            attributes,
                        )
                    if path is None:
                        continue
                    key = (str(path), role)
                    sources[str(path)] = path
                    ownership = bindings.setdefault(key, [set() for _ in lods])
                    ownership[lod_index].add(submesh_index)
                    resolved_roles.add(role)
                for role in sorted(_RUST_SYNTHESIZED_SCALAR_ROLES):
                    path = synthesized.get((lod_index, submesh_index, role))
                    if path is None:
                        continue
                    key = (str(path), role)
                    sources[str(path)] = path
                    ownership = bindings.setdefault(key, [set() for _ in lods])
                    ownership[lod_index].add(submesh_index)
                    resolved_roles.add(role)
                for item in tuple(
                    getattr(submesh, "preview_material_texture_inputs", ()) or ()
                ):
                    role = _material_input_texture_role(item)
                    if not role or role in resolved_roles:
                        continue
                    if not _material_input_is_renderer_role_eligible(
                        submesh,
                        item,
                        role,
                    ):
                        continue
                    if (
                        role in {"roughness", "metalness"}
                        and (lod_index, submesh_index, "material") in synthesized
                    ):
                        # The exact packed surface already owns G/B for
                        # this part.  Publishing raw scalar guesses as separate
                        # roles would overwrite those authoritative channels in
                        # the Rust shader.
                        continue
                    path = _material_input_dds_path(item) if role else None
                    if path is None:
                        continue
                    key = (str(path), role)
                    sources[str(path)] = path
                    ownership = bindings.setdefault(key, [set() for _ in lods])
                    ownership[lod_index].add(submesh_index)
                    resolved_roles.add(role)

        return _publish_rust_texture_resources(root, bindings, sources, stop_event, expected_root_identity)


@dataclass(frozen=True, slots=True)
class _RustMaterialLodSnapshot:
    """Minimal mesh-shaped view used by the shared material-state translator."""

    path: str
    submeshes: tuple[object, ...]


def _rust_material_optional_scalar(
    parameters: Mapping[str, object],
    *names: str,
    minimum: float,
    maximum: float,
) -> float | None:
    for name in names:
        if name not in parameters:
            continue
        try:
            value = float(parameters[name])
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value):
            return None
        return max(minimum, min(maximum, value))
    return None


def _rust_material_optional_color(
    parameters: Mapping[str, object],
    name: str,
) -> list[float] | None:
    raw = parameters.get(name)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 3:
        return None
    values: list[float] = []
    for item in raw[:3]:
        try:
            value = float(item)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value):
            return None
        values.append(max(0.0, min(2.0, value)))
    return values


_RUST_SURFACE_PROFILE_FINISHES = frozenset(
    {"unspecified", "polished", "satin", "matte", "rough"}
)
_RUST_SURFACE_PROFILE_STRUCTURES = frozenset(
    {
        "unspecified",
        "smooth",
        "woven",
        "fibrous",
        "grained",
        "porous",
        "crystalline",
        "shell",
    }
)
_RUST_SURFACE_PROFILE_COATINGS = frozenset(
    {"none", "painted", "lacquered", "clearcoat"}
)
_RUST_SURFACE_PROFILE_FACTORS = (
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "anisotropy",
)
_RUST_SURFACE_PROFILE_AUTHORED_FACTORS = (
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "anisotropy",
)


def _rust_surface_profile(
    raw_profile: object,
    *,
    material_category: str,
    category_confidence: float,
) -> dict[str, object] | None:
    """Validate the native source-derived profile at the Python/Rust boundary."""

    if not isinstance(raw_profile, Mapping) or not raw_profile:
        return None
    family = str(raw_profile.get("family", "") or "").strip().casefold()
    try:
        family_code = int(raw_profile.get("family_code", -1))
        confidence = float(raw_profile.get("confidence", category_confidence))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError(
            "Preview Core returned an invalid material surface profile"
        ) from exc
    if (
        family != material_category
        or not is_known_material_category(family)
        or family_code != material_category_code(family)
    ):
        raise RustMeshProtocolError(
            "Preview Core surface-profile family does not match its material category"
        )
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise RustMeshProtocolError(
            "Preview Core surface-profile confidence is outside 0..=1"
        )
    if abs(confidence - category_confidence) > 1.0e-6:
        raise RustMeshProtocolError(
            "Preview Core surface-profile confidence does not match its material category"
        )

    finish = str(raw_profile.get("finish", "") or "").strip().casefold()
    structure = str(raw_profile.get("structure", "") or "").strip().casefold()
    coating = str(raw_profile.get("coating", "") or "").strip().casefold()
    if finish not in _RUST_SURFACE_PROFILE_FINISHES:
        raise RustMeshProtocolError("Preview Core surface-profile finish is invalid")
    if structure not in _RUST_SURFACE_PROFILE_STRUCTURES:
        raise RustMeshProtocolError("Preview Core surface-profile structure is invalid")
    if coating not in _RUST_SURFACE_PROFILE_COATINGS:
        raise RustMeshProtocolError("Preview Core surface-profile coating is invalid")

    evidence = str(raw_profile.get("evidence", "") or "").strip()
    if (
        not evidence
        or len(evidence) > 1024
        or any(character.isprintable() is False for character in evidence)
    ):
        raise RustMeshProtocolError("Preview Core surface-profile evidence is invalid")

    raw_fallbacks = raw_profile.get("fallbacks", {})
    raw_authored = raw_profile.get("authored", {})
    raw_fallback_applied = raw_profile.get("fallback_applied", {})
    if not all(
        isinstance(value, Mapping)
        for value in (raw_fallbacks, raw_authored, raw_fallback_applied)
    ):
        raise RustMeshProtocolError("Preview Core surface-profile factors are invalid")
    fallbacks: dict[str, float] = {}
    for name in _RUST_SURFACE_PROFILE_FACTORS:
        try:
            value = float(raw_fallbacks[name])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RustMeshProtocolError(
                f"Preview Core surface-profile fallback {name!r} is invalid"
            ) from exc
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise RustMeshProtocolError(
                f"Preview Core surface-profile fallback {name!r} is outside 0..=1"
            )
        fallbacks[name] = value
    authored = {
        name: bool(raw_authored.get(name, False))
        for name in _RUST_SURFACE_PROFILE_AUTHORED_FACTORS
    }
    fallback_applied = {
        name: bool(raw_fallback_applied.get(name, False))
        for name in _RUST_SURFACE_PROFILE_FACTORS
    }
    if fallbacks["height_scale"] != 0.0 or fallback_applied["height_scale"]:
        raise RustMeshProtocolError(
            "Preview Core surface profile must not supply a height-scale fallback"
        )
    for name in _RUST_SURFACE_PROFILE_AUTHORED_FACTORS:
        if authored[name] and fallback_applied[name]:
            raise RustMeshProtocolError(
                f"Preview Core applied surface-profile fallback {name!r} over authored data"
            )
    return {
        "family": family,
        "family_code": family_code,
        "finish": finish,
        "structure": structure,
        "coating": coating,
        "confidence": confidence,
        "evidence": evidence,
        "fallbacks": fallbacks,
        "authored": authored,
        "fallback_applied": fallback_applied,
    }


def _rust_normalized_parameter_name(value: object) -> str:
    return "".join(
        character
        for character in str(value or "").casefold()
        if character.isalnum()
    )


def _rust_material_parameter_number(value: object) -> float | None:
    raw = getattr(value, "numeric_value", None)
    if raw is None:
        raw = getattr(value, "value", None)
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


_RUST_HEIGHT_SCALE_PARAMETER_NAMES = (
    "screenspacedisplacementscale",
    "detailscreenspacedisplacementscale",
    "heightintensity",
)


def _rust_exact_authored_height_scale(source: object) -> float | None:
    """Return the owner-scoped PAC displacement strength when it is explicit."""

    material_inputs = tuple(
        getattr(source, "preview_material_texture_inputs", ()) or ()
    )
    for wanted_name in _RUST_HEIGHT_SCALE_PARAMETER_NAMES:
        for item in material_inputs:
            if (
                _material_input_texture_role(item) != "height"
                or not _rust_input_is_strict_exact_owner_binding(source, item)
                or str(
                    getattr(item, "binding_disposition", "") or ""
                ).strip().casefold()
                == "layer_only"
            ):
                continue
            for parameter in tuple(
                getattr(item, "material_parameters", ()) or ()
            ):
                if (
                    _rust_normalized_parameter_name(
                        getattr(parameter, "parameter_name", "")
                    )
                    != wanted_name
                ):
                    continue
                value = _rust_material_parameter_number(parameter)
                if value is not None:
                    return max(0.0, min(1.0, value))

    # Complete PAC/PAC_XML material models also retain the wrapper's exact
    # parameter list on the submesh.  This covers old prepared models whose
    # direct height input predates owner metadata without accepting native
    # package guesses under unrelated parameter names.
    parameters = tuple(getattr(source, "preview_material_parameters", ()) or ())
    for wanted_name in _RUST_HEIGHT_SCALE_PARAMETER_NAMES:
        for parameter in parameters:
            if (
                _rust_normalized_parameter_name(
                    getattr(parameter, "parameter_name", "")
                )
                != wanted_name
            ):
                continue
            value = _rust_material_parameter_number(parameter)
            if value is not None:
                return max(0.0, min(1.0, value))
    return None


def _rust_exact_authored_anisotropy(source: object) -> bool | None:
    """Resolve explicit owner-scoped anisotropy, preserving an authored zero."""

    try:
        owner_slot_index = int(
            getattr(source, "preview_pac_material_owner_slot_index", -1)
        )
    except (TypeError, ValueError, OverflowError):
        owner_slot_index = -1
    material_inputs = tuple(
        getattr(source, "preview_material_texture_inputs", ()) or ()
    )
    if owner_slot_index < 0:
        exact_owners: set[int] = set()
        for item in material_inputs:
            authority = str(
                getattr(item, "binding_authority", "") or ""
            ).strip().casefold()
            if authority not in {"authoritative", "exact"}:
                continue
            try:
                item_owner = int(getattr(item, "owner_slot_index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if item_owner >= 0:
                exact_owners.add(item_owner)
        if len(exact_owners) == 1:
            owner_slot_index = next(iter(exact_owners))

    parameters: list[object] = []
    has_flow = False
    for item in material_inputs:
        authority = str(
            getattr(item, "binding_authority", "") or ""
        ).strip().casefold()
        try:
            item_owner = int(getattr(item, "owner_slot_index", -1))
        except (TypeError, ValueError, OverflowError):
            item_owner = -1
        if (
            owner_slot_index < 0
            or authority not in {"authoritative", "exact"}
            or item_owner != owner_slot_index
        ):
            continue
        has_flow = has_flow or _material_input_texture_role(item) == "flow"
        parameters.extend(tuple(getattr(item, "material_parameters", ()) or ()))
    # The flattened parameter list has no per-row owner identity.  It is safe
    # for an explicitly owned source, a uniquely inferred owner, or a legacy
    # source with no owner contract at all.  When authoritative inputs prove
    # multiple owners on one Preview Core batch, accepting that list would let
    # one owner's anisotropy scalar leak across the whole batch.
    if owner_slot_index >= 0 or not exact_owners:
        parameters.extend(
            tuple(getattr(source, "preview_material_parameters", ()) or ())
        )
    authored = False
    enabled = False
    for parameter in parameters:
        name = _rust_normalized_parameter_name(
            getattr(parameter, "parameter_name", "")
        )
        if "anisotrop" not in name:
            continue
        authored = True
        number = _rust_material_parameter_number(parameter)
        if number is None:
            value = str(getattr(parameter, "value", "") or "").strip()
            enabled = enabled or bool(value)
        else:
            enabled = enabled or number > 0.0
    if authored:
        return enabled
    return True if has_flow else None


def _rust_owner_scoped_surface_profile_anisotropy(
    surface_profile: dict[str, object] | None,
    authored_anisotropy: bool | None,
) -> dict[str, object] | None:
    """Make Preview Core's batch-wide hint obey the exact PAC material owner."""

    if surface_profile is None:
        return None
    authored = dict(surface_profile["authored"])
    fallback_applied = dict(surface_profile["fallback_applied"])
    owner_authored = authored_anisotropy is not None
    authored["anisotropy"] = owner_authored
    fallback_applied["anisotropy"] = bool(
        not owner_authored
        and float(dict(surface_profile["fallbacks"])["anisotropy"]) > 0.0
    )
    return {
        **surface_profile,
        "authored": authored,
        "fallback_applied": fallback_applied,
    }


_RUST_SKIN_DETAIL_PARAMETER_NAMES = frozenset(
    {
        "skindetailmasktexture",
        "skindetailnormaltexture",
        "skindetailmaterialtexture",
    }
)


def _rust_input_is_strict_exact_owner_binding(
    source: object,
    item: object,
) -> bool:
    authority = str(
        getattr(item, "binding_authority", "") or ""
    ).strip().casefold()
    if authority not in {"authoritative", "exact"}:
        return False
    try:
        source_owner = int(
            getattr(source, "preview_pac_material_owner_slot_index", -1)
        )
        item_owner = int(getattr(item, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        return False
    return source_owner >= 0 and item_owner == source_owner


def _rust_exact_skin_detail_inputs(source: object) -> tuple[object, ...]:
    return tuple(
        item
        for item in tuple(
            getattr(source, "preview_material_texture_inputs", ()) or ()
        )
        if _rust_input_is_strict_exact_owner_binding(source, item)
        and _rust_normalized_parameter_name(
            getattr(item, "parameter_name", "")
        )
        in _RUST_SKIN_DETAIL_PARAMETER_NAMES
    )


def _rust_has_exact_runtime_skin_detail(source: object) -> bool:
    return {
        _rust_normalized_parameter_name(
            getattr(item, "parameter_name", "")
        )
        for item in _rust_exact_skin_detail_inputs(source)
    } == _RUST_SKIN_DETAIL_PARAMETER_NAMES


def _rust_has_available_runtime_skin_detail(source: object) -> bool:
    available_parameters = {
        _rust_normalized_parameter_name(
            getattr(item, "parameter_name", "")
        )
        for item in _rust_exact_skin_detail_inputs(source)
        if _material_input_dds_path(item) is not None
    }
    return available_parameters == _RUST_SKIN_DETAIL_PARAMETER_NAMES


def _rust_skin_detail_factors(source: object) -> tuple[float | None, float | None]:
    """Return exact PAC skin-detail scale/opacity for one material owner.

    Crimson skin detail is support-only: the mask uses the base UVs while the
    shared pore normal/material maps repeat at ``1 / _skinDetailScale``.  Only
    exact skin-detail parameter bindings enable this path, so generic detail
    layers cannot accidentally acquire the skin shader approximation.
    """

    skin_inputs = _rust_exact_skin_detail_inputs(source)
    if not _rust_has_exact_runtime_skin_detail(source):
        return None, None

    parameters = list(
        tuple(getattr(source, "preview_material_parameters", ()) or ())
    )
    for item in skin_inputs:
        parameters.extend(tuple(getattr(item, "material_parameters", ()) or ()))

    values: dict[str, float] = {}
    for parameter in parameters:
        name = _rust_normalized_parameter_name(
            getattr(parameter, "parameter_name", "")
        )
        if name not in {"skindetailscale", "skindetailopacity"}:
            continue
        number = _rust_material_parameter_number(parameter)
        if number is not None:
            values.setdefault(name, number)

    raw_overrides = getattr(source, "preview_native_material_overrides", {})
    if isinstance(raw_overrides, Mapping):
        raw_layers = raw_overrides.get("material_layers", ())
        if isinstance(raw_layers, Sequence) and not isinstance(
            raw_layers,
            (str, bytes, bytearray),
        ):
            for layer in raw_layers:
                if not isinstance(layer, Mapping):
                    continue
                layer_role = _rust_normalized_parameter_name(
                    layer.get("layer_role", "")
                )
                source_parameter = _rust_normalized_parameter_name(
                    layer.get("source_parameter", "")
                )
                mask_parameter = _rust_normalized_parameter_name(
                    layer.get("mask_parameter", "")
                )
                if (
                    layer_role != "skindetail"
                    or "skindetailmasktexture"
                    not in {source_parameter, mask_parameter}
                ):
                    continue
                try:
                    layer_scale = float(layer.get("detail_scale"))
                except (TypeError, ValueError, OverflowError):
                    layer_scale = None
                try:
                    layer_weight = float(layer.get("weight"))
                except (TypeError, ValueError, OverflowError):
                    layer_weight = None
                if layer_scale is not None and not math.isfinite(layer_scale):
                    layer_scale = None
                if layer_weight is not None and not math.isfinite(layer_weight):
                    layer_weight = None
                if layer_scale is not None:
                    values.setdefault("skindetailscale", layer_scale)
                if layer_weight is not None:
                    values.setdefault("skindetailopacity", layer_weight)
                break
        for name, raw in raw_overrides.items():
            normalized = _rust_normalized_parameter_name(name)
            if normalized not in {"skindetailscale", "skindetailopacity"}:
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(number):
                values[normalized] = number

    scale = values.get("skindetailscale")
    opacity = values.get("skindetailopacity")
    if scale is not None:
        scale = max(0.001, min(1.0, scale))
    if opacity is not None:
        opacity = max(0.0, min(1.0, opacity))
    return scale, opacity


def _rust_has_exact_skin_category_evidence(
    source: object,
    shader_family: object,
) -> bool:
    """Recognize only the conserved PAC-XML skin material contract.

    The package classifier can preserve an authoritative ``SkinnedMeshSkin``
    shader while leaving its broad category as generic dielectric.  Rust needs
    the category to suppress metallic interpretation of skin ``*_sp`` blue,
    but a shader-looking name alone is not enough authority.  Require the
    same-owner PAC inputs that the shipped skin graph declares: its dedicated
    material response plus the complete skin-detail mask/normal/material set.
    """

    if normalize_shader_family(shader_family) != "skin":
        return False
    inputs = tuple(
        getattr(source, "preview_material_texture_inputs", ()) or ()
    )
    if not inputs:
        return False
    has_skin_material_response = False
    for item in inputs:
        if not _rust_input_is_strict_exact_owner_binding(source, item):
            continue
        parameter_name = _rust_normalized_parameter_name(
            getattr(item, "parameter_name", "")
        )
        source_kind = _rust_normalized_parameter_name(
            getattr(item, "source_kind", "")
        )
        if (
            parameter_name == "materialtexture"
            and source_kind == "crimsonskinmaterialresponse"
            and _material_input_texture_role(item) == "specular"
        ):
            has_skin_material_response = True
    return has_skin_material_response and _rust_has_exact_runtime_skin_detail(
        source
    )


def _rust_presentation_parameters(source, submeshes, material_index):
    parameters = source.get("parameters", {})
    if not isinstance(parameters, Mapping):
        parameters = {}
    raw_overrides = getattr(
        submeshes[material_index],
        "preview_native_material_overrides",
        {},
    )
    factor_parameters = (
        dict(raw_overrides) if isinstance(raw_overrides, Mapping) else {}
    )
    factor_parameters.update(parameters)
    texture_tint = _rust_material_optional_color(source, "texture_tint")
    if texture_tint is None:
        texture_tint = _rust_material_optional_color(
            factor_parameters,
            "texture_tint",
        )
    base_tint_strength = _rust_material_optional_scalar(
        source,
        "base_tint_strength",
        minimum=0.0,
        maximum=1.0,
    )
    if base_tint_strength is None:
        base_tint_strength = _rust_material_optional_scalar(
            factor_parameters,
            "base_tint_strength",
            minimum=0.0,
            maximum=1.0,
        )
    try:
        material_slot_index = int(
            source.get("material_slot_index", material_index)
        )
    except (TypeError, ValueError, OverflowError):
        material_slot_index = material_index
    material_slot_index = max(0, min(0xFFFF_FFFF, material_slot_index))
    return factor_parameters, texture_tint, base_tint_strength, material_slot_index


def _rust_presentation_surface_policy(source, submeshes, material_index):
    category = str(
        source.get("material_category", MATERIAL_CATEGORY_UNCLASSIFIED)
        or MATERIAL_CATEGORY_UNCLASSIFIED
    ).strip().casefold()
    if not is_known_material_category(category):
        category = MATERIAL_CATEGORY_UNCLASSIFIED
    try:
        category_confidence = float(
            source.get("material_category_confidence", 0.35)
        )
    except (TypeError, ValueError, OverflowError):
        category_confidence = 0.35
    if not math.isfinite(category_confidence):
        category_confidence = 0.35
    category_confidence = max(0.0, min(1.0, category_confidence))
    shader_family = str(source.get("shader_family", "generic") or "generic").strip()
    if (
        not shader_family
        or len(shader_family) > 64
        or any(character.isspace() and character not in {" "} for character in shader_family)
    ):
        shader_family = "generic"
    if _rust_has_exact_skin_category_evidence(
        submeshes[material_index],
        shader_family,
    ):
        # The conserved PAC XML shader and owner-scoped input graph are
        # stronger category evidence than the package's generic
        # dielectric fallback.  This also keeps skin *_sp blue out of
        # Rust's metalness path.
        category = "skin"
        category_confidence = max(category_confidence, 0.95)
    normal_y_policy = str(
        source.get("normal_y_policy", "preserve") or "preserve"
    ).strip().casefold()
    if normal_y_policy not in {"preserve", "invert_green_for_directx"}:
        normal_y_policy = "preserve"
    alpha_mode = str(source.get("alpha_mode", "opaque") or "opaque").strip().casefold()
    if alpha_mode not in {"opaque", "cutout", "blend"}:
        alpha_mode = "opaque"
    return category, category_confidence, shader_family, normal_y_policy, alpha_mode


def _append_rust_material_presentation(rows, source, fallback_index, submeshes, generated_overrides, lod_index):
    if not isinstance(source, Mapping):
        raise RustMeshProtocolError(
            "CDMW material-state translator returned an invalid material row"
        )
    try:
        material_index = int(source.get("submesh_index", fallback_index))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError(
            "CDMW material-state translator returned an invalid material index"
        ) from exc
    if material_index < 0 or material_index >= len(submeshes):
        raise RustMeshProtocolError(
            "CDMW material-state translator returned an out-of-range material index"
        )
    canonical_override = (
        generated_overrides.get((lod_index, material_index), {})
        if generated_overrides is not None
        else {}
    )
    if canonical_override:
        source = {**dict(source), **dict(canonical_override)}
    category, category_confidence, shader_family, normal_y_policy, alpha_mode = _rust_presentation_surface_policy(source, submeshes, material_index)
    factor_parameters, texture_tint, base_tint_strength, material_slot_index = _rust_presentation_parameters(source, submeshes, material_index)
    skin_detail_scale, skin_detail_opacity = _rust_skin_detail_factors(
        submeshes[material_index]
    )
    authored_height_scale = _rust_exact_authored_height_scale(
        submeshes[material_index]
    )
    authored_anisotropy = _rust_exact_authored_anisotropy(
        submeshes[material_index]
    )
    surface_profile = _rust_surface_profile(
        source.get("surface_profile"),
        material_category=category,
        category_confidence=category_confidence,
    )
    surface_profile = _rust_owner_scoped_surface_profile_anisotropy(
        surface_profile,
        authored_anisotropy,
    )
    profile_anisotropy = bool(
        surface_profile
        and surface_profile["fallback_applied"]["anisotropy"]
        and surface_profile["fallbacks"]["anisotropy"] > 0.0
    )
    rows.append(
        {
            "lod_index": lod_index,
            "material_index": material_index,
            "material_slot_index": material_slot_index,
            "material_category": category,
            "category_code": material_category_code(category),
            "category_confidence": category_confidence,
            "surface_profile": surface_profile,
            "shader_family": shader_family,
            "normal_y_policy": normal_y_policy,
            "normal_y_inverted": normal_y_policy
            == "invert_green_for_directx",
            "texture_flip_vertical": bool(
                source.get(
                    "texture_flip_vertical",
                    getattr(
                        submeshes[material_index],
                        "preview_texture_flip_vertical",
                        False,
                    ),
                )
            ),
            "alpha_mode": alpha_mode,
            "gltf_metallic_roughness": factor_parameters.get("gltf_metallic_roughness") is True,
            "opacity": _rust_material_optional_scalar(
                factor_parameters,
                "opacity",
                minimum=0.0,
                maximum=1.0,
            ),
            "alpha_cutoff": _rust_material_optional_scalar(
                source,
                "alpha_cutoff",
                minimum=0.0,
                maximum=1.0,
            ),
            "double_sided": bool(source.get("double_sided", False)),
            "roughness": _rust_material_optional_scalar(
                factor_parameters,
                "roughness",
                "roughness_hint",
                minimum=0.0,
                maximum=1.0,
            ),
            "metalness": _rust_material_optional_scalar(
                factor_parameters,
                "metalness",
                "metalness_hint",
                minimum=0.0,
                maximum=1.0,
            ),
            "specular": _rust_material_optional_scalar(
                factor_parameters,
                "specular",
                "specular_hint",
                minimum=0.0,
                maximum=1.0,
            ),
            "emissive_color": _rust_material_optional_color(
                factor_parameters,
                "emissive_color",
            ),
            "emissive_intensity": _rust_material_optional_scalar(
                factor_parameters,
                "emissive_intensity",
                minimum=0.0,
                maximum=32.0,
            ),
            "height_scale": (
                authored_height_scale
                if authored_height_scale is not None
                else _rust_material_optional_scalar(
                    factor_parameters,
                    "height_scale",
                    "height_amount",
                    minimum=0.0,
                    maximum=1.0,
                )
            ),
            "texture_tint": texture_tint,
            "base_tint_strength": base_tint_strength,
            "hair_anisotropy": (
                authored_anisotropy
                if authored_anisotropy is not None
                else shader_family.casefold() == "hair" or profile_anisotropy
            ),
            "skin_detail_scale": skin_detail_scale,
            "skin_detail_opacity": skin_detail_opacity,
        }
    )


def _mesh_material_presentations(
    mesh: ParsedMesh,
    *,
    generated_overrides: Mapping[tuple[int, int], Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Translate the live Archive Preview material contract for Rust.

    Rows are deliberately local to one LOD/material range.  Asking the shared
    translator for a non-replacement role makes its indices local and avoids
    leaking a scene-global or source-wrapper slot into Rust's draw ranges.
    """

    lods = _mesh_lods(mesh)
    maximum_rows = min(
        _RUST_MATERIAL_PRESENTATION_LIMIT,
        sum(len(submeshes) for submeshes in lods),
    )
    rows: list[dict[str, object]] = []
    for lod_index, submeshes in enumerate(lods):
        snapshot = _RustMaterialLodSnapshot(
            path=str(getattr(mesh, "path", "") or ""),
            submeshes=tuple(submeshes),
        )
        state = mesh_dotnet_material_state_payload(
            snapshot,
            session_id="rust-material-presentation",
            edit_revision=0,
            generation=0,
            role=f"rust_lod_{lod_index}",
            material_signature="cdmw_rust_material_presentation_v1",
        )
        material_rows = state.get("submeshes", ())
        if not isinstance(material_rows, Sequence) or isinstance(
            material_rows,
            (str, bytes),
        ):
            raise RustMeshProtocolError(
                "CDMW material-state translator returned an invalid submesh list"
            )
        for fallback_index, source in enumerate(material_rows):
            if len(rows) >= maximum_rows:
                raise RustMeshProtocolError(
                    "Mesh material presentation exceeds the owned material-range limit"
                )
            _append_rust_material_presentation(rows, source, fallback_index, submeshes, generated_overrides, lod_index)
    return rows


def _selection_payload(selection: MeshEditSelection) -> dict[str, object]:
    return {
        "vertices_by_submesh": {str(key): list(values) for key, values in selection.vertices_by_submesh},
        "edges_by_submesh": {
            str(key): [list(edge) for edge in values] for key, values in selection.edges_by_submesh
        },
        "faces_by_submesh": {str(key): list(values) for key, values in selection.faces_by_submesh},
        "source_indices": list(selection.source_indices),
    }


def _selection_from_payload(payload: object) -> MeshEditSelection:
    value = payload if isinstance(payload, Mapping) else {}
    return MeshEditSelection.from_maps(
        vertices_by_submesh=value.get("vertices_by_submesh"),
        edges_by_submesh=value.get("edges_by_submesh"),
        faces_by_submesh=value.get("faces_by_submesh"),
        source_indices=value.get("source_indices"),
    )


def _require_argument_keys(
    args: Mapping[str, object],
    allowed: frozenset[str],
    command: str,
) -> None:
    unexpected = sorted(str(key) for key in args if str(key) not in allowed)
    if unexpected:
        raise RustMeshProtocolError(
            f"Mesh {command} received unsupported arguments: {', '.join(unexpected)}"
        )


def _require_explicit_selection(
    service: MeshService,
    session_id: str,
    payload: object,
) -> MeshEditSelection:
    if not isinstance(payload, Mapping):
        raise RustMeshProtocolError("Mesh command requires an explicit selection object")
    selection = _selection_from_payload(payload)
    mesh = service.working_mesh(session_id, clone=False)
    if _prune_selection_to_mesh(mesh, selection) != selection:
        raise RustMeshProtocolError(
            "Mesh command selection contains invalid mesh elements"
        )
    return selection


def _finite_command_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise RustMeshProtocolError(f"Mesh {name} must be a finite number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError(
            f"Mesh {name} must be a finite number"
        ) from exc
    if not math.isfinite(result):
        raise RustMeshProtocolError(f"Mesh {name} must be a finite number")
    return result


def _command_truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _strict_command_index(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise RustMeshProtocolError(f"Mesh {name} must be an integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RustMeshProtocolError(f"Mesh {name} must be an integer") from exc
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise RustMeshProtocolError(f"Mesh {name} must be an integer")
    if isinstance(value, str) and str(result) != value.strip():
        raise RustMeshProtocolError(f"Mesh {name} must be an integer")
    return result


def _bounded_text(value: object) -> str:
    return str(value or "")[:_SKELETON_STATE_MAX_TEXT]


def _source_weights_available(mesh: ParsedMesh) -> bool:
    """Return whether the immutable source contains at least one usable skin row."""

    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        vertex_count = len(tuple(getattr(submesh, "vertices", ()) or ()))
        bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        for vertex_index in range(min(vertex_count, len(bone_indices), len(bone_weights))):
            try:
                index_row = tuple(bone_indices[vertex_index])
                weight_row = tuple(bone_weights[vertex_index])
            except TypeError:
                continue
            for raw_index, raw_weight in zip(index_row, weight_row):
                try:
                    bone_index = int(raw_index)
                    weight = float(raw_weight)
                except (TypeError, ValueError, OverflowError):
                    continue
                if bone_index >= 0 and math.isfinite(weight) and weight > 0.0:
                    return True
    return False


@dataclass(frozen=True, slots=True)
class _RustSkinWeightCapability:
    enabled: bool
    reason: str
    eligible_submesh_indices: tuple[int, ...] = ()
    palette: tuple[int, ...] = ()
    skeleton_bone_to_palette_slot: Mapping[int, int] = field(default_factory=dict)

    def payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "exact_pac_only": True,
            "eligible_submesh_indices": list(self.eligible_submesh_indices),
            "palette_size": len(self.palette),
        }


def _rust_skin_weight_capability(session: object) -> _RustSkinWeightCapability:
    """Return the exact writer capability, derived only from immutable inputs."""

    if str(getattr(session, "mesh_format", "") or "").strip().lower() != "pac":
        return _RustSkinWeightCapability(False, "Skin-weight editing is currently proven only for PAC LOD 0.")
    original_data = bytes(getattr(session, "original_data", b"") or b"")
    if not original_data or not bool(getattr(session, "base_mesh_is_original_parse", False)):
        return _RustSkinWeightCapability(
            False,
            "Skin-weight editing needs the immutable original PAC bytes and their exact parsed layout.",
        )
    skeleton = getattr(session, "skeleton", None)
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    if not bones:
        reason = _bounded_text(getattr(session, "skeleton_resolution_reason", "")).strip()
        return _RustSkinWeightCapability(
            False,
            reason or "No matching PAB skeleton was attached automatically. Open this PAC from Archive Browser with its skeleton dependencies available.",
        )
    palette = tuple(resolve_pac_bone_palette(original_data, skeleton))
    if not palette:
        return _RustSkinWeightCapability(
            False,
            "The linked PAB does not resolve the PAC bone palette; named weight edits are disabled.",
        )

    bone_to_slot: dict[int, int] = {}
    for slot, bone_ordinal in enumerate(palette):
        if not 0 <= bone_ordinal < len(bones):
            return _RustSkinWeightCapability(False, "The resolved PAC bone palette is outside the linked skeleton.")
        bone = bones[bone_ordinal]
        try:
            bone_index = int(getattr(bone, "index", bone_ordinal))
        except (TypeError, ValueError, OverflowError):
            bone_index = bone_ordinal
        bone_to_slot.setdefault(bone_index, slot)

    if str(getattr(session, "output_policy", "") or "") != MeshOutputPolicy.EXACT_GAME_ASSET.value:
        return _RustSkinWeightCapability(
            False,
            "Skin-weight editing requires Exact Game Asset output; Free Edit OBJ cannot preserve rig weights.",
            palette=palette,
            skeleton_bone_to_palette_slot=bone_to_slot,
        )
    if int(getattr(session, "lod_index", -1)) != 0:
        return _RustSkinWeightCapability(
            False,
            "Skin-weight editing is currently proven only for PAC LOD 0.",
            palette=palette,
            skeleton_bone_to_palette_slot=bone_to_slot,
        )

    base_mesh = getattr(session, "base_mesh", None)
    working_mesh = getattr(session, "working_mesh", None)
    base_submeshes = tuple(getattr(base_mesh, "submeshes", ()) or ())
    working_submeshes = tuple(getattr(working_mesh, "submeshes", ()) or ())
    if len(base_submeshes) != len(working_submeshes):
        return _RustSkinWeightCapability(False, "Skin-weight editing requires unchanged PAC part topology.")
    eligible = tuple(
        index
        for index, (original, current) in enumerate(zip(base_submeshes, working_submeshes))
        if _safe_pac_skin_weight_submesh(original, current, original_data, len(palette))
    )
    if not eligible:
        return _RustSkinWeightCapability(
            False,
            "No part has the proven 40-byte pac_slot_u10x6 layout without protected extra influences.",
            palette=palette,
            skeleton_bone_to_palette_slot=bone_to_slot,
        )
    return _RustSkinWeightCapability(
        True,
        "Exact PAC LOD 0 skin-weight replacement is available.",
        eligible_submesh_indices=eligible,
        palette=palette,
        skeleton_bone_to_palette_slot=bone_to_slot,
    )


def _safe_pac_skin_weight_submesh(
    original: object,
    current: object,
    original_data: bytes,
    palette_size: int,
) -> bool:
    original_vertices = tuple(getattr(original, "vertices", ()) or ())
    vertices = tuple(getattr(current, "vertices", ()) or ())
    if not vertices or len(vertices) != len(original_vertices):
        return False
    if tuple(getattr(current, "faces", ()) or ()) != tuple(getattr(original, "faces", ()) or ()):
        return False
    identity = tuple(range(len(vertices)))
    if tuple(getattr(original, "source_vertex_map", ()) or ()) != identity:
        return False
    if tuple(getattr(current, "source_vertex_map", ()) or ()) != identity:
        return False
    if tuple(getattr(current, "source_bone_palette", ()) or ()) != tuple(
        getattr(original, "source_bone_palette", ()) or ()
    ):
        return False
    if str(getattr(original, "source_skin_weight_layout", "") or "") != PAC_SKIN_WEIGHT_LAYOUT:
        return False
    if str(getattr(current, "source_skin_weight_layout", "") or "") != PAC_SKIN_WEIGHT_LAYOUT:
        return False
    if int(getattr(original, "source_vertex_stride", 0) or 0) != 40:
        return False
    if int(getattr(current, "source_vertex_stride", 0) or 0) != 40:
        return False
    original_offsets = tuple(getattr(original, "source_vertex_offsets", ()) or ())
    current_offsets = tuple(getattr(current, "source_vertex_offsets", ()) or ())
    if current_offsets != original_offsets or len(original_offsets) != len(vertices):
        return False
    try:
        if any(int(offset) < 0 or int(offset) + 40 > len(original_data) for offset in original_offsets):
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    return _safe_pac_skin_rows(original, len(vertices), palette_size) and _safe_pac_skin_rows(
        current,
        len(vertices),
        palette_size,
    )


def _safe_pac_skin_rows(submesh: object, vertex_count: int, palette_size: int) -> bool:
    index_rows = tuple(getattr(submesh, "bone_indices", ()) or ())
    weight_rows = tuple(getattr(submesh, "bone_weights", ()) or ())
    if len(index_rows) != vertex_count or len(weight_rows) != vertex_count:
        return False
    for raw_indices, raw_weights in zip(index_rows, weight_rows):
        try:
            indices = tuple(int(value) for value in tuple(raw_indices or ()))
            weights = tuple(float(value) for value in tuple(raw_weights or ()))
        except (TypeError, ValueError, OverflowError):
            return False
        if not 1 <= len(indices) == len(weights) <= 6:
            return False
        if len(set(indices)) != len(indices):
            return False
        if any(index < 0 or index > 1023 or index >= palette_size for index in indices):
            return False
        if any(not math.isfinite(weight) or weight < 0.0 for weight in weights):
            return False
        if not math.isclose(sum(weights), 1.0, rel_tol=1.0e-6, abs_tol=1.0e-6):
            return False
    return True


def _skeleton_state_payload(
    summary: object,
    *,
    source_weights_available: bool,
    weight_edit_capability: Mapping[str, object] | None = None,
    palette_slot_to_bone_index: Mapping[int, int] | None = None,
    selected_palette_slot: int | None = None,
) -> dict[str, object]:
    bones = tuple(getattr(summary, "bones", ()) or ())
    parts = tuple(getattr(summary, "parts", ()) or ())
    selected_weights = tuple(getattr(summary, "selected_vertex_weights", ()) or ())
    resolved_influences = bool(palette_slot_to_bone_index)
    pose = getattr(summary, "pose", None)
    return {
        "available": True,
        "skinned": bool(getattr(summary, "skinned", False)),
        "source_weights_available": bool(source_weights_available),
        "weight_edit_capability": dict(weight_edit_capability or {}),
        "part_count": int(getattr(summary, "part_count", 0) or 0),
        "vertex_count": int(getattr(summary, "vertex_count", 0) or 0),
        "weighted_part_count": int(getattr(summary, "weighted_part_count", 0) or 0),
        "weighted_vertex_count": int(getattr(summary, "weighted_vertex_count", 0) or 0),
        "max_bone_index": int(getattr(summary, "max_bone_index", -1)),
        "inferred_bone_count": int(getattr(summary, "inferred_bone_count", 0) or 0),
        "skeleton_bone_count": getattr(summary, "skeleton_bone_count", None),
        "skeleton_source": _bounded_text(getattr(summary, "skeleton_source", "")),
        "skeleton_parser_mode": _bounded_text(
            getattr(summary, "skeleton_parser_mode", "")
        ),
        "skeleton_parse_warning": _bounded_text(
            getattr(summary, "skeleton_parse_warning", "")
        ),
        "invalid_row_count": int(getattr(summary, "invalid_row_count", 0) or 0),
        "unnormalized_vertex_count": int(
            getattr(summary, "unnormalized_vertex_count", 0) or 0
        ),
        "selected_bone_index": int(
            getattr(pose, "selected_bone_index", -1) if pose is not None else -1
        ),
        "selected_bone_name": _bounded_text(
            getattr(pose, "selected_bone_name", "") if pose is not None else ""
        ),
        "bone_count": len(bones),
        "bones_truncated": len(bones) > _SKELETON_STATE_MAX_BONES,
        "bones": [
            {
                "index": int(getattr(bone, "index", -1)),
                "name": _bounded_text(getattr(bone, "name", "")),
                "parent_index": int(getattr(bone, "parent_index", -1)),
                "parent_name": _bounded_text(getattr(bone, "parent_name", "")),
                "child_count": int(getattr(bone, "child_count", 0) or 0),
                "depth": int(getattr(bone, "depth", 0) or 0),
                "position": [float(value) for value in tuple(getattr(bone, "position", ()) or ())[:3]],
            }
            for bone in bones[:_SKELETON_STATE_MAX_BONES]
        ],
        "parts_truncated": len(parts) > _SKELETON_STATE_MAX_PARTS,
        "parts": [
            {
                "index": int(getattr(part, "index", -1)),
                "name": _bounded_text(getattr(part, "name", "")),
                "vertex_count": int(getattr(part, "vertex_count", 0) or 0),
                "skinned": bool(getattr(part, "skinned", False)),
                "weighted_vertex_count": int(
                    getattr(part, "weighted_vertex_count", 0) or 0
                ),
                "invalid_row_count": int(getattr(part, "invalid_row_count", 0) or 0),
            }
            for part in parts[:_SKELETON_STATE_MAX_PARTS]
        ],
        "selected_weights_truncated": (
            len(selected_weights) > _SKELETON_STATE_MAX_SELECTED_WEIGHTS
        ),
        "selected_vertex_weights": [
            {
                "submesh_index": int(getattr(row, "submesh_index", -1)),
                "vertex_index": int(getattr(row, "vertex_index", -1)),
                "influences": [
                    [
                        int(
                            (palette_slot_to_bone_index or {}).get(
                                int(bone_index),
                                int(bone_index),
                            )
                        ),
                        float(weight),
                    ]
                    for bone_index, weight in tuple(getattr(row, "influences", ()) or ())[:6]
                ] if resolved_influences else [],
                "influences_resolved": resolved_influences,
                "influence_slots": [
                    [int(slot), float(weight)]
                    for slot, weight in tuple(getattr(row, "influences", ()) or ())[:6]
                ],
                "influence_labels": [
                    [f"Slot {int(slot)}", float(weight)]
                    for slot, weight in tuple(getattr(row, "influences", ()) or ())[:6]
                ] if not resolved_influences else [],
                "selected_bone_weight": float(
                    (
                        sum(
                            float(weight)
                            for bone_index, weight in tuple(
                                getattr(row, "influences", ()) or ()
                            )
                            if selected_palette_slot is not None
                            and int(bone_index) == selected_palette_slot
                        )
                        if selected_palette_slot is not None
                        else getattr(row, "selected_bone_weight", 0.0)
                    )
                    or 0.0
                ),
                "total_weight": float(getattr(row, "total_weight", 0.0) or 0.0),
                "invalid": bool(getattr(row, "invalid", False)),
            }
            for row in selected_weights[:_SKELETON_STATE_MAX_SELECTED_WEIGHTS]
        ],
    }


def _validation_blockers(report: object) -> tuple[str, ...]:
    return tuple(
        str(getattr(item, "message", "") or item).strip()
        for item in tuple(getattr(report, "blockers", ()) or ())
        if str(getattr(item, "message", "") or item).strip()
    )


def _detach_shadow_layer_project(mesh: ParsedMesh, root: Path) -> None:
    del root  # The shadow intentionally has no project or autosave location.
    for attribute in (
        "_cdmw_mesh_layer_project_path",
        "_cdmw_modify_original_workspace_manifest_path",
        "_cdmw_modify_original_workspace_dir",
    ):
        if hasattr(mesh, attribute):
            setattr(mesh, attribute, "")


def _geometry_layer_seed(session: object) -> dict[str, object]:
    layers = tuple(copy.deepcopy(getattr(session, "geometry_layers", ())))
    return {
        "layers": [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "submesh_indices": tuple(layer.submesh_indices),
                "visible": layer.visible,
                "base": layer.base,
            }
            for layer in layers
        ],
        "active_layer_id": str(getattr(session, "active_geometry_layer_id", "base")),
        "copy_counter": int(getattr(session, "geometry_layer_copy_counter", 0) or 0),
        "layer_revision": int(getattr(session, "geometry_layer_revision", 0) or 0),
        "object_transform": copy.deepcopy(getattr(session, "object_transform")),
        "workspace_mode": str(getattr(session, "mesh_layer_workspace_mode", "") or ""),
        "loaded_generation": str(
            getattr(session, "mesh_layer_loaded_generation", "") or ""
        ),
    }


def _rigging_seed(session: object) -> dict[str, object]:
    return {
        "skeleton": copy.deepcopy(getattr(session, "skeleton", None)),
        "skeleton_source": str(getattr(session, "skeleton_source", "") or ""),
        "skeleton_resolution_reason": str(
            getattr(session, "skeleton_resolution_reason", "") or ""
        ),
        "skeleton_descriptor_source": str(
            getattr(session, "skeleton_descriptor_source", "") or ""
        ),
        "skeleton_variation_source": str(
            getattr(session, "skeleton_variation_source", "") or ""
        ),
        "animation_constraint_source": str(
            getattr(session, "animation_constraint_source", "") or ""
        ),
        "animation_constraint_evidence": copy.deepcopy(
            getattr(session, "animation_constraint_evidence", {}) or {}
        ),
        "socket_source": str(getattr(session, "socket_source", "") or ""),
        "pose_preview_enabled": bool(
            getattr(session, "pose_preview_enabled", False)
        ),
        "selected_bone_index": int(getattr(session, "selected_bone_index", -1)),
        "bone_pose_rotations": copy.deepcopy(
            getattr(session, "bone_pose_rotations", {}) or {}
        ),
        "animation_clip": copy.deepcopy(getattr(session, "animation_clip", None)),
        "animation_playback_enabled": bool(
            getattr(session, "animation_playback_enabled", False)
        ),
        "animation_time_seconds": float(
            getattr(session, "animation_time_seconds", 0.0) or 0.0
        ),
        "animation_loop": bool(getattr(session, "animation_loop", True)),
        "animation_speed": float(getattr(session, "animation_speed", 1.0) or 1.0),
    }


def _install_shadow_rigging_seed(
    service: MeshService,
    session_id: str,
    seed: Mapping[str, object],
) -> None:
    session = service._session(session_id)
    with session.export_lock:
        for key, value in seed.items():
            setattr(session, key, copy.deepcopy(value))


def _install_shadow_geometry_layer_seed(
    service: MeshService,
    session_id: str,
    seed: Mapping[str, object],
) -> None:
    session = service._session(session_id)
    with session.export_lock:
        layers = _geometry_layers_from_project_payload(
            {"layers": list(seed.get("layers", ()))},
            len(session.working_mesh.submeshes),
        )
        active_layer_id = str(seed.get("active_layer_id") or "base")
        if not any(layer.layer_id == active_layer_id for layer in layers):
            raise RustMeshAuthoringError(
                "CDMW Geometry Layers named an active layer that is not present."
            )
        session.geometry_layers = layers
        session.active_geometry_layer_id = active_layer_id
        session.geometry_layer_copy_counter = max(0, int(seed.get("copy_counter", 0) or 0))
        session.geometry_layer_revision = max(0, int(seed.get("layer_revision", 0) or 0))
        session.object_transform = copy.deepcopy(seed["object_transform"])
        session.native_clipboard_ready = False
        session.mesh_layer_project_path = None
        session.mesh_layer_workspace_manifest_path = None
        session.mesh_layer_workspace_mode = str(seed.get("workspace_mode") or "")
        session.mesh_layer_loaded_generation = str(seed.get("loaded_generation") or "")
        session.mesh_layer_autosave_saved_key = (
            session.revision,
            session.geometry_layer_revision,
        )


def _restore_authoritative_metadata(candidate: ParsedMesh, authoritative: ParsedMesh) -> None:
    operations = tuple(getattr(candidate, "_cdmw_edit_operations", ()) or ())
    requires_operations = bool(getattr(candidate, "_cdmw_requires_edit_operations", False))
    for name in tuple(vars(candidate)):
        if name.startswith("_cdmw_"):
            delattr(candidate, name)
    for name, value in vars(authoritative).items():
        if name.startswith("_cdmw_"):
            setattr(candidate, name, copy.deepcopy(value))
    setattr(candidate, "_cdmw_edit_operations", operations)
    setattr(candidate, "_cdmw_requires_edit_operations", requires_operations)


@dataclass(frozen=True, slots=True)
class _ShadowSettings:
    path: Path

    def fileName(self) -> str:  # noqa: N802 - mirrors QSettings' public contract
        return str(self.path)


def _copy_shadow_morph_profiles(
    authoritative_settings: object | None,
    session_root: Path,
) -> tuple[Path | None, str]:
    try:
        source = mesh_morph_profile_root(authoritative_settings)
    except RuntimeError:
        return None, _directory_fingerprint(None)
    destination = session_root / "mesh_slider_profiles"
    with mesh_morph_profile_lock(source):
        source_existed, source_files, base_fingerprint = _capture_owned_profile_tree(source)
        if source_existed:
            _write_owned_profile_tree(destination, source_files)
        if (
            _directory_fingerprint(source) != base_fingerprint
            or _directory_fingerprint(destination) != base_fingerprint
        ):
            if destination.is_dir():
                shutil.rmtree(destination)
            raise RustMeshValidationError(
                "Morph profiles changed while the shadow session was being created."
            )
    return source, base_fingerprint


def _directory_fingerprint(root: Path | None) -> str:
    return _capture_owned_profile_tree(root)[2]


@dataclass(slots=True)
class _MorphProfilePublication:
    source: Path
    shadow: Path
    expected_fingerprint: str
    shadow_expected_fingerprint: str
    staging: Path | None = None
    backup: Path | None = None
    published: bool = False
    published_fingerprint: str = ""
    source_existed: bool = False
    parent_identity: tuple[int, int] | None = None
    source_identity: tuple[int, int] | None = None
    staging_identity: tuple[int, int] | None = None
    staging_expected_fingerprint: str = ""
    backup_identity: tuple[int, int] | None = None
    published_identity: tuple[int, int] | None = None
    rejected: Path | None = None
    rejected_identity: tuple[int, int] | None = None
    rejected_fingerprint: str = ""

    def __post_init__(self) -> None:
        self.source = self.source.expanduser().absolute()
        self.shadow = self.shadow.expanduser().absolute()

    @staticmethod
    def _remove_exact_tree(
        path: Path | None,
        identity: tuple[int, int] | None,
        fingerprint: str,
    ) -> None:
        if path is None or identity is None or not os.path.lexists(path):
            return
        if (
            _mesh_history_directory_identity(path) != identity
            or _directory_fingerprint(path) != fingerprint
        ):
            raise RustMeshValidationError(
                "Morph profile cleanup found a replaced directory and left it untouched."
            )
        shutil.rmtree(path)

    def _require_prepared_parent(self, parent: Path, identity: tuple[int, int]) -> None:
        if self.parent_identity is None or identity != self.parent_identity:
            raise RustMeshValidationError(
                "Morph profile storage changed after Finish preparation; publication was rejected."
            )
        if _mesh_history_directory_identity(parent) != identity:
            raise RustMeshValidationError(
                "Morph profile storage changed during Finish; publication was rejected."
            )

    def _require_source_state(self) -> None:
        current_existed = os.path.lexists(self.source)
        if current_existed != self.source_existed:
            raise RustMeshValidationError(
                "Morph profiles changed outside Edit Mesh; Finish was rejected."
            )
        if current_existed and (
            self.source_identity is None
            or _mesh_history_directory_identity(self.source) != self.source_identity
        ):
            raise RustMeshValidationError(
                "Morph profile storage was replaced outside Edit Mesh; Finish was rejected."
            )
        if _directory_fingerprint(self.source) != self.expected_fingerprint:
            raise RustMeshValidationError(
                "Morph profiles changed outside Edit Mesh; Finish was rejected."
            )

    def _require_staging_state(self, *, phase: str) -> None:
        if (
            self.staging is None
            or self.staging_identity is None
            or not os.path.lexists(self.staging)
            or _mesh_history_directory_identity(self.staging)
            != self.staging_identity
            or _directory_fingerprint(self.staging)
            != self.staging_expected_fingerprint
        ):
            raise RustMeshValidationError(
                f"Morph profile staging changed {phase}; Finish was rejected."
            )

    def prepare(self) -> None:
        shadow_existed, shadow_files, _shadow_fingerprint = (
            _capture_owned_profile_tree(self.shadow)
        )
        if _shadow_fingerprint != self.shadow_expected_fingerprint:
            raise RustMeshValidationError(
                "Morph profiles changed outside an acknowledged command; Finish was rejected."
            )
        parent = self.source.parent
        parent.mkdir(parents=True, exist_ok=True)
        with _pinned_mesh_history_parent(parent) as parent_identity:
            self.parent_identity = parent_identity
            self.source_existed = os.path.lexists(self.source)
            if self.source_existed:
                self.source_identity = _mesh_history_directory_identity(self.source)
            self._require_source_state()
            self.staging = parent / f".{self.source.name}.rust-stage-{uuid4().hex}"
            try:
                if shadow_existed:
                    _write_owned_profile_tree(self.staging, shadow_files)
                else:
                    self.staging.mkdir()
                self.staging_identity = _mesh_history_directory_identity(self.staging)
                self.staging_expected_fingerprint = _directory_fingerprint(self.staging)
                self._require_staging_state(phase="during preparation")
                self._require_prepared_parent(parent, parent_identity)
                self._require_source_state()
            except Exception:
                try:
                    self._remove_exact_tree(
                        self.staging,
                        self.staging_identity,
                        self.staging_expected_fingerprint,
                    )
                except Exception:
                    pass
                raise

    def publish(self) -> None:
        if (
            self.staging is None
            or self.staging_identity is None
            or self.parent_identity is None
        ):
            raise RuntimeError("morph profile publication was not prepared")
        parent = self.source.parent
        with _pinned_mesh_history_parent(parent) as parent_identity:
            self._require_prepared_parent(parent, parent_identity)
            self._require_staging_state(phase="before publication")
            self._require_source_state()
            published_path = False
            try:
                if self.source_existed:
                    self.backup = parent / (
                        f".{self.source.name}.rust-backup-{uuid4().hex}"
                    )
                    self.backup_identity = self.source_identity
                    os.replace(self.source, self.backup)
                    if (
                        _mesh_history_directory_identity(self.backup)
                        != self.backup_identity
                    ):
                        raise RustMeshValidationError(
                            "Morph profile backup identity changed during publication."
                        )
                self._require_prepared_parent(parent, parent_identity)
                self._require_staging_state(phase="during publication")
                os.replace(self.staging, self.source)
                published_path = True
                self.published_identity = _mesh_history_directory_identity(self.source)
                self.published_fingerprint = _directory_fingerprint(self.source)
                if (
                    self.published_identity != self.staging_identity
                    or self.published_fingerprint
                    != self.staging_expected_fingerprint
                ):
                    raise RustMeshValidationError(
                        "Morph profile publication changed before validation; Finish was rejected."
                    )
                self._require_prepared_parent(parent, parent_identity)
            except Exception:
                if published_path and os.path.lexists(self.source):
                    try:
                        if (
                            _mesh_history_directory_identity(self.source)
                            == self.staging_identity
                        ):
                            self.rejected = parent / (
                                f".{self.source.name}.rust-rejected-{uuid4().hex}"
                            )
                            self.rejected_identity = self.staging_identity
                            os.replace(self.source, self.rejected)
                            if (
                                _mesh_history_directory_identity(self.rejected)
                                != self.rejected_identity
                            ):
                                raise RustMeshValidationError(
                                    "Morph profile rejection quarantine identity changed."
                                )
                            self.rejected_fingerprint = _directory_fingerprint(
                                self.rejected
                            )
                    except Exception:
                        pass
                if self.backup is not None and os.path.lexists(self.backup):
                    if os.path.lexists(self.source):
                        raise RustMeshValidationError(
                            "Morph profile rollback found a replacement at the publication target."
                        )
                    if (
                        self.backup_identity is None
                        or _mesh_history_directory_identity(self.backup)
                        != self.backup_identity
                        or _directory_fingerprint(self.backup)
                        != self.expected_fingerprint
                    ):
                        raise RustMeshValidationError(
                            "Morph profile backup changed before rollback."
                        )
                    os.replace(self.backup, self.source)
                    if (
                        _mesh_history_directory_identity(self.source)
                        != self.source_identity
                        or _directory_fingerprint(self.source)
                        != self.expected_fingerprint
                    ):
                        raise RustMeshValidationError(
                            "Morph profile rollback validation failed."
                        )
                try:
                    self._remove_exact_tree(
                        self.rejected,
                        self.rejected_identity,
                        self.rejected_fingerprint,
                    )
                except Exception:
                    pass
                raise
            self.published = True

    def rollback(self) -> None:
        if self.parent_identity is None:
            raise RuntimeError("morph profile publication was not prepared")
        parent = self.source.parent
        with _pinned_mesh_history_parent(parent) as parent_identity:
            self._require_prepared_parent(parent, parent_identity)
            if self.published:
                if (
                    not os.path.lexists(self.source)
                    or self.published_identity is None
                    or _mesh_history_directory_identity(self.source)
                    != self.published_identity
                    or _directory_fingerprint(self.source)
                    != self.published_fingerprint
                ):
                    raise RustMeshValidationError(
                        "Morph profiles changed after publication; automatic rollback was rejected."
                    )
                self.rejected = parent / (
                    f".{self.source.name}.rust-rejected-{uuid4().hex}"
                )
                self.rejected_identity = self.published_identity
                self.rejected_fingerprint = self.published_fingerprint
                os.replace(self.source, self.rejected)
                quarantine_error: Exception | None = None
                try:
                    if (
                        _mesh_history_directory_identity(self.rejected)
                        != self.rejected_identity
                    ):
                        raise RustMeshValidationError(
                            "Morph profile rollback quarantine identity changed."
                        )
                except Exception as exc:
                    # The published entry has already left the authoritative
                    # path. Restore the trusted backup before surfacing a
                    # post-move verification failure.
                    quarantine_error = exc
            else:
                quarantine_error = None
            if self.backup is not None and os.path.lexists(self.backup):
                if os.path.lexists(self.source):
                    raise RustMeshValidationError(
                        "Morph profile rollback target was unexpectedly replaced."
                    )
                if (
                    self.backup_identity is None
                    or _mesh_history_directory_identity(self.backup)
                    != self.backup_identity
                    or _directory_fingerprint(self.backup)
                    != self.expected_fingerprint
                ):
                    raise RustMeshValidationError(
                        "Morph profile backup changed before rollback."
                    )
                os.replace(self.backup, self.source)
                if (
                    _mesh_history_directory_identity(self.source)
                    != self.source_identity
                    or _directory_fingerprint(self.source)
                    != self.expected_fingerprint
                ):
                    raise RustMeshValidationError(
                        "Morph profile rollback validation failed."
                    )
            self._require_prepared_parent(parent, parent_identity)
            if quarantine_error is not None:
                raise quarantine_error
            self.published = False
            self.published_fingerprint = ""
            self.published_identity = None
            try:
                self._remove_exact_tree(
                    self.rejected,
                    self.rejected_identity,
                    self.rejected_fingerprint,
                )
            except Exception:
                pass

    def finalize(self) -> None:
        if self.parent_identity is None:
            return
        parent = self.source.parent
        with _pinned_mesh_history_parent(parent) as parent_identity:
            self._require_prepared_parent(parent, parent_identity)
            self._remove_exact_tree(
                self.staging,
                self.staging_identity,
                self.staging_expected_fingerprint,
            )
            self._remove_exact_tree(
                self.backup,
                self.backup_identity,
                self.expected_fingerprint,
            )
            self._remove_exact_tree(
                self.rejected,
                self.rejected_identity,
                self.rejected_fingerprint,
            )


def _capture_shadow_session_seed(authoritative_service: MeshService, authoritative_session):
    with authoritative_session.export_lock:
        authoritative_view = authoritative_service._session_view_locked(
            authoritative_session
        )
        shadow_mesh = authoritative_service._working_mesh_locked(
            authoritative_session,
            clone=True,
        )
        geometry_layer_seed = _geometry_layer_seed(authoritative_session)
        geometry_layer_seed["archive_refit_context"] = authoritative_session.archive_refit_context
        rigging_seed = _rigging_seed(authoritative_session)
        base_morph_session_revision = max(
            0,
            int(authoritative_session.morph_session_revision),
        )
        authoritative_morph_state = (
            authoritative_service._capture_morph_session_state_locked(
                authoritative_session
            )
        )
    return (
        authoritative_view, shadow_mesh, geometry_layer_seed, rigging_seed,
        base_morph_session_revision, authoritative_morph_state,
    )


def _prepare_shadow_mesh_materials(
    shadow_mesh: ParsedMesh,
    preview_context: object,
    texture_unavailable_reason: str,
    stop_event: threading.Event | None,
) -> tuple[int, str]:
    preview_material_binding_count = 0
    preview_model = getattr(preview_context, "preview_model", None)
    if preview_model is not None:
        preview_material_binding_count = copy_dotnet_preview_material_bindings(
            shadow_mesh,
            preview_model,
        )
        if preview_material_binding_count <= 0:
            texture_unavailable_reason = (
                texture_unavailable_reason
                or "Resolved Archive Browser material context did not match any editable mesh parts."
            )
        else:
            _rebased, package_reason = _rebase_rust_preview_texture_paths(
                shadow_mesh,
                getattr(preview_context, "material_package_path", ""),
                stop_event=stop_event,
            )
            if package_reason:
                texture_unavailable_reason = (
                    texture_unavailable_reason or package_reason
                )
    archive_texture_count = _resolve_rust_archive_texture_fallbacks(
        shadow_mesh,
        preview_context,
        stop_event=stop_event,
    )
    if archive_texture_count > 0:
        preview_material_binding_count = max(
            preview_material_binding_count,
            count_dotnet_own_material_bindings(shadow_mesh),
        )
        texture_unavailable_reason = ""
    else:
        texture_unavailable_reason = (
            concise_rust_texture_unavailable_reason(
                texture_unavailable_reason
            )
            or texture_unavailable_reason
        )
    return preview_material_binding_count, texture_unavailable_reason


def _configure_shadow_session_seed(
    shadow_service: MeshService,
    shadow_view,
    geometry_layer_seed,
    rigging_seed,
    authoritative_morph_state,
    authoritative_view,
):
    shadow_service._session(shadow_view.session_id).archive_refit_context = geometry_layer_seed.get("archive_refit_context")
    _install_shadow_geometry_layer_seed(
        shadow_service,
        shadow_view.session_id,
        geometry_layer_seed,
    )
    _install_shadow_rigging_seed(
        shadow_service,
        shadow_view.session_id,
        rigging_seed,
    )
    shadow_service.install_morph_session_state(
        shadow_view.session_id,
        authoritative_morph_state,
    )
    shadow_service.prime_morph_profile_cache(
        shadow_view.session_id,
        freeze=True,
    )
    shadow_view = shadow_service.configure_output_policy(
        shadow_view.session_id,
        authoritative_view.output_policy,
        output_destination=authoritative_view.output_destination,
    )
    return shadow_view


def _dispose_shadow_morph_seed(authoritative_service: MeshService, authoritative_morph_state):
    try:
        authoritative_service.dispose_morph_session_state(
            authoritative_morph_state
        )
    except Exception:
        try:
            authoritative_service.defer_morph_session_state_disposal(
                authoritative_morph_state
            )
        except Exception:
            pass


@dataclass(slots=True)
class RustMeshAuthoringSession:
    authoritative_service: MeshService
    authoritative_session_id: str
    shadow_service: MeshService
    shadow_session_id: str
    root: Path
    root_identity: tuple[int, int]
    session_id: str
    process_generation: int
    base_revision: int
    base_geometry_layer_revision: int
    base_morph_session_revision: int
    source_weights_available: bool
    manifest_path: Path
    theme: Mapping[str, object]
    preview_material_binding_count: int = 0
    texture_resource_count: int = 0
    archive_refit_material_cache: dict[str, dict[str, object]] = field(default_factory=dict)
    archive_refit_material_references: dict[str, dict[str, object]] = field(default_factory=dict)
    texture_unavailable_reason: str = ""
    material_package_path: str = ""
    authoritative_morph_root: Path | None = None
    morph_profile_base_fingerprint: str = ""
    acknowledged_morph_profile_fingerprint: str = ""
    max_state_document_bytes: int = 0
    closed: bool = False
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _lifecycle_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _protocol_lock: object = field(default_factory=threading.RLock, repr=False)
    _commit_started: bool = field(default=False, repr=False)
    _finish_accepted: bool = field(default=False, repr=False)
    _profile_tree_tainted: bool = field(default=False, repr=False)



    @classmethod
    def create(
        cls,
        authoritative_controller: object,
        root: Path | str,
        *,
        process_generation: int,
        theme: Mapping[str, object] | None = None,
        stop_event: threading.Event | None = None,
    ) -> "RustMeshAuthoringSession":
        if stop_event is not None and stop_event.is_set():
            raise RustMeshCancellationError("Mesh session preparation was cancelled")
        session_root = Path(root).resolve()
        session_root.mkdir(parents=True, exist_ok=False)
        root_identity = _session_root_identity(session_root)
        authoritative_service = getattr(authoritative_controller, "mesh_service", None)
        authoritative_session_id = str(
            getattr(authoritative_controller, "active_session_id", "") or ""
        )
        if not isinstance(authoritative_service, MeshService) or not authoritative_session_id:
            raise RustMeshAuthoringError("CDMW has no authoritative Mesh Edit session")
        authoritative_session = authoritative_service._session(authoritative_session_id)
        preview_context = getattr(
            authoritative_controller,
            _RUST_PREVIEW_MATERIAL_CONTEXT_ATTR,
            None,
        )
        texture_unavailable_reason = str(
            getattr(preview_context, "unavailable_reason", "") or ""
        ).strip()
        (
            authoritative_view, shadow_mesh, geometry_layer_seed, rigging_seed,
            base_morph_session_revision, authoritative_morph_state,
        ) = _capture_shadow_session_seed(authoritative_service, authoritative_session)
        try:
            shadow_mesh.active_lod_index = authoritative_view.lod_index
            if geometry_layer_seed.get("archive_refit_context") is None:
                preview_material_binding_count, texture_unavailable_reason = _prepare_shadow_mesh_materials(
                    shadow_mesh, preview_context, texture_unavailable_reason, stop_event,
                )
            else:
                preview_material_binding_count = count_dotnet_own_material_bindings(shadow_mesh)
            if stop_event is not None and stop_event.is_set():
                raise RustMeshCancellationError(
                    "Mesh session preparation was cancelled"
                )
            _detach_shadow_layer_project(shadow_mesh, session_root)
            (
                authoritative_morph_root,
                morph_profile_base_fingerprint,
            ) = _copy_shadow_morph_profiles(
                authoritative_service.settings,
                session_root,
            )
            session_id = f"rust-mesh:{uuid4()}"
            shadow_service = MeshService(
                settings=_ShadowSettings(session_root / "settings.ini"),
                max_history=authoritative_service.max_history,
                max_history_bytes=authoritative_service.max_history_bytes,
            )
            shadow_view = shadow_service.open_edit_session(
                shadow_mesh,
                session_id=f"{session_id}:shadow",
                mode=authoritative_view.mode,
                load_layer_project=False,
                adopt_owned_mesh=True,
            )
        except Exception:
            _dispose_shadow_morph_seed(authoritative_service, authoritative_morph_state)
            try:
                _cleanup_failed_session_root(session_root, root_identity)
            except Exception:
                pass
            raise
        try:
            shadow_view = _configure_shadow_session_seed(
                shadow_service, shadow_view, geometry_layer_seed, rigging_seed,
                authoritative_morph_state, authoritative_view,
            )
            instance = cls(
                authoritative_service=authoritative_service,
                authoritative_session_id=authoritative_session_id,
                shadow_service=shadow_service,
                shadow_session_id=shadow_view.session_id,
                root=session_root,
                root_identity=root_identity,
                session_id=session_id,
                process_generation=max(1, int(process_generation)),
                base_revision=int(authoritative_view.revision),
                base_geometry_layer_revision=max(
                    0,
                    int(geometry_layer_seed.get("layer_revision", 0) or 0),
                ),
                base_morph_session_revision=base_morph_session_revision,
                source_weights_available=_source_weights_available(
                    shadow_service._session(shadow_view.session_id).base_mesh
                ),
                manifest_path=session_root / "manifest.json",
                theme=dict(theme or {}),
                preview_material_binding_count=preview_material_binding_count,
                texture_unavailable_reason=texture_unavailable_reason,
                material_package_path=str(
                    getattr(preview_context, "material_package_path", "") or ""
                ).strip(),
                authoritative_morph_root=authoritative_morph_root,
                morph_profile_base_fingerprint=morph_profile_base_fingerprint,
                acknowledged_morph_profile_fingerprint=morph_profile_base_fingerprint,
            )
            if authoritative_morph_root is not None:
                (authoritative_morph_root.parent / "mesh_presets").mkdir(parents=True, exist_ok=True)
            instance._write_initial_manifest(stop_event=stop_event)
            _validate_owned_session_tree(session_root, root_identity)
            return instance
        except Exception:
            try:
                shadow_service.close_edit_session(
                    shadow_view.session_id,
                    force_without_saving=True,
                )
            except Exception:
                pass
            try:
                _cleanup_failed_session_root(session_root, root_identity)
            except Exception:
                pass
            raise
        finally:
            _dispose_shadow_morph_seed(authoritative_service, authoritative_morph_state)

    def _require_open(self) -> None:
        if self.closed:
            raise RustMeshProtocolError("Mesh authoring session is closed")

    def request_cancel(self) -> bool:
        """Linearize Cancel ahead of Finish when publication has not started.

        Returning ``False`` means the atomic authoritative commit already owns
        the publication boundary.  Callers must then wait for its terminal
        result and must not report that the authoritative mesh was unchanged.
        """

        with self._lifecycle_lock:
            if self._finish_accepted or self._commit_started:
                return False
            self._cancel_event.set()
            return True

    def _raise_if_cancelled(
        self,
        stop_event: threading.Event | None = None,
    ) -> None:
        if self._cancel_event.is_set() or (stop_event is not None and stop_event.is_set()):
            raise RustMeshCancellationError(
                "Edit Mesh Finish was cancelled before authoritative publication."
            )

    def _require_authoring_enabled(self, operation: str) -> None:
        view = self.shadow_service.session_view(self.shadow_session_id)
        if view.authoring_enabled:
            return
        reason = str(view.output_policy_reason or "").strip()
        raise RustMeshValidationError(
            reason or f"Edit Mesh cannot {operation} under the current output policy."
        )

    @_with_pinned_session_root
    def _write_mesh_document(self, name: str) -> dict[str, object]:
        # Session preparation owns this shadow exclusively until the manifest
        # is complete, so another full geometry clone only delays first paint.
        mesh = self.shadow_service.working_mesh(self.shadow_session_id, clone=False)
        if _STATE_FILE_RE.fullmatch(name) is not None:
            reference = _atomic_write_state_payload(
                self.root,
                name,
                _mesh_document_payload(mesh),
                element_count=sum(len(level) for level in _mesh_lods(mesh)),
                expected_root_identity=self.root_identity,
            )
            self.max_state_document_bytes = max(
                self.max_state_document_bytes,
                int(reference["byte_length"]),
            )
            return reference
        reference = _atomic_write_payload(
            self.root,
            name,
            _mesh_document_payload(mesh),
            expected_root_identity=self.root_identity,
        )
        self.max_state_document_bytes = max(
            self.max_state_document_bytes,
            int(reference["byte_length"]),
        )
        return reference

    def _preflight_mesh_document_capacity(
        self,
        mesh: ParsedMesh,
        *,
        expansion_factor: int = 1,
    ) -> int:
        data_length = len(_canonical_json_bytes(_mesh_document_payload(mesh)))
        projected_length = max(
            self.max_state_document_bytes,
            data_length * max(1, int(expansion_factor)),
        )
        if projected_length > RUST_MESH_MAX_PAYLOAD_BYTES:
            raise RustMeshProtocolError(
                "Mesh command would exceed the 512 MiB state payload limit"
            )
        entry_count, total_bytes = _projected_state_payload_usage(
            self.root,
            projected_length,
            expected_root_identity=self.root_identity,
        )
        if entry_count > _SESSION_MAX_ENTRIES:
            raise RustMeshProtocolError("Mesh session contains too many owned entries")
        if total_bytes > _SESSION_MAX_TOTAL_BYTES:
            raise RustMeshProtocolError(
                "Mesh command would exceed the 768 MiB aggregate limit"
            )
        return data_length

    def _preflight_current_command_document(self, command: str) -> None:
        factor = 1
        if command == "layer_paste":
            factor = 4
        elif command.startswith("morph_") or command.startswith("refit_"):
            factor = 2
        mesh = self.shadow_service.working_mesh(self.shadow_session_id, clone=False)
        self._preflight_mesh_document_capacity(mesh, expansion_factor=factor)

    def _preflight_topology_command(self, command: MeshEditCommand) -> int:
        """Run topology against a disposable clone, then admit its exact result."""

        source_mesh = self.shadow_service.working_mesh(
            self.shadow_session_id,
            clone=True,
        )
        source_topology = _mesh_topology_counts(source_mesh)
        preflight_service = MeshService(
            max_history=1,
            max_history_bytes=self.shadow_service.max_history_bytes,
        )
        preflight_session_id = f"{self.session_id}:topology-preflight:{uuid4()}"
        preflight_service.open_edit_session(
            source_mesh,
            session_id=preflight_session_id,
            mode="edit",
            load_layer_project=False,
        )
        try:
            preflight_service.apply_command(preflight_session_id, command)
            candidate = preflight_service.working_mesh(
                preflight_session_id,
                clone=False,
            )
            if (
                command.action == "generate_tangents"
                and self.shadow_service.session_view(
                    self.shadow_session_id
                ).output_policy
                == MeshOutputPolicy.EXACT_GAME_ASSET.value
                and _mesh_topology_counts(candidate) != source_topology
            ):
                raise RustMeshValidationError(
                    "Generate Tangents would split vertices and cannot be written by Exact "
                    "PAC output. Choose Free Edit before generating tangents for this mesh."
                )
            return self._preflight_mesh_document_capacity(candidate)
        finally:
            preflight_service.close_edit_session(
                preflight_session_id,
                force_without_saving=True,
            )

    def _require_mesh_action_policy(
        self,
        action: str,
        params: Mapping[str, object],
    ) -> None:
        view = self.shadow_service.session_view(self.shadow_session_id)
        capability_key = (
            "uv_auto_unwrap"
            if action == "uv_transform"
            and _command_truthy(params.get("auto_uv", False))
            else action
        )
        capability = action_authoring_capability(
            capability_key,
            mesh_format=view.mesh_format,
            lod_index=view.lod_index,
            output_policy=view.output_policy,
            free_edit_destination_ready=view.output_destination_ready,
        )
        if capability is None or capability.authorable:
            return
        reason = " ".join(
            part
            for part in (capability.reason, capability.detail)
            if str(part).strip()
        )
        raise RustMeshValidationError(
            reason or f"Edit Mesh cannot run {action} under the current output policy."
        )

    def _mesh_action_command(self, args: Mapping[str, object]) -> MeshEditCommand:
        _require_argument_keys(args, _RUST_MESH_ACTION_ARGUMENTS, "mesh_action")
        action = str(args.get("action", "") or "").strip().lower()
        allowed_params = _HOST_MESH_ACTION_PARAMS.get(action)
        if allowed_params is None:
            raise RustMeshProtocolError(
                f"Unsupported Mesh authoring action: {action or '(empty)'}"
            )
        raw_params = args.get("params", {})
        if not isinstance(raw_params, Mapping):
            raise RustMeshProtocolError("Mesh authoring action params must be an object")
        params = {str(key): value for key, value in raw_params.items()}
        unexpected_params = sorted(set(params) - allowed_params)
        if unexpected_params:
            raise RustMeshProtocolError(
                "Mesh authoring action received unsupported params: "
                + ", ".join(unexpected_params)
            )
        selection = _require_explicit_selection(
            self.shadow_service,
            self.shadow_session_id,
            args.get("selection"),
        )
        self._require_mesh_action_policy(action, params)
        if action == "copy_normals":
            session = self.shadow_service._session(self.shadow_session_id)
            with session.export_lock:
                params["source_mesh"] = copy.deepcopy(session.base_mesh)
        label_value = args.get("label", "")
        if label_value is not None and not isinstance(label_value, str):
            raise RustMeshProtocolError("Mesh authoring action label must be text")
        label = str(label_value or "").strip()
        if len(label) > 128:
            raise RustMeshProtocolError(
                "Mesh authoring action label exceeds the 128-character limit"
            )
        return MeshEditCommand(
            action,
            selection=selection,
            params=params,
            mode="edit",
            label=label or action.replace("_", " ").title(),
        )

    def _topology_command(self, args: Mapping[str, object]) -> MeshEditCommand:
        """Validate one integrated Rust topology request before native preflight."""

        _require_argument_keys(args, _RUST_TOPOLOGY_ARGUMENTS, "topology")
        action = str(args.get("action", "") or "").strip().lower()
        allowed_params = _HOST_TOPOLOGY_ACTION_PARAMS.get(action)
        if allowed_params is None:
            raise RustMeshProtocolError(
                f"Unsupported Mesh topology command: {action or '(empty)'}"
            )
        raw_params = args.get("params", {})
        if not isinstance(raw_params, Mapping):
            raise RustMeshProtocolError("Mesh topology params must be an object")
        params = {str(key): value for key, value in raw_params.items()}
        unexpected_params = sorted(set(params) - allowed_params)
        if unexpected_params:
            raise RustMeshProtocolError(
                "Mesh topology command received unsupported params: "
                + ", ".join(unexpected_params)
            )
        selection = _require_explicit_selection(
            self.shadow_service,
            self.shadow_session_id,
            args.get("selection"),
        )
        if action == "delete" and _command_truthy(params.get("delete_parts")):
            mesh = self.shadow_service.working_mesh(
                self.shadow_session_id,
                clone=False,
            )
            selected_parts = {
                int(index)
                for index in selection.source_indices
                if 0 <= int(index) < len(mesh.submeshes)
            }
            if not selected_parts:
                raise RustMeshValidationError(
                    "Delete Part requires at least one explicitly selected Part."
                )
            if len(selected_parts) >= len(mesh.submeshes):
                raise RustMeshValidationError(
                    "Delete Part cannot remove every Part because the editable mesh must retain geometry."
                )
        self._require_mesh_action_policy(action, params)
        label_value = args.get("label", "")
        if label_value is not None and not isinstance(label_value, str):
            raise RustMeshProtocolError("Mesh topology label must be text")
        label = str(label_value or "").strip()
        if len(label) > 128:
            raise RustMeshProtocolError(
                "Mesh topology label exceeds the 128-character limit"
            )
        return MeshEditCommand(
            action,
            selection=selection,
            params=params,
            mode="edit",
            label=label or action.replace("_", " ").title(),
        )

    def _apply_explicit_rig_selection(
        self,
        args: Mapping[str, object],
        *,
        allowed: frozenset[str],
        command: str,
    ) -> MeshEditSelection:
        _require_argument_keys(args, allowed, command)
        selection = _require_explicit_selection(
            self.shadow_service,
            self.shadow_session_id,
            args.get("selection"),
        )
        return selection

    def _run_rig_weight_command(
        self,
        command: str,
        args: Mapping[str, object],
    ) -> object:
        allowed = (
            _RUST_RIG_ADJUST_ARGUMENTS
            if command == "rig_adjust_weight"
            else _RUST_RIG_SELECTION_ARGUMENTS
        )
        selection = self._apply_explicit_rig_selection(
            args,
            allowed=allowed,
            command=command,
        )
        delta = (
            _finite_command_float(args.get("delta"), "rig weight delta")
            if command == "rig_adjust_weight"
            else 0.0
        )
        session = self.shadow_service._session(self.shadow_session_id)
        with session.export_lock:
            capability = _rust_skin_weight_capability(session)
            if not capability.enabled:
                raise RustMeshValidationError(capability.reason)
            selected_submeshes = set(selection.vertex_map()) | set(
                selection.source_indices
            )
            if not selected_submeshes:
                raise RustMeshValidationError(
                    "Select one or more vertices or whole parts before editing skin weights."
                )
            unsupported = sorted(
                selected_submeshes - set(capability.eligible_submesh_indices)
            )
            if unsupported:
                raise RustMeshValidationError(
                    "Skin-weight editing is unavailable for selected part(s): "
                    + ", ".join(str(index) for index in unsupported)
                    + ". The parts must retain the exact 40-byte PAC LOD 0 skin layout."
                )
            selected_bone_index = int(getattr(session, "selected_bone_index", -1))
            palette_slot = capability.skeleton_bone_to_palette_slot.get(
                selected_bone_index
            )
            if command == "rig_adjust_weight" and palette_slot is None:
                raise RustMeshValidationError(
                    "The selected skeleton bone is not present in the PAC bone palette."
                )
            before_rows = {
                submesh_index: (
                    tuple(
                        tuple(row or ())
                        for row in session.working_mesh.submeshes[
                            submesh_index
                        ].bone_indices
                    ),
                    tuple(
                        tuple(row or ())
                        for row in session.working_mesh.submeshes[
                            submesh_index
                        ].bone_weights
                    ),
                )
                for submesh_index in selected_submeshes
            }
            previous_selection = session.selection
            session.selection = selection
            try:
                if command == "rig_adjust_weight":
                    result = self.shadow_service.adjust_selected_vertex_bone_weight(
                        self.shadow_session_id,
                        delta,
                        bone_index=palette_slot,
                    )
                elif command == "rig_normalize_weights":
                    result = self.shadow_service.normalize_selected_vertex_weights(
                        self.shadow_session_id
                    )
                else:
                    result = self.shadow_service.transfer_selected_vertex_weights_from_source(
                        self.shadow_session_id
                    )
            except Exception:
                session.selection = previous_selection
                raise
            changed_submeshes = tuple(
                submesh_index
                for submesh_index in sorted(selected_submeshes)
                if before_rows[submesh_index]
                != (
                    tuple(
                        tuple(row or ())
                        for row in session.working_mesh.submeshes[
                            submesh_index
                        ].bone_indices
                    ),
                    tuple(
                        tuple(row or ())
                        for row in session.working_mesh.submeshes[
                            submesh_index
                        ].bone_weights
                    ),
                )
            )
            if changed_submeshes:
                invalid = tuple(
                    submesh_index
                    for submesh_index in changed_submeshes
                    if not _safe_pac_skin_rows(
                        session.working_mesh.submeshes[submesh_index],
                        len(
                            session.working_mesh.submeshes[
                                submesh_index
                            ].vertices
                        ),
                        len(capability.palette),
                    )
                )
                if invalid:
                    self.shadow_service.undo(self.shadow_session_id)
                    session.selection = previous_selection
                    raise RustMeshValidationError(
                        "Skin-weight edit produced a row outside the exact PAC contract; the edit was rolled back."
                    )
                operations = list(tuple(session.edit_operations))
                for submesh_index in changed_submeshes:
                    submesh = session.working_mesh.submeshes[submesh_index]
                    operations.append(
                        {
                            "operation": "replace_skin_weights_same_count",
                            "lod_index": 0,
                            "submesh_index": submesh_index,
                            "vertex_count": len(submesh.vertices or ()),
                            "source": RUST_MESH_EDIT_BACKEND,
                            "created_by": "CDMW Edit Mesh",
                            "metadata": {
                                "contract": "cdmw_exact_pac_skin_weights_v1",
                                "layout": PAC_SKIN_WEIGHT_LAYOUT,
                                "vertex_stride": 40,
                                "palette_size": len(capability.palette),
                                "service_action": command,
                            },
                        }
                    )
                session.edit_operations = tuple(operations)
            if previous_selection != selection:
                session.selection_revision += 1
            return result

    @_with_pinned_session_root
    def _write_initial_manifest(
        self,
        *,
        stop_event: threading.Event | None = None,
    ) -> None:
        mesh = self.shadow_service.working_mesh(self.shadow_session_id, clone=True)
        document = _atomic_write_payload(
            self.root,
            "document.json",
            _mesh_document_payload(mesh),
            data_type="mesh_document_json",
            element_count=sum(len(level) for level in _mesh_lods(mesh)),
            expected_root_identity=self.root_identity,
        )
        self.max_state_document_bytes = max(
            self.max_state_document_bytes,
            int(document["byte_length"]),
        )
        channels = _atomic_write_payload(
            self.root,
            "channels.json",
            _mesh_channel_payload(mesh),
            data_type="mesh_channels_compact_json",
            element_count=sum(
                len(tuple(getattr(submesh, "vertices", ()) or ()))
                for level in _mesh_lods(mesh)
                for submesh in level
            ),
            expected_root_identity=self.root_identity,
        )
        material_synthesis = _RustMaterialSynthesisState()
        textures = _mesh_texture_payloads(
            self.root,
            mesh,
            expected_root_identity=self.root_identity,
            stop_event=stop_event,
            synthesis_state=material_synthesis,
            material_package_path=(self.material_package_path if self.shadow_service._session(self.shadow_session_id).archive_refit_context is None else ""),
        )
        material_presentations = _mesh_material_presentations(
            mesh,
            generated_overrides=material_synthesis.presentation_overrides,
        )
        self.texture_resource_count = len(textures)
        material_key = getattr(self.shadow_service._session(self.shadow_session_id).archive_refit_context, "context_id", "base")
        self.archive_refit_material_cache[material_key] = {
            "key": material_key, "textures": textures, "material_presentations": material_presentations,
            "reason": self.texture_unavailable_reason,
        }
        if textures:
            self.texture_unavailable_reason = ""
        elif not self.texture_unavailable_reason:
            self.texture_unavailable_reason = (
                "Resolved Archive Browser material bindings did not contain readable DDS texture payloads."
                if self.preview_material_binding_count > 0
                else "No readable DDS preview textures were supplied by CDMW."
            )
        view = self.shadow_service.session_view(self.shadow_session_id)
        manifest = {
            "schema": RUST_MESH_AUTHORING_PACKAGE,
            "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "session_id": self.session_id,
            "process_generation": self.process_generation,
            "base_revision": self.base_revision,
            "shadow_revision": view.revision,
            "renderer": RUST_MESH_RENDERER,
            "edit_backend": RUST_MESH_EDIT_BACKEND,
            "document": document,
            "channels": channels,
            "textures": textures,
            "material_presentations": material_presentations,
            "texture_status": {
                "available": bool(textures),
                "resource_count": len(textures),
                "reason": self.texture_unavailable_reason,
                "material_synthesis": {
                    "attempted": material_synthesis.attempted,
                    "generated_binding_count": (
                        material_synthesis.generated_binding_count
                    ),
                    "degraded": bool(material_synthesis.diagnostics),
                    "fallback_count": len(material_synthesis.diagnostics)
                    + material_synthesis.dropped_diagnostic_count,
                    "warnings": list(material_synthesis.diagnostics),
                    "dropped_warning_count": material_synthesis.dropped_diagnostic_count,
                    "base_luminance_guard": {
                        "applied": bool(material_synthesis.luminance_guard_count),
                        "adjusted_owner_count": material_synthesis.luminance_guard_count,
                        "adjustments": list(
                            material_synthesis.luminance_guard_adjustments
                        ),
                        "dropped_adjustment_count": (
                            material_synthesis.dropped_luminance_guard_count
                        ),
                    },
                },
            },
            "source": {
                "path": str(mesh.path or ""),
                "format": str(mesh.format or ""),
                "sha256": _source_hash(mesh),
                "lod_index": int(view.lod_index),
            },
            "output_policy": {
                "policy": view.output_policy,
                "destination": view.output_destination,
                "destination_ready": view.output_destination_ready,
                "authoring_enabled": view.authoring_enabled,
                "exact_write_status": view.exact_write_status,
                "reason": view.output_policy_reason,
            },
            "theme": _json_safe(self.theme),
            "state": self.state_payload(include_document=False),
        }
        _atomic_write_payload(
            self.root,
            self.manifest_path.name,
            manifest,
            expected_root_identity=self.root_identity,
        )

    def validate_message_identity(self, payload: Mapping[str, object]) -> None:
        if str(payload.get("protocol", "") or "") != RUST_MESH_EDITOR_PROTOCOL:
            raise RustMeshProtocolError("Mesh protocol version does not match")
        if str(payload.get("session_id", "") or "") != self.session_id:
            raise RustMeshProtocolError("Mesh session id does not match")
        try:
            generation = int(payload.get("process_generation", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RustMeshProtocolError("Mesh process generation is invalid") from exc
        if generation != self.process_generation:
            raise RustMeshProtocolError("Mesh process generation is stale")

    def _require_shadow_revision(self, payload: Mapping[str, object]) -> int:
        try:
            expected = int(payload.get("base_revision", -1))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RustMeshProtocolError("Mesh base revision is invalid") from exc
        current = self.shadow_service.session_view(self.shadow_session_id).revision
        if expected != current:
            raise RustMeshProtocolError(
                f"Mesh request is stale: expected shadow revision {current}, received {expected}."
            )
        return current

    def _require_acknowledged_profile_tree(self) -> None:
        profile_root = self.root / "mesh_slider_profiles"
        with mesh_morph_profile_lock(profile_root):
            current = _directory_fingerprint(profile_root)
        if current == self.acknowledged_morph_profile_fingerprint:
            return
        session = self.shadow_service._session(self.shadow_session_id)
        with session.export_lock:
            if not self._profile_tree_tainted:
                session.revision += 1
                self._profile_tree_tainted = True
        raise RustMeshProtocolError(
            "Morph profiles changed outside an acknowledged CDMW command."
        )

    @_with_protocol_lock
    @_with_pinned_session_root
    def state_payload(self, *, include_document: bool = True) -> dict[str, object]:
        self._require_open()
        view = self.shadow_service.session_view(self.shadow_session_id)
        shadow_session = self.shadow_service._session(self.shadow_session_id)
        with shadow_session.export_lock:
            weight_edit_capability = _rust_skin_weight_capability(shadow_session)
        try:
            morph_state: object = self.shadow_service.cached_morph_state_from_runtime(
                self.shadow_session_id
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            morph_state = {"available": False, "reason": str(exc)}
        morph_payload = _json_safe(morph_state)
        if len(_canonical_json_bytes(morph_payload)) > _MORPH_STATE_MAX_BYTES:
            raise RustMeshProtocolError(
                "Mesh Morph state exceeds the 16 MiB inline protocol limit"
            )
        state: dict[str, object] = {
            "morph_preset_directory": str(
                self.authoritative_morph_root.parent / "mesh_presets"
                if self.authoritative_morph_root is not None else self.root / "mesh_presets"
            ),
            "session_id": self.session_id,
            "base_revision": view.revision,
            "authoritative_base_revision": self.base_revision,
            "authoritative_base_morph_revision": self.base_morph_session_revision,
            "mode": view.mode,
            "selection": _selection_payload(view.selection),
            "submesh_count": view.submesh_count,
            "vertex_count": view.vertex_count,
            "face_count": view.face_count,
            "undo_count": view.undo_count,
            "redo_count": view.redo_count,
            "history_cursor": view.history_cursor,
            "history_entries": _json_safe(view.history_entries),
            "mesh_format": view.mesh_format,
            "lod_index": view.lod_index,
            "output_policy": view.output_policy,
            "output_destination": view.output_destination,
            "output_destination_ready": view.output_destination_ready,
            "authoring_enabled": view.authoring_enabled,
            "exact_write_status": view.exact_write_status,
            "output_policy_reason": view.output_policy_reason,
            "selection_revision": view.selection_revision,
            "topology_generation": view.topology_generation,
            "geometry_layers": _json_safe(
                self.shadow_service.geometry_layer_state(self.shadow_session_id)
            ),
            "morph_refit": morph_payload,
            "loaded_mesh": Path(str(self.shadow_service._session(self.shadow_session_id).working_mesh.path)).name,
            "archive_refit_assets": [
                {"path": asset.entry.path, "role": asset.role, "part_indices": list(asset.part_indices)}
                for asset in getattr(self.shadow_service._session(self.shadow_session_id).archive_refit_context, "assets", ())
            ],
            "renderer": RUST_MESH_RENDERER,
            "edit_backend": RUST_MESH_EDIT_BACKEND,
        }
        if include_document:
            state["document"] = self._write_mesh_document(
                f"state-{view.revision}-{uuid4().hex[:10]}.json"
            )
        material_key = getattr(shadow_session.archive_refit_context, "context_id", "base")
        if material_key in self.archive_refit_material_references:
            state["archive_refit_materials"] = {"key": material_key, "file": self.archive_refit_material_references[material_key]}
        try:
            skeleton_summary = self.shadow_service.skeleton_summary(
                self.shadow_session_id
            )
            pose = getattr(skeleton_summary, "pose", None)
            selected_bone_index = int(
                getattr(pose, "selected_bone_index", -1)
                if pose is not None
                else -1
            )
            selected_palette_slot = weight_edit_capability.skeleton_bone_to_palette_slot.get(
                selected_bone_index
            )
            palette_slot_to_bone_index = {
                slot: bone_index
                for bone_index, slot in weight_edit_capability.skeleton_bone_to_palette_slot.items()
            }
            state["skeleton"] = _skeleton_state_payload(
                skeleton_summary,
                source_weights_available=self.source_weights_available,
                weight_edit_capability=weight_edit_capability.payload(),
                palette_slot_to_bone_index=palette_slot_to_bone_index,
                selected_palette_slot=selected_palette_slot,
            )
            from cdmw.services.mesh_rust_rig import selected_bone_influence

            with shadow_session.export_lock:
                state["rig_influence"] = selected_bone_influence(
                    shadow_session, selected_bone_index, weight_edit_capability.palette
                )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            state["skeleton"] = {
                "available": False,
                "source_weights_available": self.source_weights_available,
                "weight_edit_capability": weight_edit_capability.payload(),
                "reason": _bounded_text(exc),
            }
        return state

    @staticmethod
    def _shadow_protocol_signature_locked(session: object) -> tuple[object, ...]:
        return (
            int(getattr(session, "selection_revision", 0)),
            int(getattr(session, "geometry_layer_revision", 0)),
            int(getattr(session, "morph_session_revision", 0)),
            str(getattr(session, "output_policy", "")),
            str(getattr(session, "output_destination", "")),
            bool(getattr(session, "output_destination_ready", False)),
            bool(getattr(session, "native_clipboard_ready", False)),
            str(getattr(session, "active_geometry_layer_id", "")),
            tuple(getattr(session, "geometry_layers", ()) or ()),
            getattr(session, "object_transform", None),
            int(getattr(session, "selected_bone_index", -1)),
        )

    def _advance_shadow_protocol_revision(
        self,
        *,
        before_revision: int,
        before_signature: tuple[object, ...],
    ) -> int:
        session = self.shadow_service._session(self.shadow_session_id)
        with session.export_lock:
            after_signature = self._shadow_protocol_signature_locked(session)
            if (
                session.revision == int(before_revision)
                and after_signature != before_signature
            ):
                session.revision += 1
            return int(session.revision)

    def _apply_candidate_geometry(self, candidate, raw_submeshes, operations, active_lod_index):
        changed = False
        changed_submesh_indices: set[int] = set()
        invalidated_tangents: tuple[int, ...] = ()
        for submesh_index, (raw, target) in enumerate(zip(raw_submeshes, candidate.submeshes)):
            if not isinstance(raw, Mapping):
                raise RustMeshProtocolError("Mesh candidate submesh is malformed")
            positions = _finite_rows(raw.get("positions"), 3, "positions")
            normals = _finite_rows(raw.get("normals"), 3, "normals")
            uvs = _finite_rows(raw.get("uvs"), 2, "uvs")
            indices = _integer_values(raw.get("indices"), "indices")
            if len(positions) != len(target.vertices):
                raise RustMeshProtocolError("Mesh candidate changed vertex count outside CDMW topology")
            if normals and len(normals) != len(positions):
                raise RustMeshProtocolError("Mesh candidate normal count does not match positions")
            if uvs and len(uvs) != len(positions):
                raise RustMeshProtocolError("Mesh candidate UV count does not match positions")
            if indices != _submesh_indices(target):
                raise RustMeshProtocolError("Mesh candidate changed topology outside CDMW topology")
            channel_values = (
                ("replace_positions_same_count", "vertices", positions),
                ("replace_normals_same_count", "normals", normals),
                ("replace_uv0_same_count", "uvs", uvs),
            )
            for operation_name, attribute, values in channel_values:
                original = list(getattr(target, attribute, ()) or ())
                if not values or original == values:
                    continue
                values = _preserve_unchanged_rust_channel(original, values)
                if original == values:
                    continue
                setattr(target, attribute, values)
                operations.append(
                    {
                        "operation": operation_name,
                        "lod_index": active_lod_index,
                        "submesh_index": submesh_index,
                        "vertex_count": len(positions),
                        "source": RUST_MESH_EDIT_BACKEND,
                        "created_by": "CDMW Edit Mesh",
                    }
                )
                changed = True
                changed_submesh_indices.add(submesh_index)
        return changed, changed_submesh_indices, invalidated_tangents


    @_with_protocol_lock
    @_with_pinned_session_root
    def apply_candidate(self, request: Mapping[str, object]) -> dict[str, object]:
        self._require_open()
        self.validate_message_identity(request)
        self._require_shadow_revision(request)
        _validate_owned_session_tree(self.root, self.root_identity)
        self._require_acknowledged_profile_tree()
        shadow_session = self.shadow_service._session(self.shadow_session_id)
        with shadow_session.export_lock:
            before_revision = int(shadow_session.revision)
            before_signature = self._shadow_protocol_signature_locked(
                shadow_session
            )
        reference = request.get("candidate")
        if not isinstance(reference, Mapping):
            raise RustMeshProtocolError("Mesh transaction omitted its candidate reference")
        try:
            payload = read_owned_payload_reference(
                self.root,
                reference,
                candidate_only=True,
                expected_root_identity=self.root_identity,
            )
        finally:
            _discard_candidate_reference(
                self.root,
                reference,
                expected_root_identity=self.root_identity,
            )
        if str(payload.get("schema", "") or "") != RUST_MESH_CANDIDATE:
            raise RustMeshProtocolError("Mesh candidate schema does not match")
        if str(payload.get("session_id", "") or "") != self.session_id:
            raise RustMeshProtocolError("Mesh candidate belongs to another session")
        candidate = self.shadow_service.working_mesh(self.shadow_session_id, clone=True)
        active_lod_index = self.shadow_service.session_view(
            self.shadow_session_id
        ).lod_index
        selection = _selection_from_payload(payload.get("selection"))
        raw_submeshes = payload.get("submeshes")
        if not isinstance(raw_submeshes, list) or len(raw_submeshes) != len(candidate.submeshes):
            raise RustMeshProtocolError("Mesh candidate submesh count changed outside CDMW topology")
        with shadow_session.export_lock:
            operations = list(tuple(shadow_session.edit_operations))
            shadow_object_transform = copy.deepcopy(shadow_session.object_transform)
        (
            changed, changed_submesh_indices, invalidated_tangents,
        ) = self._apply_candidate_geometry(
            candidate, raw_submeshes, operations, active_lod_index,
        )
        if changed:
            self._require_authoring_enabled("apply geometry edits")
            invalidated_tangents = _invalidate_tangents_after_edit(
                candidate,
                "transform",
                changed_submesh_indices,
                {},
                topology_changed=False,
            )
            candidate.total_vertices = sum(len(item.vertices) for item in candidate.submeshes)
            candidate.total_faces = sum(len(item.faces) for item in candidate.submeshes)
            candidate.has_uvs = any(bool(item.uvs) for item in candidate.submeshes)
            candidate.has_bones = any(
                bool(item.bone_indices or item.bone_weights) for item in candidate.submeshes
            )
            setattr(candidate, "_cdmw_edit_operations", tuple(operations))
            setattr(candidate, "_cdmw_requires_edit_operations", True)
            prepared = self.shadow_service.prepare_working_mesh_replacement(
                self.shadow_session_id,
                candidate,
            )
            blockers = _validation_blockers(prepared.validation_report)
            if blockers:
                raise RustMeshValidationError(blockers[0])
            admitted_document_bytes = self._preflight_mesh_document_capacity(
                prepared.working_mesh
            )
            pruned_selection = _prune_selection_to_mesh(
                prepared.working_mesh,
                selection,
            )
            if pruned_selection != selection:
                raise RustMeshProtocolError(
                    "Mesh transaction selection contains invalid mesh elements"
                )
            prepared = replace(prepared, selection=selection)
            self.shadow_service.commit_prepared_working_mesh_replacement(
                prepared,
                history_action="rust_transaction",
                history_label=str(request.get("label", "") or "Edit Gesture"),
                object_transform=shadow_object_transform,
            )
            self.max_state_document_bytes = max(
                self.max_state_document_bytes,
                admitted_document_bytes,
            )
        elif not selection.is_empty() or not self.shadow_service.session_view(
            self.shadow_session_id
        ).selection.is_empty():
            self.shadow_service.apply_command(
                self.shadow_session_id,
                MeshEditCommand(
                    "select",
                    selection=selection,
                    params={"operation": "replace"},
                    mode="edit",
                ),
            )
        self._advance_shadow_protocol_revision(
            before_revision=before_revision,
            before_signature=before_signature,
        )
        state = self.state_payload(include_document=False)
        if changed and invalidated_tangents:
            state["operation_feedback"] = {
                "status": "ok",
                "diagnostics": [
                    "Invalidated tangents for "
                    f"{len(invalidated_tangents)} part(s); run Generate Tangents before export."
                ],
            }
        return state

    def _load_refit_mesh_command(self, args, stop_event):
        from cdmw.services.mesh_service_state import _MeshGeometryLayer

        service = self.shadow_service
        session_id = self.shadow_session_id
        session = service._session(session_id)
        with session.export_lock:
            if session.output_policy != MeshOutputPolicy.FREE_EDIT.value:
                raise RustMeshValidationError("Adding body or armor Parts requires Free Edit")
            service._require_baked_morph_definition_edit(session)
            morph_state = service.cached_morph_state_from_runtime(session_id)
            if morph_state.refit.garment_submesh_indices:
                raise RustMeshValidationError("Clear Refit before adding body or armor Parts")
            current = service.working_mesh(session_id, clone=True)
            role = str(args.get("role", ""))
            try:
                combined, indices = append_refit_mesh(
                    current, str(args.get("path", "")), role, stop_event=stop_event,
                )
            except RunCancelled as exc:
                raise RustMeshCancellationError("Mesh loading was cancelled before the scene changed") from exc
            self._raise_if_cancelled(stop_event)
            prepared = service.prepare_working_mesh_replacement(session_id, combined)
            blockers = _validation_blockers(prepared.validation_report)
            if blockers:
                raise RustMeshValidationError(f"Cannot add {role} mesh: {blockers[0]}")
            prepared = replace(prepared, selection=MeshEditSelection(source_indices=indices))
            admitted = self._preflight_mesh_document_capacity(prepared.working_mesh)
            morph = stage_refit_morph_runtime(service, session_id, prepared.working_mesh)
            try:
                layers = (*session.geometry_layers, _MeshGeometryLayer(
                    layer_id=f"refit-{uuid4().hex[:12]}",
                    name=f"{role.title()} / {Path(str(args.get('path', ''))).stem}",
                    submesh_indices=indices,
                ))
                self._raise_if_cancelled(stop_event)
                view = service.commit_prepared_working_mesh_replacement(
                    prepared, history_action="refit_load_mesh", history_label=f"Load Refit {role.title()}",
                    geometry_layers=layers, active_geometry_layer_id=layers[-1].layer_id,
                    morph_session_state=morph, require_reversible_history=True,
                )
            finally:
                try:
                    service.dispose_morph_session_state(morph)
                except RuntimeError:
                    service.defer_morph_session_state_disposal(morph)
            self.max_state_document_bytes = max(self.max_state_document_bytes, admitted)
            return {"session_id": view.session_id, "loaded_parts": indices, "role": role}

    def _import_editable_package_command(self, args, stop_event):
        raw_package_path = str(args.get("path", "") or "").strip()
        if not raw_package_path:
            raise RustMeshProtocolError("Editable package path is required")
        package_path = Path(raw_package_path).expanduser()
        mesh_path = _editable_package_mesh_path(package_path)
        if mesh_path.suffix.lower() not in {".glb", ".obj"}:
            raise RustMeshValidationError(
                "Edit Mesh can import editable GLB or OBJ packages only."
            )
        self._raise_if_cancelled(stop_event)
        imported_mesh = (
            import_glb_with_sidecar(mesh_path)
            if mesh_path.suffix.lower() == ".glb"
            else import_obj(
                str(mesh_path),
                sidecar_path=_editable_package_sidecar_path(mesh_path),
            )
        )
        self._raise_if_cancelled(stop_event)
        imported_prepared = self.shadow_service.prepare_working_mesh_replacement(
            self.shadow_session_id,
            imported_mesh,
        )
        admitted_document_bytes = self._preflight_mesh_document_capacity(
            imported_prepared.working_mesh
        )
        view = self.shadow_service.commit_prepared_working_mesh_replacement(
            imported_prepared,
        )
        self.max_state_document_bytes = max(
            self.max_state_document_bytes,
            admitted_document_bytes,
        )
        validation = self.shadow_service.validate_export(self.shadow_session_id)
        result = {
            "session_id": view.session_id,
            "mesh_revision": view.revision,
            "validation": validation,
        }
        return result


    def _undo_shadow_command(self):
        result = self._run_history_command("undo")
        return result


    def _execute_shadow_command(self, command, args, stop_event, before_revision, before_signature):
        if command == "undo":
            result = self.shadow_service.undo(self.shadow_session_id)
        elif command == "redo":
            result = self._run_history_command("redo")
        elif command == "select":
            result = self.shadow_service.apply_command(
                self.shadow_session_id,
                MeshEditCommand(
                    "select",
                    selection=_selection_from_payload(args.get("selection")),
                    params={"operation": str(args.get("operation", "replace") or "replace")},
                    mode="edit",
                ),
            )
        elif command == "topology":
            topology_command = self._topology_command(args)
            admitted_document_bytes = self._preflight_topology_command(
                topology_command
            )
            result = self.shadow_service.apply_command(
                self.shadow_session_id,
                topology_command,
            )
            self.max_state_document_bytes = max(
                self.max_state_document_bytes,
                admitted_document_bytes,
            )
        elif command == "mesh_action":
            mesh_command = self._mesh_action_command(args)
            if _mesh_action_requires_result_preflight(mesh_command):
                admitted_document_bytes = self._preflight_topology_command(mesh_command)
            else:
                current_mesh = self.shadow_service.working_mesh(
                    self.shadow_session_id,
                    clone=False,
                )
                admitted_document_bytes = self._preflight_mesh_document_capacity(
                    current_mesh,
                    expansion_factor=_mesh_action_capacity_factor(mesh_command),
                )
            result = self.shadow_service.apply_command(
                self.shadow_session_id,
                mesh_command,
            )
            self.max_state_document_bytes = max(
                self.max_state_document_bytes,
                admitted_document_bytes,
            )
        elif command == "rig_select_bone":
            _require_argument_keys(
                args,
                _RUST_RIG_SELECT_BONE_ARGUMENTS,
                command,
            )
            result = self.shadow_service.select_bone(
                self.shadow_session_id,
                _strict_command_index(args.get("bone_index"), "bone index"),
            )
        elif command in {
            "rig_adjust_weight",
            "rig_normalize_weights",
            "rig_transfer_weights",
        }:
            result = self._run_rig_weight_command(command, args)
        elif command == "configure_output_policy":
            result = self.shadow_service.configure_output_policy(
                self.shadow_session_id,
                str(args.get("policy", "") or ""),
                output_destination=str(args.get("destination", "") or ""),
            )
        elif command == "export_free_edit":
            result = self.shadow_service.export_free_edit_output(
                self.shadow_session_id,
                stop_event=stop_event,
            )
        elif command == "import_editable_package":
            result = self._import_editable_package_command(args, stop_event)
        elif command == "refit_load_mesh":
            result = self._load_refit_mesh_command(args, stop_event)
        elif command == "refit_choose_archive":
            from cdmw.services.mesh_rust_archive_refit import load_archive_refit
            result = load_archive_refit(self, args, stop_event)
        elif command == "layer_activate":
            result = self.shadow_service.activate_geometry_layer(
                self.shadow_session_id,
                str(args.get("layer_id", "") or ""),
            )
        elif command == "layer_rename":
            result = self.shadow_service.rename_geometry_layer(
                self.shadow_session_id,
                str(args.get("layer_id", "") or ""),
                str(args.get("name", "") or ""),
            )
        elif command == "layer_visibility":
            result = self.shadow_service.set_geometry_layer_visibility(
                self.shadow_session_id,
                str(args.get("layer_id", "") or ""),
                bool(args.get("visible", True)),
            )
        elif command == "layer_move":
            result = self.shadow_service.move_geometry_layer(
                self.shadow_session_id,
                str(args.get("layer_id", "") or ""),
                int(args.get("direction", 0) or 0),
            )
        elif command == "layer_delete":
            result = self.shadow_service.delete_geometry_layer(
                self.shadow_session_id,
                str(args.get("layer_id", "") or ""),
            )
        elif command == "layer_copy":
            result = self.shadow_service.copy_selection(
                self.shadow_session_id,
                target=str(args.get("target", "face") or "face"),
                selection=_selection_from_payload(args.get("selection")),
            )
        elif command == "layer_paste":
            result = self.shadow_service.paste_selection(self.shadow_session_id)
        elif command.startswith("morph_") or command.startswith("refit_"):
            try:
                result = self._run_bounded_morph_command(command, args)
            except Exception:
                self._advance_shadow_protocol_revision(
                    before_revision=before_revision,
                    before_signature=before_signature,
                )
                raise
        elif command == "state":
            result = {"status": "ok"}
        else:
            raise RustMeshProtocolError(f"Unsupported Mesh command: {command or '(empty)'}")
        return result


    @_with_protocol_lock
    @_with_pinned_session_root
    def run_command(
        self,
        request: Mapping[str, object],
        *,
        stop_event: threading.Event | None = None,
    ) -> dict[str, object]:
        self._require_open()
        self.validate_message_identity(request)
        self._require_shadow_revision(request)
        self._raise_if_cancelled(stop_event)
        _validate_owned_session_tree(self.root, self.root_identity)
        self._require_acknowledged_profile_tree()
        command = str(request.get("command", "") or "").strip().lower()
        arguments = request.get("arguments")
        args = dict(arguments) if isinstance(arguments, Mapping) else {}
        shadow_session = self.shadow_service._session(self.shadow_session_id)
        if shadow_session.archive_refit_context is not None and command in {
            "topology", "layer_delete", "layer_paste", "import_editable_package", "refit_load_mesh",
        }:
            raise RustMeshValidationError("Archive Refit preserves each source Part and topology; finish this refit before changing topology")
        with shadow_session.export_lock:
            before_revision = int(shadow_session.revision)
            before_signature = self._shadow_protocol_signature_locked(
                shadow_session
            )
        result: object
        if command not in {
            "select",
            "state",
            "configure_output_policy",
            "rig_select_bone",
        }:
            self._require_authoring_enabled(f"run {command or 'this command'}")
        if command in {
            "undo",
            "redo",
            "layer_delete",
            "layer_paste",
            "rig_adjust_weight",
            "rig_normalize_weights",
            "rig_transfer_weights",
        } or command.startswith("morph_") or command.startswith("refit_"):
            self._preflight_current_command_document(command)
        result = self._execute_shadow_command(command, args, stop_event, before_revision, before_signature)
        self._raise_if_cancelled(stop_event)
        after_revision = self._advance_shadow_protocol_revision(
            before_revision=before_revision,
            before_signature=before_signature,
        )
        # These commands change selection/presentation, not the resident mesh.
        # Protocol revisions still advance so stale requests remain rejected.
        state_only = command in {
            "select",
            "rig_select_bone",
            "configure_output_policy",
            "layer_activate",
            "layer_rename",
            "layer_visibility",
            "layer_move",
            "layer_copy",
        }
        state = self.state_payload(
            include_document=(
                command == "state" or (after_revision != before_revision and not state_only)
            )
        )
        return {"result": _json_safe(result), "state": state}

    def _run_history_command(self, command: str) -> object:
        service = self.shadow_service
        session = service._session(self.shadow_session_id)
        with session.export_lock:
            stack = session.undo_stack if command == "undo" else session.redo_stack
            changes_profiles = bool(stack and stack[-1].morph_profile_root is not None)
        if not changes_profiles:
            return service.undo(self.shadow_session_id) if command == "undo" else service.redo(
                self.shadow_session_id
            )
        profile_root = self.root / "mesh_slider_profiles"
        with mesh_morph_profile_lock(profile_root):
            result = (
                service.undo(self.shadow_session_id)
                if command == "undo"
                else service.redo(self.shadow_session_id)
            )
            self.acknowledged_morph_profile_fingerprint = _directory_fingerprint(
                profile_root
            )
            self._profile_tree_tainted = False
            return result

    def _run_bounded_morph_command(
        self,
        command: str,
        args: Mapping[str, object],
    ) -> object:
        file_commands = {
            "morph_import_preset",
            "morph_save_profile",
            "morph_delete_profile",
            "morph_save_preset",
            "morph_delete_preset",
        }
        if command not in file_commands:
            return self._run_morph_command(command, args)

        service = self.shadow_service
        session = service._session(self.shadow_session_id)
        profile_root = self.root / "mesh_slider_profiles"
        with session.export_lock, mesh_morph_profile_lock(profile_root):
            before_revision = int(session.revision)
            before_undo = {id(snapshot) for snapshot in session.undo_stack}
            before_redo = {id(snapshot) for snapshot in session.redo_stack}
            before_fingerprint = _directory_fingerprint(profile_root)
            result = self._run_morph_command(command, args)
            try:
                after_fingerprint = _directory_fingerprint(profile_root)
            except Exception as validation_error:
                new_undo = [
                    snapshot
                    for snapshot in session.undo_stack
                    if id(snapshot) not in before_undo
                ]
                if session.revision == before_revision or not new_undo:
                    raise RuntimeError(
                        "Morph profile limits were exceeded and the shadow transaction "
                        "could not be rolled back safely."
                    ) from validation_error
                service.undo(self.shadow_session_id)
                rejected_redo = [
                    snapshot
                    for snapshot in session.redo_stack
                    if id(snapshot) not in before_redo
                ]
                if rejected_redo:
                    rejected_ids = {id(snapshot) for snapshot in rejected_redo}
                    session.redo_stack[:] = [
                        snapshot
                        for snapshot in session.redo_stack
                        if id(snapshot) not in rejected_ids
                    ]
                    for snapshot in rejected_redo:
                        try:
                            _dispose_history_snapshot(snapshot)
                        except Exception:
                            pass
                try:
                    restored_fingerprint = _directory_fingerprint(profile_root)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Morph profile limits were exceeded and rollback validation failed."
                    ) from rollback_error
                if restored_fingerprint != before_fingerprint:
                    raise RuntimeError(
                        "Morph profile limits were exceeded and rollback did not restore "
                        "the prior shadow profile tree."
                    ) from validation_error
                raise validation_error
            if after_fingerprint != _directory_fingerprint(profile_root):
                raise RustMeshValidationError(
                    "Morph profiles changed while the command result was being finalized."
                )
            self.acknowledged_morph_profile_fingerprint = after_fingerprint
            self._profile_tree_tainted = False
            return result

    def _run_morph_command(self, command: str, args: Mapping[str, object]) -> object:
        service = self.shadow_service
        session_id = self.shadow_session_id
        if command == "morph_import_preset":
            return service.import_morph_preset(session_id, str(args.get("path", "")))
        if command == "morph_export_preset":
            path = Path(str(args.get("path", ""))).expanduser().resolve()
            if path.is_relative_to(self.root) or (
                self.authoritative_morph_root is not None and path.is_relative_to(self.authoritative_morph_root)
            ):
                raise RustMeshValidationError("Export presets outside the internal profile and edit-session folders")
            return service.export_morph_preset(session_id, str(path), str(args.get("name", "")))
        if command == "morph_activate":
            return service.activate_cached_morph_profile(
                session_id,
                args.get("profile_id"),
            )
        if command == "morph_create":
            definition = args.get("definition")
            session = service._session(session_id)
            with session.export_lock:
                previous_state = service.capture_morph_session_state(session_id)
                try:
                    profile = service.create_morph_definition(
                        session_id,
                        **(
                            dict(definition)
                            if isinstance(definition, Mapping)
                            else {}
                        ),
                    )
                    try:
                        activation_base_revision = int(
                            session.morph_session_revision
                        )
                        activation = service.activate_cached_morph_profile(
                            session_id,
                            profile.profile_id,
                        )
                    except Exception as command_error:
                        native_activation_accepted = (
                            int(session.morph_session_revision)
                            != activation_base_revision
                        )
                        try:
                            if native_activation_accepted:
                                service.install_morph_session_state(
                                    session_id,
                                    previous_state,
                                )
                            else:
                                service.restore_morph_session_cache_after_rejected_edit(
                                    session_id,
                                    previous_state,
                                    expected_revision=activation_base_revision,
                                )
                        except Exception as rollback_error:
                            raise RuntimeError(
                                "Morph definition creation failed and its runtime rollback also failed."
                            ) from rollback_error
                        if not native_activation_accepted:
                            raise command_error

                        # Restoring a Morph runtime intentionally clears
                        # resident history. Remove Python markers that referred
                        # to the destroyed native cursor before surfacing the
                        # command error.
                        invalid_native_markers: list[object] = []
                        for stack in (session.undo_stack, session.redo_stack):
                            retained = []
                            for snapshot in stack:
                                if snapshot.native_editor_history:
                                    invalid_native_markers.append(snapshot)
                                else:
                                    retained.append(snapshot)
                            stack[:] = retained
                        session.native_history_undo_count = 0
                        session.native_history_redo_count = 0
                        session.native_history_retained_bytes = 0
                        disposed: set[int] = set()
                        for snapshot in invalid_native_markers:
                            if id(snapshot) in disposed:
                                continue
                            disposed.add(id(snapshot))
                            try:
                                _dispose_history_snapshot(snapshot)
                            except Exception:
                                pass
                        raise command_error
                    return {"profile": profile, "activation": activation}
                finally:
                    try:
                        service.dispose_morph_session_state(previous_state)
                    except RuntimeError:
                        service.defer_morph_session_state_disposal(previous_state)
        if command == "morph_save_profile":
            return service.save_active_morph_profile(session_id)
        if command == "morph_delete_profile":
            return service.delete_morph_profile(session_id, args.get("profile_id"))
        if command == "morph_delete_definition":
            return service.delete_morph_definition(
                session_id,
                args.get("definition_id"),
            )
        if command == "morph_set_value":
            return service.set_morph_value(
                session_id,
                args.get("definition_id"),
                args.get("value"),
                phase=args.get("phase", "end"),
                change_id=args.get("change_id", ""),
            )
        if command == "morph_apply_preset":
            return service.apply_cached_morph_preset(
                session_id,
                args.get("preset_id"),
            )
        if command == "morph_save_preset":
            return service.save_morph_preset(
                session_id,
                args.get("preset_id"),
                args.get("name"),
            )
        if command == "morph_delete_preset":
            return service.delete_morph_preset(session_id, args.get("preset_id"))
        if command in {"refit_set_driver", "refit_use_loaded_body"}:
            from cdmw.services.mesh_rust_archive_refit import run_refit_driver_command
            return run_refit_driver_command(self, command, args)
        if command == "refit_bind":
            return service.bind_refit(session_id, tuple(args.get("submesh_indices", ()) or ()))
        if command == "refit_configure":
            return service.configure_refit(
                session_id,
                tuple(args.get("submesh_indices", ()) or ()),
                enabled=args.get("enabled", True),
                intensity_percent=args.get("intensity_percent", 100.0),
                mode=args.get("mode", "surface"),
                clearance_percent=args.get("clearance_percent", 0.0),
            )
        if command == "refit_clear":
            return service.clear_refit(session_id)
        if command == "morph_reset":
            return service.reset_morph(session_id)
        if command == "morph_bake":
            return service.bake_morph(session_id)
        raise RustMeshProtocolError(f"Unsupported Mesh morph command: {command}")

    def _validate_exact_output_writer(
        self,
        *,
        shadow_revision: int,
        stop_event: threading.Event | None,
        snapshot=None,
    ) -> dict[str, object]:
        """Prove the current shadow mesh through the existing exact writer.

        ``rebuild_result_from_snapshot`` produces bytes in memory and therefore
        cannot publish either the source asset or the authoritative edit
        session.  Running it before preparing the authoritative replacement
        makes the existing validator/writer the admission boundary for Exact
        Game Asset Finish, without a developer override or a free-edit path.
        """

        try:
            snapshot = snapshot or self.shadow_service.capture_export_snapshot(
                self.shadow_session_id,
                stop_event=stop_event,
                expected_mesh_revision=shadow_revision,
            )
            if snapshot.archive_refit_context is not None:
                from cdmw.services.mesh_archive_refit import archive_refit_snapshots
                assets = []
                for entry, component in archive_refit_snapshots(snapshot):
                    evidence = self._validate_exact_output_writer(
                        shadow_revision=shadow_revision, stop_event=stop_event, snapshot=component,
                    )
                    assets.append({"path": entry.path, **evidence})
                return {"status": "passed", "assets": assets, "fallback_used": False}
            result, report = self.shadow_service.rebuild_result_from_snapshot(snapshot)
        except Exception as exc:
            self._raise_if_cancelled(stop_event)
            raise RustMeshValidationError(
                f"Exact game-asset writer rejected Edit Mesh Finish: {exc}"
            ) from exc
        self._raise_if_cancelled(stop_event)

        validation_status = str(getattr(report, "validation_status", "") or "")
        if validation_status != "passed":
            raise RustMeshValidationError(
                "Exact game-asset writer did not return a passing validation report."
            )
        if tuple(getattr(report, "developer_overrides", ()) or ()):
            raise RustMeshValidationError(
                "Exact game-asset writer attempted to use a developer override."
            )
        topology_report = dict(getattr(report, "topology_rebuild", {}) or {})
        if topology_report and topology_report.get("fallback_used") is not False:
            raise RustMeshValidationError(
                "Exact game-asset topology writer did not prove that fallback was disabled."
            )

        rebuilt_data = bytes(getattr(result, "data", b"") or b"")
        rebuilt_hash = _sha256_bytes(rebuilt_data)
        source_hash = _sha256_bytes(snapshot.original_data)
        if not rebuilt_data:
            raise RustMeshValidationError("Exact game-asset writer returned no rebuilt bytes.")
        if int(getattr(report, "source_size", -1)) != len(snapshot.original_data):
            raise RustMeshValidationError(
                "Exact game-asset writer source-size evidence does not match the session snapshot."
            )
        if str(getattr(report, "source_asset_hash", "") or "").upper() != source_hash:
            raise RustMeshValidationError(
                "Exact game-asset writer source hash does not match the session snapshot."
            )
        if int(getattr(report, "rebuilt_size", -1)) != len(rebuilt_data):
            raise RustMeshValidationError(
                "Exact game-asset writer rebuilt-size evidence does not match its output."
            )
        if str(getattr(report, "rebuilt_asset_hash", "") or "").upper() != rebuilt_hash:
            raise RustMeshValidationError(
                "Exact game-asset writer rebuilt hash does not match its output."
            )

        return {
            "status": "passed",
            "mesh_format": str(getattr(report, "mesh_format", "") or ""),
            "source_asset_hash": source_hash,
            "rebuilt_asset_hash": rebuilt_hash,
            "source_size": len(snapshot.original_data),
            "rebuilt_size": len(rebuilt_data),
            "byte_identical": bool(getattr(report, "byte_identical", False)),
            "changed_range_count": int(getattr(report, "changed_range_count", 0)),
            "writer": str(topology_report.get("serializer") or "exact_same_count"),
            "fallback_used": False,
        }

    def _validate_free_edit_output_writer(
        self,
        *,
        shadow_revision: int,
        stop_event: threading.Event | None,
    ) -> dict[str, object]:
        """Prove the complete shadow through the existing non-exact writer."""

        try:
            snapshot = self.shadow_service.capture_export_snapshot(
                self.shadow_session_id,
                stop_event=stop_event,
                expected_mesh_revision=shadow_revision,
            )
            source_path = str(
                getattr(snapshot.base_mesh, "path", "")
                or getattr(snapshot.mesh, "path", "")
                or ""
            )
            with tempfile.TemporaryDirectory(prefix="cdmw-rust-free-edit-proof-") as proof_root:
                result = publish_free_edit_output(
                    snapshot,
                    Path(proof_root) / "validated-output",
                    source_path=source_path,
                    stop_event=stop_event,
                )
                validation = {
                    "status": "passed",
                    "writer": "free_edit_obj_reparse",
                    "vertex_count": result.vertex_count,
                    "face_count": result.face_count,
                    "exact_archive_writeback": False,
                    "fallback_used": False,
                }
        except Exception as exc:
            self._raise_if_cancelled(stop_event)
            raise RustMeshValidationError(
                f"Free Edit writer rejected Edit Mesh Finish: {exc}"
            ) from exc
        self._raise_if_cancelled(stop_event)
        return validation

    def _validate_free_edit_destination_at_finish(
        self,
        *,
        output_destination: str,
        output_destination_ready: bool,
    ) -> Path:
        """Revalidate the selected external destination at the Finish boundary."""

        raw_destination = str(output_destination or "").strip()
        if not output_destination_ready or not raw_destination:
            raise RustMeshValidationError(
                "Free Edit requires a valid new output folder before Finish."
            )
        target = Path(raw_destination).expanduser().resolve(strict=False)
        shadow_session = self.shadow_service._session(self.shadow_session_id)
        with shadow_session.export_lock:
            source_text = str(
                getattr(shadow_session.base_mesh, "path", "")
                or getattr(shadow_session.working_mesh, "path", "")
                or ""
            ).strip()
        source = (
            Path(source_text).expanduser().resolve(strict=False)
            if source_text
            else None
        )
        if source is not None and target == source:
            raise RustMeshValidationError(
                "Free Edit output must not overwrite the source asset."
            )
        if not target.parent.is_dir():
            raise RustMeshValidationError(
                f"Free Edit output parent folder no longer exists: {target.parent}"
            )
        if os.path.lexists(target):
            raise RustMeshValidationError(
                f"Free Edit output folder must still be new; the selected destination now exists: {target}"
            )
        return target

    def _complete_accepted_finish(
        self, cleanup_warnings, committed, validation_payload, shadow_morph_state, morph_publication,
        exact_output_validation, free_edit_output_validation,
    ):
        with self._lifecycle_lock:
            self._finish_accepted = True
            self._commit_started = False
        try:
            self.authoritative_service.set_morph_profile_cache_frozen(
                self.authoritative_session_id,
                False,
            )
        except Exception as exc:
            cleanup_warnings.append(str(exc))
        if shadow_morph_state is not None:
            try:
                self.shadow_service.dispose_morph_session_state(
                    shadow_morph_state
                )
            except Exception as exc:
                try:
                    self.shadow_service.defer_morph_session_state_disposal(
                        shadow_morph_state
                    )
                except Exception as defer_exc:
                    cleanup_warnings.append(
                        "Morph runtime cleanup is pending: "
                        f"{type(exc).__name__}: {exc}; defer failed: "
                        f"{type(defer_exc).__name__}: {defer_exc}"
                    )
                else:
                    cleanup_warnings.append(str(exc))
        if morph_publication is not None:
            try:
                morph_publication.finalize()
            except Exception as exc:
                cleanup_warnings.append(
                    f"Morph profile staging cleanup is pending: {exc}"
                )
        try:
            shadow_cleanup_warning = self._dispose_shadow()
        except Exception as exc:
            self.closed = True
            shadow_cleanup_warning = (
                f"shadow-session cleanup is pending: {type(exc).__name__}: {exc}"
            )
        if shadow_cleanup_warning:
            cleanup_warnings.append(shadow_cleanup_warning)
        result = {
            "status": "accepted",
            "authoritative_revision": committed.revision,
            "validation": validation_payload,
            "renderer": RUST_MESH_RENDERER,
            "edit_backend": RUST_MESH_EDIT_BACKEND,
        }
        if cleanup_warnings:
            result["warnings"] = tuple(dict.fromkeys(cleanup_warnings))
        if exact_output_validation is not None:
            result["exact_output_validation"] = exact_output_validation
        if free_edit_output_validation is not None:
            result["free_edit_output_validation"] = free_edit_output_validation
        return result


    def _prepare_finish_profile_publication(self, prepared, output_policy, output_destination, output_destination_ready, stop_event):
        shadow_morph_root = self.root / "mesh_slider_profiles"
        with mesh_morph_profile_lock(shadow_morph_root):
            shadow_morph_profile_state = _capture_owned_profile_tree(
                shadow_morph_root
            )
        shadow_morph_fingerprint = shadow_morph_profile_state[2]
        if shadow_morph_fingerprint != self.acknowledged_morph_profile_fingerprint:
            raise RustMeshProtocolError(
                "Morph profiles changed outside an acknowledged CDMW command."
            )
        morph_publication: _MorphProfilePublication | None = None
        morph_profile_previous_state: tuple[
            bool,
            tuple[tuple[str, bytes], ...],
            str,
        ] | None = None
        if shadow_morph_fingerprint != self.morph_profile_base_fingerprint:
            if self.authoritative_morph_root is None:
                raise RustMeshValidationError(
                    "Morph profile changes cannot be published because CDMW settings are unavailable."
                )
            with mesh_morph_profile_lock(self.authoritative_morph_root):
                morph_profile_previous_state = _mesh_morph_profile_directory_state(
                    self.authoritative_morph_root
                )
                if (
                    morph_profile_previous_state[2]
                    != self.morph_profile_base_fingerprint
                ):
                    raise RustMeshValidationError(
                        "Morph profiles changed outside Edit Mesh; Finish was rejected."
                    )
                morph_publication = _MorphProfilePublication(
                    source=self.authoritative_morph_root,
                    shadow=shadow_morph_root,
                    expected_fingerprint=self.morph_profile_base_fingerprint,
                    shadow_expected_fingerprint=shadow_morph_fingerprint,
                )
                morph_publication.prepare()
        cleanup_warnings: list[str] = []
        validation_payload = _json_safe(prepared.validation_report)
        try:
            self._raise_if_cancelled(stop_event)
            if output_policy == MeshOutputPolicy.FREE_EDIT.value:
                self._validate_free_edit_destination_at_finish(
                    output_destination=output_destination,
                    output_destination_ready=output_destination_ready,
                )
            with self._lifecycle_lock:
                self._raise_if_cancelled(stop_event)
                if self.closed:
                    raise RustMeshCancellationError(
                        "Edit Mesh closed before authoritative publication."
                    )
                self._commit_started = True
        except Exception:
            if morph_publication is not None:
                try:
                    morph_publication.finalize()
                except Exception:
                    pass
            raise
        return morph_publication, morph_profile_previous_state, shadow_morph_profile_state, cleanup_warnings, validation_payload


    def _prepare_finish_mesh(self, stop_event):
        authoritative_session = self.authoritative_service._session(
            self.authoritative_session_id
        )
        with authoritative_session.export_lock:
            if authoritative_session.revision != self.base_revision:
                raise RustMeshValidationError(
                    "The CDMW mesh changed while Edit Mesh was open; Finish was rejected."
                )
            if (
                authoritative_session.geometry_layer_revision
                != self.base_geometry_layer_revision
            ):
                raise RustMeshValidationError(
                    "The CDMW geometry layers changed while Edit Mesh was open; "
                    "Finish was rejected."
                )
            if (
                authoritative_session.morph_session_revision
                != self.base_morph_session_revision
            ):
                raise RustMeshValidationError(
                    "The CDMW Morph & Refit state changed while Edit Mesh was open; "
                    "Finish was rejected."
                )
        shadow_view = self.shadow_service.session_view(self.shadow_session_id)
        exact_output_validation: dict[str, object] | None = None
        free_edit_output_validation: dict[str, object] | None = None
        if shadow_view.output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value:
            shadow_report = self.shadow_service.validate_export(self.shadow_session_id)
            self._raise_if_cancelled(stop_event)
            blockers = _validation_blockers(shadow_report)
            if blockers:
                raise RustMeshValidationError(blockers[0])
            exact_output_validation = self._validate_exact_output_writer(
                shadow_revision=shadow_view.revision,
                stop_event=stop_event,
            )
        elif shadow_view.output_policy == MeshOutputPolicy.FREE_EDIT.value:
            self._validate_free_edit_destination_at_finish(
                output_destination=shadow_view.output_destination,
                output_destination_ready=shadow_view.output_destination_ready,
            )
            free_edit_output_validation = self._validate_free_edit_output_writer(
                shadow_revision=shadow_view.revision,
                stop_event=stop_event,
            )
        shadow_session = self.shadow_service._session(self.shadow_session_id)
        with shadow_session.export_lock:
            shadow_edit_operations = tuple(copy.deepcopy(shadow_session.edit_operations))
            shadow_requires_edit_operations = bool(shadow_session.requires_edit_operations)
            geometry_layers = copy.deepcopy(shadow_session.geometry_layers)
            active_geometry_layer_id = shadow_session.active_geometry_layer_id
            geometry_layer_copy_counter = shadow_session.geometry_layer_copy_counter
            object_transform = copy.deepcopy(shadow_session.object_transform)
            output_policy = shadow_session.output_policy
            output_destination = shadow_session.output_destination
            output_destination_ready = shadow_session.output_destination_ready
        candidate = self.shadow_service.working_mesh(self.shadow_session_id, clone=True)
        setattr(candidate, "_cdmw_edit_operations", shadow_edit_operations)
        setattr(candidate, "_cdmw_requires_edit_operations", shadow_requires_edit_operations)
        authoritative_mesh = self.authoritative_service.working_mesh(
            self.authoritative_session_id,
            clone=True,
        )
        _restore_authoritative_metadata(candidate, authoritative_mesh)
        prepared = self.authoritative_service.prepare_working_mesh_replacement(
            self.authoritative_session_id,
            candidate,
            validation_output_policy=shadow_view.output_policy,
            validation_output_destination=shadow_view.output_destination,
            validation_output_destination_ready=shadow_view.output_destination_ready,
            archive_refit_context=shadow_session.archive_refit_context,
        )
        if prepared.expected_revision != self.base_revision:
            raise RustMeshValidationError(
                "The CDMW mesh changed while Edit Mesh was open; Finish was rejected."
            )
        self._raise_if_cancelled(stop_event)
        blockers = _validation_blockers(prepared.validation_report)
        if blockers:
            raise RustMeshValidationError(blockers[0])
        return authoritative_session, prepared, geometry_layers, active_geometry_layer_id, geometry_layer_copy_counter, object_transform, output_policy, output_destination, output_destination_ready, exact_output_validation, free_edit_output_validation


    @_with_protocol_lock
    @_with_pinned_session_root
    def finish(
        self,
        request: Mapping[str, object],
        *,
        stop_event: threading.Event | None = None,
    ) -> dict[str, object]:
        self._require_open()
        self.validate_message_identity(request)
        self._require_shadow_revision(request)
        self._raise_if_cancelled(stop_event)
        _validate_owned_session_tree(self.root, self.root_identity)
        self._require_acknowledged_profile_tree()
        self._require_authoring_enabled("finish this session")
        (
            authoritative_session, prepared, geometry_layers, active_geometry_layer_id,
            geometry_layer_copy_counter, object_transform, output_policy, output_destination,
            output_destination_ready, exact_output_validation, free_edit_output_validation,
        ) = self._prepare_finish_mesh(
            stop_event,
        )
        (
            morph_publication, morph_profile_previous_state, shadow_morph_profile_state, cleanup_warnings,
            validation_payload,
        ) = self._prepare_finish_profile_publication(
            prepared, output_policy, output_destination, output_destination_ready, stop_event,
        )
        shadow_morph_state = None
        rollback_error: Exception | None = None
        try:
            shadow_morph_state = self.shadow_service.capture_morph_session_state(
                self.shadow_session_id
            )
            profile_lock_context = (
                mesh_morph_profile_lock(self.authoritative_morph_root)
                if morph_publication is not None
                and self.authoritative_morph_root is not None
                else nullcontext()
            )
            with authoritative_session.export_lock:
                with profile_lock_context:
                    try:
                        if morph_publication is not None:
                            morph_publication.publish()
                        committed = self.authoritative_service.commit_prepared_working_mesh_replacement(
                            prepared,
                            history_action="rust_edit_session",
                            history_label="Edit Session",
                            geometry_layers=geometry_layers,
                            active_geometry_layer_id=active_geometry_layer_id,
                            geometry_layer_copy_counter=geometry_layer_copy_counter,
                            object_transform=object_transform,
                            output_policy=output_policy,
                            output_destination=output_destination,
                            output_destination_ready=output_destination_ready,
                            expected_geometry_layer_revision=self.base_geometry_layer_revision,
                            expected_morph_session_revision=self.base_morph_session_revision,
                            morph_session_state=shadow_morph_state,
                            morph_profile_root=(
                                str(self.authoritative_morph_root)
                                if morph_profile_previous_state is not None
                                else None
                            ),
                            morph_profile_root_existed=(
                                morph_profile_previous_state[0]
                                if morph_profile_previous_state is not None
                                else None
                            ),
                            morph_profile_files=(
                                morph_profile_previous_state[1]
                                if morph_profile_previous_state is not None
                                else None
                            ),
                            morph_profile_after_root_existed=(
                                shadow_morph_profile_state[0]
                                if morph_profile_previous_state is not None
                                else None
                            ),
                            morph_profile_after_files=(
                                shadow_morph_profile_state[1]
                                if morph_profile_previous_state is not None
                                else None
                            ),
                            morph_profile_expected_fingerprint=(
                                morph_publication.published_fingerprint
                                if morph_publication is not None
                                else None
                            ),
                            require_reversible_history=True,
                        )
                    except Exception:
                        if morph_publication is not None:
                            try:
                                morph_publication.rollback()
                            except Exception as exc:  # pragma: no cover - catastrophic filesystem rollback
                                rollback_error = exc
                        raise
        except Exception as commit_error:
            try:
                if shadow_morph_state is not None:
                    try:
                        self.shadow_service.dispose_morph_session_state(
                            shadow_morph_state
                        )
                    except Exception:
                        try:
                            self.shadow_service.defer_morph_session_state_disposal(
                                shadow_morph_state
                            )
                        except Exception:
                            pass
            finally:
                with self._lifecycle_lock:
                    self._commit_started = False
            if rollback_error is not None:
                raise RuntimeError(
                    "Edit Mesh Finish was rejected and Morph profile rollback also failed: "
                    f"{type(rollback_error).__name__}: {rollback_error}"
                ) from commit_error
            raise
        return self._complete_accepted_finish(cleanup_warnings, committed, validation_payload, shadow_morph_state, morph_publication, exact_output_validation, free_edit_output_validation)

    def cancel(self) -> None:
        if self.closed:
            return
        if not self.request_cancel():
            return
        with self._protocol_lock:
            if not self.closed:
                self._dispose_shadow()

    def _dispose_shadow(self) -> str:
        warning = ""
        try:
            self.shadow_service.close_edit_session(
                self.shadow_session_id,
                force_without_saving=True,
            )
        except Exception as exc:  # semantic Finish/Cancel already owns the outcome
            warning = f"shadow-session cleanup is pending: {type(exc).__name__}: {exc}"
        finally:
            self.closed = True
        return warning


def _preserve_unchanged_rust_channel(
    original: list[tuple[float, ...]],
    candidate: list[tuple[float, ...]],
) -> list[tuple[float, ...]]:
    """Keep source precision where the editor's f32 value has not changed.

    Rust serializes f32 with its shortest round-tripping decimal. Comparing
    that JSON number to a Python double directly invents edits. Compare the
    actual f32 representations instead; even a one-ULP Rust edit remains real.
    """
    if len(original) != len(candidate):
        return candidate
    restored: list[tuple[float, ...]] = []
    try:
        for before, after in zip(original, candidate):
            if len(before) != len(after):
                raise RustMeshProtocolError("Mesh channel row width changed")
            if before == after:
                restored.append(before)
            else:
                restored.append(
                    tuple(
                        old
                        if old == new or struct.pack("<f", old) == struct.pack("<f", new)
                        else new
                        for old, new in zip(before, after)
                    )
                )
    except (OverflowError, struct.error) as exc:
        raise RustMeshProtocolError("Mesh channel exceeds finite f32 range") from exc
    return restored


def _finite_rows(value: object, width: int, label: str) -> list[tuple[float, ...]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RustMeshProtocolError(f"Mesh candidate {label} must be an array")
    rows: list[tuple[float, ...]] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) != width:
            raise RustMeshProtocolError(
                f"Mesh candidate {label} rows must contain {width} values"
            )
        try:
            row = tuple(float(item) for item in raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RustMeshProtocolError(f"Mesh candidate {label} is not numeric") from exc
        if any(not math.isfinite(item) for item in row):
            raise RustMeshProtocolError(f"Mesh candidate {label} contains non-finite values")
        rows.append(row)
    return rows


def _integer_values(value: object, label: str) -> list[int]:
    if not isinstance(value, list):
        raise RustMeshProtocolError(f"Mesh candidate {label} must be an array")
    result: list[int] = []
    for raw in value:
        if isinstance(raw, bool):
            raise RustMeshProtocolError(f"Mesh candidate {label} contains a boolean")
        try:
            integer = int(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RustMeshProtocolError(f"Mesh candidate {label} is not integral") from exc
        if integer < 0 or integer != raw:
            raise RustMeshProtocolError(f"Mesh candidate {label} contains an invalid index")
        result.append(integer)
    return result


__all__ = [
    "RUST_MESH_AUTHORING_PACKAGE",
    "RUST_MESH_CANDIDATE",
    "RUST_MESH_EDIT_BACKEND",
    "RUST_MESH_EDITOR_BINARY",
    "RUST_MESH_EDITOR_PROTOCOL",
    "RUST_MESH_MAX_PAYLOAD_BYTES",
    "RUST_MESH_RENDERER",
    "RustMeshAuthoringError",
    "RustMeshAuthoringSession",
    "RustMeshCancellationError",
    "RustMeshExecutableResolution",
    "RustMeshProtocolError",
    "RustMeshValidationError",
    "prime_rust_mesh_preview_context",
    "read_owned_payload_reference",
    "resolve_rust_mesh_editor",
    "rust_mesh_editor_candidate_paths",
]
