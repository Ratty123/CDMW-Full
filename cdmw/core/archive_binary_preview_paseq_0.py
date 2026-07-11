from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
    'PurePosixPath',
    '_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS',
)
def _paseq_sequence_stem(virtual_path: str) -> str:
    basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    lowered = basename.lower()
    for extension in sorted(_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS, key=len, reverse=True):
        if lowered.endswith(extension):
            return basename[: -len(extension)]
    return PurePosixPath(basename).stem


@bind_binary_preview_globals(
    'PurePosixPath',
    '_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS',
)
def _paseq_reference_role(path: str) -> str:
    extension = PurePosixPath(str(path or "").replace("\\", "/")).suffix.lower()
    if extension in {".paa", ".paa_metabin", ".motionblending"}:
        return "animation_clip"
    if extension in {".hkx", ".hkt"}:
        return "havok_animation_or_skeleton"
    if extension in {".pae", ".paem", ".seqmt", ".dds", ".wem", ".bnk"}:
        return "effect_or_presentation"
    if extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        return "sequence_or_stage"
    if extension in {".pac", ".pam", ".pamlod"}:
        return "model_context"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}:
        return "skeleton_or_rig_context"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".xml"}:
        return "scene_or_descriptor_context"
    return "related_asset"


@bind_binary_preview_globals(
    '_PASEQ_EFFECT_FIELD_TOKENS',
    '_PASEQ_SCENE_FIELD_TOKENS',
)
def _paseq_timeline_field_role(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "field"
    if any(token in normalized for token in ("animation", "clip", "motion")):
        return "animation_track"
    if any(token in normalized for token in _PASEQ_EFFECT_FIELD_TOKENS):
        return "effect_track"
    if any(token in normalized for token in ("event", "notify", "trigger", "condition")):
        return "event"
    if any(token in normalized for token in ("duration", "frame", "start", "end", "time", "tick")):
        return "timing"
    if any(token in normalized for token in ("parameter", "blend", "phase", "loop", "speed")):
        return "motion_parameter"
    if any(token in normalized for token in _PASEQ_SCENE_FIELD_TOKENS):
        return "scene_context"
    return "timeline_field"


@bind_binary_preview_globals(
    'Mapping',
    '_PASEQ_EFFECT_FIELD_TOKENS',
    '_PASEQ_SCENE_FIELD_TOKENS',
    '_PASEQ_TIMELINE_FIELD_TOKENS',
    '_looks_like_structured_field_name',
    '_paseq_timeline_field_role',
)
def _paseq_timeline_field_rows(
    schema_member_rows: Sequence[Mapping[str, object]],
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_rows: int = 512,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()

    def add_row(
        *,
        name: str,
        source: str,
        offset: int,
        declared_type: str = "",
        descriptor_hex: str = "",
        descriptor_offset: int = 0,
        confidence: str = "",
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        normalized = clean_name.lstrip("_").lower()
        if not any(token in normalized for token in (*_PASEQ_TIMELINE_FIELD_TOKENS, *_PASEQ_EFFECT_FIELD_TOKENS, *_PASEQ_SCENE_FIELD_TOKENS)):
            return
        key: tuple[object, ...]
        if source == "schema_declaration":
            key = (source, clean_name.lower(), int(offset), declared_type)
        else:
            key = (source, clean_name.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "name": clean_name,
                "role": _paseq_timeline_field_role(clean_name),
                "source": source,
                "offset": int(offset),
                "declared_type": declared_type,
                "descriptor_hex": descriptor_hex,
                "descriptor_offset": int(descriptor_offset),
                "confidence": confidence or source,
            }
        )

    for row in schema_member_rows:
        if not isinstance(row, Mapping):
            continue
        add_row(
            name=str(row.get("name") or ""),
            source="schema_declaration",
            offset=int(row.get("name_offset") or row.get("declaration_offset") or 0),
            declared_type=str(row.get("declared_type") or ""),
            descriptor_hex=str(row.get("descriptor_hex") or ""),
            descriptor_offset=int(row.get("descriptor_offset") or 0),
            confidence=str(row.get("confidence") or "length_prefixed_declaration"),
        )
        if len(rows) >= max_rows:
            return rows

    for record in string_records:
        if not _looks_like_structured_field_name(record.text):
            continue
        add_row(
            name=record.text,
            source="readable_string_identifier",
            offset=int(record.offset),
            confidence="readable_string_identifier",
        )
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    '_paseq_timeline_field_role',
)
def _paseq_event_marker_rows(
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_rows: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    marker_tokens = (
        "begin",
        "camera",
        "effect",
        "end",
        "event",
        "loop",
        "notify",
        "phase",
        "sound",
        "start",
        "trigger",
    )
    for record in string_records:
        text = str(record.text or "").strip()
        normalized = text.lower()
        if normalized in seen:
            continue
        if not any(token in normalized for token in marker_tokens):
            continue
        seen.add(normalized)
        rows.append(
            {
                "offset": int(record.offset),
                "text": text,
                "role": _paseq_timeline_field_role(text),
                "confidence": "readable_event_or_phase_marker",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    'math',
    'struct',
)
def _paseq_timing_candidate_rows(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen_offsets: set[Tuple[int, str]] = set()
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 4:
        return rows

    def add_row(offset: int, kind: str, value: object, confidence: str) -> None:
        key = (offset, kind)
        if key in seen_offsets:
            return
        seen_offsets.add(key)
        rows.append(
            {
                "offset": int(offset),
                "kind": kind,
                "value": value,
                "confidence": confidence,
            }
        )

    for offset in range(0, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if 0 < word <= 120_000 and (word <= 3600 or word % 15 == 0 or word % 30 == 0):
            add_row(offset, "u32_frame_or_tick_candidate", int(word), "experimental_timing_scan")
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            value = 0.0
        if math.isfinite(value) and 0.0 < value <= 3600.0:
            rounded = round(float(value), 6)
            if abs(rounded) >= 1.0e-5 and rounded not in {1.0, 2.0, 3.0, 4.0}:
                add_row(offset, "float_seconds_or_weight_candidate", rounded, "experimental_timing_scan")
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    '_paseq_fps_candidate_context',
    'struct',
)
def _paseq_fps_candidate_value_rows(
    data: bytes,
    *,
    scan_start: int = 0,
    sample_limit: int = 262_144,
    max_rows: int = 32,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_offset = max(0, (int(scan_start) + 3) & ~3)
    scan_limit = min(len(data), sample_limit)
    if scan_offset + 4 > scan_limit:
        return rows

    integer_values = {15, 24, 30, 60}
    float_values = {15.0, 24.0, 30.0, 60.0}
    scan_confidence = "after_recovered_declaration_region" if scan_start > 0 else "aligned_4_byte_little_endian"
    for offset in range(scan_offset, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if word in integer_values:
            context = _paseq_fps_candidate_context(data, offset, "u32_fps_candidate")
            rows.append(
                {
                    "offset": int(offset),
                    "kind": "u32_fps_candidate",
                    "value": int(word),
                    "confidence": scan_confidence,
                    "value_confidence": context["value_confidence"],
                    "status": context["status"],
                    "context": context["context"],
                    "context_text": context["context_text"],
                }
            )
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            value = 0.0
        if value in float_values:
            context = _paseq_fps_candidate_context(data, offset, "float32_fps_candidate")
            rows.append(
                {
                    "offset": int(offset),
                    "kind": "float32_fps_candidate",
                    "value": int(value),
                    "confidence": scan_confidence,
                    "value_confidence": context["value_confidence"],
                    "status": context["status"],
                    "context": context["context"],
                    "context_text": context["context_text"],
                }
            )
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    '_paseq_length_prefixed_ascii',
)
def _paseq_fps_candidate_context(data: bytes, offset: int, kind: str) -> Dict[str, str]:
    if kind == "u32_fps_candidate":
        text = _paseq_length_prefixed_ascii(data, offset) or _paseq_length_prefixed_ascii(data, offset + 4)
        if text:
            return {
                "context": "length_prefixed_string_context",
                "context_text": text,
                "status": "not_bound_length_prefixed_string_context",
                "value_confidence": "blocked",
            }
    return {
        "context": "binary_scalar_context",
        "context_text": "",
        "status": "unbound_binary_scalar_candidate",
        "value_confidence": "unknown",
    }


@bind_binary_preview_globals(
    'math',
    'struct',
)
def _paseq_blend_candidate_value_rows(
    data: bytes,
    *,
    scan_start: int = 0,
    sample_limit: int = 262_144,
    max_rows: int = 32,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_offset = max(0, (int(scan_start) + 3) & ~3)
    scan_limit = min(len(data), sample_limit)
    if scan_offset + 4 > scan_limit:
        return rows
    scan_confidence = "after_recovered_declaration_region" if scan_start > 0 else "aligned_4_byte_little_endian"
    for offset in range(scan_offset, scan_limit - 3, 4):
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            continue
        if not math.isfinite(value) or abs(value) < 1.0e-5 or abs(value) > 10.0:
            continue
        rows.append(
            {
                "offset": int(offset),
                "kind": "float32_blend_candidate",
                "value": round(float(value), 6),
                "confidence": scan_confidence,
                "value_confidence": "unknown",
                "status": "unbound_binary_scalar_candidate",
                "context": "binary_scalar_context",
                "context_text": "",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    'struct',
)
def _paseq_length_prefixed_ascii(data: bytes, offset: int) -> str:
    if offset < 0 or offset + 4 > len(data):
        return ""
    length = int(struct.unpack_from("<I", data, offset)[0])
    if length <= 3 or length > 128 or offset + 4 + length > len(data):
        return ""
    raw = data[offset + 4 : offset + 4 + length]
    if any(value < 0x20 or value >= 0x7F for value in raw):
        return ""
    text = raw.decode("ascii", "ignore")
    return text if any(char.isalpha() for char in text) else ""


@bind_binary_preview_globals(
    'Mapping',
    '_paseq_blend_candidate_value_rows',
    '_paseq_blend_field_kind',
    '_paseq_fps_candidate_value_rows',
    'struct',
)
def _paseq_timing_evidence(
    data: bytes,
    timeline_fields: Sequence[Mapping[str, object]],
    *,
    sample_limit: int = 262_144,
) -> Dict[str, object]:
    fps_declarations: List[Dict[str, object]] = []
    blend_declarations: List[Dict[str, object]] = []
    declaration_region_end = 0
    for row in timeline_fields:
        if not isinstance(row, Mapping):
            continue
        descriptor_offset = int(row.get("descriptor_offset") or 0)
        if descriptor_offset > 0:
            declaration_region_end = max(declaration_region_end, descriptor_offset + 8)
        field_name = str(row.get("name") or "").strip()
        declared_type = str(row.get("declared_type") or "")
        if not declared_type:
            continue
        normalized_name = field_name.lstrip("_").lower()
        if normalized_name == "framespersecond":
            fps_declarations.append(
                {
                    "name": field_name,
                    "declared_type": declared_type,
                    "offset": int(row.get("offset") or 0),
                    "confidence": "proven",
                    "value_confidence": "unknown",
                }
            )
        if "blend" in normalized_name:
            blend_declarations.append(
                {
                    "name": field_name,
                    "declared_type": declared_type,
                    "offset": int(row.get("offset") or 0),
                    "kind": _paseq_blend_field_kind(field_name),
                    "confidence": "proven",
                    "value_confidence": "unknown",
                }
            )

    scan_limit = min(len(data), sample_limit)
    candidate_value_rows = _paseq_fps_candidate_value_rows(
        data,
        scan_start=declaration_region_end,
        sample_limit=sample_limit,
    )
    blend_candidate_value_rows = _paseq_blend_candidate_value_rows(
        data,
        scan_start=declaration_region_end,
        sample_limit=sample_limit,
    )
    integer_counts: Dict[str, int] = {str(value): 0 for value in (15, 24, 30, 60)}
    float_counts: Dict[str, int] = {str(value): 0 for value in (15, 24, 30, 60)}
    integer_values = {15, 24, 30, 60}
    float_values = {15.0, 24.0, 30.0, 60.0}
    for offset in range(0, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if word in integer_values:
            integer_counts[str(word)] += 1
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            continue
        if value in float_values:
            float_counts[str(int(value))] += 1
    candidate_total = sum(integer_counts.values()) + sum(float_counts.values())
    if fps_declarations:
        status = "source_paseq_fps_field_declared_value_offset_unmapped"
        confidence = "unknown"
        gap = "Field declaration is recovered, but current PAR schema recovery does not bind that declaration to a concrete value offset."
    else:
        status = "no_source_paseq_fps_field_declaration"
        confidence = "blocked"
        gap = "No _framesPerSecond declaration was recovered from this sequence payload."
    if blend_declarations:
        blend_status = "blend_fields_declared_value_offsets_unmapped"
        blend_confidence = "unknown"
        blend_gap = "Blend-related field declarations are recovered, but current PAR schema recovery does not bind them to concrete value offsets."
    else:
        blend_status = "no_blend_field_declaration"
        blend_confidence = "blocked"
        blend_gap = "No blend-related timeline field declaration was recovered from this sequence payload."
    return {
        "fps_field_declaration_count": len(fps_declarations),
        "fps_field_declarations": fps_declarations,
        "fps_candidate_value_counts": {
            "u32": integer_counts,
            "float32": float_counts,
        },
        "fps_candidate_value_scan": "aligned_4_byte_little_endian",
        "fps_candidate_value_region_start": int(declaration_region_end),
        "fps_candidate_value_rows": candidate_value_rows,
        "fps_candidate_value_count": int(candidate_total),
        "fps_binding_confidence": confidence,
        "fps_binding_status": status,
        "proof_gap": gap,
        "blend_field_declaration_count": len(blend_declarations),
        "blend_field_declarations": blend_declarations,
        "blend_candidate_value_scan": "aligned_4_byte_little_endian_nonzero_float32",
        "blend_candidate_value_region_start": int(declaration_region_end),
        "blend_candidate_value_rows": blend_candidate_value_rows,
        "blend_candidate_value_count": len(blend_candidate_value_rows),
        "blend_binding_confidence": blend_confidence,
        "blend_binding_status": blend_status,
        "blend_proof_gap": blend_gap,
    }


@bind_binary_preview_globals(
)
def _paseq_blend_field_kind(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "blend_field"
    if "blendingtime" in normalized or ("blend" in normalized and any(token in normalized for token in ("start", "end", "time"))):
        return "blend_window"
    if "mask" in normalized:
        return "blend_mask_or_part"
    return "blend_parameter"


@bind_binary_preview_globals(
    'Mapping',
    'PurePosixPath',
    '_normalize_model_texture_reference',
    '_paseq_reference_role',
)
def _paseq_timeline_lane_rows(
    asset_reference_rows: Sequence[Mapping[str, object]],
    *,
    max_rows: int = 96,
) -> List[Dict[str, object]]:
    lanes: List[Dict[str, object]] = []
    seen: set[str] = set()
    for row in asset_reference_rows:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace("\\", "/").strip()
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        role = _paseq_reference_role(path)
        extension = PurePosixPath(path).suffix.lower()
        lane_kind = "animation"
        if role == "effect_or_presentation":
            lane_kind = "effect"
        elif role in {"model_context", "skeleton_or_rig_context", "scene_or_descriptor_context"}:
            lane_kind = "context"
        elif role == "sequence_or_stage":
            lane_kind = "sequence"
        elif role == "related_asset":
            lane_kind = "asset"
        lanes.append(
            {
                "index": len(lanes),
                "path": path,
                "extension": extension,
                "kind": lane_kind,
                "role": role,
                "source_offset": int(row.get("offset") or 0),
                "confidence": str(row.get("confidence") or "asset_reference"),
            }
        )
        if len(lanes) >= max_rows:
            break
    return lanes


@bind_binary_preview_globals(
)
def _paseq_playback_readiness(lanes: Sequence[Mapping[str, object]], timeline_fields: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    animation_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "animation")
    effect_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "effect")
    context_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "context")
    timing_field_count = sum(1 for row in timeline_fields if str(row.get("role") or "") == "timing")
    blockers: List[str] = []
    if animation_lane_count <= 0:
        blockers.append("No referenced .paa/.hkx/.motionblending animation lane was recovered.")
    if context_lane_count <= 0:
        blockers.append("No model, skeleton, rig, or scene context lane was recovered.")
    if timing_field_count <= 0:
        blockers.append("No declared timing field was recovered; timeline timing remains candidate-only.")
    blockers.append("Runtime binding from PASEQ lanes to the 3D model preview is not implemented yet.")
    blockers.append("Exact sequence record semantics and no-edit rebuilds are not proven.")
    timing_confidence = "unknown" if timing_field_count > 0 else "blocked"
    return {
        "status": "dependency_timeline_recovered_read_only" if lanes or timeline_fields else "no_timeline_evidence_recovered",
        "ready_for_3d_playback": False,
        "game_accurate_timing": False,
        "timing_confidence": timing_confidence,
        "timing_status": "declared_timing_fields_unbound" if timing_field_count > 0 else "no_declared_timing_field",
        "animation_lane_count": int(animation_lane_count),
        "effect_lane_count": int(effect_lane_count),
        "context_lane_count": int(context_lane_count),
        "timing_field_count": int(timing_field_count),
        "blocking_gaps": blockers,
        "next_step": "Bind recovered lanes to a loaded model/skeleton preview after animation clip and PASEQ timing semantics are proven.",
    }


@bind_binary_preview_globals(
    'Counter',
    '_paseq_event_marker_rows',
    '_paseq_playback_readiness',
    '_paseq_sequence_stem',
    '_paseq_timeline_field_rows',
    '_paseq_timeline_lane_rows',
    '_paseq_timing_candidate_rows',
    '_paseq_timing_evidence',
)
def _paseq_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    string_records: Sequence[_BinarySidecarStringRecord],
    asset_reference_rows: Sequence[Mapping[str, object]],
    schema_member_rows: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    timeline_fields = _paseq_timeline_field_rows(schema_member_rows, string_records)
    event_markers = _paseq_event_marker_rows(string_records)
    timing_candidates = _paseq_timing_candidate_rows(data)
    timing_evidence = _paseq_timing_evidence(data, timeline_fields)
    lanes = _paseq_timeline_lane_rows(asset_reference_rows)
    playback_readiness = _paseq_playback_readiness(lanes, timeline_fields)
    lane_kind_counts = Counter(str(row.get("kind") or "asset") for row in lanes)
    reference_role_counts = Counter(str(row.get("role") or "related_asset") for row in lanes)
    return {
        "recognized": bool(timeline_fields or event_markers or timing_candidates or lanes),
        "format": "animation_sequence_schedule_metadata",
        "sequence_stem": _paseq_sequence_stem(virtual_path),
        "timeline": {
            "status": "read_only_recovered_timeline_evidence",
            "lane_count": len(lanes),
            "lane_kind_counts": dict(sorted(lane_kind_counts.items())),
            "reference_role_counts": dict(sorted(reference_role_counts.items())),
            "timeline_field_count": len(timeline_fields),
            "event_marker_count": len(event_markers),
            "timing_candidate_count": len(timing_candidates),
            "lanes": lanes,
            "timeline_fields": timeline_fields,
            "event_markers": event_markers,
            "timing_candidates": timing_candidates,
            "timing_evidence": timing_evidence,
        },
        "playback_readiness": playback_readiness,
        "editing_supported": False,
        "notes": [
            "PASEQ schedule evidence is read-only; offsets are decoded-payload byte offsets.",
            "Timeline lanes are recovered from asset reference strings and same payload evidence, not from proven executable game logic.",
            "3D playback remains disabled until sequence timing, clip binding, and skeleton/model application are validated.",
        ],
    }
