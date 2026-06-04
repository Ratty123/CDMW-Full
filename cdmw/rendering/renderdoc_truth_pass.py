from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_CAPTURE_INFERRED,
    decode_crimson_texture_binding,
    normalize_shader_family,
    renderdoc_truth_pass_checklist,
    texture_suffix_from_path,
)


RENDERDOC_TRUTH_SCHEMA_VERSION = 1


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _first_mapping_sequence(*values: object) -> Sequence[object]:
    for value in values:
        sequence = _as_sequence(value)
        if sequence:
            return sequence
    return ()


def _string(value: object) -> str:
    return str(value or "").strip()


def _bool_or_blank(value: object) -> object:
    if isinstance(value, bool):
        return bool(value)
    text = _string(value).lower()
    if text in {"true", "1", "yes", "srgb", "s_rgb"}:
        return True
    if text in {"false", "0", "no", "linear"}:
        return False
    return ""


def _srgb_from_format(value: object, format_value: object) -> object:
    explicit = _bool_or_blank(value)
    if explicit != "":
        return explicit
    text = _string(format_value).upper()
    if "_SRGB" in text:
        return True
    if text.startswith("DXGI_FORMAT_") and "TYPELESS" not in text and text != "DXGI_FORMAT_UNKNOWN":
        return False
    return ""


def _resource_path(entry: Mapping[str, object]) -> str:
    for key in ("path", "resource_path", "name", "resource", "texture", "dds_path", "source_path"):
        value = _string(entry.get(key, ""))
        if value:
            return value
    return ""


def _parameter_name(entry: Mapping[str, object]) -> str:
    for key in ("parameter_name", "parameter", "semantic", "slot_name", "name"):
        value = _string(entry.get(key, ""))
        if value and not value.isdigit():
            return value
    return ""


def normalize_srv_slots(data: Mapping[str, object]) -> list[Dict[str, object]]:
    slots = _first_mapping_sequence(
        data.get("srv_slots"),
        data.get("srvs"),
        data.get("shader_resource_views"),
        data.get("resources"),
    )
    normalized: list[Dict[str, object]] = []
    for index, raw_entry in enumerate(slots):
        if not isinstance(raw_entry, Mapping):
            continue
        slot_index = raw_entry.get("slot", raw_entry.get("index", raw_entry.get("bind_point", index)))
        try:
            numeric_slot = int(slot_index)
        except (TypeError, ValueError, OverflowError):
            numeric_slot = index
        path = _resource_path(raw_entry)
        parameter_name = _parameter_name(raw_entry)
        shader_family = normalize_shader_family(raw_entry.get("shader_family", data.get("shader_family", "")))
        format_value = _string(raw_entry.get("format", raw_entry.get("dxgi_format", "")))
        decode = decode_crimson_texture_binding(
            shader_family=shader_family,
            parameter_name=parameter_name,
            source_path=path,
            slot_name=_string(raw_entry.get("slot_kind", raw_entry.get("role", "material"))),
            semantic_subtype=_string(raw_entry.get("semantic_subtype", format_value)),
            layer_channel=_string(raw_entry.get("layer_channel", "")),
            blend_flags=tuple(_as_sequence(raw_entry.get("blend_flags", ()))),
            capture_inferred=True,
        )
        normalized.append(
            {
                "slot": numeric_slot,
                "name": _string(raw_entry.get("name", "")),
                "parameter_name": parameter_name,
                "resource_path": path,
                "suffix": texture_suffix_from_path(path),
                "format": format_value,
                "srgb_view": _srgb_from_format(raw_entry.get("srgb", raw_entry.get("srgb_view", raw_entry.get("is_srgb", ""))), format_value),
                "width": raw_entry.get("width", ""),
                "height": raw_entry.get("height", ""),
                "dimension": _string(raw_entry.get("dimension", raw_entry.get("dim", ""))),
                "binding_id": _string(raw_entry.get("binding_id", raw_entry.get("id", ""))),
                "hlsl_bind": _string(raw_entry.get("hlsl_bind", "")),
                "register": raw_entry.get("register", ""),
                "space": raw_entry.get("space", ""),
                "count": raw_entry.get("count", ""),
                "resource": raw_entry.get("resource", ""),
                "resource_name": _string(raw_entry.get("resource_name", raw_entry.get("object_name", ""))),
                "root_parameter": raw_entry.get("root_parameter", ""),
                "heap": raw_entry.get("heap", ""),
                "index": raw_entry.get("index", ""),
                "resource_desc": dict(raw_entry.get("resource_desc", {})) if isinstance(raw_entry.get("resource_desc", {}), Mapping) else {},
                "source": _string(raw_entry.get("source", "")),
                "shader_family": shader_family,
                "registry_decode": decode,
            }
        )
    return normalized


def normalize_sampler_states(data: Mapping[str, object]) -> list[Dict[str, object]]:
    samplers = _first_mapping_sequence(data.get("samplers"), data.get("sampler_states"))
    output: list[Dict[str, object]] = []
    for index, raw_entry in enumerate(samplers):
        if not isinstance(raw_entry, Mapping):
            continue
        output.append(
            {
                "slot": raw_entry.get("slot", raw_entry.get("index", index)),
                "filter": _string(raw_entry.get("filter", raw_entry.get("filter_mode", ""))),
                "address_u": _string(raw_entry.get("address_u", raw_entry.get("u", ""))),
                "address_v": _string(raw_entry.get("address_v", raw_entry.get("v", ""))),
                "mip_lod_bias": raw_entry.get("mip_lod_bias", raw_entry.get("lod_bias", "")),
                "max_anisotropy": raw_entry.get("max_anisotropy", ""),
                "name": _string(raw_entry.get("name", "")),
                "hlsl_bind": _string(raw_entry.get("hlsl_bind", "")),
                "register": raw_entry.get("register", ""),
                "space": raw_entry.get("space", ""),
                "count": raw_entry.get("count", ""),
                "root_parameter": raw_entry.get("root_parameter", ""),
                "heap": raw_entry.get("heap", ""),
                "index": raw_entry.get("index", ""),
                "source": _string(raw_entry.get("source", "")),
            }
        )
    return output


def normalize_constant_buffers(data: Mapping[str, object]) -> list[Dict[str, object]]:
    buffers = _first_mapping_sequence(data.get("constant_buffers"), data.get("cbs"), data.get("cbuffers"))
    output: list[Dict[str, object]] = []
    for index, raw_entry in enumerate(buffers):
        if not isinstance(raw_entry, Mapping):
            continue
        variables = raw_entry.get("variables", raw_entry.get("members", ()))
        output.append(
            {
                "slot": raw_entry.get("slot", raw_entry.get("index", index)),
                "name": _string(raw_entry.get("name", "")),
                "byte_size": raw_entry.get("byte_size", raw_entry.get("size", "")),
                "resource": raw_entry.get("resource", ""),
                "offset": raw_entry.get("offset", ""),
                "hlsl_bind": _string(raw_entry.get("hlsl_bind", "")),
                "register": raw_entry.get("register", ""),
                "space": raw_entry.get("space", ""),
                "count": raw_entry.get("count", ""),
                "source": _string(raw_entry.get("source", "")),
                "variable_count": len(_as_sequence(variables)),
                "variables": [
                    {
                        "name": _string(item.get("name", "")),
                        "value": item.get("value", ""),
                    }
                    for item in _as_sequence(variables)
                    if isinstance(item, Mapping)
                ][:128],
            }
        )
    return output


def infer_truth_findings(normalized: Mapping[str, object]) -> list[str]:
    findings: list[str] = []
    dispatch_groups = normalized.get("dispatch_groups", {})
    compute_shader = normalized.get("compute_shader")
    is_compute = (
        isinstance(dispatch_groups, Mapping)
        and bool(dispatch_groups)
        or isinstance(compute_shader, Mapping)
        and bool(_string(compute_shader.get("blob_id", compute_shader.get("hash", ""))))
    )
    srvs = _as_sequence(normalized.get("srv_slots", ()))
    if not srvs:
        findings.append("no SRV slots supplied")
    if not _as_sequence(normalized.get("sampler_states", ())):
        findings.append("no sampler states supplied")
    if not _as_sequence(normalized.get("constant_buffers", ())):
        findings.append("no constant buffers supplied")
    pixel_shader = normalized.get("pixel_shader")
    has_compute_disassembly = isinstance(compute_shader, Mapping) and (
        _string(compute_shader.get("disassembly", ""))
        or _string(compute_shader.get("disassembly_path", ""))
    )
    if not has_compute_disassembly and (not isinstance(pixel_shader, Mapping) or (
        not _string(pixel_shader.get("disassembly", ""))
        and not _string(pixel_shader.get("disassembly_path", ""))
    )):
        findings.append("no pixel shader disassembly supplied")
    if not _string(normalized.get("normal_y_mode", "")):
        findings.append("normal Y mode unresolved")
    if not is_compute and (not isinstance(normalized.get("blend_state", {}), Mapping) or not normalized.get("blend_state")):
        findings.append("blend state unresolved")
    if not is_compute and (not isinstance(normalized.get("raster_state", {}), Mapping) or not normalized.get("raster_state")):
        findings.append("raster state unresolved")
    for srv in srvs:
        if not isinstance(srv, Mapping):
            continue
        decode = srv.get("registry_decode", {})
        if isinstance(decode, Mapping) and decode.get("authority") == AUTHORITY_CAPTURE_INFERRED:
            source_kind = _string(decode.get("source_kind", ""))
            if source_kind and source_kind != "unknown_crimson_texture":
                findings.append(f"capture inferred {source_kind} at SRV {srv.get('slot')}")
    return list(dict.fromkeys(findings))


def normalize_renderdoc_truth_pass(data: Mapping[str, object]) -> Dict[str, object]:
    shader_family = normalize_shader_family(data.get("shader_family", ""))
    material_name = _string(data.get("material_name", data.get("drawcall", "")))
    pixel_shader_raw = data.get("pixel_shader", {})
    pixel_shader = pixel_shader_raw if isinstance(pixel_shader_raw, Mapping) else {}
    vertex_shader_raw = data.get("vertex_shader", {})
    vertex_shader = vertex_shader_raw if isinstance(vertex_shader_raw, Mapping) else {}
    compute_shader_raw = data.get("compute_shader", {})
    compute_shader = compute_shader_raw if isinstance(compute_shader_raw, Mapping) else {}
    normalized: Dict[str, object] = {
        "schema_version": RENDERDOC_TRUTH_SCHEMA_VERSION,
        "status": "capture_imported",
        "material_name": material_name,
        "shader_family": shader_family or "generic",
        "drawcall": _string(data.get("drawcall", "")),
        "capture_path": _string(data.get("capture_path", "")),
        "pipeline_state": data.get("pipeline_state", ""),
        "root_signature": data.get("root_signature", ""),
        "index_count": data.get("index_count", ""),
        "dispatch_groups": dict(data.get("dispatch_groups", {})) if isinstance(data.get("dispatch_groups", {}), Mapping) else {},
        "srv_slots": normalize_srv_slots(data),
        "sampler_states": normalize_sampler_states(data),
        "constant_buffers": normalize_constant_buffers(data),
        "vertex_shader": {
            "hash": _string(vertex_shader.get("hash", vertex_shader.get("sha256", vertex_shader.get("id", "")))),
            "sha256": _string(vertex_shader.get("sha256", vertex_shader.get("hash", ""))),
            "entry": _string(vertex_shader.get("entry", vertex_shader.get("entry_point", ""))),
            "model": _string(vertex_shader.get("model", vertex_shader.get("shader_model", ""))),
            "bytecode_length": vertex_shader.get("bytecode_length", vertex_shader.get("byte_length", "")),
            "blob_id": vertex_shader.get("blob_id", ""),
            "blob_path": _string(vertex_shader.get("blob_path", vertex_shader.get("path", ""))),
            "container_kind": _string(vertex_shader.get("container_kind", "")),
            "shader_ir": _string(vertex_shader.get("shader_ir", "")),
            "dxbc_parts": list(_as_sequence(vertex_shader.get("dxbc_parts", vertex_shader.get("parts", ())))),
            "resource_bindings": list(_as_sequence(vertex_shader.get("resource_bindings", ()))),
            "handle_creates": list(_as_sequence(vertex_shader.get("handle_creates", ()))),
            "disassembly_path": _string(vertex_shader.get("disassembly_path", "")),
            "disassembly_status": _string(vertex_shader.get("disassembly_status", "")),
        },
        "pixel_shader": {
            "hash": _string(pixel_shader.get("hash", pixel_shader.get("sha256", pixel_shader.get("id", "")))),
            "sha256": _string(pixel_shader.get("sha256", pixel_shader.get("hash", ""))),
            "entry": _string(pixel_shader.get("entry", pixel_shader.get("entry_point", ""))),
            "model": _string(pixel_shader.get("model", pixel_shader.get("shader_model", ""))),
            "bytecode_length": pixel_shader.get("bytecode_length", pixel_shader.get("byte_length", "")),
            "blob_id": pixel_shader.get("blob_id", ""),
            "disassembly": _string(pixel_shader.get("disassembly", "")),
            "blob_path": _string(pixel_shader.get("blob_path", pixel_shader.get("path", ""))),
            "container_kind": _string(pixel_shader.get("container_kind", "")),
            "shader_ir": _string(pixel_shader.get("shader_ir", "")),
            "dxbc_parts": list(_as_sequence(pixel_shader.get("dxbc_parts", pixel_shader.get("parts", ())))),
            "resource_bindings": list(_as_sequence(pixel_shader.get("resource_bindings", ()))),
            "handle_creates": list(_as_sequence(pixel_shader.get("handle_creates", ()))),
            "disassembly_path": _string(pixel_shader.get("disassembly_path", "")),
            "disassembly_status": _string(pixel_shader.get("disassembly_status", "")),
        },
        "compute_shader": {
            "hash": _string(compute_shader.get("hash", compute_shader.get("sha256", compute_shader.get("id", "")))),
            "sha256": _string(compute_shader.get("sha256", compute_shader.get("hash", ""))),
            "entry": _string(compute_shader.get("entry", compute_shader.get("entry_point", ""))),
            "model": _string(compute_shader.get("model", compute_shader.get("shader_model", ""))),
            "bytecode_length": compute_shader.get("bytecode_length", compute_shader.get("byte_length", "")),
            "blob_id": compute_shader.get("blob_id", ""),
            "disassembly": _string(compute_shader.get("disassembly", "")),
            "blob_path": _string(compute_shader.get("blob_path", compute_shader.get("path", ""))),
            "container_kind": _string(compute_shader.get("container_kind", "")),
            "shader_ir": _string(compute_shader.get("shader_ir", "")),
            "dxbc_parts": list(_as_sequence(compute_shader.get("dxbc_parts", compute_shader.get("parts", ())))),
            "resource_bindings": list(_as_sequence(compute_shader.get("resource_bindings", ()))),
            "handle_creates": list(_as_sequence(compute_shader.get("handle_creates", ()))),
            "disassembly_path": _string(compute_shader.get("disassembly_path", "")),
            "disassembly_status": _string(compute_shader.get("disassembly_status", "")),
        },
        "normal_y_mode": _string(data.get("normal_y_mode", data.get("normal_y", ""))),
        "blend_state": dict(data.get("blend_state", {})) if isinstance(data.get("blend_state", {}), Mapping) else {},
        "raster_state": dict(data.get("raster_state", {})) if isinstance(data.get("raster_state", {}), Mapping) else {},
        "depth_stencil_state": dict(data.get("depth_stencil_state", {})) if isinstance(data.get("depth_stencil_state", {}), Mapping) else {},
        "render_target_formats": list(_as_sequence(data.get("render_target_formats", ()))),
        "texture_srgb_views": [
            {
                "slot": srv.get("slot"),
                "resource_path": srv.get("resource_path", ""),
                "srgb_view": srv.get("srgb_view", ""),
                "format": srv.get("format", ""),
            }
            for srv in normalize_srv_slots(data)
            if isinstance(srv, Mapping) and srv.get("srgb_view", "") != ""
        ],
        "checklist": renderdoc_truth_pass_checklist(),
    }
    normalized["findings"] = infer_truth_findings(normalized)
    return normalized


def load_renderdoc_truth_pass(path: Path) -> Dict[str, object]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("RenderDoc truth JSON must be an object")
    return normalize_renderdoc_truth_pass(data)


def write_renderdoc_truth_pass_report(input_path: Path, output_path: Path) -> Dict[str, object]:
    report = load_renderdoc_truth_pass(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def summarize_truth_reports(reports: Iterable[Mapping[str, object]]) -> Dict[str, object]:
    report_list = [dict(report) for report in reports if isinstance(report, Mapping)]
    return {
        "schema_version": RENDERDOC_TRUTH_SCHEMA_VERSION,
        "status": "captures_imported" if report_list else "no_capture_data",
        "capture_count": len(report_list),
        "materials": [report.get("material_name", "") for report in report_list],
        "shader_families": list(dict.fromkeys(str(report.get("shader_family", "") or "generic") for report in report_list)),
        "findings": list(dict.fromkeys(str(finding) for report in report_list for finding in _as_sequence(report.get("findings", ())))),
    }


__all__ = [
    "RENDERDOC_TRUTH_SCHEMA_VERSION",
    "infer_truth_findings",
    "load_renderdoc_truth_pass",
    "normalize_constant_buffers",
    "normalize_renderdoc_truth_pass",
    "normalize_sampler_states",
    "normalize_srv_slots",
    "summarize_truth_reports",
    "write_renderdoc_truth_pass_report",
]
