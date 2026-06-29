from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


_PARAM_RE = re.compile(r"<Parameter\b(?P<attrs>[^>]*)>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([A-Za-z_][\w:-]*)\s*=\s*"([^"]*)"')
_PSO_RE = re.compile(r"<PSOCreateInfo\b.*?</PSOCreateInfo>", re.IGNORECASE | re.DOTALL)


def iter_material_profile_rows(roots: Sequence[Path | str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        for path in Path(root).rglob("*.material"):
            text = path.read_text(encoding="utf-8", errors="replace")
            technique = _first_attr(text, "Technique", "Name")
            for match in _PARAM_RE.finditer(text):
                attrs = _attrs(match.group("attrs"))
                name = str(attrs.get("Name") or attrs.get("_name") or "")
                if not name:
                    continue
                rows.append(
                    {
                        "source_file": path.as_posix(),
                        "technique": technique,
                        "parameter_name": name,
                        "default_value": attrs.get("DefaultValue", ""),
                        "srgb": attrs.get("sRGB", ""),
                        "source_kind": _source_kind(name),
                    }
                )
    return rows


def iter_pso_profile_rows(roots: Sequence[Path | str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        for path in Path(root).rglob("*.xml"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for block in _PSO_RE.findall(text):
                marker = _tag_text(block, "PipelineMarker")
                flags = tuple(part for part in marker.split("_") if re.fullmatch(r"[a-z]+[0-9]+|gfmd", part))
                rows.append(
                    {
                        "source_file": path.as_posix(),
                        "render_pass": _tag_text(block, "RenderPassName"),
                        "pipeline_marker": marker,
                        "material_name": _tag_text(block, "MaterialName"),
                        "permutation_flags": flags,
                    }
                )
    return rows


def build_summary(material_rows: Sequence[Mapping[str, object]], pso_rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "schema": "cdmw_crimson_material_profiles_v1",
        "material_profile_rows": len(material_rows),
        "pso_profile_rows": len(pso_rows),
        "source_kinds": sorted(Counter(str(row.get("source_kind", "")) for row in material_rows).items()),
    }


def _source_kind(name: str) -> str:
    lowered = name.lower()
    if "colorblendingmask" in lowered:
        return "crimson_color_blending_mask"
    if "detailnormalmask" in lowered:
        return "crimson_layer_normal"
    if "normal" in lowered:
        return "crimson_normal"
    return "crimson_material_parameter"


def _attrs(text: str) -> dict[str, str]:
    return {key: value for key, value in _ATTR_RE.findall(text)}


def _first_attr(text: str, tag: str, attr: str) -> str:
    match = re.search(rf"<{tag}\b([^>]*)>", text, re.IGNORECASE)
    return _attrs(match.group(1)).get(attr, "") if match else ""


def _tag_text(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row} or {"source_file"})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "|".join(value) if isinstance(value, tuple) else value for key, value in row.items()})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Crimson material profile XML files.")
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-material-csv", required=True, type=Path)
    parser.add_argument("--out-pso-csv", required=True, type=Path)
    args = parser.parse_args(argv)

    material_rows = iter_material_profile_rows(args.roots)
    pso_rows = iter_pso_profile_rows(args.roots)
    summary = build_summary(material_rows, pso_rows)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(args.out_material_csv, material_rows)
    _write_csv(args.out_pso_csv, pso_rows)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
