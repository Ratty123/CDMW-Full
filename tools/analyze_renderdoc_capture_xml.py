from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from tools.renderdoc_xml_common import (
    child_named_value,
    chunk_index,
    chunks,
    elem_value,
    find_named,
    load_xml,
    local_name,
    named_value,
    parse_descriptor_maps,
    parse_resource_descriptions,
    value_counts,
)


def _sample_chunk_values(chunk) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for elem in chunk.iter():
        name = elem.attrib.get("name")
        if name and name not in values:
            values[name] = elem_value(elem)
    return values


def summarize_renderdoc_capture_xml(xml_path: Path, *, scene_note: str = "") -> dict[str, Any]:
    root = load_xml(Path(xml_path))
    resources = parse_resource_descriptions(root)
    descriptors, _ = parse_descriptor_maps(root, resources)
    draw_chunks = [chunk for chunk in chunks(root) if "Draw" in chunk.attrib.get("name", "")]
    header = find_named(root, "header") or root
    adapter = find_named(root, "AdapterDesc")
    driver = next((elem_value(elem) for elem in root.iter() if local_name(elem.tag) == "driver"), "")
    thumbnail = next((elem for elem in root.iter() if local_name(elem.tag) == "thumbnail"), None)
    return {
        "status": "xml_summarized",
        "capture_xml": str(xml_path),
        "scene_note": scene_note,
        "header": {
            "driver": driver or named_value(header, "driver", ""),
            "thumbnail_width": int(thumbnail.attrib.get("width", 0)) if thumbnail is not None else 0,
            "thumbnail_height": int(thumbnail.attrib.get("height", 0)) if thumbnail is not None else 0,
        },
        "adapter": {
            "description": child_named_value(adapter, "Description", "") if adapter is not None else "",
            "vendor_id": child_named_value(adapter, "VendorId", "") if adapter is not None else "",
            "device_id": child_named_value(adapter, "DeviceId", "") if adapter is not None else "",
            "dedicated_video_memory": child_named_value(adapter, "DedicatedVideoMemory", "") if adapter is not None else "",
        },
        "resource_count": len(resources),
        "srv_count": sum(1 for item in descriptors.values() if item.get("type") == "SRV"),
        "chunk_count": len(chunks(root)),
        "resource_format_counts": value_counts(item.get("format", "") for item in resources.values()),
        "srv_format_counts": value_counts(item.get("format", "") for item in descriptors.values() if item.get("type") == "SRV"),
        "draw_counts": value_counts(chunk.attrib.get("name", "") for chunk in draw_chunks),
        "samples": {
            "draws": [
                {"chunk_index": chunk_index(chunk), "name": chunk.attrib.get("name", ""), **_sample_chunk_values(chunk)}
                for chunk in draw_chunks[:16]
            ],
            "srvs": list(descriptors.values())[:16],
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--scene-note", default="")
    args = parser.parse_args(argv)
    report = summarize_renderdoc_capture_xml(args.xml, scene_note=args.scene_note)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
