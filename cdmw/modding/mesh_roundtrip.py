"""No-edit mesh rebuild harness and binary diff reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from cdmw.domain.mesh.asset import validate_mesh_asset_rebuild

from .mesh_asset import mesh_asset_from_parsed_mesh, mesh_asset_to_inspect_dict
from .mesh_importer import build_mesh
from .mesh_parser import ParsedMesh, parse_mesh


@dataclass(frozen=True, slots=True)
class AllowedDifference:
    start: int
    end: int
    code: str = "allowed"


@dataclass(frozen=True, slots=True)
class MeshRoundTripResult:
    report: dict[str, object]
    rebuilt_bytes: bytes = b""


def roundtrip_mesh_file(
    asset_path: Path | str,
    *,
    output_path: Path | str | None = None,
    report_path: Path | str | None = None,
    strict: bool = True,
    allowed_differences: Sequence[AllowedDifference] = (),
) -> MeshRoundTripResult:
    path = Path(asset_path)
    result = roundtrip_mesh_bytes(
        path.read_bytes(),
        str(path),
        strict=strict,
        allowed_differences=allowed_differences,
    )
    if output_path is not None and result.rebuilt_bytes:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(result.rebuilt_bytes)
    if report_path is not None:
        write_roundtrip_report(report_path, result.report)
    return result


def roundtrip_mesh_bytes(
    data: bytes,
    filename: str = "",
    *,
    parser: Callable[[bytes, str], ParsedMesh] = parse_mesh,
    rebuilder: Callable[[ParsedMesh, bytes], bytes] = build_mesh,
    strict: bool = True,
    allowed_differences: Sequence[AllowedDifference] = (),
) -> MeshRoundTripResult:
    report: dict[str, object] = {
        "asset": filename,
        "comparison_mode": "strict" if strict else "tolerant",
        "parse": "NOT_RUN",
        "rebuild": "NOT_RUN",
        "byte_identical": False,
        "allowed_differences": 0,
        "unexpected_differences": 0,
        "unexpected_ranges": [],
        "result": "FAIL",
    }
    try:
        parsed = parser(data, filename)
        asset = mesh_asset_from_parsed_mesh(parsed, data, source_path=filename)
        validation = validate_mesh_asset_rebuild(asset, asset)
        report.update(
            {
                "parse": "OK",
                "layout_confidence": asset.layout_confidence,
                "mesh_asset": mesh_asset_to_inspect_dict(asset),
                "validation": {
                    "ok": validation.ok,
                    "issues": [asdict(issue) for issue in validation.issues],
                },
            }
        )
    except Exception as exc:
        report["parse"] = "FAIL"
        report["error"] = str(exc)
        return MeshRoundTripResult(report)

    try:
        rebuilt = rebuilder(parsed, data)
        report["rebuild"] = "OK"
    except Exception as exc:
        report["rebuild"] = "FAIL"
        report["error"] = str(exc)
        return MeshRoundTripResult(report)

    ranges = diff_byte_ranges(data, rebuilt)
    allowed_ranges, unexpected_ranges = classify_diff_ranges(ranges, allowed_differences)
    byte_identical = not ranges
    validation_ok = bool(
        isinstance(report.get("validation"), dict)
        and report["validation"].get("ok")  # type: ignore[index]
    )
    report.update(
        {
            "byte_identical": byte_identical,
            "original_size": len(data),
            "rebuilt_size": len(rebuilt),
            "allowed_differences": len(allowed_ranges),
            "unexpected_differences": len(unexpected_ranges),
            "allowed_ranges": [_range_dict(start, end) for start, end in allowed_ranges],
            "unexpected_ranges": [_range_dict(start, end) for start, end in unexpected_ranges],
            "allowed_difference_rules": [asdict(item) for item in allowed_differences],
            "result": "PASS" if validation_ok and (byte_identical or (not strict and not unexpected_ranges)) else "FAIL",
        }
    )
    return MeshRoundTripResult(report, rebuilt)


def diff_byte_ranges(original: bytes, rebuilt: bytes) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    limit = max(len(original), len(rebuilt))
    index = 0
    while index < limit:
        left = original[index] if index < len(original) else None
        right = rebuilt[index] if index < len(rebuilt) else None
        if left == right:
            index += 1
            continue
        start = index
        while index < limit:
            left = original[index] if index < len(original) else None
            right = rebuilt[index] if index < len(rebuilt) else None
            if left == right:
                break
            index += 1
        ranges.append((start, index))
    return ranges


def classify_diff_ranges(
    ranges: Sequence[tuple[int, int]],
    allowed_differences: Sequence[AllowedDifference],
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    allowed: list[tuple[int, int]] = []
    unexpected: list[tuple[int, int]] = []
    for start, end in ranges:
        if _covered_by_allowed_ranges(start, end, allowed_differences):
            allowed.append((start, end))
        else:
            unexpected.append((start, end))
    return allowed, unexpected


def roundtrip_summary_lines(report: dict[str, object]) -> list[str]:
    lines = [
        f"Asset: {report.get('asset', '')}",
        f"Parse: {report.get('parse', 'NOT_RUN')}",
        f"Rebuild: {report.get('rebuild', 'NOT_RUN')}",
        f"Byte-identical: {'YES' if report.get('byte_identical') else 'NO'}",
        f"Allowed differences: {report.get('allowed_differences', 0)}",
        f"Unexpected differences: {report.get('unexpected_differences', 0)}",
        f"Result: {report.get('result', 'FAIL')}",
    ]
    unexpected = report.get("unexpected_ranges")
    if unexpected:
        lines.append("")
        lines.append("Unexpected ranges:")
        for item in unexpected if isinstance(unexpected, list) else []:
            if isinstance(item, dict):
                lines.append(f"- {_hex_range(int(item.get('start', 0)), int(item.get('end', 0)))}")
    if report.get("error"):
        lines.append(f"Error: {report['error']}")
    return lines


def write_roundtrip_report(path: Path | str, report: dict[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def parse_allowed_difference(value: str) -> AllowedDifference:
    raw_range, _, raw_code = str(value).partition(":")
    start_text, dash, end_text = raw_range.partition("-")
    if not dash:
        raise ValueError(f"Allowed range must be START-END or START-END:CODE: {value}")
    start = int(start_text, 0)
    end_inclusive = int(end_text, 0)
    if start < 0 or end_inclusive < start:
        raise ValueError(f"Invalid allowed range: {value}")
    return AllowedDifference(start=start, end=end_inclusive + 1, code=raw_code.strip() or "allowed")


def _covered_by_allowed_ranges(start: int, end: int, allowed_differences: Sequence[AllowedDifference]) -> bool:
    cursor = start
    for allowed in sorted(allowed_differences, key=lambda item: (item.start, item.end)):
        if allowed.end <= cursor:
            continue
        if allowed.start > cursor:
            return False
        cursor = max(cursor, allowed.end)
        if cursor >= end:
            return True
    return cursor >= end


def _range_dict(start: int, end: int) -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "start_hex": f"0x{start:08X}",
        "end_hex": f"0x{end:08X}",
        "end_inclusive_hex": f"0x{max(start, end - 1):08X}",
        "size": max(0, end - start),
    }


def _hex_range(start: int, end: int) -> str:
    return f"0x{start:08X} to 0x{max(start, end - 1):08X}"


__all__ = [
    "AllowedDifference",
    "MeshRoundTripResult",
    "classify_diff_ranges",
    "diff_byte_ranges",
    "parse_allowed_difference",
    "roundtrip_mesh_bytes",
    "roundtrip_mesh_file",
    "roundtrip_summary_lines",
    "write_roundtrip_report",
]
