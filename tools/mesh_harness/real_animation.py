from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from collections.abc import Sequence
from cdmw.core.archive_binary_preview import build_binary_sidecar_analysis_document
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.animation_parser import parse_paa_animation_clip
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.modding.skeleton_variation_parser import parse_pabc_skeleton_variation
from cdmw.core.skeleton_resolver import resolve_skeleton_for_model

from tools.mesh_harness.constants import (
    _REAL_ARCHIVE_ANIMATION_PREFERRED_PAA,
    _REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT,
    _REAL_ARCHIVE_RIGGING_SAMPLES,
)

from tools.mesh_harness.evidence import (
    _mesh_editor_advanced_authoring_corpus_manifest,
)

from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _archive_key,
    _read_archive_payload,
)

from tools.mesh_harness.service_summary import (
    _mesh_vertices_changed,
)

def run_real_archive_animation_binding_smoke(game_root: Path) -> dict[str, object]:
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT: {pamt_path}",
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
        }

    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    corpus_manifest = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    model_path = _REAL_ARCHIVE_RIGGING_SAMPLES[0]
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {
            "ok": False,
            "read_only": True,
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
            "model_path": model_path,
            "corpus_manifest": corpus_manifest,
            "error": "model entry not found",
        }

    try:
        pac_data = _read_archive_payload(model_entry)
        skeleton_entry, report = resolve_skeleton_for_model(
            model_entry,
            entries,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
            pac_data=pac_data,
            read_entry_data=_read_archive_payload,
        )
        if skeleton_entry is None:
            return {
                "ok": False,
                "read_only": True,
                "game_root": str(game_root),
                "pamt_path": str(pamt_path),
                "model_path": model_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "corpus_manifest": corpus_manifest,
                "error": "skeleton entry not resolved",
            }

        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        variation_summary = _real_archive_skeleton_variation_summary(report.skeleton_variation_path, entries_by_path, skeleton)
        bone_names = _skeleton_bone_name_bytes(skeleton)
        paa_entries = _real_archive_animation_sample_entries(entries, entries_by_path, _REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT)
        samples: list[dict[str, object]] = []
        selected_clip = None
        for entry in paa_entries:
            sample, clip = _analyse_real_archive_animation_entry(entry, bone_names, skeleton=skeleton)
            samples.append(sample)
            if selected_clip is None and clip is not None:
                selected_clip = clip
        paa_count = sum(1 for entry in entries if _archive_key(entry.path).endswith(".paa"))
        paseq_count = sum(1 for entry in entries if _archive_key(entry.path).endswith(".paseq"))
        total_keyframe_rows = sum(int(sample.get("keyframe_rows") or 0) for sample in samples)
        total_exact_tracks = sum(int(sample.get("exact_bone_hash_track_count") or 0) for sample in samples)
        total_bound_bones = sum(int(sample.get("bound_bone_count") or 0) for sample in samples)
        total_bone_name_hits = sum(int(sample.get("bone_name_hit_count") or 0) for sample in samples)
        safe_playback_ready = selected_clip is not None
        playback_pose_changed = (
            _prove_real_archive_paa_playback_deformation(mesh, skeleton, selected_clip)
            if selected_clip is not None
            else False
        )
        blockers = _real_archive_animation_binding_blockers(
            sample_count=len(samples),
            keyframe_rows=total_keyframe_rows,
            exact_tracks=total_exact_tracks,
            bound_bones=total_bound_bones,
            bone_name_hits=total_bone_name_hits,
            paseq_count=paseq_count,
        )
        return {
            "ok": bool(
                report.confidence == "descriptor"
                and samples
                and variation_summary.get("matched_record_count")
                and safe_playback_ready
            ),
            "read_only": True,
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
            "entry_count": len(entries),
            "model_path": model_entry.path,
            "skeleton_path": skeleton_entry.path,
            "confidence": report.confidence,
            "descriptor_path": report.descriptor_path,
            "skeleton_variation_path": report.skeleton_variation_path,
            "animation_constraint_path": report.animation_constraint_path,
            "socket_path": report.socket_path,
            "corpus_manifest": corpus_manifest,
            "skeleton_variation": variation_summary,
            "bone_count": int(getattr(skeleton, "bone_count", 0) or len(getattr(skeleton, "bones", ()) or ())),
            "paa_entry_count": int(paa_count),
            "paseq_entry_count": int(paseq_count),
            "sample_count": len(samples),
            "safe_playback_ready": safe_playback_ready,
            "playback_pose_changed": playback_pose_changed,
            "selected_clip_source": getattr(selected_clip, "source", "") if selected_clip is not None else "",
            "binding_blockers": blockers,
            "total_keyframe_rows": int(total_keyframe_rows),
            "total_exact_bone_hash_track_count": int(total_exact_tracks),
            "total_bound_bone_count": int(total_bound_bones),
            "total_bone_name_hits": int(total_bone_name_hits),
            "samples": samples,
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "model_path": model_entry.path,
            "corpus_manifest": corpus_manifest,
            "error": f"{type(exc).__name__}: {exc}",
        }

def _real_archive_skeleton_variation_summary(
    variation_path: str,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    skeleton: object,
) -> dict[str, object]:
    entry = next(iter(entries_by_path.get(_archive_key(variation_path), ())), None)
    if entry is None:
        return {"path": variation_path, "found": False}
    try:
        variation = parse_pabc_skeleton_variation(_read_archive_payload(entry), entry.path, skeleton=skeleton)
    except Exception as exc:
        return {"path": variation_path, "found": True, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "path": entry.path,
        "found": True,
        "record_count": variation.record_count,
        "matched_record_count": variation.matched_record_count,
        "record_stride": variation.record_stride,
        "tail_size": variation.tail_size,
        "confidence": variation.confidence,
        "first_records": [
            {
                "bone_hash": record.bone_hash,
                "bone_index": record.bone_index,
                "bone_name": record.bone_name,
                "offset": record.offset,
            }
            for record in variation.records[:8]
        ],
    }

def _real_archive_animation_sample_entries(
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    limit: int,
) -> tuple[ArchiveEntry, ...]:
    selected: list[ArchiveEntry] = []
    seen: set[str] = set()

    def append(entry: ArchiveEntry | None) -> None:
        if entry is None or len(selected) >= limit:
            return
        key = _archive_key(entry.path)
        if key and key not in seen:
            selected.append(entry)
            seen.add(key)

    for path in _REAL_ARCHIVE_ANIMATION_PREFERRED_PAA:
        append(next(iter(entries_by_path.get(_archive_key(path), ())), None))

    local_entries = [
        entry
        for entry in entries
        if _archive_key(entry.path).endswith(".paa") and "/1_pc/14_ptm/" in _archive_key(entry.path)
    ]
    for entry in _evenly_spaced_entries(local_entries, limit - len(selected)):
        append(entry)

    if len(selected) < limit:
        all_paa_entries = [entry for entry in entries if _archive_key(entry.path).endswith(".paa")]
        for entry in _evenly_spaced_entries(all_paa_entries, limit - len(selected)):
            append(entry)

    return tuple(selected)

def _evenly_spaced_entries(entries: Sequence[ArchiveEntry], limit: int) -> tuple[ArchiveEntry, ...]:
    if limit <= 0 or not entries:
        return ()
    if len(entries) <= limit:
        return tuple(entries)
    if limit == 1:
        return (entries[0],)
    indexes: list[int] = []
    span = len(entries) - 1
    for index in range(limit):
        candidate = round(index * span / (limit - 1))
        if candidate not in indexes:
            indexes.append(candidate)
    return tuple(entries[index] for index in indexes[:limit])

def _analyse_real_archive_animation_entry(
    entry: ArchiveEntry,
    bone_names: Sequence[bytes],
    *,
    skeleton: object,
) -> tuple[dict[str, object], object | None]:
    data = _read_archive_payload(entry)
    document = build_binary_sidecar_analysis_document(data, entry.path, extension=".paa")
    animation = document.get("animation", {}) if isinstance(document, dict) else {}
    tables = list(animation.get("keyframe_table_candidates") or ()) if isinstance(animation, dict) else []
    strings = (document.get("strings", {}) or {}).get("readable_rows", ()) if isinstance(document, dict) else ()
    relationships = document.get("references", {}) if isinstance(document, dict) else {}
    asset_references = (relationships.get("asset_reference_hints", {}) or ()) if isinstance(relationships, dict) else ()
    raw = data.lower()
    bone_name_hits = [name.decode("ascii", "ignore") for name in bone_names if name and name in raw]
    first_table = tables[0] if tables and isinstance(tables[0], dict) else {}
    clip, binding = parse_paa_animation_clip(data, entry.path, skeleton=skeleton)
    return {
        "path": entry.path,
        "size": len(data),
        "keyframe_table_candidates": len(tables),
        "keyframe_rows": sum(int(table.get("row_count") or 0) for table in tables if isinstance(table, dict)),
        "exact_bone_hash_track_count": binding.exact_bone_hash_track_count,
        "bound_bone_count": binding.bound_bone_count,
        "bound_keyframe_count": binding.keyframe_count,
        "frame_start": binding.frame_start,
        "frame_end": binding.frame_end,
        "frame_rate": binding.frame_rate,
        "frame_rate_source": binding.frame_rate_source,
        "frame_rate_confidence": binding.frame_rate_confidence,
        "timing_status": binding.timing_status,
        "game_accurate_timing": bool(getattr(clip, "game_accurate_timing", False)) if clip is not None else False,
        "duration_seconds": float(getattr(clip, "duration_seconds", 0.0) or 0.0) if clip is not None else 0.0,
        "quaternion_order": binding.quaternion_order,
        "parser_mode": binding.parser_mode,
        "string_record_count": len(strings),
        "asset_reference_count": len(asset_references),
        "bone_name_hit_count": len(bone_name_hits),
        "bone_name_hits": bone_name_hits[:8],
        "first_table": {
            key: first_table.get(key)
            for key in ("offset", "row_count", "frame_start", "frame_end", "value_kind", "row_format", "confidence")
        },
    }, clip

def _skeleton_bone_name_bytes(skeleton: object) -> tuple[bytes, ...]:
    result: list[bytes] = []
    seen: set[bytes] = set()
    for bone in tuple(getattr(skeleton, "bones", ()) or ()):
        name = str(getattr(bone, "name", "") or "").strip()
        encoded = name.encode("ascii", "ignore").lower()
        if len(encoded) >= 4 and encoded not in seen:
            result.append(encoded)
            seen.add(encoded)
    return tuple(result)

def _real_archive_animation_binding_blockers(
    *,
    sample_count: int,
    keyframe_rows: int,
    exact_tracks: int,
    bound_bones: int,
    bone_name_hits: int,
    paseq_count: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if sample_count <= 0:
        blockers.append("No .paa payloads were sampled from the real archive index.")
    if keyframe_rows <= 0:
        blockers.append("Sampled PAA payloads exposed no decoded value-keyframe rows in the current inspector.")
    if exact_tracks <= 0:
        blockers.append("Sampled PAA keyframe tables did not have PAB bone hashes at table_offset - 8.")
        if bone_name_hits <= 0:
            blockers.append("Sampled PAA payloads contained no attached PAB bone-name strings.")
    if bound_bones <= 0:
        blockers.append("No sampled PAA tracks could be bound to attached PAB bones.")
    if exact_tracks <= 0 and paseq_count <= 0:
        blockers.append("No .paseq entries were present in the sampled package index for sequence context.")
    return tuple(blockers)

def _sequence_frame_rate_metadata(probe: Mapping[str, object]) -> tuple[str, str]:
    if int(probe.get("explicit_fps_field_count") or 0) > 0:
        return "source_paseq_framesPerSecond_field_unbound", "unknown"
    float_counts = probe.get("float_counts") if isinstance(probe.get("float_counts"), Mapping) else {}
    if any(int(float_counts.get(str(value), 0) or 0) > 0 for value in (15, 24, 30, 60)):
        return "sequence_float_fps_candidate", "inferred"
    return "parser_default_30fps", "inferred"

def _sample_real_archive_paa_playback(mesh: ParsedMesh, skeleton: object, clip: object) -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(mesh, mode="edit")
    service.attach_skeleton(view.session_id, skeleton)
    service.attach_animation_clip(view.session_id, clip)  # type: ignore[arg-type]
    duration = float(getattr(clip, "duration_seconds", 0.0) or 0.0)
    sample_time = min(max(duration * 0.5, 1.0 / 30.0), 2.0)
    before = service.working_mesh(view.session_id, clone=True)
    summary = service.seek_animation(view.session_id, sample_time)
    preview = service.pose_preview_mesh(view.session_id)
    repeat_summary = service.seek_animation(view.session_id, sample_time)
    repeat_preview = service.pose_preview_mesh(view.session_id)
    after = service.working_mesh(view.session_id, clone=True)
    playback = summary.animation_playback
    repeat_playback = repeat_summary.animation_playback
    time_seconds = float(playback.time_seconds)
    repeat_time_seconds = float(repeat_playback.time_seconds)
    sampled_bone_count = int(playback.sampled_bone_count)
    repeat_sampled_bone_count = int(repeat_playback.sampled_bone_count)
    return {
        "ready": bool(playback.ready),
        "enabled": bool(playback.enabled),
        "time_seconds": time_seconds,
        "repeat_time_seconds": repeat_time_seconds,
        "duration_seconds": float(playback.duration_seconds),
        "sampled_bone_count": sampled_bone_count,
        "repeat_sampled_bone_count": repeat_sampled_bone_count,
        "sequence_segment_count": int(playback.sequence_segment_count),
        "active_sequence_lane_index": int(playback.active_sequence_lane_index),
        "active_sequence_path": str(playback.active_sequence_path or ""),
        "active_sequence_clip_path": str(playback.active_sequence_clip_path or ""),
        "active_sequence_status": str(playback.active_sequence_status or ""),
        "pose_changed": _mesh_vertices_changed(before, preview),
        "deterministic_repeat_seek": bool(
            abs(time_seconds - repeat_time_seconds) <= 1e-9
            and sampled_bone_count == repeat_sampled_bone_count
            and not _mesh_vertices_changed(preview, repeat_preview)
        ),
        "export_geometry_unchanged": not _mesh_vertices_changed(before, after),
        "timing_confidence": str(playback.timing_confidence or ""),
        "timing_status": str(playback.timing_status or ""),
        "game_accurate_timing": bool(playback.game_accurate_timing),
        "status": str(playback.status or ""),
    }

def _prove_real_archive_paa_playback_deformation(mesh: ParsedMesh, skeleton: object, clip: object) -> bool:
    return bool(_sample_real_archive_paa_playback(mesh, skeleton, clip).get("pose_changed"))
