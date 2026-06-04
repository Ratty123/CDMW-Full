from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Mapping


RENDERDOC_XML_SUMMARY_SCHEMA_VERSION = 1


def _text_int(value: object) -> int | str:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError, OverflowError):
        return str(value or "").strip()


def _counter_rows(counter: Counter[str], limit: int = 64) -> list[dict[str, object]]:
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def _find_descendant(elem: ET.Element, tag: str, name: str) -> ET.Element | None:
    for child in elem.iter(tag):
        if child.attrib.get("name") == name:
            return child
    return None


def _find_struct(elem: ET.Element, name: str) -> ET.Element | None:
    return _find_descendant(elem, "struct", name)


def _enum_string(elem: ET.Element, name: str) -> str:
    child = _find_descendant(elem, "enum", name)
    if child is None:
        return ""
    return child.attrib.get("string", "") or (child.text or "").strip()


def _leaf_value(elem: ET.Element, name: str) -> object:
    for tag in ("uint", "int", "float", "bool", "string", "ResourceId", "enum"):
        child = _find_descendant(elem, tag, name)
        if child is not None:
            if tag == "enum":
                return child.attrib.get("string", "") or _text_int(child.text)
            return _text_int(child.text) if tag in {"uint", "int", "ResourceId"} else (child.text or "").strip()
    return ""


def _named_values(elem: ET.Element, names: Iterable[str]) -> dict[str, object]:
    return {name: _leaf_value(elem, name) for name in names if _leaf_value(elem, name) != ""}


def _record_sample(samples: list[dict[str, object]], sample: Mapping[str, object], max_samples: int) -> None:
    if len(samples) < max_samples:
        samples.append(dict(sample))


def summarize_renderdoc_capture_xml(path: Path, *, scene_note: str = "", max_samples: int = 64) -> dict[str, object]:
    path = Path(path)
    chunk_counts: Counter[str] = Counter()
    resource_formats: Counter[str] = Counter()
    resource_dimensions: Counter[str] = Counter()
    srv_formats: Counter[str] = Counter()
    srv_dimensions: Counter[str] = Counter()
    draw_counts: Counter[str] = Counter()
    pipeline_counts: Counter[str] = Counter()
    resource_samples: list[dict[str, object]] = []
    srv_samples: list[dict[str, object]] = []
    draw_samples: list[dict[str, object]] = []
    pipeline_bind_samples: list[dict[str, object]] = []
    header: dict[str, object] = {}
    adapter: dict[str, object] = {}

    context = ET.iterparse(path, events=("end",))
    for _event, elem in context:
        if elem.tag == "header":
            driver = elem.find("driver")
            thumb = elem.find("thumbnail")
            header = {
                "driver": (driver.text or "").strip() if driver is not None else "",
                "driver_id": driver.attrib.get("id", "") if driver is not None else "",
                "thumbnail": {
                    "path": (thumb.text or "").strip() if thumb is not None else "",
                    "width": _text_int(thumb.attrib.get("width", "")) if thumb is not None else "",
                    "height": _text_int(thumb.attrib.get("height", "")) if thumb is not None else "",
                },
            }
            elem.clear()
            continue

        if elem.tag != "chunk":
            continue

        name = elem.attrib.get("name", "")
        chunk_index = _text_int(elem.attrib.get("chunkIndex", ""))
        chunk_counts[name] += 1

        if name == "Internal::Driver Initialisation Parameters":
            adapter_struct = _find_struct(elem, "AdapterDesc")
            if adapter_struct is not None:
                adapter = {
                    "description": str(_leaf_value(adapter_struct, "Description")),
                    "vendor_id": _leaf_value(adapter_struct, "VendorId"),
                    "device_id": _leaf_value(adapter_struct, "DeviceId"),
                    "dedicated_vram": _leaf_value(adapter_struct, "DedicatedVideoMemory"),
                    "vendor_extensions": _enum_string(elem, "VendorExtensions"),
                    "used_dxil": _leaf_value(elem, "usedDXIL"),
                    "sdk_version": _leaf_value(elem, "SDKVersion"),
                }

        if "PipelineState" in name or "Pipeline" in name or "RootSignature" in name:
            pipeline_counts[name] += 1
            if name.endswith("SetPipelineState"):
                _record_sample(
                    pipeline_bind_samples,
                    {
                        "chunk_index": chunk_index,
                        "pipeline_state": _leaf_value(elem, "pPipelineState"),
                        "command_list": _leaf_value(elem, "pCommandList"),
                    },
                    max_samples,
                )

        if name.endswith("CreateCommittedResource") or name.endswith("CreatePlacedResource"):
            found_desc = _find_struct(elem, "pDesc")
            desc = found_desc if found_desc is not None else elem
            fmt = _enum_string(desc, "Format")
            dim = _enum_string(desc, "Dimension")
            if fmt:
                resource_formats[fmt] += 1
            if dim:
                resource_dimensions[dim] += 1
            _record_sample(
                resource_samples,
                {
                    "chunk_index": chunk_index,
                    "resource": _leaf_value(elem, "pResource"),
                    "dimension": dim,
                    "format": fmt,
                    "width": _leaf_value(desc, "Width"),
                    "height": _leaf_value(desc, "Height"),
                    "mip_levels": _leaf_value(desc, "MipLevels"),
                    "flags": _enum_string(desc, "Flags"),
                },
                max_samples,
            )

        if name.endswith("CreateShaderResourceView"):
            found_desc = _find_struct(elem, "Descriptor")
            desc = found_desc if found_desc is not None else elem
            dst = _find_struct(elem, "dst")
            fmt = _enum_string(desc, "Format")
            dim = _enum_string(desc, "ViewDimension")
            if fmt:
                srv_formats[fmt] += 1
            if dim:
                srv_dimensions[dim] += 1
            _record_sample(
                srv_samples,
                {
                    "chunk_index": chunk_index,
                    "resource": _leaf_value(elem, "Resource"),
                    "format": fmt,
                    "view_dimension": dim,
                    "component_mapping": _enum_string(desc, "Shader4ComponentMapping"),
                    "heap": _leaf_value(dst, "heap") if dst is not None else "",
                    "heap_index": _leaf_value(dst, "index") if dst is not None else "",
                    "most_detailed_mip": _leaf_value(desc, "MostDetailedMip"),
                    "mip_levels": _leaf_value(desc, "MipLevels"),
                },
                max_samples,
            )

        if name.endswith("DrawIndexedInstanced") or name.endswith("DrawInstanced") or name.endswith("Dispatch"):
            draw_counts[name] += 1
            values = _named_values(
                elem,
                (
                    "IndexCountPerInstance",
                    "VertexCountPerInstance",
                    "InstanceCount",
                    "ThreadGroupCountX",
                    "ThreadGroupCountY",
                    "ThreadGroupCountZ",
                    "StartIndexLocation",
                    "BaseVertexLocation",
                    "StartVertexLocation",
                ),
            )
            _record_sample(
                draw_samples,
                {
                    "chunk_index": chunk_index,
                    "event": name,
                    "command_list": _leaf_value(elem, "pCommandList"),
                    **values,
                },
                max_samples,
            )

        elem.clear()

    return {
        "schema_version": RENDERDOC_XML_SUMMARY_SCHEMA_VERSION,
        "source_xml": str(path),
        "source_bytes": path.stat().st_size,
        "status": "xml_summarized",
        "scene_note": scene_note,
        "header": header,
        "adapter": adapter,
        "chunk_counts": _counter_rows(chunk_counts, 128),
        "draw_counts": _counter_rows(draw_counts, 32),
        "pipeline_counts": _counter_rows(pipeline_counts, 64),
        "resource_format_counts": _counter_rows(resource_formats, 64),
        "resource_dimension_counts": _counter_rows(resource_dimensions, 32),
        "srv_format_counts": _counter_rows(srv_formats, 64),
        "srv_dimension_counts": _counter_rows(srv_dimensions, 32),
        "samples": {
            "resources": resource_samples,
            "srvs": srv_samples,
            "draws": draw_samples,
            "pipeline_binds": pipeline_bind_samples,
        },
        "limitations": [
            "Converted XML gives D3D12 API events, not RenderDoc replay pipeline-state reflection.",
            "Material shader-family/SRV slot truth still needs a capture at weapon/armor draw plus replay/UI export.",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize RenderDoc converted XML without loading it all into memory.")
    parser.add_argument("--xml", required=True, help="RenderDoc XML exported by renderdoccmd convert.")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--scene-note", default="")
    parser.add_argument("--max-samples", type=int, default=64)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = summarize_renderdoc_capture_xml(
        Path(args.xml),
        scene_note=str(args.scene_note or ""),
        max_samples=max(0, int(args.max_samples)),
    )
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote RenderDoc XML summary: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
