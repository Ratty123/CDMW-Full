"""Canonical PAC-owned material graph evidence for Mesh Editor transport."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from cdmw.core.archive_model_texture_semantics import _is_placeholder_model_texture
from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding


PAC_MATERIAL_GRAPH_SCHEMA = "cdmw_pac_material_graph_v1"
PAC_MATERIAL_GRAPH_VERSION = 1


def _value(item: object, name: str, fallback: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(name, fallback)
    return getattr(item, name, fallback)


def _safe_int(value: object, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _normalized_parameter(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())


def _normalized_path(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip()
    return text.casefold()


def _input_source_path(item: object) -> str:
    """Return the canonical PAC reference, independent of local transport."""

    return str(
        _value(item, "source_texture_path")
        or _value(item, "source_dds_path")
        or _value(item, "preview_texture_path")
        or ""
    ).replace("\\", "/").strip()


def _input_transport_path(item: object) -> str:
    return str(
        _value(item, "source_dds_path")
        or _value(item, "preview_texture_path")
        or _value(item, "source_texture_path")
        or ""
    ).replace("\\", "/").strip()


def _parameter_key(parameter: object) -> tuple[object, ...]:
    return (
        str(_value(parameter, "parameter_kind") or "").strip().casefold(),
        _normalized_parameter(_value(parameter, "parameter_name")),
        str(_value(parameter, "item_id") or "").strip(),
        _safe_int(_value(parameter, "index", -1)),
        _normalized_path(_value(parameter, "texture_path")),
        str(_value(parameter, "value") or "").strip(),
    )


def _parameter_preview_disposition(parameter: object) -> str:
    kind = str(_value(parameter, "parameter_kind") or "").strip().casefold()
    name = _normalized_parameter(_value(parameter, "parameter_name"))
    if kind == "texture" or _value(parameter, "texture_path"):
        if _is_placeholder_model_texture(str(_value(parameter, "texture_path") or "")):
            return "diagnostic"
        return "unsupported"
    visual_tokens = (
        "alpha",
        "brightness",
        "color",
        "dye",
        "emissive",
        "metal",
        "opacity",
        "roughness",
        "specular",
        "tile",
        "tint",
        "uv",
    )
    if kind in {"color", "float", "byte4"} and any(token in name for token in visual_tokens):
        return "baked"
    return "diagnostic"


def _binding_parameter_disposition(
    decode: Mapping[str, object],
    *,
    source_bound: bool,
) -> str:
    disposition = str(decode.get("disposition", "") or "").strip().casefold()
    if disposition in {
        "environment_height",
        "environment_layer",
        "environment_mask",
        "environment_simulation",
        "fallback_black",
        "fallback_flat_normal",
        "layer_direction",
        "layer_flow",
        "layer_material_response",
        "layer_only",
        "promoted",
        "recorded",
        "scalar_hint",
    }:
        return "bound"
    if disposition == "diagnostic_only" and bool(decode.get("known_slot", False)):
        return "diagnostic"
    return "unsupported" if source_bound else "diagnostic"


def _binding_row(item: object, fallback_shader_family: str) -> dict[str, object]:
    parameter_name = str(_value(item, "parameter_name") or "").strip()
    source_path = _input_source_path(item)
    transport_path = _input_transport_path(item)
    semantic = str(_value(item, "semantic_type") or _value(item, "slot_kind") or "material").strip()
    shader_family = str(_value(item, "shader_family") or fallback_shader_family or "").strip()
    decode = decode_crimson_texture_binding(
        shader_family=shader_family,
        parameter_name=parameter_name,
        source_path=source_path,
        slot_name=semantic,
        semantic_subtype=_value(item, "semantic_subtype"),
        packed_channels=tuple(_value(item, "packed_channels", ()) or ()),
        layer_channel=_value(item, "layer_channel"),
        blend_flags=tuple(_value(item, "blend_flags", ()) or ()),
        sidecar_kind=_value(item, "sidecar_kind"),
        parameter_declared_by=_value(item, "parameter_declared_by"),
    )
    authority = str(_value(item, "binding_authority") or decode.get("authority", "") or "")
    disposition = str(
        _value(item, "binding_disposition") or decode.get("disposition", "") or ""
    )
    source_kind = str(_value(item, "source_kind") or decode.get("source_kind", "") or "")
    owner_slot_index = _safe_int(_value(item, "owner_slot_index", -1))
    sidecar_kind = str(_value(item, "sidecar_kind") or "").strip().casefold()
    source_bound = owner_slot_index >= 0 or sidecar_kind in {"pac_xml", "pami"}
    return {
        "owner_slot_index": owner_slot_index,
        "owner_wrapper_item_id": str(_value(item, "owner_wrapper_item_id") or "").strip(),
        "material_name": str(_value(item, "material_name") or "").strip(),
        "part_name": str(_value(item, "part_name") or "").strip(),
        "shader_family": shader_family,
        "parameter_name": parameter_name,
        "parameter_key": _normalized_parameter(parameter_name),
        "source_reference": source_path,
        "transport_reference": transport_path,
        "source_name": PurePosixPath(source_path).name if source_path else "",
        "semantic": semantic.casefold(),
        "semantic_subtype": str(_value(item, "semantic_subtype") or "").strip().casefold(),
        "layer_role": str(_value(item, "layer_role") or "").strip().casefold(),
        "layer_channel": str(_value(item, "layer_channel") or "").strip().casefold(),
        "packed_channels": [str(value) for value in tuple(_value(item, "packed_channels", ()) or ())],
        "binding_authority": authority,
        "binding_disposition": disposition,
        "source_kind": source_kind,
        "parameter_disposition": _binding_parameter_disposition(
            {**decode, "disposition": disposition},
            source_bound=source_bound,
        ),
        "promoted_channels": dict(decode.get("promoted_channels", {}) or {}),
        "known_slot": bool(decode.get("known_slot", False)),
        "reason": str(decode.get("reason", "") or ""),
    }


def _declared_graph_texture_binding_row(
    parameter: object,
    *,
    owner_slot_index: int,
    owner_wrapper_item_id: str,
    fallback_shader_family: str,
) -> dict[str, object] | None:
    """Keep known graph-only or policy-fallback PAC texture declarations."""

    if owner_slot_index < 0:
        return None
    if str(_value(parameter, "parameter_kind") or "").strip().casefold() != "texture":
        return None
    parameter_name = str(_value(parameter, "parameter_name") or "").strip()
    source_path = str(_value(parameter, "texture_path") or "").replace("\\", "/").strip()
    if not parameter_name or not source_path or _is_placeholder_model_texture(source_path):
        return None
    decode = decode_crimson_texture_binding(
        shader_family=fallback_shader_family,
        parameter_name=parameter_name,
        source_path=source_path,
        slot_name="",
    )
    decoded_disposition = str(decode.get("disposition", "") or "").strip().casefold()
    decoded_slot = str(decode.get("slot", "") or "").strip().casefold()
    if decoded_disposition == "recorded":
        disposition = "recorded"
        authority = str(decode.get("authority", "") or "authoritative")
        source_kind = str(decode.get("source_kind", "") or "")
        reason = str(decode.get("reason", "") or "")
    elif decoded_disposition == "promoted" and decoded_slot == "normal":
        disposition = "fallback_flat_normal"
        authority = "policy"
        source_kind = "crimson_normal_fallback"
        reason = "declared normal resource unavailable; renderer uses flat-normal fallback"
    elif decoded_disposition == "promoted" and decoded_slot == "emissive":
        disposition = "fallback_black"
        authority = "policy"
        source_kind = "crimson_emissive_fallback"
        reason = "declared emissive resource unavailable; renderer uses black fallback"
    else:
        return None
    row = _binding_row(
        {
            "parameter_name": parameter_name,
            "source_texture_path": source_path,
            "semantic_type": decoded_slot or "material",
            "shader_family": fallback_shader_family,
            "owner_slot_index": owner_slot_index,
            "owner_wrapper_item_id": owner_wrapper_item_id,
            "binding_authority": authority,
            "binding_disposition": disposition,
            "source_kind": source_kind,
        },
        fallback_shader_family,
    )
    row["transport_reference"] = ""
    row["promoted_channels"] = {}
    row["reason"] = reason
    return row


def _parameter_row(
    parameter: object,
    *,
    owner_slot_index: int,
    owner_wrapper_item_id: str,
    binding_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    name = str(_value(parameter, "parameter_name") or "").strip()
    parameter_key = _normalized_parameter(name)
    texture_path = str(_value(parameter, "texture_path") or "").replace("\\", "/").strip()
    matching = [
        row
        for row in binding_rows
        if str(row.get("parameter_key", "") or "") == parameter_key
        and (
            not texture_path
            or _normalized_path(row.get("source_reference")) == _normalized_path(texture_path)
            or PurePosixPath(_normalized_path(row.get("source_reference"))).name
            == PurePosixPath(_normalized_path(texture_path)).name
        )
        and (
            owner_slot_index < 0
            or _safe_int(row.get("owner_slot_index", -1)) < 0
            or _safe_int(row.get("owner_slot_index", -1)) == owner_slot_index
        )
    ]
    disposition = (
        str(matching[0].get("parameter_disposition", "") or "")
        if matching
        else _parameter_preview_disposition(parameter)
    )
    return {
        "owner_slot_index": owner_slot_index,
        "owner_wrapper_item_id": owner_wrapper_item_id,
        "parameter_kind": str(_value(parameter, "parameter_kind") or "").strip().casefold(),
        "parameter_name": name,
        "parameter_key": parameter_key,
        "tag_name": str(_value(parameter, "tag_name") or "").strip(),
        "string_item_id": str(_value(parameter, "string_item_id") or "").strip(),
        "item_id": str(_value(parameter, "item_id") or "").strip(),
        "index": _safe_int(_value(parameter, "index", -1)),
        "value": str(_value(parameter, "value") or "").strip(),
        "texture_path": texture_path,
        "color_value": list(tuple(_value(parameter, "color_value", ()) or ())),
        "numeric_value": _value(parameter, "numeric_value", None),
        "disposition": disposition,
        "binding_count": len(matching),
    }


def build_pac_material_graph_v1(
    source: object | None,
    resolved_channels: Mapping[str, str] | None = None,
    *,
    source_asset_path: str = "",
) -> dict[str, object]:
    """Build a JSON-safe, owner-conserving material graph from preview inputs."""

    if source is None:
        graph = {
            "schema": PAC_MATERIAL_GRAPH_SCHEMA,
            "version": PAC_MATERIAL_GRAPH_VERSION,
            "source_asset_path": str(source_asset_path or ""),
            "wrappers": [],
            "bindings": [],
            "parameters": [],
            "binding_conservation": {
                "declared_parameter_count": 0,
                "binding_count": 0,
                "dropped_parameters": [],
                "cross_owner_bindings": [],
                "layer_as_base_bindings": [],
                "conserved": True,
            },
            "unsupported_features": [],
        }
        graph["graph_hash"] = _graph_hash(graph)
        return graph

    raw_family = str(getattr(source, "preview_sidecar_shader_family", "") or "").strip()
    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    binding_rows = [_binding_row(item, raw_family) for item in inputs]
    source_owner_slot_index = _safe_int(
        getattr(
            source,
            "preview_pac_material_owner_slot_index",
            getattr(
                source,
                "material_slot_index",
                getattr(source, "source_submesh_index", getattr(source, "submesh_index", -1)),
            ),
        )
    )
    authoritative_owner_indices = {
        _safe_int(row.get("owner_slot_index", -1))
        for row in binding_rows
        if _safe_int(row.get("owner_slot_index", -1)) >= 0
    }
    if source_owner_slot_index < 0 and len(authoritative_owner_indices) == 1:
        source_owner_slot_index = next(iter(authoritative_owner_indices))

    parameters_by_key: dict[tuple[object, ...], object] = {}
    parameter_owners: dict[tuple[object, ...], tuple[int, str]] = {}
    for item in inputs:
        item_owner = _safe_int(_value(item, "owner_slot_index", -1))
        wrapper_id = str(_value(item, "owner_wrapper_item_id") or "").strip()
        for parameter in tuple(_value(item, "material_parameters", ()) or ()):
            key = _parameter_key(parameter)
            parameters_by_key.setdefault(key, parameter)
            parameter_owners.setdefault(key, (item_owner, wrapper_id))
    for parameter in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        key = _parameter_key(parameter)
        parameters_by_key.setdefault(key, parameter)
        parameter_owners.setdefault(key, (source_owner_slot_index, ""))

    # Some graph-only parameters (for example PAC height/displacement inputs)
    # remain declared even when their archive resource is unavailable locally.
    # The registry explicitly records these without promoting them to a resident
    # renderer channel, so preserve that source binding instead of reporting it
    # as dropped.
    for key, parameter in parameters_by_key.items():
        owner_slot_index, owner_wrapper_item_id = parameter_owners[key]
        parameter_name = _normalized_parameter(_value(parameter, "parameter_name"))
        texture_path = _normalized_path(_value(parameter, "texture_path"))
        if any(
            str(row.get("parameter_key", "") or "") == parameter_name
            and (
                not texture_path
                or _normalized_path(row.get("source_reference")) == texture_path
                or PurePosixPath(_normalized_path(row.get("source_reference"))).name
                == PurePosixPath(texture_path).name
            )
            and (
                owner_slot_index < 0
                or _safe_int(row.get("owner_slot_index", -1)) < 0
                or _safe_int(row.get("owner_slot_index", -1)) == owner_slot_index
            )
            for row in binding_rows
        ):
            continue
        declared_binding = _declared_graph_texture_binding_row(
            parameter,
            owner_slot_index=owner_slot_index,
            owner_wrapper_item_id=owner_wrapper_item_id,
            fallback_shader_family=raw_family,
        )
        if declared_binding is not None:
            binding_rows.append(declared_binding)
    parameter_rows = [
        _parameter_row(
            parameter,
            owner_slot_index=parameter_owners[key][0],
            owner_wrapper_item_id=parameter_owners[key][1],
            binding_rows=binding_rows,
        )
        for key, parameter in parameters_by_key.items()
    ]

    # A PAC texture binding is itself a declared parameter even when a legacy
    # attachment path did not copy the full parameter vector onto the mesh.
    parameter_binding_keys = {
        (
            _safe_int(row.get("owner_slot_index", -1)),
            str(row.get("owner_wrapper_item_id", "") or ""),
            str(row.get("parameter_key", "") or ""),
            _normalized_path(row.get("source_reference")),
        )
        for row in parameter_rows
        if str(row.get("parameter_kind", "") or "") == "texture"
    }
    for binding in binding_rows:
        key = (
            _safe_int(binding.get("owner_slot_index", -1)),
            str(binding.get("owner_wrapper_item_id", "") or ""),
            str(binding.get("parameter_key", "") or ""),
            _normalized_path(binding.get("source_reference")),
        )
        if key in parameter_binding_keys:
            continue
        parameter_rows.append(
            {
                "owner_slot_index": key[0],
                "owner_wrapper_item_id": key[1],
                "parameter_kind": "texture",
                "parameter_name": str(binding.get("parameter_name", "") or ""),
                "parameter_key": key[2],
                "tag_name": "MaterialParameterTexture",
                "string_item_id": "",
                "item_id": "",
                "index": -1,
                "value": "",
                "texture_path": str(binding.get("source_reference", "") or ""),
                "color_value": [],
                "numeric_value": None,
                "disposition": str(binding.get("parameter_disposition", "") or ""),
                "binding_count": 1,
            }
        )

    wrappers_by_key: defaultdict[tuple[int, str], list[dict[str, object]]] = defaultdict(list)
    for binding in binding_rows:
        wrappers_by_key[
            (
                _safe_int(binding.get("owner_slot_index", -1)),
                str(binding.get("owner_wrapper_item_id", "") or ""),
            )
        ].append(binding)
    wrappers = [
        {
            "owner_slot_index": key[0],
            "owner_wrapper_item_id": key[1],
            "material_name": next(
                (str(row.get("material_name", "") or "") for row in rows if row.get("material_name")),
                "",
            ),
            "part_name": next(
                (str(row.get("part_name", "") or "") for row in rows if row.get("part_name")),
                "",
            ),
            "shader_family": next(
                (str(row.get("shader_family", "") or "") for row in rows if row.get("shader_family")),
                raw_family,
            ),
            "binding_count": len(rows),
            "parameter_count": sum(
                1
                for parameter in parameter_rows
                if _safe_int(parameter.get("owner_slot_index", -1)) == key[0]
                and str(parameter.get("owner_wrapper_item_id", "") or "") == key[1]
            ),
        }
        for key, rows in sorted(wrappers_by_key.items(), key=lambda item: item[0])
    ]

    dropped = [
        {
            "owner_slot_index": _safe_int(row.get("owner_slot_index", -1)),
            "owner_wrapper_item_id": str(row.get("owner_wrapper_item_id", "") or ""),
            "parameter_name": str(row.get("parameter_name", "") or ""),
            "texture_path": str(row.get("texture_path", "") or ""),
        }
        for row in parameter_rows
        if str(row.get("parameter_kind", "") or "") == "texture"
        and int(row.get("binding_count", 0) or 0) <= 0
        and str(row.get("disposition", "") or "") not in {"baked", "diagnostic"}
    ]
    cross_owner = [
        {
            "owner_slot_index": _safe_int(row.get("owner_slot_index", -1)),
            "parameter_name": str(row.get("parameter_name", "") or ""),
            "source_reference": str(row.get("source_reference", "") or ""),
        }
        for row in binding_rows
        if source_owner_slot_index >= 0
        and _safe_int(row.get("owner_slot_index", -1)) >= 0
        and _safe_int(row.get("owner_slot_index", -1)) != source_owner_slot_index
    ]
    resolved_base_paths = {
        _normalized_path(path)
        for channel, path in dict(resolved_channels or {}).items()
        if str(channel or "").strip().casefold() in {"albedo", "base", "diffuse"}
        and str(path or "").strip()
    }
    promoted_base_paths = {
        normalized_path
        for row in binding_rows
        if str(row.get("binding_disposition", "") or "").casefold() == "promoted"
        and "base_color" in dict(row.get("promoted_channels", {}) or {})
        for normalized_path in (
            _normalized_path(row.get("source_reference")),
            _normalized_path(row.get("transport_reference")),
        )
        if normalized_path
    }
    layer_as_base = [
        {
            "owner_slot_index": _safe_int(row.get("owner_slot_index", -1)),
            "parameter_name": str(row.get("parameter_name", "") or ""),
            "source_reference": str(row.get("source_reference", "") or ""),
        }
        for row in binding_rows
        if str(row.get("binding_disposition", "") or "").casefold() == "layer_only"
        and bool(
            {
                _normalized_path(row.get("source_reference")),
                _normalized_path(row.get("transport_reference")),
            }
            & resolved_base_paths
            - promoted_base_paths
        )
    ]
    unsupported = [
        {
            "owner_slot_index": _safe_int(row.get("owner_slot_index", -1)),
            "parameter_name": str(row.get("parameter_name", "") or ""),
            "parameter_kind": str(row.get("parameter_kind", "") or ""),
            "texture_path": str(row.get("texture_path", "") or ""),
        }
        for row in parameter_rows
        if str(row.get("disposition", "") or "") == "unsupported"
    ]
    conservation = {
        "declared_parameter_count": len(parameter_rows),
        "binding_count": len(binding_rows),
        "dropped_parameters": dropped,
        "cross_owner_bindings": cross_owner,
        "layer_as_base_bindings": layer_as_base,
        "conserved": not dropped and not cross_owner and not layer_as_base,
    }
    graph = {
        "schema": PAC_MATERIAL_GRAPH_SCHEMA,
        "version": PAC_MATERIAL_GRAPH_VERSION,
        "source_asset_path": str(source_asset_path or getattr(source, "path", "") or ""),
        "source_kind": "pac_xml" if any(row.get("owner_slot_index", -1) >= 0 for row in binding_rows) else "preview_material_graph",
        "source_submesh_index": source_owner_slot_index,
        "wrappers": wrappers,
        "bindings": binding_rows,
        "parameters": parameter_rows,
        "binding_conservation": conservation,
        "unsupported_features": unsupported,
    }
    graph["graph_hash"] = _graph_hash(graph)
    return graph


def _graph_hash(graph: Mapping[str, object]) -> str:
    payload = json.dumps(dict(graph), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "PAC_MATERIAL_GRAPH_SCHEMA",
    "PAC_MATERIAL_GRAPH_VERSION",
    "build_pac_material_graph_v1",
]
