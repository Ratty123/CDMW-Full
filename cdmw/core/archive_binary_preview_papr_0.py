from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
)
def _papr_constraint_string_role(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = value.lower()
    if "local_euler" in normalized or "local_quat" in normalized or "local_position" in normalized:
        if normalized.startswith(("amin", "amax")) or "amin(" in normalized or "amax(" in normalized:
            return "limit_expression"
        return "driver_expression"
    if normalized.startswith(("amin", "amax")):
        return "limit_expression"
    if value.startswith("P_") or normalized.startswith("p_bip"):
        return "parent_bone_reference"
    if (
        "bip01" in normalized
        or normalized.startswith("b_")
        or normalized.startswith("bone")
        or normalized.endswith("_dummy")
        or "_dummy" in normalized
        or normalized.endswith("_sub")
    ):
        if "_dummy" in normalized or normalized.endswith("_sub"):
            return "helper_bone_reference"
        return "bone_reference"
    return ""


@bind_binary_preview_globals(
    '_PAPR_EXPRESSION_CHANNEL_RE',
    '_PAPR_EXPRESSION_NUMBER_RE',
    '_PAPR_LIMIT_OPERATOR_RE',
    '_papr_constraint_expression_numeric_roles',
    '_papr_constraint_expression_shape',
    '_papr_constraint_expression_syntax_signature',
)
def _papr_constraint_expression_evidence(expression: str) -> Dict[str, object]:
    text = str(expression or "")
    channels = tuple(match.group(0) for match in _PAPR_EXPRESSION_CHANNEL_RE.finditer(text))
    limit_operators = tuple(match.group(0).lower() for match in _PAPR_LIMIT_OPERATOR_RE.finditer(text))
    numeric_values = tuple(match.group(0) for match in _PAPR_EXPRESSION_NUMBER_RE.finditer(text))
    numeric_roles = _papr_constraint_expression_numeric_roles(text)
    shape = _papr_constraint_expression_shape(
        text,
        channels=channels,
        limit_operators=limit_operators,
        numeric_values=numeric_values,
    )
    syntax_signature = _papr_constraint_expression_syntax_signature(
        shape=shape,
        channels=channels,
        limit_operators=limit_operators,
        numeric_roles=numeric_roles,
    )
    return {
        "expression_channels": channels,
        "expression_channel_confidence": "proven" if channels else "unknown",
        "limit_operators": limit_operators,
        "limit_operator_confidence": "proven" if limit_operators else "unknown",
        "expression_numeric_values": numeric_values,
        "expression_numeric_value_confidence": "proven" if numeric_values else "unknown",
        "expression_numeric_roles": numeric_roles,
        "expression_numeric_role_confidence": "inferred_readable_expression_syntax" if numeric_roles else "unknown",
        "expression_shape": shape,
        "expression_syntax_signature": syntax_signature,
        "expression_shape_confidence": "inferred_readable_expression_syntax",
        "expression_shape_status": "solver_semantics_unknown",
        "expression_semantics_confidence": "unknown",
    }


@bind_binary_preview_globals(
)
def _papr_constraint_expression_syntax_signature(
    *,
    shape: str,
    channels: Sequence[str],
    limit_operators: Sequence[str],
    numeric_roles: Sequence[str],
) -> str:
    channel_text = ">".join(str(value) for value in channels if str(value)) or "none"
    limit_text = ">".join(str(value) for value in limit_operators if str(value)) or "none"
    numeric_role_text = ">".join(str(value) for value in numeric_roles if str(value)) or "none"
    return (
        f"shape={shape or 'unknown'}|channels={channel_text}|"
        f"limits={limit_text}|numeric_roles={numeric_role_text}"
    )


@bind_binary_preview_globals(
    '_PAPR_ABS_OPERATOR_RE',
)
def _papr_constraint_expression_shape(
    expression: str,
    *,
    channels: Sequence[str],
    limit_operators: Sequence[str],
    numeric_values: Sequence[str],
) -> str:
    text = str(expression or "")
    has_channel = bool(channels)
    has_limit = bool(limit_operators)
    has_number = bool(numeric_values)
    has_abs = bool(_PAPR_ABS_OPERATOR_RE.search(text))
    has_arithmetic = any(operator in text for operator in ("*", "+", "-", "/"))
    if has_limit:
        if has_abs and has_channel:
            return "limit_absolute_channel_transform_candidate"
        if has_channel and has_number:
            return "limit_linear_channel_transform_candidate"
        if has_channel:
            return "limit_channel_expression_candidate"
        return "limit_expression_candidate"
    if has_abs and has_channel:
        return "absolute_channel_transform_candidate"
    if has_channel and has_number and has_arithmetic:
        return "linear_channel_transform_candidate"
    if has_channel:
        return "channel_reference_expression_candidate"
    return "opaque_expression_candidate"


@bind_binary_preview_globals(
    '_PAPR_EXPRESSION_NUMBER_RE',
    '_papr_limit_tail_start',
    '_previous_non_space',
)
def _papr_constraint_expression_numeric_roles(expression: str) -> Tuple[str, ...]:
    text = str(expression or "")
    limit_tail_start = _papr_limit_tail_start(text)
    roles: List[str] = []
    for match in _PAPR_EXPRESSION_NUMBER_RE.finditer(text):
        previous = _previous_non_space(text, match.start())
        if limit_tail_start > 0 and match.start() >= limit_tail_start:
            role = "limit_argument"
        elif previous == "*":
            role = "channel_coefficient"
        elif previous == "/":
            role = "channel_divisor"
        elif previous in {"+", "-"}:
            role = "additive_offset"
        else:
            role = "numeric_constant"
        roles.append(role)
    return tuple(roles)


@bind_binary_preview_globals(
    '_PAPR_LIMIT_OPERATOR_RE',
)
def _papr_limit_tail_start(expression: str) -> int:
    match = _PAPR_LIMIT_OPERATOR_RE.search(expression)
    if match is None:
        return 0
    open_index = expression.find("(", match.end())
    if open_index < 0:
        return 0
    depth = 0
    for index in range(open_index, len(expression)):
        char = expression[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return 0


@bind_binary_preview_globals(
)
def _previous_non_space(text: str, offset: int) -> str:
    for index in range(max(0, offset) - 1, -1, -1):
        char = text[index]
        if not char.isspace():
            return char
    return ""


@bind_binary_preview_globals(
    'Counter',
)
def _papr_constraint_expression_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    role_counts: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()
    limit_operator_counts: Counter[str] = Counter()
    numeric_role_counts: Counter[str] = Counter()
    syntax_signature_counts: Counter[str] = Counter()
    numeric_value_count = 0
    numeric_value_row_count = 0
    for row in candidates:
        role = str(row.get("expression_role") or "")
        if role:
            role_counts[role] += 1
        shape = str(row.get("expression_shape") or "")
        if shape:
            shape_counts[shape] += 1
        for channel in row.get("expression_channels") or ():
            channel_counts[str(channel)] += 1
        for operator in row.get("limit_operators") or ():
            limit_operator_counts[str(operator)] += 1
        for numeric_role in row.get("expression_numeric_roles") or ():
            numeric_role_counts[str(numeric_role)] += 1
        syntax_signature = str(row.get("expression_syntax_signature") or "")
        if syntax_signature:
            signature_role = role or "expression"
            syntax_signature_counts[f"role={signature_role}|{syntax_signature}"] += 1
        numeric_values = row.get("expression_numeric_values") or ()
        if numeric_values:
            numeric_value_row_count += 1
            numeric_value_count += len(tuple(numeric_values))
    return {
        "status": "readable_expression_tokens_solver_semantics_unknown",
        "token_confidence": "proven",
        "shape_confidence": "inferred_readable_expression_syntax",
        "semantics_confidence": "unknown",
        "expression_role_counts": dict(sorted(role_counts.items())),
        "shape_counts": dict(sorted(shape_counts.items())),
        "channel_counts": dict(sorted(channel_counts.items())),
        "limit_operator_counts": dict(sorted(limit_operator_counts.items())),
        "numeric_role_counts": dict(sorted(numeric_role_counts.items())),
        "syntax_signature_counts": dict(sorted(syntax_signature_counts.items())),
        "numeric_value_row_count": numeric_value_row_count,
        "numeric_value_count": numeric_value_count,
    }


@bind_binary_preview_globals(
)
def _papr_constraint_offset_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    return {
        "status": "readable_string_offsets_candidate_record_map",
        "offset_confidence": "proven",
        "record_confidence": "inferred_nearby_string_order",
        "candidate_count": len(candidates),
        "target_offset_count": sum(1 for row in candidates if int(row.get("target_bone_offset") or 0) > 0),
        "helper_offset_count": sum(1 for row in candidates if int(row.get("helper_bone_offset") or 0) > 0),
        "parent_offset_count": sum(1 for row in candidates if int(row.get("parent_bone_offset") or 0) > 0),
    }


@bind_binary_preview_globals(
    'Counter',
    '_papr_constraint_expression_summary',
    '_papr_constraint_offset_summary',
    '_papr_constraint_record_candidates',
    '_papr_constraint_record_layout_summary',
    '_papr_constraint_string_role',
)
def _papr_constraint_analysis_document(
    data: bytes,
    string_records: Sequence[_BinarySidecarStringRecord],
    related_references: Sequence[object],
    *,
    max_rows: int = 96,
) -> Dict[str, object]:
    role_counts: Counter[str] = Counter()
    all_evidence_rows: List[Dict[str, object]] = []
    evidence_rows: List[Dict[str, object]] = []
    for record in string_records:
        role = _papr_constraint_string_role(record.text)
        if not role:
            continue
        role_counts[role] += 1
        row = {
            "offset": int(record.offset),
            "text": record.text,
            "role": role,
            "field_confidence": "proven_readable_string",
            "role_confidence": "inferred",
        }
        all_evidence_rows.append(row)
        if len(evidence_rows) >= max_rows:
            continue
        evidence_rows.append(row)
    all_record_candidates = _papr_constraint_record_candidates(all_evidence_rows, data=data, max_rows=None)
    record_candidates = all_record_candidates[:128]

    physics_rows: List[Dict[str, object]] = []
    for reference in related_references:
        reference_kind = str(getattr(reference, "reference_kind", "") or "")
        resolved_path = str(getattr(reference, "resolved_archive_path", "") or "")
        reference_name = str(getattr(reference, "reference_name", "") or "")
        if reference_kind != "physics" and not resolved_path.lower().endswith((".hkx", ".hkt")):
            continue
        physics_rows.append(
            {
                "reference_name": reference_name,
                "resolved_archive_path": resolved_path,
                "relation_confidence": str(getattr(reference, "relation_confidence", "") or "unknown"),
                "relation_reason": str(getattr(reference, "relation_reason", "") or ""),
            }
        )

    return {
        "recognized": bool(evidence_rows or physics_rows),
        "status": "read_only_constraint_string_evidence" if evidence_rows or physics_rows else "no_constraint_evidence_recovered",
        "constraint_solving_supported": False,
        "string_evidence_count": int(sum(role_counts.values())),
        "role_counts": dict(sorted(role_counts.items())),
        "evidence_rows": evidence_rows,
        "record_candidate_count": len(all_record_candidates),
        "record_candidates": record_candidates,
        "expression_evidence": _papr_constraint_expression_summary(all_record_candidates),
        "offset_evidence": _papr_constraint_offset_summary(all_record_candidates),
        "record_layout_evidence": _papr_constraint_record_layout_summary(all_record_candidates),
        "related_physics_rows": physics_rows,
        "proof_gap": (
            "PAPR readable strings expose bone names and expression text, and nearby strings can form inferred record candidates, but current recovery does not bind records, value offsets, or solver semantics."
            if evidence_rows or physics_rows
            else "No PAPR constraint strings or physics references were recovered from this payload."
        ),
    }


@bind_binary_preview_globals(
    '_papr_candidate_field_sequence',
    '_papr_candidate_gap_evidence',
    '_papr_candidate_span',
    '_papr_constraint_expression_evidence',
)
def _papr_constraint_record_candidates(
    evidence_rows: Sequence[Mapping[str, object]],
    *,
    data: bytes = b"",
    max_rows: int | None = 64,
) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    last_parent: Mapping[str, object] | None = None
    last_bone: Mapping[str, object] | None = None
    last_helper: Mapping[str, object] | None = None
    for row in evidence_rows:
        role = str(row.get("role") or "")
        offset = int(row.get("offset") or 0)
        if role == "parent_bone_reference":
            last_parent = row
            continue
        if role == "helper_bone_reference":
            last_helper = row
            last_bone = row
            continue
        if role == "bone_reference":
            last_bone = row
            continue
        if role not in {"driver_expression", "limit_expression"}:
            continue
        target = last_bone if last_bone is not None and offset - int(last_bone.get("offset") or 0) <= 192 else None
        helper = last_helper if last_helper is not None and offset - int(last_helper.get("offset") or 0) <= 192 else None
        parent = last_parent if last_parent is not None and offset - int(last_parent.get("offset") or 0) <= 768 else None
        if target is None and parent is None:
            continue
        expression = str(row.get("text") or "")
        expression_evidence = _papr_constraint_expression_evidence(expression)
        target_offset = int(target.get("offset") or 0) if target is not None else 0
        helper_offset = int(helper.get("offset") or 0) if helper is not None else 0
        parent_offset = int(parent.get("offset") or 0) if parent is not None else 0
        span_start, span_end, span_field_count = _papr_candidate_span(row, target, helper, parent)
        field_sequence = _papr_candidate_field_sequence(
            ("parent", parent),
            ("helper", helper),
            ("target", target),
            ("expression", row),
        )
        gap_evidence = _papr_candidate_gap_evidence(
            data,
            ("parent", parent),
            ("helper", helper),
            ("target", target),
            ("expression", row),
            candidate_offset=offset,
            expression_numeric_values=expression_evidence.get("expression_numeric_values") or (),
            expression_numeric_roles=expression_evidence.get("expression_numeric_roles") or (),
        )
        candidates.append(
            {
                "offset": offset,
                "expression_offset": offset,
                "constraint_type": "local_transform_limit_candidate" if role == "limit_expression" else "driver_expression_candidate",
                "expression": expression,
                "expression_role": role,
                "target_bone": str(target.get("text") or "") if target is not None else "",
                "target_bone_offset": target_offset,
                "target_bone_delta": offset - target_offset if target_offset > 0 else 0,
                "parent_bone": str(parent.get("text") or "") if parent is not None else "",
                "parent_bone_offset": parent_offset,
                "parent_bone_delta": offset - parent_offset if parent_offset > 0 else 0,
                "helper_bone": str(helper.get("text") or "") if helper is not None else "",
                "helper_bone_offset": helper_offset,
                "helper_bone_delta": offset - helper_offset if helper_offset > 0 else 0,
                "field_confidence": "proven_readable_strings",
                "field_offset_confidence": "proven_decoded_string_offsets",
                "record_confidence": "inferred_nearby_string_order",
                "record_span_start": span_start,
                "record_span_end": span_end,
                "record_span_size": max(0, span_end - span_start),
                "record_span_field_count": span_field_count,
                "record_field_sequence": field_sequence,
                "record_field_sequence_confidence": "proven_decoded_string_offset_order",
                **gap_evidence,
                "record_layout_status": "nearby_string_span_only_value_layout_unproven",
                "solver_status": "blocked_record_layout_unproven",
                **expression_evidence,
            }
        )
        if max_rows is not None and len(candidates) >= max_rows:
            break
    return candidates


@bind_binary_preview_globals(
)
def _papr_candidate_span(*rows: Mapping[str, object] | None) -> Tuple[int, int, int]:
    spans: List[Tuple[int, int]] = []
    for row in rows:
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        spans.append((offset, offset + len(text.encode("ascii", errors="ignore")) + 1))
    if not spans:
        return 0, 0, 0
    return min(start for start, _end in spans), max(end for _start, end in spans), len(spans)


@bind_binary_preview_globals(
)
def _papr_candidate_field_sequence(*fields: Tuple[str, Mapping[str, object] | None]) -> Tuple[str, ...]:
    ordered: List[Tuple[int, int, str]] = []
    for index, (label, row) in enumerate(fields):
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        ordered.append((offset, index, label))
    ordered.sort()
    return tuple(label for _offset, _index, label in ordered)


@bind_binary_preview_globals(
)
def _papr_gap_numeric_match_signature(
    *,
    numeric_role: str,
    pair: str,
    storage: str,
    scalar_kind: str,
    value_confidence: str,
    previous_delta: int,
    next_delta: int,
) -> str:
    return (
        f"role={numeric_role}|pair={pair}|storage={storage}|scalar={scalar_kind}|"
        f"value={value_confidence}|prev={previous_delta}|next={next_delta}"
    )


@bind_binary_preview_globals(
)
def _papr_expression_numeric_entries(
    numeric_values: Sequence[object],
    numeric_roles: Sequence[object],
) -> Tuple[Tuple[str, str, float, int | None], ...]:
    roles = tuple(str(role) for role in numeric_roles or ())
    entries: List[Tuple[str, str, float, int | None]] = []
    for index, value in enumerate(numeric_values or ()):
        text = str(value)
        try:
            float_value = float(text)
        except ValueError:
            continue
        role = roles[index] if index < len(roles) and roles[index] else "numeric_constant"
        integer_value: int | None = None
        lowered = text.lower()
        if "." not in lowered and "e" not in lowered:
            try:
                integer_value = int(text, 10)
            except ValueError:
                integer_value = None
        entries.append((text, role, float_value, integer_value))
    return tuple(entries)


@bind_binary_preview_globals(
    'math',
)
def _papr_gap_numeric_matches(
    word: int,
    float_value: float,
    numeric_entries: Sequence[Tuple[str, str, float, int | None]],
    *,
    scalar_kind: str,
) -> Tuple[Dict[str, object], ...]:
    if not numeric_entries:
        return ()
    matches: List[Dict[str, object]] = []
    for numeric_text, numeric_role, numeric_value, integer_value in numeric_entries:
        if integer_value is not None and 0 <= integer_value <= 0xFFFFFFFF and word == integer_value:
            matches.append(
                {
                    "numeric_value": numeric_text,
                    "numeric_role": numeric_role,
                    "storage": "u32",
                    "scalar_kind": scalar_kind,
                    "scalar_value": int(word),
                    "value_confidence": "exact_u32_numeric_value_match_layout_unproven",
                }
            )
            continue
        if math.isfinite(float_value) and math.isclose(float_value, numeric_value, rel_tol=1.0e-6, abs_tol=1.0e-6):
            value_confidence = (
                "exact_float32_numeric_value_match_layout_unproven"
                if float_value == numeric_value
                else "approx_float32_numeric_value_match_layout_unproven"
            )
            matches.append(
                {
                    "numeric_value": numeric_text,
                    "numeric_role": numeric_role,
                    "storage": "f32",
                    "scalar_kind": scalar_kind,
                    "scalar_value": float(float_value),
                    "value_confidence": value_confidence,
                }
            )
    return tuple(matches)


@bind_binary_preview_globals(
)
def _papr_gap_class(chunk: bytes) -> str:
    if not chunk:
        return "contiguous_strings"
    if all(value == 0 for value in chunk):
        return "zero_padding"
    printable = sum(1 for value in chunk if value in (9, 10, 13) or 32 <= value <= 126)
    if printable / max(len(chunk), 1) >= 0.85:
        return "printable_ascii_gap"
    if chunk.count(0) / max(len(chunk), 1) >= 0.5:
        return "mixed_null_binary_gap"
    return "binary_gap"


@bind_binary_preview_globals(
)
def _papr_gap_status(gap_classes: Sequence[str]) -> str:
    classes = set(gap_classes)
    if not classes:
        return ""
    if {"binary_gap", "mixed_null_binary_gap"} & classes:
        return "binary_like_interfield_gap_bytes_unbound"
    if "printable_ascii_gap" in classes:
        return "printable_interfield_gap_bytes_unbound"
    if "zero_padding" in classes:
        return "zero_padding_interfield_gap_bytes_unbound"
    return "no_interfield_gap_payload"


@bind_binary_preview_globals(
    'math',
)
def _papr_gap_scalar_kind(word: int, float_value: float) -> str:
    if word == 0:
        return "zero_word"
    if word == 1:
        return "u32_bool_candidate"
    if 2 <= word <= 255:
        return "u32_u8_candidate"
    if 256 <= word <= 65535:
        return "u32_u16_candidate"
    if math.isfinite(float_value):
        absolute = abs(float_value)
        if 1.0e-6 <= absolute <= 1.0:
            return "f32_unit_candidate"
        if 1.0 < absolute <= 10.0:
            return "f32_small_candidate"
        if 10.0 < absolute <= 360.0:
            return "f32_angle_candidate"
    return "opaque_word"
