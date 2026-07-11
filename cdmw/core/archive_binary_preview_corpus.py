from __future__ import annotations

import json
import os
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_binary_preview_analysis import build_binary_sidecar_analysis_document
from cdmw.core.common import RunCancelled, raise_if_cancelled


_BINARY_SIDECAR_CORPUS_EXTENSIONS = (
    ".meshinfo",
    ".motionblending",
    ".paa_metabin",
    ".papr",
    ".paseq",
    ".paseqc",
    ".paschedule",
    ".paschedulepath",
    ".pastage",
    ".prefab",
    ".pappt",
    ".pamhc",
    ".paccd",
    ".seqmt",
)
_BINARY_SIDECAR_KNOWN_TYPE_CODES = {0, 1, 2, 3, 4, 5, 7, 10}


def _discover_binary_sidecar_corpus_paths(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    candidates_by_extension: Dict[str, List[Path]] = defaultdict(list)
    seen_paths: set[str] = set()
    max_files = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None

    def add_candidate(path: Path) -> None:
        extension = path.suffix.lower()
        if extension not in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            return
        normalized = str(path.expanduser().resolve()).lower()
        if normalized in seen_paths:
            return
        seen_paths.add(normalized)
        if max_files is None or len(candidates_by_extension[extension]) < max_files:
            candidates_by_extension[extension].append(path)

    for raw_source in source_paths:
        raise_if_cancelled(stop_event)
        source = Path(raw_source).expanduser()
        if source.is_file():
            add_candidate(source)
            continue
        if not source.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(source):
            raise_if_cancelled(stop_event)
            for filename in filenames:
                extension = PurePosixPath(filename).suffix.lower()
                if extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
                    add_candidate(Path(dirpath) / filename)

    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        candidates_by_extension[extension].sort(key=lambda item: str(item).casefold())
    if max_files is None:
        return [
            path
            for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS
            for path in candidates_by_extension.get(extension, ())
        ]

    discovered: List[Path] = []
    discovered_counts: Dict[str, int] = defaultdict(int)
    while len(discovered) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = candidates_by_extension.get(extension, [])
            index = discovered_counts[extension]
            if index >= len(extension_paths):
                continue
            discovered.append(extension_paths[index])
            discovered_counts[extension] += 1
            added = True
            if len(discovered) >= max_files:
                break
        if not added:
            break
    return discovered


def _binary_sidecar_corpus_path_label(path: Path, source_paths: Sequence[Path]) -> str:
    for raw_source in source_paths:
        source = Path(raw_source).expanduser()
        try:
            if source.is_dir():
                return path.relative_to(source).as_posix()
            if source.is_file() and path.resolve() == source.resolve():
                return path.name
        except (OSError, ValueError):
            continue
    return str(path)


def _select_balanced_binary_sidecar_detail_paths(paths: Sequence[Path], max_files: Optional[int]) -> List[Path]:
    if max_files is None or max_files <= 0 or len(paths) <= max_files:
        return list(paths)
    by_extension: Dict[str, List[Path]] = defaultdict(list)
    for path in paths:
        by_extension[path.suffix.lower()].append(path)
    selected: List[Path] = []
    selected_counts: Dict[str, int] = defaultdict(int)
    while len(selected) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = by_extension.get(extension, [])
            index = selected_counts[extension]
            if index >= len(extension_paths):
                continue
            selected.append(extension_paths[index])
            selected_counts[extension] += 1
            added = True
            if len(selected) >= max_files:
                break
        if not added:
            break
    return selected


def _binary_sidecar_descriptor_is_unknown(row: Mapping[str, object]) -> bool:
    try:
        type_code = int(row.get("type_code") or 0)
    except (TypeError, ValueError):
        return True
    confidence = str(row.get("confidence") or "")
    return type_code not in _BINARY_SIDECAR_KNOWN_TYPE_CODES or confidence.startswith("experimental")


@dataclass
class _ExtensionStats:
    layout_counts: Counter[str] = field(default_factory=Counter)
    layout_examples: Dict[str, Dict[str, object]] = field(default_factory=dict)
    field_file_counts: Counter[str] = field(default_factory=Counter)
    field_decl_counts: Counter[str] = field(default_factory=Counter)
    field_type_counts: Dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    field_descriptor_counts: Dict[Tuple[str, str], Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    field_metadata: Dict[Tuple[str, str], Dict[str, str]] = field(default_factory=dict)
    unknown_descriptor_counts: Counter[str] = field(default_factory=Counter)
    unknown_descriptor_examples: Dict[str, Dict[str, object]] = field(default_factory=dict)
    value_region_counts: Counter[int] = field(default_factory=Counter)
    value_region_examples: Dict[int, str] = field(default_factory=dict)
    numeric_region_counts: Counter[int] = field(default_factory=Counter)
    numeric_region_examples: Dict[int, str] = field(default_factory=dict)
    animation_type_counts: Counter[str] = field(default_factory=Counter)
    animation_hint_counts: Counter[str] = field(default_factory=Counter)
    animation_stream_size_counts: Counter[int] = field(default_factory=Counter)
    animation_examples: Dict[str, str] = field(default_factory=dict)
    seqmt_grid_counts: Counter[str] = field(default_factory=Counter)
    seqmt_flag_counts: Counter[int] = field(default_factory=Counter)
    seqmt_payload_status_counts: Counter[str] = field(default_factory=Counter)
    seqmt_examples: Dict[str, str] = field(default_factory=dict)
    paccd_layout_counts: Counter[str] = field(default_factory=Counter)
    paccd_slot_counts: Counter[int] = field(default_factory=Counter)
    paccd_stride_counts: Counter[int] = field(default_factory=Counter)
    paccd_examples: Dict[str, str] = field(default_factory=dict)
    paseq_playback_status_counts: Counter[str] = field(default_factory=Counter)
    paseq_lane_counts: Counter[int] = field(default_factory=Counter)
    paseq_animation_lane_counts: Counter[int] = field(default_factory=Counter)
    paseq_effect_lane_counts: Counter[int] = field(default_factory=Counter)
    paseq_context_lane_counts: Counter[int] = field(default_factory=Counter)
    paseq_examples: Dict[str, str] = field(default_factory=dict)
    scanned_count: int = 0
    failed_rows: List[Dict[str, object]] = field(default_factory=list)


def _record_seqmt_and_paccd(stats: _ExtensionStats, document: Mapping[str, object], label: str) -> None:
    seqmt = document.get("seqmt", {})
    if isinstance(seqmt, Mapping) and seqmt.get("recognized"):
        columns = int(seqmt.get("columns") or 0)
        rows_count = int(seqmt.get("rows") or 0)
        frame_count = int(seqmt.get("frame_count") or 0)
        grid_key = f"{columns}x{rows_count}:{frame_count}"
        stats.seqmt_grid_counts[grid_key] += 1
        stats.seqmt_examples.setdefault(grid_key, label)
        flag_value = int(seqmt.get("flags_or_packing_byte") or 0)
        stats.seqmt_flag_counts[flag_value] += 1
        stats.seqmt_examples.setdefault(f"flag_0x{flag_value:02X}", label)
        payload_status = "complete" if bool(seqmt.get("payload_complete")) else "truncated"
        if int(seqmt.get("trailing_payload_bytes") or 0) > 0:
            payload_status = "complete_with_trailing_payload"
        stats.seqmt_payload_status_counts[payload_status] += 1
        stats.seqmt_examples.setdefault(payload_status, label)

    paccd = document.get("paccd", {})
    if isinstance(paccd, Mapping) and paccd.get("recognized"):
        family = str(paccd.get("format_family") or "unknown")
        slot_count = int(paccd.get("slot_count") or 0)
        row_stride = int(paccd.get("row_stride") or 0)
        stats.paccd_layout_counts[family] += 1
        stats.paccd_slot_counts[slot_count] += 1
        stats.paccd_stride_counts[row_stride] += 1
        stats.paccd_examples.setdefault(family, label)
        stats.paccd_examples.setdefault(f"slot_{slot_count}", label)
        stats.paccd_examples.setdefault(f"stride_{row_stride}", label)


def _record_paseq_and_animation(stats: _ExtensionStats, document: Mapping[str, object], label: str) -> None:
    paseq = document.get("paseq", {})
    if isinstance(paseq, Mapping) and paseq:
        timeline = paseq.get("timeline", {})
        playback = paseq.get("playback_readiness", {})
        if isinstance(timeline, Mapping):
            lane_count = int(timeline.get("lane_count") or 0)
            kind_counts = timeline.get("lane_kind_counts")
            kind_counts = kind_counts if isinstance(kind_counts, Mapping) else {}
            animation_lanes = int(kind_counts.get("animation") or 0)
            effect_lanes = int(kind_counts.get("effect") or 0)
            context_lanes = int(kind_counts.get("context") or 0)
            stats.paseq_lane_counts[lane_count] += 1
            stats.paseq_animation_lane_counts[animation_lanes] += 1
            stats.paseq_effect_lane_counts[effect_lanes] += 1
            stats.paseq_context_lane_counts[context_lanes] += 1
            stats.paseq_examples.setdefault(f"lanes_{lane_count}", label)
            stats.paseq_examples.setdefault(f"animation_{animation_lanes}", label)
            stats.paseq_examples.setdefault(f"effect_{effect_lanes}", label)
            stats.paseq_examples.setdefault(f"context_{context_lanes}", label)
        if isinstance(playback, Mapping):
            status = str(playback.get("status") or "unknown")
            stats.paseq_playback_status_counts[status] += 1
            stats.paseq_examples.setdefault(status, label)

    animation = document.get("animation_metadata", {})
    if not isinstance(animation, Mapping) or not animation:
        return
    declared_type = str(animation.get("declared_type") or "").strip()
    if declared_type:
        stats.animation_type_counts[declared_type] += 1
        stats.animation_examples.setdefault(declared_type, label)
    for hint in animation.get("filename_hints") or []:
        if not isinstance(hint, Mapping):
            continue
        hint_key = f"{hint.get('kind') or 'Hint'}: {hint.get('meaning') or hint.get('token') or ''}".strip()
        if hint_key:
            stats.animation_hint_counts[hint_key] += 1
            stats.animation_examples.setdefault(hint_key, label)
    stream = animation.get("packed_metadata_stream", {})
    if isinstance(stream, Mapping) and int(stream.get("stream_size") or 0) > 0:
        bucket = (int(stream.get("stream_size") or 0) // 256) * 256
        stats.animation_stream_size_counts[bucket] += 1
        stats.animation_examples.setdefault(f"stream_0x{bucket:08X}", label)


def _record_schema(stats: _ExtensionStats, document: Mapping[str, object], label: str) -> None:
    schema = document.get("schema_declarations", {})
    if not isinstance(schema, Mapping):
        return
    rows = [row for row in schema.get("declared_member_rows", []) if isinstance(row, Mapping)]
    signature = str(schema.get("layout_signature") or "")
    if signature:
        stats.layout_counts[signature] += 1
        region = schema.get("declaration_region", {})
        stats.layout_examples.setdefault(
            signature,
            {
                "signature": signature,
                "example_path": label,
                "declaration_count": len(rows),
                "first_fields": [str(row.get("name") or "") for row in rows[:8]],
                "candidate_value_region_start": int(region.get("candidate_value_region_start") or 0)
                if isinstance(region, Mapping)
                else 0,
            },
        )
    region = schema.get("declaration_region", {})
    if isinstance(region, Mapping) and int(region.get("candidate_value_region_start") or 0) > 0:
        region_start = int(region.get("candidate_value_region_start") or 0)
        region_bucket = (region_start // 256) * 256
        stats.value_region_counts[region_bucket] += 1
        stats.value_region_examples.setdefault(region_bucket, label)

    seen_names: set[str] = set()
    for row in rows:
        name = str(row.get("name") or "").strip()
        declared_type = str(row.get("declared_type") or "").strip()
        descriptor_hex = str(row.get("descriptor_hex") or "").strip()
        if not name or not declared_type:
            continue
        stats.field_decl_counts[name] += 1
        stats.field_type_counts[name][declared_type] += 1
        stats.field_descriptor_counts[(name, declared_type)][descriptor_hex] += 1
        stats.field_metadata.setdefault(
            (name, declared_type),
            {
                "group": str(row.get("group") or ""),
                "likely_kind": str(row.get("likely_kind") or ""),
                "array_status": str(row.get("array_status") or ""),
                "reference_status": str(row.get("reference_status") or ""),
                "confidence": str(row.get("confidence") or ""),
            },
        )
        if name not in seen_names:
            seen_names.add(name)
            stats.field_file_counts[name] += 1
        if _binary_sidecar_descriptor_is_unknown(row):
            stats.unknown_descriptor_counts[descriptor_hex] += 1
            stats.unknown_descriptor_examples.setdefault(
                descriptor_hex,
                {
                    "descriptor_hex": descriptor_hex,
                    "example_path": label,
                    "example_field": name,
                    "declared_type": declared_type,
                    "type_code": int(row.get("type_code") or 0),
                },
            )

    tables = document.get("tables", {})
    float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
    for row in float_rows[:8]:
        if isinstance(row, Mapping) and int(row.get("offset") or 0) > 0:
            offset = int(row.get("offset") or 0)
            bucket = (offset // 256) * 256
            stats.numeric_region_counts[bucket] += 1
            stats.numeric_region_examples.setdefault(bucket, label)


def _scan_extension_paths(
    stats: _ExtensionStats,
    paths: Sequence[Path],
    source_paths: Sequence[Path],
    *,
    stop_event: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, int, str], None]],
    progress_offset: int,
    progress_total: int,
) -> None:
    total = progress_total or len(paths)
    for local_index, path in enumerate(paths, start=1):
        raise_if_cancelled(stop_event)
        label = _binary_sidecar_corpus_path_label(path, source_paths)
        if progress_callback is not None:
            progress_callback(
                progress_offset + local_index - 1,
                total,
                f"Scanning binary sidecar corpus {progress_offset + local_index:,} / {total:,}: {path.name}",
            )
        try:
            document = build_binary_sidecar_analysis_document(
                path.read_bytes(), label, extension=path.suffix.lower()
            )
        except RunCancelled:
            raise
        except Exception as exc:
            stats.failed_rows.append({"path": label, "error": str(exc)})
            continue
        stats.scanned_count += 1
        _record_seqmt_and_paccd(stats, document, label)
        _record_paseq_and_animation(stats, document, label)
        _record_schema(stats, document, label)


def _stable_field_rows(stats: _ExtensionStats) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for name, file_count in stats.field_file_counts.items():
        type_counts = stats.field_type_counts.get(name, Counter())
        if not type_counts:
            continue
        declared_type, type_count = type_counts.most_common(1)[0]
        descriptor_counts = stats.field_descriptor_counts.get((name, declared_type), Counter())
        descriptor_hex, descriptor_count = descriptor_counts.most_common(1)[0] if descriptor_counts else ("", 0)
        metadata = stats.field_metadata.get((name, declared_type), {})
        rows.append(
            {
                "name": name,
                "declared_type": declared_type,
                "files_with_field": int(file_count),
                "declaration_count": int(stats.field_decl_counts.get(name, 0)),
                "type_consistency": round(type_count / max(sum(type_counts.values()), 1), 4),
                "top_descriptor_hex": descriptor_hex,
                "top_descriptor_count": int(descriptor_count),
                "descriptor_consistency": round(descriptor_count / max(type_count, 1), 4),
                "group": metadata.get("group", ""),
                "likely_kind": metadata.get("likely_kind", ""),
                "array_status": metadata.get("array_status", ""),
                "reference_status": metadata.get("reference_status", ""),
                "confidence": metadata.get("confidence", ""),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row.get("files_with_field") or 0),
            -float(row.get("type_consistency") or 0.0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows


def _layout_unknown_and_region_rows(stats: _ExtensionStats) -> Tuple[List[Dict[str, object]], ...]:
    layouts = []
    for signature, count in stats.layout_counts.most_common(64):
        row = dict(stats.layout_examples.get(signature, {}))
        row["file_count"] = int(count)
        layouts.append(row)
    unknown = []
    for descriptor_hex, count in stats.unknown_descriptor_counts.most_common(64):
        row = dict(stats.unknown_descriptor_examples.get(descriptor_hex, {"descriptor_hex": descriptor_hex}))
        row["count"] = int(count)
        unknown.append(row)
    regions = [
        {
            "region_start_bucket": f"0x{start:08X}",
            "file_count": int(count),
            "source": "declaration_end_bucket",
            "example_path": stats.value_region_examples.get(start, ""),
        }
        for start, count in stats.value_region_counts.most_common(32)
    ]
    regions.extend(
        {
            "region_start_bucket": f"0x{start:08X}",
            "file_count": int(count),
            "source": "numeric_candidate_bucket",
            "example_path": stats.numeric_region_examples.get(start, ""),
        }
        for start, count in stats.numeric_region_counts.most_common(32)
    )
    return layouts, unknown, regions


def _animation_rows(stats: _ExtensionStats) -> Dict[str, object]:
    return {
        "declared_types": [
            {"declared_type": name, "file_count": int(count), "example_path": stats.animation_examples.get(name, "")}
            for name, count in stats.animation_type_counts.most_common(16)
        ],
        "filename_hints": [
            {"hint": name, "file_count": int(count), "example_path": stats.animation_examples.get(name, "")}
            for name, count in stats.animation_hint_counts.most_common(32)
        ],
        "packed_stream_size_buckets": [
            {
                "stream_size_bucket": f"0x{bucket:08X}",
                "file_count": int(count),
                "example_path": stats.animation_examples.get(f"stream_0x{bucket:08X}", ""),
            }
            for bucket, count in stats.animation_stream_size_counts.most_common(32)
        ],
    }


def _seqmt_rows(stats: _ExtensionStats) -> Dict[str, object]:
    return {
        "atlas_grids": [
            {"grid": name, "file_count": int(count), "example_path": stats.seqmt_examples.get(name, "")}
            for name, count in stats.seqmt_grid_counts.most_common(32)
        ],
        "flag_or_packing_bytes": [
            {
                "value": f"0x{value:02X}",
                "file_count": int(count),
                "example_path": stats.seqmt_examples.get(f"flag_0x{value:02X}", ""),
            }
            for value, count in stats.seqmt_flag_counts.most_common(16)
        ],
        "payload_statuses": [
            {"status": name, "file_count": int(count), "example_path": stats.seqmt_examples.get(name, "")}
            for name, count in stats.seqmt_payload_status_counts.most_common(16)
        ],
    }


def _paccd_rows(stats: _ExtensionStats) -> Dict[str, object]:
    return {
        "layout_families": [
            {"format_family": name, "file_count": int(count), "example_path": stats.paccd_examples.get(name, "")}
            for name, count in stats.paccd_layout_counts.most_common(16)
        ],
        "slot_counts": [
            {
                "slot_count": int(value),
                "file_count": int(count),
                "example_path": stats.paccd_examples.get(f"slot_{value}", ""),
            }
            for value, count in stats.paccd_slot_counts.most_common(16)
        ],
        "row_strides": [
            {
                "row_stride": int(value),
                "file_count": int(count),
                "example_path": stats.paccd_examples.get(f"stride_{value}", ""),
            }
            for value, count in stats.paccd_stride_counts.most_common(16)
        ],
    }


def _paseq_rows(stats: _ExtensionStats) -> Dict[str, object]:
    specs = (
        ("playback_statuses", "status", stats.paseq_playback_status_counts, ""),
        ("timeline_lane_buckets", "lane_count", stats.paseq_lane_counts, "lanes_"),
        ("animation_lane_buckets", "lane_count", stats.paseq_animation_lane_counts, "animation_"),
        ("effect_lane_buckets", "lane_count", stats.paseq_effect_lane_counts, "effect_"),
        ("context_lane_buckets", "lane_count", stats.paseq_context_lane_counts, "context_"),
    )
    result: Dict[str, object] = {}
    for output_name, value_name, counts, prefix in specs:
        result[output_name] = [
            {
                value_name: name if value_name == "status" else int(name),
                "file_count": int(count),
                "example_path": stats.paseq_examples.get(f"{prefix}{name}", ""),
            }
            for name, count in counts.most_common(16)
        ]
    return result


def _build_binary_sidecar_corpus_extension_report(
    paths: Sequence[Path],
    source_paths: Sequence[Path],
    *,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_offset: int = 0,
    progress_total: int = 0,
) -> Dict[str, object]:
    stats = _ExtensionStats()
    _scan_extension_paths(
        stats,
        paths,
        source_paths,
        stop_event=stop_event,
        progress_callback=progress_callback,
        progress_offset=progress_offset,
        progress_total=progress_total,
    )
    layouts, unknown, regions = _layout_unknown_and_region_rows(stats)
    return {
        "files_scanned": stats.scanned_count,
        "files_failed": len(stats.failed_rows),
        "failed_rows": stats.failed_rows[:32],
        "layout_signatures": layouts,
        "stable_fields": _stable_field_rows(stats)[:256],
        "unknown_descriptor_bytes": unknown,
        "candidate_value_regions": regions,
        "animation_metadata": _animation_rows(stats),
        "seqmt": _seqmt_rows(stats),
        "paccd": _paccd_rows(stats),
        "paseq": _paseq_rows(stats),
    }


def build_binary_sidecar_corpus_report(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    normalized_sources = tuple(Path(path).expanduser() for path in source_paths)
    discovered_paths = _discover_binary_sidecar_corpus_paths(
        normalized_sources,
        discovery_limit=discovery_limit,
        stop_event=stop_event,
    )
    max_detail = int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None
    detail_paths = _select_balanced_binary_sidecar_detail_paths(discovered_paths, max_detail)
    by_extension_paths: Dict[str, List[Path]] = defaultdict(list)
    for path in detail_paths:
        by_extension_paths[path.suffix.lower()].append(path)

    progress_total = max(len(detail_paths), 1)
    if progress_callback is not None:
        progress_callback(0, progress_total, f"Discovered {len(discovered_paths):,} binary sidecar file(s).")
    by_extension: Dict[str, object] = {}
    progress_offset = 0
    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        extension_paths = by_extension_paths.get(extension, [])
        by_extension[extension] = _build_binary_sidecar_corpus_extension_report(
            extension_paths,
            normalized_sources,
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_offset=progress_offset,
            progress_total=progress_total,
        )
        progress_offset += len(extension_paths)
    if progress_callback is not None:
        progress_callback(progress_total, progress_total, "Binary sidecar corpus report complete.")

    return {
        "document": "Crimson Desert Mod Workbench binary sidecar corpus report.",
        "format": "cdmw_binary_sidecar_corpus_v1",
        "format_status": "experimental_read_only_schema_recovery",
        "source_paths": [str(path) for path in normalized_sources],
        "summary": {
            "files_discovered": len(discovered_paths),
            "files_scanned": len(detail_paths),
            "discovery_limit": int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None,
            "detail_scan_limit": int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None,
            **{
                f"{extension.lstrip('.').replace('.', '_')}_files_scanned": len(by_extension_paths.get(extension, []))
                for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS
            },
        },
        "by_extension": by_extension,
        "editing": {
            "supported": False,
            "policy": "read_only_until_exact_value_offsets_and_no_edit_rebuilds_are_proven",
            "reason": "Corpus ranking proves declarations and layout frequency, not safe write offsets.",
        },
    }


def build_binary_sidecar_corpus_json(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_binary_sidecar_corpus_report(
            source_paths,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
    )
