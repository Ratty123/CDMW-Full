from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.crimson_shader_registry import (
    decode_crimson_texture_binding,
    infer_layer_channel,
    normalize_shader_family,
    texture_suffix_from_path,
)


_SCAN_SUFFIXES = {
    ".material",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".app_xml",
    ".prefabdata_xml",
}
_GENERIC_XML_SUFFIXES = {".xml"}
_DDS_RE = re.compile(r"(?i)([A-Za-z0-9_./\\:-]+\.dds)")
_PARAM_RE = re.compile(r"(?i)(?:Name|name|ParameterName|parameter_name)\s*=\s*['\"]([^'\"]+)['\"]")
_SHADER_RE = re.compile(r"(?i)(?:Technique|Shader|ShaderFamily|shader_family|MaterialTechnique)\s*=\s*['\"]([^'\"]+)['\"]")
_MAT_RE = re.compile(r"(?i)(?:Material|MaterialName|material_name|Name)\s*=\s*['\"]([^'\"]+)['\"]")
_MATERIAL_PARAMETER_TOKEN_RE = re.compile(
    r"(?i)(texture|color|mask|normal|rough|metal|spec|gloss|smooth|emissive|opacity|alpha|ao|"
    r"cavity|height|displace|dye|grime|detail|scratch|subsurface|skin|hair)"
)

_CSV_FIELDS = (
    "source_file",
    "shader_family",
    "material_name",
    "parameter_name",
    "parameter_kind",
    "dds_path",
    "suffix",
    "srgb",
    "default_scalar",
    "color_value",
    "layer_channel",
    "blend_flags",
    "slot",
    "source_kind",
    "authority",
    "disposition",
    "promoted_channels",
    "reason",
)


def _local_name(tag: object) -> str:
    text = str(tag or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    return text


def _attr(element: ET.Element, *names: str) -> str:
    lowered = {str(key).lower(): str(value) for key, value in element.attrib.items()}
    for name in names:
        value = lowered.get(str(name).lower())
        if value not in (None, ""):
            return value
    return ""


def _element_text(element: ET.Element) -> str:
    text = "".join(element.itertext()).strip()
    return text


def _safe_xml_root(text: str) -> ET.Element | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    attempts = (stripped, f"<Root>{stripped}</Root>")
    for candidate in attempts:
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


def _is_parameter_element(element: ET.Element) -> bool:
    tag = _local_name(element.tag).lower()
    name = _attr(element, "Name", "name", "ParameterName", "parameter_name")
    kind = _attr(element, "Type", "type", "Kind", "kind", "semantic_subtype")
    immediate_text = " ".join([*(str(value) for value in element.attrib.values()), _element_text(element)])
    if ".dds" in immediate_text.lower():
        return True
    if "texture" in kind.lower() or "image" in kind.lower() or "sampler" in kind.lower():
        return True
    if "parameter" in tag and name and _MATERIAL_PARAMETER_TOKEN_RE.search(name):
        return True
    if name and (kind or _attr(element, "DefaultValue", "default", "Value", "value") or _attr(element, "sRGB", "SRGB", "srgb")) and _MATERIAL_PARAMETER_TOKEN_RE.search(name):
        return True
    if "parameter" in tag and name and _MATERIAL_PARAMETER_TOKEN_RE.search(kind):
        return True
    return False


def _dds_paths_for_element(element: ET.Element) -> List[str]:
    values: list[str] = []
    for key, value in element.attrib.items():
        if ".dds" in str(value).lower():
            values.extend(match.group(1) for match in _DDS_RE.finditer(str(value)))
    text = _element_text(element)
    if ".dds" in text.lower():
        values.extend(match.group(1) for match in _DDS_RE.finditer(text))
    for child in element.iter():
        if child is element:
            continue
        tag = _local_name(child.tag).lower()
        if "texture" in tag or "resource" in tag or "path" in tag:
            values.extend(_dds_paths_for_element(child))
    return list(dict.fromkeys(values))


def _context_for_element(element: ET.Element, parents: Mapping[int, ET.Element]) -> Dict[str, str]:
    shader = ""
    material = ""
    current: ET.Element | None = element
    while current is not None:
        tag = _local_name(current.tag).lower()
        shader = shader or _attr(
            current,
            "Technique",
            "Shader",
            "ShaderFamily",
            "shader_family",
            "MaterialTechnique",
            "_materialName",
            "materialName",
        )
        if tag == "technique":
            shader = shader or _attr(current, "Name", "name")
        if "shader" in tag:
            shader = shader or _attr(current, "Name", "name") or _element_text(current)
        if "material" in tag or tag in {"materialwrapper", "meshmaterial"}:
            material = material or _attr(current, "_subMeshName", "SubMeshName", "Name", "name", "MaterialName", "material_name")
            shader = shader or _attr(current, "Technique", "Shader", "ShaderFamily", "shader_family", "_materialName", "materialName")
        current = parents.get(id(current))
    return {"shader_family": normalize_shader_family(shader), "material_name": material}


def _parameter_owner_for_element(element: ET.Element, parents: Mapping[int, ET.Element]) -> ET.Element:
    current: ET.Element | None = element
    while current is not None:
        tag = _local_name(current.tag).lower()
        if "parameter" in tag:
            return current
        current = parents.get(id(current))
    return element


def _parameter_name_for_element(element: ET.Element, parents: Mapping[int, ET.Element]) -> str:
    direct = _attr(element, "StringItemID", "_name", "ParameterName", "parameter_name", "Name", "name")
    if direct and direct != "_value":
        return direct
    owner = _parameter_owner_for_element(element, parents)
    owner_name = _attr(owner, "StringItemID", "_name", "ParameterName", "parameter_name", "Name", "name")
    if owner_name:
        return owner_name
    return direct


def _parameter_kind_for_element(element: ET.Element, parents: Mapping[int, ET.Element]) -> str:
    kind = _attr(element, "Type", "type", "Kind", "kind", "semantic_subtype")
    if kind:
        return kind
    owner = _parameter_owner_for_element(element, parents)
    tag = _local_name(owner.tag)
    if tag != _local_name(element.tag):
        return tag
    return ""


def _row_from_values(
    *,
    source_file: Path,
    shader_family: str,
    material_name: str,
    parameter_name: str,
    parameter_kind: str = "",
    dds_path: str = "",
    srgb: str = "",
    default_scalar: str = "",
    color_value: str = "",
    layer_channel: str = "",
    blend_flags: Iterable[str] = (),
) -> Dict[str, object]:
    decode = decode_crimson_texture_binding(
        shader_family=shader_family,
        parameter_name=parameter_name,
        source_path=dds_path,
        slot_name="material",
        semantic_subtype=parameter_kind,
        layer_channel=layer_channel,
        blend_flags=tuple(blend_flags),
        sidecar_kind="corpus_xml",
        parameter_declared_by="corpus_xml",
    )
    promoted = decode.get("promoted_channels", {})
    return {
        "source_file": str(source_file),
        "shader_family": str(decode.get("shader_family", "") or shader_family or "generic"),
        "material_name": material_name,
        "parameter_name": parameter_name,
        "parameter_kind": parameter_kind,
        "dds_path": dds_path,
        "suffix": texture_suffix_from_path(dds_path),
        "srgb": srgb,
        "default_scalar": default_scalar,
        "color_value": color_value,
        "layer_channel": layer_channel or str(decode.get("layer_channel", "") or ""),
        "blend_flags": list(tuple(blend_flags or ())),
        "slot": str(decode.get("slot", "") or ""),
        "source_kind": str(decode.get("source_kind", "") or ""),
        "authority": str(decode.get("authority", "") or ""),
        "disposition": str(decode.get("disposition", "") or ""),
        "promoted_channels": dict(promoted) if isinstance(promoted, Mapping) else {},
        "reason": str(decode.get("reason", "") or ""),
    }


def _rows_from_xml(path: Path, text: str) -> List[Dict[str, object]]:
    root = _safe_xml_root(text)
    if root is None:
        return []
    parents: Dict[int, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parents[id(child)] = parent
    default_shader = ""
    default_material = ""
    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if not default_shader and tag == "technique":
            default_shader = normalize_shader_family(_attr(element, "Name", "name"))
        if not default_shader and "shader" in tag:
            default_shader = normalize_shader_family(_attr(element, "Name", "name") or _element_text(element))
        if not default_material and "material" in tag:
            default_material = _attr(element, "Name", "name", "MaterialName", "material_name")
    rows: list[Dict[str, object]] = []
    for element in root.iter():
        if not _is_parameter_element(element):
            continue
        owner = _parameter_owner_for_element(element, parents)
        if owner is not element and _is_parameter_element(owner):
            continue
        context = _context_for_element(element, parents)
        if not context["shader_family"]:
            context["shader_family"] = default_shader
        if not context["material_name"]:
            context["material_name"] = default_material
        parameter_name = _parameter_name_for_element(element, parents)
        parameter_kind = _parameter_kind_for_element(element, parents)
        srgb = _attr(element, "sRGB", "SRGB", "srgb")
        default_scalar = _attr(element, "DefaultValue", "default", "Value", "value")
        color_value = _attr(element, "Color", "color", "ColorValue", "color_value")
        layer_channel = infer_layer_channel(parameter_name, _attr(element, "Channel", "channel", "layer_channel"))
        blend_flags = [
            str(value)
            for key, value in element.attrib.items()
            if "blend" in str(key).lower() or "flag" in str(key).lower()
        ]
        dds_paths = _dds_paths_for_element(element)
        if not dds_paths:
            rows.append(
                _row_from_values(
                    source_file=path,
                    shader_family=context["shader_family"],
                    material_name=context["material_name"],
                    parameter_name=parameter_name,
                    parameter_kind=parameter_kind,
                    srgb=srgb,
                    default_scalar=default_scalar,
                    color_value=color_value,
                    layer_channel=layer_channel,
                    blend_flags=blend_flags,
                )
            )
            continue
        for dds_path in dds_paths:
            rows.append(
                _row_from_values(
                    source_file=path,
                    shader_family=context["shader_family"],
                    material_name=context["material_name"],
                    parameter_name=parameter_name,
                    parameter_kind=parameter_kind,
                    dds_path=dds_path,
                    srgb=srgb,
                    default_scalar=default_scalar,
                    color_value=color_value,
                    layer_channel=layer_channel,
                    blend_flags=blend_flags,
                )
            )
    return rows


def _rows_from_regex(path: Path, text: str) -> List[Dict[str, object]]:
    rows: list[Dict[str, object]] = []
    shader_match = _SHADER_RE.search(text)
    material_match = _MAT_RE.search(text)
    shader_family = normalize_shader_family(shader_match.group(1) if shader_match else "")
    material_name = material_match.group(1) if material_match else ""
    dds_matches = list(_DDS_RE.finditer(text))
    for match in dds_matches:
        start = max(0, match.start() - 512)
        end = min(len(text), match.end() + 512)
        window = text[start:end]
        param_match = _PARAM_RE.search(window)
        parameter_name = param_match.group(1) if param_match else ""
        rows.append(
            _row_from_values(
                source_file=path,
                shader_family=shader_family,
                material_name=material_name,
                parameter_name=parameter_name,
                dds_path=match.group(1),
                layer_channel=infer_layer_channel(parameter_name),
            )
        )
    return rows


def scan_corpus(
    roots: Iterable[Path],
    *,
    limit: int = 0,
    include_generic_xml: bool = False,
) -> List[Dict[str, object]]:
    rows: list[Dict[str, object]] = []
    scanned = 0
    scan_suffixes = set(_SCAN_SUFFIXES)
    if include_generic_xml:
        scan_suffixes.update(_GENERIC_XML_SUFFIXES)
    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else (
            path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in scan_suffixes
        )
        for path in candidates:
            if path.suffix.lower() not in scan_suffixes:
                continue
            if limit > 0 and scanned >= limit:
                return rows
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            parsed = _rows_from_xml(path, text)
            rows.extend(parsed if parsed else _rows_from_regex(path, text))
    return rows


def _write_json(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            normalized["blend_flags"] = ";".join(str(value) for value in tuple(row.get("blend_flags", ()) or ()))
            promoted = row.get("promoted_channels", {})
            normalized["promoted_channels"] = json.dumps(promoted, sort_keys=True, separators=(",", ":"))
            writer.writerow({field: normalized.get(field, "") for field in _CSV_FIELDS})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Crimson shader/material corpus audit.")
    parser.add_argument("--roots", nargs="+", required=True, help="Explicit roots/files to scan. No implicit user folder scan.")
    parser.add_argument("--out-json", required=True, help="Output JSON path.")
    parser.add_argument("--out-csv", required=True, help="Output CSV path.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max source files to scan.")
    parser.add_argument(
        "--include-generic-xml",
        action="store_true",
        help="Also scan plain .xml files; noisy PSO/config XML is skipped by default.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    roots = [Path(value) for value in args.roots]
    rows = scan_corpus(
        roots,
        limit=max(0, int(args.limit or 0)),
        include_generic_xml=bool(args.include_generic_xml),
    )
    _write_json(Path(args.out_json), rows)
    _write_csv(Path(args.out_csv), rows)
    print(f"wrote {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
