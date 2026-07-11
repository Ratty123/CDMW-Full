from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
    '_read_binary_sidecar_string_at',
    'struct',
)
def _binary_sidecar_offset_candidates(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_candidates: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 8:
        return rows
    for owner_offset in range(0, scan_limit - 3, 4):
        target_offset = struct.unpack_from("<I", data, owner_offset)[0]
        if target_offset <= 0 or target_offset >= len(data):
            continue
        if target_offset % 4 != 0:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "string_target" if target_string else "aligned_in_file"
        rows.append(
            {
                "owner_offset": owner_offset,
                "target_offset": target_offset,
                "patched_slot_value": f"0x{target_offset:08X}",
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_candidates:
            break
    return rows


@bind_binary_preview_globals(
    '_read_binary_sidecar_string_at',
    'struct',
)
def _binary_sidecar_count_offset_pairs(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_pairs: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    stride_candidates = (4, 8, 12, 16, 24, 32, 48, 64)
    for owner_offset in range(0, scan_limit - 7, 4):
        count = struct.unpack_from("<I", data, owner_offset)[0]
        target_offset = struct.unpack_from("<I", data, owner_offset + 4)[0]
        if count <= 0 or count > 1_000_000:
            continue
        if target_offset <= 0 or target_offset >= len(data) or target_offset % 4 != 0:
            continue
        remaining = len(data) - target_offset
        possible_strides = [stride for stride in stride_candidates if count * stride <= remaining]
        if not possible_strides:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "strong_string_table" if target_string else "candidate_count_offset_pair"
        rows.append(
            {
                "owner_offset": owner_offset,
                "count": count,
                "data_offset": target_offset,
                "possible_element_sizes": possible_strides,
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_pairs:
            break
    return rows


@bind_binary_preview_globals(
    'math',
)
def _is_binary_sidecar_plausible_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 1_000_000.0:
        return False
    if 0.0 < abs(value) < 1.0e-12:
        return False
    return True


@bind_binary_preview_globals(
    '_is_binary_sidecar_plausible_float',
    'struct',
)
def _binary_sidecar_float_rows(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    for offset in range(0, scan_limit - 15, 4):
        values = struct.unpack_from("<4f", data, offset)
        if not all(_is_binary_sidecar_plausible_float(value) for value in values):
            continue
        if all(abs(value) < 1.0e-6 for value in values):
            continue
        # Random integer tables can also look like floats. Keep these explicitly
        # experimental and only sample enough rows to guide format recovery.
        non_zero_count = sum(1 for value in values if abs(value) >= 1.0e-6)
        row_kind = "float4_candidate" if non_zero_count >= 4 else "float3_or_padded_float4_candidate"
        rows.append(
            {
                "offset": offset,
                "type": row_kind,
                "values": [round(float(value), 7) for value in values],
                "confidence": "experimental_numeric_scan",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


@bind_binary_preview_globals(
    'struct',
)
def _decode_binary_sidecar_half_float(raw_value: int) -> float:
    try:
        return float(struct.unpack("<e", int(raw_value & 0xFFFF).to_bytes(2, "little"))[0])
    except (struct.error, OverflowError, ValueError):
        return float("nan")


@bind_binary_preview_globals(
    'math',
)
def _is_binary_sidecar_plausible_half_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 16.0:
        return False
    if 0.0 < abs(value) < 1.0e-7:
        return False
    return True


@bind_binary_preview_globals(
    '_decode_binary_sidecar_half_float',
    '_is_binary_sidecar_plausible_half_float',
    'math',
    'struct',
)
def _binary_sidecar_animation_keyframe_tables(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_tables: int = 16,
    max_preview_rows: int = 8,
) -> List[Dict[str, object]]:
    """Recover read-only PAA-style keyframe table candidates."""

    row_size = 10
    component_count = 4
    minimum_rows = 4
    scan_limit = min(len(data), sample_limit)
    if scan_limit < row_size * minimum_rows:
        return []

    def read_row(offset: int) -> Optional[Tuple[int, Tuple[float, ...], float]]:
        if offset < 0 or offset + row_size > scan_limit:
            return None
        frame = struct.unpack_from("<H", data, offset)[0]
        values: List[float] = []
        for component_index in range(component_count):
            raw_value = struct.unpack_from("<H", data, offset + 2 + component_index * 2)[0]
            value = _decode_binary_sidecar_half_float(raw_value)
            if not _is_binary_sidecar_plausible_half_float(value):
                return None
            values.append(value)
        if all(abs(value) < 1.0e-7 for value in values):
            return None
        norm = math.sqrt(sum(value * value for value in values))
        return frame, tuple(values), norm

    candidates: List[Dict[str, object]] = []
    max_rows_per_candidate = 2048
    for offset in range(0, scan_limit - row_size * minimum_rows + 1, 2):
        first_rows: List[Tuple[int, Tuple[float, ...], float, int]] = []
        previous_frame: Optional[int] = None
        valid = True
        for row_index in range(minimum_rows):
            row_offset = offset + row_index * row_size
            row = read_row(row_offset)
            if row is None:
                valid = False
                break
            frame, values, norm = row
            if previous_frame is not None and not (0 < frame - previous_frame <= 256):
                valid = False
                break
            previous_frame = frame
            first_rows.append((frame, values, norm, row_offset))
        if not valid:
            continue

        rows = list(first_rows)
        while len(rows) < max_rows_per_candidate:
            row_offset = offset + len(rows) * row_size
            row = read_row(row_offset)
            if row is None:
                break
            frame, values, norm = row
            previous_frame = int(rows[-1][0])
            if not (0 < frame - previous_frame <= 256):
                break
            rows.append((frame, values, norm, row_offset))

        consecutive_steps = sum(1 for index in range(1, len(rows)) if int(rows[index][0]) - int(rows[index - 1][0]) == 1)
        normish_rows = sum(1 for _frame, _values, norm, _row_offset in rows if 0.75 <= norm <= 1.25)
        value_kind = "half_float_quaternion_or_vector4"
        if normish_rows >= max(3, int(len(rows) * 0.75)):
            value_kind = "half_float_quaternion_candidate"
        confidence = "strong_half_float_keyframe_run" if consecutive_steps >= len(rows) - 2 else "half_float_keyframe_run"
        preview_rows = [
            {
                "offset": row_offset,
                "frame": int(frame),
                "values": [round(float(value), 6) for value in values],
                "norm": round(float(norm), 6),
            }
            for frame, values, norm, row_offset in rows[:max_preview_rows]
        ]
        candidates.append(
            {
                "offset": offset,
                "row_size": row_size,
                "components": component_count,
                "row_format": "u16 frame + 4 half-float values",
                "row_count": len(rows),
                "frame_start": int(rows[0][0]),
                "frame_end": int(rows[-1][0]),
                "value_kind": value_kind,
                "confidence": confidence,
                "preview_rows": preview_rows,
            }
        )

    candidates.sort(key=lambda row: (-int(row.get("row_count") or 0), int(row.get("offset") or 0)))
    selected: List[Dict[str, object]] = []
    occupied_ranges: List[Tuple[int, int]] = []
    for candidate in candidates:
        start = int(candidate.get("offset") or 0)
        end = start + int(candidate.get("row_count") or 0) * row_size
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_ranges):
            continue
        selected.append(candidate)
        occupied_ranges.append((start, end))
        if len(selected) >= max_tables:
            break
    selected.sort(key=lambda row: int(row.get("offset") or 0))
    return selected


@bind_binary_preview_globals(
    '_STRUCTURED_BINARY_IDENTIFIER_RE',
)
def _looks_like_binary_sidecar_declared_type(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 96:
        return False
    if text.startswith("_") or "/" in text or "\\" in text or "." in text or " " in text:
        return False
    if not _STRUCTURED_BINARY_IDENTIFIER_RE.fullmatch(text):
        return False
    return any(character.isalpha() for character in text)


@bind_binary_preview_globals(
    '_BINARY_SIDECAR_PRIMITIVE_TYPES',
    '_BINARY_SIDECAR_STRING_TYPES',
)
def _binary_sidecar_descriptor_likely_kind(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> Tuple[str, str, str]:
    normalized_name = str(member_name or "").strip().lstrip("_").lower()
    normalized_type = str(declared_type or "").strip().lower()
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else 0
    flags_word = int(descriptor_words[2]) if len(descriptor_words) > 2 else 0

    is_array = (
        type_code in {3, 10}
        or bool(flags_word & 0x1000)
        or normalized_name.endswith(("list", "array"))
        or any(token in normalized_name for token in ("list", "container", "filenames", "triangles", "phases"))
    )
    array_status = "array_or_table" if is_array else "single_value"

    if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "path" in normalized_type:
        reference_status = "string_reference" if "path" in normalized_type else "string"
        likely_kind = "string_array" if is_array else "string"
    elif "reflectobjectptr" in normalized_type or normalized_type.endswith("ptr"):
        reference_status = "object_reference"
        likely_kind = "object_reference_array" if is_array else "object_reference"
    elif "reflectobject" in normalized_type:
        reference_status = "object_reference"
        likely_kind = "object_value_or_reference"
    elif type_code == 2:
        reference_status = "type_or_enum_reference"
        likely_kind = "enum_or_flags"
    elif normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES:
        reference_status = "value"
        likely_kind = "numeric_array" if is_array else ("bool" if normalized_type == "bool" else "numeric")
    elif element_size in {1, 2, 4, 8, 12, 16} and type_code == 0:
        reference_status = "value"
        likely_kind = "numeric_or_packed_value"
    else:
        reference_status = "type_or_class_reference"
        likely_kind = "array_or_table" if is_array else "typed_value"

    return likely_kind, array_status, reference_status


@bind_binary_preview_globals(
    '_BINARY_SIDECAR_KNOWN_TYPE_CODES',
    '_BINARY_SIDECAR_PRIMITIVE_TYPES',
    '_BINARY_SIDECAR_STRING_TYPES',
    '_looks_like_binary_sidecar_declared_type',
)
def _binary_sidecar_descriptor_confidence(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> str:
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else -1
    normalized_type = str(declared_type or "").strip().lower()
    if not str(member_name or "").startswith("_"):
        return "low"
    if type_code in _BINARY_SIDECAR_KNOWN_TYPE_CODES:
        if normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES and element_size in {1, 2, 4, 8, 12, 16}:
            return "strong_length_prefixed_member_declaration"
        if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "reflectobject" in normalized_type:
            return "strong_length_prefixed_member_declaration"
        if type_code == 2 and _looks_like_binary_sidecar_declared_type(declared_type):
            return "strong_length_prefixed_member_declaration"
        return "length_prefixed_member_declaration"
    return "experimental_unknown_descriptor"


@bind_binary_preview_globals(
    '_BINARY_SIDECAR_DECL_IDENTIFIER_RE',
    '_BINARY_SIDECAR_KNOWN_TYPE_CODES',
    '_BINARY_SIDECAR_PRIMITIVE_TYPES',
    '_BINARY_SIDECAR_STRING_TYPES',
    '_binary_sidecar_descriptor_confidence',
    '_binary_sidecar_descriptor_likely_kind',
    '_binary_sidecar_group_func_for_extension',
    '_looks_like_binary_sidecar_declared_type',
    '_looks_like_structured_field_name',
    'hashlib',
    'struct',
)
def _binary_sidecar_schema_declarations(
    data: bytes,
    extension: str,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 512,
) -> Dict[str, object]:
    scan_limit = min(len(data), sample_limit)
    normalized_extension = str(extension or "").strip().lower()
    field_group_func = _binary_sidecar_group_func_for_extension(normalized_extension)
    rows: List[Dict[str, object]] = []
    seen_row_keys: set[Tuple[int, str, str]] = set()
    class_candidates: List[Dict[str, object]] = []
    seen_class_names: set[str] = set()

    for match in _BINARY_SIDECAR_DECL_IDENTIFIER_RE.finditer(data[:scan_limit]):
        name_offset = match.start()
        name = match.group().decode("ascii", errors="ignore")
        if name_offset < 4:
            continue
        try:
            name_length = struct.unpack_from("<I", data, name_offset - 4)[0]
        except struct.error:
            continue
        if name_length != len(name):
            continue

        if (
            not name.startswith("_")
            and len(class_candidates) < 24
            and _looks_like_binary_sidecar_declared_type(name)
            and name.lower() not in _BINARY_SIDECAR_PRIMITIVE_TYPES
            and name.lower() not in _BINARY_SIDECAR_STRING_TYPES
            and name not in seen_class_names
        ):
            seen_class_names.add(name)
            class_candidates.append(
                {
                    "offset": name_offset,
                    "name": name,
                    "confidence": "length_prefixed_type_or_class_name",
                }
            )

        if not name.startswith("_") or not _looks_like_structured_field_name(name):
            continue
        type_length_offset = name_offset + len(name)
        if type_length_offset + 4 > scan_limit:
            continue
        try:
            type_length = struct.unpack_from("<I", data, type_length_offset)[0]
        except struct.error:
            continue
        if type_length < 3 or type_length > 96:
            continue
        type_offset = type_length_offset + 4
        descriptor_offset = type_offset + type_length
        if descriptor_offset + 8 > scan_limit:
            continue
        declared_type_bytes = data[type_offset:descriptor_offset]
        if not _BINARY_SIDECAR_DECL_IDENTIFIER_RE.fullmatch(declared_type_bytes):
            continue
        declared_type = declared_type_bytes.decode("ascii", errors="ignore")
        if not _looks_like_binary_sidecar_declared_type(declared_type):
            continue
        descriptor_bytes = data[descriptor_offset:descriptor_offset + 8]
        descriptor_words = struct.unpack_from("<4H", descriptor_bytes, 0)
        if descriptor_words[0] > 64 or descriptor_words[1] > 256:
            continue
        row_key = (name_offset, name, declared_type)
        if row_key in seen_row_keys:
            continue
        seen_row_keys.add(row_key)
        likely_kind, array_status, reference_status = _binary_sidecar_descriptor_likely_kind(
            name,
            declared_type,
            descriptor_words,
        )
        rows.append(
            {
                "declaration_offset": name_offset - 4,
                "name_offset": name_offset,
                "name": name,
                "declared_type": declared_type,
                "type_offset": type_offset,
                "descriptor_offset": descriptor_offset,
                "descriptor_hex": descriptor_bytes.hex(" ").upper(),
                "descriptor_words_le_u16": [int(value) for value in descriptor_words],
                "type_code": int(descriptor_words[0]),
                "element_size": int(descriptor_words[1]),
                "descriptor_flags_hex": f"0x{int(descriptor_words[2]):04X}{int(descriptor_words[3]):04X}",
                "likely_kind": likely_kind,
                "array_status": array_status,
                "reference_status": reference_status,
                "group": field_group_func(name),
                "confidence": _binary_sidecar_descriptor_confidence(name, declared_type, descriptor_words),
                "edit_status": "read_only_declaration_only",
            }
        )
        if len(rows) >= max_rows:
            break

    signature_source = "\n".join(
        f"{row['name']}:{row['declared_type']}:{row['descriptor_hex']}"
        for row in rows
    )
    layout_signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:16] if signature_source else ""
    declaration_end = 0
    if rows:
        declaration_end = max(int(row.get("descriptor_offset") or 0) + 8 for row in rows)
        declaration_end = min(len(data), (declaration_end + 3) & ~3)
    unusual_rows = [
        row
        for row in rows
        if int(row.get("type_code") or 0) not in _BINARY_SIDECAR_KNOWN_TYPE_CODES
        or str(row.get("confidence") or "").startswith("experimental")
    ]

    return {
        "status": "experimental_read_only_declaration_recovery",
        "declaration_count": len(rows),
        "unique_member_count": len({str(row.get("name") or "") for row in rows}),
        "layout_signature": layout_signature,
        "root_or_class_candidates": class_candidates,
        "declaration_region": {
            "start_offset": int(rows[0]["declaration_offset"]) if rows else 0,
            "end_offset": declaration_end,
            "candidate_value_region_start": declaration_end,
            "confidence": "declaration_end_heuristic" if rows else "no_declarations",
        },
        "declared_member_rows": rows,
        "unknown_descriptor_rows": unusual_rows[:64],
    }


@bind_binary_preview_globals(
    'Mapping',
    'defaultdict',
)
def _build_grouped_schema_declaration_lines(
    declaration_rows: Sequence[Mapping[str, object]],
    *,
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in declaration_rows:
        if not isinstance(row, Mapping):
            continue
        group = str(row.get("group") or "Misc").strip() or "Misc"
        grouped[group].append(row)

    lines: List[str] = []
    ordered_sections = list(section_order) + [
        section_name
        for section_name in sorted(grouped, key=str.casefold)
        if section_name not in section_order
    ]
    for section_name in ordered_sections:
        rows = grouped.get(section_name, [])
        if not rows:
            continue
        lines.extend(["", f"{section_name} declared fields ({len(rows)})"])
        for row in rows[:per_section_limit]:
            name = str(row.get("name") or "").strip()
            declared_type = str(row.get("declared_type") or "").strip()
            likely_kind = str(row.get("likely_kind") or "field").strip()
            array_status = str(row.get("array_status") or "").strip()
            descriptor = str(row.get("descriptor_hex") or "").strip()
            array_suffix = ", array" if array_status and array_status != "single_value" else ""
            lines.append(
                f"  [{likely_kind}{array_suffix}] {name}: {declared_type} "
                f"@0x{int(row.get('name_offset') or 0):X} desc={descriptor}"
            )
        if len(rows) > per_section_limit:
            lines.append(f"  ... {len(rows) - per_section_limit} more")
    return lines


@bind_binary_preview_globals(
    '_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS',
)
def _binary_sidecar_container_summary(data: bytes, extension: str) -> Dict[str, object]:
    head4 = data[:4]
    magic_ascii = "".join(chr(value) if 32 <= value <= 126 else "." for value in head4)
    normalized_extension = str(extension or "").strip().lower()
    container: Dict[str, object] = {
        "magic_ascii": magic_ascii,
        "magic_hex": head4.hex(" ").upper(),
        "recognized_family": "unknown",
    }
    if head4 == b"PAR ":
        container["recognized_family"] = "PAR"
        container["note"] = "PAR-family binary. Current decode is read-only and schema-recovery oriented."
    elif head4 == b"PARC":
        container["recognized_family"] = "PARC"
        container["note"] = "PARC structured container. Current decode is read-only and schema-recovery oriented."
    elif normalized_extension == ".meshinfo":
        container["note"] = "MeshInfo sidecar without a currently proven top-level magic."
    elif normalized_extension == ".motionblending":
        container["note"] = "Motion-blending sidecar without a currently proven top-level magic."
    elif normalized_extension == ".paa_metabin":
        container["note"] = "PAA animation metadata sidecar. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".pappt":
        container["note"] = "Part-prefab table metadata. Current decode is read-only and used for part/model relationship evidence."
    elif normalized_extension == ".pamhc":
        container["note"] = "Model-property header metadata. Current decode is read-only and used for material/model relationship evidence."
    elif normalized_extension == ".paccd":
        container["recognized_family"] = "PACCD_CUSTOMIZATION"
        container["note"] = "Character customization byte table. Current decode exposes compact/extended slot rows as read-only slider/palette evidence."
    elif normalized_extension == ".papr":
        container["note"] = "Animation constraint metadata. Current decode is read-only and schema-recovery oriented."
    elif normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        container["note"] = "Animation schedule/sequence metadata. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".seqmt":
        if head4 == b"DDS!":
            container["recognized_family"] = "DDS_SEQUENCE_TEXTURE"
            container["note"] = "SEQMT DDS! sequence texture metadata. Current decode is read-only and exposes atlas/frame-table evidence."
        else:
            container["note"] = "SEQMT sequence texture metadata. Current decode is read-only and used for timeline/material relationship evidence."
    return container


@bind_binary_preview_globals(
    '_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS',
)
def _binary_sidecar_kind_label(extension: str) -> str:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return "MeshInfo"
    if normalized_extension == ".motionblending":
        return "Motion Blending"
    if normalized_extension == ".paa":
        return "PAA Animation Clip"
    if normalized_extension == ".paa_metabin":
        return "PAA Animation Metadata"
    if normalized_extension == ".pappt":
        return "Part Prefab Table"
    if normalized_extension == ".pamhc":
        return "Model Property Header"
    if normalized_extension == ".paccd":
        return "Character Customization Data"
    if normalized_extension == ".papr":
        return "Animation Constraint"
    if normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        return "Animation Schedule"
    if normalized_extension == ".seqmt":
        return "SEQMT Sequence Texture Metadata"
    return normalized_extension.lstrip(".").upper() or "Binary Sidecar"


@bind_binary_preview_globals(
    '_find_archive_model_related_entries',
    'build_archive_related_file_references',
    'build_archive_relationship_references',
    'merge_archive_reference_rows',
)
def _build_binary_sidecar_related_references(
    source_entry: Optional[ArchiveEntry],
    *,
    asset_references: Sequence[str],
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    if source_entry is None:
        return ()
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if archive_entries_by_basename is not None
        else ()
    )
    explicit_references = build_archive_related_file_references(
        source_entry,
        explicit_reference_names=asset_references,
        companion_entries=companion_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    graph_references = build_archive_relationship_references(
        source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return merge_archive_reference_rows(explicit_references, graph_references)


@bind_binary_preview_globals(
)
def _binary_sidecar_reference_document_rows(
    references: Sequence[ArchiveModelTextureReference],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for reference in references:
        rows.append(
            {
                "reference_name": reference.reference_name,
                "semantic_label": reference.semantic_label,
                "resolution_status": reference.resolution_status,
                "resolved_archive_path": reference.resolved_archive_path,
                "resolved_package_label": reference.resolved_package_label,
                "reference_kind": reference.reference_kind,
                "relation_group": reference.relation_group,
                "relation_confidence": reference.relation_confidence,
                "relation_reason": reference.relation_reason,
                "usage_count": reference.usage_count,
            }
        )
    return rows
