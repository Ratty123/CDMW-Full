from __future__ import annotations

from collections import defaultdict
import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


KEYWORDS = ("texture", "sampler", "material", "constant", "bindless", "normal", "albedo", "roughness", "metal")


def _manifests(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in items if isinstance(item, Mapping)]


def summarize_shader_bindings(manifests: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    blobs = [blob for manifest in _manifests(manifests) for blob in manifest.get("blobs", []) if isinstance(blob, Mapping)]
    bindless: dict[tuple[str, int, str], dict[str, Any]] = {}
    dynamic: dict[tuple[str, int], dict[str, Any]] = {}
    keyword_hits: list[dict[str, Any]] = []
    for blob in blobs:
        for binding in blob.get("resource_bindings", []) or []:
            if not isinstance(binding, Mapping):
                continue
            name = str(binding.get("name", ""))
            space = binding.get("space", "")
            btype = str(binding.get("type", ""))
            hlsl = str(binding.get("hlsl_bind", ""))
            if binding.get("count") == "unbounded" or "bindless" in name.lower():
                key = (btype, int(space or 0), hlsl)
                row = bindless.setdefault(key, {"type": btype, "space": int(space or 0), "hlsl_bind": hlsl, "shader_count": 0, "names": []})
                row["shader_count"] += 1
                if name and name not in row["names"]:
                    row["names"].append(name)
            if any(word in name.lower() for word in KEYWORDS):
                keyword_hits.append({"rank": blob.get("rank", ""), "stage": blob.get("stage", ""), "name": name, "type": btype, "hlsl_bind": hlsl})
        for create in blob.get("handle_creates", []) or []:
            if not isinstance(create, Mapping):
                continue
            key = (str(create.get("class", "")), int(create.get("space", 0) or 0))
            row = dynamic.setdefault(key, {"class": key[0], "space": key[1], "handle_create_count": 0})
            row["handle_create_count"] += 1
    findings = []
    if bindless:
        findings.append("bindless_texture_array_detected")
    return {
        "status": "shader_bindings_summarized",
        "blob_count": len(blobs),
        "bindless_spaces": list(bindless.values()),
        "dynamic_handle_spaces": list(dynamic.values()),
        "keyword_hits": keyword_hits,
        "findings": findings,
    }


def _write_csv(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "space", "name", "hlsl_bind"])
        writer.writeheader()
        for row in report.get("bindless_spaces", []):
            writer.writerow({"kind": row.get("type", ""), "space": row.get("space", ""), "name": ";".join(row.get("names", [])), "hlsl_bind": row.get("hlsl_bind", "")})
        for row in report.get("keyword_hits", []):
            writer.writerow({"kind": row.get("type", ""), "space": "", "name": row.get("name", ""), "hlsl_bind": row.get("hlsl_bind", "")})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shader-blob-manifest", type=Path, action="append", required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path)
    args = parser.parse_args(argv)
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in args.shader_blob_manifest]
    report = summarize_shader_bindings(manifests)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.out_csv:
        _write_csv(args.out_csv, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
