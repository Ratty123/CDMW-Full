"""Read-only PAA animation ownership parser."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Mapping

from cdmw.core.archive_binary_preview import _binary_sidecar_animation_keyframe_tables
from cdmw.domain.mesh.skeleton import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
)

_TIMING_CONFIDENCE_LABELS = {"proven", "inferred", "unknown", "blocked"}


@dataclass(frozen=True, slots=True)
class PaaBoneTrackBindingSummary:
    source: str = ""
    table_count: int = 0
    exact_bone_hash_track_count: int = 0
    bound_bone_count: int = 0
    keyframe_count: int = 0
    frame_start: int = 0
    frame_end: int = 0
    frame_rate: float = 30.0
    frame_rate_source: str = "parser_default_30fps"
    frame_rate_confidence: str = "inferred"
    timing_status: str = "default_30fps_unproven"
    quaternion_order: str = "xyzw"
    parser_mode: str = "paa_exact_bone_hash_quaternion_tracks"

    @property
    def ready(self) -> bool:
        return self.exact_bone_hash_track_count > 0 and self.keyframe_count > 0 and self.bound_bone_count > 0


def parse_paa_animation_clip(
    data: bytes,
    filename: str = "",
    *,
    skeleton: object,
    frame_rate: float = 30.0,
    frame_rate_source: str = "",
    frame_rate_confidence: str = "",
    sequence_path: str = "",
    sequence_lane_index: object = -1,
    sequence_lane_source_offset: object = 0,
    sequence_lane_confidence: str = "",
) -> tuple[MeshAnimationClip | None, PaaBoneTrackBindingSummary]:
    """Build a preview clip from PAA tables that are exactly owned by PAB bone hashes."""

    if len(data) < 16 or data[:4] != b"PAR ":
        raise ValueError(f"Not a valid PAA/PAR file: {data[:4]!r}")
    frame_rate, frame_rate_source, frame_rate_confidence, timing_status = _frame_rate_metadata(
        frame_rate,
        frame_rate_source,
        frame_rate_confidence,
    )

    bone_lookup = _bone_hash_lookup(skeleton)
    tables = _binary_sidecar_animation_keyframe_tables(data, sample_limit=len(data), max_tables=512)
    tracks_by_bone: dict[int, list[MeshAnimationKeyframe]] = {}
    names_by_bone: dict[int, str] = {}
    frame_start: int | None = None
    frame_end = 0
    exact_tracks = 0
    keyframe_count = 0

    for table in tables:
        offset = int(table.get("offset") or 0)
        row_count = int(table.get("row_count") or 0)
        if row_count <= 0 or offset < 8:
            continue
        bone_hash = struct.unpack_from("<I", data, offset - 8)[0]
        owner = bone_lookup.get(bone_hash)
        if owner is None:
            continue
        bone_index, bone_name = owner
        keyframes = _read_paa_quaternion_keyframes(data, offset, row_count, frame_rate)
        if not keyframes:
            continue
        exact_tracks += 1
        names_by_bone[bone_index] = bone_name
        tracks_by_bone.setdefault(bone_index, []).extend(keyframes)
        keyframe_count += len(keyframes)
        frame_start = min(frame_start if frame_start is not None else keyframes[0][0], keyframes[0][0])
        frame_end = max(frame_end, keyframes[-1][0])

    tracks: list[MeshAnimationTrack] = []
    for bone_index, rows in sorted(tracks_by_bone.items()):
        deduped: dict[int, MeshAnimationKeyframe] = {}
        for frame, keyframe in rows:
            deduped[frame] = keyframe
        keyframes = tuple(deduped[frame] for frame in sorted(deduped))
        if keyframes:
            tracks.append(
                MeshAnimationTrack(
                    bone_index=bone_index,
                    bone_name=names_by_bone.get(bone_index, ""),
                    rotation_keyframes=keyframes,
                )
            )

    summary = PaaBoneTrackBindingSummary(
        source=filename,
        table_count=len(tables),
        exact_bone_hash_track_count=exact_tracks,
        bound_bone_count=len(tracks),
        keyframe_count=keyframe_count,
        frame_start=int(frame_start or 0),
        frame_end=int(frame_end),
        frame_rate=float(frame_rate),
        frame_rate_source=frame_rate_source,
        frame_rate_confidence=frame_rate_confidence,
        timing_status=timing_status,
    )
    if not tracks:
        return None, summary
    sequence_segments = _sequence_segments_for_binding(
        summary,
        skeleton=skeleton,
        sequence_path=sequence_path,
        sequence_lane_index=sequence_lane_index,
        sequence_lane_source_offset=sequence_lane_source_offset,
        sequence_lane_confidence=sequence_lane_confidence,
    )
    return (
        MeshAnimationClip(
            source=filename,
            duration_seconds=max(0.0, frame_end / frame_rate),
            tracks=tuple(tracks),
            sequence_segments=sequence_segments,
            parser_mode=summary.parser_mode,
            frame_rate=summary.frame_rate,
            timing_confidence=summary.frame_rate_confidence,
            timing_status=summary.timing_status,
        ),
        summary,
    )


def _sequence_segments_for_binding(
    summary: PaaBoneTrackBindingSummary,
    *,
    skeleton: object,
    sequence_path: str,
    sequence_lane_index: object,
    sequence_lane_source_offset: object,
    sequence_lane_confidence: str,
) -> tuple[MeshAnimationSequenceSegment, ...]:
    sequence = str(sequence_path or "").strip()
    if not sequence:
        return ()
    frame_rate = float(summary.frame_rate or 0.0)
    if frame_rate <= 0.0:
        frame_rate = 30.0
    lane_index = _coerce_int(sequence_lane_index, default=-1)
    source_offset = _coerce_int(sequence_lane_source_offset, default=0)
    lane_confidence = _confidence_label(sequence_lane_confidence, default="inferred")
    binding_confidence = "proven" if summary.ready else "blocked"
    timing_confidence = _confidence_label(summary.frame_rate_confidence, default="unknown")
    return (
        MeshAnimationSequenceSegment(
            sequence_path=sequence,
            clip_path=str(summary.source or ""),
            lane_index=lane_index,
            lane_source_offset=max(0, source_offset),
            start_frame=int(summary.frame_start),
            end_frame=int(summary.frame_end),
            start_seconds=max(0.0, float(summary.frame_start) / frame_rate),
            end_seconds=max(0.0, float(summary.frame_end) / frame_rate),
            blend_weight=1.0,
            skeleton_source=str(getattr(skeleton, "path", "") or ""),
            status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
            field_confidence=(
                ("sequence_path", lane_confidence),
                ("clip_path", binding_confidence),
                ("lane_index", lane_confidence if lane_index >= 0 else "unknown"),
                ("lane_source_offset", lane_confidence if source_offset > 0 else "unknown"),
                ("start_frame", "inferred"),
                ("end_frame", "inferred"),
                ("start_seconds", timing_confidence),
                ("end_seconds", timing_confidence),
                ("blend_weight", "unknown"),
                ("skeleton_source", "proven" if getattr(skeleton, "path", "") else "unknown"),
            ),
        ),
    )


def _read_paa_quaternion_keyframes(
    data: bytes,
    offset: int,
    row_count: int,
    frame_rate: float,
) -> list[tuple[int, MeshAnimationKeyframe]]:
    rows: list[tuple[int, MeshAnimationKeyframe]] = []
    for index in range(row_count):
        row_offset = offset + index * 10
        if row_offset + 10 > len(data):
            break
        frame, x, y, z, w = struct.unpack_from("<H4e", data, row_offset)
        rotation = _quaternion_xyzw_to_euler_degrees(float(x), float(y), float(z), float(w))
        if rotation is None:
            continue
        rows.append((int(frame), MeshAnimationKeyframe(time_seconds=float(frame) / frame_rate, rotation_degrees=rotation)))
    rows.sort(key=lambda row: row[0])
    return rows


def _quaternion_xyzw_to_euler_degrees(x: float, y: float, z: float, w: float) -> tuple[float, float, float] | None:
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm <= 1e-6:
        return None
    x /= norm
    y /= norm
    z /= norm
    w /= norm

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


def _bone_hash_lookup(skeleton: object) -> Mapping[int, tuple[int, str]]:
    result: dict[int, tuple[int, str]] = {}
    for bone in tuple(getattr(skeleton, "bones", ()) or ()):
        try:
            bone_hash = int(getattr(bone, "name_hash", 0) or 0)
            bone_index = int(getattr(bone, "index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if bone_hash and bone_index >= 0:
            result[bone_hash] = (bone_index, str(getattr(bone, "name", "") or ""))
    return result


def _frame_rate_metadata(
    frame_rate: object,
    frame_rate_source: object,
    frame_rate_confidence: object,
) -> tuple[float, str, str, str]:
    try:
        value = float(frame_rate)
    except (TypeError, ValueError, OverflowError):
        value = 0.0
    source = str(frame_rate_source or "").strip()
    confidence = str(frame_rate_confidence or "").strip().lower()
    if confidence not in _TIMING_CONFIDENCE_LABELS:
        confidence = "inferred"
    if value <= 0.0 or not math.isfinite(value):
        source = source or "parser_default_30fps"
        return 30.0, source, "blocked", "invalid_frame_rate_defaulted_to_30fps"
    source = source or ("parser_default_30fps" if math.isclose(value, 30.0) else "caller_frame_rate")
    if confidence == "proven":
        status = "game_sequence_fps_proven"
    elif source == "parser_default_30fps":
        status = "default_30fps_unproven"
    else:
        status = "frame_rate_unproven"
    return value, source, confidence, status


def _confidence_label(value: object, *, default: str) -> str:
    label = str(value or "").strip().lower()
    return label if label in _TIMING_CONFIDENCE_LABELS else default


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


__all__ = [
    "PaaBoneTrackBindingSummary",
    "parse_paa_animation_clip",
]
