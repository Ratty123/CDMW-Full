from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path

from cdmw.domain.mesh.material_resource_policy import mesh_material_resource_policy
from cdmw.modding.material_profiles import (
    CDMaterialRuntimeProfile,
    complete_swap_material_runtime_profiles,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.rendering.asset_fidelity_preflight import normal_y_policy_report
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_state_payload


_PROFILE_CHANNELS = ("base", "normal", "material", "emissive")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _dds_header_row(source: Path) -> dict[str, object]:
    """Read identity-level DDS metadata without decoding or mutating the source."""

    if source.suffix.casefold() != ".dds":
        return {}
    try:
        with source.open("rb") as handle:
            header = handle.read(148)
    except OSError:
        return {"dds_header_status": "unreadable"}
    if len(header) < 128 or header[:4] != b"DDS " or struct.unpack_from("<I", header, 4)[0] != 124:
        return {"dds_header_status": "invalid"}
    height, width, mip_count = struct.unpack_from("<III", header, 12)[0], struct.unpack_from("<I", header, 16)[0], struct.unpack_from("<I", header, 28)[0]
    fourcc = header[84:88].rstrip(b"\0 ").decode("ascii", errors="replace")
    caps2 = struct.unpack_from("<I", header, 112)[0]
    dxgi_format = 0
    native_2d_candidate = not bool(caps2 & (0x00000200 | 0x00200000))
    native_rejection_reason = "" if native_2d_candidate else "legacy_cubemap_or_volume"
    if fourcc == "DX10" and len(header) >= 148:
        dxgi_format = struct.unpack_from("<I", header, 128)[0]
        resource_dimension = struct.unpack_from("<I", header, 132)[0]
        misc_flag = struct.unpack_from("<I", header, 136)[0]
        array_size = struct.unpack_from("<I", header, 140)[0]
        native_2d_candidate = resource_dimension == 3 and array_size == 1 and not bool(misc_flag & 0x4)
        native_rejection_reason = "" if native_2d_candidate else "dx10_non_2d_array_or_cube"
    return {
        "dds_header_status": "valid",
        "source_width": int(width),
        "source_height": int(height),
        "source_mip_count": max(1, int(mip_count)),
        "source_format": f"DXGI_{dxgi_format}" if dxgi_format else fourcc or "legacy_rgb",
        "native_2d_candidate": native_2d_candidate,
        "native_rejection_reason": native_rejection_reason,
    }


def _profile_expected_channels(profile: CDMaterialRuntimeProfile) -> tuple[str, ...]:
    channels = ["base", "normal", "material"]
    if str(profile.emissive_mode or "disabled").casefold() != "disabled":
        channels.append("emissive")
    return tuple(channels)


def material_profile_contract_row(profile: CDMaterialRuntimeProfile) -> dict[str, object]:
    """Return the deterministic preview/export contract for one supported profile."""

    expected_channels = _profile_expected_channels(profile)
    policies = {
        channel: {
            "criticality": policy.criticality,
            "fallback_policy": policy.fallback_policy,
        }
        for channel in _PROFILE_CHANNELS
        for policy in (
            mesh_material_resource_policy(
                profile.name,
                channel,
                concrete_expected_resource=True,
            ),
        )
    }
    row: dict[str, object] = {
        "profile": profile.name,
        "expected_channels": list(expected_channels),
        "resource_policy": policies,
        "scalar_rules": {
            "ao_mode": profile.ao_mode,
            "ao_default": int(profile.ao_default),
            "roughness_default": int(profile.roughness_default),
            "roughness_inverted": bool(profile.roughness_inverted or profile.roughness_invert),
            "roughness_min": profile.roughness_min,
            "roughness_scale": profile.roughness_scale,
            "roughness_max": profile.roughness_max,
            "metallic_default": int(profile.metallic_default),
            "metallic_inverted": bool(profile.metallic_inverted or profile.metallic_invert),
            "metallic_min": profile.metallic_min,
            "metallic_scale": profile.metallic_scale,
            "metallic_max": profile.metallic_max,
            "force_nonmetal": bool(profile.force_nonmetal),
            "shine_scalar": profile.shine_scalar,
        },
        "tint_rules": {
            "neutral_color_rgb": list(profile.neutral_color_rgb),
            "base_color_lift": int(profile.base_color_lift),
            "base_color_scale": profile.base_color_scale,
            "base_color_gamma": profile.base_color_gamma,
            "base_color_saturation": profile.base_color_saturation,
            "base_color_value_max": profile.base_color_value_max,
            "source_color_layer_authority": bool(profile.source_color_layer_authority),
        },
        "normal_y_policy": normal_y_policy_report("asset"),
        "layer_behavior": {
            "support_policy": profile.support_policy,
            "force_neutral_layer_support": bool(profile.force_neutral_layer_support),
            "preserve_target_layer_response": bool(profile.preserve_target_layer_response),
            "source_color_layer_authority": bool(profile.source_color_layer_authority),
            "authority_contract": profile.authority_contract,
        },
        "binding_rules": {
            "material_mask_layout": profile.material_mask_layout,
            "ma_layout": profile.ma_layout,
            "base_binding_mode": profile.base_binding_mode,
            "mask_binding_mode": profile.mask_binding_mode,
            "shader": profile.shader,
        },
    }
    row["contract_fingerprint"] = _fingerprint(row)
    return row


def supported_material_profile_contracts() -> tuple[dict[str, object], ...]:
    return tuple(material_profile_contract_row(profile) for profile in complete_swap_material_runtime_profiles())


def _stable_openimageio_row(result: Mapping[str, object]) -> dict[str, object]:
    metadata = result.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    channel_stats = metadata.get("channel_stats")
    return {
        "status": str(result.get("status", "") or ""),
        "width": int(metadata.get("width", 0) or 0),
        "height": int(metadata.get("height", 0) or 0),
        "channel_count": int(metadata.get("channel_count", 0) or 0),
        "bit_depth": str(metadata.get("bit_depth", "") or ""),
        "color_space": str(metadata.get("color_space", "") or ""),
        "channel_names": [str(value) for value in tuple(metadata.get("channel_names", ()) or ())],
        "channel_stats": dict(channel_stats) if isinstance(channel_stats, Mapping) else {},
        "has_alpha_channel": bool(metadata.get("has_alpha_channel", False)),
        "alpha_varies": bool(metadata.get("alpha_varies", False)),
        "alpha_has_transparency": bool(metadata.get("alpha_has_transparency", False)),
    }


def _stable_resource_row(
    resource: Mapping[str, object],
    *,
    texture_probe: Callable[[Path], Mapping[str, object]] | None = None,
    texture_probe_cache: MutableMapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    source = Path(str(resource.get("source_reference", "") or "")).expanduser()
    try:
        source_sha256 = _sha256_file(source) if source.is_file() else ""
        source_bytes = int(source.stat().st_size) if source.is_file() else 0
    except OSError:
        source_sha256 = ""
        source_bytes = 0
    row = {
        "role": str(resource.get("role", "") or ""),
        "submesh_index": int(resource.get("submesh_index", -1) or 0),
        "channel": str(resource.get("material_channel", "") or ""),
        "profile": str(resource.get("profile", "") or ""),
        "criticality": str(resource.get("criticality", "") or ""),
        "fallback_policy": str(resource.get("fallback_policy", "") or ""),
        "semantic": str(resource.get("semantic", resource.get("material_channel", "")) or ""),
        "semantic_authority": str(resource.get("semantic_authority", "guess") or "guess"),
        "color_space": str(resource.get("color_space", "linear") or "linear"),
        "source_bytes": source_bytes,
        "source_sha256": source_sha256,
    }
    row.update(_dds_header_row(source))
    if texture_probe is not None and source_sha256:
        cached = texture_probe_cache.get(source_sha256) if texture_probe_cache is not None else None
        if cached is None:
            try:
                cached = _stable_openimageio_row(texture_probe(source))
            except Exception as exc:
                cached = {
                    "status": "probe_failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            if texture_probe_cache is not None:
                texture_probe_cache[source_sha256] = cached
        row["openimageio"] = dict(cached)
    return row


def material_asset_contract_row(
    mesh: ParsedMesh,
    *,
    asset_kind: str,
    source_identity: Mapping[str, object],
    texture_provenance: Sequence[Mapping[str, object]] = (),
    profile_assignment: str = "",
    texture_probe: Callable[[Path], Mapping[str, object]] | None = None,
    texture_probe_cache: MutableMapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Record the actual resident translator contract without path/mtime noise."""

    profile_name = str(profile_assignment or "").strip()
    previous_profiles = []
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        previous_profiles.append(
            (
                submesh,
                getattr(submesh, "cdmw_material_authority_profile", None),
                hasattr(submesh, "cdmw_material_authority_profile"),
            )
        )
        if profile_name:
            setattr(submesh, "cdmw_material_authority_profile", profile_name)
    try:
        payload = mesh_dotnet_material_state_payload(
            mesh,
            session_id="material-profile-corpus",
            edit_revision=0,
            generation=1,
        )
    finally:
        for submesh, previous, existed in previous_profiles:
            if existed:
                setattr(submesh, "cdmw_material_authority_profile", previous)
            else:
                delattr(submesh, "cdmw_material_authority_profile")
    resources = sorted(
        (
            _stable_resource_row(
                resource,
                texture_probe=texture_probe,
                texture_probe_cache=texture_probe_cache,
            )
            for resource in tuple(payload.get("resources", ()) or ())
            if isinstance(resource, Mapping)
        ),
        key=lambda row: (
            str(row["role"]),
            int(row["submesh_index"]),
            str(row["channel"]),
            str(row["source_sha256"]),
        ),
    )
    submeshes = []
    for submesh in tuple(payload.get("submeshes", ()) or ()):
        if not isinstance(submesh, Mapping):
            continue
        channels = submesh.get("channels")
        parameters = submesh.get("parameters")
        components = submesh.get("channel_components")
        color_spaces = submesh.get("channel_color_spaces")
        authorities = submesh.get("channel_authorities")
        submeshes.append(
            {
                "submesh_index": int(submesh.get("submesh_index", -1) or 0),
                "material": str(submesh.get("material", "") or ""),
                "channels": sorted(str(key) for key in channels) if isinstance(channels, Mapping) else [],
                "normal_y_policy": str(submesh.get("normal_y_policy", "preserve") or "preserve"),
                "channel_components": dict(sorted(components.items())) if isinstance(components, Mapping) else {},
                "channel_color_spaces": dict(sorted(color_spaces.items())) if isinstance(color_spaces, Mapping) else {},
                "channel_authorities": dict(sorted(authorities.items())) if isinstance(authorities, Mapping) else {},
                "shader_family": str(submesh.get("shader_family", "generic") or "generic"),
                "shader_technique": str(submesh.get("shader_technique", "") or ""),
                "shader_authority": str(submesh.get("shader_authority", "guess") or "guess"),
                "shader_family_source": str(submesh.get("shader_family_source", "") or ""),
                "shader_family_reason": str(submesh.get("shader_family_reason", "") or ""),
                "alpha_mode": str(submesh.get("alpha_mode", "opaque") or "opaque"),
                "alpha_cutoff": float(submesh.get("alpha_cutoff", 0.5) or 0.0),
                "opacity_factor": float(submesh.get("opacity_factor", 1.0)),
                "alpha_authority": str(submesh.get("alpha_authority", "guess") or "guess"),
                "alpha_reason": str(submesh.get("alpha_reason", "") or ""),
                "double_sided": bool(submesh.get("double_sided", False)),
                "double_sided_authority": str(
                    submesh.get("double_sided_authority", "guess") or "guess"
                ),
                "double_sided_reason": str(submesh.get("double_sided_reason", "") or ""),
                "layer_binding_count": len(tuple(submesh.get("layer_bindings", ()) or ())),
                "unsupported_features": sorted(str(value) for value in tuple(submesh.get("unsupported_features", ()) or ())),
                "parameters": dict(sorted(parameters.items())) if isinstance(parameters, Mapping) else {},
            }
        )
    provenance = sorted(
        (
            {
                "channel_source_sha256": str(row.get("source_sha256", "") or ""),
                "channel_source_bytes": int(row.get("source_bytes", 0) or 0),
                "archive_path": str(row.get("archive_path", "") or "").replace("\\", "/"),
            }
            for row in texture_provenance
        ),
        key=lambda row: (
            str(row["archive_path"]).casefold(),
            str(row["channel_source_sha256"]),
        ),
    )
    row: dict[str, object] = {
        "asset_kind": str(asset_kind),
        "profile_assignment": profile_name or "asset_declared_or_legacy",
        "source_identity": dict(sorted(source_identity.items())),
        "expected_channels": sorted({str(item["channel"]) for item in resources}),
        "resources": resources,
        "submeshes": sorted(submeshes, key=lambda item: (int(item["submesh_index"]), str(item["material"]))),
        "texture_provenance": provenance,
        "normal_y_policy": normal_y_policy_report("asset"),
        "claim_scope": (
            "resident translator, texture criticality, DDS identity/mips, semantic/color-space transport, "
            "scalar/tint binding, input provenance, and OpenImageIO channel statistics"
            if texture_probe is not None
            else "resident translator, texture criticality, DDS identity/mips, semantic/color-space transport, scalar/tint binding, and input provenance"
        ),
    }
    row["output_fingerprint"] = _fingerprint(row)
    return row


def synthetic_material_failure_contracts() -> tuple[dict[str, object], ...]:
    cases = (
        ("required_base_missing", "material_authority_true_source", "base"),
        ("optional_normal_missing", "material_authority_true_source", "normal"),
        ("unresolved_symbolic_base", "legacy_unknown", "base"),
    )
    rows: list[dict[str, object]] = []
    for name, profile, channel in cases:
        concrete = name != "unresolved_symbolic_base"
        policy = mesh_material_resource_policy(
            profile,
            channel,
            concrete_expected_resource=concrete,
        )
        row: dict[str, object] = {
            "case": name,
            "profile": profile,
            "channel": channel,
            "concrete_expected_resource": concrete,
            "criticality": policy.criticality,
            "fallback_policy": policy.fallback_policy,
            "ready_allowed_after_failure": not policy.required,
        }
        row["output_fingerprint"] = _fingerprint(row)
        rows.append(row)
    return tuple(rows)


def material_profile_corpus_report(
    *,
    asset_rows: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    profile_rows = supported_material_profile_contracts()
    synthetic_rows = synthetic_material_failure_contracts()
    stable_assets = [dict(row) for row in asset_rows]
    actual_profile_coverage = sorted(
        {
            str(resource.get("profile", "") or "")
            for asset in stable_assets
            for resource in tuple(asset.get("resources", ()) or ())
            if isinstance(resource, Mapping)
            and str(resource.get("profile", "") or "") not in {"", "legacy_unknown"}
        }
    )
    body: dict[str, object] = {
        "schema": "cdmw_mesh_material_profile_corpus_v1",
        "claim_scope": (
            "Contract and asset-input parity only; visible renderer parity is established separately "
            "by deterministic production captures."
        ),
        "supported_profiles": list(profile_rows),
        "assets": stable_assets,
        "actual_profile_coverage": actual_profile_coverage,
        "coverage_limitations": [
            "Profile rows are deterministic contracts, not proof that every shader family was observed in the bounded asset corpus.",
            "Visible renderer fidelity is established separately by production-backend captures.",
            "Layer graphs, hair/fur anisotropy, skin subsurface response, and per-triangle alpha sorting remain diagnostic-only.",
        ],
        "synthetic_failure_cases": list(synthetic_rows),
    }
    body["corpus_fingerprint"] = _fingerprint(body)
    return body


__all__ = [
    "material_asset_contract_row",
    "material_profile_contract_row",
    "material_profile_corpus_report",
    "supported_material_profile_contracts",
    "synthetic_material_failure_contracts",
]
