from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.crimson_shader_registry import (
    decode_crimson_texture_binding,
    normalize_shader_family,
    texture_suffix_from_path,
)


PROFILE_SCHEMA_VERSION = 1
_TEXTURE_EXT_RE = re.compile(r"(?i)([A-Za-z0-9_./\\:-]+\.dds)")


def _safe_xml_root(text: str) -> ET.Element | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    for candidate in (stripped, f"<Root>{stripped}</Root>"):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


def _local_name(tag: object) -> str:
    text = str(tag or "")
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _attr(element: ET.Element, *names: str) -> str:
    lowered = {str(key).lower(): str(value) for key, value in element.attrib.items()}
    for name in names:
        value = lowered.get(str(name).lower())
        if value not in (None, ""):
            return value
    return ""


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _first_child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local_name(child.tag).lower() in wanted:
            return _text(child)
    return ""


def iter_material_profile_rows(roots: Iterable[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        root = Path(root)
        candidates = [root] if root.is_file() else root.rglob("*.material")
        for path in candidates:
            if path.suffix.lower() != ".material":
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            xml_root = _safe_xml_root(text)
            if xml_root is None:
                continue
            technique = ""
            permutations: list[str] = []
            for element in xml_root.iter():
                tag = _local_name(element.tag).lower()
                if tag == "technique" and not technique:
                    technique = _attr(element, "Name", "name") or _text(element)
                elif tag == "permutation":
                    name = _attr(element, "Name", "name")
                    value = _attr(element, "Value", "value", "DefaultValue", "default")
                    if name:
                        permutations.append(f"{name}={value}" if value else name)
            family = normalize_shader_family(technique or path.stem)
            for element in xml_root.iter():
                if _local_name(element.tag).lower() != "parameter":
                    continue
                name = _attr(element, "Name", "name")
                kind = _attr(element, "Type", "type", "Kind", "kind")
                default = _attr(element, "DefaultValue", "default", "Value", "value")
                srgb = _attr(element, "sRGB", "SRGB", "srgb")
                values = [default, *element.attrib.values(), _text(element)]
                dds_paths: list[str] = []
                for value in values:
                    dds_paths.extend(match.group(1) for match in _TEXTURE_EXT_RE.finditer(str(value or "")))
                if kind.lower() not in {"texture", "texture2d", "image"} and not dds_paths:
                    continue
                decode = decode_crimson_texture_binding(
                    shader_family=family,
                    parameter_name=name,
                    source_path=dds_paths[0] if dds_paths else default,
                    slot_name="material",
                    semantic_subtype=kind,
                    parameter_declared_by="material_profile",
                )
                rows.append(
                    {
                        "source_file": str(path),
                        "technique": technique or path.stem,
                        "shader_family": family,
                        "parameter_name": name,
                        "parameter_kind": kind,
                        "default_value": default,
                        "dds_path": dds_paths[0] if dds_paths else "",
                        "suffix": texture_suffix_from_path(dds_paths[0] if dds_paths else default),
                        "srgb": srgb,
                        "slot": decode.get("slot", ""),
                        "source_kind": decode.get("source_kind", ""),
                        "authority": decode.get("authority", ""),
                        "disposition": decode.get("disposition", ""),
                        "promoted_channels": dict(decode.get("promoted_channels", {}) or {}),
                        "permutations": tuple(permutations),
                    }
                )
    return rows


def iter_pso_profile_rows(roots: Iterable[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        root = Path(root)
        candidates = [root] if root.is_file() else root.rglob("*pso*.xml")
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            xml_root = _safe_xml_root(text)
            if xml_root is None:
                continue
            for element in xml_root.iter():
                if _local_name(element.tag).lower() != "psocreateinfo":
                    continue
                marker = _first_child_text(element, "PipelineMarker")
                material = _first_child_text(element, "MaterialName")
                render_pass = _first_child_text(element, "RenderPassName")
                if not marker and not material:
                    continue
                family = normalize_shader_family(material or marker)
                flags = tuple(
                    part
                    for part in str(marker or "").split("_")[1:]
                    if re.match(r"^[a-z]{2,5}\d+$", part) or part in {"gfma", "gfmd"}
                )
                rows.append(
                    {
                        "source_file": str(path),
                        "render_pass": render_pass,
                        "pipeline_marker": marker,
                        "material_name": material,
                        "shader_family": family,
                        "permutation_flags": flags,
                    }
                )
    return rows


def build_summary(material_rows: list[Mapping[str, object]], pso_rows: list[Mapping[str, object]]) -> dict[str, object]:
    family_counts = Counter(str(row.get("shader_family", "") or "generic") for row in material_rows)
    param_counts = Counter(str(row.get("parameter_name", "") or "") for row in material_rows)
    source_counts = Counter(str(row.get("source_kind", "") or "") for row in material_rows)
    disposition_counts = Counter(str(row.get("disposition", "") or "") for row in material_rows)
    pso_family_counts = Counter(str(row.get("shader_family", "") or "generic") for row in pso_rows)
    render_pass_counts = Counter(str(row.get("render_pass", "") or "") for row in pso_rows)
    flag_counts = Counter(flag for row in pso_rows for flag in tuple(row.get("permutation_flags", ()) or ()))
    family_params: dict[str, Counter[str]] = defaultdict(Counter)
    for row in material_rows:
        family_params[str(row.get("shader_family", "") or "generic")][str(row.get("parameter_name", "") or "")] += 1
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "material_profile_rows": len(material_rows),
        "pso_rows": len(pso_rows),
        "material_families": family_counts.most_common(40),
        "material_parameters": param_counts.most_common(80),
        "material_source_kinds": source_counts.most_common(40),
        "material_dispositions": disposition_counts.most_common(20),
        "pso_families": pso_family_counts.most_common(80),
        "render_passes": render_pass_counts.most_common(80),
        "pso_permutation_flags": flag_counts.most_common(120),
        "family_parameters": {
            family: counter.most_common(40)
            for family, counter in sorted(family_params.items())
        },
    }


def _write_csv(path: Path, rows: list[Mapping[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            for key, value in list(normalized.items()):
                if isinstance(value, (tuple, list)):
                    normalized[key] = ";".join(str(item) for item in value)
                elif isinstance(value, Mapping):
                    normalized[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
            writer.writerow({key: normalized.get(key, "") for key in fieldnames})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit extracted Crimson .material and PSO profile declarations.")
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-material-csv", default="")
    parser.add_argument("--out-pso-csv", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    roots = [Path(value) for value in args.roots]
    material_rows = iter_material_profile_rows(roots)
    pso_rows = iter_pso_profile_rows(roots)
    summary = build_summary(material_rows, pso_rows)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_material_csv:
        _write_csv(
            Path(args.out_material_csv),
            material_rows,
            [
                "source_file",
                "technique",
                "shader_family",
                "parameter_name",
                "parameter_kind",
                "default_value",
                "dds_path",
                "suffix",
                "srgb",
                "slot",
                "source_kind",
                "authority",
                "disposition",
                "promoted_channels",
                "permutations",
            ],
        )
    if args.out_pso_csv:
        _write_csv(
            Path(args.out_pso_csv),
            pso_rows,
            ["source_file", "render_pass", "pipeline_marker", "material_name", "shader_family", "permutation_flags"],
        )
    print(f"wrote material profile summary: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
