from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for item in element:
        if item.attrib.get("name") == name:
            return item
    return None


def _text(element: ET.Element | None, default: str = "") -> str:
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _int_text(element: ET.Element | None, default: int = 0) -> int:
    try:
        return int(_text(element, str(default)), 0)
    except (TypeError, ValueError):
        return default


def _resource_id(element: ET.Element, name: str) -> int:
    return _int_text(_child(element, name))


def _uint(element: ET.Element, name: str, default: int = 0) -> int:
    return _int_text(_child(element, name), default)


def _enum_string(element: ET.Element, name: str) -> str:
    item = _child(element, name)
    if item is None:
        return ""
    return str(item.attrib.get("string") or _text(item))


def _handle(element: ET.Element | None) -> dict[str, int]:
    if element is None:
        return {"heap": 0, "index": 0}
    return {"heap": _resource_id(element, "heap"), "index": _uint(element, "index")}


def _buffer_location(element: ET.Element | None) -> dict[str, int]:
    if element is None:
        return {"resource": 0, "offset": 0}
    return {"resource": _resource_id(element, "Buffer"), "offset": _uint(element, "Offset")}


def _chunk_index(chunk: ET.Element) -> int:
    try:
        return int(chunk.attrib.get("chunkIndex", "0"))
    except ValueError:
        return 0


def _thread_id(chunk: ET.Element) -> int:
    try:
        return int(chunk.attrib.get("threadID", "0"))
    except ValueError:
        return 0


def _descriptor_key(handle: Mapping[str, int]) -> tuple[int, int]:
    return (int(handle.get("heap", 0)), int(handle.get("index", 0)))


def _parse_resource_desc(chunk: ET.Element) -> tuple[int, dict[str, Any]] | None:
    desc = _child(chunk, "pDesc")
    if desc is None:
        desc = _child(chunk, "desc")
    resource = _resource_id(chunk, "pResource")
    if desc is None or not resource:
        return None
    return resource, {
        "resource": resource,
        "dimension": _enum_string(desc, "Dimension"),
        "width": _uint(desc, "Width"),
        "height": _uint(desc, "Height"),
        "depth_or_array_size": _uint(desc, "DepthOrArraySize"),
        "mip_levels": _uint(desc, "MipLevels"),
        "format": _enum_string(desc, "Format"),
        "layout": _enum_string(desc, "Layout"),
        "flags": _enum_string(desc, "Flags"),
    }


def _parse_resource_name(chunk: ET.Element) -> tuple[int, str] | None:
    resource = _resource_id(chunk, "pResource")
    name = _text(_child(chunk, "Name"))
    if not resource or not name:
        return None
    return resource, name


def _parse_srv_uav_descriptor(chunk: ET.Element, descriptor_type: str) -> tuple[tuple[int, int], dict[str, Any]] | None:
    desc = _child(chunk, "desc")
    dst = _child(chunk, "dst")
    if desc is None or dst is None:
        return None
    descriptor = _child(desc, "Descriptor")
    payload = {
        "type": descriptor_type,
        "resource": _resource_id(desc, "Resource"),
        "format": _enum_string(descriptor, "Format") if descriptor is not None else "",
        "view_dimension": _enum_string(descriptor, "ViewDimension") if descriptor is not None else "",
        "component_mapping": _enum_string(descriptor, "Shader4ComponentMapping") if descriptor is not None else "",
        "created_at_chunk": _chunk_index(chunk),
    }
    return _descriptor_key(_handle(dst)), payload


def _parse_cbv_descriptor(chunk: ET.Element) -> tuple[tuple[int, int], dict[str, Any]] | None:
    desc = _child(chunk, "desc")
    dst = _child(chunk, "dst")
    if desc is None or dst is None:
        return None
    descriptor = _child(desc, "Descriptor")
    payload = {
        "type": "CBV",
        "buffer_location": _buffer_location(_child(descriptor, "BufferLocation") if descriptor is not None else None),
        "size_in_bytes": _uint(descriptor, "SizeInBytes") if descriptor is not None else 0,
        "created_at_chunk": _chunk_index(chunk),
    }
    return _descriptor_key(_handle(dst)), payload


def _parse_inline_d3d12_descriptors(chunk: ET.Element) -> dict[tuple[int, int], dict[str, Any]]:
    output: dict[tuple[int, int], dict[str, Any]] = {}
    for desc in chunk.iter("struct"):
        if desc.attrib.get("typename") != "D3D12Descriptor":
            continue
        descriptor_type = _enum_string(desc, "type") or "unknown"
        handle = {"heap": _resource_id(desc, "heap"), "index": _uint(desc, "index")}
        key = _descriptor_key(handle)
        if not key[0]:
            continue
        descriptor = _child(desc, "Descriptor")
        payload: dict[str, Any] = {
            "type": descriptor_type,
            "resource": _resource_id(desc, "Resource"),
            "created_at_chunk": _chunk_index(chunk),
            "source": "initial_contents_descriptor",
        }
        descriptor_type_upper = descriptor_type.upper()
        if descriptor_type_upper in {"SRV", "UAV"}:
            payload.update(
                {
                    "format": _enum_string(descriptor, "Format") if descriptor is not None else "",
                    "view_dimension": _enum_string(descriptor, "ViewDimension") if descriptor is not None else "",
                    "component_mapping": _enum_string(descriptor, "Shader4ComponentMapping") if descriptor is not None else "",
                }
            )
        elif descriptor_type_upper == "CBV":
            payload.update(
                {
                    "size_in_bytes": _uint(descriptor, "SizeInBytes") if descriptor is not None else 0,
                    "buffer_location": _buffer_location(_child(descriptor, "BufferLocation") if descriptor is not None else None),
                }
            )
        elif "SAMPLER" in descriptor_type_upper:
            payload.update(
                {
                    "filter": _enum_string(descriptor, "Filter") if descriptor is not None else "",
                    "address_u": _enum_string(descriptor, "AddressU") if descriptor is not None else "",
                    "address_v": _enum_string(descriptor, "AddressV") if descriptor is not None else "",
                    "address_w": _enum_string(descriptor, "AddressW") if descriptor is not None else "",
                    "mip_lod_bias": _text(_child(descriptor, "MipLODBias")) if descriptor is not None else "",
                    "max_anisotropy": _uint(descriptor, "MaxAnisotropy") if descriptor is not None else 0,
                    "comparison_func": _enum_string(descriptor, "ComparisonFunc") if descriptor is not None else "",
                    "min_lod": _text(_child(descriptor, "MinLOD")) if descriptor is not None else "",
                    "max_lod": _text(_child(descriptor, "MaxLOD")) if descriptor is not None else "",
                }
            )
        output[key] = payload
    return output


def _copy_descriptors(chunk: ET.Element, descriptor_map: dict[tuple[int, int], dict[str, Any]]) -> None:
    copies = _child(chunk, "DescriptorCopies")
    if copies is None:
        return
    for entry in copies:
        dst = _handle(_child(entry, "dst"))
        src = _handle(_child(entry, "src"))
        src_key = _descriptor_key(src)
        dst_key = _descriptor_key(dst)
        payload = copy.deepcopy(descriptor_map.get(src_key, {"type": "unknown", "source_handle": src}))
        payload["copied_from"] = src
        payload["copied_at_chunk"] = _chunk_index(chunk)
        descriptor_map[dst_key] = payload


def _parse_index_buffer(chunk: ET.Element) -> dict[str, Any]:
    view = _child(chunk, "pView")
    return {
        "buffer_location": _buffer_location(_child(view, "BufferLocation") if view is not None else None),
        "size_in_bytes": _uint(view, "SizeInBytes") if view is not None else 0,
        "format": _enum_string(view, "Format") if view is not None else "",
    }


def _parse_descriptor_heaps(chunk: ET.Element) -> list[int]:
    heaps = _child(chunk, "ppDescriptorHeaps")
    if heaps is None:
        heaps = _child(chunk, "pDescriptorHeaps")
    if heaps is None:
        return []
    return [_int_text(item) for item in heaps if item.tag == "ResourceId"]


def _bool_text(element: ET.Element | None) -> bool | str:
    text = _text(element).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "1":
        return True
    if text == "0":
        return False
    return _text(element)


def _buffer_ref(element: ET.Element | None) -> dict[str, Any]:
    if element is None:
        return {"blob_id": 0, "byte_length": 0}
    try:
        byte_length = int(element.attrib.get("byteLength", "0"))
    except ValueError:
        byte_length = 0
    return {"blob_id": _int_text(element), "byte_length": byte_length}


def _shader_bytecode(desc: ET.Element | None, name: str) -> dict[str, Any]:
    shader = _child(desc, name) if desc is not None else None
    if shader is None:
        return {"blob_id": 0, "byte_length": 0}
    result = _buffer_ref(_child(shader, "pShaderBytecode"))
    bytecode_length = _uint(shader, "BytecodeLength")
    if bytecode_length:
        result["byte_length"] = bytecode_length
    return result


def _first_render_target_blend(blend_state: ET.Element | None) -> dict[str, Any]:
    render_targets = _child(blend_state, "RenderTarget") if blend_state is not None else None
    first = next(iter(render_targets), None) if render_targets is not None else None
    if first is None:
        return {}
    return {
        "blend_enable": _bool_text(_child(first, "BlendEnable")),
        "logic_op_enable": _bool_text(_child(first, "LogicOpEnable")),
        "src_blend": _enum_string(first, "SrcBlend"),
        "dest_blend": _enum_string(first, "DestBlend"),
        "blend_op": _enum_string(first, "BlendOp"),
        "src_blend_alpha": _enum_string(first, "SrcBlendAlpha"),
        "dest_blend_alpha": _enum_string(first, "DestBlendAlpha"),
        "blend_op_alpha": _enum_string(first, "BlendOpAlpha"),
        "write_mask": _enum_string(first, "RenderTargetWriteMask"),
    }


def _render_target_formats(desc: ET.Element | None) -> list[str]:
    formats = _child(desc, "RTVFormats") if desc is not None else None
    if formats is None:
        return []
    return [str(item.attrib.get("string") or _text(item)) for item in formats.iter() if item.tag == "enum"]


def _input_layout_summary(desc: ET.Element | None) -> list[dict[str, Any]]:
    input_layout = _child(desc, "InputLayout") if desc is not None else None
    elements = _child(input_layout, "pInputElementDescs") if input_layout is not None else None
    if elements is None:
        return []
    summary: list[dict[str, Any]] = []
    for element in elements:
        semantic = _text(_child(element, "SemanticName"))
        if not semantic:
            semantic = _text(_child(element, "Semantic"))
        summary.append(
            {
                "semantic": semantic,
                "semantic_index": _uint(element, "SemanticIndex"),
                "format": _enum_string(element, "Format"),
                "input_slot": _uint(element, "InputSlot"),
                "aligned_byte_offset": _uint(element, "AlignedByteOffset"),
                "input_slot_class": _enum_string(element, "InputSlotClass"),
            }
        )
    return summary[:32]


def _parse_pipeline_state_description(chunk: ET.Element) -> tuple[int, dict[str, Any]] | None:
    desc = _child(chunk, "pDesc")
    pso = _resource_id(chunk, "pPipelineState")
    if desc is None or not pso:
        return None
    blend_state = _child(desc, "BlendState")
    rasterizer_state = _child(desc, "RasterizerState")
    depth_stencil_state = _child(desc, "DepthStencilState")
    sample_desc = _child(desc, "SampleDesc")
    inline_shader_array = _child(chunk, "InlineShaderIDs")
    inline_shader_ids = [_int_text(item) for item in inline_shader_array if item.tag == "ResourceId"] if inline_shader_array is not None else []
    return pso, {
        "pipeline_state": pso,
        "created_at_chunk": _chunk_index(chunk),
        "root_signature": _resource_id(desc, "pRootSignature"),
        "shaders": {
            name: _shader_bytecode(desc, name)
            for name in ("VS", "PS", "DS", "HS", "GS", "AS", "MS")
        },
        "inline_shader_ids": inline_shader_ids,
        "blend_state": {
            "alpha_to_coverage": _bool_text(_child(blend_state, "AlphaToCoverageEnable")),
            "independent_blend": _bool_text(_child(blend_state, "IndependentBlendEnable")),
            "rt0": _first_render_target_blend(blend_state),
        },
        "raster_state": {
            "fill_mode": _enum_string(rasterizer_state, "FillMode"),
            "cull_mode": _enum_string(rasterizer_state, "CullMode"),
            "front_counter_clockwise": _bool_text(_child(rasterizer_state, "FrontCounterClockwise")),
            "depth_clip_enable": _bool_text(_child(rasterizer_state, "DepthClipEnable")),
            "conservative_raster": _enum_string(rasterizer_state, "ConservativeRaster"),
        },
        "depth_stencil_state": {
            "depth_enable": _bool_text(_child(depth_stencil_state, "DepthEnable")),
            "depth_write_mask": _enum_string(depth_stencil_state, "DepthWriteMask"),
            "depth_func": _enum_string(depth_stencil_state, "DepthFunc"),
            "stencil_enable": _bool_text(_child(depth_stencil_state, "StencilEnable")),
        },
        "input_layout": _input_layout_summary(desc),
        "primitive_topology_type": _enum_string(desc, "PrimitiveTopologyType"),
        "ib_strip_cut_value": _enum_string(desc, "IBStripCutValue"),
        "num_render_targets": _uint(desc, "NumRenderTargets"),
        "rtv_formats": _render_target_formats(desc),
        "dsv_format": _enum_string(desc, "DSVFormat"),
        "sample_desc": {
            "count": _uint(sample_desc, "Count") if sample_desc is not None else 0,
            "quality": _uint(sample_desc, "Quality") if sample_desc is not None else 0,
        },
        "flags": _enum_string(desc, "Flags"),
    }


def _parse_root_signature_description(chunk: ET.Element) -> tuple[int, dict[str, Any]] | None:
    root_signature = _resource_id(chunk, "pRootSignature")
    if not root_signature:
        return None
    return root_signature, {
        "root_signature": root_signature,
        "created_at_chunk": _chunk_index(chunk),
        "blob": _buffer_ref(_child(chunk, "pBlobWithRootSignature")),
        "blob_length": _uint(chunk, "blobLengthInBytes"),
    }


def _resolve_descriptor_window(
    handle: Mapping[str, int],
    descriptor_map: Mapping[tuple[int, int], Mapping[str, Any]],
    resource_descs: Mapping[int, Mapping[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    base_heap = int(handle.get("heap", 0))
    base_index = int(handle.get("index", 0))
    output: list[dict[str, Any]] = []
    for offset in range(max(0, count)):
        key = (base_heap, base_index + offset)
        descriptor = dict(descriptor_map.get(key, {"type": "unresolved"}))
        descriptor["heap"] = key[0]
        descriptor["index"] = key[1]
        resource = int(descriptor.get("resource", 0) or descriptor.get("buffer_location", {}).get("resource", 0) or 0)
        if resource and resource in resource_descs:
            descriptor["resource_desc"] = dict(resource_descs[resource])
        output.append(descriptor)
    return output


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
        "state_object": state.get("state_object", 0),
        "graphics_root_signature": state.get("graphics_root_signature", 0),
        "descriptor_heaps": list(state.get("descriptor_heaps", [])),
        "root_descriptor_tables": root_tables,
        "root_cbvs": dict(state.get("root_cbvs", {})),
        "root_constants": dict(state.get("root_constants", {})),
        "index_buffer": dict(state.get("index_buffer", {})),
        "primitive_topology": state.get("primitive_topology", ""),
    }


def locate_draw_truth_candidates(
    xml_path: Path,
    *,
    min_index_count: int = 1,
    max_candidates: int = 256,
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
            "index_buffer": {},
        }
    )
    candidates: list[dict[str, Any]] = []
    pipeline_descriptions: dict[int, dict[str, Any]] = {}
    root_signature_descriptions: dict[int, dict[str, Any]] = {}
    pso_counts: Counter[int] = Counter()
    root_signature_counts: Counter[int] = Counter()
    draw_count = 0

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
        elif name == "ID3D12Device2::CreatePipelineState":
            parsed_pso = _parse_pipeline_state_description(chunk)
            if parsed_pso:
                pso, description = parsed_pso
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
            elif name == "ID3D12GraphicsCommandList4::SetPipelineState1":
                state["state_object"] = _resource_id(chunk, "pStateObject")
            elif name == "ID3D12GraphicsCommandList::SetGraphicsRootSignature":
                state["graphics_root_signature"] = _resource_id(chunk, "pRootSignature")
            elif name == "ID3D12GraphicsCommandList::SetDescriptorHeaps":
                state["descriptor_heaps"] = _parse_descriptor_heaps(chunk)
            elif name == "ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable":
                state["root_descriptor_tables"][_uint(chunk, "RootParameterIndex")] = _handle(_child(chunk, "BaseDescriptor"))
            elif name == "ID3D12GraphicsCommandList::SetGraphicsRootConstantBufferView":
                state["root_cbvs"][_uint(chunk, "RootParameterIndex")] = _buffer_location(_child(chunk, "BufferLocation"))
            elif name == "ID3D12GraphicsCommandList::SetGraphicsRoot32BitConstants":
                state["root_constants"][_uint(chunk, "RootParameterIndex")] = {
                    "num_values": _uint(chunk, "Num32BitValuesToSet"),
                    "dest_offset": _uint(chunk, "DestOffsetIn32BitValues"),
                    "set_at_chunk": _chunk_index(chunk),
                }
            elif name == "ID3D12GraphicsCommandList::IASetIndexBuffer":
                state["index_buffer"] = _parse_index_buffer(chunk)
            elif name == "ID3D12GraphicsCommandList::IASetPrimitiveTopology":
                state["primitive_topology"] = _enum_string(chunk, "PrimitiveTopology")
            elif name == "ID3D12GraphicsCommandList::DrawIndexedInstanced":
                draw_count += 1
                index_count = _uint(chunk, "IndexCountPerInstance")
                instance_count = _uint(chunk, "InstanceCount")
                if index_count >= min_index_count:
                    snapshot = _state_snapshot(state, descriptor_map, resource_descs, descriptor_window)
                    pso_counts[int(snapshot.get("pipeline_state", 0) or 0)] += 1
                    root_signature_counts[int(snapshot.get("graphics_root_signature", 0) or 0)] += 1
                    pso_id = int(snapshot.get("pipeline_state", 0) or 0)
                    root_sig_id = int(snapshot.get("graphics_root_signature", 0) or 0)
                    candidates.append(
                        {
                            "chunk_index": _chunk_index(chunk),
                            "thread_id": _thread_id(chunk),
                            "command_list": command_list,
                            "index_count": index_count,
                            "instance_count": instance_count,
                            "start_index": _uint(chunk, "StartIndexLocation"),
                            "base_vertex": _uint(chunk, "BaseVertexLocation"),
                            "rank_score": index_count * max(1, instance_count),
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
        "draw_indexed_count": draw_count,
        "candidate_count": len(ranked),
        "descriptor_count": len(descriptor_map),
        "resource_description_count": len(resource_descs),
        "resource_name_count": len(resource_names),
        "pso_draw_counts": [
            {"pipeline_state": pso, "draw_count": count}
            for pso, count in pso_counts.most_common()
            if pso
        ],
        "root_signature_draw_counts": [
            {"root_signature": root_sig, "draw_count": count}
            for root_sig, count in root_signature_counts.most_common()
            if root_sig
        ],
        "pipeline_description_count": len(pipeline_descriptions),
        "root_signature_description_count": len(root_signature_descriptions),
        "candidates": ranked,
    }


def _root_table_summary(candidate: Mapping[str, Any]) -> str:
    state = candidate.get("state", {}) if isinstance(candidate.get("state"), Mapping) else {}
    tables = state.get("root_descriptor_tables", {}) if isinstance(state.get("root_descriptor_tables"), Mapping) else {}
    parts = []
    for key, value in sorted(tables.items(), key=lambda item: int(item[0])):
        if not isinstance(value, Mapping):
            continue
        base = value.get("base", {})
        if isinstance(base, Mapping):
            parts.append(f"{key}={base.get('heap', 0)}:{base.get('index', 0)}")
    return ";".join(parts)


def write_candidates_csv(report: Mapping[str, Any], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "chunk_index",
                "command_list",
                "index_count",
                "instance_count",
                "pipeline_state",
                "graphics_root_signature",
                "root_descriptor_tables",
            ],
        )
        writer.writeheader()
        for candidate in report.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            state = candidate.get("state", {}) if isinstance(candidate.get("state"), Mapping) else {}
            writer.writerow(
                {
                    "rank": candidate.get("rank", ""),
                    "chunk_index": candidate.get("chunk_index", ""),
                    "command_list": candidate.get("command_list", ""),
                    "index_count": candidate.get("index_count", ""),
                    "instance_count": candidate.get("instance_count", ""),
                    "pipeline_state": state.get("pipeline_state", "") if isinstance(state, Mapping) else "",
                    "graphics_root_signature": state.get("graphics_root_signature", "") if isinstance(state, Mapping) else "",
                    "root_descriptor_tables": _root_table_summary(candidate),
                }
            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Locate RenderDoc D3D12 draw candidates for shader truth inspection.")
    parser.add_argument("--xml", required=True, help="RenderDoc XML or zip.xml export.")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", default="")
    parser.add_argument("--min-index-count", type=int, default=1)
    parser.add_argument("--max-candidates", type=int, default=256)
    parser.add_argument("--descriptor-window", type=int, default=16)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = locate_draw_truth_candidates(
        Path(args.xml),
        min_index_count=int(args.min_index_count),
        max_candidates=int(args.max_candidates),
        descriptor_window=int(args.descriptor_window),
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        write_candidates_csv(report, Path(args.out_csv))
    print(f"wrote {report['candidate_count']} draw candidate(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
