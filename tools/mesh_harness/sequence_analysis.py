from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
from cdmw.core.archive_extraction import _read_archive_entry_data_from_handle
import struct

from tools.mesh_harness.constants import (
    _REAL_ARCHIVE_SEQUENCE_EXTENSIONS,
)

from tools.mesh_harness.real_common import (
    _archive_key,
    _real_archive_extension_counts_by_package,
)

def _real_archive_sequence_timing_corpus_summary(entries: Sequence[ArchiveEntry]) -> dict[str, object]:
    sequence_entries = [
        entry
        for entry in entries
        if str(entry.extension or "").lower() in _REAL_ARCHIVE_SEQUENCE_EXTENSIONS
    ]
    by_extension_counts = _real_archive_extension_counts_by_package(sequence_entries, _REAL_ARCHIVE_SEQUENCE_EXTENSIONS)
    entries_by_paz: dict[Path, list[ArchiveEntry]] = {}
    for entry in sequence_entries:
        entries_by_paz.setdefault(entry.paz_file, []).append(entry)
    field_counts: Counter[str] = Counter()
    integer_counts: Counter[str] = Counter()
    float_counts: Counter[str] = Counter()
    per_extension: dict[str, Counter[str]] = {}
    explicit_fps_paths: list[str] = []
    float_fps_paths: list[str] = []
    errors: list[dict[str, str]] = []
    read_count = 0
    for paz_file, paz_entries in entries_by_paz.items():
        try:
            handle_context = paz_file.open("rb")
        except Exception as exc:
            for entry in paz_entries[:8 - len(errors)]:
                errors.append({"path": entry.path, "error": f"{type(exc).__name__}: {exc}"})
            continue
        with handle_context as handle:
            for entry in paz_entries:
                extension = str(entry.extension or "").lower()
                extension_counts = per_extension.setdefault(extension, Counter())
                extension_counts["files"] += 1
                try:
                    data, _decompressed, _note = _read_archive_entry_data_from_handle(handle, entry)
                except Exception as exc:
                    if len(errors) < 8:
                        errors.append({"path": entry.path, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                read_count += 1
                probe = _binary_timing_probe_counts(data)
                for name, count in (probe.get("field_counts") or {}).items():
                    value = int(count or 0)
                    field_counts[str(name)] += value
                    extension_counts[str(name)] += value
                for name, count in (probe.get("integer_counts") or {}).items():
                    value = int(count or 0)
                    integer_counts[str(name)] += value
                    extension_counts[f"u{name}"] += value
                current_float_total = 0
                for name, count in (probe.get("float_counts") or {}).items():
                    value = int(count or 0)
                    float_counts[str(name)] += value
                    extension_counts[f"f{name}"] += value
                    current_float_total += value
                if int(probe.get("explicit_fps_field_count") or 0) > 0 and len(explicit_fps_paths) < 8:
                    explicit_fps_paths.append(entry.path)
                if current_float_total > 0 and len(float_fps_paths) < 8:
                    float_fps_paths.append(entry.path)
    explicit_fps_total = int(field_counts.get("_framespersecond", 0))
    float_fps_total = sum(int(float_counts.get(str(value), 0)) for value in (15, 24, 30, 60))
    status = (
        "explicit_fps_evidence_found_in_sequence_family_corpus"
        if explicit_fps_total > 0
        else "fps_float_candidates_only_in_sequence_family_corpus"
        if float_fps_total > 0
        else "no_explicit_fps_evidence_in_sequence_family_corpus"
    )
    return {
        "entry_count": len(sequence_entries),
        "read_count": read_count,
        "error_count": len(sequence_entries) - read_count,
        "entry_counts_by_package": by_extension_counts,
        "field_counts": dict(field_counts),
        "integer_counts": dict(integer_counts),
        "float_counts": dict(float_counts),
        "per_extension": {extension: dict(counter) for extension, counter in sorted(per_extension.items())},
        "explicit_fps_field_count": explicit_fps_total,
        "float_fps_value_count": float_fps_total,
        "explicit_fps_examples": tuple(explicit_fps_paths),
        "float_fps_examples": tuple(float_fps_paths),
        "read_errors": tuple(errors),
        "fps_evidence_status": status,
    }

def _source_sequence_path_for_compiled_sequence(path: object) -> str:
    value = str(path or "").replace("\\", "/").strip()
    lowered = value.lower()
    if lowered.endswith(".paseqc"):
        return value[:-1]
    return value

def _document_asset_reference_paths(document: Mapping[str, object]) -> tuple[str, ...]:
    references = document.get("references", {}) if isinstance(document, Mapping) else {}
    rows = references.get("asset_reference_hints", ()) if isinstance(references, Mapping) else ()
    result: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, Sequence) else ():
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace("\\", "/").strip()
        key = _archive_key(path)
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)

def _sequence_reference_overlap(
    source_refs: Sequence[str],
    compiled_refs: Sequence[str],
    *,
    active_path: object = "",
) -> dict[str, object]:
    source_keys = {_archive_key(path) for path in source_refs if _archive_key(path)}
    compiled_keys = {_archive_key(path) for path in compiled_refs if _archive_key(path)}
    overlap = tuple(path for path in source_refs if _archive_key(path) in compiled_keys)
    source_only = tuple(path for path in source_refs if _archive_key(path) not in compiled_keys)
    compiled_only = tuple(path for path in compiled_refs if _archive_key(path) not in source_keys)
    active_key = _archive_key(active_path)
    active_in_overlap = bool(active_key and active_key in {_archive_key(path) for path in overlap})
    overlap_paa_count = sum(1 for path in overlap if str(path).lower().endswith(".paa"))
    status = (
        "source_compiled_clip_reference_overlap"
        if overlap_paa_count > 0
        else "no_source_compiled_clip_reference_overlap"
    )
    return {
        "status": status,
        "confidence": "proven_reference_string_overlap" if overlap_paa_count > 0 else "blocked",
        "source_reference_count": len(source_refs),
        "compiled_reference_count": len(compiled_refs),
        "overlap_reference_count": len(overlap),
        "source_only_reference_count": len(source_only),
        "compiled_only_reference_count": len(compiled_only),
        "source_paa_reference_count": sum(1 for path in source_refs if str(path).lower().endswith(".paa")),
        "compiled_paa_reference_count": sum(1 for path in compiled_refs if str(path).lower().endswith(".paa")),
        "overlap_paa_reference_count": overlap_paa_count,
        "active_clip_in_overlap": active_in_overlap,
        "overlap_paths": overlap,
        "source_only_paths": source_only,
        "compiled_only_paths": compiled_only,
    }

def _sequence_lane_pair_summary(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
    *,
    active_path: object = "",
) -> dict[str, object]:
    source_lanes = tuple(
        row for row in (source_timeline.get("lanes") or ()) if isinstance(row, Mapping)
    ) if isinstance(source_timeline, Mapping) else ()
    compiled_lanes = tuple(
        row for row in (compiled_timeline.get("lanes") or ()) if isinstance(row, Mapping)
    ) if isinstance(compiled_timeline, Mapping) else ()
    compiled_by_key = {
        _archive_key(row.get("path")): row
        for row in compiled_lanes
        if _archive_key(row.get("path"))
    }
    active_key = _archive_key(active_path)
    pairs: list[dict[str, object]] = []
    for source_lane in source_lanes:
        key = _archive_key(source_lane.get("path"))
        compiled_lane = compiled_by_key.get(key)
        if not key or compiled_lane is None:
            continue
        pairs.append(
            {
                "path": str(source_lane.get("path") or ""),
                "source_lane_index": int(source_lane.get("index") or 0),
                "compiled_lane_index": int(compiled_lane.get("index") or 0),
                "source_offset": int(source_lane.get("source_offset") or 0),
                "compiled_offset": int(compiled_lane.get("source_offset") or 0),
                "source_confidence": str(source_lane.get("confidence") or ""),
                "compiled_confidence": str(compiled_lane.get("confidence") or ""),
                "active_clip": bool(active_key and key == active_key),
                "status": "source_compiled_lane_pair_read_only",
                "confidence": "proven_reference_string_overlap",
            }
        )
    active_pair_count = sum(1 for row in pairs if bool(row.get("active_clip")))
    return {
        "status": "source_compiled_lane_pair_overlap" if pairs else "no_source_compiled_lane_pair_overlap",
        "confidence": "proven_reference_string_overlap" if pairs else "blocked",
        "source_lane_count": len(source_lanes),
        "compiled_lane_count": len(compiled_lanes),
        "lane_pair_count": len(pairs),
        "active_lane_pair_count": active_pair_count,
        "lane_pairs": tuple(pairs),
    }

def _sequence_event_marker_overlap(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    source_markers = tuple(
        row for row in (source_timeline.get("event_markers") or ()) if isinstance(row, Mapping)
    ) if isinstance(source_timeline, Mapping) else ()
    compiled_markers = tuple(
        row for row in (compiled_timeline.get("event_markers") or ()) if isinstance(row, Mapping)
    ) if isinstance(compiled_timeline, Mapping) else ()
    compiled_by_key: dict[str, Mapping[str, object]] = {}
    for row in compiled_markers:
        key = str(row.get("text") or "").strip().casefold()
        if key and key not in compiled_by_key:
            compiled_by_key[key] = row
    source_keys = {str(row.get("text") or "").strip().casefold() for row in source_markers}
    source_keys.discard("")
    compiled_keys = set(compiled_by_key)
    overlap_rows: list[dict[str, object]] = []
    for row in source_markers:
        text = str(row.get("text") or "").strip()
        key = text.casefold()
        compiled_row = compiled_by_key.get(key)
        if not text or compiled_row is None:
            continue
        overlap_rows.append(
            {
                "text": text,
                "source_offset": int(row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_role": str(row.get("role") or ""),
                "compiled_role": str(compiled_row.get("role") or ""),
                "status": "source_compiled_event_marker_overlap_read_only",
                "confidence": "proven_readable_string_overlap",
            }
        )
    source_only = tuple(
        str(row.get("text") or "").strip()
        for row in source_markers
        if str(row.get("text") or "").strip().casefold() not in compiled_keys
    )
    compiled_only = tuple(
        str(row.get("text") or "").strip()
        for row in compiled_markers
        if str(row.get("text") or "").strip().casefold() not in source_keys
    )
    return {
        "status": "source_compiled_event_marker_overlap" if overlap_rows else "no_source_compiled_event_marker_overlap",
        "confidence": "proven_readable_string_overlap" if overlap_rows else "blocked",
        "source_marker_count": len(source_markers),
        "compiled_marker_count": len(compiled_markers),
        "overlap_marker_count": len(overlap_rows),
        "source_only_marker_count": len(source_only),
        "compiled_only_marker_count": len(compiled_only),
        "overlap_markers": tuple(overlap_rows),
        "source_only_markers": source_only,
        "compiled_only_markers": compiled_only,
    }

def _sequence_timeline_field_overlap(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    def unique_fields(timeline: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        rows = tuple(
            row for row in (timeline.get("timeline_fields") or ()) if isinstance(row, Mapping)
        ) if isinstance(timeline, Mapping) else ()
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if key and key not in result:
                result[key] = row
        return result

    source_fields = unique_fields(source_timeline)
    compiled_fields = unique_fields(compiled_timeline)
    overlap_rows: list[dict[str, object]] = []
    for key, source_row in source_fields.items():
        compiled_row = compiled_fields.get(key)
        if compiled_row is None:
            continue
        overlap_rows.append(
            {
                "name": str(source_row.get("name") or ""),
                "role": str(source_row.get("role") or ""),
                "source_offset": int(source_row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_declared_type": str(source_row.get("declared_type") or ""),
                "compiled_declared_type": str(compiled_row.get("declared_type") or ""),
                "source_confidence": str(source_row.get("confidence") or ""),
                "compiled_confidence": str(compiled_row.get("confidence") or ""),
                "status": "source_compiled_timeline_field_overlap_read_only",
                "confidence": "proven_field_name_overlap",
            }
        )
    source_only = tuple(
        str(row.get("name") or "")
        for key, row in source_fields.items()
        if key not in compiled_fields
    )
    compiled_only = tuple(
        str(row.get("name") or "")
        for key, row in compiled_fields.items()
        if key not in source_fields
    )
    return {
        "status": "source_compiled_timeline_field_overlap" if overlap_rows else "no_source_compiled_timeline_field_overlap",
        "confidence": "proven_field_name_overlap" if overlap_rows else "blocked",
        "source_unique_field_count": len(source_fields),
        "compiled_unique_field_count": len(compiled_fields),
        "overlap_field_count": len(overlap_rows),
        "source_only_field_count": len(source_only),
        "compiled_only_field_count": len(compiled_only),
        "overlap_fields": tuple(overlap_rows),
        "source_only_fields": source_only,
        "compiled_only_fields": compiled_only,
    }

def _sequence_timeline_field_semantic_aliases(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    def unique_fields(timeline: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        rows = tuple(
            row for row in (timeline.get("timeline_fields") or ()) if isinstance(row, Mapping)
        ) if isinstance(timeline, Mapping) else ()
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if key and key not in result:
                result[key] = row
        return result

    def alias_key(name: object) -> str:
        text = str(name or "").strip().lstrip("_").casefold().replace("blending", "blend")
        return "".join(character for character in text if character.isalnum())

    source_fields = unique_fields(source_timeline)
    compiled_fields = unique_fields(compiled_timeline)
    source_only = {
        key: row
        for key, row in source_fields.items()
        if key not in compiled_fields
    }
    compiled_only_by_alias: dict[str, Mapping[str, object]] = {}
    for key, row in compiled_fields.items():
        if key in source_fields:
            continue
        alias = alias_key(row.get("name"))
        if alias and alias not in compiled_only_by_alias:
            compiled_only_by_alias[alias] = row

    alias_rows: list[dict[str, object]] = []
    unmatched_source_fields: list[str] = []
    for row in source_only.values():
        alias = alias_key(row.get("name"))
        compiled_row = compiled_only_by_alias.get(alias)
        if compiled_row is None:
            unmatched_source_fields.append(str(row.get("name") or ""))
            continue
        alias_rows.append(
            {
                "alias_key": alias,
                "source_name": str(row.get("name") or ""),
                "compiled_name": str(compiled_row.get("name") or ""),
                "source_offset": int(row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_declared_type": str(row.get("declared_type") or ""),
                "compiled_declared_type": str(compiled_row.get("declared_type") or ""),
                "status": "source_compiled_timeline_field_semantic_alias_read_only",
                "confidence": "inferred_name_alias_value_unbound",
            }
        )
    return {
        "status": "source_compiled_timeline_field_semantic_aliases" if alias_rows else "no_source_compiled_timeline_field_semantic_alias",
        "confidence": "inferred_name_alias_value_unbound" if alias_rows else "blocked",
        "alias_count": len(alias_rows),
        "alias_rows": tuple(alias_rows),
        "unmatched_source_fields": tuple(unmatched_source_fields),
    }

def _sequence_path_record_context(
    data: bytes,
    path: object,
    *,
    window_before: int = 96,
    window_after: int = 192,
) -> dict[str, object]:
    path_text = str(path or "").replace("\\", "/").strip()
    path_bytes = path_text.encode("ascii", errors="ignore")
    text_offset = data.find(path_bytes) if path_bytes else -1
    if text_offset < 0:
        return {
            "status": "path_not_found",
            "confidence": "blocked",
            "binding_status": "active_lane_record_layout_unbound",
            "path": path_text,
        }

    path_length_offset = -1
    if text_offset >= 4 and int(struct.unpack_from("<I", data, text_offset - 4)[0]) == len(path_bytes):
        path_length_offset = text_offset - 4
    window_start = max(0, text_offset - max(0, int(window_before)))
    window_end = min(len(data), text_offset + max(0, int(window_after)))
    strings: list[dict[str, object]] = []
    scalar_rows: list[dict[str, object]] = []
    fps_like_u32_count = 0
    float32_candidate_count = 0
    interesting_u32 = {1, 2, 5, 7, 15, 19, 24, 26, 30, 33, 35, 45, 60, 81, 111, 256, 257, 272, 768, 1024, 1536, 2048, 2304}

    for offset in range(window_start, max(window_start, window_end - 3)):
        word = int(struct.unpack_from("<I", data, offset)[0])
        if 3 <= word <= 160 and offset + 4 + word <= window_end:
            text_bytes = data[offset + 4 : offset + 4 + word]
            if all(32 <= byte < 127 for byte in text_bytes):
                strings.append(
                    {
                        "offset": offset,
                        "relative_offset": offset - text_offset,
                        "length": word,
                        "text": text_bytes.decode("ascii"),
                    }
                )

    first_aligned_offset = window_start + (-window_start % 4)
    for offset in range(first_aligned_offset, max(first_aligned_offset, window_end - 3), 4):
        word = int(struct.unpack_from("<I", data, offset)[0])
        if word in {15, 24, 30, 60}:
            fps_like_u32_count += 1
        float_value = float(struct.unpack_from("<f", data, offset)[0])
        is_float_candidate = 0.00001 <= abs(float_value) <= 10.0
        if is_float_candidate:
            float32_candidate_count += 1
        if word in interesting_u32 or is_float_candidate:
            row: dict[str, object] = {
                "offset": offset,
                "relative_offset": offset - text_offset,
                "u32": word,
                "hex": data[offset : offset + 4].hex(),
            }
            if is_float_candidate:
                row["float32"] = round(float_value, 6)
            scalar_rows.append(row)

    return {
        "status": "path_record_window_recovered",
        "confidence": "read_only_window_context",
        "binding_status": "active_lane_record_layout_unbound",
        "path": path_text,
        "path_length": len(path_bytes),
        "path_length_offset": path_length_offset,
        "path_text_offset": text_offset,
        "window_start": window_start,
        "window_end": window_end,
        "length_prefixed_string_count": len(strings),
        "length_prefixed_strings": tuple(strings[:12]),
        "fps_like_u32_count": fps_like_u32_count,
        "float32_candidate_count": float32_candidate_count,
        "scalar_rows": tuple(scalar_rows[:24]),
    }

def _paseq_lane_for_path(timeline: Mapping[str, object], path: object) -> Mapping[str, object]:
    target = _archive_key(path)
    if not target:
        return {}
    lanes = timeline.get("lanes", ()) if isinstance(timeline, Mapping) else ()
    for row in lanes if isinstance(lanes, Sequence) else ():
        if isinstance(row, Mapping) and _archive_key(row.get("path")) == target:
            return row
    return {}

def _document_paseq_timing_evidence(document: Mapping[str, object]) -> Mapping[str, object]:
    paseq = document.get("paseq", {}) if isinstance(document, Mapping) else {}
    timeline = paseq.get("timeline", {}) if isinstance(paseq, Mapping) else {}
    evidence = timeline.get("timing_evidence", {}) if isinstance(timeline, Mapping) else {}
    return evidence if isinstance(evidence, Mapping) else {}

def _document_related_resolved_paths(document: Mapping[str, object]) -> tuple[str, ...]:
    references = document.get("references", {}) if isinstance(document, Mapping) else {}
    rows = references.get("related_files", ()) if isinstance(references, Mapping) else ()
    result: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, Sequence) else ():
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("resolved_archive_path") or "").replace("\\", "/").strip()
        key = _archive_key(path)
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)

def _clip_sequence_segments_json(clip: object | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    segments = tuple(getattr(clip, "sequence_segments", ()) or ()) if clip is not None else ()
    for segment in segments:
        field_confidence = {
            str(name): str(confidence)
            for name, confidence in tuple(getattr(segment, "field_confidence", ()) or ())
        }
        rows.append(
            {
                "sequence_path": str(getattr(segment, "sequence_path", "") or ""),
                "clip_path": str(getattr(segment, "clip_path", "") or ""),
                "lane_index": int(getattr(segment, "lane_index", -1) or -1),
                "lane_source_offset": int(getattr(segment, "lane_source_offset", 0) or 0),
                "start_frame": int(getattr(segment, "start_frame", 0) or 0),
                "end_frame": int(getattr(segment, "end_frame", 0) or 0),
                "start_seconds": float(getattr(segment, "start_seconds", 0.0) or 0.0),
                "end_seconds": float(getattr(segment, "end_seconds", 0.0) or 0.0),
                "blend_weight": float(getattr(segment, "blend_weight", 1.0) or 1.0),
                "skeleton_source": str(getattr(segment, "skeleton_source", "") or ""),
                "status": str(getattr(segment, "status", "") or ""),
                "field_confidence": field_confidence,
            }
        )
    return rows

def _binary_timing_probe_counts(data: bytes) -> dict[str, object]:
    lowered = data.lower()
    field_counts = {
        "_framespersecond": lowered.count(b"_framespersecond"),
        "_starttimepiece": lowered.count(b"_starttimepiece"),
        "_endtimepiece": lowered.count(b"_endtimepiece"),
        "_duration": lowered.count(b"_duration"),
        "_frame": lowered.count(b"_frame"),
        "_time": lowered.count(b"_time"),
    }
    integer_counts = {str(value): data.count(struct.pack("<I", value)) for value in (15, 24, 30, 60)}
    float_counts = {str(value): data.count(struct.pack("<f", float(value))) for value in (15, 24, 30, 60)}
    return {
        "field_counts": field_counts,
        "integer_counts": integer_counts,
        "float_counts": float_counts,
        "explicit_fps_field_count": field_counts["_framespersecond"],
    }
