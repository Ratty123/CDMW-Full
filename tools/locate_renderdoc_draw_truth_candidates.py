from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.renderdoc_xml_common import (
    as_int,
    chunk_index,
    chunks,
    find_named,
    load_xml,
    named_value,
    parse_descriptor_maps,
    parse_pipeline_states,
    parse_resource_descriptions,
    parse_root_signatures,
    resolve_descriptor,
)


def _descriptor_window(
    descriptors: dict[tuple[str, int], dict[str, Any]],
    copies: dict[tuple[str, int], tuple[str, int]],
    heap: object,
    index: object,
    width: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(max(1, int(width))):
        record = resolve_descriptor(descriptors, copies, heap, as_int(index) + offset)
        if record:
            rows.append(record)
    return rows


def _candidate_descriptors(candidate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    state = candidate.get("state", {})
    if not isinstance(state, Mapping):
        return []
    tables = state.get("root_descriptor_tables", {})
    if not isinstance(tables, Mapping):
        return []
    descriptors: list[Mapping[str, Any]] = []
    for table in tables.values():
        if isinstance(table, Mapping):
            descriptors.extend(item for item in table.get("descriptors", []) if isinstance(item, Mapping))
    return descriptors


def _candidate_selection_evidence(candidate: Mapping[str, Any]) -> dict[str, int]:
    descriptors = _candidate_descriptors(candidate)
    srvs = [item for item in descriptors if item.get("type") == "SRV"]
    samplers = [item for item in descriptors if item.get("type") == "Sampler"]
    cbvs = [item for item in descriptors if item.get("type") == "CBV"]
    state = candidate.get("state", {})
    root_cbvs = state.get("root_cbvs", {}) if isinstance(state, Mapping) else {}
    shaders = candidate.get("pipeline_description", {}).get("shaders", {})
    ps = shaders.get("PS", {}) if isinstance(shaders, Mapping) else {}
    formats = [
        str(item.get("format") or item.get("resource_desc", {}).get("format", ""))
        for item in srvs
        if isinstance(item.get("resource_desc", {}), Mapping)
    ]
    index_count = as_int(candidate.get("index_count", 0))
    return {
        "pixel_shader": int(isinstance(ps, Mapping) and (as_int(ps.get("blob_id", 0)) > 0 or as_int(ps.get("byte_length", 0)) > 0)),
        "plausible_index_count": int(100 <= index_count <= 1_000_000),
        "bc_srv_count": sum(1 for fmt in formats if "BC" in fmt),
        "srv_count": len(srvs),
        "sampler_count": len(samplers),
        "constant_buffer_count": len(cbvs) + (len(root_cbvs) if isinstance(root_cbvs, Mapping) else 0),
        "index_count": min(index_count, 1_000_000),
    }


def _candidate_selection_score(candidate: Mapping[str, Any]) -> tuple[int, ...]:
    evidence = _candidate_selection_evidence(candidate)
    return (
        evidence["pixel_shader"],
        evidence["plausible_index_count"],
        int(evidence["bc_srv_count"] > 0),
        int(evidence["sampler_count"] > 0),
        int(evidence["constant_buffer_count"] > 0),
        evidence["index_count"],
        evidence["bc_srv_count"],
        evidence["sampler_count"],
        evidence["constant_buffer_count"],
        evidence["srv_count"],
        -as_int(candidate.get("chunk_index", 0)),
    )


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=_candidate_selection_score, reverse=True)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
        candidate["selection_evidence"] = _candidate_selection_evidence(candidate)
    return ranked


def locate_draw_truth_candidates(xml_path: Path, *, descriptor_window: int = 4) -> dict[str, Any]:
    root = load_xml(Path(xml_path))
    resources = parse_resource_descriptions(root)
    descriptors, copies = parse_descriptor_maps(root, resources)
    psos = parse_pipeline_states(root)
    roots = parse_root_signatures(root)
    state_by_command: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for chunk in chunks(root):
        name = chunk.attrib.get("name", "")
        command_list = str(named_value(chunk, "pCommandList", ""))
        if command_list and command_list not in state_by_command:
            state_by_command[command_list] = {"root_descriptor_tables": {}, "root_cbvs": {}}
        state = state_by_command.get(command_list, {})
        if "SetPipelineState" in name and command_list:
            state["pipeline_state"] = as_int(named_value(chunk, "pPipelineState", 0))
        elif "SetGraphicsRootSignature" in name and command_list:
            state["graphics_root_signature"] = as_int(named_value(chunk, "pRootSignature", 0))
        elif "SetGraphicsRootDescriptorTable" in name and command_list:
            root_param = str(named_value(chunk, "RootParameterIndex", ""))
            base = next((elem for elem in chunk.iter() if elem.attrib.get("name") == "BaseDescriptor"), chunk)
            heap = named_value(base, "heap", "")
            index = named_value(base, "index", "")
            state.setdefault("root_descriptor_tables", {})[root_param] = {
                "heap": as_int(heap),
                "index": as_int(index),
                "descriptors": _descriptor_window(descriptors, copies, heap, index, descriptor_window),
            }
        elif "SetGraphicsRootConstantBufferView" in name and command_list:
            root_param = str(named_value(chunk, "RootParameterIndex", ""))
            buffer_location = find_named(chunk, "BufferLocation")
            state.setdefault("root_cbvs", {})[root_param] = {
                "gpu_address": named_value(chunk, "BufferLocation", ""),
                "resource": named_value(buffer_location, "Buffer", "") if buffer_location is not None else "",
                "offset": named_value(buffer_location, "Offset", "") if buffer_location is not None else "",
                "source": "set_graphics_root_constant_buffer_view",
            }
        elif "DrawIndexedInstanced" in name:
            pso = state.get("pipeline_state", 0)
            root_sig = state.get("graphics_root_signature", 0) or psos.get(str(pso), {}).get("root_signature", 0)
            candidate_state = {
                "pipeline_state": pso,
                "graphics_root_signature": root_sig,
                "primitive_topology": state.get("primitive_topology", ""),
                "root_descriptor_tables": state.get("root_descriptor_tables", {}),
                "root_cbvs": state.get("root_cbvs", {}),
            }
            candidates.append(
                {
                    "rank": len(candidates) + 1,
                    "action_rank": len(candidates) + 1,
                    "chunk_index": chunk_index(chunk),
                    "command_list": as_int(command_list),
                    "index_count": as_int(named_value(chunk, "IndexCountPerInstance", 0)),
                    "instance_count": as_int(named_value(chunk, "InstanceCount", 0)),
                    "start_index_location": as_int(named_value(chunk, "StartIndexLocation", 0)),
                    "base_vertex_location": as_int(named_value(chunk, "BaseVertexLocation", 0)),
                    "state": candidate_state,
                    "pipeline_description": psos.get(str(pso), {}),
                    "root_signature_description": roots.get(str(root_sig), {}),
                }
            )
    ranked_candidates = _rank_candidates(candidates)
    return {
        "status": "draw_candidates_located",
        "capture_xml": str(xml_path),
        "draw_indexed_count": len(candidates),
        "candidate_count": len(candidates),
        "resource_name_count": sum(1 for item in resources.values() if item.get("name")),
        "candidates": ranked_candidates,
    }


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "chunk_index", "pipeline_state", "index_count", "instance_count"])
        writer.writeheader()
        for candidate in report.get("candidates", []):
            writer.writerow(
                {
                    "rank": candidate.get("rank", ""),
                    "chunk_index": candidate.get("chunk_index", ""),
                    "pipeline_state": candidate.get("state", {}).get("pipeline_state", ""),
                    "index_count": candidate.get("index_count", ""),
                    "instance_count": candidate.get("instance_count", ""),
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--descriptor-window", type=int, default=4)
    args = parser.parse_args(argv)
    report = locate_draw_truth_candidates(args.xml, descriptor_window=args.descriptor_window)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.out_csv:
        _write_csv(args.out_csv, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
