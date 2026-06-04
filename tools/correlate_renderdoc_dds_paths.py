from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.dds_native import DdsNativeInfo, inspect_dds_native_path


SCHEMA_VERSION = 1
_PACKAGE_PREFIX_RE = re.compile(r"^[0-9a-f]{4}$", re.IGNORECASE)
_DDS_IMAGE_SUFFIXES = {
    "n": "normal",
    "normal": "normal",
    "wn": "normal",
    "sp": "material_response",
    "ma": "material_response",
    "mg": "detail_mask",
    "m": "material_response",
    "d": "height",
    "disp": "height",
    "em": "emissive",
    "emi": "emissive",
}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError, OverflowError):
        return default


def _format_family(format_value: object) -> str:
    text = str(format_value or "").strip().upper()
    text = text.replace("DXGI_FORMAT_", "").replace("DXGI_", "")
    for family in ("BC1", "BC2", "BC3", "BC4", "BC5", "BC6H", "BC7"):
        if text.startswith(family):
            return family
    for family in ("R8G8B8A8", "B8G8R8A8", "B8G8R8X8", "R8G8", "R8"):
        if text.startswith(family):
            return family
    return text.split("_", 1)[0] if text else ""


def _archive_vpath(dds_root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(dds_root).as_posix()
    except ValueError:
        return path.as_posix()
    parts = rel.split("/")
    if len(parts) > 1 and _PACKAGE_PREFIX_RE.match(parts[0]):
        return "/".join(parts[1:])
    return rel


def _suffix_role(vpath: str) -> str:
    stem = Path(str(vpath).replace("\\", "/")).stem.lower()
    suffix = stem.rsplit("_", 1)[-1] if "_" in stem else ""
    return _DDS_IMAGE_SUFFIXES.get(suffix, "base_or_layer")


def _dds_record(dds_root: Path, path: Path, info: DdsNativeInfo) -> dict[str, object]:
    vpath = _archive_vpath(dds_root, path)
    return {
        "path": str(path),
        "archive_path": vpath,
        "basename": Path(vpath).name.lower(),
        "format": info.format_name,
        "family": _format_family(info.format_name),
        "width": info.width,
        "height": info.height,
        "mip_count": info.mip_count,
        "srgb": info.srgb,
        "role": _suffix_role(vpath),
        "direct_upload_candidate": bool(info.supported_compressed or info.supported_uncompressed),
        "data_offset": info.data_offset,
        "top_mip_byte_count": info.mip_levels[0].byte_count if info.mip_levels else 0,
        "reason": info.reason,
    }


def scan_dds_corpus(dds_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    root = Path(dds_root)
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.dds")):
        try:
            info = inspect_dds_native_path(path)
        except OSError:
            continue
        if info.width <= 0 or info.height <= 0:
            continue
        rows.append(_dds_record(root, path, info))
    return rows


def _truth_captures(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    captures = [item for item in _as_sequence(report.get("captures", ())) if isinstance(item, Mapping)]
    return captures or [report]


def _capture_srv_resources(reports: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    by_resource: dict[str, dict[str, object]] = {}
    for report in reports:
        for capture in _truth_captures(report):
            for slot in _as_sequence(capture.get("srv_slots", ())):
                if not isinstance(slot, Mapping):
                    continue
                resource = str(slot.get("resource", slot.get("resource_id", "")) or "").strip()
                if not resource:
                    continue
                desc = _as_mapping(slot.get("resource_desc", {}))
                record = by_resource.setdefault(
                    resource,
                    {
                        "resource": resource,
                        "slot_count": 0,
                        "formats": Counter(),
                        "root_parameters": Counter(),
                        "heaps": Counter(),
                        "indices": [],
                    },
                )
                record["slot_count"] = _safe_int(record.get("slot_count")) + 1
                view_format = str(slot.get("format", "") or "")
                resource_format = str(desc.get("format", "") or "")
                if view_format:
                    record["formats"][view_format] += 1
                root_parameter = str(slot.get("root_parameter", "") or "")
                heap = str(slot.get("heap", "") or "")
                if root_parameter:
                    record["root_parameters"][root_parameter] += 1
                if heap:
                    record["heaps"][heap] += 1
                if slot.get("index", "") != "":
                    record["indices"].append(slot.get("index", ""))
                record.setdefault("width", slot.get("width", desc.get("width", "")))
                record.setdefault("height", slot.get("height", desc.get("height", "")))
                record.setdefault("mip_count", desc.get("mip_levels", slot.get("mip_count", "")))
                record.setdefault("view_format", view_format)
                record.setdefault("resource_format", resource_format)
                record.setdefault("dimension", slot.get("dimension", desc.get("dimension", "")))
                record.setdefault("srgb_view", slot.get("srgb_view", ""))
    output = []
    for record in by_resource.values():
        record = dict(record)
        formats = record.pop("formats", Counter())
        roots = record.pop("root_parameters", Counter())
        heaps = record.pop("heaps", Counter())
        record["view_format"] = str(record.get("view_format", "")) or (formats.most_common(1)[0][0] if formats else "")
        record["format_family"] = _format_family(record.get("view_format") or record.get("resource_format"))
        record["root_parameters"] = [key for key, _count in roots.most_common(8)]
        record["heaps"] = [key for key, _count in heaps.most_common(8)]
        record["indices_sample"] = list(record.get("indices", ()))[:8]
        record.pop("indices", None)
        output.append(record)
    return sorted(output, key=lambda item: (_safe_int(item.get("resource")), str(item.get("resource"))))


def scan_resource_content_blobs(xml_path: Path, wanted_resources: set[str] | None = None) -> dict[str, dict[str, object]]:
    wanted = {str(value) for value in wanted_resources or set() if str(value)}
    output: dict[str, dict[str, object]] = {}
    for _event, elem in ET.iterparse(str(xml_path), events=("end",)):
        if elem.tag != "chunk" or elem.attrib.get("name") != "Internal::Initial Contents":
            continue
        resource = ""
        resource_type = ""
        blob_id = ""
        byte_length = 0
        for child in elem:
            name = child.attrib.get("name", "")
            if name == "id":
                resource = str(child.text or "").strip()
            elif name == "type":
                resource_type = str(child.attrib.get("string") or child.text or "").strip()
            elif name == "ResourceContents":
                blob_id = str(child.text or "").strip()
                byte_length = _safe_int(child.attrib.get("byteLength", 0))
        if resource and resource_type == "Resource" and blob_id and (not wanted or resource in wanted):
            output[resource] = {
                "resource": resource,
                "blob_id": blob_id,
                "zip_name": f"{_safe_int(blob_id):06d}",
                "byte_length": byte_length,
                "chunk_index": _safe_int(elem.attrib.get("chunkIndex", 0)),
            }
        elem.clear()
    return output


def _index_dds(dds_rows: Sequence[Mapping[str, object]]) -> dict[tuple[str, int, int, int], list[Mapping[str, object]]]:
    index: dict[tuple[str, int, int, int], list[Mapping[str, object]]] = defaultdict(list)
    for row in dds_rows:
        family = str(row.get("family", "") or "")
        width = _safe_int(row.get("width"))
        height = _safe_int(row.get("height"))
        mip_count = _safe_int(row.get("mip_count"))
        index[(family, width, height, mip_count)].append(row)
        index[(family, width, height, 0)].append(row)
        index[("", width, height, 0)].append(row)
    return index


def _rank_candidates(resource: Mapping[str, object], candidates: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    family = str(resource.get("format_family", "") or "")
    srgb_view = resource.get("srgb_view", "")
    expected_role = "normal" if family == "BC5" else ""

    def score(row: Mapping[str, object]) -> tuple[int, str]:
        value = 0
        if str(row.get("family", "")) == family:
            value += 50
        if expected_role and row.get("role") == expected_role:
            value += 20
        if srgb_view is True and row.get("role") in {"base_or_layer", "emissive"}:
            value += 10
        if bool(row.get("direct_upload_candidate", False)):
            value += 5
        return (-value, str(row.get("archive_path", "")))

    return sorted(candidates, key=score)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dds_hash_index(dds_rows: Sequence[Mapping[str, object]]) -> dict[tuple[str, int], list[Mapping[str, object]]]:
    index: dict[tuple[str, int], list[Mapping[str, object]]] = defaultdict(list)
    for row in dds_rows:
        path_text = str(row.get("path", "") or "")
        if not path_text:
            continue
        path = Path(path_text)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        variants = {
            "dds_full": data,
        }
        data_offset = _safe_int(row.get("data_offset"), 128)
        if data_offset and data_offset < len(data):
            variants["dds_payload_all"] = data[data_offset:]
        top_mip_bytes = _safe_int(row.get("top_mip_byte_count"))
        if top_mip_bytes and data_offset + top_mip_bytes <= len(data):
            variants["dds_top_mip"] = data[data_offset : data_offset + top_mip_bytes]
        for kind, payload in variants.items():
            if not payload:
                continue
            enriched = {**dict(row), "hash_kind": kind, "sha256": _sha256(payload), "byte_length": len(payload)}
            index[(str(enriched["sha256"]), int(enriched["byte_length"]))].append(enriched)
    return index


def _apply_blob_hash_matches(
    rows: list[dict[str, object]],
    *,
    resource_blobs: Mapping[str, Mapping[str, object]],
    blob_zip_path: Path,
    dds_hashes: Mapping[tuple[str, int], Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    exact_matches = 0
    hashed_resources = 0
    missing_blobs = 0
    with ZipFile(blob_zip_path) as archive:
        names = set(archive.namelist())
        for row in rows:
            resource = str(row.get("resource", "") or "")
            blob = resource_blobs.get(resource, {})
            if not blob:
                continue
            zip_name = str(blob.get("zip_name", "") or "")
            if zip_name not in names:
                missing_blobs += 1
                continue
            payload = archive.read(zip_name)
            hashed_resources += 1
            digest = _sha256(payload)
            matches = [
                item
                for item in dds_hashes.get((digest, len(payload)), ())
                if _dds_match_compatible(row, item)
            ]
            row["resource_blob"] = {
                "blob_id": blob.get("blob_id", ""),
                "zip_name": zip_name,
                "byte_length": len(payload),
                "sha256": digest,
                "chunk_index": blob.get("chunk_index", ""),
            }
            row["exact_blob_match_count"] = len(matches)
            if matches:
                exact_matches += 1
                first = matches[0]
                row["exact_blob_dds_path"] = first.get("archive_path", "")
                row["exact_blob_hash_kind"] = first.get("hash_kind", "")
                row["exact_blob_candidates"] = [dict(item) for item in matches[:8]]
                row["authority"] = "capture_blob_exact" if len(matches) == 1 else "capture_blob_exact_ambiguous"
                row["confidence"] = "high" if len(matches) == 1 else "ambiguous"
    return {
        "resource_blob_count": len(resource_blobs),
        "hashed_resource_blob_count": hashed_resources,
        "missing_zip_blob_count": missing_blobs,
        "exact_blob_match_count": exact_matches,
    }


def _dds_match_compatible(resource: Mapping[str, object], dds: Mapping[str, object]) -> bool:
    resource_width = _safe_int(resource.get("width"))
    resource_height = _safe_int(resource.get("height"))
    dds_width = _safe_int(dds.get("width"))
    dds_height = _safe_int(dds.get("height"))
    if resource_width and dds_width and resource_width != dds_width:
        return False
    if resource_height and dds_height and resource_height != dds_height:
        return False
    resource_family = str(resource.get("format_family", "") or "")
    dds_family = str(dds.get("family", "") or "")
    if resource_family and dds_family and resource_family != dds_family:
        return False
    return True


def _correlation_count(rows: Sequence[Mapping[str, object]], confidence: str) -> int:
    return sum(1 for row in rows if row.get("confidence") == confidence)


def correlate_resources_to_dds(
    capture_reports: Sequence[Mapping[str, object]],
    dds_rows: Sequence[Mapping[str, object]],
    *,
    max_candidates_per_resource: int = 8,
    resource_blobs: Mapping[str, Mapping[str, object]] | None = None,
    blob_zip_path: Path | None = None,
) -> dict[str, object]:
    resources = _capture_srv_resources(capture_reports)
    index = _index_dds(dds_rows)
    rows: list[dict[str, object]] = []
    summary = Counter()
    for resource in resources:
        family = str(resource.get("format_family", "") or "")
        width = _safe_int(resource.get("width"))
        height = _safe_int(resource.get("height"))
        mip_count = _safe_int(resource.get("mip_count"))
        match_kind = "none"
        candidates = index.get((family, width, height, mip_count), [])
        if candidates:
            match_kind = "format_dimension_mip"
        else:
            candidates = index.get((family, width, height, 0), [])
            if candidates:
                match_kind = "format_dimension"
            else:
                candidates = index.get(("", width, height, 0), [])
                if candidates:
                    match_kind = "dimension_only"
        ranked = _rank_candidates(resource, candidates)
        candidate_count = len(ranked)
        if not candidate_count:
            confidence = "unmatched"
            authority = "unresolved"
        elif candidate_count == 1 and match_kind == "format_dimension_mip":
            confidence = "high"
            authority = "capture_correlated_unique"
        elif candidate_count == 1 and match_kind == "format_dimension":
            confidence = "medium"
            authority = "capture_correlated_unique"
        else:
            confidence = "ambiguous"
            authority = "capture_correlated_ambiguous"
        top = ranked[0] if ranked else {}
        summary[f"{match_kind}_{confidence}"] += 1
        rows.append(
            {
                **dict(resource),
                "match_kind": match_kind,
                "candidate_count": candidate_count,
                "confidence": confidence,
                "authority": authority,
                "correlated_dds_path": top.get("archive_path", ""),
                "correlated_dds_format": top.get("format", ""),
                "correlated_dds_role": top.get("role", ""),
                "candidates": [dict(row) for row in ranked[: max(0, int(max_candidates_per_resource))]],
            }
        )
    blob_summary: dict[str, object] = {}
    if resource_blobs and blob_zip_path is not None and Path(blob_zip_path).is_file():
        blob_summary = _apply_blob_hash_matches(
            rows,
            resource_blobs=resource_blobs,
            blob_zip_path=Path(blob_zip_path),
            dds_hashes=_dds_hash_index(dds_rows),
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "dds_count": len(dds_rows),
        "capture_resource_count": len(resources),
        "matched_resource_count": sum(1 for row in rows if row["candidate_count"]),
        "unique_high_confidence_count": _correlation_count(rows, "high"),
        "unique_medium_confidence_count": _correlation_count(rows, "medium"),
        "ambiguous_count": _correlation_count(rows, "ambiguous"),
        "unmatched_count": _correlation_count(rows, "unmatched"),
        "summary_counts": dict(summary),
        "blob_hash_summary": blob_summary,
        "correlations": rows,
        "policy": "DDS paths are metadata correlations against extracted sample DDS headers; not RenderDoc-authored names.",
    }


def _read_json(path: Path) -> Mapping[str, object]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, Mapping) else {}


def _write_csv(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "resource",
        "width",
        "height",
        "mip_count",
        "view_format",
        "resource_format",
        "format_family",
        "srgb_view",
        "slot_count",
        "match_kind",
        "candidate_count",
        "confidence",
        "authority",
        "correlated_dds_path",
        "correlated_dds_format",
        "correlated_dds_role",
        "exact_blob_match_count",
        "exact_blob_dds_path",
        "exact_blob_hash_kind",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in _as_sequence(report.get("correlations", ())):
            if isinstance(row, Mapping):
                writer.writerow({field: row.get(field, "") for field in fields})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Correlate RenderDoc SRV resource IDs with extracted DDS sample headers.")
    parser.add_argument("--capture-report", action="append", default=[], required=True, help="RenderDoc truth report JSON; repeatable.")
    parser.add_argument("--dds-root", required=True, help="Extracted DDS corpus root.")
    parser.add_argument("--out-json", required=True, help="Correlation report JSON.")
    parser.add_argument("--out-csv", default="", help="Optional flat CSV output.")
    parser.add_argument("--max-candidates-per-resource", type=int, default=8)
    parser.add_argument("--capture-xml", default="", help="Optional converted RenderDoc XML for ResourceContents blob IDs.")
    parser.add_argument("--blob-zip", default="", help="Optional RenderDoc convert ZIP containing binary blobs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    capture_reports = [_read_json(Path(value)) for value in args.capture_report]
    dds_rows = scan_dds_corpus(Path(args.dds_root))
    resources = {str(row.get("resource", "")) for row in _capture_srv_resources(capture_reports)}
    resource_blobs = (
        scan_resource_content_blobs(Path(args.capture_xml), resources)
        if args.capture_xml
        else {}
    )
    report = correlate_resources_to_dds(
        capture_reports,
        dds_rows,
        max_candidates_per_resource=max(0, int(args.max_candidates_per_resource or 0)),
        resource_blobs=resource_blobs,
        blob_zip_path=Path(args.blob_zip) if args.blob_zip else None,
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        _write_csv(Path(args.out_csv), report)
    print(f"correlated {report['matched_resource_count']} of {report['capture_resource_count']} capture resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
