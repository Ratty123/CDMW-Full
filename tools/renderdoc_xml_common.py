from __future__ import annotations

from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Iterable


def load_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return default


def elem_value(elem: ET.Element | None) -> Any:
    if elem is None:
        return ""
    if "string" in elem.attrib:
        return elem.attrib["string"]
    text = (elem.text or "").strip()
    tag = local_name(elem.tag)
    if tag in {"uint", "int", "ResourceId"}:
        return as_int(text)
    if tag == "bool":
        return text.lower() == "true"
    return text


def direct_child(elem: ET.Element, name: str) -> ET.Element | None:
    for child in list(elem):
        if child.attrib.get("name") == name:
            return child
    return None


def find_named(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem.iter():
        if child.attrib.get("name") == name:
            return child
    return None


def named_value(elem: ET.Element, name: str, default: Any = "") -> Any:
    found = find_named(elem, name)
    if found is None:
        return default
    value = elem_value(found)
    return default if value == "" else value


def child_named_value(elem: ET.Element, name: str, default: Any = "") -> Any:
    found = direct_child(elem, name)
    if found is None:
        return default
    value = elem_value(found)
    return default if value == "" else value


def chunks(root: ET.Element) -> list[ET.Element]:
    return [elem for elem in root.iter() if local_name(elem.tag) == "chunk"]


def chunk_index(chunk: ET.Element) -> int:
    return as_int(chunk.attrib.get("chunkIndex", chunk.attrib.get("index", 0)))


def descriptor_key(heap: object, index: object) -> tuple[str, int]:
    return (str(heap), as_int(index))


def parse_resource_descriptions(root: ET.Element) -> dict[str, dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}
    for chunk in chunks(root):
        name = chunk.attrib.get("name", "")
        if "Create" in name and "Resource" in name:
            resource = named_value(chunk, "pResource", "")
            if resource == "":
                continue
            desc = find_named(chunk, "pDesc")
            if desc is None:
                desc = chunk
            resources[str(resource)] = {
                "resource": as_int(resource),
                "dimension": named_value(desc, "Dimension", ""),
                "width": as_int(named_value(desc, "Width", 0)),
                "height": as_int(named_value(desc, "Height", 0)),
                "depth_or_array_size": as_int(named_value(desc, "DepthOrArraySize", 0)),
                "mip_levels": as_int(named_value(desc, "MipLevels", 0)),
                "format": named_value(desc, "Format", ""),
                "layout": named_value(desc, "Layout", ""),
                "flags": named_value(desc, "Flags", ""),
            }
        if "SetName" in name:
            resource = named_value(chunk, "pResource", "")
            if resource != "":
                resources.setdefault(str(resource), {"resource": as_int(resource)})["name"] = named_value(chunk, "Name", "")
    return resources


def _descriptor_desc(struct: ET.Element) -> dict[str, Any]:
    desc = find_named(struct, "Descriptor")
    if desc is None:
        desc = find_named(struct, "desc")
    if desc is None:
        desc = struct
    return {
        "format": named_value(desc, "Format", ""),
        "view_dimension": named_value(desc, "ViewDimension", ""),
        "shader4_component_mapping": named_value(desc, "Shader4ComponentMapping", ""),
        "most_detailed_mip": named_value(desc, "MostDetailedMip", ""),
        "mip_levels": named_value(desc, "MipLevels", ""),
        "filter": named_value(desc, "Filter", ""),
        "address_u": named_value(desc, "AddressU", ""),
        "address_v": named_value(desc, "AddressV", ""),
        "address_w": named_value(desc, "AddressW", ""),
        "mip_lod_bias": named_value(desc, "MipLODBias", ""),
        "max_anisotropy": named_value(desc, "MaxAnisotropy", ""),
        "buffer_resource": named_value(desc, "Buffer", ""),
        "buffer_offset": named_value(desc, "Offset", ""),
        "size_in_bytes": named_value(desc, "SizeInBytes", ""),
    }


def _descriptor_type(value: object) -> str:
    text = str(value).lower()
    if "sampler" in text:
        return "Sampler"
    if "cbv" in text or text == "4096":
        return "CBV"
    if "uav" in text or text == "4098":
        return "UAV"
    return "SRV"


def parse_descriptor_maps(
    root: ET.Element, resources: dict[str, dict[str, Any]]
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, int], tuple[str, int]]]:
    descriptors: dict[tuple[str, int], dict[str, Any]] = {}
    copies: dict[tuple[str, int], tuple[str, int]] = {}
    for chunk in chunks(root):
        name = chunk.attrib.get("name", "")
        if "CreateShaderResourceView" in name:
            dst = find_named(chunk, "dst")
            if dst is None:
                dst = chunk
            heap = named_value(dst, "heap", "")
            index = named_value(dst, "index", "")
            resource = named_value(chunk, "Resource", "")
            desc = _descriptor_desc(chunk)
            resource_desc = dict(resources.get(str(resource), {}))
            if heap != "" and index != "":
                descriptors[descriptor_key(heap, index)] = {
                    "type": "SRV",
                    "resource": as_int(resource),
                    "heap": as_int(heap),
                    "index": as_int(index),
                    "source": "create_shader_resource_view",
                    "resource_desc": resource_desc,
                    **desc,
                }
        if "Initial Contents" in name:
            for struct in chunk.iter():
                if local_name(struct.tag) != "struct" or struct.attrib.get("typename") != "D3D12Descriptor":
                    continue
                dtype = str(named_value(struct, "type", "")).lower()
                heap = named_value(struct, "heap", "")
                index = named_value(struct, "index", "")
                if heap == "" or index == "":
                    continue
                desc = _descriptor_desc(struct)
                resource = named_value(struct, "Resource", "")
                record = {
                    "type": _descriptor_type(dtype),
                    "resource": as_int(resource) if resource != "" else "",
                    "heap": as_int(heap),
                    "index": as_int(index),
                    "source": "initial_contents_descriptor",
                    "resource_desc": dict(resources.get(str(resource), {})),
                    **desc,
                }
                descriptors[descriptor_key(heap, index)] = record
        if "CopyDescriptors" in name:
            for struct in chunk.iter():
                if local_name(struct.tag) != "struct":
                    continue
                dst = direct_child(struct, "dst")
                src = direct_child(struct, "src")
                if dst is not None and src is not None:
                    copies[descriptor_key(named_value(dst, "heap", ""), named_value(dst, "index", ""))] = descriptor_key(
                        named_value(src, "heap", ""), named_value(src, "index", "")
                    )
    return descriptors, copies


def resolve_descriptor(
    descriptors: dict[tuple[str, int], dict[str, Any]],
    copies: dict[tuple[str, int], tuple[str, int]],
    heap: object,
    index: object,
) -> dict[str, Any] | None:
    key = descriptor_key(heap, index)
    seen: set[tuple[str, int]] = set()
    while key in copies and key not in seen:
        seen.add(key)
        key = copies[key]
    record = descriptors.get(key)
    if not record:
        return None
    return dict(record)


def parse_root_signatures(root: ET.Element) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for chunk in chunks(root):
        if "CreateRootSignature" not in chunk.attrib.get("name", ""):
            continue
        root_id = named_value(chunk, "pRootSignature", "")
        if root_id == "":
            continue
        blob = find_named(chunk, "pBlobWithRootSignature")
        output[str(root_id)] = {
            "root_signature": as_int(root_id),
            "blob_id": as_int((blob.text or "").strip()) if blob is not None else 0,
            "blob_length": as_int(blob.attrib.get("byteLength", 0)) if blob is not None else as_int(named_value(chunk, "blobLengthInBytes", 0)),
        }
    return output


def _shader_info(stage_elem: ET.Element | None) -> dict[str, Any]:
    if stage_elem is None:
        return {}
    blob = find_named(stage_elem, "pShaderBytecode")
    return {
        "blob_id": as_int((blob.text or "").strip()) if blob is not None else 0,
        "byte_length": as_int(blob.attrib.get("byteLength", 0)) if blob is not None else as_int(named_value(stage_elem, "BytecodeLength", 0)),
    }


def parse_pipeline_states(root: ET.Element) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for chunk in chunks(root):
        name = chunk.attrib.get("name", "")
        if "CreatePipelineState" not in name and "CreateComputePipeline" not in name:
            continue
        pso = named_value(chunk, "pPipelineState", "")
        if pso == "":
            continue
        desc = find_named(chunk, "pDesc")
        if desc is None:
            desc = chunk
        shaders = {
            stage: _shader_info(find_named(desc, stage))
            for stage in ("VS", "PS", "GS", "HS", "DS", "CS")
            if _shader_info(find_named(desc, stage))
        }
        blend = find_named(desc, "BlendState")
        raster = find_named(desc, "RasterizerState")
        depth = find_named(desc, "DepthStencilState")
        rtv = find_named(desc, "RTVFormats")
        output[str(pso)] = {
            "pipeline_state": as_int(pso),
            "root_signature": as_int(named_value(desc, "pRootSignature", 0)),
            "shaders": shaders,
            "blend_state": {
                "alpha_to_coverage": bool(named_value(blend, "AlphaToCoverageEnable", False)) if blend is not None else "",
                "independent_blend": bool(named_value(blend, "IndependentBlendEnable", False)) if blend is not None else "",
                "rt0": {
                    "blend_enable": bool(named_value(blend, "BlendEnable", False)) if blend is not None else "",
                    "src_blend": named_value(blend, "SrcBlend", "") if blend is not None else "",
                    "dest_blend": named_value(blend, "DestBlend", "") if blend is not None else "",
                    "write_mask": named_value(blend, "RenderTargetWriteMask", "") if blend is not None else "",
                },
            },
            "raster_state": {
                "cull_mode": named_value(raster, "CullMode", "") if raster is not None else "",
                "depth_clip_enable": bool(named_value(raster, "DepthClipEnable", False)) if raster is not None else "",
            },
            "depth_stencil_state": {
                "depth_enable": bool(named_value(depth, "DepthEnable", False)) if depth is not None else "",
                "depth_func": named_value(depth, "DepthFunc", "") if depth is not None else "",
            },
            "primitive_topology_type": named_value(desc, "PrimitiveTopologyType", ""),
            "num_render_targets": as_int(named_value(desc, "NumRenderTargets", 0)),
            "rtv_formats": [elem_value(item) for item in list(rtv) if elem_value(item)] if rtv is not None else [],
            "dsv_format": named_value(desc, "DSVFormat", ""),
        }
    return output


def value_counts(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"value": key, "count": count} for key, count in Counter(v for v in values if v not in {"", None}).most_common()]
