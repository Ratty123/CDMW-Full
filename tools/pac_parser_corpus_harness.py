from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.models import ArchiveEntry

_REPORT_FORMAT = "cdmw_pac_parser_corpus_v1"
_MAX_ISSUE_SAMPLES = 200


@dataclass(frozen=True)
class PacCorpusIssue:
    code: str
    message: str
    submesh_index: int | None = None
    expected: object | None = None
    actual: object | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
        }
        if self.submesh_index is not None:
            payload["submesh_index"] = self.submesh_index
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload


def _normalized_archive_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip()


def _entry_key(entry: ArchiveEntry) -> str:
    return f"{Path(entry.pamt_path).as_posix()}::{_normalized_archive_path(entry.path)}"


def _entry_family(path: str, depth: int = 4) -> str:
    parts = [part for part in PurePosixPath(_normalized_archive_path(path).lower()).parts if part and part != "."]
    if len(parts) <= depth:
        return "/".join(parts)
    return "/".join(parts[:depth])


def _matches_filters(entry: ArchiveEntry, filters: Sequence[str]) -> bool:
    if not filters:
        return True
    path = _normalized_archive_path(entry.path).casefold()
    return all(str(value or "").replace("\\", "/").strip().casefold() in path for value in filters)


def discover_pac_entries(
    *,
    game_root: Path | None = None,
    pamt_paths: Sequence[Path] = (),
    path_contains: Sequence[str] = (),
) -> list[ArchiveEntry]:
    if game_root is None and not pamt_paths:
        raise ValueError("Provide --game-root or at least one --pamt path.")

    discovered_pamts: list[Path] = []
    if pamt_paths:
        discovered_pamts.extend(Path(path).expanduser() for path in pamt_paths)
    if game_root is not None:
        discovered_pamts.extend(discover_pamt_files(Path(game_root).expanduser()))

    unique_pamts = sorted({path.resolve() for path in discovered_pamts})
    entries: list[ArchiveEntry] = []
    for pamt_path in unique_pamts:
        for entry in parse_archive_pamt(pamt_path):
            if str(getattr(entry, "extension", "") or "").casefold() != ".pac":
                continue
            if not _matches_filters(entry, path_contains):
                continue
            entries.append(entry)
    entries.sort(key=lambda entry: (_entry_key(entry).casefold(), int(getattr(entry, "offset", 0) or 0)))
    return entries


def _chunk_bounds(total: int, chunk_size: int, chunk_index: int, chunk_count: int = 1) -> tuple[int, int]:
    if chunk_size <= 0:
        raise ValueError("chunk size must be greater than zero")
    if chunk_index < 0:
        raise ValueError("chunk index must be greater than or equal to zero")
    if chunk_count <= 0:
        raise ValueError("chunk count must be greater than zero")
    start = chunk_index * chunk_size
    end = min(total, start + chunk_size * chunk_count)
    if start > total:
        start = total
    return start, end


def _row_width(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (str, bytes)):
        return 1 if value else 0
    try:
        return len(tuple(value))  # type: ignore[arg-type]
    except TypeError:
        return 1


def _validate_submesh(submesh: SubMesh, index: int, *, mesh_has_bones: bool, data_size: int) -> list[PacCorpusIssue]:
    issues: list[PacCorpusIssue] = []
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    vertex_count = len(vertices)
    if vertex_count <= 0:
        issues.append(PacCorpusIssue("submesh_empty_vertices", "Submesh has no vertices.", index))
    if not faces:
        issues.append(PacCorpusIssue("submesh_empty_faces", "Submesh has no faces.", index))

    source_map = tuple(getattr(submesh, "source_vertex_map", ()) or ())
    if len(source_map) != vertex_count:
        issues.append(
            PacCorpusIssue(
                "source_vertex_map_length_mismatch",
                "Submesh source vertex map length does not match vertex count.",
                index,
                expected=vertex_count,
                actual=len(source_map),
            )
        )
    elif any(not isinstance(value, int) or value < 0 for value in source_map):
        issues.append(PacCorpusIssue("source_vertex_map_invalid", "Submesh source vertex map contains invalid values.", index))

    source_offsets = tuple(getattr(submesh, "source_vertex_offsets", ()) or ())
    stride = int(getattr(submesh, "source_vertex_stride", 0) or 0)
    if len(source_offsets) != vertex_count:
        issues.append(
            PacCorpusIssue(
                "source_vertex_offsets_length_mismatch",
                "Submesh source vertex offsets length does not match vertex count.",
                index,
                expected=vertex_count,
                actual=len(source_offsets),
            )
        )
    if stride <= 0:
        issues.append(PacCorpusIssue("source_vertex_stride_missing", "Submesh source vertex stride is missing.", index))
    elif data_size > 0:
        bad_offsets: list[object] = []
        for value in source_offsets:
            if not isinstance(value, int) or value < 0 or value + stride > data_size:
                bad_offsets.append(value)
        if bad_offsets:
            issues.append(
                PacCorpusIssue(
                    "source_vertex_offsets_out_of_range",
                    "Submesh source vertex offsets point outside the source asset.",
                    index,
                    actual=bad_offsets[:5],
                )
            )

    index_count = int(getattr(submesh, "source_index_count", 0) or 0)
    if faces and index_count <= 0:
        issues.append(PacCorpusIssue("source_index_count_missing", "Submesh source index count is missing.", index))

    for face_index, face in enumerate(faces):
        if len(tuple(face or ())) != 3:
            issues.append(
                PacCorpusIssue(
                    "face_not_triangle",
                    f"Face {face_index} is not triangular.",
                    index,
                    expected=3,
                    actual=len(tuple(face or ())),
                )
            )
            continue
        if any(not isinstance(vertex_index, int) or vertex_index < 0 or vertex_index >= vertex_count for vertex_index in face):
            issues.append(
                PacCorpusIssue(
                    "face_index_out_of_range",
                    f"Face {face_index} references a missing vertex.",
                    index,
                    expected=f"0..{max(vertex_count - 1, 0)}",
                    actual=list(face),
                )
            )
            break

    bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    if mesh_has_bones:
        if len(bone_indices) != vertex_count or len(bone_weights) != vertex_count:
            issues.append(
                PacCorpusIssue(
                    "bone_row_count_mismatch",
                    "Skinned mesh submesh bone row counts do not match vertex count.",
                    index,
                    expected=vertex_count,
                    actual={"bone_indices": len(bone_indices), "bone_weights": len(bone_weights)},
                )
            )
        else:
            for vertex_index, (raw_indices, raw_weights) in enumerate(zip(bone_indices, bone_weights)):
                index_width = _row_width(raw_indices)
                weight_width = _row_width(raw_weights)
                if index_width != weight_width:
                    issues.append(
                        PacCorpusIssue(
                            "bone_influence_width_mismatch",
                            f"Bone index/weight width mismatch at vertex {vertex_index}.",
                            index,
                            expected=index_width,
                            actual=weight_width,
                        )
                    )
                    break
                if index_width > 4:
                    issues.append(
                        PacCorpusIssue(
                            "bone_influence_width_too_large",
                            f"Bone influence row is wider than four at vertex {vertex_index}.",
                            index,
                            expected="<=4",
                            actual=index_width,
                        )
                    )
                    break
    return issues


def validate_parsed_pac_mesh(mesh: ParsedMesh, *, data_size: int = 0) -> list[PacCorpusIssue]:
    issues: list[PacCorpusIssue] = []
    if str(getattr(mesh, "format", "") or "").casefold() != "pac":
        issues.append(
            PacCorpusIssue(
                "fallback_format",
                "PAC parser returned a non-PAC format, which means the PAC path fell back to another parser.",
                expected="pac",
                actual=str(getattr(mesh, "format", "") or ""),
            )
        )
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    total_vertices = int(getattr(mesh, "total_vertices", 0) or 0)
    total_faces = int(getattr(mesh, "total_faces", 0) or 0)
    if not submeshes or total_vertices <= 0 or total_faces <= 0:
        issues.append(
            PacCorpusIssue(
                "empty_geometry",
                "PAC parser returned no usable geometry.",
                expected="submeshes, vertices, and faces",
                actual={"submeshes": len(submeshes), "total_vertices": total_vertices, "total_faces": total_faces},
            )
        )
        return issues

    summed_vertices = sum(len(tuple(getattr(submesh, "vertices", ()) or ())) for submesh in submeshes)
    summed_faces = sum(len(tuple(getattr(submesh, "faces", ()) or ())) for submesh in submeshes)
    if summed_vertices != total_vertices:
        issues.append(
            PacCorpusIssue(
                "total_vertices_mismatch",
                "Mesh total vertex count does not match submesh vertices.",
                expected=summed_vertices,
                actual=total_vertices,
            )
        )
    if summed_faces != total_faces:
        issues.append(
            PacCorpusIssue(
                "total_faces_mismatch",
                "Mesh total face count does not match submesh faces.",
                expected=summed_faces,
                actual=total_faces,
            )
        )

    mesh_has_bones = bool(getattr(mesh, "has_bones", False))
    for index, submesh in enumerate(submeshes):
        issues.extend(_validate_submesh(submesh, index, mesh_has_bones=mesh_has_bones, data_size=data_size))
    return issues


def _entry_report(entry: ArchiveEntry) -> dict[str, object]:
    started_at = time.perf_counter()
    payload: dict[str, object] = {
        "entry_key": _entry_key(entry),
        "path": _normalized_archive_path(entry.path),
        "pamt_path": Path(entry.pamt_path).as_posix(),
        "paz_file": Path(entry.paz_file).as_posix(),
        "size": int(getattr(entry, "size", 0) or 0),
        "compressed_size": int(getattr(entry, "compressed_size", 0) or 0),
        "compression_type": int(getattr(entry, "compression_type", 0) or 0),
        "status": "unknown",
        "issues": [],
    }
    try:
        data, decompressed, note = read_archive_entry_data(entry)
    except Exception as exc:
        payload.update(
            {
                "status": "read_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
            }
        )
        return payload
    try:
        mesh = parse_mesh(data, entry.path)
    except Exception as exc:
        payload.update(
            {
                "status": "parse_error",
                "decompressed": bool(decompressed),
                "decode_note": str(note or ""),
                "data_size": len(data),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
            }
        )
        return payload

    issues = validate_parsed_pac_mesh(mesh, data_size=len(data))
    status = "ok" if not issues else "unsupported_or_incomplete"
    payload.update(
        {
            "status": status,
            "decompressed": bool(decompressed),
            "decode_note": str(note or ""),
            "data_size": len(data),
            "format": str(getattr(mesh, "format", "") or ""),
            "submesh_count": len(tuple(getattr(mesh, "submeshes", ()) or ())),
            "total_vertices": int(getattr(mesh, "total_vertices", 0) or 0),
            "total_faces": int(getattr(mesh, "total_faces", 0) or 0),
            "has_bones": bool(getattr(mesh, "has_bones", False)),
            "issues": [issue.to_dict() for issue in issues],
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        }
    )
    return payload


def _summarize_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    statuses = Counter(str(row.get("status") or "unknown") for row in rows)
    issue_codes: Counter[str] = Counter()
    families: Counter[str] = Counter()
    total_vertices = 0
    total_faces = 0
    max_submeshes = 0
    issue_samples: list[dict[str, object]] = []
    for row in rows:
        path = str(row.get("path") or "")
        if path:
            families[_entry_family(path)] += 1
        total_vertices += int(row.get("total_vertices", 0) or 0)
        total_faces += int(row.get("total_faces", 0) or 0)
        max_submeshes = max(max_submeshes, int(row.get("submesh_count", 0) or 0))
        row_issues = row.get("issues")
        if isinstance(row_issues, list):
            for issue in row_issues:
                if isinstance(issue, Mapping):
                    issue_codes[str(issue.get("code") or "unknown")] += 1
        if str(row.get("status") or "") != "ok" and len(issue_samples) < _MAX_ISSUE_SAMPLES:
            issue_samples.append(dict(row))
    return {
        "scanned": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "issue_codes": dict(sorted(issue_codes.items())),
        "total_vertices": total_vertices,
        "total_faces": total_faces,
        "max_submeshes": max_submeshes,
        "families": dict(families.most_common(50)),
        "issue_samples": issue_samples,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _chunk_report_name(chunk_index: int, start: int, end: int) -> str:
    return f"chunk_{chunk_index:05d}_{start:07d}-{max(end - 1, start - 1):07d}.json"


def _load_chunk_reports(output_dir: Path) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for path in sorted(output_dir.glob("chunk_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("format") == _REPORT_FORMAT:
            reports.append(payload)
    return reports


def _write_cumulative_summary(output_dir: Path, *, total_entries: int, chunk_size: int) -> dict[str, object]:
    chunk_reports = _load_chunk_reports(output_dir)
    rows: list[Mapping[str, object]] = []
    completed_chunks: list[int] = []
    for report in chunk_reports:
        chunk = report.get("chunk")
        if isinstance(chunk, Mapping):
            try:
                raw_chunk_index = chunk.get("chunk_index", -1)
                completed_chunks.append(int(raw_chunk_index if raw_chunk_index is not None else -1))
            except (TypeError, ValueError):
                pass
        raw_rows = report.get("rows")
        if isinstance(raw_rows, list):
            rows.extend(row for row in raw_rows if isinstance(row, Mapping))
    summary = _summarize_rows(rows)
    total_chunks = int(math.ceil(total_entries / chunk_size)) if chunk_size > 0 else 0
    payload: dict[str, object] = {
        "format": _REPORT_FORMAT,
        "report_type": "cumulative_summary",
        "total_entries": total_entries,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "completed_chunks": sorted(set(index for index in completed_chunks if index >= 0)),
        "completed_chunk_count": len(set(index for index in completed_chunks if index >= 0)),
        "remaining_chunk_count": max(0, total_chunks - len(set(index for index in completed_chunks if index >= 0))),
        "summary": summary,
        "gate": {
            "all_entries_scanned": int(summary.get("scanned", 0) or 0) >= total_entries,
            "all_scanned_entries_ok": dict(summary.get("statuses", {})).get("ok", 0) == int(summary.get("scanned", 0) or 0),
            "parser_compatibility_ready_for_scanned_entries": not dict(summary.get("issue_codes", {})),
        },
    }
    _atomic_write_json(output_dir / "summary.json", payload)
    return payload


def scan_chunk(
    entries: Sequence[ArchiveEntry],
    *,
    output_dir: Path,
    chunk_size: int,
    chunk_index: int,
    chunk_count: int = 1,
    force: bool = False,
) -> dict[str, object]:
    start, end = _chunk_bounds(len(entries), chunk_size, chunk_index, chunk_count)
    selected = list(entries[start:end])
    rows: list[dict[str, object]] = []
    started_at = time.perf_counter()
    current_chunk = chunk_index
    for index, entry in enumerate(selected, start=start):
        if chunk_size > 0:
            current_chunk = index // chunk_size
        rows.append(_entry_report(entry))
        next_index = index + 1
        next_chunk = next_index // chunk_size if chunk_size > 0 else current_chunk
        chunk_boundary = next_index == end or next_chunk != current_chunk
        if not chunk_boundary:
            continue
        chunk_start = current_chunk * chunk_size
        chunk_end = min(len(entries), chunk_start + chunk_size)
        chunk_rows = rows[max(0, chunk_start - start) : max(0, chunk_end - start)]
        chunk_path = output_dir / _chunk_report_name(current_chunk, chunk_start, chunk_end)
        if chunk_path.is_file() and not force:
            continue
        chunk_payload = {
            "format": _REPORT_FORMAT,
            "report_type": "chunk",
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chunk": {
                "chunk_index": current_chunk,
                "chunk_size": chunk_size,
                "start": chunk_start,
                "end": chunk_end,
                "scanned": len(chunk_rows),
            },
            "summary": _summarize_rows(chunk_rows),
            "rows": chunk_rows,
        }
        _atomic_write_json(chunk_path, chunk_payload)
    payload = {
        "format": _REPORT_FORMAT,
        "report_type": "run",
        "chunk": {
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "chunk_size": chunk_size,
            "start": start,
            "end": end,
            "scanned": len(rows),
        },
        "summary": _summarize_rows(rows),
        "elapsed_s": round(time.perf_counter() - started_at, 3),
    }
    _write_cumulative_summary(output_dir, total_entries=len(entries), chunk_size=chunk_size)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan Crimson Desert .pac archive entries in resumable parser-compatibility chunks."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-root", type=Path, help="Crimson Desert package root containing .pamt files.")
    source.add_argument("--pamt", type=Path, action="append", default=[], help="Specific .pamt file to scan. Repeatable.")
    parser.add_argument("--out", type=Path, required=True, help="Directory for chunk JSON and cumulative summary.json.")
    parser.add_argument("--path-contains", action="append", default=[], help="Only scan archive paths containing this text. Repeatable.")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--chunk-count", type=int, default=1, help="Number of consecutive chunks to process in this invocation.")
    parser.add_argument("--force", action="store_true", help="Rewrite existing chunk files.")
    parser.add_argument("--list-only", action="store_true", help="Only discover matching .pac entries and write summary.json.")
    parser.add_argument("--fail-on-issue", action="store_true", help="Exit non-zero when scanned entries contain parser issues.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    entries = discover_pac_entries(
        game_root=args.game_root,
        pamt_paths=tuple(args.pamt or ()),
        path_contains=tuple(args.path_contains or ()),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    if args.list_only:
        payload = {
            "format": _REPORT_FORMAT,
            "report_type": "entry_index",
            "total_entries": len(entries),
            "chunk_size": int(args.chunk_size),
            "total_chunks": int(math.ceil(len(entries) / int(args.chunk_size))) if int(args.chunk_size) > 0 else 0,
            "path_contains": list(args.path_contains or ()),
            "entries": [
                {
                    "entry_key": _entry_key(entry),
                    "path": _normalized_archive_path(entry.path),
                    "pamt_path": Path(entry.pamt_path).as_posix(),
                    "size": int(getattr(entry, "size", 0) or 0),
                    "compressed_size": int(getattr(entry, "compressed_size", 0) or 0),
                    "compression_type": int(getattr(entry, "compression_type", 0) or 0),
                }
                for entry in entries
            ],
        }
        _atomic_write_json(args.out / "entry_index.json", payload)
        summary_payload = _write_cumulative_summary(args.out, total_entries=len(entries), chunk_size=int(args.chunk_size))
        print(json.dumps({"total_entries": len(entries), "summary": summary_payload["summary"]}, sort_keys=True))
        return 0

    run_payload = scan_chunk(
        entries,
        output_dir=args.out,
        chunk_size=int(args.chunk_size),
        chunk_index=int(args.chunk_index),
        chunk_count=int(args.chunk_count),
        force=bool(args.force),
    )
    summary_path = args.out / "summary.json"
    cumulative = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    status_payload = {
        "total_entries": len(entries),
        "run": run_payload,
        "cumulative": {
            "completed_chunk_count": cumulative.get("completed_chunk_count", 0),
            "remaining_chunk_count": cumulative.get("remaining_chunk_count", 0),
            "summary": cumulative.get("summary", {}),
            "gate": cumulative.get("gate", {}),
        },
        "summary_path": str(summary_path),
    }
    print(json.dumps(status_payload, sort_keys=True))
    run_summary = run_payload.get("summary", {})
    statuses = run_summary.get("statuses", {}) if isinstance(run_summary, Mapping) else {}
    issue_codes = run_summary.get("issue_codes", {}) if isinstance(run_summary, Mapping) else {}
    if args.fail_on_issue and (dict(statuses).get("ok", 0) != run_summary.get("scanned", 0) or issue_codes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
