"""Pure Mesh Editor skinning summary helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .editing import MeshEditSelection

_TIMING_CONFIDENCE_LABELS = {"proven", "inferred", "unknown", "blocked"}


@dataclass(frozen=True, slots=True)
class MeshSkeletonBoneSummary:
    index: int
    name: str
    parent_index: int = -1
    parent_name: str = ""
    child_count: int = 0
    depth: int = 0
    position: tuple[float, float, float] = ()

    @property
    def position_text(self) -> str:
        if len(self.position) < 3:
            return ""
        return f"{self.position[0]:.3f}, {self.position[1]:.3f}, {self.position[2]:.3f}"


@dataclass(frozen=True, slots=True)
class MeshSkeletonPoseSummary:
    enabled: bool = False
    selected_bone_index: int = -1
    selected_bone_name: str = ""
    rotation_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotations: tuple[tuple[int, tuple[float, float, float]], ...] = ()
    posed_bone_count: int = 0

    @property
    def rotation_text(self) -> str:
        x, y, z = self.rotation_degrees
        return f"{x:.1f}, {y:.1f}, {z:.1f}"


@dataclass(frozen=True, slots=True)
class MeshAnimationKeyframe:
    time_seconds: float
    rotation_degrees: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class MeshAnimationTrack:
    bone_index: int = -1
    bone_name: str = ""
    rotation_keyframes: tuple[MeshAnimationKeyframe, ...] = ()


@dataclass(frozen=True, slots=True)
class MeshAnimationSequenceSegment:
    sequence_path: str = ""
    clip_path: str = ""
    lane_index: int = -1
    lane_source_offset: int = 0
    start_frame: int = 0
    end_frame: int = 0
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    blend_weight: float = 1.0
    skeleton_source: str = ""
    status: str = "sequence_semantics_unproven"
    field_confidence: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MeshAnimationClip:
    source: str = ""
    duration_seconds: float = 0.0
    tracks: tuple[MeshAnimationTrack, ...] = ()
    sequence_segments: tuple[MeshAnimationSequenceSegment, ...] = ()
    parser_mode: str = "safe_parsed"
    frame_rate: float = 0.0
    timing_confidence: str = "unknown"
    timing_status: str = "timing_unproven"

    @property
    def game_accurate_timing(self) -> bool:
        return str(self.timing_confidence or "").strip().lower() == "proven" and self.frame_rate > 0.0


@dataclass(frozen=True, slots=True)
class MeshAnimationPlaybackSummary:
    ready: bool = False
    enabled: bool = False
    source: str = ""
    parser_mode: str = ""
    time_seconds: float = 0.0
    duration_seconds: float = 0.0
    loop: bool = True
    playback_speed: float = 1.0
    track_count: int = 0
    sequence_segment_count: int = 0
    active_sequence_lane_index: int = -1
    active_sequence_path: str = ""
    active_sequence_clip_path: str = ""
    active_sequence_status: str = ""
    active_sequence_field_confidence: tuple[tuple[str, str], ...] = ()
    sampled_bone_count: int = 0
    frame_rate: float = 0.0
    timing_confidence: str = "unknown"
    timing_status: str = "timing_unproven"
    game_accurate_timing: bool = False
    status: str = ""
    blockers: tuple[str, ...] = ()

    @property
    def time_text(self) -> str:
        return f"{self.time_seconds:.3f}/{self.duration_seconds:.3f}s"


@dataclass(frozen=True, slots=True)
class MeshAuthoringStatusRow:
    feature: str
    state: str
    confidence: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MeshConstraintRecordCandidateSummary:
    offset: int = 0
    constraint_type: str = ""
    target_bone: str = ""
    target_bone_index: int = -1
    target_bone_confidence: str = "unmatched"
    helper_bone: str = ""
    helper_bone_index: int = -1
    helper_bone_confidence: str = "unmatched"
    parent_bone: str = ""
    parent_bone_index: int = -1
    parent_bone_confidence: str = "unmatched"
    expression: str = ""
    expression_offset: int = 0
    target_bone_offset: int = 0
    target_bone_delta: int = 0
    helper_bone_offset: int = 0
    helper_bone_delta: int = 0
    parent_bone_offset: int = 0
    parent_bone_delta: int = 0
    expression_channels: tuple[str, ...] = ()
    limit_operators: tuple[str, ...] = ()
    expression_numeric_values: tuple[str, ...] = ()
    field_confidence: str = ""
    field_offset_confidence: str = ""
    expression_channel_confidence: str = ""
    limit_operator_confidence: str = ""
    expression_numeric_value_confidence: str = ""
    expression_numeric_roles: tuple[str, ...] = ()
    expression_numeric_role_confidence: str = ""
    expression_shape: str = ""
    expression_syntax_signature: str = ""
    expression_shape_confidence: str = ""
    expression_shape_status: str = ""
    expression_semantics_confidence: str = ""
    record_confidence: str = ""
    record_span_start: int = 0
    record_span_end: int = 0
    record_span_size: int = 0
    record_span_field_count: int = 0
    record_field_sequence: tuple[str, ...] = ()
    record_field_sequence_confidence: str = ""
    record_gap_status: str = ""
    record_gap_classes: tuple[str, ...] = ()
    record_gap_class_counts: tuple[tuple[str, int], ...] = ()
    record_gap_count: int = 0
    record_gap_total_size: int = 0
    record_gap_max_size: int = 0
    record_gap_confidence: str = ""
    record_gap_scalar_status: str = ""
    record_gap_scalar_kind_counts: tuple[tuple[str, int], ...] = ()
    record_gap_aligned_word_count: int = 0
    record_gap_scalar_candidate_count: int = 0
    record_gap_scalar_confidence: str = ""
    record_gap_numeric_match_status: str = ""
    record_gap_numeric_match_role_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_scalar_kind_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_storage_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_pair_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_value_confidence_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_signature_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_candidate_relative_signature_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_previous_delta_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_next_delta_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_candidate_relative_offset_counts: tuple[tuple[str, int], ...] = ()
    record_gap_numeric_match_count: int = 0
    record_gap_numeric_match_min_previous_delta: int = 0
    record_gap_numeric_match_max_previous_delta: int = 0
    record_gap_numeric_match_min_next_delta: int = 0
    record_gap_numeric_match_max_next_delta: int = 0
    record_gap_numeric_match_min_candidate_relative_offset: int = 0
    record_gap_numeric_match_max_candidate_relative_offset: int = 0
    record_gap_numeric_match_offset_confidence: str = ""
    record_gap_numeric_match_candidate_relative_offset_confidence: str = ""
    record_gap_numeric_match_confidence: str = ""
    record_layout_status: str = ""
    solver_status: str = ""

    @property
    def offset_text(self) -> str:
        return f"0x{self.offset:X}" if self.offset > 0 else "offset unknown"


@dataclass(frozen=True, slots=True)
class MeshConstraintEvidenceSummary:
    status: str = ""
    string_evidence_count: int = 0
    record_candidate_count: int = 0
    related_physics_count: int = 0
    role_counts: tuple[tuple[str, int], ...] = ()
    record_candidates: tuple[MeshConstraintRecordCandidateSummary, ...] = ()
    candidate_family_counts: tuple[tuple[str, int], ...] = ()
    family_readiness_rows: tuple[tuple[str, str, tuple[tuple[str, int], ...]], ...] = ()
    bone_match_candidate_count: int = 0
    bone_match_counts: tuple[tuple[str, int], ...] = ()
    expression_status: str = ""
    expression_token_confidence: str = ""
    expression_semantics_confidence: str = ""
    expression_counts: tuple[tuple[str, int], ...] = ()
    expression_syntax_signature_counts: tuple[tuple[str, int], ...] = ()
    expression_numeric_value_count: int = 0
    field_offset_status: str = ""
    field_offset_confidence: str = ""
    field_offset_record_confidence: str = ""
    field_offset_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_count: int = 0
    numeric_match_status_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_role_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_storage_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_pair_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_value_confidence_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_family_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_family_row_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_family_role_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()
    numeric_match_family_pair_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()
    numeric_match_family_value_confidence_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()
    numeric_match_signature_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_candidate_relative_signature_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_previous_delta_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_next_delta_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_candidate_relative_offset_counts: tuple[tuple[str, int], ...] = ()
    numeric_match_min_previous_delta: int = 0
    numeric_match_max_previous_delta: int = 0
    numeric_match_min_next_delta: int = 0
    numeric_match_max_next_delta: int = 0
    numeric_match_min_candidate_relative_offset: int = 0
    numeric_match_max_candidate_relative_offset: int = 0
    numeric_match_offset_confidence: str = ""
    numeric_match_candidate_relative_offset_confidence: str = ""
    solver_readiness_status: str = ""
    solver_readiness_counts: tuple[tuple[str, int], ...] = ()
    solver_supported: bool = False
    proof_gap: str = ""

    @property
    def recognized(self) -> bool:
        return bool(
            self.status
            or self.string_evidence_count
            or self.record_candidate_count
            or self.related_physics_count
            or self.role_counts
            or self.record_candidates
            or self.candidate_family_counts
            or self.family_readiness_rows
            or self.bone_match_candidate_count
            or self.bone_match_counts
            or self.expression_status
            or self.expression_counts
            or self.expression_syntax_signature_counts
            or self.expression_numeric_value_count
            or self.field_offset_status
            or self.field_offset_counts
            or self.numeric_match_count
            or self.numeric_match_status_counts
            or self.numeric_match_role_counts
            or self.numeric_match_storage_counts
            or self.numeric_match_pair_counts
            or self.numeric_match_value_confidence_counts
            or self.numeric_match_family_counts
            or self.numeric_match_family_row_counts
            or self.numeric_match_family_role_counts
            or self.numeric_match_family_pair_counts
            or self.numeric_match_family_value_confidence_counts
            or self.numeric_match_signature_counts
            or self.numeric_match_candidate_relative_signature_counts
            or self.numeric_match_previous_delta_counts
            or self.numeric_match_next_delta_counts
            or self.numeric_match_candidate_relative_offset_counts
            or self.solver_readiness_status
            or self.solver_readiness_counts
        )


@dataclass(frozen=True, slots=True)
class MeshVertexWeightSummary:
    submesh_index: int
    vertex_index: int
    influences: tuple[tuple[int, float], ...] = ()
    selected_bone_weight: float = 0.0
    total_weight: float = 0.0
    invalid: bool = False

    @property
    def influences_text(self) -> str:
        if not self.influences:
            return "no weights"
        return ", ".join(f"{bone}:{weight:.3f}" for bone, weight in self.influences)


@dataclass(frozen=True, slots=True)
class MeshSkinningPartSummary:
    index: int
    name: str
    vertex_count: int
    skinned: bool = False
    weighted_vertex_count: int = 0
    unweighted_vertex_count: int = 0
    max_influences: int = 0
    max_bone_index: int = -1
    unique_bone_indices: tuple[int, ...] = ()
    invalid_row_count: int = 0
    unnormalized_vertex_count: int = 0
    selected: bool = False

    @property
    def bone_count(self) -> int:
        return len(self.unique_bone_indices)


@dataclass(frozen=True, slots=True)
class MeshSkeletonSummary:
    skinned: bool
    part_count: int
    vertex_count: int
    weighted_part_count: int = 0
    weighted_vertex_count: int = 0
    max_bone_index: int = -1
    inferred_bone_count: int = 0
    skeleton_bone_count: int | None = None
    skeleton_source: str = ""
    skeleton_descriptor_source: str = ""
    skeleton_variation_source: str = ""
    skeleton_variation_status: str = ""
    animation_constraint_source: str = ""
    animation_constraint_status: str = ""
    animation_constraint_evidence: MeshConstraintEvidenceSummary = MeshConstraintEvidenceSummary()
    socket_source: str = ""
    animation_status: str = ""
    animation_playback_ready: bool = False
    animation_blockers: tuple[str, ...] = ()
    animation_playback: MeshAnimationPlaybackSummary = MeshAnimationPlaybackSummary()
    authoring_status_rows: tuple[MeshAuthoringStatusRow, ...] = ()
    skeleton_parser_mode: str = ""
    skeleton_parse_warning: str = ""
    root_bone_count: int = 0
    max_depth: int = 0
    invalid_row_count: int = 0
    unnormalized_vertex_count: int = 0
    pose: MeshSkeletonPoseSummary = MeshSkeletonPoseSummary()
    selected_vertex_weights: tuple[MeshVertexWeightSummary, ...] = ()
    bones: tuple[MeshSkeletonBoneSummary, ...] = ()
    parts: tuple[MeshSkinningPartSummary, ...] = ()

    @property
    def skeleton_linked(self) -> bool:
        return self.skeleton_bone_count is not None or bool(self.skeleton_source)


def summarize_mesh_skinning(
    mesh: object,
    selection: MeshEditSelection | None = None,
    *,
    skeleton: object | None = None,
    skeleton_bone_count: int | None = None,
    skeleton_source: str = "",
    skeleton_descriptor_source: str = "",
    skeleton_variation_source: str = "",
    animation_constraint_source: str = "",
    animation_constraint_evidence: Mapping[str, object] | None = None,
    socket_source: str = "",
    pose_enabled: bool = False,
    selected_bone_index: int = -1,
    pose_rotations: dict[int, tuple[float, float, float]] | None = None,
    animation_clip: MeshAnimationClip | None = None,
    animation_enabled: bool = False,
    animation_time_seconds: float = 0.0,
    animation_loop: bool = True,
    animation_speed: float = 1.0,
) -> MeshSkeletonSummary:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    selected_sources = set(selection.source_indices if selection is not None else ())
    bones = summarize_skeleton_bones(skeleton) if skeleton is not None else ()
    if skeleton is not None:
        skeleton_source = str(skeleton_source or getattr(skeleton, "path", "") or "")
        skeleton_bone_count = len(bones) if skeleton_bone_count is None else skeleton_bone_count
    parts = tuple(
        _part_summary(
            index,
            submesh,
            selected=index in selected_sources,
            skeleton_bone_count=skeleton_bone_count,
        )
        for index, submesh in enumerate(submeshes)
    )
    max_bone_index = max((part.max_bone_index for part in parts), default=-1)
    skinned = any(part.skinned for part in parts)
    animation_playback = summarize_mesh_animation_playback(
        bones,
        animation_clip,
        enabled=animation_enabled,
        time_seconds=animation_time_seconds,
        loop=animation_loop,
        playback_speed=animation_speed,
    )
    metadata_status = _animation_status(skeleton_variation_source, animation_constraint_source)
    metadata_blockers = _animation_blockers(skeleton_variation_source, animation_constraint_source)
    constraint_evidence = _constraint_evidence_summary(animation_constraint_evidence, bones=bones)
    invalid_row_count = sum(part.invalid_row_count for part in parts)
    unnormalized_vertex_count = sum(part.unnormalized_vertex_count for part in parts)
    return MeshSkeletonSummary(
        skinned=skinned,
        part_count=len(parts),
        vertex_count=sum(part.vertex_count for part in parts),
        weighted_part_count=sum(1 for part in parts if part.skinned),
        weighted_vertex_count=sum(part.weighted_vertex_count for part in parts),
        max_bone_index=max_bone_index,
        inferred_bone_count=max_bone_index + 1 if max_bone_index >= 0 else 0,
        skeleton_bone_count=skeleton_bone_count,
        skeleton_source=str(skeleton_source or ""),
        skeleton_descriptor_source=str(skeleton_descriptor_source or ""),
        skeleton_variation_source=str(skeleton_variation_source or ""),
        skeleton_variation_status=_variation_status(skeleton_variation_source),
        animation_constraint_source=str(animation_constraint_source or ""),
        animation_constraint_status=_constraint_status(animation_constraint_source),
        animation_constraint_evidence=constraint_evidence,
        socket_source=str(socket_source or ""),
        animation_status=animation_playback.status or metadata_status,
        animation_playback_ready=animation_playback.ready,
        animation_blockers=animation_playback.blockers or metadata_blockers,
        animation_playback=animation_playback,
        authoring_status_rows=_authoring_status_rows(
            skinned=skinned,
            skeleton_linked=skeleton is not None or bool(skeleton_source),
            invalid_row_count=invalid_row_count,
            animation_playback=animation_playback,
            skeleton_variation_source=skeleton_variation_source,
            animation_constraint_source=animation_constraint_source,
        ),
        skeleton_parser_mode=str(getattr(skeleton, "parser_mode", "") or "") if skeleton is not None else "",
        skeleton_parse_warning=str(getattr(skeleton, "parse_warning", "") or "") if skeleton is not None else "",
        root_bone_count=sum(1 for bone in bones if bone.parent_index < 0),
        max_depth=max((bone.depth for bone in bones), default=0),
        invalid_row_count=invalid_row_count,
        unnormalized_vertex_count=unnormalized_vertex_count,
        pose=_pose_summary(bones, pose_enabled, selected_bone_index, pose_rotations),
        selected_vertex_weights=_selected_vertex_weights(submeshes, selection, selected_bone_index),
        bones=bones,
        parts=parts,
    )


def summarize_skeleton_bones(skeleton: object | None) -> tuple[MeshSkeletonBoneSummary, ...]:
    raw_bones = tuple(getattr(skeleton, "bones", ()) or ()) if skeleton is not None else ()
    if not raw_bones:
        return ()
    by_index: dict[int, object] = {}
    for ordinal, bone in enumerate(raw_bones):
        bone_index = _coerce_index(getattr(bone, "index", ordinal))
        if bone_index is None or bone_index < 0:
            bone_index = ordinal
        by_index[bone_index] = bone
    children_by_parent: dict[int, int] = {}
    for bone in by_index.values():
        parent_index = _coerce_index(getattr(bone, "parent_index", -1))
        if parent_index is not None and parent_index >= 0:
            children_by_parent[parent_index] = children_by_parent.get(parent_index, 0) + 1

    def depth_for(index: int, seen: set[int] | None = None) -> int:
        if seen is None:
            seen = set()
        if index in seen:
            return 0
        seen.add(index)
        parent_index = _coerce_index(getattr(by_index.get(index), "parent_index", -1))
        if parent_index is None or parent_index < 0 or parent_index not in by_index:
            return 0
        return 1 + depth_for(parent_index, seen)

    summaries: list[MeshSkeletonBoneSummary] = []
    for index in sorted(by_index):
        bone = by_index[index]
        parent_index = _coerce_index(getattr(bone, "parent_index", -1))
        if parent_index is None or parent_index not in by_index:
            parent_index = -1
        parent = by_index.get(parent_index)
        summaries.append(
            MeshSkeletonBoneSummary(
                index=index,
                name=str(getattr(bone, "name", "") or f"bone_{index}"),
                parent_index=parent_index,
                parent_name=str(getattr(parent, "name", "") or "") if parent is not None else "",
                child_count=children_by_parent.get(index, 0),
                depth=depth_for(index),
                position=_vec3(getattr(bone, "position", ())),
            )
        )
    return tuple(summaries)


def summarize_mesh_animation_playback(
    bones: tuple[MeshSkeletonBoneSummary, ...],
    clip: MeshAnimationClip | None,
    *,
    enabled: bool,
    time_seconds: float,
    loop: bool,
    playback_speed: float = 1.0,
) -> MeshAnimationPlaybackSummary:
    if clip is None:
        return MeshAnimationPlaybackSummary()
    blockers = _animation_clip_blockers(bones, clip)
    duration = _animation_clip_duration(clip)
    frame_rate, timing_confidence, timing_status, game_accurate_timing = _animation_clip_timing(clip)
    playback_time = _animation_time(time_seconds, duration, loop=loop)
    active_segment = _active_sequence_segment(clip, playback_time)
    active_lane_index, active_sequence_path, active_clip_path, active_segment_status, active_field_confidence = (
        _sequence_segment_diagnostics(active_segment)
    )
    if blockers:
        return MeshAnimationPlaybackSummary(
            ready=False,
            enabled=False,
            source=str(clip.source or ""),
            parser_mode=str(clip.parser_mode or ""),
            time_seconds=playback_time,
            duration_seconds=duration,
            loop=bool(loop),
            playback_speed=_animation_speed(playback_speed),
            track_count=len(tuple(clip.tracks or ())),
            sequence_segment_count=len(tuple(clip.sequence_segments or ())),
            active_sequence_lane_index=active_lane_index,
            active_sequence_path=active_sequence_path,
            active_sequence_clip_path=active_clip_path,
            active_sequence_status=active_segment_status,
            active_sequence_field_confidence=active_field_confidence,
            frame_rate=frame_rate,
            timing_confidence=timing_confidence,
            timing_status=timing_status,
            game_accurate_timing=game_accurate_timing,
            status="playback_blocked",
            blockers=blockers,
        )
    sampled = sample_mesh_animation_pose(bones, clip, time_seconds, loop=loop)
    return MeshAnimationPlaybackSummary(
        ready=True,
        enabled=bool(enabled),
        source=str(clip.source or ""),
        parser_mode=str(clip.parser_mode or ""),
        time_seconds=playback_time,
        duration_seconds=duration,
        loop=bool(loop),
        playback_speed=_animation_speed(playback_speed),
        track_count=len(tuple(clip.tracks or ())),
        sequence_segment_count=len(tuple(clip.sequence_segments or ())),
        active_sequence_lane_index=active_lane_index,
        active_sequence_path=active_sequence_path,
        active_sequence_clip_path=active_clip_path,
        active_sequence_status=active_segment_status,
        active_sequence_field_confidence=active_field_confidence,
        sampled_bone_count=len(sampled),
        frame_rate=frame_rate,
        timing_confidence=timing_confidence,
        timing_status=timing_status,
        game_accurate_timing=game_accurate_timing,
        status="playback_ready",
        blockers=(),
    )


def sample_mesh_animation_pose(
    bones: tuple[MeshSkeletonBoneSummary, ...],
    clip: MeshAnimationClip | None,
    time_seconds: object,
    *,
    loop: bool = True,
) -> dict[int, tuple[float, float, float]]:
    if clip is None:
        return {}
    duration = _animation_clip_duration(clip)
    time_value = _animation_time(time_seconds, duration, loop=loop)
    by_index = {bone.index: bone for bone in bones}
    by_name = {bone.name.strip().lower(): bone.index for bone in bones if bone.name.strip()}
    sampled: dict[int, tuple[float, float, float]] = {}
    for track in tuple(clip.tracks or ()):
        bone_index = _track_bone_index(track, by_index, by_name)
        if bone_index is None:
            continue
        keyframes = _valid_rotation_keyframes(track.rotation_keyframes)
        if not keyframes:
            continue
        sampled[bone_index] = _sample_rotation_keyframes(keyframes, time_value)
    return sampled


def mesh_animation_clip_from_document(
    document: Mapping[str, object],
    *,
    source: str = "",
) -> MeshAnimationClip | None:
    """Build a playable clip only from explicit decoded bone-track documents."""
    if not isinstance(document, Mapping):
        return None
    animation = document.get("animation")
    if not isinstance(animation, Mapping):
        return None
    raw_tracks = _first_sequence(animation, ("bone_tracks", "tracks"))
    if not raw_tracks:
        return None
    frame_rate = _document_frame_rate(document, animation)
    tracks = tuple(
        track
        for raw_track in raw_tracks
        if (track := _mesh_animation_track_from_document(raw_track, frame_rate=frame_rate)) is not None
    )
    if not tracks:
        return None
    return MeshAnimationClip(
        source=str(source or _document_source(document) or ""),
        duration_seconds=_document_duration_seconds(document, animation, tracks),
        tracks=tracks,
        parser_mode=str(animation.get("parser_mode") or document.get("parser_mode") or "explicit_bone_tracks"),
        frame_rate=frame_rate,
        timing_confidence=_document_timing_confidence(document, animation, frame_rate),
        timing_status=_document_timing_status(document, animation, frame_rate),
    )


def _mesh_animation_track_from_document(raw_track: object, *, frame_rate: float) -> MeshAnimationTrack | None:
    if not isinstance(raw_track, Mapping):
        return None
    bone_index = _coerce_index(_first_value(raw_track, ("bone_index", "index")))
    if bone_index is None or bone_index < 0:
        bone_index = -1
    bone_name = str(_first_value(raw_track, ("bone_name", "name", "target_bone")) or "").strip()
    if bone_index < 0 and not bone_name:
        return None
    raw_keyframes = _first_sequence(raw_track, ("rotation_keyframes", "rotations", "keyframes"))
    keyframes = tuple(
        keyframe
        for raw_keyframe in raw_keyframes
        if (keyframe := _mesh_animation_keyframe_from_document(raw_keyframe, frame_rate=frame_rate)) is not None
    )
    keyframes = _valid_rotation_keyframes(keyframes)
    if not keyframes:
        return None
    return MeshAnimationTrack(bone_index=bone_index, bone_name=bone_name, rotation_keyframes=keyframes)


def _mesh_animation_keyframe_from_document(raw_keyframe: object, *, frame_rate: float) -> MeshAnimationKeyframe | None:
    if not isinstance(raw_keyframe, Mapping):
        return None
    time_value = _coerce_float(_first_value(raw_keyframe, ("time_seconds", "seconds", "time", "t")))
    if time_value is None:
        frame_value = _coerce_float(_first_value(raw_keyframe, ("frame", "frame_index")))
        if frame_value is not None and frame_rate > 0.0:
            time_value = frame_value / frame_rate
    rotation = _vec3(_first_value(raw_keyframe, ("rotation_degrees", "euler_degrees", "degrees")))
    if time_value is None or time_value < 0.0 or not rotation:
        return None
    return MeshAnimationKeyframe(time_seconds=time_value, rotation_degrees=rotation)


def _document_frame_rate(document: Mapping[str, object], animation: Mapping[str, object]) -> float:
    summary = document.get("summary")
    containers = (animation, summary, document)
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in ("frame_rate", "fps", "frames_per_second"):
            value = _coerce_float(container.get(key))
            if value is not None and value > 0.0:
                return value
    return 0.0


def _document_timing_confidence(
    document: Mapping[str, object],
    animation: Mapping[str, object],
    frame_rate: float,
) -> str:
    summary = document.get("summary")
    for container in (animation, summary, document):
        if not isinstance(container, Mapping):
            continue
        for key in ("timing_confidence", "frame_rate_confidence", "fps_confidence"):
            value = str(container.get(key) or "").strip().lower()
            if value in _TIMING_CONFIDENCE_LABELS:
                return value
    return "inferred" if frame_rate > 0.0 else "unknown"


def _document_timing_status(
    document: Mapping[str, object],
    animation: Mapping[str, object],
    frame_rate: float,
) -> str:
    summary = document.get("summary")
    for container in (animation, summary, document):
        if not isinstance(container, Mapping):
            continue
        value = str(container.get("timing_status") or "").strip()
        if value:
            return value
    if frame_rate <= 0.0:
        return "timing_unproven"
    confidence = _document_timing_confidence(document, animation, frame_rate)
    return "document_frame_rate_proven" if confidence == "proven" else "document_frame_rate_unproven"


def _document_duration_seconds(
    document: Mapping[str, object],
    animation: Mapping[str, object],
    tracks: tuple[MeshAnimationTrack, ...],
) -> float:
    summary = document.get("summary")
    duration = 0.0
    for container in (animation, summary, document):
        if not isinstance(container, Mapping):
            continue
        for key in ("duration_seconds", "length_seconds", "duration"):
            value = _coerce_float(container.get(key))
            if value is not None and value >= 0.0:
                duration = max(duration, value)
    for track in tracks:
        keyframes = _valid_rotation_keyframes(track.rotation_keyframes)
        if keyframes:
            duration = max(duration, keyframes[-1].time_seconds)
    return duration


def _document_source(document: Mapping[str, object]) -> str:
    source = document.get("source")
    if isinstance(source, Mapping):
        for key in ("path", "virtual_path", "label", "name"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    for key in ("path", "virtual_path", "source"):
        value = document.get(key)
        if not isinstance(value, Mapping):
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _first_value(mapping: Mapping[str, object], keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _first_sequence(mapping: Mapping[str, object], keys: tuple[str, ...]) -> tuple[object, ...]:
    for key in keys:
        value = mapping.get(key)
        if value is None or isinstance(value, (str, bytes, Mapping)):
            continue
        try:
            items = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            continue
        if items:
            return items
    return ()


def _has_nonempty_bone_rows(*row_sets: tuple[object, ...]) -> bool:
    return any(_row_tuple(row) for rows in row_sets for row in rows)


def _part_summary(
    index: int,
    submesh: object,
    *,
    selected: bool,
    skeleton_bone_count: int | None,
) -> MeshSkinningPartSummary:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    skinned = _has_nonempty_bone_rows(bone_indices, bone_weights)
    if not skinned:
        return MeshSkinningPartSummary(
            index=index,
            name=str(getattr(submesh, "name", "") or f"part_{index}"),
            vertex_count=len(vertices),
            selected=bool(selected),
        )

    weighted_vertices = 0
    invalid_rows = 0
    unnormalized_vertices = 0
    max_influences = 0
    bones: set[int] = set()
    row_count = max(len(vertices), len(bone_indices), len(bone_weights))
    for vertex_index in range(row_count):
        if vertex_index >= len(vertices) or vertex_index >= len(bone_indices) or vertex_index >= len(bone_weights):
            invalid_rows += 1
            continue
        index_row = _row_tuple(bone_indices[vertex_index])
        weight_row = _row_tuple(bone_weights[vertex_index])
        row_invalid = len(index_row) != len(weight_row) or len(index_row) > 4
        max_influences = max(max_influences, len(index_row), len(weight_row))
        clean_weights: list[float] = []
        has_weight = False
        for raw_index, raw_weight in zip(index_row, weight_row):
            bone_index = _coerce_index(raw_index)
            weight = _coerce_float(raw_weight)
            if bone_index is None or bone_index < 0:
                row_invalid = True
            else:
                bones.add(bone_index)
                if skeleton_bone_count is not None and bone_index >= skeleton_bone_count:
                    row_invalid = True
            if weight is None or weight < 0.0:
                row_invalid = True
                continue
            clean_weights.append(weight)
            if weight > 0.0 and bone_index is not None and bone_index >= 0:
                has_weight = True
        if has_weight:
            weighted_vertices += 1
        total = sum(clean_weights)
        if clean_weights and not math.isclose(total, 1.0, rel_tol=0.02, abs_tol=0.02):
            unnormalized_vertices += 1
        if row_invalid:
            invalid_rows += 1

    max_bone_index = max(bones, default=-1)
    vertex_count = len(vertices)
    return MeshSkinningPartSummary(
        index=index,
        name=str(getattr(submesh, "name", "") or f"part_{index}"),
        vertex_count=vertex_count,
        skinned=True,
        weighted_vertex_count=weighted_vertices,
        unweighted_vertex_count=max(0, vertex_count - weighted_vertices),
        max_influences=max_influences,
        max_bone_index=max_bone_index,
        unique_bone_indices=tuple(sorted(bones)),
        invalid_row_count=invalid_rows,
        unnormalized_vertex_count=unnormalized_vertices,
        selected=bool(selected),
    )


def _row_tuple(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _vec3(value: object) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return ()
    values = tuple(_coerce_float(component) for component in value[:3])
    if any(component is None for component in values):
        return ()
    return values  # type: ignore[return-value]


def _pose_summary(
    bones: tuple[MeshSkeletonBoneSummary, ...],
    enabled: bool,
    selected_bone_index: int,
    pose_rotations: dict[int, tuple[float, float, float]] | None,
) -> MeshSkeletonPoseSummary:
    by_index = {bone.index: bone for bone in bones}
    selected = selected_bone_index if selected_bone_index in by_index else -1
    rotations = pose_rotations or {}
    rotation = _vec3(rotations.get(selected, (0.0, 0.0, 0.0))) if selected >= 0 else (0.0, 0.0, 0.0)
    valid_rotations = tuple(
        (index, value)
        for index, raw_value in sorted(rotations.items())
        if index in by_index
        if (value := _vec3(raw_value)) != (0.0, 0.0, 0.0)
    )
    return MeshSkeletonPoseSummary(
        enabled=bool(enabled),
        selected_bone_index=selected,
        selected_bone_name=by_index[selected].name if selected >= 0 else "",
        rotation_degrees=rotation or (0.0, 0.0, 0.0),
        rotations=valid_rotations,
        posed_bone_count=len(valid_rotations),
    )


def _selected_vertex_weights(
    submeshes: tuple[object, ...],
    selection: MeshEditSelection | None,
    selected_bone_index: int,
) -> tuple[MeshVertexWeightSummary, ...]:
    if selection is None:
        return ()
    result: list[MeshVertexWeightSummary] = []
    for submesh_index, vertex_indices in sorted(selection.vertex_map().items()):
        if not 0 <= submesh_index < len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        vertex_count = len(tuple(getattr(submesh, "vertices", ()) or ()))
        for vertex_index in sorted(vertex_indices):
            if vertex_index < 0 or vertex_index >= vertex_count:
                continue
            index_row = _row_tuple(bone_indices[vertex_index]) if vertex_index < len(bone_indices) else ()
            weight_row = _row_tuple(bone_weights[vertex_index]) if vertex_index < len(bone_weights) else ()
            influences: list[tuple[int, float]] = []
            invalid = len(index_row) != len(weight_row) or len(index_row) > 4
            for raw_index, raw_weight in zip(index_row, weight_row):
                bone_index = _coerce_index(raw_index)
                weight = _coerce_float(raw_weight)
                if bone_index is None or bone_index < 0 or weight is None or weight < 0.0:
                    invalid = True
                    continue
                influences.append((bone_index, weight))
            total = sum(weight for _bone, weight in influences)
            result.append(
                MeshVertexWeightSummary(
                    submesh_index=submesh_index,
                    vertex_index=vertex_index,
                    influences=tuple(influences),
                    selected_bone_weight=sum(weight for bone, weight in influences if bone == selected_bone_index),
                    total_weight=total,
                    invalid=invalid or (bool(influences) and not math.isclose(total, 1.0, rel_tol=0.02, abs_tol=0.02)),
                )
            )
    return tuple(result)


def _animation_status(skeleton_variation_source: str, animation_constraint_source: str) -> str:
    if animation_constraint_source:
        return "constraint_metadata_only"
    if skeleton_variation_source:
        return "variation_metadata_only"
    return ""


def _variation_status(skeleton_variation_source: str) -> str:
    if skeleton_variation_source:
        return "linked_read_only_hash_records"
    return ""


def _constraint_status(animation_constraint_source: str) -> str:
    if animation_constraint_source:
        return "linked_read_only_par_metadata_solver_blocked"
    return ""


def _constraint_evidence_summary(
    evidence: Mapping[str, object] | None,
    *,
    bones: tuple[MeshSkeletonBoneSummary, ...] = (),
) -> MeshConstraintEvidenceSummary:
    if not isinstance(evidence, Mapping):
        return MeshConstraintEvidenceSummary()
    role_counts = evidence.get("role_counts")
    if not isinstance(role_counts, Mapping):
        role_counts = evidence.get("constraint_role_counts")
    related_rows = evidence.get("related_physics_rows")
    related_count = len(related_rows) if isinstance(related_rows, tuple | list) else _int(evidence.get("constraint_related_physics"))
    counts: list[tuple[str, int]] = []
    if isinstance(role_counts, Mapping):
        for name, count in role_counts.items():
            value = _int(count)
            if value > 0:
                counts.append((str(name), value))
    counts.sort(key=lambda row: (-row[1], row[0]))
    all_record_candidates = _constraint_record_candidate_rows(evidence, bones=bones, max_rows=None)
    record_candidates = all_record_candidates[:6]
    (
        expression_status,
        expression_token_confidence,
        expression_semantics_confidence,
        expression_counts,
        expression_syntax_signature_counts,
        expression_numeric_value_count,
    ) = (
        _constraint_expression_evidence_summary(evidence)
    )
    field_offset_status, field_offset_confidence, field_offset_record_confidence, field_offset_counts = _constraint_field_offset_summary(evidence)
    (
        numeric_match_count,
        numeric_match_status_counts,
        numeric_match_role_counts,
        numeric_match_storage_counts,
        numeric_match_pair_counts,
        numeric_match_value_confidence_counts,
        numeric_match_family_counts,
        numeric_match_family_row_counts,
        numeric_match_family_role_counts,
        numeric_match_family_pair_counts,
        numeric_match_family_value_confidence_counts,
        numeric_match_signature_counts,
        numeric_match_candidate_relative_signature_counts,
        numeric_match_previous_delta_counts,
        numeric_match_next_delta_counts,
        numeric_match_candidate_relative_offset_counts,
        numeric_match_min_previous_delta,
        numeric_match_max_previous_delta,
        numeric_match_min_next_delta,
        numeric_match_max_next_delta,
        numeric_match_min_candidate_relative_offset,
        numeric_match_max_candidate_relative_offset,
        numeric_match_offset_confidence,
        numeric_match_candidate_relative_offset_confidence,
    ) = _constraint_numeric_match_summary(
        evidence,
        all_record_candidates,
    )
    solver_supported = bool(evidence.get("constraint_solving_supported"))
    solver_readiness_status, solver_readiness_counts = _constraint_solver_readiness_summary(
        all_record_candidates,
        expression_counts,
        solver_supported=solver_supported,
    )
    return MeshConstraintEvidenceSummary(
        status=str(evidence.get("constraint_evidence_status") or evidence.get("status") or ""),
        string_evidence_count=_int(evidence.get("string_evidence_count") or evidence.get("constraint_string_evidence")),
        record_candidate_count=_int(evidence.get("record_candidate_count") or evidence.get("constraint_record_candidates")),
        related_physics_count=related_count,
        role_counts=tuple(counts),
        record_candidates=record_candidates,
        candidate_family_counts=_constraint_candidate_family_counts(all_record_candidates),
        family_readiness_rows=_constraint_family_readiness_rows(
            all_record_candidates,
            solver_supported=solver_supported,
        ),
        bone_match_candidate_count=len(all_record_candidates),
        bone_match_counts=_constraint_bone_match_counts(all_record_candidates),
        expression_status=expression_status,
        expression_token_confidence=expression_token_confidence,
        expression_semantics_confidence=expression_semantics_confidence,
        expression_counts=expression_counts,
        expression_syntax_signature_counts=expression_syntax_signature_counts,
        expression_numeric_value_count=expression_numeric_value_count,
        field_offset_status=field_offset_status,
        field_offset_confidence=field_offset_confidence,
        field_offset_record_confidence=field_offset_record_confidence,
        field_offset_counts=field_offset_counts,
        numeric_match_count=numeric_match_count,
        numeric_match_status_counts=numeric_match_status_counts,
        numeric_match_role_counts=numeric_match_role_counts,
        numeric_match_storage_counts=numeric_match_storage_counts,
        numeric_match_pair_counts=numeric_match_pair_counts,
        numeric_match_value_confidence_counts=numeric_match_value_confidence_counts,
        numeric_match_family_counts=numeric_match_family_counts,
        numeric_match_family_row_counts=numeric_match_family_row_counts,
        numeric_match_family_role_counts=numeric_match_family_role_counts,
        numeric_match_family_pair_counts=numeric_match_family_pair_counts,
        numeric_match_family_value_confidence_counts=numeric_match_family_value_confidence_counts,
        numeric_match_signature_counts=numeric_match_signature_counts,
        numeric_match_candidate_relative_signature_counts=numeric_match_candidate_relative_signature_counts,
        numeric_match_previous_delta_counts=numeric_match_previous_delta_counts,
        numeric_match_next_delta_counts=numeric_match_next_delta_counts,
        numeric_match_candidate_relative_offset_counts=numeric_match_candidate_relative_offset_counts,
        numeric_match_min_previous_delta=numeric_match_min_previous_delta,
        numeric_match_max_previous_delta=numeric_match_max_previous_delta,
        numeric_match_min_next_delta=numeric_match_min_next_delta,
        numeric_match_max_next_delta=numeric_match_max_next_delta,
        numeric_match_min_candidate_relative_offset=numeric_match_min_candidate_relative_offset,
        numeric_match_max_candidate_relative_offset=numeric_match_max_candidate_relative_offset,
        numeric_match_offset_confidence=numeric_match_offset_confidence,
        numeric_match_candidate_relative_offset_confidence=numeric_match_candidate_relative_offset_confidence,
        solver_readiness_status=solver_readiness_status,
        solver_readiness_counts=solver_readiness_counts,
        solver_supported=solver_supported,
        proof_gap=str(evidence.get("proof_gap") or ""),
    )


def _constraint_candidate_family_counts(
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        family = str(candidate.constraint_type or "constraint_candidate").strip() or "constraint_candidate"
        counts[family] = counts.get(family, 0) + 1
    return tuple(sorted(counts.items(), key=lambda row: (-row[1], row[0])))


def _constraint_solver_readiness_summary(
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
    expression_counts: tuple[tuple[str, int], ...],
    *,
    solver_supported: bool,
) -> tuple[str, tuple[tuple[str, int], ...]]:
    if not candidates:
        return "", ()
    expression_candidate_count = sum(count for label, count in expression_counts if label.startswith("role "))
    return _constraint_solver_readiness_counts(
        candidates,
        expression_candidate_count=expression_candidate_count,
        solver_supported=solver_supported,
    )


def _constraint_family_readiness_rows(
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
    *,
    solver_supported: bool,
) -> tuple[tuple[str, str, tuple[tuple[str, int], ...]], ...]:
    grouped: dict[str, list[MeshConstraintRecordCandidateSummary]] = {}
    for candidate in candidates:
        family = str(candidate.constraint_type or "constraint_candidate").strip() or "constraint_candidate"
        grouped.setdefault(family, []).append(candidate)
    rows: list[tuple[str, str, tuple[tuple[str, int], ...]]] = []
    for family, family_candidates in sorted(grouped.items(), key=lambda row: (-len(row[1]), row[0])):
        family_tuple = tuple(family_candidates)
        status, counts = _constraint_solver_readiness_counts(
            family_tuple,
            expression_candidate_count=sum(1 for candidate in family_tuple if candidate.expression),
            solver_supported=solver_supported,
        )
        if counts:
            rows.append((family, status, counts))
    return tuple(rows)


def _constraint_solver_readiness_counts(
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
    *,
    expression_candidate_count: int,
    solver_supported: bool,
) -> tuple[str, tuple[tuple[str, int], ...]]:
    candidate_count = len(candidates)
    blocked_record_count = sum(
        1
        for candidate in candidates
        if "blocked" in str(candidate.solver_status or "").lower()
        or "unproven" in str(candidate.solver_status or "").lower()
    )
    counts = (
        ("candidates", candidate_count),
        ("solver ready", candidate_count - blocked_record_count if solver_supported else 0),
        ("target bound", sum(1 for candidate in candidates if candidate.target_bone and candidate.target_bone_index >= 0)),
        ("helper bound", sum(1 for candidate in candidates if candidate.helper_bone and candidate.helper_bone_index >= 0)),
        ("parent bound", sum(1 for candidate in candidates if candidate.parent_bone and candidate.parent_bone_index >= 0)),
        ("record layout unproven", blocked_record_count),
        ("expression semantics unknown", min(candidate_count, expression_candidate_count)),
    )
    status = "solver_enabled" if solver_supported else "solver_blocked_until_record_layout_and_expression_semantics_proven"
    return status, tuple((label, count) for label, count in counts if count > 0 or label == "solver ready")


def _constraint_field_offset_summary(
    evidence: Mapping[str, object],
) -> tuple[str, str, str, tuple[tuple[str, int], ...]]:
    raw = evidence.get("offset_evidence")
    if not isinstance(raw, Mapping):
        raw = evidence.get("constraint_offset_evidence")
    if not isinstance(raw, Mapping):
        return "", "", "", ()
    counts = (
        ("target", _int(raw.get("target_offset_count"))),
        ("helper", _int(raw.get("helper_offset_count"))),
        ("parent", _int(raw.get("parent_offset_count"))),
    )
    return (
        str(raw.get("status") or ""),
        str(raw.get("offset_confidence") or ""),
        str(raw.get("record_confidence") or ""),
        tuple((name, count) for name, count in counts if count > 0),
    )


def _constraint_numeric_match_summary(
    evidence: Mapping[str, object],
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
) -> tuple[
    int,
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    int,
    int,
    int,
    int,
    int,
    int,
    str,
    str,
]:
    raw = evidence.get("record_layout_evidence")
    if not isinstance(raw, Mapping):
        raw = evidence.get("constraint_record_layout_evidence")
    status_counts = _count_tuple(raw.get("gap_numeric_match_status_counts")) if isinstance(raw, Mapping) else ()
    role_counts = _count_tuple(raw.get("gap_numeric_match_role_counts")) if isinstance(raw, Mapping) else ()
    storage_counts = _count_tuple(raw.get("gap_numeric_match_storage_counts")) if isinstance(raw, Mapping) else ()
    pair_counts = _count_tuple(raw.get("gap_numeric_match_pair_counts")) if isinstance(raw, Mapping) else ()
    value_confidence_counts = _count_tuple(raw.get("gap_numeric_match_value_confidence_counts")) if isinstance(raw, Mapping) else ()
    family_counts = _count_tuple(raw.get("gap_numeric_match_family_counts")) if isinstance(raw, Mapping) else ()
    family_row_counts = _count_tuple(raw.get("gap_numeric_match_family_row_counts")) if isinstance(raw, Mapping) else ()
    family_role_counts = (
        _nested_count_tuple(raw.get("gap_numeric_match_family_role_counts"))
        if isinstance(raw, Mapping)
        else ()
    )
    family_pair_counts = (
        _nested_count_tuple(raw.get("gap_numeric_match_family_pair_counts"))
        if isinstance(raw, Mapping)
        else ()
    )
    family_value_confidence_counts = (
        _nested_count_tuple(raw.get("gap_numeric_match_family_value_confidence_counts"))
        if isinstance(raw, Mapping)
        else ()
    )
    signature_counts = _count_tuple(raw.get("gap_numeric_match_signature_counts")) if isinstance(raw, Mapping) else ()
    candidate_relative_signature_counts = (
        _count_tuple(raw.get("gap_numeric_match_candidate_relative_signature_counts"))
        if isinstance(raw, Mapping)
        else ()
    )
    previous_delta_counts = _count_tuple(raw.get("gap_numeric_match_previous_delta_counts")) if isinstance(raw, Mapping) else ()
    next_delta_counts = _count_tuple(raw.get("gap_numeric_match_next_delta_counts")) if isinstance(raw, Mapping) else ()
    candidate_relative_offset_counts = (
        _count_tuple(raw.get("gap_numeric_match_candidate_relative_offset_counts"))
        if isinstance(raw, Mapping)
        else ()
    )
    min_previous_delta = _int(raw.get("min_gap_numeric_match_previous_delta")) if isinstance(raw, Mapping) else 0
    max_previous_delta = _int(raw.get("max_gap_numeric_match_previous_delta")) if isinstance(raw, Mapping) else 0
    min_next_delta = _int(raw.get("min_gap_numeric_match_next_delta")) if isinstance(raw, Mapping) else 0
    max_next_delta = _int(raw.get("max_gap_numeric_match_next_delta")) if isinstance(raw, Mapping) else 0
    min_candidate_relative_offset = (
        _int(raw.get("min_gap_numeric_match_candidate_relative_offset")) if isinstance(raw, Mapping) else 0
    )
    max_candidate_relative_offset = (
        _int(raw.get("max_gap_numeric_match_candidate_relative_offset")) if isinstance(raw, Mapping) else 0
    )
    offset_confidence = str(raw.get("gap_numeric_match_offset_confidence") or "") if isinstance(raw, Mapping) else ""
    candidate_relative_offset_confidence = (
        str(raw.get("gap_numeric_match_candidate_relative_offset_confidence") or "")
        if isinstance(raw, Mapping)
        else ""
    )
    match_count = _int(raw.get("gap_numeric_match_count")) if isinstance(raw, Mapping) else 0
    if match_count or role_counts:
        return (
            match_count,
            status_counts,
            role_counts,
            storage_counts,
            pair_counts,
            value_confidence_counts,
            family_counts,
            family_row_counts,
            family_role_counts,
            family_pair_counts,
            family_value_confidence_counts,
            signature_counts,
            candidate_relative_signature_counts,
            previous_delta_counts,
            next_delta_counts,
            candidate_relative_offset_counts,
            min_previous_delta,
            max_previous_delta,
            min_next_delta,
            max_next_delta,
            min_candidate_relative_offset,
            max_candidate_relative_offset,
            offset_confidence,
            candidate_relative_offset_confidence,
        )

    status_counter: dict[str, int] = {}
    role_counter: dict[str, int] = {}
    storage_counter: dict[str, int] = {}
    pair_counter: dict[str, int] = {}
    value_confidence_counter: dict[str, int] = {}
    family_counter: dict[str, int] = {}
    family_row_counter: dict[str, int] = {}
    family_role_counter: dict[str, dict[str, int]] = {}
    family_pair_counter: dict[str, dict[str, int]] = {}
    family_value_confidence_counter: dict[str, dict[str, int]] = {}
    signature_counter: dict[str, int] = {}
    candidate_relative_signature_counter: dict[str, int] = {}
    previous_delta_counter: dict[str, int] = {}
    next_delta_counter: dict[str, int] = {}
    candidate_relative_offset_counter: dict[str, int] = {}
    previous_deltas: list[int] = []
    next_deltas: list[int] = []
    candidate_relative_offsets: list[int] = []
    offset_confidence = ""
    candidate_relative_offset_confidence = ""
    for candidate in candidates:
        status = str(candidate.record_gap_numeric_match_status or "")
        if status:
            status_counter[status] = status_counter.get(status, 0) + 1
        for role, count in candidate.record_gap_numeric_match_role_counts:
            role_counter[role] = role_counter.get(role, 0) + count
        for storage, count in candidate.record_gap_numeric_match_storage_counts:
            storage_counter[storage] = storage_counter.get(storage, 0) + count
        for pair, count in candidate.record_gap_numeric_match_pair_counts:
            pair_counter[pair] = pair_counter.get(pair, 0) + count
        for confidence, count in candidate.record_gap_numeric_match_value_confidence_counts:
            value_confidence_counter[confidence] = value_confidence_counter.get(confidence, 0) + count
        for signature, count in candidate.record_gap_numeric_match_signature_counts:
            signature_key = f"family={candidate.constraint_type or 'constraint_candidate'}|{signature}"
            signature_counter[signature_key] = signature_counter.get(signature_key, 0) + count
        for signature, count in candidate.record_gap_numeric_match_candidate_relative_signature_counts:
            signature_key = f"family={candidate.constraint_type or 'constraint_candidate'}|{signature}"
            candidate_relative_signature_counter[signature_key] = (
                candidate_relative_signature_counter.get(signature_key, 0) + count
            )
        for delta, count in candidate.record_gap_numeric_match_previous_delta_counts:
            previous_delta_counter[delta] = previous_delta_counter.get(delta, 0) + count
        for delta, count in candidate.record_gap_numeric_match_next_delta_counts:
            next_delta_counter[delta] = next_delta_counter.get(delta, 0) + count
        for relative_offset, count in candidate.record_gap_numeric_match_candidate_relative_offset_counts:
            candidate_relative_offset_counter[relative_offset] = (
                candidate_relative_offset_counter.get(relative_offset, 0) + count
            )
        match_count += candidate.record_gap_numeric_match_count
        if candidate.record_gap_numeric_match_count > 0:
            family = str(candidate.constraint_type or "constraint_candidate").strip() or "constraint_candidate"
            family_counter[family] = family_counter.get(family, 0) + candidate.record_gap_numeric_match_count
            family_row_counter[family] = family_row_counter.get(family, 0) + 1
            family_roles = family_role_counter.setdefault(family, {})
            for role, count in candidate.record_gap_numeric_match_role_counts:
                family_roles[role] = family_roles.get(role, 0) + count
            family_pairs = family_pair_counter.setdefault(family, {})
            for pair, count in candidate.record_gap_numeric_match_pair_counts:
                family_pairs[pair] = family_pairs.get(pair, 0) + count
            confidence_counter = family_value_confidence_counter.setdefault(family, {})
            for confidence, count in candidate.record_gap_numeric_match_value_confidence_counts:
                confidence_counter[confidence] = confidence_counter.get(confidence, 0) + count
            previous_deltas.extend(
                (
                    candidate.record_gap_numeric_match_min_previous_delta,
                    candidate.record_gap_numeric_match_max_previous_delta,
                )
            )
            next_deltas.extend(
                (
                    candidate.record_gap_numeric_match_min_next_delta,
                    candidate.record_gap_numeric_match_max_next_delta,
                )
            )
            candidate_relative_offsets.extend(
                (
                    candidate.record_gap_numeric_match_min_candidate_relative_offset,
                    candidate.record_gap_numeric_match_max_candidate_relative_offset,
                )
            )
            if candidate.record_gap_numeric_match_offset_confidence:
                offset_confidence = candidate.record_gap_numeric_match_offset_confidence
            if candidate.record_gap_numeric_match_candidate_relative_offset_confidence:
                candidate_relative_offset_confidence = (
                    candidate.record_gap_numeric_match_candidate_relative_offset_confidence
                )
    return (
        match_count,
        tuple(sorted(status_counter.items())),
        tuple(sorted(role_counter.items())),
        tuple(sorted(storage_counter.items())),
        tuple(sorted(pair_counter.items())),
        tuple(sorted(value_confidence_counter.items())),
        tuple(sorted(family_counter.items())),
        tuple(sorted(family_row_counter.items())),
        _nested_count_tuple(family_role_counter),
        _nested_count_tuple(family_pair_counter),
        _nested_count_tuple(family_value_confidence_counter),
        tuple(sorted(signature_counter.items())),
        tuple(sorted(candidate_relative_signature_counter.items())),
        tuple(sorted(previous_delta_counter.items())),
        tuple(sorted(next_delta_counter.items())),
        tuple(sorted(candidate_relative_offset_counter.items())),
        min(previous_deltas) if previous_deltas else 0,
        max(previous_deltas) if previous_deltas else 0,
        min(next_deltas) if next_deltas else 0,
        max(next_deltas) if next_deltas else 0,
        min(candidate_relative_offsets) if candidate_relative_offsets else 0,
        max(candidate_relative_offsets) if candidate_relative_offsets else 0,
        offset_confidence,
        candidate_relative_offset_confidence,
    )


def _constraint_expression_evidence_summary(
    evidence: Mapping[str, object],
) -> tuple[str, str, str, tuple[tuple[str, int], ...], tuple[tuple[str, int], ...], int]:
    raw = evidence.get("expression_evidence")
    if not isinstance(raw, Mapping):
        raw = evidence.get("constraint_expression_evidence")
    if not isinstance(raw, Mapping):
        return "", "", "", (), (), 0
    rows: list[tuple[str, int]] = []
    for prefix, key in (
        ("channel", "channel_counts"),
        ("limit", "limit_operator_counts"),
        ("shape", "shape_counts"),
        ("numeric role", "numeric_role_counts"),
        ("role", "expression_role_counts"),
    ):
        counts = raw.get(key)
        if not isinstance(counts, Mapping):
            continue
        for name, count in counts.items():
            value = _int(count)
            if value > 0:
                rows.append((f"{prefix} {name}", value))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return (
        str(raw.get("status") or ""),
        str(raw.get("token_confidence") or ""),
        str(raw.get("semantics_confidence") or ""),
        tuple(rows),
        _count_tuple(raw.get("syntax_signature_counts")),
        _int(raw.get("numeric_value_count")),
    )


def _constraint_record_candidate_rows(
    evidence: Mapping[str, object],
    *,
    bones: tuple[MeshSkeletonBoneSummary, ...] = (),
    max_rows: int | None = 6,
) -> tuple[MeshConstraintRecordCandidateSummary, ...]:
    rows = evidence.get("record_candidates")
    if not isinstance(rows, tuple | list):
        rows = evidence.get("constraint_record_candidate_rows")
    if not isinstance(rows, tuple | list):
        return ()
    bone_indices = {bone.name: bone.index for bone in bones if bone.name}
    candidates: list[MeshConstraintRecordCandidateSummary] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        target_bone = str(row.get("target_bone") or "")
        helper_bone = str(row.get("helper_bone") or "")
        parent_bone = str(row.get("parent_bone") or "")
        target_index, target_confidence = _constraint_bone_match(target_bone, bone_indices, role="target")
        helper_index, helper_confidence = _constraint_bone_match(helper_bone, bone_indices, role="helper")
        parent_index, parent_confidence = _constraint_bone_match(parent_bone, bone_indices, role="parent")
        candidates.append(
            MeshConstraintRecordCandidateSummary(
                offset=_int(row.get("offset")),
                constraint_type=str(row.get("constraint_type") or "constraint_candidate"),
                target_bone=target_bone,
                target_bone_index=target_index,
                target_bone_confidence=target_confidence,
                helper_bone=helper_bone,
                helper_bone_index=helper_index,
                helper_bone_confidence=helper_confidence,
                parent_bone=parent_bone,
                parent_bone_index=parent_index,
                parent_bone_confidence=parent_confidence,
                expression=str(row.get("expression") or ""),
                expression_offset=_int(row.get("expression_offset")),
                target_bone_offset=_int(row.get("target_bone_offset")),
                target_bone_delta=_int(row.get("target_bone_delta")),
                helper_bone_offset=_int(row.get("helper_bone_offset")),
                helper_bone_delta=_int(row.get("helper_bone_delta")),
                parent_bone_offset=_int(row.get("parent_bone_offset")),
                parent_bone_delta=_int(row.get("parent_bone_delta")),
                expression_channels=_string_tuple(row.get("expression_channels")),
                limit_operators=_string_tuple(row.get("limit_operators")),
                expression_numeric_values=_string_tuple(row.get("expression_numeric_values")),
                field_confidence=str(row.get("field_confidence") or ""),
                field_offset_confidence=str(row.get("field_offset_confidence") or ""),
                expression_channel_confidence=str(row.get("expression_channel_confidence") or ""),
                limit_operator_confidence=str(row.get("limit_operator_confidence") or ""),
                expression_numeric_value_confidence=str(row.get("expression_numeric_value_confidence") or ""),
                expression_numeric_roles=_string_tuple(row.get("expression_numeric_roles")),
                expression_numeric_role_confidence=str(row.get("expression_numeric_role_confidence") or ""),
                expression_shape=str(row.get("expression_shape") or ""),
                expression_syntax_signature=str(row.get("expression_syntax_signature") or ""),
                expression_shape_confidence=str(row.get("expression_shape_confidence") or ""),
                expression_shape_status=str(row.get("expression_shape_status") or ""),
                expression_semantics_confidence=str(row.get("expression_semantics_confidence") or ""),
                record_confidence=str(row.get("record_confidence") or "unknown"),
                record_span_start=_int(row.get("record_span_start")),
                record_span_end=_int(row.get("record_span_end")),
                record_span_size=_int(row.get("record_span_size")),
                record_span_field_count=_int(row.get("record_span_field_count")),
                record_field_sequence=_string_tuple(row.get("record_field_sequence")),
                record_field_sequence_confidence=str(row.get("record_field_sequence_confidence") or ""),
                record_gap_status=str(row.get("record_gap_status") or ""),
                record_gap_classes=_string_tuple(row.get("record_gap_classes")),
                record_gap_class_counts=_count_tuple(row.get("record_gap_class_counts")),
                record_gap_count=_int(row.get("record_gap_count")),
                record_gap_total_size=_int(row.get("record_gap_total_size")),
                record_gap_max_size=_int(row.get("record_gap_max_size")),
                record_gap_confidence=str(row.get("record_gap_confidence") or ""),
                record_gap_scalar_status=str(row.get("record_gap_scalar_status") or ""),
                record_gap_scalar_kind_counts=_count_tuple(row.get("record_gap_scalar_kind_counts")),
                record_gap_aligned_word_count=_int(row.get("record_gap_aligned_word_count")),
                record_gap_scalar_candidate_count=_int(row.get("record_gap_scalar_candidate_count")),
                record_gap_scalar_confidence=str(row.get("record_gap_scalar_confidence") or ""),
                record_gap_numeric_match_status=str(row.get("record_gap_numeric_match_status") or ""),
                record_gap_numeric_match_role_counts=_count_tuple(row.get("record_gap_numeric_match_role_counts")),
                record_gap_numeric_match_scalar_kind_counts=_count_tuple(row.get("record_gap_numeric_match_scalar_kind_counts")),
                record_gap_numeric_match_storage_counts=_count_tuple(row.get("record_gap_numeric_match_storage_counts")),
                record_gap_numeric_match_pair_counts=_count_tuple(row.get("record_gap_numeric_match_pair_counts")),
                record_gap_numeric_match_value_confidence_counts=_count_tuple(
                    row.get("record_gap_numeric_match_value_confidence_counts")
                ),
                record_gap_numeric_match_signature_counts=_count_tuple(
                    row.get("record_gap_numeric_match_signature_counts")
                ),
                record_gap_numeric_match_candidate_relative_signature_counts=_count_tuple(
                    row.get("record_gap_numeric_match_candidate_relative_signature_counts")
                ),
                record_gap_numeric_match_previous_delta_counts=_count_tuple(
                    row.get("record_gap_numeric_match_previous_delta_counts")
                ),
                record_gap_numeric_match_next_delta_counts=_count_tuple(
                    row.get("record_gap_numeric_match_next_delta_counts")
                ),
                record_gap_numeric_match_candidate_relative_offset_counts=_count_tuple(
                    row.get("record_gap_numeric_match_candidate_relative_offset_counts")
                ),
                record_gap_numeric_match_count=_int(row.get("record_gap_numeric_match_count")),
                record_gap_numeric_match_min_previous_delta=_int(
                    row.get("record_gap_numeric_match_min_previous_delta")
                ),
                record_gap_numeric_match_max_previous_delta=_int(
                    row.get("record_gap_numeric_match_max_previous_delta")
                ),
                record_gap_numeric_match_min_next_delta=_int(row.get("record_gap_numeric_match_min_next_delta")),
                record_gap_numeric_match_max_next_delta=_int(row.get("record_gap_numeric_match_max_next_delta")),
                record_gap_numeric_match_min_candidate_relative_offset=_int(
                    row.get("record_gap_numeric_match_min_candidate_relative_offset")
                ),
                record_gap_numeric_match_max_candidate_relative_offset=_int(
                    row.get("record_gap_numeric_match_max_candidate_relative_offset")
                ),
                record_gap_numeric_match_offset_confidence=str(
                    row.get("record_gap_numeric_match_offset_confidence") or ""
                ),
                record_gap_numeric_match_candidate_relative_offset_confidence=str(
                    row.get("record_gap_numeric_match_candidate_relative_offset_confidence") or ""
                ),
                record_gap_numeric_match_confidence=str(row.get("record_gap_numeric_match_confidence") or ""),
                record_layout_status=str(row.get("record_layout_status") or ""),
                solver_status=str(row.get("solver_status") or "blocked"),
            )
        )
        if max_rows is not None and len(candidates) >= max_rows:
            break
    return tuple(candidates)


def _constraint_bone_match(name: str, bone_indices: Mapping[str, int], *, role: str = "") -> tuple[int, str]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return -1, "missing"
    if clean_name in bone_indices:
        return int(bone_indices[clean_name]), "exact_name"
    base_name = _constraint_suffix_base_name(clean_name)
    if base_name and base_name in bone_indices:
        return int(bone_indices[base_name]), "suffix_base_name"
    base_name = _constraint_parent_prefix_base_name(clean_name) if role == "parent" else ""
    if base_name and base_name in bone_indices:
        return int(bone_indices[base_name]), "prefix_base_name"
    return -1, "unmatched"


def _constraint_suffix_base_name(name: str) -> str:
    parts = str(name or "").split(":")
    if len(parts) <= 1:
        return ""
    if all(part.isdigit() for part in parts[1:]):
        return parts[0].strip()
    return ""


def _constraint_parent_prefix_base_name(name: str) -> str:
    clean_name = str(name or "").strip()
    if clean_name.startswith("P_"):
        return clean_name[2:].strip()
    return ""


def _constraint_bone_match_counts(
    candidates: tuple[MeshConstraintRecordCandidateSummary, ...],
) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for role, name, confidence in (
            ("target", candidate.target_bone, candidate.target_bone_confidence),
            ("helper", candidate.helper_bone, candidate.helper_bone_confidence),
            ("parent", candidate.parent_bone, candidate.parent_bone_confidence),
        ):
            if not str(name or "").strip():
                continue
            key = f"{role}_{confidence or 'unknown'}"
            counts[key] = counts.get(key, 0) + 1
    role_order = {"target": 0, "helper": 1, "parent": 2}
    confidence_order = {"exact_name": 0, "suffix_base_name": 1, "prefix_base_name": 2, "unmatched": 3, "missing": 4}

    def sort_key(row: tuple[str, int]) -> tuple[int, int, str]:
        role, _, confidence = row[0].partition("_")
        return (role_order.get(role, 99), confidence_order.get(confidence, 99), row[0])

    return tuple(sorted(((key, value) for key, value in counts.items() if value > 0), key=sort_key))


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, tuple | list):
        return tuple(str(item) for item in value if str(item))
    return ()


def _count_tuple(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping):
        return ()
    rows = ((str(key), _int(count)) for key, count in value.items())
    return tuple(sorted((key, count) for key, count in rows if key and count > 0))


def _nested_count_tuple(value: object) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    if not isinstance(value, Mapping):
        return ()
    rows: list[tuple[str, tuple[tuple[str, int], ...]]] = []
    for key, counts in value.items():
        nested_counts = _count_tuple(counts)
        if str(key) and nested_counts:
            rows.append((str(key), nested_counts))
    return tuple(sorted(rows))


def _animation_blockers(skeleton_variation_source: str, animation_constraint_source: str) -> tuple[str, ...]:
    if not (skeleton_variation_source or animation_constraint_source):
        return ()
    return (
        "PABC/PAPR data is linked as metadata but is not parsed into bind-pose or animation tracks yet.",
        "PAA/PASEQ keyframes are read-only relationship evidence until bone-track binding is proven.",
    )


def _authoring_status_rows(
    *,
    skinned: bool,
    skeleton_linked: bool,
    invalid_row_count: int,
    animation_playback: MeshAnimationPlaybackSummary,
    skeleton_variation_source: str,
    animation_constraint_source: str,
) -> tuple[MeshAuthoringStatusRow, ...]:
    rows: list[MeshAuthoringStatusRow] = []
    if skinned:
        rows.append(
            MeshAuthoringStatusRow(
                feature="Pose preview",
                state="preview-only" if skeleton_linked else "blocked",
                confidence="proven" if skeleton_linked else "unknown",
                detail=(
                    "PAB skinning drives preview geometry without mutating the edit session."
                    if skeleton_linked
                    else "Attach a parsed PAB skeleton before pose preview."
                ),
            )
        )
        rows.append(
            MeshAuthoringStatusRow(
                feature="Weight edits",
                state="exportable" if invalid_row_count <= 0 else "blocked",
                confidence="proven" if invalid_row_count <= 0 else "blocked",
                detail=(
                    "Edit-session weights can use the package export path."
                    if invalid_row_count <= 0
                    else "Invalid skinning rows must be fixed before export."
                ),
            )
        )
    if animation_playback.ready:
        timing_status = animation_playback.timing_status or animation_playback.timing_confidence
        rows.append(
            MeshAuthoringStatusRow(
                feature="Animation playback",
                state="preview-only",
                confidence="proven",
                detail=f"{animation_playback.track_count} bound track(s); timing {timing_status}; game writer semantics unknown.",
            )
        )
    elif skeleton_variation_source or animation_constraint_source:
        rows.append(
            MeshAuthoringStatusRow(
                feature="Animation playback",
                state="blocked",
                confidence="unknown",
                detail="PASEQ/PAA timing or track ownership is not proven for this session.",
            )
        )
    if animation_constraint_source:
        rows.append(
            MeshAuthoringStatusRow(
                feature="PAPR constraints",
                state="blocked",
                confidence="unknown",
                detail="PAPR is read-only metadata until constraint fields and solver semantics are proven.",
            )
        )
    rows.append(
        MeshAuthoringStatusRow(
            feature="Archive mutation",
            state="blocked",
            confidence="blocked",
            detail="Direct archive writes remain disabled; package export is the default path.",
        )
    )
    return tuple(rows)


def _animation_clip_blockers(
    bones: tuple[MeshSkeletonBoneSummary, ...],
    clip: MeshAnimationClip,
) -> tuple[str, ...]:
    if not bones:
        return ("Animation playback needs an attached parsed skeleton.",)
    tracks = tuple(clip.tracks or ())
    if not tracks:
        return ("Animation clip has no parsed bone tracks.",)
    by_index = {bone.index: bone for bone in bones}
    by_name = {bone.name.strip().lower(): bone.index for bone in bones if bone.name.strip()}
    bound_tracks = 0
    for track in tracks:
        bone_index = _track_bone_index(track, by_index, by_name)
        if bone_index is None:
            continue
        if _valid_rotation_keyframes(track.rotation_keyframes):
            bound_tracks += 1
    if bound_tracks <= 0:
        return ("Animation clip has no rotation tracks bound to the attached skeleton bones.",)
    return ()


def _animation_clip_timing(clip: MeshAnimationClip) -> tuple[float, str, str, bool]:
    frame_rate = _coerce_float(getattr(clip, "frame_rate", 0.0)) or 0.0
    confidence = str(getattr(clip, "timing_confidence", "") or "").strip().lower()
    if confidence not in _TIMING_CONFIDENCE_LABELS:
        confidence = "unknown"
    status = str(getattr(clip, "timing_status", "") or "").strip()
    if not status:
        status = "game_accurate_timing_proven" if confidence == "proven" and frame_rate > 0.0 else "timing_unproven"
    return frame_rate, confidence, status, bool(confidence == "proven" and frame_rate > 0.0)


def _track_bone_index(
    track: MeshAnimationTrack,
    by_index: Mapping[int, MeshSkeletonBoneSummary],
    by_name: Mapping[str, int],
) -> int | None:
    bone_index = _coerce_index(track.bone_index)
    if bone_index is not None and bone_index in by_index:
        return bone_index
    name = str(track.bone_name or "").strip().lower()
    if name:
        resolved = by_name.get(name)
        if resolved is not None:
            return resolved
    return None


def _valid_rotation_keyframes(
    keyframes: tuple[MeshAnimationKeyframe, ...],
) -> tuple[MeshAnimationKeyframe, ...]:
    valid: list[MeshAnimationKeyframe] = []
    for keyframe in tuple(keyframes or ()):
        time_value = _coerce_float(getattr(keyframe, "time_seconds", None))
        rotation = _vec3(getattr(keyframe, "rotation_degrees", ()))
        if time_value is None or time_value < 0.0 or not rotation:
            continue
        valid.append(MeshAnimationKeyframe(time_seconds=time_value, rotation_degrees=rotation))
    return tuple(sorted(valid, key=lambda item: item.time_seconds))


def _animation_clip_duration(clip: MeshAnimationClip) -> float:
    duration = _coerce_float(getattr(clip, "duration_seconds", 0.0)) or 0.0
    max_keyframe_time = 0.0
    for track in tuple(clip.tracks or ()):
        keyframes = _valid_rotation_keyframes(track.rotation_keyframes)
        if keyframes:
            max_keyframe_time = max(max_keyframe_time, keyframes[-1].time_seconds)
    return max(0.0, duration, max_keyframe_time)


def _active_sequence_segment(
    clip: MeshAnimationClip,
    time_seconds: float,
) -> MeshAnimationSequenceSegment | None:
    segments = tuple(clip.sequence_segments or ())
    if not segments:
        return None
    for segment in sorted(segments, key=lambda item: (_coerce_float(item.start_seconds) or 0.0, item.lane_index)):
        start = max(0.0, _coerce_float(segment.start_seconds) or 0.0)
        end = max(start, _coerce_float(segment.end_seconds) or start)
        if start <= time_seconds <= end:
            return segment
    return None


def _sequence_segment_diagnostics(
    segment: MeshAnimationSequenceSegment | None,
) -> tuple[int, str, str, str, tuple[tuple[str, str], ...]]:
    if segment is None:
        return -1, "", "", "", ()
    confidence_rows: list[tuple[str, str]] = []
    for raw_name, raw_confidence in tuple(segment.field_confidence or ()):
        name = str(raw_name or "").strip()
        confidence = str(raw_confidence or "").strip().lower()
        if name and confidence in _TIMING_CONFIDENCE_LABELS:
            confidence_rows.append((name, confidence))
    lane_index = _coerce_index(segment.lane_index)
    return (
        lane_index if lane_index is not None else -1,
        str(segment.sequence_path or ""),
        str(segment.clip_path or ""),
        str(segment.status or ""),
        tuple(confidence_rows),
    )


def _animation_time(value: object, duration: float, *, loop: bool) -> float:
    time_value = _coerce_float(value) or 0.0
    time_value = max(0.0, time_value)
    if duration <= 1e-8:
        return 0.0
    if loop:
        return time_value % duration
    return min(time_value, duration)


def _animation_speed(value: object) -> float:
    number = _coerce_float(value) or 1.0
    return min(4.0, max(0.1, number))


def _sample_rotation_keyframes(
    keyframes: tuple[MeshAnimationKeyframe, ...],
    time_seconds: float,
) -> tuple[float, float, float]:
    if not keyframes:
        return (0.0, 0.0, 0.0)
    if time_seconds <= keyframes[0].time_seconds:
        return keyframes[0].rotation_degrees
    for previous, following in zip(keyframes, keyframes[1:]):
        if time_seconds > following.time_seconds:
            continue
        span = max(1e-8, following.time_seconds - previous.time_seconds)
        amount = max(0.0, min(1.0, (time_seconds - previous.time_seconds) / span))
        return tuple(
            previous.rotation_degrees[axis]
            + (following.rotation_degrees[axis] - previous.rotation_degrees[axis]) * amount
            for axis in range(3)
        )  # type: ignore[return-value]
    return keyframes[-1].rotation_degrees


def mesh_pose_deformed_vertices(
    mesh: object,
    skeleton: object | None,
    pose_rotations: Mapping[int, tuple[float, float, float]] | None,
) -> dict[int, tuple[tuple[float, float, float], ...]]:
    """Return preview-only skinned vertex positions for a posed skeleton."""
    rotations = {
        index: rotation
        for raw_index, raw_rotation in tuple((pose_rotations or {}).items())
        if (index := _coerce_index(raw_index)) is not None
        if (rotation := _vec3(raw_rotation)) and any(abs(component) > 1e-6 for component in rotation)
    }
    if skeleton is None or not rotations:
        return {}
    skinning_matrices = _bone_skinning_matrices(tuple(getattr(skeleton, "bones", ()) or ()), rotations)
    if not skinning_matrices:
        return {}

    deformed: dict[int, tuple[tuple[float, float, float], ...]] = {}
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        if not vertices or len(bone_indices) != len(vertices) or len(bone_weights) != len(vertices):
            continue
        next_vertices: list[tuple[float, float, float]] = []
        changed = False
        for vertex_index, raw_vertex in enumerate(vertices):
            vertex = _vec3(raw_vertex)
            if not vertex:
                next_vertices.append((0.0, 0.0, 0.0))
                continue
            posed = _skin_vertex(
                vertex,
                _row_tuple(bone_indices[vertex_index]),
                _row_tuple(bone_weights[vertex_index]),
                skinning_matrices,
            )
            next_vertices.append(posed)
            changed = changed or any(abs(posed[axis] - vertex[axis]) > 1e-6 for axis in range(3))
        if changed:
            deformed[submesh_index] = tuple(next_vertices)
    return deformed


_Matrix4 = tuple[float, float, float, float, float, float, float, float, float, float, float, float, float, float, float, float]
_IDENTITY_MATRIX: _Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _bone_skinning_matrices(
    raw_bones: tuple[object, ...],
    rotations: Mapping[int, tuple[float, float, float]],
) -> dict[int, _Matrix4]:
    bones: dict[int, object] = {}
    for ordinal, bone in enumerate(raw_bones):
        index = _coerce_index(getattr(bone, "index", ordinal))
        if index is None or index < 0:
            index = ordinal
        bones[index] = bone
    if not bones:
        return {}
    bind_globals: dict[int, _Matrix4] = {}
    pose_globals: dict[int, _Matrix4] = {}
    skinning: dict[int, _Matrix4] = {}

    def build(index: int, seen: set[int] | None = None) -> None:
        if index in skinning:
            return
        if seen is None:
            seen = set()
        if index in seen:
            bind_globals[index] = _IDENTITY_MATRIX
            pose_globals[index] = _IDENTITY_MATRIX
            skinning[index] = _IDENTITY_MATRIX
            return
        seen.add(index)
        bone = bones[index]
        parent_index = _coerce_index(getattr(bone, "parent_index", -1))
        if parent_index is None or parent_index not in bones or parent_index == index:
            parent_index = -1
        if parent_index >= 0:
            build(parent_index, seen)

        bind_global = _bone_bind_matrix(bone)
        bind_globals[index] = bind_global
        if parent_index >= 0:
            parent_bind_inverse = _invert_rigid_affine(bind_globals.get(parent_index, _IDENTITY_MATRIX))
            local_bind = _matrix_multiply(parent_bind_inverse, bind_global)
            parent_pose = pose_globals.get(parent_index, _IDENTITY_MATRIX)
        else:
            local_bind = bind_global
            parent_pose = _IDENTITY_MATRIX
        pose_local = _matrix_multiply(local_bind, _euler_rotation_matrix(rotations.get(index, (0.0, 0.0, 0.0))))
        pose_global = _matrix_multiply(parent_pose, pose_local)
        pose_globals[index] = pose_global
        inv_bind = _bone_inverse_bind_matrix(bone) or _invert_rigid_affine(bind_global)
        skinning[index] = _matrix_multiply(pose_global, inv_bind)

    for bone_index in sorted(bones):
        build(bone_index)
    return skinning


def _bone_bind_matrix(bone: object) -> _Matrix4:
    matrix = _matrix4(getattr(bone, "bind_matrix", ()))
    if matrix is not None:
        return matrix
    return _translation_matrix(_vec3(getattr(bone, "position", ())) or (0.0, 0.0, 0.0))


def _bone_inverse_bind_matrix(bone: object) -> _Matrix4 | None:
    return _matrix4(getattr(bone, "inv_bind_matrix", ()))


def _matrix4(value: object) -> _Matrix4 | None:
    try:
        raw = tuple(float(component) for component in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if len(raw) != 16 or any(not math.isfinite(component) for component in raw):
        return None
    if not any(abs(component) > 1e-12 for component in raw):
        return None
    matrix = raw  # type: ignore[assignment]
    column_translation = abs(matrix[3]) + abs(matrix[7]) + abs(matrix[11])
    row_translation = abs(matrix[12]) + abs(matrix[13]) + abs(matrix[14])
    if row_translation > column_translation and column_translation <= 1e-6:
        matrix = _transpose_matrix(matrix)
    return matrix


def _translation_matrix(position: tuple[float, float, float]) -> _Matrix4:
    x, y, z = position
    return (
        1.0, 0.0, 0.0, x,
        0.0, 1.0, 0.0, y,
        0.0, 0.0, 1.0, z,
        0.0, 0.0, 0.0, 1.0,
    )


def _euler_rotation_matrix(rotation_degrees: tuple[float, float, float]) -> _Matrix4:
    x, y, z = (math.radians(component) for component in rotation_degrees)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx: _Matrix4 = (
        1.0, 0.0, 0.0, 0.0,
        0.0, cx, -sx, 0.0,
        0.0, sx, cx, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    ry: _Matrix4 = (
        cy, 0.0, sy, 0.0,
        0.0, 1.0, 0.0, 0.0,
        -sy, 0.0, cy, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    rz: _Matrix4 = (
        cz, -sz, 0.0, 0.0,
        sz, cz, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    return _matrix_multiply(rz, _matrix_multiply(ry, rx))


def _matrix_multiply(left: _Matrix4, right: _Matrix4) -> _Matrix4:
    return tuple(
        sum(left[row * 4 + mid] * right[mid * 4 + column] for mid in range(4))
        for row in range(4)
        for column in range(4)
    )  # type: ignore[return-value]


def _transpose_matrix(matrix: _Matrix4) -> _Matrix4:
    return tuple(matrix[column * 4 + row] for row in range(4) for column in range(4))  # type: ignore[return-value]


def _invert_rigid_affine(matrix: _Matrix4) -> _Matrix4:
    r00, r01, r02, tx = matrix[0], matrix[1], matrix[2], matrix[3]
    r10, r11, r12, ty = matrix[4], matrix[5], matrix[6], matrix[7]
    r20, r21, r22, tz = matrix[8], matrix[9], matrix[10], matrix[11]
    return (
        r00, r10, r20, -(r00 * tx + r10 * ty + r20 * tz),
        r01, r11, r21, -(r01 * tx + r11 * ty + r21 * tz),
        r02, r12, r22, -(r02 * tx + r12 * ty + r22 * tz),
        0.0, 0.0, 0.0, 1.0,
    )


def _transform_point(matrix: _Matrix4, point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )


def _skin_vertex(
    vertex: tuple[float, float, float],
    bone_indices: tuple[object, ...],
    bone_weights: tuple[object, ...],
    skinning_matrices: Mapping[int, _Matrix4],
) -> tuple[float, float, float]:
    if len(bone_indices) != len(bone_weights):
        return vertex
    total = 0.0
    x = y = z = 0.0
    for raw_index, raw_weight in zip(bone_indices, bone_weights):
        bone_index = _coerce_index(raw_index)
        weight = _coerce_float(raw_weight)
        if bone_index is None or weight is None or weight <= 0.0:
            continue
        matrix = skinning_matrices.get(bone_index)
        if matrix is None:
            continue
        px, py, pz = _transform_point(matrix, vertex)
        x += px * weight
        y += py * weight
        z += pz * weight
        total += weight
    if total <= 1e-8:
        return vertex
    return (x / total, y / total, z / total)


__all__ = [
    "MeshAnimationClip",
    "MeshAnimationKeyframe",
    "MeshAnimationPlaybackSummary",
    "MeshAuthoringStatusRow",
    "MeshAnimationTrack",
    "MeshSkeletonBoneSummary",
    "MeshSkeletonPoseSummary",
    "MeshSkeletonSummary",
    "MeshSkinningPartSummary",
    "MeshVertexWeightSummary",
    "mesh_animation_clip_from_document",
    "mesh_pose_deformed_vertices",
    "sample_mesh_animation_pose",
    "summarize_mesh_animation_playback",
    "summarize_mesh_skinning",
    "summarize_skeleton_bones",
]
