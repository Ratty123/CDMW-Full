from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Mapping, Sequence
from zipfile import ZipFile

from tools.renderdoc_xml_common import chunks, load_xml, named_value


DDS_HEADER_SIZE = 128
FOURCC_FORMATS = {
    "DXT1": "BC1_UNORM",
    "DXT3": "BC2_UNORM",
    "DXT5": "BC3_UNORM",
    "ATI2": "BC5_UNORM",
    "BC5U": "BC5_UNORM",
    "BC4U": "BC4_UNORM",
    "BC7U": "BC7_UNORM",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dds_row(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"DDS "):
        raise ValueError(f"not a DDS file: {path}")
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mips = struct.unpack_from("<I", data, 28)[0]
    fourcc = data[84:88].decode("ascii", errors="ignore").strip("\0")
    fmt = FOURCC_FORMATS.get(fourcc, fourcc or "UNKNOWN")
    rel_parts = path.relative_to(root).parts
    archive_path = Path(*rel_parts[1:]).as_posix() if rel_parts and rel_parts[0].isdigit() and len(rel_parts) > 1 else path.relative_to(root).as_posix()
    stem = path.stem.lower()
    role = "normal" if stem.endswith("_n") or "_normal" in stem else "base_or_layer"
    payload = data[DDS_HEADER_SIZE:]
    return {
        "archive_path": archive_path,
        "format": fmt,
        "family": fmt.split("_", 1)[0],
        "width": width,
        "height": height,
        "mip_count": mips,
        "role": role,
        "direct_upload_candidate": True,
        "dds_payload_all_sha256": _sha256(payload),
        "dds_sha256": _sha256(data),
    }


def scan_dds_corpus(root: Path) -> list[dict[str, Any]]:
    base = Path(root)
    rows: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.dds")):
        try:
            rows.append(_dds_row(path, base))
        except (OSError, ValueError, struct.error):
            continue
    return rows


def _norm_format(value: object) -> str:
    text = str(value or "").upper().replace("DXGI_FORMAT_", "")
    return text.replace("_SRGB", "").replace("_TYPELESS", "")


def _srv_rows(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if isinstance(report.get("captures"), list):
        return [srv for capture in report["captures"] if isinstance(capture, Mapping) for srv in capture.get("srv_slots", []) if isinstance(srv, Mapping)]
    if isinstance(report.get("srv_slots"), list):
        return [srv for srv in report.get("srv_slots", []) if isinstance(srv, Mapping)]
    return []


def _resource_shape(srv: Mapping[str, Any]) -> tuple[str, int, int, int]:
    desc = srv.get("resource_desc", {}) if isinstance(srv.get("resource_desc"), Mapping) else {}
    return (
        _norm_format(srv.get("format", desc.get("format", ""))),
        int(desc.get("width", srv.get("width", 0)) or 0),
        int(desc.get("height", srv.get("height", 0)) or 0),
        int(desc.get("mip_levels", desc.get("mips", desc.get("mip_count", srv.get("mip_count", 0)))) or 0),
    )


def correlate_resources_to_dds(
    capture_reports: Sequence[Mapping[str, Any]],
    dds_rows: Sequence[Mapping[str, Any]],
    *,
    resource_blob_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    blob_hashes = dict(resource_blob_hashes or {})
    dds_by_payload = {str(row.get("dds_payload_all_sha256", "")): row for row in dds_rows if row.get("dds_payload_all_sha256")}
    correlations: list[dict[str, Any]] = []
    for srv in [srv for report in capture_reports for srv in _srv_rows(report)]:
        fmt, width, height, mips = _resource_shape(srv)
        exact_blob = dds_by_payload.get(blob_hashes.get(str(srv.get("resource", "")), ""))
        exact = [
            row
            for row in dds_rows
            if _norm_format(row.get("format")) == fmt
            and int(row.get("width", 0) or 0) == width
            and int(row.get("height", 0) or 0) == height
            and (not mips or int(row.get("mip_count", 0) or 0) == mips)
        ]
        dimension = [row for row in dds_rows if int(row.get("width", 0) or 0) == width and int(row.get("height", 0) or 0) == height]
        row: dict[str, Any] = {
            "resource": srv.get("resource", ""),
            "format": srv.get("format", ""),
            "width": width,
            "height": height,
            "mip_levels": mips,
            "correlated_dds_path": "",
            "match_kind": "none",
            "authority": "capture_correlation_unresolved",
            "confidence": "none",
        }
        if exact_blob:
            row.update(
                {
                    "exact_blob_dds_path": exact_blob.get("archive_path", ""),
                    "exact_blob_hash_kind": "dds_payload_all",
                    "correlated_dds_path": exact_blob.get("archive_path", ""),
                    "match_kind": "exact_blob",
                    "authority": "capture_blob_exact",
                    "confidence": "high",
                }
            )
        elif len(exact) == 1:
            row.update(
                {
                    "correlated_dds_path": exact[0].get("archive_path", ""),
                    "match_kind": "format_dimensions_mips",
                    "authority": "capture_correlated_unique",
                    "confidence": "high",
                }
            )
        elif dimension:
            row.update(
                {
                    "match_kind": "dimension_only",
                    "candidate_count": len(dimension),
                    "confidence": "ambiguous" if len(dimension) > 1 else "low",
                    "correlated_dds_path": dimension[0].get("archive_path", "") if len(dimension) == 1 else "",
                }
            )
        correlations.append(row)
    exact_blob_count = sum(1 for row in correlations if row.get("authority") == "capture_blob_exact")
    return {
        "status": "dds_correlation_complete",
        "policy": "metadata correlation",
        "dds_count": len(dds_rows),
        "capture_resource_count": len(correlations),
        "matched_resource_count": sum(1 for row in correlations if row.get("confidence") == "high"),
        "unique_high_confidence_count": sum(1 for row in correlations if row.get("authority") in {"capture_correlated_unique", "capture_blob_exact"}),
        "correlations": correlations,
        "blob_hash_summary": {"exact_blob_match_count": exact_blob_count},
    }


def scan_resource_content_blobs(xml_path: Path, resource_ids: set[str]) -> dict[str, dict[str, Any]]:
    root = load_xml(Path(xml_path))
    output: dict[str, dict[str, Any]] = {}
    for chunk in chunks(root):
        if "Initial Contents" not in chunk.attrib.get("name", ""):
            continue
        resource = str(named_value(chunk, "id", named_value(chunk, "Resource", "")))
        blob = str(named_value(chunk, "ResourceContents", ""))
        if resource in resource_ids and blob:
            output[resource] = {"resource": resource, "blob_id": blob}
    return output


def _blob_hashes(xml_path: Path | None, zip_path: Path | None, resource_ids: set[str]) -> dict[str, str]:
    if not xml_path or not zip_path:
        return {}
    refs = scan_resource_content_blobs(xml_path, resource_ids)
    hashes: dict[str, str] = {}
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for resource, ref in refs.items():
            entry = f"{int(ref['blob_id']):06d}"
            if entry in names:
                hashes[resource] = _sha256(archive.read(entry))
    return hashes


def _write_csv(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["resource", "format", "width", "height", "confidence", "correlated_dds_path", "authority"])
        writer.writeheader()
        for row in report.get("correlations", []):
            writer.writerow({field: row.get(field, "") for field in writer.fieldnames or []})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-report", type=Path, action="append", required=True)
    parser.add_argument("--dds-root", type=Path, required=True)
    parser.add_argument("--capture-xml", type=Path)
    parser.add_argument("--blob-zip", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path)
    args = parser.parse_args(argv)
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.capture_report]
    dds_rows = scan_dds_corpus(args.dds_root)
    resource_ids = {str(srv.get("resource", "")) for report in reports for srv in _srv_rows(report) if srv.get("resource", "") != ""}
    report = correlate_resources_to_dds(reports, dds_rows, resource_blob_hashes=_blob_hashes(args.capture_xml, args.blob_zip, resource_ids))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.out_csv:
        _write_csv(args.out_csv, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
