from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def _candidate(report: Mapping[str, Any], rank: int) -> Mapping[str, Any]:
    for item in report.get("candidates", []):
        if isinstance(item, Mapping) and int(item.get("rank", 0) or 0) == int(rank):
            return item
    raise ValueError(f"candidate rank not found: {rank}")


def _blob(manifest: Mapping[str, Any] | None, *, rank: int, chunk_index: object, stage: str) -> Mapping[str, Any]:
    if not manifest:
        return {}
    for item in manifest.get("blobs", []):
        if (
            isinstance(item, Mapping)
            and int(item.get("rank", 0) or 0) == int(rank)
            and str(item.get("chunk_index", "")) == str(chunk_index)
            and str(item.get("stage", "")) == stage
        ):
            return item
    return {}


def _shader(base: Mapping[str, Any], blob: Mapping[str, Any]) -> dict[str, Any]:
    result = {"blob_id": base.get("blob_id", ""), "bytecode_length": base.get("byte_length", base.get("bytecode_length", ""))}
    if blob:
        result.update(
            {
                "sha256": blob.get("sha256", ""),
                "blob_path": blob.get("path", ""),
                "container_kind": blob.get("container_kind", ""),
                "shader_ir": blob.get("shader_ir", ""),
                "dxbc_parts": blob.get("parts", []),
                "resource_bindings": blob.get("resource_bindings", []),
                "handle_creates": blob.get("handle_creates", []),
                "disassembly_path": blob.get("disassembly_path", ""),
                "disassembly_status": blob.get("disassembly_status", ""),
            }
        )
    return result


def _add_binding_slots(truth: dict[str, Any], blob: Mapping[str, Any], source: str = "shader_reflection") -> None:
    for binding in blob.get("resource_bindings", []) or []:
        if not isinstance(binding, Mapping):
            continue
        btype = str(binding.get("type", "")).lower()
        row = {
            "name": binding.get("name", ""),
            "hlsl_bind": binding.get("hlsl_bind", ""),
            "register": binding.get("register", ""),
            "space": binding.get("space", ""),
            "count": binding.get("count", ""),
            "source": source,
        }
        if btype == "texture":
            truth["srv_slots"].append({**row, "slot": len(truth["srv_slots"]), "format": binding.get("format", ""), "dimension": binding.get("dim", ""), "binding_id": binding.get("id", "")})
        elif btype == "sampler":
            truth["sampler_states"].append({**row, "slot": len(truth["sampler_states"])})
        elif btype == "cbuffer":
            truth["constant_buffers"].append({**row, "slot": len(truth["constant_buffers"])})


def _add_descriptors(truth: dict[str, Any], candidate: Mapping[str, Any]) -> None:
    tables = candidate.get("state", {}).get("root_descriptor_tables", {}) if isinstance(candidate.get("state"), Mapping) else {}
    for root_param, table in tables.items():
        for descriptor in table.get("descriptors", []) if isinstance(table, Mapping) else []:
            if not isinstance(descriptor, Mapping):
                continue
            dtype = descriptor.get("type")
            common = {
                "heap": descriptor.get("heap", ""),
                "index": descriptor.get("index", ""),
                "root_parameter": int(root_param),
                "source": descriptor.get("source", ""),
            }
            if dtype == "SRV":
                truth["srv_slots"].append(
                    {
                        **common,
                        "slot": len(truth["srv_slots"]),
                        "name": f"root_{root_param}_descriptor_{descriptor.get('index', '')}",
                        "resource": descriptor.get("resource", ""),
                        "resource_name": descriptor.get("resource_desc", {}).get("name", ""),
                        "format": descriptor.get("format", ""),
                        "dimension": descriptor.get("view_dimension", ""),
                        "resource_desc": descriptor.get("resource_desc", {}),
                    }
                )
            elif dtype == "Sampler":
                truth["sampler_states"].append(
                    {
                        **common,
                        "slot": len(truth["sampler_states"]),
                        "filter": descriptor.get("filter", ""),
                        "address_u": descriptor.get("address_u", ""),
                        "address_v": descriptor.get("address_v", ""),
                        "mip_lod_bias": descriptor.get("mip_lod_bias", ""),
                        "max_anisotropy": descriptor.get("max_anisotropy", ""),
                    }
                )
            elif dtype == "CBV":
                truth["constant_buffers"].append(
                    {
                        **common,
                        "slot": len(truth["constant_buffers"]),
                        "resource": descriptor.get("buffer_resource", descriptor.get("resource", "")),
                        "offset": descriptor.get("buffer_offset", ""),
                        "size_in_bytes": descriptor.get("size_in_bytes", ""),
                    }
                )


def candidate_to_truth_input(
    candidate_report: Mapping[str, Any],
    *,
    rank: int,
    capture_path: str = "",
    shader_blob_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = _candidate(candidate_report, rank)
    state = candidate.get("state", {}) if isinstance(candidate.get("state"), Mapping) else {}
    pipeline = candidate.get("pipeline_description", {}) if isinstance(candidate.get("pipeline_description"), Mapping) else {}
    shaders = pipeline.get("shaders", {}) if isinstance(pipeline.get("shaders"), Mapping) else {}
    chunk = candidate.get("chunk_index", "")
    vs_blob = _blob(shader_blob_manifest, rank=rank, chunk_index=chunk, stage="VS")
    ps_blob = _blob(shader_blob_manifest, rank=rank, chunk_index=chunk, stage="PS")
    cs_blob = _blob(shader_blob_manifest, rank=rank, chunk_index=chunk, stage="CS")
    truth: dict[str, Any] = {
        "material_name": f"draw_{chunk}" if "index_count" in candidate else f"dispatch_{chunk}",
        "drawcall": f"chunk_{chunk}",
        "capture_path": capture_path or candidate_report.get("capture_xml", ""),
        "pipeline_state": state.get("pipeline_state", ""),
        "root_signature": state.get("graphics_root_signature", state.get("compute_root_signature", "")),
        "index_count": candidate.get("index_count", ""),
        "dispatch_groups": candidate.get("dispatch_groups", {}),
        "srv_slots": [],
        "sampler_states": [],
        "constant_buffers": [],
        "vertex_shader": _shader(shaders.get("VS", {}) if isinstance(shaders, Mapping) else {}, vs_blob),
        "pixel_shader": _shader(shaders.get("PS", {}) if isinstance(shaders, Mapping) else {}, ps_blob),
        "compute_shader": _shader(shaders.get("CS", {}) if isinstance(shaders, Mapping) else {}, cs_blob),
        "blend_state": pipeline.get("blend_state", {}),
        "raster_state": pipeline.get("raster_state", {}),
        "depth_stencil_state": pipeline.get("depth_stencil_state", {}),
        "render_target_formats": pipeline.get("rtv_formats", []),
        "dsv_format": pipeline.get("dsv_format", ""),
        "normal_y_mode_unresolved": True,
    }
    for root_param, cbv in state.get("root_cbvs", {}).items() if isinstance(state.get("root_cbvs"), Mapping) else []:
        if isinstance(cbv, Mapping):
            truth["constant_buffers"].append({"slot": int(root_param), "root_parameter": int(root_param), **dict(cbv)})
    _add_descriptors(truth, candidate)
    for blob in (ps_blob, cs_blob, vs_blob):
        _add_binding_slots(truth, blob)
    return truth


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draw-candidates-json", type=Path)
    parser.add_argument("--dispatch-candidates-json", type=Path)
    parser.add_argument("--shader-blob-manifest", type=Path)
    parser.add_argument("--rank", type=int, required=True)
    parser.add_argument("--capture-path", default="")
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.draw_candidates_json or args.dispatch_candidates_json
    if source is None:
        raise SystemExit("--draw-candidates-json or --dispatch-candidates-json required")
    report = json.loads(source.read_text(encoding="utf-8"))
    manifest = json.loads(args.shader_blob_manifest.read_text(encoding="utf-8")) if args.shader_blob_manifest else None
    truth = candidate_to_truth_input(report, rank=args.rank, capture_path=args.capture_path, shader_blob_manifest=manifest)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
