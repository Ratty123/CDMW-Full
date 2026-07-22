"""Resource manifests and resident .NET material-state payloads."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.domain.mesh.material_resource_policy import (
    canonical_material_channel,
    mesh_material_resource_policy,
)
from cdmw.services.mesh_dotnet_material_bindings import (
    _dotnet_material_name,
    _dotnet_material_slot_index,
    _dotnet_material_sources,
    _dotnet_texture_name,
    _safe_int,
)
from cdmw.services.mesh_dotnet_material_channels import (
    _dotnet_initial_material_parameters,
    _dotnet_material_channel_components,
    _dotnet_material_normal_y_policy,
    _dotnet_resolved_texture_channels,
)
from cdmw.services.mesh_dotnet_material_semantics import (
    _dotnet_material_semantic_contract,
    _source_file_content_fingerprint,
    mesh_dotnet_material_input_signature,
)


def _dotnet_material_resource(raw_path: str) -> tuple[str, str]:
    source = Path(raw_path).expanduser()
    try:
        resolved = source.resolve()
        normalized_path = resolved.as_posix()
        fingerprint = _source_file_content_fingerprint(resolved)
    except OSError:
        normalized_path = os.path.normpath(raw_path).replace("\\", "/")
        fingerprint = hashlib.sha256(
            f"raw:{normalized_path.casefold()}".encode("utf-8")
        ).hexdigest()
    return normalized_path, fingerprint


def mesh_dotnet_texture_resource_id(raw_path: str | Path) -> str:
    _normalized_path, fingerprint = _dotnet_material_resource(str(raw_path or ""))
    return f"texture:{fingerprint}"


def _material_profile_name(source: object | None) -> str:
    if source is None:
        return ""
    return str(
        getattr(source, "cdmw_material_authority_profile", "")
        or getattr(source, "material_authority_profile", "")
        or getattr(source, "complete_swap_material_profile", "")
        or ""
    ).strip()


def _resource_channel_rank(channel: str) -> int:
    return {
        "base": 0,
        "normal": 1,
        "material": 2,
        "roughness": 3,
        "metallic": 4,
        "specular": 5,
        "emissive": 6,
        "height": 7,
    }.get(canonical_material_channel(channel), 99)


def _dotnet_manifest_resource_bindings(
    resolved_channels: Mapping[str, str],
    packaged_channels: Mapping[str, str],
    *,
    source: object | None = None,
    source_asset_path: str = "",
    submesh_index: int = 0,
    role: str = "replacement",
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    channels: dict[str, str] = {}
    resources: dict[str, dict[str, object]] = {}
    profile_name = _material_profile_name(source)
    semantic_contract = _dotnet_material_semantic_contract(
        source,
        resolved_channels,
        source_asset_path=source_asset_path,
    )
    channel_color_spaces = semantic_contract["channel_color_spaces"]
    channel_authorities = semantic_contract["channel_authorities"]
    for semantic, raw_path in sorted(resolved_channels.items()):
        source_path = str(raw_path or "").strip()
        if not source_path:
            continue
        normalized_path, fingerprint = _dotnet_material_resource(source_path)
        resource_id = (
            f"texture:{fingerprint}"
            if role == "replacement"
            else f"texture:{fingerprint}:{role}:{int(submesh_index)}"
        )
        channels[str(semantic)] = resource_id
        existing = resources.get(resource_id)
        if existing is None:
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            resources[resource_id] = {
                "resource_id": resource_id,
                "path": str(packaged_channels.get(semantic, normalized_path) or normalized_path),
                "source_reference": normalized_path,
                "fingerprint": fingerprint,
                "role": str(role or "replacement"),
                "submesh_index": int(submesh_index),
                "material_channel": policy.channel,
                "semantic": canonical_material_channel(semantic),
                "color_space": str(channel_color_spaces.get(semantic, "linear")),
                "semantic_authority": str(channel_authorities.get(semantic, "guess")),
                "profile": policy.profile,
                "required": policy.required,
                "criticality": policy.criticality,
                "fallback_policy": policy.fallback_policy,
            }
        elif _resource_channel_rank(str(semantic)) < _resource_channel_rank(
            str(existing.get("material_channel", ""))
        ):
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            existing.update(
                material_channel=policy.channel,
                semantic=canonical_material_channel(semantic),
                color_space=str(channel_color_spaces.get(semantic, "linear")),
                semantic_authority=str(channel_authorities.get(semantic, "guess")),
                required=policy.required,
                criticality=policy.criticality,
                fallback_policy=policy.fallback_policy,
            )
        elif not bool(existing.get("required", False)):
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            if policy.required:
                existing.update(
                    profile=policy.profile,
                    material_channel=policy.channel,
                    required=True,
                    criticality=policy.criticality,
                    fallback_policy=policy.fallback_policy,
                )
    return channels, resources


def mesh_dotnet_material_state_payload(
    mesh: object,
    *,
    session_id: str,
    edit_revision: int,
    generation: int,
    affected_submeshes: Sequence[int] | None = None,
    role: str = "replacement",
    submesh_index_offset: int = 0,
    material_signature: str = "",
) -> dict[str, object]:
    """Snapshot resident material bindings without rebuilding a package."""
    resources: dict[str, dict[str, object]] = {}
    submesh_payloads: list[dict[str, object]] = []
    all_indices: list[int] = []
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    source_submeshes = _dotnet_material_sources(mesh)
    for fallback_index, submesh in enumerate(source_submeshes):
        local_index = _safe_int(
            getattr(
                submesh,
                "submesh_index",
                getattr(submesh, "source_submesh_index", fallback_index),
            ),
            fallback_index,
        )
        if local_index < 0:
            local_index = fallback_index
        submesh_index = (
            max(0, _safe_int(submesh_index_offset, 0)) + fallback_index
            if role != "replacement" or submesh_index_offset
            else local_index
        )
        all_indices.append(submesh_index)
        resolved_channels = _dotnet_resolved_texture_channels(submesh)
        semantic_contract = _dotnet_material_semantic_contract(
            submesh,
            resolved_channels,
            source_asset_path=source_asset_path,
        )
        channels, submesh_resources = _dotnet_manifest_resource_bindings(
            resolved_channels,
            {},
            source=submesh,
            source_asset_path=source_asset_path,
            submesh_index=submesh_index,
            role=role,
        )
        resources.update(submesh_resources)
        submesh_payloads.append(
            {
                "submesh_index": submesh_index,
                "material_slot_index": _dotnet_material_slot_index(
                    submesh,
                    source_submeshes,
                    fallback_index,
                ),
                "material": _dotnet_material_name(submesh),
                "texture": _dotnet_texture_name(submesh),
                "texture_flip_vertical": bool(
                    getattr(submesh, "preview_texture_flip_vertical", False)
                ),
                "channels": channels,
                "normal_y_policy": _dotnet_material_normal_y_policy(submesh),
                "channel_components": _dotnet_material_channel_components(submesh),
                **semantic_contract,
                "parameters": _dotnet_initial_material_parameters(
                    submesh, resolved_channels
                ),
            }
        )
    valid_indices = set(all_indices)
    affected = sorted(valid_indices) if affected_submeshes is None else sorted(
        {
            index
            for value in affected_submeshes
            if (index := _safe_int(value, -1)) in valid_indices
        }
    )
    return {
        "schema": "cdmw_mesh_material_state_v3",
        "version": 3,
        "event": "material_state_update",
        "session_id": str(session_id or ""),
        "edit_revision": max(0, _safe_int(edit_revision, 0)),
        "generation": max(0, _safe_int(generation, 0)),
        "material_signature": str(material_signature or mesh_dotnet_material_input_signature(mesh)),
        "affected_submeshes": affected,
        "resources": [resources[key] for key in sorted(resources)],
        "submeshes": submesh_payloads,
    }
