from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.locate_renderdoc_draw_truth_candidates import (
    _buffer_location,
    _child,
    _chunk_index,
    _copy_descriptors,
    _enum_string,
    _handle,
    _parse_cbv_descriptor,
    _parse_descriptor_heaps,
    _parse_inline_d3d12_descriptors,
    _parse_resource_desc,
    _parse_resource_name,
    _parse_root_signature_description,
    _parse_srv_uav_descriptor,
    _resolve_descriptor_window,
    _resource_id,
    _shader_bytecode,
    _thread_id,
    _uint,
)


SCHEMA_VERSION = 1


def _parse_compute_pipeline_state_description(chunk: ET.Element) -> tuple[int, dict[str, Any]] | None:
    desc = _child(chunk, "pDesc")
    pso = _resource_id(chunk, "pPipelineState")
    if desc is None or not pso:
        return None
    return pso, {
        "pipeline_state": pso,
        "created_at_chunk": _chunk_index(chunk),
        "root_signature": _resource_id(desc, "pRootSignature"),
        "shaders": {"CS": _shader_bytecode(desc, "CS")},
        "inline_shader_ids": [_resource_id(chunk, "InlineShaderID")],
        "flags": _enum_string(desc, "Flags"),
    }


def _state_snapshot(
    state: Mapping[str, Any],
    descriptor_map: Mapping[tuple[int, int], Mapping[str, Any]],
    resource_descs: Mapping[int, Mapping[str, Any]],
    descriptor_window: int,
) -> dict[str, Any]:
    root_tables = {}
    for root_index, handle in dict(state.get("root_descriptor_tables", {})).items():
        root_tables[str(root_index)] = {
            "base": dict(handle),
            "descriptors": _resolve_descriptor_window(handle, descriptor_map, resource_descs, descriptor_window),
        }
    return {
        "pipeline_state": state.get("pipeline_state", 0),
        "compute_root_signature": state.get("compute_root_signature", 0),
        "descriptor_heaps": list(state.get("descriptor_heaps", [])),
        "root_descriptor_tables": root_tables,
        "root_cbvs": dict(state.get("root_cbvs", {})),
        "root_constants": dict(state.get("root_constants", {})),
    }


def locate_dispatch_truth_candidates(
    xml_path: Path,
    *,
    min_thread_groups: int = 1,
    max_candidates: int = 512,
    descriptor_window: int = 16,
) -> dict[str, Any]:
    descriptor_map: dict[tuple[int, int], dict[str, Any]] = {}
    resource_descs: dict[int, dict[str, Any]] = {}
    resource_names: dict[int, str] = {}
    states: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "root_descriptor_tables": {},
            "root_cbvs": {},
            "root_constants": {},
            "descriptor_heaps": [],
        }
    )
    pipeline_descriptions: dict[int, dict[str, Any]] = {}
    root_signature_descriptions: dict[int, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    pso_counts: Counter[int] = Counter()
    dispatch_count = 0

    for _, chunk in ET.iterparse(str(xml_path), events=("end",)):
        if chunk.tag != "chunk":
            continue
        name = chunk.attrib.get("name", "")
        command_list = _resource_id(chunk, "pCommandList")
        if name in {
            "ID3D12Device10::Device_CreatePlacedResource2",
            "ID3D12Device10::CreatePlacedResource2",
            "ID3D12Device10::Device_CreateCommittedResource3",
            "ID3D12Device::CreateCommittedResource",
        }:
            parsed = _parse_resource_desc(chunk)
            if parsed:
                resource, desc = parsed
                if resource in resource_names:
                    desc["name"] = resource_names[resource]
                resource_descs[resource] = desc
        elif name.endswith("::SetName"):
            parsed_name = _parse_resource_name(chunk)
            if parsed_name:
                resource, resource_name = parsed_name
                resource_names[resource] = resource_name
                if resource in resource_descs:
                    resource_descs[resource]["name"] = resource_name
        elif name == "ID3D12Device::CreateShaderResourceView":
            parsed = _parse_srv_uav_descriptor(chunk, "SRV")
            if parsed:
                key, descriptor = parsed
                descriptor_map[key] = descriptor
        elif name == "ID3D12Device::CreateUnorderedAccessView":
            parsed = _parse_srv_uav_descriptor(chunk, "UAV")
            if parsed:
                key, descriptor = parsed
                descriptor_map[key] = descriptor
        elif name == "ID3D12Device::CreateConstantBufferView":
            parsed = _parse_cbv_descriptor(chunk)
            if parsed:
                key, descriptor = parsed
                descriptor_map[key] = descriptor
        elif name == "ID3D12Device::CreateComputePipeline":
            parsed_compute = _parse_compute_pipeline_state_description(chunk)
            if parsed_compute:
                pso, description = parsed_compute
                pipeline_descriptions[pso] = description
        elif name == "ID3D12Device::CreateRootSignature":
            parsed_root = _parse_root_signature_description(chunk)
            if parsed_root:
                root_signature, description = parsed_root
                root_signature_descriptions[root_signature] = description
        elif name == "ID3D12Device::CopyDescriptorsSimple":
            _copy_descriptors(chunk, descriptor_map)
        elif name == "Internal::Initial Contents":
            descriptor_map.update(_parse_inline_d3d12_descriptors(chunk))
        elif command_list:
            state = states[command_list]
            if name == "ID3D12GraphicsCommandList::SetPipelineState":
                state["pipeline_state"] = _resource_id(chunk, "pPipelineState")
            elif name == "ID3D12GraphicsCommandList::SetComputeRootSignature":
                state["compute_root_signature"] = _resource_id(chunk, "pRootSignature")
            elif name == "ID3D12GraphicsCommandList::SetDescriptorHeaps":
                state["descriptor_heaps"] = _parse_descriptor_heaps(chunk)
            elif name == "ID3D12GraphicsCommandList::SetComputeRootDescriptorTable":
                state["root_descriptor_tables"][_uint(chunk, "RootParameterIndex")] = _handle(_child(chunk, "BaseDescriptor"))
            elif name == "ID3D12GraphicsCommandList::SetComputeRootConstantBufferView":
                state["root_cbvs"][_uint(chunk, "RootParameterIndex")] = _buffer_location(_child(chunk, "BufferLocation"))
            elif name == "ID3D12GraphicsCommandList::Dispatch":
                dispatch_count += 1
                group_x = _uint(chunk, "ThreadGroupCountX")
                group_y = _uint(chunk, "ThreadGroupCountY")
                group_z = _uint(chunk, "ThreadGroupCountZ")
                group_total = group_x * group_y * group_z
                if group_total >= min_thread_groups:
                    snapshot = _state_snapshot(state, descriptor_map, resource_descs, descriptor_window)
                    pso_id = int(snapshot.get("pipeline_state", 0) or 0)
                    root_sig_id = int(snapshot.get("compute_root_signature", 0) or 0)
                    pso_counts[pso_id] += 1
                    candidates.append(
                        {
                            "chunk_index": _chunk_index(chunk),
                            "thread_id": _thread_id(chunk),
                            "command_list": command_list,
                            "dispatch_groups": {"x": group_x, "y": group_y, "z": group_z, "total": group_total},
                            "rank_score": group_total,
                            "state": snapshot,
                            "pipeline_description": dict(pipeline_descriptions.get(pso_id, {})),
                            "root_signature_description": dict(root_signature_descriptions.get(root_sig_id, {})),
                        }
                    )
        chunk.clear()

    ranked = sorted(candidates, key=lambda item: (-int(item["rank_score"]), int(item["chunk_index"])))[:max_candidates]
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return {
        "schema_version": SCHEMA_VERSION,
        "capture_xml": str(xml_path),
        "dispatch_count": dispatch_count,
        "candidate_count": len(ranked),
        "descriptor_count": len(descriptor_map),
        "resource_description_count": len(resource_descs),
        "resource_name_count": len(resource_names),
        "pipeline_description_count": len(pipeline_descriptions),
        "root_signature_description_count": len(root_signature_descriptions),
        "pso_dispatch_counts": [
            {"pipeline_state": pso, "dispatch_count": count}
            for pso, count in pso_counts.most_common()
            if pso
        ],
        "candidates": ranked,
    }


def write_candidates_csv(report: Mapping[str, Any], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["rank", "chunk_index", "command_list", "groups_x", "groups_y", "groups_z", "groups_total", "pipeline_state", "compute_root_signature"],
        )
        writer.writeheader()
        for candidate in report.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            groups = candidate.get("dispatch_groups", {}) if isinstance(candidate.get("dispatch_groups"), Mapping) else {}
            state = candidate.get("state", {}) if isinstance(candidate.get("state"), Mapping) else {}
            writer.writerow(
                {
                    "rank": candidate.get("rank", ""),
                    "chunk_index": candidate.get("chunk_index", ""),
                    "command_list": candidate.get("command_list", ""),
                    "groups_x": groups.get("x", ""),
                    "groups_y": groups.get("y", ""),
                    "groups_z": groups.get("z", ""),
                    "groups_total": groups.get("total", ""),
                    "pipeline_state": state.get("pipeline_state", "") if isinstance(state, Mapping) else "",
                    "compute_root_signature": state.get("compute_root_signature", "") if isinstance(state, Mapping) else "",
                }
            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Locate RenderDoc D3D12 compute dispatch candidates for shader truth inspection.")
    parser.add_argument("--xml", required=True, help="RenderDoc XML or zip.xml export.")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", default="")
    parser.add_argument("--min-thread-groups", type=int, default=1)
    parser.add_argument("--max-candidates", type=int, default=512)
    parser.add_argument("--descriptor-window", type=int, default=16)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = locate_dispatch_truth_candidates(
        Path(args.xml),
        min_thread_groups=int(args.min_thread_groups),
        max_candidates=int(args.max_candidates),
        descriptor_window=int(args.descriptor_window),
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        write_candidates_csv(report, Path(args.out_csv))
    print(f"wrote {report['candidate_count']} dispatch candidate(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
