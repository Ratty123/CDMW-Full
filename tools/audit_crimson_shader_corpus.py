from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Mapping, Sequence


_PARAM_RE = re.compile(r"<Parameter\b(?P<attrs>[^>]*)>(?P<body>.*?)</Parameter>|<Parameter\b(?P<self_attrs>[^>]*)/>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'([A-Za-z_][\w:-]*)\s*=\s*"([^"]*)"')
_REF_RE = re.compile(r'ResourceReferencePath_ITexture\b[^>]*(?:_path|value)\s*=\s*"([^"]*)"', re.IGNORECASE)


def scan_corpus(roots: Sequence[Path | str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        for path in Path(root).rglob("*"):
            if path.suffix.lower() not in {".material", ".xml"} and not path.name.lower().endswith(".pac_xml"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            shader_family = _shader_family(text)
            for match in _PARAM_RE.finditer(text):
                attrs = _attrs(match.group("attrs") or match.group("self_attrs") or "")
                name = str(attrs.get("Name") or attrs.get("_name") or "")
                if not name:
                    continue
                body = match.group("body") or ""
                ref = next(iter(_REF_RE.findall(body)), str(attrs.get("DefaultValue", "")))
                row = {
                    "source_file": path.as_posix(),
                    "shader_family": shader_family,
                    "parameter_name": name,
                    "texture_path": ref,
                    "suffix": _dds_suffix(ref),
                    "source_kind": _source_kind(name),
                    "authority": "",
                    "disposition": "",
                    "layer_channel": "",
                    "promoted_channels": {},
                }
                _classify_row(row)
                rows.append(row)
    return rows


def _classify_row(row: dict[str, object]) -> None:
    name = str(row["parameter_name"]).lower()
    if "colorblendingmask" in name:
        row["authority"] = "authoritative"
        row["promoted_channels"] = {"ao": "r", "roughness": "g", "metalness": "b"}
    if "detailmasktexture" in name:
        row["disposition"] = "layer_only"
    if "grimematerialtexturer" in name:
        row["layer_channel"] = "r"
        row["disposition"] = "layer_material_response"


def _shader_family(text: str) -> str:
    if "SkinnedMeshStandard_Ver2" in text:
        return "standard_v2"
    return ""


def _source_kind(name: str) -> str:
    lowered = name.lower()
    if "normal" in lowered:
        return "crimson_normal"
    if "colorblendingmask" in lowered:
        return "crimson_color_blending_mask"
    return "crimson_material_parameter"


def _dds_suffix(path: str) -> str:
    stem = Path(path.replace("\\", "/")).stem.lower()
    return stem.rsplit("_", 1)[-1] if "_" in stem else ""


def _attrs(text: str) -> dict[str, str]:
    return {key: value for key, value in _ATTR_RE.findall(text)}


def _json_ready(row: Mapping[str, object]) -> dict[str, object]:
    return dict(row)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row} or {"source_file"})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, dict) else value for key, value in row.items()})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit extracted Crimson shader/material XML corpus.")
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    args = parser.parse_args(argv)

    rows = scan_corpus(args.roots)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps([_json_ready(row) for row in rows], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(args.out_csv, rows)
    print(json.dumps({"rows": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
