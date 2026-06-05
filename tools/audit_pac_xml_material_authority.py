from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping
from collections import Counter
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.modding.pac_xml_profiles import (
    PacXmlMaterialAuthorityReport,
    build_pac_xml_material_authority_report,
)


MATERIAL_AUTHORITY_AUDIT_SCHEMA = "cdmw_pac_xml_material_authority_audit_v1"
MATERIAL_SIDECAR_SUFFIXES = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
DEFAULT_LOCAL_SHADER_CORPUS = REPO_ROOT / ".tmp_crimson_shader_corpus"
DEFAULT_CRIMSON_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")


def default_pac_xml_material_authority_roots(
    *,
    repo_root: Path = REPO_ROOT,
    game_root: Path = DEFAULT_CRIMSON_GAME_ROOT,
) -> tuple[Path, ...]:
    """Prefer extracted shader corpus; use game root only when corpus has no sidecars."""
    local_corpus = Path(repo_root).expanduser() / ".tmp_crimson_shader_corpus"
    if _root_has_material_sidecars(local_corpus):
        return (local_corpus,)
    fallback_game = Path(game_root).expanduser()
    if _root_has_material_sidecars(fallback_game):
        return (fallback_game,)
    return (local_corpus,)


def iter_pac_xml_material_authority_reports(
    roots: Iterable[Path],
    *,
    authority_contract: str = "true_source_authority",
    limit: int | None = None,
) -> list[PacXmlMaterialAuthorityReport]:
    reports: list[PacXmlMaterialAuthorityReport] = []
    for root in roots:
        base = Path(root).expanduser()
        candidates = [base] if base.is_file() else _iter_material_sidecar_files(base)
        for path in candidates:
            if limit is not None and len(reports) >= int(limit):
                return reports
            if path.suffix.lower() not in MATERIAL_SIDECAR_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            reports.append(
                build_pac_xml_material_authority_report(
                    text,
                    _display_path(path, base),
                    authority_contract=authority_contract,
                )
            )
    return reports


def build_pac_xml_material_authority_audit_summary(
    reports: Iterable[PacXmlMaterialAuthorityReport],
) -> dict[str, object]:
    report_list = list(reports)
    report_dicts = [report.to_dict() for report in report_list]
    parameter_rows = [
        parameter
        for report in report_list
        for parameter in _iter_material_authority_parameters(report)
    ]
    wrapper_rows = [wrapper for report in report_list for wrapper in report.wrapper_order]
    submesh_rows = [binding for report in report_list for binding in report.submesh_bindings]
    texture_rows = [parameter for parameter in parameter_rows if _parameter_type_kind(parameter.parameter_type) == "texture"]
    color_rows = [
        row
        for report_dict in report_dicts
        for row in tuple(report_dict.get("color_parameters", ()) or ())
        if isinstance(row, Mapping)
    ]
    scalar_rows = [
        row
        for report_dict in report_dicts
        for row in tuple(report_dict.get("scalar_ranges", ()) or ())
        if isinstance(row, Mapping)
    ]
    alpha_rows = [
        row
        for report_dict in report_dicts
        for row in tuple(report_dict.get("alpha_controls", ()) or ())
        if isinstance(row, Mapping)
    ]
    status_counts = Counter(report.status for report in report_list)
    family_counts = Counter(report.profile_family for report in report_list)
    shader_counts = Counter(shader for report in report_list for shader in report.shader_families)
    inherited_reasons = Counter(
        parameter.reason for report in report_list for parameter in report.inherited_influence_parameters
    )
    unknown_parameters = Counter(
        parameter.parameter_name or "<unnamed>"
        for report in report_list
        for parameter in report.unknown_material_response_parameters
    )
    unknown_examples = _unknown_material_response_examples(report_list)
    neutralization_actions = [
        action for report in report_list for action in tuple(report.neutralization_actions or ())
    ]
    return {
        "schema": MATERIAL_AUTHORITY_AUDIT_SCHEMA,
        "source_files": len(report_list),
        "status_counts": status_counts.most_common(),
        "families": family_counts.most_common(40),
        "shader_families": shader_counts.most_common(80),
        "abi_evidence": {
            "wrapper_rows": len(wrapper_rows),
            "submesh_binding_rows": len(submesh_rows),
            "parameter_rows": len(parameter_rows),
            "runtime_abi_parameter_rows": sum(len(report.runtime_abi_parameters) for report in report_list),
            "source_authority_parameter_rows": sum(len(report.source_authority_parameters) for report in report_list),
            "inherited_influence_parameter_rows": sum(len(report.inherited_influence_parameters) for report in report_list),
            "unknown_material_response_parameter_rows": sum(
                len(report.unknown_material_response_parameters) for report in report_list
            ),
            "neutralization_action_rows": len(neutralization_actions),
            "neutralization_required_rows": sum(1 for action in neutralization_actions if action.required),
            "texture_parameter_rows": len(texture_rows),
            "stock_runtime_texture_rows": sum(1 for parameter in texture_rows if parameter.stock_runtime),
            "scalar_range_rows": len(scalar_rows),
            "color_parameter_rows": len(color_rows),
            "alpha_control_rows": len(alpha_rows),
            "wrapper_item_id_rows": sum(1 for wrapper in wrapper_rows if wrapper.item_id),
            "submesh_item_id_rows": sum(1 for binding in submesh_rows if binding.item_id),
            "submesh_id_base_rows": sum(1 for binding in submesh_rows if binding.id_base),
            "parameter_item_id_rows": sum(1 for parameter in parameter_rows if parameter.item_id),
            "parameter_index_rows": sum(1 for parameter in parameter_rows if parameter.index),
            "files_with_wrapper_order": sum(1 for report in report_list if report.wrapper_order),
            "files_with_submesh_bindings": sum(1 for report in report_list if report.submesh_bindings),
            "files_with_alpha_controls": sum(
                1
                for report_dict in report_dicts
                if tuple(report_dict.get("alpha_controls", ()) or ())
            ),
            "files_with_unknown_material_response": sum(
                1 for report in report_list if report.unknown_material_response_parameters
            ),
            "files_with_neutralization_actions": sum(1 for report in report_list if report.neutralization_actions),
        },
        "wrapper_names": Counter(wrapper.wrapper_name or "<unnamed>" for wrapper in wrapper_rows).most_common(80),
        "submesh_binding_names": Counter(binding.wrapper_name or "<unnamed>" for binding in submesh_rows).most_common(80),
        "parameter_types": Counter(_parameter_type_key(parameter.parameter_type) for parameter in parameter_rows).most_common(80),
        "parameter_names": Counter(parameter.parameter_name or "<unnamed>" for parameter in parameter_rows).most_common(120),
        "texture_parameter_names": Counter(parameter.parameter_name or "<unnamed>" for parameter in texture_rows).most_common(120),
        "texture_roles": Counter(parameter.role or "<unknown>" for parameter in texture_rows).most_common(80),
        "alpha_control_modes": Counter(str(row.get("mode") or "<unknown>") for row in alpha_rows).most_common(40),
        "color_parameter_names": Counter(str(row.get("parameter_name") or "<unnamed>") for row in color_rows).most_common(80),
        "scalar_parameter_names": Counter(str(row.get("parameter_name") or "<unnamed>") for row in scalar_rows).most_common(80),
        "runtime_abi_parameters": Counter(
            parameter.parameter_name or "<unnamed>"
            for report in report_list
            for parameter in report.runtime_abi_parameters
        ).most_common(120),
        "source_authority_parameters": Counter(
            parameter.parameter_name or "<unnamed>"
            for report in report_list
            for parameter in report.source_authority_parameters
        ).most_common(120),
        "inherited_influence_parameters": Counter(
            parameter.parameter_name or "<unnamed>"
            for report in report_list
            for parameter in report.inherited_influence_parameters
        ).most_common(120),
        "inherited_influence_reasons": inherited_reasons.most_common(80),
        "neutralization_actions": Counter(action.action or "<unknown>" for action in neutralization_actions).most_common(80),
        "neutralization_statuses": Counter(action.action_status or "<unknown>" for action in neutralization_actions).most_common(40),
        "unknown_material_response_parameters": unknown_parameters.most_common(80),
        "unknown_material_response_examples": unknown_examples,
        "warning_count": sum(len(report.warnings) for report in report_list),
        "reports": report_dicts,
    }


def _unknown_material_response_examples(
    reports: Iterable[PacXmlMaterialAuthorityReport],
    *,
    limit: int = 80,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for report in reports:
        wrapper_lookup = _wrapper_lookup(report)
        submesh_lookup = _submesh_lookup(report)
        for parameter in tuple(report.unknown_material_response_parameters or ()):
            identity = (
                str(report.path or ""),
                str(parameter.wrapper_name or ""),
                str(parameter.parameter_name or ""),
                str(parameter.item_id or ""),
                str(parameter.index or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            wrapper = wrapper_lookup.get(parameter.wrapper_name)
            submesh = submesh_lookup.get(parameter.wrapper_name)
            rows.append(
                {
                    "source_file": report.path,
                    "profile_family": report.profile_family,
                    "profile_slot": report.profile_slot,
                    "shader_families": tuple(report.shader_families),
                    "wrapper_name": parameter.wrapper_name,
                    "wrapper_item_id": getattr(wrapper, "item_id", "") if wrapper else "",
                    "submesh_item_id": getattr(submesh, "item_id", "") if submesh else "",
                    "submesh_id_base": getattr(submesh, "id_base", "") if submesh else "",
                    "parameter_name": parameter.parameter_name,
                    "parameter_type": parameter.parameter_type,
                    "item_id": parameter.item_id,
                    "index": parameter.index,
                    "role": parameter.role,
                    "reason": parameter.reason,
                    "value": parameter.value,
                    "texture_path": parameter.texture_path,
                }
            )
            if len(rows) >= max(1, int(limit)):
                return rows
    return rows


def _iter_material_authority_parameters(report: PacXmlMaterialAuthorityReport) -> tuple[object, ...]:
    return (
        *tuple(report.runtime_abi_parameters),
        *tuple(report.source_authority_parameters),
        *tuple(report.inherited_influence_parameters),
        *tuple(report.unknown_material_response_parameters),
    )


def _parameter_type_key(value: str) -> str:
    return str(value or "").strip() or "<unknown>"


def _parameter_type_kind(value: str) -> str:
    return str(value or "").strip().lower()


def _iter_material_sidecar_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MATERIAL_SIDECAR_SUFFIXES
    )


def _root_has_material_sidecars(root: Path) -> bool:
    try:
        return next(iter(_iter_material_sidecar_files(Path(root).expanduser())), None) is not None
    except OSError:
        return False


def _display_path(path: Path, root: Path) -> str:
    try:
        if root.is_dir():
            return path.relative_to(root).as_posix()
    except ValueError:
        pass
    return path.as_posix()


def _write_csv(path: Path, reports: Iterable[PacXmlMaterialAuthorityReport]) -> None:
    fieldnames = [
        "source_file",
        "status",
        "authority_contract",
        "profile_family",
        "profile_slot",
        "shader_families",
        "category",
        "reason",
        "wrapper_order",
        "wrapper_name",
        "wrapper_item_id",
        "submesh_order",
        "submesh_item_id",
        "submesh_id_base",
        "parameter_name",
        "parameter_type",
        "item_id",
        "index",
        "value",
        "numeric_value",
        "color_rgba",
        "color_order",
        "alpha_mode",
        "role",
        "texture_path",
        "stock_runtime",
        "neutralization_action",
        "neutralization_status",
        "neutralization_required",
        "neutralization_replacement_target",
        "preserve_runtime_abi",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            parameters = (
                list(report.runtime_abi_parameters)
                + list(report.source_authority_parameters)
                + list(report.inherited_influence_parameters)
                + list(report.unknown_material_response_parameters)
            )
            wrapper_lookup = _wrapper_lookup(report)
            submesh_lookup = _submesh_lookup(report)
            alpha_lookup = _alpha_control_lookup(report)
            neutralization_lookup = _neutralization_action_lookup(report)
            for parameter in parameters:
                details = parameter.to_dict()
                wrapper = wrapper_lookup.get(parameter.wrapper_name)
                submesh = submesh_lookup.get(parameter.wrapper_name)
                neutralization = neutralization_lookup.get(_parameter_identity(parameter), {})
                writer.writerow(
                    {
                        "source_file": report.path,
                        "status": report.status,
                        "authority_contract": report.authority_contract,
                        "profile_family": report.profile_family,
                        "profile_slot": report.profile_slot,
                        "shader_families": ";".join(report.shader_families),
                        "category": parameter.category,
                        "reason": parameter.reason,
                        "wrapper_order": wrapper.order if wrapper else "",
                        "wrapper_name": parameter.wrapper_name,
                        "wrapper_item_id": wrapper.item_id if wrapper else "",
                        "submesh_order": submesh.order if submesh else "",
                        "submesh_item_id": submesh.item_id if submesh else "",
                        "submesh_id_base": submesh.id_base if submesh else "",
                        "parameter_name": parameter.parameter_name,
                        "parameter_type": parameter.parameter_type,
                        "item_id": parameter.item_id,
                        "index": parameter.index,
                        "value": parameter.value,
                        "numeric_value": _csv_cell(details.get("numeric_value")),
                        "color_rgba": _csv_cell(details.get("color_rgba")),
                        "color_order": details.get("color_order") or "",
                        "alpha_mode": alpha_lookup.get(_parameter_identity(parameter), ""),
                        "role": parameter.role,
                        "texture_path": parameter.texture_path,
                        "stock_runtime": "1" if parameter.stock_runtime else "0",
                        "neutralization_action": neutralization.get("action") or "",
                        "neutralization_status": neutralization.get("action_status") or "",
                        "neutralization_required": "1" if neutralization.get("required") else "0" if neutralization else "",
                        "neutralization_replacement_target": neutralization.get("replacement_target") or "",
                        "preserve_runtime_abi": "1" if neutralization.get("preserve_runtime_abi") else "0" if neutralization else "",
                    }
                )


def _wrapper_lookup(report: PacXmlMaterialAuthorityReport) -> dict[str, object]:
    rows: dict[str, object] = {}
    for wrapper in report.wrapper_order:
        rows.setdefault(wrapper.wrapper_name, wrapper)
    return rows


def _submesh_lookup(report: PacXmlMaterialAuthorityReport) -> dict[str, object]:
    rows: dict[str, object] = {}
    for binding in report.submesh_bindings:
        rows.setdefault(binding.wrapper_name, binding)
    return rows


def _alpha_control_lookup(report: PacXmlMaterialAuthorityReport) -> dict[tuple[str, str, str, str], str]:
    lookup: dict[tuple[str, str, str, str], str] = {}
    report_dict = report.to_dict()
    for row in tuple(report_dict.get("alpha_controls", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        lookup[_mapping_parameter_identity(row)] = str(row.get("mode") or "")
    return lookup


def _neutralization_action_lookup(report: PacXmlMaterialAuthorityReport) -> dict[tuple[str, str, str, str], Mapping[str, object]]:
    lookup: dict[tuple[str, str, str, str], Mapping[str, object]] = {}
    for action in tuple(report.neutralization_actions or ()):
        row = action.to_dict()
        lookup[_mapping_parameter_identity(row)] = row
    return lookup


def _parameter_identity(parameter: object) -> tuple[str, str, str, str]:
    return (
        str(getattr(parameter, "wrapper_name", "") or ""),
        str(getattr(parameter, "parameter_name", "") or ""),
        str(getattr(parameter, "item_id", "") or ""),
        str(getattr(parameter, "index", "") or ""),
    )


def _mapping_parameter_identity(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("wrapper_name") or ""),
        str(row.get("parameter_name") or ""),
        str(row.get("item_id") or ""),
        str(row.get("index") or ""),
    )


def _csv_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(part) for part in value)
    return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit PAC XML/PAMI material authority risks without mutating archives.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=None,
        help=(
            "Corpus roots or individual .pac_xml/.pami files. Defaults to .tmp_crimson_shader_corpus when it has "
            "sidecars; falls back to --game-root only when the local corpus is empty/missing."
        ),
    )
    parser.add_argument(
        "--game-root",
        default=str(DEFAULT_CRIMSON_GAME_ROOT),
        help="Fallback Crimson Desert game/package root used only when default local shader corpus has no sidecars.",
    )
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", default="")
    parser.add_argument(
        "--authority-contract",
        default="true_source_authority",
        choices=("true_source_authority", "true_source_authority_detail_mask", "runtime_xml_preserve"),
    )
    parser.add_argument("--limit", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    roots = (
        tuple(Path(value) for value in args.roots)
        if args.roots
        else default_pac_xml_material_authority_roots(game_root=Path(args.game_root))
    )
    reports = iter_pac_xml_material_authority_reports(
        roots,
        authority_contract=str(args.authority_contract),
        limit=int(args.limit) if int(args.limit or 0) > 0 else None,
    )
    summary = build_pac_xml_material_authority_audit_summary(reports)
    summary["roots"] = [str(root) for root in roots]
    summary["root_selection"] = "explicit" if args.roots else "default_local_corpus_first"
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        _write_csv(Path(args.out_csv), reports)
    print(f"wrote PAC XML material authority audit: {out_json} ({len(reports):,} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
