from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.archive import extract_archive_entries
from cdmw.core.archive_accelerator import scan_archive_entries_cached_accelerated
from cdmw.models import ArchiveEntry


SHADER_TEXT_EXTENSIONS = (
    ".material",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".app_xml",
    ".prefabdata_xml",
    ".xml",
)
DEFAULT_DDS_REF_LIMIT = 512
_DDS_REF_RE = re.compile(r"(?P<path>[A-Za-z0-9_./\\:-]+\.dds)\b", re.IGNORECASE)


def _safe_archive_path(path: object) -> str:
    value = str(path or "").replace("\\", "/").strip().lstrip("/")
    parts = [part for part in PurePosixPath(value).parts if part not in {"", ".", ".."}]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _entry_output_path(output_root: Path, entry: ArchiveEntry) -> Path:
    package_root = entry.pamt_path.parent.name.strip() or "package"
    return output_root.joinpath(package_root, *PurePosixPath(_safe_archive_path(entry.path)).parts)


def _entry_sort_key(entry: ArchiveEntry) -> tuple[str, int, str]:
    return (str(entry.pamt_path), int(entry.offset), str(entry.path).lower())


def _matches_any_filter(entry: ArchiveEntry, filters: Sequence[str]) -> bool:
    if not filters:
        return True
    path = str(entry.path).replace("\\", "/").lower()
    return any(str(item or "").lower() in path for item in filters)


def select_shader_text_entries(
    entries: Iterable[ArchiveEntry],
    *,
    extensions: Sequence[str] = SHADER_TEXT_EXTENSIONS,
    path_filters: Sequence[str] = (),
    limit: int = 0,
) -> list[ArchiveEntry]:
    wanted = {
        str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
        for ext in extensions
    }
    selected = [
        entry
        for entry in entries
        if entry.extension.lower() in wanted and _matches_any_filter(entry, path_filters)
    ]
    selected.sort(key=_entry_sort_key)
    if limit > 0:
        selected = selected[:limit]
    return selected


def _read_text_safely(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def collect_dds_references(output_root: Path, sidecar_entries: Sequence[ArchiveEntry]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in sidecar_entries:
        source_path = _safe_archive_path(entry.path)
        text = _read_text_safely(_entry_output_path(output_root, entry))
        if not text:
            continue
        for match in _DDS_REF_RE.finditer(text):
            dds_path = _safe_archive_path(match.group("path"))
            if not dds_path:
                continue
            key = (source_path.lower(), dds_path.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "sidecar_path": source_path,
                    "dds_reference": dds_path,
                    "dds_basename": PurePosixPath(dds_path).name.lower(),
                }
            )
    return rows


def resolve_dds_entries(
    entries: Iterable[ArchiveEntry],
    refs: Sequence[Mapping[str, str]],
    *,
    limit: int = DEFAULT_DDS_REF_LIMIT,
) -> tuple[list[ArchiveEntry], list[dict[str, str]], dict[str, int]]:
    path_index: dict[str, ArchiveEntry] = {}
    basename_index: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        if entry.extension.lower() != ".dds":
            continue
        safe_path = _safe_archive_path(entry.path).lower()
        path_index.setdefault(safe_path, entry)
        basename_index[PurePosixPath(safe_path).name].append(entry)

    resolved: list[ArchiveEntry] = []
    rows: list[dict[str, str]] = []
    seen_entries: set[tuple[str, int, str]] = set()
    stats = {"exact": 0, "unique_basename": 0, "ambiguous_basename": 0, "missing": 0, "limited": 0}
    max_count = max(0, int(limit))
    for ref in refs:
        ref_path = _safe_archive_path(ref.get("dds_reference", ""))
        if not ref_path:
            continue
        ref_key = ref_path.lower()
        entry = path_index.get(ref_key)
        method = "exact" if entry is not None else ""
        if entry is None:
            candidates = basename_index.get(PurePosixPath(ref_key).name, [])
            if len(candidates) == 1:
                entry = candidates[0]
                method = "unique_basename"
            elif len(candidates) > 1:
                stats["ambiguous_basename"] += 1
                rows.append({**dict(ref), "resolution": "ambiguous_basename", "resolved_path": "", "archive_path": ""})
                continue
            else:
                stats["missing"] += 1
                rows.append({**dict(ref), "resolution": "missing", "resolved_path": "", "archive_path": ""})
                continue
        identity = (str(entry.pamt_path), int(entry.offset), str(entry.path))
        if identity not in seen_entries:
            if max_count and len(resolved) >= max_count:
                stats["limited"] += 1
                rows.append({**dict(ref), "resolution": "limited", "resolved_path": "", "archive_path": ""})
                continue
            seen_entries.add(identity)
            resolved.append(entry)
        stats[method] += 1
        rows.append(
            {
                **dict(ref),
                "resolution": method,
                "resolved_path": _safe_archive_path(entry.path),
                "archive_path": str(entry.pamt_path),
            }
        )
    resolved.sort(key=_entry_sort_key)
    return resolved, rows, stats


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sidecar_path", "dds_reference", "dds_basename", "resolution", "resolved_path", "archive_path"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only extraction of Crimson shader/material sidecars and a bounded DDS reference sample."
    )
    parser.add_argument("--game-root", required=True, help="Crimson Desert install/package root containing .pamt/.paz.")
    parser.add_argument("--cache-root", default="archive_cache", help="Archive scan cache root.")
    parser.add_argument("--out-root", required=True, help="Output folder for extracted research corpus.")
    parser.add_argument("--limit-sidecars", type=int, default=0, help="Max text sidecars to extract; 0 means all selected.")
    parser.add_argument("--max-dds", type=int, default=DEFAULT_DDS_REF_LIMIT, help="Max unique DDS refs to extract; 0 disables DDS extraction.")
    parser.add_argument("--path-filter", action="append", default=[], help="Case-insensitive archive path substring filter; repeatable.")
    parser.add_argument("--extension", action="append", default=[], help="Override sidecar extension list; repeatable.")
    parser.add_argument("--skip-sidecar-extract", action="store_true", help="Reuse existing extracted sidecars under --out-root.")
    parser.add_argument("--manifest-json", default="", help="Optional manifest path; defaults to <out-root>/_shader_corpus_extract_manifest.json.")
    parser.add_argument("--refs-csv", default="", help="Optional DDS reference CSV; defaults to <out-root>/_shader_corpus_dds_refs.csv.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    started = time.perf_counter()
    game_root = Path(args.game_root)
    cache_root = Path(args.cache_root)
    out_root = Path(args.out_root)
    manifest_path = Path(args.manifest_json) if args.manifest_json else out_root / "_shader_corpus_extract_manifest.json"
    refs_csv_path = Path(args.refs_csv) if args.refs_csv else out_root / "_shader_corpus_dds_refs.csv"
    extensions = tuple(args.extension or SHADER_TEXT_EXTENSIONS)

    entries, source, cache_path, timings, metadata = scan_archive_entries_cached_accelerated(game_root, cache_root)
    sidecar_entries = select_shader_text_entries(
        entries,
        extensions=extensions,
        path_filters=tuple(args.path_filter or ()),
        limit=max(0, int(args.limit_sidecars or 0)),
    )
    print(f"archive entries: {len(entries):,} ({source})")
    print(f"shader/material sidecars selected: {len(sidecar_entries):,}")
    if args.skip_sidecar_extract:
        sidecar_result = {"total": len(sidecar_entries), "extracted": 0, "decompressed": 0, "renamed": 0, "failed": 0}
    else:
        sidecar_result = extract_archive_entries(sidecar_entries, out_root, collision_mode="overwrite")

    refs = collect_dds_references(out_root, sidecar_entries)
    dds_entries: list[ArchiveEntry] = []
    resolved_rows: list[dict[str, str]] = []
    dds_stats: dict[str, int] = {"exact": 0, "unique_basename": 0, "ambiguous_basename": 0, "missing": 0, "limited": 0}
    dds_result: dict[str, int] = {"total": 0, "extracted": 0, "decompressed": 0, "renamed": 0, "failed": 0}
    if int(args.max_dds or 0) > 0 and refs:
        dds_entries, resolved_rows, dds_stats = resolve_dds_entries(entries, refs, limit=int(args.max_dds))
        print(f"DDS refs: {len(refs):,}; extracting resolved sample: {len(dds_entries):,}")
        dds_result = extract_archive_entries(dds_entries, out_root, collision_mode="overwrite")
    else:
        resolved_rows = [{**dict(row), "resolution": "not_requested", "resolved_path": "", "archive_path": ""} for row in refs]
    _write_csv(refs_csv_path, resolved_rows)

    ext_counts = Counter(entry.extension.lower() for entry in sidecar_entries)
    dds_suffix_counts = Counter(PurePosixPath(_safe_archive_path(entry.path)).stem.lower().rsplit("_", 1)[-1] for entry in dds_entries)
    manifest = {
        "schema_version": 1,
        "game_root": str(game_root),
        "cache_root": str(cache_root),
        "cache_source": source,
        "cache_path": str(cache_path or ""),
        "scan_timings": timings,
        "scan_metadata": metadata,
        "out_root": str(out_root),
        "extensions": list(extensions),
        "path_filters": list(args.path_filter or []),
        "entries_total": len(entries),
        "sidecar_entries_selected": len(sidecar_entries),
        "sidecar_extension_counts": dict(sorted(ext_counts.items())),
        "sidecar_extract_skipped": bool(args.skip_sidecar_extract),
        "sidecar_extract_result": sidecar_result,
        "dds_reference_rows": len(refs),
        "dds_resolve_stats": dds_stats,
        "dds_entries_selected": len(dds_entries),
        "dds_suffix_sample_counts": dict(dds_suffix_counts.most_common(64)),
        "dds_extract_result": dds_result,
        "refs_csv": str(refs_csv_path),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "policy": "read-only archive source; extracted corpus is local research payload and must not be committed",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
