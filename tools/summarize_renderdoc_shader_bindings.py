from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
KEYWORD_RE = re.compile(
    r"(bindless|material|skinned|skin|cloth|hair|base|normal|rough|metal|dye|grime|overlay|scratch|detail|mask)",
    re.IGNORECASE,
)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _load_manifest(path: Path) -> Mapping[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"manifest must be an object: {path}")
    return data


def _binding_name(binding: Mapping[str, object]) -> str:
    return str(binding.get("name", "") or "")


def _binding_key(binding: Mapping[str, object]) -> tuple[str, int, str]:
    return (
        str(binding.get("type", "")),
        _int(binding.get("space", 0)),
        str(binding.get("hlsl_bind", "")),
    )


def _handle_key(handle: Mapping[str, object]) -> tuple[str, int]:
    return (str(handle.get("class", "")), _int(handle.get("space", 0)))


def summarize_shader_bindings(manifests: Sequence[Mapping[str, object]]) -> dict[str, object]:
    blob_rows: list[dict[str, object]] = []
    bindless: dict[tuple[str, int, str], dict[str, object]] = {}
    dynamic_handles: Counter[tuple[str, int]] = Counter()
    keyword_hits: Counter[str] = Counter()

    for manifest in manifests:
        source = str(manifest.get("renderdoc_zip", ""))
        for blob in _as_sequence(manifest.get("blobs", ())):
            if not isinstance(blob, Mapping):
                continue
            bindings = [item for item in _as_sequence(blob.get("resource_bindings", ())) if isinstance(item, Mapping)]
            handles = [item for item in _as_sequence(blob.get("handle_creates", ())) if isinstance(item, Mapping)]
            unbounded_bindings = [binding for binding in bindings if str(binding.get("count", "")) == "unbounded"]
            matched_names = sorted({name for binding in bindings if (name := _binding_name(binding)) and KEYWORD_RE.search(name)})
            for name in matched_names:
                keyword_hits[name] += 1
            for handle in handles:
                dynamic_handles[_handle_key(handle)] += 1
            for binding in unbounded_bindings:
                key = _binding_key(binding)
                entry = bindless.setdefault(
                    key,
                    {
                        "type": key[0],
                        "space": key[1],
                        "hlsl_bind": key[2],
                        "names": [],
                        "shader_count": 0,
                        "stages": [],
                        "samples": [],
                    },
                )
                name = _binding_name(binding)
                if name and name not in entry["names"]:
                    entry["names"].append(name)
                stage = str(blob.get("stage", ""))
                if stage and stage not in entry["stages"]:
                    entry["stages"].append(stage)
                entry["shader_count"] = int(entry["shader_count"]) + 1
                samples = entry["samples"]
                if isinstance(samples, list) and len(samples) < 12:
                    samples.append(
                        {
                            "rank": blob.get("rank", ""),
                            "chunk_index": blob.get("chunk_index", ""),
                            "stage": stage,
                            "blob_id": blob.get("blob_id", ""),
                        }
                    )
            blob_rows.append(
                {
                    "source": source,
                    "rank": blob.get("rank", ""),
                    "chunk_index": blob.get("chunk_index", ""),
                    "stage": blob.get("stage", ""),
                    "blob_id": blob.get("blob_id", ""),
                    "sha256": blob.get("sha256", ""),
                    "binding_count": len(bindings),
                    "texture_count": sum(1 for binding in bindings if binding.get("type") == "texture"),
                    "sampler_count": sum(1 for binding in bindings if binding.get("type") == "sampler"),
                    "cbuffer_count": sum(1 for binding in bindings if binding.get("type") == "cbuffer"),
                    "unbounded_count": len(unbounded_bindings),
                    "dynamic_handle_count": len(handles),
                    "dynamic_unbounded_handle_count": sum(1 for handle in handles if bool(handle.get("is_unbounded", False))),
                    "keyword_hits": matched_names,
                }
            )

    bindless_rows = sorted(
        bindless.values(),
        key=lambda item: (-int(item.get("shader_count", 0)), int(item.get("space", 0)), str(item.get("hlsl_bind", ""))),
    )
    dynamic_rows = [
        {"class": cls, "space": space, "handle_create_count": count}
        for (cls, space), count in sorted(dynamic_handles.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_count": len(manifests),
        "blob_count": len(blob_rows),
        "bindless_spaces": bindless_rows,
        "dynamic_handle_spaces": dynamic_rows,
        "keyword_hits": [
            {"name": name, "shader_count": count}
            for name, count in keyword_hits.most_common()
        ],
        "blobs": blob_rows,
        "findings": [
            "bindless_texture_array_detected" if any(row.get("type") == "texture" for row in bindless_rows) else "",
            "dynamic_resource_indexing_detected" if dynamic_rows else "",
        ],
    }


def write_blob_csv(report: Mapping[str, object], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "rank",
            "chunk_index",
            "stage",
            "blob_id",
            "binding_count",
            "texture_count",
            "sampler_count",
            "cbuffer_count",
            "unbounded_count",
            "dynamic_handle_count",
            "dynamic_unbounded_handle_count",
            "keyword_hits",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in _as_sequence(report.get("blobs", ())):
            if not isinstance(row, Mapping):
                continue
            payload = {key: row.get(key, "") for key in fieldnames}
            payload["keyword_hits"] = ";".join(str(item) for item in _as_sequence(row.get("keyword_hits", ())))
            writer.writerow(payload)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize RenderDoc shader resource bindings from shader blob manifests.")
    parser.add_argument("--shader-blob-manifest", action="append", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = summarize_shader_bindings([_load_manifest(Path(path)) for path in args.shader_blob_manifest])
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        write_blob_csv(report, Path(args.out_csv))
    print(f"wrote shader binding summary: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
