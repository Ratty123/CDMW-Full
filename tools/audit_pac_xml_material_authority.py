from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.atomic_file import atomic_text_writer, atomic_write_text
from cdmw.models import ArchiveEntry
from cdmw.services.archive_read_service import read_archive_entry_data


_PARAM_TAGS = {
    "MaterialParameterTexture": "Texture",
    "MaterialParameterColor": "Color",
    "MaterialParameterFloat": "Float",
    "MaterialParameterBool": "Bool",
    "MaterialParameterBitFlag32": "BitFlag32",
}

_DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")


@dataclass(frozen=True, slots=True)
class _PacXmlAuditSource:
    source_file: str
    source_kind: str
    loose_path: Path | None = None
    archive_entry: ArchiveEntry | None = None


def default_pac_xml_material_authority_roots(*, repo_root: Path, game_root: Path) -> tuple[Path, ...]:
    local = repo_root / ".tmp_crimson_shader_corpus"
    if local.is_dir() and (any(local.rglob("*.pac_xml")) or any(local.rglob("*.pamt"))):
        return (local,)
    if game_root.is_dir():
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


def audit_pac_xml_material_authority_corpus(
    roots: Sequence[Path | str],
    *,
    authority_contract: str = "true_source_authority",
    resume_summary: Mapping[str, object] | None = None,
    force: bool = False,
    chunk_size: int | None = None,
    chunk_index: int = 0,
    include_archives: bool = True,
) -> dict[str, object]:
    normalized_roots = tuple(_normalize_path(root) for root in roots)
    pamt_paths = _pamt_paths(normalized_roots) if include_archives else ()
    loose_sources = _loose_sources(normalized_roots)
    archive_sources, index_errors = _archive_sources(pamt_paths)
    archive_paths = set(pamt_paths)
    for source in archive_sources:
        if source.archive_entry is not None:
            archive_paths.add(_normalize_path(source.archive_entry.pamt_path))
            archive_paths.add(_normalize_path(source.archive_entry.paz_file))
    archive_before = _fingerprint_files(archive_paths)
    sources = tuple(sorted((*loose_sources, *archive_sources), key=_source_sort_key))
    previous = _previous_pac_xml_reports(resume_summary)
    start, end = _chunk_range(len(sources), chunk_size=chunk_size, chunk_index=chunk_index)
    reports: list[dict[str, object]] = list(index_errors)
    audited = reused = 0
    for index, source in enumerate(sources):
        fingerprint = _source_fingerprint(source, archive_before)
        audit_key = _pac_xml_audit_key(fingerprint, authority_contract)
        prior = previous.get(audit_key)
        selected = start <= index < end
        if prior is not None and (not selected or not force):
            row = dict(prior)
            row["resume_reused"] = True
            reports.append(row)
            reused += 1
            continue
        if not selected:
            continue
        reports.append(_audit_pac_xml_source(source, authority_contract, fingerprint, audit_key))
        audited += 1
    archive_after = _fingerprint_files(archive_paths)
    summary = build_pac_xml_material_authority_audit_summary(reports)
    discovered = len(sources) + len(index_errors)
    accounted = len(reports)
    errors = sum(1 for report in reports if str(report.get("classification") or "") == "safely_blocked")
    classifications = Counter(str(report.get("classification") or "review_required") for report in reports)
    valid_classifications = {"supported", "review_required", "safely_blocked"}
    unclassified = sum(1 for report in reports if str(report.get("classification") or "") not in valid_classifications)
    archives_unchanged = archive_before == archive_after
    summary.update(
        {
            "corpus_schema": "cdmw_pac_xml_material_authority_corpus_v2",
            "roots": [str(root) for root in normalized_roots],
            "progress": {
                "discovered": discovered,
                "accounted": accounted,
                "pending": max(0, discovered - accounted),
                "complete": accounted == discovered,
                "chunk_index": max(0, int(chunk_index)),
                "chunk_size": None if chunk_size is None or int(chunk_size) <= 0 else int(chunk_size),
                "audited_this_run": audited,
                "reused": reused,
            },
            "classification_counts": dict(sorted(classifications.items())),
            "read_parse_error_count": errors,
            "read_parse_crash_count": 0,
            "unclassified_count": unclassified,
            "archive_fingerprints_before": _fingerprint_rows(archive_before),
            "archive_fingerprints_after": _fingerprint_rows(archive_after),
            "source_archives_unchanged": archives_unchanged,
        }
    )
    summary["ok"] = bool(summary["progress"]["complete"] and not unclassified and archives_unchanged)
    return summary


def _audit_pac_xml_source(
    source: _PacXmlAuditSource,
    authority_contract: str,
    fingerprint: Mapping[str, object],
    audit_key: str,
) -> dict[str, object]:
    provenance = _source_provenance(source)
    try:
        if source.archive_entry is not None:
            payload, _decompressed, _note = read_archive_entry_data(source.archive_entry)
            text = payload.decode("utf-8", errors="replace")
        elif source.loose_path is not None:
            text = source.loose_path.read_text(encoding="utf-8", errors="replace")
        else:
            raise ValueError("PAC_XML audit source has no readable owner")
        report = _report_for_text(text, source.source_file, authority_contract)
    except Exception as exc:
        report = {
            "source_file": source.source_file,
            "status": "read_or_parse_failed",
            "wrappers": [],
            "submesh_bindings": [],
            "parameters": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    report["classification"] = _classify_pac_xml_report(report)
    report["source_provenance"] = provenance
    report["source_fingerprint"] = dict(fingerprint)
    report["audit_fingerprint_key"] = audit_key
    report["resume_reused"] = False
    return report


def _archive_sources(
    pamt_paths: Sequence[Path],
) -> tuple[tuple[_PacXmlAuditSource, ...], tuple[dict[str, object], ...]]:
    sources: list[_PacXmlAuditSource] = []
    errors: list[dict[str, object]] = []
    seen: set[object] = set()
    for pamt_path in pamt_paths:
        try:
            entries = parse_archive_pamt(pamt_path)
        except Exception as exc:
            errors.append(
                {
                    "source_file": str(pamt_path),
                    "status": "archive_index_failed",
                    "classification": "safely_blocked",
                    "wrappers": [],
                    "submesh_bindings": [],
                    "parameters": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for entry in entries:
            if str(entry.extension or "").casefold() != ".pac_xml" or entry.identity in seen:
                continue
            seen.add(entry.identity)
            sources.append(
                _PacXmlAuditSource(
                    source_file=str(entry.path or "").replace("\\", "/").strip("/"),
                    source_kind="archive_entry",
                    archive_entry=entry,
                )
            )
    return tuple(sources), tuple(errors)


def _loose_sources(roots: Sequence[Path]) -> tuple[_PacXmlAuditSource, ...]:
    sources: list[_PacXmlAuditSource] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*.pac_xml")
            for path in paths:
                key = _normalized_key(path)
                if key in seen or not path.is_file():
                    continue
                seen.add(key)
                sources.append(
                    _PacXmlAuditSource(
                        source_file=path.relative_to(root).as_posix(),
                        source_kind="loose_file",
                        loose_path=path,
                    )
                )
        except OSError:
            continue
    return tuple(sources)


def _pamt_paths(roots: Sequence[Path]) -> tuple[Path, ...]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.pamt"):
                if path.is_file():
                    found.setdefault(_normalized_key(path), _normalize_path(path))
        except OSError:
            continue
    return tuple(sorted(found.values(), key=_normalized_key))


def _fingerprint_files(paths: Sequence[Path] | set[Path]) -> dict[str, dict[str, object]]:
    return {
        _normalized_key(path): _fingerprint_file(path)
        for path in sorted(tuple(paths), key=_normalized_key)
    }


def _fingerprint_file(path: Path) -> dict[str, object]:
    resolved = _normalize_path(path)
    row: dict[str, object] = {"path": str(resolved), "size": 0, "mtime_ns": 0, "sha256": ""}
    try:
        stat = resolved.stat()
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        row.update(size=int(stat.st_size), mtime_ns=int(stat.st_mtime_ns), sha256=digest.hexdigest())
    except OSError as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def _fingerprint_rows(values: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    return [dict(values[key]) for key in sorted(values)]


def _source_fingerprint(
    source: _PacXmlAuditSource,
    archive_fingerprints: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    if source.archive_entry is not None:
        entry = source.archive_entry
        return {
            "kind": "archive_entry",
            "identity": entry.identity._asdict(),
            "compressed_size": int(entry.comp_size),
            "expanded_size": int(entry.orig_size),
            "flags": int(entry.flags),
            "source_pamt": dict(archive_fingerprints.get(_normalized_key(entry.pamt_path), {})),
            "source_paz": dict(archive_fingerprints.get(_normalized_key(entry.paz_file), {})),
        }
    path = source.loose_path or Path(source.source_file)
    row = _fingerprint_file(path)
    return {
        "kind": "loose_file",
        "normalized_path": _normalized_key(path),
        "size": int(row.get("size") or 0),
        "mtime_ns": int(row.get("mtime_ns") or 0),
    }


def _source_provenance(source: _PacXmlAuditSource) -> dict[str, object]:
    if source.archive_entry is None:
        return {
            "kind": "loose_file",
            "path": str(source.loose_path or source.source_file),
        }
    entry = source.archive_entry
    return {
        "kind": "archive_entry",
        "identity": entry.identity._asdict(),
        "pamt_path": str(entry.pamt_path),
        "paz_file": str(entry.paz_file),
        "compressed_size": int(entry.comp_size),
        "expanded_size": int(entry.orig_size),
    }


def _pac_xml_audit_key(fingerprint: Mapping[str, object], authority_contract: str) -> str:
    return json.dumps(
        {
            "schema": 2,
            "authority_contract": str(authority_contract),
            "source": fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _previous_pac_xml_reports(summary: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
    if not isinstance(summary, Mapping):
        return {}
    output: dict[str, dict[str, object]] = {}
    for report in tuple(summary.get("reports", ()) or ()):
        if not isinstance(report, Mapping):
            continue
        key = str(report.get("audit_fingerprint_key") or "")
        if key:
            output[key] = dict(report)
    return output


def _chunk_range(total: int, *, chunk_size: int | None, chunk_index: int) -> tuple[int, int]:
    count = max(0, int(total))
    if chunk_size is None or int(chunk_size) <= 0:
        return 0, count
    size = max(1, int(chunk_size))
    start = min(count, max(0, int(chunk_index)) * size)
    return start, min(count, start + size)


def _classify_pac_xml_report(report: Mapping[str, object]) -> str:
    status = str(report.get("status") or "").casefold()
    if status == "ok":
        return "supported"
    if status == "needs_review":
        return "review_required"
    return "safely_blocked"


def _source_sort_key(source: _PacXmlAuditSource) -> tuple[str, str]:
    provenance = _source_provenance(source)
    identity = provenance.get("identity", {})
    return str(source.source_file).casefold(), json.dumps(identity, sort_keys=True)


def _normalize_path(path: Path | str) -> Path:
    value = Path(path).expanduser()
    try:
        return value.resolve()
    except OSError:
        return value.absolute()


def _normalized_key(path: Path | str) -> str:
    return _normalize_path(path).as_posix().casefold()


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
    return _report_for_text(text, path.relative_to(root).as_posix(), authority_contract)


def _report_for_text(text: str, source_file: str, authority_contract: str) -> dict[str, object]:
    root_element = ET.fromstring(f"<CDMWRoot>{text}</CDMWRoot>")
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
                source_file=source_file,
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
    return {"source_file": source_file, "status": status, "wrappers": wrappers, "submesh_bindings": bindings, "parameters": parameters}


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
    with atomic_text_writer(path, encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit PAC XML material authority rows.")
    parser.add_argument("--roots", nargs="+")
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--authority-contract", default="true_source_authority")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--loose-only", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    game_root = Path(str(os.environ.get("CDMW_GAME_ROOT") or _DEFAULT_GAME_ROOT))
    roots = tuple(Path(value) for value in args.roots) if args.roots else default_pac_xml_material_authority_roots(
        repo_root=repo_root,
        game_root=game_root,
    )
    resume_summary: Mapping[str, object] | None = None
    if args.resume and args.out_json.is_file():
        loaded = json.loads(args.out_json.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise ValueError(f"Resume report must contain a JSON object: {args.out_json}")
        resume_summary = loaded
    summary = audit_pac_xml_material_authority_corpus(
        roots,
        authority_contract=args.authority_contract,
        resume_summary=resume_summary,
        force=args.force,
        chunk_size=args.chunk_size,
        chunk_index=args.chunk_index,
        include_archives=not args.loose_only,
    )
    atomic_write_text(args.out_json, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_csv(args.out_csv, tuple(summary.get("reports", ()) or ()))
    print(json.dumps({"ok": summary["ok"], "source_files": summary["source_files"]}, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
