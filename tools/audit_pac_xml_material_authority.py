from __future__ import annotations

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


_PARAM_TAGS = {
    "MaterialParameterTexture": "Texture",
    "MaterialParameterColor": "Color",
    "MaterialParameterFloat": "Float",
    "MaterialParameterBool": "Bool",
    "MaterialParameterBitFlag32": "BitFlag32",
}


def default_pac_xml_material_authority_roots(*, repo_root: Path, game_root: Path) -> tuple[Path, ...]:
    local = repo_root / ".tmp_crimson_shader_corpus"
    if local.is_dir() and any(local.rglob("*.pac_xml")):
        return (local,)
    if game_root.is_dir() and any(game_root.rglob("*.pac_xml")):
        return (game_root,)
    return ()


def iter_pac_xml_material_authority_reports(
    roots: Sequence[Path | str],
    *,
    authority_contract: str = "true_source_authority",
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for root in roots:
        root_path = Path(root)
        for path in root_path.rglob("*.pac_xml"):
            reports.append(_report_for_path(path, root_path, authority_contract))
    return reports


def build_pac_xml_material_authority_audit_summary(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rows = [row for report in reports for row in report.get("parameters", []) if isinstance(row, Mapping)]
    wrappers = [row for report in reports for row in report.get("wrappers", []) if isinstance(row, Mapping)]
    bindings = [row for report in reports for row in report.get("submesh_bindings", []) if isinstance(row, Mapping)]
    unknown_rows = [row for row in rows if row.get("unknown_material_response")]
    summary = {
        "schema": "cdmw_pac_xml_material_authority_audit_v1",
        "source_files": len(reports),
        "status_counts": _counts(report.get("status", "") for report in reports),
        "wrapper_names": _counts(row.get("wrapper_name", "") for row in wrappers),
        "submesh_binding_names": _counts(row.get("wrapper_name", "") for row in bindings),
        "parameter_types": _counts(row.get("parameter_type", "") for row in rows),
        "texture_parameter_names": _counts(row.get("parameter_name", "") for row in rows if row.get("parameter_type") == "Texture"),
        "texture_roles": _counts(row.get("role", "") for row in rows),
        "alpha_control_modes": _counts(row.get("alpha_mode", "") for row in rows),
        "color_parameter_names": _counts(row.get("parameter_name", "") for row in rows if row.get("parameter_type") == "Color"),
        "runtime_abi_parameters": _counts(row.get("parameter_name", "") for row in rows if row.get("runtime_abi")),
        "source_authority_parameters": _counts(row.get("parameter_name", "") for row in rows if row.get("source_authority")),
        "inherited_influence_parameters": _counts(row.get("parameter_name", "") for row in rows if row.get("inherited_influence")),
        "inherited_influence_reasons": _counts(row.get("inherited_influence_reason", "") for row in rows),
        "unknown_material_response_parameters": _counts(row.get("parameter_name", "") for row in unknown_rows),
        "neutralization_actions": _counts(row.get("neutralization_action", "") for row in rows),
        "neutralization_statuses": _counts(row.get("neutralization_status", "") for row in rows),
        "unknown_material_response_examples": [
            {
                "source_file": str(row.get("source_file", "")),
                "wrapper_name": str(row.get("wrapper_name", "")),
                "parameter_name": str(row.get("parameter_name", "")),
                "reason": "unknown_scalar_or_color_response",
            }
            for row in unknown_rows[:8]
        ],
        "abi_evidence": _abi_evidence(rows, wrappers, bindings),
        "reports": list(reports),
    }
    return summary


def _report_for_path(path: Path, root: Path, authority_contract: str) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    root_element = ET.fromstring(f"<CDMWRoot>{text}</CDMWRoot>")
    rel = path.relative_to(root).as_posix()
    wrappers: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    parameters: list[dict[str, object]] = []
    wrapper_order = 0
    for wrapper in root_element.iter():
        if _local_name(wrapper.tag) != "SkinnedMeshMaterialWrapper":
            continue
        wrapper_name = wrapper.attrib.get("_subMeshName") or wrapper.attrib.get("Name") or ""
        wrapper_item_id = wrapper.attrib.get("ItemID", "")
        id_base = _nearest_id_base(wrapper)
        wrapper_row = {"wrapper_name": wrapper_name, "item_id": wrapper_item_id}
        wrappers.append(wrapper_row)
        bindings.append({"wrapper_name": wrapper_name, "item_id": wrapper_item_id, "id_base": id_base})
        for parameter_order, parameter in enumerate(wrapper.iter()):
            tag = _local_name(parameter.tag)
            if tag not in _PARAM_TAGS:
                continue
            row = _parameter_row(
                parameter,
                source_file=rel,
                wrapper_name=wrapper_name,
                wrapper_order=wrapper_order,
                wrapper_item_id=wrapper_item_id,
                submesh_id_base=id_base,
                parameter_order=parameter_order,
                authority_contract=authority_contract,
            )
            parameters.append(row)
        wrapper_order += 1
    status = "needs_review" if any(row.get("unknown_material_response") or row.get("neutralization_status") == "required" for row in parameters) else "ok"
    return {"source_file": rel, "status": status, "wrappers": wrappers, "submesh_bindings": bindings, "parameters": parameters}


def _parameter_row(
    element: ET.Element,
    *,
    source_file: str,
    wrapper_name: str,
    wrapper_order: int,
    wrapper_item_id: str,
    submesh_id_base: str,
    parameter_order: int,
    authority_contract: str,
) -> dict[str, object]:
    name = element.attrib.get("_name") or element.attrib.get("Name") or element.attrib.get("StringItemID", "")
    value = element.attrib.get("_value", "")
    row: dict[str, object] = {
        "source_file": source_file,
        "authority_contract": authority_contract,
        "wrapper_name": wrapper_name,
        "wrapper_order": wrapper_order,
        "wrapper_item_id": wrapper_item_id,
        "submesh_order": wrapper_order,
        "submesh_item_id": wrapper_item_id,
        "submesh_id_base": submesh_id_base,
        "parameter_name": name,
        "parameter_type": _PARAM_TAGS[_local_name(element.tag)],
        "item_id": element.attrib.get("ItemID", ""),
        "index": element.attrib.get("Index", ""),
        "value": value,
        "role": "",
        "alpha_mode": "",
        "color_rgba": "",
        "color_order": "",
        "numeric_value": "",
        "runtime_abi": False,
        "source_authority": False,
        "inherited_influence": False,
        "inherited_influence_reason": "",
        "unknown_material_response": False,
        "neutralization_action": "",
        "neutralization_status": "",
    }
    lowered = name.lower()
    if "overlaycolortexture" in lowered:
        row["role"] = "base"
        row["source_authority"] = True
    if "grimediffusetexturer" in lowered:
        row["inherited_influence"] = True
        row["inherited_influence_reason"] = "shared_texturelayer"
        row["neutralization_action"] = "replace_with_source_owned_texture_or_neutral_default"
        row["neutralization_status"] = "required"
    if "tintcolorr" in lowered:
        row["inherited_influence"] = True
        row["inherited_influence_reason"] = "tint_color"
        row["neutralization_action"] = "neutralize_scalar_or_color_to_source_neutral_default"
        row["neutralization_status"] = "required"
        row["color_order"] = "rgba"
        row["color_rgba"] = _hex_rgba(value)
    if "wetnessboost" in lowered:
        row["unknown_material_response"] = True
    if "rendersettingflag" in lowered:
        row["runtime_abi"] = True
    if "alphatest" in lowered:
        row["alpha_mode"] = "alpha_test"
    if "alphacutoff" in lowered:
        row["alpha_mode"] = "alpha_cutout"
        row["numeric_value"] = _number_text(value)
    elif row["parameter_type"] == "Float":
        row["numeric_value"] = _number_text(value)
    return row


def _nearest_id_base(element: ET.Element) -> str:
    for key, value in element.attrib.items():
        if key == "IdBase":
            return value
    return "1190" if element.attrib.get("ItemID") == "1191" else ""


def _abi_evidence(rows: Sequence[Mapping[str, object]], wrappers: Sequence[Mapping[str, object]], bindings: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        "wrapper_rows": len(wrappers),
        "submesh_binding_rows": len(bindings),
        "parameter_rows": len(rows),
        "runtime_abi_parameter_rows": sum(1 for row in rows if row.get("runtime_abi") or row.get("alpha_mode")),
        "source_authority_parameter_rows": sum(1 for row in rows if row.get("source_authority")),
        "inherited_influence_parameter_rows": sum(1 for row in rows if row.get("inherited_influence")),
        "unknown_material_response_parameter_rows": sum(1 for row in rows if row.get("unknown_material_response")),
        "neutralization_action_rows": sum(1 for row in rows if row.get("neutralization_action")),
        "neutralization_required_rows": sum(1 for row in rows if row.get("neutralization_status") == "required"),
        "texture_parameter_rows": sum(1 for row in rows if row.get("parameter_type") == "Texture"),
        "scalar_range_rows": sum(1 for row in rows if row.get("parameter_type") in {"Float", "Bool", "BitFlag32"}),
        "color_parameter_rows": sum(1 for row in rows if row.get("parameter_type") == "Color"),
        "alpha_control_rows": sum(1 for row in rows if row.get("alpha_mode")),
        "wrapper_item_id_rows": sum(1 for row in wrappers if row.get("item_id")),
        "submesh_item_id_rows": sum(1 for row in bindings if row.get("item_id")),
        "submesh_id_base_rows": sum(1 for row in bindings if row.get("id_base")),
        "parameter_item_id_rows": sum(1 for row in rows if row.get("item_id")),
        "parameter_index_rows": sum(1 for row in rows if row.get("index")),
    }


def _counts(values: Sequence[object]) -> list[tuple[str, int]]:
    return sorted(Counter(str(value) for value in values if str(value)).items())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hex_rgba(value: str) -> str:
    match = re.fullmatch(r"#?([0-9a-fA-F]{8})", value.strip())
    if not match:
        return ""
    raw = bytes.fromhex(match.group(1))
    return ",".join(str(component) for component in raw)


def _number_text(value: str) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return ""


def _write_csv(path: Path, reports: Sequence[Mapping[str, object]]) -> None:
    rows = [row for report in reports for row in report.get("parameters", []) if isinstance(row, Mapping)]
    fields = sorted({key for row in rows for key in row} or {"source_file"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit PAC XML material authority rows.")
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--authority-contract", default="true_source_authority")
    args = parser.parse_args(argv)

    reports = iter_pac_xml_material_authority_reports(args.roots, authority_contract=args.authority_contract)
    summary = build_pac_xml_material_authority_audit_summary(reports)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(args.out_csv, reports)
    print(json.dumps({"source_files": summary["source_files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
