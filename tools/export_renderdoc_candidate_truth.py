from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = 1


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _pick_candidate(report: Mapping[str, object], *, rank: int = 0, chunk_index: int = 0) -> Mapping[str, object]:
    candidates = [item for item in _as_sequence(report.get("candidates", ())) if isinstance(item, Mapping)]
    for candidate in candidates:
        if rank and int(candidate.get("rank", 0) or 0) == rank:
            return candidate
        if chunk_index and int(candidate.get("chunk_index", 0) or 0) == chunk_index:
            return candidate
    raise ValueError("candidate_not_found")


def _shader_blob_lookup(
    shader_blob_manifest: Mapping[str, object],
    *,
    rank: int,
    chunk_index: int,
    stage: str,
    blob_id: int,
) -> Mapping[str, object]:
    for blob in _as_sequence(shader_blob_manifest.get("blobs", ())):
        if not isinstance(blob, Mapping):
            continue
        if _int(blob.get("blob_id", 0)) != blob_id:
            continue
        if str(blob.get("stage", "")).upper() != stage.upper():
            continue
        if rank and _int(blob.get("rank", 0)) != rank:
            continue
        if chunk_index and _int(blob.get("chunk_index", 0)) != chunk_index:
            continue
        return blob
    return {}


def _shader_payload(
    shader: Mapping[str, object],
    blob: Mapping[str, object],
    *,
    model_default: str = "DXIL",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(shader.get("blob_id", "")),
        "blob_id": shader.get("blob_id", ""),
        "bytecode_length": shader.get("byte_length", ""),
        "model": str(blob.get("shader_ir", "")) or model_default,
    }
    if blob:
        payload.update(
            {
                "hash": blob.get("sha256", ""),
                "sha256": blob.get("sha256", ""),
                "blob_path": blob.get("path", ""),
                "container_kind": blob.get("container_kind", ""),
                "shader_ir": blob.get("shader_ir", ""),
                "dxbc_parts": list(_as_sequence(blob.get("parts", ()))),
                "resource_bindings": list(_as_sequence(blob.get("resource_bindings", ()))),
                "handle_creates": list(_as_sequence(blob.get("handle_creates", ()))),
                "disassembly_path": blob.get("disassembly_path", ""),
                "disassembly_status": blob.get("disassembly_status", ""),
            }
        )
    return payload


def _binding_register(binding: Mapping[str, object]) -> int:
    try:
        return int(binding.get("register", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _shader_reflection_srv_slots(blob: Mapping[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for binding in _as_sequence(blob.get("resource_bindings", ())):
        if not isinstance(binding, Mapping) or binding.get("type") != "texture":
            continue
        output.append(
            {
                "slot": _binding_register(binding),
                "name": binding.get("name", ""),
                "parameter_name": binding.get("name", ""),
                "resource_path": "",
                "format": binding.get("format", ""),
                "dimension": binding.get("dim", ""),
                "binding_id": binding.get("id", ""),
                "hlsl_bind": binding.get("hlsl_bind", ""),
                "register": _binding_register(binding),
                "space": binding.get("space", 0),
                "count": binding.get("count", 1),
                "source": "shader_reflection",
            }
        )
    return output


def _shader_reflection_sampler_states(blob: Mapping[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for binding in _as_sequence(blob.get("resource_bindings", ())):
        if not isinstance(binding, Mapping) or binding.get("type") != "sampler":
            continue
        output.append(
            {
                "slot": _binding_register(binding),
                "name": binding.get("name", ""),
                "hlsl_bind": binding.get("hlsl_bind", ""),
                "register": _binding_register(binding),
                "space": binding.get("space", 0),
                "count": binding.get("count", 1),
                "source": "shader_reflection",
            }
        )
    return output


def _shader_reflection_constant_buffers(blob: Mapping[str, object]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for binding in _as_sequence(blob.get("resource_bindings", ())):
        if not isinstance(binding, Mapping) or binding.get("type") != "cbuffer":
            continue
        output.append(
            {
                "slot": _binding_register(binding),
                "name": binding.get("name", ""),
                "hlsl_bind": binding.get("hlsl_bind", ""),
                "register": _binding_register(binding),
                "space": binding.get("space", 0),
                "count": binding.get("count", 1),
                "source": "shader_reflection",
                "variables": [],
            }
        )
    return output


def _root_cbvs(state: Mapping[str, object]) -> list[dict[str, object]]:
    cbvs = _as_mapping(state.get("root_cbvs", {}))
    output: list[dict[str, object]] = []
    for slot_text, location_raw in sorted(cbvs.items(), key=lambda item: int(item[0])):
        location = _as_mapping(location_raw)
        output.append(
            {
                "slot": int(slot_text),
                "name": f"root_cbv_{slot_text}",
                "resource": location.get("resource", ""),
                "offset": location.get("offset", ""),
                "variables": [],
            }
        )
    return output


def _resolved_srv_slots(candidate: Mapping[str, object]) -> list[dict[str, object]]:
    state = _as_mapping(candidate.get("state", {}))
    tables = _as_mapping(state.get("root_descriptor_tables", {}))
    output: list[dict[str, object]] = []
    for root_slot, table_raw in sorted(tables.items(), key=lambda item: int(item[0])):
        table = _as_mapping(table_raw)
        for descriptor in _as_sequence(table.get("descriptors", ())):
            if not isinstance(descriptor, Mapping) or descriptor.get("type") != "SRV":
                continue
            resource_desc = _as_mapping(descriptor.get("resource_desc", {}))
            output.append(
                {
                    "slot": len(output),
                    "name": f"root_{root_slot}_descriptor_{descriptor.get('index', '')}",
                    "parameter_name": "",
                    "resource_path": "",
                    "format": descriptor.get("format", resource_desc.get("format", "")),
                    "resource": descriptor.get("resource", ""),
                    "resource_name": resource_desc.get("name", ""),
                    "root_parameter": int(root_slot),
                    "heap": descriptor.get("heap", ""),
                    "index": descriptor.get("index", ""),
                    "width": resource_desc.get("width", ""),
                    "height": resource_desc.get("height", ""),
                    "dimension": descriptor.get("view_dimension", resource_desc.get("dimension", "")),
                    "source": descriptor.get("source", ""),
                    "resource_desc": dict(resource_desc),
                }
            )
    return output


def _resolved_sampler_states(candidate: Mapping[str, object]) -> list[dict[str, object]]:
    state = _as_mapping(candidate.get("state", {}))
    tables = _as_mapping(state.get("root_descriptor_tables", {}))
    output: list[dict[str, object]] = []
    for root_slot, table_raw in sorted(tables.items(), key=lambda item: int(item[0])):
        table = _as_mapping(table_raw)
        for descriptor in _as_sequence(table.get("descriptors", ())):
            if not isinstance(descriptor, Mapping) or "SAMPLER" not in str(descriptor.get("type", "")).upper():
                continue
            output.append(
                {
                    "slot": len(output),
                    "name": f"root_{root_slot}_sampler_{descriptor.get('index', '')}",
                    "filter": descriptor.get("filter", ""),
                    "address_u": descriptor.get("address_u", ""),
                    "address_v": descriptor.get("address_v", ""),
                    "address_w": descriptor.get("address_w", ""),
                    "mip_lod_bias": descriptor.get("mip_lod_bias", ""),
                    "max_anisotropy": descriptor.get("max_anisotropy", ""),
                    "comparison_func": descriptor.get("comparison_func", ""),
                    "root_parameter": int(root_slot),
                    "heap": descriptor.get("heap", ""),
                    "index": descriptor.get("index", ""),
                    "source": descriptor.get("source", ""),
                }
            )
    return output


def candidate_to_truth_input(
    report: Mapping[str, object],
    *,
    rank: int = 0,
    chunk_index: int = 0,
    capture_path: str = "",
    material_name: str = "",
    shader_family: str = "generic",
    shader_blob_manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    candidate = _pick_candidate(report, rank=rank, chunk_index=chunk_index)
    picked_rank = _int(candidate.get("rank", rank))
    picked_chunk_index = _int(candidate.get("chunk_index", chunk_index))
    state = _as_mapping(candidate.get("state", {}))
    pipeline = _as_mapping(candidate.get("pipeline_description", {}))
    root_signature = _as_mapping(candidate.get("root_signature_description", {}))
    shaders = _as_mapping(pipeline.get("shaders", {}))
    vs = _as_mapping(shaders.get("VS", {}))
    ps = _as_mapping(shaders.get("PS", {}))
    cs = _as_mapping(shaders.get("CS", {}))
    blobs = shader_blob_manifest or {}
    vs_blob = _shader_blob_lookup(blobs, rank=picked_rank, chunk_index=picked_chunk_index, stage="VS", blob_id=_int(vs.get("blob_id", 0)))
    ps_blob = _shader_blob_lookup(blobs, rank=picked_rank, chunk_index=picked_chunk_index, stage="PS", blob_id=_int(ps.get("blob_id", 0)))
    cs_blob = _shader_blob_lookup(blobs, rank=picked_rank, chunk_index=picked_chunk_index, stage="CS", blob_id=_int(cs.get("blob_id", 0)))
    pixel_shader = _shader_payload(ps, ps_blob)
    pixel_shader["disassembly"] = ""
    compute_shader = _shader_payload(cs, cs_blob)
    compute_shader["disassembly"] = ""
    binding_blob = ps_blob or cs_blob
    resolved_srvs = _resolved_srv_slots(candidate)
    resolved_samplers = _resolved_sampler_states(candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "renderdoc_xml_draw_candidate",
        "material_name": material_name or f"draw_{candidate.get('chunk_index', '')}",
        "shader_family": shader_family,
        "drawcall": f"chunk_{candidate.get('chunk_index', '')}",
        "capture_path": capture_path or str(report.get("capture_xml", "")),
        "chunk_index": candidate.get("chunk_index", ""),
        "command_list": candidate.get("command_list", ""),
        "index_count": candidate.get("index_count", ""),
        "dispatch_groups": dict(_as_mapping(candidate.get("dispatch_groups", {}))),
        "pipeline_state": state.get("pipeline_state", ""),
        "root_signature": state.get("graphics_root_signature", state.get("compute_root_signature", "")),
        "primitive_topology": state.get("primitive_topology", ""),
        "vertex_shader": _shader_payload(vs, vs_blob),
        "pixel_shader": pixel_shader,
        "compute_shader": compute_shader,
        "blend_state": dict(_as_mapping(pipeline.get("blend_state", {}))),
        "raster_state": dict(_as_mapping(pipeline.get("raster_state", {}))),
        "depth_stencil_state": dict(_as_mapping(pipeline.get("depth_stencil_state", {}))),
        "render_target_formats": list(_as_sequence(pipeline.get("rtv_formats", ()))),
        "depth_format": pipeline.get("dsv_format", ""),
        "root_signature_description": dict(root_signature),
        "srv_slots": resolved_srvs or _shader_reflection_srv_slots(binding_blob),
        "sampler_states": resolved_samplers or _shader_reflection_sampler_states(binding_blob),
        "constant_buffers": _root_cbvs(state) + _shader_reflection_constant_buffers(binding_blob),
        "findings_hint": [
            "XML candidate gives PSO/root state and shader bytecode IDs/lengths, not shader disassembly.",
            "Descriptor SRV slots can remain unresolved without ref-all-resources or RenderDoc replay/UI export.",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export one RenderDoc draw candidate as normalized truth-pass input JSON.")
    parser.add_argument("--draw-candidates-json", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--rank", type=int, default=0)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--capture-path", default="")
    parser.add_argument("--material-name", default="")
    parser.add_argument("--shader-family", default="generic")
    parser.add_argument("--shader-blob-manifest", default="", help="Optional manifest from extract_renderdoc_shader_blobs.py.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = json.loads(Path(args.draw_candidates_json).read_text(encoding="utf-8"))
    if not isinstance(report, Mapping):
        raise ValueError("draw candidate report must be an object")
    shader_blob_manifest: Mapping[str, object] = {}
    if args.shader_blob_manifest:
        loaded_manifest = json.loads(Path(args.shader_blob_manifest).read_text(encoding="utf-8"))
        if not isinstance(loaded_manifest, Mapping):
            raise ValueError("shader blob manifest must be an object")
        shader_blob_manifest = loaded_manifest
    output = candidate_to_truth_input(
        report,
        rank=int(args.rank or 0),
        chunk_index=int(args.chunk_index or 0),
        capture_path=str(args.capture_path or ""),
        material_name=str(args.material_name or ""),
        shader_family=str(args.shader_family or "generic"),
        shader_blob_manifest=shader_blob_manifest,
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote draw truth input: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
