"""Shared content-addressed compiler for initial and resident .NET materials."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping, Sequence

from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_dotnet_material_bindings import (
    _DOTNET_PREVIEW_MATERIAL_ATTRS,
    _canonical_dotnet_material_source,
    _dotnet_material_slot_index,
    _dotnet_material_sources,
    _dotnet_pac_material_owner_slot_index,
)
from cdmw.services.mesh_dotnet_material_package import (
    compile_mesh_dotnet_material_manifest,
)
from cdmw.services.mesh_dotnet_material_semantics import (
    mesh_dotnet_material_input_signature,
)


MESH_DOTNET_MATERIAL_COMPILER_VERSION = 5
MESH_DOTNET_MATERIAL_CACHE_NAME = "cdmw-mesh-dotnet-material-cache-v1"


class MeshDotNetMaterialCompilationError(RuntimeError):
    """Raised when a required source graph cannot be conserved or synthesized."""


def _safe_int(value: object, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


@dataclass(frozen=True, slots=True)
class MeshDotNetMaterialCompileRequest:
    session_id: str
    edit_revision: int
    generation: int
    role: str
    mesh_snapshot: object
    affected_submeshes: tuple[int, ...] = ()
    submesh_index_offset: int = 0
    material_signature: str = ""
    output_root: Path | None = None
    reason: str = "changed"
    process_generation: int = 0
    parameter_groups: tuple[Mapping[str, object], ...] = ()
    material_authority_fingerprint: str = ""
    material_authority_revision: int = 0


def _deepcopy_or_value(value: object) -> object:
    try:
        return copy.deepcopy(value)
    except (TypeError, ValueError, RuntimeError):
        return value


def snapshot_mesh_dotnet_material_inputs(
    mesh: object,
    *,
    scene_material_slot_indices: Sequence[int] = (),
    submesh_index_offset: int = 0,
) -> object:
    """Capture immutable material inputs without copying geometry buffers."""

    source_submeshes = _dotnet_material_sources(mesh)
    scene_slots = tuple(_safe_int(value, -1) for value in scene_material_slot_indices)
    scene_offset = max(0, _safe_int(submesh_index_offset, 0))
    submeshes: list[object] = []
    for fallback_index, raw_source in enumerate(source_submeshes):
        source = _canonical_dotnet_material_source(raw_source, fallback_index)
        explicit_tangents = getattr(source, "preview_tangents_usable", None)
        if explicit_tangents is None:
            vertices = (
                getattr(source, "vertices", ())
                or getattr(source, "positions", ())
                or ()
            )
            uvs = (
                getattr(source, "uvs", ())
                or getattr(source, "texture_coordinates", ())
                or ()
            )
            try:
                explicit_tangents = bool(vertices) and len(vertices) == len(uvs)
            except (TypeError, ValueError):
                explicit_tangents = False
        scene_submesh_index = scene_offset + fallback_index
        scene_material_slot_index = (
            scene_slots[scene_submesh_index]
            if scene_submesh_index < len(scene_slots)
            else -1
        )
        source_submesh_index = _safe_int(
            getattr(
                source,
                "submesh_index",
                getattr(source, "source_submesh_index", fallback_index),
            ),
            fallback_index,
        )
        if source_submesh_index < 0:
            source_submesh_index = fallback_index
        values: dict[str, object] = {
            "name": str(getattr(source, "name", "") or ""),
            "material": str(
                getattr(source, "material", "")
                or getattr(source, "material_name", "")
                or ""
            ),
            "texture": str(
                getattr(source, "texture", "")
                or getattr(source, "texture_name", "")
                or ""
            ),
            "submesh_index": source_submesh_index,
            "source_submesh_index": source_submesh_index,
            "material_slot_index": (
                scene_material_slot_index
                if scene_material_slot_index >= 0
                else _dotnet_material_slot_index(
                    source,
                    source_submeshes,
                    fallback_index,
                )
            ),
            "preview_pac_material_owner_slot_index": _dotnet_pac_material_owner_slot_index(
                source,
                fallback_index,
            ),
            "preview_tangents_usable": bool(explicit_tangents),
        }
        for name in _DOTNET_PREVIEW_MATERIAL_ATTRS:
            if hasattr(source, name):
                values[name] = _deepcopy_or_value(getattr(source, name))
        submeshes.append(SimpleNamespace(**values))
    return SimpleNamespace(
        path=str(getattr(mesh, "path", "") or ""),
        submeshes=tuple(submeshes),
    )


def _request_signature(request: MeshDotNetMaterialCompileRequest) -> str:
    source_input_signature = mesh_dotnet_material_input_signature(request.mesh_snapshot)
    material_signature = str(request.material_signature or source_input_signature).strip()
    identity = json.dumps(
        {
            "compiler_version": MESH_DOTNET_MATERIAL_COMPILER_VERSION,
            "material_signature": material_signature,
            "source_input_signature": source_input_signature,
            "role": str(request.role or "replacement"),
            "submesh_index_offset": max(0, int(request.submesh_index_offset)),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _cache_root(request: MeshDotNetMaterialCompileRequest) -> Path:
    return Path(
        request.output_root
        or Path(tempfile.gettempdir()) / MESH_DOTNET_MATERIAL_CACHE_NAME
    ).expanduser().resolve()


def _load_cached_manifest(path: Path, signature: str) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    compiler = payload.get("compiler")
    if not isinstance(compiler, Mapping):
        return None
    if str(compiler.get("cache_key", "") or "") != signature:
        return None
    return payload


def _material_compile_blockers(manifest: Mapping[str, object]) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    raw_submeshes = manifest.get("submeshes", ())
    submeshes = raw_submeshes if isinstance(raw_submeshes, Sequence) else ()
    for submesh in submeshes:
        if not isinstance(submesh, Mapping):
            continue
        submesh_index = _safe_int(submesh.get("submesh_index", -1), -1)
        conservation = submesh.get("binding_conservation", {})
        if isinstance(conservation, Mapping) and not bool(conservation.get("conserved", True)):
            blockers.append(
                {
                    "submesh_index": submesh_index,
                    "kind": "binding_conservation",
                    "dropped_parameters": list(conservation.get("dropped_parameters", ()) or ()),
                    "cross_owner_bindings": list(conservation.get("cross_owner_bindings", ()) or ()),
                    "layer_as_base_bindings": list(conservation.get("layer_as_base_bindings", ()) or ()),
                }
            )
        source_contract = submesh.get("source_contract", {})
        unsupported = (
            list(source_contract.get("unsupported_features", ()) or ())
            if isinstance(source_contract, Mapping)
            else []
        )
        if unsupported:
            blockers.append(
                {
                    "submesh_index": submesh_index,
                    "kind": "unsupported_parameters",
                    "parameters": unsupported,
                }
            )
        synthesis = submesh.get("material_synthesis", {})
        raw_contract = submesh.get("raw_material_contract", {})
        synthesis_notes = (
            tuple(synthesis.get("notes", ()) or ())
            if isinstance(synthesis, Mapping)
            else ()
        )
        unreadable_inputs = [
            str(note)
            for note in synthesis_notes
            if "unreadable:" in str(note).casefold()
        ]
        if unreadable_inputs:
            blockers.append(
                {
                    "submesh_index": submesh_index,
                    "kind": "unreadable_material_inputs",
                    "notes": unreadable_inputs,
                }
            )
        if (
            isinstance(synthesis, Mapping)
            and bool(synthesis.get("attempted", False))
            and not bool(synthesis.get("succeeded", False))
            and isinstance(raw_contract, Mapping)
            and bool(tuple(raw_contract.get("layer_bindings", ()) or ()))
        ):
            blockers.append(
                {
                    "submesh_index": submesh_index,
                    "kind": "synthesis_failure",
                    "failure": str(
                        synthesis.get("failure", synthesis.get("skipped", "no generated output"))
                        or "no generated output"
                    ),
                }
            )
    return blockers


def _compile_manifest_to_cache(
    request: MeshDotNetMaterialCompileRequest,
    *,
    cache_key: str,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, object], Path, bool]:
    root = _cache_root(request)
    cache_dir = root / cache_key
    manifest_path = cache_dir / "net_materials.json"
    cached = _load_cached_manifest(manifest_path, cache_key)
    if cached is not None:
        return cached, cache_dir, True
    if cancelled is not None and cancelled():
        raise RunCancelled("Mesh .NET resident material compilation cancelled.")
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{cache_key}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        manifest = compile_mesh_dotnet_material_manifest(
            request.mesh_snapshot,
            package_dir=staging,
            material_signature=str(
                request.material_signature
                or mesh_dotnet_material_input_signature(request.mesh_snapshot)
            ),
            role=str(request.role or "replacement"),
            submesh_index_offset=max(0, int(request.submesh_index_offset)),
            cancelled=cancelled,
        )
        blockers = _material_compile_blockers(manifest)
        if blockers:
            raise MeshDotNetMaterialCompilationError(
                "PAC material graph could not be compiled: "
                + json.dumps(blockers, ensure_ascii=True, separators=(",", ":"))
            )
        manifest["compiler"] = {
            "name": "canonical_mesh_dotnet_material_compiler",
            "version": MESH_DOTNET_MATERIAL_COMPILER_VERSION,
            "cache_key": cache_key,
        }
        manifest = _rebase_manifest_paths(manifest, staging, cache_dir)
        atomic_write_text(staging / "net_materials.json", json.dumps(manifest, indent=2))
        if cancelled is not None and cancelled():
            raise RunCancelled("Mesh .NET resident material compilation cancelled.")
        try:
            os.replace(staging, cache_dir)
        except OSError:
            cached = _load_cached_manifest(manifest_path, cache_key)
            if cached is None:
                raise
            return cached, cache_dir, True
        return manifest, cache_dir, False
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _rebase_manifest_paths(
    value: object,
    staging: Path,
    cache_dir: Path,
) -> object:
    """Replace unpublished staging roots before the directory is atomically moved."""

    if isinstance(value, Mapping):
        return {
            str(key): _rebase_manifest_paths(item, staging, cache_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase_manifest_paths(item, staging, cache_dir) for item in value]
    if isinstance(value, tuple):
        return tuple(_rebase_manifest_paths(item, staging, cache_dir) for item in value)
    if not isinstance(value, str):
        return value
    replacements = (
        (str(staging.resolve()), str(cache_dir.resolve())),
        (staging.resolve().as_posix(), cache_dir.resolve().as_posix()),
    )
    rebased = value
    for source_root, target_root in replacements:
        rebased = rebased.replace(source_root, target_root)
    return rebased


def _resident_payload_from_manifest(
    request: MeshDotNetMaterialCompileRequest,
    manifest: Mapping[str, object],
    cache_dir: Path,
    *,
    cache_hit: bool,
) -> dict[str, object]:
    resources: list[dict[str, object]] = []
    for raw_resource in tuple(manifest.get("resources", ()) or ()):
        if not isinstance(raw_resource, Mapping):
            continue
        resource = dict(raw_resource)
        path = Path(str(resource.get("path", "") or ""))
        if not path.is_absolute():
            resource["path"] = str((cache_dir / path).resolve())
        resources.append(resource)
    submeshes: list[dict[str, object]] = []
    all_indices: list[int] = []
    for raw_submesh in tuple(manifest.get("submeshes", ()) or ()):
        if not isinstance(raw_submesh, Mapping):
            continue
        submesh = dict(raw_submesh)
        submesh_index = _safe_int(submesh.get("submesh_index", -1), -1)
        all_indices.append(submesh_index)
        submesh["channels"] = dict(submesh.get("resource_channels", {}) or {})
        submeshes.append(submesh)
    valid_indices = set(all_indices)
    affected = (
        sorted(valid_indices)
        if not request.affected_submeshes
        else sorted(index for index in request.affected_submeshes if index in valid_indices)
    )
    conservation = {
        "conserved": all(
            bool(
                (submesh.get("binding_conservation", {}) or {}).get("conserved", True)
            )
            for submesh in submeshes
            if isinstance(submesh.get("binding_conservation", {}), Mapping)
        ),
        "submesh_count": len(submeshes),
        "dropped_parameter_count": sum(
            len(tuple((submesh.get("binding_conservation", {}) or {}).get("dropped_parameters", ()) or ()))
            for submesh in submeshes
            if isinstance(submesh.get("binding_conservation", {}), Mapping)
        ),
        "cross_owner_binding_count": sum(
            len(tuple((submesh.get("binding_conservation", {}) or {}).get("cross_owner_bindings", ()) or ()))
            for submesh in submeshes
            if isinstance(submesh.get("binding_conservation", {}), Mapping)
        ),
        "layer_as_base_count": sum(
            len(tuple((submesh.get("binding_conservation", {}) or {}).get("layer_as_base_bindings", ()) or ()))
            for submesh in submeshes
            if isinstance(submesh.get("binding_conservation", {}), Mapping)
        ),
    }
    compiler = dict(manifest.get("compiler", {}) or {})
    compiler.update(
        {
            "cache_hit": bool(cache_hit),
            "cache_dir": str(cache_dir),
            "initial_resident_equivalent": True,
        }
    )
    submeshes_by_index = {
        _safe_int(submesh.get("submesh_index", -1), -1): submesh
        for submesh in submeshes
    }
    parameter_metadata = {
        "source_submesh_indices",
        "source_submesh_index",
        "submesh_indices",
        "affected_submeshes",
        "editor_role",
    }
    for raw_group in request.parameter_groups:
        if not isinstance(raw_group, Mapping):
            continue
        raw_indices = raw_group.get(
            "source_submesh_indices",
            raw_group.get("submesh_indices", raw_group.get("affected_submeshes", ())),
        )
        indices = tuple(raw_indices) if isinstance(raw_indices, Sequence) and not isinstance(raw_indices, (str, bytes, bytearray)) else ()
        parameters = {
            str(key): _deepcopy_or_value(value)
            for key, value in raw_group.items()
            if str(key) not in parameter_metadata
        }
        for raw_index in indices:
            index = _safe_int(raw_index, -1)
            if index in submeshes_by_index:
                submeshes_by_index[index]["parameters"] = dict(parameters)
    return {
        "schema": "cdmw_mesh_material_state_v3",
        "version": 3,
        "event": "material_state_update",
        "session_id": str(request.session_id or ""),
        "edit_revision": max(0, int(request.edit_revision)),
        "generation": max(0, int(request.generation)),
        "role": str(request.role or "replacement"),
        "reason": str(request.reason or "changed"),
        "material_signature": str(
            request.material_signature
            or manifest.get("material_signature", "")
            or ""
        ),
        "affected_submeshes": affected,
        "resources": resources,
        "submeshes": submeshes,
        "binding_conservation": conservation,
        "compiler": compiler,
        "material_authority_parameter_groups": [
            dict(group) for group in request.parameter_groups if isinstance(group, Mapping)
        ],
        "material_authority_fingerprint": str(request.material_authority_fingerprint or ""),
        "material_authority_revision": max(0, int(request.material_authority_revision)),
    }


def compile_mesh_dotnet_material_update(
    request: MeshDotNetMaterialCompileRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    cache_key = _request_signature(request)
    manifest, cache_dir, cache_hit = _compile_manifest_to_cache(
        request,
        cache_key=cache_key,
        cancelled=cancelled,
    )
    if cancelled is not None and cancelled():
        raise RunCancelled("Mesh .NET resident material compilation cancelled.")
    return _resident_payload_from_manifest(
        request,
        manifest,
        cache_dir,
        cache_hit=cache_hit,
    )


__all__ = [
    "MESH_DOTNET_MATERIAL_CACHE_NAME",
    "MESH_DOTNET_MATERIAL_COMPILER_VERSION",
    "MeshDotNetMaterialCompilationError",
    "MeshDotNetMaterialCompileRequest",
    "compile_mesh_dotnet_material_update",
    "snapshot_mesh_dotnet_material_inputs",
]
